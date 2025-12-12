# Precipitation HDF Investigation - Complete Report

**Investigation Date:** 2025-12-10
**Investigator:** Claude Code
**Issue:** Python precipitation import doesn't work correctly with HEC-RAS

---

## Files in This Investigation

### Primary Documents

1. **`precipitation_hdf_comparison.md`** - Complete detailed analysis
   - Line-by-line comparison of working HEC-RAS file vs Python implementation
   - Root cause analysis for each difference
   - Evidence from actual HDF inspection
   - Full fix implementation guide

2. **`precipitation_fixes_summary.md`** - Quick reference guide
   - Summary of 6 critical/major issues
   - Exact code changes needed (before/after)
   - Testing checklist

3. **`precipitation_structure_comparison.txt`** - Visual side-by-side
   - ASCII side-by-side comparison of HDF structure
   - Easy to see what matches and what doesn't
   - Visual markers for issues

### Scripts

4. **`inspect_gdal_precipitation.py`** - HDF inspection tool
   - Detailed inspection of working HEC-RAS precipitation HDF
   - Prints all groups, datasets, attributes with types
   - Used to generate evidence for comparison

5. **`find_gdal_precipitation.py`** - Search tool
   - Searches projects for GDAL raster precipitation
   - Distinguishes DSS vs GDAL raster sources
   - Found the working example file

6. **`compare_precipitation_implementation.py`** - Comparison tool
   - Automated comparison of implementation vs working file
   - Generates list of issues with severity ratings
   - Outputs recommended fixes

7. **`validate_precipitation_fix.py`** - Validation tool
   - Run against generated HDF to verify fixes
   - Checks all 6 critical/major issues
   - Returns success/fail with detailed messages
   - **Usage:** `python validate_precipitation_fix.py <hdf_file>`

---

## Key Findings Summary

### Working Reference File
- **Project:** BaldEagleCrkMulti2D
- **File:** `BaldEagleDamBrk.u04.hdf`
- **Source:** GDAL Raster File(s)
- **Data:** 144 timesteps, 494 cells (19 rows × 26 cols)
- **NetCDF:** `storm_20200417.nc`

### Critical Issues Found (6)

| # | Issue | Severity | Code Line | Impact |
|---|-------|----------|-----------|--------|
| 1 | Enabled attribute type (uint8 vs int32) | CRITICAL | 822 | May prevent HEC-RAS from recognizing precipitation |
| 2 | Times attribute format (ISO 8601 vs HEC-RAS) | CRITICAL | 874 | Time parsing will fail |
| 3 | Unnecessary Meteorology/Attributes dataset | MAJOR | 831-838 | Wrong workflow indicator |
| 4 | Values dataset chunking | MAJOR | 886, 900 | Performance/compatibility issues |
| 5 | Values dataset compression | MAJOR | 887-888, 901-902 | Decompression overhead |
| 6 | Values fillvalue (np.nan vs 0.0) | MAJOR | 889, 903 | Semantic confusion |

### Root Causes

1. **Type assumptions** - Assumed uint8 for boolean, but HEC-RAS uses int32
2. **Over-optimization** - Added chunking/compression that HEC-RAS doesn't use
3. **Format mismatch** - Created separate ISO 8601 timestamps instead of reusing HEC-RAS format
4. **DSS confusion** - Included dataset (Meteorology/Attributes) from DSS workflow
5. **Convention difference** - Used Python convention (np.nan) vs HEC-RAS (0.0 for no precip)

---

## Quick Start: Fixing the Implementation

### 1. Apply Fixes to RasUnsteady.py

Open `ras_commander/RasUnsteady.py` and make these changes:

```python
# Line 822: Change Enabled type
precip_grp.attrs['Enabled'] = np.int32(1)  # was: np.uint8(1)

# Lines 831-838: DELETE entire Meteorology/Attributes block

# Line 784: DELETE (no longer needed)
# timestamp_iso = [t.strftime('%Y-%m-%d %H:%M:%S') for t in timestamps]

# Line 874: Use HEC-RAS format
'Times': np.array(timestamp_strs, dtype='S22'),  # was: timestamp_iso, 'S19'

# Lines 882-891: Remove chunking/compression, fix fillvalue
values_ds = raster_grp.create_dataset(
    'Values',
    data=precip_cumulative,
    dtype=np.float32,
    # Remove: chunks=(n_times, n_cells),
    # Remove: compression='gzip',
    # Remove: compression_opts=1,
    fillvalue=0.0,  # was: np.nan
    maxshape=(None, None)
)

# Lines 896-905: Same fixes for Values (Vertical)
values_vert_ds = raster_grp.create_dataset(
    'Values (Vertical)',
    data=precip_cumulative,
    dtype=np.float32,
    # Remove: chunks=(n_times, n_cells),
    # Remove: compression='gzip',
    # Remove: compression_opts=1,
    fillvalue=0.0,  # was: np.nan
    maxshape=(None, None)
)
```

### 2. Test the Fix

```bash
# Generate test HDF with fixed code
python test_precipitation.py

# Validate against requirements
python planning_docs/validate_precipitation_fix.py test.u01.hdf
```

Expected output:
```
[OK] Enabled: int32 = 1
[OK] Meteorology/Attributes: not present (correct)
[OK] Timestamp: |S22, format=15Apr2020 00:00:00
[OK] Values: no chunking (contiguous)
[OK] Values: no compression
[OK] Values: fillvalue=0.0
[OK] Values/Times: |S22, format=15Apr2020 00:00:00
[OK] Values: all 14 required attributes present

================================================================================
VALIDATION RESULTS
================================================================================

*** ALL CHECKS PASSED! ***
```

### 3. Verify in HEC-RAS

1. Open project in HEC-RAS GUI
2. Unsteady Flow Editor → Meteorology → Precipitation
3. Verify "Import Raster Data" shows correct timesteps
4. Run computation
5. Verify precipitation is applied (check results)

---

## Investigation Methodology

1. **Search for examples** - Found BaldEagleDamBrk.u04.hdf with GDAL raster precipitation
2. **Inspect working file** - Used h5py to dump complete structure with types
3. **Compare implementations** - Identified 6 differences between working and Python code
4. **Root cause analysis** - Determined why each difference occurred
5. **Create validation** - Built automated validator to verify fixes
6. **Document findings** - Comprehensive report with evidence and fixes

---

## Lessons Learned

### When Reverse-Engineering Binary Formats

1. **Match exactly** - Don't "improve" or optimize without evidence
2. **Types matter** - int32 vs uint8 can break parsers completely
3. **Check all examples** - DSS vs GDAL have different structures
4. **String formats are literal** - Date formats must match exactly
5. **Storage matters** - Chunking/compression changes file layout
6. **Semantics matter** - np.nan vs 0.0 have different meanings

### Best Practices

- Always inspect working examples with h5py first
- Document every attribute type, not just value
- Test storage properties (chunks, compression, fillvalue)
- Check string encodings and lengths
- Validate against working file before testing in application

---

## Next Steps

1. Apply fixes to `ras_commander/RasUnsteady.py`
2. Run validation script to verify
3. Test in actual HEC-RAS project
4. Update any related documentation
5. Consider adding automated tests comparing generated HDF to reference

---

## Contact

For questions about this investigation or the fixes, refer to:
- Full analysis: `precipitation_hdf_comparison.md`
- Quick fixes: `precipitation_fixes_summary.md`
- Validation tool: `validate_precipitation_fix.py`
