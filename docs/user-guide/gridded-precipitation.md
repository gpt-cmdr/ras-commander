# Gridded Historic Precipitation

The AORC (Analysis of Record for Calibration) module provides access to gridded historical precipitation data for model calibration, storm reconstruction, and historical event analysis.

## Overview

AORC is a gridded historical precipitation dataset from NOAA's National Water Model retrospective forcing archive:

| Feature | Details |
|---------|---------|
| **Period** | 1979 - present (operationally updated) |
| **Spatial Resolution** | ~4 km grid (1/24 degree) |
| **Temporal Resolution** | Hourly precipitation |
| **Coverage** | Continental United States (CONUS) |
| **Source** | NOAA Office of Water Prediction |

**Use AORC for**:

- ✅ Historical storm calibration
- ✅ Long-term continuous simulation
- ✅ Storm event reconstruction
- ✅ Validation with observed flows/stages
- ✅ Climate analysis and trends

**For design storms**, see [Atlas 14 Precipitation](atlas14-precipitation.md).

## Quick Start

Basic AORC workflow for a historical storm event:

```python
from ras_commander.precip import PrecipAorc

# 1. Define watershed (HUC code or shapefile)
watershed = "02070010"  # HUC-8 code

# 2. Retrieve AORC data for storm period
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=watershed,
    start_date="2018-05-15",  # Historical storm date
    end_date="2018-05-20"
)

# 3. Calculate spatial average over watershed
avg_precip = PrecipAorc.spatial_average(aorc_data, watershed)

# 4. Aggregate to model timestep
hourly_precip = PrecipAorc.aggregate_to_interval(
    avg_precip,
    interval="1HR"
)

# 5. Export for HEC-RAS
hourly_precip.to_csv("storm_may2018.csv")
```

## Data Retrieval

### By HUC Code

Use USGS Hydrologic Unit Code for watershed definition:

```python
from ras_commander.precip import PrecipAorc

# Retrieve by HUC-8 code
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",  # Potomac River HUC-8
    start_date="2015-01-01",
    end_date="2015-12-31"
)
```

### By Custom Boundary

Use custom watershed shapefile:

```python
from pathlib import Path

# Custom watershed boundary
watershed_shp = Path("watershed_boundary.shp")

aorc_data = PrecipAorc.extract_by_watershed(
    watershed=watershed_shp,
    start_date="2015-01-01",
    end_date="2015-12-31"
)
```

### Check Data Availability

Verify AORC coverage before retrieval:

```python
# Check if data exists for period
coverage = PrecipAorc.check_data_coverage(
    watershed="02070010",
    start_date="1990-01-01",
    end_date="2023-12-31"
)

if coverage['available']:
    print(f"AORC available: {coverage['start']} to {coverage['end']}")
    print(f"Total years: {coverage['years']}")
else:
    print("AORC data not available for this period")
```

### Get Available Years

```python
# List all available AORC years
years = PrecipAorc.get_available_years()
print(f"AORC coverage: {min(years)} to {max(years)}")
```

## Spatial Processing

### Spatial Averaging

Calculate areal average precipitation over watershed:

```python
# Option 1: Average during retrieval
avg_precip = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-05-15",
    end_date="2018-05-20",
    spatial_average=True  # Returns time series only
)

# Option 2: Average after retrieval
aorc_grid = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-05-15",
    end_date="2018-05-20",
    return_grid=True  # Keep gridded format
)
avg_precip = PrecipAorc.spatial_average(aorc_grid, watershed="02070010")
```

### Grid Resampling

Aggregate AORC grid to coarser resolution:

```python
# Resample from 4 km to 10 km grid
coarse_grid = PrecipAorc.resample_grid(
    aorc_data,
    target_resolution_km=10  # Coarsen grid
)

# Useful for:
# - Faster processing of large watersheds
# - Matching HEC-RAS 2D mesh resolution
# - Reducing data volume
```

## Temporal Processing

### Aggregation to Model Timestep

Match AORC hourly data to HEC-RAS computational interval:

```python
# Aggregate to 1-hour (no change, already hourly)
hourly = PrecipAorc.aggregate_to_interval(avg_precip, interval="1HR")

# Aggregate to 6-hour
six_hour = PrecipAorc.aggregate_to_interval(avg_precip, interval="6HR")

# Aggregate to daily
daily = PrecipAorc.aggregate_to_interval(avg_precip, interval="1DAY")
```

**Supported intervals**: `1HR`, `6HR`, `1DAY`

### Storm Event Extraction

Automatically identify and extract individual storms from continuous record:

