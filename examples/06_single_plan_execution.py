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

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.

def main():
    # Initialize the project using the global 'ras' object
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Example 1: Execute a single plan
    print("Example 1: Executing a single plan")
    plan_number = "01"
    success = RasCommander.compute_plan(plan_number)
    if success:
        print(f"Plan {plan_number} executed successfully")
    else:
        print(f"Plan {plan_number} execution failed")
    print()

    # Example 2: Execute a plan in a separate compute folder
    print("Example 2: Executing a plan in a separate compute folder")
    plan_number = "02"
    compute_folder = project_path.parent / "compute_test"
    success = RasCommander.compute_plan(plan_number, compute_folder=compute_folder)
    if success:
        print(f"Plan {plan_number} executed successfully in {compute_folder}")
    else:
        print(f"Plan {plan_number} execution failed in {compute_folder}")
    print()

    # Example 3: Get and print results path
    print("Example 3: Getting results path")
    results_path = RasPlan.get_results_path(plan_number)
    if results_path:
        print(f"Results for plan {plan_number} are located at: {results_path}")
    else:
        print(f"No results found for plan {plan_number}")

if __name__ == "__main__":
    main()