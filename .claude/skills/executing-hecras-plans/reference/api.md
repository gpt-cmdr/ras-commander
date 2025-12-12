# RasCmdr API Reference

Complete API documentation for HEC-RAS plan execution methods.

## Overview

`RasCmdr` is a static class providing three execution modes:
1. **Single plan**: `compute_plan()` - Execute one plan with full control
2. **Parallel**: `compute_parallel()` - Run multiple plans simultaneously
3. **Sequential test**: `compute_test_mode()` - Run plans one at a time for debugging

All methods are static and do not require instantiation.

## compute_plan()

Execute a single HEC-RAS plan with full parameter control.

### Signature

```python
@staticmethod
def compute_plan(
    plan_number: Union[str, Number, Path],
    dest_folder: Union[str, Path, None] = None,
    ras_object: Optional[RasPrj] = None,
    clear_geompre: bool = False,
    num_cores: Optional[int] = None,
    overwrite_dest: bool = False,
    skip_existing: bool = False,
    verify: bool = False,
    stream_callback: Optional[Callable] = None
) -> bool
```

### Parameters

#### plan_number
- **Type**: `str` (recommended), `int`, or `Path`
- **Required**: Yes
- **Format**: Two-digit string ("01", "02", ..., "99") or plan file path
- **Description**: Identifies which HEC-RAS plan to execute

**Examples**:
```python
RasCmdr.compute_plan("01")  # String (recommended)
RasCmdr.compute_plan(1)     # Integer (converted to "01")
RasCmdr.compute_plan(Path("project.p01"))  # Full path
```

#### dest_folder
- **Type**: `str`, `Path`, or `None`
- **Default**: `None`
- **Description**: Destination folder for computation
  - `None`: Run in original project folder (modifies in-place)
  - String: Created in same parent directory as project
  - Path: Full absolute path to destination

**Examples**:
```python
# Run in original project
RasCmdr.compute_plan("01", dest_folder=None)

# Relative folder name (created in parent of project folder)
RasCmdr.compute_plan("01", dest_folder="computation")

# Absolute path
RasCmdr.compute_plan("01", dest_folder=Path("C:/Output/run1"))
```

**Behavior**:
- Project files copied to destination before execution
- Original project remains unmodified
- Results written to destination folder

#### ras_object
- **Type**: `RasPrj` or `None`
- **Default**: `None` (uses global `ras` instance)
- **Description**: Specific RAS project object to use

**Examples**:
```python
from ras_commander import RasPrj, init_ras_project

# Use global ras object (default)
init_ras_project("C:/Models/Project1", "6.5")
RasCmdr.compute_plan("01")  # Uses global ras

# Use specific ras object
project2 = RasPrj()
init_ras_project("C:/Models/Project2", "6.5", ras_object=project2)
RasCmdr.compute_plan("01", ras_object=project2)
```

#### clear_geompre
- **Type**: `bool`
- **Default**: `False`
- **Description**: Clear geometry preprocessor files before execution

**Behavior**:
- `True`: Deletes `.g##.hdf` files (forces geometry reprocessing)
- `False`: Keeps existing preprocessor files (faster)

