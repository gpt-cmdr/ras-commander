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
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Module code starts here

# TODO: Future Enhancements
# 1. Alternate Run Mode for compute_plan and compute_parallel:
#    - Use Powershell to execute HEC-RAS command
#    - Hide RAS window and all child windows
#    - Note: This mode may prevent execution if the plan has a popup
#    - Intended for background runs or popup-free scenarios
#    - Limit to non-commercial use
#
# 2. Implement compute_plan_remote:
#    - Execute compute_plan on a remote machine via psexec
#    - Use keyring package for secure credential storage
#    - Implement psexec command for remote HEC-RAS execution
#    - Create remote_worker objects to store machine details:
#      (machine name, username, password, ras_exe_path, local folder path, etc.)
#    - Develop RasRemote class for remote_worker management and abstractions
#    - Implement compute_plan_remote in RasCmdr as a thin wrapper around RasRemote
#      (similar to existing compute_plan functions but for remote execution)


class RasCmdr:
    
    @staticmethod
    @log_call
    def compute_plan(
        plan_number,
        dest_folder=None, 
        ras_object=None,
        clear_geompre=False,
        num_cores=None,
        overwrite_dest=False
    ):
        """
        Execute a single HEC-RAS plan in a specified location.

        This function runs a HEC-RAS plan by launching the HEC-RAS executable through command line, 
        allowing for destination folder specification, core count control, and geometry preprocessor management.

        Args:
            plan_number (str, Path): The plan number to execute (e.g., "01", "02") or the full path to the plan file.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder (str, Path, optional): Name of the folder or full path for computation.
                If a string is provided, it will be created in the same parent directory as the project folder.
                If a full path is provided, it will be used as is.
                If None, computation occurs in the original project folder, modifying the original project.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files. Defaults to False.
                Set to True when geometry has been modified to force recomputation of preprocessor files.
            num_cores (int, optional): Number of cores to use for the plan execution. 
                If None, the current setting in the plan file is not changed.
                Generally, 2-4 cores provides good performance for most models.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.
                Set to True to replace an existing destination folder with the same name.

        Returns:
            bool: True if the execution was successful, False otherwise.

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
            
            # Run a plan in a specific folder with multiple options
            RasCmdr.compute_plan(
                "01", 
                dest_folder="computation_folder",
                num_cores=2,
                clear_geompre=True,
                overwrite_dest=True
            )
            
        Notes:
            - For executing multiple plans, consider using compute_parallel() or compute_test_mode().
            - Setting num_cores appropriately is important for performance:
              * 1-2 cores: Highest efficiency per core, good for small models
              * 3-8 cores: Good balance for most models
              * >8 cores: May have diminishing returns due to overhead
            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.
        """
        try:
            ras_obj = ras_object if ras_object is not None else ras
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
                return False

            # Clear geometry preprocessor files if requested
            if clear_geompre:
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

            # Prepare the command for HEC-RAS execution
            cmd = f'"{compute_ras.ras_exe_path}" -c "{compute_prj_path}" "{compute_plan_path}"'
            logger.info("Running HEC-RAS from the Command Line:")
            logger.info(f"Running command: {cmd}")

            # Execute the HEC-RAS command
            start_time = time.time()
            try:
                subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
                end_time = time.time()
                run_time = end_time - start_time
                logger.info(f"HEC-RAS execution completed for plan: {plan_number}")
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")
                return True
            except subprocess.CalledProcessError as e:
                end_time = time.time()
                run_time = end_time - start_time
                logger.error(f"Error running plan: {plan_number}")
                logger.error(f"Error message: {e.output}")
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")
                return False
        except Exception as e:
            logger.critical(f"Error in compute_plan: {str(e)}")
            return False
        finally:
            # Update the RAS object's dataframes
            if ras_obj:
                ras_obj.plan_df = ras_obj.get_plan_entries()
                ras_obj.geom_df = ras_obj.get_geom_entries()
                ras_obj.flow_df = ras_obj.get_flow_entries()
                ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
    


    @staticmethod
    @log_call
    def compute_parallel(
        plan_number: Union[str, List[str], None] = None,
        max_workers: int = 2,
        num_cores: int = 2,
        clear_geompre: bool = False,
        ras_object: Optional['RasPrj'] = None,
        dest_folder: Union[str, Path, None] = None,
        overwrite_dest: bool = False
    ) -> Dict[str, bool]:
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
            clear_geompre (bool): Whether to clear geometry preprocessor files before computation.
                Set to True when geometry has been modified to force recomputation.
            ras_object (Optional[RasPrj]): RAS project object. If None, uses global 'ras' instance.
                Useful when working with multiple projects simultaneously.
            dest_folder (Union[str, Path, None]): Destination folder for computed results.
                If None, creates a "[Computed]" folder adjacent to the project folder.
                If string, creates folder in the project's parent directory.
                If Path, uses the exact path provided.
            overwrite_dest (bool): Whether to overwrite existing destination folder.
                Set to True to replace an existing destination folder with the same name.

        Returns:
            Dict[str, bool]: Dictionary of plan numbers and their execution success status.
                Keys are plan numbers and values are boolean success indicators.

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

            if plan_number:
                if isinstance(plan_number, str):
                    plan_number = [plan_number]
                ras_obj.plan_df = ras_obj.plan_df[ras_obj.plan_df['plan_number'].isin(plan_number)]
                logger.info(f"Filtered plans to execute: {plan_number}")

            num_plans = len(ras_obj.plan_df)
            max_workers = min(max_workers, num_plans) if num_plans > 0 else 1
            logger.info(f"Adjusted max_workers to {max_workers} based on the number of plans: {num_plans}")

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

            worker_cycle = cycle(range(1, max_workers + 1))
            plan_assignments = [(next(worker_cycle), plan_num) for plan_num in ras_obj.plan_df['plan_number']]

            execution_results: Dict[str, bool] = {}

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        RasCmdr.compute_plan,
                        plan_num, 
                        ras_object=worker_ras_objects[worker_id], 
                        clear_geompre=clear_geompre,
                        num_cores=num_cores
                    )
                    for worker_id, plan_num in plan_assignments
                ]

                for future, (worker_id, plan_num) in zip(as_completed(futures), plan_assignments):
                    try:
                        success = future.result()
                        execution_results[plan_num] = success
                        logger.info(f"Plan {plan_num} executed in worker {worker_id}: {'Successful' if success else 'Failed'}")
                    except Exception as e:
                        execution_results[plan_num] = False
                        logger.error(f"Plan {plan_num} failed in worker {worker_id}: {str(e)}")

            final_dest_folder = dest_folder_path if dest_folder is not None else project_folder.parent / f"{project_folder.name} [Computed]"
            final_dest_folder.mkdir(parents=True, exist_ok=True)
            logger.info(f"Final destination for computed results: {final_dest_folder}")

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

            try:
                final_dest_folder_ras = RasPrj()
                final_dest_folder_ras_obj = init_ras_project(
                    ras_project_folder=final_dest_folder, 
                    ras_version=ras_obj.ras_exe_path,
                    ras_object=final_dest_folder_ras
                )
                final_dest_folder_ras_obj.check_initialized()
            except Exception as e:
                logger.critical(f"Failed to initialize RasPrj for final destination: {str(e)}")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

            ras_obj = ras_object or ras
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

            return execution_results

        except Exception as e:
            logger.critical(f"Error in compute_parallel: {str(e)}")
            return {}

    @staticmethod
    @log_call
    def compute_test_mode(
        plan_number=None, 
        dest_folder_suffix="[Test]", 
        clear_geompre=False, 
        num_cores=None, 
        ras_object=None,
        overwrite_dest=False
    ):
        """
        Execute HEC-RAS plans sequentially in a separate test folder.

        This function creates a separate test folder, copies the project there, and executes
        the specified plans in sequential order. It's useful for batch processing plans that 
        need to be run in a specific order or when you want to ensure consistent resource usage.

        Args:
            plan_number (str, list[str], optional): Plan number or list of plan numbers to execute. 
                If None, all plans will be executed. Default is None.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder_suffix (str, optional): Suffix to append to the test folder name. 
                Defaults to "[Test]".
                The test folder is always created in the project folder's parent directory.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files.
                Defaults to False.
                Set to True when geometry has been modified to force recomputation.
            num_cores (int, optional): Number of cores to use for each plan.
                If None, the current setting in the plan file is not changed. Default is None.
                For sequential execution, 4-8 cores often provides good performance.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. 
                Defaults to False.
                Set to True to replace an existing test folder with the same name.

        Returns:
            Dict[str, bool]: Dictionary of plan numbers and their execution success status.
                Keys are plan numbers and values are boolean success indicators.

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
            
            # Run specific plans with multiple options
            RasCmdr.compute_test_mode(
                plan_number=["01", "02"],
                dest_folder_suffix="[SpecificSequential]",
                clear_geompre=True,
                num_cores=6,
                overwrite_dest=True
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
        """
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            
            logger.info("Starting the compute_test_mode...")
               
            project_folder = Path(ras_obj.project_folder)

            if not project_folder.exists():
                logger.error(f"Project folder '{project_folder}' does not exist.")
                return {}

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
                return {}

            try:
                compute_ras = RasPrj()
                compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
                logger.info(f"Initialized RAS project in compute folder: {compute_prj_path}")
            except Exception as e:
                logger.critical(f"Error initializing RAS project in compute folder: {str(e)}")
                return {}

            if not compute_prj_path:
                logger.error("Project file not found.")
                return {}

            logger.info("Getting plan entries...")
            try:
                ras_compute_plan_entries = compute_ras.plan_df
                logger.info("Retrieved plan entries successfully.")
            except Exception as e:
                logger.critical(f"Error retrieving plan entries: {str(e)}")
                return {}

            if plan_number:
                if isinstance(plan_number, str):
                    plan_number = [plan_number]
                ras_compute_plan_entries = ras_compute_plan_entries[
                    ras_compute_plan_entries['plan_number'].isin(plan_number)
                ]
                logger.info(f"Filtered plans to execute: {plan_number}")

            execution_results = {}
            logger.info("Running selected plans sequentially...")
            for _, plan in ras_compute_plan_entries.iterrows():
                plan_number = plan["plan_number"]
                start_time = time.time()
                try:
                    success = RasCmdr.compute_plan(
                        plan_number,
                        ras_object=compute_ras,
                        clear_geompre=clear_geompre,
                        num_cores=num_cores
                    )
                    execution_results[plan_number] = success
                    if success:
                        logger.info(f"Successfully computed plan {plan_number}")
                    else:
                        logger.error(f"Failed to compute plan {plan_number}")
                except Exception as e:
                    execution_results[plan_number] = False
                    logger.error(f"Error computing plan {plan_number}: {str(e)}")
                finally:
                    end_time = time.time()
                    run_time = end_time - start_time
                    logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

            logger.info("All selected plans have been executed.")
            logger.info("compute_test_mode completed.")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

            return execution_results

        except Exception as e:
            logger.critical(f"Error in compute_test_mode: {str(e)}")
            return {}