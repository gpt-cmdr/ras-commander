"""
GeomStorage - Storage area operations for HEC-RAS geometry files

This module provides functionality for reading and writing storage area data
in HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_storage_areas() - List all storage areas with metadata
- get_elevation_volume() - Read elevation-volume curve for a storage area
- set_elevation_volume() - Write elevation-volume curve to a storage area

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
from typing import Union, Optional, List
import pandas as pd

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
            with open(geom_file, 'r') as f:
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
            with open(geom_file, 'r') as f:
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
            with open(geom_file, 'r') as f:
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
            with open(geom_file, 'w') as f:
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
