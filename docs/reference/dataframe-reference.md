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

Key columns you can rely on (column names preserve the HEC-RAS plan-file keys
verbatim, including spaces and the HEC-RAS spelling of `Reoccurance`). Values
parsed from the plan text are strings unless noted:

| Column | Dtype | Meaning |
|--------|-------|---------|
| `plan_number` | str | normalized two-digit plan id such as `01` |
| `geometry_number` | str | normalized geometry id used by the plan |
| `unsteady_number` | str / None | normalized unsteady-flow id when the plan is unsteady; `None` for steady plans |
| `Plan Title` | str | HEC-RAS plan title (`Plan Title=`) |
| `Short Identifier` | str | HEC-RAS short id used by stored-map/result folders |
| `Geom File` | str | geometry reference number from the plan (`Geom File=`) |
| `Geom Path` | str | resolved absolute `.g##` path |
| `Flow File` | str | steady/unsteady flow reference number (`Flow File=`) |
| `Flow Path` | str | resolved absolute `.f##` / `.u##` path |
| `Computation Interval` | str | computation time step (`Computation Interval=`) |
| `Mapping Interval` | str | RAS Mapper output interval (`Mapping Interval=`) |
| `Simulation Date` | str | simulation date/time window (`Simulation Date=`) |
| `Run HTab` / `Run UNet` / `Run PostProcess` / `Run Sediment` / `Run WQNet` | str | run-flag toggles parsed from the plan |
| `UNET D1 Cores` / `UNET D2 Cores` / `PS Cores` | int / None | core counts; cast to `int` when present, else `None` |
| `Write IC File` / `IC Time` | str | restart / hot-start output-save settings when present |
| `Write IC File at Fixed DateTime` | str | restart-at-fixed-datetime flag when present |
| `Write IC File Reoccurance` | str | restart output recurrence interval (HEC-RAS spelling preserved) |
| `Write IC File at Sim End` | str | final-step restart output flag |
| `Program Version` | str | HEC-RAS version recorded in the plan |
| `description` | str / None | plan `BEGIN DESCRIPTION` block when present |
| `HDF_Results_Path` | str / None | resolved `.p##.hdf` path; `None` when results do not exist yet |
| `full_path` | str | resolved absolute `.p##` path |
| `flow_type` | str | `"Unsteady"`, `"Steady"`, or `"Unknown"` (derived from `unsteady_number`) |

!!! note
    Columns derive directly from `_parse_plan_file()` in `ras_commander/RasPrj.py`,
    so any plan key present in the file appears as a same-named column. Not every plan
    contains every key; missing keys are simply absent or `None`.

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

Columns (the metadata columns come from `GeomMetadata`, which prefers fast
HDF-based extraction when `.g##.hdf` exists and falls back to plain-text parsing):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `geom_file` | str | raw `.g##` reference token from the project (e.g. `g01`) |
| `geom_number` | str | normalized geometry id (e.g. `01`) |
| `full_path` | str | resolved absolute `.g##` path |
| `hdf_path` | str | expected compiled `.g##.hdf` path |
| `geom_title` | str / None | parsed `Geom Title=` value when present |
| `description` | str / None | geometry `BEGIN DESCRIPTION` block when present |
| `has_1d_xs` | bool | `True` if the geometry has 1D cross sections |
| `has_2d_mesh` | bool | `True` if the geometry has 2D mesh / flow areas |
| `num_cross_sections` | int | count of 1D cross sections |
| `num_inline_structures` | int | total inline structures (bridges + culverts + weirs) |
| `num_bridges` | int | count of bridge structures |
| `num_culverts` | int | count of culvert structures |
| `num_weirs` | int | count of inline weir structures |
| `num_gates` | int | count of gate structures |
| `num_lateral_structures` | int | count of lateral structures |
| `num_sa_2d_connections` | int | count of SA/2D connections |
| `mesh_cell_count` | int | total 2D mesh cells across all areas |
| `mesh_area_names` | list[str] | names of 2D flow areas |

When metadata extraction fails for a geometry, counts default to `0`, booleans to
`False`, and `mesh_area_names` to an empty list. Use this table for geometry
discovery first, then move to `RasGeometry`, `Geom*`, or HDF readers for detail.

## `flow_df` and `unsteady_df`

These inventory steady and unsteady flow files referenced by the project.
Both come from `_parse_flow_file()` / `_parse_unsteady_file()` in `RasPrj.py`.

`flow_df` (steady `.f##`):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `flow_number` | str | normalized steady-flow id |
| `unsteady_number` | None | always `None` for steady-flow rows |
| `full_path` | str | resolved absolute `.f##` path |
| `Flow Title` | str / None | parsed `Flow Title=` value |
| `Program Version` | str / None | HEC-RAS version recorded in the flow file |
| `description` | str | flow `BEGIN DESCRIPTION` block (empty string when absent) |

