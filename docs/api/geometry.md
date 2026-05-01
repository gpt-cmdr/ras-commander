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

## GeomReferenceFeatures

Reference line and reference point helpers for 2D calibration and native
reference-line output.

### Reference Line Methods

- `add_reference_lines(geom_file, lines, storage_area)` - Insert manually
  supplied reference lines into a `.g##` file
- `generate_reference_lines_from_longitudinal_line(...)` - Generate
  transverse reference-line dictionaries at regular station intervals along a
  named longitudinal line
- `add_reference_lines_from_longitudinal_line(...)` - Generate and write
  transverse reference lines through the existing `.g##` writer
- `get_reference_lines(geom_file)` - Read reference lines from a `.g##` file

### Automated Reference Lines

```python
from ras_commander import GeomReferenceFeatures

reference_lines = GeomReferenceFeatures.generate_reference_lines_from_longitudinal_line(
    centerlines_gdf,
    longitudinal_line_name="Main River",
    spacing=500.0,
    line_length=1500.0,
    name_template="MainRiver_{station_int}",
)

GeomReferenceFeatures.add_reference_lines(
    "MyModel.g01",
    reference_lines,
    storage_area="Perimeter 1",
)
```

For result-guided orientation, pass `orientation="velocity"` or
`orientation="depth_velocity"` with `orientation_plan_hdf`. Generated lines fall
back to normal-to-line orientation unless `orientation_fallback="raise"` is set.

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
- `get_hydraulic_methods(geom, river, reach, station)` - Get bridge low-flow/high-flow method selections from `Bridge Culvert-`, `Deck Dist Width WeirC`, `BR Coef=`, and `WSPro=` records
- `set_hydraulic_methods(geom, river, reach, station, low_flow_method=..., high_flow_method=..., weir_coefficient=...)` - Set bridge modeling approach method selections and related coefficients
- `get_bridge_htab(geom, river, reach, station)` - Get HTAB settings

Accepted `low_flow_method` values are `energy`, `momentum`, `yarnell`, and `wspro`.
Accepted `high_flow_method` values are `energy` and `pressure_weir`.
Optional compute flags are `use_energy`, `use_momentum`, `use_yarnell`, and `use_wspro`.
Optional coefficient fields include `momentum_cd`, `yarnell_k`, `pressure_flow_submerged_inlet_cd`, `pressure_flow_submerged_inlet_outlet_cd`, and positive `weir_coefficient`.
Unsupported combinations, such as disabling the selected low-flow method or selecting Momentum/Yarnell without an existing or supplied coefficient, raise `ValueError`.

### Culvert Methods

- `GeomCulvert.get_culverts(geom, river, reach, station)` - Get all culverts at a bridge/culvert structure
- `GeomCulvert.get_all(geom, river=None, reach=None)` - Get all culverts in a geometry file
- `GeomCulvert.set_culverts(geom, river, reach, station, culverts)` - Replace culvert records at an existing bridge/culvert structure
- `GeomCulvert.set_culvert(geom, river, reach, station, culvert=None, culvert_index=None, culvert_name=None, **kwargs)` - Update one culvert by index/name or append a new one
- `GeomCulvert.get_adjacent_cross_sections(geom, river, reach, station)` - Find the nearest upstream and downstream cross sections around a structure
- `GeomCulvert.set_adjacent_ineffective_flow(geom, river, reach, station, upstream_ineffective=None, downstream_ineffective=None, ...)` - Coordinate ineffective-flow writes on adjacent cross sections

`set_culverts()` accepts a DataFrame, list of dictionaries, or one dictionary. Shape can be supplied as `Shape` code or `ShapeName`. Required fields are `Shape`/`ShapeName`, `Span`, `Length`, `ManningsN`, `EntranceLoss`, `ExitLoss`, `InletType`, `OutletType`, `UpstreamInvert`, and `DownstreamInvert`; non-circular shapes also require `Rise`. Single-barrel records require `UpstreamStation` and `DownstreamStation`. Multi-barrel records require `NumBarrels` and matching `BarrelStations` pairs.

```python
from ras_commander.geom.GeomCulvert import GeomCulvert

GeomCulvert.set_culverts(
    "model.g01",
    "River",
    "Reach",
    "1000",
    [
        {
            "ShapeName": "Circular",
            "Span": 6,
            "Length": 50,
            "ManningsN": 0.013,
            "EntranceLoss": 0.5,
            "ExitLoss": 1.0,
            "InletType": 1,
            "OutletType": 1,
            "UpstreamInvert": 25.1,
            "UpstreamStation": 996,
            "DownstreamInvert": 25.0,
            "DownstreamStation": 996,
            "CulvertName": "Culvert #1",
        },
        {
            "ShapeName": "Box",
            "Span": 4,
            "Rise": 4,
            "Length": 55,
            "ManningsN": 0.015,
            "EntranceLoss": 0.3,
            "ExitLoss": 1.0,
            "InletType": 8,
            "OutletType": 1,
            "UpstreamInvert": 27.5,
            "DownstreamInvert": 27.0,
            "NumBarrels": 2,
            "BarrelStations": [(980, 980), (1020, 1020)],
            "CulvertName": "Twin Box",
        },
    ],
)
```

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
