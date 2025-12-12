# Report Generation Specification

## Overview

This document specifies the report generation system for RasCheck, which produces HTML reports, DataFrame exports, and CSV message logs from validation results.

## Report Types

### 1. HTML Report
- Full visual report with styling
- Expandable sections for each check type
- Color-coded severity indicators
- Summary statistics
- Export to PDF capability (optional)

### 2. DataFrame Report
- Programmatic access to all results
- Multiple DataFrames for different data types
- Easy filtering and analysis
- Integration with pandas workflows

### 3. CSV Message Export
- Simple text export of all messages
- Machine-readable format
- Import into other tools

## Implementation

### report.py

```python
"""
Report generation for RasCheck validation results.

Generates HTML reports, DataFrame exports, and CSV message logs
from validation results.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import pandas as pd
from datetime import datetime
import html
from ..logging_config import get_logger, log_call

logger = get_logger(__name__)


# ============================================================================
# Report Data Classes
# ============================================================================

@dataclass
class ReportMetadata:
    """Metadata for report generation."""
    project_name: str
    project_path: Path
    plan_name: str
    plan_hdf_path: Path
    geometry_name: str
    geometry_hdf_path: Path
    ras_version: str
    report_generated: datetime
    check_version: str = "1.0.0"

    # Profile information
    profiles_checked: List[str] = None
    base_flood_profile: Optional[str] = None
    floodway_profile: Optional[str] = None

    # Summary counts
    total_cross_sections: int = 0
    total_structures: int = 0
    total_reaches: int = 0


@dataclass
class ReportSummary:
    """Summary statistics for report."""
    total_messages: int
    error_count: int
    warning_count: int
    info_count: int
    checks_passed: int
    checks_failed: int

    # By check type
    nt_messages: int = 0
    xs_messages: int = 0
    struct_messages: int = 0
    floodway_messages: int = 0
    profile_messages: int = 0


# ============================================================================
# HTML Report Generator
# ============================================================================

# CSS Styles for HTML Report
HTML_STYLES = """
<style>
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        margin: 0;
        padding: 20px;
        background-color: #f5f5f5;
        color: #333;
    }

    .container {
        max-width: 1200px;
        margin: 0 auto;
        background: white;
        padding: 30px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }

    h1 {
        color: #2c3e50;
        border-bottom: 3px solid #3498db;
        padding-bottom: 10px;
    }

    h2 {
        color: #34495e;
        margin-top: 30px;
        border-left: 4px solid #3498db;
        padding-left: 10px;
    }

    h3 {
        color: #7f8c8d;
        margin-top: 20px;
    }

    .metadata {
        background: #ecf0f1;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 20px;
    }

    .metadata table {
        width: 100%;
        border-collapse: collapse;
    }

    .metadata td {
        padding: 5px 10px;
    }

    .metadata td:first-child {
        font-weight: bold;
        width: 200px;
        color: #7f8c8d;
    }

    .summary-box {
        display: flex;
        gap: 20px;
        margin: 20px 0;
        flex-wrap: wrap;
    }

    .summary-card {
        flex: 1;
        min-width: 150px;
        padding: 20px;
        border-radius: 8px;
        text-align: center;
    }

    .summary-card.errors {
        background: #e74c3c;
        color: white;
    }

    .summary-card.warnings {
        background: #f39c12;
        color: white;
    }

    .summary-card.info {
        background: #3498db;
        color: white;
    }

    .summary-card.passed {
        background: #27ae60;
        color: white;
    }

    .summary-card .count {
        font-size: 36px;
        font-weight: bold;
    }

    .summary-card .label {
        font-size: 14px;
        text-transform: uppercase;
        opacity: 0.9;
    }

    .check-section {
        margin: 30px 0;
        border: 1px solid #ddd;
        border-radius: 5px;
        overflow: hidden;
    }

    .check-header {
        background: #34495e;
        color: white;
        padding: 15px 20px;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .check-header:hover {
        background: #2c3e50;
    }

    .check-header .title {
        font-size: 18px;
        font-weight: bold;
    }

    .check-header .badge {
        background: rgba(255,255,255,0.2);
        padding: 5px 15px;
        border-radius: 15px;
        font-size: 14px;
    }

    .check-content {
        padding: 20px;
        display: block;
    }

    .check-content.collapsed {
        display: none;
    }

    table.messages {
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
    }

    table.messages th {
        background: #ecf0f1;
        padding: 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #bdc3c7;
    }

    table.messages td {
        padding: 10px 12px;
        border-bottom: 1px solid #ecf0f1;
        vertical-align: top;
    }

    table.messages tr:hover {
        background: #f8f9fa;
    }

    .severity-error {
        color: #e74c3c;
        font-weight: bold;
    }

    .severity-warning {
        color: #f39c12;
        font-weight: bold;
    }

    .severity-info {
        color: #3498db;
    }

    .message-id {
        font-family: monospace;
        background: #ecf0f1;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 12px;
    }

    .location {
        color: #7f8c8d;
        font-size: 13px;
    }

    .help-text {
        font-size: 12px;
        color: #95a5a6;
        margin-top: 5px;
        font-style: italic;
    }

    .data-table {
        width: 100%;
        border-collapse: collapse;
        margin: 15px 0;
        font-size: 13px;
    }

    .data-table th {
        background: #3498db;
        color: white;
        padding: 10px;
        text-align: left;
    }

    .data-table td {
        padding: 8px 10px;
        border-bottom: 1px solid #ecf0f1;
    }

    .data-table tr:nth-child(even) {
        background: #f8f9fa;
    }

    .footer {
        margin-top: 40px;
        padding-top: 20px;
        border-top: 1px solid #ecf0f1;
        color: #95a5a6;
        font-size: 12px;
        text-align: center;
    }

    .no-messages {
        color: #27ae60;
        font-style: italic;
        padding: 20px;
        text-align: center;
    }

    @media print {
        body {
            background: white;
        }
        .container {
            box-shadow: none;
        }
        .check-content.collapsed {
            display: block !important;
        }
    }
</style>
"""

# JavaScript for interactivity
HTML_SCRIPT = """
<script>
    function toggleSection(id) {
        var content = document.getElementById(id);
        if (content.classList.contains('collapsed')) {
            content.classList.remove('collapsed');
        } else {
            content.classList.add('collapsed');
        }
    }

    function expandAll() {
        var contents = document.querySelectorAll('.check-content');
        contents.forEach(function(c) {
            c.classList.remove('collapsed');
        });
    }

    function collapseAll() {
        var contents = document.querySelectorAll('.check-content');
        contents.forEach(function(c) {
            c.classList.add('collapsed');
        });
    }
</script>
"""


@log_call
def generate_html_report(
    results: 'CheckResults',
    metadata: ReportMetadata,
    output_path: Path,
    include_data_tables: bool = True,
    collapse_sections: bool = False
) -> Path:
    """
    Generate HTML report from check results.

    Args:
        results: CheckResults object with all validation messages
        metadata: ReportMetadata with project information
        output_path: Path for output HTML file
        include_data_tables: Include detailed data tables for each check
        collapse_sections: Start with sections collapsed

    Returns:
        Path to generated HTML file

    Example:
        >>> results = RasCheck.run_all(hdf_path, ...)
        >>> metadata = ReportMetadata(
        ...     project_name="Example Project",
        ...     project_path=Path("C:/projects/example"),
        ...     ...
        ... )
        >>> html_path = generate_html_report(results, metadata, Path("report.html"))
    """
    output_path = Path(output_path)

    # Calculate summary
    summary = _calculate_summary(results)

    # Build HTML
    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>RasCheck Report - {html.escape(metadata.project_name)}</title>",
        HTML_STYLES,
        "</head>",
        "<body>",
        "<div class='container'>",
        _generate_header(metadata),
        _generate_summary_cards(summary),
        _generate_check_sections(results, collapse_sections, include_data_tables),
        _generate_footer(metadata),
        "</div>",
        HTML_SCRIPT,
        "</body>",
        "</html>"
    ]

    html_content = "\n".join(html_parts)

    # Write file
    output_path.write_text(html_content, encoding='utf-8')
    logger.info(f"HTML report generated: {output_path}")

    return output_path


def _calculate_summary(results: 'CheckResults') -> ReportSummary:
    """Calculate summary statistics from results."""
    messages = results.messages

    error_count = sum(1 for m in messages if m.severity.name == 'ERROR')
    warning_count = sum(1 for m in messages if m.severity.name == 'WARNING')
    info_count = sum(1 for m in messages if m.severity.name == 'INFO')

    # Count by check type
    nt_msgs = sum(1 for m in messages if m.message_id.startswith('NT_'))
    xs_msgs = sum(1 for m in messages if m.message_id.startswith('XS_'))
    struct_msgs = sum(1 for m in messages if m.message_id.startswith(('BR_', 'CU_', 'IW_', 'ST_')))
    fw_msgs = sum(1 for m in messages if m.message_id.startswith('FW_'))
    prof_msgs = sum(1 for m in messages if m.message_id.startswith('MP_'))

    return ReportSummary(
        total_messages=len(messages),
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        checks_passed=5 - (1 if nt_msgs > 0 else 0) - (1 if xs_msgs > 0 else 0) -
                      (1 if struct_msgs > 0 else 0) - (1 if fw_msgs > 0 else 0) -
                      (1 if prof_msgs > 0 else 0),
        checks_failed=(1 if nt_msgs > 0 else 0) + (1 if xs_msgs > 0 else 0) +
                      (1 if struct_msgs > 0 else 0) + (1 if fw_msgs > 0 else 0) +
                      (1 if prof_msgs > 0 else 0),
        nt_messages=nt_msgs,
        xs_messages=xs_msgs,
        struct_messages=struct_msgs,
        floodway_messages=fw_msgs,
        profile_messages=prof_msgs
    )


def _generate_header(metadata: ReportMetadata) -> str:
    """Generate report header HTML."""
    return f"""
    <h1>RasCheck Validation Report</h1>

    <div class='metadata'>
        <table>
            <tr>
                <td>Project Name:</td>
                <td>{html.escape(metadata.project_name)}</td>
            </tr>
            <tr>
                <td>Project Path:</td>
                <td>{html.escape(str(metadata.project_path))}</td>
            </tr>
            <tr>
                <td>Plan:</td>
                <td>{html.escape(metadata.plan_name)}</td>
            </tr>
            <tr>
                <td>Geometry:</td>
                <td>{html.escape(metadata.geometry_name)}</td>
            </tr>
            <tr>
                <td>HEC-RAS Version:</td>
                <td>{html.escape(metadata.ras_version)}</td>
            </tr>
            <tr>
                <td>Report Generated:</td>
                <td>{metadata.report_generated.strftime('%Y-%m-%d %H:%M:%S')}</td>
            </tr>
            <tr>
                <td>Cross Sections:</td>
                <td>{metadata.total_cross_sections}</td>
            </tr>
            <tr>
                <td>Structures:</td>
                <td>{metadata.total_structures}</td>
            </tr>
        </table>
    </div>
    """


def _generate_summary_cards(summary: ReportSummary) -> str:
    """Generate summary cards HTML."""
    return f"""
    <h2>Summary</h2>

    <div class='summary-box'>
        <div class='summary-card errors'>
            <div class='count'>{summary.error_count}</div>
            <div class='label'>Errors</div>
        </div>
        <div class='summary-card warnings'>
            <div class='count'>{summary.warning_count}</div>
            <div class='label'>Warnings</div>
        </div>
        <div class='summary-card info'>
            <div class='count'>{summary.info_count}</div>
            <div class='label'>Info</div>
        </div>
        <div class='summary-card passed'>
            <div class='count'>{summary.checks_passed}/5</div>
            <div class='label'>Checks Passed</div>
        </div>
    </div>

    <p>
        <button onclick='expandAll()'>Expand All</button>
        <button onclick='collapseAll()'>Collapse All</button>
    </p>
    """


def _generate_check_sections(
    results: 'CheckResults',
    collapse_sections: bool,
    include_data_tables: bool
) -> str:
    """Generate check section HTML."""
    sections = []

    # Define check types and their display info
    check_types = [
        ('NT', "Manning's n / Transition Coefficients", 'nt_'),
        ('XS', "Cross Section Validation", 'xs_'),
        ('STRUCT', "Structure Validation", ('br_', 'cu_', 'iw_', 'st_')),
        ('FW', "Floodway Validation", 'fw_'),
        ('MP', "Multiple Profile Comparison", 'mp_')
    ]

    for check_id, check_name, prefix in check_types:
        # Filter messages for this check
        if isinstance(prefix, tuple):
            msgs = [m for m in results.messages
                    if m.message_id.lower().startswith(prefix)]
        else:
            msgs = [m for m in results.messages
                    if m.message_id.lower().startswith(prefix)]

        collapse_class = "collapsed" if collapse_sections else ""

        section_html = f"""
        <div class='check-section'>
            <div class='check-header' onclick="toggleSection('section-{check_id}')">
                <span class='title'>{check_name}</span>
                <span class='badge'>{len(msgs)} messages</span>
            </div>
            <div class='check-content {collapse_class}' id='section-{check_id}'>
        """

        if not msgs:
            section_html += "<div class='no-messages'>No issues found</div>"
        else:
            section_html += _generate_message_table(msgs)

        # Add data tables if requested
        if include_data_tables and check_id in results.details:
            section_html += _generate_data_table(
                results.details[check_id],
                f"{check_name} Details"
            )

        section_html += "</div></div>"
        sections.append(section_html)

    return "\n".join(sections)


def _generate_message_table(messages: List['CheckMessage']) -> str:
    """Generate message table HTML."""
    rows = []

    for msg in messages:
        severity_class = f"severity-{msg.severity.name.lower()}"

        help_html = ""
        if msg.help_text:
            help_html = f"<div class='help-text'>{html.escape(msg.help_text)}</div>"

        rows.append(f"""
        <tr>
            <td><span class='message-id'>{html.escape(msg.message_id)}</span></td>
            <td><span class='{severity_class}'>{msg.severity.name}</span></td>
            <td class='location'>{html.escape(msg.location or '')}</td>
            <td>
                {html.escape(msg.message)}
                {help_html}
            </td>
        </tr>
        """)

    return f"""
    <table class='messages'>
        <thead>
            <tr>
                <th>ID</th>
                <th>Severity</th>
                <th>Location</th>
                <th>Message</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def _generate_data_table(df: pd.DataFrame, title: str) -> str:
    """Generate data table HTML from DataFrame."""
    if df is None or df.empty:
        return ""

    # Limit to first 100 rows for performance
    df_display = df.head(100)

    headers = "".join(f"<th>{html.escape(str(col))}</th>" for col in df_display.columns)

    rows = []
    for _, row in df_display.iterrows():
        cells = "".join(f"<td>{html.escape(str(val))}</td>" for val in row)
        rows.append(f"<tr>{cells}</tr>")

    note = ""
    if len(df) > 100:
        note = f"<p><em>Showing first 100 of {len(df)} rows</em></p>"

    return f"""
    <h3>{html.escape(title)}</h3>
    {note}
    <table class='data-table'>
        <thead><tr>{headers}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    """


def _generate_footer(metadata: ReportMetadata) -> str:
    """Generate report footer HTML."""
    return f"""
    <div class='footer'>
        <p>
            Generated by RasCheck v{metadata.check_version}
            (ras-commander) on {metadata.report_generated.strftime('%Y-%m-%d %H:%M:%S')}
        </p>
        <p>
            Based on FEMA cHECk-RAS validation methodology
        </p>
    </div>
    """


# ============================================================================
# DataFrame Report Generator
# ============================================================================

@log_call
def generate_dataframe_report(
    results: 'CheckResults',
    metadata: Optional[ReportMetadata] = None
) -> Dict[str, pd.DataFrame]:
    """
    Generate DataFrame report from check results.

    Returns a dictionary of DataFrames:
    - 'messages': All validation messages
    - 'summary': Summary statistics
    - 'nt_details': Manning's n details (if available)
    - 'xs_details': Cross section details (if available)
    - 'struct_details': Structure details (if available)
    - 'floodway_details': Floodway details (if available)
    - 'profile_details': Profile comparison details (if available)

    Args:
        results: CheckResults object with all validation messages
        metadata: Optional ReportMetadata for additional context

    Returns:
        Dictionary of DataFrames

    Example:
        >>> results = RasCheck.run_all(hdf_path, ...)
        >>> dfs = generate_dataframe_report(results)
        >>> dfs['messages'].to_csv('messages.csv')
        >>> dfs['summary']
    """
    report = {}

    # Messages DataFrame
    messages_data = []
    for msg in results.messages:
        messages_data.append({
            'message_id': msg.message_id,
            'severity': msg.severity.name,
            'location': msg.location,
            'message': msg.message,
            'check_type': _get_check_type(msg.message_id),
            'river': msg.river,
            'reach': msg.reach,
            'station': msg.station,
            'profile': msg.profile,
            'value': msg.value,
            'threshold': msg.threshold,
            'help_text': msg.help_text
        })

    report['messages'] = pd.DataFrame(messages_data)

    # Summary DataFrame
    summary = _calculate_summary(results)
    summary_data = {
        'metric': [
            'Total Messages',
            'Errors',
            'Warnings',
            'Info',
            'NT Check Messages',
            'XS Check Messages',
            'Structure Check Messages',
            'Floodway Check Messages',
            'Profile Check Messages'
        ],
        'count': [
            summary.total_messages,
            summary.error_count,
            summary.warning_count,
            summary.info_count,
            summary.nt_messages,
            summary.xs_messages,
            summary.struct_messages,
            summary.floodway_messages,
            summary.profile_messages
        ]
    }
    report['summary'] = pd.DataFrame(summary_data)

    # Add metadata if provided
    if metadata:
        metadata_data = {
            'field': [
                'project_name', 'project_path', 'plan_name', 'geometry_name',
                'ras_version', 'report_generated', 'total_cross_sections',
                'total_structures', 'total_reaches'
            ],
            'value': [
                metadata.project_name, str(metadata.project_path),
                metadata.plan_name, metadata.geometry_name,
                metadata.ras_version, str(metadata.report_generated),
                metadata.total_cross_sections, metadata.total_structures,
                metadata.total_reaches
            ]
        }
        report['metadata'] = pd.DataFrame(metadata_data)

    # Add detail DataFrames from results
    if results.details:
        for key, df in results.details.items():
            if df is not None and not df.empty:
                report[f'{key.lower()}_details'] = df

    return report


def _get_check_type(message_id: str) -> str:
    """Get check type from message ID."""
    prefix = message_id.split('_')[0].upper()
    type_map = {
        'NT': 'Manning\'s n / Transitions',
        'XS': 'Cross Sections',
        'BR': 'Bridges',
        'CU': 'Culverts',
        'IW': 'Inline Weirs',
        'ST': 'Structures',
        'FW': 'Floodway',
        'MP': 'Multiple Profiles'
    }
    return type_map.get(prefix, 'Unknown')


# ============================================================================
# CSV Export
# ============================================================================

@log_call
def export_messages_csv(
    results: 'CheckResults',
    output_path: Path,
    include_help_text: bool = True
) -> Path:
    """
    Export messages to CSV file.

    Args:
        results: CheckResults object with all validation messages
        output_path: Path for output CSV file
        include_help_text: Include help text column

    Returns:
        Path to generated CSV file

    Example:
        >>> results = RasCheck.run_all(hdf_path, ...)
        >>> csv_path = export_messages_csv(results, Path("messages.csv"))
    """
    output_path = Path(output_path)

    # Build DataFrame
    data = []
    for msg in results.messages:
        row = {
            'Message ID': msg.message_id,
            'Severity': msg.severity.name,
            'Location': msg.location or '',
            'Message': msg.message,
            'River': msg.river or '',
            'Reach': msg.reach or '',
            'Station': msg.station if msg.station is not None else '',
            'Profile': msg.profile or '',
            'Value': msg.value if msg.value is not None else '',
            'Threshold': msg.threshold if msg.threshold is not None else ''
        }
        if include_help_text:
            row['Help Text'] = msg.help_text or ''
        data.append(row)

    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False, encoding='utf-8')

    logger.info(f"Messages exported to CSV: {output_path}")
    return output_path


# ============================================================================
# Excel Export
# ============================================================================

@log_call
def export_excel_report(
    results: 'CheckResults',
    metadata: ReportMetadata,
    output_path: Path
) -> Path:
    """
    Export complete report to Excel file with multiple sheets.

    Args:
        results: CheckResults object with all validation messages
        metadata: ReportMetadata with project information
        output_path: Path for output Excel file

    Returns:
        Path to generated Excel file

    Example:
        >>> results = RasCheck.run_all(hdf_path, ...)
        >>> xlsx_path = export_excel_report(results, metadata, Path("report.xlsx"))
    """
    output_path = Path(output_path)

    # Generate DataFrame report
    dfs = generate_dataframe_report(results, metadata)

    # Write to Excel with multiple sheets
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name, df in dfs.items():
            # Truncate sheet name to Excel's 31 character limit
            sheet_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Excel report generated: {output_path}")
    return output_path


# ============================================================================
# Summary Text Report
# ============================================================================

@log_call
def generate_summary_text(
    results: 'CheckResults',
    metadata: Optional[ReportMetadata] = None
) -> str:
    """
    Generate plain text summary of results.

    Args:
        results: CheckResults object with all validation messages
        metadata: Optional ReportMetadata for additional context

    Returns:
        Text summary string

    Example:
        >>> results = RasCheck.run_all(hdf_path, ...)
        >>> print(generate_summary_text(results))
    """
    summary = _calculate_summary(results)

    lines = [
        "=" * 60,
        "RASCHECK VALIDATION SUMMARY",
        "=" * 60,
        ""
    ]

    if metadata:
        lines.extend([
            f"Project: {metadata.project_name}",
            f"Plan: {metadata.plan_name}",
            f"Geometry: {metadata.geometry_name}",
            ""
        ])

    lines.extend([
        f"Total Messages: {summary.total_messages}",
        f"  Errors:   {summary.error_count}",
        f"  Warnings: {summary.warning_count}",
        f"  Info:     {summary.info_count}",
        "",
        "By Check Type:",
        f"  Manning's n / Transitions: {summary.nt_messages}",
        f"  Cross Sections:            {summary.xs_messages}",
        f"  Structures:                {summary.struct_messages}",
        f"  Floodway:                  {summary.floodway_messages}",
        f"  Multiple Profiles:         {summary.profile_messages}",
        "",
        "=" * 60
    ])

    return "\n".join(lines)


# ============================================================================
# Report Integration with RasCheck
# ============================================================================

def create_report_metadata(
    ras_object: 'RasPrj',
    plan_hdf_path: Path,
    geometry_hdf_path: Path,
    profiles: List[str] = None
) -> ReportMetadata:
    """
    Create ReportMetadata from ras-commander objects.

    Args:
        ras_object: Initialized RasPrj object
        plan_hdf_path: Path to plan HDF file
        geometry_hdf_path: Path to geometry HDF file
        profiles: List of profile names checked

    Returns:
        ReportMetadata instance

    Example:
        >>> init_ras_project(project_path, "6.5")
        >>> metadata = create_report_metadata(ras, plan_hdf, geom_hdf)
    """
    import h5py

    # Extract plan info
    plan_name = plan_hdf_path.stem
    geom_name = geometry_hdf_path.stem

    # Get RAS version from HDF
    ras_version = "Unknown"
    with h5py.File(plan_hdf_path, 'r') as hdf:
        if 'Plan Data/Plan Information' in hdf:
            attrs = hdf['Plan Data/Plan Information'].attrs
            if 'HEC-RAS Version' in attrs:
                ras_version = attrs['HEC-RAS Version']
                if isinstance(ras_version, bytes):
                    ras_version = ras_version.decode('utf-8')

    # Count cross sections and structures from geometry
    total_xs = 0
    total_structs = 0
    total_reaches = 0

    with h5py.File(geometry_hdf_path, 'r') as hdf:
        if 'Geometry/Cross Sections' in hdf:
            xs_group = hdf['Geometry/Cross Sections']
            if 'River Stations' in xs_group:
                total_xs = len(xs_group['River Stations'][()])

        if 'Geometry/Structures' in hdf:
            structs = hdf['Geometry/Structures']
            for struct_type in ['Bridges', 'Culverts', 'Inline Weirs']:
                if struct_type in structs:
                    total_structs += len(structs[struct_type].keys())

        if 'Geometry/River Centerlines' in hdf:
            total_reaches = len(hdf['Geometry/River Centerlines'].keys())

    return ReportMetadata(
        project_name=ras_object.project_name if hasattr(ras_object, 'project_name') else str(plan_hdf_path.parent.name),
        project_path=plan_hdf_path.parent,
        plan_name=plan_name,
        plan_hdf_path=plan_hdf_path,
        geometry_name=geom_name,
        geometry_hdf_path=geometry_hdf_path,
        ras_version=ras_version,
        report_generated=datetime.now(),
        profiles_checked=profiles,
        total_cross_sections=total_xs,
        total_structures=total_structs,
        total_reaches=total_reaches
    )
```

