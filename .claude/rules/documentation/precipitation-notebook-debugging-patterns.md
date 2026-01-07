# Precipitation Notebook Debugging Patterns

**Context**: Lessons learned from debugging 720-series precipitation notebooks
**Priority**: Medium - Helps with future notebook development
**Auto-loads**: When working with precipitation notebooks
**Created**: 2026-01-06 (Session closeout knowledge extraction)

---

## Overview

This document captures debugging patterns discovered while fixing notebooks 720, 721, and 722 during the precipitation API standardization project.

## Common Precipitation Notebook Bugs

### Bug 1: Return Type Inconsistencies

**Symptom**: TypeError when calling `.sum()`, `.max()`, or array operations on precipitation methods

**Cause**: Mixing methods that return different types (DataFrame vs ndarray)

**Before standardization**:
```python
hyeto_df = StormGenerator.generate_hyetograph(...)  # Returns DataFrame
hyeto_arr = Atlas14Storm.generate_hyetograph(...)   # Returned ndarray

# This works for DataFrame but not ndarray:
total = hyeto_df['cumulative_depth'].iloc[-1]

# This works for ndarray but not DataFrame:
total = hyeto_arr.sum()
```

**Solution**: Standardize all methods to return DataFrame (completed in v0.88.0)

**Current behavior** (post-standardization):
```python
# All methods return DataFrame with consistent columns
hyeto = StormGenerator.generate_hyetograph(...)
hyeto = Atlas14Storm.generate_hyetograph(...)
hyeto = FrequencyStorm.generate_hyetograph(...)
hyeto = ScsTypeStorm.generate_hyetograph(...)

# Consistent access pattern works for all:
total = hyeto['cumulative_depth'].iloc[-1]
peak = hyeto['incremental_depth'].max()
```

### Bug 2: Return Period Indexing

**Symptom**: Precipitation depths much lower than expected (e.g., 5 inches instead of 17 inches for 100-year storm)

**Cause**: Hardcoded array index assumes filtered data, but API returns all return periods

**Example** (notebook 722 bug):
```python
# User requests 100-year return period
pfe_data = Atlas14Grid.get_pfe_from_project(..., return_periods=[100])

# BUG: Assumes index 0 is the requested period
precip_grid = pfe_data['pfe_24hr'][:, :, 0]  # Gets 2-year data!

# Reality: API returns ALL 9 return periods [2, 5, 10, 25, 50, 100, 200, 500, 1000]
# Index 0 = 2-year
# Index 5 = 100-year
```

**Fix**: Always use dynamic indexing
```python
ari = pfe_data['ari']  # Array of return periods
target_rp = int(100 / aep_percent)  # Calculate target from AEP
ari_idx = np.argmin(np.abs(ari - target_rp))  # Find closest index
print(f"Using {ari[ari_idx]}-year (index {ari_idx})")
precip_grid = pfe_data['pfe_24hr'][:, :, ari_idx]  # Correct!
```

**Prevention**: Never hardcode array indices when working with return period data

### Bug 3: HDF Path Resolution After compute_parallel()

**Symptom**: "No HDF file found for Plan XX" after successful execution

**Cause**: `compute_parallel()` consolidates results to "[Computed]" folder, code looks in original folder

**Example** (notebook 721 bug):
```python
# Execution creates: project_folder [Computed]/
# But code looks in: project_folder/

# BUG: Wrong folder
hdf_files = list(project_path.glob(f"*.p{plan_number}.hdf"))  # Empty!

# Also BUG: Constructs path instead of using plan_df
```

**Fix**: Detect "[Computed]" folder and use plan_df
```python
# Detect where results actually are
original_path = storm_projects[aep_name]['path']
computed_path = original_path.parent / f"{original_path.name} [Computed]"

if computed_path.exists():
    project_path = computed_path
else:
    project_path = original_path

# Re-initialize to get fresh plan_df
init_ras_project(project_path, RAS_VERSION)

# Use plan_df as authoritative source
plan_row = ras.plan_df[ras.plan_df['plan_number'] == plan_number]
hdf_path = plan_row['HDF_Results_Path'].iloc[0]
hdf_file = Path(hdf_path)
```

**Prevention**: Always use plan_df for HDF paths, never construct them

