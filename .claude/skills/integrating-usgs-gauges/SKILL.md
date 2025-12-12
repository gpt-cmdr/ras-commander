---
name: integrating-usgs-gauges
description: |
  Complete USGS gauge data integration workflow from spatial discovery to
  model validation. Handles gauge finding, data retrieval, matching to HEC-RAS
  features, boundary condition generation, initial conditions, real-time
  monitoring, and validation metrics (NSE, KGE). Use when working with USGS
  data, NWIS gauges, generating boundaries from observed flow, calibrating
  models, validating with observed data, or setting up operational forecasting.
---

# Integrating USGS Gauges

Complete integration between USGS National Water Information System (NWIS) gauge data and HEC-RAS models, covering spatial discovery, data retrieval, boundary condition generation, and model validation.

## Quick Start

Basic workflow from gauge discovery to boundary condition generation:

```python
from ras_commander import init_ras_project, ras
from ras_commander.usgs import (
    UsgsGaugeSpatial,
    RasUsgsCore,
    GaugeMatcher,
    RasUsgsTimeSeries,
    RasUsgsBoundaryGeneration
)

# Initialize project
init_ras_project(r"C:\Projects\MyModel", "6.5")

# 1. Find gauges within project bounds (5-mile buffer)
gauges_gdf = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder=r"C:\Projects\MyModel",
    buffer_miles=5.0
)

print(f"Found {len(gauges_gdf)} USGS gauges")
print(gauges_gdf[['site_no', 'station_nm', 'drain_area_va']])

# 2. Retrieve flow data for specific gauge
flow_data = RasUsgsCore.retrieve_flow_data(
    site_no="01646500",  # Potomac River at Little Falls
    start_date="2023-09-01",
    end_date="2023-09-15",
    service='iv'  # Instantaneous values (15-min or hourly)
)

print(f"Retrieved {len(flow_data)} observations")
print(f"Flow range: {flow_data['value'].min():.0f} to {flow_data['value'].max():.0f} cfs")

# 3. Match gauge to nearest cross section
matches = GaugeMatcher.auto_match_gauges(
    gauges_gdf=gauges_gdf,
    project_folder=r"C:\Projects\MyModel"
)

print(f"\nGauge Matches:")
for _, match in matches.iterrows():
    print(f"  {match['site_no']}: {match['matched_feature']} (distance: {match['distance_ft']:.0f} ft)")

# 4. Resample to HEC-RAS interval
resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    flow_data,
    interval="15MIN"
)

# 5. Generate boundary condition table
bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=resampled,
    river="Potomac River",
    reach="Main",
    rs="100.0"
)

print(f"\nBoundary condition table generated ({len(bc_table)} lines)")

# 6. Update unsteady file
RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=r"C:\Projects\MyModel\MyPlan.u01",
    bc_table=bc_table,
    bc_line_number=15  # Line number of existing BC to replace
)

print("Boundary condition updated in .u01 file")
```

## Core Workflow Stages

### Stage 1: Spatial Discovery

Find USGS gauges within or near your HEC-RAS project:

```python
from ras_commander.usgs import UsgsGaugeSpatial

# Find all gauges in project bounds
gauges = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder=r"C:\Projects\MyModel",
    buffer_miles=5.0  # Expand search beyond project bounds
)

# Filter for gauges with data in simulation period
gauges_with_data = UsgsGaugeSpatial.get_project_gauges_with_data(
    project_folder=r"C:\Projects\MyModel",
    start_date="2023-09-01",
    end_date="2023-09-15",
    buffer_miles=5.0
)

# Find gauges near specific point
gauges_near_point = UsgsGaugeSpatial.find_gauges_near_point(
    lat=38.9490,
    lon=-77.1333,
    radius_miles=10.0
)
```

**Returns**: GeoDataFrame with gauge locations, site numbers, names, drainage areas, and activity status.

### Stage 2: Data Retrieval

Download flow and stage data from USGS NWIS:

```python
from ras_commander.usgs import RasUsgsCore

# Retrieve flow data (instantaneous values)
flow_data = RasUsgsCore.retrieve_flow_data(
    site_no="01646500",
    start_date="2023-09-01",
    end_date="2023-09-15",
    service='iv'  # 'iv' = instantaneous, 'dv' = daily
)

# Retrieve stage data
stage_data = RasUsgsCore.retrieve_stage_data(
    site_no="01646500",
    start_date="2023-09-01",
    end_date="2023-09-15",
    service='iv'
)

# Get gauge metadata
metadata = RasUsgsCore.get_gauge_metadata(site_no="01646500")
print(f"Gauge: {metadata['station_nm']}")
print(f"Drainage area: {metadata['drain_area_va']} sq mi")

# Check data availability before retrieval
available = RasUsgsCore.check_data_availability(
    site_no="01646500",
    start_date="2023-09-01",
    end_date="2023-09-15",
    parameter='flow'
)
```

**Parameter codes**:
- `flow` → 00060 (Discharge, cfs)
- `stage` → 00065 (Gage height, ft)

**Service types**:
- `iv` - Instantaneous values (15-minute or hourly intervals)
- `dv` - Daily values (for historical analysis)

### Stage 3: Gauge Matching

Match gauges to HEC-RAS model features:

```python
from ras_commander.usgs import GaugeMatcher

# Automatic matching to cross sections and 2D areas
matches = GaugeMatcher.auto_match_gauges(
    gauges_gdf=gauges,
    project_folder=r"C:\Projects\MyModel"
)

# Match specific gauge to nearest cross section
xs_match = GaugeMatcher.match_gauge_to_cross_section(
    gauge_lat=38.9490,
    gauge_lon=-77.1333,
    project_folder=r"C:\Projects\MyModel"
)

print(f"Matched to: {xs_match['river']} / {xs_match['reach']} / {xs_match['rs']}")
print(f"Distance: {xs_match['distance_ft']:.0f} ft")

# Match to 2D flow area
area_match = GaugeMatcher.match_gauge_to_2d_area(
    gauge_lat=38.9490,
    gauge_lon=-77.1333,
    project_folder=r"C:\Projects\MyModel"
)

# Assess matching confidence
confidence = GaugeMatcher.get_matching_confidence(
    gauge_drainage_area=56.0,
    model_drainage_area=58.3,
    distance_ft=250.0
)
```

**Matching criteria**:
- Spatial proximity (distance to cross section or 2D area)
- Drainage area comparison (gauge vs upstream model area)
- River/reach name matching (when available)

### Stage 4: Time Series Processing

Prepare USGS data for HEC-RAS compatibility:

```python
from ras_commander.usgs import RasUsgsTimeSeries

# Resample to HEC-RAS interval
resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    flow_data,
    interval="15MIN"  # HEC-RAS interval code
)

# Check for data gaps
gaps = RasUsgsTimeSeries.check_data_gaps(flow_data)
if gaps['has_gaps']:
    print(f"Warning: {gaps['num_gaps']} gaps detected")
    print(f"Total gap duration: {gaps['total_gap_hours']:.1f} hours")

# Fill gaps if needed
filled_data = RasUsgsTimeSeries.fill_data_gaps(
    flow_data,
    method='linear'  # or 'forward', 'backward'
)

# Align observed and modeled time series for validation
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=flow_data,
    modeled=modeled_results,
    method='nearest'
)

# Extract simulation period
sim_period = RasUsgsTimeSeries.extract_simulation_period(
    flow_data,
    start_datetime="2023-09-01 00:00",
    end_datetime="2023-09-15 23:59"
)
```

**HEC-RAS interval codes**:
- `15MIN`, `30MIN`, `1HOUR`, `2HOUR`, `6HOUR`, `1DAY`

### Stage 5: Boundary Condition Generation

Create HEC-RAS boundary condition tables:

