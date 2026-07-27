#!/usr/bin/env python3
"""Audit a Linux host before starting HEC-RAS Windows components under Wine."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any


REQUIRED_RAS_FILES = (
    "RasProcess.exe",
    "RasMapperLib.dll",
    "HDF.PInvoke.dll",
)
REQUIRED_RAS_DIRECTORIES = ("GDAL",)


def inspect_cpu_topology() -> dict[str, Any]:
    """Return the CPU namespace invariant required by Wine's Windows APIs."""
    if not hasattr(os, "sched_getaffinity"):
        return {
            "supported": False,
            "reported_processor_count": os.cpu_count(),
            "allowed_linux_cpu_ids": None,
            "out_of_range_cpu_ids": None,
            "wine_topology_safe": None,
            "single_cpu_fallback": None,
            "reason": "os.sched_getaffinity is unavailable on this platform",
        }

    reported_count = int(os.sysconf("SC_NPROCESSORS_ONLN"))
    allowed = sorted(os.sched_getaffinity(0))
    out_of_range = [cpu for cpu in allowed if cpu >= reported_count]
    safe_fallbacks = [cpu for cpu in allowed if cpu < reported_count]
    return {
        "supported": True,
        "reported_processor_count": reported_count,
        "allowed_linux_cpu_ids": allowed,
        "out_of_range_cpu_ids": out_of_range,
        "wine_topology_safe": bool(allowed) and not out_of_range,
        "single_cpu_fallback": safe_fallbacks[0] if safe_fallbacks else None,
        "reason": (
            "Every schedulable Linux CPU ID is a valid zero-based Windows processor index."
            if allowed and not out_of_range
            else "Wine may return a raw Linux CPU ID outside its reported Windows processor count."
        ),
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _wine_version(executable: str, env: dict[str, str]) -> tuple[bool, str | None, str | None]:
    resolved = shutil.which(executable)
    if resolved is None and Path(executable).is_file():
        resolved = str(Path(executable).resolve())
    if resolved is None:
        return False, None, f"Wine executable not found: {executable}"

    try:
        completed = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)
    version = (completed.stdout or completed.stderr).strip() or None
    return completed.returncode == 0, version, None if completed.returncode == 0 else version


def inspect_runtime(
    wine_executable: str,
    wine_prefix: str | None,
    ras_install_dir: str | None,
) -> dict[str, Any]:
    """Inspect the prefix and HEC-RAS payload without launching a GUI."""
    prefix = Path(wine_prefix).expanduser().resolve() if wine_prefix else None
    ras_dir = Path(ras_install_dir).expanduser().resolve() if ras_install_dir else None
    env = {**os.environ, "DISPLAY": "", "WINEDEBUG": "-all"}
    if prefix is not None:
        env["WINEPREFIX"] = str(prefix)

    wine_found, wine_version, wine_error = _wine_version(wine_executable, env)
    prefix_exists = bool(prefix and prefix.is_dir())
    prefix_writable = bool(prefix_exists and os.access(prefix, os.W_OK))
    drive_c_exists = bool(prefix_exists and (prefix / "drive_c").is_dir())
    dotnet_markers = []
    if prefix is not None:
        dotnet_markers = [
            prefix / "drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscorlib.dll",
            prefix / "drive_c/windows/Microsoft.NET/Framework/v4.0.30319/mscorlib.dll",
        ]

    missing_files = [] if ras_dir else list(REQUIRED_RAS_FILES)
    missing_directories = [] if ras_dir else list(REQUIRED_RAS_DIRECTORIES)
    if ras_dir is not None:
        missing_files = [name for name in REQUIRED_RAS_FILES if not (ras_dir / name).is_file()]
        missing_directories = [
            name for name in REQUIRED_RAS_DIRECTORIES if not (ras_dir / name).is_dir()
        ]

    native_hdf_dirs = []
    if ras_dir is not None and ras_dir.is_dir():
        for name in ("x64", "bin64", "bin32"):
            candidate = ras_dir / name
            if candidate.is_dir():
                native_hdf_dirs.append(name)

    ras_commander_version = _package_version("ras-commander")
    ras2cng_version = _package_version("ras2cng")
    ready = all(
        (
            wine_found,
            prefix_exists,
            prefix_writable,
            drive_c_exists,
            any(marker.is_file() for marker in dotnet_markers),
            bool(ras_dir and ras_dir.is_dir()),
            not missing_files,
            not missing_directories,
            bool(native_hdf_dirs),
        )
    )
    return {
        "wine_executable": wine_executable,
        "wine_found": wine_found,
        "wine_version": wine_version,
        "wine_error": wine_error,
        "wine_prefix": str(prefix) if prefix else None,
        "prefix_exists": prefix_exists,
        "prefix_writable": prefix_writable,
        "drive_c_exists": drive_c_exists,
        "dotnet48_marker_found": any(marker.is_file() for marker in dotnet_markers),
        "ras_install_dir": str(ras_dir) if ras_dir else None,
        "ras_install_exists": bool(ras_dir and ras_dir.is_dir()),
        "missing_ras_files": missing_files,
        "missing_ras_directories": missing_directories,
        "native_hdf_directories": native_hdf_dirs,
        "ras_commander_version": ras_commander_version,
        "ras2cng_version": ras2cng_version,
        "python_packages_ready": bool(ras_commander_version and ras2cng_version),
        "runtime_ready": ready,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    topology = inspect_cpu_topology()
    runtime = inspect_runtime(args.wine_executable, args.wine_prefix, args.ras_install_dir)
    warnings = []
    if platform.system() != "Linux":
        warnings.append("Run this preflight in the native Linux namespace that will launch Wine.")
    if topology["wine_topology_safe"] is False:
        warnings.append(
            "Unsafe sparse CPU namespace: fix the scheduler/container topology "
            "or pin the full Wine tree "
            "to single_cpu_fallback. taskset cannot renumber CPU IDs."
        )
    if runtime["runtime_ready"] is False:
        warnings.append("Wine/prefix/HEC-RAS payload is incomplete; inspect the runtime fields.")
    return {
        "schema_version": 1,
        "platform": platform.platform(),
        "cpu_topology": topology,
        "runtime": runtime,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wine-prefix", default=os.environ.get("WINEPREFIX"))
    parser.add_argument("--wine-executable", default=os.environ.get("WINE", "wine"))
    parser.add_argument("--ras-install-dir", default=os.environ.get("RAS_INSTALL_DIR"))
    parser.add_argument(
        "--require-safe-topology",
        action="store_true",
        help="Return exit code 2 when Wine's CPU namespace invariant fails.",
    )
    parser.add_argument(
        "--require-runtime",
        action="store_true",
        help="Return exit code 3 when Wine, the prefix, or HEC-RAS payload is incomplete.",
    )
    parser.add_argument(
        "--require-python-packages",
        action="store_true",
        help=(
            "Return exit code 4 unless ras-commander and ras2cng are installed "
            "in this interpreter."
        ),
    )
    args = parser.parse_args()
    report = build_report(args)
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.require_safe_topology and report["cpu_topology"]["wine_topology_safe"] is not True:
        return 2
    if args.require_runtime and report["runtime"]["runtime_ready"] is not True:
        return 3
    if (
        args.require_python_packages
        and report["runtime"]["python_packages_ready"] is not True
    ):
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
