"""
GeomStorage - Storage area operations for HEC-RAS geometry files

This module provides functionality for reading storage area data from
HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_storage_areas() - List all storage areas with metadata
- get_elevation_volume() - Read elevation-volume curve for a storage area

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
    def get_storage_areas(geom_file: Union[str, Path]) -> pd.DataFrame:
        """
        Extract storage area metadata from geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Name (str): Storage area name
                - NumPoints (int): Number of elevation-volume points
                - MinElev (float): Minimum elevation in storage curve (if available)
                - MaxElev (float): Maximum elevation in storage curve (if available)

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> storage_df = GeomStorage.get_storage_areas("model.g01")
            >>> print(f"Found {len(storage_df)} storage areas")
            >>> for _, row in storage_df.iterrows():
            ...     print(f"  {row['Name']}: {row['NumPoints']} points")
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
                    sa_name = GeomParser.extract_keyword_value(line, "Storage Area")

                    # Look for elevation-volume count
                    num_points = 0
                    min_elev = None
                    max_elev = None

                    for j in range(i+1, min(i+50, len(lines))):
                        if lines[j].startswith("Storage Area Elev Volume="):
                            count_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Elev Volume")
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

                        # Stop at next storage area or section
                        if lines[j].startswith("Storage Area=") or lines[j].startswith("River Reach="):
                            break

                    storage_areas.append({
                        'Name': sa_name,
                        'NumPoints': num_points,
                        'MinElev': min_elev,
                        'MaxElev': max_elev
                    })

                i += 1

            df = pd.DataFrame(storage_areas)
            logger.info(f"Found {len(df)} storage areas in {geom_file.name}")
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
                    sa_name = GeomParser.extract_keyword_value(line, "Storage Area")
                    if sa_name == storage_name:
                        sa_idx = i
                        break

            if sa_idx is None:
                raise ValueError(f"Storage area not found: {storage_name}")

            # Find elevation-volume data
            for j in range(sa_idx+1, min(sa_idx+50, len(lines))):
                if lines[j].startswith("Storage Area Elev Volume="):
                    count_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Elev Volume")
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

                # Stop at next storage area
                if lines[j].startswith("Storage Area="):
                    break

            raise ValueError(f"Elevation-volume data not found for {storage_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading elevation-volume: {str(e)}")
            raise IOError(f"Failed to read elevation-volume: {str(e)}")
