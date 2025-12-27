# Precipitation Workflows

This subpackage provides tools for integrating precipitation data into HEC-RAS models, including AORC (Analysis of Record for Calibration) and NOAA Atlas 14 design storms.

## Purpose

The precip subpackage automates precipitation data retrieval, processing, and formatting for HEC-RAS and HEC-HMS models. It supports both historical calibration workflows (AORC) and design storm generation (Atlas 14).

## Module Organization

The precip subpackage contains 5 modules organized by data source:

### PrecipAorc.py (AORC Data Integration)

**PrecipAorc** - Historical precipitation data from AORC dataset (38 KB):

**Data Retrieval**:
- `retrieve_aorc_data()` - Download AORC precipitation time series for watershed
- `get_available_years()` - Query available data years (1979-present)
- `check_data_coverage()` - Verify spatial and temporal coverage

**Spatial Processing**:
- `extract_by_watershed()` - Extract data for HUC or custom polygon
- `spatial_average()` - Calculate areal average over watershed
- `resample_grid()` - Aggregate AORC grid cells to coarser resolution

**Temporal Processing**:
- `aggregate_to_interval()` - Aggregate to HEC-RAS/HMS intervals (1HR, 6HR, 1DAY)
- `extract_storm_events()` - Identify and extract individual storm events
- `calculate_rolling_totals()` - Compute N-hour rolling precipitation totals

**Output Formats**:
- CSV time series (for HEC-HMS)
- DSS format (for HEC-RAS/HMS via pydsstools)
- NetCDF (for further analysis)

**AORC Dataset Details**:
- **Spatial Resolution**: ~4 km grid (1/24 degree)
- **Temporal Resolution**: Hourly precipitation
- **Coverage**: Continental United States (CONUS)
- **Period of Record**: 1979 - present (updated operationally)
- **Source**: NOAA National Water Model retrospective forcing

### StormGenerator.py (Atlas 14 Design Storms)

**StormGenerator** - NOAA Atlas 14 design storm generation (27 KB):

**Design Storm Creation**:
- `generate_design_storm()` - Create Atlas 14 design storm hyetograph
- `get_precipitation_frequency()` - Query Atlas 14 point precipitation values
- `apply_temporal_distribution()` - Apply standard temporal patterns (SCS Type II, etc.)

**AEP Events** (Annual Exceedance Probability):
- Standard AEPs: 50%, 20%, 10%, 4%, 2%, 1%, 0.5%, 0.2%
- Common durations: 6hr, 12hr, 24hr, 48hr
- Custom AEP and duration supported

**Temporal Distributions**:
- **SCS Type II** - Standard for most of US
- **SCS Type IA** - Pacific maritime climate
- **SCS Type III** - Gulf Coast and Florida
- **Custom distributions** - User-defined hyetograph patterns

**Spatial Processing**:
- `interpolate_point_values()` - Interpolate Atlas 14 values to grid
- `apply_areal_reduction()` - Apply ARF (Areal Reduction Factor) for large watersheds
- `generate_multi_point_storms()` - Spatially distributed design storms

**Output Formats**:
- HEC-HMS precipitation gage file
- HEC-RAS DSS precipitation
- Tabular hyetograph (CSV)

**Atlas 14 Regions**:
- CONUS coverage (volumes 1-11)
- Automatic region detection by lat/lon
- Hawaii and Puerto Rico supported

### Atlas14Storm (HMS-Equivalent - from hms-commander)

**Atlas14Storm** - HMS-equivalent hyetograph generation (imported from hms-commander):

**Key Distinction from StormGenerator**:
- **Atlas14Storm**: Matches HEC-HMS "Specified Pattern" at **10^-6 precision**
- **StormGenerator**: Uses Alternating Block Method, **NOT HMS-equivalent**

**Choose Atlas14Storm** for:
- HMS-equivalent workflows
- Official NOAA Atlas 14 temporal distributions
- Workflows requiring proven depth conservation