**When to Use `True`**:
- Geometry was modified (Manning's n, terrain, structures)
- 2D mesh was changed
- Troubleshooting geometry preprocessing issues

**Performance Impact**:
- `False`: 2x-10x faster for 2D models (reuses preprocessor)
- `True`: Required for correctness after geometry changes

**Examples**:
```python
# Geometry unchanged - fast execution
RasCmdr.compute_plan("01", clear_geompre=False)

# Geometry modified - force reprocessing
RasCmdr.compute_plan("01", clear_geompre=True)
```

#### num_cores
- **Type**: `int` or `None`
- **Default**: `None`
- **Description**: Number of CPU cores for computation
  - `None`: HEC-RAS uses current plan file setting (not modified)
  - Integer: Updates plan file to use specified core count

**Guidelines**:
- **1-2 cores**: Highest efficiency per core, good for small models
- **3-8 cores**: Good balance for most models
- **>8 cores**: Diminishing returns due to overhead
- **2D models**: Benefit significantly from multiple cores
- **1D models**: Limited parallelization benefit

**Examples**:
```python
# Use plan file setting
RasCmdr.compute_plan("01", num_cores=None)

# Use 4 cores
RasCmdr.compute_plan("01", num_cores=4)

# Use all available cores
import os
RasCmdr.compute_plan("01", num_cores=os.cpu_count())
```

#### overwrite_dest
- **Type**: `bool`
- **Default**: `False`
- **Description**: Allow overwriting existing destination folder

**Behavior**:
- `False`: Raises `ValueError` if destination exists and is not empty (safe default)
- `True`: Deletes existing destination folder and recreates it

**Examples**:
```python
# Safe mode - fail if destination exists
RasCmdr.compute_plan("01", dest_folder="output", overwrite_dest=False)
# ValueError if output/ already contains files

# Overwrite mode - useful for re-runs
RasCmdr.compute_plan("01", dest_folder="output", overwrite_dest=True)
```

#### skip_existing
- **Type**: `bool`
- **Default**: `False`
- **Description**: Skip computation if HDF results already exist with "Complete Process"

**Behavior**:
- `False`: Always run computation (default)
- `True`: Check if HDF exists with "Complete Process" and skip if found

**When to Use**:
- Resuming interrupted batch runs
- Incremental workflows
- Avoiding duplicate computation

**Note**: Check happens AFTER copying to destination folder (if `dest_folder` specified)

**Examples**:
```python
# Always run
RasCmdr.compute_plan("01", skip_existing=False)

# Skip if already completed
for plan in ["01", "02", "03"]:
    RasCmdr.compute_plan(
        plan,
        skip_existing=True,  # Resumes from where it left off
        dest_folder=f"run_{plan}"
    )
```

#### verify
- **Type**: `bool`
- **Default**: `False`
- **Description**: Verify computation completed successfully after execution

**Verification Process**:
1. Check HDF file exists
2. Read compute messages from HDF
3. Look for "Complete Process" string
4. Return `False` if verification fails even if subprocess succeeded

**Examples**:
```python
# Run without verification
success = RasCmdr.compute_plan("01", verify=False)
# Returns True if subprocess completes (may not have valid results)

# Run with verification
success = RasCmdr.compute_plan("01", verify=True)
# Returns True only if HDF contains "Complete Process"

if not success:
    print("Execution failed or incomplete")
```

#### stream_callback
- **Type**: `Callable` or `None`
- **Default**: `None`
- **Description**: Callback object for real-time execution monitoring

**Requirements**:
- Must implement `ExecutionCallback` protocol (all methods optional)
- Must be thread-safe when used with `compute_parallel()`

**Available Methods** (all optional):
- `on_prep_start(plan_number: str)` - Before geometry preprocessing
- `on_prep_complete(plan_number: str)` - After preprocessing complete
- `on_exec_start(plan_number: str, command: str)` - When subprocess starts
- `on_exec_message(plan_number: str, message: str)` - For each .bco message
- `on_exec_complete(plan_number: str, success: bool, duration: float)` - When finished
- `on_verify_result(plan_number: str, verified: bool)` - After verification

**Examples**:
```python
from ras_commander.callbacks import ConsoleCallback, FileLoggerCallback

# Console output
RasCmdr.compute_plan("01", stream_callback=ConsoleCallback())

# File logging
RasCmdr.compute_plan("01", stream_callback=FileLoggerCallback("logs"))
```

**See**: [callbacks.md](callbacks.md) for complete callback reference

### Return Value

- **Type**: `bool`
- **Description**: Execution success status
  - `True`: Execution completed (and verification passed if `verify=True`)
  - `False`: Execution failed (or verification failed)

**Examples**:
```python
# Check return value
success = RasCmdr.compute_plan("01")
if success:
    print("Plan executed successfully")
else:
    print("Execution failed")

# With verification
success = RasCmdr.compute_plan("01", verify=True)
if success:
    print("Execution completed with valid results")
```

### Exceptions

#### ValueError
- **When**: Destination folder exists and is not empty (when `overwrite_dest=False`)
- **Fix**: Use `overwrite_dest=True` or choose different destination

```python
try:
    RasCmdr.compute_plan("01", dest_folder="existing")
except ValueError as e:
    print(f"Destination exists: {e}")
    # Fix: overwrite or use different folder
    RasCmdr.compute_plan("01", dest_folder="existing", overwrite_dest=True)
```

#### FileNotFoundError
- **When**: Plan file or project file cannot be found
- **Fix**: Verify plan number and project initialization

```python
from ras_commander import ras

# Check if project initialized
try:
    ras.check_initialized()
except RuntimeError:
    print("Project not initialized - call init_ras_project()")

# Check if plan exists
print(ras.plan_df)  # List available plans
```

#### PermissionError
- **When**: Cannot access or write to destination folder
- **Fix**: Check file permissions, close HEC-RAS GUI, run as administrator

#### subprocess.CalledProcessError
- **When**: HEC-RAS execution fails
- **Fix**: Check compute messages, verify model validity, try in HEC-RAS GUI

### Examples

#### Basic Execution
```python
from ras_commander import init_ras_project, RasCmdr

init_ras_project("C:/Models/MyProject", "6.5")
RasCmdr.compute_plan("01")
```

#### Separate Destination Folder
```python
RasCmdr.compute_plan(
    "01",
    dest_folder="computation_folder",
    overwrite_dest=True
)
```

#### With Performance Options
```python
RasCmdr.compute_plan(
    "01",
    num_cores=4,
    clear_geompre=True,
    verify=True
)
```

#### With Real-Time Monitoring
```python
from ras_commander.callbacks import ConsoleCallback

callback = ConsoleCallback(verbose=True)
RasCmdr.compute_plan("01", stream_callback=callback)
```

#### Complete Parameter Set
```python
success = RasCmdr.compute_plan(
    plan_number="01",
    dest_folder="output/scenario1",
    num_cores=4,
    clear_geompre=True,
    overwrite_dest=True,
    skip_existing=False,
    verify=True,
    stream_callback=ConsoleCallback()
)

if not success:
    print("Execution failed")
```

---

## compute_parallel()

Execute multiple HEC-RAS plans in parallel using separate worker folders.

### Signature

```python
@staticmethod
def compute_parallel(
    plans_to_run: List[Union[str, Number]],
    ras_object: Optional[RasPrj] = None,
    clear_geompre: bool = False,
    num_cores: Optional[int] = None,
    overwrite_dest: bool = False,
    stream_callback: Optional[Callable] = None
) -> Dict[str, bool]
```

### Parameters

#### plans_to_run
- **Type**: `List[Union[str, int]]`
- **Required**: Yes
- **Description**: List of plan numbers to execute

**Examples**:
```python
RasCmdr.compute_parallel(["01", "02", "03"])
RasCmdr.compute_parallel([1, 2, 3])  # Also works
```

#### Other Parameters
Same as `compute_plan()` except:
- No `dest_folder` parameter (workers created automatically)
- No `skip_existing` parameter
- No `verify` parameter

### How It Works

1. **Create Workers**: Separate folder for each plan
   - Format: `{project_folder}_worker_{plan_number}`
2. **Copy Project**: Full project copied to each worker
3. **Execute Parallel**: All plans run simultaneously
4. **Consolidate**: Results copied back to original project

### Return Value

- **Type**: `Dict[str, bool]`
- **Description**: Dictionary mapping plan numbers to success status

**Example**:
```python
results = RasCmdr.compute_parallel(["01", "02", "03"])
# Returns: {"01": True, "02": True, "03": False}

for plan, success in results.items():
    if success:
        print(f"Plan {plan} succeeded")
    else:
        print(f"Plan {plan} failed")
```

### Examples

#### Basic Parallel Execution
```python
RasCmdr.compute_parallel(["01", "02", "03", "04"])
```

#### With Core Count
```python
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    num_cores=4  # Each plan uses 4 cores
)
```

#### With Monitoring
```python
from ras_commander.callbacks import ConsoleCallback

results = RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=ConsoleCallback()
)

# Check results
all_passed = all(results.values())
if all_passed:
    print("All plans completed successfully")
```

---

## compute_test_mode()

Execute multiple plans sequentially in a test folder (for debugging).

### Signature

```python
@staticmethod
def compute_test_mode(
    plans_to_run: List[Union[str, Number]],
    ras_object: Optional[RasPrj] = None,
    clear_geompre: bool = False,
    num_cores: Optional[int] = None,
    stream_callback: Optional[Callable] = None
) -> Dict[str, bool]
```

### Parameters

Same as `compute_parallel()` but:
- Plans executed ONE AT A TIME (sequential)
- Uses single test folder (not separate workers)

### How It Works

1. **Create Test Folder**: `{project_folder}_test_mode`
2. **Copy Project**: Project copied to test folder
3. **Execute Sequential**: Run plans one at a time
4. **Consolidate**: Results copied back to original

### Return Value

- **Type**: `Dict[str, bool]`
- **Description**: Dictionary mapping plan numbers to success status

### When to Use

- **Debugging**: See each plan's execution isolated
- **Limited Resources**: Don't have cores for parallel execution
- **Sequential Dependencies**: Plans must run in order
- **Development**: Testing new workflows

### Examples

#### Basic Sequential Execution
```python
RasCmdr.compute_test_mode(["01", "02", "03"])
```

#### With Verbose Monitoring
```python
from ras_commander.callbacks import ConsoleCallback

results = RasCmdr.compute_test_mode(
    plans_to_run=["01", "02"],
    stream_callback=ConsoleCallback(verbose=True)
)
```

---

## Static Class Pattern

**IMPORTANT**: `RasCmdr` uses static methods - do NOT instantiate.

```python
# ✅ CORRECT - Call methods directly on class
from ras_commander import RasCmdr
RasCmdr.compute_plan("01")

# ❌ WRONG - Do not instantiate
commander = RasCmdr()  # TypeError or unexpected behavior
```

---

## Thread Safety

All execution methods are designed to be thread-safe EXCEPT:
- Callbacks must be thread-safe for `compute_parallel()`
- Use `SynchronizedCallback` wrapper if needed

```python
from ras_commander.callbacks import SynchronizedCallback, FileLoggerCallback

# Make callback thread-safe
callback = SynchronizedCallback(FileLoggerCallback("logs"))

RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    stream_callback=callback
)
```

---

## See Also

- **Callbacks**: [callbacks.md](callbacks.md) - Real-time monitoring reference
- **Main Skill**: [../skill.md](../skill.md) - Common patterns and workflows
- **HEC-RAS Rules**: `C:\GH\ras-commander\.claude\rules\hec-ras\execution.md`
- **Remote Execution**: `C:\GH\ras-commander\.claude\rules\hec-ras\remote.md`
