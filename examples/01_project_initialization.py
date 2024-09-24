# 01_project_initialization.py

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
ras_examples.extract_project(["Balde Eagle Creek", "BaldEagleCrkMulti2D", "Muncie"])

#### --- START OF SCRIPT --- ####

# RAS Commander Library Notes:
# 1. This example demonstrates both the default global 'ras' object and custom ras objects.
# 2. The global 'ras' object is suitable for simple scripts working with a single project.
# 3. Custom ras objects are recommended for complex scripts or when working with multiple projects.
# 4. The init_ras_project function initializes a project and sets up the ras object.
# 5. Each ras object contains comprehensive information about its project, including plan, geometry, flow files, and boundary conditions.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. Use descriptive names for custom ras objects to clearly identify different projects.

def print_ras_object_data(ras_obj, project_name):
    print(f"\n{project_name} Project Data:")
    print("=" * 50)
    print(f"Project Name: {ras_obj.get_project_name()}")
    print(f"Project Folder: {ras_obj.project_folder}")
    print(f"PRJ File: {ras_obj.prj_file}")
    print(f"HEC-RAS Executable Path: {ras_obj.ras_exe_path}")
    
    print("\nPlan Files DataFrame:")
    print(ras_obj.plan_df)
    
    print("\nFlow Files DataFrame:")
    print(ras_obj.flow_df)
    
    print("\nUnsteady Flow Files DataFrame:")
    print(ras_obj.unsteady_df)
    
    print("\nGeometry Files DataFrame:")
    print(ras_obj.geom_df)
    
    print("\nHDF Entries DataFrame:")
    print(ras_obj.get_hdf_entries())
    
    print("\nBoundary Conditions DataFrame:")
    print(ras_obj.get_boundary_conditions())
    
    print("\nMeteorological Data:")
    for attr in ['precipitation_mode', 'wind_mode', 'precipitation_metadata', 'evapotranspiration_metadata']:
        if hasattr(ras_obj, attr):
            print(f"{attr.capitalize().replace('_', ' ')}: {getattr(ras_obj, attr)}")
        else:
            print(f"{attr.capitalize().replace('_', ' ')}: Not available")

def main():
    # Get the current script's directory
    current_dir = Path(__file__).parent
    
    # Define paths to example projects
    bald_eagle_path = current_dir.parent / "examples" / "example_projects" / "Balde Eagle Creek"
    multi_2d_path = current_dir.parent / "examples" / "example_projects" / "BaldEagleCrkMulti2D"
    muncie_path = current_dir.parent / "examples" / "example_projects" / "Muncie"

    print("Example Set 1: Using the default global 'ras' object")
    print("-----------------------------------------------------")

    # Initialize using the global RAS instance
    print("Step 1: Initializing with global RAS instance")
    init_ras_project(bald_eagle_path, "6.5") # This will set the global 'ras' object
    print_ras_object_data(ras, "Global RAS Instance (Bald Eagle Creek)")

    print("\nExample Set 2: Using custom ras objects")
    print("-----------------------------------------------------")

    # Initialize multiple project instances
    print("Step 1: Initializing multiple project instances")
    multi_2d_project = init_ras_project(multi_2d_path, "6.5")
    muncie_project = init_ras_project(muncie_path, "6.5")

    print_ras_object_data(multi_2d_project, "Multi2D Project")
    print_ras_object_data(muncie_project, "Muncie Project")

    print("\nExample of simplified import (not recommended for complex scripts)")
    print("-----------------------------------------------------")
    print("from ras_commander import *")
    print("# This allows you to use all functions and classes without prefixes")
    print("# For example: compute_plan() instead of RasCmdr.compute_plan()")
    print("# Note: This approach can lead to naming conflicts and is generally not recommended for larger scripts")

if __name__ == "__main__":
    main()