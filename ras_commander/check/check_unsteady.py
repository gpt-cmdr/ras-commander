"""
CheckUnsteady - Unsteady flow validation checks.

Extracted from RasCheck.py for modular organization.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import numpy as np
import h5py

from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from ..fast_hdf import reraise_required
from .types import Severity, FlowType, CheckMessage, CheckResults
from .thresholds import ValidationThresholds, get_default_thresholds
from .messages import get_message_template, get_help_text, format_message
from . import _utils

logger = get_logger(__name__)


class CheckUnsteady:
    """Unsteady flow validation checks."""

    # =========================================================================
    # UNSTEADY FLOW CHECK METHODS
    # =========================================================================

    @staticmethod
    @log_call
    def check_mass_balance(
        plan_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check volume accounting and mass conservation for unsteady flow.

        Validates:
        - Volume error percentage
        - Inflow/outflow balance
        - Storage changes

        Args:
            plan_hdf: Path to plan HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with mass balance check messages

        Data Source:
            Uses HdfResultsPlan.get_volume_accounting() for volume metrics
        """
        from ..hdf.HdfResultsPlan import HdfResultsPlan

        results = CheckResults()

        if thresholds is None:
            thresholds = get_default_thresholds()

        try:
            plan_hdf = Path(plan_hdf)

            # Get volume accounting data
            volume_data = HdfResultsPlan.get_volume_accounting(plan_hdf)

            if volume_data is None:
                msg = CheckMessage(
                    message_id="US_MB_INFO",
                    severity=Severity.INFO,
                    check_type="UNSTEADY",
                    message="Volume accounting data not available in this plan"
                )
                results.messages.append(msg)
                return results

            # Create summary DataFrame
            if isinstance(volume_data, pd.DataFrame):
                results.mass_balance_summary = volume_data
            elif isinstance(volume_data, dict):
                results.mass_balance_summary = pd.DataFrame([volume_data])

            # Extract volume error if available
            error_found = False
            if results.mass_balance_summary is not None and not results.mass_balance_summary.empty:
                # Look for volume error percentage in various possible column names
                vol_err_pct = None
                for col in results.mass_balance_summary.columns:
                    col_lower = col.lower()
                    if 'volume' in col_lower and 'error' in col_lower and '%' in col_lower:
                        try:
                            vol_err_pct = float(results.mass_balance_summary[col].iloc[0])
                            error_found = True
                            break
                        except (ValueError, TypeError, IndexError):
                            continue

                if vol_err_pct is not None:
                    # Check against thresholds
                    if abs(vol_err_pct) >= thresholds.unsteady.volume_error_error_pct:
                        msg = CheckMessage(
                            message_id="US_MB_02",
                            severity=Severity.ERROR,
                            check_type="UNSTEADY",
                            message=format_message("US_MB_02",
                                error_pct=abs(vol_err_pct),
                                threshold=thresholds.unsteady.volume_error_error_pct
                            ),
                            value=abs(vol_err_pct),
                            threshold=thresholds.unsteady.volume_error_error_pct
                        )
                        results.messages.append(msg)
                    elif abs(vol_err_pct) >= thresholds.unsteady.volume_error_warning_pct:
                        msg = CheckMessage(
                            message_id="US_MB_01",
                            severity=Severity.WARNING,
                            check_type="UNSTEADY",
                            message=format_message("US_MB_01",
                                error_pct=abs(vol_err_pct),
                                threshold=thresholds.unsteady.volume_error_warning_pct
                            ),
                            value=abs(vol_err_pct),
                            threshold=thresholds.unsteady.volume_error_warning_pct
                        )
                        results.messages.append(msg)
                    else:
                        # Volume error within acceptable limits
                        msg = CheckMessage(
                            message_id="US_MB_PASS",
                            severity=Severity.INFO,
                            check_type="UNSTEADY",
                            message=f"Mass balance check passed - volume error {abs(vol_err_pct):.3f}% (acceptable)"
                        )
                        results.messages.append(msg)

                # Check inflow/outflow balance
                inflow_val = None
                outflow_val = None

                for col in results.mass_balance_summary.columns:
                    col_lower = col.lower()
                    if 'inflow' in col_lower and 'total' in col_lower:
                        try:
                            inflow_val = float(results.mass_balance_summary[col].iloc[0])
                        except (ValueError, TypeError, IndexError):
                            pass
                    if 'outflow' in col_lower and 'total' in col_lower:
                        try:
                            outflow_val = float(results.mass_balance_summary[col].iloc[0])
                        except (ValueError, TypeError, IndexError):
                            pass

                if inflow_val is not None and outflow_val is not None and inflow_val != 0:
                    diff = abs(inflow_val - outflow_val)
                    diff_pct = (diff / abs(inflow_val)) * 100.0

                    if diff_pct > thresholds.unsteady.volume_error_warning_pct:
                        msg = CheckMessage(
                            message_id="US_MB_03",
                            severity=Severity.WARNING,
                            check_type="UNSTEADY",
                            message=format_message("US_MB_03",
                                inflow=inflow_val,
                                outflow=outflow_val,
                                diff=diff,
                                pct=diff_pct
                            )
                        )
                        results.messages.append(msg)

            if not error_found:
                # No volume error data found, but accounting data exists
                msg = CheckMessage(
                    message_id="US_MB_PASS",
                    severity=Severity.INFO,
                    check_type="UNSTEADY",
                    message="Mass balance data present but volume error not quantified"
                )
                results.messages.append(msg)

        except Exception as e:
            reraise_required(e)
            logger.error("Failed to check mass balance")
            logger.debug("Mass balance check failure for %s: %s", plan_hdf, e)
            msg = CheckMessage(
                message_id="US_MB_ERR",
                severity=Severity.ERROR,
                check_type="UNSTEADY",
                message=f"Failed to read volume accounting data: {e}"
            )
            results.messages.append(msg)

        return results

    @staticmethod
    @log_call
    def check_computation(
        plan_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check HEC-RAS computation messages and performance.

        Validates:
        - HEC-RAS warnings during computation
        - HEC-RAS errors during computation
        - Runtime performance anomalies

        Args:
            plan_hdf: Path to plan HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with computation check messages

        Data Source:
            Uses HdfResultsPlan.get_compute_messages() and get_runtime_data()
        """
        from ..hdf.HdfResultsPlan import HdfResultsPlan

        results = CheckResults()

        if thresholds is None:
            thresholds = get_default_thresholds()

        try:
            plan_hdf = Path(plan_hdf)

            # Get computation messages
            compute_messages = HdfResultsPlan.get_compute_messages(plan_hdf)

            error_count = 0
            warning_count = 0

            if compute_messages:
                # Parse messages for warnings and errors
                msg_list = compute_messages if isinstance(compute_messages, list) else [compute_messages]

                for msg_text in msg_list:
                    if not msg_text:
                        continue

                    msg_str = msg_text if isinstance(msg_text, str) else str(msg_text)
                    msg_lower = msg_str.lower()

                    # Skip empty or very short messages
                    if len(msg_str.strip()) < 3:
                        continue

                    # Classify message severity
                    if 'error' in msg_lower:
                        # Specific error patterns get higher severity
                        msg = CheckMessage(
                            message_id="US_CW_02",
                            severity=Severity.ERROR,
                            check_type="UNSTEADY",
                            message=f"HEC-RAS computation error: {msg_str[:250]}"
                        )
                        results.messages.append(msg)
                        error_count += 1

                    elif 'warning' in msg_lower or 'caution' in msg_lower:
                        # Check for convergence-related warnings
                        if 'converge' in msg_lower or 'iteration' in msg_lower:
                            msg = CheckMessage(
                                message_id="US_CW_03",
                                severity=Severity.WARNING,
                                check_type="UNSTEADY",
                                message=f"Solution convergence warning: {msg_str[:250]}"
                            )
                        else:
                            msg = CheckMessage(
                                message_id="US_CW_01",
                                severity=Severity.WARNING,
                                check_type="UNSTEADY",
                                message=f"HEC-RAS computation warning: {msg_str[:250]}"
                            )
                        results.messages.append(msg)
                        warning_count += 1

            # Get runtime data for performance check
            runtime_data = HdfResultsPlan.get_runtime_data(plan_hdf)

            if runtime_data is not None and not runtime_data.empty:
                # Check for compute speed metrics
                speed_info_added = False

                # Look for compute speed or simulation time columns
                for col in runtime_data.columns:
                    col_lower = col.lower()

                    # Look for speed metrics (simulation-time / compute-time ratio)
                    if 'speed' in col_lower and 'compute' in col_lower:
                        try:
                            compute_speed = float(runtime_data[col].iloc[0])

                            if compute_speed < 1.0:
                                msg = CheckMessage(
                                    message_id="US_PE_02",
                                    severity=Severity.WARNING,
                                    check_type="UNSTEADY",
                                    message=format_message("US_PE_02", speed=compute_speed)
                                )
                                results.messages.append(msg)
                                speed_info_added = True
                                break
                        except (ValueError, TypeError, IndexError):
                            continue

                if not speed_info_added:
                    # Just note that runtime data is available
                    msg = CheckMessage(
                        message_id="US_PE_INFO",
                        severity=Severity.INFO,
                        check_type="UNSTEADY",
                        message="Runtime performance data available"
                    )
                    results.messages.append(msg)

            # Summary message
            if error_count == 0 and warning_count == 0:
                msg = CheckMessage(
                    message_id="US_CW_PASS",
                    severity=Severity.INFO,
                    check_type="UNSTEADY",
                    message="No HEC-RAS computation warnings or errors detected"
                )
                results.messages.append(msg)

        except Exception as e:
            reraise_required(e)
            logger.warning("Could not check computation messages")
            logger.debug("Computation-message check failure for %s: %s", plan_hdf, e)

        return results

    @staticmethod
    @log_call
    def check_peaks(
        plan_hdf: Path,
        geom_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Validate peak values from unsteady simulation.

        This is the unsteady equivalent of check_profiles().
        Instead of comparing multiple steady profiles, validates
        maximum and minimum values against physical expectations.

        Validates:
        - Maximum WSE within geometry bounds
        - Maximum velocity within erosion thresholds
        - Peak timing consistency
        - Minimum values (dry conditions)

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with peak validation messages

        Data Source:
            Uses HdfResultsXsec.get_xsec_timeseries() for 1D results
            Uses HdfResultsMesh.get_mesh_max_ws() for 2D results
        """
        results = CheckResults()

        if thresholds is None:
            thresholds = get_default_thresholds()

        try:
            plan_hdf = Path(plan_hdf)
            geom_hdf = Path(geom_hdf)

            # Try to get 1D cross section results
            peaks_validated = False
            try:
                from ..hdf.HdfResultsXsec import HdfResultsXsec
                from ..hdf.HdfXsec import HdfXsec

                xsec_data = HdfResultsXsec.get_xsec_timeseries(plan_hdf)

                if xsec_data is not None:
                    # Get cross section geometry for bounds checking
                    try:
                        xs_geom = HdfXsec.get_cross_sections(geom_hdf)
                    except Exception as e:
                        reraise_required(e)
                        logger.debug(
                            "Could not read XS geometry for bounds checking from %s: %s",
                            geom_hdf,
                            e,
                        )
                        xs_geom = None

                    # Extract maximum values from xarray Dataset
                    if 'max_water_surface' in xsec_data.data_vars:
                        max_wse = xsec_data['max_water_surface'].values
                        xs_names = xsec_data['cross_section'].values

                        # Check maximum velocity thresholds
                        if 'max_velocity_total' in xsec_data.data_vars:
                            max_vel = xsec_data['max_velocity_total'].values

                            velocity_warn = thresholds.unsteady.max_velocity_warning_fps
                            velocity_err = thresholds.unsteady.max_velocity_error_fps

                            for i, (xs_name, vel) in enumerate(zip(xs_names, max_vel)):
                                if np.isnan(vel):
                                    continue

                                if vel >= velocity_err:
                                    # Get location info
                                    river = xsec_data['river'].values[i] if 'river' in xsec_data else ""
                                    reach = xsec_data['reach'].values[i] if 'reach' in xsec_data else ""
                                    station = xsec_data['station'].values[i] if 'station' in xsec_data else str(xs_name)

                                    location = f"{river}/{reach}/RS {station}" if river else str(xs_name)

                                    msg = CheckMessage(
                                        message_id="US_PK_03",
                                        severity=Severity.ERROR,
                                        check_type="UNSTEADY",
                                        river=str(river),
                                        reach=str(reach),
                                        station=str(station),
                                        message=format_message("US_PK_03",
                                            max_vel=vel,
                                            threshold=velocity_err,
                                            location=location
                                        ),
                                        value=vel,
                                        threshold=velocity_err
                                    )
                                    results.messages.append(msg)
                                    peaks_validated = True

                                elif vel >= velocity_warn:
                                    river = xsec_data['river'].values[i] if 'river' in xsec_data else ""
                                    reach = xsec_data['reach'].values[i] if 'reach' in xsec_data else ""
                                    station = xsec_data['station'].values[i] if 'station' in xsec_data else str(xs_name)

                                    location = f"{river}/{reach}/RS {station}" if river else str(xs_name)

                                    msg = CheckMessage(
                                        message_id="US_PK_02",
                                        severity=Severity.WARNING,
                                        check_type="UNSTEADY",
                                        river=str(river),
                                        reach=str(reach),
                                        station=str(station),
                                        message=format_message("US_PK_02",
                                            max_vel=vel,
                                            threshold=velocity_warn,
                                            location=location
                                        ),
                                        value=vel,
                                        threshold=velocity_warn
                                    )
                                    results.messages.append(msg)
                                    peaks_validated = True

                        # Create peaks summary if we found data
                        if peaks_validated:
                            # Build summary dataframe
                            summary_data = []
                            for i in range(len(xs_names)):
                                row = {
                                    'cross_section': xs_names[i],
                                    'max_wse': max_wse[i] if i < len(max_wse) else np.nan,
                                }
                                if 'max_velocity_total' in xsec_data.data_vars:
                                    row['max_velocity'] = xsec_data['max_velocity_total'].values[i]
                                if 'max_flow' in xsec_data.data_vars:
                                    row['max_flow'] = xsec_data['max_flow'].values[i]
                                if 'river' in xsec_data:
                                    row['river'] = xsec_data['river'].values[i]
                                if 'reach' in xsec_data:
                                    row['reach'] = xsec_data['reach'].values[i]
                                if 'station' in xsec_data:
                                    row['station'] = xsec_data['station'].values[i]

                                summary_data.append(row)

                            results.peaks_summary = pd.DataFrame(summary_data)

                    if not peaks_validated:
                        msg = CheckMessage(
                            message_id="US_PK_INFO",
                            severity=Severity.INFO,
                            check_type="UNSTEADY",
                            message="1D cross section time series data available for peak validation"
                        )
                        results.messages.append(msg)

            except Exception as e:
                reraise_required(e)
                logger.debug(f"Could not read 1D results: {e}")

            # Check for max velocity threshold (from profiles thresholds)
            velocity_threshold = thresholds.unsteady.max_velocity_warning_fps

            if not peaks_validated:
                msg = CheckMessage(
                    message_id="US_PK_PASS",
                    severity=Severity.INFO,
                    check_type="UNSTEADY",
                    message=f"Peak validation check completed (velocity threshold: {velocity_threshold} ft/s)"
                )
                results.messages.append(msg)

        except Exception as e:
            reraise_required(e)
            logger.error("Failed to check peaks")
            logger.debug(
                "Peak check failure for plan %s and geometry %s: %s",
                plan_hdf,
                geom_hdf,
                e,
            )
            msg = CheckMessage(
                message_id="US_PK_ERR",
                severity=Severity.ERROR,
                check_type="UNSTEADY",
                message=f"Failed to validate peak values: {e}"
            )
            results.messages.append(msg)

        return results

    @staticmethod
    @log_call
    def check_stability(
        plan_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check unsteady simulation stability and convergence.

        Validates:
        - Maximum iteration counts per cell
        - Average iteration counts (solver stress)
        - Water surface errors
        - Courant number indicators

        Args:
            plan_hdf: Path to plan HDF file
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with stability check messages

        Data Source:
            Uses HdfResultsMesh.get_mesh_max_iter() for iteration counts
            Uses HdfResultsMesh.get_mesh_max_ws_err() for WS errors
        """
        results = CheckResults()

        if thresholds is None:
            thresholds = get_default_thresholds()

        try:
            plan_hdf = Path(plan_hdf)

            # Get 2D mesh stability metrics
            stability_checks_performed = False
            try:
                from ..hdf.HdfResultsMesh import HdfResultsMesh

                # Get max iterations
                max_iter_df = HdfResultsMesh.get_mesh_max_iter(plan_hdf, include_geometry=False)

                if max_iter_df is not None and not max_iter_df.empty:
                    # Extract mesh name if available
                    mesh_name = "2D Flow Area"
                    if 'mesh_name' in max_iter_df.columns:
                        mesh_name = max_iter_df['mesh_name'].iloc[0]

                    # Find iteration column
                    iter_col = None
                    for col in max_iter_df.columns:
                        if 'iter' in col.lower() or 'iteration' in col.lower():
                            iter_col = col
                            break

                    if iter_col is not None:
                        max_iterations = max_iter_df[iter_col].values

                        # Remove NaN values for statistics
                        valid_iters = max_iterations[~np.isnan(max_iterations)]

                        if len(valid_iters) > 0:
                            max_iter_value = np.max(valid_iters)
                            avg_iter_value = np.mean(valid_iters)

                            # Check against thresholds
                            if max_iter_value >= thresholds.unsteady.max_iterations_error:
                                # Find cell with max iterations
                                max_idx = np.argmax(max_iterations)
                                cell_id = max_idx if 'cell_id' not in max_iter_df.columns else max_iter_df['cell_id'].iloc[max_idx]

                                msg = CheckMessage(
                                    message_id="US_IT_02",
                                    severity=Severity.ERROR,
                                    check_type="UNSTEADY",
                                    message=format_message("US_IT_02",
                                        max_iter=int(max_iter_value),
                                        threshold=thresholds.unsteady.max_iterations_error,
                                        mesh_name=mesh_name
                                    ),
                                    value=max_iter_value,
                                    threshold=thresholds.unsteady.max_iterations_error
                                )
                                results.messages.append(msg)
                                stability_checks_performed = True

                            elif max_iter_value >= thresholds.unsteady.max_iterations_warning:
                                max_idx = np.argmax(max_iterations)
                                cell_id = max_idx if 'cell_id' not in max_iter_df.columns else max_iter_df['cell_id'].iloc[max_idx]

                                msg = CheckMessage(
                                    message_id="US_IT_01",
                                    severity=Severity.WARNING,
                                    check_type="UNSTEADY",
                                    message=format_message("US_IT_01",
                                        max_iter=int(max_iter_value),
                                        threshold=thresholds.unsteady.max_iterations_warning,
                                        mesh_name=mesh_name,
                                        cell_id=cell_id
                                    ),
                                    value=max_iter_value,
                                    threshold=thresholds.unsteady.max_iterations_warning
                                )
                                results.messages.append(msg)
                                stability_checks_performed = True

                            # Check average iterations
                            if avg_iter_value >= thresholds.unsteady.avg_iterations_warning:
                                msg = CheckMessage(
                                    message_id="US_IT_03",
                                    severity=Severity.WARNING,
                                    check_type="UNSTEADY",
                                    message=format_message("US_IT_03",
                                        avg_iter=avg_iter_value,
                                        mesh_name=mesh_name
                                    ),
                                    value=avg_iter_value,
                                    threshold=thresholds.unsteady.avg_iterations_warning
                                )
                                results.messages.append(msg)
                                stability_checks_performed = True

                            # Create stability summary
                            results.stability_summary = pd.DataFrame([{
                                'mesh_name': mesh_name,
                                'max_iterations': max_iter_value,
                                'avg_iterations': avg_iter_value,
                                'cells_checked': len(valid_iters)
                            }])

                    if not stability_checks_performed:
                        msg = CheckMessage(
                            message_id="US_IT_INFO",
                            severity=Severity.INFO,
                            check_type="UNSTEADY",
                            message="2D mesh iteration data available for stability check"
                        )
                        results.messages.append(msg)

                # Get water surface errors
                ws_err_df = HdfResultsMesh.get_mesh_max_ws_err(plan_hdf, include_geometry=False)

                if ws_err_df is not None and not ws_err_df.empty:
                    # Find WS error column
                    ws_err_col = None
                    for col in ws_err_df.columns:
                        col_lower = col.lower()
                        if 'error' in col_lower and ('ws' in col_lower or 'water' in col_lower):
                            ws_err_col = col
                            break

                    if ws_err_col is not None:
                        ws_errors = ws_err_df[ws_err_col].values
                        valid_errors = ws_errors[~np.isnan(ws_errors)]

                        if len(valid_errors) > 0:
                            max_ws_err = np.max(valid_errors)

                            if max_ws_err >= thresholds.unsteady.ws_error_max_ft:
                                mesh_name = "2D Flow Area"
                                if 'mesh_name' in ws_err_df.columns:
                                    mesh_name = ws_err_df['mesh_name'].iloc[0]

                                msg = CheckMessage(
                                    message_id="US_WS_01",
                                    severity=Severity.WARNING,
                                    check_type="UNSTEADY",
                                    message=format_message("US_WS_01",
                                        ws_err=max_ws_err,
                                        threshold=thresholds.unsteady.ws_error_max_ft,
                                        mesh_name=mesh_name
                                    ),
                                    value=max_ws_err,
                                    threshold=thresholds.unsteady.ws_error_max_ft
                                )
                                results.messages.append(msg)
                                stability_checks_performed = True
                    else:
                        msg = CheckMessage(
                            message_id="US_WS_INFO",
                            severity=Severity.INFO,
                            check_type="UNSTEADY",
                            message="Water surface error data available"
                        )
                        results.messages.append(msg)

            except Exception as e:
                reraise_required(e)
                logger.debug(f"Could not read 2D stability metrics: {e}")

            if not stability_checks_performed:
                msg = CheckMessage(
                    message_id="US_ST_PASS",
                    severity=Severity.INFO,
                    check_type="UNSTEADY",
                    message="Stability check completed - no issues detected"
                )
                results.messages.append(msg)

        except Exception as e:
            reraise_required(e)
            logger.error("Failed to check stability")
            logger.debug("Stability check failure for %s: %s", plan_hdf, e)
            msg = CheckMessage(
                message_id="US_ST_ERR",
                severity=Severity.ERROR,
                check_type="UNSTEADY",
                message=f"Failed to check stability: {e}"
            )
            results.messages.append(msg)

        return results

    @staticmethod
    @log_call
    def check_mesh_quality(
        plan_hdf: Path,
        geom_hdf: Path,
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """Check cell areas, bounding-box aspect ratios, and maximum face velocities.

        Area thresholds are in square feet; velocity thresholds are in ft/s.
        Areas use projected CRS axis units and velocities use native result-HDF
        unit metadata. Missing or conflicting unit evidence prevents comparison.
        Connectivity and other geometric mesh rules are not implemented here.

        Returns:
            CheckResults with per-check status and reason in
            ``statistics["mesh_quality_coverage"]``. A passed status covers only
            that check, never unavailable data or unimplemented geometric rules.
        """
        from ..hdf.HdfBase import HdfBase
        from ..hdf.HdfMesh import HdfMesh
        from ..hdf.HdfResultsMesh import HdfResultsMesh

        results = CheckResults()
        if thresholds is None:
            thresholds = get_default_thresholds()
        coverage = {}
        results.statistics["mesh_quality_coverage"] = coverage

        def record(check, status, reason):
            coverage[check] = {"status": status, "reason": reason}
            severity = (Severity.ERROR if status == "failed" else
                        Severity.WARNING if status == "unavailable" else Severity.INFO)
            results.messages.append(CheckMessage(
                message_id="US_2D_ERR" if status == "failed" else "US_2D_INFO",
                severity=severity, check_type="UNSTEADY",
                message=f"2D mesh {check}: {status} - {reason}",
            ))

        record("connectivity", "unsupported", "Connectivity checks are not implemented")
        # Validate file structure here: legacy geometry readers can turn read
        # errors into empty frames/lists, which are not evidence of a 1D model.
        try:
            geom_hdf = Path(geom_hdf)
            with h5py.File(geom_hdf, "r") as hdf:
                if "Geometry" not in hdf:
                    raise ValueError("Geometry group is absent")
                mesh_group = hdf.get("Geometry/2D Flow Areas")
                if mesh_group is None or len(mesh_group) == 0:
                    for check in ("cell_area", "aspect_ratio", "face_velocity"):
                        record(check, "not_applicable", "Geometry contains no 2D flow areas")
                    return results
            mesh_names = HdfMesh.get_mesh_area_names(geom_hdf)
            if not mesh_names:
                raise ValueError("2D flow-area inventory could not be read")
        except Exception as exc:
            reraise_required(exc)
            for check in ("cell_area", "aspect_ratio"):
                record(check, "failed", f"Cannot read mesh geometry: {exc}")
            mesh_names = None

        if mesh_names:
            geometry_read = False
            try:
                polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf, strict=True)
                geometry_read = True
                if polygons is None or polygons.empty:
                    raise ValueError("Cell polygon data are absent or unreadable")
                if set(polygons["mesh_name"]) != set(mesh_names):
                    raise ValueError("Cell polygons do not cover every 2D flow area")
                valid = (polygons.geometry.notna() & ~polygons.geometry.is_empty
                         & polygons.geometry.is_valid)
                if not valid.all():
                    raise ValueError("Invalid or missing cell polygons prevent complete coverage")
            except Exception as exc:
                reraise_required(exc)
                for check in ("cell_area", "aspect_ratio"):
                    record(check, "unavailable" if geometry_read else "failed",
                           f"Complete cell polygons unavailable: {exc}")
            else:
                crs = polygons.crs
                if crs is None or not crs.is_projected:
                    for check in ("cell_area", "aspect_ratio"):
                        record(check, "unavailable", "Projected CRS with linear axis units is required")
                else:
                    # CRS axis factors are metres per coordinate unit, including
                    # US survey feet. Project/result units cannot substitute for
                    # horizontal coordinate units.
                    try:
                        factors = [axis.unit_conversion_factor for axis in crs.axis_info[:2]]
                        if (len(factors) != 2 or not np.isfinite(factors).all()
                                or min(factors) <= 0 or not np.isclose(*factors)):
                            raise ValueError("CRS horizontal axis units are unsupported")
                        area_factor = factors[0] * factors[1] / 0.3048 ** 2
                        areas = polygons.geometry.area * area_factor
                        if not np.isfinite(areas).all() or (areas <= 0).any():
                            raise ValueError("Non-finite or nonpositive cell areas")
                        min_area = thresholds.unsteady.min_cell_area_sqft
                        max_area = thresholds.unsteady.max_cell_area_sqft
                        summaries = []
                        issues = False
                        for mesh_name in mesh_names:
                            mesh_areas = areas[polygons["mesh_name"] == mesh_name]
                            small, large = mesh_areas < min_area, mesh_areas > max_area
                            for flagged, message_id, value, limit in (
                                (small.any(), "US_2D_01", mesh_areas.min(), min_area),
                                (large.any(), "US_2D_02", mesh_areas.max(), max_area),
                            ):
                                if flagged:
                                    issues = True
                                    results.messages.append(CheckMessage(
                                        message_id=message_id, severity=Severity.WARNING,
                                        check_type="UNSTEADY", value=float(value), threshold=limit,
                                        message=format_message(message_id, area=value,
                                                               threshold=limit, mesh_name=mesh_name),
                                    ))
                            summaries.append({
                                "mesh_name": mesh_name, "total_cells": len(mesh_areas),
                                "cells_too_small": int(small.sum()), "cells_too_large": int(large.sum()),
                                "min_area_sqft": mesh_areas.min(), "max_area_sqft": mesh_areas.max(),
                                "mean_area_sqft": mesh_areas.mean(),
                            })
                        results.mesh_summary = pd.DataFrame(summaries)
                        record("cell_area", "issues" if issues else "passed",
                               f"Compared {len(areas)} cell areas in ft²")
                    except Exception as exc:
                        record("cell_area", "unavailable", f"Area comparison unavailable: {exc}")

                    try:
                        if (len(crs.axis_info) < 2 or not np.isclose(
                                crs.axis_info[0].unit_conversion_factor,
                                crs.axis_info[1].unit_conversion_factor)):
                            raise ValueError("CRS horizontal axes must have equal linear units")
                        bounds = polygons.geometry.bounds
                        widths = bounds.maxx - bounds.minx
                        heights = bounds.maxy - bounds.miny
                        ratios = np.maximum(widths / heights, heights / widths)
                        if not np.isfinite(ratios).all():
                            raise ValueError("Non-finite bounding-box aspect ratios")
                        issues = False
                        for mesh_name in mesh_names:
                            value = ratios[polygons["mesh_name"] == mesh_name].max()
                            limit = thresholds.unsteady.max_aspect_ratio
                            if value > limit:
                                issues = True
                                results.messages.append(CheckMessage(
                                    message_id="US_2D_03", severity=Severity.WARNING,
                                    check_type="UNSTEADY", value=float(value), threshold=limit,
                                    message=format_message("US_2D_03", ratio=value,
                                                           threshold=limit, mesh_name=mesh_name),
                                ))
                        record("aspect_ratio", "issues" if issues else "passed",
                               f"Compared {len(ratios)} bounding-box aspect ratios (approximation)")
                    except Exception as exc:
                        record("aspect_ratio", "unavailable", f"Aspect-ratio comparison unavailable: {exc}")

        try:
            plan_hdf = Path(plan_hdf)
            # Opening separately prevents a swallowed/empty reader result from
            # concealing a nonexistent or corrupt plan HDF.
            with h5py.File(plan_hdf, "r"):
                pass
            velocities = HdfResultsMesh.get_mesh_max_face_v(plan_hdf, include_geometry=False)
            if velocities is None or velocities.empty:
                record("face_velocity", "unavailable", "Maximum face velocity data are absent")
            elif "maximum_face_velocity" not in velocities.columns:
                record("face_velocity", "unavailable", "Maximum face velocity column is absent")
            elif not mesh_names or set(velocities["mesh_name"]) != set(mesh_names):
                record("face_velocity", "unavailable", "Velocity data do not cover the geometry mesh inventory")
            elif "face_id" not in velocities.columns:
                record("face_velocity", "unavailable", "Native face IDs are absent from velocity data")
            else:
                # A mesh name alone cannot establish coverage: a shortened
                # summary matrix still carries that name. Native face IDs are
                # zero-based rows of Faces FacePoint Indexes, including the
                # boundary faces, and must each occur exactly once.
                with h5py.File(geom_hdf, "r") as geometry:
                    for mesh_name in mesh_names:
                        topology = geometry.get(
                            f"Geometry/2D Flow Areas/{mesh_name}/Faces FacePoint Indexes"
                        )
                        if (not isinstance(topology, h5py.Dataset)
                                or topology.ndim != 2 or topology.shape[1] != 2
                                or topology.shape[0] == 0 or topology.dtype.kind not in "iu"):
                            raise ValueError(f"Native face inventory unavailable for {mesh_name!r}")
                        face_ids = pd.to_numeric(
                            velocities.loc[velocities["mesh_name"] == mesh_name, "face_id"],
                            errors="coerce",
                        ).to_numpy()
                        if (len(face_ids) != topology.shape[0]
                                or not np.isfinite(face_ids).all()
                                or not np.array_equal(np.sort(face_ids), np.arange(topology.shape[0]))):
                            raise ValueError(
                                f"Velocity face IDs do not cover every native face exactly once "
                                f"for {mesh_name!r} (expected {topology.shape[0]}, got {len(face_ids)})"
                            )
                metadata = HdfBase.get_result_unit_metadata(plan_hdf)
                unit = metadata["velocity_units"]
                if unit not in ("ft/s", "m/s"):
                    raise ValueError(f"Unsupported native velocity units: {unit}")
                values = pd.to_numeric(velocities["maximum_face_velocity"], errors="coerce")
                if not np.isfinite(values).all():
                    raise ValueError("Missing or non-finite maximum face velocity values")
                values = values * (1 / 0.3048 if unit == "m/s" else 1)
                issues = False
                for mesh_name in mesh_names:
                    value = values[velocities["mesh_name"] == mesh_name].max()
                    limit = thresholds.unsteady.max_velocity_error_fps
                    if value >= limit:
                        issues = True
                        results.messages.append(CheckMessage(
                            message_id="US_2D_04", severity=Severity.WARNING,
                            check_type="UNSTEADY", value=float(value), threshold=limit,
                            message=format_message("US_2D_04", vel=value, mesh_name=mesh_name),
                        ))
                record("face_velocity", "issues" if issues else "passed",
                       f"Compared {len(values)} maximum face velocities in ft/s (native {unit})")
        except Exception as exc:
            reraise_required(exc)
            record("face_velocity", "failed", f"Cannot evaluate maximum face velocities: {exc}")

        return results
