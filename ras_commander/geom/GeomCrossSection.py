"""
GeomCrossSection - 1D Cross section operations for HEC-RAS geometry files

This module provides comprehensive functionality for reading and modifying
HEC-RAS 1D cross section data in plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_cross_sections() - Extract all cross section metadata
- get_station_elevation() - Read station/elevation pairs for a cross section
- set_station_elevation() - Write station/elevation with automatic bank interpolation
- get_bank_stations() - Read left and right bank station locations
- get_expansion_contraction() - Read expansion and contraction coefficients
- get_mannings_n() - Read Manning's roughness values with LOB/Channel/ROB classification

Example Usage:
    >>> from ras_commander import GeomCrossSection
    >>> from pathlib import Path
    >>>
    >>> # List all cross sections
    >>> geom_file = Path("BaldEagle.g01")
    >>> xs_df = GeomCrossSection.get_cross_sections(geom_file)
    >>> print(f"Found {len(xs_df)} cross sections")
    >>>
    >>> # Get station/elevation for specific XS
    >>> sta_elev = GeomCrossSection.get_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4"
    ... )
    >>> print(sta_elev.head())
    >>>
    >>> # Modify and write back
    >>> sta_elev['Elevation'] += 1.0  # Raise XS by 1 foot
    >>> GeomCrossSection.set_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4", sta_elev
    ... )

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Count interpretation: "#Sta/Elev= 40" means 40 PAIRS (80 total values)
    - Always creates .bak backup before modification
"""

