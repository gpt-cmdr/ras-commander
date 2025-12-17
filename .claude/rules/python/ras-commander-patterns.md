# RAS Commander Specific Patterns

**Context**: ras-commander library-specific coding patterns
**Priority**: High - affects correctness of multi-project code
**Auto-loads**: Yes (applies to all ras-commander code)

## Overview

This file documents patterns specific to ras-commander that extend beyond general Python conventions. These patterns ensure correct operation when working with HEC-RAS projects, especially in scenarios involving multiple projects or nested function calls.

## Context Object Discipline

### The ras_object Parameter Pattern

**Rule**: When a function creates a local `ras` object via `init_ras_project()`, it MUST pass that object to ALL downstream ras-commander function calls via the `ras_object` parameter.

### Why This Matters

Most ras-commander static methods accept an optional `ras_object` parameter. If not provided, they fall back to the global `ras` object. This fallback can cause subtle bugs when:

1. A function initializes its own project context
2. Downstream calls don't receive the local context
3. Those calls use the global `ras` object (wrong project)
4. File paths resolve incorrectly, causing FileNotFoundError or data corruption

### Correct Pattern

```python
from ras_commander import init_ras_project, RasPlan, RasCmdr
from ras_commander.hdf import HdfMesh, HdfResultsMesh

def process_project(project_folder):
    """Process a HEC-RAS project with sensitivity analysis."""

    # Create local ras context
    ras = init_ras_project(project_folder, "6.6")

    # ✅ CORRECT: Pass ras_object to ALL calls
    new_plan = RasPlan.clone_plan("01", new_plan_shortid="modified", ras_object=ras)
    new_geom = RasPlan.clone_geom("01", ras_object=ras)
    RasPlan.set_geom(new_plan, new_geom, ras_object=ras)

    RasCmdr.compute_parallel(
        plan_number=[new_plan],
        ras_object=ras,  # CRITICAL
        max_workers=2
    )

    mesh_cells = HdfMesh.get_mesh_cell_points(new_plan, ras_object=ras)
    results = HdfResultsMesh.get_mesh_cells_timeseries(new_plan, ras_object=ras)

    return results
```

### Incorrect Pattern

```python
def process_project(project_folder):
    """BROKEN: Missing ras_object parameters."""

    # Create local ras context
    ras = init_ras_project(project_folder, "6.6")

    # ❌ WRONG: Missing ras_object parameter
    new_plan = RasPlan.clone_plan("01", new_plan_shortid="modified")
    # Uses global ras object - wrong project context!

    # ❌ WRONG: Missing ras_object parameter
    RasCmdr.compute_parallel(plan_number=[new_plan], max_workers=2)
    # Looks for files in global ras project folder - FileNotFoundError!

    # ❌ WRONG: Missing ras_object parameter
    mesh_cells = HdfMesh.get_mesh_cell_points(new_plan)
    # Tries to open HDF from global ras project - FileNotFoundError!
```

### Functions Requiring ras_object Parameter

**Plan Operations** (ras_commander/RasPlan.py):
- `RasPlan.clone_plan(..., ras_object=ras)`
- `RasPlan.clone_geom(..., ras_object=ras)`
- `RasPlan.set_geom(..., ras_object=ras)`
- `RasPlan.get_plan_path(..., ras_object=ras)`
- `RasPlan.update_run_flags(..., ras_object=ras)`

**Execution** (ras_commander/RasCmdr.py):
- `RasCmdr.compute_plan(..., ras_object=ras)`
- `RasCmdr.compute_parallel(..., ras_object=ras)`
- `RasCmdr.compute_test_mode(..., ras_object=ras)`

**HDF Operations** (ras_commander/hdf/):
- `HdfMesh.get_mesh_cell_points(..., ras_object=ras)`
- `HdfResultsMesh.get_mesh_cells_timeseries(..., ras_object=ras)`
- `HdfResultsPlan.get_wse(..., ras_object=ras)`
- Most Hdf* class methods that accept plan/geometry numbers

### When ras_object Is Optional

If your code only uses the global `ras` object (single project):
```python
from ras_commander import init_ras_project, RasCmdr

# Initialize global ras object
init_ras_project("/path/to/project", "6.6")

# No ras_object needed - uses global
RasCmdr.compute_plan("01")  # Uses global ras object
```

If your code creates a local `ras` object:
```python
# MUST pass ras_object to every call
ras = init_ras_project("/path/to/project", "6.6")
RasCmdr.compute_plan("01", ras_object=ras)  # REQUIRED
```

### Testing for This Bug

**Symptom**: `FileNotFoundError` for HDF or plan files that should exist

**Diagnosis**:
1. Check if function creates local `ras` object
2. Search for calls to RasPlan, RasCmdr, Hdf* methods
3. Verify each call includes `ras_object=ras` parameter

