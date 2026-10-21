# HDF Subpackage Contract

This file is the canonical local instruction file for `ras_commander/hdf/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-RAS geometry and results HDF access.

## Module Families

- Core helpers: `HdfBase`, `HdfUtils`, `HdfPlan`
- Geometry readers: `HdfMesh`, `HdfXsec`, `HdfBndry`, `HdfStruc`, `HdfHydraulicTables`
- Project extent / footprint: `HdfProject`
- Results readers: `HdfResultsPlan`, `HdfResultsMesh`, `HdfResultView`, `HdfResultsXsec`, `HdfResultsBreach`, `HdfResultsSediment`
- Infrastructure and land surface: `HdfPipe`, `HdfPump`, `HdfInfiltration`, `HdfLandCover`
- Plotting and analysis: `HdfPlot`, `HdfResultsPlot`, `HdfBenefitAreas`, `HdfChannelCapacity`, `HdfFluvialPluvial`

- `HdfFluvialPluvial.generate_fluvial_pluvial_polygons()` converts native polygon
  areas using both projected horizontal CRS axis factors before applying acre
  thresholds. Missing/geographic CRS skips filtering with a warning; unresolved
  projected units and other processing failures log contextual ERROR plus traceback
  and return an empty GeoDataFrame, discarding partial output. Existing upstream
  input/decorator validation exceptions remain unchanged. No status attributes are added.


## Implementation Rules

- Follow the existing static-class pattern.
- Public methods should use `@staticmethod`, `@log_call`, and `@standardize_input(...)` when the surrounding module already does.
- Keep heavy dependencies lazy-loaded inside methods when practical:
  - `geopandas`
  - `shapely`
  - `xarray`
  - `matplotlib`
  - `scipy`
- Use `h5py.File(..., "r")` context managers for direct inspection. RAS-owned
  authoring must use the applicable native HEC-RAS API unless a method is
  explicitly version/schema-qualified as a recovery or solver-temporary-file
  operation.
- Distinguish clearly between `plan_hdf` inputs and `geom_hdf` inputs when adding or modifying decorators.

## Input And Output Rules

- Pump operation and hydrograph readers use only their owning DSS Profile or
  DSS Hydrograph block's stored timestamps (seconds or milliseconds), falling
  back to that block's finite nondecreasing numeric `Time` in days only when
  timestamps are absent. Numeric axes expose `time_units` on DataFrames or
  `time.units` on DataArrays. Missing, malformed or mismatched axes raise;
  never borrow Base Output time or synthesize integer row indexes.

- Accept the flexible HDF-facing input forms already used in this package: plan numbers, prefixed plan numbers, paths, and open HDF handles where the decorator pattern already allows them.
- Return pandas or GeoPandas objects in the shapes established by nearby code. Do not invent a new container style for one method unless the surrounding API also changes.
- Log read failures with enough file context to debug the issue.
- Packed `Info`/`Parts`/`Points` features: Parts offsets are relative to the
  feature's own point slice and bounded by its point count. Resolve offsets for
  the complete feature, never per part or by whether values fit the global
  range; legacy global offsets are accepted only when all parts together cover
  the point slice exactly. `_packed_parts.resolve_feature_part_ranges()` does
  this for `HdfBndry.get_refinement_regions()` and `HdfStruc.get_structures()`.
- `HdfStruc.get_structures()` returns a MultiLineString (one line per stored
  part, no connecting segment) for a structure whose Centerline Info Part
  Count is greater than 1; single-part centerlines remain LineStrings.
- A zero-point centerline (Info Point Count 0, e.g. lateral structures in
  Muncie, Baxter, OrleansEx) is a valid empty range, as in the native engine.
  `get_structures()` returns None geometry for it (the missing-geometry
  convention used by `HdfPipe` and the other readers). Out-of-range starts,
  negative counts, one-point centerlines and inconsistent Parts still raise.

## Common Entry Points

- Plan metadata and compute messages: `HdfResultsPlan`
- Simulation start time: `HdfBase.get_simulation_start_time()` resolves across versions — 6.x
  `Plan Information/Simulation Start Time` attr, then 5.0.x `Time Window` ("<start> to <end>"),
  then the first `Unsteady Time Series/Time Date Stamp`. Required by all 2D summary reads
  (`HdfResultsMesh.get_mesh_max_ws`/`get_mesh_summary_output`); 5.0.x plan HDFs omit the 6.x attr.
  It and `HdfBase.get_unsteady_timestamps()` accept a path or an open handle.
- 2D cell result arrays list ghost cells after the physical cells (IDs >= `Attributes/Cell Count`).
  Ghost values are placeholders (summary max WSE 0.0, NaN min elevation). `HdfResultsMesh` cell
  results exclude them by default (`include_ghost_cells=True` keeps them, flagged `is_ghost_cell`).
  `HdfMesh.get_mesh_cell_points()` still returns every center unless `include_ghost_cells=False`.
  Never pair cell results with the full `Cells Center Coordinate` array by position.
- 2D cell geometry and face geometry: `HdfMesh`
- HEC-RAS 7.0 Linux solver-temporary face property-table recovery:
  `HdfMesh.write_linux_tmp_face_property_tables()`,
  `extend_linux_tmp_face_property_tables()`,
  `transform_linux_tmp_face_mannings_n()`,
  `sample_linux_tmp_face_mannings_n_from_landcover_curves()`, and
  `set_mesh_pinned_attribute()`. These APIs are restricted to verified
  `HEC-RAS Results` `*.p##.tmp.hdf` files and always back up and validate.