```python
from ras_commander.usgs import RasUsgsBoundaryGeneration

# Generate flow hydrograph table (fixed-width format)
bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=resampled,
    river="Potomac River",
    reach="Main",
    rs="100.0"
)

# Generate stage hydrograph table
stage_bc_table = RasUsgsBoundaryGeneration.generate_stage_hydrograph_table(
    stage_data=resampled_stage,
    river="Potomac River",
    reach="Main",
    rs="200.0"
)

# Update existing boundary condition in .u## file
RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=r"C:\Projects\MyModel\MyPlan.u01",
    bc_table=bc_table,
    bc_line_number=15  # Line number where BC starts
)

# Validate format before writing
is_valid = RasUsgsBoundaryGeneration.validate_boundary_format(bc_table)
if not is_valid:
    print("Warning: Boundary table format invalid")
```

**Output format**: HEC-RAS fixed-width format compatible with .u## unsteady files.

### Stage 6: Initial Conditions

Extract initial condition values from USGS data:

```python
from ras_commander.usgs import InitialConditions

# Get IC value at simulation start time
ic_value = InitialConditions.get_ic_value_from_usgs(
    flow_data=flow_data,
    start_datetime="2023-09-01 00:00"
)

print(f"Initial flow: {ic_value:.0f} cfs")

# Create IC line for .u## file
ic_line = InitialConditions.create_ic_line(
    river="Potomac River",
    reach="Main",
    rs="100.0",
    value=ic_value,
    ic_type='flow'  # or 'stage'
)

# Update initial conditions in unsteady file
InitialConditions.update_initial_conditions(
    unsteady_file=r"C:\Projects\MyModel\MyPlan.u01",
    ic_line=ic_line,
    ic_line_number=10
)

# Parse existing IC lines
existing_ics = InitialConditions.parse_initial_conditions(
    unsteady_file=r"C:\Projects\MyModel\MyPlan.u01"
)
```

**IC types**:
- `flow` - Flow initial conditions (for upstream boundaries)
- `stage` - Stage initial conditions (for downstream boundaries)

### Stage 7: Real-Time Monitoring (v0.87.0+)

Monitor gauges for operational forecasting and early warning:

```python
from ras_commander.usgs import RasUsgsRealTime

# Get most recent gauge reading (updated hourly by USGS)
latest = RasUsgsRealTime.get_latest_value(
    site_no="01646500",
    parameter="flow"
)

print(f"Latest reading: {latest['value']:.0f} cfs at {latest['datetime']}")

# Get recent data for trend analysis
recent_data = RasUsgsRealTime.get_recent_data(
    site_no="01646500",
    hours=24,
    parameter="flow"
)

# Incrementally update cache with only new records
RasUsgsRealTime.refresh_data(
    site_no="01646500",
    parameter="flow",
    max_age_hours=1  # Only fetch if cache older than 1 hour
)

# Detect threshold crossing (flood stage)
is_flooding = RasUsgsRealTime.detect_threshold_crossing(
    site_no="01646500",
    threshold=50000,  # cfs
    parameter="flow"
)

if is_flooding:
    print("ALERT: Gauge exceeded flood threshold")

# Detect rapid change (flash flood conditions)
rapid_rise = RasUsgsRealTime.detect_rapid_change(
    site_no="01646500",
    rate_threshold=5000,  # cfs per hour
    window_hours=3,
    parameter="flow"
)

# Continuous monitoring with callback
def alert_callback(site_no, value, threshold):
    print(f"ALERT: {site_no} exceeded {threshold}: {value:.0f} cfs")
    # Trigger HEC-RAS model execution, send notification, etc.

RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=50000,
    callback=alert_callback,
    interval_minutes=15,  # Check every 15 minutes
    parameter="flow"
)
```

**Use cases**:
- Automated model triggering when flow exceeds threshold
- Early warning systems for flood response
- Real-time boundary condition updates
- Operational forecasting workflows

**Caching**: Automatic cache management prevents redundant API calls. Configurable max age.

### Stage 8: Gauge Catalog Generation (v0.89.0+)

