# RASMapper geometry completion

Geometry completion creates native geometry-derived layers in an **existing
compiled geometry HDF**. It is distinct from compiling geometry text, generating
2D computation points, and executing a hydraulic plan.

| API | Runtime | Inputs and outputs |
|---|---|---|
| `RasGeometryCompute.compute_geometry` | Windows, pythonnet, HEC-RAS 6.6+ | Geometry HDF and optional `.rasmap`; mutates HDF and returns `GeometryCompleteResult` |
| Individual `generate_*` methods | Same in-process native bridge | Selected edge lines, interpolation surface or flow paths; `GeometryLayerResult` |
| `validate_geometry`, `is_valid_geometry` | Native geometry validation | Diagnostics or Boolean convenience result |
| Reach-length and flow-path audits | See method-specific requirements below | Audit tables or `FlowPathPolicyResult` |
| `RasProcess.compute_geometry` | Windows or supported Linux/Wine subprocess path | Full native completion; dictionary with semantic validation and process evidence |

The full completion pipeline includes edge lines, the cross-section
interpolation surface and other geometry/property-table work. **Flow paths are
separate:** use `generate_flow_paths()` when needed. Completion may rebuild 2D
property tables and mutate more than one layer. Work on a project copy and
review diagnostics and resulting geometry before accepting it.

With the default `overwrite=False`, `RasGeometryCompute.compute_geometry()`
skips the pipeline if both edge lines and the interpolation surface already
exist. That path returns `success=True` without a separate `skipped` flag;
success alone does not prove the current call recomputed property tables.

Use `RasGeometryCompute` for the Windows in-process path; use the documented
`RasProcess` path for Linux/Wine completion. Do not infer that every in-process
method has a Wine equivalent. `RasProcess.complete_geometry()` is a deprecated
alias for `compute_geometry()`.

Read native output layers through `HdfXsec.get_river_edge_lines()`,
`get_xs_interpolation_surface()` and `get_river_flow_paths()` in the
[HDF API](../hdf.md). [234 — geometry completion](../../notebooks/234_rasmapper_geometry_completion.md)
contains retained execution outputs.

## In-process completion and diagnostics

::: ras_commander.RasGeometryCompute.RasGeometryCompute
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - generate_edge_lines
        - generate_interpolation_surface
        - generate_flow_paths
        - compute_geometry
        - validate_geometry
        - is_valid_geometry
        - audit_reach_lengths
        - assess_flow_path_policy
        - audit_main_channel_lengths

## Subprocess completion and native association validation

`validate_geometry_association_cli()` mutates its target HDF; use an intentional
validation copy. It is not a read-only check.

::: ras_commander.RasProcess.RasProcess
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3
      members:
        - compute_geometry
        - complete_geometry
        - validate_geometry_association_cli


## Completion result records

::: ras_commander.ComputeResults.GeometryLayerResult
    options:
      heading_level: 3

::: ras_commander.ComputeResults.GeometryCompleteResult
    options:
      heading_level: 3

::: ras_commander.ComputeResults.FlowPathPolicyResult
    options:
      heading_level: 3
