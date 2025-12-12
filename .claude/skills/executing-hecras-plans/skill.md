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

This skill helps you execute HEC-RAS plans using ras-commander. It serves as a navigator to primary sources containing comprehensive documentation and working examples.

## Primary Sources

### 1. Execution Patterns (CLAUDE.md)
**Location**: `C:\GH\ras-commander\ras_commander\CLAUDE.md`

**See sections**:
- **"Plan Execution"** - Core execution methods and parameters
- **"Execution Modes"** - Four modes: single, parallel, sequential, remote
- **"Plan Execution Parameters"** - Complete parameter reference
- **"Common Workflow Pattern"** - Initialize → Execute → Extract

**Key execution modes**:
```python
# Single plan
RasCmdr.compute_plan("01", dest_folder="run1", num_cores=4)

# Parallel local
RasCmdr.compute_parallel(["01", "02", "03"], max_workers=3)

# Sequential test
RasCmdr.compute_test_mode(["01", "02"])
```

### 2. Working Examples (Jupyter Notebooks)

**Core execution notebooks**:
- `examples/05_single_plan_execution.ipynb` - Complete single plan workflow
- `examples/06_executing_plan_sets.ipynb` - Plan sets and batch processing
- `examples/07_sequential_plan_execution.ipynb` - Test mode execution
- `examples/08_parallel_execution.ipynb` - Parallel execution with performance analysis

**Advanced workflows**:
- `examples/23_remote_execution_psexec.ipynb` - Distributed execution
- Real-time monitoring examples (search for `stream_callback` usage)

### 3. Code Documentation (Docstrings)

**Location**: `C:\GH\ras-commander\ras_commander\RasCmdr.py`

**Read docstrings for**:
- `RasCmdr.compute_plan()` - Lines 139-250+ (comprehensive parameter docs)
- `RasCmdr.compute_parallel()` - Parallel execution details
- `RasCmdr.compute_test_mode()` - Sequential debugging mode

**Callback protocol**: `C:\GH\ras-commander\ras_commander\callbacks.py`
- `ExecutionCallback` - Protocol definition
- `ConsoleCallback`, `FileLoggerCallback`, `ProgressBarCallback` - Implementations

## Quick Reference

### Single Plan Execution

**Basic pattern**:
```python
from ras_commander import init_ras_project, RasCmdr

# Initialize
init_ras_project(r"C:\Models\MyProject", "6.6")

# Execute
RasCmdr.compute_plan("01")
```

**With destination folder** (preserves original):
```python
RasCmdr.compute_plan("01", dest_folder="computation_folder")
```

**With monitoring**:
```python
from ras_commander.callbacks import ConsoleCallback

RasCmdr.compute_plan(
    "01",
    stream_callback=ConsoleCallback(verbose=True)
)
```

**Key parameters**:
- `plan_number` - "01", "02", etc. (use strings)
- `dest_folder` - None = in-place, path = separate folder
- `num_cores` - CPU cores to use (None = plan default)
- `clear_geompre` - True after geometry changes
- `verify` - True to check completion
- `skip_existing` - True to resume interrupted runs
- `stream_callback` - Real-time monitoring object

### Parallel Execution

**Execute multiple plans**:
```python
# All plans with 3 workers
RasCmdr.compute_parallel(max_workers=3, num_cores=2)

# Specific plans
RasCmdr.compute_parallel(
    plans_to_run=["01", "02", "03"],
    max_workers=3,
    num_cores=2
)
```

**Worker allocation**:
- `max_workers` - Parallel plan executions
- `num_cores` - Cores per plan
- Total cores used = `max_workers × num_cores`
- Optimal: 2-4 cores per worker, workers ≤ physical cores / num_cores

### Sequential Test Mode

**For debugging**:
```python
# Run plans one at a time in test folder
RasCmdr.compute_test_mode(["01", "02", "03"])
```

**Difference from parallel**:
- ONE plan at a time (not simultaneous)
- Single test folder (not multiple workers)
- Easier to debug issues

## Common Patterns

### Pattern: Preserve Original Project
```python
# Run in separate folder, leave original untouched
RasCmdr.compute_plan(
    "01",
    dest_folder="results/run_2024_12_11",
    overwrite_dest=True,
    verify=True
)
```

### Pattern: Geometry Modification Workflow
```python
from ras_commander.RasGeo import RasGeo

# Modify geometry
RasGeo.update_mannings_n(geom_file="g01", landcover_map={...})

# Run with forced reprocessing
RasCmdr.compute_plan("01", clear_geompre=True)  # CRITICAL
```

### Pattern: Batch Scenario Processing
```python
scenarios = {
    "baseline": {"plan": "01", "dest": "output/baseline"},
    "mitigation": {"plan": "02", "dest": "output/mitigation"},
}

for name, config in scenarios.items():
    RasCmdr.compute_plan(
        config["plan"],
        dest_folder=config["dest"],
        verify=True
    )
```

### Pattern: Skip Already Completed
```python
# Resume interrupted batch run
for plan in ["01", "02", "03"]:
    RasCmdr.compute_plan(
        plan,
        skip_existing=True,  # Skip if already complete
        verify=True
    )
```

