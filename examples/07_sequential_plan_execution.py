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
# Define the keys to search for in folder names
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

# ras-commander Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. For functions that do batched execution (sequential or parallel), they are careful not to overwrite existing folders.
# 5. If you want your script to be repeatable, make sure to delete the folders before running again.

def main():
    # Initialize the project using the global 'ras' object
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print()

    # Example 1: Sequential execution of all plans with overwrite_dest
    print("Example 1: Sequential execution of all plans with overwrite_dest")
    RasCmdr.compute_test_mode(
        dest_folder_suffix="[AllSequential]",
        overwrite_dest=True
    )
    print("Sequential execution of all plans completed with overwrite_dest")
    print()
    
    # Example 2: Sequential execution of specific plans with clearing geompre files and overwrite_dest
    print("Example 2: Sequential execution of specific plans with clearing geompre files and overwrite_dest")
    RasCmdr.compute_test_mode(
        plan_number=["01", "02"],
        dest_folder_suffix="[SpecificSequentialClearGeompre]",
        clear_geompre=True,
        overwrite_dest=True
    )
    print("Sequential execution of specific plans completed with clearing geompre files and overwrite_dest")
    print()

    # Example 3: Demonstrate clearing geompre files for specific plans
    print("Example 3: Clearing geompre files for specific plans")
    plan_files = [RasPlan.get_plan_path("01"), RasPlan.get_plan_path("02")]
    RasGeo.clear_geompre_files(plan_files)
    print("Geometry preprocessor files cleared for specific plans")
    print()

    # Example 4: Demonstrate clearing all geompre files
    print("Example 4: Clearing all geompre files")
    RasGeo.clear_geompre_files()
    print("All geometry preprocessor files cleared")

if __name__ == "__main__":
    main()