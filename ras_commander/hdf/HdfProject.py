"""
HdfProject - Project-level geometry extraction from HEC-RAS geometry sources.

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
from typing import Tuple, Optional, Union, TYPE_CHECKING
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

    All methods are static. Extent methods can combine HDF and plain-text geometry.
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
    def get_project_extent(
        hdf_path: Optional[Union[str, Path, h5py.File]] = None,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        buffer_percent: float = 50.0,
        buffer_x_percent: Optional[float] = None,
        buffer_y_percent: Optional[float] = None,
        geometry_type: str = "footprint",
        fill_holes: bool = True,
        *,
        geom_path: Optional[Union[str, Path]] = None,
        fallback_to_plaintext: bool = True,
        ras_object=None,
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
        hdf_path : path-like, optional
            Path to a geometry HDF (``.g##.hdf``), its plain-text geometry
            file (``.g##``), or an existing plan-number input.
        include_1d : bool, default True
            Include 1D river reach footprints (footprint mode) or 1D cross
            sections and river centerlines (bbox mode). Set include_2d=False to
            get the 1D-only extent.
        include_2d : bool, default True
            Include 2D flow area perimeters. Set include_1d=False to get the
            2D-only extent.
        include_storage : bool, default True
            Include storage area extents from HDF or companion text geometry.
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
        fill_holes : bool, default True
            Footprint mode only. Remove interior sliver gaps (holes) from the
            combined 1D + 2D footprint. Unioning 1D reach footprints with 2D
            flow-area perimeters leaves thin interior rings wherever the two
            boundaries overlap without aligning exactly (clearly visible on
            Muncie). Set False to keep those holes. Ignored in 'bbox' mode. Only
            interior rings are dropped; disconnected parts of a genuinely
            multipart model (e.g. separate 2D flow areas) are always preserved.
        geom_path : path-like, optional
            Explicit plain-text geometry path. When omitted, the companion
            ``.g##`` file is inferred from ``hdf_path``. When its compiled HDF
            sibling exists, usable HDF components remain preferred.
        ras_object : RasPrj, optional
            Project context for plan-number, geometry-path, and CRS resolution.
        fallback_to_plaintext : bool, default True
            Use the matching plain-text geometry when requested geometry is
            unavailable in HDF. Set False to require HDF-derived geometry only.

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

        hdf_path, geom_path, ras_object = HdfProject._resolve_geometry_sources(
            hdf_path,
            geom_path=geom_path,
            ras_object=ras_object,
            fallback_to_plaintext=fallback_to_plaintext,
        )
        crs = HdfProject._resolve_extent_crs(hdf_path, ras_object=ras_object)

        if geometry_type == "footprint":
            return HdfProject._get_project_footprint(
                hdf_path,
                geom_path=geom_path,
                crs=crs,
                include_1d=include_1d,
                include_2d=include_2d,
                include_storage=include_storage,
                buffer_percent=buffer_percent,
                fill_holes=fill_holes,
                ras_object=ras_object,
            )

        # Lazy imports
        from geopandas import GeoDataFrame
        from shapely.geometry import box
        from shapely.ops import unary_union

        geometries = []
        found_hdf_1d = False
        found_hdf_2d = False
        found_hdf_storage = False
        used_hdf = False
        used_plaintext = False

        # Get 2D flow area perimeters
        if include_2d and hdf_path is not None:
            try:
                mesh_areas = HdfMesh.get_mesh_areas(hdf_path)
                mesh_polygons = HdfProject._usable_polygons(mesh_areas)
                if mesh_polygons:
                    geometries.extend(mesh_polygons)
                    if crs is None:
                        crs = mesh_areas.crs
                    found_hdf_2d = True
                    used_hdf = True
                    logger.debug(f"Found {len(mesh_polygons)} 2D flow areas")
            except Exception as e:
                logger.debug(f"No 2D areas found or error: {e}")

        if include_storage and hdf_path is not None:
            try:
                storage_areas = HdfProject._get_hdf_storage_polygons(
                    hdf_path,
                    ras_object=ras_object,
                )
                storage_polygons = HdfProject._usable_polygons(storage_areas)
                if storage_polygons:
                    geometries.extend(storage_polygons)
                    found_hdf_storage = True
                    used_hdf = True
                    if crs is None:
                        crs = storage_areas.crs
                    logger.debug(f"Found {len(storage_polygons)} HDF storage areas")
            except Exception as e:
                logger.debug(f"No HDF storage areas found or error: {e}")

        # Get 1D cross sections and river centerlines
        if include_1d and hdf_path is not None:
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
                        found_hdf_1d = True
                        used_hdf = True
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
                        used_hdf = True
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

        if geom_path is not None and (
            (include_storage and not found_hdf_storage)
            or (include_2d and not found_hdf_2d)
        ):
            try:
                text_areas = HdfProject._get_text_area_polygons(
                    geom_path,
                    include_2d=include_2d and not found_hdf_2d,
                    include_storage=include_storage and not found_hdf_storage,
                    crs=crs,
                )
                text_polygons = HdfProject._usable_polygons(text_areas)
                geometries.extend(text_polygons)
                used_plaintext |= bool(text_polygons)
            except Exception as e:
                logger.debug(
                    "Plain-text 2D/storage extent fallback failed for %s: %s",
                    geom_path,
                    e,
                    exc_info=True,
                )

        if include_1d and not found_hdf_1d and geom_path is not None:
            try:
                text_footprint = HdfProject._get_text_1d_footprint(
                    geom_path,
                    crs=crs,
                    ras_object=ras_object,
                )
                if not text_footprint.empty:
                    geometries.extend(text_footprint.geometry.tolist())
                    used_plaintext = True
                    logger.debug("BBox extent: using plain-text 1D footprint fallback")
            except Exception as e:
                logger.debug(
                    "Plain-text 1D extent fallback failed for %s: %s",
                    geom_path,
                    e,
                    exc_info=True,
                )

        # Handle empty geometries
        if not geometries:
            source_name = (hdf_path or geom_path).name
            logger.warning(
                "No project geometries found in %s; returning empty extent "
                "and zero project-coordinate bounds.",
                source_name,
            )
            logger.debug(
                "No project geometries found in %s "
                "(include_1d=%s, include_2d=%s, include_storage=%s).",
                source_name,
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
            {
                'description': ['Project Extent (Buffered)'],
                'source': [HdfProject._extent_source_label(used_hdf, used_plaintext)],
            },
            geometry=[buffered_polygon],
            crs=crs
        )

        if used_plaintext:
            logger.info("Project extent used plain-text geometry: %s", geom_path.name)

        return extent_gdf, (buffered_minx, buffered_miny, buffered_maxx, buffered_maxy)

    @staticmethod
    def _resolve_geometry_sources(
        hdf_path,
        geom_path=None,
        ras_object=None,
        fallback_to_plaintext=True,
    ):
        """Resolve optional HDF and text sources without requiring compiled geometry."""
        from numbers import Number
        import re

        if isinstance(hdf_path, h5py.File):
            hdf_path = Path(hdf_path.filename)

        from ..RasPrj import ras as global_ras

        project_reference = False
        ras_obj = ras_object or global_ras

        def _valid_value(value):
            return value is not None and str(value).strip().lower() not in {
                "", "<na>", "nan", "none",
            }

        def _is_text_geometry(path):
            return re.search(r"\.g\d{2}$", Path(path).name, re.IGNORECASE) is not None

        def _reference_number(value):
            if isinstance(value, Number):
                try:
                    return int(value)
                except (TypeError, ValueError, OverflowError):
                    return None
            if isinstance(value, str):
                raw = value.strip().lower()
                if raw.startswith("p"):
                    raw = raw[1:]
                if raw.isdigit():
                    return int(raw)
            return None

        def _resolve_plan_geometry(value):
            nonlocal project_reference
            number = _reference_number(value)
            if number is None:
                return None, None
            if not 1 <= number <= 99:
                raise ValueError(
                    f"Plan/geometry number must be between 1 and 99, got {number}"
                )

            if hasattr(ras_obj, "check_initialized"):
                try:
                    ras_obj.check_initialized()
                except Exception as exc:
                    raise ValueError(f"RAS object is not initialized: {exc}") from exc

            plan_df = getattr(ras_obj, "plan_df", None)
            if plan_df is None or plan_df.empty or "plan_number" not in plan_df:
                return None, None

            def _normalize_number(value):
                raw = str(value).strip().lstrip("0") or "0"
                return int(raw) if raw.isdigit() else None

            plan_numbers = plan_df["plan_number"].map(_normalize_number)
            matches = plan_df[plan_numbers == number]
            if matches.empty:
                return None, None

            project_reference = True
            row = matches.iloc[0]
            text_path = None
            if _valid_value(row.get("Geom Path")):
                text_path = Path(str(row.get("Geom Path")))
            elif _valid_value(row.get("geometry_number")):
                project_folder = getattr(ras_obj, "project_folder", None)
                project_name = getattr(ras_obj, "project_name", None)
                if project_folder is not None and project_name:
                    geometry_number = str(row.get("geometry_number")).strip()
                    if geometry_number.lower().startswith("g"):
                        geometry_number = geometry_number[1:]
                    if geometry_number.isdigit():
                        geometry_number = geometry_number.zfill(2)
                    text_path = Path(project_folder) / (
                        f"{project_name}.g{geometry_number}"
                    )

            compiled_path = None
            geom_df = getattr(ras_obj, "geom_df", None)
            if text_path is not None and geom_df is not None and not geom_df.empty:
                if "full_path" in geom_df and "hdf_path" in geom_df:
                    match = geom_df[geom_df["full_path"].astype(str) == str(text_path)]
                    if not match.empty and _valid_value(match.iloc[0].get("hdf_path")):
                        candidate = Path(str(match.iloc[0].get("hdf_path")))
                        if candidate.is_file():
                            compiled_path = candidate
            if compiled_path is None and text_path is not None:
                candidate = Path(str(text_path) + ".hdf")
                if candidate.is_file():
                    compiled_path = candidate
            return text_path, compiled_path

        primary = Path(str(hdf_path).strip()) if hdf_path is not None else None
        plan_text = None
        plan_hdf = None
        if primary is not None and not primary.is_file():
            plan_text, plan_hdf = _resolve_plan_geometry(hdf_path)

        resolved_hdf = plan_hdf
        resolved_text = (
            plan_text
            if plan_text is not None
            and plan_text.is_file()
            and _is_text_geometry(plan_text)
            else None
        )
        if primary is not None and primary.is_file():
            if primary.suffix.lower() == ".hdf":
                resolved_hdf = primary
                sibling = primary.with_suffix("")
                if sibling.is_file() and _is_text_geometry(sibling):
                    resolved_text = sibling
            elif _is_text_geometry(primary):
                resolved_text = primary
                sibling = Path(str(primary) + ".hdf")
                if sibling.is_file():
                    resolved_hdf = sibling
        elif primary is not None and primary.suffix.lower() == ".hdf":
            sibling = primary.with_suffix("")
            if sibling.is_file() and _is_text_geometry(sibling):
                resolved_text = sibling

        explicit_text = Path(geom_path) if geom_path is not None else None
        if explicit_text is not None:
            if not _is_text_geometry(explicit_text):
                raise ValueError(
                    f"Plain-text geometry path must end in .g##: {explicit_text}"
                )
            if explicit_text.is_file():
                resolved_text = explicit_text
                sibling = Path(str(explicit_text) + ".hdf")
                if resolved_hdf is None and sibling.is_file():
                    resolved_hdf = sibling
            elif resolved_hdf is None and fallback_to_plaintext:
                raise FileNotFoundError(
                    f"Plain-text geometry file not found: {explicit_text}"
                )
            else:
                logger.debug(
                    "Plain-text geometry fallback is unavailable: %s",
                    explicit_text,
                )

        if not fallback_to_plaintext:
            resolved_text = None
            if resolved_hdf is None:
                requested = hdf_path if hdf_path is not None else geom_path
                raise FileNotFoundError(
                    f"Geometry HDF file not found and plain-text fallback is disabled: "
                    f"{requested}"
                )

        if resolved_hdf is None and resolved_text is None:
            requested = geom_path if geom_path is not None else hdf_path
            raise FileNotFoundError(f"Geometry HDF or text file not found: {requested}")

        resolved_ras = ras_object
        if resolved_ras is None and project_reference:
            resolved_ras = ras_obj

        return resolved_hdf, resolved_text, resolved_ras

    @staticmethod
    def _resolve_extent_crs(hdf_path, ras_object=None):
        """Resolve extent CRS from HDF first, then matching project context."""
        if hdf_path is not None:
            try:
                crs = HdfBase.get_projection(hdf_path)
                if crs is not None:
                    return crs
            except Exception as exc:
                logger.debug("Could not resolve extent CRS from HDF: %s", exc)
        if ras_object is not None:
            return getattr(ras_object, "project_crs", None)
        return None

    @staticmethod
    def _extent_source_label(used_hdf, used_plaintext):
        """Describe which resolved geometry sources contributed to an extent."""
        if used_hdf and used_plaintext:
            return "hdf_and_plaintext"
        if used_plaintext:
            return "plaintext"
        return "hdf"

    @staticmethod
    def _get_text_1d_footprint(geom_path, crs=None, ras_object=None):
        """Read a 1D footprint from a companion plain-text geometry file."""
        from ..geom.GeomParser import GeomParser

        return GeomParser.get_1d_footprint(
            geom_path,
            crs=crs,
            dissolve=False,
            ras_object=ras_object,
        )

    @staticmethod
    def _get_hdf_storage_polygons(hdf_path, ras_object=None):
        """Read storage polygons while keeping HdfStruc's imports lazy."""
        from .HdfStruc import HdfStruc

        return HdfStruc.get_storage_area_polygons(
            hdf_path,
            ras_object=ras_object,
        )

    @staticmethod
    def _get_text_area_polygons(
        geom_path,
        include_2d=True,
        include_storage=True,
        crs=None,
    ):
        """Read selected 2D and storage perimeters from plain-text geometry."""
        from ..geom.GeomStorage import GeomStorage

        areas = GeomStorage.get_storage_area_polygons(geom_path, exclude_2d=False)
        if areas.empty:
            return areas
        selected = areas[
            (areas["is_2d"] & include_2d)
            | (~areas["is_2d"] & include_storage)
        ].copy()
        if crs is not None and selected.crs is None:
            selected = selected.set_crs(crs)
        return selected

    @staticmethod
    def _usable_polygons(frame):
        """Return valid non-empty polygonal geometries from a GeoDataFrame."""
        usable = []
        if frame is None or frame.empty:
            return usable
        for geometry in frame.geometry:
            if geometry is None or geometry.is_empty:
                continue
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            if (
                not geometry.is_empty
                and geometry.geom_type in ("Polygon", "MultiPolygon")
                and geometry.area > 0
            ):
                usable.append(geometry)
        return usable

    @staticmethod
    def _count_holes(geometry) -> int:
        """Count interior rings across a (Multi)Polygon."""
        from shapely.geometry import Polygon, MultiPolygon

        if isinstance(geometry, Polygon):
            return len(geometry.interiors)
        if isinstance(geometry, MultiPolygon):
            return sum(len(p.interiors) for p in geometry.geoms)
        return 0

    @staticmethod
    def _fill_polygon_holes(geometry):
        """Drop interior rings (holes) from a (Multi)Polygon.

        Unioning 1D reach footprints with 2D flow-area perimeters leaves thin
        sliver gaps where the two boundaries overlap without aligning exactly;
        these show up as interior rings. Rebuilding each polygon from its exterior
        ring removes them. Non-polygonal geometry is returned unchanged.
        """
        from shapely.geometry import Polygon, MultiPolygon

        if isinstance(geometry, Polygon):
            return Polygon(geometry.exterior) if geometry.interiors else geometry
        if isinstance(geometry, MultiPolygon):
            filled = [
                Polygon(part.exterior) if part.interiors else part
                for part in geometry.geoms
            ]
            # Re-dissolve so any exterior that grew into a neighbor stays merged.
            from shapely.ops import unary_union
            return unary_union(filled)
        return geometry

    @staticmethod
    def _get_project_footprint(
        hdf_path: Optional[Path],
        geom_path: Optional[Path] = None,
        crs=None,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        buffer_percent: float = 0.0,
        fill_holes: bool = True,
        ras_object=None,
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
        found_hdf_2d = False
        found_hdf_storage = False
        found_1d_polygon = False
        used_hdf = False
        used_plaintext = False

        # 2D flow area perimeters (already polygons).
        if include_2d and hdf_path is not None:
            try:
                mesh_areas = HdfMesh.get_mesh_areas(hdf_path)
                hdf_polygons = HdfProject._usable_polygons(mesh_areas)
                if hdf_polygons:
                    polygons.extend(hdf_polygons)
                    found_hdf_2d = True
                    used_hdf = True
                    if crs is None:
                        crs = mesh_areas.crs
                    logger.debug(f"Footprint: {len(hdf_polygons)} HDF 2D flow areas")
            except Exception as e:
                logger.debug(f"No 2D areas found or error: {e}")

        if include_storage and hdf_path is not None:
            try:
                storage_areas = HdfProject._get_hdf_storage_polygons(
                    hdf_path,
                    ras_object=ras_object,
                )
                storage_polygons = HdfProject._usable_polygons(storage_areas)
                if storage_polygons:
                    polygons.extend(storage_polygons)
                    found_hdf_storage = True
                    used_hdf = True
                    if crs is None:
                        crs = storage_areas.crs
                    logger.debug(
                        f"Footprint: {len(storage_polygons)} HDF storage areas"
                    )
            except Exception as e:
                logger.debug(f"No HDF storage areas found or error: {e}")

        if geom_path is not None and (
            (include_storage and not found_hdf_storage)
            or (include_2d and not found_hdf_2d)
        ):
            try:
                text_areas = HdfProject._get_text_area_polygons(
                    geom_path,
                    include_2d=include_2d and not found_hdf_2d,
                    include_storage=include_storage and not found_hdf_storage,
                    crs=crs,
                )
                text_polygons = HdfProject._usable_polygons(text_areas)
                polygons.extend(text_polygons)
                if text_polygons:
                    used_plaintext = True
                    logger.debug(
                        "Footprint: %s plain-text 2D/storage perimeters",
                        len(text_polygons),
                    )
            except Exception as e:
                logger.debug(
                    "Plain-text 2D/storage footprint fallback failed for %s: %s",
                    geom_path,
                    e,
                    exc_info=True,
                )

        # 1D reach footprints (from river edge lines).
        if include_1d:
            if hdf_path is not None:
                try:
                    footprint_1d = HdfXsec.get_1d_footprint(
                        hdf_path,
                        dissolve=False,
                        ras_object=ras_object,
                    )
                    hdf_polygons = HdfProject._usable_polygons(footprint_1d)
                    if hdf_polygons:
                        polygons.extend(hdf_polygons)
                        found_1d_polygon = True
                        used_hdf = True
                        if crs is None:
                            crs = footprint_1d.crs
                        logger.debug(
                            f"Footprint: {len(hdf_polygons)} HDF 1D reach footprints"
                        )
                except Exception as e:
                    logger.debug(f"No 1D HDF footprint or error: {e}")

            if not found_1d_polygon and geom_path is not None:
                try:
                    text_footprint = HdfProject._get_text_1d_footprint(
                        geom_path,
                        crs=crs,
                        ras_object=ras_object,
                    )
                    text_polygons = HdfProject._usable_polygons(text_footprint)
                    if text_polygons:
                        polygons.extend(text_polygons)
                        found_1d_polygon = True
                        used_plaintext = True
                        if crs is None:
                            crs = text_footprint.crs
                        logger.debug(
                            "Footprint: %s plain-text 1D reach footprints",
                            len(text_polygons),
                        )
                except Exception as e:
                    logger.debug(
                        "Plain-text 1D footprint fallback failed for %s: %s",
                        geom_path,
                        e,
                        exc_info=True,
                    )

            # Keep HDF line geometry for a convex-hull fallback if no 1D polygon forms.
            if not found_1d_polygon and not polygons and hdf_path is not None:
                for getter in (HdfXsec.get_cross_sections, HdfXsec.get_river_centerlines):
                    try:
                        lines = getter(hdf_path)
                        if lines is not None and not lines.empty:
                            fallback_lines.extend(lines.geometry.tolist())
                            used_hdf = True
                            if crs is None:
                                crs = lines.crs
                    except Exception as e:
                        logger.debug(f"1D line fallback getter failed: {e}")

        # Resolve the core footprint geometry.
        if polygons:
            combined = unary_union(polygons)
        elif fallback_lines:
            logger.debug("Footprint: no polygonizable areas; using convex hull of 1D lines")
            combined = unary_union(fallback_lines).convex_hull
        else:
            logger.warning(
                "No geometries found in resolved geometry sources for %s",
                hdf_path or geom_path,
            )
            empty_gdf = GeoDataFrame(geometry=[], crs=crs)
            return empty_gdf, (0.0, 0.0, 0.0, 0.0)

        if combined.is_empty:
            logger.warning("Combined footprint geometry is empty")
            empty_gdf = GeoDataFrame(geometry=[], crs=crs)
            return empty_gdf, (0.0, 0.0, 0.0, 0.0)

        # Remove interior sliver gaps left where 1D and 2D boundaries overlap.
        if fill_holes:
            n_holes_before = HdfProject._count_holes(combined)
            if n_holes_before:
                combined = HdfProject._fill_polygon_holes(combined)
                logger.debug(f"Footprint: filled {n_holes_before} interior hole(s)")

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
            {
                'description': ['Project Extent (Footprint)'],
                'source': [HdfProject._extent_source_label(used_hdf, used_plaintext)],
            },
            geometry=[combined],
            crs=crs,
        )

        if used_plaintext:
            logger.info("Project extent used plain-text geometry: %s", geom_path.name)

        return extent_gdf, tuple(float(v) for v in combined.bounds)

    @staticmethod
    @log_call
    def get_project_bounds_latlon(
        hdf_path: Optional[Union[str, Path, h5py.File]] = None,
        buffer_percent: float = 50.0,
        include_1d: bool = True,
        include_2d: bool = True,
        include_storage: bool = True,
        project_crs: Optional[str] = None,
        *,
        geom_path: Optional[Union[str, Path]] = None,
        fallback_to_plaintext: bool = True,
        ras_object=None,
    ) -> Tuple[float, float, float, float]:
        """
        Get project bounds in WGS84 lat/lon coordinates.

        Calculates project extent and transforms to WGS84 (EPSG:4326) for use
        with web services like AORC that expect lat/lon coordinates.

        Parameters
        ----------
        hdf_path : path-like, optional
            Path to a geometry HDF, plain-text geometry, or plan number.
        buffer_percent : float, default 50.0
            Buffer percentage to apply to extent
        include_1d : bool, default True
            Include 1D elements
        include_2d : bool, default True
            Include 2D elements
        include_storage : bool, default True
            Include storage areas from HDF or companion text geometry
        project_crs : str, optional
            Override CRS for projects without embedded projection. Use EPSG codes
            like "EPSG:26918" (UTM Zone 18N) or "EPSG:2271" (PA State Plane North).
            If None, attempts to read CRS from HDF file.
        geom_path : path-like, optional
            Explicit companion plain-text geometry path.
        ras_object : RasPrj, optional
            Project context for plan-number, geometry-path, and CRS resolution.
        fallback_to_plaintext : bool, default True
            Use plain-text geometry when requested geometry is unavailable in
            HDF. Set False to require HDF-derived geometry only.

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
            geom_path=geom_path,
            ras_object=ras_object,
            fallback_to_plaintext=fallback_to_plaintext,
        )

        source = hdf_path if hdf_path is not None else geom_path
        if isinstance(source, h5py.File):
            source_label = Path(source.filename).name
        elif isinstance(source, (str, Path)):
            source_label = Path(source).name
        else:
            source_label = str(source)

        if extent_gdf.empty:
            logger.debug(
                "Empty project extent for %s; returning zero bounds.",
                source_label,
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
                    source_label,
                )
                logger.debug(
                    "Original project-coordinate bounds for %s: W=%.6f, "
                    "S=%.6f, E=%.6f, N=%.6f",
                    source_label,
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
                    source_label,
                )
                logger.debug(
                    "Invalid WGS84 bounds for %s from source CRS %s: "
                    "W=%.6f, S=%.6f, E=%.6f, N=%.6f; original bounds=%s",
                    source_label,
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
                source_label,
            )
            logger.debug(
                "CRS transformation exception for %s: %s; original "
                "project-coordinate bounds W=%.6f, S=%.6f, E=%.6f, N=%.6f",
                source_label,
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
        buffer_percent: float = 50.0,
        *,
        geom_path: Optional[Union[str, Path]] = None,
        fallback_to_plaintext: bool = True,
        ras_object=None,
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
        geom_path : path-like, optional
            Explicit companion plain-text geometry path.
        fallback_to_plaintext : bool, default True
            Use companion plain-text geometry when requested geometry is
            unavailable in HDF. Set False to require HDF-derived geometry only.
        ras_object : RasPrj, optional
            Project context for path and CRS resolution.

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
            buffer_percent=buffer_percent,
            geom_path=geom_path,
            fallback_to_plaintext=fallback_to_plaintext,
            ras_object=ras_object,
        )

        # Convert to WGS84 for GeoJSON
        if extent_gdf.crs is not None and str(extent_gdf.crs) != "EPSG:4326":
            extent_gdf = extent_gdf.to_crs("EPSG:4326")

        extent_gdf.to_file(output_path, driver="GeoJSON")
        logger.info("Exported project extent to %s", output_path.name)
        logger.debug("Exported project extent full path: %s", output_path)

        return output_path
