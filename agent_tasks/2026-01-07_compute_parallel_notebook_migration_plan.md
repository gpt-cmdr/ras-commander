# compute_parallel Notebook Migration Plan

**Created**: 2026-01-07
**Related**: Backlog item arch-breaking-001
**Scope**: Update example notebooks for new `compute_parallel()` default behavior (no [Computed] folder)
**Total Effort**: 2.5-5 hours

---

## Change Summary

**Current Behavior** (will be deprecated):
- `compute_parallel()` creates `[Worker N]` folders → consolidates to `[Computed]` folder
- Users must re-initialize from `[Computed]` folder to access results
- plan_df is out of sync (points to original folder, results are in [Computed])

**New Default Behavior** (v1.0):
- `compute_parallel()` creates temporary `[Worker N]` folders → copies results BACK to original folder → cleans up workers
- No re-initialization needed - plan_df automatically has correct paths
- Opt-in parameter: `create_computed_folder=True` for legacy behavior

---

## Affected Notebooks

### Category A: Major Revision (4 notebooks, 2-4 hours)

These notebooks explicitly re-initialize from [Computed] folders and need significant updates:

#### 1. **721_Precipitation_Hyetograph_Comparison.ipynb** (COMPLEX)
- **Usage**: 3+ cells with [Computed] folder detection
- **Current pattern**:
  ```python
  # Cell ~10312: Debug HDF paths
  computed_path = original_path.parent / f"{original_path.name} [Computed]"

  # Cell ~10429: Re-initialize for analysis
  computed_folder = original_project_path.parent / f"{original_project_path.name} [Computed]"
  if computed_folder.exists():
      project_path = computed_folder

  # Cell ~11009: analyze_dominant_method function
  # Re-initialize from project_path to get correct HDF_Results_Path
  ras_local = init_ras_project(project_path, ras.ras_version)
  ```
- **Changes needed**:
  1. Remove [Computed] folder detection in all cells
  2. Remove re-initialization code (no longer needed)
  3. Update `analyze_dominant_method()` to NOT re-initialize (plan_df already correct)
  4. Keep project_path as original throughout
- **Effort**: 45-60 minutes

#### 2. **900_aorc_precipitation.ipynb** (MEDIUM)
- **Usage**: Single clear re-initialization point
- **Current pattern**:
  ```python
  # Step 6: Extract and Compare Results
  # This is critical after compute_parallel() which creates [Computed] folder
  computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
  if computed_folder.exists():
      ras = init_ras_project(computed_folder, RAS_VERSION)
      print(f"Re-initialized from: {computed_folder}")
  else:
      print(f"Warning: Computed folder not found")
  ```
- **Changes needed**:
  1. Remove [Computed] folder detection
  2. Remove init_ras_project() call (ras is already initialized correctly)
  3. Update comment: "plan_df is automatically updated after execution"
- **Best candidate to show `create_computed_folder=True` opt-in behavior**
- **Effort**: 20-30 minutes

#### 3. **901_aorc_precipitation_catalog.ipynb** (MEDIUM)
- **Usage**: Similar to 900, single re-initialization point
- **Current pattern**: Same as 900_aorc_precipitation.ipynb
- **Changes needed**: Same as 900
- **Effort**: 20-30 minutes

#### 4. **722_gridded_precipitation_atlas14.ipynb** (MEDIUM)
- **Usage**: 2 cells with [Computed] folder handling
- **Current pattern**:
  ```python
  # Cell ~3129: Section 7.1 variance visualization
  computed_folder = project_path.parent / f"{project_path.name} [Computed]"

  # Cell ~4159: Section 7.3 comparison visualization
  computed_folder = project_path.parent / f"{project_path.name} [Computed]"
  if computed_folder.exists():
      analysis_path = computed_folder
  else:
      analysis_path = project_path
  ```
- **Changes needed**:
  1. Remove [Computed] folder detection in both cells
  2. Use `project_path` directly (results are in original folder)
  3. Remove re-initialization from `analyze_dominant_method()` function
