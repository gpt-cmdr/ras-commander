# Core Classes

Core classes for HEC-RAS project management and execution.

## Important Notes

!!! warning "Static Class Pattern"
    All primary classes use static methods - do NOT instantiate:
    ```python
    # Correct
    RasCmdr.compute_plan("01")

    # Wrong - will fail
    cmd = RasCmdr()
    cmd.compute_plan("01")
    ```

!!! warning "RASMapper Flag Inversion"
    When using `RasPlan.update_run_flags()`, note that RASMapper flags have **inverted logic**:

    - Standard flags: `True = -1`, `False = 0`
    - RASMapper flag: `True = 0`, `False = -1`

    This is a HEC-RAS quirk, not a library bug.

!!! tip "Input Flexibility"
    Most methods accept multiple input types via `@standardize_input`:
    ```python
    # All valid for HDF methods:
    HdfResultsMesh.get_mesh_max_ws("01")           # Plan number
    HdfResultsMesh.get_mesh_max_ws(1)              # Integer
    HdfResultsMesh.get_mesh_max_ws(Path("x.hdf")) # Path object
    ```

## Project Management

### init_ras_project

::: ras_commander.init_ras_project
    options:
      show_root_heading: true
      heading_level: 3

### RasPrj

::: ras_commander.RasPrj
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - project_folder
        - project_name
        - prj_file
        - ras_exe_path
        - plan_df
        - geom_df
        - flow_df
        - unsteady_df
        - boundaries_df
        - rasmap_df
        - get_hdf_entries
        - get_boundary_conditions

## Plan Execution

### RasCmdr

::: ras_commander.RasCmdr
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - compute_plan
        - compute_parallel
        - compute_test_mode

### RasControl

::: ras_commander.RasControl
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - run_plan
        - get_steady_results
        - get_unsteady_results
        - get_output_times
        - set_current_plan

#### RasControl Details

!!! info "Open-Operate-Close Pattern"
    Unlike other ras-commander classes, RasControl opens HEC-RAS, performs one operation, then closes it. This prevents conflicts with modern workflows and ensures clean resource management.

##### Supported Versions

| Version | Registry Key | HEC-RAS Years |
|---------|-------------|---------------|
| `"31"` | 3.1 | Legacy |
| `"41"` | 4.1 | ~2008-2014 |
| `"501"`, `"503"`, `"505"`, `"506"` | 5.0.x | 2015-2019 |
| `"60"` | 6.0 | 2020 |
| `"63"` | 6.3 | 2021-2022 |
| `"66"` | 6.6 | 2023+ |

##### RasControl vs RasCmdr

| Aspect | RasControl | RasCmdr |
|--------|------------|---------|
| **HEC-RAS Versions** | 3.x - 6.x (COM) | 5.x+ (command line) |
| **Data Source** | Live COM extraction | HDF file results |
| **Requires GUI** | Yes (HEC-RAS installed) | Yes (HEC-RAS installed) |
| **Use Case** | Legacy models, validation | Modern automation |
| **Returns** | pandas DataFrame | bool / dict |

##### Understanding "Max WS" in Unsteady Results

When extracting unsteady results, the **first row per cross section** (time_index=1) contains "Max WS" - the maximum at ANY computational timestep:

```python
# Unsteady results include special "Max WS" row
df = RasControl.get_unsteady_results("01")

# time_index=1 is "Max WS" (maximum at any timestep)
df_max = df[df['time_string'] == 'Max WS']

# time_index=2+ are actual output intervals
df_timeseries = df[df['time_string'] != 'Max WS']

# Parse datetime for analysis
df_timeseries['datetime'] = pd.to_datetime(
    df_timeseries['time_string'],
    format='%d%b%Y %H%M'
)
```

!!! warning "Max WS vs Output Interval Maximums"
    "Max WS" captures peaks that may occur BETWEEN output intervals. This is critical for design applications - always use "Max WS" for peak values, not `max()` of output intervals.

##### Result Columns

**Steady Results** (`get_steady_results`):

| Column | Type | Description |
|--------|------|-------------|
| `river` | str | River name |
| `reach` | str | Reach name |
| `node_id` | str | Cross section station |
| `profile` | str | Profile name |
| `wsel` | float | Water surface elevation |
| `velocity` | float | Total velocity |
| `flow` | float | Total flow |
| `froude` | float | Froude number |
| `energy` | float | Energy grade elevation |
| `max_depth` | float | Maximum channel depth |
| `min_ch_el` | float | Minimum channel elevation |

