# AORC API Reference

Complete API documentation for AORC (Analysis of Record for Calibration) precipitation data integration.

## Module: `ras_commander.precip.PrecipAorc`

All methods are static (no instantiation required).

---

## Data Retrieval Methods

### `retrieve_aorc_data()`

Download AORC precipitation time series for a watershed.

```python
PrecipAorc.retrieve_aorc_data(
    watershed,           # str (HUC code) or Path (shapefile)
    start_date,          # str "YYYY-MM-DD" or datetime
    end_date,            # str "YYYY-MM-DD" or datetime
    target_crs=None,     # str "EPSG:XXXX" or None (use watershed CRS)
    resolution=None      # float (meters) or None (use native ~800m)
)
```

**Returns**: `xarray.Dataset` with hourly precipitation on grid

**Parameters**:
- `watershed`: HUC-8/HUC-10 code (e.g., "02070010") or path to shapefile
- `start_date`: Start of time period
- `end_date`: End of time period
- `target_crs`: Target coordinate system (default: match watershed CRS)
- `resolution`: Grid resolution in meters (default: ~800m native resolution)

**Example**:
```python
data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-05-01",
    end_date="2015-05-15"
)
# Returns xarray Dataset with 'APCP_surface' variable (mm/hr)
```

---

### `download()`

Low-level AORC download to NetCDF file.

```python
PrecipAorc.download(
    bounds,              # tuple (west, south, east, north) in WGS84
    start_time,          # str or datetime
    end_time,            # str or datetime
    output_path,         # str or Path
    target_crs="EPSG:5070",  # str
    resolution=2000.0    # float (meters)
)
```

**Returns**: `Path` to output NetCDF file

**Parameters**:
- `bounds`: Bounding box (west, south, east, north) in degrees WGS84
- `start_time`: Start of time period
- `end_time`: End of time period
- `output_path`: Path for output NetCDF file
- `target_crs`: Target coordinate system (default: EPSG:5070 - CONUS Albers)
- `resolution`: Grid resolution in meters

**Example**:
```python
nc_file = PrecipAorc.download(
    bounds=(-77.5, 38.5, -76.5, 39.5),
    start_time="2015-05-01 00:00",
    end_time="2015-05-15 23:00",
    output_path="aorc_precip.nc",
    target_crs="EPSG:5070",
    resolution=2000.0
)
```

---

### `get_available_years()`

Query available years in AORC dataset.

```python
PrecipAorc.get_available_years(region="CONUS")
```

**Returns**: `list[int]` - Available years

**Parameters**:
- `region`: "CONUS" or "Alaska"

**Example**:
```python
years = PrecipAorc.get_available_years("CONUS")
# Returns [1979, 1980, ..., 2024, 2025]
```

---

### `check_data_coverage()`

Verify spatial and temporal coverage for a request.

```python
PrecipAorc.check_data_coverage(
    bounds,              # tuple (west, south, east, north)
    start_date,          # str or datetime
    end_date             # str or datetime
)
```

**Returns**: `dict` with coverage information

**Example**:
```python
coverage = PrecipAorc.check_data_coverage(
    bounds=(-77.5, 38.5, -76.5, 39.5),
    start_date="2015-05-01",
    end_date="2015-05-15"
)
# Returns: {'spatial': True, 'temporal': True, 'missing_days': []}
```

---

## Spatial Processing Methods

### `spatial_average()`

Calculate areal average over watershed.

```python
PrecipAorc.spatial_average(
    data,                # xarray Dataset
    watershed            # str (HUC) or Path (shapefile)
)
```

**Returns**: `pandas.Series` - Time series of average precipitation

**Example**:
```python
avg_precip = PrecipAorc.spatial_average(data, "02070010")
# Returns Series with datetime index, values in mm/hr
print(f"Total: {avg_precip.sum():.2f} mm")
```

---

### `extract_by_watershed()`

Extract AORC data for specific watershed (clips grid).

```python
PrecipAorc.extract_by_watershed(
    data,                # xarray Dataset
    watershed            # str (HUC) or Path (shapefile)
)
```

**Returns**: `xarray.Dataset` - Clipped to watershed bounds

**Example**:
```python
clipped = PrecipAorc.extract_by_watershed(data, "02070010")
# Returns Dataset with same structure but smaller spatial extent
```

---

### `resample_grid()`

Aggregate AORC grid cells to coarser resolution.

```python
PrecipAorc.resample_grid(
    data,                # xarray Dataset
    factor=2             # int - resampling factor
)
```

**Returns**: `xarray.Dataset` - Resampled grid

**Example**:
```python
coarse = PrecipAorc.resample_grid(data, factor=4)
# 800m → 3200m resolution
```

---

## Temporal Processing Methods

### `aggregate_to_interval()`

Aggregate to HEC-RAS/HMS intervals.

```python
PrecipAorc.aggregate_to_interval(
    timeseries,          # pandas Series
    interval="1HR"       # str
)
```

**Returns**: `pandas.Series` - Aggregated time series

**Supported Intervals**:
- `"15MIN"` - 15 minutes
- `"30MIN"` - 30 minutes
- `"1HR"` - 1 hour
- `"6HR"` - 6 hours
- `"1DAY"` - 1 day

**Example**:
```python
hourly = PrecipAorc.aggregate_to_interval(avg_precip, "1HR")
daily = PrecipAorc.aggregate_to_interval(avg_precip, "1DAY")
```

---

### `extract_storm_events()`

Identify and extract individual storm events.

```python
PrecipAorc.extract_storm_events(
    timeseries,          # pandas Series
    inter_event_hours=8.0,  # float
    min_depth_mm=20.0    # float
)
```

**Returns**: `list[dict]` - Storm events with metadata

