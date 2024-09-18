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
# 5. Each ras object contains information about its project, including plan, geometry, and flow files.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.
# 4. Use descriptive names for custom ras objects to clearly identify different projects.

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
    ras.print_data()  # Using the class method

    # Demonstrate accessing specific data
    print("\nStep 2: Demonstrating accessing specific data")
    print("Global RAS instance (Bald Eagle Creek) first plan file:")
    print(ras.plan_df.iloc[0] if not ras.plan_df.empty else "No plan files")
    
    print("\nStep 3: Accessing All RAS Object Data")
    print(f"Project Name: {ras.get_project_name()}")
    print(f"Project Folder: {ras.project_folder}")
    print(f"PRJ File: {ras.prj_file}")
    print(f"HEC-RAS Executable Path: {ras.ras_exe_path}")
    
    print("\nPlan Files DataFrame:")
    print(ras.plan_df)
    
    print("\nFlow Files DataFrame:")
    print(ras.flow_df)
    
    print("\nUnsteady Flow Files DataFrame:")
    print(ras.unsteady_df)
    
    print("\nGeometry Files DataFrame:")
    print(ras.geom_df)
    
    print("\nHDF Entries DataFrame:")
    print(ras.get_hdf_entries())

    print("\nExample Set 2: Using custom ras objects")
    print("-----------------------------------------------------")

    # Initialize multiple project instances
    print("Step 1: Initializing multiple project instances")
    multi_2d_project = init_ras_project(multi_2d_path, "6.5")
    muncie_project = init_ras_project(muncie_path, "6.5")

    print("\nMulti2D project data:")    
    multi_2d_project.print_data()
    print("\nMuncie project data:")
    muncie_project.print_data()

    # Demonstrate accessing specific data from custom ras objects
    print("\nStep 2: Accessing specific data from custom ras objects")
    print("Multi2D project first geometry file:")
    print(multi_2d_project.geom_df.iloc[0] if not multi_2d_project.geom_df.empty else "No geometry files")
    
    print("\nMuncie project first unsteady flow file:")
    print(muncie_project.unsteady_df.iloc[0] if not muncie_project.unsteady_df.empty else "No unsteady flow files")

    print("\nStep 3: Accessing All RAS Object Data for Multi2D Project")
    print(f"Project Name: {multi_2d_project.get_project_name()}")
    print(f"Project Folder: {multi_2d_project.project_folder}")
    print(f"PRJ File: {multi_2d_project.prj_file}")
    print(f"HEC-RAS Executable Path: {multi_2d_project.ras_exe_path}")
    
    print("\nPlan Files DataFrame:")
    print(multi_2d_project.plan_df)
    
    print("\nFlow Files DataFrame:")
    print(multi_2d_project.flow_df)
    
    print("\nUnsteady Flow Files DataFrame:")
    print(multi_2d_project.unsteady_df)
    
    print("\nGeometry Files DataFrame:")
    print(multi_2d_project.geom_df)
    
    print("\nHDF Entries DataFrame:")
    print(multi_2d_project.get_hdf_entries())

    print("\nExample of simplified import (not recommended for complex scripts)")
    print("-----------------------------------------------------")
    print("from ras_commander import *")
    print("# This allows you to use all functions and classes without prefixes")
    print("# For example: compute_plan() instead of RasCmdr.compute_plan()")
    print("# Note: This approach can lead to naming conflicts and is generally not recommended for larger scripts")

if __name__ == "__main__":
    main()