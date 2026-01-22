# DataFrame-First Principle

**Context**: Core architectural pattern for ras-commander data access
**Priority**: Critical - affects all file path resolution and metadata queries
**Auto-loads**: Yes (all code)
**Discovered**: 2026-01-07 (Precipitation notebook debugging session)

---

## Core Principle

**ras-commander DataFrames are the SINGLE SOURCE OF TRUTH for project metadata.**

All file paths, execution status, and project configuration should be queried from:
- `ras.plan_df` - Plan files, HDF paths, titles, execution status
- `ras.geom_df` - Geometry files, mesh info, structure counts
- `ras.flow_df` - Flow files, boundary conditions
- `ras.unsteady_df` - Unsteady files, precipitation mode, IC/BC settings
- `ras.boundaries_df` - Boundary condition locations and types

---

## The Golden Rules

### ✅ DO

1. **Use plan_df['HDF_Results_Path'] for HDF file paths**
   ```python
   # ✅ CORRECT - authoritative source
   hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
   hdf_file = Path(hdf_path)
   ```

2. **DataFrames are automatically refreshed after execution**
   ```python
   # After execution, plan_df automatically has correct HDF paths
   RasCmdr.compute_parallel(["01", "02"])

   # plan_df is automatically refreshed - HDF results are in original folder
   hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
   ```

3. **Query DataFrames for file existence**
   ```python
   # ✅ CORRECT - DataFrame tells us if HDF exists
   plan_row = ras.plan_df[ras.plan_df['plan_number'] == '01']
   hdf_path = plan_row['HDF_Results_Path'].iloc[0]

   if hdf_path is None or pd.isna(hdf_path):
       print("Plan not executed yet")
   else:
       print(f"Results: {hdf_path}")
   ```

4. **Trust DataFrame as authoritative**
   ```python
   # ✅ CORRECT - DataFrame knows the truth
   if ras.plan_df['HDF_Results_Path'].notna().sum() > 0:
       print("Some plans have been executed")
   ```

### ❌ DON'T

1. **Don't use glob patterns to find files**
   ```python
   # ❌ WRONG - fragile, doesn't handle dest_folder parameter
   hdf_files = list(project_path.glob(f"*.p{plan_num}.hdf"))
   hdf_path = hdf_files[0] if hdf_files else None
   ```

2. **Don't construct paths manually**
   ```python
   # ❌ WRONG - assumes location, breaks with dest_folder
   hdf_path = project_path / f"{project_name}.p01.hdf"
   ```

3. **Don't cache file paths outside DataFrames**
   ```python
   # ❌ WRONG - goes stale after execution
   hdf_paths = {p: f"{project_name}.p{p}.hdf" for p in ["01", "02"]}
   ```

4. **Use plan_df after execution (no special refresh needed)**
   ```python
   # ✅ CORRECT - plan_df is automatically refreshed after compute_parallel
   RasCmdr.compute_parallel(["01", "02"])
   hdf_path = ras.plan_df['HDF_Results_Path'].iloc[0]  # Correct!
   ```

---

## When to Refresh DataFrames

### After compute_plan(), compute_parallel(), or compute_test_mode()

**No special refresh needed** - DataFrames are automatically refreshed and HDF results
are consolidated to the original project folder.

```python
# All compute functions work the same way now
RasCmdr.compute_plan("01")
# OR
RasCmdr.compute_parallel(["01", "02"])
# OR
RasCmdr.compute_test_mode(["01", "02"])

# plan_df is automatically refreshed - HDF files are in original folder
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
```

### After compute_plan() with dest_folder
```python
# When using dest_folder, results go to that folder (original unchanged)
RasCmdr.compute_plan("01", dest_folder="/output/run1")

# Either: Initialize from dest_folder to access results
init_ras_project("/output/run1", ras_version)
hdf_path = ras.plan_df['HDF_Results_Path'].iloc[0]

# Or: Construct path manually (you know the location)
hdf_path = Path("/output/run1") / f"{project_name}.p01.hdf"
```

---

## Common Access Patterns

### Get HDF File Path
```python
# Single plan
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]

# Multiple plans
for plan_num in ['01', '02', '03']:
    plan_row = ras.plan_df[ras.plan_df['plan_number'] == plan_num]
    hdf_path = plan_row['HDF_Results_Path'].iloc[0]
    if hdf_path and Path(hdf_path).exists():
        print(f"Plan {plan_num}: {hdf_path}")
```

