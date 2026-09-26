# HDF Data Extraction

RAS Commander provides comprehensive access to HEC-RAS HDF result files through specialized classes.

## Overview

HEC-RAS 5.x and later can store results in HDF5 format (`.p##.hdf` files). Dataset availability depends on the producer version, model family, and output settings. RAS Commander's `Hdf*` classes provide:

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
    ras.plan_df['plan_number'] == '01', 'HDF_Results_Path'
].iloc[0]

# Or using RasPlan
hdf_path = RasPlan.get_results_path("01")
```

## 2D Mesh Results

### Result Shapes and Availability

| Reader | Return and selection | Required retained output |
|---|---|---|
| `get_mesh_max_ws()` | `GeoDataFrame`: `mesh_name`, `cell_id`, `maximum_water_surface`, point `geometry`; optional `maximum_water_surface_time` | 2D summary output and cell centers |
| `get_mesh_timeseries()` | `DataArray`: `time` and `cell_id` (or `face_id` for face variables) | Requested 2D time-series variable |
| `get_mesh_cells_timeseries()` | `dict[str, Dataset]`, keyed by mesh; original HDF variable names such as `Water Surface`; `time`, `cell_id`/`face_id` | Available requested variables for each mesh |
| `get_mesh_faces_timeseries()` | `Dataset`: normalized names such as `face_velocity`; `time`, `face_id` | Available face time-series variables |
| `get_xsec_timeseries()` | `Dataset`: `Water_Surface`, `Flow`, velocity variables; `time`, `cross_section` | Unsteady 1D time series, cross-section attributes, names, and timestamps |

Cell and face IDs are local to a mesh. Inspect `.sizes`, `.coords`, and
`.data_vars` before selecting them. Mesh time-series arrays expose the stored
dataset unit label in `.attrs['units']`; a missing label remains empty. Spatial
outputs use the HDF projection when present (`gdf.crs`); this does not establish
the vertical datum. Use project unit metadata, or
[`HdfBase.get_result_unit_metadata()`](../api/hdf.md#hdfbase) for a standalone
result HDF, and retain the source model's vertical/time reference.

An absent optional output is not a zero-valued result. Summary readers can
return empty frames; the multi-mesh reader omits meshes with no usable requested
variables, and the face reader can return an empty `Dataset`. The single-variable
reader raises `ValueError` when its dataset is absent. The 1D time-series reader
requires its full dataset set and raises when those paths are missing. Inspect
the HDF and producer output settings before choosing another reader; a steady
1D result is not an unsteady cross-section time series.

### Maximum Values

```python
from ras_commander import HdfResultsMesh

# Maximum water surface elevation
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)
if not max_wse.empty:
    print(max_wse[['mesh_name', 'cell_id', 'maximum_water_surface', 'geometry']].head())

# Maximum velocity at cell faces
max_vel = HdfResultsMesh.get_mesh_max_face_v(hdf_path)

# Maximum depth
max_depth = HdfResultsMesh.get_mesh_max_depth(hdf_path)

# Time accompanies the maximum when the producer stored value/time rows
if 'maximum_water_surface_time' in max_wse.columns:
    max_wse_time = max_wse[['mesh_name', 'cell_id', 'maximum_water_surface_time']]
```

`get_mesh_max_depth()` reports one INFO provenance message for every mesh. If
HEC-RAS stored the optional `Depth` time series, ras-commander reads that
dataset without modifying the HDF. If `Depth` is absent, ras-commander derives
depth in memory from `Water Surface - Cells Minimum Elevation`, clips finite
negative values to zero, and does not create or write a `Depth` dataset.

The source message describes the calculation path, not how the input file was
created. Repository tests label temporary, synthetic HDF artifacts separately
from pre-existing producer HDFs written by HEC-RAS. Reading either kind of file
does not run HEC-RAS or generate model output.

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
    "Water Surface",
    truncate=False,
)
print(wse_ts)
print(wse_ts.sizes, list(wse_ts.coords), wse_ts.attrs)

# Available variables: "Water Surface", "Velocity", "Depth"
```

### Cell and Face Data

```python
from ras_commander import HdfResultsMesh

# Read the requested variable, then select cells in the returned Dataset
cell_results = HdfResultsMesh.get_mesh_cells_timeseries(
    hdf_path,
    mesh_names=first_mesh,
    var="Water Surface"
)
cell_dataset = cell_results[first_mesh]  # Requires available Water Surface output
print(cell_dataset.sizes, list(cell_dataset.data_vars))
cell_ts = cell_dataset["Water Surface"].isel(cell_id=slice(0, 4))

# Face time series (flow, velocity)
face_dataset = HdfResultsMesh.get_mesh_faces_timeseries(
    hdf_path,
    mesh_name=first_mesh,
    truncate=False,
)
print(face_dataset.sizes, list(face_dataset.data_vars))
if "face_velocity" in face_dataset:
    face_ts = face_dataset["face_velocity"].isel(face_id=slice(0, 3))
```

