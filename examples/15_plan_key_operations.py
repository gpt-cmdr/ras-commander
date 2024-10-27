# 15_plan_key_operations.py

#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
from pathlib import Path
from datetime import datetime, timedelta

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

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    ras_obj = init_ras_project(project_path, "6.6")

    print("Example 15: Plan Key Operations")
    print("------------------------------------------")

    # Get the first plan number
    plan_number = ras_obj.plan_df['plan_number'].iloc[0]
    print(f"Working with Plan: {plan_number}")

    # 1. Get and print initial plan values
    keys_to_check = ['Computation Interval', 'Simulation Date', 'Short Identifier', 'UNET D1 Cores']
    print("\n1. Initial Plan Values:")
    for key in keys_to_check:
        value = RasPlan.get_plan_value(plan_number, key, ras_object=ras_obj)
        print(f"  {key}: {value}")

    # 2. Update run flags
    print("\n2. Updating Run Flags:")
    RasPlan.update_run_flags(
        plan_number,
        geometry_preprocessor=True,
        unsteady_flow_simulation=True,
        run_sediment=False,
        post_processor=True,
        floodplain_mapping=False,
        ras_object=ras_obj
    )
    print("  Run flags updated.")

    # 3. Update plan intervals
    print("\n3. Updating Plan Intervals:")
    RasPlan.update_plan_intervals(
        plan_number,
        computation_interval="5SEC",
        output_interval="1MIN",
        instantaneous_interval="5MIN",
        mapping_interval="15MIN",
        ras_object=ras_obj
    )
    print("  Plan intervals updated.")

    # 4. Update plan description
    
    print("\n4. Current Plan Description:")
    current_description = RasPlan.read_plan_description(plan_number, ras_object=ras_obj)
    print(f"  {current_description}")    
    print("\n4. Updating Plan Description:")
    new_description = "This is an updated plan description for testing purposes."
    RasPlan.update_plan_description(plan_number, new_description, ras_object=ras_obj)
    print("  Plan description updated.")

    # 5. Update simulation date
    print("\n5. Updating Simulation Date:")
    start_date = datetime.now()
    end_date = start_date + timedelta(days=1)
    RasPlan.update_simulation_date(plan_number, start_date, end_date, ras_object=ras_obj)
    print(f"  Simulation date updated to: {start_date} - {end_date}")

    # 6. Get and print updated plan values
    print("\n6. Updated Plan Values:")
    for key in keys_to_check:
        value = RasPlan.get_plan_value(plan_number, key, ras_object=ras_obj)
        print(f"  {key}: {value}")

    # 7. Get updated description
    print("\n7. Updated Plan Description:")
    updated_description = RasPlan.read_plan_description(plan_number, ras_object=ras_obj)
    print(f"  {updated_description}")

    print("\nExample 15 completed.")

if __name__ == "__main__":
    main()