## Report Output Examples

### HTML Report Structure

```
RasCheck Validation Report
==========================

Project: Bald Eagle Creek
Plan: Floodplain Mapping
Geometry: Existing Conditions
HEC-RAS Version: 6.5
Report Generated: 2024-01-15 14:30:00

+--------+----------+---------+--------+
| ERRORS | WARNINGS |  INFO   | PASSED |
|   12   |    45    |   23    |  3/5   |
+--------+----------+---------+--------+

[Expand All] [Collapse All]

+--------------------------------------------------+
| Manning's n / Transition Coefficients  [8 msgs]  |
+--------------------------------------------------+
| ID        | Severity | Location        | Message |
| NT_RC_01L | ERROR    | Reach 1, 5000   | ...     |
| NT_TL_01  | WARNING  | Reach 1, 4500   | ...     |
+--------------------------------------------------+

+--------------------------------------------------+
| Cross Section Validation               [15 msgs] |
+--------------------------------------------------+
...

Generated by RasCheck v1.0.0 (ras-commander)
Based on FEMA cHECk-RAS validation methodology
```

### DataFrame Report Structure

```python
>>> dfs = generate_dataframe_report(results)
>>> dfs.keys()
dict_keys(['messages', 'summary', 'metadata', 'nt_details', 'xs_details', ...])

>>> dfs['messages'].head()
   message_id severity        location                    message  check_type
0   NT_RC_01L    ERROR  Reach 1, 5000  Left overbank Manning's...  Manning's n
1   NT_TL_01  WARNING  Reach 1, 4500  Transition coefficients...  Manning's n

>>> dfs['summary']
                    metric  count
0          Total Messages     80
1                  Errors     12
2                Warnings     45
3                    Info     23
...
```

