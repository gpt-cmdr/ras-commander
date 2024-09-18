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

import pandas as pd


def create_plan_set(base_plan, base_geom, num_copies):
    plan_set = []
    for i in range(num_copies):
        new_plan = RasPlan.clone_plan(base_plan)
        new_geom = RasPlan.clone_geom(base_geom)
        RasPlan.set_geom(new_plan, new_geom)
        plan_set.append({
            'plan_number': new_plan,
            'geom_number': new_geom
        })
    return pd.DataFrame(plan_set)

def main():
    # Initialize the project
    current_dir = Path(__file__).parent
    project_path = current_dir / "example_projects" / "Balde Eagle Creek"
    init_ras_project(project_path, "6.5")

    print("Available plans:")
    print(ras.plan_df)
    print("\nAvailable geometries:")
    print(ras.geom_df)
    print()

    # Create a plan set
    base_plan = "01"
    base_geom = "01"
    num_copies = 5
    plan_set = create_plan_set(base_plan, base_geom, num_copies)
    
    print("Created plan set:")
    print(plan_set)
    print()

    # Placeholder for user to insert code that makes programmatic changes to the model
    # For example:
    # for index, row in plan_set.iterrows():
    #     plan_path = RasPlan.get_plan_path(row['plan_number'])
    #     geom_path = RasPlan.get_geom_path(row['geom_number'])
    #     # Make changes to the plan or geometry file here
    #     # For example, you could modify Manning's n values, cross-section data, etc.

    # Execute the plan set in parallel
    print("Executing plan set in parallel")
    results = RasCmdr.compute_parallel(
        plan_number=plan_set['plan_number'].tolist(),
        max_workers=3,
        num_cores=2
    )

    # Add execution results to the plan_set DataFrame
    plan_set['execution_success'] = plan_set['plan_number'].map(results)

    print("\nPlan set execution results:")
    print(plan_set)

    # Here you could add code to analyze the results, such as:
    # - Extracting key output values from each simulation
    # - Comparing results across different plans
    # - Creating visualizations of the results

if __name__ == "__main__":
    main()