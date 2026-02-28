"""
VortexCli - HEC-Vortex CLI wrapper for gridded meteorological data conversion.

Converts GRIB2, NetCDF, and other gridded meteorological formats to HEC-DSS
using HEC-Vortex's BatchImporter via Jython scripts.

This module wraps HEC-Vortex's command-line interface, generating temporary
Jython scripts that use Vortex's Java API (mil.army.usace.hec.vortex.io.BatchImporter)
and executing them via `vortex.bat -s script.py`.

HEC-Vortex is a free tool from USACE that handles:
- GRIB2 (HRRR, GFS, MRMS, QPF)
- NetCDF (AORC, ERA5)
- ASC grid files
- SHG (Standard Hydrologic Grid) reprojection
- Spatial clipping to watershed boundaries
- DSS pathname construction with proper time metadata

Typical workflow:
    1. Download forecast GRIB2 files (via PrecipHrrr or manually)
    2. Use VortexCli.import_gridded() to convert GRIB2 → DSS
    3. Reference DSS file in HEC-HMS/RAS met model

Platform:
    Windows only (HEC-Vortex is a Windows application)

Requirements:
    - HEC-Vortex 3.x installed (free from https://www.hec.usace.army.mil/software/hec-vortex/)
    - Windows OS

Example:
    >>> from ras_commander.precip import VortexCli
    >>>
    >>> # Find Vortex installation
    >>> vortex_path = VortexCli.find_vortex()
    >>> print(f"Found Vortex at: {vortex_path}")
    >>>
    >>> # Import HRRR GRIB2 files to DSS
    >>> output_dss = VortexCli.import_gridded(
    ...     input_files=["hrrr.t12z.wrfsubhf01.grib2", "hrrr.t12z.wrfsubhf02.grib2"],
    ...     output_dss="precipitation.dss",
    ...     variables=["Total_precipitation_surface_1_Hour_Accumulation"],
    ...     clip_shp="watershed.shp",
    ...     target_wkt="SHG",
    ...     target_cell_size=2000,
    ...     dss_parts={"A": "SHG", "B": "WATERSHED", "F": "HRRR-FORECAST"}
    ... )

See Also:
    - ras_commander/precip/PrecipHrrr.py for downloading HRRR forecast GRIB2 files
    - ras_commander/terrain/RasTerrain.py for similar CLI wrapper pattern
    - https://www.hec.usace.army.mil/software/hec-vortex/ for HEC-Vortex documentation
"""

import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Union
from datetime import datetime

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


# Standard HEC-Vortex installation paths
_VORTEX_BASE_PATHS = [
    Path("C:/Program Files/HEC/HEC-Vortex"),
    Path("C:/Program Files (x86)/HEC/HEC-Vortex"),
    Path("C:/HEC/HEC-Vortex"),
]

# Common GRIB2 variable names for meteorological data
HRRR_PRECIP_VARIABLES = [
    "Total_precipitation_surface_1_Hour_Accumulation",
]

MRMS_PRECIP_VARIABLES = [
    "GaugeCorrQPE01H_altitude_above_msl",
]

GFS_PRECIP_VARIABLES = [
    "Total_precipitation_surface_Mixed_intervals_Accumulation",
]


