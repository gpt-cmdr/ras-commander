"""
RasGeometry - Operations for parsing and modifying HEC-RAS geometry files

This module provides comprehensive functionality for reading and modifying
HEC-RAS plain text geometry files (.g##). It handles 1D cross sections,
2D flow areas, storage areas, connections, and all related geometry data.

All methods are static and designed to be used without instantiation.

List of Functions:

Cross Section Operations:
- get_cross_sections() - Extract all cross section metadata
- get_station_elevation() - Read station/elevation pairs for a cross section
- set_station_elevation() - Write station/elevation with automatic bank interpolation
- get_bank_stations() - Read left and right bank station locations
- get_expansion_contraction() - Read expansion and contraction coefficients
- get_mannings_n() - Read Manning's roughness values with LOB/Channel/ROB classification

Storage Area Operations:
- get_storage_areas() - List all storage area names (excluding 2D flow areas)
- get_storage_elevation_volume() - Read elevation-volume curve for a storage area

Lateral Structure Operations:
- get_lateral_structures() - List all lateral weir structures with metadata
- get_lateral_weir_profile() - Read station-elevation profile for lateral weir

SA/2D Connection Operations:
- get_connections() - List all SA/2D area connections
- get_connection_weir_profile() - Read dam/weir crest station-elevation profile
- get_connection_gates() - Read gate definitions (CSV format, 23+ parameters)

Example Usage:
    >>> from ras_commander import RasGeometry
    >>> from pathlib import Path
    >>>
    >>> # List all cross sections
    >>> geom_file = Path("BaldEagle.g01")
    >>> xs_df = RasGeometry.get_cross_sections(geom_file)
    >>> print(f"Found {len(xs_df)} cross sections")
    >>>
    >>> # Get station/elevation for specific XS
    >>> sta_elev = RasGeometry.get_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4"
    ... )
    >>> print(sta_elev.head())
    >>>
    >>> # Modify and write back
    >>> sta_elev['Elevation'] += 1.0  # Raise XS by 1 foot
    >>> RasGeometry.set_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4", sta_elev
    ... )

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Count interpretation: "#Sta/Elev= 40" means 40 PAIRS (80 total values)
    - Always creates .bak backup before modification


References:
    - See research/geometry file parsing/geometry_docs/1D_geometry_structure.md
    - See research/geometry file parsing/geometry_docs/_PARSING_PATTERNS_REFERENCE.md
"""

from pathlib import Path
from typing import Union, Optional, List, Tuple, Dict, Any
import pandas as pd
import numpy as np

from .LoggingConfig import get_logger
from .Decorators import log_call
from .RasGeometryUtils import RasGeometryUtils

logger = get_logger(__name__)


