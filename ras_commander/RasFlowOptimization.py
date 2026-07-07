"""
RasFlowOptimization - Native HEC-RAS flow hydrograph optimization helpers.

This module configures HEC-RAS Automated Flow Optimization using the native
``Flow Ratio ...`` plan-file parameters and extracts trial summaries from HDF
results or computation messages after execution.

All methods are static and are designed to be used without instantiation.
"""

from __future__ import annotations

import re
from numbers import Number
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import h5py
import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPlan import RasPlan
from .RasPrj import ras
from .RasUtils import RasUtils

logger = get_logger(__name__)


class RasFlowOptimization:
    """
    Static helpers for HEC-RAS native Automated Flow Optimization.

    HEC-RAS stores flow hydrograph optimization setup in plan files using
    ``Flow Ratio ...`` keys and reports trial progress in compute messages.
    This API keeps execution in the standard ras-commander path: configure a
    copied plan, run it with :class:`RasCmdr`, then extract the trial summary.
    """

    PLAN_KEYS = {
        "target_value": "Flow Ratio Target",
        "tolerance": "Flow Ratio Tolerance",
        "initial_ratio": "Flow Ratio Initial Ratio",
        "min_ratio": "Flow Ratio Min Ratio",
        "max_ratio": "Flow Ratio Max Ratio",
        "max_iterations": "Flow Ratio Max Iterations",
        "reference": "Flow Ratio Reference",
        "user_selected_hydrographs": "Flow Ratio User Selected Hydrographs",
        "hydrograph": "Flow Ratio Optimization Hydrograph",
        # These keys are not present in every HEC-RAS plan. The writer preserves
        # and updates them when callers need the non-default restart behavior.
        "restart_approach": "Flow Ratio Restart Approach",
        "transition_period_hours": "Flow Ratio Transition Period",
    }

    RESTART_APPROACH_VALUES = {
        "reuse_initial_conditions": "Re-use Initial Conditions",
        "reuse": "Re-use Initial Conditions",
        "default": "Re-use Initial Conditions",
        "recompute_each_trial": "Recompute Each Trial",
        "recompute": "Recompute Each Trial",
    }

    TRIAL_RESULT_COLUMNS = [
        "trial",
        "ratio",
        "difference",
        "target",
        "computed",
        "mode",
        "units",
        "reference_location",
        "converged",
        "failed",
        "source",
        "source_path",
        "source_dataset",
        "message",
    ]

    @staticmethod
    @log_call
    def get_settings(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Read native flow optimization settings from a HEC-RAS plan file.

        Args:
            plan_number_or_path: Plan number (``"01"``) or explicit ``.p##``
                path.
            ras_object: Optional RAS project object. If None, uses global
                ``ras``.

        Returns:
            Dict with normalized keys including ``enabled``, ``mode``,
            ``reference_location``, ratio limits, and selected hydrographs.
        """
        ras_obj = ras_object or ras
        plan_path = RasFlowOptimization._resolve_plan_file_path(
            plan_number_or_path,
            ras_obj,
        )
        lines = RasFlowOptimization._read_text_lines(plan_path)
        raw_values, hydrographs = RasFlowOptimization._read_flow_ratio_values(lines)

        reference = raw_values.get(RasFlowOptimization.PLAN_KEYS["reference"])
        reference_type, reference_location = RasFlowOptimization._split_reference(
            reference
        )
        mode = RasFlowOptimization._infer_mode(reference_type, raw_values)

        settings = {
            "enabled": any(key.startswith("Flow Ratio ") for key in raw_values),
            "mode": mode,
            "reference": reference,
            "reference_type": reference_type,
            "reference_location": reference_location,
            "target_value": RasFlowOptimization._parse_float(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["target_value"])
            ),
            "tolerance": RasFlowOptimization._parse_float(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["tolerance"])
            ),
            "initial_ratio": RasFlowOptimization._parse_float(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["initial_ratio"])
            ),
            "min_ratio": RasFlowOptimization._parse_float(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["min_ratio"])
            ),
            "max_ratio": RasFlowOptimization._parse_float(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["max_ratio"])
            ),
            "max_iterations": RasFlowOptimization._parse_int(
                raw_values.get(RasFlowOptimization.PLAN_KEYS["max_iterations"])
            ),
            "user_selected_hydrographs": RasFlowOptimization._parse_ras_bool(
                raw_values.get(
                    RasFlowOptimization.PLAN_KEYS["user_selected_hydrographs"]
                )
            ),
            "hydrographs": hydrographs,
            "restart_approach": raw_values.get(
                RasFlowOptimization.PLAN_KEYS["restart_approach"]
            ),
            "transition_period_hours": RasFlowOptimization._parse_float(
                raw_values.get(
                    RasFlowOptimization.PLAN_KEYS["transition_period_hours"]
                )
            ),
            "plan_path": str(plan_path),
            "raw_values": raw_values,
        }
        return settings

    @staticmethod
    @log_call
    def set_settings(
        plan_number_or_path: Union[str, Number, Path],
        mode: str,
        reference_location: str,
        target_value: Union[int, float],
        tolerance: Union[int, float] = 0.1,
        initial_ratio: Union[int, float] = 1.0,
        min_ratio: Union[int, float] = 0.5,
        max_ratio: Union[int, float] = 4.0,
        max_iterations: int = 10,
        hydrographs: Optional[Union[str, Iterable[str]]] = None,
        user_selected_hydrographs: Optional[bool] = None,
        restart_approach: Optional[str] = None,
        transition_period_hours: Optional[Union[int, float]] = None,
        update_observed_timeseries: bool = True,
        target_units: Optional[str] = None,
        ras_object=None,
    ) -> bool:
        """
        Write native flow optimization settings into a plan file.

        Args:
            plan_number_or_path: Plan number or explicit plan path.
            mode: ``"stage"``, ``"flow"``, or ``"none"``.
            reference_location: Existing HEC-RAS reference point/line name. A
                full value such as ``"Ref Point: LowPoint"`` is accepted; if no
                prefix is supplied, the prefix is inferred from ``mode``.
            target_value: Target stage or flow value.
            tolerance: Allowed target tolerance.
            initial_ratio: Flow ratio used by trial 1.
            min_ratio: Minimum trial flow ratio.
            max_ratio: Maximum trial flow ratio.
            max_iterations: Maximum number of trials.
            hydrographs: Exact optimization hydrograph labels, a single label,
                or ``None`` to auto-discover flow hydrographs where possible.
                Plain names are written as ``"BCLine: <name>"``.
            user_selected_hydrographs: Override the native user-selected flag.
                Defaults to ``True`` when hydrograph labels are written.
            restart_approach: Optional restart approach. Accepted shorthands:
                ``"reuse_initial_conditions"`` or ``"recompute_each_trial"``.
            transition_period_hours: Optional restart transition period.
            update_observed_timeseries: Also write the constant observed stage
                or flow target in the referenced unsteady flow file.
            target_units: Units for the observed target series. Defaults to
                ``"ft"`` for stage and ``"cfs"`` for flow.
            ras_object: Optional RAS project object.

        Returns:
            True when the plan file was written successfully.
        """
        mode_key = RasFlowOptimization._normalize_mode(mode)
        if mode_key == "none":
            return RasFlowOptimization.disable_plan(
                plan_number_or_path,
                ras_object=ras_object,
            )

        RasFlowOptimization._validate_ratio_bounds(
            min_ratio=min_ratio,
            max_ratio=max_ratio,
            initial_ratio=initial_ratio,
            max_iterations=max_iterations,
        )

        ras_obj = ras_object or ras
        plan_path = RasFlowOptimization._resolve_plan_file_path(
            plan_number_or_path,
            ras_obj,
        )
        reference = RasFlowOptimization._format_reference(
            mode_key,
            reference_location,
        )
        hydrograph_labels = RasFlowOptimization._resolve_hydrograph_labels(
            hydrographs,
            plan_path,
            ras_obj,
        )
        if user_selected_hydrographs is None:
            user_selected_hydrographs = bool(hydrograph_labels)

        restart_value = None
        if restart_approach is not None:
            restart_value = RasFlowOptimization._normalize_restart_approach(
                restart_approach
            )

        requested = {
            RasFlowOptimization.PLAN_KEYS["target_value"]: target_value,
            RasFlowOptimization.PLAN_KEYS["tolerance"]: tolerance,
            RasFlowOptimization.PLAN_KEYS["initial_ratio"]: initial_ratio,
            RasFlowOptimization.PLAN_KEYS["min_ratio"]: min_ratio,
            RasFlowOptimization.PLAN_KEYS["max_ratio"]: max_ratio,
            RasFlowOptimization.PLAN_KEYS["max_iterations"]: max_iterations,
            RasFlowOptimization.PLAN_KEYS["reference"]: reference,
            RasFlowOptimization.PLAN_KEYS[
                "user_selected_hydrographs"
            ]: user_selected_hydrographs,
        }
        if restart_value is not None:
            requested[RasFlowOptimization.PLAN_KEYS["restart_approach"]] = (
                restart_value
            )
        if transition_period_hours is not None:
            requested[
                RasFlowOptimization.PLAN_KEYS["transition_period_hours"]
            ] = transition_period_hours

        lines = RasFlowOptimization._read_text_lines(plan_path)
        updated_lines = RasFlowOptimization._upsert_flow_ratio_lines(
            lines,
            requested,
            hydrograph_labels,
        )
        RasFlowOptimization._write_text_lines(plan_path, updated_lines)

        if update_observed_timeseries:
            unsteady_path = RasFlowOptimization._resolve_unsteady_file_from_plan(
                plan_path,
                ras_obj,
            )
            if unsteady_path and unsteady_path.exists():
                units = target_units or ("ft" if mode_key == "stage" else "cfs")
                RasFlowOptimization._set_observed_target_timeseries(
                    unsteady_path=unsteady_path,
                    mode=mode_key,
                    reference=reference,
                    target_value=target_value,
                    target_units=units,
                    plan_lines=updated_lines,
                )
            else:
                detail = "not found" if unsteady_path else "could not be resolved"
                logger.warning(
                    "Skipped observed target time-series update for %s (%s): "
                    "unsteady flow file %s",
                    plan_path.name,
                    reference,
                    detail,
                )
                logger.debug("Observed target unsteady path candidate: %s", unsteady_path)

        RasFlowOptimization._refresh_plan_dataframe(ras_obj)
        logger.info("Updated flow optimization settings in %s", plan_path.name)
        return True

    @staticmethod
    @log_call
    def enable_plan(
        plan_number_or_path: Union[str, Number, Path],
        mode: str,
        reference_location: str,
        target_value: Union[int, float],
        **kwargs,
    ) -> bool:
        """
        Enable native Automated Flow Optimization for an existing plan.

        This is an alias for :meth:`set_settings` with intent-focused naming.
        """
        return RasFlowOptimization.set_settings(
            plan_number_or_path=plan_number_or_path,
            mode=mode,
            reference_location=reference_location,
            target_value=target_value,
            **kwargs,
        )

    @staticmethod
    @log_call
    def disable_plan(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> bool:
        """
        Remove native ``Flow Ratio ...`` settings from a plan file.

        Args:
            plan_number_or_path: Plan number or explicit plan path.
            ras_object: Optional RAS project object.

        Returns:
            True when the plan file was updated.
        """
        ras_obj = ras_object or ras
        plan_path = RasFlowOptimization._resolve_plan_file_path(
            plan_number_or_path,
            ras_obj,
        )
        lines = RasFlowOptimization._read_text_lines(plan_path)
        updated_lines = [
            line
            for line in lines
            if not line.lstrip().startswith("Flow Ratio ")
        ]
        RasFlowOptimization._write_text_lines(plan_path, updated_lines)
        RasFlowOptimization._refresh_plan_dataframe(ras_obj)
        logger.info("Disabled flow optimization in %s", plan_path.name)
        return True

    @staticmethod
    @log_call
    def copy_plan_with_optimization(
        template_plan: Union[str, Number],
        mode: str,
        reference_location: str,
        target_value: Union[int, float],
        new_plan_shortid: Optional[str] = None,
        new_title: Optional[str] = None,
        ras_object=None,
        **settings_kwargs,
    ) -> str:
        """
        Clone a plan and enable native flow optimization on the copy.

        Args:
            template_plan: Existing plan number to copy.
            mode: ``"stage"`` or ``"flow"``.
            reference_location: Existing reference point/line.
            target_value: Target stage or flow value.
            new_plan_shortid: Optional new Short Identifier.
            new_title: Optional new Plan Title.
            ras_object: Optional RAS project object.
            **settings_kwargs: Additional :meth:`set_settings` options.

        Returns:
            New plan number.
        """
        ras_obj = ras_object or ras
        new_plan = RasPlan.clone_plan(
            template_plan=template_plan,
            new_plan_shortid=new_plan_shortid,
            new_title=new_title,
            ras_object=ras_obj,
        )
        RasFlowOptimization.set_settings(
            new_plan,
            mode=mode,
            reference_location=reference_location,
            target_value=target_value,
            ras_object=ras_obj,
            **settings_kwargs,
        )
        return new_plan

    @staticmethod
    @log_call
    def list_flow_hydrographs(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List flow hydrograph boundary labels available to a plan.

        The returned ``optimization_hydrograph`` values are suitable for the
        ``Flow Ratio Optimization Hydrograph=`` plan-file lines when HEC-RAS
        uses 2D boundary condition line labels.
        """
        ras_obj = ras_object or ras
        plan_path = RasFlowOptimization._resolve_plan_file_path(
            plan_number_or_path,
            ras_obj,
        )
        unsteady_path = RasFlowOptimization._resolve_unsteady_file_from_plan(
            plan_path,
            ras_obj,
        )
        if not unsteady_path or not unsteady_path.exists():
            raise FileNotFoundError(
                RasFlowOptimization._format_missing_unsteady_error(plan_path, unsteady_path)
            )

        lines = RasFlowOptimization._read_text_lines(unsteady_path)
        rows = []
        index = 0
        while index < len(lines):
            if lines[index].startswith("Boundary Location="):
                block_end = index + 1
                while (
                    block_end < len(lines)
                    and not lines[block_end].startswith("Boundary Location=")
                ):
                    block_end += 1
                row = RasFlowOptimization._parse_unsteady_boundary_block(
                    lines[index:block_end],
                    line_number=index + 1,
                )
                if row.get("bc_type") in {
                    "Flow Hydrograph",
                    "Lateral Inflow Hydrograph",
                    "Uniform Lateral Inflow Hydrograph",
                }:
                    rows.append(row)
                index = block_end
            else:
                index += 1

        df = pd.DataFrame(rows)
        logger.debug("Found %s flow hydrograph boundary rows", len(df))
        return df

    @staticmethod
    @log_call
    def get_trial_results(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Extract native flow optimization trial results after compute.

        The extractor first looks for flow optimization result datasets in the
        plan HDF. If HEC-RAS stores the trials only in compute messages, it
        falls back to parsing ``.computeMsgs.txt`` / ``.comp_msgs.txt`` or the
        HDF compute-message text dataset.

        Returns:
            DataFrame with one row per parsed trial. Empty when no native flow
            optimization output is available.
        """
        ras_obj = ras_object or ras
        plan_path, hdf_path = RasFlowOptimization._resolve_plan_and_hdf_paths(
            plan_number_or_path,
            ras_obj,
        )

        hdf_df = pd.DataFrame()
        if hdf_path is not None and hdf_path.exists():
            hdf_df = RasFlowOptimization._extract_trial_results_from_hdf(hdf_path)
            if not hdf_df.empty:
                return RasFlowOptimization._finalize_trial_results(hdf_df)

        messages = RasFlowOptimization._read_compute_messages(plan_path, hdf_path)
        if not messages:
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)

        message_df = RasFlowOptimization.parse_compute_messages(messages)
        if not message_df.empty:
            source_path = hdf_path if hdf_path and hdf_path.exists() else plan_path
            message_df["source_path"] = str(source_path) if source_path else None
        return RasFlowOptimization._finalize_trial_results(message_df)

    @staticmethod
    @log_call
    def parse_compute_messages(messages: str) -> pd.DataFrame:
        """
        Parse HEC-RAS flow optimization trial lines from compute messages.

        Args:
            messages: Raw compute message text.

        Returns:
            DataFrame with one row per ``Optimization trial #`` message.
        """
        if not messages:
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)

        header_re = re.compile(
            r"Hydro\s+Flow\s+Optimization\s+"
            r"(?P<mode>Stage|Flow)\s*,\s*Target\s+"
            r"(?P<target>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)"
            r"(?:\s+(?P<units>[A-Za-z0-9_/^.-]+))?\s+at\s+"
            r"(?P<reference>.+)",
            re.IGNORECASE,
        )
        trial_re = re.compile(
            r"Optimization\s+trial\s*#\s*(?P<trial>\d+)\s+"
            r"Ratio\s+(?P<ratio>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+"
            r"Difference\s+(?P<difference>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+"
            r"Target\s+(?P<target>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+"
            r"Computed\s+(?P<computed>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)",
            re.IGNORECASE,
        )
        converged_re = re.compile(
            r"Hydro\s+Flow\s+Optimization\s+Converged\s+Trial\s*#\s*"
            r"(?P<trial>\d+)\s+Ratio\s+"
            r"(?P<ratio>[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)",
            re.IGNORECASE,
        )
        failed_re = re.compile(
            r"Hydro\s+Flow\s+Optimization.*"
            r"(failed|not\s+able\s+to\s+converge|did\s+not\s+converge)",
            re.IGNORECASE,
        )

        mode = None
        units = None
        reference = None
        rows: List[Dict[str, Any]] = []
        converged_trial = None
        failed = False

        for raw_line in messages.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            header_match = header_re.search(line)
            if header_match:
                mode = header_match.group("mode").lower()
                units = header_match.group("units")
                reference = header_match.group("reference").strip()
                continue

            trial_match = trial_re.search(line)
            if trial_match:
                rows.append(
                    {
                        "trial": int(trial_match.group("trial")),
                        "ratio": float(trial_match.group("ratio")),
                        "difference": float(trial_match.group("difference")),
                        "target": float(trial_match.group("target")),
                        "computed": float(trial_match.group("computed")),
                        "mode": mode,
                        "units": units,
                        "reference_location": reference,
                        "converged": False,
                        "failed": False,
                        "source": "compute_messages",
                        "source_path": None,
                        "source_dataset": None,
                        "message": line,
                    }
                )
                continue

            converged_match = converged_re.search(line)
            if converged_match:
                converged_trial = int(converged_match.group("trial"))
                continue

            if failed_re.search(line):
                failed = True

        if not rows:
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)

        df = pd.DataFrame(rows)
        if converged_trial is not None:
            df.loc[df["trial"] == converged_trial, "converged"] = True
        if failed:
            df["failed"] = True
        return df

    @staticmethod
    @log_call
    def compute_plan_and_get_trials(
        plan_number: Union[str, Number, Path],
        ras_object=None,
        **compute_kwargs,
    ) -> Dict[str, Any]:
        """
        Execute a plan through :class:`RasCmdr` and return native trials.

        This method is a convenience wrapper only; it does not invoke HEC-RAS
        directly.
        """
        from .RasCmdr import RasCmdr

        compute_result = RasCmdr.compute_plan(
            plan_number,
            ras_object=ras_object,
            **compute_kwargs,
        )
        trial_plan = RasFlowOptimization._resolve_trial_plan_after_compute(
            plan_number,
            ras_object=ras_object,
            dest_folder=compute_kwargs.get("dest_folder"),
        )
        trial_results = RasFlowOptimization.get_trial_results(
            trial_plan,
            ras_object=ras_object,
        )
        return {
            "compute_result": compute_result,
            "trial_results": trial_results,
        }

    @staticmethod
    def _resolve_plan_file_path(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> Path:
        if isinstance(plan_number_or_path, (str, Path)):
            path = Path(plan_number_or_path)
            if path.is_file():
                return path

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        plan_path = RasPlan.get_plan_path(plan_number_or_path, ras_obj)
        if plan_path is None or not Path(plan_path).exists():
            raise FileNotFoundError(
                RasFlowOptimization._format_missing_plan_error(
                    plan_number_or_path,
                    plan_path,
                    ras_obj,
                )
            )
        return Path(plan_path)

    @staticmethod
    def _resolve_plan_and_hdf_paths(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        if isinstance(plan_number_or_path, (str, Path)):
            path = Path(plan_number_or_path)
            if path.is_file():
                if path.suffix.lower() == ".hdf":
                    plan_path = Path(str(path)[:-4])
                    return (plan_path if plan_path.exists() else None, path)
                return path, Path(str(path) + ".hdf")

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        plan_path = RasPlan.get_plan_path(plan_number_or_path, ras_obj)
        hdf_path = RasPlan.get_results_path(plan_number_or_path, ras_obj)
        if hdf_path is None and plan_path is not None:
            hdf_path = Path(str(plan_path) + ".hdf")
        return plan_path, hdf_path

    @staticmethod
    def _resolve_trial_plan_after_compute(
        plan_number: Union[str, Number, Path],
        ras_object=None,
        dest_folder: Optional[Union[str, Path]] = None,
    ) -> Union[str, Number, Path]:
        if dest_folder is None:
            return plan_number

        ras_obj = ras_object or ras
        if isinstance(dest_folder, str):
            project_folder = getattr(ras_obj, "project_folder", None)
            if project_folder is None:
                return plan_number
            dest_path = Path(project_folder).parent / dest_folder
        else:
            dest_path = Path(dest_folder)

        if isinstance(plan_number, (str, Path)):
            plan_path = Path(plan_number)
            if plan_path.is_file() or plan_path.suffix.lower().startswith(".p"):
                return dest_path / plan_path.name

        if isinstance(plan_number, Number) or str(plan_number).isdigit():
            project_name = getattr(ras_obj, "project_name", None)
            if project_name:
                plan_num = RasUtils.normalize_ras_number(plan_number)
                return dest_path / f"{project_name}.p{plan_num}"

        return plan_number

    @staticmethod
    def _resolve_unsteady_file_from_plan(
        plan_path: Path,
        ras_object=None,
    ) -> Optional[Path]:
        flow_file = RasFlowOptimization._flow_file_reference_from_plan(plan_path)
        if not flow_file or not flow_file.lower().startswith("u"):
            return None

        unsteady_number = RasUtils.normalize_ras_number(flow_file[1:])
        ras_obj = ras_object or ras
        try:
            if getattr(ras_obj, "project_folder", None):
                unsteady_path = RasPlan.get_unsteady_path(
                    unsteady_number,
                    ras_obj,
                )
                if unsteady_path is not None:
                    return Path(unsteady_path)
        except Exception:
            logger.debug("Could not resolve unsteady path from ras_object")

        match = re.match(r"(?P<base>.+)\.p\d{2,3}$", plan_path.name, re.IGNORECASE)
        if not match:
            return None
        return plan_path.parent / f"{match.group('base')}.u{unsteady_number}"

    @staticmethod
    def _flow_file_reference_from_plan(plan_path: Path) -> Optional[str]:
        for line in RasFlowOptimization._read_text_lines(plan_path):
            if line.startswith("Flow File="):
                return line.split("=", 1)[1].strip()
        return None

    @staticmethod
    def _format_missing_unsteady_error(plan_path: Path, unsteady_path: Optional[Path]) -> str:
        flow_file = RasFlowOptimization._flow_file_reference_from_plan(plan_path)
        if flow_file is None:
            return (
                f"Unsteady flow file could not be resolved from plan: {plan_path}. "
                "No Flow File=u## record was found."
            )
        if not flow_file.lower().startswith("u"):
            return (
                f"Unsteady flow file could not be resolved from plan: {plan_path}. "
                f"Plan references non-unsteady Flow File={flow_file}."
            )
        if unsteady_path is None:
            return (
                f"Unsteady flow file could not be resolved from plan: {plan_path}. "
                f"Plan references Flow File={flow_file}, but no candidate path could be constructed."
            )
        return (
            f"Unsteady flow file could not be resolved from plan: {plan_path}. "
            f"Plan references Flow File={flow_file}, but expected file was not found: {unsteady_path}"
        )

    @staticmethod
    def _format_missing_plan_error(
        plan_number_or_path: Any,
        resolved_path: Optional[Path],
        ras_obj,
    ) -> str:
        message = [f"Plan file not found: {plan_number_or_path}"]
        context = RasFlowOptimization._ras_project_context(ras_obj)
        if context:
            message.append(context)
        candidate = resolved_path or RasFlowOptimization._plan_candidate_path(
            plan_number_or_path,
            ras_obj,
        )
        if candidate is not None:
            message.append(f"Expected path: {candidate}")
        available = RasFlowOptimization._available_plan_numbers(ras_obj)
        if available:
            message.append(f"Available plans: {available}")
        return ". ".join(message)

    @staticmethod
    def _ras_project_context(ras_obj) -> str:
        project_name = getattr(ras_obj, "project_name", None)
        project_folder = getattr(ras_obj, "project_folder", None)
        if project_name and project_folder:
            return f"Project: {project_name} in {project_folder}"
        if project_name:
            return f"Project: {project_name}"
        if project_folder:
            return f"Project folder: {project_folder}"
        return ""

    @staticmethod
    def _plan_candidate_path(plan_number_or_path: Any, ras_obj) -> Optional[Path]:
        project_name = getattr(ras_obj, "project_name", None)
        project_folder = getattr(ras_obj, "project_folder", None)
        if not project_name or not project_folder:
            return None
        try:
            plan_number = RasUtils.normalize_ras_number(plan_number_or_path)
        except Exception:
            return None
        return Path(project_folder) / f"{project_name}.p{plan_number}"

    @staticmethod
    def _available_plan_numbers(ras_obj) -> str:
        df = getattr(ras_obj, "plan_df", None)
        if (df is None or getattr(df, "empty", True)) and hasattr(ras_obj, "get_plan_entries"):
            try:
                df = ras_obj.get_plan_entries()
            except Exception:
                logger.debug("Could not refresh plan_df while formatting missing plan error", exc_info=True)
                df = None
        if df is None or getattr(df, "empty", True) or "plan_number" not in df.columns:
            return ""
        values = [str(value) for value in df["plan_number"].dropna().tolist()]
        return ", ".join(values)

    @staticmethod
    def _read_text_lines(path: Path) -> List[str]:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )

    @staticmethod
    def _write_text_lines(path: Path, lines: List[str]) -> None:
        path.write_text("".join(lines), encoding="utf-8")

    @staticmethod
    def _read_flow_ratio_values(
        lines: List[str],
    ) -> Tuple[Dict[str, str], List[str]]:
        raw_values: Dict[str, str] = {}
        hydrographs: List[str] = []
        for line in lines:
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if not key.startswith("Flow Ratio "):
                continue
            value = raw_value.strip()
            if key == RasFlowOptimization.PLAN_KEYS["hydrograph"]:
                hydrographs.append(value)
            else:
                raw_values[key] = value
        return raw_values, hydrographs

    @staticmethod
    def _upsert_flow_ratio_lines(
        lines: List[str],
        requested: Dict[str, Any],
        hydrograph_labels: List[str],
    ) -> List[str]:
        original_keys = set(requested.keys())
        updated_keys = set()
        output: List[str] = []

        for line in lines:
            if "=" not in line:
                output.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key == RasFlowOptimization.PLAN_KEYS["hydrograph"]:
                continue
            if key in requested:
                output.append(
                    f"{key}={RasFlowOptimization._format_plan_value(requested[key])}\n"
                )
                updated_keys.add(key)
            else:
                output.append(line)

        missing = [
            key
            for key in requested
            if key in original_keys and key not in updated_keys
        ]
        new_lines = [
            f"{key}={RasFlowOptimization._format_plan_value(requested[key])}\n"
            for key in missing
        ]
        new_lines.extend(
            f"{RasFlowOptimization.PLAN_KEYS['hydrograph']}={label}\n"
            for label in hydrograph_labels
        )

        insert_index = RasFlowOptimization._find_flow_ratio_insert_index(output)
        output[insert_index:insert_index] = new_lines
        return output

    @staticmethod
    def _find_flow_ratio_insert_index(lines: List[str]) -> int:
        insert_index = None
        for index, line in enumerate(lines):
            if line.startswith("Flow Ratio "):
                insert_index = index + 1
        if insert_index is not None:
            return insert_index

        for index, line in enumerate(lines):
            if line.startswith("Computation Interval="):
                return index
            if line.startswith("CheckData="):
                insert_index = index + 1
        return insert_index if insert_index is not None else len(lines)

    @staticmethod
    def _format_plan_value(value: Any) -> str:
        if isinstance(value, bool):
            return "-1" if value else "0"
        if isinstance(value, (int, np.integer)):
            return f" {int(value)} "
        if isinstance(value, (float, np.floating)):
            return RasFlowOptimization._format_float(float(value))
        return str(value)

    @staticmethod
    def _format_float(value: float) -> str:
        return f"{value:.12g}"

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        mode_key = str(mode).strip().lower()
        if mode_key not in {"stage", "flow", "none"}:
            raise ValueError("mode must be one of: 'stage', 'flow', 'none'")
        return mode_key

    @staticmethod
    def _format_reference(mode: str, reference_location: str) -> str:
        reference = str(reference_location).strip()
        if not reference:
            raise ValueError("reference_location cannot be empty")
        if ":" in reference:
            return reference
        prefix = "Ref Point" if mode == "stage" else "Ref Line"
        return f"{prefix}: {reference}"

    @staticmethod
    def _split_reference(reference: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        if not reference:
            return None, None
        match = re.match(r"(?P<kind>Ref\s+(?:Point|Line)):\s*(?P<name>.*)", reference)
        if not match:
            return None, reference
        return match.group("kind"), match.group("name").strip()

    @staticmethod
    def _infer_mode(
        reference_type: Optional[str],
        raw_values: Dict[str, str],
    ) -> Optional[str]:
        explicit_mode = raw_values.get("Flow Ratio Mode")
        if explicit_mode:
            lowered = explicit_mode.strip().lower()
            if lowered in {"stage", "flow", "none"}:
                return lowered
        if reference_type:
            if "point" in reference_type.lower():
                return "stage"
            if "line" in reference_type.lower():
                return "flow"
        return None

    @staticmethod
    def _normalize_restart_approach(restart_approach: str) -> str:
        key = str(restart_approach).strip().lower().replace("-", "_").replace(" ", "_")
        return RasFlowOptimization.RESTART_APPROACH_VALUES.get(
            key,
            str(restart_approach).strip(),
        )

    @staticmethod
    def _validate_ratio_bounds(
        min_ratio: Union[int, float],
        max_ratio: Union[int, float],
        initial_ratio: Union[int, float],
        max_iterations: int,
    ) -> None:
        min_value = float(min_ratio)
        max_value = float(max_ratio)
        initial_value = float(initial_ratio)
        if min_value > max_value:
            raise ValueError("min_ratio cannot exceed max_ratio")
        if not min_value <= initial_value <= max_value:
            raise ValueError("initial_ratio must be between min_ratio and max_ratio")
        if int(max_iterations) < 1:
            raise ValueError("max_iterations must be at least 1")

    @staticmethod
    def _resolve_hydrograph_labels(
        hydrographs: Optional[Union[str, Iterable[str]]],
        plan_path: Path,
        ras_object=None,
    ) -> List[str]:
        if hydrographs is None:
            try:
                df = RasFlowOptimization.list_flow_hydrographs(
                    plan_path,
                    ras_object=ras_object,
                )
                if "optimization_hydrograph" in df.columns:
                    return [
                        str(value)
                        for value in df["optimization_hydrograph"].dropna().tolist()
                        if str(value).strip()
                    ]
            except Exception as exc:
                logger.debug("Auto-discovery of hydrographs failed: %s", exc)
                return []

        if isinstance(hydrographs, str):
            if hydrographs.strip().lower() == "all":
                return RasFlowOptimization._resolve_hydrograph_labels(
                    None,
                    plan_path,
                    ras_object=ras_object,
                )
            hydrograph_iterable = [hydrographs]
        else:
            hydrograph_iterable = list(hydrographs)

        return [
            RasFlowOptimization._format_hydrograph_label(label)
            for label in hydrograph_iterable
            if str(label).strip()
        ]

    @staticmethod
    def _format_hydrograph_label(label: Any) -> str:
        text = str(label).strip()
        if ":" in text:
            return text
        return f"BCLine: {text}"

    @staticmethod
    def _parse_unsteady_boundary_block(
        block_lines: List[str],
        line_number: int,
    ) -> Dict[str, Any]:
        location_line = block_lines[0].split("=", 1)[1]
        fields = [field.strip() for field in location_line.split(",")]
        row = {
            "river": fields[0] if len(fields) > 0 else "",
            "reach": fields[1] if len(fields) > 1 else "",
            "station": fields[2] if len(fields) > 2 else "",
            "storage_area": fields[4] if len(fields) > 4 else "",
            "flow_area": fields[5] if len(fields) > 5 else "",
            "bc_line": fields[7] if len(fields) > 7 else "",
            "bc_type": "",
            "interval": "",
            "use_dss": "",
            "dss_file": "",
            "dss_path": "",
            "line_number": line_number,
        }

        for raw_line in block_lines[1:]:
            line = raw_line.strip()
            if line.startswith("Interval="):
                row["interval"] = line.split("=", 1)[1].strip()
            elif line.startswith("Flow Hydrograph="):
                row["bc_type"] = "Flow Hydrograph"
            elif line.startswith("Lateral Inflow Hydrograph="):
                row["bc_type"] = "Lateral Inflow Hydrograph"
            elif line.startswith("Uniform Lateral Inflow Hydrograph="):
                row["bc_type"] = "Uniform Lateral Inflow Hydrograph"
            elif line.startswith("Use DSS="):
                row["use_dss"] = line.split("=", 1)[1].strip()
            elif line.startswith("DSS File="):
                row["dss_file"] = line.split("=", 1)[1].strip()
            elif line.startswith("DSS Path="):
                row["dss_path"] = line.split("=", 1)[1].strip()

        if row["bc_line"]:
            row["optimization_hydrograph"] = f"BCLine: {row['bc_line']}"
        else:
            parts = [row["river"], row["reach"], row["station"]]
            row["optimization_hydrograph"] = ", ".join(
                part for part in parts if part
            )
        return row

    @staticmethod
    def _set_observed_target_timeseries(
        unsteady_path: Path,
        mode: str,
        reference: str,
        target_value: Union[int, float],
        target_units: str,
        plan_lines: List[str],
    ) -> None:
        series_type = "Stage" if mode == "stage" else "Flow"
        prefix = f"Observed Time Series={series_type}|"
        start_datetime = RasFlowOptimization._simulation_start_datetime(plan_lines)
        block = [
            f"{prefix}TS Name={reference}\n",
            f"{prefix}TS Used=-1\n",
            f"{prefix}TS Source=Constant\n",
            f"{prefix}TS Table Mode=0\n",
            f"{prefix}TS Table Use Fixed Start=0\n",
            f"{prefix}TS Table StartDateTime={start_datetime}\n",
            f"{prefix}TS Table Interval=1 Hour\n",
            f"{prefix}TS Table Data Units={target_units}\n",
            f"{prefix}TS Table Data Type=INST-VAL\n",
            (
                f"{prefix}TS Constant Value="
                f"{RasFlowOptimization._format_float(float(target_value))}\n"
            ),
            f"{prefix}TS Constant Units={target_units}\n",
        ]

        lines = RasFlowOptimization._read_text_lines(unsteady_path)
        start_idx, end_idx = RasFlowOptimization._find_observed_timeseries_block(
            lines,
            prefix,
            reference,
        )
        if start_idx is not None and end_idx is not None:
            lines[start_idx:end_idx] = block
        else:
            insert_idx = RasFlowOptimization._find_unsteady_observed_insert_index(lines)
            lines[insert_idx:insert_idx] = block

        RasFlowOptimization._write_text_lines(unsteady_path, lines)
        logger.debug("Updated observed %s target in %s", series_type, unsteady_path.name)

    @staticmethod
    def _find_observed_timeseries_block(
        lines: List[str],
        prefix: str,
        reference: str,
    ) -> Tuple[Optional[int], Optional[int]]:
        target_name = f"{prefix}TS Name={reference}"
        for index, line in enumerate(lines):
            if line.strip() != target_name:
                continue
            end = index + 1
            while end < len(lines):
                if (
                    lines[end].startswith("Observed Time Series=")
                    and "|TS Name=" in lines[end]
                ):
                    break
                if not lines[end].startswith(prefix):
                    break
                end += 1
            return index, end
        return None, None

    @staticmethod
    def _find_unsteady_observed_insert_index(lines: List[str]) -> int:
        for index, line in enumerate(lines):
            if line.startswith("Non-Newtonian Method="):
                return index
        return len(lines)

    @staticmethod
    def _simulation_start_datetime(plan_lines: List[str]) -> str:
        for line in plan_lines:
            if not line.startswith("Simulation Date="):
                continue
            value = line.split("=", 1)[1].strip()
            parts = [part.strip() for part in value.split(",")]
            if len(parts) < 2:
                return ""
            date_part = parts[0]
            time_part = parts[1].zfill(4)
            day = date_part[:2]
            month = date_part[2:5].title()
            year = date_part[5:]
            return f"{day}{month}{year} {time_part[:2]}:{time_part[2:]}:00"
        return ""

    @staticmethod
    def _extract_trial_results_from_hdf(hdf_path: Path) -> pd.DataFrame:
        rows = []
        with h5py.File(hdf_path, "r") as hdf_file:
            def visitor(name: str, obj: Any) -> None:
                if not isinstance(obj, h5py.Dataset):
                    return
                lowered = name.lower()
                if not (
                    ("flow" in lowered and "optimization" in lowered)
                    or "flow ratio" in lowered
                ):
                    return
                candidate = RasFlowOptimization._dataset_to_dataframe(obj)
                if candidate.empty:
                    return
                normalized = RasFlowOptimization._normalize_hdf_trial_dataframe(
                    candidate,
                    hdf_path,
                    name,
                )
                if not normalized.empty:
                    rows.append(normalized)

            hdf_file.visititems(visitor)

        if not rows:
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)
        return pd.concat(rows, ignore_index=True)

    @staticmethod
    def _dataset_to_dataframe(dataset: h5py.Dataset) -> pd.DataFrame:
        data = dataset[()]
        if isinstance(data, (bytes, str)) or np.isscalar(data):
            return pd.DataFrame()

        if getattr(data, "dtype", None) is not None and data.dtype.names:
            df = pd.DataFrame.from_records(data)
        elif isinstance(data, np.ndarray) and data.ndim == 2:
            columns = RasFlowOptimization._get_dataset_column_names(
                dataset,
                data.shape[1],
            )
            df = pd.DataFrame(data, columns=columns)
        elif isinstance(data, np.ndarray) and data.ndim == 1:
            df = pd.DataFrame({"value": data})
        else:
            return pd.DataFrame()

        for column in df.columns:
            if df[column].dtype == object:
                df[column] = df[column].map(RasFlowOptimization._decode_hdf_value)
        return df

    @staticmethod
    def _get_dataset_column_names(
        dataset: h5py.Dataset,
        width: int,
    ) -> List[str]:
        for attr_name in (
            "Column Names",
            "Column names",
            "Columns",
            "Variable Names",
            "Variables",
        ):
            if attr_name not in dataset.attrs:
                continue
            raw = dataset.attrs[attr_name]
            values = np.atleast_1d(raw).tolist()
            columns = [
                str(RasFlowOptimization._decode_hdf_value(value)).strip()
                for value in values
            ]
            if len(columns) == width:
                return columns
        return [f"column_{index}" for index in range(width)]

    @staticmethod
    def _decode_hdf_value(value: Any) -> Any:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").strip()
        return value

    @staticmethod
    def _normalize_hdf_trial_dataframe(
        df: pd.DataFrame,
        hdf_path: Path,
        dataset_name: str,
    ) -> pd.DataFrame:
        normalized_columns = {
            column: RasFlowOptimization._normalize_column_name(str(column))
            for column in df.columns
        }
        rename_map = {}
        for column, normalized in normalized_columns.items():
            if normalized in {"trial", "trial_number"}:
                rename_map[column] = "trial"
            elif normalized in {"ratio", "flow_ratio", "hydrograph_ratio"}:
                rename_map[column] = "ratio"
            elif normalized in {"difference", "diff", "error"}:
                rename_map[column] = "difference"
            elif normalized == "target":
                rename_map[column] = "target"
            elif normalized in {"computed", "computed_value"}:
                rename_map[column] = "computed"

        result = df.rename(columns=rename_map)
        required = {"trial", "ratio"}
        if not required.issubset(set(result.columns)):
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)

        result = result.copy()
        result["source"] = "hdf"
        result["source_path"] = str(hdf_path)
        result["source_dataset"] = dataset_name
        result["message"] = None
        result["converged"] = False
        result["failed"] = False
        return result

    @staticmethod
    def _normalize_column_name(name: str) -> str:
        normalized = name.strip().lower()
        normalized = normalized.replace("#", "number")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        return normalized.strip("_")

    @staticmethod
    def _read_compute_messages(
        plan_path: Optional[Path],
        hdf_path: Optional[Path],
    ) -> str:
        if hdf_path is not None and hdf_path.exists():
            try:
                with h5py.File(hdf_path, "r") as hdf_file:
                    path = "Results/Summary/Compute Messages (text)"
                    if path in hdf_file:
                        data = hdf_file[path][()]
                        return str(RasFlowOptimization._decode_compute_message_data(data))
            except Exception as exc:
                logger.debug("Could not read HDF compute messages: %s", exc)

        candidate_paths: List[Path] = []
        if hdf_path is not None:
            candidate_paths.extend(
                [
                    Path(str(hdf_path).replace(".hdf", ".computeMsgs.txt")),
                    Path(str(hdf_path).replace(".hdf", ".comp_msgs.txt")),
                ]
            )
        if plan_path is not None:
            candidate_paths.extend(
                [
                    Path(str(plan_path) + ".computeMsgs.txt"),
                    Path(str(plan_path) + ".comp_msgs.txt"),
                ]
            )

        for candidate_path in candidate_paths:
            if candidate_path.exists():
                return candidate_path.read_text(encoding="utf-8", errors="ignore")
        return ""

    @staticmethod
    def _decode_compute_message_data(data: Any) -> str:
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="ignore")
        if isinstance(data, np.ndarray):
            values = data.ravel().tolist()
            return "\n".join(
                str(RasFlowOptimization._decode_hdf_value(value))
                for value in values
            )
        return str(data)

    @staticmethod
    def _finalize_trial_results(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=RasFlowOptimization.TRIAL_RESULT_COLUMNS)
        result = df.copy()
        for column in RasFlowOptimization.TRIAL_RESULT_COLUMNS:
            if column not in result.columns:
                result[column] = None

        for column in ("trial",):
            result[column] = pd.to_numeric(result[column], errors="coerce").astype(
                "Int64"
            )
        for column in ("ratio", "difference", "target", "computed"):
            result[column] = pd.to_numeric(result[column], errors="coerce")
        for column in ("converged", "failed"):
            result[column] = result[column].fillna(False).astype(bool)

        return result[RasFlowOptimization.TRIAL_RESULT_COLUMNS]

    @staticmethod
    def _parse_float(value: Optional[str]) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except ValueError:
            return None

    @staticmethod
    def _parse_ras_bool(value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"-1", "true", "yes", "1"}:
            return True
        if text in {"0", "false", "no"}:
            return False
        return None

    @staticmethod
    def _refresh_plan_dataframe(ras_object=None) -> None:
        ras_obj = ras_object or ras
        try:
            if getattr(ras_obj, "project_folder", None):
                ras_obj.plan_df = ras_obj.get_plan_entries()
        except Exception:
            logger.debug("Skipped plan_df refresh")
