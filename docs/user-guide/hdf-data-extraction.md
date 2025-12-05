# HDF Data Extraction

RAS Commander provides comprehensive access to HEC-RAS HDF result files through specialized classes.

## Overview

HEC-RAS 6.x stores results in HDF5 format (`.p##.hdf` files). RAS Commander's `Hdf*` classes provide:

- **HdfResultsMesh**: 2D mesh results (WSE, velocity, depth)
- **HdfResultsXsec**: 1D cross-section results
- **HdfResultsPlan**: Plan-level results (volume accounting, runtime)
- **HdfMesh**: Mesh geometry (cells, faces, points)
- **HdfStruc**: Structure data and connections

## Getting HDF File Paths

```python
from ras_commander import init_ras_project, ras, RasPlan

init_ras_project("/path/to/project", "6.5")

# From plan_df
hdf_path = ras.plan_df.loc[
    ras.plan_df['plan_number'] == '01', 'hdf_path'
].iloc[0]

# Or using RasPlan
hdf_path = RasPlan.get_results_path("01")
```

## 2D Mesh Results

### Maximum Values

```python
from ras_commander import HdfResultsMesh

# Maximum water surface elevation
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)
print(max_wse[['cell_id', 'max_ws', 'geometry']].head())

# Maximum velocity at cell faces
max_vel = HdfResultsMesh.get_mesh_max_face_v(hdf_path)

# Maximum depth
max_depth = HdfResultsMesh.get_mesh_max_depth(hdf_path)

# Time of maximum WSE
max_wse_time = HdfResultsMesh.get_mesh_max_ws_time(hdf_path)
```

### Time Series

```python
from ras_commander import HdfResultsMesh, HdfMesh

# Get mesh area names
mesh_names = HdfMesh.get_mesh_area_names(hdf_path)
first_mesh = mesh_names[0]

# Water surface time series (returns xarray DataArray)
wse_ts = HdfResultsMesh.get_mesh_timeseries(
    hdf_path,
    first_mesh,
    "Water Surface"
)
print(wse_ts)

# Available variables: "Water Surface", "Velocity", "Depth"
```

### Cell and Face Data

```python
from ras_commander import HdfResultsMesh

# Cell time series for specific cells
cell_ts = HdfResultsMesh.get_mesh_cells_timeseries(
    hdf_path,
    mesh_name="2D Flow Area",
    cell_ids=[0, 1, 2, 3],
    var="Water Surface"
)

# Face time series (flow, velocity)
face_ts = HdfResultsMesh.get_mesh_faces_timeseries(
    hdf_path,
    mesh_name="2D Flow Area",
    face_ids=[10, 11, 12],
    var="Face Velocity"
)
```

## 1D Cross-Section Results

```python
from ras_commander import HdfResultsXsec

# All cross-section results (returns xarray Dataset)
xsec_results = HdfResultsXsec.get_xsec_timeseries(hdf_path)
print(xsec_results)

# Available variables typically include:
# - Water_Surface
# - Flow
# - Velocity_Channel
# - Velocity_Total

# Extract specific cross-section
xs_name = xsec_results['cross_section'][0].item()
wse_xs = xsec_results['Water_Surface'].sel(cross_section=xs_name)
```

## Plan-Level Results

```python
from ras_commander import HdfResultsPlan

# Runtime statistics
runtime = HdfResultsPlan.get_runtime_data(hdf_path)
print(runtime)

# Volume accounting
volume = HdfResultsPlan.get_volume_accounting(hdf_path)
print(volume)

# Computation messages
messages = HdfResultsPlan.get_compute_messages(hdf_path)
print(messages)

# Computation options used
options = HdfResultsPlan.get_compute_options(hdf_path)
```

## Mesh Geometry

```python
from ras_commander import HdfMesh

# Cell polygons as GeoDataFrame
cells = HdfMesh.get_mesh_cell_polygons(hdf_path)
print(cells[['cell_id', 'geometry']].head())

# Cell face lines
faces = HdfMesh.get_mesh_cell_faces(hdf_path)

# Cell center points
points = HdfMesh.get_mesh_cell_points(hdf_path)

# Mesh area perimeter
perimeter = HdfMesh.get_mesh_perimeter(hdf_path)
```

## Structure Data

```python
from ras_commander import HdfStruc

# SA/2D Connections
connections = HdfStruc.get_connection_list(hdf_path)
print(connections)

# Connection profiles
profile = HdfStruc.get_connection_profile(hdf_path, "Connection 1")

# Gate data
gates = HdfStruc.get_connection_gates(hdf_path, "Connection 1")
```

## Pipe Networks

```python
from ras_commander import HdfPipe

# Pipe conduit geometry
conduits = HdfPipe.get_pipe_conduits(hdf_path)

# Pipe node locations
nodes = HdfPipe.get_pipe_nodes(hdf_path)

# Node depth time series
node_depth = HdfPipe.get_pipe_network_timeseries(
    hdf_path,
    "Nodes/Depth"
)

# Pipe network summary
summary = HdfPipe.get_pipe_network_summary(hdf_path)
```

## Pump Stations

```python
from ras_commander import HdfPump

# Pump station locations
stations = HdfPump.get_pump_stations(hdf_path)

# Pump group details
groups = HdfPump.get_pump_groups(hdf_path)

# Station time series
pump_ts = HdfPump.get_pump_station_timeseries(
    hdf_path,
    "Pump Station 1"
)

# Pump operation history
operation = HdfPump.get_pump_operation_timeseries(
    hdf_path,
    "Pump Station 1"
)
```

## Exploring HDF Structure

```python
from ras_commander import HdfBase

# Print HDF file structure
HdfBase.get_dataset_info(hdf_path)

# Explore specific group
HdfBase.get_dataset_info(
    hdf_path,
    group_path="/Results/Unsteady/Output"
)
```

## Working with xarray Results

Many methods return xarray DataArrays or Datasets:

```python
import matplotlib.pyplot as plt

# Get time series
wse_ts = HdfResultsMesh.get_mesh_timeseries(
    hdf_path, "2D Flow Area", "Water Surface"
)

# Select specific cell
cell_0_wse = wse_ts.sel(cell=0)

# Plot
cell_0_wse.plot()
plt.title("Water Surface at Cell 0")
plt.show()

# Convert to pandas
wse_df = wse_ts.to_dataframe()
```

## Working with GeoDataFrames

Geometry methods return GeoPandas GeoDataFrames:

```python
import matplotlib.pyplot as plt

# Get max WSE with geometry
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)

# Plot
fig, ax = plt.subplots(figsize=(10, 8))
max_wse.plot(
    column='max_ws',
    cmap='Blues',
    legend=True,
    ax=ax
)
plt.title("Maximum Water Surface Elevation")
plt.show()

# Export to file
max_wse.to_file("max_wse.geojson", driver="GeoJSON")
```

## Performance Tips

1. **Use specific methods**: `get_mesh_max_ws()` is faster than extracting all time series
2. **Limit cell/face selections**: Specify `cell_ids` or `face_ids` when possible
3. **Close files**: HDF files are closed automatically, but avoid keeping many open
4. **Memory**: Large models may require chunked processing

## Common Issues

### HDF File Not Found

```python
from pathlib import Path

hdf_path = RasPlan.get_results_path("01")
if hdf_path is None or not Path(hdf_path).exists():
    print("No HDF results - run the plan first")
```

### Missing Data

```python
try:
    max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)
except KeyError as e:
    print(f"Dataset not found in HDF: {e}")
    # Check if plan was fully computed
```
