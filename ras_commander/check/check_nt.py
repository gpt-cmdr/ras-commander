"""
CheckNt - Manning's n values and HTAB parameter validation.

Extracted from RasCheck.py for modular organization.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import numpy as np
import h5py

from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from .types import Severity, FlowType, CheckMessage, CheckResults
from .thresholds import ValidationThresholds, get_default_thresholds
from .messages import get_message_template, get_help_text, format_message
from . import _utils

logger = get_logger(__name__)


class CheckNt:
    """Manning's n values and HTAB parameter validation."""

    # =========================================================================
    # STEADY FLOW CHECK METHODS
    # =========================================================================

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
        variation_messages = CheckNt._check_n_value_variation(xs_gdf, thresholds)
        messages.extend(variation_messages)

        # =====================================================================
        # NT_TL_01: Transition Coefficients at Structure Sections
        # Check structure sections (2, 3, 4) for proper 0.3/0.5 coefficients
        # =====================================================================
        struct_trans_messages = CheckNt._check_structure_transition_coefficients(geom_hdf, xs_gdf, thresholds)
        messages.extend(struct_trans_messages)

        # =====================================================================
        # Bridge Section Manning's n Checks (NT_RS_*)
        # Only run when bridges have custom internal Manning's n
        # =====================================================================
        bridge_messages = CheckNt._check_bridge_section_mannings_n(geom_hdf, thresholds)
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
    def check_htab_params(
        geom_file: Union[str, Path],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check HTAB (Hydraulic Table) parameters for cross sections.

        Validates HTAB parameters against best practices:
        - Starting elevation must be >= cross section invert
        - Starting elevation should not be too far above invert
        - Increment should not be excessively large
        - Number of points should be adequate for accuracy

        This is a SEPARATE check method, not integrated into xs_check().

        Args:
            geom_file: Path to geometry file (.g##) - NOT HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with HTAB validation messages and summary DataFrame

        Example:
            >>> from ras_commander.check import RasCheck
            >>> results = CheckNt.check_htab_params("model.g01")
            >>> print(f"Found {results.get_error_count()} HTAB errors")

        Notes:
            - Requires plain text geometry file, not HDF
            - Uses GeomCrossSection to read HTAB parameters
            - ERROR: starting_el < invert (HEC-RAS requirement)
            - WARNING: starting_el > invert + threshold (may miss low flows)
            - WARNING: increment > threshold (interpolation accuracy)
            - INFO: num_points < minimum (table resolution)
        """
        from ..geom.GeomCrossSection import GeomCrossSection
        import math

        results = CheckResults()
        messages = []
        summary_data = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        geom_file = Path(geom_file)

        if not geom_file.exists():
            msg = CheckMessage(
                message_id="SYS_001",
                severity=Severity.ERROR,
                check_type="HTAB",
                message=f"Geometry file not found: {geom_file}"
            )
            results.messages.append(msg)
            return results

        # Use configurable thresholds from HtabThresholds
        se_above_invert_threshold = thresholds.htab.xs_se_above_invert_threshold
        increment_warn_threshold = 1.0   # ft - warn if increment > this
        optimal_points = thresholds.htab.xs_optimal_points  # 500
        optimal_increment = thresholds.htab.xs_optimal_increment  # 0.1

        try:
            # Get all cross sections from geometry file
            xs_df = GeomCrossSection.get_cross_sections(geom_file)
            # Filter to Type 1 (real cross sections) only - excludes lateral
            # structures (Type 6), bridges, culverts, etc. which lack #Sta/Elev data
            if 'Type' in xs_df.columns:
                xs_df = xs_df[xs_df['Type'] == 1].reset_index(drop=True)

            if xs_df.empty:
                logger.info(f"No cross sections found in {geom_file.name}")
                results.messages = messages
                return results

            logger.info(f"Checking HTAB parameters for {len(xs_df)} cross sections")

            for _, row in xs_df.iterrows():
                river = row['River']
                reach = row['Reach']
                rs = row['RS']
                issues = []

                try:
                    # Get HTAB parameters for this XS
                    htab_params = GeomCrossSection.get_xs_htab_params(
                        geom_file, river, reach, rs
                    )

                    starting_el = htab_params.get('starting_el')
                    increment = htab_params.get('increment')
                    num_points = htab_params.get('num_points')
                    invert = htab_params.get('invert')

                    # Skip if no HTAB params defined
                    if starting_el is None and increment is None and num_points is None:
                        continue

                    # Check 1: starting_el < invert (ERROR)
                    if starting_el is not None and invert is not None:
                        if starting_el < invert:
                            msg = CheckMessage(
                                message_id="HTAB_SE_01",
                                severity=Severity.ERROR,
                                check_type="HTAB",
                                river=river,
                                reach=reach,
                                station=str(rs),
                                message=format_message(
                                    "HTAB_SE_01",
                                    starting_el=starting_el,
                                    invert=invert,
                                    river=river,
                                    reach=reach,
                                    station=rs
                                ),
                                value=starting_el,
                                threshold=invert,
                                help_text=get_help_text("HTAB_SE_01")
                            )
                            messages.append(msg)
                            issues.append("SE<invert")

                        # Check 2: starting_el > invert + threshold (WARNING)
                        elif starting_el > invert + se_above_invert_threshold:
                            msg = CheckMessage(
                                message_id="HTAB_SE_02",
                                severity=Severity.WARNING,
                                check_type="HTAB",
                                river=river,
                                reach=reach,
                                station=str(rs),
                                message=format_message(
                                    "HTAB_SE_02",
                                    starting_el=starting_el,
                                    threshold=se_above_invert_threshold,
                                    invert=invert,
                                    river=river,
                                    reach=reach,
                                    station=rs
                                ),
                                value=starting_el,
                                threshold=invert + se_above_invert_threshold,
                                help_text=get_help_text("HTAB_SE_02")
                            )
                            messages.append(msg)
                            issues.append("SE>invert+threshold")

                    # Check 3: increment > threshold (WARNING)
                    if increment is not None and increment > increment_warn_threshold:
                        msg = CheckMessage(
                            message_id="HTAB_INC_01",
                            severity=Severity.WARNING,
                            check_type="HTAB",
                            river=river,
                            reach=reach,
                            station=str(rs),
                            message=format_message(
                                "HTAB_INC_01",
                                increment=increment,
                                threshold=increment_warn_threshold,
                                river=river,
                                reach=reach,
                                station=rs
                            ),
                            value=increment,
                            threshold=increment_warn_threshold,
                            help_text=get_help_text("HTAB_INC_01")
                        )
                        messages.append(msg)
                        issues.append("large_increment")

                    # Check 4: num_points < optimal (INFO)
                    if num_points is not None and num_points < optimal_points:
                        msg = CheckMessage(
                            message_id="HTAB_PTS_02",
                            severity=Severity.INFO,
                            check_type="HTAB",
                            river=river,
                            reach=reach,
                            station=str(rs),
                            message=format_message(
                                "HTAB_PTS_02",
                                num_points=num_points,
                                optimal_points=optimal_points,
                                river=river,
                                reach=reach,
                                station=rs
                            ),
                            value=num_points,
                            threshold=optimal_points,
                            help_text=get_help_text("HTAB_PTS_02")
                        )
                        messages.append(msg)
                        issues.append("suboptimal_points")

                    # Check 5: non-optimal increment (INFO)
                    if increment is not None and num_points is not None:
                        if abs(increment - optimal_increment) > 1e-6:
                            depth_range = num_points * increment
                            msg = CheckMessage(
                                message_id="HTAB_INC_02",
                                severity=Severity.INFO,
                                check_type="HTAB",
                                river=river,
                                reach=reach,
                                station=str(rs),
                                message=format_message(
                                    "HTAB_INC_02",
                                    increment=increment,
                                    num_points=num_points,
                                    depth_range=depth_range,
                                    river=river,
                                    reach=reach,
                                    station=rs
                                ),
                                value=increment,
                                threshold=optimal_increment,
                                help_text=get_help_text("HTAB_INC_02")
                            )
                            messages.append(msg)
                            issues.append("non_optimal_increment")

                    # Add to summary
                    summary_data.append({
                        'River': river,
                        'Reach': reach,
                        'RS': rs,
                        'starting_el': starting_el,
                        'increment': increment,
                        'num_points': num_points,
                        'invert': invert,
                        'issues': issues
                    })

                except Exception as e:
                    logger.warning(f"Error checking HTAB for {river}/{reach}/RS {rs}: {e}")
                    continue

            results.messages = messages

            if summary_data:
                summary_df = pd.DataFrame(summary_data)
                # Convert issues list to string for display
                summary_df['issues'] = summary_df['issues'].apply(
                    lambda x: ', '.join(x) if x else ''
                )
                results.xs_summary = summary_df  # Reuse xs_summary for HTAB results

            logger.info(
                f"HTAB check complete: {len(messages)} issues found "
                f"({len([m for m in messages if m.severity == Severity.ERROR])} errors, "
                f"{len([m for m in messages if m.severity == Severity.WARNING])} warnings)"
            )

        except Exception as e:
            logger.error(f"Failed to check HTAB parameters: {e}")
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Failed to check HTAB parameters: {e}"
            )
            results.messages.append(msg)

        return results

    @staticmethod
    @log_call
    def check_structure_htab_params(
        geom_file: Union[str, Path],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check HTAB parameters for internal boundary structures (bridges, culverts, inline weirs).

        Validates structure HTAB parameters against optimal values:
        - Free flow curve points (optimal 100)
        - Number of submerged rating curves (optimal 60)
        - Points per submerged curve (optimal 50)

        All findings are INFO severity - suboptimal values are improvement opportunities,
        not modeling errors.

        Args:
            geom_file: Path to geometry file (.g##) - NOT HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with structure HTAB validation messages

        Example:
            >>> from ras_commander.check import RasCheck
            >>> results = CheckNt.check_structure_htab_params("model.g01")
            >>> for msg in results.messages:
            ...     print(f"[{msg.severity.name}] {msg.message}")

        Note:
            Roadmap: A future enhancement could fit recommended HTAB values to
            current 1D results â€” e.g., set hw_max/tw_max from observed envelopes.
            This would only apply to models with existing HDF results.
        """
        from ..geom.GeomBridge import GeomBridge
        from ..geom.GeomInlineWeir import GeomInlineWeir

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        geom_file = Path(geom_file)

        if not geom_file.exists():
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="HTAB",
                message=f"Geometry file not found: {geom_file}"
            )
            results.messages.append(msg)
            return results

        # Optimal values from thresholds
        optimal_ff = thresholds.htab.structure_optimal_ff_points
        optimal_rc = thresholds.htab.structure_optimal_sub_curves
        optimal_prc = thresholds.htab.structure_optimal_pts_per_curve

        try:
            # Get all bridge/culvert and inline weir structures from the geometry
            bridges_df = GeomBridge.get_bridges(geom_file)
            weirs_df = GeomInlineWeir.get_weirs(geom_file)

            structure_rows = []

            if bridges_df is not None and not bridges_df.empty:
                structure_rows.extend(bridges_df.to_dict('records'))

            if weirs_df is not None and not weirs_df.empty:
                structure_rows.extend(weirs_df.to_dict('records'))

            if not structure_rows:
                logger.info(f"No bridges/structures found in {geom_file.name}")
                results.messages = messages
                return results

            logger.info(
                f"Checking structure HTAB parameters for {len(structure_rows)} structures"
            )

            for row in structure_rows:
                river = row.get('River', '')
                reach = row.get('Reach', '')
                rs = str(row.get('RS', ''))
                structure_name = f"{river}/{reach}/RS {rs}"

                try:
                    # Get HTAB parameters for this structure
                    htab_params = GeomBridge.get_htab_dict(
                        geom_file,
                        river,
                        reach,
                        rs,
                        include_invert=False
                    )

                    if htab_params is None:
                        continue

                    ff_points = htab_params.get('free_flow_points')
                    sub_curves = htab_params.get('submerged_curves')
                    pts_per_curve = htab_params.get('points_per_curve')

                    # Check free flow points
                    if ff_points is not None and ff_points < optimal_ff:
                        msg = CheckMessage(
                            message_id="HTAB_STR_FF_01",
                            severity=Severity.INFO,
                            check_type="HTAB",
                            river=river,
                            reach=reach,
                            station=str(rs),
                            structure=structure_name,
                            message=format_message(
                                "HTAB_STR_FF_01",
                                structure_name=structure_name,
                                ff_points=ff_points,
                                optimal_ff=optimal_ff
                            ),
                            value=ff_points,
                            threshold=optimal_ff,
                            help_text=get_help_text("HTAB_STR_FF_01")
                        )
                        messages.append(msg)

                    # Check submerged rating curves
                    if sub_curves is not None and sub_curves < optimal_rc:
                        msg = CheckMessage(
                            message_id="HTAB_STR_RC_01",
                            severity=Severity.INFO,
                            check_type="HTAB",
                            river=river,
                            reach=reach,
                            station=str(rs),
                            structure=structure_name,
                            message=format_message(
                                "HTAB_STR_RC_01",
                                structure_name=structure_name,
                                sub_curves=sub_curves,
                                optimal_rc=optimal_rc
                            ),
                            value=sub_curves,
                            threshold=optimal_rc,
                            help_text=get_help_text("HTAB_STR_RC_01")
                        )
                        messages.append(msg)

                    # Check points per curve
                    if pts_per_curve is not None and pts_per_curve < optimal_prc:
                        msg = CheckMessage(
                            message_id="HTAB_STR_PRC_01",
                            severity=Severity.INFO,
                            check_type="HTAB",
                            river=river,
                            reach=reach,
                            station=str(rs),
                            structure=structure_name,
                            message=format_message(
                                "HTAB_STR_PRC_01",
                                structure_name=structure_name,
                                pts_per_curve=pts_per_curve,
                                optimal_prc=optimal_prc
                            ),
                            value=pts_per_curve,
                            threshold=optimal_prc,
                            help_text=get_help_text("HTAB_STR_PRC_01")
                        )
                        messages.append(msg)

                except Exception as e:
                    logger.warning(f"Error checking structure HTAB for {structure_name}: {e}")
                    continue

            results.messages = messages

            logger.info(
                f"Structure HTAB check complete: {len(messages)} info items found"
            )

        except Exception as e:
            logger.error(f"Failed to check structure HTAB parameters: {e}")
            msg = CheckMessage(
                message_id="SYS_002",
                severity=Severity.ERROR,
                check_type="SYSTEM",
                message=f"Failed to check structure HTAB parameters: {e}"
            )
            results.messages.append(msg)

        return results

    # =========================================================================
    # Subgrid Sampling Options Check (2D Flow Areas)
    # =========================================================================

    @staticmethod
    @log_call
    def check_subgrid_sampling(
        geom_file: Union[str, Path],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check whether 2D flow areas have subgrid sampling options enabled.

        For HEC-RAS 6.x models with 2D flow areas, recommends enabling:
        - Spatially Varied Manning's n on Faces
        - Composite Classification Values in Cells

        These settings significantly improve hydraulic accuracy by using
        land-cover-based roughness at each face and weighted composite
        classification within each cell, rather than a single default value.

        Reference:
            https://www.hec.usace.army.mil/confluence/rasdocs/d2sd/ras2dsedtr/latest/numerical-methods/subgrid-concept

        Args:
            geom_file: Path to geometry file (.g##) - NOT HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with subgrid sampling suggestion messages
        """
        from ..geom.GeomStorage import GeomStorage

        results = CheckResults()
        messages = []

        geom_file = Path(geom_file)
        if not geom_file.exists():
            logger.warning(f"Geometry file not found for subgrid check: {geom_file}")
            return results

        try:
            settings = GeomStorage.get_2d_flow_area_settings(geom_file)

            if settings.empty:
                logger.debug("No 2D flow areas found - subgrid sampling check skipped")
                return results

            for _, row in settings.iterrows():
                flow_area = row['name']
                spatial = row['spatially_varied_mann_on_faces']
                composite = row['composite_classification']

                if spatial and composite:
                    # Both enabled - good
                    msg = CheckMessage(
                        message_id="NT_SG_03",
                        severity=Severity.INFO,
                        check_type="NT",
                        structure=flow_area,
                        message=format_message("NT_SG_03", flow_area=flow_area),
                        help_text=get_help_text("NT_SG_03")
                    )
                    messages.append(msg)
                else:
                    if not spatial:
                        msg = CheckMessage(
                            message_id="NT_SG_01",
                            severity=Severity.WARNING,
                            check_type="NT",
                            structure=flow_area,
                            message=format_message("NT_SG_01", flow_area=flow_area),
                            help_text=get_help_text("NT_SG_01")
                        )
                        messages.append(msg)

                    if not composite:
                        msg = CheckMessage(
                            message_id="NT_SG_02",
                            severity=Severity.WARNING,
                            check_type="NT",
                            structure=flow_area,
                            message=format_message("NT_SG_02", flow_area=flow_area),
                            help_text=get_help_text("NT_SG_02")
                        )
                        messages.append(msg)

            results.messages = messages

            logger.info(
                f"Subgrid sampling check: {len(settings)} 2D flow areas, "
                f"{len([m for m in messages if m.severity == Severity.WARNING])} suggestions"
            )

        except Exception as e:
            logger.error(f"Failed to check subgrid sampling options: {e}")

        return results

    # =========================================================================
    # N-Value Variation and Structure Transition Checks
    # (Moved from CheckStructures - these are NT checks, not structure checks)
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
                bridge_data = CheckNt._get_bridge_section_mannings_n(geom_hdf, bridge_idx)

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
                    sec1_channel_n = CheckNt._get_channel_n_from_regions(section_1_n, left_bank, right_bank)
                    sec2_channel_n = CheckNt._get_channel_n_from_regions(section_2_n, left_bank, right_bank)

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
                    differences = CheckNt._compare_n_regions(section_1_n, section_2_n)
                    if differences:
                        # Summarize differences
                        diff_summary = "; ".join([
                            f"sta {d['station']:.0f}: {d['n1']:.3f}\u2192{d['n2']:.3f}"
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
                    sec3_channel_n = CheckNt._get_channel_n_from_regions(section_3_n, left_bank, right_bank)
                    sec4_channel_n = CheckNt._get_channel_n_from_regions(section_4_n, left_bank, right_bank)

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
                    differences = CheckNt._compare_n_regions(section_4_n, section_3_n)
                    if differences:
                        # Summarize differences
                        diff_summary = "; ".join([
                            f"sta {d['station']:.0f}: {d['n1']:.3f}\u2192{d['n2']:.3f}"
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