**Choose StormGenerator** for:
- Flexible peak positioning (0-100%)
- Non-HMS workflows
- Custom DDF data sources

**Usage**:
```python
from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

if ATLAS14_AVAILABLE:
    # Generate HMS-equivalent hyetograph
    hyeto = Atlas14Storm.generate_hyetograph(
        total_depth_inches=17.9,
        state="tx",
        region=3,
        aep_percent=1.0,
        quartile="All Cases"
    )
    print(f"Total depth: {hyeto.sum():.6f} inches")  # Exact: 17.900000
```

**Quartile Options**:
- "First Quartile", "Second Quartile", "Third Quartile", "Fourth Quartile", "All Cases"

**Dependency**: Requires `hms-commander>=0.1.0` (installed automatically with ras-commander)

### Atlas14Grid.py (Gridded PFE Access)

**Atlas14Grid** - Remote access to NOAA Atlas 14 CONUS grids:

**Key Feature**: Downloads only data within project extent via HTTP byte-range requests (99.9% data reduction compared to full state downloads).

**Data Access**:
- `get_pfe_for_bounds()` - Get precipitation frequency for a bounding box
- `get_pfe_from_project()` - Get PFE using HEC-RAS project extent
- `get_point_pfe()` - Get PFE for a single point (quick lookup)

**Integration with HEC-RAS**:
- Automatic extent extraction from 2D flow areas or project bounds
- `extent_source` parameter: "2d_flow_area" (default) or "project_extent"
- Buffer percentage for extent expansion

**Data Specifications**:
- **Coverage**: CONUS (24°N-50°N, -125°W to -66°W)
- **Resolution**: ~0.0083° (~830m)
- **Durations**: 1, 2, 3, 6, 12, 24, 48, 72, 96, 168 hours
- **Return Periods**: 2, 5, 10, 25, 50, 100, 200, 500, 1000 years
- **Units**: inches (raw values × 0.01 scale factor)

**Usage**:
```python
from ras_commander.precip import Atlas14Grid

# Get PFE for HEC-RAS project
pfe = Atlas14Grid.get_pfe_from_project(
    geom_hdf="MyProject.g01.hdf",
    extent_source="2d_flow_area",
    durations=[6, 12, 24],
    return_periods=[10, 50, 100]
)

# Access data
print(f"100-yr 24-hr max: {pfe['pfe_24hr'][:,:,5].max():.2f} inches")
```

### Atlas14Variance.py (Variance Analysis)

**Atlas14Variance** - Spatial variance analysis for precipitation:

**Purpose**: Assess whether uniform rainfall assumptions are appropriate for rain-on-grid modeling.

**Analysis Methods**:
- `analyze()` - Full variance analysis across durations/return periods
- `analyze_quick()` - Quick check for single representative event
- `calculate_stats()` - Calculate min/max/mean/range for array
- `is_uniform_rainfall_appropriate()` - Decision support

**Report Generation**:
- `generate_report()` - Export CSV and plots for engineering review

**Variance Metrics**:
- `variance_denominator='min'`: range_pct = (max - min) / min × 100
- `variance_denominator='max'`: range_pct = (max - min) / max × 100
- `variance_denominator='mean'`: range_pct = (max - min) / mean × 100

**Usage**:
```python
from ras_commander.precip import Atlas14Variance

# Full variance analysis
results = Atlas14Variance.analyze(
    geom_hdf="MyProject.g01.hdf",
    durations=[6, 12, 24],
    return_periods=[10, 25, 50, 100]
)

# Check if uniform rainfall is appropriate
ok, msg = Atlas14Variance.is_uniform_rainfall_appropriate(results, threshold_pct=10.0)
print(msg)
```

**Guidance**:
- Range percentage > 10% suggests spatially variable rainfall should be considered
- Larger model domains typically show higher variance
- 100-year, 24-hour is a common representative event for quick checks

### __init__.py (Package Interface)

