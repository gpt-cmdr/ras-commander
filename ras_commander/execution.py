"""
Execution operations for runningHEC-RAS simulations using subprocess.
Based on the HEC-Commander project's "Command Line is All You Need" approach, leveraging the -c compute flag to run HEC-RAS and orchestrating changes directly in the RAS input files to achieve automation outcomes. 
"""

import os
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from .file_operations import FileOperations
from .plan_operations import PlanOperations
import subprocess
import os
import logging
import time
from .project_config import ProjectConfig
import pandas as pd

class RasExecutor:

    @staticmethod
    def compute_hecras_plan(compute_plan_file):
        """
        Compute a HEC-RAS plan using the provided plan file.

        This method executes a HEC-RAS plan by running the HEC-RAS executable
        with the specified plan file. It uses the plan file's path to determine
        the corresponding project file path.

        Args:
            compute_plan_file (str): The full path to the HEC-RAS plan file (.p**)

        Returns:
            bool: True if the plan computation was successful, False otherwise.

        Raises:
            subprocess.CalledProcessError: If the HEC-RAS execution fails.

        Note:
            This method assumes that the project file (.prj) is in the same
            directory as the plan file and has the same name (different extension).
        """
        config = ProjectConfig()
        config.check_initialized()

        # Derive the project file path from the plan file path
        compute_project_file = Path(compute_plan_file).with_suffix('.prj')

        cmd = f'"{config.hecras_exe_path}" -c "{compute_project_file}" "{compute_plan_file}"'
        print(f"Running command: {cmd}")
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
            logging.info(f"HEC-RAS execution completed for plan: {Path(compute_plan_file).name}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running plan: {Path(compute_plan_file).name}")
            logging.error(f"Error message: {e.output}")
            return False
        
        
    @staticmethod
    def compute_hecras_plan_from_folder(plan_for_compute, folder_for_compute):
        """
        Compute a HEC-RAS plan from a specified folder.

        This function allows running a plan directly from a different folder than the project folder,
        which is useful for the -test function and parallel runs. It uses the HEC-RAS executable path
        from the ProjectConfig, but derives other paths from the provided arguments.

        Args:
            plan_for_compute (str): The full path to the HEC-RAS plan file (.p**) to be computed.
            folder_for_compute (str): The folder containing the HEC-RAS project files.

        Returns:
            bool: True if the plan computation was successful, False otherwise.

        Raises:
            subprocess.CalledProcessError: If the HEC-RAS execution fails.

        Note:
            This function uses the ProjectConfig only to get the hecras_exe_path.
            Other paths are derived from plan_for_compute and folder_for_compute.
        """
        config = ProjectConfig()
        config.check_initialized()
        compute_project_file = FileOperations.find_hecras_project_file(folder_for_compute)
        cmd = f'"{config.hecras_exe_path}" -c "{compute_project_file}" "{plan_for_compute}"'
        print(f"Running command: {cmd}")
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
            logging.info(f"HEC-RAS execution completed for plan: {Path(plan_for_compute).name}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running plan: {Path(plan_for_compute).name}")
            logging.error(f"Error message: {e.output}")
            return False 


    @staticmethod
    def recreate_test_function(project_folder):
        """
        Recreate the -test function of HEC-RAS command line.
        
        Parameters:
        project_folder (str): Path to the HEC-RAS project folder
        
        Returns:
        None
        
        
        This function executes all ras plans in a separate folder defined by compute_folder='[Test]', so we need to call the individual functions and use distinct variable names
        For this function, we are using "compute" in the varable names as these are the values used for the compute operations in a separate copy of the ras project folder
     
        """
        print("Starting the recreate_test_function...")

        # Create the test folder path
        compute_folder='[Test]'
        folder_for_compute = Path(project_folder).parent / f"{Path(project_folder).name} {compute_folder}"
        print(f"Creating the test folder: {folder_for_compute}...")

        # Copy the project folder to the test folder
        print("Copying project folder to the test folder...")
        shutil.copytree(project_folder, folder_for_compute, dirs_exist_ok=True)
        print(f"Test folder created at: {folder_for_compute}")

        # Find the project file
        print("Finding the project file...")
        compute_project_file = FileOperations.find_hecras_project_file(folder_for_compute)

        if not compute_project_file:
            print("Project file not found.")
            return
        print(f"Project file found: {compute_project_file}")

        # Parse the project file to get plan entries
        print("Parsing the project file to get plan entries...")
        ras_compute_plan_entries = FileOperations.get_plan_entries(compute_project_file)
        print("Parsed project file successfully.")

        # Enforce recomputing of geometry preprocessor and IB tables
        print("Enforcing recomputing of geometry preprocessor and IB tables...")
        for plan_file in ras_compute_plan_entries['full_path']:
            PlanOperations.update_geompre_flags(plan_file, run_htab_value=-1, use_ib_tables_value=-1)
        print("Recomputing enforced successfully.")

        # Change max cores to 1
        print("Changing max cores to 2 for all plan files...")
        for plan_file in ras_compute_plan_entries['full_path']:
            PlanOperations.set_num_cores(plan_file, num_cores=2)
        print("Max cores updated successfully.")

        # Run all plans sequentially
        print("Running all plans sequentially...")
        for _, plan in ras_compute_plan_entries.iterrows():
            plan_for_compute = plan["full_path"]
            RasExecutor.compute_hecras_plan_from_folder(plan_for_compute, folder_for_compute)

        print("All plans have been executed.")
        print("recreate_test_function completed.")
        
    @staticmethod    
    def run_plans_parallel(config, max_workers, cores_per_run):
        """
        Run HEC-RAS plans in parallel using ThreadPoolExecutor.
        
        Parameters:
        config (ProjectConfig): Configuration object containing project information
        max_workers (int): Maximum number of parallel runs
        cores_per_run (int): Number of cores to use per run
        
        Returns:
        dict: Dictionary with plan numbers as keys and execution success as values
        
        This function executes all ras plans in separate folders defined by the max_workers and the numbering of the test folders [Test 1], [Test 2], etc. 
        Each worker operates sequentially on its assigned folder while all workers operate in parallel.
     
        Revisions:
        1. Created a pandas DataFrame to map each folder to a plan for execution.
        2. Implemented logic to assign worker numbers and compute folders.
        3. Used find_hecras_project_file function to get the full path of project files.
        4. Updated plan file paths to use compute folders.
        5. Revised the parallel execution to use separate threads for each worker.
        6. Implemented a queue system for each worker to handle plans sequentially.
        7. Updated the cleanup process to use the new folder structure.
        """
        import queue
        from threading import Thread

        project_folder = Path(config.project_file).parent
        test_folders = []

        # Create multiple copies of the project folder
        for i in range(1, max_workers + 1):
            folder_for_compute = project_folder.parent / f"{project_folder.name} [Test {i}]"
            shutil.copytree(project_folder, folder_for_compute, dirs_exist_ok=True)
            test_folders.append(folder_for_compute)
            print(f"Created test folder: {folder_for_compute}")

        compute_parallel_entries = []
        for i, (_, plan_row) in enumerate(config.ras_plan_entries.iterrows()):
            worker_number = i % max_workers
            compute_folder = test_folders[worker_number]
            compute_project_file = FileOperations.find_hecras_project_file(compute_folder)
            compute_plan_file = compute_folder / Path(plan_row['full_path']).name
            compute_parallel_entries.append({
                'worker_number': worker_number,
                'compute_folder': compute_folder,
                'compute_project_file': compute_project_file,
                'compute_plan_file': compute_plan_file,
                'plan_number': plan_row['plan_number']
            })

        compute_parallel_df = pd.DataFrame(compute_parallel_entries)
        print("compute_parallel_entries dataframe:")
        display(compute_parallel_df)

        results = {}
        worker_queues = [queue.Queue() for _ in range(max_workers)]

        def worker_thread(worker_id):
            """
            Execute HEC-RAS plans assigned to a specific worker thread.

            This function continuously processes plans from the worker's queue until it's empty.
            It sets the number of cores for each plan, computes the plan, and records the result.

            Parameters:
            worker_id (int): The ID of the worker thread.

            Notes:
            - Uses PlanOperations.set_num_cores to set the number of cores for each plan.
            - Uses RasExecutor.compute_hecras_plan to execute each plan.
            - Records success or failure in the 'results' dictionary.
            - Prints status messages for completed or failed plans.
            """
            while True:
                try:
                    row = worker_queues[worker_id].get(block=False)
                    PlanOperations.set_num_cores(str(row['compute_plan_file']), cores_per_run)
                    success = RasExecutor.compute_hecras_plan(row['compute_plan_file'])
                    results[row['plan_number']] = success
                    print(f"Completed: Plan {row['plan_number']} in worker {worker_id}")
                except queue.Empty:
                    break
                except Exception as e:
                    results[row['plan_number']] = False
                    print(f"Failed: Plan {row['plan_number']} in worker {worker_id}. Error: {str(e)}")

        # Distribute plans to worker queues
        for _, row in compute_parallel_df.iterrows():
            worker_queues[row['worker_number']].put(row)

        # Start worker threads
        threads = []
        for i in range(max_workers):
            thread = Thread(target=worker_thread, args=(i,))
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Clean up and consolidate results
        time.sleep(3)  # Allow files to close
        final_test_folder = project_folder.parent / f"{project_folder.name} [Test]"
        final_test_folder.mkdir(exist_ok=True)
        
        for test_folder in test_folders:
            for item in test_folder.iterdir():
                dest_path = final_test_folder / item.name
                if dest_path.exists():
                    if dest_path.is_dir():
                        shutil.rmtree(dest_path)
                    else:
                        dest_path.unlink()
                shutil.move(str(item), final_test_folder)
            shutil.rmtree(test_folder)
            print(f"Moved and removed test folder: {test_folder}")

        return results
    
    @staticmethod    
    def run_all_plans_parallel(project_folder, hecras_exe_path):
        """
        Run all plans in a project folder in parallel.
        
        Parameters:
        project_folder (str): The path to the project folder.
        hecras_exe_path (str): The path to the HEC-RAS executable.
        
        Returns:
        dict: A dictionary with plan numbers as keys and execution success status as values.
        """
        config = ProjectConfig.init_ras_project(project_folder, hecras_exe_path)
        
        if config:
            print("ras_plan_entries dataframe:")
            display(config.ras_plan_entries)
            
            max_workers = 2  # Number of parallel runs
            cores_per_run = 2  # Number of cores per run
            
            results = RasExecutor.run_plans_parallel(config, max_workers, cores_per_run)
            
            print("\nExecution Results:")
            for plan_number, success in results.items():
                print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
            
            return results
        else:
            print("Failed to initialize project configuration.")
            return None