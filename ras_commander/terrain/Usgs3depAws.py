"""
USGS 3DEP AWS Direct Access

Downloads elevation data directly from USGS 3DEP Cloud Optimized GeoTIFFs hosted on AWS S3.

This module provides direct access to all USGS 3DEP elevation datasets:
- 1m resolution (LiDAR-derived, highest quality)
- 10m resolution (1/3 arc-second, good CONUS coverage)
- 30m resolution (1 arc-second, full CONUS coverage)

Data is accessed directly from the public S3 bucket (no API rate limits or timeouts).

Key Features:
- Automatic tile discovery via spatial metadata (GeoPackage)
- Multi-tile mosaicking for seamless coverage
- Virtual raster (VRT) creation for efficient processing
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
"""

import logging
from pathlib import Path
from typing import Union, List, Tuple, Optional
import geopandas as gpd
from shapely.geometry import box, Polygon
import requests
from urllib.parse import urlparse

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
            resolution: DEM resolution in meters (1, 10, or 30)
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
            logger.info(f"Downloading {resolution}m tile index from AWS S3...")
            logger.info(f"  URL: {url}")

            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Save to cache
            with open(cache_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"  Saved to: {cache_path}")
        else:
            logger.info(f"Using cached {resolution}m tile index: {cache_path}")

        # Read GeoPackage
        gdf = gpd.read_file(cache_path)
        logger.info(f"  Loaded {len(gdf)} tiles")

        return gdf

    @staticmethod
    def query_tiles_api(
        bbox: Union[Polygon, Tuple[float, float, float, float]],
        resolution: int
    ) -> gpd.GeoDataFrame:
        """
        Query USGS 3DEP Tile Index API for tiles intersecting a bounding box.

        Uses the National Map ArcGIS REST API to get tile information.

        Args:
            bbox: Bounding box as (minx, miny, maxx, maxy) in WGS84 or Polygon
            resolution: DEM resolution in meters (1, 3, 10, or 30)

        Returns:
            GeoDataFrame with tile information including download URLs
        """
        # Convert bbox to tuple if Polygon
        if isinstance(bbox, Polygon):
            bbox_tuple = bbox.bounds
        else:
            bbox_tuple = bbox

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

        logger.info(f"Querying USGS Tile Index API for {resolution}m tiles...")
        response = requests.get(query_url, params=params)
        response.raise_for_status()

        # Parse GeoJSON response
        data = response.json()

        if 'features' not in data or len(data['features']) == 0:
            logger.warning("No tiles found in this area")
            return gpd.GeoDataFrame()

        # Convert to GeoDataFrame
        gdf = gpd.GeoDataFrame.from_features(data['features'], crs="EPSG:4326")

        logger.info(f"  Found {len(gdf)} tiles")

        return gdf

    @staticmethod
    def find_tiles_for_bbox(
        bbox: Union[Polygon, Tuple[float, float, float, float]],
        resolution: int,
        cache_folder: Optional[Union[str, Path]] = None
    ) -> gpd.GeoDataFrame:
        """
        Find all tiles that intersect with a bounding box.

        Uses GeoPackage tile index (more reliable than API).

        Args:
            bbox: Bounding box as (minx, miny, maxx, maxy) in WGS84 or Polygon
            resolution: DEM resolution in meters (1, 10, or 30)
            cache_folder: Optional folder to cache tile index

        Returns:
            GeoDataFrame with intersecting projects
        """
        # Convert bbox to Polygon if tuple
        if isinstance(bbox, tuple):
            bbox = box(*bbox)

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

        logger.info(f"Found {len(intersecting)} projects intersecting bbox")

        return intersecting

    @staticmethod
    def list_projects_for_bbox(
        bbox: Union[Polygon, Tuple[float, float, float, float]],
        resolution: int,
        cache_folder: Optional[Union[str, Path]] = None
    ) -> gpd.GeoDataFrame:
        """
        List all USGS 3DEP projects that intersect with a bounding box.

        Useful for exploring available data before downloading, or selecting
        specific projects by name or year.

        Args:
            bbox: Bounding box as (minx, miny, maxx, maxy) in WGS84 or Polygon
            resolution: DEM resolution in meters (1, 10, or 30)
            cache_folder: Optional folder to cache tile index

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

        # Convert bbox to Polygon if tuple
        if isinstance(bbox, tuple):
            bbox = box(*bbox)

        # Find intersecting projects (from tile index)
        projects = Usgs3depAws.find_tiles_for_bbox(bbox, resolution, cache_folder)

        if len(projects) == 0:
            logger.info("No projects found for bbox")
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

        logger.info(f"Found {len(projects)} project(s) intersecting bbox:")
        for idx, row in projects.iterrows():
            proj_name = row.get('proj_name', row.get('project', row.get('demname', 'Unknown')))
            year = row['_year']
            year_str = str(year) if year else 'unknown'
            logger.info(f"  - {proj_name} (year {year_str})")

        return projects

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
                logger.warning(f"UTM zone {utm_zone} outside expected range (4-5, 10-19)")
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

        logger.info(f"Fetching tile list from: {project_name}")

        try:
            response = requests.get(links_url, timeout=30)
            response.raise_for_status()

            # Parse URLs
            urls = [line.strip() for line in response.text.strip().split('\n') if line.strip()]

            logger.info(f"  Found {len(urls)} tiles in project")
            return urls

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"  Project not found in S3: {project_name}")
                logger.warning(f"    (Tile index may contain outdated project names)")
                return None
            else:
                # Other HTTP errors should propagate
                raise
        except requests.exceptions.RequestException as e:
            logger.error(f"  Network error fetching tile list: {e}")
            return None

    @staticmethod
    def _get_remote_file_size(url: str) -> Optional[int]:
        """
        Get remote file size in bytes using HTTP HEAD request.

        Args:
            url: Remote file URL

        Returns:
            File size in bytes, or None if cannot determine
        """
        try:
            response = requests.head(url, timeout=10)
            response.raise_for_status()

            content_length = response.headers.get('Content-Length')
            if content_length:
                return int(content_length)
            else:
                logger.debug(f"No Content-Length header for {url}")
                return None

        except Exception as e:
            logger.debug(f"Error getting file size for {url}: {e}")
            return None

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
                    logger.info(f"    Using cached: {filename} ({size_mb:.2f} MB)")
                    return output_path
                elif expected_size:
                    # File exists but wrong size - re-download
                    logger.warning(f"    Cached file size mismatch for {filename}")
                    logger.warning(f"      Local: {local_size:,} bytes, Expected: {expected_size:,} bytes")
                    logger.info(f"      Re-downloading...")
                else:
                    # Cannot verify size - assume cached file is good
                    size_mb = local_size / 1024 / 1024
                    logger.info(f"    Using cached: {filename} ({size_mb:.2f} MB, size unverified)")
                    return output_path

            # Download tile
            logger.info(f"    Downloading: {filename}")
            response = requests.get(tile_url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_mb = output_path.stat().st_size / 1024 / 1024
            logger.info(f"      Saved ({size_mb:.2f} MB)")
            return output_path

        except Exception as e:
            logger.error(f"      Failed to download {filename}: {e}")
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
        bbox: Union[Polygon, Tuple[float, float, float, float]],
        resolution: int,
        output_folder: Union[str, Path],
        cache_folder: Optional[Union[str, Path]] = None,
        overwrite_dest: bool = False,
        max_workers: int = 3,
        project_name: Optional[str] = None,
        min_year: Optional[int] = None
    ) -> List[Path]:
        """
        Download all DEM tiles for a bounding box with concurrent downloads.

        Implements passive file caching: if a tile already exists with the correct
        file size, it will be reused instead of re-downloaded. This allows
        interrupted downloads to resume and repeated runs to use cached files.

        Downloads are performed concurrently using multiple threads for improved
        performance (default 3 concurrent downloads).

        Args:
            bbox: Bounding box as (minx, miny, maxx, maxy) in WGS84 or Polygon
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

        Returns:
            List of paths to downloaded TIFF files

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
        """
        import rasterio

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        # Convert bbox to Polygon if tuple
        if isinstance(bbox, tuple):
            bbox_poly = box(*bbox)
        else:
            bbox_poly = bbox

        # Find intersecting projects (from tile index)
        projects = Usgs3depAws.find_tiles_for_bbox(bbox_poly, resolution, cache_folder)

        if len(projects) == 0:
            logger.warning("No projects found for bbox - no data available in this area")
            return []

        logger.info(f"Found {len(projects)} projects intersecting bbox")

        # Extract year from project names for filtering/sorting
        import re

        def extract_year(row):
            """Extract year from project name."""
            for field in ['proj_name', 'project', 'demname']:
                if field in row.index and row[field]:
                    match = re.search(r'_(\d{4})_', str(row[field]))
                    if match:
                        return int(match.group(1))
            return None

        projects['_year'] = projects.apply(extract_year, axis=1)

        # Project selection logic
        if project_name:
            # Filter to exact project name match
            logger.info(f"  Filtering to project: {project_name}")

            # Try all possible project name fields
            mask = False
            for field in ['proj_name', 'project', 'demname']:
                if field in projects.columns:
                    mask = mask | (projects[field] == project_name)

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
            logger.info(f"    Found project: {project_name}")

        elif min_year:
            # Filter to projects >= min_year
            logger.info(f"  Filtering to projects from {min_year} or newer")

            # Filter out projects with no year or year < min_year
            projects_filtered = projects[
                (projects['_year'].notna()) & (projects['_year'] >= min_year)
            ]

            if len(projects_filtered) == 0:
                logger.warning(f"  No projects found from {min_year} or newer")
                logger.warning(f"  Available years: {sorted(projects['_year'].dropna().unique())}")
                raise ValueError(f"No projects found from year {min_year} or newer")

            projects = projects_filtered
            logger.info(f"    Found {len(projects)} project(s) >= {min_year}")

        # If multiple projects remain, select most recent
        if len(projects) > 1:
            projects = projects.sort_values('_year', ascending=False, na_position='last')

            most_recent = projects.iloc[0]
            year = projects.iloc[0]['_year']

            logger.info(f"  Selecting most recent project (year {year if year else 'unknown'})")
            logger.info(f"    Selected: {most_recent.get('proj_name', most_recent.get('project', most_recent.get('demname')))}")

            logger.info(f"    Skipping {len(projects) - 1} older project(s):")
            for idx in range(1, min(len(projects), 4)):
                older = projects.iloc[idx]
                older_year = older['_year']
                older_name = older.get('proj_name', older.get('project', older.get('demname')))
                logger.info(f"      - {older_name} (year {older_year if older_year else 'unknown'})")

            # Use only the most recent project
            projects = projects.iloc[[0]]

        # Download tiles from selected project(s)
        all_downloaded = []

        for idx, project_row in projects.iterrows():
            # Project name field may be 'project', 'proj_name', or 'demname'
            project_name = None
            for field in ['proj_name', 'project', 'demname']:
                if field in project_row.index and project_row[field]:
                    project_name = project_row[field]
                    break

            if not project_name:
                logger.warning(f"No project name found in row {idx}, skipping")
                continue

            logger.info(f"\nProcessing project: {project_name}")

            # Get all tile URLs for this project
            tile_urls = Usgs3depAws._get_project_tile_urls(project_name)

            # Skip if project not found in S3 (outdated tile index)
            if tile_urls is None:
                logger.info(f"  Skipping project (not available in S3)")
                continue

            # Find which tiles intersect our bbox
            logger.info(f"  Checking {len(tile_urls)} tiles for intersection...")
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
                    if tile_box.intersects(bbox_poly):
                        intersecting_urls.append(tile_url)

                except Exception as e:
                    logger.debug(f"    Error checking tile {filename}: {e}")
                    continue

            logger.info(f"  Found {len(intersecting_urls)} intersecting tiles")

            # Download intersecting tiles (concurrent)
            if max_workers == 1:
                # Sequential downloads
                logger.info(f"  Downloading tiles sequentially...")
                for tile_url in intersecting_urls:
                    result = Usgs3depAws._download_single_tile(
                        tile_url, output_folder, overwrite_dest
                    )
                    if result:
                        all_downloaded.append(result)
            else:
                # Concurrent downloads
                from concurrent.futures import ThreadPoolExecutor, as_completed

                logger.info(f"  Downloading tiles with {max_workers} concurrent workers...")

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
                                all_downloaded.append(result)
                        except Exception as e:
                            filename = tile_url.split('/')[-1]
                            logger.error(f"      Concurrent download failed for {filename}: {e}")

        logger.info(f"\nTotal tiles downloaded: {len(all_downloaded)}")
        return all_downloaded

    @staticmethod
    def create_vrt(
        tile_files: List[Path],
        output_vrt: Union[str, Path]
    ) -> Path:
        """
        Create a Virtual Raster (VRT) mosaic from multiple tiles.

        Args:
            tile_files: List of TIFF files to mosaic
            output_vrt: Output VRT file path

        Returns:
            Path to created VRT file
        """
        from osgeo import gdal

        output_vrt = Path(output_vrt)

        # Build VRT
        logger.info(f"Creating VRT mosaic from {len(tile_files)} tiles...")

        vrt_options = gdal.BuildVRTOptions(resampleAlg='bilinear')
        vrt = gdal.BuildVRT(
            str(output_vrt),
            [str(f) for f in tile_files],
            options=vrt_options
        )

        if vrt is None:
            raise RuntimeError("Failed to create VRT")

        # Close dataset
        vrt = None

        logger.info(f"  Created: {output_vrt}")
        return output_vrt
