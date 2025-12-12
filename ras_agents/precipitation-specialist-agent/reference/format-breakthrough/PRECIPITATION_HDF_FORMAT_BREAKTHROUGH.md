# HEC-RAS 6.6 Precipitation HDF Format - Breakthrough Documentation

**Date:** December 10, 2025
**Status:** RESOLVED - Python precipitation import now works with HEC-RAS 6.6
**Test Result:** 416.3 MB output, 0.000153% volume error, 1248x realtime speed

## Executive Summary

After extensive investigation including decompilation of HEC-RAS assemblies and byte-level HDF comparison, we discovered that HEC-RAS 6.6 uses a **completely different** precipitation HDF format than HEC-RAS 5.x. The old example files in the HEC-RAS distribution were created with version 5.x and are incompatible with 6.6.

The solution was to perform a manual GDAL import using the HEC-RAS 6.6 GUI, then reverse-engineer the exact format it produces.

## Root Cause Analysis

### Why Previous Attempts Failed

The reference file `BaldEagleDamBrk.u04.hdf` from the HEC-RAS example projects was created with **HEC-RAS 5.00** (verified via `Program Version=5.00` in the plan file). When run with HEC-RAS 6.6, it produces:

```
Error processing layer - could not parse timestamps.
Error processing Precipitation data, exiting...
```

This error occurs because HEC-RAS 6.6 cannot parse the timestamp format used in 5.x files.

### The Discovery Process

1. **Initial hypothesis:** Format issues (compression, chunking, fillvalue)
2. **Decompilation analysis:** Examined H5Assist.dll, GDALAssist.dll, RAS.dll
3. **Critical insight:** Running the REFERENCE example plan also fails!
4. **Breakthrough:** Manual GUI import with HEC-RAS 6.6 creates a working file
5. **Solution:** Compare Python output against GUI-imported file, match exactly

## HEC-RAS 5.x vs 6.6 Format Comparison

| Feature | HEC-RAS 5.x (BROKEN) | HEC-RAS 6.6 (WORKING) |
|---------|---------------------|----------------------|
| **Times format** | `15Apr2020 00:00:00` | `2020-04-15 00:00:00` |
| **Times dtype** | `\|S22` | `\|S19` |
| **Timestamp dataset** | YES (separate) | NO |
| **Values chunks** | None | (n_times, n_cells) |
| **Values compression** | None | gzip level 1 |
| **Values fillvalue** | 0.0 | nan |
| **NoData dtype** | float64 | float32 |
| **IRD group attrs** | 7 (grid extent) | 0 |
| **Enabled dtype** | uint8 | uint8 |

### Key Format Changes in HEC-RAS 6.6

1. **ISO 8601 Timestamps:** `YYYY-MM-DD HH:MM:SS` instead of `DDMmmYYYY HH:MM:SS`
2. **No Separate Timestamp Dataset:** Timestamps only in `Times` attribute on Values dataset
3. **Chunked + Compressed:** Single chunk, gzip level 1
4. **NaN Fillvalue:** Not 0.0
5. **Grid Attrs on Values:** Not on Imported Raster Data group

## Exact HEC-RAS 6.6 Format Specification

### Precipitation Group (`Event Conditions/Meteorology/Precipitation`)

```python
# Attributes
'Enabled': np.uint8(1)
'Mode': b'Gridded'
'Source': b'GDAL Raster File(s)'
'GDAL Filename': b'.\\Precipitation\\filename.nc'
'GDAL Datasetname': b''
'GDAL Filter': b''
'GDAL Folder': b''
'Interpolation Method': b'Nearest'  # or 'Bilinear'
```

### Meteorology Attributes Dataset (`Event Conditions/Meteorology/Attributes`)

```python
# Compound dtype
dtype = np.dtype([('Variable', 'S32'), ('Group', 'S42')])
data = np.array([(b'Precipitation', b'Event Conditions/Meteorology/Precipitation')], dtype=dtype)
# chunks=(1,), compression='gzip'
```

### Imported Raster Data Group

```python
# NO attributes on this group (unlike 5.x which had grid extent attrs here)
```

### Values Dataset

```python
# Dataset properties
shape = (n_times, n_cells)  # n_cells = rows * cols
dtype = np.float32
chunks = (n_times, n_cells)  # Single chunk
compression = 'gzip'
compression_opts = 1
fillvalue = np.nan

# Attributes
'Data Type': b'cumulative'
'GUID': b'<uuid>'
'NoData': np.float32(-9999.0)
'Projection': b'<WKT string for EPSG:5070>'
'Raster Cellsize': np.float64(cellsize)
'Raster Cols': np.int32(n_cols)
'Raster Left': np.float64(left_edge)
'Raster Rows': np.int32(n_rows)
'Raster Top': np.float64(top_edge)
'Rate Time Units': b'Hour'
'Storage Configuration': b'Sequential'
'Time Series Data Type': b'Amount'
'Times': np.array(['2020-04-15 00:00:00', ...], dtype='S19')  # ISO 8601!
'Units': b'mm'
'Version': b'1.0'
```