### Bug 4: File Locking in Custom Parallel Execution

**Symptom**: Plans fail to execute with access denied or file locked errors

**Cause**: Custom ThreadPoolExecutor with multiple threads accessing same project files

**Example** (notebook 721 original code):
```python
# BUG: Multiple threads access same project folder
with ThreadPoolExecutor(max_workers=4) as executor:
    for plan in plans:
        executor.submit(execute_plan, project_path, plan)
```

**Fix**: Use library functions designed for parallel execution
```python
# CORRECT: Uses worker folders to isolate execution
RasCmdr.compute_parallel(
    plans_to_run=plan_numbers,
    max_workers=4,
    num_cores=2
)

# Or for multiple projects: Sequential by project, parallel within project
for aep_name, project_info in storm_projects.items():
    init_ras_project(project_info['path'], "6.6")
    RasCmdr.compute_parallel(plans_to_run=plan_numbers, max_workers=4)
```

**Prevention**: Use `RasCmdr.compute_parallel()` instead of custom threading

### Bug 5: Mesh Polygon Visualization

**Symptom**: Mesh results display as scatter points instead of colored polygons

**Cause**: Multiple issues in polygon extraction and merging:
- Bare `except:` silently hides errors
- Wrong HDF source for polygons
- Type mismatches in cell_id columns (int vs string)
- No merge validation

**Example** (notebook 722 bug):
```python
# BUG: Bare except hides why polygon extraction failed
try:
    cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
except:  # Silently fails, falls back to scatter
    cell_polygons = None
```

**Fix**: Proper error handling and data validation
```python
# Try plan HDF first (more reliable)
try:
    cell_polygons = HdfMesh.get_mesh_cell_polygons(plan_hdf)
    print(f"  [OK] Extracted {len(cell_polygons)} polygons from plan HDF")
except Exception as e:
    print(f"  [!] Plan HDF failed: {e}, trying geometry HDF...")
    try:
        cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
    except Exception as e2:
        print(f"  [!!] Polygon extraction failed: {e2}")
        cell_polygons = None

if cell_polygons is not None:
    # Ensure cell_id types match for merge
    cell_polygons['cell_id'] = cell_polygons['cell_id'].astype(int)
    max_ws_gdf['cell_id'] = max_ws_gdf['cell_id'].astype(int)

    # Merge and validate
    merged = cell_polygons.merge(max_ws_gdf, on=['mesh_name', 'cell_id'])

    if merged[wse_col].notna().sum() == 0:
        print("  [!!] Merge failed - no matching cells")
        cell_polygons = None  # Fall back to scatter
```

**Prevention**:
- Never use bare `except:`
- Try plan_hdf before geom_hdf for polygons
- Convert types before merging
- Validate merge succeeded

---

## Debugging Checklist for Precipitation Notebooks

### Pre-Execution Validation

Add cells that verify:
- [ ] All plan files exist
- [ ] All unsteady files exist
- [ ] Hyetographs match expected depths (compare to Atlas 14)
- [ ] Precipitation mode not "Disable"
- [ ] Visualize hyetographs before execution

**Example validation cell**:
```python
for aep, config in storm_configs.items():
    hyeto = storm_hyetographs[aep]
    expected = config['depth_inches']
    actual = hyeto['cumulative_depth'].iloc[-1]
    error = abs(actual - expected)

    if error > 1e-6:
        print(f"[!!] {aep}: Depth mismatch! Expected {expected}, got {actual}")
    else:
        print(f"[OK] {aep}: {actual:.6f} inches (exact)")
```

### Post-Execution Debugging

Add cells that verify:
- [ ] HDF files exist in expected locations
- [ ] Plan_df has correct HDF paths
- [ ] Results contain expected data (WSE, velocity, etc.)
- [ ] Return periods match configuration

**Example debug cell**:
```python
# After compute_parallel()
computed_folder = project_path.parent / f"{project_path.name} [Computed]"
if computed_folder.exists():
    print(f"[OK] Results consolidated to: {computed_folder}")
    init_ras_project(computed_folder, "6.6")
    print(f"     Plans with HDF: {len(ras.plan_df)}")
else:
    print(f"[!] No computed folder, using original")
```

### Spatial Analysis Validation