Create standardized "USGS Gauge Data" folder with catalog and historical data:

```python
from ras_commander.usgs import catalog

# Generate complete gauge catalog (one command)
summary = catalog.generate_gauge_catalog(
    project_folder=r"C:\Projects\MyModel",
    buffer_miles=10.0,
    start_date="2020-01-01",
    end_date="2023-12-31",
    show_progress=True  # Show tqdm progress bars
)

print(f"Catalog Summary:")
print(f"  Gauges found: {summary['total_gauges']}")
print(f"  Successful downloads: {summary['successful']}")
print(f"  Failed: {summary['failed']}")

# Load gauge catalog
catalog_df = catalog.load_gauge_catalog(
    project_folder=r"C:\Projects\MyModel"
)

print(f"Catalog contains {len(catalog_df)} gauges")

# Load historical data for specific gauge
flow_data = catalog.load_gauge_data(
    project_folder=r"C:\Projects\MyModel",
    site_no="01646500",
    parameter="flow"
)

# Get path to gauge folder
gauge_folder = catalog.get_gauge_folder(
    project_folder=r"C:\Projects\MyModel",
    site_no="01646500"
)

# Update existing catalog with latest data
catalog.update_gauge_catalog(
    project_folder=r"C:\Projects\MyModel",
    end_date="2024-12-31"  # Extend to new end date
)
```

**Folder structure**:
```
project_folder/
  USGS Gauge Data/
    gauge_catalog.csv           # Master catalog (site_id, name, lat/lon, drainage, etc.)
    gauge_locations.geojson     # Spatial data for mapping
    README.md                   # Documentation
    USGS-{site_id}/             # One folder per gauge
      metadata.json             # Gauge metadata
      historical_flow.csv       # Historical flow data
      historical_stage.csv      # Historical stage data (if available)
      data_availability.json    # Data availability summary
```

**Benefits**:
- One-command gauge discovery and download
- Standard project organization (similar to precipitation module)
- Enables engineering review of gauge data
- Supports reproducible workflows

### Stage 9: Model Validation

Assess model performance against observed data:

```python
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import metrics, visualization

# Extract modeled results
modeled_df = HdfResultsXsec.get_xsec_timeseries(
    plan_number="01",
    river="Potomac River",
    reach="Main",
    rs="100.0"
)

# Align observed and modeled data
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=flow_data,
    modeled=modeled_df,
    method='nearest'
)

# Calculate all validation metrics
all_metrics = metrics.calculate_all_metrics(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    observed_times=observed_aligned['datetime'],
    modeled_times=modeled_aligned['datetime'],
    timestep_hours=1
)

# Print validation summary
print("Validation Metrics:")
print(f"  NSE:              {all_metrics['nse']:.3f}")
print(f"  KGE:              {all_metrics['kge']:.3f}")
print(f"  Correlation:      {all_metrics['correlation']:.3f}")
print(f"  RMSE:             {all_metrics['rmse']:,.0f} cfs")
print(f"  Peak Error:       {all_metrics['peak_error_pct']:.1f}%")
print(f"  Timing Error:     {all_metrics['timing_error_hours']:.1f} hours")
print(f"  Volume Bias:      {all_metrics['volume_bias_pct']:.1f}%")

# Generate time series comparison plot
fig = visualization.plot_timeseries_comparison(
    observed=observed_aligned,
    modeled=modeled_aligned,
    title="Potomac River at Little Falls - Model Validation",
    metrics=all_metrics,
    output_file="validation_timeseries.png"
)

# Generate scatter plot
fig = visualization.plot_scatter_comparison(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    title="Observed vs Modeled Flow",
    metrics=all_metrics,
    output_file="validation_scatter.png"
)

# Generate residual diagnostics (4-panel)
fig = visualization.plot_residuals(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    observed_times=observed_aligned['datetime'],
    output_file="validation_residuals.png"
)

# Flow duration curve
fig = visualization.plot_flow_duration_curve(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    output_file="validation_fdc.png"
)
```

