# HDF Subpackage Contract

This file is the canonical local instruction file for `ras_commander/hdf/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-RAS geometry and results HDF access.

## Module Families

- Core helpers: `HdfBase`, `HdfUtils`, `HdfPlan`
- Geometry readers: `HdfMesh`, `HdfXsec`, `HdfBndry`, `HdfStruc`, `HdfHydraulicTables`
- Project extent / footprint: `HdfProject`
- Results readers: `HdfResultsPlan`, `HdfResultsMesh`, `HdfResultsXsec`, `HdfResultsBreach`, `HdfResultsSediment`
- Infrastructure and land surface: `HdfPipe`, `HdfPump`, `HdfInfiltration`, `HdfLandCover`
- Plotting and analysis: `HdfPlot`, `HdfResultsPlot`, `HdfBenefitAreas`, `HdfChannelCapacity`, `HdfFluvialPluvial`

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

- Accept the flexible HDF-facing input forms already used in this package: plan numbers, prefixed plan numbers, paths, and open HDF handles where the decorator pattern already allows them.
- Return pandas or GeoPandas objects in the shapes established by nearby code. Do not invent a new container style for one method unless the surrounding API also changes.
- Log read failures with enough file context to debug the issue.

## Common Entry Points

- Plan metadata and compute messages: `HdfResultsPlan`
- Simulation start time: `HdfBase.get_simulation_start_time()` resolves across versions — 6.x
  `Plan Information/Simulation Start Time` attr, then 5.0.x `Time Window` ("<start> to <end>"),
  then the first `Unsteady Time Series/Time Date Stamp`. Required by all 2D summary reads
  (`HdfResultsMesh.get_mesh_max_ws`/`get_mesh_summary_output`); 5.0.x plan HDFs omit the 6.x attr.
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
- 2D mobile-bed (sediment) results: `HdfResultsSediment` (`is_sediment_plan()`, `get_sediment_mesh_areas()`, `get_cell_bed_change()`/`get_cell_bed_elevation()`/`get_active_layer_grain_class()` -> GeoDataFrame, `get_bed_change_volumes()` -> erosion/deposition/net volume per area, `get_cell_bed_change_timeseries()` -> xr.DataArray). Reads the `Sediment Bed` output block; per-cell arrays align with computed `Cells Surface Area` (zero-area ghost cells drop out of volume integrals). Covered by `examples/230_mesh_sensitivity_analysis.ipynb`.
- 1D cross section geometry and results: `HdfXsec`, `HdfResultsXsec`
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
  unions 2D flow-area perimeters with 1D reach footprints (multipart when multiple areas/reaches).
  Use `include_1d=False` / `include_2d=False` for 2D-only / 1D-only extents, and
  `buffer_percent=0` for the raw footprint. `fill_holes=True` (default, footprint mode) removes the
  thin interior sliver gaps left where 1D reach footprints and 2D flow areas overlap without
  aligning exactly — it drops interior rings only, never disconnected parts of a multipart model;
  pass `fill_holes=False` to keep the raw union. `geometry_type='bbox'` returns the legacy buffered
  bounding box (still used by `get_project_bounds_latlon` for data downloads).
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
