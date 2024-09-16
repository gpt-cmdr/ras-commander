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
# 4. The RasCommander class provides various arguments for fine-tuning plan computation:
#    - plan_numbers: List of plan numbers to compute (e.g., ["01", "02"])
#    - folder_suffix: String to append to the computation folder name
#    - clear_geompre: Boolean to clear geometry preprocessor files before computation
#    - max_cores: Integer specifying the maximum number of cores to use
#    - max_workers: Integer specifying the maximum number of parallel workers (for parallel execution)
#    - cores_per_run: Integer specifying the number of cores to use per run (for parallel execution)
#    - dest_folder: Path object specifying the destination folder for computation results

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. Utilize the various arguments in compute functions to customize plan execution.
# 5. Always consider your system's capabilities when setting max_cores and max_workers.
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

    # Example 1: Sequential execution with various arguments
    print("Example 1: Sequential execution with various arguments")
    RasCommander.compute_test_mode(
        plan_numbers=["01", "02"],
        folder_suffix="[SequentialWithArgs]",
        clear_geompre=True,
        max_cores=2
    )
    print("Sequential execution completed")
    print()

    # Example 2: Parallel execution with various arguments
    print("Example 2: Parallel execution with various arguments")
    results = RasCommander.compute_parallel(
        plan_numbers=["01", "02"],
        max_workers=2,
        cores_per_run=2,
        dest_folder=project_path.parent / "parallel_results",
        clear_geompre=True
    )
    print("Parallel execution results:")
    for plan_number, success in results.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 3: Single plan execution with specific arguments
    print("Example 3: Single plan execution with specific arguments")
    success = RasCommander.compute_plan(
        "03",
        compute_folder=project_path.parent / "single_plan_result",
        clear_geompre=True
    )
    print(f"Single plan execution: {'Successful' if success else 'Failed'}")

if __name__ == "__main__":
    main()