class RasGeometry:
    """
    Operations for parsing and modifying HEC-RAS geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format
    MAX_XS_POINTS = 450         # HEC-RAS hard limit on cross section points

    # Parsing constants
    DEFAULT_SEARCH_RANGE = 50   # Default number of lines to search for keywords after XS header
    MAX_PARSE_LINES = 100       # Safety limit on lines to parse for data blocks

    # ========== PRIVATE HELPER METHODS ==========

    @staticmethod
    def _find_cross_section(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """
        Find cross section in geometry file and return starting line index.

        This helper eliminates ~320 lines of duplication across 8 public methods.

        Args:
            lines: File lines (from readlines())
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string, e.g., "138154.4")

        Returns:
            Line index where "Type RM Length L Ch R =" for matching XS starts,
            or None if not found

        Example:
            >>> with open(geom_file, 'r') as f:
            ...     lines = f.readlines()
            >>> idx = RasGeometry._find_cross_section(lines, "Bald Eagle", "Loc Hav", "138154.4")
            >>> if idx:
            ...     # Process XS block starting at lines[idx]
        """
        current_river = None
        current_reach = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Find matching cross section
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]

                if len(values) > 1:
                    # Format: Type, RS, Length_L, Length_Ch, Length_R
                    xs_rs = values[1]  # RS is second value

                    if (current_river == river and
                        current_reach == reach and
                        xs_rs == rs):
                        logger.debug(f"Found XS at line {i}: {river}/{reach}/RS {rs}")
                        return i

        logger.debug(f"XS not found: {river}/{reach}/RS {rs}")
        return None

    @staticmethod
    def _read_bank_stations(lines: List[str], start_idx: int,
                           search_range: Optional[int] = None) -> Optional[Tuple[float, float]]:
        """
        Read bank stations from XS block starting at start_idx.

        This helper eliminates ~40 lines of duplication across 4 public methods.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start searching (typically from _find_cross_section)
            search_range: Number of lines to search ahead (default: DEFAULT_SEARCH_RANGE)

        Returns:
            (left_bank, right_bank) tuple or None if no banks defined

        Example:
            >>> xs_idx = RasGeometry._find_cross_section(lines, river, reach, rs)
            >>> banks = RasGeometry._read_bank_stations(lines, xs_idx)
            >>> if banks:
            ...     left, right = banks
        """
        if search_range is None:
            search_range = RasGeometry.DEFAULT_SEARCH_RANGE

        for k in range(start_idx, min(start_idx + search_range, len(lines))):
            if lines[k].startswith("Bank Sta="):
                bank_str = RasGeometryUtils.extract_keyword_value(lines[k], "Bank Sta")
                bank_values = [v.strip() for v in bank_str.split(',')]
                if len(bank_values) >= 2:
                    left_bank = float(bank_values[0])
                    right_bank = float(bank_values[1])
                    logger.debug(f"Read bank stations: {left_bank}, {right_bank}")
                    return (left_bank, right_bank)

        return None

    @staticmethod
    def _parse_data_block(lines: List[str], start_idx: int, expected_count: int,
                         column_width: Optional[int] = None,
                         max_lines: Optional[int] = None) -> List[float]:
        """
        Parse fixed-width numeric data block following a count keyword.

        This helper eliminates ~120 lines of duplication across 8 public methods.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            expected_count: Number of values to read
            column_width: Character width of each column (default: FIXED_WIDTH_COLUMN)
            max_lines: Safety limit on lines to read (default: MAX_PARSE_LINES)

        Returns:
            List of parsed float values

        Example:
            >>> # After finding "#Sta/Elev= 40"
            >>> values = RasGeometry._parse_data_block(lines, count_line_idx + 1, 80)
            >>> # Returns 80 values (40 pairs)
        """
        if column_width is None:
            column_width = RasGeometry.FIXED_WIDTH_COLUMN
        if max_lines is None:
            max_lines = RasGeometry.MAX_PARSE_LINES

        values = []
        line_idx = start_idx

        while len(values) < expected_count and line_idx < len(lines):
            # Stop if hit next keyword
            if lines[line_idx].strip() and lines[line_idx].strip()[0].isupper():
                if '=' in lines[line_idx]:
                    break

            parsed = RasGeometryUtils.parse_fixed_width(lines[line_idx], column_width=column_width)
            values.extend(parsed)
            line_idx += 1

            # Safety check
            if line_idx > start_idx + max_lines:
                logger.warning(f"Exceeded max lines ({max_lines}) while parsing data block")
                break

        return values

    @staticmethod
    def _parse_paired_data(lines: List[str], start_idx: int, count: int,
                          col1_name: str = 'Station',
                          col2_name: str = 'Elevation') -> pd.DataFrame:
        """
        Parse paired data (station/elevation, elevation/volume, etc.) into DataFrame.

        This helper eliminates duplication in 5 public methods.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            count: Number of PAIRS (not total values)
            col1_name: Name for first column (default: 'Station')
            col2_name: Name for second column (default: 'Elevation')

        Returns:
            DataFrame with two columns

        Example:
            >>> # After finding "#Sta/Elev= 40" (means 40 pairs)
            >>> df = RasGeometry._parse_paired_data(lines, count_line_idx + 1, 40,
            ...                                     'Station', 'Elevation')
            >>> # Returns DataFrame with 40 rows, 2 columns
        """
        total_values = count * 2
        values = RasGeometry._parse_data_block(lines, start_idx, total_values)

        if len(values) != total_values:
            logger.warning(f"Expected {total_values} values, got {len(values)}")

        # Split into pairs
        col1_data = values[0::2]  # Every other value starting at 0
        col2_data = values[1::2]  # Every other value starting at 1

        return pd.DataFrame({col1_name: col1_data, col2_name: col2_data})

    # ========== PUBLIC API METHODS ==========

    @staticmethod
    @log_call
    def get_cross_sections(geom_file: Union[str, Path],
                          river: Optional[str] = None,
                          reach: Optional[str] = None) -> pd.DataFrame:
        """
        Extract cross section metadata from geometry file.

        Parses all cross sections and returns their metadata including
        river, reach, river station, type, and reach lengths.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (Optional[str]): Filter by specific river name. If None, returns all rivers.
            reach (Optional[str]): Filter by specific reach name. If None, returns all reaches.
                                  Note: If reach is specified, river must also be specified.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - River (str): River name
                - Reach (str): Reach name
                - RS (str): River station
                - Type (int): Cross section type (1=natural, etc.)
                - Length_Left (float): Left overbank length to next XS
                - Length_Channel (float): Channel length to next XS
                - Length_Right (float): Right overbank length to next XS
                - NodeName (str): Node name (if specified)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If reach specified without river

        Example:
            >>> # Get all cross sections
            >>> xs_df = RasGeometry.get_cross_sections("BaldEagle.g01")
            >>> print(f"Total XS: {len(xs_df)}")
            >>>
            >>> # Filter by river
            >>> xs_df = RasGeometry.get_cross_sections("BaldEagle.g01", river="Bald Eagle Creek")
            >>>
            >>> # Filter by river and reach
            >>> xs_df = RasGeometry.get_cross_sections("BaldEagle.g01",
            ...                                        river="Bald Eagle Creek",
            ...                                        reach="Reach 1")

        Notes:
            - Cross sections are listed in downstream order within each reach
            - Type codes: 1=natural, others vary by HEC-RAS version
            - Lengths are to the next downstream cross section
            - See 1D_geometry_structure.md Section 4 for format details
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if reach is not None and river is None:
            raise ValueError("If reach is specified, river must also be specified")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            cross_sections = []
            current_river = None
            current_reach = None

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(lines[i], "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]
                        logger.debug(f"Parsing {current_river} / {current_reach}")

                # Parse cross section metadata
                elif line.startswith("Type RM Length L Ch R ="):
                    if current_river is None or current_reach is None:
                        logger.warning(f"Found XS without river/reach at line {i}")
                        i += 1
                        continue

                    # Parse the metadata line
                    # Format: "Type RM Length L Ch R = TYPE, RS, Length_L, Length_Ch, Length_R"
                    value_str = RasGeometryUtils.extract_keyword_value(lines[i], "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]

                    if len(values) >= 4:
                        xs_type_code = int(values[0]) if values[0] else 1
                        rs = values[1]  # RS is second value, not first
                        try:
                            node_name = ""

                            # Look ahead for Node Name
                            j = i + 1
                            while j < len(lines) and j < i + 10:  # Look ahead max 10 lines
                                next_line = lines[j].strip()
                                if next_line.startswith("Node Name="):
                                    node_name = RasGeometryUtils.extract_keyword_value(lines[j], "Node Name")
                                if next_line.startswith("Type RM Length") or next_line.startswith("River Reach="):
                                    break
                                j += 1

                            # Use the type code we already extracted
                            xs_type = xs_type_code

                            # Lengths are values[2], values[3], values[4]
                            length_left = float(values[2]) if len(values) > 2 and values[2] else 0.0
                            length_channel = float(values[3]) if len(values) > 3 and values[3] else 0.0
                            length_right = float(values[4]) if len(values) > 4 and values[4] else 0.0

                            # Apply filters
                            if river is not None and current_river != river:
                                i += 1
                                continue
                            if reach is not None and current_reach != reach:
                                i += 1
                                continue

                            cross_sections.append({
                                'River': current_river,
                                'Reach': current_reach,
                                'RS': rs,
                                'Type': xs_type,
                                'Length_Left': length_left,
                                'Length_Channel': length_channel,
                                'Length_Right': length_right,
                                'NodeName': node_name
                            })

                        except (ValueError, IndexError) as e:
                            logger.warning(f"Error parsing XS at line {i}: {e}")

                i += 1

            df = pd.DataFrame(cross_sections)
            logger.info(f"Extracted {len(df)} cross sections from {geom_file.name}")

            if river is not None:
                logger.debug(f"Filtered to river '{river}': {len(df)} cross sections")
            if reach is not None:
                logger.debug(f"Filtered to reach '{reach}': {len(df)} cross sections")

            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting cross sections: {str(e)}")
            raise IOError(f"Failed to extract cross sections: {str(e)}")

    @staticmethod
    @log_call
    def get_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str) -> pd.DataFrame:
        """
        Extract station/elevation pairs for a cross section.

        Reads the cross section geometry data from the plain text geometry file.
        Uses fixed-width parsing (8-character columns) following FORTRAN conventions.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "138154.4")

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along cross section (ft or m)
                - Elevation (float): Ground elevation at station (ft or m)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If cross section not found

        Example:
            >>> sta_elev = RasGeometry.get_station_elevation(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "138154.4"
            ... )
            >>> print(f"XS has {len(sta_elev)} points")
            >>> print(f"Station range: {sta_elev['Station'].min():.1f} to {sta_elev['Station'].max():.1f}")
            >>> print(f"Elevation range: {sta_elev['Elevation'].min():.2f} to {sta_elev['Elevation'].max():.2f}")
            >>>
            >>> # Plot cross section
            >>> import matplotlib.pyplot as plt
            >>> plt.plot(sta_elev['Station'], sta_elev['Elevation'])
            >>> plt.xlabel('Station (ft)')
            >>> plt.ylabel('Elevation (ft)')
            >>> plt.title(f'{river} - {reach} - RS {rs}')

        Notes:
            - CRITICAL: Uses 8-character fixed-width parsing (NOT whitespace splitting)
            - Count interpretation: "#Sta/Elev= 40" means 40 PAIRS (80 total values)
            - Values alternate: station1, elev1, station2, elev2, ...
            - Typically 10 values per line (80 characters total)
            - See 1D_geometry_structure.md Section 4.6 for format details
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = RasGeometry._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Find #Sta/Elev= line within search range
            for j in range(xs_idx, min(xs_idx + RasGeometry.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract count
                    count_str = RasGeometryUtils.extract_keyword_value(lines[j], "#Sta/Elev")
                    count = int(count_str.strip())

                    logger.debug(f"#Sta/Elev= {count} (means {count} pairs)")

                    # Calculate total values using interpret_count (handles count interpretation)
                    total_values = RasGeometryUtils.interpret_count("#Sta/Elev", count)
                    logger.debug(f"Reading {total_values} total values ({count} pairs)")

                    # Parse paired data using helper
                    df = RasGeometry._parse_paired_data(
                        lines, j + 1, count, 'Station', 'Elevation'
                    )

                    logger.info(
                        f"Extracted {len(df)} station/elevation pairs for "
                        f"{river}/{reach}/RS {rs}"
                    )

                    return df

            # If we get here, #Sta/Elev not found for this XS
            raise ValueError(
                f"#Sta/Elev data not found for {river}/{reach}/RS {rs}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading station/elevation: {str(e)}")
            raise IOError(f"Failed to read station/elevation: {str(e)}")

    @staticmethod
    def _interpolate_at_banks(sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None) -> pd.DataFrame:
        """
        Interpolate elevation at bank stations and insert into station/elevation data.

        HEC-RAS REQUIRES that bank station values appear as exact points in the
        station/elevation data. This method ensures banks are interpolated and inserted.

        Parameters:
            sta_elev_df (pd.DataFrame): Station/elevation data
            bank_left (Optional[float]): Left bank station
            bank_right (Optional[float]): Right bank station

        Returns:
            pd.DataFrame: Modified DataFrame with banks interpolated and inserted

        Notes:
            - Uses linear interpolation between adjacent points
            - Inserts banks into sorted station list
            - Required for HEC-RAS compatibility
        """
        result_df = sta_elev_df.copy()

        # Interpolate and insert left bank if needed
        if bank_left is not None:
            stations = result_df['Station'].values
            elevations = result_df['Elevation'].values

            if bank_left not in stations:
                # Interpolate elevation at left bank
                bank_left_elev = np.interp(bank_left, stations, elevations)

                # Insert into DataFrame
                new_row = pd.DataFrame({'Station': [bank_left], 'Elevation': [bank_left_elev]})
                result_df = pd.concat([result_df, new_row], ignore_index=True)
                result_df = result_df.sort_values('Station').reset_index(drop=True)

                logger.debug(f"Interpolated left bank at station {bank_left:.2f}, elevation {bank_left_elev:.2f}")

        # Interpolate and insert right bank if needed
        if bank_right is not None:
            stations = result_df['Station'].values
            elevations = result_df['Elevation'].values

            if bank_right not in stations:
                # Interpolate elevation at right bank
                bank_right_elev = np.interp(bank_right, stations, elevations)

                # Insert into DataFrame
                new_row = pd.DataFrame({'Station': [bank_right], 'Elevation': [bank_right_elev]})
                result_df = pd.concat([result_df, new_row], ignore_index=True)
                result_df = result_df.sort_values('Station').reset_index(drop=True)

                logger.debug(f"Interpolated right bank at station {bank_right:.2f}, elevation {bank_right_elev:.2f}")

        return result_df

    @staticmethod
    @log_call
    def set_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str,
                             sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None):
        """
        Write station/elevation pairs to a cross section with automatic bank interpolation.

        Modifies the geometry file in-place, replacing the station/elevation data and
        optionally updating bank stations. Creates a .bak backup automatically.

        CRITICAL REQUIREMENTS (HEC-RAS compatibility):
        - Bank stations MUST appear as exact points in station/elevation data
        - This method automatically interpolates elevations at bank locations
        - Maximum 450 points per cross section (HEC-RAS hard limit)

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station
            sta_elev_df (pd.DataFrame): DataFrame with 'Station' and 'Elevation' columns
            bank_left (Optional[float]): Left bank station. If provided, updates bank in file.
                                         If None, reads existing banks and interpolates them.
            bank_right (Optional[float]): Right bank station. If provided, updates bank in file.

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If cross section not found, DataFrame invalid, or >450 points
            IOError: If file write fails

        Example:
            >>> # Simple elevation modification (banks auto-interpolated)
            >>> sta_elev = RasGeometry.get_station_elevation(geom_file, river, reach, rs)
            >>> sta_elev['Elevation'] += 1.0
            >>> RasGeometry.set_station_elevation(geom_file, river, reach, rs, sta_elev)
            >>>
            >>> # Modify geometry AND change bank stations
            >>> sta_elev = RasGeometry.get_station_elevation(geom_file, river, reach, rs)
            >>> RasGeometry.set_station_elevation(geom_file, river, reach, rs, sta_elev,
            ...                                   bank_left=200.0, bank_right=400.0)

        Notes:
            - ALWAYS interpolates elevation at bank stations (HEC-RAS requirement)
            - If banks not provided, reads existing banks from file
            - Validates max 450 points AFTER interpolation
            - Creates .bak backup before modification
            - Formats in 8-char fixed-width, 10 values per line
            - Updates "Bank Sta=" line if new banks provided
            - Stations must be in ascending order
            - Geometry preprocessor must be re-run after modification
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate DataFrame
        if not isinstance(sta_elev_df, pd.DataFrame):
            raise ValueError("sta_elev_df must be a pandas DataFrame")

        if 'Station' not in sta_elev_df.columns or 'Elevation' not in sta_elev_df.columns:
            raise ValueError("DataFrame must have 'Station' and 'Elevation' columns")

        if len(sta_elev_df) == 0:
            raise ValueError("DataFrame cannot be empty")

        # Validate banks if provided
        if bank_left is not None and bank_right is not None:
            if bank_left >= bank_right:
                raise ValueError(f"Left bank ({bank_left}) must be < right bank ({bank_right})")

        # Validate initial point count (before interpolation)
        if len(sta_elev_df) > RasGeometry.MAX_XS_POINTS:
            raise ValueError(
                f"Cross section has {len(sta_elev_df)} points, exceeds HEC-RAS limit of {RasGeometry.MAX_XS_POINTS} points.\n"
                f"Reduce point count by decimating or simplifying the cross section geometry."
            )

        try:
            # Create backup
            backup_path = RasGeometryUtils.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            i = RasGeometry._find_cross_section(lines, river, reach, rs)

            if i is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            modified_lines = lines.copy()

            # Read existing bank stations if not provided (using helper)
            existing_banks = None
            if bank_left is None or bank_right is None:
                existing_banks = RasGeometry._read_bank_stations(lines, i)

            # Use provided banks or existing banks
            if existing_banks:
                existing_bank_left, existing_bank_right = existing_banks
            else:
                existing_bank_left = existing_bank_right = None

            final_bank_left = bank_left if bank_left is not None else existing_bank_left
            final_bank_right = bank_right if bank_right is not None else existing_bank_right

            # Interpolate at bank stations (HEC-RAS requirement)
            sta_elev_with_banks = RasGeometry._interpolate_at_banks(
                sta_elev_df, final_bank_left, final_bank_right
            )

            # Validate point count AFTER interpolation (HEC-RAS limit)
            if len(sta_elev_with_banks) > RasGeometry.MAX_XS_POINTS:
                raise ValueError(
                    f"Cross section would have {len(sta_elev_with_banks)} points after bank interpolation, "
                    f"exceeds HEC-RAS limit of {RasGeometry.MAX_XS_POINTS} points.\n"
                    f"Original points: {len(sta_elev_df)}, added by interpolation: "
                    f"{len(sta_elev_with_banks) - len(sta_elev_df)}.\n"
                    f"Reduce point count before writing."
                )

            # Validate stations are in ascending order
            if not sta_elev_with_banks['Station'].is_monotonic_increasing:
                raise ValueError("Stations must be in ascending order")

            logger.info(
                f"Prepared geometry: {len(sta_elev_with_banks)} points "
                f"(original: {len(sta_elev_df)}, interpolated: "
                f"{len(sta_elev_with_banks) - len(sta_elev_df)})"
            )

            # Find #Sta/Elev= line
            for j in range(i, min(i + RasGeometry.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract old count
                    old_count_str = RasGeometryUtils.extract_keyword_value(lines[j], "#Sta/Elev")
                    old_count = int(old_count_str.strip())
                    old_total_values = RasGeometryUtils.interpret_count("#Sta/Elev", old_count)

                    # Calculate old data line count
                    old_data_lines = (old_total_values + RasGeometry.VALUES_PER_LINE - 1) // RasGeometry.VALUES_PER_LINE

                    # Prepare new data (using bank-interpolated DataFrame)
                    new_count = len(sta_elev_with_banks)

                    # Interleave station and elevation
                    new_values = []
                    for _, row in sta_elev_with_banks.iterrows():
                        new_values.append(row['Station'])
                        new_values.append(row['Elevation'])

                    # Format new data lines using constants
                    new_data_lines = RasGeometryUtils.format_fixed_width(
                        new_values,
                        column_width=RasGeometry.FIXED_WIDTH_COLUMN,
                        values_per_line=RasGeometry.VALUES_PER_LINE,
                        precision=2
                    )

                    # Update count line
                    modified_lines[j] = f"#Sta/Elev= {new_count}\n"

                    # Replace data lines
                    # Remove old data lines
                    for k in range(old_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = None  # Mark for deletion

                    # Insert new data lines
                    for k, data_line in enumerate(new_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = data_line
                        else:
                            # Append if needed
                            modified_lines.append(data_line)

                    # Clean up None entries
                    modified_lines = [line for line in modified_lines if line is not None]

                    # Update Bank Sta= line if new banks provided
                    if bank_left is not None and bank_right is not None:
                        # Find Bank Sta= line in the modified lines
                        bank_sta_updated = False
                        for k in range(i, min(i + RasGeometry.DEFAULT_SEARCH_RANGE, len(modified_lines))):
                            if modified_lines[k].startswith("Bank Sta="):
                                # Update with new bank stations (format: no spaces after comma)
                                modified_lines[k] = f"Bank Sta={bank_left:g},{bank_right:g}\n"
                                bank_sta_updated = True
                                logger.debug(f"Updated Bank Sta= line: {bank_left:g},{bank_right:g}")
                                break

                        if not bank_sta_updated:
                            logger.warning(f"Bank Sta= line not found for XS {rs}, banks not updated in file")

                    # Write modified file
                    with open(geom_file, 'w') as f:
                        f.writelines(modified_lines)

                    logger.info(
                        f"Updated station/elevation for {river}/{reach}/RS {rs}: "
                        f"{new_count} pairs written"
                    )

                    if bank_left is not None and bank_right is not None:
                        logger.info(f"Updated bank stations: {bank_left:g}, {bank_right:g}")

                    return

            raise ValueError(
                f"#Sta/Elev data not found for {river}/{reach}/RS {rs}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing station/elevation: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write station/elevation: {str(e)}")

    @staticmethod
    @log_call
    def get_storage_areas(geom_file: Union[str, Path],
                         exclude_2d: bool = True) -> List[str]:
        """
        Extract list of storage area names from geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            exclude_2d (bool, optional): If True, exclude 2D flow areas (Storage Area Is2D=-1).
                                        If False, include all storage areas. Defaults to True.

        Returns:
            List[str]: List of storage area names

        Example:
            >>> storage_areas = RasGeometry.get_storage_areas("BaldEagleDamBrk.g01")
            >>> print(f"Found {len(storage_areas)} storage areas")
            >>> print(storage_areas)
            ['Res Pool 1', 'Res Pool 2']

        Notes:
            - Storage areas can be traditional elevation-volume storage (Type 1)
            - Or 2D flow areas with "Storage Area Is2D=-1" flag
            - Use exclude_2d=False to include 2D flow areas in the list
            - See dam_break_structure.md for format details
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            storage_areas = []
            current_storage_name = None
            is_2d = None

            for line in lines:
                # Find storage area definition
                if line.startswith("Storage Area="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    values = [v.strip() for v in value_str.split(',')]
                    current_storage_name = values[0] if values else value_str
                    is_2d = None  # Reset for new storage area

                # Check if it's a 2D flow area
                elif line.startswith("Storage Area Is2D=") and current_storage_name:
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Storage Area Is2D")
                    is_2d_value = int(value_str.strip())

                    # Add to list based on filter
                    if exclude_2d:
                        if is_2d_value != -1:  # Not a 2D flow area
                            storage_areas.append(current_storage_name)
                    else:
                        storage_areas.append(current_storage_name)

                    current_storage_name = None  # Reset

            logger.info(f"Found {len(storage_areas)} storage areas in {geom_file.name}")

            return storage_areas

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting storage areas: {str(e)}")
            raise IOError(f"Failed to extract storage areas: {str(e)}")

    @staticmethod
    @log_call
    def get_storage_elevation_volume(geom_file: Union[str, Path],
                                     area_name: str) -> pd.DataFrame:
        """
        Extract storage area elevation-volume curve.

        Reads the elevation-volume relationship for a storage area, which defines
        how much volume is stored at each elevation.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            area_name (str): Storage area name (case-sensitive)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Elevation (float): Water surface elevation (ft or m)
                - Volume (float): Storage volume (cu ft or cu m)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If storage area not found or is a 2D flow area

        Example:
            >>> elev_vol = RasGeometry.get_storage_elevation_volume(
            ...     "BaldEagleDamBrk.g01", "Res Pool 1"
            ... )
            >>> print(f"Storage curve has {len(elev_vol)} points")
            >>> print(f"Volume range: {elev_vol['Volume'].min():.0f} to {elev_vol['Volume'].max():.0f} cu ft")
            >>>
            >>> # Plot storage curve
            >>> import matplotlib.pyplot as plt
            >>> plt.plot(elev_vol['Volume'], elev_vol['Elevation'])
            >>> plt.xlabel('Volume (cu ft)')
            >>> plt.ylabel('Elevation (ft)')
            >>> plt.title(f'Storage Area: {area_name}')

        Notes:
            - Uses 8-char fixed-width parsing for elevation/volume pairs
            - Count interpretation: "Storage Area Elev Volume= 53" means 53 PAIRS (106 values)
            - Only works for Type 1 storage areas (not 2D flow areas)
            - See dam_break_structure.md Section 2 for format details
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the storage area
            found_storage = False
            in_target_storage = False

            for i, line in enumerate(lines):
                # Find storage area by name
                if line.startswith("Storage Area="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    values = [v.strip() for v in value_str.split(',')]
                    current_name = values[0] if values else value_str
                    in_target_storage = (current_name == area_name)

                    if in_target_storage:
                        found_storage = True
                        logger.debug(f"Found storage area '{area_name}' at line {i}")

                # Check if it's a 2D flow area (can't extract elev-volume for 2D)
                elif line.startswith("Storage Area Is2D=") and in_target_storage:
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Storage Area Is2D")
                    if int(value_str.strip()) == -1:
                        raise ValueError(
                            f"Storage area '{area_name}' is a 2D flow area. "
                            f"Use get_2d_perimeter() instead."
                        )

                # Find elevation-volume data (keyword is "Vol Elev" not "Elev Volume")
                elif line.startswith("Storage Area Vol Elev=") and in_target_storage:
                    # Extract count
                    count_str = RasGeometryUtils.extract_keyword_value(line, "Storage Area Vol Elev")
                    count = int(count_str.strip())

                    logger.debug(f"Storage Area Vol Elev= {count} (means {count} pairs)")

                    # Parse elevation/volume data using helper
                    df = RasGeometry._parse_paired_data(
                        lines, i + 1, count, 'Elevation', 'Volume'
                    )

                    logger.info(f"Extracted {len(df)} elevation/volume pairs for '{area_name}'")

                    return df

            if not found_storage:
                raise ValueError(f"Storage area not found: {area_name}")

            # If we found the storage area but no elev-volume data
            raise ValueError(f"No elevation-volume data found for storage area: {area_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading storage elevation-volume: {str(e)}")
            raise IOError(f"Failed to read storage elevation-volume: {str(e)}")

    @staticmethod
    @log_call
    def get_lateral_structures(geom_file: Union[str, Path],
                               river: Optional[str] = None,
                               reach: Optional[str] = None) -> pd.DataFrame:
        """
        Extract lateral structure definitions from geometry file.

        Lateral structures are weirs, culverts, or other hydraulic structures along
        the side of a channel that connect to adjacent areas (detention basins,
        floodplains, irrigation ditches, etc.).

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (Optional[str]): Filter by specific river. If None, returns all rivers.
            reach (Optional[str]): Filter by specific reach. If None, returns all reaches.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - River (str): River name
                - Reach (str): Reach name
                - RS (str): River station where lateral structure is located
                - Position (int): Lateral position (0, 1, 2...)
                - Distance (float): Distance from XS (ft or m)
                - Width (float): Weir width (ft or m)
                - Coefficient (float): Weir discharge coefficient
                - Type (int): Lateral weir type code
                - SE_Count (int): Number of station-elevation pairs in profile
                - HW_RS (str): Headwater river station
                - HW_Distance (float): Headwater distance
                - Description (str): XS description (often describes the lateral)

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> lat_strucs = RasGeometry.get_lateral_structures("A100_00_00.g08")
            >>> print(f"Found {len(lat_strucs)} lateral structures")
            >>> print(lat_strucs[['River', 'Reach', 'RS', 'Distance', 'Width']])

        Notes:
            - Lateral structures appear as keywords after cross section definitions
            - Station-elevation profile follows "Lateral Weir SE=" keyword
            - Uses 8-char fixed-width parsing for profiles
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            lateral_structures = []
            current_river = None
            current_reach = None
            current_rs = None
            current_description = ""
            in_lateral = False
            lateral_data = {}

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(lines[i], "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track current cross section
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = RasGeometryUtils.extract_keyword_value(lines[i], "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    # Format: Type, RS, Length_L, Length_Ch, Length_R
                    # values[0] = Type, values[1] = RS
                    if len(values) > 1:
                        current_rs = values[1]
                    elif len(values) > 0:
                        current_rs = values[0]

                # Track description
                elif line.startswith("BEGIN DESCRIPTION:"):
                    current_description = ""
                    j = i + 1
                    while j < len(lines) and not lines[j].strip().startswith("END DESCRIPTION"):
                        current_description += lines[j].strip() + " "
                        j += 1
                    current_description = current_description.strip()

                # Detect lateral weir start
                elif line.startswith("Lateral Weir Pos="):
                    # If already in lateral, save the previous one first
                    if in_lateral and lateral_data:
                        if river is None or lateral_data['River'] == river:
                            if reach is None or lateral_data['Reach'] == reach:
                                lateral_structures.append(lateral_data)

                    # Start new lateral
                    in_lateral = True
                    lateral_data = {
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': current_rs,
                        'Description': current_description,
                        'Position': int(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir Pos"))
                    }
                    logger.debug(f"Started new lateral: {current_river}/{current_reach}/RS {current_rs}, line {i}")

                # Extract lateral weir parameters
                elif in_lateral:
                    # Check if starting a new lateral while already in one
                    if line.startswith("Lateral Weir Pos="):
                        print(f"DEBUG: Line {i} - New Lateral while in_lateral, saving previous")  # TEMP DEBUG
                        # Save previous lateral
                        if lateral_data:
                            print(f"DEBUG: lateral_data exists, checking filters")  # TEMP DEBUG
                            if river is None or lateral_data['River'] == river:
                                if reach is None or lateral_data['Reach'] == reach:
                                    lateral_structures.append(lateral_data)
                                    print(f"DEBUG: APPENDED! Total now: {len(lateral_structures)}")  # TEMP DEBUG

                        # Start new lateral
                        lateral_data = {
                            'River': current_river,
                            'Reach': current_reach,
                            'RS': current_rs,
                            'Description': current_description,
                            'Position': int(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir Pos"))
                        }

                    elif line.startswith("Lateral Weir Distance="):
                        lateral_data['Distance'] = float(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir Distance"))

                    elif line.startswith("Lateral Weir WD="):
                        lateral_data['Width'] = float(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir WD"))

                    elif line.startswith("Lateral Weir Coef="):
                        lateral_data['Coefficient'] = float(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir Coef"))

                    elif line.startswith("Lateral Weir Type="):
                        lateral_data['Type'] = int(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir Type"))

                    elif line.startswith("Lateral Weir SE="):
                        lateral_data['SE_Count'] = int(RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir SE"))

                    elif line.startswith("Lateral Weir HW RS Station="):
                        value_str = RasGeometryUtils.extract_keyword_value(lines[i], "Lateral Weir HW RS Station")
                        values = [v.strip() for v in value_str.split(',')]
                        lateral_data['HW_RS'] = values[0] if len(values) > 0 else ""
                        lateral_data['HW_Distance'] = float(values[1]) if len(values) > 1 and values[1] else 0.0

                    # End of lateral weir section
                    elif line.startswith("Type RM Length") or line.startswith("River Reach="):
                        # Save this lateral structure
                        if lateral_data:
                            # Apply filters
                            if river is None or lateral_data['River'] == river:
                                if reach is None or lateral_data['Reach'] == reach:
                                    lateral_structures.append(lateral_data)

                        in_lateral = False
                        lateral_data = {}
                        # Don't increment i, re-process this line
                        continue

                i += 1

            # Handle last lateral if file ends while in lateral section
            if in_lateral and lateral_data:
                if river is None or lateral_data['River'] == river:
                    if reach is None or lateral_data['Reach'] == reach:
                        lateral_structures.append(lateral_data)

            df = pd.DataFrame(lateral_structures)
            logger.info(f"Extracted {len(df)} lateral structures from {geom_file.name}")

            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting lateral structures: {str(e)}")
            raise IOError(f"Failed to extract lateral structures: {str(e)}")

    @staticmethod
    @log_call
    def get_lateral_weir_profile(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str,
                                  position: int = 0) -> pd.DataFrame:
        """
        Extract lateral weir station-elevation profile.

        Reads the weir crest profile which defines the spillway geometry.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station of cross section with lateral weir
            position (int, optional): Lateral weir position if multiple at same XS. Defaults to 0.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along weir (ft or m)
                - Elevation (float): Weir crest elevation at station (ft or m)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If lateral weir not found

        Example:
            >>> profile = RasGeometry.get_lateral_weir_profile(
            ...     "A100_00_00.g08", "A100", "A100", "16473", position=0
            ... )
            >>> print(f"Weir profile has {len(profile)} points")
            >>>
            >>> # Plot weir profile
            >>> import matplotlib.pyplot as plt
            >>> plt.plot(profile['Station'], profile['Elevation'])
            >>> plt.xlabel('Station (ft)')
            >>> plt.ylabel('Elevation (ft)')
            >>> plt.title('Lateral Weir Crest Profile')

        Notes:
            - Uses 8-char fixed-width parsing
            - Count from "Lateral Weir SE=" indicates number of pairs
            - Profile data appears after SE count line
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the lateral weir
            current_river = None
            current_reach = None
            current_rs = None
            in_target_lateral = False
            found_lateral = False

            for i, line in enumerate(lines):
                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track current cross section
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    # Format: Type, RS, Length_L, Length_Ch, Length_R
                    # values[0] = Type, values[1] = RS
                    if len(values) > 1:
                        current_rs = values[1]
                    elif len(values) > 0:
                        current_rs = values[0]

                # Check for matching lateral weir
                elif line.startswith("Lateral Weir Pos="):
                    pos = int(RasGeometryUtils.extract_keyword_value(line, "Lateral Weir Pos"))

                    if (current_river == river and
                        current_reach == reach and
                        current_rs == rs and
                        pos == position):
                        in_target_lateral = True
                        found_lateral = True
                        logger.debug(f"Found lateral weir at {river}/{reach}/RS {rs}, pos {position}")

                # Extract station-elevation data
                elif line.startswith("Lateral Weir SE=") and in_target_lateral:
                    # Extract count
                    count_str = RasGeometryUtils.extract_keyword_value(line, "Lateral Weir SE")
                    count = int(count_str.strip())

                    logger.debug(f"Lateral Weir SE= {count} (means {count} pairs)")

                    # Parse station/elevation data using helper (note: max_lines=20 for lateral weirs)
                    df = RasGeometry._parse_paired_data(
                        lines, i + 1, count, 'Station', 'Elevation'
                    )

                    logger.info(
                        f"Extracted {len(df)} station/elevation pairs for "
                        f"lateral weir at {river}/{reach}/RS {rs}, pos {position}"
                    )

                    return df

                # End of lateral weir section
                elif line.startswith("Type RM Length") and in_target_lateral:
                    in_target_lateral = False

            if not found_lateral:
                raise ValueError(
                    f"Lateral weir not found: {river}/{reach}/RS {rs}, position {position}"
                )

            # If found but no SE data
            raise ValueError(
                f"No station-elevation profile found for lateral weir at "
                f"{river}/{reach}/RS {rs}, position {position}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading lateral weir profile: {str(e)}")
            raise IOError(f"Failed to read lateral weir profile: {str(e)}")

    @staticmethod
    @log_call
    def get_connections(geom_file: Union[str, Path]) -> pd.DataFrame:
        """
        Extract all SA/2D area connection definitions.

        Connections link storage areas to 2D flow areas (or 2D to 2D) for
        dam breach modeling, levee overtopping, or floodplain connectivity.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Connection_Name (str): Connection name
                - Upstream_Area (str): Upstream storage/2D area name
                - Downstream_Area (str): Downstream storage/2D area name
                - Weir_Width (float): Weir width (ft or m)
                - Weir_Coefficient (float): Weir discharge coefficient
                - SE_Count (int): Number of station-elevation pairs in weir profile
                - Num_Gates (int): Number of gates in connection
                - Routing_Type (int): Connection routing type

        Example:
            >>> connections = RasGeometry.get_connections("BaldEagleDamBrk.g01")
            >>> print(f"Found {len(connections)} connections")
            >>> print(connections[['Connection_Name', 'Upstream_Area', 'Downstream_Area']])

        Notes:
            - Connections defined with "Connection=" keyword
            - Format: Connection=Name,X,Y
            - See dam_break_structure.md for complete format details
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            connections = []
            in_connection = False
            conn_data = {}

            for i, line in enumerate(lines):
                # Detect connection start
                if line.startswith("Connection="):
                    # Save previous connection if exists
                    if in_connection and conn_data:
                        connections.append(conn_data)

                    in_connection = True
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Connection")
                    # Format: Name,X,Y
                    values = [v.strip() for v in value_str.split(',')]
                    conn_name = values[0] if values else value_str

                    conn_data = {'Connection_Name': conn_name}

                # Extract connection parameters
                elif in_connection:
                    if line.startswith("Connection Up SA="):
                        conn_data['Upstream_Area'] = RasGeometryUtils.extract_keyword_value(line, "Connection Up SA").strip()

                    elif line.startswith("Connection Dn SA="):
                        conn_data['Downstream_Area'] = RasGeometryUtils.extract_keyword_value(line, "Connection Dn SA").strip()

                    elif line.startswith("Conn Routing Type="):
                        conn_data['Routing_Type'] = int(RasGeometryUtils.extract_keyword_value(line, "Conn Routing Type"))

                    elif line.startswith("Conn Weir WD="):
                        conn_data['Weir_Width'] = float(RasGeometryUtils.extract_keyword_value(line, "Conn Weir WD"))

                    elif line.startswith("Conn Weir Coef="):
                        conn_data['Weir_Coefficient'] = float(RasGeometryUtils.extract_keyword_value(line, "Conn Weir Coef"))

                    elif line.startswith("Conn Weir SE="):
                        conn_data['SE_Count'] = int(RasGeometryUtils.extract_keyword_value(line, "Conn Weir SE"))

                    # Count gates
                    elif line.startswith("Conn Gate Name"):
                        # Count gate lines (lines starting with "Gate #")
                        num_gates = 0
                        j = i + 1
                        while j < len(lines) and lines[j].startswith("Gate #"):
                            num_gates += 1
                            j += 1
                        conn_data['Num_Gates'] = num_gates

                    # End of connection when hitting storage area
                    elif line.startswith("Storage Area="):
                        if conn_data:
                            connections.append(conn_data)
                        in_connection = False
                        conn_data = {}
                        continue  # Don't increment i

            # Handle last connection if file ends
            if in_connection and conn_data:
                connections.append(conn_data)

            df = pd.DataFrame(connections)

            # Ensure Num_Gates column exists
            if 'Num_Gates' not in df.columns:
                df['Num_Gates'] = 0

            logger.info(f"Extracted {len(df)} connections from {geom_file.name}")

            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting connections: {str(e)}")
            raise IOError(f"Failed to extract connections: {str(e)}")

    @staticmethod
    @log_call
    def get_connection_weir_profile(geom_file: Union[str, Path],
                                    connection_name: str) -> pd.DataFrame:
        """
        Extract weir/dam crest station-elevation profile for a connection.

        Reads the weir crest geometry which defines the spillway or dam crest elevation
        as a function of station along the connection.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            connection_name (str): Connection name (case-sensitive)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along weir/dam crest (ft or m)
                - Elevation (float): Crest elevation at station (ft or m)

        Example:
            >>> profile = RasGeometry.get_connection_weir_profile(
            ...     "BaldEagleDamBrk.g01", "Dam"
            ... )
            >>> print(f"Dam crest has {len(profile)} station/elevation points")
            >>> plt.plot(profile['Station'], profile['Elevation'])

        Notes:
            - Uses 8-char fixed-width parsing
            - Count from "Conn Weir SE=" indicates number of pairs
            - Profile data follows SE count line
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the connection
            in_target_conn = False
            found_conn = False

            for i, line in enumerate(lines):
                # Find connection by name
                if line.startswith("Connection="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Connection")
                    values = [v.strip() for v in value_str.split(',')]
                    current_name = values[0] if values else value_str

                    in_target_conn = (current_name == connection_name)
                    if in_target_conn:
                        found_conn = True
                        logger.debug(f"Found connection '{connection_name}' at line {i}")

                # Extract weir profile
                elif line.startswith("Conn Weir SE=") and in_target_conn:
                    count_str = RasGeometryUtils.extract_keyword_value(line, "Conn Weir SE")
                    count = int(count_str.strip())

                    logger.debug(f"Conn Weir SE= {count} (means {count} pairs)")

                    # Parse station/elevation data using helper
                    df = RasGeometry._parse_paired_data(
                        lines, i + 1, count, 'Station', 'Elevation'
                    )

                    logger.info(
                        f"Extracted {len(df)} station/elevation pairs for "
                        f"connection '{connection_name}'"
                    )

                    return df

                # End of connection
                elif line.startswith("Connection=") and in_target_conn:
                    in_target_conn = False

            if not found_conn:
                raise ValueError(f"Connection not found: {connection_name}")

            # If found but no SE data
            raise ValueError(f"No weir profile found for connection: {connection_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection weir profile: {str(e)}")
            raise IOError(f"Failed to read connection weir profile: {str(e)}")

    @staticmethod
    @log_call
    def get_connection_gates(geom_file: Union[str, Path],
                            connection_name: str) -> pd.DataFrame:
        """
        Extract gate definitions for a connection.

        Reads gate parameters in CSV format (23+ fields per gate).

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            connection_name (str): Connection name

        Returns:
            pd.DataFrame: DataFrame with gate parameters (columns vary by gate data)
                Typical columns include:
                - Gate_Name, Width, Height, Invert, Gate_Coefficient,
                - Expansion_T, Expansion_O, Expansion_H, Type, Weir_Coefficient,
                - Is_Ogee, Spill_Height, Design_Head, Num_Openings, etc.

        Example:
            >>> gates = RasGeometry.get_connection_gates("BaldEagleDamBrk.g01", "Dam")
            >>> if not gates.empty:
            ...     print(gates[['Gate_Name', 'Width', 'Height', 'Invert']])

        Notes:
            - Gate data is CSV format with 23+ fields
            - Header line: "Conn Gate Name Wd,H,Inv,GCoef,..."
            - Data lines: "Gate #1     ,7,15,590,..."
            - Returns empty DataFrame if no gates
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the connection
            in_target_conn = False
            gates = []

            for i, line in enumerate(lines):
                # Find connection by name
                if line.startswith("Connection="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Connection")
                    values = [v.strip() for v in value_str.split(',')]
                    current_name = values[0] if values else value_str

                    in_target_conn = (current_name == connection_name)

                # Find gate definitions
                elif line.startswith("Conn Gate Name") and in_target_conn:
                    # Next lines contain gate data
                    j = i + 1
                    while j < len(lines) and lines[j].startswith("Gate #"):
                        gate_line = lines[j].strip()
                        # Parse CSV
                        gate_values = [v.strip() for v in gate_line.split(',')]

                        # Build gate dict (using simplified field names)
                        gate_dict = {
                            'Gate_Name': gate_values[0] if len(gate_values) > 0 else "",
                            'Width': float(gate_values[1]) if len(gate_values) > 1 and gate_values[1] else 0.0,
                            'Height': float(gate_values[2]) if len(gate_values) > 2 and gate_values[2] else 0.0,
                            'Invert': float(gate_values[3]) if len(gate_values) > 3 and gate_values[3] else 0.0,
                            'Gate_Coefficient': float(gate_values[4]) if len(gate_values) > 4 and gate_values[4] else 0.0,
                        }

                        # Add remaining fields as generic Gate_Param_N
                        for idx in range(5, len(gate_values)):
                            if gate_values[idx]:
                                gate_dict[f'Gate_Param_{idx}'] = gate_values[idx]

                        gates.append(gate_dict)
                        j += 1

                    break  # Found gates, stop searching

                # End of connection
                elif line.startswith("Connection=") and in_target_conn:
                    break

            df = pd.DataFrame(gates)

            if len(df) > 0:
                logger.info(f"Extracted {len(df)} gates for connection '{connection_name}'")
            else:
                logger.info(f"No gates found for connection '{connection_name}'")

            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection gates: {str(e)}")
            raise IOError(f"Failed to read connection gates: {str(e)}")

    @staticmethod
    @log_call
    def get_bank_stations(geom_file: Union[str, Path],
                         river: str,
                         reach: str,
                         rs: str) -> Optional[Tuple[float, float]]:
        """
        Extract left and right bank station locations for a cross section.

        Bank stations define the boundary between overbank areas and the main channel,
        used for subsection conveyance calculations.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            Optional[Tuple[float, float]]: (left_bank, right_bank) or None if no banks defined

        Example:
            >>> banks = RasGeometry.get_bank_stations("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> if banks:
            ...     left, right = banks
            ...     print(f"Bank stations: Left={left}, Right={right}")
            ...     print(f"Main channel width: {right - left} ft")

        Notes:
            - Format: Bank Sta=<left>,<right> (CSV, no spaces)
            - Returns None for cross sections without banks (bridges, inline structures)
            - ~10% of cross sections don't have bank stations
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = RasGeometry._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Read bank stations using helper
            banks = RasGeometry._read_bank_stations(lines, xs_idx)

            if banks:
                left_bank, right_bank = banks
                logger.info(f"Extracted bank stations for {river}/{reach}/RS {rs}: {left_bank}, {right_bank}")
                return banks
            else:
                logger.info(f"No bank stations found for {river}/{reach}/RS {rs}")
                return None

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bank stations: {str(e)}")
            raise IOError(f"Failed to read bank stations: {str(e)}")

    @staticmethod
    @log_call
    def get_expansion_contraction(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str) -> Tuple[float, float]:
        """
        Extract expansion and contraction coefficients for a cross section.

        These coefficients account for energy losses due to flow expansion
        (downstream) and contraction (upstream) at cross sections.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            Tuple[float, float]: (expansion, contraction) coefficients

        Example:
            >>> exp, cntr = RasGeometry.get_expansion_contraction(
            ...     "BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4"
            ... )
            >>> print(f"Expansion: {exp}, Contraction: {cntr}")
            >>> # Typical values: expansion=0.3, contraction=0.1

        Notes:
            - Format: Exp/Cntr=<expansion>,<contraction> (CSV, no spaces)
            - Default values if not specified: 0.3 (expansion), 0.1 (contraction)
            - Used in energy loss calculations between cross sections
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = RasGeometry._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Find Exp/Cntr= line within search range
            for j in range(xs_idx, min(xs_idx + RasGeometry.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("Exp/Cntr="):
                    exp_cntr_str = RasGeometryUtils.extract_keyword_value(lines[j], "Exp/Cntr")
                    values = [v.strip() for v in exp_cntr_str.split(',')]

                    if len(values) >= 2:
                        expansion = float(values[0])
                        contraction = float(values[1])

                        logger.info(
                            f"Extracted expansion/contraction for {river}/{reach}/RS {rs}: "
                            f"{expansion}, {contraction}"
                        )
                        return (expansion, contraction)

            # XS found but no Exp/Cntr= (use defaults)
            logger.info(f"No Exp/Cntr found for {river}/{reach}/RS {rs}, using defaults")
            return (0.3, 0.1)  # HEC-RAS defaults

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading expansion/contraction: {str(e)}")
            raise IOError(f"Failed to read expansion/contraction: {str(e)}")

    @staticmethod
    @log_call
    def get_mannings_n(geom_file: Union[str, Path],
                      river: str,
                      reach: str,
                      rs: str) -> pd.DataFrame:
        """
        Extract Manning's n roughness values for a cross section.

        Manning's n values define channel roughness and are organized by subsections
        (Left Overbank, Main Channel, Right Overbank) based on bank station locations.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station where this Manning's n value starts
                - n_value (float): Manning's roughness coefficient
                - Subsection (str): 'LOB' (Left Overbank), 'Channel', or 'ROB' (Right Overbank)

        Example:
            >>> mann = RasGeometry.get_mannings_n("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> print(mann)
               Station  n_value Subsection
            0      0.0     0.06        LOB
            1    190.0     0.04    Channel
            2    375.0     0.10        ROB
            >>>
            >>> # Calculate average channel Manning's n
            >>> channel_n = mann[mann['Subsection'] == 'Channel']['n_value'].mean()

        Notes:
            - Format: #Mann= <count> , 0 , 0 (standard 3-segment L-MC-R)
            - Data: Triplets (station, n_value, 0) in 8-char fixed-width
            - Subsection classification uses bank stations
            - Supports standard format (3 segments) and variable segments
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = RasGeometry._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Get bank stations using helper (for subsection classification)
            banks = RasGeometry._read_bank_stations(lines, xs_idx)
            bank_left = bank_right = None
            if banks:
                bank_left, bank_right = banks

            # Find #Mann= line
            for j in range(xs_idx, min(xs_idx + RasGeometry.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Mann="):
                    # Extract count
                    mann_str = RasGeometryUtils.extract_keyword_value(lines[j], "#Mann")
                    count_values = [v.strip() for v in mann_str.split(',')]

                    num_segments = int(count_values[0]) if count_values[0] else 0
                    format_flag = int(count_values[1]) if len(count_values) > 1 and count_values[1] else 0

                    logger.debug(f"Manning's n: {num_segments} segments, format={format_flag}")

                    # Calculate total values to read (triplets)
                    total_values = num_segments * 3

                    # Parse Manning's n data using helper (note: max_lines=20 for Manning's n)
                    values = RasGeometry._parse_data_block(
                        lines, j + 1, total_values,
                        column_width=RasGeometry.FIXED_WIDTH_COLUMN,
                        max_lines=20
                    )

                    # Convert triplets to DataFrame
                    segments = []
                    for seg_idx in range(0, len(values), 3):
                        if seg_idx + 2 < len(values):
                            station = values[seg_idx]
                            n_value = values[seg_idx + 1]
                            # values[seg_idx + 2] is always 0, ignore

                            # Classify subsection based on bank stations
                            if bank_left is not None and bank_right is not None:
                                if station < bank_left:
                                    subsection = 'LOB'
                                elif station < bank_right:
                                    subsection = 'Channel'
                                else:
                                    subsection = 'ROB'
                            else:
                                subsection = 'Unknown'

                            segments.append({
                                'Station': station,
                                'n_value': n_value,
                                'Subsection': subsection
                            })

                    df = pd.DataFrame(segments)

                    logger.info(
                        f"Extracted {len(df)} Manning's n segments for {river}/{reach}/RS {rs}"
                    )

                    return df

            # XS found but no Manning's n
            raise ValueError(f"No Manning's n data found for {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading Manning's n: {str(e)}")
            raise IOError(f"Failed to read Manning's n: {str(e)}")
