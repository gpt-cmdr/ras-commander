"""
USGS 3DEP AWS Direct Access

Downloads elevation data directly from USGS 3DEP Cloud Optimized GeoTIFFs hosted on AWS S3.

This module provides metadata access across USGS 3DEP elevation datasets and
direct download support for 1m project-based products:
- 1m resolution downloads (LiDAR-derived, highest quality)
- 10m resolution metadata/discovery only in this revision
- 30m resolution metadata/discovery only in this revision

Data is accessed directly from the public S3 bucket (no API rate limits or timeouts).

Key Features:
- Automatic tile discovery via spatial metadata (GeoPackage)
- Multi-tile mosaicking for seamless coverage
- Coverage-aware, newest-per-sub-area project selection (no silent gaps)
- Virtual raster (VRT) creation for efficient processing
- Single-raster, project-CRS terrain builds on the smallest integer multiple of
  the dominant source resolution >= 5 project units, with prioritized
  bilinear backfill and a zero-nodata gate inside the buffered model extent
- Per-tile download provenance (source URL, project, ETag, Last-Modified, size)
- Cloud Optimized GeoTIFF support for partial reads

S3 Bucket Structure:
- 1m: s3://prd-tnm/StagedProducts/Elevation/1m/
- 10m: s3://prd-tnm/StagedProducts/Elevation/13/TIFF/
- 30m: s3://prd-tnm/StagedProducts/Elevation/1/TIFF/

Example:
    from ras_commander.terrain import Usgs3depAws
    from shapely.geometry import box

    # Create bounding box for area of interest
    bbox = box(-77.1, 40.6, -77.0, 40.7)

    # Download 1m DEM tiles
    tiles = Usgs3depAws.download_tiles(
        bbox=bbox,
        resolution=1,
        output_folder="Terrain"
    )

    # Create VRT mosaic
    vrt = Usgs3depAws.create_vrt(tiles, "terrain_1m.vrt")

    # Single-raster HEC-RAS terrain in the project CRS, gap-free inside the
    # buffered model extent, with 10m/30m backfill only where 1m is missing
    receipt = Usgs3depAws.build_terrain_raster(
        "Terrain/terrain_epsg2277.tif",
        project_crs="EPSG:2277",
        geom_path="Model.g01",
        hec_terrain_hdf="Terrain/hec/Terrain.hdf",
    )
"""

import json
import math
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box

