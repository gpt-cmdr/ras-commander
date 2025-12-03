"""
RasGeometryUtils - Utility functions for parsing HEC-RAS geometry files

DEPRECATION NOTICE:
    This class is deprecated and will be removed before v1.0.
    Please migrate to GeomParser from the geometry subpackage:

    from ras_commander import GeomParser

    All methods have the same names and signatures.

This module provides reusable utility functions for parsing and manipulating
HEC-RAS geometry files. These utilities handle FORTRAN-era fixed-width formats,
count interpretation, section identification, and file manipulation.

All methods are static and designed to be used without instantiation.

List of Functions:
- parse_fixed_width() - Parse fixed-width numeric data (8 or 16 char columns) [DEPRECATED]
- format_fixed_width() - Format values into fixed-width lines [DEPRECATED]
- interpret_count() - Interpret count declarations based on context [DEPRECATED]
- identify_section() - Find section boundaries by keyword marker [DEPRECATED]
- extract_keyword_value() - Extract value following keyword [DEPRECATED]
- extract_comma_list() - Extract comma-separated list [DEPRECATED]
- create_backup() - Create .bak backup before modification [DEPRECATED]
- validate_river_reach_rs() - Validate river/reach/RS exists [DEPRECATED]
"""

import warnings
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasGeometryUtils:
    """
    Utility functions for parsing HEC-RAS geometry files.

    DEPRECATED: This class is deprecated and will be removed before v1.0.
    Please migrate to GeomParser from the geometry subpackage:

    from ras_commander import GeomParser

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    def parse_fixed_width(line: str, column_width: int = 8) -> List[float]:
        """
        Parse fixed-width numeric data from a line.

        DEPRECATED: Use GeomParser.parse_fixed_width() instead.
        """
        warnings.warn(
            "RasGeometryUtils.parse_fixed_width() is deprecated. "
            "Use GeomParser.parse_fixed_width() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.parse_fixed_width(line, column_width)

    @staticmethod
    def format_fixed_width(values: List[float],
                          column_width: int = 8,
                          values_per_line: int = 10,
                          precision: int = 2) -> List[str]:
        """
        Format values into fixed-width lines for writing to geometry files.

        DEPRECATED: Use GeomParser.format_fixed_width() instead.
        """
        warnings.warn(
            "RasGeometryUtils.format_fixed_width() is deprecated. "
            "Use GeomParser.format_fixed_width() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.format_fixed_width(values, column_width, values_per_line, precision)

    @staticmethod
    @log_call
    def interpret_count(keyword: str,
                       count_value: int,
                       additional_values: Optional[List[int]] = None) -> int:
        """
        Interpret count declarations based on keyword context.

        DEPRECATED: Use GeomParser.interpret_count() instead.
        """
        warnings.warn(
            "RasGeometryUtils.interpret_count() is deprecated. "
            "Use GeomParser.interpret_count() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.interpret_count(keyword, count_value, additional_values)

    @staticmethod
    @log_call
    def identify_section(lines: List[str],
                        keyword: str,
                        start_index: int = 0) -> Optional[Tuple[int, int]]:
        """
        Find section boundaries based on keyword marker.

        DEPRECATED: Use GeomParser.identify_section() instead.
        """
        warnings.warn(
            "RasGeometryUtils.identify_section() is deprecated. "
            "Use GeomParser.identify_section() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.identify_section(lines, keyword, start_index)

    @staticmethod
    def extract_keyword_value(line: str, keyword: str) -> str:
        """
        Extract value following keyword marker.

        DEPRECATED: Use GeomParser.extract_keyword_value() instead.
        """
        warnings.warn(
            "RasGeometryUtils.extract_keyword_value() is deprecated. "
            "Use GeomParser.extract_keyword_value() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.extract_keyword_value(line, keyword)

    @staticmethod
    def extract_comma_list(line: str, keyword: str) -> List[str]:
        """
        Extract comma-separated list following keyword.

        DEPRECATED: Use GeomParser.extract_comma_list() instead.
        """
        warnings.warn(
            "RasGeometryUtils.extract_comma_list() is deprecated. "
            "Use GeomParser.extract_comma_list() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.extract_comma_list(line, keyword)

    @staticmethod
    @log_call
    def create_backup(file_path: Path) -> Path:
        """
        Create .bak backup of file before modification.

        DEPRECATED: Use GeomParser.create_backup() instead.
        """
        warnings.warn(
            "RasGeometryUtils.create_backup() is deprecated. "
            "Use GeomParser.create_backup() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.create_backup(file_path)

    @staticmethod
    def update_timestamp(lines: List[str], keyword: str) -> List[str]:
        """
        Update timestamp for a modified section.

        DEPRECATED: Use GeomParser.update_timestamp() instead.
        """
        warnings.warn(
            "RasGeometryUtils.update_timestamp() is deprecated. "
            "Use GeomParser.update_timestamp() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.update_timestamp(lines, keyword)

    @staticmethod
    @log_call
    def validate_river_reach_rs(geom_file: Path,
                               river: str,
                               reach: str,
                               rs: str) -> bool:
        """
        Validate that river/reach/RS combination exists in geometry file.

        DEPRECATED: Use GeomParser.validate_river_reach_rs() instead.
        """
        warnings.warn(
            "RasGeometryUtils.validate_river_reach_rs() is deprecated. "
            "Use GeomParser.validate_river_reach_rs() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomParser
        return GeomParser.validate_river_reach_rs(geom_file, river, reach, rs)
