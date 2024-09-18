# 05_utility_functions.py

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

# RAS Commander (ras-commander) Library Notes:
# 1. This example uses the default global 'ras' object for simplicity.
# 2. If you need to work with multiple projects, use separate ras objects for each project.
# 3. Once you start using non-global ras objects, stick with that approach throughout your script.
# 4. The RasUtils class provides various utility functions for working with HEC-RAS projects.

# Best Practices:
# 1. For simple scripts working with a single project, using the global 'ras' object is fine.
# 2. For complex scripts or when working with multiple projects, create and use separate ras objects.
# 3. Be consistent in your approach: don't mix global and non-global ras object usage in the same script.

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")
    plan_number = "01"

    # Example 1: Get plan path using RasUtils
    print("Example 1: Getting plan path")
    plan_path = RasUtils.get_plan_path(plan_number)
    print(f"Path for plan {plan_number} is: {plan_path}")
    
    # Example 2: Get geometry path using RasPlan
    print("\nExample 2: Getting geometry path")
    geom_number = "01"
    geom_path = RasPlan.get_geom_path(geom_number)
    print(f"Path for geometry {geom_number} is: {geom_path}")
    
    # Example 3: Get unsteady flow path using RasPlan
    print("\nExample 3: Getting unsteady flow path")
    unsteady_number = "01"
    unsteady_path = RasPlan.get_unsteady_path(unsteady_number)
    print(f"Path for unsteady flow {unsteady_number} is: {unsteady_path}")
    
    # Example 4: Get project name
    print("\nExample 4: Getting project name")
    project_name = ras.get_project_name()
    print(f"Project name: {project_name}")


if __name__ == "__main__":
    main()