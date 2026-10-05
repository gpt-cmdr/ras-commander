# HDF Modules

Classes for reading and processing HEC-RAS HDF result files.

## SA/2D native attachment evidence

Call `HdfStruc.get_connection_attachments(hdf_path, connections_df=None,
ras_object=None)` with an explicit HDF path or plan number. Plan numbers resolve
through `plan_df` to results; explicit geometry HDF paths are also accepted and
normally report unverified attachment after preprocessing alone. Supply the
expected `Name`, `From`, `To` inventory from `GeomLateral.get_connection_data()`
so a missing imported connection receives a failure row.

The return DataFrame contains those identities, `from_cells`, `from_faces`,
`to_cells`, `to_faces`, `attachment_verified`, `reason_code`,
`orientation_verified`, `flux_sign_verified`, `evidence_paths`, `details`,
`source_hdf` and `native_version`. IDs are tuples of zero-based mesh-local native
indices; repeated segment cells are preserved. The native headwater/tailwater
cell lists and face-point chains must map exactly to active cells and their
incident faces in the named areas. Geographic proximity never establishes
attachment. Absent, ambiguous, wrong-area, malformed, inactive or unsupported
native evidence reports `CONNECTION_ATTACHMENT_UNVERIFIED`.

Positive evidence is qualified on actual HEC-RAS 6.6 BaldEagleCrkMulti2D results.
Three internal levees were verified on both sides. Its geometry-only
preprocessing output lacked those persisted records. The storage-to-2D dam and
unqualified versions remain unverified. A caller must establish that results
are fresh for the authored geometry using input hashes and native compute
receipts; this reader does not certify source currentness. Orientation and flow
sign are separate and remain explicitly false in this interface.

Use `scripts/qualify_sa2d_attachment.py` in a fresh disposable workspace:

```text
uv run python scripts/qualify_sa2d_attachment.py --project <source-copy> --workspace <new-workspace> --plan-number 04 --ras-exe <installed-Ras.exe> --max-wait 120 --compute-start 1999-01-01T12:00:00
```

The optional five-minute compute collects result-side native connectivity; it
does not qualify seam conveyance. Without it, the script records preprocessing
evidence and an explicit unverified outcome. Source hashes, runtime/TCU status,
elapsed time and native receipts are retained in `sa2d_attachment_receipt.json`.
Run the script under Wine Python in `fim-hecras-wine:6.6-clb-v8` with the new
library installed for intended-runtime qualification. Mount source projects
read-only and choose a fresh output variant; fleet orchestration remains the
coordinator's responsibility.

## Core Classes

### HdfBase

Base functionality for HDF file operations.

- `get_dataset_info(file_path, group_path="/")` - Print HDF structure
- `get_attrs(hdf_file, attr_path)` - Get attributes at path
- `get_projection(hdf_path)` - Get coordinate system
- `get_result_unit_metadata(hdf_path, *, strict=True)` - Read normalized unit
  metadata and source evidence from a standalone plan-result HDF

