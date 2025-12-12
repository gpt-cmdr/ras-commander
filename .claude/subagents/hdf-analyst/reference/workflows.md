# Common HDF Workflows

Complete workflow patterns for the most common HDF analysis tasks.

## 1. Steady Flow Results Extraction

Extract water surface elevations and other variables from steady flow simulations.

### 1.1 Basic Steady Flow Workflow

```python
from ras_commander import HdfResultsPlan, init_ras_project
from pathlib import Path

# Initialize project
project_dir = Path(r"C:/HEC-RAS/MyProject")
init_ras_project(project_dir, "6.5")

# Check if plan has steady results
plan_hdf = "plan.p01.hdf"
if HdfResultsPlan.is_steady_plan(plan_hdf):
    print("Plan contains steady flow results")

    # Get profile names
    profiles = HdfResultsPlan.get_steady_profile_names(plan_hdf)
    print(f"Profiles: {profiles}")

    # Extract water surface elevations
    wse_df = HdfResultsPlan.get_steady_wse(plan_hdf)
    print(wse_df.head())
    # Index: Cross section IDs (river-reach-RS)
    # Columns: Profile names
    # Values: WSE in project units
else:
    print("Plan contains unsteady flow results")
```

### 1.2 Extract Specific Profile

```python
# Get WSE for a single profile
profile_name = "100yr"
wse_df = HdfResultsPlan.get_steady_wse(plan_hdf, profile=profile_name)

# Get other steady variables
velocity = HdfResultsPlan.get_steady_results(plan_hdf, "Velocity", profile_name)
depth = HdfResultsPlan.get_steady_results(plan_hdf, "Depth", profile_name)

# List all available variables
variables = HdfResultsPlan.list_steady_variables(plan_hdf)
print(f"Available variables: {variables}")
```

### 1.3 Export to Shapefile

```python
from ras_commander import HdfXsec
import geopandas as gpd

# Get cross section geometry
xs_points = HdfXsec.get_cross_section_points(plan_hdf)

# Get WSE for profile
wse_df = HdfResultsPlan.get_steady_wse(plan_hdf, profile="100yr")

# Join geometry and results
xs_points['WSE_100yr'] = xs_points.index.map(wse_df['100yr'])

# Export to shapefile
xs_points.to_file("cross_sections_100yr.shp")
```

## 2. Unsteady Flow Time Series

Extract and analyze time series from unsteady flow simulations.

### 2.1 Basic Unsteady Workflow

```python
from ras_commander import HdfResultsPlan, HdfResultsMesh

# Get simulation metadata
info = HdfResultsPlan.get_unsteady_info("plan.p01.hdf")
print(f"Start time: {info['Start Time']}")
print(f"End time: {info['End Time']}")
print(f"Interval: {info['Computation Interval']}")

# Get summary statistics
summary = HdfResultsPlan.get_unsteady_summary("plan.p01.hdf")
print(summary)

# Get volume accounting
vol_acct = HdfResultsPlan.get_volume_accounting("plan.p01.hdf")
print(f"Total inflow: {vol_acct['Total Inflow'].sum()}")
print(f"Total outflow: {vol_acct['Total Outflow'].sum()}")
```

### 2.2 Extract Mesh Time Series

```python
import xarray as xr

# Get complete time series for a variable
depth_ts = HdfResultsMesh.get_mesh_timeseries(
    "plan.p01.hdf",
    variable="Depth",
    mesh_name="2D Area"
)

# xr.DataArray with dimensions (time, cell_id)
print(f"Shape: {depth_ts.shape}")
print(f"Times: {len(depth_ts.time)}")
print(f"Cells: {len(depth_ts.cell_id)}")

# Get time series for specific cells
cell_ids = [100, 200, 300]
depth_cells = HdfResultsMesh.get_mesh_cells_timeseries(
    "plan.p01.hdf",
    variable="Depth",
    mesh_name="2D Area",
    cell_ids=cell_ids
)

# DataFrame with columns for each cell
print(depth_cells.head())
```