**Validation metrics**:
- **NSE** (Nash-Sutcliffe Efficiency): −∞ to 1 (perfect = 1)
- **KGE** (Kling-Gupta Efficiency): −∞ to 1 (perfect = 1)
- **Peak Error**: Magnitude and timing of peak flows
- **Volume Bias**: Total volume error over simulation period

**See**: [reference/validation.md](reference/validation.md) for detailed interpretation guidelines.

## Data Caching and File I/O

Save and load USGS data locally:

```python
from ras_commander.usgs import RasUsgsFileIo

# Cache gauge data to CSV
RasUsgsFileIo.cache_gauge_data(
    data=flow_data,
    site_no="01646500",
    parameter="flow",
    output_dir=r"C:\Projects\MyModel\gauge_data"
)

# Load cached data
cached_data = RasUsgsFileIo.load_cached_gauge_data(
    site_no="01646500",
    parameter="flow",
    data_dir=r"C:\Projects\MyModel\gauge_data"
)

# Get or create gauge data directory
gauge_dir = RasUsgsFileIo.get_gauge_data_dir(
    project_folder=r"C:\Projects\MyModel"
)

# Export to HEC-DSS (if pydsstools available)
RasUsgsFileIo.export_to_dss(
    data=flow_data,
    dss_file=r"C:\Projects\MyModel\boundaries.dss",
    pathname="/POTOMAC/LITTLE FALLS/FLOW//1HOUR/USGS/"
)
```

**Cache format**: Standardized CSV with ISO 8601 timestamps and metadata header.

## Dependencies

The USGS module uses **lazy loading** for optional dependencies:

**Required** (always available):
- `pandas` - Data handling
- `geopandas` - Spatial queries
- `requests` - NWIS API access

**Optional** (lazy-loaded):
- `dataretrieval` - USGS NWIS Python client (**recommended**)
  - Install: `pip install dataretrieval`
  - Methods check availability on first use
  - Helpful error message with installation instructions if missing

**Check dependencies**:
```python
from ras_commander.usgs import check_dependencies
deps = check_dependencies()
print(deps)  # {'pandas': True, 'geopandas': True, 'dataretrieval': True/False}
```

## Common Patterns

### Pattern 1: Operational Forecasting

Trigger HEC-RAS model when gauge exceeds threshold:

```python
from ras_commander import RasCmdr
from ras_commander.usgs import RasUsgsRealTime

def run_model_if_threshold_exceeded(site_no, value, threshold):
    """Callback to trigger model execution"""
    print(f"Threshold exceeded: {value:.0f} cfs > {threshold:.0f} cfs")

    # Update boundary conditions with latest data
    # ... (generate BC table from recent data)

    # Execute HEC-RAS plan
    RasCmdr.compute_plan(
        plan_number="01",
        dest_folder=r"C:\Projects\MyModel\runs\forecast_run"
    )

    print("Forecast model execution complete")

# Monitor gauge and trigger model
RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=50000,  # cfs
    callback=run_model_if_threshold_exceeded,
    interval_minutes=15
)
```

### Pattern 2: Multi-Gauge Validation

Validate model at multiple gauge locations:

```python
from ras_commander.usgs import RasUsgsCore, metrics, visualization

gauge_sites = ["01646500", "01647500", "01648000"]
validation_results = {}

for site_no in gauge_sites:
    # Retrieve observed data
    observed = RasUsgsCore.retrieve_flow_data(
        site_no=site_no,
        start_date="2023-09-01",
        end_date="2023-09-15"
    )

    # Extract modeled results (match to appropriate XS)
    # ... (use GaugeMatcher to find corresponding XS)

    # Calculate metrics
    all_metrics = metrics.calculate_all_metrics(observed, modeled)
    validation_results[site_no] = all_metrics

    # Generate plots
    visualization.plot_timeseries_comparison(
        observed, modeled,
        title=f"Validation: {site_no}",
        output_file=f"validation_{site_no}.png"
    )

# Summary report
print("\nMulti-Gauge Validation Summary:")
for site_no, metrics_dict in validation_results.items():
    print(f"{site_no}: NSE={metrics_dict['nse']:.3f}, KGE={metrics_dict['kge']:.3f}")
```

