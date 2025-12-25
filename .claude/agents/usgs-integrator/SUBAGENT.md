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

# USGS Integrator - Primary Source Navigator

## Purpose

This subagent is a **lightweight navigator** to the USGS integration documentation. All detailed workflows, API references, and examples are maintained in primary sources.

**DO NOT duplicate workflow details here.** Point to primary sources instead.

## Primary Documentation Sources

### 1. Complete Module Reference (PRIMARY)
**Location**: `ras_commander/usgs/CLAUDE.md` (310 lines)

**Contains**:
- Complete module overview (14 modules)
- All function signatures and parameters
- Complete workflows (discovery → validation)
- Real-time monitoring workflows (v0.87.0+)
- Catalog generation workflows (v0.89.0+)
- Code examples for every workflow stage

**When to use**: For ANY technical question about USGS integration

### 2. Example Notebooks (DEMONSTRATIONS)

**Primary workflows**:
- `examples/911_usgs_gauge_data_integration.ipynb` - Complete end-to-end workflow
- `examples/912_usgs_real_time_monitoring.ipynb` - Real-time monitoring examples
- `examples/913_bc_generation_from_live_gauge.ipynb` - Boundary condition generation
- `examples/914_model_validation_with_usgs.ipynb` - Model validation workflow
- `examples/910_usgs_gauge_catalog.ipynb` - Catalog generation (v0.89.0+)

**When to use**: For working examples and jupyter-based demonstrations

### 3. Code Docstrings (API DETAILS)

**Locations**: `ras_commander/usgs/*.py` files
- `core.py` - Data retrieval (RasUsgsCore)
- `spatial.py` - Geospatial queries (UsgsGaugeSpatial)
- `gauge_matching.py` - Gauge-to-model matching (GaugeMatcher)
- `time_series.py` - Resampling and alignment (RasUsgsTimeSeries)
- `boundary_generation.py` - BC table generation (RasUsgsBoundaryGeneration)
- `initial_conditions.py` - IC extraction (InitialConditions)
- `real_time.py` - Real-time monitoring (RasUsgsRealTime)
- `catalog.py` - Catalog generation (v0.89.0+)
- `metrics.py` - Validation metrics (NSE, KGE, peak error)
- `visualization.py` - Publication-quality plots

**When to use**: For precise function signatures and parameter details

## When to Delegate to This Subagent

**Trigger phrases**:
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

**Workflow indicators**:
- Spatial queries for gauges within project bounds
- Retrieving historical flow or stage data
- Generating HEC-RAS boundary condition tables
- Model calibration and validation tasks
- Real-time operational forecasting
- QAQC of gauge data quality

## Quick Reference: Workflow Stages

This subagent supports these workflow stages (details in `usgs/CLAUDE.md`):

1. **Spatial Discovery** - Find gauges in project area
2. **Data Retrieval** - Download flow/stage from USGS NWIS
3. **Gauge Matching** - Associate gauges with HEC-RAS features
4. **Time Series Processing** - Resample to HEC-RAS intervals
5. **Initial Conditions** - Extract IC values from observations
6. **Boundary Generation** - Create BC tables for unsteady files
7. **Real-Time Monitoring** - Monitor gauges for operational forecasting (v0.87.0+)
8. **Catalog Generation** - Create standardized gauge data folder (v0.89.0+)
9. **Model Validation** - Calculate metrics and generate plots

See `ras_commander/usgs/CLAUDE.md` for complete workflow documentation.

## Module Organization (14 Modules)

Brief overview - see `usgs/CLAUDE.md` for complete details:

### Data Operations
- **RasUsgsCore** - Primary data retrieval from USGS NWIS
- **RasUsgsFileIo** - Cache data locally, load cached data
- **RasUsgsTimeSeries** - Resample to HEC-RAS intervals, gap detection

### Spatial Operations
- **UsgsGaugeSpatial** - Find gauges within project bounds
- **GaugeMatcher** - Match gauges to HEC-RAS features

### Boundary Conditions
- **RasUsgsBoundaryGeneration** - Generate fixed-width BC tables for .u## files
- **InitialConditions** - Extract IC values, create IC lines

### Real-Time Operations (v0.87.0+)
- **RasUsgsRealTime** - Get latest values, monitor gauges, detect thresholds
- **Callbacks** - Alert functions for threshold/rate exceedance

### Catalog Operations (v0.89.0+)
- **catalog** module - Generate standardized "USGS Gauge Data" folder

### Validation
- **metrics** module - NSE, KGE, peak error, volume bias
- **visualization** module - Time series plots, scatter, residuals, flow duration curves

### Configuration
- **config** - USGS service endpoints, parameter codes
- **rate_limiter** - Respectful API usage (1 req/sec default)

