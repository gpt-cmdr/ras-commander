"""
Type definitions for the RasCheck quality assurance module.

Contains shared enums and dataclasses used across all check submodules.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pandas as pd


class Severity(Enum):
    """Message severity levels."""
    ERROR = "ERROR"      # Must be fixed
    WARNING = "WARNING"  # Should be reviewed
    INFO = "INFO"        # Informational only


class FlowType(Enum):
    """Flow type for plan classification."""
    STEADY = "steady"           # Steady flow plan with profiles
    UNSTEADY = "unsteady"       # Unsteady flow plan with time series
    GEOMETRY_ONLY = "geometry_only"  # No results, geometry checks only


@dataclass
class CheckMessage:
    """A single validation message."""
    message_id: str           # e.g., "NT_TL_01S2"
    severity: Severity        # ERROR, WARNING, INFO
    check_type: str           # NT, XS, STRUCT, FW, PROFILES
    river: str = ""
    reach: str = ""
    station: str = ""
    structure: str = ""
    message: str = ""
    help_text: str = ""
    flagged: bool = False
    comment: str = ""
    value: Optional[float] = None
    threshold: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for DataFrame creation."""
        return {
            'message_id': self.message_id,
            'severity': self.severity.value,
            'check_type': self.check_type,
            'river': self.river,
            'reach': self.reach,
            'station': self.station,
            'structure': self.structure,
            'message': self.message,
            'flagged': self.flagged,
            'comment': self.comment,
            'value': self.value,
            'threshold': self.threshold
        }


@dataclass
class CheckResults:
    """Container for all check results."""
    messages: List[CheckMessage] = field(default_factory=list)
    flow_type: Optional[FlowType] = None  # Detected flow type (steady/unsteady/geometry_only)
    nt_summary: Optional[pd.DataFrame] = None
    xs_summary: Optional[pd.DataFrame] = None
    struct_summary: Optional[pd.DataFrame] = None
    floodway_summary: Optional[pd.DataFrame] = None
    profiles_summary: Optional[pd.DataFrame] = None
    # Unsteady-specific summaries
    stability_summary: Optional[pd.DataFrame] = None
    mass_balance_summary: Optional[pd.DataFrame] = None
    peaks_summary: Optional[pd.DataFrame] = None
    mesh_summary: Optional[pd.DataFrame] = None
    statistics: Dict = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert all messages to a DataFrame."""
        if not self.messages:
            return pd.DataFrame()
        return pd.DataFrame([m.to_dict() for m in self.messages])

    def filter_by_severity(self, severity: Severity) -> List[CheckMessage]:
        """Filter messages by severity level."""
        return [m for m in self.messages if m.severity == severity]

    def filter_by_check_type(self, check_type: str) -> List[CheckMessage]:
        """Filter messages by check type."""
        return [m for m in self.messages if m.check_type == check_type]

    def filter_by_station(self, station: str) -> List[CheckMessage]:
        """Filter messages by river station."""
        return [m for m in self.messages if m.station == station]

    def get_error_count(self) -> int:
        """Count ERROR severity messages."""
        return len(self.filter_by_severity(Severity.ERROR))

    def get_warning_count(self) -> int:
        """Count WARNING severity messages."""
        return len(self.filter_by_severity(Severity.WARNING))

    def to_html(self, output_path: Path, metadata=None) -> Path:
        """
        Generate HTML report.

        NOTE: This is an UNOFFICIAL implementation inspired by FEMA cHECk-RAS.

        Args:
            output_path: Path for output HTML file
            metadata: Optional ReportMetadata for additional context

        Returns:
            Path to generated HTML file
        """
        from .report import RasCheckReport
        report = RasCheckReport(self, metadata)
        return report.generate_html(output_path)

    def __repr__(self) -> str:
        return (f"CheckResults(messages={len(self.messages)}, "
                f"errors={self.get_error_count()}, "
                f"warnings={self.get_warning_count()})")
