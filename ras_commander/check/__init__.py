"""
RasCheck - Quality Assurance Validation for HEC-RAS Steady Flow Models.

NOTE: This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
It is part of the ras-commander library and is NOT affiliated with or endorsed by FEMA.
The original cHECk-RAS is a Windows application developed for FEMA's National Flood
Insurance Program. This implementation provides similar functionality using modern
HDF-based data access for HEC-RAS 6.x models.

This subpackage provides comprehensive validation of HEC-RAS 6.x steady flow models.

Modules:
    RasCheck: Main class with check methods (check_nt, check_xs, check_structures, etc.)
    thresholds: Validation threshold constants (Manning's n, transitions, etc.)
    messages: Message catalog with standardized validation messages
    report: HTML and CSV report generation

Example:
    >>> from ras_commander.check import RasCheck, Severity, RasCheckReport
    >>>
    >>> # Run NT checks on geometry
    >>> results = RasCheck.check_nt(geom_hdf)
    >>> print(f"Errors: {results.get_error_count()}")
    >>>
    >>> # Generate HTML report
    >>> report = RasCheckReport(results)
    >>> report.generate_html("validation_report.html")
"""

from .RasCheck import RasCheck, CheckResults, CheckMessage, Severity
from .thresholds import (
    ValidationThresholds,
    get_default_thresholds,
    get_state_surcharge_limit,
    create_custom_thresholds,
)
from .messages import (
    MESSAGE_CATALOG,
    MessageType,
    get_message_template,
    get_help_text,
)
from .report import (
    RasCheckReport,
    ReportMetadata,
    ReportSummary,
    generate_html_report,
    export_messages_csv,
)

__all__ = [
    # Main class
    'RasCheck',
    # Result classes
    'CheckResults',
    'CheckMessage',
    'Severity',
    # Thresholds
    'ValidationThresholds',
    'get_default_thresholds',
    'get_state_surcharge_limit',
    'create_custom_thresholds',
    # Messages
    'MESSAGE_CATALOG',
    'MessageType',
    'get_message_template',
    'get_help_text',
    # Report generation
    'RasCheckReport',
    'ReportMetadata',
    'ReportSummary',
    'generate_html_report',
    'export_messages_csv',
]
