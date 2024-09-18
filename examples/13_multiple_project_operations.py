#### --- IMPORTS AND EXAMPLE PROJECT SETUP --- ####

import sys
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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
ras_examples.extract_project(["Balde Eagle Creek", "Muncie"])

#### --- START OF SCRIPT --- ####

def execute_plan(plan_number, ras_object, compute_folder):
    # Set the number of cores to 2 before executing the plan
    RasPlan.set_num_cores(plan_number, 2, ras_object=ras_object)
    
    # Execute the plan in the compute folder
    success = RasCmdr.compute_plan(plan_number, ras_object=ras_object, dest_folder=compute_folder)
    
    return plan_number, success

def main():
    # Initialize two projects
    current_dir = Path(__file__).parent
    bald_eagle_path = current_dir / "example_projects" / "Balde Eagle Creek"
    muncie_path = current_dir / "example_projects" / "Muncie"
    
    bald_eagle = init_ras_project(bald_eagle_path, "6.5")
    muncie = init_ras_project(muncie_path, "6.5")

    print("Available plans in Bald Eagle Creek project:")
    print(bald_eagle.plan_df)
    print("\nAvailable plans in Muncie project:")
    print(muncie.plan_df)
    print()

    # Example 1: Clone plans with custom short identifiers
    print("Example 1: Cloning plans with custom short identifiers")
    new_bald_eagle_plan = RasPlan.clone_plan("01", new_plan_shortid="BECustom", ras_object=bald_eagle)
    new_muncie_plan = RasPlan.clone_plan("01", new_plan_shortid="MunCustom", ras_object=muncie)
    print(f"Created new plan {new_bald_eagle_plan} in Bald Eagle Creek project")
    print(f"Created new plan {new_muncie_plan} in Muncie project")
    print()

    # Example 2: Set geometry for the new plans
    print("Example 2: Setting geometry for the new plans")
    RasPlan.set_geom(new_bald_eagle_plan, "01", ras_object=bald_eagle)
    RasPlan.set_geom(new_muncie_plan, "01", ras_object=muncie)
    print(f"Set geometry for plan {new_bald_eagle_plan} in Bald Eagle Creek project")
    print(f"Set geometry for plan {new_muncie_plan} in Muncie project")
    print()

    # Example 3: Update unsteady flow parameters for both projects
    print("Example 3: Updating unsteady flow parameters")
    bald_eagle_plan_file = RasPlan.get_plan_path(new_bald_eagle_plan, ras_object=bald_eagle)
    muncie_plan_file = RasPlan.get_plan_path(new_muncie_plan, ras_object=muncie)

    modifications = {
        "Computation Interval": "2MIN",
        "Output Interval": "30MIN",
        "Mapping Interval": "1HOUR"
    }

    RasUnsteady.update_unsteady_parameters(bald_eagle_plan_file, modifications, ras_object=bald_eagle)
    RasUnsteady.update_unsteady_parameters(muncie_plan_file, modifications, ras_object=muncie)
    print("Updated unsteady flow parameters for both projects")
    print()

    # Example 4: Execute plans for both projects simultaneously in separate compute folders
    print("Example 4: Executing plans for both projects simultaneously in separate compute folders")
    
    # Create compute folders
    bald_eagle_compute_folder = bald_eagle_path.parent / "compute_bald_eagle"
    muncie_compute_folder = muncie_path.parent / "compute_muncie"
    
    # Remove existing compute folders if they exist
    for folder in [bald_eagle_compute_folder, muncie_compute_folder]:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(execute_plan, new_bald_eagle_plan, bald_eagle, bald_eagle_compute_folder),
            executor.submit(execute_plan, new_muncie_plan, muncie, muncie_compute_folder)
        ]
        
        results = {}
        for future in futures:
            plan_number, success = future.result()
            results[plan_number] = success

    print("Execution results:")
    for plan_number, success in results.items():
        print(f"Plan {plan_number} execution: {'Successful' if success else 'Failed'}")
    print()

    # Example 5: Get and print results paths
    print("Example 5: Getting results paths")
    bald_eagle_results = RasPlan.get_results_path(new_bald_eagle_plan, ras_object=bald_eagle)
    muncie_results = RasPlan.get_results_path(new_muncie_plan, ras_object=muncie)

    if bald_eagle_results:
        print(f"Results for Bald Eagle Creek plan {new_bald_eagle_plan} are located at: {bald_eagle_results}")
    else:
        print(f"No results found for Bald Eagle Creek plan {new_bald_eagle_plan}")

    if muncie_results:
        print(f"Results for Muncie plan {new_muncie_plan} are located at: {muncie_results}")
    else:
        print(f"No results found for Muncie plan {new_muncie_plan}")

    print("\nNote: The original project folders can now be edited while the compute operations are running in separate folders.")

if __name__ == "__main__":
    main()