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


class RasCommander:
    @staticmethod
    def compute_plan(
        plan_number,
        compute_folder=None, 
        ras_object=None
        ):
        """
        Execute a HEC-RAS plan.

        Args:
            plan_number (str, Path): The plan number to execute (e.g., "01", "02") or the full path to the plan file.
            compute_folder (str, Path, optional): Name of the folder or full path for computation.
                If a string is provided, it will be created in the same parent directory as the project folder.
                If a full path is provided, it will be used as is.
                If the compute_folder already exists, a ValueError will be raised to prevent overwriting.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            bool: True if the execution was successful, False otherwise.

        Raises:
            ValueError: If the specified compute_folder already exists and is not empty.

        Example:
            # Execute plan "01" in the current project folder
            RasCommander.compute_plan("01")

            # Execute plan "02" in a new compute folder
            RasCommander.compute_plan("02", compute_folder="ComputeRun1")

            # Execute a specific plan file in a new compute folder
            RasCommander.compute_plan(r"C:\path\to\plan.p01.hdf", compute_folder="ComputeRun2")

        Notes:
            When using a compute_folder:
            - A new RasPrj object is created for the computation.
            - The entire project is copied to the new folder before execution.
            - Results will be stored in the new folder, preserving the original project.
        """
        # Initialize RasPrj object with the default "ras" object if no specific object is provided
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Determine the compute folder path and plan path
        if compute_folder is not None:
            compute_folder = Path(ras_obj.project_folder).parent / compute_folder if isinstance(compute_folder, str) else Path(compute_folder)
            
            # Check if the compute folder exists and is empty
            if compute_folder.exists() and any(compute_folder.iterdir()):
                raise ValueError(f"Compute folder '{compute_folder}' exists and is not empty. Please ensure the compute folder is empty before proceeding.")
            elif not compute_folder.exists():
                shutil.copytree(ras_obj.project_folder, compute_folder)
            
            # Initialize a new RAS project in the compute folder
            compute_ras = RasPrj()
            compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
            compute_prj_path = compute_ras.prj_file
        else:
            compute_ras = ras_obj
            compute_prj_path = ras_obj.prj_file

        # Determine the plan path
        compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

        if not compute_prj_path or not compute_plan_path:
            print(f"Error: Could not find project file or plan file for plan {plan_number}")
            return False

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


    def compute_test_mode(
        plan_numbers=None, 
        folder_suffix="[Test]", 
        clear_geompre=False, 
        max_cores=None, 
        ras_object=None
    ):
        """
        Execute HEC-RAS plans in test mode.

        This function creates a separate test folder, copies the project there, and executes the specified plans.
        It allows for isolated testing without affecting the original project files.

        Args:
            plan_numbers (list of str, optional): List of plan numbers to execute. 
                If None, all plans will be executed. Default is None.
            folder_suffix (str, optional): Suffix to append to the test folder name. 
                Defaults to "[Test]".
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files.
                Defaults to False.
            max_cores (int, optional): Maximum number of cores to use for each plan.
                If None, the current setting is not changed. Default is None.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            None

        Example:
            Run all plans: RasCommander.compute_test_mode()
            Run specific plans: RasCommander.compute_test_mode(plan_numbers=["01", "03", "05"])
            Run plans with a custom folder suffix: RasCommander.compute_test_mode(folder_suffix="[TestRun]")
            Run plans and clear geometry preprocessor files: RasCommander.compute_test_mode(clear_geompre=True)
            Run plans with a specific number of cores: RasCommander.compute_test_mode(max_cores=4)
            
        Notes:
            - This function executes plans in a separate folder for isolated testing.
            - If plan_numbers is not provided, all plans in the project will be executed.
            - The function does not change the geometry preprocessor and IB tables settings.  
                - To force recomputing of geometry preprocessor and IB tables, use the clear_geompre=True option.
            - Plans are executed sequentially.
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
        compute_folder = project_folder.parent / f"{project_folder.name} {folder_suffix}"
        print(f"Creating the test folder: {compute_folder}...")

        # Check if the compute folder exists and is empty
        if compute_folder.exists():
            if any(compute_folder.iterdir()):
                raise ValueError(
                    f"Compute folder '{compute_folder}' exists and is not empty. "
                    "Please ensure the compute folder is empty before proceeding."
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
        print(f"Project file found: {compute_prj_path}")

        # Get plan entries
        print("Getting plan entries...")
        try:
            ras_compute_plan_entries = compute_ras.plan_df
            print("Retrieved plan entries successfully.")
        except Exception as e:
            print(f"Error retrieving plan entries: {str(e)}")
            return

        # Filter plans if plan_numbers is provided
        if plan_numbers:
            ras_compute_plan_entries = ras_compute_plan_entries[
                ras_compute_plan_entries['plan_number'].isin(plan_numbers)
            ]
            print(f"Filtered plans to execute: {plan_numbers}")

        # Optimize by iterating once to clear geompre files and set max cores
        if clear_geompre or max_cores is not None:
            print("Processing geometry preprocessor files and core settings...")
            for plan_file in ras_compute_plan_entries['full_path']:
                if clear_geompre:
                    try:
                        RasGeo.clear_geompre_files(plan_file)
                        print(f"Cleared geometry preprocessor files for {plan_file}")
                    except Exception as e:
                        print(f"Error clearing geometry preprocessor files for {plan_file}: {str(e)}")
                if max_cores is not None:
                    try:
                        RasPlan.set_num_cores(plan_file, num_cores=max_cores)
                        print(f"Set max cores to {max_cores} for {plan_file}")
                    except Exception as e:
                        print(f"Error setting max cores for {plan_file}: {str(e)}")
            print("Geometry preprocessor files and core settings processed successfully.")

        # Run plans sequentially
        print("Running selected plans sequentially...")
        for _, plan in ras_compute_plan_entries.iterrows():
            plan_number = plan["plan_number"]
            start_time = time.time()
            try:
                RasCommander.compute_plan(plan_number, ras_object=compute_ras)
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

    @staticmethod
    def compute_parallel(
        plan_numbers: list[str] | None = None,
        max_workers: int = 2,
        cores_per_run: int = 2,
        ras_object: RasPrj | None = None,
        dest_folder: str | Path | None = None
    ) -> dict[str, bool]:
        """
        Execute HEC-RAS plans in parallel using multiple worker threads.

        This function creates separate worker folders, copies the project to each, and executes the specified plans
        in parallel. It allows for isolated and concurrent execution of multiple plans.

        Args:
            plan_numbers (list[str], optional): List of plan numbers to execute. 
                If None, all plans will be executed. Default is None.
            max_workers (int, optional): Maximum number of worker threads to use.
                Default is 2.
            cores_per_run (int, optional): Number of cores to use for each plan execution.
                Default is 2.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
            dest_folder (str | Path, optional): Destination folder for the final computed results.
                If None, results will be stored in a "[Computed]" folder next to the original project.

        Returns:
            dict[str, bool]: A dictionary with plan numbers as keys and boolean values indicating success (True) or failure (False).

        Raises:
            ValueError: If the destination folder exists and is not empty.
            FileNotFoundError: If a plan file is not found.

        Notes:
            - This function creates separate folders for each worker to ensure isolated execution.
            - Each worker uses its own RAS object to prevent conflicts.
            - Plans are distributed among workers using a queue to ensure efficient parallel processing.
            - The function automatically handles cleanup and consolidation of results after execution.
        
        Revision Notes:
            - Removed redundant variable initializations.
            - Streamlined worker folder creation and RAS object initialization.
            - Optimized the consolidation of results from worker folders.
            - Removed debug print statements for cleaner execution logs.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        project_folder = ras_obj.project_folder

        if dest_folder is not None:
            dest_folder_path = Path(dest_folder)
            if dest_folder_path.exists():
                if any(dest_folder_path.iterdir()):
                    raise ValueError(
                        f"\nError: Destination folder already exists: '{dest_folder_path}'\n"
                        f"To prevent accidental overwriting of results, this operation cannot proceed.\n"
                        f"Please take one of the following actions:\n"
                        f"1. Delete the folder manually and run the operation again.\n"
                        f"2. Use a different destination folder name.\n"
                        f"3. Programmatically delete the folder before calling compute_parallel, like this:\n"
                        f"   if Path('{dest_folder_path}').exists():\n"
                        f"       shutil.rmtree('{dest_folder_path}')\n"
                        f"This safety measure ensures that you don't inadvertently overwrite existing results."
                    )
            else:
                try:
                    dest_folder_path.mkdir(parents=True, exist_ok=True)
                except PermissionError:
                    raise PermissionError(f"Unable to create destination folder '{dest_folder_path}'. Permission denied.")
            try:
                shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True)
            except shutil.Error as e:
                raise IOError(f"Error copying project to destination folder: {str(e)}")
            project_folder = dest_folder_path  # Update project_folder to the new destination

        if plan_numbers:
            if isinstance(plan_numbers, str):
                plan_numbers = [plan_numbers]
            ras_obj.plan_df = ras_obj.plan_df[ras_obj.plan_df['plan_number'].isin(plan_numbers)]

        num_plans = len(ras_obj.plan_df)
        max_workers = min(max_workers, num_plans) if num_plans > 0 else 1
        print(f"Adjusted max_workers to {max_workers} based on the number of plans: {num_plans}")

        # Clean up existing worker folders
        for worker_id in range(1, max_workers + 1):
            worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
            if worker_folder.exists():
                shutil.rmtree(worker_folder)
                print(f"Removed existing worker folder: {worker_folder}")

        # Create worker folders and initialize RAS objects
        worker_ras_objects = {}
        for worker_id in range(1, max_workers + 1):
            worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
            shutil.copytree(project_folder, worker_folder)
            
            worker_ras_instance = RasPrj()
            worker_ras_instance = init_ras_project(
                ras_project_folder=worker_folder,
                ras_version=ras_obj.ras_exe_path,
                ras_instance=worker_ras_instance
            )
            worker_ras_objects[worker_id] = worker_ras_instance

        # Prepare plan queue with plan numbers
        plan_queue = queue.Queue()
        for plan_number in ras_obj.plan_df['plan_number']:
            plan_queue.put(plan_number)

        # Initialize results dictionary and thread locks
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
                    plan_path = RasPlan.get_plan_path(plan_number, ras_object=worker_ras_obj)
                    if not plan_path:
                        raise FileNotFoundError(f"Plan file not found: {plan_number}")

                    RasPlan.set_num_cores(plan_number, cores_per_run, ras_object=worker_ras_obj)

                    print(f"Worker {worker_id} executing plan {plan_number}")

                    success = RasCommander.compute_plan(plan_number, ras_object=worker_ras_obj)

                    with results_lock:
                        execution_results[plan_number] = success
                    print(f"Completed: Plan {plan_number} in worker {worker_id}")
                except Exception as e:
                    with results_lock:
                        execution_results[plan_number] = False
                    print(f"Failed: Plan {plan_number} in worker {worker_id}. Error: {str(e)}")

        # Start worker threads
        worker_threads = []
        for worker_id in range(1, max_workers + 1):
            worker_ras_instance = worker_ras_objects[worker_id]
            worker_ras_instance.plan_df = worker_ras_instance.get_plan_entries()
            worker_ras_instance.geom_df = worker_ras_instance.get_geom_entries()
            worker_ras_instance.flow_df = worker_ras_instance.get_flow_entries()
            worker_ras_instance.unsteady_df = worker_ras_instance.get_unsteady_entries()
            
            thread = Thread(target=worker_thread, args=(worker_id,))
            thread.start()
            worker_threads.append(thread)
            print(f"Started worker thread {worker_id}")

        # Wait for all threads to complete
        for worker_id, thread in enumerate(worker_threads, 1):
            thread.join()
            print(f"Worker thread {worker_id} has completed.")

        # Consolidate results
        final_dest_folder = dest_folder_path if dest_folder is not None else project_folder.parent / f"{project_folder.name} [Computed]"
        final_dest_folder.mkdir(exist_ok=True)
        print(f"Final destination for computed results: {final_dest_folder}")

        for worker_id, worker_ras in worker_ras_objects.items():
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
                print(f"Moved results and removed worker folder: {worker_folder}")
            except Exception as e:
                print(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

        # Print execution results for each plan
        print("\nExecution Results:")
        for plan_number, success in execution_results.items():
            print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")

        return execution_results