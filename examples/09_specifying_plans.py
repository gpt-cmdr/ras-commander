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

# Housekeeping Note: 
# For all of the functions that do batched execution (sequential or parallel), they are careful not to overwrite existing folders
# So if you want your script to be repeatable, you need to make sure you delete the folders before running again.
# Otherwise an error will be raised to prevent overwriting any results from your previous runs.
# This will not be done by the example projects routines, which only overwrite the source folder for repeatability. 
    
import shutil
from pathlib import Path

# Delete example projects folder
current_file = Path(__file__).resolve()
current_dir = current_file.parent
delete_folder_path = current_dir / "example_projects"

if delete_folder_path.exists():
    print(f"Removing existing folder: {delete_folder_path}")
    shutil.rmtree(delete_folder_path)
else:
    print(f"Folder not found: {delete_folder_path}")

# Extract specific projects
ras_examples = RasExamples()
ras_examples.extract_project(["Balde Eagle Creek"])

#### --- START OF SCRIPT --- ####

# RAS Commander (ras-commander) Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.
# 4. The RasCmdr class provides methods for executing plans in various ways.
# 5. You can specify individual plans or lists of plans for batch operations.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. When specifying plans, use plan numbers as strings (e.g., "01", "02") for consistency.
# 5. Always check the available plans in the project before specifying plan numbers for execution.

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Example 1: Sequential execution of specific plans
    print("Example 1: Sequential execution of specific plans (1 and 3)")
    RasCmdr.compute_test_mode(plan_number=["01", "03"], dest_folder_suffix="[SpecificSequential]", num_cores=6)
    print("Sequential execution of specific plans completed")
    print()

    # Example 2: Parallel execution of specific plans
    print("Example 2: Parallel execution of specific plans")
    results_specific = RasCmdr.compute_parallel(
        plan_number=["01", "02"],
        max_workers=2,
        num_cores=2
    )
    print("Parallel execution of specific plans results:")
    for plan_number, success in results_specific.items():
        print(f"Plan {plan_number}: {'Successful' if success else 'Failed'}")
    print()

    # Example 3: Execute all plans
    print("Example 3: Execute all plans")
    all_plan_numbers = ras.plan_df['plan_number'].tolist()
    RasCmdr.compute_test_mode(plan_number=all_plan_numbers, dest_folder_suffix="[AllPlans]")
    print("Execution of all plans completed")
    print()

if __name__ == "__main__":
    main()
