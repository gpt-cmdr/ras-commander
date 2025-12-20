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

After execution, verify results were generated and the run completed without errors. This is critical for determining if the simulation succeeded.

### Quick Verification

```python
from ras_commander import init_ras_project, ras, HdfResultsPlan

# Refresh project data to see new results
init_ras_project(ras.project_folder, "6.5")

# Check for HDF results
hdf_entries = ras.get_hdf_entries()
print(f"Found {len(hdf_entries)} HDF result files")
```

### Check Compute Messages for Errors

The compute messages contain the HEC-RAS log output. Always check for errors:

```python
from ras_commander import HdfResultsPlan

# Get computation messages (accepts plan number or HDF path)
msgs = HdfResultsPlan.get_compute_messages("01")

if msgs:
    # Check for error keywords
    if 'ERROR' in msgs.upper() or 'FAILED' in msgs.upper():
        print("ERRORS DETECTED in computation!")
        # Print error lines
        for line in msgs.split('\n'):
            if 'ERROR' in line.upper() or 'FAILED' in line.upper():
                print(f"  {line}")
    else:
        print("Computation completed without errors")
else:
    print("No compute messages - run may not have completed")
```

### Check Volume Accounting

Volume accounting verifies mass conservation. A large imbalance indicates problems:

```python
from ras_commander import HdfResultsPlan

volume_df = HdfResultsPlan.get_volume_accounting("01")

if volume_df is not None:
    print("Volume Accounting Data:")
    # Display as transposed for readability
    print(volume_df.T)
else:
    print("No volume accounting - run may have failed")
```

### Check Unsteady Results Exist

Verify unsteady results were written to the HDF:

```python
from ras_commander import HdfResultsPlan

# Basic unsteady info
try:
    info = HdfResultsPlan.get_unsteady_info("01")
    print("Unsteady results present")
    print(info.T)
except KeyError:
    print("No unsteady results found")

# Detailed unsteady summary
try:
    summary = HdfResultsPlan.get_unsteady_summary("01")
    print("\nUnsteady Summary:")
    print(summary.T)
except KeyError:
    print("No unsteady summary - check if run completed")
```

### Check Runtime Performance

Review computation timing and performance:

```python
from ras_commander import HdfResultsPlan

runtime = HdfResultsPlan.get_runtime_data("01")

if runtime is not None:
    print(f"Plan: {runtime['Plan Name'].iloc[0]}")
    print(f"Simulation: {runtime['Simulation Time (hr)'].iloc[0]:.1f} hr")
    print(f"Compute Time: {runtime['Complete Process (hr)'].iloc[0]:.3f} hr")
    print(f"Speed: {runtime['Complete Process Speed (hr/hr)'].iloc[0]:.0f}x realtime")
```

### Complete Verification Example

```python
from ras_commander import init_ras_project, HdfResultsPlan

init_ras_project("/path/to/project", "6.5")

def check_run_success(plan_number):
    """Check if a plan run was successful."""
    print(f"\n{'='*50}")
    print(f"Verifying Plan {plan_number}")
    print('='*50)

    success = True

    # 1. Check compute messages
    msgs = HdfResultsPlan.get_compute_messages(plan_number)
    if msgs:
        has_errors = any(kw in msgs.upper()
                        for kw in ['ERROR', 'FAILED', 'UNSTABLE'])
        if has_errors:
            print("[FAIL] Errors found in compute messages")
            success = False
        else:
            print("[OK] No errors in compute messages")
    else:
        print("[FAIL] No compute messages found")
        success = False

    # 2. Check volume accounting
    volume = HdfResultsPlan.get_volume_accounting(plan_number)
    if volume is not None:
        print("[OK] Volume accounting data present")
    else:
        print("[WARN] No volume accounting data")

    # 3. Check unsteady results
    try:
        HdfResultsPlan.get_unsteady_summary(plan_number)
        print("[OK] Unsteady results present")
    except:
        print("[WARN] No unsteady summary")

    # 4. Runtime data
    runtime = HdfResultsPlan.get_runtime_data(plan_number)
    if runtime is not None:
        speed = runtime['Complete Process Speed (hr/hr)'].iloc[0]
        print(f"[INFO] Compute speed: {speed:.0f}x realtime")

    print(f"\nOverall: {'SUCCESS' if success else 'NEEDS REVIEW'}")
    return success

# Usage
check_run_success("01")
```

