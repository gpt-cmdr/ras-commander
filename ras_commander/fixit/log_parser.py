"""
HEC-RAS Log Parser for Error Detection.

This module provides utilities for detecting blocked obstruction errors
from HEC-RAS compute logs and output files. It enables automated workflows
where errors are detected and then fixed programmatically.

Example Workflow:
    >>> from ras_commander.fixit import log_parser
    >>> from ras_commander import RasFixit
    >>>
    >>> # Parse compute log for errors
    >>> errors = log_parser.detect_obstruction_errors(log_content)
    >>> if errors:
    ...     # Find affected geometry files
    ...     geom_files = log_parser.find_geometry_files_in_directory(project_dir)
    ...     for geom_path in geom_files:
    ...         results = RasFixit.fix_blocked_obstructions(geom_path)
"""

import re
import os
from pathlib import Path
from typing import List, Dict, Optional

from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def detect_obstruction_errors(log_content: str) -> List[Dict[str, str]]:
    """
    Parse HEC-RAS log content and detect blocked obstruction errors.

    Scans log text for common error patterns related to blocked obstructions
    and extracts relevant information.

    Args:
        log_content: String containing HEC-RAS log output or error messages.

    Returns:
        List of dictionaries containing error details:
        [
            {
                'type': 'overlap' | 'adjacent' | 'invalid' | 'general',
                'river_station': '12345.67',
                'description': 'Short description',
                'message': 'Full error message',
                'line_number': 42
            },
            ...
        ]

    Example:
        >>> log_text = '''
        ... ERROR: Cross Section 12345.67 has overlapping blocked obstructions
        ... '''
        >>> errors = detect_obstruction_errors(log_text)
        >>> print(errors[0]['river_station'])
        '12345.67'
    """
    errors = []

    # Common error patterns in HEC-RAS output
    patterns = [
        # Overlapping obstructions
        (r'(?i)cross\s+section\s+([\d.]+).*overlapping.*blocked\s+obstruction',
         'overlap',
         'Overlapping blocked obstructions'),

        # Adjacent obstructions
        (r'(?i)blocked\s+obstructions.*station\s+([\d.]+).*adjacent',
         'adjacent',
         'Adjacent blocked obstructions'),

        # Invalid configuration
        (r'(?i)invalid.*blocked\s+obstruction.*(?:at|station)\s+([\d.]+)',
         'invalid',
         'Invalid blocked obstruction configuration'),

        # Generic obstruction error
        (r'(?i)error.*blocked\s+obstruction.*(?:rs|station)\s*([\d.]+)',
         'general',
         'Blocked obstruction error'),

        # Alternative pattern for station format
        (r'(?i)(?:rs|river\s+station)[:\s]*([\d.]+).*blocked\s+obstruction.*(?:overlap|adjacent|error)',
         'general',
         'Blocked obstruction issue'),
    ]

    lines = log_content.split('\n')

    for line_num, line in enumerate(lines, 1):
        for pattern, error_type, description in patterns:
            match = re.search(pattern, line)
            if match:
                # Extract river station if available
                rs = match.group(1) if match.lastindex >= 1 else 'Unknown'

                errors.append({
                    'type': error_type,
                    'river_station': rs,
                    'description': description,
                    'message': line.strip(),
                    'line_number': line_num
                })
                break  # Only match one pattern per line

    return errors


def extract_geometry_files(log_content: str, project_dir: str = '.') -> List[str]:
    """
    Extract geometry file paths from HEC-RAS log content.

    Searches log text for references to geometry files (.g##) and resolves
    them to absolute paths.

    Args:
        log_content: String containing HEC-RAS log output.
        project_dir: Project directory to resolve relative paths.

    Returns:
        List of absolute paths to geometry files that may need fixing.
        Only includes files that actually exist on disk.

    Example:
        >>> geom_files = extract_geometry_files(log_text, "/path/to/project")
        >>> for f in geom_files:
        ...     print(f)
    """
    geometry_files = set()

    # Patterns to match geometry file references
    patterns = [
        r'(?i)geometry\s+file[:\s]+([\w\\/.-]+\.g\d+)',
        r'(?i)using\s+geometry[:\s]+([\w\\/.-]+\.g\d+)',
        r'(?i)processing[:\s]+([\w\\/.-]+\.g\d+)',
        r'([\w\\/.-]+\.g\d+)',  # Any .gXX file mention
    ]

    for pattern in patterns:
        matches = re.findall(pattern, log_content)
        for match in matches:
            # Resolve to absolute path
            if os.path.isabs(match):
                geom_path = match
            else:
                geom_path = os.path.join(project_dir, match)

            # Only add if file exists
            if os.path.exists(geom_path):
                geometry_files.add(os.path.abspath(geom_path))

    return sorted(list(geometry_files))


