# Stored Maps

Stored maps turn **existing computed results** into raster or polygon products. They do not
run a hydraulic simulation. Supply a valid result HDF, the intended terrain
association, map types and a profile or output timestep supported by the method.

| Entry point | Use | Return |
|---|---|---|
| `RasMap.store_all_maps` | Canonical orchestration across its documented modes | Report dictionary |
| `RasProcess.store_maps` | Selected products for one plan/profile | Dictionary of map types to path lists |
| `RasProcess.store_maps_at_timesteps` | Selected output times | Nested dictionaries of product paths |
| `RasProcess.store_maps_at_steady_profiles` | Selected steady profiles in one helper launch | DataFrame |
| `estimate_store_map_resources`, `profile_store_maps` | Resource estimate or an actual profiled export | Typed estimate/profile result |
| Result registration and calculated layers | RASMapper result tree and expressions | XML / `.rasscript` edits; does not itself produce a stored raster |
| Raster batch/composite methods | Existing maps or selected plans | Export DataFrame or raster path |

The headless `RasProcess.store_maps()` implementation uses the native
`RasStoreMapHelper.exe`; the namespace also wraps other RasProcess operations.
Native export needs the matching installed HEC-RAS components, with Windows or
an explicitly configured supported Wine environment. `RasMap` also retains GUI
postprocessing: inspect the chosen mode's requirements before unattended use.
The compatibility `RasProcess.store_all_maps()` delegates to
`RasMap.store_all_maps(mode="all_plans")`.

Use returned product evidence and expected output files to check completion.
A layer visible in the RASMapper tree is not proof that its raster was generated.
For depth-comparison products see [Benefits analysis](benefits.md); for terrain
surface export see [Terrain](terrain.md), which is distinct from result mapping.

[601 — headless stored maps](../notebooks/601_headless_stored_map_generation_rasmapper.md)
contains retained execution outputs. [125 — arrival and duration maps](../notebooks/125_rasmapper_stored_maps_arrival_duration.md)
currently has no retained code-cell outputs; use it as a workflow example, not
execution evidence.

A separate retained Ether Hollow control qualifies native HEC-RAS 7.0.1
arrival, duration and percent rasters with horizontal rendering, one explicitly
selected terrain, a 0.5-foot wetness threshold and five regular output times.
Across 21,292 wet pixels, percent matches the fraction of wet stored samples;
arrival matches the first wet output time, and duration matches the observed
single-period time support. All product grids match the registered terrain.
The opt-in `tests/test_stored_maps_native_contract.py` checks these contracts
against hash-pinned external fixtures. This evidence does not execute notebook
125 or qualify sloping rendering, irregular intervals, initially wet conditions,
multiple wet periods, threshold equality or general recession semantics.

## Native inundation boundary

Pass `inundation_boundary=True` to request RAS Mapper's **Inundation Boundary**
stored layer. Disable the three default raster products for a boundary-only export:

```python
from ras_commander import RasProcess

products = RasProcess.store_maps(
    "02", profile="Max", render_mode="sloping",
    wse=False, depth=False, velocity=False,
    inundation_boundary=True,
    output_path="stored-boundary",
)
boundaries = products.get("inundation_boundary", [])  # list[Path] of .shp files
```

This uses native `RASResultsMap` storage through the packaged helper:
`MapType="depth"`, `OutputMode="Stored Polygon Specified Depth"`, and
`ContourPolygonValue="0"`. In HEC-RAS 7.0.1, this combination is recognized
by the native `IsIndundationBoundaryMap` property. There is no separate
`MapTypes.InundationBoundary` member in that runtime. It does not polygonize
an exported depth raster in Python.

HEC's [RAS Mapper User's Manual 6.6, Managing Results Maps — Inundation Boundary](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/mapping-results/managing-results-maps)
describes this as a stored polygon at the zero-depth contour for the selected
water-surface profile and associated terrain. Depth contours at other values
are a separate Depth map configuration; this flag selects the zero contour.

The result dictionary contains primary SHP paths. Native names can include
the contour value, for example `Inundation Boundary (Max Value_0).shp`.
`output_path` moves the freshly generated companion files, including SHX, DBF,
and PRJ when present. The call restores the original `.rasmap` on success or
failure. Existing raster defaults and return types are unchanged.

The collector requires a fresh SHP/SHX/DBF bundle with nonempty polygon records.
Missing, empty, truncated, incomplete, or unchanged products are omitted with
a warning; any files written remain available for inspection. A helper failure
raises `RuntimeError`. These structure checks do not assess polygon topology
or hydraulic accuracy. Inspect the returned paths before using the product.

Use `profile="Max"`, `"Min"`, or an available output timestamp. Boundary
generation uses the ordered serial helper path; explicit parallel workers
are unsupported. `RasMap.store_all_maps(mode="selected",
map_types=["inundation_boundary"])` routes to the same implementation.
The steady-profile entry point retains its existing final-selected-profile
boundary behavior and DataFrame return. Other depth contours, contour bands,
and the Mapper wet/dry editing layers are outside this flag's scope.

