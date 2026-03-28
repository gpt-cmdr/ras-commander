"""
GeomStorage - Storage area operations for HEC-RAS geometry files

This module provides functionality for reading and writing storage area data
in HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_storage_areas() - List all storage areas with metadata
- get_elevation_volume() - Read elevation-volume curve for a storage area
- set_elevation_volume() - Write elevation-volume curve to a storage area
- get_storage_area_polygons() - Extract storage area polygon perimeter geometry
- get_2d_flow_area_settings() - Read 2D flow area cell/face property settings
- set_2d_flow_area_settings() - Write 2D flow area cell/face property settings

Example Usage:
    >>> from ras_commander import GeomStorage
    >>> from pathlib import Path
    >>>
    >>> # List all storage areas
    >>> geom_file = Path("model.g01")
    >>> storage_df = GeomStorage.get_storage_areas(geom_file)
    >>> print(f"Found {len(storage_df)} storage areas")
    >>>
    >>> # Get elevation-volume curve
    >>> elev_vol = GeomStorage.get_elevation_volume(geom_file, "Reservoir Pool 1")
    >>> print(elev_vol)
    >>>
    >>> # Write modified curve back to file
    >>> GeomStorage.set_elevation_volume(
    ...     geom_file, "Reservoir Pool 1",
    ...     elevations=[1200.0, 1210.0, 1220.0],
    ...     volumes=[0.0, 500.0, 1500.0]
    ... )
"""

