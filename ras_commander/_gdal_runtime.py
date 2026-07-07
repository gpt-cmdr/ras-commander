"""Process-level GDAL bootstrap for HEC-RAS .NET interop."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .LoggingConfig import get_logger

logger = get_logger(__name__)

_DLL_DIRECTORY_HANDLES = []


@dataclass(frozen=True)
class GdalRuntimePaths:
    """Resolved HEC-RAS GDAL runtime paths."""

    hecras_dir: Path
    gdal_root: Path
    gdal_bin: Path
    gdal_data: Path


def _prepend_path_env(path: Path) -> None:
    path_text = str(path)
    existing = os.environ.get("PATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if any(Path(p) == path for p in parts):
        return
    os.environ["PATH"] = path_text + os.pathsep + existing if existing else path_text


def _add_dll_directory(path: Path) -> None:
    if platform.system() != "Windows":
        return

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return

    try:
        handle = add_dll_directory(str(path))
    except OSError as exc:
        logger.debug("Could not add DLL directory %s: %s", path, exc)
        return

    # Keep the handle alive for the lifetime of the process.
    _DLL_DIRECTORY_HANDLES.append(handle)


def _normalize_python_dir(path: Union[str, Path]) -> Path:
    """Return the directory RasMapper may inspect for a sibling GDAL folder."""
    path = Path(path)
    if path.suffix.lower() == ".exe":
        return path.parent
    return path


def _candidate_python_dirs(
    python_dir: Optional[Union[str, Path]] = None,
) -> list[Path]:
    """
    Return Python directories that RasMapper may treat as the app directory.

    In uv/venv environments, .NET can report the base CPython executable even
    though Python code is running from ``.venv/Scripts/python.exe``. Preparing
    both locations prevents RasMapperLib's legacy GDAL probe from surfacing a
    modal error before the managed assembly is fully loaded.
    """
    candidates: list[Path] = []

    def add(value: Optional[Union[str, Path]]) -> None:
        if value is None:
            return
        candidate = _normalize_python_dir(value)
        if candidate not in candidates:
            candidates.append(candidate)

    if python_dir is not None:
        add(python_dir)
        return candidates

    add(Path(sys.executable).parent)
    add(getattr(sys, "_base_executable", None))

    if getattr(sys, "base_prefix", None) != getattr(sys, "prefix", None):
        add(getattr(sys, "base_prefix", None))

    if getattr(sys, "base_exec_prefix", None) != getattr(sys, "exec_prefix", None):
        add(getattr(sys, "base_exec_prefix", None))

    return candidates


def resolve_hecras_gdal_paths(hecras_dir: Union[str, Path]) -> GdalRuntimePaths:
    """Resolve and validate the GDAL runtime bundled with a HEC-RAS install."""
    hecras_dir = Path(hecras_dir)
    gdal_root = hecras_dir / "GDAL"
    gdal_bin = gdal_root / "bin64"
    gdal_data = gdal_root / "common" / "data"

    if not gdal_root.is_dir():
        raise FileNotFoundError(f"HEC-RAS GDAL directory not found: {gdal_root}")
    if not gdal_bin.is_dir():
        raise FileNotFoundError(f"HEC-RAS GDAL bin64 directory not found: {gdal_bin}")
    if not gdal_data.is_dir():
        raise FileNotFoundError(f"HEC-RAS GDAL data directory not found: {gdal_data}")

    return GdalRuntimePaths(
        hecras_dir=hecras_dir,
        gdal_root=gdal_root,
        gdal_bin=gdal_bin,
        gdal_data=gdal_data,
    )


def configure_hecras_gdal_runtime(
    hecras_dir: Union[str, Path],
) -> GdalRuntimePaths:
    """
    Point the current process at HEC-RAS's bundled GDAL runtime.

    RasMapperLib and Geospatial.GDALAssist can be loaded from Python without a
    writable ``GDAL`` sibling directory next to ``python.exe`` when the process
    environment and DLL search paths are initialized first.
    """
    paths = resolve_hecras_gdal_paths(hecras_dir)

    os.environ["GDAL_DATA"] = str(paths.gdal_data)
    os.environ["PROJ_LIB"] = str(paths.gdal_data)
    os.environ.setdefault("PROJ_DATA", str(paths.gdal_data))

    _prepend_path_env(paths.hecras_dir)
    _prepend_path_env(paths.gdal_bin)
    _add_dll_directory(paths.hecras_dir)
    _add_dll_directory(paths.gdal_bin)

    if str(paths.hecras_dir) not in sys.path:
        sys.path.insert(0, str(paths.hecras_dir))

    logger.debug(
        "Configured HEC-RAS GDAL runtime: GDAL_DATA=%s, PROJ_LIB=%s, bin=%s",
        os.environ["GDAL_DATA"],
        os.environ["PROJ_LIB"],
        paths.gdal_bin,
    )
    return paths


def python_gdal_bridge_is_usable(
    python_dir: Optional[Union[str, Path]] = None,
) -> bool:
    """Return True when ``python_dir/GDAL`` looks like HEC-RAS's GDAL tree."""
    python_dir = (
        _normalize_python_dir(python_dir)
        if python_dir is not None
        else Path(sys.executable).parent
    )
    gdal_dir = python_dir / "GDAL"
    return (
        (gdal_dir / "bin64").is_dir()
        and (gdal_dir / "common" / "data").is_dir()
    )


