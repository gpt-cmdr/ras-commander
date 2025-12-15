# Notebook 04 Cell Ordering Fix - Detailed Analysis

**Notebook**: `04_multiple_project_operations.ipynb`
**Issue**: `NameError: name 'examples_dir' is not defined` in Cell 2
**Date**: 2025-12-15
**Analyzed by**: notebook-runner subagent

---

## Executive Summary

Cell 2 attempts to use `examples_dir` variable before it is defined in Cell 5. The variable is created as `examples_dir = extracted_paths[0].parent` after project extraction, but Cell 2 needs it to define output folder paths.

**Root Cause**: Variable definition out of order - Cell 2 uses `examples_dir` before Cell 5 defines it.

**Fix Strategy**: Move variable definitions from Cell 5 up to Cell 2, OR reorder cells to define paths after extraction.

---

## Current Cell Structure

### Cell 0: Title (Markdown)
```markdown
# Multiple Project Operations
```

### Cell 1: Imports and Setup (Code)
- Development mode toggle
- All imports
- System verification
- **No issues here**

### Cell 2: Define Computation Paths + System Resources (Code)
**PROBLEM CELL - Uses undefined variable**

```python
# Define computation output paths
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"  # ❌ examples_dir not defined yet
muncie_compute_folder = examples_dir / "compute_muncie"           # ❌ examples_dir not defined yet

# Check system resources
cpu_count = psutil.cpu_count(logical=True)
# ... rest of system resource checking code
```

**Problem**: `examples_dir` is not defined at this point in execution.

### Cell 3: Markdown
Understanding Multiple RAS Project Management explanation

### Cell 4: Markdown
Downloading and Extracting Example HEC-RAS Projects explanation

### Cell 5: Extract Projects (Code)
**DEFINES THE VARIABLE NEEDED BY CELL 2**

```python
# Extract the example projects
ras_examples = RasExamples()
extracted_paths = ras_examples.extract_project(
    ["Balde Eagle Creek", "Muncie"],
    output_path="example_projects_04_multiple_project_operations"
)

# Update examples_dir to match
examples_dir = extracted_paths[0].parent  # ✅ DEFINED HERE - but too late!

# Verify the paths exist
print(f"Bald Eagle Creek project exists: {bald_eagle_path.exists()}")  # Also uses undefined bald_eagle_path
print(f"Muncie project exists: {muncie_path.exists()}")                # Also uses undefined muncie_path
```

**Additional Problem**: Cell 5 also references `bald_eagle_path` and `muncie_path` which are never defined anywhere in the notebook!

---

## Dependency Analysis

### Variables and Their Dependencies

**Cell 2 NEEDS**:
- `examples_dir` (used to define `bald_eagle_compute_folder` and `muncie_compute_folder`)

**Cell 5 PROVIDES**:
- `examples_dir = extracted_paths[0].parent`

**Cell 5 NEEDS (but missing)**:
- `bald_eagle_path` - Never defined!
- `muncie_path` - Never defined!

**Cell 6 NEEDS**:
- `bald_eagle_path` (for `init_ras_project()`)
- `muncie_path` (for `init_ras_project()`)

### Execution Order Problems

**Current Order**:
1. Cell 1: Imports ✓
2. Cell 2: Uses `examples_dir` ❌ (not defined yet)
3. Cell 3-4: Markdown ✓
4. Cell 5: Defines `examples_dir`, references undefined `bald_eagle_path`/`muncie_path` ❌
5. Cell 6: Uses undefined `bald_eagle_path`/`muncie_path` ❌

**Required Order**:
1. Cell 1: Imports ✓
2. Extract projects and define ALL paths
3. Define computation output folders
4. Initialize projects
5. Rest of workflow

---

## Root Cause Explanation

The notebook has **two separate issues**:

### Issue 1: Forward Reference to `examples_dir`
Cell 2 creates a **forward reference** - it uses a variable before it exists. This is the immediate cause of the `NameError`.