```python
# Extract storm events from multi-year record
storms = PrecipAorc.extract_storm_events(
    avg_precip,
    inter_event_hours=6,      # Minimum dry period between storms
    min_depth_inches=0.5,     # Minimum total to count as storm
    buffer_hours=6            # Hours before/after storm to include
)

# Returns list of storm DataFrames
for i, storm in enumerate(storms):
    storm_start = storm['datetime'].min()
    storm_end = storm['datetime'].max()
    storm_total = storm['precip'].sum()
    storm_peak = storm['precip'].max()

    print(f"Storm {i}: {storm_start} to {storm_end}")
    print(f"  Total: {storm_total:.2f} inches")
    print(f"  Peak: {storm_peak:.2f} in/hr")
```

### Rolling Precipitation Totals

Calculate N-hour rolling accumulations:

```python
# Calculate 24-hour rolling totals
rolling_24hr = PrecipAorc.calculate_rolling_totals(
    hourly_precip,
    window_hours=24
)

# Find maximum 24-hour precipitation in period
max_24hr = rolling_24hr.max()
max_date = rolling_24hr.idxmax()

print(f"Maximum 24-hr total: {max_24hr:.2f} inches")
print(f"Occurred on: {max_date}")

# Calculate for multiple durations
for duration in [6, 12, 24, 48]:
    rolling = PrecipAorc.calculate_rolling_totals(hourly_precip, window_hours=duration)
    print(f"Max {duration}-hr: {rolling.max():.2f} inches")
```

## Integration with HEC-RAS

### Spatially Uniform Precipitation

For models with uniform rainfall over entire domain:

```python
from ras_commander.precip import PrecipAorc
from ras_commander.usgs import RasUsgsFileIo

# 1. Retrieve and average AORC data
avg_precip = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-05-15",
    end_date="2018-05-20",
    spatial_average=True
)

# 2. Aggregate to HEC-RAS interval
hourly = PrecipAorc.aggregate_to_interval(avg_precip, interval="1HR")

# 3. Export to DSS
RasUsgsFileIo.export_to_dss(
    hourly,
    dss_file="aorc_may2018.dss",
    pathname="//BASIN/PRECIP/AORC//1HOUR/OBS/"
)

# 4. Update unsteady file to reference DSS
from ras_commander import RasUnsteady
# ... (update boundary configuration in .u## file)
```

### Gridded Precipitation (Rain-on-Grid)

For 2D models with spatially distributed rainfall:

```python
# 1. Retrieve AORC in gridded format
aorc_grid = PrecipAorc.retrieve_aorc_data(
    watershed=watershed_boundary,
    start_date="2018-05-15",
    end_date="2018-05-20",
    return_grid=True  # Keep spatial structure
)

# 2. Resample to HEC-RAS mesh resolution
ras_grid = PrecipAorc.resample_grid(
    aorc_grid,
    target_resolution_km=2.0  # Match 2D mesh cell size
)

# 3. Export to GDAL Raster format (HEC-RAS compatible)
PrecipAorc.export_to_gdal_raster(
    ras_grid,
    output_folder="C:/Projects/MyModel/precipitation",
    format="GeoTIFF"  # or "HFA" for ERDAS Imagine
)

# 4. Configure unsteady file for gridded precipitation
from ras_commander import RasUnsteady

RasUnsteady.set_gridded_precipitation(
    unsteady_file="MyModel.u01",
    precip_folder="precipitation",
    start_datetime="2018-05-15 00:00"
)
```

## Model Calibration Workflow

Use AORC for calibrating HEC-RAS models to historical events:

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.precip import PrecipAorc
from ras_commander.usgs import RasUsgsCore

# 1. Identify historical event from USGS gauge record
observed_flow = RasUsgsCore.retrieve_flow_data(
    site_no="01646500",
    start_date="2018-05-01",
    end_date="2018-06-01"
)
# ... identify peak flow date

# 2. Retrieve AORC for event period
event_precip = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-05-15",
    end_date="2018-05-20",
    spatial_average=True
)

# 3. Export to HEC-RAS
# ... (DSS export as shown above)

# 4. Run HEC-RAS with historical precipitation
init_ras_project("C:/Projects/Potomac", "6.6")
RasCmdr.compute_plan("01", num_cores=4)

# 5. Compare modeled vs observed (validation)
from ras_commander import HdfResultsXsec
modeled_flow = HdfResultsXsec.get_xsec_timeseries("01", ...)

# 6. Calculate metrics
from ras_commander.usgs import metrics
nse = metrics.nash_sutcliffe_efficiency(observed_flow, modeled_flow)
print(f"Calibration NSE: {nse:.3f}")

