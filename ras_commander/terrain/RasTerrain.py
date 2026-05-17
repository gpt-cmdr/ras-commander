"""
RasTerrain - HEC-RAS Terrain Creation and Manipulation

This module provides static methods for creating HEC-RAS terrain files from
input rasters using the RasProcess.exe CreateTerrain command and GDAL tools
bundled with HEC-RAS.

Summary:
    Provides terrain creation capabilities without requiring external GDAL
    installations - uses the GDAL tools bundled with HEC-RAS for maximum
    compatibility with HEC-RAS terrain formats.

Key Functions:
    create_terrain_hdf():
        Creates HEC-RAS terrain HDF from input rasters using RasProcess.exe.
        This is the primary terrain creation method, verified working with
        HEC-RAS 6.6.

    vrt_to_tiff():
        Converts VRT (Virtual Raster) mosaics to single optimized TIFF files
        using HEC-RAS bundled GDAL tools.

    _get_hecras_path():
        Locates HEC-RAS installation directory for a given version.

    _get_hecras_gdal_path():
        Locates GDAL tools within HEC-RAS installation.

    _generate_prj_from_raster():
        Generates ESRI PRJ file from raster's coordinate reference system.

Platform:
    Windows only (HEC-RAS is a Windows application)

Requirements:
    - HEC-RAS 6.3+ installed
    - Windows OS

Example:
    from ras_commander.terrain import RasTerrain
    from pathlib import Path

    # Create terrain HDF
    terrain = RasTerrain.create_terrain_hdf(
        input_rasters=[Path("terrain.tif")],
        output_hdf=Path("Terrain/MyTerrain.hdf"),
        projection_prj=Path("Terrain/Projection.prj"),
        units="Feet",
        hecras_version="7.0"
    )

See Also:
    - feature_dev_notes/HEC-RAS_Terrain_CLI/CLAUDE.md for design documentation
    - feature_dev_notes/HEC-RAS_Terrain_CLI/test_rasprocess_createterrain.py
"""

import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Union

