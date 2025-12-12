# AORC API Reference

Complete API reference for AORC (Analysis of Record for Calibration) precipitation data integration.

## Overview

AORC provides historical precipitation data from 1979 to present with ~4 km spatial resolution and hourly temporal resolution. This data is ideal for model calibration and validation with observed flow/stage data.

## PrecipAorc Class

All methods are static and use `@log_call` decorators for execution tracking.

### Data Retrieval

#### retrieve_aorc_data()

Download AORC precipitation time series for a watershed.

**Signature**:
```python
PrecipAorc.retrieve_aorc_data(
    watershed: Union[str, Path],
    start_date: str,
    end_date: str,
    cache_dir: Optional[Path] = None
) -> xr.Dataset
```

**Parameters**:
- `watershed`: HUC code (string) or shapefile path (Path object)
- `start_date`: ISO format "YYYY-MM-DD"
- `end_date`: ISO format "YYYY-MM-DD"
- `cache_dir`: Optional local cache directory (default: `./aorc_cache/`)

**Returns**: xarray Dataset with precipitation time series

**Example**:
```python
from ras_commander.precip import PrecipAorc
from pathlib import Path

# Option 1: HUC-8 code
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",  # Upper James River
    start_date="2015-06-01",
    end_date="2015-06-30"
)

# Option 2: Custom shapefile
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=Path("watershed_boundary.shp"),
    start_date="2015-06-01",
    end_date="2015-06-30",
    cache_dir=Path("my_cache")
)
```

**Performance**: ~1-5 minutes per year (depends on watershed size)

#### get_available_years()

Query available data years at a location.

**Signature**:
```python
PrecipAorc.get_available_years(
    lat: float,
    lon: float
) -> List[int]
```

**Parameters**:
- `lat`: Latitude (decimal degrees)
- `lon`: Longitude (decimal degrees, negative for Western Hemisphere)

**Returns**: List of years with available data

**Example**:
```python
# Check availability for Richmond, VA
years = PrecipAorc.get_available_years(
    lat=37.5407,
    lon=-77.4360
)
print(f"Available years: {min(years)} to {max(years)}")
# Output: Available years: 1979 to 2024
```

#### check_data_coverage()

Verify spatial and temporal data coverage.

**Signature**:
```python
PrecipAorc.check_data_coverage(
    watershed: Union[str, Path],
    start_date: str,
    end_date: str
) -> Dict[str, Any]
```

**Returns**: Dictionary with coverage statistics:
- `spatial_coverage_pct`: Percentage of watershed covered by AORC grid
- `temporal_coverage_pct`: Percentage of requested period with data
- `missing_dates`: List of dates with missing data
- `grid_cells`: Number of AORC cells intersecting watershed

**Example**:
```python
coverage = PrecipAorc.check_data_coverage(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2015-12-31"
)
print(f"Spatial coverage: {coverage['spatial_coverage_pct']:.1f}%")
print(f"Temporal coverage: {coverage['temporal_coverage_pct']:.1f}%")
```

### Spatial Processing

#### spatial_average()

Calculate areal average precipitation over watershed.

**Signature**:
```python
PrecipAorc.spatial_average(
    aorc_data: xr.Dataset,
    watershed: Union[str, Path],
    method: str = "area_weighted"
) -> pd.DataFrame
```

**Parameters**:
- `aorc_data`: AORC dataset from `retrieve_aorc_data()`
- `watershed`: HUC code or shapefile (must match retrieval)
- `method`: Averaging method ("area_weighted", "simple", "thiessen")

**Returns**: DataFrame with columns `['datetime', 'precipitation_mm']`

**Example**:
```python
# Retrieve data
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-06-01",
    end_date="2015-06-30"
)

# Calculate spatial average
avg_precip = PrecipAorc.spatial_average(
    aorc_data,
    watershed="02070010",
    method="area_weighted"
)

# Check results
print(avg_precip.head())
#          datetime  precipitation_mm
# 0  2015-06-01 00:00:00          0.5
# 1  2015-06-01 01:00:00          1.2
```

**Methods**:
- `area_weighted`: Weight by grid cell area intersection (recommended)
- `simple`: Unweighted average of all cells
- `thiessen`: Thiessen polygon interpolation

#### extract_by_watershed()

Extract AORC data for specific watershed without averaging.

**Signature**:
```python
PrecipAorc.extract_by_watershed(
    aorc_data: xr.Dataset,
    watershed: Union[str, Path]
) -> xr.Dataset
```

**Returns**: Subset of AORC data covering watershed (gridded, not averaged)

**Use case**: When you need spatially distributed precipitation for HMS or 2D RAS models

#### resample_grid()

Aggregate AORC grid cells to coarser resolution.

**Signature**:
```python
PrecipAorc.resample_grid(
    aorc_data: xr.Dataset,
    target_resolution_km: float
) -> xr.Dataset
```

**Example**:
```python
# Aggregate ~4 km AORC to ~10 km resolution
coarse_data = PrecipAorc.resample_grid(
    aorc_data,
    target_resolution_km=10.0
)
```

### Temporal Processing

#### aggregate_to_interval()

Aggregate to HEC-RAS/HMS timesteps.

**Signature**:
```python
PrecipAorc.aggregate_to_interval(
    precip_df: pd.DataFrame,
    interval: str
) -> pd.DataFrame
```

**Parameters**:
- `precip_df`: DataFrame from `spatial_average()`
- `interval`: HEC-RAS interval code ("15MIN", "1HOUR", "6HOUR", "1DAY")

**Returns**: DataFrame with aggregated precipitation

