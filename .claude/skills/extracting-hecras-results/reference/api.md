# API Reference: Extracting HEC-RAS Results

Complete API documentation for HDF results extraction classes.

## HdfResultsPlan

Core class for plan-level results and metadata.

### Detection and Metadata

#### `is_steady_plan(plan_or_hdf_path)`

Check if HDF contains steady state results.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `bool`: True if steady state plan, False if unsteady

**Example:**
```python
is_steady = HdfResultsPlan.is_steady_plan("02")
if is_steady:
    print("Extracting steady state results...")
```

---

#### `get_plan_info(plan_or_hdf_path)`

Extract plan metadata and attributes.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `pd.DataFrame`: Plan information with columns:
  - `Program Name` (str)
  - `Program Version` (str)
  - `Project File Name` (str)
  - `Type of Run` (str)
  - `Run Time Window` (str)

**Example:**
```python
info = HdfResultsPlan.get_plan_info("01")
print(f"HEC-RAS version: {info['Program Version'].iloc[0]}")
```

---

#### `get_compute_messages(plan_or_hdf_path)`

Extract computation log messages.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `str`: Full computation log text

**Example:**
```python
messages = HdfResultsPlan.get_compute_messages("01")
if "ERROR" in messages:
    print("Computation errors detected!")
```

---

#### `get_output_times(plan_or_hdf_path)`

Get all output timesteps from unsteady simulation.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `pd.DataFrame`: Timesteps with columns:
  - `timestep` (int): 0, 1, 2, ...
  - `datetime` (datetime64): timestamp
  - `hours` (float): hours since simulation start

**Example:**
```python
times = HdfResultsPlan.get_output_times("01")
print(f"Simulation duration: {times['hours'].max()} hours")
print(f"Total timesteps: {len(times)}")
```

---

### Steady Flow Results

#### `get_steady_profile_names(plan_or_hdf_path)`

List all steady state profile names.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `list[str]`: Profile names (e.g., ['.5 year', '1 year', '2 year', ...])

**Example:**
```python
profiles = HdfResultsPlan.get_steady_profile_names("02")
print(f"Available profiles: {profiles}")
```

---

#### `get_steady_wse(plan_or_hdf_path, profile_name=None, profile_index=None)`

Extract water surface elevations for steady state profiles.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `profile_name` (str, optional): Specific profile name (e.g., "100 year")
- `profile_index` (int, optional): Specific profile index (0-based)

**Returns:**
- `pd.DataFrame`: Water surface elevations
  - If single profile: columns are `River`, `Reach`, `Station`, `WSE`
  - If all profiles: additional `Profile` column

**Example:**
```python
# Single profile
wse_100 = HdfResultsPlan.get_steady_wse("02", profile_name="100 year")

# By index
wse_first = HdfResultsPlan.get_steady_wse("02", profile_index=0)

# All profiles
wse_all = HdfResultsPlan.get_steady_wse("02")
```

---

#### `get_steady_info(plan_or_hdf_path)`

Extract steady flow metadata.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `pd.DataFrame`: Metadata with columns:
  - `Program Version` (str)
  - `Solution` (str): e.g., "Steady Finished Successfully"
  - `Flow Title` (str)
  - `Flow Filename` (str)
  - `Run Time Window` (str)

**Example:**
```python
info = HdfResultsPlan.get_steady_info("02")
print(f"Solution status: {info['Solution'].iloc[0]}")
```

---

#### `list_steady_variables(plan_or_hdf_path)`