### CSV Export Format

```csv
Message ID,Severity,Location,Message,River,Reach,Station,Profile,Value,Threshold,Help Text
NT_RC_01L,ERROR,"Reach 1, 5000","Left overbank Manning's n value (0.250) exceeds maximum threshold (0.200)",River 1,Reach 1,5000.0,,0.250,0.200,"Review land cover..."
NT_TL_01,WARNING,"Reach 1, 4500","Contraction coefficient (0.5) exceeds typical value for non-structure XS",River 1,Reach 1,4500.0,,0.5,0.3,"Verify..."
```

## Integration with RasCheck

### Usage Pattern

```python
from ras_commander import init_ras_project, ras
from ras_commander.RasCheck import RasCheck
from ras_commander.check.report import (
    generate_html_report,
    generate_dataframe_report,
    export_messages_csv,
    export_excel_report,
    create_report_metadata
)

# Initialize project
init_ras_project(r"C:\Projects\Example", "6.5")

# Run all checks
results = RasCheck.run_all(
    plan_hdf_path=Path("C:/Projects/Example/Example.p01.hdf"),
    geometry_hdf_path=Path("C:/Projects/Example/Example.g01.hdf"),
    profiles=['100yr', 'Floodway']
)

# Create metadata
metadata = create_report_metadata(
    ras,
    plan_hdf_path,
    geometry_hdf_path,
    profiles=['100yr', 'Floodway']
)

# Generate reports
html_path = generate_html_report(results, metadata, Path("report.html"))
dfs = generate_dataframe_report(results, metadata)
csv_path = export_messages_csv(results, Path("messages.csv"))
xlsx_path = export_excel_report(results, metadata, Path("report.xlsx"))

# Print summary
from ras_commander.check.report import generate_summary_text
print(generate_summary_text(results, metadata))
```

