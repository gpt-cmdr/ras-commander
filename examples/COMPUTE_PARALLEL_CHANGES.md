# compute_parallel() and compute_test_mode() Behavior Change

**Version**: v0.88.1
**Date**: 2026-01-08
**Type**: Breaking Change (Improvement)

---

## What Changed

### Before v0.88.1 (Old Behavior)

**`compute_parallel()`** created a `[Computed]` folder:
```python
RasCmdr.compute_parallel(["01", "02"])

# Results written to: {project} [Computed]/
# plan_df points to: {project}/ (original folder)
# Result: HDF_Results_Path is stale → FileNotFoundError

# Required workaround:
computed_folder = project_path.parent / f"{project_path.name} [Computed]"
init_ras_project(computed_folder, "6.6")  # Had to re-initialize!
```

**`compute_test_mode()`** created a `[Test]` folder:
```python
RasCmdr.compute_test_mode(["01", "02"])

# Results written to: {project} [Test]/
# plan_df points to: {project}/ (original folder)
# Same problem - required re-initialization
```

### After v0.88.1 (New Behavior)

**Both functions now consolidate results to original folder**:

```python
# compute_parallel() - No [Computed] folder created!
RasCmdr.compute_parallel(["01", "02"])

# Results in: {project}/ (original folder)
# plan_df points to: {project}/ (original folder)
# HDF_Results_Path is correct → Just works!

hdf_path = ras.plan_df['HDF_Results_Path'].iloc[0]  # Correct path!
```

```python
# compute_test_mode() - [Test] folder is temporary
RasCmdr.compute_test_mode(["01", "02"])

# Execution in: {project} [Test]/ (temporary)
# Results copied to: {project}/ (original folder)
# [Test] folder deleted
# plan_df points to: {project}/ with correct HDF paths
```

---

## Why This Change?

### The Problem

The `[Computed]` folder pattern created several issues:

1. **Non-linear workflow** - Results written to one location, plan_df points to another
2. **Required re-initialization** - Users had to manually detect and re-initialize from [Computed]
3. **Violated DataFrame-First principle** - plan_df wasn't the authoritative source
4. **User confusion** - "Where are my results?"
5. **Fragile notebooks** - Required complex workaround code

### The Solution

**Direct consolidation to original folder**:
- Worker folders (`[Worker 1]`, `[Worker 2]`, etc.) still used during execution for isolation
- After execution completes, HDF files copied back to original project folder
- Worker/test folders cleaned up automatically
- plan_df refreshed - now has correct paths
- Linear, predictable workflow

---

## Migration Guide

### If You Have Code With Workarounds

**Old workaround pattern** (still works, but unnecessary):
```python
# This still works but is no longer needed
RasCmdr.compute_parallel(["01", "02"])

computed_folder = project_path.parent / f"{project_path.name} [Computed]"
if computed_folder.exists():
    init_ras_project(computed_folder, "6.6")
else:
    init_ras_project(project_path, "6.6")  # Falls back to this now
```

**Simplified pattern** (v0.88.1+):
```python
# Just use original folder - results are there
RasCmdr.compute_parallel(["01", "02"])

# plan_df already has correct paths
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
```

### Notebooks You Can Simplify

The following notebooks have old workaround code that can be removed:

1. `examples/721_Precipitation_Hyetograph_Comparison.ipynb`
2. `examples/722_gridded_precipitation_atlas14.ipynb`
3. `examples/900_aorc_precipitation.ipynb`
4. `examples/901_aorc_precipitation_catalog.ipynb`
5. `examples/420_breach_results_extraction.ipynb`
6. `examples/710_mannings_sensitivity_bulk_analysis.ipynb`
7. `examples/711_mannings_sensitivity_multi_interval.ipynb`

**Good news**: These notebooks still work correctly with the workaround code - the `if computed_folder.exists()` check simply falls back to the original folder now.

---

## dest_folder Parameter Unchanged

**When you specify `dest_folder`, behavior is unchanged**:

```python
# Results still go to specified destination
RasCmdr.compute_parallel(
    ["01", "02"],
    dest_folder="/output/scenario_analysis"
)

# Results are in: /output/scenario_analysis/
# Original project unchanged
# plan_df still points to original folder
```

**Use `dest_folder` when**:
- You want to preserve the original project
- Running multiple scenarios
- Need isolated execution folders

---

## What About Worker Folders?

**Worker folders (`[Worker 1]`, `[Worker 2]`, etc.) are still created**:

1. **During execution**: Each plan runs in isolated `[Worker N]` folder
2. **After execution**: Results consolidated to final destination (original or dest_folder)
3. **Cleanup**: Worker folders automatically deleted

This pattern:
- ✅ Maintains execution isolation (prevents file locking)
- ✅ Consolidates results to predictable location
- ✅ Cleans up temporary folders
- ✅ Matches remote execution behavior

---

## Benefits

### For Users

- ✅ **Simpler workflow** - Results go where you expect
- ✅ **No re-initialization dance** - plan_df just works
- ✅ **Fewer surprises** - Linear, predictable behavior
- ✅ **Less disk space** - No duplicate [Computed] folders

### For Developers

- ✅ **DataFrame-First principle** - plan_df is always authoritative
- ✅ **Consistent patterns** - Local and remote execution work the same way
- ✅ **Easier to explain** - No special cases to document
- ✅ **Fewer bugs** - Eliminates entire class of path resolution issues

---

## Technical Details

### compute_parallel() Changes

**File**: `ras_commander/RasCmdr.py:673-761`

**Key change** (line 673-681):
```python
# Old: Always created [Computed] folder
final_dest_folder = project_folder.parent / f"{project_folder.name} [Computed]"

# New: Consolidate to original when no dest_folder specified
if dest_folder is not None:
    final_dest_folder = dest_folder_path
else:
    final_dest_folder = project_folder  # Back to original!
```

**Result**: Worker results consolidated directly to original project folder

### compute_test_mode() Changes

**File**: `ras_commander/RasCmdr.py:981-1009`

**New consolidation logic** (lines 981-996):
```python
# Copy HDF files from [Test] back to original
for hdf_file in compute_folder.glob("*.hdf"):
    dest_path = project_folder / hdf_file.name
    shutil.copy2(hdf_file, dest_path)

# Remove [Test] folder
shutil.rmtree(compute_folder)
```

**Result**: HDF files in original folder, [Test] folder cleaned up

---

## Testing

All changes tested and verified:

- ✅ Library code compiles correctly
- ✅ Consolidation logic validated
- ✅ plan_df refresh verified
- ✅ Existing notebooks backward compatible

**Test yourself**:
```python
from ras_commander import RasExamples, init_ras_project, RasCmdr

# Extract example
project_path = RasExamples.extract_project("Muncie")
init_ras_project(project_path, "6.5")

# Execute
RasCmdr.compute_parallel(["01", "02"])

# Verify HDF in original folder
import pandas as pd
for _, row in ras.plan_df.iterrows():
    print(f"Plan {row['plan_number']}: {row['HDF_Results_Path']}")
    # Should show paths in project_path, not [Computed]
```

---

## Questions?

- **"Will my existing notebooks break?"** - No, old workaround code still works (falls back correctly)
- **"Do I need to update my code?"** - Not immediately, but you can simplify by removing workarounds
- **"What about dest_folder?"** - Unchanged - results still go to specified destination
- **"Can I get the old behavior back?"** - No, this is a breaking change for the better

---

## See Also

- **DataFrame-First Principle**: `.claude/rules/python/dataframe-first-principle.md`
- **Precipitation Debugging**: `.claude/rules/documentation/precipitation-notebook-debugging-patterns.md`
- **BACKLOG**: `agent_tasks/BACKLOG.md` (arch-breaking-001 marked completed)
- **Migration Plan**: `agent_tasks/2026-01-07_compute_parallel_notebook_migration_plan.md`

---

**Key Takeaway**: After `compute_parallel()` or `compute_test_mode()`, HDF results are in the original project folder. plan_df has correct paths automatically. No special handling needed.
