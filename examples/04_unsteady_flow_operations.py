# 04_unsteady_flow_operations.py

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

    print("Initial plan files:")
    print(ras.plan_df)
    print()

    # Step 1: Clone a plan
    print("Step 1: Cloning a plan")
    new_plan_number = RasPlan.clone_plan("01")
    print(f"New plan created: {new_plan_number}")
    print("Updated plan files:")
    print(ras.plan_df)
    print()

    # Step 2: Get the plan file path
    plan_path = RasPlan.get_plan_path(new_plan_number)

    # Step 3: Update unsteady flow parameters individually
    print("Step 3: Updating unsteady flow parameters individually")
    RasUnsteady.update_unsteady_parameters(plan_path, {"Simulation Date": "01JAN2023,0000,05JAN2023,2400"})
    RasUnsteady.update_unsteady_parameters(plan_path, {"Computation Interval": "1MIN"})
    RasUnsteady.update_unsteady_parameters(plan_path, {"Output Interval": "15MIN"})
    print("Updated parameters individually")
    print()

    # Step 4: Update unsteady flow parameters in batch
    print("Step 4: Updating unsteady flow parameters in batch")
    batch_modifications = {
        "Mapping Interval": "30MIN",
        "Hydrograph Output Interval": "1HOUR",
        "Detailed Output Interval": "1HOUR"
    }
    RasUnsteady.update_unsteady_parameters(plan_path, batch_modifications)
    print("Updated parameters in batch")
    print()

    # Step 5: Verify changes
    print("Step 5: Verifying changes")
    with open(plan_path, 'r') as f:
        content = f.read()
        for param in ["Simulation Date", "Computation Interval", "Output Interval", 
                      "Mapping Interval", "Hydrograph Output Interval", "Detailed Output Interval"]:
            for line in content.split('\n'):
                if line.startswith(param):
                    print(f"Updated {line}")
                    break
    print()

    # Step 6: Compute the updated plan
    print("Step 6: Computing the updated plan")
    success = RasCommander.compute_plan(new_plan_number)
    if success:
        print(f"Plan {new_plan_number} computed successfully")
    else:
        print(f"Failed to compute plan {new_plan_number}")

if __name__ == "__main__":
    main()