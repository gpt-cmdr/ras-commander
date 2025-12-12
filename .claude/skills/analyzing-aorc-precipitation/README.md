# Analyzing AORC Precipitation Skill

Claude Code skill for working with AORC historical precipitation and NOAA Atlas 14 design storms in HEC-RAS/HMS projects.

**This is a NAVIGATOR skill** - it points to primary sources rather than duplicating content.

## Files

- **SKILL.md** - Lightweight skill navigator (~390 lines) pointing to primary sources
- **README.md** - This file (skill overview)

## Primary Sources

All detailed workflows and API documentation live in:
- `ras_commander/precip/CLAUDE.md` - Complete API reference (329 lines)
- `examples/24_aorc_precipitation.ipynb` - AORC workflow demonstration
- `examples/103_Running_AEP_Events_from_Atlas_14.ipynb` - Atlas 14 workflow
- `examples/104_Atlas14_AEP_Multi_Project.ipynb` - Multi-project batch processing

## Trigger Keywords

This skill is triggered by mentions of:
- precipitation, AORC, Atlas 14
- design storm, rainfall, hyetograph
- SCS Type II, AEP, 100-year storm
- rain-on-grid, temporal distribution
- areal reduction, calibration

## Quick Reference

### AORC Historical Data
```python
from ras_commander.precip import PrecipAorc

# Retrieve and process
data = PrecipAorc.retrieve_aorc_data("02070010", "2015-05-01", "2015-05-15")
avg = PrecipAorc.spatial_average(data, "02070010")
hourly = PrecipAorc.aggregate_to_interval(avg, "1HR")
PrecipAorc.export_to_dss(hourly, "precip.dss", "/PATH//AORC//1HR/OBS/")
```

### Atlas 14 Design Storm
```python
from ras_commander.precip import StormGenerator

# Query and generate
precip = StormGenerator.get_precipitation_frequency((38.9, -77.0), 24, 1.0)
hyeto = StormGenerator.generate_design_storm(precip, 24, "SCS_Type_II", 15)
StormGenerator.export_to_dss(hyeto, "design.dss", "/PATH//DESIGN//15MIN/SYN/")
```

## Navigation Pattern

1. **Read SKILL.md** for overview and navigation map
2. **Consult primary sources** (`ras_commander/precip/CLAUDE.md`) for API details
3. **Review example notebooks** for working implementations
4. **Implement** using patterns from examples

## See Also

- DSS operations: `ras_commander.dss.RasDss`
- Unsteady flow: `ras_commander.RasUnsteady`
- HDF project bounds: `ras_commander.hdf.HdfProject`
