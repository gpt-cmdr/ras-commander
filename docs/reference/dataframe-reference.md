# DataFrame Reference

This page covers the **current project-level DataFrames** populated by
`init_ras_project()`. These tables are the stable entry point for most
automation, validation, and notebook workflows.

!!! tip
    Use the DataFrames first for project metadata and file-path discovery.
    Use dedicated HDF readers for heavy result extraction, and use xarray-based
    result APIs when the data is naturally time-series or grid-shaped.

## What Gets Created at Initialization

```python
from ras_commander import init_ras_project, ras

init_ras_project(r"C:\Projects\MyModel", "6.6")

print(ras.plan_df.columns.tolist())
print(ras.boundaries_df.columns.tolist())
print(ras.rasmap_df.columns.tolist())
```

| DataFrame | Primary source | Typical use |
|-----------|----------------|-------------|
| `ras.plan_df` | `.p##` plan files plus `.prj` references | execution targeting, geometry/flow linkage, HDF result discovery |
| `ras.geom_df` | `.g##` files and compiled `.g##.hdf` paths | geometry inventory, HDF presence, geometry titles/descriptions |
| `ras.flow_df` | `.f##` files | steady-flow inventory and descriptions |
| `ras.unsteady_df` | `.u##` files | unsteady-flow inventory and descriptions |
| `ras.boundaries_df` | parsed unsteady boundary blocks | DSS audits, hydrograph inspection, boundary summaries |
| `ras.rasmap_df` | `.rasmap` project summary | compact terrain / land-cover / projection path summary |
| `ras.results_df` | lightweight HDF summaries | completion, runtime, error/warning, and result-file status |

Related live notebooks:

- [101_project_initialization.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/101_project_initialization.ipynb)
- [104_plan_parameter_operations.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/104_plan_parameter_operations.ipynb)
- [111_executing_plan_sets.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/111_executing_plan_sets.ipynb)
- [122_rasmapper_spatial_review.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/122_rasmapper_spatial_review.ipynb)
- [150_results_dataframe.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/150_results_dataframe.ipynb)
- [212_landcover_mannings_n_write.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/212_landcover_mannings_n_write.ipynb)
- [611_validating_map_layers.ipynb](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/611_validating_map_layers.ipynb)

## Plan-Number Normalization

ras-commander normalizes RAS file numbers to a two-digit form before path
construction. All of these inputs resolve to the same plan number:

```python
from pathlib import Path
from ras_commander import RasUtils

RasUtils.normalize_ras_number(1)                  # "01"
RasUtils.normalize_ras_number("01")               # "01"
RasUtils.normalize_ras_number("p01")              # "01"
RasUtils.normalize_ras_number(Path("Model.p01"))  # "01"
```

This matters when you pass prefixed plan numbers into `RasCmdr`,
`RasProcess`, HDF readers, or any helper that resolves `.p##` / `.g##` files
from project metadata.

## `plan_df`

`plan_df` is the main execution and metadata table. It is assembled from the
`.prj` file, parsed `.p##` contents, and project-relative path resolution.

Key columns you can rely on:

| Column | Meaning |
|--------|---------|
| `plan_number` | normalized two-digit plan id such as `01` |
| `geometry_number` | normalized geometry id used by the plan |
| `unsteady_number` | normalized unsteady-flow id when the plan is unsteady |
| `Plan Title` | HEC-RAS plan title |
| `Short Identifier` | HEC-RAS short id used by stored-map/result folders |
| `Geom File` / `Geom Path` | geometry reference and resolved path |
| `Flow File` / `Flow Path` | steady or unsteady flow reference and resolved path |
| `Computation Interval` / `Output Interval` | time-step metadata |
| `Program Version` | HEC-RAS version recorded in the plan |
| `HDF_Results_Path` | resolved `.p##.hdf` path when present |
| `full_path` | resolved `.p##` path |
| `flow_type` | convenience flow-type classification |

