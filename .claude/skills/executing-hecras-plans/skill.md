---
name: executing-hecras-plans
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, manages destination folders, and monitors
  real-time progress with callbacks. Use when running HEC-RAS simulations,
  computing plans, executing models, parallel workflows, setting up
  distributed computation, batch processing, scenario analysis, or monitoring
  execution progress in real-time.
trigger_keywords:
  - execute
  - run
  - compute
  - HEC-RAS
  - plan
  - simulation
  - parallel
  - callback
  - batch
  - scenario
  - destination folder
  - worker
  - monitoring
  - progress
  - real-time
location: .claude/skills/executing-hecras-plans
---

# Executing HEC-RAS Plans

Complete workflow for running HEC-RAS simulations using ras-commander. Covers single plan execution, parallel processing, sequential test mode, real-time monitoring, and destination folder management.

## Quick Start

### Execute Single Plan

```python
from ras_commander import init_ras_project, RasCmdr

# Initialize project
init_ras_project(r"C:\Models\MyProject", "6.5")

# Execute plan (in-place, modifies original)
RasCmdr.compute_plan("01")

# Execute in separate folder (preserves original)
RasCmdr.compute_plan("01", dest_folder="run1")
```

### Execute Multiple Plans in Parallel

```python
# Execute 3 plans simultaneously
RasCmdr.compute_parallel(["01", "02", "03"])

# With specific number of cores
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    num_cores=4
)
```

### Monitor Execution in Real-Time

```python
from ras_commander.callbacks import ConsoleCallback

# Execute with console monitoring
RasCmdr.compute_plan(
    "01",
    stream_callback=ConsoleCallback(verbose=True)
)
```

## When to Use This Skill

Use when you need to:

1. **Run single HEC-RAS plans** - Execute one plan with full parameter control
2. **Parallel execution** - Run multiple plans simultaneously using worker folders
3. **Batch processing** - Process multiple scenarios or parameter sets
4. **Preserve original projects** - Run computations in separate destination folders
5. **Monitor progress** - Track execution in real-time with callbacks
6. **Sequential testing** - Run plans one at a time for debugging
7. **Optimize performance** - Control core count and geometry preprocessing

## Execution Modes

### 1. Single Plan Execution

Execute one HEC-RAS plan with full parameter control.

**Method**: `RasCmdr.compute_plan()`

```python
from ras_commander import init_ras_project, RasCmdr

# Initialize project
init_ras_project(r"C:\Models\MyProject", "6.5")

# Basic execution (in-place)
RasCmdr.compute_plan("01")

# Execute in separate folder
RasCmdr.compute_plan("01", dest_folder="computation_folder")

# With specific core count
RasCmdr.compute_plan("01", num_cores=4)

# Force geometry reprocessing
RasCmdr.compute_plan("01", clear_geompre=True)

# With verification
RasCmdr.compute_plan("01", verify=True)
```

**Key Parameters**:
- `plan_number` - Plan ID as string ("01", "02", etc.)
- `dest_folder` - Optional computation folder (None = modify original)
- `num_cores` - Number of CPU cores (None = HEC-RAS decides)
- `clear_geompre` - Clear geometry preprocessor files (True/False)
- `verify` - Verify successful completion (True/False)
- `overwrite_dest` - Overwrite existing destination (True/False)
- `stream_callback` - Real-time monitoring callback (optional)

### 2. Parallel Local Execution

Run multiple plans simultaneously using separate worker folders.

**Method**: `RasCmdr.compute_parallel()`

```python
# Execute 4 plans in parallel
RasCmdr.compute_parallel(["01", "02", "03", "04"])

# With specific core count per plan
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    num_cores=4  # 4 cores per plan
)

# With real-time monitoring
from ras_commander.callbacks import ConsoleCallback

RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=ConsoleCallback()
)
```

**How It Works**:
- Creates separate worker folders for each plan
- Copies project files to each worker
- Executes all plans simultaneously
- Consolidates results back to original project

### 3. Sequential Test Mode

Run multiple plans one at a time in a test folder (for debugging).

**Method**: `RasCmdr.compute_test_mode()`

```python
# Execute plans sequentially
RasCmdr.compute_test_mode(["01", "02", "03"])

# With monitoring
RasCmdr.compute_test_mode(
    plans_to_run=["01", "02"],
    stream_callback=ConsoleCallback(verbose=True)
)
```