## Code Changes Made

### File: `ras_commander/RasUnsteady.py`

Function `_update_precipitation_hdf()` was completely rewritten to match HEC-RAS 6.6 format.

**Key changes:**

```python
# 1. Timestamp format - ISO 8601
timestamp_strs = [t.strftime('%Y-%m-%d %H:%M:%S') for t in timestamps]  # NOT '%d%b%Y %H:%M:%S'

# 2. Times attribute dtype
'Times': np.array(timestamp_strs, dtype='S19')  # NOT 'S22'

# 3. Values dataset - chunked, compressed, nan fillvalue
values_ds = raster_grp.create_dataset(
    'Values',
    data=precip_cumulative,
    dtype=np.float32,
    chunks=(n_times, n_cells),
    compression='gzip',
    compression_opts=1,
    fillvalue=np.nan  # NOT 0.0
)

# 4. NoData as float32
'NoData': np.float32(-9999.0)  # NOT float64

# 5. No Timestamp dataset created (removed)

# 6. No grid attrs on Imported Raster Data group (removed)

# 7. Meteorology/Attributes dataset created for indexing
```

## Verification Test Results

```
================================================================================
COMPARISON: Our Python Output vs HEC-RAS 6.6 GUI Reference
================================================================================

Precipitation Group Attributes:
  [OK] Enabled: ours=1 ref=1
  [OK] Mode: ours=b'Gridded' ref=b'Gridded'
  [OK] Source: ours=b'GDAL Raster File(s)' ref=b'GDAL Raster File(s)'
  [OK] GDAL Filename: ours=b'.\\Precipitation\\storm_20200415.nc' ref=b'.\\Precipitation\\storm_20200415.nc'
  [OK] Interpolation Method: ours=b'Nearest' ref=b'Nearest'

Values Dataset:
  [OK] shape: ours=(144, 352) ref=(144, 352)
  [OK] dtype: ours=float32 ref=float32
  [OK] chunks: ours=(144, 352) ref=(144, 352)
  [OK] compression: ours=gzip ref=gzip
  [OK] fillvalue: ours=nan ref=nan

Values Attributes:
  [OK] Data Type: ours=b'cumulative' ref=b'cumulative'
  [OK] NoData value: ours=-9999.0 ref=-9999.0
  [OK] NoData dtype: ours=float32 ref=float32
  [OK] Units: ours=b'mm' ref=b'mm'
  [OK] Times dtype: ours=|S19 ref=|S19
       Times[0]: ours=b'2020-04-15 00:00:00' ref=b'2020-04-15 00:00:00'
  [OK] Timestamp dataset: ours=False ref=False
  [OK] IRD group attrs: ours=0 ref=0
```

## HEC-RAS Compute Results

```
Plan: 'Python GDAL Precip Test' (BaldEagleDamBrk.p21)
Result: True (SUCCESS)
Elapsed: 360.4 seconds
Output HDF: 416.3 MB

Processing Precipitation data...
   (assumes geometry data is geo-referenced)
Warning: Some of the 2D Cells in Mesh "BaldEagleCr" were out-of-bounds in the input raster.
Warning: Some of the 2D Faces in Mesh "BaldEagleCr" were out-of-bounds in the input raster.
Finished Processing Precipitation data (1.152s)

Overall Volume Accounting Error in Acre Feet: 0.2114
Overall Volume Accounting Error as percentage: 0.000153

Computation Speed: 1248x realtime
```

## Investigation Methodology

### 1. Decompilation Approach

Used ILSpyCMD 9.1.0.7988 to decompile HEC-RAS .NET assemblies:

```bash
ilspycmd "C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.dll" -p -o "RAS"
ilspycmd "C:\Program Files (x86)\HEC\HEC-RAS\6.6\H5Assist.dll" -p -o "H5Assist"
ilspycmd "C:\Program Files (x86)\HEC\HEC-RAS\6.6\Geospatial.GDALAssist.dll" -p -o "GDALAssist"
```

**Key findings from decompilation:**
- `H5Assist/H5Writer.cs:275` - Uses ASCII encoding for all strings
- `GDALAssist/GDALRaster.cs` - GDAL file parsing expects ISO 8601 timestamps
- RAS.dll ViewModels - Event condition processing logic

### 2. HDF Comparison Strategy

