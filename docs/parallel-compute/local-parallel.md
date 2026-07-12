# Local Parallel Execution

The `RasCmdr.compute_parallel()` method enables concurrent execution of multiple HEC-RAS plans on a single machine by creating isolated worker folders.

## Basic Usage

```python
from ras_commander import RasCmdr, init_ras_project

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Run multiple plans in parallel
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03", "04"],
    max_workers=4,
    num_cores=4
)

# Check results
for plan, success in results.items():
    print(f"Plan {plan}: {'Success' if success else 'Failed'}")
```

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan_number` | str, number, list, or None | Plan number(s) to execute; `None` selects all plans |
| `max_workers` | int | Maximum number of concurrent workers (parallel plans) |
| `num_cores` | int | CPU cores allocated per plan |
| `clear_geompre` | bool | Clear geometry preprocessor before run |
| `force_geompre` | bool | Clear geometry HDF and `.c##` files before each assigned run |
| `force_rerun` | bool | Compatibility option; assigned worker plans are already forced to execute |
| `ras_object` | RasPrj | Project object (uses global `ras` if `None`) |
| `dest_folder` | str, Path, or None | Final copied project directory; results are consolidated here |
| `overwrite_dest` | bool | Remove and replace the complete `dest_folder` directory if it exists |
| `skip_existing` | bool | Skip source plans whose HDF compute messages report `Complete Process` |
| `verify` | bool | Require `Complete Process` verification for each assigned plan |

## How It Works

### 1. Worker Folder Creation

`compute_parallel` first uses the original project, or copies it to
`dest_folder` when one is supplied. Temporary worker projects are created as
siblings of that project:

```
project_parent/
├── parallel_run/
│   ├── project.prj
│   ├── project.g01
│   └── project.p01
├── parallel_run [Worker 1]/
├── parallel_run [Worker 2]/
└── parallel_run [Worker 3]/
```

If `overwrite_dest=True`, the entire `dest_folder` is removed before the
project is copied. Use a dedicated output location, never a directory that
contains unrelated files.

### 2. Plan Distribution

Plans are assigned to worker IDs in round-robin order before execution begins.
The thread pool may finish plans in any order, but workers do not dynamically
dequeue the next plan:

```
Plans: [01, 02, 03, 04, 05, 06]
Workers: 3

Worker 1: [01, 04]
Worker 2: [02, 05]
Worker 3: [03, 06]
```

### 3. Results Collection

After all plans complete, their plan and geometry artifacts are consolidated
into the selected project directory. Temporary worker folders are then
removed. Review the returned result, consolidated HDF compute messages, and
DEBUG logs when diagnosing failures.

## Optimal Configuration

### Balancing Workers vs. Cores

The total CPU usage is: `max_workers × num_cores`

For a 16-core machine:

| Configuration | Workers | Cores/Plan | Total Cores | Best For |
|---------------|---------|------------|-------------|----------|
| High Throughput | 8 | 2 | 16 | Small models |
| Balanced | 4 | 4 | 16 | Medium models |
| Max Performance | 2 | 8 | 16 | Large models |

### Guidelines

- **Small models (< 10K cells)**: More workers, fewer cores per plan
- **Large models (> 100K cells)**: Fewer workers, more cores per plan
- **Leave 1-2 cores free** for system overhead
- **SSD storage** significantly improves worker folder creation/copying

## Example: Batch Processing

```python
from ras_commander import RasCmdr, RasPlan, init_ras_project
from pathlib import Path
import pandas as pd

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Get all plans
from ras_commander import ras
all_plans = ras.plan_df['plan_number'].tolist()

# Run all plans in parallel
results = RasCmdr.compute_parallel(
    plan_number=all_plans,
    max_workers=4,
    num_cores=4,
    dest_folder=Path("/output/parallel_run"),
    overwrite_dest=True
)

# Summarize results
df = pd.DataFrame([
    {"plan": k, "success": v}
    for k, v in results.items()
])
print(f"Success rate: {df['success'].mean()*100:.1f}%")
```

## Example: Parameter Sweep

```python
from ras_commander import RasCmdr, RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Create modified plans for parameter sweep
manning_values = [0.02, 0.03, 0.04, 0.05]
plans_created = []

for n in manning_values:
    # Clone and modify plan
    new_plan = RasPlan.clone_plan("01", f"Manning_{n}")
    # Modify Manning's n (implementation depends on geometry)
    plans_created.append(new_plan)

# Execute all variations in parallel
results = RasCmdr.compute_parallel(
    plan_number=plans_created,
    max_workers=len(plans_created),
    num_cores=4
)
```

## Error Handling

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=2,
    num_cores=4
)

# Check for failures
failed = [plan for plan, success in results.items() if not success]
if failed:
    print(f"Failed plans: {failed}")
    # Inspect consolidated HDF compute messages and DEBUG logs
```

## Limitations

- **Single machine**: Limited by local CPU and memory
- **File I/O**: Worker folder creation requires copying project files
- **Memory**: Each HEC-RAS instance uses memory; monitor total usage
- **Windows only**: HEC-RAS requires Windows

## Performance Tips

1. **Use SSDs**: Worker folder creation is I/O intensive
2. **Close other applications**: Maximize available memory and CPU
3. **Monitor resources**: Use Task Manager to check CPU/memory usage
4. **Start conservative**: Begin with fewer workers and scale up
5. **Pre-process geometry**: Run geometry preprocessing once before parallel runs

## Related

- [Remote Parallel Execution](remote-parallel.md) - Scale beyond one machine
- [Scaling Strategies](scaling-strategies.md) - Best practices for large-scale runs
- [compute_plan()](../user-guide/plan-execution.md) - Single plan execution
