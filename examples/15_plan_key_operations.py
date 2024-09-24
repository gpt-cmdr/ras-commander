# 15_plan_key_operations.py

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

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    ras_obj = init_ras_project(project_path, "6.5")

    print("Example 15: Getting and Setting Plan Keys")
    print("------------------------------------------")

    # Get the first plan number
    plan_number = ras_obj.plan_df['plan_number'].iloc[0]
    print(f"Working with Plan: {plan_number}")

    # 1. Get and print multiple plan values
    keys_to_check = ['computation_interval', 'simulation_date', 'short_identifier', 'unet_d1_cores']
    print("\n1. Current Plan Values:")
    for key in keys_to_check:
        value = RasPlan.get_plan_value(plan_number, key, ras_object=ras_obj)
        print(f"  {key}: {value}")

    # 2. Update plan values
    print("\n2. Updating Plan Values:")
    updates = {
        'computation_interval': '30SEC',
        'short_identifier': 'Updated_Plan',
        'unet_d1_cores': '4'
    }
    for key, value in updates.items():
        RasPlan.update_plan_value(plan_number, key, value, ras_object=ras_obj)
        print(f"  Updated {key} to: {value}")

    # 3. Verify updates
    print("\n3. Verifying Updates:")
    for key in updates.keys():
        new_value = RasPlan.get_plan_value(plan_number, key, ras_object=ras_obj)
        print(f"  {key}: {new_value}")

    # 4. Get and update description
    print("\n4. Plan Description:")
    current_description = RasPlan.get_plan_value(plan_number, 'description', ras_object=ras_obj)
    print(f"  Current description: {current_description}")

    new_description = "This is an updated plan description for Example 15."
    RasPlan.update_plan_value(plan_number, 'description', new_description, ras_object=ras_obj)
    print(f"  Updated description to: {new_description}")

    # Verify description update
    updated_description = RasPlan.get_plan_value(plan_number, 'description', ras_object=ras_obj)
    print(f"  Verified updated description: {updated_description}")

    # 5. Attempt to get and set an invalid key
    print("\n5. Handling Invalid Keys:")
    try:
        RasPlan.get_plan_value(plan_number, 'invalid_key', ras_object=ras_obj)
    except ValueError as e:
        print(f"  Error when getting invalid key: {e}")

    try:
        RasPlan.update_plan_value(plan_number, 'invalid_key', 'some_value', ras_object=ras_obj)
    except ValueError as e:
        print(f"  Error when updating invalid key: {e}")

    print("\nExample 15 completed.")

if __name__ == "__main__":
    main()