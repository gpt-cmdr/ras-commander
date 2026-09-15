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
- Explicit target CRS, cell size, resampling, and nodata for the mosaic
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

    # Coverage-aware download plus provenance, mosaicked onto an explicit grid
    tiles, provenance = Usgs3depAws.download_tiles(
        bbox=bbox,
        resolution=1,
        output_folder="Terrain",
        project_selection="coverage",
        return_provenance=True,
    )
    vrt = Usgs3depAws.create_vrt(
        tiles,
        "terrain_2277.vrt",
        target_crs="EPSG:2277",          # NAD83 / Texas Central (US survey feet)
        target_resolution=10.0,          # 10-foot cells
        resampling_method="bilinear",
        src_nodata=-999999,
        vrt_nodata=-9999,
    )
"""

import logging
import re
import subprocess
import tempfile
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
logger = logging.getLogger(__name__)


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

    # Metadata URLs for each resolution (fallback)
    METADATA_URLS = {
        1: f"{S3_BASE_URL}/1m/FullExtentSpatialMetadata/FESM_1m.gpkg",
        10: f"{S3_BASE_URL}/13/FullExtentSpatialMetadata/FESM_13.gpkg",
        30: f"{S3_BASE_URL}/1/FullExtentSpatialMetadata/FESM_1.gpkg",
    }

    @staticmethod
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
    def _parse_tile_bounds_from_filename(filename: str) -> Optional[Tuple[float, float, float, float]]:
        """
        Parse WGS84 bounds from USGS 3DEP 1m DEM filename (instant, no file I/O).

        USGS 3DEP 1m tiles use a 10km × 10km UTM grid system with tile indices
        encoded in the filename. This method provides ~10,000x speedup vs opening
        remote files (500 microseconds vs 2-5 seconds per tile).

        Args:
            filename: e.g., 'USGS_1M_10_x37y351_PA_Northcentral_2019_B19.tif'

        Returns:
            (minx, miny, maxx, maxy) in WGS84 (EPSG:4326), or None if parsing fails

        Example:
            >>> bounds = _parse_tile_bounds_from_filename('USGS_1M_10_x37y351_PA_...')
            >>> print(bounds)
            (-77.123, 40.456, -77.012, 40.543)

        Note:
            Only works for USGS_1M_* files (1-meter products in UTM grid).
            Returns None for other resolutions (10m, 30m use lat/lon grid).
        """
        import re
        from pyproj import Transformer

        # Extract filename from path if needed
        if '/' in filename or '\\' in filename:
            filename = Path(filename).name

        # Parse filename: USGS_1M_{zone}_x{X}y{Y}_{rest}.tif
        pattern = r'USGS_1M_(\d+)_x(\d+)y(\d+)_'
        match = re.search(pattern, filename)

        if not match:
            return None  # Not a 1m DEM or invalid format

        try:
            utm_zone = int(match.group(1))
            x_index = int(match.group(2))
            y_index = int(match.group(3))

            # Validate zone (CONUS: 10-19, Hawaii: 4-5)
            if not (4 <= utm_zone <= 19):
                logger.debug(f"UTM zone {utm_zone} outside expected range (4-5, 10-19)")
                return None

            # Calculate UTM bounds (10km grid, meters)
            TILE_SIZE_M = 10000  # 10km = 10,000 meters

            utm_minx = x_index * TILE_SIZE_M
            utm_maxx = (x_index + 1) * TILE_SIZE_M
            utm_miny = y_index * TILE_SIZE_M
            utm_maxy = (y_index + 1) * TILE_SIZE_M

            # Get cached transformer for this zone
            transformer = Usgs3depAws._get_transformer(utm_zone)

            # Transform corners to WGS84
            minx, miny = transformer.transform(utm_minx, utm_miny)
            maxx, maxy = transformer.transform(utm_maxx, utm_maxy)

            return (minx, miny, maxx, maxy)

        except (ValueError, IndexError) as e:
            logger.debug(f"Error parsing tile coordinates from {filename}: {e}")
            return None

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
    ) -> Dict[str, Any]:
        """
        Build one provenance record for a downloaded or cached tile.

        Args:
            tile_url: Source URL the tile was downloaded from
            tile_path: Local path to the downloaded or cached tile
            project_name: USGS 3DEP project the tile belongs to
            project_year: Survey year of that project

        Returns:
            Dict with ``tile_id``, ``file_name``, ``file_path``,
            ``source_url``, ``project_name``, ``project_year``, ``etag``,
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
            (tile_url, tile_path, group['project_name'], group['project_year'])
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
        output_folder: Path,
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
        output_path = output_folder / filename

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

        Returns:
            List of paths to downloaded TIFF files, or, when
            ``return_provenance=True``, a ``(tile_paths, provenance)`` tuple.
            Each provenance record is a dict with ``tile_id``, ``file_name``,
            ``file_path``, ``source_url``, ``project_name``, ``project_year``,
            ``etag``, ``last_modified``, ``content_length``, and
            ``local_size_bytes``.

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

            for tile_url in tile_urls:
                filename = tile_url.split('/')[-1]

                try:
                    # Fast path: Parse bounds from filename (instant)
                    tile_bounds = Usgs3depAws._parse_tile_bounds_from_filename(filename)

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
    def create_vrt(
        tile_files: Sequence[Union[str, Path]],
        output_vrt: Union[str, Path],
        hecras_version: Optional[str] = None,
        *,
        target_crs: Optional[str] = None,
        target_resolution: Optional[Union[int, float, Tuple[float, float]]] = None,
        resampling_method: str = "bilinear",
        src_nodata: Optional[Union[int, float, str]] = None,
        vrt_nodata: Optional[Union[int, float, str]] = None,
        source_crs: Optional[str] = None,
    ) -> Path:
        """
        Create a Virtual Raster (VRT) mosaic from multiple tiles.

        By default the mosaic inherits the SRS and native cell size of the
        source tiles, which is only safe when every tile already shares one
        projection. USGS 3DEP 1m tiles are delivered per UTM zone, so a bbox
        that straddles a zone boundary produces tiles in two projections; use
        ``target_crs`` (optionally with ``target_resolution``) to state the
        grid the mosaic must land on instead of inheriting the first tile's.

        When ``target_crs`` is set, each tile is first reprojected to a warped
        VRT with HEC-RAS bundled ``gdalwarp.exe`` (written to a
        ``<output_vrt stem>_warped`` folder beside the output), then those
        warped VRTs are mosaicked. The warped VRTs are lightweight XML that
        reference the original tiles, but they must be kept alongside the
        output VRT for it to remain readable.

        Args:
            tile_files: TIFF files to mosaic, as str or Path
            output_vrt: Output VRT file path
            hecras_version: Optional HEC-RAS version to use for bundled
                GDAL discovery. If None, auto-detects the newest available
                install.
            target_crs: Optional target CRS for the mosaic (for example
                ``"EPSG:2277"``). When set, tiles are warped to this CRS
                before mosaicking. When None (default), the mosaic inherits
                the source SRS exactly as before. Keyword-only.
            target_resolution: Optional output cell size in target CRS units.
                A single number is used for both axes; an ``(x, y)`` pair sets
                them independently. When None (default), GDAL's native
                resolution handling is unchanged. Keyword-only.
            resampling_method: GDAL resampling method for the mosaic and for
                any warp step. Default ``"bilinear"`` (the historical value).
                Keyword-only.
            src_nodata: Optional source nodata value. Keyword-only.
            vrt_nodata: Optional nodata value written to the mosaic
                (``-vrtnodata``, or ``-dstnodata`` on the warp step).
                Keyword-only.
            source_crs: Optional SRS to assign to source tiles that carry no
                projection of their own. Without ``target_crs`` this becomes
                ``gdalbuildvrt -a_srs``, which requires GDAL 3.6 or newer; with
                ``target_crs`` it becomes ``gdalwarp -s_srs``, which every
                bundled GDAL supports. Keyword-only.

        Returns:
            Path to created VRT file

        Raises:
            ValueError: If ``tile_files`` is empty or ``target_resolution`` is
                not a positive number or positive ``(x, y)`` pair.
            FileNotFoundError: If a tile is missing, or the HEC-RAS bundled
                GDAL executables cannot be found.
            RuntimeError: If a GDAL command fails, times out, or produces no
                output.

        Example:
            # Unchanged default: inherit source SRS and resolution
            vrt = Usgs3depAws.create_vrt(tiles, "terrain_1m.vrt")

            # Explicit grid: NAD83 / Texas Central (ftUS), 10-foot cells
            vrt = Usgs3depAws.create_vrt(
                tiles,
                "terrain_2277.vrt",
                target_crs="EPSG:2277",
                target_resolution=10.0,
                resampling_method="bilinear",
                src_nodata=-999999,
                vrt_nodata=-9999,
            )
        """
        if not tile_files:
            raise ValueError("tile_files must contain at least one raster")

        output_vrt = Path(output_vrt)
        output_vrt.parent.mkdir(parents=True, exist_ok=True)
        tile_paths = [Path(tile_file) for tile_file in tile_files]

        for tile_path in tile_paths:
            if not tile_path.exists():
                raise FileNotFoundError(f"Tile file not found: {tile_path}")

        resolution_xy = Usgs3depAws._normalize_target_resolution(target_resolution)

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

        if target_crs:
            # gdalbuildvrt cannot reproject, so bring every tile onto the
            # requested grid first. This is what keeps mixed-UTM-zone tiles
            # from silently inheriting the first tile's SRS.
            tile_paths = Usgs3depAws._warp_tiles_to_target_crs(
                tile_paths,
                output_vrt,
                target_crs,
                target_resolution=resolution_xy,
                resampling_method=resampling_method,
                src_nodata=src_nodata,
                dst_nodata=vrt_nodata,
                source_crs=source_crs,
                hecras_version=hecras_version,
            )

        input_list_path = Usgs3depAws._write_gdal_input_file_list(
            tile_paths,
            output_vrt.parent,
        )
        logger.debug(f"gdalbuildvrt input file list: {input_list_path}")
        cmd = [
            str(gdalbuildvrt),
            "-overwrite",
            "-r", resampling_method,
        ]

        if source_crs and not target_crs:
            cmd += ["-a_srs", source_crs]

        if resolution_xy is not None:
            cmd += [
                "-resolution", "user",
                "-tr", str(resolution_xy[0]), str(resolution_xy[1]),
            ]

        if src_nodata is not None and not target_crs:
            cmd += ["-srcnodata", str(src_nodata)]

        if vrt_nodata is not None:
            cmd += ["-vrtnodata", str(vrt_nodata)]

        cmd += [
            "-input_file_list", str(input_list_path),
            str(output_vrt),
        ]
        logger.debug(f"gdalbuildvrt command: {cmd}")

        try:
            Usgs3depAws._run_gdal_command(
                cmd,
                "gdalbuildvrt",
                "creating the VRT mosaic",
            )
        finally:
            input_list_path.unlink(missing_ok=True)

        if not output_vrt.exists():
            raise RuntimeError(
                f"gdalbuildvrt completed but VRT was not created: {output_vrt}"
            )

        logger.info(f"VRT mosaic created: {output_vrt.name}")
        logger.debug(f"VRT mosaic output path: {output_vrt}")
        return output_vrt

    @staticmethod
    def _normalize_target_resolution(
        target_resolution: Optional[Union[int, float, Tuple[float, float]]],
    ) -> Optional[Tuple[float, float]]:
        """
        Normalize a target resolution to a positive ``(x_res, y_res)`` pair.

        Args:
            target_resolution: A single number for square cells, an
                ``(x, y)`` pair, or None.

        Returns:
            ``(x_res, y_res)`` as floats, or None when no resolution was
            requested.

        Raises:
            ValueError: If the value is not a number or a two-item pair, or if
                either resolution is not positive.
        """
        if target_resolution is None:
            return None

        if isinstance(target_resolution, (int, float)) and not isinstance(target_resolution, bool):
            resolution_xy = (float(target_resolution), float(target_resolution))
        else:
            try:
                x_res, y_res = target_resolution
                resolution_xy = (float(x_res), float(y_res))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "target_resolution must be a number or an (x, y) pair, "
                    f"got {target_resolution!r}"
                ) from exc

        if resolution_xy[0] <= 0 or resolution_xy[1] <= 0:
            raise ValueError(
                f"target_resolution values must be positive, got {resolution_xy}"
            )

        return resolution_xy

    @staticmethod
    def _warp_tiles_to_target_crs(
        tile_paths: Sequence[Union[str, Path]],
        output_vrt: Union[str, Path],
        target_crs: str,
        target_resolution: Optional[Tuple[float, float]] = None,
        resampling_method: str = "bilinear",
        src_nodata: Optional[Union[int, float, str]] = None,
        dst_nodata: Optional[Union[int, float, str]] = None,
        source_crs: Optional[str] = None,
        hecras_version: Optional[str] = None,
    ) -> List[Path]:
        """
        Reproject each tile to a warped VRT on the requested target grid.

        Uses HEC-RAS bundled ``gdalwarp.exe``, discovered the same way as
        ``gdalbuildvrt.exe``. Warping each tile individually (rather than
        assembling a mixed-SRS VRT) is what makes a mosaic across UTM zone
        boundaries correct. When a target resolution is supplied the warp also
        uses ``-tap`` so every warped tile shares one aligned grid and the
        mosaic has no resampling seams.

        Args:
            tile_paths: Source tiles to reproject
            output_vrt: Final mosaic path; warped VRTs are written to a
                ``<stem>_warped`` folder beside it
            target_crs: Target CRS, for example ``"EPSG:2277"``
            target_resolution: Optional ``(x_res, y_res)`` in target CRS units
            resampling_method: GDAL resampling method. Default ``"bilinear"``.
            src_nodata: Optional source nodata value
            dst_nodata: Optional destination nodata value
            source_crs: Optional SRS for tiles that carry no projection
            hecras_version: Optional HEC-RAS version for GDAL discovery

        Returns:
            List of warped VRT paths, in the order of ``tile_paths``

        Raises:
            FileNotFoundError: If HEC-RAS bundled gdalwarp.exe is not found
            RuntimeError: If a warp command fails or produces no output
        """
        try:
            gdalwarp = Usgs3depAws._find_gdalwarp_path(hecras_version)
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "Reprojecting a VRT mosaic requires HEC-RAS bundled gdalwarp.exe. "
                f"{exc}"
            ) from exc
        logger.debug(f"Using gdalwarp executable: {gdalwarp}")

        output_vrt = Path(output_vrt)
        warped_folder = output_vrt.parent / f"{output_vrt.stem}_warped"
        warped_folder.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Warped tile folder: {warped_folder}")

        warped_paths: List[Path] = []

        for tile_path in tile_paths:
            tile_path = Path(tile_path)
            warped_path = warped_folder / f"{tile_path.stem}.vrt"

            cmd = [
                str(gdalwarp),
                "-overwrite",
                "-of", "VRT",
                "-t_srs", target_crs,
                "-r", resampling_method,
            ]

            if source_crs:
                cmd += ["-s_srs", source_crs]

            if target_resolution is not None:
                cmd += [
                    "-tr", str(target_resolution[0]), str(target_resolution[1]),
                    "-tap",
                ]

            if src_nodata is not None:
                cmd += ["-srcnodata", str(src_nodata)]

            if dst_nodata is not None:
                cmd += ["-dstnodata", str(dst_nodata)]

            cmd += [str(tile_path), str(warped_path)]
            logger.debug(f"gdalwarp command: {cmd}")

            Usgs3depAws._run_gdal_command(
                cmd,
                "gdalwarp",
                "warping tiles to the target CRS",
            )

            if not warped_path.exists():
                raise RuntimeError(
                    f"gdalwarp completed but warped VRT was not created: {warped_path}"
                )

            warped_paths.append(warped_path)

        return warped_paths

    @staticmethod
    def _run_gdal_command(
        cmd: List[str],
        tool_name: str,
        operation: str,
        timeout_seconds: int = 600,
    ) -> subprocess.CompletedProcess:
        """
        Run one HEC-RAS bundled GDAL command with consistent error handling.

        Args:
            cmd: Full command line, executable first
            tool_name: Executable name used in error messages
            operation: Present-participle phrase used in the timeout message
            timeout_seconds: Subprocess timeout. Default 600.

        Returns:
            The completed subprocess result

        Raises:
            RuntimeError: If the command times out, cannot be executed, or
                returns a non-zero exit code.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{tool_name} timed out while {operation}."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Failed to execute {tool_name}: {exc}"
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"{tool_name} failed with code {result.returncode}. "
                f"STDERR: {result.stderr}"
            )

        return result

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
    def _find_gdalbuildvrt_in_install_dir(install_dir: Path) -> Optional[Path]:
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
        tile_paths: List[Path],
        output_dir: Path,
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
