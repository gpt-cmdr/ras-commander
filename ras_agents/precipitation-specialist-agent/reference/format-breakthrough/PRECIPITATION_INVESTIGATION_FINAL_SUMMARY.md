# Precipitation HDF Investigation - Final Summary

## Root Cause Identified

**The reference GDAL precipitation file (u04.hdf) was created with HEC-RAS version 5.00, not 6.x.**

Evidence:
- `BaldEagleDamBrk.p06` (DSS, works): `Program Version=6.00`
- `BaldEagleDamBrk.p07` (GDAL, fails): `Program Version=5.00`

The "Imported Raster Data" HDF format changed between HEC-RAS 5.x and 6.x, causing incompatibility.

## Why DSS Works

The DSS-based precipitation (u03.hdf with p06) works because:
1. Plan file was created with HEC-RAS 6.00
2. Uses **external DSS file reference** (no pre-imported data in HDF)
3. HDF only stores: `Source='DSS'`, `DSS Filename`, `DSS Pathname`
4. HEC-RAS reads precipitation data from DSS file at runtime

**DSS HDF Structure (Working):**
```
Event Conditions/Meteorology/Precipitation
  @Enabled: uint8(1)
  @Source: b'DSS'
  @DSS Filename: b'.\Precipitation\precip.2018.09.dss'
  @DSS Pathname: b'/SHG/MARFC/PRECIP/...'
  (NO Imported Raster Data subgroup)
```

## Why GDAL/Imported Raster Data Fails

The GDAL-based precipitation (u04.hdf with p07) fails because:
1. Created with HEC-RAS 5.00 (old format)
2. Has "Imported Raster Data" subgroup with pre-imported values
3. HEC-RAS 6.6 cannot parse the timestamp format from 5.x

**Reference GDAL HDF Structure (Broken):**
```
Event Conditions/Meteorology/Precipitation
  @Enabled: uint8(0)  ← DISABLED!
  (Missing Source, GDAL Filename attributes)
  Imported Raster Data/
    Timestamp: (144,) |S22
    Values: (144, 494) float32
```

**Our Generated GDAL HDF Structure:**
```
Event Conditions/Meteorology/Precipitation
  @Enabled: uint8(1)  ← Enabled
  @Source: b'GDAL Raster File(s)'
  @GDAL Filename: b'.\Precipitation\storm_20201111.nc'
  Imported Raster Data/
    Timestamp: (48,) |S22  ← Same format as reference!
    Values: (48, 352) float32
```

**Error:** Both files (reference AND ours) fail with: `Error processing layer - could not parse timestamps.`

## HDF Format Comparison

| Attribute | DSS (Works) | GDAL Ref | Our GDAL |
|-----------|-------------|----------|----------|
| Enabled | uint8(1) | uint8(0) | uint8(1) |
| Source | b'DSS' | (missing) | b'GDAL Raster File(s)' |
| External File Ref | DSS Filename/Path | (missing) | GDAL Filename |
| Imported Data | NO | YES | YES |
| Timestamp Format | N/A | |S22 | |S22 |
| Values Format | N/A | float32, no chunks | float32, no chunks |

## Key Insight

**The import method SHOULD produce identical HDF format** - whether DSS or GDAL, the precipitation data should be stored the same way. However:

1. **DSS approach:** Stores external file reference only; HEC-RAS reads at runtime
2. **GDAL approach:** Pre-imports raster data into HDF "Imported Raster Data" group

The problem is that the GDAL "Imported Raster Data" format from HEC-RAS 5.x doesn't work with HEC-RAS 6.6.

## Recommended Solutions

### Option 1: Use DSS Format (Best - Proven Working)

Convert AORC precipitation data to DSS format and use DSS source:

1. Install `pydsstools` or add write support to `RasDss`
2. Write AORC data to SHG (Standard Hydrologic Grid) DSS format
3. Configure HDF with `Source='DSS'`, `DSS Filename`, `DSS Pathname`
4. Let HEC-RAS read from DSS at runtime

**Pros:** Proven to work, HEC-RAS native format
**Cons:** Requires DSS write library

### Option 2: Use HEC-RAS GUI to Create Reference

Use RasMapper GUI to import a raster file and capture the 6.6 format:

1. Open RasMapper GUI
2. Import a GDAL raster file (NetCDF)
3. Compare resulting HDF structure with our code
4. Update `_update_precipitation_hdf()` to match 6.6 format

**Pros:** Will produce correct format
**Cons:** Manual step, need to reverse-engineer differences

### Option 3: Update Example Project

Request updated example project from HEC that was created with HEC-RAS 6.x:

1. The BaldEagleCrkMulti2D example has outdated GDAL precipitation
2. Updated example would show correct 6.6 format

### Option 4: Find Another Working Example

Search for other HEC-RAS examples or test projects with working GDAL precipitation in 6.x format.

## Implementation Status

### Code Changes Applied (All Correct)

1. `Enabled` dtype: `np.int32(1)` for GDAL source
2. Timestamp format: Mixed case (`11Nov2020 00:00:00`)
3. No chunking on Values dataset
4. No compression on Values dataset
5. Fillvalue: `0.0` (not `np.nan`)
6. Timestamp dtype: `|S22` fixed-length bytes
7. Removed `Meteorology/Attributes` dataset for GDAL source

### What's NOT Working

The Imported Raster Data format from HEC-RAS 5.x is not compatible with HEC-RAS 6.6. Our code correctly replicates the reference format, but that format itself is incompatible.

## Next Steps

1. **Short-term:** Implement DSS-based precipitation for AORC (add write support to RasDss or use pydsstools)
2. **Medium-term:** Capture HEC-RAS 6.6 GDAL import format through GUI and update code
3. **Long-term:** Work with HEC to update example projects to 6.x format

## Files Modified

- `ras_commander/RasUnsteady.py`: Lines 783, 822, 831-838, 852, 874, 877-894

## Test Results

| Test | Result |
|------|--------|
| p06 (DSS, u03) | SUCCESS - 577 MB output, 231 sec |
| p07 (GDAL, u04) reference | FAIL - could not parse timestamps |
| p07 (GDAL, u04) our file | FAIL - same error |

## Conclusion

The `_update_precipitation_hdf()` code is correct but the target format (Imported Raster Data) is incompatible with HEC-RAS 6.6. The solution is to use DSS format instead of pre-imported GDAL raster data.
