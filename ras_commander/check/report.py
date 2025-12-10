"""
Report generation for RasCheck validation results.

This module generates HTML reports, DataFrame exports, and CSV message logs
from RasCheck validation results.

NOTE: This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
It is part of the ras-commander library and is not affiliated with or endorsed by FEMA.
The original cHECk-RAS is a Windows application developed for FEMA's National Flood
Insurance Program. This implementation provides similar functionality using modern
HDF-based data access for HEC-RAS 6.x models.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
import pandas as pd
from datetime import datetime
import html

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .RasCheck import CheckResults, CheckMessage, Severity

logger = get_logger(__name__)


# ============================================================================
# Report Data Classes
# ============================================================================

@dataclass
class ReportMetadata:
    """Metadata for report generation."""
    project_name: str = ""
    plan_name: str = ""
    geometry_name: str = ""
    report_generated: datetime = field(default_factory=datetime.now)

    # File paths
    project_path: Optional[Path] = None
    plan_hdf_path: Optional[Path] = None
    geometry_hdf_path: Optional[Path] = None

    # Profile information
    profiles_checked: List[str] = field(default_factory=list)
    base_flood_profile: Optional[str] = None
    floodway_profile: Optional[str] = None
    surcharge_limit: float = 1.0

    # Summary counts
    total_cross_sections: int = 0
    total_structures: int = 0


@dataclass
class ReportSummary:
    """Summary statistics for report."""
    total_messages: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    # By check type
    nt_messages: int = 0
    xs_messages: int = 0
    struct_messages: int = 0
    floodway_messages: int = 0
    profile_messages: int = 0


# ============================================================================
# CSS Styles for HTML Report
# ============================================================================

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
    .disclaimer {
        background: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 20px;
        font-size: 13px;
        color: #856404;
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
        display: flex;
        justify-content: space-between;
        align-items: center;
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
        body { background: white; }
        .container { box-shadow: none; }
    }
</style>
"""


# ============================================================================
# Report Generator Class
# ============================================================================

