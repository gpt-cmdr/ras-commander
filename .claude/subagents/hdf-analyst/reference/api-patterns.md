# HDF API Patterns

Complete API reference for all 19 classes in the `ras_commander.hdf` subpackage.

## Input Normalization Pattern

All HDF methods use the `@standardize_input` decorator for flexible input handling:

```python
@standardize_input(file_type='plan_hdf')  # or 'geom_hdf'
def method(hdf_path: Path) -> ReturnType:
    """Method accepts multiple input types."""
```

**Accepted input types**:
1. **Plan number** (string): `"01"`, `"02"` - Resolved via global `ras` object
2. **File path** (string or Path): `"plan.p01.hdf"`, `Path("plan.p01.hdf")`
3. **h5py.File object**: Open file handle for batch operations

**File type validation**:
- `file_type='plan_hdf'` - Expects `.p##.hdf` extension
- `file_type='geom_hdf'` - Expects `.g##.hdf` extension

## Core Classes (3)

### HdfBase
Foundation class providing common HDF operations.

**Methods** (8):
- `get_hdf_file_type(hdf_path)` → `str` - Identify file type (plan/geom)
- `validate_hdf_path(hdf_path, expected_type)` → `Path` - Validate file exists and type
- `get_hdf_attributes(hdf_path, group_path)` → `dict` - Extract attributes from group
- `read_hdf_dataset(hdf_path, dataset_path)` → `np.ndarray` - Read dataset
- `check_group_exists(hdf_path, group_path)` → `bool` - Check if group exists
- `list_group_contents(hdf_path, group_path)` → `List[str]` - List datasets in group

**Return Types**: Path, dict, np.ndarray, bool, List[str]

### HdfUtils
Utility functions for data conversion and parsing.

**Methods** (15):
- `parse_ras_datetime(datetime_str)` → `datetime` - Parse HEC-RAS datetime format
- `convert_ras_time_to_hours(time_str)` → `float` - Convert time string to hours
- `decode_bytes(value)` → `str` - Decode byte strings from HDF
- `get_units(hdf_file, dataset_path)` → `str` - Extract units attribute
- `apply_units_conversion(data, from_units, to_units)` → `np.ndarray` - Unit conversion

**Return Types**: datetime, float, str, np.ndarray

### HdfPlan
Extract plan file metadata and parameters.

**Methods** (7):
- `get_plan_info(hdf_path)` → `pd.DataFrame` - Plan metadata
- `get_plan_parameters(hdf_path)` → `dict` - Plan parameters
- `get_simulation_times(hdf_path)` → `dict` - Start/end times
- `get_computation_interval(hdf_path)` → `str` - Time step interval

**Return Types**: pd.DataFrame, dict, str

## Geometry Classes (5)

### HdfMesh
2D mesh geometry and spatial operations.

**Methods** (17):

**Basic Geometry**:
- `get_mesh_area_names(hdf_path)` → `List[str]` - List 2D area names
- `get_mesh_areas(hdf_path)` → `GeoDataFrame` - Mesh perimeter polygons
- `get_mesh_cell_polygons(hdf_path, mesh_name=None)` → `GeoDataFrame` - Cell polygons
- `get_mesh_cell_points(hdf_path, mesh_name=None)` → `GeoDataFrame` - Cell center points
- `get_mesh_cell_faces(hdf_path, mesh_name=None)` → `GeoDataFrame` - Face linestrings
- `get_mesh_area_attributes(hdf_path)` → `pd.DataFrame` - 2D area attributes

**Property Tables**:
- `get_mesh_face_property_tables(hdf_path, mesh_name)` → `pd.DataFrame` - Face properties
- `get_mesh_cell_property_tables(hdf_path, mesh_name)` → `pd.DataFrame` - Cell properties

**Spatial Queries**:
- `find_nearest_cell(hdf_path, point, mesh_name)` → `dict` - Nearest cell to point
- `find_nearest_face(hdf_path, point, mesh_name)` → `dict` - Nearest face to point
- `get_faces_along_profile_line(hdf_path, linestring, mesh_name)` → `List[int]` - Faces crossing line
- `combine_faces_to_linestring(hdf_path, face_ids, mesh_name)` → `LineString` - Merge faces