def ensure_python_gdal_junction(
    hecras_dir: Union[str, Path],
    python_dir: Optional[Union[str, Path]] = None,
) -> bool:
    """
    Create the legacy ``python.exe`` sibling GDAL junction when explicitly used.

    New code should prefer :func:`configure_hecras_gdal_runtime`. This fallback
    remains for environments where a HEC-RAS assembly still insists on an
    application-directory ``GDAL`` folder.
    """
    if platform.system() != "Windows":
        logger.warning("GDAL junction creation is Windows-only")
        return False

    paths = resolve_hecras_gdal_paths(hecras_dir)
    python_dirs = _candidate_python_dirs(python_dir)
    if not python_dirs:
        logger.error("Could not identify a Python directory for GDAL bridge setup")
        return False

    ok = True
    for target_python_dir in python_dirs:
        gdal_junction = target_python_dir / "GDAL"

        if python_gdal_bridge_is_usable(target_python_dir):
            continue

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f'New-Item -ItemType Junction -Path "{gdal_junction}" '
                    f'-Target "{paths.gdal_root}" -Force',
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            logger.error("GDAL junction creation failed for %s: %s", gdal_junction, exc)
            ok = False
            continue

        if result.returncode == 0:
            logger.info("Created GDAL junction for HEC-RAS GDAL bridge")
            logger.debug("Created GDAL junction: %s -> %s", gdal_junction, paths.gdal_root)
            ok = python_gdal_bridge_is_usable(target_python_dir) and ok
            continue

        logger.error(
            "GDAL junction creation failed for %s: %s",
            gdal_junction,
            result.stderr.strip(),
        )
        ok = False

    return ok


def configure_rasmapper_gdal_bridge(
    hecras_dir: Union[str, Path],
    python_dir: Optional[Union[str, Path]] = None,
) -> GdalRuntimePaths:
    """
    Configure GDAL and verify the legacy Python sibling bridge for RasMapperLib.

    HEC-RAS/RasMapperLib builds may show a modal error unless a ``GDAL``
    directory is present next to the running ``python.exe``. Call this before
    loading any RasMapperLib assembly.
    """
    paths = configure_hecras_gdal_runtime(hecras_dir)
    if not ensure_python_gdal_junction(paths.hecras_dir, python_dir):
        py_dirs = _candidate_python_dirs(python_dir)
        expected = ", ".join(str(py_dir / "GDAL") for py_dir in py_dirs)
        raise RuntimeError(
            "Could not initialize the GDAL bridge required by RasMapperLib. "
            f"Expected usable GDAL directories at: {expected}."
        )
    return paths
