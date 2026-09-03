# Geometry Modules

Classes for parsing and modifying HEC-RAS geometry files.

## Unified Cross-Section Points

`RasCrossSections.get_points(project, geometry)` exports the same stable point
schema from a plain-text `.g##` geometry or compiled `.g##.hdf`. Pass a
`RasPrj`, project folder, or `.prj` file for `project`; pass a geometry number,
title, text path, or HDF path for `geometry`. `source="auto"` prefers an
available HDF for project geometry selectors, while an explicit source path
keeps its source type.

```python
from ras_commander import RasCrossSections

points = RasCrossSections.get_points("Muncie.prj", "01")
points.to_csv("muncie-xs-points.csv", index=False)
```

The frame includes model/geometry/reach/XS identifiers; exact river, reach, and
river-station strings; native and station order; cut-line relative distance;
XYZ; Manning's n and bank fields; horizontal CRS/units; vertical units/datum;
`vertical_units_source`; and source/extraction provenance. Native elevations are preserved by default.
A vertical datum is never inferred from a horizontal CRS or a model centroid.
When the source does not store a datum, pass `vertical_datum=` explicitly;
`vertical_units=` is the highest-priority override, followed by the full
project's text `.prj` marker. A direct `HdfXsec.get_xs_coords()` call uses only
genuinely explicit HDF vertical-unit metadata and does not infer units from
generic HDF unit-system flags. The source column reports `explicit`,
`project_text`, `geometry_hdf_explicit`, or `unknown`.

The identifiers are deterministic within one export; collection-wide model
identity remains the responsibility of the consuming catalog. Prefer Parquet
for large exports because the complete transform-provenance JSON is repeated
per point and can make CSV files unnecessarily large.

Vertical conversion is opt-in through `VerticalTransform`. Use either an exact
PROJ pipeline or explicit source and target 3D/compound CRSs. The operation is
run against every point's own X/Y/Z coordinate, and the requested operation,
resolved PROJ definition, datum/unit labels, and PROJ/pyproj versions are
stored in `vertical_transform_provenance` and `DataFrame.attrs`.

```python
from ras_commander import RasCrossSections, VerticalTransform

transform = VerticalTransform(
    source_vertical_datum="NAVD88",
    target_vertical_datum="Local project datum",
    source_vertical_units="ft",
    target_vertical_units="ft",
    pipeline="+proj=pipeline +step +proj=affine +zoff=1.25",
)

adjusted = RasCrossSections.get_points(
    "Muncie.prj",
    "01",
    vertical_datum="NAVD88",
    vertical_transform=transform,
)
```

An affine offset is shown only to make the explicit operation easy to inspect.
For geodetic vertical transformations, use the project-approved PROJ pipeline
or full compound CRS definitions and confirm required grid files are installed.

## GeomProjection

Model geometry reprojection helpers for copied HEC-RAS projects and plain-text
geometry files.

### Methods

- `reproject_model_geometry(project_path, source_crs, destination_crs, dest_folder=None, ...)` - Copy a project folder, transform authored `.g##` model geometry coordinates, write a destination ESRI projection file, update copied `.rasmap` `RASProjectionFilename` references, and return terrain / compiled-geometry rebuild requirements.
- `reproject_geometry(geom_file, source_crs, destination_crs, output_geom=None, ...)` - Transform one plain-text `.g##` file. By default writes a sibling copied geometry named `*_reprojected.g##`.

Both methods accept CRS inputs supported by `pyproj.CRS.from_user_input()`,
plus ESRI `.prj` file paths or WKT text. Datum shifts are rejected by default
because HEC-RAS project reprojection cannot reproduce geodetic datum
transformations. Set `allow_datum_shift=True` only after a project-specific
engineering review.

`reproject_model_geometry()` always works on a copied project folder. The
destination cannot be the source project folder or a child of it, even with
`overwrite=True`.

```python
from ras_commander import GeomProjection

report = GeomProjection.reproject_model_geometry(
    project_path="Muncie.prj",
    source_crs="EPSG:5070",
    destination_crs="EPSG:26915",
    dest_folder="Muncie_reprojected",
)

print(report["projection_file"])
print(report["terrain_requirements"])
```

The reprojection writer transforms authored text geometry such as river reach
XY lines, cross-section GIS cut lines, storage-area and 2D perimeters, 2D seed
points, breaklines, SA/2D connection lines, BC lines, reference lines, and IC
point positions. It intentionally does **not** transform station/elevation
tables, bank stations, compiled `.g##.hdf` geometry, refinement-region HDF
datasets, terrain HDF/raster pixels, land-cover rasters, infiltration rasters,
or sediment bed-material rasters. The returned report identifies compiled
geometry preprocessing requirements, refinement-region HDF integrity findings,
and terrain layers whose CRS no longer matches the destination project CRS.

