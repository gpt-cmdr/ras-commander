# Gridded Historic Precipitation

The precipitation module provides tools for integrating gridded precipitation data into HEC-RAS and HEC-HMS models. It supports both **AORC** (Analysis of Record for Calibration) historical data and **NOAA Atlas 14** design storm generation.

## Overview

Two complementary data sources for precipitation modeling:

| Data Source | Use Case | Coverage | Resolution |
|-------------|----------|----------|------------|
| **AORC** | Historical calibration, storm reconstruction | CONUS, 1979-present | 4 km grid, hourly |
| **Atlas 14** | Design storm generation, frequency analysis | CONUS + territories | Point values, API |

## AORC: Historical Precipitation

AORC (Analysis of Record for Calibration) provides gridded historical precipitation data from NOAA's National Water Model retrospective forcing archive.

### Key Features

- **Period**: 1979 - present (operationally updated)
- **Resolution**: ~4 km grid (1/24 degree), hourly
- **Coverage**: Continental United States
- **Source**: NOAA National Water Model forcing data

### Basic Workflow

```python
from ras_commander.precip import PrecipAorc

# 1. Define watershed boundary (HUC code or shapefile)
watershed = "02070010"  # HUC-8 code

# 2. Retrieve AORC data
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=watershed,
    start_date="2015-06-01",
    end_date="2015-08-31"
)

# 3. Calculate spatial average over watershed
avg_precip = PrecipAorc.spatial_average(aorc_data, watershed)

# 4. Aggregate to model timestep
hourly_precip = PrecipAorc.aggregate_to_interval(
    avg_precip,
    interval="1HR"  # Options: 1HR, 6HR, 1DAY
)

# 5. Export to HEC-RAS/HMS
hourly_precip.to_csv("aorc_precipitation.csv")
```

### Spatial Processing

**Extract by custom polygon**:
```python
from pathlib import Path

# Use custom watershed boundary shapefile
watershed_shp = Path("watershed_boundary.shp")
aorc_data = PrecipAorc.extract_by_watershed(watershed_shp)
```

**Resample grid resolution**:
```python
# Aggregate AORC cells to coarser resolution
coarse_grid = PrecipAorc.resample_grid(
    aorc_data,
    target_resolution_km=10  # From 4 km to 10 km
)
```

### Storm Event Extraction

Identify and extract individual storm events from historical data:

```python
# Extract storm events automatically
storms = PrecipAorc.extract_storm_events(
    avg_precip,
    inter_event_hours=6,      # Minimum dry period between storms
    min_depth_inches=0.5      # Minimum storm total to include
)

# Returns list of storm DataFrames
for i, storm in enumerate(storms):
    print(f"Storm {i}: {storm['datetime'].min()} to {storm['datetime'].max()}")
    print(f"  Total: {storm['precip'].sum():.2f} inches")
```

### Rolling Precipitation Totals

Calculate N-hour rolling totals for intensity analysis:

```python
# Calculate 24-hour rolling totals
rolling_24hr = PrecipAorc.calculate_rolling_totals(
    hourly_precip,
    window_hours=24
)

# Find maximum 24-hour precipitation
max_24hr = rolling_24hr.max()
print(f"Maximum 24-hr total: {max_24hr:.2f} inches")
```

### Export to DSS

Export for use in HEC-RAS or HEC-HMS:

```python
# Export to DSS format (requires pydsstools)
from ras_commander.usgs import RasUsgsFileIo

RasUsgsFileIo.export_to_dss(
    hourly_precip,
    dss_file="precipitation.dss",
    pathname="/BASIN/PRECIP/AORC//1HOUR/OBS/"
)
```

## NOAA Atlas 14: Design Storms

Atlas 14 provides official NOAA precipitation frequency estimates for design storm generation.

### Quick Start

```python
from ras_commander.precip import StormGenerator

# 1. Query Atlas 14 for location and AEP
precip_depth = StormGenerator.get_precipitation_frequency(
    location=(38.9072, -77.0369),  # Washington, DC
    duration_hours=24,
    aep_percent=1.0  # 1% = 100-year event
)

print(f"24-hr, 1% AEP: {precip_depth} inches")

# 2. Generate temporal distribution
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip_depth,
    duration_hours=24,
    distribution="SCS_Type_II",  # Standard for most of US
    interval_minutes=15
)

# 3. Export for HEC-RAS
hyetograph.to_csv("design_storm_100yr.csv")
```

### AEP Events

Standard Annual Exceedance Probability (AEP) events:

| AEP | Return Period | Typical Use |
|-----|---------------|-------------|
| 50% | 2-year | Frequent events, erosion studies |
| 20% | 5-year | Minor flooding |
| 10% | 10-year | Regulatory (some jurisdictions) |
| 4% | 25-year | Floodplain management |
| 2% | 50-year | Infrastructure design |
| 1% | 100-year | Regulatory (FEMA) |
| 0.5% | 200-year | Critical infrastructure |
| 0.2% | 500-year | High-hazard dams |

