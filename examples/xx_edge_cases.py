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
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, ras
except ImportError:
    # If the import fails, add the parent directory to the Python path
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    
    # Now try to import again
    from ras_commander import init_ras_project, RasExamples, RasCmdr, RasPlan, RasGeo, RasUnsteady, RasUtils, ras

example_projects_folder = Path(__file__).parent.parent / "example_projects"

# delete the folder if it exists
if example_projects_folder.exists():
    shutil.rmtree(example_projects_folder)


# Extract specific projects
ras_examples = RasExamples()
ras_examples.extract_project(["Balde Eagle Creek"])

#### --- START OF SCRIPT --- ####

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Example 1: Execute a single plan using compute_test_mode
    print("Example 1: Executing a single plan using compute_test_mode")
    single_plan = "01"
    dest_folder_suffix = "[SinglePlanTest]"
    compute_folder = project_path.parent / f"{project_path.name} {dest_folder_suffix}"
    
    # Delete the compute folder if it exists
    if compute_folder.exists():
        shutil.rmtree(compute_folder)
        print(f"Deleted existing compute folder: {compute_folder}")

    RasCmdr.compute_test_mode(
        plan_number=single_plan,
        dest_folder_suffix=dest_folder_suffix,
        clear_geompre=False,
        num_cores=2
    )
    print(f"Execution of plan {single_plan} completed using compute_test_mode")
    print()

    # Example 2: Execute a single plan using compute_parallel
    print("Example 2: Executing a single plan using compute_parallel")
    parallel_result_folder = project_path.parent / "parallel_single_plan_result"
    if parallel_result_folder.exists():
        shutil.rmtree(parallel_result_folder)
        print(f"Deleted existing result folder: {parallel_result_folder}")

    results = RasCmdr.compute_parallel(
        plan_number=single_plan,
        max_workers=1,
        num_cores=2,
        dest_folder=parallel_result_folder
    )
    print("Parallel execution of single plan results:")
    for plan_number, success in results.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 3: Execute a single plan using compute_test_mode with a string input
    print("Example 3: Executing a single plan using compute_test_mode with a string input")
    dest_folder_suffix = "[SinglePlanTestString]"
    compute_folder = project_path.parent / f"{project_path.name} {dest_folder_suffix}"
    
    # Delete the compute folder if it exists
    if compute_folder.exists():
        shutil.rmtree(compute_folder)
        print(f"Deleted existing compute folder: {compute_folder}")

    RasCmdr.compute_test_mode(
        plan_number="02",
        dest_folder_suffix=dest_folder_suffix,
        clear_geompre=False,
        num_cores=2
    )
    print("Execution of plan 02 completed using compute_test_mode with string input")
    print()

    # Example 4: Execute a single plan using compute_parallel with a string input
    print("Example 4: Executing a single plan using compute_parallel with a string input")
    parallel_result_folder = project_path.parent / "parallel_single_plan_string_result"
    if parallel_result_folder.exists():
        shutil.rmtree(parallel_result_folder)
        print(f"Deleted existing result folder: {parallel_result_folder}")

    results = RasCmdr.compute_parallel(
        plan_number="01",  # Changed from "03" to "01"
        max_workers=1,
        num_cores=2,
        dest_folder=parallel_result_folder
    )
    print("Parallel execution of single plan (string input) results:")
    for plan_number, success in results.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 5: Attempt to execute with an empty plan list
    print("Example 5: Attempting to execute with an empty plan list")
    dest_folder_suffix = "[EmptyPlanList]"
    compute_folder = project_path.parent / f"{project_path.name} {dest_folder_suffix}"
    
    if compute_folder.exists():
        shutil.rmtree(compute_folder)
        print(f"Deleted existing compute folder: {compute_folder}")

    try:
        RasCmdr.compute_test_mode(plan_number=[], dest_folder_suffix=dest_folder_suffix)
    except ValueError as e:
        print(f"Error caught: {e}")
    print()

    # Example 6: Attempt to execute with a non-existent plan number
    print("Example 6: Attempting to execute with a non-existent plan number")
    non_existent_plan = "99"
    dest_folder_suffix = "[NonExistentPlan]"
    compute_folder = project_path.parent / f"{project_path.name} {dest_folder_suffix}"
    
    if compute_folder.exists():
        shutil.rmtree(compute_folder)
        print(f"Deleted existing compute folder: {compute_folder}")

    try:
        RasCmdr.compute_test_mode(plan_number=non_existent_plan, dest_folder_suffix=dest_folder_suffix)
    except ValueError as e:
        print(f"Error caught: {e}")
    print()

if __name__ == "__main__":
    main()