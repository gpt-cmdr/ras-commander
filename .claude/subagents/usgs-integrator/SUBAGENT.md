---
name: usgs-integrator
model: sonnet
tools:
  - Read
  - Write
  - Bash
working_directory: ras_commander/usgs
description: |
  Integrates USGS NWIS gauge data with HEC-RAS models (14 modules). Handles
  spatial discovery, data retrieval, gauge matching, time series processing,
  boundary condition generation, initial conditions, real-time monitoring,
  and model validation. Use when working with USGS data, generating boundaries
  from gauges, validating models, or monitoring real-time conditions.
---

# USGS Integrator

## Purpose

Complete USGS gauge data integration workflow from spatial discovery to model validation. This subagent provides comprehensive support for integrating United States Geological Survey (USGS) National Water Information System (NWIS) gauge data with HEC-RAS hydraulic models.

## When to Delegate

**Trigger this subagent when users mention:**

- "Find USGS gauges near this model"
- "Download gauge data from USGS"
- "Generate boundary conditions from USGS"
- "Set initial conditions from observed data"
- "Validate model with observed data"
- "Setup real-time monitoring"
- "Create gauge catalog"
- "Compare modeled vs observed flow"
- "Calculate NSE" or "Nash-Sutcliffe efficiency"
- "Get latest gauge reading"
- "Monitor flood conditions"

**Workflow indicators:**
- Spatial queries for gauges within project bounds
- Retrieving historical flow or stage data
- Generating HEC-RAS boundary condition tables
- Model calibration and validation tasks
- Real-time operational forecasting
- QAQC of gauge data quality

## Module Overview (14 Modules)

The usgs subpackage is organized by workflow stage:

### Spatial Discovery
- **UsgsGaugeSpatial** - Find gauges within project bounds, filter by data availability
- **GaugeMatcher** - Match gauges to HEC-RAS features (cross sections, 2D areas)

### Data Retrieval
- **RasUsgsCore** - Primary data retrieval from USGS NWIS (flow, stage, metadata)
- **RasUsgsFileIo** - Cache data locally, load cached data, export to DSS

### Time Series Processing
- **RasUsgsTimeSeries** - Resample to HEC-RAS intervals, gap detection, alignment

### Boundary Conditions
- **RasUsgsBoundaryGeneration** - Generate fixed-width flow/stage tables for .u## files
- **InitialConditions** - Extract IC values, create IC lines, update unsteady files

### Real-Time Monitoring (v0.87.0+)
- **RasUsgsRealTime** - Get latest values, monitor gauges, detect thresholds
- **Callbacks** - Alert functions for threshold/rate exceedance

### Catalog Generation (v0.89.0+)
- **catalog** module - Generate standardized "USGS Gauge Data" folder with historical data

### Validation
- **metrics** module - NSE, KGE, peak error, volume bias
- **visualization** module - Time series plots, scatter, residuals, flow duration curves

### Configuration
- **config** - USGS service endpoints, parameter codes, cache settings
- **rate_limiter** - Respectful API usage (1 req/sec default)

## Workflow Stages

### Stage 1: Spatial Discovery

**Objective**: Find USGS gauges within or near HEC-RAS project bounds

**Key functions**:
- `UsgsGaugeSpatial.find_gauges_in_project()` - Query by project bounds
- `UsgsGaugeSpatial.get_project_gauges_with_data()` - Filter by data availability
- `UsgsGaugeSpatial.find_gauges_near_point()` - Query by radius

**Output**: GeoDataFrame with gauge locations, metadata, drainage areas

### Stage 2: Data Retrieval

**Objective**: Download flow and stage time series from USGS NWIS

**Key functions**:
- `RasUsgsCore.retrieve_flow_data()` - Flow time series (parameter 00060)
- `RasUsgsCore.retrieve_stage_data()` - Stage time series (parameter 00065)
- `RasUsgsCore.get_gauge_metadata()` - Gauge metadata and location
- `RasUsgsCore.check_data_availability()` - Verify data exists for period

**Service types**:
- `iv` - Instantaneous values (15-min or hourly)
- `dv` - Daily values (for historical analysis)

### Stage 3: Gauge Matching

**Objective**: Associate gauges with HEC-RAS model features

