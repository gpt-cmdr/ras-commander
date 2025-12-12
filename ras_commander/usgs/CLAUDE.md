# USGS Gauge Data Integration

This subpackage provides complete integration between USGS NWIS gauge data and HEC-RAS models. It covers the entire workflow from spatial discovery to boundary condition generation to model validation.

## Module Overview

The usgs subpackage contains 14 modules organized by workflow stage:

### Data Retrieval (core.py)

**RasUsgsCore** - Primary data retrieval interface:
- `retrieve_flow_data()` - Retrieve flow time series from USGS NWIS (instantaneous or daily)
- `retrieve_stage_data()` - Retrieve stage/elevation time series
- `get_gauge_metadata()` - Get gauge metadata (location, drainage area, station name)
- `check_data_availability()` - Check if data exists for a time period
- `list_available_parameters()` - List all parameters available at a gauge

**Service types**:
- `iv` - Instantaneous values (15-minute or hourly intervals)
- `dv` - Daily values (for historical analysis)

### Spatial Queries (spatial.py)

**UsgsGaugeSpatial** - Geospatial gauge discovery:
- `find_gauges_in_project()` - Query USGS gauges within HEC-RAS project bounds
- `get_project_gauges_with_data()` - Find gauges with available data for simulation period
- `find_gauges_near_point()` - Find gauges within radius of point
- `filter_active_gauges()` - Filter by active status and data availability

**Returns**: GeoDataFrames with gauge locations, metadata, and data availability.

### Gauge Matching (gauge_matching.py)

**GaugeMatcher** - Associate gauges with HEC-RAS features:
- `match_gauge_to_cross_section()` - Match gauge to nearest 1D cross section
- `match_gauge_to_2d_area()` - Match gauge to 2D flow area by spatial intersection
- `auto_match_gauges()` - Automatically match multiple gauges to model features
- `get_matching_confidence()` - Assess quality of gauge-to-feature match

**Matching criteria**:
- Spatial proximity (distance to cross section or 2D area)
- Drainage area comparison (gauge vs upstream area)
- River/reach name matching (when available)

### Time Series Processing (time_series.py)

**RasUsgsTimeSeries** - Time series alignment and quality control:
- `resample_to_hecras_interval()` - Resample to HEC-RAS intervals (15MIN, 1HOUR, etc.)
- `check_data_gaps()` - Detect and report missing data
- `fill_data_gaps()` - Interpolate or extrapolate missing values
- `align_timeseries()` - Align observed and modeled data for validation
- `extract_simulation_period()` - Extract data matching HEC-RAS simulation window

**HEC-RAS interval codes**:
- `15MIN` - 15-minute intervals
- `1HOUR` - Hourly intervals
- `1DAY` - Daily intervals

### Boundary Conditions (boundary_generation.py)

**RasUsgsBoundaryGeneration** - Generate HEC-RAS boundary condition files:
- `generate_flow_hydrograph_table()` - Create fixed-width flow table for .u## files
- `generate_stage_hydrograph_table()` - Create stage boundary condition table
- `update_boundary_hydrograph()` - Update existing boundary condition in unsteady file
- `validate_boundary_format()` - Verify HEC-RAS fixed-width format compliance

**Output format**: HEC-RAS fixed-width format compatible with .u## unsteady files.

**Example workflow**:
1. Retrieve USGS flow data
2. Resample to HEC-RAS interval
3. Generate boundary table
4. Insert into .u## file

### Initial Conditions (initial_conditions.py)

**InitialConditions** - Extract and format initial condition values:
- `create_ic_line()` - Generate properly formatted IC lines for .u## files
- `get_ic_value_from_usgs()` - Extract IC value from USGS data at simulation start
- `parse_initial_conditions()` - Parse existing IC lines from unsteady files
- `update_initial_conditions()` - Update IC values in unsteady file

**IC types**:
- Flow initial conditions (for upstream boundaries)
- Stage initial conditions (for downstream boundaries)

### Real-Time Monitoring (real_time.py)

**RasUsgsRealTime** - Real-time data access and monitoring (NEW v0.87.0+):
- `get_latest_value()` - Get most recent gauge reading (updated hourly by USGS)
- `get_recent_data()` - Retrieve last N hours of data for trend analysis
- `refresh_data()` - Incrementally update cache with only new records (efficient sync)
- `monitor_gauge()` - Continuous monitoring with periodic refresh and callbacks
- `detect_threshold_crossing()` - Detect when readings cross flood stage
- `detect_rapid_change()` - Detect flash flood conditions (rapid rise/recession)

