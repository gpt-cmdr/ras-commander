# Precipitation Data Integration

**Context**: AORC and Atlas 14 precipitation workflows for HEC-RAS
**Priority**: Medium - precipitation-driven modeling workflows
**Auto-loads**: Yes (precipitation-related code)

## Primary Source

**See**: `ras_commander/precip/CLAUDE.md` for complete precipitation documentation.

## Overview

ras-commander supports two precipitation data sources:

1. **AORC** (Analysis of Record for Calibration) - Historic gridded precipitation
2. **Atlas 14** - NOAA design storm frequencies (AEP events)

## Precipitation Classes

| Class | Purpose |
|-------|---------|
| `RasPrecipAorc` | AORC data download and processing |
| `RasPrecipAtlas14` | Atlas 14 point frequency data |
| `RasPrecipUtils` | Precipitation utilities |

## AORC Workflow (Historic Data)

```python
from ras_commander.precip import RasPrecipAorc

# Download AORC data for model domain
aorc_data = RasPrecipAorc.download_for_domain(
    domain_polygon,
    start_date="2020-01-01",
    end_date="2020-01-10"
)

# Generate HEC-RAS precipitation input
RasPrecipAorc.generate_ras_precip(
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
from ras_commander.precip import RasPrecipAtlas14

# Get design storm for location
design_storm = RasPrecipAtlas14.get_point_frequency(
    latitude=40.0,
    longitude=-86.0,
    duration="24H",
    aep=0.01  # 1% AEP (100-year)
)

# Generate HEC-RAS precipitation
RasPrecipAtlas14.generate_ras_precip(
    design_storm,
    output_dss="atlas14.dss"
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

## Internet Dependency

Both AORC and Atlas 14 require internet access:
- AORC downloads from AWS/NOAA servers
- Atlas 14 queries NOAA Point Precipitation Frequency

Handle offline scenarios:

```python
try:
    data = RasPrecipAtlas14.get_point_frequency(lat, lon, duration, aep)
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
- **Skill**: `.claude/skills/analyzing-aorc-precipitation/SKILL.md`

---

**Key Takeaway**: AORC for historic events, Atlas 14 for design storms. Both require internet access. AEP = 1/return period.