**Example**:
```python
# Get hourly spatial average
avg_precip = PrecipAorc.spatial_average(aorc_data, watershed="02070010")

# Aggregate to 1-hour intervals (for HEC-RAS)
hourly = PrecipAorc.aggregate_to_interval(avg_precip, interval="1HOUR")

# Aggregate to 6-hour intervals (for coarse models)
six_hour = PrecipAorc.aggregate_to_interval(avg_precip, interval="6HOUR")

# Aggregate to daily (for long-term simulation)
daily = PrecipAorc.aggregate_to_interval(avg_precip, interval="1DAY")
```

**Interval Codes**:
- `15MIN`: 15-minute (sub-hourly aggregation)
- `1HOUR`: 1-hour (typical for urban models)
- `6HOUR`: 6-hour (coarse timestep)
- `1DAY`: Daily total

#### extract_storm_events()

Identify and extract individual storm events from time series.

**Signature**:
```python
PrecipAorc.extract_storm_events(
    precip_df: pd.DataFrame,
    min_interevent_hours: int = 6,
    min_total_mm: float = 5.0
) -> List[pd.DataFrame]
```

**Parameters**:
- `precip_df`: DataFrame from `spatial_average()`
- `min_interevent_hours`: Minimum dry period between events
- `min_total_mm`: Minimum total precipitation to qualify as event

**Returns**: List of DataFrames, one per storm event

**Example**:
```python
# Extract individual storms
storms = PrecipAorc.extract_storm_events(
    avg_precip,
    min_interevent_hours=6,
    min_total_mm=10.0  # At least 10 mm total
)

print(f"Found {len(storms)} storm events")

# Analyze largest storm
largest = max(storms, key=lambda df: df['precipitation_mm'].sum())
print(f"Largest storm: {largest['precipitation_mm'].sum():.1f} mm")
print(f"Duration: {largest['datetime'].max() - largest['datetime'].min()}")
```

#### calculate_rolling_totals()

Compute N-hour rolling precipitation totals.

**Signature**:
```python
PrecipAorc.calculate_rolling_totals(
    precip_df: pd.DataFrame,
    window_hours: int
) -> pd.DataFrame
```

**Parameters**:
- `precip_df`: DataFrame from `spatial_average()`
- `window_hours`: Rolling window size in hours

**Returns**: DataFrame with additional column `precipitation_Nhour_mm`

**Example**:
```python
# Calculate 24-hour rolling totals
rolling_24hr = PrecipAorc.calculate_rolling_totals(
    avg_precip,
    window_hours=24
)

# Find maximum 24-hour precipitation
max_24hr = rolling_24hr['precipitation_24hour_mm'].max()
print(f"Maximum 24-hour precipitation: {max_24hr:.1f} mm")
```

### Output Formats

#### export_to_dss()

Export to HEC-DSS format for HEC-RAS/HMS.

**Signature**:
```python
PrecipAorc.export_to_dss(
    precip_df: pd.DataFrame,
    dss_file: Union[str, Path],
    pathname: str
) -> None
```

**Parameters**:
- `precip_df`: DataFrame from `aggregate_to_interval()`
- `dss_file`: Output DSS file path
- `pathname`: DSS pathname (A/B/C/D/E/F format)

**DSS Pathname Format**:
- A: Project name
- B: Location (e.g., "PRECIP")
- C: Parameter (e.g., "PRECIPITATION-INCREMENTAL")
- D: Start date (auto-filled)
- E: Interval (e.g., "1HOUR")
- F: Version (e.g., "OBS" for observed, "SYN" for synthetic)

**Example**:
```python
# Export hourly precipitation to DSS
PrecipAorc.export_to_dss(
    hourly_precip,
    dss_file="precipitation.dss",
    pathname="/UPPER_JAMES/PRECIP/AORC//1HOUR/OBS/"
)
```

**Requires**: `pip install pydsstools` (lazy-loaded)

#### export_to_csv()

Export to CSV for HEC-HMS or analysis.

**Example**:
```python
# Simple CSV export
hourly_precip.to_csv("aorc_precipitation.csv", index=False)
```

#### export_to_netcdf()

Save processed data as NetCDF for further analysis.

**Signature**:
```python
PrecipAorc.export_to_netcdf(
    aorc_data: xr.Dataset,
    output_file: Union[str, Path]
) -> None
```

**Example**:
```python
# Save gridded data
PrecipAorc.export_to_netcdf(
    aorc_data,
    output_file="aorc_watershed.nc"
)
```

## Complete Workflow Example

```python
from ras_commander.precip import PrecipAorc
from pathlib import Path

# 1. Check data availability
coverage = PrecipAorc.check_data_coverage(
    watershed="02070010",
    start_date="2015-06-01",
    end_date="2015-06-30"
)
print(f"Coverage: {coverage['temporal_coverage_pct']:.1f}%")

# 2. Retrieve AORC data
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-06-01",
    end_date="2015-06-30"
)

# 3. Calculate spatial average
avg_precip = PrecipAorc.spatial_average(
    aorc_data,
    watershed="02070010",
    method="area_weighted"
)

# 4. Aggregate to HEC-RAS interval
hourly = PrecipAorc.aggregate_to_interval(
    avg_precip,
    interval="1HOUR"
)

# 5. Export to DSS
PrecipAorc.export_to_dss(
    hourly,
    dss_file="precipitation.dss",
    pathname="/PROJECT/PRECIP/AORC//1HOUR/OBS/"
)

# 6. Also export to CSV for review
hourly.to_csv("aorc_precipitation.csv", index=False)

print("AORC precipitation export complete")
```

## See Also

- Parent module: `ras_commander/precip/CLAUDE.md`
- Atlas 14 workflows: [atlas14.md](atlas14.md)
- Example notebook: `examples/24_aorc_precipitation.ipynb`