### Get Geometry File Path
```python
# From geometry number
geom_path = ras.geom_df.loc[ras.geom_df['geom_number'] == '01', 'file_path'].iloc[0]

# From plan (find which geometry it uses)
plan_row = ras.plan_df[ras.plan_df['plan_number'] == '01']
geom_num = plan_row['Geom File'].iloc[0]
geom_path = ras.geom_df.loc[ras.geom_df['geom_number'] == geom_num, 'file_path'].iloc[0]
```

### Check Execution Status
```python
# Which plans have been executed?
executed_plans = ras.plan_df[ras.plan_df['HDF_Results_Path'].notna()]
print(f"Executed: {executed_plans['plan_number'].tolist()}")

# Which plans need execution?
pending_plans = ras.plan_df[ras.plan_df['HDF_Results_Path'].isna()]
print(f"Pending: {pending_plans['plan_number'].tolist()}")
```

### Get Plan Metadata
```python
# Plan title and configuration
plan_info = ras.plan_df[ras.plan_df['plan_number'] == '01'][
    ['plan_number', 'Plan Title', 'Geom File', 'Flow File', 'unsteady_number']
].iloc[0]

print(f"Plan {plan_info['plan_number']}: {plan_info['Plan Title']}")
print(f"  Geometry: g{plan_info['Geom File']}")
print(f"  Unsteady: u{plan_info['unsteady_number']}")
```

---

## Anti-Patterns to Avoid

### ❌ Anti-Pattern 1: Glob Instead of plan_df
```python
# DON'T DO THIS
hdf_files = list(project_path.glob("*.p01.hdf"))
hdf_path = hdf_files[0] if hdf_files else None

# DO THIS INSTEAD
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
```

**Why**: Glob patterns:
- Don't validate plan exists
- May find wrong files in complex project structures
- Are fragile to filename changes
- Don't work correctly with dest_folder parameter

### ❌ Anti-Pattern 2: Manual Path Construction
```python
# DON'T DO THIS
hdf_path = project_path / f"{project_name}.p01.hdf"

# DO THIS INSTEAD
hdf_path_str = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]
hdf_path = Path(hdf_path_str) if hdf_path_str else None
```

**Why**: Manual construction:
- Assumes file location (breaks with dest_folder)
- Doesn't check if plan was executed
- Misses renamed files or alternative locations

### ✅ Simplified: No Special Handling After Execution

**As of v0.88.1**: HDF results are automatically consolidated to the original project folder.
No special [Computed] folder handling is needed.

```python
# Simple workflow - just use plan_df after execution
init_ras_project(project_path, "6.6")
RasCmdr.compute_parallel(["01", "02"])

# plan_df is automatically refreshed with correct HDF paths
hdf_path = ras.plan_df['HDF_Results_Path'].iloc[0]  # Works!
```

---

## Library Implementation Requirements

### For Library Developers

When implementing new functions that execute HEC-RAS or modify project files:

1. **Update DataFrames after state changes**
   ```python
   def my_function(ras_object=None):
       _ras = ras_object if ras_object else ras

       # Perform operation that changes state
       modify_plan_file()

       # Refresh DataFrames
       _ras.plan_df = _ras.get_plan_entries()
   ```

2. **Document which DataFrames are affected**
   ```python
   def create_new_plan(...):
       """
       Create a new plan.

       Side Effects:
           - Updates ras.plan_df with new plan entry
           - Re-initializes plan_df automatically
       """
   ```

3. **Consider returning updated DataFrame rows**
   ```python
   def clone_plan(...) -> str:
       """
       Returns:
           str: New plan number

       Note:
           ras.plan_df is automatically refreshed. Access new plan via:
           ras.plan_df[ras.plan_df['plan_number'] == returned_value]
       """
   ```

---

## See Also

- **Context Object Discipline**: `.claude/rules/python/ras-commander-patterns.md` - ras_object parameter pattern
- **Static Classes**: `.claude/rules/python/static-classes.md` - DataFrame refresh in static methods

---

**Key Takeaway**: Always use DataFrames as authoritative source. Never use glob patterns or manual path construction. After `compute_parallel()` or `compute_test_mode()`, `plan_df` is automatically refreshed and HDF files are in the original project folder.