## Report Customization

### Custom Thresholds

Reports can highlight custom threshold violations:

```python
# Custom threshold highlighting in HTML
custom_thresholds = {
    'mannings_n_max': 0.150,  # More restrictive than default
    'surcharge_max': 0.5      # State-specific requirement
}

results = RasCheck.run_all(..., custom_thresholds=custom_thresholds)
```

### Filtering Messages

```python
# Filter to only errors
dfs = generate_dataframe_report(results)
errors_only = dfs['messages'][dfs['messages']['severity'] == 'ERROR']
errors_only.to_csv('errors_only.csv')

# Filter by check type
xs_messages = dfs['messages'][dfs['messages']['check_type'] == 'Cross Sections']
```

### Custom Report Sections

```python
# Add custom section to HTML report
def add_custom_section(html_content: str, section_html: str) -> str:
    """Insert custom section before footer."""
    insert_point = html_content.find("<div class='footer'>")
    return html_content[:insert_point] + section_html + html_content[insert_point:]
```

## Original cHECk-RAS Report Comparison

| Feature | cHECk-RAS | RasCheck |
|---------|-----------|----------|
| Output Format | PDF (iTextSharp) | HTML, CSV, Excel, DataFrame |
| Interactivity | None | Expandable sections, filtering |
| Data Export | None | Full DataFrame access |
| Customization | None | Programmatic control |
| Styling | Fixed | CSS customizable |
| Integration | Standalone | ras-commander workflow |

## Dependencies

### Required
- `pandas` - DataFrame operations (already in ras-commander)
- `html` - HTML escaping (standard library)
- `datetime` - Timestamps (standard library)

### Optional
- `openpyxl` - Excel export
- `jinja2` - Advanced HTML templating (future)
- `weasyprint` or `pdfkit` - PDF export (future)
