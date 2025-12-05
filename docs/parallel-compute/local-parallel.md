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
    num_workers=4,
    num_cores=4
)

# Check results
for plan, success in results.items():
    print(f"Plan {plan}: {'Success' if success else 'Failed'}")
```

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `plan_number` | list | List of plan numbers to execute |
| `num_workers` | int | Number of concurrent workers (parallel plans) |
| `num_cores` | int | CPU cores allocated per plan |
| `dest_folder` | Path | Base folder for worker directories |
| `ras_object` | RasPrj | Project object (uses global `ras` if None) |
| `clear_geompre` | bool | Clear geometry preprocessor before run |
| `overwrite_dest` | bool | Overwrite existing worker folders |

## How It Works

### 1. Worker Folder Creation

For each worker, `compute_parallel` creates an isolated copy of the HEC-RAS project:

```
dest_folder/
├── worker_01/
│   ├── project.prj
│   ├── project.g01
│   ├── project.p01
│   └── ...
├── worker_02/
│   └── ...
└── worker_03/
    └── ...
```

### 2. Plan Distribution

Plans are distributed across workers using a queue. As each worker completes a plan, it picks up the next available one:

```
Plans: [01, 02, 03, 04, 05, 06]
Workers: 3

Time 0: Worker1=01, Worker2=02, Worker3=03
Time 1: Worker1=04 (01 done), Worker2=02, Worker3=05 (03 done)
Time 2: Worker1=04, Worker2=06 (02 done), Worker3=05
...
```

### 3. Results Collection

After all plans complete, results from each worker folder can be collected and analyzed.

## Optimal Configuration

### Balancing Workers vs. Cores

The total CPU usage is: `num_workers × num_cores`

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
    num_workers=4,
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
    num_workers=len(plans_created),
    num_cores=4
)
```

## Error Handling

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    num_workers=2,
    num_cores=4
)

# Check for failures
failed = [plan for plan, success in results.items() if not success]
if failed:
    print(f"Failed plans: {failed}")
    # Investigate by checking worker folder logs
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