## Common Questions → Primary Source Routing

**Q: How do I find gauges near my model?**
- See: `usgs/CLAUDE.md` Section "Complete Workflow → 1. Spatial Discovery"
- Example: `examples/421_usgs_gauge_data_integration.ipynb`

**Q: How do I generate boundary conditions from USGS data?**
- See: `usgs/CLAUDE.md` Section "Complete Workflow → 5. Boundary Generation"
- Example: `examples/423_bc_generation_from_live_gauge.ipynb`

**Q: How do I validate my model with observed data?**
- See: `usgs/CLAUDE.md` Section "Complete Workflow → 6. Model Validation"
- Example: `examples/424_model_validation_with_usgs.ipynb`

**Q: How do I monitor gauges in real-time?**
- See: `usgs/CLAUDE.md` Section "Real-Time Workflows (v0.87.0+)"
- Example: `examples/422_usgs_real_time_monitoring.ipynb`

**Q: How do I create a gauge catalog for my project?**
- See: `usgs/CLAUDE.md` Section "Catalog generation" (catalog.py)
- Example: `examples/420_usgs_gauge_catalog.ipynb`

**Q: What validation metrics are available?**
- See: `usgs/CLAUDE.md` Section "Validation Metrics (metrics.py)"
- Functions: `nash_sutcliffe_efficiency()`, `kling_gupta_efficiency()`, `calculate_peak_error()`, `calculate_all_metrics()`

**Q: What parameter codes does USGS use?**
- See: `usgs/CLAUDE.md` Section "Configuration (config.py)"
- Common codes: 00060 = flow (cfs), 00065 = stage (ft)

## Dependencies

### Required
- `pandas` - Data handling
- `geopandas` - Spatial queries
- `requests` - NWIS API access

### Optional (Lazy-Loaded)
- `dataretrieval` - USGS NWIS Python client (**required for most functions**)
  - Install: `pip install dataretrieval`
  - Module loads without it; methods check on first use
  - Helpful error raised if missing

### Checking Dependencies
```python
from ras_commander.usgs import check_dependencies
deps = check_dependencies()
# Returns: {'pandas': True, 'geopandas': True, 'dataretrieval': True/False}
```

## Key Features (Brief - see usgs/CLAUDE.md for details)

### Multi-Level Verifiability
- HEC-RAS boundary conditions reviewable in GUI
- Visual outputs for domain expert review
- Code audit trails with @log_call decorators

### USGS Service Compliance
- Rate limiting (1 req/sec default)
- Proper parameter codes (00060 = flow, 00065 = stage)
- Service timeout handling and retry logic

### Data Quality
- Automatic gap detection and reporting
- Data availability checks before processing
- Validation of resampled time series

## Implementation Notes

### Lazy Loading Pattern
The usgs module loads without dataretrieval. Methods check for availability on first use and raise helpful errors if missing.

### USGS Parameter Codes
- `00060` - Discharge (cfs)
- `00065` - Gage height (ft)
- Additional parameters available via `list_available_parameters()`

### HEC-RAS Fixed-Width Format
Boundary tables use HEC-RAS fixed-width format (Fortran-style). Functions handle formatting automatically.

### Time Zone Handling
USGS data is in UTC. Functions handle timezone conversions automatically when aligning with HEC-RAS simulation windows.

## Related Components

**HEC-RAS Integration**:
- `ras_commander.RasUnsteady` - Boundary condition utilities
- `ras_commander.HdfResultsXsec` - Extract modeled 1D results for validation
- `ras_commander.HdfResultsMesh` - Extract modeled 2D results for validation

**Real-time execution**:
- `.claude/rules/hec-ras/execution.md` - Real-time computation callbacks

## Subagent Workflow

When delegated a task:

1. **Read the primary source first**: `ras_commander/usgs/CLAUDE.md`
2. **Check example notebooks** for working demonstrations
3. **Read code docstrings** for precise API details
4. **Implement the workflow** based on primary sources
5. **DO NOT create new workflow documentation** - point to existing sources

## Maintenance Notes

**This file should remain ~300-400 lines** as a lightweight navigator.

**If you find yourself duplicating workflows**:
1. Stop immediately
2. Check if the workflow exists in `usgs/CLAUDE.md`
3. If yes: Point to it instead of duplicating
4. If no: Add it to `usgs/CLAUDE.md` (primary source), then reference it here

**Primary source hierarchy**:
1. `ras_commander/usgs/CLAUDE.md` - COMPLETE workflows and API reference
2. `examples/420-424_*.ipynb` - Working demonstrations
3. Code docstrings - Precise function signatures
4. This file - Lightweight navigator ONLY