from pathlib import Path
from typing import Union, Optional, List, Tuple
import pandas as pd
import numpy as np
import math

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomCrossSection:
    """
    Operations for parsing and modifying HEC-RAS 1D cross sections.

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

        Args:
            lines: File lines (from readlines())
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string, e.g., "138154.4")

        Returns:
            Line index where "Type RM Length L Ch R =" for matching XS starts,
            or None if not found
        """
        current_river = None
        current_reach = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Find matching cross section
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
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

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start searching (typically from _find_cross_section)
            search_range: Number of lines to search ahead (default: DEFAULT_SEARCH_RANGE)

        Returns:
            (left_bank, right_bank) tuple or None if no banks defined
        """
        if search_range is None:
            search_range = GeomCrossSection.DEFAULT_SEARCH_RANGE

        for k in range(start_idx, min(start_idx + search_range, len(lines))):
            if lines[k].startswith("Bank Sta="):
                bank_str = GeomParser.extract_keyword_value(lines[k], "Bank Sta")
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

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            expected_count: Number of values to read
            column_width: Character width of each column (default: FIXED_WIDTH_COLUMN)
            max_lines: Safety limit on lines to read (default: MAX_PARSE_LINES)

        Returns:
            List of parsed float values
        """
        if column_width is None:
            column_width = GeomCrossSection.FIXED_WIDTH_COLUMN
        if max_lines is None:
            max_lines = GeomCrossSection.MAX_PARSE_LINES

        values = []
        line_idx = start_idx

        while len(values) < expected_count and line_idx < len(lines):
            # Stop if hit next keyword
            if lines[line_idx].strip() and lines[line_idx].strip()[0].isupper():
                if '=' in lines[line_idx]:
                    break

            parsed = GeomParser.parse_fixed_width(lines[line_idx], column_width=column_width)
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

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            count: Number of PAIRS (not total values)
            col1_name: Name for first column (default: 'Station')
            col2_name: Name for second column (default: 'Elevation')

        Returns:
            DataFrame with two columns
        """
        total_values = count * 2
        values = GeomCrossSection._parse_data_block(lines, start_idx, total_values)

        if len(values) != total_values:
            logger.warning(f"Expected {total_values} values, got {len(values)}")

        # Split into pairs
        col1_data = values[0::2]  # Every other value starting at 0
        col2_data = values[1::2]  # Every other value starting at 1

        return pd.DataFrame({col1_name: col1_data, col2_name: col2_data})

    @staticmethod
    def _interpolate_at_banks(sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None) -> pd.DataFrame:
        """
        Interpolate elevation at bank stations and insert into station/elevation data.

        HEC-RAS REQUIRES that bank station values appear as exact points in the
        station/elevation data. This method ensures banks are interpolated and inserted.

        Args:
            sta_elev_df: Station/elevation data
            bank_left: Left bank station
            bank_right: Right bank station

        Returns:
            Modified DataFrame with banks interpolated and inserted
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
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01")
            >>> print(f"Total XS: {len(xs_df)}")
            >>>
            >>> # Filter by river
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01", river="Bald Eagle Creek")
            >>>
            >>> # Filter by river and reach
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01",
            ...                                        river="Bald Eagle Creek",
            ...                                        reach="Reach 1")
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
                    values = GeomParser.extract_comma_list(lines[i], "River Reach")
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
                    value_str = GeomParser.extract_keyword_value(lines[i], "Type RM Length L Ch R")
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
                                    node_name = GeomParser.extract_keyword_value(lines[j], "Node Name")
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
            logger.debug(f"Extracted {len(df)} cross sections from {geom_file.name}")

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
            >>> sta_elev = GeomCrossSection.get_station_elevation(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "138154.4"
            ... )
            >>> print(f"XS has {len(sta_elev)} points")
            >>> print(f"Station range: {sta_elev['Station'].min():.1f} to {sta_elev['Station'].max():.1f}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Find #Sta/Elev= line within search range
            for j in range(xs_idx, min(xs_idx + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract count
                    count_str = GeomParser.extract_keyword_value(lines[j], "#Sta/Elev")
                    count = int(count_str.strip())

                    logger.debug(f"#Sta/Elev= {count} (means {count} pairs)")

                    # Parse paired data using helper
                    df = GeomCrossSection._parse_paired_data(
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
            >>> sta_elev = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
            >>> sta_elev['Elevation'] += 1.0
            >>> GeomCrossSection.set_station_elevation(geom_file, river, reach, rs, sta_elev)
            >>>
            >>> # Modify geometry AND change bank stations
            >>> GeomCrossSection.set_station_elevation(geom_file, river, reach, rs, sta_elev,
            ...                                   bank_left=200.0, bank_right=400.0)
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
        if len(sta_elev_df) > GeomCrossSection.MAX_XS_POINTS:
            raise ValueError(
                f"Cross section has {len(sta_elev_df)} points, exceeds HEC-RAS limit of {GeomCrossSection.MAX_XS_POINTS} points.\n"
                f"Reduce point count by decimating or simplifying the cross section geometry."
            )

        try:
            # Create backup
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            i = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if i is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            modified_lines = lines.copy()

            # Read existing bank stations if not provided (using helper)
            existing_banks = None
            if bank_left is None or bank_right is None:
                existing_banks = GeomCrossSection._read_bank_stations(lines, i)

            # Use provided banks or existing banks
            if existing_banks:
                existing_bank_left, existing_bank_right = existing_banks
            else:
                existing_bank_left = existing_bank_right = None

            final_bank_left = bank_left if bank_left is not None else existing_bank_left
            final_bank_right = bank_right if bank_right is not None else existing_bank_right

            # Interpolate at bank stations (HEC-RAS requirement)
            sta_elev_with_banks = GeomCrossSection._interpolate_at_banks(
                sta_elev_df, final_bank_left, final_bank_right
            )

            # Validate point count AFTER interpolation (HEC-RAS limit)
            if len(sta_elev_with_banks) > GeomCrossSection.MAX_XS_POINTS:
                raise ValueError(
                    f"Cross section would have {len(sta_elev_with_banks)} points after bank interpolation, "
                    f"exceeds HEC-RAS limit of {GeomCrossSection.MAX_XS_POINTS} points.\n"
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
            for j in range(i, min(i + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract old count
                    old_count_str = GeomParser.extract_keyword_value(lines[j], "#Sta/Elev")
                    old_count = int(old_count_str.strip())
                    old_total_values = GeomParser.interpret_count("#Sta/Elev", old_count)

                    # Calculate old data line count
                    old_data_lines = (old_total_values + GeomCrossSection.VALUES_PER_LINE - 1) // GeomCrossSection.VALUES_PER_LINE

                    # Prepare new data (using bank-interpolated DataFrame)
                    new_count = len(sta_elev_with_banks)

                    # Interleave station and elevation
                    new_values = []
                    for _, row in sta_elev_with_banks.iterrows():
                        new_values.append(row['Station'])
                        new_values.append(row['Elevation'])

                    # Format new data lines using constants
                    new_data_lines = GeomParser.format_fixed_width(
                        new_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
                        values_per_line=GeomCrossSection.VALUES_PER_LINE,
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
                        for k in range(i, min(i + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(modified_lines))):
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
            >>> banks = GeomCrossSection.get_bank_stations("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> if banks:
            ...     left, right = banks
            ...     print(f"Bank stations: Left={left}, Right={right}")
            ...     print(f"Main channel width: {right - left} ft")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Read bank stations using helper
            banks = GeomCrossSection._read_bank_stations(lines, xs_idx)

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
            >>> exp, cntr = GeomCrossSection.get_expansion_contraction(
            ...     "BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4"
            ... )
            >>> print(f"Expansion: {exp}, Contraction: {cntr}")
            >>> # Typical values: expansion=0.3, contraction=0.1
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Find Exp/Cntr= line within search range
            for j in range(xs_idx, min(xs_idx + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("Exp/Cntr="):
                    exp_cntr_str = GeomParser.extract_keyword_value(lines[j], "Exp/Cntr")
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
            >>> mann = GeomCrossSection.get_mannings_n("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> print(mann)
               Station  n_value Subsection
            0      0.0     0.06        LOB
            1    190.0     0.04    Channel
            2    375.0     0.10        ROB
            >>>
            >>> # Calculate average channel Manning's n
            >>> channel_n = mann[mann['Subsection'] == 'Channel']['n_value'].mean()
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Get bank stations using helper (for subsection classification)
            banks = GeomCrossSection._read_bank_stations(lines, xs_idx)
            bank_left = bank_right = None
            if banks:
                bank_left, bank_right = banks

            # Find #Mann= line
            for j in range(xs_idx, min(xs_idx + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Mann="):
                    # Extract count
                    mann_str = GeomParser.extract_keyword_value(lines[j], "#Mann")
                    count_values = [v.strip() for v in mann_str.split(',')]

                    num_segments = int(count_values[0]) if count_values[0] else 0
                    format_flag = int(count_values[1]) if len(count_values) > 1 and count_values[1] else 0

                    logger.debug(f"Manning's n: {num_segments} segments, format={format_flag}")

                    # Calculate total values to read (triplets)
                    total_values = num_segments * 3

                    # Parse Manning's n data using helper (note: max_lines=20 for Manning's n)
                    values = GeomCrossSection._parse_data_block(
                        lines, j + 1, total_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
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

    @staticmethod
    @log_call
    def get_xs_htab_params(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str) -> dict:
        """
        Read cross section HTAB (hydraulic table) parameters from geometry file.

        HTAB parameters control how HEC-RAS pre-computes hydraulic properties
        (area, conveyance, storage) as a function of elevation. These tables are
        used during unsteady flow simulations for fast lookup via interpolation.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "5280")

        Returns:
            dict with keys:
                - 'starting_el' (float or None): Starting elevation for HTAB
                - 'increment' (float or None): Elevation increment between points
                - 'num_points' (int or None): Number of points in HTAB
                - 'invert' (float): Lowest elevation in cross section
                - 'top' (float): Highest elevation in cross section
                - 'has_htab_lines' (bool): True if explicit HTAB lines found in file

        Notes:
            - Handles two geometry file formats:
              1. Combined format: "XS HTab Starting El and Incr=val1,val2, val3"
              2. Separate format: "HTAB Starting El and Incr=" and "HTAB Number of Points="
            - If HTAB lines are not present, starting_el/increment/num_points will be None
              (HEC-RAS uses defaults: starting=invert+0.5-1.0, increment=1.0, points~20)
            - invert/top are always computed from station-elevation data

        Example:
            >>> params = GeomCrossSection.get_xs_htab_params(
            ...     "Muncie.g01", "White", "Muncie", "15696.24"
            ... )
            >>> print(f"Starting El: {params['starting_el']}")
            >>> print(f"Increment: {params['increment']}")
            >>> print(f"Num Points: {params['num_points']}")
            >>> print(f"Invert: {params['invert']}, Top: {params['top']}")
            >>> if not params['has_htab_lines']:
            ...     print("No HTAB lines - using HEC-RAS defaults")
        """
        import re
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Regex patterns for both HTAB formats
        # Format 1 (combined): XS HTab Starting El and Incr=937.99,0.5, 100
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )

        # Format 2 (separate lines):
        # HTAB Starting El and Incr=     580.0,      0.5
        # HTAB Number of Points= 100
        HTAB_START_PATTERN = re.compile(
            r'^HTAB Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*$'
        )
        HTAB_POINTS_PATTERN = re.compile(
            r'^HTAB Number of Points=\s*(\d+)\s*$'
        )

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Initialize result dict
            params = {
                'starting_el': None,
                'increment': None,
                'num_points': None,
                'invert': None,
                'top': None,
                'has_htab_lines': False
            }

            # Search forward from XS start
            # Need extended range because "XS HTab" combined format appears AFTER
            # station-elevation data, which can be 100+ lines for large XS
            max_search_range = 200  # Extended range for combined HTAB format
            for i in range(xs_idx, min(xs_idx + max_search_range, len(lines))):
                line = lines[i].rstrip('\n\r')

                # Stop at next XS or structure
                if line.startswith("River Reach=") and i > xs_idx + 5:
                    break
                if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                    break

                # Try Format 1: Combined line (XS HTab Starting El and Incr=val1,val2, val3)
                match = XS_HTAB_COMBINED_PATTERN.match(line)
                if match:
                    params['starting_el'] = float(match.group(1))
                    params['increment'] = float(match.group(2))
                    params['num_points'] = int(match.group(3))
                    params['has_htab_lines'] = True
                    logger.debug(
                        f"Found combined HTAB format at line {i}: "
                        f"starting_el={params['starting_el']}, "
                        f"increment={params['increment']}, "
                        f"num_points={params['num_points']}"
                    )
                    continue

                # Try Format 2a: HTAB Starting El and Incr
                match = HTAB_START_PATTERN.match(line)
                if match:
                    params['starting_el'] = float(match.group(1))
                    params['increment'] = float(match.group(2))
                    params['has_htab_lines'] = True
                    logger.debug(
                        f"Found separate HTAB starting el at line {i}: "
                        f"starting_el={params['starting_el']}, increment={params['increment']}"
                    )
                    continue

                # Try Format 2b: HTAB Number of Points
                match = HTAB_POINTS_PATTERN.match(line)
                if match:
                    params['num_points'] = int(match.group(1))
                    params['has_htab_lines'] = True
                    logger.debug(f"Found separate HTAB num points at line {i}: {params['num_points']}")

            # Get invert/top from station-elevation data
            try:
                sta_elev_df = GeomCrossSection.get_station_elevation(
                    geom_file, river, reach, rs
                )
                if sta_elev_df is not None and len(sta_elev_df) > 0:
                    params['invert'] = float(sta_elev_df['Elevation'].min())
                    params['top'] = float(sta_elev_df['Elevation'].max())
                    logger.debug(f"Computed invert={params['invert']}, top={params['top']}")
            except Exception as e:
                logger.warning(f"Could not extract station-elevation data: {e}")
                # Continue without invert/top - they'll remain None

            logger.info(
                f"Extracted HTAB params for {river}/{reach}/RS {rs}: "
                f"has_htab_lines={params['has_htab_lines']}, "
                f"starting_el={params['starting_el']}, "
                f"increment={params['increment']}, "
                f"num_points={params['num_points']}"
            )

            return params

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading XS HTAB params: {str(e)}")
            raise IOError(f"Failed to read XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def set_xs_htab_params(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str,
                           starting_el: Optional[Union[float, str]] = None,
                           increment: Optional[float] = None,
                           num_points: Optional[int] = None) -> None:
        """
        Set cross section HTAB (hydraulic table) parameters in geometry file.

        This method modifies the HTAB parameters for a specific cross section,
        either replacing existing values or inserting new HTAB lines if they
        don't exist.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "5280")
            starting_el (Optional[Union[float, str]]): Starting elevation:
                - float: Use this elevation value
                - 'invert': Copy the cross section's minimum elevation
                - None: No change (keep existing or HEC-RAS default)
            increment (Optional[float]): Elevation increment (0.1-2.0 typical)
                - None: No change (keep existing or HEC-RAS default)
            num_points (Optional[int]): Number of points (20-500)
                - None: No change (keep existing or HEC-RAS default)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If cross section not found, or parameters invalid
            IOError: If file write fails

        Notes:
            - Only specified parameters are modified
            - If HTAB lines don't exist in the file, they are inserted
            - Geometry file is modified in-place with backup (.bak) created
            - HTAB lines are inserted after "Type RM Length" line, before
              "XS GIS Cut Line" or "#Sta/Elev"

        File Format:
            HTAB Starting El and Incr=     580.0,      0.1
            HTAB Number of Points= 500

        Example:
            >>> # Set optimal HTAB for single XS
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     starting_el=580.0, increment=0.1, num_points=500
            ... )

            >>> # Copy invert as starting elevation
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     starting_el='invert', increment=0.1, num_points=500
            ... )

            >>> # Only update increment (keep other values)
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     increment=0.2
            ... )

        See Also:
            - get_xs_htab_params(): Read current HTAB parameters
            - GeomHtabUtils.validate_xs_htab_params(): Validate parameters
            - GeomHtabUtils.calculate_optimal_xs_htab(): Calculate optimal values
        """
        from .GeomHtabUtils import GeomHtabUtils

        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Get current HTAB params (for defaults and validation)
        current_params = GeomCrossSection.get_xs_htab_params(
            geom_file, river, reach, rs
        )

        # Handle 'invert' as starting_el
        final_starting_el = None
        xs_invert = current_params.get('invert')

        if starting_el is not None:
            if isinstance(starting_el, str) and starting_el.lower() == 'invert':
                if xs_invert is not None:
                    # Round invert UP to 0.01 ft precision to ensure starting_el >= invert
                    final_starting_el = math.ceil(xs_invert * 100) / 100
                    logger.info(
                        f"Using invert elevation as starting_el: {final_starting_el} "
                        f"(rounded up from {xs_invert})"
                    )
                else:
                    raise ValueError(
                        f"Cannot use 'invert' as starting_el: invert elevation "
                        f"not available for {river}/{reach}/RS {rs}"
                    )
            else:
                final_starting_el = float(starting_el)
                # Auto-fix: If starting_el < invert, round up to ensure >= invert
                if xs_invert is not None and final_starting_el < xs_invert:
                    corrected_el = math.ceil(xs_invert * 100) / 100
                    logger.info(
                        f"HTAB starting_el ({final_starting_el}) adjusted to {corrected_el} "
                        f"(>= invert {xs_invert}) for {river}/{reach}/RS {rs}"
                    )
                    final_starting_el = corrected_el

        final_increment = increment
        final_num_points = num_points

        # If no parameters specified, nothing to do
        if final_starting_el is None and final_increment is None and final_num_points is None:
            logger.warning(
                f"No HTAB parameters specified for {river}/{reach}/RS {rs}. "
                "Geometry file unchanged."
            )
            return

        # Build final parameters dict for validation
        # Use current values for any unspecified parameters
        params_to_write = {
            'starting_el': final_starting_el if final_starting_el is not None else current_params.get('starting_el'),
            'increment': final_increment if final_increment is not None else current_params.get('increment'),
            'num_points': final_num_points if final_num_points is not None else current_params.get('num_points')
        }

        # Check if we have enough to write
        # We need at least starting_el and increment for the first line
        # and num_points for the second line
        write_start_incr = params_to_write['starting_el'] is not None and params_to_write['increment'] is not None
        write_num_points = params_to_write['num_points'] is not None

        if not write_start_incr and not write_num_points:
            logger.warning(
                f"Insufficient parameters to write HTAB for {river}/{reach}/RS {rs}. "
                "Need at least (starting_el + increment) or num_points."
            )
            return

        # Validate parameters if we have a complete set
        if all(v is not None for v in params_to_write.values()):
            # Use xs_invert already retrieved above, default to 0 if still None
            validation_invert = xs_invert if xs_invert is not None else 0
            xs_top = current_params.get('top', validation_invert + 100)

            errors, warnings = GeomHtabUtils.validate_xs_htab_params(
                params_to_write, validation_invert, xs_top
            )

            if errors:
                raise ValueError(
                    f"Invalid HTAB parameters for {river}/{reach}/RS {rs}: "
                    f"{'; '.join(errors)}"
                )

            for warning in warnings:
                logger.warning(f"HTAB validation warning: {warning}")

        try:
            # Create backup
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the cross section
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Find existing HTAB lines and insertion point
            # HEC-RAS has TWO possible HTAB formats:
            # 1. Separate format (early in XS block): "HTAB Starting El and Incr=" + "HTAB Number of Points="
            # 2. Combined format (later in XS block): "XS HTab Starting El and Incr=val1,val2, val3"
            htab_start_idx = None       # Line index of "HTAB Starting El and Incr="
            htab_points_idx = None      # Line index of "HTAB Number of Points="
            xs_htab_combined_idx = None # Line index of "XS HTab Starting El and Incr=" (combined format)
            insert_idx = None           # Where to insert if not found

            # Extended search range - XS blocks can be 100+ lines with station/elevation data
            max_search_range = 200

            for i in range(xs_idx, min(xs_idx + max_search_range, len(lines))):
                line = lines[i]

                # Track "Type RM Length" as potential insertion point (insert after it)
                if line.startswith("Type RM Length") and i == xs_idx:
                    insert_idx = i + 1

                # Check for existing HTAB lines - separate format (near top of XS)
                if line.startswith("HTAB Starting El and Incr="):
                    htab_start_idx = i
                    # Also note where to insert num_points if needed
                    if insert_idx is None:
                        insert_idx = i + 1
                elif line.startswith("HTAB Number of Points="):
                    htab_points_idx = i

                # Check for combined format (later in XS, after bank stations)
                if line.startswith("XS HTab Starting El and Incr="):
                    xs_htab_combined_idx = i

                # Track insertion point - should be after Type RM Length, before XS GIS Cut Line
                if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                    if insert_idx is None:
                        insert_idx = i

                # Stop at next XS or river reach
                if line.startswith("River Reach=") and i > xs_idx + 5:
                    break
                if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                    break

            # Build the HTAB lines to write
            modified_lines = lines.copy()

            # If combined format exists, we need to update it (it takes precedence in HEC-RAS)
            if xs_htab_combined_idx is not None:
                # Update the combined format line
                combined_line = f"XS HTab Starting El and Incr={params_to_write['starting_el']},{params_to_write['increment']}, {params_to_write['num_points']} \n"
                modified_lines[xs_htab_combined_idx] = combined_line
                logger.debug(f"Updated combined format XS HTab at line {xs_htab_combined_idx}")

                # If separate format lines also exist, update them for consistency
                if write_start_incr and htab_start_idx is not None:
                    htab_start_line = f"HTAB Starting El and Incr={params_to_write['starting_el']:10.1f},{params_to_write['increment']:10.4f}\n"
                    modified_lines[htab_start_idx] = htab_start_line
                    logger.debug(f"Also updated separate format HTAB at line {htab_start_idx}")

                if write_num_points and htab_points_idx is not None:
                    htab_points_line = f"HTAB Number of Points= {params_to_write['num_points']}\n"
                    modified_lines[htab_points_idx] = htab_points_line
                    logger.debug(f"Also updated separate format HTAB points at line {htab_points_idx}")
            else:
                # No combined format - use separate format
                # Handle "HTAB Starting El and Incr=" line
                if write_start_incr:
                    htab_start_line = f"HTAB Starting El and Incr={params_to_write['starting_el']:10.1f},{params_to_write['increment']:10.4f}\n"

                    if htab_start_idx is not None:
                        # Replace existing line
                        modified_lines[htab_start_idx] = htab_start_line
                        logger.debug(f"Replaced HTAB Starting El and Incr at line {htab_start_idx}")
                    else:
                        # Insert new line
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            # Adjust indices if we inserted before other HTAB line
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1  # Move insertion point for next line
                            logger.debug(f"Inserted HTAB Starting El and Incr at line {insert_idx - 1}")
                        else:
                            raise ValueError(
                                f"Could not find insertion point for HTAB lines in {river}/{reach}/RS {rs}"
                            )

                # Handle "HTAB Number of Points=" line
                if write_num_points:
                    htab_points_line = f"HTAB Number of Points= {params_to_write['num_points']}\n"

                    if htab_points_idx is not None:
                        # Replace existing line
                        modified_lines[htab_points_idx] = htab_points_line
                        logger.debug(f"Replaced HTAB Number of Points at line {htab_points_idx}")
                    else:
                        # Insert new line (after HTAB Starting El and Incr if we just inserted it)
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            logger.debug(f"Inserted HTAB Number of Points at line {insert_idx}")
                        else:
                            raise ValueError(
                                f"Could not find insertion point for HTAB lines in {river}/{reach}/RS {rs}"
                            )

            # Write modified file
            with open(geom_file, 'w') as f:
                f.writelines(modified_lines)

            logger.info(
                f"Updated HTAB params for {river}/{reach}/RS {rs}: "
                f"starting_el={params_to_write.get('starting_el')}, "
                f"increment={params_to_write.get('increment')}, "
                f"num_points={params_to_write.get('num_points')}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing XS HTAB params: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def set_all_xs_htab_params(geom_file: Union[str, Path],
                                starting_el: Union[float, str] = 'invert',
                                increment: float = 0.1,
                                num_points: int = 500,
                                create_backup: bool = True) -> dict:
        """
        Set HTAB parameters for ALL cross sections in geometry file.

        This method efficiently updates HTAB parameters for every cross section
        in a single file read/write cycle. It's optimized for batch operations
        on geometry files with many cross sections.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            starting_el (Union[float, str]): Starting elevation for all XS:
                - float: Use this elevation for all cross sections
                - 'invert': Copy each XS's invert (minimum elevation) - RECOMMENDED
            increment (float): Elevation increment for all XS (default 0.1)
                              Typical values: 0.1-0.2 ft for fine resolution
            num_points (int): Number of points for all XS (default 500)
                             HEC-RAS maximum is 500
            create_backup (bool): Create .bak file before modifying (default True)

        Returns:
            dict: Summary of modifications with keys:
                - 'modified' (int): Number of cross sections successfully modified
                - 'skipped' (int): Number of cross sections skipped (no valid data)
                - 'backup' (Path or None): Path to backup file, or None if no backup
                - 'xs_details' (List[dict]): Per-XS details with river/reach/rs/starting_el

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If invalid parameters (increment <= 0, num_points out of range)
            IOError: If file write fails

        Notes:
            - Processes all cross sections in a SINGLE file read/write cycle
            - Much more efficient than calling set_xs_htab_params() in a loop
            - When starting_el='invert', each XS gets its own invert elevation
            - Uses safe_write_geometry() for atomic write with backup
            - Handles both HTAB formats: separate lines and combined "XS HTab" format

        Performance:
            - Target: <5 seconds for 100 cross sections
            - Single file read, single file write

        Example:
            >>> # Set optimal HTAB for all XS (recommended settings)
            >>> result = GeomCrossSection.set_all_xs_htab_params(
            ...     "model.g01",
            ...     starting_el='invert',  # Copy each XS's invert
            ...     increment=0.1,
            ...     num_points=500
            ... )
            >>> print(f"Modified {result['modified']} cross sections")
            >>> print(f"Backup at: {result['backup']}")

            >>> # Set fixed starting elevation for all XS
            >>> result = GeomCrossSection.set_all_xs_htab_params(
            ...     "model.g01",
            ...     starting_el=580.0,  # Same starting el for all
            ...     increment=0.2,
            ...     num_points=250
            ... )

        See Also:
            - set_xs_htab_params(): Set HTAB for single XS
            - get_xs_htab_params(): Read current HTAB parameters
            - get_cross_sections(): List all XS in geometry file
        """
        import re
        import time

        start_time = time.time()
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate parameters
        if increment <= 0:
            raise ValueError(f"increment ({increment}) must be positive")

        if num_points < 20:
            raise ValueError(f"num_points ({num_points}) must be >= 20 (HEC-RAS minimum)")

        if num_points > 500:
            raise ValueError(f"num_points ({num_points}) must be <= 500 (HEC-RAS maximum)")

        # Regex patterns for both HTAB formats
        # Format 1 (combined): XS HTab Starting El and Incr=937.99,0.5, 100
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )

        # Format 2 (separate lines):
        # HTAB Starting El and Incr=     580.0,      0.5
        # HTAB Number of Points= 100
        HTAB_START_PATTERN = re.compile(
            r'^HTAB Starting El and Incr='
        )
        HTAB_POINTS_PATTERN = re.compile(
            r'^HTAB Number of Points='
        )

        # XS identifier pattern
        STA_ELEV_PATTERN = re.compile(r'^#Sta/Elev=\s*(\d+)')

        try:
            # Step 1: Read entire file ONCE
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            logger.debug(f"Read {len(lines)} lines from {geom_file.name}")

            # Step 2: Get all cross sections using existing method
            xs_df = GeomCrossSection.get_cross_sections(geom_file)
            logger.debug(f"Found {len(xs_df)} cross sections in geometry file")

            if len(xs_df) == 0:
                logger.warning(f"No cross sections found in {geom_file.name}")
                return {
                    'modified': 0,
                    'skipped': 0,
                    'backup': None,
                    'xs_details': []
                }

            # Step 3: Build index of XS locations and compute inverts
            # This avoids re-reading the file for each XS
            xs_info = []
            for _, row in xs_df.iterrows():
                river = row['River']
                reach = row['Reach']
                rs = row['RS']

                # Find XS start index
                xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
                if xs_idx is None:
                    logger.warning(f"Could not find XS {river}/{reach}/RS {rs} in lines")
                    continue

                # Get station-elevation data to compute invert
                invert = None
                top = None
                for j in range(xs_idx, min(xs_idx + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(lines))):
                    match = STA_ELEV_PATTERN.match(lines[j])
                    if match:
                        count = int(match.group(1))
                        # Parse station-elevation data
                        sta_elev_df = GeomCrossSection._parse_paired_data(
                            lines, j + 1, count, 'Station', 'Elevation'
                        )
                        if len(sta_elev_df) > 0:
                            invert = float(sta_elev_df['Elevation'].min())
                            top = float(sta_elev_df['Elevation'].max())
                        break

                xs_info.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'line_idx': xs_idx,
                    'invert': invert,
                    'top': top
                })

            logger.info(f"Indexed {len(xs_info)} cross sections with location data")

            # Step 4: Process all XS and modify lines in place
            modified_count = 0
            skipped_count = 0
            xs_details = []
            modified_lines = lines.copy()

            # Track line offset due to insertions
            line_offset = 0

            for xs in xs_info:
                river = xs['river']
                reach = xs['reach']
                rs = xs['rs']
                xs_idx = xs['line_idx'] + line_offset
                xs_invert = xs['invert']
                xs_top = xs['top']

                # Determine starting elevation for this XS
                if isinstance(starting_el, str) and starting_el.lower() == 'invert':
                    if xs_invert is None:
                        logger.warning(
                            f"Cannot use 'invert' for {river}/{reach}/RS {rs}: "
                            "invert not available. Skipping."
                        )
                        skipped_count += 1
                        continue
                    # Round invert UP to 0.01 ft precision to ensure starting_el >= invert
                    final_starting_el = math.ceil(xs_invert * 100) / 100
                else:
                    final_starting_el = float(starting_el)
                    # Auto-fix: If starting_el < invert, round up to ensure >= invert
                    if xs_invert is not None and final_starting_el < xs_invert:
                        corrected_el = math.ceil(xs_invert * 100) / 100
                        logger.info(
                            f"HTAB starting_el ({final_starting_el}) adjusted to {corrected_el} "
                            f"(>= invert {xs_invert}) for {river}/{reach}/RS {rs}"
                        )
                        final_starting_el = corrected_el

                # Find HTAB lines for this XS
                htab_start_idx = None
                htab_points_idx = None
                xs_htab_combined_idx = None
                insert_idx = None

                # Extended search range
                max_search = min(xs_idx + 200, len(modified_lines))

                for i in range(xs_idx, max_search):
                    line = modified_lines[i]

                    # Track insertion point after "Type RM Length"
                    if line.startswith("Type RM Length") and i == xs_idx:
                        insert_idx = i + 1

                    # Check for existing HTAB lines
                    if HTAB_START_PATTERN.match(line):
                        htab_start_idx = i
                        if insert_idx is None:
                            insert_idx = i + 1

                    if HTAB_POINTS_PATTERN.match(line):
                        htab_points_idx = i

                    if XS_HTAB_COMBINED_PATTERN.match(line):
                        xs_htab_combined_idx = i

                    # Track insertion point before XS GIS Cut Line
                    if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                        if insert_idx is None:
                            insert_idx = i

                    # Stop at next XS
                    if line.startswith("River Reach=") and i > xs_idx + 5:
                        break
                    if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                        break

                # Build HTAB lines to write
                htab_start_line = f"HTAB Starting El and Incr={final_starting_el:10.1f},{increment:10.4f}\n"
                htab_points_line = f"HTAB Number of Points= {num_points}\n"

                lines_added = 0

                # Handle combined format (takes precedence)
                if xs_htab_combined_idx is not None:
                    combined_line = f"XS HTab Starting El and Incr={final_starting_el},{increment}, {num_points} \n"
                    modified_lines[xs_htab_combined_idx] = combined_line

                    # Also update separate format if exists
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line

                else:
                    # Use separate format
                    # Handle HTAB Starting El and Incr
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            lines_added += 1
                            # Adjust indices for subsequent operations
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1
                        else:
                            logger.warning(f"Could not find insertion point for {river}/{reach}/RS {rs}")
                            skipped_count += 1
                            continue

                    # Handle HTAB Number of Points
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            lines_added += 1

                # Update line offset for subsequent XS
                line_offset += lines_added

                modified_count += 1
                xs_details.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'starting_el': final_starting_el,
                    'increment': increment,
                    'num_points': num_points
                })

            # Step 5: Write file ONCE using safe_write_geometry
            if modified_count > 0:
                backup_path = GeomParser.safe_write_geometry(
                    geom_file,
                    modified_lines,
                    create_backup=create_backup
                )
            else:
                backup_path = None
                logger.warning("No cross sections modified - file unchanged")

            elapsed_time = time.time() - start_time

            result = {
                'modified': modified_count,
                'skipped': skipped_count,
                'backup': backup_path,
                'xs_details': xs_details
            }

            logger.info(
                f"set_all_xs_htab_params complete: {modified_count} modified, "
                f"{skipped_count} skipped, {elapsed_time:.2f} seconds"
            )

            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error in set_all_xs_htab_params: {str(e)}")
            raise IOError(f"Failed to set all XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def optimize_xs_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        safety_factor: float = 1.3,
        increment: float = 0.1,
        num_points: int = 500
    ) -> dict:
        """
        Optimize cross section HTAB parameters based on existing HEC-RAS results.

        This method reads maximum water surface elevations from HDF results,
        computes optimal HTAB parameters for each cross section using appropriate
        safety factors, and writes the optimized parameters to the geometry file.

        Algorithm:
            1. Get all cross sections from geometry file
            2. Extract maximum WSE for each cross section from HDF results
            3. For each cross section:
               a. Get invert elevation from geometry
               b. Look up max WSE from HDF results
               c. Use GeomHtabUtils.calculate_optimal_xs_htab() to compute parameters
               d. Collect modification for batch write
            4. Write all modifications to geometry file (single write operation)
            5. Return summary statistics

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            hdf_results_path (Union[str, Path]): Path to plan HDF file with results
            safety_factor (float): Multiplier on max depth to provide buffer (default 1.3 = 30%)
                                   Recommended: 1.2-1.5 for typical floods, 2.0 for dam break
            increment (float): Maximum elevation increment in feet (default 0.1)
                              Smaller increments give more accurate interpolation
            num_points (int): Maximum number of points (default 500, HEC-RAS limit)

        Returns:
            dict: Summary statistics with keys:
                - 'modified_count' (int): Number of cross sections modified
                - 'total_xs_count' (int): Total number of cross sections in geometry
                - 'skipped_count' (int): Number of XS skipped (no results or errors)
                - 'backup_path' (Path): Path to geometry backup file
                - 'min_increment' (float): Minimum increment used
                - 'max_increment' (float): Maximum increment used
                - 'avg_increment' (float): Average increment used
                - 'modifications' (List[dict]): Details of each modification

        Raises:
            FileNotFoundError: If geometry file or HDF file doesn't exist
            ValueError: If safety_factor < 1.0 or other invalid parameters
            IOError: If file read/write fails

        Example:
            >>> from ras_commander import RasExamples, init_ras_project, RasCmdr
            >>> from ras_commander.geom import GeomCrossSection
            >>>
            >>> # Extract and run example project
            >>> path = RasExamples.extract_project("Muncie", suffix="htab_opt")
            >>> init_ras_project(path, "6.6")
            >>> RasCmdr.compute_plan("01")  # Run to get results
            >>>
            >>> # Optimize HTAB from results
            >>> summary = GeomCrossSection.optimize_xs_htab_from_results(
            ...     path / "Muncie.g01",
            ...     path / "Muncie.p01.hdf",
            ...     safety_factor=1.3,
            ...     increment=0.1,
            ...     num_points=500
            ... )
            >>> print(f"Modified {summary['modified_count']} of {summary['total_xs_count']} XS")
            >>> print(f"Increment range: {summary['min_increment']:.2f} - {summary['max_increment']:.2f}")

        Notes:
            - Creates a single backup before any modifications
            - Cross sections without matching HDF results are skipped
            - Modifications are batched to minimize file I/O
            - Safety factor is applied to depth range (max_wse - invert), not absolute elevation

        See Also:
            - GeomHtabUtils.calculate_optimal_xs_htab(): Core calculation algorithm
            - set_xs_htab_params(): Write HTAB parameters for single XS
            - get_xs_htab_params(): Read current HTAB parameters
        """
        import re
        import time
        from .GeomHtabUtils import GeomHtabUtils
        from ..hdf.HdfResultsXsec import HdfResultsXsec

        start_time = time.time()
        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        # Validate inputs
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        if safety_factor < 1.0:
            raise ValueError(f"safety_factor ({safety_factor}) must be >= 1.0")

        if num_points < GeomHtabUtils.MIN_XS_POINTS or num_points > GeomHtabUtils.MAX_XS_POINTS:
            raise ValueError(
                f"num_points ({num_points}) must be between {GeomHtabUtils.MIN_XS_POINTS} "
                f"and {GeomHtabUtils.MAX_XS_POINTS}"
            )

        if increment <= 0:
            raise ValueError(f"increment ({increment}) must be positive")

        logger.info(
            f"Optimizing XS HTAB from results: geom={geom_file.name}, "
            f"hdf={hdf_results_path.name}, safety={safety_factor}, "
            f"increment={increment}, num_points={num_points}"
        )

        # Step 1: Get all cross sections from geometry file
        xs_df = GeomCrossSection.get_cross_sections(geom_file)
        total_xs_count = len(xs_df)

        if total_xs_count == 0:
            logger.warning(f"No cross sections found in {geom_file.name}")
            return {
                'modified_count': 0,
                'total_xs_count': 0,
                'skipped_count': 0,
                'backup_path': None,
                'min_increment': increment,
                'max_increment': increment,
                'avg_increment': increment,
                'modifications': []
            }

        logger.debug(f"Found {total_xs_count} cross sections in geometry file")

        # Step 2: Extract maximum WSE from HDF results
        try:
            xsec_results = HdfResultsXsec.get_xsec_timeseries(hdf_results_path)

            # Build lookup dictionary with multiple key formats
            # The HDF results use format: "River Reach RS" in cross_section names
            # Plus River/Reach/Station as separate coordinate arrays
            max_wse_lookup = {}

            if 'Maximum_Water_Surface' in xsec_results.coords:
                xs_names = xsec_results.coords['cross_section'].values
                rivers = xsec_results.coords['River'].values
                reaches = xsec_results.coords['Reach'].values
                stations = xsec_results.coords['Station'].values
                max_wses = xsec_results.coords['Maximum_Water_Surface'].values

                for idx in range(len(xs_names)):
                    max_wse = float(max_wses[idx])

                    # Store by cross_section name (full string)
                    xs_name = str(xs_names[idx])
                    max_wse_lookup[xs_name] = max_wse

                    # Store by (River, Reach, Station) tuple
                    river = str(rivers[idx])
                    reach = str(reaches[idx])
                    station = str(stations[idx])
                    key = (river, reach, station)
                    max_wse_lookup[key] = max_wse

            logger.info(f"Extracted max WSE for {len(max_wse_lookup) // 2} cross sections from HDF")

        except Exception as e:
            logger.error(f"Failed to extract cross section results from HDF: {e}")
            raise IOError(f"Failed to read HDF results: {e}")

        # Step 3: Read geometry file once and prepare for modifications
        with open(geom_file, 'r') as f:
            lines = f.readlines()

        # Regex patterns for HTAB lines
        HTAB_START_PATTERN = re.compile(r'^HTAB Starting El and Incr=')
        HTAB_POINTS_PATTERN = re.compile(r'^HTAB Number of Points=')
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )
        STA_ELEV_PATTERN = re.compile(r'^#Sta/Elev=\s*(\d+)')

        # Step 4: Create backup ONCE before any modifications
        backup_path = GeomParser.create_backup(geom_file)
        logger.info(f"Created backup: {backup_path}")

        # Step 5: Calculate optimal parameters for each XS and collect modifications
        modifications = []
        skipped_count = 0
        increments_used = []
        modified_lines = lines.copy()
        line_offset = 0

        for _, xs_row in xs_df.iterrows():
            river = xs_row['River']
            reach = xs_row['Reach']
            rs = xs_row['RS']

            # Try multiple lookup key formats
            max_wse = None

            # Try (River, Reach, RS) tuple
            lookup_key = (river, reach, rs)
            max_wse = max_wse_lookup.get(lookup_key)

            if max_wse is None:
                # Try alternate lookup with various string formats
                for key, value in max_wse_lookup.items():
                    if isinstance(key, str):
                        # Key might be "River Reach RS" or other format
                        if river in key and reach in key and rs in key:
                            max_wse = value
                            break

            if max_wse is None:
                logger.debug(f"No HDF results for XS {river}/{reach}/RS {rs}, skipping")
                skipped_count += 1
                continue

            # Find XS in lines and get invert
            xs_idx = GeomCrossSection._find_cross_section(modified_lines, river, reach, rs)
            if xs_idx is None:
                logger.warning(f"XS {river}/{reach}/RS {rs} not found in geometry file, skipping")
                skipped_count += 1
                continue

            # Adjust for any previously inserted lines
            xs_idx_adjusted = xs_idx

            # Get invert from station-elevation data
            invert = None
            for j in range(xs_idx_adjusted, min(xs_idx_adjusted + GeomCrossSection.DEFAULT_SEARCH_RANGE, len(modified_lines))):
                match = STA_ELEV_PATTERN.match(modified_lines[j])
                if match:
                    count = int(match.group(1))
                    sta_elev_df = GeomCrossSection._parse_paired_data(
                        modified_lines, j + 1, count, 'Station', 'Elevation'
                    )
                    if len(sta_elev_df) > 0:
                        invert = float(sta_elev_df['Elevation'].min())
                    break

            if invert is None:
                logger.warning(f"Could not determine invert for {river}/{reach}/RS {rs}, skipping")
                skipped_count += 1
                continue

            # Validate max_wse > invert
            if max_wse <= invert:
                logger.warning(
                    f"Max WSE ({max_wse}) <= invert ({invert}) for {river}/{reach}/RS {rs}, skipping"
                )
                skipped_count += 1
                continue

            # Calculate optimal HTAB parameters
            try:
                optimal_params = GeomHtabUtils.calculate_optimal_xs_htab(
                    invert=invert,
                    max_wse=max_wse,
                    safety_factor=safety_factor,
                    target_increment=increment,
                    max_points=num_points
                )

                final_starting_el = optimal_params['starting_el']
                final_increment = optimal_params['increment']
                final_num_points = optimal_params['num_points']

                # Find and update HTAB lines for this XS
                htab_start_idx = None
                htab_points_idx = None
                xs_htab_combined_idx = None
                insert_idx = None

                max_search = min(xs_idx_adjusted + 200, len(modified_lines))

                for i in range(xs_idx_adjusted, max_search):
                    line = modified_lines[i]

                    if line.startswith("Type RM Length") and i == xs_idx_adjusted:
                        insert_idx = i + 1

                    if HTAB_START_PATTERN.match(line):
                        htab_start_idx = i
                        if insert_idx is None:
                            insert_idx = i + 1

                    if HTAB_POINTS_PATTERN.match(line):
                        htab_points_idx = i

                    if XS_HTAB_COMBINED_PATTERN.match(line):
                        xs_htab_combined_idx = i

                    if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                        if insert_idx is None:
                            insert_idx = i

                    if line.startswith("River Reach=") and i > xs_idx_adjusted + 5:
                        break
                    if line.startswith("Type RM Length L Ch R =") and i > xs_idx_adjusted + 5:
                        break

                # Build HTAB lines
                htab_start_line = f"HTAB Starting El and Incr={final_starting_el:10.1f},{final_increment:10.4f}\n"
                htab_points_line = f"HTAB Number of Points= {final_num_points}\n"

                lines_added = 0

                # Handle combined format
                if xs_htab_combined_idx is not None:
                    combined_line = f"XS HTab Starting El and Incr={final_starting_el},{final_increment}, {final_num_points} \n"
                    modified_lines[xs_htab_combined_idx] = combined_line

                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line

                else:
                    # Use separate format
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            lines_added += 1
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1

                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            lines_added += 1

                line_offset += lines_added

                modifications.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'invert': invert,
                    'max_wse': max_wse,
                    'starting_el': final_starting_el,
                    'increment': final_increment,
                    'num_points': final_num_points,
                    'actual_max_el': optimal_params['actual_max_el'],
                    'target_max_el': optimal_params['target_max_el']
                })

                increments_used.append(final_increment)

            except Exception as e:
                logger.warning(f"Error calculating optimal params for {river}/{reach}/RS {rs}: {e}")
                skipped_count += 1
                continue

        logger.info(
            f"Calculated optimal HTAB for {len(modifications)} cross sections, "
            f"skipped {skipped_count}"
        )

        # Step 6: Write all modifications to geometry file
        if modifications:
            try:
                with open(geom_file, 'w') as f:
                    f.writelines(modified_lines)

                logger.info(f"Wrote {len(modifications)} HTAB modifications to {geom_file.name}")

            except Exception as e:
                logger.error(f"Error writing modifications: {e}")
                # Restore from backup
                if backup_path and backup_path.exists():
                    import shutil
                    logger.info(f"Restoring from backup: {backup_path}")
                    shutil.copy2(backup_path, geom_file)
                raise IOError(f"Failed to write HTAB modifications: {e}")

        # Calculate summary statistics
        if increments_used:
            min_increment = min(increments_used)
            max_increment = max(increments_used)
            avg_increment = sum(increments_used) / len(increments_used)
        else:
            min_increment = max_increment = avg_increment = increment

        elapsed_time = time.time() - start_time

        summary = {
            'modified_count': len(modifications),
            'total_xs_count': total_xs_count,
            'skipped_count': skipped_count,
            'backup_path': backup_path,
            'min_increment': round(min_increment, 4),
            'max_increment': round(max_increment, 4),
            'avg_increment': round(avg_increment, 4),
            'modifications': modifications,
            'elapsed_time': round(elapsed_time, 2)
        }

        logger.info(
            f"HTAB optimization complete: {summary['modified_count']} of {summary['total_xs_count']} "
            f"XS modified, increment range {summary['min_increment']}-{summary['max_increment']}, "
            f"{elapsed_time:.2f} seconds"
        )

        return summary
