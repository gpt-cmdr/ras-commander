# Workflows and Patterns

Common workflow patterns for automating HEC-RAS with ras-commander.

## Clone-Modify-Execute Pattern

The most common workflow: clone a plan, modify parameters, execute, analyze results.

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan, HdfResultsMesh
from pathlib import Path

# 1. Initialize project
init_ras_project("/path/to/project", "6.5")

# 2. Clone the base plan
new_plan = RasPlan.clone_plan("01", "sensitivity_01")

# 3. Modify parameters
RasPlan.set_num_cores(new_plan, 8)
RasPlan.set_computation_interval(new_plan, "1MIN")

# 4. Execute
success = RasCmdr.compute_plan(new_plan)

# 5. Analyze results
if success:
    max_wse = HdfResultsMesh.get_mesh_max_ws(new_plan)
    print(f"Max WSE: {max_wse['max_ws'].max():.2f} ft")
```

## Batch Parameter Sensitivity

Run multiple scenarios with different parameters:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan, RasGeo

init_ras_project("/path/to/project", "6.5")

# Define sensitivity parameters
manning_n_values = [0.03, 0.04, 0.05, 0.06]
results = {}

for n in manning_n_values:
    # Clone plan for this scenario
    plan_name = f"mann_n_{n:.2f}"
    new_plan = RasPlan.clone_plan("01", plan_name)

    # Modify Manning's n (using geometry operations)
    # ... geometry modification code ...

    # Execute
    success = RasCmdr.compute_plan(new_plan, num_cores=4)

    # Store result
    results[n] = {
        'plan': new_plan,
        'success': success
    }

# Summary
for n, result in results.items():
    print(f"n={n:.2f}: {'Success' if result['success'] else 'Failed'}")
```

## Parallel Batch Processing

Execute many plans efficiently using parallel workers:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan

init_ras_project("/path/to/project", "6.5")

# Create multiple plan variations
plans = []
for i in range(1, 11):
    new_plan = RasPlan.clone_plan("01", f"scenario_{i:02d}")
    # Modify parameters for each scenario...
    plans.append(new_plan)

# Execute in parallel (local machine)
results = RasCmdr.compute_parallel(
    plan_number=plans,
    num_workers=4,    # 4 parallel workers
    num_cores=4       # 4 cores per worker
)

# Check results
successful = sum(1 for v in results.values() if v)
print(f"Completed: {successful}/{len(plans)} plans")
```

## Boundary Condition Modification

Modify unsteady flow boundary conditions:

```python
from ras_commander import init_ras_project, RasUnsteady, RasCmdr
import pandas as pd

init_ras_project("/path/to/project", "6.5")

# 1. Extract current boundary condition table
tables = RasUnsteady.extract_tables("u01")
flow_hydrograph = tables['Flow Hydrograph=']
print(f"Original flow table: {len(flow_hydrograph)} values")

# 2. Modify the hydrograph (e.g., scale by 1.2x)
modified_flow = flow_hydrograph * 1.2

# 3. Write back to file
RasUnsteady.write_table_to_file(
    "u01",
    "Flow Hydrograph=",
    modified_flow
)

# 4. Execute with modified boundary
success = RasCmdr.compute_plan("01")
```

## Results Extraction Pipeline

Extract and analyze results systematically:

```python
from ras_commander import (
    init_ras_project,
    HdfResultsMesh,
    HdfResultsPlan,
    HdfXsec
)
import pandas as pd

init_ras_project("/path/to/project", "6.5")

plans = ["01", "02", "03"]
all_results = []

for plan in plans:
    # Get plan metadata
    runtime = HdfResultsPlan.get_runtime_data(plan)

    # Get 2D mesh results
    max_wse = HdfResultsMesh.get_mesh_max_ws(plan)
    max_depth = HdfResultsMesh.get_mesh_max_depth(plan)

    # Aggregate statistics
    stats = {
        'plan': plan,
        'runtime_seconds': runtime.get('Compute Time (s)', 0),
        'max_wse': max_wse['max_ws'].max(),
        'max_depth': max_depth['max_depth'].max(),
        'avg_depth': max_depth['max_depth'].mean()
    }
    all_results.append(stats)

# Create summary DataFrame
summary_df = pd.DataFrame(all_results)
print(summary_df)
summary_df.to_csv("results_summary.csv", index=False)
```

## Working with Multiple Projects

Handle multiple HEC-RAS projects simultaneously:

```python
from ras_commander import init_ras_project, RasCmdr, RasPrj

# Create separate project objects
project1 = RasPrj()
project2 = RasPrj()

# Initialize each
init_ras_project("/path/to/project1", "6.5", ras_object=project1)
init_ras_project("/path/to/project2", "6.5", ras_object=project2)

# Work with project 1
print(f"Project 1 has {len(project1.plan_df)} plans")
RasCmdr.compute_plan("01", ras_object=project1)

# Work with project 2
print(f"Project 2 has {len(project2.plan_df)} plans")
RasCmdr.compute_plan("01", ras_object=project2)
```

## Error Handling Pattern

Robust error handling for automation scripts:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_execute_plan(plan_number, **kwargs):
    """Execute plan with error handling."""
    try:
        success = RasCmdr.compute_plan(plan_number, **kwargs)
        if success:
            logger.info(f"Plan {plan_number}: completed successfully")
            return True
        else:
            logger.warning(f"Plan {plan_number}: execution returned False")
            return False
    except FileNotFoundError as e:
        logger.error(f"Plan {plan_number}: file not found - {e}")
        return False
    except Exception as e:
        logger.error(f"Plan {plan_number}: unexpected error - {e}")
        return False

# Usage
init_ras_project("/path/to/project", "6.5")

plans = ["01", "02", "03"]
results = {}

for plan in plans:
    results[plan] = safe_execute_plan(plan, num_cores=4)

# Report
failed = [p for p, s in results.items() if not s]
if failed:
    logger.warning(f"Failed plans: {failed}")
```

## Geometry Preprocessing Optimization

For parallel runs, preprocess geometry once:

```python
from ras_commander import init_ras_project, RasCmdr, RasGeo

init_ras_project("/path/to/project", "6.5")

# Step 1: Run single plan to build geometry preprocessor files
print("Building geometry preprocessor files...")
RasCmdr.compute_plan("01", clear_geompre=False)

# Step 2: Run parallel without clearing preprocessor
print("Running parallel with cached geometry...")
plans = ["01", "02", "03", "04", "05", "06"]

results = RasCmdr.compute_parallel(
    plan_number=plans,
    num_workers=4,
    num_cores=4,
    clear_geompre=False  # Don't clear cached geometry!
)

print(f"Completed: {sum(results.values())}/{len(plans)}")
```

## Data Source Strategy

Choosing the right data source for your workflow:

| Task | Recommended Source | Method |
|------|-------------------|--------|
| Read boundary conditions | Plain text (.u##) | `RasUnsteady.extract_tables()` |
| Modify Manning's n | Plain text (.g##) | `RasGeo.set_mannings_baseoverrides()` |
| Extract max WSE | HDF results (.p##.hdf) | `HdfResultsMesh.get_mesh_max_ws()` |
| Read mesh geometry | HDF geometry (.g##.hdf) | `HdfMesh.get_mesh_cell_polygons()` |
| Read pipe networks | HDF only | `HdfPipe.get_pipe_conduits()` |

## Related

- [Plan Execution](plan-execution.md) - Detailed execution options
- [HDF Data Extraction](hdf-data-extraction.md) - Working with results
- [Remote Parallel](../parallel-compute/remote-parallel.md) - Distributed execution