**Topology**:
- `get_mesh_sloped_topology(hdf_path, mesh_name)` → `pd.DataFrame` - Slope topology

**Return Types**: GeoDataFrame (with CRS), pd.DataFrame, List[str], dict, LineString

**GeoDataFrame Schema**:
```
Columns: ['cell_id', 'geometry'] or ['face_id', 'geometry']
CRS: Inherited from HEC-RAS project (EPSG from projection info)
Geometry: Polygon (cells) or LineString (faces)
```

### HdfXsec
Cross section geometry extraction.

**Methods** (7):
- `get_cross_section_info(hdf_path)` → `pd.DataFrame` - XS metadata (river, reach, RS)
- `get_cross_section_geometry(hdf_path, river, reach, rs)` → `pd.DataFrame` - Station-elevation
- `get_cross_section_points(hdf_path)` → `GeoDataFrame` - XS point locations
- `get_cross_section_lines(hdf_path)` → `GeoDataFrame` - XS cut lines
- `get_mannings_n(hdf_path, river, reach, rs)` → `pd.DataFrame` - Manning's n values

**Return Types**: pd.DataFrame, GeoDataFrame

**DataFrame Schema (get_cross_section_geometry)**:
```
Columns: ['station', 'elevation', 'mannings_n']
Index: Integer station points
```

### HdfBndry
Boundary features (BC lines, breaklines, reference features).

**Methods** (5):
- `get_bc_lines(hdf_path)` → `GeoDataFrame` - Boundary condition lines
- `get_breaklines(hdf_path, mesh_name)` → `GeoDataFrame` - Internal breaklines
- `get_reference_lines(hdf_path)` → `GeoDataFrame` - Reference output lines
- `get_reference_points(hdf_path)` → `GeoDataFrame` - Reference output points

**Return Types**: GeoDataFrame

### HdfStruc
2D structure geometry.

**Methods** (4):
- `get_2d_structures(hdf_path, mesh_name)` → `GeoDataFrame` - 2D structure locations
- `get_sa_2d_connections(hdf_path)` → `GeoDataFrame` - SA/2D area connections
- `get_structure_attributes(hdf_path, structure_name)` → `dict` - Structure metadata

**Return Types**: GeoDataFrame, dict

### HdfHydraulicTables
Extract hydraulic property tables (HTAB) from preprocessed geometry.

**Methods** (4):
- `get_xs_htab(hdf_path, river, reach, rs)` → `pd.DataFrame` - Cross section HTAB
- `get_bridge_htab(hdf_path, river, reach, rs)` → `pd.DataFrame` - Bridge HTAB
- `get_culvert_htab(hdf_path, river, reach, rs)` → `pd.DataFrame` - Culvert HTAB

**Return Types**: pd.DataFrame

**DataFrame Schema (get_xs_htab)**:
```
Columns: ['elevation', 'area', 'wetted_perimeter', 'conveyance']
Index: Elevation points (float)
Units: area (ft²/m²), perimeter (ft/m), conveyance (depends on unit system)
```

## Results Classes (4)

### HdfResultsPlan
Plan-level results (steady and unsteady).

**Methods** (13):

**Steady Flow**:
- `is_steady_plan(hdf_path)` → `bool` - Check if plan has steady results
- `get_steady_profile_names(hdf_path)` → `List[str]` - Profile names
- `get_steady_wse(hdf_path, profile=None)` → `pd.DataFrame` - Water surface elevations
- `get_steady_info(hdf_path)` → `pd.DataFrame` - Steady flow metadata
- `get_steady_results(hdf_path, variable, profile)` → `pd.DataFrame` - Any steady variable
- `list_steady_variables(hdf_path)` → `List[str]` - Available steady variables

**Unsteady Flow**:
- `get_unsteady_info(hdf_path)` → `pd.DataFrame` - Unsteady attributes
- `get_unsteady_summary(hdf_path)` → `pd.DataFrame` - Unsteady summary data
- `get_volume_accounting(hdf_path)` → `pd.DataFrame` - Volume accounting
- `get_runtime_data(hdf_path)` → `pd.DataFrame` - Runtime and compute time

