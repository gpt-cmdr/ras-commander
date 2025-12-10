"""
Gauge-to-model location matching for HEC-RAS models.

This module provides functions to match USGS gauge locations (in WGS84 lat/lon)
to model elements (cross sections, 2D flow areas) by transforming coordinates
and finding nearest neighbors.

Functions:
- transform_gauge_coords() - Convert WGS84 to project CRS
- match_gauge_to_cross_section() - Find nearest cross section to gauge
- match_gauge_to_2d_area() - Find 2D flow area containing gauge
- auto_match_gauges() - Match multiple gauges to model locations
"""

from pathlib import Path
from typing import Union, Dict, Optional, Any, TYPE_CHECKING
import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from ..hdf import HdfXsec, HdfMesh, HdfBase

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

logger = get_logger(__name__)


class GaugeMatchingError(Exception):
    """Exception raised for errors in gauge matching operations."""
    pass


class GaugeMatcher:
    """
    Static class for matching USGS gauge locations to HEC-RAS model elements.

    All methods are static and designed to be used without instantiation.
    Handles coordinate transformations and spatial queries to find nearest
    model elements (cross sections, 2D areas) to gauge locations.
    """

    @staticmethod
    @log_call
    def transform_gauge_coords(
        lon: float,
        lat: float,
        target_crs: str
    ) -> tuple[float, float]:
        """
        Transform gauge coordinates from WGS84 to project coordinate system.

        USGS gauge locations are provided in WGS84 (EPSG:4326) latitude/longitude.
        This function transforms them to the model's projected coordinate system
        (typically State Plane or UTM).

        Parameters
        ----------
        lon : float
            Longitude in WGS84 (decimal degrees, negative for western hemisphere)
        lat : float
            Latitude in WGS84 (decimal degrees)
        target_crs : str
            Target coordinate reference system (e.g., 'EPSG:6556', 'EPSG:32617')

        Returns
        -------
        tuple[float, float]
            Transformed coordinates (x, y) in target CRS units (typically meters or feet)

        Raises
        ------
        GaugeMatchingError
            If coordinate transformation fails

        Examples
        --------
        >>> # Transform gauge location to Texas State Plane South Central (feet)
        >>> x, y = GaugeMatcher.transform_gauge_coords(
        ...     lon=-98.5, lat=29.5, target_crs='EPSG:6556'
        ... )
        >>> print(f"X: {x:.2f}, Y: {y:.2f}")
        X: 3043123.45, Y: 13685432.10

        >>> # Transform to UTM Zone 17N (meters)
        >>> x, y = GaugeMatcher.transform_gauge_coords(
        ...     lon=-81.0, lat=35.5, target_crs='EPSG:32617'
        ... )
        """
        try:
            from pyproj import Transformer

            # Create transformer from WGS84 to target CRS
            transformer = Transformer.from_crs(
                "EPSG:4326",  # WGS84
                target_crs,
                always_xy=True  # Use (lon, lat) order instead of (lat, lon)
            )

            # Transform coordinates
            x, y = transformer.transform(lon, lat)

            logger.debug(f"Transformed ({lon:.6f}, {lat:.6f}) WGS84 -> "
                        f"({x:.2f}, {y:.2f}) {target_crs}")

            return x, y

        except Exception as e:
            error_msg = f"Failed to transform coordinates from WGS84 to {target_crs}: {e}"
            logger.error(error_msg)
            raise GaugeMatchingError(error_msg) from e

    @staticmethod
    @log_call
    def match_gauge_to_cross_section(
        gauge_lon: float,
        gauge_lat: float,
        hdf_path: Union[str, Path],
        max_distance_m: float = 1000.0
    ) -> Optional[Dict[str, Any]]:
        """
        Find nearest cross section to gauge location.

        Transforms gauge coordinates to project CRS, extracts all cross sections
        from HDF geometry file, and finds the nearest one using spatial indexing.

        Parameters
        ----------
        gauge_lon : float
            Gauge longitude in WGS84 (decimal degrees)
        gauge_lat : float
            Gauge latitude in WGS84 (decimal degrees)
        hdf_path : str or Path
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        max_distance_m : float, default 1000.0
            Maximum search distance in meters (or project CRS units).
            Matches beyond this distance are rejected.

        Returns
        -------
        dict or None
            Match information if successful, None if no match found within max_distance:
            - 'river' (str): River name
            - 'reach' (str): Reach name
            - 'station' (str): River station
            - 'distance_m' (float): Distance from gauge to cross section (meters or feet)
            - 'match_quality' (str): 'excellent' (<100m), 'good' (<500m),
                                     'fair' (<1000m), 'poor' (>1000m)
            - 'gauge_lon' (float): Original gauge longitude
            - 'gauge_lat' (float): Original gauge latitude
            - 'xs_x' (float): Cross section X coordinate in project CRS
            - 'xs_y' (float): Cross section Y coordinate in project CRS

        Raises
        ------
        GaugeMatchingError
            If HDF file cannot be read or CRS transformation fails

        Examples
        --------
        >>> match = GaugeMatcher.match_gauge_to_cross_section(
        ...     gauge_lon=-98.5,
        ...     gauge_lat=29.5,
        ...     hdf_path='model.g01.hdf',
        ...     max_distance_m=500.0
        ... )
        >>> if match:
        ...     print(f"Matched to {match['river']}, {match['reach']}, "
        ...           f"RS {match['station']} ({match['match_quality']})")
        Matched to Colorado River, Reach 1, RS 12345.67 (good)
        """
        try:
            hdf_path = Path(hdf_path)

            # Get project CRS from HDF file
            crs = HdfBase.get_projection(hdf_path)
            if crs is None:
                raise GaugeMatchingError(f"Could not determine CRS from {hdf_path}")

            logger.info(f"Using project CRS: {crs}")

            # Transform gauge coordinates to project CRS
            gauge_x, gauge_y = GaugeMatcher.transform_gauge_coords(
                gauge_lon, gauge_lat, crs
            )

            # Extract cross sections from HDF
            xs_gdf = HdfXsec.get_cross_sections(hdf_path)
            if xs_gdf.empty:
                logger.warning(f"No cross sections found in {hdf_path}")
                return None

            logger.info(f"Found {len(xs_gdf)} cross sections in model")

            # Calculate centroid of each cross section for distance calculation
            from shapely.geometry import Point
            xs_gdf['centroid'] = xs_gdf.geometry.centroid
            xs_gdf['centroid_x'] = xs_gdf.centroid.x
            xs_gdf['centroid_y'] = xs_gdf.centroid.y

            # Calculate distance from gauge to each cross section centroid
            xs_gdf['distance'] = np.sqrt(
                (xs_gdf['centroid_x'] - gauge_x)**2 +
                (xs_gdf['centroid_y'] - gauge_y)**2
            )

            # Find nearest cross section
            nearest_idx = xs_gdf['distance'].idxmin()
            nearest_xs = xs_gdf.loc[nearest_idx]
            distance = nearest_xs['distance']

            # Check if within max distance
            if distance > max_distance_m:
                logger.warning(
                    f"Nearest cross section is {distance:.1f}m away, "
                    f"exceeds max_distance_m={max_distance_m}"
                )
                return None

            # Classify match quality
            if distance < 100:
                quality = 'excellent'
            elif distance < 500:
                quality = 'good'
            elif distance < 1000:
                quality = 'fair'
            else:
                quality = 'poor'

            # Build match result
            match_info = {
                'river': str(nearest_xs['River']),
                'reach': str(nearest_xs['Reach']),
                'station': str(nearest_xs['RS']),
                'distance_m': float(distance),
                'match_quality': quality,
                'gauge_lon': float(gauge_lon),
                'gauge_lat': float(gauge_lat),
                'xs_x': float(nearest_xs['centroid_x']),
                'xs_y': float(nearest_xs['centroid_y'])
            }

            logger.info(
                f"Matched gauge ({gauge_lon:.6f}, {gauge_lat:.6f}) to XS "
                f"{match_info['river']}, {match_info['reach']}, RS {match_info['station']} "
                f"at {distance:.1f}m ({quality})"
            )

            return match_info

        except Exception as e:
            error_msg = f"Failed to match gauge to cross section: {e}"
            logger.error(error_msg)
            raise GaugeMatchingError(error_msg) from e

    @staticmethod
    @log_call
    def match_gauge_to_2d_area(
        gauge_lon: float,
        gauge_lat: float,
        hdf_path: Union[str, Path]
    ) -> Optional[Dict[str, Any]]:
        """
        Find 2D flow area containing gauge location.

        Transforms gauge coordinates to project CRS and checks if the point
        falls within any 2D flow area perimeter polygon.

        Parameters
        ----------
        gauge_lon : float
            Gauge longitude in WGS84 (decimal degrees)
        gauge_lat : float
            Gauge latitude in WGS84 (decimal degrees)
        hdf_path : str or Path
            Path to HEC-RAS geometry HDF file (.g##.hdf)

        Returns
        -------
        dict or None
            Match information if gauge is within a 2D area, None otherwise:
            - 'area_name' (str): 2D flow area name
            - 'area_type' (str): 'mesh' (currently only mesh areas supported)
            - 'contains_gauge' (bool): True if gauge is within area
            - 'gauge_lon' (float): Original gauge longitude
            - 'gauge_lat' (float): Original gauge latitude
            - 'gauge_x' (float): Gauge X coordinate in project CRS
            - 'gauge_y' (float): Gauge Y coordinate in project CRS

        Raises
        ------
        GaugeMatchingError
            If HDF file cannot be read or CRS transformation fails

        Examples
        --------
        >>> match = GaugeMatcher.match_gauge_to_2d_area(
        ...     gauge_lon=-98.5,
        ...     gauge_lat=29.5,
        ...     hdf_path='model.g01.hdf'
        ... )
        >>> if match:
        ...     print(f"Gauge is within 2D area: {match['area_name']}")
        Gauge is within 2D area: Detention Basin
        """
        try:
            hdf_path = Path(hdf_path)

            # Get project CRS from HDF file
            crs = HdfBase.get_projection(hdf_path)
            if crs is None:
                raise GaugeMatchingError(f"Could not determine CRS from {hdf_path}")

            # Transform gauge coordinates to project CRS
            gauge_x, gauge_y = GaugeMatcher.transform_gauge_coords(
                gauge_lon, gauge_lat, crs
            )

            # Create gauge point
            from shapely.geometry import Point
            gauge_point = Point(gauge_x, gauge_y)

            # Extract 2D flow areas from HDF
            mesh_gdf = HdfMesh.get_mesh_areas(hdf_path)
            if mesh_gdf.empty:
                logger.info(f"No 2D flow areas found in {hdf_path}")
                return None

            logger.info(f"Found {len(mesh_gdf)} 2D flow areas in model")

            # Check which area contains the gauge point
            for idx, row in mesh_gdf.iterrows():
                if row.geometry.contains(gauge_point):
                    match_info = {
                        'area_name': str(row['mesh_name']),
                        'area_type': 'mesh',
                        'contains_gauge': True,
                        'gauge_lon': float(gauge_lon),
                        'gauge_lat': float(gauge_lat),
                        'gauge_x': float(gauge_x),
                        'gauge_y': float(gauge_y)
                    }

                    logger.info(
                        f"Gauge ({gauge_lon:.6f}, {gauge_lat:.6f}) is within "
                        f"2D area '{match_info['area_name']}'"
                    )

                    return match_info

            # No containing area found
            logger.info(
                f"Gauge ({gauge_lon:.6f}, {gauge_lat:.6f}) is not within "
                f"any 2D flow area"
            )
            return None

        except Exception as e:
            error_msg = f"Failed to match gauge to 2D area: {e}"
            logger.error(error_msg)
            raise GaugeMatchingError(error_msg) from e

    @staticmethod
    @log_call
    def auto_match_gauges(
        gauges_gdf: 'GeoDataFrame',
        hdf_path: Union[str, Path],
        max_distance_m: float = 1000.0
    ) -> pd.DataFrame:
        """
        Automatically match multiple gauges to model locations.

        Takes a GeoDataFrame of gauges (typically from find_gauges_in_project())
        and attempts to match each to the nearest cross section. Also checks
        if gauges are within 2D flow areas.

        Parameters
        ----------
        gauges_gdf : GeoDataFrame
            GeoDataFrame with gauge information. Must contain 'dec_long_va' and
            'dec_lat_va' columns (standard USGS field names).
        hdf_path : str or Path
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        max_distance_m : float, default 1000.0
            Maximum search distance for cross section matching (meters or feet)

        Returns
        -------
        pd.DataFrame
            DataFrame with original gauge info plus matched model locations:
            - All original columns from gauges_gdf
            - 'matched_river' (str): River name (if matched to XS)
            - 'matched_reach' (str): Reach name (if matched to XS)
            - 'matched_station' (str): River station (if matched to XS)
            - 'match_distance_m' (float): Distance to nearest XS
            - 'match_quality' (str): Match quality classification
            - 'in_2d_area' (bool): True if within a 2D flow area
            - '2d_area_name' (str): 2D area name (if applicable)

        Raises
        ------
        GaugeMatchingError
            If gauges_gdf is invalid or required columns are missing

        Examples
        --------
        >>> from ras_commander.usgs.spatial import find_gauges_in_project
        >>>
        >>> # Find gauges in project area
        >>> gauges_gdf = find_gauges_in_project('model.g01.hdf')
        >>>
        >>> # Match all gauges to model locations
        >>> matches_df = GaugeMatcher.auto_match_gauges(
        ...     gauges_gdf, 'model.g01.hdf', max_distance_m=500
        ... )
        >>>
        >>> # Display matched gauges
        >>> print(matches_df[['station_nm', 'matched_river', 'matched_station',
        ...                    'match_quality']])
        """
        try:
            # Validate input
            if gauges_gdf.empty:
                logger.warning("Empty GeoDataFrame provided, returning empty results")
                return pd.DataFrame()

            required_cols = ['dec_long_va', 'dec_lat_va']
            missing_cols = [col for col in required_cols if col not in gauges_gdf.columns]
            if missing_cols:
                raise GaugeMatchingError(
                    f"Missing required columns in gauges_gdf: {missing_cols}"
                )

            logger.info(f"Matching {len(gauges_gdf)} gauges to model locations")

            # Initialize result columns
            results = []

            # Match each gauge
            for idx, gauge in gauges_gdf.iterrows():
                gauge_dict = gauge.to_dict()

                lon = gauge['dec_long_va']
                lat = gauge['dec_lat_va']

                # Try cross section matching
                xs_match = GaugeMatcher.match_gauge_to_cross_section(
                    lon, lat, hdf_path, max_distance_m
                )

                if xs_match:
                    gauge_dict['matched_river'] = xs_match['river']
                    gauge_dict['matched_reach'] = xs_match['reach']
                    gauge_dict['matched_station'] = xs_match['station']
                    gauge_dict['match_distance_m'] = xs_match['distance_m']
                    gauge_dict['match_quality'] = xs_match['match_quality']
                else:
                    gauge_dict['matched_river'] = None
                    gauge_dict['matched_reach'] = None
                    gauge_dict['matched_station'] = None
                    gauge_dict['match_distance_m'] = None
                    gauge_dict['match_quality'] = 'no_match'

                # Try 2D area matching
                area_match = GaugeMatcher.match_gauge_to_2d_area(lon, lat, hdf_path)

                if area_match:
                    gauge_dict['in_2d_area'] = True
                    gauge_dict['2d_area_name'] = area_match['area_name']
                else:
                    gauge_dict['in_2d_area'] = False
                    gauge_dict['2d_area_name'] = None

                results.append(gauge_dict)

            # Create results DataFrame
            results_df = pd.DataFrame(results)

            # Summary statistics
            n_matched = (results_df['match_quality'] != 'no_match').sum()
            n_in_2d = results_df['in_2d_area'].sum()

            logger.info(
                f"Matching complete: {n_matched}/{len(results_df)} gauges matched to XS, "
                f"{n_in_2d} within 2D areas"
            )

            # Quality breakdown
            if n_matched > 0:
                quality_counts = results_df[
                    results_df['match_quality'] != 'no_match'
                ]['match_quality'].value_counts()
                logger.info(f"Match quality distribution: {quality_counts.to_dict()}")

            return results_df

        except Exception as e:
            error_msg = f"Failed to auto-match gauges: {e}"
            logger.error(error_msg)
            raise GaugeMatchingError(error_msg) from e