**Use cases**:
- Operational forecasting workflows
- Automated model triggering based on gauge thresholds
- Early warning systems for flood response
- Real-time boundary condition updates

**Caching**: Automatic cache management with configurable max age prevents redundant API calls.

**Callbacks**: Custom alert functions triggered on threshold or rate exceedance.

### Gauge Catalog Generation (catalog.py)

**Catalog generation** - Standardized project organization (NEW v0.89.0+):
- `generate_gauge_catalog()` - Create "USGS Gauge Data" folder with catalog and historical data
- `load_gauge_catalog()` - Load gauge catalog from standard project location
- `load_gauge_data()` - Load historical data for specific gauge (flow or stage)
- `get_gauge_folder()` - Get path to gauge folder in standard location
- `update_gauge_catalog()` - Refresh existing catalog with latest data

**Folder structure**:
```
project_folder/
  USGS Gauge Data/
    gauge_catalog.csv           # Master catalog (site_id, name, lat/lon, drainage area, etc.)
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
- Standard project organization
- Enables engineering review of gauge data
- Supports reproducible workflows

### Validation Metrics (metrics.py)

**Performance metrics** - Model validation statistics:
- `nash_sutcliffe_efficiency()` - NSE metric (−∞ to 1, perfect = 1)
- `kling_gupta_efficiency()` - KGE metric with components (correlation, bias, variability)
- `calculate_peak_error()` - Peak flow/stage error and timing offset
- `calculate_volume_error()` - Total volume bias
- `calculate_all_metrics()` - Comprehensive suite of validation metrics

**Returns**: Dictionary with all metrics for model validation reporting.

### Visualization (visualization.py)

**Publication-quality plots**:
- `plot_timeseries_comparison()` - Observed vs modeled time series with statistics
- `plot_scatter_comparison()` - Scatter plots with 1:1 line and regression
- `plot_residuals()` - 4-panel residual diagnostics (time series, histogram, Q-Q, scatter)
- `plot_flow_duration_curve()` - Compare flow duration curves (observed vs modeled)

**Output**: Matplotlib figures suitable for technical reports.

### File I/O (file_io.py)

**RasUsgsFileIo** - Data caching and persistence:
- `cache_gauge_data()` - Save USGS data to standardized CSV format with metadata
- `load_cached_gauge_data()` - Load cached data with metadata validation
- `get_gauge_data_dir()` - Create gauge_data/ directory structure
- `export_to_dss()` - Export time series to HEC-DSS format (if pydsstools available)

**Cache format**: CSV with ISO 8601 timestamps and metadata header.

### Configuration (config.py)

**USGS service configuration**:
- `USGS_BASE_URL` - NWIS web service endpoint
- `DEFAULT_PARAMETERS` - Parameter codes (flow: 00060, stage: 00065)
- `SERVICE_TIMEOUT` - API request timeout settings
- `CACHE_SETTINGS` - Cache expiration and refresh policies

### Rate Limiting (rate_limiter.py)

**API rate limiting** - Respectful USGS service usage (NEW):
- `RateLimiter` class - Enforces delays between API requests
- Configurable requests per second (default: 1 req/sec)
- Prevents overwhelming USGS NWIS servers
- Thread-safe for parallel workflows

## Complete Workflow

A typical USGS integration workflow proceeds through these stages:

### 1. Spatial Discovery
```python
from ras_commander.usgs import UsgsGaugeSpatial

# Find all gauges in project bounds
gauges = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder="C:/Projects/MyModel",
    buffer_miles=5.0
)
```

### 2. Data Retrieval
```python
from ras_commander.usgs import RasUsgsCore

# Retrieve historical flow data
flow_data = RasUsgsCore.retrieve_flow_data(
    site_no="01646500",
    start_date="2023-01-01",
    end_date="2023-12-31"
)
```

### 3. Gauge Matching
```python
from ras_commander.usgs import GaugeMatcher

# Match gauges to cross sections
matches = GaugeMatcher.auto_match_gauges(
    gauges_gdf=gauges,
    project_folder="C:/Projects/MyModel"
)
```

### 4. Time Series Processing
```python
from ras_commander.usgs import RasUsgsTimeSeries