### 2.3 Extract Maximum Envelopes

```python
# Get maximum water surface envelope
max_ws = HdfResultsMesh.get_mesh_max_ws("plan.p01.hdf", "2D Area")

# GeoDataFrame with geometry and max_ws attribute
print(max_ws[['cell_id', 'max_ws', 'geometry']].head())

# Get maximum velocity envelope
max_vel = HdfResultsMesh.get_mesh_max_face_v("plan.p01.hdf", "2D Area")

# Export to shapefile
max_ws.to_file("max_water_surface.shp")
max_vel.to_file("max_velocity.shp")
```

### 2.4 Time Series at Specific Location

```python
from ras_commander import HdfMesh
from shapely.geometry import Point

# Define point of interest
poi = Point(-123.45, 45.67)

# Find nearest cell
nearest = HdfMesh.find_nearest_cell(
    "geom.g01.hdf",
    point=poi,
    mesh_name="2D Area"
)
cell_id = nearest['cell_id']

# Get time series for that cell
depth_ts = HdfResultsMesh.get_mesh_cells_timeseries(
    "plan.p01.hdf",
    variable="Depth",
    mesh_name="2D Area",
    cell_ids=[cell_id]
)

# Plot time series
import matplotlib.pyplot as plt
depth_ts.plot()
plt.title(f"Depth at Cell {cell_id}")
plt.ylabel("Depth (ft)")
plt.xlabel("Time")
plt.show()
```

## 3. 2D Mesh Analysis

Work with 2D mesh geometry and perform spatial queries.

### 3.1 Extract Mesh Geometry

```python
from ras_commander import HdfMesh

# Get mesh area names
areas = HdfMesh.get_mesh_area_names("geom.g01.hdf")
print(f"2D areas: {areas}")

# Get mesh area perimeters
area_polys = HdfMesh.get_mesh_areas("geom.g01.hdf")
print(area_polys)

# Get cell polygons
cells = HdfMesh.get_mesh_cell_polygons("geom.g01.hdf", "2D Area")
print(f"Number of cells: {len(cells)}")

# Get cell center points
points = HdfMesh.get_mesh_cell_points("geom.g01.hdf", "2D Area")

# Get cell faces (edges)
faces = HdfMesh.get_mesh_cell_faces("geom.g01.hdf", "2D Area")
```

### 3.2 Spatial Queries

```python
from shapely.geometry import Point, LineString, box

# Find cells within bounding box
bbox = box(minx=-123.5, miny=45.6, maxx=-123.4, maxy=45.7)
cells = HdfMesh.get_mesh_cell_polygons("geom.g01.hdf", "2D Area")
cells_in_bbox = cells[cells.geometry.intersects(bbox)]

# Find nearest cell to a point
poi = Point(-123.45, 45.67)
nearest = HdfMesh.find_nearest_cell("geom.g01.hdf", poi, "2D Area")
print(f"Nearest cell: {nearest['cell_id']}")

# Find faces along a profile line
profile_line = LineString([(-123.5, 45.65), (-123.4, 45.65)])
face_ids = HdfMesh.get_faces_along_profile_line(
    "geom.g01.hdf",
    profile_line,
    "2D Area"
)
print(f"Faces crossing line: {face_ids}")
```

### 3.3 Mesh Property Tables

```python
# Get face property tables (area, length, etc.)
face_props = HdfMesh.get_mesh_face_property_tables("geom.g01.hdf", "2D Area")
print(face_props.head())

# Get cell property tables (area, volume, elevation)
cell_props = HdfMesh.get_mesh_cell_property_tables("geom.g01.hdf", "2D Area")
print(cell_props.head())

# Join with geometry for analysis
cells = HdfMesh.get_mesh_cell_polygons("geom.g01.hdf", "2D Area")
cells = cells.merge(cell_props, left_on='cell_id', right_index=True)

# Find cells with area > 1000 sq ft
large_cells = cells[cells['area'] > 1000]
```

