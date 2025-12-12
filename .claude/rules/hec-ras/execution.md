# HEC-RAS Plan Execution

**Context**: Running HEC-RAS simulations via ras-commander
**Priority**: Critical - core library functionality
**Auto-loads**: Yes (all code)

## Overview

ras-commander provides four execution modes for running HEC-RAS plans: single plan, parallel local, sequential test mode, and distributed remote execution.

## Execution Modes

### 1. Single Plan Execution

**Purpose**: Execute one HEC-RAS plan with full parameter control

**Primary Method**: `RasCmdr.compute_plan()`

**Signature**:
```python
RasCmdr.compute_plan(
    plan_number,              # Plan ID (string, e.g., "01")
    dest_folder=None,         # Optional computation folder
    ras_object=None,          # RasPrj object (default: global ras)
    clear_geompre=False,      # Clear geometry preprocessor files
    num_cores=None,           # Number of processing cores
    overwrite_dest=False,     # Overwrite existing destination
    stream_callback=None      # Real-time monitoring callback
)
```

**Example**:
```python
from ras_commander import init_ras_project, RasCmdr

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Execute plan
RasCmdr.compute_plan("01")
```

### 2. Parallel Local Execution

**Purpose**: Run multiple plans simultaneously using worker folders

**Method**: `RasCmdr.compute_parallel()`

**Signature**:
```python
RasCmdr.compute_parallel(
    plans_to_run,             # List of plan numbers
    ras_object=None,
    clear_geompre=False,
    num_cores=None,
    overwrite_dest=False,
    stream_callback=None
)
```

**Example**:
```python
# Execute 3 plans in parallel
RasCmdr.compute_parallel(["01", "02", "03"])
```

**How It Works**:
- Creates separate worker folders for each plan
- Copies project files to workers
- Executes plans simultaneously
- Returns results from all workers

### 3. Sequential Test Mode

**Purpose**: Run multiple plans in order in test folder

**Method**: `RasCmdr.compute_test_mode()`

**Signature**:
```python
RasCmdr.compute_test_mode(
    plans_to_run,
    ras_object=None,
    clear_geompre=False,
    num_cores=None,
    stream_callback=None
)
```

**Example**:
```python
# Execute plans sequentially for testing
RasCmdr.compute_test_mode(["01", "02", "03"])
```

**Difference from compute_parallel()**:
- Runs ONE plan at a time (sequential)
- Uses single test folder (not multiple workers)
- Useful for debugging and validation

### 4. Distributed Remote Execution

**Purpose**: Execute plans across remote machines via PsExec/SSH/cloud

**Function**: `compute_parallel_remote()`

**Signature**:
```python
from ras_commander.remote import compute_parallel_remote, init_ras_worker

compute_parallel_remote(
    plans_to_run,
    workers,                  # List of worker objects
    ras_object=None,
    clear_geompre=False,
    num_cores=None
)
```

**Example**:
```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Create workers
worker1 = init_ras_worker(worker_type='psexec', hostname='192.168.1.100', ...)
worker2 = init_ras_worker(worker_type='docker', hostname='192.168.1.101', ...)

# Execute across workers
compute_parallel_remote(
    plans_to_run=["01", "02", "03", "04"],
    workers=[worker1, worker2]  # Distributes plans across 2 workers
)
```

**See**: `.claude/rules/hec-ras/remote.md` for worker configuration

## Key Parameters

### plan_number

**Type**: String
**Format**: "01", "02", ... "99"
**Purpose**: Identifies which HEC-RAS plan to execute

**Examples**:
```python
RasCmdr.compute_plan("01")  # Plan 01
RasCmdr.compute_plan("15")  # Plan 15
```

**Common Mistake**: Using integer instead of string
```python
# ❌ WRONG
RasCmdr.compute_plan(1)  # TypeError or unexpected behavior

# ✅ CORRECT
RasCmdr.compute_plan("01")  # String with zero-padding
```

### dest_folder

**Type**: Path or string (optional)
**Default**: `None` (modifies original project)
**Purpose**: Copy project to destination before execution

