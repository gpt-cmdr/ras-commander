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

## RAS Mapper Reach-Length QA

`RasGeometryCompute.assess_flow_path_policy()` determines whether a joined 1D
reach may safely regenerate its overbank flow paths. It copies the whole project,
forces RAS Mapper to regenerate flow paths on the copy, recomputes LOB/channel/ROB
reach lengths, and compares them with the stored values. The source project is
never modified.

```python
from ras_commander import RasGeometryCompute

policy = RasGeometryCompute.assess_flow_path_policy(
    "JoinedModel.g01.hdf",
    tolerance_fraction=0.01,
)

print(policy.recommended_policy)
display(policy.reach_metrics_df)
display(policy.xs_metrics_df)
```

The recommendation is `regenerate_and_recompute` only when every usable LOB and
ROB interval reproduces its stored length within 1%. Otherwise it is
`preserve_and_recompute_only_at_join_boundary`. The preserve policy is also selected
when no source flow paths span a reach but its stored overbank lengths differ
from the channel lengths. This prevents an automatically generated path from
silently replacing evidence of intentionally different overbank routing.

For a provisional joined reach, pass the two cross sections adjacent to the
join. The method returns exactly one regenerated left and right segment clipped
between those cut lines. Save the review evidence directly as GeoParquet when
desired:

```python
policy = RasGeometryCompute.assess_flow_path_policy(
    "JoinedModel.g01.hdf",
    join_upstream_xs=("Walnut", "Main", "5304.8"),
    join_downstream_xs=("Walnut", "Main", "4884.4"),
    review_segments_path="working/walnut_join_flow_paths.parquet",
)

display(policy.join_segments_gdf[["side", "length", "geometry"]])
```

Join selectors may use the full-precision restationed values returned by
`RasBreakout1D.assemble_network_edge().seams_gdf`. Compiled geometry HDF files
can store those values at a shorter displayed precision; the selector accepts a
unique match within one unit of that displayed precision and still fails closed
when more than one cross section could match.

The clipped segment lengths supply only the new join interval's LOB/ROB values;
the remaining stored source lengths stay unchanged under the preserve policy.
The returned geometries should be retained for visual review.

`audit_main_channel_lengths()` is the independent, read-only informative QA
check. It accepts either a plain-text `.g##` geometry or a compiled `.g##.hdf`,
measures the distance between adjacent cross-section intersections along the
river centerline, and compares that distance with the stored channel reach
length. It flags non-terminal intervals outside the supplied relative tolerance
or with an invalid centerline intersection.

```python
channel_audit = RasGeometryCompute.audit_main_channel_lengths(
    "WALNUT 0229.g01",
    tolerance_fraction=0.01,
)
display(channel_audit[channel_audit["main_channel_flagged"]])
```

These APIs follow HEC's documented distinction: channel length comes from the
river line, while LOB/ROB lengths come from flow paths. Automatically generated
flow paths are review starting points rather than reconstructions of engineering
judgment. See the official HEC-RAS Mapper pages for
[Cross Sections](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/cross-sections)
[Rivers](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/rivers),
[River Station Markers](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/river-station-markers),
and [Flow Path Lines](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/flow-path-lines).

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

See [Meshing: Generation, Diagnostics and Repair](meshing.md) for the complete
method reference, runtime matrix, diagnostics, and repair evidence.

<a id="domain-and-mesh-methods"></a>
<a id="hec-ras-version-support-for-headless-mesh-generation"></a>
<a id="hec-ras-refinement-region-caveats"></a>
<a id="refinement-region-methods"></a>

