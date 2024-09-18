#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
from pathlib import Path

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

# Extract specific projects
ras_examples = RasExamples()
ras_examples.extract_project(["Balde Eagle Creek"])

#### --- START OF SCRIPT --- ####

# RAS Commander Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.
# 4. The RasCmdr class provides various arguments for fine-tuning plan computation:
#    - plan_number: String representing the plan number to compute (e.g., "01")
#    - dest_folder: Path object specifying the destination folder for computation results
#    - clear_geompre: Boolean to clear geometry preprocessor files before computation
#    - num_cores: Integer specifying the number of cores to use
#    - overwrite_dest: Boolean to determine if existing destination folders should be overwritten

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. Utilize the various arguments in compute functions to customize plan execution.
# 5. Always consider your system's capabilities when setting num_cores.
# 6. Use clear_geompre=True when you want to ensure a clean computation environment.
# 7. Specify dest_folder to keep your project folder organized and prevent overwriting previous results.

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Example 1: Sequential execution (compute_test_mode) with various arguments
    print("Example 1: Sequential execution with various arguments")
    for plan_number in ["01", "02"]:
        # Put dest_folder in the parent directory of the project folder (placing it horizontally with the project folder)
        # Test mode only allows dest_folder_suffix, and always creates a copy in the project folder's parent directory. 
        # So instead of building the full folder name or path, we only define the suffix. 
        dest_folder_suffix = f"_{plan_number}_[SequentialWithArgs]"
        success = RasCmdr.compute_test_mode(
            plan_number=plan_number,
            dest_folder_suffix=dest_folder_suffix,  # Test mode only allows dest_folder_suffix, and always creates a copy in the project folder's parent directory
            clear_geompre=True,
            num_cores=2,
            overwrite_dest=True
        )
        print(f"Plan {plan_number} execution: {'Successful' if success else 'Failed'}")
    print("Sequential execution completed")
    print()
    
    # This variation will fail, as the folder already exists and overwrite_dest is False.  
    # Be sure to think step by step about folder management in your multi-folder automation workflows:
    # Also, try to run the same thing with compute_parallel, but with overwrite_dest=False
    # Since we just created these folders, they are not empty, so this should generate an error message on the terminal
    # Put in Try-Except block:
    try:
        dest_folder = project_path.parent / f"{ras.project_name}_compute_test_01_[SequentialWithArgs]"
        success = RasCmdr.compute_test_mode(
            plan_number="01",
            dest_folder_suffix=dest_folder_suffix,
            clear_geompre=True,
            num_cores=2,
            overwrite_dest=False
        )
    except ValueError as e:
        print(f"If the example operates successfully (it is meant to generate an error above), you will not see this message.")

    # Example 2: Parallel execution (compute_parallel) with various arguments
    print("Example 2: Parallel execution with various arguments")
    results = RasCmdr.compute_parallel(
        plan_number=["01", "02"],
        max_workers=2,
        num_cores=2,
        dest_folder=project_path.parent / "parallel_results",
        clear_geompre=True
    )
    print("Parallel execution results:")
    for plan_number, success in results.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 3: Single plan execution (compute_plan) with specific arguments
    print("Example 3: Single plan execution with specific arguments")
    plan_number = "02"
    dest_folder = project_path.parent / "compute_test_2"
    success = RasCmdr.compute_plan(plan_number, dest_folder=dest_folder, num_cores=2, clear_geompre=True, overwrite_dest=True)
    print(f"Single plan execution: {'Successful' if success else 'Failed'}")

if __name__ == "__main__":
    main()