Use existing CRS inspection and validation APIs with the returned report:

- `RasPrj.refresh_project_crs()` to refresh the active project's inferred CRS.
- `RasMap.parse_rasmap()` to inspect `.rasmap` projection and terrain paths.
- `RasMapValidation.check_layer_crs()` to validate GIS/raster layers against an expected EPSG code.
- `HdfBase.get_projection()` to inspect HDF or rasmap-associated projection metadata.

## RasGeometry

Comprehensive 1D geometry parsing and modification.

### Cross Section Methods

- `get_cross_sections(geom)` - List all cross sections
- `build_cross_section(input_spec=None, **kwargs)` - Build a complete Type 1 cross-section geometry entry from station/elevation, terrain, adjacent XS, bank, Manning's n, and reach-length inputs
- `get_station_elevation(geom, river, reach, station)` - Get station-elevation pairs
- `set_station_elevation(geom, river, reach, station, sta_elev)` - Modify station-elevation
- `get_mannings_n(geom, river, reach, station)` - Get Manning's n values
- `get_bank_stations(geom, river, reach, station)` - Get bank station locations

### Cross Section Builder

`GeomCrossSection.build_cross_section()` returns a `CrossSectionBuildResult`
with resolved station/elevation, bank stations, Manning's n breakpoints, reach
lengths, fallback messages, and formatted `.g##` geometry lines. The method
accepts either keyword arguments or a `CrossSectionBuildInput` dataclass.

```python
from ras_commander import (
    CrossSectionBankStations,
    CrossSectionManningsN,
    CrossSectionReachLengths,
    GeomCrossSection,
)

result = GeomCrossSection.build_cross_section(
    river="Example River",
    reach="Main",
    rs="1000",
    terrain_profile=terrain_df,  # columns: station/elevation or Station/Elevation
    cut_line=[(0.0, 0.0), (500.0, 0.0)],
    river_centerline=[(250.0, -50.0), (250.0, 50.0)],
)

entry_text = result.text
```

Fallback behavior is intentionally visible. Every fallback logs at `ERROR`
level with `river|reach|RS` and also appears in `result.fallback_messages`.
The builder always writes required `Bank Sta=`, `#Sta/Elev=`, and `#Mann=`
records when enough station/elevation data can be resolved.

Resolution order:

- Station/elevation: explicit `station_elevation`, terrain profile or
  `RasTerrainMod.get_terrain_profile()`, then adjacent XS interpolation.
- Bank stations: explicit station/elevation, explicit stations with terrain
  elevations, river-centerline intersection with default 20-unit main-channel
  width, then profile-interpolated bank elevations when terrain is unavailable.
- Manning's n: controlled by `mannings_strategy`. `auto` prefers land cover,
  neighboring XS interpolation, user values, then defaults (`MC=0.06`,
  `LOB=ROB=0.08`). Strategies `landcover`, `neighbor`, `user`, and `default`
  make a source preferred.
- Point count: station/elevation output is capped at 500 points using a
  Douglas-Peucker-style reducer that preserves endpoints, banks, the thalweg,
  and major slope breaks.

Fully specified inputs avoid fallbacks:

```python
result = GeomCrossSection.build_cross_section(
    river="Example River",
    reach="Main",
    rs="1000",
    station_elevation=survey_df,
    bank_stations=CrossSectionBankStations(120.0, 180.0, 534.2, 533.8),
    mannings_n=CrossSectionManningsN(lob=0.08, channel=0.05, rob=0.08),
    reach_lengths=CrossSectionReachLengths(left=400.0, channel=390.0, right=410.0),
)
assert result.fallback_messages == []
```

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
- `replace_reference_lines(geom_file, storage_area, reference_lines, *, expected_existing_names=..., create_backup=True)` - Atomically replace or remove one existing 2D area's complete reference-line collection while preserving other areas; returns the backup path, or `None` when backups are disabled
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

## GeomMesh

Headless 2D mesh generation helpers and compiled geometry HDF refinement-region
utilities.

### Domain and Mesh Methods

- `audit_domain_containment(geom_number, mesh_name=..., cell_size=..., ras_object=...)` - Fail closed unless every breakline, refinement region, and structure associated with the selected 2D area is wholly covered by the exact compiled perimeter buffered **inward** by one base mesh-cell spacing. BC lines are intentionally excluded because they are authored on the perimeter and require a separate association/overlap audit.
- `generate(geom_number, mesh_name=..., ras_object=...)` - Regenerate the mesh and automatically run the same inward one-cell containment gate before loading native RAS Mapper dependencies.
- `compute_property_tables(geom_number, mesh_name=..., ras_object=...)` - Compute face profiles, Manning's n assignments, face hydraulic tables, and cell properties against the restored geometry associations.