**Public API**:
```python
from ras_commander.precip import PrecipAorc, StormGenerator

# Gridded PFE access and variance analysis
from ras_commander.precip import Atlas14Grid, Atlas14Variance

# HMS-equivalent Atlas 14 (from hms-commander)
from ras_commander.precip import Atlas14Storm, Atlas14Config, ATLAS14_AVAILABLE

# Convenience imports
from ras_commander.precip import (
    PrecipAorc,
    StormGenerator,
    Atlas14Grid,       # Remote access to NOAA Atlas 14 CONUS grids
    Atlas14Variance,   # Spatial variance analysis for precipitation
    Atlas14Storm,      # HMS-equivalent temporal distributions
    Atlas14Config,     # Configuration dataclass
    ATLAS14_AVAILABLE  # Boolean flag for availability check
)
```

## AORC Workflow

Historical calibration with AORC precipitation:

### 1. Define Watershed

Specify watershed boundary (HUC or custom shapefile):
```python
from ras_commander.precip import PrecipAorc
from pathlib import Path

# Option 1: HUC code
watershed = "02070010"  # HUC-8 code

# Option 2: Custom shapefile
watershed = Path("watershed_boundary.shp")
```

### 2. Retrieve AORC Data

Download and process time series:
```python
# Retrieve hourly AORC data
aorc_data = PrecipAorc.retrieve_aorc_data(
    watershed=watershed,
    start_date="2015-01-01",
    end_date="2015-12-31"
)

# Spatial average over watershed
avg_precip = PrecipAorc.spatial_average(aorc_data, watershed)
```

### 3. Aggregate to HEC-RAS Interval

Temporal aggregation to match model timestep:
```python
# Aggregate to 1-hour intervals (for HEC-RAS)
hourly_precip = PrecipAorc.aggregate_to_interval(
    avg_precip,
    interval="1HR"
)

# Aggregate to 6-hour intervals (for coarse models)
six_hour_precip = PrecipAorc.aggregate_to_interval(
    avg_precip,
    interval="6HR"
)
```

### 4. Export to HEC-RAS/HMS

Generate model input files:
```python
# Export to DSS (requires pydsstools)
PrecipAorc.export_to_dss(
    hourly_precip,
    dss_file="precipitation.dss",
    pathname="/PROJECT/PRECIP/AORC//1HOUR/OBS/"
)

# Export to CSV (for HEC-HMS)
hourly_precip.to_csv("aorc_precipitation.csv")
```

## Atlas 14 Workflow

Design storm generation for AEP events:

### 1. Specify Location

Define location for precipitation frequency query:
```python
from ras_commander.precip import StormGenerator

# Option 1: Lat/lon
location = (38.9072, -77.0369)  # Washington, DC

# Option 2: Station ID (if available)
location = "USGS:01646500"
```

### 2. Query Atlas 14 Values

Retrieve precipitation frequency estimates:
```python
# Get 24-hour, 1% AEP (100-year) precipitation
precip_value = StormGenerator.get_precipitation_frequency(
    location=location,
    duration_hours=24,
    aep_percent=1.0  # 1% = 100-year event
)

print(f"24-hr, 1% AEP precipitation: {precip_value} inches")
```

### 3. Generate Design Storm

Create temporal distribution:
```python
# Generate SCS Type II distribution
hyetograph = StormGenerator.generate_design_storm(
    total_precip=precip_value,
    duration_hours=24,
    distribution="SCS_Type_II",
    interval_minutes=15  # 15-minute increments
)
```

### 4. Export to HEC-RAS/HMS

Multiple output formats:
```python
# Export to DSS
StormGenerator.export_to_dss(
    hyetograph,
    dss_file="design_storm.dss",
    pathname="/PROJECT/PRECIP/DESIGN//15MIN/SYN/"
)

# Export to HEC-HMS gage file
StormGenerator.export_to_hms_gage(
    hyetograph,
    output_file="design_storm.gage",
    gage_id="PRECIP1"
)

# Export to CSV
hyetograph.to_csv("design_storm.csv")
```

