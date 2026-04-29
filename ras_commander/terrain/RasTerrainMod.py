"""
RasTerrainMod - Terrain Modification Analysis via RasMapperLib.dll

This module provides static methods for sampling HEC-RAS terrain WITH terrain
modifications applied, enabling cut/fill analysis and no-net-fill calculations
without requiring the RASMapper GUI.

Uses pythonnet to call RasMapperLib.dll's RASMapperCom class directly from Python.
Terrain modifications (channels, levees, polygons, etc.) are automatically applied
to all terrain sampling operations.

Summary:
    Wraps RASMapperCom methods (TerrainExtent, TerrainProfile, TerrainVolumeElevation)
    for headless terrain analysis with modifications. No HEC-RAS GUI required.

Key Functions:
    setup_gdal_bridge():
        Configure HEC-RAS GDAL paths before pythonnet loading.

    get_terrain_extent():
        Get terrain layer bounding box (with modifications).

    get_terrain_profile():
        Sample terrain along a polyline (with modifications applied).

    get_terrain_volume_elevation():
        Compute elevation-volume curve for a polygon (with modifications).

    compare_terrain_profiles():
        Compare two terrain profiles for cut/fill analysis.

    compare_terrain_volumes():
        Compare elevation-volume curves for no-net-fill analysis.

Platform:
    Windows only (requires HEC-RAS 6.6+ and .NET Framework)

Requirements:
    - HEC-RAS 6.6+ installed
    - pythonnet (pip install pythonnet)
    - HEC-RAS GDAL runtime, configured automatically before RasMapperLib loads

Example:
    from ras_commander.terrain import RasTerrainMod

    # One-time setup
    RasTerrainMod.setup_gdal_bridge()

    # Sample terrain profile with modifications
    profile = RasTerrainMod.get_terrain_profile(
        rasmap_path="project.rasmap",
        geom_hdf_path="project.g01.hdf",
        x_coords=[3400000, 3405000, 3410000],
        y_coords=[612000, 612000, 612000]
    )
"""

import platform
import threading
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..Decorators import log_call
from .._gdal_runtime import (
    configure_hecras_gdal_runtime,
    configure_rasmapper_gdal_bridge,
)
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

_RAS_INSTALL_PATHS = [
    Path("C:/Program Files (x86)/HEC/HEC-RAS/7.0"),
    Path("C:/Program Files (x86)/HEC/HEC-RAS/6.6"),
    Path("C:/Program Files (x86)/HEC/HEC-RAS/6.5"),
    Path("C:/Program Files/HEC/HEC-RAS/7.0"),
    Path("C:/Program Files/HEC/HEC-RAS/6.6"),
    Path("C:/Program Files/HEC/HEC-RAS/6.5"),
]


