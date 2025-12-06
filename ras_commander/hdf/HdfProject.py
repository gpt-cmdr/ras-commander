"""
HdfProject - Project-level geometry extraction from HEC-RAS HDF files.

Provides methods to extract combined project extents from all model elements
(1D rivers, cross sections, 2D areas, storage areas) for use in data downloads
such as precipitation and terrain data.

List of Functions:
-----------------
get_project_extent()
    Calculate combined project extent from all model elements with buffering
get_project_bounds_latlon()
    Get project bounds in WGS84 lat/lon coordinates
get_project_crs()
    Get the coordinate reference system from HDF file

Example Usage:
    >>> from ras_commander import HdfProject
    >>>
    >>> # Get project extent with 50% buffer for precipitation download
    >>> extent_gdf, bounds = HdfProject.get_project_extent(
    ...     "project.g01.hdf",
    ...     buffer_percent=50.0
    ... )
    >>> print(f"Buffered bounds: {bounds}")
    >>>
    >>> # Get bounds in lat/lon for AORC data query
    >>> west, south, east, north = HdfProject.get_project_bounds_latlon(
    ...     "project.g01.hdf",
    ...     buffer_percent=50.0
    ... )
"""

from pathlib import Path
from typing import Tuple, Optional, Union, List, TYPE_CHECKING
import logging

from .HdfBase import HdfBase
from .HdfMesh import HdfMesh
from .HdfXsec import HdfXsec
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

logger = get_logger(__name__)