class RasCheckReport:
    """
    Generate reports from RasCheck validation results.

    This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
    It provides similar functionality for HEC-RAS 6.x models using HDF-based data access.

    Example:
        >>> results = RasCheck.check_nt(geom_hdf)
        >>> report = RasCheckReport(results, metadata)
        >>> report.generate_html("validation_report.html")
        >>> df = report.to_dataframe()
    """

    def __init__(
        self,
        results: Union[CheckResults, List[CheckResults]],
        metadata: Optional[ReportMetadata] = None
    ):
        """
        Initialize report generator.

        Args:
            results: Single CheckResults or list of CheckResults from different checks
            metadata: Optional report metadata
        """
        if isinstance(results, CheckResults):
            self.results_list = [results]
        else:
            self.results_list = results

        self.metadata = metadata or ReportMetadata()
        self._build_summary()

    def _build_summary(self):
        """Build summary statistics from all results."""
        self.summary = ReportSummary()

        all_messages = []
        for results in self.results_list:
            all_messages.extend(results.messages)

        self.all_messages = all_messages
        self.summary.total_messages = len(all_messages)
        self.summary.error_count = sum(1 for m in all_messages if m.severity == Severity.ERROR)
        self.summary.warning_count = sum(1 for m in all_messages if m.severity == Severity.WARNING)
        self.summary.info_count = sum(1 for m in all_messages if m.severity == Severity.INFO)

        # Count by check type
        for msg in all_messages:
            check_type = msg.check_type.upper() if msg.check_type else ""
            if check_type == "NT":
                self.summary.nt_messages += 1
            elif check_type == "XS":
                self.summary.xs_messages += 1
            elif check_type == "STRUCT":
                self.summary.struct_messages += 1
            elif check_type == "FLOODWAY":
                self.summary.floodway_messages += 1
            elif check_type == "PROFILES":
                self.summary.profile_messages += 1

    @log_call
    def generate_html(self, output_path: Union[str, Path]) -> Path:
        """
        Generate HTML report.

        Args:
            output_path: Path for output HTML file

        Returns:
            Path to generated report
        """
        output_path = Path(output_path)

        html_content = self._build_html()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Generated HTML report: {output_path}")
        return output_path

    def _build_html(self) -> str:
        """Build complete HTML document."""
        parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            f"    <title>RasCheck Validation Report - {html.escape(self.metadata.project_name or 'HEC-RAS Model')}</title>",
            HTML_STYLES,
            "</head>",
            "<body>",
            "<div class='container'>",
            self._build_header(),
            self._build_disclaimer(),
            self._build_metadata_section(),
            self._build_summary_section(),
            self._build_check_sections(),
            self._build_footer(),
            "</div>",
            "</body>",
            "</html>"
        ]
        return "\n".join(parts)

    def _build_header(self) -> str:
        """Build report header."""
        project_name = html.escape(self.metadata.project_name or "HEC-RAS Model")
        return f"<h1>RasCheck Validation Report</h1>\n<h2 style='border:none; padding:0; margin-top:0;'>{project_name}</h2>"

    def _build_disclaimer(self) -> str:
        """Build disclaimer section."""
        return """
        <div class='disclaimer'>
            <strong>Disclaimer:</strong> This is an <strong>unofficial</strong> Python implementation
            inspired by the FEMA cHECk-RAS tool. It is part of the ras-commander library and is
            <strong>not affiliated with or endorsed by FEMA</strong>. Results should be independently
            verified for official submissions. The original cHECk-RAS is a Windows application
            developed for FEMA's National Flood Insurance Program.
        </div>
        """

    def _build_metadata_section(self) -> str:
        """Build metadata section."""
        m = self.metadata
        rows = []

        if m.plan_name:
            rows.append(f"<tr><td>Plan</td><td>{html.escape(m.plan_name)}</td></tr>")
        if m.geometry_name:
            rows.append(f"<tr><td>Geometry</td><td>{html.escape(m.geometry_name)}</td></tr>")
        if m.profiles_checked:
            profiles = ", ".join(html.escape(p) for p in m.profiles_checked)
            rows.append(f"<tr><td>Profiles Checked</td><td>{profiles}</td></tr>")
        if m.base_flood_profile:
            rows.append(f"<tr><td>Base Flood Profile</td><td>{html.escape(m.base_flood_profile)}</td></tr>")
        if m.floodway_profile:
            rows.append(f"<tr><td>Floodway Profile</td><td>{html.escape(m.floodway_profile)}</td></tr>")
            rows.append(f"<tr><td>Surcharge Limit</td><td>{m.surcharge_limit:.2f} ft</td></tr>")

        rows.append(f"<tr><td>Report Generated</td><td>{m.report_generated.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>")

        if m.total_cross_sections > 0:
            rows.append(f"<tr><td>Cross Sections</td><td>{m.total_cross_sections}</td></tr>")
        if m.total_structures > 0:
            rows.append(f"<tr><td>Structures</td><td>{m.total_structures}</td></tr>")

        return f"""
        <div class='metadata'>
            <table>
                {''.join(rows)}
            </table>
        </div>
        """

    def _build_summary_section(self) -> str:
        """Build summary cards section."""
        s = self.summary

        # Determine if model passed (no errors)
        status_class = "passed" if s.error_count == 0 else "errors"
        status_text = "PASSED" if s.error_count == 0 else "ISSUES FOUND"

        return f"""
        <h2>Summary</h2>
        <div class='summary-box'>
            <div class='summary-card {status_class}'>
                <div class='count'>{status_text}</div>
                <div class='label'>Status</div>
            </div>
            <div class='summary-card errors'>
                <div class='count'>{s.error_count}</div>
                <div class='label'>Errors</div>
            </div>
            <div class='summary-card warnings'>
                <div class='count'>{s.warning_count}</div>
                <div class='label'>Warnings</div>
            </div>
            <div class='summary-card info'>
                <div class='count'>{s.info_count}</div>
                <div class='label'>Info</div>
            </div>
        </div>
        """

    def _build_check_sections(self) -> str:
        """Build individual check sections."""
        sections = []

        # Group messages by check type
        check_types = [
            ("NT", "Manning's n and Transitions", self.summary.nt_messages),
            ("XS", "Cross Section Validation", self.summary.xs_messages),
            ("STRUCT", "Structure Validation", self.summary.struct_messages),
            ("FLOODWAY", "Floodway Analysis", self.summary.floodway_messages),
            ("PROFILES", "Profile Consistency", self.summary.profile_messages),
        ]

        for check_type, title, count in check_types:
            messages = [m for m in self.all_messages
                       if (m.check_type or "").upper() == check_type]

            if messages or count > 0:
                sections.append(self._build_check_section(check_type, title, messages))

        # Handle any uncategorized messages
        categorized_types = {"NT", "XS", "STRUCT", "FLOODWAY", "PROFILES"}
        other_messages = [m for m in self.all_messages
                        if (m.check_type or "").upper() not in categorized_types]
        if other_messages:
            sections.append(self._build_check_section("OTHER", "Other Checks", other_messages))

        return "\n".join(sections)

    def _build_check_section(self, check_type: str, title: str, messages: List[CheckMessage]) -> str:
        """Build a single check section."""
        error_count = sum(1 for m in messages if m.severity == Severity.ERROR)
        warning_count = sum(1 for m in messages if m.severity == Severity.WARNING)

        badge_text = f"{len(messages)} messages"
        if error_count > 0:
            badge_text = f"{error_count} errors, {warning_count} warnings"
        elif warning_count > 0:
            badge_text = f"{warning_count} warnings"

        if not messages:
            content = "<div class='no-messages'>No issues found</div>"
        else:
            content = self._build_messages_table(messages)

        return f"""
        <div class='check-section'>
            <div class='check-header'>
                <span class='title'>{html.escape(title)}</span>
                <span class='badge'>{badge_text}</span>
            </div>
            <div class='check-content'>
                {content}
            </div>
        </div>
        """

    def _build_messages_table(self, messages: List[CheckMessage]) -> str:
        """Build messages table."""
        rows = []

        # Sort by severity (errors first, then warnings, then info)
        severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        sorted_messages = sorted(messages, key=lambda m: severity_order.get(m.severity, 3))

        for msg in sorted_messages:
            severity_class = f"severity-{msg.severity.value.lower()}"
            location = f"{msg.river} / {msg.reach} / RS {msg.station}" if msg.river else ""

            help_html = ""
            if msg.help_text:
                help_html = f"<div class='help-text'>{html.escape(msg.help_text)}</div>"

            rows.append(f"""
            <tr>
                <td><span class='{severity_class}'>{msg.severity.value}</span></td>
                <td><span class='message-id'>{html.escape(msg.message_id)}</span></td>
                <td>
                    {html.escape(msg.message)}
                    {help_html}
                </td>
                <td><span class='location'>{html.escape(location)}</span></td>
            </tr>
            """)

        return f"""
        <table class='messages'>
            <thead>
                <tr>
                    <th style='width:80px;'>Severity</th>
                    <th style='width:100px;'>ID</th>
                    <th>Message</th>
                    <th style='width:200px;'>Location</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """

    def _build_footer(self) -> str:
        """Build report footer."""
        return f"""
        <div class='footer'>
            <p>Generated by RasCheck (ras-commander) - An unofficial Python implementation inspired by FEMA cHECk-RAS</p>
            <p>Report generated: {self.metadata.report_generated.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><a href='https://github.com/billk-FM/ras-commander'>https://github.com/billk-FM/ras-commander</a></p>
        </div>
        """

    @log_call
    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert all messages to a DataFrame.

        Returns:
            DataFrame with all validation messages
        """
        if not self.all_messages:
            return pd.DataFrame()

        records = []
        for msg in self.all_messages:
            records.append({
                'severity': msg.severity.value,
                'check_type': msg.check_type,
                'message_id': msg.message_id,
                'message': msg.message,
                'river': msg.river,
                'reach': msg.reach,
                'station': msg.station,
                'value': msg.value,
                'threshold': msg.threshold,
                'help_text': msg.help_text
            })

        return pd.DataFrame(records)

    @log_call
    def export_csv(self, output_path: Union[str, Path]) -> Path:
        """
        Export messages to CSV file.

        Args:
            output_path: Path for output CSV file

        Returns:
            Path to generated CSV
        """
        output_path = Path(output_path)
        df = self.to_dataframe()
        df.to_csv(output_path, index=False)
        logger.info(f"Exported messages to CSV: {output_path}")
        return output_path

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics as dictionary.

        Returns:
            Dictionary with summary statistics
        """
        return {
            'total_messages': self.summary.total_messages,
            'error_count': self.summary.error_count,
            'warning_count': self.summary.warning_count,
            'info_count': self.summary.info_count,
            'passed': self.summary.error_count == 0,
            'by_check_type': {
                'NT': self.summary.nt_messages,
                'XS': self.summary.xs_messages,
                'STRUCT': self.summary.struct_messages,
                'FLOODWAY': self.summary.floodway_messages,
                'PROFILES': self.summary.profile_messages,
            }
        }


# ============================================================================
# Convenience Functions
# ============================================================================

@log_call
def generate_html_report(
    results: Union[CheckResults, List[CheckResults]],
    output_path: Union[str, Path],
    metadata: Optional[ReportMetadata] = None
) -> Path:
    """
    Generate HTML report from validation results.

    This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.

    Args:
        results: CheckResults or list of CheckResults
        output_path: Path for output HTML file
        metadata: Optional report metadata

    Returns:
        Path to generated report

    Example:
        >>> results = RasCheck.check_nt(geom_hdf)
        >>> generate_html_report(results, "report.html")
    """
    report = RasCheckReport(results, metadata)
    return report.generate_html(output_path)


@log_call
def export_messages_csv(
    results: Union[CheckResults, List[CheckResults]],
    output_path: Union[str, Path]
) -> Path:
    """
    Export validation messages to CSV.

    Args:
        results: CheckResults or list of CheckResults
        output_path: Path for output CSV file

    Returns:
        Path to generated CSV
    """
    report = RasCheckReport(results)
    return report.export_csv(output_path)