def find_geometry_files_in_directory(directory: str) -> List[str]:
    """
    Find all HEC-RAS geometry files in a directory.

    Searches for files matching the pattern *.g[0-9]* (e.g., .g01, .g02, etc.)
    but excludes HDF files.

    Args:
        directory: Path to search for geometry files.

    Returns:
        List of absolute paths to geometry files (.g01, .g02, etc.)

    Example:
        >>> geom_files = find_geometry_files_in_directory("/path/to/project")
        >>> print(f"Found {len(geom_files)} geometry files")
    """
    geometry_files = []

    # Pattern for HEC-RAS geometry files
    pattern = '*.g[0-9]*'

    for file_path in Path(directory).glob(pattern):
        # Skip .hdf files (not plain text geometry files)
        if not str(file_path).lower().endswith('.hdf'):
            geometry_files.append(str(file_path.absolute()))

    return sorted(geometry_files)


def has_obstruction_errors(log_file_path: str) -> bool:
    """
    Quick check if a log file contains blocked obstruction errors.

    Reads the log file and checks for any obstruction-related errors.

    Args:
        log_file_path: Path to HEC-RAS log file.

    Returns:
        True if blocked obstruction errors are detected, False otherwise.

    Example:
        >>> if has_obstruction_errors("compute.log"):
        ...     print("Obstruction errors found!")
    """
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            return bool(detect_obstruction_errors(content))
    except Exception as e:
        logger.warning(f"Could not read log file {log_file_path}: {e}")
        return False


def generate_error_report(errors: List[Dict[str, str]]) -> str:
    """
    Generate a human-readable error report.

    Creates a formatted report suitable for logging or display, grouped
    by error type.

    Args:
        errors: List of error dictionaries from detect_obstruction_errors().

    Returns:
        Formatted string report.

    Example:
        >>> errors = detect_obstruction_errors(log_content)
        >>> print(generate_error_report(errors))
    """
    if not errors:
        return "No blocked obstruction errors detected."

    report_lines = [
        "=" * 80,
        "BLOCKED OBSTRUCTION ERROR REPORT",
        "=" * 80,
        f"\nTotal Errors Found: {len(errors)}\n"
    ]

    # Group by type
    by_type: Dict[str, List[Dict[str, str]]] = {}
    for error in errors:
        error_type = error['type']
        if error_type not in by_type:
            by_type[error_type] = []
        by_type[error_type].append(error)

    for error_type, type_errors in by_type.items():
        report_lines.append(f"\n{error_type.upper()} ({len(type_errors)} occurrences):")
        report_lines.append("-" * 80)

        for error in type_errors:
            report_lines.append(f"  River Station: {error['river_station']}")
            report_lines.append(f"  Line: {error['line_number']}")
            report_lines.append(f"  Message: {error['message']}")
            report_lines.append("")

    report_lines.append("=" * 80)

    return "\n".join(report_lines)


def extract_cross_section_ids(log_content: str) -> List[str]:
    """
    Extract cross-section/river station IDs from error messages.

    Parses log content and returns unique river station IDs that have
    obstruction errors.

    Args:
        log_content: String containing HEC-RAS log output.

    Returns:
        List of unique river station IDs that have errors, sorted numerically.

    Example:
        >>> stations = extract_cross_section_ids(log_content)
        >>> print(f"Affected stations: {stations}")
    """
    errors = detect_obstruction_errors(log_content)
    stations = set()

    for error in errors:
        rs = error.get('river_station')
        if rs and rs != 'Unknown':
            stations.add(rs)

    # Sort numerically if possible
    try:
        return sorted(list(stations), key=float)
    except ValueError:
        return sorted(list(stations))