**Example Error**:
```
FileNotFoundError: HDF file not found: 03
```

**Root Cause**: HDF lookup used global `ras` object's project folder instead of local `ras` object's folder.

## RasExamples.extract_project() Patterns

### The suffix Parameter Pattern

**Rule**: Use the `suffix` parameter and capture the return value when extracting projects. Do NOT use `output_path` with manual path construction.

### Correct Pattern

```python
from ras_commander import RasExamples, init_ras_project

# ✅ CORRECT: Use suffix parameter
project_folder = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="105")

# Initialize with returned path
init_ras_project(project_folder, "6.6")
```

**Result**: Extracts to `example_projects/BaldEagleCrkMulti2D_105/`

### Incorrect Patterns

**Anti-Pattern 1: output_path with manual path construction**
```python
from pathlib import Path

# ❌ WRONG: Extract to one location
RasExamples.extract_project(
    ["BaldEagleCrkMulti2D"],
    output_path="example_projects_105_analysis"
)

# ❌ WRONG: Initialize from different location (doesn't exist!)
project_folder = Path("example_projects") / "BaldEagleCrkMulti2D"
init_ras_project(project_folder, "6.6")  # FileNotFoundError!
```

**Anti-Pattern 2: Not capturing return value**
```python
# ❌ WRONG: Return value ignored
RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="105")

# ❌ WRONG: Manually construct path (may be wrong)
project_folder = Path("example_projects") / "BaldEagleCrkMulti2D_105"
init_ras_project(project_folder, "6.6")  # Fragile!
```

### Why suffix Is Better

**suffix parameter**:
- ✅ Returns correct path automatically
- ✅ Consistent location (`example_projects/{project}_{suffix}/`)
- ✅ Clear intent (project variant for specific purpose)
- ✅ No manual path construction errors

**output_path parameter**:
- ❌ Doesn't return path (easy to lose track)
- ❌ Arbitrary location (inconsistent)
- ❌ Requires manual path construction
- ❌ Path synchronization bugs common

### Multiple Projects Pattern

```python
# Extract multiple variants of same project
project_baseline = RasExamples.extract_project("Muncie", suffix="baseline")
project_modified = RasExamples.extract_project("Muncie", suffix="modified")
project_future = RasExamples.extract_project("Muncie", suffix="future")

# Each has unique folder:
# example_projects/Muncie_baseline/
# example_projects/Muncie_modified/
# example_projects/Muncie_future/
```

## Notebook-Specific Patterns

### Hidden Workflow Prerequisites

**Rule**: Document and validate hidden prerequisites for analysis functions.

**Example**: Sensitivity analysis functions that need mesh cell identification

```python
def sensitivity_analysis(project_folder, template_plan, point_of_interest, ...):
    """
    Run sensitivity analysis on HEC-RAS model.

    Args:
        project_folder: Path to HEC-RAS project
        template_plan: Plan number to use as template (e.g., "03")
            **IMPORTANT**: This plan must already be executed (HDF file
            must exist) so mesh cells can be identified.
        point_of_interest: Coordinates for result extraction
    """
    # Validate prerequisite
    ras = init_ras_project(project_folder, "6.6")
    hdf_path = ras.plan_df.loc[
        ras.plan_df['plan_number'] == template_plan, 'hdf_path'
    ].values[0]

    if not Path(hdf_path).exists():
        raise ValueError(
            f"Template plan {template_plan} has not been executed. "
            f"Run RasCmdr.compute_plan('{template_plan}') first."
        )

    # Now safe to read mesh cells
    mesh_cells = HdfMesh.get_mesh_cell_points(template_plan, ras_object=ras)
    # ... rest of function
```

**In Notebooks**: Add cell to execute prerequisite plans BEFORE calling analysis functions.

```python
# Cell N: Execute template plan (prerequisite)
init_ras_project(project_folder, "6.6")
RasCmdr.compute_plan(template_plan, num_cores=2)
print(f"Template plan {template_plan} complete - HDF file created")

# Cell N+1: Now safe to call analysis function
results = sensitivity_analysis(
    project_folder=project_folder,
    template_plan=template_plan,
    point_of_interest=poi
)
```

## See Also

- **Static Classes**: `.claude/rules/python/static-classes.md` - Why most classes don't need instantiation
- **Path Handling**: `.claude/rules/python/path-handling.md` - pathlib.Path patterns
- **Testing Approach**: `.claude/rules/testing/tdd-approach.md` - RasExamples usage in tests
- **Library Context**: `ras_commander/CLAUDE.md` - Multiple projects workflow

---

**Key Takeaway**: When creating local `ras` objects, ALWAYS pass them via `ras_object` parameter to downstream calls. Use `suffix` parameter with RasExamples.extract_project() and capture return value.
