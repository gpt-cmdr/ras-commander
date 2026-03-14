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
