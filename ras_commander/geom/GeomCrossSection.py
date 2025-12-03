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