### Refinement Region Methods

- `add_refinement_region(geom_number, polygon, spacing_dx, ...)` - Add one refinement polygon to an existing compiled geometry HDF.
- `add_flowline_refinement_regions(geom_number, flowlines, buffer_width, ...)` - Buffer GeoDataFrame or LineString channel flowlines into refinement-region polygons, optionally simplify/trim them, write them through `add_refinement_region()`, and return FID/name/spacing mappings.
- `replace_refinement_regions(geom_number, regions, expected_existing_names=..., ...)` - Atomically replace or remove the complete HDF refinement-region collection, with an optional optimistic-concurrency guard.
- `get_refinement_regions(geom_number)` - Read refinement-region FID, name, and spacing values from a compiled geometry HDF.
- `set_refinement_region_spacing(geom_number, spacing_dx, ...)` - Update spacing for one or more existing refinement regions.
- `set_refinement_region_name(geom_number, new_name, ...)` - Rename an existing refinement region.

## Structure APIs

Inline structures are exposed through the public `GeomInlineWeir`,
`GeomBridge`, and `GeomCulvert` classes. There is no public `RasStruct` class.

### Inline Weir Methods

- `GeomInlineWeir.get_weirs(geom, river=None, reach=None)` - List inline weirs
- `GeomInlineWeir.get_profile(geom, river, reach, station)` - Get weir profile
- `GeomInlineWeir.get_gates(geom, river, reach, station)` - Get gate data

### Bridge Methods

- `GeomBridge.get_bridges(geom)` - List bridges
- `GeomBridge.get_deck(geom, river, reach, station)` - Get deck profile
- `GeomBridge.get_piers(geom, river, reach, station)` - Get pier data
- `GeomBridge.get_abutment(geom, river, reach, station)` - Get abutment data
- `GeomBridge.get_approach_sections(geom, river, reach, station)` - Get approach sections
- `GeomBridge.get_coefficients(geom, river, reach, station)` - Get coefficients
- `GeomBridge.get_hydraulic_methods(geom, river, reach, station)` - Get bridge low-flow/high-flow method selections from `Bridge Culvert-`, `Deck Dist Width WeirC`, `BR Coef=`, and `WSPro=` records
- `GeomBridge.set_hydraulic_methods(geom, river, reach, station, low_flow_method=..., high_flow_method=..., weir_coefficient=...)` - Set bridge modeling approach method selections and related coefficients
- `GeomBridge.get_htab(geom, river, reach, station)` - Get HTAB settings

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

`set_culverts()` accepts a DataFrame, list of dictionaries, or one dictionary. Shape can be supplied as `Shape` code or `ShapeName` for any taxonomy-backed HEC-RAS culvert shape: Circular, Box, Pipe Arch, Ellipse, Arch, Semi-Circle, Low Profile Arch, High Profile Arch, or Con Span. Required fields are validated against `culvert_taxonomy.json`, including shape-specific dimensions, positive/nonnegative numeric ranges, `Chart #`/`Scale#` combinations, a maximum of 10 culvert groups per crossing, and a maximum of 25 identical barrels per group. The API preserves legacy field names `InletType` and `OutletType` for HEC-RAS `Chart #` and `Scale#`; `ChartID` and `ScaleID` aliases are also accepted. Single-barrel records require `UpstreamStation` and `DownstreamStation`. Multi-barrel records require `NumBarrels` and matching `BarrelStations` pairs.

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
            "ShapeName": "Pipe Arch",
            "Span": 7,
            "Rise": 5,
            "Length": 48,
            "ManningsN": 0.024,
            "EntranceLoss": 0.4,
            "ExitLoss": 1.0,
            "ChartID": 34,
            "ScaleID": 1,
            "UpstreamInvert": 26.2,
            "UpstreamStation": 1000,
            "DownstreamInvert": 25.8,
            "DownstreamStation": 1000,
            "CulvertName": "Pipe Arch",
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

## GeomCrossSection

Cross-section authoring and blocked-obstruction management.

### Cross Section Builder

- `build_cross_section(input_spec=None, **kwargs)` - Build complete cross-section geometry entry from terrain, survey, or adjacent XS data
- `get_blocked_obstructions(geom_file, river, reach, rs)` - Read blocked obstructions for a cross section
- `set_blocked_obstructions(geom_file, river, reach, rs, obstructions)` - Write blocked obstructions