**Reference Features**:
- `get_reference_timeseries(hdf_path, reftype)` → `pd.DataFrame` - Reference line/point time series
- `get_reference_summary(hdf_path, reftype)` → `pd.DataFrame` - Reference summary

**Messages**:
- `get_compute_messages(hdf_path)` → `str` - Computation messages (HDF or .txt fallback)

**Return Types**: bool, List[str], pd.DataFrame, str

**DataFrame Schema (get_steady_wse)**:
```
Index: Cross section identifiers (river-reach-RS)
Columns: Profile names
Values: Water surface elevation (float)
```

### HdfResultsMesh
2D mesh results and time series.

**Methods** (19):

**Time Series**:
- `get_mesh_timeseries(hdf_path, variable, mesh_name)` → `xr.DataArray` - Complete time series
- `get_mesh_cells_timeseries(hdf_path, variable, mesh_name, cell_ids)` → `pd.DataFrame` - Specific cells
- `get_mesh_faces_timeseries(hdf_path, variable, mesh_name, face_ids)` → `pd.DataFrame` - Specific faces

**Envelopes (Maximum/Minimum)**:
- `get_mesh_max_ws(hdf_path, mesh_name)` → `GeoDataFrame` - Maximum water surface
- `get_mesh_min_ws(hdf_path, mesh_name)` → `GeoDataFrame` - Minimum water surface
- `get_mesh_max_face_v(hdf_path, mesh_name)` → `GeoDataFrame` - Maximum velocity
- `get_mesh_min_face_v(hdf_path, mesh_name)` → `GeoDataFrame` - Minimum velocity
- `get_mesh_max_ws_err(hdf_path, mesh_name)` → `GeoDataFrame` - Maximum WS error
- `get_mesh_max_iter(hdf_path, mesh_name)` → `GeoDataFrame` - Maximum iterations

**Summary**:
- `get_mesh_summary(hdf_path, mesh_name)` → `pd.DataFrame` - Summary statistics
- `get_mesh_last_iter(hdf_path, mesh_name)` → `GeoDataFrame` - Last iteration data

**Boundary Conditions**:
- `get_boundary_conditions_timeseries(hdf_path, bc_name)` → `pd.DataFrame` - BC time series

**Return Types**: xr.DataArray, pd.DataFrame, GeoDataFrame

**xr.DataArray Schema (get_mesh_timeseries)**:
```
Dimensions: (time, cell_id) or (time, face_id)
Coordinates: time (datetime64), cell_id/face_id (int)
Attributes: units, mesh_name, variable_name
```

### HdfResultsXsec
Cross section results.

**Methods** (4):
- `get_xs_timeseries(hdf_path, variable, river, reach, rs)` → `pd.DataFrame` - XS time series
- `get_xs_summary(hdf_path, river, reach, rs)` → `pd.DataFrame` - XS summary statistics

**Return Types**: pd.DataFrame

### HdfResultsBreach
Dam breach results extraction.

**Methods** (4):
- `get_breach_timeseries(hdf_path, structure_name)` → `pd.DataFrame` - Complete breach time series
- `get_breach_summary(hdf_path)` → `pd.DataFrame` - Summary of all breaches
- `get_breaching_variables(hdf_path, structure_name)` → `pd.DataFrame` - Breach geometry evolution
- `get_structure_variables(hdf_path, structure_name)` → `pd.DataFrame` - Structure flow variables

**Return Types**: pd.DataFrame

**DataFrame Schema (get_breach_timeseries)**:
```
Index: datetime (time of breach event)
Columns: ['flow', 'stage', 'breach_width', 'breach_depth', 'breach_area']
Units: flow (cfs/cms), stage (ft/m), width (ft/m), depth (ft/m), area (ft²/m²)
```

## Infrastructure Classes (3)

### HdfPipe
Pipe network geometry and results.

**Methods** (8):
- `get_pipe_geometry(hdf_path)` → `GeoDataFrame` - Pipe network geometry
- `get_pipe_timeseries(hdf_path, pipe_id, variable)` → `pd.DataFrame` - Pipe flow time series
- `get_pipe_summary(hdf_path)` → `pd.DataFrame` - Pipe summary statistics

