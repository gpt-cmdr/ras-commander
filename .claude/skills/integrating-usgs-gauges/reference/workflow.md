# Complete USGS Integration Workflow

This document demonstrates the complete end-to-end workflow for integrating USGS gauge data with HEC-RAS models, from initial spatial discovery through model execution and validation.

## Workflow Overview

The USGS integration workflow proceeds through 9 stages:

1. **Spatial Discovery** - Find gauges within project bounds
2. **Data Retrieval** - Download flow and stage time series from USGS NWIS
3. **Gauge Matching** - Associate gauges with HEC-RAS features
4. **Time Series Processing** - Resample and prepare data for HEC-RAS
5. **Boundary Generation** - Create HEC-RAS boundary condition tables
6. **Initial Conditions** - Set IC values from observed data
7. **Model Execution** - Run HEC-RAS with USGS boundaries
8. **Results Extraction** - Extract modeled time series from HDF
9. **Validation** - Calculate metrics and generate comparison plots

## Complete Example

This example demonstrates the entire workflow for a typical project:

```python
from pathlib import Path
from datetime import datetime
from ras_commander import init_ras_project, ras, RasCmdr
from ras_commander.hdf import HdfResultsXsec
from ras_commander.usgs import (
    UsgsGaugeSpatial,
    RasUsgsCore,
    GaugeMatcher,
    RasUsgsTimeSeries,
    RasUsgsBoundaryGeneration,
    InitialConditions,
    metrics,
    visualization,
    RasUsgsFileIo
)

# ==============================================================================
# PROJECT SETUP
# ==============================================================================

project_folder = r"C:\Projects\PotomacRiver"
project_name = "Potomac"
ras_version = "6.5"

# Initialize HEC-RAS project
init_ras_project(project_folder, ras_version)

print(f"Project initialized: {project_name}")
print(f"Plans available: {len(ras.plan_df)}")
print(f"Geometry files: {len(ras.geom_df)}")

# ==============================================================================
# STAGE 1: SPATIAL DISCOVERY
# ==============================================================================

print("\n" + "="*70)
print("STAGE 1: SPATIAL DISCOVERY")
print("="*70)

# Find all USGS gauges within 10 miles of project bounds
gauges_gdf = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder=project_folder,
    buffer_miles=10.0
)

print(f"\nFound {len(gauges_gdf)} USGS gauges within 10 miles")
print("\nGauge Inventory:")
print(gauges_gdf[['site_no', 'station_nm', 'drain_area_va']].to_string(index=False))

# Filter for gauges with data in our simulation period
sim_start = "2023-09-01"
sim_end = "2023-09-15"

gauges_with_data = UsgsGaugeSpatial.get_project_gauges_with_data(
    project_folder=project_folder,
    start_date=sim_start,
    end_date=sim_end,
    buffer_miles=10.0
)

print(f"\nGauges with data for {sim_start} to {sim_end}: {len(gauges_with_data)}")

# ==============================================================================
# STAGE 2: DATA RETRIEVAL
# ==============================================================================

print("\n" + "="*70)
print("STAGE 2: DATA RETRIEVAL")
print("="*70)

# Select primary gauge (Potomac River at Little Falls)
primary_gauge = "01646500"

# Check data availability first
available = RasUsgsCore.check_data_availability(
    site_no=primary_gauge,
    start_date=sim_start,
    end_date=sim_end,
    parameter='flow'
)

if available:
    print(f"\nData available for gauge {primary_gauge}")
else:
    print(f"\nWARNING: No data available for gauge {primary_gauge}")

# Retrieve flow data (instantaneous values)
print(f"\nRetrieving flow data from USGS NWIS...")
upstream_flow = RasUsgsCore.retrieve_flow_data(
    site_no=primary_gauge,
    start_date=sim_start,
    end_date=sim_end,
    service='iv'  # Instantaneous values (15-min or hourly)
)

print(f"Retrieved {len(upstream_flow)} observations")
print(f"Date range: {upstream_flow['datetime'].min()} to {upstream_flow['datetime'].max()}")
print(f"Flow range: {upstream_flow['value'].min():.0f} to {upstream_flow['value'].max():.0f} cfs")
print(f"Mean flow: {upstream_flow['value'].mean():.0f} cfs")

# Retrieve stage data for downstream boundary
downstream_gauge = "01647500"
downstream_stage = RasUsgsCore.retrieve_stage_data(
    site_no=downstream_gauge,
    start_date=sim_start,
    end_date=sim_end,
    service='iv'
)

print(f"\nRetrieved stage data: {len(downstream_stage)} observations")

# Get gauge metadata
metadata = RasUsgsCore.get_gauge_metadata(site_no=primary_gauge)
print(f"\nPrimary Gauge Metadata:")
print(f"  Station: {metadata['station_nm']}")
print(f"  Drainage area: {metadata['drain_area_va']:.1f} sq mi")
print(f"  Location: {metadata['dec_lat_va']:.4f}, {metadata['dec_long_va']:.4f}")

# Cache data locally for future use
gauge_data_dir = RasUsgsFileIo.get_gauge_data_dir(project_folder)
RasUsgsFileIo.cache_gauge_data(
    data=upstream_flow,
    site_no=primary_gauge,
    parameter="flow",
    output_dir=gauge_data_dir
)
print(f"\nData cached to: {gauge_data_dir}")

# ==============================================================================
# STAGE 3: GAUGE MATCHING
# ==============================================================================

print("\n" + "="*70)
print("STAGE 3: GAUGE MATCHING")
print("="*70)

# Automatically match all gauges to nearest HEC-RAS features
matches = GaugeMatcher.auto_match_gauges(
    gauges_gdf=gauges_gdf,
    project_folder=project_folder
)

print(f"\nGauge Matching Results:")
for idx, match in matches.iterrows():
    print(f"  {match['site_no']}: {match['matched_feature']} "
          f"(distance: {match['distance_ft']:.0f} ft, "
          f"confidence: {match['confidence']})")

# Get specific match for primary gauge
primary_match = matches[matches['site_no'] == primary_gauge].iloc[0]
print(f"\nPrimary Gauge Match:")
print(f"  River: {primary_match['river']}")
print(f"  Reach: {primary_match['reach']}")
print(f"  RS: {primary_match['rs']}")
print(f"  Distance: {primary_match['distance_ft']:.0f} ft")

# ==============================================================================
# STAGE 4: TIME SERIES PROCESSING
# ==============================================================================

print("\n" + "="*70)
print("STAGE 4: TIME SERIES PROCESSING")
print("="*70)

# Check for data gaps
gaps = RasUsgsTimeSeries.check_data_gaps(upstream_flow)
if gaps['has_gaps']:
    print(f"\nWARNING: {gaps['num_gaps']} gaps detected")
    print(f"Total gap duration: {gaps['total_gap_hours']:.1f} hours")
    print(f"Largest gap: {gaps['max_gap_hours']:.1f} hours")

    # Fill gaps if needed
    upstream_flow = RasUsgsTimeSeries.fill_data_gaps(
        upstream_flow,
        method='linear'
    )
    print("Gaps filled using linear interpolation")
else:
    print("\nNo data gaps detected")

# Resample to HEC-RAS interval (1 hour)
print("\nResampling to HEC-RAS interval (1HOUR)...")
upstream_resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    upstream_flow,
    interval="1HOUR"
)

print(f"Resampled to {len(upstream_resampled)} hourly values")

# Extract exact simulation period
upstream_sim = RasUsgsTimeSeries.extract_simulation_period(
    upstream_resampled,
    start_datetime=f"{sim_start} 00:00",
    end_datetime=f"{sim_end} 23:59"
)

print(f"Extracted simulation period: {len(upstream_sim)} values")

# ==============================================================================
# STAGE 5: BOUNDARY CONDITION GENERATION
# ==============================================================================

print("\n" + "="*70)
print("STAGE 5: BOUNDARY CONDITION GENERATION")
print("="*70)

# Generate upstream flow boundary table
print("\nGenerating upstream flow boundary table...")
bc_upstream = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=upstream_sim,
    river=primary_match['river'],
    reach=primary_match['reach'],
    rs=primary_match['rs']
)

print(f"Generated {len(bc_upstream)} lines of boundary table")

# Validate format
is_valid = RasUsgsBoundaryGeneration.validate_boundary_format(bc_upstream)
if is_valid:
    print("Boundary table format: VALID")
else:
    print("WARNING: Boundary table format INVALID")

# Generate downstream stage boundary
downstream_match = matches[matches['site_no'] == downstream_gauge].iloc[0]
downstream_resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    downstream_stage,
    interval="1HOUR"
)

bc_downstream = RasUsgsBoundaryGeneration.generate_stage_hydrograph_table(
    stage_data=downstream_resampled,
    river=downstream_match['river'],
    reach=downstream_match['reach'],
    rs=downstream_match['rs']
)

print(f"Generated downstream stage BC: {len(bc_downstream)} lines")

# Update unsteady file with boundaries
unsteady_file = ras.unsteady_df[ras.unsteady_df['plan_number'] == '01']['path'].iloc[0]

RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=str(unsteady_file),
    bc_table=bc_upstream,
    bc_line_number=15  # Upstream BC location in file
)

RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file=str(unsteady_file),
    bc_table=bc_downstream,
    bc_line_number=150  # Downstream BC location in file
)

print(f"\nBoundary conditions updated in: {unsteady_file.name}")

# ==============================================================================
# STAGE 6: INITIAL CONDITIONS
# ==============================================================================

print("\n" + "="*70)
print("STAGE 6: INITIAL CONDITIONS")
print("="*70)

# Get IC value at simulation start
ic_value = InitialConditions.get_ic_value_from_usgs(
    flow_data=upstream_sim,
    start_datetime=f"{sim_start} 00:00"
)

print(f"\nInitial flow at {sim_start} 00:00: {ic_value:.0f} cfs")

# Create IC line for unsteady file
ic_line = InitialConditions.create_ic_line(
    river=primary_match['river'],
    reach=primary_match['reach'],
    rs=primary_match['rs'],
    value=ic_value,
    ic_type='flow'
)

print(f"IC line generated: {ic_line[:50]}...")

# Update initial conditions in unsteady file
InitialConditions.update_initial_conditions(
    unsteady_file=str(unsteady_file),
    ic_line=ic_line,
    ic_line_number=10
)

print("Initial conditions updated in unsteady file")

# ==============================================================================
# STAGE 7: MODEL EXECUTION
# ==============================================================================

print("\n" + "="*70)
print("STAGE 7: MODEL EXECUTION")
print("="*70)

# Execute HEC-RAS plan
dest_folder = Path(project_folder) / "runs" / f"USGS_{sim_start}_{sim_end}"

print(f"\nExecuting HEC-RAS plan 01...")
print(f"Destination: {dest_folder}")

RasCmdr.compute_plan(
    plan_number="01",
    dest_folder=str(dest_folder),
    num_cores=4,
    overwrite_dest=True
)

print("Model execution complete")

# ==============================================================================
# STAGE 8: RESULTS EXTRACTION
# ==============================================================================

print("\n" + "="*70)
print("STAGE 8: RESULTS EXTRACTION")
print("="*70)

# Extract modeled time series at gauge location
print(f"\nExtracting modeled results at gauge location...")
modeled_df = HdfResultsXsec.get_xsec_timeseries(
    plan_number="01",
    river=primary_match['river'],
    reach=primary_match['reach'],
    rs=primary_match['rs'],
    dest_folder=str(dest_folder)
)

print(f"Extracted {len(modeled_df)} timesteps")
print(f"Modeled flow range: {modeled_df['Flow'].min():.0f} to {modeled_df['Flow'].max():.0f} cfs")

# ==============================================================================
# STAGE 9: VALIDATION
# ==============================================================================

print("\n" + "="*70)
print("STAGE 9: VALIDATION")
print("="*70)

# Align observed and modeled time series
print("\nAligning time series...")
observed_aligned, modeled_aligned = RasUsgsTimeSeries.align_timeseries(
    observed=upstream_sim,
    modeled=modeled_df,
    method='nearest'
)

print(f"Aligned to {len(observed_aligned)} common timesteps")

# Calculate all validation metrics
print("\nCalculating validation metrics...")
all_metrics = metrics.calculate_all_metrics(
    observed=observed_aligned['value'].values,
    modeled=modeled_aligned['Flow'].values,
    observed_times=observed_aligned['datetime'].values,
    modeled_times=modeled_aligned.index.values,
    timestep_hours=1
)

# Print validation summary
print("\n" + "="*70)
print("VALIDATION METRICS SUMMARY")
print("="*70)
print(f"Gauge: USGS-{primary_gauge} ({metadata['station_nm']})")
print(f"Period: {sim_start} to {sim_end}")
print(f"Observations: {len(observed_aligned)}")
print("\nGoodness-of-Fit Metrics:")
print(f"  NSE (Nash-Sutcliffe):     {all_metrics['nse']:.3f}")
print(f"  KGE (Kling-Gupta):        {all_metrics['kge']:.3f}")
print(f"  Correlation (r):          {all_metrics['correlation']:.3f}")
print("\nError Metrics:")
print(f"  RMSE:                     {all_metrics['rmse']:,.0f} cfs")
print(f"  MAE:                      {all_metrics['mae']:,.0f} cfs")
print(f"  Mean Bias:                {all_metrics['bias']:+,.0f} cfs")
print("\nPeak Performance:")
print(f"  Peak Error (magnitude):   {all_metrics['peak_error_pct']:+.1f}%")
print(f"  Timing Error:             {all_metrics['timing_error_hours']:+.1f} hours")
print("\nVolume Balance:")
print(f"  Volume Bias:              {all_metrics['volume_bias_pct']:+.1f}%")
print("="*70)

# Interpret results
if all_metrics['nse'] > 0.75:
    performance = "VERY GOOD"
elif all_metrics['nse'] > 0.65:
    performance = "GOOD"
elif all_metrics['nse'] > 0.50:
    performance = "SATISFACTORY"
else:
    performance = "UNSATISFACTORY - Further calibration required"

print(f"\nOverall Performance: {performance}")

# ==============================================================================
# VISUALIZATION
# ==============================================================================

print("\n" + "="*70)
print("GENERATING VALIDATION PLOTS")
print("="*70)

output_dir = Path(project_folder) / "validation_output"
output_dir.mkdir(exist_ok=True)

# Time series comparison
print("\nGenerating time series comparison plot...")
visualization.plot_timeseries_comparison(
    observed=observed_aligned,
    modeled=modeled_aligned,
    title=f"{metadata['station_nm']} - Model Validation",
    metrics=all_metrics,
    observed_label=f"USGS-{primary_gauge} Observed",
    modeled_label="HEC-RAS Modeled",
    ylabel="Discharge (cfs)",
    output_file=str(output_dir / "timeseries_comparison.png")
)

# Scatter plot
print("Generating scatter plot...")
visualization.plot_scatter_comparison(
    observed=observed_aligned['value'].values,
    modeled=modeled_aligned['Flow'].values,
    title="Observed vs Modeled Flow",
    metrics=all_metrics,
    output_file=str(output_dir / "scatter_comparison.png")
)

# Residual diagnostics (4-panel)
print("Generating residual diagnostics...")
visualization.plot_residuals(
    observed=observed_aligned['value'].values,
    modeled=modeled_aligned['Flow'].values,
    observed_times=observed_aligned['datetime'].values,
    output_file=str(output_dir / "residual_diagnostics.png")
)

# Flow duration curve
print("Generating flow duration curve...")
visualization.plot_flow_duration_curve(
    observed=observed_aligned['value'].values,
    modeled=modeled_aligned['Flow'].values,
    output_file=str(output_dir / "flow_duration_curve.png")
)

print(f"\nValidation plots saved to: {output_dir}")

# ==============================================================================
# WORKFLOW COMPLETE
# ==============================================================================

print("\n" + "="*70)
print("WORKFLOW COMPLETE")
print("="*70)
print(f"\nProject: {project_name}")
print(f"Simulation: {sim_start} to {sim_end}")
print(f"Primary Gauge: USGS-{primary_gauge}")
print(f"Model Performance: {performance}")
print(f"Output: {output_dir}")
print("\nNext steps:")
print("  - Review validation plots")
print("  - Check residual patterns for systematic errors")
print("  - If performance unsatisfactory, adjust calibration parameters")
print("  - Document validation results for project records")
```