**Unsteady Results** (`get_unsteady_results`): Same columns plus `time_index`, `time_string`, `datetime`.

##### Compute Messages Fallback

The `get_comp_msgs()` method attempts to read computation messages from multiple sources:

1. First tries `.computeMsgs.txt` (modern format)
2. Falls back to `.comp_msgs.txt` (legacy format)
3. Returns empty string if neither exists

## File Operations

### RasPlan

::: ras_commander.RasPlan
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - clone_plan
        - get_plan_path
        - get_results_path
        - set_geom
        - set_flow
        - set_num_cores
        - set_computation_interval
        - set_output_interval
        - set_description
        - get_value
        - set_value

### RasGeo

::: ras_commander.RasGeo
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - clear_geompre_files
        - get_base_mannings_table
        - get_regional_mannings
        - set_base_mannings_table

### RasUnsteady

::: ras_commander.RasUnsteady
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - clone_unsteady
        - get_unsteady_path
        - set_flow_title
        - set_restart_settings
        - get_boundary_tables

## Utilities

### RasUtils

::: ras_commander.RasUtils
    options:
      show_root_heading: true
      heading_level: 3

#### Method Categories

##### File Operations

| Method | Description |
|--------|-------------|
| `create_directory(path)` | Ensure directory exists, create if needed |
| `find_files_by_extension(folder, ext)` | Find all files with given extension |
| `get_file_size(path)` | Get file size in bytes |
| `get_file_modification_time(path)` | Get file modification timestamp |
| `clone_file(src, dest)` | Copy file to new location |
| `update_file(path, content)` | Write content to file |
| `remove_with_retry(path, retries=3)` | Delete file with retry logic |
| `check_file_access(path, mode)` | Verify file access permissions |

##### Plan/Project Helpers

| Method | Description |
|--------|-------------|
| `normalize_ras_number(number)` | Convert "1", "01", "p01" to "01" format |
| `get_plan_path(plan_number)` | Get full path to plan file |
| `get_next_number(folder, prefix)` | Find next available plan/geom number |
| `update_plan_file(path, key, value)` | Update single key in plan file |
| `update_project_file(prj_path, updates)` | Batch update .prj file |

##### Data Conversion

| Method | Description |
|--------|-------------|
| `convert_to_dataframe(path)` | Load CSV/Excel to DataFrame |
| `save_to_excel(df, path, sheet)` | Save DataFrame to Excel |
| `decode_byte_strings(data)` | Decode HDF byte strings to Python strings |
| `consolidate_dataframe(df, group_by)` | Group and aggregate DataFrame rows |

##### Statistical Analysis

| Method | Description |
|--------|-------------|
| `calculate_rmse(observed, predicted)` | Root Mean Square Error |
| `calculate_percent_bias(obs, pred)` | Percent bias metric |
| `calculate_error_metrics(obs, pred)` | All metrics (RMSE, NSE, PBIAS, R²) |

```python
from ras_commander import RasUtils
import numpy as np

observed = np.array([100, 120, 140, 160, 180])
predicted = np.array([105, 125, 135, 165, 175])

metrics = RasUtils.calculate_error_metrics(observed, predicted)
print(f"RMSE: {metrics['rmse']:.2f}")
print(f"NSE: {metrics['nse']:.3f}")
print(f"PBIAS: {metrics['pbias']:.1f}%")
```

##### Spatial Operations

| Method | Description |
|--------|-------------|
| `perform_kdtree_query(points, query, max_dist)` | Find nearest points using KDTree |
| `find_nearest_neighbors(points, max_dist)` | Find nearest neighbor for each point |
| `find_nearest_value(array, target)` | Find value closest to target |
| `horizontal_distance(p1, p2)` | Calculate 2D distance between points |

```python
from ras_commander import RasUtils
import numpy as np

# Find nearest mesh cell for a list of query points
mesh_centroids = np.array([[0, 0], [10, 10], [20, 20]])
query_points = np.array([[5, 5], [15, 15]])

indices = RasUtils.perform_kdtree_query(
    mesh_centroids,
    query_points,
    max_distance=10.0
)
# Returns [1, 2] - nearest cell indices
```

### RasExamples

::: ras_commander.RasExamples
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - list_projects
        - list_categories
        - extract_project
        - get_project_path

### RasMap

::: ras_commander.RasMap
    options:
      show_root_heading: true
      heading_level: 3
      members:
        - parse_rasmap
        - get_terrain_path
        - get_landcover_path
