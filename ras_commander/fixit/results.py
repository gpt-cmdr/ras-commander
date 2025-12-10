"""
Results dataclasses for RasFixit operations.

This module provides dataclasses for representing fix operation results,
including individual fix messages and aggregate results.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
from pathlib import Path


class FixAction(Enum):
    """Type of fix action taken."""
    OVERLAP_RESOLVED = "OVERLAP_RESOLVED"      # Overlapping obstructions merged via elevation envelope
    GAP_INSERTED = "GAP_INSERTED"              # 0.02-unit gap added for adjacency compliance
    SEGMENT_MERGED = "SEGMENT_MERGED"          # Same-elevation segments combined
    NO_ACTION = "NO_ACTION"                    # No fix needed (no issues detected)


@dataclass
class FixMessage:
    """
    A single fix action message for a cross section.

    Attributes:
        message_id: Unique identifier for the fix type (e.g., "FX_BO_01")
        fix_type: Category of fix (e.g., "OBSTRUCTION", "INEFFECTIVE", "BANK")
        river: River name (if available)
        reach: Reach name (if available)
        station: River station identifier
        action: Type of fix action taken
        message: Human-readable description of the fix
        original_count: Number of obstructions before fix
        fixed_count: Number of obstructions after fix
        original_data: List of (start_sta, end_sta, elevation) tuples before fix
        fixed_data: List of (start_sta, end_sta, elevation) tuples after fix
        visualization_path: Path to before/after PNG visualization (if generated)
    """
    message_id: str
    fix_type: str
    river: str = ""
    reach: str = ""
    station: str = ""
    action: FixAction = FixAction.NO_ACTION
    message: str = ""
    original_count: int = 0
    fixed_count: int = 0
    original_data: List[Tuple[float, float, float]] = field(default_factory=list)
    fixed_data: List[Tuple[float, float, float]] = field(default_factory=list)
    visualization_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for DataFrame creation.

        Returns:
            Dictionary representation of the fix message.
        """
        return {
            'message_id': self.message_id,
            'fix_type': self.fix_type,
            'river': self.river,
            'reach': self.reach,
            'station': self.station,
            'action': self.action.value,
            'message': self.message,
            'original_count': self.original_count,
            'fixed_count': self.fixed_count,
            'visualization': str(self.visualization_path) if self.visualization_path else None
        }


@dataclass
class FixResults:
    """
    Container for all fix operation results.

    Provides aggregate statistics and detailed messages for each fixed cross section.

    Attributes:
        messages: List of FixMessage objects for each processed cross section
        total_xs_checked: Total number of cross sections examined
        total_xs_fixed: Number of cross sections that were modified
        backup_path: Path to backup file (if created)
        visualization_folder: Path to folder containing PNG visualizations
        statistics: Additional statistics dictionary

    Example:
        >>> results = RasFixit.fix_blocked_obstructions("model.g01")
        >>> print(f"Fixed {results.total_xs_fixed} of {results.total_xs_checked} cross sections")
        >>> df = results.to_dataframe()
    """
    messages: List[FixMessage] = field(default_factory=list)
    total_xs_checked: int = 0
    total_xs_fixed: int = 0
    backup_path: Optional[Path] = None
    visualization_folder: Optional[Path] = None
    statistics: Dict[str, Any] = field(default_factory=dict)

    def to_dataframe(self) -> 'pd.DataFrame':
        """
        Convert all messages to a pandas DataFrame.

        Returns:
            DataFrame with one row per fix message.
        """
        import pandas as pd
        if not self.messages:
            return pd.DataFrame()
        return pd.DataFrame([m.to_dict() for m in self.messages])

    def get_fixed_count(self) -> int:
        """
        Count cross sections that were actually fixed.

        Returns:
            Number of messages with action other than NO_ACTION.
        """
        return len([m for m in self.messages if m.action != FixAction.NO_ACTION])

    def get_messages_by_action(self, action: FixAction) -> List[FixMessage]:
        """
        Filter messages by action type.

        Args:
            action: FixAction enum value to filter by.

        Returns:
            List of FixMessage objects matching the action.
        """
        return [m for m in self.messages if m.action == action]

    def __repr__(self) -> str:
        return (f"FixResults(checked={self.total_xs_checked}, "
                f"fixed={self.total_xs_fixed}, "
                f"messages={len(self.messages)})")
