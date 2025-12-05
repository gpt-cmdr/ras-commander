# Geometry Operations

RAS Commander provides comprehensive geometry parsing and modification for HEC-RAS projects.

## Overview

| Class | Purpose |
|-------|---------|
| `RasGeometry` | 1D geometry parsing (cross sections, storage areas, connections) |
| `RasGeometryUtils` | Parsing utilities (fixed-width, count interpretation) |
| `RasStruct` | Inline structure parsing (bridges, culverts, weirs) |
| `RasGeo` | 2D Manning's n land cover operations |
| `HdfHydraulicTables` | Cross section property tables (HTAB) from HDF |

## Cross Sections

### List Cross Sections

```python
from ras_commander import RasGeometry, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get all cross sections
xs_df = RasGeometry.get_cross_sections("01")  # geometry number
print(xs_df[['river', 'reach', 'station', 'description']])
```

### Station-Elevation Data

```python
# Get station-elevation for a specific cross section
river = "Big Creek"
reach = "Upper"
station = "1000"

sta_elev = RasGeometry.get_station_elevation("01", river, reach, station)
print(sta_elev)  # DataFrame with 'station' and 'elevation' columns
```

### Manning's n Values

```python
# Get Manning's n for a cross section
mannings = RasGeometry.get_mannings_n("01", river, reach, station)
print(mannings)  # Returns LOB, Channel, ROB values
```

### Modify Cross Sections

```python
import pandas as pd

# Create modified station-elevation
new_sta_elev = pd.DataFrame({
    'station': [0, 50, 100, 150, 200],
    'elevation': [105, 100, 98, 100, 105]
})

# Update the cross section
RasGeometry.set_station_elevation(
    "01", river, reach, station,
    new_sta_elev
)
```

!!! warning "Critical Limits"
    - Maximum 450 points per cross section
    - Bank stations are automatically interpolated if not on existing points
    - Always verify results after modification

## Storage Areas

```python
# List all storage areas
sa_df = RasGeometry.get_storage_areas("01")
print(sa_df[['name', 'max_elevation']])

# Get elevation-volume curve
sa_name = "Storage Area 1"
elev_vol = RasGeometry.get_storage_elevation_volume("01", sa_name)
print(elev_vol)  # DataFrame with elevation, area, volume
```

## Lateral Structures

```python
# List lateral structures
lat_df = RasGeometry.get_lateral_structures("01")
print(lat_df)

# Get weir profile for a lateral structure
profile = RasGeometry.get_lateral_weir_profile("01", "Lateral Weir 1")
print(profile)  # Station and elevation
```

## SA/2D Connections

```python
# List connections
conn_df = RasGeometry.get_connections("01")
print(conn_df)

# Get weir profile
weir_profile = RasGeometry.get_connection_weir_profile("01", "SA-2D Conn 1")

# Get gate data
gates = RasGeometry.get_connection_gates("01", "SA-2D Conn 1")
```

## Inline Structures

### Inline Weirs

```python
from ras_commander import RasStruct

# List inline weirs
weirs = RasStruct.get_inline_weirs("01")
print(weirs)

# Get weir profile
profile = RasStruct.get_inline_weir_profile("01", river, reach, station)
print(profile)

# Get gate data
gates = RasStruct.get_inline_weir_gates("01", river, reach, station)
```

### Bridges

```python
# List bridges
bridges = RasStruct.get_bridges("01")
print(bridges)

# Get bridge deck profile
deck = RasStruct.get_bridge_deck("01", river, reach, station)

# Get pier data
piers = RasStruct.get_bridge_piers("01", river, reach, station)

# Get abutment data
abutment = RasStruct.get_bridge_abutment("01", river, reach, station)

# Get approach sections
approach = RasStruct.get_bridge_approach_sections("01", river, reach, station)

# Get bridge coefficients
coeffs = RasStruct.get_bridge_coefficients("01", river, reach, station)

# Get HTAB settings
htab = RasStruct.get_bridge_htab("01", river, reach, station)
```

### Culverts

```python
# List all culverts
culverts = RasStruct.get_culverts("01")
print(culverts)

# Get detailed culvert data for all at a location
all_culverts = RasStruct.get_all_culverts("01", river, reach, station)
```

**Culvert Shape Codes:**

| Code | Shape |
|------|-------|
| 1 | Circular |
| 2 | Box |
| 3 | Pipe Arch |
| 4 | Ellipse |
| 5 | Arch |
| 6 | Semi-Circle |
| 7 | Low Profile Arch |
| 8 | High Profile Arch |
| 9 | Con Span |

## 2D Manning's n (Land Cover)

```python
from ras_commander import RasGeo

# Get base Manning's n table
base_n = RasGeo.get_base_mannings_table("01")
print(base_n)

# Get regional overrides
regional = RasGeo.get_regional_mannings("01", "2D Flow Area")

# Update Manning's n
RasGeo.set_base_mannings_table("01", updated_table)
```

## Hydraulic Tables (HTAB)

Extract property tables from preprocessed geometry HDF:

```python
from ras_commander import HdfHydraulicTables

# Get geometry HDF path
geom_hdf = "/path/to/project.g01.hdf"

# Get cross section HTAB
htab = HdfHydraulicTables.get_xs_htab(geom_hdf, river, reach, station)
print(htab)
# Contains: elevation, area, conveyance, wetted_perimeter, top_width
```

This enables rating curve generation without re-running HEC-RAS.

## Geometry Preprocessor Files

Clear `.c##` files to force HEC-RAS to recalculate hydraulic tables:

```python
from ras_commander import RasGeo, RasPlan

# Clear for specific plan
plan_path = RasPlan.get_plan_path("01")
RasGeo.clear_geompre_files(plan_path)

# Or clear for all plans
RasGeo.clear_geompre_files()
```

## File Format Notes

HEC-RAS geometry files use FORTRAN-style fixed-width formatting:

- 8-character fields (common)
- Comma-separated values (some sections)
- Bank stations require interpolation to match points

The `RasGeometryUtils` class handles these formats internally.

## Best Practices

1. **Backup first**: Always backup geometry files before modification
2. **Clear preprocessor**: Run `clear_geompre_files()` after geometry changes
3. **Validate changes**: Re-open in HEC-RAS GUI to verify modifications
4. **Point limits**: Keep cross sections under 450 points
5. **Bank stations**: Let the library handle interpolation automatically

## Example: Modify Cross Section Elevations

```python
from ras_commander import RasGeometry, RasGeo, RasCmdr, init_ras_project
import pandas as pd

init_ras_project("/path/to/project", "6.5")

# Get current data
river, reach, station = "Big Creek", "Upper", "1000"
sta_elev = RasGeometry.get_station_elevation("01", river, reach, station)

# Lower the channel by 2 feet
sta_elev['elevation'] = sta_elev['elevation'] - 2.0

# Update geometry
RasGeometry.set_station_elevation("01", river, reach, station, sta_elev)

# Clear preprocessor and recompute
RasGeo.clear_geompre_files()
success = RasCmdr.compute_plan("01", dest_folder="./modified_run")
```
