<a id="rasmapper-api"></a>

# RASMapper

Use these dedicated references for related tasks:

| Task | Reference |
|---|---|
| Generate, diagnose, or repair a 2D mesh | [Meshing](../meshing.md) |
| Sample results, profiles, or reference hydrographs | [Results Queries](../results-queries.md) |
| Export computed results to raster maps | [Stored Maps](../stored-maps.md) |
| Create, modify, or export terrain | [Terrain](../terrain.md) |

This page covers the remaining RASMapper operations: screenshots and spatial
review, map and geometry layers, display controls, geometry associations, and
native geometry completion. Use the static namespaces directly; there is no
single RASMapper object to instantiate. File readers and XML editors can run
without a visible desktop. Native methods need their documented HEC-RAS runtime;
GUI capture additionally needs an interactive Windows desktop. A headless Wine
qualification does not establish GUI screenshot support.

Registration in `.rasmap` and associations in compiled geometry HDF are distinct.
Changing visibility does not alter hydraulic results, and geometry completion
does not execute a hydraulic plan. Use [RasCmdr](../core.md#rascmdr) for execution
and review the resulting evidence before exporting maps.

<a id="configuration-native-processing-and-computation"></a>

## Inspect, configure, and capture

```python
from pathlib import Path
from ras_commander import RasMap

project_path = Path("review-copy/Model.prj")
print(RasMap.list_map_layers(project_path))
print(RasMap.get_current_view(project_path))

# Register an existing vector layer on the copied project.
RasMap.add_reference_map_layer(
    project_path,
    source_path=Path("review-inputs/review-area.geojson"),
    layer_name="Review area",
)
```

GeoJSON registration validates WGS84 compatibility. Use method-specific CRS
rules instead of assuming all layer inputs are in the model CRS.
`clone_geometry_layer()` registers an existing geometry clone; it does not copy
the geometry files. Use geometry cloning first, then register the new HDF and
verify its compiled associations.

On an interactive Windows review desktop:

```python
from ras_commander import RasMap

snapshot = RasMap.screenshot_model(
    "review-copy/Model.prj",
    output_path="review-output/model.png",
    ras_version="6.6",
)
if snapshot is None:
    raise RuntimeError("No screenshot was captured; inspect the logged diagnostics")
print(snapshot)
```

`create_spatial_review_package()` can produce an evidence bundle without a
screenshot (`capture_snapshot=False`, the default). That path can still persist
display settings in `.rasmap`; it is not a read-only inventory. To require a
screenshot, select a GUI-capable runtime and use `capture_snapshot=True` with
`require_snapshot=True`. See the method for preflight and restoration behavior.

## RASMapper display and spatial review

Use `RasMap` to select geometry and result layers, set visibility and view bounds,
and capture review evidence. Visibility and rendering changes are persisted in
`.rasmap`; HDF feature readers supply model bounds and feature inventories.

| Task | Input | Output |
|---|---|---|
| Layer and feature discovery | Project and exact geometry/layer selector | Lists or DataFrames |
| Visibility and terrain display | Layer selector and display options | Updated XML; Boolean or changed-entry count |
| View and zoom | Explicit bounds or HDF feature selector | View/bounds dictionary |
| Open/capture/close | Project and optionally an owned process ID | Process handle, optional PNG path, closed-window count |
| Screenshot gallery / review package | Projects and output directory | Gallery records or review-bundle dictionary |

Screenshots require Windows GUI facilities and a visible RASMapper window.
Prefer the process ID returned by `open_rasmapper()` when capturing or closing
that window. `screenshot_model()` temporarily configures display layers and
restores its `.rasmap` backup after capture. Read each method's return value;
an absent screenshot is not successful visual evidence.

Examples with retained outputs: [122 — spatial review](../../notebooks/122_rasmapper_spatial_review.md),
[123 — geometry layer updates](../../notebooks/123_rasmapper_geometry_layer_updates.md),
and [124 — bank lines](../../notebooks/124_rasmapper_bank_lines.md).

## Display, features and review methods

::: ras_commander.RasMap.RasMap
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3
      members:
        - list_geometries
        - clone_geometry_layer
        - set_geometry_visibility
        - set_all_geometries_visibility
        - list_geometry_layers
        - set_geometry_layer_visibility
        - list_result_layers
        - set_result_layer_visibility
        - list_geometry_features
        - get_current_view
        - set_current_view
        - set_terrain_layer_visibility
        - list_terrain_display_settings
        - get_terrain_display_settings
        - set_terrain_display_settings
        - set_update_legend_with_view
        - get_geometry_layer_bounds
        - get_geometry_feature_bounds
        - zoom_to_geometry_layer
        - open_rasmapper
        - capture_rasmapper_snapshot
        - close_rasmapper
        - screenshot_model
        - screenshot_model_gallery
        - create_spatial_review_package
        - set_water_surface_render_mode
        - get_water_surface_render_mode


## RASMapper layers and associations

Import `RasMap` from `ras_commander` and call its static methods. Project-path
readers and initialized-project methods have different signatures: pass the
project path or `ras_object` accepted by the selected method rather than assuming
every method uses the global project.

| Operation | Input | Return / persisted effect |
|---|---|---|
| `parse_rasmap`, layer-list methods | `.rasmap` or project path, as documented below | DataFrames or lists describing configured layers |
| `add_terrain_layer` | Existing terrain HDF | Registers terrain in `.rasmap`; does not create elevation data |
| `add_landcover_layer`, `add_soils_layer`, `add_infiltration_layer` | Classification sources and project | Created layer HDF path and registration |
| Classification polygon CRUD | Layer HDF, feature selectors and polygon/class data | GeoDataFrame; native polygon edits for authoring calls |
| Reference maps and basemaps | Existing vector file or supported basemap name | `.rasmap` registration, with method-specific path or Boolean return |
| Geometry association inspection/validation | Compiled geometry HDF or project | Association dictionaries or diagnostic DataFrames |
| `associate_geometry_layers` | Compiled geometry and terrain/classification paths | Updated geometry HDF path |
| `recompute_property_tables` | Geometry and selected native version | Updated HDF path after native property-table processing |

Native classification creation and polygon authoring require the HEC-RAS
runtime supported by that method; reading a layer inventory is a separate
operation. Check source CRS, project units and extent explicitly; see the
[spatial extent contract](../../user-guide/spatial-data.md#authoritative-extents-for-raster-inputs).

Before computing property tables, inspect and validate the compiled-HDF
associations. Afterwards inspect final cell properties, including Manning's n,
using the [HDF API](../hdf.md). An XML registration alone is insufficient.
`RasProcess.validate_geometry_association_cli()` on the
[geometry completion page](#rasmapper-geometry-completion) is a **mutating native reference
validator**, intended for disposable copies, not a read-only association check.

Examples with retained outputs: [233 — classification polygons](../../notebooks/233_mannings_region_polygon_authoring.md)
and [931 — native terrain export](../../notebooks/931_native_rasmapper_terrain_export.md).

## Layer discovery and authoring

::: ras_commander.RasMap.RasMap
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - parse_rasmap
        - list_land_classification_layers
        - list_terrain_layers
        - list_landcover_layers
        - list_soils_layers
        - list_infiltration_layers
        - list_land_classification_polygons
        - add_land_classification_polygon
        - update_land_classification_polygon
        - delete_land_classification_polygon
        - add_landcover_layer
        - add_soils_layer
        - add_infiltration_layer
        - get_rasmap_path
        - initialize_rasmap_df
        - get_terrain_names
        - list_map_layers
        - list_reference_map_layers
        - list_basemap_layers
        - set_map_layer_visibility
        - list_standard_basemap_layers
        - add_reference_map_layer
        - add_basemap_layer
        - add_map_layer
        - remove_map_layer
        - ensure_rasmap_compatible
        - add_terrain_layer
        - prune_event_condition_layers
        - ensure_2d_encroachment_plan_layers

## Compiled geometry associations

::: ras_commander.RasMap.RasMap
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3
      members:
        - associate_geometry_layers
        - set_geometry_association
        - get_geometry_association
        - list_geometry_associations
        - validate_geometry_associations
        - get_hdf_geometry_association
        - recompute_property_tables

## Layer validation

`RasMapValidation` performs format, CRS, raster and spatial checks and returns
validation results (or the Boolean convenience result from `is_valid_layer`).
These checks do not run the hydraulic solver.

::: ras_commander.RasMapValidation.RasMapValidation
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - check_layer_format
        - check_layer_crs
        - check_raster_metadata
        - check_spatial_extent
        - check_terrain_layer
        - check_land_cover_layer
        - check_layer
        - is_valid_layer


## RASMapper geometry completion

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

## Lower-level screenshot utilities

`RasMap` is the project-aware entry point above. For an already identified window
or dialog, `RasScreenshot` exposes capture and evidence-folder utilities. These
GUI calls require the documented Windows dependencies and desktop; listing saved
screenshots does not establish that a fresh capture succeeded.

::: ras_commander.gui.screenshots.RasScreenshot
    options:
      show_root_heading: false
      heading_level: 3
      show_source: false
      members:
        - capture_all_ras_windows
        - capture_dialog
        - capture_foreground
        - capture_hecras_main
        - capture_menu_exploration
        - capture_window
        - capture_with_delay
        - document_dialog
        - get_screenshot_folder
        - list_screenshots