The developer likely intended to:
1. Define where output folders should go (Cell 2)
2. Extract projects to discover the parent directory (Cell 5)
3. Use the parent directory path later

But Python executes cells sequentially, so Cell 2 fails when `examples_dir` doesn't exist yet.

### Issue 2: Missing Path Definitions
Cell 5 and Cell 6 reference `bald_eagle_path` and `muncie_path`, but these variables are **never defined anywhere**. This will cause additional `NameError` exceptions after fixing Issue 1.

Looking at Cell 5's logic:
```python
extracted_paths = ras_examples.extract_project([...])  # Returns list of Path objects
examples_dir = extracted_paths[0].parent
```

It appears `bald_eagle_path` and `muncie_path` should be:
```python
bald_eagle_path = extracted_paths[0]  # First extracted project
muncie_path = extracted_paths[1]      # Second extracted project
```

---

## Proposed Fix

### Option A: Move Path Definitions Earlier (Recommended)

**Strategy**: Define paths immediately after extraction in Cell 5, move system resource check to separate cell.

**Modified Cell 2** (System Resources Only):
```python
# Check system resources
cpu_count = psutil.cpu_count(logical=True)
physical_cpu_count = psutil.cpu_count(logical=False)
available_memory_gb = psutil.virtual_memory().available / (1024**3)

print(f"System Resources:")
print(f"- {physical_cpu_count} physical CPU cores ({cpu_count} logical cores)")
print(f"- {available_memory_gb:.1f} GB available memory")
print(f"For multiple HEC-RAS projects, a good rule of thumb is:")
print(f"- Assign 2-4 cores per project")
print(f"- Allocate at least 2-4 GB of RAM per project")
print(f"Based on your system, you could reasonably run {min(physical_cpu_count//2, int(available_memory_gb//3))} projects simultaneously.")
```

**Modified Cell 5** (Extract Projects + Define ALL Paths):
```python
# Extract the example projects
ras_examples = RasExamples()
extracted_paths = ras_examples.extract_project(
    ["Balde Eagle Creek", "Muncie"],
    output_path="example_projects_04_multiple_project_operations"
)
print(f"Extracted projects to:")
for path in extracted_paths:
    print(f"- {path}")

# Define project paths
bald_eagle_path = extracted_paths[0]  # First project
muncie_path = extracted_paths[1]      # Second project
examples_dir = extracted_paths[0].parent

# Define computation output folders
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"
muncie_compute_folder = examples_dir / "compute_muncie"

# Verify the paths exist
print(f"\nBald Eagle Creek project exists: {bald_eagle_path.exists()}")
print(f"Muncie project exists: {muncie_path.exists()}")
```

### Option B: Reorder Cells Completely

**New Order**:
1. Cell 0: Title (Markdown) - no change
2. Cell 1: Imports and Setup (Code) - no change
3. Cell 3: Markdown explanation - no change
4. Cell 4: Markdown explanation - no change
5. **Cell 5: Extract Projects + Define Paths** (modified as in Option A)
6. **Cell 2: System Resources Check** (modified as in Option A)
7. Cell 6+: Rest of notebook - no change

This maintains the narrative flow (explanation → action → resource check).

---

## Recommended Implementation: Option A

**Reason**: Minimal disruption to notebook narrative, fixes both issues with small changes.

### Step-by-Step Instructions

#### Step 1: Modify Cell 2
Remove the path definitions that use `examples_dir`, keep only system resource check.

**Before**:
```python
# Define computation output paths
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"
muncie_compute_folder = examples_dir / "compute_muncie"

# Check system resources
cpu_count = psutil.cpu_count(logical=True)
# ... rest of code
```