Common patterns:

```python
# Plans that already have local HDF results
plans_with_results = ras.plan_df[ras.plan_df["HDF_Results_Path"].notna()]

# Plans using a specific geometry
g04_plans = ras.plan_df[ras.plan_df["geometry_number"] == "04"]

# Quick lookup through RasPrj helpers
info = ras.get_plan_info("01")
paths = ras.get_hdf_paths("01")
```

## `geom_df`

`geom_df` inventories geometry files and compiled HDF companions.

Useful columns:

| Column | Meaning |
|--------|---------|
| `geom_number` | normalized geometry id |
| `geom_file` | raw `.g##` reference from the project |
| `full_path` | resolved `.g##` path |
| `hdf_path` | expected compiled `.g##.hdf` path |
| `geom_title` | parsed geometry title when present |
| `description` | geometry description block when present |

The table may also include counts or metadata parsed from the geometry file.
Use it for geometry discovery first, then move to `RasGeometry`, `Geom*`, or
HDF readers for detailed geometry content.

## `flow_df` and `unsteady_df`

These inventory steady and unsteady flow files referenced by the project.

Typical columns:

| DataFrame | Common columns |
|-----------|----------------|
| `flow_df` | `flow_number`, `full_path`, `description` |
| `unsteady_df` | `unsteady_number`, `full_path`, `description`, plus parsed unsteady metadata |

Use these tables when you need to audit which `.f##` / `.u##` files exist
before editing them through `RasPlan` or `RasUnsteady`.

## `boundaries_df`

`boundaries_df` is built from the unsteady boundary blocks and is the main
table for DSS-path audits and boundary-condition summaries.

Common columns:

| Column | Meaning |
|--------|---------|
| `unsteady_number` | parent `.u##` file |
| `boundary_condition_number` | boundary sequence within the file |
| `bc_type` | high-level boundary type |
| `hydrograph_type` | parsed hydrograph subtype when present |
| `river_reach_name` / `river_station` | 1D location metadata |
| `storage_area_name` | 2D/storage-area location when present |
| `Interval` | time interval |
| `Use DSS` | whether the boundary uses DSS |
| `DSS File` / `DSS Path` | raw DSS references |
| `dss_part_a` ... `dss_part_f` | parsed DSS pathname components |
| `hydrograph_num_values` | number of inline hydrograph values |

Examples:

```python
# DSS-backed boundaries only
dss_boundaries = ras.boundaries_df[ras.boundaries_df["Use DSS"] == "True"]

# Flow hydrographs only
flow_bcs = ras.boundaries_df[ras.boundaries_df["bc_type"] == "Flow Hydrograph"]
```

## `rasmap_df`

`rasmap_df` is a **single-row compact summary** of the project `.rasmap`.
Several columns contain lists because the dataframe is optimized for project
overview, not one-row-per-layer discovery.

Current default columns:

| Column | Shape | Meaning |
|--------|-------|---------|
| `projection_path` | scalar | project projection reference |
| `profile_lines_path` | list | profile/reference line paths |
| `soil_layer_path` | list | soils sidecar paths |
| `infiltration_hdf_path` | list | infiltration sidecar HDFs |
| `landcover_hdf_path` | list | land-cover sidecar HDFs |
| `terrain_hdf_path` | list | terrain HDFs |
| `reference_map_layer_names` / `reference_map_layer_path` | list | reference map layers |
| `basemap_layer_names` / `basemap_layer_path` | list | basemap layers |
| `current_settings` | dict | compact `.rasmap` settings summary |

```python
summary = ras.rasmap_df.iloc[0]
print(summary["terrain_hdf_path"])
print(summary["landcover_hdf_path"])
```

Use `rasmap_df` for quick project-level path inspection. When you need
discoverable layer names and per-layer metadata, prefer:

- `RasMap.list_terrain_layers()`
- `RasMap.list_landcover_layers()`
- `RasMap.list_soils_layers()`
- `RasMap.list_infiltration_layers()`
- `RasMap.list_map_layers()`
- `RasMap.list_geometry_layers()`
- `RasMap.list_result_layers()`

For compiled HDF asset resolution, pair the `.rasmap` summary with
`RasMap.get_hdf_geometry_association()` on geometry or plan/result HDFs.

## `results_df`

`results_df` is a lightweight summary table generated from plan HDFs through
`ResultsSummary`. It is intended for fast execution-status and runtime queries,
not heavy spatial extraction.

Typical columns:

| Column | Meaning |
|--------|---------|
| `plan_number` / `plan_title` / `flow_type` | copied project metadata |
| `hdf_path` / `hdf_exists` / `hdf_file_modified` | result-file status |
| `completed` | completion flag parsed from compute metadata |
| `has_errors` / `has_warnings` | summary health flags |
| `error_count` / `warning_count` | parsed message counts |
| `first_error_line` | first blocking compute-message line when present |
| `runtime_simulation_hours` | simulation duration |
| `runtime_complete_process_hours` | end-to-end runtime |
| `runtime_unsteady_compute_hours` | unsteady compute runtime when present |
| `runtime_complete_process_speed` | normalized throughput metric |
| `runtime_source` | whether runtime came from HDF metadata or compute-message fallback |

```python
print(ras.results_df[[
    "plan_number",
    "completed",
    "has_errors",
    "runtime_complete_process_hours",
]])

# Refresh after new runs
ras.update_results_df(["01"])
```

## HDF and Time-Series Data Are Not Always DataFrames

Project metadata belongs in pandas DataFrames. Heavy simulation outputs often do
not. Prefer the dedicated HDF readers and xarray-backed APIs for:

- 1D cross-section time series
- 2D mesh cell or face time series
- reference lines and reference points
- profile-line flow and peak-Q extraction
- large raster or mesh-derived result families

### Profile-Line Flow Outputs

`HdfResultsMesh.get_profile_line_flow_timeseries()` returns a profile/reference
line flow time series. The API uses native HDF reference-line internal faces
when present, then falls back to RAS Mapper profile-line geometry.

| Column | Meaning |
|--------|---------|
| `time` | Output timestamp |
| `flow` | Sum of selected face flows |
| `line_name` | Requested profile/reference line |
| `mesh_name` | 2D flow area used for extraction |
| `direction` | `absolute` or `signed` aggregation mode |
| `face_count` | Count of selected mesh faces |
| `selection_source` | `reference_line_internal_faces` or `profile_lines_geometry` |

`HdfResultsMesh.get_profile_line_peak_flow()` returns one peak-Q row derived
from the time series.

| Column | Meaning |
|--------|---------|
| `line_name` | Requested profile/reference line |
| `mesh_name` | 2D flow area used for extraction |
| `peak_time` | Timestamp of peak flow magnitude |
| `peak_flow` | Peak flow value; signed mode preserves native sign |
| `direction` | `absolute` or `signed` aggregation mode |
| `face_count` | Count of selected mesh faces |
| `selection_source` | `reference_line_internal_faces` or `profile_lines_geometry` |

See:

- [HDF Data Extraction](../user-guide/hdf-data-extraction.md)
- [Spatial Data & RASMapper](../user-guide/spatial-data.md)
- [API Reference](../api/index.md)

## Practical Workflow

1. Initialize the project and inspect `plan_df`, `boundaries_df`, and `rasmap_df`.
2. Normalize any user-supplied plan or geometry numbers before constructing paths.
3. Use `results_df` for quick execution and health checks.
4. Use `RasMap.list_*_layers()` and `get_hdf_geometry_association()` for
   per-layer RASMapper and compiled-HDF QA.
5. Move to dedicated HDF or geometry APIs only after the project metadata tables
   tell you which files and plans matter.