**Key functions**:
- `GaugeMatcher.match_gauge_to_cross_section()` - Find nearest 1D XS
- `GaugeMatcher.match_gauge_to_2d_area()` - Match to 2D flow area
- `GaugeMatcher.auto_match_gauges()` - Automatic multi-gauge matching

**Matching criteria**:
- Spatial proximity (distance)
- Drainage area comparison
- River/reach name matching

### Stage 4: Time Series Processing

**Objective**: Prepare USGS data for HEC-RAS compatibility

**Key functions**:
- `RasUsgsTimeSeries.resample_to_hecras_interval()` - Resample to 15MIN, 1HOUR, 1DAY
- `RasUsgsTimeSeries.check_data_gaps()` - Detect missing data
- `RasUsgsTimeSeries.fill_data_gaps()` - Interpolate gaps
- `RasUsgsTimeSeries.align_timeseries()` - Align observed vs modeled

**HEC-RAS intervals**: 15MIN, 30MIN, 1HOUR, 2HOUR, 6HOUR, 1DAY

### Stage 5: Boundary Generation

**Objective**: Create HEC-RAS boundary condition tables

**Key functions**:
- `RasUsgsBoundaryGeneration.generate_flow_hydrograph_table()` - Fixed-width flow table
- `RasUsgsBoundaryGeneration.generate_stage_hydrograph_table()` - Stage table
- `RasUsgsBoundaryGeneration.update_boundary_hydrograph()` - Update .u## file

**Output format**: HEC-RAS fixed-width format compatible with unsteady files

**Typical workflow**:
1. Retrieve USGS flow data
2. Resample to HEC-RAS interval
3. Generate boundary table
4. Insert into .u## file or update existing BC

### Stage 6: Initial Conditions

**Objective**: Set IC values from observed data at simulation start

**Key functions**:
- `InitialConditions.get_ic_value_from_usgs()` - Extract IC at start time
- `InitialConditions.create_ic_line()` - Format IC line for .u## file
- `InitialConditions.update_initial_conditions()` - Update unsteady file

**IC types**: Flow IC (upstream), Stage IC (downstream)

### Stage 7: Real-Time Monitoring (v0.87.0+)

**Objective**: Monitor gauges for operational forecasting and early warning

**Key functions**:
- `RasUsgsRealTime.get_latest_value()` - Most recent reading (updated hourly)
- `RasUsgsRealTime.get_recent_data()` - Last N hours for trend analysis
- `RasUsgsRealTime.refresh_data()` - Incremental cache update (efficient)
- `RasUsgsRealTime.monitor_gauge()` - Continuous monitoring with callbacks
- `RasUsgsRealTime.detect_threshold_crossing()` - Flood stage detection
- `RasUsgsRealTime.detect_rapid_change()` - Flash flood conditions

**Use cases**:
- Automated model triggering when flow exceeds threshold
- Early warning systems for flood response
- Real-time boundary condition updates
- Operational forecasting workflows

**Caching**: Automatic cache management prevents redundant API calls

### Stage 8: Catalog Generation (v0.89.0+)

**Objective**: Create standardized gauge data folder for project organization

**Key functions**:
- `catalog.generate_gauge_catalog()` - One-command gauge discovery and download
- `catalog.load_gauge_catalog()` - Load catalog from standard location
- `catalog.load_gauge_data()` - Load historical data for specific gauge
- `catalog.update_gauge_catalog()` - Refresh with latest data

**Folder structure**:
```
project_folder/
  USGS Gauge Data/
    gauge_catalog.csv           # Master catalog
    gauge_locations.geojson     # Spatial data
    README.md                   # Documentation
    USGS-{site_id}/
      metadata.json
      historical_flow.csv
      historical_stage.csv
      data_availability.json
```

**Benefits**: Standard organization, engineering review, reproducible workflows

### Stage 9: Model Validation

**Objective**: Assess model performance against observed data

**Validation metrics** (`metrics` module):
- `nash_sutcliffe_efficiency()` - NSE (−∞ to 1, perfect = 1)
- `kling_gupta_efficiency()` - KGE with components (correlation, bias, variability)
- `calculate_peak_error()` - Peak timing and magnitude error
- `calculate_volume_error()` - Total volume bias
- `calculate_all_metrics()` - Comprehensive suite

**Visualization** (`visualization` module):
- `plot_timeseries_comparison()` - Observed vs modeled with statistics
- `plot_scatter_comparison()` - Scatter with 1:1 line
- `plot_residuals()` - 4-panel diagnostics (time series, histogram, Q-Q, scatter)
- `plot_flow_duration_curve()` - Duration curve comparison