# Import decorator from parent package
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class RasTerrain:
    """
    Static class for HEC-RAS terrain creation and manipulation.

    All methods are static and designed to be called directly without
    instantiation, following the ras-commander coding pattern.

    Primary Methods:
        compute_bank_lines(): Generate bank lines from XS bank stations
        create_terrain_hdf(): Create HEC-RAS terrain HDF from input rasters
        vrt_to_tiff(): Convert VRT mosaic to single optimized TIFF

    Helper Methods:
        _get_hecras_path(): Find HEC-RAS installation directory
        _get_hecras_gdal_path(): Find GDAL tools in HEC-RAS installation
        _generate_prj_from_raster(): Create ESRI PRJ file from raster CRS

    Usage:
        from ras_commander.terrain import RasTerrain
        from pathlib import Path

        # Create terrain from TIFF
        RasTerrain.create_terrain_hdf(
            input_rasters=[Path("dem.tif")],
            output_hdf=Path("Terrain/Terrain.hdf"),
            projection_prj=Path("Terrain/Projection.prj")
        )
    """

    # Standard HEC-RAS installation paths
    _HECRAS_BASE_PATHS = [
        Path("C:/Program Files (x86)/HEC/HEC-RAS"),
        Path("C:/Program Files/HEC/HEC-RAS"),
    ]

    @staticmethod
    def _empty_bank_lines_gdf(crs=None):
        """Return an empty bank-lines GeoDataFrame with the public schema."""
        try:
            import geopandas as gpd
        except ImportError:
            raise ImportError(
                "geopandas is required for compute_bank_lines(). "
                "Install with: pip install geopandas"
            )

        columns = [
            "river",
            "reach",
            "bank_side",
            "xs_count",
            "rs_values",
            "geometry",
            "length",
        ]
        gdf = gpd.GeoDataFrame(columns=columns, geometry="geometry")
        if crs is not None:
            gdf = gdf.set_crs(crs, allow_override=True)
        return gdf

    @staticmethod
    def _bank_point_from_stationed_xy(xs_coords, bank_station):
        """
        Interpolate a bank point from GeomCrossSection.get_xs_coords() output.
        """
        try:
            import pandas as pd
            from shapely.geometry import Point
        except ImportError:
            raise ImportError(
                "pandas and shapely are required for compute_bank_lines(). "
                "Install with: pip install pandas shapely"
            )

        if bank_station is None or pd.isna(bank_station):
            return None

        group = xs_coords.sort_values("station")
        if group.empty:
            return None

        station = float(bank_station)
        stations = group["station"].astype(float)
        min_station = float(stations.min())
        max_station = float(stations.max())
        tolerance = 1e-8

        if station < min_station - tolerance or station > max_station + tolerance:
            logger.warning(
                "Bank station %.3f is outside station range %.3f-%.3f; skipping",
                station,
                min_station,
                max_station,
            )
            return None

        exact = group[(stations - station).abs() <= tolerance]
        if not exact.empty:
            row = exact.iloc[0]
            return Point(float(row["x"]), float(row["y"]))

        before = group[stations < station]
        after = group[stations > station]
        if before.empty or after.empty:
            return None

        left = before.iloc[-1]
        right = after.iloc[0]
        left_station = float(left["station"])
        right_station = float(right["station"])
        if right_station == left_station:
            return Point(float(left["x"]), float(left["y"]))

        fraction = (station - left_station) / (right_station - left_station)
        x = float(left["x"]) + fraction * (float(right["x"]) - float(left["x"]))
        y = float(left["y"]) + fraction * (float(right["y"]) - float(left["y"]))
        return Point(x, y)

    @staticmethod
    def _bank_point_from_xs_geometry(xs_geometry, station_elevation, bank_station):
        """
        Interpolate a bank point along an HDF cross-section LineString.
        """
        try:
            import numpy as np
            import pandas as pd
        except ImportError:
            raise ImportError(
                "numpy and pandas are required for compute_bank_lines(). "
                "Install with: pip install numpy pandas"
            )

        if bank_station is None or pd.isna(bank_station):
            return None
        if xs_geometry is None or xs_geometry.is_empty:
            return None

        stations = np.asarray(station_elevation, dtype=float)
        if stations.ndim != 2 or stations.shape[1] < 1 or stations.shape[0] == 0:
            return None

        station_values = stations[:, 0]
        min_station = float(np.nanmin(station_values))
        max_station = float(np.nanmax(station_values))
        station = float(bank_station)
        tolerance = 1e-8

        if station < min_station - tolerance or station > max_station + tolerance:
            logger.warning(
                "Bank station %.3f is outside station range %.3f-%.3f; skipping",
                station,
                min_station,
                max_station,
            )
            return None

        if max_station == min_station:
            return xs_geometry.interpolate(0.5, normalized=True)

        fraction = (station - min_station) / (max_station - min_station)
        fraction = min(1.0, max(0.0, fraction))
        return xs_geometry.interpolate(fraction, normalized=True)

    @staticmethod
    def _build_bank_lines_gdf(bank_points, crs=None):
        """Build the public bank-line GeoDataFrame from ordered bank points."""
        try:
            import geopandas as gpd
            from shapely.geometry import LineString
        except ImportError:
            raise ImportError(
                "geopandas and shapely are required for compute_bank_lines(). "
                "Install with: pip install geopandas shapely"
            )

        records = []
        groups = {}
        for point_record in bank_points:
            key = (
                point_record["river"],
                point_record["reach"],
                point_record["bank_side"],
            )
            groups.setdefault(key, []).append(point_record)

        for (river, reach, bank_side), points in groups.items():
            if len(points) < 2:
                logger.warning(
                    "Skipping %s/%s %s bank line with fewer than two points",
                    river,
                    reach,
                    bank_side,
                )
                continue

            line = LineString([
                point_record["geometry"].coords[0]
                for point_record in points
            ])
            records.append({
                "river": river,
                "reach": reach,
                "bank_side": bank_side,
                "xs_count": len(points),
                "rs_values": [point_record["rs"] for point_record in points],
                "geometry": line,
                "length": line.length,
            })

        if not records:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

    @staticmethod
    def _compute_bank_lines_from_text(geom_path: Path, crs=None, ras_object=None):
        """Compute bank lines from a plain-text HEC-RAS geometry file."""
        from ..geom.GeomCrossSection import GeomCrossSection

        xs_df = GeomCrossSection.get_cross_sections(geom_path)
        if xs_df.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        if "Type" in xs_df.columns:
            xs_df = xs_df[xs_df["Type"] == 1].reset_index(drop=True)
        if xs_df.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        try:
            xs_coords = GeomCrossSection.get_xs_coords(
                geom_path,
                ras_object=ras_object,
            )
        except ValueError:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        if xs_coords.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        coord_groups = {
            (river, reach, rs): group
            for (river, reach, rs), group in xs_coords.groupby(["river", "reach", "RS"])
        }

        bank_points = []
        for _, row in xs_df.iterrows():
            river = row["River"]
            reach = row["Reach"]
            rs = str(row["RS"])
            coords = coord_groups.get((river, reach, rs))
            if coords is None or coords.empty:
                logger.warning(
                    "No XS coordinates found for %s/%s/RS %s",
                    river,
                    reach,
                    rs,
                )
                continue

            banks = GeomCrossSection.get_bank_stations(geom_path, river, reach, rs)
            if banks is None:
                logger.warning(
                    "No bank stations found for %s/%s/RS %s",
                    river,
                    reach,
                    rs,
                )
                continue

            left_bank, right_bank = banks
            for bank_side, bank_station in (
                ("Left", left_bank),
                ("Right", right_bank),
            ):
                point = RasTerrain._bank_point_from_stationed_xy(coords, bank_station)
                if point is None:
                    continue
                bank_points.append({
                    "river": river,
                    "reach": reach,
                    "bank_side": bank_side,
                    "rs": rs,
                    "geometry": point,
                })

        return RasTerrain._build_bank_lines_gdf(bank_points, crs=crs)

    @staticmethod
    def _compute_bank_lines_from_hdf(geom_path: Path, crs=None, ras_object=None):
        """Compute bank lines from a compiled HEC-RAS geometry HDF file."""
        from ..hdf.HdfXsec import HdfXsec

        xs_gdf = HdfXsec.get_cross_sections(
            str(geom_path),
            ras_object=ras_object,
        )
        result_crs = crs if crs is not None else getattr(xs_gdf, "crs", None)
        if xs_gdf.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=result_crs)

        bank_points = []
        for _, row in xs_gdf.iterrows():
            river = row.get("River", "")
            reach = row.get("Reach", "")
            rs = str(row.get("RS", ""))
            station_elevation = row.get("station_elevation")

            for bank_side, column in (
                ("Left", "Left Bank"),
                ("Right", "Right Bank"),
            ):
                point = RasTerrain._bank_point_from_xs_geometry(
                    row.geometry,
                    station_elevation,
                    row.get(column),
                )
                if point is None:
                    continue
                bank_points.append({
                    "river": river,
                    "reach": reach,
                    "bank_side": bank_side,
                    "rs": rs,
                    "geometry": point,
                })

        return RasTerrain._build_bank_lines_gdf(bank_points, crs=result_crs)

    @staticmethod
    @log_call
    def compute_bank_lines(
        geom_path: Union[str, Path],
        *,
        crs=None,
        ras_object=None,
    ):
        """
        Generate bank-line geometry from cross-section bank stations.

        This is a non-mutating API equivalent to RASMapper's
        Bank Lines layer -> Compute Bank Lines from XS Bank Stations workflow.
        It reads existing cross-section bank station metadata and returns
        reviewable line geometry without modifying `.rasmap`, text geometry,
        or compiled geometry HDF bank-line layers.

        Parameters:
            geom_path (Union[str, Path]): Path to a plain-text `.g##` geometry
                file or compiled `.g##.hdf` geometry HDF file.
            crs: Optional CRS to assign to the returned GeoDataFrame. If omitted
                and an HDF input exposes a CRS, that CRS is preserved.
            ras_object: Optional RasPrj instance for multi-project workflows.

        Returns:
            geopandas.GeoDataFrame: Bank lines with columns:
                - river (str): River name
                - reach (str): Reach name
                - bank_side (str): "Left" or "Right"
                - xs_count (int): Number of cross sections used
                - rs_values (list[str]): River stations used in line order
                - geometry (LineString): Generated bank line
                - length (float): Line length in project coordinate units

        Raises:
            FileNotFoundError: If geom_path does not exist.
            ImportError: If geopandas, shapely, pandas, or numpy are unavailable.
        """
        geom_path = Path(geom_path)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        if geom_path.suffix.lower() == ".hdf":
            return RasTerrain._compute_bank_lines_from_hdf(
                geom_path,
                crs=crs,
                ras_object=ras_object,
            )

        return RasTerrain._compute_bank_lines_from_text(
            geom_path,
            crs=crs,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def _get_hecras_path(version: str = "7.0") -> Path:
        """
        Get path to HEC-RAS installation directory.

        Searches standard installation locations for the specified HEC-RAS
        version and verifies that RasProcess.exe exists.

        Args:
            version: HEC-RAS version string (e.g., "7.0", "6.5", "6.3").
                     Defaults to "7.0".

        Returns:
            Path: Path to HEC-RAS installation directory containing
                  RasProcess.exe.

        Raises:
            FileNotFoundError: If HEC-RAS installation not found for the
                               specified version.

        Example:
            >>> hecras_path = RasTerrain._get_hecras_path("7.0")
            >>> print(hecras_path)
            C:\\Program Files (x86)\\HEC\\HEC-RAS\\7.0
        """
        for base_path in RasTerrain._HECRAS_BASE_PATHS:
            hecras_path = base_path / version
            rasprocess = hecras_path / "RasProcess.exe"

            if rasprocess.exists():
                logger.debug(f"Found HEC-RAS {version} at {hecras_path}")
                return hecras_path

        # Try with minor version variations
        version_parts = version.split(".")
        if len(version_parts) == 2:
            major, minor = version_parts
            # Try checking for point releases (e.g., 6.6.1)
            for base_path in RasTerrain._HECRAS_BASE_PATHS:
                parent = base_path
                if parent.exists():
                    for subdir in parent.iterdir():
                        if subdir.is_dir() and subdir.name.startswith(f"{major}.{minor}"):
                            rasprocess = subdir / "RasProcess.exe"
                            if rasprocess.exists():
                                logger.debug(f"Found HEC-RAS at {subdir}")
                                return subdir

        raise FileNotFoundError(
            f"HEC-RAS {version} installation not found. "
            f"Searched in: {[str(p) for p in RasTerrain._HECRAS_BASE_PATHS]}. "
            f"Ensure HEC-RAS {version} is installed and RasProcess.exe exists."
        )

    @staticmethod
    @log_call
    def _get_hecras_gdal_path(version: str = "7.0") -> Path:
        """
        Get path to GDAL tools in HEC-RAS installation.

        HEC-RAS bundles GDAL tools that are optimized for HEC-RAS terrain
        formats. This method locates the GDAL bin64 directory.

        Args:
            version: HEC-RAS version string (e.g., "7.0"). Defaults to "7.0".

        Returns:
            Path: Path to GDAL bin64 directory containing gdal_translate.exe,
                  gdaladdo.exe, and other GDAL utilities.

        Raises:
            FileNotFoundError: If HEC-RAS installation or GDAL tools not found.

        Example:
            >>> gdal_path = RasTerrain._get_hecras_gdal_path("7.0")
            >>> print(gdal_path)
            C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\GDAL\\bin64
        """
        hecras_path = RasTerrain._get_hecras_path(version)

        # Check for GDAL in different possible locations
        gdal_paths = [
            hecras_path / "GDAL" / "bin64",
            hecras_path / "GDAL" / "bin",
            hecras_path / "gdal" / "bin64",
            hecras_path / "gdal" / "bin",
        ]

        for gdal_path in gdal_paths:
            if gdal_path.exists():
                # Verify key GDAL tools exist
                gdal_translate = gdal_path / "gdal_translate.exe"
                if gdal_translate.exists():
                    logger.debug(f"Found HEC-RAS GDAL tools at {gdal_path}")
                    return gdal_path

        raise FileNotFoundError(
            f"HEC-RAS GDAL tools not found in {hecras_path}. "
            f"Expected GDAL\\bin64\\gdal_translate.exe to exist."
        )

    @staticmethod
    @log_call
    def _generate_prj_from_raster(
        raster_path: Union[str, Path],
        output_prj: Union[str, Path]
    ) -> Path:
        """
        Generate ESRI PRJ file from raster's coordinate reference system.

        Reads the CRS from the input raster and writes it as an ESRI-format
        projection file (.prj) suitable for use with RasProcess.exe.

        Args:
            raster_path: Path to input raster file (GeoTIFF, etc.).
            output_prj: Path for output ESRI PRJ file.

        Returns:
            Path: Path to created PRJ file.

        Raises:
            ImportError: If rasterio is not installed.
            ValueError: If raster has no CRS defined.
            FileNotFoundError: If raster file not found.

        Example:
            >>> prj_file = RasTerrain._generate_prj_from_raster(
            ...     "dem.tif",
            ...     "Projection.prj"
            ... )
        """
        raster_path = Path(raster_path)
        output_prj = Path(output_prj)

        if not raster_path.exists():
            raise FileNotFoundError(f"Raster file not found: {raster_path}")

        try:
            import rasterio
        except ImportError:
            raise ImportError(
                "rasterio is required for automatic PRJ generation. "
                "Install with: pip install rasterio\n"
                "Alternatively, provide an existing ESRI PRJ file."
            )

        with rasterio.open(raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    f"Raster has no CRS defined: {raster_path}. "
                    f"Cannot generate projection file."
                )

            # Get WKT in ESRI format
            try:
                # pyproj 3.x approach
                from pyproj import CRS
                crs = CRS.from_wkt(src.crs.to_wkt())
                prj_wkt = crs.to_wkt("WKT1_ESRI")
            except (ImportError, AttributeError):
                # Fallback: use rasterio's WKT (may not be ESRI format)
                prj_wkt = src.crs.to_wkt()
                logger.warning(
                    "pyproj not available for ESRI WKT conversion. "
                    "Using standard WKT format."
                )

        # Ensure parent directory exists
        output_prj.parent.mkdir(parents=True, exist_ok=True)

        # Write PRJ file
        output_prj.write_text(prj_wkt, encoding='utf-8')
        logger.info(f"Created projection file: {output_prj}")

        return output_prj

    @staticmethod
    @log_call
    def create_terrain_hdf(
        input_rasters: List[Union[str, Path]],
        output_hdf: Union[str, Path],
        projection_prj: Union[str, Path],
        units: str = "Feet",
        stitch: bool = True,
        hecras_version: str = "7.0",
        timeout_seconds: int = 600,
    ) -> Path:
        """
        Create HEC-RAS terrain HDF from input rasters using RasProcess.exe.

        This method uses the verified RasProcess.exe CreateTerrain command
        to create a terrain HDF file compatible with HEC-RAS. The created
        terrain includes:
        - Multi-resolution pyramid levels (7 levels, 0-6)
        - TIN stitching for seamless multi-source terrain
        - Tile-based storage optimized for HEC-RAS rendering

        Args:
            input_rasters: List of input raster file paths (GeoTIFF, FLT, etc.).
                          Files are processed in priority order - first file
                          has highest priority in overlapping areas.
            output_hdf: Path for output terrain HDF file. Parent directory
                       will be created if it doesn't exist.
            projection_prj: Path to ESRI PRJ file defining the coordinate
                           reference system. Must be an existing file.
            units: Vertical data units. Options: "Feet" or "Meters".
                   Defaults to "Feet".
            stitch: Enable terrain stitching for multi-source terrains.
                   Defaults to True.
            hecras_version: HEC-RAS version to use for RasProcess.exe.
                           Defaults to "7.0".
            timeout_seconds: Maximum time to wait for RasProcess.exe to
                            finish terrain creation. Defaults to 600
                            seconds (10 minutes).

        Returns:
            Path: Path to created terrain HDF file.

        Raises:
            FileNotFoundError: If HEC-RAS installation, input rasters, or
                              PRJ file not found.
            ValueError: If units is not "Feet" or "Meters".
            RuntimeError: If terrain creation fails.

        Example:
            >>> from pathlib import Path
            >>> terrain = RasTerrain.create_terrain_hdf(
            ...     input_rasters=[Path("Terrain/dem.tif")],
            ...     output_hdf=Path("Terrain/Terrain.hdf"),
            ...     projection_prj=Path("Terrain/Projection.prj"),
            ...     units="Feet",
            ...     stitch=True,
            ...     hecras_version="7.0",
            ...     timeout_seconds=1800,
            ... )
            >>> print(f"Terrain created: {terrain}")

        Notes:
            - The RasProcess.exe command requires all paths to be quoted
              due to spaces in "Program Files".
            - Input rasters are processed in order - first raster has
              priority in overlapping areas.
            - The output folder will be created automatically if it doesn't
              exist.
            - Verified working with HEC-RAS 6.6 (tested 2025-12-25).
        """
        # Convert to Path objects
        output_hdf = Path(output_hdf)
        projection_prj = Path(projection_prj)
        input_rasters = [Path(r) for r in input_rasters]

        # Validate units
        if units not in ("Feet", "Meters"):
            raise ValueError(
                f"Units must be 'Feet' or 'Meters', got: '{units}'"
            )
        if timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be positive, got: {timeout_seconds}"
            )

        # Validate input files exist
        for raster in input_rasters:
            if not raster.exists():
                raise FileNotFoundError(f"Input raster not found: {raster}")

        # Validate PRJ file exists
        if not projection_prj.exists():
            raise FileNotFoundError(
                f"Projection PRJ file not found: {projection_prj}. "
                f"Use _generate_prj_from_raster() to create one from a raster."
            )

        # Get HEC-RAS path
        hecras_path = RasTerrain._get_hecras_path(hecras_version)
        rasprocess = hecras_path / "RasProcess.exe"

        # Ensure output directory exists
        output_hdf.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing output if present
        if output_hdf.exists():
            output_hdf.unlink()
            logger.info(f"Removed existing terrain HDF: {output_hdf}")

        # Build command string with proper quoting
        # Note: Must use shell=True due to spaces in "Program Files"
        stitch_str = "true" if stitch else "false"

        cmd_str = (
            f'"{rasprocess}" CreateTerrain '
            f'units={units} stitch={stitch_str} '
            f'prj="{projection_prj}" '
            f'out="{output_hdf}"'
        )

        # Add input files (all in double quotes)
        for raster in input_rasters:
            cmd_str += f' "{raster}"'

        logger.info(f"Executing terrain creation command...")
        logger.debug(f"Command: {cmd_str}")

        # Execute command
        try:
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            logger.debug(f"Return code: {result.returncode}")

            if result.stdout:
                logger.debug(f"STDOUT: {result.stdout}")

            if result.stderr:
                logger.warning(f"STDERR: {result.stderr}")

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Terrain creation timed out after {timeout_seconds} seconds. "
                "This may indicate very large input files or system issues."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to execute RasProcess.exe: {e}")

        # Verify output was created
        if not output_hdf.exists():
            error_details = ""
            if result.stderr:
                error_details = f" STDERR: {result.stderr}"
            if result.stdout:
                error_details += f" STDOUT: {result.stdout}"

            raise RuntimeError(
                f"Terrain creation failed - output HDF not created: {output_hdf}."
                f" Return code: {result.returncode}.{error_details}"
            )

        # Log success
        file_size = output_hdf.stat().st_size
        logger.info(
            f"Terrain HDF created successfully: {output_hdf} "
            f"({file_size:,} bytes, {file_size/1024/1024:.2f} MB)"
        )

        return output_hdf

    @staticmethod
    @log_call
    def vrt_to_tiff(
        vrt_path: Union[str, Path],
        output_path: Union[str, Path],
        compression: str = "LZW",
        create_overviews: bool = True,
        overview_levels: Optional[List[int]] = None,
        nodata_value: Optional[float] = None,
        hecras_version: str = "7.0"
    ) -> Path:
        """
        Convert VRT (Virtual Raster) to single optimized TIFF.

        Uses GDAL tools bundled with HEC-RAS installation to convert a VRT
        mosaic to a single GeoTIFF file. Optionally adds pyramid overviews
        for faster rendering in HEC-RAS.

        Args:
            vrt_path: Path to input VRT file.
            output_path: Path for output TIFF file.
            compression: Compression algorithm for output TIFF.
                        Options: "LZW", "DEFLATE", "ZSTD", "NONE".
                        Defaults to "LZW".
            create_overviews: Add pyramid overviews for faster rendering.
                             Defaults to True.
            overview_levels: Custom overview levels (e.g., [2, 4, 8, 16, 32]).
                            Defaults to [2, 4, 8, 16, 32] if None.
            nodata_value: NoData value for output raster. If None, uses
                         source NoData value.
            hecras_version: HEC-RAS version for GDAL tools path.
                           Defaults to "7.0".

        Returns:
            Path: Path to created TIFF file.

        Raises:
            FileNotFoundError: If VRT file or HEC-RAS GDAL tools not found.
            RuntimeError: If conversion fails.

        Example:
            >>> output = RasTerrain.vrt_to_tiff(
            ...     vrt_path="terrain/combined.vrt",
            ...     output_path="terrain/combined.tif",
            ...     compression="LZW",
            ...     create_overviews=True
            ... )
        """
        vrt_path = Path(vrt_path)
        output_path = Path(output_path)

        if not vrt_path.exists():
            raise FileNotFoundError(f"VRT file not found: {vrt_path}")

        # Set default overview levels
        if overview_levels is None:
            overview_levels = [2, 4, 8, 16, 32]

        # Get GDAL tools path
        gdal_path = RasTerrain._get_hecras_gdal_path(hecras_version)
        gdal_translate = gdal_path / "gdal_translate.exe"
        gdaladdo = gdal_path / "gdaladdo.exe"

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build gdal_translate command
        cmd = [
            str(gdal_translate),
            "-of", "GTiff",
            "-co", f"COMPRESS={compression}",
            "-co", "TILED=YES",
            "-co", "BIGTIFF=IF_SAFER",
        ]

        if nodata_value is not None:
            cmd.extend(["-a_nodata", str(nodata_value)])

        cmd.extend([str(vrt_path), str(output_path)])

        logger.info(f"Converting VRT to TIFF: {vrt_path} -> {output_path}")
        logger.debug(f"Command: {' '.join(cmd)}")

        # Execute gdal_translate
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout for large files
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"gdal_translate failed with code {result.returncode}. "
                    f"STDERR: {result.stderr}"
                )

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "VRT to TIFF conversion timed out. "
                "Consider processing smaller areas."
            )
        except Exception as e:
            if "RuntimeError" in str(type(e)):
                raise
            raise RuntimeError(f"Failed to execute gdal_translate: {e}")

        # Verify output was created
        if not output_path.exists():
            raise RuntimeError(
                f"TIFF creation failed - output file not created: {output_path}"
            )

        logger.info(f"TIFF created: {output_path}")

        # Add overviews if requested
        if create_overviews:
            logger.info(f"Adding pyramid overviews: {overview_levels}")

            cmd = [
                str(gdaladdo),
                "-r", "average",
                str(output_path)
            ] + [str(level) for level in overview_levels]

            logger.debug(f"Command: {' '.join(cmd)}")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout for overviews
                )

                if result.returncode != 0:
                    logger.warning(
                        f"gdaladdo failed with code {result.returncode}. "
                        f"STDERR: {result.stderr}. Continuing without overviews."
                    )
                else:
                    logger.info("Pyramid overviews added successfully")

            except subprocess.TimeoutExpired:
                logger.warning(
                    "Overview creation timed out. Continuing without overviews."
                )
            except Exception as e:
                logger.warning(f"Failed to add overviews: {e}")

        # Log final file info
        file_size = output_path.stat().st_size
        logger.info(
            f"VRT to TIFF conversion complete: {output_path} "
            f"({file_size:,} bytes, {file_size/1024/1024:.2f} MB)"
        )

        return output_path

    @staticmethod
    @log_call
    def create_terrain_from_rasters(
        input_rasters: List[Union[str, Path]],
        output_folder: Union[str, Path],
        terrain_name: str = "Terrain",
        units: str = "Feet",
        stitch: bool = True,
        hecras_version: str = "7.0",
        generate_prj: bool = True
    ) -> Path:
        """
        Create HEC-RAS terrain from input rasters with automatic PRJ generation.

        This is a convenience method that combines PRJ generation and terrain
        creation. It automatically generates the projection file from the first
        input raster's CRS.

        Args:
            input_rasters: List of input raster file paths.
            output_folder: Folder for terrain output (HDF + PRJ files).
            terrain_name: Base name for terrain files (e.g., "Terrain" creates
                         Terrain.hdf). Defaults to "Terrain".
            units: Vertical data units ("Feet" or "Meters").
            stitch: Enable terrain stitching. Defaults to True.
            hecras_version: HEC-RAS version. Defaults to "7.0".
            generate_prj: Auto-generate PRJ from first raster. If False,
                         expects Projection.prj to exist in output_folder.

        Returns:
            Path: Path to created terrain HDF file.

        Raises:
            FileNotFoundError: If input rasters not found.
            ImportError: If rasterio not available for PRJ generation.
            RuntimeError: If terrain creation fails.

        Example:
            >>> terrain = RasTerrain.create_terrain_from_rasters(
            ...     input_rasters=["lidar_dem.tif", "bathymetry.tif"],
            ...     output_folder="Terrain",
            ...     terrain_name="Terrain50",
            ...     units="Feet"
            ... )
        """
        output_folder = Path(output_folder)
        input_rasters = [Path(r) for r in input_rasters]

        # Validate input files exist
        for raster in input_rasters:
            if not raster.exists():
                raise FileNotFoundError(f"Input raster not found: {raster}")

        # Ensure output folder exists
        output_folder.mkdir(parents=True, exist_ok=True)

        # Define output paths
        output_hdf = output_folder / f"{terrain_name}.hdf"
        projection_prj = output_folder / "Projection.prj"

        # Generate PRJ if requested and not already present
        if generate_prj and not projection_prj.exists():
            logger.debug(f"Generating projection file from: {input_rasters[0]}")
            RasTerrain._generate_prj_from_raster(
                input_rasters[0],
                projection_prj
            )
        elif not projection_prj.exists():
            raise FileNotFoundError(
                f"Projection file not found and generate_prj=False: {projection_prj}"
            )

        # Create terrain HDF
        return RasTerrain.create_terrain_hdf(
            input_rasters=input_rasters,
            output_hdf=output_hdf,
            projection_prj=projection_prj,
            units=units,
            stitch=stitch,
            hecras_version=hecras_version
        )

    @staticmethod
    def get_available_versions() -> List[str]:
        """
        Get list of installed HEC-RAS versions with terrain creation support.

        Scans standard HEC-RAS installation directories for versions that
        have RasProcess.exe available.

        Returns:
            List[str]: List of version strings (e.g., ["7.0", "6.5"]).
                      Empty list if no compatible versions found.

        Example:
            >>> versions = RasTerrain.get_available_versions()
            >>> print(versions)
            ['6.6', '6.5', '6.4', '6.3']
        """
        versions = []

        for base_path in RasTerrain._HECRAS_BASE_PATHS:
            if not base_path.exists():
                continue

            for subdir in base_path.iterdir():
                if not subdir.is_dir():
                    continue

                rasprocess = subdir / "RasProcess.exe"
                if rasprocess.exists():
                    versions.append(subdir.name)

        # Sort versions in descending order
        versions.sort(reverse=True)

        return versions
