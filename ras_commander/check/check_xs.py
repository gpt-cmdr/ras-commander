"""
CheckXs - Cross section validation.

Extracted from RasCheck.py for modular organization.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union

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


class CheckXs:
    """Cross section validation."""

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
            regime_messages = CheckXs._check_flow_regime_transitions(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(regime_messages)

        # =====================================================================
        # XS_DC_01: Discharge Conservation Check
        # Check for flow changes within a reach
        # =====================================================================
        if steady_results is not None and not steady_results.empty:
            discharge_messages = CheckXs._check_discharge_conservation(
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
            area_messages = CheckXs._check_flow_area_changes(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(area_messages)

            # XS_SL_01/02: Water Surface Slope Anomalies
            slope_messages = CheckXs._check_wse_slope(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(slope_messages)

            # XS_EGL_01: Energy Grade Line Reversals
            egl_messages = CheckXs._check_energy_grade_line(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(egl_messages)

            # XS_TW_02: Top Width Changes Between Adjacent Sections
            tw_messages = CheckXs._check_top_width_changes(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(tw_messages)

            # XS_EL_01/02: Energy Loss Checks
            eloss_messages = CheckXs._check_energy_loss(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(eloss_messages)

            # XS_HK_01 and XS_VD_01: Hydraulic Properties Checks
            hydprop_messages = CheckXs._check_hydraulic_properties(
                xs_gdf, steady_results, thresholds
            )
            messages.extend(hydprop_messages)

        # =====================================================================
        # XS_LV_01/02/03: Levee Definition Checks
        # Check levee station and elevation against cross section geometry
        # =====================================================================
        levee_messages = CheckXs._check_levees(xs_gdf, thresholds)
        messages.extend(levee_messages)

        # =====================================================================
        # XS_CT_03/04: Contraction Coefficient Checks
        # XS_CW_01: Channel Width Ratio Checks
        # Check coefficient consistency and channel width ratios between sections
        # =====================================================================
        coef_width_messages = CheckXs._check_contraction_coefficients_and_widths(
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
