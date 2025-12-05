# HDF Modules

Classes for reading and processing HEC-RAS HDF result files.

## Core Classes

### HdfBase

Base functionality for HDF file operations.

- `get_dataset_info(hdf_path, group_path=None)` - Print HDF structure
- `get_attrs(hdf_path, path)` - Get attributes at path
- `get_projection(hdf_path)` - Get coordinate system
- `parse_ras_datetime(datetime_str)` - Parse HEC-RAS datetime string
- `parse_ras_datetime_ms(datetime_bytes)` - Parse datetime with milliseconds

### HdfPlan

Plan-level information from HDF files.

- `get_plan_info(hdf_path)` - Get plan metadata
- `get_simulation_times(hdf_path)` - Get start/end times
- `get_plan_parameters(hdf_path)` - Get computation parameters

## Mesh Operations

### HdfMesh

Mesh geometry data.

- `get_mesh_area_names(hdf_path)` - List 2D flow areas
- `get_mesh_cell_polygons(hdf_path)` - Get cell polygons as GeoDataFrame
- `get_mesh_cell_faces(hdf_path)` - Get cell face lines
- `get_mesh_cell_points(hdf_path)` - Get cell center points
- `get_mesh_perimeter(hdf_path)` - Get mesh perimeter polygon
- `get_mesh_cell_count(hdf_path)` - Get number of cells
- `get_nearest_cell(hdf_path, point)` - Find nearest cell to point
- `get_nearest_face(hdf_path, point)` - Find nearest face to point

### HdfResultsMesh

2D mesh results.

- `get_mesh_max_ws(hdf_path)` - Maximum water surface elevation
- `get_mesh_max_ws_time(hdf_path)` - Time of maximum WSE
- `get_mesh_max_depth(hdf_path)` - Maximum depth
- `get_mesh_max_face_v(hdf_path)` - Maximum face velocity
- `get_mesh_timeseries(hdf_path, mesh, var)` - Time series for mesh
- `get_mesh_cells_timeseries(hdf_path, mesh, cell_ids, var)` - Cell time series
- `get_mesh_faces_timeseries(hdf_path, mesh, face_ids, var)` - Face time series

## Plan Results

### HdfResultsPlan

Plan-level results.

- `get_runtime_data(hdf_path)` - Runtime statistics
- `get_volume_accounting(hdf_path)` - Volume accounting data
- `get_compute_messages(hdf_path)` - Computation messages
- `get_compute_options(hdf_path)` - Computation options used
- `is_steady_plan(hdf_path)` - Check if steady state
- `get_steady_profile_names(hdf_path)` - Get steady profile names
- `get_steady_wse(hdf_path)` - Get steady water surface elevations
- `get_steady_info(hdf_path)` - Get steady flow metadata

### HdfResultsXsec

1D cross-section results.

- `get_xsec_timeseries(hdf_path)` - All cross-section time series
- `get_xsec_summary(hdf_path)` - Cross-section summary data

## 1D Geometry

### HdfXsec

Cross-section and river geometry extraction from HDF.

- `get_cross_sections(hdf_path)` - Extract cross-section geometries as GeoDataFrame
- `get_river_centerlines(hdf_path)` - Extract river centerlines
- `get_river_stationing(hdf_path)` - Calculate river stationing along centerlines
- `get_river_reaches(hdf_path)` - Return model 1D river reach lines
- `get_river_edge_lines(hdf_path)` - Return river edge lines
- `get_river_bank_lines(hdf_path)` - Extract river bank lines

## Structure Data

### HdfStruc

Structure geometry and SA/2D connections.

- `get_connection_list(hdf_path)` - List SA/2D connections
- `get_connection_profile(hdf_path, name)` - Get connection profile
- `get_connection_gates(hdf_path, name)` - Get gate data

### HdfResultsBreach

Dam breach results.

- `get_breach_timeseries(hdf_path, structure)` - Breach time series
- `get_breach_summary(hdf_path, structure)` - Breach summary statistics
- `get_breaching_variables(hdf_path, structure)` - Breach geometry evolution
- `get_structure_variables(hdf_path, structure)` - Structure flow variables

### HdfHydraulicTables

