# 03_geometry_operations.py

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
ras_examples.extract_project(["Muncie"])

#### --- START OF SCRIPT --- ####

# RAS Commander Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.
# 4. The RasGeo class provides methods for working with geometry files and preprocessor operations.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. Always clear geometry preprocessor files before making significant changes to ensure clean results.

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Muncie"
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

    # Step 2: Clone a geometry file and assign it to the cloned plan
    print("Step 2: Cloning a geometry file and assigning it to the cloned plan")
    new_geom_number = RasPlan.clone_geom("01")
    print(f"New geometry created: {new_geom_number}")
    print(f"Now set the new geometry to the new plan")
    RasPlan.set_geom(new_plan_number, new_geom_number)
    print(f"New geometry {new_geom_number} assigned to plan {new_plan_number}")
    print("Updated geometry files:")
    print(ras.geom_df)
    print()

    # Step 3: Clear geometry preprocessor files for the cloned plan
    print("Step 3: Clearing geometry preprocessor files for the cloned plan")
    plan_path = RasPlan.get_plan_path(new_plan_number)
    RasGeo.clear_geompre_files(plan_path)
    print(f"Cleared geometry preprocessor files for plan {new_plan_number}")
    print()

    # Step 4: Clear geometry preprocessor files for all plans
    print("Step 4: Clearing geometry preprocessor files for all plans")
    RasGeo.clear_geompre_files()
    print("Cleared geometry preprocessor files for all plans")
    print()

    # Step 5: Print the updated plan information
    print("Step 5: Updated plan information")
    plan_df = ras.get_plan_entries()
    print(plan_df)
    print()

    # Step 6: Compute the cloned plan with new geometry and core count
    print("Step 6: Computing the cloned plan")
    success = RasCmdr.compute_plan(new_plan_number)
    print(f"Computing plan {new_plan_number}")
    if success:
        print(f"Plan {new_plan_number} computed successfully")
    else:
        print(f"Failed to compute plan {new_plan_number}")
        
    # Step 7: Get and print results paths
    print("\nStep 7: Getting results paths")
    for plan_number in [new_plan_number, "01"]:  # Check both the new plan and the original plan
        results_path = RasPlan.get_results_path(plan_number)
        if results_path:
            print(f"Results for plan {plan_number} are located at: {results_path}")
        else:
            print(f"No results found for plan {plan_number}")
        

if __name__ == "__main__":
    main()