Datetime parsers are provided by [`HdfUtils`](#hdfutils).

`get_result_unit_metadata()` is deliberately a result-HDF fallback. When the
full project is available, use `RasPrj.get_project_units()` and treat the text
`.prj` marker as authoritative. The HDF reader never defaults missing metadata
to English units. It raises on missing, unrecognized, geometry-only, or
contradictory metadata unless `strict=False`, which returns the raw evidence
and an unresolved status for audit workflows.

### HdfPlan

Plan-level information from HDF files.

- `get_plan_information(hdf_path)` - Get plan metadata
- `get_plan_start_time(hdf_path)` / `get_plan_end_time(hdf_path)` - Get start/end times
- `get_plan_parameters(hdf_path)` - Get computation parameters
- `get_2d_flow_options(hdf_path)` - Get 2D equation set, initial condition time, tolerances, and solver options from computed HDF output

### HdfProject

Project-wide extent and coordinate-system helpers.

- `get_project_extent(hdf_path=None, include_1d=True, include_2d=True,
  include_storage=True, buffer_percent=50.0, buffer_x_percent=None,
  buffer_y_percent=None, geometry_type="footprint", fill_holes=True, *,
  geom_path=None, fallback_to_plaintext=True, ras_object=None)` - Return a
  footprint or buffered bounding box and its project-coordinate bounds.
- `get_project_bounds_latlon(hdf_path=None, buffer_percent=50.0,
  include_1d=True, include_2d=True, include_storage=True, project_crs=None, *,
  geom_path=None, fallback_to_plaintext=True, ras_object=None)` - Return the
  project bounds in WGS84.
- `export_extent_geojson(hdf_path, output_path, buffer_percent=50.0, *,
  geom_path=None, fallback_to_plaintext=True, ras_object=None)` - Export the
  project extent as GeoJSON.

Extent extraction prefers usable HDF geometry independently for 1D reaches,
2D flow areas, and storage areas. With the default
`fallback_to_plaintext=True`, a matching plain-text `.g##` file supplies only
components unavailable from HDF; a text-only 1D footprint is constructed from
cross-section cut-line endpoints. Set `fallback_to_plaintext=False` for strict
HDF-only behavior. `include_storage=True` is also component-aware: HDF storage
polygons are preferred and companion text geometry is used only when needed.

## Mesh Operations

### HdfMesh

Mesh geometry data. See [Meshing](meshing.md) for the diagnostic-to-repair
workflow and operation-specific failure limits.

`get_mesh_perimeter_faces(hdf_path, mesh_name, ras_object=None)` returns every
native perimeter face of a named 2D area as a GeoDataFrame, including faces
without an assigned BC line. It preserves native `face_id`, `cell0`, `cell1`,
`interior_cell_id`, `exterior_cell_id`, face-point endpoint IDs, `face_length`,
and complete face geometry. Physical cells use native `Attributes/Cell Count`;
ghost cell IDs are retained rather than classified from surface area.

Nullable `bc_line_id`, `bc_line_name`, and `bc_line_type` come from native BC
associations. The geometry BC type (for example `External`) is distinct from
the flow forcing type. Duplicate ownership, stale face/endpoints, non-perimeter
assignments, and missing association tables when BC lines exist raise errors.
It does not infer attachment from proximity. Inspect `attrs['association_status']`
and `attrs['length_source']`; native length is in model units. Interior-hole
boundary faces are included by topology, but rings are not classified.

```python
from ras_commander.hdf import HdfMesh

faces = HdfMesh.get_mesh_perimeter_faces("child.g01.hdf", "Perimeter 1")
unassigned = faces.loc[faces.bc_line_id.isna()]
```

See `scripts/validate_perimeter_bc.py` for real-example native compilation and
source-preservation acceptance. Read only a current native compiled HDF after
editing geometry text.

- `get_mesh_area_names(hdf_path)` - List 2D flow areas
- `get_mesh_areas(hdf_path)` - Read named-area perimeters, with a strictly
  validated collection-level fallback for affected 6.2/6.3-era geometry HDFs
- `diagnose_mesh_layout(hdf_path, program_version=None)` - Report version
  evidence, detected layout, dataset paths, and per-capability status for area
  names, perimeters, cell centers, face topology, and cell polygons
- `get_mesh_cell_polygons(hdf_path, strict=False)` - Get cell polygons as a
  GeoDataFrame; warnings and the equality-safe tuple of record dictionaries in
  `result.attrs["cell_polygon_diagnostics"]` expose physical cells that were
  omitted or ambiguously polygonized. Use `diagnose_mesh_cell_polygons()` when
  a DataFrame is preferred.
- `diagnose_mesh_cell_polygons(hdf_path)` - Report native cell IDs, face IDs,
  polygon counts, and reason codes for physical-cell reconstruction problems
  and expected boundary-only records
- `get_mesh_cell_faces(hdf_path)` - Get cell face lines
- `get_mesh_cell_points(hdf_path)` - Get cell center points
- `find_nearest_cell(point, cell_points_gdf, mesh_name=None)` - Find nearest cell ID and distance using previously read cell centers
- `find_nearest_face(point, cell_faces_gdf, mesh_name=None)` - Find nearest face ID and distance using previously read faces
- `get_mesh_face_property_tables(hdf_path)` - Read face elevation/area/wetted-perimeter/Manning tables

Some delivered geometries created across the HEC-RAS 6.2/6.3 timeframe store
valid 2D flow-area perimeters only in the collection-level `Polygon Info`,
`Polygon Parts`, and `Polygon Points` datasets. `get_mesh_areas()` can recover
those perimeters after validating every offset, count, part range, coordinate,
ring closure, and multipart association. It does not repair malformed rings or
change their topology.

The same files may report `Complete Geometry=True` while omitting the named-area
face-connectivity datasets. In that state, `diagnose_mesh_layout()` reports the
perimeter as `collection_fallback` and face/cell-polygon topology as
`not_present`. `get_mesh_cell_faces()` and `get_mesh_cell_polygons()` return an
empty GeoDataFrame with a warning. They never infer connectivity from cell
centers or collection-level `Cell Info` / `Cell Points`. Public USACE changelogs
do not identify the exact producer defect or establish its first fixed release,
so dataset inspection—not a blanket version rule—selects the safe reader.

Detailed face linework can also fail to produce exactly one polygon for an
individual physical cell. The default reader preserves its historical output
shape but warns, retains the native zero-based cell IDs, and attaches a
diagnostic table to the result. Use `diagnose_mesh_cell_polygons()` to inspect
the affected IDs or `get_mesh_cell_polygons(..., strict=True)` when incomplete
or ambiguous physical-cell geometry must stop the workflow. One- and two-face
boundary-only records are reported separately and do not fail strict mode.
Never assume the GeoDataFrame row index is an exhaustive physical-cell mask,
and do not silently replace failed detailed geometry with a convex hull,
endpoint ring, or selected repaired component.

> **EXPERIMENTAL — not recommended for production or any other
> non-experimental use.** These direct writes have been tested only with
> HEC-RAS 7.0 April 2026 in one Windows-preprocess/Linux-solve
> `*.p##.tmp.hdf` workflow. All other HEC-RAS versions and workflows are
> untested. They are not general land-cover or geometry-authoring APIs.

The methods require `acknowledge_unsupported=True`, validate the exact
temporary-result role and schema, retain a unique full-file backup, emit a
runtime warning, and verify readback:

- `write_linux_tmp_face_property_tables(...)` - Replace selected temporary face tables
- `extend_linux_tmp_face_property_tables(...)` - Extend temporary tables and return a structured report
- `transform_linux_tmp_face_mannings_n(...)` - Transform only the temporary-table Manning column
- `sample_linux_tmp_face_mannings_n_from_landcover_curves(...)` - Apply the documented equal-class land-cover sampling heuristic
- `set_mesh_pinned_attribute(...)` - Set informational `Pinned` metadata; this does not protect edits from Windows preprocessing

The former names remain compatibility wrappers through v1.1.x and will not be
removed before v1.2.0:

| Compatibility name | Canonical replacement |
|---|---|
| `set_mesh_face_property_tables()` | `write_linux_tmp_face_property_tables()` |
| `extend_face_property_tables()` | `extend_linux_tmp_face_property_tables()` |
| `set_face_mannings_n_values()` | `transform_linux_tmp_face_mannings_n()` |
| `recompute_face_mannings_n_from_landcover_curves()` | `sample_linux_tmp_face_mannings_n_from_landcover_curves()` |
| `pin_property_tables()` | `set_mesh_pinned_attribute()` |

### HdfResultsMesh

2D mesh results.

- `get_mesh_max_ws(hdf_path, round_to="100ms")` - GeoDataFrame with `maximum_water_surface` and, when stored, `maximum_water_surface_time`
- `get_mesh_summary(hdf_path, var)` - GeoDataFrame for a named HEC-RAS summary variable, with cell or face geometry
- `get_mesh_summary_values(hdf_path, var)` - Read summary values and identifiers without constructing Shapely geometry
- `get_mesh_max_depth(hdf_path)` - Maximum depth from stored HEC-RAS `Depth`
  when present, otherwise derived in memory from `Water Surface - Cells Minimum
  Elevation`
- `get_mesh_max_face_v(hdf_path)` - Maximum face velocity
- `get_mesh_timeseries(hdf_path, mesh_name, var, truncate=True, *, time_selection=None,
  spatial_selection=None, return_type="xarray")` - Eager time series with
  source-coordinate HDF slicing, or an opt-in lazy `HdfResultView`
- `iter_mesh_timeseries(hdf_path, mesh_name, var, *, time_selection=None,
  spatial_selection=None, batch_size=None, max_chunk_bytes=16777216)` - Stream
  untruncated, bounded, time-major xarray batches

- `get_mesh_cells_timeseries(hdf_path, mesh_names=None, var=None, truncate=False, ras_object=None)` - Dictionary of mesh Datasets; select cells/faces afterward
- `get_mesh_faces_timeseries(hdf_path, mesh_name, truncate=True)` - Available face variables as one Dataset; select `face_velocity` and `face_id` afterward
- `get_profile_line_flow_timeseries(hdf_path, line_name, mesh_name=None, profile_lines_path=None, direction="absolute")` - Native Mapper named-line flow; inspect returned `selection_source`
- `get_profile_line_peak_flow(hdf_path, line_name, mesh_name=None, profile_lines_path=None, direction="absolute")` - Peak Q and time from the same native named-line extraction path

The canonical profile-line methods above require pythonnet/RasMapperLib. They
may return a native-associated precomputed hydrograph of unqualified provenance
or aggregate selected face flows; these have different signed/absolute-flow semantics. The native-associated
hydrograph is not independently established as solver-recorded and may be
observed data. Explicit solver-recorded Reference Lines HDF output is read with
`HdfResultsXsec.get_ref_lines_timeseries()`.
See [Profiles, hydrographs and reference locations](results-queries.md) for
method contracts and [batch workflows](../user-guide/2d-profile-and-reference-workflows.md)
for plot/export examples. HDF storage should not be confused with the method
used to calculate the stored quantity.

`get_mesh_max_depth()` logs one INFO source message per mesh. Stored `Depth` is
read only. The fallback is computed only in memory and does not create or write
`Depth` in the HDF. Temporary synthetic test HDFs are test artifacts; they are
not producer output and are labeled separately from pre-existing HEC-RAS result
fixtures.

The maximum methods have different temporal bases. `get_mesh_max_ws()` and
`get_mesh_max_face_v()` read native HEC-RAS Summary Output maxima, which are
tracked across the computation and can include peaks between saved
mapping/output timestamps. `get_mesh_max_depth()` instead reduces the retained
`Depth` series or derives depth from retained `Water Surface`; its maximum is
limited to those stored output times. See [Maximum values](../user-guide/hdf-data-extraction.md#maximum-values)
for an example and comparison with a time-series reduction.

### Bounded and lazy result reads

Existing calls to `get_mesh_timeseries()` still return an eager
`xarray.DataArray`. The optional `time_selection` and `spatial_selection`
arguments are pushed into the HDF read before materialization. Integer
selections preserve a length-one dimension; forward slices preserve source
cell/face identifiers.

Set `return_type="view"` to receive an `HdfResultView`. Creating the view reads
only HDF metadata—not result values—and does not retain an open file handle.
Each operation reopens the source read-only and verifies its size and
nanosecond modification time before and after the read, detecting ordinary
source replacement or modification. Available operations are `to_xarray()`, `to_numpy()`,
`to_pandas()`, optional `to_arrow()`, `iter_batches()`, `select()`, and bounded
`reduce("max"|"min"|"mean"|"argmax")`.

For `truncate=True`, eager conversion reads the selected HDF slab once and
trims zero-only leading/trailing rows in memory. Lazy `shape`, batching, and
reductions perform a bounded scan when the active window is needed. An all-zero
selection retains its full time extent, matching the historical eager API.
Truncation is evaluated over the selected spatial subset. `select(time=None)`
preserves a prior selection; pass `slice(None)` to reset it. NumPy and Python
integer indexes are both accepted. An explicit reduction `dtype` must be a
floating-point dtype so NaN/infinite filtering remains valid.

`iter_mesh_timeseries()` is intentionally untruncated: it emits every selected
source timestep once, in time-major batches. This makes batch reassembly
deterministic and avoids a hidden preliminary scan.

```python
from ras_commander import HdfResultsMesh

view = HdfResultsMesh.get_mesh_timeseries(
    "BaldEagleDamBrk.p03.hdf",
    "BaldEagleCr",
    "Water Surface",
    truncate=False,
    time_selection=slice(100, 200),
    return_type="view",
)

# Only one selected timestep and the first 5,000 cells are materialized.
snapshot = view.select(time=150, spatial=slice(0, 5_000)).to_xarray()

# Batch sizing targets 16 MiB of result values by default.
for batch in view.iter_batches():
    consume(batch)

# Geometry-free native summary output for database loading.
summary = HdfResultsMesh.get_mesh_summary_values(
    "BaldEagleDamBrk.p03.hdf",
    "Maximum Water Surface",
)
```

Prefer a native HEC-RAS summary dataset when it represents the requested
engineering statistic. A raw reduction over `Water Surface` is not always
semantically identical to HEC-RAS `Maximum Water Surface`; for example,
HEC-RAS may encode never-wet cells as zero in the summary while the time-series
array retains terrain-elevation values. Bounded reductions deliberately report
the selected raw dataset statistic and do not invent wet/dry semantics.

See the [result-shape and availability contract](../user-guide/hdf-data-extraction.md#result-shapes-and-availability)
for variable naming, coordinates, metadata, and missing-output behavior.

### HdfResultsProducts

Inspection and deterministic product contracts for completed unsteady result
HDFs.

- `inspect_result(hdf_path)` - Read an existing result HDF without mutation and
  fail closed on incomplete or conflicting completion evidence, inconsistent
  time axes, missing CRS or units, and mesh/result/topology misalignment
- `export(hdf_path, output_directory, *, resolution=None,
  max_dimension=2048, nodata=-9999.0, include_preview=True)` - Generate a
  checksum-pinned hydraulic product package without modifying the producer HDF

Current HEC-RAS results can establish completion with
`Event Conditions/Completed Successfully=True`. Older producer HDFs that do
not contain that attribute can establish completion with their embedded
`Complete Process` compute-message marker. An explicit false or malformed
attribute is never overridden by messages.

The returned inspection identifies whether maximum depth will be read from the
stored HEC-RAS `Depth` time series or derived in memory from `Water Surface -
Cells Minimum Elevation`. It also records `hydraulic_qaqc: not_evaluated`:
mechanical completion and product readiness are not engineering acceptance.

```python
from ras_commander import HdfResultsProducts

inspection = HdfResultsProducts.inspect_result("project.p02.hdf")
manifest = HdfResultsProducts.export(
    "project.p02.hdf",
    "project-p02-hydraulic-products",
)
```

`export()` supports completed unsteady HDFs with 2D flow areas. It writes a
common-grid trio of Cloud Optimized GeoTIFFs for maximum WSE, maximum depth, and
maximum adjacent-face velocity; a fixed-schema Arrow/Parquet boundary
hydrograph table; result metadata; numerical evidence; a WGS84 GeoJSON
footprint; and, by default, a depth preview. `pyarrow>=14.0` is a required core
dependency because Arrow and Parquet are part of the modern geospatial product
contract, not an optional fallback.

Raster dimensions are bounded twice: neither width nor height may exceed
`max_dimension`, and the total raster contains at most 16,777,216 cells. The
`nodata` argument is normalized to float32 before collision checks so a nearby
double-precision value cannot silently become equal to valid stored data.
Pixels are square at the exact selected resolution; when a footprint span is
not evenly divisible, raster bounds expand by less than one pixel on the right
or bottom rather than silently changing the requested cell size.

The source HDF is opened read-only and protected by point-in-time digest checks.
The files in the output directory are newly generated ras-commander derivative
artifacts; they are not newly generated HEC-RAS model output. The output
directory must not already exist. Assets are published without overwriting and
`hydraulic-products.json` is linked last, so consumers must use that manifest as
the package-complete marker. A package that lacks the manifest is incomplete.
Publication requires same-filesystem hard-link support and fails closed when
the destination filesystem cannot provide it.

The exporter preserves valid negative-datum WSE and uses 2D flow-area
footprints as raster support. It does not infer hydraulic acceptability:
`numerical-qaqc.json` preserves evidence while the manifest remains
`hydraulic_qaqc: not_evaluated`. A result with no boundary-condition series gets
a valid, empty Parquet table with the same schema rather than losing the asset.

Synthetic HDFs created by focused tests are labeled test artifacts. Real-file
integration uses pre-existing producer HDFs read-only and does not run HEC-RAS
or generate model output; it generates only temporary derivative packages.

## Plan Results

### HdfResultsPlan

Plan-level results.

- `get_runtime_data(hdf_path)` - Runtime statistics
- `get_volume_accounting(hdf_path)` - Volume accounting data
- `get_compute_messages(hdf_path)` - Computation messages
- `get_unsteady_info(hdf_path)` - Unsteady result metadata; use `HdfPlan.get_plan_parameters()` for plan parameters
- `is_steady_plan(hdf_path)` - Check if steady state
- `get_steady_profile_names(hdf_path)` - Get steady profile names
- `get_steady_wse(hdf_path)` - Get steady water surface elevations
- `get_steady_info(hdf_path)` - Get steady flow metadata

### HdfResultsXsec

1D cross-section results.

- `get_xsec_timeseries(hdf_path)` - All cross-section time series
- `get_xsec_summary(hdf_path)` - Cross-section summary data

## 1D Geometry

### HdfXsec

Cross-section and river geometry extraction from HDF.

- `get_cross_sections(hdf_path, ras_object=None)` - Extract cross-section
  geometries as a GeoDataFrame. Accepts a geometry HDF path or a plan selector;
  multipart cut lines are returned as `MultiLineString` without synthetic connectors.
- `get_xs_coords(hdf_path, river=None, reach=None, rs=None)` - Extract native
  station/elevation points as XYZ with point/station order, cut-line distance,
  Manning's n, bank classification, coordinate metadata, and source provenance
- `get_river_centerlines(hdf_path)` - Extract river centerlines as `LineString`
  or `MultiLineString` geometries
- `get_river_stationing(hdf_path)` - Calculate river stationing along centerlines
- `get_river_reaches(hdf_path)` - Return model 1D river reach lines with stable
  `river_id` and computed `length` columns
- `get_river_edge_lines(hdf_path)` - Return river edge lines
- `get_river_bank_lines(hdf_path)` - Extract river bank lines

## Structure Data

### HdfStruc

`HdfStruc.get_structures()` treats a native empty `Geometry/Structures` group,
or one containing only an empty `Property Tables` subgroup, as an empty layer.
It returns typed `Structure ID`/geometry columns, source CRS/group attributes and
`attrs["structure_status"]="empty_placeholder"`. Populated property tables,
unrecognized children, and incomplete nonempty layers remain hard errors; no
actual structure is silently skipped. Source files and native units are unchanged.


Structure geometry and SA/2D connections.

- `list_sa2d_connections(hdf_path, *, ras_object=None)` - List SA/2D connections with time-series results
- `get_structures(hdf_path, datetime_to_str=False)` - Structure geometry and available attributes as a GeoDataFrame
- `get_geom_structures_attrs(hdf_path)` - Stored geometry structure attributes as a DataFrame
- `get_storage_area_polygons(hdf_path, *, ras_object=None)` - Extract storage
  area polygons and attributes from geometry or plan HDF files, including
  multi-ring polygons with interior rings; returns an empty GeoDataFrame when no
  storage areas are present.

### HdfResultsBreach

Dam breach results.

- `get_breach_timeseries(hdf_path, structure)` - Breach time series
- `get_breach_summary(hdf_path, structure)` - Breach summary statistics
- `get_breaching_variables(hdf_path, structure)` - Breach geometry evolution
- `get_structure_variables(hdf_path, structure)` - Structure flow variables

### HdfStorageArea

Storage area volume-elevation curve extraction from HDF.

- `get_volume_elevation_curve(hdf_path, sa_name)` - Get volume-elevation curve for a storage area
- `get_storage_area_names(hdf_path)` - List storage areas in HDF

### HdfChannelCapacity

1D channel capacity analysis (multi-AEP).

- `analyze_channel_capacity(...)` - Run channel capacity analysis from geometry and result inputs; see the full signature below
- `compare_conditions(existing_results, proposed_results, level="segments")` - Compare previously analyzed channel conditions

### HdfStruc1D

1D structure result extraction from plan HDF results.

- `get_structure_max_values(hdf_path, river, reach, rs)` - Extract maximum headwater, tailwater, and flow for a bridge, culvert, inline weir, or inline control structure. Raises an actionable `ValueError` when the plan HDF has no steady/unsteady results, required cross-section result datasets are absent, or the requested structure is not present in the results.
- `list_1d_structures(hdf_path)` - List 1D structures identified from result markers. Returns an empty DataFrame quietly when no structures are present in an otherwise readable HDF.

For steady plans, `get_structure_max_values()` can use the flanking cross sections when the structure is represented in HDF `Node Info` instead of `Cross Section Attributes`. The returned `hw_source`, `tw_source`, and `flow_source` fields identify the result locations used.

### HdfHydraulicTables

Cross section property tables (HTAB).

- `get_xs_htab(hdf_path, river, reach, station)` - Get HTAB data

## Infrastructure

### HdfPipe

Pipe network analysis.

- `get_pipe_conduits(hdf_path)` - Get conduit geometry
- `get_pipe_nodes(hdf_path)` - Get node locations
- `get_pipe_network_timeseries(hdf_path, var)` - Network time series
- `get_pipe_network_summary(hdf_path)` - Network summary
- `get_pipe_profile(hdf_path, conduit_id)` - Get conduit profile

### HdfPump

Pump station analysis.

- `get_pump_stations(hdf_path)` - Get station locations
- `get_pump_groups(hdf_path)` - Get pump groups
- `get_pump_station_timeseries(hdf_path, name)` - Station time series
- `get_pump_station_summary(hdf_path)` - Station summary
- `get_pump_operation_timeseries(hdf_path, name)` - Operation history

## Analysis

### HdfFluvialPluvial

Fluvial-pluvial boundary analysis.

- `calculate_fluvial_pluvial_boundary(hdf_path, delta_t)` - Calculate boundary

### HdfInfiltration

Native infiltration authoring and read-only inspection.

**Geometry File Operations:**

- `get_preprocessed_infiltration(hdf_path, mesh_name=None, variable=...)` - Read solver-owned per-cell infiltration arrays
- `get_infiltration_baseoverrides(hdf_path)` - Retrieve the geometry-wide class-to-parameter fallback table
- `get_infiltration_calibration_regions(hdf_path)` - Read every region table in the bulk variable-oriented HDF view
- `get_infiltration_region_overrides(hdf_path, region_name=..., hecras_version=...)` - Read one selected region in the class-ordered native view
- `get_infiltration_region_names(hdf_path)` - Read stable region names
- `get_infiltration_region_polygons(hdf_path)` - Read stable region IDs, names, and polygon geometry
- `create_infiltration_override_regions(hdf_path, region_names, hecras_version=...)` - Create native geometry override regions from existing Manning-region polygons
- `set_infiltration_base_overrides(hdf_path, data, hecras_version=...)` - Set the native geometry-wide Base Overrides fallback
- `scale_infiltration_base_overrides(hdf_path, data, scale_factors, hecras_version=...)` - Scale active geometry-wide Base Overrides while preserving sentinel values
- `set_infiltration_region_overrides(hdf_path, data, region_name=..., hecras_version=...)` - Set one native region's parameter table without changing Base Overrides or other regions
- `scale_infiltration_region_overrides(hdf_path, data, scale_factors, region_name=..., hecras_version=...)` - Scale one selected region while preserving sentinel values

**Raster and Layer Operations:**

- `get_infiltration_layer_data(hdf_path)` - Get infiltration layer data from HDF
- `set_infiltration_sidecar_parameters(hdf_path, data, hecras_version=...)` - Set sidecar parameters through native RASMapper serialization
- `scale_infiltration_sidecar_parameters(hdf_path, data, scale_factors, hecras_version=...)` - Scale and save sidecar parameters natively
- `get_classification_polygons(hdf_path)` - Read infiltration sidecar classification polygon overrides
- `get_infiltration_map(hdf_path=None, ras_object=None)` - Read the
  infiltration raster map; without an explicit path, resolve the first usable
  `rasmap_df["infiltration_hdf_path"]`
- `calculate_soil_statistics(hdf_path)` - Process zonal statistics for soil analysis
- `get_soils_raster_stats(geom_hdf_path, soil_hdf_path=None, ras_object=None)` -
  Resolve the soil sidecar consistently; lookup failures retain the empty-frame
  recovery contract
- `get_soil_raster_stats(...)`, `get_infiltration_stats(...)`, and
  `get_landcover_raster_stats(...)` - Use the same status-aware sidecar resolver
  and empty-frame recovery contract

The compatibility names `create_infiltration_group()`,
`set_infiltration_baseoverrides()`, `set_infiltration_layer_data()`, and
`scale_infiltration_baseoverrides()` delegate to the canonical native APIs
through the v1.1.x compatibility window. The historical
`scale_infiltration_data()` name was ambiguous between a geometry HDF and an
infiltration sidecar and now fails closed with three explicit choices: the
geometry-wide, selected-region, or sidecar scaler.
These compatibility names will not be removed before v1.2.0.
Ras Commander never hand-authors or selectively deletes
`/Geometry/Infiltration` datasets.

**Soil Analysis:**

- `get_significant_mukeys(hdf_path, threshold)` - Identify mukeys above percentage threshold
- `calculate_total_significant_percentage(hdf_path)` - Compute total coverage
- `get_infiltration_parameters(hdf_path=None, mukey=None, ras_object=None)` - Get
  parameters for a specific mukey, with the same optional `rasmap_df` lookup
- `calculate_weighted_parameters(hdf_path)` - Compute weighted average parameters

**Data Export:**

- `save_statistics(data, path)` - Export soil statistics to CSV

### HdfLandCover

Land-cover sidecar and final Manning's n extraction.

- `get_landcover_raster_map(hdf_path)` - Read land-cover class IDs, names, and Manning's n values
- `set_landcover_mannings_n(hdf_path, mapping, hecras_version=...)` - Set sidecar Manning's n through native RASMapper serialization
- `sanitize_classification_names(hdf_path, raster_path=..., hecras_version="6.6")` - Opt in to HEC-RAS 6.6's native labels-only sanitizer. It preserves IDs, numeric parameters, and exact companion-TIFF bytes; a legacy V1 sidecar is saved as native V2, with the returned result retaining before/after mappings and a durable backup path. This method is qualified only for `6.6`/`6.6.0`; it never rebuilds or resamples the raster.
- `get_classification_polygons(hdf_path)` - Read land-cover sidecar classification polygon overrides
- `get_preprocessed_mannings_n(hdf_path)` - Read preprocessed cell-center Manning's n values from geometry HDF
- `audit_final_mannings_n(hdf_path, ...)` - Strictly audit solver-owned final cell/face Manning arrays
- `estimate_final_mannings_raster(hdf_path, ...)` - Build a non-authoritative visualization estimate

Compatibility mappings are retained through v1.1.x and will not be removed
before v1.2.0:

| Compatibility name | Canonical replacement |
|---|---|
| `set_landcover_raster_map()` | `set_landcover_mannings_n()` |
| `compute_final_mannings_raster()` | `estimate_final_mannings_raster()` for visualization, or `audit_final_mannings_n()` for solver evidence |

### HdfBndry

Boundary condition geometry.

- `get_bc_lines(hdf_path)` - Get BC lines
- `get_breaklines(hdf_path)` - Get breaklines. Zero- and one-point source records
  are excluded from line geometry and returned in `result.attrs["breakline_diagnostics"]`.
  Each diagnostic preserves native zero-based `bl_id`, `Name`, all decoded source
  `attributes`, `point_start`, `point_count`, exclusive `point_end`, `part_start`,
  `part_count`, and `reason_code="BREAKLINE_TOO_FEW_POINTS"`. The list is empty for
  clean or absent layers and remains available when every record is degenerate.
  Persist diagnostics separately before GeoParquet/other tabular export because
  writers may discard attrs. Negative, truncated or out-of-range spans still
  raise; this read-only extraction does not change source geometry, units or CRS.

## Utilities

### HdfUtils

Utility class for HDF file operations.

**Data Conversion:**

- `convert_ras_string(value)` - Convert RAS HDF strings to Python objects
- `convert_ras_hdf_value(value)` - Convert general HDF values to Python objects
- `convert_df_datetimes_to_str(df)` - Convert DataFrame datetime columns to strings
- `convert_hdf5_attrs_to_dict(attrs)` - Convert HDF5 attributes to dictionary
- `convert_timesteps_to_datetimes(timesteps)` - Convert timesteps to datetime objects

**Spatial Operations:**

- `perform_kdtree_query(source, target)` - KDTree search between datasets
- `find_nearest_neighbors(data, k)` - Find nearest neighbors within dataset

**DateTime Parsing:**

- `parse_ras_datetime(datetime_str)` - Parse RAS datetime (ddMMMYYYY HH:MM:SS)
- `parse_ras_window_datetime(datetime_str)` - Parse simulation window datetime
- `parse_duration(duration_str)` - Parse duration strings (HH:MM:SS)
- `parse_ras_datetime_ms(datetime_bytes)` - Parse datetime with milliseconds
- `parse_run_time_window(window_str)` - Parse time window strings

## Visualization

### HdfPlot & HdfResultsPlot

Basic plotting utilities.

- `plot_results_max_wsel(gdf)` - Plot maximum WSE map

## Usage Example

```python
from ras_commander import HdfResultsMesh, HdfResultsPlan, init_ras_project, ras

init_ras_project("/path/to/project", "6.5")

# Get HDF path
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'].iloc[0]

# Extract max WSE
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)

# Get runtime stats
runtime = HdfResultsPlan.get_runtime_data(hdf_path)
```

## Complete source reference

The sections above explain common operations. The source-derived reference below
includes the remaining public methods and their full signatures. Method-specific
prerequisites and return contracts take precedence over abbreviated summaries.

### HdfBase source reference

::: ras_commander.hdf.HdfBase.HdfBase
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_2d_flow_area_names_and_counts
        - get_attrs
        - get_dataset_info
        - get_polylines_from_parts
        - get_projection
        - get_result_unit_metadata
        - get_simulation_start_time
        - get_unsteady_timestamps
        - plan_vertex_ordinates
        - print_attrs
        - strip_results

### HdfUtils source reference

::: ras_commander.hdf.HdfUtils.HdfUtils
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - convert_df_datetimes_to_str
        - convert_hdf5_attrs_to_dict
        - convert_ras_hdf_value
        - convert_ras_string
        - convert_timesteps_to_datetimes
        - find_nearest_neighbors
        - parse_duration
        - parse_ras_datetime
        - parse_ras_datetime_ms
        - parse_ras_window_datetime
        - parse_run_time_window
        - perform_kdtree_query
        - resolve_hdf_paths
        - scan_hdf_files

### HdfPlan source reference

::: ras_commander.hdf.HdfPlan.HdfPlan
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_2d_flow_options
        - get_geometry_information
        - get_plan_end_time
        - get_plan_information
        - get_plan_met_precip
        - get_plan_parameters
        - get_plan_start_time
        - get_plan_timestamps_list
        - get_starting_wse_method

### HdfMesh source reference

::: ras_commander.hdf.HdfMesh.HdfMesh
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - combine_faces_to_linestring
        - diagnose_mesh_cell_polygons
        - diagnose_mesh_layout
        - extend_face_property_tables
        - extend_linux_tmp_face_property_tables
        - find_nearest_cell
        - find_nearest_face
        - get_face_ids_in_calibration_region
        - get_face_ids_in_polygon
        - get_faces_along_profile_line
        - get_mannings_calibration_table
        - get_mesh_area_attributes
        - get_mesh_area_names
        - get_mesh_areas
        - get_mesh_cell_faces
        - get_mesh_cell_points
        - get_mesh_cell_polygons
        - get_mesh_cell_property_tables
        - get_mesh_face_hydraulic_properties_at_stage
        - get_mesh_face_property_tables
        - get_mesh_perimeter_faces
        - get_mesh_sloped_topology
        - get_reference_line_internal_faces
        - pin_property_tables
        - recompute_face_mannings_n_from_landcover_curves
        - sample_linux_tmp_face_mannings_n_from_landcover_curves
        - set_face_mannings_n_values
        - set_mesh_face_property_tables
        - set_mesh_pinned_attribute
        - transform_linux_tmp_face_mannings_n
        - write_linux_tmp_face_property_tables

### HdfXsec source reference

::: ras_commander.hdf.HdfXsec.HdfXsec
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - generate_river_edge_lines
        - get_1d_footprint
        - get_cross_sections
        - get_river_bank_lines
        - get_river_centerlines
        - get_river_edge_lines
        - get_river_flow_paths
        - get_river_reaches
        - get_river_stationing
        - get_xs_coords
        - get_xs_interpolation_surface

### HdfBndry source reference

::: ras_commander.hdf.HdfBndry.HdfBndry
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_bc_external_faces
        - get_bc_lines
        - get_breaklines
        - get_reference_lines
        - get_reference_points
        - get_refinement_regions

### HdfStruc source reference

::: ras_commander.hdf.HdfStruc.HdfStruc
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_connection_attachments
        - get_culvert_hydraulics
        - get_geom_structures_attrs
        - get_sa2d_breach_info
        - get_storage_area_polygons
        - get_structures
        - list_sa2d_connections

### HdfStorageArea source reference

::: ras_commander.hdf.HdfStorageArea.HdfStorageArea
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - compute_stage_storage_curve
        - compute_volume_below_elevation
        - get_storage_area_for_breach_structure
        - get_storage_area_names
        - get_storage_area_properties
        - get_terrain_path_from_geom_hdf
        - get_volume_elevation_curve

### HdfStruc1D source reference

::: ras_commander.hdf.HdfStruc1D.HdfStruc1D
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_structure_max_values
        - list_1d_structures

### HdfHydraulicTables source reference

::: ras_commander.hdf.HdfHydraulicTables.HdfHydraulicTables
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_all_xs_htabs
        - get_xs_htab

### HdfResultsPlan source reference

::: ras_commander.hdf.HdfResultsPlan.HdfResultsPlan
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_compute_messages
        - get_compute_messages_hdf_only
        - get_reference_summary
        - get_reference_timeseries
        - get_runtime_data
        - get_steady_info
        - get_steady_profile_names
        - get_steady_results
        - get_steady_wse
        - get_unsteady_info
        - get_unsteady_summary
        - get_volume_accounting
        - is_steady_plan
        - list_steady_variables

### HdfResultsMesh source reference

::: ras_commander.hdf.HdfResultsMesh.HdfResultsMesh
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - export_depth_rasters_at_times
        - export_max_depth_raster
        - get_boundary_conditions_timeseries
        - get_flood_extent_polygon
        - get_mesh_cells_timeseries
        - get_mesh_faces_timeseries
        - get_mesh_last_iter
        - get_mesh_max_depth
        - get_mesh_max_face_v
        - get_mesh_max_iter
        - get_mesh_max_ws
        - get_mesh_max_ws_err
        - get_mesh_min_face_v
        - get_mesh_min_ws
        - get_mesh_summary
        - get_mesh_summary_output
        - get_mesh_summary_output_group
        - get_mesh_summary_values
        - get_mesh_timeseries
        - get_profile_line_flow_timeseries
        - get_profile_line_flow_timeseries_legacy
        - get_profile_line_peak_flow
        - iter_mesh_timeseries

### HdfResultView source reference

::: ras_commander.hdf.HdfResultView.HdfResultView
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - iter_batches
        - reduce
        - select
        - to_arrow
        - to_numpy
        - to_pandas
        - to_xarray

### HdfResultsXsec source reference

::: ras_commander.hdf.HdfResultsXsec.HdfResultsXsec
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_ref_lines_timeseries
        - get_ref_points_timeseries
        - get_xsec_summary
        - get_xsec_timeseries

### HdfResultsBreach source reference

::: ras_commander.hdf.HdfResultsBreach.HdfResultsBreach
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_breach_summary
        - get_breach_timeseries
        - get_breaching_variables
        - get_structure_variables

### HdfResultsSediment source reference

::: ras_commander.hdf.HdfResultsSediment.HdfResultsSediment
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_active_layer_grain_class
        - get_bed_change_volumes
        - get_cell_bed_change
        - get_cell_bed_change_timeseries
        - get_cell_bed_elevation
        - get_sediment_mesh_areas
        - is_sediment_plan

### HdfResultsProducts source reference

::: ras_commander.hdf.HdfResultsProducts.HdfResultsProducts
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - export
        - inspect_result

### HdfPipe source reference

::: ras_commander.hdf.HdfPipe.HdfPipe
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - extract_timeseries_for_conduit
        - extract_timeseries_for_node
        - get_pipe_conduits
        - get_pipe_inlets
        - get_pipe_network
        - get_pipe_network_summary
        - get_pipe_network_timeseries
        - get_pipe_nodes
        - get_pipe_profile

### HdfPump source reference

::: ras_commander.hdf.HdfPump.HdfPump
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - get_pump_groups
        - get_pump_operation_timeseries
        - get_pump_station_summary
        - get_pump_station_timeseries
        - get_pump_stations

### HdfInfiltration source reference

::: ras_commander.hdf.HdfInfiltration.HdfInfiltration
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - calculate_soil_statistics
        - calculate_total_significant_percentage
        - calculate_weighted_parameters
        - create_infiltration_group
        - create_infiltration_override_regions
        - get_classification_polygons
        - get_infiltration_baseoverrides
        - get_infiltration_calibration_regions
        - get_infiltration_layer_data
        - get_infiltration_map
        - get_infiltration_parameters
        - get_infiltration_region_names
        - get_infiltration_region_overrides
        - get_infiltration_region_polygons
        - get_infiltration_stats
        - get_landcover_raster_stats
        - get_preprocessed_infiltration
        - get_preprocessed_infiltration_stats
        - get_significant_mukeys
        - get_soil_raster_stats
        - get_soils_raster_stats
        - save_statistics
        - scale_infiltration_base_overrides
        - scale_infiltration_baseoverrides
        - scale_infiltration_data
        - scale_infiltration_region_overrides
        - scale_infiltration_sidecar_parameters
        - set_infiltration_base_overrides
        - set_infiltration_baseoverrides
        - set_infiltration_layer_data
        - set_infiltration_region_overrides
        - set_infiltration_sidecar_parameters

### HdfLandCover source reference

::: ras_commander.hdf.HdfLandCover.HdfLandCover
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - audit_final_mannings_n
        - build_landcover_depth_roughness_curves
        - compare_base_vs_calibrated
        - compute_final_mannings_raster
        - estimate_final_mannings_raster
        - get_classification_polygons
        - get_landcover_association
        - get_landcover_raster_map
        - get_mannings_calibration_table
        - get_mannings_region_cell_mapping
        - get_mannings_region_polygons
        - get_preprocessed_mannings_n
        - get_preprocessed_mannings_stats
        - set_landcover_mannings_n
        - set_landcover_raster_map
        - sanitize_classification_names

### HdfPlot source reference

::: ras_commander.hdf.HdfPlot.HdfPlot
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - plot_mesh_cells
        - plot_time_series

### HdfResultsPlot source reference

::: ras_commander.hdf.HdfResultsPlot.HdfResultsPlot
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - plot_results_max_wsel
        - plot_results_max_wsel_time
        - plot_results_mesh_variable

### HdfFluvialPluvial source reference

::: ras_commander.hdf.HdfFluvialPluvial.HdfFluvialPluvial
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - calculate_fluvial_pluvial_boundary
        - generate_fluvial_pluvial_polygons

### HdfBenefitAreas source reference

::: ras_commander.hdf.HdfBenefitAreas.HdfBenefitAreas
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - identify_benefit_areas

### HdfChannelCapacity source reference

::: ras_commander.hdf.HdfChannelCapacity.HdfChannelCapacity
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - analyze_channel_capacity
        - compare_conditions
        - determine_capacity
        - extract_bank_elevations
        - extract_max_wse
        - extract_steady_profile_wse
        - segment_channel
        - system_capacity_summary

### HdfResultsAnalysis source reference

::: ras_commander.hdf.HdfResultsAnalysis.HdfResultsAnalysis
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - analyze_critical_duration

### HdfProject source reference

::: ras_commander.hdf.HdfProject.HdfProject
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - export_extent_geojson
        - get_project_bounds_latlon
        - get_project_crs
        - get_project_extent
