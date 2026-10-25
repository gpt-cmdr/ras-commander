# Stored Maps

Stored maps turn **existing computed results** into raster products. They do not
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
