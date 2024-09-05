"""
Execution operations for HEC-RAS simulations.
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

class RasExecutor:

    @staticmethod
    def compute_hecras_plan(plan_file):
        config = ProjectConfig()
        config.check_initialized()
        
        cmd = f'"{config.hecras_exe_path}" -c "{config.project_file}" "{plan_file}"'
        print(f"Running command: {cmd}")
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
            logging.info(f"HEC-RAS execution completed for plan: {os.path.basename(plan_file)}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running plan: {os.path.basename(plan_file)}")
            logging.error(f"Error message: {e.output}")
            return False
        
        
    @staticmethod
    def compute_hecras_plan_from_folder(test_plan_file, test_folder_path):
        # Config is only used to get the hecras_exe_path, the other paths are derived from test_plan_file and test_folder_path
        # This funciton allows us to run a plan directly from a different folder than the project folder (useful for the -test function and parallel runs)
        config = ProjectConfig()
        config.check_initialized()
        test_project_file = FileOperations.find_hecras_project_file(test_folder_path)
        cmd = f'"{config.hecras_exe_path}" -c "{test_project_file}" "{test_plan_file}"'
        print(f"Running command: {cmd}")
        try:
            subprocess.run(cmd, check=True, shell=True, capture_output=True, text=True)
            logging.info(f"HEC-RAS execution completed for plan: {os.path.basename(test_plan_file)}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running plan: {os.path.basename(plan_file)}")
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
        """
        print("Starting the recreate_test_function...")

        # Create the test folder path
        test_folder='[Test]'
        test_folder_path = Path(project_folder).parent / f"{Path(project_folder).name} {test_folder}"
        print(f"Creating the test folder: {test_folder_path}...")

        # Copy the project folder to the test folder
        print("Copying project folder to the test folder...")
        shutil.copytree(project_folder, test_folder_path, dirs_exist_ok=True)
        print(f"Test folder created at: {test_folder_path}")

        # Find the project file
        print("Finding the project file...")
        test_project_file = FileOperations.find_hecras_project_file(test_folder_path)

        if not test_project_file:
            print("Project file not found.")
            return
        print(f"Project file found: {test_project_file}")

        # Parse the project file to get plan entries
        print("Parsing the project file to get plan entries...")
        ras_plan_entries = FileOperations.get_plan_entries(test_project_file)
        print("Parsed project file successfully.")

        # Enforce recomputing of geometry preprocessor and IB tables
        print("Enforcing recomputing of geometry preprocessor and IB tables...")
        for plan_file in ras_plan_entries['full_path']:
            PlanOperations.update_geompre_flags(plan_file, run_htab_value=-1, use_ib_tables_value=-1)
        print("Recomputing enforced successfully.")

        # Change max cores to 1
        print("Changing max cores to 2 for all plan files...")
        for plan_file in ras_plan_entries['full_path']:
            PlanOperations.set_num_cores(plan_file, num_cores=2)
        print("Max cores updated successfully.")

        # Run all plans sequentially
        print("Running all plans sequentially...")
        for _, plan in ras_plan_entries.iterrows():
            RasExecutor.compute_hecras_plan_from_folder(plan["full_path"], test_folder_path)

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
        """
        project_folder = Path(config.project_file).parent
        test_folders = []

        # Create multiple copies of the project folder
        for i in range(1, max_workers + 1):
            test_folder_path = project_folder.parent / f"{project_folder.name} [Test {i}]"
            shutil.copytree(project_folder, test_folder_path, dirs_exist_ok=True)
            test_folders.append(test_folder_path)
            print(f"Created test folder: {test_folder_path}")

        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_plan = {}
            for i, (_, plan_row) in enumerate(config.ras_plan_entries.iterrows()):
                test_folder_path = test_folders[i % max_workers]
                plan_file = test_folder_path / Path(plan_row['full_path']).name
                project_file_copy = test_folder_path / Path(config.project_file).name

                # Update the plan file to use the specified number of cores
                PlanOperations.set_num_cores(str(plan_file), cores_per_run)

                future = executor.submit(
                    RasExecutor.compute_hecras_plan,
                    plan_file
                )
                future_to_plan[future] = plan_row['plan_number']

            for future in as_completed(future_to_plan):
                plan_number = future_to_plan[future]
                try:
                    success = future.result()
                    results[plan_number] = success
                    print(f"Completed: Plan {plan_number}")
                except Exception as e:
                    results[plan_number] = False
                    print(f"Failed: Plan {plan_number}. Error: {str(e)}")

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