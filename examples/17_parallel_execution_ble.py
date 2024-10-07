#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
from pathlib import Path
import shutil
import psutil
import math
import logging

# Add the parent directory to the Python path
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent
sys.path.append(str(parent_directory))

# Flexible imports to allow for development without installation
try:
    # Try to import from the installed package
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, RasPrj
except ImportError:
    # If the import fails, add the parent directory to the Python path
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    
    # Now try to import again
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, RasPrj

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    handlers=[
        logging.StreamHandler()  # Log to stderr
    ]
)

# Initialize RasExamples
ras_examples = RasExamples()

#### --- START OF SCRIPT --- ####

# ras-commander Library Notes:
# 1. This example uses separate RasPrj objects for each project/folder.
# 2. Using separate RasPrj objects allows working with multiple projects or folders.
# 3. We'll create new RasPrj objects for the original project and each output folder.
# 4. For functions that do batched execution (sequential or parallel), they are careful not to overwrite existing folders.
# 5. If you want your script to be repeatable, make sure to delete the folders before running again.

# Best Practices:
# 1. For complex scripts or when working with multiple projects/folders, create and use separate RasPrj objects.
# 2. Be consistent in your approach: use non-global RasPrj objects throughout the script.
# 3. When using parallel execution, consider the number of cores available on your machine.
# 4. Use the dest_folder argument to keep your project folder clean and organized.

##  WHISKY CHITTO DOES NOT WORK - BLE MODEL IS BROKEN AND REQUIRED FIXING BEFORE RUNNING

def get_physical_core_count():
    return psutil.cpu_count(logical=False)

def main():
    # Define paths
    current_dir = Path(__file__).parent
    csv_directory = current_dir / "FEMA_BLE_Models"
    csv_file = csv_directory / "08080204_WhiskyChitto_DownloadIndex.csv"
    
    # Download FEMA BLE Models (specifically WhiskyChitto)
    ras_examples.download_fema_ble_model(csv_file=csv_file)
    
    
    # Initialize the RasPrj object for WhiskyChitto
    project_path = csv_directory / "WhiskyChitto" / "HECRAS_Models" / "Model" / "Input"
    logging.info(f"Initializing RasPrj for project at: {project_path}")
    whisky_project = init_ras_project(project_path, "5.0.7")
    
    print("Available plans:")
    print(whisky_project.plan_df)
    print()
    
    # Example 1: Parallel execution of all plans with overwrite_dest
    print("Example 1: Parallel execution of all plans with overwrite_dest")
    compute_folder = project_path.parent / "compute_test_parallel_whisky"
    results_all = RasCmdr.compute_parallel(
        max_workers=2,
        num_cores=2,
        dest_folder=compute_folder,
        overwrite_dest=True,
        ras_object=whisky_project
    )
    print("Parallel execution of all plans results:")
    for plan_number, success in results_all.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()
    
    # Initialize a new RasPrj object for the compute_folder
    compute_source_project = init_ras_project(compute_folder, "6.6")
    print("Plan DataFrame after parallel execution of all plans:")
    print(compute_source_project.plan_df)
    print()
    
    # Example 2: Parallel execution of specific plans with overwrite_dest
    print("Example 2: Parallel execution of specific plans with overwrite_dest")
    specific_plans = ["01", "02"]
    specific_compute_folder = project_path.parent / "compute_test_parallel_specific_whisky"
    results_specific = RasCmdr.compute_parallel(
        plan_number=specific_plans,
        max_workers=2,
        num_cores=2,
        dest_folder=specific_compute_folder,
        overwrite_dest=True,
        ras_object=whisky_project
    )
    print("Parallel execution of specific plans results:")
    for plan_number, success in results_specific.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()
    
    # Example 3: Parallel execution with dynamic max_workers based on physical cores
    print("Example 3: Parallel execution with dynamic max_workers")
    num_cores = 2
    physical_cores = get_physical_core_count()
    max_workers = math.floor(physical_cores / num_cores) if num_cores > 0 else 1
    
    dynamic_compute_folder = project_path.parent / "compute_test_parallel_dynamic_whisky"
    results_dynamic = RasCmdr.compute_parallel(
        max_workers=max_workers,
        num_cores=num_cores,
        dest_folder=dynamic_compute_folder,
        overwrite_dest=True,
        ras_object=whisky_project
    )
    print(f"Parallel execution with {max_workers} workers and {num_cores} cores per worker:")
    for plan_number, success in results_dynamic.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()
    
    # Get and print results paths
    print("Results paths for dynamic execution:")
    dynamic_compute_source_project = init_ras_project(dynamic_compute_folder, "6.6")
    print(dynamic_compute_source_project.plan_df)

if __name__ == "__main__":
    main()

