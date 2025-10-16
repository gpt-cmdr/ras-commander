# RAS Commander API Documentation - HDF Classes

This document provides detailed reference for HDF data extraction and analysis classes in the `ras_commander` library. For HEC-RAS project management and plan execution classes, see [api-ras.md](api-ras.md).

## Overview

The HDF classes provide methods for extracting and analyzing data from HEC-RAS HDF5 files (.hdf), including:
- Geometry data (cross sections, 2D mesh, structures, boundaries)
- Simulation results (water surface, velocity, depth, flow)
- Plan information and metadata

All methods use the `@standardize_input` decorator for flexible file path handling and the `@log_call` decorator for operation logging.

---

## Class: HdfBase

Contains fundamental static methods for interacting with HEC-RAS HDF files. Used by other `Hdf*` classes. Requires an open `h5py.File` object or uses `@standardize_input`.

### `HdfBase.get_simulation_start_time(hdf_file)`

*   **Purpose:** Extracts the simulation start time attribute from the Plan Information group.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
*   **Returns:** (`datetime`): Simulation start time.
*   **Raises:** `ValueError` if path not found or time parsing fails.

### `HdfBase.get_unsteady_timestamps(hdf_file)`

*   **Purpose:** Extracts the list of unsteady output timestamps (usually in milliseconds format) and converts them to datetime objects.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
*   **Returns:** `List[datetime]`: List of datetime objects for each output time step.

### `HdfBase.get_2d_flow_area_names_and_counts(hdf_path)`

*   **Purpose:** Gets the names and cell counts of all 2D Flow Areas defined in the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry HDF).
*   **Returns:** `List[Tuple[str, int]]`: List of tuples `(area_name, cell_count)`.
*   **Raises:** `ValueError` on read errors.

### `HdfBase.get_projection(hdf_path)`

*   **Purpose:** Retrieves the spatial projection information (WKT string) from the HDF file attributes or associated `.rasmap` file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** (`str` or `None`): Well-Known Text (WKT) string of the projection, or `None` if not found.

### `HdfBase.get_attrs(hdf_file, attr_path)`

*   **Purpose:** Retrieves all attributes from a specific group or dataset within the HDF file.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
    *   `attr_path` (`str`): Internal HDF path to the group/dataset (e.g., "Plan Data/Plan Information").
*   **Returns:** `Dict[str, Any]`: Dictionary of attributes. Returns empty dict if path not found.

### `HdfBase.get_dataset_info(file_path, group_path='/')`