# 7. Iterate: adjust roughness, re-run, validate
```

## Storm Catalog Generation

Create catalog of all significant storms in multi-year period:

```python
# Retrieve long-term AORC record
long_term = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2023-12-31",
    spatial_average=True
)

# Extract all storms meeting criteria
storm_catalog = PrecipAorc.extract_storm_events(
    long_term,
    inter_event_hours=6,       # 6-hour dry period separates storms
    min_depth_inches=1.0,      # Minimum 1" total
    buffer_hours=12            # Include 12hr before/after
)

print(f"Found {len(storm_catalog)} storms in 9-year period")

# Summarize each storm
import pandas as pd
summary = []
for i, storm in enumerate(storm_catalog):
    summary.append({
        'storm_id': i,
        'start': storm['datetime'].min(),
        'end': storm['datetime'].max(),
        'duration_hr': len(storm),
        'total_in': storm['precip'].sum(),
        'peak_in_hr': storm['precip'].max()
    })

catalog_df = pd.DataFrame(summary)
catalog_df.to_csv("storm_catalog.csv", index=False)
```

## Performance Optimization

### Temporal Subsetting

Minimize data volume by downloading only required periods:

```python
# Bad: Download entire year when only need one month
aorc_full = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-01-01",
    end_date="2018-12-31"  # 365 days
)

# Good: Download only event period
aorc_event = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2018-05-15",
    end_date="2018-05-20"  # 5 days - much faster
)
```

### Spatial Buffering

Reduce download area to just what's needed:

```python
# Retrieve with minimal buffer around watershed
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=watershed_boundary,
    start_date="2018-05-15",
    end_date="2018-05-20",
    buffer_km=5.0  # Small buffer (faster download)
)
```

### Local Caching

Cache processed AORC data to avoid re-downloading:

```python
from pathlib import Path

# Define cache directory
cache_dir = Path("C:/AORC_Cache")
cache_dir.mkdir(exist_ok=True)

# Retrieve with caching
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2015-12-31",
    cache_dir=cache_dir  # Save to cache
)

# Subsequent calls use cached data (much faster)
aorc_same = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2015-12-31",
    cache_dir=cache_dir  # Reads from cache
)
```

## Export Formats

### CSV Export

Simple tabular format for spreadsheet analysis:

```python
# Export to CSV
hourly_precip.to_csv("aorc_precipitation.csv", index=True)

# CSV format:
# datetime,precip_inches
# 2018-05-15 00:00:00,0.05
# 2018-05-15 01:00:00,0.12
# ...
```

### DSS Export

HEC-DSS format for HEC-RAS and HEC-HMS:

```python
from ras_commander.usgs import RasUsgsFileIo

# Export to DSS (requires pydsstools)
RasUsgsFileIo.export_to_dss(
    hourly_precip,
    dss_file="aorc_precip.dss",
    pathname="//BASIN/PRECIP/AORC//1HOUR/OBS/"
)
```

### NetCDF Export

Keep gridded structure for further analysis:

```python
# Export gridded data to NetCDF
PrecipAorc.export_to_netcdf(
    aorc_grid,
    output_file="aorc_grid.nc"
)
```

## Advanced Workflows

### Multi-Year Continuous Simulation

Run HEC-RAS with continuous precipitation record:

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.precip import PrecipAorc

# 1. Retrieve multi-year AORC data
continuous_precip = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2020-12-31",  # 6 years
    spatial_average=True,
    cache_dir="C:/AORC_Cache"  # Cache for reuse
)

# 2. Aggregate to daily (for long-term simulation)
daily_precip = PrecipAorc.aggregate_to_interval(
    continuous_precip,
    interval="1DAY"
)

# 3. Export to DSS
from ras_commander.usgs import RasUsgsFileIo
RasUsgsFileIo.export_to_dss(
    daily_precip,
    dss_file="aorc_2015_2020.dss",
    pathname="//BASIN/PRECIP/AORC//1DAY/OBS/"
)

# 4. Run continuous simulation
init_ras_project("C:/Projects/Continuous", "6.6")
RasCmdr.compute_plan("01", num_cores=8)  # Long run
```

### Storm Comparison Analysis

Compare precipitation patterns across multiple historical storms:

```python
# Define storm periods
storms = {
    "May 2018": ("2018-05-15", "2018-05-20"),
    "Sep 2019": ("2019-09-12", "2019-09-18"),
    "Jul 2020": ("2020-07-08", "2020-07-12")
}

storm_data = {}

for name, (start, end) in storms.items():
    # Retrieve AORC for each storm
    precip = PrecipAorc.retrieve_aorc_data(
        watershed="02070010",
        start_date=start,
        end_date=end,
        spatial_average=True
    )

    storm_data[name] = {
        'total': precip['precip'].sum(),
        'peak': precip['precip'].max(),
        'duration_hr': len(precip)
    }

# Compare storms
import pandas as pd
comparison = pd.DataFrame(storm_data).T
print(comparison)
```

