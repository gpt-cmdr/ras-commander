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
This script demonstrates the process of initializing a HEC-RAS project and performing various operations on unsteady flow files using the RasUnsteady class.

Process Flow:
1. Project Initialization: Initialize a HEC-RAS project by specifying the project path and version.
2. Extract Boundary and Tables: Extract boundary conditions and associated tables from an unsteady flow file.
3. Print Boundaries and Tables: Display the extracted boundary conditions and tables.
4. Update Unsteady Parameters: Modify parameters in the unsteady flow file.
5. Verify Changes: Check the updated unsteady flow file to confirm the changes.
"""

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.6")

    print("Initial unsteady flow files:")
    print(ras.unsteady_df)
    print()

    # Step 1: Extract boundary and tables
    print("Step 1: Extracting boundary conditions and tables")
    unsteady_file = RasPlan.get_unsteady_path("02")  # Using unsteady flow file "02"
    print(f"Unsteady file: {unsteady_file}")
    boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_file)
    print("Extracted boundary conditions and tables")
    #print(boundaries_df)

    # Step 2: Print boundaries and tables
    print("Step 2: Printing boundaries and tables")
    RasUnsteady.print_boundaries_and_tables(boundaries_df)
    print()

    # Step 3: Update unsteady parameters
    #print("Step 3: Updating unsteady flow parameters")
    #modifications = {
    #    "Computation Interval": "30SEC",
    #    "Output Interval": "10MIN",
    #    "Mapping Interval": "1HOUR"
    #}
    #RasUnsteady.update_unsteady_parameters(unsteady_file, modifications)
    #print("Updated unsteady flow parameters")
    #print()

    
if __name__ == "__main__":
    main()