**Examples**:
```python
from pathlib import Path

# Run in original project (modifies in-place)
RasCmdr.compute_plan("01", dest_folder=None)

# Run in separate folder (preserves original)
RasCmdr.compute_plan("01", dest_folder="/output/run1")
RasCmdr.compute_plan("01", dest_folder=Path("/output/run1"))
```

**When to Use**:
- ✅ Preserving original project files
- ✅ Running multiple scenarios
- ✅ Automating batch processing
- ❌ Simple one-time execution (use None)

### clear_geompre

**Type**: Boolean
**Default**: `False`
**Purpose**: Clear geometry preprocessor files before execution

**When True**: Deletes `.g##.hdf` files (forces geometry reprocessing)

**Examples**:
```python
# Keep preprocessed geometry (faster)
RasCmdr.compute_plan("01", clear_geompre=False)

# Force geometry reprocessing (slower, but ensures fresh)
RasCmdr.compute_plan("01", clear_geompre=True)
```

**Use Cases**:
- ✅ `True`: Geometry was modified, need fresh preprocessing
- ✅ `True`: Troubleshooting geometry issues
- ✅ `False`: Geometry unchanged, save time

### num_cores

**Type**: Integer (optional)
**Default**: `None` (HEC-RAS decides)
**Purpose**: Specify number of CPU cores for computation

**Examples**:
```python
# Let HEC-RAS decide
RasCmdr.compute_plan("01", num_cores=None)

# Use 4 cores
RasCmdr.compute_plan("01", num_cores=4)

# Use all available cores
import os
RasCmdr.compute_plan("01", num_cores=os.cpu_count())
```

**Considerations**:
- 2D models benefit from multiple cores
- 1D models may not see speedup
- Too many cores can cause overhead

### overwrite_dest

**Type**: Boolean
**Default**: `False`
**Purpose**: Allow overwriting existing destination folder

**Examples**:
```python
# Fail if destination exists (safe default)
RasCmdr.compute_plan("01", dest_folder="/output", overwrite_dest=False)

# Overwrite existing destination
RasCmdr.compute_plan("01", dest_folder="/output", overwrite_dest=True)
```

**Safety**:
- `False`: Prevents accidental data loss
- `True`: Useful for automated re-runs

### stream_callback

**Type**: Callable (optional)
**Default**: `None`
**Purpose**: Monitor HEC-RAS execution in real-time

**Available Callbacks** (`ras_commander.callbacks`):
- `ConsoleCallback` - Print to console
- `FileLoggerCallback` - Log to file
- `ProgressBarCallback` - Show progress bar (requires tqdm)
- `SynchronizedCallback` - Thread-safe wrapper

**Example**:
```python
from ras_commander.callbacks import ConsoleCallback

# Monitor execution in real-time
RasCmdr.compute_plan("01", stream_callback=ConsoleCallback(verbose=True))
```

**Custom Callback**:
```python
from ras_commander.callbacks import ExecutionCallback

class MyCallback(ExecutionCallback):
    def on_exec_message(self, message):
        print(f"HEC-RAS: {message}")

RasCmdr.compute_plan("01", stream_callback=MyCallback())
```

**See**: Real-Time Computation Messages documentation for callback protocol

## Execution Workflow

### Standard Workflow

1. **Initialize Project**:
   ```python
   from ras_commander import init_ras_project
   init_ras_project("/path/to/project", "6.5")
   ```

2. **Execute Plan**:
   ```python
   from ras_commander import RasCmdr
   RasCmdr.compute_plan("01")
   ```

3. **Extract Results**:
   ```python
   from ras_commander.hdf import HdfResultsPlan
   results = HdfResultsPlan("/path/to/project/plan.p01.hdf")
   wse = results.get_wse(time_index=0)
   ```

### Multiple Projects Workflow

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr

# Project 1
project1 = RasPrj()
init_ras_project("/path/to/project1", "6.5", ras_object=project1)

# Project 2
project2 = RasPrj()
init_ras_project("/path/to/project2", "6.5", ras_object=project2)