### Climate Trend Analysis

Analyze precipitation trends over decades:

```python
# Retrieve 20+ years of AORC data
long_record = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2000-01-01",
    end_date="2023-12-31",
    spatial_average=True,
    cache_dir="C:/AORC_Cache"
)

# Aggregate to annual totals
annual_totals = long_record.groupby(long_record['datetime'].dt.year)['precip'].sum()

# Analyze trend
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
plt.plot(annual_totals.index, annual_totals.values, marker='o')
plt.xlabel('Year')
plt.ylabel('Annual Precipitation (inches)')
plt.title('Annual Precipitation Trend (2000-2023)')
plt.grid(True)
plt.savefig('precip_trend.png')
```

## Data Quality Considerations

### AORC Characteristics

**Strengths**:
- ✅ Continuous coverage (no gaps)
- ✅ Spatially consistent
- ✅ Hourly resolution
- ✅ Long period of record (1979-present)

**Limitations**:
- ⚠ ~4 km resolution (may miss localized convective storms)
- ⚠ Model-derived (not direct observations)
- ⚠ Uncertainty in complex terrain
- ⚠ May differ from rain gauge measurements

### Validation with Rain Gauges

Compare AORC to observed rain gauge data:

```python
# Retrieve AORC for gauge location
aorc_point = PrecipAorc.extract_by_point(
    latitude=38.9,
    longitude=-77.0,
    start_date="2018-05-15",
    end_date="2018-05-20"
)

# Compare to rain gauge observations
# (gauge_data from local source)
import matplotlib.pyplot as plt

plt.figure(figsize=(12, 6))
plt.plot(gauge_data['datetime'], gauge_data['precip'], label='Rain Gauge', marker='o')
plt.plot(aorc_point['datetime'], aorc_point['precip'], label='AORC', alpha=0.7)
plt.xlabel('Date')
plt.ylabel('Precipitation (inches/hour)')
plt.title('AORC vs Rain Gauge Comparison')
plt.legend()
plt.grid(True)
plt.show()
```

## Dependencies

**Required**:
```bash
pip install xarray  # For AORC NetCDF data handling
```

**Optional (for advanced features)**:
```bash
pip install rasterio    # For gridded processing
pip install geopandas   # For custom watershed boundaries
pip install pydsstools  # For DSS export
```

The module uses **lazy loading** - methods check for dependencies only when needed and provide installation instructions if missing.

## Data Access

AORC data is accessed from NOAA's cloud storage (AWS S3):

- **Storage**: Zarr format on AWS S3
- **Access**: No authentication required (public dataset)
- **Speed**: ~1-5 minutes per year of data (depends on watershed size and network)
- **Volume**: ~10-50 MB per year (hourly, single watershed)

## Example Notebooks

Comprehensive AORC workflow demonstrations:

- [AORC Precipitation](../notebooks/900_aorc_precipitation.ipynb) - Basic retrieval and processing
- [AORC Storm Catalog](../notebooks/901_aorc_precipitation_catalog.ipynb) - Automated storm extraction

## Common Workflows

### Historical Event Reconstruction

Reconstruct a specific historical flood event:

1. **Identify event date** from USGS flow data or news reports
2. **Retrieve AORC precipitation** for event period
3. **Process and export** to HEC-RAS format
4. **Run model** with historical precipitation
5. **Validate results** against observed flows/stages
6. **Calibrate roughness** if needed

### Continuous Simulation

Run HEC-RAS for extended periods (months to years):

1. **Retrieve multi-year AORC** record
2. **Aggregate to appropriate interval** (daily for long periods)
3. **Export to DSS**
4. **Configure HEC-RAS** for continuous run
5. **Execute with sufficient cores** (long runtime)
6. **Extract statistics** (peak events, exceedance curves)

### Climate Analysis

Analyze precipitation patterns and trends:

1. **Retrieve decades of AORC data** (1979-present)
2. **Extract storm events** from continuous record
3. **Analyze storm characteristics** (frequency, intensity, duration)
4. **Identify trends** over time
5. **Compare to design storm assumptions**

## See Also

- [Atlas 14 Precipitation](atlas14-precipitation.md) - Design storm generation for AEP analysis
- [Boundary Conditions](boundary-conditions.md) - General boundary workflows
- [DSS Operations](dss-operations.md) - Working with DSS files
- [USGS Gauge Data](usgs-gauge-data.md) - Flow/stage data for validation