class VortexCli:
    """
    Static class for converting gridded meteorological data to HEC-DSS via HEC-Vortex CLI.

    Generates temporary Jython scripts using Vortex's BatchImporter Java API
    and executes them via ``vortex.bat -s script.py``. All methods are static
    and follow the ras-commander coding pattern (no instantiation).

    Primary Methods:
        find_vortex(): Discover HEC-Vortex installation on the system
        import_gridded(): Convert gridded files (GRIB2/NetCDF) to DSS
        clip_and_import(): Clip to watershed boundary and import to DSS
        batch_import(): Convert multiple file sets in batch

    Usage:
        from ras_commander.precip import VortexCli

        # Convert HRRR GRIB2 files to DSS
        VortexCli.import_gridded(
            input_files=["hrrr_f01.grib2", "hrrr_f02.grib2"],
            output_dss="precip.dss",
            variables=["Total_precipitation_surface_1_Hour_Accumulation"]
        )
    """

    # Class-level aliases for module-level constants (accessible as VortexCli.HRRR_PRECIP_VARIABLES)
    HRRR_PRECIP_VARIABLES = HRRR_PRECIP_VARIABLES
    MRMS_PRECIP_VARIABLES = MRMS_PRECIP_VARIABLES
    GFS_PRECIP_VARIABLES = GFS_PRECIP_VARIABLES

    @staticmethod
    @log_call
    def find_vortex(vortex_path: Optional[Union[str, Path]] = None) -> Path:
        """
        Discover HEC-Vortex installation on the system.

        Searches standard installation locations for HEC-Vortex and verifies
        that vortex.bat exists. If vortex_path is provided, validates that
        path instead.

        Args:
            vortex_path: Optional explicit path to HEC-Vortex installation
                directory. If None, searches standard locations.

        Returns:
            Path: Path to HEC-Vortex installation directory containing
                vortex.bat.

        Raises:
            FileNotFoundError: If HEC-Vortex installation cannot be found.
        """
        # If explicit path provided, validate it
        if vortex_path is not None:
            vortex_path = Path(vortex_path)
            vortex_bat = vortex_path / "bin" / "vortex.bat"
            if vortex_bat.exists():
                logger.info(f"Found HEC-Vortex at: {vortex_path}")
                return vortex_path
            # Also check if vortex.bat is directly in the path
            vortex_bat = vortex_path / "vortex.bat"
            if vortex_bat.exists():
                logger.info(f"Found HEC-Vortex at: {vortex_path}")
                return vortex_path
            raise FileNotFoundError(
                f"HEC-Vortex not found at specified path: {vortex_path}. "
                f"Expected vortex.bat at {vortex_path / 'bin' / 'vortex.bat'}"
            )

        # Search standard installation paths
        for base_path in _VORTEX_BASE_PATHS:
            if not base_path.exists():
                continue
            # Check for versioned subdirectories (e.g., HEC-Vortex/3.0)
            try:
                subdirs = sorted(
                    [d for d in base_path.iterdir() if d.is_dir()],
                    reverse=True  # Latest version first
                )
                for subdir in subdirs:
                    vortex_bat = subdir / "bin" / "vortex.bat"
                    if vortex_bat.exists():
                        logger.info(f"Found HEC-Vortex {subdir.name} at: {subdir}")
                        return subdir
            except PermissionError:
                continue

            # Check if vortex.bat is directly in base path
            vortex_bat = base_path / "bin" / "vortex.bat"
            if vortex_bat.exists():
                logger.info(f"Found HEC-Vortex at: {base_path}")
                return base_path

        # Check PATH environment variable
        import shutil
        vortex_on_path = shutil.which("vortex")
        if vortex_on_path:
            vortex_dir = Path(vortex_on_path).parent.parent
            logger.info(f"Found HEC-Vortex on PATH at: {vortex_dir}")
            return vortex_dir

        raise FileNotFoundError(
            "HEC-Vortex installation not found. Searched:\n"
            + "\n".join(f"  - {p}" for p in _VORTEX_BASE_PATHS)
            + "\nInstall from: https://www.hec.usace.army.mil/software/hec-vortex/\n"
            + "Or pass vortex_path= explicitly."
        )

    @staticmethod
    def _get_vortex_bat(vortex_path: Path) -> Path:
        """Get path to vortex.bat executable."""
        vortex_bat = vortex_path / "bin" / "vortex.bat"
        if vortex_bat.exists():
            return vortex_bat
        vortex_bat = vortex_path / "vortex.bat"
        if vortex_bat.exists():
            return vortex_bat
        raise FileNotFoundError(f"vortex.bat not found in {vortex_path}")

    @staticmethod
    def _generate_import_script(
        input_files: List[Path],
        output_dss: Path,
        variables: List[str],
        clip_shp: Optional[Path] = None,
        target_wkt: str = "SHG",
        target_cell_size: int = 2000,
        resampling_method: str = "Bilinear",
        dss_parts: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Generate a Jython script for HEC-Vortex BatchImporter.

        Args:
            input_files: List of input file paths (GRIB2, NetCDF, etc.)
            output_dss: Output DSS file path.
            variables: List of variable names to extract.
            clip_shp: Optional shapefile for spatial clipping.
            target_wkt: Target projection WKT. "SHG" for Standard Hydrologic Grid.
            target_cell_size: Target grid cell size in meters.
            resampling_method: Resampling method (Bilinear, NearestNeighbor, etc.)
            dss_parts: Optional DSS pathname parts {A, B, C, D, E, F}.

        Returns:
            str: Jython script content.
        """
        # Escape backslashes for Java string literals
        input_paths_java = ", ".join(
            f'r"{str(f)}"' for f in input_files
        )
        output_dss_java = str(output_dss).replace("\\", "/")

        # Build variables list
        variables_block = "\n".join(
            f'variables.add("{v}")' for v in variables
        )

        # Build geo options
        geo_options_lines = []
        if clip_shp:
            clip_path = str(clip_shp).replace("\\", "/")
            geo_options_lines.append(f'    "pathToShp": r"{clip_path}",')
        geo_options_lines.append(f'    "targetCellSize": "{target_cell_size}",')
        if target_wkt.upper() == "SHG":
            geo_options_lines.append('    "targetWkt": WktFactory.shg(),')
        else:
            geo_options_lines.append(f'    "targetWkt": r"{target_wkt}",')
        geo_options_lines.append(f'    "resamplingMethod": "{resampling_method}",')
        geo_options_block = "\n".join(geo_options_lines)

        # Build write options (DSS pathname parts)
        write_options_lines = []
        if dss_parts:
            for part, value in dss_parts.items():
                part_key = part.upper() if len(part) == 1 else part
                if part_key in ("A", "B", "C", "D", "E", "F"):
                    write_options_lines.append(
                        f'    "part{part_key}": "{value}",'
                    )
        write_options_block = "\n".join(write_options_lines)

        script = textwrap.dedent(f"""\
            # Auto-generated HEC-Vortex import script
            # Generated by ras-commander VortexCli at {datetime.now().isoformat()}

            from mil.army.usace.hec.vortex.io import BatchImporter
            from mil.army.usace.hec.vortex.geo import WktFactory
            import java.util.ArrayList as ArrayList
            import java.util.HashMap as HashMap

            # Input files
            inFiles = [{input_paths_java}]

            # Variables to extract
            variables = ArrayList()
            {variables_block}

            # Geo-processing options
            geoOptions = HashMap()
            geoOptionsDict = {{
            {geo_options_block}
            }}
            for key, val in geoOptionsDict.items():
                geoOptions.put(key, str(val) if not isinstance(val, str) else val)

            # Write options (DSS pathname parts)
            writeOptions = HashMap()
            writeOptionsDict = {{
            {write_options_block}
            }}
            for key, val in writeOptionsDict.items():
                writeOptions.put(key, val)

            # Destination
            destination = r"{output_dss_java}"

            # Build and execute importer
            importer = BatchImporter.builder() \\
                .inFiles(inFiles) \\
                .variables(variables) \\
                .geoOptions(geoOptions) \\
                .writeOptions(writeOptions) \\
                .destination(destination) \\
                .build()

            importer.process()

            print("VORTEX_IMPORT_COMPLETE")
        """)
        return script

    @staticmethod
    @log_call
    def import_gridded(
        input_files: Union[str, Path, List[Union[str, Path]]],
        output_dss: Union[str, Path],
        variables: List[str],
        clip_shp: Optional[Union[str, Path]] = None,
        target_wkt: str = "SHG",
        target_cell_size: int = 2000,
        resampling_method: str = "Bilinear",
        dss_parts: Optional[Dict[str, str]] = None,
        vortex_path: Optional[Union[str, Path]] = None,
        timeout: int = 600,
    ) -> Path:
        """
        Convert gridded meteorological files to HEC-DSS using HEC-Vortex.

        Generates a temporary Jython script using Vortex's BatchImporter API,
        executes it via ``vortex.bat -s script.py``, validates the output,
        and cleans up the temporary script.

        Args:
            input_files: Input file path(s) - GRIB2, NetCDF, ASC, etc.
                Can be a single path or list of paths.
            output_dss: Path for the output HEC-DSS file.
            variables: List of variable names to extract from the input files.
                Common variables:
                - HRRR: ["Total_precipitation_surface_1_Hour_Accumulation"]
                - MRMS: ["GaugeCorrQPE01H_altitude_above_msl"]
                - GFS: ["Total_precipitation_surface_Mixed_intervals_Accumulation"]
            clip_shp: Optional path to shapefile for spatial clipping.
                Restricts output to the shapefile extent (typically watershed boundary).
            target_wkt: Target projection. Use "SHG" for Standard Hydrologic Grid
                (required by HEC-HMS/RAS). Default: "SHG".
            target_cell_size: Target grid cell size in meters. Default: 2000.
            resampling_method: Spatial resampling method. Options:
                "Bilinear" (default), "NearestNeighbor", "Average".
            dss_parts: Optional DSS pathname parts as dict. Keys are
                single letters A-F. Example: {"A": "SHG", "B": "BASIN", "F": "HRRR"}.
            vortex_path: Optional explicit path to HEC-Vortex installation.
                If None, searches standard locations.
            timeout: Maximum execution time in seconds. Default: 600 (10 min).

        Returns:
            Path: Path to the created DSS file.

        Raises:
            FileNotFoundError: If input files or Vortex installation not found.
            RuntimeError: If Vortex execution fails.
            TimeoutError: If execution exceeds timeout.

        Example:
            >>> from ras_commander.precip import VortexCli
            >>>
            >>> VortexCli.import_gridded(
            ...     input_files=["hrrr_f01.grib2", "hrrr_f02.grib2"],
            ...     output_dss="precip.dss",
            ...     variables=["Total_precipitation_surface_1_Hour_Accumulation"],
            ...     clip_shp="watershed.shp",
            ...     dss_parts={"A": "SHG", "B": "WATERSHED", "F": "HRRR"}
            ... )
        """
        # Normalize input_files to list of Paths
        if isinstance(input_files, (str, Path)):
            input_files = [input_files]
        input_files = [Path(f) for f in input_files]

        # Validate input files exist
        for f in input_files:
            if not f.exists():
                raise FileNotFoundError(f"Input file not found: {f}")

        output_dss = Path(output_dss)

        # Validate clip shapefile if provided
        if clip_shp is not None:
            clip_shp = Path(clip_shp)
            if not clip_shp.exists():
                raise FileNotFoundError(f"Clip shapefile not found: {clip_shp}")

        # Find Vortex installation
        vortex_dir = VortexCli.find_vortex(vortex_path)
        vortex_bat = VortexCli._get_vortex_bat(vortex_dir)

        # Create output directory if needed
        output_dss.parent.mkdir(parents=True, exist_ok=True)

        # Generate Jython import script
        script_content = VortexCli._generate_import_script(
            input_files=input_files,
            output_dss=output_dss,
            variables=variables,
            clip_shp=clip_shp,
            target_wkt=target_wkt,
            target_cell_size=target_cell_size,
            resampling_method=resampling_method,
            dss_parts=dss_parts,
        )

        # Write temporary script file
        script_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                prefix="vortex_import_",
                delete=False,
                dir=str(output_dss.parent),
            ) as f:
                f.write(script_content)
                script_file = Path(f.name)

            logger.info(
                f"Importing {len(input_files)} file(s) to DSS via HEC-Vortex: "
                f"{output_dss.name}"
            )
            logger.debug(f"Vortex script: {script_file}")
            logger.debug(f"Variables: {variables}")

            # Execute: vortex.bat -s script.py
            cmd_str = f'"{vortex_bat}" -s "{script_file}"'
            logger.debug(f"Executing: {cmd_str}")

            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(output_dss.parent),
            )

            # Check execution result
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "No error output"
                logger.error(f"Vortex execution failed (exit code {result.returncode})")
                logger.error(f"stderr: {error_msg}")
                if result.stdout:
                    logger.debug(f"stdout: {result.stdout[:2000]}")
                raise RuntimeError(
                    f"HEC-Vortex import failed (exit code {result.returncode}):\n"
                    f"{error_msg}"
                )

            # Verify completion marker in output
            if "VORTEX_IMPORT_COMPLETE" not in (result.stdout or ""):
                logger.warning(
                    "Vortex did not emit completion marker. "
                    "Import may have partially completed."
                )
                if result.stdout:
                    logger.debug(f"Vortex stdout: {result.stdout[:2000]}")

            # Validate output DSS file exists
            if not output_dss.exists():
                raise RuntimeError(
                    f"Vortex execution completed but DSS file not created: {output_dss}"
                )

            file_size = output_dss.stat().st_size
            logger.info(
                f"DSS file created: {output_dss.name} "
                f"({file_size / 1024:.1f} KB)"
            )
            return output_dss

        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"HEC-Vortex import timed out after {timeout} seconds. "
                f"Try increasing timeout= parameter or reducing input data."
            )
        finally:
            # Clean up temporary script
            if script_file and script_file.exists():
                try:
                    script_file.unlink()
                    logger.debug(f"Cleaned up temporary script: {script_file}")
                except OSError:
                    logger.warning(f"Could not delete temp script: {script_file}")

    @staticmethod
    @log_call
    def clip_and_import(
        input_files: Union[str, Path, List[Union[str, Path]]],
        output_dss: Union[str, Path],
        clip_shp: Union[str, Path],
        variables: Optional[List[str]] = None,
        target_cell_size: int = 2000,
        dss_parts: Optional[Dict[str, str]] = None,
        vortex_path: Optional[Union[str, Path]] = None,
        timeout: int = 600,
    ) -> Path:
        """
        Clip gridded data to watershed boundary and import to DSS.

        Convenience wrapper around import_gridded() that requires a clip
        shapefile and uses sensible defaults for HEC-HMS/RAS workflows.

        Args:
            input_files: Input file path(s) - GRIB2, NetCDF, etc.
            output_dss: Path for the output HEC-DSS file.
            clip_shp: Path to watershed boundary shapefile for clipping.
            variables: Variable names. If None, uses HRRR precipitation defaults.
            target_cell_size: Target cell size in meters. Default: 2000.
            dss_parts: Optional DSS pathname parts.
            vortex_path: Optional HEC-Vortex installation path.
            timeout: Maximum execution time in seconds.

        Returns:
            Path: Path to the created DSS file.

        Example:
            >>> VortexCli.clip_and_import(
            ...     input_files=list(Path("hrrr_data").glob("*.grib2")),
            ...     output_dss="clipped_precip.dss",
            ...     clip_shp="watershed.shp",
            ...     dss_parts={"A": "SHG", "B": "BASIN", "F": "HRRR"}
            ... )
        """
        if variables is None:
            variables = HRRR_PRECIP_VARIABLES
            logger.info("No variables specified, using HRRR precipitation defaults")

        return VortexCli.import_gridded(
            input_files=input_files,
            output_dss=output_dss,
            variables=variables,
            clip_shp=clip_shp,
            target_wkt="SHG",
            target_cell_size=target_cell_size,
            resampling_method="Bilinear",
            dss_parts=dss_parts,
            vortex_path=vortex_path,
            timeout=timeout,
        )

    @staticmethod
    @log_call
    def batch_import(
        file_groups: Dict[str, List[Union[str, Path]]],
        output_dir: Union[str, Path],
        variables: List[str],
        clip_shp: Optional[Union[str, Path]] = None,
        target_cell_size: int = 2000,
        dss_parts: Optional[Dict[str, str]] = None,
        vortex_path: Optional[Union[str, Path]] = None,
        timeout_per_group: int = 600,
    ) -> Dict[str, Path]:
        """
        Batch convert multiple file groups to separate DSS files.

        Each group is imported to a separate DSS file, useful for
        processing multiple forecast cycles or data sources.

        Args:
            file_groups: Dictionary mapping group names to lists of input files.
                Example: {"cycle_00z": [f1, f2], "cycle_12z": [f3, f4]}
            output_dir: Directory for output DSS files. Files are named
                ``{group_name}.dss``.
            variables: Variable names to extract.
            clip_shp: Optional watershed boundary shapefile.
            target_cell_size: Target cell size in meters.
            dss_parts: Optional DSS pathname parts.
            vortex_path: Optional HEC-Vortex installation path.
            timeout_per_group: Timeout per group in seconds.

        Returns:
            Dict[str, Path]: Mapping of group names to created DSS file paths.

        Example:
            >>> results = VortexCli.batch_import(
            ...     file_groups={
            ...         "hrrr_00z": list(Path("data/00z").glob("*.grib2")),
            ...         "hrrr_12z": list(Path("data/12z").glob("*.grib2")),
            ...     },
            ...     output_dir="dss_output",
            ...     variables=["Total_precipitation_surface_1_Hour_Accumulation"],
            ...     clip_shp="watershed.shp"
            ... )
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = {}
        total = len(file_groups)

        for i, (group_name, files) in enumerate(file_groups.items(), 1):
            output_dss = output_dir / f"{group_name}.dss"
            logger.info(f"Processing group {i}/{total}: {group_name} ({len(files)} files)")

            try:
                result_path = VortexCli.import_gridded(
                    input_files=files,
                    output_dss=output_dss,
                    variables=variables,
                    clip_shp=clip_shp,
                    target_cell_size=target_cell_size,
                    dss_parts=dss_parts,
                    vortex_path=vortex_path,
                    timeout=timeout_per_group,
                )
                results[group_name] = result_path
                logger.info(f"Group {group_name}: complete ({result_path.name})")
            except Exception as e:
                logger.error(f"Group {group_name}: failed - {e}")
                results[group_name] = None

        successful = sum(1 for v in results.values() if v is not None)
        logger.info(f"Batch import complete: {successful}/{total} groups succeeded")
        return results

    @staticmethod
    @log_call
    def get_grib2_variables(
        grib_file: Union[str, Path],
        vortex_path: Optional[Union[str, Path]] = None,
        timeout: int = 120,
    ) -> List[str]:
        """
        List available variables in a GRIB2 file using HEC-Vortex.

        Generates a Jython script that reads the GRIB2 file and lists all
        available variable names, useful for discovering the correct variable
        name for import.

        Args:
            grib_file: Path to GRIB2 file to inspect.
            vortex_path: Optional HEC-Vortex installation path.
            timeout: Maximum execution time in seconds.

        Returns:
            List[str]: Available variable names in the GRIB2 file.

        Raises:
            FileNotFoundError: If GRIB2 file or Vortex not found.
            RuntimeError: If Vortex execution fails.
        """
        grib_file = Path(grib_file)
        if not grib_file.exists():
            raise FileNotFoundError(f"GRIB2 file not found: {grib_file}")

        vortex_dir = VortexCli.find_vortex(vortex_path)
        vortex_bat = VortexCli._get_vortex_bat(vortex_dir)

        grib_path_java = str(grib_file).replace("\\", "/")

        script_content = textwrap.dedent(f"""\
            # Auto-generated HEC-Vortex variable listing script
            from mil.army.usace.hec.vortex.io import DataReader

            source = r"{grib_path_java}"
            variables = DataReader.getVariables(source)

            print("VORTEX_VARIABLES_START")
            for v in variables:
                print(v)
            print("VORTEX_VARIABLES_END")
        """)

        script_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                prefix="vortex_vars_",
                delete=False,
            ) as f:
                f.write(script_content)
                script_file = Path(f.name)

            cmd_str = f'"{vortex_bat}" -s "{script_file}"'
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Vortex variable listing failed: {result.stderr or 'Unknown error'}"
                )

            # Parse variables from output
            stdout = result.stdout or ""
            variables = []
            in_vars = False
            for line in stdout.splitlines():
                line = line.strip()
                if line == "VORTEX_VARIABLES_START":
                    in_vars = True
                    continue
                elif line == "VORTEX_VARIABLES_END":
                    in_vars = False
                    continue
                elif in_vars and line:
                    variables.append(line)

            logger.info(f"Found {len(variables)} variables in {grib_file.name}")
            return variables

        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Variable listing timed out after {timeout} seconds"
            )
        finally:
            if script_file and script_file.exists():
                try:
                    script_file.unlink()
                except OSError:
                    pass
