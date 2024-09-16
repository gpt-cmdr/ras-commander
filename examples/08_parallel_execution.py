#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
from pathlib import Path
import shutil

# Add the parent directory to the Python path
current_file = Path(__file__).resolve()
parent_directory = current_file.parent.parent
sys.path.append(str(parent_directory))

# Flexible imports to allow for development without installation
try:
    # Try to import from the installed package
    from ras_commander import init_ras_project, RasExamples, RasCommander, RasPlan, RasGeo, RasUnsteady, RasUtils, ras
except ImportError:
    # If the import fails, add the parent directory to the Python path
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    
    # Now try to import again
    from ras_commander import init_ras_project, RasExamples, RasCommander, RasPlan, RasGeo, RasUnsteady, RasUtils, ras

# Extract specific projects
ras_examples = RasExamples()
ras_examples.extract_project(["Balde Eagle Creek"])

#### --- START OF SCRIPT --- ####

# RAS-Commander Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.
# 4. For functions that do batched execution (sequential or parallel), they are careful not to overwrite existing folders.
# 5. If you want your script to be repeatable, make sure to delete the folders before running again.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. When using parallel execution, consider the number of cores available on your machine.
# 5. Use the dest_folder argument to keep your project folder clean and organized.

def main():
    # Initialize the project using the global 'ras' object
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Housekeeping: Remove existing compute folders if they exist
    compute_folder = project_path.parent / "compute_test_parallel"
    if compute_folder.exists():
        print(f"Removing existing folder: {compute_folder}")
        shutil.rmtree(compute_folder)
    
    # Example 1: Parallel execution of all plans
    print("Example 1: Parallel execution of all plans")
    results_all = RasCommander.compute_parallel(max_workers=3, cores_per_run=2, dest_folder=compute_folder)
    print("Parallel execution of all plans results:")
    for plan_number, success in results_all.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()
    
    # Example 2: Parallel execution of specific plans
    print("Example 2: Parallel execution of specific plans")
    specific_plans = ["01", "02"]
    specific_compute_folder = compute_folder / "specific_plans"
    if specific_compute_folder.exists():
        print(f"Removing existing folder: {specific_compute_folder}")
        shutil.rmtree(specific_compute_folder)
    results_specific = RasCommander.compute_parallel(
        plan_numbers=specific_plans,
        max_workers=2,
        cores_per_run=2,
        dest_folder=specific_compute_folder
    )
    print("Parallel execution of specific plans results:")
    for plan_number, success in results_specific.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 3: Get and print results paths
    print("Example 3: Getting results paths")
    for plan_number in specific_plans:
        results_path = RasPlan.get_results_path(plan_number)
        if results_path:
            print(f"Results for plan {plan_number} are located at: {results_path}")
        else:
            print(f"No results found for plan {plan_number}")

if __name__ == "__main__":
    main()