---
name: precipitation-specialist
model: haiku
tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
working_directory: ras_commander/precip
description: |
  Integrates precipitation data into HEC-RAS/HMS models using AORC (historical
  calibration) and NOAA Atlas 14 (design storms). Handles spatial averaging,
  temporal distributions (SCS Type II), areal reduction factors, and DSS export.
  Use when working with precipitation data, design storms, AORC retrieval, or
  generating HEC-RAS boundary conditions from rainfall.
---

# Precipitation Specialist Subagent

## Purpose

This subagent specializes in precipitation data integration for HEC-RAS and HEC-HMS models. It handles two primary data sources:

1. **AORC (Analysis of Record for Calibration)**: Historical precipitation data (1979-present) for model calibration and validation
2. **NOAA Atlas 14**: Design storm generation for annual exceedance probability (AEP) events

## When to Delegate to This Subagent

Delegate tasks containing these trigger phrases:

**Data Source Triggers**:
- "AORC" or "Analysis of Record for Calibration"
- "Atlas 14" or "NOAA precipitation frequency"
- "historical precipitation" or "observed rainfall"
- "design storm" or "synthetic storm"

**Operation Triggers**:
- "precipitation data" or "rainfall data"
- "spatial average" or "watershed precipitation"
- "temporal distribution" or "SCS Type II"
- "areal reduction factor" or "ARF"
- "precipitation frequency" or "AEP event"
- "storm hyetograph" or "rainfall distribution"

**Output Triggers**:
- "DSS precipitation" or "precipitation boundary condition"
- "HEC-HMS gage file" or "precipitation gage"
- "design storm generation" or "100-year storm"

**Example Delegation Phrases**:
- "Retrieve AORC precipitation for my watershed"
- "Generate a 24-hour, 1% AEP design storm using Atlas 14"
- "Apply areal reduction factor to design storm"
- "Export precipitation to DSS format for HEC-RAS"
- "Create SCS Type II temporal distribution"

## Module Organization

The precip subpackage contains 3 modules organized by data source:

### PrecipAorc.py (Historical Data)

**Primary Class**: `PrecipAorc` - AORC data retrieval and processing

**Data Retrieval**:
- `retrieve_aorc_data()` - Download AORC time series for watershed
- `get_available_years()` - Query 1979-present coverage
- `check_data_coverage()` - Verify spatial/temporal availability

**Spatial Processing**:
- `extract_by_watershed()` - Extract for HUC or custom polygon
- `spatial_average()` - Calculate areal average
- `resample_grid()` - Aggregate grid cells

**Temporal Processing**:
- `aggregate_to_interval()` - Match HEC-RAS/HMS timesteps (1HR, 6HR, 1DAY)
- `extract_storm_events()` - Identify individual storms
- `calculate_rolling_totals()` - N-hour rolling precipitation

**AORC Specifications**:
- Spatial resolution: ~4 km grid (1/24 degree)
- Temporal resolution: Hourly
- Coverage: CONUS (1979 - present)
- Source: NOAA National Water Model retrospective forcing

### StormGenerator.py (Design Storms)

**Primary Class**: `StormGenerator` - Atlas 14 design storm generation

**Design Storm Creation**:
- `generate_design_storm()` - Create temporal hyetograph
- `get_precipitation_frequency()` - Query Atlas 14 point values
- `apply_temporal_distribution()` - Apply SCS patterns

**AEP Events**:
- Standard: 50%, 20%, 10%, 4%, 2%, 1%, 0.5%, 0.2%
- Durations: 6hr, 12hr, 24hr, 48hr (custom supported)

**Temporal Distributions**:
- SCS Type II (standard for most US)
- SCS Type IA (Pacific maritime)
- SCS Type III (Gulf Coast, Florida)
- Custom user-defined patterns

**Spatial Processing**:
- `interpolate_point_values()` - Gridded Atlas 14 interpolation
- `apply_areal_reduction()` - ARF for large watersheds
- `generate_multi_point_storms()` - Spatially distributed design storms

### __init__.py (Public API)

Convenience imports for users:
```python
from ras_commander.precip import PrecipAorc, StormGenerator
```

## Data Sources

### AORC Dataset

