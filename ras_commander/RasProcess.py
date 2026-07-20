"""
RasProcess - Wrapper for RasProcess.exe CLI automation

This module provides functionality to automate HEC-RAS mapping operations through
the undocumented RasProcess.exe command-line interface. It enables headless
generation of stored maps, preprocessing, and other RASMapper operations.

Key Features:
- Generate stored maps (WSE, Depth, Velocity, etc.) without GUI
- Support for Max/Min profiles and specific timesteps
- Automatic .rasmap modification for stored map configuration
- Georeferencing fix for StoreMap command bug
- **Linux support via Wine** (headless, no display required)

Classes:
    RasProcess: Static class for RasProcess.exe CLI operations

Note:
    RasProcess.exe is an undocumented CLI tool bundled with HEC-RAS that exposes
    RASMapper automation functionality. See rasmapper_docs/16_rasprocess_cli_reference.md
    for complete documentation.

Linux/Wine Support:
    On Linux, RasProcess.exe runs under Wine with .NET Framework 4.8.
    Requirements:
    - Wine 8.0+ (64-bit prefix)
    - winetricks: dotnet48, gdiplus, corefonts
    - HEC-RAS DLLs copied into Wine prefix (see setup_wine_environment())

    The module auto-detects Linux and wraps commands with Wine automatically.
    No code changes needed for users — just install the Wine environment.
"""

import fnmatch
import functools
import inspect
import ntpath
import os
import re
import socket
import sys
import subprocess
import tempfile
import threading
import time
import uuid
import warnings
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Union, Optional, List, Dict, Any, Tuple
from datetime import datetime
import shutil
import platform
import numpy as np
import pandas as pd


@dataclass
class ProjectionInfo:
    """
    Terrain projection information extracted from .rasmap XML.

    Attributes:
        prj_path: Path to projection file (.prj) if found, None otherwise
        terrain_path: First terrain TIF file if found, None otherwise
        terrain_paths: All terrain TIF files referenced by rasmap terrain layers
    """
    prj_path: Optional[Path]
    terrain_path: Optional[Path]
    terrain_paths: Tuple[Path, ...] = ()


@dataclass
class WineConfig:
    """
    Configuration for Wine-based execution on Linux.

    Attributes:
        wine_prefix: Path to the Wine prefix directory (WINEPREFIX)
        wine_executable: Path to the wine binary (default: 'wine')
        ras_install_dir: Path to HEC-RAS DLLs within the Wine prefix drive_c
    """
    wine_prefix: Path
    wine_executable: str = "wine"
    ras_install_dir: Optional[Path] = None


from .RasPrj import ras
from .RasMap import RasMap
from .RasBenefits import BenefitAreaConfig, RasBenefits
from .RasUtils import RasUtils
from .LoggingConfig import get_logger
from .Decorators import log_call
from ._native_helper import (
    normalize_store_map_render_mode,
    run_store_all_maps_helper,
    store_maps_runtime_provenance,
)

# Optional rasterio for georeferencing fix
try:
    import rasterio
    from rasterio.crs import CRS
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

logger = get_logger(__name__)

# Detect platform once at import time
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

_STORE_MAPS_LOCKS: Dict[str, threading.RLock] = {}
_STORE_MAPS_LOCKS_GUARD = threading.Lock()
_STORE_MAPS_LOCK_STATE = threading.local()


def _windows_extended_length_path(path: Union[str, Path]) -> str:
    """Return an extended-length path on Windows and a normal path elsewhere."""
    path_str = os.fspath(path)
    if not IS_WINDOWS or path_str.startswith("\\\\?\\"):
        return path_str

    absolute_path = ntpath.abspath(path_str)
    if absolute_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute_path[2:]
    return "\\\\?\\" + absolute_path


def _iterdir_paths(directory: Union[str, Path]) -> List[Path]:
    """List a directory while preserving normal Path values for callers."""
    directory_path = Path(directory)
    with os.scandir(_windows_extended_length_path(directory_path)) as entries:
        return [directory_path / entry.name for entry in entries]


def _glob_paths(directory: Union[str, Path], pattern: str) -> List[Path]:
    """Match direct children using extended-length-safe directory scanning."""
    return sorted(
        (
            path
            for path in _iterdir_paths(directory)
            if fnmatch.fnmatch(path.name, pattern)
        ),
        key=lambda path: path.name.casefold(),
    )


def _serialize_store_maps(func):
    """Serialize rasmap mutation for one project across threads/processes.

    ``StoreAllMaps`` temporarily edits the project's shared ``.rasmap``.  A
    re-entrant in-process lock protects threads and nested BenefitArea calls;
    an atomically created directory extends the same exclusion to other Python
    processes using the project.  A lock left by a killed process is preserved
    for diagnosis rather than guessed stale and deleted behind another host.
    """
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        ras_obj = bound.arguments.get("ras_object") or ras
        project_folder = getattr(ras_obj, "project_folder", None)
        project_name = getattr(ras_obj, "project_name", None)
        if not project_folder or not project_name:
            return func(*args, **kwargs)

        lock_dir = Path(project_folder) / f".{project_name}.storemaps.lock"
        lock_key = os.path.normcase(os.path.abspath(lock_dir))
        with _STORE_MAPS_LOCKS_GUARD:
            thread_lock = _STORE_MAPS_LOCKS.setdefault(
                lock_key,
                threading.RLock(),
            )

        timeout = max(float(bound.arguments.get("timeout", 600)), 0.0)
        deadline = time.monotonic() + timeout
        if not thread_lock.acquire(timeout=timeout):
            raise TimeoutError(
                "Timed out waiting for another StoreMaps call in this Python "
                f"process to release project {project_name!r}"
            )
        try:
            depths = getattr(_STORE_MAPS_LOCK_STATE, "depths", None)
            if depths is None:
                depths = {}
                _STORE_MAPS_LOCK_STATE.depths = depths

            depth = depths.get(lock_key, 0)
            owns_directory = depth == 0
            if owns_directory:
                while True:
                    try:
                        os.mkdir(_windows_extended_length_path(lock_dir))
                        break
                    except FileExistsError:
                        if time.monotonic() >= deadline:
                            owner_path = lock_dir / "owner.txt"
                            try:
                                owner = owner_path.read_text(
                                    encoding="utf-8",
                                ).strip()
                            except OSError:
                                owner = "owner metadata unavailable"
                            raise TimeoutError(
                                "Timed out waiting for StoreMaps project lock "
                                f"{lock_dir} ({owner}). If no mapping process is "
                                "running, remove this stale lock directory and retry."
                            )
                        time.sleep(0.1)

                owner_path = lock_dir / "owner.txt"
                try:
                    owner_path.write_text(
                        f"host={socket.gethostname()} pid={os.getpid()} "
                        f"thread={threading.get_ident()}",
                        encoding="utf-8",
                    )
                except OSError as exc:
                    logger.warning(
                        "Could not write StoreMaps lock owner metadata %s: %s",
                        owner_path,
                        exc,
                    )

            depths[lock_key] = depth + 1
            try:
                return func(*args, **kwargs)
            finally:
                remaining = depths[lock_key] - 1
                if remaining:
                    depths[lock_key] = remaining
                else:
                    depths.pop(lock_key, None)
                    if owns_directory:
                        try:
                            os.remove(
                                _windows_extended_length_path(
                                    lock_dir / "owner.txt"
                                )
                            )
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            logger.warning(
                                "Could not remove StoreMaps lock metadata %s: %s",
                                lock_dir / "owner.txt",
                                exc,
                            )
                        try:
                            os.rmdir(_windows_extended_length_path(lock_dir))
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            logger.warning(
                                "Could not release StoreMaps project lock %s: %s",
                                lock_dir,
                                exc,
                            )
        finally:
            thread_lock.release()

    return wrapper


