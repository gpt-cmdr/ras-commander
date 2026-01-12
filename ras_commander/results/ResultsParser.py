"""
ResultsParser - Parse HEC-RAS compute messages for errors and warnings.

This module provides utilities to analyze HEC-RAS computation messages
and extract summary information about execution status.
"""

from typing import Dict, Optional
import logging
import re

logger = logging.getLogger(__name__)


class ResultsParser:
    """
    Parse HEC-RAS compute messages for errors and warnings.

    This is a static class - do not instantiate.

    Attributes:
        ERROR_KEYWORDS: Keywords indicating errors (case-insensitive)
        WARNING_KEYWORDS: Keywords indicating warnings (case-insensitive)

    Example:
        >>> from ras_commander.results import ResultsParser
        >>> result = ResultsParser.parse_compute_messages(compute_msgs_text)
        >>> if result['has_errors']:
        ...     print(f"Found {result['error_count']} errors")
    """

    # Configurable keyword sets for error/warning detection
    # More specific patterns to avoid false positives from metric names
    ERROR_PATTERNS = [
        r'\berror\s*:',                    # "Error:" or "ERROR:"
        r'\berror\s*-',                    # "Error -" or "ERROR -"
        r'computation\s+failed',           # "computation failed"
        r'run\s+failed',                   # "run failed"
        r'failed\s+to',                    # "failed to..."
        r'unable\s+to',                    # "unable to..."
        r'cannot\s+',                      # "cannot ..."
        r'fatal\s+error',                  # "fatal error"
        r'exception\s*:',                  # "Exception:"
        r'aborted',                        # "aborted"
        r'terminated\s+abnormally',        # "terminated abnormally"
    ]

    # Exclusion patterns for known false positives (HEC-RAS metrics)
    ERROR_EXCLUSIONS = [
        r'volume\s+accounting\s+error',    # Volume accounting metric
        r'wsel\s+error',                   # Water surface elevation error metric
        r'error\s+\(ft\)',                 # Error in feet (metric)
        r'maximum.*error',                 # Maximum error metrics
        r'rs\s+wsel\s+error',              # Cross section wsel error (metric)
        r'iterations',                     # Lines with iteration counts
    ]

    WARNING_KEYWORDS = [
        'warning',
        'caution',
        'notice',
        'exceeded',
        'unstable',
        'convergence'
    ]

    @staticmethod
    def parse_compute_messages(messages: str) -> Dict:
        """
        Parse compute messages and extract summary information.

        Analyzes HEC-RAS compute messages to determine completion status,
        detect errors and warnings, and extract the first error line for
        quick diagnosis.

        Args:
            messages: Raw compute messages text from HDF or .txt file

        Returns:
            dict: Summary with keys:
                - completed (bool): True if "Complete Process" found
                - has_errors (bool): True if error keywords found
                - has_warnings (bool): True if warning keywords found
                - error_count (int): Number of lines with error keywords
                - warning_count (int): Number of lines with warning keywords
                - first_error_line (str or None): First line containing error (truncated to 200 chars)

        Example:
            >>> result = ResultsParser.parse_compute_messages("Complete Process\\nWarning: High velocity")
            >>> result
            {'completed': True, 'has_errors': False, 'has_warnings': True,
             'error_count': 0, 'warning_count': 1, 'first_error_line': None}
        """
        if not messages:
            return {
                'completed': False,
                'has_errors': False,
                'has_warnings': False,
                'error_count': 0,
                'warning_count': 0,
                'first_error_line': None
            }

        # Check for completion
        completed = 'Complete Process' in messages

        # Split into lines for analysis
        lines = messages.split('\n')

        # Count errors and warnings
        error_count = 0
        warning_count = 0
        first_error_line = None

        # Compile error patterns
        error_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in ResultsParser.ERROR_PATTERNS]
        exclusion_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in ResultsParser.ERROR_EXCLUSIONS]

        # Build regex pattern for warnings
        warning_pattern = re.compile(
            '|'.join(re.escape(kw) for kw in ResultsParser.WARNING_KEYWORDS),
            re.IGNORECASE
        )

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Check for errors with exclusion filtering
            is_error = False
            for error_pat in error_patterns:
                if error_pat.search(line_stripped):
                    # Check if this matches an exclusion pattern (false positive)
                    is_excluded = any(excl.search(line_stripped) for excl in exclusion_patterns)
                    if not is_excluded:
                        is_error = True
                        break

            if is_error:
                error_count += 1
                if first_error_line is None:
                    # Truncate to 200 chars for storage efficiency
                    first_error_line = line_stripped[:200]

            # Check for warnings (only if not already counted as error)
            elif warning_pattern.search(line_stripped):
                warning_count += 1

        return {
            'completed': completed,
            'has_errors': error_count > 0,
            'has_warnings': warning_count > 0,
            'error_count': error_count,
            'warning_count': warning_count,
            'first_error_line': first_error_line
        }

    @staticmethod
    def is_successful_completion(messages: str) -> bool:
        """
        Quick check if computation completed successfully.

        A computation is considered successful if it contains "Complete Process"
        and has no error keywords.

        Args:
            messages: Raw compute messages text

        Returns:
            bool: True if completed without errors
        """
        result = ResultsParser.parse_compute_messages(messages)
        return result['completed'] and not result['has_errors']