See the [Cross Section Builder](#cross-section-builder) section above for resolution order and fallback behavior.

## GeomBridge

Bridge geometry authoring (deck profiles, piers, abutments, approach sections).

### Methods

- `get_bridges(geom_file, river=None, reach=None)` - List bridges
- `get_deck(geom_file, river, reach, rs)` - Read bridge deck profile
- `set_deck(geom_file, river, reach, rs, deck_data, ...)` - Write bridge deck profile

## GeomBcLines

2D boundary condition line geometry authoring.

### Methods

- `add_bc_line(geom_file, flow_area, name, coordinates, bc_type)` - Add BC line to 2D flow area
- `get_bc_lines(geom_file, flow_area=None)` - Read existing BC lines
- `remove_bc_line(geom_file, flow_area, name)` - Remove a BC line

## GeomLateral

Lateral structure parsing and modification.

### Methods

- `get_lateral_structures(geom_file)` - List lateral structures
- `get_lateral_weir_profile(geom_file, name)` - Get weir profile data

## GeomStorage

Storage area and 2D flow area geometry parsing and writing.

### Methods

- `get_storage_areas(geom_file)` - List storage areas with elevation-volume data
- `get_2d_flow_areas(geom_file)` - List 2D flow areas with settings
- `get_2d_flow_area_settings(geom_file)` - Read 2D flow area computation settings
- `set_2d_flow_area_settings(geom_file, area_name, **settings)` - Write 2D flow area settings (subgrid sampling, composite classification)
- `write_2d_flow_area_perimeter(geom_file, area_name, coordinates, ...)` - Write 2D flow area perimeter
- `replace_breaklines(geom_file, flow_area_name, breaklines, expected_existing_names=..., ...)` - Atomically replace the geometry-global breakline collection while preserving supplied near/far spacing, near-repeat, and protection-radius values.

## MeshRegenerationWorkflow

Exact RAS Mapper geometry import and legacy mesh-regeneration GUI workflows.

### Methods

- `refresh_geometry_hdf_from_text(geom_number=..., geometry_name=..., flow_area_name=..., ras_object=..., ...)` - Transactionally displace one exact geometry HDF, let the explicitly initialized HEC-RAS version rebuild it from task-local `.g##` text, validate the exact 2D perimeter and sibling-HDF isolation, and roll back on failure. This imports geometry features but does not create computation cells.
- `regenerate_mesh(geom_number=..., geometry_name=..., flow_area_name=..., ras_object=..., ...)` - Open/save and validate an already-current exact geometry and compiled mesh.
- `regenerate_mesh_iterative(...)` - Legacy retry workflow; exact geometry selectors are supported and no first-registration fallback is used.

## GeomLevee

Levee station-elevation parsing and modification.

### Methods

- `get_levees(geom_file, river=None, reach=None, rs=None)` - Read levee data for cross sections
- `set_levees(geom_file, river, reach, rs, levee_data)` - Write levee station-elevation data

## RasBreach

Breach discovery and parameter modification in plan files. Detailed computed
results are read separately through `HdfResultsBreach`.

### Methods

- `list_breach_structures_plan(plan_input, *, ras_object=None)` - Return one dictionary per stored definition with `structure`, `river`, `reach`, `station`, and local stored `is_active`
- `read_breach_block(plan_input, structure_name, *, ras_object=None)` - Return the named definition's location, raw `values`, and parsed `table_rows`
- `update_breach_block(plan_input, structure_name, *, is_active=None, method=None, geom_values=None, start_values=None, progression_mode=None, progression_pairs=None, downcutting_pairs=None, widening_pairs=None, calculator_data=None, dlb_methods=None, dlb_soil_type=None, dlb_soil_properties=None, dlb_core_soil_type=None, dlb_cover_option=None, dlb_cover_soil_properties=None, dlb_breach_direction=None, user_growth_flag=None, user_growth_ratio=None, mass_wasting_option=None, create_backup=True, ras_object=None)` - Update complete stored fields and tables
- `set_breach_geom(plan_input, structure_name, *, centerline=None, final_bottom_width=None, final_bottom_elev=None, left_slope=None, right_slope=None, failure_mode=None, piping_coefficient=None, initial_piping_elevation=None, formation_time=None, weir_coefficient=None, initial_width=None, weir_coef=None, active=None, top_elev=None, formation_method=None, ras_object=None)` - Update selected fields in the `Breach Geom` record; `initial_width`/`weir_coef` are deprecated safe aliases, while the three other legacy keywords fail closed with migration guidance
- `create_breach_block(plan_input, structure_name, *, river="", reach="", station="", is_active=True, create_backup=True, ras_object=None)` - Create a new minimal stored breach block

The list output is the structure-level discovery API. Project-level
`plan_df` contains only `breach_definition_count` and
`breach_active_count`; it does not duplicate the full definition records.

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

# Update named fields in Breach Geom
RasBreach.set_breach_geom(
    "01",
    "Dam1",
    formation_time=2.0,
    final_bottom_width=100.0,
    weir_coefficient=2.6,
)
```