class RasProcess:
    """
    Static class for automating HEC-RAS operations via RasProcess.exe CLI.

    This class provides methods to:
    - Find RasProcess.exe in standard HEC-RAS installation paths
    - Generate stored maps using StoreAllMaps command
    - Configure stored maps in .rasmap files
    - Fix georeferencing issues in generated TIFs
    - **Run on Linux via Wine** (auto-detected, no code changes needed)

    All methods are static and follow the ras-commander pattern of accepting
    an optional ras_object parameter for multi-project support.

    Example (Windows - unchanged):
        >>> from ras_commander import init_ras_project, RasProcess
        >>> init_ras_project("path/to/project", "7.0")
        >>> results = RasProcess.store_maps(
        ...     plan_number="01",
        ...     output_folder="Maps",
        ...     wse=True,
        ...     depth=True,
        ...     velocity=True
        ... )

    Example (Linux with Wine):
        >>> from ras_commander import init_ras_project, RasProcess
        >>> # Auto-detects Linux and uses default Wine prefix
        >>> init_ras_project("/path/to/project", "7.0")
        >>> results = RasProcess.store_maps(plan_number="01")
        >>>
        >>> # Or configure Wine explicitly:
        >>> RasProcess.configure_wine(
        ...     wine_prefix="/opt/hecras-wine",
        ...     ras_install_dir="/opt/hecras-wine/drive_c/HEC-RAS/6.6"
        ... )
    """

    @staticmethod
    @log_call
    def get_store_maps_runtime_provenance(ras_object=None) -> Dict[str, Any]:
        """Return content identities for the actual StoreMaps runtime."""

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        hecras_dir = Path(str(ras_obj.ras_exe_path)).parent
        if not hecras_dir.is_dir():
            raise FileNotFoundError(f"HEC-RAS directory not found: {hecras_dir}")
        return store_maps_runtime_provenance(hecras_dir)

    # Map type definitions: (xml_name, display_name, needs_profile)
    MAP_TYPES = {
        'wse': ('elevation', 'WSE', True),
        'depth': ('depth', 'Depth', True),
        'velocity': ('velocity', 'Velocity', True),
        'froude': ('froude', 'Froude', True),
        'shear_stress': ('Shear', 'Shear Stress', True),
        'depth_x_velocity': ('depth and velocity', 'D * V', True),
        'depth_x_velocity_sq': ('depth and velocity squared', 'D * V^2', True),
        'flow': ('flow', 'Flow', True),
        # XML names verified against the RasMapperLib.dll MapTypes table
        # (identical in 6.6 and 7.0.1): "arrival time" (with space) and
        # "fraction inundated". These types use the ArrivalDepth threshold
        # attribute and label outputs "(<depth><unit> hrs)" instead of the
        # profile name.
        'arrival_time': ('arrival time', 'Arrival Time', False),
        'duration': ('duration', 'Duration', False),
        'percent_inundated': ('fraction inundated', 'Percent Time Inundated', False),
        # NOTE: RasMapperLib has no 'recession' MapType (verified 6.6/7.0.1).
        # Recession time = arrival_time + duration; derive it downstream.
        'inundation_boundary': ('depth', 'Inundation Boundary', False),
    }

    # Standard HEC-RAS installation paths (Windows)
    RAS_INSTALL_PATHS = [
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.6",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.5",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.4.1",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.4",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.3.1",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.3",
        r"C:\Program Files\HEC\HEC-RAS\6.6",
        r"C:\Program Files\HEC\HEC-RAS\6.5",
    ]

    # Default Wine prefix paths to search on Linux
    WINE_PREFIX_PATHS = [
        "/opt/hecras-wine",
        os.path.expanduser("~/.wine"),
        os.path.expanduser("~/hecras-wine"),
    ]

    # Wine configuration (class-level, set via configure_wine())
    _wine_config: Optional[WineConfig] = None

    # ------------------------------------------------------------------ #
    #  Wine / Linux Support Methods
    # ------------------------------------------------------------------ #

    @staticmethod
    def configure_wine(
        wine_prefix: Union[str, Path] = None,
        wine_executable: str = "wine",
        ras_install_dir: Union[str, Path] = None,
    ) -> WineConfig:
        """
        Configure Wine environment for Linux execution.

        Call this once before using RasProcess on Linux if the defaults
        don't match your setup. If not called, auto-detection is used.

        Args:
            wine_prefix: Path to WINEPREFIX (default: auto-detect from WINE_PREFIX_PATHS)
            wine_executable: Wine binary name or path used to launch
                            Windows executables under Wine. Auxiliary tools
                            such as ``winepath`` are resolved automatically.
            ras_install_dir: Path to directory containing RasProcess.exe and DLLs.
                           Can be a Linux path (under drive_c/) or left None for auto-detect.

        Returns:
            WineConfig instance that was set.

        Example:
            >>> RasProcess.configure_wine(
            ...     wine_prefix="/opt/hecras-wine",
            ...     ras_install_dir="/opt/hecras-wine/drive_c/HEC-RAS"
            ... )
        """
        if wine_prefix is None:
            wine_prefix = RasProcess._find_wine_prefix()
            if wine_prefix is None:
                raise FileNotFoundError(
                    "No Wine prefix found. Searched: " +
                    ", ".join(RasProcess.WINE_PREFIX_PATHS) +
                    ". Set WINEPREFIX or call configure_wine(wine_prefix=...)"
                )

        wine_prefix = Path(wine_prefix)
        if not wine_prefix.exists():
            raise FileNotFoundError(f"Wine prefix not found: {wine_prefix}")

        ras_dir = Path(ras_install_dir) if ras_install_dir else None

        config = WineConfig(
            wine_prefix=wine_prefix,
            wine_executable=wine_executable,
            ras_install_dir=ras_dir,
        )
        RasProcess._wine_config = config
        ras_dir_state = "configured" if ras_dir is not None else "not configured"
        logger.info(
            "Wine configured for RasProcess: executable=%s, ras_dir=%s",
            wine_executable,
            ras_dir_state,
        )
        logger.debug("Wine configuration paths: prefix=%s, ras_dir=%s", wine_prefix, ras_dir)
        return config

    @staticmethod
    def _find_wine_prefix() -> Optional[Path]:
        """Find an existing Wine prefix from standard locations or WINEPREFIX env."""
        # Check environment variable first
        env_prefix = os.environ.get("WINEPREFIX")
        if env_prefix and Path(env_prefix).exists():
            return Path(env_prefix)

        # Check standard paths
        for prefix_path in RasProcess.WINE_PREFIX_PATHS:
            p = Path(prefix_path)
            if p.exists() and (p / "drive_c").exists():
                return p

        return None

    @staticmethod
    def _get_wine_config() -> Optional[WineConfig]:
        """Get Wine config, auto-detecting if not explicitly configured."""
        if RasProcess._wine_config is not None:
            return RasProcess._wine_config

        if not IS_LINUX:
            return None

        # Auto-detect
        prefix = RasProcess._find_wine_prefix()
        if prefix is None:
            return None

        config = WineConfig(wine_prefix=prefix)
        RasProcess._wine_config = config
        logger.debug(f"Auto-detected Wine prefix: {prefix}")
        return config

    @staticmethod
    def _build_wine_env(
        wine_config: WineConfig = None,
        include_winedebug: bool = True,
    ) -> Dict[str, str]:
        """Build environment variables for Wine subprocess execution."""
        config = wine_config or RasProcess._get_wine_config()

        env = {**os.environ, "DISPLAY": ""}
        if config and config.wine_prefix:
            env["WINEPREFIX"] = str(config.wine_prefix)
        if include_winedebug:
            env["WINEDEBUG"] = "-all"

        return env

    @staticmethod
    def _resolve_wine_tool_executable(
        tool_name: str,
        wine_config: WineConfig = None,
    ) -> str:
        """
        Resolve an auxiliary Wine tool for the configured Wine install.

        For the main Wine runner, returns the configured ``wine_executable``.
        For tools like ``winepath``, prefer a sibling binary next to a
        path-based executable (for example ``/opt/wine/bin/wine64`` ->
        ``/opt/wine/bin/winepath``). Otherwise fall back to the generic tool
        name on ``PATH``.
        """
        config = wine_config or RasProcess._get_wine_config()
        if config is None:
            return tool_name

        if tool_name == "wine":
            return str(config.wine_executable)

        wine_executable = Path(str(config.wine_executable))
        if wine_executable.parent != Path(".") or wine_executable.is_absolute():
            sibling_tool = wine_executable.with_name(tool_name)
            if sibling_tool.exists():
                return str(sibling_tool)

        return tool_name

    @staticmethod
    def _linux_to_wine_path(linux_path: Union[str, Path]) -> str:
        """
        Convert a Linux filesystem path to a Wine/Windows path.

        Examples:
            /opt/hecras-wine/drive_c/projects/test → C:\\projects\\test
            /home/user/.wine/drive_c/HEC-RAS/6.6  → C:\\HEC-RAS\\6.6

        Args:
            linux_path: Path on the Linux filesystem (must be under drive_c/)

        Returns:
            Windows-style path string for use with Wine
        """
        linux_path = Path(linux_path).resolve()
        path_str = str(linux_path)

        # Find drive_c in the path
        drive_c_marker = "/drive_c/"
        idx = path_str.find(drive_c_marker)
        if idx == -1:
            # Try to use winepath if available
            wine_config = RasProcess._get_wine_config()
            if wine_config:
                try:
                    winepath_executable = (
                        RasProcess._resolve_wine_tool_executable(
                            "winepath",
                            wine_config,
                        )
                    )
                    result = subprocess.run(
                        [winepath_executable, "-w", str(linux_path)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=RasProcess._build_wine_env(
                            wine_config,
                            include_winedebug=False,
                        ),
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    pass
            # Fallback: return as-is (Wine can sometimes handle Unix paths)
            logger.warning(f"Cannot convert to Wine path (no drive_c/ found): {linux_path}")
            return str(linux_path)

        # Extract the part after drive_c/
        relative = path_str[idx + len(drive_c_marker):]
        # Convert to Windows path format
        win_path = "C:\\" + relative.replace("/", "\\")
        return win_path

    @staticmethod
    def _wine_to_linux_path(wine_path: str, wine_config: WineConfig = None) -> Path:
        """
        Convert a Wine/Windows path to a Linux filesystem path.

        Examples:
            C:\\projects\\test → /opt/hecras-wine/drive_c/projects/test

        Args:
            wine_path: Windows-style path
            wine_config: Optional WineConfig (auto-detected if None)

        Returns:
            Linux Path object
        """
        config = wine_config or RasProcess._get_wine_config()
        if config is None:
            raise RuntimeError("No Wine config available for path conversion")

        # Handle common Windows path formats
        wine_path = wine_path.replace("/", "\\")

        # Extract drive letter and path
        if len(wine_path) >= 2 and wine_path[1] == ':':
            drive = wine_path[0].lower()
            remainder = wine_path[2:].lstrip("\\").replace("\\", "/")
            return config.wine_prefix / f"drive_{drive}" / remainder
        else:
            # Relative path — return relative to drive_c
            remainder = wine_path.lstrip("\\.").replace("\\", "/")
            return config.wine_prefix / "drive_c" / remainder

    @staticmethod
    def _build_wine_command(
        exe_path: Union[str, Path],
        args: List[str],
        wine_config: WineConfig = None,
        working_dir: Path = None,
    ) -> Tuple[List[str], Dict[str, str], Optional[str]]:
        """
        Build a Wine-wrapped command line.

        Args:
            exe_path: Path to the .exe (Linux path or Wine path)
            args: Command arguments (should use Windows-style paths)
            wine_config: Optional WineConfig
            working_dir: Optional working directory (Linux path)

        Returns:
            Tuple of (cmd_list, env_dict, cwd) ready for subprocess.run()
        """
        config = wine_config or RasProcess._get_wine_config()
        if config is None:
            raise RuntimeError("Wine not configured. Call configure_wine() or set WINEPREFIX.")

        # Convert exe path to Wine path if it's a Linux path
        exe_str = str(exe_path)
        if "/" in exe_str and "/drive_c/" in exe_str:
            exe_wine_path = RasProcess._linux_to_wine_path(exe_path)
        elif "\\" in exe_str or ":" in exe_str:
            exe_wine_path = exe_str  # Already a Windows path
        else:
            exe_wine_path = exe_str  # Bare filename, let Wine find it

        cmd = [
            RasProcess._resolve_wine_tool_executable("wine", config),
            exe_wine_path,
        ] + args

        env = RasProcess._build_wine_env(config)

        cwd = str(working_dir) if working_dir else None

        return cmd, env, cwd

    @staticmethod
    @log_call
    def check_wine_environment() -> Dict[str, Any]:
        """
        Verify the Wine environment is properly configured for RasProcess.

        Uses the configured ``wine_executable`` when one was provided via
        ``configure_wine()``.

        Returns a dict with status of each component:
        - wine_found: bool
        - wine_version: str or None
        - wine_prefix: str or None
        - dotnet48: bool (checks for .NET 4.8 marker files)
        - gdiplus: bool (checks for native gdiplus override)
        - rasprocess_found: bool
        - hdf5_found: bool

        Example:
            >>> status = RasProcess.check_wine_environment()
            >>> if all(status.values()):
            ...     print("Wine environment ready!")
            >>> else:
            ...     print("Missing:", [k for k,v in status.items() if not v])
        """
        result = {
            "wine_found": False,
            "wine_version": None,
            "wine_prefix": None,
            "prefix_exists": False,
            "dotnet48": False,
            "gdiplus": False,
            "corefonts": False,
            "rasprocess_found": False,
            "hdf5_found": False,
        }

        config = RasProcess._get_wine_config()
        wine_executable = RasProcess._resolve_wine_tool_executable(
            "wine",
            config,
        )

        # Check wine binary
        try:
            proc = subprocess.run(
                [wine_executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                env=RasProcess._build_wine_env(
                    config,
                    include_winedebug=False,
                ),
            )
            if proc.returncode == 0:
                result["wine_found"] = True
                result["wine_version"] = proc.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check Wine prefix
        if config and config.wine_prefix:
            result["wine_prefix"] = str(config.wine_prefix)
            result["prefix_exists"] = config.wine_prefix.exists()

            drive_c = config.wine_prefix / "drive_c"
            if drive_c.exists():
                # Check .NET 4.8
                dotnet_markers = [
                    drive_c / "windows" / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "mscorlib.dll",
                    drive_c / "windows" / "Microsoft.NET" / "Framework" / "v4.0.30319" / "mscorlib.dll",
                ]
                result["dotnet48"] = any(m.exists() for m in dotnet_markers)

                # Check gdiplus native override
                gdiplus_path = drive_c / "windows" / "system32" / "gdiplus.dll"
                result["gdiplus"] = gdiplus_path.exists()

                # Check fonts
                fonts_path = drive_c / "windows" / "Fonts" / "arial.ttf"
                result["corefonts"] = fonts_path.exists()

                # Check RasProcess.exe
                rasprocess = RasProcess.find_rasprocess()
                result["rasprocess_found"] = rasprocess is not None

                # Check HDF5 DLLs
                # Search in common locations
                for search_dir in [drive_c]:
                    for hdf5 in search_dir.rglob("hdf5.dll"):
                        result["hdf5_found"] = True
                        break
                    if result["hdf5_found"]:
                        break

        return result

    @staticmethod
    @log_call
    def setup_wine_environment(
        wine_prefix: Union[str, Path] = "/opt/hecras-wine",
        ras_version: str = "7.0",
    ) -> None:
        """
        Print setup instructions for the Wine environment.

        This does NOT automatically install — it prints the commands needed.
        Actual installation requires root/sudo and takes ~20 minutes.

        Args:
            wine_prefix: Target Wine prefix path
            ras_version: HEC-RAS version to configure for
        """
        instructions = f"""
=== Wine Environment Setup for RasProcess.exe ===

Prerequisites: Debian/Ubuntu Linux with sudo access.
Estimated time: ~20 minutes (mostly .NET 4.8 install).

Step 1: Install Wine and winetricks
    sudo dpkg --add-architecture i386
    sudo apt update
    sudo apt install -y wine wine64 wine32 winetricks cabextract

Step 2: Create Wine prefix with .NET 4.8
    export WINEPREFIX={wine_prefix}
    export WINEARCH=win64
    export DISPLAY=
    wineboot --init
    winetricks -q dotnet48     # ~15 min, installs .NET Framework 4.8
    winetricks -q gdiplus      # Native GDI+ (required for System.Drawing)
    winetricks -q corefonts    # Arial, Times New Roman, etc.

Step 3: Copy HEC-RAS DLLs from a Windows installation
    # From a Windows machine with HEC-RAS {ras_version} installed:
    # Copy the following from C:\\Program Files (x86)\\HEC\\HEC-RAS\\{ras_version}\\
    # to {wine_prefix}/drive_c/HEC-RAS/{ras_version}/

    Required files (from HEC-RAS install root):
        RasProcess.exe
        H5Assist.dll
        HDF.PInvoke.dll
        Geospatial.Core.dll
        Geospatial.GDALAssist.dll
        Geospatial.IO.dll
        Geospatial.Rendering.dll
        BitMiracle.LibTiff.NET.dll
        Hec.Dss.dll
        HecCs.dll
        MathNet.Numerics.dll
        (and all other DLLs in the root folder)

    Required files (from HEC-RAS x64/ subfolder):
        hdf5.dll
        hdf5_hl.dll
        hdf5_tools.dll
        libifcoremd.dll
        libiomp5md.dll
        libmmd.dll

    Required folder:
        GDAL/ (entire folder with bin64/ contents)

Step 4: Verify installation
    >>> from ras_commander import RasProcess
    >>> status = RasProcess.check_wine_environment()
    >>> print(status)

Step 5: Configure (optional — auto-detection usually works)
    >>> RasProcess.configure_wine(
    ...     wine_prefix="{wine_prefix}",
    ...     ras_install_dir="{wine_prefix}/drive_c/HEC-RAS/{ras_version}"
    ... )
"""
        print(instructions)
        logger.debug("Wine setup instructions printed. Follow steps to configure environment.")

    # ------------------------------------------------------------------ #
    #  Original Methods (with Wine support integrated)
    # ------------------------------------------------------------------ #

    @staticmethod
    @log_call
    def find_rasprocess(ras_version: str = None) -> Optional[Path]:
        """
        Find RasProcess.exe in standard HEC-RAS installation paths.

        On Windows, searches standard Program Files paths.
        On Linux, searches within the Wine prefix drive_c/ directory.

        Args:
            ras_version: Optional specific version to look for (e.g., "7.0").
                        If None, searches all known paths.

        Returns:
            Path to RasProcess.exe if found, None otherwise.
            On Linux, returns the Linux filesystem path (under drive_c/).
        """
        if IS_WINDOWS:
            # Original Windows behavior
            if ras_version:
                paths = [
                    Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/RasProcess.exe"),
                    Path(f"C:/Program Files/HEC/HEC-RAS/{ras_version}/RasProcess.exe"),
                ]
            else:
                paths = [Path(p) / "RasProcess.exe" for p in RasProcess.RAS_INSTALL_PATHS]

            for path in paths:
                if path.exists():
                    logger.debug(f"Found RasProcess.exe at: {path}")
                    return path

        elif IS_LINUX:
            config = RasProcess._get_wine_config()
            if config is None:
                logger.warning("No Wine prefix found on Linux")
                return None

            drive_c = config.wine_prefix / "drive_c"

            # Check explicitly configured ras_install_dir first
            if config.ras_install_dir:
                exe = Path(config.ras_install_dir) / "RasProcess.exe"
                if exe.exists():
                    logger.debug(f"Found RasProcess.exe at configured path: {exe}")
                    return exe

            # Search common locations under drive_c
            search_dirs = []

            if ras_version:
                search_dirs.extend([
                    drive_c / "Program Files (x86)" / "HEC" / "HEC-RAS" / ras_version,
                    drive_c / "Program Files" / "HEC" / "HEC-RAS" / ras_version,
                    drive_c / "HEC-RAS" / ras_version,
                    drive_c / "HEC-RAS",
                ])
            else:
                # Search all known version paths
                for win_path in RasProcess.RAS_INSTALL_PATHS:
                    # Convert Windows path to Linux path under drive_c
                    relative = win_path.replace("C:\\", "").replace("\\", "/")
                    search_dirs.append(drive_c / relative)

                # Also search common custom locations
                search_dirs.extend([
                    drive_c / "HEC-RAS",
                    drive_c / "hecras",
                ])

            for search_dir in search_dirs:
                exe = search_dir / "RasProcess.exe"
                if exe.exists():
                    logger.debug(f"Found RasProcess.exe at: {exe}")
                    return exe

            # Last resort: recursive search under drive_c (slow but thorough)
            logger.debug("Searching drive_c recursively for RasProcess.exe...")
            for exe in drive_c.rglob("RasProcess.exe"):
                logger.debug(f"Found RasProcess.exe at: {exe}")
                return exe

        logger.warning("RasProcess.exe not found in standard installation paths")
        return None

    @staticmethod
    def _run_rasprocess(
        rasprocess_path: Path,
        args: List[str],
        timeout: int = 600,
        working_dir: Path = None,
    ) -> subprocess.CompletedProcess:
        """
        Run RasProcess.exe, handling Wine wrapping on Linux automatically.

        Args:
            rasprocess_path: Path to RasProcess.exe (Linux or Windows path)
            args: Command-line arguments (use Windows-style paths on Linux)
            timeout: Timeout in seconds
            working_dir: Optional working directory

        Returns:
            subprocess.CompletedProcess
        """
        if IS_LINUX:
            wine_config = RasProcess._get_wine_config()
            if wine_config is None:
                raise RuntimeError(
                    "Wine not configured on Linux. "
                    "Call RasProcess.configure_wine() or set WINEPREFIX environment variable."
                )

            cmd, env, cwd = RasProcess._build_wine_command(
                rasprocess_path, args, wine_config,
                working_dir=working_dir
            )

            logger.debug(f"Wine command: {' '.join(cmd[:3])}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )

            # Filter Wine debug noise from stderr
            if result.stderr:
                filtered_stderr = "\n".join(
                    line for line in result.stderr.splitlines()
                    if not line.startswith(("0", "wine: ")) and "err:" not in line[:20]
                )
                result = subprocess.CompletedProcess(
                    result.args, result.returncode, result.stdout, filtered_stderr
                )

            return result

        else:
            # Windows: direct execution
            cmd = [str(rasprocess_path)] + args
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(working_dir) if working_dir else None,
            )

    @staticmethod
    def _resolve_path_for_rasprocess(path: Path) -> str:
        """
        Convert a path to the format RasProcess.exe expects.

        On Windows: returns the path as-is (string).
        On Linux: converts Linux path to Wine/Windows path.

        Args:
            path: Path object (native OS path)

        Returns:
            String path suitable for RasProcess.exe command arguments
        """
        if IS_LINUX:
            return RasProcess._linux_to_wine_path(path)
        else:
            return str(path)

    @staticmethod
    @log_call
    def validate_geometry_association_cli(
        hdf_path: Union[str, Path],
        terrain_hdf_path: Optional[Union[str, Path]] = None,
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        infiltration_hdf_path: Optional[Union[str, Path]] = None,
        sediment_soils_hdf_path: Optional[Union[str, Path]] = None,
        ras_version: str = None,
        timeout: int = 600,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Validate geometry association behavior against RasProcess.exe.

        Warning:
            This method runs RasProcess.exe ``SetGeometryAssociation`` in-place
            and mutates the supplied geometry HDF. It is a reference/validation
            path only. Normal workflows should call
            ``RasMap.associate_geometry_layers(...)``, which writes the same
            ``/Geometry`` association attributes through Python-native h5py.

        Args:
            hdf_path: Existing geometry HDF to mutate and validate.
            terrain_hdf_path: Optional terrain HDF to associate.
            landcover_hdf_path: Optional land-cover/Manning's n HDF.
            infiltration_hdf_path: Optional infiltration HDF.
            sediment_soils_hdf_path: Optional sediment bed-material soils HDF.
            ras_version: Optional HEC-RAS version for RasProcess.exe lookup.
            timeout: Command timeout in seconds.
            ras_object: Optional RasPrj object. Present for API consistency.

        Returns:
            Dict containing command args, return code, stdout/stderr,
            before/after association attrs, expected attrs, mismatches, and
            ``passed``.
        """
        from ._geometry_association import (
            build_expected_geometry_association_attrs,
            build_set_geometry_association_args,
            compare_expected_geometry_association_attrs,
            read_geometry_association,
            safe_resolve_path,
        )

        hdf_path = safe_resolve_path(hdf_path)
        if not hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {hdf_path}")

        supplied = {
            "terrain_hdf_path": terrain_hdf_path,
            "landcover_hdf_path": landcover_hdf_path,
            "infiltration_hdf_path": infiltration_hdf_path,
            "sediment_soils_hdf_path": sediment_soils_hdf_path,
        }
        if all(path is None for path in supplied.values()):
            raise ValueError("Provide at least one geometry association path.")

        resolved_paths: Dict[str, Path] = {}
        for key, path_value in supplied.items():
            if path_value is None:
                continue
            resolved_path = safe_resolve_path(path_value)
            if not resolved_path.exists():
                raise FileNotFoundError(
                    f"Association artifact not found for {key}: {resolved_path}"
                )
            resolved_paths[key] = resolved_path

        before = read_geometry_association(hdf_path, resolve_paths=True)
        expected_attrs = build_expected_geometry_association_attrs(
            hdf_path,
            resolved_paths,
            project_folder=hdf_path.parent,
        )

        rasprocess = RasProcess.find_rasprocess(ras_version)
        if rasprocess is None:
            raise FileNotFoundError("RasProcess.exe not found")

        command_args = build_set_geometry_association_args(
            hdf_path,
            resolved_paths,
            path_formatter=RasProcess._resolve_path_for_rasprocess,
        )
        result = RasProcess._run_rasprocess(
            rasprocess,
            command_args,
            timeout=timeout,
            working_dir=hdf_path.parent,
        )

        after = read_geometry_association(hdf_path, resolve_paths=True)
        mismatches = compare_expected_geometry_association_attrs(
            hdf_path,
            after,
            expected_attrs,
        )
        passed = result.returncode == 0 and not mismatches

        return {
            "rasprocess_path": str(rasprocess),
            "command_args": command_args,
            "return_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "before": before,
            "after": after,
            "expected_attrs": expected_attrs,
            "mismatches": mismatches,
            "passed": passed,
        }

    @staticmethod
    @log_call
    def compute_geometry(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 1800,
    ) -> Dict[str, Any]:
        """
        Run HEC-RAS's headless geometry completion (RasProcess.exe CompleteGeometry).

        This is the GUI-free equivalent of RASMapper's *Compute Geometry* action.
        It wraps ``RASGeometry.CompleteForComputations()``, the same pipeline the
        RASMapper GUI runs, so it authors HEC-RAS's own **River Edge Lines**
        ("Create Edge Lines at XS Limits") and **XS Interpolation Surface**, plus
        bank lines, ineffective areas, blocked obstructions, storage-area and
        structure connectivity, and 2D property tables. The edge lines it produces
        use HEC-RAS's bank-line-anchored offset-curve algorithm and carry the
        group-level ``Source Data Hash``, so HEC-RAS treats them as authoritative
        and will not silently recompute them. (Flow paths are not part of this
        pipeline.)

        Platform guidance
        -----------------
        This runs ``RasProcess.exe`` as a subprocess and works on both Windows
        (native) and Linux (via Wine, auto-detected). **On Windows, prefer
        ``RasGeometryCompute.compute_geometry()``** — it runs the same pipeline
        in-process via pythonnet (no subprocess), exposes each layer separately
        (edge lines / interpolation surface / flow paths), and returns structured
        ``ValidateGeometry`` diagnostics. This subprocess method remains the only
        supported geometry-completion path for **Linux/Wine** execution.

        Warning
        -------
        This runs the **entire** geometry-completion pipeline (there is no
        narrower "just edge lines" RasProcess subcommand) and **mutates the
        geometry HDF in place**. Point it at a disposable copy unless you intend
        to complete the original geometry. On models with large 2D flow areas the
        pipeline also (re)builds 2D property tables and can take minutes.

        Parameters
        ----------
        geom_hdf_path : str or Path
            Geometry HDF (``.g##.hdf``) to complete, mutated in place.
        rasmap_path : str or Path, optional
            ``.rasmap`` used to resolve the spatial reference. When None and a
            ``ras_object`` is available, it is discovered via
            ``RasMap.get_rasmap_path``.
        ras_object : RasPrj, optional
            RAS project object used to locate the ``.rasmap`` when not supplied.
        ras_version : str, optional
            Specific HEC-RAS version for the RasProcess.exe lookup.
        timeout : int, optional
            Command timeout in seconds (default 1800).

        Returns
        -------
        dict
            ``rasprocess_path``, ``command_args``, ``return_code``, ``stdout``,
            ``stderr``, ``edge_lines_written`` (bool), ``interpolation_surface_written``
            (bool), and ``success`` (return code 0, no ``Error:`` in stdout, and the
            River Edge Lines group present afterward).

        Raises
        ------
        FileNotFoundError
            If the geometry HDF or RasProcess.exe cannot be found.
        """
        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")

        # Resolve the .rasmap for the spatial reference when not supplied.
        if rasmap_path is None:
            ras_obj = ras_object or ras
            try:
                if getattr(ras_obj, "initialized", False) or getattr(ras_obj, "project_folder", None):
                    rasmap_path = RasMap.get_rasmap_path(ras_obj)
            except Exception as e:
                logger.debug(f"Could not auto-resolve .rasmap: {e}")
        rasmap_path = Path(rasmap_path) if rasmap_path else None

        rasprocess = RasProcess.find_rasprocess(ras_version)
        if rasprocess is None:
            raise FileNotFoundError("RasProcess.exe not found")

        args = [
            "CompleteGeometry",
            f"GeomFilename={RasProcess._resolve_path_for_rasprocess(geom_hdf_path)}",
        ]
        if rasmap_path is not None and rasmap_path.exists():
            args.append(f"RasMapFilename={RasProcess._resolve_path_for_rasprocess(rasmap_path)}")

        logger.info(f"Running RasProcess.exe CompleteGeometry on {geom_hdf_path.name}")
        result = RasProcess._run_rasprocess(
            rasprocess, args, timeout=timeout, working_dir=geom_hdf_path.parent
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Confirm the artifacts landed in the geometry HDF.
        edge_lines_written = False
        interp_surface_written = False
        try:
            import h5py
            with h5py.File(geom_hdf_path, "r") as hdf:
                edge_lines_written = "Geometry/River Edge Lines" in hdf
                interp_surface_written = (
                    "Geometry/Cross Section Interpolation Surfaces" in hdf
                )
        except Exception as e:
            logger.debug(f"Post-run HDF inspection failed: {e}")

        success = (
            result.returncode == 0
            and "Error:" not in stdout
            and edge_lines_written
        )
        if not success:
            logger.warning(
                f"CompleteGeometry did not fully succeed (rc={result.returncode}, "
                f"edge_lines={edge_lines_written}). stdout: {stdout.strip()[:400]}"
            )

        return {
            "rasprocess_path": str(rasprocess),
            "command_args": args,
            "return_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "edge_lines_written": edge_lines_written,
            "interpolation_surface_written": interp_surface_written,
            "success": success,
        }

    @staticmethod
    @log_call
    def complete_geometry(
        geom_hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 1800,
    ) -> Dict[str, Any]:
        """Deprecated alias for :meth:`compute_geometry`. Use ``compute_geometry``."""
        warnings.warn(
            "RasProcess.complete_geometry() is renamed to compute_geometry(); "
            "the old name will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        return RasProcess.compute_geometry(
            geom_hdf_path, rasmap_path=rasmap_path, ras_object=ras_object,
            ras_version=ras_version, timeout=timeout,
        )

    @staticmethod
    @log_call
    def get_plan_timestamps(
        plan_number: str,
        ras_object=None
    ) -> List[str]:
        """
        Get available output timestamps for a plan in RASMapper format.

        Args:
            plan_number: Plan number (e.g., "01", "06")
            ras_object: Optional RAS object instance

        Returns:
            List of timestamp strings in format "DDMMMYYYY HH:MM:SS" (e.g., "10SEP2018 02:30:00")
        """
        from .hdf.HdfPlan import HdfPlan

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get HDF path for plan
        plan_num = RasUtils.normalize_ras_number(plan_number)
        hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_num}.hdf"

        if not hdf_path.exists():
            logger.error(f"Plan HDF not found: {hdf_path}")
            return []

        try:
            timestamps = HdfPlan.get_plan_timestamps_list(hdf_path)
            # Convert to RASMapper format: "DDMMMYYYY HH:MM:SS"
            rasmap_timestamps = []
            for ts in timestamps:
                # Format: 10SEP2018 02:30:00
                formatted = ts.strftime("%d%b%Y %H:%M:%S").upper()
                rasmap_timestamps.append(formatted)
            return rasmap_timestamps
        except Exception as e:
            logger.error(f"Failed to get timestamps from {hdf_path}: {e}")
            return []

    @staticmethod
    @log_call
    def _get_projection_info(rasmap_path: Path) -> ProjectionInfo:
        """
        Extract projection file path and terrain raster paths from .rasmap XML.

        Args:
            rasmap_path: Path to .rasmap file

        Returns:
            ProjectionInfo containing the projection path and every terrain
            raster associated with the rasmap terrain layers.
        """
        try:
            rasmap_path = Path(rasmap_path)
            tree = ET.parse(_windows_extended_length_path(rasmap_path))
            root = tree.getroot()

            # Get projection file
            prj_path = None
            proj_elem = root.find(".//RASProjectionFilename")
            if proj_elem is not None:
                filename = proj_elem.get("Filename")
                if filename:
                    prj_path = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if not os.path.exists(_windows_extended_length_path(prj_path)):
                        prj_path = None

            terrain_paths: List[Path] = []
            for layer in root.findall("./Terrains/Layer"):
                if layer.get("Checked", "True").casefold() == "false":
                    continue
                filename = layer.get("Filename")
                if filename:
                    terrain_hdf = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if os.path.exists(_windows_extended_length_path(terrain_hdf)):
                        terrain_dir = terrain_hdf.parent
                        layer_tifs = _glob_paths(
                            terrain_dir,
                            f"{terrain_hdf.stem}*.tif",
                        )
                        if not layer_tifs:
                            layer_tifs = _glob_paths(terrain_dir, "*.tif")
                        for tif_path in layer_tifs:
                            if tif_path not in terrain_paths:
                                terrain_paths.append(tif_path)

            terrain_paths_tuple = tuple(terrain_paths)
            terrain_path = terrain_paths_tuple[0] if terrain_paths_tuple else None
            return ProjectionInfo(
                prj_path=prj_path,
                terrain_path=terrain_path,
                terrain_paths=terrain_paths_tuple,
            )

        except Exception as e:
            logger.error(f"Failed to parse rasmap for projection info: {e}")
            return ProjectionInfo(prj_path=None, terrain_path=None, terrain_paths=())

    @staticmethod
    def _terrain_for_stored_map(
        tif_path: Path,
        terrain_paths: Tuple[Path, ...],
    ) -> Optional[Path]:
        """Match a stored-map terrain suffix to its source terrain raster."""
        if not terrain_paths:
            return None
        if len(terrain_paths) == 1:
            return terrain_paths[0]

        stored_map_stem = Path(tif_path).stem.casefold()
        matches = [
            terrain_path
            for terrain_path in terrain_paths
            if stored_map_stem.endswith(terrain_path.stem.casefold())
        ]
        if not matches:
            return None
        return max(matches, key=lambda path: len(path.stem))

    @staticmethod
    @log_call
    def _fix_georeferencing(
        tif_path: Path,
        prj_path: Optional[Path],
        terrain_path: Path
    ) -> bool:
        """
        Apply georeferencing to TIF from projection and terrain files.

        Args:
            tif_path: Path to TIF file to fix
            prj_path: Path to .prj file with CRS, if available
            terrain_path: Path to terrain TIF with transform

        Returns:
            True if fix was applied, False otherwise
        """
        if not HAS_RASTERIO:
            logger.warning(f"Skipping georef fix for {tif_path} (rasterio not installed)")
            return False

        try:
            terrain_path = Path(terrain_path)
            with rasterio.open(
                _windows_extended_length_path(terrain_path)
            ) as terrain:
                transform = terrain.transform
                terrain_crs = terrain.crs

            crs = None
            if prj_path is not None and os.path.exists(
                _windows_extended_length_path(prj_path)
            ):
                with open(
                    _windows_extended_length_path(prj_path),
                    'r',
                    encoding='utf-8',
                ) as f:
                    wkt = f.read()
                crs = CRS.from_wkt(wkt)
            elif terrain_crs is not None:
                crs = terrain_crs
                logger.debug(
                    "Using terrain CRS for georeferencing fix on %s because "
                    "no projection file was found.",
                    tif_path,
                )
            else:
                logger.warning(
                    "Could not determine CRS for georeferencing fix on %s "
                    "(missing projection file and terrain CRS).",
                    tif_path,
                )
                return False

            tif_path = Path(tif_path)
            tmp_path = tif_path.with_name(f"{tif_path.stem}.georef_tmp{tif_path.suffix}")
            tif_io_path = _windows_extended_length_path(tif_path)
            tmp_io_path = _windows_extended_length_path(tmp_path)
            with rasterio.open(tif_io_path) as src:
                data = src.read()
                profile = src.profile.copy()
                tags = src.tags()

            profile.update(crs=crs, transform=transform)
            with rasterio.open(tmp_io_path, "w", **profile) as dst:
                dst.write(data)
                if tags:
                    dst.update_tags(**tags)

            os.replace(tmp_io_path, tif_io_path)

            logger.debug("Fixed georeferencing: %s", tif_path)
            return True

        except Exception as e:
            logger.error(f"Failed to fix georeferencing for {tif_path}: {e}")
            return False

    @staticmethod
    def _drop_unreadable_tifs(
        generated_files: Dict[str, List[Path]],
    ) -> Dict[str, List[Path]]:
        """
        Remove invalid GeoTIFFs from StoreAllMaps results.

        HEC-RAS can occasionally emit a partial or corrupt TIFF for a single
        stored-map timestep. Downstream animation code treats a missing timestep
        as dry/no-data, but it cannot recover from a path that exists and then
        fails during raster read.
        """
        if not HAS_RASTERIO:
            return generated_files

        for map_key, tif_list in list(generated_files.items()):
            readable_tifs: List[Path] = []
            for tif_path in tif_list:
                if Path(tif_path).suffix.lower() not in {".tif", ".tiff"}:
                    readable_tifs.append(tif_path)
                    continue
                try:
                    with rasterio.open(
                        _windows_extended_length_path(tif_path)
                    ) as src:
                        if src.count < 1 or src.width < 1 or src.height < 1:
                            raise ValueError("GeoTIFF has no readable raster band")
                        src.read(1)
                    readable_tifs.append(tif_path)
                except Exception as exc:
                    logger.warning(
                        "Dropping unreadable stored-map TIFF %s: %s",
                        tif_path,
                        exc,
                    )
                    try:
                        tif_io_path = _windows_extended_length_path(tif_path)
                        if os.path.exists(tif_io_path):
                            os.remove(tif_io_path)
                    except OSError:
                        logger.debug("Could not delete unreadable TIFF: %s", tif_path)
            generated_files[map_key] = readable_tifs

        return generated_files

    @staticmethod
    def _tif_has_data(tif_path: Union[str, Path]) -> bool:
        """Return True when a readable TIFF contains at least one valid cell."""
        if not HAS_RASTERIO:
            return True
        try:
            with rasterio.open(
                _windows_extended_length_path(tif_path)
            ) as src:
                return bool(src.read(1, masked=True).count())
        except Exception:
            return False

    @staticmethod
    def _hdf_has_wet_maximum_depth(
        hdf_path: Union[str, Path],
        minimum_depth: float = 1.0e-6,
    ) -> bool:
        """Return True when plan-HDF summary results contain a wet cell.

        This distinguishes a legitimate all-dry Depth map from the HEC-RAS
        mapper failure mode that emits an all-NoData TIFF even though the plan
        HDF contains positive hydraulic depth.
        """
        try:
            import h5py

            with h5py.File(hdf_path, "r") as hdf:
                summary_root = (
                    "Results/Unsteady/Output/Output Blocks/Base Output/"
                    "Summary Output"
                )
                component_specs = (
                    (
                        "2D Flow Areas",
                        "Geometry/2D Flow Areas",
                        "Cells Minimum Elevation",
                    ),
                    (
                        "Pipe Networks",
                        "Geometry/Pipe Networks",
                        "Cells Minimum Elevations",
                    ),
                )
                for component, geometry_root, elevation_name in component_specs:
                    result_root = f"{summary_root}/{component}"
                    if result_root not in hdf or geometry_root not in hdf:
                        continue
                    for name in hdf[result_root].keys():
                        wse_path = f"{result_root}/{name}/Maximum Water Surface"
                        elevation_path = f"{geometry_root}/{name}/{elevation_name}"
                        if wse_path not in hdf or elevation_path not in hdf:
                            continue
                        wse = np.asarray(hdf[wse_path][()], dtype=np.float64)
                        elevations = np.asarray(
                            hdf[elevation_path][()], dtype=np.float64
                        ).reshape(-1)
                        if wse.ndim > 1:
                            wse = np.nanmax(wse, axis=0)
                        wse = wse.reshape(-1)
                        count = min(len(wse), len(elevations))
                        if count and np.any(
                            np.isfinite(wse[:count])
                            & np.isfinite(elevations[:count])
                            & ((wse[:count] - elevations[:count]) > minimum_depth)
                        ):
                            return True
        except Exception as exc:
            logger.debug("Could not audit plan-HDF wet cells: %s", exc)
        return False

    @staticmethod
    def _normalize_mapper_geometry_timestamps(hdf_path: Union[str, Path]) -> int:
        """Normalize HEC-RAS 7.0 PM geometry timestamps in a temporary HDF.

        HEC-RAS 7.0 April 2026 can write embedded geometry timestamps with a
        24-hour value greater than 12, then fail to parse that same geometry in
        the headless StoreAllMaps path.  The native mapper reports success but
        writes an all-NoData or corrupt TIFF.  This method is intentionally
        private and is only applied to a temporary byte-for-byte plan-HDF copy.
        Hydraulic and geometry values are not changed.
        """
        import h5py

        timestamp_pattern = re.compile(r"(?P<prefix>\b\d{2}[A-Za-z]{3}\d{4} )(?P<hour>\d{2})(?=:)")
        changed = 0
        touch_paths: List[str] = []

        with h5py.File(hdf_path, "r+") as hdf:
            geometry = hdf.get("Geometry")
            if geometry is None:
                return 0

            def normalize_attributes(_name: str, obj) -> None:
                nonlocal changed
                for attr_name, raw_value in list(obj.attrs.items()):
                    if isinstance(raw_value, str):
                        text = raw_value
                        encoded_value = False
                    elif isinstance(raw_value, (bytes, np.bytes_)):
                        text = bytes(raw_value).decode("ascii", errors="ignore")
                        encoded_value = True
                    else:
                        continue
                    match = timestamp_pattern.search(text)
                    if match is None:
                        continue
                    hour = int(match.group("hour"))
                    if hour <= 12:
                        continue
                    normalized = (
                        text[:match.start("hour")]
                        + f"{hour - 12:02d}"
                        + text[match.end("hour"):]
                    )
                    obj.attrs.modify(
                        attr_name,
                        normalized.encode("ascii") if encoded_value else normalized,
                    )
                    changed += 1

            normalize_attributes("Geometry", geometry)
            geometry.visititems(normalize_attributes)
            if not changed:
                return 0

            def collect_touch_paths(name: str, obj) -> None:
                if not isinstance(obj, h5py.Dataset) or obj.size == 0:
                    return
                full_name = f"Geometry/{name}"
                if (
                    full_name.endswith("/Cells Minimum Elevation")
                    or full_name.endswith("/Cell Property Table")
                    or full_name in {
                        "Geometry/Pump Stations/Attributes",
                        "Geometry/Cross Sections/Attributes",
                        "Geometry/Storage Areas/Attributes",
                    }
                ):
                    touch_paths.append(full_name)

            geometry.visititems(collect_touch_paths)
            if not touch_paths:
                geometry.visititems(
                    lambda name, obj: touch_paths.append(f"Geometry/{name}")
                    if not touch_paths
                    and isinstance(obj, h5py.Dataset)
                    and obj.size
                    else None
                )

            # Rewriting the same values refreshes HDF object metadata consumed
            # by RasMapperLib.  This occurs only in the disposable copy.
            for dataset_path in touch_paths:
                dataset = hdf[dataset_path]
                dataset[...] = dataset[...]

        return changed

    @staticmethod
    @contextmanager
    def _mapper_compatible_result_hdf(
        hdf_path: Union[str, Path],
        ras_version: Optional[str],
    ):
        """Temporarily swap in a mapper-compatible HDF copy when required."""
        source = Path(hdf_path)
        if not str(ras_version or "").startswith("7.0"):
            yield source
            return

        working_copy = source.with_name(
            f".{source.name}.{os.getpid()}.{uuid.uuid4().hex}.mapper-work"
        )
        original_backup = source.with_name(
            f".{source.name}.{os.getpid()}.{uuid.uuid4().hex}.mapper-original"
        )
        swapped = False
        try:
            shutil.copy2(
                _windows_extended_length_path(source),
                _windows_extended_length_path(working_copy),
            )
            changed = RasProcess._normalize_mapper_geometry_timestamps(working_copy)
            if not changed:
                os.remove(_windows_extended_length_path(working_copy))
                yield source
                return

            os.replace(
                _windows_extended_length_path(source),
                _windows_extended_length_path(original_backup),
            )
            try:
                os.replace(
                    _windows_extended_length_path(working_copy),
                    _windows_extended_length_path(source),
                )
                swapped = True
            except Exception:
                os.replace(
                    _windows_extended_length_path(original_backup),
                    _windows_extended_length_path(source),
                )
                raise

            logger.debug(
                "Applied temporary HEC-RAS 7.0 StoreAllMaps geometry-timestamp "
                "compatibility to %s (%d attributes)",
                source.name,
                changed,
            )
            yield source
        finally:
            if swapped:
                source_io = _windows_extended_length_path(source)
                if os.path.exists(source_io):
                    os.remove(source_io)
                os.replace(
                    _windows_extended_length_path(original_backup),
                    source_io,
                )
            for temporary_path in (working_copy, original_backup):
                temporary_io = _windows_extended_length_path(temporary_path)
                if os.path.exists(temporary_io):
                    os.remove(temporary_io)

    @staticmethod
    def _get_plan_short_id(hdf_path: Path) -> Optional[str]:
        """
        Get the Plan ShortID from an HDF file.

        RasProcess.exe uses this to determine the output folder name.

        Args:
            hdf_path: Path to plan HDF file

        Returns:
            Plan ShortID string, or None if not found
        """
        try:
            import h5py
            with h5py.File(hdf_path, 'r') as hdf:
                if 'Plan Data' in hdf and 'Plan Information' in hdf['Plan Data']:
                    info = hdf['Plan Data']['Plan Information']
                    if 'Plan ShortID' in info.attrs:
                        short_id = info.attrs['Plan ShortID']
                        if isinstance(short_id, bytes):
                            short_id = short_id.decode('utf-8')
                        return short_id.strip()
        except Exception as e:
            logger.debug(f"Could not read Plan ShortID from {hdf_path}: {e}")
        return None

    @staticmethod
    @log_call
    def _add_stored_map_to_rasmap(
        rasmap_path: Path,
        plan_hdf_filename: str,
        map_type: str,
        profile_name: str,
        output_folder: str,
        profile_index: int = 2147483647,
        output_mode: str = "Stored Current Terrain",
        extra_attrs: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Add a stored map configuration to the .rasmap file.

        If the Results element or plan layer doesn't exist, they will be created.

        Args:
            rasmap_path: Path to .rasmap file
            plan_hdf_filename: HDF filename (e.g., "Project.p01.hdf")
            map_type: Map type XML name (e.g., "elevation", "depth")
            profile_name: Profile name (e.g., "Max", "10SEP2018 02:30:00")
            output_folder: Output folder name relative to project
            profile_index: Profile index (2147483647 for Max/Min)
            output_mode: OutputMode for MapParameters. Use "Stored Current Terrain"
                for raster outputs (default), or "Stored Polygon Specified Depth"
                for inundation boundary shapefile output.
            extra_attrs: Additional attributes set on the MapParameters element
                (e.g. {"ArrivalDepth": "0.1"} for arrival time / duration /
                percent-inundated maps).

        Returns:
            True if successful, False otherwise
        """
        try:
            tree = ET.parse(_windows_extended_length_path(rasmap_path))
            root = tree.getroot()

            # Find or create the Results element
            results_elem = root.find(".//Results")
            if results_elem is None:
                # Create Results element - insert after Geometries if present
                results_elem = ET.Element("Results")
                results_elem.set("Checked", "True")
                results_elem.set("Expanded", "True")

                # Find insertion point (after Geometries or at end)
                geom_elem = root.find(".//Geometries")
                if geom_elem is not None:
                    # Insert after Geometries
                    parent = root
                    geom_index = list(parent).index(geom_elem)
                    parent.insert(geom_index + 1, results_elem)
                else:
                    root.append(results_elem)
                logger.debug("Created Results element in rasmap")

            # Find the specific plan layer - match by filename basename
            plan_layer = None
            plan_basename = Path(plan_hdf_filename).name.lower()
            for layer in results_elem.findall("Layer"):
                filename = layer.get("Filename", "")
                if Path(filename).name.lower() == plan_basename:
                    plan_layer = layer
                    break

            if plan_layer is None:
                # Create the plan layer - use output_folder as layer name
                plan_layer = ET.SubElement(results_elem, "Layer")
                plan_layer.set("Name", output_folder)
                plan_layer.set("Filename", f".\\{plan_hdf_filename}")
                logger.debug(
                    "Created plan layer '%s' in rasmap for %s",
                    output_folder,
                    plan_hdf_filename,
                )
            plan_layer.set("Type", "RASResults")
            plan_layer.set("Checked", "True")
            plan_layer.set("Expanded", "True")

            # Determine display name and output filename
            type_info = None
            for key, (xml_name, display_name, _) in RasProcess.MAP_TYPES.items():
                if xml_name == map_type:
                    type_info = (xml_name, display_name)
                    break

            if type_info is None:
                display_name = map_type.title()
            else:
                display_name = type_info[1]

            # Create output filename
            # Polygon outputs use .shp; raster outputs use .vrt
            safe_profile = profile_name.replace(":", " ").replace("/", "_")
            is_polygon = "Polygon" in output_mode
            ext = ".shp" if is_polygon else ".vrt"
            output_filename = f".\\{output_folder}\\{display_name} ({safe_profile}){ext}"

            # Create the Layer element
            layer_elem = ET.SubElement(plan_layer, "Layer")
            layer_elem.set("Name", display_name)
            layer_elem.set("Type", "RASResultsMap")
            layer_elem.set("Checked", "True")
            layer_elem.set("Filename", output_filename)

            # Create MapParameters element
            map_params = ET.SubElement(layer_elem, "MapParameters")
            map_params.set("MapType", map_type)
            map_params.set("OutputMode", output_mode)
            map_params.set("StoredFilename", output_filename)
            map_params.set("ProfileIndex", str(profile_index))
            map_params.set("ProfileName", profile_name)
            for attr_name, attr_value in (extra_attrs or {}).items():
                map_params.set(attr_name, str(attr_value))

            # Write back
            tree.write(
                _windows_extended_length_path(rasmap_path),
                encoding='utf-8',
                xml_declaration=True,
            )
            logger.debug(f"Added stored map: {display_name} ({profile_name})")
            return True

        except Exception as e:
            logger.error(f"Failed to add stored map to rasmap: {e}")
            return False

    @staticmethod
    @log_call
    def _remove_stored_maps_from_rasmap(
        rasmap_path: Path,
        plan_hdf_filename: str = None
    ) -> int:
        """
        Remove all stored map configurations from .rasmap file.

        Args:
            rasmap_path: Path to .rasmap file
            plan_hdf_filename: Optional specific plan to clear. If None, clears all.

        Returns:
            Number of stored maps removed
        """
        try:
            tree = ET.parse(_windows_extended_length_path(rasmap_path))
            root = tree.getroot()

            removed_count = 0
            results_elem = root.find(".//Results")
            if results_elem is None:
                return 0

            for plan_layer in results_elem.findall("Layer"):
                if plan_hdf_filename:
                    filename = plan_layer.get("Filename", "")
                    # Match by basename to handle relative paths like .\file.hdf
                    plan_basename = Path(plan_hdf_filename).name.lower()
                    if Path(filename).name.lower() != plan_basename:
                        continue

                # Find and remove stored map layers
                to_remove = []
                for layer in plan_layer.findall("Layer"):
                    if layer.get("Type") == "RASResultsMap":
                        map_params = layer.find("MapParameters")
                        if map_params is not None:
                            output_mode = map_params.get("OutputMode", "")
                            if "Stored" in output_mode:
                                to_remove.append(layer)

                for layer in to_remove:
                    plan_layer.remove(layer)
                    removed_count += 1

            if removed_count > 0:
                tree.write(
                    _windows_extended_length_path(rasmap_path),
                    encoding='utf-8',
                    xml_declaration=True,
                )
                logger.debug(f"Removed {removed_count} stored maps from rasmap")

            return removed_count

        except Exception as e:
            logger.error(f"Failed to remove stored maps from rasmap: {e}")
            return 0

    @staticmethod
    def _select_terrain_for_mapping(
        rasmap_path: Path,
        terrain_name: str,
        ras_object=None,
    ) -> None:
        """Validate and exclusively select a registered RAS Mapper terrain."""

        layers = RasMap.list_terrain_layers(rasmap_path, ras_object=ras_object)
        matches = layers[
            layers["name"].fillna("").str.casefold() == terrain_name.casefold()
        ] if not layers.empty else layers
        if len(matches) != 1:
            available = layers["name"].tolist() if not layers.empty else []
            raise ValueError(
                f"Registered terrain layer {terrain_name!r} was not found uniquely. "
                f"Available terrains: {available}"
            )

        layer_type = str(matches.iloc[0].get("type") or "")
        if layer_type != "TerrainLayer":
            raise ValueError(
                f"Registered terrain layer {terrain_name!r} has unsupported Type "
                f"{layer_type!r}; expected 'TerrainLayer'. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )

        resolved_path = matches.iloc[0].get("resolved_path")
        if not resolved_path or not Path(resolved_path).is_file():
            raise FileNotFoundError(
                f"Registered terrain HDF for {terrain_name!r} was not found: "
                f"{resolved_path}"
            )

        RasMap.set_terrain_layer_visibility(
            rasmap_path,
            terrain_name=terrain_name,
            checked=True,
            exclusive=True,
            surface_on=True,
            ras_object=ras_object,
        )
        selected_layers = RasMap.list_terrain_layers(
            rasmap_path,
            ras_object=ras_object,
        )
        selected = selected_layers[
            selected_layers["name"].fillna("").str.casefold()
            == terrain_name.casefold()
        ]
        other_terrains = selected_layers[
            (selected_layers["type"] == "TerrainLayer")
            & (
                selected_layers["name"].fillna("").str.casefold()
                != terrain_name.casefold()
            )
        ]
        if (
            len(selected) != 1
            or not bool(selected.iloc[0]["checked"])
            or not bool(selected.iloc[0]["surface_on"])
            or bool(other_terrains["checked"].any())
        ):
            raise RuntimeError(
                f"Failed to select registered terrain {terrain_name!r} exclusively"
            )
        logger.debug("Selected terrain layer for stored-map generation: %s", terrain_name)

    @staticmethod
    def _resolve_benefit_terrain_name(
        ras_object,
        terrain_tif: Union[str, Path],
        terrain_name: Optional[str] = None,
    ) -> str:
        """Resolve a single registered terrain for BenefitArea mapping."""

        terrain_path = RasBenefits.validate_terrain_tif(terrain_tif).resolve()
        rasmap_path = RasMap.get_rasmap_path(ras_object)
        if rasmap_path is None:
            raise FileNotFoundError(
                "Benefit analysis requires a project .rasmap with a registered "
                f"terrain. {RasBenefits.TERRAIN_REMEDIATION}"
            )

        layers = RasMap.list_terrain_layers(rasmap_path, ras_object=ras_object)
        if layers.empty:
            raise ValueError(
                "No terrain is registered in the project .rasmap. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )

        if terrain_name:
            matches = layers[
                layers["name"].fillna("").str.casefold() == terrain_name.casefold()
            ]
        else:
            matched_indexes = []
            for index, row in layers.iterrows():
                resolved = row.get("resolved_path")
                if not resolved or not Path(resolved).is_file():
                    continue
                try:
                    source_path = RasBenefits.get_registered_terrain_source(resolved)
                except (FileNotFoundError, ValueError):
                    continue
                if source_path == terrain_path:
                    matched_indexes.append(index)
            matches = layers.loc[matched_indexes]

        if len(matches) != 1:
            available = layers["name"].tolist()
            raise ValueError(
                "Benefit analysis could not match the required single GeoTIFF "
                "to exactly one registered terrain. Provide terrain_name. "
                f"Available terrains: {available}. {RasBenefits.TERRAIN_REMEDIATION}"
            )

        row = matches.iloc[0]
        selected_name = str(row["name"])
        resolved_hdf_text = row.get("resolved_path")
        if not resolved_hdf_text or not Path(resolved_hdf_text).is_file():
            raise FileNotFoundError(
                f"Registered terrain HDF for {selected_name!r} was not found: "
                f"{resolved_hdf_text}. {RasBenefits.TERRAIN_REMEDIATION}"
            )

        registered_source = RasBenefits.get_registered_terrain_source(
            Path(resolved_hdf_text)
        )
        if registered_source != terrain_path:
            raise ValueError(
                "terrain_tif must be the single GeoTIFF recorded by the registered "
                f"terrain HDF: {registered_source}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        return selected_name

    @staticmethod
    def _require_common_benefit_terrain_association(
        ras_object,
        plan_numbers,
        terrain_name: str,
    ) -> Path:
        """Verify StoreAllMaps will use one selected terrain for both plans."""

        rasmap_path = RasMap.get_rasmap_path(ras_object)
        if rasmap_path is None:
            raise FileNotFoundError(
                "Benefit analysis requires a project .rasmap with a registered "
                f"terrain. {RasBenefits.TERRAIN_REMEDIATION}"
            )
        layers = RasMap.list_terrain_layers(
            rasmap_path,
            ras_object=ras_object,
        )
        matches = layers[
            layers["name"].fillna("").str.casefold() == terrain_name.casefold()
        ] if not layers.empty else layers
        if len(matches) != 1:
            raise ValueError(
                f"Registered terrain layer {terrain_name!r} was not found uniquely. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        selected_text = matches.iloc[0].get("resolved_path")
        if not selected_text or not Path(selected_text).is_file():
            raise FileNotFoundError(
                f"Registered terrain HDF for {terrain_name!r} was not found: "
                f"{selected_text}. {RasBenefits.TERRAIN_REMEDIATION}"
            )
        selected_hdf = Path(selected_text).resolve()
        selected_key = os.path.normcase(os.path.abspath(selected_hdf))

        project_folder = Path(ras_object.project_folder)
        project_name = str(ras_object.project_name)
        for plan_number in plan_numbers:
            plan_num = RasUtils.normalize_ras_number(plan_number)
            plan_hdf = project_folder / f"{project_name}.p{plan_num}.hdf"
            if not plan_hdf.is_file():
                raise FileNotFoundError(f"Plan HDF not found: {plan_hdf}")
            try:
                association = RasMap.get_hdf_geometry_association(
                    plan_hdf,
                    resolve_paths=True,
                    include_2d_area_attrs=True,
                    ras_object=ras_object,
                )
            except Exception as exc:
                raise ValueError(
                    "Benefit analysis could not verify the terrain association "
                    f"recorded by plan p{plan_num}. {RasBenefits.TERRAIN_REMEDIATION}"
                ) from exc

            geometry_terrain = association.get("terrain_hdf_path")
            if not geometry_terrain:
                raise ValueError(
                    f"Plan p{plan_num} does not record a Geometry terrain. "
                    "BenefitArea requires both plan HDFs to reference the same "
                    "registered single-TIFF terrain because RAS Mapper uses the "
                    "plan association when storing Depth maps. "
                    f"{RasBenefits.TERRAIN_REMEDIATION}"
                )

            recorded = [("Geometry", geometry_terrain)]
            recorded.extend(
                (
                    f"2D Flow Area {area.get('flow_area')!r}",
                    area.get("terrain_hdf_path"),
                )
                for area in association.get(
                    "two_d_area_terrain_associations",
                    [],
                )
                if area.get("terrain_hdf_path")
            )
            mismatches = [
                (scope, Path(path).resolve())
                for scope, path in recorded
                if os.path.normcase(os.path.abspath(Path(path).resolve()))
                != selected_key
            ]
            if mismatches:
                observed = ", ".join(
                    f"{scope}={path}" for scope, path in mismatches
                )
                raise ValueError(
                    "BenefitArea requires both plan HDFs to reference the same "
                    "registered single-TIFF terrain. "
                    f"Plan p{plan_num} records {observed}, but the selected terrain "
                    f"is {selected_hdf}. RAS Mapper uses plan-HDF terrain "
                    "associations when storing Depth maps; terrain visibility alone "
                    "does not override them. "
                    f"{RasBenefits.TERRAIN_REMEDIATION}"
                )
        return selected_hdf

    @staticmethod
    @_serialize_store_maps
    @log_call
    def store_benefit_area(
        post_plan_number: str,
        config: BenefitAreaConfig,
        *,
        output_path: Union[str, Path] = None,
        profile: str = "Max",
        render_mode: str = None,
        terrain_name: Optional[str] = None,
        include_wse: Optional[bool] = None,
        post_depth: bool = True,
        post_velocity: bool = False,
        post_froude: bool = False,
        post_shear_stress: bool = False,
        post_depth_x_velocity: bool = False,
        post_depth_x_velocity_sq: bool = False,
        post_inundation_boundary: bool = False,
        post_arrival_time: bool = False,
        post_duration: bool = False,
        post_percent_inundated: bool = False,
        arrival_depth: float = 0.0,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600,
        _log_summary: bool = True,
    ) -> Dict[str, List[Path]]:
        """Generate paired Depth maps and derive one BenefitArea product."""

        if not isinstance(config, BenefitAreaConfig):
            raise TypeError("config must be a BenefitAreaConfig")
        if not post_depth:
            raise ValueError("Depth generation cannot be disabled for BenefitArea")

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        pre_plan = RasUtils.normalize_ras_number(config.pre_plan_number)
        post_plan = RasUtils.normalize_ras_number(post_plan_number)
        if pre_plan == post_plan:
            raise ValueError("BenefitArea pre- and post-project plans must be different")

        terrain_path = Path(config.terrain_tif)
        if terrain_name and config.terrain_name and (
            terrain_name.casefold() != config.terrain_name.casefold()
        ):
            raise ValueError(
                "terrain_name conflicts with BenefitAreaConfig.terrain_name"
            )
        selected_terrain = RasProcess._resolve_benefit_terrain_name(
            ras_obj,
            terrain_path,
            terrain_name or config.terrain_name,
        )
        RasProcess._require_common_benefit_terrain_association(
            ras_obj,
            (pre_plan, post_plan),
            selected_terrain,
        )
        terrain_path = terrain_path.resolve()
        effective_wse = config.include_wse if include_wse is None else bool(include_wse)

        if output_path is None:
            root_output = (
                Path(ras_obj.project_folder)
                / "BenefitArea"
                / f"p{pre_plan}-to-p{post_plan}"
            )
        else:
            root_output = Path(output_path)
            if not root_output.is_absolute():
                root_output = Path(ras_obj.project_folder) / root_output
        root_output.mkdir(parents=True, exist_ok=True)
        pre_output = root_output / f"p{pre_plan}"
        post_output = root_output / f"p{post_plan}"

        def map_plan(
            plan_number: str,
            plan_output: Path,
            *,
            include_post_maps: bool,
        ) -> Dict[str, List[Path]]:
            project_name = getattr(ras_obj, "project_name", "")
            plan_hdf = (
                Path(ras_obj.project_folder)
                / f"{project_name}.p{plan_number}.hdf"
            )
            last_reason = "stored map was not produced"
            last_result: Dict[str, List[Path]] = {}
            for attempt in range(1, 4):
                result = RasProcess.store_maps(
                    plan_number=plan_number,
                    output_path=plan_output,
                    profile=profile,
                    render_mode=render_mode,
                    wse=effective_wse,
                    depth=True,
                    velocity=post_velocity if include_post_maps else False,
                    froude=post_froude if include_post_maps else False,
                    shear_stress=(
                        post_shear_stress if include_post_maps else False
                    ),
                    depth_x_velocity=(
                        post_depth_x_velocity if include_post_maps else False
                    ),
                    depth_x_velocity_sq=(
                        post_depth_x_velocity_sq if include_post_maps else False
                    ),
                    inundation_boundary=(
                        post_inundation_boundary if include_post_maps else False
                    ),
                    arrival_time=(
                        post_arrival_time if include_post_maps else False
                    ),
                    duration=post_duration if include_post_maps else False,
                    percent_inundated=(
                        post_percent_inundated if include_post_maps else False
                    ),
                    arrival_depth=arrival_depth,
                    clear_existing=clear_existing,
                    terrain_name=selected_terrain,
                    benefit_area=None,
                    fix_georef=fix_georef,
                    ras_object=ras_obj,
                    ras_version=ras_version,
                    timeout=timeout,
                    _log_summary=False,
                )
                last_result = result

                depth_paths = [Path(path) for path in result.get("depth", [])]
                wse_paths = [Path(path) for path in result.get("wse", [])]
                if len(depth_paths) != 1:
                    last_reason = f"found {len(depth_paths)} readable Depth TIFFs"
                elif effective_wse and len(wse_paths) != 1:
                    last_reason = f"found {len(wse_paths)} readable WSE TIFFs"
                elif (
                    not RasProcess._tif_has_data(depth_paths[0])
                    and RasProcess._hdf_has_wet_maximum_depth(plan_hdf)
                ):
                    last_reason = (
                        "Depth TIFF is all NoData while the plan HDF contains wet cells"
                    )
                else:
                    return result

                if attempt < 3:
                    logger.warning(
                        "Retrying BenefitArea source maps for plan p%s "
                        "(attempt %d of 3): %s",
                        plan_number,
                        attempt + 1,
                        last_reason,
                    )

            if "all NoData" in last_reason:
                raise RuntimeError(
                    f"BenefitArea source-map generation failed for plan p{plan_number} "
                    f"after 3 attempts: {last_reason}. Confirm the selected terrain "
                    "is a registered single-TIFF terrain."
                )
            # Preserve the established exact-count validation and error text
            # below after giving transient mapper failures a chance to recover.
            return last_result

        pre_results = map_plan(
            pre_plan,
            pre_output,
            include_post_maps=False,
        )
        post_results = map_plan(
            post_plan,
            post_output,
            include_post_maps=True,
        )

        def require_one(
            result: Dict[str, List[Path]],
            key: str,
            plan: str,
        ) -> Path:
            paths = [Path(item) for item in result.get(key, [])]
            if len(paths) != 1:
                raise RuntimeError(
                    f"BenefitArea requires exactly one {key.replace('_', ' ').title()} "
                    f"GeoTIFF for plan p{plan}; found {len(paths)}. Confirm the "
                    "selected terrain is a registered single-TIFF terrain."
                )
            return paths[0]

        pre_depth_path = require_one(pre_results, "depth", pre_plan)
        post_depth_path = require_one(post_results, "depth", post_plan)
        pre_wse_path: Optional[Path] = None
        post_wse_path: Optional[Path] = None
        if effective_wse:
            # Validate every requested source map before publishing the derived
            # product so a partial WSE run cannot leave a successful-looking
            # BenefitArea raster behind.
            pre_wse_path = require_one(pre_results, "wse", pre_plan)
            post_wse_path = require_one(post_results, "wse", post_plan)
        safe_profile = profile.replace(":", " ").replace("/", "_")
        benefit_path = root_output / (
            f"Benefit Area ({safe_profile}).p{pre_plan}-to-p{post_plan}.tif"
        )

        polygon_output = config.polygon_output
        if polygon_output is True:
            polygon_output = benefit_path.with_suffix(".gpkg")
        elif polygon_output:
            polygon_output = Path(polygon_output)
            if not polygon_output.is_absolute():
                polygon_output = root_output / polygon_output

        benefit_result = RasBenefits.create_benefit_area(
            pre_depth_path,
            post_depth_path,
            terrain_path,
            benefit_path,
            flood_min_depth=config.flood_min_depth,
            benefit_min_depth=config.benefit_min_depth,
            minimum_region_pixels=config.minimum_region_pixels,
            analysis_boundary=config.analysis_boundary,
            improvement_boundary=config.improvement_boundary,
            polygon_output=polygon_output,
            polygon_simplify_tolerance=config.polygon_simplify_tolerance,
        )

        generated: Dict[str, List[Path]] = {
            key: [Path(path) for path in paths]
            for key, paths in post_results.items()
        }
        generated["benefit_source_pre_depth"] = [pre_depth_path]
        generated["benefit_source_post_depth"] = [post_depth_path]
        if effective_wse:
            generated["benefit_source_pre_wse"] = [pre_wse_path]
            generated["benefit_source_post_wse"] = [post_wse_path]
        generated["benefit_area"] = [benefit_result.raster_path]
        if benefit_result.polygon_path is not None:
            generated["benefit_area_polygon"] = [benefit_result.polygon_path]

        if _log_summary:
            logger.info(
                "BenefitArea stored-map workflow complete: pre=p%s; post=p%s; "
                "wse=%s; filter=%s; polygon=%s",
                pre_plan,
                post_plan,
                effective_wse,
                config.minimum_region_pixels,
                benefit_result.polygon_path is not None,
            )
        return generated

    @staticmethod
    @_serialize_store_maps
    @log_call
    def store_maps(
        plan_number: str,
        output_folder: str = None,
        output_path: Union[str, Path] = None,
        profile: str = "Max",
        render_mode: str = None,
        wse: Optional[bool] = None,
        depth: Optional[bool] = None,
        velocity: Optional[bool] = None,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        inundation_boundary: bool = False,
        arrival_time: bool = False,
        duration: bool = False,
        percent_inundated: bool = False,
        arrival_depth: float = 0.0,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600,
        _log_summary: bool = True,
        terrain_name: Optional[str] = None,
        benefit_area: Optional[BenefitAreaConfig] = None,
    ) -> Dict[str, List[Path]]:
        """
        Generate stored maps for a plan using RasStoreMapHelper.exe.

        This method:
        1. Configures stored maps in the .rasmap file
        2. Runs the packaged mapper helper and HEC-RAS mapping libraries
        3. Optionally fixes georeferencing on output TIFs

        Works on both Windows (native) and Linux (via Wine, auto-detected).

        Output Path Behavior:
            The ``StoreAllMaps`` CLI command always writes output to
            ``<project_folder>/<Plan ShortID>/``. When ``output_path`` is
            specified, this method runs ``StoreAllMaps`` to the default
            location, then moves the generated files to the requested
            directory. This avoids a HEC-RAS 6.6 bug where individual
            ``StoreMap`` commands with absolute ``OutputBaseFilename``
            crash with ``NullReferenceException`` in
            ``SetProjectionInfo()`` on multi-terrain projects.

        Args:
            plan_number: Plan number (e.g., "01", "06")
            output_folder: Output folder name used in .rasmap StoredFilename
                paths (default: plan name from rasmap). This does NOT control
                where the HEC-RAS mapping command writes files — see output_path.
            output_path: Custom output directory for generated rasters (str
                or Path). If provided, ``StoreAllMaps`` runs to the default
                Plan ShortID folder, then files are moved to this directory.
                Accepts relative or absolute paths — relative paths are
                resolved against the project folder. If None (default),
                files remain in ``<project_folder>/<Plan ShortID>/``.
            profile: Profile to map - "Max", "Min", or specific timestamp string
            render_mode: Water surface rendering mode to set before generating
                maps. Options: "horizontal", "sloping", "slopingPretty".
                If None (default), uses whatever mode is already in the .rasmap.
            wse: Generate Water Surface Elevation map. Defaults to True for
                ordinary stored-map generation and False for BenefitArea unless
                ``BenefitAreaConfig.include_wse`` is True.
            depth: Generate Depth map (default: True). BenefitArea always
                requires Depth and rejects False.
            velocity: Generate Velocity map. Defaults to True for ordinary
                stored-map generation and False for BenefitArea.
            froude: Generate Froude number map (default: False)
            shear_stress: Generate Shear Stress map (default: False)
            depth_x_velocity: Generate D*V hazard map (default: False)
            depth_x_velocity_sq: Generate D*V² impact map (default: False)
            inundation_boundary: Generate inundation boundary polygon (default: False)
            arrival_time: Generate flood Arrival Time map in hours (default: False).
                Whole-simulation product; ignores the ``profile`` argument.
            duration: Generate inundation Duration map in hours (default: False).
                Whole-simulation product; ignores the ``profile`` argument.
            percent_inundated: Generate Percent Time Inundated map (default: False).
                Whole-simulation product; ignores the ``profile`` argument.
            arrival_depth: Wet/dry depth threshold (model vertical units) for
                arrival_time / duration / percent_inundated maps (default: 0.0).
                Appears in output filenames, e.g. "Arrival Time (0.1ft hrs)".
            terrain_name: Registered RAS Mapper terrain to select exclusively
                while generating maps. BenefitArea requires this terrain to
                resolve to the single GeoTIFF in its configuration.
            benefit_area: Optional BenefitArea configuration. When provided,
                ``plan_number`` is the post-project plan and the configured
                pre-project plan is mapped separately before the categorical
                BenefitArea raster is calculated.
            clear_existing: Clear existing stored maps before adding new ones (default: True)
            fix_georef: Apply georeferencing fix to output TIFs (default: True)
            ras_object: Optional RAS object instance
            ras_version: Optional specific HEC-RAS mapping-runtime version
            timeout: Command timeout in seconds (default: 600)

        Returns:
            Dict mapping map type names to lists of generated file paths.
            Paths point to ``output_path`` if specified (files are moved
            there after generation), otherwise to the default Plan ShortID
            folder.

        Raises:
            FileNotFoundError: If the mapper helper or required files are not found
            RuntimeError: If the HEC-RAS mapping command fails

        Example:
            >>> # Default output (writes to ./PlanShortID/)
            >>> results = RasProcess.store_maps(
            ...     plan_number="01",
            ...     profile="Max",
            ...     wse=True,
            ...     depth=True
            ... )

            >>> # Custom output path
            >>> results = RasProcess.store_maps(
            ...     plan_number="01",
            ...     output_path="C:/MyProject/CustomMaps",
            ...     profile="Max",
            ...     wse=True,
            ...     depth=True,
            ...     velocity=True
            ... )
            >>> print(results['wse'])
            [Path('C:/MyProject/CustomMaps/WSE (Max).Terrain.tif')]
        """
        # HISTORY: Prior to 2026-03-24, this used RasProcess.exe StoreAllMaps
        # which ignores RenderMode in HEC-RAS 6.x. Now uses RasStoreMapHelper.exe
        # which sets SharedData render mode via .NET reflection before executing
        # StoreAllMapsCommand, producing pixel-perfect output.

        if benefit_area is not None:
            if not isinstance(benefit_area, BenefitAreaConfig):
                raise TypeError("benefit_area must be a BenefitAreaConfig")
            if depth is False:
                raise ValueError("Depth generation cannot be disabled for BenefitArea")
            if output_folder is not None:
                raise ValueError(
                    "output_folder is not supported for BenefitArea because two plans "
                    "are mapped separately; use output_path for the comparison root"
                )

            effective_wse = (
                benefit_area.include_wse if wse is None else bool(wse)
            )
            return RasProcess.store_benefit_area(
                post_plan_number=plan_number,
                config=benefit_area,
                output_path=output_path,
                profile=profile,
                render_mode=render_mode,
                terrain_name=terrain_name,
                include_wse=effective_wse,
                post_depth=True,
                post_velocity=False if velocity is None else bool(velocity),
                post_froude=froude,
                post_shear_stress=shear_stress,
                post_depth_x_velocity=depth_x_velocity,
                post_depth_x_velocity_sq=depth_x_velocity_sq,
                post_inundation_boundary=inundation_boundary,
                post_arrival_time=arrival_time,
                post_duration=duration,
                post_percent_inundated=percent_inundated,
                arrival_depth=arrival_depth,
                clear_existing=clear_existing,
                fix_georef=fix_georef,
                ras_object=ras_object,
                ras_version=ras_version,
                timeout=timeout,
                _log_summary=_log_summary,
            )

        # Preserve the long-standing ordinary StoreMaps defaults while allowing
        # BenefitArea to use a cheaper Depth-only default above.
        wse = True if wse is None else bool(wse)
        depth = True if depth is None else bool(depth)
        velocity = True if velocity is None else bool(velocity)

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Locate HEC-RAS directory
        hecras_dir = Path(str(ras_obj.ras_exe_path)).parent
        if not hecras_dir.exists():
            raise FileNotFoundError(f"HEC-RAS directory not found: {hecras_dir}")

        # Get paths
        plan_num = RasUtils.normalize_ras_number(plan_number)
        rasmap_path = RasMap.get_rasmap_path(ras_obj)
        if rasmap_path is None:
            raise FileNotFoundError(f"No .rasmap file found in project folder")

        plan_hdf = f"{ras_obj.project_name}.p{plan_num}.hdf"
        plan_hdf_path = ras_obj.project_folder / plan_hdf

        if not plan_hdf_path.exists():
            raise FileNotFoundError(f"Plan HDF not found: {plan_hdf_path}")

        # RasProcess.exe uses the Plan ShortID from HDF to determine output folder name
        # This is the authoritative source - rasmap Layer Name should match but isn't used by RasProcess
        plan_short_id = RasProcess._get_plan_short_id(plan_hdf_path)

        # Get the output folder from rasmap Layer Name (should match Plan ShortID)
        tree = ET.parse(_windows_extended_length_path(rasmap_path))
        root = tree.getroot()
        output_folder_from_rasmap = None
        plan_basename = Path(plan_hdf).name.lower()
        for layer in root.findall(".//Results/Layer"):
            filename = layer.get("Filename", "")
            if Path(filename).name.lower() == plan_basename:
                output_folder_from_rasmap = layer.get("Name")
                break

        # Determine output folder - priority: Plan ShortID > rasmap Layer Name > user-provided > default
        if plan_short_id:
            actual_output_folder = plan_short_id
        elif output_folder_from_rasmap:
            actual_output_folder = output_folder_from_rasmap
        elif output_folder:
            actual_output_folder = output_folder
        else:
            actual_output_folder = f"Plan_{plan_num}"

        # Use actual output folder for the StoredFilename paths in rasmap
        if output_folder is None:
            output_folder = actual_output_folder

        output_dir = ras_obj.project_folder / actual_output_folder
        os.makedirs(_windows_extended_length_path(output_dir), exist_ok=True)

        logger.debug(f"Plan ShortID from HDF: {plan_short_id}")
        logger.debug(f"Output folder from rasmap: {output_folder_from_rasmap}")
        logger.debug(f"Actual output directory: {output_dir}")

        # Determine profile index
        if profile.upper() in ("MAX", "MIN"):
            profile_index = 2147483647  # Special value for Max/Min
            profile_name = profile.title()  # "Max" or "Min"
        else:
            # Specific timestamp - need to find index
            timestamps = RasProcess.get_plan_timestamps(plan_num, ras_obj)
            try:
                profile_index = timestamps.index(profile)
                profile_name = profile
            except ValueError:
                logger.warning(f"Timestamp '{profile}' not found. Available: {timestamps[:5]}...")
                profile_index = 2147483647
                profile_name = "Max"

        # Backup rasmap
        rasmap_backup = rasmap_path.with_name(
            f".{rasmap_path.name}.{os.getpid()}.{uuid.uuid4().hex}.bak"
        )
        shutil.copy2(
            _windows_extended_length_path(rasmap_path),
            _windows_extended_length_path(rasmap_backup),
        )

        try:
            if terrain_name is not None:
                RasProcess._select_terrain_for_mapping(
                    rasmap_path,
                    terrain_name,
                    ras_object=ras_obj,
                )

            # Set render mode if requested (before modifying stored maps)
            if render_mode is not None:
                RasMap.set_water_surface_render_mode(
                    mode=render_mode,
                    ras_object=ras_obj,
                )
                logger.debug(f"Set render mode to '{render_mode}' before StoreAllMaps")

            # Clear existing stored maps if requested
            if clear_existing:
                RasProcess._remove_stored_maps_from_rasmap(rasmap_path, plan_hdf)

            # Build list of maps to generate
            maps_to_add = []
            if wse:
                maps_to_add.append(('elevation', 'wse'))
            if depth:
                maps_to_add.append(('depth', 'depth'))
            if velocity:
                maps_to_add.append(('velocity', 'velocity'))
            if froude:
                maps_to_add.append(('froude', 'froude'))
            if shear_stress:
                maps_to_add.append(('Shear', 'shear_stress'))
            if depth_x_velocity:
                maps_to_add.append(('depth and velocity', 'depth_x_velocity'))
            if depth_x_velocity_sq:
                maps_to_add.append(('depth and velocity squared', 'depth_x_velocity_sq'))

            # Whole-simulation map types: always Max profile, labeled by the
            # ArrivalDepth threshold (e.g. "Arrival Time (0.1ft hrs)") rather
            # than the profile name. XML names come from MAP_TYPES — the
            # single source of truth for RasMapperLib name strings.
            adr_flags = {
                'arrival_time': arrival_time,
                'duration': duration,
                'percent_inundated': percent_inundated,
            }
            adr_maps_to_add = [
                (RasProcess.MAP_TYPES[key][0], key)
                for key, enabled in adr_flags.items()
                if enabled
            ]

            # Add stored maps to rasmap
            for map_type, _ in maps_to_add:
                RasProcess._add_stored_map_to_rasmap(
                    rasmap_path,
                    plan_hdf,
                    map_type,
                    profile_name,
                    output_folder,
                    profile_index
                )

            for map_type, _ in adr_maps_to_add:
                RasProcess._add_stored_map_to_rasmap(
                    rasmap_path,
                    plan_hdf,
                    map_type,
                    "Max",
                    output_folder,
                    2147483647,
                    extra_attrs={"ArrivalDepth": str(arrival_depth)},
                )

            # Add inundation boundary if requested (shapefile polygon output)
            if inundation_boundary:
                RasProcess._add_stored_map_to_rasmap(
                    rasmap_path,
                    plan_hdf,
                    'depth',
                    profile_name,
                    output_folder,
                    profile_index,
                    output_mode="Stored Polygon Specified Depth",
                )

            # Resolve output_path to absolute if provided
            resolved_output_path = None
            if output_path is not None:
                resolved_output_path = Path(output_path)
                if not resolved_output_path.is_absolute():
                    resolved_output_path = (ras_obj.project_folder / resolved_output_path).resolve()
                os.makedirs(
                    _windows_extended_length_path(resolved_output_path),
                    exist_ok=True,
                )

            # Snapshot pre-existing files in output_dir so we only move files
            # that were created or changed by this StoreAllMaps call when
            # output_path is specified. This preserves unrelated benchmark or
            # manually curated files while still relocating regenerated rasters
            # that overwrite the same filenames on reruns.
            pre_existing_files = {}
            if os.path.isdir(_windows_extended_length_path(output_dir)):
                for item in _iterdir_paths(output_dir):
                    try:
                        stat = os.stat(_windows_extended_length_path(item))
                    except FileNotFoundError:
                        continue
                    pre_existing_files[item.name] = (
                        stat.st_mtime_ns,
                        stat.st_size,
                    )

            # Use RasStoreMapHelper.exe instead of RasProcess.exe.
            # RasStoreMapHelper sets SharedData render mode via .NET reflection
            # before calling StoreAllMapsCommand.Execute(), fixing the 6.x bug
            # where RasProcess.exe ignores the RenderMode from the .rasmap.

            current_mode = render_mode
            if current_mode is None:
                current_mode = RasMap.get_water_surface_render_mode(
                    ras_object=ras_obj,
                )

            helper_mode = normalize_store_map_render_mode(current_mode)

            logger.debug("Running StoreAllMaps for plan %s (mode=%s)", plan_num, helper_mode)

            effective_ras_version = ras_version or getattr(
                ras_obj,
                "ras_version",
                None,
            )
            with RasProcess._mapper_compatible_result_hdf(
                plan_hdf_path,
                effective_ras_version,
            ) as mapper_hdf_path:
                result = run_store_all_maps_helper(
                    hecras_dir=hecras_dir,
                    render_mode=helper_mode,
                    rasmap_path=rasmap_path,
                    result_hdf_path=mapper_hdf_path,
                    timeout=timeout,
                    working_dir=ras_obj.project_folder,
                )

            logger.debug(f"StoreAllMaps stdout: {result.stdout}")
            if result.stderr:
                stderr_lines = result.stderr.splitlines()
                stderr_preview = stderr_lines[0] if stderr_lines else result.stderr[:200]
                logger.warning("StoreAllMaps reported stderr: %s", stderr_preview)
                logger.debug("StoreAllMaps full stderr: %s", result.stderr)
            if result.returncode != 0:
                stderr_detail = next(
                    (
                        line.strip()
                        for line in result.stderr.splitlines()
                        if line.strip()
                    ),
                    "",
                )
                detail_suffix = (
                    f": {stderr_detail[:500]}" if stderr_detail else ""
                )
                raise RuntimeError(
                    "StoreAllMaps failed for plan "
                    f"{plan_num} (exit code {result.returncode}){detail_suffix}"
                )

            for line in result.stdout.splitlines():
                if "Maps generated" in line:
                    logger.debug(line.strip())

            # Identify this invocation's outputs before looking up requested
            # map names.  Filtering every return value through this set keeps
            # an old TIFF from being reported as fresh output when the helper
            # succeeds without producing a requested map.
            fresh_source_files = []
            for item in _iterdir_paths(output_dir):
                try:
                    stat = os.stat(_windows_extended_length_path(item))
                except FileNotFoundError:
                    continue
                if not os.path.isfile(_windows_extended_length_path(item)):
                    continue
                previous_signature = pre_existing_files.get(item.name)
                current_signature = (stat.st_mtime_ns, stat.st_size)
                if previous_signature != current_signature:
                    fresh_source_files.append(item)

            search_dir = output_dir
            produced_paths = list(fresh_source_files)

            # If output_path was requested, move files from default dir to output_path
            if (
                resolved_output_path is not None
                and os.path.normcase(os.path.abspath(resolved_output_path))
                != os.path.normcase(os.path.abspath(output_dir))
            ):
                logger.debug(
                    "Moving generated files from %s to %s",
                    output_dir,
                    resolved_output_path,
                )
                moved_count = 0
                moved_paths = []
                # Move files that were created or modified by this call.
                for item in fresh_source_files:
                    # PostProcessing.hdf is RasMapperLib's derived-map cache
                    # (can exceed the plan HDF in size): leave it beside the
                    # plan so reruns reuse it instead of paying a potentially
                    # cross-volume move of a multi-GB scratch file.
                    if item.name == "PostProcessing.hdf":
                        continue
                    dest = resolved_output_path / item.name
                    dest_move_path = _windows_extended_length_path(dest)
                    if os.path.exists(dest_move_path):
                        os.remove(dest_move_path)
                    shutil.move(
                        _windows_extended_length_path(item),
                        dest_move_path,
                    )
                    moved_paths.append(dest)
                    moved_count += 1
                logger.debug(
                    "Moved %d generated file(s) to %s",
                    moved_count,
                    resolved_output_path,
                )

                search_dir = resolved_output_path
                produced_paths = moved_paths

            def fresh_glob(pattern):
                """Return matching files only when produced by this call."""
                produced_keys = {
                    os.path.normcase(os.path.abspath(path))
                    for path in produced_paths
                }
                return [
                    path
                    for path in _glob_paths(search_dir, pattern)
                    if os.path.normcase(os.path.abspath(path)) in produced_keys
                ]

            # Find generated files in the appropriate directory
            generated_files = {}
            for map_type, map_key in maps_to_add:
                for key, (xml_name, display_name, _) in RasProcess.MAP_TYPES.items():
                    if xml_name == map_type:
                        display_name_used = display_name
                        break
                else:
                    display_name_used = map_type.title()

                safe_profile = profile_name.replace(":", " ").replace("/", "_")
                pattern = f"{display_name_used} ({safe_profile})*.tif"
                tif_files = fresh_glob(pattern)

                if not tif_files:
                    pattern_alt = f"{display_name_used.replace(' ', '_')} ({safe_profile})*.tif"
                    tif_files = fresh_glob(pattern_alt)

                if tif_files:
                    generated_files[map_key] = tif_files
                    logger.debug("Generated %d %s TIF(s)", len(tif_files), map_key)
                else:
                    logger.debug(f"No TIF files found for {map_key} with pattern: {pattern}")

            # Whole-simulation types label outputs by threshold, not profile
            # (e.g. "Arrival Time (0.1ft hrs).Terrain.tile.tif") — glob by
            # display-name prefix, restricted to files produced by this run so
            # a rerun at a different arrival_depth never collects the previous
            # threshold's rasters.
            for map_type, map_key in adr_maps_to_add:
                display_name_used = RasProcess.MAP_TYPES[map_key][1]

                pattern = f"{display_name_used} (*.tif"
                tif_files = fresh_glob(pattern)
                if tif_files:
                    generated_files[map_key] = tif_files
                    logger.info(f"Generated {len(tif_files)} {map_key} TIF(s)")
                else:
                    logger.debug(f"No TIF files found for {map_key} with pattern: {pattern}")

            # Collect inundation boundary shapefile if requested
            if inundation_boundary:
                safe_profile = profile_name.replace(":", " ").replace("/", "_")
                shp_pattern = f"Inundation Boundary ({safe_profile})*.shp"
                shp_files = fresh_glob(shp_pattern)
                if not shp_files:
                    shp_pattern_alt = f"Inundation_Boundary*({safe_profile})*.shp"
                    shp_files = fresh_glob(shp_pattern_alt)
                if shp_files:
                    generated_files['inundation_boundary'] = shp_files
                    logger.debug(
                        "Generated %d inundation boundary shapefile(s)",
                        len(shp_files),
                    )
                else:
                    logger.debug(f"No inundation boundary shapefiles found with pattern: {shp_pattern}")

            # Fix georeferencing if requested
            if fix_georef and generated_files:
                proj_info = RasProcess._get_projection_info(rasmap_path)
                terrain_paths = proj_info.terrain_paths
                if not terrain_paths and proj_info.terrain_path is not None:
                    terrain_paths = (proj_info.terrain_path,)
                if terrain_paths:
                    if proj_info.prj_path is None:
                        logger.debug(
                            "Projection file referenced by %s was not found; "
                            "using terrain CRS for georef fix instead.",
                            rasmap_path.name,
                        )
                    for tif_list in generated_files.values():
                        for tif_path in tif_list:
                            if Path(tif_path).suffix.lower() not in {".tif", ".tiff"}:
                                continue
                            terrain_path = RasProcess._terrain_for_stored_map(
                                tif_path,
                                terrain_paths,
                            )
                            if terrain_path is None:
                                logger.warning(
                                    "Could not match stored-map TIFF to one of %d "
                                    "terrain rasters; georeferencing was not changed: %s",
                                    len(terrain_paths),
                                    tif_path,
                                )
                                continue
                            RasProcess._fix_georeferencing(
                                tif_path,
                                proj_info.prj_path,
                                terrain_path,
                            )
                else:
                    logger.warning("Could not find terrain for georef fix")
                RasProcess._drop_unreadable_tifs(generated_files)

            generated_file_count = sum(len(paths) for paths in generated_files.values())
            if _log_summary:
                logger.info(
                    "StoreAllMaps complete: plan=%s; mode=%s; map_types=%d; files=%d",
                    plan_num,
                    helper_mode,
                    len(generated_files),
                    generated_file_count,
                )
            return generated_files

        finally:
            # Restore rasmap backup
            rasmap_backup_path = _windows_extended_length_path(rasmap_backup)
            if os.path.exists(rasmap_backup_path):
                shutil.copy2(
                    rasmap_backup_path,
                    _windows_extended_length_path(rasmap_path),
                )
                os.remove(rasmap_backup_path)

    @staticmethod
    @log_call
    def store_maps_at_timesteps(
        plan_number: str,
        output_path: Union[str, Path] = None,
        timesteps: Optional[Union[int, str, datetime, List[Union[int, str, datetime]]]] = None,
        max_timesteps: Optional[int] = None,
        wse: bool = False,
        depth: bool = True,
        velocity: bool = False,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        render_mode: str = None,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600,
    ) -> Dict[str, Dict[str, List[Path]]]:
        """
        Generate stored maps for one or more output timesteps.

        This convenience wrapper routes each selected timestep through
        ``store_maps(profile=<timestamp>)`` so callers can export a sequence of
        rasters suitable for animation.

        Args:
            plan_number: Plan number (e.g., "02").
            output_path: Optional directory for generated rasters.
            timesteps: Optional timestep selector. Items may be zero-based
                integer indices, exact RASMapper timestamp strings, or datetimes.
                If omitted, all available output timesteps are used.
            max_timesteps: Optional cap applied after timestep selection.
            wse, depth, velocity, froude, shear_stress, depth_x_velocity,
                depth_x_velocity_sq: Map types to export. Defaults to Depth only.
            render_mode, clear_existing, fix_georef, ras_object, ras_version,
                timeout: Passed through to ``store_maps``.

        Returns:
            Dict keyed by RASMapper timestamp string. Each value is the
            ``store_maps`` result for that timestep.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        available = RasProcess.get_plan_timestamps(plan_number, ras_obj)
        if not available:
            raise ValueError(f"No output timesteps found for plan {plan_number}")

        selected = RasProcess._select_store_map_timesteps(available, timesteps)
        if max_timesteps is not None:
            selected = selected[: int(max_timesteps)]
        if not selected:
            raise ValueError("No timesteps selected for stored map export")

        results: Dict[str, Dict[str, List[Path]]] = {}
        for timestamp in selected:
            results[timestamp] = RasProcess.store_maps(
                plan_number=plan_number,
                output_path=output_path,
                profile=timestamp,
                render_mode=render_mode,
                wse=wse,
                depth=depth,
                velocity=velocity,
                froude=froude,
                shear_stress=shear_stress,
                depth_x_velocity=depth_x_velocity,
                depth_x_velocity_sq=depth_x_velocity_sq,
                clear_existing=clear_existing,
                fix_georef=fix_georef,
                ras_object=ras_obj,
                ras_version=ras_version,
                timeout=timeout,
                _log_summary=False,
            )
            timestep_file_count = sum(len(paths) for paths in results[timestamp].values())
            logger.debug(
                "StoreAllMaps timestep complete: plan=%s; timestep=%s; files=%d",
                plan_number,
                timestamp,
                timestep_file_count,
            )

        map_types = {
            map_type
            for timestep_results in results.values()
            for map_type, paths in timestep_results.items()
            if paths
        }
        total_files = sum(
            len(paths)
            for timestep_results in results.values()
            for paths in timestep_results.values()
        )
        logger.info(
            "StoreAllMaps timesteps complete: plan=%s; timesteps=%d; map_types=%d; files=%d",
            RasUtils.normalize_ras_number(plan_number),
            len(selected),
            len(map_types),
            total_files,
        )
        return results

    @staticmethod
    def _select_store_map_timesteps(
        available: List[str],
        timesteps: Optional[Union[int, str, datetime, List[Union[int, str, datetime]]]],
    ) -> List[str]:
        if timesteps is None:
            return list(available)
        if isinstance(timesteps, (int, str, datetime, pd.Timestamp)):
            requested = [timesteps]
        else:
            requested = list(timesteps)

        selected: List[str] = []
        for item in requested:
            if isinstance(item, int):
                try:
                    selected.append(available[item])
                except IndexError as exc:
                    raise ValueError(
                        f"Timestep index {item} out of range for {len(available)} timesteps"
                    ) from exc
                continue

            if isinstance(item, (datetime, pd.Timestamp)):
                item_text = pd.Timestamp(item).strftime("%d%b%Y %H:%M:%S").upper()
            else:
                item_text = str(item).strip()

            if item_text in available:
                selected.append(item_text)
                continue

            parsed_text = None
            try:
                parsed_text = pd.Timestamp(item_text).strftime("%d%b%Y %H:%M:%S").upper()
            except Exception:
                pass
            if parsed_text in available:
                selected.append(parsed_text)
                continue

            raise ValueError(
                f"Timestep {item!r} not found. First available timesteps: {available[:5]}"
            )

        return selected

    @staticmethod
    @log_call
    def store_all_maps(
        output_folder: str = None,
        output_path: Union[str, Path] = None,
        profile: str = "Max",
        wse: bool = True,
        depth: bool = True,
        velocity: bool = True,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 1800
    ) -> Dict[str, Dict[str, List[Path]]]:
        """
        Generate stored maps for all plans in the project.

        This is a convenience wrapper around store_maps() that processes
        all plans with HDF results.

        Args:
            output_folder: Base output folder (plan name appended). If None, uses plan titles.
            output_path: Custom output directory. If provided, a subdirectory per plan
                is created (e.g., ``output_path/plan_01/``). See store_maps() for details.
            profile: Profile to map - "Max", "Min", or specific timestamp
            wse: Generate WSE maps (default: True)
            depth: Generate Depth maps (default: True)
            velocity: Generate Velocity maps (default: True)
            froude: Generate Froude maps (default: False)
            shear_stress: Generate Shear Stress maps (default: False)
            depth_x_velocity: Generate D*V maps (default: False)
            depth_x_velocity_sq: Generate D*V² maps (default: False)
            fix_georef: Apply georeferencing fix (default: True)
            ras_object: Optional RAS object instance
            ras_version: Optional specific HEC-RAS version
            timeout: Timeout per plan in seconds (default: 1800)

        Returns:
            Dict mapping plan numbers to their generated files dict.

        Example:
            >>> all_results = RasProcess.store_all_maps(profile="Max")
            >>> for plan, files in all_results.items():
            ...     print(f"Plan {plan}: {len(files.get('wse', []))} WSE files")
        """
        # HISTORY: Prior to 2026-03-24, this was deprecated because it delegated
        # to store_maps() which used RasProcess.exe (ignores RenderMode in 6.x).
        # Now uses RasStoreMapHelper.exe via store_maps().

        all_results = {}

        # Get plans with HDF results
        for _, row in ras_obj.plan_df.iterrows():
            plan_num = row['plan_number']
            hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_num}.hdf"

            if not hdf_path.exists():
                logger.debug(f"Skipping plan {plan_num} - no HDF results")
                continue

            # Determine output folder for this plan
            if output_folder:
                plan_output = f"{output_folder}_{plan_num}"
            else:
                plan_output = None  # Will use plan title

            # Per-plan output_path subdirectory
            plan_output_path = None
            if output_path is not None:
                plan_output_path = Path(output_path) / f"plan_{plan_num}"

            try:
                results = RasProcess.store_maps(
                    plan_number=plan_num,
                    output_folder=plan_output,
                    output_path=plan_output_path,
                    profile=profile,
                    wse=wse,
                    depth=depth,
                    velocity=velocity,
                    froude=froude,
                    shear_stress=shear_stress,
                    depth_x_velocity=depth_x_velocity,
                    depth_x_velocity_sq=depth_x_velocity_sq,
                    fix_georef=fix_georef,
                    ras_object=ras_obj,
                    ras_version=ras_version,
                    timeout=timeout
                )
                all_results[plan_num] = results

            except Exception as e:
                logger.error(f"Failed to generate maps for plan {plan_num}: {e}")
                all_results[plan_num] = {'error': str(e)}

        return all_results

    @staticmethod
    @log_call
    def run_command(
        command_xml: str,
        ras_version: str = None,
        timeout: int = 600
    ) -> subprocess.CompletedProcess:
        """
        Run a raw RasProcess.exe command from XML string.

        This is a low-level method for running arbitrary RasProcess commands.
        See rasmapper_docs/16_rasprocess_cli_reference.md for available commands.

        Works on both Windows (native) and Linux (via Wine).

        Warning:
            ``StoreAllMaps`` commands always write to
            ``<project>/<Plan ShortID>/`` and cannot be redirected.
            To control the output directory, use ``store_maps(output_path=...)``
            which runs ``StoreAllMaps`` then moves files to the requested path.
            Individual ``StoreMap`` commands with absolute ``OutputBaseFilename``
            crash on multi-terrain projects (NullReferenceException in
            ``SetProjectionInfo``), so ``store_maps()`` avoids that approach.

        Args:
            command_xml: XML command string
            ras_version: Optional specific HEC-RAS version
            timeout: Command timeout in seconds

        Returns:
            subprocess.CompletedProcess with stdout/stderr

        Example:
            >>> xml = '''<?xml version="1.0" encoding="utf-8"?>
            ... <Command Type="StoreMap">
            ...   <MapType>depth</MapType>
            ...   <Result>C:/project/plan.p01.hdf</Result>
            ...   <ProfileName>Max</ProfileName>
            ...   <OutputBaseFilename>C:/project/Maps/depth_max</OutputBaseFilename>
            ... </Command>'''
            >>> result = RasProcess.run_command(xml)
        """
        rasprocess = RasProcess.find_rasprocess(ras_version)
        if rasprocess is None:
            raise FileNotFoundError("RasProcess.exe not found")

        # Warn if StoreAllMaps is used — it cannot write to a custom output path
        if 'StoreAllMaps' in command_xml:
            logger.warning(
                "StoreAllMaps always writes to <project>/<Plan ShortID>/. "
                "To write to a custom directory, use store_maps(output_path=...) "
                "which runs StoreAllMaps then moves files to the requested path."
            )

        # Write XML to temp file
        # On Linux, temp file must be within Wine's drive_c for accessibility
        if IS_LINUX:
            wine_config = RasProcess._get_wine_config()
            if wine_config:
                temp_dir = wine_config.wine_prefix / "drive_c" / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                xml_path = temp_dir / f"rasprocess_cmd_{os.getpid()}.xml"
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(command_xml)
                xml_wine_path = RasProcess._linux_to_wine_path(xml_path)
            else:
                raise RuntimeError("Wine not configured on Linux")
        else:
            f = tempfile.NamedTemporaryFile(
                mode='w', suffix='.xml', delete=False, encoding='utf-8'
            )
            f.write(command_xml)
            f.close()
            xml_path = Path(f.name)
            xml_wine_path = str(xml_path)

        try:
            result = RasProcess._run_rasprocess(
                rasprocess,
                [f"-CommandFile={xml_wine_path}"],
                timeout=timeout,
            )

            logger.debug(f"Command output: {result.stdout}")
            if result.stderr:
                stderr_lines = result.stderr.splitlines()
                stderr_preview = stderr_lines[0] if stderr_lines else result.stderr[:200]
                logger.warning("Command reported stderr: %s", stderr_preview)
                logger.debug("Command full stderr: %s", result.stderr)

            return result

        finally:
            if xml_path.exists():
                xml_path.unlink()

    @staticmethod
    @log_call
    def apply_depth_threshold(
        input_tiff: Union[str, Path],
        output_tiff: Union[str, Path],
        min_depth: float = 0.0,
        reproject_wgs84: bool = False,
        ras_object=None
    ) -> Dict[str, Any]:
        """
        Apply depth threshold to a GeoTIFF and optionally reproject to WGS84.

        Cells with values below min_depth are set to NoData. Optionally
        reprojects the raster to EPSG:4326 (WGS84).

        Parameters
        ----------
        input_tiff : str or Path
            Path to input GeoTIFF
        output_tiff : str or Path
            Path for output GeoTIFF
        min_depth : float, default 0.0
            Minimum depth threshold. Cells below this value become NoData.
        reproject_wgs84 : bool, default False
            If True, reproject output to EPSG:4326 (WGS84)
        ras_object : optional
            Custom RAS object (unused, for API consistency)

        Returns
        -------
        dict
            Report with keys: input, output, cells_total, cells_filtered,
            cells_remaining, reprojected

        Example
        -------
        >>> result = RasProcess.apply_depth_threshold(
        ...     'depth_max.tif', 'depth_filtered.tif', min_depth=0.75
        ... )
        >>> print(f"Filtered {result['cells_filtered']} cells below 0.75 ft")
        """
        if not HAS_RASTERIO:
            raise ImportError(
                "rasterio is required for apply_depth_threshold(). "
                "Install with: pip install rasterio"
            )

        input_path = Path(input_tiff)
        output_path = Path(output_tiff)

        if not input_path.exists():
            raise FileNotFoundError(f"Input TIFF not found: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(input_path) as src:
            data = src.read(1)
            profile = src.profile.copy()
            nodata = src.nodata if src.nodata is not None else -9999.0

            # Apply threshold
            mask = (data < min_depth) | np.isnan(data)
            if src.nodata is not None:
                mask = mask | (data == src.nodata)

            cells_total = int(data.size)
            cells_filtered = int(mask.sum())
            data[mask] = nodata

            profile.update(nodata=nodata)

            if reproject_wgs84:
                from rasterio.warp import calculate_default_transform, reproject as rio_reproject
                from rasterio.crs import CRS as RioCRS

                dst_crs = RioCRS.from_epsg(4326)
                transform, width, height = calculate_default_transform(
                    src.crs, dst_crs, src.width, src.height, *src.bounds
                )
                profile.update(crs=dst_crs, transform=transform, width=width, height=height)

                dst_data = np.full((height, width), nodata, dtype=data.dtype)
                rio_reproject(
                    source=data,
                    destination=dst_data,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    src_nodata=nodata,
                    dst_nodata=nodata,
                )
                data = dst_data

            with rasterio.open(output_path, 'w', **profile) as dst:
                dst.write(data, 1)

        logger.debug(
            f"Threshold applied: {cells_filtered}/{cells_total} cells filtered "
            f"(min_depth={min_depth}), output: {output_path.name}"
        )

        return {
            'input': str(input_path),
            'output': str(output_path),
            'cells_total': cells_total,
            'cells_filtered': cells_filtered,
            'cells_remaining': cells_total - cells_filtered,
            'reprojected': reproject_wgs84,
        }

    @staticmethod
    @log_call
    def batch_export_rasters(
        plan_numbers: List[str],
        output_dir: Union[str, Path],
        min_depth: float = 0.0,
        reproject_wgs84: bool = False,
        naming_template: str = "{plan}_{map_type}",
        profile: str = "Max",
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600
    ) -> pd.DataFrame:
        """
        Batch export depth rasters for multiple plans with post-processing.

        Wraps store_maps() for multiple plans, then applies depth threshold
        filtering and optional WGS84 reprojection.

        Parameters
        ----------
        plan_numbers : list of str
            Plan numbers to export (e.g., ['01', '02', '03'])
        output_dir : str or Path
            Directory for processed output rasters
        min_depth : float, default 0.0
            Minimum depth threshold. Cells below this become NoData.
        reproject_wgs84 : bool, default False
            If True, reproject outputs to EPSG:4326
        naming_template : str, default '{plan}_{map_type}'
            Template for output file names. Supports {plan}, {map_type}.
        profile : str, default 'Max'
            Profile to export ('Max', 'Min', or timestamp)
        ras_object : optional
            Custom RAS object to use instead of the global one
        ras_version : str, optional
            HEC-RAS version for RasProcess.exe
        timeout : int, default 600
            Timeout for each store_maps call

        Returns
        -------
        pd.DataFrame
            Report with columns: plan, map_type, source, output,
            cells_filtered, status

        Example
        -------
        >>> report = RasProcess.batch_export_rasters(
        ...     plan_numbers=['01', '02', '03'],
        ...     output_dir='./exported_rasters',
        ...     min_depth=0.75,
        ...     reproject_wgs84=True
        ... )
        >>> print(report[['plan', 'cells_filtered', 'status']])
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        report_rows = []

        for plan_num in plan_numbers:
            plan_num = RasUtils.normalize_ras_number(plan_num)

            # Generate raw TIFs via store_maps
            try:
                map_results = RasProcess.store_maps(
                    plan_number=plan_num,
                    profile=profile,
                    depth=True,
                    wse=True,
                    velocity=False,
                    ras_object=ras_obj,
                    ras_version=ras_version,
                    timeout=timeout
                )
            except Exception as e:
                logger.error(f"store_maps failed for plan {plan_num}: {e}")
                report_rows.append({
                    'plan': plan_num,
                    'map_type': 'all',
                    'source': None,
                    'output': None,
                    'cells_filtered': 0,
                    'status': f'error: {e}',
                })
                continue

            # Post-process each generated TIF
            for map_type, tif_list in map_results.items():
                for tif_path in tif_list:
                    tif_path = Path(tif_path)
                    if not tif_path.exists():
                        continue

                    out_name = naming_template.format(
                        plan=plan_num, map_type=map_type
                    ) + '.tif'
                    out_path = output_path / out_name

                    try:
                        if HAS_RASTERIO and (min_depth > 0 or reproject_wgs84):
                            result = RasProcess.apply_depth_threshold(
                                tif_path, out_path,
                                min_depth=min_depth,
                                reproject_wgs84=reproject_wgs84
                            )
                            cells_filtered = result['cells_filtered']
                        else:
                            # Just copy the file
                            import shutil
                            shutil.copy2(tif_path, out_path)
                            cells_filtered = 0

                        report_rows.append({
                            'plan': plan_num,
                            'map_type': map_type,
                            'source': str(tif_path),
                            'output': str(out_path),
                            'cells_filtered': cells_filtered,
                            'status': 'exported',
                        })
                    except Exception as e:
                        logger.error(f"Post-processing failed for {tif_path.name}: {e}")
                        report_rows.append({
                            'plan': plan_num,
                            'map_type': map_type,
                            'source': str(tif_path),
                            'output': None,
                            'cells_filtered': 0,
                            'status': f'error: {e}',
                        })

        report = pd.DataFrame(report_rows)
        n_exported = len(report[report['status'] == 'exported']) if not report.empty else 0
        logger.info(f"Batch export: {n_exported} rasters exported for {len(plan_numbers)} plans")
        return report

    @staticmethod
    @log_call
    def composite_rasters(
        input_tiffs: List[Union[str, Path]],
        output_path: Union[str, Path],
        method: str = "max",
        extent_mode: str = "intersection",
        ras_object=None
    ) -> Path:
        """
        Composite multiple rasters using max, min, or mean method.

        Parameters
        ----------
        input_tiffs : list of str or Path
            Paths to input GeoTIFF files
        output_path : str or Path
            Path for output composite raster
        method : str, default 'max'
            Compositing method: 'max', 'min', or 'mean'
        extent_mode : str, default 'intersection'
            How to handle differing extents: 'intersection' or 'union'
        ras_object : optional
            Custom RAS object (unused, for API consistency)

        Returns
        -------
        Path
            Path to the composite raster

        Example
        -------
        >>> composite = RasProcess.composite_rasters(
        ...     ['plan01_depth.tif', 'plan02_depth.tif', 'plan03_depth.tif'],
        ...     'composite_max_depth.tif',
        ...     method='max'
        ... )
        """
        if not HAS_RASTERIO:
            raise ImportError(
                "rasterio is required for composite_rasters(). "
                "Install with: pip install rasterio"
            )
        from rasterio.merge import merge

        input_paths = [Path(p) for p in input_tiffs]
        out_path = Path(output_path)

        # Validate inputs exist
        for p in input_paths:
            if not p.exists():
                raise FileNotFoundError(f"Input TIFF not found: {p}")

        if len(input_paths) < 2:
            raise ValueError("At least 2 input rasters are required for compositing")

        # Validate CRS consistency
        datasets = [rasterio.open(p) for p in input_paths]
        try:
            crs_set = {str(ds.crs) for ds in datasets if ds.crs is not None}
            if len(crs_set) > 1:
                logger.warning(
                    f"CRS mismatch across inputs: {crs_set}. "
                    f"Results may be unreliable."
                )

            # Map method name to rasterio merge method
            if method == 'max':
                merge_method = 'max'
            elif method == 'min':
                merge_method = 'min'
            elif method == 'mean':
                # rasterio doesn't have built-in mean, use manual approach
                merge_method = 'max'  # placeholder, we'll handle mean separately
            else:
                raise ValueError(f"Unknown method '{method}'. Use 'max', 'min', or 'mean'.")

            if method == 'mean':
                # Manual mean compositing
                # Read first raster for reference
                ref = datasets[0]
                bounds_list = [ds.bounds for ds in datasets]

                if extent_mode == 'intersection':
                    from rasterio.transform import from_bounds
                    min_left = max(b.left for b in bounds_list)
                    min_bottom = max(b.bottom for b in bounds_list)
                    max_right = min(b.right for b in bounds_list)
                    max_top = min(b.top for b in bounds_list)
                else:
                    min_left = min(b.left for b in bounds_list)
                    min_bottom = min(b.bottom for b in bounds_list)
                    max_right = max(b.right for b in bounds_list)
                    max_top = max(b.top for b in bounds_list)

                # Use first dataset's resolution
                res_x = ref.res[0]
                res_y = ref.res[1]
                width = int((max_right - min_left) / res_x)
                height = int((max_top - min_bottom) / res_y)

                from rasterio.transform import from_bounds as fb
                transform = fb(min_left, min_bottom, max_right, max_top, width, height)

                sum_data = np.zeros((height, width), dtype=np.float64)
                count_data = np.zeros((height, width), dtype=np.int32)

                from rasterio.warp import reproject as rio_reproject
                for ds in datasets:
                    temp = np.full((height, width), np.nan, dtype=np.float64)
                    rio_reproject(
                        source=rasterio.band(ds, 1),
                        destination=temp,
                        dst_transform=transform,
                        dst_crs=ref.crs,
                        dst_nodata=np.nan,
                    )
                    valid = ~np.isnan(temp)
                    if ds.nodata is not None:
                        valid = valid & (temp != ds.nodata)
                    sum_data[valid] += temp[valid]
                    count_data[valid] += 1

                mean_data = np.where(count_data > 0, sum_data / count_data, ref.nodata or -9999.0)

                profile = ref.profile.copy()
                profile.update(
                    transform=transform, width=width, height=height,
                    dtype='float64', count=1
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with rasterio.open(out_path, 'w', **profile) as dst:
                    dst.write(mean_data, 1)
            else:
                # Use rasterio merge for max/min
                bounds_mode = 'intersection' if extent_mode == 'intersection' else 'union'
                merged, transform = merge(datasets, method=merge_method, bounds=None)

                profile = datasets[0].profile.copy()
                profile.update(
                    transform=transform,
                    width=merged.shape[2],
                    height=merged.shape[1],
                    count=1
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with rasterio.open(out_path, 'w', **profile) as dst:
                    dst.write(merged[0], 1)

        finally:
            for ds in datasets:
                ds.close()

        logger.info(f"Composite raster ({method}): {len(input_paths)} inputs → {out_path.name}")
        return out_path

    @staticmethod
    @log_call
    def composite_rasters_from_plans(
        plan_numbers: List[str],
        map_type: str = "depth",
        output_path: Union[str, Path] = None,
        method: str = "max",
        ras_object=None
    ) -> Path:
        """
        Composite stored map TIFs from multiple plans.

        Finds stored map GeoTIFFs for each plan in the project folder,
        then delegates to composite_rasters().

        Parameters
        ----------
        plan_numbers : list of str
            Plan numbers to composite (e.g., ['01', '02', '03'])
        map_type : str, default 'depth'
            Map type to composite (e.g., 'depth', 'wse', 'velocity')
        output_path : str or Path, optional
            Path for output composite. If None, auto-generated in project folder.
        method : str, default 'max'
            Compositing method: 'max', 'min', or 'mean'
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        Path
            Path to the composite raster

        Example
        -------
        >>> composite = RasProcess.composite_rasters_from_plans(
        ...     plan_numbers=['01', '02', '03'],
        ...     map_type='depth',
        ...     method='max'
        ... )
        >>> print(f"Composite saved to: {composite}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Search for TIFs matching map_type for each plan
        input_tiffs = []
        for plan_num in plan_numbers:
            plan_num = RasUtils.normalize_ras_number(plan_num)

            # Search in project folder and subdirectories
            search_patterns = [
                f"*{map_type}*{plan_num}*.tif",
                f"*p{plan_num}*{map_type}*.tif",
                f"*{map_type.capitalize()}*Max*.tif",
            ]

            found = False
            for pattern in search_patterns:
                matches = list(ras_obj.project_folder.rglob(pattern))
                if matches:
                    # Use the most recently modified match
                    best = max(matches, key=lambda p: p.stat().st_mtime)
                    input_tiffs.append(best)
                    logger.debug(f"Plan {plan_num}: found {best.name}")
                    found = True
                    break

            if not found:
                logger.warning(f"No {map_type} TIF found for plan {plan_num}")

        if len(input_tiffs) < 2:
            raise ValueError(
                f"Need at least 2 TIFs for compositing, found {len(input_tiffs)}. "
                f"Run store_maps() for each plan first."
            )

        if output_path is None:
            output_path = ras_obj.project_folder / f"composite_{map_type}_{method}.tif"

        return RasProcess.composite_rasters(
            input_tiffs=input_tiffs,
            output_path=output_path,
            method=method
        )