**After**:
```python
# Check system resources
cpu_count = psutil.cpu_count(logical=True)
physical_cpu_count = psutil.cpu_count(logical=False)
available_memory_gb = psutil.virtual_memory().available / (1024**3)

print(f"System Resources:")
print(f"- {physical_cpu_count} physical CPU cores ({cpu_count} logical cores)")
print(f"- {available_memory_gb:.1f} GB available memory")
print(f"For multiple HEC-RAS projects, a good rule of thumb is:")
print(f"- Assign 2-4 cores per project")
print(f"- Allocate at least 2-4 GB of RAM per project")
print(f"Based on your system, you could reasonably run {min(physical_cpu_count//2, int(available_memory_gb//3))} projects simultaneously.")
```

#### Step 2: Modify Cell 5
Add path definitions immediately after extraction.

**Before**:
```python
# Extract the example projects (use same output path as cell 4)
# RasExamples handles extraction - no need to manually delete the directory
ras_examples = RasExamples()
extracted_paths = ras_examples.extract_project(
    ["Balde Eagle Creek", "Muncie"],
    output_path="example_projects_04_multiple_project_operations"
)
print(f"Extracted projects to:")
for path in extracted_paths:
    print(f"- {path}")

# Update examples_dir to match
examples_dir = extracted_paths[0].parent

# Verify the paths exist
print(f"Bald Eagle Creek project exists: {bald_eagle_path.exists()}")
print(f"Muncie project exists: {muncie_path.exists()}")
```

**After**:
```python
# Extract the example projects
ras_examples = RasExamples()
extracted_paths = ras_examples.extract_project(
    ["Balde Eagle Creek", "Muncie"],
    output_path="example_projects_04_multiple_project_operations"
)
print(f"Extracted projects to:")
for path in extracted_paths:
    print(f"- {path}")

# Define project paths
bald_eagle_path = extracted_paths[0]  # First project (Balde Eagle Creek)
muncie_path = extracted_paths[1]      # Second project (Muncie)
examples_dir = extracted_paths[0].parent

# Define computation output folders
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"
muncie_compute_folder = examples_dir / "compute_muncie"

# Verify the paths exist
print(f"\nBald Eagle Creek project exists: {bald_eagle_path.exists()}")
print(f"Muncie project exists: {muncie_path.exists()}")
print(f"Computation folders will be created at:")
print(f"- {bald_eagle_compute_folder}")
print(f"- {muncie_compute_folder}")
```

#### Step 3: Verify No Other References
Search the rest of the notebook for any other uses of:
- `examples_dir` ✓ (now defined in Cell 5)
- `bald_eagle_path` ✓ (now defined in Cell 5)
- `muncie_path` ✓ (now defined in Cell 5)
- `bald_eagle_compute_folder` ✓ (now defined in Cell 5)
- `muncie_compute_folder` ✓ (now defined in Cell 5)

All downstream cells should work correctly after this fix.

---

## Verification Checklist

After implementing the fix:

### Dependency Verification
- [ ] Cell 2 no longer references `examples_dir`
- [ ] Cell 5 defines `bald_eagle_path` before use
- [ ] Cell 5 defines `muncie_path` before use
- [ ] Cell 5 defines `examples_dir` before use
- [ ] Cell 5 defines `bald_eagle_compute_folder` and `muncie_compute_folder`
- [ ] All path variables defined before first use

### Execution Verification
- [ ] Restart kernel and run Cell 1 (imports) - should succeed
- [ ] Run Cell 2 (system resources) - should succeed
- [ ] Run Cell 5 (extract + define paths) - should succeed
- [ ] Verify all path variables exist: `bald_eagle_path`, `muncie_path`, `examples_dir`, `bald_eagle_compute_folder`, `muncie_compute_folder`
- [ ] Run Cell 6 (initialize projects) - should succeed
- [ ] Run rest of notebook - should succeed

### Narrative Verification
- [ ] Markdown cells still make sense in context
- [ ] Explanatory text matches code behavior
- [ ] User understands why system resources are checked first
- [ ] User understands project extraction and path setup

