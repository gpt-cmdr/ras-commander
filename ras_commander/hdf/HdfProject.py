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
import h5py

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
    def _has_hdf_paths(
        hdf_path: Path,
        paths: Tuple[str, ...],
        label: str,
    ) -> bool:
        """Return True when all required HDF paths exist for an optional probe."""
        try:
            with h5py.File(hdf_path, "r") as hdf_file:
                missing = [path for path in paths if path not in hdf_file]
        except Exception as e:
            logger.debug(
                "Could not inspect %s paths in %s: %s",
                label,
                hdf_path,
                e,
                exc_info=True,
            )
            return False

        if missing:
            logger.debug(
                "%s not available in %s; missing HDF path(s): %s",
                label,
                hdf_path.name,
                ", ".join(missing),
            )
            return False

        return True

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
        buffer_y_percent: Optional[float] = None,
        geometry_type: str = "footprint",
    ) -> Tuple['GeoDataFrame', Tuple[float, float, float, float]]:
        """
        Calculate the combined project extent from all model elements.

        With ``geometry_type='footprint'`` (default) this returns the true model
        extent as a (multi)polygon: the union of 2D flow-area perimeters and 1D
        reach footprints (built from river edge lines, see
        ``HdfXsec.get_1d_footprint``). With ``geometry_type='bbox'`` it returns
        the legacy buffered bounding box.

        In both modes the returned ``bounds`` tuple is the (optionally buffered)
        bounding box of the geometry, so downstream callers that only use the
        bounds (lat/lon conversion, data downloads) are unaffected.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS geometry HDF file (.g##.hdf)
        include_1d : bool, default True
            Include 1D river reach footprints (footprint mode) or 1D cross
            sections and river centerlines (bbox mode). Set include_2d=False to
            get the 1D-only extent.
        include_2d : bool, default True
            Include 2D flow area perimeters. Set include_1d=False to get the
            2D-only extent.
        include_storage : bool, default True
            Include storage area extents (if stored in HDF).
        buffer_percent : float, default 50.0
            Buffer percentage. In bbox mode it expands the bounding box on each
            axis (recommended 50% for precipitation to capture contributing
            areas). In footprint mode it buffers the footprint polygon outward by
            an equivalent distance. Pass ``buffer_percent=0`` for the raw,
            unbuffered footprint.
        buffer_x_percent : float, optional
            Override buffer for X axis (bbox mode). If None, uses buffer_percent.
        buffer_y_percent : float, optional
            Override buffer for Y axis (bbox mode). If None, uses buffer_percent.
        geometry_type : {'footprint', 'bbox'}, default 'footprint'
            'footprint' returns the true extent polygon; 'bbox' returns the
            legacy buffered bounding box.

        Returns
        -------
        Tuple[GeoDataFrame, Tuple[float, float, float, float]]
            - GeoDataFrame with the extent geometry (footprint polygon or box)
              and project CRS
            - Bounding box (minx, miny, maxx, maxy) in project CRS

        Examples
        --------
        >>> # True model footprint (raw, unbuffered)
        >>> gdf, bounds = HdfProject.get_project_extent(
        ...     "BaldEagle.g01.hdf", buffer_percent=0.0
        ... )
        >>> # 2D-only footprint
        >>> gdf_2d, _ = HdfProject.get_project_extent(
        ...     "BaldEagle.g01.hdf", include_1d=False, buffer_percent=0.0
        ... )
        >>> # Legacy buffered bounding box (for precipitation download)
        >>> box_gdf, box_bounds = HdfProject.get_project_extent(
        ...     "BaldEagle.g01.hdf", geometry_type='bbox', buffer_percent=50.0
        ... )
        """
        if geometry_type not in ("footprint", "bbox"):
            raise ValueError(
                f"geometry_type must be 'footprint' or 'bbox', got '{geometry_type}'"
            )

        if geometry_type == "footprint":
            return HdfProject._get_project_footprint(
                hdf_path,
                include_1d=include_1d,
                include_2d=include_2d,
                include_storage=include_storage,
                buffer_percent=buffer_percent,
            )

        # Lazy imports
        from geopandas import GeoDataFrame
        from shapely.geometry import box
        from shapely.ops import unary_union

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
                    logger.debug(f"Found {len(mesh_areas)} 2D flow areas")
            except Exception as e:
                logger.debug(f"No 2D areas found or error: {e}")

        # Get 1D cross sections and river centerlines
        if include_1d:
            cross_section_paths = (
                "/Geometry/Cross Sections/Polyline Info",
                "/Geometry/Cross Sections/Polyline Parts",
                "/Geometry/Cross Sections/Polyline Points",
                "/Geometry/Cross Sections/Station Elevation Info",
                "/Geometry/Cross Sections/Station Elevation Values",
                "/Geometry/Cross Sections/Attributes",
                "/Geometry/Cross Sections/Manning's n Info",
                "/Geometry/Cross Sections/Manning's n Values",
            )
            if HdfProject._has_hdf_paths(
                hdf_path,
                cross_section_paths,
                "Cross-section geometry",
            ):
                try:
                    cross_sections = HdfXsec.get_cross_sections(hdf_path)
                    if not cross_sections.empty:
                        geometries.extend(cross_sections.geometry.tolist())
                        if crs is None:
                            crs = cross_sections.crs
                        logger.debug(f"Found {len(cross_sections)} cross sections")
                except Exception as e:
                    logger.debug(
                        "Could not extract cross sections from %s: %s",
                        hdf_path,
                        e,
                        exc_info=True,
                    )

            river_centerline_paths = ("Geometry/River Centerlines",)
            if HdfProject._has_hdf_paths(
                hdf_path,
                river_centerline_paths,
                "River centerline geometry",
            ):
                try:
                    centerlines = HdfXsec.get_river_centerlines(hdf_path)
                    if not centerlines.empty:
                        geometries.extend(centerlines.geometry.tolist())
                        if crs is None:
                            crs = centerlines.crs
                        logger.debug(f"Found {len(centerlines)} river centerlines")
                except Exception as e:
                    logger.debug(
                        "Could not extract river centerlines from %s: %s",
                        hdf_path,
                        e,
                        exc_info=True,
                    )

        # Get CRS from HDF if still None
        if crs is None:
            crs = HdfBase.get_projection(hdf_path)
            logger.debug(f"Got CRS from HDF: {crs}")

        # Handle empty geometries
        if not geometries:
            logger.warning(
                "No project geometries found in %s; returning empty extent "
                "and zero project-coordinate bounds.",
                hdf_path.name,
            )
            logger.debug(
                "No project geometries found in %s "
                "(include_1d=%s, include_2d=%s, include_storage=%s).",
                hdf_path,
                include_1d,
                include_2d,
                include_storage,
            )
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

        logger.debug(f"Original extent: ({minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f})")
        logger.debug(f"Buffered extent ({x_buffer}% x, {y_buffer}% y): "
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
    def _get_project_footprint(
        hdf_path: Path,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        buffer_percent: float = 0.0,
    ) -> Tuple['GeoDataFrame', Tuple[float, float, float, float]]:
        """
        Build the true model extent as a footprint (multi)polygon.

        Unions 2D flow-area perimeters with 1D reach footprints. Falls back to the
        convex hull of 1D line geometry when reaches cannot be polygonized (e.g.
        a model with no cross-section end points). See ``get_project_extent`` for
        parameter semantics.
        """
        from geopandas import GeoDataFrame
        from shapely.ops import unary_union

        polygons = []
        fallback_lines = []
        crs = None

        # 2D flow area perimeters (already polygons).
        if include_2d:
            try:
                mesh_areas = HdfMesh.get_mesh_areas(hdf_path)
                if not mesh_areas.empty:
                    polygons.extend(mesh_areas.geometry.tolist())
                    if crs is None:
                        crs = mesh_areas.crs
                    logger.debug(f"Footprint: {len(mesh_areas)} 2D flow areas")
            except Exception as e:
                logger.debug(f"No 2D areas found or error: {e}")

        # 1D reach footprints (from river edge lines).
        if include_1d:
            try:
                footprint_1d = HdfXsec.get_1d_footprint(hdf_path, dissolve=False)
                if not footprint_1d.empty:
                    polygons.extend(footprint_1d.geometry.tolist())
                    if crs is None:
                        crs = footprint_1d.crs
                    logger.debug(f"Footprint: {len(footprint_1d)} 1D reach footprints")
            except Exception as e:
                logger.debug(f"No 1D footprint or error: {e}")

            # Keep 1D line geometry for a convex-hull fallback if no polygons form.
            if not polygons:
                for getter in (HdfXsec.get_cross_sections, HdfXsec.get_river_centerlines):
                    try:
                        lines = getter(hdf_path)
                        if lines is not None and not lines.empty:
                            fallback_lines.extend(lines.geometry.tolist())
                            if crs is None:
                                crs = lines.crs
                    except Exception as e:
                        logger.debug(f"1D line fallback getter failed: {e}")

        if crs is None:
            crs = HdfBase.get_projection(hdf_path)

        # Resolve the core footprint geometry.
        if polygons:
            combined = unary_union(polygons)
        elif fallback_lines:
            logger.debug("Footprint: no polygonizable areas; using convex hull of 1D lines")
            combined = unary_union(fallback_lines).convex_hull
        else:
            logger.warning("No geometries found in HDF file")
            empty_gdf = GeoDataFrame(geometry=[], crs=crs)
            return empty_gdf, (0.0, 0.0, 0.0, 0.0)

        if combined.is_empty:
            logger.warning("Combined footprint geometry is empty")
            empty_gdf = GeoDataFrame(geometry=[], crs=crs)
            return empty_gdf, (0.0, 0.0, 0.0, 0.0)

        # Optional isotropic buffer (0 => raw footprint).
        if buffer_percent and buffer_percent > 0:
            minx, miny, maxx, maxy = combined.bounds
            width = maxx - minx
            height = maxy - miny
            reference = min(d for d in (width, height) if d > 0) if (width > 0 or height > 0) else 0.0
            buffer_distance = (buffer_percent / 100.0) * 0.5 * reference
            if buffer_distance > 0:
                combined = combined.buffer(buffer_distance)

        extent_gdf = GeoDataFrame(
            {'description': ['Project Extent (Footprint)']},
            geometry=[combined],
            crs=crs,
        )

        return extent_gdf, tuple(float(v) for v in combined.bounds)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_project_bounds_latlon(
        hdf_path: Path,
        buffer_percent: float = 50.0,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        project_crs: Optional[str] = None
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
        project_crs : str, optional
            Override CRS for projects without embedded projection. Use EPSG codes
            like "EPSG:26918" (UTM Zone 18N) or "EPSG:2271" (PA State Plane North).
            If None, attempts to read CRS from HDF file.

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
        
        >>> # For projects without embedded CRS, specify manually:
        >>> west, south, east, north = HdfProject.get_project_bounds_latlon(
        ...     "BaldEagle.g01.hdf",
        ...     buffer_percent=50.0,
        ...     project_crs="EPSG:26918"  # UTM Zone 18N
        ... )
        """
        # Use the buffered bounding box (download-oriented) to preserve behavior.
        extent_gdf, _ = HdfProject.get_project_extent(
            hdf_path,
            include_1d=include_1d,
            include_2d=include_2d,
            include_storage=include_storage,
            buffer_percent=buffer_percent,
            geometry_type="bbox",
        )

        if extent_gdf.empty:
            logger.debug(
                "Empty project extent for %s; returning zero bounds.",
                hdf_path.name,
            )
            return (0.0, 0.0, 0.0, 0.0)

        # Transform to WGS84
        # Use provided project_crs if extent has no CRS defined
        if extent_gdf.crs is None:
            if project_crs is not None:
                logger.debug(f"No CRS in HDF file, using provided project_crs: {project_crs}")
                extent_gdf = extent_gdf.set_crs(project_crs)
            else:
                bounds = extent_gdf.total_bounds
                west, south, east, north = bounds
                logger.warning(
                    "Project CRS unavailable for %s; returning untransformed "
                    "project-coordinate bounds. Pass project_crs=... to return "
                    "WGS84 bounds.",
                    hdf_path.name,
                )
                logger.debug(
                    "Original project-coordinate bounds for %s: W=%.6f, "
                    "S=%.6f, E=%.6f, N=%.6f",
                    hdf_path,
                    west,
                    south,
                    east,
                    north,
                )
                return (west, south, east, north)
        
        try:
            from pyproj import CRS as PyprojCRS
            # Validate the source CRS can be parsed
            source_crs = PyprojCRS.from_user_input(extent_gdf.crs)
            logger.debug(f"Source CRS: {source_crs.name}")
            
            extent_wgs84 = extent_gdf.to_crs("EPSG:4326")
            bounds = extent_wgs84.total_bounds
            west, south, east, north = bounds
            
            # Validate the transformation actually worked (WGS84 bounds check)
            if not (-180 <= west <= 180 and -180 <= east <= 180 and 
                    -90 <= south <= 90 and -90 <= north <= 90):
                original_bounds = extent_gdf.total_bounds
                logger.error(
                    "CRS transformation failed for %s; returning original "
                    "project-coordinate bounds, not WGS84. Enable DEBUG for "
                    "CRS and bounds.",
                    hdf_path.name,
                )
                logger.debug(
                    "Invalid WGS84 bounds for %s from source CRS %s: "
                    "W=%.6f, S=%.6f, E=%.6f, N=%.6f; original bounds=%s",
                    hdf_path,
                    source_crs.name,
                    west,
                    south,
                    east,
                    north,
                    original_bounds,
                )
                return tuple(original_bounds)
            
            logger.debug(f"WGS84 bounds: W={west:.6f}, S={south:.6f}, E={east:.6f}, N={north:.6f}")
            return (west, south, east, north)
            
        except Exception as e:
            bounds = extent_gdf.total_bounds
            west, south, east, north = bounds
            logger.error(
                "CRS transformation failed for %s; returning original "
                "project-coordinate bounds, not WGS84. Enable DEBUG for CRS "
                "and bounds.",
                hdf_path.name,
            )
            logger.debug(
                "CRS transformation exception for %s: %s; original "
                "project-coordinate bounds W=%.6f, S=%.6f, E=%.6f, N=%.6f",
                hdf_path,
                e,
                west,
                south,
                east,
                north,
                exc_info=True,
            )
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
            CRS as an EPSG string when resolvable, otherwise WKT, or None if
            not defined

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
        logger.info("Exported project extent to %s", output_path.name)
        logger.debug("Exported project extent full path: %s", output_path)

        return output_path
