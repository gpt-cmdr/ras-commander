"""
Class: HdfResultsMesh

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All methods in this class are static and designed to be used without instantiation.

Public Functions:
- get_mesh_summary(): Get summary output data for a variable 
- get_mesh_timeseries(): Get timeseries output for a mesh and variable  
- get_mesh_faces_timeseries(): Get timeseries for all face-based variables
- get_mesh_cells_timeseries(): Get timeseries for mesh cells
- get_mesh_last_iter(): Get last iteration count for cells
- get_mesh_max_ws(): Get maximum water surface elevation at each cell   
- get_mesh_min_ws(): Get minimum water surface elevation at each cell
- get_mesh_max_face_v(): Get maximum face velocity at each face
- get_mesh_min_face_v(): Get minimum face velocity at each face
- get_mesh_max_ws_err(): Get maximum water surface error at each cell
- get_mesh_max_iter(): Get maximum iteration count at each cell

Private Functions:
- _get_mesh_timeseries_output_path(): Get HDF path for timeseries output  #REDUNDANT??
- _get_mesh_cells_timeseries_output(): Internal handler for cell timeseries   #REDUNDANT??
- _get_mesh_timeseries_output(): Internal handler for mesh timeseries       # FACES?? 
- _get_mesh_timeseries_output_values_units(): Get values and units for timeseries
- _get_available_meshes(): Get list of available meshes in HDF            #USE HDFBASE OR HDFUTIL
- get_mesh_summary_output(): Internal handler for summary output        
- get_mesh_summary_output_group(): Get HDF group for summary output         #REDUNDANT??  Include in Above

The class works with HEC-RAS version 6.0+ plan HDF files and uses HdfBase and 
HdfUtils for common operations. Methods use @log_call decorator for logging and 
@standardize_input decorator to handle different input types.









"""

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
import h5py
from typing import Union, List, Optional, Dict, Any, Tuple
from .HdfMesh import HdfMesh
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import setup_logging, get_logger
import geopandas as gpd

logger = get_logger(__name__)

