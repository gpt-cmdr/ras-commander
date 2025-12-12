---
name: analyzing-aorc-precipitation
description: |
  Retrieves and processes AORC precipitation data for HEC-RAS/HMS models.
  Handles spatial averaging over watersheds, temporal aggregation, DSS export,
  and Atlas 14 design storms. Use when working with historical precipitation,
  AORC data, calibration workflows, design storm generation, rainfall analysis,
  SCS Type II distributions, AEP events, 100-year storms, or generating
  precipitation boundary conditions for rain-on-grid models.
trigger_keywords:
  - precipitation
  - AORC
  - Atlas 14
  - design storm
  - rainfall
  - SCS Type II
  - AEP
  - 100-year
  - rain-on-grid
  - hyetograph
  - temporal distribution
  - areal reduction
  - calibration
  - historical precipitation
location: .claude/skills/analyzing-aorc-precipitation
---

# Analyzing AORC Precipitation

Complete workflow for integrating precipitation data into HEC-RAS and HEC-HMS models using AORC (Analysis of Record for Calibration) historical data and NOAA Atlas 14 design storms.

## Quick Start

### AORC Historical Data
```python
from ras_commander.precip import PrecipAorc

# Retrieve hourly AORC data for watershed
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed="02070010",  # HUC-8 code or shapefile path
    start_date="2015-05-01",
    end_date="2015-05-15"
)

# Spatial average over watershed
avg_precip = PrecipAorc.spatial_average(aorc_data, watershed)

# Aggregate to HEC-RAS interval
hourly = PrecipAorc.aggregate_to_interval(avg_precip, interval="1HR")

# Export to DSS for HEC-RAS
PrecipAorc.export_to_dss(
    hourly,
    dss_file="precipitation.dss",
    pathname="/PROJECT/PRECIP/AORC//1HOUR/OBS/"
)
```

### Atlas 14 Design Storm
```python
from ras_commander.precip import StormGenerator

# Get 24-hr, 1% AEP (100-year) precipitation
precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),  # lat, lon
    duration_hours=24,
    aep_percent=1.0
)

# Generate SCS Type II distribution
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15
)

# Export to HEC-RAS DSS
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm.dss",
    pathname="/PROJECT/PRECIP/DESIGN//15MIN/SYN/"
)
```

## When to Use This Skill

Use when you need to:

1. **Retrieve historical precipitation** - AORC data for calibration and validation
2. **Generate design storms** - Atlas 14 AEP events (10%, 2%, 1%, 0.2%, etc.)
3. **Process precipitation spatially** - Watershed averaging, areal reduction factors
4. **Aggregate precipitation temporally** - Match HEC-RAS/HMS timesteps
5. **Export to HEC-RAS/HMS** - DSS files, CSV time series, or direct HDF integration
6. **Identify storm events** - Extract individual storms from AORC record
7. **Apply temporal distributions** - SCS Type II, IA, III for design storms

## AORC Data Workflows

### 1. Basic AORC Retrieval

Retrieve historical precipitation for a specific location and time period:

```python
from ras_commander.precip import PrecipAorc
from pathlib import Path

# Define watershed (HUC or shapefile)
watershed = "02070010"  # HUC-8 code
# OR
watershed = Path("watershed_boundary.shp")

# Retrieve data
data = PrecipAorc.retrieve_aorc_data(
    watershed=watershed,
    start_date="2015-01-01",
    end_date="2015-12-31"
)

# Returns xarray Dataset with hourly precipitation on ~4km grid
```

### 2. Spatial Averaging

Calculate areal average over watershed:

```python
# Spatial average (converts grid to single time series)
avg_precip = PrecipAorc.spatial_average(data, watershed)

# Result is pandas Series indexed by time
print(f"Total precipitation: {avg_precip.sum():.2f} mm")
```

### 3. Temporal Aggregation

Aggregate to match HEC-RAS/HMS timestep:

```python
# Available intervals: 15MIN, 30MIN, 1HR, 6HR, 1DAY
hourly = PrecipAorc.aggregate_to_interval(avg_precip, interval="1HR")
six_hour = PrecipAorc.aggregate_to_interval(avg_precip, interval="6HR")
daily = PrecipAorc.aggregate_to_interval(avg_precip, interval="1DAY")
```

### 4. Storm Catalog Generation

Identify all significant storm events in a time period:

