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

## Verifying Run Success

After executing HEC-RAS plans, it's critical to verify the run completed successfully and without runtime errors. The HDF file contains three key pieces of information for validation:

### Complete Verification Workflow

```python
from ras_commander import init_ras_project, HdfResultsPlan, RasCmdr

init_ras_project("/path/to/project", "6.5")

def verify_run_success(plan_number: str) -> dict:
    """
    Comprehensive verification of HEC-RAS run success.

    Returns dict with success status and diagnostic information.
    """
    result = {
        'plan': plan_number,
        'success': False,
        'has_results': False,
        'volume_balance_ok': False,
        'no_errors': False,
        'messages': []
    }

    # 1. Check compute messages for errors
    compute_msgs = HdfResultsPlan.get_compute_messages(plan_number)
    if compute_msgs:
        result['has_results'] = True
        # Check for error indicators in messages
        error_keywords = ['ERROR', 'FAILED', 'UNSTABLE', 'ABORTED']
        has_errors = any(kw in compute_msgs.upper() for kw in error_keywords)
        result['no_errors'] = not has_errors

        if has_errors:
            # Extract error lines for reporting
            for line in compute_msgs.split('\n'):
                if any(kw in line.upper() for kw in error_keywords):
                    result['messages'].append(line.strip())

    # 2. Check volume accounting (mass balance)
    volume_df = HdfResultsPlan.get_volume_accounting(plan_number)
    if volume_df is not None:
        # Volume accounting exists - check for balance
        result['volume_accounting'] = volume_df.to_dict('records')[0]
        # Typical check: cumulative error should be small relative to total volume
        result['volume_balance_ok'] = True  # Customize threshold as needed

    # 3. Check unsteady summary for completion status
    try:
        unsteady_summary = HdfResultsPlan.get_unsteady_summary(plan_number)
        result['unsteady_summary'] = unsteady_summary.to_dict('records')[0]
    except KeyError:
        result['messages'].append("No unsteady summary found - run may not have completed")

    # Overall success determination
    result['success'] = (
        result['has_results'] and
        result['no_errors'] and
        result['volume_balance_ok']
    )

    return result

# Usage
result = verify_run_success("01")
if result['success']:
    print(f"Plan {result['plan']}: Run completed successfully")
else:
    print(f"Plan {result['plan']}: Run had issues")
    for msg in result['messages']:
        print(f"  - {msg}")
```

### Checking Compute Messages

Compute messages contain the HEC-RAS computation log with warnings, errors, and performance information:

```python
from ras_commander import HdfResultsPlan

# Get computation messages
msgs = HdfResultsPlan.get_compute_messages("01")

# Display messages
if msgs:
    print("="*60)
    print("COMPUTATION MESSAGES")
    print("="*60)
    for line in msgs.split('\n'):
        if line.strip():
            # Highlight errors and warnings
            if 'ERROR' in line.upper():
                print(f"[ERROR] {line}")
            elif 'WARNING' in line.upper():
                print(f"[WARN]  {line}")
            else:
                print(f"        {line}")
else:
    print("No compute messages found - run may not have completed")
```

### Checking Volume Accounting

Volume accounting verifies mass conservation in the hydraulic simulation:

```python
from ras_commander import HdfResultsPlan

# Get volume accounting
volume_df = HdfResultsPlan.get_volume_accounting("01")

if volume_df is not None:
    print("Volume Accounting:")
    print(volume_df.T)  # Transpose for readability

    # Key attributes to check (available attributes vary by model):
    # - Boundary Conditions In/Out
    # - Precipitation In
    # - Storage Area volumes
    # - Cumulative error
else:
    print("No volume accounting data - check if run completed")
```

### Checking Unsteady Results Existence

Verify that unsteady results were generated:

```python
from ras_commander import HdfResultsPlan

# Check unsteady info (basic attributes)
try:
    unsteady_info = HdfResultsPlan.get_unsteady_info("01")
    print("Unsteady Results Found:")
    print(unsteady_info.T)
except KeyError:
    print("No unsteady results - plan may not have run or is steady flow")

# Check unsteady summary (detailed summary)
try:
    unsteady_summary = HdfResultsPlan.get_unsteady_summary("01")
    print("\nUnsteady Summary:")
    print(unsteady_summary.T)
except KeyError:
    print("No unsteady summary data")
```

### Checking Runtime Performance

Monitor computation performance and timing:

```python
from ras_commander import HdfResultsPlan

runtime = HdfResultsPlan.get_runtime_data("01")

if runtime is not None:
    print("Runtime Statistics:")
    print(f"  Plan: {runtime['Plan Name'].iloc[0]}")
    print(f"  Simulation Duration: {runtime['Simulation Time (hr)'].iloc[0]:.2f} hours")
    print(f"  Compute Time: {runtime['Complete Process (hr)'].iloc[0]:.4f} hours")
    print(f"  Speed: {runtime['Complete Process Speed (hr/hr)'].iloc[0]:.1f}x realtime")

    # Check individual process times
    if runtime['Unsteady Flow Computations (hr)'].iloc[0] != 'N/A':
        print(f"  Unsteady Compute: {runtime['Unsteady Flow Computations (hr)'].iloc[0]:.4f} hours")
```

### Batch Verification Pattern

For parallel or batch runs, verify all plans systematically:

```python
from ras_commander import init_ras_project, HdfResultsPlan, RasCmdr
import pandas as pd

init_ras_project("/path/to/project", "6.5")

# Run multiple plans
plans = ["01", "02", "03", "04"]
results = RasCmdr.compute_parallel(plans, max_workers=4)

# Verify all runs
verification_results = []
for plan, executed in results.items():
    if not executed:
        verification_results.append({
            'plan': plan, 'status': 'EXECUTION_FAILED', 'errors': ['Did not execute']
        })
        continue

    # Check compute messages
    msgs = HdfResultsPlan.get_compute_messages(plan)
    has_errors = 'ERROR' in msgs.upper() if msgs else True

    # Check volume accounting
    volume_df = HdfResultsPlan.get_volume_accounting(plan)
    has_volume = volume_df is not None

    # Get runtime
    runtime = HdfResultsPlan.get_runtime_data(plan)
    compute_time = runtime['Complete Process (hr)'].iloc[0] if runtime is not None else None

    verification_results.append({
        'plan': plan,
        'status': 'OK' if (not has_errors and has_volume) else 'ERRORS',
        'has_errors': has_errors,
        'has_volume_accounting': has_volume,
        'compute_time_hr': compute_time
    })

# Summary report
summary_df = pd.DataFrame(verification_results)
print("\n" + "="*60)
print("BATCH RUN VERIFICATION SUMMARY")
print("="*60)
print(summary_df.to_string(index=False))

# Identify failures
failures = summary_df[summary_df['status'] != 'OK']
if not failures.empty:
    print(f"\n{len(failures)} plans require attention!")
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
