"""
CheckFloodways - Floodway encroachment validation.

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
from .check_structures import CheckStructures

logger = get_logger(__name__)


class CheckFloodways:
    """Floodway encroachment validation."""

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
        encroachment_msgs = CheckFloodways._check_encroachment_data(
            plan_hdf, geom_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(encroachment_msgs)

        # Check for discharge changes within floodway reach
        discharge_msgs = CheckFloodways._check_floodway_discharge_conservation(
            steady_results, floodway_profile
        )
        messages.extend(discharge_msgs)

        # ST_IF_05: Check for permanent ineffective flow at structures (problematic in floodway)
        perm_ineff_msgs = CheckStructures._check_structure_permanent_ineffective(geom_hdf, is_floodway=True)
        messages.extend(perm_ineff_msgs)

        # FW_EM_*: Check encroachment methods
        encr_method_msgs = CheckFloodways._check_floodway_encroachment_methods(
            plan_hdf, geom_hdf, floodway_profile, thresholds
        )
        messages.extend(encr_method_msgs)

        # FW_BC_*: Check boundary conditions
        bc_msgs = CheckFloodways._check_floodway_boundary_conditions(
            plan_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(bc_msgs)

        # FW_SW_*: Check starting WSE (includes method-specific variants)
        sw_msgs = CheckFloodways._check_floodway_starting_wse(
            plan_hdf, steady_results, geom_hdf, base_profile, floodway_profile, thresholds
        )
        messages.extend(sw_msgs)

        # FW_LW_*: Check lateral weirs
        lw_msgs = CheckFloodways._check_floodway_lateral_weirs(
            plan_hdf, geom_hdf, floodway_profile, thresholds
        )
        messages.extend(lw_msgs)

        results.messages = messages
        results.floodway_summary = pd.DataFrame(summary_records)
        return results

    @staticmethod
    @log_call

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
            encr_data = CheckFloodways._get_encroachment_stations(plan_hdf, floodway_profile)

            if encr_data is None or encr_data.empty:
                # No encroachment data found - could be Method 1 or no encroachments
                logger.debug("No encroachment data found in plan HDF")
                return messages

            # Get cross section data for bank station comparison
            from ..hdf.HdfXsec import HdfXsec
            xs_gdf = HdfXsec.get_cross_sections(geom_hdf)

            # Get structure data for abutment comparison
            struct_data = _utils.get_structure_locations(geom_hdf)

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
    def _get_structure_locations(geom_hdf):
        """Delegate to _utils.get_structure_locations."""
        return _utils.get_structure_locations(geom_hdf)

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
            encr_data = CheckFloodways._get_encroachment_stations(plan_hdf, floodway_profile)

            if encr_data is None or encr_data.empty:
                return messages

            # Get structure locations to identify structure vs non-structure XS
            struct_data = _utils.get_structure_locations(geom_hdf)
            struct_stations = set()
            if struct_data is not None and not struct_data.empty:
                for _, row in struct_data.iterrows():
                    key = (row.get('river', ''), row.get('reach', ''), str(row.get('station', '')))
                    struct_stations.add(key)

            # Track encroachment methods by reach
            reach_methods = {}

            # Try to get encroachment parameters from plan HDF for Method 5 checks
            encr_params = CheckFloodways._get_encroachment_parameters(plan_hdf, floodway_profile)

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
            encr_data = CheckFloodways._get_encroachment_stations(plan_hdf, floodway_profile)
            encr_params = CheckFloodways._get_encroachment_parameters(plan_hdf, floodway_profile)

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
            encr_data = CheckFloodways._get_encroachment_stations(plan_hdf, floodway_profile)
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