- **Effort**: 30-45 minutes

---

### Category B: Uses dest_folder Parameter (2 notebooks, 30-60 minutes)

These notebooks explicitly specify `dest_folder`, which is the CORRECT pattern when you want results in a different location:

#### 5. **420_breach_results_extraction.ipynb** (SIMPLE)
- **Usage**: Passes `dest_folder` to `compute_parallel()`
- **Current pattern**:
  ```python
  parallel_computed_folder = example_project_folder.parent / f"{example_project_folder.name}_parallelcomputed"
  RasCmdr.compute_parallel([...], dest_folder=Path(parallel_computed_folder), overwrite_dest=True)

  # Re-initialize in new folder where results are present
  init_ras_project(parallel_computed_folder)
  ```
- **Changes needed**:
  - **NO CHANGES REQUIRED** - This is the correct pattern for explicit destination
  - Optional: Add comment explaining when to use `dest_folder` vs default
- **Effort**: 5-10 minutes (documentation only)

#### 6. **113_parallel_execution.ipynb** (SIMPLE)
- **Usage**: Passes `dest_folder` to `compute_parallel()`
- **Current pattern**:
  ```python
  compute_folder = project_folder.parent / "parallel_compute_example"
  RasCmdr.compute_parallel([...], dest_folder=compute_folder, overwrite_dest=True, ras_object=source_project)

  # Initialize in dest_folder to access results
  compute_project = RasPrj()
  init_ras_project(compute_folder, RAS_VERSION, ras_object=compute_project)
  ```
- **Changes needed**:
  - **NO CHANGES REQUIRED** - This demonstrates the `dest_folder` use case
  - Optional: Add note that this is when you want results separate from original
- **Effort**: 5-10 minutes (documentation only)

---

### Category C: No Changes Needed (6 notebooks, 0 hours)

These notebooks mention `compute_parallel` but don't use the [Computed] folder pattern:

| File | Reason No Changes Needed |
|------|--------------------------|
| **110_single_plan_execution.ipynb** | Documentation reference only, no actual execution |
| **112_sequential_plan_execution.ipynb** | Uses `compute_test_mode()`, not `compute_parallel()` |
| **500_remote_execution_psexec.ipynb** | Just prints [Computed] folder path, doesn't access results |
| **710_mannings_sensitivity_bulk_analysis.ipynb** | Executes in-place, accesses results via plan_df already |
| **711_mannings_sensitivity_multi_interval.ipynb** | Executes in-place, accesses results via plan_df already |
| **103_plan_and_geometry_operations.ipynb** | Documentation reference only |

**Note**: 710 and 711 are **already following the new pattern** - they don't use [Computed] folders at all!

---

## Implementation Plan

### Phase 1: Update Core Notebooks (Category A)

#### 1.1 Notebook 721 (Most Complex)

**Current behavior**:
- Multiple cells detect [Computed] folder
- Re-initializes in 3 different places
- analyze_dominant_method() re-initializes internally

**Changes**:
1. **Remove [Computed] folder detection** from cells ~10312, 10429, 11009
2. **Update analyze_dominant_method() helper function** (Cell 30):
   ```python
   # OLD (remove):
   ras_local = init_ras_project(project_path, RAS_VERSION)

   # NEW (just use global ras or passed ras_object):
   _ras = ras_object if ras_object else ras

   # Access HDF paths from current plan_df (already correct)
   hdf_path_str = _ras.plan_df.loc[_ras.plan_df['plan_number'] == plan_num, 'HDF_Results_Path'].iloc[0]
   ```
3. **Remove project_path switching logic** - always use original project_path
4. **Test**: Verify dominant method analysis still works with in-place results

#### 1.2 Notebook 900 (Good Candidate for Opt-In Demo)

**Strategy**: Keep ONE copy of the old behavior to demonstrate opt-in