## Multi-Event Workflows

Running multiple AEP events across projects:

```python
from ras_commander.precip import StormGenerator

# Define AEP suite (10%, 2%, 1%, 0.2%)
aep_events = [10, 2, 1, 0.2]

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
```

## Areal Reduction Factors (ARF)

For large watersheds, apply areal reduction:

```python
# Point precipitation (from Atlas 14)
point_precip = StormGenerator.get_precipitation_frequency(
    location=(38.9, -77.0),
    duration_hours=24,
    aep_percent=1.0
)

# Apply ARF for 500 sq mi watershed
watershed_area_sqmi = 500
reduced_precip = StormGenerator.apply_areal_reduction(
    point_precip=point_precip,
    area_sqmi=watershed_area_sqmi,
    duration_hours=24
)

print(f"Point: {point_precip:.2f} in")
print(f"Areal (500 sq mi): {reduced_precip:.2f} in")
```

**ARF Guidance**:
- Small watersheds (< 10 sq mi): ARF ≈ 1.0 (use point values)
- Medium watersheds (10-100 sq mi): ARF = 0.95-0.98
- Large watersheds (> 100 sq mi): ARF < 0.95 (significant reduction)

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Precipitation files reviewable in HEC-RAS/HMS GUI
- **Visual Outputs**: Time series plots and hyetographs for visual verification
- **Code Audit Trails**: All functions use @log_call decorators for execution tracking

### AORC Advantages
- Historical precipitation for calibration and validation
- Spatially distributed data (not just point gages)
- Consistent coverage across CONUS
- Hourly resolution suitable for urban hydrology

### Atlas 14 Advantages
- Authoritative NOAA precipitation frequency estimates
- Regional temporal distributions
- Support for full range of AEPs and durations
- Areal reduction factors for large watersheds

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
pip install xarray rasterio geopandas pydsstools
```

## Data Sources

### AORC (Analysis of Record for Calibration)
- **Provider**: NOAA Office of Water Prediction
- **Access**: NOAA NWM retrospective forcing archive
- **Format**: NetCDF (gridded)
- **Update Frequency**: Operational (near real-time)
- **Documentation**: https://water.noaa.gov/about/nwm

### NOAA Atlas 14
- **Provider**: NOAA National Weather Service
- **Access**: NOAA HDSC Precipitation Frequency Data Server (PFDS)
- **Format**: JSON API response (point), NetCDF (gridded CONUS)
- **Coverage**: CONUS, Hawaii, Puerto Rico
- **Documentation**: https://hdsc.nws.noaa.gov/pfds/

### Atlas 14 CONUS NetCDF (for Atlas14Grid)
- **Provider**: NOAA HDSC
- **Access**: HTTP with byte-range requests (remote spatial subsetting)
- **URL**: `https://hdsc.nws.noaa.gov/pub/hdsc/data/tx/NOAA_Atlas_14_CONUS.nc`
- **Format**: HDF5-based NetCDF-4 (320 MB total, chunked for efficient access)
- **Coverage**: CONUS only (24°N-50°N, -125°W to -66°W)
- **Resolution**: ~0.0083° (~830m)
- **Data**: 10 durations (1-168 hr), 9 return periods (2-1000 yr)

## Example Notebooks

Complete workflow demonstrations:

- `examples/900_aorc_precipitation.ipynb` - AORC retrieval and processing
- `examples/720_atlas14_aep_events.ipynb` - Single-project Atlas 14 workflow
- `examples/722_atlas14_multi_project.ipynb` - Batch processing multiple projects
- `examples/725_atlas14_spatial_variance.ipynb` - Spatial variance analysis for uniform rainfall assessment

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