```python
# Generate catalog of storms
catalog = PrecipAorc.get_storm_catalog(
    bounds=(-77.5, 38.5, -76.5, 39.5),  # west, south, east, north
    year=2020,
    inter_event_hours=8.0,     # USGS standard for storm separation
    min_depth_inches=0.75,     # Minimum significant precipitation
    buffer_hours=48            # Simulation warmup buffer
)

# Result is DataFrame with columns:
# storm_id, start_time, end_time, sim_start, sim_end,
# total_depth_in, peak_intensity_in_hr, duration_hours, rank

print(f"Found {len(catalog)} storms in {year}")
```

### 5. Export to HEC-RAS/HMS

Multiple output formats supported:

```python
# DSS format (requires pydsstools)
PrecipAorc.export_to_dss(
    hourly,
    dss_file="precipitation.dss",
    pathname="/PROJECT/PRECIP/AORC//1HOUR/OBS/"
)

# CSV for HEC-HMS
hourly.to_csv("aorc_precipitation.csv")

# Direct HDF integration for HEC-RAS rain-on-grid
from ras_commander import RasUnsteady

RasUnsteady.set_gridded_precipitation(
    plan_number="01",
    precip_file="aorc_data.nc",  # NetCDF from PrecipAorc.download()
    start_time="2015-05-01 00:00",
    end_time="2015-05-15 00:00"
)
```

### 6. Complete Storm Processing Workflow

Automate storm identification, download, and plan creation:

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.precip import PrecipAorc

# Initialize project
ras = init_ras_project("path/to/project", "6.6")

# Get project bounds from geometry HDF
from ras_commander.hdf import HdfProject
geom_hdf = ras.project_folder / f"{ras.project_name}.g09.hdf"
bounds = HdfProject.get_project_bounds_latlon(
    geom_hdf,
    buffer_percent=50.0  # 50% buffer ensures full coverage
)

# Generate storm catalog
catalog = PrecipAorc.get_storm_catalog(
    bounds=bounds,
    year=2020,
    inter_event_hours=8.0,
    min_depth_inches=0.75,
    buffer_hours=48
)

# Create plans with precipitation data
results = PrecipAorc.create_storm_plans(
    storm_catalog=catalog,
    bounds=bounds,
    template_plan="06",
    precip_folder="Precipitation",
    ras_object=ras,
    download_data=True
)

# Execute all storm plans in parallel
plan_numbers = results[results['status'] == 'success']['plan_number'].tolist()
execution_results = RasCmdr.compute_parallel(
    plan_number=plan_numbers,
    max_workers=3,
    num_cores=2,
    ras_object=ras
)
```

## Atlas 14 Design Storm Workflows

### 1. Query Precipitation Frequency

Retrieve Atlas 14 point precipitation estimates:

```python
from ras_commander.precip import StormGenerator

# Get 24-hour, 1% AEP (100-year) precipitation
precip_100yr = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),  # (lat, lon)
    duration_hours=24,
    aep_percent=1.0  # 1% = 100-year event
)

print(f"24-hr, 1% AEP: {precip_100yr:.2f} inches")

# Common AEPs:
# 50% = 2-year
# 20% = 5-year
# 10% = 10-year
# 4% = 25-year
# 2% = 50-year
# 1% = 100-year
# 0.5% = 200-year
# 0.2% = 500-year
```

### 2. Generate Design Storm Hyetograph

Apply temporal distribution to create design storm:

```python
# Generate SCS Type II distribution (standard for most of US)
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip_100yr,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15  # 15-minute increments
)

# Available distributions:
# - SCS_Type_II (standard for most of US)
# - SCS_Type_IA (Pacific maritime climate)
# - SCS_Type_III (Gulf Coast and Florida)
# - Custom (user-defined pattern)
```

### 3. Apply Areal Reduction Factor

For large watersheds, reduce point precipitation:

```python
# Apply ARF for 500 sq mi watershed
watershed_area_sqmi = 500
reduced_precip = StormGenerator.apply_areal_reduction(
    point_precip=precip_100yr,
    area_sqmi=watershed_area_sqmi,
    duration_hours=24
)

print(f"Point: {precip_100yr:.2f} in")
print(f"Areal (500 sq mi): {reduced_precip:.2f} in")

# ARF Guidance:
# < 10 sq mi: ARF ≈ 1.0 (use point values)
# 10-100 sq mi: ARF = 0.95-0.98
# > 100 sq mi: ARF < 0.95 (significant reduction)
```

### 4. Multi-Event Suite

Run multiple AEP events for flood frequency analysis:

```python
# Define AEP suite
aep_events = [10, 4, 2, 1, 0.5, 0.2]  # 10%, 4%, 2%, 1%, 0.5%, 0.2%