from .._spatial_extent import (
    _normalize_extent_bounds,
    _normalize_extent_geometry,
)
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class TerrainBuildError(RuntimeError):
    """
    Raised when ``Usgs3depAws.build_terrain_raster()`` cannot deliver a valid
    single-raster terrain.

    Attributes:
        reason_code: Stable machine-readable reason, one of the
            ``Usgs3depAws.TERRAIN_REASON_*`` constants.
        details: JSON-serializable context such as the nodata pixel count,
            the bounds of the uncovered pixels, sample pixel-centre locations,
            and the path of the failure receipt.
    """

    def __init__(
        self,
        reason_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(f"[{reason_code}] {message}")
        self.reason_code = reason_code
        self.details = details or {}


class Usgs3depAws:
    """Direct access to USGS 3DEP elevation data on AWS S3."""

    # S3 bucket base URL
    S3_BASE_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation"

    # USGS 3DEP Tile Index API
    TILE_INDEX_API = "https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer"

    # Resolution to MapServer layer ID mapping
    # Based on https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer
    # Note: Layer IDs 1-6 have query errors, use layers 18-30 (project-level) instead
    LAYER_IDS = {
        1: 19,   # 1-meter projects
        3: 20,   # 1/9 arc-second projects
        10: 22,  # 1/3 arc-second projects
        30: 23,  # 1 arc-second projects
    }

    # Seamless 1-degree products used as terrain backfill:
    # resolution -> (S3 product folder, product label)
    SEAMLESS_PRODUCTS = {
        10: ("13", "3dep_seamless_1_3_arc_second"),
        30: ("1", "3dep_seamless_1_arc_second"),
    }

    # All 3DEP DEM products store NAVD88 heights in metres (CONUS).
    SOURCE_VERTICAL_DATUM = "NAVD88"
    SOURCE_VERTICAL_UNIT = "metre"

    # Exact metre equivalents of the linear units a project CRS may use, kept
    # as fractions so 1 m converts to exactly 3937/1200 US survey feet.
    LINEAR_UNIT_METRES = {
        "metre": Fraction(1),
        "us survey foot": Fraction(1200, 3937),
        "foot": Fraction(3048, 10000),
    }

    TERRAIN_RECEIPT_SCHEMA = "ras-commander/usgs-3dep-terrain-receipt"
    TERRAIN_REASON_VALID = "terrain_single_raster_valid"
    TERRAIN_REASON_NO_SOURCES = "terrain_no_source_coverage"
    TERRAIN_REASON_AOI_NODATA = "terrain_aoi_nodata_after_backfill"
    TERRAIN_REASON_HEC_MULTI_SOURCE = "hec_terrain_vrt_not_single_source"

    # Metadata URLs for each resolution (fallback)
    METADATA_URLS = {
        1: f"{S3_BASE_URL}/1m/FullExtentSpatialMetadata/FESM_1m.gpkg",
        10: f"{S3_BASE_URL}/13/FullExtentSpatialMetadata/FESM_13.gpkg",
        30: f"{S3_BASE_URL}/1/FullExtentSpatialMetadata/FESM_1.gpkg",
    }

    @staticmethod
    @log_call
    def download_tile_index(
        resolution: int,
        cache_folder: Optional[Union[str, Path]] = None
    ) -> gpd.GeoDataFrame:
        """
        Download tile index (spatial metadata) for a given resolution.

        Args:
            resolution: DEM resolution in meters. Direct downloads currently
                support only ``1``. Requests for 10m or 30m raise
                ``NotImplementedError`` until those download paths are added.
            cache_folder: Optional folder to cache the index. If None, downloads to temp.

        Returns:
            GeoDataFrame with tile locations and metadata

        Raises:
            ValueError: If resolution not supported
            requests.HTTPError: If download fails
        """
        if resolution not in Usgs3depAws.METADATA_URLS:
            raise ValueError(
                f"Resolution {resolution}m not supported. "
                f"Available: {list(Usgs3depAws.METADATA_URLS.keys())}"
            )

        url = Usgs3depAws.METADATA_URLS[resolution]

        # Determine cache path
        if cache_folder:
            cache_path = Path(cache_folder) / f"FESM_{resolution}m.gpkg"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            import tempfile
            cache_path = Path(tempfile.gettempdir()) / f"FESM_{resolution}m.gpkg"

        # Download if not cached
        if not cache_path.exists():
            logger.debug(f"Downloading {resolution}m USGS 3DEP tile index")
            logger.debug(f"USGS 3DEP tile index URL: {url}")
            logger.debug(f"USGS 3DEP tile index cache path: {cache_path}")

            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Save to cache
            with open(cache_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.debug(f"USGS 3DEP tile index saved to: {cache_path}")
        else:
            logger.debug(f"Using cached {resolution}m USGS 3DEP tile index: {cache_path}")

        # Read GeoPackage
        gdf = gpd.read_file(cache_path)
        logger.debug(f"USGS 3DEP tile index loaded: {len(gdf)} tiles ({resolution}m)")

        return gdf

    @staticmethod
    @log_call
    def query_tiles_api(
        bbox: Any,
        resolution: int,
        buffer_distance: float = 0.0,
    ) -> gpd.GeoDataFrame:
        """
        Query USGS 3DEP Tile Index API for tiles intersecting a bounding box.

        Uses the National Map ArcGIS REST API to get tile information.

        Args:
            bbox: One valid Polygon or a legacy bounds-shaped input in WGS84.
            resolution: DEM resolution in meters (1, 3, 10, or 30)
            buffer_distance: Optional buffer in WGS84 degrees. Default is 0.0.

        Returns:
            GeoDataFrame with tile information including download URLs
        """
        bbox_tuple = _normalize_extent_bounds(
            bbox,
            buffer_distance=buffer_distance,
            parameter_name="bbox",
        )

        # Get layer ID for resolution
        if resolution not in Usgs3depAws.LAYER_IDS:
            raise ValueError(
                f"Resolution {resolution}m not supported. "
                f"Available: {list(Usgs3depAws.LAYER_IDS.keys())}"
            )

        layer_id = Usgs3depAws.LAYER_IDS[resolution]

        # Build query URL
        query_url = f"{Usgs3depAws.TILE_INDEX_API}/{layer_id}/query"

        # Query parameters
        params = {
            'geometry': f"{bbox_tuple[0]},{bbox_tuple[1]},{bbox_tuple[2]},{bbox_tuple[3]}",
            'geometryType': 'esriGeometryEnvelope',
            'inSR': '4326',  # WGS84
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': '*',  # Get all fields
            'returnGeometry': 'true',
            'f': 'geojson'
        }

        logger.debug(f"Querying USGS Tile Index API for {resolution}m tiles")
        logger.debug(f"USGS Tile Index API request: {query_url} params={params}")
        response = requests.get(query_url, params=params)
        response.raise_for_status()

        # Parse GeoJSON response
        data = response.json()

        if 'features' not in data or len(data['features']) == 0:
            logger.warning("No tiles found in this area")
            return gpd.GeoDataFrame()

        # Convert to GeoDataFrame
        gdf = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")

        logger.debug(f"USGS Tile Index API returned {len(gdf)} tiles ({resolution}m)")

        return gdf

    @staticmethod
    @log_call
    def find_tiles_for_bbox(
        bbox: Any,
        resolution: int,
        cache_folder: Optional[Union[str, Path]] = None,
        buffer_distance: float = 0.0,
    ) -> gpd.GeoDataFrame:
        """
        Find all tiles that intersect with a bounding box.

        Uses GeoPackage tile index (more reliable than API).

        Args:
            bbox: One valid Polygon or a legacy bounds-shaped input in WGS84.
            resolution: DEM resolution in meters (1, 10, or 30)
            cache_folder: Optional folder to cache tile index
            buffer_distance: Optional buffer in WGS84 degrees. Default is 0.0.

        Returns:
            GeoDataFrame with intersecting projects
        """
        bbox = _normalize_extent_geometry(
            bbox,
            buffer_distance=buffer_distance,
            parameter_name="bbox",
        )

        # Download tile index (GeoPackage)
        tile_index = Usgs3depAws.download_tile_index(resolution, cache_folder)

        # Ensure CRS matches (tile index is typically EPSG:4326)
        if tile_index.crs is None:
            logger.warning("Tile index has no CRS, assuming EPSG:4326")
            tile_index = tile_index.set_crs("EPSG:4326")

        # Create GeoDataFrame for bbox
        bbox_gdf = gpd.GeoDataFrame([{'geometry': bbox}], crs="EPSG:4326")

        # Reproject bbox to match tile index if needed
        if bbox_gdf.crs != tile_index.crs:
            bbox_gdf = bbox_gdf.to_crs(tile_index.crs)

        # Find intersecting projects
        intersecting = tile_index[tile_index.intersects(bbox_gdf.geometry.iloc[0])]

        logger.debug(f"USGS 3DEP projects intersecting bbox: {len(intersecting)} ({resolution}m)")

        return intersecting

    @staticmethod
    @log_call
    def list_projects_for_bbox(
        bbox: Any,
        resolution: int,
        cache_folder: Optional[Union[str, Path]] = None,
        buffer_distance: float = 0.0,
    ) -> gpd.GeoDataFrame:
        """
        List all USGS 3DEP projects that intersect with a bounding box.

        Useful for exploring available data before downloading, or selecting
        specific projects by name or year.

        Args:
            bbox: One valid Polygon or a legacy bounds-shaped input in WGS84.
            resolution: DEM resolution in meters (1, 10, or 30)
            cache_folder: Optional folder to cache tile index
            buffer_distance: Optional buffer in WGS84 degrees. Default is 0.0.

        Returns:
            GeoDataFrame with project information including:
            - Project name (proj_name, project, or demname field)
            - Geometry (project extent polygon)
            - Year (extracted from project name if available)
            - All metadata from tile index

        Example:
            >>> from shapely.geometry import box
            >>> bbox = box(-77.5, 40.0, -76.5, 41.0)
            >>> projects = Usgs3depAws.list_projects_for_bbox(bbox, resolution=1)
            >>> print(projects[['proj_name', '_year', 'geometry']])
               proj_name                          _year  geometry
            0  PA_Northcentral_2019_B19           2019   POLYGON(...)
            1  PA_South_Central_2017_D17          2017   POLYGON(...)
        """
        import re

        # Find intersecting projects (from tile index)
        projects = Usgs3depAws.find_tiles_for_bbox(
            bbox,
            resolution,
            cache_folder,
            buffer_distance=buffer_distance,
        )

        if len(projects) == 0:
            logger.debug("No USGS 3DEP projects found for bbox")
            return projects

        # Extract year from project names
        def extract_year(row):
            """Extract year from project name."""
            for field in ['proj_name', 'project', 'demname']:
                if field in row.index and row[field]:
                    match = re.search(r'_(\d{4})_', str(row[field]))
                    if match:
                        return int(match.group(1))
            return None

        projects['_year'] = projects.apply(extract_year, axis=1)

        # Sort by year (most recent first)
        projects = projects.sort_values('_year', ascending=False, na_position='last')

        logger.debug(f"USGS 3DEP projects listed: {len(projects)} project(s) intersect bbox")
        for idx, row in projects.iterrows():
            proj_name = row.get('proj_name', row.get('project', row.get('demname', 'Unknown')))
            year = row['_year']
            year_str = str(year) if year else 'unknown'
            logger.debug(f"USGS 3DEP project: {proj_name} (year {year_str})")

        return projects

    @staticmethod
    def _extract_project_year(row) -> Optional[int]:
        """
        Extract the survey year from a USGS 3DEP project index row.

        USGS 3DEP project names embed the acquisition year between underscores
        (for example ``PA_Northcentral_2019_B19``).

        Args:
            row: One row of a USGS 3DEP project index (a pandas Series).

        Returns:
            Four-digit year as an int, or None when no project-name field on
            the row carries a parsable year.
        """
        for field in ['proj_name', 'project', 'demname']:
            if field in row.index and row[field]:
                match = re.search(r'_(\d{4})_', str(row[field]))
                if match:
                    return int(match.group(1))
        return None

    @staticmethod
    def _project_label(row) -> Optional[str]:
        """
        Return the first populated project-name field for a project index row.

        Args:
            row: One row of a USGS 3DEP project index (a pandas Series).

        Returns:
            Project name string, or None when the row carries no name field.
        """
        for field in ['proj_name', 'project', 'demname']:
            if field in row.index and row[field]:
                return str(row[field])
        return None

    @staticmethod
    def _row_year(row) -> Optional[int]:
        """
        Read the ``_year`` column from a project row as an optional int.

        Args:
            row: One row of a USGS 3DEP project index (a pandas Series).

        Returns:
            Year as an int, or None when the column is missing or NaN.
        """
        if '_year' not in row.index:
            return None

        year_value = row['_year']
        if year_value is None or pd.isna(year_value):
            return None

        return int(year_value)

    @staticmethod
    @log_call
    def select_projects_for_coverage(
        projects: gpd.GeoDataFrame,
        bbox: Any,
        min_coverage_fraction: float = 0.999,
        min_project_area_fraction: float = 0.0,
    ) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
        """
        Greedily select the newest USGS 3DEP project available per sub-area.

        A single "most recent project" can be smaller than the requested
        extent. Selecting only that project silently drops every sub-area it
        does not cover, which shows up later as holes or seams in the terrain
        mosaic. This method instead walks the candidate projects newest-first
        and keeps each project that contributes new area, falling back to
        progressively older projects only for the residual uncovered geometry.
        Selection stops as soon as the bbox is covered (within
        ``min_coverage_fraction``) or no candidate projects remain.

        Args:
            projects: Candidate projects, typically from
                ``find_tiles_for_bbox()`` or ``list_projects_for_bbox()``.
                A ``_year`` column is used when present and derived from the
                project names otherwise.
            bbox: One valid Polygon or a legacy bounds-shaped input in WGS84.
            min_coverage_fraction: Stop once this fraction of the bbox area is
                covered. Default 0.999 (99.9%).
            min_project_area_fraction: Skip a project whose new contribution is
                smaller than this fraction of the bbox area. Default 0.0, which
                keeps every project that contributes any positive area.

        Returns:
            Tuple of ``(selected_projects, coverage_report)``:

            - ``selected_projects`` is a GeoDataFrame in EPSG:4326, newest
              first, with three added columns: ``_year``,
              ``_coverage_area_fraction`` (the fraction of the bbox this
              project was selected to cover), and ``_coverage_region`` (the
              WGS84 geometry assigned to that project).
            - ``coverage_report`` is a dict with ``bbox_area``,
              ``covered_fraction``, ``uncovered_fraction``,
              ``uncovered_geometry`` (None when fully covered), and
              ``projects`` (one ``{project, year, area_fraction}`` entry per
              selected project, newest first).

        Raises:
            ValueError: If the coverage fractions are outside their valid
                ranges.

        Example:
            >>> from shapely.geometry import box
            >>> bbox = box(-77.5, 40.0, -76.5, 41.0)
            >>> projects = Usgs3depAws.list_projects_for_bbox(bbox, resolution=1)
            >>> selected, report = Usgs3depAws.select_projects_for_coverage(
            ...     projects, bbox
            ... )
            >>> report['covered_fraction']
            1.0
            >>> [entry['project'] for entry in report['projects']]
            ['PA_Northcentral_2019_B19', 'PA_South_Central_2017_D17']
        """
        if not 0.0 < min_coverage_fraction <= 1.0:
            raise ValueError(
                "min_coverage_fraction must be greater than 0 and at most 1, "
                f"got {min_coverage_fraction}"
            )

        if not 0.0 <= min_project_area_fraction < 1.0:
            raise ValueError(
                "min_project_area_fraction must be at least 0 and less than 1, "
                f"got {min_project_area_fraction}"
            )

        bbox_poly = _normalize_extent_geometry(bbox, parameter_name="bbox")
        bbox_area = bbox_poly.area

        if len(projects) == 0:
            return projects, {
                'bbox_area': bbox_area,
                'covered_fraction': 0.0,
                'uncovered_fraction': 1.0,
                'uncovered_geometry': bbox_poly,
                'projects': [],
            }

        # Work in WGS84 so the bbox and the project extents share one CRS.
        coverage_projects = projects
        if coverage_projects.crs is not None and coverage_projects.crs != "EPSG:4326":
            coverage_projects = coverage_projects.to_crs("EPSG:4326")

        if '_year' not in coverage_projects.columns:
            coverage_projects = coverage_projects.copy()
            coverage_projects['_year'] = coverage_projects.apply(
                Usgs3depAws._extract_project_year, axis=1
            )

        ordered = coverage_projects.sort_values(
            '_year', ascending=False, na_position='last'
        )

        residual = bbox_poly
        selected_positions: List[int] = []
        coverage_regions: List[Any] = []
        area_fractions: List[float] = []
        project_entries: List[Dict[str, Any]] = []

        for position, (_, project_row) in enumerate(ordered.iterrows()):
            if residual.is_empty:
                break

            geometry = project_row.geometry
            if geometry is None or geometry.is_empty:
                continue

            contribution = residual.intersection(geometry)
            if contribution.is_empty or contribution.area <= 0.0:
                continue

            area_fraction = contribution.area / bbox_area if bbox_area > 0 else 0.0
            label = Usgs3depAws._project_label(project_row)
            year = Usgs3depAws._row_year(project_row)

            if area_fraction < min_project_area_fraction:
                logger.debug(
                    f"Skipping USGS 3DEP project below minimum contribution: "
                    f"{label} ({area_fraction:.4%} of bbox)"
                )
                continue

            selected_positions.append(position)
            coverage_regions.append(contribution)
            area_fractions.append(area_fraction)
            project_entries.append({
                'project': label,
                'year': year,
                'area_fraction': area_fraction,
            })

            residual = residual.difference(geometry)

            if residual.is_empty:
                break
            if bbox_area > 0 and residual.area / bbox_area <= 1.0 - min_coverage_fraction:
                break

        uncovered_fraction = residual.area / bbox_area if bbox_area > 0 else 0.0
        coverage_report = {
            'bbox_area': bbox_area,
            'covered_fraction': max(0.0, 1.0 - uncovered_fraction),
            'uncovered_fraction': uncovered_fraction,
            'uncovered_geometry': None if residual.is_empty else residual,
            'projects': project_entries,
        }

        selected = ordered.iloc[selected_positions].copy()
        selected['_coverage_area_fraction'] = area_fractions
        selected['_coverage_region'] = coverage_regions

        logger.debug(
            f"USGS 3DEP coverage selection: {len(selected)} project(s), "
            f"{coverage_report['covered_fraction']:.2%} of bbox covered"
        )

        return selected, coverage_report

    @staticmethod
    def _get_transformer(utm_zone: int):
        """
        Get cached transformer for UTM zone to WGS84.

        Uses functools.lru_cache to avoid repeated CRS initialization.

        Args:
            utm_zone: UTM zone number (10-19 for CONUS)

        Returns:
            pyproj.Transformer: Cached transformer object
        """
        from functools import lru_cache
        from pyproj import Transformer

        @lru_cache(maxsize=10)
        def _cached_transformer(zone: int) -> Transformer:
            utm_epsg = f"EPSG:269{zone:02d}"
            return Transformer.from_crs(utm_epsg, "EPSG:4326", always_xy=True)

        return _cached_transformer(utm_zone)

    @staticmethod
    def _parse_tile_bounds_from_filename(
        filename: str,
        utm_zone: Optional[int] = None,
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Parse WGS84 bounds from USGS 3DEP 1m DEM filename (instant, no file I/O).

        USGS 3DEP 1m tiles use a 10km x 10km UTM grid with the tile's
        upper-left corner encoded in the filename: ``x`` is the west edge and
        ``y`` is the NORTH edge, both in 10km units. For example
        ``USGS_1M_14_x80y330_TX_Houston_B24.tif`` covers easting
        800000-810000 and northing 3290000-3300000 (plus a 6m overlap). This
        method provides ~10,000x speedup vs opening remote files.

        Two naming schemes are recognized:

        - ``USGS_1M_{zone}_x{X}y{Y}_...`` carries its UTM zone.
        - ``USGS_one_meter_x{X}y{Y}_...`` (older projects) does not; pass
          ``utm_zone`` for these, typically read once per project from one
          tile's metadata.

        Args:
            filename: e.g., 'USGS_1M_10_x37y351_PA_Northcentral_2019_B19.tif'
            utm_zone: UTM zone for filenames that do not encode one.

        Returns:
            (minx, miny, maxx, maxy) in WGS84 (EPSG:4326), or None if parsing fails

        Example:
            >>> Usgs3depAws._parse_tile_bounds_from_filename(
            ...     'USGS_1M_14_x80y330_TX_Houston_B24.tif'
            ... )
            (-95.87..., 29.72..., -95.76..., 29.82...)

        Note:
            Returns None for other products (10m and 30m use a lat/lon grid)
            and for ``USGS_one_meter`` names when ``utm_zone`` is not given.
        """
        # Extract filename from path if needed
        if '/' in filename or '\\' in filename:
            filename = Path(filename).name

        zoned_match = re.search(r'USGS_1M_(\d+)_x(\d+)y(\d+)_', filename)
        unzoned_match = re.search(r'USGS_one_meter_x(\d+)y(\d+)_', filename)

        try:
            if zoned_match:
                zone = int(zoned_match.group(1))
                x_index = int(zoned_match.group(2))
                y_index = int(zoned_match.group(3))
            elif unzoned_match and utm_zone is not None:
                zone = int(utm_zone)
                x_index = int(unzoned_match.group(1))
                y_index = int(unzoned_match.group(2))
            else:
                return None  # Not a recognized 1m DEM name

            # Validate zone (CONUS: 10-19, Hawaii: 4-5)
            if not (4 <= zone <= 19):
                logger.debug(f"UTM zone {zone} outside expected range (4-5, 10-19)")
                return None

            tile_size_m = 10000
            overlap_m = 6

            # x is the west edge; y is the north edge.
            utm_minx = x_index * tile_size_m - overlap_m
            utm_maxx = (x_index + 1) * tile_size_m + overlap_m
            utm_maxy = y_index * tile_size_m + overlap_m
            utm_miny = (y_index - 1) * tile_size_m - overlap_m

            transformer = Usgs3depAws._get_transformer(zone)

            # A UTM square is not axis-aligned in lon/lat, so take the
            # envelope of all four transformed corners.
            corners = [
                transformer.transform(utm_minx, utm_miny),
                transformer.transform(utm_minx, utm_maxy),
                transformer.transform(utm_maxx, utm_miny),
                transformer.transform(utm_maxx, utm_maxy),
            ]
            lons = [corner[0] for corner in corners]
            lats = [corner[1] for corner in corners]

            return (min(lons), min(lats), max(lons), max(lats))

        except (ValueError, IndexError) as e:
            logger.debug(f"Error parsing tile coordinates from {filename}: {e}")
            return None

    @staticmethod
    def _get_tile_utm_zone(tile_url: str) -> Optional[int]:
        """
        Read the UTM zone of a remote 1m tile from its GeoTIFF header.

        Used once per project whose tile names do not encode a zone, so the
        remaining tiles can be located by filename.

        Args:
            tile_url: Direct URL to a TIFF tile

        Returns:
            UTM zone number, or None when the CRS is not a UTM projection or
            the header cannot be read.
        """
        try:
            import rasterio
            from pyproj import CRS

            with rasterio.open(f"/vsicurl/{tile_url}") as src:
                utm_zone = CRS.from_wkt(src.crs.to_wkt()).utm_zone
        except Exception as e:
            logger.debug(f"Could not read UTM zone for {tile_url}: {e}")
            return None

        if not utm_zone:
            return None

        return int(re.match(r'(\d+)', utm_zone).group(1))

    @staticmethod
    def _get_project_tile_urls(project_name: str) -> Optional[List[str]]:
        """
        Get list of all tile URLs for a project from the download links file.

        Args:
            project_name: Project name (e.g., 'PA_Northcentral_2019_B19')

        Returns:
            List of direct URLs to TIFF tiles, or None if project not found in S3

        Note:
            GeoPackage tile index may contain outdated project names that no longer
            exist in S3. This method returns None for missing projects instead of
            failing, allowing downloads to continue with available projects.
        """
        # Download the file list
        links_url = f"{Usgs3depAws.S3_BASE_URL}/1m/Projects/{project_name}/0_file_download_links.txt"

        logger.debug(f"Fetching USGS 3DEP tile list for project: {project_name}")
        logger.debug(f"USGS 3DEP tile list URL: {links_url}")

        try:
            response = requests.get(links_url, timeout=30)
            response.raise_for_status()

            # Parse URLs
            urls = [line.strip() for line in response.text.strip().split('\n') if line.strip()]

            logger.debug(f"USGS 3DEP project tile count for {project_name}: {len(urls)}")
            return urls

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Project not found in S3: {project_name} (tile index may be outdated)")
                return None
            else:
                # Other HTTP errors should propagate
                raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching tile list for {project_name}: {e}")
            return None

    @staticmethod
    def _s3_project_folder(product_link) -> Optional[str]:
        """Extract the S3 StagedProducts project folder from a FESM index
        ``product_link`` value.

        e.g. ``https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/
        Projects/UT_Central_QL1_B2_2018`` -> ``UT_Central_QL1_B2_2018``.
        Returns None if the link is empty or has no ``/Projects/`` segment.
        """
        if not product_link:
            return None
        s = str(product_link).strip().rstrip('/')
        if '/Projects/' in s:
            return s.split('/Projects/')[-1].split('/')[0] or None
        return None

    @staticmethod
    def _get_remote_file_headers(url: str) -> Dict[str, Any]:
        """
        Read cache and provenance headers for a remote file with HTTP HEAD.

        One HEAD request supplies both the cache check used by
        ``_download_single_tile()`` and the ``ETag`` / ``Last-Modified`` /
        ``Content-Length`` provenance reported by ``download_tiles()``.

        Args:
            url: Remote file URL

        Returns:
            Dict with ``content_length`` (int or None), ``etag`` (str with any
            surrounding quotes removed, or None), and ``last_modified`` (str or
            None). Every value is None when the request fails.
        """
        headers: Dict[str, Any] = {
            'content_length': None,
            'etag': None,
            'last_modified': None,
        }

        try:
            response = requests.head(url, timeout=10)
            response.raise_for_status()

            content_length = response.headers.get('Content-Length')
            if content_length:
                headers['content_length'] = int(content_length)
            else:
                logger.debug(f"No Content-Length header for {url}")

            etag = response.headers.get('ETag')
            if etag:
                headers['etag'] = etag.strip('"')

            headers['last_modified'] = response.headers.get('Last-Modified')

        except Exception as e:
            logger.debug(f"Error getting remote headers for {url}: {e}")

        return headers

    @staticmethod
    def _get_remote_file_size(url: str) -> Optional[int]:
        """
        Get remote file size in bytes using HTTP HEAD request.

        Args:
            url: Remote file URL

        Returns:
            File size in bytes, or None if cannot determine
        """
        return Usgs3depAws._get_remote_file_headers(url)['content_length']

    @staticmethod
    def _build_tile_provenance(
        tile_url: str,
        tile_path: Union[str, Path],
        project_name: Optional[str] = None,
        project_year: Optional[int] = None,
        project_folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build one provenance record for a downloaded or cached tile.

        Args:
            tile_url: Source URL the tile was downloaded from
            tile_path: Local path to the downloaded or cached tile
            project_name: USGS 3DEP project the tile belongs to
            project_year: Survey year of that project
            project_folder: S3 StagedProducts project folder the tile was
                read from, which can differ from the index collection name

        Returns:
            Dict with ``tile_id``, ``file_name``, ``file_path``,
            ``source_url``, ``project_name``, ``project_folder``,
            ``project_year``, ``etag``,
            ``last_modified``, ``content_length``, and ``local_size_bytes``.
            The remote header values are None when the HEAD request fails.
        """
        tile_path = Path(tile_path)
        remote_headers = Usgs3depAws._get_remote_file_headers(tile_url)

        local_size = None
        if tile_path.exists():
            local_size = tile_path.stat().st_size

        return {
            'tile_id': Path(tile_url.split('/')[-1]).stem,
            'file_name': tile_path.name,
            'file_path': str(tile_path),
            'source_url': tile_url,
            'project_name': project_name,
            'project_folder': project_folder,
            'project_year': project_year,
            'etag': remote_headers['etag'],
            'last_modified': remote_headers['last_modified'],
            'content_length': remote_headers['content_length'],
            'local_size_bytes': local_size,
        }

    @staticmethod
    def _collect_tile_provenance(
        project_groups: Sequence[Dict[str, Any]],
        max_workers: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Build provenance records for every downloaded tile, in mosaic order.

        Args:
            project_groups: Per-project download groups, each a dict with
                ``project_name``, ``project_year``, and ``tiles`` (a list of
                ``(tile_url, tile_path)`` pairs).
            max_workers: Maximum concurrent HEAD requests. Default 3.

        Returns:
            List of provenance dicts in the same order as the supplied groups
            and tiles.
        """
        tasks = [
            (
                tile_url,
                tile_path,
                group['project_name'],
                group['project_year'],
                group.get('project_folder'),
            )
            for group in project_groups
            for tile_url, tile_path in group['tiles']
        ]

        if not tasks:
            return []

        if max_workers <= 1:
            return [Usgs3depAws._build_tile_provenance(*task) for task in tasks]

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(
                executor.map(
                    lambda task: Usgs3depAws._build_tile_provenance(*task),
                    tasks,
                )
            )

    @staticmethod
    def _download_single_tile(
        tile_url: str,
        output_folder: Union[str, Path],
        overwrite_dest: bool
    ) -> Optional[Path]:
        """
        Download a single tile with caching support (thread-safe).

        Args:
            tile_url: URL to tile
            output_folder: Destination folder
            overwrite_dest: Force re-download even if cached

        Returns:
            Path to downloaded/cached file, or None if failed
        """
        filename = tile_url.split('/')[-1]
        output_path = Path(output_folder) / filename

        try:
            # Check if file exists and is valid (passive caching)
            if output_path.exists() and not overwrite_dest:
                # Verify file size matches expected size
                local_size = output_path.stat().st_size
                expected_size = Usgs3depAws._get_remote_file_size(tile_url)

                if expected_size and local_size == expected_size:
                    # File exists with correct size - use cached version
                    size_mb = local_size / 1024 / 1024
                    logger.debug(f"Using cached USGS 3DEP tile: {output_path} ({size_mb:.2f} MB)")
                    return output_path
                elif expected_size:
                    # File exists but wrong size - re-download
                    logger.warning(
                        f"Cached file size mismatch for {filename}: "
                        f"local={local_size:,} bytes, expected={expected_size:,} bytes"
                    )
                    logger.debug(f"Re-downloading USGS 3DEP tile after cache size mismatch: {output_path}")
                else:
                    # Cannot verify size - assume cached file is good
                    size_mb = local_size / 1024 / 1024
                    logger.debug(f"Using cached USGS 3DEP tile: {output_path} ({size_mb:.2f} MB, size unverified)")
                    return output_path

            # Download tile
            logger.debug(f"Downloading USGS 3DEP tile: {filename} from {tile_url}")
            response = requests.get(tile_url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_mb = output_path.stat().st_size / 1024 / 1024
            logger.debug(f"Saved USGS 3DEP tile: {output_path} ({size_mb:.2f} MB)")
            return output_path

        except Exception as e:
            logger.error(f"Failed to download USGS 3DEP tile {filename}: {e}")
            return None

    @staticmethod
    def _get_tile_bounds_wgs84(tile_url: str) -> Tuple[float, float, float, float]:
        """
        Get tile bounds in WGS84 using /vsicurl/ (reads metadata without full download).

        Args:
            tile_url: Direct URL to TIFF tile

        Returns:
            Bounds as (minx, miny, maxx, maxy) in WGS84
        """
        import rasterio
        from pyproj import Transformer

        vsicurl_path = f"/vsicurl/{tile_url}"

        with rasterio.open(vsicurl_path) as src:
            bounds = src.bounds
            crs = src.crs

            # Convert to WGS84
            transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            minx, miny = transformer.transform(bounds.left, bounds.bottom)
            maxx, maxy = transformer.transform(bounds.right, bounds.top)

            return (minx, miny, maxx, maxy)

    @staticmethod
    @log_call
    def download_tiles(
        bbox: Any,
        resolution: int,
        output_folder: Union[str, Path],
        cache_folder: Optional[Union[str, Path]] = None,
        overwrite_dest: bool = False,
        max_workers: int = 3,
        project_name: Optional[str] = None,
        min_year: Optional[int] = None,
        buffer_distance: float = 0.0,
        *,
        project_selection: str = "newest",
        min_coverage_fraction: float = 0.999,
        min_project_area_fraction: float = 0.0,
        return_provenance: bool = False,
        exclude_tile_ids: Optional[Sequence[str]] = None,
    ) -> Union[List[Path], Tuple[List[Path], List[Dict[str, Any]]]]:
        """
        Download all DEM tiles for a bounding box with concurrent downloads.

        Implements passive file caching: if a tile already exists with the correct
        file size, it will be reused instead of re-downloaded. This allows
        interrupted downloads to resume and repeated runs to use cached files.

        Downloads are performed concurrently using multiple threads for improved
        performance (default 3 concurrent downloads).

        Args:
            bbox: One valid Polygon or a legacy bounds-shaped input in WGS84.
            resolution: DEM resolution in meters (1, 10, or 30)
            output_folder: Folder to save downloaded tiles
            cache_folder: Optional folder to cache tile index
            overwrite_dest: If True, re-download even if file exists with correct size.
                           Default False (passive caching enabled).
            max_workers: Maximum number of concurrent downloads. Default 3.
                        Set to 1 for sequential downloads.
            project_name: Optional specific project name to download (e.g., 'PA_Northcentral_2019_B19').
                         If specified, downloads only from this project.
                         Use list_projects_for_bbox() to see available projects.
            min_year: Optional minimum year filter (e.g., 2019).
                     Only considers projects from this year or newer.
                     Ignored if project_name is specified.
            buffer_distance: Optional buffer in WGS84 degrees, applied before
                tile discovery and intersection. Default is 0.0.
            project_selection: How to choose among the projects that intersect
                the bbox. ``"newest"`` (default) keeps the single most recent
                project, which is the historical behavior and can silently
                leave the rest of the bbox uncovered. ``"coverage"`` greedily
                covers the bbox with the newest project available per
                sub-area, falling back to older projects only for the residual
                uncovered geometry. Keyword-only.
            min_coverage_fraction: Coverage-mode stop condition; selection ends
                once this fraction of the bbox is covered. Default 0.999.
                Ignored when ``project_selection="newest"``. Keyword-only.
            min_project_area_fraction: Coverage-mode minimum new contribution
                required to pull in another project, as a fraction of bbox
                area. Default 0.0 (accept any positive contribution). Ignored
                when ``project_selection="newest"``. Keyword-only.
            return_provenance: If True, also return one provenance record per
                downloaded tile. Default False. Keyword-only.
            exclude_tile_ids: Tile identifiers (filename stems, for example
                ``"USGS_1M_14_x80y330_TX_Houston_B24"``) that must not be
                downloaded, such as known-bad tiles. Default None.
                Keyword-only.

        Returns:
            List of paths to downloaded TIFF files, or, when
            ``return_provenance=True``, a ``(tile_paths, provenance)`` tuple.
            Each provenance record is a dict with ``tile_id``, ``file_name``,
            ``file_path``, ``source_url``, ``project_name``, ``project_year``,
            ``etag``, ``last_modified``, ``content_length``,
            ``local_size_bytes``, and ``project_folder`` (the S3 project
            folder, which can differ from the index collection name).

            In coverage mode the returned tiles are ordered oldest project
            first, so the newest tiles come last and win where projects
            overlap in a ``gdalbuildvrt`` mosaic.

        Raises:
            NotImplementedError: If ``resolution`` is not 1.
            ValueError: If ``project_selection`` is not ``"newest"`` or
                ``"coverage"``, or if a requested ``project_name`` or
                ``min_year`` matches no project in the bbox.

        Example:
            # Default: Downloads tiles from most recent project (3 concurrent)
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain")

            # List available projects first
            projects = Usgs3depAws.list_projects_for_bbox(bbox, 1)
            print(projects[['proj_name', '_year']])

            # Download from specific project by name
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain",
                                                project_name="PA_Northcentral_2019_B19")

            # Download only from projects 2018 or newer
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain", min_year=2018)

            # Force re-download with 5 concurrent workers
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain",
                                                overwrite_dest=True, max_workers=5)

            # Sequential downloads (no concurrency)
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain", max_workers=1)

            # Cover the whole bbox using the newest project per sub-area
            tiles = Usgs3depAws.download_tiles(bbox, 1, "Terrain",
                                                project_selection="coverage")

            # Capture per-tile provenance for a terrain build record
            tiles, provenance = Usgs3depAws.download_tiles(
                bbox, 1, "Terrain",
                project_selection="coverage",
                return_provenance=True,
            )
            print(provenance[0]['source_url'], provenance[0]['etag'])
        """
        if resolution != 1:
            raise NotImplementedError(
                "download_tiles() currently supports only 1m USGS 3DEP project "
                "downloads. 10m and 30m direct download paths are not implemented "
                "yet."
            )

        excluded_tile_ids = set(exclude_tile_ids or [])

        valid_selection_modes = ("newest", "coverage")
        if project_selection not in valid_selection_modes:
            raise ValueError(
                "project_selection must be one of "
                f"{valid_selection_modes}, got {project_selection!r}"
            )

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        bbox_poly = _normalize_extent_geometry(
            bbox,
            buffer_distance=buffer_distance,
            parameter_name="bbox",
        )

        # Find intersecting projects (from tile index)
        projects = Usgs3depAws.find_tiles_for_bbox(bbox_poly, resolution, cache_folder)

        if len(projects) == 0:
            logger.warning("No projects found for bbox - no data available in this area")
            return ([], []) if return_provenance else []

        logger.debug(f"USGS 3DEP download candidate projects: {len(projects)}")

        # Extract year from project names for filtering/sorting
        projects['_year'] = projects.apply(Usgs3depAws._extract_project_year, axis=1)
        selection_logged = False

        # Project selection logic
        if project_name:
            # Filter to exact project name match
            logger.debug(f"Filtering USGS 3DEP projects to: {project_name}")

            # Try all possible project name fields, plus the S3 folder parsed
            # from 'product_link' (so callers may pass either the collection
            # name or the actual S3 StagedProducts folder).
            mask = False
            for field in ['proj_name', 'project', 'demname']:
                if field in projects.columns:
                    mask = mask | (projects[field] == project_name)
            if 'product_link' in projects.columns:
                mask = mask | projects['product_link'].apply(
                    lambda pl: Usgs3depAws._s3_project_folder(pl) == project_name)

            projects_filtered = projects[mask]

            if len(projects_filtered) == 0:
                # Show available projects to help user
                available = []
                for idx, row in projects.iterrows():
                    proj = row.get('proj_name', row.get('project', row.get('demname', 'Unknown')))
                    year = row['_year']
                    available.append(f"{proj} (year {year if year else 'unknown'})")

                raise ValueError(
                    f"Project '{project_name}' not found in bbox.\n"
                    f"Available projects:\n  - " + "\n  - ".join(available)
                )

            projects = projects_filtered
            logger.debug(f"Matched requested USGS 3DEP project: {project_name}")

        elif min_year:
            # Filter to projects >= min_year
            logger.debug(f"Filtering USGS 3DEP projects to {min_year} or newer")

            # Filter out projects with no year or year < min_year
            projects_filtered = projects[
                (projects['_year'].notna()) & (projects['_year'] >= min_year)
            ]

            if len(projects_filtered) == 0:
                logger.warning(f"No USGS 3DEP projects found from {min_year} or newer")
                logger.warning(f"Available USGS 3DEP project years: {sorted(projects['_year'].dropna().unique())}")
                raise ValueError(f"No projects found from year {min_year} or newer")

            projects = projects_filtered
            logger.debug(f"USGS 3DEP projects matching min_year={min_year}: {len(projects)}")

        if project_selection == "coverage":
            # Cover the bbox with the newest project available per sub-area
            # instead of dropping every area the single newest project misses.
            projects, coverage_report = Usgs3depAws.select_projects_for_coverage(
                projects,
                bbox_poly,
                min_coverage_fraction=min_coverage_fraction,
                min_project_area_fraction=min_project_area_fraction,
            )
            selection_logged = True

            for entry in coverage_report['projects']:
                entry_year = entry['year'] if entry['year'] else 'unknown'
                logger.debug(
                    f"USGS 3DEP coverage project selected: {entry['project']} "
                    f"(year {entry_year}; {entry['area_fraction']:.2%} of bbox)"
                )

            if coverage_report['uncovered_fraction'] > 0:
                logger.warning(
                    "USGS 3DEP coverage gap: "
                    f"{coverage_report['uncovered_fraction']:.2%} of the requested "
                    "bbox is not covered by any available project"
                )

            if len(projects) == 0:
                logger.warning("No USGS 3DEP project covers any part of the bbox")
                return ([], []) if return_provenance else []

        # If multiple projects remain, select most recent
        elif len(projects) > 1:
            projects = projects.sort_values('_year', ascending=False, na_position='last')

            most_recent = projects.iloc[0]
            year = projects.iloc[0]['_year']

            selected_name = most_recent.get('proj_name', most_recent.get('project', most_recent.get('demname')))
            logger.debug(
                f"USGS 3DEP project selected: {selected_name} "
                f"(year {year if year else 'unknown'}; skipped {len(projects) - 1} older)"
            )
            selection_logged = True

            logger.debug(f"Skipping {len(projects) - 1} older USGS 3DEP project(s)")
            for idx in range(1, min(len(projects), 4)):
                older = projects.iloc[idx]
                older_year = older['_year']
                older_name = older.get('proj_name', older.get('project', older.get('demname')))
                logger.debug(f"Skipped older USGS 3DEP project: {older_name} (year {older_year if older_year else 'unknown'})")

            # Use only the most recent project
            projects = projects.iloc[[0]]

        # Download tiles from selected project(s)
        downloaded_by_project: List[Dict[str, Any]] = []

        for idx, project_row in projects.iterrows():
            # The actual S3 StagedProducts folder lives in 'product_link'. The
            # index 'project' field is a logical collection name that often
            # differs from the S3 folder (e.g. 'UT_StateWide_2018_A18' whose
            # tiles live under '.../Projects/UT_Central_QL1_B2_2018', or
            # 'Wasatch_Fault_UT_LiDAR' -> '.../Projects/UT_Wasatch_L5_2014').
            # Building the S3 path from the collection name 404s; use the link.
            s3_folder = Usgs3depAws._s3_project_folder(project_row.get('product_link'))
            label = None
            for field in ['proj_name', 'project', 'demname']:
                if field in project_row.index and project_row[field]:
                    label = project_row[field]
                    break
            s3_folder = s3_folder or label  # fall back to the collection name

            if not s3_folder:
                logger.warning(f"No project folder/name found in row {idx}, skipping")
                continue

            if len(projects) == 1 and not selection_logged:
                year = project_row['_year'] if '_year' in project_row.index else None
                logger.debug(
                    f"USGS 3DEP project selected: {label or s3_folder} "
                    f"(year {year if year else 'unknown'})"
                )
            logger.debug(f"Processing USGS 3DEP project: {label or s3_folder}")

            # Get all tile URLs for this project
            tile_urls = Usgs3depAws._get_project_tile_urls(s3_folder)

            # Skip if project not found in S3 (outdated tile index)
            if tile_urls is None:
                logger.debug(f"Skipping USGS 3DEP project not available in S3: {project_name}")
                continue

            # Coverage mode assigns each project the sub-area it was
            # selected to cover, so an older project only contributes tiles
            # for the part of the bbox no newer project reaches.
            selection_region = bbox_poly
            if '_coverage_region' in project_row.index:
                coverage_region = project_row['_coverage_region']
                if coverage_region is not None and not coverage_region.is_empty:
                    selection_region = coverage_region

            # Find which tiles intersect our bbox
            logger.debug(f"Checking {len(tile_urls)} USGS 3DEP tiles for intersection")
            intersecting_urls = []
            project_utm_zone: Optional[int] = None

            for tile_url in tile_urls:
                filename = tile_url.split('/')[-1]

                if Path(filename).stem in excluded_tile_ids:
                    logger.debug(f"Excluding USGS 3DEP tile by request: {filename}")
                    continue

                try:
                    # Fast path: Parse bounds from filename (instant)
                    tile_bounds = Usgs3depAws._parse_tile_bounds_from_filename(filename)

                    # Older 'USGS_one_meter' names omit the UTM zone: read it
                    # once per project, then keep using the filename fast path.
                    if tile_bounds is None and 'USGS_one_meter_' in filename:
                        if project_utm_zone is None:
                            project_utm_zone = Usgs3depAws._get_tile_utm_zone(tile_url)
                        if project_utm_zone is not None:
                            tile_bounds = Usgs3depAws._parse_tile_bounds_from_filename(
                                filename,
                                utm_zone=project_utm_zone,
                            )

                    # Fallback: Open remote file if parsing fails (slow, 2-5 sec)
                    if tile_bounds is None:
                        logger.debug(f"    Filename parsing failed for {filename}, using /vsicurl/ fallback")
                        tile_bounds = Usgs3depAws._get_tile_bounds_wgs84(tile_url)

                    tile_box = box(*tile_bounds)

                    # Check intersection
                    if tile_box.intersects(selection_region):
                        intersecting_urls.append(tile_url)

                except Exception as e:
                    logger.debug(f"    Error checking tile {filename}: {e}")
                    continue

            logger.debug(f"USGS 3DEP intersecting tiles: {len(intersecting_urls)}")

            project_tiles: List[Tuple[str, Path]] = []

            # Download intersecting tiles (concurrent)
            if max_workers == 1:
                # Sequential downloads
                logger.debug("Downloading USGS 3DEP tiles sequentially")
                for tile_url in intersecting_urls:
                    result = Usgs3depAws._download_single_tile(
                        tile_url, output_folder, overwrite_dest
                    )
                    if result:
                        project_tiles.append((tile_url, Path(result)))
            else:
                # Concurrent downloads
                from concurrent.futures import ThreadPoolExecutor, as_completed

                logger.debug(f"Downloading USGS 3DEP tiles with {max_workers} concurrent workers")

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all download tasks
                    future_to_url = {
                        executor.submit(
                            Usgs3depAws._download_single_tile,
                            tile_url,
                            output_folder,
                            overwrite_dest
                        ): tile_url
                        for tile_url in intersecting_urls
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_url):
                        tile_url = future_to_url[future]
                        try:
                            result = future.result()
                            if result:
                                project_tiles.append((tile_url, Path(result)))
                        except Exception as e:
                            filename = tile_url.split('/')[-1]
                            logger.error(f"Concurrent USGS 3DEP tile download failed for {filename}: {e}")

            downloaded_by_project.append({
                'project_name': label or s3_folder,
                'project_folder': s3_folder,
                'project_year': Usgs3depAws._row_year(project_row),
                'tiles': project_tiles,
            })

        if project_selection == "coverage":
            # Oldest project first so the newest tiles are last in the mosaic
            # order and win wherever selected projects overlap.
            ordered_groups = list(reversed(downloaded_by_project))
            for group in ordered_groups:
                group['tiles'] = sorted(group['tiles'], key=lambda tile: tile[1].name)
        else:
            ordered_groups = downloaded_by_project

        all_downloaded = [
            tile_path
            for group in ordered_groups
            for _, tile_path in group['tiles']
        ]

        logger.info(f"USGS 3DEP tile download complete: {len(all_downloaded)} tile(s) available")

        if not return_provenance:
            return all_downloaded

        provenance = Usgs3depAws._collect_tile_provenance(
            ordered_groups,
            max_workers=max_workers,
        )
        return all_downloaded, provenance

    @staticmethod
    @log_call
    def create_vrt(
        tile_files: Sequence[Union[str, Path]],
        output_vrt: Union[str, Path],
        hecras_version: Optional[str] = None,
    ) -> Path:
        """
        Create a Virtual Raster (VRT) mosaic from multiple tiles.

        Args:
            tile_files: List of TIFF files to mosaic
            output_vrt: Output VRT file path
            hecras_version: Optional HEC-RAS version to use for bundled
                GDAL discovery. If None, auto-detects the newest available
                install.

        Returns:
            Path to created VRT file
        """
        if not tile_files:
            raise ValueError("tile_files must contain at least one raster")

        output_vrt = Path(output_vrt)
        output_vrt.parent.mkdir(parents=True, exist_ok=True)
        tile_paths = [Path(tile_file) for tile_file in tile_files]

        for tile_path in tile_paths:
            if not tile_path.exists():
                raise FileNotFoundError(f"Tile file not found: {tile_path}")

        # Build VRT
        logger.debug(f"Creating VRT mosaic from {len(tile_files)} tile(s)")

        try:
            gdalbuildvrt = Usgs3depAws._find_gdalbuildvrt_path(hecras_version)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Creating a VRT requires HEC-RAS bundled gdalbuildvrt.exe. "
                f"{exc}"
            ) from exc
        logger.debug(f"Using gdalbuildvrt executable: {gdalbuildvrt}")

        input_list_path = Usgs3depAws._write_gdal_input_file_list(
            tile_paths,
            output_vrt.parent,
        )
        logger.debug(f"gdalbuildvrt input file list: {input_list_path}")
        cmd = [
            str(gdalbuildvrt),
            "-overwrite",
            "-r", "bilinear",
            "-input_file_list", str(input_list_path),
            str(output_vrt),
        ]
        logger.debug(f"gdalbuildvrt command: {cmd}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "gdalbuildvrt timed out while creating the VRT mosaic."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Failed to execute gdalbuildvrt: {exc}"
            ) from exc
        finally:
            input_list_path.unlink(missing_ok=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"gdalbuildvrt failed with code {result.returncode}. "
                f"STDERR: {result.stderr}"
            )

        if not output_vrt.exists():
            raise RuntimeError(
                f"gdalbuildvrt completed but VRT was not created: {output_vrt}"
            )

        logger.info(f"VRT mosaic created: {output_vrt.name}")
        logger.debug(f"VRT mosaic output path: {output_vrt}")
        return output_vrt

    @staticmethod
    @log_call
    def build_terrain_raster(
        output_raster: Union[str, Path],
        project_crs: str,
        geom_path: Optional[Union[str, Path]] = None,
        aoi_geometry: Optional[Any] = None,
        *,
        buffer_distance: float = 100.0,
        buffer_units: str = "US survey foot",
        vertical_unit: Optional[str] = None,
        minimum_cell_size: float = 5.0,
        target_resolution: Optional[float] = None,
        backfill_resolutions: Sequence[int] = (10, 30),
        exclude_tile_ids: Optional[Sequence[str]] = None,
        download_folder: Optional[Union[str, Path]] = None,
        cache_folder: Optional[Union[str, Path]] = None,
        resampling_method: str = "bilinear",
        nodata: float = -9999.0,
        src_nodata: Optional[float] = None,
        max_workers: int = 3,
        hecras_version: Optional[str] = None,
        hec_terrain_hdf: Optional[Union[str, Path]] = None,
        receipt_path: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        timeout_seconds: int = 7200,
    ) -> Dict[str, Any]:
        """
        Build one gap-free GeoTIFF terrain in the project CRS for HEC-RAS.

        RASMapper creates result rasters that mirror the structure of the
        terrain VRT: when the terrain references several rasters, every result
        output mirrors that multi-raster structure. This method therefore
        delivers exactly ONE raster, already in the project CRS (so HEC-RAS
        never reprojects), on one common grid, and verifies that the HEC-RAS
        terrain built from it has a single source member.

        Pipeline:

        1. **AOI.** The buffered model extent in project CRS. From
           ``geom_path`` it is the union of the model footprint
           (``HdfProject.get_project_extent(..., geometry_type="footprint")``,
           which supports text-only 1D geometry) and the FULL cross-section
           cut lines, which can protrude beyond the edge-line footprint, then
           buffered by an ABSOLUTE distance. Alternatively pass
           ``aoi_geometry`` (project CRS), which is buffered the same way.
        2. **Priority chain.** 3DEP 1m project-based DEMs selected with
           ``download_tiles(project_selection="coverage")`` (newest project per
           sub-area), then the seamless 1/3 arc-second (~10m) and 1
           arc-second (~30m) products. A lower tier is downloaded only when
           the higher tiers leave AOI pixels uncovered, and only for the
           bounds of those pixels.
        3. **Cell size.** The dominant resolution is the native resolution of
           the tier contributing the most AOI area, converted to project CRS
           linear units with exact fractions (1m in EPSG:2277 is 3937/1200 =
           3.2808333333333333 US survey feet). The cell size is
           ``k * dominant_resolution`` for the smallest integer ``k >= 1`` with
           ``k * dominant_resolution >= minimum_cell_size`` (default 5 project
           units): 1m in EPSG:2277 gives k=2 and 6.5616666666666667 ftUS, while a
           10m source already exceeds 5 ft, so k=1. ``target_resolution``
           overrides the rule; a value that is not an integer multiple of the
           dominant resolution is snapped to the nearest multiple (at least 1x)
           with a logged warning.
        4. **One composite.** A single HEC-RAS bundled ``gdalwarp.exe`` call
           with every source ordered lowest priority first and highest last
           (later valid pixels overwrite earlier ones), ``-t_srs``, ``-tr``,
           ``-tap``, ``-te`` snapped outward, bilinear resampling for every
           tier, and a tiled, compressed GeoTIFF.
        5. **Vertical units.** 3DEP heights are NAVD88 metres and reprojection
           changes horizontal units only; the bundled GDAL 3.0.2 ``gdalwarp``
           does not rescale Z even when given compound CRSs. Valid pixels are
           therefore explicitly scaled into the project vertical unit (x
           3.2808333333333333 for US survey feet).
        6. **Hard gate.** Nodata pixels inside the buffered AOI polygon (not
           its bounding rectangle; any pixel touching the polygon counts) must
           be zero. If backfill is exhausted, ``TerrainBuildError`` is raised
           with ``TERRAIN_REASON_AOI_NODATA``, the count, and the locations.
           Terrain is never fabricated.
        7. **Receipt.** Per tier: projects, tiles with provenance, contributed
           AOI pixels and area; plus the chosen resolution and why, vertical
           conversion, target CRS, grid origin, and the nodata-inside-AOI count.
        8. **HEC-RAS handoff (optional).** With ``hec_terrain_hdf``, the terrain
           is built by ``RasTerrain.create_terrain_hdf`` from the single raster
           with stitching disabled, and the resulting Terrain.vrt must contain
           exactly one source member.

        Args:
            output_raster: Output GeoTIFF path.
            project_crs: Projected CRS of the HEC-RAS project, for example
                ``"EPSG:2277"``. Required, because text-only geometry carries
                no CRS of its own.
            geom_path: Plain-text (``.g##``) or HDF geometry to derive the AOI
                from. Provide exactly one of ``geom_path`` and ``aoi_geometry``.
            aoi_geometry: Shapely geometry of the model extent in project CRS.
            buffer_distance: Absolute AOI buffer. Default 100. Keyword-only.
            buffer_units: Units of ``buffer_distance``: ``"US survey foot"``
                (default), ``"foot"``, ``"metre"``, or ``"project"`` for the
                project CRS linear unit. Keyword-only.
            vertical_unit: Output elevation unit: ``"US survey foot"``,
                ``"foot"``, or ``"metre"``. Default None uses the project CRS
                linear unit. Keyword-only.
            minimum_cell_size: Minimum output cell size in project CRS linear
                units. Default 5.0. The cell size is the smallest integer
                multiple of the dominant resolution that reaches it.
                Keyword-only.
            target_resolution: Cell size in project CRS units overriding the
                minimum-cell-size rule. Snapped, with a warning, to the nearest
                integer multiple (at least 1) of the dominant resolution.
                Keyword-only.
            backfill_resolutions: Lower-priority tiers, in priority order,
                from ``10`` and ``30``. Default ``(10, 30)``; ``()`` disables
                backfill. Keyword-only.
            exclude_tile_ids: Tile identifiers (filename stems) to withhold in
                every tier. Keyword-only.
            download_folder: Where source tiles are cached. Default is a
                ``source-tiles`` folder beside the output. Keyword-only.
            cache_folder: Tile index cache folder. Keyword-only.
            resampling_method: gdalwarp resampling applied to every tier.
                Default ``"bilinear"``. Keyword-only.
            nodata: Output nodata value. Default -9999. Keyword-only.
            src_nodata: Source nodata override. Default None uses each
                source's own nodata metadata, which differs between 3DEP
                products. Keyword-only.
            max_workers: Concurrent tile downloads. Default 3. Keyword-only.
            hecras_version: HEC-RAS version whose bundled GDAL and RasProcess
                are used. Default None picks the newest install with gdalwarp
                (and ``create_terrain_hdf``'s own default). Keyword-only.
            hec_terrain_hdf: If given, build the HEC-RAS terrain HDF here and
                assert its Terrain.vrt has exactly one source. Keyword-only.
            receipt_path: Receipt JSON path. Default
                ``<output stem>.terrain_receipt.json``. Keyword-only.
            overwrite: Replace an existing output. Default False. Keyword-only.
            timeout_seconds: Timeout for each gdalwarp call and for HEC-RAS
                terrain creation. Default 7200. Keyword-only.

        Returns:
            The receipt dict, also written to ``receipt_path``.

        Raises:
            ValueError: For invalid arguments, a non-projected project CRS, or
                an empty AOI.
            FileExistsError: If the output exists and ``overwrite`` is False.
            FileNotFoundError: If the HEC-RAS bundled gdalwarp.exe is missing.
            RuntimeError: If gdalwarp fails.
            TerrainBuildError: With ``TERRAIN_REASON_NO_SOURCES``,
                ``TERRAIN_REASON_AOI_NODATA``, or
                ``TERRAIN_REASON_HEC_MULTI_SOURCE``.

        Example:
            >>> receipt = Usgs3depAws.build_terrain_raster(
            ...     "Terrain/maha_creek_epsg2277.tif",
            ...     project_crs="EPSG:2277",
            ...     geom_path="MAHA CREEK.g01",
            ...     hec_terrain_hdf="Terrain/hec-6.6/Terrain.hdf",
            ...     hecras_version="6.6",
            ... )
            >>> receipt["resolution"]["value"], receipt["resolution"]["multiple"]
            (6.5616666666666665, 2)
            >>> receipt["nodata"]["inside_aoi_count"]
            0
            >>> receipt["hec_terrain"]["source_member_count"]
            1
        """
        output_raster = Path(output_raster)
        receipt_path = (
            Path(receipt_path)
            if receipt_path is not None
            else output_raster.with_name(f"{output_raster.stem}.terrain_receipt.json")
        )

        if output_raster.exists() and not overwrite:
            raise FileExistsError(
                f"Output raster already exists (pass overwrite=True): {output_raster}"
            )

        invalid_backfill = [res for res in backfill_resolutions if res not in Usgs3depAws.SEAMLESS_PRODUCTS]
        if invalid_backfill:
            raise ValueError(
                "backfill_resolutions may only contain "
                f"{sorted(Usgs3depAws.SEAMLESS_PRODUCTS)}, got {invalid_backfill}"
            )

        if target_resolution is not None and not target_resolution > 0:
            raise ValueError(f"target_resolution must be positive, got {target_resolution}")

        if not minimum_cell_size > 0:
            raise ValueError(f"minimum_cell_size must be positive, got {minimum_cell_size}")

        horizontal_unit, _ = Usgs3depAws._crs_linear_unit(project_crs)
        vertical_unit = Usgs3depAws._normalize_linear_unit(vertical_unit or horizontal_unit)
        vertical_scale_factor = float(1 / Usgs3depAws.LINEAR_UNIT_METRES[vertical_unit])

        aoi, aoi_report = Usgs3depAws._build_terrain_aoi(
            project_crs,
            geom_path=geom_path,
            aoi_geometry=aoi_geometry,
            buffer_distance=buffer_distance,
            buffer_units=buffer_units,
        )

        output_raster.parent.mkdir(parents=True, exist_ok=True)
        download_folder = (
            Path(download_folder)
            if download_folder is not None
            else output_raster.parent / "source-tiles"
        )
        work_dir = output_raster.parent / f".{output_raster.stem}.work"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)

        tiers: List[Dict[str, Any]] = [
            {"tier": 1, "product": "3dep_1m_project", "requested_resolution": 1},
        ] + [
            {
                "tier": position + 2,
                "product": Usgs3depAws.SEAMLESS_PRODUCTS[resolution][1],
                "requested_resolution": resolution,
            }
            for position, resolution in enumerate(backfill_resolutions)
        ]

        aoi_centroid = aoi.representative_point()
        aoi_wgs84 = Usgs3depAws._geometry_to_wgs84(aoi, project_crs)

        used_tiers: List[Dict[str, Any]] = []
        analysis_cell: Optional[Fraction] = None
        analysis_resolution: Optional[float] = None
        gate: Optional[Dict[str, Any]] = None
        composite_path: Optional[Path] = None
        gdalwarp_path: Optional[Path] = None

        try:
            for tier in tiers:
                if gate is not None and gate["nodata_pixel_count"] == 0:
                    tier.update(status="not_required", tiles=[], projects=[])
                    continue

                tier_folder = download_folder / tier["product"]

                if tier["requested_resolution"] == 1:
                    tier_paths, tier_provenance = Usgs3depAws.download_tiles(
                        aoi_wgs84.convex_hull,
                        1,
                        tier_folder,
                        cache_folder,
                        max_workers=max_workers,
                        project_selection="coverage",
                        return_provenance=True,
                        exclude_tile_ids=exclude_tile_ids,
                    )
                else:
                    if gate is None:
                        request_bounds = aoi_wgs84.bounds
                    else:
                        request_bounds = Usgs3depAws._bounds_to_wgs84(
                            gate["nodata_bounds"], project_crs
                        )
                    tier_paths, tier_provenance = Usgs3depAws._download_seamless_tiles(
                        request_bounds,
                        tier["requested_resolution"],
                        tier_folder,
                        max_workers=max_workers,
                        exclude_tile_ids=exclude_tile_ids,
                    )

                tier["tiles"] = tier_provenance
                tier["projects"] = sorted(
                    {record["project_name"] for record in tier_provenance if record["project_name"]}
                )
                tier["project_folders"] = sorted(
                    {record.get("project_folder") for record in tier_provenance if record.get("project_folder")}
                )

                if not tier_paths:
                    tier["status"] = "no_sources"
                    logger.warning(
                        f"USGS 3DEP terrain tier {tier['tier']} ({tier['product']}) "
                        "supplied no tiles"
                    )
                    continue

                tier["paths"] = [Path(path) for path in tier_paths]
                tier.update(
                    Usgs3depAws._native_resolution_in_crs_units(
                        tier["paths"][-1], project_crs, aoi_centroid
                    )
                )
                tier["status"] = "used"
                used_tiers.append(tier)

                if analysis_cell is None:
                    # Provisional grid: the first tier with data is assumed to
                    # be dominant until the contributions are known.
                    analysis_cell, _ = Usgs3depAws._cell_size_for_dominant(
                        tier["_native_resolution_exact"],
                        minimum_cell_size,
                        target_resolution,
                    )
                    analysis_resolution = float(analysis_cell)

                uncovered_before = None if gate is None else gate["nodata_pixel_count"]

                composite_path, gdalwarp_path = Usgs3depAws._composite_terrain_sources(
                    used_tiers,
                    work_dir / f"composite_tier{tier['tier']}.tif",
                    project_crs,
                    analysis_resolution,
                    aoi.bounds,
                    resampling_method=resampling_method,
                    src_nodata=src_nodata,
                    nodata=nodata,
                    hecras_version=hecras_version,
                    timeout_seconds=timeout_seconds,
                    previous_composite=composite_path,
                )
                gate = Usgs3depAws._count_nodata_in_aoi(composite_path, aoi, nodata)

                if uncovered_before is None:
                    uncovered_before = gate["aoi_pixel_count"]
                tier["contributed_aoi_pixels"] = int(uncovered_before - gate["nodata_pixel_count"])
                tier["analysis_resolution"] = analysis_resolution

            if not used_tiers:
                details = {"aoi": aoi_report}
                Usgs3depAws._write_terrain_receipt(
                    receipt_path,
                    Usgs3depAws._terrain_receipt(
                        "fail", Usgs3depAws.TERRAIN_REASON_NO_SOURCES, output_raster,
                        project_crs, horizontal_unit, vertical_unit,
                        vertical_scale_factor, aoi_report, tiers,
                    ),
                )
                raise TerrainBuildError(
                    Usgs3depAws.TERRAIN_REASON_NO_SOURCES,
                    "No USGS 3DEP tier supplied any tile for the AOI",
                    details,
                )

            aoi_pixel_count = gate["aoi_pixel_count"]
            for tier in used_tiers:
                tier["contributed_aoi_area"] = tier["contributed_aoi_pixels"] * analysis_resolution ** 2
                tier["contributed_aoi_fraction"] = (
                    tier["contributed_aoi_pixels"] / aoi_pixel_count if aoi_pixel_count else 0.0
                )

            dominant = max(
                used_tiers,
                key=lambda item: (item["contributed_aoi_pixels"], -item["tier"]),
            )
            cell, resolution_report = Usgs3depAws._cell_size_for_dominant(
                dominant["_native_resolution_exact"],
                minimum_cell_size,
                target_resolution,
            )
            resolution = float(cell)
            resolution_report.update(
                units=horizontal_unit,
                dominant_tier=dominant["tier"],
                dominant_product=dominant["product"],
                dominant_contributed_aoi_fraction=dominant["contributed_aoi_fraction"],
                analysis_resolution=analysis_resolution,
                resampling=resampling_method,
            )
            if resolution_report["chosen_by"] == "minimum_cell_size_rule":
                rule_text = f"the smallest integer multiple >= minimum_cell_size {minimum_cell_size!r}"
            else:
                rule_text = f"from target_resolution {target_resolution!r}"
            resolution_report["reason"] = (
                f"{resolution_report['multiple']} x the native resolution of tier "
                f"{dominant['tier']} ({dominant['product']}: "
                f"{dominant['native_resolution_source_units']} "
                f"{dominant['native_resolution_source_unit']} = "
                f"{resolution_report['dominant_resolution']!r} {horizontal_unit}), which "
                f"contributes the most AOI area ({dominant['contributed_aoi_fraction']:.2%}); "
                f"{rule_text}"
            )

            if cell != analysis_cell:
                composite_path, gdalwarp_path = Usgs3depAws._composite_terrain_sources(
                    used_tiers,
                    work_dir / "composite_final.tif",
                    project_crs,
                    resolution,
                    aoi.bounds,
                    resampling_method=resampling_method,
                    src_nodata=src_nodata,
                    nodata=nodata,
                    hecras_version=hecras_version,
                    timeout_seconds=timeout_seconds,
                    previous_composite=composite_path,
                )
                gate = Usgs3depAws._count_nodata_in_aoi(composite_path, aoi, nodata)

            if gate["nodata_pixel_count"] > 0:
                receipt = Usgs3depAws._terrain_receipt(
                    "fail", Usgs3depAws.TERRAIN_REASON_AOI_NODATA, output_raster,
                    project_crs, horizontal_unit, vertical_unit,
                    vertical_scale_factor, aoi_report, tiers,
                    resolution=resolution_report, gate=gate,
                    nodata=nodata, resampling_method=resampling_method,
                    gdalwarp_path=gdalwarp_path,
                )
                Usgs3depAws._write_terrain_receipt(receipt_path, receipt)
                raise TerrainBuildError(
                    Usgs3depAws.TERRAIN_REASON_AOI_NODATA,
                    f"{gate['nodata_pixel_count']} nodata pixel(s) remain inside the buffered "
                    f"AOI after exhausting backfill; bounds {gate['nodata_bounds']}",
                    {
                        "nodata_pixel_count": gate["nodata_pixel_count"],
                        "nodata_bounds": gate["nodata_bounds"],
                        "nodata_samples": gate["nodata_samples"],
                        "receipt_path": str(receipt_path),
                    },
                )

            partial = output_raster.with_name(f"{output_raster.stem}.partial{output_raster.suffix}")
            Usgs3depAws._scale_raster_values(
                composite_path, partial, vertical_scale_factor, nodata, vertical_unit
            )
            partial.replace(output_raster)

            final_gate = Usgs3depAws._count_nodata_in_aoi(output_raster, aoi, nodata)
            if final_gate["nodata_pixel_count"] != gate["nodata_pixel_count"]:
                raise RuntimeError(
                    "Vertical scaling changed the nodata-inside-AOI count "
                    f"({gate['nodata_pixel_count']} -> {final_gate['nodata_pixel_count']})"
                )

            receipt = Usgs3depAws._terrain_receipt(
                "pass", Usgs3depAws.TERRAIN_REASON_VALID, output_raster,
                project_crs, horizontal_unit, vertical_unit,
                vertical_scale_factor, aoi_report, tiers,
                resolution=resolution_report, gate=final_gate,
                nodata=nodata, resampling_method=resampling_method,
                gdalwarp_path=gdalwarp_path,
            )

            if hec_terrain_hdf is not None:
                receipt["hec_terrain"] = Usgs3depAws._build_single_source_hec_terrain(
                    output_raster,
                    hec_terrain_hdf,
                    project_crs,
                    vertical_unit,
                    hecras_version,
                    timeout_seconds=timeout_seconds,
                )
                if receipt["hec_terrain"]["source_member_count"] != 1:
                    receipt["status"] = "fail"
                    receipt["reason_code"] = Usgs3depAws.TERRAIN_REASON_HEC_MULTI_SOURCE
                    Usgs3depAws._write_terrain_receipt(receipt_path, receipt)
                    raise TerrainBuildError(
                        Usgs3depAws.TERRAIN_REASON_HEC_MULTI_SOURCE,
                        "HEC-RAS Terrain.vrt has "
                        f"{receipt['hec_terrain']['source_member_count']} source members; "
                        "RASMapper results would mirror a multi-raster terrain",
                        {"hec_terrain": receipt["hec_terrain"], "receipt_path": str(receipt_path)},
                    )

            Usgs3depAws._write_terrain_receipt(receipt_path, receipt)
            logger.info(
                f"USGS 3DEP terrain raster built: {output_raster.name} "
                f"({resolution:.10g} {horizontal_unit}, 0 nodata pixels inside AOI)"
            )
            return receipt

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _normalize_linear_unit(unit: str) -> str:
        """
        Normalize a linear unit name to a key of ``LINEAR_UNIT_METRES``.

        Args:
            unit: Unit name such as ``"US survey foot"``, ``"ftUS"``,
                ``"foot"``, ``"ft"``, ``"metre"``, or ``"meter"``.

        Returns:
            ``"us survey foot"``, ``"foot"``, or ``"metre"``.

        Raises:
            ValueError: If the unit is not recognized.
        """
        key = str(unit).strip().lower().replace("_", " ")
        aliases = {
            "us survey foot": "us survey foot",
            "us survey feet": "us survey foot",
            "ftus": "us survey foot",
            "us-ft": "us survey foot",
            "foot us": "us survey foot",
            "foot": "foot",
            "feet": "foot",
            "ft": "foot",
            "international foot": "foot",
            "metre": "metre",
            "meter": "metre",
            "metres": "metre",
            "meters": "metre",
            "m": "metre",
        }
        if key not in aliases:
            raise ValueError(f"Unsupported linear unit: {unit!r}")
        return aliases[key]

    @staticmethod
    def _crs_linear_unit(crs: Any) -> Tuple[str, Fraction]:
        """
        Return the normalized linear unit of a projected CRS and its metres.

        Args:
            crs: Anything ``pyproj.CRS.from_user_input`` accepts.

        Returns:
            ``(unit_key, metres_per_unit)``, using exact factors for metre,
            US survey foot, and international foot.

        Raises:
            ValueError: If the CRS is not projected or its unit is unsupported.
        """
        from pyproj import CRS

        crs = CRS.from_user_input(crs)
        if not crs.is_projected:
            raise ValueError(f"CRS must be projected, got {crs.name!r}")

        unit = Usgs3depAws._normalize_linear_unit(crs.axis_info[0].unit_name)
        return unit, Usgs3depAws.LINEAR_UNIT_METRES[unit]

    @staticmethod
    def _build_terrain_aoi(
        project_crs: str,
        geom_path: Optional[Union[str, Path]] = None,
        aoi_geometry: Optional[Any] = None,
        buffer_distance: float = 100.0,
        buffer_units: str = "US survey foot",
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Build the buffered model extent polygon in project CRS.

        For ``geom_path`` the extent is the model footprint unioned with every
        cross-section cut line before buffering, because the 1D footprint is
        built from river edge lines and cross sections can protrude past it.

        Args:
            project_crs: Projected CRS of the project.
            geom_path: Model geometry (``.g##`` or ``.g##.hdf``).
            aoi_geometry: Model extent geometry in project CRS.
            buffer_distance: Absolute buffer distance.
            buffer_units: ``"project"`` or a unit name understood by
                ``_normalize_linear_unit``.

        Returns:
            ``(aoi_polygon, aoi_report)``.

        Raises:
            ValueError: If not exactly one extent source is given, the buffer
                is negative, or the AOI has no area.
        """
        from shapely.ops import unary_union

        if (geom_path is None) == (aoi_geometry is None):
            raise ValueError("Provide exactly one of geom_path or aoi_geometry")

        _, project_unit_metres = Usgs3depAws._crs_linear_unit(project_crs)
        if str(buffer_units).strip().lower() == "project":
            distance = float(buffer_distance)
            buffer_unit_label = "project"
        else:
            buffer_unit_label = Usgs3depAws._normalize_linear_unit(buffer_units)
            distance = float(
                Fraction(float(buffer_distance))
                * Usgs3depAws.LINEAR_UNIT_METRES[buffer_unit_label]
                / project_unit_metres
            )

        if distance < 0:
            raise ValueError(f"buffer_distance must not be negative, got {buffer_distance}")

        report: Dict[str, Any] = {
            "source": "geometry" if geom_path is not None else "caller_geometry",
            "geom_path": str(geom_path) if geom_path is not None else None,
            "buffer_distance": float(buffer_distance),
            "buffer_units": buffer_unit_label,
            "buffer_distance_project_units": distance,
        }

        if geom_path is not None:
            from ..geom.GeomParser import GeomParser
            from ..hdf.HdfProject import HdfProject

            footprint_gdf, _ = HdfProject.get_project_extent(
                geom_path=geom_path,
                fallback_to_plaintext=True,
                geometry_type="footprint",
                buffer_percent=0.0,
            )
            footprint_parts = [
                geometry for geometry in footprint_gdf.geometry
                if geometry is not None and not geometry.is_empty
            ]

            text_geom_path = Path(geom_path)
            if text_geom_path.suffix.lower() == ".hdf":
                text_geom_path = text_geom_path.with_suffix("")
            cut_lines = []
            if text_geom_path.exists():
                cut_lines = [
                    geometry for geometry in GeomParser.get_xs_cut_lines(text_geom_path).geometry
                    if geometry is not None and not geometry.is_empty
                ]

            footprint = unary_union(footprint_parts) if footprint_parts else None
            report["footprint_crs"] = str(footprint_gdf.crs) if footprint_gdf.crs else None
            report["cross_section_count"] = len(cut_lines)
            report["cross_sections_outside_footprint"] = sum(
                1 for line in cut_lines if footprint is None or not footprint.covers(line)
            )
            extent = unary_union(footprint_parts + cut_lines)
        else:
            extent = aoi_geometry

        aoi = extent.buffer(distance) if distance > 0 else extent.buffer(0)
        if aoi.is_empty or aoi.area <= 0:
            raise ValueError("The buffered AOI has no area")

        report["area_project_units"] = aoi.area
        report["bounds"] = list(aoi.bounds)
        return aoi, report

    @staticmethod
    def _geometry_to_wgs84(geometry: Any, crs: str) -> Any:
        """Densify and reproject a project-CRS geometry to EPSG:4326."""
        import shapely

        minx, miny, maxx, maxy = geometry.bounds
        spacing = max(maxx - minx, maxy - miny) / 200.0 or 1.0
        densified = shapely.segmentize(geometry, spacing)
        return gpd.GeoSeries([densified], crs=crs).to_crs("EPSG:4326").iloc[0]

    @staticmethod
    def _bounds_to_wgs84(
        bounds: Sequence[float],
        crs: str,
    ) -> Tuple[float, float, float, float]:
        """Reproject project-CRS bounds to an enclosing EPSG:4326 envelope."""
        from pyproj import Transformer

        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        return tuple(transformer.transform_bounds(*bounds, densify_pts=21))

    @staticmethod
    def _seamless_tile_names(
        bounds_wgs84: Sequence[float],
        resolution: int,
    ) -> List[str]:
        """
        List the seamless 1-degree tile ids covering WGS84 bounds.

        Seamless 3DEP tiles are named by their NORTH-WEST corner, e.g.
        ``USGS_13_n31w098`` covers latitude 30-31 and longitude -98 to -97.

        Args:
            bounds_wgs84: ``(min_lon, min_lat, max_lon, max_lat)``.
            resolution: ``10`` (1/3 arc-second) or ``30`` (1 arc-second).

        Returns:
            Tile ids such as ``["USGS_13_n31w098"]``, north to south, west to
            east.
        """
        token = Usgs3depAws.SEAMLESS_PRODUCTS[resolution][0]
        min_lon, min_lat, max_lon, max_lat = bounds_wgs84
        names = []

        for north in range(math.floor(max_lat) + 1, math.floor(min_lat), -1):
            for west in range(math.floor(min_lon), math.floor(max_lon) + 1):
                lat_part = f"{'n' if north >= 0 else 's'}{abs(north):02d}"
                lon_part = f"{'w' if west < 0 else 'e'}{abs(west):03d}"
                names.append(f"USGS_{token}_{lat_part}{lon_part}")

        return names

    @staticmethod
    def _download_seamless_tiles(
        bounds_wgs84: Sequence[float],
        resolution: int,
        output_folder: Union[str, Path],
        max_workers: int = 3,
        exclude_tile_ids: Optional[Sequence[str]] = None,
    ) -> Tuple[List[Path], List[Dict[str, Any]]]:
        """
        Download seamless 1/3 or 1 arc-second tiles covering WGS84 bounds.

        Args:
            bounds_wgs84: ``(min_lon, min_lat, max_lon, max_lat)``.
            resolution: ``10`` or ``30``.
            output_folder: Download folder (cached tiles are reused).
            max_workers: Concurrent HEAD requests for provenance.
            exclude_tile_ids: Tile ids to withhold.

        Returns:
            ``(tile_paths, provenance)``. Tiles that do not exist on S3 (for
            example over open water) are skipped.
        """
        token, product = Usgs3depAws.SEAMLESS_PRODUCTS[resolution]
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        excluded = set(exclude_tile_ids or [])

        downloaded: List[Tuple[str, Path]] = []
        for tile_id in Usgs3depAws._seamless_tile_names(bounds_wgs84, resolution):
            if tile_id in excluded:
                logger.debug(f"Excluding USGS 3DEP tile by request: {tile_id}")
                continue

            folder = tile_id.split("_")[-1]
            tile_url = f"{Usgs3depAws.S3_BASE_URL}/{token}/TIFF/current/{folder}/{tile_id}.tif"

            if Usgs3depAws._get_remote_file_size(tile_url) is None:
                logger.debug(f"USGS 3DEP seamless tile not available: {tile_url}")
                continue

            tile_path = Usgs3depAws._download_single_tile(tile_url, output_folder, False)
            if tile_path:
                downloaded.append((tile_url, Path(tile_path)))

        provenance = Usgs3depAws._collect_tile_provenance(
            [{"project_name": product, "project_year": None, "tiles": downloaded}],
            max_workers=max_workers,
        )
        return [tile_path for _, tile_path in downloaded], provenance

    @staticmethod
    def _native_resolution_in_crs_units(
        raster_path: Union[str, Path],
        project_crs: str,
        reference_point: Any,
    ) -> Dict[str, Any]:
        """
        Convert a source raster's native cell size into project CRS units.

        Projected sources convert by exact linear-unit ratio (1m becomes
        3.2808333333333333 US survey feet). Geographic sources convert by the
        geodesic length of one cell at ``reference_point``, averaged over both
        axes.

        Args:
            raster_path: A source raster of the tier.
            project_crs: Projected CRS of the project.
            reference_point: Shapely point in project CRS, typically inside
                the AOI.

        Returns:
            Dict with ``native_resolution_source_units``,
            ``native_resolution_source_unit``, ``native_resolution_source_crs``,
            ``native_resolution_project_units`` (float), and
            ``_native_resolution_exact`` (``fractions.Fraction``, kept out of
            receipts).
        """
        import rasterio
        from pyproj import CRS, Transformer

        with rasterio.open(raster_path) as src:
            res_x, res_y = (abs(value) for value in src.res)
            source_crs = CRS.from_wkt(src.crs.to_wkt())

        _, project_unit_metres = Usgs3depAws._crs_linear_unit(project_crs)

        if source_crs.is_projected:
            source_unit, source_unit_metres = Usgs3depAws._crs_linear_unit(source_crs)
            source_resolution = (res_x + res_y) / 2.0
            exact_resolution = Fraction(source_resolution) * source_unit_metres / project_unit_metres
        else:
            source_unit = "degree"
            source_resolution = (res_x + res_y) / 2.0
            transformer = Transformer.from_crs(project_crs, source_crs, always_xy=True)
            lon, lat = transformer.transform(reference_point.x, reference_point.y)
            geod = source_crs.get_geod()
            _, _, dx = geod.inv(lon, lat, lon + res_x, lat)
            _, _, dy = geod.inv(lon, lat, lon, lat + res_y)
            exact_resolution = Fraction((dx + dy) / 2.0) / project_unit_metres

        return {
            "native_resolution_source_units": source_resolution,
            "native_resolution_source_unit": source_unit,
            "native_resolution_source_crs": source_crs.to_string(),
            "native_resolution_project_units": float(exact_resolution),
            "_native_resolution_exact": exact_resolution,
        }

    @staticmethod
    def _cell_size_for_dominant(
        dominant_resolution: Union[Fraction, float],
        minimum_cell_size: float = 5.0,
        target_resolution: Optional[float] = None,
    ) -> Tuple[Fraction, Dict[str, Any]]:
        """
        Choose the output cell size as an integer multiple of the dominant resolution.

        Default rule: ``k`` is the smallest integer >= 1 with
        ``k * dominant_resolution >= minimum_cell_size``. With
        ``target_resolution`` the multiple is instead the nearest integer
        (at least 1) to ``target_resolution / dominant_resolution``; a request
        that is not already an integer multiple is snapped with a logged
        warning rather than rejected, because the dominant resolution is only
        known after the sources are downloaded. All arithmetic uses exact
        fractions.

        Args:
            dominant_resolution: Dominant native resolution in project units.
            minimum_cell_size: Minimum cell size in project units.
            target_resolution: Optional caller-requested cell size.

        Returns:
            ``(cell_size_exact, report)``; the report holds ``value``,
            ``multiple``, ``dominant_resolution``, ``minimum_cell_size``,
            ``requested_resolution``, ``snapped``, and ``chosen_by``
            (``"minimum_cell_size_rule"``, ``"override"``, or
            ``"override_snapped"``).

        Raises:
            ValueError: If a size is not positive.

        Example:
            >>> cell, report = Usgs3depAws._cell_size_for_dominant(Fraction(3937, 1200), 5.0)
            >>> report["multiple"], float(cell)
            (2, 6.5616666666666665)
        """
        dominant = Fraction(dominant_resolution)
        minimum = Fraction(minimum_cell_size)
        if dominant <= 0 or minimum <= 0:
            raise ValueError("dominant_resolution and minimum_cell_size must be positive")

        snapped = False
        if target_resolution is None:
            multiple = max(1, math.ceil(minimum / dominant))
            chosen_by = "minimum_cell_size_rule"
        else:
            requested = Fraction(target_resolution)
            if requested <= 0:
                raise ValueError(f"target_resolution must be positive, got {target_resolution}")
            multiple = max(1, math.floor(requested / dominant + Fraction(1, 2)))
            exact = multiple * dominant
            snapped = abs(exact - requested) > requested * Fraction(1, 10**9)
            chosen_by = "override_snapped" if snapped else "override"
            if snapped:
                logger.warning(
                    f"target_resolution {target_resolution!r} is not an integer multiple of the "
                    f"dominant resolution {float(dominant)!r}; snapped to {multiple} x = "
                    f"{float(exact)!r}"
                )

        cell = multiple * dominant
        return cell, {
            "value": float(cell),
            "multiple": multiple,
            "dominant_resolution": float(dominant),
            "minimum_cell_size": float(minimum_cell_size),
            "requested_resolution": None if target_resolution is None else float(target_resolution),
            "snapped": snapped,
            "chosen_by": chosen_by,
        }

    @staticmethod
    def _snap_bounds_outward(
        bounds: Sequence[float],
        resolution: float,
    ) -> Tuple[float, float, float, float]:
        """Snap bounds outward to whole multiples of ``resolution`` (as -tap does)."""
        minx, miny, maxx, maxy = bounds
        return (
            math.floor(minx / resolution) * resolution,
            math.floor(miny / resolution) * resolution,
            math.ceil(maxx / resolution) * resolution,
            math.ceil(maxy / resolution) * resolution,
        )

    @staticmethod
    def _composite_terrain_sources(
        tiers: Sequence[Dict[str, Any]],
        output_path: Union[str, Path],
        project_crs: str,
        resolution: float,
        aoi_bounds: Sequence[float],
        resampling_method: str = "bilinear",
        src_nodata: Optional[float] = None,
        nodata: float = -9999.0,
        hecras_version: Optional[str] = None,
        timeout_seconds: int = 7200,
        previous_composite: Optional[Union[str, Path]] = None,
    ) -> Tuple[Path, Path]:
        """
        Composite every tier's sources in ONE HEC-RAS bundled gdalwarp call.

        Sources are passed lowest priority first and highest last, so a valid
        higher-priority pixel always overwrites lower-priority data.

        Args:
            tiers: Used tiers, highest priority first, each with ``paths``
                (already oldest project first within the tier).
            output_path: Composite GeoTIFF to write.
            project_crs: Target CRS.
            resolution: Target cell size in project CRS units.
            aoi_bounds: AOI bounds in project CRS; snapped outward.
            resampling_method: gdalwarp ``-r`` value.
            src_nodata: Optional ``-srcnodata`` override.
            nodata: ``-dstnodata`` value.
            hecras_version: HEC-RAS version for GDAL discovery.
            timeout_seconds: Subprocess timeout.
            previous_composite: Earlier probe composite to delete first.

        Returns:
            ``(composite_path, gdalwarp_path)``

        Raises:
            FileNotFoundError: If HEC-RAS bundled gdalwarp.exe is not found.
            RuntimeError: If gdalwarp fails or writes nothing.
        """
        from .RasTerrain import RasTerrain

        output_path = Path(output_path)
        if previous_composite is not None:
            Path(previous_composite).unlink(missing_ok=True)

        try:
            gdalwarp = Usgs3depAws._find_gdalwarp_path(hecras_version)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Building a terrain raster requires HEC-RAS bundled gdalwarp.exe. "
                f"{exc}"
            ) from exc

        sources = [
            str(path)
            for tier in reversed(list(tiers))
            for path in tier["paths"]
        ]
        target_bounds = Usgs3depAws._snap_bounds_outward(aoi_bounds, resolution)

        cmd = [
            str(gdalwarp),
            "-overwrite",
            "-of", "GTiff",
            "-ot", "Float32",
            "-t_srs", project_crs,
            "-tr", repr(float(resolution)), repr(float(resolution)),
            "-tap",
            "-te", *[repr(float(value)) for value in target_bounds],
            "-r", resampling_method,
        ]
        if src_nodata is not None:
            cmd += ["-srcnodata", repr(float(src_nodata))]
        cmd += [
            "-dstnodata", repr(float(nodata)),
            "-wm", "1024",
            "-multi",
            "-wo", "NUM_THREADS=ALL_CPUS",
            "-co", "TILED=YES",
            "-co", "COMPRESS=DEFLATE",
            "-co", "PREDICTOR=3",
            "-co", "BIGTIFF=IF_SAFER",
            *sources,
            str(output_path),
        ]
        logger.debug(f"gdalwarp terrain composite command: {cmd}")

        env = RasTerrain._build_hecras_terrain_env(gdalwarp.parents[2])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("gdalwarp timed out while compositing the terrain raster.") from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to execute gdalwarp: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"gdalwarp failed with code {result.returncode}. STDERR: {result.stderr}"
            )
        if not output_path.exists():
            raise RuntimeError(f"gdalwarp completed but did not write {output_path}")

        return output_path, gdalwarp

    @staticmethod
    def _count_nodata_in_aoi(
        raster_path: Union[str, Path],
        aoi: Any,
        nodata: float,
        max_samples: int = 10,
        window_size: int = 4096,
    ) -> Dict[str, Any]:
        """
        Count nodata pixels inside the AOI polygon, window by window.

        A pixel is inside when it touches the AOI polygon (rasterized with
        ``all_touched=True``), which is stricter than a centre-in-polygon
        rule. Pixels inside the raster's bounding rectangle but outside the
        polygon are ignored. NaN counts as nodata.

        Args:
            raster_path: Raster to check.
            aoi: AOI polygon in the raster CRS.
            nodata: Nodata value.
            max_samples: Maximum nodata pixel-centre samples to report.
            window_size: Processing window edge in pixels.

        Returns:
            Dict with ``aoi_pixel_count``, ``nodata_pixel_count``,
            ``nodata_bounds`` (pixel-edge bounds of the uncovered pixels, or
            None), ``nodata_samples`` (``[x, y]`` pixel centres), and ``rule``.
        """
        import numpy as np
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.windows import Window

        aoi_pixels = 0
        nodata_pixels = 0
        samples: List[List[float]] = []
        nodata_bounds: Optional[List[float]] = None

        with rasterio.open(raster_path) as src:
            res_x, res_y = src.res
            for row_off in range(0, src.height, window_size):
                for col_off in range(0, src.width, window_size):
                    window = Window(
                        col_off,
                        row_off,
                        min(window_size, src.width - col_off),
                        min(window_size, src.height - row_off),
                    )
                    window_transform = src.window_transform(window)
                    inside = geometry_mask(
                        [aoi],
                        out_shape=(int(window.height), int(window.width)),
                        transform=window_transform,
                        all_touched=True,
                        invert=True,
                    )
                    if not inside.any():
                        continue

                    data = src.read(1, window=window)
                    missing = inside & ((data == np.float32(nodata)) | ~np.isfinite(data))
                    aoi_pixels += int(inside.sum())
                    count = int(missing.sum())
                    if not count:
                        continue

                    nodata_pixels += count
                    rows, cols = np.nonzero(missing)
                    xs, ys = rasterio.transform.xy(window_transform, rows, cols)
                    xs = np.asarray(xs, dtype=float)
                    ys = np.asarray(ys, dtype=float)
                    window_bounds = [
                        float(xs.min() - res_x / 2), float(ys.min() - res_y / 2),
                        float(xs.max() + res_x / 2), float(ys.max() + res_y / 2),
                    ]
                    if nodata_bounds is None:
                        nodata_bounds = window_bounds
                    else:
                        nodata_bounds = [
                            min(nodata_bounds[0], window_bounds[0]),
                            min(nodata_bounds[1], window_bounds[1]),
                            max(nodata_bounds[2], window_bounds[2]),
                            max(nodata_bounds[3], window_bounds[3]),
                        ]
                    for x, y in zip(xs[: max_samples - len(samples)], ys[: max_samples - len(samples)]):
                        samples.append([float(x), float(y)])

        return {
            "aoi_pixel_count": aoi_pixels,
            "nodata_pixel_count": nodata_pixels,
            "nodata_bounds": nodata_bounds,
            "nodata_samples": samples,
            "rule": "all_touched",
        }

    @staticmethod
    def _scale_raster_values(
        source_path: Union[str, Path],
        output_path: Union[str, Path],
        scale_factor: float,
        nodata: float,
        vertical_unit: str,
        window_size: int = 4096,
    ) -> Path:
        """
        Write a copy of a single-band raster with valid values scaled.

        Nodata and non-finite pixels stay ``nodata``; every other pixel is
        multiplied by ``scale_factor``. Georeferencing is copied unchanged.

        Args:
            source_path: Composite in source vertical units.
            output_path: Scaled GeoTIFF to write.
            scale_factor: Multiplier, e.g. 3.2808333333333333 for metres to
                US survey feet.
            nodata: Nodata value.
            vertical_unit: Unit recorded on the output band.
            window_size: Processing window edge in pixels.

        Returns:
            ``output_path``
        """
        import numpy as np
        import rasterio
        from rasterio.windows import Window

        output_path = Path(output_path)

        with rasterio.open(source_path) as src:
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                dtype="float32",
                nodata=nodata,
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress="deflate",
                predictor=3,
                BIGTIFF="IF_SAFER",
            )
            with rasterio.open(output_path, "w", **profile) as dst:
                for row_off in range(0, src.height, window_size):
                    for col_off in range(0, src.width, window_size):
                        window = Window(
                            col_off,
                            row_off,
                            min(window_size, src.width - col_off),
                            min(window_size, src.height - row_off),
                        )
                        data = src.read(1, window=window)
                        valid = (data != np.float32(nodata)) & np.isfinite(data)
                        scaled = np.where(valid, data.astype("float64") * scale_factor, nodata)
                        dst.write(scaled.astype("float32"), 1, window=window)
                dst.units = (vertical_unit,)
                dst.update_tags(
                    1,
                    VERTICAL_DATUM=Usgs3depAws.SOURCE_VERTICAL_DATUM,
                    VERTICAL_UNIT=vertical_unit,
                    VERTICAL_SCALE_FACTOR=repr(scale_factor),
                )

        return output_path

    @staticmethod
    def _count_vrt_source_members(vrt_path: Union[str, Path]) -> List[str]:
        """
        List the source rasters a GDAL VRT references.

        Args:
            vrt_path: VRT file.

        Returns:
            The ``SourceFilename`` values, one per source member.
        """
        root = ET.parse(Path(vrt_path)).getroot()
        return [element.text or "" for element in root.iter("SourceFilename")]

    @staticmethod
    def _build_single_source_hec_terrain(
        raster_path: Union[str, Path],
        hec_terrain_hdf: Union[str, Path],
        project_crs: str,
        vertical_unit: str,
        hecras_version: Optional[str] = None,
        timeout_seconds: int = 7200,
    ) -> Dict[str, Any]:
        """
        Build a HEC-RAS terrain from one raster and report its VRT members.

        Args:
            raster_path: The single terrain raster.
            hec_terrain_hdf: Terrain HDF to create; its ``.vrt`` sibling is
                inspected.
            project_crs: CRS written to ``Projection.prj`` (ESRI WKT1).
            vertical_unit: Terrain elevation unit.
            hecras_version: HEC-RAS version for RasProcess.exe.
            timeout_seconds: RasProcess.exe CreateTerrain timeout.

        Returns:
            Dict with ``hdf``, ``vrt``, ``projection_prj``, ``build_seconds``,
            ``source_member_count``, and ``source_members``.
        """
        from pyproj import CRS

        from .RasTerrain import RasTerrain

        hec_terrain_hdf = Path(hec_terrain_hdf)
        hec_terrain_hdf.parent.mkdir(parents=True, exist_ok=True)
        projection_prj = hec_terrain_hdf.parent / "Projection.prj"
        projection_prj.write_text(CRS.from_user_input(project_crs).to_wkt("WKT1_ESRI"), encoding="utf-8")

        kwargs: Dict[str, Any] = {
            "input_rasters": [Path(raster_path)],
            "output_hdf": hec_terrain_hdf,
            "projection_prj": projection_prj,
            "units": "Meters" if vertical_unit == "metre" else "Feet",
            "stitch": False,
            "timeout_seconds": timeout_seconds,
        }
        if hecras_version is not None:
            kwargs["hecras_version"] = hecras_version

        started = datetime.now(timezone.utc)
        RasTerrain.create_terrain_hdf(**kwargs)
        build_seconds = (datetime.now(timezone.utc) - started).total_seconds()

        vrt_path = hec_terrain_hdf.with_suffix(".vrt")
        members = Usgs3depAws._count_vrt_source_members(vrt_path) if vrt_path.exists() else []

        return {
            "hdf": str(hec_terrain_hdf),
            "vrt": str(vrt_path),
            "projection_prj": str(projection_prj),
            "hecras_version": hecras_version,
            "stitch": False,
            "build_seconds": build_seconds,
            "source_member_count": len(members),
            "source_members": members,
        }

    @staticmethod
    def _terrain_receipt(
        status: str,
        reason_code: str,
        output_raster: Union[str, Path],
        project_crs: str,
        horizontal_unit: str,
        vertical_unit: str,
        vertical_scale_factor: float,
        aoi_report: Dict[str, Any],
        tiers: Sequence[Dict[str, Any]],
        resolution: Optional[Dict[str, Any]] = None,
        gate: Optional[Dict[str, Any]] = None,
        nodata: Optional[float] = None,
        resampling_method: Optional[str] = None,
        gdalwarp_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Assemble the JSON-serializable terrain build receipt."""
        output_raster = Path(output_raster)
        grid = None
        if status == "pass" and output_raster.exists():
            import rasterio

            with rasterio.open(output_raster) as src:
                grid = {
                    "origin_x": src.transform.c,
                    "origin_y": src.transform.f,
                    "resolution_x": src.res[0],
                    "resolution_y": src.res[1],
                    "width": src.width,
                    "height": src.height,
                    "bounds": list(src.bounds),
                    "crs_wkt": src.crs.to_wkt() if src.crs else None,
                }

        tier_records = []
        for tier in tiers:
            record = {
                key: value
                for key, value in tier.items()
                if key != "paths" and not key.startswith("_")
            }
            record.setdefault("status", "not_required")
            record.setdefault("tiles", [])
            record.setdefault("projects", [])
            tier_records.append(record)

        return {
            "schema": Usgs3depAws.TERRAIN_RECEIPT_SCHEMA,
            "version": "1.0.0",
            "status": status,
            "reason_code": reason_code,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_raster": str(output_raster),
            "format": "GeoTIFF",
            "single_raster": True,
            "target_crs": project_crs,
            "horizontal_unit": horizontal_unit,
            "vertical": {
                "datum": Usgs3depAws.SOURCE_VERTICAL_DATUM,
                "source_unit": Usgs3depAws.SOURCE_VERTICAL_UNIT,
                "target_unit": vertical_unit,
                "scale_factor": vertical_scale_factor,
                "method": "explicit_value_scaling",
            },
            "resolution": resolution,
            "grid": grid,
            "aoi": aoi_report,
            "nodata": {
                "value": nodata,
                "inside_aoi_count": None if gate is None else gate["nodata_pixel_count"],
                "aoi_pixel_count": None if gate is None else gate["aoi_pixel_count"],
                "nodata_bounds": None if gate is None else gate["nodata_bounds"],
                "nodata_samples": [] if gate is None else gate["nodata_samples"],
                "rule": "all_touched",
            },
            "composite": {
                "tool": str(gdalwarp_path) if gdalwarp_path else None,
                "resampling": resampling_method,
                "source_order": "lowest_priority_first",
            },
            "tiers": tier_records,
            "hec_terrain": None,
        }

    @staticmethod
    def _write_terrain_receipt(
        receipt_path: Union[str, Path],
        receipt: Dict[str, Any],
    ) -> Path:
        """Write a terrain receipt as indented JSON."""
        receipt_path = Path(receipt_path)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
        return receipt_path

    @staticmethod
    def _find_gdalbuildvrt_path(hecras_version: Optional[str] = None) -> Path:
        """
        Find HEC-RAS bundled gdalbuildvrt.exe.

        Args:
            hecras_version: Optional specific HEC-RAS version to use.

        Returns:
            Path to gdalbuildvrt.exe within the HEC-RAS GDAL folder.

        Raises:
            FileNotFoundError: If no supported HEC-RAS GDAL install is found.
        """
        return Usgs3depAws._find_gdal_tool_path("gdalbuildvrt.exe", hecras_version)

    @staticmethod
    def _find_gdalwarp_path(hecras_version: Optional[str] = None) -> Path:
        """
        Find HEC-RAS bundled gdalwarp.exe.

        Discovered exactly like gdalbuildvrt.exe so a reprojected mosaic uses
        the same GDAL build as the rest of the terrain workflow instead of an
        unrelated system GDAL.

        Args:
            hecras_version: Optional specific HEC-RAS version to use.

        Returns:
            Path to gdalwarp.exe within the HEC-RAS GDAL folder.

        Raises:
            FileNotFoundError: If no supported HEC-RAS GDAL install is found.
        """
        return Usgs3depAws._find_gdal_tool_path("gdalwarp.exe", hecras_version)

    @staticmethod
    def _find_gdal_tool_path(
        tool_name: str,
        hecras_version: Optional[str] = None,
    ) -> Path:
        """
        Find a HEC-RAS bundled GDAL executable by file name.

        Args:
            tool_name: Executable file name, e.g. ``"gdalbuildvrt.exe"``.
            hecras_version: Optional specific HEC-RAS version to use.

        Returns:
            Path to the executable within the HEC-RAS GDAL folder.

        Raises:
            FileNotFoundError: If no supported HEC-RAS GDAL install is found.
        """
        from .RasTerrain import RasTerrain

        searched_locations = []

        if hecras_version:
            install_dirs = [RasTerrain._get_hecras_path(hecras_version)]
        else:
            install_dirs = list(Usgs3depAws._iter_hecras_install_dirs())

        for install_dir in install_dirs:
            searched_locations.append(str(install_dir))
            gdal_tool = Usgs3depAws._find_gdal_tool_in_install_dir(install_dir, tool_name)
            if gdal_tool is not None:
                return gdal_tool

        searched_text = ", ".join(searched_locations) if searched_locations else "no HEC-RAS installs detected"
        raise FileNotFoundError(
            f"HEC-RAS bundled {tool_name} not found. "
            f"Searched: {searched_text}"
        )

    @staticmethod
    def _iter_hecras_install_dirs():
        """
        Yield installed HEC-RAS directories in descending version order.

        Uses RasTerrain's install discovery first, then falls back to a direct
        scan of the standard HEC-RAS base directories so point releases and
        new versions remain discoverable without code changes.
        """
        from .RasTerrain import RasTerrain

        seen = set()
        versions = sorted(
            set(RasTerrain.get_available_versions()),
            key=Usgs3depAws._version_sort_key,
            reverse=True,
        )

        for version in versions:
            try:
                install_dir = RasTerrain._get_hecras_path(version)
            except FileNotFoundError:
                continue

            resolved = install_dir.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield install_dir

        fallback_dirs = []
        for base_path in RasTerrain._HECRAS_BASE_PATHS:
            if not base_path.exists():
                continue
            for subdir in base_path.iterdir():
                if subdir.is_dir():
                    fallback_dirs.append(subdir)

        fallback_dirs.sort(
            key=lambda path: Usgs3depAws._version_sort_key(path.name),
            reverse=True,
        )

        for install_dir in fallback_dirs:
            resolved = install_dir.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield install_dir

    @staticmethod
    def _find_gdalbuildvrt_in_install_dir(install_dir: Union[str, Path]) -> Optional[Path]:
        """Return gdalbuildvrt.exe from a specific HEC-RAS install directory."""
        return Usgs3depAws._find_gdal_tool_in_install_dir(install_dir, "gdalbuildvrt.exe")

    @staticmethod
    def _find_gdal_tool_in_install_dir(
        install_dir: Union[str, Path],
        tool_name: str,
    ) -> Optional[Path]:
        """Return a named GDAL executable from a HEC-RAS install directory."""
        install_dir = Path(install_dir)
        gdal_paths = [
            install_dir / "GDAL" / "bin64",
            install_dir / "GDAL" / "bin",
            install_dir / "gdal" / "bin64",
            install_dir / "gdal" / "bin",
        ]

        for gdal_path in gdal_paths:
            gdal_tool = gdal_path / tool_name
            if gdal_tool.exists():
                return gdal_tool

        return None

    @staticmethod
    def _write_gdal_input_file_list(
        tile_paths: Sequence[Union[str, Path]],
        output_dir: Union[str, Path],
    ) -> Path:
        """Write a temporary GDAL input file list and return its path."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            suffix=".txt",
            prefix="gdalbuildvrt-input-",
            dir=output_dir,
            delete=False,
        ) as temp_file:
            for tile_path in tile_paths:
                temp_file.write(f"{tile_path}\n")

            return Path(temp_file.name)

    @staticmethod
    def _version_sort_key(version: str) -> Tuple[Tuple[int, ...], str]:
        """Sort HEC-RAS version strings numerically when possible."""
        numeric_parts = tuple(int(part) for part in re.findall(r"\d+", version))
        return numeric_parts, version.lower()