class RasTerrainMod:
    """
    Static class for terrain modification analysis via RasMapperLib.dll.

    Provides headless terrain sampling with modifications applied, enabling
    cut/fill analysis and no-net-fill calculations without the RASMapper GUI.

    All methods are static - call directly without instantiation:
        RasTerrainMod.get_terrain_profile(rasmap, geom_hdf, x, y)

    Prerequisites:
        1. HEC-RAS 6.6+ installed
        2. pythonnet installed (pip install pythonnet)
        3. HEC-RAS GDAL runtime available from the HEC-RAS install

    Thread Safety:
        NOT thread-safe. The .NET RASMapperCom instance is shared and COM
        objects follow single-threaded apartment (STA) rules. Do not call
        methods concurrently from multiple threads.
    """

    _com_instance = None
    _ras_path = None
    _initialized = False
    _lock = threading.Lock()

    @staticmethod
    def _find_hecras_path() -> Path:
        """Find HEC-RAS installation directory."""
        for path in _RAS_INSTALL_PATHS:
            if (path / "RasMapperLib.dll").exists():
                return path
        raise FileNotFoundError(
            "HEC-RAS 6.5+ installation not found. "
            "Searched: " + ", ".join(str(p) for p in _RAS_INSTALL_PATHS)
        )

    @staticmethod
    @log_call
    def setup_gdal_bridge(
        hecras_version: str = "7.0",
        python_dir: Optional[Union[str, Path]] = None,
        create_junction: bool = True,
    ) -> bool:
        """
        Configure HEC-RAS GDAL runtime for pythonnet/RasMapperLib.

        The default path points GDAL_DATA, PROJ_LIB, PATH, and Python DLL search
        directories at HEC-RAS's bundled GDAL runtime, then verifies the legacy
        ``python.exe`` sibling GDAL bridge before RasMapperLib is loaded.

        Args:
            hecras_version: HEC-RAS version to use (default "7.0")
            python_dir: Python installation directory for legacy junction mode
            create_junction: Verify/create the legacy python.exe sibling junction

        Returns:
            True if the process runtime was configured successfully.
        """
        ras_path = RasTerrainMod._find_hecras_path()

        if hecras_version:
            version_text = str(hecras_version)
            versioned_path = ras_path.parent / version_text
            if (versioned_path / "RasMapperLib.dll").exists():
                ras_path = versioned_path

        try:
            configure_hecras_gdal_runtime(ras_path)
        except FileNotFoundError as exc:
            logger.error(str(exc))
            return False

        if create_junction:
            try:
                configure_rasmapper_gdal_bridge(ras_path, python_dir)
            except (FileNotFoundError, RuntimeError) as exc:
                logger.error(str(exc))
                return False

        logger.info("Configured HEC-RAS GDAL runtime from %s", ras_path / "GDAL")
        return True

    @staticmethod
    def _ensure_initialized():
        """Initialize pythonnet and RasMapperLib if not already done."""
        if RasTerrainMod._initialized:
            return

        if platform.system() != "Windows":
            raise RuntimeError("RasTerrainMod requires Windows (HEC-RAS is Windows-only)")

        try:
            import clr
        except ImportError:
            raise ImportError(
                "pythonnet is required for RasTerrainMod. "
                "Install with: pip install pythonnet"
            )

        ras_path = RasTerrainMod._find_hecras_path()
        RasTerrainMod._ras_path = ras_path

        try:
            configure_rasmapper_gdal_bridge(ras_path)
        except (FileNotFoundError, RuntimeError) as exc:
            raise RuntimeError(
                f"Failed to initialize HEC-RAS GDAL runtime from {ras_path}: {exc}"
            ) from exc

        # Load RasMapperLib.dll
        try:
            clr.AddReference(str(ras_path / "RasMapperLib.dll"))
            logger.info(f"RasMapperLib.dll loaded from {ras_path}")
        except Exception as e:
            raise RuntimeError(
                f"Failed to load RasMapperLib.dll from {ras_path}: {e}"
            )

        RasTerrainMod._initialized = True

    @staticmethod
    def _get_com():
        """Get or create the RASMapperCom instance (thread-safe)."""
        with RasTerrainMod._lock:
            RasTerrainMod._ensure_initialized()

            if RasTerrainMod._com_instance is None:
                from RasMapperLib import RASMapperCom
                RasTerrainMod._com_instance = RASMapperCom()
                logger.debug("Created RASMapperCom instance")

            return RasTerrainMod._com_instance

    @staticmethod
    def _validate_paths(rasmap_path: Union[str, Path], geom_hdf_path: Union[str, Path]):
        """Validate that rasmap and geometry HDF paths exist."""
        rasmap_path = Path(rasmap_path)
        geom_hdf_path = Path(geom_hdf_path)
        if not rasmap_path.exists():
            raise FileNotFoundError(f"rasmap file not found: {rasmap_path}")
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")
        return rasmap_path, geom_hdf_path

    @staticmethod
    def _validate_coords(x_coords: List[float], y_coords: List[float]):
        """Validate coordinate arrays are finite and matching length."""
        if len(x_coords) != len(y_coords):
            raise ValueError("x_coords and y_coords must have the same length")
        arr = np.array(x_coords + y_coords, dtype=float)
        if not np.all(np.isfinite(arr)):
            raise ValueError("Coordinate values must be finite (no NaN or inf)")

    @staticmethod
    @log_call
    def get_terrain_extent(
        rasmap_path: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        ras_object=None
    ) -> dict:
        """
        Get the terrain bounding box with modifications applied.

        Args:
            rasmap_path: Path to .rasmap project file
            geom_hdf_path: Path to geometry HDF file (.g##.hdf)

        Returns:
            dict with keys: success, min_x, max_x, min_y, max_y

        Example:
            >>> extent = RasTerrainMod.get_terrain_extent(
            ...     "project.rasmap", "project.g01.hdf"
            ... )
            >>> print(f"Extent: {extent['min_x']:.0f} to {extent['max_x']:.0f}")
        """
        rasmap_path, geom_hdf_path = RasTerrainMod._validate_paths(rasmap_path, geom_hdf_path)
        com = RasTerrainMod._get_com()

        try:
            result = com.TerrainExtent(
                str(rasmap_path), str(geom_hdf_path),
                0.0, 0.0, 0.0, 0.0
            )
        except Exception as e:
            raise RuntimeError(
                f"TerrainExtent failed for rasmap='{rasmap_path}': {e}"
            ) from e

        # pythonnet returns all ref params: (success, rasmap, geom, minX, maxX, minY, maxY)
        return {
            'success': result[0],
            'min_x': result[3],
            'max_x': result[4],
            'min_y': result[5],
            'max_y': result[6],
        }

    @staticmethod
    @log_call
    def get_terrain_profile(
        rasmap_path: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        x_coords: List[float],
        y_coords: List[float],
        filter_tolerance: float = 0.01,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Sample terrain elevation along a polyline with modifications applied.

        The terrain profile includes ALL terrain modifications (channels, levees,
        polygon overrides, etc.) that exist in the terrain HDF referenced by
        the .rasmap file.

        Args:
            rasmap_path: Path to .rasmap project file
            geom_hdf_path: Path to geometry HDF file (.g##.hdf)
            x_coords: X coordinates defining the profile polyline
            y_coords: Y coordinates defining the profile polyline
            filter_tolerance: Douglas-Peucker vertical filter tolerance (default 0.01)

        Returns:
            DataFrame with columns:
            - station: float - distance along polyline (project units)
            - elevation: float - terrain elevation with modifications

        Example:
            >>> profile = RasTerrainMod.get_terrain_profile(
            ...     "project.rasmap", "project.g01.hdf",
            ...     x_coords=[3400000, 3410000],
            ...     y_coords=[612000, 612000]
            ... )
            >>> profile.plot(x='station', y='elevation')
        """
        rasmap_path, geom_hdf_path = RasTerrainMod._validate_paths(rasmap_path, geom_hdf_path)
        RasTerrainMod._validate_coords(x_coords, y_coords)
        com = RasTerrainMod._get_com()

        from System import Array, Double, Single

        n = len(x_coords)
        if n < 2:
            raise ValueError("Need at least 2 points to define a profile line")

        x = Array.CreateInstance(Double, n)
        y = Array.CreateInstance(Double, n)
        for i in range(n):
            x[i] = float(x_coords[i])
            y[i] = float(y_coords[i])

        sta = Array.CreateInstance(Single, 0)
        elev = Array.CreateInstance(Single, 0)

        try:
            # All 10 params are ref - pythonnet returns all in tuple:
            # (rasmap, geom, count, x, y, tol, profileCount, station, elevation, err)
            result = com.TerrainProfile(
                str(rasmap_path), str(geom_hdf_path),
                n, x, y, filter_tolerance,
                0, sta, elev, ''
            )
        except Exception as e:
            raise RuntimeError(
                f"TerrainProfile failed for rasmap='{rasmap_path}': {e}"
            ) from e

        prof_count = result[6]
        sta_out = result[7]
        elev_out = result[8]
        err_out = result[9]

        if err_out:
            logger.warning(f"TerrainProfile warning: {err_out}")

        if prof_count == 0:
            logger.warning("TerrainProfile returned 0 points")
            return pd.DataFrame(columns=['station', 'elevation'])

        return pd.DataFrame({
            'station': [float(sta_out[i]) for i in range(prof_count)],
            'elevation': [float(elev_out[i]) for i in range(prof_count)],
        })

    @staticmethod
    @log_call
    def get_terrain_volume_elevation(
        rasmap_path: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        x_coords: List[float],
        y_coords: List[float],
        filter_tolerance: float = 0.01,
        volume_factor: float = 1.0,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Compute elevation-volume curve for a polygon with modifications applied.

        Returns the volume of space below each elevation within the polygon,
        computed from the modified terrain surface (including channels, ponds, etc.).

        Args:
            rasmap_path: Path to .rasmap project file
            geom_hdf_path: Path to geometry HDF file (.g##.hdf)
            x_coords: X coordinates of polygon vertices (must close - first == last)
            y_coords: Y coordinates of polygon vertices (must close - first == last)
            filter_tolerance: Terrain sampling tolerance (default 0.01)
            volume_factor: Volume conversion factor:
                - 1.0 = cubic feet (if project units are feet)
                - 43560.0 = acre-feet
                - 0.0283168 = cubic meters (from cubic feet)

        Returns:
            DataFrame with columns:
            - elevation: float - terrain elevation
            - volume: float - cumulative volume below that elevation

        Example:
            >>> # Define a pond polygon (must close)
            >>> x = [3400000, 3400500, 3400500, 3400000, 3400000]
            >>> y = [612000, 612000, 612500, 612500, 612000]
            >>> ev = RasTerrainMod.get_terrain_volume_elevation(
            ...     "project.rasmap", "project.g01.hdf", x, y
            ... )
            >>> ev.plot(x='elevation', y='volume', title='Elev-Volume Curve')
        """
        rasmap_path, geom_hdf_path = RasTerrainMod._validate_paths(rasmap_path, geom_hdf_path)
        RasTerrainMod._validate_coords(x_coords, y_coords)
        com = RasTerrainMod._get_com()

        from System import Array, Double, Single

        n = len(x_coords)
        if n < 4:
            raise ValueError("Need at least 4 points (3 vertices + closing point)")

        x = Array.CreateInstance(Double, n)
        y = Array.CreateInstance(Double, n)
        for i in range(n):
            x[i] = float(x_coords[i])
            y[i] = float(y_coords[i])

        elev = Array.CreateInstance(Single, 0)
        vol = Array.CreateInstance(Single, 0)

        try:
            # All 11 params are ref - pythonnet returns all in tuple:
            # (rasmap, geom, count, x, y, tol, volFactor, tableCount, elev, vol, err)
            result = com.TerrainVolumeElevation(
                str(rasmap_path), str(geom_hdf_path),
                n, x, y, filter_tolerance, volume_factor,
                0, elev, vol, ''
            )
        except Exception as e:
            raise RuntimeError(
                f"TerrainVolumeElevation failed for rasmap='{rasmap_path}': {e}"
            ) from e

        table_count = result[7]
        elev_out = result[8]
        vol_out = result[9]
        err_out = result[10]

        if err_out:
            logger.warning(f"TerrainVolumeElevation warning: {err_out}")

        if table_count == 0:
            logger.warning("TerrainVolumeElevation returned 0 rows")
            return pd.DataFrame(columns=['elevation', 'volume'])

        return pd.DataFrame({
            'elevation': [float(elev_out[i]) for i in range(table_count)],
            'volume': [float(vol_out[i]) for i in range(table_count)],
        })

    @staticmethod
    @log_call
    def compare_terrain_profiles(
        rasmap_existing: Union[str, Path],
        rasmap_proposed: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        x_coords: List[float],
        y_coords: List[float],
        filter_tolerance: float = 0.01,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Compare terrain profiles between existing and proposed conditions.

        Computes cut/fill along a profile line by differencing terrain elevations
        from two .rasmap files (each referencing different terrain HDFs with
        different terrain modifications).

        Args:
            rasmap_existing: Path to .rasmap with existing terrain
            rasmap_proposed: Path to .rasmap with proposed terrain (with modifications)
            geom_hdf_path: Path to geometry HDF (shared between both)
            x_coords: X coordinates of profile line
            y_coords: Y coordinates of profile line
            filter_tolerance: Terrain sampling tolerance

        Returns:
            DataFrame with columns:
            - station: float - distance along profile
            - existing_elevation: float - existing terrain elevation
            - proposed_elevation: float - proposed terrain elevation
            - difference: float - proposed - existing (positive = fill, negative = cut)

        Example:
            >>> df = RasTerrainMod.compare_terrain_profiles(
            ...     "existing.rasmap", "proposed.rasmap", "project.g01.hdf",
            ...     x_coords=[3400000, 3410000], y_coords=[612000, 612000]
            ... )
            >>> cut_volume = df[df['difference'] < 0]['difference'].sum()
            >>> fill_volume = df[df['difference'] > 0]['difference'].sum()
        """
        existing = RasTerrainMod.get_terrain_profile(
            rasmap_existing, geom_hdf_path, x_coords, y_coords, filter_tolerance
        )
        proposed = RasTerrainMod.get_terrain_profile(
            rasmap_proposed, geom_hdf_path, x_coords, y_coords, filter_tolerance
        )

        if len(existing) == 0 or len(proposed) == 0:
            logger.warning("One or both profiles are empty")
            return pd.DataFrame(columns=[
                'station', 'existing_elevation', 'proposed_elevation', 'difference'
            ])

        # Clip to overlapping station range to avoid extrapolation
        sta_min = max(existing['station'].iloc[0], proposed['station'].iloc[0])
        sta_max = min(existing['station'].iloc[-1], proposed['station'].iloc[-1])
        mask = (existing['station'] >= sta_min) & (existing['station'] <= sta_max)
        existing_clipped = existing[mask]

        if len(existing_clipped) == 0:
            logger.warning("No overlapping station range between profiles")
            return pd.DataFrame(columns=[
                'station', 'existing_elevation', 'proposed_elevation', 'difference'
            ])

        proposed_interp = np.interp(
            existing_clipped['station'].values,
            proposed['station'].values,
            proposed['elevation'].values
        )

        return pd.DataFrame({
            'station': existing_clipped['station'].values,
            'existing_elevation': existing_clipped['elevation'].values,
            'proposed_elevation': proposed_interp,
            'difference': proposed_interp - existing_clipped['elevation'].values,
        })

    @staticmethod
    @log_call
    def compare_terrain_volumes(
        rasmap_existing: Union[str, Path],
        rasmap_proposed: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        x_coords: List[float],
        y_coords: List[float],
        filter_tolerance: float = 0.01,
        volume_factor: float = 1.0,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Compare elevation-volume curves for no-net-fill analysis.

        Computes volume differences between existing and proposed terrain
        within a polygon, enabling no-net-fill compliance checking.

        At each elevation:
        - net_volume = proposed_volume - existing_volume
        - Positive net_volume = net fill added
        - Negative net_volume = net cut (excavation exceeds fill)
        - Zero net_volume = no-net-fill condition met

        Args:
            rasmap_existing: Path to .rasmap with existing terrain
            rasmap_proposed: Path to .rasmap with proposed terrain
            geom_hdf_path: Path to geometry HDF (shared)
            x_coords: Polygon X coordinates (must close)
            y_coords: Polygon Y coordinates (must close)
            filter_tolerance: Terrain sampling tolerance
            volume_factor: Volume unit conversion (1.0 = cubic feet)

        Returns:
            DataFrame with columns:
            - elevation: float - terrain elevation
            - existing_volume: float - volume below elevation (existing)
            - proposed_volume: float - volume below elevation (proposed)
            - net_volume: float - proposed - existing (positive = net fill)

        Example:
            >>> df = RasTerrainMod.compare_terrain_volumes(
            ...     "existing.rasmap", "proposed.rasmap", "project.g01.hdf",
            ...     x_coords=pond_x, y_coords=pond_y,
            ...     volume_factor=43560.0  # acre-feet
            ... )
            >>> # Check no-net-fill at 100-year flood elevation
            >>> flood_elev = 10.0
            >>> row = df[df['elevation'] >= flood_elev].iloc[0]
            >>> print(f"Net volume at {flood_elev} ft: {row['net_volume']:.1f} ac-ft")
        """
        existing = RasTerrainMod.get_terrain_volume_elevation(
            rasmap_existing, geom_hdf_path, x_coords, y_coords,
            filter_tolerance, volume_factor
        )
        proposed = RasTerrainMod.get_terrain_volume_elevation(
            rasmap_proposed, geom_hdf_path, x_coords, y_coords,
            filter_tolerance, volume_factor
        )

        if len(existing) == 0 or len(proposed) == 0:
            logger.warning("One or both volume curves are empty")
            return pd.DataFrame(columns=[
                'elevation', 'existing_volume', 'proposed_volume', 'net_volume'
            ])

        # Create common elevation grid spanning both curves
        all_elevations = np.unique(np.concatenate([
            existing['elevation'].values,
            proposed['elevation'].values
        ]))

        # Clip to overlapping elevation range for reliable comparison
        elev_min = max(existing['elevation'].min(), proposed['elevation'].min())
        elev_max = min(existing['elevation'].max(), proposed['elevation'].max())
        all_elevations = all_elevations[
            (all_elevations >= elev_min) & (all_elevations <= elev_max)
        ]

        if len(all_elevations) == 0:
            logger.warning("No overlapping elevation range between volume curves")
            return pd.DataFrame(columns=[
                'elevation', 'existing_volume', 'proposed_volume', 'net_volume'
            ])

        # Interpolate both curves onto common grid
        existing_interp = np.interp(
            all_elevations,
            existing['elevation'].values,
            existing['volume'].values,
            left=0.0
        )
        proposed_interp = np.interp(
            all_elevations,
            proposed['elevation'].values,
            proposed['volume'].values,
            left=0.0
        )

        return pd.DataFrame({
            'elevation': all_elevations,
            'existing_volume': existing_interp,
            'proposed_volume': proposed_interp,
            'net_volume': proposed_interp - existing_interp,
        })

    @staticmethod
    @log_call
    def compute_modified_terrain_raster(
        rasmap_path: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        terrain_tif_path: Union[str, Path],
        output_tif_path: Optional[Union[str, Path]] = None,
        filter_tolerance: float = 0.0,
        ras_object=None,
    ) -> Optional[np.ndarray]:
        """
        Compute a full-resolution raster of terrain with modifications applied.

        Reads the original terrain GeoTIFF to determine the output grid (CRS,
        resolution, extent), then samples the modified terrain (with channels,
        levees, polygon overrides, etc.) at each cell center row-by-row via
        RasMapperLib. Where sampling succeeds, modified elevations replace the
        original; where it fails (e.g., outside the geometry extent), the
        original terrain value is preserved.

        Args:
            rasmap_path: Path to .rasmap project file
            geom_hdf_path: Path to geometry HDF file (.g##.hdf)
            terrain_tif_path: Path to original terrain GeoTIFF (defines output grid)
            output_tif_path: If provided, writes result to GeoTIFF (deflate compressed)
            filter_tolerance: Douglas-Peucker vertical filter tolerance for profile
                sampling (default 0.0 = maximum detail, no filtering)

        Returns:
            2D numpy array (float32) of modified terrain elevations, same shape as
            the input terrain raster. None if the terrain TIF cannot be read.

        Platform:
            Windows only (requires HEC-RAS 6.6+ and pythonnet).

        Example:
            >>> RasTerrainMod.setup_gdal_bridge()
            >>> arr = RasTerrainMod.compute_modified_terrain_raster(
            ...     "project.rasmap", "project.g01.hdf",
            ...     "Terrain/Terrain.tif",
            ...     output_tif_path="Terrain/Terrain_modified.tif"
            ... )
            >>> print(f"Shape: {arr.shape}, range: {arr.min():.1f} to {arr.max():.1f}")
        """
        import rasterio

        terrain_tif_path = Path(terrain_tif_path)
        if not terrain_tif_path.exists():
            raise FileNotFoundError(f"Terrain TIF not found: {terrain_tif_path}")

        rasmap_path, geom_hdf_path = RasTerrainMod._validate_paths(rasmap_path, geom_hdf_path)

        # Read terrain raster grid definition and original data
        with rasterio.open(terrain_tif_path) as src:
            height = src.height
            width = src.width
            transform = src.transform
            crs = src.crs
            nodata = src.nodata if src.nodata is not None else -9999.0
            original = src.read(1).astype(np.float32)

        # Compute cell center x-coordinates (constant for all rows)
        # transform: x = origin_x + col * pixel_width  (pixel_width = transform.a)
        x_centers = transform.c + (np.arange(width) + 0.5) * transform.a

        # Allocate output — start with original terrain
        modified = original.copy()

        logger.info(
            f"Sampling modified terrain: {width}x{height} grid "
            f"({width * height:,} cells, {height} rows)"
        )

        sampled_rows = 0
        for row_idx in range(height):
            # Cell center y for this row
            y_center = transform.f + (row_idx + 0.5) * transform.e

            # Horizontal polyline spanning the full row
            x_line = [float(x_centers[0]), float(x_centers[-1])]
            y_line = [float(y_center), float(y_center)]

            try:
                profile = RasTerrainMod.get_terrain_profile(
                    rasmap_path, geom_hdf_path,
                    x_coords=x_line, y_coords=y_line,
                    filter_tolerance=filter_tolerance,
                )
            except Exception as e:
                logger.debug(f"Row {row_idx} sampling failed: {e}")
                continue  # keep original values for this row

            if len(profile) < 2:
                continue  # keep original

            # Interpolate profile (station-based) to grid cell centers.
            # For a horizontal line, station = distance from start = x - x_start
            cell_stations = x_centers - x_centers[0]
            row_elevations = np.interp(
                cell_stations,
                profile['station'].values,
                profile['elevation'].values,
                left=np.nan, right=np.nan,
            )

            # Only overwrite cells where interpolation succeeded
            valid = np.isfinite(row_elevations)
            if valid.any():
                modified[row_idx, valid] = row_elevations[valid].astype(np.float32)
                sampled_rows += 1

            if (row_idx + 1) % 500 == 0:
                logger.info(f"  Progress: {row_idx + 1}/{height} rows")

        logger.info(f"Modified terrain raster: {sampled_rows}/{height} rows updated")

        # Write GeoTIFF if requested
        if output_tif_path is not None:
            output_tif_path = Path(output_tif_path)
            output_tif_path.parent.mkdir(parents=True, exist_ok=True)

            out_meta = {
                'driver': 'GTiff',
                'dtype': 'float32',
                'width': width,
                'height': height,
                'count': 1,
                'crs': crs,
                'transform': transform,
                'nodata': float(nodata),
                'compress': 'deflate',
            }

            with rasterio.open(output_tif_path, 'w', **out_meta) as dst:
                dst.write(modified, 1)

            logger.info(f"Modified terrain raster written to {output_tif_path}")

        return modified
