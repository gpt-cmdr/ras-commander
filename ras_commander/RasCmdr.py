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
        Execute a HEC-RAS plan.

        Args:
            plan_number (str, Path): The plan number to execute (e.g., "01", "02") or the full path to the plan file.
            dest_folder (str, Path, optional): Name of the folder or full path for computation.
                If a string is provided, it will be created in the same parent directory as the project folder.
                If a full path is provided, it will be used as is.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files. Defaults to False.
            num_cores (int, optional): Number of cores to use for the plan execution. If None, the current setting is not changed.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.

        Returns:
            bool: True if the execution was successful, False otherwise.

        Raises:
            ValueError: If the specified dest_folder already exists and is not empty, and overwrite_dest is False.
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
        Compute multiple HEC-RAS plans in parallel.

        Args:
            plan_number (Union[str, List[str], None]): Plan number(s) to compute. If None, all plans are computed.
            max_workers (int): Maximum number of parallel workers.
            num_cores (int): Number of cores to use per plan computation.
            clear_geompre (bool): Whether to clear geometry preprocessor files.
            ras_object (Optional[RasPrj]): RAS project object. If None, uses global instance.
            dest_folder (Union[str, Path, None]): Destination folder for computed results.
            overwrite_dest (bool): Whether to overwrite existing destination folder.

        Returns:
            Dict[str, bool]: Dictionary of plan numbers and their execution success status.
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
                    ras_instance = RasPrj()
                    worker_ras_instance = init_ras_project(
                        ras_project_folder=worker_folder,
                        ras_version=ras_obj.ras_exe_path,
                        ras_instance=ras_instance
                    )
                    worker_ras_objects[worker_id] = worker_ras_instance
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
                    for item in worker_folder.iterdir():
                        dest_path = final_dest_folder / item.name
                        if dest_path.exists():
                            if dest_path.is_dir():
                                shutil.rmtree(dest_path)
                                logger.debug(f"Removed existing directory at {dest_path}")
                            else:
                                dest_path.unlink()
                                logger.debug(f"Removed existing file at {dest_path}")
                        shutil.move(str(item), final_dest_folder)
                        logger.debug(f"Moved {item} to {final_dest_folder}")
                    shutil.rmtree(worker_folder)
                    logger.info(f"Removed worker folder: {worker_folder}")
                except Exception as e:
                    logger.error(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

            try:
                final_dest_folder_ras_obj = RasPrj()
                final_dest_folder_ras_obj = init_ras_project(
                    ras_project_folder=final_dest_folder, 
                    ras_version=ras_obj.ras_exe_path,
                    ras_instance=final_dest_folder_ras_obj
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
        Execute HEC-RAS plans in test mode. This is a re-creation of the HEC-RAS command line -test flag, 
        which does not work in recent versions of HEC-RAS.
        
        As a special-purpose function that emulates the original -test flag, it operates differently than the 
        other two compute_ functions. Per the original HEC-RAS test flag, it creates a separate test folder,
        copies the project there, and executes the specified plans in sequential order.
        
        For most purposes, just copying a the project folder, initing that new folder, then running each plan 
        with compute_plan is a simpler and more flexible approach.  This is shown in the examples provided
        in the ras-commander library.

        Args:
            plan_number (str, list[str], optional): Plan number or list of plan numbers to execute. 
                If None, all plans will be executed. Default is None.
            dest_folder_suffix (str, optional): Suffix to append to the test folder name to create dest_folder. 
                Defaults to "[Test]".
                dest_folder is always created in the project folder's parent directory.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files.
                Defaults to False.
            num_cores (int, optional): Maximum number of cores to use for each plan.
                If None, the current setting is not changed. Default is None.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.

        Returns:
            Dict[str, bool]: Dictionary of plan numbers and their execution success status.

        Example:
            Run all plans: RasCommander.compute_test_mode()
            Run a specific plan: RasCommander.compute_test_mode(plan_number="01")
            Run multiple plans: RasCommander.compute_test_mode(plan_number=["01", "03", "05"])
            Run plans with a custom folder suffix: RasCommander.compute_test_mode(dest_folder_suffix="[TestRun]")
            Run plans and clear geometry preprocessor files: RasCommander.compute_test_mode(clear_geompre=True)
            Run plans with a specific number of cores: RasCommander.compute_test_mode(num_cores=4)
            
        Notes:
            - This function executes plans in a separate folder for isolated testing.
            - If plan_number is not provided, all plans in the project will be executed.
            - The function does not change the geometry preprocessor and IB tables settings.  
                - To force recomputing of geometry preprocessor and IB tables, use the clear_geompre=True option.
            - Plans are executed sequentially.
            - Because copying the project is implicit, only a dest_folder_suffix option is provided.
            - For more flexible run management, use the compute_parallel or compute_sequential functions.
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