## Workflow Variations

### Variation 1: Multiple Gauges

Extend workflow to validate at multiple gauge locations:

```python
gauge_sites = {
    "01646500": "upstream",
    "01647500": "midstream",
    "01648000": "downstream"
}

validation_results = {}

for site_no, location in gauge_sites.items():
    print(f"\nProcessing gauge: {site_no} ({location})")

    # Retrieve data
    observed = RasUsgsCore.retrieve_flow_data(site_no, sim_start, sim_end)

    # Match to HEC-RAS feature
    match = matches[matches['site_no'] == site_no].iloc[0]

    # Extract modeled results
    modeled = HdfResultsXsec.get_xsec_timeseries(
        "01", match['river'], match['reach'], match['rs']
    )

    # Calculate metrics
    all_metrics = metrics.calculate_all_metrics(observed, modeled)
    validation_results[site_no] = all_metrics

    # Generate plots
    visualization.plot_timeseries_comparison(
        observed, modeled,
        title=f"Validation: {location}",
        output_file=f"validation_{location}.png"
    )

# Summary table
print("\nMulti-Gauge Validation Summary:")
print(f"{'Gauge':<12} {'Location':<12} {'NSE':>8} {'KGE':>8} {'Peak Error':>12}")
print("-" * 60)
for site_no, location in gauge_sites.items():
    m = validation_results[site_no]
    print(f"{site_no:<12} {location:<12} {m['nse']:>8.3f} {m['kge']:>8.3f} {m['peak_error_pct']:>11.1f}%")
```