Cross section property tables (HTAB).

- `get_xs_htab(hdf_path, river, reach, station)` - Get HTAB data

## Infrastructure

### HdfPipe

Pipe network analysis.

- `get_pipe_conduits(hdf_path)` - Get conduit geometry
- `get_pipe_nodes(hdf_path)` - Get node locations
- `get_pipe_network_timeseries(hdf_path, var)` - Network time series
- `get_pipe_network_summary(hdf_path)` - Network summary
- `get_pipe_profile(hdf_path, conduit_id)` - Get conduit profile

### HdfPump

Pump station analysis.

- `get_pump_stations(hdf_path)` - Get station locations
- `get_pump_groups(hdf_path)` - Get pump groups
- `get_pump_station_timeseries(hdf_path, name)` - Station time series
- `get_pump_station_summary(hdf_path)` - Station summary
- `get_pump_operation_timeseries(hdf_path, name)` - Operation history

## Analysis

### HdfFluvialPluvial

Fluvial-pluvial boundary analysis.

- `calculate_fluvial_pluvial_boundary(hdf_path, delta_t)` - Calculate boundary

### HdfInfiltration

Infiltration parameter management from HDF geometry files.

**Geometry File Operations:**

- `get_infiltration_baseoverrides(hdf_path)` - Retrieve infiltration parameters from geometry HDF
- `set_infiltration_baseoverrides(hdf_path, data)` - Set infiltration parameters

**Raster and Layer Operations:**

- `get_infiltration_layer_data(hdf_path)` - Get infiltration layer data from HDF
- `get_infiltration_map(hdf_path)` - Read infiltration raster map
- `calculate_soil_statistics(hdf_path)` - Process zonal statistics for soil analysis

**Soil Analysis:**

- `get_significant_mukeys(hdf_path, threshold)` - Identify mukeys above percentage threshold
- `calculate_total_significant_percentage(hdf_path)` - Compute total coverage
- `get_infiltration_parameters(hdf_path, mukey)` - Get parameters for specific mukey
- `calculate_weighted_parameters(hdf_path)` - Compute weighted average parameters

**Data Export:**

- `save_statistics(data, path)` - Export soil statistics to CSV

### HdfBndry

Boundary condition geometry.

- `get_bc_lines(hdf_path)` - Get BC lines
- `get_breaklines(hdf_path)` - Get breaklines

## Utilities

### HdfUtils

Utility class for HDF file operations.

**Data Conversion:**

- `convert_ras_string(value)` - Convert RAS HDF strings to Python objects
- `convert_ras_hdf_value(value)` - Convert general HDF values to Python objects
- `convert_df_datetimes_to_str(df)` - Convert DataFrame datetime columns to strings
- `convert_hdf5_attrs_to_dict(attrs)` - Convert HDF5 attributes to dictionary
- `convert_timesteps_to_datetimes(timesteps)` - Convert timesteps to datetime objects

**Spatial Operations:**

- `perform_kdtree_query(source, target)` - KDTree search between datasets
- `find_nearest_neighbors(data, k)` - Find nearest neighbors within dataset

**DateTime Parsing:**

- `parse_ras_datetime(datetime_str)` - Parse RAS datetime (ddMMMYYYY HH:MM:SS)
- `parse_ras_window_datetime(datetime_str)` - Parse simulation window datetime
- `parse_duration(duration_str)` - Parse duration strings (HH:MM:SS)
- `parse_ras_datetime_ms(datetime_bytes)` - Parse datetime with milliseconds
- `parse_run_time_window(window_str)` - Parse time window strings

## Visualization

### HdfPlot & HdfResultsPlot

Basic plotting utilities.

- `plot_results_max_wsel(gdf)` - Plot maximum WSE map

## Usage Example

```python
from ras_commander import HdfResultsMesh, HdfResultsPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get HDF path
hdf_path = ras.plan_df.loc[ras.plan_df['plan_number'] == '01', 'hdf_path'].iloc[0]

# Extract max WSE
max_wse = HdfResultsMesh.get_mesh_max_ws(hdf_path)

# Get runtime stats
runtime = HdfResultsPlan.get_runtime_data(hdf_path)
```
