# Analyzing AORC Precipitation Skill

Claude Code skill for working with AORC historical precipitation and NOAA Atlas 14 design storms in HEC-RAS/HMS projects.

## Files

- **SKILL.md** - Main skill definition with quick start, workflows, and use cases
- **reference/aorc-api.md** - Complete AORC API reference
- **reference/atlas14.md** - Atlas 14 design storm API reference
- **examples/aorc-retrieval.py** - Basic AORC workflow script
- **examples/design-storm.py** - Atlas 14 design storm generation script

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

## Cross-References

- **Precip Module**: `ras_commander/precip/CLAUDE.md`
- **Example Notebooks**:
  - `examples/24_aorc_precipitation.ipynb`
  - `examples/103_Running_AEP_Events_from_Atlas_14.ipynb`
  - `examples/104_Atlas14_AEP_Multi_Project.ipynb`

## See Also

- DSS operations: `ras_commander.dss.RasDss`
- Unsteady flow: `ras_commander.RasUnsteady`
- HDF project bounds: `ras_commander.hdf.HdfProject`