## Real-Time Monitoring

### Console Output
```python
from ras_commander.callbacks import ConsoleCallback

callback = ConsoleCallback(verbose=True)
RasCmdr.compute_plan("01", stream_callback=callback)
```

**Output example**:
```
[Plan 01] Starting execution...
[Plan 01] Geometry Preprocessor Version 6.6
[Plan 01] Computing Plan: 01
[Plan 01] SUCCESS in 45.2s
```

### File Logging
```python
from ras_commander.callbacks import FileLoggerCallback
from pathlib import Path

callback = FileLoggerCallback(output_dir=Path("logs"))
RasCmdr.compute_plan("01", stream_callback=callback)
# Creates: logs/plan_01_execution.log
```

### Progress Bar
```python
from ras_commander.callbacks import ProgressBarCallback

# Requires: pip install tqdm
callback = ProgressBarCallback()
RasCmdr.compute_plan("01", stream_callback=callback)
```

### Custom Callback
```python
from ras_commander.callbacks import ExecutionCallback

class AlertCallback(ExecutionCallback):
    def on_exec_complete(self, plan_number: str, success: bool, duration: float):
        send_email(subject=f"Plan {plan_number} {'SUCCESS' if success else 'FAILED'}")

RasCmdr.compute_plan("01", stream_callback=AlertCallback())
```

**Available callback methods** (all optional):
- `on_prep_start()` - Before geometry preprocessing
- `on_prep_complete()` - After preprocessing
- `on_exec_start()` - HEC-RAS subprocess starts
- `on_exec_message()` - Each .bco file message (real-time)
- `on_exec_complete()` - Execution finishes
- `on_verify_result()` - After verification (if verify=True)

**Thread safety**: Use `SynchronizedCallback` wrapper for parallel execution

## Verification

### Return Value Check
```python
success = RasCmdr.compute_plan("01", verify=True)
if not success:
    print("Execution failed or incomplete")
```

### Parse Compute Messages
```python
from ras_commander.hdf import HdfResultsPlan

messages = HdfResultsPlan.get_compute_messages("01")
if "Complete Process" in messages:
    print("Success!")
```

### Validate Results
```python
wse = HdfResultsPlan.get_wse("01", time_index=-1)
if wse is not None:
    print(f"WSE range: {wse.min():.2f} to {wse.max():.2f} ft")
```

## Performance Optimization

### Geometry Preprocessing
- **Keep** (`clear_geompre=False`): 2x-10x faster, only if geometry unchanged
- **Clear** (`clear_geompre=True`): Required after ANY geometry modification

### Core Count
- **2-4 cores**: Good balance for most models
- **1-2 cores**: Highest efficiency per core
- **>8 cores**: Diminishing returns, overhead may slow execution

### Parallel vs Sequential
**Use parallel when**:
- Multiple independent plans
- Sufficient CPU cores (8+ for 4 plans)
- Time is critical

**Use sequential when**:
- Debugging execution issues
- Limited system resources
- Plans are interdependent

## Troubleshooting

### Plan Doesn't Execute
**Checklist**:
1. Project initialized? (`init_ras_project()` called?)
2. Plan exists? (Check `ras.plan_df`)
3. HEC-RAS installed? (Correct version?)
4. Permissions? (Write access to folder?)

```python
from ras_commander import ras
print(f"Project: {ras.project_folder}")
print(f"RAS executable: {ras.ras_exe_path}")
print(ras.plan_df)
```

### HDF File Not Created
**Diagnosis**:
1. Enable verbose callback to see execution progress
2. Check compute messages (if HDF partially exists)
3. Try running plan manually in HEC-RAS GUI

```python
from ras_commander.callbacks import ConsoleCallback
RasCmdr.compute_plan("01", stream_callback=ConsoleCallback(verbose=True))
```

### Performance Issues
**Optimization checklist**:
- ✅ Use `compute_parallel()` for multiple plans
- ✅ Set `clear_geompre=False` if geometry unchanged
- ✅ Try 2-4 cores instead of max
- ✅ Use SSD for project files (not network drive)
- ✅ Close unnecessary applications

## Where to Learn More

### CLAUDE.md Sections
- **"Plan Execution"** - Core execution API
- **"Execution Modes"** - Four execution patterns
- **"Performance Guidance"** - CPU and execution mode optimization
- **"Real-Time Computation Messages"** - Callback system (v0.88.0+)

### Example Notebooks
- **05** - Single plan execution walkthrough
- **06** - Plan sets and batch processing
- **07** - Sequential test mode
- **08** - Parallel execution with performance comparison
- **23** - Remote/distributed execution

### Code Docstrings
- **RasCmdr.py** - Complete API reference with examples
- **callbacks.py** - Real-time monitoring protocol and implementations
- **BcoMonitor.py** - .bco file monitoring internals

### Related Rules
- `.claude/rules/hec-ras/execution.md` - Detailed execution patterns
- `.claude/rules/hec-ras/remote.md` - Remote execution configuration
- `.claude/rules/python/static-classes.md` - Why RasCmdr is static

---

**Remember**: This skill is a navigator. For detailed documentation, comprehensive examples, and complete API reference, always consult the primary sources listed above.