See [Workflows and Patterns](workflows-and-patterns.md#verifying-run-success) for more detailed verification patterns including batch verification.

## Detailed Compute Message Logging

Monitor HEC-RAS execution in real-time with stream callbacks. This provides live feedback during computation and enables automated error detection.

### Stream Callbacks

The `stream_callback` parameter accepts callback objects for real-time monitoring:

```python
from ras_commander import RasCmdr
from ras_commander.callbacks import ConsoleCallback

# Monitor execution with console output
success = RasCmdr.compute_plan(
    "01",
    stream_callback=ConsoleCallback(verbose=True)
)
```

### Available Callbacks

```python
from ras_commander.callbacks import (
    ConsoleCallback,      # Print to console
    FileLoggerCallback,   # Log to file
    ProgressBarCallback,  # Show progress bar (requires tqdm)
    SynchronizedCallback  # Thread-safe wrapper for parallel execution
)

# Console callback
RasCmdr.compute_plan("01", stream_callback=ConsoleCallback(verbose=True))

# File logger callback
RasCmdr.compute_plan("01", stream_callback=FileLoggerCallback("run.log"))

# Progress bar (requires: pip install tqdm)
RasCmdr.compute_plan("01", stream_callback=ProgressBarCallback())
```

### Custom Callbacks

Create custom callbacks for specialized monitoring:

```python
from ras_commander.callbacks import ExecutionCallback

class ErrorDetectionCallback(ExecutionCallback):
    """Callback that stops execution on first error."""

    def on_exec_message(self, message):
        # Check for error keywords
        if any(kw in message.upper() for kw in ['ERROR', 'FAILED', 'UNSTABLE']):
            print(f"❌ ERROR DETECTED: {message}")
            # Could raise exception, send alert, etc.
        elif 'warning' in message.lower():
            print(f"⚠ WARNING: {message}")
        else:
            # Normal message
            print(f"ℹ {message}")

# Use custom callback
RasCmdr.compute_plan("01", stream_callback=ErrorDetectionCallback())
```

### Callback Methods

Custom callbacks can implement these methods:

```python
class MyCallback(ExecutionCallback):
    def on_start(self, plan_number):
        """Called when execution starts."""
        print(f"Starting plan {plan_number}")

    def on_exec_message(self, message):
        """Called for each HEC-RAS message during execution."""
        print(f"HEC-RAS: {message}")

    def on_complete(self, success):
        """Called when execution completes."""
        if success:
            print("✓ Execution completed successfully")
        else:
            print("✗ Execution failed")

    def on_error(self, error):
        """Called if exception occurs."""
        print(f"Exception: {error}")
```

### Parallel Execution with Callbacks

Use `SynchronizedCallback` wrapper for thread-safe logging:

```python
from ras_commander.callbacks import ConsoleCallback, SynchronizedCallback

# Wrap callback for thread safety
safe_callback = SynchronizedCallback(ConsoleCallback(verbose=True))

# Use with parallel execution
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=3,
    stream_callback=safe_callback  # Thread-safe logging
)
```

### Post-Execution Message Review

Review compute messages after execution completes:

```python
from ras_commander import HdfResultsPlan

# Get all compute messages
msgs = HdfResultsPlan.get_compute_messages("01")

# Parse for specific information
for line in msgs.split('\n'):
    if 'time step' in line.lower():
        print(line)  # Timestep information
    elif 'iterations' in line.lower():
        print(line)  # Iteration counts
    elif 'error' in line.lower():
        print(f"⚠ {line}")  # Errors
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
