# USGS Gauge Data Integration

**Context**: Integrating USGS gauge data with HEC-RAS models
**Priority**: Medium - validation and boundary generation workflows
**Auto-loads**: Yes (USGS-related code)

## Primary Source

**See**: `ras_commander/usgs/CLAUDE.md` for complete USGS documentation.

## Overview

ras-commander integrates with USGS NWIS (National Water Information System) for gauge discovery, data retrieval, validation, and boundary condition generation.

## Key Classes

| Class | Purpose |
|-------|---------|
| `RasUsgsCore` | Core data retrieval from NWIS |
| `UsgsGaugeSpatial` | Spatial queries (gauges near model) |
| `GaugeMatcher` | Match gauges to model cross sections |
| `RasUsgsTimeSeries` | Time series processing |
| `RasUsgsBoundaryGeneration` | Generate BC from gauge data |
| `RasUsgsRealTime` | Real-time monitoring |
| `InitialConditions` | IC generation from gauge data |

## Common Workflows

### 1. Spatial Discovery

```python
from ras_commander.usgs import UsgsGaugeSpatial

# Find gauges near HEC-RAS model
gauges = UsgsGaugeSpatial.find_gauges_in_project(
    project_folder,
    buffer_miles=10.0
)
```

### 2. Data Retrieval

```python
from ras_commander.usgs import RasUsgsCore

# Get streamflow data
data = RasUsgsCore.get_discharge(
    site_number="03339000",
    start_date="2020-01-01",
    end_date="2020-12-31"
)
```

### 3. Gauge-to-Model Matching

```python
from ras_commander.usgs import GaugeMatcher

# Match gauges to cross sections
matches = GaugeMatcher.match_gauges_to_xs(
    gauges_gdf,
    xs_gdf,
    max_distance_ft=1000
)
```

### 4. Boundary Generation

```python
from ras_commander.usgs import RasUsgsBoundaryGeneration

# Generate boundary conditions from gauge data
RasUsgsBoundaryGeneration.generate_bc_from_gauge(
    gauge_id="03339000",
    unsteady_file=unsteady_file,
    bc_location="Upstream"
)
```

## Quick Reference

```python
from ras_commander.usgs import (
    RasUsgsCore,
    UsgsGaugeSpatial,
    GaugeMatcher
)

# Discover gauges
gauges = UsgsGaugeSpatial.find_gauges_in_project(project)

# Get data
data = RasUsgsCore.get_discharge(site, start, end)

# Match to model
matches = GaugeMatcher.match_gauges_to_xs(gauges, cross_sections)
```

## Internet Dependency

**Note**: USGS workflows require internet access:
- Gauge discovery queries USGS servers
- Data retrieval fetches from NWIS
- Real-time monitoring polls live data

Handle offline scenarios gracefully:

```python
try:
    data = RasUsgsCore.get_discharge(site, start, end)
except requests.ConnectionError:
    logger.warning("USGS service unavailable - using cached data")
    data = load_cached_data(site)
```

## See Also

- **Complete Documentation**: `ras_commander/usgs/CLAUDE.md`
- **Example Notebooks**: `examples/` (USGS integration notebooks)
- **Skill**: `.claude/skills/integrating-usgs-gauges/SKILL.md`

---

**Key Takeaway**: USGS integration provides spatial discovery, data retrieval, and boundary generation. Requires internet access - handle offline scenarios gracefully.
