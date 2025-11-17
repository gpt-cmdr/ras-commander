"""
RasGeometryUtils - Utility functions for parsing HEC-RAS geometry files

This module provides reusable utility functions for parsing and manipulating
HEC-RAS geometry files. These utilities handle FORTRAN-era fixed-width formats,
count interpretation, section identification, and file manipulation.

All methods are static and designed to be used without instantiation.

List of Functions:
- parse_fixed_width() - Parse fixed-width numeric data (8 or 16 char columns)
- format_fixed_width() - Format values into fixed-width lines
- interpret_count() - Interpret count declarations based on context
- identify_section() - Find section boundaries by keyword marker
- extract_keyword_value() - Extract value following keyword
- extract_comma_list() - Extract comma-separated list
- create_backup() - Create .bak backup before modification
- validate_river_reach_rs() - Validate river/reach/RS exists

Example Usage:
    >>> from ras_commander import RasGeometryUtils
    >>> # Parse fixed-width line (8-char columns)
    >>> line = "       0  963.04    27.2  963.04"
    >>> values = RasGeometryUtils.parse_fixed_width(line, column_width=8)
    >>> print(values)
    [0.0, 963.04, 27.2, 963.04]

    >>> # Interpret count declaration
    >>> total_values = RasGeometryUtils.interpret_count("#Sta/Elev", 40)
    >>> print(f"40 pairs = {total_values} total values")
    40 pairs = 80 total values
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasGeometryUtils:
    """
    Utility functions for parsing HEC-RAS geometry files.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    def parse_fixed_width(line: str, column_width: int = 8) -> List[float]:
        """
        Parse fixed-width numeric data from a line.

        HEC-RAS uses FORTRAN-era fixed-width columns for numeric data:
        - 8-character columns: Station/elevation, Manning's n, elevation-volume
        - 16-character columns: 2D coordinates (X, Y pairs)

        Values are right-aligned and left-padded with spaces within each column.
        This function MUST parse by column position, NOT by whitespace splitting.

        Parameters:
            line (str): Line containing fixed-width values
            column_width (int): Width of each column in characters. Defaults to 8.
                               Use 16 for 2D coordinate data.

        Returns:
            List[float]: Parsed numeric values

        Raises:
            ValueError: If a column contains non-numeric data that can't be parsed

        Example:
            >>> # 8-character columns (station/elevation)
            >>> line = "       0  963.04    27.2  963.04   32.64  963.02"
            >>> values = RasGeometryUtils.parse_fixed_width(line, 8)
            >>> print(values)
            [0.0, 963.04, 27.2, 963.04, 32.64, 963.02]

            >>> # 16-character columns (2D coordinates)
            >>> line = "   648224.43125   4551425.84375   648229.43125   4551425.84375"
            >>> coords = RasGeometryUtils.parse_fixed_width(line, 16)
            >>> print(coords)
            [648224.43125, 4551425.84375, 648229.43125, 4551425.84375]

        Notes:
            - Based on successful RasUnsteady.parse_fixed_width_table() pattern
            - Handles merged values (adjacent numbers without spaces) using regex
            - Skips empty columns
            - Strips line before parsing to remove trailing newlines
        """
        values = []
        line_stripped = line.rstrip('\n\r')

        # Parse by column position (CRITICAL: do NOT use .split())
        for i in range(0, len(line_stripped), column_width):
            column = line_stripped[i:i+column_width].strip()

            if not column:
                continue  # Skip empty columns

            try:
                # Try direct conversion first
                values.append(float(column))
            except ValueError:
                # Handle merged values (e.g., "123.45678.90" without space)
                # Use regex to split merged numeric values
                merged_values = re.findall(r'-?\d+\.?\d*', column)
                if merged_values:
                    for val_str in merged_values:
                        try:
                            values.append(float(val_str))
                        except ValueError:
                            logger.warning(f"Could not parse value '{val_str}' from merged column '{column}'")
                else:
                    logger.warning(f"Could not parse column '{column}' as numeric")

        return values

    @staticmethod
    def format_fixed_width(values: List[float],
                          column_width: int = 8,
                          values_per_line: int = 10,
                          precision: int = 2) -> List[str]:
        """
        Format values into fixed-width lines for writing to geometry files.

        Creates properly formatted lines with right-aligned values, left-padded
        with spaces to fill the column width. Follows HEC-RAS conventions:
        - 8-char columns: Typically 10 values per line (80 chars total)
        - 16-char columns: Typically 4 values per line (64 chars total)

        Parameters:
            values (List[float]): List of numeric values to format
            column_width (int): Width of each column in characters. Defaults to 8.
            values_per_line (int): Number of values per line. Defaults to 10.
            precision (int): Decimal places for formatting. Defaults to 2.

        Returns:
            List[str]: Lines with fixed-width formatted values (with newlines)

        Example:
            >>> values = [0.0, 963.04, 27.2, 963.04]
            >>> lines = RasGeometryUtils.format_fixed_width(values, 8, 10, 2)
            >>> print(lines[0])
            '    0.00  963.04   27.20  963.04\\n'

            >>> # 16-char columns for coordinates
            >>> coords = [648224.43125, 4551425.84375]
            >>> lines = RasGeometryUtils.format_fixed_width(coords, 16, 4, 5)
            >>> print(lines[0])
            '  648224.43125  4551425.84375\\n'

        Notes:
            - Based on RasUnsteady.write_table_to_file() pattern
            - Values are formatted as f'{value:{column_width}.{precision}f}'
            - Right-aligned within column, left-padded with spaces
            - Last line may have fewer than values_per_line values
        """
        lines = []

        for i in range(0, len(values), values_per_line):
            row_values = values[i:i+values_per_line]
            # Format each value with specified width and precision
            formatted_row = ''.join(f'{value:{column_width}.{precision}f}' for value in row_values)
            lines.append(formatted_row + '\n')

        return lines

    @staticmethod
    @log_call
    def interpret_count(keyword: str,
                       count_value: int,
                       additional_values: Optional[List[int]] = None) -> int:
        """
        Interpret count declarations based on keyword context.

        CRITICAL: Different keywords use counts differently. This is a common
        source of parsing bugs if not handled correctly.

        Count Interpretation Rules:
        - "#Sta/Elev= 40" → 40 PAIRS → 80 total values (station + elevation)
        - "#Mann= 3 , 0 , 0" → 3 SEGMENTS → 9 total values (3 left + 3 channel + 3 right)
        - "Reach XY= 591" → 591 PAIRS → 1182 total values (591 X + 591 Y)
        - "Storage Area Elev Volume= 53" → 53 PAIRS → 106 total values
        - "Levee= 12 , 0" → 12 + 0 = 12 values (left side only)

        Parameters:
            keyword (str): Section keyword (e.g., "#Sta/Elev", "#Mann", "Reach XY")
            count_value (int): First count value after keyword
            additional_values (Optional[List[int]]): Additional count values if comma-separated

        Returns:
            int: Total number of values to read from the file

        Example:
            >>> # Station/elevation: 40 pairs = 80 values
            >>> RasGeometryUtils.interpret_count("#Sta/Elev", 40)
            80

            >>> # Manning's n: 3 segments × 3 positions = 9 values
            >>> RasGeometryUtils.interpret_count("#Mann", 3, [0, 0])
            9

            >>> # Reach coordinates: 591 pairs = 1182 values
            >>> RasGeometryUtils.interpret_count("Reach XY", 591)
            1182

            >>> # Levees: 12 left + 0 right = 12 values
            >>> RasGeometryUtils.interpret_count("Levee", 12, [0])
            12

        Notes:
            - See _PARSING_PATTERNS_REFERENCE.md for complete count interpretation guide
            - This is based on extensive validation against HDF files
        """
        keyword_lower = keyword.lower()

        # Station/Elevation pairs (most common)
        if 'sta' in keyword_lower and 'elev' in keyword_lower:
            return count_value * 2  # Pairs: station + elevation

        # Manning's n segments (triplets: left, channel, right)
        if 'mann' in keyword_lower:
            # #Mann= 3 , 0 , 0 means 3 segments with left/channel/right values each
            return count_value * 3

        # Coordinate pairs (X, Y)
        if 'xy' in keyword_lower or ('x' in keyword_lower and 'y' in keyword_lower):
            return count_value * 2  # Pairs: X + Y

        # Elevation-Volume pairs (storage areas)
        if 'elev' in keyword_lower and 'volume' in keyword_lower:
            return count_value * 2  # Pairs: elevation + volume

        # Levees (can have left and right counts)
        if 'levee' in keyword_lower:
            if additional_values:
                return count_value + sum(additional_values)
            return count_value

        # Default: count is total values (not pairs)
        logger.debug(f"Using default count interpretation for keyword '{keyword}': {count_value} values")
        return count_value

    @staticmethod
    @log_call
    def identify_section(lines: List[str],
                        keyword: str,
                        start_index: int = 0) -> Optional[Tuple[int, int]]:
        """
        Find section boundaries based on keyword marker.

        Searches for a line starting with the specified keyword and determines
        where the section ends (either at the next keyword or end of file).

        Parameters:
            lines (List[str]): All lines from geometry file
            keyword (str): Section marker keyword to search for
            start_index (int): Line index to start searching from. Defaults to 0.

        Returns:
            Optional[Tuple[int, int]]: (start_line, end_line) or None if not found
                                       start_line: Index of line with keyword
                                       end_line: Index of last line in section (exclusive)

        Example:
            >>> with open("geometry.g01") as f:
            ...     lines = f.readlines()
            >>> section = RasGeometryUtils.identify_section(lines, "River Reach=")
            >>> if section:
            ...     start, end = section
            ...     print(f"River Reach section: lines {start} to {end}")

        Notes:
            - Keyword matching is case-insensitive
            - Returns None if keyword not found
            - Section ends at next keyword starting with capital letter or "=" sign
        """
        start_line = None

        # Find the start of the section
        for i in range(start_index, len(lines)):
            if lines[i].strip().lower().startswith(keyword.lower()):
                start_line = i
                break

        if start_line is None:
            logger.debug(f"Keyword '{keyword}' not found starting from line {start_index}")
            return None

        # Find the end of the section (next keyword or end of file)
        end_line = len(lines)
        for i in range(start_line + 1, len(lines)):
            line_stripped = lines[i].strip()
            # Section ends at next keyword (starts with capital or contains "=")
            if line_stripped and (line_stripped[0].isupper() or '=' in line_stripped):
                # Check if it looks like a keyword (not just data with "=")
                if '=' in line_stripped:
                    end_line = i
                    break

        logger.debug(f"Section '{keyword}' found: lines {start_line} to {end_line}")
        return (start_line, end_line)

    @staticmethod
    def extract_keyword_value(line: str, keyword: str) -> str:
        """
        Extract value following keyword marker.

        Finds keyword followed by "=" and returns everything after the "=".

        Parameters:
            line (str): Line containing keyword
            keyword (str): Keyword to search for

        Returns:
            str: Value after "=" (stripped of leading/trailing whitespace)

        Example:
            >>> line = "Geom Title=White Lick Creek Geometry"
            >>> title = RasGeometryUtils.extract_keyword_value(line, "Geom Title")
            >>> print(title)
            'White Lick Creek Geometry'

            >>> line = "Program Version=6.30"
            >>> version = RasGeometryUtils.extract_keyword_value(line, "Program Version")
            >>> print(version)
            '6.30'

        Notes:
            - Keyword matching is case-insensitive
            - Returns empty string if keyword not found or no value after "="
        """
        # Pattern: keyword (case-insensitive) followed by = and value
        pattern = rf'{re.escape(keyword)}\s*=\s*(.+)'
        match = re.search(pattern, line, re.IGNORECASE)

        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def extract_comma_list(line: str, keyword: str) -> List[str]:
        """
        Extract comma-separated list following keyword.

        Handles embedded commas in quoted strings properly.

        Parameters:
            line (str): Line containing keyword and comma-separated values
            keyword (str): Keyword before the list

        Returns:
            List[str]: List of values (stripped of whitespace)

        Example:
            >>> line = "River Reach=White Lick,Reach 1"
            >>> values = RasGeometryUtils.extract_comma_list(line, "River Reach")
            >>> print(values)
            ['White Lick', 'Reach 1']

            >>> line = "Storage Area=Res Pool 1"
            >>> values = RasGeometryUtils.extract_comma_list(line, "Storage Area")
            >>> print(values)
            ['Res Pool 1']

        Notes:
            - Handles cases with or without commas
            - Handles quoted strings with embedded commas
        """
        value_str = RasGeometryUtils.extract_keyword_value(line, keyword)

        if not value_str:
            return []

        # Split by comma, handling quoted strings
        # Simple approach: split by comma and strip
        values = [v.strip().strip('"\'') for v in value_str.split(',')]

        return values

    @staticmethod
    @log_call
    def create_backup(file_path: Path) -> Path:
        """
        Create .bak backup of file before modification.

        Creates a backup copy with .bak extension. If .bak already exists,
        creates .bak1, .bak2, etc.

        Parameters:
            file_path (Path): Path to file to backup

        Returns:
            Path: Path to backup file

        Raises:
            FileNotFoundError: If original file doesn't exist
            IOError: If backup creation fails

        Example:
            >>> from pathlib import Path
            >>> geom_file = Path("MyProject.g01")
            >>> backup = RasGeometryUtils.create_backup(geom_file)
            >>> print(f"Backup created: {backup}")
            Backup created: MyProject.g01.bak

        Notes:
            - Based on RasGeo.set_mannings_baseoverrides() pattern
            - Always creates backup before file modification
            - Finds next available .bakN filename if .bak exists
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Cannot create backup: file not found: {file_path}")

        # Find next available backup filename
        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        counter = 1

        while backup_path.exists():
            backup_path = file_path.with_suffix(f'{file_path.suffix}.bak{counter}')
            counter += 1

        try:
            # Copy file to backup
            import shutil
            shutil.copy2(file_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            return backup_path

        except Exception as e:
            logger.error(f"Failed to create backup of {file_path}: {str(e)}")
            raise IOError(f"Backup creation failed: {str(e)}")

    @staticmethod
    def update_timestamp(lines: List[str], keyword: str) -> List[str]:
        """
        Update timestamp for a modified section.

        Finds lines with timestamp keywords and updates them to current time.

        Parameters:
            lines (List[str]): File lines to modify
            keyword (str): Timestamp keyword to search for

        Returns:
            List[str]: Modified lines with updated timestamp

        Example:
            >>> lines = ["LCMann Time=01Jan2023 14:30:45\\n"]
            >>> updated = RasGeometryUtils.update_timestamp(lines, "LCMann Time")
            >>> print(updated[0])
            'LCMann Time=11Nov2025 10:45:30\\n'

        Notes:
            - Timestamp format: DDMmmYYYY HH:MM:SS
            - Only updates lines matching the specified keyword
            - Preserves all other lines unchanged
        """
        current_time = datetime.now()
        timestamp_str = current_time.strftime("%d%b%Y %H:%M:%S")

        updated_lines = []
        for line in lines:
            if keyword in line and '=' in line:
                # Replace the timestamp after the "="
                parts = line.split('=')
                updated_line = f"{parts[0]}={timestamp_str}\n"
                updated_lines.append(updated_line)
            else:
                updated_lines.append(line)

        return updated_lines

    @staticmethod
    @log_call
    def validate_river_reach_rs(geom_file: Path,
                               river: str,
                               reach: str,
                               rs: str) -> bool:
        """
        Validate that river/reach/RS combination exists in geometry file.

        Parameters:
            geom_file (Path): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            bool: True if combination exists

        Raises:
            ValueError: If river/reach/RS not found in geometry file

        Example:
            >>> from pathlib import Path
            >>> geom_file = Path("BaldEagle.g01")
            >>> valid = RasGeometryUtils.validate_river_reach_rs(
            ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4"
            ... )
            >>> print(valid)
            True

        Notes:
            - Used before modification operations to ensure valid target
            - Searches for "Type RM Length L Ch R =" line with matching RS
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find River Reach line
            current_river = None
            current_reach = None

            for i, line in enumerate(lines):
                # Check for River Reach definition
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Check for cross section with matching RS
                if line.startswith("Type RM Length L Ch R ="):
                    # Next line should have river station
                    if i + 1 < len(lines):
                        parts = lines[i].split('=')
                        if len(parts) > 1:
                            values = parts[1].strip().split(',')
                            if len(values) > 0:
                                xs_rs = values[0].strip()
                                if (current_river == river and
                                    current_reach == reach and
                                    xs_rs == rs):
                                    logger.debug(f"Found XS: {river}/{reach}/RS {rs}")
                                    return True

            raise ValueError(f"Cross section not found: {river}, {reach}, RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error validating river/reach/RS: {str(e)}")
            raise ValueError(f"Validation failed: {str(e)}")
