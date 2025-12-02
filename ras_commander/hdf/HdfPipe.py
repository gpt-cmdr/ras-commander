"""
Class: HdfPipe

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfPipe:
Geometry Retrieval Functions:
- get_pipe_conduits() - Get pipe conduit geometries and attributes
- get_pipe_nodes() - Get pipe node geometries and attributes
- get_pipe_network() - Get complete pipe network data
- get_pipe_profile() - Get elevation profile for a specific conduit
- extract_pipe_network_data() - Extract both nodes and conduits data

Results Retrieval Functions:
- get_pipe_network_timeseries() - Get timeseries data for pipe network variables
- get_pipe_network_summary() - Get summary statistics for pipe networks
- get_pipe_node_timeseries() - Get timeseries data for a specific node
- get_pipe_conduit_timeseries() - Get timeseries data for a specific conduit

Note: All functions use the @standardize_input decorator to validate input paths
and the @log_call decorator for logging function calls.
"""
import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from pathlib import Path
from shapely.geometry import LineString, Point, MultiLineString, Polygon, MultiPolygon
from typing import List, Dict, Any, Optional, Union, Tuple
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from .HdfResultsMesh import HdfResultsMesh
import logging  

logger = get_logger(__name__)

class HdfPipe:
    """
    Static methods for handling pipe network data from HEC-RAS HDF files.

    Contains methods for:
    - Geometry retrieval (nodes, conduits, networks, profiles)
    - Results retrieval (timeseries and summary data)

    All methods use @standardize_input for path validation and @log_call
    """

    # Geometry Retrieval Functions
    
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_conduits(hdf_path: Path, crs: Optional[str] = "EPSG:4326") -> gpd.GeoDataFrame:
        """
        Extracts pipe conduit geometries and attributes from HDF5 file.

        Parameters:
            hdf_path: Path to the HDF5 file
            crs: Coordinate Reference System (default: "EPSG:4326")

        Returns:
            GeoDataFrame with columns:
            - Attributes from HDF5
            - Polyline: LineString geometries
            - Terrain_Profiles: List of (station, elevation) tuples
        """
        with h5py.File(hdf_path, 'r') as f:
            group = f['/Geometry/Pipe Conduits/']
            
            # --- Read and Process Attributes ---
            attributes = group['Attributes'][:]
            attr_df = pd.DataFrame(attributes)
            
            # Decode byte string fields to UTF-8 strings
            string_columns = attr_df.select_dtypes([object]).columns
            for col in string_columns:
                attr_df[col] = attr_df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
            
            # --- Read Polyline Data ---
            polyline_info = group['Polyline Info'][:]  # Shape (132,4) - point_start_idx, point_count, part_start_idx, part_count
            polyline_points = group['Polyline Points'][:]  # Shape (396,2) - x,y coordinates
            
            polyline_geometries = []
            for info in polyline_info:
                point_start_idx = info[0]
                point_count = info[1]
                
                # Extract coordinates for this polyline directly using start index and count
                coords = polyline_points[point_start_idx:point_start_idx + point_count]
                
                if len(coords) < 2:
                    polyline_geometries.append(None)
                else:
                    polyline_geometries.append(LineString(coords))
            
            # --- Read Terrain Profiles Data ---
            terrain_info = group['Terrain Profiles Info'][:]
            terrain_values = group['Terrain Profiles Values'][:]
            
            # Create a list of (Station, Elevation) tuples for Terrain Profiles
            terrain_coords = list(zip(terrain_values[:, 0], terrain_values[:, 1]))
            
            terrain_profiles_list: List[List[Tuple[float, float]]] = []
            
            for i in range(len(terrain_info)):
                info = terrain_info[i]
                start_idx = info[0]
                count = info[1]
                
                # Extract (Station, Elevation) pairs
                segment = terrain_coords[start_idx : start_idx + count]
                
                terrain_profiles_list.append(segment)  # Store the list of (Station, Elevation) tuples
            
            # --- Combine Data into GeoDataFrame ---
            attr_df['Polyline'] = polyline_geometries
            attr_df['Terrain_Profiles'] = terrain_profiles_list
            
            # Initialize GeoDataFrame with Polyline geometries
            gdf = gpd.GeoDataFrame(attr_df, geometry='Polyline', crs=crs)
            
            return gdf


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_nodes(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Creates a GeoDataFrame for Pipe Node points and their attributes from an HDF5 file.
        
        Parameters:
        - hdf_path: Path to the HDF5 file.
        
        Returns:
        - A GeoDataFrame containing pipe node attributes and their geometries.
        """
        with h5py.File(hdf_path, 'r') as f:
            group = f['/Geometry/Pipe Nodes/']
            
            # --- Read and Process Attributes ---
            attributes = group['Attributes'][:]
            attr_df = pd.DataFrame(attributes)
            
            # Decode byte string fields to UTF-8 strings
            string_columns = attr_df.select_dtypes([object]).columns  # Changed 'S' to object
            for col in string_columns:
                attr_df[col] = attr_df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
            
            # --- Read Points Data ---
            points = group['Points'][:]
            # Create Shapely Point geometries
            geometries = [Point(xy) for xy in points]
            
            # --- Combine Attributes and Geometries into GeoDataFrame ---
            gdf = gpd.GeoDataFrame(attr_df, geometry=geometries)
            
            return gdf
        
        


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network(hdf_path: Path, pipe_network_name: Optional[str] = None, crs: Optional[str] = "EPSG:4326") -> gpd.GeoDataFrame:
        """
        Creates a GeoDataFrame for a pipe network's geometry.

        Parameters:
            hdf_path: Path to the HDF5 file
            pipe_network_name: Name of network (uses first if None)
            crs: Coordinate Reference System (default: "EPSG:4326")

        Returns:
            GeoDataFrame containing:
            - Cell polygons (primary geometry)
            - Face polylines
            - Node points
            - Associated attributes
        """
        with h5py.File(hdf_path, 'r') as f:
            pipe_networks_group = f['/Geometry/Pipe Networks/']
            
            # --- Determine Pipe Network to Use ---
            attributes = pipe_networks_group['Attributes'][:]
            attr_df = pd.DataFrame(attributes)
            
            # Decode 'Name' from byte strings to UTF-8
            attr_df['Name'] = attr_df['Name'].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
            
            if pipe_network_name:
                if pipe_network_name not in attr_df['Name'].values:
                    raise ValueError(f"Pipe network '{pipe_network_name}' not found in the HDF5 file.")
                network_idx = attr_df.index[attr_df['Name'] == pipe_network_name][0]
            else:
                network_idx = 0  # Default to first network
            
            # Get the name of the selected pipe network
            selected_network_name = attr_df.at[network_idx, 'Name']
            logging.info(f"Selected Pipe Network: {selected_network_name}")
            
            # Access the selected pipe network group
            network_group_path = f"/Geometry/Pipe Networks/{selected_network_name}/"
            network_group = f[network_group_path]
            
            # --- Helper Functions ---
            def decode_bytes(df: pd.DataFrame) -> pd.DataFrame:
                """Decode byte string columns to UTF-8."""
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                return df
            
            def build_polygons(info, parts, points) -> List[Optional[Polygon or MultiPolygon]]:
                """Build Shapely Polygon or MultiPolygon geometries from HDF5 datasets."""
                poly_coords = list(zip(points[:, 0], points[:, 1]))
                geometries = []
                for i in range(len(info)):
                    cell_info = info[i]
                    point_start_idx = cell_info[0]
                    point_count = cell_info[1]
                    part_start_idx = cell_info[2]
                    part_count = cell_info[3]
                    
                    parts_list = []
                    for p in range(part_start_idx, part_start_idx + part_count):
                        if p >= len(parts):
                            continue  # Prevent index out of range
                        part_info = parts[p]
                        part_point_start = part_info[0]
                        part_point_count = part_info[1]
                        
                        coords = poly_coords[part_point_start : part_point_start + part_point_count]
                        if len(coords) < 3:
                            continue  # Not a valid polygon part
                        parts_list.append(coords)
                    
                    if not parts_list:
                        geometries.append(None)
                    elif len(parts_list) == 1:
                        try:
                            geometries.append(Polygon(parts_list[0]))
                        except ValueError:
                            geometries.append(None)
                    else:
                        try:
                            geometries.append(MultiPolygon([Polygon(p) for p in parts_list if len(p) >= 3]))
                        except ValueError:
                            geometries.append(None)
                return geometries
            
            def build_multilinestring(info, parts, points) -> List[Optional[LineString or MultiLineString]]:
                """Build Shapely LineString or MultiLineString geometries from HDF5 datasets."""
                line_coords = list(zip(points[:, 0], points[:, 1]))
                geometries = []
                for i in range(len(info)):
                    face_info = info[i]
                    point_start_idx = face_info[0]
                    point_count = face_info[1]
                    part_start_idx = face_info[2]
                    part_count = face_info[3]
                    
                    parts_list = []
                    for p in range(part_start_idx, part_start_idx + part_count):
                        if p >= len(parts):
                            continue  # Prevent index out of range
                        part_info = parts[p]
                        part_point_start = part_info[0]
                        part_point_count = part_info[1]
                        
                        coords = line_coords[part_point_start : part_point_start + part_point_count]
                        if len(coords) < 2:
                            continue  # Cannot form LineString with fewer than 2 points
                        parts_list.append(coords)
                    
                    if not parts_list:
                        geometries.append(None)
                    elif len(parts_list) == 1:
                        geometries.append(LineString(parts_list[0]))
                    else:
                        geometries.append(MultiLineString(parts_list))
                return geometries
            
            # --- Read and Process Cell Polygons ---
            cell_polygons_info = network_group['Cell Polygons Info'][:]
            cell_polygons_parts = network_group['Cell Polygons Parts'][:]
            cell_polygons_points = network_group['Cell Polygons Points'][:]
            
            cell_polygons_geometries = build_polygons(cell_polygons_info, cell_polygons_parts, cell_polygons_points)
            
            # --- Read and Process Face Polylines ---
            face_polylines_info = network_group['Face Polylines Info'][:]
            face_polylines_parts = network_group['Face Polylines Parts'][:]
            face_polylines_points = network_group['Face Polylines Points'][:]
            
            face_polylines_geometries = build_multilinestring(face_polylines_info, face_polylines_parts, face_polylines_points)
            
            # --- Read and Process Node Points ---
            node_surface_connectivity_group = network_group.get('Node Surface Connectivity', None)
            if node_surface_connectivity_group is not None:
                node_surface_connectivity = node_surface_connectivity_group[:]
            else:
                node_surface_connectivity = None
            
            # Assuming Node Connectivity Info and Values contain node coordinates
            node_connectivity_info = network_group['Node Connectivity Info'][:]
            node_connectivity_values = network_group['Node Connectivity Values'][:]
            node_indices = network_group['Node Indices'][:]
            node_surface_connectivity = network_group['Node Surface Connectivity'][:]
            
            # For simplicity, assuming that node connectivity includes X and Y coordinates
            # This may need to be adjusted based on actual data structure
            # Here, we'll create dummy points as placeholder
            # Replace with actual coordinate extraction logic as per data structure
            # For demonstration, we'll create random points
            # You should replace this with actual data extraction
            # Example:
            # node_points = network_group['Node Coordinates'][:]
            # node_geometries = [Point(x, y) for x, y in node_points]
            
            # Placeholder for node geometries
            # Assuming node_indices contains Node IDs and coordinates
            # Adjust based on actual dataset structure
            # Here, we assume that node_indices has columns: [Node ID, X, Y]
            # But based on the log, Node Surface Connectivity has ['Node ID', 'Layer', 'Layer ID', 'Sublayer ID']
            # No coordinates are provided, so we cannot create Point geometries unless coordinates are available elsewhere
            # Therefore, this part may need to be adapted based on actual data
            # For now, we'll skip node points geometries
            node_geometries = [None] * len(node_indices)  # Placeholder
            
            # --- Read and Process Cell Property Table ---
            cell_property_table = network_group['Cell Property Table'][:]
            cell_property_df = pd.DataFrame(cell_property_table)
            
            # Decode byte strings if any
            cell_property_df = decode_bytes(cell_property_df)
            
            # --- Read and Process Cells DS Face Indices ---
            cells_ds_face_info = network_group['Cells DS Face Indices Info'][:]
            cells_ds_face_values = network_group['Cells DS Face Indices Values'][:]
            
            # Create lists of DS Face Indices per cell
            cells_ds_face_indices = []
            for i in range(len(cells_ds_face_info)):
                info = cells_ds_face_info[i]
                start_idx, count = info
                indices = cells_ds_face_values[start_idx : start_idx + count]
                cells_ds_face_indices.append(indices.tolist())
            
            # --- Read and Process Cells Face Indices ---
            cells_face_info = network_group['Cells Face Indices Info'][:]
            cells_face_values = network_group['Cells Face Indices Values'][:]
            
            # Create lists of Face Indices per cell
            cells_face_indices = []
            for i in range(len(cells_face_info)):
                info = cells_face_info[i]
                start_idx, count = info
                indices = cells_face_values[start_idx : start_idx + count]
                cells_face_indices.append(indices.tolist())
            
            # --- Read and Process Cells Minimum Elevations ---
            cells_min_elevations = network_group['Cells Minimum Elevations'][:]
            cells_min_elevations_df = pd.DataFrame(cells_min_elevations, columns=['Minimum_Elevation'])
            
            # --- Read and Process Cells Node and Conduit IDs ---
            cells_node_conduit_ids = network_group['Cells Node and Conduit IDs'][:]
            cells_node_conduit_df = pd.DataFrame(cells_node_conduit_ids, columns=['Node_ID', 'Conduit_ID'])
            
            # --- Read and Process Cells US Face Indices ---
            cells_us_face_info = network_group['Cells US Face Indices Info'][:]
            cells_us_face_values = network_group['Cells US Face Indices Values'][:]
            
            # Create lists of US Face Indices per cell
            cells_us_face_indices = []
            for i in range(len(cells_us_face_info)):
                info = cells_us_face_info[i]
                start_idx, count = info
                indices = cells_us_face_values[start_idx : start_idx + count]
                cells_us_face_indices.append(indices.tolist())
            
            # --- Read and Process Conduit Indices ---
            conduit_indices = network_group['Conduit Indices'][:]
            conduit_indices_df = pd.DataFrame(conduit_indices, columns=['Conduit_ID'])
            
            # --- Read and Process Face Property Table ---
            face_property_table = network_group['Face Property Table'][:]
            face_property_df = pd.DataFrame(face_property_table)
            
            # Decode byte strings if any
            face_property_df = decode_bytes(face_property_df)
            
            # --- Read and Process Face Conduit ID and Stations ---
            faces_conduit_id_stations = network_group['Faces Conduit ID and Stations'][:]
            faces_conduit_df = pd.DataFrame(faces_conduit_id_stations, columns=['ConduitID', 'ConduitStation', 'CellUS', 'CellDS', 'Elevation'])
            
            # --- Read and Process Node Connectivity Info and Values ---
            node_connectivity_info = network_group['Node Connectivity Info'][:]
            node_connectivity_values = network_group['Node Connectivity Values'][:]
            
            # Create lists of connected nodes per node
            node_connectivity = []
            for i in range(len(node_connectivity_info)):
                info = node_connectivity_info[i]
                start_idx, count = info
                connections = node_connectivity_values[start_idx : start_idx + count]
                node_connectivity.append(connections.tolist())
            
            # --- Read and Process Node Indices ---
            node_indices = network_group['Node Indices'][:]
            node_indices_df = pd.DataFrame(node_indices, columns=['Node_ID'])
            
            # --- Read and Process Node Surface Connectivity ---
            node_surface_connectivity = network_group['Node Surface Connectivity'][:]
            node_surface_connectivity_df = pd.DataFrame(node_surface_connectivity, columns=['Node_ID', 'Layer', 'Layer_ID', 'Sublayer_ID'])
            
            # --- Combine All Cell-Related Data ---
            cells_df = pd.DataFrame({
                'Cell_ID': range(len(cell_polygons_geometries)),
                'Conduit_ID': cells_node_conduit_df['Conduit_ID'],
                'Node_ID': cells_node_conduit_df['Node_ID'],
                'Minimum_Elevation': cells_min_elevations_df['Minimum_Elevation'],
                'DS_Face_Indices': cells_ds_face_indices,
                'Face_Indices': cells_face_indices,
                'US_Face_Indices': cells_us_face_indices,
                'Cell_Property_Info_Index': cell_property_df['Info Index'],
                # Add other cell properties as needed
            })
            
            # Merge with cell property table
            cells_df = cells_df.merge(cell_property_df, left_on='Cell_Property_Info_Index', right_index=True, how='left')
            
            # --- Combine All Face-Related Data ---
            faces_df = pd.DataFrame({
                'Face_ID': range(len(face_polylines_geometries)),
                'Conduit_ID': faces_conduit_df['ConduitID'],
                'Conduit_Station': faces_conduit_df['ConduitStation'],
                'Cell_US': faces_conduit_df['CellUS'],
                'Cell_DS': faces_conduit_df['CellDS'],
                'Elevation': faces_conduit_df['Elevation'],
                'Face_Property_Info_Index': face_property_df['Info Index'],
                # Add other face properties as needed
            })
            
            # Merge with face property table
            faces_df = faces_df.merge(face_property_df, left_on='Face_Property_Info_Index', right_index=True, how='left')
            
            # --- Combine All Node-Related Data ---
            nodes_df = pd.DataFrame({
                'Node_ID': node_indices_df['Node_ID'],
                'Connected_Nodes': node_connectivity,
                # Add other node properties as needed
            })
            
            # Merge with node surface connectivity
            nodes_df = nodes_df.merge(node_surface_connectivity_df, on='Node_ID', how='left')
            
            # --- Create GeoDataFrame ---
            # Main DataFrame will be cells with their polygons
            cells_df['Cell_Polygon'] = cell_polygons_geometries
            
            # Add face polylines as a separate column (list of geometries)
            cells_df['Face_Polylines'] = cells_df['Face_Indices'].apply(lambda indices: [face_polylines_geometries[i] for i in indices if i < len(face_polylines_geometries)])
            
            # Add node points if geometries are available
            # Currently, node_geometries are placeholders (None). Replace with actual geometries if available.
            cells_df['Node_Point'] = cells_df['Node_ID'].apply(lambda nid: node_geometries[nid] if nid < len(node_geometries) else None)
            
            # Initialize GeoDataFrame with Cell Polygons
            gdf = gpd.GeoDataFrame(cells_df, geometry='Cell_Polygon', crs=crs)
            
            # Optionally, add Face Polylines and Node Points as separate columns
            # Note: GeoPandas primarily supports one geometry column, so these are stored as object columns
            gdf['Face_Polylines'] = cells_df['Face_Polylines']
            gdf['Node_Point'] = cells_df['Node_Point']
            
            # You can further expand this GeoDataFrame by merging with faces_df and nodes_df if needed
            
            return gdf
        
        
        
        
        


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_profile(hdf_path: Path, conduit_id: int) -> pd.DataFrame:
        """
        Extract the profile data for a specific pipe conduit.

        Args:
            hdf_path (Path): Path to the HDF file.
            conduit_id (int): ID of the conduit to extract profile for.

        Returns:
            pd.DataFrame: DataFrame containing the pipe profile data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
            IndexError: If the specified conduit_id is out of range.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Get conduit info
                terrain_profiles_info = hdf['/Geometry/Pipe Conduits/Terrain Profiles Info'][()]
                
                if conduit_id >= len(terrain_profiles_info):
                    raise IndexError(f"conduit_id {conduit_id} is out of range")

                start, count = terrain_profiles_info[conduit_id]

                # Extract profile data
                profile_values = hdf['/Geometry/Pipe Conduits/Terrain Profiles Values'][start:start+count]

                # Create DataFrame
                df = pd.DataFrame(profile_values, columns=['Station', 'Elevation'])

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except IndexError as e:
            logger.error(f"Invalid conduit_id: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pipe profile data: {e}")
            raise
        
        
   









# RESULTS FUNCTIONS: 

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network_summary(hdf_path: Path) -> pd.DataFrame:
        """
        Extract results summary data for pipe networks from the HDF file.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing pipe network summary data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract summary data
                summary_path = "/Results/Unsteady/Summary/Pipe Network"
                if summary_path not in hdf:
                    logger.warning("Pipe Network summary data not found in HDF file")
                    return pd.DataFrame()

                summary_data = hdf[summary_path][()]
                
                # Create DataFrame
                df = pd.DataFrame(summary_data)

                # Convert column names
                df.columns = [col.decode('utf-8') for col in df.columns]

                return df

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pipe network summary data: {e}")
            raise




    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def extract_timeseries_for_node(plan_hdf_path: Path, node_id: int) -> Dict[str, xr.DataArray]:
        """
        Extract time series data for a specific node.
        
        Parameters:
        -----------
        plan_hdf_path : Path
            Path to HEC-RAS results HDF file
        node_id : int
            ID of the node to extract data for
            
        Returns:
        --------
        Dict[str, xr.DataArray]: Dictionary containing time series data for:
            - Depth
            - Drop Inlet Flow
            - Water Surface
        """
        try:
            node_variables = ["Nodes/Depth", "Nodes/Drop Inlet Flow", "Nodes/Water Surface"]
            node_data = {}

            for variable in node_variables:
                data = HdfPipe.get_pipe_network_timeseries(plan_hdf_path, variable=variable)
                node_data[variable] = data.sel(location=node_id)
            
            return node_data
        except Exception as e:
            logger.error(f"Error extracting time series data for node {node_id}: {str(e)}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def extract_timeseries_for_conduit(plan_hdf_path: Path, conduit_id: int) -> Dict[str, xr.DataArray]:
        """
        Extract time series data for a specific conduit.
        
        Parameters:
        -----------
        plan_hdf_path : Path
            Path to HEC-RAS results HDF file
        conduit_id : int
            ID of the conduit to extract data for
            
        Returns:
        --------
        Dict[str, xr.DataArray]: Dictionary containing time series data for:
            - Pipe Flow (US/DS)
            - Velocity (US/DS)
        """
        try:
            conduit_variables = ["Pipes/Pipe Flow DS", "Pipes/Pipe Flow US", 
                                "Pipes/Vel DS", "Pipes/Vel US"]
            conduit_data = {}

            for variable in conduit_variables:
                data = HdfPipe.get_pipe_network_timeseries(plan_hdf_path, variable=variable)
                conduit_data[variable] = data.sel(location=conduit_id)
            
            return conduit_data
        except Exception as e:
            logger.error(f"Error extracting time series data for conduit {conduit_id}: {str(e)}")
            raise


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network_timeseries(hdf_path: Path, variable: str) -> xr.DataArray:
        """
        Extracts timeseries data for a pipe network variable.

        Parameters:
            hdf_path: Path to the HDF5 file
            variable: Variable name to extract. Valid options:
                - Cell: Courant, Water Surface
                - Face: Flow, Velocity, Water Surface
                - Pipes: Pipe Flow (DS/US), Vel (DS/US)
                - Nodes: Depth, Drop Inlet Flow, Water Surface

        Returns:
            xarray.DataArray with dimensions (time, location)
        """
        valid_variables = [
            "Cell Courant", "Cell Water Surface", "Face Flow", "Face Velocity",
            "Face Water Surface", "Pipes/Pipe Flow DS", "Pipes/Pipe Flow US",
            "Pipes/Vel DS", "Pipes/Vel US", "Nodes/Depth", "Nodes/Drop Inlet Flow",
            "Nodes/Water Surface"
        ]

        if variable not in valid_variables:
            raise ValueError(f"Invalid variable. Must be one of: {', '.join(valid_variables)}")

        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract timeseries data
                data_path = f"/Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Pipe Networks/Davis/{variable}"
                data = hdf[data_path][()]

                # Extract time information using the correct method name
                time = HdfBase.get_unsteady_timestamps(hdf)

                # Create DataArray
                da = xr.DataArray(
                    data=data,
                    dims=['time', 'location'],
                    coords={'time': time, 'location': range(data.shape[1])},
                    name=variable
                )

                # Add attributes
                da.attrs['units'] = hdf[data_path].attrs.get('Units', b'').decode('utf-8')
                da.attrs['variable'] = variable

                return da

        except KeyError as e:
            logger.error(f"Required dataset not found in HDF file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error extracting pipe network timeseries data: {e}")
            raise