```python
# Generate suite of AEP events
aep_events = [50, 20, 10, 4, 2, 1, 0.5, 0.2]

for aep in aep_events:
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=24,
        aep_percent=aep
    )

    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    output_file = f"storm_{aep}pct_AEP.csv"
    hyetograph.to_csv(output_file)
```

### Temporal Distributions

Different regions use different temporal patterns:

```python
# SCS Type II (most of US)
hyeto_type2 = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_II"
)

# SCS Type IA (Pacific maritime)
hyeto_type1a = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_IA"
)

# SCS Type III (Gulf Coast, Florida)
hyeto_type3 = StormGenerator.generate_design_storm(
    total_precip=8.5,
    duration_hours=24,
    distribution="SCS_Type_III"
)
```

**Distribution Selection**:

- **Type II**: Default for most of US (except coasts)
- **Type IA**: Pacific Northwest, coastal California
- **Type III**: Gulf of Mexico coast, Florida peninsula

### Areal Reduction Factors

For large watersheds, apply areal reduction to point precipitation:

```python
# Point precipitation from Atlas 14
point_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# Apply ARF for 250 sq mi watershed
reduced_precip = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=250,
    duration_hours=24
)

# Generate design storm with reduced depth
hyetograph = StormGenerator.generate_design_storm(
    total_precip=reduced_precip,
    duration_hours=24,
    distribution="SCS_Type_II"
)
```

**ARF Typical Values** (24-hour duration):

| Watershed Area | ARF Factor |
|----------------|------------|
| < 10 sq mi | ~1.00 |
| 50 sq mi | ~0.97 |
| 100 sq mi | ~0.95 |
| 500 sq mi | ~0.90 |
| 1000 sq mi | ~0.85 |

### Multiple Durations

Generate storms for different durations:

```python
# Standard durations for frequency analysis
durations = [6, 12, 24, 48]  # hours

for duration in durations:
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=duration,
        aep_percent=1.0
    )

    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=duration,
        distribution="SCS_Type_II"
    )

    output = f"storm_100yr_{duration}hr.csv"
    hyetograph.to_csv(output)
```

## Integration with HEC-RAS

### Gridded Precipitation (Rain-on-Grid)

For 2D models with rain-on-grid:

```python
# Retrieve AORC data (keeps gridded format)
aorc_grid = PrecipAorc.retrieve_aorc_data(
    watershed=watershed_boundary,
    start_date="2023-06-01",
    end_date="2023-06-05",
    return_grid=True  # Don't spatially average
)

# Resample to HEC-RAS grid resolution
ras_grid = PrecipAorc.resample_grid(
    aorc_grid,
    target_resolution_km=2.0  # Match HEC-RAS 2D mesh resolution
)

# Export to HEC-RAS GDAL Raster format
PrecipAorc.export_to_gdal_raster(
    ras_grid,
    output_folder="C:/Projects/MyModel/precipitation",
    format="GeoTIFF"
)

# Update unsteady flow file
from ras_commander import RasUnsteady

RasUnsteady.set_gridded_precipitation(
    unsteady_file="MyModel.u01",
    precip_folder="precipitation",
    start_datetime="2023-06-01 00:00"
)
```

### Spatially Uniform Precipitation

For models with spatially uniform rainfall:

```python
# Retrieve AORC with spatial averaging
avg_precip = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",
    start_date="2023-06-01",
    end_date="2023-06-05",
    spatial_average=True  # Returns time series only
)

# Export to DSS
from ras_commander.usgs import RasUsgsFileIo

RasUsgsFileIo.export_to_dss(
    avg_precip,
    dss_file="precipitation.dss",
    pathname="/BASIN/PRECIP/AORC//1HOUR/OBS/"
)
```

## Batch Processing

Process multiple AEP events across multiple projects:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan
from ras_commander.precip import StormGenerator

# Define project and AEP suite
projects = ["ModelA", "ModelB", "ModelC"]
aep_events = [10, 2, 1, 0.2]  # 10%, 2%, 1%, 0.2%

for project_name in projects:
    project_folder = f"C:/Projects/{project_name}"
    init_ras_project(project_folder, "6.6")

    for aep in aep_events:
        # Query Atlas 14
        precip = StormGenerator.get_precipitation_frequency(
            location=(38.9, -77.0),
            duration_hours=24,
            aep_percent=aep
        )

        # Generate design storm
        hyeto = StormGenerator.generate_design_storm(
            total_precip=precip,
            duration_hours=24,
            distribution="SCS_Type_II"
        )

        # Clone plan for this event
        plan_id = RasPlan.clone_plan(
            "01",
            new_plan_shortid=f"AEP_{aep}pct"
        )

        # Export precipitation and update plan
        dss_file = f"{project_name}_AEP{aep}.dss"
        StormGenerator.export_to_dss(hyeto, dss_file)

        # Execute plan
        RasCmdr.compute_plan(plan_id, num_cores=4)