**Difference from `compute_parallel()`**:
- Runs ONE plan at a time (sequential, not parallel)
- Uses single test folder (not multiple workers)
- Useful for debugging and validation

## Common Patterns

### Pattern: Batch Scenario Processing

```python
from ras_commander import init_ras_project, RasCmdr
from pathlib import Path

# Initialize project
init_ras_project(r"C:\Models\MyProject", "6.5")

# Define scenarios
scenarios = {
    "baseline": {"plan": "01", "dest": "output/baseline"},
    "mitigation": {"plan": "02", "dest": "output/mitigation"},
    "future": {"plan": "03", "dest": "output/future"},
    "extreme": {"plan": "04", "dest": "output/extreme"}
}

# Run each scenario
for name, config in scenarios.items():
    print(f"Running {name} scenario...")
    RasCmdr.compute_plan(
        config["plan"],
        dest_folder=config["dest"],
        num_cores=4,
        verify=True
    )
    print(f"Completed {name}")
```

### Pattern: Preserve Original with Destination Folders

```python
# Original project remains untouched
RasCmdr.compute_plan(
    "01",
    dest_folder="results/run_2024_12_11",
    overwrite_dest=True,  # Allow re-runs
    verify=True
)

# Results are in separate folder
from ras_commander.hdf import HdfResultsPlan
results = HdfResultsPlan("results/run_2024_12_11/MyProject.p01.hdf")
```

### Pattern: Geometry Modification Workflow

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.RasGeo import RasGeo

init_ras_project(r"C:\Models\MyProject", "6.5")

# Modify geometry
RasGeo.update_mannings_n(
    geom_file="g01",
    landcover_map={"Forest": 0.08, "Urban": 0.05}
)

# Run with forced geometry reprocessing
RasCmdr.compute_plan(
    "01",
    clear_geompre=True,  # CRITICAL: Force reprocessing after geometry change
    num_cores=4
)
```

### Pattern: Skip Already Completed Plans

```python
# Resume interrupted batch run
plans = ["01", "02", "03", "04", "05"]

for plan in plans:
    RasCmdr.compute_plan(
        plan,
        skip_existing=True,  # Skip if HDF already has 'Complete Process'
        dest_folder=f"run_{plan}",
        verify=True
    )
```

### Pattern: Error Handling and Retry

```python
import logging
from time import sleep

logger = logging.getLogger(__name__)

def run_with_retry(plan_number, max_retries=3):
    """Execute plan with automatic retry on failure."""
    for attempt in range(max_retries):
        try:
            success = RasCmdr.compute_plan(
                plan_number,
                dest_folder=f"attempt_{attempt+1}",
                overwrite_dest=True,
                verify=True
            )

            if success:
                logger.info(f"Plan {plan_number} succeeded on attempt {attempt+1}")
                return True
            else:
                logger.warning(f"Plan {plan_number} failed verification on attempt {attempt+1}")

        except Exception as e:
            logger.error(f"Plan {plan_number} error on attempt {attempt+1}: {e}")

        if attempt < max_retries - 1:
            sleep(5)  # Wait before retry

    logger.error(f"Plan {plan_number} failed after {max_retries} attempts")
    return False

# Use it
run_with_retry("01")
```

## Real-Time Monitoring with Callbacks

Monitor HEC-RAS execution progress in real-time using callback objects.

### Console Monitoring

```python
from ras_commander.callbacks import ConsoleCallback

# Simple console output
callback = ConsoleCallback()
RasCmdr.compute_plan("01", stream_callback=callback)

# Verbose mode (shows all messages)
callback = ConsoleCallback(verbose=True)
RasCmdr.compute_plan("01", stream_callback=callback)
```

**Output Example**:
```
[Plan 01] Starting execution...
[Plan 01] Geometry Preprocessor Version 6.6
[Plan 01] Processing 2D Flow Areas...
[Plan 01] Computing Plan: 01
[Plan 01] SUCCESS in 45.2s
```

### File Logging

```python
from ras_commander.callbacks import FileLoggerCallback
from pathlib import Path

# Create logger that writes to files
callback = FileLoggerCallback(output_dir=Path("logs"))

RasCmdr.compute_plan("01", stream_callback=callback)
# Creates: logs/plan_01_execution.log with full details
```

### Progress Bar

```python
from ras_commander.callbacks import ProgressBarCallback

# Requires: pip install tqdm
callback = ProgressBarCallback()