# Resample to HEC-RAS interval
resampled = RasUsgsTimeSeries.resample_to_hecras_interval(
    flow_data,
    interval="15MIN"
)
```

### 5. Boundary Generation
```python
from ras_commander.usgs import RasUsgsBoundaryGeneration

# Generate boundary condition table
bc_table = RasUsgsBoundaryGeneration.generate_flow_hydrograph_table(
    flow_data=resampled,
    river="Potomac River",
    reach="Main",
    rs="100.0"
)

# Update unsteady file
RasUsgsBoundaryGeneration.update_boundary_hydrograph(
    unsteady_file="MyPlan.u01",
    bc_table=bc_table,
    bc_line_number=15
)
```

### 6. Model Validation
```python
from ras_commander.usgs import metrics, visualization

# Extract modeled results
modeled = HdfResultsXsec.get_xsec_timeseries("01", river="...", reach="...")

# Calculate validation metrics
all_metrics = metrics.calculate_all_metrics(
    observed=flow_data,
    modeled=modeled
)

# Generate comparison plots
visualization.plot_timeseries_comparison(
    observed=flow_data,
    modeled=modeled,
    title="Potomac River at Little Falls",
    metrics=all_metrics
)
```

### 7. Catalog Generation (Optional)
```python
from ras_commander.usgs import catalog

# Generate standardized gauge catalog
catalog.generate_gauge_catalog(
    project_folder="C:/Projects/MyModel",
    buffer_miles=10.0,
    start_date="2020-01-01",
    end_date="2023-12-31"
)
```

## Real-Time Workflows (v0.87.0+)

For operational forecasting and monitoring:

```python
from ras_commander.usgs import RasUsgsRealTime

# Get latest gauge reading
latest = RasUsgsRealTime.get_latest_value(site_no="01646500", parameter="flow")

# Detect flood conditions
is_flooding = RasUsgsRealTime.detect_threshold_crossing(
    site_no="01646500",
    threshold=50000,  # cfs
    parameter="flow"
)

# Continuous monitoring with callback
def alert_callback(site_no, value, threshold):
    print(f"ALERT: {site_no} exceeded {threshold}: {value}")

RasUsgsRealTime.monitor_gauge(
    site_no="01646500",
    threshold=50000,
    callback=alert_callback,
    interval_minutes=15
)
```

## Dependencies

The usgs subpackage uses **lazy loading** for the dataretrieval dependency:

**Required**:
- pandas
- geopandas (for spatial queries)
- requests (for NWIS API access)

**Optional (lazy-loaded)**:
- `dataretrieval` - USGS NWIS Python client (pip install dataretrieval)
  - Methods check for availability on first use
  - Import error raised with installation instructions if missing

**Installation**:
```bash
pip install dataretrieval
```

## Example Notebooks

Complete workflow demonstrations:

- `examples/29_usgs_gauge_data_integration.ipynb` - Complete workflow (discovery → validation)
- `examples/30_usgs_real_time_monitoring.ipynb` - Real-time monitoring examples
- `examples/31_bc_generation_from_live_gauge.ipynb` - Boundary condition generation
- `examples/32_model_validation_with_usgs.ipynb` - Model validation workflow
- `examples/33_gauge_catalog_generation.ipynb` - Catalog generation (v0.89.0+)

## Key Features

### Multi-Level Verifiability
- **HEC-RAS Projects**: Boundary conditions in .u## files reviewable in HEC-RAS GUI
- **Visual Outputs**: Time series plots and validation metrics for domain expert review
- **Code Audit Trails**: All functions use @log_call decorators for execution tracking

### USGS Service Compliance
- Respectful API usage with rate limiting
- Proper parameter codes (00060 = flow, 00065 = stage)
- Service timeout handling and retry logic

### Data Quality
- Automatic gap detection and reporting
- Data availability checks before processing
- Validation of resampled time series

## See Also

- Parent library context: `ras_commander/CLAUDE.md`
- Boundary condition utilities: `ras_commander.RasUnsteady`
- HDF extraction for validation: `ras_commander.HdfResultsXsec`, `HdfResultsMesh`
- Real-time computation: `.claude/rules/hec-ras/execution.md`