for aep in aep_events:
    # Query Atlas 14
    precip = StormGenerator.get_precipitation_frequency(
        location=(38.9, -77.0),
        duration_hours=24,
        aep_percent=aep
    )

    # Generate design storm
    hyetograph = StormGenerator.generate_design_storm(
        total_precip=precip,
        duration_hours=24,
        distribution="SCS_Type_II"
    )

    # Export to DSS
    dss_file = f"design_storm_{aep}pct.dss"
    StormGenerator.export_to_dss(hyetograph, dss_file)

    print(f"{aep}% AEP: {precip:.2f} in → {dss_file}")
```

## Key Concepts

### AORC Dataset
- **Coverage**: CONUS (1979-present), Alaska (1981-present)
- **Resolution**: ~800 meters, hourly timesteps
- **Format**: Cloud-optimized Zarr on AWS S3
- **Access**: Anonymous (no authentication required)
- **Provider**: NOAA Office of Water Prediction

### NOAA Atlas 14
- **Coverage**: CONUS, Hawaii, Puerto Rico
- **Data**: Precipitation frequency estimates (depth-duration-frequency)
- **Access**: NOAA HDSC Precipitation Frequency Data Server (PFDS)
- **Format**: JSON API response
- **Provider**: NOAA National Weather Service

### Temporal Distributions
- **SCS Type II**: Standard for most of US (24-hr peak at 12 hours)
- **SCS Type IA**: Pacific maritime climate (24-hr peak at 8 hours)
- **SCS Type III**: Gulf Coast and Florida (24-hr peak at 13 hours)

### Storm Separation
- **Inter-event hours**: Time between storms (USGS standard: 6-8 hours)
- **Minimum depth**: Threshold for significant precipitation (typical: 0.5-1.0 inches)
- **Buffer hours**: Simulation warmup period (typical: 24-48 hours)

## Related Skills and References

### Cross-References
- **Precipitation Specialist Subagent**: `.claude/subagents/precipitation-specialist/` (if available)
- **Precip Module Documentation**: `ras_commander/precip/CLAUDE.md`
- **DSS Operations**: `ras_commander.dss.RasDss` for DSS file operations
- **Unsteady Flow**: `ras_commander.RasUnsteady` for boundary condition management

### Example Notebooks
- `examples/24_aorc_precipitation.ipynb` - Complete AORC workflow
- `examples/103_Running_AEP_Events_from_Atlas_14.ipynb` - Single-project Atlas 14
- `examples/104_Atlas14_AEP_Multi_Project.ipynb` - Batch processing multiple projects

### Reference Documentation
- [reference/aorc-api.md](reference/aorc-api.md) - Complete AORC API reference
- [reference/atlas14.md](reference/atlas14.md) - Design storm generation details

### Example Scripts
- [examples/aorc-retrieval.py](examples/aorc-retrieval.py) - Basic AORC workflow
- [examples/design-storm.py](examples/design-storm.py) - Atlas 14 generation

## Dependencies

**Required**:
- pandas (time series handling)
- numpy (numerical operations)
- xarray (for AORC NetCDF data)
- requests (Atlas 14 API access)

**Optional**:
- geopandas (spatial operations on watersheds)
- rasterio (AORC grid processing)
- pydsstools (DSS export, lazy-loaded)

**Installation**:
```bash
pip install ras-commander[precip]  # Includes all precipitation dependencies
# OR
pip install xarray rasterio geopandas pydsstools
```

## Common Use Cases

### Calibration with AORC
1. Retrieve AORC for historical storm event
2. Apply spatial average over watershed
3. Aggregate to model timestep
4. Run HEC-RAS/HMS model
5. Compare modeled vs observed flow/stage

### Design Storm Analysis
1. Query Atlas 14 for design AEP
2. Generate temporal distribution (SCS Type II)
3. Apply areal reduction (if needed)
4. Export to HEC-RAS/HMS
5. Run model for design event

### Multi-Event Suite
1. Define AEP range (50% to 0.2%)
2. Loop through events
3. Generate design storms for each
4. Batch run HEC-RAS models
5. Generate flood frequency curves

### Rain-on-Grid Models
1. Get project bounds from geometry HDF
2. Download AORC NetCDF at project resolution
3. Write precipitation directly to unsteady HDF
4. Execute model with gridded precipitation
5. Extract 2D inundation results