### Pattern 3: Historical Event Reconstruction

Reconstruct historical flood event with USGS boundary conditions:

```python
from ras_commander import init_ras_project, RasCmdr
from ras_commander.usgs import RasUsgsCore, RasUsgsBoundaryGeneration

# Initialize project
init_ras_project(r"C:\Projects\MyModel", "6.5")

# Retrieve historical event data
upstream_flow = RasUsgsCore.retrieve_flow_data(
    site_no="01646500",
    start_date="2011-09-05",  # Tropical Storm Lee
    end_date="2011-09-13",
    service='iv'
)

# Generate upstream BC
bc_upstream = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=upstream_flow,
    river="Potomac River",
    reach="Main",
    rs="100.0"
)

# Update unsteady file
RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=r"C:\Projects\MyModel\TS_Lee.u01",
    bc_table=bc_upstream,
    bc_line_number=15
)

# Execute model
RasCmdr.compute_plan(
    plan_number="01",
    dest_folder=r"C:\Projects\MyModel\runs\TS_Lee_2011"
)

print("Historical event reconstruction complete")
```

## Detailed References

- **Complete end-to-end workflow**: See [reference/workflow.md](reference/workflow.md)
- **Validation metrics and interpretation**: See [reference/validation.md](reference/validation.md)
- **Module documentation**: See `ras_commander/usgs/CLAUDE.md`
- **Subagent for complex tasks**: See `.claude/subagents/usgs-integrator/SUBAGENT.md`

## Example Scripts

- **Complete workflow**: See [examples/complete-workflow.py](examples/complete-workflow.py)
- **Real-time monitoring**: See [examples/real-time.py](examples/real-time.py)

## Example Notebooks

Complete demonstrations in `examples/`:
- `29_usgs_gauge_data_integration.ipynb` - Complete workflow (discovery → validation)
- `30_usgs_real_time_monitoring.ipynb` - Real-time monitoring examples
- `31_bc_generation_from_live_gauge.ipynb` - Boundary condition generation
- `32_model_validation_with_usgs.ipynb` - Model validation workflow
- `33_gauge_catalog_generation.ipynb` - Catalog generation (v0.89.0+)

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Boundary conditions in .u## files reviewable in HEC-RAS GUI
- **Visual Outputs**: Time series plots and validation metrics for domain expert review
- **Code Audit Trails**: All functions use @log_call decorators for execution tracking

### USGS Service Compliance
- Respectful API usage with rate limiting (1 req/sec default)
- Proper parameter codes (00060 = flow, 00065 = stage)
- Service timeout handling and retry logic

### Data Quality
- Automatic gap detection and reporting
- Data availability checks before processing
- Validation of resampled time series

## Troubleshooting

**Issue**: `ModuleNotFoundError: No module named 'dataretrieval'`
- **Solution**: Install dataretrieval: `pip install dataretrieval`

**Issue**: No gauges found in project bounds
- **Solution**: Increase buffer_miles parameter, check project coordinate system

**Issue**: Data gaps in USGS data
- **Solution**: Use `check_data_gaps()` to detect, `fill_data_gaps()` to interpolate

**Issue**: Boundary condition format invalid
- **Solution**: Verify HEC-RAS interval code, check fixed-width format with `validate_boundary_format()`

**Issue**: Poor validation metrics (NSE < 0.5)
- **Solution**: Check model calibration, verify boundary conditions, review gauge location

## See Also

- **HEC-RAS execution**: `.claude/skills/executing-hecras-plans/`
- **HDF results extraction**: `.claude/skills/extracting-hecras-results/`
- **Boundary condition utilities**: `ras_commander.RasUnsteady`
- **HDF extraction for validation**: `ras_commander.HdfResultsXsec`, `HdfResultsMesh`