**Changes**:
1. **Add new cell** before execution showing two options:
   ```python
   # =============================================================================
   # OPTION 1: In-Place Execution (New Default - Recommended)
   # =============================================================================
   # Results written to original project folder - simple and clean
   USE_COMPUTED_FOLDER = False  # Default behavior

   # =============================================================================
   # OPTION 2: Isolated [Computed] Folder (Opt-In)
   # =============================================================================
   # Use this when you need to preserve the original project unchanged
   # Requires re-initialization to access results
   # USE_COMPUTED_FOLDER = True
   ```

2. **Update execution cell**:
   ```python
   if USE_COMPUTED_FOLDER:
       RasCmdr.compute_parallel([...], create_computed_folder=True)
       # Re-initialize from [Computed] folder
       computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
       init_ras_project(computed_folder, RAS_VERSION)
       print("Using isolated [Computed] folder")
   else:
       RasCmdr.compute_parallel([...])  # New default - in-place
       print("Using in-place execution - results in original folder")
   ```

3. **Test both branches**: Verify results accessible in both cases

#### 1.3 Notebooks 901, 722 (Similar to 900)

**Strategy**: Simplify to new default (remove [Computed] handling)

**Changes**: Same pattern as 900, but use Option 1 only (don't demonstrate opt-in)

---

### Phase 2: Document dest_folder Notebooks (Category B)

#### 2.1 Notebooks 113, 420

**Changes**: Add clarifying comment only

```python
# Using explicit dest_folder - results will be in this separate location
# This pattern is correct regardless of compute_parallel() default behavior
RasCmdr.compute_parallel([...], dest_folder=output_location, overwrite_dest=True)

# Must initialize from dest_folder to access results
init_ras_project(output_location, RAS_VERSION)
```

---

### Phase 3: Validation (Category C)

Verify Category C notebooks still run correctly with no changes.

---

## Testing Checklist

For each updated notebook:
- [ ] Executes without errors
- [ ] HDF files created in expected location
- [ ] Results accessible via `ras.plan_df['HDF_Results_Path']`
- [ ] No FileNotFoundError when accessing results
- [ ] Visualizations display correctly
- [ ] Output matches expected behavior

---

## Documentation Updates Needed

After notebook migration:

1. **`.claude/rules/hec-ras/execution.md`**:
   - Update compute_parallel() documentation
   - Add `create_computed_folder` parameter docs
   - Remove "[Computed] folder is created" from default behavior
   - Add "Results copied back to original folder" to default behavior

2. **`.claude/rules/python/dataframe-first-principle.md`**:
   - Simplify "When to Refresh DataFrames" section
   - Remove compute_parallel special case (will work like compute_plan)

3. **`CHANGELOG.md`**:
   - Add BREAKING CHANGE notice for v1.0
   - Document migration path for users

---

## Migration Guide for Users (CHANGELOG Entry)

```markdown
## v1.0.0 - BREAKING CHANGES

### compute_parallel() Default Behavior Changed

**Old Behavior**:
- Created `[Computed]` folder with consolidated results
- Required re-initialization to access results

**New Behavior**:
- Results copied back to original project folder (no [Computed] folder)
- plan_df automatically updated with correct paths
- No re-initialization needed

**Migration**:

If your code uses:
```python
RasCmdr.compute_parallel([...])
computed = project_folder.parent / f"{project_folder.name} [Computed]"
init_ras_project(computed, version)  # Re-initialize
```

**Option 1 - Simplify (recommended)**:
```python
RasCmdr.compute_parallel([...])
# Results are in original folder - plan_df already correct!
hdf_path = ras.plan_df['HDF_Results_Path'].iloc[0]
```

**Option 2 - Keep old behavior**:
```python
RasCmdr.compute_parallel([...], create_computed_folder=True)
computed = project_folder.parent / f"{project_folder.name} [Computed]"
init_ras_project(computed, version)
```
```

---

## Notebook-Specific Revision Details

### 721_Precipitation_Hyetograph_Comparison.ipynb

**Before** (Complex [Computed] handling):
```python
# Cell N: After execution
for aep_name, project_info in storm_projects.items():
    original_path = project_info['path']
    computed_folder = original_path.parent / f"{original_path.name} [Computed]"

    if computed_folder.exists():
        project_path = computed_folder
        init_ras_project(project_path, RAS_VERSION)
    else:
        project_path = original_path

    # Extract results from project_path...
```

**After** (Simplified):
```python
# Cell N: After execution
for aep_name, project_info in storm_projects.items():
    project_path = project_info['path']
    # Results are in original folder - no re-initialization needed!

    # Extract results from project_path...
```

**Additional change** - `analyze_dominant_method()` function:
```python
# REMOVE this line (no longer needed):
ras_local = init_ras_project(project_path, RAS_VERSION)

# CHANGE: Use passed ras_object or global ras
_ras = ras_object if ras_object else ras

# Access plan_df from current context:
hdf_path_str = _ras.plan_df.loc[_ras.plan_df['plan_number'] == plan_num, 'HDF_Results_Path'].iloc[0]
```

---

### 900_aorc_precipitation.ipynb (DEMONSTRATE OPT-IN)

**Add configuration cell** before execution:
```python
# =============================================================================
# Execution Mode Configuration
# =============================================================================
#
# OPTION 1 (Default): In-Place Execution
#   - Results written to original project folder
#   - Simplest workflow, no re-initialization needed
#   - plan_df automatically updated with correct paths
#
# OPTION 2 (Opt-In): Isolated [Computed] Folder
#   - Results written to separate [Computed] folder
#   - Preserves original project unchanged
#   - Requires re-initialization to access results
#   - Useful for archival workflows or when original must remain pristine

USE_COMPUTED_FOLDER = False  # Set True for Option 2
```

**Update execution cell**:
```python
if USE_COMPUTED_FOLDER:
    # Opt-in to [Computed] folder (legacy behavior)
    RasCmdr.compute_parallel(
        plan_number=plans_to_run,
        max_workers=MAX_WORKERS,
        num_cores=NUM_CORES,
        create_computed_folder=True  # Opt-in parameter
    )

    # Re-initialize from [Computed] folder to access results
    computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
    init_ras_project(computed_folder, RAS_VERSION)
    print(f"[OK] Results in isolated folder: {computed_folder}")

else:
    # New default: In-place execution
    RasCmdr.compute_parallel(
        plan_number=plans_to_run,
        max_workers=MAX_WORKERS,
        num_cores=NUM_CORES
        # No create_computed_folder parameter - defaults to False
    )

    # No re-initialization needed! Results are in original folder
    # plan_df automatically updated with correct HDF paths
    print(f"[OK] Results in original folder: {ras.project_folder}")
```

---

### 901_aorc_precipitation_catalog.ipynb

**Changes**: Same as 900, but use default behavior only (don't show opt-in)

Remove:
```python
computed_folder = ras.project_folder.parent / f"{ras.project_folder.name} [Computed]"
if computed_folder.exists():
    ras = init_ras_project(computed_folder, RAS_VERSION)
```

No replacement needed - results already in `ras.project_folder`.

---

### 722_gridded_precipitation_atlas14.ipynb

**Changes**: Remove [Computed] detection from 2 cells

**Cell ~3129** (Section 7.1):
```python
# REMOVE:
computed_folder = project_path.parent / f"{project_path.name} [Computed]"

# Use project_path directly
```

**Cell ~4159** (Section 7.3):
```python
# REMOVE:
computed_folder = project_path.parent / f"{project_path.name} [Computed]"
if computed_folder.exists():
    analysis_path = computed_folder
else:
    analysis_path = project_path

# REPLACE WITH:
analysis_path = project_path  # Results are in original folder
```

**Cell 30** (analyze_dominant_method function):
```python
# REMOVE re-initialization:
# ras_local = init_ras_project(project_path, RAS_VERSION)

# ACCESS plan_df from passed context:
_ras = ras_object if ras_object else ras
hdf_path_str = _ras.plan_df.loc[_ras.plan_df['plan_number'] == plan_num, 'HDF_Results_Path'].iloc[0]
```

---

## Category B & C: No Changes or Documentation Only

### 113_parallel_execution.ipynb & 420_breach_results_extraction.ipynb

**These are CORRECT** - they demonstrate the `dest_folder` use case.

Optional enhancement - add clarifying comment:
```python
# Using explicit dest_folder for demonstration purposes
# When dest_folder is specified, results go to that location (not original folder)
# Must initialize from dest_folder to access results
RasCmdr.compute_parallel([...], dest_folder=output_location)
init_ras_project(output_location)  # Access results here
```

### Other Category C Notebooks

No changes needed - verify they still run correctly.

---

## Implementation Checklist

### Pre-Implementation
- [ ] Read current CHANGELOG.md format
- [ ] Review arch-breaking-001 in BACKLOG.md for requirements
- [ ] Backup example notebooks (git commit before changes)

### Code Changes
- [ ] Update `RasCmdr.compute_parallel()` in `ras_commander/RasCmdr.py`
- [ ] Add `create_computed_folder` parameter (default False)
- [ ] Refactor to copy results back (like LocalWorker does)
- [ ] Update `compute_test_mode()` similarly

### Notebook Updates
- [ ] 721_Precipitation_Hyetograph_Comparison.ipynb (45-60 min)
- [ ] 900_aorc_precipitation.ipynb (30 min, add opt-in demo)
- [ ] 901_aorc_precipitation_catalog.ipynb (20-30 min)
- [ ] 722_gridded_precipitation_atlas14.ipynb (30-45 min)
- [ ] 113_parallel_execution.ipynb (5-10 min, docs only)
- [ ] 420_breach_results_extraction.ipynb (5-10 min, docs only)

### Documentation Updates
- [ ] `.claude/rules/hec-ras/execution.md`
- [ ] `.claude/rules/python/dataframe-first-principle.md`
- [ ] `CHANGELOG.md` (v1.0 breaking change notice)
- [ ] `ras_commander/CLAUDE.md` (if execution patterns documented there)

### Testing
- [ ] Run each updated notebook end-to-end
- [ ] Verify HDF files in original folder (not [Computed])
- [ ] Verify plan_df['HDF_Results_Path'] correct without re-initialization
- [ ] Test opt-in `create_computed_folder=True` in notebook 900
- [ ] Verify Category C notebooks still work

### Post-Implementation
- [ ] Git commit with detailed message explaining breaking change
- [ ] Update version to 1.0.0-alpha or 1.0.0-beta
- [ ] Tag release candidate for testing

---

## Risk Assessment

**Low Risk**:
- Remote execution unchanged (already correct)
- Category B notebooks unchanged (explicit dest_folder)
- Category C notebooks unchanged (no [Computed] usage)

**Medium Risk**:
- Category A notebooks need careful testing (5 notebooks)
- Users with custom scripts may break (mitigated by migration guide)

**Mitigation**:
- Clear CHANGELOG.md breaking change notice
- Opt-in parameter available for backward compatibility
- Phased rollout: alpha → beta → v1.0

---

## Success Criteria

After migration:
1. ✓ All 12 notebooks run successfully
2. ✓ Zero notebooks require re-initialization after compute_parallel() (unless using dest_folder or create_computed_folder=True)
3. ✓ One notebook (900) demonstrates the opt-in isolation behavior
4. ✓ DataFrame-First principle simplified (no special cases for compute_parallel)
5. ✓ All documentation updated
6. ✓ Migration guide in CHANGELOG

---

**Estimated Total Effort**: 2.5-5 hours
**Recommended Implementation Order**: 721 → 722 → 900 (with opt-in demo) → 901 → Category B (docs) → Category C (verify)