# Execute on specific projects
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("02", ras_object=project2)
```

## Common Patterns

### Pattern: Batch Processing with Scenarios

```python
scenarios = {
    "baseline": {"dest": "/output/baseline", "plan": "01"},
    "mitigation": {"dest": "/output/mitigation", "plan": "02"},
    "future": {"dest": "/output/future", "plan": "03"},
}

for name, config in scenarios.items():
    print(f"Running {name} scenario...")
    RasCmdr.compute_plan(
        config["plan"],
        dest_folder=config["dest"],
        clear_geompre=True,
        num_cores=4
    )
```

### Pattern: Parallel Execution with Monitoring

```python
from ras_commander.callbacks import ProgressBarCallback

RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    num_cores=4,
    stream_callback=ProgressBarCallback()  # Progress bar for each plan
)
```

### Pattern: Error Handling

```python
import logging
logger = logging.getLogger(__name__)

try:
    RasCmdr.compute_plan("01", dest_folder="/output/run1")
except Exception as e:
    logger.error(f"Execution failed: {e}")
    # Check compute messages
    from ras_commander.hdf import HdfResultsPlan
    hdf = HdfResultsPlan("/output/run1/plan.p01.hdf")
    messages = hdf.get_compute_messages()
    logger.error(f"HEC-RAS messages: {messages}")
    raise
```

## Verification

### Check if Execution Succeeded

**Method 1: Check HDF Exists**:
```python
from pathlib import Path

hdf_file = Path("/project/plan.p01.hdf")
if hdf_file.exists():
    print("Execution completed (HDF file created)")
else:
    print("Execution failed (no HDF file)")
```

**Method 2: Parse Compute Messages**:
```python
from ras_commander.hdf import HdfResultsPlan

hdf = HdfResultsPlan("/project/plan.p01.hdf")
messages = hdf.get_compute_messages()

if "Run completed successfully" in messages:
    print("Success!")
else:
    print(f"Check messages: {messages}")
```

**Method 3: Validate Results**:
```python
# Check results are reasonable
wse = hdf.get_wse(time_index=-1)  # Final time step

if wse is not None and len(wse) > 0:
    print(f"Results extracted: {len(wse)} values")
    print(f"WSE range: {wse.min():.2f} to {wse.max():.2f}")
else:
    print("No results found")
```

## Performance Optimization

### Parallel vs Sequential

**Use `compute_parallel()` when**:
- Multiple independent plans
- Sufficient CPU cores available
- Plans don't compete for resources

**Use `compute_test_mode()` when**:
- Debugging
- Limited resources
- Plans are interdependent

### Geometry Preprocessing

**Reuse preprocessed geometry** (`clear_geompre=False`):
- 2x-10x faster for 2D models
- Only valid if geometry unchanged

**Force reprocessing** (`clear_geompre=True`):
- Required after geometry modifications
- Slower but ensures correctness

## Troubleshooting

### Plan Doesn't Execute

**Check**:
1. Project initialized? `init_ras_project()` called?
2. Plan exists? Check `ras.plan_df`
3. HEC-RAS installed? Correct version?
4. Permissions? Write access to project folder?

### HDF File Not Created

**Diagnosis**:
1. Check compute messages (if HDF partially exists)
2. Check Windows Event Log
3. Enable `stream_callback` for real-time monitoring
4. Try running HEC-RAS GUI manually

### Performance Issues

**Optimization**:
1. Reduce `num_cores` (too many causes overhead)
2. Use `compute_parallel()` for multiple plans
3. Enable `clear_geompre=False` if geometry unchanged
4. Use SSD for project files (not network drive)

## See Also

- **Remote Execution**: `.claude/rules/hec-ras/remote.md` - Distributed execution
- **Static Classes**: `.claude/rules/python/static-classes.md` - RasCmdr pattern
- **Error Handling**: `.claude/rules/python/error-handling.md` - Exception patterns
- **HDF Results**: `ras_commander/hdf/CLAUDE.md` - Results extraction

---

**Key Takeaway**: Use `RasCmdr.compute_plan()` for single plans, `compute_parallel()` for multiple plans, and `compute_parallel_remote()` for distributed execution. Always pass plan numbers as strings ("01", not 1).
