"""
RasCmdr - Execution operations for running HEC-RAS simulations

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).

Example:
    @log_call
    def my_function():
        
        logger.debug("Additional debug information")
        # Function logic here
        
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasCmdr:
- compute_plan()
- cancel_plan()
- compute_parallel()
- compute_test_mode()
        
        
        
"""
import os
import subprocess
import shutil
import shlex
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from .RasPrj import ras, RasPrj, init_ras_project, get_ras_exe
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUtils import RasUtils
import logging
import time
import queue
from threading import Thread, Lock
from typing import Union, List, Optional, Dict, Any
from pathlib import Path
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread
from itertools import cycle
from ras_commander.RasPrj import RasPrj  # Ensure RasPrj is imported
from threading import Lock, Thread, current_thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from typing import Union, List, Optional, Dict, Any
from numbers import Number
from .LoggingConfig import get_logger
from .Decorators import log_call
from .RasBco import BcoMonitor
from .ComputeResults import ComputeResult, ComputeParallelResult
import pandas as pd
from typing import Callable

logger = get_logger(__name__)

# Module code starts here



class RasCmdr:
    """
    Static class for HEC-RAS plan execution operations.

    All methods are static and designed to be used without instantiation.

    Methods:
        compute_plan(): Execute a single HEC-RAS plan
        compute_parallel(): Execute multiple plans in parallel using worker folders
        compute_test_mode(): Execute multiple plans sequentially in a test folder
    """

    @staticmethod
    def _get_hdf_path(plan_number: Union[str, Number], ras_object: 'RasPrj') -> Path:
        """
        Get the expected HDF results path for a plan.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Path to the expected HDF file
        """
        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        return Path(ras_object.project_folder) / f"{ras_object.project_name}.p{plan_num_str}.hdf"

    @staticmethod
    def _plan_entries_with_expected_hdf_paths(
        plan_entries: Optional[pd.DataFrame],
        project_folder: Union[str, Path],
        project_name: str,
        plan_numbers: List[Union[str, Number]],
    ) -> pd.DataFrame:
        """
        Return plan metadata with expected HDF paths without rereading the .prj.
        """
        normalized_plan_numbers = [
            RasUtils.normalize_ras_number(plan_number)
            for plan_number in plan_numbers
        ]
        project_folder = Path(project_folder)

        if plan_entries is None or plan_entries.empty:
            cached_plan_entries = pd.DataFrame(
                {"plan_number": normalized_plan_numbers}
            )
        else:
            cached_plan_entries = plan_entries.copy()

        if "plan_number" not in cached_plan_entries.columns:
            cached_plan_entries["plan_number"] = normalized_plan_numbers[:len(
                cached_plan_entries
            )]

        cached_plan_entries["plan_number"] = cached_plan_entries[
            "plan_number"
        ].map(RasUtils.normalize_ras_number)

        for column_name in ("HDF_Results_Path", "full_path"):
            if column_name not in cached_plan_entries.columns:
                cached_plan_entries[column_name] = None

        missing_plan_numbers = [
            plan_number
            for plan_number in normalized_plan_numbers
            if plan_number not in set(cached_plan_entries["plan_number"])
        ]
        if missing_plan_numbers:
            cached_plan_entries = pd.concat(
                [
                    cached_plan_entries,
                    pd.DataFrame(
                        {"plan_number": missing_plan_numbers}
                    ),
                ],
                ignore_index=True,
            )

        for plan_number in normalized_plan_numbers:
            plan_mask = cached_plan_entries["plan_number"] == plan_number
            expected_plan_path = project_folder / f"{project_name}.p{plan_number}"
            expected_hdf_path = Path(f"{expected_plan_path}.hdf")
            cached_plan_entries.loc[
                plan_mask, "full_path"
            ] = str(expected_plan_path)
            cached_plan_entries.loc[
                plan_mask, "HDF_Results_Path"
            ] = str(expected_hdf_path)

        return cached_plan_entries

    @staticmethod
    def _update_results_from_cached_plan_entries(
        ras_object: 'RasPrj',
        plan_numbers: List[Union[str, Number]],
        project_folder: Union[str, Path, None] = None,
        project_name: Optional[str] = None,
        plan_entries: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Update results_df using cached plan metadata when the .prj is unavailable.
        """
        normalized_plan_numbers = [
            RasUtils.normalize_ras_number(plan_number)
            for plan_number in plan_numbers
        ]
        project_folder = Path(project_folder or ras_object.project_folder)
        project_name = project_name or ras_object.project_name
        cached_plan_entries = (
            plan_entries
            if plan_entries is not None
            else getattr(ras_object, "plan_df", None)
        )

        ras_object.plan_df = RasCmdr._plan_entries_with_expected_hdf_paths(
            cached_plan_entries,
            project_folder,
            project_name,
            normalized_plan_numbers,
        )
        return ras_object.update_results_df(
            plan_numbers=normalized_plan_numbers
        )

    @staticmethod
    def _normalize_requested_plan_numbers(
        plan_number: Union[str, Number, List[Union[str, Number]], None]
    ) -> Optional[List[str]]:
        """
        Normalize user-supplied plan selectors to two-digit plan numbers.
        """
        if plan_number is None:
            return None

        if isinstance(plan_number, (str, Number)):
            requested_plan_numbers = [plan_number]
        else:
            requested_plan_numbers = list(plan_number)

        return [
            RasUtils.normalize_ras_number(requested_plan)
            for requested_plan in requested_plan_numbers
        ]

    @staticmethod
    def _filter_plan_entries(
        plan_entries: pd.DataFrame,
        plan_number: Union[str, Number, List[Union[str, Number]], None]
    ) -> pd.DataFrame:
        """
        Filter plan entries using normalized two-digit plan numbers.
        """
        if plan_number is None:
            return plan_entries

        requested_plan_numbers = RasCmdr._normalize_requested_plan_numbers(
            plan_number
        )
        filtered_plan_entries = plan_entries[
            plan_entries["plan_number"].isin(requested_plan_numbers)
        ].copy()
        available_plan_numbers = set(filtered_plan_entries["plan_number"])
        missing_plan_numbers = [
            requested_plan
            for requested_plan in requested_plan_numbers
            if requested_plan not in available_plan_numbers
        ]

        if missing_plan_numbers:
            logger.warning(
                "Requested plan numbers not found in plan_df after "
                f"normalization: {missing_plan_numbers}"
            )

        filtered_plan_list = list(filtered_plan_entries["plan_number"])
        if len(filtered_plan_list) > 10:
            logger.info(
                "Filtered plans to execute: %s plan(s) (%s ... %s)",
                len(filtered_plan_list),
                ", ".join(map(str, filtered_plan_list[:5])),
                ", ".join(map(str, filtered_plan_list[-3:])),
            )
            logger.debug("Full filtered plan list: %s", filtered_plan_list)
        else:
            logger.info("Filtered plans to execute: %s", filtered_plan_list)
        return filtered_plan_entries

    @staticmethod
    def _get_plan_geometry_number(
        plan_entries: pd.DataFrame,
        plan_number: Union[str, Number]
    ) -> Optional[str]:
        """
        Resolve the geometry number associated with a plan entry.
        """
        normalized_plan_number = RasUtils.normalize_ras_number(plan_number)
        matching_rows = plan_entries[
            plan_entries["plan_number"] == normalized_plan_number
        ]
        if matching_rows.empty:
            return None

        plan_row = matching_rows.iloc[0]
        for column_name in ("geometry_number", "Geom File"):
            value = plan_row.get(column_name)
            if pd.isna(value):
                continue

            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if digits:
                return digits.zfill(2)

        return None

    @staticmethod
    def _get_worker_plan_artifacts(
        worker_folder: Path,
        project_name: str,
        plan_number: str,
        geometry_number: Optional[str] = None
    ) -> List[Path]:
        """
        Collect plan-owned worker artifacts that are safe to consolidate.
        """
        artifact_patterns = [
            f"{project_name}.p{plan_number}",
            f"{project_name}.p{plan_number}.*",
            f"{project_name}.bco{plan_number}",
            f"{project_name}.O{plan_number}",
            f"{project_name}.c{plan_number}",
        ]
        if geometry_number:
            artifact_patterns.append(f"{project_name}.g{geometry_number}.hdf")

        artifact_paths = {}
        for pattern in artifact_patterns:
            for artifact_path in worker_folder.glob(pattern):
                if artifact_path.is_file():
                    artifact_paths[artifact_path.name] = artifact_path

        return [artifact_paths[name] for name in sorted(artifact_paths)]

    @staticmethod
    def _log_execution_results(execution_results: Dict[str, bool]) -> None:
        """
        Log a concise execution summary with per-plan detail at DEBUG.
        """
        if not execution_results:
            logger.info("Execution results: no plans executed")
            return

        successful_plans = [
            str(plan_num)
            for plan_num, success in execution_results.items()
            if success
        ]
        failed_plans = [
            str(plan_num)
            for plan_num, success in execution_results.items()
            if not success
        ]
        total_plans = len(execution_results)

        logger.info(
            "Execution results: %s/%s plan(s) successful",
            len(successful_plans),
            total_plans,
        )
        for plan_num in successful_plans:
            logger.debug("Plan %s: Successful", plan_num)
        if failed_plans:
            logger.warning("Failed plan(s): %s", ", ".join(failed_plans))
            for plan_num in failed_plans:
                logger.debug("Plan %s: Failed", plan_num)

    @staticmethod
    def _copy_worker_artifact(source_path: Path, dest_path: Path) -> bool:
        """
        Copy a worker artifact unless the destination is already newer.
        """
        if not source_path.exists() or not source_path.is_file():
            return False

        if dest_path.exists():
            source_stat = source_path.stat()
            dest_stat = dest_path.stat()

            if dest_stat.st_mtime > source_stat.st_mtime:
                logger.debug(
                    "Skipping older worker artifact %s because destination %s is newer",
                    source_path,
                    dest_path,
                )
                return False

            if (
                dest_stat.st_mtime == source_stat.st_mtime
                and dest_stat.st_size == source_stat.st_size
            ):
                logger.debug(
                    "Skipping unchanged worker artifact %s",
                    source_path,
                )
                return False

            dest_path.unlink()

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        return True

    @staticmethod
    def _verify_completion(
        hdf_path: Path,
        check_errors: bool = True,
        modified_after: Optional[float] = None,
    ) -> bool:
        """
        Verify that a HEC-RAS computation completed successfully (HDF-only).

        Checks three conditions:
        1. 'Complete Process' present in compute messages
        2. '/Plan Data/Plan Information' HDF group exists (structural integrity)
        3. No error patterns in compute messages (when check_errors=True)

        Args:
            hdf_path: Path to plan HDF file
            check_errors: If True, also fail verification if errors detected
                         in compute messages (default: True)
            modified_after: Optional execution start timestamp. When provided,
                reject an otherwise valid HDF whose modification time predates
                this execution. This prevents a failed forced rerun from being
                credited with a copied or stale successful result.

        Returns:
            bool: True if verification passed
        """
        if not hdf_path.exists():
            logger.debug(f"HDF file does not exist: {hdf_path}")
            return False

        if modified_after is not None:
            # A two-second tolerance accommodates filesystems with coarse
            # timestamp resolution while still excluding pre-existing HDFs.
            if hdf_path.stat().st_mtime < float(modified_after) - 2.0:
                logger.debug(
                    "Verification rejected stale HDF %s (modified before this run)",
                    hdf_path.name,
                )
                return False

        try:
            import h5py
            from .hdf.HdfResultsPlan import HdfResultsPlan

            compute_msgs = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)

            if not compute_msgs or 'Complete Process' not in compute_msgs:
                logger.debug(f"Verification failed: 'Complete Process' not found in {hdf_path.name}")
                return False

            # Structural check: /Plan Data/Plan Information must exist
            with h5py.File(str(hdf_path), 'r') as hdf:
                if hdf.get('Plan Data/Plan Information') is None:
                    logger.warning(f"Verification failed: '/Plan Data/Plan Information' missing in {hdf_path.name} (partial HDF)")
                    return False

            if check_errors:
                from .results.ResultsParser import ResultsParser
                parsed = ResultsParser.parse_compute_messages(compute_msgs)
                if parsed['has_errors']:
                    logger.warning(f"Verification failed: {parsed['error_count']} errors found in {hdf_path.name}")
                    return False

            logger.debug(f"Verification passed for {hdf_path.name}")
            return True
        except Exception as e:
            logger.warning(f"Error verifying completion for {hdf_path}: {e}")
            return False

    @staticmethod
    def _rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path: Path) -> bool:
        """Return True when a Windows RasUnsteady process still owns this plan tmp HDF."""
        if os.name != "nt":
            return False

        try:
            needle = str(tmp_hdf_path).replace("'", "''")
            ps_command = (
                f"$needle = '{needle}'; "
                "$proc = Get-CimInstance Win32_Process "
                "-Filter \"Name='RasUnsteady.exe'\" | "
                "Where-Object { $_.CommandLine -like \"*$needle*\" } | "
                "Select-Object -First 1 -ExpandProperty ProcessId; "
                "if ($proc) { Write-Output $proc }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception as exc:
            logger.debug(
                "Could not query RasUnsteady process state for %s: %s",
                tmp_hdf_path.name,
                exc,
            )
            return False

    @staticmethod
    def _wait_for_async_plan_completion(
        plan_number: Union[str, Number],
        ras_object: 'RasPrj',
        check_errors: bool = True,
        poll_interval: float = 5.0,
        timeout_seconds: float = 7200.0,
        modified_after: Optional[float] = None,
    ) -> Optional[bool]:
        """
        Wait for a solver child process that outlives ``Ras.exe -c``.

        HEC-RAS 7 can return from the command launcher before the child
        ``RasUnsteady.exe`` process has finished writing ``.p##.tmp.hdf``.
        Returning before that child exits lets parallel workers reuse the same
        folder early and can create false failure logs.  This helper only waits
        when there is concrete evidence of an active or partial async solve.

        Returns
        -------
        True
            Final plan HDF verified.
        False
            An async solve was observed, but no verified final HDF appeared.
        None
            No async solve evidence was present; callers should keep their
            normal success/failure behavior.
        """
        plan_num = RasUtils.normalize_ras_number(plan_number)
        hdf_path = RasCmdr._get_hdf_path(plan_num, ras_object)
        tmp_hdf_path = (
            Path(ras_object.project_folder)
            / f"{ras_object.project_name}.p{plan_num}.tmp.hdf"
        )

        if RasCmdr._verify_completion(
            hdf_path,
            check_errors=check_errors,
            modified_after=modified_after,
        ):
            return True

        active = RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path)
        partial_exists = tmp_hdf_path.exists()
        if not active and not partial_exists:
            return None

        logger.debug(
            "Waiting for RasUnsteady to finish plan %s after Ras.exe returned",
            plan_num,
        )
        deadline = time.time() + timeout_seconds
        observed_async = True

        while time.time() < deadline:
            if RasCmdr._verify_completion(
                hdf_path,
                check_errors=check_errors,
                modified_after=modified_after,
            ):
                return True

            active = RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path)
            partial_exists = tmp_hdf_path.exists()
            if not active and not partial_exists:
                return False

            if not active and partial_exists:
                # Give HEC-RAS a short grace window to rename/close files after
                # the solver process exits, then verify one final time.
                time.sleep(min(poll_interval, 2.0))
                if RasCmdr._verify_completion(
                    hdf_path,
                    check_errors=check_errors,
                    modified_after=modified_after,
                ):
                    return True
                if not RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path):
                    return False

            time.sleep(poll_interval)

        logger.warning(
            "Timed out waiting for RasUnsteady to finish plan %s after %.0f seconds",
            plan_num,
            timeout_seconds,
        )
        return False if observed_async else None

    @staticmethod
    @log_call
    def cancel_plan(
        plan_number: Union[str, Number],
        ras_object=None,
        timeout_seconds: float = 10.0,
    ) -> bool:
        """Stop only the active Windows process tree for one project plan.

        Process matching is deliberately strict: a ``Ras.exe`` launcher must
        contain both the initialized project path and resolved plan path, while
        a solver must contain the exact plan ``.tmp.hdf`` path. Unrelated RAS
        sessions are never selected by executable name alone.

        Args:
            plan_number: Plan number to cancel (for example, ``"01"``).
            ras_object: Initialized :class:`RasPrj` object. Uses the global
                project when omitted.
            timeout_seconds: Grace period before force-killing only the already
                matched processes.

        Returns:
            ``True`` when a matching process tree was found and stopped;
            ``False`` when no matching active process existed.
        """
        if os.name != "nt":
            raise NotImplementedError(
                "RasCmdr.cancel_plan() currently supports Windows HEC-RAS "
                "process trees only."
            )

        import psutil

        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()
        plan_num = RasUtils.normalize_ras_number(plan_number)
        project_path = Path(ras_obj.prj_file).resolve(strict=False)
        resolved_plan_path = RasPlan.get_plan_path(plan_num, ras_obj)
        if resolved_plan_path is None:
            raise FileNotFoundError(f"Plan file not found: {plan_num}")
        plan_path = Path(resolved_plan_path).resolve(strict=False)
        tmp_hdf_path = (
            Path(ras_obj.project_folder)
            / f"{ras_obj.project_name}.p{plan_num}.tmp.hdf"
        ).resolve(strict=False)

        def command_needle(path: Path) -> str:
            return str(path).replace("/", "\\").lower()

        project_needle = command_needle(project_path)
        plan_needle = command_needle(plan_path)
        tmp_hdf_needle = command_needle(tmp_hdf_path)
        roots = []

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = str(process.info.get("name") or "").lower()
                command_line = " ".join(
                    str(part) for part in (process.info.get("cmdline") or [])
                ).replace("/", "\\").lower()
                is_launcher = (
                    name == "ras.exe"
                    and project_needle in command_line
                    and plan_needle in command_line
                )
                is_solver = (
                    name == "rasunsteady.exe"
                    and tmp_hdf_needle in command_line
                )
                if is_launcher or is_solver:
                    roots.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not roots:
            logger.info("No active HEC-RAS process found for plan %s", plan_num)
            return False

        targets = {}
        for root in roots:
            try:
                for child in root.children(recursive=True):
                    targets[child.pid] = child
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            targets[root.pid] = root

        ordered_targets = list(targets.values())
        for process in reversed(ordered_targets):
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        _, alive = psutil.wait_procs(
            ordered_targets,
            timeout=max(0.1, float(timeout_seconds)),
        )
        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if alive:
            psutil.wait_procs(alive, timeout=3.0)

        logger.info(
            "Stopped HEC-RAS process tree for plan %s (%s matched process(es))",
            plan_num,
            len(targets),
        )
        return True
    
    @staticmethod
    @log_call
    def compute_plan(
        plan_number: Union[str, Number, Path],
        dest_folder=None,
        ras_object=None,
        clear_geompre=False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        num_cores=None,
        overwrite_dest=False,
        skip_existing: bool = False,
        verify: bool = False,
        stream_callback: Optional[Callable] = None,
        use_optimal_hdf_settings: bool = False,
        hdf_settings_profile: str = "balanced",
        hdf_additional_variables: Optional[List[str]] = None,
        hdf_output_variables: Optional[List[str]] = None,
        hdf_output_options: Optional[Dict[str, Any]] = None,
        hdf_output_profile: Optional[str] = None,
        dialog_watchdog: bool = True,
    ) -> 'ComputeResult':
        """
        Execute a single HEC-RAS plan in a specified location.

        This function runs a HEC-RAS plan by launching the HEC-RAS executable through command line,
        allowing for destination folder specification, core count control, and geometry preprocessor management.

        Args:
            plan_number (Union[str, Number, Path]): The plan number to execute (e.g., "01", 1, 1.0) or the full path to the plan file.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder (str, Path, optional): Name of the folder or full path for computation.
                If a string is provided, it will be created in the same parent directory as the project folder.
                If a full path is provided, it will be used as is.
                If None, computation occurs in the original project folder, modifying the original project.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files (.c## files). Defaults to False.
                Set to True when geometry has been modified to force recomputation of preprocessor files.
            force_geompre (bool, optional): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
            force_rerun (bool, optional): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
                When True, always executes regardless of result currency.
            num_cores (int, optional): Number of cores to use for the plan execution.
                If None, the current setting in the plan file is not changed.
                Generally, 2-4 cores provides good performance for most models.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.
                Set to True to replace an existing destination folder with the same name.
            skip_existing (bool, optional): If True, skip computation if HDF results file already exists
                and contains 'Complete Process' in compute messages. Defaults to False.
                Useful for resuming interrupted batch runs or incremental workflows.
            verify (bool, optional): If True, verify computation completed successfully by checking
                for 'Complete Process' in compute messages after execution. Defaults to False.
                Returns False if verification fails even if subprocess returned success.
            stream_callback (Callable, optional): Callback object for real-time execution progress monitoring.
                Must implement ExecutionCallback protocol methods (all methods optional):
                - on_prep_start(plan_number): Called before geometry preprocessing
                - on_prep_complete(plan_number): Called after preprocessing
                - on_exec_start(plan_number, command): Called when HEC-RAS subprocess starts
                - on_exec_message(plan_number, message): Called for each .bco file message (real-time)
                - on_exec_complete(plan_number, success, duration): Called when execution finishes
                - on_verify_result(plan_number, verified): Called after verification (if verify=True)
                IMPORTANT: Must be thread-safe when used with compute_parallel().
                See ras_commander.callbacks for example implementations.
            use_optimal_hdf_settings (bool, optional): If True, apply ras-commander's
                recommended HDF write settings to the plan before currency checks and execution.
                Defaults to False.
            hdf_settings_profile (str, optional): HDF settings profile to apply when
                use_optimal_hdf_settings=True. Options are "balanced", "speed", "size",
                and "nas". Defaults to "balanced".
            hdf_additional_variables (List[str], optional): Additional HDF output variables
                to enable when use_optimal_hdf_settings=True.
            hdf_output_variables (List[str], optional): Additional HDF output variables
                to enable before execution.
            hdf_output_options (Dict[str, Any], optional): Explicit HDF output options
                passed to ``RasPlan.set_hdf_output_options()`` before execution.
            hdf_output_profile (str, optional): Named HDF output profile to apply before
                execution. Equivalent to ``use_optimal_hdf_settings=True`` with a profile.

        Returns:
            ComputeResult: Result object with ``success`` bool and ``results_df_row`` (pd.Series or None).
                Backward compatible with bool: ``if RasCmdr.compute_plan("01"):`` still works.
                Access execution metrics via ``result.results_df_row`` (e.g., runtime, volume accounting).
                ``results_df_row`` is None when dest_folder is used, execution fails, or extraction errors.
                When skip_existing=True and results exist, returns ComputeResult(success=True).

        Raises:
            ValueError: If the specified dest_folder already exists and is not empty, and overwrite_dest is False.
            FileNotFoundError: If the plan file or project file cannot be found.
            PermissionError: If there are issues accessing or writing to the destination folder.
            subprocess.CalledProcessError: If the HEC-RAS execution fails.

        Examples:
            # Run a plan in the original project folder
            RasCmdr.compute_plan("01")

            # Run a plan in a separate folder
            RasCmdr.compute_plan("01", dest_folder="computation_folder")

            # Run a plan with a specific number of cores
            RasCmdr.compute_plan("01", num_cores=4)

            # Run a plan in a specific folder, overwriting if it exists
            RasCmdr.compute_plan("01", dest_folder="computation_folder", overwrite_dest=True)

            # Skip computation if results already exist
            RasCmdr.compute_plan("01", skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_plan("01", verify=True)

            # Run with real-time progress monitoring
            from ras_commander.callbacks import ConsoleCallback
            callback = ConsoleCallback()
            RasCmdr.compute_plan("01", stream_callback=callback)

            # Run with recommended HDF write parameters
            RasCmdr.compute_plan("01", use_optimal_hdf_settings=True)

            # Run a plan in a specific folder with multiple options
            RasCmdr.compute_plan(
                "01",
                dest_folder="computation_folder",
                num_cores=2,
                clear_geompre=True,
                overwrite_dest=True,
                verify=True
            )

        Notes:
            - For executing multiple plans, consider using compute_parallel() or compute_test_mode().
            - Setting num_cores appropriately is important for performance:
              * 1-2 cores: Highest efficiency per core, good for small models
              * 3-8 cores: Good balance for most models
              * >8 cores: May have diminishing returns due to overhead
            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.
            - When skip_existing=True with dest_folder, the check happens AFTER copying to destination.
            - The verify parameter checks for 'Complete Process' in HDF compute messages.
        """
        _success = False
        _results_df_row = None
        _ras_obj = None
        _did_execute = False  # Track if we actually ran HEC-RAS (vs skip/early exit)
        _watchdog = None
        try:
            ras_obj = ras_object if ras_object is not None else ras
            _ras_obj = ras_obj
            logger.debug(f"Using ras_object with project folder: {ras_obj.project_folder}")
            ras_obj.check_initialized()

            if dest_folder is not None:
                dest_folder = Path(ras_obj.project_folder).parent / dest_folder if isinstance(dest_folder, str) else Path(dest_folder)

                if dest_folder.resolve() == Path(ras_obj.project_folder).resolve():
                    logger.info("Destination folder matches the active project folder; executing in place.")
                    dest_folder = None
                    compute_ras = ras_obj
                    compute_prj_path = ras_obj.prj_file
                else:
                    if dest_folder.exists():
                        if overwrite_dest:
                            if not RasUtils.remove_with_retry(dest_folder, ras_object=ras_obj):
                                raise PermissionError(f"Unable to remove destination folder: {dest_folder}")
                            logger.info("Destination folder exists; overwriting as requested: %s", dest_folder.name)
                            logger.debug(f"Overwriting destination folder: {dest_folder}")
                        elif any(dest_folder.iterdir()):
                            error_msg = f"Destination folder '{dest_folder}' exists and is not empty. Use overwrite_dest=True to overwrite."
                            logger.error(error_msg)
                            raise ValueError(error_msg)

                    dest_folder.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(ras_obj.project_folder, dest_folder, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                    logger.info("Copied project folder to destination: %s", dest_folder.name)
                    logger.debug(f"Copied project folder to destination path: {dest_folder}")

                    compute_ras = RasPrj()
                    compute_ras.initialize(dest_folder, ras_obj.ras_exe_path)
                    compute_prj_path = compute_ras.prj_file
            if dest_folder is None:
                compute_ras = ras_obj
                compute_prj_path = ras_obj.prj_file

            # Determine the plan path
            compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

            if not compute_prj_path or not compute_plan_path:
                logger.error(f"Could not find project file or plan file for plan {plan_number}")
                _success = False
                return ComputeResult(success=False, results_df_row=None)

            if use_optimal_hdf_settings or hdf_output_profile:
                profile_to_apply = hdf_output_profile or hdf_settings_profile
                variables_to_apply = hdf_additional_variables or hdf_output_variables
                hdf_settings_success = RasPlan.use_optimal_hdf_settings(
                    compute_plan_path,
                    profile=profile_to_apply,
                    additional_variables=variables_to_apply,
                    ras_object=compute_ras
                )
                if hdf_settings_success:
                    logger.info(
                        f"Applied '{profile_to_apply}' HDF settings profile "
                        f"to plan: {compute_plan_path.name}"
                    )
                else:
                    logger.warning(
                        f"Could not apply '{profile_to_apply}' HDF settings profile "
                        f"to plan: {compute_plan_path.name}"
                    )

            if hdf_output_options:
                hdf_options_success = RasPlan.set_hdf_output_options(
                    compute_plan_path,
                    ras_object=compute_ras,
                    **hdf_output_options
                )
                if not hdf_options_success:
                    logger.warning(f"Could not apply explicit HDF output options to {compute_plan_path.name}")

            if hdf_output_variables and not (use_optimal_hdf_settings or hdf_output_profile):
                RasPlan.set_hdf_output_variables(
                    compute_plan_path,
                    hdf_output_variables,
                    enabled=True,
                    ras_object=compute_ras
                )

            # Skip existing check - runs regardless of force_rerun (for resume capability)
            if skip_existing:
                hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                if RasCmdr._verify_completion(hdf_path, check_errors=False):
                    logger.info(f"Skipping plan {plan_number}: HDF results already exist with 'Complete Process'")
                    _success = True
                    return ComputeResult(success=True, results_df_row=None)

            # Smart skip: check file modification times (unless force_rerun or skip_existing)
            # Note: Smart skip is bypassed when skip_existing=True since that provides explicit skip logic
            if not force_rerun and not skip_existing:
                from .RasCurrency import RasCurrency
                is_current, reason = RasCurrency.are_plan_results_current(plan_number, compute_ras)
                if is_current:
                    logger.info(f"Skipping plan {plan_number}: {reason}")
                    _success = True
                    return ComputeResult(success=True, results_df_row=None)
                else:
                    logger.debug(f"Plan {plan_number} needs execution: {reason}")

            # Always enable Write Detailed= 1 to ensure .computeMsgs.txt is written
            # This is critical for results_df fallback on pre-6.4 HEC-RAS versions
            BcoMonitor.enable_detailed_logging(compute_plan_path)
            logger.debug(f"Enabled Write Detailed= 1 for plan {plan_number}")

            # Enable .bco monitoring if callback provided
            bco_monitor = None
            if stream_callback:
                # Create monitor with callback wrapper
                bco_monitor = BcoMonitor(
                    project_path=Path(compute_ras.project_folder),
                    plan_number=RasUtils.normalize_ras_number(plan_number),
                    project_name=compute_ras.project_name,
                    message_callback=lambda msg: (
                        stream_callback.on_exec_message(str(plan_number), msg)
                        if hasattr(stream_callback, 'on_exec_message') else None
                    )
                )
                logger.debug(f"BcoMonitor initialized for plan {plan_number}")

            # Callback: preprocessing start
            if stream_callback and hasattr(stream_callback, 'on_prep_start'):
                stream_callback.on_prep_start(str(plan_number))

            # Handle geometry preprocessor clearing
            if force_geompre:
                # Force full geometry reprocessing (clears both .g##.hdf AND .c## files)
                from .RasCurrency import RasCurrency
                try:
                    RasCurrency.clear_geom_hdf(plan_number, compute_ras)
                    RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.debug(f"Force-cleared all geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error force-clearing geometry preprocessor files for plan {plan_number}: {str(e)}")
            elif clear_geompre:
                # Original behavior - only clear .c## files
                try:
                    RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.debug(f"Cleared geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error clearing geometry preprocessor files for plan {plan_number}: {str(e)}")

            # Set the number of cores if specified
            if num_cores is not None:
                try:
                    RasPlan.set_num_cores(compute_plan_path, num_cores=num_cores, ras_object=compute_ras)
                    logger.debug(f"Set number of cores to {num_cores} for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error setting number of cores for plan {plan_number}: {str(e)}")

            # Callback: preprocessing complete
            if stream_callback and hasattr(stream_callback, 'on_prep_complete'):
                stream_callback.on_prep_complete(str(plan_number))

            # Prepare the command for HEC-RAS execution
            cmd = f'"{compute_ras.ras_exe_path}" -c "{compute_prj_path}" "{compute_plan_path}"'
            logger.debug("Running Ras.exe with -c command line flag for plan %s", plan_number)
            logger.debug(f"Running command: {cmd}")

            # Per-plan stdio log. HEC-RAS stdout/stderr are redirected to this file
            # rather than a PIPE to avoid an inherited-pipe deadlock (CLB-880): with
            # shell=True the pipe's write handle is inherited by the whole
            # cmd.exe -> Ras.exe -> RasUnsteady.exe tree, and the parent blocks on
            # pipe EOF until EVERY descendant closes it. If a solver grandchild
            # lingers past compute completion (intermittent, and far more likely
            # under CPU contention) the read end never reaches EOF and the call
            # hangs forever. HEC-RAS emits no compute messages to stdio -- they go
            # to .bco##/.computeMsgs.txt, which the library already parses -- so a
            # file loses no diagnostics while removing the EOF dependency entirely.
            _run_log_path = (
                Path(compute_ras.project_folder)
                / f"_compute_p{RasUtils.normalize_ras_number(plan_number)}.log"
            )

            # Callback: execution start
            if stream_callback and hasattr(stream_callback, 'on_exec_start'):
                stream_callback.on_exec_start(str(plan_number), cmd)

            # Execute the HEC-RAS command
            _did_execute = True
            start_time = time.time()
            try:
                if dialog_watchdog:
                    from .RasDialogWatchdog import DialogWatchdog
                    _watchdog = DialogWatchdog()
                    _watchdog.start()

                # Choose execution method based on whether callback is provided
                if stream_callback and bco_monitor:
                    # Use Popen for real-time monitoring. Redirect stdio to the
                    # per-plan log file (not PIPE) to avoid the inherited-pipe
                    # deadlock (CLB-880). monitor_until_signal() polls the .bco
                    # file and process.poll(); it never reads process.stdout, so
                    # nothing here depends on a pipe.
                    with open(_run_log_path, "w", encoding="utf-8", errors="ignore") as _run_log_fh:
                        process = subprocess.Popen(
                            cmd,
                            stdout=_run_log_fh,
                            stderr=subprocess.STDOUT,
                            cwd=str(compute_ras.project_folder),
                            shell=True
                        )
                        if _watchdog:
                            _watchdog.add_pid(process.pid)

                        # Monitor .bco file until process completes
                        # (BcoMonitor will call on_exec_message callback as messages appear)
                        bco_monitor.monitor_until_signal(process)

                        # Wait for process to complete
                        return_code = process.wait()

                    # Check if subprocess succeeded
                    if return_code != 0:
                        raise subprocess.CalledProcessError(return_code, cmd)

                else:
                    # Original behavior when no callback. Redirect stdio to the
                    # per-plan log file instead of capture_output/PIPE: with
                    # shell=True the PIPE write handle is inherited by the
                    # cmd.exe -> Ras.exe -> RasUnsteady.exe tree, and
                    # subprocess.run() blocks on pipe EOF until every grandchild
                    # exits -- the intermittent CLB-880 hang. A file handle has no
                    # EOF wait, so run() returns as soon as the process exits.
                    with open(_run_log_path, "w", encoding="utf-8", errors="ignore") as _run_log_fh:
                        subprocess.run(
                            cmd,
                            check=True,
                            shell=True,
                            stdout=_run_log_fh,
                            stderr=subprocess.STDOUT,
                        )

                end_time = time.time()
                run_time = end_time - start_time
                logger.debug(
                    f"HEC-RAS execution completed for plan {plan_number} "
                    f"in {run_time:.2f} seconds"
                )

                async_verified = RasCmdr._wait_for_async_plan_completion(
                    plan_number,
                    compute_ras,
                    check_errors=verify,
                    modified_after=start_time,
                )
                if async_verified is True:
                    logger.debug(
                        "Verified final HDF for plan %s after Ras.exe returned",
                        plan_number,
                    )
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)
                    if verify and stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), True)
                    _success = True
                elif async_verified is False and verify:
                    logger.error(
                        "Verification failed for plan %s after Ras.exe returned. "
                        "See: https://rascommander.info/user-guide/plan-execution/",
                        plan_number,
                    )
                    _success = False
                    if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), False)
                else:
                    # Callback: execution complete
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)

                    # Verify completion if requested
                    if verify:
                        hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                        verified = (
                            async_verified is True
                            or RasCmdr._verify_completion(
                                hdf_path,
                                modified_after=start_time,
                            )
                        )

                        # Callback: verification result
                        if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                            stream_callback.on_verify_result(str(plan_number), verified)

                        if verified:
                            logger.debug(f"Verification passed for plan {plan_number}")
                            _success = True
                        else:
                            logger.error(
                                f"Verification failed for plan {plan_number}: 'Complete Process' not found in compute messages. "
                                f"See: https://rascommander.info/user-guide/plan-execution/"
                            )
                            _success = False
                    else:
                        _success = True

            except subprocess.CalledProcessError as e:
                end_time = time.time()
                run_time = end_time - start_time
                async_verified = RasCmdr._wait_for_async_plan_completion(
                    plan_number,
                    compute_ras,
                    check_errors=True,
                    modified_after=start_time,
                )
                if async_verified is True:
                    logger.info(
                        "Ras.exe returned exit code %s for plan %s, but the final HDF verified after solver completion",
                        e.returncode,
                        plan_number,
                    )
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)
                    _success = True
                else:
                    logger.error(f"Error running plan: {plan_number} (exit code {e.returncode})")
                    logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

                    # stdout/stderr were redirected to a file (no PIPE), so e.output is
                    # None; surface the tail of the run log for context. The substantive
                    # compute messages are read from the .bco/.computeMsgs files below.
                    try:
                        if _run_log_path.exists():
                            _log_text = _run_log_path.read_text(encoding="utf-8", errors="ignore").strip()
                            if _log_text:
                                logger.error(f"HEC-RAS console output ({_run_log_path.name}):\n{_log_text[-2000:]}")
                    except Exception as _log_err:
                        logger.debug(f"Could not read run log {_run_log_path}: {_log_err}")

                    # Read compute message files (.bco## for 5.x, .computeMsgs.txt/.comp_msgs.txt for 6.x+)
                    plan_num_str = RasUtils.normalize_ras_number(plan_number)
                    try:
                        bco_path = Path(compute_ras.project_folder) / f"{compute_ras.project_name}.bco{plan_num_str}"
                        if bco_path.exists():
                            bco_content = bco_path.read_text(encoding='utf-8', errors='ignore')
                            if bco_content.strip():
                                logger.error(f"Compute messages from {bco_path.name}:\n{bco_content}")
                            else:
                                logger.debug(f"BCO file {bco_path.name} exists but is empty")
                    except Exception as bco_err:
                        logger.debug(f"Could not read .bco file: {bco_err}")

                    try:
                        for suffix in [f".p{plan_num_str}.computeMsgs.txt", f".p{plan_num_str}.comp_msgs.txt"]:
                            msg_path = Path(compute_ras.project_folder) / f"{compute_ras.project_name}{suffix}"
                            if msg_path.exists():
                                msg_content = msg_path.read_text(encoding='utf-8', errors='ignore')
                                if msg_content.strip():
                                    logger.error(f"Compute messages from {msg_path.name}:\n{msg_content}")
                                break
                    except Exception as msg_err:
                        logger.debug(f"Could not read compute messages file: {msg_err}")

                    # Callback: execution complete (failure case)
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), False, run_time)

                    _success = False
        except Exception as e:
            logger.critical(f"Error in compute_plan: {str(e)}")
            _success = False
        finally:
            if _watchdog:
                _watchdog.stop()

            # Update the RAS object's dataframes ONLY if executing in original folder
            # When dest_folder is used, the original project is unchanged
            if _ras_obj and dest_folder is None:
                try:
                    _ras_obj.plan_df = _ras_obj.get_plan_entries()
                    _ras_obj.geom_df = _ras_obj.get_geom_entries()
                    _ras_obj.flow_df = _ras_obj.get_flow_entries()
                    _ras_obj.unsteady_df = _ras_obj.get_unsteady_entries()
                    if _did_execute:
                        normalized_plan_number = RasUtils.normalize_ras_number(
                            plan_number
                        )
                        _ras_obj.update_results_df(
                            plan_numbers=[normalized_plan_number]
                        )
                        # Capture results_df row for the executed plan
                        try:
                            plan_num_str = normalized_plan_number
                            mask = _ras_obj.results_df['plan_number'] == plan_num_str
                            if mask.any():
                                _results_df_row = _ras_obj.results_df[mask].iloc[0].copy()
                        except Exception as e:
                            logger.debug(f"Could not extract results_df_row: {e}")
                except Exception as e_refresh:
                    logger.warning(f"Error refreshing DataFrames after compute_plan: {e_refresh}")
                    if _did_execute:
                        try:
                            normalized_plan_number = RasUtils.normalize_ras_number(
                                plan_number
                            )
                            RasCmdr._update_results_from_cached_plan_entries(
                                _ras_obj,
                                [normalized_plan_number],
                            )
                            mask = (
                                _ras_obj.results_df["plan_number"]
                                == normalized_plan_number
                            )
                            if mask.any():
                                _results_df_row = (
                                    _ras_obj.results_df[mask].iloc[0].copy()
                                )
                        except Exception as e_results:
                            logger.warning(
                                "Could not summarize plan %s after refresh "
                                "failure: %s",
                                plan_number,
                                e_results,
                            )

        return ComputeResult(success=_success, results_df_row=_results_df_row)



    @staticmethod
    @log_call
    def compute_parallel(
        plan_number: Union[str, Number, List[Union[str, Number]], None] = None,
        max_workers: int = 2,
        num_cores: int = 2,
        clear_geompre: bool = False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        ras_object: Optional['RasPrj'] = None,
        dest_folder: Union[str, Path, None] = None,
        overwrite_dest: bool = False,
        skip_existing: bool = False,
        verify: bool = False
    ) -> 'ComputeParallelResult':
        """
        Execute multiple HEC-RAS plans in parallel using multiple worker instances.

        This method creates separate worker folders for each parallel process, runs plans
        in those folders, and then consolidates results to a final destination folder.
        It's ideal for running independent plans simultaneously to make better use of system resources.

        Args:
            plan_number (Union[str, List[str], None]): Plan number(s) to compute.
                If None, all plans in the project are computed.
                If string, only that plan will be computed.
                If list, all specified plans will be computed.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            max_workers (int): Maximum number of parallel workers (separate HEC-RAS instances).
                Each worker gets a separate folder with a copy of the project.
                Optimal value depends on CPU cores and memory available.
                A good starting point is: max_workers = floor(physical_cores / num_cores).
            num_cores (int): Number of cores to use per plan computation.
                Controls computational resources allocated to each individual HEC-RAS instance.
                For parallel execution, 2-4 cores per worker often provides the best balance.
            clear_geompre (bool): Whether to clear geometry preprocessor files (.c## files) before computation.
                Set to True when geometry has been modified to force recomputation.
            force_geompre (bool): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
            force_rerun (bool): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
            ras_object (Optional[RasPrj]): RAS project object. If None, uses global 'ras' instance.
                Useful when working with multiple projects simultaneously.
            dest_folder (Union[str, Path, None]): Destination folder for computed results.
                If None, results are consolidated back to the original project folder.
                If string, creates folder in the project's parent directory.
                If Path, uses the exact path provided.
            overwrite_dest (bool): Whether to overwrite existing destination folder.
                Set to True to replace an existing destination folder with the same name.
            skip_existing (bool): If True, skip computation for plans that already have HDF results
                with 'Complete Process' in compute messages. Defaults to False.
                Skipped plans are marked as successful (True) in results. Checked on source folder.
            verify (bool): If True, verify each plan completed successfully by checking
                for 'Complete Process' in compute messages. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                Existing code like ``for plan, ok in results.items():`` still works.
                When skip_existing=True, skipped plans return True.
                When verify=True, plans failing verification return False.

        Raises:
            ValueError: If the destination folder already exists, is not empty, and overwrite_dest is False.
            FileNotFoundError: If project files cannot be found.
            PermissionError: If there are issues accessing or writing to folders.
            RuntimeError: If worker initialization fails.

        Examples:
            # Run all plans in parallel with default settings
            RasCmdr.compute_parallel()

            # Run all plans with 4 workers, 2 cores per worker
            RasCmdr.compute_parallel(max_workers=4, num_cores=2)

            # Run specific plans in parallel
            RasCmdr.compute_parallel(plan_number=["01", "03"], max_workers=2)

            # Resume interrupted parallel run - skip already completed plans
            RasCmdr.compute_parallel(skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_parallel(verify=True)

            # Run all plans with dynamic worker allocation based on system resources
            import psutil
            physical_cores = psutil.cpu_count(logical=False)
            cores_per_worker = 2
            max_workers = max(1, physical_cores // cores_per_worker)
            RasCmdr.compute_parallel(max_workers=max_workers, num_cores=cores_per_worker)

            # Run all plans in a specific destination folder
            RasCmdr.compute_parallel(dest_folder="parallel_results", overwrite_dest=True)

        Notes:
            - Worker Assignment: Plans are assigned to workers in a round-robin fashion.
              For example, with 3 workers and 5 plans, assignment would be:
              Worker 1: Plans 1 & 4, Worker 2: Plans 2 & 5, Worker 3: Plan 3.

            - Resource Management: Each HEC-RAS instance (worker) typically requires:
              * 2-4 GB of RAM
              * 2-4 cores for optimal performance

            - When to use parallel vs. sequential:
              * Parallel: For independent plans, faster overall completion
              * Sequential: For dependent plans, consistent resource usage, easier debugging

            - The function creates worker folders during execution and consolidates results
              to the destination folder upon completion.

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the SOURCE folder before creating workers. Plans with existing
              results are not assigned to workers at all.

            - verify is passed through to compute_plan() for each worker execution.
        """
        execution_results: Dict[str, bool] = {}
        filtered_plan_numbers: List[str] = []

        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()

            project_folder = Path(ras_obj.project_folder)

            if dest_folder is not None:
                dest_folder_path = Path(dest_folder)
                if dest_folder_path.exists():
                    if overwrite_dest:
                        if not RasUtils.remove_with_retry(dest_folder_path, ras_object=None):
                            raise PermissionError(f"Unable to remove destination folder: {dest_folder_path}")
                        logger.info("Destination folder exists; overwriting as requested: %s", dest_folder_path.name)
                        logger.debug(f"Overwriting destination folder: {dest_folder_path}")
                    elif any(dest_folder_path.iterdir()):
                        error_msg = f"Destination folder '{dest_folder_path}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                dest_folder_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                logger.info("Copied project folder to destination: %s", dest_folder_path.name)
                logger.debug(f"Copied project folder to destination path: {dest_folder_path}")
                project_folder = dest_folder_path

            # Store filtered plan numbers separately to ensure only these are executed
            filtered_plan_entries = RasCmdr._filter_plan_entries(
                ras_obj.plan_df,
                plan_number
            )
            filtered_plan_numbers = list(filtered_plan_entries["plan_number"])

            # Filter out plans with existing results if skip_existing is True
            if skip_existing:
                plans_to_skip = []
                plans_to_compute = []
                for plan_num in filtered_plan_numbers:
                    hdf_path = RasCmdr._get_hdf_path(plan_num, ras_obj)
                    if RasCmdr._verify_completion(hdf_path, check_errors=False):
                        plans_to_skip.append(plan_num)
                        execution_results[plan_num] = True  # Mark as successful (results exist)
                    else:
                        plans_to_compute.append(plan_num)
                if plans_to_skip:
                    logger.info(f"Skipping {len(plans_to_skip)} plans with existing results: {plans_to_skip}")
                filtered_plan_numbers = plans_to_compute

            num_plans = len(filtered_plan_numbers)

            # If all plans were skipped, return early
            if num_plans == 0:
                if execution_results:
                    logger.info("All plans skipped (existing results found). No computation needed.")
                else:
                    logger.warning("No plans matched the requested plan filter. No computation needed.")
                # Try to populate results_df from existing results
                _results_df = pd.DataFrame()
                try:
                    if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None:
                        mask = ras_obj.results_df['plan_number'].isin(list(execution_results.keys()))
                        if mask.any():
                            _results_df = ras_obj.results_df[mask].copy()
                except Exception:
                    pass
                return ComputeParallelResult(execution_results=execution_results, results_df=_results_df)

            max_workers = min(max_workers, num_plans)
            logger.info(f"Adjusted max_workers to {max_workers} based on the number of plans to compute: {num_plans}")

            worker_ras_objects = {}
            worker_plan_numbers: Dict[int, List[str]] = defaultdict(list)
            for worker_id in range(1, max_workers + 1):
                worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
                if worker_folder.exists():
                    if not RasUtils.remove_with_retry(worker_folder, ras_object=None):
                        raise PermissionError(f"Unable to remove existing worker folder: {worker_folder}")
                    logger.debug(f"Removed existing worker folder: {worker_folder}")
                shutil.copytree(project_folder, worker_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.debug(f"Created worker folder {worker_id}: {worker_folder}")

                try:
                    worker_ras = RasPrj()
                    worker_ras_object = init_ras_project(
                        ras_project_folder=worker_folder,
                        ras_version=ras_obj.ras_exe_path,
                        ras_object=worker_ras,
                        hide_intro=True,
                    )
                    worker_ras_objects[worker_id] = worker_ras_object
                except Exception as e:
                    logger.critical(f"Failed to initialize RAS project for worker {worker_id}: {str(e)}")
                    worker_ras_objects[worker_id] = None
            logger.info(f"Prepared {max_workers} worker folder(s) for parallel execution")

            # Explicitly use the filtered plan numbers for assignments
            worker_cycle = cycle(range(1, max_workers + 1))
            plan_assignments = [(next(worker_cycle), plan_num) for plan_num in filtered_plan_numbers]
            for worker_id, plan_num in plan_assignments:
                worker_plan_numbers[worker_id].append(plan_num)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit futures and track which plan each future represents
                future_to_plan = {}
                for worker_id, plan_num in plan_assignments:
                    future = executor.submit(
                        RasCmdr.compute_plan,
                        plan_num,
                        ras_object=worker_ras_objects[worker_id],
                        clear_geompre=clear_geompre,
                        force_geompre=force_geompre,
                        force_rerun=True,  # Always force execution in workers - plans passed skip_existing filter
                        num_cores=num_cores,
                        verify=verify
                    )
                    future_to_plan[future] = (worker_id, plan_num)

                # Process futures as they complete (not in submission order)
                for future in as_completed(future_to_plan.keys()):
                    worker_id, plan_num = future_to_plan[future]
                    try:
                        compute_result = future.result()
                        # Extract bool from ComputeResult for execution_results dict
                        execution_results[plan_num] = bool(compute_result)
                        if compute_result:
                            logger.debug(f"Plan {plan_num} executed in worker {worker_id}: Successful")
                        else:
                            logger.warning(f"Plan {plan_num} executed in worker {worker_id}: Failed")
                    except Exception as e:
                        execution_results[plan_num] = False
                        logger.error(f"Plan {plan_num} failed in worker {worker_id}: {str(e)}")

            # Consolidate results: use dest_folder if provided, otherwise back to original folder
            # This eliminates the [Computed] folder anti-pattern - results go directly to original project
            if dest_folder is not None:
                final_dest_folder = dest_folder_path
                final_dest_folder.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "Consolidating worker artifacts to destination folder: %s",
                    final_dest_folder.name,
                )
                logger.debug(f"Consolidating worker artifacts to destination path: {final_dest_folder}")
            else:
                final_dest_folder = project_folder
                logger.info(
                    "Consolidating worker artifacts back to original project folder: %s",
                    final_dest_folder.name,
                )
                logger.debug(f"Consolidating worker artifacts back to original project path: {final_dest_folder}")

            consolidated_artifact_count = 0
            for worker_id, worker_ras in worker_ras_objects.items():
                if worker_ras is None:
                    continue
                worker_folder = Path(worker_ras.project_folder)
                assigned_plan_numbers = worker_plan_numbers.get(worker_id, [])
                try:
                    # First, close any open resources in the worker RAS object
                    worker_ras.close() if hasattr(worker_ras, 'close') else None
                    
                    # Add a small delay to ensure file handles are released
                    time.sleep(1)
                    
                    # Move files with retry mechanism
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            for plan_num in assigned_plan_numbers:
                                geometry_number = RasCmdr._get_plan_geometry_number(
                                    filtered_plan_entries,
                                    plan_num
                                )
                                plan_artifacts = RasCmdr._get_worker_plan_artifacts(
                                    worker_folder=worker_folder,
                                    project_name=worker_ras.project_name,
                                    plan_number=plan_num,
                                    geometry_number=geometry_number
                                )
                                for artifact_path in plan_artifacts:
                                    dest_path = final_dest_folder / artifact_path.name
                                    if RasCmdr._copy_worker_artifact(
                                        artifact_path,
                                        dest_path
                                    ):
                                        consolidated_artifact_count += 1
                             
                            # Add another small delay before removal
                            time.sleep(1)
                            
                            # Try to remove the worker folder
                            if worker_folder.exists():
                                if not RasUtils.remove_with_retry(worker_folder, ras_object=None):
                                    raise PermissionError(f"Unable to remove worker folder: {worker_folder}")
                            break  # If successful, break the retry loop
                            
                        except PermissionError as pe:
                            if retry == max_retries - 1:  # If this was the last retry
                                logger.error(f"Failed to move/remove files after {max_retries} attempts: {str(pe)}")
                                raise
                            time.sleep(2 ** retry)  # Exponential backoff
                            continue
                            
                except Exception as e:
                    logger.error(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

            logger.info(
                "Consolidated %s worker artifact(s) to %s",
                consolidated_artifact_count,
                final_dest_folder.name
            )
            logger.debug(f"Consolidated worker artifacts to destination path: {final_dest_folder}")

            # When dest_folder is used, re-initialize ras_obj from dest_folder
            # This ensures results_df reflects results in the destination folder
            if dest_folder is not None:
                try:
                    ras_obj.initialize(final_dest_folder, ras_obj.ras_exe_path)
                    logger.info("Re-initialized ras_object from destination folder: %s", final_dest_folder.name)
                    logger.debug(f"Re-initialized ras_object from destination path: {final_dest_folder}")
                except Exception as e:
                    logger.critical(f"Failed to re-initialize ras_object from destination folder: {str(e)}")

            RasCmdr._log_execution_results(execution_results)

            ras_obj = ras_object or ras
            try:
                ras_obj.plan_df = ras_obj.get_plan_entries()
                ras_obj.geom_df = ras_obj.get_geom_entries()
                ras_obj.flow_df = ras_obj.get_flow_entries()
                ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
                ras_obj.update_results_df(plan_numbers=list(execution_results.keys()))
            except Exception as e_refresh:
                logger.warning(
                    "Error refreshing DataFrames after compute_parallel: %s. "
                    "Using cached plan metadata and expected result paths.",
                    e_refresh,
                )
                try:
                    RasCmdr._update_results_from_cached_plan_entries(
                        ras_obj,
                        list(execution_results.keys()),
                        project_folder=final_dest_folder,
                        project_name=ras_obj.project_name,
                        plan_entries=filtered_plan_entries,
                    )
                except Exception as e_results:
                    logger.error(
                        "Could not summarize parallel results after refresh "
                        "failure: %s",
                        e_results,
                    )

            # Extract results_df rows for executed plans
            _results_df = pd.DataFrame()
            try:
                plan_nums = list(execution_results.keys())
                if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None and len(ras_obj.results_df) > 0:
                    mask = ras_obj.results_df['plan_number'].isin(plan_nums)
                    if mask.any():
                        _results_df = ras_obj.results_df[mask].copy()
            except Exception as e:
                logger.debug(f"Could not extract results_df for parallel plans: {e}")

            return ComputeParallelResult(execution_results=execution_results, results_df=_results_df)

        except Exception as e:
            logger.critical(f"Error in compute_parallel: {str(e)}")
            for plan_num in filtered_plan_numbers:
                execution_results.setdefault(plan_num, False)
            return ComputeParallelResult(execution_results=execution_results)

    @staticmethod
    @log_call
    def compute_test_mode(
        plan_number: Union[str, Number, List[Union[str, Number]], None] = None,
        dest_folder_suffix="[Test]",
        clear_geompre=False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        num_cores=None,
        ras_object=None,
        overwrite_dest=False,
        skip_existing: bool = False,
        verify: bool = False
    ) -> 'ComputeParallelResult':
        """
        Execute HEC-RAS plans sequentially in a separate test folder.

        This function creates a separate test folder, copies the project there, and executes
        the specified plans in sequential order. It's useful for batch processing plans that
        need to be run in a specific order or when you want to ensure consistent resource usage.

        Args:
            plan_number (Union[str, Number, List[Union[str, Number]], None], optional): Plan number or list of plan numbers to execute (e.g., "01", 1, 1.0, or ["01", 2]).
                If None, all plans will be executed. Default is None.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder_suffix (str, optional): Suffix to append to the test folder name.
                Defaults to "[Test]".
                The test folder is always created in the project folder's parent directory.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files (.c## files).
                Defaults to False.
                Set to True when geometry has been modified to force recomputation.
            force_geompre (bool, optional): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
            force_rerun (bool, optional): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
            num_cores (int, optional): Number of cores to use for each plan.
                If None, the current setting in the plan file is not changed. Default is None.
                For sequential execution, 4-8 cores often provides good performance.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists.
                Defaults to False.
                Set to True to replace an existing test folder with the same name.
            skip_existing (bool, optional): If True, skip computation for plans that already have HDF results
                with 'Complete Process' in compute messages. Defaults to False.
                Skipped plans are marked as successful (True) in results. Check happens in test folder.
            verify (bool, optional): If True, verify each plan completed successfully by checking
                for 'Complete Process' in compute messages. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                Existing code like ``for plan, ok in results.items():`` still works.
                When skip_existing=True, skipped plans return True.
                When verify=True, plans failing verification return False.

        Raises:
            ValueError: If the destination folder already exists, is not empty, and overwrite_dest is False.
            FileNotFoundError: If project files cannot be found.
            PermissionError: If there are issues accessing or writing to folders.

        Examples:
            # Run all plans sequentially
            RasCmdr.compute_test_mode()

            # Run a specific plan
            RasCmdr.compute_test_mode(plan_number="01")

            # Run multiple specific plans
            RasCmdr.compute_test_mode(plan_number=["01", "03", "05"])

            # Run plans with a custom folder suffix
            RasCmdr.compute_test_mode(dest_folder_suffix="[SequentialRun]")

            # Run plans with a specific number of cores
            RasCmdr.compute_test_mode(num_cores=4)

            # Resume interrupted test run - skip completed plans
            RasCmdr.compute_test_mode(skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_test_mode(verify=True)

            # Run specific plans with multiple options
            RasCmdr.compute_test_mode(
                plan_number=["01", "02"],
                dest_folder_suffix="[SpecificSequential]",
                clear_geompre=True,
                num_cores=6,
                overwrite_dest=True,
                verify=True
            )

        Notes:
            - This function was created to replicate the original HEC-RAS command line -test flag,
              which does not work in recent versions of HEC-RAS.

            - Key differences from other compute functions:
              * compute_plan: Runs a single plan, with option for destination folder
              * compute_parallel: Runs multiple plans simultaneously in worker folders
              * compute_test_mode: Runs multiple plans sequentially in a single test folder

            - Use cases:
              * Running plans in a specific order
              * Ensuring consistent resource usage
              * Easier debugging (one plan at a time)
              * Isolated test environment

            - Performance considerations:
              * Sequential execution is generally slower overall than parallel execution
              * Each plan gets consistent resource usage
              * Execution time scales linearly with the number of plans

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the TEST folder after copying. This allows resuming interrupted test runs.

            - verify is passed through to compute_plan() for each plan execution.
        """
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            
            logger.info("Starting the compute_test_mode...")
               
            project_folder = Path(ras_obj.project_folder)

            if not project_folder.exists():
                logger.error(f"Project folder '{project_folder}' does not exist.")
                return ComputeParallelResult()

            compute_folder = project_folder.parent / f"{project_folder.name} {dest_folder_suffix}"
            logger.info("Creating test folder: %s", compute_folder.name)
            logger.debug(f"Creating test folder path: {compute_folder}")

            if compute_folder.exists():
                if overwrite_dest:
                    shutil.rmtree(compute_folder)
                    logger.info("Compute folder exists; overwriting as requested: %s", compute_folder.name)
                    logger.debug(f"Overwriting compute folder: {compute_folder}")
                elif any(compute_folder.iterdir()):
                    error_msg = (
                        f"Compute folder '{compute_folder}' exists and is not empty. "
                        "Use overwrite_dest=True to overwrite."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

            try:
                shutil.copytree(project_folder, compute_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.info("Copied project folder to compute folder: %s", compute_folder.name)
                logger.debug(f"Copied project folder to compute folder path: {compute_folder}")
            except Exception as e:
                logger.critical(f"Error occurred while copying project folder: {str(e)}")
                return ComputeParallelResult()

            try:
                compute_ras = RasPrj()
                compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
                logger.info("Initialized RAS project in compute folder: %s", compute_folder.name)
                logger.debug(f"Initialized RAS project file in compute folder: {compute_prj_path}")
            except Exception as e:
                logger.critical(f"Error initializing RAS project in compute folder: {str(e)}")
                return ComputeParallelResult()

            if not compute_prj_path:
                logger.error("Project file not found.")
                return ComputeParallelResult()

            logger.debug("Getting plan entries...")
            try:
                ras_compute_plan_entries = compute_ras.plan_df
                logger.debug("Retrieved plan entries successfully.")
            except Exception as e:
                logger.critical(f"Error retrieving plan entries: {str(e)}")
                return ComputeParallelResult()

            ras_compute_plan_entries = RasCmdr._filter_plan_entries(
                ras_compute_plan_entries,
                plan_number
            )

            execution_results = {}
            logger.info("Running selected plans sequentially...")
            for _, plan in ras_compute_plan_entries.iterrows():
                current_plan_number = plan["plan_number"]
                start_time = time.time()
                try:
                    compute_result = RasCmdr.compute_plan(
                        current_plan_number,
                        ras_object=compute_ras,
                        clear_geompre=clear_geompre,
                        force_geompre=force_geompre,
                        force_rerun=True,  # Always force execution in test folder - bypass broken smart skip from copytree timestamp preservation
                        num_cores=num_cores,
                        skip_existing=skip_existing,  # Still respected (skip_existing check happens before force_rerun check)
                        verify=verify
                    )
                    # Extract bool from ComputeResult for execution_results dict
                    execution_results[current_plan_number] = bool(compute_result)
                    if compute_result:
                        logger.debug(f"Successfully computed plan {current_plan_number}")
                    else:
                        logger.error(f"Failed to compute plan {current_plan_number}")
                except Exception as e:
                    execution_results[current_plan_number] = False
                    logger.error(f"Error computing plan {current_plan_number}: {str(e)}")
                finally:
                    end_time = time.time()
                    run_time = end_time - start_time
                    logger.debug(f"Total run time for plan {current_plan_number}: {run_time:.2f} seconds")

            logger.info("All selected plans have been executed.")

            # Consolidate HDF results back to original project folder
            # This eliminates the [Test] folder anti-pattern - results go to original project
            logger.info("Consolidating HDF results from test folder back to original project folder")
            logger.debug(f"Consolidating HDF results from {compute_folder} back to {project_folder}")
            hdf_files_copied = 0
            for hdf_file in compute_folder.glob("*.hdf"):
                dest_path = project_folder / hdf_file.name
                try:
                    if dest_path.exists():
                        dest_path.unlink()
                    shutil.copy2(hdf_file, dest_path)
                    hdf_files_copied += 1
                    logger.debug(f"Copied {hdf_file.name} to original project folder")
                except Exception as e:
                    logger.error(f"Failed to copy {hdf_file.name}: {str(e)}")

            logger.info(f"Consolidated {hdf_files_copied} HDF file(s) to original project folder")

            # Clean up test folder
            try:
                shutil.rmtree(compute_folder)
                logger.info("Removed test folder: %s", compute_folder.name)
                logger.debug(f"Removed test folder path: {compute_folder}")
            except Exception as e:
                logger.warning(f"Failed to remove test folder {compute_folder}: {str(e)}")

            logger.info("compute_test_mode completed.")

            RasCmdr._log_execution_results(execution_results)

            # Refresh DataFrames from original folder - HDF files are now there
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            ras_obj.update_results_df(plan_numbers=list(execution_results.keys()))

            # Extract results_df rows for executed plans
            _results_df = pd.DataFrame()
            try:
                plan_nums = list(execution_results.keys())
                if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None and len(ras_obj.results_df) > 0:
                    mask = ras_obj.results_df['plan_number'].isin(plan_nums)
                    if mask.any():
                        _results_df = ras_obj.results_df[mask].copy()
            except Exception as e:
                logger.debug(f"Could not extract results_df for test mode plans: {e}")

            return ComputeParallelResult(execution_results=execution_results, results_df=_results_df)

        except Exception as e:
            logger.critical(f"Error in compute_test_mode: {str(e)}")
            return ComputeParallelResult()

    @staticmethod
    @log_call
    def compute_plan_linux(
        plan_number: Union[str, Number],
        ras_exe_dir: Union[str, Path],
        ras_object=None,
        timeout_sec: int = 14400,
        dos2unix: bool = True,
        num_cores: int = None,
        retry: bool = True,
        retry_delay_sec: int = 30,
    ) -> 'ComputeResult':
        """
        Execute a HEC-RAS plan using the native Linux RasUnsteady binary.

        Attribution: Execution pattern derived from ras-agent
        (https://github.com/gheistand/ras-agent) by Glenn Heistand / CHAMP —
        Illinois State Water Survey. See runner.py:run_job() for the original
        Linux RasUnsteady invocation pattern (subprocess, LD_LIBRARY_PATH,
        .tmp.hdf preparation, retry logic).

        This is Phase 2 of a two-phase Linux execution workflow:

        **Phase 1 (Windows)**: Preprocess the plan on Windows to generate
        .tmp.hdf, .b##, and .x## files. Use ``RasPreprocess.preprocess_plan()``
        to automate this step, or manually run HEC-RAS on Windows and kill
        after "Starting Unsteady Flow Computations" appears in the .bco log.

        **Phase 2 (Linux — this method)**: Execute the preprocessed plan
        using the native RasUnsteady binary.

        Prerequisites (must exist in project folder before calling):
            - {project}.p{plan_num}.tmp.hdf — preprocessed plan HDF
            - {project}.b{plan_num} — boundary conditions file
            - {project}.x{geom_num} — cross-section preprocessor file
            - {project}.c{geom_num} — computed-geometry file (5.0.7 layout only)

        Supported native Linux install layouts (auto-detected from ``ras_exe_dir``):

        * **canonical (6.3.1-7.0)** — ``RasUnsteady`` at the install root with a
          sibling ``libs/`` tree (``libs/``, ``libs/mkl/``, ``libs/rhel_8/``).
          Invoked as ``RasUnsteady {proj}.p{plan}.tmp.hdf x{geom}``.
        * **bin_ras (5.0.7)** — ``bin_ras/rasUnsteady64`` with libraries colocated
          in ``bin_ras/`` (no ``libs/`` tree). Invoked as
          ``rasUnsteady64 {proj}.c{geom} b{plan}`` and additionally requires the
          ``.c{geom}`` computed-geometry file. (CLB-886)

        Detection and binary resolution mirror
        :meth:`RasUtils._scan_native_linux_ras` (root ``RasUnsteady`` →
        ``bin_ras/{rasUnsteady64,RasUnsteady,rasUnsteady}``).

        The Linux RasUnsteady binary uses Fortran I/O conventions that require
        files to be accessible with a base name of "io" (e.g., io.b, io.X).
        This method creates temporary symlinks to satisfy this requirement.

        Args:
            plan_number (Union[str, Number]): Plan number to execute (e.g., "01").
            ras_exe_dir (Union[str, Path]): HEC-RAS Linux install directory. For the
                canonical layout this holds ``RasUnsteady`` + ``libs/``; for the
                5.0.7 layout it holds ``bin_ras/rasUnsteady64`` + its libraries.
            ras_object: Optional RAS project object. If None, uses global ras.
            timeout_sec (int): Maximum execution time in seconds (default 14400 = 4 hours).
            dos2unix (bool): Convert CRLF→LF in text files before execution (default True).
            num_cores (int, optional): Number of cores. If specified, updates plan file.
            retry (bool): Retry once on failure after retry_delay_sec (default True).
            retry_delay_sec (int): Seconds to wait before retry (default 30).

        Returns:
            ComputeResult: Result object with success bool and results_df_row.

        Raises:
            FileNotFoundError: If RasUnsteady binary, .tmp.hdf, .b, or .x files not found.

        Example:
            >>> # Phase 1: Preprocess on Windows (generates .tmp.hdf, .b, .x)
            >>> # Phase 2: Execute on Linux
            >>> from ras_commander import init_ras_project, RasCmdr
            >>> init_ras_project("/home/user/model")
            >>> result = RasCmdr.compute_plan_linux(
            ...     "01", ras_exe_dir="/opt/hecras/6.7-beta5"
            ... )
        """
        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()

        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        ras_exe_dir_raw = str(ras_exe_dir)
        ras_exe_dir_posix = ras_exe_dir_raw.replace("\\", "/").rstrip("/")
        run_via_wsl = os.name == "nt" and ras_exe_dir_posix.startswith("/mnt/")

        if run_via_wsl:
            ras_exe = f"{ras_exe_dir_posix}/RasUnsteady"
            probe = subprocess.run(
                ["wsl", "test", "-x", ras_exe],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if probe.returncode != 0:
                raise FileNotFoundError(
                    f"RasUnsteady binary not found or not executable in WSL at {ras_exe}. "
                    "Ensure HEC-RAS Linux binaries are installed and WSL can access them."
                )
        else:
            ras_exe_dir = Path(ras_exe_dir)
            layout = RasCmdr._resolve_linux_layout(ras_exe_dir)
            ras_exe = layout["ras_exe"]
            if not ras_exe.exists():
                raise FileNotFoundError(
                    f"Linux RasUnsteady binary not found under {ras_exe_dir} "
                    f"(looked for {ras_exe}). Ensure HEC-RAS Linux binaries are installed."
                )

        project_dir = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Determine geometry number from plan file
        plan_path = RasPlan.get_plan_path(plan_num_str, ras_obj)
        # Resolve the geometry number from the plan file. Fail fast rather than
        # silently defaulting to "01" — running an unknown/wrong geometry would
        # produce results for the wrong model (CLB-884).
        geom_num = None
        try:
            plan_text = Path(plan_path).read_text(errors='replace')
            for line in plan_text.splitlines():
                if line.startswith("Geom File="):
                    geom_ref = line.split("=", 1)[1].strip()
                    # Extract number: "g04" → "04"
                    import re
                    m = re.search(r'(\d+)', geom_ref)
                    if m:
                        geom_num = m.group(1)
                    break
        except Exception as e:
            raise RuntimeError(
                f"Could not read the geometry reference from plan file {plan_path}: {e}. "
                f"Refusing to run Linux compute without a resolved geometry."
            )
        if geom_num is None:
            raise RuntimeError(
                f"Could not resolve a geometry number from plan file {plan_path} "
                f"(no parseable 'Geom File=' entry). Refusing to fall back to a default "
                f"geometry for Linux compute — that could silently run the wrong geometry."
            )

        # Verify prerequisite files exist
        tmp_hdf = project_dir / f"{project_name}.p{plan_num_str}.tmp.hdf"
        b_file = project_dir / f"{project_name}.b{plan_num_str}"
        x_file = project_dir / f"{project_name}.x{geom_num}"
        # 5.0.7 (bin_ras/rasUnsteady64) additionally consumes the computed-geometry
        # ".c{geom}" binary file and is invoked as `rasUnsteady64 {proj}.c{geom} b{plan}`
        # rather than the 6.x/7.0 `RasUnsteady {tmp.hdf} x{geom}` convention (CLB-886).
        c_file = project_dir / f"{project_name}.c{geom_num}"

        missing = []
        if not tmp_hdf.exists():
            missing.append(f".p{plan_num_str}.tmp.hdf")
        if not b_file.exists():
            missing.append(f".b{plan_num_str}")
        if not x_file.exists():
            missing.append(f".x{geom_num}")
        if layout["needs_c_file"] and not c_file.exists():
            missing.append(f".c{geom_num}")

        if missing:
            raise FileNotFoundError(
                f"Missing prerequisite files for Linux execution ({layout['label']} layout): "
                f"{', '.join(missing)}. "
                f"Run RasPreprocess.preprocess_plan() on Windows first (Phase 1). "
                f"See examples/510_linux_execution.ipynb for the complete workflow."
            )

        # Set num_cores if specified
        if num_cores is not None:
            try:
                RasPlan.set_num_cores(plan_path, num_cores=num_cores, ras_object=ras_obj)
                logger.info(f"Set number of cores to {num_cores} for plan: {plan_num_str}")
            except Exception as e:
                logger.error(f"Error setting number of cores: {e}")

        if run_via_wsl:
            return RasCmdr._compute_plan_linux_via_wsl(
                ras_exe=str(ras_exe),
                ras_exe_dir=ras_exe_dir_posix,
                plan_number=plan_num_str,
                geom_num=geom_num,
                project_dir=project_dir,
                project_name=project_name,
                tmp_hdf=tmp_hdf,
                timeout_sec=timeout_sec,
                dos2unix=dos2unix,
                retry=retry,
                retry_delay_sec=retry_delay_sec,
                ras_obj=ras_obj,
            )

        # Build LD_LIBRARY_PATH — auto-detect library locations per layout:
        #   5.0.7:     libs live alongside the binary in bin_ras/
        #   6.3.1-6.5: libs/, libs/mkl/
        #   6.6-6.7:   libs/, libs/mkl/, libs/rhel_8/
        ld_path = RasCmdr._build_linux_ld_path(ras_exe_dir, layout)
        logger.info("Configured Linux library path for RasUnsteady")
        logger.debug(f"LD_LIBRARY_PATH: {ld_path}")

        # dos2unix text files
        if dos2unix:
            try:
                count = RasUtils.dos2unix(project_dir)
                logger.debug(f"dos2unix converted {count} files")
            except Exception as e:
                logger.warning(f"dos2unix failed: {e}")

        # Create Fortran io.* symlinks
        # RasUnsteady uses Fortran I/O that expects files named io.b, io.X, io.g, etc.
        io_links = []

        def _create_io_link(source: Path, io_name: str):
            """Create io.* symlink and track for cleanup."""
            link_path = project_dir / io_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(source.name)
            io_links.append(link_path)

        try:
            _create_io_link(b_file, "io.b")
            _create_io_link(x_file, "io.X")
            _create_io_link(x_file, "io.x")
            # Symlink all project files to io.* equivalents
            for f in project_dir.iterdir():
                if f.name.startswith(project_name + ".") and not f.name.startswith("io."):
                    suffix = f.name[len(project_name) + 1:]  # everything after "ProjectName."
                    io_name = f"io.{suffix}"
                    io_path = project_dir / io_name
                    if not io_path.exists() and not io_path.is_symlink():
                        _create_io_link(f, io_name)
            logger.debug(f"Created {len(io_links)} io.* symlinks")
        except OSError as e:
            logger.warning(f"Could not create io.* symlinks (may not be needed): {e}")

        max_attempts = 2 if retry else 1
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Linux execution attempt {attempt}/{max_attempts} for plan {plan_num_str}")

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = ld_path

            log_path = project_dir / f"compute_linux_{plan_num_str}.log"
            success = False
            err_msg = ""

            try:
                start_time = time.time()
                # Argument convention differs by layout (CLB-886):
                #   5.0.7:    rasUnsteady64 {proj}.c{geom} b{plan}   (cwd-relative basenames)
                #   6.x/7.0:  RasUnsteady   {proj}.p{plan}.tmp.hdf x{geom}
                if layout["needs_c_file"]:
                    ras_args = [c_file.name, f"b{plan_num_str}"]
                else:
                    ras_args = [str(tmp_hdf), f"x{geom_num}"]
                with open(log_path, "w") as log_fh:
                    proc = subprocess.Popen(
                        [str(ras_exe), *ras_args],
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        env=env,
                        cwd=str(project_dir),
                    )
                try:
                    rc = proc.wait(timeout=timeout_sec)
                    end_time = time.time()
                    run_time = end_time - start_time
                    if rc == 0:
                        # RasUnsteady can exit 0 even when the solve failed in-band
                        # (e.g. "Unsteady flow encountered an error"). Validate the
                        # solver log and result HDF before declaring success so a bad
                        # result HDF is never promoted .tmp.hdf -> .hdf (CLB-882).
                        ok, reason = RasCmdr._validate_linux_solve(
                            log_path, tmp_hdf, plan_num_str
                        )
                        if ok:
                            success = True
                            logger.info(
                                f"RasUnsteady completed for plan {plan_num_str} "
                                f"in {run_time:.1f}s (exit code 0, validated)"
                            )
                        else:
                            success = False
                            err_msg = (
                                f"RasUnsteady exited 0 but the solve did not produce a "
                                f"valid result: {reason}"
                            )
                            logger.error(f"Plan {plan_num_str}: {err_msg}")
                    else:
                        try:
                            tail = log_path.read_text(errors='replace')[-500:]
                        except OSError:
                            tail = "(log unreadable)"
                        err_msg = f"RasUnsteady exited with code {rc}. Log tail: {tail}"
                        logger.error(f"Plan {plan_num_str}: {err_msg}")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    err_msg = f"Timeout after {timeout_sec}s"
                    logger.error(f"Plan {plan_num_str}: {err_msg}")
            except FileNotFoundError:
                raise RuntimeError(
                    f"RasUnsteady binary not found at {ras_exe}."
                )

            if success:
                # Move results from .tmp.hdf → .hdf
                if tmp_hdf.exists():
                    plan_hdf = RasCmdr._get_hdf_path(plan_num_str, ras_obj)
                    shutil.move(str(tmp_hdf), str(plan_hdf))
                    logger.debug(f"Renamed {tmp_hdf.name} → {plan_hdf.name}")

                # Clean up io.* symlinks
                for link in io_links:
                    try:
                        if link.is_symlink():
                            link.unlink()
                    except OSError:
                        pass

                # Refresh DataFrames
                try:
                    ras_obj.plan_df = ras_obj.get_plan_entries()
                    ras_obj.update_results_df(plan_numbers=[plan_num_str])
                    mask = ras_obj.results_df['plan_number'] == plan_num_str
                    results_row = ras_obj.results_df[mask].iloc[0].copy() if mask.any() else None
                except Exception as e:
                    logger.debug(f"Could not extract results_df_row: {e}")
                    results_row = None

                return ComputeResult(success=True, results_df_row=results_row)
            else:
                if attempt < max_attempts:
                    logger.info(f"Retrying in {retry_delay_sec}s...")
                    time.sleep(retry_delay_sec)
                    continue

                # Clean up io.* symlinks on final failure
                for link in io_links:
                    try:
                        if link.is_symlink():
                            link.unlink()
                    except OSError:
                        pass

                return ComputeResult(success=False, results_df_row=None)

    @staticmethod
    def _resolve_linux_layout(ras_exe_dir: Path) -> dict:
        """Detect the HEC-RAS Linux install layout and return its execution adapter (CLB-886).

        Two native layouts are supported:

        * **canonical (6.3.1-7.0)** — ``RasUnsteady`` at the install root, with a
          sibling ``libs/`` (plus ``libs/mkl/``, ``libs/rhel_8/``). Invoked as
          ``RasUnsteady {proj}.p{plan}.tmp.hdf x{geom}``.
        * **bin_ras (5.0.7)** — ``bin_ras/rasUnsteady64`` with the shared libraries
          alongside the binary in ``bin_ras/`` (no ``libs/`` tree). Invoked as
          ``rasUnsteady64 {proj}.c{geom} b{plan}`` and additionally requires the
          computed-geometry ``.c{geom}`` file.

        Resolution prefers a root ``RasUnsteady`` (canonical) and otherwise falls
        back to ``bin_ras/rasUnsteady64`` / ``bin_ras/RasUnsteady`` — mirroring the
        binary names :meth:`RasUtils._scan_native_linux_ras` recognizes.

        Returns:
            dict: ``ras_exe`` (Path), ``needs_c_file`` (bool), ``lib_dirs``
            (list[Path] explicit lib dirs, or ``[]`` to auto-detect ``libs/``),
            and ``label`` (str).
        """
        ras_exe_dir = Path(ras_exe_dir)
        # Canonical layout: RasUnsteady at the install root.
        root_exe = ras_exe_dir / "RasUnsteady"
        if root_exe.exists():
            return {
                "ras_exe": root_exe,
                "needs_c_file": False,
                "lib_dirs": [],          # auto-detect libs/ tree
                "label": "canonical",
            }
        # bin_ras layout (5.0.7): rasUnsteady64 (or RasUnsteady) under bin_ras/,
        # libraries colocated in the same bin_ras/ directory.
        bin_ras = ras_exe_dir / "bin_ras"
        for binname in ("rasUnsteady64", "RasUnsteady", "rasUnsteady"):
            cand = bin_ras / binname
            if cand.exists():
                return {
                    "ras_exe": cand,
                    "needs_c_file": True,
                    "lib_dirs": [bin_ras],
                    "label": "bin_ras (5.0.7)",
                }
        # Nothing matched — return the canonical guess so the caller raises a
        # clear FileNotFoundError pointing at the expected location.
        return {
            "ras_exe": root_exe,
            "needs_c_file": False,
            "lib_dirs": [],
            "label": "canonical",
        }

    @staticmethod
    def _build_linux_ld_path(ras_exe_dir: Path, layout: dict) -> str:
        """Build LD_LIBRARY_PATH for a Linux RasUnsteady run, per layout (CLB-886)."""
        ras_exe_dir = Path(ras_exe_dir)
        ld_path_parts = []
        # Explicit lib dirs (e.g. 5.0.7 bin_ras/) take precedence.
        for d in layout.get("lib_dirs") or []:
            if Path(d).exists():
                ld_path_parts.append(str(d))
        if ld_path_parts:
            return ":".join(ld_path_parts)
        # Canonical: auto-detect a libs/ tree next to the binary.
        lib_base = ras_exe_dir / "libs"
        if not lib_base.exists():
            lib_base = ras_exe_dir.parent / "libs"
        if lib_base.exists():
            ld_path_parts.append(str(lib_base))
            for subdir in sorted(lib_base.iterdir()):
                if subdir.is_dir():
                    ld_path_parts.append(str(subdir))
                    logger.debug(f"Added library path: {subdir}")
        else:
            logger.warning(f"No libs/ directory found near {ras_exe_dir}")
            ld_path_parts.append(str(ras_exe_dir))
        return ":".join(ld_path_parts)

    @staticmethod
    def _validate_linux_solve(log_path, result_hdf, plan_num_str: str):
        """Validate a Linux RasUnsteady solve beyond exit-code 0 (CLB-882).

        RasUnsteady can exit 0 even when the unsteady solve failed in-band
        (convergence failure, "encountered an error", etc.), leaving an
        unpopulated result HDF. This scans the solver log for error markers and
        confirms the result HDF actually contains an Unsteady results group
        (not just the skeleton groups carried over from Phase-1 preprocessing).

        Returns:
            tuple[bool, str]: ``(ok, reason)`` — ``ok`` is False with a
            human-readable reason when the solve did not produce a valid result.
        """
        error_markers = [
            "encountered an error",
            "did not complete",
            "failed to converge",
            "computations were stopped",
            "fatal error",
        ]
        try:
            log_text = Path(log_path).read_text(errors="replace")
        except OSError:
            return False, "solver log unreadable"
        low = log_text.lower()
        for marker in error_markers:
            if marker in low:
                return False, f"solver log reports failure ('{marker}')"
        try:
            import h5py
            with h5py.File(str(result_hdf), "r") as hf:
                results = hf.get("Results")
                if results is None:
                    return False, "result HDF missing /Results group"
                if results.get("Unsteady") is None:
                    return False, "result HDF missing /Results/Unsteady group"
        except Exception as e:
            return False, f"result HDF unreadable or invalid: {e}"
        return True, "ok"

    @staticmethod
    @log_call
    def preprocess_geometry_linux(
        plan_number: Union[str, Number],
        ras_exe_dir: Union[str, Path],
        ras_object=None,
        timeout_sec: int = 7200,
        dos2unix: bool = True,
    ) -> 'ComputeResult':
        """Run the native Linux ``RasGeomPreprocess`` geometry preprocessor (CLB-885).

        This regenerates the geometry preprocessor tables (1D cross-section
        property tables and 2D cell/face HTab property tables) inside an
        existing ``{project}.p{plan}.tmp.hdf``, headlessly on Linux — mirroring
        :meth:`compute_plan_linux` (LD_LIBRARY_PATH auto-detect, dos2unix,
        output validation).

        **Scope / honest limitation:** the native ``RasGeomPreprocess`` binary
        operates *in place* on an existing ``.tmp.hdf`` that already contains the
        raw ``/Geometry`` group. It does **not** build the ``.tmp.hdf`` skeleton
        (nor the ``.b##``/``.x##`` files) from raw ``.prj``/``.g##``/``.u##``
        text — that initial assembly is still the Windows Phase-1 step. Use this
        to (re)compute geometry HTab tables on Linux after a geometry-only change,
        or to refresh ``/Geometry/GeomPreprocess`` before
        :meth:`compute_plan_linux` without round-tripping to Windows.

        Args:
            plan_number: Plan number whose ``.tmp.hdf`` to preprocess (e.g. "04").
            ras_exe_dir: Directory containing the ``RasGeomPreprocess`` binary and
                sibling ``libs/`` directory (e.g. ``/opt/hecras/6.6``).
            ras_object: Optional RAS project object. If None, uses global ``ras``.
            timeout_sec: Maximum preprocessing time in seconds (default 7200).
            dos2unix: Convert CRLF->LF in text files first (default True).

        Returns:
            ComputeResult: ``success`` True when the preprocessor finished and the
            ``.tmp.hdf`` contains a populated ``/Geometry/GeomPreprocess`` group.

        Raises:
            FileNotFoundError: If the ``RasGeomPreprocess`` binary or the
                ``.tmp.hdf``/``.x##`` prerequisites are missing.
        """
        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()

        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        ras_exe_dir = Path(str(ras_exe_dir).replace("\\", "/").rstrip("/"))
        geom_exe = ras_exe_dir / "RasGeomPreprocess"
        if not geom_exe.exists():
            raise FileNotFoundError(
                f"RasGeomPreprocess binary not found at {geom_exe}. "
                "Native Linux geometry preprocessing requires HEC-RAS 6.x Linux "
                "binaries (RasGeomPreprocess is bundled alongside RasUnsteady)."
            )

        project_dir = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Resolve geometry number from the plan file (mirror compute_plan_linux).
        geom_num = "01"
        try:
            plan_path = RasPlan.get_plan_path(plan_num_str, ras_obj)
            if plan_path is None:
                raise ValueError(
                    f"Could not resolve plan path for plan {plan_num_str}; "
                    "ensure the project is initialized and the plan exists."
                )
            plan_text = Path(plan_path).read_text(errors="replace")
            for line in plan_text.splitlines():
                if line.startswith("Geom File="):
                    import re as _re
                    m = _re.search(r"(\d+)", line.split("=", 1)[1])
                    if m:
                        geom_num = m.group(1)
                    break
        except Exception as e:
            logger.warning(f"Could not read geom number from plan file: {e}")

        tmp_hdf = project_dir / f"{project_name}.p{plan_num_str}.tmp.hdf"
        x_file = project_dir / f"{project_name}.x{geom_num}"
        missing = []
        if not tmp_hdf.exists():
            missing.append(f".p{plan_num_str}.tmp.hdf")
        if not x_file.exists():
            missing.append(f".x{geom_num}")
        if missing:
            raise FileNotFoundError(
                f"Missing prerequisites for Linux geometry preprocessing: "
                f"{', '.join(missing)}. The .tmp.hdf (with raw /Geometry) and .x## "
                f"must already exist (Windows Phase-1 builds these). "
                f"See examples/510_linux_execution.ipynb."
            )

        # Build LD_LIBRARY_PATH — auto-detect library subdirectories (mirror compute_plan_linux).
        lib_base = ras_exe_dir / "libs"
        if not lib_base.exists():
            lib_base = ras_exe_dir.parent / "libs"
        ld_path_parts = []
        if lib_base.exists():
            ld_path_parts.append(str(lib_base))
            for subdir in sorted(lib_base.iterdir()):
                if subdir.is_dir():
                    ld_path_parts.append(str(subdir))
        else:
            logger.warning(f"No libs/ directory found near {ras_exe_dir}")
            ld_path_parts.append(str(ras_exe_dir))
        ld_path = ":".join(ld_path_parts)
        logger.info(f"LD_LIBRARY_PATH: {ld_path}")

        if dos2unix:
            try:
                RasUtils.dos2unix(project_dir)
            except Exception as e:
                logger.warning(f"dos2unix failed: {e}")

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = ld_path

        log_path = project_dir / f"geompre_linux_{plan_num_str}.log"
        try:
            start_time = time.time()
            with open(log_path, "w") as log_fh:
                proc = subprocess.Popen(
                    [str(geom_exe), str(tmp_hdf), f"x{geom_num}"],
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=str(project_dir),
                )
            try:
                rc = proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                logger.error(f"Plan {plan_num_str}: geometry preprocessing timed out after {timeout_sec}s")
                return ComputeResult(success=False, results_df_row=None)
            run_time = time.time() - start_time
        except FileNotFoundError:
            raise RuntimeError(f"RasGeomPreprocess binary not found at {geom_exe}.")

        if rc != 0:
            try:
                tail = log_path.read_text(errors="replace")[-500:]
            except OSError:
                tail = "(log unreadable)"
            logger.error(
                f"Plan {plan_num_str}: RasGeomPreprocess exited with code {rc}. Log tail: {tail}"
            )
            return ComputeResult(success=False, results_df_row=None)

        ok, reason = RasCmdr._validate_geom_preprocess(log_path, tmp_hdf)
        if ok:
            logger.info(
                f"RasGeomPreprocess completed for plan {plan_num_str} "
                f"in {run_time:.1f}s (exit code 0, validated)"
            )
            return ComputeResult(success=True, results_df_row=None)
        logger.error(
            f"Plan {plan_num_str}: RasGeomPreprocess exited 0 but did not produce "
            f"a valid geometry preprocess result: {reason}"
        )
        return ComputeResult(success=False, results_df_row=None)

    @staticmethod
    def _validate_geom_preprocess(log_path, tmp_hdf):
        """Validate a Linux RasGeomPreprocess run beyond exit-code 0 (CLB-885).

        RasGeomPreprocess can exit 0 even when it failed in-band. This scans the
        log for error markers and confirms the .tmp.hdf gained a populated
        ``/Geometry/GeomPreprocess`` group (the 1D/2D hydraulic property tables
        the unsteady solver consumes).

        Returns:
            tuple[bool, str]: ``(ok, reason)``.
        """
        error_markers = [
            "encountered an error",
            "fatal error",
            "must be closed if it is being used",
            "hdf_error",
        ]
        try:
            log_low = Path(log_path).read_text(errors="replace").lower()
        except OSError:
            return False, "geompre log unreadable"
        for marker in error_markers:
            if marker in log_low:
                return False, f"geompre log reports failure ('{marker}')"
        # The "Finished Processing Geometry" banner is the success signal.
        if "finished processing geometry" not in log_low:
            return False, "geompre log missing 'Finished Processing Geometry' banner"
        try:
            import h5py
            with h5py.File(str(tmp_hdf), "r") as hf:
                geom = hf.get("Geometry")
                if geom is None:
                    return False, "tmp.hdf missing /Geometry group"
                gp = geom.get("GeomPreprocess")
                if gp is None or len(list(gp.keys())) == 0:
                    return False, "tmp.hdf missing/empty /Geometry/GeomPreprocess group"
        except Exception as e:
            return False, f"tmp.hdf unreadable or invalid: {e}"
        return True, "ok"

    @staticmethod
    def _windows_path_to_wsl(path: Union[str, Path]) -> str:
        """Translate a Windows path to its WSL path using the active distro."""
        path_arg = str(path).replace("\\", "/")
        proc = subprocess.run(
            ["wsl", "wslpath", "-a", path_arg],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"wslpath failed for {path}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    @staticmethod
    def _compute_plan_linux_via_wsl(
        ras_exe: str,
        ras_exe_dir: str,
        plan_number: str,
        geom_num: str,
        project_dir: Path,
        project_name: str,
        tmp_hdf: Path,
        timeout_sec: int,
        dos2unix: bool,
        retry: bool,
        retry_delay_sec: int,
        ras_obj,
    ) -> 'ComputeResult':
        """Run native Linux RasUnsteady from a Windows Python session via WSL."""
        project_dir_wsl = RasCmdr._windows_path_to_wsl(project_dir)
        tmp_hdf_wsl = RasCmdr._windows_path_to_wsl(tmp_hdf)
        log_path = project_dir / f"compute_linux_{plan_number}.log"
        log_path_wsl = RasCmdr._windows_path_to_wsl(log_path)

        if dos2unix:
            try:
                count = RasUtils.dos2unix(project_dir)
                logger.debug(f"dos2unix converted {count} files")
            except Exception as e:
                logger.warning(f"dos2unix failed before WSL execution: {e}")

        project_q = shlex.quote(project_dir_wsl)
        project_name_q = shlex.quote(project_name)
        ras_exe_q = shlex.quote(ras_exe)
        ras_exe_dir_q = shlex.quote(ras_exe_dir)
        tmp_hdf_q = shlex.quote(tmp_hdf_wsl)
        log_path_q = shlex.quote(log_path_wsl)
        geom_arg_q = shlex.quote(f"x{geom_num}")

        cleanup_script = (
            f"cd {project_q} && "
            "find . -maxdepth 1 -type l -name 'io.*' -delete"
        )

        script = fr"""
set -e
cd {project_q}
find . -maxdepth 1 -type l -name 'io.*' -delete
link_or_copy() {{
    ln -sfn "\$1" "\$2" 2>/dev/null || cp -f "\$1" "\$2"
}}
prefix={project_name_q}.
link_or_copy {shlex.quote(f'{project_name}.b{plan_number}')} io.b
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.X
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.x
for f in {project_name_q}.*; do
    [ -e "\$f" ] || continue
    suffix="\${{f#\$prefix}}"
    [ -e "io.\$suffix" ] || link_or_copy "\$f" "io.\$suffix"
done
lib_base=""
if [ -d {ras_exe_dir_q}/libs ]; then
    lib_base={ras_exe_dir_q}/libs
elif [ -d "\$(dirname {ras_exe_dir_q})/libs" ]; then
    lib_base="\$(dirname {ras_exe_dir_q})/libs"
fi
if [ -n "\$lib_base" ]; then
    ld_path="\$lib_base"
    for d in "\$lib_base"/*; do
        if [ -d "\$d" ]; then
            ld_path="\$ld_path:\$d"
        fi
    done
else
    ld_path={ras_exe_dir_q}
fi
LD_LIBRARY_PATH="\$ld_path" {ras_exe_q} {tmp_hdf_q} {geom_arg_q} > {log_path_q} 2>&1
"""

        max_attempts = 2 if retry else 1
        for attempt in range(1, max_attempts + 1):
            logger.info(
                f"WSL Linux execution attempt {attempt}/{max_attempts} for plan {plan_number}"
            )

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            proc = subprocess.Popen(
                ["wsl", "bash", "-lc", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                logger.error(f"Plan {plan_number}: WSL RasUnsteady timeout after {timeout_sec}s")
                stdout, stderr = "", f"Timeout after {timeout_sec}s"
                rc = -1
            else:
                rc = proc.returncode

            if rc == 0:
                subprocess.run(
                    ["wsl", "bash", "-lc", cleanup_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                if tmp_hdf.exists():
                    plan_hdf = RasCmdr._get_hdf_path(plan_number, ras_obj)
                    shutil.move(str(tmp_hdf), str(plan_hdf))
                    logger.debug(f"Renamed {tmp_hdf.name} -> {plan_hdf.name}")

                try:
                    ras_obj.plan_df = ras_obj.get_plan_entries()
                    ras_obj.update_results_df(plan_numbers=[plan_number])
                    mask = ras_obj.results_df['plan_number'] == plan_number
                    results_row = ras_obj.results_df[mask].iloc[0].copy() if mask.any() else None
                except Exception as e:
                    logger.debug(f"Could not extract results_df_row: {e}")
                    results_row = None

                return ComputeResult(success=True, results_df_row=results_row)

            try:
                tail = log_path.read_text(errors='replace')[-800:] if log_path.exists() else ""
            except OSError:
                tail = "(log unreadable)"
            logger.error(
                f"Plan {plan_number}: WSL RasUnsteady exited with code {rc}. "
                f"stdout={stdout.strip()} stderr={stderr.strip()} log tail={tail}"
            )

            if attempt < max_attempts:
                logger.info(f"Retrying in {retry_delay_sec}s...")
                time.sleep(retry_delay_sec)

        subprocess.run(
            ["wsl", "bash", "-lc", cleanup_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return ComputeResult(success=False, results_df_row=None)