### Spatial Variance Analysis
1. Load HEC-RAS geometry HDF file
2. Extract 2D flow area extent
3. Download Atlas 14 grid data for extent
4. Calculate variance statistics (min/max/mean/range)
5. Determine if uniform rainfall is appropriate

```python
from ras_commander.precip import Atlas14Variance

# Quick check for 100-yr 24-hr
stats = Atlas14Variance.analyze_quick("MyProject.g01.hdf")
if stats['range_pct'] > 10:
    print("Consider spatially variable rainfall")
```

## Performance

### AORC Data Retrieval
- **Speed**: ~1-5 minutes per year of hourly data (depends on watershed size)
- **Storage**: ~10-50 MB per year (hourly, single watershed)
- **Caching**: Local cache recommended for repeated analyses

### Atlas 14 Queries
- **Speed**: < 5 seconds per query (API access)
- **Rate Limiting**: NOAA PFDS has request limits (respect usage guidelines)
- **Caching**: Automatic caching of API responses

### Atlas 14 Grid Access
- **Speed**: ~5-15 seconds for typical project extent (HTTP range requests)
- **Data Transfer**: ~250 KB for 1°×1° extent (vs 50-100 MB for full state ZIPs)
- **Efficiency**: 99.9% reduction compared to downloading full state datasets
- **Caching**: Coordinate arrays cached in memory after first load

## Atlas 14 Grid Workflow

Complete workflow for spatial variance analysis:

### 1. Check If Analysis is Needed

Quick variance check to see if spatial analysis is warranted:

```python
from ras_commander.precip import Atlas14Variance

# Quick check for representative event (100-yr, 24-hr)
stats = Atlas14Variance.analyze_quick(
    geom_hdf="MyProject.g01.hdf",
    duration=24,
    return_period=100
)

print(f"Range: {stats['range_pct']:.1f}%")

if stats['range_pct'] > 10:
    print("⚠️ High variance - consider spatially variable rainfall")
else:
    print("✓ Uniform rainfall likely appropriate")
```

### 2. Full Variance Analysis

If quick check shows variance, run comprehensive analysis:

```python
from ras_commander.precip import Atlas14Variance

# Analyze across multiple events
results = Atlas14Variance.analyze(
    geom_hdf="MyProject.g01.hdf",
    durations=[6, 12, 24, 48],
    return_periods=[10, 25, 50, 100, 500],
    extent_source="2d_flow_area",  # Use 2D flow area extents
    variance_denominator='min',
    output_dir="Atlas14_Variance_Report"
)

# Review results
print(results[['duration_hr', 'return_period_yr', 'min_inches', 'max_inches', 'range_pct']])
```

### 3. Generate Report

Export results with visualizations:

```python
# Generate comprehensive report
report_dir = Atlas14Variance.generate_report(
    results_df=results,
    output_dir="Atlas14_Variance_Report",
    project_name="My Project",
    include_plots=True
)

# Files created:
# - variance_statistics.csv (detailed results)
# - variance_summary.csv (summary by mesh area)
# - variance_by_duration.png (plot)
# - variance_heatmap.png (plot)
```

### 4. Access Raw Grid Data

For custom analysis or export to HEC-RAS:

```python
from ras_commander.precip import Atlas14Grid

# Get grid data for project extent
pfe = Atlas14Grid.get_pfe_from_project(
    geom_hdf="MyProject.g01.hdf",
    extent_source="2d_flow_area",
    durations=[24],
    return_periods=[100]
)

# Access data arrays
lat = pfe['lat']
lon = pfe['lon']
data_100yr_24hr = pfe['pfe_24hr'][:, :, 5]  # 100-yr is index 5

# Export to GeoTIFF or NetCDF for HEC-RAS import
# (future feature)
```

## See Also

- Parent library context: `ras_commander/CLAUDE.md`
- DSS file operations: `ras_commander/dss/AGENTS.md`
- Unsteady flow files: `ras_commander.RasUnsteady`
- Spatial data handling: `.claude/rules/python/path-handling.md`