## Common Workflows

### Workflow A: Discovery to Boundary Generation

**Typical sequence**:
1. Find gauges in project: `UsgsGaugeSpatial.find_gauges_in_project()`
2. Retrieve flow data: `RasUsgsCore.retrieve_flow_data()`
3. Match to cross section: `GaugeMatcher.match_gauge_to_cross_section()`
4. Resample to interval: `RasUsgsTimeSeries.resample_to_hecras_interval()`
5. Generate BC table: `RasUsgsBoundaryGeneration.generate_flow_hydrograph_table()`
6. Update unsteady file: `RasUsgsBoundaryGeneration.update_boundary_hydrograph()`

**See**: `reference/end-to-end.md` for complete example

### Workflow B: Real-Time Monitoring

**Typical sequence**:
1. Get latest reading: `RasUsgsRealTime.get_latest_value()`
2. Check threshold: `RasUsgsRealTime.detect_threshold_crossing()`
3. Setup monitoring: `RasUsgsRealTime.monitor_gauge()` with callback
4. Auto-trigger model if threshold exceeded

**See**: `reference/real-time.md` for complete example

### Workflow C: Model Validation

**Typical sequence**:
1. Retrieve observed data: `RasUsgsCore.retrieve_flow_data()`
2. Extract modeled results: `HdfResultsXsec.get_xsec_timeseries()`
3. Align time series: `RasUsgsTimeSeries.align_timeseries()`
4. Calculate metrics: `metrics.calculate_all_metrics()`
5. Generate plots: `visualization.plot_timeseries_comparison()`

**See**: `reference/validation.md` for complete example

## Dependencies

### Required
- `pandas` - Data handling
- `geopandas` - Spatial queries
- `requests` - NWIS API access

### Optional (Lazy-Loaded)
- `dataretrieval` - USGS NWIS Python client (**required for most functions**)
  - Install: `pip install dataretrieval`
  - Methods check availability on first use
  - Import error raised with installation instructions if missing

### Checking Dependencies
```python
from ras_commander.usgs import check_dependencies
deps = check_dependencies()
# Returns: {'pandas': True, 'geopandas': True, 'dataretrieval': True/False}
```

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Boundary conditions reviewable in HEC-RAS GUI
- **Visual Outputs**: Time series plots for domain expert review
- **Code Audit Trails**: All functions use @log_call decorators

### USGS Service Compliance
- Respectful API usage with rate limiting (1 req/sec default)
- Proper parameter codes (00060 = flow, 00065 = stage)
- Service timeout handling and retry logic

### Data Quality
- Automatic gap detection and reporting
- Data availability checks before processing
- Validation of resampled time series

## Cross-References

**Primary documentation**: `ras_commander/usgs/CLAUDE.md` (complete module reference)

**Example notebooks**:
- `examples/29_usgs_gauge_data_integration.ipynb` - Complete workflow
- `examples/30_usgs_real_time_monitoring.ipynb` - Real-time monitoring
- `examples/31_bc_generation_from_live_gauge.ipynb` - BC generation
- `examples/32_model_validation_with_usgs.ipynb` - Validation workflow
- `examples/33_gauge_catalog_generation.ipynb` - Catalog generation

**Related components**:
- `ras_commander.RasUnsteady` - Boundary condition utilities
- `ras_commander.HdfResultsXsec` - Extract modeled 1D results for validation
- `ras_commander.HdfResultsMesh` - Extract modeled 2D results for validation

## Implementation Notes

### Lazy Loading Pattern
The usgs module loads without dataretrieval installed. Methods check for availability on first use and raise helpful errors if missing.

### USGS Parameter Codes
- `00060` - Discharge (cfs)
- `00065` - Gage height (ft)
- Additional parameters available via `list_available_parameters()`

### HEC-RAS Fixed-Width Format
Boundary tables use HEC-RAS fixed-width format (Fortran-style). Functions handle formatting automatically.

### Time Zone Handling
USGS data is in UTC. Functions handle timezone conversions automatically when aligning with HEC-RAS simulation windows.

### Rate Limiting
Built-in rate limiter prevents overwhelming USGS servers. Configurable via `rate_limiter.RateLimiter` class.