class HdfProject:
    """
    Extract project-level geometry and metadata from HEC-RAS HDF files.

    This class provides methods to calculate combined project extents from
    all model elements (2D areas, cross sections, river centerlines, storage areas)
    with configurable buffering for precipitation and terrain data downloads.

    All methods are static and designed to work with HEC-RAS geometry HDF files.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_project_extent(
        hdf_path: Path,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        buffer_percent: float = 50.0,
        buffer_x_percent: Optional[float] = None,
        buffer_y_percent: Optional[float] = None
    ) -> Tuple['GeoDataFrame', Tuple[float, float, float, float]]:
        """
        Calculate combined project extent from all model elements.

        Extracts geometries from 2D flow areas, cross sections, river centerlines,
        and storage areas, combines them into a single extent, and applies buffering.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        include_1d : bool, default True
            Include 1D river centerlines and cross sections
        include_2d : bool, default True
            Include 2D flow area perimeters
        include_storage : bool, default True
            Include storage area extents (if stored in HDF)
        buffer_percent : float, default 50.0
            Default buffer percentage applied to all directions.
            For precipitation data, 50% is recommended to capture
            upstream contributing areas.
        buffer_x_percent : float, optional
            Override buffer for X axis. If None, uses buffer_percent.
        buffer_y_percent : float, optional
            Override buffer for Y axis. If None, uses buffer_percent.

        Returns
        -------
        Tuple[GeoDataFrame, Tuple[float, float, float, float]]
            - GeoDataFrame with combined geometry envelope and project CRS
            - Buffered bounding box (minx, miny, maxx, maxy) in project CRS

        Examples
        --------
        >>> extent_gdf, bounds = HdfProject.get_project_extent(
        ...     "BaldEagle.g01.hdf",
        ...     buffer_percent=50.0
        ... )
        >>> print(f"Project extent: {bounds}")
        >>> print(f"CRS: {extent_gdf.crs}")
        """
        # Lazy imports
        from geopandas import GeoDataFrame
        from shapely.geometry import box
        from shapely.ops import unary_union
        import pandas as pd

        geometries = []
        crs = None

        # Get 2D flow area perimeters
        if include_2d:
            try:
                mesh_areas = HdfMesh.get_mesh_areas(hdf_path)
                if not mesh_areas.empty:
                    geometries.extend(mesh_areas.geometry.tolist())
                    if crs is None:
                        crs = mesh_areas.crs
                    logger.info(f"Found {len(mesh_areas)} 2D flow areas")
            except Exception as e:
                logger.debug(f"No 2D areas found or error: {e}")

        # Get 1D cross sections and river centerlines
        if include_1d:
            try:
                cross_sections = HdfXsec.get_cross_sections(hdf_path)
                if not cross_sections.empty:
                    geometries.extend(cross_sections.geometry.tolist())
                    if crs is None:
                        crs = cross_sections.crs
                    logger.info(f"Found {len(cross_sections)} cross sections")
            except Exception as e:
                logger.debug(f"No cross sections found or error: {e}")

            try:
                centerlines = HdfXsec.get_river_centerlines(hdf_path)
                if not centerlines.empty:
                    geometries.extend(centerlines.geometry.tolist())
                    if crs is None:
                        crs = centerlines.crs
                    logger.info(f"Found {len(centerlines)} river centerlines")
            except Exception as e:
                logger.debug(f"No river centerlines found or error: {e}")

        # Get CRS from HDF if still None
        if crs is None:
            crs = HdfBase.get_projection(hdf_path)
            logger.debug(f"Got CRS from HDF: {crs}")

        # Handle empty geometries
        if not geometries:
            logger.warning("No geometries found in HDF file")
            empty_gdf = GeoDataFrame(geometry=[], crs=crs)
            return empty_gdf, (0.0, 0.0, 0.0, 0.0)

        # Combine all geometries and get envelope
        combined = unary_union(geometries)
        minx, miny, maxx, maxy = combined.bounds

        # Calculate buffer
        x_buffer = buffer_x_percent if buffer_x_percent is not None else buffer_percent
        y_buffer = buffer_y_percent if buffer_y_percent is not None else buffer_percent

        width = maxx - minx
        height = maxy - miny

        # Handle edge cases where width or height is 0
        if width == 0:
            width = height if height > 0 else 1000  # Default 1km
        if height == 0:
            height = width if width > 0 else 1000

        x_expansion = (width * x_buffer / 100) / 2
        y_expansion = (height * y_buffer / 100) / 2

        buffered_minx = minx - x_expansion
        buffered_miny = miny - y_expansion
        buffered_maxx = maxx + x_expansion
        buffered_maxy = maxy + y_expansion

        logger.info(f"Original extent: ({minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f})")
        logger.info(f"Buffered extent ({x_buffer}% x, {y_buffer}% y): "
                   f"({buffered_minx:.2f}, {buffered_miny:.2f}, "
                   f"{buffered_maxx:.2f}, {buffered_maxy:.2f})")

        # Create buffered polygon
        buffered_polygon = box(buffered_minx, buffered_miny,
                               buffered_maxx, buffered_maxy)

        extent_gdf = GeoDataFrame(
            {'description': ['Project Extent (Buffered)']},
            geometry=[buffered_polygon],
            crs=crs
        )

        return extent_gdf, (buffered_minx, buffered_miny, buffered_maxx, buffered_maxy)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_project_bounds_latlon(
        hdf_path: Path,
        buffer_percent: float = 50.0,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True
    ) -> Tuple[float, float, float, float]:
        """
        Get project bounds in WGS84 lat/lon coordinates.

        Calculates project extent and transforms to WGS84 (EPSG:4326) for use
        with web services like AORC that expect lat/lon coordinates.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS geometry HDF file
        buffer_percent : float, default 50.0
            Buffer percentage to apply to extent
        include_1d : bool, default True
            Include 1D elements
        include_2d : bool, default True
            Include 2D elements
        include_storage : bool, default True
            Include storage areas

        Returns
        -------
        Tuple[float, float, float, float]
            (west, south, east, north) in decimal degrees (WGS84)

        Examples
        --------
        >>> west, south, east, north = HdfProject.get_project_bounds_latlon(
        ...     "BaldEagle.g01.hdf",
        ...     buffer_percent=50.0
        ... )
        >>> print(f"Lat/Lon bounds: W={west}, S={south}, E={east}, N={north}")
        """
        extent_gdf, _ = HdfProject.get_project_extent(
            hdf_path,
            include_1d=include_1d,
            include_2d=include_2d,
            include_storage=include_storage,
            buffer_percent=buffer_percent
        )

        if extent_gdf.empty:
            logger.warning("Empty extent, returning zeros")
            return (0.0, 0.0, 0.0, 0.0)

        # Transform to WGS84
        if extent_gdf.crs is None:
            logger.warning("No CRS defined, assuming WGS84")
            extent_wgs84 = extent_gdf
        else:
            extent_wgs84 = extent_gdf.to_crs("EPSG:4326")

        bounds = extent_wgs84.total_bounds
        west, south, east, north = bounds

        logger.info(f"WGS84 bounds: W={west:.6f}, S={south:.6f}, E={east:.6f}, N={north:.6f}")

        return (west, south, east, north)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_project_crs(hdf_path: Path) -> Optional[str]:
        """
        Get the coordinate reference system from HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS geometry HDF file

        Returns
        -------
        str or None
            CRS as WKT string, or None if not defined

        Examples
        --------
        >>> crs = HdfProject.get_project_crs("BaldEagle.g01.hdf")
        >>> print(f"Project CRS: {crs}")
        """
        return HdfBase.get_projection(hdf_path)

    @staticmethod
    @log_call
    def export_extent_geojson(
        hdf_path: Union[str, Path],
        output_path: Union[str, Path],
        buffer_percent: float = 50.0
    ) -> Path:
        """
        Export project extent to GeoJSON file.

        Parameters
        ----------
        hdf_path : str or Path
            Path to HEC-RAS geometry HDF file
        output_path : str or Path
            Path for output GeoJSON file
        buffer_percent : float, default 50.0
            Buffer percentage to apply

        Returns
        -------
        Path
            Path to created GeoJSON file

        Examples
        --------
        >>> path = HdfProject.export_extent_geojson(
        ...     "BaldEagle.g01.hdf",
        ...     "project_extent.geojson",
        ...     buffer_percent=50.0
        ... )
        """
        hdf_path = Path(hdf_path)
        output_path = Path(output_path)

        extent_gdf, bounds = HdfProject.get_project_extent(
            hdf_path,
            buffer_percent=buffer_percent
        )

        # Convert to WGS84 for GeoJSON
        if extent_gdf.crs is not None and str(extent_gdf.crs) != "EPSG:4326":
            extent_gdf = extent_gdf.to_crs("EPSG:4326")

        extent_gdf.to_file(output_path, driver="GeoJSON")
        logger.info(f"Exported project extent to: {output_path}")

        return output_path