```

## Data Availability

### Check AORC Coverage

```python
# Verify AORC data exists for time period
coverage = PrecipAorc.check_data_coverage(
    watershed="02070010",
    start_date="2015-01-01",
    end_date="2015-12-31"
)

if coverage['available']:
    print(f"AORC available: {coverage['start']} to {coverage['end']}")
else:
    print("AORC data not available for this period")
```

### Atlas 14 Regions

Atlas 14 coverage by volume:

- **Volume 1**: Semiarid Southwest
- **Volume 2**: Ohio River Basin and Surrounding States
- **Volume 3**: Puerto Rico and U.S. Virgin Islands
- **Volume 4**: Hawaiian Islands
- **Volume 5**: Selected Pacific Islands
- **Volume 6**: California
- **Volume 7**: Alaska
- **Volume 8**: Midwestern States
- **Volume 9**: Southeastern States
- **Volume 10**: Northeastern States
- **Volume 11**: Texas

**Automatic region detection**:
```python
# StormGenerator automatically detects region from lat/lon
precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),  # Automatically uses Volume 2 (Ohio Basin)
    duration_hours=24,
    aep_percent=1.0
)
```

## Performance Considerations

### AORC Data Retrieval

AORC downloads can be large for multi-year analyses:

**Optimization strategies**:

1. **Temporal subsetting** - Download only required time periods
2. **Spatial subsetting** - Use small buffer around watershed
3. **Caching** - Save processed data locally
4. **Resolution** - Aggregate to coarser grid if appropriate

```python
# Optimized retrieval for large watersheds
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=large_watershed,
    start_date="2023-06-01",
    end_date="2023-06-05",  # Short period
    buffer_km=5.0,  # Small buffer
    cache_dir="C:/AORC_Cache"  # Cache for reuse
)
```

### Atlas 14 API

Atlas 14 queries are fast but respect NOAA service limits:

- **Typical query**: < 5 seconds
- **Rate limiting**: Built-in delays between requests
- **Caching**: Automatic caching of API responses

```python
# Batch queries with automatic rate limiting
for lat, lon in project_locations:
    precip = StormGenerator.get_precipitation_frequency(
        location=(lat, lon),
        duration_hours=24,
        aep_percent=1.0
    )
    # Automatic delays prevent overwhelming NOAA servers
```

## Example Notebooks

Comprehensive workflow demonstrations:

- [AORC Precipitation](../notebooks/900_aorc_precipitation.ipynb) - Historical data retrieval and processing
- [AORC Storm Catalog](../notebooks/901_aorc_precipitation_catalog.ipynb) - Automated storm event extraction
- [Atlas 14 AEP Events](../notebooks/720_atlas14_aep_events.ipynb) - Design storm generation
- [Atlas 14 Caching](../notebooks/721_atlas14_caching_demo.ipynb) - Efficient caching strategies
- [Atlas 14 Multi-Project](../notebooks/722_atlas14_multi_project.ipynb) - Batch processing workflows

## Dependencies

**Required**:
```bash
pip install xarray  # For AORC NetCDF data
```

**Optional**:
```bash
pip install rasterio geopandas pydsstools  # For spatial ops and DSS export
```

The module uses **lazy loading** - methods check for dependencies only when needed and provide clear installation instructions if missing.

## Common Workflows

### Calibration Workflow

Use AORC historical data to calibrate HEC-RAS model:

1. **Identify storm event** from historical record
2. **Retrieve AORC data** for event period
3. **Process and export** to HEC-RAS/HMS format
4. **Run model** with historical precipitation
5. **Compare to observed flow/stage** (see [USGS Gauge Data](usgs-gauge-data.md))

### Design Storm Workflow

Use Atlas 14 for regulatory design storm analysis:

1. **Query Atlas 14** for required AEP (e.g., 1% = 100-year)
2. **Generate hyetograph** with appropriate temporal distribution
3. **Apply ARF** if watershed is large (> 10 sq mi)
4. **Export to HEC-RAS/HMS**
5. **Run model** for design event
6. **Extract peak results** for floodplain mapping

### Sensitivity Analysis

Test model sensitivity to precipitation depth:

```python
# Vary precipitation around Atlas 14 estimate
base_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# Test ±20% scenarios
for factor in [0.8, 0.9, 1.0, 1.1, 1.2]:
    precip = base_precip * factor

    hyeto = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    # Clone plan and run
    plan_id = RasPlan.clone_plan("01", new_plan_shortid=f"precip_{int(factor*100)}")
    # ... export precipitation, execute plan
```

## See Also

- [Boundary Conditions](boundary-conditions.md) - General boundary condition workflows
- [DSS Operations](dss-operations.md) - Working with DSS boundary files
- [USGS Gauge Data](usgs-gauge-data.md) - Flow/stage data for validation
- [Plan Execution](plan-execution.md) - Running batch scenarios