`unsteady_df` (unsteady `.u##`):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `unsteady_number` | str | normalized unsteady-flow id |
| `full_path` | str | resolved absolute `.u##` path |
| `Flow Title` | str / None | parsed `Flow Title=` value |
| `Program Version` | str / None | HEC-RAS version recorded in the file |
| `Use Restart` | str / None | restart/hot-start flag (`Use Restart=`) |
| `Restart Filename` | str / None | restart source file when restart is enabled |
| `Precipitation Mode` / `Wind Mode` | str / None | meteorology mode toggles when present |
| `Met BC=Precipitation\|...` | str / None | parsed gridded-precip / met-BC settings when present |
| `description` | str | unsteady `BEGIN DESCRIPTION` block (empty string when absent) |

Use these tables when you need to audit which `.f##` / `.u##` files exist
before editing them through `RasPlan` or `RasUnsteady`.

## `boundaries_df`

`boundaries_df` is built from the unsteady boundary blocks and is the main
table for DSS-path audits and boundary-condition summaries.

Common columns (from `_parse_boundary_condition()` in `RasPrj.py`; DSS/typed
columns appear only when the source line is present):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `unsteady_number` | str | parent `.u##` file |
| `boundary_condition_number` | int | boundary sequence within the file (1-based) |
| `bc_type` | str | high-level boundary type (e.g. `Flow Hydrograph`, `Normal Depth`, `Unknown`) |
| `hydrograph_type` | str / None | hydrograph subtype when the BC is a hydrograph, else `None` |
| `river_reach_name` | str | 1D river/reach location field (may be empty string) |
| `river_station` | str | 1D river-station field (may be empty string) |
| `storage_area_name` | str | storage-area location field when present |
| `pump_station_name` | str | pump-station field when present |
| `area_2d` | str | 2D flow-area name field when present |
| `bc_line_name` | str | boundary-condition line name when present |
| `Interval` | str | time interval (`Interval=`) |
| `Use DSS` | str | `"True"` / `"False"` string (note: string, not bool) |
| `DSS File` | str | raw DSS file reference |
| `DSS Path` | str | raw DSS pathname |
| `dss_part_a` … `dss_part_f` | str | parsed DSS pathname components A–F |
| `Friction Slope` | str | raw friction-slope field for `Normal Depth` BCs |
| `friction_slope_value` | float / None | parsed friction-slope value |
| `critical_fallback_flag` | int / None | parsed critical-boundary fallback flag |
| `hydrograph_num_values` | int | number of inline hydrograph values (0 if none) |
| `hydrograph_values` | list[str] | inline hydrograph values when present |

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

Current default columns (each cell is one element because the DataFrame is a
single row; "Dtype" describes the value inside that cell):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `projection_path` | str / None | project projection (`.prj`) reference |
| `profile_lines_path` | list[str] | profile/reference line paths |
| `soil_layer_path` | list[str] | soils sidecar paths |
| `infiltration_hdf_path` | list[str] | infiltration sidecar HDFs |
| `landcover_hdf_path` | list[str] | land-cover sidecar HDFs |
| `terrain_hdf_path` | list[str] | terrain HDFs |
| `reference_map_layer_names` | list[str] | reference map layer names |
| `reference_map_layer_path` | list[str] | reference map layer paths |
| `basemap_layer_names` | list[str] | basemap layer names |
| `basemap_layer_path` | list[str] | basemap layer paths |
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

Columns (from `ResultsSummary.summarize_plan()` /
`get_summary_columns()` in `ras_commander/results/ResultsSummary.py`; identity,
health, and runtime columns are always present, `None`/`0` when unavailable):

| Column | Dtype | Meaning |
|--------|-------|---------|
| `plan_number` | str | copied plan id |
| `plan_title` | str / None | copied plan title |
| `flow_type` | str / None | `Steady` / `Unsteady` classification |
| `hdf_path` | str | path to the `.p##.hdf` result file |
| `hdf_exists` | bool | whether the HDF result file exists |
| `hdf_file_modified` | datetime / None | HDF modification timestamp |
| `ras_version` | str / None | HEC-RAS version (`Program Version`) |
| `completed` | bool | completion flag parsed from compute metadata |
| `has_errors` | bool | summary error flag |
| `has_warnings` | bool | summary warning flag |
| `error_count` | int | parsed error-message count |
| `warning_count` | int | parsed warning-message count |
| `first_error_line` | str / None | first blocking compute-message line when present |
| `runtime_simulation_start` | datetime / None | simulation start time |
| `runtime_simulation_end` | datetime / None | simulation end time |
| `runtime_simulation_hours` | float / None | simulated duration (hours) |
| `runtime_complete_process_hours` | float / None | end-to-end wall-clock runtime (hours) |
| `runtime_unsteady_compute_hours` | float / None | unsteady compute runtime (hours) |
| `runtime_complete_process_speed` | float / None | normalized throughput (sim hr / wall hr) |
| `runtime_source` | str / None | `'hdf'` or `'compute_messages'` provenance |
| `vol_error` | float / None | volume-accounting error (unsteady only) |
| `vol_accounting_units` | str / None | volume units |
| `vol_error_percent` | float / None | volume error as percent |
| `vol_flux_in` / `vol_flux_out` | float / None | total inflow / outflow volume |
| `vol_starting` / `vol_ending` | float / None | starting / ending storage volume |

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
