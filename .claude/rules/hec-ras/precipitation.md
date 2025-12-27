# Precipitation Data Integration

**Context**: AORC and Atlas 14 precipitation workflows for HEC-RAS
**Priority**: Medium - precipitation-driven modeling workflows
**Auto-loads**: Yes (precipitation-related code)

## Primary Source

**See**: `ras_commander/precip/CLAUDE.md` for complete precipitation documentation.

## Overview

ras-commander supports multiple precipitation data sources and hyetograph generation methods:

1. **AORC** (Analysis of Record for Calibration) - Historic gridded precipitation
2. **Atlas 14** - NOAA design storm frequencies (AEP events)
3. **Atlas14Storm** (from hms-commander) - HMS-equivalent hyetograph generation

## Precipitation Classes

| Class | Purpose |
|-------|---------|
| `PrecipAorc` | AORC data download and processing |
| `StormGenerator` | Alternating Block Method (flexible peak, NOT HMS-equivalent) |
| `Atlas14Storm` | HMS-equivalent temporal distributions (10^-6 precision) |
| `Atlas14Grid` | Remote access to NOAA Atlas 14 CONUS grids (HTTP range requests) |
| `Atlas14Variance` | Spatial variance analysis for uniform rainfall assessment |

## HMS-Equivalent Hyetograph Generation

**Atlas14Storm** (imported from hms-commander) provides HMS-equivalent hyetograph generation:

```python
from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

if ATLAS14_AVAILABLE:
    hyeto = Atlas14Storm.generate_hyetograph(
        total_depth_inches=17.9,
        state="tx",
        region=3,
        aep_percent=1.0,
        quartile="All Cases"
    )
    # Depth conservation: exact at 10^-6 precision
```

**Choose Atlas14Storm** for HMS-equivalent workflows.
**Choose StormGenerator** for flexible peak positioning (0-100%).

## AORC Workflow (Historic Data)

```python
from ras_commander.precip import PrecipAorc

# Download AORC data for model domain
aorc_data = PrecipAorc.download_for_domain(
    domain_polygon,
    start_date="2020-01-01",
    end_date="2020-01-10"
)

# Generate HEC-RAS precipitation input
PrecipAorc.generate_ras_precip(
    aorc_data,
    output_dss="precipitation.dss"
)
```

**Use Cases**:
- Model calibration with historic storms
- Event reconstruction
- Long-term simulations

## Atlas 14 Workflow (Design Storms)

```python
from ras_commander.precip import StormGenerator

# Download DDF data and generate hyetograph
gen = StormGenerator.download_from_coordinates(40.0, -86.0)
hyeto = gen.generate_hyetograph(
    ari=100,  # 100-year event
    duration_hours=24,
    position_percent=50  # Peak at 50%
)
```

**Use Cases**:
- Design flood analysis
- Floodplain mapping
- Infrastructure design

## AEP (Annual Exceedance Probability)

| AEP | Return Period | Common Name |
|-----|---------------|-------------|
| 0.50 | 2-year | Common flood |
| 0.10 | 10-year | Minor flood |
| 0.04 | 25-year | Moderate flood |
| 0.02 | 50-year | Significant flood |
| 0.01 | 100-year | 1% annual chance |
| 0.002 | 500-year | 0.2% annual chance |

## Atlas 14 Grid Workflow (Spatial Variance Analysis)

**New in v0.87.6**: Assess whether uniform rainfall is appropriate for rain-on-grid modeling:

```python
from ras_commander.precip import Atlas14Variance

# Quick variance check (100-yr, 24-hr)
stats = Atlas14Variance.analyze_quick("MyProject.g01.hdf")

if stats['range_pct'] > 10:
    print("⚠️ Consider spatially variable rainfall")
else:
    print("✓ Uniform rainfall appropriate")
```

**Key Feature**: Downloads only data within project extent via HTTP byte-range requests (99.9% data reduction vs full state datasets).

**Extent Options**:
- `extent_source="2d_flow_area"` - Use 2D flow area perimeters (recommended)
- `extent_source="project_extent"` - Use full project bounds

**Performance**: ~5-15 seconds for typical extent, ~250 KB data transfer.

## Internet Dependency

AORC and Atlas 14 require internet access:
- AORC downloads from AWS/NOAA servers
- Atlas 14 queries NOAA Point Precipitation Frequency
- Atlas14Grid accesses NOAA CONUS NetCDF via HTTP

Handle offline scenarios:

```python
try:
    data = StormGenerator.download_from_coordinates(lat, lon)
except requests.ConnectionError:
    logger.warning("NOAA service unavailable")
    # Use cached data or fail gracefully
```

## See Also

- **Complete Documentation**: `ras_commander/precip/CLAUDE.md`
- **Example Notebooks**:
  - `examples/900_aorc_precipitation.ipynb` - AORC workflow
  - `examples/720_atlas14_aep_events.ipynb` - Atlas 14 workflow
  - `examples/722_atlas14_multi_project.ipynb` - Batch processing
  - `examples/725_atlas14_spatial_variance.ipynb` - Spatial variance analysis
- **Skill**: `.claude/skills/analyzing-aorc-precipitation/SKILL.md`

---

**Key Takeaway**: Use Atlas14Storm for HMS-equivalent hyetographs, StormGenerator for flexible peak positioning, Atlas14Grid for spatial variance analysis, AORC for historic events. Range % > 10% suggests spatially variable rainfall. AEP = 1/return period.