## 4. Structure Data Extraction

Extract data for inline structures, bridges, culverts, and dam breaches.

### 4.1 Dam Breach Results

```python
from ras_commander import HdfResultsBreach

# Get summary of all breaches
breach_summary = HdfResultsBreach.get_breach_summary("plan.p01.hdf")
print(breach_summary)

# Get complete time series for a specific structure
breach_ts = HdfResultsBreach.get_breach_timeseries(
    "plan.p01.hdf",
    structure_name="Dam 1"
)
print(breach_ts.head())
# Columns: flow, stage, breach_width, breach_depth, breach_area

# Get breach geometry evolution
breach_geom = HdfResultsBreach.get_breaching_variables(
    "plan.p01.hdf",
    "Dam 1"
)

# Plot breach development
import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 1, figsize=(10, 8))

breach_ts['breach_width'].plot(ax=axes[0])
axes[0].set_ylabel('Width (ft)')
axes[0].set_title('Breach Width Evolution')

breach_ts['flow'].plot(ax=axes[1])
axes[1].set_ylabel('Flow (cfs)')
axes[1].set_title('Breach Outflow')

plt.tight_layout()
plt.show()
```

### 4.2 Structure Geometry

```python
from ras_commander import HdfStruc

# Get 2D structure locations
structures = HdfStruc.get_2d_structures("geom.g01.hdf", "2D Area")
print(structures)

# Get SA/2D area connections
connections = HdfStruc.get_sa_2d_connections("geom.g01.hdf")
print(connections)

# Export to shapefile
structures.to_file("structures_2d.shp")
connections.to_file("sa_2d_connections.shp")
```

### 4.3 Pipe and Pump Networks

```python
from ras_commander import HdfPipe, HdfPump

# Get pipe network geometry
pipes = HdfPipe.get_pipe_geometry("plan.p01.hdf")
print(f"Number of pipes: {len(pipes)}")

# Get pipe flow time series
pipe_flow = HdfPipe.get_pipe_timeseries(
    "plan.p01.hdf",
    pipe_id="Pipe-1",
    variable="Flow"
)

# Get pump stations
pumps = HdfPump.get_pump_geometry("plan.p01.hdf")

# Get pump operation time series
pump_flow = HdfPump.get_pump_timeseries(
    "plan.p01.hdf",
    pump_id="Pump-1",
    variable="Flow"
)
```

## 5. Cross Section Analysis

Extract cross section geometry and results.

### 5.1 Cross Section Geometry

```python
from ras_commander import HdfXsec

# Get cross section metadata
xs_info = HdfXsec.get_cross_section_info("geom.g01.hdf")
print(xs_info.head())
# Columns: river, reach, rs, node_name

# Get station-elevation for specific XS
xs_geom = HdfXsec.get_cross_section_geometry(
    "geom.g01.hdf",
    river="Main River",
    reach="Upper Reach",
    rs="1000"
)
print(xs_geom.head())
# Columns: station, elevation, mannings_n

# Plot cross section
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
plt.plot(xs_geom['station'], xs_geom['elevation'])
plt.xlabel('Station (ft)')
plt.ylabel('Elevation (ft)')
plt.title('Cross Section Main River - Upper Reach - 1000')
plt.grid(True)
plt.show()
```

### 5.2 Hydraulic Property Tables (HTAB)

