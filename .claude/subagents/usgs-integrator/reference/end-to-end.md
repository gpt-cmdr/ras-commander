# End-to-End USGS Integration Workflow

This document demonstrates a complete workflow from spatial discovery to model validation using the ras_commander.usgs subpackage.

## Workflow Overview

**Complete sequence**:
1. Spatial Discovery - Find gauges in project area
2. Data Retrieval - Download flow and stage data from USGS
3. Gauge Matching - Associate gauges with HEC-RAS features
4. Time Series Processing - Resample to HEC-RAS intervals
5. Initial Conditions - Set IC from observed data
6. Boundary Generation - Create BC tables for unsteady file
7. Model Execution - Run HEC-RAS with USGS-derived boundaries
8. Results Extraction - Extract modeled time series
9. Validation - Calculate metrics and generate plots
10. Catalog Generation - Create standardized gauge folder

## Step-by-Step Example

### 1. Project Initialization

```python
from pathlib import Path
from ras_commander import init_ras_project, ras, RasCmdr, RasExamples
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import (
    UsgsGaugeSpatial, RasUsgsCore, GaugeMatcher, RasUsgsTimeSeries,
    RasUsgsBoundaryGeneration, InitialConditions, catalog,
    metrics, visualization, check_dependencies
)
from datetime import datetime
import pandas as pd

# Check dependencies first
deps = check_dependencies()
if not deps['dataretrieval']:
    raise ImportError("dataretrieval required: pip install dataretrieval")

# Extract example project
project_path = RasExamples.extract_project("Balde Eagle Creek")
init_ras_project(project_path, "6.5")

print(f"Project: {ras.project_name}")
print(f"Plans: {len(ras.plan_df)}")
```

### 2. Spatial Discovery

Find USGS gauges within project bounds with 5-mile buffer:

```python
# Find gauges in project area
gauges_gdf = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder=project_path,
    buffer_miles=5.0
)

print(f"Found {len(gauges_gdf)} USGS stream gauges")
print("\nGauges:")
for idx, row in gauges_gdf.iterrows():
    site_id = row['monitoring_location_id']
    name = row['monitoring_location_name']
    drainage = row.get('drain_area_va', 'N/A')
    print(f"  {site_id}: {name} (DA: {drainage} sq mi)")
```

**Alternative**: Query by bounding box:

```python
# Manual bounding box (west, south, east, north)
gauges_gdf = UsgsGaugeSpatial.find_gauges_in_bbox(
    bbox=[-77.60, 40.90, -77.30, 41.15],
    site_type='ST'  # Stream sites only
)
```

### 3. Data Retrieval

Retrieve historical flow data for target event:

```python
# Define event period (Tropical Storm Lee, September 2011)
event_start = datetime(2011, 9, 5, 0, 0, 0)
event_end = datetime(2011, 9, 13, 0, 0, 0)

# Select upstream gauge for boundary condition
upstream_site = "01547200"  # Bald Eagle Creek below Spring Creek at Milesburg, PA

# Retrieve flow data (try instantaneous, fallback to daily)
flow_df = RasUsgsCore.retrieve_flow_data(
    site_no=upstream_site,
    start_date=event_start.strftime('%Y-%m-%d'),
    end_date=event_end.strftime('%Y-%m-%d'),
    service='iv'  # Instantaneous values
)

# If no instantaneous data available
if flow_df is None or len(flow_df) == 0:
    print("No instantaneous data available. Retrieving daily values...")
    flow_df = RasUsgsCore.retrieve_flow_data(
        site_no=upstream_site,
        start_date=event_start.strftime('%Y-%m-%d'),
        end_date=event_end.strftime('%Y-%m-%d'),
        service='dv'  # Daily values
    )

print(f"Retrieved {len(flow_df)} observations")
print(f"Peak flow: {flow_df['value'].max():.0f} cfs")
```

**Retrieve stage data** (for initial conditions):

```python
stage_df = RasUsgsCore.retrieve_stage_data(
    site_no=upstream_site,
    start_date=event_start.strftime('%Y-%m-%d'),
    end_date=event_end.strftime('%Y-%m-%d'),
    service='iv'
)

if stage_df is not None:
    print(f"Stage range: {stage_df['value'].min():.2f} to {stage_df['value'].max():.2f} ft")
```

### 4. Gauge Matching

Match gauge to nearest cross section:

```python
# Auto-match gauges to model features
matches_df = GaugeMatcher.auto_match_gauges(
    gauges_gdf=gauges_gdf,
    project_folder=project_path
)

print("\nGauge-to-Model Matches:")
for idx, match in matches_df.iterrows():
    print(f"  {match['site_id']}: {match['river']}/{match['reach']}/RS {match['station']}")
    print(f"    Distance: {match['distance_m']:.0f} m, Confidence: {match['confidence']}")
```

**Manual matching** if needed:

```python
# Match specific gauge to known cross section
upstream_match = {
    'site_id': upstream_site,
    'river': 'Bald Eagle Cr.',
    'reach': 'Lock Haven',
    'station': 137520,  # River station in model
    'use': 'upstream_bc'
}
```

### 5. Time Series Processing

Resample USGS data to match HEC-RAS boundary condition interval:

```python
# Check existing BC interval from project
bc_interval = ras.boundaries_df.iloc[0]['Interval']  # e.g., "1HOUR"
print(f"HEC-RAS BC interval: {bc_interval}")

# Resample flow data to HEC-RAS interval
flow_resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    flow_df,
    interval=bc_interval  # "15MIN", "1HOUR", etc.
)

print(f"Original: {len(flow_df)} points")
print(f"Resampled: {len(flow_resampled)} points")

# Check for data gaps
gaps = RasUsgsTimeSeries.check_data_gaps(flow_resampled, interval=bc_interval)
if len(gaps) > 0:
    print(f"Warning: {len(gaps)} data gaps detected")
    for gap in gaps:
        print(f"  Gap: {gap['start']} to {gap['end']} ({gap['duration']})")
```

### 6. Initial Conditions

Extract initial condition value from USGS data at simulation start:

```python
# Define simulation start time
simulation_start = datetime(2011, 9, 6, 0, 0, 0)

# Get IC value from USGS data
ic_value, ic_time = InitialConditions.get_ic_value_from_usgs(
    gauge_data=flow_df,
    target_time=simulation_start,
    parameter='flow'
)

print(f"Initial Condition at {simulation_start}:")
print(f"  Flow: {ic_value:.0f} cfs (from {ic_time})")

# Create IC line for unsteady file
ic_line = InitialConditions.create_ic_line(
    ic_type='flow',
    river=upstream_match['river'],
    reach=upstream_match['reach'],
    station=upstream_match['station'],
    value=ic_value
)

print(f"IC Line: {ic_line}")
```

### 7. Boundary Generation

Generate HEC-RAS fixed-width boundary condition table:

```python
# Generate flow hydrograph table
bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=flow_resampled,
    river=upstream_match['river'],
    reach=upstream_match['reach'],
    rs=upstream_match['station']
)

print(f"Generated BC table: {len(bc_table.splitlines())} lines")
print("\nFirst few lines:")
print('\n'.join(bc_table.splitlines()[:10]))

# Update unsteady file with new boundary condition
unsteady_file = project_path / f"{ras.project_name}.u01"

# Option A: Update existing BC (if line number known)
RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=unsteady_file,
    bc_table=bc_table,
    bc_line_number=15  # Line number of existing BC in .u## file
)

# Option B: Append as new BC (manual insertion required)
output_file = project_path / f"usgs_bc_{upstream_site}.txt"
with open(output_file, 'w') as f:
    f.write(bc_table)
print(f"BC table saved to: {output_file}")
```

### 8. Model Execution

Run HEC-RAS with updated boundary conditions:

```python
# Compute plan
print("Running HEC-RAS simulation...")
RasCmdr.compute_plan(
    plan_number="01",
    clear_geompre=True,
    num_cores=4
)

print("Simulation complete")

# Verify HDF results exist
hdf_file = project_path / f"{ras.project_name}.p01.hdf"
if hdf_file.exists():
    print(f"HDF results: {hdf_file}")
else:
    print("Warning: HDF results not found")
```

### 9. Results Extraction

Extract modeled time series for comparison with USGS data:

```python
# Extract modeled flow at validation location (downstream gauge)
downstream_site = "01548010"  # Bald Eagle Creek near Mill Hall, PA

# Get modeled results at cross section near downstream gauge
modeled_df = HdfResultsXsec.get_xsec_timeseries(
    plan_number="01",
    river="Bald Eagle Cr.",
    reach="Lock Haven",
    rs="123456"  # Station near downstream gauge
)

# Extract flow from results
modeled_flow = modeled_df['Flow'].to_frame()
modeled_flow.columns = ['value']
modeled_flow = modeled_flow.reset_index()
modeled_flow.rename(columns={'index': 'datetime'}, inplace=True)

print(f"Modeled results: {len(modeled_flow)} timesteps")
```

