"""Bounded out-of-process RasMapperLib geometry operations."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from ..LoggingConfig import get_logger
from .._gdal_runtime import configure_rasmapper_gdal_bridge
from .mesh_host import (
    _bounded_run,
    _compiler_path,
    _native_wine_controller,
    _reset_wineserver,
    _sha256,
    _stream_tail,
    _to_windows_path,
    _wine_executable,
    is_wine_runtime,
)

logger = get_logger(__name__)

_SOURCE_NAME = "RasMapperGeometryHelper.cs"
_EXECUTABLE_NAME = "RasMapperGeometryHelper.exe"


def ensure_managed_geometry_host(hecras_dir: Union[str, Path]) -> Path:
    """Compile the packaged x86 geometry host once per source hash."""
    native_wine = _native_wine_controller()
    if platform.system() != "Windows" and not native_wine:
        raise RuntimeError(
            "The managed RasMapper geometry host requires Windows or a native "
            "controller process with WINEPREFIX configured."
        )

    hecras_dir = Path(hecras_dir)
    if native_wine:
        prefix = Path(os.environ["WINEPREFIX"])
        python_candidates = sorted((prefix / "drive_c").glob("Python3*"))
        python_dir = next(
            (candidate for candidate in python_candidates if candidate.is_dir()),
            None,
        )
        if python_dir is None:
            raise FileNotFoundError(
                f"No Windows Python installation was found in Wine prefix {prefix}"
            )
        if not (
            (python_dir / "GDAL" / "bin64").is_dir()
            and (python_dir / "GDAL" / "common" / "data").is_dir()
        ):
            raise RuntimeError(
                "The native Wine controller requires the qualified GDAL link "
                f"beside Windows Python: {python_dir / 'GDAL'}"
            )
        compiler = (
            prefix
            / "drive_c"
            / "windows"
            / "Microsoft.NET"
            / "Framework"
            / "v4.0.30319"
            / "csc.exe"
        )
        if not compiler.is_file():
            raise FileNotFoundError(
                f".NET Framework csc.exe was not found in Wine prefix: {compiler}"
            )
        host_dir = python_dir
    else:
        compiler = _compiler_path()
        host_dir = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))
        ) / "ras_commander" / "managed_host"
        host_dir.mkdir(parents=True, exist_ok=True)
        configure_rasmapper_gdal_bridge(hecras_dir, python_dir=host_dir)

    source = Path(__file__).with_name(_SOURCE_NAME)
    if not source.is_file():
        raise FileNotFoundError(
            f"Packaged managed geometry host source is missing: {source}"
        )

    executable = host_dir / _EXECUTABLE_NAME
    marker = executable.with_suffix(executable.suffix + ".source-sha256")
    source_hash = _sha256(source)
    if executable.is_file() and marker.is_file():
        if marker.read_text(encoding="ascii").strip() == source_hash:
            return executable

    environment = os.environ.copy()
    if is_wine_runtime():
        environment.setdefault("COMPlus_ZapDisable", "1")
    command = (
        [
            _wine_executable(),
            _to_windows_path(compiler),
            "/nologo",
            "/platform:x86",
            f"/out:{_to_windows_path(executable)}",
            _to_windows_path(source),
        ]
        if native_wine
        else [
            str(compiler),
            "/nologo",
            "/platform:x86",
            f"/out:{executable}",
            str(source),
        ]
    )
    completed = _bounded_run(command, timeout=120, environment=environment)
    if completed.returncode != 0 or not executable.is_file():
        detail = _stream_tail(completed.stderr or completed.stdout)
        raise RuntimeError(
            "Failed to compile the managed RasMapper geometry host "
            f"(exit {completed.returncode}): {detail}"
        )
    marker.write_text(source_hash, encoding="ascii")
    _reset_wineserver(environment)
    logger.info("Compiled managed RasMapper geometry host: %s", executable)
    return executable


def _run_managed_geometry_action(
    action: str,
    geom_hdf_path: Union[str, Path],
    hecras_dir: Union[str, Path],
    action_arguments: list[str],
    *,
    timeout_seconds: float,
    max_attempts: int,
) -> dict[str, Any]:
    """Run one geometry-host action with Wine-safe retries and supervision."""
    if int(max_attempts) < 1:
        raise ValueError("max_attempts must be at least 1")
    max_attempts = int(max_attempts)
    executable = ensure_managed_geometry_host(hecras_dir)
    geom_hdf_path = Path(geom_hdf_path)
    hecras_dir = Path(hecras_dir)
    environment = os.environ.copy()
    native_wine = _native_wine_controller()
    if is_wine_runtime():
        environment.setdefault("COMPlus_ZapDisable", "1")

    started = time.monotonic()
    attempt_timeout = max(1.0, float(timeout_seconds) / max_attempts)
    failed_attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        receipt_path = executable.with_name(
            f".{geom_hdf_path.name}.{action}-{uuid.uuid4().hex}.json"
        )
        progress_path = receipt_path.with_name(receipt_path.name + ".progress")
        helper_arguments = [
            _to_windows_path(executable) if native_wine else str(executable),
            action,
            _to_windows_path(hecras_dir) if native_wine else str(hecras_dir),
            _to_windows_path(geom_hdf_path) if native_wine else str(geom_hdf_path),
            _to_windows_path(receipt_path) if native_wine else str(receipt_path),
            *action_arguments,
        ]
        command = (
            [_wine_executable(), *helper_arguments]
            if native_wine
            else helper_arguments
        )
        attempt_started = time.monotonic()
        completed = None
        timed_out = False
        if native_wine:
            _reset_wineserver(environment)
        try:
            completed = _bounded_run(
                command,
                timeout=attempt_timeout,
                environment=environment,
            )
        except subprocess.TimeoutExpired:
            timed_out = True

        progress = (
            progress_path.read_text(encoding="utf-8", errors="replace")
            if progress_path.is_file()
            else ""
        )
        progress_path.unlink(missing_ok=True)
        stage_trace = [line for line in progress.splitlines() if line.strip()]
        duration = time.monotonic() - attempt_started
        if timed_out:
            receipt_path.unlink(missing_ok=True)
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": True,
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                }
            )
            continue

        assert completed is not None
        if not receipt_path.is_file():
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": False,
                    "return_code": int(completed.returncode),
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                    "stderr_tail": _stream_tail(
                        completed.stderr or completed.stdout
                    ),
                }
            )
            continue

        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        finally:
            receipt_path.unlink(missing_ok=True)
        transient_error = str(receipt.get("error") or "")
        retryable_managed_error = any(
            transient_error.startswith(prefix)
            for prefix in (
                "System.AccessViolationException:",
                "System.EntryPointNotFoundException:",
            )
        )
        if retryable_managed_error and attempt < max_attempts:
            failed_attempts.append(
                {
                    "attempt": attempt,
                    "timed_out": False,
                    "return_code": int(completed.returncode),
                    "duration_seconds": duration,
                    "stage_trace": stage_trace,
                    "managed_error": transient_error,
                    "stderr_tail": _stream_tail(completed.stderr),
                }
            )
            continue
        receipt.update(
            {
                "return_code": int(completed.returncode),
                "process_duration_seconds": duration,
                "total_duration_seconds": time.monotonic() - started,
                "attempt_count": attempt,
                "failed_attempts": failed_attempts,
                "stdout_tail": _stream_tail(completed.stdout),
                "stderr_tail": _stream_tail(completed.stderr),
                "stage_trace": stage_trace,
            }
        )
        if completed.returncode != 0 and not receipt.get("error"):
            receipt["error"] = (
                f"Managed RasMapper geometry host exited {completed.returncode}: "
                f"{receipt['stderr_tail'] or receipt['stdout_tail']}"
            )
        return receipt

    raise RuntimeError(
        "Managed RasMapper geometry host exhausted "
        f"{max_attempts} isolated attempts for '{action}': "
        f"{json.dumps(failed_attempts, sort_keys=True)}"
    )


def run_managed_geometry_association(
    geom_hdf_path: Union[str, Path],
    hecras_dir: Union[str, Path],
    associations: Mapping[str, Optional[Union[str, Path]]],
    *,
    timeout_seconds: float = 300.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Run ``SetGeometryAssociationCommand`` in the managed host."""
    native_wine = _native_wine_controller()

    def formatted(key: str) -> str:
        value = associations.get(key)
        if value is None:
            return ""
        path = Path(value)
        return _to_windows_path(path) if native_wine else str(path)

    arguments = [
        formatted("terrain_hdf_path"),
        formatted("landcover_hdf_path"),
        formatted("infiltration_hdf_path"),
        formatted("sediment_soils_hdf_path"),
    ]
    return _run_managed_geometry_action(
        "associate",
        geom_hdf_path,
        hecras_dir,
        arguments,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def run_managed_property_tables(
    geom_hdf_path: Union[str, Path],
    mesh_name: str,
    hecras_dir: Union[str, Path],
    *,
    rasmap_path: Optional[Union[str, Path]] = None,
    force: bool = True,
    complete_geometry: bool = True,
    timeout_seconds: float = 1800.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Compute one 2D flow area's property tables in the managed host."""
    rasmap_argument = ""
    if rasmap_path is not None:
        resolved_rasmap_path = Path(rasmap_path)
        rasmap_argument = (
            _to_windows_path(resolved_rasmap_path)
            if _native_wine_controller()
            else str(resolved_rasmap_path)
        )
    return _run_managed_geometry_action(
        "property-tables",
        geom_hdf_path,
        hecras_dir,
        [
            str(mesh_name),
            str(bool(force)),
            rasmap_argument,
            str(bool(complete_geometry)),
        ],
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


__all__ = [
    "ensure_managed_geometry_host",
    "run_managed_geometry_association",
    "run_managed_property_tables",
]