- The historical `set_mesh_face_property_tables()`,
  `extend_face_property_tables()`, `set_face_mannings_n_values()`, and
  `recompute_face_mannings_n_from_landcover_curves()`, and
  `pin_property_tables()` names are compatibility wrappers through v1.1.x.
  The recompute name delegates to
  `sample_linux_tmp_face_mannings_n_from_landcover_curves()`; none will be
  removed before v1.2.0.
- 2D face spatial filtering (polygon mask): `HdfMesh.get_face_ids_in_polygon()`, `get_face_ids_in_calibration_region()`
- Both `extend_linux_tmp_face_property_tables()` and
  `transform_linux_tmp_face_mannings_n()` accept optional `polygon` and
  `region_name` parameters for selective face application (precedence:
  `face_ids` > `region_name` > `polygon` > all faces).
- 2D results extraction: `HdfResultsMesh`
- Unsteady `HdfResultsQuery` velocity queries at integer time indexes prefer stored
  `Cell Velocity - Velocity X/Y` components per mesh. Validate their stored
  cell Location, time/geometry axes, physical count and velocity units; compute
  speed from those components. Legacy components and face reconstruction remain
  fallbacks when the stored components are absent. Malformed stored components
  raise errors instead of silently selecting reconstruction.
- Large 2D result access: `HdfResultsMesh.get_mesh_timeseries(...,
  return_type="view")` returns an immutable `HdfResultView`;
  `iter_mesh_timeseries()` emits untruncated bounded batches; and
  `get_mesh_summary_values()` returns native summary values without Shapely
  geometry. Eager results remain the default. A view owns no persistent HDF
  handle and validates its source fingerprint whenever it reads.
- 2D mobile-bed (sediment) results: `HdfResultsSediment` (`is_sediment_plan()`, `get_sediment_mesh_areas()`, `get_cell_bed_change()`/`get_cell_bed_elevation()`/`get_active_layer_grain_class()` -> GeoDataFrame, `get_bed_change_volumes()` -> erosion/deposition/net volume per area, `get_cell_bed_change_timeseries()` -> xr.DataArray). Reads the `Sediment Bed` output block; per-cell arrays align with computed `Cells Surface Area` (zero-area ghost cells drop out of volume integrals). Covered by `examples/230_mesh_sensitivity_analysis.ipynb`.
- 1D cross section geometry and results: `HdfXsec`, `HdfResultsXsec`
- `HdfStruc.get_structures()` keeps one-based public `Structure ID` values,
  joining bridge coefficients by their native zero-based Attributes row IDs.
  Duplicate, noninteger or out-of-range coefficient IDs are errors.
- 1D river edge lines: `HdfXsec.get_river_edge_lines()` (stored `Geometry/River Edge Lines`);
  `HdfXsec.generate_river_edge_lines()` builds them from XS cut-line end points when none are
  stored (pure-Python equivalent of RASMapper "Create Edge Lines at XS Limits") — it returns a
  GeoDataFrame and does not write to the HDF. To author edge lines that HEC-RAS honors (real
  bank-line-anchored offset curves, with the group-level `Source Data Hash`), use
  `RasGeometryCompute.generate_edge_lines()`; there is deliberately no pure-Python writer, since a
  hand-written approximation carries no valid hash and HEC-RAS may silently recompute it.
