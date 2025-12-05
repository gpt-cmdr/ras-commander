# Plan Execution

RAS Commander provides three modes for executing HEC-RAS plans, each optimized for different workflows.

## Single Plan Execution

Execute one plan with full parameter control using `RasCmdr.compute_plan()`.

```python
from ras_commander import init_ras_project, RasCmdr

init_ras_project("/path/to/project", "6.5")

# Basic execution
success = RasCmdr.compute_plan("01")
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan_number` | str | Plan identifier ("01", "02", etc.) |
| `dest_folder` | str/Path | Directory for computation (None = in-place) |
| `ras_object` | RasPrj | Project object (default: global `ras`) |
| `clear_geompre` | bool | Clear geometry preprocessor files first |
| `num_cores` | int | Number of CPU cores to use |
| `overwrite_dest` | bool | Overwrite destination if exists |

### Examples

```python
# Execute with specific core count
success = RasCmdr.compute_plan("01", num_cores=4)

# Execute to separate folder (preserves original)
success = RasCmdr.compute_plan(
    "01",
    dest_folder="/results/run1",
    overwrite_dest=True
)

# Force geometry preprocessing
success = RasCmdr.compute_plan("01", clear_geompre=True)
```

## Sequential Execution

Run multiple plans in order using `RasCmdr.compute_test_mode()`. Plans execute in a copy of the project.

```python
results = RasCmdr.compute_test_mode(
    plan_number=["01", "02", "03"],
    dest_folder_suffix="[Test]"
)

for plan, success in results.items():
    print(f"Plan {plan}: {'OK' if success else 'FAILED'}")
```

### When to Use

- Plans have dependencies (e.g., plan 02 needs results from 01)
- Controlled resource usage is needed
- Debugging complex multi-plan workflows

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan_number` | list | Plans to run in order |
| `dest_folder_suffix` | str | Suffix for test folder name |
| `clear_geompre` | bool | Clear preprocessor before each plan |
| `num_cores` | int | Cores per plan |
| `overwrite_dest` | bool | Overwrite test folder |

## Parallel Execution

Run multiple independent plans simultaneously using `RasCmdr.compute_parallel()`. Creates temporary worker folders.

```python
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=3,
    num_cores=2,
    dest_folder="/results/parallel_run"
)
```

### Resource Optimization

Balance workers and cores based on your system:

```python
import psutil

# Calculate optimal configuration
physical_cores = psutil.cpu_count(logical=False)
cores_per_worker = 2
max_workers = physical_cores // cores_per_worker

# Also consider RAM (each HEC-RAS instance needs 2-4GB+)
available_ram_gb = psutil.virtual_memory().available / (1024**3)
ram_limited_workers = int(available_ram_gb // 4)

# Use the more restrictive limit
optimal_workers = min(max_workers, ram_limited_workers)

results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03", "04"],
    max_workers=optimal_workers,
    num_cores=cores_per_worker
)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan_number` | list | Plans to run concurrently |
| `max_workers` | int | Maximum parallel HEC-RAS instances |
| `num_cores` | int | Cores assigned to each worker |
| `dest_folder` | str/Path | Final results location |
| `clear_geompre` | bool | Clear preprocessor in worker folders |
| `overwrite_dest` | bool | Overwrite destination folder |

### How It Works

1. Creates temporary worker folders (copies of project)
2. Assigns plans to workers
3. Executes plans in parallel
4. Consolidates results to destination folder
5. Cleans up worker folders

## Execution Mode Comparison

| Feature | Single | Sequential | Parallel |
|---------|--------|------------|----------|
| Speed | Fast (1 plan) | Moderate | Fastest (many plans) |
| Resource Usage | Low | Low | High |
| Dependencies | N/A | Supported | Not supported |
| Disk Space | Low | Medium | High (temp folders) |
| Use Case | Testing, debugging | Dependent plans | Batch processing |

## Plan Modification Before Execution

Modify plan parameters programmatically before running:

```python
from ras_commander import RasPlan, RasCmdr

# Clone and modify
new_plan = RasPlan.clone_plan("01", new_plan_shortid="Modified Run")

# Change parameters
RasPlan.set_num_cores(new_plan, 4)
RasPlan.set_computation_interval(new_plan, "5MIN")
RasPlan.set_description(new_plan, "Run with finer timestep")

# Execute modified plan
success = RasCmdr.compute_plan(new_plan)
```

## Checking Results

After execution, verify results:

```python
from ras_commander import ras, HdfResultsPlan

# Refresh project data
init_ras_project(ras.project_folder, "6.5")

# Check for HDF results
hdf_entries = ras.get_hdf_entries()
print(hdf_entries)

# Get computation messages
plan_path = ras.plan_df.loc[
    ras.plan_df['plan_number'] == '01', 'hdf_path'
].iloc[0]

messages = HdfResultsPlan.get_compute_messages(plan_path)
print(messages)
```

## Error Handling

```python
from ras_commander import RasCmdr
import logging

# Enable debug logging
logging.getLogger('ras_commander').setLevel(logging.DEBUG)

try:
    success = RasCmdr.compute_plan("01")
    if not success:
        print("Plan execution failed - check HEC-RAS logs")
except FileNotFoundError as e:
    print(f"Plan file not found: {e}")
except ValueError as e:
    print(f"Invalid parameter: {e}")
```

## Best Practices

1. **Test first**: Use `compute_plan()` with `dest_folder` to test without modifying original
2. **Monitor resources**: Watch CPU and RAM during parallel execution
3. **Clear preprocessor**: Use `clear_geompre=True` after geometry changes
4. **Check return values**: Always verify execution success
5. **Use logging**: Enable DEBUG level for troubleshooting
