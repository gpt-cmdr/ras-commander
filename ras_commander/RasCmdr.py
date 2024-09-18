"""
Execution operations for running HEC-RAS simulations using subprocess.
Based on the HEC-Commander project's "Command Line is All You Need" approach, leveraging the -c compute flag to run HEC-RAS and orchestrating changes directly in the RAS input files to achieve automation outcomes. 
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
import subprocess
import os
import logging
import time
import pandas as pd
from threading import Thread, Lock
import queue
from pathlib import Path
import shutil
import queue
from threading import Thread, Lock
import time

# TO DO: 
# 1. Alternate Run Mode for compute_plan and compute_parallel:  Using Powershell to execute the HEC-RAS command and hide the RAS window and all child windows.
#    If this is implemented, and the plan has a popup, then the plan will not execute.  This is a deal breaker for many scenarios, and should only be used
#    as a special option for those who don't want to deal with the popups, or want to run in the background.  This option should be limited to non-commercial use.
# 2. Implment compute_plan_remote to go along with compute_plan.  This will be a compute_plan that is run on a remote machine via a psexec command.
#    First, we will use the keyring package to securely store the remote machine username and password.
#    Second, we will implement the psexec command to execute the HEC-RAS command on the remote machine.
#    Each machine will need to be initialized as a remote_worker object, which will store the machine name, username, password, ras_exe_path, local folder path and other relevant info.
#    A separate RasRemote class will be created to handle the creation of the remote_worker objects and the necessary abstractions. 
#    The compute_plan_remote function will live in RasCmdr, and will be a thin abstraction above the RasRemote class, since the functions will be simliar to the existing compute_plan functions, but specific to remote execution.  


class RasCmdr:
    @staticmethod
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
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        if dest_folder is not None:
            dest_folder = Path(ras_obj.project_folder).parent / dest_folder if isinstance(dest_folder, str) else Path(dest_folder)
            
            if dest_folder.exists():
                if overwrite_dest:
                    shutil.rmtree(dest_folder)
                elif any(dest_folder.iterdir()):
                    raise ValueError(f"Destination folder '{dest_folder}' exists and is not empty. Use overwrite_dest=True to overwrite.")
            
            dest_folder.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ras_obj.project_folder, dest_folder, dirs_exist_ok=True)
            
            compute_ras = RasPrj()
            compute_ras.initialize(dest_folder, ras_obj.ras_exe_path)
            compute_prj_path = compute_ras.prj_file
        else:
            compute_ras = ras_obj
            compute_prj_path = ras_obj.prj_file

        # Determine the plan path
        compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

        if not compute_prj_path or not compute_plan_path:
            print(f"Error: Could not find project file or plan file for plan {plan_number}")
            return False

        # Clear geometry preprocessor files if requested
        if clear_geompre:
            try:
                RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                print(f"Cleared geometry preprocessor files for plan: {plan_number}")
            except Exception as e:
                print(f"Error clearing geometry preprocessor files for plan {plan_number}: {str(e)}")

        # Set the number of cores if specified
        if num_cores is not None:
            try:
                RasPlan.set_num_cores(compute_plan_path, num_cores=num_cores, ras_object=compute_ras)
                print(f"Set number of cores to {num_cores} for plan: {plan_number}")
            except Exception as e:
                print(f"Error setting number of cores for plan {plan_number}: {str(e)}")

        # Prepare the command for HEC-RAS execution
        cmd = f'"{compute_ras.ras_exe_path}" -c "{compute_prj_path}" "{compute_plan_path}"'
        print("Running HEC-RAS from the Command Line:")
        print(f"Running command: {cmd}")

        # Execute the HEC-RAS command
        start_time = time.time()
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
            end_time = time.time()
            run_time = end_time - start_time
            print(f"HEC-RAS execution completed for plan: {plan_number}")
            print(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")
            return True
        except subprocess.CalledProcessError as e:
            end_time = time.time()
            run_time = end_time - start_time
            print(f"Error running plan: {plan_number}")
            print(f"Error message: {e.output}")
            print(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")
            return False

        ras_obj = ras_object or ras
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()



    @staticmethod
    def compute_parallel(
        plan_number: str | list[str] | None = None,
        max_workers: int = 2,
        num_cores: int = 2,
        clear_geompre: bool = False,
        ras_object: RasPrj | None = None,
        dest_folder: str | Path | None = None,
        overwrite_dest: bool = False
    ) -> dict[str, bool]:
        """
        Execute HEC-RAS plans in parallel using multiple worker threads.

        This function creates separate worker folders, copies the project to each, and executes the specified plans
        in parallel. It allows for isolated and concurrent execution of multiple plans.

        Args:
            plan_number (str | list[str] | None): Plan number, list of plan numbers, or None to execute all plans.
            max_workers (int, optional): Maximum number of worker threads to use. Default is 2.
            num_cores (int, optional): Number of cores to use for each plan execution. Default is 2.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files. Defaults to False.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
            dest_folder (str | Path, optional): Destination folder for the final computed results.
                If None, results will be stored in a "[Computed]" folder next to the original project.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.

        Returns:
            dict[str, bool]: A dictionary with plan numbers as keys and boolean values indicating success (True) or failure (False).

        Raises:
            ValueError: If the destination folder exists and is not empty, and overwrite_dest is False.
            FileNotFoundError: If a plan file is not found.

        Notes:
            - This function creates separate folders for each worker to ensure isolated execution.
            - Each worker uses its own RAS object to prevent conflicts.
            - Plans are distributed among workers using a queue to ensure efficient parallel processing.
            - The function automatically handles cleanup and consolidation of results after execution.
        
        Revision Notes:
            - Added support for clear_geompre flag as a pass-through to compute_plan.
            - Simplified worker thread logic by removing redundant operations.
            - Removed duplicate RAS object initialization in worker threads.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        project_folder = ras_obj.project_folder

        if dest_folder is not None:
            dest_folder_path = Path(dest_folder)
            if dest_folder_path.exists():
                if overwrite_dest:
                    shutil.rmtree(dest_folder_path)
                elif any(dest_folder_path.iterdir()):
                    raise ValueError(f"Destination folder '{dest_folder_path}' exists and is not empty. Use overwrite_dest=True to overwrite.")
            dest_folder_path.mkdir(parents=True, exist_ok=True)
            shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True)
            project_folder = dest_folder_path

        if plan_number:
            if isinstance(plan_number, str):
                plan_number = [plan_number]
            ras_obj.plan_df = ras_obj.plan_df[ras_obj.plan_df['plan_number'].isin(plan_number)]

        num_plans = len(ras_obj.plan_df)
        max_workers = min(max_workers, num_plans) if num_plans > 0 else 1
        print(f"Adjusted max_workers to {max_workers} based on the number of plans: {num_plans}")

        # Clean up existing worker folders and create new ones
        worker_ras_objects = {}
        for worker_id in range(1, max_workers + 1):
            worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
            if worker_folder.exists():
                shutil.rmtree(worker_folder)
            shutil.copytree(project_folder, worker_folder)
            
            worker_ras_instance = init_ras_project(
                ras_project_folder=worker_folder,
                ras_version=ras_obj.ras_exe_path,
                ras_instance=RasPrj()
            )
            worker_ras_objects[worker_id] = worker_ras_instance

        plan_queue = queue.Queue()
        for plan_number in ras_obj.plan_df['plan_number']:
            plan_queue.put(plan_number)

        execution_results: dict[str, bool] = {}
        results_lock = Lock()
        queue_lock = Lock()

        def worker_thread(worker_id: int):
            worker_ras_obj = worker_ras_objects[worker_id]
            while True:
                with queue_lock:
                    if plan_queue.empty():
                        break
                    plan_number = plan_queue.get()
                
                try:
                    print(f"Worker {worker_id} executing plan {plan_number}")
                    success = RasCmdr.compute_plan(
                        plan_number, 
                        ras_object=worker_ras_obj, 
                        clear_geompre=clear_geompre,
                        num_cores=num_cores
                    )
                    with results_lock:
                        execution_results[plan_number] = success
                    print(f"Completed: Plan {plan_number} in worker {worker_id}")
                except Exception as e:
                    with results_lock:
                        execution_results[plan_number] = False
                    print(f"Failed: Plan {plan_number} in worker {worker_id}. Error: {str(e)}")

        # Start worker threads
        worker_threads = [Thread(target=worker_thread, args=(worker_id,)) for worker_id in range(1, max_workers + 1)]
        for thread in worker_threads:
            thread.start()

        # Wait for all threads to complete
        for thread in worker_threads:
            thread.join()

        # Consolidate results
        final_dest_folder = dest_folder_path if dest_folder is not None else project_folder.parent / f"{project_folder.name} [Computed]"
        final_dest_folder.mkdir(exist_ok=True)
        print(f"Final destination for computed results: {final_dest_folder}")

        for worker_ras in worker_ras_objects.values():
            worker_folder = worker_ras.project_folder
            try:
                for item in worker_folder.iterdir():
                    dest_path = final_dest_folder / item.name
                    if dest_path.exists():
                        if dest_path.is_dir():
                            shutil.rmtree(dest_path)
                        else:
                            dest_path.unlink()
                    shutil.move(str(item), final_dest_folder)
                shutil.rmtree(worker_folder)
            except Exception as e:
                print(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

        # Print execution results for each plan
        print("\nExecution Results:")
        for plan_number, success in execution_results.items():
            print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")

        return execution_results
    
    
    
    @staticmethod
    def compute_test_mode(
        plan_number=None, 
        dest_folder_suffix="[Test]", 
        clear_geompre=False, 
        num_cores=None, 
        ras_object=None,
        overwrite_dest=False
    ):
        """
        Execute HEC-RAS plans in test mode.  This is a re-creation of the HEC-RAS command line -test flag, 
        which does not work in recent versions of HEC-RAS.
        
        As a special-purpose function that emulates the original -test flag, it operates differently than the 
        other two compute_ functions.  Per the original HEC-RAS test flag, it creates a separate test folder,
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
            None

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
        
        # This line of code is used to initialize the RasPrj object with the default "ras" object if no specific object is provided.
        ras_obj = ras_object or ras
        # This line of code is used to check if the RasPrj object is initialized.
        ras_obj.check_initialized()
        
        print("Starting the compute_test_mode...")
           
        # Use the project folder from the ras object
        project_folder = ras_obj.project_folder

        # Check if the project folder exists
        if not project_folder.exists():
            print(f"Error: Project folder '{project_folder}' does not exist.")
            return

        # Create test folder with the specified suffix in the same directory as the project folder
        compute_folder = project_folder.parent / f"{project_folder.name} {dest_folder_suffix}"
        print(f"Creating the test folder: {compute_folder}...")

        # Check if the compute folder exists and is empty
        if compute_folder.exists():
            if overwrite_dest:
                shutil.rmtree(compute_folder)
            elif any(compute_folder.iterdir()):
                raise ValueError(
                    f"Compute folder '{compute_folder}' exists and is not empty. "
                    "Use overwrite_dest=True to overwrite."
                )
        else:
            try:
                shutil.copytree(project_folder, compute_folder)
            except FileNotFoundError:
                print(f"Error: Unable to copy project folder. Source folder '{project_folder}' not found.")
                return
            except PermissionError:
                print(f"Error: Permission denied when trying to create or copy to '{compute_folder}'.")
                return
            except Exception as e:
                print(f"Error occurred while copying project folder: {str(e)}")
                return

        # Initialize a new RAS project in the compute folder
        try:
            compute_ras = RasPrj()
            compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
            compute_prj_path = compute_ras.prj_file
        except Exception as e:
            print(f"Error initializing RAS project in compute folder: {str(e)}")
            return

        if not compute_prj_path:
            print("Project file not found.")
            return


        # Get plan entries
        print("Getting plan entries...")
        try:
            ras_compute_plan_entries = compute_ras.plan_df
            print("Retrieved plan entries successfully.")
        except Exception as e:
            print(f"Error retrieving plan entries: {str(e)}")
            return

        if plan_number:
            if isinstance(plan_number, str):
                plan_number = [plan_number]
            ras_compute_plan_entries = ras_compute_plan_entries[
                ras_compute_plan_entries['plan_number'].isin(plan_number)
            ]
            print(f"Filtered plans to execute: {plan_number}")

        print("Running selected plans sequentially...")
        for _, plan in ras_compute_plan_entries.iterrows():
            plan_number = plan["plan_number"]
            start_time = time.time()
            try:
                RasCommander.compute_plan(
                    plan_number,
                    ras_object=compute_ras,
                    clear_geompre=clear_geompre,
                    num_cores=num_cores
                )
            except Exception as e:
                print(f"Error computing plan {plan_number}: {str(e)}")
            end_time = time.time()
            run_time = end_time - start_time
            print(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

        print("All selected plans have been executed.")
        print("compute_test_mode completed.")

        ras_obj = ras_object or ras
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()