### Variation 2: Gauge Catalog Workflow

Use catalog generation for standardized organization:

```python
from ras_commander.usgs import catalog

# Generate complete gauge catalog (replaces stages 1-2)
print("Generating gauge catalog...")
summary = catalog.generate_gauge_catalog(
    project_folder=project_folder,
    buffer_miles=10.0,
    start_date=sim_start,
    end_date=sim_end,
    show_progress=True
)

print(f"Catalog generated: {summary['total_gauges']} gauges")

# Load catalog
catalog_df = catalog.load_gauge_catalog(project_folder)

# Load historical data for specific gauge
flow_data = catalog.load_gauge_data(
    project_folder=project_folder,
    site_no=primary_gauge,
    parameter="flow"
)

# Continue with stages 3-9 using catalog data
```

### Variation 3: Real-Time Operational Workflow

Use real-time monitoring for operational forecasting:

```python
from ras_commander.usgs import RasUsgsRealTime

def operational_forecast(site_no, value, threshold):
    """Triggered when gauge exceeds threshold"""
    print(f"Threshold exceeded: {value:.0f} cfs")

    # Get recent data for boundary conditions
    recent_data = RasUsgsRealTime.get_recent_data(
        site_no=site_no,
        hours=24,
        parameter="flow"
    )

    # Generate boundary conditions
    bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
        flow_data=recent_data,
        river="Potomac River",
        reach="Main",
        rs="100.0"
    )

    # Update unsteady file
    RasUsgsBoundaryGeneration.update_boundary_hydrograph(
        unsteady_file=unsteady_file,
        bc_table=bc_table,
        bc_line_number=15
    )

    # Execute forecast model
    RasCmdr.compute_plan(
        plan_number="01",
        dest_folder=r"C:\Projects\Forecasts\latest"
    )

    print("Forecast complete")

# Monitor gauge and trigger forecast
RasUsgsRealTime.monitor_gauge(
    site_no=primary_gauge,
    threshold=50000,  # cfs
    callback=operational_forecast,
    interval_minutes=15
)
```

## See Also

- **Validation metrics**: [validation.md](validation.md)
- **Main skill**: [../SKILL.md](../SKILL.md)
- **Module documentation**: `ras_commander/usgs/CLAUDE.md`
- **Subagent**: `.claude/subagents/usgs-integrator/SUBAGENT.md`