**Example**:
```python
storms = PrecipAorc.extract_storm_events(
    avg_precip,
    inter_event_hours=8.0,
    min_depth_mm=20.0
)
# Returns list of dicts with keys: start, end, total_mm, peak_mm_hr
```

---

### `calculate_rolling_totals()`

Compute N-hour rolling precipitation totals.

```python
PrecipAorc.calculate_rolling_totals(
    timeseries,          # pandas Series
    window_hours=24      # int
)
```

**Returns**: `pandas.Series` - Rolling totals

**Example**:
```python
rolling_24hr = PrecipAorc.calculate_rolling_totals(hourly, 24)
max_24hr = rolling_24hr.max()
print(f"Max 24-hr total: {max_24hr:.2f} mm")
```

---

## Storm Catalog Methods

### `get_storm_catalog()`

Generate catalog of all significant precipitation events.

```python
PrecipAorc.get_storm_catalog(
    bounds,              # tuple (west, south, east, north)
    year,                # int
    inter_event_hours=8.0,  # float
    min_depth_inches=0.75,  # float
    buffer_hours=48      # int
)
```

**Returns**: `pandas.DataFrame` - Storm catalog

**DataFrame Columns**:
- `storm_id`: Storm identifier (1, 2, 3, ...)
- `start_time`: Storm start timestamp
- `end_time`: Storm end timestamp
- `sim_start`: Simulation start (with buffer)
- `sim_end`: Simulation end
- `total_depth_in`: Total precipitation (inches)
- `peak_intensity_in_hr`: Peak intensity (in/hr)
- `duration_hours`: Storm duration
- `rank`: Rank by total depth (1 = largest)

**Example**:
```python
catalog = PrecipAorc.get_storm_catalog(
    bounds=(-77.5, 38.5, -76.5, 39.5),
    year=2020,
    inter_event_hours=8.0,
    min_depth_inches=0.75,
    buffer_hours=48
)
print(f"Found {len(catalog)} storms in 2020")
```

---

### `create_storm_plans()`

Create HEC-RAS plans for all storms in catalog.

```python
PrecipAorc.create_storm_plans(
    storm_catalog,       # pandas DataFrame
    bounds,              # tuple (west, south, east, north)
    template_plan,       # str - plan number
    precip_folder="Precipitation",  # str or Path
    ras_object=None,     # RasPrj instance or None (use global ras)
    download_data=True   # bool
)
```

**Returns**: `pandas.DataFrame` - Results with plan numbers and status

**Example**:
```python
results = PrecipAorc.create_storm_plans(
    storm_catalog=catalog,
    bounds=bounds,
    template_plan="06",
    precip_folder="Precipitation",
    ras_object=ras,
    download_data=True
)
# Returns DataFrame with columns: storm_id, plan_number, status
```

---

## Export Methods

### `export_to_dss()`

Export time series to HEC-DSS format.

```python
PrecipAorc.export_to_dss(
    timeseries,          # pandas Series
    dss_file,            # str or Path
    pathname             # str - DSS pathname
)
```

**Requires**: `pydsstools` (lazy-loaded)

**Example**:
```python
PrecipAorc.export_to_dss(
    hourly,
    dss_file="precipitation.dss",
    pathname="/PROJECT/PRECIP/AORC//1HOUR/OBS/"
)
```

---

### `export_to_netcdf()`

Export to NetCDF format.

```python
PrecipAorc.export_to_netcdf(
    data,                # xarray Dataset
    output_path          # str or Path
)
```

**Example**:
```python
PrecipAorc.export_to_netcdf(data, "aorc_output.nc")
```

---

## Data Format Details

### xarray Dataset Structure

AORC data is returned as xarray Dataset:

```python
<xarray.Dataset>
Dimensions:  (time: 360, y: 50, x: 50)
Coordinates:
  * time     (time) datetime64[ns] 2015-05-01T00:00:00 ... 2015-05-15T23:00:00
  * y        (y) float64 ...
  * x        (x) float64 ...
Data variables:
    APCP_surface (time, y, x) float32 ...
Attributes:
    crs: EPSG:5070
    resolution: 2000.0
    units: mm/hr
```

**Key Variables**:
- `APCP_surface`: Precipitation rate (mm/hr)
- `time`: Hourly timestamps
- `x`, `y`: Spatial coordinates

---

## Performance Considerations

### AORC Data Retrieval
- **Speed**: ~1-5 minutes per year of hourly data (depends on watershed size)
- **Storage**: ~10-50 MB per year (hourly, single watershed)
- **Caching**: Local cache recommended for repeated analyses

### Spatial Operations
- Spatial averaging: ~1-10 seconds for typical watersheds
- Grid resampling: ~5-30 seconds depending on resolution

### Temporal Aggregation
- Aggregation to hourly/6-hour: < 1 second
- Storm event extraction: ~1-5 seconds per year

---

## Error Handling

All methods raise informative exceptions:

```python
try:
    data = PrecipAorc.retrieve_aorc_data(
        watershed="invalid_huc",
        start_date="2015-05-01",
        end_date="2015-05-15"
    )
except ValueError as e:
    print(f"Invalid HUC code: {e}")
except Exception as e:
    print(f"Error retrieving AORC data: {e}")
```

Common errors:
- `ValueError`: Invalid HUC code, invalid date range
- `FileNotFoundError`: Shapefile not found
- `ConnectionError`: AORC server unavailable
- `RuntimeError`: Data processing error

---

## See Also

- **Main Skill**: [../SKILL.md](../SKILL.md)
- **Atlas 14 API**: [atlas14.md](atlas14.md)
- **Precip Module**: `ras_commander/precip/CLAUDE.md`
- **Example Notebook**: `examples/24_aorc_precipitation.ipynb`