### 10. Model Validation

Compare modeled results with observed downstream gauge data:

```python
# Retrieve observed data from downstream gauge
observed_df = RasUsgsCore.retrieve_flow_data(
    site_no=downstream_site,
    start_date=event_start.strftime('%Y-%m-%d'),
    end_date=event_end.strftime('%Y-%m-%d'),
    service='iv'
)

# Align time series (handle different intervals)
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=observed_df,
    modeled=modeled_flow,
    method='nearest'  # or 'interpolate'
)

print(f"Aligned observations: {len(observed_aligned)}")

# Calculate all validation metrics
all_metrics = metrics.calculate_all_metrics(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value']
)

print("\nValidation Metrics:")
print(f"  NSE:        {all_metrics['nse']:.3f}")
print(f"  KGE:        {all_metrics['kge']:.3f}")
print(f"  Peak Error: {all_metrics['peak_error_pct']:.1f}%")
print(f"  Volume Bias: {all_metrics['volume_bias_pct']:.1f}%")

# Generate time series comparison plot
fig = visualization.plot_timeseries_comparison(
    observed=observed_aligned,
    modeled=modeled_aligned,
    title=f"USGS-{downstream_site} Validation",
    metrics=all_metrics,
    output_file=project_path / "validation_timeseries.png"
)

# Generate residual diagnostics
fig_residuals = visualization.plot_residuals(
    observed=observed_aligned['value'],
    modeled=modeled_aligned['value'],
    output_file=project_path / "validation_residuals.png"
)

print("Validation plots saved")
```

### 11. Catalog Generation

Create standardized gauge data folder for project organization:

```python
# Generate gauge catalog (one-command discovery and download)
catalog_info = catalog.generate_gauge_catalog(
    project_folder=project_path,
    buffer_miles=10.0,
    start_date="2010-01-01",
    end_date="2023-12-31",
    parameters=['flow', 'stage'],
    progress_bar=True
)

print(f"\nGauge Catalog Generated:")
print(f"  Gauges: {catalog_info['gauge_count']}")
print(f"  Folder: {catalog_info['catalog_folder']}")
print(f"  Files downloaded: {catalog_info['files_downloaded']}")

# Load catalog for future use
catalog_df = catalog.load_gauge_catalog(project_path)
print(f"\nCatalog loaded: {len(catalog_df)} gauges")

# Load specific gauge data from catalog
gauge_flow = catalog.load_gauge_data(
    project_folder=project_path,
    site_id=upstream_site,
    parameter='flow'
)
print(f"Gauge data loaded: {len(gauge_flow)} records")
```

## Summary

This end-to-end workflow demonstrates:

1. **Spatial Discovery**: Finding gauges in project area
2. **Data Retrieval**: Downloading flow and stage from USGS NWIS
3. **Gauge Matching**: Associating gauges with model features
4. **Time Series Processing**: Resampling to HEC-RAS intervals
5. **Initial Conditions**: Extracting IC values from observations
6. **Boundary Generation**: Creating fixed-width BC tables
7. **Model Execution**: Running HEC-RAS with USGS boundaries
8. **Results Extraction**: Getting modeled time series from HDF
9. **Validation**: Calculating metrics and generating plots
10. **Catalog Generation**: Creating standardized project organization

## Key Takeaways

### Data Quality Checks
- Always check for data gaps before using USGS data
- Verify data availability for target period before processing
- Use `check_data_gaps()` to identify missing values

### Time Series Alignment
- USGS data is in UTC timezone
- Use `align_timeseries()` to handle different intervals
- Consider interpolation method based on data frequency

### Boundary Condition Format
- HEC-RAS uses fixed-width Fortran format
- Functions handle formatting automatically
- Always verify BC tables in HEC-RAS GUI before running

### Validation Best Practices
- Use multiple metrics (NSE, KGE, peak error)
- Generate visual diagnostics (time series, residuals)
- Document model performance in engineering reports

## Related Notebooks

- `examples/29_usgs_gauge_data_integration.ipynb` - Complete workflow example
- `examples/30_usgs_real_time_monitoring.ipynb` - Real-time monitoring
- `examples/31_bc_generation_from_live_gauge.ipynb` - BC generation details
- `examples/32_model_validation_with_usgs.ipynb` - Validation workflow
- `examples/33_gauge_catalog_generation.ipynb` - Catalog generation
