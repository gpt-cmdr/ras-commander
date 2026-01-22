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

    # Task name aliases - maps various HEC-RAS version task names to standardized keys
    TASK_NAME_ALIASES = {
        'Complete Process': 'complete_process',
        'Unsteady Flow Computations': 'unsteady_compute',
        'Completing Geometry': 'geometry',
        'Completing Geometry, Flow and Plan': 'geometry',  # HEC-RAS 6.6 variant
        'Preprocessing Geometry': 'preprocessing',
        'Completing Event Conditions': 'event_conditions',
    }

    @staticmethod
    def _parse_compute_time(time_str: str) -> Optional[float]:
        """
        Parse HEC-RAS time format to seconds.

        Handles various formats found in compute messages:
        - '<1': Sub-second operations (estimated as 0.5 seconds)
        - '27': Seconds only
        - '6:24': Minutes:seconds (mm:ss)
        - '1:23:45': Hours:minutes:seconds (hh:mm:ss)

        Args:
            time_str: Time string from compute messages

        Returns:
            float: Time in seconds, or None if unparseable
        """
        if not time_str:
            return None

        time_str = time_str.strip()
        if not time_str:
            return None

        # Handle sub-second indicator
        if time_str == '<1':
            return 0.5  # Estimate for sub-second operations

        parts = time_str.split(':')
        try:
            if len(parts) == 1:  # seconds only: '27'
                return float(parts[0])
            elif len(parts) == 2:  # mm:ss: '6:24'
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:  # hh:mm:ss: '1:23:45'
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            return None

        return None

    @staticmethod
    def parse_compute_messages_runtime(messages: str) -> Dict:
        """
        Parse compute messages for runtime data (fallback for pre-6.4 HEC-RAS).

        This method parses the "Computations Summary" section of compute messages
        to extract runtime metrics. This is useful for HEC-RAS versions before 6.4
        that do not store runtime data in structured HDF paths.

        Args:
            messages: Raw compute messages text from HDF or .txt file

        Returns:
            dict: Runtime data with keys:
                - runtime_complete_process_seconds: float | None
                - runtime_unsteady_compute_seconds: float | None
                - runtime_geometry_seconds: float | None
                - runtime_preprocessing_seconds: float | None
                - runtime_event_conditions_seconds: float | None
                - complete_process_speed: float | None (simulation/runtime ratio)
                - unsteady_flow_speed: float | None
                - vol_error_percent: float | None

        Example:
            >>> messages = '''
            ... Computations Summary
            ... Computation Task	Time(hh:mm:ss)
            ... Complete Process	    6:41
            ... Overall Volume Accounting Error as percentage:           0.01866
            ... '''
            >>> result = ResultsParser.parse_compute_messages_runtime(messages)
            >>> result['runtime_complete_process_seconds']
            401.0
        """
        result = {
            'runtime_complete_process_seconds': None,
            'runtime_unsteady_compute_seconds': None,
            'runtime_geometry_seconds': None,
            'runtime_preprocessing_seconds': None,
            'runtime_event_conditions_seconds': None,
            'complete_process_speed': None,
            'unsteady_flow_speed': None,
            'vol_error_percent': None,
        }

        if not messages:
            return result

        lines = messages.split('\n')

        # State machine for parsing
        in_task_table = False
        in_speed_table = False

        # Regex patterns
        # Task/time line: "Completing Geometry	      27" or "Unsteady Flow Computations	<1"
        # Format is: task_name + tab + optional_spaces + time_value
        # Note: Some time values like "<1" have no extra spaces, others like "27" have padding
        task_time_pattern = re.compile(r'^([A-Za-z,\s]+?)\t\s*(<?[\d:]+)\s*$')

        # Speed line: "Unsteady Flow Computations	673x" or "Complete Process	646x"
        # Format is: task_name + tab + optional_spaces + speed_value + optional 'x'
        speed_pattern = re.compile(r'^([A-Za-z\s]+?)\t\s*([\d.]+)x?\s*$')

        # Volume error: "Overall Volume Accounting Error as percentage:           0.01866"
        vol_error_pattern = re.compile(
            r'Overall Volume Accounting Error as percentage:\s*([\d.]+)',
            re.IGNORECASE
        )

        for line in lines:
            line_stripped = line.strip()

            # Check for volume error (can appear anywhere)
            vol_match = vol_error_pattern.search(line_stripped)
            if vol_match:
                try:
                    result['vol_error_percent'] = float(vol_match.group(1))
                except ValueError:
                    pass

            # Detect table sections
            if 'Computation Task' in line and 'Time' in line:
                in_task_table = True
                in_speed_table = False
                continue

            if 'Computation Speed' in line and 'Simulation' in line:
                in_task_table = False
                in_speed_table = True
                continue

            # Skip empty lines and header lines
            if not line_stripped:
                continue

            if line_stripped.startswith('Computations Summary'):
                continue

            # Parse task/time table
            if in_task_table:
                match = task_time_pattern.match(line_stripped)
                if match:
                    task_name = match.group(1).strip()
                    time_str = match.group(2).strip()
                    time_seconds = ResultsParser._parse_compute_time(time_str)

                    # Map task name to standardized key
                    task_key = ResultsParser.TASK_NAME_ALIASES.get(task_name)
                    if task_key and time_seconds is not None:
                        if task_key == 'complete_process':
                            result['runtime_complete_process_seconds'] = time_seconds
                        elif task_key == 'unsteady_compute':
                            result['runtime_unsteady_compute_seconds'] = time_seconds
                        elif task_key == 'geometry':
                            result['runtime_geometry_seconds'] = time_seconds
                        elif task_key == 'preprocessing':
                            result['runtime_preprocessing_seconds'] = time_seconds
                        elif task_key == 'event_conditions':
                            result['runtime_event_conditions_seconds'] = time_seconds

            # Parse speed table
            if in_speed_table:
                match = speed_pattern.match(line_stripped)
                if match:
                    task_name = match.group(1).strip()
                    speed_str = match.group(2).strip()
                    try:
                        speed_value = float(speed_str)
                        if 'Complete Process' in task_name:
                            result['complete_process_speed'] = speed_value
                        elif 'Unsteady Flow' in task_name:
                            result['unsteady_flow_speed'] = speed_value
                    except ValueError:
                        pass

        return result