```python
from ras_commander import HdfHydraulicTables

# Get HTAB for cross section
htab = HdfHydraulicTables.get_xs_htab(
    "geom.g01.hdf",
    river="Main River",
    reach="Upper Reach",
    rs="1000"
)
print(htab.head())
# Columns: elevation, area, wetted_perimeter, conveyance

# Plot area vs elevation (rating curve components)
import matplotlib.pyplot as plt
fig, axes = plt.subplots(1, 3, figsize=(15, 5))

htab.plot(x='elevation', y='area', ax=axes[0])
axes[0].set_ylabel('Area (ft²)')

htab.plot(x='elevation', y='wetted_perimeter', ax=axes[1])
axes[1].set_ylabel('Wetted Perimeter (ft)')

htab.plot(x='elevation', y='conveyance', ax=axes[2])
axes[2].set_ylabel('Conveyance')

plt.tight_layout()
plt.show()
```

### 5.3 Cross Section Results

```python
from ras_commander import HdfResultsXsec

# Get time series for specific XS
xs_ts = HdfResultsXsec.get_xs_timeseries(
    "plan.p01.hdf",
    variable="Water Surface",
    river="Main River",
    reach="Upper Reach",
    rs="1000"
)

# Plot hydrograph
xs_ts.plot()
plt.title('Water Surface Elevation at XS 1000')
plt.ylabel('WSE (ft)')
plt.xlabel('Time')
plt.show()

# Get summary statistics
xs_summary = HdfResultsXsec.get_xs_summary(
    "plan.p01.hdf",
    river="Main River",
    reach="Upper Reach",
    rs="1000"
)
print(f"Max WSE: {xs_summary['max_ws']}")
print(f"Max velocity: {xs_summary['max_velocity']}")
```

## 6. Multi-Plan Comparison

Compare results across multiple plans.

### 6.1 Compare Maximum Envelopes

```python
from ras_commander import HdfResultsMesh
import geopandas as gpd

# Extract maximum WSE for multiple plans
plans = ["plan.p01.hdf", "plan.p02.hdf", "plan.p03.hdf"]
plan_names = ["Existing", "Alternative 1", "Alternative 2"]

max_ws_list = []
for plan, name in zip(plans, plan_names):
    max_ws = HdfResultsMesh.get_mesh_max_ws(plan, "2D Area")
    max_ws['plan'] = name
    max_ws_list.append(max_ws)

# Combine into single GeoDataFrame
all_max_ws = gpd.GeoDataFrame(pd.concat(max_ws_list, ignore_index=True))

# Pivot to get one column per plan
comparison = all_max_ws.pivot_table(
    index='cell_id',
    columns='plan',
    values='max_ws'
)

# Calculate differences
comparison['Alt1_vs_Existing'] = comparison['Alternative 1'] - comparison['Existing']
comparison['Alt2_vs_Existing'] = comparison['Alternative 2'] - comparison['Existing']

# Export comparison
comparison.to_csv("plan_comparison.csv")
```

### 6.2 Volume Accounting Comparison

```python
from ras_commander import HdfResultsPlan
import pandas as pd

# Get volume accounting for all plans
vol_acct_list = []
for plan, name in zip(plans, plan_names):
    vol_acct = HdfResultsPlan.get_volume_accounting(plan)
    vol_acct['plan'] = name
    vol_acct_list.append(vol_acct)

# Combine and compare
all_vol_acct = pd.concat(vol_acct_list)

# Summarize by plan
summary = all_vol_acct.groupby('plan').sum()
print(summary[['Total Inflow', 'Total Outflow', 'Error']])
```

## 7. Reference Features

Extract time series and summary data from reference lines and points.

### 7.1 Reference Line Time Series

```python
from ras_commander import HdfResultsPlan

# Get reference line time series
ref_lines = HdfResultsPlan.get_reference_timeseries(
    "plan.p01.hdf",
    reftype="line"
)
print(ref_lines.head())

# Get summary statistics for reference lines
ref_line_summary = HdfResultsPlan.get_reference_summary(
    "plan.p01.hdf",
    reftype="line"
)
print(ref_line_summary)
```

### 7.2 Reference Point Time Series