For maps involving grid data:
- [ ] Print return period array (`pfe_data['ari']`)
- [ ] Print which index is being used
- [ ] Verify precipitation values in expected range
- [ ] Check CRS compatibility across datasets

**Example**:
```python
ari = pfe_data['ari']
target_rp = 100  # 100-year return period
ari_idx = np.argmin(np.abs(ari - target_rp))

print(f"Return periods available: {ari}")
print(f"Target: {target_rp}-year")
print(f"Using: {ari[ari_idx]}-year (index {ari_idx})")
print(f"Precip range: {np.nanmin(precip_grid):.2f} - {np.nanmax(precip_grid):.2f} inches")

# Sanity check for 100-year 24-hr (CONUS typical range)
if np.nanmin(precip_grid) < 8 or np.nanmax(precip_grid) > 30:
    print("[!] WARNING: Values outside typical 100-yr 24-hr range (8-30 inches for CONUS)")
```

---

## API Migration Patterns

### StormGenerator Instance → Static (v0.88.0)

**OLD (deprecated, warns in v0.88.0, removed in v0.89.0)**:
```python
gen = StormGenerator.download_from_coordinates(29.76, -95.37)
hyeto = gen.generate_hyetograph(total_depth_inches=17.0, duration_hours=24)
```

**NEW**:
```python
ddf = StormGenerator.download_from_coordinates(29.76, -95.37)
hyeto = StormGenerator.generate_hyetograph(
    ddf_data=ddf,
    total_depth_inches=17.0,
    duration_hours=24
)
```

**Migration**: Mechanical replacement (search and replace pattern)

### HMS Methods: ndarray → DataFrame (hms-commander v0.2.0)

**OLD (hms-commander v0.1.x)**:
```python
hyeto = Atlas14Storm.generate_hyetograph(total_depth_inches=17.0, ...)
total = hyeto.sum()  # ndarray
peak = hyeto.max()
```

**NEW (hms-commander v0.2.0)**:
```python
hyeto = Atlas14Storm.generate_hyetograph(total_depth_inches=17.0, ...)
total = hyeto['incremental_depth'].sum()  # DataFrame
peak = hyeto['incremental_depth'].max()

# Or use cumulative for total:
total = hyeto['cumulative_depth'].iloc[-1]
```

**Migration**: Replace array operations with DataFrame column access

---

## Reference Examples

### Working Patterns

**Notebook 720**: `examples/720_precipitation_methods_comprehensive.ipynb`
- Complete method comparison
- All 4 methods demonstrated
- DataFrame API usage throughout

**Notebook 721**: `examples/721_Precipitation_Hyetograph_Comparison.ipynb`
- Multi-method multi-AEP workflow
- Parallel execution pattern
- Pre-execution validation cells

**Notebook 722**: `examples/722_gridded_precipitation_atlas14.ipynb`
- Gridded precipitation workflow
- Spatial variance analysis
- Mesh polygon visualization

### Deprecated Patterns (Do Not Use)

**Custom parallel execution**:
```python
# DON'T: Custom ThreadPoolExecutor causes file locking
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(execute_plan, path, plan) for plan in plans]
```

**Hardcoded return period indices**:
```python
# DON'T: Assumes index structure
precip_grid = pfe_data['pfe_24hr'][:, :, 0]  # What return period is index 0?
```

**Glob patterns for HDF files**:
```python
# DON'T: Construct paths
hdf_files = list(project_path.glob(f"*.p{plan_number}.hdf"))

# DO: Use plan_df
hdf_path = ras.plan_df[ras.plan_df['plan_number'] == plan_number]['HDF_Results_Path'].iloc[0]
```

---

## See Also

- **API Audit**: `.claude/outputs/api-consistency-auditor/2026-01-05-precipitation-api-audit.md`
- **Session Closeout**: `.claude/outputs/2026-01-05_precipitation_api_standardization_session_closeout.md`
- **Precipitation Rules**: `.claude/rules/hec-ras/precipitation.md`
- **Precipitation CLAUDE**: `ras_commander/precip/CLAUDE.md`
- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`

---

**Key Takeaway**: Use library functions (RasCmdr.compute_parallel), use plan_df for paths, use dynamic indexing for return periods, validate DataFrame structure before operations.
