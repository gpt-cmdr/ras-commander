# Geometry Modules

Classes for parsing and modifying HEC-RAS geometry files.

## RasGeometry

Comprehensive 1D geometry parsing and modification.

### Cross Section Methods

- `get_cross_sections(geom)` - List all cross sections
- `get_station_elevation(geom, river, reach, station)` - Get station-elevation pairs
- `set_station_elevation(geom, river, reach, station, sta_elev)` - Modify station-elevation
- `get_mannings_n(geom, river, reach, station)` - Get Manning's n values
- `get_bank_stations(geom, river, reach, station)` - Get bank station locations

### Storage Area Methods

- `get_storage_areas(geom)` - List storage areas
- `get_storage_elevation_volume(geom, name)` - Get elevation-volume curve

### Lateral Structure Methods

- `get_lateral_structures(geom)` - List lateral structures
- `get_lateral_weir_profile(geom, name)` - Get weir profile

### Connection Methods

- `get_connections(geom)` - List SA/2D connections
- `get_connection_weir_profile(geom, name)` - Get connection weir profile
- `get_connection_gates(geom, name)` - Get gate data

## RasGeometryUtils

Parsing utilities for HEC-RAS geometry files.

### Methods

- `parse_fixed_width(line, width=8)` - Parse fixed-width formatted line
- `parse_count_line(line)` - Parse count header line
- `interpolate_bank_station(sta_elev, bank)` - Interpolate bank station elevation

## RasStruct

Inline structure parsing.

### Inline Weir Methods

- `get_inline_weirs(geom)` - List inline weirs
- `get_inline_weir_profile(geom, river, reach, station)` - Get weir profile
- `get_inline_weir_gates(geom, river, reach, station)` - Get gate data

### Bridge Methods

- `get_bridges(geom)` - List bridges
- `get_bridge_deck(geom, river, reach, station)` - Get deck profile
- `get_bridge_piers(geom, river, reach, station)` - Get pier data
- `get_bridge_abutment(geom, river, reach, station)` - Get abutment data
- `get_bridge_approach_sections(geom, river, reach, station)` - Get approach sections
- `get_bridge_coefficients(geom, river, reach, station)` - Get coefficients
- `get_bridge_htab(geom, river, reach, station)` - Get HTAB settings

### Culvert Methods

- `get_culverts(geom)` - List culverts
- `get_all_culverts(geom, river, reach, station)` - Get all culverts at location

## RasBreach

Breach parameter modification in plan files.

### Methods

- `list_breach_structures_plan(plan)` - List structures with breach data
- `read_breach_block(plan, structure)` - Read breach parameters
- `update_breach_block(plan, structure, **params)` - Modify breach parameters

## Usage Examples

### Cross Section Modification

```python
from ras_commander import RasGeometry, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get station-elevation
sta_elev = RasGeometry.get_station_elevation("01", "River", "Reach", "1000")

# Modify and save
sta_elev['elevation'] = sta_elev['elevation'] - 2.0
RasGeometry.set_station_elevation("01", "River", "Reach", "1000", sta_elev)
```

### Breach Parameter Update

```python
from ras_commander import RasBreach

# Update breach parameters
RasBreach.update_breach_block(
    "01", "Dam1",
    formation_time=2.0,
    bottom_width=100.0
)
```