```python
# Get reference point time series
ref_points = HdfResultsPlan.get_reference_timeseries(
    "plan.p01.hdf",
    reftype="point"
)

# Get summary for reference points
ref_point_summary = HdfResultsPlan.get_reference_summary(
    "plan.p01.hdf",
    reftype="point"
)

# Plot time series for specific reference point
point_name = "Gauge-1"
if point_name in ref_points.columns:
    ref_points[point_name].plot()
    plt.title(f'Water Surface at {point_name}')
    plt.ylabel('WSE (ft)')
    plt.show()
```

## 8. Computation Messages and Diagnostics

Extract computation messages and runtime information.

### 8.1 Get Computation Messages

```python
from ras_commander import HdfResultsPlan

# Get computation messages (from HDF or .txt fallback)
messages = HdfResultsPlan.get_compute_messages("plan.p01.hdf")
print(messages)

# Search for specific messages
if "warning" in messages.lower():
    print("Warnings found in computation messages")

if "error" in messages.lower():
    print("Errors found in computation messages")
```

### 8.2 Runtime Analysis

```python
# Get runtime data
runtime = HdfResultsPlan.get_runtime_data("plan.p01.hdf")
print(f"Total runtime: {runtime['Total Runtime']}")
print(f"Computation time: {runtime['Computation Time']}")
print(f"Iterations: {runtime['Total Iterations']}")

# Get unsteady summary
summary = HdfResultsPlan.get_unsteady_summary("plan.p01.hdf")
print(f"Max iterations: {summary['Max Iterations']}")
print(f"Max water surface error: {summary['Max WS Error']}")
```

## 9. Fluvial-Pluvial Analysis

Distinguish riverine vs rainfall-driven flooding.

### 9.1 Source Delineation

```python
from ras_commander import HdfFluvialPluvial

# Delineate fluvial vs pluvial flooding
source_map = HdfFluvialPluvial.delineate_fluvial_pluvial(
    "plan.p01.hdf",
    mesh_name="2D Area",
    threshold=0.5  # Depth threshold (ft)
)

# GeoDataFrame with 'source' attribute: 'fluvial', 'pluvial', or 'mixed'
print(source_map['source'].value_counts())

# Export to shapefile
source_map.to_file("flood_source_delineation.shp")
```

### 9.2 Contributing Area Analysis

```python
# Calculate contributing drainage area at a point
poi = Point(-123.45, 45.67)
drainage_area = HdfFluvialPluvial.calculate_contributing_area(
    "geom.g01.hdf",
    mesh_name="2D Area",
    point=poi
)
print(f"Drainage area: {drainage_area} sq ft")
```

## 10. Batch Processing

Process multiple HDF files efficiently.

### 10.1 Extract All Plan Results

```python
from pathlib import Path
from ras_commander import HdfResultsPlan, HdfResultsMesh

# Find all plan HDF files
project_dir = Path(r"C:/HEC-RAS/MyProject")
plan_hdfs = list(project_dir.glob("*.p*.hdf"))

# Extract maximum WSE for all plans
for plan_hdf in plan_hdfs:
    plan_name = plan_hdf.stem
    print(f"Processing {plan_name}...")

    # Check if steady or unsteady
    if HdfResultsPlan.is_steady_plan(plan_hdf):
        wse = HdfResultsPlan.get_steady_wse(plan_hdf)
        wse.to_csv(f"{plan_name}_steady_wse.csv")
    else:
        max_ws = HdfResultsMesh.get_mesh_max_ws(plan_hdf, "2D Area")
        max_ws.to_file(f"{plan_name}_max_ws.shp")
```

### 10.2 Project-Wide Summary

```python
from ras_commander import HdfProject

# Generate summary for all plans in project
summary = HdfProject.generate_project_summary(project_dir)
print(summary)

# Extract all results
all_results = HdfProject.extract_all_results(project_dir)
print(f"Extracted {len(all_results)} plans")
```
