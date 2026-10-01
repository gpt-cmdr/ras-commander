# Profiles, hydrographs and reference locations

For repeatable batch plots, start with the
[2D profile and reference workflow guide](../../user-guide/2d-profile-and-reference-workflows.md).
The classes below separate cell sampling, native Mapper rendering, geometry
reference-feature authoring, and reading recorded solver output. These methods
do not themselves run a hydraulic simulation.

## Runtime and output contracts

| Surface | Input | Return | Requirements |
|---|---|---|---|
| Offline point/straight-profile sampling | Completed plan HDF, model-coordinate points/endpoints, variable and stored time selector | Dictionary or DataFrame of values and nearest-cell provenance | Python/HDF; reconstructed quantities are not a Mapper renderer |
| Native polyline profile | Plan HDF, LineString/coordinates, time index, spacing, optional terrain HDF | DataFrame: `station`, `x`, `y`, `mesh_name`, `face_id`, variable fields; WSE/velocity/flow profiles also include `depth`, `terrain_elev` | pythonnet and compatible installed HEC-RAS libraries |
| Native polyline time series | Same inputs, optional `time_range` | Long DataFrame, or `wide=True` station-by-`time_index` pivot of the selected variable | Same native runtime; saved result times only |
| Stored reference output | Completed plan HDF, optional variable names | xarray Dataset; lines use `time`, `refln_id` and coordinate `refln_name`; points use `refpt_id` and `refpt_name`; both include `mesh_name` | Reference locations present during computation; offline reader |
| Reference-feature generation/writing | Longitudinal coordinates, spacing/length, geometry file, target 2D area | Reviewable dictionaries or write count | Writes geometry, not computed results |

Native `terrain_raster` arguments currently resolve a **RAS terrain HDF**.
Coordinates must already match the model; the query does not reproject them.
`sample_spacing=None` requests 50 model coordinate units. Returned stations need
not be uniformly spaced at that request and may repeat. Native minimum-spacing
and sample-count limits also apply. `wide=True` uses a first-value aggregation
for repeated station/time-index pairs; keep long output to inspect all samples.
Native polyline
methods require a concrete output index and reject `"max"`; time-series ranges
are start-inclusive/stop-exclusive. The current shared input path rejects 2D
bridge groups. There is no public render-mode selector in these methods.

`face_id` in native sampled profiles is nearest-face metadata, not a guarantee
that a renderer used only that face. Preserve DataFrame `attrs` alongside CSV
exports for source/version/unit information. See the guide for terrain,
maximum-envelope and timestamp comparisons.

## Offline spatial sampling

::: ras_commander.hdf.HdfResultsQuery.HdfResultsQuery
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - query_point
        - query_points
        - query_profile
        - query_transverse_profile

## Native mapped profiles and time series

The `flow` sample column is not automatically whole-line Q. Use recorded
reference-line flow for that quantity when available; do not sum station samples.

::: ras_commander.hdf.HdfResultsQuery.HdfResultsQuery
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3
      members:
        - query_polyline_wse_profile
        - query_polyline_velocity_profile
        - query_polyline_flow_profile
        - query_polyline_wse_timeseries
        - query_polyline_velocity_timeseries
        - query_polyline_flow_timeseries
        - query_polyline_wse_difference
        - query_polyline_velocity_difference
        - query_polyline_pipe_velocity_profile
        - query_polyline_pipe_flow_profile
        - query_polyline_pipe_velocity_timeseries
        - query_polyline_pipe_flow_timeseries

## Recorded reference hydrographs

These methods read HDF datasets recorded during computation, including 2D
reference results despite the class name. An absent group or no matching numeric
variables produces an empty Dataset; a present group missing required `Name` or
timestamps raises `KeyError`. Missing or malformed output is not zero flow. Use `list(result.data_vars)` to discover
available variables and retain their unit/source attributes. Feature names are
coordinates, not necessarily xarray indexes; use `isel(refln_id=...)` or
explicit coordinate filtering instead of assuming `.sel(refln_name=...)` works.

::: ras_commander.hdf.HdfResultsXsec.HdfResultsXsec
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_ref_lines_timeseries
        - get_ref_points_timeseries

For a tidy DataFrame instead of xarray, use
`HdfResultsPlan.get_reference_timeseries(hdf_path, reftype="lines")` (or
`"points"`). It delegates to the reference readers and returns one row per
stored time/feature pair. An empty DataFrame can mean missing output **or a
caught read error**; inspect logged diagnostics rather than interpreting absence
as zero flow or stage.

::: ras_commander.hdf.HdfResultsPlan.HdfResultsPlan
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_reference_timeseries

## Named-line Q and extraction provenance

The canonical method needs RasMapperLib. It first attempts a native-associated
precomputed hydrograph via `ObservedDataLayer.TryReadRefLineFlow`, then falls
back to face aggregation. This native-associated hydrograph's provenance has
not been independently qualified as solver output and may be observed data.
Use `HdfResultsXsec.get_ref_lines_timeseries` for explicit solver-recorded HDF
Reference Lines datasets. Inspect `selection_source` in
the returned DataFrame: `try_read_ref_line_flow` is distinct from
`reference_line_internal_faces` and `rasmapper_perimeter_faces`.

For native-associated hydrographs, `direction="absolute"` takes `abs(Q)`; for aggregated
faces it sums `abs(Q_face)`. The latter is not a net flux. The signed face
fallback sums native face signs without a common line-normal correction or
solver projected-length weighting. `_legacy` is the explicit offline path,
not an automatic fallback when the native runtime is unavailable.
The [workflow guide](../../user-guide/2d-profile-and-reference-workflows.md#interpret-named-line-flow-provenance)
provides the interpretation table. The native-associated lookup is by name only,
so duplicate names across meshes are ambiguous. Its `face_count=0` and empty
`face_ids` identify the lookup path, not a physical face count; an omitted
`mesh_name` is reported as an empty string.

::: ras_commander.hdf.HdfResultsMesh.HdfResultsMesh
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_profile_line_flow_timeseries
        - get_profile_line_flow_timeseries_legacy
        - get_profile_line_peak_flow

## Reference-feature authoring

Generate proposed lines first, inspect them, then write to a working geometry.
Recompute and inspect the resulting reference output groups. In particular,
`add_reference_points` writes IC-point records; example 314's retained HEC-RAS
7.0 run did not produce a native Reference Points output group from these.
Authored point records plus a successful run do not guarantee recorded point
results. A profile line
used only for postprocessing does not retroactively become a recorded reference
location. Reference areas are not covered by these point/line writers.

::: ras_commander.geom.GeomReferenceFeatures.GeomReferenceFeatures
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - generate_reference_lines_from_longitudinal_line
        - add_reference_lines_from_longitudinal_line
        - add_reference_lines
        - replace_reference_lines
        - get_reference_lines
        - add_reference_points
        - get_reference_points

## Inspect geometry and output settings

::: ras_commander.hdf.HdfBndry.HdfBndry
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_reference_lines
        - get_reference_points

::: ras_commander.hdf.HdfMesh.HdfMesh
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_reference_line_internal_faces

Saved output intervals are distinct from the computation timestep. Updating a
plan's settings does not change an existing result HDF: recompute to produce the
new output, then inspect the timestamps actually written.

::: ras_commander.RasPlan
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - update_plan_intervals
        - get_hdf_output_options
        - set_hdf_output_options
        - apply_hdf_output_profile