- 1D XS interpolation surface: `HdfXsec.get_xs_interpolation_surface()` reads
  `Geometry/Cross Section Interpolation Surfaces` — one dissolved (Multi)Polygon per XS-to-XS TIN
  segment, with `us_xs_id` / `ds_xs_id` / `area` columns (triangle indices are local to each
  segment's point slice). Generate it with `RasGeometryCompute.generate_interpolation_surface()`.
- 1D river flow paths: `HdfXsec.get_river_flow_paths()` reads `Geometry/River Flow Paths`
  (`Flow Path Lines Info/Parts/Points`). Generate/backup with
  `RasGeometryCompute.generate_flow_paths()`.
- 1D model footprint polygons: `HdfXsec.get_1d_footprint()` closes left/right edge lines into a
  per-(River, Reach) polygon. Each end cap follows the real cut-line geometry of the end cross
  section, interior vertices included, so a bent cut line is not chorded straight across; when an
  edge-line end point does not land on a cut-line limit (possible for stored edge lines) that cap
  falls back to a straight chord. `edge_source='auto'|'stored'|'generate'`,
  `close_with_end_xs=False` for the legacy straight-chord closure, `dissolve=True` for a single
  (multi)polygon.
- True model extent polygon: `HdfProject.get_project_extent(..., geometry_type='footprint')`
  unions 2D flow-area perimeters, storage areas, and 1D reach footprints (multipart when multiple
  areas/reaches).
  Missing HDF components fall back to companion plain-text geometry by default; pass
  `fallback_to_plaintext=False` for strict HDF-only extraction.
  Use `include_1d=False` / `include_2d=False` for 2D-only / 1D-only extents, and
  `buffer_percent=0` for the raw footprint. `fill_holes=True` (default, footprint mode) removes the
  thin interior sliver gaps left where 1D reach footprints and 2D flow areas overlap without
  aligning exactly — it drops interior rings only, never disconnected parts of a multipart model;
  pass `fill_holes=False` to keep the raw union. `geometry_type='bbox'` returns the legacy buffered
  bounding box (still used by `get_project_bounds_latlon` for data downloads).
- `HdfStruc.get_storage_area_polygons()` attaches the available project CRS
  through `HdfBase.get_projection()` without transforming the stored coordinates.
  Unknown CRS remains unset; no geographic default is assigned.
- Land cover and infiltration preprocessing: `HdfLandCover`, `HdfInfiltration`
- Native infiltration geometry authoring:
  `HdfInfiltration.create_infiltration_override_regions()`,
  `get_infiltration_region_overrides()`,
  `set_infiltration_base_overrides()`,
  `set_infiltration_region_overrides()`,
  `scale_infiltration_base_overrides()`, and
  `scale_infiltration_region_overrides()` for HEC-RAS 6.x and 7.0.x. Native
  Base Overrides are the geometry-wide class-to-parameter fallback;
  per-region values are separate native parameter tables. Region polygons
  containing holes fail closed because HEC-RAS 6.0–7.0.1 drops interior-ring
  topology during native parameter resampling.
  Native sidecar editing uses `set_infiltration_sidecar_parameters()` and
  `scale_infiltration_sidecar_parameters()`. Historical spellings remain
  working compatibility wrappers through v1.1.x; do not recreate or
  selectively delete `/Geometry/Infiltration` datasets with `h5py`.

## Testing

- Use real example HDF files when validating behavior.
- Prefer targeted tests over synthetic HDF fixtures unless a regression cannot be reproduced against real examples.

## Packed perimeter offsets

- Collection-level `HdfMesh.get_mesh_areas()` resolves Parts offsets for each
  complete feature through `HdfBase._feature_part_ranges()`. Native local
  offsets are valid when every part lies within the feature's point count
  (gaps and unused vertices allowed, as in the native engine) and take
  precedence. Legacy global offsets remain supported only when all parts
  exactly cover the feature's point slice. Any other layout, including mixed
  conventions, fails closed.

## Pipe network reads

- `HdfPipe.get_pipe_network_timeseries(..., pipe_network_name=None,
  output_block="DSS Hydrograph Output")` defaults to the first geometry Attributes
  network. Base and DSS use only their own timestamps; absent/mismatched axes raise.
- Domain comes from stored Location plus geometry count. Positional `location`
  remains available; `node_id`/`conduit_id` hold exact Node/Conduit Indices.
  `extract_timeseries_for_node` and `extract_timeseries_for_conduit` select stored IDs,
  accept network/block options and raise for unknown IDs. Both preserve the
  explicit `ras_object` for positional and keyword `plan_hdf_path` plan numbers.
- `get_pipe_network_summary(..., pipe_network_name=None)` returns literal Base
  summary rows and volume-accounting attributes in long form. Row/column ordinals,
  labels, units, values, shapes and raw metadata are retained. Volume-accounting
  rows carry null units; the `Vol Accounting in` row names the volume unit.
  `get_pipe_conduits` validates terrain-profile start/count slices and refuses
  partially present profile tables. The legacy
  Summary/Pipe Network table keeps its historical return shape when present
  without geometry network identities. One-row minima never
  receive a fabricated time row; absent Location does not imply a typed domain.
- Pipe geometry defaults to the stored CRS; explicit `crs` overrides it. Parts
  offsets are relative to each feature's Points slice. Unqualified multipart polygon
  topology refuses. Network Node Points resolve global stored IDs, and Cell Property
  Table rows align by cell position, not their separate lookup-table Info Index.
- `get_pipe_profile` uses a global conduit geometry row (the stored conduit ID),
  not its position in a selected network. Optional inlets can be absent; a present
  inlet group missing Attributes raises rather than disappearing silently.
