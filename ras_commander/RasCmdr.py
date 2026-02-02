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
- compute_parallel()
- compute_test_mode()
        
        
        
"""
import os
import subprocess
import shutil
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
from typing import Union, List, Optional, Dict
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
from typing import Union, List, Optional, Dict
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
        # Normalize plan number to 2-digit string
        if isinstance(plan_number, Number):
            plan_num_str = f"{int(plan_number):02d}"
        else:
            plan_num_str = str(plan_number).zfill(2)

        return Path(ras_object.project_folder) / f"{ras_object.project_name}.p{plan_num_str}.hdf"

    @staticmethod
    def _verify_completion(hdf_path: Path, check_errors: bool = False) -> bool:
        """
        Verify that a HEC-RAS computation completed successfully (HDF-only).

        Args:
            hdf_path: Path to plan HDF file
            check_errors: If True, also fail verification if errors detected
                         in compute messages (default: False for backward compatibility)

        Returns:
            bool: True if verification passed
        """
        if not hdf_path.exists():
            logger.debug(f"HDF file does not exist: {hdf_path}")
            return False

        try:
            # Late import to avoid circular dependency
            from .hdf.HdfResultsPlan import HdfResultsPlan

            compute_msgs = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)

            if compute_msgs and 'Complete Process' in compute_msgs:
                # Optionally check for errors
                if check_errors:
                    from .results.ResultsParser import ResultsParser
                    parsed = ResultsParser.parse_compute_messages(compute_msgs)
                    if parsed['has_errors']:
                        logger.debug(f"Verification failed: {parsed['error_count']} errors found in {hdf_path.name}")
                        return False

                logger.debug(f"Verification passed: 'Complete Process' found in {hdf_path.name}")
                return True
            else:
                logger.debug(f"Verification failed: 'Complete Process' not found in {hdf_path.name}")
                return False
        except Exception as e:
            logger.warning(f"Error verifying completion for {hdf_path}: {e}")
            return False
    
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
        stream_callback: Optional[Callable] = None
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
        try:
            ras_obj = ras_object if ras_object is not None else ras
            _ras_obj = ras_obj
            logger.info(f"Using ras_object with project folder: {ras_obj.project_folder}")
            ras_obj.check_initialized()

            if dest_folder is not None:
                dest_folder = Path(ras_obj.project_folder).parent / dest_folder if isinstance(dest_folder, str) else Path(dest_folder)

                if dest_folder.exists():
                    if overwrite_dest:
                        shutil.rmtree(dest_folder)
                        logger.info(f"Destination folder '{dest_folder}' exists. Overwriting as per overwrite_dest=True.")
                    elif any(dest_folder.iterdir()):
                        error_msg = f"Destination folder '{dest_folder}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)

                dest_folder.mkdir(parents=True, exist_ok=True)
                shutil.copytree(ras_obj.project_folder, dest_folder, dirs_exist_ok=True)
                logger.info(f"Copied project folder to destination: {dest_folder}")

                compute_ras = RasPrj()
                compute_ras.initialize(dest_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
            else:
                compute_ras = ras_obj
                compute_prj_path = ras_obj.prj_file

            # Determine the plan path
            compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

            if not compute_prj_path or not compute_plan_path:
                logger.error(f"Could not find project file or plan file for plan {plan_number}")
                _success = False
                return ComputeResult(success=False, results_df_row=None)

            # Skip existing check - runs regardless of force_rerun (for resume capability)
            if skip_existing:
                hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                if RasCmdr._verify_completion(hdf_path):
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
                    plan_number=str(plan_number).zfill(2) if isinstance(plan_number, (int, Number)) else str(plan_number),
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
                    logger.info(f"Force-cleared all geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error force-clearing geometry preprocessor files for plan {plan_number}: {str(e)}")
            elif clear_geompre:
                # Original behavior - only clear .c## files
                try:
                    RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.info(f"Cleared geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error clearing geometry preprocessor files for plan {plan_number}: {str(e)}")

            # Set the number of cores if specified
            if num_cores is not None:
                try:
                    RasPlan.set_num_cores(compute_plan_path, num_cores=num_cores, ras_object=compute_ras)
                    logger.info(f"Set number of cores to {num_cores} for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error setting number of cores for plan {plan_number}: {str(e)}")

            # Callback: preprocessing complete
            if stream_callback and hasattr(stream_callback, 'on_prep_complete'):
                stream_callback.on_prep_complete(str(plan_number))

            # Prepare the command for HEC-RAS execution
            cmd = f'"{compute_ras.ras_exe_path}" -c "{compute_prj_path}" "{compute_plan_path}"'
            logger.info("Running HEC-RAS from the Command Line:")
            logger.info(f"Running command: {cmd}")

            # Callback: execution start
            if stream_callback and hasattr(stream_callback, 'on_exec_start'):
                stream_callback.on_exec_start(str(plan_number), cmd)

            # Execute the HEC-RAS command
            _did_execute = True
            start_time = time.time()
            try:
                # Choose execution method based on whether callback is provided
                if stream_callback and bco_monitor:
                    # Use Popen for real-time monitoring
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=str(compute_ras.project_folder),
                        shell=True
                    )

                    # Monitor .bco file until process completes
                    # (BcoMonitor will call on_exec_message callback as messages appear)
                    bco_monitor.monitor_until_signal(process)

                    # Wait for process to complete
                    return_code = process.wait()

                    # Check if subprocess succeeded
                    if return_code != 0:
                        raise subprocess.CalledProcessError(return_code, cmd)

                else:
                    # Original behavior when no callback
                    subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)

                end_time = time.time()
                run_time = end_time - start_time
                logger.info(f"HEC-RAS execution completed for plan: {plan_number}")
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

                # Callback: execution complete
                if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                    stream_callback.on_exec_complete(str(plan_number), True, run_time)

                # Verify completion if requested
                if verify:
                    hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                    verified = RasCmdr._verify_completion(hdf_path)

                    # Callback: verification result
                    if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), verified)

                    if verified:
                        logger.info(f"Verification passed for plan {plan_number}")
                        _success = True
                    else:
                        logger.error(f"Verification failed for plan {plan_number}: 'Complete Process' not found in compute messages")
                        _success = False
                else:
                    _success = True

            except subprocess.CalledProcessError as e:
                end_time = time.time()
                run_time = end_time - start_time
                logger.error(f"Error running plan: {plan_number}")
                logger.error(f"Error message: {e.output}")
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

                # Callback: execution complete (failure case)
                if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                    stream_callback.on_exec_complete(str(plan_number), False, run_time)

                _success = False
        except Exception as e:
            logger.critical(f"Error in compute_plan: {str(e)}")
            _success = False
        finally:
            # Update the RAS object's dataframes ONLY if executing in original folder
            # When dest_folder is used, the original project is unchanged
            if _ras_obj and dest_folder is None:
                try:
                    _ras_obj.plan_df = _ras_obj.get_plan_entries()
                    _ras_obj.geom_df = _ras_obj.get_geom_entries()
                    _ras_obj.flow_df = _ras_obj.get_flow_entries()
                    _ras_obj.unsteady_df = _ras_obj.get_unsteady_entries()
                    if _did_execute:
                        _ras_obj.update_results_df(plan_numbers=[plan_number])
                        # Capture results_df row for the executed plan
                        try:
                            plan_num_str = str(plan_number).zfill(2) if not isinstance(plan_number, str) else str(plan_number)
                            mask = _ras_obj.results_df['plan_number'] == plan_num_str
                            if mask.any():
                                _results_df_row = _ras_obj.results_df[mask].iloc[0].copy()
                        except Exception:
                            pass  # results_df_row stays None
                except Exception as e_refresh:
                    logger.warning(f"Error refreshing DataFrames after compute_plan: {e_refresh}")

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
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()

            project_folder = Path(ras_obj.project_folder)

            if dest_folder is not None:
                dest_folder_path = Path(dest_folder)
                if dest_folder_path.exists():
                    if overwrite_dest:
                        shutil.rmtree(dest_folder_path)
                        logger.info(f"Destination folder '{dest_folder_path}' exists. Overwriting as per overwrite_dest=True.")
                    elif any(dest_folder_path.iterdir()):
                        error_msg = f"Destination folder '{dest_folder_path}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                dest_folder_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True)
                logger.info(f"Copied project folder to destination: {dest_folder_path}")
                project_folder = dest_folder_path

            # Store filtered plan numbers separately to ensure only these are executed
            filtered_plan_numbers = []

            if plan_number:
                if isinstance(plan_number, (str, Number)):
                    plan_number = [plan_number]
                ras_obj.plan_df = ras_obj.plan_df[ras_obj.plan_df['plan_number'].isin(plan_number)]
                filtered_plan_numbers = list(ras_obj.plan_df['plan_number'])
                logger.info(f"Filtered plans to execute: {filtered_plan_numbers}")
            else:
                filtered_plan_numbers = list(ras_obj.plan_df['plan_number'])

            # Initialize execution_results dict
            execution_results: Dict[str, bool] = {}

            # Filter out plans with existing results if skip_existing is True
            if skip_existing:
                plans_to_skip = []
                plans_to_compute = []
                for plan_num in filtered_plan_numbers:
                    hdf_path = RasCmdr._get_hdf_path(plan_num, ras_obj)
                    if RasCmdr._verify_completion(hdf_path):
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
                logger.info("All plans skipped (existing results found). No computation needed.")
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
            for worker_id in range(1, max_workers + 1):
                worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
                if worker_folder.exists():
                    shutil.rmtree(worker_folder)
                    logger.info(f"Removed existing worker folder: {worker_folder}")
                shutil.copytree(project_folder, worker_folder)
                logger.info(f"Created worker folder: {worker_folder}")

                try:
                    worker_ras = RasPrj()
                    worker_ras_object = init_ras_project(
                        ras_project_folder=worker_folder,
                        ras_version=ras_obj.ras_exe_path,
                        ras_object=worker_ras
                    )
                    worker_ras_objects[worker_id] = worker_ras_object
                except Exception as e:
                    logger.critical(f"Failed to initialize RAS project for worker {worker_id}: {str(e)}")
                    worker_ras_objects[worker_id] = None

            # Explicitly use the filtered plan numbers for assignments
            worker_cycle = cycle(range(1, max_workers + 1))
            plan_assignments = [(next(worker_cycle), plan_num) for plan_num in filtered_plan_numbers]

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
                        logger.info(f"Plan {plan_num} executed in worker {worker_id}: {'Successful' if compute_result else 'Failed'}")
                    except Exception as e:
                        execution_results[plan_num] = False
                        logger.error(f"Plan {plan_num} failed in worker {worker_id}: {str(e)}")

            # Consolidate results: use dest_folder if provided, otherwise back to original folder
            # This eliminates the [Computed] folder anti-pattern - results go directly to original project
            if dest_folder is not None:
                final_dest_folder = dest_folder_path
                final_dest_folder.mkdir(parents=True, exist_ok=True)
                logger.info(f"Consolidating results to destination folder: {final_dest_folder}")
            else:
                final_dest_folder = project_folder
                logger.info(f"Consolidating results back to original project folder: {final_dest_folder}")

            for worker_ras in worker_ras_objects.values():
                if worker_ras is None:
                    continue
                worker_folder = Path(worker_ras.project_folder)
                try:
                    # First, close any open resources in the worker RAS object
                    worker_ras.close() if hasattr(worker_ras, 'close') else None
                    
                    # Add a small delay to ensure file handles are released
                    time.sleep(1)
                    
                    # Move files with retry mechanism
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            for item in worker_folder.iterdir():
                                dest_path = final_dest_folder / item.name
                                if dest_path.exists():
                                    if dest_path.is_dir():
                                        shutil.rmtree(dest_path)
                                    else:
                                        dest_path.unlink()
                                # Use copy instead of move for more reliability
                                if item.is_dir():
                                    shutil.copytree(item, dest_path)
                                else:
                                    shutil.copy2(item, dest_path)
                            
                            # Add another small delay before removal
                            time.sleep(1)
                            
                            # Try to remove the worker folder
                            if worker_folder.exists():
                                shutil.rmtree(worker_folder)
                            break  # If successful, break the retry loop
                            
                        except PermissionError as pe:
                            if retry == max_retries - 1:  # If this was the last retry
                                logger.error(f"Failed to move/remove files after {max_retries} attempts: {str(pe)}")
                                raise
                            time.sleep(2 ** retry)  # Exponential backoff
                            continue
                            
                except Exception as e:
                    logger.error(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

            # When dest_folder is used, re-initialize ras_obj from dest_folder
            # This ensures results_df reflects results in the destination folder
            if dest_folder is not None:
                try:
                    ras_obj.initialize(final_dest_folder, ras_obj.ras_exe_path)
                    logger.info(f"Re-initialized ras_object from destination folder: {final_dest_folder}")
                except Exception as e:
                    logger.critical(f"Failed to re-initialize ras_object from destination folder: {str(e)}")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

            ras_obj = ras_object or ras
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
            except Exception:
                pass  # _results_df stays empty

            return ComputeParallelResult(execution_results=execution_results, results_df=_results_df)

        except Exception as e:
            logger.critical(f"Error in compute_parallel: {str(e)}")
            return ComputeParallelResult()

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
            logger.info(f"Creating the test folder: {compute_folder}...")

            if compute_folder.exists():
                if overwrite_dest:
                    shutil.rmtree(compute_folder)
                    logger.info(f"Compute folder '{compute_folder}' exists. Overwriting as per overwrite_dest=True.")
                elif any(compute_folder.iterdir()):
                    error_msg = (
                        f"Compute folder '{compute_folder}' exists and is not empty. "
                        "Use overwrite_dest=True to overwrite."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

            try:
                shutil.copytree(project_folder, compute_folder)
                logger.info(f"Copied project folder to compute folder: {compute_folder}")
            except Exception as e:
                logger.critical(f"Error occurred while copying project folder: {str(e)}")
                return ComputeParallelResult()

            try:
                compute_ras = RasPrj()
                compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
                logger.info(f"Initialized RAS project in compute folder: {compute_prj_path}")
            except Exception as e:
                logger.critical(f"Error initializing RAS project in compute folder: {str(e)}")
                return ComputeParallelResult()

            if not compute_prj_path:
                logger.error("Project file not found.")
                return ComputeParallelResult()

            logger.info("Getting plan entries...")
            try:
                ras_compute_plan_entries = compute_ras.plan_df
                logger.info("Retrieved plan entries successfully.")
            except Exception as e:
                logger.critical(f"Error retrieving plan entries: {str(e)}")
                return ComputeParallelResult()

            if plan_number:
                if isinstance(plan_number, (str, Number)):
                    plan_number = [plan_number]
                ras_compute_plan_entries = ras_compute_plan_entries[
                    ras_compute_plan_entries['plan_number'].isin(plan_number)
                ]
                logger.info(f"Filtered plans to execute: {plan_number}")

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
                        logger.info(f"Successfully computed plan {current_plan_number}")
                    else:
                        logger.error(f"Failed to compute plan {current_plan_number}")
                except Exception as e:
                    execution_results[current_plan_number] = False
                    logger.error(f"Error computing plan {current_plan_number}: {str(e)}")
                finally:
                    end_time = time.time()
                    run_time = end_time - start_time
                    logger.info(f"Total run time for plan {current_plan_number}: {run_time:.2f} seconds")

            logger.info("All selected plans have been executed.")

            # Consolidate HDF results back to original project folder
            # This eliminates the [Test] folder anti-pattern - results go to original project
            logger.info(f"Consolidating HDF results from {compute_folder} back to original project folder...")
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
                logger.info(f"Removed test folder: {compute_folder}")
            except Exception as e:
                logger.warning(f"Failed to remove test folder {compute_folder}: {str(e)}")

            logger.info("compute_test_mode completed.")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

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
            except Exception:
                pass  # _results_df stays empty

            return ComputeParallelResult(execution_results=execution_results, results_df=_results_df)

        except Exception as e:
            logger.critical(f"Error in compute_test_mode: {str(e)}")
            return ComputeParallelResult()