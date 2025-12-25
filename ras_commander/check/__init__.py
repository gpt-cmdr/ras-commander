"""
RasCheck - Quality Assurance Validation for HEC-RAS Models.

NOTE: This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
It is part of the ras-commander library and is NOT affiliated with or endorsed by FEMA.
The original cHECk-RAS is a Windows application developed for FEMA's National Flood
Insurance Program. This implementation provides similar functionality using modern
HDF-based data access for HEC-RAS 6.x models.

This subpackage provides comprehensive validation of HEC-RAS 6.x models for both
steady flow and unsteady flow simulations. Flow type is auto-detected.

Steady Flow Checks:
    - NT Check: Manning's n values and transition coefficients
    - XS Check: Cross section spacing, ineffective flow, reach lengths
    - Structure Check: Bridge, culvert, and inline weir validation
    - Floodway Check: Surcharge and discharge matching
    - Profiles Check: Multiple profile comparison

Unsteady Flow Checks:
    - NT Check: Manning's n values (geometry-only, shared)
    - Mass Balance Check: Volume conservation
    - Computation Check: HEC-RAS warnings and performance
    - Peaks Check: Maximum WSE and velocity validation
    - Stability Check: Iteration counts and convergence (2D)
    - Mesh Quality Check: Cell areas and aspect ratios (2D)

Modules:
    RasCheck: Main class with check methods
    thresholds: Validation threshold constants
    messages: Message catalog with standardized validation messages
    report: HTML and CSV report generation

Example:
    >>> from ras_commander.check import RasCheck, FlowType
    >>>
    >>> # Auto-detects steady or unsteady flow
    >>> results = RasCheck.run_all("01")
    >>> print(f"Flow type: {results.flow_type}")  # FlowType.STEADY or FlowType.UNSTEADY
    >>> print(f"Errors: {results.get_error_count()}")
    >>>
    >>> # Generate HTML report
    >>> results.to_html("validation_report.html")
"""

from .RasCheck import RasCheck, CheckResults, CheckMessage, Severity, FlowType
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
    'FlowType',
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