Created detailed comparison scripts to examine:
- Dataset properties (shape, dtype, chunks, compression, fillvalue)
- All attribute types and values
- Binary/byte-level timestamp encoding
- Group structure differences

### 3. Golden Reference Creation

**Critical step:** Used HEC-RAS 6.6 GUI to import the same NetCDF file:
1. Open project in HEC-RAS 6.6
2. Edit > Unsteady Flow Data > Meteorological Data > Gridded Precipitation
3. Set Source: "GDAL Raster File(s)"
4. Click "Import Raster Data"
5. Select NetCDF file, set Data Type="per-cum", Units="mm"
6. Save - this creates the golden reference HDF

## Extent Coverage and Buffering

### The Warning (Non-Fatal)

```
Warning: Some of the 2D Cells in Mesh "BaldEagleCr" were out-of-bounds in the input raster.
Warning: Some of the 2D Faces in Mesh "BaldEagleCr" were out-of-bounds in the input raster.
```

This warning is **non-fatal** - the simulation runs successfully. It indicates some mesh cells fall outside the precipitation raster extent after HEC-RAS performs on-the-fly CRS reprojection.

### CRS Mismatch Handling

The geometry and precipitation use different coordinate systems:
- **Geometry:** Pennsylvania State Plane North (Feet) - `NAD_1983_StatePlane_Pennsylvania_North_FIPS_3701_Feet`
- **Precipitation:** NAD83 / Conus Albers (Meters) - `EPSG:5070`

HEC-RAS handles this automatically:
```
Processing Precipitation data...
   (assumes geometry data is geo-referenced)
```

### Solution: Use HdfProject.get_project_bounds_latlon()

The proper workflow to avoid extent warnings:

```python
from ras_commander.hdf.HdfProject import HdfProject
from ras_commander.precip import PrecipAorc

# Get properly buffered bounds from geometry HDF
bounds = HdfProject.get_project_bounds_latlon(
    "BaldEagleDamBrk.g09.hdf",
    buffer_percent=50.0,  # Default - adds 50% buffer
    include_1d=True,
    include_2d=True,
    include_storage=True
)

# Download with proper extent
output = PrecipAorc.download(
    bounds=bounds,
    start_time="2020-04-15",
    end_time="2020-04-20",
    output_path="Precipitation/aorc_precip.nc"
)
```

### Buffer Comparison

| Buffer % | West | South | East | North | Coverage |
|----------|------|-------|------|-------|----------|
| 0% | -77.7591 | 40.9607 | -77.3275 | 41.1849 | Exact mesh extent |
| 10% | -77.7807 | 40.9494 | -77.3059 | 41.1961 | Small margin |
| 25% | -77.8131 | 40.9325 | -77.2734 | 41.2129 | Moderate |
| **50%** | -77.8672 | 40.9044 | -77.2192 | 41.2408 | **Default, recommended** |
| 100% | -77.9754 | 40.8479 | -77.1106 | 41.2965 | Large watershed studies |

### Why My Test Had Warnings

I manually specified bounds `(-77.71, 41.01, -77.25, 41.22)` without using the helper function. The correct bounds with 50% buffer would have been `(-77.8672, 40.9044, -77.2192, 41.2408)`.

## Files Created/Modified

### Modified
- `ras_commander/RasUnsteady.py` - `_update_precipitation_hdf()` function

### Test Files Created
- `examples/example_projects/BaldEagleCrkMulti2D_precip_test/` - Test project
- `BaldEagleDamBrk.u20.hdf` - GUI-imported reference (golden standard)
- `BaldEagleDamBrk.u21` - Python-generated test
- `BaldEagleDamBrk.p21` - Test plan
- `Precipitation/storm_20200415.nc` - AORC precipitation data

### Documentation
- `planning_docs/PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md` - This file
- `planning_docs/DSS_SPATIAL_GRID_WRITING_RESEARCH.md` - DSS alternative research
- `planning_docs/PRECIPITATION_INVESTIGATION_FINAL_SUMMARY.md` - Investigation history

## Lessons Learned

1. **Never trust example files** - They may be from older versions
2. **Use GUI as ground truth** - When reverse-engineering, create reference with current version
3. **Byte-level comparison** - Format issues hide in dtype differences
4. **Timestamp parsing is fragile** - ISO 8601 vs custom formats cause silent failures
5. **Decompilation helps understand intent** - But runtime behavior is the ultimate test

## Next Steps

1. **Buffering fix** - Add generous buffer to extent calculations
2. **Update notebook** - Integrate fixes into `examples/24_aorc_precipitation.ipynb`
3. **Add tests** - Create automated tests for precipitation HDF format
4. **Document API** - Update docstrings with format requirements