class HdfResultsMesh:
    """
    Handles mesh-related results from HEC-RAS HDF files.

    Provides methods to extract and analyze:
    - Mesh summary outputs
    - Timeseries data
    - Water surface elevations
    - Velocities
    - Error metrics

    Works with HEC-RAS 6.0+ plan HDF files.
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_summary(hdf_path: Path, var: str, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (Path): Path to the HDF file
            mesh_name (str): Name of the mesh
            var (str): Variable to retrieve (see valid options below)
            truncate (bool): Whether to truncate trailing zeros (default True)

        Returns:
            xr.DataArray: DataArray with dimensions:
                - time: Timestamps
                - face_id/cell_id: IDs for faces/cells
                And attributes:
                - units: Variable units
                - mesh_name: Name of mesh
                - variable: Variable name

        Valid variables include:
            "Water Surface", "Face Velocity", "Cell Velocity X"...
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, var, round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_summary: {str(e)}")
            logger.error(f"Variable: {var}")
            raise ValueError(f"Failed to get summary output: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_timeseries(hdf_path: Path, mesh_name: str, var: str, truncate: bool = True) -> xr.DataArray:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (Path): Path to the HDF file
            mesh_name (str): Name of the mesh
            var (str): Variable to retrieve (see valid options below)
            truncate (bool): Whether to truncate trailing zeros (default True)

        Returns:
            xr.DataArray: DataArray with dimensions:
                - time: Timestamps
                - face_id/cell_id: IDs for faces/cells
                And attributes:
                - units: Variable units
                - mesh_name: Name of mesh
                - variable: Variable name

        Valid variables include:
            "Water Surface", "Face Velocity", "Cell Velocity X"...
        """
        with h5py.File(hdf_path, 'r') as hdf_path:
            return HdfResultsMesh._get_mesh_timeseries_output(hdf_path, mesh_name, var, truncate)

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_faces_timeseries(hdf_path: Path, mesh_name: str) -> xr.Dataset:
        """
        Get timeseries output for all face-based variables of a specific mesh.

        Args:
            hdf_path (Path): Path to the HDF file.
            mesh_name (str): Name of the mesh.

        Returns:
            xr.Dataset: Dataset containing the timeseries output for all face-based variables.
        """
        face_vars = ["Face Velocity", "Face Flow"]
        datasets = []
        
        for var in face_vars:
            try:
                da = HdfResultsMesh.get_mesh_timeseries(hdf_path, mesh_name, var)
                # Assign the variable name as the DataArray name
                da.name = var.lower().replace(' ', '_')
                datasets.append(da)
            except Exception as e:
                logger.warning(f"Failed to process {var} for mesh {mesh_name}: {str(e)}")
        
        if not datasets:
            logger.error(f"No valid data found for mesh {mesh_name}")
            return xr.Dataset()
        
        try:
            return xr.merge(datasets)
        except Exception as e:
            logger.error(f"Failed to merge datasets: {str(e)}")
            return xr.Dataset()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_cells_timeseries(hdf_path: Path, mesh_names: Optional[Union[str, List[str]]] = None, var: Optional[str] = None, truncate: bool = False, ras_object: Optional[Any] = None) -> Dict[str, xr.Dataset]:
        """
        Get mesh cells timeseries output.

        Args:
            hdf_path (Path): Path to HDF file
            mesh_names (str|List[str], optional): Mesh name(s). If None, processes all meshes
            var (str, optional): Variable name. If None, retrieves all variables
            truncate (bool): Remove trailing zeros if True
            ras_object (Any, optional): RAS object if available

        Returns:
            Dict[str, xr.Dataset]: Dictionary mapping mesh names to datasets containing:
                - Time-indexed variables
                - Cell/face IDs
                - Variable metadata
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_path:
                return HdfResultsMesh._get_mesh_cells_timeseries_output(hdf_path, mesh_names, var, truncate)
        except Exception as e:
            logger.error(f"Error in get_mesh_cells_timeseries: {str(e)}")
            raise ValueError(f"Error processing timeseries output data: {e}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_last_iter(hdf_file: Path) -> pd.DataFrame:
        """
        Get last iteration count for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing last iteration counts.
        """
        return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Last Iteration")


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_ws(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get maximum water surface elevation for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing maximum water surface elevations with geometry.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Maximum Water Surface", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_ws: {str(e)}")
            raise ValueError(f"Failed to get maximum water surface: {str(e)}")
        




    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_min_ws(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get minimum water surface elevation for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing minimum water surface elevations with geometry.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Minimum Water Surface", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_min_ws: {str(e)}")
            raise ValueError(f"Failed to get minimum water surface: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_face_v(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get maximum face velocity for each mesh face.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing maximum face velocities.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Maximum Face Velocity", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_face_v: {str(e)}")
            raise ValueError(f"Failed to get maximum face velocity: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_min_face_v(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get minimum face velocity for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing minimum face velocities.

        Raises:
            ValueError: If there's an error processing the minimum face velocity data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Minimum Face Velocity", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_min_face_v: {str(e)}")
            raise ValueError(f"Failed to get minimum face velocity: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_ws_err(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get maximum water surface error for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing maximum water surface errors.

        Raises:
            ValueError: If there's an error processing the maximum water surface error data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Maximum Water Surface Error", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_ws_err: {str(e)}")
            raise ValueError(f"Failed to get maximum water surface error: {str(e)}")


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_iter(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get maximum iteration count for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing maximum iteration counts with geometry.
                Includes columns:
                - mesh_name: Name of the mesh
                - cell_id: ID of the cell
                - cell_last_iteration: Maximum number of iterations
                - cell_last_iteration_time: Time when max iterations occurred
                - geometry: Point geometry representing cell center
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Last Iteration", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_iter: {str(e)}")
            raise ValueError(f"Failed to get maximum iteration count: {str(e)}")
        
        


    @staticmethod
    def _get_mesh_timeseries_output_path(mesh_name: str, var_name: str) -> str:
        """
        Get the HDF path for mesh timeseries output.

        Args:
            mesh_name (str): Name of the mesh.
            var_name (str): Name of the variable.

        Returns:
            str: The HDF path for the specified mesh and variable.
        """
        return f"Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{mesh_name}/{var_name}"


    @staticmethod
    def _get_mesh_cells_timeseries_output(hdf_path: h5py.File, 
                                         mesh_names: Optional[Union[str, List[str]]] = None,
                                         var: Optional[str] = None, 
                                         truncate: bool = False) -> Dict[str, xr.Dataset]:
        """
        Get mesh cells timeseries output for specified meshes and variables.
        
        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_names (Optional[Union[str, List[str]]]): Name(s) of the mesh(es). If None, processes all available meshes.
            var (Optional[str]): Name of the variable to retrieve. If None, retrieves all variables.
            truncate (bool): If True, truncates the output to remove trailing zeros.

        Returns:
            Dict[str, xr.Dataset]: A dictionary of xarray Datasets, one for each mesh, containing the mesh cells timeseries output.

        Raises:
            ValueError: If there's an error processing the timeseries output data.
        """
        TIME_SERIES_OUTPUT_VARS = {
            "cell": [
                "Water Surface", "Depth", "Velocity", "Velocity X", "Velocity Y",
                "Froude Number", "Courant Number", "Shear Stress", "Bed Elevation",
                "Precipitation Rate", "Infiltration Rate", "Evaporation Rate",
                "Percolation Rate", "Groundwater Elevation", "Groundwater Depth",
                "Groundwater Flow", "Groundwater Velocity", "Groundwater Velocity X",
                "Groundwater Velocity Y"
            ],
            "face": [
                "Face Velocity", "Face Flow", "Face Water Surface", "Face Courant",
                "Face Cumulative Volume", "Face Eddy Viscosity", "Face Flow Period Average",
                "Face Friction Term", "Face Pressure Gradient Term", "Face Shear Stress",
                "Face Tangential Velocity"
            ]
        }

        try:
            start_time = HdfBase.get_simulation_start_time(hdf_path)
            time_stamps = HdfBase.get_unsteady_timestamps(hdf_path)

            if mesh_names is None:
                mesh_names = HdfResultsMesh._get_available_meshes(hdf_path)
            elif isinstance(mesh_names, str):
                mesh_names = [mesh_names]

            if var:
                variables = [var]
            else:
                variables = TIME_SERIES_OUTPUT_VARS["cell"] + TIME_SERIES_OUTPUT_VARS["face"]

            datasets = {}
            for mesh_name in mesh_names:
                data_vars = {}
                for variable in variables:
                    try:
                        path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, variable)
                        dataset = hdf_path[path]
                        values = dataset[:]
                        units = dataset.attrs.get("Units", "").decode("utf-8")

                        if truncate:
                            last_nonzero = np.max(np.nonzero(values)[1]) + 1 if values.size > 0 else 0
                            values = values[:, :last_nonzero]
                            truncated_time_stamps = time_stamps[:last_nonzero]
                        else:
                            truncated_time_stamps = time_stamps

                        if values.shape[0] != len(truncated_time_stamps):
                            logger.warning(f"Mismatch between time steps ({len(truncated_time_stamps)}) and data shape ({values.shape}) for variable {variable}")
                            continue

                        # Determine if this is a face-based or cell-based variable
                        id_dim = "face_id" if any(face_var in variable for face_var in TIME_SERIES_OUTPUT_VARS["face"]) else "cell_id"

                        data_vars[variable] = xr.DataArray(
                            data=values,
                            dims=['time', id_dim],
                            coords={'time': truncated_time_stamps, id_dim: np.arange(values.shape[1])},
                            attrs={'units': units}
                        )
                    except KeyError:
                        logger.warning(f"Variable '{variable}' not found in the HDF file for mesh '{mesh_name}'. Skipping.")
                    except Exception as e:
                        logger.error(f"Error processing variable '{variable}' for mesh '{mesh_name}': {str(e)}")

                if data_vars:
                    datasets[mesh_name] = xr.Dataset(
                        data_vars=data_vars,
                        attrs={'mesh_name': mesh_name, 'start_time': start_time}
                    )
                else:
                    logger.warning(f"No valid data variables found for mesh '{mesh_name}'")

            return datasets
        except Exception as e:
            logger.error(f"Error in _mesh_cells_timeseries_output: {str(e)}")
            raise ValueError(f"Error processing timeseries output data: {e}")



    @staticmethod
    def _get_mesh_timeseries_output(hdf_path: h5py.File, mesh_name: str, var: str, truncate: bool = True) -> xr.DataArray:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Variable name to retrieve.
            truncate (bool): Whether to truncate the output to remove trailing zeros (default True).

        Returns:
            xr.DataArray: DataArray containing the timeseries output.

        Raises:
            ValueError: If the specified path is not found in the HDF file or if there's an error processing the data.
        """
        try:
            path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, var)
            
            if path not in hdf_path:
                raise ValueError(f"Path {path} not found in HDF file")

            dataset = hdf_path[path]
            values = dataset[:]
            units = dataset.attrs.get("Units", "").decode("utf-8")
            
            # Get start time and timesteps
            start_time = HdfBase.get_simulation_start_time(hdf_path)
            # Updated to use the new function name from HdfUtils
            timesteps = HdfUtils.convert_timesteps_to_datetimes(
                np.array(hdf_path["Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time"][:]),
                start_time
            )

            if truncate:
                non_zero = np.nonzero(values)[0]
                if len(non_zero) > 0:
                    start, end = non_zero[0], non_zero[-1] + 1
                    values = values[start:end]
                    timesteps = timesteps[start:end]

            # Determine if this is a face-based or cell-based variable
            id_dim = "face_id" if "Face" in var else "cell_id"
            dims = ["time", id_dim] if values.ndim == 2 else ["time"]
            coords = {"time": timesteps}
            if values.ndim == 2:
                coords[id_dim] = np.arange(values.shape[1])

            return xr.DataArray(
                values,
                coords=coords,
                dims=dims,
                attrs={"units": units, "mesh_name": mesh_name, "variable": var},
            )
        except Exception as e:
            logger.error(f"Error in get_mesh_timeseries_output: {str(e)}")
            raise ValueError(f"Failed to get timeseries output: {str(e)}")


    @staticmethod
    def _get_mesh_timeseries_output_values_units(hdf_path: h5py.File, mesh_name: str, var: str) -> Tuple[np.ndarray, str]:
        """
        Get the mesh timeseries output values and units for a specific variable from the HDF file.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Variable name to retrieve.

        Returns:
            Tuple[np.ndarray, str]: A tuple containing the output values and units.
        """
        path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, var)
        group = hdf_path[path]
        values = group[:]
        units = group.attrs.get("Units")
        if units is not None:
            units = units.decode("utf-8")
        return values, units


    @staticmethod
    def _get_available_meshes(hdf_path: h5py.File) -> List[str]:
        """
        Get the names of all available meshes in the HDF file.

        Args:
            hdf_path (h5py.File): Open HDF file object.

        Returns:
            List[str]: A list of mesh names.
        """
        return HdfMesh.get_mesh_area_names(hdf_path)
    
    
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_summary_output(hdf_file: h5py.File, var: str, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get the summary output data for a given variable from the HDF file.

        Parameters
        ----------
        hdf_path : h5py.File
            Open HDF file object.
        var : str
            The summary output variable to retrieve.
        round_to : str, optional
            The time unit to round the datetimes to. Default is "100ms".

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the summary output data with decoded attributes as metadata.
            Returns empty GeoDataFrame if variable is not found.
        """
        try:
            dfs = []
            start_time = HdfBase.get_simulation_start_time(hdf_file)
            
            logger.info(f"Processing summary output for variable: {var}")
            d2_flow_areas = hdf_file.get("Geometry/2D Flow Areas/Attributes")
            if d2_flow_areas is None:
                logger.info("No 2D Flow Areas found in HDF file")
                return gpd.GeoDataFrame()

            for d2_flow_area in d2_flow_areas[:]:
                mesh_name = HdfUtils.convert_ras_string(d2_flow_area[0])
                cell_count = d2_flow_area[-1]
                logger.debug(f"Processing mesh: {mesh_name} with {cell_count} cells")
                
                try:
                    group = HdfResultsMesh.get_mesh_summary_output_group(hdf_file, mesh_name, var)
                except ValueError:
                    logger.info(f"Variable '{var}' not present in output file for mesh '{mesh_name}', skipping")
                    continue
                
                data = group[:]
                logger.debug(f"Data shape for {var} in {mesh_name}: {data.shape}")
                logger.debug(f"Data type: {data.dtype}")
                logger.debug(f"Attributes: {dict(group.attrs)}")
                
                if data.ndim == 2 and data.shape[0] == 2:
                    # Handle 2D datasets (e.g. Maximum Water Surface)
                    row_variables = group.attrs.get('Row Variables', [b'Value', b'Time'])
                    row_variables = [v.decode('utf-8').strip() if isinstance(v, bytes) else v for v in row_variables]
                    
                    df = pd.DataFrame({
                        "mesh_name": [mesh_name] * data.shape[1],
                        "cell_id" if "Face" not in var else "face_id": range(data.shape[1]),
                        f"{var.lower().replace(' ', '_')}": data[0, :],
                        f"{var.lower().replace(' ', '_')}_time": HdfUtils.convert_timesteps_to_datetimes(
                            data[1, :], start_time, time_unit="days", round_to=round_to
                        )
                    })
                    
                elif data.ndim == 1:
                    # Handle 1D datasets (e.g. Cell Last Iteration)
                    df = pd.DataFrame({
                        "mesh_name": [mesh_name] * len(data),
                        "cell_id" if "Face" not in var else "face_id": range(len(data)),
                        var.lower().replace(' ', '_'): data
                    })
                    
                else:
                    raise ValueError(f"Unexpected data shape for {var} in {mesh_name}. "
                                  f"Got shape {data.shape}")
                
                # Add geometry based on variable type
                if "Face" in var:
                    face_df = HdfMesh.get_mesh_cell_faces(hdf_file)
                    if not face_df.empty:
                        df = df.merge(face_df[['mesh_name', 'face_id', 'geometry']], 
                                    on=['mesh_name', 'face_id'], 
                                    how='left')
                else:
                    cell_df = HdfMesh.get_mesh_cell_points(hdf_file)
                    if not cell_df.empty:
                        df = df.merge(cell_df[['mesh_name', 'cell_id', 'geometry']], 
                                    on=['mesh_name', 'cell_id'], 
                                    how='left')
                
                # Add group attributes as metadata with proper decoding
                df.attrs['mesh_name'] = mesh_name
                for attr_name, attr_value in group.attrs.items():
                    if isinstance(attr_value, bytes):
                        # Decode single byte string
                        decoded_value = attr_value.decode('utf-8')
                    elif isinstance(attr_value, np.ndarray):
                        if attr_value.dtype.kind in {'S', 'a'}:  # Array of byte strings
                            # Decode array of byte strings
                            decoded_value = [v.decode('utf-8') if isinstance(v, bytes) else v for v in attr_value]
                        else:
                            # Convert other numpy arrays to list
                            decoded_value = attr_value.tolist()
                    else:
                        decoded_value = attr_value
                    df.attrs[attr_name] = decoded_value
                
                dfs.append(df)
            
            if not dfs:
                return gpd.GeoDataFrame()
                
            result = pd.concat(dfs, ignore_index=True)
            
            # Convert to GeoDataFrame
            gdf = gpd.GeoDataFrame(result, geometry='geometry')
            
            # Get CRS from HdfUtils
            crs = HdfBase.get_projection(hdf_file)
            if crs:
                gdf.set_crs(crs, inplace=True)
            
            # Combine attributes from all meshes with decoded values
            combined_attrs = {}
            for df in dfs:
                for key, value in df.attrs.items():
                    if key not in combined_attrs:
                        combined_attrs[key] = value
                    elif combined_attrs[key] != value:
                        combined_attrs[key] = f"Multiple values: {combined_attrs[key]}, {value}"
            
            gdf.attrs.update(combined_attrs)
            
            logger.info(f"Processed {len(gdf)} rows of summary output data")
            return gdf
        
        except Exception as e:
            logger.error(f"Error processing summary output data: {e}")
            raise ValueError(f"Error processing summary output data: {e}")

    @staticmethod
    def get_mesh_summary_output_group(hdf_file: h5py.File, mesh_name: str, var: str) -> Union[h5py.Group, h5py.Dataset]:
        """
        Return the HDF group for a given mesh and summary output variable.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Name of the summary output variable.

        Returns:
            Union[h5py.Group, h5py.Dataset]: The HDF group or dataset for the specified mesh and variable.

        Raises:
            ValueError: If the specified group or dataset is not found in the HDF file.
        """
        output_path = f"Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/{mesh_name}/{var}"
        output_item = hdf_file.get(output_path)
        if output_item is None:
            raise ValueError(f"Dataset not found at path '{output_path}'")
        return output_item

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_boundary_conditions_timeseries(hdf_path: Path) -> xr.Dataset:
        """
        Get timeseries output for all boundary conditions as a single combined xarray Dataset.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            xr.Dataset: Dataset containing all boundary condition data with:
                - Dimensions: time, bc_name (boundary condition name), face_id
                - Variables: stage, flow, flow_per_face, stage_per_face
                - Coordinates and attributes preserving original metadata

        Example:
            >>> bc_data = HdfResultsMesh.get_boundary_conditions_timeseries_combined(hdf_path)
            >>> print(bc_data)
            >>> # Plot flow for all boundary conditions
            >>> bc_data.flow.plot(x='time', hue='bc_name')
            >>> # Extract data for a specific boundary condition
            >>> upstream_data = bc_data.sel(bc_name='Upstream Inflow')
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Get the base path and check if boundary conditions exist
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                bc_base_path = f"{base_path}/Boundary Conditions"
                
                if bc_base_path not in hdf_file:
                    logger.warning(f"No boundary conditions found in HDF file")
                    return xr.Dataset()
                
                # Get timestamps
                start_time = HdfBase.get_simulation_start_time(hdf_file)
                time_data = hdf_file[f"{base_path}/Time"][:]
                timestamps = HdfUtils.convert_timesteps_to_datetimes(time_data, start_time)
                
                # Get all boundary condition names (excluding those with " - Flow per Face" or " - Stage per Face" suffix)
                bc_names = [name for name in hdf_file[bc_base_path].keys() 
                        if " - Flow per Face" not in name and " - Stage per Face" not in name]
                
                if not bc_names:
                    logger.warning(f"No boundary conditions found in HDF file")
                    return xr.Dataset()
                
                # Initialize arrays for main stage and flow data
                num_timesteps = len(timestamps)
                num_bcs = len(bc_names)
                
                stage_data = np.full((num_timesteps, num_bcs), np.nan)
                flow_data = np.full((num_timesteps, num_bcs), np.nan)
                
                # Dictionary to store face-specific data
                face_data = {
                    'flow_per_face': {},
                    'stage_per_face': {}
                }
                
                # Extract metadata from all boundary conditions
                bc_metadata = {}
                
                # Process each boundary condition
                for bc_idx, bc_name in enumerate(bc_names):
                    bc_path = f"{bc_base_path}/{bc_name}"
                    
                    try:
                        # Extract main boundary data
                        bc_data = hdf_file[bc_path][:]
                        bc_attrs = dict(hdf_file[bc_path].attrs)
                        
                        # Store metadata
                        bc_metadata[bc_name] = {
                            k: v.decode('utf-8') if isinstance(v, bytes) else v 
                            for k, v in bc_attrs.items()
                        }
                        
                        # Get column indices for Stage and Flow
                        if 'Columns' in bc_attrs:
                            columns = [col.decode('utf-8') if isinstance(col, bytes) else col 
                                    for col in bc_attrs['Columns']]
                            
                            stage_idx = columns.index('Stage') if 'Stage' in columns else None
                            flow_idx = columns.index('Flow') if 'Flow' in columns else None
                            
                            if stage_idx is not None:
                                stage_data[:, bc_idx] = bc_data[:, stage_idx]
                            if flow_idx is not None:
                                flow_data[:, bc_idx] = bc_data[:, flow_idx]
                        
                        # Extract Flow per Face data
                        flow_face_path = f"{bc_path} - Flow per Face"
                        if flow_face_path in hdf_file:
                            flow_face_data = hdf_file[flow_face_path][:]
                            flow_face_attrs = dict(hdf_file[flow_face_path].attrs)
                            
                            # Get face IDs
                            face_ids = flow_face_attrs.get('Faces', [])
                            if isinstance(face_ids, np.ndarray):
                                face_ids = face_ids.tolist()
                            else:
                                face_ids = list(range(flow_face_data.shape[1]))
                            
                            face_data['flow_per_face'][bc_name] = {
                                'data': flow_face_data,
                                'faces': face_ids,
                                'attrs': {
                                    k: v.decode('utf-8') if isinstance(v, bytes) else v 
                                    for k, v in flow_face_attrs.items()
                                }
                            }
                        
                        # Extract Stage per Face data
                        stage_face_path = f"{bc_path} - Stage per Face"
                        if stage_face_path in hdf_file:
                            stage_face_data = hdf_file[stage_face_path][:]
                            stage_face_attrs = dict(hdf_file[stage_face_path].attrs)
                            
                            # Get face IDs
                            face_ids = stage_face_attrs.get('Faces', [])
                            if isinstance(face_ids, np.ndarray):
                                face_ids = face_ids.tolist()
                            else:
                                face_ids = list(range(stage_face_data.shape[1]))
                            
                            face_data['stage_per_face'][bc_name] = {
                                'data': stage_face_data,
                                'faces': face_ids,
                                'attrs': {
                                    k: v.decode('utf-8') if isinstance(v, bytes) else v 
                                    for k, v in stage_face_attrs.items()
                                }
                            }
                    
                    except Exception as e:
                        logger.warning(f"Error processing boundary condition '{bc_name}': {str(e)}")
                        continue
                
                # Create base dataset with stage and flow data
                ds = xr.Dataset(
                    data_vars={
                        'stage': xr.DataArray(
                            stage_data,
                            dims=['time', 'bc_name'],
                            coords={
                                'time': timestamps,
                                'bc_name': bc_names
                            },
                            attrs={'description': 'Water surface elevation at boundary condition'}
                        ),
                        'flow': xr.DataArray(
                            flow_data,
                            dims=['time', 'bc_name'],
                            coords={
                                'time': timestamps,
                                'bc_name': bc_names
                            },
                            attrs={'description': 'Flow at boundary condition'}
                        )
                    },
                    attrs={
                        'source': 'HEC-RAS HDF Boundary Conditions',
                        'start_time': start_time
                    }
                )
                
                # Add metadata as coordinates
                for key in bc_metadata[bc_names[0]]:
                    if key != 'Columns':  # Skip Columns attribute as it's used for Stage/Flow
                        try:
                            values = [bc_metadata[bc].get(key, '') for bc in bc_names]
                            ds = ds.assign_coords({f'{key.lower()}': ('bc_name', values)})
                        except Exception as e:
                            logger.debug(f"Could not add metadata coordinate '{key}': {str(e)}")
                
                # Add face-specific data variables if available
                if face_data['flow_per_face']:
                    # First determine the maximum number of faces across all BCs
                    all_flow_faces = set()
                    for bc_name in face_data['flow_per_face']:
                        all_flow_faces.update(face_data['flow_per_face'][bc_name]['faces'])
                    
                    # Create a merged array with NaN values for missing faces
                    all_flow_faces = sorted(list(all_flow_faces))
                    flow_face_data = np.full((num_timesteps, num_bcs, len(all_flow_faces)), np.nan)
                    
                    # Fill in the data where available
                    for bc_idx, bc_name in enumerate(bc_names):
                        if bc_name in face_data['flow_per_face']:
                            bc_faces = face_data['flow_per_face'][bc_name]['faces']
                            bc_data = face_data['flow_per_face'][bc_name]['data']
                            
                            for face_idx, face_id in enumerate(bc_faces):
                                if face_id in all_flow_faces:
                                    target_idx = all_flow_faces.index(face_id)
                                    flow_face_data[:, bc_idx, target_idx] = bc_data[:, face_idx]
                    
                    # Add to the dataset
                    ds['flow_per_face'] = xr.DataArray(
                        flow_face_data,
                        dims=['time', 'bc_name', 'face_id'],
                        coords={
                            'time': timestamps,
                            'bc_name': bc_names,
                            'face_id': all_flow_faces
                        },
                        attrs={'description': 'Flow per face at boundary condition'}
                    )
                
                # Similar approach for stage per face
                if face_data['stage_per_face']:
                    all_stage_faces = set()
                    for bc_name in face_data['stage_per_face']:
                        all_stage_faces.update(face_data['stage_per_face'][bc_name]['faces'])
                    
                    all_stage_faces = sorted(list(all_stage_faces))
                    stage_face_data = np.full((num_timesteps, num_bcs, len(all_stage_faces)), np.nan)
                    
                    for bc_idx, bc_name in enumerate(bc_names):
                        if bc_name in face_data['stage_per_face']:
                            bc_faces = face_data['stage_per_face'][bc_name]['faces']
                            bc_data = face_data['stage_per_face'][bc_name]['data']
                            
                            for face_idx, face_id in enumerate(bc_faces):
                                if face_id in all_stage_faces:
                                    target_idx = all_stage_faces.index(face_id)
                                    stage_face_data[:, bc_idx, target_idx] = bc_data[:, face_idx]
                    
                    ds['stage_per_face'] = xr.DataArray(
                        stage_face_data,
                        dims=['time', 'bc_name', 'face_id'],
                        coords={
                            'time': timestamps,
                            'bc_name': bc_names,
                            'face_id': all_stage_faces
                        },
                        attrs={'description': 'Water surface elevation per face at boundary condition'}
                    )
                
                return ds
                
        except Exception as e:
            logger.error(f"Error getting all boundary conditions timeseries: {str(e)}")
            return xr.Dataset()