*   **Purpose:** Prints a recursive listing of the structure (groups, datasets, attributes, shapes, dtypes) within an HDF5 file, starting from `group_path`.
*   **Parameters:**
    *   `file_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
    *   `group_path` (`str`, optional): Internal HDF path to start exploration from. Default is root ('/').
*   **Returns:** `None`. Prints to console.

### `HdfBase.get_polylines_from_parts(hdf_path, path, info_name="Polyline Info", parts_name="Polyline Parts", points_name="Polyline Points")`

*   **Purpose:** Reconstructs Shapely LineString or MultiLineString geometries from HEC-RAS's standard polyline representation in HDF (using Info, Parts, Points datasets).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
    *   `path` (`str`): Internal HDF base path containing the polyline datasets (e.g., "Geometry/River Centerlines").
    *   `info_name` (`str`, optional): Name of the dataset containing polyline start/count info. Default "Polyline Info".
    *   `parts_name` (`str`, optional): Name of the dataset defining parts for multi-part lines. Default "Polyline Parts".
    *   `points_name` (`str`, optional): Name of the dataset containing all point coordinates. Default "Polyline Points".
*   **Returns:** `List[LineString or MultiLineString]`: List of reconstructed Shapely geometries.

### `HdfBase.print_attrs(name, obj)`

*   **Purpose:** Helper method to print the attributes of an HDF5 object (Group or Dataset) during exploration (used by `get_dataset_info`).
*   **Parameters:**
    *   `name` (`str`): Name of the HDF5 object.
    *   `obj` (`h5py.Group` or `h5py.Dataset`): The HDF5 object.
*   **Returns:** `None`. Prints to console.

---

## Class: HdfBndry

Contains static methods for extracting boundary-related *geometry* features (BC Lines, Breaklines, Refinement Regions, Reference Lines/Points) from HEC-RAS HDF files (typically geometry HDF). Returns GeoDataFrames.

### `HdfBndry.get_bc_lines(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Boundary Condition Lines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes (Name, SA-2D, Type, etc.).

### `HdfBndry.get_breaklines(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Break Lines. Skips invalid (zero-length, single-point) breaklines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString/MultiLineString geometries and attributes (bl_id, Name).

### `HdfBndry.get_refinement_regions(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Refinement Regions.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon/MultiPolygon geometries and attributes (rr_id, Name).

### `HdfBndry.get_reference_lines(hdf_path, mesh_name=None)`

*   **Purpose:** Extracts Reference Lines used for profile output, optionally filtering by mesh name.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
    *   `mesh_name` (`str`, optional): Filter results to this specific mesh area.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString/MultiLineString geometries and attributes (refln_id, Name, mesh_name, Type).

### `HdfBndry.get_reference_points(hdf_path, mesh_name=None)`

*   **Purpose:** Extracts Reference Points used for point output, optionally filtering by mesh name.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
    *   `mesh_name` (`str`, optional): Filter results to this specific mesh area.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes (refpt_id, Name, mesh_name, Cell Index).

---

## Class: HdfFluvialPluvial

Contains static methods for analyzing fluvial-pluvial boundaries based on simulation results.

### `HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf_path, delta_t=12, min_line_length=None)`

*   **Purpose:** Calculates the boundary line between areas dominated by fluvial (riverine) vs. pluvial (rainfall/local) flooding, based on the timing difference of maximum water surface elevation between adjacent 2D cells. Attempts to join adjacent boundary segments.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF file.
    *   `delta_t` (`float`, optional): Time difference threshold in hours. Adjacent cells with max WSE time differences greater than this are considered part of the boundary. Default is 12.
    *   `min_line_length` (`float`, optional): Minimum length (in CRS units) for boundary lines to be included. Lines shorter than this will be dropped. Default is None (no filtering).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing LineString geometries representing the calculated boundary. CRS matches the input HDF.
*   **Raises:** `ValueError` if required mesh or results data is missing.

### `HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf_path, delta_t=12, temporal_tolerance_hours=1.0, min_polygon_area_acres=None)`

*   **Purpose:** Generates dissolved polygons representing fluvial, pluvial, and ambiguous flood zones. Classifies each wetted cell using iterative region growth based on maximum water surface elevation timing, then merges cells into three distinct regions: 'fluvial', 'pluvial', and 'ambiguous'.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF file.
    *   `delta_t` (`float`, optional): The time difference (in hours) between adjacent cells that defines the initial boundary between fluvial and pluvial zones. Default is 12.
    *   `temporal_tolerance_hours` (`float`, optional): The maximum time difference (in hours) for a cell to be considered part of an expanding region during iterative growth. Default is 1.0.
    *   `min_polygon_area_acres` (`float`, optional): Minimum polygon area (in acres). For fluvial or pluvial polygons smaller than this threshold, they are reclassified to the opposite type and merged with adjacent polygons. Ambiguous polygons are not affected. Default is None (no filtering).
*   **Returns:** `gpd.GeoDataFrame`: A GeoDataFrame with dissolved polygons for 'fluvial', 'pluvial', and 'ambiguous' zones. CRS matches the input HDF.
*   **Raises:** `ValueError` if required mesh or results data is missing.
*   **Notes:** 
    - Uses iterative region growth algorithm to expand from initial boundary seeds
    - Handles conflicts by marking cells as 'ambiguous' when both fluvial and pluvial regions compete for the same cell
    - Area-based filtering requires projected CRS; geographic CRS will skip this step with a warning

---

## Class: HdfInfiltration

Contains static methods for handling infiltration data within HEC-RAS HDF files (typically geometry HDF).

### `HdfInfiltration.get_infiltration_baseoverrides(hdf_path: Path) -> Optional[pd.DataFrame]`

*   **Purpose:** Retrieves current infiltration parameters from a HEC-RAS geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Optional[pd.DataFrame]`: DataFrame containing infiltration parameters if successful, None if operation fails.

### `HdfInfiltration.get_infiltration_layer_data(hdf_path: Path) -> Optional[pd.DataFrame]`

*   **Purpose:** Retrieves current infiltration parameters from a HEC-RAS infiltration layer HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the infiltration layer HDF.
*   **Returns:** `Optional[pd.DataFrame]`: DataFrame containing infiltration parameters if successful, None if operation fails.

### `HdfInfiltration.set_infiltration_layer_data(hdf_path: Path, infiltration_df: pd.DataFrame) -> Optional[pd.DataFrame]`

*   **Purpose:** Sets infiltration layer data in the infiltration layer HDF file directly from the provided DataFrame.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the infiltration layer HDF.
    *   `infiltration_df` (`pd.DataFrame`): DataFrame containing infiltration parameters.
*   **Returns:** `Optional[pd.DataFrame]`: The infiltration DataFrame if successful, None if operation fails.

### `HdfInfiltration.scale_infiltration_data(hdf_path: Path, infiltration_df: pd.DataFrame, scale_factors: Dict[str, float]) -> Optional[pd.DataFrame]`

*   **Purpose:** Updates infiltration parameters in the HDF file with scaling factors.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `infiltration_df` (`pd.DataFrame`): DataFrame containing infiltration parameters.
    *   `scale_factors` (`Dict[str, float]`): Dictionary mapping column names to their scaling factors.
*   **Returns:** `Optional[pd.DataFrame]`: The updated infiltration DataFrame if successful, None if operation fails.

### `HdfInfiltration.get_infiltration_map(hdf_path: Path = None, ras_object: Any = None) -> dict`

*   **Purpose:** Reads the infiltration raster map from HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `dict`: Dictionary mapping raster values to mukeys.

### `HdfInfiltration.calculate_soil_statistics(zonal_stats: list, raster_map: dict) -> pd.DataFrame`

*   **Purpose:** Calculates soil statistics from zonal statistics.
*   **Parameters:**
    *   `zonal_stats` (`list`): List of zonal statistics.
    *   `raster_map` (`dict`): Dictionary mapping raster values to mukeys.
*   **Returns:** `pd.DataFrame`: DataFrame with soil statistics including percentages and areas.

### `HdfInfiltration.get_significant_mukeys(soil_stats: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame`

*   **Purpose:** Gets mukeys with percentage greater than threshold.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `threshold` (`float`, optional): Minimum percentage threshold. Default 1.0.
*   **Returns:** `pd.DataFrame`: DataFrame with significant mukeys and their statistics.

### `HdfInfiltration.calculate_total_significant_percentage(significant_mukeys: pd.DataFrame) -> float`

*   **Purpose:** Calculates total percentage covered by significant mukeys.
*   **Parameters:**
    *   `significant_mukeys` (`pd.DataFrame`): DataFrame of significant mukeys.
*   **Returns:** `float`: Total percentage covered by significant mukeys.

### `HdfInfiltration.save_statistics(soil_stats: pd.DataFrame, output_path: Path, include_timestamp: bool = True)`

*   **Purpose:** Saves soil statistics to CSV.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `output_path` (`Path`): Path to save CSV file.
    *   `include_timestamp` (`bool`, optional): Whether to include timestamp in filename. Default True.
*   **Returns:** None

### `HdfInfiltration.get_infiltration_parameters(hdf_path: Path = None, mukey: str = None, ras_object: Any = None) -> dict`

*   **Purpose:** Gets infiltration parameters for a specific mukey from HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df.
    *   `mukey` (`str`): Mukey identifier.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `dict`: Dictionary of infiltration parameters.

### `HdfInfiltration.calculate_weighted_parameters(soil_stats: pd.DataFrame, infiltration_params: dict) -> dict`

*   **Purpose:** Calculates weighted infiltration parameters based on soil statistics.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `infiltration_params` (`dict`): Dictionary of infiltration parameters by mukey.
*   **Returns:** `dict`: Dictionary of weighted average infiltration parameters.

---

## Class: HdfMesh

Contains static methods for extracting 2D mesh geometry information from HEC-RAS HDF files (typically geometry or plan HDF).

### `HdfMesh.get_mesh_area_names(hdf_path)`

*   **Purpose:** Retrieves the names of all 2D Flow Areas defined in the HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `List[str]`: List of 2D Flow Area names.

### `HdfMesh.get_mesh_areas(hdf_path)`

*   **Purpose:** Extracts the outer perimeter polygons for each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon geometries and 'mesh_name' attribute.

### `HdfMesh.get_mesh_cell_polygons(hdf_path)`

*   **Purpose:** Reconstructs the individual cell polygons for all 2D Flow Areas by assembling cell faces.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon geometries and attributes 'mesh_name', 'cell_id'.

### `HdfMesh.get_mesh_cell_points(hdf_path)`

*   **Purpose:** Extracts the center point coordinates for each cell in all 2D Flow Areas.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes 'mesh_name', 'cell_id'.

### `HdfMesh.get_mesh_cell_faces(hdf_path)`

*   **Purpose:** Extracts the face line segments that form the boundaries of the mesh cells.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes 'mesh_name', 'face_id'.

### `HdfMesh.get_mesh_area_attributes(hdf_path)`

*   **Purpose:** Retrieves the main attributes associated with the 2D Flow Areas group in the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the attributes (e.g., Manning's n values).

### `HdfMesh.get_mesh_face_property_tables(hdf_path)`

*   **Purpose:** Extracts the detailed hydraulic property tables (Elevation vs. Area, Wetted Perimeter, Roughness) associated with each *face* in each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Dict[str, pd.DataFrame]`: Dictionary mapping mesh names to DataFrames. Each DataFrame contains columns ['Face ID', 'Z', 'Area', 'Wetted Perimeter', "Manning's n"].

### `HdfMesh.get_mesh_cell_property_tables(hdf_path)`

*   **Purpose:** Extracts the detailed hydraulic property tables (Elevation vs. Volume, Surface Area) associated with each *cell* in each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Dict[str, pd.DataFrame]`: Dictionary mapping mesh names to DataFrames. Each DataFrame contains columns ['Cell ID', 'Z', 'Volume', 'Surface Area'].

---

## Class: HdfPipe

Contains static methods for handling pipe network geometry and results data from HEC-RAS HDF files.

### `HdfPipe.get_pipe_conduits(hdf_path, crs="EPSG:4326")`

*   **Purpose:** Extracts pipe conduit centerlines, attributes, and terrain profiles from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `crs` (`str`, optional): Coordinate Reference System string. Default "EPSG:4326".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries ('Polyline'), attributes, and 'Terrain_Profiles' (list of (station, elevation) tuples).

### `HdfPipe.get_pipe_nodes(hdf_path)`

*   **Purpose:** Extracts pipe node locations and attributes from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes.

### `HdfPipe.get_pipe_network(hdf_path, pipe_network_name=None, crs="EPSG:4326")`

*   **Purpose:** Extracts the detailed geometry of a specific pipe network, including cell polygons, faces, nodes, and connectivity information from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `pipe_network_name` (`str`, optional): Name of the network. If `None`, uses the first network found.
    *   `crs` (`str`, optional): Coordinate Reference System string. Default "EPSG:4326".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame primarily representing cells (Polygon geometry), with related face and node info included as attributes or object columns.
*   **Raises:** `ValueError` if `pipe_network_name` not found.

### `HdfPipe.get_pipe_profile(hdf_path, conduit_id)`

*   **Purpose:** Extracts the station-elevation terrain profile data for a specific pipe conduit from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `conduit_id` (`int`): Zero-based index of the conduit.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Station', 'Elevation'].
*   **Raises:** `KeyError`, `IndexError`.

### `HdfPipe.get_pipe_network_timeseries(hdf_path, variable)`

*   **Purpose:** Extracts time series results for a specified variable across all elements (cells, faces, pipes, nodes) of a pipe network.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `variable` (`str`): The results variable name (e.g., "Cell Water Surface", "Pipes/Pipe Flow DS", "Nodes/Depth").
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'location') containing the time series values. Includes units attribute.
*   **Raises:** `ValueError` for invalid variable name, `KeyError`.

### `HdfPipe.get_pipe_network_summary(hdf_path)`

*   **Purpose:** Extracts summary statistics (min/max values, timing) for pipe network results from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the summary statistics. Returns empty DataFrame if data not found.
*   **Raises:** `KeyError`.

### `HdfPipe.extract_timeseries_for_node(plan_hdf_path, node_id)`

*   **Purpose:** Extracts time series data specifically for a single pipe node (Depth, Drop Inlet Flow, Water Surface).
*   **Parameters:**
    *   `plan_hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `node_id` (`int`): Zero-based index of the node.
*   **Returns:** `Dict[str, xr.DataArray]`: Dictionary mapping variable names to their respective DataArrays (time dimension only).

### `HdfPipe.extract_timeseries_for_conduit(plan_hdf_path, conduit_id)`

*   **Purpose:** Extracts time series data specifically for a single pipe conduit (Flow US/DS, Velocity US/DS).
*   **Parameters:**
    *   `plan_hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `conduit_id` (`int`): Zero-based index of the conduit.
*   **Returns:** `Dict[str, xr.DataArray]`: Dictionary mapping variable names to their respective DataArrays (time dimension only).

---

## Class: HdfPlan

Contains static methods for extracting general plan-level information and attributes from HEC-RAS HDF files (plan or geometry HDF).

### `HdfPlan.get_plan_start_time(hdf_path)`

*   **Purpose:** Gets the simulation start time from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** (`datetime`): Simulation start time.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_end_time(hdf_path)`

*   **Purpose:** Gets the simulation end time from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** (`datetime`): Simulation end time.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_timestamps_list(hdf_path)`

*   **Purpose:** Gets the list of simulation output timestamps from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `List[datetime]`: List of output datetime objects.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_information(hdf_path)`

*   **Purpose:** Extracts all attributes from the 'Plan Data/Plan Information' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `Dict[str, Any]`: Dictionary of plan information attributes.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_parameters(hdf_path)`

*   **Purpose:** Extracts all attributes from the 'Plan Data/Plan Parameters' group in the plan HDF file and returns them as a DataFrame. Includes the plan number extracted from the filename.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Plan', 'Parameter', 'Value'].
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_met_precip(hdf_path)`

*   **Purpose:** Extracts precipitation attributes from the 'Event Conditions/Meteorology/Precipitation' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `Dict[str, Any]`: Dictionary of precipitation attributes. Returns empty dict if not found.

### `HdfPlan.get_geometry_information(hdf_path)`

*   **Purpose:** Extracts root-level attributes (like Version, Units, Projection) from the 'Geometry' group in a geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Value'] and index ['Attribute Name'].
*   **Raises:** `ValueError`.

---

## Class: HdfPlot

Contains static methods for creating basic plots from HEC-RAS HDF data using `matplotlib`.

### `HdfPlot.plot_mesh_cells(cell_polygons_df, projection, title='2D Flow Area Mesh Cells', figsize=(12, 8))`

*   **Purpose:** Plots 2D mesh cell outlines from a GeoDataFrame.
*   **Parameters:**
    *   `cell_polygons_df` (`gpd.GeoDataFrame`): GeoDataFrame containing cell polygons (requires 'geometry' column).
    *   `projection` (`str`): CRS string to assign if `cell_polygons_df` doesn't have one.
    *   `title` (`str`, optional): Plot title. Default '2D Flow Area Mesh Cells'.
    *   `figsize` (`Tuple[int, int]`, optional): Figure size. Default (12, 8).
*   **Returns:** (`gpd.GeoDataFrame` or `None`): The input GeoDataFrame (with CRS possibly assigned), or `None` if input was empty. Displays the plot.

### `HdfPlot.plot_time_series(df, x_col, y_col, title=None, figsize=(12, 6))`

*   **Purpose:** Creates a simple line plot for time series data from a DataFrame.
*   **Parameters:**
    *   `df` (`pd.DataFrame`): DataFrame containing the data.
    *   `x_col` (`str`): Column name for the x-axis (usually time).
    *   `y_col` (`str`): Column name for the y-axis.
    *   `title` (`str`, optional): Plot title. Default `None`.
    *   `figsize` (`Tuple[int, int]`, optional): Figure size. Default (12, 6).
*   **Returns:** `None`. Displays the plot.

---

## Class: HdfPump

Contains static methods for handling pump station geometry and results data from HEC-RAS HDF files.

### `HdfPump.get_pump_stations(hdf_path)`

*   **Purpose:** Extracts pump station locations and attributes from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes including 'station_id'.
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_groups(hdf_path)`

*   **Purpose:** Extracts pump group attributes and efficiency curve data from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `pd.DataFrame`: DataFrame containing pump group attributes and 'efficiency_curve' data (list of values).
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_station_timeseries(hdf_path, pump_station)`

*   **Purpose:** Extracts time series results (Flow, Stage HW, Stage TW, Pumps On) for a specific pump station from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `pump_station` (`str`): Name of the pump station as defined in HEC-RAS.
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'variable') containing the time series. Includes units attribute.
*   **Raises:** `KeyError`, `ValueError` if pump station not found.

### `HdfPump.get_pump_station_summary(hdf_path)`

*   **Purpose:** Extracts summary statistics (min/max values, volumes, durations) for all pump stations from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the summary statistics. Returns empty DataFrame if data not found.
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_operation_timeseries(hdf_path, pump_station)`

*   **Purpose:** Extracts detailed pump operation time series data (similar to `get_pump_station_timeseries` but often from a different HDF group, potentially DSS Profile Output) for a specific pump station. Returns as a DataFrame.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `pump_station` (`str`): Name of the pump station.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Time', 'Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on'].
*   **Raises:** `KeyError`, `ValueError` if pump station not found.

---

## Class: HdfResultsMesh

Contains static methods for extracting and analyzing 2D mesh *results* data from HEC-RAS plan HDF files.

### `HdfResultsMesh.get_mesh_summary(hdf_path, var, round_to="100ms")`

*   **Purpose:** Extracts summary output (e.g., max/min values and times) for a specific variable across all cells/faces in all 2D areas. Merges with geometry (points for cells, lines for faces).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `var` (`str`): The summary variable name (e.g., "Maximum Water Surface", "Maximum Face Velocity", "Cell Last Iteration").
    *   `round_to` (`str`, optional): Time rounding precision for timestamps. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing the summary results, geometry, and mesh/element IDs.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_timeseries(hdf_path, mesh_name, var, truncate=True)`

*   **Purpose:** Extracts the full time series for a specific variable for all cells or faces within a *single* specified 2D mesh area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_name` (`str`): Name of the 2D Flow Area.
    *   `var` (`str`): Results variable name (e.g., "Water Surface", "Face Velocity", "Depth").
    *   `truncate` (`bool`, optional): If `True`, remove trailing zero-value time steps. Default `True`.
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'cell_id' or 'face_id') containing the time series. Includes units attribute.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_faces_timeseries(hdf_path, mesh_name)`

*   **Purpose:** Extracts time series for all standard *face-based* variables ("Face Velocity", "Face Flow") for a specific mesh area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_name` (`str`): Name of the 2D Flow Area.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each face variable, indexed by time and face_id.

### `HdfResultsMesh.get_mesh_cells_timeseries(hdf_path, mesh_names=None, var=None, truncate=False, ras_object=None)`

*   **Purpose:** Extracts time series for specified (or all) *cell-based* variables for specified (or all) mesh areas.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_names` (`str` or `List[str]`, optional): Name(s) of mesh area(s). If `None`, processes all.
    *   `var` (`str`, optional): Specific variable name. If `None`, retrieves all available cell and face variables.
    *   `truncate` (`bool`, optional): Remove trailing zero time steps. Default `False`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `Dict[str, xr.Dataset]`: Dictionary mapping mesh names to Datasets containing the requested variable(s) as DataArrays, indexed by time and cell_id/face_id.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_last_iter(hdf_path)`

*   **Purpose:** Shortcut to get the summary output for "Cell Last Iteration".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the last iteration count for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_ws(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Maximum Water Surface".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing max WSE and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_min_ws(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Minimum Water Surface".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing min WSE and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_face_v(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Maximum Face Velocity".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing max velocity and time for each face (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_min_face_v(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Minimum Face Velocity".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing min velocity and time for each face (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_ws_err(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Cell Maximum Water Surface Error".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing max WSE error and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_iter(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Cell Last Iteration" (often used as max iteration indicator).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing max iteration count and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)`

*   **Purpose:** Extracts timeseries data for all boundary conditions as a single combined xarray Dataset with stage, flow, and per-face data.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing boundary condition data with dimensions (time, bc_name, face_id) and variables (stage, flow, flow_per_face, stage_per_face).
*   **Raises:** `ValueError`.

---

## Class: HdfResultsPlan

Contains static methods for extracting general plan-level *results* and summary information from HEC-RAS plan HDF files.

### `HdfResultsPlan.get_unsteady_info(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the unsteady results attributes.
*   **Raises:** `FileNotFoundError`, `KeyError`, `RuntimeError`.

### `HdfResultsPlan.get_unsteady_summary(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady/Summary' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the unsteady summary attributes.
*   **Raises:** `FileNotFoundError`, `KeyError`, `RuntimeError`.

### `HdfResultsPlan.get_volume_accounting(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady/Summary/Volume Accounting' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** (`pd.DataFrame` or `None`): Single-row DataFrame containing volume accounting attributes, or `None` if the group doesn't exist.
*   **Raises:** `FileNotFoundError`, `RuntimeError`.

### `HdfResultsPlan.get_runtime_data(hdf_path)`

*   **Purpose:** Extracts detailed computational performance metrics (durations, speeds) for different simulation processes (Geometry, Preprocessing, Unsteady Flow) from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** (`pd.DataFrame` or `None`): Single-row DataFrame containing runtime statistics, or `None` if data is missing or parsing fails.

### `HdfResultsPlan.get_reference_timeseries(hdf_path, reftype)`

*   **Purpose:** Extracts time series results for all Reference Lines or Reference Points from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `reftype` (`str`): Type of reference feature ('lines' or 'points').
*   **Returns:** `pd.DataFrame`: DataFrame containing time series data for the specified reference type. Each column represents a reference feature, indexed by time step. Returns empty DataFrame if data not found.

### `HdfResultsPlan.get_reference_summary(hdf_path, reftype)`

*   **Purpose:** Extracts summary results (e.g., max/min values) for all Reference Lines or Reference Points from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `reftype` (`str`): Type of reference feature ('lines' or 'points').
*   **Returns:** `pd.DataFrame`: DataFrame containing summary data for the specified reference type. Returns empty DataFrame if data not found.

---

## Class: HdfResultsPlot

Contains static methods for plotting specific HEC-RAS *results* data using `matplotlib`.

### `HdfResultsPlot.plot_results_max_wsel(max_ws_df)`

*   **Purpose:** Creates a scatter plot showing the spatial distribution of maximum water surface elevation (WSE) per mesh cell.
*   **Parameters:**
    *   `max_ws_df` (`gpd.GeoDataFrame`): GeoDataFrame containing max WSE results (requires 'geometry' and 'maximum_water_surface' columns, typically from `HdfResultsMesh.get_mesh_max_ws`).
*   **Returns:** `None`. Displays the plot.

### `HdfResultsPlot.plot_results_max_wsel_time(max_ws_df)`

*   **Purpose:** Creates a scatter plot showing the spatial distribution of the *time* at which maximum water surface elevation occurred for each mesh cell. Also prints timing statistics.
*   **Parameters:**
    *   `max_ws_df` (`gpd.GeoDataFrame`): GeoDataFrame containing max WSE results (requires 'geometry' and 'maximum_water_surface_time' columns, typically from `HdfResultsMesh.get_mesh_max_ws`).
*   **Returns:** `None`. Displays the plot and prints statistics.

### `HdfResultsPlot.plot_results_mesh_variable(variable_df, variable_name, colormap='viridis', point_size=10)`

*   **Purpose:** Creates a generic scatter plot for visualizing any scalar mesh variable (e.g., max depth, max velocity) spatially across cell points.
*   **Parameters:**
    *   `variable_df` (`gpd.GeoDataFrame` or `pd.DataFrame`): (Geo)DataFrame containing the variable data and either a 'geometry' column (Point) or 'x', 'y' columns.
    *   `variable_name` (`str`): The name of the column in `variable_df` containing the data to plot and label.
    *   `colormap` (`str`, optional): Matplotlib colormap name. Default 'viridis'.
    *   `point_size` (`int`, optional): Size of scatter plot points. Default 10.
*   **Returns:** `None`. Displays the plot.
*   **Raises:** `ValueError` if coordinates or variable column are missing.

---

## Class: HdfResultsXsec

Contains static methods for extracting 1D cross-section and related *results* data from HEC-RAS plan HDF files.

### `HdfResultsXsec.get_xsec_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Water Surface, Velocity, Flow, etc.) for all 1D cross-sections. Includes cross-section attributes (River, Reach, Station) and calculated maximum values as coordinates/variables.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and cross_section name/identifier. Includes coordinates for attributes and max values.
*   **Raises:** `KeyError`.

### `HdfResultsXsec.get_ref_lines_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Flow, Velocity, Water Surface) for all 1D Reference Lines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and reference line ID/name. Returns empty dataset if data not found.
*   **Raises:** `FileNotFoundError`, `KeyError`.

### `HdfResultsXsec.get_ref_points_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Flow, Velocity, Water Surface) for all 1D Reference Points.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and reference point ID/name. Returns empty dataset if data not found.
*   **Raises:** `FileNotFoundError`, `KeyError`.

---

## Class: HdfStruc

Contains static methods for extracting hydraulic structure *geometry* data from HEC-RAS HDF files (typically geometry HDF).

### `HdfStruc.get_structures(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts geometry and attributes for all structures (bridges, culverts, inline structures, lateral structures) defined in the geometry HDF. Includes centerline geometry, profile data, and other specific attributes like bridge coefficients.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to ISO strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries (centerlines) and numerous attribute columns, including nested profile data ('Profile_Data'). Returns empty GeoDataFrame if no structures found.

### `HdfStruc.get_geom_structures_attrs(hdf_path)`

*   **Purpose:** Extracts the top-level attributes associated with the 'Geometry/Structures' group in the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the group attributes. Returns empty DataFrame if group not found.

---

## Class: HdfUtils

Contains general static utility methods used for HDF processing, data conversion, and calculations.

### `HdfUtils.convert_ras_string(value)`

*   **Purpose:** Converts byte strings or regular strings potentially containing HEC-RAS specific formats (dates, durations, booleans) into appropriate Python objects (`bool`, `datetime`, `List[datetime]`, `timedelta`, `str`).
*   **Parameters:**
    *   `value` (`str` or `bytes`): Input string or byte string.
*   **Returns:** (`bool`, `datetime`, `List[datetime]`, `timedelta`, `str`): Converted Python object.

### `HdfUtils.convert_ras_hdf_value(value)`

*   **Purpose:** General converter for values read directly from HDF datasets (handles `np.nan`, byte strings, numpy types).
*   **Parameters:**
    *   `value` (`Any`): Value read from HDF.
*   **Returns:** (`None`, `bool`, `str`, `List[str]`, `int`, `float`, `List[int]`, `List[float]`): Converted Python object.

### `HdfUtils.convert_df_datetimes_to_str(df)`

*   **Purpose:** Converts all columns of dtype `datetime64` in a DataFrame to ISO format strings (`YYYY-MM-DD HH:MM:SS`).
*   **Parameters:**
    *   `df` (`pd.DataFrame`): Input DataFrame.
*   **Returns:** `pd.DataFrame`: DataFrame with datetime columns converted to strings.

### `HdfUtils.convert_hdf5_attrs_to_dict(attrs, prefix=None)`

*   **Purpose:** Converts HDF5 attributes (from `.attrs`) into a Python dictionary, applying `convert_ras_hdf_value` to each value.
*   **Parameters:**
    *   `attrs` (`h5py.AttributeManager` or `Dict`): Attributes object or dictionary.
    *   `prefix` (`str`, optional): Prefix to add to keys in the resulting dictionary.
*   **Returns:** `Dict[str, Any]`: Dictionary of converted attributes.

### `HdfUtils.convert_timesteps_to_datetimes(timesteps, start_time, time_unit="days", round_to="100ms")`

*   **Purpose:** Converts an array of numeric time steps (relative to a start time) into a pandas `DatetimeIndex`.
*   **Parameters:**
    *   `timesteps` (`np.ndarray`): Array of time step values.
    *   `start_time` (`datetime`): The reference start datetime.
    *   `time_unit` (`str`, optional): Unit of the `timesteps` ('days' or 'hours'). Default 'days'.
    *   `round_to` (`str`, optional): Pandas frequency string for rounding. Default '100ms'.
*   **Returns:** `pd.DatetimeIndex`: Index of datetime objects.

### `HdfUtils.perform_kdtree_query(reference_points, query_points, max_distance=2.0)`

*   **Purpose:** Finds nearest point in `reference_points` for each point in `query_points` using KDTree, within `max_distance`. Returns index or -1. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.perform_kdtree_query`.
*   **Returns:** (`np.ndarray`): Array of indices or -1.

### `HdfUtils.find_nearest_neighbors(points, max_distance=2.0)`

*   **Purpose:** Finds nearest neighbor for each point within the same dataset using KDTree, excluding self and points beyond `max_distance`. Returns index or -1. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.find_nearest_neighbors`.
*   **Returns:** (`np.ndarray`): Array of indices or -1.

### `HdfUtils.parse_ras_datetime(datetime_str)`

*   **Purpose:** Parses HEC-RAS standard datetime string format ("ddMMMYYYY HH:MM:SS").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object.

### `HdfUtils.parse_ras_window_datetime(datetime_str)`

*   **Purpose:** Parses HEC-RAS simulation window datetime string format ("ddMMMYYYY HHMM").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object.

### `HdfUtils.parse_duration(duration_str)`

*   **Purpose:** Parses HEC-RAS duration string format ("HH:MM:SS").
*   **Parameters:**
    *   `duration_str` (`str`): String to parse.
*   **Returns:** (`timedelta`): Parsed timedelta object.

### `HdfUtils.parse_ras_datetime_ms(datetime_str)`

*   **Purpose:** Parses HEC-RAS datetime string format that includes milliseconds ("ddMMMYYYY HH:MM:SS:fff").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object with microseconds.

### `HdfUtils.parse_run_time_window(window)`

*   **Purpose:** Parses a HEC-RAS time window string ("datetime1 to datetime2") into start and end datetime objects.
*   **Parameters:**
    *   `window` (`str`): Time window string.
*   **Returns:** `Tuple[datetime, datetime]`: Tuple containing (start_datetime, end_datetime).


---

## Class: HdfXsec

Contains static methods for extracting 1D cross-section *geometry* data from HEC-RAS HDF files (typically geometry HDF).

### `HdfXsec.get_cross_sections(hdf_path, datetime_to_str=True, ras_object=None)`

*   **Purpose:** Extracts detailed cross-section geometry, attributes, station-elevation data, Manning's n values, and ineffective flow areas from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `True`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries (cross-section cut lines) and numerous attributes including nested lists/dicts for profile data ('station_elevation'), roughness ('mannings_n'), and ineffective areas ('ineffective_blocks').

### `HdfXsec.get_river_centerlines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river centerline geometries and attributes from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes like 'River Name', 'Reach Name', 'length'.

### `HdfXsec.get_river_stationing(centerlines_gdf)`

*   **Purpose:** Calculates stationing values along river centerlines, interpolating points and determining direction based on upstream/downstream connections.
*   **Parameters:**
    *   `centerlines_gdf` (`gpd.GeoDataFrame`): GeoDataFrame obtained from `get_river_centerlines`.
*   **Returns:** `gpd.GeoDataFrame`: The input GeoDataFrame with added columns: 'station_start', 'station_end', 'stations' (array), 'points' (array of Shapely Points).

### `HdfXsec.get_river_reaches(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts 1D river reach lines (often identical to centerlines but potentially simplified) from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes.

### `HdfXsec.get_river_edge_lines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river edge lines (representing the extent of the 1D river schematic) from the geometry HDF file. Usually includes Left and Right edges.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes including 'bank_side' ('Left'/'Right').

### `HdfXsec.get_river_bank_lines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river bank lines (defining the main channel within the cross-section) from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes 'bank_id', 'bank_side'.

---

## Logging Configuration Functions

### `get_logger(name)`

*   **Purpose:** Retrieves a configured logger instance for use within the library or user scripts. Ensures logging is set up.
*   **Parameters:**
    *   `name` (`str`): Name for the logger (typically `__name__`).
*   **Returns:** (`logging.Logger`): A standard Python logger instance.

---

## Class: RasMap

Contains static methods for parsing and accessing information from HEC-RAS mapper configuration files (.rasmap) and automating post-processing tasks.

### `RasMap.parse_rasmap(rasmap_path: Union[str, Path], ras_object=None) -> pd.DataFrame`

*   **Purpose:** Parse a .rasmap file and extract relevant information, including paths to terrain, soil layers, land cover, and other spatial datasets.
*   **Parameters:**
    *   `rasmap_path` (`Union[str, Path]`): Path to the .rasmap file.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `pd.DataFrame`: A single-row DataFrame containing extracted information from the .rasmap file.
*   **Raises:** Various exceptions for file access or parsing failures.

### `RasMap.get_rasmap_path(ras_object=None) -> Optional[Path]`

*   **Purpose:** Get the path to the .rasmap file based on the current project.
*   **Parameters:**
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `Optional[Path]`: Path to the .rasmap file if found, None otherwise.

### `RasMap.initialize_rasmap_df(ras_object=None) -> pd.DataFrame`

*   **Purpose:** Initialize the `rasmap_df` as part of project initialization. This is typically called internally by `init_ras_project`.
*   **Parameters:**
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `pd.DataFrame`: DataFrame containing information from the .rasmap file.

### `RasMap.get_terrain_names(rasmap_path: Union[str, Path]) -> List[str]`
*   **Purpose:** Extracts all terrain layer names from a given `.rasmap` file.
*   **Parameters:**
    *   `rasmap_path` (`Union[str, Path]`): Path to the `.rasmap` file.
*   **Returns:** (`List[str]`): A list of terrain names.
*   **Raises:** `FileNotFoundError`, `ValueError`.

### `RasMap.postprocess_stored_maps(plan_number: Union[str, List[str]], specify_terrain: Optional[str] = None, layers: Union[str, List[str]] = None, ras_object: Optional[Any] = None) -> bool`
*   **Purpose:** Automates the generation of stored floodplain map outputs (e.g., `.tif` files) for a specific plan.
*   **Parameters:**
    *   `plan_number` (`Union[str, List[str]]`): Plan number(s) to generate maps for. Can be a single plan number as a string or a list of plan numbers for batch processing.
    *   `specify_terrain` (`Optional[str]`): The name of a specific terrain to use for mapping. If provided, other terrains are temporarily ignored.
    *   `layers` (`Union[str, List[str]]`, optional): A list of map layers to generate. Defaults to `['WSEL', 'Velocity', 'Depth']`.
    *   `ras_object` (`RasPrj`, optional): The RAS project object to use.
*   **Returns:** (`bool`): `True` if the process completed successfully, `False` otherwise.
*   **Workflow:**
    1.  Backs up the original plan and `.rasmap` files.
    2.  Modifies the plan file to only run floodplain mapping.
    3.  Modifies the `.rasmap` file to include the specified stored map layers.
    4.  Opens HEC-RAS GUI and waits for the user to manually execute the plan(s) using the 'Compute Multiple' window.
    5.  Completely restores the original plan and `.rasmap` files to their previous state after HEC-RAS closes.