Discover all available steady state variables.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `dict`: Variable categories:
  - `'cross_sections'`: Basic XS variables (WSE, Flow, Energy Grade)
  - `'additional'`: Detailed variables (Velocity, Depth, Manning's n, etc.)
  - `'structures'`: Structure variables (if present)

**Example:**
```python
vars_dict = HdfResultsPlan.list_steady_variables("02")
print(f"XS variables: {vars_dict['cross_sections']}")
print(f"Additional: {vars_dict['additional']}")
```

---

#### `get_steady_data(plan_or_hdf_path, variable, profile_name=None, profile_index=None)`

Extract specific steady state variable.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `variable` (str): Variable name (from `list_steady_variables()`)
- `profile_name` (str, optional): Specific profile
- `profile_index` (int, optional): Specific profile index

**Returns:**
- `pd.DataFrame`: Same structure as `get_steady_wse()` but for requested variable

**Example:**
```python
velocity = HdfResultsPlan.get_steady_data("02", variable="Velocity Total")
depth = HdfResultsPlan.get_steady_data("02", variable="Hydraulic Depth Total")
```

---

## HdfResultsXsec

Cross section results for unsteady flow.

### `get_xsec_timeseries(plan_or_hdf_path)`

Extract time series for all cross sections.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `xarray.Dataset`: Time series data
  - **Dimensions:**
    - `time` (datetime64[ns])
    - `cross_section` (str): "River Reach Station"
  - **Coordinates:**
    - `time`, `cross_section`, `River`, `Reach`, `Station`, `Name`
    - `Maximum_Water_Surface`, `Maximum_Flow`, `Maximum_Channel_Velocity`, `Maximum_Velocity_Total`
  - **Data variables:**
    - `Water_Surface` (time, cross_section)
    - `Velocity_Total` (time, cross_section)
    - `Velocity_Channel` (time, cross_section)
    - `Flow` (time, cross_section)
    - `Flow_Lateral` (time, cross_section)

**Example:**
```python
xsec_ts = HdfResultsXsec.get_xsec_timeseries("01")

# Access specific variable
wse = xsec_ts["Water_Surface"]

# Get specific cross section
target = "Bald Eagle       Loc Hav          136202.3"
wse_at_xs = wse.sel(cross_section=target)

# Convert to DataFrame
df = wse_at_xs.to_dataframe()
```

---

## HdfResultsMesh

2D mesh results for unsteady flow.

### `get_mesh_maximum(plan_or_hdf_path, variable="Water Surface", mesh_name=None)`

Extract maximum values over entire simulation.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `variable` (str): Variable name ("Water Surface", "Depth", "Velocity", etc.)
- `mesh_name` (str, optional): Specific 2D area name (auto-detected if single area)

**Returns:**
- `pd.DataFrame`: Maximum values with columns:
  - `cell_id` (int)
  - `max_value` (float)
  - `max_time` (datetime64): when maximum occurred
  - `geometry` (shapely.Polygon): cell polygon

**Example:**
```python
max_wse = HdfResultsMesh.get_mesh_maximum("01", variable="Water Surface")
max_depth = HdfResultsMesh.get_mesh_maximum("01", variable="Depth")

# Find cells with depth > 10 ft
deep_cells = max_wse[max_wse['max_value'] > 10]
```

---

### `get_mesh_timeseries(plan_or_hdf_path, timestep_indices=None, variables=None, mesh_name=None)`

Extract time series at mesh cells.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `timestep_indices` (list[int] | str, optional): Specific timesteps or "all"
- `variables` (list[str], optional): Variable names (default: ["Water Surface", "Depth", "Velocity"])
- `mesh_name` (str, optional): Specific 2D area name

**Returns:**
- `pd.DataFrame`: Time series with columns:
  - `cell_id` (int)
  - `timestep` (int)
  - `datetime` (datetime64)
  - `Water_Surface` (float)
  - `Depth` (float)
  - `Velocity` (float)
  - ... (other requested variables)

**Example:**
```python
# Specific timesteps
mesh_ts = HdfResultsMesh.get_mesh_timeseries(
    "01",
    timestep_indices=[0, 50, 100, 150]
)

# All timesteps (caution: large files)
mesh_ts_all = HdfResultsMesh.get_mesh_timeseries("01", timestep_indices="all")
```

---

## HdfResultsBreach

Dam breach results extraction.

### `get_breach_timeseries(plan_or_hdf_path, structure_name)`

Extract complete breach time series.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `structure_name` (str): Structure name (from `HdfStruc.list_sa2d_connections()`)

**Returns:**
- `pd.DataFrame`: Time series with columns:
  - `datetime` (datetime64)
  - `total_flow` (float): combined weir + breach flow
  - `weir_flow` (float)
  - `breach_flow` (float)
  - `hw` (float): headwater elevation
  - `tw` (float): tailwater elevation
  - `bottom_width` (float): breach width evolution
  - `bottom_elevation` (float)
  - `left_slope`, `right_slope` (float)
  - `breach_velocity` (float)
  - `breach_flow_area` (float)

**Example:**
```python
breach_ts = HdfResultsBreach.get_breach_timeseries("02", "Dam")

# Find peak breach flow
peak_flow = breach_ts['breach_flow'].max()
peak_time = breach_ts.loc[breach_ts['breach_flow'].idxmax(), 'datetime']
```

---

### `get_breach_summary(plan_or_hdf_path, structure_name=None)`

Extract breach summary statistics.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `structure_name` (str, optional): Structure name (None for all structures)

**Returns:**
- `pd.DataFrame`: Summary with columns:
  - `structure` (str)
  - `breach_initiated` (bool)
  - `breach_at_time` (float): hours from start
  - `breach_at_date` (str): formatted date/time
  - `max_total_flow` (float)
  - `max_total_flow_time` (datetime64)
  - `max_breach_flow` (float)
  - `max_breach_flow_time` (datetime64)
  - `final_breach_width` (float)
  - `final_breach_depth` (float)
  - `max_hw` (float)
  - `max_tw` (float)

**Example:**
```python
summary = HdfResultsBreach.get_breach_summary("02", "Dam")
print(f"Peak breach flow: {summary['max_breach_flow'].iloc[0]:,.0f} cfs")
print(f"Final breach width: {summary['final_breach_width'].iloc[0]:.1f} ft")
```

---

### `get_breaching_variables(plan_or_hdf_path, structure_name)`

Extract breach geometry evolution.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `structure_name` (str): Structure name

**Returns:**
- `pd.DataFrame`: Breach geometry over time:
  - `datetime` (datetime64)
  - `hw`, `tw` (float)
  - `bottom_width` (float): width evolution
  - `bottom_elevation` (float)
  - `left_slope`, `right_slope` (float)
  - `breach_flow` (float)
  - `breach_velocity` (float)
  - `breach_flow_area` (float)

**Example:**
```python
breach_geom = HdfResultsBreach.get_breaching_variables("02", "Dam")

# Plot width evolution
import matplotlib.pyplot as plt
plt.plot(breach_geom['datetime'], breach_geom['bottom_width'])
plt.xlabel("Time")
plt.ylabel("Breach Width (ft)")
```

---

### `get_structure_variables(plan_or_hdf_path, structure_name)`

Extract all available structure variables.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path
- `structure_name` (str): Structure name

**Returns:**
- `pd.DataFrame`: All structure variables over time

**Example:**
```python
all_vars = HdfResultsBreach.get_structure_variables("02", "Dam")
print(f"Available columns: {list(all_vars.columns)}")
```

---

## HdfStruc

Structure geometry and metadata (prerequisite for breach operations).

### `list_sa2d_connections(plan_or_hdf_path)`

List SA/2D connection structures.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `list[str]`: Structure names

**Example:**
```python
structures = HdfStruc.list_sa2d_connections("02")
print(f"Structures: {structures}")
# Output: ['Dam', 'Spillway', ...]
```

---

### `get_sa2d_breach_info(plan_or_hdf_path)`

Get breach capability information.

**Parameters:**
- `plan_or_hdf_path` (str | Path): Plan number or full HDF path

**Returns:**
- `pd.DataFrame`: Breach info with columns:
  - `structure` (str)
  - `has_breach` (bool)
  - `breach_at_date` (str)
  - `breach_at_time` (float)
  - `centerline_breach` (float)

**Example:**
```python
breach_info = HdfStruc.get_sa2d_breach_info("02")
breach_structures = breach_info[breach_info['has_breach']]['structure'].tolist()
```

---

## Common Return Structures

### Steady WSE DataFrame
```python
pd.DataFrame:
    River: str (e.g., "Bald Eagle")
    Reach: str (e.g., "Loc Hav")
    Station: str (e.g., "138154.4")
    Profile: str (e.g., "100 year") - only for multiple profiles
    WSE: float (water surface elevation)
```

### Unsteady XS xarray Dataset
```python
xarray.Dataset:
    dims: (time: 150, cross_section: 178)
    coords:
        time: datetime64[ns]
        cross_section: str ("River Reach Station")
        River, Reach, Station, Name: str
        Maximum_Water_Surface, Maximum_Flow, etc.: float
    data_vars:
        Water_Surface: (time, cross_section) float
        Velocity_Total: (time, cross_section) float
        Flow: (time, cross_section) float
```

### Mesh Maximum DataFrame
```python
pd.DataFrame:
    cell_id: int
    max_value: float
    max_time: datetime64
    geometry: shapely.Polygon
```

### Breach Time Series DataFrame
```python
pd.DataFrame:
    datetime: datetime64
    total_flow: float
    weir_flow: float
    breach_flow: float
    hw, tw: float
    bottom_width, bottom_elevation: float
    left_slope, right_slope: float
    breach_velocity, breach_flow_area: float
```
