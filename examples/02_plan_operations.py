# 02_plan_operations.py

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

"""
This script demonstrates the process of initializing a HEC-RAS project and performing various operations on plans, geometries, and unsteady flows using the functions within the RasPlan Class.

Process Flow:
1. Project Initialization: Initialize a HEC-RAS project by specifying the project path and version.
2. Plan Cloning: Clone an existing plan, creating a new plan entry.
3. Geometry Cloning: Clone a geometry associated with the original plan, generating a new geometry entry.
4. Unsteady Flow Cloning: Clone an unsteady flow, creating a new unsteady flow entry.
5. Plan Configuration:
   a. Set the cloned geometry for the new plan.
   b. Set the cloned unsteady flow for the new plan.
   c. Update the number of cores to be used for the new plan.
   d. Configure geometry preprocessor options for the new plan.
6. Plan Computation: Compute the new plan and verify successful execution.
7. Results Verification: Check the HDF entries to confirm that results were written.

Additional operations that could be demonstrated:
8. Plan Modification: Update specific parameters in the plan file (e.g., simulation time, output intervals).
9. Geometry Editing: Modify cross-sections, manning's n values, or other geometry data.
10. Unsteady Flow Modification: Adjust boundary conditions or initial conditions.
11. Batch Operations: Perform operations on multiple plans simultaneously.
12. Error Handling: Demonstrate how to handle and report errors during plan operations.
13. Results Analysis: Extract and analyze key output values from the computed plan.
"""

# RAS Commander Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.

def main():
    # Initialize the project
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
    
    # Step 2: Clone a geometry
    print("Step 2: Cloning a geometry")
    new_geo_number = RasPlan.clone_geom("01")
    print(f"New geometry created: {new_geo_number}")
    print("Updated geometry files:")
    print(ras.geom_df)
    print()
    
    # Step 3: Clone an unsteady flow
    print("Step 3: Cloning an unsteady flow")
    new_unsteady_number = RasPlan.clone_unsteady("02")
    print(f"New unsteady flow created: {new_unsteady_number}")
    print("Updated unsteady flow files:")
    print(ras.unsteady_df)
    print()

    # Step 4: Set geometry for the cloned plan
    print("Step 4: Setting geometry for a plan")
    RasPlan.set_geom(new_plan_number, new_geo_number)
    plan_path = RasPlan.get_plan_path(new_plan_number)
    print(f"Updated geometry for plan {new_plan_number}")
    print(f"Plan file path: {plan_path}")
    print()

    # Step 5: Set unsteady flow for the cloned plan
    print("Step 5: Setting unsteady flow for a plan")
    RasPlan.set_unsteady(new_plan_number, new_unsteady_number)
    print(f"Updated unsteady flow for plan {new_plan_number}")
    print()

    # Step 6: Set the number of cores for the cloned plan
    print("Step 6: Setting the number of cores for a plan")
    RasPlan.set_num_cores(new_plan_number, 2)
    print(f"Updated number of cores for plan {new_plan_number}")
    print()

    # Step 7: Set geometry preprocessor options for the cloned plan
    print("Step 7: Setting geometry preprocessor options")
    RasPlan.set_geom_preprocessor(plan_path, run_htab=-1, use_ib_tables=-1)
    print(f"Updated geometry preprocessor options for plan {new_plan_number}")
    
    # Step 8: Compute the cloned plan
    print("Step 8: Computing the cloned plan")
    success = RasCmdr.compute_plan(new_plan_number)
    print(f"Computing plan {new_plan_number}")
    if success:
        print(f"Plan {new_plan_number} computed successfully")
    else:
        print(f"Failed to compute plan {new_plan_number}")
    print()
    
    # Step 9: Get the HDF entries for the cloned plan to prove that the results were written
    print("Step 9: Retrieving HDF entries for the cloned plan")
    # Refresh the plan entries to ensure we have the latest data
    ras.plan_df = ras.get_plan_entries()
    hdf_entries = ras.get_hdf_entries()
    if not hdf_entries.empty:
        print("HDF entries for the cloned plan:")
        print(hdf_entries)
    else:
        print("No HDF entries found. This could mean the plan hasn't been computed successfully or the results haven't been written yet.")
    
    # Display the plan entries to see if the HDF path is populated
    print("\nCurrent plan entries:")
    print(ras.plan_df)
    
if __name__ == "__main__":
    main()