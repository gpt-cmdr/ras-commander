"""
RasCheck - Quality Assurance Validation for HEC-RAS Steady Flow Models.

NOTE: This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
It is part of the ras-commander library and is NOT affiliated with or endorsed by FEMA.
The original cHECk-RAS is a Windows application developed for FEMA's National Flood
Insurance Program. This implementation provides similar functionality using modern
HDF-based data access for HEC-RAS 6.x models.

Supported Checks:
- NT Check: Manning's n values and transition loss coefficients
- XS Check: Cross section spacing, ineffective flow, reach lengths
- Structure Check: Bridge, culvert, and inline weir validation
- Floodway Check: Surcharge validation and discharge matching
- Profiles Check: Multiple profile comparison and consistency

Example:
    >>> from ras_commander.check import RasCheck
    >>> results = RasCheck.check_nt(geom_hdf)
    >>> print(f"Found {results.get_error_count()} errors")
    >>> results.to_html("check_report.html")
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np
import h5py

from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from ..RasPrj import ras
from .thresholds import ValidationThresholds, get_default_thresholds
from .messages import get_message_template, get_help_text, format_message

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
        thresholds: Optional[ValidationThresholds] = None,
        ras_object=None
    ) -> CheckResults:
        """
        Run all validation checks on a HEC-RAS plan.

        Args:
            plan: Plan number (e.g., "01") or path to plan HDF file
            profiles: List of profile names to check. If None, checks all profiles.
            floodway_profile: Name of floodway profile (triggers floodway checks)
            surcharge: Maximum allowable surcharge in feet (default 1.0)
            thresholds: Custom ValidationThresholds (uses defaults if None)
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

        if thresholds is None:
            thresholds = get_default_thresholds()

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
        nt_results = RasCheck.check_nt(geom_hdf, thresholds)
        results.messages.extend(nt_results.messages)
        results.nt_summary = nt_results.nt_summary

        xs_results = RasCheck.check_xs(plan_hdf, geom_hdf, profiles, thresholds)
        results.messages.extend(xs_results.messages)
        results.xs_summary = xs_results.xs_summary

        struct_results = RasCheck.check_structures(plan_hdf, geom_hdf, profiles, thresholds)
        results.messages.extend(struct_results.messages)
        results.struct_summary = struct_results.struct_summary

        if floodway_profile and floodway_profile in profiles:
            base_profile = profiles[0] if profiles[0] != floodway_profile else profiles[1]
            fw_results = RasCheck.check_floodways(
                plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge, thresholds
            )
            results.messages.extend(fw_results.messages)
            results.floodway_summary = fw_results.floodway_summary

        if len(profiles) >= 2:
            # Exclude floodway from profiles check
            check_profiles = [p for p in profiles if p != floodway_profile]
            if len(check_profiles) >= 2:
                prof_results = RasCheck.check_profiles(plan_hdf, check_profiles, thresholds)
                results.messages.extend(prof_results.messages)
                results.profiles_summary = prof_results.profiles_summary

        # Calculate statistics
        results.statistics = RasCheck._calculate_statistics(results)

        return results

    @staticmethod
    @log_call
    def check_nt(
        geom_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check Manning's n values and transition loss coefficients.

        Validates:
        - Left/right overbank n values (default: 0.030 - 0.200)
        - Channel n values (default: 0.025 - 0.100)
        - Transition coefficients at structures (0.3/0.5)
        - Transition coefficients at regular XS (0.1/0.3)
        - Channel n at bridge sections vs adjacent sections

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with NT check messages and summary DataFrame
        """
        from ..hdf.HdfXsec import HdfXsec

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        n_thresholds = thresholds.mannings_n
        t_thresholds = thresholds.transitions

        # Get cross section data with Manning's n values
        try:
            geom_hdf = Path(geom_hdf)
            xs_gdf = HdfXsec.get_cross_sections(geom_hdf)
        except Exception as e:
            logger.error(f"Failed to read geometry HDF: {e}")
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Failed to read geometry HDF: {e}"
            )
            results.messages.append(msg)
            return results

        if xs_gdf.empty:
            msg = CheckMessage(
                message_id="SYS_003",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message="No cross section data found in geometry HDF"
            )
            results.messages.append(msg)
            return results

        # Check for required columns
        required_cols = ['n_lob', 'n_channel', 'n_rob', 'Contr', 'Expan']
        missing_cols = [c for c in required_cols if c not in xs_gdf.columns]
        if missing_cols:
            msg = CheckMessage(
                message_id="SYS_004",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Missing required columns in geometry data: {missing_cols}"
            )
            results.messages.append(msg)
            return results

        # Create summary data for each cross section
        summary_data = []

        for idx, xs in xs_gdf.iterrows():
            river = xs.get('River', '')
            reach = xs.get('Reach', '')
            station = str(xs.get('RS', ''))
            n_lob = xs['n_lob']
            n_channel = xs['n_channel']
            n_rob = xs['n_rob']
            contr = xs['Contr']
            expan = xs['Expan']

            xs_summary = {
                'River': river,
                'Reach': reach,
                'RS': station,
                'n_lob': n_lob,
                'n_channel': n_channel,
                'n_rob': n_rob,
                'Contr': contr,
                'Expan': expan,
                'issues': []
            }

            # Skip if n values are NaN
            if pd.isna(n_lob) or pd.isna(n_channel) or pd.isna(n_rob):
                continue

            # NT_RC_01L: Left overbank n too low
            if n_lob < n_thresholds.overbank_min:
                msg = CheckMessage(
                    message_id="NT_RC_01L",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_01L", n=f"{n_lob:.3f}"),
                    help_text=get_help_text("NT_RC_01L"),
                    value=n_lob,
                    threshold=n_thresholds.overbank_min
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_01L")

            # NT_RC_02L: Left overbank n too high
            if n_lob > n_thresholds.overbank_max:
                msg = CheckMessage(
                    message_id="NT_RC_02L",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_02L", n=f"{n_lob:.3f}"),
                    help_text=get_help_text("NT_RC_02L"),
                    value=n_lob,
                    threshold=n_thresholds.overbank_max
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_02L")

            # NT_RC_01R: Right overbank n too low
            if n_rob < n_thresholds.overbank_min:
                msg = CheckMessage(
                    message_id="NT_RC_01R",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_01R", n=f"{n_rob:.3f}"),
                    help_text=get_help_text("NT_RC_01R"),
                    value=n_rob,
                    threshold=n_thresholds.overbank_min
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_01R")

            # NT_RC_02R: Right overbank n too high
            if n_rob > n_thresholds.overbank_max:
                msg = CheckMessage(
                    message_id="NT_RC_02R",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_02R", n=f"{n_rob:.3f}"),
                    help_text=get_help_text("NT_RC_02R"),
                    value=n_rob,
                    threshold=n_thresholds.overbank_max
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_02R")

            # NT_RC_03C: Channel n too low
            if n_channel < n_thresholds.channel_min:
                msg = CheckMessage(
                    message_id="NT_RC_03C",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_03C", n=f"{n_channel:.3f}"),
                    help_text=get_help_text("NT_RC_03C"),
                    value=n_channel,
                    threshold=n_thresholds.channel_min
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_03C")

            # NT_RC_04C: Channel n too high
            if n_channel > n_thresholds.channel_max:
                msg = CheckMessage(
                    message_id="NT_RC_04C",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("NT_RC_04C", n=f"{n_channel:.3f}"),
                    help_text=get_help_text("NT_RC_04C"),
                    value=n_channel,
                    threshold=n_thresholds.channel_max
                )
                messages.append(msg)
                xs_summary['issues'].append("NT_RC_04C")

            # NT_RC_05: Overbank n should be greater than channel n
            if n_lob <= n_channel or n_rob <= n_channel:
                # Only flag if the difference is significant
                if (n_channel - n_lob > 0.005) or (n_channel - n_rob > 0.005):
                    msg = CheckMessage(
                        message_id="NT_RC_05",
                        severity=Severity.INFO,
                        check_type="NT",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("NT_RC_05",
                            n_lob=f"{n_lob:.3f}",
                            n_rob=f"{n_rob:.3f}",
                            n_chl=f"{n_channel:.3f}"),
                        help_text=get_help_text("NT_RC_05")
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("NT_RC_05")

            # NT_TL_02: Check transition coefficients (for regular XS)
            # Standard values are 0.1 contraction, 0.3 expansion
            if not pd.isna(contr) and not pd.isna(expan):
                # Check if coefficients differ from typical values
                typical_contr = t_thresholds.regular_contraction_max
                typical_expan = t_thresholds.regular_expansion_max

                if abs(contr - typical_contr) > 0.05 or abs(expan - typical_expan) > 0.05:
                    # This is informational - coefficients may be intentionally different
                    msg = CheckMessage(
                        message_id="NT_TL_02",
                        severity=Severity.INFO,
                        check_type="NT",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("NT_TL_02",
                            station=station,
                            cc=f"{contr:.2f}",
                            ce=f"{expan:.2f}"),
                        help_text=get_help_text("NT_TL_02")
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("NT_TL_02")

            summary_data.append(xs_summary)

        # =====================================================================
        # NT_VR_01: N-Value Variation Between Adjacent Cross Sections
        # Check for large changes in Manning's n between consecutive XS
        # =====================================================================
        variation_messages = RasCheck._check_n_value_variation(xs_gdf, thresholds)
        messages.extend(variation_messages)

        # =====================================================================
        # NT_TL_01: Transition Coefficients at Structure Sections
        # Check structure sections (2, 3, 4) for proper 0.3/0.5 coefficients
        # =====================================================================
        struct_trans_messages = RasCheck._check_structure_transition_coefficients(geom_hdf, xs_gdf, thresholds)
        messages.extend(struct_trans_messages)

        # =====================================================================
        # Bridge Section Manning's n Checks (NT_RS_*)
        # Only run when bridges have custom internal Manning's n
        # =====================================================================
        bridge_messages = RasCheck._check_bridge_section_mannings_n(geom_hdf, thresholds)
        messages.extend(bridge_messages)

        results.messages = messages
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            # Convert issues list to string for display
            summary_df['issues'] = summary_df['issues'].apply(lambda x: ', '.join(x) if x else '')
            results.nt_summary = summary_df

        return results

    @staticmethod
    @log_call
    def check_xs(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: List[str],
        thresholds: Optional[ValidationThresholds] = None
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
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with XS check messages and summary DataFrame
        """
        from ..hdf.HdfXsec import HdfXsec
        from ..hdf.HdfResultsPlan import HdfResultsPlan

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        r_thresholds = thresholds.reach_length
        p_thresholds = thresholds.profiles

        # Get cross section geometry data
        try:
            geom_hdf = Path(geom_hdf)
            xs_gdf = HdfXsec.get_cross_sections(geom_hdf)
        except Exception as e:
            logger.error(f"Failed to read geometry HDF: {e}")
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Failed to read geometry HDF for XS check: {e}"
            )
            results.messages.append(msg)
            return results

        if xs_gdf.empty:
            results.messages = messages
            results.xs_summary = pd.DataFrame()
            return results

        # Get steady results if plan HDF exists
        steady_results = None
        try:
            plan_hdf = Path(plan_hdf)
            if plan_hdf.exists():
                steady_results = HdfResultsPlan.get_steady_results(plan_hdf)
        except Exception as e:
            logger.warning(f"Could not read steady results: {e}")

        # Create summary data
        summary_data = []

        # Check column names for reach lengths (they vary by HDF version)
        len_lob_col = 'Len Left' if 'Len Left' in xs_gdf.columns else None
        len_chl_col = 'Len Channel' if 'Len Channel' in xs_gdf.columns else None
        len_rob_col = 'Len Right' if 'Len Right' in xs_gdf.columns else None

        # Build bridge section mapping for WSE exceedance checks
        # Maps (river, reach, RS) -> 'US' or 'DS' for bridge sections
        bridge_sections = {}
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' in hdf:
                    struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                    attr_names = struct_attrs.dtype.names
                    if 'US Type' in attr_names and 'DS Type' in attr_names:
                        for attr in struct_attrs:
                            us_type = attr['US Type'].decode().strip() if isinstance(attr['US Type'], bytes) else str(attr['US Type']).strip()
                            ds_type = attr['DS Type'].decode().strip() if isinstance(attr['DS Type'], bytes) else str(attr['DS Type']).strip()
                            if us_type == 'XS' and ds_type == 'XS':
                                river = attr['River'].decode().strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                                reach = attr['Reach'].decode().strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                                us_rs = attr['US RS'].decode().strip() if isinstance(attr['US RS'], bytes) else str(attr['US RS'])
                                ds_rs = attr['DS RS'].decode().strip() if isinstance(attr['DS RS'], bytes) else str(attr['DS RS'])
                                bridge_rs = attr['RS'].decode().strip() if isinstance(attr['RS'], bytes) else str(attr['RS'])
                                bridge_sections[(river, reach, us_rs)] = ('US', bridge_rs)
                                bridge_sections[(river, reach, ds_rs)] = ('DS', bridge_rs)
        except Exception as e:
            logger.debug(f"Could not build bridge section mapping: {e}")

        for idx, xs in xs_gdf.iterrows():
            river = xs.get('River', '')
            reach = xs.get('Reach', '')
            station = str(xs.get('RS', ''))

            xs_summary = {
                'River': river,
                'Reach': reach,
                'RS': station,
                'issues': []
            }

            # Get reach lengths
            len_lob = xs.get(len_lob_col, np.nan) if len_lob_col else np.nan
            len_chl = xs.get(len_chl_col, np.nan) if len_chl_col else np.nan
            len_rob = xs.get(len_rob_col, np.nan) if len_rob_col else np.nan

            xs_summary['Len_LOB'] = len_lob
            xs_summary['Len_CHL'] = len_chl
            xs_summary['Len_ROB'] = len_rob

            # XS_DT_01: Both overbanks exceed channel by more than 25 ft
            if (not pd.isna(len_lob) and not pd.isna(len_chl) and not pd.isna(len_rob)
                and len_chl > 0):
                if (len_lob - len_chl > 25) and (len_rob - len_chl > 25):
                    msg = CheckMessage(
                        message_id="XS_DT_01",
                        severity=Severity.WARNING,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("XS_DT_01",
                            lob=f"{len_lob:.0f}",
                            rob=f"{len_rob:.0f}",
                            chl=f"{len_chl:.0f}"),
                        help_text=get_help_text("XS_DT_01")
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("XS_DT_01")

            # XS_DT_02L: Left overbank > 2x channel
            if (not pd.isna(len_lob) and not pd.isna(len_chl)
                and len_chl > 0 and len_lob / len_chl > r_thresholds.length_ratio_max):
                msg = CheckMessage(
                    message_id="XS_DT_02L",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_DT_02L",
                        lob=f"{len_lob:.0f}",
                        chl=f"{len_chl:.0f}"),
                    help_text=get_help_text("XS_DT_02L"),
                    value=len_lob / len_chl,
                    threshold=r_thresholds.length_ratio_max
                )
                messages.append(msg)
                xs_summary['issues'].append("XS_DT_02L")

            # XS_DT_02R: Right overbank > 2x channel
            if (not pd.isna(len_rob) and not pd.isna(len_chl)
                and len_chl > 0 and len_rob / len_chl > r_thresholds.length_ratio_max):
                msg = CheckMessage(
                    message_id="XS_DT_02R",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_DT_02R",
                        rob=f"{len_rob:.0f}",
                        chl=f"{len_chl:.0f}"),
                    help_text=get_help_text("XS_DT_02R"),
                    value=len_rob / len_chl,
                    threshold=r_thresholds.length_ratio_max
                )
                messages.append(msg)
                xs_summary['issues'].append("XS_DT_02R")

            # XS_FS_01: Long reach lengths may benefit from Average Conveyance
            # Check if channel reach length exceeds 500 ft
            friction_mode = xs.get('Friction Mode', '')
            if not pd.isna(len_chl) and len_chl > 500:
                # Only warn if not already using Average Conveyance
                if friction_mode and 'average' not in str(friction_mode).lower():
                    msg = CheckMessage(
                        message_id="XS_FS_01",
                        severity=Severity.INFO,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("XS_FS_01",
                            frictionslopename=str(friction_mode) if friction_mode else "Standard"),
                        help_text=get_help_text("XS_FS_01"),
                        value=len_chl
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("XS_FS_01")

            # XS_CT_01/02: Conveyance tube/subdivision checks
            hp_lob_slices = xs.get('HP LOB Slices', 0)
            hp_chan_slices = xs.get('HP Chan Slices', 0)
            hp_rob_slices = xs.get('HP ROB Slices', 0)

            # Check for zero subdivisions (potential issue)
            if hp_lob_slices == 0:
                msg = CheckMessage(
                    message_id="XS_CT_02",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_CT_02", region="LOB"),
                    help_text=get_help_text("XS_CT_02")
                )
                messages.append(msg)
                if "XS_CT_02" not in xs_summary['issues']:
                    xs_summary['issues'].append("XS_CT_02")

            if hp_chan_slices == 0:
                msg = CheckMessage(
                    message_id="XS_CT_02",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_CT_02", region="Channel"),
                    help_text=get_help_text("XS_CT_02")
                )
                messages.append(msg)
                if "XS_CT_02" not in xs_summary['issues']:
                    xs_summary['issues'].append("XS_CT_02")

            if hp_rob_slices == 0:
                msg = CheckMessage(
                    message_id="XS_CT_02",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_CT_02", region="ROB"),
                    help_text=get_help_text("XS_CT_02")
                )
                messages.append(msg)
                if "XS_CT_02" not in xs_summary['issues']:
                    xs_summary['issues'].append("XS_CT_02")

            # Check for non-standard subdivision counts (>20 is unusual)
            if hp_lob_slices > 20 or hp_chan_slices > 20 or hp_rob_slices > 20:
                msg = CheckMessage(
                    message_id="XS_CT_01",
                    severity=Severity.INFO,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_CT_01",
                        lob_slices=hp_lob_slices,
                        chan_slices=hp_chan_slices,
                        rob_slices=hp_rob_slices),
                    help_text=get_help_text("XS_CT_01")
                )
                messages.append(msg)
                if "XS_CT_01" not in xs_summary['issues']:
                    xs_summary['issues'].append("XS_CT_01")

            # XS_GD_01/02: GIS cut line data review
            default_centerline = xs.get('Default Centerline', 1)
            # Note: Default Centerline = 1 means using default, 0 means using GIS cut line
            if default_centerline == 0:
                # Using non-default (GIS) centerline - may need review
                msg = CheckMessage(
                    message_id="XS_GD_01",
                    severity=Severity.INFO,
                    check_type="XS",
                    river=river,
                    reach=reach,
                    station=station,
                    message=format_message("XS_GD_01", station=station),
                    help_text=get_help_text("XS_GD_01")
                )
                messages.append(msg)
                if "XS_GD_01" not in xs_summary['issues']:
                    xs_summary['issues'].append("XS_GD_01")

            # Check ineffective flow areas
            ineff_blocks = xs.get('ineffective_blocks', None)
            left_bank = xs.get('Left Bank', 0)
            right_bank = xs.get('Right Bank', 0)
            sta_elev = xs.get('station_elevation', None)

            if ineff_blocks is not None and len(ineff_blocks) > 0:
                center = (left_bank + right_bank) / 2 if left_bank and right_bank else 0

                # Count left and right ineffective areas and track their properties
                left_count = 0
                right_count = 0
                left_ineff_blocks = []
                right_ineff_blocks = []

                for block in ineff_blocks:
                    # ineffective_blocks is a list of dicts with 'Left Sta', 'Right Sta', 'Elevation', 'Permanent'
                    if isinstance(block, dict):
                        sta_start = block.get('Left Sta', 0)
                        sta_end = block.get('Right Sta', sta_start)
                        ineff_elev = block.get('Elevation', None)
                        is_permanent = block.get('Permanent', False)
                    elif hasattr(block, '__len__') and len(block) >= 2:
                        sta_start = block[0]
                        sta_end = block[1] if len(block) > 1 else block[0]
                        ineff_elev = block[2] if len(block) > 2 else None
                        is_permanent = block[3] if len(block) > 3 else False
                    else:
                        continue

                    if sta_end <= center:
                        left_count += 1
                        left_ineff_blocks.append({
                            'sta_start': sta_start, 'sta_end': sta_end,
                            'elev': ineff_elev, 'permanent': is_permanent
                        })
                    elif sta_start >= center:
                        right_count += 1
                        right_ineff_blocks.append({
                            'sta_start': sta_start, 'sta_end': sta_end,
                            'elev': ineff_elev, 'permanent': is_permanent
                        })

                # XS_IF_02L: Multiple left ineffective areas
                if left_count > 1:
                    msg = CheckMessage(
                        message_id="XS_IF_02L",
                        severity=Severity.INFO,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=get_message_template("XS_IF_02L"),
                        help_text=get_help_text("XS_IF_02L")
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("XS_IF_02L")

                # XS_IF_02R: Multiple right ineffective areas
                if right_count > 1:
                    msg = CheckMessage(
                        message_id="XS_IF_02R",
                        severity=Severity.INFO,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=get_message_template("XS_IF_02R"),
                        help_text=get_help_text("XS_IF_02R")
                    )
                    messages.append(msg)
                    xs_summary['issues'].append("XS_IF_02R")

                # XS_IF_03L: Left ineffective station beyond left bank station
                for block in left_ineff_blocks:
                    if block['sta_end'] > left_bank:
                        msg = CheckMessage(
                            message_id="XS_IF_03L",
                            severity=Severity.WARNING,
                            check_type="XS",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("XS_IF_03L",
                                ineffstal=f"{block['sta_end']:.1f}",
                                bankstal=f"{left_bank:.1f}"),
                            help_text=get_help_text("XS_IF_03L")
                        )
                        messages.append(msg)
                        if "XS_IF_03L" not in xs_summary['issues']:
                            xs_summary['issues'].append("XS_IF_03L")
                        break  # Only report once per XS

                # XS_IF_03R: Right ineffective station beyond right bank station
                for block in right_ineff_blocks:
                    if block['sta_start'] < right_bank:
                        msg = CheckMessage(
                            message_id="XS_IF_03R",
                            severity=Severity.WARNING,
                            check_type="XS",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("XS_IF_03R",
                                ineffstar=f"{block['sta_start']:.1f}",
                                bankstar=f"{right_bank:.1f}"),
                            help_text=get_help_text("XS_IF_03R")
                        )
                        messages.append(msg)
                        if "XS_IF_03R" not in xs_summary['issues']:
                            xs_summary['issues'].append("XS_IF_03R")
                        break  # Only report once per XS

            # XS_BO_01L/R and XS_BO_02L/R: Blocked obstruction checks
            blocked_obs = xs.get('blocked_obstructions', None)
            if blocked_obs is not None and len(blocked_obs) > 0 and sta_elev is not None and len(sta_elev) > 0:
                left_ground_sta = sta_elev[0][0]  # First point station
                right_ground_sta = sta_elev[-1][0]  # Last point station
                center = (left_bank + right_bank) / 2 if left_bank and right_bank else (left_ground_sta + right_ground_sta) / 2

                left_blocked_count = 0
                right_blocked_count = 0

                for obs in blocked_obs:
                    if isinstance(obs, dict):
                        obs_sta_start = obs.get('Left Sta', obs.get('Sta Start', 0))
                        obs_sta_end = obs.get('Right Sta', obs.get('Sta End', obs_sta_start))
                    elif hasattr(obs, '__len__') and len(obs) >= 2:
                        obs_sta_start = obs[0]
                        obs_sta_end = obs[1] if len(obs) > 1 else obs[0]
                    else:
                        continue

                    obs_center = (obs_sta_start + obs_sta_end) / 2

                    if obs_center < center:
                        left_blocked_count += 1
                        # XS_BO_01L: Check if blocked obstruction starts at left ground point
                        if abs(obs_sta_start - left_ground_sta) < 1.0:  # Within 1 ft tolerance
                            if "XS_BO_01L" not in xs_summary['issues']:
                                msg = CheckMessage(
                                    message_id="XS_BO_01L",
                                    severity=Severity.INFO,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("XS_BO_01L"),
                                    help_text=get_help_text("XS_BO_01L")
                                )
                                messages.append(msg)
                                xs_summary['issues'].append("XS_BO_01L")
                    else:
                        right_blocked_count += 1
                        # XS_BO_01R: Check if blocked obstruction starts at right ground point
                        if abs(obs_sta_end - right_ground_sta) < 1.0:  # Within 1 ft tolerance
                            if "XS_BO_01R" not in xs_summary['issues']:
                                msg = CheckMessage(
                                    message_id="XS_BO_01R",
                                    severity=Severity.INFO,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("XS_BO_01R"),
                                    help_text=get_help_text("XS_BO_01R")
                                )
                                messages.append(msg)
                                xs_summary['issues'].append("XS_BO_01R")

                # XS_BO_02L/R: Multiple blocked obstructions
                if left_blocked_count > 1:
                    msg = CheckMessage(
                        message_id="XS_BO_02L",
                        severity=Severity.INFO,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=get_message_template("XS_BO_02L"),
                        help_text=get_help_text("XS_BO_02L")
                    )
                    messages.append(msg)
                    if "XS_BO_02L" not in xs_summary['issues']:
                        xs_summary['issues'].append("XS_BO_02L")

                if right_blocked_count > 1:
                    msg = CheckMessage(
                        message_id="XS_BO_02R",
                        severity=Severity.INFO,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=get_message_template("XS_BO_02R"),
                        help_text=get_help_text("XS_BO_02R")
                    )
                    messages.append(msg)
                    if "XS_BO_02R" not in xs_summary['issues']:
                        xs_summary['issues'].append("XS_BO_02R")

            # XS_LV_04L/R: Levee overtopping checks (geometry-only, no WSE needed yet)
            left_levee_sta = xs.get('Left Levee Sta', None)
            left_levee_elev = xs.get('Left Levee Elev', None)
            right_levee_sta = xs.get('Right Levee Sta', None)
            right_levee_elev = xs.get('Right Levee Elev', None)

            # Store levee info for results-based checks later
            xs_summary['left_levee_elev'] = left_levee_elev
            xs_summary['right_levee_elev'] = right_levee_elev

            # Check results data for each profile
            if steady_results is not None and not steady_results.empty:
                # Find matching results for this XS
                xs_results = steady_results[
                    (steady_results['river'] == river) &
                    (steady_results['reach'] == reach) &
                    (steady_results['node_id'] == station)
                ]

                for _, result in xs_results.iterrows():
                    profile = result['profile']
                    wsel = result.get('wsel', np.nan)
                    velocity = result.get('velocity', np.nan)
                    froude = result.get('froude', np.nan)

                    # Check velocity reasonableness
                    if not pd.isna(velocity):
                        if velocity > p_thresholds.velocity_max_fps:
                            msg = CheckMessage(
                                message_id="XS_VEL_01",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"High velocity ({velocity:.1f} ft/s) for {profile}",
                                help_text="Velocity exceeds typical maximum. Verify geometry and roughness.",
                                value=velocity,
                                threshold=p_thresholds.velocity_max_fps
                            )
                            messages.append(msg)

                    # Check Froude number (supercritical flow warning)
                    if not pd.isna(froude):
                        if froude >= p_thresholds.froude_subcritical_max:
                            # This is informational - supercritical flow occurs
                            if froude > p_thresholds.froude_supercritical_max:
                                msg = CheckMessage(
                                    message_id="XS_FR_03",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Extreme Froude number ({froude:.2f}) for {profile}",
                                    help_text="Very high Froude number may indicate unstable flow conditions.",
                                    value=froude,
                                    threshold=p_thresholds.froude_supercritical_max
                                )
                                messages.append(msg)

                    # XS_EC_01L/R: Check if WSE exceeds ground at left/right boundary
                    # Also check for bridge sections (XS_EC_01BUL/BUR/BDL/BDR)
                    sta_elev = xs.get('station_elevation', None)
                    if not pd.isna(wsel) and sta_elev is not None and len(sta_elev) > 0:
                        # Get left and right ground elevations
                        left_ground = sta_elev[0][1]  # First point elevation
                        right_ground = sta_elev[-1][1]  # Last point elevation

                        # Check if this XS is a bridge section
                        bridge_info = bridge_sections.get((river, reach, station), None)

                        if wsel > left_ground:
                            # Determine message ID based on bridge section type
                            if bridge_info is not None:
                                bridge_side, bridge_rs = bridge_info
                                if bridge_side == 'US':
                                    msg_id = "XS_EC_01BUL"
                                else:  # DS
                                    msg_id = "XS_EC_01BDL"
                            else:
                                msg_id = "XS_EC_01L"

                            msg = CheckMessage(
                                message_id=msg_id,
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message(msg_id,
                                    wsel=f"{wsel:.2f}",
                                    grelv=f"{left_ground:.2f}",
                                    assignedname=profile),
                                help_text=get_help_text(msg_id),
                                value=wsel - left_ground
                            )
                            messages.append(msg)
                            if msg_id not in xs_summary['issues']:
                                xs_summary['issues'].append(msg_id)

                        if wsel > right_ground:
                            # Determine message ID based on bridge section type
                            if bridge_info is not None:
                                bridge_side, bridge_rs = bridge_info
                                if bridge_side == 'US':
                                    msg_id = "XS_EC_01BUR"
                                else:  # DS
                                    msg_id = "XS_EC_01BDR"
                            else:
                                msg_id = "XS_EC_01R"

                            msg = CheckMessage(
                                message_id=msg_id,
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message(msg_id,
                                    wsel=f"{wsel:.2f}",
                                    grelv=f"{right_ground:.2f}",
                                    assignedname=profile),
                                help_text=get_help_text(msg_id),
                                value=wsel - right_ground
                            )
                            messages.append(msg)
                            if msg_id not in xs_summary['issues']:
                                xs_summary['issues'].append(msg_id)

                    # XS_CD_01: Check for critical depth with permanent ineffective
                    if not pd.isna(froude) and froude >= 0.95:  # Near or at critical
                        ineff_blocks_check = xs.get('ineffective_blocks', None)
                        if ineff_blocks_check is not None and len(ineff_blocks_check) > 0:
                            # Check if any are permanent
                            has_permanent = False
                            for block in ineff_blocks_check:
                                if isinstance(block, dict) and block.get('Permanent', False):
                                    has_permanent = True
                                    break
                            if has_permanent:
                                msg = CheckMessage(
                                    message_id="XS_CD_01",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("XS_CD_01", assignedname=profile),
                                    help_text=get_help_text("XS_CD_01"),
                                    value=froude
                                )
                                messages.append(msg)
                                if "XS_CD_01" not in xs_summary['issues']:
                                    xs_summary['issues'].append("XS_CD_01")

                    # XS_CD_02: Critical depth with low channel n
                    n_channel = xs.get('n_channel', np.nan)
                    if not pd.isna(froude) and froude >= 0.95 and not pd.isna(n_channel):
                        if n_channel < 0.025:
                            msg = CheckMessage(
                                message_id="XS_CD_02",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("XS_CD_02", assignedname=profile),
                                help_text=get_help_text("XS_CD_02"),
                                value=n_channel
                            )
                            messages.append(msg)
                            if "XS_CD_02" not in xs_summary['issues']:
                                xs_summary['issues'].append("XS_CD_02")

                    # XS_LV_04L: Left levee overtopped
                    if not pd.isna(wsel) and left_levee_elev is not None and not pd.isna(left_levee_elev):
                        if wsel > left_levee_elev:
                            msg = CheckMessage(
                                message_id="XS_LV_04L",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("XS_LV_04L",
                                    assignedname=profile,
                                    wselev=f"{wsel:.2f}",
                                    leveel=f"{left_levee_elev:.2f}"),
                                help_text=get_help_text("XS_LV_04L"),
                                value=wsel - left_levee_elev
                            )
                            messages.append(msg)
                            if "XS_LV_04L" not in xs_summary['issues']:
                                xs_summary['issues'].append("XS_LV_04L")

                    # XS_LV_04R: Right levee overtopped
                    if not pd.isna(wsel) and right_levee_elev is not None and not pd.isna(right_levee_elev):
                        if wsel > right_levee_elev:
                            msg = CheckMessage(
                                message_id="XS_LV_04R",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("XS_LV_04R",
                                    assignedname=profile,
                                    wselev=f"{wsel:.2f}",
                                    leveel=f"{right_levee_elev:.2f}"),
                                help_text=get_help_text("XS_LV_04R"),
                                value=wsel - right_levee_elev
                            )
                            messages.append(msg)
                            if "XS_LV_04R" not in xs_summary['issues']:
                                xs_summary['issues'].append("XS_LV_04R")

                    # XS_IF_01L/R: Ineffective flow area with ground below WSE
                    # Check if ineffective areas are "active" but ground is below WSE
                    if not pd.isna(wsel) and ineff_blocks is not None and sta_elev is not None:
                        for block in ineff_blocks:
                            if isinstance(block, dict):
                                block_sta_start = block.get('Left Sta', 0)
                                block_sta_end = block.get('Right Sta', block_sta_start)
                                block_elev = block.get('Elevation', None)
                            else:
                                continue

                            if block_elev is None:
                                continue

                            # Determine if this is left or right ineffective
                            block_center = (block_sta_start + block_sta_end) / 2
                            xs_center = (left_bank + right_bank) / 2

                            # Find ground elevation at the ineffective area station
                            ground_at_ineff = None
                            for i in range(len(sta_elev) - 1):
                                if sta_elev[i][0] <= block_center <= sta_elev[i+1][0]:
                                    # Linear interpolation
                                    t = (block_center - sta_elev[i][0]) / (sta_elev[i+1][0] - sta_elev[i][0]) if sta_elev[i+1][0] != sta_elev[i][0] else 0
                                    ground_at_ineff = sta_elev[i][1] + t * (sta_elev[i+1][1] - sta_elev[i][1])
                                    break

                            if ground_at_ineff is not None and wsel > block_elev and ground_at_ineff < wsel:
                                # Ineffective is active (WSE > ineff elev) but ground is below WSE
                                if block_center < xs_center:
                                    msg = CheckMessage(
                                        message_id="XS_IF_01L",
                                        severity=Severity.WARNING,
                                        check_type="XS",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("XS_IF_01L",
                                            assignedname=profile,
                                            grelv=f"{ground_at_ineff:.2f}",
                                            wsel=f"{wsel:.2f}"),
                                        help_text=get_help_text("XS_IF_01L")
                                    )
                                    messages.append(msg)
                                    if "XS_IF_01L" not in xs_summary['issues']:
                                        xs_summary['issues'].append("XS_IF_01L")
                                else:
                                    msg = CheckMessage(
                                        message_id="XS_IF_01R",
                                        severity=Severity.WARNING,
                                        check_type="XS",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("XS_IF_01R",
                                            assignedname=profile,
                                            grelv=f"{ground_at_ineff:.2f}",
                                            wsel=f"{wsel:.2f}"),
                                        help_text=get_help_text("XS_IF_01R")
                                    )
                                    messages.append(msg)
                                    if "XS_IF_01R" not in xs_summary['issues']:
                                        xs_summary['issues'].append("XS_IF_01R")

                    # XS_DF_01L/R: Check for default ineffective flow areas
                    # Default patterns: ineffective area from XS edge to bank, high/no elevation
                    if ineff_blocks is not None and sta_elev is not None and len(sta_elev) > 0:
                        left_ground_sta = sta_elev[0][0]
                        right_ground_sta = sta_elev[-1][0]

                        for block in ineff_blocks:
                            if isinstance(block, dict):
                                block_sta_start = block.get('Left Sta', 0)
                                block_sta_end = block.get('Right Sta', block_sta_start)
                                block_elev = block.get('Elevation', None)
                                is_permanent = block.get('Permanent', False)
                            else:
                                continue

                            # Check if this looks like a default left ineffective area
                            # Criteria: starts at or near left ground station, extends to or near left bank
                            if (abs(block_sta_start - left_ground_sta) < 5.0 and
                                left_bank and abs(block_sta_end - left_bank) < 5.0):
                                # This could be a default ineffective area
                                # Check if elevation is unusually high or permanent
                                if is_permanent or block_elev is None or (len(sta_elev) > 0 and block_elev > max(p[1] for p in sta_elev) + 10):
                                    if "XS_DF_01L" not in xs_summary['issues']:
                                        msg = CheckMessage(
                                            message_id="XS_DF_01L",
                                            severity=Severity.INFO,
                                            check_type="XS",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message("XS_DF_01L", assignedname=profile),
                                            help_text=get_help_text("XS_DF_01L")
                                        )
                                        messages.append(msg)
                                        xs_summary['issues'].append("XS_DF_01L")

                            # Check if this looks like a default right ineffective area
                            if (abs(block_sta_end - right_ground_sta) < 5.0 and
                                right_bank and abs(block_sta_start - right_bank) < 5.0):
                                if is_permanent or block_elev is None or (len(sta_elev) > 0 and block_elev > max(p[1] for p in sta_elev) + 10):
                                    if "XS_DF_01R" not in xs_summary['issues']:
                                        msg = CheckMessage(
                                            message_id="XS_DF_01R",
                                            severity=Severity.INFO,
                                            check_type="XS",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message("XS_DF_01R", assignedname=profile),
                                            help_text=get_help_text("XS_DF_01R")
                                        )
                                        messages.append(msg)
                                        xs_summary['issues'].append("XS_DF_01R")

            # XS_LV_05L/R: Levee ground below WSE but levee not overtopped
            # This check compares across profiles for this XS
            if steady_results is not None and not steady_results.empty:
                xs_results = steady_results[
                    (steady_results['river'] == river) &
                    (steady_results['reach'] == reach) &
                    (steady_results['node_id'] == station)
                ]

                if not xs_results.empty and sta_elev is not None and len(sta_elev) > 0:
                    left_ground = sta_elev[0][1]
                    right_ground = sta_elev[-1][1]

                    # For left levee
                    if left_levee_elev is not None and not pd.isna(left_levee_elev):
                        # Find profiles where ground < WSE but levee > WSE
                        profiles_ground_wet = []
                        profiles_levee_dry = []
                        for _, res in xs_results.iterrows():
                            wsel_val = res.get('wsel', np.nan)
                            if not pd.isna(wsel_val):
                                if wsel_val > left_ground:
                                    profiles_ground_wet.append(res['profile'])
                                if wsel_val < left_levee_elev:
                                    profiles_levee_dry.append(res['profile'])

                        # If some profiles have ground wet but levee dry, report
                        profiles_affected = set(profiles_ground_wet) & set(profiles_levee_dry)
                        if profiles_affected and profiles_ground_wet and profiles_levee_dry:
                            msg = CheckMessage(
                                message_id="XS_LV_05L",
                                severity=Severity.INFO,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("XS_LV_05L",
                                    grelv=f"{left_ground:.2f}",
                                    assignednameMin=profiles_ground_wet[0],
                                    leveeelvl=f"{left_levee_elev:.2f}",
                                    assignednameMax=profiles_levee_dry[-1]),
                                help_text=get_help_text("XS_LV_05L")
                            )
                            messages.append(msg)
                            if "XS_LV_05L" not in xs_summary['issues']:
                                xs_summary['issues'].append("XS_LV_05L")

                    # For right levee
                    if right_levee_elev is not None and not pd.isna(right_levee_elev):
                        profiles_ground_wet = []
                        profiles_levee_dry = []
                        for _, res in xs_results.iterrows():
                            wsel_val = res.get('wsel', np.nan)
                            if not pd.isna(wsel_val):
                                if wsel_val > right_ground:
                                    profiles_ground_wet.append(res['profile'])
                                if wsel_val < right_levee_elev:
                                    profiles_levee_dry.append(res['profile'])

                        profiles_affected = set(profiles_ground_wet) & set(profiles_levee_dry)
                        if profiles_affected and profiles_ground_wet and profiles_levee_dry:
                            msg = CheckMessage(
                                message_id="XS_LV_05R",
                                severity=Severity.INFO,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("XS_LV_05R",
                                    grelv=f"{right_ground:.2f}",
                                    assignednameMin=profiles_ground_wet[0],
                                    leveeelvr=f"{right_levee_elev:.2f}",
                                    assignednameMax=profiles_levee_dry[-1]),
                                help_text=get_help_text("XS_LV_05R")
                            )
                            messages.append(msg)
                            if "XS_LV_05R" not in xs_summary['issues']:
                                xs_summary['issues'].append("XS_LV_05R")

            summary_data.append(xs_summary)

        # =====================================================================
        # XS_FR_01/02: Flow Regime Transition Checks
        # Check for transitions between subcritical and supercritical flow
        # =====================================================================
        if steady_results is not None and not steady_results.empty:
            regime_messages = RasCheck._check_flow_regime_transitions(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(regime_messages)

        # =====================================================================
        # XS_DC_01: Discharge Conservation Check
        # Check for flow changes within a reach
        # =====================================================================
        if steady_results is not None and not steady_results.empty:
            discharge_messages = RasCheck._check_discharge_conservation(
                steady_results, thresholds
            )
            messages.extend(discharge_messages)

        # =====================================================================
        # XS_JT_01/02: Junction Checks
        # Check for junctions where multiple reaches connect
        # =====================================================================
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                # Check for multiple rivers/reaches indicating potential junctions
                if 'Geometry/River Centerlines/Attributes' in hdf:
                    river_attrs = hdf['Geometry/River Centerlines/Attributes'][:]
                    num_reaches = len(river_attrs)

                    if num_reaches > 1:
                        # Multiple reaches exist - junctions likely
                        reach_names = []
                        for attr in river_attrs:
                            river_name = attr['Name'].decode().strip() if isinstance(attr['Name'], bytes) else str(attr['Name']).strip()
                            reach_names.append(river_name)

                        junction_name = f"{num_reaches} reaches"
                        msg = CheckMessage(
                            message_id="XS_JT_02",
                            severity=Severity.INFO,
                            check_type="XS",
                            river="",
                            reach="",
                            station="",
                            message=format_message("XS_JT_02", junction_name=junction_name),
                            help_text=get_help_text("XS_JT_02")
                        )
                        messages.append(msg)

                # Check for lateral structures (potential split flow indicators)
                if 'Geometry/Structures/Attributes' in hdf:
                    struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                    for i, attr in enumerate(struct_attrs):
                        struct_type = attr['Type'].decode().strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                        if 'Lateral' in struct_type:
                            river = attr['River'].decode().strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                            reach = attr['Reach'].decode().strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                            rs = attr['RS'].decode().strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                            msg = CheckMessage(
                                message_id="XS_SW_01",
                                severity=Severity.INFO,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=rs,
                                message=format_message("XS_SW_01", location=f"{river}/{reach} @ RS {rs}"),
                                help_text=get_help_text("XS_SW_01")
                            )
                            messages.append(msg)
        except Exception as e:
            logger.debug(f"Could not check junctions/split flow: {e}")

        # =====================================================================
        # NEW XS HYDRAULIC CHECKS - Adjacent Section Comparisons
        # =====================================================================
        if steady_results is not None and not steady_results.empty:
            # XS_AR_01: Flow Area Changes Between Adjacent Sections
            area_messages = RasCheck._check_flow_area_changes(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(area_messages)

            # XS_SL_01/02: Water Surface Slope Anomalies
            slope_messages = RasCheck._check_wse_slope(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(slope_messages)

            # XS_EGL_01: Energy Grade Line Reversals
            egl_messages = RasCheck._check_energy_grade_line(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(egl_messages)

            # XS_TW_02: Top Width Changes Between Adjacent Sections
            tw_messages = RasCheck._check_top_width_changes(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(tw_messages)

            # XS_EL_01/02: Energy Loss Checks
            eloss_messages = RasCheck._check_energy_loss(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(eloss_messages)

            # XS_HK_01 and XS_VD_01: Hydraulic Properties Checks
            hydprop_messages = RasCheck._check_hydraulic_properties(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(hydprop_messages)

        # =====================================================================
        # XS_LV_01/02/03: Levee Definition Checks
        # Check levee station and elevation against cross section geometry
        # =====================================================================
        levee_messages = RasCheck._check_levees(xs_gdf, thresholds)
        messages.extend(levee_messages)

        # =====================================================================
        # XS_CT_03/04: Contraction Coefficient Checks
        # XS_CW_01: Channel Width Ratio Checks
        # Check coefficient consistency and channel width ratios between sections
        # =====================================================================
        coef_width_messages = RasCheck._check_contraction_coefficients_and_widths(
            xs_gdf, geom_hdf, thresholds
        )
        messages.extend(coef_width_messages)

        results.messages = messages
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df['issues'] = summary_df['issues'].apply(lambda x: ', '.join(x) if x else '')
            results.xs_summary = summary_df

        return results

    @staticmethod
    @log_call
    def check_structures(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: List[str],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check bridge, culvert, and inline weir data.

        Validates:
        - Multiple structures at same location
        - Weir coefficient ranges
        - Structure type identification

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            profiles: List of profile names to check
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with structure check messages and summary DataFrame
        """
        from ..hdf.HdfStruc import HdfStruc

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        s_thresholds = thresholds.structures

        # Get structure data from geometry
        try:
            struct_gdf = HdfStruc.get_structures(geom_hdf)
        except Exception as e:
            logger.warning(f"Could not read structures: {e}")
            struct_gdf = None

        if struct_gdf is None or struct_gdf.empty:
            # No structures in model - not an error
            results.messages = []
            results.struct_summary = pd.DataFrame()
            return results

        # Build summary records
        summary_records = []

        for idx, struct in struct_gdf.iterrows():
            struct_type = struct.get('Type', '')
            river = struct.get('River', '')
            reach = struct.get('Reach', '')
            station = struct.get('RS', 0)
            name = struct.get('Node Name', struct.get('Groupname', ''))

            record = {
                'River': river,
                'Reach': reach,
                'RS': station,
                'Type': struct_type,
                'Name': name,
                'issues': []
            }

            # Check weir coefficient (for bridges and inline weirs)
            weir_coef = struct.get('Weir Coef', None)
            if weir_coef is not None and weir_coef > 0:
                record['Weir_Coef'] = weir_coef
                if weir_coef < s_thresholds.weir_coefficient_min or weir_coef > s_thresholds.weir_coefficient_max:
                    if 'Bridge' in struct_type:
                        msg_id = "BR_PW_03"
                    else:
                        msg_id = "IW_03"
                    msg = CheckMessage(
                        message_id=msg_id,
                        severity=Severity.WARNING,
                        check_type="STRUCT",
                        river=river,
                        reach=reach,
                        station=str(station),
                        message=format_message(msg_id, c=f"{weir_coef:.2f}"),
                        help_text=get_help_text(msg_id),
                        value=weir_coef,
                        threshold=f"{s_thresholds.weir_coefficient_min}-{s_thresholds.weir_coefficient_max}"
                    )
                    messages.append(msg)
                    record['issues'].append(msg_id)

            # Check upstream distance
            upstream_dist = struct.get('Upstream Distance', None)
            if upstream_dist is not None and upstream_dist > 0:
                record['US_Distance'] = upstream_dist

            summary_records.append(record)

        # Check for multiple structures at same location
        location_groups = {}
        for record in summary_records:
            key = (record['River'], record['Reach'], record['RS'])
            if key not in location_groups:
                location_groups[key] = []
            location_groups[key].append(record)

        for key, group in location_groups.items():
            if len(group) > 1:
                river, reach, station = key
                msg = CheckMessage(
                    message_id="ST_MS_01",
                    severity=Severity.INFO,
                    check_type="STRUCT",
                    river=river,
                    reach=reach,
                    station=str(station),
                    message=format_message("ST_MS_01", station=str(station)),
                    help_text=get_help_text("ST_MS_01")
                )
                messages.append(msg)

                # Mark all structures in group
                for record in group:
                    if "ST_MS_01" not in record['issues']:
                        record['issues'].append("ST_MS_01")

                # Check for mixed types
                types = set(r['Type'] for r in group if r.get('Type'))
                if len(types) > 1:
                    msg = CheckMessage(
                        message_id="ST_MS_02",
                        severity=Severity.INFO,
                        check_type="STRUCT",
                        river=river,
                        reach=reach,
                        station=str(station),
                        message=format_message("ST_MS_02", station=str(station)),
                        help_text=get_help_text("ST_MS_02")
                    )
                    messages.append(msg)
                    for record in group:
                        if "ST_MS_02" not in record['issues']:
                            record['issues'].append("ST_MS_02")

        # =====================================================================
        # Additional Structure Checks from HDF
        # =====================================================================
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' in hdf:
                    struct_attrs = hdf['Geometry/Structures/Attributes'][:]

                    for i, attr in enumerate(struct_attrs):
                        struct_type = attr['Type'].decode().strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                        river = attr['River'].decode().strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode().strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode().strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                        # Get section distances
                        us_dist = float(attr['Upstream Distance']) if 'Upstream Distance' in attr.dtype.names else 0

                        # ST_DT_03: Check for missing structure data table entries
                        missing_fields = []
                        if 'Bridge' in struct_type:
                            # Check for required bridge fields
                            required_bridge_fields = [
                                ('BR US Left Bank', 'upstream left abutment'),
                                ('BR US Right Bank', 'upstream right abutment'),
                                ('Low Chord', 'low chord elevation'),
                                ('High Chord', 'high chord elevation'),
                            ]
                            for field_name, field_desc in required_bridge_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        elif 'Culvert' in struct_type:
                            # Check for required culvert fields
                            required_culvert_fields = [
                                ('Rise', 'culvert rise/height'),
                                ('Span', 'culvert span/width'),
                                ('Length', 'culvert length'),
                            ]
                            for field_name, field_desc in required_culvert_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        elif 'Inline' in struct_type or 'Weir' in struct_type:
                            # Check for required inline weir fields
                            required_weir_fields = [
                                ('Weir Coef', 'weir coefficient'),
                            ]
                            for field_name, field_desc in required_weir_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        if missing_fields:
                            struct_name = attr['Node Name'].decode().strip() if 'Node Name' in attr.dtype.names and isinstance(attr['Node Name'], bytes) else f"{struct_type}_{station}"
                            msg = CheckMessage(
                                message_id="ST_DT_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("ST_DT_03",
                                                      name=struct_name,
                                                      missing_field=', '.join(missing_fields)),
                                help_text=get_help_text("ST_DT_03")
                            )
                            messages.append(msg)

                        # BR_SD_01/03: Bridge section distance checks
                        if 'Bridge' in struct_type:
                            # Upstream distance check - should be at least 1x expansion length (typically 100-300 ft)
                            min_us_dist = s_thresholds.bridge_upstream_distance_min if hasattr(s_thresholds, 'bridge_upstream_distance_min') else 50
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="BR_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("BR_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("BR_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                            # Check bridge contraction/expansion coefficients
                            br_contraction = float(attr['BR Contraction']) if 'BR Contraction' in attr.dtype.names else 0
                            br_expansion = float(attr['BR Expansion']) if 'BR Expansion' in attr.dtype.names else 0

                            # BR_LF_01: Unusual contraction coefficient
                            if br_contraction > 0 and (br_contraction < 0.1 or br_contraction > 0.6):
                                msg = CheckMessage(
                                    message_id="BR_LF_01",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Bridge contraction coefficient ({br_contraction:.2f}) outside typical range (0.1-0.6)",
                                    help_text="Typical bridge contraction coefficients range from 0.1 to 0.6."
                                )
                                messages.append(msg)

                            # BR_LF_02: Unusual expansion coefficient
                            if br_expansion > 0 and (br_expansion < 0.3 or br_expansion > 0.8):
                                msg = CheckMessage(
                                    message_id="BR_LF_02",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Bridge expansion coefficient ({br_expansion:.2f}) outside typical range (0.3-0.8)",
                                    help_text="Typical bridge expansion coefficients range from 0.3 to 0.8."
                                )
                                messages.append(msg)

                            # BR_LF_03: Bridge low flow coefficient check
                            # Check for low flow coefficient (typically used in energy-based methods)
                            br_low_flow_coef = 0.0
                            for coef_name in ['Low Flow Coef', 'LF Coef', 'Yarnell Coef', 'Pier Shape']:
                                if coef_name in attr.dtype.names:
                                    br_low_flow_coef = float(attr[coef_name])
                                    break

                            if br_low_flow_coef > 0:
                                # Typical range depends on flow class and method
                                # Class A (Energy): Yarnell K typically 0.9-1.05
                                # Pier drag: typically 1.0-2.5
                                min_coef = 0.5
                                max_coef = 2.5
                                if br_low_flow_coef < min_coef or br_low_flow_coef > max_coef:
                                    msg = CheckMessage(
                                        message_id="BR_LF_03",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("BR_LF_03",
                                                              coef=br_low_flow_coef,
                                                              min=min_coef,
                                                              max=max_coef),
                                        help_text=get_help_text("BR_LF_03"),
                                        value=br_low_flow_coef
                                    )
                                    messages.append(msg)

                        # CU_SD_01: Culvert section distance checks
                        elif 'Culvert' in struct_type:
                            min_us_dist = s_thresholds.culvert_upstream_distance_min if hasattr(s_thresholds, 'culvert_upstream_distance_min') else 30
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="CU_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("CU_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("CU_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                        # IW_SD_01: Inline weir section distance checks
                        elif 'Inline' in struct_type or 'Weir' in struct_type:
                            min_us_dist = 20
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="IW_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("IW_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("IW_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                        # ST_IF_01/02: Structure ineffective flow checks
                        if 'Bridge' in struct_type:
                            # Check for upstream ineffective flow
                            us_ineff_left_sta = float(attr['US Ineff Left Sta']) if 'US Ineff Left Sta' in attr.dtype.names else 0
                            us_ineff_right_sta = float(attr['US Ineff Right Sta']) if 'US Ineff Right Sta' in attr.dtype.names else 0
                            ds_ineff_left_sta = float(attr['DS Ineff Left Sta']) if 'DS Ineff Left Sta' in attr.dtype.names else 0
                            ds_ineff_right_sta = float(attr['DS Ineff Right Sta']) if 'DS Ineff Right Sta' in attr.dtype.names else 0

                            # If no ineffective defined (both zeros), warn
                            if us_ineff_left_sta == 0 and us_ineff_right_sta == 0:
                                msg = CheckMessage(
                                    message_id="ST_IF_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("ST_IF_01"),
                                    help_text=get_help_text("ST_IF_01")
                                )
                                messages.append(msg)

                            if ds_ineff_left_sta == 0 and ds_ineff_right_sta == 0:
                                msg = CheckMessage(
                                    message_id="ST_IF_02",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("ST_IF_02"),
                                    help_text=get_help_text("ST_IF_02")
                                )
                                messages.append(msg)

                            # ST_IF_03L/R: Ineffective should extend to abutment
                            br_us_left_bank = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                            br_us_right_bank = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0

                            if us_ineff_left_sta > 0 and br_us_left_bank > 0:
                                if us_ineff_right_sta < br_us_left_bank - 5:  # 5 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_IF_03L",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_IF_03L"),
                                        help_text=get_help_text("ST_IF_03L")
                                    )
                                    messages.append(msg)

                            if us_ineff_right_sta > 0 and br_us_right_bank > 0:
                                if us_ineff_left_sta > br_us_right_bank + 5:  # 5 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_IF_03R",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_IF_03R"),
                                        help_text=get_help_text("ST_IF_03R")
                                    )
                                    messages.append(msg)

                        # ST_GE_01L/R: Bank station alignment checks
                        if 'Bridge' in struct_type:
                            br_us_left_bank = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                            br_us_right_bank = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0
                            xs_us_left_bank = float(attr['XS US Left Bank']) if 'XS US Left Bank' in attr.dtype.names else 0
                            xs_us_right_bank = float(attr['XS US Right Bank']) if 'XS US Right Bank' in attr.dtype.names else 0

                            # Check if bridge bank stations are significantly different from XS bank stations
                            if br_us_left_bank > 0 and xs_us_left_bank > 0:
                                if abs(br_us_left_bank - xs_us_left_bank) > 50:  # 50 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_GE_01L",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_GE_01L"),
                                        help_text=get_help_text("ST_GE_01L")
                                    )
                                    messages.append(msg)

                            if br_us_right_bank > 0 and xs_us_right_bank > 0:
                                if abs(br_us_right_bank - xs_us_right_bank) > 50:
                                    msg = CheckMessage(
                                        message_id="ST_GE_01R",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_GE_01R"),
                                        help_text=get_help_text("ST_GE_01R")
                                    )
                                    messages.append(msg)

                        # Weir submergence check
                        weir_max_sub = float(attr['Weir Max Submergence']) if 'Weir Max Submergence' in attr.dtype.names else 0
                        if weir_max_sub > 0 and weir_max_sub < 0.8:
                            msg = CheckMessage(
                                message_id="BR_PW_04",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("BR_PW_04", sub=f"{weir_max_sub:.2f}"),
                                help_text=get_help_text("BR_PW_04")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not perform additional structure checks: {e}")

        # =====================================================================
        # Additional Structure Checks Using Helper Methods
        # =====================================================================

        # ST_DT_01/02: Structure distance checks
        distance_messages = RasCheck._check_structure_distances(geom_hdf, thresholds)
        messages.extend(distance_messages)

        # ST_GE_02L/R, ST_GE_03: Structure geometry alignment checks
        geometry_messages = RasCheck._check_structure_geometry_alignment(geom_hdf, thresholds)
        messages.extend(geometry_messages)

        # ST_IF_04L/R: Section 3 ineffective flow checks
        ineff_section3_messages = RasCheck._check_structure_ineffective_section3(geom_hdf, thresholds)
        messages.extend(ineff_section3_messages)

        # IW_TF_*: Inline weir flow type checks
        inline_weir_messages = RasCheck._check_inline_weirs(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(inline_weir_messages)

        # CV_TF_*, CV_LF_*, CV_PF_*, CV_PW_*, CV_CF_*: Culvert flow type and coefficient checks
        culvert_messages = RasCheck._check_culverts(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(culvert_messages)

        # BR_TF_*, BR_PF_*, BR_PW_*: Bridge flow type and pressure/weir checks
        bridge_flow_messages = RasCheck._check_bridge_flow_types(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(bridge_flow_messages)

        # ST_GD_*: Structure ground data validation checks
        ground_messages = RasCheck._check_structure_ground(geom_hdf, thresholds)
        messages.extend(ground_messages)

        # Convert issues lists to strings for DataFrame
        for record in summary_records:
            record['issues'] = ', '.join(record['issues'])

        results.messages = messages
        results.struct_summary = pd.DataFrame(summary_records)
        return results

    @staticmethod
    @log_call
    def check_floodways(
        plan_hdf: Path,
        geom_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        surcharge_limit: float = 1.0,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check floodway encroachment analysis.

        Validates:
        - Surcharge values against allowable limit
        - Discharge matching between base and floodway profiles
        - Negative surcharge (WSE decrease) detection

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            base_profile: Name of base (1% annual chance) profile
            floodway_profile: Name of floodway profile
            surcharge_limit: Maximum allowable surcharge in feet (default 1.0)
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with floodway check messages and summary DataFrame
        """
        from ..hdf.HdfResultsPlan import HdfResultsPlan

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        # Get steady flow results
        try:
            steady_results = HdfResultsPlan.get_steady_results(plan_hdf)
        except Exception as e:
            logger.warning(f"Could not read steady results: {e}")
            steady_results = None

        if steady_results is None or steady_results.empty:
            results.messages = []
            results.floodway_summary = pd.DataFrame()
            return results

        # Filter to base and floodway profiles
        base_data = steady_results[steady_results['profile'] == base_profile].copy()
        fw_data = steady_results[steady_results['profile'] == floodway_profile].copy()

        if base_data.empty:
            logger.warning(f"Base profile '{base_profile}' not found in results")
            results.messages = []
            results.floodway_summary = pd.DataFrame()
            return results

        if fw_data.empty:
            logger.warning(f"Floodway profile '{floodway_profile}' not found in results")
            results.messages = []
            results.floodway_summary = pd.DataFrame()
            return results

        # Build summary comparing profiles
        summary_records = []

        for _, base_row in base_data.iterrows():
            river = base_row.get('river', '')
            reach = base_row.get('reach', '')
            node_id = base_row.get('node_id', '')
            base_wsel = base_row.get('wsel', np.nan)
            base_q = base_row.get('flow', np.nan)

            # Find matching floodway data
            fw_match = fw_data[
                (fw_data['river'] == river) &
                (fw_data['reach'] == reach) &
                (fw_data['node_id'] == node_id)
            ]

            if fw_match.empty:
                continue

            fw_row = fw_match.iloc[0]
            fw_wsel = fw_row.get('wsel', np.nan)
            fw_q = fw_row.get('flow', np.nan)

            # Calculate surcharge
            surcharge = fw_wsel - base_wsel if not (pd.isna(base_wsel) or pd.isna(fw_wsel)) else np.nan

            record = {
                'River': river,
                'Reach': reach,
                'RS': node_id,
                'Base_WSEL': base_wsel,
                'FW_WSEL': fw_wsel,
                'Surcharge': surcharge,
                'Base_Q': base_q,
                'FW_Q': fw_q,
                'issues': []
            }

            # FW_SC_01: Surcharge exceeds limit
            if not pd.isna(surcharge) and surcharge > surcharge_limit:
                msg = CheckMessage(
                    message_id="FW_SC_01",
                    severity=Severity.ERROR,
                    check_type="FLOODWAY",
                    river=river,
                    reach=reach,
                    station=str(node_id),
                    message=format_message("FW_SC_01",
                        sc=f"{surcharge:.2f}",
                        max=f"{surcharge_limit:.2f}"),
                    help_text=get_help_text("FW_SC_01"),
                    value=surcharge,
                    threshold=surcharge_limit
                )
                messages.append(msg)
                record['issues'].append("FW_SC_01")

            # FW_SC_02: Negative surcharge (WSE decreased)
            if not pd.isna(surcharge) and surcharge < -0.01:
                msg = CheckMessage(
                    message_id="FW_SC_02",
                    severity=Severity.WARNING,
                    check_type="FLOODWAY",
                    river=river,
                    reach=reach,
                    station=str(node_id),
                    message=format_message("FW_SC_02", sc=f"{surcharge:.2f}"),
                    help_text=get_help_text("FW_SC_02"),
                    value=surcharge
                )
                messages.append(msg)
                record['issues'].append("FW_SC_02")

            # FW_SC_03: Zero surcharge (exact match)
            if not pd.isna(surcharge) and abs(surcharge) < 0.005:
                msg = CheckMessage(
                    message_id="FW_SC_03",
                    severity=Severity.INFO,
                    check_type="FLOODWAY",
                    river=river,
                    reach=reach,
                    station=str(node_id),
                    message=get_message_template("FW_SC_03"),
                    help_text=get_help_text("FW_SC_03"),
                    value=surcharge
                )
                messages.append(msg)
                record['issues'].append("FW_SC_03")

            # FW_SC_04: Surcharge within 0.01 ft of limit
            if not pd.isna(surcharge) and surcharge > 0 and abs(surcharge - surcharge_limit) < 0.01:
                msg = CheckMessage(
                    message_id="FW_SC_04",
                    severity=Severity.INFO,
                    check_type="FLOODWAY",
                    river=river,
                    reach=reach,
                    station=str(node_id),
                    message=format_message("FW_SC_04", sc=f"{surcharge:.3f}"),
                    help_text=get_help_text("FW_SC_04"),
                    value=surcharge,
                    threshold=surcharge_limit
                )
                messages.append(msg)
                record['issues'].append("FW_SC_04")

            # FW_Q_01: Discharge mismatch
            if not (pd.isna(base_q) or pd.isna(fw_q)):
                q_diff = abs(fw_q - base_q)
                q_pct = (q_diff / base_q * 100) if base_q > 0 else 0
                if q_pct > 1.0:
                    msg = CheckMessage(
                        message_id="FW_Q_01",
                        severity=Severity.WARNING,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=str(node_id),
                        message=format_message("FW_Q_01",
                            qfw=f"{fw_q:.0f}",
                            qbf=f"{base_q:.0f}"),
                        help_text=get_help_text("FW_Q_01"),
                        value=q_pct
                    )
                    messages.append(msg)
                    record['issues'].append("FW_Q_01")

                # FW_Q_02: Floodway Q exceeds base flood by more than 1%
                if fw_q > base_q * 1.01:
                    msg = CheckMessage(
                        message_id="FW_Q_02",
                        severity=Severity.WARNING,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=str(node_id),
                        message=format_message("FW_Q_02", station=str(node_id)),
                        help_text=get_help_text("FW_Q_02"),
                        value=q_pct
                    )
                    messages.append(msg)
                    record['issues'].append("FW_Q_02")

            # Convert issues to string
            record['issues'] = ', '.join(record['issues'])
            summary_records.append(record)

        # =====================================================================
        # Additional Floodway Checks from HDF
        # =====================================================================
        encroachment_msgs = RasCheck._check_encroachment_data(
            plan_hdf, geom_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(encroachment_msgs)

        # Check for discharge changes within floodway reach
        discharge_msgs = RasCheck._check_floodway_discharge_conservation(
            steady_results, floodway_profile
        )
        messages.extend(discharge_msgs)

        # ST_IF_05: Check for permanent ineffective flow at structures (problematic in floodway)
        perm_ineff_msgs = RasCheck._check_structure_permanent_ineffective(geom_hdf, is_floodway=True)
        messages.extend(perm_ineff_msgs)

        # FW_EM_*: Check encroachment methods
        encr_method_msgs = RasCheck._check_floodway_encroachment_methods(
            plan_hdf, geom_hdf, floodway_profile, thresholds
        )
        messages.extend(encr_method_msgs)

        # FW_BC_*: Check boundary conditions
        bc_msgs = RasCheck._check_floodway_boundary_conditions(
            plan_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(bc_msgs)

        # FW_SW_*: Check starting WSE (includes method-specific variants)
        sw_msgs = RasCheck._check_floodway_starting_wse(
            plan_hdf, steady_results, geom_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(sw_msgs)

        # FW_LW_*: Check lateral weirs
        lw_msgs = RasCheck._check_floodway_lateral_weirs(
            plan_hdf, geom_hdf, floodway_profile, thresholds
        )
        messages.extend(lw_msgs)

        results.messages = messages
        results.floodway_summary = pd.DataFrame(summary_records)
        return results

    @staticmethod
    @log_call
    def check_profiles(
        plan_hdf: Path,
        profiles: List[str],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check multiple profile consistency.

        Validates:
        - MP_WS_01/02: Water surface elevation ordering between profiles
        - MP_Q_01: Discharge ordering between profiles
        - MP_TW_01: Top width ordering between profiles
        - PF_TW_01: Top width significant decrease (>20%) between profiles
        - PF_VEL_01: Velocity ordering between profiles
        - PF_EG_01: Energy grade line ordering between profiles

        Args:
            plan_hdf: Path to plan HDF file
            profiles: List of profile names to compare (ordered by frequency,
                      from lowest/most severe to highest/least severe)
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with profiles check messages and summary DataFrame

        Notes:
            - Profile ordering assumes profiles[0] is the most severe (e.g., 100yr)
              and profiles[-1] is the least severe (e.g., 10yr)
            - Lower frequency (more severe) events should have:
              - Higher WSE
              - Higher discharge
              - Wider top width
              - Higher velocity (typically)
              - Higher energy grade elevation
        """
        from ..hdf.HdfResultsPlan import HdfResultsPlan

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        p_thresholds = thresholds.profiles

        if len(profiles) < 2:
            # Need at least 2 profiles to compare
            results.messages = messages
            results.profiles_summary = pd.DataFrame()
            return results

        # Get steady results
        try:
            plan_hdf = Path(plan_hdf)
            steady_results = HdfResultsPlan.get_steady_results(plan_hdf)
        except Exception as e:
            logger.error(f"Failed to read steady results: {e}")
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Failed to read steady results for profiles check: {e}"
            )
            results.messages.append(msg)
            return results

        if steady_results.empty:
            results.messages = messages
            results.profiles_summary = pd.DataFrame()
            return results

        # Filter to only requested profiles
        steady_results = steady_results[steady_results['profile'].isin(profiles)]

        # Get unique cross sections
        xs_list = steady_results[['river', 'reach', 'node_id']].drop_duplicates()

        summary_data = []

        for _, xs_row in xs_list.iterrows():
            river = xs_row['river']
            reach = xs_row['reach']
            station = xs_row['node_id']

            # Get results for this XS across all profiles
            xs_results = steady_results[
                (steady_results['river'] == river) &
                (steady_results['reach'] == reach) &
                (steady_results['node_id'] == station)
            ].set_index('profile')

            xs_summary = {
                'River': river,
                'Reach': reach,
                'RS': station,
                'issues': []
            }

            # Compare consecutive profiles
            for i in range(len(profiles) - 1):
                profile_low = profiles[i]      # Lower frequency (more severe)
                profile_high = profiles[i + 1]  # Higher frequency (less severe)

                if profile_low not in xs_results.index or profile_high not in xs_results.index:
                    continue

                # Get values
                wse_low = xs_results.loc[profile_low, 'wsel']
                wse_high = xs_results.loc[profile_high, 'wsel']
                flow_low = xs_results.loc[profile_low, 'flow']
                flow_high = xs_results.loc[profile_high, 'flow']
                tw_low = xs_results.loc[profile_low, 'top_width']
                tw_high = xs_results.loc[profile_high, 'top_width']

                # MP_WS_01: WSE ordering check (lower frequency should have higher WSE)
                if not pd.isna(wse_low) and not pd.isna(wse_high):
                    wse_diff = wse_low - wse_high
                    if wse_diff < -p_thresholds.wse_order_tolerance_ft:
                        # Higher frequency profile has higher WSE - unusual
                        msg = CheckMessage(
                            message_id="MP_WS_01",
                            severity=Severity.WARNING,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("MP_WS_01",
                                profile_low=profile_low,
                                profile_high=profile_high,
                                station=station),
                            help_text=get_help_text("MP_WS_01"),
                            value=wse_diff
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("MP_WS_01")

                    # MP_WS_02: WSE nearly equal
                    elif abs(wse_diff) < p_thresholds.wse_order_tolerance_ft:
                        msg = CheckMessage(
                            message_id="MP_WS_02",
                            severity=Severity.INFO,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("MP_WS_02",
                                profile_low=profile_low,
                                profile_high=profile_high,
                                station=station),
                            help_text=get_help_text("MP_WS_02"),
                            value=wse_diff
                        )
                        messages.append(msg)

                # MP_Q_01: Discharge ordering check
                if not pd.isna(flow_low) and not pd.isna(flow_high):
                    if flow_low < flow_high * 0.99:  # Allow 1% tolerance
                        msg = CheckMessage(
                            message_id="MP_Q_01",
                            severity=Severity.WARNING,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("MP_Q_01",
                                profile_low=profile_low,
                                profile_high=profile_high,
                                station=station),
                            help_text=get_help_text("MP_Q_01"),
                            value=flow_low - flow_high
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("MP_Q_01")

                # MP_TW_01: Top width ordering check
                if not pd.isna(tw_low) and not pd.isna(tw_high):
                    if tw_low < tw_high * 0.95:  # Allow 5% tolerance
                        msg = CheckMessage(
                            message_id="MP_TW_01",
                            severity=Severity.INFO,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("MP_TW_01",
                                profile_low=profile_low,
                                profile_high=profile_high,
                                station=station),
                            help_text=get_help_text("MP_TW_01"),
                            value=tw_low - tw_high
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("MP_TW_01")

                # PF_TW_01: Top width significant decrease check (>20%)
                if not pd.isna(tw_low) and not pd.isna(tw_high) and tw_high > 0:
                    tw_decrease_pct = (tw_high - tw_low) / tw_high * 100
                    if tw_decrease_pct > 20.0:  # More than 20% decrease
                        msg = CheckMessage(
                            message_id="PF_TW_01",
                            severity=Severity.WARNING,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("PF_TW_01",
                                pct=tw_decrease_pct,
                                profile_low=profile_low,
                                tw_low=tw_low,
                                profile_high=profile_high,
                                tw_high=tw_high,
                                station=station),
                            help_text=get_help_text("PF_TW_01"),
                            value=tw_decrease_pct
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("PF_TW_01")

                # Get velocity and energy data if available
                vel_low = xs_results.loc[profile_low, 'velocity'] if 'velocity' in xs_results.columns else np.nan
                vel_high = xs_results.loc[profile_high, 'velocity'] if 'velocity' in xs_results.columns else np.nan
                eg_low = xs_results.loc[profile_low, 'energy'] if 'energy' in xs_results.columns else np.nan
                eg_high = xs_results.loc[profile_high, 'energy'] if 'energy' in xs_results.columns else np.nan

                # PF_VEL_01: Velocity ordering check
                # Lower frequency (more severe) events should typically have higher velocity
                if not pd.isna(vel_low) and not pd.isna(vel_high):
                    if vel_low < vel_high * 0.95:  # Lower frequency has lower velocity (5% tolerance)
                        msg = CheckMessage(
                            message_id="PF_VEL_01",
                            severity=Severity.WARNING,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("PF_VEL_01",
                                profile_low=profile_low,
                                vel_low=vel_low,
                                profile_high=profile_high,
                                vel_high=vel_high,
                                station=station),
                            help_text=get_help_text("PF_VEL_01"),
                            value=vel_low - vel_high
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("PF_VEL_01")

                # PF_EG_01: Energy grade ordering check
                # Lower frequency (more severe) events should have higher energy grade
                if not pd.isna(eg_low) and not pd.isna(eg_high):
                    if eg_low < eg_high - p_thresholds.wse_order_tolerance_ft:
                        msg = CheckMessage(
                            message_id="PF_EG_01",
                            severity=Severity.WARNING,
                            check_type="PROFILES",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("PF_EG_01",
                                profile_low=profile_low,
                                eg_low=eg_low,
                                profile_high=profile_high,
                                eg_high=eg_high,
                                station=station),
                            help_text=get_help_text("PF_EG_01"),
                            value=eg_low - eg_high
                        )
                        messages.append(msg)
                        xs_summary['issues'].append("PF_EG_01")

            summary_data.append(xs_summary)

        results.messages = messages
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df['issues'] = summary_df['issues'].apply(lambda x: ', '.join(x) if x else '')
            results.profiles_summary = summary_df

        return results

    # =========================================================================
    # Flow Regime Transition Check Methods
    # =========================================================================

    @staticmethod
    def _check_flow_regime_transitions(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for flow regime transitions between adjacent cross sections.

        Flags:
        - XS_FR_01: Subcritical to supercritical transition (Froude < 1 to > 1)
        - XS_FR_02: Supercritical to subcritical transition (hydraulic jump)

        Args:
            xs_gdf: Cross section GeoDataFrame
            steady_results: Steady flow results DataFrame with Froude numbers
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for flow regime transition issues
        """
        messages = []

        if steady_results.empty or 'froude' not in steady_results.columns:
            return messages

        # Get unique profiles
        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            # Group by River and Reach
            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                # Sort by station (descending = upstream to downstream)
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_froude = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    froude = row.get('froude', np.nan)

                    if prev_row is not None and not pd.isna(froude) and not pd.isna(prev_froude):
                        prev_station = str(prev_row.get('node_id', ''))

                        # Check for subcritical to supercritical (XS_FR_01)
                        if prev_froude < 1.0 and froude >= 1.0:
                            msg = CheckMessage(
                                message_id="XS_FR_01",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Flow regime transition: subcritical to supercritical between RS {prev_station} (Fr={prev_froude:.2f}) and RS {station} (Fr={froude:.2f}) for {profile}",
                                help_text=get_help_text("XS_FR_01") if get_help_text("XS_FR_01") else "Subcritical to supercritical flow transition detected.",
                                value=froude
                            )
                            messages.append(msg)

                        # Check for supercritical to subcritical (XS_FR_02) - hydraulic jump
                        if prev_froude >= 1.0 and froude < 1.0:
                            msg = CheckMessage(
                                message_id="XS_FR_02",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Flow regime transition: supercritical to subcritical (hydraulic jump) between RS {prev_station} (Fr={prev_froude:.2f}) and RS {station} (Fr={froude:.2f}) for {profile}",
                                help_text=get_help_text("XS_FR_02") if get_help_text("XS_FR_02") else "Supercritical to subcritical flow transition (hydraulic jump) detected.",
                                value=froude
                            )
                            messages.append(msg)

                    prev_row = row
                    prev_froude = froude

        return messages

    @staticmethod
    def _check_discharge_conservation(
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for discharge conservation within reaches.

        Flags when flow changes significantly between adjacent cross sections
        within the same reach (without a junction or lateral inflow).

        Args:
            steady_results: Steady flow results DataFrame with flow column
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for discharge conservation issues
        """
        messages = []

        if steady_results.empty or 'flow' not in steady_results.columns:
            return messages

        # Tolerance for flow change (5% or 100 cfs, whichever is greater)
        flow_pct_tolerance = 0.05
        flow_abs_tolerance = 100.0

        # Get unique profiles
        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            # Group by River and Reach
            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                # Sort by station (descending = upstream to downstream)
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_flow = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    flow = row.get('flow', np.nan)

                    if prev_row is not None and not pd.isna(flow) and not pd.isna(prev_flow):
                        prev_station = str(prev_row.get('node_id', ''))

                        # Check for flow change
                        flow_diff = abs(flow - prev_flow)
                        flow_pct = flow_diff / prev_flow if prev_flow > 0 else 0

                        # Flag if flow changes by more than tolerance
                        if flow_diff > flow_abs_tolerance and flow_pct > flow_pct_tolerance:
                            msg = CheckMessage(
                                message_id="XS_DC_01",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Discharge change ({flow_diff:.0f} cfs, {flow_pct*100:.1f}%) between RS {prev_station} ({prev_flow:.0f} cfs) and RS {station} ({flow:.0f} cfs) for {profile}",
                                help_text=get_help_text("XS_DC_01") if get_help_text("XS_DC_01") else "Unexpected discharge change within reach. Verify no unmmodeled inflows or diversions.",
                                value=flow_diff
                            )
                            messages.append(msg)

                    prev_row = row
                    prev_flow = flow

        return messages

    # =========================================================================
    # NEW XS Hydraulic Check Methods
    # =========================================================================

    @staticmethod
    def _check_flow_area_changes(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for large flow area changes between adjacent cross sections.

        Flags:
        - XS_AR_01: Flow area changes by more than 50% between adjacent sections
        """
        messages = []

        if steady_results.empty or 'area' not in steady_results.columns:
            return messages

        area_pct_threshold = 0.50
        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_area = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    area = row.get('area', np.nan)

                    if prev_row is not None and not pd.isna(area) and not pd.isna(prev_area):
                        prev_station = str(prev_row.get('node_id', ''))

                        if prev_area > 0:
                            area_pct_change = abs(area - prev_area) / prev_area

                            if area_pct_change > area_pct_threshold:
                                msg = CheckMessage(
                                    message_id="XS_AR_01",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Large flow area change ({area_pct_change*100:.0f}%) between RS {prev_station} ({prev_area:.0f} sq ft) and RS {station} ({area:.0f} sq ft) for {profile}",
                                    help_text=get_help_text("XS_AR_01"),
                                    value=area_pct_change * 100
                                )
                                messages.append(msg)

                    prev_row = row
                    prev_area = area

        return messages

    @staticmethod
    def _check_wse_slope(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for water surface slope anomalies between adjacent cross sections.

        Flags:
        - XS_SL_01: Negative water surface slope (WSE increases downstream)
        - XS_SL_02: Very steep water surface slope (> 0.02 ft/ft)
        """
        messages = []

        if steady_results.empty or 'wsel' not in steady_results.columns:
            return messages

        xs_lengths = {}
        if 'RS' in xs_gdf.columns and 'Len Channel' in xs_gdf.columns:
            for _, xs in xs_gdf.iterrows():
                river = xs.get('River', '')
                reach = xs.get('Reach', '')
                rs = str(xs.get('RS', ''))
                length = xs.get('Len Channel', np.nan)
                if not pd.isna(length):
                    xs_lengths[(river, reach, rs)] = length

        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_wsel = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    wsel = row.get('wsel', np.nan)

                    if prev_row is not None and not pd.isna(wsel) and not pd.isna(prev_wsel):
                        prev_station = str(prev_row.get('node_id', ''))

                        reach_length = xs_lengths.get((river, reach, station), 0)
                        if reach_length <= 0:
                            try:
                                reach_length = abs(float(prev_station) - float(station))
                            except ValueError:
                                reach_length = 100

                        if reach_length > 0:
                            wse_slope = (prev_wsel - wsel) / reach_length

                            if wse_slope < -0.0001:
                                msg = CheckMessage(
                                    message_id="XS_SL_01",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Water surface slope anomaly ({wse_slope:.6f}) between RS {prev_station} and RS {station} for {profile}",
                                    help_text=get_help_text("XS_SL_01"),
                                    value=wse_slope
                                )
                                messages.append(msg)

                            elif wse_slope > 0.02:
                                msg = CheckMessage(
                                    message_id="XS_SL_02",
                                    severity=Severity.INFO,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Steep water surface slope ({wse_slope:.4f} ft/ft) between RS {prev_station} and RS {station} for {profile}",
                                    help_text=get_help_text("XS_SL_02"),
                                    value=wse_slope
                                )
                                messages.append(msg)

                    prev_row = row
                    prev_wsel = wsel

        return messages

    @staticmethod
    def _check_energy_grade_line(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for energy grade line reversals between adjacent cross sections.

        Flags:
        - XS_EGL_01: EGL increases in downstream direction (energy conservation violation)
        """
        messages = []

        egl_col = None
        for col in ['egl', 'EGL', 'energy_grade_line', 'eg']:
            if col in steady_results.columns:
                egl_col = col
                break

        if steady_results.empty or egl_col is None:
            return messages

        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_egl = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    egl = row.get(egl_col, np.nan)
                    froude = row.get('froude', np.nan)

                    if prev_row is not None and not pd.isna(egl) and not pd.isna(prev_egl):
                        prev_station = str(prev_row.get('node_id', ''))

                        if pd.isna(froude) or froude < 1.0:
                            if egl > prev_egl + 0.01:
                                msg = CheckMessage(
                                    message_id="XS_EGL_01",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Energy grade line reversal: EGL at RS {station} ({egl:.2f} ft) exceeds RS {prev_station} ({prev_egl:.2f} ft) for {profile}",
                                    help_text=get_help_text("XS_EGL_01"),
                                    value=egl - prev_egl
                                )
                                messages.append(msg)

                    prev_row = row
                    prev_egl = egl

        return messages

    @staticmethod
    def _check_top_width_changes(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for large top width changes between adjacent cross sections.

        Flags:
        - XS_TW_02: Top width changes by more than 100% between adjacent sections
        """
        messages = []

        tw_col = None
        for col in ['top_width', 'topwidth', 'TopWidth', 'tw']:
            if col in steady_results.columns:
                tw_col = col
                break

        if steady_results.empty or tw_col is None:
            return messages

        tw_pct_threshold = 1.0
        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_tw = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    tw = row.get(tw_col, np.nan)

                    if prev_row is not None and not pd.isna(tw) and not pd.isna(prev_tw):
                        prev_station = str(prev_row.get('node_id', ''))

                        if prev_tw > 0:
                            tw_pct_change = abs(tw - prev_tw) / prev_tw

                            if tw_pct_change > tw_pct_threshold:
                                msg = CheckMessage(
                                    message_id="XS_TW_02",
                                    severity=Severity.INFO,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Large top width change ({tw_pct_change*100:.0f}%) between RS {prev_station} ({prev_tw:.0f} ft) and RS {station} ({tw:.0f} ft) for {profile}",
                                    help_text=get_help_text("XS_TW_02"),
                                    value=tw_pct_change * 100
                                )
                                messages.append(msg)

                    prev_row = row
                    prev_tw = tw

        return messages

    @staticmethod
    def _check_energy_loss(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for energy loss anomalies between adjacent cross sections.

        Flags:
        - XS_EL_01: Very low energy loss (<0.01 ft) between adjacent sections
        - XS_EL_02: Very high energy loss (>5 ft) between adjacent sections
        """
        messages = []

        egl_col = None
        for col in ['egl', 'EGL', 'energy_grade_line', 'eg']:
            if col in steady_results.columns:
                egl_col = col
                break

        if steady_results.empty or egl_col is None:
            return messages

        low_loss_threshold = 0.01
        high_loss_threshold = 5.0
        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for (river, reach), group in profile_results.groupby(['river', 'reach']):
                group_sorted = group.sort_values('node_id', ascending=False)

                prev_row = None
                prev_egl = None
                for idx, row in group_sorted.iterrows():
                    station = str(row.get('node_id', ''))
                    egl = row.get(egl_col, np.nan)

                    if prev_row is not None and not pd.isna(egl) and not pd.isna(prev_egl):
                        prev_station = str(prev_row.get('node_id', ''))

                        energy_loss = prev_egl - egl

                        if 0 <= energy_loss < low_loss_threshold:
                            msg = CheckMessage(
                                message_id="XS_EL_01",
                                severity=Severity.INFO,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Low energy loss ({energy_loss:.3f} ft) between RS {prev_station} and RS {station} for {profile}",
                                help_text=get_help_text("XS_EL_01"),
                                value=energy_loss
                            )
                            messages.append(msg)

                        elif energy_loss > high_loss_threshold:
                            msg = CheckMessage(
                                message_id="XS_EL_02",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"High energy loss ({energy_loss:.2f} ft) between RS {prev_station} and RS {station} for {profile}",
                                help_text=get_help_text("XS_EL_02"),
                                value=energy_loss
                            )
                            messages.append(msg)

                    prev_row = row
                    prev_egl = egl

        return messages

    @staticmethod
    def _check_hydraulic_properties(
        xs_gdf: pd.DataFrame,
        steady_results: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for hydraulic property anomalies at cross sections.

        Flags:
        - XS_HK_01: Hydraulic radius outside expected range
        - XS_VD_01: Velocity distribution coefficient (alpha) outside typical range
        """
        messages = []

        if steady_results.empty:
            return messages

        hr_min = 0.1
        hr_max = 50.0
        alpha_min = 1.0
        alpha_max = 2.5

        profiles = steady_results['profile'].unique()

        for profile in profiles:
            profile_results = steady_results[steady_results['profile'] == profile]

            for idx, row in profile_results.iterrows():
                river = row.get('river', '')
                reach = row.get('reach', '')
                station = str(row.get('node_id', ''))

                area = row.get('area', np.nan)
                wp = row.get('wetted_perimeter', row.get('wp', np.nan))

                if not pd.isna(area) and not pd.isna(wp) and wp > 0:
                    hr = area / wp

                    if hr < hr_min or hr > hr_max:
                        msg = CheckMessage(
                            message_id="XS_HK_01",
                            severity=Severity.INFO,
                            check_type="XS",
                            river=river,
                            reach=reach,
                            station=station,
                            message=f"Hydraulic radius ({hr:.2f} ft) out of expected range at RS {station} for {profile}",
                            help_text=get_help_text("XS_HK_01"),
                            value=hr
                        )
                        messages.append(msg)

                alpha = row.get('alpha', row.get('velocity_coef', np.nan))

                if not pd.isna(alpha):
                    if alpha < alpha_min or alpha > alpha_max:
                        msg = CheckMessage(
                            message_id="XS_VD_01",
                            severity=Severity.INFO,
                            check_type="XS",
                            river=river,
                            reach=reach,
                            station=station,
                            message=f"Velocity distribution coefficient (alpha={alpha:.2f}) outside typical range at RS {station} for {profile}",
                            help_text=get_help_text("XS_VD_01"),
                            value=alpha
                        )
                        messages.append(msg)

        return messages

    # =========================================================================
    # Contraction Coefficient and Channel Width Check Methods
    # =========================================================================

    @staticmethod
    def _check_contraction_coefficients_and_widths(
        xs_gdf: pd.DataFrame,
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check contraction coefficients and channel widths between adjacent cross sections.

        Validates:
        - XS_CT_03: Contraction coefficient at junction differs from adjacent sections
        - XS_CT_04: Contraction coefficient varies significantly between adjacent sections
        - XS_CW_01: Channel width ratio between adjacent sections exceeds threshold

        Args:
            xs_gdf: Cross section GeoDataFrame
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for coefficient and width issues
        """
        messages = []

        # Get contraction coefficients and channel widths from HDF
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                # Try to get contraction coefficients from XS attributes
                xs_attrs_path = 'Geometry/Cross Sections/Attributes'
                if xs_attrs_path not in hdf:
                    return messages

                xs_attrs = hdf[xs_attrs_path][:]
                attr_names = xs_attrs.dtype.names

                # Build a lookup dictionary of XS data
                xs_data = {}
                for attr in xs_attrs:
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get contraction coefficient
                    contraction_coef = 0.1  # Default
                    if 'Contraction' in attr_names:
                        contraction_coef = float(attr['Contraction'])
                    elif 'Cont Coef' in attr_names:
                        contraction_coef = float(attr['Cont Coef'])

                    # Get expansion coefficient
                    expansion_coef = 0.3  # Default
                    if 'Expansion' in attr_names:
                        expansion_coef = float(attr['Expansion'])
                    elif 'Exp Coef' in attr_names:
                        expansion_coef = float(attr['Exp Coef'])

                    # Get bank stations for channel width
                    left_bank = float(attr['Left Bank']) if 'Left Bank' in attr_names else 0
                    right_bank = float(attr['Right Bank']) if 'Right Bank' in attr_names else 0
                    channel_width = abs(right_bank - left_bank) if right_bank > left_bank else 0

                    # Try numeric RS for sorting
                    try:
                        rs_numeric = float(station.replace('*', ''))
                    except (ValueError, TypeError):
                        rs_numeric = 0

                    xs_data[(river, reach, station)] = {
                        'river': river,
                        'reach': reach,
                        'station': station,
                        'rs_numeric': rs_numeric,
                        'contraction': contraction_coef,
                        'expansion': expansion_coef,
                        'channel_width': channel_width,
                        'left_bank': left_bank,
                        'right_bank': right_bank
                    }

                # Check for junctions from geometry
                junctions = set()
                if 'Geometry/River Centerlines/Attributes' in hdf:
                    river_attrs = hdf['Geometry/River Centerlines/Attributes'][:]
                    if len(river_attrs) > 1:
                        # Multiple reaches - check for junction XS
                        # Junctions are typically at the downstream end of reaches
                        for river_attr in river_attrs:
                            river_name = river_attr['Name'].decode().strip() if isinstance(river_attr['Name'], bytes) else str(river_attr['Name']).strip()
                            # Find the downstream XS (lowest RS) for each reach
                            reach_xs = [(k, v) for k, v in xs_data.items() if k[0] == river_name]
                            if reach_xs:
                                reach_xs.sort(key=lambda x: x[1]['rs_numeric'])
                                # Mark the downstream XS as potentially at a junction
                                junctions.add(reach_xs[0][0])

                # Group XS by river/reach for sequential checks
                reach_xs_groups = {}
                for key, data in xs_data.items():
                    reach_key = (data['river'], data['reach'])
                    if reach_key not in reach_xs_groups:
                        reach_xs_groups[reach_key] = []
                    reach_xs_groups[reach_key].append(data)

                # Sort each reach's XS by station (downstream to upstream)
                for reach_key, xs_list in reach_xs_groups.items():
                    xs_list.sort(key=lambda x: x['rs_numeric'], reverse=True)  # High to low (US to DS)

                # Check adjacent cross sections
                for reach_key, xs_list in reach_xs_groups.items():
                    for i in range(len(xs_list) - 1):
                        xs_us = xs_list[i]
                        xs_ds = xs_list[i + 1]

                        us_key = (xs_us['river'], xs_us['reach'], xs_us['station'])
                        ds_key = (xs_ds['river'], xs_ds['reach'], xs_ds['station'])

                        # XS_CT_03: Check contraction coefficient at junction
                        if us_key in junctions or ds_key in junctions:
                            # This XS is near a junction - check coefficient consistency
                            if abs(xs_us['contraction'] - xs_ds['contraction']) > 0.05:
                                junction_station = xs_us['station'] if us_key in junctions else xs_ds['station']
                                junction_coef = xs_us['contraction'] if us_key in junctions else xs_ds['contraction']
                                msg = CheckMessage(
                                    message_id="XS_CT_03",
                                    severity=Severity.INFO,
                                    check_type="XS",
                                    river=xs_us['river'],
                                    reach=xs_us['reach'],
                                    station=junction_station,
                                    message=format_message("XS_CT_03",
                                                          cc=junction_coef,
                                                          station=junction_station),
                                    help_text=get_help_text("XS_CT_03"),
                                    value=junction_coef
                                )
                                messages.append(msg)

                        # XS_CT_04: Check for significant coefficient variation
                        coef_diff = abs(xs_us['contraction'] - xs_ds['contraction'])
                        if coef_diff > 0.2:  # Threshold: 0.2 difference is significant
                            msg = CheckMessage(
                                message_id="XS_CT_04",
                                severity=Severity.INFO,
                                check_type="XS",
                                river=xs_us['river'],
                                reach=xs_us['reach'],
                                station=xs_us['station'],
                                message=format_message("XS_CT_04",
                                                      cc_us=xs_us['contraction'],
                                                      cc_ds=xs_ds['contraction'],
                                                      station_us=xs_us['station'],
                                                      station_ds=xs_ds['station']),
                                help_text=get_help_text("XS_CT_04"),
                                value=coef_diff
                            )
                            messages.append(msg)

                        # XS_CW_01: Check channel width ratio
                        if xs_us['channel_width'] > 0 and xs_ds['channel_width'] > 0:
                            width_ratio = max(xs_us['channel_width'], xs_ds['channel_width']) / \
                                         min(xs_us['channel_width'], xs_ds['channel_width'])

                            # Flag if ratio exceeds 2.0 (channel doubles or halves)
                            if width_ratio > 2.0:
                                msg = CheckMessage(
                                    message_id="XS_CW_01",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=xs_us['river'],
                                    reach=xs_us['reach'],
                                    station=xs_us['station'],
                                    message=format_message("XS_CW_01",
                                                          ratio=width_ratio,
                                                          station_us=xs_us['station'],
                                                          width_us=xs_us['channel_width'],
                                                          station_ds=xs_ds['station'],
                                                          width_ds=xs_ds['channel_width']),
                                    help_text=get_help_text("XS_CW_01"),
                                    value=width_ratio,
                                    threshold=2.0
                                )
                                messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not check contraction coefficients and widths: {e}")

        return messages

    # =========================================================================
    # Levee Check Methods
    # =========================================================================

    @staticmethod
    def _check_levees(
        xs_gdf: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check levee definitions at cross sections for geometry issues.

        Validates:
        - XS_LV_01L/R: Levee station outside cross section extent
        - XS_LV_02L/R: Levee elevation below adjacent ground
        - XS_LV_03L/R: Levee not at local high point

        Args:
            xs_gdf: Cross section GeoDataFrame with levee data (station_elevation,
                   Left Levee Sta, Left Levee Elev, Right Levee Sta, Right Levee Elev)
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for levee issues
        """
        messages = []

        # Process each cross section
        for idx, xs in xs_gdf.iterrows():
            river = xs.get('River', '')
            reach = xs.get('Reach', '')
            station = str(xs.get('RS', ''))

            # Get levee data
            left_levee_sta = xs.get('Left Levee Sta', None)
            left_levee_elev = xs.get('Left Levee Elev', None)
            right_levee_sta = xs.get('Right Levee Sta', None)
            right_levee_elev = xs.get('Right Levee Elev', None)

            # Get station-elevation data
            sta_elev = xs.get('station_elevation', None)

            # Skip if no levees defined
            if (left_levee_sta is None or pd.isna(left_levee_sta)) and \
               (right_levee_sta is None or pd.isna(right_levee_sta)):
                continue

            # Skip if no station-elevation data
            if sta_elev is None or len(sta_elev) < 2:
                continue

            # Extract station-elevation arrays
            try:
                stations = np.array([p[0] for p in sta_elev])
                elevations = np.array([p[1] for p in sta_elev])
            except (IndexError, TypeError):
                continue

            xs_min_sta = stations.min()
            xs_max_sta = stations.max()

            # Get bank stations for determining left/right search regions
            left_bank = xs.get('Left Bank', xs_min_sta)
            right_bank = xs.get('Right Bank', xs_max_sta)

            # ================================================================
            # Left Levee Checks
            # ================================================================
            if left_levee_sta is not None and not pd.isna(left_levee_sta):
                # XS_LV_01L: Left levee station outside cross section extent
                if left_levee_sta < xs_min_sta or left_levee_sta > xs_max_sta:
                    msg = CheckMessage(
                        message_id="XS_LV_01L",
                        severity=Severity.ERROR,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=f"Left levee station ({left_levee_sta:.1f}) is outside cross section extent ({xs_min_sta:.1f} to {xs_max_sta:.1f})",
                        help_text=get_help_text("XS_LV_01L"),
                        value=left_levee_sta
                    )
                    messages.append(msg)
                else:
                    # Levee station is within XS - do further checks
                    if left_levee_elev is not None and not pd.isna(left_levee_elev):
                        # Find ground elevation at or near levee station
                        # Use interpolation for exact station match
                        ground_elev_at_levee = np.interp(left_levee_sta, stations, elevations)

                        # XS_LV_02L: Left levee elevation below adjacent ground
                        if left_levee_elev < ground_elev_at_levee:
                            msg = CheckMessage(
                                message_id="XS_LV_02L",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Left levee elevation ({left_levee_elev:.2f}) is below adjacent ground elevation ({ground_elev_at_levee:.2f})",
                                help_text=get_help_text("XS_LV_02L"),
                                value=left_levee_elev - ground_elev_at_levee
                            )
                            messages.append(msg)

                        # XS_LV_03L: Left levee not at local high point
                        # Find max ground elevation in a search window around the levee
                        # Search from start of XS to left bank (left overbank region)
                        search_mask = (stations >= xs_min_sta) & (stations <= left_bank)
                        if search_mask.any():
                            local_max_ground = elevations[search_mask].max()

                            # Check if levee elevation is the highest point (within tolerance)
                            tolerance = 0.1  # 0.1 ft tolerance
                            if left_levee_elev < local_max_ground - tolerance:
                                msg = CheckMessage(
                                    message_id="XS_LV_03L",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Left levee ({left_levee_elev:.2f}) is not at local high point (max nearby ground: {local_max_ground:.2f})",
                                    help_text=get_help_text("XS_LV_03L"),
                                    value=local_max_ground - left_levee_elev
                                )
                                messages.append(msg)

            # ================================================================
            # Right Levee Checks
            # ================================================================
            if right_levee_sta is not None and not pd.isna(right_levee_sta):
                # XS_LV_01R: Right levee station outside cross section extent
                if right_levee_sta < xs_min_sta or right_levee_sta > xs_max_sta:
                    msg = CheckMessage(
                        message_id="XS_LV_01R",
                        severity=Severity.ERROR,
                        check_type="XS",
                        river=river,
                        reach=reach,
                        station=station,
                        message=f"Right levee station ({right_levee_sta:.1f}) is outside cross section extent ({xs_min_sta:.1f} to {xs_max_sta:.1f})",
                        help_text=get_help_text("XS_LV_01R"),
                        value=right_levee_sta
                    )
                    messages.append(msg)
                else:
                    # Levee station is within XS - do further checks
                    if right_levee_elev is not None and not pd.isna(right_levee_elev):
                        # Find ground elevation at or near levee station
                        ground_elev_at_levee = np.interp(right_levee_sta, stations, elevations)

                        # XS_LV_02R: Right levee elevation below adjacent ground
                        if right_levee_elev < ground_elev_at_levee:
                            msg = CheckMessage(
                                message_id="XS_LV_02R",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=river,
                                reach=reach,
                                station=station,
                                message=f"Right levee elevation ({right_levee_elev:.2f}) is below adjacent ground elevation ({ground_elev_at_levee:.2f})",
                                help_text=get_help_text("XS_LV_02R"),
                                value=right_levee_elev - ground_elev_at_levee
                            )
                            messages.append(msg)

                        # XS_LV_03R: Right levee not at local high point
                        # Search from right bank to end of XS (right overbank region)
                        search_mask = (stations >= right_bank) & (stations <= xs_max_sta)
                        if search_mask.any():
                            local_max_ground = elevations[search_mask].max()

                            # Check if levee elevation is the highest point (within tolerance)
                            tolerance = 0.1  # 0.1 ft tolerance
                            if right_levee_elev < local_max_ground - tolerance:
                                msg = CheckMessage(
                                    message_id="XS_LV_03R",
                                    severity=Severity.WARNING,
                                    check_type="XS",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Right levee ({right_levee_elev:.2f}) is not at local high point (max nearby ground: {local_max_ground:.2f})",
                                    help_text=get_help_text("XS_LV_03R"),
                                    value=local_max_ground - right_levee_elev
                                )
                                messages.append(msg)

        return messages

    # =========================================================================
    # N-Value Variation Check Methods
    # =========================================================================

    @staticmethod
    def _check_n_value_variation(
        xs_gdf: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check for large Manning's n value changes between adjacent cross sections.

        Flags when n-values change by more than 50% between consecutive XS
        within the same reach.

        Args:
            xs_gdf: Cross section GeoDataFrame with n_lob, n_channel, n_rob columns
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for n-value variation issues
        """
        messages = []

        # Get variation threshold (default 50% = 0.5)
        max_variation = getattr(thresholds.mannings_n, 'max_variation_pct', 50.0) / 100.0

        # Group by River and Reach
        if 'River' not in xs_gdf.columns or 'Reach' not in xs_gdf.columns:
            return messages

        for (river, reach), group in xs_gdf.groupby(['River', 'Reach']):
            # Sort by station (RS) - descending for upstream to downstream
            group_sorted = group.sort_values('RS', ascending=False)

            # Compare adjacent cross sections
            prev_row = None
            for idx, row in group_sorted.iterrows():
                if prev_row is not None:
                    station_us = str(prev_row.get('RS', ''))
                    station_ds = str(row.get('RS', ''))

                    # Check LOB n variation
                    n_lob_us = prev_row.get('n_lob', np.nan)
                    n_lob_ds = row.get('n_lob', np.nan)
                    if not pd.isna(n_lob_us) and not pd.isna(n_lob_ds) and n_lob_us > 0:
                        pct_change = abs(n_lob_ds - n_lob_us) / n_lob_us
                        if pct_change > max_variation:
                            msg = CheckMessage(
                                message_id="NT_VR_01L",
                                severity=Severity.WARNING,
                                check_type="NT",
                                river=river,
                                reach=reach,
                                station=station_ds,
                                message=f"Large LOB n-value change ({pct_change*100:.0f}%) between RS {station_us} ({n_lob_us:.3f}) and RS {station_ds} ({n_lob_ds:.3f})",
                                help_text=get_help_text("NT_VR_01L"),
                                value=pct_change * 100
                            )
                            messages.append(msg)

                    # Check Channel n variation
                    n_chl_us = prev_row.get('n_channel', np.nan)
                    n_chl_ds = row.get('n_channel', np.nan)
                    if not pd.isna(n_chl_us) and not pd.isna(n_chl_ds) and n_chl_us > 0:
                        pct_change = abs(n_chl_ds - n_chl_us) / n_chl_us
                        if pct_change > max_variation:
                            msg = CheckMessage(
                                message_id="NT_VR_01C",
                                severity=Severity.WARNING,
                                check_type="NT",
                                river=river,
                                reach=reach,
                                station=station_ds,
                                message=f"Large channel n-value change ({pct_change*100:.0f}%) between RS {station_us} ({n_chl_us:.3f}) and RS {station_ds} ({n_chl_ds:.3f})",
                                help_text=get_help_text("NT_VR_01C"),
                                value=pct_change * 100
                            )
                            messages.append(msg)

                    # Check ROB n variation
                    n_rob_us = prev_row.get('n_rob', np.nan)
                    n_rob_ds = row.get('n_rob', np.nan)
                    if not pd.isna(n_rob_us) and not pd.isna(n_rob_ds) and n_rob_us > 0:
                        pct_change = abs(n_rob_ds - n_rob_us) / n_rob_us
                        if pct_change > max_variation:
                            msg = CheckMessage(
                                message_id="NT_VR_01R",
                                severity=Severity.WARNING,
                                check_type="NT",
                                river=river,
                                reach=reach,
                                station=station_ds,
                                message=f"Large ROB n-value change ({pct_change*100:.0f}%) between RS {station_us} ({n_rob_us:.3f}) and RS {station_ds} ({n_rob_ds:.3f})",
                                help_text=get_help_text("NT_VR_01R"),
                                value=pct_change * 100
                            )
                            messages.append(msg)

                prev_row = row

        return messages

    @staticmethod
    def _check_structure_transition_coefficients(
        geom_hdf: Path,
        xs_gdf: pd.DataFrame,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check transition coefficients at structure sections (2, 3, 4).

        Standard values at structure sections are 0.3 contraction / 0.5 expansion.

        Args:
            geom_hdf: Path to geometry HDF file
            xs_gdf: Cross section GeoDataFrame with Contr, Expan columns
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for non-standard coefficients at structures
        """
        messages = []

        # Expected coefficients at structure sections
        struct_contr = thresholds.transitions.structure_contraction_max  # 0.3
        struct_expan = thresholds.transitions.structure_expansion_max    # 0.5
        tolerance = 0.01  # Allow small tolerance

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                # Check if structures exist
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                if 'US Type' not in attr_names or 'DS Type' not in attr_names:
                    return messages

                # Find bridges (structures with US Type='XS' and DS Type='XS')
                for i, attr in enumerate(struct_attrs):
                    us_type = attr['US Type'].decode().strip() if isinstance(attr['US Type'], bytes) else str(attr['US Type']).strip()
                    ds_type = attr['DS Type'].decode().strip() if isinstance(attr['DS Type'], bytes) else str(attr['DS Type']).strip()

                    # Only check bridges (XS on both sides)
                    if us_type != 'XS' or ds_type != 'XS':
                        continue

                    river = attr['River'].decode().strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode().strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    bridge_rs = attr['RS']

                    # Get US RS and DS RS (Section 1 and Section 4)
                    us_rs = float(attr['US RS'].decode().strip() if isinstance(attr['US RS'], bytes) else attr['US RS'])
                    ds_rs = float(attr['DS RS'].decode().strip() if isinstance(attr['DS RS'], bytes) else attr['DS RS'])

                    # Find Section 1 (US RS) in xs_gdf
                    section_1 = xs_gdf[(xs_gdf['River'] == river) &
                                       (xs_gdf['Reach'] == reach) &
                                       (abs(xs_gdf['RS'].astype(float) - us_rs) < 0.1)]
                    if not section_1.empty:
                        row = section_1.iloc[0]
                        contr = row.get('Contr', np.nan)
                        expan = row.get('Expan', np.nan)

                        # Section 1 should also have structure coefficients
                        if not pd.isna(contr) and not pd.isna(expan):
                            if abs(contr - struct_contr) > tolerance or abs(expan - struct_expan) > tolerance:
                                msg = CheckMessage(
                                    message_id="NT_TL_01S1",
                                    severity=Severity.WARNING,
                                    check_type="NT",
                                    river=river,
                                    reach=reach,
                                    station=str(us_rs),
                                    structure=str(bridge_rs),
                                    message=f"Section 1 (US of bridge {bridge_rs}): Transition coefficients ({contr:.2f}/{expan:.2f}) should be {struct_contr}/{struct_expan}",
                                    help_text=get_help_text("NT_TL_01S2")  # Reuse help text
                                )
                                messages.append(msg)

                    # Find Section 4 (DS RS) in xs_gdf
                    section_4 = xs_gdf[(xs_gdf['River'] == river) &
                                       (xs_gdf['Reach'] == reach) &
                                       (abs(xs_gdf['RS'].astype(float) - ds_rs) < 0.1)]
                    if not section_4.empty:
                        row = section_4.iloc[0]
                        contr = row.get('Contr', np.nan)
                        expan = row.get('Expan', np.nan)

                        # Section 4 should have structure coefficients
                        if not pd.isna(contr) and not pd.isna(expan):
                            if abs(contr - struct_contr) > tolerance or abs(expan - struct_expan) > tolerance:
                                msg = CheckMessage(
                                    message_id="NT_TL_01S4",
                                    severity=Severity.WARNING,
                                    check_type="NT",
                                    river=river,
                                    reach=reach,
                                    station=str(ds_rs),
                                    structure=str(bridge_rs),
                                    message=format_message("NT_TL_01S4", cc=f"{contr:.2f}", ce=f"{expan:.2f}"),
                                    help_text=get_help_text("NT_TL_01S4")
                                )
                                messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure transition coefficients: {e}")

        return messages

    # =========================================================================
    # Bridge Section Manning's n Methods
    # =========================================================================

    @staticmethod
    def _check_bridge_section_mannings_n(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check Manning's n consistency between bridge sections.

        Compares:
        - Section 1 vs Section 2 (only when Section 2 has custom Manning's n)
        - Section 3 vs Section 4 (only when Section 3 has custom Manning's n)

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for any issues found
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                attrs = hdf['Geometry/Structures/Attributes'][:]

                # Find all bridges
                bridge_indices = []
                for i, attr in enumerate(attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type'])
                    us_type = attr['US Type'].decode('utf-8').strip() if isinstance(attr['US Type'], bytes) else str(attr['US Type'])
                    ds_type = attr['DS Type'].decode('utf-8').strip() if isinstance(attr['DS Type'], bytes) else str(attr['DS Type'])

                    # Only check bridges that connect cross sections on both sides
                    if struct_type == 'Bridge' and us_type == 'XS' and ds_type == 'XS':
                        bridge_indices.append(i)

        except Exception as e:
            logger.warning(f"Could not read structures for bridge n check: {e}")
            return messages

        # Check each bridge
        for bridge_idx in bridge_indices:
            try:
                bridge_data = RasCheck._get_bridge_section_mannings_n(geom_hdf, bridge_idx)

                river = bridge_data['river']
                reach = bridge_data['reach']
                bridge_rs = bridge_data['bridge_rs']
                us_rs = bridge_data['us_rs']
                ds_rs = bridge_data['ds_rs']

                # NT_RS_01S2C: Compare Section 1 vs Section 2 channel n
                # Only check when Section 2 has custom Manning's n
                if bridge_data['section_2_custom']:
                    section_1_n = bridge_data['section_1_n']
                    section_2_n = bridge_data['section_2_n']
                    left_bank, right_bank = bridge_data['section_1_banks']

                    # Get channel n for both sections
                    sec1_channel_n = RasCheck._get_channel_n_from_regions(section_1_n, left_bank, right_bank)
                    sec2_channel_n = RasCheck._get_channel_n_from_regions(section_2_n, left_bank, right_bank)

                    if sec1_channel_n is not None and sec2_channel_n is not None:
                        n_diff = abs(sec2_channel_n - sec1_channel_n)
                        if n_diff > 0.005:
                            msg = CheckMessage(
                                message_id="NT_RS_01S2C",
                                severity=Severity.INFO,
                                check_type="NT",
                                river=river,
                                reach=reach,
                                station=bridge_rs,
                                structure=f"Bridge {bridge_rs}",
                                message=f"Bridge {bridge_rs}: Section 2 channel n ({sec2_channel_n:.3f}) "
                                       f"differs from Section 1 ({sec1_channel_n:.3f}) by {n_diff:.3f}",
                                help_text="Internal bridge section has different channel roughness than upstream XS. "
                                         "Verify this is intentional.",
                                value=n_diff
                            )
                            messages.append(msg)

                    # Also check for any n-value differences across the section
                    differences = RasCheck._compare_n_regions(section_1_n, section_2_n)
                    if differences:
                        # Summarize differences
                        diff_summary = "; ".join([
                            f"sta {d['station']:.0f}: {d['n1']:.3f}→{d['n2']:.3f}"
                            for d in differences[:3]  # Show first 3
                        ])
                        if len(differences) > 3:
                            diff_summary += f" (+{len(differences)-3} more)"

                        msg = CheckMessage(
                            message_id="NT_RS_02BUC",
                            severity=Severity.INFO,
                            check_type="NT",
                            river=river,
                            reach=reach,
                            station=bridge_rs,
                            structure=f"Bridge {bridge_rs}",
                            message=f"Bridge {bridge_rs} upstream: Section 2 has different n-values "
                                   f"than Section 1: {diff_summary}",
                            help_text="Bridge internal upstream section has modified Manning's n values. "
                                     "Review to ensure they are appropriate for the bridge opening.",
                            value=len(differences)
                        )
                        messages.append(msg)

                # NT_RS_01S3C: Compare Section 3 vs Section 4 channel n
                # Only check when Section 3 has custom Manning's n
                if bridge_data['section_3_custom']:
                    section_3_n = bridge_data['section_3_n']
                    section_4_n = bridge_data['section_4_n']
                    left_bank, right_bank = bridge_data['section_4_banks']

                    # Get channel n for both sections
                    sec3_channel_n = RasCheck._get_channel_n_from_regions(section_3_n, left_bank, right_bank)
                    sec4_channel_n = RasCheck._get_channel_n_from_regions(section_4_n, left_bank, right_bank)

                    if sec3_channel_n is not None and sec4_channel_n is not None:
                        n_diff = abs(sec3_channel_n - sec4_channel_n)
                        if n_diff > 0.005:
                            msg = CheckMessage(
                                message_id="NT_RS_01S3C",
                                severity=Severity.INFO,
                                check_type="NT",
                                river=river,
                                reach=reach,
                                station=bridge_rs,
                                structure=f"Bridge {bridge_rs}",
                                message=f"Bridge {bridge_rs}: Section 3 channel n ({sec3_channel_n:.3f}) "
                                       f"differs from Section 4 ({sec4_channel_n:.3f}) by {n_diff:.3f}",
                                help_text="Internal bridge section has different channel roughness than downstream XS. "
                                         "Verify this is intentional.",
                                value=n_diff
                            )
                            messages.append(msg)

                    # Also check for any n-value differences across the section
                    differences = RasCheck._compare_n_regions(section_4_n, section_3_n)
                    if differences:
                        # Summarize differences
                        diff_summary = "; ".join([
                            f"sta {d['station']:.0f}: {d['n1']:.3f}→{d['n2']:.3f}"
                            for d in differences[:3]  # Show first 3
                        ])
                        if len(differences) > 3:
                            diff_summary += f" (+{len(differences)-3} more)"

                        msg = CheckMessage(
                            message_id="NT_RS_02BDC",
                            severity=Severity.INFO,
                            check_type="NT",
                            river=river,
                            reach=reach,
                            station=bridge_rs,
                            structure=f"Bridge {bridge_rs}",
                            message=f"Bridge {bridge_rs} downstream: Section 3 has different n-values "
                                   f"than Section 4: {diff_summary}",
                            help_text="Bridge internal downstream section has modified Manning's n values. "
                                     "Review to ensure they are appropriate for the bridge opening.",
                            value=len(differences)
                        )
                        messages.append(msg)

            except Exception as e:
                logger.warning(f"Could not check bridge {bridge_idx}: {e}")
                continue

        return messages

    @staticmethod
    def _get_bridge_section_mannings_n(
        geom_hdf: Path,
        bridge_idx: int
    ) -> Dict:
        """
        Get Manning's n values for all 4 sections of a bridge.

        In HEC-RAS bridge modeling:
        - Section 1 = Last regular XS upstream of bridge (at US RS)
        - Section 2 = Bridge upstream face (uses Section 1 geometry or custom BR U data)
        - Section 3 = Bridge downstream face (uses Section 4 geometry or custom BR D data)
        - Section 4 = First regular XS downstream of bridge (at DS RS)

        Args:
            geom_hdf: Path to geometry HDF file
            bridge_idx: Index of the bridge in Structures/Attributes

        Returns:
            Dictionary with:
                - section_1_n: List of (station, n_value) tuples for Section 1
                - section_2_n: List of (station, n_value) tuples for Section 2
                - section_3_n: List of (station, n_value) tuples for Section 3
                - section_4_n: List of (station, n_value) tuples for Section 4
                - section_2_custom: True if Section 2 has custom Manning's n
                - section_3_custom: True if Section 3 has custom Manning's n
                - us_rs: Upstream RS (Section 1)
                - ds_rs: Downstream RS (Section 4)
                - bridge_rs: Bridge RS
                - river: River name
                - reach: Reach name
        """
        with h5py.File(geom_hdf, 'r') as hdf:
            # Get structure attributes
            attrs = hdf['Geometry/Structures/Attributes'][bridge_idx]
            table_info = hdf['Geometry/Structures/Table Info'][bridge_idx]

            river = attrs['River'].decode('utf-8').strip() if isinstance(attrs['River'], bytes) else str(attrs['River'])
            reach = attrs['Reach'].decode('utf-8').strip() if isinstance(attrs['Reach'], bytes) else str(attrs['Reach'])
            bridge_rs = attrs['RS'].decode('utf-8').strip() if isinstance(attrs['RS'], bytes) else str(attrs['RS'])
            us_rs = attrs['US RS'].decode('utf-8').strip() if isinstance(attrs['US RS'], bytes) else str(attrs['US RS'])
            ds_rs = attrs['DS RS'].decode('utf-8').strip() if isinstance(attrs['DS RS'], bytes) else str(attrs['DS RS'])

            # Get cross section Manning's n data
            xs_attrs = hdf['Geometry/Cross Sections/Attributes'][:]
            xs_mann_info = hdf['Geometry/Cross Sections/Manning\'s n Info'][:]
            xs_mann_values = hdf['Geometry/Cross Sections/Manning\'s n Values'][:]

            # Find Section 1 (US RS) in cross sections
            section_1_n = []
            section_1_banks = (0, 0)
            for i, xs in enumerate(xs_attrs):
                xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS'])
                if xs_rs == us_rs:
                    mann_idx = xs_mann_info[i][0]
                    mann_cnt = xs_mann_info[i][1]
                    if mann_cnt > 0:
                        section_1_n = [(float(xs_mann_values[mann_idx + j][0]),
                                       float(xs_mann_values[mann_idx + j][1]))
                                      for j in range(mann_cnt)]
                    section_1_banks = (float(xs['Left Bank']), float(xs['Right Bank']))
                    break

            # Find Section 4 (DS RS) in cross sections
            section_4_n = []
            section_4_banks = (0, 0)
            for i, xs in enumerate(xs_attrs):
                xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS'])
                if xs_rs == ds_rs:
                    mann_idx = xs_mann_info[i][0]
                    mann_cnt = xs_mann_info[i][1]
                    if mann_cnt > 0:
                        section_4_n = [(float(xs_mann_values[mann_idx + j][0]),
                                       float(xs_mann_values[mann_idx + j][1]))
                                      for j in range(mann_cnt)]
                    section_4_banks = (float(xs['Left Bank']), float(xs['Right Bank']))
                    break

            # Check for custom Section 2 (US BR Mann) data
            us_br_cnt = int(table_info['US BR Mann (Count)'])
            section_2_custom = us_br_cnt > 0

            if section_2_custom and 'Geometry/Structures/Mannings Data' in hdf:
                us_br_idx = int(table_info['US BR Mann (Index)'])
                struct_mann = hdf['Geometry/Structures/Mannings Data'][:]
                section_2_n = [(float(struct_mann[us_br_idx + j][0]),
                               float(struct_mann[us_br_idx + j][1]))
                              for j in range(us_br_cnt)]
            else:
                # Inherit from Section 1
                section_2_n = section_1_n.copy()

            # Check for custom Section 3 (DS BR Mann) data
            ds_br_cnt = int(table_info['DS BR Mann (Count)'])
            section_3_custom = ds_br_cnt > 0

            if section_3_custom and 'Geometry/Structures/Mannings Data' in hdf:
                ds_br_idx = int(table_info['DS BR Mann (Index)'])
                struct_mann = hdf['Geometry/Structures/Mannings Data'][:]
                section_3_n = [(float(struct_mann[ds_br_idx + j][0]),
                               float(struct_mann[ds_br_idx + j][1]))
                              for j in range(ds_br_cnt)]
            else:
                # Inherit from Section 4
                section_3_n = section_4_n.copy()

            return {
                'section_1_n': section_1_n,
                'section_2_n': section_2_n,
                'section_3_n': section_3_n,
                'section_4_n': section_4_n,
                'section_1_banks': section_1_banks,
                'section_4_banks': section_4_banks,
                'section_2_custom': section_2_custom,
                'section_3_custom': section_3_custom,
                'us_rs': us_rs,
                'ds_rs': ds_rs,
                'bridge_rs': bridge_rs,
                'river': river,
                'reach': reach
            }

    @staticmethod
    def _get_channel_n_from_regions(
        n_regions: List[Tuple[float, float]],
        left_bank: float,
        right_bank: float
    ) -> Optional[float]:
        """
        Extract channel Manning's n from station-based n regions.

        Args:
            n_regions: List of (station, n_value) tuples
            left_bank: Left bank station
            right_bank: Right bank station

        Returns:
            Channel n value, or None if not found
        """
        if not n_regions or left_bank >= right_bank:
            return None

        # Find the n value that applies to the channel region
        # N values are given at the START of each region
        channel_n = None
        for sta, n in n_regions:
            if sta <= left_bank:
                # This region extends into or past the channel
                channel_n = n
            elif sta < right_bank:
                # This region starts in the channel
                channel_n = n
                break

        return channel_n

    @staticmethod
    def _compare_n_regions(
        n_regions_1: List[Tuple[float, float]],
        n_regions_2: List[Tuple[float, float]],
        tolerance: float = 0.005
    ) -> List[Dict]:
        """
        Compare two sets of Manning's n regions and find differences.

        Args:
            n_regions_1: First set of (station, n_value) tuples
            n_regions_2: Second set of (station, n_value) tuples
            tolerance: Tolerance for n value differences

        Returns:
            List of difference dictionaries with station, n1, n2
        """
        differences = []

        # Build combined station list
        all_stations = set()
        for sta, _ in n_regions_1:
            all_stations.add(sta)
        for sta, _ in n_regions_2:
            all_stations.add(sta)

        # Convert to sorted list
        all_stations = sorted(all_stations)

        # Get n value at each station for both regions
        def get_n_at_station(n_regions, station):
            n_val = None
            for sta, n in n_regions:
                if sta <= station:
                    n_val = n
                else:
                    break
            return n_val

        for sta in all_stations:
            n1 = get_n_at_station(n_regions_1, sta)
            n2 = get_n_at_station(n_regions_2, sta)

            if n1 is not None and n2 is not None:
                if abs(n1 - n2) > tolerance:
                    differences.append({
                        'station': sta,
                        'n1': n1,
                        'n2': n2,
                        'diff': n2 - n1
                    })

        return differences

    # =========================================================================
    # Culvert Flow Type and Coefficient Checks
    # =========================================================================

    @staticmethod
    def _check_culverts(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check culvert flow types and loss coefficients (CV_* checks).

        Validates:
        - CV_TF_01-07: Flow type detection (outlet control, inlet control, pressure, overtopping)
        - CV_LF_01-03: Loss coefficient ranges (entrance, exit, bend)
        - CV_PF_01-02: Pressure flow and submergence warnings
        - CV_PW_01: Combined pressure and weir flow detection
        - CV_CF_01-02: Chart/scale configuration checks

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for culvert validation
        """
        messages = []
        s_thresholds = thresholds.structures

        try:
            with h5py.File(geom_hdf, 'r') as geom_h:
                # Check for structures in geometry
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Find culverts
                culverts = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Check for culvert type
                    if 'Culvert' in struct_type:
                        river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                        name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else f'Culvert_{station}'

                        culvert_info = {
                            'index': i,
                            'river': river,
                            'reach': reach,
                            'station': station,
                            'name': name,
                            'type': struct_type
                        }

                        culverts.append(culvert_info)

                if not culverts:
                    return messages

                # Try to read culvert-specific data from geometry if available
                # Check for Culvert Groups dataset
                culvert_groups_path = 'Geometry/Structures/Culvert Groups'
                if culvert_groups_path in geom_h:
                    culvert_groups = geom_h[culvert_groups_path][:]
                    cg_names = culvert_groups.dtype.names if culvert_groups.dtype.names else []

                    # Match culvert groups to structures
                    for culvert in culverts:
                        # Find matching culvert group by structure index or name
                        for cg in culvert_groups:
                            # Extract relevant attributes if available
                            if 'Entrance Loss' in cg_names:
                                ke = float(cg['Entrance Loss'])
                                culvert['entrance_loss'] = ke

                                # CV_LF_01: Check entrance loss coefficient range (0.2-0.9)
                                if ke < s_thresholds.culvert_entrance_coef_min or ke > s_thresholds.culvert_entrance_coef_max:
                                    msg = CheckMessage(
                                        message_id="CV_LF_01",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Entrance loss coefficient ({ke:.2f}) outside typical range (0.2-0.9) at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_LF_01"),
                                        value=ke,
                                        threshold=f"{s_thresholds.culvert_entrance_coef_min}-{s_thresholds.culvert_entrance_coef_max}"
                                    )
                                    messages.append(msg)

                            if 'Exit Loss' in cg_names:
                                kx = float(cg['Exit Loss'])
                                culvert['exit_loss'] = kx

                                # CV_LF_02: Check exit loss coefficient range (0.5-1.0)
                                if kx < 0.5 or kx > 1.0:
                                    msg = CheckMessage(
                                        message_id="CV_LF_02",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Exit loss coefficient ({kx:.2f}) outside typical range (0.5-1.0) at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_LF_02"),
                                        value=kx
                                    )
                                    messages.append(msg)

                            if 'Chart' in cg_names and 'Scale' in cg_names:
                                chart = int(cg['Chart']) if cg['Chart'] else 0
                                scale = float(cg['Scale']) if cg['Scale'] else 1.0

                                # CV_CF_01: Chart/scale configuration (INFO)
                                if chart > 0:
                                    msg = CheckMessage(
                                        message_id="CV_CF_01",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Chart {chart} with scale {scale:.2f} at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_CF_01")
                                    )
                                    messages.append(msg)

                                # CV_CF_02: Scale factor less than 1.0
                                if scale < 1.0:
                                    msg = CheckMessage(
                                        message_id="CV_CF_02",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Scale factor ({scale:.2f}) less than 1.0 at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_CF_02"),
                                        value=scale
                                    )
                                    messages.append(msg)

                            # Only process first matching group per culvert
                            break

        except Exception as e:
            logger.debug(f"Could not read culvert geometry data: {e}")

        # Check results if plan HDF is available
        if plan_hdf is None or not Path(plan_hdf).exists():
            return messages

        try:
            with h5py.File(plan_hdf, 'r') as plan_h:
                # Look for steady results with structure data
                # Check multiple possible paths
                struct_results_base = None
                for base_path in ['Results/Steady/Structures', 'Results/Steady/Structure']:
                    if base_path in plan_h:
                        struct_results_base = base_path
                        break

                if struct_results_base is None:
                    return messages

                # Try to find culvert-specific results
                # Path may vary: Results/Steady/Structures/Culvert or similar
                for profile in profiles:
                    profile_path = f"{struct_results_base}/{profile}"
                    if profile_path not in plan_h:
                        continue

                    profile_grp = plan_h[profile_path]

                    # Check for culvert results
                    for culvert in culverts:
                        culvert_name = culvert['name']
                        river = culvert['river']
                        reach = culvert['reach']
                        station = culvert['station']

                        # Try different culvert result paths
                        culvert_result = None
                        for path_variant in [culvert_name, f"Culvert {station}", station]:
                            if path_variant in profile_grp:
                                culvert_result = profile_grp[path_variant]
                                break

                        if culvert_result is None:
                            continue

                        # Check for flow type indicators
                        # HEC-RAS stores: Culvert Q, HW Elev, TW Elev, Flow Type, etc.
                        result_attrs = dict(culvert_result.attrs) if hasattr(culvert_result, 'attrs') else {}

                        flow_type = result_attrs.get('Flow Type', None)
                        if flow_type is not None:
                            if isinstance(flow_type, bytes):
                                flow_type = flow_type.decode('utf-8').strip()
                            flow_type = str(flow_type).strip()

                            # Map flow types to CV_TF_* messages
                            flow_type_map = {
                                '1': ('CV_TF_01', Severity.INFO, "Type 1 flow (outlet control, unsubmerged)"),
                                '2': ('CV_TF_02', Severity.INFO, "Type 2 flow (outlet control, submerged outlet)"),
                                '3': ('CV_TF_03', Severity.INFO, "Type 3 flow (inlet control, unsubmerged)"),
                                '4': ('CV_TF_04', Severity.INFO, "Type 4 flow (inlet control, submerged)"),
                                '5': ('CV_TF_05', Severity.WARNING, "Type 5 flow (full flow)"),
                                '6': ('CV_TF_06', Severity.WARNING, "Type 6 flow (pressure flow)"),
                                '7': ('CV_TF_07', Severity.WARNING, "Type 7 flow (overtopping)"),
                                'Outlet': ('CV_TF_01', Severity.INFO, "Outlet control flow"),
                                'Inlet': ('CV_TF_03', Severity.INFO, "Inlet control flow"),
                                'Full': ('CV_TF_05', Severity.WARNING, "Full flow"),
                                'Pressure': ('CV_TF_06', Severity.WARNING, "Pressure flow"),
                                'Overtop': ('CV_TF_07', Severity.WARNING, "Overtopping"),
                            }

                            # Check for matching flow type
                            for key, (msg_id, severity, desc) in flow_type_map.items():
                                if key.lower() in flow_type.lower():
                                    msg = CheckMessage(
                                        message_id=msg_id,
                                        severity=severity,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=culvert_name,
                                        message=f"{desc} at culvert '{culvert_name}' for {profile}",
                                        help_text=get_help_text(msg_id)
                                    )
                                    messages.append(msg)
                                    break

                        # Check headwater/tailwater for pressure flow indicators
                        hw_elev = result_attrs.get('HW Elev', None)
                        tw_elev = result_attrs.get('TW Elev', None)
                        inlet_elev = result_attrs.get('Inlet Elev', result_attrs.get('US Invert', None))
                        culvert_rise = result_attrs.get('Rise', result_attrs.get('Diameter', None))

                        if hw_elev is not None and inlet_elev is not None and culvert_rise is not None:
                            try:
                                hw = float(hw_elev)
                                inlet = float(inlet_elev)
                                rise = float(culvert_rise)

                                if rise > 0:
                                    hw_ratio = (hw - inlet) / rise

                                    # CV_PF_02: Deep submergence (HW/D > 1.2)
                                    if hw_ratio > 1.2:
                                        msg = CheckMessage(
                                            message_id="CV_PF_02",
                                            severity=Severity.WARNING,
                                            check_type="STRUCT",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            structure=culvert_name,
                                            message=f"Inlet submerged by more than 1.2D (HW/D = {hw_ratio:.2f}) at culvert '{culvert_name}' for {profile}",
                                            help_text=get_help_text("CV_PF_02"),
                                            value=hw_ratio
                                        )
                                        messages.append(msg)

                                    # CV_PF_01: General pressure flow
                                    if hw_ratio > 1.0:
                                        msg = CheckMessage(
                                            message_id="CV_PF_01",
                                            severity=Severity.WARNING,
                                            check_type="STRUCT",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            structure=culvert_name,
                                            message=f"Pressure flow detected at culvert '{culvert_name}' for {profile}",
                                            help_text=get_help_text("CV_PF_01")
                                        )
                                        messages.append(msg)
                            except (ValueError, TypeError):
                                pass

                        # Check for combined pressure/weir flow
                        weir_q = result_attrs.get('Weir Q', result_attrs.get('Weir Flow', None))
                        culvert_q = result_attrs.get('Culvert Q', result_attrs.get('Culvert Flow', None))

                        if weir_q is not None and culvert_q is not None:
                            try:
                                weir_flow = float(weir_q)
                                culv_flow = float(culvert_q)

                                # CV_PW_01: Combined pressure and weir flow
                                if weir_flow > 0 and culv_flow > 0:
                                    msg = CheckMessage(
                                        message_id="CV_PW_01",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=culvert_name,
                                        message=f"Combined pressure and weir flow at culvert '{culvert_name}' for {profile}",
                                        help_text=get_help_text("CV_PW_01")
                                    )
                                    messages.append(msg)
                            except (ValueError, TypeError):
                                pass

        except Exception as e:
            logger.debug(f"Could not read culvert results: {e}")

        return messages

    # =========================================================================
    # Inline Weir Flow Type Checks
    # =========================================================================

    @staticmethod
    def _check_inline_weirs(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check inline weir flow types (IW_TF_* checks).

        Determines flow type for each inline weir:
        - IW_TF_01: Weir flow only (no gate flow)
        - IW_TF_02: Gate flow only (no weir flow)
        - IW_TF_03: Combined weir and gate flow

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for inline weir flow type observations
        """
        messages = []

        if plan_hdf is None or not plan_hdf.exists():
            return messages

        try:
            with h5py.File(geom_hdf, 'r') as geom_h, h5py.File(plan_hdf, 'r') as plan_h:
                # Check for inline weirs in geometry
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Find inline weirs
                inline_weirs = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Check for inline weir types
                    if 'Inline' in struct_type or 'Weir' in struct_type:
                        river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                        name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else str(attr.get('Node Name', f'IW_{station}'))

                        # Get weir attributes
                        weir_coef = float(attr['Weir Coef']) if 'Weir Coef' in attr_names else 0
                        has_gates = False

                        # Check for gate groups
                        if 'Gate Groups' in attr_names:
                            gate_groups = attr['Gate Groups']
                            if isinstance(gate_groups, bytes):
                                gate_groups = gate_groups.decode('utf-8').strip()
                            has_gates = len(str(gate_groups).strip()) > 0

                        inline_weirs.append({
                            'index': i,
                            'river': river,
                            'reach': reach,
                            'station': station,
                            'name': name,
                            'type': struct_type,
                            'weir_coef': weir_coef,
                            'has_gates': has_gates
                        })

                if not inline_weirs:
                    return messages

                # Check for steady results with structure flow data
                # Path varies: Results/Steady/Structures/ or Results/Steady/Structure/
                struct_results_base = None
                for base_path in ['Results/Steady/Structures', 'Results/Steady/Structure']:
                    if base_path in plan_h:
                        struct_results_base = base_path
                        break

                if struct_results_base is None:
                    # No structure results, just report weir presence
                    for weir in inline_weirs:
                        msg = CheckMessage(
                            message_id="IW_TF_01",
                            severity=Severity.INFO,
                            check_type="STRUCT",
                            river=weir['river'],
                            reach=weir['reach'],
                            station=weir['station'],
                            structure=weir['name'],
                            message=format_message("IW_TF_01", name=weir['name'], profile="all profiles"),
                            help_text=get_help_text("IW_TF_01")
                        )
                        messages.append(msg)
                    return messages

                # Process each inline weir
                for weir in inline_weirs:
                    for profile in profiles:
                        weir_flow = 0.0
                        gate_flow = 0.0

                        # Try to get flow data for this weir
                        # Structure results path: {base}/Node Name/Flow
                        weir_path = f"{struct_results_base}/{weir['name']}"

                        if weir_path in plan_h:
                            struct_group = plan_h[weir_path]

                            # Look for weir flow data
                            if 'Weir Flow' in struct_group:
                                weir_flow_data = struct_group['Weir Flow'][:]
                                # Find profile index
                                if 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names' in plan_h:
                                    profile_names = plan_h['Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'][:]
                                    profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                   for p in profile_names]
                                    if profile in profile_names:
                                        prof_idx = profile_names.index(profile)
                                        if prof_idx < len(weir_flow_data):
                                            weir_flow = float(weir_flow_data[prof_idx])

                            # Look for gate flow data
                            if 'Gate Flow' in struct_group:
                                gate_flow_data = struct_group['Gate Flow'][:]
                                if 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names' in plan_h:
                                    profile_names = plan_h['Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'][:]
                                    profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                   for p in profile_names]
                                    if profile in profile_names:
                                        prof_idx = profile_names.index(profile)
                                        if prof_idx < len(gate_flow_data):
                                            gate_flow = float(gate_flow_data[prof_idx])

                        # Determine flow type and generate message
                        flow_tolerance = 0.1  # cfs tolerance

                        has_weir_flow = abs(weir_flow) > flow_tolerance
                        has_gate_flow = abs(gate_flow) > flow_tolerance

                        if has_weir_flow and has_gate_flow:
                            # IW_TF_03: Combined flow
                            msg = CheckMessage(
                                message_id="IW_TF_03",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_03", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_03"),
                                value=weir_flow + gate_flow
                            )
                            messages.append(msg)
                        elif has_gate_flow and not has_weir_flow:
                            # IW_TF_02: Gate flow only
                            msg = CheckMessage(
                                message_id="IW_TF_02",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_02", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_02"),
                                value=gate_flow
                            )
                            messages.append(msg)
                        elif has_weir_flow and not has_gate_flow:
                            # IW_TF_01: Weir flow only
                            msg = CheckMessage(
                                message_id="IW_TF_01",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_01", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_01"),
                                value=weir_flow
                            )
                            messages.append(msg)
                        # If no flow at all, don't generate a message

                        # IW_TF_04: Check for tailwater submergence
                        if has_weir_flow and weir_path in plan_h:
                            struct_group = plan_h[weir_path]

                            # Get WSE data to check submergence
                            headwater_elev = None
                            tailwater_elev = None
                            crest_elev = None

                            # Try to get headwater/tailwater elevations
                            if 'HW Elev' in struct_group:
                                hw_data = struct_group['HW Elev'][:]
                                # Get profile-specific value
                                profile_names_path = 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'
                                alt_profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                                for ppath in [profile_names_path, alt_profile_path]:
                                    if ppath in plan_h:
                                        profile_names = plan_h[ppath][:]
                                        profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                       for p in profile_names]
                                        if profile in profile_names:
                                            prof_idx = profile_names.index(profile)
                                            if prof_idx < len(hw_data):
                                                headwater_elev = float(hw_data[prof_idx])
                                        break

                            if 'TW Elev' in struct_group:
                                tw_data = struct_group['TW Elev'][:]
                                for ppath in [profile_names_path, alt_profile_path]:
                                    if ppath in plan_h:
                                        profile_names = plan_h[ppath][:]
                                        profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                       for p in profile_names]
                                        if profile in profile_names:
                                            prof_idx = profile_names.index(profile)
                                            if prof_idx < len(tw_data):
                                                tailwater_elev = float(tw_data[prof_idx])
                                        break

                            # Try to get crest elevation from geometry
                            if 'Crest Elev' in struct_group.attrs:
                                crest_elev = float(struct_group.attrs['Crest Elev'])
                            elif 'Weir Crest' in attr_names:
                                crest_elev = float(attr['Weir Crest']) if 'Weir Crest' in attr_names else None

                            # Check for submergence condition
                            if tailwater_elev is not None and crest_elev is not None:
                                # Submergence occurs when TW approaches or exceeds crest
                                if tailwater_elev > crest_elev - 0.5:  # Within 0.5 ft of crest
                                    msg = CheckMessage(
                                        message_id="IW_TF_04",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=weir['river'],
                                        reach=weir['reach'],
                                        station=weir['station'],
                                        structure=weir['name'],
                                        message=format_message("IW_TF_04",
                                                              name=weir['name'],
                                                              tw_elev=tailwater_elev,
                                                              crest=crest_elev,
                                                              profile=profile),
                                        help_text=get_help_text("IW_TF_04"),
                                        value=tailwater_elev,
                                        threshold=crest_elev
                                    )
                                    messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check inline weir flow types: {e}")

        return messages

    @staticmethod
    def _check_bridge_flow_types(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check bridge flow types and classifications (BR_TF_*, BR_PF_*, BR_PW_*).

        Determines flow type for each bridge based on results:
        - BR_TF_01: Low flow Class A (free surface through bridge)
        - BR_TF_02: Low flow Class B (free surface with hydraulic jump DS)
        - BR_TF_03: Low flow Class C (supercritical through bridge)
        - BR_TF_04: High flow (pressure only)
        - BR_TF_05: High flow (weir only)
        - BR_TF_06: High flow (pressure and weir combined)
        - BR_PF_01: Pressure flow detected at bridge
        - BR_PF_02: Weir flow detected over bridge deck
        - BR_PF_03: Flow type for highest frequency profile differs from others
        - BR_PF_04: Pressure flow with Class B low flow (transitional conditions)
        - BR_PF_05: Submergence ratio indicates orifice flow (TW/HW ratio >= 0.8)
        - BR_PF_06: Tailwater controls pressure flow (TW near deck elevation)
        - BR_PF_07: Energy-based pressure flow method mismatch (non-Energy method with pressure)
        - BR_PF_08: Pressure flow coefficient outside typical range (0.8-1.0)
        - BR_PW_01: Sluice gate coefficients used for pressure flow
        - BR_PW_02: High flow method is not Energy (recommend Energy method)

        Bridge flow classification logic:
        - Class A: WSE below low chord both US and DS
        - Class B: WSE above low chord US, below DS (hydraulic jump downstream)
        - Class C: Supercritical flow through (rare)
        - Pressure: WSE above high chord (deck)
        - Weir: Roadway overtopping
        - Combined: Both pressure and weir flow

        Pressure flow checks (BR_PF_04-08):
        - BR_PF_04 detects transitional Class B + pressure flow conditions
        - BR_PF_05 checks submergence ratio for orifice vs sluice gate flow
        - BR_PF_06 warns when tailwater controls the pressure flow
        - BR_PF_07 recommends Energy method for pressure flow computations
        - BR_PF_08 validates pressure flow coefficient against typical range

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for bridge flow type observations
        """
        messages = []

        # First, do geometry-only checks (BR_PW_01, BR_PW_02)
        try:
            with h5py.File(geom_hdf, 'r') as geom_h:
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Collect bridge information
                bridges = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else str(attr.get('Node Name', f'BR_{station}'))

                    # Get bridge-specific attributes
                    low_chord = float(attr['Low Chord']) if 'Low Chord' in attr_names else 0
                    high_chord = float(attr['High Chord']) if 'High Chord' in attr_names else 0
                    deck_elev = float(attr['Deck/Roadway']) if 'Deck/Roadway' in attr_names else high_chord
                    weir_coef = float(attr['Weir Coef']) if 'Weir Coef' in attr_names else 0

                    # Check for sluice gate coefficient (BR_PW_01)
                    sluice_coef = float(attr['Sluice Gate Coef']) if 'Sluice Gate Coef' in attr_names else 0
                    if sluice_coef > 0:
                        msg = CheckMessage(
                            message_id="BR_PW_01",
                            severity=Severity.INFO,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("BR_PW_01", cd=f"{sluice_coef:.2f}"),
                            help_text=get_help_text("BR_PW_01"),
                            value=sluice_coef
                        )
                        messages.append(msg)

                    # BR_LW_02: Check bridge weir coefficient
                    if weir_coef > 0:
                        if weir_coef < 2.5 or weir_coef > 3.1:
                            msg = CheckMessage(
                                message_id="BR_LW_02",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("BR_LW_02", coef=weir_coef, name=name),
                                help_text=get_help_text("BR_LW_02"),
                                value=weir_coef
                            )
                            messages.append(msg)

                    # BR_LW_01: Check lateral weir length vs roadway width
                    weir_length = float(attr['Weir Length']) if 'Weir Length' in attr_names else 0
                    roadway_width = 0
                    if 'Roadway Left Sta' in attr_names and 'Roadway Right Sta' in attr_names:
                        roadway_left = float(attr['Roadway Left Sta'])
                        roadway_right = float(attr['Roadway Right Sta'])
                        roadway_width = abs(roadway_right - roadway_left)
                    elif 'BR US Left Bank' in attr_names and 'BR US Right Bank' in attr_names:
                        # Use abutment stations as proxy for roadway width
                        left_abut = float(attr['BR US Left Bank'])
                        right_abut = float(attr['BR US Right Bank'])
                        roadway_width = abs(right_abut - left_abut) if right_abut > left_abut else 0

                    if weir_length > 0 and roadway_width > 0:
                        # Flag if weir length differs from roadway width by more than 50%
                        diff_pct = abs(weir_length - roadway_width) / roadway_width * 100
                        if diff_pct > 50:
                            msg = CheckMessage(
                                message_id="BR_LW_01",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("BR_LW_01", length=weir_length, roadway=roadway_width),
                                help_text=get_help_text("BR_LW_01"),
                                value=weir_length,
                                threshold=roadway_width
                            )
                            messages.append(msg)

                    # Check for high flow method (BR_PW_02)
                    high_flow_method = attr['High Flow Method'] if 'High Flow Method' in attr_names else None
                    if high_flow_method is not None:
                        if isinstance(high_flow_method, bytes):
                            high_flow_method = high_flow_method.decode('utf-8').strip()
                        else:
                            high_flow_method = str(high_flow_method).strip()

                        # Check if it's not Energy method (0 = Energy, 1 = Momentum, etc.)
                        try:
                            hf_method_int = int(high_flow_method)
                            if hf_method_int != 0:  # Not Energy method
                                msg = CheckMessage(
                                    message_id="BR_PW_02",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=get_message_template("BR_PW_02"),
                                    help_text=get_help_text("BR_PW_02")
                                )
                                messages.append(msg)
                        except (ValueError, TypeError):
                            pass

                    # Store high flow method value for BR_PF_07 check
                    high_flow_method_value = None
                    if high_flow_method is not None:
                        try:
                            high_flow_method_value = int(high_flow_method) if not isinstance(high_flow_method, str) else int(high_flow_method)
                        except (ValueError, TypeError):
                            high_flow_method_value = high_flow_method

                    bridges.append({
                        'index': i,
                        'river': river,
                        'reach': reach,
                        'station': station,
                        'name': name,
                        'low_chord': low_chord,
                        'high_chord': high_chord,
                        'deck_elev': deck_elev,
                        'weir_coef': weir_coef,
                        'sluice_coef': sluice_coef,
                        'high_flow_method': high_flow_method_value
                    })

        except Exception as e:
            logger.warning(f"Could not read bridge attributes for flow type check: {e}")
            return messages

        if not bridges:
            return messages

        # Now check results-based flow types (BR_TF_*, BR_PF_*)
        if plan_hdf is None or not plan_hdf.exists():
            return messages

        try:
            with h5py.File(plan_hdf, 'r') as plan_h:
                # Check for steady results
                if 'Results/Steady' not in plan_h:
                    return messages

                # Get profile names
                profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                alt_profile_path = 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'

                available_profiles = []
                for ppath in [profile_path, alt_profile_path]:
                    if ppath in plan_h:
                        profile_names = plan_h[ppath][:]
                        available_profiles = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                             for p in profile_names]
                        break

                if not available_profiles:
                    return messages

                # Try to get structure output data
                struct_output_base = None
                for base in ['Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Structure Output',
                            'Results/Steady/Output/Output Blocks/Steady Profiles/Structure Output',
                            'Results/Steady/Structures']:
                    if base in plan_h:
                        struct_output_base = base
                        break

                # Track flow types per bridge for BR_PF_03 check
                bridge_flow_types = {}  # bridge_key -> {profile: flow_type}

                for bridge in bridges:
                    bridge_key = (bridge['river'], bridge['reach'], bridge['station'])
                    bridge_flow_types[bridge_key] = {}

                    for profile in profiles:
                        if profile not in available_profiles:
                            continue

                        prof_idx = available_profiles.index(profile)

                        # Initialize flow type detection
                        us_wse = None
                        ds_wse = None
                        pressure_flow = 0.0
                        weir_flow = 0.0
                        froude_us = None

                        # Try to get structure-specific output
                        if struct_output_base:
                            struct_name = bridge['name']
                            struct_path = f"{struct_output_base}/{struct_name}"

                            if struct_path in plan_h:
                                struct_data = plan_h[struct_path]

                                # Get pressure flow
                                if 'Pressure Flow' in struct_data:
                                    pf_data = struct_data['Pressure Flow'][:]
                                    if prof_idx < len(pf_data):
                                        pressure_flow = float(pf_data[prof_idx])

                                # Get weir flow
                                if 'Weir Flow' in struct_data:
                                    wf_data = struct_data['Weir Flow'][:]
                                    if prof_idx < len(wf_data):
                                        weir_flow = float(wf_data[prof_idx])

                                # Get US/DS WSE if available
                                if 'US WSE' in struct_data:
                                    us_wse_data = struct_data['US WSE'][:]
                                    if prof_idx < len(us_wse_data):
                                        us_wse = float(us_wse_data[prof_idx])

                                if 'DS WSE' in struct_data:
                                    ds_wse_data = struct_data['DS WSE'][:]
                                    if prof_idx < len(ds_wse_data):
                                        ds_wse = float(ds_wse_data[prof_idx])

                        # Classify flow type
                        flow_tolerance = 0.1  # cfs tolerance
                        has_pressure_flow = abs(pressure_flow) > flow_tolerance
                        has_weir_flow = abs(weir_flow) > flow_tolerance

                        low_chord = bridge['low_chord']

                        # Determine flow type
                        flow_type = None
                        msg_id = None
                        severity = Severity.INFO

                        if has_pressure_flow and has_weir_flow:
                            # BR_TF_06: High flow (pressure and weir combined)
                            flow_type = "pressure_weir"
                            msg_id = "BR_TF_06"
                            severity = Severity.WARNING
                        elif has_pressure_flow and not has_weir_flow:
                            # BR_TF_04: High flow (pressure only)
                            flow_type = "pressure"
                            msg_id = "BR_TF_04"
                            severity = Severity.WARNING
                        elif has_weir_flow and not has_pressure_flow:
                            # BR_TF_05: High flow (weir only)
                            flow_type = "weir"
                            msg_id = "BR_TF_05"
                            severity = Severity.INFO
                        elif us_wse is not None and ds_wse is not None and low_chord > 0:
                            # Low flow classification based on WSE vs low chord
                            us_below_low_chord = us_wse < low_chord
                            ds_below_low_chord = ds_wse < low_chord

                            if us_below_low_chord and ds_below_low_chord:
                                # BR_TF_01: Class A - free surface both sides
                                flow_type = "class_a"
                                msg_id = "BR_TF_01"
                                severity = Severity.INFO
                            elif not us_below_low_chord and ds_below_low_chord:
                                # BR_TF_02: Class B - hydraulic jump downstream
                                flow_type = "class_b"
                                msg_id = "BR_TF_02"
                                severity = Severity.WARNING
                            elif froude_us is not None and froude_us > 1.0:
                                # BR_TF_03: Class C - supercritical
                                flow_type = "class_c"
                                msg_id = "BR_TF_03"
                                severity = Severity.WARNING
                            else:
                                # Default to Class A for low flow without enough info
                                flow_type = "class_a"
                                msg_id = "BR_TF_01"
                                severity = Severity.INFO
                        else:
                            # Not enough data to classify - skip this profile
                            continue

                        # Store flow type for BR_PF_03 check
                        bridge_flow_types[bridge_key][profile] = flow_type

                        # Generate message for this bridge/profile
                        if msg_id:
                            msg = CheckMessage(
                                message_id=msg_id,
                                severity=severity,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message(msg_id, profile=profile),
                                help_text=get_help_text(msg_id)
                            )
                            messages.append(msg)

                        # BR_PF_01: Pressure flow detected
                        if has_pressure_flow:
                            msg = CheckMessage(
                                message_id="BR_PF_01",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_01", profile=profile),
                                help_text=get_help_text("BR_PF_01"),
                                value=pressure_flow
                            )
                            messages.append(msg)

                        # BR_PF_02: Weir flow detected
                        if has_weir_flow:
                            msg = CheckMessage(
                                message_id="BR_PF_02",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_02", profile=profile),
                                help_text=get_help_text("BR_PF_02"),
                                value=weir_flow
                            )
                            messages.append(msg)

                        # BR_PF_04: Pressure flow with Class B low flow
                        # Class B is when US WSE > low chord but DS WSE < low chord
                        if has_pressure_flow and flow_type == "class_b":
                            msg = CheckMessage(
                                message_id="BR_PF_04",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_04", profile=profile),
                                help_text=get_help_text("BR_PF_04")
                            )
                            messages.append(msg)

                        # BR_PF_05, BR_PF_06: Submergence and tailwater control checks
                        # These require both US and DS WSE data plus deck elevation
                        deck_elev = bridge['deck_elev']
                        high_chord = bridge['high_chord']
                        effective_deck = deck_elev if deck_elev > 0 else high_chord

                        if has_pressure_flow and us_wse is not None and ds_wse is not None and effective_deck > 0:
                            # Calculate submergence ratio for orifice flow check
                            # Submergence = (TW depth above deck) / (HW depth above deck)
                            hw_depth_above_deck = us_wse - effective_deck
                            tw_depth_above_deck = ds_wse - effective_deck

                            if hw_depth_above_deck > 0:
                                submergence_ratio = tw_depth_above_deck / hw_depth_above_deck if tw_depth_above_deck > 0 else 0

                                # BR_PF_05: Submergence ratio indicates orifice flow
                                if submergence_ratio >= thresholds.structures.orifice_flow_submergence_ratio:
                                    msg = CheckMessage(
                                        message_id="BR_PF_05",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=bridge['river'],
                                        reach=bridge['reach'],
                                        station=bridge['station'],
                                        structure=bridge['name'],
                                        message=format_message("BR_PF_05", submergence=submergence_ratio, profile=profile),
                                        help_text=get_help_text("BR_PF_05"),
                                        value=submergence_ratio,
                                        threshold=thresholds.structures.orifice_flow_submergence_ratio
                                    )
                                    messages.append(msg)

                            # BR_PF_06: Tailwater controls pressure flow
                            # When TW approaches or exceeds deck elevation
                            tw_control_threshold = effective_deck - thresholds.structures.tailwater_control_tolerance_ft
                            if ds_wse >= tw_control_threshold:
                                msg = CheckMessage(
                                    message_id="BR_PF_06",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=bridge['river'],
                                    reach=bridge['reach'],
                                    station=bridge['station'],
                                    structure=bridge['name'],
                                    message=format_message("BR_PF_06", tw_elev=ds_wse, deck_elev=effective_deck, profile=profile),
                                    help_text=get_help_text("BR_PF_06"),
                                    value=ds_wse,
                                    threshold=tw_control_threshold
                                )
                                messages.append(msg)

                        # BR_PF_07: Energy-based pressure flow method mismatch
                        # When pressure flow occurs, check if energy method is used
                        if has_pressure_flow and bridge.get('high_flow_method') is not None:
                            hf_method = bridge.get('high_flow_method')
                            # 0 = Energy, non-zero = other methods (Momentum, etc.)
                            if hf_method != 0 and hf_method != '0':
                                method_names = {
                                    1: 'Momentum', '1': 'Momentum',
                                    2: 'Yarnell', '2': 'Yarnell',
                                    3: 'WSPRO', '3': 'WSPRO'
                                }
                                method_name = method_names.get(hf_method, str(hf_method))
                                msg = CheckMessage(
                                    message_id="BR_PF_07",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=bridge['river'],
                                    reach=bridge['reach'],
                                    station=bridge['station'],
                                    structure=bridge['name'],
                                    message=format_message("BR_PF_07", method=method_name, profile=profile),
                                    help_text=get_help_text("BR_PF_07")
                                )
                                messages.append(msg)

                        # BR_PF_08: Pressure flow coefficient outside typical range
                        # Check the sluice gate coefficient (pressure flow Cd)
                        if has_pressure_flow and bridge.get('sluice_coef') is not None:
                            sluice_coef = bridge.get('sluice_coef', 0)
                            if sluice_coef > 0:
                                pf_coef_min = thresholds.structures.pressure_flow_coef_min
                                pf_coef_max = thresholds.structures.pressure_flow_coef_max
                                if sluice_coef < pf_coef_min or sluice_coef > pf_coef_max:
                                    msg = CheckMessage(
                                        message_id="BR_PF_08",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=bridge['river'],
                                        reach=bridge['reach'],
                                        station=bridge['station'],
                                        structure=bridge['name'],
                                        message=format_message("BR_PF_08", coef=sluice_coef, profile=profile),
                                        help_text=get_help_text("BR_PF_08"),
                                        value=sluice_coef,
                                        threshold=pf_coef_min  # Use min as reference
                                    )
                                    messages.append(msg)

                # BR_PF_03: Check if highest frequency profile differs from others
                for bridge_key, profile_types in bridge_flow_types.items():
                    if len(profile_types) < 2:
                        continue

                    # Find the highest frequency profile (typically first in list)
                    sorted_profiles = [p for p in profiles if p in profile_types]
                    if len(sorted_profiles) < 2:
                        continue

                    highest_freq_profile = sorted_profiles[0]
                    highest_freq_type = profile_types.get(highest_freq_profile)

                    # Check if any other profile has a different type
                    different_types = [p for p in sorted_profiles[1:]
                                      if profile_types.get(p) != highest_freq_type]

                    if different_types and highest_freq_type:
                        # Find the bridge info
                        bridge_info = next((b for b in bridges
                                           if (b['river'], b['reach'], b['station']) == bridge_key), None)
                        if bridge_info:
                            msg = CheckMessage(
                                message_id="BR_PF_03",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=bridge_info['river'],
                                reach=bridge_info['reach'],
                                station=bridge_info['station'],
                                structure=bridge_info['name'],
                                message=format_message("BR_PF_03", flow_type=highest_freq_type),
                                help_text=get_help_text("BR_PF_03")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check bridge flow types from results: {e}")

        return messages

    # =========================================================================
    # Structure Distance and Geometry Checks
    # =========================================================================

    @staticmethod
    def _check_structure_distances(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check upstream/downstream distances at structures (ST_DT_* checks).

        Validates:
        - ST_DT_01: Upstream distance too short for flow expansion
        - ST_DT_02: Downstream distance too short for contraction recovery

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for structure distance issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else station

                    # Get distances
                    us_dist = float(attr['Upstream Distance']) if 'Upstream Distance' in attr_names else 0
                    ds_dist = float(attr['Downstream Distance']) if 'Downstream Distance' in attr_names else 0

                    # Get opening width for ratio check (if available)
                    opening_width = 0
                    if 'Bridge' in struct_type:
                        # For bridges, use abutment stations
                        left_abut = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr_names else 0
                        right_abut = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr_names else 0
                        if left_abut > 0 and right_abut > 0:
                            opening_width = abs(right_abut - left_abut)

                    # Determine minimum distance thresholds
                    # Rule of thumb: US distance should be 1x expansion length (min 50 ft for bridges)
                    # DS distance should be 2x contraction length (min 100 ft)
                    if 'Bridge' in struct_type:
                        min_us = max(50, opening_width * 1.0) if opening_width > 0 else 50
                        min_ds = max(30, opening_width * 0.5) if opening_width > 0 else 30
                    elif 'Culvert' in struct_type:
                        min_us = 30
                        min_ds = 20
                    elif 'Inline' in struct_type or 'Weir' in struct_type:
                        min_us = 20
                        min_ds = 20
                    else:
                        continue  # Unknown structure type

                    # ST_DT_01: Check upstream distance
                    if us_dist > 0 and us_dist < min_us:
                        msg = CheckMessage(
                            message_id="ST_DT_01",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_DT_01", dist=f"{us_dist:.1f}", name=name),
                            help_text=get_help_text("ST_DT_01"),
                            value=us_dist,
                            threshold=min_us
                        )
                        messages.append(msg)

                    # ST_DT_02: Check downstream distance
                    if ds_dist > 0 and ds_dist < min_ds:
                        msg = CheckMessage(
                            message_id="ST_DT_02",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_DT_02", dist=f"{ds_dist:.1f}", name=name),
                            help_text=get_help_text("ST_DT_02"),
                            value=ds_dist,
                            threshold=min_ds
                        )
                        messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure distances: {e}")

        return messages

    @staticmethod
    def _check_structure_ineffective_section3(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure ineffective flow at Section 3 (ST_IF_04L/R checks).

        Validates that ineffective flow areas extend to abutments at Section 3
        (downstream face of bridge).

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for Section 3 ineffective flow issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Only check bridges (have abutments)
                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get downstream ineffective flow stations (Section 3)
                    ds_ineff_left_sta = float(attr['DS Ineff Left Sta']) if 'DS Ineff Left Sta' in attr_names else 0
                    ds_ineff_right_sta = float(attr['DS Ineff Right Sta']) if 'DS Ineff Right Sta' in attr_names else 0

                    # Get downstream bank stations (abutments)
                    br_ds_left_bank = float(attr['BR DS Left Bank']) if 'BR DS Left Bank' in attr_names else 0
                    br_ds_right_bank = float(attr['BR DS Right Bank']) if 'BR DS Right Bank' in attr_names else 0

                    tolerance = 5.0  # 5 ft tolerance

                    # ST_IF_04L: Left ineffective should extend to left abutment
                    if ds_ineff_left_sta > 0 and br_ds_left_bank > 0:
                        # Left ineffective right station should be near left abutment
                        if ds_ineff_right_sta < br_ds_left_bank - tolerance:
                            msg = CheckMessage(
                                message_id="ST_IF_04L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_IF_04L"),
                                help_text=get_help_text("ST_IF_04L")
                            )
                            messages.append(msg)

                    # ST_IF_04R: Right ineffective should extend to right abutment
                    if ds_ineff_right_sta > 0 and br_ds_right_bank > 0:
                        # Right ineffective left station should be near right abutment
                        if ds_ineff_left_sta > br_ds_right_bank + tolerance:
                            msg = CheckMessage(
                                message_id="ST_IF_04R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_IF_04R"),
                                help_text=get_help_text("ST_IF_04R")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check Section 3 ineffective flow: {e}")

        return messages

    @staticmethod
    def _check_structure_permanent_ineffective(
        geom_hdf: Path,
        is_floodway: bool = False
    ) -> List[CheckMessage]:
        """
        Check for permanent ineffective flow at structures (ST_IF_05).

        Permanent ineffective flow may be problematic in floodway analysis.

        Args:
            geom_hdf: Path to geometry HDF file
            is_floodway: True if this is a floodway analysis

        Returns:
            List of CheckMessage objects for permanent ineffective flow issues
        """
        messages = []

        if not is_floodway:
            return messages  # Only check in floodway context

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Check for permanent ineffective flags
                    us_ineff_perm = False
                    ds_ineff_perm = False

                    if 'US Ineff Permanent' in attr_names:
                        us_ineff_perm = bool(attr['US Ineff Permanent'])
                    if 'DS Ineff Permanent' in attr_names:
                        ds_ineff_perm = bool(attr['DS Ineff Permanent'])

                    if us_ineff_perm or ds_ineff_perm:
                        msg = CheckMessage(
                            message_id="ST_IF_05",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            message=get_message_template("ST_IF_05"),
                            help_text=get_help_text("ST_IF_05")
                        )
                        messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check permanent ineffective flow: {e}")

        return messages

    @staticmethod
    def _check_structure_geometry_alignment(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure geometry alignment (ST_GE_02L/R, ST_GE_03 checks).

        Validates:
        - ST_GE_02L/R: Section 3 effective stations align with roadway
        - ST_GE_03: Ground/roadway station differences

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for geometry alignment issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get Section 3 bank stations
                    br_ds_left_bank = float(attr['BR DS Left Bank']) if 'BR DS Left Bank' in attr_names else 0
                    br_ds_right_bank = float(attr['BR DS Right Bank']) if 'BR DS Right Bank' in attr_names else 0

                    # Get XS bank stations for comparison
                    xs_ds_left_bank = float(attr['XS DS Left Bank']) if 'XS DS Left Bank' in attr_names else 0
                    xs_ds_right_bank = float(attr['XS DS Right Bank']) if 'XS DS Right Bank' in attr_names else 0

                    tolerance = 50.0  # 50 ft tolerance

                    # ST_GE_02L: Left bank alignment at Section 3
                    if br_ds_left_bank > 0 and xs_ds_left_bank > 0:
                        if abs(br_ds_left_bank - xs_ds_left_bank) > tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_02L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_02L"),
                                help_text=get_help_text("ST_GE_02L")
                            )
                            messages.append(msg)

                    # ST_GE_02R: Right bank alignment at Section 3
                    if br_ds_right_bank > 0 and xs_ds_right_bank > 0:
                        if abs(br_ds_right_bank - xs_ds_right_bank) > tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_02R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_02R"),
                                help_text=get_help_text("ST_GE_02R")
                            )
                            messages.append(msg)

                    # ST_GE_03: Ground/roadway station difference
                    # Check if roadway extends significantly beyond ground
                    roadway_left = float(attr['Roadway Left Sta']) if 'Roadway Left Sta' in attr_names else 0
                    roadway_right = float(attr['Roadway Right Sta']) if 'Roadway Right Sta' in attr_names else 0
                    ground_left = float(attr['Ground Left Sta']) if 'Ground Left Sta' in attr_names else 0
                    ground_right = float(attr['Ground Right Sta']) if 'Ground Right Sta' in attr_names else 0

                    roadway_tolerance = 10.0  # 10 ft tolerance

                    if roadway_left > 0 and ground_left > 0:
                        if abs(roadway_left - ground_left) > roadway_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_03"),
                                help_text=get_help_text("ST_GE_03")
                            )
                            messages.append(msg)
                    elif roadway_right > 0 and ground_right > 0:
                        if abs(roadway_right - ground_right) > roadway_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_03"),
                                help_text=get_help_text("ST_GE_03")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure geometry alignment: {e}")

        return messages

    @staticmethod
    def _check_structure_ground(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure ground/terrain data validity (ST_GD_* checks).

        Validates:
        - ST_GD_01: Ground data missing at structure
        - ST_GD_02: Ground elevation discontinuity at structure
        - ST_GD_03L/R: Left/Right ground below structure invert
        - ST_GD_04L/R: Left/Right ground above structure deck
        - ST_GD_05: Ground slope exceeds threshold at structure
        - ST_GD_06: Ground data inconsistent between approach sections
        - ST_GD_07: Approach section ground doesn't match structure
        - ST_GD_08: Pier ground elevation issues
        - ST_GD_09: Abutment ground elevation issues
        - ST_GD_10: Embankment slope too steep
        - ST_GD_11: Fill depth exceeds reasonable limit

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for structure ground data issues
        """
        messages = []

        # Threshold values for ground checks
        ground_elev_tolerance = 2.0  # ft - tolerance for ground/structure elevation comparison
        ground_discontinuity_threshold = 5.0  # ft - max acceptable discontinuity
        ground_slope_threshold = 0.1  # ft/ft - 10% slope threshold
        embankment_slope_threshold = 1.5  # H:V - steeper than 1.5:1 is unusual
        fill_depth_threshold = 30.0  # ft - max reasonable fill depth

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Get cross section data for approach section comparisons
                xs_attrs = None
                xs_sta_elev_info = None
                xs_sta_elev_values = None
                if 'Geometry/Cross Sections/Attributes' in hdf:
                    xs_attrs = hdf['Geometry/Cross Sections/Attributes'][:]
                if 'Geometry/Cross Sections/Station Elevation Info' in hdf:
                    xs_sta_elev_info = hdf['Geometry/Cross Sections/Station Elevation Info'][:]
                if 'Geometry/Cross Sections/Station Elevation Values' in hdf:
                    xs_sta_elev_values = hdf['Geometry/Cross Sections/Station Elevation Values'][:]

                # Check for structure ground data
                struct_ground_data = None
                struct_ground_info = None
                if 'Geometry/Structures/Ground Data' in hdf:
                    struct_ground_data = hdf['Geometry/Structures/Ground Data'][:]
                if 'Geometry/Structures/Ground Info' in hdf:
                    struct_ground_info = hdf['Geometry/Structures/Ground Info'][:]

                # Check deck/roadway data
                deck_data = None
                deck_info = None
                if 'Geometry/Structures/Deck Data' in hdf:
                    deck_data = hdf['Geometry/Structures/Deck Data'][:]
                if 'Geometry/Structures/Deck Info' in hdf or 'Geometry/Structures/Table Info' in hdf:
                    deck_info = hdf.get('Geometry/Structures/Deck Info', hdf.get('Geometry/Structures/Table Info', None))
                    if deck_info is not None:
                        deck_info = deck_info[:]

                # Check pier data
                pier_data = None
                pier_info = None
                if 'Geometry/Structures/Pier Data' in hdf:
                    pier_data = hdf['Geometry/Structures/Pier Data'][:]
                if 'Geometry/Structures/Pier Info' in hdf:
                    pier_info = hdf['Geometry/Structures/Pier Info'][:]

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else station

                    # Get approach section RS values
                    us_rs = attr['US RS'].decode('utf-8').strip() if 'US RS' in attr_names and isinstance(attr['US RS'], bytes) else ''
                    ds_rs = attr['DS RS'].decode('utf-8').strip() if 'DS RS' in attr_names and isinstance(attr['DS RS'], bytes) else ''

                    # ST_GD_01: Check if ground data exists for this structure
                    has_ground_data = False
                    struct_ground_pts = []

                    if struct_ground_data is not None and struct_ground_info is not None and i < len(struct_ground_info):
                        try:
                            info = struct_ground_info[i]
                            # Info typically contains (start_index, count) or similar
                            if hasattr(info, '__len__') and len(info) >= 2:
                                start_idx = int(info[0])
                                count = int(info[1])
                                if count > 0:
                                    has_ground_data = True
                                    for j in range(count):
                                        if start_idx + j < len(struct_ground_data):
                                            pt = struct_ground_data[start_idx + j]
                                            sta = float(pt[0]) if len(pt) > 0 else 0
                                            elev = float(pt[1]) if len(pt) > 1 else 0
                                            struct_ground_pts.append((sta, elev))
                        except (IndexError, TypeError, ValueError):
                            pass

                    if not has_ground_data and 'Bridge' in struct_type:
                        # Only warn for bridges - culverts may not have explicit ground data
                        msg = CheckMessage(
                            message_id="ST_GD_01",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_GD_01", name=name),
                            help_text=get_help_text("ST_GD_01")
                        )
                        messages.append(msg)
                        continue  # Skip other ground checks if no ground data

                    if not struct_ground_pts:
                        continue

                    # Get structure geometry for comparison
                    # For bridges: get invert (low chord) and deck (high chord) elevations
                    invert_elev = None
                    deck_elev = None
                    left_abut_sta = None
                    right_abut_sta = None

                    if 'Bridge' in struct_type:
                        # Get deck/roadway data
                        if deck_data is not None and deck_info is not None and i < len(deck_info):
                            try:
                                d_info = deck_info[i]
                                deck_elevs = []
                                if hasattr(d_info, '__len__'):
                                    # Try to extract deck elevations
                                    if 'Deck High Chord (Index)' in d_info.dtype.names:
                                        hc_idx = int(d_info['Deck High Chord (Index)'])
                                        hc_cnt = int(d_info['Deck High Chord (Count)']) if 'Deck High Chord (Count)' in d_info.dtype.names else 0
                                        for j in range(hc_cnt):
                                            if hc_idx + j < len(deck_data):
                                                deck_elevs.append(float(deck_data[hc_idx + j][1]))
                                if deck_elevs:
                                    deck_elev = max(deck_elevs)
                            except (IndexError, TypeError, ValueError, KeyError):
                                pass

                        # Get low chord / invert elevation
                        if 'BR US Low Chord' in attr_names:
                            try:
                                invert_elev = float(attr['BR US Low Chord'])
                            except (TypeError, ValueError):
                                pass

                        # Get abutment stations
                        if 'BR US Left Bank' in attr_names:
                            try:
                                left_abut_sta = float(attr['BR US Left Bank'])
                            except (TypeError, ValueError):
                                pass
                        if 'BR US Right Bank' in attr_names:
                            try:
                                right_abut_sta = float(attr['BR US Right Bank'])
                            except (TypeError, ValueError):
                                pass

                    elif 'Culvert' in struct_type:
                        # For culverts, get invert from structure attributes
                        if 'US Invert' in attr_names:
                            try:
                                invert_elev = float(attr['US Invert'])
                            except (TypeError, ValueError):
                                pass

                    # Get ground elevations at key locations
                    left_ground_elev = struct_ground_pts[0][1] if struct_ground_pts else None
                    right_ground_elev = struct_ground_pts[-1][1] if struct_ground_pts else None

                    # Calculate min/max ground elevations in the channel area
                    channel_ground_min = None
                    channel_ground_max = None
                    if struct_ground_pts and left_abut_sta is not None and right_abut_sta is not None:
                        channel_pts = [(s, e) for s, e in struct_ground_pts if left_abut_sta <= s <= right_abut_sta]
                        if channel_pts:
                            channel_ground_min = min(e for _, e in channel_pts)
                            channel_ground_max = max(e for _, e in channel_pts)

                    # ST_GD_02: Ground elevation discontinuity
                    # Check for large elevation difference between US and DS ground
                    us_ground_elev = None
                    ds_ground_elev = None
                    if xs_attrs is not None and xs_sta_elev_values is not None and xs_sta_elev_info is not None:
                        # Find approach section elevations
                        for j, xs in enumerate(xs_attrs):
                            xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()
                            if xs_rs == us_rs or xs_rs == ds_rs:
                                try:
                                    info = xs_sta_elev_info[j]
                                    start_idx = int(info[0])
                                    count = int(info[1])
                                    if count > 0:
                                        # Get min elevation (channel thalweg)
                                        elevs = []
                                        for k in range(count):
                                            if start_idx + k < len(xs_sta_elev_values):
                                                elevs.append(float(xs_sta_elev_values[start_idx + k][1]))
                                        if elevs:
                                            if xs_rs == us_rs:
                                                us_ground_elev = min(elevs)
                                            else:
                                                ds_ground_elev = min(elevs)
                                except (IndexError, TypeError, ValueError):
                                    pass

                    if us_ground_elev is not None and ds_ground_elev is not None:
                        elev_diff = abs(us_ground_elev - ds_ground_elev)
                        if elev_diff > ground_discontinuity_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_02",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_02", diff=elev_diff, name=name),
                                help_text=get_help_text("ST_GD_02"),
                                value=elev_diff,
                                threshold=ground_discontinuity_threshold
                            )
                            messages.append(msg)

                    # ST_GD_02BU/BD: Bridge deck elevation check at upstream/downstream faces
                    # Compare deck elevations with approach XS ground at deck station locations
                    if 'Bridge' in struct_type and deck_data is not None and deck_info is not None and i < len(deck_info):
                        try:
                            d_info = deck_info[i]

                            # Get deck high chord (top of deck) station-elevation pairs
                            us_deck_sta_elev = []
                            ds_deck_sta_elev = []

                            if hasattr(d_info, 'dtype') and d_info.dtype.names is not None:
                                # Extract upstream deck profile (US high chord)
                                if 'Deck US High Chord (Index)' in d_info.dtype.names:
                                    us_hc_idx = int(d_info['Deck US High Chord (Index)'])
                                    us_hc_cnt = int(d_info['Deck US High Chord (Count)']) if 'Deck US High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(us_hc_cnt):
                                        if us_hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[us_hc_idx + dk][0])
                                            elev = float(deck_data[us_hc_idx + dk][1])
                                            us_deck_sta_elev.append((sta, elev))
                                elif 'Deck High Chord (Index)' in d_info.dtype.names:
                                    # Fallback: use generic high chord for both US and DS
                                    hc_idx = int(d_info['Deck High Chord (Index)'])
                                    hc_cnt = int(d_info['Deck High Chord (Count)']) if 'Deck High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(hc_cnt):
                                        if hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[hc_idx + dk][0])
                                            elev = float(deck_data[hc_idx + dk][1])
                                            us_deck_sta_elev.append((sta, elev))
                                            ds_deck_sta_elev.append((sta, elev))

                                # Extract downstream deck profile (DS high chord)
                                if 'Deck DS High Chord (Index)' in d_info.dtype.names:
                                    ds_hc_idx = int(d_info['Deck DS High Chord (Index)'])
                                    ds_hc_cnt = int(d_info['Deck DS High Chord (Count)']) if 'Deck DS High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(ds_hc_cnt):
                                        if ds_hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[ds_hc_idx + dk][0])
                                            elev = float(deck_data[ds_hc_idx + dk][1])
                                            ds_deck_sta_elev.append((sta, elev))

                            # Get upstream approach XS station-elevation data
                            us_xs_sta_elev = []
                            ds_xs_sta_elev = []
                            if xs_attrs is not None and xs_sta_elev_values is not None and xs_sta_elev_info is not None:
                                for j, xs in enumerate(xs_attrs):
                                    xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()
                                    if xs_rs == us_rs or xs_rs == ds_rs:
                                        try:
                                            info = xs_sta_elev_info[j]
                                            start_idx = int(info[0])
                                            count = int(info[1])
                                            if count > 0:
                                                xs_pts = []
                                                for k in range(count):
                                                    if start_idx + k < len(xs_sta_elev_values):
                                                        sta = float(xs_sta_elev_values[start_idx + k][0])
                                                        elev = float(xs_sta_elev_values[start_idx + k][1])
                                                        xs_pts.append((sta, elev))
                                                if xs_rs == us_rs:
                                                    us_xs_sta_elev = xs_pts
                                                else:
                                                    ds_xs_sta_elev = xs_pts
                                        except (IndexError, TypeError, ValueError):
                                            pass

                            # Helper function to interpolate ground elevation at a station
                            def interpolate_ground_at_station(sta_elev_list, target_sta):
                                """Interpolate ground elevation at target station from XS data."""
                                if not sta_elev_list or len(sta_elev_list) < 2:
                                    return None
                                # Find bracketing points
                                for k in range(len(sta_elev_list) - 1):
                                    sta1, elev1 = sta_elev_list[k]
                                    sta2, elev2 = sta_elev_list[k + 1]
                                    if sta1 <= target_sta <= sta2:
                                        if (sta2 - sta1) > 0:
                                            t = (target_sta - sta1) / (sta2 - sta1)
                                            return elev1 + t * (elev2 - elev1)
                                        return elev1
                                # Check if target is outside range (extrapolate to nearest)
                                if target_sta < sta_elev_list[0][0]:
                                    return sta_elev_list[0][1]
                                if target_sta > sta_elev_list[-1][0]:
                                    return sta_elev_list[-1][1]
                                return None

                            # ST_GD_02BU: Check upstream deck vs Section 1 (US XS) ground
                            if us_deck_sta_elev and us_xs_sta_elev:
                                # Check deck elevation at abutment stations
                                for deck_sta, deck_el in us_deck_sta_elev:
                                    ground_el = interpolate_ground_at_station(us_xs_sta_elev, deck_sta)
                                    if ground_el is not None:
                                        # Deck should be above or at ground level
                                        diff = abs(deck_el - ground_el)
                                        if diff > ground_elev_tolerance and deck_el < ground_el:
                                            msg = CheckMessage(
                                                message_id="ST_GD_02BU",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_02BU", deck_elev=deck_el, ground_elev=ground_el, name=name),
                                                help_text=get_help_text("ST_GD_02BU"),
                                                value=diff,
                                                threshold=ground_elev_tolerance
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure

                            # ST_GD_02BD: Check downstream deck vs Section 4 (DS XS) ground
                            if ds_deck_sta_elev and ds_xs_sta_elev:
                                for deck_sta, deck_el in ds_deck_sta_elev:
                                    ground_el = interpolate_ground_at_station(ds_xs_sta_elev, deck_sta)
                                    if ground_el is not None:
                                        diff = abs(deck_el - ground_el)
                                        if diff > ground_elev_tolerance and deck_el < ground_el:
                                            msg = CheckMessage(
                                                message_id="ST_GD_02BD",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_02BD", deck_elev=deck_el, ground_elev=ground_el, name=name),
                                                help_text=get_help_text("ST_GD_02BD"),
                                                value=diff,
                                                threshold=ground_elev_tolerance
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure

                        except Exception as e:
                            logger.debug(f"Could not check deck elevation at bridge {name}: {e}")

                    # ST_GD_03L/R: Ground below structure invert
                    if invert_elev is not None:
                        if left_ground_elev is not None and left_ground_elev < invert_elev - ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_03L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_03L", ground_elev=left_ground_elev, invert_elev=invert_elev, name=name),
                                help_text=get_help_text("ST_GD_03L"),
                                value=left_ground_elev
                            )
                            messages.append(msg)

                        if right_ground_elev is not None and right_ground_elev < invert_elev - ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_03R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_03R", ground_elev=right_ground_elev, invert_elev=invert_elev, name=name),
                                help_text=get_help_text("ST_GD_03R"),
                                value=right_ground_elev
                            )
                            messages.append(msg)

                    # ST_GD_04L/R: Ground above structure deck (unusual but may be intentional)
                    if deck_elev is not None:
                        if left_ground_elev is not None and left_ground_elev > deck_elev + ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_04L",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_04L", ground_elev=left_ground_elev, deck_elev=deck_elev, name=name),
                                help_text=get_help_text("ST_GD_04L"),
                                value=left_ground_elev
                            )
                            messages.append(msg)

                        if right_ground_elev is not None and right_ground_elev > deck_elev + ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_04R",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_04R", ground_elev=right_ground_elev, deck_elev=deck_elev, name=name),
                                help_text=get_help_text("ST_GD_04R"),
                                value=right_ground_elev
                            )
                            messages.append(msg)

                    # ST_GD_05: Ground slope at structure
                    if len(struct_ground_pts) >= 2:
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if abs(sta2 - sta1) > 0.1:  # Avoid division by very small values
                                slope = abs(elev2 - elev1) / abs(sta2 - sta1)
                                if slope > ground_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_05",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_05", slope=slope, name=name),
                                        help_text=get_help_text("ST_GD_05"),
                                        value=slope,
                                        threshold=ground_slope_threshold
                                    )
                                    messages.append(msg)
                                    break  # Only report once per structure

                    # ST_GD_06: Ground data inconsistent between approach sections
                    if us_ground_elev is not None and ds_ground_elev is not None:
                        # Also check against structure ground
                        if channel_ground_min is not None:
                            if abs(us_ground_elev - channel_ground_min) > ground_discontinuity_threshold:
                                msg = CheckMessage(
                                    message_id="ST_GD_06",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=format_message("ST_GD_06", name=name, us_elev=us_ground_elev, ds_elev=ds_ground_elev),
                                    help_text=get_help_text("ST_GD_06")
                                )
                                messages.append(msg)

                    # ST_GD_07: Approach section ground doesn't match structure ground
                    if us_ground_elev is not None and channel_ground_min is not None:
                        diff = abs(us_ground_elev - channel_ground_min)
                        if diff > ground_discontinuity_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_07",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_07", xs_elev=us_ground_elev, struct_elev=channel_ground_min, name=name),
                                help_text=get_help_text("ST_GD_07"),
                                value=diff
                            )
                            messages.append(msg)

                    # ST_GD_08: Pier ground elevation issues
                    if pier_data is not None and pier_info is not None and i < len(pier_info) and 'Bridge' in struct_type:
                        try:
                            p_info = pier_info[i]
                            if hasattr(p_info, '__len__') and len(p_info) >= 2:
                                p_start = int(p_info[0])
                                p_count = int(p_info[1])
                                for pj in range(p_count):
                                    if p_start + pj < len(pier_data):
                                        pier_pt = pier_data[p_start + pj]
                                        pier_sta = float(pier_pt[0]) if len(pier_pt) > 0 else 0
                                        pier_elev = float(pier_pt[1]) if len(pier_pt) > 1 else 0
                                        # Check if pier is above channel ground
                                        if channel_ground_min is not None and pier_elev > channel_ground_min + ground_elev_tolerance:
                                            msg = CheckMessage(
                                                message_id="ST_GD_08",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_08", pier_elev=pier_elev, name=name, issue=f"above channel ground ({channel_ground_min:.2f} ft)"),
                                                help_text=get_help_text("ST_GD_08"),
                                                value=pier_elev
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure
                        except (IndexError, TypeError, ValueError):
                            pass

                    # ST_GD_09: Abutment ground elevation issues
                    if left_abut_sta is not None and struct_ground_pts:
                        # Find ground elevation at left abutment
                        left_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= left_abut_sta <= sta2:
                                # Linear interpolation
                                t = (left_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                left_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if left_abut_ground is not None:
                            # Abutment ground should be at or above channel ground
                            if channel_ground_min is not None and left_abut_ground < channel_ground_min - ground_elev_tolerance:
                                msg = CheckMessage(
                                    message_id="ST_GD_09",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=format_message("ST_GD_09", abut_elev=left_abut_ground, name=name, issue="left abutment below channel ground"),
                                    help_text=get_help_text("ST_GD_09"),
                                    value=left_abut_ground
                                )
                                messages.append(msg)

                    # ST_GD_10: Embankment slope too steep
                    # Check slope from channel edge to overbank ground
                    if left_abut_sta is not None and struct_ground_pts and len(struct_ground_pts) >= 2:
                        # Find ground at left edge and at abutment
                        left_edge = struct_ground_pts[0]
                        left_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= left_abut_sta <= sta2:
                                t = (left_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                left_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if left_abut_ground is not None and left_edge[0] < left_abut_sta:
                            horiz_dist = left_abut_sta - left_edge[0]
                            vert_dist = abs(left_abut_ground - left_edge[1])
                            if vert_dist > 0.1:  # Significant height difference
                                slope_hv = horiz_dist / vert_dist if vert_dist > 0 else float('inf')
                                if slope_hv < embankment_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_10",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_10", slope=slope_hv, name=name, side="left"),
                                        help_text=get_help_text("ST_GD_10"),
                                        value=slope_hv,
                                        threshold=embankment_slope_threshold
                                    )
                                    messages.append(msg)

                    # Similar check for right side
                    if right_abut_sta is not None and struct_ground_pts and len(struct_ground_pts) >= 2:
                        right_edge = struct_ground_pts[-1]
                        right_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= right_abut_sta <= sta2:
                                t = (right_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                right_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if right_abut_ground is not None and right_edge[0] > right_abut_sta:
                            horiz_dist = right_edge[0] - right_abut_sta
                            vert_dist = abs(right_edge[1] - right_abut_ground)
                            if vert_dist > 0.1:
                                slope_hv = horiz_dist / vert_dist if vert_dist > 0 else float('inf')
                                if slope_hv < embankment_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_10",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_10", slope=slope_hv, name=name, side="right"),
                                        help_text=get_help_text("ST_GD_10"),
                                        value=slope_hv,
                                        threshold=embankment_slope_threshold
                                    )
                                    messages.append(msg)

                    # ST_GD_11: Fill depth exceeds reasonable limit
                    if deck_elev is not None and channel_ground_min is not None:
                        fill_depth = deck_elev - channel_ground_min
                        if fill_depth > fill_depth_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_11",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_11", fill_depth=fill_depth, name=name),
                                help_text=get_help_text("ST_GD_11"),
                                value=fill_depth,
                                threshold=fill_depth_threshold
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure ground data: {e}")

        return messages

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
            matching = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan]
            if matching.empty:
                raise ValueError(f"Plan '{plan}' not found. Available: {ras_obj.plan_df['plan_number'].tolist()}")
            plan_row = matching.iloc[0]
            plan_hdf = Path(plan_row['HDF_Results_Path'])
            geom_path = plan_row['Geom Path']
            # Get geometry HDF from geometry file path
            geom_base = Path(str(geom_path))
            geom_hdf = geom_base.with_suffix('.hdf')
        else:
            plan_hdf = Path(plan)
            # Derive geometry HDF from plan HDF name
            # Pattern: project.p01.hdf -> project.g01.hdf
            plan_stem = plan_hdf.stem  # e.g., "project.p01"
            if '.p' in plan_stem:
                geom_stem = plan_stem.replace('.p', '.g', 1)
            else:
                geom_stem = plan_stem
            geom_hdf = plan_hdf.parent / f"{geom_stem}.hdf"

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

    # =========================================================================
    # Floodway Check Helper Methods
    # =========================================================================

    @staticmethod
    def _check_encroachment_data(
        plan_hdf: Path,
        geom_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check encroachment data from HDF files for floodway analysis.

        Validates:
        - FW_EM_01: Fixed encroachment stations (Method 1)
        - FW_WD_01: Zero floodway width
        - FW_WD_02/03: Encroachment beyond bank stations
        - FW_WD_04: Floodway narrower than channel
        - FW_ST_02: Encroachments inside bridge abutments

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            base_profile: Name of base flood profile
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for encroachment issues
        """
        messages = []

        try:
            # Try to extract encroachment stations from plan HDF
            encr_data = RasCheck._get_encroachment_stations(plan_hdf, floodway_profile)

            if encr_data is None or encr_data.empty:
                # No encroachment data found - could be Method 1 or no encroachments
                logger.debug("No encroachment data found in plan HDF")
                return messages

            # Get cross section data for bank station comparison
            from ..hdf.HdfXsec import HdfXsec
            xs_gdf = HdfXsec.get_cross_sections(geom_hdf)

            # Get structure data for abutment comparison
            struct_data = RasCheck._get_structure_locations(geom_hdf)

            for _, row in encr_data.iterrows():
                river = row.get('river', '')
                reach = row.get('reach', '')
                station = row.get('station', '')
                encr_l = row.get('encr_sta_l', np.nan)
                encr_r = row.get('encr_sta_r', np.nan)

                # Find matching XS for bank stations
                xs_match = xs_gdf[
                    (xs_gdf['River'] == river) &
                    (xs_gdf['Reach'] == reach) &
                    (xs_gdf['RS'].astype(str) == str(station))
                ]

                bank_l = 0
                bank_r = 0
                if not xs_match.empty:
                    xs_row = xs_match.iloc[0]
                    bank_l = xs_row.get('Left Bank', 0)
                    bank_r = xs_row.get('Right Bank', 0)

                # FW_WD_01: Zero floodway width
                if not pd.isna(encr_l) and not pd.isna(encr_r):
                    fw_width = encr_r - encr_l
                    if fw_width <= 0:
                        msg = CheckMessage(
                            message_id="FW_WD_01",
                            severity=Severity.ERROR,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=str(station),
                            message=format_message("FW_WD_01", station=str(station)),
                            help_text=get_help_text("FW_WD_01"),
                            value=fw_width
                        )
                        messages.append(msg)

                    # FW_WD_04: Floodway narrower than channel
                    channel_width = bank_r - bank_l if bank_l and bank_r else 0
                    if channel_width > 0 and fw_width < channel_width:
                        msg = CheckMessage(
                            message_id="FW_WD_04",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=str(station),
                            message=format_message("FW_WD_04", station=str(station)),
                            help_text=get_help_text("FW_WD_04"),
                            value=fw_width - channel_width
                        )
                        messages.append(msg)

                # FW_WD_02: Left encroachment beyond left bank
                if not pd.isna(encr_l) and bank_l > 0:
                    if encr_l > bank_l:
                        msg = CheckMessage(
                            message_id="FW_WD_02",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=str(station),
                            message=format_message("FW_WD_02", station=str(station)),
                            help_text=get_help_text("FW_WD_02"),
                            value=encr_l - bank_l
                        )
                        messages.append(msg)

                # FW_WD_03: Right encroachment beyond right bank
                if not pd.isna(encr_r) and bank_r > 0:
                    if encr_r < bank_r:
                        msg = CheckMessage(
                            message_id="FW_WD_03",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=str(station),
                            message=format_message("FW_WD_03", station=str(station)),
                            help_text=get_help_text("FW_WD_03"),
                            value=bank_r - encr_r
                        )
                        messages.append(msg)

                # FW_ST_02: Check if encroachments are inside bridge abutments
                # FW_ST_03: No encroachment specified at structure
                if struct_data is not None:
                    struct_match = struct_data[
                        (struct_data['river'] == river) &
                        (struct_data['reach'] == reach) &
                        (struct_data['station'] == str(station))
                    ]
                    if not struct_match.empty:
                        struct_row = struct_match.iloc[0]
                        abut_l = struct_row.get('abut_left', 0)
                        abut_r = struct_row.get('abut_right', 0)

                        # FW_ST_03: Check if no encroachment at structure location
                        has_encr = not (pd.isna(encr_l) and pd.isna(encr_r))
                        if not has_encr:
                            msg = CheckMessage(
                                message_id="FW_ST_03",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=str(station),
                                message=format_message("FW_ST_03", station=str(station)),
                                help_text=get_help_text("FW_ST_03"),
                                value=0.0
                            )
                            messages.append(msg)

                        if abut_l > 0 and abut_r > 0:
                            if not pd.isna(encr_l) and encr_l > abut_l:
                                msg = CheckMessage(
                                    message_id="FW_ST_02",
                                    severity=Severity.ERROR,
                                    check_type="FLOODWAY",
                                    river=river,
                                    reach=reach,
                                    station=str(station),
                                    message=format_message("FW_ST_02", station=str(station)),
                                    help_text=get_help_text("FW_ST_02"),
                                    value=encr_l - abut_l
                                )
                                messages.append(msg)

                            if not pd.isna(encr_r) and encr_r < abut_r:
                                msg = CheckMessage(
                                    message_id="FW_ST_02",
                                    severity=Severity.ERROR,
                                    check_type="FLOODWAY",
                                    river=river,
                                    reach=reach,
                                    station=str(station),
                                    message=format_message("FW_ST_02", station=str(station)),
                                    help_text=get_help_text("FW_ST_02"),
                                    value=abut_r - encr_r
                                )
                                messages.append(msg)

            # FW_WD_05: Steep floodway boundary slope check
            # Need to compare encroachment stations between adjacent XS
            encr_sorted = encr_data.sort_values(['river', 'reach', 'station'], ascending=[True, True, False])
            prev_row = None
            prev_reach_len = 100.0  # Default reach length if unknown

            for _, row in encr_sorted.iterrows():
                river = row.get('river', '')
                reach = row.get('reach', '')
                station = row.get('station', '')
                encr_l = row.get('encr_sta_l', np.nan)
                encr_r = row.get('encr_sta_r', np.nan)

                if prev_row is not None and prev_row.get('river', '') == river and prev_row.get('reach', '') == reach:
                    prev_encr_l = prev_row.get('encr_sta_l', np.nan)
                    prev_encr_r = prev_row.get('encr_sta_r', np.nan)

                    # Try to get actual reach length between stations
                    try:
                        prev_sta = float(prev_row.get('station', 0))
                        curr_sta = float(station)
                        reach_len = abs(prev_sta - curr_sta)
                        if reach_len > 0:
                            prev_reach_len = reach_len
                    except (ValueError, TypeError):
                        reach_len = prev_reach_len

                    # Check left encroachment slope
                    if not pd.isna(encr_l) and not pd.isna(prev_encr_l) and reach_len > 0:
                        left_change = abs(encr_l - prev_encr_l)
                        left_slope = left_change / reach_len
                        if left_slope > 0.10:  # 10% slope threshold
                            msg = CheckMessage(
                                message_id="FW_WD_05",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=str(station),
                                message=format_message("FW_WD_05", slope=f"{left_slope:.2f}", station=str(station)),
                                help_text=get_help_text("FW_WD_05"),
                                value=left_slope,
                                threshold=0.10
                            )
                            messages.append(msg)

                    # Check right encroachment slope
                    if not pd.isna(encr_r) and not pd.isna(prev_encr_r) and reach_len > 0:
                        right_change = abs(encr_r - prev_encr_r)
                        right_slope = right_change / reach_len
                        if right_slope > 0.10:  # 10% slope threshold
                            msg = CheckMessage(
                                message_id="FW_WD_05",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=str(station),
                                message=format_message("FW_WD_05", slope=f"{right_slope:.2f}", station=str(station)),
                                help_text=get_help_text("FW_WD_05"),
                                value=right_slope,
                                threshold=0.10
                            )
                            messages.append(msg)

                prev_row = row

            # FW_ST_01: Structure encroachment doesn't match adjacent XS
            if struct_data is not None and not struct_data.empty:
                for _, struct_row in struct_data.iterrows():
                    s_river = struct_row.get('river', '')
                    s_reach = struct_row.get('reach', '')
                    s_station = str(struct_row.get('station', ''))

                    # Get encroachment at structure
                    struct_encr = encr_data[
                        (encr_data['river'] == s_river) &
                        (encr_data['reach'] == s_reach) &
                        (encr_data['station'].astype(str) == s_station)
                    ]

                    if struct_encr.empty:
                        continue

                    struct_encr_l = struct_encr.iloc[0].get('encr_sta_l', np.nan)
                    struct_encr_r = struct_encr.iloc[0].get('encr_sta_r', np.nan)

                    # Find adjacent XS (immediately upstream and downstream)
                    reach_data = encr_data[
                        (encr_data['river'] == s_river) &
                        (encr_data['reach'] == s_reach)
                    ].copy()
                    reach_data['station_num'] = pd.to_numeric(reach_data['station'], errors='coerce')
                    reach_data = reach_data.sort_values('station_num', ascending=False)

                    try:
                        struct_sta_num = float(s_station)
                    except (ValueError, TypeError):
                        continue

                    # Find adjacent XS
                    upstream = reach_data[reach_data['station_num'] > struct_sta_num]
                    downstream = reach_data[reach_data['station_num'] < struct_sta_num]

                    adjacent_encr_l = []
                    adjacent_encr_r = []

                    if not upstream.empty:
                        adjacent_encr_l.append(upstream.iloc[0].get('encr_sta_l', np.nan))
                        adjacent_encr_r.append(upstream.iloc[0].get('encr_sta_r', np.nan))
                    if not downstream.empty:
                        adjacent_encr_l.append(downstream.iloc[0].get('encr_sta_l', np.nan))
                        adjacent_encr_r.append(downstream.iloc[0].get('encr_sta_r', np.nan))

                    # Check if structure encroachment significantly differs from adjacent
                    tolerance = 50.0  # feet tolerance for mismatch
                    for adj_l in adjacent_encr_l:
                        if not pd.isna(struct_encr_l) and not pd.isna(adj_l):
                            if abs(struct_encr_l - adj_l) > tolerance:
                                msg = CheckMessage(
                                    message_id="FW_ST_01",
                                    severity=Severity.WARNING,
                                    check_type="FLOODWAY",
                                    river=s_river,
                                    reach=s_reach,
                                    station=s_station,
                                    message=get_message_template("FW_ST_01"),
                                    help_text=get_help_text("FW_ST_01"),
                                    value=abs(struct_encr_l - adj_l)
                                )
                                messages.append(msg)
                                break

                    for adj_r in adjacent_encr_r:
                        if not pd.isna(struct_encr_r) and not pd.isna(adj_r):
                            if abs(struct_encr_r - adj_r) > tolerance:
                                msg = CheckMessage(
                                    message_id="FW_ST_01",
                                    severity=Severity.WARNING,
                                    check_type="FLOODWAY",
                                    river=s_river,
                                    reach=s_reach,
                                    station=s_station,
                                    message=get_message_template("FW_ST_01"),
                                    help_text=get_help_text("FW_ST_01"),
                                    value=abs(struct_encr_r - adj_r)
                                )
                                messages.append(msg)
                                break

        except Exception as e:
            logger.debug(f"Could not check encroachment data: {e}")

        return messages

    @staticmethod
    def _get_encroachment_stations(
        plan_hdf: Path,
        floodway_profile: str
    ) -> Optional[pd.DataFrame]:
        """
        Extract encroachment stations from plan HDF file.

        Args:
            plan_hdf: Path to plan HDF file
            floodway_profile: Name of floodway profile

        Returns:
            DataFrame with columns: river, reach, station, encr_sta_l, encr_sta_r
            or None if no encroachment data found
        """
        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                # Try multiple possible paths for encroachment data
                encr_paths = [
                    'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Encroachment Stations',
                    'Results/Steady/Output/Cross Sections/Encroachment Stations',
                    'Geometry/Cross Sections/Encroachment Stations'
                ]

                encr_data = None
                for path in encr_paths:
                    if path in hdf:
                        encr_data = hdf[path][:]
                        break

                if encr_data is None:
                    return None

                # Get cross section attributes for river/reach/station info
                xs_attrs_path = 'Geometry/Cross Sections/Attributes'
                if xs_attrs_path not in hdf:
                    return None

                xs_attrs = hdf[xs_attrs_path][:]

                # Get profile names to find floodway profile index
                profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                profile_idx = 0
                if profile_path in hdf:
                    profile_names = hdf[profile_path][:]
                    for i, name in enumerate(profile_names):
                        name_str = name.decode('utf-8').strip() if isinstance(name, bytes) else str(name).strip()
                        if name_str == floodway_profile:
                            profile_idx = i
                            break

                # Build encroachment data DataFrame
                records = []
                for i, xs in enumerate(xs_attrs):
                    river = xs['River'].decode('utf-8').strip() if isinstance(xs['River'], bytes) else str(xs['River']).strip()
                    reach = xs['Reach'].decode('utf-8').strip() if isinstance(xs['Reach'], bytes) else str(xs['Reach']).strip()
                    station = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()

                    # Get encroachment values - structure varies by HDF version
                    if encr_data.ndim == 2:
                        # 2D array: [xs_index, profile_index] or [xs_index, left/right]
                        if encr_data.shape[1] >= 2:
                            encr_l = float(encr_data[i, 0]) if i < encr_data.shape[0] else np.nan
                            encr_r = float(encr_data[i, 1]) if i < encr_data.shape[0] else np.nan
                        else:
                            encr_l = np.nan
                            encr_r = np.nan
                    elif encr_data.ndim == 3:
                        # 3D array: [xs_index, profile_index, left/right]
                        if i < encr_data.shape[0] and profile_idx < encr_data.shape[1]:
                            encr_l = float(encr_data[i, profile_idx, 0])
                            encr_r = float(encr_data[i, profile_idx, 1]) if encr_data.shape[2] > 1 else np.nan
                        else:
                            encr_l = np.nan
                            encr_r = np.nan
                    else:
                        encr_l = np.nan
                        encr_r = np.nan

                    records.append({
                        'river': river,
                        'reach': reach,
                        'station': station,
                        'encr_sta_l': encr_l,
                        'encr_sta_r': encr_r
                    })

                return pd.DataFrame(records)

        except Exception as e:
            logger.debug(f"Could not extract encroachment stations: {e}")
            return None

    @staticmethod
    def _get_structure_locations(geom_hdf: Path) -> Optional[pd.DataFrame]:
        """
        Get structure locations with abutment stations for floodway checks.

        Args:
            geom_hdf: Path to geometry HDF file

        Returns:
            DataFrame with columns: river, reach, station, abut_left, abut_right
            or None if no structures found
        """
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return None

                attrs = hdf['Geometry/Structures/Attributes'][:]

                records = []
                for attr in attrs:
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get abutment stations if available
                    abut_l = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                    abut_r = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0

                    records.append({
                        'river': river,
                        'reach': reach,
                        'station': station,
                        'abut_left': abut_l,
                        'abut_right': abut_r
                    })

                return pd.DataFrame(records)

        except Exception as e:
            logger.debug(f"Could not get structure locations: {e}")
            return None

    @staticmethod
    def _check_floodway_discharge_conservation(
        steady_results: pd.DataFrame,
        floodway_profile: str
    ) -> List[CheckMessage]:
        """
        Check for discharge changes within floodway reach.

        Args:
            steady_results: Steady flow results DataFrame
            floodway_profile: Name of floodway profile

        Returns:
            List of CheckMessage objects for discharge conservation issues
        """
        messages = []

        if steady_results.empty or 'flow' not in steady_results.columns:
            return messages

        # Filter to floodway profile
        fw_results = steady_results[steady_results['profile'] == floodway_profile]

        if fw_results.empty:
            return messages

        # Tolerance for flow change (2% or 50 cfs, whichever is greater)
        flow_pct_tolerance = 0.02
        flow_abs_tolerance = 50.0

        # Group by River and Reach
        for (river, reach), group in fw_results.groupby(['river', 'reach']):
            # Sort by station (descending = upstream to downstream)
            group_sorted = group.sort_values('node_id', ascending=False)

            prev_row = None
            prev_flow = None
            for idx, row in group_sorted.iterrows():
                station = str(row.get('node_id', ''))
                flow = row.get('flow', np.nan)

                if prev_row is not None and not pd.isna(flow) and not pd.isna(prev_flow):
                    # Check for flow change
                    flow_diff = abs(flow - prev_flow)
                    flow_pct = flow_diff / prev_flow if prev_flow > 0 else 0

                    # Flag if flow changes significantly
                    if flow_diff > flow_abs_tolerance and flow_pct > flow_pct_tolerance:
                        msg = CheckMessage(
                            message_id="FW_Q_03",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_Q_03"),
                            help_text=get_help_text("FW_Q_03"),
                            value=flow_diff
                        )
                        messages.append(msg)

                prev_row = row
                prev_flow = flow

        return messages

    @staticmethod
    def _check_floodway_encroachment_methods(
        plan_hdf: Path,
        geom_hdf: Path,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check encroachment methods used for floodway analysis.

        Validates:
        - FW_EM_01: Fixed encroachment stations (Method 1) used
        - FW_EM_02: No encroachment method specified at XS
        - FW_EM_03: Encroachment method varies within reach
        - FW_EM_04: No encroachment at non-structure XS
        - FW_EM_05: Method 5 (target surcharge) specific checks
        - FW_EM_06: Encroachment at structures special handling
        - FW_EM_07: Encroachment optimization warnings
        - FW_EM_08: Encroachment iteration limits

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for encroachment method issues
        """
        messages = []

        try:
            # Get encroachment data
            encr_data = RasCheck._get_encroachment_stations(plan_hdf, floodway_profile)

            if encr_data is None or encr_data.empty:
                return messages

            # Get structure locations to identify structure vs non-structure XS
            struct_data = RasCheck._get_structure_locations(geom_hdf)
            struct_stations = set()
            if struct_data is not None and not struct_data.empty:
                for _, row in struct_data.iterrows():
                    key = (row.get('river', ''), row.get('reach', ''), str(row.get('station', '')))
                    struct_stations.add(key)

            # Track encroachment methods by reach
            reach_methods = {}

            # Try to get encroachment parameters from plan HDF for Method 5 checks
            encr_params = RasCheck._get_encroachment_parameters(plan_hdf, floodway_profile)

            for _, row in encr_data.iterrows():
                river = row.get('river', '')
                reach = row.get('reach', '')
                station = str(row.get('station', ''))
                encr_l = row.get('encr_sta_l', np.nan)
                encr_r = row.get('encr_sta_r', np.nan)
                encr_method = row.get('encr_method', 0)

                reach_key = (river, reach)
                xs_key = (river, reach, station)
                is_structure = xs_key in struct_stations

                # Track methods for reach consistency check
                if reach_key not in reach_methods:
                    reach_methods[reach_key] = set()
                if encr_method > 0:
                    reach_methods[reach_key].add(encr_method)

                # FW_EM_01: Method 1 (Fixed encroachment stations) used
                if encr_method == 1:
                    msg = CheckMessage(
                        message_id="FW_EM_01",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_EM_01", station=station),
                        help_text=get_help_text("FW_EM_01"),
                        value=float(encr_method)
                    )
                    messages.append(msg)

                # FW_EM_02: No encroachment method specified
                if encr_method == 0 and not is_structure:
                    # Check if encroachment stations are actually set
                    has_encr = not (pd.isna(encr_l) and pd.isna(encr_r))
                    if not has_encr:
                        msg = CheckMessage(
                            message_id="FW_EM_02",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=get_message_template("FW_EM_02"),
                            help_text=get_help_text("FW_EM_02"),
                            value=0.0
                        )
                        messages.append(msg)

                # FW_EM_04: No encroachment at non-structure XS
                if not is_structure:
                    has_encr = not (pd.isna(encr_l) and pd.isna(encr_r))
                    if not has_encr and encr_method == 0:
                        msg = CheckMessage(
                            message_id="FW_EM_04",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_EM_04", station=station),
                            help_text=get_help_text("FW_EM_04"),
                            value=0.0
                        )
                        messages.append(msg)

                # FW_EM_05: Method 5 (target surcharge) specific check
                if encr_method == 5:
                    target_surcharge = encr_params.get('target_surcharge', 1.0) if encr_params else 1.0
                    msg = CheckMessage(
                        message_id="FW_EM_05",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_EM_05", station=station, target=f"{target_surcharge:.2f}"),
                        help_text=get_help_text("FW_EM_05"),
                        value=target_surcharge
                    )
                    messages.append(msg)

                # FW_EM_06: Encroachment at structure requires special handling
                if is_structure and encr_method > 0:
                    msg = CheckMessage(
                        message_id="FW_EM_06",
                        severity=Severity.WARNING,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_EM_06", station=station),
                        help_text=get_help_text("FW_EM_06"),
                        value=float(encr_method)
                    )
                    messages.append(msg)

                # FW_EM_07: Check for optimization warnings (irregular encroachment pattern)
                # Detect if encroachments create irregular floodway boundaries
                if encr_method in [4, 5]:
                    # Check if encroachment is asymmetric in an unusual way
                    if not pd.isna(encr_l) and not pd.isna(encr_r):
                        # Get bank stations if available
                        bank_l = row.get('bank_sta_l', 0)
                        bank_r = row.get('bank_sta_r', 0)
                        if bank_l > 0 and bank_r > 0:
                            left_encr_dist = encr_l - bank_l if encr_l > bank_l else 0
                            right_encr_dist = bank_r - encr_r if encr_r < bank_r else 0

                            # Flag highly asymmetric encroachments (ratio > 5:1)
                            if left_encr_dist > 0 and right_encr_dist > 0:
                                ratio = max(left_encr_dist, right_encr_dist) / min(left_encr_dist, right_encr_dist)
                                if ratio > 5.0:
                                    msg = CheckMessage(
                                        message_id="FW_EM_07",
                                        severity=Severity.WARNING,
                                        check_type="FLOODWAY",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("FW_EM_07", station=station,
                                                              warning=f"asymmetric encroachment ratio {ratio:.1f}:1"),
                                        help_text=get_help_text("FW_EM_07"),
                                        value=ratio
                                    )
                                    messages.append(msg)

            # FW_EM_03: Check for varying encroachment methods within reach
            for (river, reach), methods in reach_methods.items():
                if len(methods) > 1:
                    methods_str = ', '.join(str(m) for m in sorted(methods))
                    msg = CheckMessage(
                        message_id="FW_EM_03",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station="",
                        message=format_message("FW_EM_03", methods=methods_str),
                        help_text=get_help_text("FW_EM_03"),
                        value=float(len(methods))
                    )
                    messages.append(msg)

            # FW_EM_08: Check iteration limits from encroachment parameters
            if encr_params:
                max_iterations = encr_params.get('max_iterations', 20)
                # Standard default is 20; flag if less than 10
                if max_iterations < 10:
                    # Get a representative station for the message
                    if not encr_data.empty:
                        sample_row = encr_data.iloc[0]
                        msg = CheckMessage(
                            message_id="FW_EM_08",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=sample_row.get('river', ''),
                            reach=sample_row.get('reach', ''),
                            station=str(sample_row.get('station', '')),
                            message=format_message("FW_EM_08", iterations=max_iterations,
                                                  station=str(sample_row.get('station', ''))),
                            help_text=get_help_text("FW_EM_08"),
                            value=float(max_iterations)
                        )
                        messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not check encroachment methods: {e}")

        return messages

    @staticmethod
    def _get_encroachment_parameters(
        plan_hdf: Path,
        floodway_profile: str
    ) -> Optional[Dict]:
        """
        Extract encroachment parameters from plan HDF file.

        Args:
            plan_hdf: Path to plan HDF file
            floodway_profile: Name of floodway profile

        Returns:
            Dictionary with encroachment parameters (target_surcharge, max_iterations, etc.)
            or None if not found
        """
        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                # Try multiple possible paths for encroachment parameters
                param_paths = [
                    'Plan Data/Encroachment Data',
                    'Event Conditions/Steady Flow/Encroachment Data',
                    'Plan Data/Plan Parameters/Encroachment'
                ]

                for path in param_paths:
                    if path in hdf:
                        param_group = hdf[path]
                        params = {}

                        # Extract target surcharge
                        if 'Target Surcharge' in param_group.attrs:
                            params['target_surcharge'] = float(param_group.attrs['Target Surcharge'])
                        elif 'Target Surcharge' in param_group:
                            params['target_surcharge'] = float(param_group['Target Surcharge'][()])

                        # Extract max iterations
                        if 'Max Iterations' in param_group.attrs:
                            params['max_iterations'] = int(param_group.attrs['Max Iterations'])
                        elif 'Maximum Iterations' in param_group.attrs:
                            params['max_iterations'] = int(param_group.attrs['Maximum Iterations'])

                        # Extract tolerance
                        if 'Tolerance' in param_group.attrs:
                            params['tolerance'] = float(param_group.attrs['Tolerance'])

                        if params:
                            return params

                # Default values if not found
                return {'target_surcharge': 1.0, 'max_iterations': 20, 'tolerance': 0.01}

        except Exception as e:
            logger.debug(f"Could not extract encroachment parameters: {e}")
            return None

    @staticmethod
    def _check_floodway_boundary_conditions(
        plan_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check boundary conditions for floodway analysis.

        Validates:
        - FW_BC_01: Different starting WSE between base and floodway
        - FW_BC_02: Same slope boundary used
        - FW_BC_03: Known WSE boundary used

        Args:
            plan_hdf: Path to plan HDF file
            base_profile: Name of base flood profile
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for boundary condition issues
        """
        messages = []

        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                # Try to find boundary condition data
                bc_paths = [
                    'Plan Data/Plan Information/Boundary Conditions',
                    'Event Conditions/Steady Flow/Boundary Conditions',
                    'Plan Data/Boundary Conditions'
                ]

                bc_data = None
                for path in bc_paths:
                    if path in hdf:
                        bc_data = hdf[path]
                        break

                if bc_data is None:
                    return messages

                # Try to extract boundary condition type
                bc_type = None
                if 'Type' in bc_data.attrs:
                    bc_type = bc_data.attrs['Type']
                    if isinstance(bc_type, bytes):
                        bc_type = bc_type.decode('utf-8')

                # FW_BC_02: Same slope boundary
                if bc_type and 'slope' in str(bc_type).lower():
                    msg = CheckMessage(
                        message_id="FW_BC_02",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river="",
                        reach="",
                        station="",
                        message=get_message_template("FW_BC_02"),
                        help_text=get_help_text("FW_BC_02")
                    )
                    messages.append(msg)

                # FW_BC_03: Known WSE boundary
                if bc_type and ('wse' in str(bc_type).lower() or 'known' in str(bc_type).lower()):
                    msg = CheckMessage(
                        message_id="FW_BC_03",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river="",
                        reach="",
                        station="",
                        message=get_message_template("FW_BC_03"),
                        help_text=get_help_text("FW_BC_03")
                    )
                    messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not check boundary conditions: {e}")

        return messages

    @staticmethod
    def _check_floodway_starting_wse(
        plan_hdf: Path,
        steady_results: pd.DataFrame,
        geom_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check starting water surface elevations for floodway analysis.

        Validates:
        - FW_SW_01: Starting WSE not specified for floodway (informational)
        - FW_SW_02: Starting WSE differs from base flood by more than threshold
        - FW_SW_03: Floodway starting WSE below channel invert
        - FW_SW_04: Floodway starting WSE above top of bank
        - FW_SW_05: Starting WSE inconsistent between profiles
        - FW_SW_06: Starting WSE produces supercritical flow
        - FW_SW_07: Starting WSE results in negative depth
        - FW_SW_08: Starting WSE differs significantly from computed WSE

        Method-Specific Variants (added for encroachment method-specific validation):
        - FW_SW_02M1: Starting WSE difference - Method 1 (fixed stations) specific
        - FW_SW_02M4: Starting WSE difference - Method 4 (target surcharge) specific
        - FW_SW_02M5: Starting WSE difference - Method 5 (target width reduction) specific
        - FW_SW_03M1: Starting WSE below invert - Method 1 variant
        - FW_SW_03M4: Starting WSE below invert - Method 4 variant
        - FW_SW_04M1: Starting WSE above bank - Method 1 variant
        - FW_SW_04M4: Starting WSE above bank - Method 4 variant
        - FW_SW_05M1: Starting WSE inconsistent - Method 1 variant
        - FW_SW_05M4: Starting WSE inconsistent - Method 4 variant

        HEC-RAS Encroachment Methods:
        - Method 1: Fixed encroachment stations
        - Method 2: Fixed top widths
        - Method 3: Fixed percentage of conveyance reduction
        - Method 4: Target surcharge (most common for FEMA)
        - Method 5: Target width reduction

        Args:
            plan_hdf: Path to plan HDF file (needed for encroachment method detection)
            steady_results: Steady flow results DataFrame with columns:
                - profile, river, reach, node_id, wsel, min_ch_el, froude, max_depth
            geom_hdf: Path to geometry HDF file for cross section data
            base_profile: Name of base flood profile
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for starting WSE issues
        """
        from ..hdf.HdfXsec import HdfXsec

        messages = []

        if steady_results.empty:
            return messages

        fw_thresholds = thresholds.floodway

        try:
            # Get base and floodway results
            base_data = steady_results[steady_results['profile'] == base_profile]
            fw_data = steady_results[steady_results['profile'] == floodway_profile]

            if base_data.empty or fw_data.empty:
                return messages

            # Get encroachment method data for method-specific checks
            encr_data = RasCheck._get_encroachment_stations(plan_hdf, floodway_profile)
            encr_params = RasCheck._get_encroachment_parameters(plan_hdf, floodway_profile)

            # Build a lookup for encroachment methods by station
            encr_method_by_station = {}
            if encr_data is not None and not encr_data.empty:
                for _, row in encr_data.iterrows():
                    key = (row.get('river', ''), row.get('reach', ''), str(row.get('station', '')))
                    encr_method_by_station[key] = row.get('encr_method', 0)

            # Get target values from encroachment parameters
            target_surcharge = encr_params.get('target_surcharge', 1.0) if encr_params else 1.0
            target_width_reduction_pct = encr_params.get('target_width_reduction', 50.0) if encr_params else 50.0

            # Try to get cross section geometry for bank elevations
            xs_gdf = None
            try:
                xs_gdf = HdfXsec.get_cross_sections(geom_hdf)
            except Exception as e:
                logger.debug(f"Could not read cross section geometry: {e}")

            # Find downstream boundary (lowest station in each reach)
            for (river, reach), group in base_data.groupby(['river', 'reach']):
                # Get downstream station (minimum station value)
                group_sorted = group.sort_values('node_id', ascending=True)
                if group_sorted.empty:
                    continue

                ds_row = group_sorted.iloc[0]
                station = str(ds_row.get('node_id', ''))
                base_wse = ds_row.get('wsel', np.nan)
                base_min_ch_el = ds_row.get('min_ch_el', np.nan)
                base_froude = ds_row.get('froude', np.nan)
                base_depth = ds_row.get('max_depth', np.nan)

                # Find matching floodway data
                fw_match = fw_data[
                    (fw_data['river'] == river) &
                    (fw_data['reach'] == reach) &
                    (fw_data['node_id'] == ds_row['node_id'])
                ]

                if fw_match.empty:
                    continue

                fw_row = fw_match.iloc[0]
                fw_wse = fw_row.get('wsel', np.nan)
                fw_min_ch_el = fw_row.get('min_ch_el', np.nan)
                fw_froude = fw_row.get('froude', np.nan)
                fw_depth = fw_row.get('max_depth', np.nan)

                # Use floodway min_ch_el, fall back to base if not available
                min_ch_el = fw_min_ch_el if not pd.isna(fw_min_ch_el) else base_min_ch_el

                # Get bank elevation from geometry if available
                bank_elev = None
                if xs_gdf is not None and not xs_gdf.empty:
                    xs_match = xs_gdf[
                        (xs_gdf['River'] == river) &
                        (xs_gdf['Reach'] == reach) &
                        (xs_gdf['RS'].astype(str) == station)
                    ]
                    if not xs_match.empty:
                        # Get station-elevation data to find bank elevations
                        xs_row = xs_match.iloc[0]
                        sta_elev = xs_row.get('station_elevation', None)
                        left_bank_sta = xs_row.get('Left Bank', np.nan)
                        right_bank_sta = xs_row.get('Right Bank', np.nan)

                        if sta_elev is not None and len(sta_elev) > 0:
                            try:
                                # Find elevations at bank stations
                                stations = np.array([pt[0] for pt in sta_elev])
                                elevations = np.array([pt[1] for pt in sta_elev])

                                # Get maximum elevation at or near bank stations
                                bank_elevs = []
                                for bank_sta in [left_bank_sta, right_bank_sta]:
                                    if not pd.isna(bank_sta):
                                        # Find closest station
                                        idx = np.argmin(np.abs(stations - bank_sta))
                                        bank_elevs.append(elevations[idx])

                                if bank_elevs:
                                    bank_elev = max(bank_elevs)
                            except Exception:
                                pass

                # Get encroachment method for this cross section
                xs_key = (river, reach, station)
                encr_method = encr_method_by_station.get(xs_key, 0)

                # =====================================================================
                # FW_SW_01: Report starting WSE (informational)
                # =====================================================================
                if not pd.isna(fw_wse):
                    msg = CheckMessage(
                        message_id="FW_SW_01",
                        severity=Severity.INFO,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_SW_01",
                            wse=f"{fw_wse:.2f}",
                            profile=floodway_profile),
                        help_text=get_help_text("FW_SW_01"),
                        value=fw_wse
                    )
                    messages.append(msg)

                # =====================================================================
                # FW_SW_02: Starting WSE difference exceeds threshold
                # =====================================================================
                if not pd.isna(base_wse) and not pd.isna(fw_wse):
                    wse_diff = abs(fw_wse - base_wse)
                    threshold = fw_thresholds.starting_wse_diff_threshold_ft
                    if wse_diff > threshold:
                        msg = CheckMessage(
                            message_id="FW_SW_02",
                            severity=Severity.WARNING,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_SW_02",
                                diff=f"{wse_diff:.2f}",
                                base_wse=f"{base_wse:.2f}",
                                fw_wse=f"{fw_wse:.2f}"),
                            help_text=get_help_text("FW_SW_02"),
                            value=wse_diff,
                            threshold=threshold
                        )
                        messages.append(msg)

                        # =========================================================
                        # Method-specific variants of FW_SW_02
                        # =========================================================

                        # FW_SW_02M1: Method 1 (fixed stations) specific
                        if encr_method == 1:
                            msg = CheckMessage(
                                message_id="FW_SW_02M1",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_02M1",
                                    diff=f"{wse_diff:.2f}",
                                    station=station),
                                help_text=get_help_text("FW_SW_02M1"),
                                value=wse_diff,
                                threshold=threshold
                            )
                            messages.append(msg)

                        # FW_SW_02M4: Method 4 (target surcharge) specific
                        elif encr_method == 4:
                            msg = CheckMessage(
                                message_id="FW_SW_02M4",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_02M4",
                                    diff=f"{wse_diff:.2f}",
                                    station=station,
                                    target=f"{target_surcharge:.2f}"),
                                help_text=get_help_text("FW_SW_02M4"),
                                value=wse_diff,
                                threshold=threshold
                            )
                            messages.append(msg)

                        # FW_SW_02M5: Method 5 (target width reduction) specific
                        elif encr_method == 5:
                            msg = CheckMessage(
                                message_id="FW_SW_02M5",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_02M5",
                                    diff=f"{wse_diff:.2f}",
                                    station=station,
                                    target_pct=f"{target_width_reduction_pct:.0f}"),
                                help_text=get_help_text("FW_SW_02M5"),
                                value=wse_diff,
                                threshold=threshold
                            )
                            messages.append(msg)

                # =====================================================================
                # FW_SW_03: Starting WSE below channel invert
                # =====================================================================
                if not pd.isna(fw_wse) and not pd.isna(min_ch_el):
                    if fw_wse < min_ch_el:
                        msg = CheckMessage(
                            message_id="FW_SW_03",
                            severity=Severity.ERROR,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_SW_03",
                                wse=f"{fw_wse:.2f}",
                                invert=f"{min_ch_el:.2f}",
                                station=station),
                            help_text=get_help_text("FW_SW_03"),
                            value=fw_wse,
                            threshold=min_ch_el
                        )
                        messages.append(msg)

                        # =========================================================
                        # Method-specific variants of FW_SW_03
                        # =========================================================

                        # FW_SW_03M1: Method 1 (fixed stations) specific
                        if encr_method == 1:
                            msg = CheckMessage(
                                message_id="FW_SW_03M1",
                                severity=Severity.ERROR,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_03M1",
                                    wse=f"{fw_wse:.2f}",
                                    invert=f"{min_ch_el:.2f}",
                                    station=station),
                                help_text=get_help_text("FW_SW_03M1"),
                                value=fw_wse,
                                threshold=min_ch_el
                            )
                            messages.append(msg)

                        # FW_SW_03M4: Method 4 (target surcharge) specific
                        elif encr_method == 4:
                            msg = CheckMessage(
                                message_id="FW_SW_03M4",
                                severity=Severity.ERROR,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_03M4",
                                    wse=f"{fw_wse:.2f}",
                                    invert=f"{min_ch_el:.2f}",
                                    station=station),
                                help_text=get_help_text("FW_SW_03M4"),
                                value=fw_wse,
                                threshold=min_ch_el
                            )
                            messages.append(msg)

                # =====================================================================
                # FW_SW_04: Starting WSE above top of bank
                # =====================================================================
                if (not pd.isna(fw_wse) and bank_elev is not None
                    and fw_thresholds.starting_wse_above_bank_warning):
                    if fw_wse > bank_elev:
                        msg = CheckMessage(
                            message_id="FW_SW_04",
                            severity=Severity.INFO,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_SW_04",
                                wse=f"{fw_wse:.2f}",
                                bank_elev=f"{bank_elev:.2f}",
                                station=station),
                            help_text=get_help_text("FW_SW_04"),
                            value=fw_wse,
                            threshold=bank_elev
                        )
                        messages.append(msg)

                        # =========================================================
                        # Method-specific variants of FW_SW_04
                        # =========================================================

                        # FW_SW_04M1: Method 1 (fixed stations) specific
                        if encr_method == 1:
                            msg = CheckMessage(
                                message_id="FW_SW_04M1",
                                severity=Severity.INFO,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_04M1",
                                    wse=f"{fw_wse:.2f}",
                                    bank_elev=f"{bank_elev:.2f}",
                                    station=station),
                                help_text=get_help_text("FW_SW_04M1"),
                                value=fw_wse,
                                threshold=bank_elev
                            )
                            messages.append(msg)

                        # FW_SW_04M4: Method 4 (target surcharge) specific
                        elif encr_method == 4:
                            msg = CheckMessage(
                                message_id="FW_SW_04M4",
                                severity=Severity.INFO,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_04M4",
                                    wse=f"{fw_wse:.2f}",
                                    bank_elev=f"{bank_elev:.2f}",
                                    station=station),
                                help_text=get_help_text("FW_SW_04M4"),
                                value=fw_wse,
                                threshold=bank_elev
                            )
                            messages.append(msg)

                # =====================================================================
                # FW_SW_05: Starting WSE inconsistent between profiles
                # Check other profiles at the same location for consistency
                # =====================================================================
                all_profiles = steady_results['profile'].unique()
                for other_profile in all_profiles:
                    if other_profile in [base_profile, floodway_profile]:
                        continue

                    other_match = steady_results[
                        (steady_results['profile'] == other_profile) &
                        (steady_results['river'] == river) &
                        (steady_results['reach'] == reach) &
                        (steady_results['node_id'] == ds_row['node_id'])
                    ]

                    if other_match.empty:
                        continue

                    other_wse = other_match.iloc[0].get('wsel', np.nan)

                    if not pd.isna(fw_wse) and not pd.isna(other_wse):
                        diff = abs(fw_wse - other_wse)
                        # Use same threshold as FW_SW_02
                        if diff > fw_thresholds.starting_wse_diff_threshold_ft:
                            msg = CheckMessage(
                                message_id="FW_SW_05",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_SW_05",
                                    station=station,
                                    profile1=floodway_profile,
                                    wse1=f"{fw_wse:.2f}",
                                    profile2=other_profile,
                                    wse2=f"{other_wse:.2f}"),
                                help_text=get_help_text("FW_SW_05"),
                                value=diff
                            )
                            messages.append(msg)

                            # =========================================================
                            # Method-specific variants of FW_SW_05
                            # =========================================================

                            # FW_SW_05M1: Method 1 (fixed stations) specific
                            if encr_method == 1:
                                msg = CheckMessage(
                                    message_id="FW_SW_05M1",
                                    severity=Severity.WARNING,
                                    check_type="FLOODWAY",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("FW_SW_05M1",
                                        profile1=floodway_profile,
                                        wse1=f"{fw_wse:.2f}",
                                        profile2=other_profile,
                                        wse2=f"{other_wse:.2f}",
                                        station=station),
                                    help_text=get_help_text("FW_SW_05M1"),
                                    value=diff
                                )
                                messages.append(msg)

                            # FW_SW_05M4: Method 4 (target surcharge) specific
                            elif encr_method == 4:
                                msg = CheckMessage(
                                    message_id="FW_SW_05M4",
                                    severity=Severity.INFO,
                                    check_type="FLOODWAY",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("FW_SW_05M4",
                                        profile1=floodway_profile,
                                        wse1=f"{fw_wse:.2f}",
                                        profile2=other_profile,
                                        wse2=f"{other_wse:.2f}",
                                        station=station),
                                    help_text=get_help_text("FW_SW_05M4"),
                                    value=diff
                                )
                                messages.append(msg)

                # =====================================================================
                # FW_SW_06: Starting WSE produces supercritical flow
                # =====================================================================
                if not pd.isna(fw_froude) and fw_froude >= 1.0:
                    msg = CheckMessage(
                        message_id="FW_SW_06",
                        severity=Severity.WARNING,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_SW_06",
                            froude=fw_froude,
                            station=station,
                            profile=floodway_profile),
                        help_text=get_help_text("FW_SW_06"),
                        value=fw_froude,
                        threshold=1.0
                    )
                    messages.append(msg)

                # =====================================================================
                # FW_SW_07: Starting WSE results in negative depth
                # =====================================================================
                if not pd.isna(fw_depth) and fw_depth < 0:
                    msg = CheckMessage(
                        message_id="FW_SW_07",
                        severity=Severity.ERROR,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_SW_07",
                            wse=f"{fw_wse:.2f}" if not pd.isna(fw_wse) else "N/A",
                            depth=f"{fw_depth:.2f}",
                            station=station),
                        help_text=get_help_text("FW_SW_07"),
                        value=fw_depth
                    )
                    messages.append(msg)
                # Also check using computed depth from WSE - min_ch_el
                elif not pd.isna(fw_wse) and not pd.isna(min_ch_el):
                    computed_depth = fw_wse - min_ch_el
                    if computed_depth < 0:
                        msg = CheckMessage(
                            message_id="FW_SW_07",
                            severity=Severity.ERROR,
                            check_type="FLOODWAY",
                            river=river,
                            reach=reach,
                            station=station,
                            message=format_message("FW_SW_07",
                                wse=f"{fw_wse:.2f}",
                                depth=f"{computed_depth:.2f}",
                                station=station),
                            help_text=get_help_text("FW_SW_07"),
                            value=computed_depth
                        )
                        messages.append(msg)

                # =====================================================================
                # FW_SW_08: Starting WSE differs significantly from computed WSE
                # Compare specified boundary WSE with computed WSE at downstream section
                # This detects when boundary conditions don't match computed results
                # =====================================================================
                # The WSE in steady_results is the computed WSE. If there's a boundary
                # condition file with specified starting WSE, the difference could be large
                # when the boundary condition is inappropriate for the reach
                # For this check, we compare base and floodway WSE differences to detect
                # inconsistencies that may indicate boundary condition problems
                if not pd.isna(base_wse) and not pd.isna(fw_wse):
                    # Get second downstream station to compare slope/trend
                    if len(group_sorted) >= 2:
                        second_ds_row = group_sorted.iloc[1]
                        second_station = str(second_ds_row.get('node_id', ''))
                        second_base_wse = second_ds_row.get('wsel', np.nan)

                        fw_second_match = fw_data[
                            (fw_data['river'] == river) &
                            (fw_data['reach'] == reach) &
                            (fw_data['node_id'] == second_ds_row['node_id'])
                        ]

                        if not fw_second_match.empty and not pd.isna(second_base_wse):
                            second_fw_wse = fw_second_match.iloc[0].get('wsel', np.nan)

                            if not pd.isna(second_fw_wse):
                                # Compare the slope of WSE between DS sections
                                # If floodway and base have very different trends at boundary,
                                # it may indicate boundary condition issues
                                base_slope = base_wse - second_base_wse
                                fw_slope = fw_wse - second_fw_wse

                                # Large difference in WSE drop from boundary to next section
                                slope_diff = abs(base_slope - fw_slope)
                                computed_diff_threshold = fw_thresholds.starting_wse_computed_diff_ft

                                if slope_diff > computed_diff_threshold:
                                    msg = CheckMessage(
                                        message_id="FW_SW_08",
                                        severity=Severity.WARNING,
                                        check_type="FLOODWAY",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("FW_SW_08",
                                            start_wse=f"{fw_wse:.2f}",
                                            computed_wse=f"{second_fw_wse:.2f}",
                                            diff=f"{slope_diff:.2f}",
                                            station=station),
                                        help_text=get_help_text("FW_SW_08"),
                                        value=slope_diff,
                                        threshold=computed_diff_threshold
                                    )
                                    messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not check starting WSE: {e}")

        return messages

    @staticmethod
    def _check_floodway_lateral_weirs(
        plan_hdf: Path,
        geom_hdf: Path,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check lateral weirs for floodway analysis.

        Validates:
        - FW_LW_01: Lateral weir active in floodway profile
        - FW_LW_02: Lateral weir flow exceeds 5% of main channel

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for lateral weir issues
        """
        messages = []

        try:
            # Get lateral structure data from geometry HDF
            with h5py.File(geom_hdf, 'r') as hdf:
                lat_path = 'Geometry/Lateral Structures/Attributes'
                if lat_path not in hdf:
                    return messages

                lat_attrs = hdf[lat_path][:]

                for attr in lat_attrs:
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # FW_LW_01: Lateral weir is present (may be active)
                    msg = CheckMessage(
                        message_id="FW_LW_01",
                        severity=Severity.WARNING,
                        check_type="FLOODWAY",
                        river=river,
                        reach=reach,
                        station=station,
                        message=format_message("FW_LW_01", sta=station),
                        help_text=get_help_text("FW_LW_01")
                    )
                    messages.append(msg)

            # Check for lateral weir flow from plan results
            with h5py.File(plan_hdf, 'r') as hdf:
                # Try to find lateral structure flow data
                lat_flow_paths = [
                    'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Lateral Structures/Flow',
                    'Results/Steady/Output/Lateral Structures/Flow'
                ]

                for lat_flow_path in lat_flow_paths:
                    if lat_flow_path not in hdf:
                        continue

                    lat_flow = hdf[lat_flow_path][:]

                    # Get profile names to find floodway profile index
                    profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                    profile_idx = 0
                    if profile_path in hdf:
                        profile_names = hdf[profile_path][:]
                        for i, name in enumerate(profile_names):
                            name_str = name.decode('utf-8').strip() if isinstance(name, bytes) else str(name).strip()
                            if name_str == floodway_profile:
                                profile_idx = i
                                break

                    # Get main channel flow for comparison
                    xs_flow_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Flow'
                    main_channel_flows = None
                    if xs_flow_path in hdf:
                        main_channel_flows = hdf[xs_flow_path][:]

                    # Check lateral weir flow percentages
                    for i, lat_f in enumerate(lat_flow):
                        if lat_flow.ndim == 2:
                            flow_val = float(lat_f[profile_idx]) if profile_idx < lat_f.shape[0] else 0
                        else:
                            flow_val = float(lat_f) if not np.isnan(lat_f) else 0

                        if flow_val > 0 and main_channel_flows is not None:
                            # Compare to nearby main channel flow
                            if i < len(main_channel_flows):
                                if main_channel_flows.ndim == 2:
                                    mc_flow = float(main_channel_flows[i, profile_idx]) if profile_idx < main_channel_flows.shape[1] else 0
                                else:
                                    mc_flow = float(main_channel_flows[i])

                                if mc_flow > 0:
                                    pct = flow_val / mc_flow * 100
                                    if pct > 5.0:
                                        # FW_LW_02: Significant lateral weir flow
                                        msg = CheckMessage(
                                            message_id="FW_LW_02",
                                            severity=Severity.WARNING,
                                            check_type="FLOODWAY",
                                            river="",
                                            reach="",
                                            station=str(i),
                                            message=format_message("FW_LW_02", sta=str(i)),
                                            help_text=get_help_text("FW_LW_02"),
                                            value=pct,
                                            threshold=5.0
                                        )
                                        messages.append(msg)
                    break

        except Exception as e:
            logger.debug(f"Could not check lateral weirs: {e}")

        return messages

    @staticmethod
    def _check_structure_floodway(
        plan_hdf: Path,
        geom_hdf: Path,
        base_profile: str,
        floodway_profile: str,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure floodway encroachments (FW_ST_* checks).

        Validates floodway encroachments at structures (bridges/culverts):
        - FW_ST_02L/R: Left/Right encroachment inside bridge/culvert opening
        - FW_ST_03L/R: Left/Right encroachment starts inside abutment
        - FW_ST_04L/R: Left/Right encroachment ends inside abutment
        - FW_ST_05L/R: Left/Right encroachment blocks flow area
        - FW_ST_06: Floodway width exceeds structure opening width
        - FW_ST_07: Floodway bottom elevation above structure invert
        - FW_ST_08: Floodway top width less than structure width
        - FW_ST_09: Encroachment in deck/roadway area
        - FW_ST_10: Pier within floodway encroachment limits
        - FW_ST_11: Abutment within floodway limits
        - FW_ST_12: Structure opening blocked by encroachment
        - FW_ST_13: Flow area reduced by more than X% at structure

        Section-Specific Variants for Bridges (4-Section Model):
        Bridge structures use a 4-section model where:
        - Section 1 (S1) = Upstream cross section
        - Section 2 (S2/BU) = Bridge Upstream face
        - Section 3 (S3/BD) = Bridge Downstream face
        - Section 4 (S4) = Downstream cross section

        Section-specific check IDs:
        - FW_ST_02S2L/R, FW_ST_02BUL/R: Section 2 left/right encroachment inside opening
        - FW_ST_02S3L/R, FW_ST_02BDL/R: Section 3 left/right encroachment inside opening
        - FW_ST_03S2L/R, FW_ST_03BUL/R: Section 2 left/right encroachment in abutment zone
        - FW_ST_03S3L/R, FW_ST_03BDL/R: Section 3 left/right encroachment in abutment zone
        - FW_ST_04S2L/R, FW_ST_04BUL/R: Section 2 left/right encroachment ends inside abutment
        - FW_ST_04S3L/R, FW_ST_04BDL/R: Section 3 left/right encroachment ends inside abutment
        - FW_ST_05S2L/R, FW_ST_05BUL/R: Section 2 left/right encroachment blocks flow
        - FW_ST_05S3L/R, FW_ST_05BDL/R: Section 3 left/right encroachment blocks flow

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            base_profile: Name of base flood profile
            floodway_profile: Name of floodway profile
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for structure floodway issues
        """
        messages = []

        try:
            # Get encroachment data
            encr_data = RasCheck._get_encroachment_stations(plan_hdf, floodway_profile)
            if encr_data is None or encr_data.empty:
                return messages

            # Get structure data from geometry HDF
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Try to get table info and pier data
                table_info = None
                pier_data = None
                if 'Geometry/Structures/Table Info' in hdf:
                    table_info = hdf['Geometry/Structures/Table Info'][:]
                if 'Geometry/Structures/Pier Data' in hdf:
                    pier_data = hdf['Geometry/Structures/Pier Data'][:]

                # Process each structure
                for struct_idx, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Only process bridges and culverts
                    is_bridge = 'Bridge' in struct_type
                    is_culvert = 'Culvert' in struct_type
                    if not is_bridge and not is_culvert:
                        continue

                    # Get abutment stations (opening limits)
                    # For bridges: Section 2 = Bridge Upstream (BU), Section 3 = Bridge Downstream (BD)
                    abut_left = 0.0
                    abut_right = 0.0
                    # Section-specific abutment stations for bridges (4-section model)
                    abut_us_left = 0.0   # Section 2 (BU) left abutment
                    abut_us_right = 0.0  # Section 2 (BU) right abutment
                    abut_ds_left = 0.0   # Section 3 (BD) left abutment
                    abut_ds_right = 0.0  # Section 3 (BD) right abutment
                    invert_elev = 0.0
                    deck_elev = 0.0
                    struct_width = 0.0

                    if is_bridge:
                        # Section 2 (Bridge Upstream face) abutments
                        if 'BR US Left Bank' in attr_names:
                            abut_us_left = float(attr['BR US Left Bank'])
                            abut_left = abut_us_left  # Default to US for backward compatibility
                        if 'BR US Right Bank' in attr_names:
                            abut_us_right = float(attr['BR US Right Bank'])
                            abut_right = abut_us_right
                        # Section 3 (Bridge Downstream face) abutments
                        if 'BR DS Left Bank' in attr_names:
                            abut_ds_left = float(attr['BR DS Left Bank'])
                        if 'BR DS Right Bank' in attr_names:
                            abut_ds_right = float(attr['BR DS Right Bank'])
                        if 'Low Chord' in attr_names:
                            invert_elev = float(attr['Low Chord'])
                        if 'High Chord' in attr_names:
                            deck_elev = float(attr['High Chord'])
                        elif 'Deck/Roadway' in attr_names:
                            deck_elev = float(attr['Deck/Roadway'])

                    elif is_culvert:
                        # For culverts, try to get barrel positions
                        if 'Culvert Left Sta' in attr_names:
                            abut_left = float(attr['Culvert Left Sta'])
                        if 'Culvert Right Sta' in attr_names:
                            abut_right = float(attr['Culvert Right Sta'])
                        if 'US Invert' in attr_names:
                            invert_elev = float(attr['US Invert'])
                        if 'Roadway Elev' in attr_names:
                            deck_elev = float(attr['Roadway Elev'])

                    # Calculate structure width from abutments
                    if abut_left > 0 and abut_right > 0:
                        struct_width = abs(abut_right - abut_left)

                    # Find encroachment data for this structure location
                    encr_match = encr_data[
                        (encr_data['river'] == river) &
                        (encr_data['reach'] == reach) &
                        (encr_data['station'].astype(str) == str(station))
                    ]

                    if encr_match.empty:
                        continue

                    encr_row = encr_match.iloc[0]
                    encr_l = encr_row.get('encr_sta_l', np.nan)
                    encr_r = encr_row.get('encr_sta_r', np.nan)

                    if pd.isna(encr_l) and pd.isna(encr_r):
                        continue  # No encroachment at this station

                    # Calculate floodway width
                    fw_width = 0.0
                    if not pd.isna(encr_l) and not pd.isna(encr_r):
                        fw_width = encr_r - encr_l

                    # =========================================================
                    # FW_ST_02L: Left encroachment inside bridge/culvert opening
                    # =========================================================
                    if not pd.isna(encr_l) and abut_left > 0:
                        if encr_l > abut_left:
                            # Left encroachment is to the right of left abutment (inside opening)
                            msg = CheckMessage(
                                message_id="FW_ST_02L",
                                severity=Severity.ERROR,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_02L",
                                    encr_sta=encr_l,
                                    station=station,
                                    abut_sta=abut_left),
                                help_text=get_help_text("FW_ST_02L"),
                                value=encr_l - abut_left
                            )
                            messages.append(msg)

                    # =========================================================
                    # FW_ST_02R: Right encroachment inside bridge/culvert opening
                    # =========================================================
                    if not pd.isna(encr_r) and abut_right > 0:
                        if encr_r < abut_right:
                            # Right encroachment is to the left of right abutment (inside opening)
                            msg = CheckMessage(
                                message_id="FW_ST_02R",
                                severity=Severity.ERROR,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_02R",
                                    encr_sta=encr_r,
                                    station=station,
                                    abut_sta=abut_right),
                                help_text=get_help_text("FW_ST_02R"),
                                value=abut_right - encr_r
                            )
                            messages.append(msg)

                    # =========================================================
                    # Section-Specific Floodway Checks for Bridges (4-Section Model)
                    # Section 2 = Bridge Upstream (BU), Section 3 = Bridge Downstream (BD)
                    # =========================================================
                    if is_bridge:
                        # Define section data for iteration
                        # Each tuple: (section_suffix, alt_suffix, left_abut, right_abut, section_name)
                        bridge_sections = []
                        if abut_us_left > 0 or abut_us_right > 0:
                            bridge_sections.append(('S2', 'BU', abut_us_left, abut_us_right, 'Bridge upstream'))
                        if abut_ds_left > 0 or abut_ds_right > 0:
                            bridge_sections.append(('S3', 'BD', abut_ds_left, abut_ds_right, 'Bridge downstream'))

                        for section_num, section_code, sect_abut_l, sect_abut_r, section_name in bridge_sections:
                            # =========================================================
                            # FW_ST_02 Section-Specific: Encroachment inside opening
                            # =========================================================
                            # Left encroachment inside opening at this section
                            if not pd.isna(encr_l) and sect_abut_l > 0:
                                if encr_l > sect_abut_l:
                                    # Use both S2/S3 and BU/BD message IDs
                                    for suffix in [f'{section_num}L', f'{section_code}L']:
                                        msg_id = f"FW_ST_02{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.ERROR,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_l,
                                                station=station,
                                                abut_sta=sect_abut_l),
                                            help_text=get_help_text(msg_id),
                                            value=encr_l - sect_abut_l
                                        )
                                        messages.append(msg)

                            # Right encroachment inside opening at this section
                            if not pd.isna(encr_r) and sect_abut_r > 0:
                                if encr_r < sect_abut_r:
                                    for suffix in [f'{section_num}R', f'{section_code}R']:
                                        msg_id = f"FW_ST_02{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.ERROR,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_r,
                                                station=station,
                                                abut_sta=sect_abut_r),
                                            help_text=get_help_text(msg_id),
                                            value=sect_abut_r - encr_r
                                        )
                                        messages.append(msg)

                            # =========================================================
                            # FW_ST_03 Section-Specific: Encroachment in abutment zone
                            # (encroachment near but not inside the opening)
                            # =========================================================
                            tolerance = 10.0  # 10 ft abutment zone
                            # Left encroachment in abutment zone
                            if not pd.isna(encr_l) and sect_abut_l > 0:
                                if encr_l <= sect_abut_l and encr_l > sect_abut_l - tolerance:
                                    for suffix in [f'{section_num}L', f'{section_code}L']:
                                        msg_id = f"FW_ST_03{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.WARNING,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_l,
                                                station=station,
                                                abut_sta=sect_abut_l),
                                            help_text=get_help_text(msg_id),
                                            value=sect_abut_l - encr_l
                                        )
                                        messages.append(msg)

                            # Right encroachment in abutment zone
                            if not pd.isna(encr_r) and sect_abut_r > 0:
                                if encr_r >= sect_abut_r and encr_r < sect_abut_r + tolerance:
                                    for suffix in [f'{section_num}R', f'{section_code}R']:
                                        msg_id = f"FW_ST_03{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.WARNING,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_r,
                                                station=station,
                                                abut_sta=sect_abut_r),
                                            help_text=get_help_text(msg_id),
                                            value=encr_r - sect_abut_r
                                        )
                                        messages.append(msg)

                            # =========================================================
                            # FW_ST_04 Section-Specific: Encroachment ends inside abutment
                            # (encroachment terminates within abutment structure)
                            # =========================================================
                            # Left encroachment ends inside abutment (terminates past left abutment toward channel)
                            if not pd.isna(encr_l) and sect_abut_l > 0:
                                # If left encroachment ends just past the abutment (within the abutment structure)
                                abutment_tolerance = 5.0  # 5 ft within abutment
                                if encr_l > sect_abut_l and encr_l < sect_abut_l + abutment_tolerance:
                                    for suffix in [f'{section_num}L', f'{section_code}L']:
                                        msg_id = f"FW_ST_04{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.WARNING,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_l,
                                                station=station,
                                                abut_sta=sect_abut_l),
                                            help_text=get_help_text(msg_id),
                                            value=encr_l - sect_abut_l
                                        )
                                        messages.append(msg)

                            # Right encroachment ends inside abutment
                            if not pd.isna(encr_r) and sect_abut_r > 0:
                                abutment_tolerance = 5.0
                                if encr_r < sect_abut_r and encr_r > sect_abut_r - abutment_tolerance:
                                    for suffix in [f'{section_num}R', f'{section_code}R']:
                                        msg_id = f"FW_ST_04{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.WARNING,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_r,
                                                station=station,
                                                abut_sta=sect_abut_r),
                                            help_text=get_help_text(msg_id),
                                            value=sect_abut_r - encr_r
                                        )
                                        messages.append(msg)

                            # =========================================================
                            # FW_ST_05 Section-Specific: Encroachment blocks flow area
                            # (encroachment significantly past opening limit)
                            # =========================================================
                            blockage_threshold = 5.0  # 5 ft past opening = blocking flow
                            # Left encroachment blocks flow
                            if not pd.isna(encr_l) and sect_abut_l > 0:
                                if encr_l > sect_abut_l + blockage_threshold:
                                    for suffix in [f'{section_num}L', f'{section_code}L']:
                                        msg_id = f"FW_ST_05{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.ERROR,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_l,
                                                station=station,
                                                opening_sta=sect_abut_l),
                                            help_text=get_help_text(msg_id),
                                            value=encr_l - sect_abut_l
                                        )
                                        messages.append(msg)

                            # Right encroachment blocks flow
                            if not pd.isna(encr_r) and sect_abut_r > 0:
                                if encr_r < sect_abut_r - blockage_threshold:
                                    for suffix in [f'{section_num}R', f'{section_code}R']:
                                        msg_id = f"FW_ST_05{suffix}"
                                        msg = CheckMessage(
                                            message_id=msg_id,
                                            severity=Severity.ERROR,
                                            check_type="FLOODWAY",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            message=format_message(msg_id,
                                                encr_sta=encr_r,
                                                station=station,
                                                opening_sta=sect_abut_r),
                                            help_text=get_help_text(msg_id),
                                            value=sect_abut_r - encr_r
                                        )
                                        messages.append(msg)

                    # =========================================================
                    # FW_ST_06: Floodway width exceeds structure opening width
                    # =========================================================
                    if fw_width > 0 and struct_width > 0:
                        if fw_width > struct_width:
                            msg = CheckMessage(
                                message_id="FW_ST_06",
                                severity=Severity.INFO,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_06",
                                    fw_width=fw_width,
                                    opening_width=struct_width,
                                    station=station),
                                help_text=get_help_text("FW_ST_06"),
                                value=fw_width - struct_width
                            )
                            messages.append(msg)

                    # =========================================================
                    # FW_ST_08: Floodway top width less than structure width
                    # =========================================================
                    if fw_width > 0 and struct_width > 0:
                        if fw_width < struct_width * 0.8:  # Less than 80% of structure width
                            msg = CheckMessage(
                                message_id="FW_ST_08",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_08",
                                    fw_tw=fw_width,
                                    struct_width=struct_width,
                                    station=station),
                                help_text=get_help_text("FW_ST_08"),
                                value=struct_width - fw_width
                            )
                            messages.append(msg)

                    # =========================================================
                    # FW_ST_11: Abutment within floodway limits
                    # =========================================================
                    if not pd.isna(encr_l) and not pd.isna(encr_r):
                        # Check if left abutment is within floodway
                        if abut_left > 0 and encr_l < abut_left < encr_r:
                            msg = CheckMessage(
                                message_id="FW_ST_11",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_11",
                                    station=station,
                                    side="left",
                                    abut_sta=abut_left),
                                help_text=get_help_text("FW_ST_11"),
                                value=abut_left
                            )
                            messages.append(msg)

                        # Check if right abutment is within floodway
                        if abut_right > 0 and encr_l < abut_right < encr_r:
                            msg = CheckMessage(
                                message_id="FW_ST_11",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_11",
                                    station=station,
                                    side="right",
                                    abut_sta=abut_right),
                                help_text=get_help_text("FW_ST_11"),
                                value=abut_right
                            )
                            messages.append(msg)

                    # =========================================================
                    # FW_ST_10: Pier within floodway encroachment limits
                    # =========================================================
                    if is_bridge and pier_data is not None and table_info is not None:
                        try:
                            struct_table = table_info[struct_idx]
                            pier_idx = int(struct_table['Pier (Index)']) if 'Pier (Index)' in struct_table.dtype.names else -1
                            pier_cnt = int(struct_table['Pier (Count)']) if 'Pier (Count)' in struct_table.dtype.names else 0

                            if pier_idx >= 0 and pier_cnt > 0:
                                for p in range(pier_cnt):
                                    pier_row = pier_data[pier_idx + p]
                                    pier_sta = float(pier_row['Sta']) if 'Sta' in pier_row.dtype.names else 0

                                    # Check if pier is within floodway limits
                                    if not pd.isna(encr_l) and not pd.isna(encr_r) and pier_sta > 0:
                                        if encr_l < pier_sta < encr_r:
                                            msg = CheckMessage(
                                                message_id="FW_ST_10",
                                                severity=Severity.INFO,
                                                check_type="FLOODWAY",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                message=format_message("FW_ST_10",
                                                    pier_num=p+1,
                                                    station=station,
                                                    pier_sta=pier_sta),
                                                help_text=get_help_text("FW_ST_10"),
                                                value=pier_sta
                                            )
                                            messages.append(msg)
                        except Exception:
                            pass  # Pier data parsing failed

                    # =========================================================
                    # FW_ST_12: Structure opening blocked by encroachment
                    # =========================================================
                    if struct_width > 0 and abut_left > 0 and abut_right > 0:
                        blocked_left = 0.0
                        blocked_right = 0.0

                        # Calculate left side blockage
                        if not pd.isna(encr_l) and encr_l > abut_left:
                            blocked_left = min(encr_l - abut_left, struct_width)

                        # Calculate right side blockage
                        if not pd.isna(encr_r) and encr_r < abut_right:
                            blocked_right = min(abut_right - encr_r, struct_width)

                        total_blocked = blocked_left + blocked_right
                        pct_blocked = (total_blocked / struct_width) * 100 if struct_width > 0 else 0

                        if pct_blocked > 25.0:  # More than 25% blockage
                            msg = CheckMessage(
                                message_id="FW_ST_12",
                                severity=Severity.WARNING,
                                check_type="FLOODWAY",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("FW_ST_12",
                                    station=station,
                                    pct_blocked=pct_blocked),
                                help_text=get_help_text("FW_ST_12"),
                                value=pct_blocked,
                                threshold=25.0
                            )
                            messages.append(msg)

            # =========================================================
            # FW_ST_13: Flow area reduction check (requires results data)
            # =========================================================
            try:
                with h5py.File(plan_hdf, 'r') as plan_h:
                    # Try to get flow area data for base and floodway profiles
                    area_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Flow Area'
                    if area_path not in plan_h:
                        area_path = 'Results/Steady/Output/Cross Sections/Flow Area'

                    if area_path in plan_h:
                        area_data = plan_h[area_path][:]

                        # Get profile indices
                        profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                        if profile_path not in plan_h:
                            profile_path = 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'

                        base_idx = -1
                        fw_idx = -1
                        if profile_path in plan_h:
                            profile_names = plan_h[profile_path][:]
                            for i, name in enumerate(profile_names):
                                name_str = name.decode('utf-8').strip() if isinstance(name, bytes) else str(name).strip()
                                if name_str == base_profile:
                                    base_idx = i
                                if name_str == floodway_profile:
                                    fw_idx = i

                        if base_idx >= 0 and fw_idx >= 0:
                            # Get structure attributes for matching
                            with h5py.File(geom_hdf, 'r') as geom_h:
                                if 'Geometry/Structures/Attributes' in geom_h:
                                    struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                                    xs_attrs_path = 'Geometry/Cross Sections/Attributes'
                                    xs_attrs = geom_h[xs_attrs_path][:] if xs_attrs_path in geom_h else None

                                    for struct_idx, attr in enumerate(struct_attrs):
                                        struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                                        river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                                        reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                                        station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                                        if 'Bridge' not in struct_type and 'Culvert' not in struct_type:
                                            continue

                                        # Find matching XS index for this structure
                                        if xs_attrs is not None:
                                            for xs_idx, xs in enumerate(xs_attrs):
                                                xs_river = xs['River'].decode('utf-8').strip() if isinstance(xs['River'], bytes) else str(xs['River']).strip()
                                                xs_reach = xs['Reach'].decode('utf-8').strip() if isinstance(xs['Reach'], bytes) else str(xs['Reach']).strip()
                                                xs_station = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()

                                                if xs_river == river and xs_reach == reach and xs_station == station:
                                                    # Get flow areas for base and floodway
                                                    if area_data.ndim == 2:
                                                        base_area = float(area_data[xs_idx, base_idx]) if xs_idx < area_data.shape[0] else 0
                                                        fw_area = float(area_data[xs_idx, fw_idx]) if xs_idx < area_data.shape[0] else 0
                                                    else:
                                                        base_area = 0
                                                        fw_area = 0

                                                    if base_area > 0 and fw_area > 0:
                                                        pct_reduction = ((base_area - fw_area) / base_area) * 100

                                                        if pct_reduction > 30.0:  # More than 30% reduction
                                                            msg = CheckMessage(
                                                                message_id="FW_ST_13",
                                                                severity=Severity.WARNING,
                                                                check_type="FLOODWAY",
                                                                river=river,
                                                                reach=reach,
                                                                station=station,
                                                                message=format_message("FW_ST_13",
                                                                    pct_reduction=pct_reduction,
                                                                    station=station,
                                                                    base_area=base_area,
                                                                    fw_area=fw_area),
                                                                help_text=get_help_text("FW_ST_13"),
                                                                value=pct_reduction,
                                                                threshold=30.0
                                                            )
                                                            messages.append(msg)
                                                    break

            except Exception as e:
                logger.debug(f"Could not check flow area reduction at structures: {e}")

        except Exception as e:
            logger.warning(f"Could not check structure floodway encroachments: {e}")

        return messages
