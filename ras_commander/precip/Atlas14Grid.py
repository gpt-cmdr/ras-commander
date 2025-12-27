"""
Atlas14Grid: Remote access to NOAA Atlas 14 precipitation frequency grids.

This module provides spatial access to NOAA Atlas 14 precipitation frequency
estimates via the consolidated CONUS NetCDF file, enabling efficient downloads
of only the data needed for a specific project extent.

Key Features:
- Remote spatial subsetting via HTTP byte-range requests (99.9% data reduction)
- Integration with HEC-RAS project extents (2D flow areas or project bounds)
- Support for all CONUS locations (24°N-50°N, -125°W to -66°W)
- All standard durations (1hr to 168hr) and return periods (2yr to 1000yr)

Example (Direct Bounds):
    >>> from ras_commander.precip import Atlas14Grid
    >>>
    >>> # Get precipitation frequency for a bounding box
    >>> pfe = Atlas14Grid.get_pfe_for_bounds(
    ...     bounds=(-95.5, 29.5, -95.0, 30.0),  # (west, south, east, north)
    ...     durations=[6, 12, 24],
    ...     return_periods=[10, 25, 50, 100]
    ... )

Example (HEC-RAS Project):
    >>> from ras_commander.precip import Atlas14Grid
    >>>
    >>> # Get PFE using HEC-RAS project extent
    >>> pfe = Atlas14Grid.get_pfe_from_project(
    ...     geom_hdf="MyProject.g01.hdf",
    ...     extent_source="2d_flow_area",
    ...     buffer_percent=10.0
    ... )

Data Source:
    NOAA Hydrometeorological Design Studies Center (HDSC)
    https://hdsc.nws.noaa.gov/pub/hdsc/data/

References:
    - NOAA Atlas 14: https://hdsc.nws.noaa.gov/pfds/
    - HDSC Precipitation Frequency Data Server
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Literal

import numpy as np
import pandas as pd

try:
    import xarray as xr
    XARRAY_AVAILABLE = True
except ImportError:
    XARRAY_AVAILABLE = False
    xr = None

try:
    import fsspec
    import h5py
    REMOTE_ACCESS_AVAILABLE = True
except ImportError:
    REMOTE_ACCESS_AVAILABLE = False
    fsspec = None
    h5py = None

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


class Atlas14Grid:
    """
    Remote access to NOAA Atlas 14 CONUS precipitation frequency grids.

    This class provides methods to:
    - Access Atlas 14 data remotely via HTTP byte-range requests
    - Extract precipitation frequency estimates for specific geographic bounds
    - Integrate with HEC-RAS project extents for automatic extent detection

    The data is accessed from a consolidated NetCDF file covering the entire
    Continental United States (CONUS), which supports partial reads via HTTP
    range requests. This enables downloading only the data needed for a specific
    project area, reducing data transfer by ~99.9% compared to downloading
    full state datasets.

    Attributes:
        CONUS_URL (str): URL to the NOAA Atlas 14 CONUS NetCDF file
        SCALE_FACTOR (float): Scale factor to convert raw values to inches
        AVAILABLE_DURATIONS (list): Available duration hours in the dataset
        AVAILABLE_RETURN_PERIODS (list): Available return periods in years
        COVERAGE_BOUNDS (tuple): Geographic coverage (west, south, east, north)

    Note:
        This class uses static methods and should not be instantiated.
        All methods are called directly on the class.
    """

    # NOAA HDSC CONUS NetCDF file URL
    CONUS_URL = "https://hdsc.nws.noaa.gov/pub/hdsc/data/tx/NOAA_Atlas_14_CONUS.nc"

    # Scale factor from NetCDF attributes (raw values * SCALE_FACTOR = inches)
    SCALE_FACTOR = 0.01

    # Available durations in hours (from NetCDF variable names)
    AVAILABLE_DURATIONS = [1, 2, 3, 6, 12, 24, 48, 72, 96, 168]

    # Available return periods in years (from 'ari' dimension)
    AVAILABLE_RETURN_PERIODS = [2, 5, 10, 25, 50, 100, 200, 500, 1000]

    # CONUS geographic coverage (decimal degrees)
    COVERAGE_BOUNDS = (-125.0, 24.0, -66.0, 50.0)  # (west, south, east, north)

    # NoData value
    NODATA_VALUE = -9

    # Coordinate arrays cache (loaded once, reused)
    _lat_cache: Optional[np.ndarray] = None
    _lon_cache: Optional[np.ndarray] = None
    _ari_cache: Optional[np.ndarray] = None

    @staticmethod
    def _check_dependencies() -> None:
        """Check that required dependencies are available."""
        if not REMOTE_ACCESS_AVAILABLE:
            raise ImportError(
                "Remote access requires 'fsspec' and 'h5py'. "
                "Install with: pip install fsspec h5py"
            )

    @staticmethod
    @log_call
    def _get_remote_file():
        """
        Open the remote CONUS NetCDF file for reading.

        Returns:
            h5py.File: HDF5 file handle for the remote NetCDF

        Raises:
            ImportError: If fsspec or h5py not installed
            IOError: If remote file cannot be accessed
        """
        Atlas14Grid._check_dependencies()

        try:
            fs = fsspec.filesystem('http')
            f = fs.open(Atlas14Grid.CONUS_URL)
            return h5py.File(f, 'r')
        except Exception as e:
            logger.error(f"Failed to open remote Atlas 14 file: {e}")
            raise IOError(f"Cannot access NOAA Atlas 14 CONUS NetCDF: {e}") from e

    @staticmethod
    @log_call
    def _load_coordinates() -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Load and cache coordinate arrays from the remote file.

        Returns:
            Tuple of (lat, lon, ari) numpy arrays

        Note:
            Coordinates are cached after first load to avoid repeated downloads.
        """
        if Atlas14Grid._lat_cache is not None:
            return (Atlas14Grid._lat_cache, Atlas14Grid._lon_cache,
                    Atlas14Grid._ari_cache)

        logger.info("Loading Atlas 14 coordinate arrays from remote file...")

        with Atlas14Grid._get_remote_file() as hf:
            Atlas14Grid._lat_cache = hf['lat'][:]
            Atlas14Grid._lon_cache = hf['lon'][:]
            Atlas14Grid._ari_cache = hf['ari'][:]

        logger.info(
            f"Loaded coordinates: lat={len(Atlas14Grid._lat_cache)}, "
            f"lon={len(Atlas14Grid._lon_cache)}, ari={len(Atlas14Grid._ari_cache)}"
        )

        return (Atlas14Grid._lat_cache, Atlas14Grid._lon_cache,
                Atlas14Grid._ari_cache)

    @staticmethod
    def _get_spatial_indices(
        bounds: Tuple[float, float, float, float]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get array indices for a geographic bounding box.

        Args:
            bounds: (west, south, east, north) in decimal degrees

        Returns:
            Tuple of (lat_indices, lon_indices) numpy arrays
        """
        west, south, east, north = bounds
        lat, lon, _ = Atlas14Grid._load_coordinates()

        lat_mask = (lat >= south) & (lat <= north)
        lon_mask = (lon >= west) & (lon <= east)

        lat_indices = np.where(lat_mask)[0]
        lon_indices = np.where(lon_mask)[0]

        if len(lat_indices) == 0 or len(lon_indices) == 0:
            raise ValueError(
                f"No data within bounds ({west}, {south}, {east}, {north}). "
                f"Valid range: lon={lon.min():.2f} to {lon.max():.2f}, "
                f"lat={lat.min():.2f} to {lat.max():.2f}"
            )

        return lat_indices, lon_indices

    @staticmethod
    def _duration_to_varname(duration_hours: int) -> str:
        """Convert duration in hours to NetCDF variable name."""
        return f"pf_{duration_hours:03d}_hr"

    @staticmethod
    def _get_ari_index(return_period: int) -> int:
        """Get index for a return period in the ARI dimension."""
        _, _, ari = Atlas14Grid._load_coordinates()

        # Find closest ARI
        idx = np.argmin(np.abs(ari - return_period))
        if ari[idx] != return_period:
            logger.warning(
                f"Return period {return_period} not exact match, "
                f"using {ari[idx]:.0f}-year"
            )
        return idx

    @staticmethod
    @log_call
    def get_pfe_for_bounds(
        bounds: Tuple[float, float, float, float],
        durations: Optional[List[int]] = None,
        return_periods: Optional[List[int]] = None,
        buffer_percent: float = 0.0
    ) -> Dict[str, np.ndarray]:
        """
        Get precipitation frequency estimates for a geographic bounding box.

        Downloads only the data within the specified bounds using HTTP
        byte-range requests, minimizing data transfer.

        Args:
            bounds: (west, south, east, north) in decimal degrees (WGS84)
            durations: List of durations in hours. If None, uses [24].
                      Valid values: 1, 2, 3, 6, 12, 24, 48, 72, 96, 168
            return_periods: List of return periods in years. If None, uses [100].
                           Valid values: 2, 5, 10, 25, 50, 100, 200, 500, 1000
            buffer_percent: Buffer to add around bounds as percentage (0-100)

        Returns:
            Dictionary containing:
                - 'lat': 1D array of latitude values
                - 'lon': 1D array of longitude values
                - 'bounds': (west, south, east, north) tuple
                - 'durations': list of requested durations
                - 'return_periods': list of requested return periods
                - 'pfe_{duration}hr': 3D array (lat, lon, ari) for each duration
                - 'units': 'inches'

        Example:
            >>> pfe = Atlas14Grid.get_pfe_for_bounds(
            ...     bounds=(-95.5, 29.5, -95.0, 30.0),
            ...     durations=[6, 12, 24],
            ...     return_periods=[10, 50, 100]
            ... )
            >>> print(f"Shape: {pfe['pfe_24hr'].shape}")
            >>> print(f"100-yr 24-hr max: {pfe['pfe_24hr'][:,:,5].max():.2f} inches")
        """
        Atlas14Grid._check_dependencies()

        if durations is None:
            durations = [24]
        if return_periods is None:
            return_periods = [100]

        # Validate durations
        invalid_durations = [d for d in durations
                           if d not in Atlas14Grid.AVAILABLE_DURATIONS]
        if invalid_durations:
            raise ValueError(
                f"Invalid durations: {invalid_durations}. "
                f"Valid: {Atlas14Grid.AVAILABLE_DURATIONS}"
            )

        # Validate return periods
        invalid_rps = [rp for rp in return_periods
                      if rp not in Atlas14Grid.AVAILABLE_RETURN_PERIODS]
        if invalid_rps:
            raise ValueError(
                f"Invalid return periods: {invalid_rps}. "
                f"Valid: {Atlas14Grid.AVAILABLE_RETURN_PERIODS}"
            )

        # Apply buffer
        west, south, east, north = bounds
        if buffer_percent > 0:
            width = east - west
            height = north - south
            buffer_x = width * buffer_percent / 100
            buffer_y = height * buffer_percent / 100
            west -= buffer_x
            east += buffer_x
            south -= buffer_y
            north += buffer_y
            bounds = (west, south, east, north)

        # Check bounds within CONUS coverage
        cov_west, cov_south, cov_east, cov_north = Atlas14Grid.COVERAGE_BOUNDS
        if (west < cov_west or east > cov_east or
            south < cov_south or north > cov_north):
            logger.warning(
                f"Bounds extend outside CONUS coverage. "
                f"Requested: {bounds}, Coverage: {Atlas14Grid.COVERAGE_BOUNDS}"
            )

        # Get spatial indices
        lat_indices, lon_indices = Atlas14Grid._get_spatial_indices(bounds)

        lat_slice = slice(lat_indices[0], lat_indices[-1] + 1)
        lon_slice = slice(lon_indices[0], lon_indices[-1] + 1)

        logger.info(
            f"Extracting Atlas 14 data for bounds ({west:.4f}, {south:.4f}, "
            f"{east:.4f}, {north:.4f}): "
            f"lat[{lat_indices[0]}:{lat_indices[-1]+1}], "
            f"lon[{lon_indices[0]}:{lon_indices[-1]+1}]"
        )

        # Build result dictionary
        result = {
            'bounds': bounds,
            'durations': durations,
            'return_periods': return_periods,
            'units': 'inches'
        }

        # Load coordinates for subset
        lat, lon, ari = Atlas14Grid._load_coordinates()
        result['lat'] = lat[lat_slice]
        result['lon'] = lon[lon_slice]
        result['ari'] = ari

        # Load data for each duration
        with Atlas14Grid._get_remote_file() as hf:
            for duration in durations:
                varname = Atlas14Grid._duration_to_varname(duration)

                if varname not in hf:
                    logger.warning(f"Variable {varname} not found in NetCDF")
                    continue

                # Read subset (HTTP range request)
                raw_data = hf[varname][lat_slice, lon_slice, :]

                # Apply scale factor and handle nodata
                data = raw_data.astype(np.float32) * Atlas14Grid.SCALE_FACTOR
                data[raw_data == Atlas14Grid.NODATA_VALUE] = np.nan

                result[f'pfe_{duration}hr'] = data

                logger.debug(
                    f"Loaded {varname}: shape={data.shape}, "
                    f"range=[{np.nanmin(data):.2f}, {np.nanmax(data):.2f}] inches"
                )

        # Log data transfer efficiency
        subset_size = len(result['lat']) * len(result['lon']) * len(durations) * 9 * 2
        full_size = 3121 * 7081 * len(durations) * 9 * 2
        reduction = (1 - subset_size / full_size) * 100
        logger.info(
            f"Data transfer: {subset_size/1024:.1f} KB "
            f"(vs {full_size/1024/1024:.1f} MB full grid, "
            f"{reduction:.1f}% reduction)"
        )

        return result

    @staticmethod
    @log_call
    def get_pfe_from_project(
        geom_hdf: Union[str, Path],
        extent_source: Literal["2d_flow_area", "project_extent"] = "2d_flow_area",
        mesh_area_names: Optional[List[str]] = None,
        durations: Optional[List[int]] = None,
        return_periods: Optional[List[int]] = None,
        buffer_percent: float = 10.0,
        ras_object: Optional['RasPrj'] = None
    ) -> Dict[str, np.ndarray]:
        """
        Get precipitation frequency estimates using HEC-RAS project extent.

        Automatically extracts the project extent from a HEC-RAS geometry HDF
        file and downloads Atlas 14 data for that area.

        Args:
            geom_hdf: Path to HEC-RAS geometry HDF file (e.g., "Project.g01.hdf")
            extent_source: Source for extent extraction:
                - "2d_flow_area": Use 2D flow area perimeters (recommended for
                  rain-on-grid models)
                - "project_extent": Use full project extent including 1D elements
            mesh_area_names: Optional list of specific 2D area names to include.
                            If None, uses all 2D areas.
            durations: List of durations in hours. If None, uses [24].
            return_periods: List of return periods in years. If None, uses [100].
            buffer_percent: Buffer to add around extent as percentage (default 10%)
            ras_object: Optional RasPrj object for multi-project workflows

        Returns:
            Dictionary containing precipitation frequency data (same format as
            get_pfe_for_bounds, plus 'extent_source' and 'mesh_areas' keys)

        Example:
            >>> pfe = Atlas14Grid.get_pfe_from_project(
            ...     geom_hdf="MyProject.g01.hdf",
            ...     extent_source="2d_flow_area",
            ...     durations=[6, 12, 24],
            ...     return_periods=[10, 25, 50, 100],
            ...     buffer_percent=10.0
            ... )
        """
        from ..hdf import HdfProject, HdfMesh

        geom_hdf = Path(geom_hdf)

        if not geom_hdf.exists():
            raise FileNotFoundError(f"Geometry HDF file not found: {geom_hdf}")

        logger.info(f"Extracting extent from {geom_hdf} using {extent_source}")

        if extent_source == "2d_flow_area":
            # Get 2D flow area perimeters
            mesh_areas = HdfMesh.get_mesh_areas(geom_hdf)

            if mesh_areas.empty:
                logger.warning(
                    "No 2D flow areas found, falling back to project_extent"
                )
                extent_source = "project_extent"
            else:
                # Filter to specific areas if requested
                if mesh_area_names:
                    mesh_areas = mesh_areas[
                        mesh_areas['mesh_name'].isin(mesh_area_names)
                    ]
                    if mesh_areas.empty:
                        raise ValueError(
                            f"No matching 2D areas found for: {mesh_area_names}"
                        )

                # Transform to WGS84 and get bounds
                if mesh_areas.crs is not None:
                    mesh_areas_wgs84 = mesh_areas.to_crs("EPSG:4326")
                else:
                    logger.warning("No CRS defined for mesh areas")
                    mesh_areas_wgs84 = mesh_areas

                bounds = mesh_areas_wgs84.total_bounds
                west, south, east, north = bounds

                logger.info(
                    f"2D flow area bounds: W={west:.4f}, S={south:.4f}, "
                    f"E={east:.4f}, N={north:.4f}"
                )

        if extent_source == "project_extent":
            # Use project-level extent
            west, south, east, north = HdfProject.get_project_bounds_latlon(
                geom_hdf,
                buffer_percent=0.0,  # We'll apply buffer in get_pfe_for_bounds
                include_1d=True,
                include_2d=True,
                include_storage=True
            )
            mesh_areas = None

        bounds = (west, south, east, north)

        # Get PFE data
        result = Atlas14Grid.get_pfe_for_bounds(
            bounds=bounds,
            durations=durations,
            return_periods=return_periods,
            buffer_percent=buffer_percent
        )

        # Add metadata
        result['extent_source'] = extent_source
        result['geom_hdf'] = str(geom_hdf)
        if mesh_areas is not None:
            result['mesh_area_names'] = mesh_areas['mesh_name'].tolist()

        return result

    @staticmethod
    @log_call
    def get_point_pfe(
        lat: float,
        lon: float,
        durations: Optional[List[int]] = None,
        return_periods: Optional[List[int]] = None
    ) -> pd.DataFrame:
        """
        Get precipitation frequency estimates for a single point.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            durations: List of durations in hours. If None, uses all available.
            return_periods: List of return periods in years. If None, uses all.

        Returns:
            DataFrame with columns: duration_hr, return_period_yr, depth_inches

        Example:
            >>> df = Atlas14Grid.get_point_pfe(29.76, -95.37)
            >>> print(df[df['return_period_yr'] == 100])
        """
        if durations is None:
            durations = Atlas14Grid.AVAILABLE_DURATIONS
        if return_periods is None:
            return_periods = Atlas14Grid.AVAILABLE_RETURN_PERIODS

        # Load coordinates
        lat_arr, lon_arr, ari = Atlas14Grid._load_coordinates()

        # Find nearest grid point
        lat_idx = np.argmin(np.abs(lat_arr - lat))
        lon_idx = np.argmin(np.abs(lon_arr - lon))

        actual_lat = lat_arr[lat_idx]
        actual_lon = lon_arr[lon_idx]

        logger.info(
            f"Point ({lat:.4f}, {lon:.4f}) -> "
            f"nearest grid ({actual_lat:.4f}, {actual_lon:.4f})"
        )

        results = []

        with Atlas14Grid._get_remote_file() as hf:
            for duration in durations:
                varname = Atlas14Grid._duration_to_varname(duration)

                if varname not in hf:
                    continue

                # Read single point
                raw_values = hf[varname][lat_idx, lon_idx, :]

                for rp in return_periods:
                    ari_idx = np.argmin(np.abs(ari - rp))
                    raw_val = raw_values[ari_idx]

                    if raw_val == Atlas14Grid.NODATA_VALUE:
                        depth = np.nan
                    else:
                        depth = raw_val * Atlas14Grid.SCALE_FACTOR

                    results.append({
                        'lat': actual_lat,
                        'lon': actual_lon,
                        'duration_hr': duration,
                        'return_period_yr': int(ari[ari_idx]),
                        'depth_inches': depth
                    })

        return pd.DataFrame(results)

    @staticmethod
    def is_available() -> bool:
        """
        Check if Atlas14Grid remote access is available.

        Returns:
            True if fsspec and h5py are installed and NOAA server is reachable
        """
        if not REMOTE_ACCESS_AVAILABLE:
            return False

        try:
            # Quick connectivity check
            import requests
            resp = requests.head(Atlas14Grid.CONUS_URL, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def clear_cache() -> None:
        """Clear cached coordinate arrays to free memory."""
        Atlas14Grid._lat_cache = None
        Atlas14Grid._lon_cache = None
        Atlas14Grid._ari_cache = None
        logger.debug("Atlas14Grid coordinate cache cleared")
