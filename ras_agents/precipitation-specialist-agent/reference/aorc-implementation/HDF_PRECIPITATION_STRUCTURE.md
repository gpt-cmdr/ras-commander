# HEC-RAS Precipitation HDF Structure

## Overview

When HEC-RAS imports gridded precipitation data via "Import Raster Data" in the Unsteady Flow Editor, it stores the data in a specific format within the `.u##.hdf` file. This document describes the exact structure required for programmatic import.

## Key Findings

### 1. Data Shape Transformation

- **NetCDF Input**: `(time, y, x)` - e.g., `(144, 16, 22)`
- **HDF Output**: `(time, rows*cols)` - e.g., `(144, 352)` where 352 = 16×22

The spatial dimensions are **flattened** to a 1D array per timestep. This is NOT sampling to mesh cells - it's simply reshaping the raster grid.

### 2. Cumulative vs Instantaneous

- **NetCDF Input**: Instantaneous precipitation rate (mm/hr or kg/m²/hr)
- **HDF Output**: Cumulative total precipitation (mm)

Transformation: `cumulative = np.cumsum(instantaneous, axis=0)`

This means values are monotonically increasing over time for each cell.

### 3. Required Datasets

The HDF must contain these datasets under `Event Conditions/Meteorology/Precipitation/Imported Raster Data/`:

| Dataset | Shape | Dtype | Description |
|---------|-------|-------|-------------|
| `Timestamp` | `(n_times,)` | `|S22` | HEC-RAS format: "28Apr2020 00:00:00" |
| `Values` | `(n_times, rows*cols)` | `float32` | Cumulative precipitation |
| `Values (Vertical)` | `(n_times, rows*cols)` | `float32` | Duplicate of Values |

### 4. Required Attributes

#### On Precipitation Group

```
Event Conditions/Meteorology/Precipitation/
  Attributes:
    Enabled: 1 (int32)
    Mode: "Gridded"
    Source: "GDAL Raster File(s)"
    GDAL Filename: ".\Precipitation\storm_20200430.nc"
    GDAL Datasetname: ""
    GDAL Filter: ""
    GDAL Folder: ""
    Interpolation Method: "Bilinear"
```

#### On Imported Raster Data Group

```
Event Conditions/Meteorology/Precipitation/Imported Raster Data/
  Attributes:
    Cellsize: 2000.0 (float64)
    Cols: 22 (int32)
    Rows: 16 (int32)
    Left: 1512379.96... (float64) - left edge of raster
    Right: 1556379.96... (float64) - right edge of raster
    Bottom: 2135021.64... (float64) - bottom edge of raster
    Top: 2177021.64... (float64) - top edge of raster
```

Note: Left/Right/Bottom/Top are **cell edges**, not cell centers. Calculate as:
- `Left = x_min - cellsize/2`
- `Right = x_max + cellsize/2`
- `Bottom = y_min - cellsize/2`
- `Top = y_max + cellsize/2`

#### On Values Datasets

Both `Values` and `Values (Vertical)` require these attributes:

```
  Data Type: "cumulative"
  GUID: "006f157e-d2c5-4fe2-a595-1a27a091d874" (unique UUID)
  NoData: -9999.0 (float64)
  Projection: <EPSG:5070 WKT string>
  Raster Cellsize: 2000.0 (float64)
  Raster Cols: 22 (int32)
  Raster Left: 1512379.96... (float64)
  Raster Rows: 16 (int32)
  Raster Top: 2177021.64... (float64)
  Rate Time Units: "Hour"
  Storage Configuration: "Sequential"
  Time Series Data Type: "Amount"
  Times: [array of timestamp strings]
  Units: "mm"
  Version: "1.0"
```

## Example: Fixed HDF Analysis

From `BaldEagleCrkMulti2D - FixedNetCDFGridPrecip/BaldEagleDamBrk.u04.hdf`:

```
Values dataset:
  Shape: (144, 352)  # 144 timesteps, 352 = 16×22 cells
  Dtype: float32
  Data range: 0.0 to 677.0 mm (cumulative)

  First timestep: all zeros (no precip yet)
  Last timestep: cumulative totals up to 677mm in wettest cell
```

Time series for a single cell (monotonically increasing):
```
Hour 0-10:  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
Hour 50-60: [0, 2, 8, 9, 9, 9, 9, 14, 18, 39]
Hour 134-144: [494, 494, 494, 494, 494, 494, 494, 494, 494, 494]
```

## Implementation

The `RasUnsteady._update_precipitation_hdf()` function implements this structure:

```python
# 1. Flatten spatial dimensions
precip_flat = precip_data.reshape(n_times, n_rows * n_cols)

# 2. Convert to cumulative
precip_cumulative = np.cumsum(precip_flat, axis=0)

# 3. Create both Values and Values (Vertical) datasets
values_ds = raster_grp.create_dataset('Values', data=precip_cumulative, dtype=np.float32)
values_vert_ds = raster_grp.create_dataset('Values (Vertical)', data=precip_cumulative, dtype=np.float32)

# 4. Add all required attributes
for attr_name, attr_val in values_attrs.items():
    values_ds.attrs[attr_name] = attr_val
    values_vert_ds.attrs[attr_name] = attr_val
```

## Common Errors

### "Expected precip dataset ... does not exist"

This error occurs when HEC-RAS cannot find `/Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values` in the HDF file. Solution: Ensure `_update_precipitation_hdf()` is called to import the data.

### "Some 2D Cells were out-of-bounds"

This warning occurs when the precipitation raster doesn't fully cover the 2D mesh. Solution: Use larger bounds when downloading precipitation data. Calculate required bounds from mesh extent with a buffer.

## Projection Notes

- HEC-RAS expects precipitation data in EPSG:5070 (NAD83 / Conus Albers)
- The `PrecipAorc.download()` function automatically reprojects to EPSG:5070
- The WKT string stored in HDF should match the NAD83/Conus Albers definition
