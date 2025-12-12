# RasCheck Class Specification

## Module Location

```
ras_commander/RasCheck.py
```

## Class Definition

```python
"""
RasCheck - Quality Assurance Validation for HEC-RAS Steady Flow Models

This module provides comprehensive validation of HEC-RAS 6.x steady flow models,
implementing equivalent functionality to the FEMA cHECk-RAS tool.

Supported Checks:
- NT Check: Manning's n values and transition loss coefficients
- XS Check: Cross section spacing, ineffective flow, boundary conditions
- Structure Check: Bridge, culvert, and inline weir validation
- Floodway Check: Encroachment methods and surcharge validation
- Profiles Check: Multiple profile comparison and consistency

Example:
    >>> from ras_commander import init_ras_project, RasCheck
    >>> init_ras_project("/path/to/project", "6.5")
    >>> results = RasCheck.run_all("01", profiles=['100yr', '500yr', 'Floodway'])
    >>> results.to_html("check_report.html")
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np
import h5py

from .Decorators import standardize_input, log_call
from .LoggingConfig import get_logger
from .RasPrj import ras

logger = get_logger(__name__)


class Severity(Enum):
    """Message severity levels."""
    ERROR = "ERROR"      # Must be fixed
    WARNING = "WARNING"  # Should be reviewed
    INFO = "INFO"        # Informational only


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
            'comment': self.comment
        }


@dataclass
class CheckResults:
    """Container for all check results."""
    messages: List[CheckMessage] = field(default_factory=list)
    nt_summary: Optional[pd.DataFrame] = None
    xs_summary: Optional[pd.DataFrame] = None
    struct_summary: Optional[pd.DataFrame] = None
    floodway_summary: Optional[pd.DataFrame] = None
    profiles_summary: Optional[pd.DataFrame] = None
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

    def to_html(self, output_path: Path, include_help: bool = True) -> Path:
        """Generate HTML report."""
        from .check.report import generate_html_report
        return generate_html_report(self, output_path, include_help)

    def __repr__(self) -> str:
        return (f"CheckResults(messages={len(self.messages)}, "
                f"errors={self.get_error_count()}, "
                f"warnings={self.get_warning_count()})")


class RasCheck:
    """
    Quality assurance validation for HEC-RAS 6.x steady flow models.

    All methods are static and follow ras-commander conventions.
    Use @standardize_input decorator for flexible path handling.
    """

    @staticmethod
    @log_call
    def run_all(
        plan: Union[str, Path],
        profiles: Optional[List[str]] = None,
        floodway_profile: Optional[str] = None,
        surcharge: float = 1.0,
        ras_object = None
    ) -> CheckResults:
        """
        Run all validation checks on a HEC-RAS plan.

        Args:
            plan: Plan number (e.g., "01") or path to plan HDF file
            profiles: List of profile names to check. If None, checks all profiles.
            floodway_profile: Name of floodway profile (triggers floodway checks)
            surcharge: Maximum allowable surcharge in feet (default 1.0)
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            CheckResults object containing all validation messages and summaries

        Example:
            >>> results = RasCheck.run_all("01",
            ...     profiles=['10yr', '50yr', '100yr', 'Floodway'],
            ...     floodway_profile='Floodway',
            ...     surcharge=1.0)
            >>> print(f"Found {results.get_error_count()} errors")
        """
        results = CheckResults()
        ras_obj = ras_object or ras

        # Resolve HDF paths
        plan_hdf, geom_hdf = RasCheck._resolve_hdf_paths(plan, ras_obj)

        # Verify this is a steady flow plan
        if not RasCheck._verify_steady_plan(plan_hdf):
            msg = CheckMessage(
                message_id="SYS_001",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message="This is not a steady flow plan. RasCheck only supports steady flow."
            )
            results.messages.append(msg)
            return results

        # Get profile information
        available_profiles = RasCheck._get_available_profiles(plan_hdf)
        if profiles is None:
            profiles = available_profiles

        # Run individual checks
        nt_results = RasCheck.check_nt(plan_hdf, geom_hdf)
        results.messages.extend(nt_results.messages)
        results.nt_summary = nt_results.nt_summary

        xs_results = RasCheck.check_xs(plan_hdf, geom_hdf, profiles)
        results.messages.extend(xs_results.messages)
        results.xs_summary = xs_results.xs_summary

        struct_results = RasCheck.check_structures(plan_hdf, geom_hdf, profiles)
        results.messages.extend(struct_results.messages)
        results.struct_summary = struct_results.struct_summary

        if floodway_profile and floodway_profile in profiles:
            base_profile = profiles[0] if profiles[0] != floodway_profile else profiles[1]
            fw_results = RasCheck.check_floodways(
                plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge
            )
            results.messages.extend(fw_results.messages)
            results.floodway_summary = fw_results.floodway_summary

        if len(profiles) >= 2:
            # Exclude floodway from profiles check
            check_profiles = [p for p in profiles if p != floodway_profile]
            if len(check_profiles) >= 2:
                prof_results = RasCheck.check_profiles(plan_hdf, check_profiles)
                results.messages.extend(prof_results.messages)
                results.profiles_summary = prof_results.profiles_summary

        # Calculate statistics
        results.statistics = RasCheck._calculate_statistics(results)

        return results

    @staticmethod
    @log_call
    def check_nt(
        plan_hdf: Path,
        geom_hdf: Path
    ) -> CheckResults:
        """
        Check Manning's n values and transition loss coefficients.

        Validates:
        - Left/right overbank n values (0.030 - 0.200)
        - Channel n values (0.025 - 0.100)
        - Transition coefficients at structures (0.3/0.5)
        - Transition coefficients at regular XS (0.1/0.3)
        - Channel n at bridge sections vs adjacent sections

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file

        Returns:
            CheckResults with NT check messages and summary DataFrame
        """
        from .check.nt_check import run_nt_check
        return run_nt_check(plan_hdf, geom_hdf)

    @staticmethod
    @log_call
    def check_xs(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: List[str]
    ) -> CheckResults:
        """
        Check cross section data validity.

        Validates:
        - Reach distances (overbank vs channel)
        - Cross section spacing criteria
        - Ineffective flow areas
        - Boundary conditions
        - Flow regime
        - Discharge continuity

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            profiles: List of profile names to check

        Returns:
            CheckResults with XS check messages and summary DataFrame
        """
        from .check.xs_check import run_xs_check
        return run_xs_check(plan_hdf, geom_hdf, profiles)

    @staticmethod
    @log_call
    def check_structures(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: List[str]
    ) -> CheckResults:
        """
        Check bridge, culvert, and inline weir data.

        Validates:
        - Section distances at structures
        - Flow type determination
        - Culvert coefficients
        - Ineffective flow at structures
        - Deck/roadway alignment

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            profiles: List of profile names to check

        Returns:
            CheckResults with structure check messages and summary DataFrame
        """
        from .check.struct_check import run_struct_check
        return run_struct_check(plan_hdf, geom_hdf, profiles)

    @staticmethod
    @log_call
    def check_floodways(
        plan_hdf: Path,
        geom_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        surcharge: float = 1.0
    ) -> CheckResults:
        """
        Check floodway encroachment analysis.

        Validates:
        - Encroachment method (Methods 2-5)
        - Starting water surface elevation
        - Floodway widths
        - Surcharge values
        - Floodway discharge matching

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            base_profile: Name of base (1% annual chance) profile
            floodway_profile: Name of floodway profile
            surcharge: Maximum allowable surcharge in feet

        Returns:
            CheckResults with floodway check messages and summary DataFrame
        """
        from .check.floodway_check import run_floodway_check
        return run_floodway_check(
            plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge
        )

    @staticmethod
    @log_call
    def check_profiles(
        plan_hdf: Path,
        profiles: List[str]
    ) -> CheckResults:
        """
        Check multiple profile consistency.

        Validates:
        - Boundary condition consistency
        - Water surface elevation ordering
        - Top width consistency
        - Discharge ordering

        Args:
            plan_hdf: Path to plan HDF file
            profiles: List of profile names to compare (ordered by frequency)

        Returns:
            CheckResults with profiles check messages and summary DataFrame
        """
        from .check.profiles_check import run_profiles_check
        return run_profiles_check(plan_hdf, profiles)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _resolve_hdf_paths(
        plan: Union[str, Path],
        ras_obj
    ) -> Tuple[Path, Path]:
        """Resolve plan and geometry HDF paths from plan identifier."""
        if isinstance(plan, str) and len(plan) <= 3:
            # Plan number format (e.g., "01")
            plan_row = ras_obj.plan_df.loc[plan]
            plan_hdf = Path(plan_row['HDF_Results_File'])
            geom_file = plan_row['Geom_File']
            geom_hdf = Path(str(geom_file).replace('.g', '.g') + '.hdf')
        else:
            plan_hdf = Path(plan)
            # Derive geometry HDF from plan HDF name
            geom_hdf = Path(str(plan_hdf).replace('.p', '.g').replace('.hdf', '.hdf'))

        return plan_hdf, geom_hdf

    @staticmethod
    def _verify_steady_plan(plan_hdf: Path) -> bool:
        """Check if plan contains steady flow results."""
        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                return 'Results/Steady' in hdf
        except Exception:
            return False

    @staticmethod
    def _get_available_profiles(plan_hdf: Path) -> List[str]:
        """Get list of available profile names from HDF."""
        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                if path in hdf:
                    names = hdf[path][:]
                    return [n.decode('utf-8').strip() for n in names]
        except Exception:
            pass
        return []

    @staticmethod
    def _calculate_statistics(results: CheckResults) -> Dict:
        """Calculate summary statistics from check results."""
        return {
            'total_messages': len(results.messages),
            'error_count': results.get_error_count(),
            'warning_count': results.get_warning_count(),
            'info_count': len(results.filter_by_severity(Severity.INFO)),
            'nt_messages': len(results.filter_by_check_type('NT')),
            'xs_messages': len(results.filter_by_check_type('XS')),
            'struct_messages': len(results.filter_by_check_type('STRUCT')),
            'fw_messages': len(results.filter_by_check_type('FW')),
            'profiles_messages': len(results.filter_by_check_type('PROFILES'))
        }
```