**Provider**: NOAA Office of Water Prediction
**Access**: NOAA NWM retrospective forcing archive
**Format**: NetCDF (gridded)
**Update Frequency**: Operational (near real-time)
**Documentation**: https://water.noaa.gov/about/nwm

**Key Features**:
- Historical data for calibration
- Spatially distributed (not just point gages)
- Consistent CONUS coverage
- Hourly resolution for urban hydrology

### NOAA Atlas 14

**Provider**: NOAA National Weather Service
**Access**: HDSC Precipitation Frequency Data Server (PFDS)
**Format**: JSON API
**Coverage**: CONUS, Hawaii, Puerto Rico (volumes 1-11)
**Documentation**: https://hdsc.nws.noaa.gov/pfds/

**Key Features**:
- Authoritative precipitation frequency estimates
- Regional temporal distributions
- Full AEP and duration range
- Areal reduction factors

## Common Workflows

### 1. Historical Calibration (AORC)

**Typical sequence**:
1. Define watershed boundary (HUC or shapefile)
2. Retrieve AORC data for event period
3. Apply spatial average over watershed
4. Aggregate to HEC-RAS timestep (1HR, 6HR)
5. Export to DSS or CSV
6. Run HEC-RAS model
7. Compare modeled vs observed flow/stage

**Time estimate**: 5-15 minutes per year of data

### 2. Design Storm Generation (Atlas 14)

**Typical sequence**:
1. Specify location (lat/lon or station ID)
2. Query Atlas 14 for design AEP (e.g., 1% = 100-year)
3. Generate temporal distribution (SCS Type II)
4. Apply areal reduction (if watershed > 10 sq mi)
5. Export to DSS or HEC-HMS gage file
6. Run HEC-RAS/HMS for design event

**Time estimate**: < 5 minutes per event

### 3. Multi-Event Suite

**Typical sequence**:
1. Define AEP range (e.g., 10%, 2%, 1%, 0.2%)
2. Loop through events
3. Generate design storms for each
4. Batch export to DSS files
5. Parallel HEC-RAS execution
6. Generate flood frequency curves

**Time estimate**: 10-30 minutes for 4-6 events

### 4. Areal Reduction Application

**When to use**:
- Small watersheds (< 10 sq mi): ARF ≈ 1.0 (use point values)
- Medium watersheds (10-100 sq mi): ARF = 0.95-0.98
- Large watersheds (> 100 sq mi): ARF < 0.95 (significant reduction)

**Process**:
1. Query point precipitation from Atlas 14
2. Calculate watershed area (sq mi)
3. Apply ARF based on area and duration
4. Use reduced value for design storm

## Dependencies

**Required**:
- pandas (time series handling)
- numpy (numerical operations)
- xarray (AORC NetCDF data)
- requests (Atlas 14 API)

**Optional**:
- geopandas (spatial operations)
- rasterio (AORC grid processing)
- pydsstools (DSS export, lazy-loaded)

**Installation**:
```bash
pip install xarray rasterio geopandas pydsstools
```

## Performance Expectations

### AORC Retrieval
- Speed: ~1-5 minutes per year (depends on watershed size)
- Storage: ~10-50 MB per year (hourly, single watershed)
- Caching: Local cache recommended

### Atlas 14 Queries
- Speed: < 5 seconds per query
- Rate limiting: Respect NOAA PFDS usage guidelines
- Caching: Automatic API response caching

## Cross-References

**Complete User Workflows**:
- Main precipitation documentation: `ras_commander/precip/CLAUDE.md`

**Technical Details**:
- AORC API reference: [reference/aorc-api.md](reference/aorc-api.md)
- Atlas 14 workflows: [reference/atlas14.md](reference/atlas14.md)

**Example Notebooks**:
- `examples/24_aorc_precipitation.ipynb` - AORC retrieval
- `examples/103_Running_AEP_Events_from_Atlas_14.ipynb` - Single-project Atlas 14
- `examples/104_Atlas14_AEP_Multi_Project.ipynb` - Batch processing

**Related Subpackages**:
- DSS file operations: `ras_commander/dss/AGENTS.md`
- Unsteady flow files: `ras_commander.RasUnsteady`
- Spatial data: `.claude/rules/python/path-handling.md`