The opt-in `tests/test_native_inundation_boundary.py` copies a computed public
project, exports maximum and middle-timestep boundaries, checks readable,
valid, nonempty polygons and CRS, and verifies source-file hashes and `.rasmap`
restoration. Set `RAS_NATIVE_BOUNDARY_PROJECT` to the source `.prj`,
`RAS_NATIVE_BOUNDARY_PLAN` to its plan number (default `02`), and
`RAS_NATIVE_BOUNDARY_VERSION` to an installed runtime (default `7.0.1`).
Use a short scratch directory with pytest's `--basetemp` option. Runtime
qualification for this change covers sloping rendering with Windows HEC-RAS
7.0.1 on the public Davis Storm System. Both profiles produced valid,
nonempty multipart polygon features in EPSG:2871. A horizontal-rendering
attempt on that copy reported a native `Store-Map` fatal error; its cause is
unresolved. This evidence does not qualify horizontal boundary exports,
other runtime versions, or Linux/Wine boundary exports.

## Orchestration, result registration and calculated layers

::: ras_commander.RasMap.RasMap
    options:
      show_root_heading: false
      show_root_toc_entry: false
      heading_level: 3
      members:
        - postprocess_stored_maps
        - store_all_maps
        - get_results_folder
        - get_results_raster
        - scan_results_folders
        - find_results_folder
        - resolve_raster_paths
        - find_steady_raster
        - list_results_plans
        - ensure_results_plan_layer
        - list_results_map_layers
        - add_results_map_layer
        - list_calculated_layers
        - add_calculated_layer
        - remove_calculated_layer
        - add_wse_comparison_layers

## Headless mapping, resources and raster products

### Native command failures

The packaged `RasStoreMapHelper.exe` runs installed RAS Mapper library commands.
Aggregate exports use `StoreAllMapsCommand`; independent map exports use the
`StoreMapCommand` factories followed by headless native map storage. Both routes
use the same Commander helper executable, not different mapping engines.

Native aggregate commands can report a fatal error through their progress
reporter and return without throwing. Commander captures these messages, returns
a nonzero helper exit code, and raises an error from `RasProcess.store_maps()`.
Files left by a failed command are not evidence of a completed export. The helper
does not retry automatically or repair missing pixel values.

In Windows HEC-RAS 7.0.1 tests of the public Davis pipe-network example, aggregate
horizontal Max exports intermittently failed during pipe-rendering cache updates
inside `RASPipeNetworks.RenderMeshPipeRenderOptions.SetLastMesh`. The captured
exception reached `DataRow` mutation from parallel pipe rasterization. Failed
exports could leave all-nodata TIFFs without georeferencing. The project PRJ,
result HDF and terrain agreed on EPSG:2871; explicit projection initialization
still reproduced the failure, as did exports with Python georeferencing repair
disabled.

A diagnostic control restricted inherited process affinity to one logical CPU:
all 20 aggregate calls completed, and all 10 calls with georeferencing repair
enabled exactly matched the Rust comparison on 4,883 wet pixels after a strict
depth greater than 0.5 ft filter. Four-CPU diagnostic controls failed in 5 of
8 calls, including a separate control with explicit projection initialization.
These observations support a native concurrency defect; they do not establish
a general repair. `max_workers=1` limits helper processes, not native internal
threads. Commander does not automatically apply this Windows affinity control,
and independent exports are not a guaranteed workaround.

### Sloping render options

`RasProcess.store_maps(render_mode=None)` reads the project's current render
configuration through `RasMap.get_water_surface_render_mode()`. For
`slopingPretty`, the helper receives both `reduce_shallow_to_horizontal` and
`use_depth_weighted_faces`; it does not replace explicit settings with helper
defaults. Bare mode names retain their existing default behavior.

Configure these flags with `RasMap.set_water_surface_render_mode()` before
calling `store_maps(render_mode=None)`. Setting the configuration is a persistent
project edit. The stored-map call restores the configuration present at its own
entry, including the selected flags; it does not undo a preceding setter call.
These options affect native sloping interpolation and are distinct from the
optional pixel depth cutoff applied after mapping. See HEC's
[Mapping Options](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/7.0/mapping-results/mapping-options)
for the two sloping modes and their display controls.

::: ras_commander.RasProcess.RasProcess
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - get_store_maps_runtime_provenance
        - configure_wine
        - check_wine_environment
        - setup_wine_environment
        - find_rasprocess
        - get_plan_timestamps
        - estimate_store_map_resources
        - profile_store_maps
        - store_benefit_area
        - store_maps
        - store_maps_at_steady_profiles
        - store_maps_at_timesteps
        - store_all_maps
        - run_command
        - apply_depth_threshold
        - batch_export_rasters
        - composite_rasters
        - composite_rasters_from_plans
