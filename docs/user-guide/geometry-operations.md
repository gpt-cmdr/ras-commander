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

## Rebuilding a copied 2D geometry from text

For a task-local breakout model, initialize the copied project with the HEC-RAS
version that will perform the work. An existing geometry HDF remains
authoritative in RAS Mapper, so opening and saving it does **not** import an
externally edited `.g##` perimeter or breakline collection. Use the exact,
transactional import workflow instead:

```python
from pathlib import Path
from ras_commander import (
    GeomMesh,
    GeomReferenceFeatures,
    GeomStorage,
    init_ras_project,
)
from ras_commander.gui.workflows import MeshRegenerationWorkflow

ras = init_ras_project(
    Path(r"C:\tasks\breakout\Model.prj"),
    "6.6",
    ras_object="new",
    load_results_summary=False,
)

# The caller has already edited only the task-local cloned g03 text.
GeomStorage.set_2d_flow_area_perimeter(
    ras.project_folder / "Model.g03",
    "Breakout Area",
    reduced_domain_polygon,
)
GeomStorage.replace_breaklines(
    ras.project_folder / "Model.g03",
    "Breakout Area",
    retained_and_clipped_breaklines,
    expected_existing_names=source_breakline_names,
)

# Remove parent reference lines outside the reduced domain and replace the
# retained collection in one guarded text mutation.
GeomReferenceFeatures.replace_reference_lines(
    ras.project_folder / "Model.g03",
    retained_reference_lines,
    storage_area="Breakout Area",
    expected_existing_names=source_reference_line_names,
)

refresh = MeshRegenerationWorkflow.refresh_geometry_hdf_from_text(
    geom_number="03",
    geometry_name="Breakout Geometry",
    flow_area_name="Breakout Area",
    ras_object=ras,
)
if not refresh.success:
    raise refresh.error

# HDF-only collections are replaced after RAS Mapper imports the text.
GeomMesh.replace_refinement_regions(
    "03",
    retained_refinement_regions,
    expected_existing_names=source_refinement_names,
    ras_object=ras,
)

# The admissible feature envelope is smaller than the new domain: the exact
# compiled perimeter buffered inward by one full base-cell spacing.
containment = GeomMesh.audit_domain_containment(
    "03",
    mesh_name="Breakout Area",
    ras_object=ras,
)
if not containment.ok:
    raise ValueError(containment.violations)

mesh = GeomMesh.generate(
    "03",
    mesh_name="Breakout Area",
    ras_object=ras,
    hecras_dir=Path(ras.ras_exe_path).parent,
)
if not mesh.ok:
    raise RuntimeError(mesh.error_message)

GeomMesh.compute_property_tables(
    "03",
    mesh_name="Breakout Area",
    ras_object=ras,
)
```

The import defaults to the geometry referenced by the sole current plan when
`geom_number` is omitted. If both number and name are supplied, they must
identify the same unique RAS Mapper layer. Only that HDF is displaced; failure
restores it, non-target geometry HDFs must retain their size and modification
time, and the post-save perimeter must match the text geometrically. The GUI
process tree is supervised from the owned `Ras.exe` PID and no global process
cleanup is performed. Terrain, land-cover, infiltration, and sediment
associations are captured before the import and restored and validated on the
replacement HDF. A missing associated artifact or failed restoration rolls the
transaction back.

The containment buffer is **inward**, not outward. With a 200-foot base mesh,
the eligible feature envelope is the new perimeter eroded by 200 feet.
Breaklines, refinement regions, and structures must be wholly inside that
envelope before meshing begins. Do not apply this gate to BC lines: inflow and
outflow lines belong on the perimeter and instead need exact 2D-area
association, external-face coverage, endpoint clearance, and mutual-overlap
checks. Reference lines are result-extraction features rather than meshing
constraints; remove any parent line that no longer intersects the reduced
domain so HEC-RAS cannot fail during results processing.

`HdfBndry.get_breaklines()` exposes `cell_spacing_near`,
`cell_spacing_far`, `near_repeats`, and `protection_radius` so a clipped
collection can preserve the parent BLE meshing controls. Multipart intersections
must be emitted as uniquely named single-part breaklines because the text format
stores one polyline per breakline block.

Treat the resulting compiled geometry and property tables as reusable run
inputs. A compute may still perform ordinary plan preparation, but do not clear
geometry-preprocessor artifacts for every hydrograph or rating-curve ordinate.
On a real 200,226-cell HEC-RAS 6.6 qualification model, a two-hour Diffusion
Wave solve used about 9 seconds while complete plan preparation and results
processing used about 44 minutes. The operational optimization is therefore to
prepare and certify each immutable reduced geometry once, then reuse it across
the flow series unless geometry-owned inputs change.

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
from ras_commander import GeomPreprocessor, RasPlan

# Clear for specific plan
plan_path = RasPlan.get_plan_path("01")
GeomPreprocessor.clear_geompre_files(plan_path)

# Or clear for all plans
GeomPreprocessor.clear_geompre_files()
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
from ras_commander import GeomPreprocessor, RasGeometry, RasCmdr, init_ras_project
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
GeomPreprocessor.clear_geompre_files()
success = RasCmdr.compute_plan("01", dest_folder="./modified_run")
```