RasCmdr.compute_plan("01", stream_callback=callback)
# Shows: Plan 01: 100%|████████| 1234/1234 [00:45<00:00, 27.42msg/s]
```

### Custom Callback

```python
from ras_commander.callbacks import ExecutionCallback

class AlertCallback(ExecutionCallback):
    """Send email alerts on completion."""

    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        status = "SUCCESS" if success else "FAILED"
        send_email(
            subject=f"Plan {plan_number} {status}",
            body=f"Execution completed in {duration:.1f}s"
        )

# Use custom callback
RasCmdr.compute_plan("01", stream_callback=AlertCallback())
```

**See**: [reference/callbacks.md](reference/callbacks.md) for complete callback protocol

## Parameter Reference

### plan_number

**Type**: `str` (recommended) or `int`
**Format**: "01", "02", ... "99"

```python
# ✅ CORRECT - Use string with zero-padding
RasCmdr.compute_plan("01")
RasCmdr.compute_plan("15")

# ⚠️ WORKS but not recommended - Integer without padding
RasCmdr.compute_plan(1)  # Converted internally to "01"
```

### dest_folder

**Type**: `str` or `Path` or `None`
**Default**: `None` (runs in original project)

```python
# Run in original project (modifies in-place)
RasCmdr.compute_plan("01", dest_folder=None)

# Run in subfolder (relative path)
RasCmdr.compute_plan("01", dest_folder="computation")

# Run in absolute path
RasCmdr.compute_plan("01", dest_folder=r"C:\Output\run1")
```

**When to Use**:
- ✅ Preserving original project files
- ✅ Running multiple scenarios
- ✅ Batch processing with organized outputs
- ❌ Simple one-time execution (use `None`)

### clear_geompre

**Type**: `bool`
**Default**: `False`

```python
# Keep preprocessed geometry (faster)
RasCmdr.compute_plan("01", clear_geompre=False)

# Force geometry reprocessing (slower, ensures correctness)
RasCmdr.compute_plan("01", clear_geompre=True)
```

**When `True` is Required**:
- ✅ Geometry was modified (Manning's n, terrain, etc.)
- ✅ 2D mesh was changed
- ✅ Troubleshooting geometry issues
- ❌ Geometry unchanged (wastes time)

### num_cores

**Type**: `int` or `None`
**Default**: `None` (HEC-RAS decides)

```python
# Let HEC-RAS decide
RasCmdr.compute_plan("01", num_cores=None)

# Use 4 cores
RasCmdr.compute_plan("01", num_cores=4)

# Use all available cores
import os
RasCmdr.compute_plan("01", num_cores=os.cpu_count())
```

**Performance Guidance**:
- **2D models**: Benefit significantly from multiple cores
- **1D models**: Limited benefit from parallelization
- **Optimal**: Usually 2-8 cores depending on model size
- **Too many**: Overhead can slow down execution

### verify

**Type**: `bool`
**Default**: `False`

```python
# Run without verification
success = RasCmdr.compute_plan("01", verify=False)

# Verify successful completion
success = RasCmdr.compute_plan("01", verify=True)

if not success:
    print("Execution failed or did not complete properly")
```

**What It Checks**:
- HDF file exists
- Contains "Complete Process" in compute messages

### skip_existing

**Type**: `bool`
**Default**: `False`

```python
# Always run plan
RasCmdr.compute_plan("01", skip_existing=False)

# Skip if results already exist
RasCmdr.compute_plan("01", skip_existing=True)
```

**Use Cases**:
- Resuming interrupted batch runs
- Incremental workflows
- Avoiding duplicate computation

## Verification and Error Checking

### Check Execution Success

```python
# Method 1: Return value with verify=True
success = RasCmdr.compute_plan("01", verify=True)
if success:
    print("Execution completed successfully")
else:
    print("Execution failed or incomplete")
```

### Check HDF File Created

```python
from pathlib import Path

hdf_file = Path("MyProject/MyProject.p01.hdf")
if hdf_file.exists():
    print("HDF file created")
else:
    print("Execution failed - no HDF file")
```

### Parse Compute Messages

```python
from ras_commander.hdf import HdfResultsPlan

# Read compute messages
hdf = HdfResultsPlan("MyProject/MyProject.p01.hdf")
messages = hdf.get_compute_messages()

# Check for success indicator
if "Complete Process" in messages:
    print("Success!")
else:
    print(f"Issues detected:\n{messages}")
