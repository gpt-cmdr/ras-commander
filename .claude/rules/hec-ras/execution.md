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
    clear_geompre=False,      # Clear .c## preprocessor files
    force_geompre=False,      # Force full geom reprocessing (.g##.hdf + .c##)
    force_rerun=False,        # Force execution even if results current
    num_cores=None,           # Number of processing cores
    overwrite_dest=False,     # Overwrite existing destination
    skip_existing=False,      # Simple existence check (legacy)
    verify=False,             # Verify completion after execution
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
    max_workers=2,            # Number of parallel workers
    num_cores=2,              # Cores per worker
    ras_object=None,
    clear_geompre=False,
    force_geompre=False,      # New in v0.88.0
    force_rerun=False,        # New in v0.88.0
    dest_folder=None,
    overwrite_dest=False,
    skip_existing=False,
    verify=False
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
    dest_folder_suffix="[Test]",
    ras_object=None,
    clear_geompre=False,
    force_geompre=False,      # New in v0.88.0
    force_rerun=False,        # New in v0.88.0
    num_cores=None,
    overwrite_dest=False,
    skip_existing=False,
    verify=False
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
    num_cores=4,
    clear_geompre=False,
    force_geompre=False,      # New in v0.88.0
    force_rerun=False,        # New in v0.88.0
    max_concurrent=None,
    autoclean=True
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
**Purpose**: Clear geometry preprocessor binary files (.c## only) before execution

**When True**: Deletes `.c##` files (forces geometry recompilation)

**Examples**:
```python
# Keep preprocessed geometry (faster)
RasCmdr.compute_plan("01", clear_geompre=False)

# Force geometry recompilation (slower, but ensures fresh)
RasCmdr.compute_plan("01", clear_geompre=True)
```

**Use Cases**:
- ✅ `True`: Minor geometry edits, need recompilation
- ✅ `True`: Troubleshooting geometry issues
- ✅ `False`: Geometry unchanged, save time

### force_geompre (New in v0.88.0)

**Type**: Boolean
**Default**: `False`
**Purpose**: Force complete geometry reprocessing (clears both .g##.hdf AND .c## files)

**When True**: Deletes both `.g##.hdf` (geometry HDF) and `.c##` (binary preprocessor)

**Examples**:
```python
# Lightweight recompilation (only .c##)
RasCmdr.compute_plan("01", clear_geompre=True)

# Complete reprocessing (both .g##.hdf and .c##)
RasCmdr.compute_plan("01", force_geompre=True)
```

**When to Use**:
- ✅ Major geometry changes (new 2D mesh, modified structures)
- ✅ Geometry HDF corruption suspected
- ✅ Switching HEC-RAS versions
- ✅ Complete geometry regeneration needed

**Comparison to clear_geompre**:

| Parameter | Deletes | Use Case |
|-----------|---------|----------|
| `clear_geompre=True` | `.c##` only | Minor geometry edits |
| `force_geompre=True` | `.g##.hdf` + `.c##` | Major changes, corruption |

### force_rerun (New in v0.88.0)

**Type**: Boolean
**Default**: `False`
**Purpose**: Force execution even if results are current

**When False (default)**: Smart skip - checks file modification times and skips if results are current
**When True**: Always executes regardless of currency

**Smart Skip Logic (default behavior)**:
Results are skipped if ALL conditions met:
1. Plan HDF exists AND contains "Complete Process"
2. Plan HDF mtime > Plan file (.p##) mtime
3. Plan HDF mtime > Geometry file (.g##) mtime
4. Plan HDF mtime > Flow file (.u##/.f##) mtime

**Examples**:
```python
# Smart skip (default) - skips if results are current
RasCmdr.compute_plan("01")
# Logs: "Skipping plan 01: Results are current (HDF newer than inputs)"

# Force re-run even if current
RasCmdr.compute_plan("01", force_rerun=True)
# Executes HEC-RAS regardless of currency
```

**When to Use**:
- ✅ `False` (default): Efficient batch processing, development iterations
- ✅ `True`: Testing different HEC-RAS versions, reproducibility checks
- ✅ `True`: Forcing fresh results for validation

**Efficiency Example**:
```python
# Scenario: 10 plans, only 2 modified since last run
RasCmdr.compute_parallel(["01", "02", ..., "10"])
# Smart skip: Only runs 2 modified plans (80% time savings)

# Force all to run
RasCmdr.compute_parallel(["01", "02", ..., "10"], force_rerun=True)
# Runs all 10 plans (no skipping)
```

### skip_existing

**Type**: Boolean
**Default**: `False`
**Purpose**: Simple existence check (legacy parameter, use smart skip instead)

**When True**: Skips if HDF exists and contains "Complete Process" (no timestamp checking)

**Examples**:
```python
# Smart skip (recommended) - checks file modification times
RasCmdr.compute_plan("01")  # force_rerun=False is default

# Simple existence check (legacy)
RasCmdr.compute_plan("01", skip_existing=True)
```

**Comparison**:

| Feature | `skip_existing=True` | Smart Skip (default) |
|---------|---------------------|----------------------|
| Check HDF exists | ✓ | ✓ |
| Check "Complete Process" | ✓ | ✓ |
| Check file mtimes | ✗ | ✓ |
| Detects stale results | ✗ | ✓ |

**When to Use**:
- ✅ `skip_existing=True`: File modification times unreliable (network shares, virtualization)
- ✅ Smart skip (default): Most workflows, accurate staleness detection

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
        num_cores=4,
        overwrite_dest=True
    )
    # Smart skip automatically detects if scenario already run
    # Only executes if plan/geometry/flow files changed
```

### Pattern: Efficient Re-runs with Smart Skip

```python
# First run: Execute all plans
for plan in ["01", "02", "03"]:
    RasCmdr.compute_plan(plan, dest_folder=f"/runs/plan_{plan}")

# Modify only plan 02's geometry
modify_geometry("02")

# Re-run all: Only plan 02 executes (plans 01 and 03 skipped)
for plan in ["01", "02", "03"]:
    RasCmdr.compute_plan(plan, dest_folder=f"/runs/plan_{plan}", overwrite_dest=True)
# Logs: "Skipping plan 01: Results are current"
# Logs: "Skipping plan 03: Results are current"
# Plan 02 executes (geometry file is newer than HDF)
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

## DataFrame Refresh Behavior

All local compute functions automatically refresh DataFrames after execution:

| Function | Refreshes DataFrames | Condition |
|----------|---------------------|-----------|
| `compute_plan()` | Yes | Only when `dest_folder=None` |
| `compute_parallel()` | Yes | Always (re-inits from final location) |
| `compute_test_mode()` | Yes | Always |
| `compute_parallel_remote()` | No | By design (results on remote workers) |

**After execution, access results via plan_df**:
```python
# DataFrames are automatically refreshed - just use them
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
```

**Note**: For `compute_parallel_remote()`, results stay on remote workers. See `.claude/rules/hec-ras/remote.md` for details on updating DataFrames after remote execution.

## Performance Optimization

### Smart Execution Skip (New in v0.88.0)

**Automatic skip when results are current** (default behavior):
- Checks file modification times before execution
- Skips execution if HDF is newer than all input files
- Logs informative message: "Skipping plan 01: Results are current"

**Time Savings Example**:
```python
# Scenario: 10 plans, only 2 modified since last run
RasCmdr.compute_parallel(["01", ..., "10"])
# Smart skip: Runs only 2 plans (~20 minutes)
# Without skip: Runs all 10 plans (~100 minutes)
# Time savings: 80 minutes (80% reduction)
```

**When Smart Skip Helps**:
- ✅ Iterative development (re-running after small changes)
- ✅ Resuming interrupted batch runs
- ✅ Re-running analysis after fixing post-processing code
- ✅ Testing different result extraction methods

**Override Smart Skip**:
```python
# Always run regardless of currency
RasCmdr.compute_plan("01", force_rerun=True)
```

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

**Lightweight recompilation** (`clear_geompre=True`):
- Clears `.c##` files only
- 2x-5x faster than full reprocessing
- Use for minor geometry edits

**Complete reprocessing** (`force_geompre=True`):
- Clears both `.g##.hdf` and `.c##` files
- Required after major geometry changes
- Slower but ensures correctness

**Smart selection**:
```python
# Minor edit (changed Manning's n)
RasCmdr.compute_plan("01", clear_geompre=True)

# Major change (new 2D mesh)
RasCmdr.compute_plan("01", force_geompre=True)
```

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

## Compute Messages File Generation

### Write Detailed Flag

**All ras-commander execution functions automatically enable `Write Detailed= 1`** in plan files.

**What it does**:
- Generates `.computeMsgs.txt` file (HEC-RAS 6.x+)
- Generates `.comp_msgs.txt` file (HEC-RAS 5.x and earlier)
- Contains detailed computation messages, warnings, errors, convergence info

**Why automatic**:
- Required for results_df fallback on pre-6.4 HEC-RAS versions
- Enables better debugging (messages always available)
- Minimal overhead (1-5 KB file, no performance impact)

**Affected functions**:
- `RasCmdr.compute_plan()` - Enables before execution
- `RasCmdr.compute_parallel()` - Inherits from compute_plan
- `RasCmdr.compute_test_mode()` - Inherits from compute_plan
- `RasControl.run_plan()` - Enables before COM execution
- All remote workers - Enable in worker folders

**File naming by version**:
- HEC-RAS 6.x+: `{project}.p##.computeMsgs.txt`
- HEC-RAS 5.x: `{project}.p##.comp_msgs.txt`

**Manual override**: Not currently supported (flag always enabled)

## See Also

- **Remote Execution**: `.claude/rules/hec-ras/remote.md` - Distributed execution
- **Static Classes**: `.claude/rules/python/static-classes.md` - RasCmdr pattern
- **Error Handling**: `.claude/rules/python/error-handling.md` - Exception patterns
- **HDF Results**: `ras_commander/hdf/CLAUDE.md` - Results extraction
- **Results DataFrame**: `ras_commander/results/ResultsSummary.py` - Fallback mechanism

---

**Key Takeaway**: Use `RasCmdr.compute_plan()` for single plans, `compute_parallel()` for multiple plans, and `compute_parallel_remote()` for distributed execution. Smart skip (default) automatically avoids re-running current results. Use `force_rerun=True` to override. Always pass plan numbers as strings ("01", not 1). All execution functions automatically enable `Write Detailed= 1` for compute messages generation.
