# HDF Attribute Mapping Pattern

**Context**: Extracting HDF attributes into DataFrame columns
**Priority**: Medium - Affects HDF attribute flattening
**Auto-loads**: When working with HDF attribute extraction
**Discovered**: 2026-01-11 (results_df refactoring)

---

## Overview

When extracting HDF attributes into DataFrame columns, use **explicit mapping dictionaries** instead of dynamic sanitization for clarity, maintainability, and control.

---

## The Pattern

### ❌ Avoid: Dynamic Sanitization

**Problem**: Unpredictable column names, hard to maintain, obscures intent

```python
# BAD - Dynamic sanitization
for col in hdf_attrs.columns:
    # Sanitize column names for safe attribute access
    safe_col = str(col).replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'pct')
    result[f'vol_{safe_col}'] = row.get(col)

# Result: vol_Error_pct, vol_Total_Boundary_Flux_of_Water_In
# Unpredictable, hard to document
```

**Issues**:
- Column names depend on HDF attribute names (may change between HEC-RAS versions)
- Sanitization edge cases (what about '/', '-', etc.?)
- No control over output names
- Difficult to document expected schema
- Breaks when HDF attributes change

### ✅ Prefer: Explicit Mapping

**Solution**: Define explicit mapping from HDF attributes to desired column names

```python
# GOOD - Explicit mapping
VOL_COLUMN_MAP = {
    'Error': 'vol_error',
    'Error Percent': 'vol_error_percent',
    'Vol Accounting in': 'vol_accounting_units',
    'Total Boundary Flux of Water In': 'vol_flux_in',
    'Total Boundary Flux of Water Out': 'vol_flux_out',
    'Volume Starting': 'vol_starting',
    'Volume Ending': 'vol_ending',
}

for hdf_attr, df_column in VOL_COLUMN_MAP.items():
    if hdf_attr in hdf_attrs.columns:
        result[df_column] = row.get(hdf_attr)

# Result: vol_error, vol_flux_in - predictable, documented
```

**Benefits**:
- ✅ Exact control over column names
- ✅ Self-documenting (shows HDF → DataFrame mapping)
- ✅ Easy to update when requirements change
- ✅ Clear expected schema
- ✅ Graceful handling of missing attributes

---

## When to Use Explicit Mapping

**Use explicit mapping when**:
- Building user-facing DataFrame schemas
- Column names are part of public API
- Need consistent naming across HEC-RAS versions
- Attribute names may have special characters

**Dynamic sanitization is OK when**:
- Internal/private DataFrames
- Column names are temporary/exploratory
- All attributes should be included (no filtering)
- HDF attributes are well-behaved (no special chars)

---

## Real-World Example

### results_df Volume Accounting

**Implementation**: `ras_commander/results/ResultsSummary.py:155-163`

```python
# Volume column mapping (HDF attribute name -> results_df column name)
VOL_COLUMN_MAP = {
    'Error': 'vol_error',
    'Vol Accounting in': 'vol_accounting_units',
    'Error Percent': 'vol_error_percent',
    'Total Boundary Flux of Water In': 'vol_flux_in',
    'Total Boundary Flux of Water Out': 'vol_flux_out',
    'Volume Starting': 'vol_starting',
    'Volume Ending': 'vol_ending',
}

try:
    vol_df = HdfResultsPlan.get_volume_accounting(hdf_path)
    if vol_df is not None and len(vol_df) > 0:
        vol_row = vol_df.iloc[0]
        # Map HDF columns to standardized column names
        for hdf_col, result_col in VOL_COLUMN_MAP.items():
            if hdf_col in vol_df.columns:
                result[result_col] = vol_row.get(hdf_col)
except Exception as e:
    logger.debug(f"Error extracting volume accounting: {e}")
```

**Why this works**:
- HDF has attributes like "Error Percent", "Vol Accounting in"
- Want standardized names: `vol_error_percent`, `vol_accounting_units`
- Explicit mapping makes intent clear
- Future-proof (can update mapping if HDF changes)

---

## Migration Pattern

**When replacing dynamic sanitization with explicit mapping**:

1. **Discover HDF attribute names** (inspect actual HDF file):
   ```python
   import h5py
   with h5py.File("project.p01.hdf", 'r') as hdf:
       attrs = dict(hdf["Results/Unsteady/Summary/Volume Accounting"].attrs)
       print(list(attrs.keys()))  # Exact attribute names
   ```

2. **Create mapping dictionary**:
   ```python
   ATTR_MAP = {
       'HDF Attribute Name': 'desired_column_name',
       # ... for each attribute
   }
   ```

3. **Replace sanitization loop**:
   ```python
   for hdf_attr, df_col in ATTR_MAP.items():
       if hdf_attr in source_df.columns:
           result[df_col] = row.get(hdf_attr)
   ```

4. **Update column schema documentation** (e.g., `get_summary_columns()`)

---

## See Also

- **Implementation Example**: `ras_commander/results/ResultsSummary.py:155-174`
- **HDF Attribute Reference**: `.claude/outputs/2026-01-11-results-df-refactoring-closeout.md`
- **Naming Conventions**: `.claude/rules/python/naming-conventions.md`

---

**Key Takeaway**: Use explicit mapping dictionaries for HDF attribute → DataFrame column mapping. Provides clarity, control, and maintainability over dynamic sanitization.