## Public API Summary

### Main Entry Points

| Method | Description |
|--------|-------------|
| `RasCheck.run_all()` | Run all checks on a plan |
| `RasCheck.check_nt()` | Manning's n and transition checks only |
| `RasCheck.check_xs()` | Cross section checks only |
| `RasCheck.check_structures()` | Structure checks only |
| `RasCheck.check_floodways()` | Floodway checks only |
| `RasCheck.check_profiles()` | Multiple profile checks only |

### Result Classes

| Class | Description |
|-------|-------------|
| `CheckResults` | Container for all check results |
| `CheckMessage` | Single validation message |
| `Severity` | Message severity enum (ERROR, WARNING, INFO) |

### CheckResults Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `to_dataframe()` | `pd.DataFrame` | All messages as DataFrame |
| `to_html(path)` | `Path` | Generate HTML report |
| `filter_by_severity(sev)` | `List[CheckMessage]` | Filter by severity |
| `filter_by_check_type(type)` | `List[CheckMessage]` | Filter by check type |
| `filter_by_station(sta)` | `List[CheckMessage]` | Filter by river station |
| `get_error_count()` | `int` | Count of ERROR messages |
| `get_warning_count()` | `int` | Count of WARNING messages |

## Usage Examples

### Basic Usage
```python
from ras_commander import init_ras_project, RasCheck

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Run all checks
results = RasCheck.run_all("01")

# View summary
print(f"Errors: {results.get_error_count()}")
print(f"Warnings: {results.get_warning_count()}")

# Export to HTML
results.to_html("validation_report.html")
```

### With Floodway Analysis
```python
results = RasCheck.run_all(
    plan="01",
    profiles=['10yr', '50yr', '100yr', '500yr', 'Floodway'],
    floodway_profile='Floodway',
    surcharge=0.5  # State-specific limit
)

# Get floodway-specific messages
fw_messages = results.filter_by_check_type('FW')
```

### Individual Check
```python
# Run only NT check
from pathlib import Path
plan_hdf = Path("/path/to/project/plan.p01.hdf")
geom_hdf = Path("/path/to/project/geom.g01.hdf")

nt_results = RasCheck.check_nt(plan_hdf, geom_hdf)
print(nt_results.nt_summary)
```

### Filter and Export Messages
```python
results = RasCheck.run_all("01")

# Get all errors
errors_df = pd.DataFrame([m.to_dict() for m in results.filter_by_severity(Severity.ERROR)])

# Get messages for specific station
station_msgs = results.filter_by_station("1234.56")

# Export all to CSV
results.to_dataframe().to_csv("all_messages.csv", index=False)
```