# Convenience functions for backward compatibility
def transform_gauge_coords(lon: float, lat: float, target_crs: str) -> tuple[float, float]:
    """Convenience wrapper for GaugeMatcher.transform_gauge_coords()."""
    return GaugeMatcher.transform_gauge_coords(lon, lat, target_crs)


def match_gauge_to_cross_section(
    gauge_lon: float,
    gauge_lat: float,
    hdf_path: Union[str, Path],
    max_distance_m: float = 1000.0
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper for GaugeMatcher.match_gauge_to_cross_section()."""
    return GaugeMatcher.match_gauge_to_cross_section(
        gauge_lon, gauge_lat, hdf_path, max_distance_m
    )


def match_gauge_to_2d_area(
    gauge_lon: float,
    gauge_lat: float,
    hdf_path: Union[str, Path]
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper for GaugeMatcher.match_gauge_to_2d_area()."""
    return GaugeMatcher.match_gauge_to_2d_area(gauge_lon, gauge_lat, hdf_path)


def auto_match_gauges(
    gauges_gdf: 'GeoDataFrame',
    hdf_path: Union[str, Path],
    max_distance_m: float = 1000.0
) -> pd.DataFrame:
    """Convenience wrapper for GaugeMatcher.auto_match_gauges()."""
    return GaugeMatcher.auto_match_gauges(gauges_gdf, hdf_path, max_distance_m)
