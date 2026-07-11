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
- Use `h5py.File(..., "r")` context managers for direct file access.
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
- 2D face property table write (Manning's n vs Elevation): `HdfMesh.set_mesh_face_property_tables()`, `extend_face_property_tables()`, `set_face_mannings_n_values()`, `pin_property_tables()`
- 2D face spatial filtering (polygon mask): `HdfMesh.get_face_ids_in_polygon()`, `get_face_ids_in_calibration_region()`
- Both `extend_face_property_tables()` and `set_face_mannings_n_values()` accept optional `polygon` and `region_name` parameters for selective face application (precedence: `face_ids` > `region_name` > `polygon` > all faces)
- 2D results extraction: `HdfResultsMesh`
- 2D mobile-bed (sediment) results: `HdfResultsSediment` (`is_sediment_plan()`, `get_sediment_mesh_areas()`, `get_cell_bed_change()`/`get_cell_bed_elevation()`/`get_active_layer_grain_class()` -> GeoDataFrame, `get_bed_change_volumes()` -> erosion/deposition/net volume per area, `get_cell_bed_change_timeseries()` -> xr.DataArray). Reads the `Sediment Bed` output block; per-cell arrays align with computed `Cells Surface Area` (zero-area ghost cells drop out of volume integrals). Covered by `examples/230_mesh_sensitivity_analysis.ipynb`.
- 1D cross section geometry and results: `HdfXsec`, `HdfResultsXsec`
- 1D river edge lines: `HdfXsec.get_river_edge_lines()` (stored `Geometry/River Edge Lines`);
  `HdfXsec.generate_river_edge_lines()` builds them from XS cut-line end points when none are
  stored (pure-Python equivalent of RASMapper "Create Edge Lines at XS Limits");
  `HdfXsec.set_river_edge_lines()` writes edge lines back into the geometry HDF in HEC-RAS's native
  schema — `Polyline Info/Parts/Points` with the `Row`/`Column`/`Feature Type` attrs and no
  `Attributes` dataset (HEC-RAS stores none for this layer; `get_river_edge_lines` derives bank side
  from row order). No RASMapper GUI is needed. It does NOT write the group-level `Source Data Hash`
  or update the `.rasmap`, so HEC-RAS may recompute these on next open; for edge lines HEC-RAS treats
  as authoritative, run its own headless geometry completion (`RasProcess.exe CompleteGeometry`),
  which also builds the XS interpolation surface.
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
  `buffer_percent=0` for the raw footprint. `geometry_type='bbox'` returns the legacy buffered
  bounding box (still used by `get_project_bounds_latlon` for data downloads).
- Land cover and infiltration preprocessing: `HdfLandCover`, `HdfInfiltration`
- Infiltration group authoring: `HdfInfiltration.create_infiltration_group()`, `HdfInfiltration.set_infiltration_baseoverrides()`

## Testing

- Use real example HDF files when validating behavior.
- Prefer targeted tests over synthetic HDF fixtures unless a regression cannot be reproduced against real examples.
