"""
CheckProfiles - Multiple profile consistency validation.

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


class CheckProfiles:
    """Multiple profile consistency validation."""

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
            logger.error("Failed to read steady results for profile checks")
            logger.debug("Profile steady-results read failure for %s: %s", plan_hdf, e)
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

        # =====================================================================
        # Starting WSE Method Validation Checks
        # NOTE: Only applicable to unsteady flow plans. For steady flow,
        # boundary conditions are per-profile and stored in the .f## file,
        # not in the HDF. The "starting WSE" concept applies to unsteady
        # flow initial conditions at simulation start time.
        # =====================================================================
        from ..hdf.HdfPlan import HdfPlan

        # Detect flow type - only run starting WSE checks for unsteady plans
        flow_type = _utils.detect_flow_type(plan_hdf)

        # Skip starting WSE validation for steady flow plans
        if flow_type == FlowType.STEADY:
            logger.debug("Skipping starting WSE validation for steady flow plan (BCs are per-profile in .f## file)")
        elif flow_type == FlowType.GEOMETRY_ONLY:
            logger.debug("Skipping starting WSE validation for geometry-only plan (no results)")
        else:
            # Unsteady flow - run starting WSE validation
            try:
                # Get starting WSE method from plan HDF
                wse_method_info = HdfPlan.get_starting_wse_method(plan_hdf)
                method = wse_method_info.get('method', 'Unknown')

                # PF_IC_01: Known WSE validation
                if 'Known' in method:
                    known_wse = wse_method_info.get('wse', None)
                    if known_wse is not None:
                        # Check if known WSE is reasonable (not too high or too low)
                        if known_wse < -100 or known_wse > 10000:
                            msg = CheckMessage(
                                message_id="PF_IC_01",
                                severity=Severity.WARNING,
                                check_type="PROFILES",
                                message=f"Known WSE ({known_wse:.2f} ft) may be unreasonable for starting water surface",
                                help_text="Known WSE should be within realistic elevation range for the project area.",
                                value=known_wse
                            )
                            messages.append(msg)

                # PF_IC_02: Normal depth slope reasonableness
                elif 'Normal' in method:
                    slope = wse_method_info.get('slope', None)
                    if slope is not None:
                        # Check if slope is reasonable (typical range: 0.0001 to 0.1)
                        if abs(slope) < 0.0001:
                            msg = CheckMessage(
                                message_id="PF_IC_02",
                                severity=Severity.WARNING,
                                check_type="PROFILES",
                                message=f"Normal depth slope ({slope:.6f}) may be too flat for convergence",
                                help_text="Very flat slopes (< 0.0001) may cause convergence issues. Verify slope is appropriate for channel.",
                                value=abs(slope),
                                threshold="0.0001"
                            )
                            messages.append(msg)
                        elif abs(slope) > 0.1:
                            msg = CheckMessage(
                                message_id="PF_IC_02",
                                severity=Severity.WARNING,
                                check_type="PROFILES",
                                message=f"Normal depth slope ({slope:.6f}) may be too steep",
                                help_text="Very steep slopes (> 0.1) are unusual. Verify slope is appropriate for channel.",
                                value=abs(slope),
                                threshold="0.1"
                            )
                            messages.append(msg)

                # PF_IC_03: Critical depth applicability
                elif 'Critical' in method:
                    # Check if critical depth is appropriate (INFO message)
                    msg = CheckMessage(
                        message_id="PF_IC_03",
                        severity=Severity.INFO,
                        check_type="PROFILES",
                        message="Critical depth used for starting water surface - appropriate for steep slopes and supercritical flow",
                        help_text="Critical depth is appropriate when Froude number > 1.0 (supercritical flow). Verify flow regime is supercritical."
                    )
                    messages.append(msg)

                # PF_IC_04: Energy grade line method verification
                elif 'EGL' in method or 'Energy' in method:
                    # Check if EGL slope line method is used (INFO message)
                    msg = CheckMessage(
                        message_id="PF_IC_04",
                        severity=Severity.INFO,
                        check_type="PROFILES",
                        message="Energy grade line slope method used for starting water surface",
                        help_text="EGL slope method is appropriate for gradually varied flow. Verify energy slope is reasonable."
                    )
                    messages.append(msg)

                # If method is Unknown or Error, add warning
                elif method in ['Unknown', 'Error']:
                    msg = CheckMessage(
                        message_id="PF_IC_00",
                        severity=Severity.WARNING,
                        check_type="PROFILES",
                        message=f"Starting WSE method could not be determined: {wse_method_info.get('note', 'Unknown reason')}",
                        help_text="Verify boundary condition method is properly defined in plan file."
                    )
                    messages.append(msg)

            except Exception as e:
                logger.debug(f"Could not validate starting WSE method: {e}")

        results.messages = messages
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df['issues'] = summary_df['issues'].apply(lambda x: ', '.join(x) if x else '')
            results.profiles_summary = summary_df

        return results