---

## Potential Side Effects

### None Expected
The fix:
- ✅ Only moves variable definitions to where they're first needed
- ✅ Doesn't change any logic or computation
- ✅ Doesn't alter notebook narrative flow significantly
- ✅ Makes dependencies explicit and correct
- ✅ Defines all missing variables

### Minor Changes
- System resource check now happens BEFORE project extraction (was after)
  - **Impact**: User sees their system capabilities before downloading ~50MB of example projects
  - **Benefit**: Better UX - user knows if their system can handle the operations

---

## Alternative Fixes Considered

### Alternative 1: Define Placeholder Path
```python
# Cell 2
from pathlib import Path
examples_dir = Path.cwd() / "example_projects_04_multiple_project_operations"
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"
muncie_compute_folder = examples_dir / "compute_muncie"
```

**Rejected**: Creates unnecessary coupling between Cell 2 and Cell 5's output path. If Cell 5 changes output location, Cell 2 breaks silently.

### Alternative 2: Defer Path Usage
Move ALL code using paths into Cell 6+.

**Rejected**: Breaks logical grouping - path definitions should be near extraction.

### Alternative 3: Use Hardcoded Paths
```python
bald_eagle_path = Path("example_projects_04_multiple_project_operations/Balde Eagle Creek")
```

**Rejected**: Fragile, breaks if extraction path changes, not dynamic.

---

## Summary

**Issue**: Cell ordering bug causing `NameError` for `examples_dir`, plus missing definitions for `bald_eagle_path` and `muncie_path`.

**Root Cause**: Variable used before definition (forward reference).

**Fix**: Move all path definitions to Cell 5 immediately after extraction.

**Impact**: Minimal - improves code correctness, slightly reorders when system resources are displayed.

**Risk**: None - fix is straightforward variable definition reordering.

**Verification**: Run cells 1→2→5→6 in order, verify all paths defined and used correctly.

---

## Implementation Script

For automated fix, the following changes are needed:

**File**: `examples/04_multiple_project_operations.ipynb`

**Cell 2 - Replace entire cell content**:
```python
# Check system resources
cpu_count = psutil.cpu_count(logical=True)
physical_cpu_count = psutil.cpu_count(logical=False)
available_memory_gb = psutil.virtual_memory().available / (1024**3)

print(f"System Resources:")
print(f"- {physical_cpu_count} physical CPU cores ({cpu_count} logical cores)")
print(f"- {available_memory_gb:.1f} GB available memory")
print(f"For multiple HEC-RAS projects, a good rule of thumb is:")
print(f"- Assign 2-4 cores per project")
print(f"- Allocate at least 2-4 GB of RAM per project")
print(f"Based on your system, you could reasonably run {min(physical_cpu_count//2, int(available_memory_gb//3))} projects simultaneously.")
```

**Cell 5 - Replace entire cell content**:
```python
# Extract the example projects
ras_examples = RasExamples()
extracted_paths = ras_examples.extract_project(
    ["Balde Eagle Creek", "Muncie"],
    output_path="example_projects_04_multiple_project_operations"
)
print(f"Extracted projects to:")
for path in extracted_paths:
    print(f"- {path}")

# Define project paths
bald_eagle_path = extracted_paths[0]  # First project (Balde Eagle Creek)
muncie_path = extracted_paths[1]      # Second project (Muncie)
examples_dir = extracted_paths[0].parent

# Define computation output folders
bald_eagle_compute_folder = examples_dir / "compute_bald_eagle"
muncie_compute_folder = examples_dir / "compute_muncie"

# Verify the paths exist
print(f"\nBald Eagle Creek project exists: {bald_eagle_path.exists()}")
print(f"Muncie project exists: {muncie_path.exists()}")
print(f"Computation folders will be created at:")
print(f"- {bald_eagle_compute_folder}")
print(f"- {muncie_compute_folder}")
```

---

**End of Analysis**