The [repair contract](meshing.md#repair-persistence-and-failure-contract),
[version support](meshing.md#hec-ras-version-support-for-headless-mesh-generation),
and [refinement caveats](meshing.md#hec-ras-refinement-region-caveats) retain the
existing qualification and failure limits.

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

`replace_bc_lines(geom_file, unsteady_files, *, area_2d, lines, ras_object=None)`
replaces the complete named-area line set and its forcing in one staged
transaction. Pass explicit paths in a disposable cloned project. Each line
specification contains `name`, `coordinates`, and `bc_type`: `Normal Depth`
requires `friction_slope`; `Flow Hydrograph` requires `hydrograph_df` and
`friction_slope`; `Stage Hydrograph` requires `hydrograph_df`. Hydrographs use
`hour` and `value` columns. The supplied forcing applies to every supplied flow
file. An empty `lines` list clears the target area's named perimeter boundaries.

Other areas, 1D boundaries, and area-wide rainfall remain intact. Supply every
associated unsteady file; an initialized clone `ras_object` verifies this set
through project DataFrames and rejects flows shared with other geometries.
Without that context, completeness is the caller's responsibility. The result
is a DataFrame with `geom_file`, `unsteady_file`, `area_2d`, `bc_line`, and
`bc_type`, plus removed names and backup paths in `attrs`.

```python
from ras_commander.geom import GeomBcLines

written = GeomBcLines.replace_bc_lines(
    "child.g01", ["child.u01"], area_2d="Perimeter 1",
    lines=[dict(name="OUTLET", coordinates=[(100, 200), (300, 200)],
                bc_type="Normal Depth", friction_slope=0.001)],
)
```

All inputs are validated and staged before replacement, with backups and
byte-exact rollback on write exceptions. This is exception atomicity across
the supplied files; individual file swaps are atomic. It does not provide
crash-atomic visibility across multiple files. Exclude concurrent readers and
writers. The method does not create the clone or update compiled HDF files.
Run native preprocessing, then inspect `HdfMesh.get_mesh_perimeter_faces()`
before relying on native face attachment. A complete disposable example is
provided in `scripts/validate_perimeter_bc.py`; the companion fleet shell script
targets `fim-hecras-wine:6.6-clb-v8`.

### Methods

- `add_bc_lines(geom_file, lines, replace_existing=False)` - Add or upsert named geometry lines
- `delete_bc_line(geom_file, name)` - Delete a named geometry line
- `rename_bc_line(geom_file, old_name, new_name)` - Rename a geometry line
- `replace_bc_lines(...)` - Replace all target-area lines and supplied unsteady references

## GeomLateral

### Complete SA/2D connection records

Use `GeomLateral.get_connection_data(geom_file)` to read one row per connection.
The existing `get_connections()` metadata interface is unchanged. The complete
reader adds `LineCoordinates`, `CrestProfile`, `TerrainProfile`, `Culverts` and
`Gates` as nested DataFrames; `WeirWidth` and `WeirCoefficient` as model-unit
scalars; `Breach`, `UnknownRecords`, `ParseIssues` and `DefaultsUsed` as lists;
and exact `RawBlock` text. Profiles use `Station`/`Elevation`, coordinates use
`X`/`Y`. Unknown/version-specific records are preserved in raw form, not claimed
to be decoded hydraulic parameters. An absent terrain profile is empty; no
terrain is silently sampled. CRS, elevation units and vertical datum inherit
the source model and are not converted or inferred.

`write_connection_data(geom_file, connections_df, create_backup=True)` replaces
the connection inventory with the supplied complete rows, preserving unrelated
geometry text. Omitted rows are removed deliberately. `RawBlock` is authoritative:
decoded columns are checked against it; use focused setters to edit a physical
field and reread before a lossless write. Duplicate names and inconsistent rows
fail before mutation. Both APIs accept strings or `Path` objects; they operate
on explicit geometry files, with no global project state.

```python
from pathlib import Path
import shutil
from ras_commander import GeomLateral, RasExamples

project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path="working/sa2d")
source = project / "BaldEagleDamBrk.g13"
child = Path("working/sa2d/roundtrip.g13")
shutil.copy2(source, child)
records = GeomLateral.get_connection_data(source)
GeomLateral.write_connection_data(child, records)
assert records.RawBlock.tolist() == GeomLateral.get_connection_data(child).RawBlock.tolist()
```

A runnable example is `scripts/sa2d_connection_roundtrip.py`.

### Explicit physical authoring and clipping

`set_connection(..., weir_width=..., weir_coef=..., crest_profile=...)` requires
explicit physical inputs. `crest_profile` is a DataFrame with `Station` and
`Elevation`. Supply both exact existing area names and finite line coordinates.
The historical width 100, coefficient 3 and zero crest are only available with
`allow_defaults=True`; `DefaultsUsed` records which fields used that choice.
These numbers are compatibility defaults, not qualified physical geometry.
Callers supplying the former implicit defaults must opt in or provide measured
parameters. Use culvert, gate, bridge and profile setters for specialized edits.

`classify_connections(geom_file, child_boundary, retained_area_names=None,
tolerance=0)` returns a GeoDataFrame with `Name`, `From`, `To`, `action`, `reason`
and support `geometry`. The child geometry must use the source horizontal CRS
and model units. Width-expanded line support and explicit culvert barrel
coordinates are considered; unknown gate/bridge/breach support blocks the edit.
Actions are `keep`, `drop`, `block`. Every decision has a stable reason code.
Positive tolerance guards external separation; it does not excuse a physical
footprint crossing the child perimeter. Named endpoints must remain present.

`GeomStorage.clip_2d_flow_area(geom_file, flow_area_name, geometry,
containment_tolerance=0, create_backup=True)` stages all changes, retains internal
records exactly and explicitly reports fully external removals. Partial or
unknown affected support raises a reason-bearing error before changing the
original. Unrelated areas and connections are retained. Its return value uses
the same decision columns; `attrs['backup_path']` identifies the backup and
`attrs['attachment_status']` remains `CONNECTION_ATTACHMENT_UNVERIFIED`.
It accepts a contained Polygon; hole-aware/multipart perimeter authoring remains
outside this API. Existing `set_2d_flow_area_perimeter()` stays compatible and
does not provide this connection-classification workflow.

Text retention does not establish attachment or hydraulic equivalence. After
fresh native preprocessing, inspect `HdfStruc.get_connection_attachments()`.
Missing native evidence remains unverified; an offset line inside only one area
cannot establish the other attachment. Forward flow, tailwater reversal, wet/dry
transitions and engineer-selected WSE/volume/peak gates still need hydraulic
qualification against an unsplit control.

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

<a id="geomlevee"></a>

## Cross-section levees

`GeomLevee` is not a public class. Use `GeomCrossSection.get_levees()` and
`GeomCrossSection.set_levees()`; their full contracts appear below.

Levee station-elevation parsing and modification.

### Methods

- `GeomCrossSection.get_levees(...)` - Read left/right levee points; unset points are NaN
- `GeomCrossSection.set_levees(...)` - Write explicitly selected left/right station and elevation values

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

## Complete source reference

The sections above explain common operations. The source-derived reference below
includes the remaining public methods and their full signatures. Method-specific
prerequisites and return contracts take precedence over abbreviated summaries.

### GeomParser source reference

::: ras_commander.geom.GeomParser.GeomParser
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - create_backup
        - extract_comma_list
        - extract_keyword_value
        - extract_river_reach
        - format_fixed_width
        - get_1d_footprint
        - get_geom_title
        - get_river_centerlines
        - get_xs_cut_lines
        - identify_section
        - interpret_count
        - parse_fixed_width
        - rollback_geometry
        - safe_write_geometry
        - set_geom_title
        - update_timestamp
        - validate_river_reach_rs

### GeomPreprocessor source reference

::: ras_commander.geom.GeomPreprocessor.GeomPreprocessor
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - clear_geompre_files
        - clear_geompre_hdf
        - invalidate_legacy_geometry_hdf_preprocessor_cache
        - run_geometry_preprocessor

### GeomLandCover source reference

::: ras_commander.geom.GeomLandCover.GeomLandCover
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_base_mannings_n
        - get_region_mannings_n
        - override_2d_mannings_n
        - replace_base_mannings_n
        - set_base_mannings_n
        - set_mannings_region_polygons
        - set_region_mannings_n

### ManningsFromLandCover source reference

::: ras_commander.geom.ManningsFromLandCover.ManningsFromLandCover
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - assign
        - default_landcover_classification_table
        - default_mannings_table
        - preview

### GeomCrossSection source reference

::: ras_commander.geom.GeomCrossSection.GeomCrossSection
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - build_cross_section
        - format_blocked_obstructions
        - get_bank_stations
        - get_blocked_obstructions
        - get_cross_sections
        - get_expansion_contraction
        - get_ineffective_flow
        - get_levees
        - get_mannings_n
        - get_station_elevation
        - get_xs_coords
        - get_xs_htab_params
        - interpolate_cross_section
        - interpolate_station_elevation
        - optimize_xs_htab_from_results
        - parse_blocked_obstructions
        - set_all_xs_htab_params
        - set_bank_stations
        - set_blocked_obstructions
        - set_expansion_contraction
        - set_ineffective_flow
        - set_levees
        - set_mannings_n
        - set_station_elevation
        - set_xs_htab_params
        - validate_blocked_obstructions_hdf

### CrossSectionBankStations source reference

::: ras_commander.geom.GeomCrossSection.CrossSectionBankStations
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### CrossSectionBuildInput source reference

::: ras_commander.geom.GeomCrossSection.CrossSectionBuildInput
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### CrossSectionBuildResult source reference

::: ras_commander.geom.GeomCrossSection.CrossSectionBuildResult
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### CrossSectionManningsN source reference

::: ras_commander.geom.GeomCrossSection.CrossSectionManningsN
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### CrossSectionReachLengths source reference

::: ras_commander.geom.GeomCrossSection.CrossSectionReachLengths
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false

### GeomStorage source reference

::: ras_commander.geom.GeomStorage.GeomStorage
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - clip_2d_flow_area
        - get_2d_flow_area_settings
        - get_elevation_volume
        - get_storage_area_polygons
        - get_storage_areas
        - repair_viewing_rectangle_from_2d_areas
        - replace_breaklines
        - set_2d_flow_area_perimeter
        - set_2d_flow_area_settings
        - set_breaklines
        - set_elevation_volume

### GeomProjection source reference

::: ras_commander.geom.GeomProjection.GeomProjection
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - reproject_geometry
        - reproject_model_geometry

### GeomLateral source reference

::: ras_commander.geom.GeomLateral.GeomLateral
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - classify_connections
        - delete_connection
        - get_bridge_approach_xs
        - get_bridge_data
        - get_bridge_deck
        - get_bridge_piers
        - get_bridge_xs
        - get_connection_culverts
        - get_connection_data
        - get_connection_gates
        - get_connection_line_coords
        - get_connection_profile
        - get_connections
        - get_lateral_structures
        - get_weir_profile
        - set_bridge_approach_xs
        - set_bridge_coefficients
        - set_bridge_deck
        - set_bridge_piers
        - set_bridge_xs
        - set_connection
        - set_connection_culverts
        - set_connection_gates
        - set_connection_profile
        - set_connection_profile_from_terrain
        - write_connection_data

### GeomInlineWeir source reference

::: ras_commander.geom.GeomInlineWeir.GeomInlineWeir
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_gates
        - get_profile
        - get_weirs

### GeomBridge source reference

::: ras_commander.geom.GeomBridge.GeomBridge
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_abutment
        - get_approach_sections
        - get_bridge_opening_xs
        - get_bridges
        - get_coefficients
        - get_deck
        - get_htab
        - get_htab_dict
        - get_hydraulic_methods
        - get_piers
        - optimize_all_structures_from_results
        - optimize_htab_from_results
        - set_abutments
        - set_all_structures_htab
        - set_approach_sections
        - set_coefficients
        - set_deck
        - set_htab
        - set_hydraulic_methods
        - set_piers

### GeomCulvert source reference

::: ras_commander.geom.GeomCulvert.GeomCulvert
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_adjacent_cross_sections
        - get_all
        - get_culverts
        - set_adjacent_ineffective_flow
        - set_culvert
        - set_culverts

### GeomCulvertGIS source reference

::: ras_commander.geom.GeomCulvertGIS.GeomCulvertGIS
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - mesh_cell_min_from_terrain
        - reconstruct_barrels
        - validate_2d_inverts
        - validate_placement

### GeomHtabUtils source reference

::: ras_commander.geom.GeomHtabUtils.GeomHtabUtils
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - calculate_optimal_structure_htab
        - calculate_optimal_xs_htab
        - get_structure_htab_defaults
        - get_xs_htab_defaults
        - validate_structure_htab_params
        - validate_xs_htab_params

### GeomHtab source reference

::: ras_commander.geom.GeomHtab.GeomHtab
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_optimization_report
        - optimize_all_htab_from_results
        - optimize_structures_htab_from_results
        - optimize_xs_htab_from_results

### GeomMetadata source reference

::: ras_commander.geom.GeomMetadata.GeomMetadata
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_geometry_counts

### GeomReferenceFeatures source reference

::: ras_commander.geom.GeomReferenceFeatures.GeomReferenceFeatures
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - add_reference_lines
        - add_reference_lines_from_longitudinal_line
        - add_reference_points
        - generate_reference_lines_from_longitudinal_line
        - get_reference_lines
        - get_reference_points
        - replace_reference_lines

### GeomBcLines source reference

::: ras_commander.geom.GeomBcLines.GeomBcLines
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - add_bc_lines
        - delete_bc_line
        - rename_bc_line
        - replace_bc_lines

### GeomPipeNetwork source reference

::: ras_commander.geom.GeomPipeNetwork.GeomPipeNetwork
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - set_conduit_dimensions
        - set_pump_group_hq_curve


### RasGeometry source reference

::: ras_commander.RasGeometry.RasGeometry
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_bank_stations
        - get_connection_gates
        - get_connection_weir_profile
        - get_connections
        - get_cross_sections
        - get_expansion_contraction
        - get_lateral_structures
        - get_lateral_weir_profile
        - get_mannings_n
        - get_station_elevation
        - get_storage_areas
        - get_storage_elevation_volume
        - interpolate_cross_section
        - interpolate_station_elevation
        - set_bank_stations
        - set_connection_weir_profile
        - set_expansion_contraction
        - set_station_elevation


### RasGeometryUtils source reference

::: ras_commander.RasGeometryUtils.RasGeometryUtils
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - create_backup
        - extract_comma_list
        - extract_keyword_value
        - format_fixed_width
        - identify_section
        - interpret_count
        - parse_fixed_width
        - update_timestamp
        - validate_river_reach_rs


### RasBreach source reference

::: ras_commander.RasBreach.RasBreach
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - create_breach_block
        - list_breach_structures_plan
        - read_breach_block
        - set_breach_geom
        - update_breach_block


### RasCrossSections source reference

::: ras_commander.RasCrossSections.RasCrossSections
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_points


### VerticalTransform source reference

::: ras_commander.RasCrossSections.VerticalTransform
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - apply