**Return Types**: GeoDataFrame, pd.DataFrame

### HdfPump
Pump station geometry and results.

**Methods** (5):
- `get_pump_geometry(hdf_path)` → `GeoDataFrame` - Pump station locations
- `get_pump_timeseries(hdf_path, pump_id, variable)` → `pd.DataFrame` - Pump flow time series
- `get_pump_summary(hdf_path)` → `pd.DataFrame` - Pump summary statistics

**Return Types**: GeoDataFrame, pd.DataFrame

### HdfInfiltration
Infiltration parameters and results.

**Methods** (18):
- `get_infiltration_parameters(hdf_path, mesh_name)` → `pd.DataFrame` - Infiltration settings
- `get_cell_infiltration_timeseries(hdf_path, mesh_name, cell_ids)` → `pd.DataFrame` - Cell infiltration

**Return Types**: pd.DataFrame

## Visualization Classes (2)

### HdfPlot
General HDF plotting utilities.

**Methods** (2):
- `plot_mesh(hdf_path, mesh_name, **kwargs)` → `matplotlib.figure.Figure` - Plot mesh
- `plot_results(hdf_path, variable, **kwargs)` → `matplotlib.figure.Figure` - Plot results

**Return Types**: matplotlib.figure.Figure

### HdfResultsPlot
Results-specific visualization.

**Methods** (3):
- `plot_timeseries(data, **kwargs)` → `matplotlib.figure.Figure` - Time series plot
- `plot_spatial_results(gdf, variable, **kwargs)` → `matplotlib.figure.Figure` - Spatial map
- `plot_profile(xs_data, **kwargs)` → `matplotlib.figure.Figure` - Profile plot

**Return Types**: matplotlib.figure.Figure

## Analysis Classes (1)

### HdfFluvialPluvial
Fluvial-pluvial boundary analysis.

**Methods** (6):
- `delineate_fluvial_pluvial(hdf_path, mesh_name, threshold)` → `GeoDataFrame` - Source attribution
- `calculate_contributing_area(hdf_path, mesh_name, point)` → `float` - Drainage area

**Return Types**: GeoDataFrame, float

## Project-Level Classes (1)

### HdfProject
Multi-file and project-wide operations.

**Methods** (4):
- `compare_plans(hdf_paths, variable)` → `pd.DataFrame` - Multi-plan comparison
- `extract_all_results(project_dir)` → `dict` - Batch extraction for all plans
- `generate_project_summary(project_dir)` → `pd.DataFrame` - Project-level summary

**Return Types**: pd.DataFrame, dict

## Common Return Type Patterns

### GeoDataFrame
```python
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString

# Standard schema
GeoDataFrame(
    data={'id': [...], 'attribute': [...]},
    geometry=[Polygon(...), Polygon(...)],
    crs="EPSG:XXXX"  # Project CRS
)
```

### pd.DataFrame (Time Series)
```python
import pandas as pd

# Time-indexed DataFrame
pd.DataFrame(
    data={'variable1': [...], 'variable2': [...]},
    index=pd.DatetimeIndex([...])  # datetime64[ns]
)
```

### xr.DataArray (Multi-dimensional)
```python
import xarray as xr

# 2D time series array
xr.DataArray(
    data=np.array(...),  # shape (n_times, n_cells)
    dims=('time', 'cell_id'),
    coords={'time': [...], 'cell_id': [...]},
    attrs={'units': 'ft', 'variable': 'Water Surface'}
)
```

## Error Handling Pattern

All methods follow consistent error handling:

```python
try:
    with h5py.File(hdf_path, 'r') as hdf_file:
        # Read operations
        data = hdf_file["/path/to/dataset"][()]
except KeyError as e:
    logger.error(f"Dataset not found: {e}")
    return pd.DataFrame()  # Empty DataFrame
except Exception as e:
    logger.error(f"Error reading {hdf_path}: {e}")
    return pd.DataFrame()  # Or GeoDataFrame(), {}, [], etc.
```

**Return values on error**:
- DataFrame/GeoDataFrame → Empty with no columns
- dict → Empty dict `{}`
- List → Empty list `[]`
- bool → `False`
- Scalar → `None`