from pathlib import Path
from typing import TYPE_CHECKING, Union, Optional, List
import pandas as pd

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomStorage:
    """
    Operations for parsing HEC-RAS storage areas in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format

    @staticmethod
    @log_call
    def get_storage_areas(geom_file: Union[str, Path],
                         exclude_2d: bool = True) -> pd.DataFrame:
        """
        Extract storage area metadata from geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            exclude_2d (bool): If True, exclude 2D flow areas (default True).
                2D flow areas are identified by having "Storage Area Is2D=" set to -1.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Name (str): Storage area name
                - NumPoints (int): Number of elevation-volume points
                - MinElev (float): Minimum elevation in storage curve (if available)
                - MaxElev (float): Maximum elevation in storage curve (if available)
                - Is2D (bool): Whether this is a 2D flow area

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> # Get only traditional storage areas (exclude 2D)
            >>> storage_df = GeomStorage.get_storage_areas("model.g01", exclude_2d=True)
            >>> print(f"Found {len(storage_df)} storage areas")
            >>>
            >>> # Get all storage areas including 2D flow areas
            >>> all_storage = GeomStorage.get_storage_areas("model.g01", exclude_2d=False)
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            storage_areas = []
            i = 0

            while i < len(lines):
                line = lines[i]

                # Find Storage Area definition
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str

                    # Look for elevation-volume count and 2D flag
                    num_points = 0
                    min_elev = None
                    max_elev = None
                    is_2d = False

                    # Search until next storage area (surface line data can span many lines)
                    for j in range(i+1, len(lines)):
                        # Stop at next storage area or section
                        if lines[j].startswith("Storage Area=") or lines[j].startswith("River Reach="):
                            break

                        # Check if this is a 2D flow area
                        if lines[j].startswith("Storage Area Is2D="):
                            is2d_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Is2D")
                            try:
                                is_2d = int(is2d_str.strip()) == -1
                            except ValueError:
                                pass

                        # Check for elevation-volume data (two keyword variants exist)
                        elev_vol_keyword = None
                        if lines[j].startswith("Storage Area Elev Volume="):
                            elev_vol_keyword = "Storage Area Elev Volume"
                        elif lines[j].startswith("Storage Area Vol Elev="):
                            elev_vol_keyword = "Storage Area Vol Elev"

                        if elev_vol_keyword:
                            count_str = GeomParser.extract_keyword_value(lines[j], elev_vol_keyword)
                            try:
                                num_points = int(count_str.strip())
                            except ValueError:
                                pass

                            # Parse first and last elevation values
                            if num_points > 0:
                                values = []
                                k = j + 1
                                total_needed = num_points * 2
                                while len(values) < total_needed and k < len(lines):
                                    if '=' in lines[k]:
                                        break
                                    parsed = GeomParser.parse_fixed_width(lines[k], GeomStorage.FIXED_WIDTH_COLUMN)
                                    values.extend(parsed)
                                    k += 1

                                if len(values) >= 2:
                                    # Elevations are at even indices (0, 2, 4, ...)
                                    elevations = values[0::2]
                                    if elevations:
                                        min_elev = elevations[0]
                                        max_elev = elevations[-1] if len(elevations) > 1 else elevations[0]
                            break

                    storage_areas.append({
                        'Name': sa_name,
                        'NumPoints': num_points,
                        'MinElev': min_elev,
                        'MaxElev': max_elev,
                        'Is2D': is_2d
                    })

                i += 1

            df = pd.DataFrame(storage_areas)

            # Filter out 2D flow areas if requested
            if exclude_2d and not df.empty and 'Is2D' in df.columns:
                original_count = len(df)
                df = df[~df['Is2D']].reset_index(drop=True)
                if original_count != len(df):
                    logger.debug(f"Excluded {original_count - len(df)} 2D flow areas")

            logger.debug(f"Found {len(df)} storage areas in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading storage areas: {str(e)}")
            raise IOError(f"Failed to read storage areas: {str(e)}")

    @staticmethod
    @log_call
    def get_elevation_volume(geom_file: Union[str, Path],
                            storage_name: str) -> pd.DataFrame:
        """
        Extract elevation-volume curve for a storage area.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            storage_name (str): Storage area name (case-sensitive)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Elevation (float): Storage elevation (ft or m)
                - Volume (float): Storage volume at elevation (acre-ft or m³)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If storage area not found

        Example:
            >>> elev_vol = GeomStorage.get_elevation_volume("model.g01", "Reservoir Pool 1")
            >>> print(f"Storage curve has {len(elev_vol)} points")
            >>> print(f"Elevation range: {elev_vol['Elevation'].min():.1f} to {elev_vol['Elevation'].max():.1f}")
            >>> print(f"Max volume: {elev_vol['Volume'].max():,.0f} acre-ft")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the storage area
            sa_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    if sa_name == storage_name:
                        sa_idx = i
                        break

            if sa_idx is None:
                raise ValueError(f"Storage area not found: {storage_name}")

            # Find elevation-volume data (two keyword variants exist)
            # Search until next storage area (surface line data can span many lines)
            for j in range(sa_idx+1, len(lines)):
                # Stop at next storage area
                if lines[j].startswith("Storage Area="):
                    break

                elev_vol_keyword = None
                if lines[j].startswith("Storage Area Elev Volume="):
                    elev_vol_keyword = "Storage Area Elev Volume"
                elif lines[j].startswith("Storage Area Vol Elev="):
                    elev_vol_keyword = "Storage Area Vol Elev"

                if elev_vol_keyword:
                    count_str = GeomParser.extract_keyword_value(lines[j], elev_vol_keyword)
                    count = int(count_str.strip())

                    # Parse elevation-volume pairs
                    total_values = count * 2
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        if '=' in lines[k]:
                            break
                        parsed = GeomParser.parse_fixed_width(lines[k], GeomStorage.FIXED_WIDTH_COLUMN)
                        values.extend(parsed)
                        k += 1

                    # Split into elevations and volumes
                    elevations = values[0::2]
                    volumes = values[1::2]

                    df = pd.DataFrame({
                        'Elevation': elevations[:count],
                        'Volume': volumes[:count]
                    })

                    logger.info(f"Extracted {len(df)} elevation-volume points for {storage_name}")
                    return df

            raise ValueError(f"Elevation-volume data not found for {storage_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading elevation-volume: {str(e)}")
            raise IOError(f"Failed to read elevation-volume: {str(e)}")

    @staticmethod
    @log_call
    def set_elevation_volume(geom_file: Union[str, Path],
                            storage_name: str,
                            elevations: List[float],
                            volumes: List[float],
                            create_backup: bool = True) -> Path:
        """
        Write elevation-volume curve for a storage area to geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            storage_name (str): Storage area name (case-sensitive, must exist)
            elevations (List[float]): List of elevation values (must be ascending)
            volumes (List[float]): List of volume values (same length as elevations)
            create_backup (bool): If True, create .bak backup before modification (default True)

        Returns:
            Path: Path to backup file if created, or geometry file path if no backup

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If storage area not found, or if elevations/volumes invalid

        Example:
            >>> # Modify an existing storage curve
            >>> backup = GeomStorage.set_elevation_volume(
            ...     "model.g01", "Reservoir Pool 1",
            ...     elevations=[1200.0, 1210.0, 1220.0, 1230.0],
            ...     volumes=[0.0, 500.0, 1500.0, 3500.0]
            ... )
            >>> print(f"Backup created: {backup}")

            >>> # Modify without backup (not recommended)
            >>> GeomStorage.set_elevation_volume(
            ...     "model.g01", "Reservoir Pool 1",
            ...     elevations=[1200.0, 1220.0],
            ...     volumes=[0.0, 1000.0],
            ...     create_backup=False
            ... )

        Notes:
            - Elevations must be in ascending order
            - Lengths of elevations and volumes must match
            - Creates .bak backup by default (strongly recommended)
            - Supports both "Storage Area Elev Volume=" and "Storage Area Vol Elev=" keywords
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate inputs
        if len(elevations) != len(volumes):
            raise ValueError(
                f"Elevations and volumes must have same length: "
                f"{len(elevations)} != {len(volumes)}"
            )

        if len(elevations) < 2:
            raise ValueError("At least 2 elevation-volume points are required")

        # Check elevations are ascending
        for i in range(1, len(elevations)):
            if elevations[i] <= elevations[i-1]:
                raise ValueError(
                    f"Elevations must be strictly ascending: "
                    f"{elevations[i-1]} >= {elevations[i]} at index {i}"
                )

        # Create backup if requested
        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the storage area
            sa_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    if sa_name == storage_name:
                        sa_idx = i
                        break

            if sa_idx is None:
                raise ValueError(f"Storage area not found: {storage_name}")

            # Find the elevation-volume data line and data extent
            elev_vol_line_idx = None
            data_start_idx = None
            data_end_idx = None
            elev_vol_keyword = None

            # Search until next storage area (surface line data can span many lines)
            for j in range(sa_idx + 1, len(lines)):
                # Stop at next storage area
                if lines[j].startswith("Storage Area="):
                    break

                # Check for elevation-volume keyword line
                if lines[j].startswith("Storage Area Elev Volume="):
                    elev_vol_keyword = "Storage Area Elev Volume"
                    elev_vol_line_idx = j
                    data_start_idx = j + 1
                elif lines[j].startswith("Storage Area Vol Elev="):
                    elev_vol_keyword = "Storage Area Vol Elev"
                    elev_vol_line_idx = j
                    data_start_idx = j + 1

                if elev_vol_line_idx is not None and data_start_idx is not None:
                    # Find end of data (next keyword line or next storage area)
                    for k in range(data_start_idx, len(lines)):
                        if '=' in lines[k]:
                            data_end_idx = k
                            break
                    if data_end_idx is None:
                        data_end_idx = len(lines)
                    break

            if elev_vol_line_idx is None:
                raise ValueError(f"Elevation-volume data not found for {storage_name}")

            # Format new data
            # Interleave elevations and volumes: elev1, vol1, elev2, vol2, ...
            interleaved = []
            for elev, vol in zip(elevations, volumes):
                interleaved.append(elev)
                interleaved.append(vol)

            # Format as fixed-width lines
            new_data_lines = GeomParser.format_fixed_width(
                interleaved,
                column_width=GeomStorage.FIXED_WIDTH_COLUMN,
                values_per_line=GeomStorage.VALUES_PER_LINE,
                precision=2
            )

            # Create new keyword line with updated count
            new_keyword_line = f"{elev_vol_keyword}= {len(elevations)} \n"

            # Build modified file content
            new_lines = (
                lines[:elev_vol_line_idx] +
                [new_keyword_line] +
                new_data_lines +
                lines[data_end_idx:]
            )

            # Write modified file
            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            logger.info(
                f"Updated elevation-volume curve for {storage_name}: "
                f"{len(elevations)} points"
            )

            return backup_path if backup_path else geom_file

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing elevation-volume: {str(e)}")
            raise IOError(f"Failed to write elevation-volume: {str(e)}")

    @staticmethod
    @log_call
    def get_storage_area_polygons(
        geom_file: Union[str, Path],
        exclude_2d: bool = True
    ) -> "GeoDataFrame":
        """
        Extract storage area polygon perimeter geometry from plain text geometry file.

        Parses the ``Storage Area Surface Line= N`` block to build a Shapely
        Polygon from the N 16-char fixed-width XY pairs that follow it.

        Parameters:
            geom_file: Path to .g## geometry file
            exclude_2d: If True, exclude 2D flow areas identified by
                ``Storage Area Is2D= -1`` (default True)

        Returns:
            GeoDataFrame with columns:
                - Name (str): Storage area name
                - geometry (Polygon): Perimeter polygon in project CRS
                - centroid_x (float): SA centroid X coordinate
                - centroid_y (float): SA centroid Y coordinate
                - is_2d (bool): Whether this is a 2D flow area

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> sa_polygons = GeomStorage.get_storage_area_polygons("model.g01")
            >>> print(f"Found {len(sa_polygons)} storage area polygons")
            >>> for _, row in sa_polygons.iterrows():
            ...     coords = list(row.geometry.exterior.coords)
            ...     print(f"  {row['Name']}: {len(coords)-1} vertices")
        """
        import geopandas as gpd
        from shapely.geometry import Polygon as ShapelyPolygon

        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        def _parse_surface_line_coords(lines, start_idx, count):
            """Parse N XY pairs from Storage Area Surface Line data."""
            vertices = []
            for k in range(start_idx, start_idx + count):
                if k >= len(lines):
                    break
                line = lines[k].rstrip('\n')
                # Primary: 16-char fixed-width (standard HEC-RAS format, no separator)
                try:
                    x = float(line[0:16])
                    y = float(line[16:32])
                except (ValueError, IndexError):
                    # Fallback: space-separated (rare variant)
                    parts = line.split()
                    if len(parts) >= 2:
                        x, y = float(parts[0]), float(parts[1])
                    else:
                        continue  # skip malformed line
                vertices.append((x, y))
            return vertices

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            records = []
            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Format: Name,centroid_X,centroid_Y
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    try:
                        centroid_x = float(parts[1]) if len(parts) > 1 else None
                        centroid_y = float(parts[2]) if len(parts) > 2 else None
                    except ValueError:
                        centroid_x = None
                        centroid_y = None

                    # Scan entire SA block FIRST to record both Surface Line index
                    # and Is2D flag before processing any coordinates.
                    # Is2D= may appear AFTER Surface Line= in the file.
                    surface_line_idx = None
                    surface_line_count = 0
                    is_2d = False

                    for j in range(i + 1, len(lines)):
                        if (lines[j].startswith("Storage Area=") or
                                lines[j].startswith("River Reach=")):
                            break
                        if lines[j].startswith("Storage Area Surface Line="):
                            try:
                                count_str = GeomParser.extract_keyword_value(
                                    lines[j], "Storage Area Surface Line"
                                )
                                surface_line_count = int(count_str.strip())
                                surface_line_idx = j + 1
                            except ValueError:
                                pass
                        if lines[j].startswith("Storage Area Is2D="):
                            try:
                                is2d_str = GeomParser.extract_keyword_value(
                                    lines[j], "Storage Area Is2D"
                                )
                                is_2d = int(is2d_str.strip()) == -1
                            except ValueError:
                                pass

                    # Now parse coordinates if we found a surface line
                    polygon = None
                    if surface_line_idx is not None and surface_line_count > 0:
                        vertices = _parse_surface_line_coords(
                            lines, surface_line_idx, surface_line_count
                        )
                        if len(vertices) >= 3:
                            try:
                                polygon = ShapelyPolygon(vertices)
                            except Exception as poly_err:
                                logger.warning(
                                    f"Could not create polygon for '{sa_name}': {poly_err}"
                                )

                    records.append({
                        'Name': sa_name,
                        'geometry': polygon,
                        'centroid_x': centroid_x,
                        'centroid_y': centroid_y,
                        'is_2d': is_2d,
                    })

                i += 1

            if not records:
                return gpd.GeoDataFrame(
                    columns=['Name', 'geometry', 'centroid_x', 'centroid_y', 'is_2d'],
                    geometry='geometry'
                )

            gdf = gpd.GeoDataFrame(records, geometry='geometry')

            if exclude_2d and not gdf.empty:
                original_count = len(gdf)
                gdf = gdf[~gdf['is_2d']].reset_index(drop=True)
                if original_count != len(gdf):
                    logger.debug(f"Excluded {original_count - len(gdf)} 2D flow areas")

            # Drop entries without valid polygon geometry
            valid_mask = gdf['geometry'].notna()
            if not valid_mask.all():
                dropped = (~valid_mask).sum()
                logger.warning(
                    f"Dropped {dropped} storage areas with no polygon geometry"
                )
                gdf = gdf[valid_mask].reset_index(drop=True)

            logger.debug(f"Found {len(gdf)} storage area polygons in {geom_file.name}")
            return gdf

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading storage area polygons: {str(e)}")
            raise IOError(f"Failed to read storage area polygons: {str(e)}")

    # Plain text keywords for 2D flow area settings
    _SETTINGS_KEYWORDS = {
        'Storage Area Mannings': 'mannings_n',
        '2D Cell Volume Filter Tolerance': 'cell_vol_tol',
        '2D Cell Minimum Area Fraction': 'cell_min_area_fraction',
        '2D Face Profile Filter Tolerance': 'face_profile_tol',
        '2D Face Area Elevation Profile Filter Tolerance': 'face_area_tol',
        '2D Face Area Elevation Conveyance Ratio': 'face_conv_ratio',
        '2D Face Area Laminar Depth': 'laminar_depth',
        '2D Face Min Length Ratio': 'min_face_length_ratio',
    }

    # Boolean keywords: present with =-1 means True, absent means False
    _BOOLEAN_KEYWORDS = {
        '2D Multiple Face Mann n': 'spatially_varied_mann_on_faces',
        '2D Composite LC': 'composite_classification',
    }

    @staticmethod
    @log_call
    def get_2d_flow_area_settings(geom_file: Union[str, Path]) -> pd.DataFrame:
        """
        Read 2D flow area cell/face property settings from plain text geometry file.

        Extracts per-flow-area settings including default Manning's n,
        tolerance/filter values, and subgrid sampling options (spatially
        varied Manning's n on faces, composite classification in cells).

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)

        Returns:
            pd.DataFrame: DataFrame with one row per 2D flow area. Columns:
                - name (str): 2D flow area name
                - mannings_n (float): Default Manning's n
                - spatially_varied_mann_on_faces (bool): Spatially varied Manning's n
                - composite_classification (bool): Composite classification values
                - cell_vol_tol (float): Cell volume filter tolerance
                - cell_min_area_fraction (float): Cell minimum area fraction
                - face_profile_tol (float): Face profile filter tolerance
                - face_area_tol (float): Face area elevation profile filter tolerance
                - face_conv_ratio (float): Face area elevation conveyance ratio
                - laminar_depth (float): Face area laminar depth
                - min_face_length_ratio (float): Min face length ratio (NaN if absent)

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> settings = GeomStorage.get_2d_flow_area_settings("model.g01")
            >>> for _, row in settings.iterrows():
            ...     print(f"{row['name']}: Mann n={row['mannings_n']}, "
            ...           f"Spatial={row['spatially_varied_mann_on_faces']}, "
            ...           f"Composite={row['composite_classification']}")
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        records = []
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("Storage Area="):
                value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                parts = [p.strip() for p in value_str.split(',')]
                sa_name = parts[0] if parts else value_str

                is_2d = False
                settings = {
                    'name': sa_name,
                    'mannings_n': float('nan'),
                    'spatially_varied_mann_on_faces': False,
                    'composite_classification': False,
                    'cell_vol_tol': float('nan'),
                    'cell_min_area_fraction': float('nan'),
                    'face_profile_tol': float('nan'),
                    'face_area_tol': float('nan'),
                    'face_conv_ratio': float('nan'),
                    'laminar_depth': float('nan'),
                    'min_face_length_ratio': float('nan'),
                }

                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("Storage Area=") or lines[j].startswith("River Reach="):
                        break

                    if lines[j].startswith("Storage Area Is2D="):
                        is2d_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Is2D")
                        try:
                            is_2d = int(is2d_str.strip()) == -1
                        except ValueError:
                            pass

                    for keyword, column in GeomStorage._SETTINGS_KEYWORDS.items():
                        if lines[j].startswith(keyword + '='):
                            val_str = GeomParser.extract_keyword_value(lines[j], keyword)
                            try:
                                settings[column] = float(val_str.strip())
                            except ValueError:
                                pass

                    for keyword, column in GeomStorage._BOOLEAN_KEYWORDS.items():
                        if lines[j].startswith(keyword + '='):
                            val_str = GeomParser.extract_keyword_value(lines[j], keyword)
                            try:
                                settings[column] = int(val_str.strip()) == -1
                            except ValueError:
                                pass

                if is_2d:
                    records.append(settings)

            i += 1

        df = pd.DataFrame(records)
        if df.empty:
            df = pd.DataFrame(columns=[
                'name', 'mannings_n', 'spatially_varied_mann_on_faces',
                'composite_classification', 'cell_vol_tol', 'cell_min_area_fraction',
                'face_profile_tol', 'face_area_tol', 'face_conv_ratio',
                'laminar_depth', 'min_face_length_ratio',
            ])

        logger.debug(f"Found {len(df)} 2D flow area settings in {geom_file.name}")
        return df

    @staticmethod
    @log_call
    def set_2d_flow_area_settings(
        geom_file: Union[str, Path],
        flow_area_name: str,
        spatially_varied_mann_on_faces: Optional[bool] = None,
        composite_classification: Optional[bool] = None,
        mannings_n: Optional[float] = None,
        create_backup: bool = True,
    ) -> Path:
        """
        Set 2D flow area cell/face property settings in plain text geometry file.

        Modifies settings for a specific 2D flow area. Only parameters that
        are explicitly provided (not None) are modified; others are left unchanged.

        The geometry HDF is rebuilt from the plain text file during preprocessing,
        so changes here propagate to the HDF automatically.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            flow_area_name (str): Name of the 2D flow area (case-sensitive)
            spatially_varied_mann_on_faces (Optional[bool]): Enable/disable
                spatially varied Manning's n on faces. None = no change.
            composite_classification (Optional[bool]): Enable/disable
                composite classification values in cells. None = no change.
            mannings_n (Optional[float]): Default Manning's n value.
                None = no change.
            create_backup (bool): Create .bak backup before modification (default True)

        Returns:
            Path: Path to backup file if created, or geometry file path if no backup

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If flow area not found or not a 2D flow area

        Example:
            >>> # Enable both subgrid sampling options
            >>> GeomStorage.set_2d_flow_area_settings(
            ...     "model.g01",
            ...     flow_area_name="Perimeter 1",
            ...     spatially_varied_mann_on_faces=True,
            ...     composite_classification=True,
            ... )

            >>> # Change default Manning's n and disable composite
            >>> GeomStorage.set_2d_flow_area_settings(
            ...     "model.g01",
            ...     flow_area_name="Perimeter 1",
            ...     mannings_n=0.04,
            ...     composite_classification=False,
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if (spatially_varied_mann_on_faces is None and
                composite_classification is None and
                mannings_n is None):
            logger.info("No settings to change")
            return geom_file

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Find the target 2D flow area block
        sa_idx = None
        block_end = None
        is_2d = False

        for i, line in enumerate(lines):
            if line.startswith("Storage Area="):
                value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                parts = [p.strip() for p in value_str.split(',')]
                sa_name = parts[0] if parts else value_str
                if sa_name == flow_area_name:
                    sa_idx = i
                    # Find end of this storage area block
                    for j in range(i + 1, len(lines)):
                        if lines[j].startswith("Storage Area=") or lines[j].startswith("River Reach="):
                            block_end = j
                            break
                    if block_end is None:
                        block_end = len(lines)
                    # Check it's a 2D flow area
                    for j in range(i + 1, block_end):
                        if lines[j].startswith("Storage Area Is2D="):
                            is2d_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Is2D")
                            try:
                                is_2d = int(is2d_str.strip()) == -1
                            except ValueError:
                                pass
                    break

        if sa_idx is None:
            raise ValueError(f"Flow area not found: {flow_area_name}")
        if not is_2d:
            raise ValueError(f"'{flow_area_name}' is not a 2D flow area")

        # Find the settings sub-block (between PointsPerimeterTime and
        # blank line or BreakLine)
        settings_start = None
        settings_end = None
        for j in range(sa_idx + 1, block_end):
            if lines[j].startswith("Storage Area Mannings="):
                settings_start = j
            if settings_start is not None and j > settings_start:
                stripped = lines[j].strip()
                if (stripped == '' or
                        lines[j].startswith("BreakLine ") or
                        lines[j].startswith("Storage Area=") or
                        lines[j].startswith("River Reach=")):
                    settings_end = j
                    break
        if settings_end is None and settings_start is not None:
            settings_end = block_end

        if settings_start is None:
            raise ValueError(
                f"Could not find settings block for '{flow_area_name}'. "
                f"Expected 'Storage Area Mannings=' line."
            )

        # Create backup before modifying
        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        # Modify settings in place
        # 1. Update Manning's n if requested
        if mannings_n is not None:
            for j in range(settings_start, settings_end):
                if lines[j].startswith("Storage Area Mannings="):
                    lines[j] = f"Storage Area Mannings={mannings_n}\n"
                    break

        # 2. Handle boolean settings (add/remove lines)
        bool_changes = {}
        if spatially_varied_mann_on_faces is not None:
            bool_changes['2D Multiple Face Mann n'] = spatially_varied_mann_on_faces
        if composite_classification is not None:
            bool_changes['2D Composite LC'] = composite_classification

        for keyword, enabled in bool_changes.items():
            # Find if line already exists
            existing_idx = None
            for j in range(settings_start, settings_end):
                if lines[j].startswith(keyword + '='):
                    existing_idx = j
                    break

            if enabled and existing_idx is None:
                # Add the line before settings_end
                new_line = f"{keyword}=-1\n"
                lines.insert(settings_end, new_line)
                settings_end += 1  # Adjust for inserted line
            elif not enabled and existing_idx is not None:
                # Remove the line
                lines.pop(existing_idx)
                settings_end -= 1  # Adjust for removed line

        # Write modified file
        with open(geom_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        changes = []
        if mannings_n is not None:
            changes.append(f"Manning's n={mannings_n}")
        if spatially_varied_mann_on_faces is not None:
            changes.append(f"Spatially Varied={'ON' if spatially_varied_mann_on_faces else 'OFF'}")
        if composite_classification is not None:
            changes.append(f"Composite LC={'ON' if composite_classification else 'OFF'}")

        logger.info(f"Updated {flow_area_name}: {', '.join(changes)}")

        return backup_path if backup_path else geom_file
