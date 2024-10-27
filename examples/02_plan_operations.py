# 02_plan_operations.py

#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
from pathlib import Path
import datetime

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
6. Update Simulation Parameters: Modify various simulation parameters in the new plan.
7. Plan Computation: Compute the new plan and verify successful execution.
8. Results Verification: Check the HDF entries to confirm that results were written.
"""

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.6")

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
    print()

    # Step 8: Update simulation parameters
    print("Step 8: Updating simulation parameters")

    # Import the datetime module
    from datetime import datetime

    # Update simulation date
    start_date = datetime(2023, 1, 1, 0, 0)
    end_date = datetime(2023, 1, 5, 23, 59)
    RasPlan.update_simulation_date(new_plan_number, start_date, end_date)

    # Update plan intervals
    RasPlan.update_plan_intervals(
        new_plan_number,
        computation_interval="1MIN",
        output_interval="15MIN",
        mapping_interval="30MIN"
    )

    # Update run flags
    RasPlan.update_run_flags(
        new_plan_number,
        geometry_preprocessor=True,
        unsteady_flow_simulation=True,
        post_processor=True,
        floodplain_mapping=True
    )

    # Update plan description
    new_description = "Updated plan with modified simulation parameters"
    RasPlan.update_plan_description(new_plan_number, new_description)


    print("Updated simulation parameters")
    print()


    # Step 9: Compute the cloned plan
    print("Step 10: Computing the cloned plan")
    success = RasCmdr.compute_plan(new_plan_number)
    print(f"Computing plan {new_plan_number}")
    if success:
        print(f"Plan {new_plan_number} computed successfully")
    else:
        print(f"Failed to compute plan {new_plan_number}")
    print()
    
    # Step 11: Get the HDF entries for the cloned plan to prove that the results were written
    print("Step 11: Retrieving HDF entries for the cloned plan")
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
