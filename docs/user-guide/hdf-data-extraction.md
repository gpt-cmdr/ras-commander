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

Plan-level results contain critical information for verifying simulation success and diagnosing issues. These methods are essential for automated workflows and quality control.

### Compute Messages (Error Checking)

The compute messages contain the full HEC-RAS computation log. **This is the primary source for detecting runtime errors:**

```python
from ras_commander import HdfResultsPlan

# Get computation messages
messages = HdfResultsPlan.get_compute_messages(hdf_path)

if messages:
    # Check for errors
    error_keywords = ['ERROR', 'FAILED', 'UNSTABLE', 'ABORTED']
    has_errors = any(kw in messages.upper() for kw in error_keywords)

    if has_errors:
        print("ERRORS DETECTED:")
        for line in messages.split('\n'):
            if any(kw in line.upper() for kw in error_keywords):
                print(f"  {line}")
    else:
        print("Run completed without errors")

    # Check for warnings
    if 'WARNING' in messages.upper():
        print("\nWarnings found - review compute messages")
else:
    print("No compute messages - run may not have completed")
```

**Common error patterns to look for:**
- `"ERROR"` - General computation errors
- `"FAILED"` - Component failures
- `"UNSTABLE"` - Numerical instability
- `"ABORTED"` - Run terminated early

### Volume Accounting (Mass Balance)

Volume accounting verifies mass conservation in the simulation. Large imbalances indicate numerical issues:

```python
from ras_commander import HdfResultsPlan

volume = HdfResultsPlan.get_volume_accounting(hdf_path)

if volume is not None:
    print("Volume Accounting:")
    print(volume.T)  # Transpose for readability

    # Volume accounting attributes may include:
    # - Boundary Conditions In/Out
    # - Precipitation In
    # - Infiltration Out
    # - Storage Area volumes
    # - SA/2D In/Out
    # - Cumulative error percentage
else:
    print("No volume accounting - check if run completed successfully")
```

### Unsteady Results Information

Check that unsteady results were properly generated:

```python
from ras_commander import HdfResultsPlan

# Basic unsteady attributes
try:
    info = HdfResultsPlan.get_unsteady_info(hdf_path)
    print("Unsteady Info:")
    print(info.T)
except KeyError:
    print("No unsteady results found")

# Detailed unsteady summary
try:
    summary = HdfResultsPlan.get_unsteady_summary(hdf_path)
    print("\nUnsteady Summary:")
    print(summary.T)
except KeyError:
    print("No unsteady summary available")
```

### Runtime Statistics

Monitor computation performance:

```python
from ras_commander import HdfResultsPlan

runtime = HdfResultsPlan.get_runtime_data(hdf_path)

if runtime is not None:
    print("Runtime Statistics:")
    print(f"  Plan: {runtime['Plan Name'].iloc[0]}")
    print(f"  File: {runtime['File Name'].iloc[0]}")
    print(f"  Simulation Start: {runtime['Simulation Start Time'].iloc[0]}")
    print(f"  Simulation End: {runtime['Simulation End Time'].iloc[0]}")
    print(f"  Simulation Duration: {runtime['Simulation Time (hr)'].iloc[0]:.2f} hr")
    print(f"  Total Compute Time: {runtime['Complete Process (hr)'].iloc[0]:.4f} hr")
    print(f"  Compute Speed: {runtime['Complete Process Speed (hr/hr)'].iloc[0]:.0f}x realtime")

    # Process breakdown
    if runtime['Unsteady Flow Computations (hr)'].iloc[0] != 'N/A':
        print(f"  Geometry Processing: {runtime['Completing Geometry (hr)'].iloc[0]:.4f} hr")
        print(f"  Unsteady Compute: {runtime['Unsteady Flow Computations (hr)'].iloc[0]:.4f} hr")
```

### Complete Verification Function

Combine all checks into a reusable verification function:

```python
from ras_commander import HdfResultsPlan

def verify_hdf_results(hdf_path_or_plan):
    """
    Comprehensive verification of HDF results.

    Returns dict with verification status and details.
    """
    result = {
        'valid': False,
        'has_compute_msgs': False,
        'has_errors': False,
        'has_volume_accounting': False,
        'has_unsteady_results': False,
        'runtime_hours': None,
        'errors': []
    }

    # 1. Check compute messages
    msgs = HdfResultsPlan.get_compute_messages(hdf_path_or_plan)
    if msgs:
        result['has_compute_msgs'] = True
        error_kw = ['ERROR', 'FAILED', 'UNSTABLE', 'ABORTED']
        if any(kw in msgs.upper() for kw in error_kw):
            result['has_errors'] = True
            for line in msgs.split('\n'):
                if any(kw in line.upper() for kw in error_kw):
                    result['errors'].append(line.strip())

    # 2. Check volume accounting
    volume = HdfResultsPlan.get_volume_accounting(hdf_path_or_plan)
    result['has_volume_accounting'] = volume is not None

    # 3. Check unsteady results
    try:
        HdfResultsPlan.get_unsteady_summary(hdf_path_or_plan)
        result['has_unsteady_results'] = True
    except:
        pass

    # 4. Get runtime
    runtime = HdfResultsPlan.get_runtime_data(hdf_path_or_plan)
    if runtime is not None:
        result['runtime_hours'] = runtime['Complete Process (hr)'].iloc[0]

    # Determine overall validity
    result['valid'] = (
        result['has_compute_msgs'] and
        not result['has_errors'] and
        result['has_volume_accounting']
    )

    return result

# Usage
status = verify_hdf_results("01")
print(f"Valid: {status['valid']}")
if status['errors']:
    print(f"Errors: {status['errors']}")
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