These readers load the stored arrays before the xarray selection. `truncate=False`
preserves zero-only leading/trailing timesteps; single-variable and face readers
default to truncation, while the multi-mesh reader defaults to no truncation.

### Profile-Line Flow and Peak Q

Use the profile-line helpers when you need modeled Q across a named RAS Mapper
profile/reference line. The API uses native HDF reference-line internal faces
when present. If those are absent, pass a RAS Mapper Profile Lines feature file
or initialize a project whose `rasmap_df` resolves `profile_lines_path`.

```python
from ras_commander import HdfResultsMesh

flow_ts = HdfResultsMesh.get_profile_line_flow_timeseries(
    hdf_path,
    line_name="Upstream",
    mesh_name="Perimeter 1",
    profile_lines_path="Features/Profile Lines.shp",
    direction="absolute",
)

peak_q = HdfResultsMesh.get_profile_line_peak_flow(
    hdf_path,
    line_name="Upstream",
    mesh_name="Perimeter 1",
    profile_lines_path="Features/Profile Lines.shp",
)
```

`direction="absolute"` sums absolute face flows to avoid cancellation from
opposing face-normal signs. `direction="signed"` preserves native HEC-RAS face
signs, so the line orientation and face normals control the sign convention.

## 1D Cross-Section Results

```python
from ras_commander import HdfResultsXsec

# All cross-section results (returns xarray Dataset)
xsec_results = HdfResultsXsec.get_xsec_timeseries(hdf_path)
print(xsec_results)
print(xsec_results.sizes, list(xsec_results.coords))

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

Compute messages provide stored HEC-RAS diagnostics. A keyword search helps
locate messages for review; it cannot establish successful completion by itself:

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
        print("No matching error keywords; inspect completion evidence separately")

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
except (KeyError, RuntimeError):
    print("No unsteady results found")

# Detailed unsteady summary
try:
    summary = HdfResultsPlan.get_unsteady_summary(hdf_path)
    print("\nUnsteady Summary:")
    print(summary.T)
except (KeyError, RuntimeError):
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

### Result Availability Screening

Combine these reads into a preliminary screen. This checks output availability
and selected diagnostic keywords; it does not verify run identity, numerical
quality, or hydraulic acceptance. Use
[`RasCmdr.inspect_execution_evidence()`](../api/core.md#structured-execution-evidence)
for the library's structured completion evidence.

```python
from ras_commander import HdfResultsPlan

def screen_hdf_results(hdf_path_or_plan):
    """
    Screen retained HDF result availability and message keywords.

    Returns dict with screening status and details.
    """
    result = {
        'passes_screen': False,
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
    result['has_volume_accounting'] = volume is not None and not volume.empty

    # 3. Check unsteady results
    try:
        summary = HdfResultsPlan.get_unsteady_summary(hdf_path_or_plan)
        result['has_unsteady_results'] = summary is not None and not summary.empty
    except (KeyError, ValueError, RuntimeError):
        pass

    # 4. Get runtime
    runtime = HdfResultsPlan.get_runtime_data(hdf_path_or_plan)
    if runtime is not None:
        result['runtime_hours'] = runtime['Complete Process (hr)'].iloc[0]

    # Determine whether this preliminary screen passed
    result['passes_screen'] = (
        result['has_compute_msgs'] and
        not result['has_errors'] and
        result['has_volume_accounting'] and
        result['has_unsteady_results']
    )

    return result

# Usage
status = screen_hdf_results("01")
print(f"Passes preliminary screen: {status['passes_screen']}")
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
perimeters = HdfMesh.get_mesh_areas(hdf_path)
print(perimeters.head())  # mesh_name and polygon geometry
```

## Structure Data

```python
from ras_commander import HdfStruc

# SA/2D connections with retained time-series results
connections = HdfStruc.list_sa2d_connections(hdf_path)
print(connections)

# Structure geometry and attributes (empty when unavailable)
structures = HdfStruc.get_structures(hdf_path)
print(structures.head())
```

Connection profiles and gates in the text geometry use the
[`RasGeometry` connection readers](geometry-operations.md#sa2d-connections).
The connection-name list above describes results availability, not a complete
inventory of every structure authored in the project.

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
    hdf_path, first_mesh, "Water Surface", truncate=False
)

# Select specific cell
cell_0_wse = wse_ts.sel(cell_id=0)

# Plot
cell_0_wse.plot()
plt.title("Water Surface at Cell 0")
plt.show()

# Convert to pandas
wse_df = wse_ts.to_dataframe(name="water_surface")
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
    column='maximum_water_surface',
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
2. **Limit variables and meshes**: Use `var` and `mesh_names` on the multi-mesh reader; selecting cell/face IDs afterward does not reduce initial HDF loading
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
except ValueError as e:
    print(f"Dataset not found in HDF: {e}")
    # Check if plan was fully computed
```