```

### Validate Results

```python
# Check results are reasonable
wse = hdf.get_wse(time_index=-1)  # Final time step

if wse is not None and len(wse) > 0:
    print(f"Results extracted: {len(wse)} values")
    print(f"WSE range: {wse.min():.2f} to {wse.max():.2f} ft")

    # Check for unreasonable values
    if wse.max() > 10000 or wse.min() < -100:
        print("WARNING: Unreasonable water surface elevations")
else:
    print("No results found in HDF file")
```

## Performance Optimization

### Parallel vs Sequential

**Use `compute_parallel()` when**:
- Multiple independent plans to run
- Sufficient CPU cores available (e.g., 8+ cores for 4 plans)
- Plans don't compete for resources
- Time is critical

**Use `compute_test_mode()` when**:
- Debugging execution issues
- Limited system resources
- Plans are interdependent
- Sequential workflow required

### Geometry Preprocessing Strategy

**Reuse preprocessed geometry** (`clear_geompre=False`):
- 2x-10x faster for 2D models
- Only valid if geometry unchanged
- Default and recommended for most cases

**Force reprocessing** (`clear_geompre=True`):
- Required after ANY geometry modification
- Slower but ensures correctness
- Use after: Manning's n changes, terrain updates, mesh modifications

### Destination Folder Management

```python
# For parameter sweeps, organize by parameter
for n_value in [0.03, 0.04, 0.05, 0.06]:
    # Update Manning's n
    RasGeo.update_mannings_n(geom_file="g01", n_value=n_value)

    # Run in organized folder
    RasCmdr.compute_plan(
        "01",
        dest_folder=f"sensitivity/n_{n_value:.3f}",
        clear_geompre=True,
        overwrite_dest=True
    )
```

## Troubleshooting

### Plan Doesn't Execute

**Checklist**:
1. ✅ Project initialized? (`init_ras_project()` called?)
2. ✅ Plan exists? (Check `ras.plan_df`)
3. ✅ HEC-RAS installed? (Correct version?)
4. ✅ Permissions? (Write access to project folder?)
5. ✅ Path valid? (No special characters, not too long?)

```python
# Verify initialization
from ras_commander import ras

print(f"Project folder: {ras.project_folder}")
print(f"HEC-RAS executable: {ras.ras_exe_path}")
print(f"Available plans:\n{ras.plan_df}")
```

### HDF File Not Created

**Diagnosis Steps**:
1. Check compute messages (if HDF partially exists)
2. Enable verbose callback to see execution progress
3. Check Windows Event Log for HEC-RAS crashes
4. Try running plan manually in HEC-RAS GUI

```python
# Enable verbose monitoring
from ras_commander.callbacks import ConsoleCallback

RasCmdr.compute_plan(
    "01",
    stream_callback=ConsoleCallback(verbose=True)
)
```

### Performance Issues

**Optimization Checklist**:
- ✅ Reduce `num_cores` if too high (try 2-4 instead of max)
- ✅ Use `compute_parallel()` for multiple plans
- ✅ Set `clear_geompre=False` if geometry unchanged
- ✅ Use SSD for project files (not network drive)
- ✅ Close unnecessary applications
- ✅ Check model size (simplify if too large)

### Destination Folder Errors

```python
# ❌ ERROR: Destination exists and not empty
RasCmdr.compute_plan("01", dest_folder="existing_folder")
# ValueError: Destination folder 'existing_folder' exists and is not empty

# ✅ FIX: Use overwrite_dest=True
RasCmdr.compute_plan("01", dest_folder="existing_folder", overwrite_dest=True)
```

## See Also

- **Detailed API**: [reference/api.md](reference/api.md) - Complete parameter reference
- **Callbacks**: [reference/callbacks.md](reference/callbacks.md) - Real-time monitoring
- **HEC-RAS Execution**: `C:\GH\ras-commander\.claude\rules\hec-ras\execution.md`
- **Remote Execution**: `C:\GH\ras-commander\.claude\rules\hec-ras\remote.md`
- **Static Classes**: `C:\GH\ras-commander\.claude\rules\python\static-classes.md`
- **Results Extraction**: `.claude/skills/extracting-hecras-results/` (coming soon)

---

**Key Takeaway**: Use `RasCmdr.compute_plan()` for single plans, `compute_parallel()` for multiple plans in parallel, and `compute_test_mode()` for sequential debugging. Always pass plan numbers as strings ("01", not 1), and use `dest_folder` to preserve original projects.
