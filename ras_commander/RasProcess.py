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

import os
import sys
import subprocess
import tempfile
import xml.etree.ElementTree as ET
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
        terrain_path: Path to terrain TIF file if found, None otherwise
    """
    prj_path: Optional[Path]
    terrain_path: Optional[Path]


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
from .RasUtils import RasUtils
from .LoggingConfig import get_logger
from .Decorators import log_call
from ._native_helper import (
    normalize_store_map_render_mode,
    run_store_all_maps_helper,
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
        'arrival_time': ('arrivaltime', 'Arrival Time', False),
        'duration': ('duration', 'Duration', False),
        'recession': ('recession', 'Recession', False),
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
        logger.info(f"Wine configured: prefix={wine_prefix}, ras_dir={ras_dir}")
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
        logger.info("Wine setup instructions printed. Follow steps to configure environment.")

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
        Extract projection file path and terrain path from .rasmap XML.

        Args:
            rasmap_path: Path to .rasmap file

        Returns:
            ProjectionInfo dataclass with prj_path and terrain_path fields.
            Fields are None if not found.
        """
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Get projection file
            prj_path = None
            proj_elem = root.find(".//RASProjectionFilename")
            if proj_elem is not None:
                filename = proj_elem.get("Filename")
                if filename:
                    prj_path = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if not prj_path.exists():
                        prj_path = None

            # Get terrain TIF
            terrain_path = None
            for layer in root.findall(".//Terrains/Layer"):
                filename = layer.get("Filename")
                if filename:
                    terrain_hdf = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if terrain_hdf.exists():
                        # Look for .tif in same folder
                        terrain_dir = terrain_hdf.parent
                        for tif in terrain_dir.glob("*.tif"):
                            terrain_path = tif
                            break
                    break

            return ProjectionInfo(prj_path=prj_path, terrain_path=terrain_path)

        except Exception as e:
            logger.error(f"Failed to parse rasmap for projection info: {e}")
            return ProjectionInfo(prj_path=None, terrain_path=None)

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
            with rasterio.open(terrain_path) as terrain:
                transform = terrain.transform
                terrain_crs = terrain.crs

            crs = None
            if prj_path is not None and prj_path.exists():
                with open(prj_path, 'r', encoding='utf-8') as f:
                    wkt = f.read()
                crs = CRS.from_wkt(wkt)
            elif terrain_crs is not None:
                crs = terrain_crs
                logger.info(
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
            with rasterio.open(tif_path) as src:
                data = src.read()
                profile = src.profile.copy()
                tags = src.tags()

            profile.update(crs=crs, transform=transform)
            with rasterio.open(tmp_path, "w", **profile) as dst:
                dst.write(data)
                if tags:
                    dst.update_tags(**tags)

            tmp_path.replace(tif_path)

            logger.info(f"Fixed georeferencing: {tif_path}")
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
                try:
                    with rasterio.open(tif_path) as src:
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
                        Path(tif_path).unlink(missing_ok=True)
                    except OSError:
                        logger.debug("Could not delete unreadable TIFF: %s", tif_path)
            generated_files[map_key] = readable_tifs

        return generated_files

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

        Returns:
            True if successful, False otherwise
        """
        try:
            tree = ET.parse(rasmap_path)
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
                logger.info("Created Results element in rasmap")

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
                plan_layer.set("Type", "RASResults")
                plan_layer.set("Filename", f".\\{plan_hdf_filename}")
                logger.info(f"Created plan layer '{output_folder}' in rasmap for {plan_hdf_filename}")

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

            # Write back
            tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
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
            tree = ET.parse(rasmap_path)
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
                tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
                logger.debug(f"Removed {removed_count} stored maps from rasmap")

            return removed_count

        except Exception as e:
            logger.error(f"Failed to remove stored maps from rasmap: {e}")
            return 0

    @staticmethod
    @log_call
    def store_maps(
        plan_number: str,
        output_folder: str = None,
        output_path: Union[str, Path] = None,
        profile: str = "Max",
        render_mode: str = None,
        wse: bool = True,
        depth: bool = True,
        velocity: bool = True,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        inundation_boundary: bool = False,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600
    ) -> Dict[str, List[Path]]:
        """
        Generate stored maps for a plan using RasProcess.exe StoreAllMaps.

        This method:
        1. Configures stored maps in the .rasmap file
        2. Runs RasProcess.exe (StoreAllMaps or individual StoreMap commands)
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
                where RasProcess.exe writes files — see output_path.
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
            wse: Generate Water Surface Elevation map (default: True)
            depth: Generate Depth map (default: True)
            velocity: Generate Velocity map (default: True)
            froude: Generate Froude number map (default: False)
            shear_stress: Generate Shear Stress map (default: False)
            depth_x_velocity: Generate D*V hazard map (default: False)
            depth_x_velocity_sq: Generate D*V² impact map (default: False)
            inundation_boundary: Generate inundation boundary polygon (default: False)
            clear_existing: Clear existing stored maps before adding new ones (default: True)
            fix_georef: Apply georeferencing fix to output TIFs (default: True)
            ras_object: Optional RAS object instance
            ras_version: Optional specific HEC-RAS version for RasProcess.exe
            timeout: Command timeout in seconds (default: 600)

        Returns:
            Dict mapping map type names to lists of generated file paths.
            Paths point to ``output_path`` if specified (files are moved
            there after generation), otherwise to the default Plan ShortID
            folder.

        Raises:
            FileNotFoundError: If RasProcess.exe or required files not found
            RuntimeError: If RasProcess.exe command fails

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
        tree = ET.parse(rasmap_path)
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
        output_dir.mkdir(exist_ok=True)

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
        rasmap_backup = rasmap_path.with_suffix('.rasmap.bak')
        shutil.copy2(rasmap_path, rasmap_backup)

        try:
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
                resolved_output_path.mkdir(parents=True, exist_ok=True)

            # Snapshot pre-existing files in output_dir so we only move files
            # that were created or changed by this StoreAllMaps call when
            # output_path is specified. This preserves unrelated benchmark or
            # manually curated files while still relocating regenerated rasters
            # that overwrite the same filenames on reruns.
            pre_existing_files = {}
            if output_dir.exists():
                for item in output_dir.iterdir():
                    try:
                        stat = item.stat()
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

            logger.info(f"Running StoreAllMaps for plan {plan_num} (mode={helper_mode})...")

            result = run_store_all_maps_helper(
                hecras_dir=hecras_dir,
                render_mode=helper_mode,
                rasmap_path=rasmap_path,
                result_hdf_path=plan_hdf_path,
                timeout=timeout,
                working_dir=ras_obj.project_folder,
            )

            logger.debug(f"StoreAllMaps stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"StoreAllMaps stderr: {result.stderr}")
            if result.returncode != 0:
                logger.error(f"StoreAllMaps failed (exit code {result.returncode})")
                logger.error(f"stderr: {result.stderr}")

            for line in result.stdout.splitlines():
                if "Maps generated" in line:
                    logger.info(line.strip())

            search_dir = output_dir

            # If output_path was requested, move files from default dir to output_path
            if resolved_output_path is not None:
                logger.info(
                    f"Moving generated files from {output_dir} to {resolved_output_path}"
                )
                moved_count = 0
                # Move files that were created or modified by this call.
                for item in output_dir.iterdir():
                    try:
                        stat = item.stat()
                    except FileNotFoundError:
                        continue
                    previous_signature = pre_existing_files.get(item.name)
                    current_signature = (stat.st_mtime_ns, stat.st_size)
                    if previous_signature != current_signature:
                        dest = resolved_output_path / item.name
                        if dest.exists():
                            dest.unlink()
                        shutil.move(str(item), str(dest))
                        moved_count += 1
                logger.info(f"Moved {moved_count} generated file(s) to {resolved_output_path}")

                search_dir = resolved_output_path

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
                tif_files = list(search_dir.glob(pattern))

                if not tif_files:
                    pattern_alt = f"{display_name_used.replace(' ', '_')} ({safe_profile})*.tif"
                    tif_files = list(search_dir.glob(pattern_alt))

                if tif_files:
                    generated_files[map_key] = tif_files
                    logger.info(f"Generated {len(tif_files)} {map_key} TIF(s)")
                else:
                    logger.debug(f"No TIF files found for {map_key} with pattern: {pattern}")

            # Collect inundation boundary shapefile if requested
            if inundation_boundary:
                safe_profile = profile_name.replace(":", " ").replace("/", "_")
                shp_pattern = f"Inundation Boundary ({safe_profile})*.shp"
                shp_files = list(search_dir.glob(shp_pattern))
                if not shp_files:
                    shp_pattern_alt = f"Inundation_Boundary*({safe_profile})*.shp"
                    shp_files = list(search_dir.glob(shp_pattern_alt))
                if shp_files:
                    generated_files['inundation_boundary'] = shp_files
                    logger.info(f"Generated {len(shp_files)} inundation boundary shapefile(s)")
                else:
                    logger.debug(f"No inundation boundary shapefiles found with pattern: {shp_pattern}")

            # Fix georeferencing if requested
            if fix_georef and generated_files:
                proj_info = RasProcess._get_projection_info(rasmap_path)
                if proj_info.terrain_path:
                    if proj_info.prj_path is None:
                        logger.info(
                            "Projection file referenced by %s was not found; "
                            "using terrain CRS for georef fix instead.",
                            rasmap_path.name,
                        )
                    for tif_list in generated_files.values():
                        for tif_path in tif_list:
                            RasProcess._fix_georeferencing(
                                tif_path,
                                proj_info.prj_path,
                                proj_info.terrain_path,
                            )
                else:
                    logger.warning("Could not find terrain for georef fix")
                RasProcess._drop_unreadable_tifs(generated_files)

            return generated_files

        finally:
            # Restore rasmap backup
            if rasmap_backup.exists():
                shutil.copy2(rasmap_backup, rasmap_path)
                rasmap_backup.unlink()

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
                logger.warning(f"Command errors: {result.stderr}")

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
