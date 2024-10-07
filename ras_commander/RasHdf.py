"""
RasHdf Module

This module provides utilities for working with RESULTS (Plan) HDF files in HEC-RAS projects.
It contains the RasHdf class, which offers various static methods for extracting,
analyzing, and manipulating data from HEC-RAS RESULTS HDF files.

Note:
    This method is decorated with @hdf_operation, which handles the opening and closing of the HDF file.
    The decorator should be used for all methods that directly interact with HDF files.
    It ensures proper file handling and error management.

    When using the @hdf_operation decorator:
    - The method receives an open h5py.File object as its first argument after 'cls'.
    - Error handling for file operations is managed by the decorator.
    - The HDF file is automatically closed after the method execution.

    Methods without this decorator must manually handle file opening, closing, and error management.
    Failure to use the decorator or properly manage the file can lead to resource leaks or file access errors.

Example:
    @classmethod
    @hdf_operation
    def example_method(cls, hdf_file: h5py.File, other_args):
        # Method implementation using hdf_file
        
This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).
3. Obtain the logger using: logger = logging.getLogger(__name__)

Example:
    @log_call
    def my_function():
        logger = logging.getLogger(__name__)
        logger.debug("Additional debug information")
        # Function logic here
"""
import h5py
import numpy as np
import pandas as pd
from typing import Union, List, Optional, Dict, Tuple, Any, Callable
from scipy.spatial import KDTree
from pathlib import Path
from datetime import datetime
import logging
from functools import wraps
from .RasPrj import RasPrj, ras, init_ras_project

# If you're using RasPrj in type hints, you might need to use string literals to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .RasPrj import RasPrj
from ras_commander import get_logger
from ras_commander.logging_config import log_call

logger = get_logger(__name__)

class RasHdf:
    """
    A utility class for working with HDF files in HEC-RAS projects.

    This class provides static methods for various operations on HDF files,
    including listing paths, extracting data, and performing analyses on
    HEC-RAS project data stored in HDF format.
    """
    
    
    @staticmethod
    def hdf_operation(func):
        """
        A decorator for HDF file operations in the RasHdf class.

        This decorator wraps methods that perform operations on HDF files. It handles:
        1. Resolving the HDF filename from various input types.
        2. Opening and closing the HDF file.
        3. Error handling and logging.
        4. Applying the decorated function as a class method.

        Args:
            func (Callable): The function to be decorated.

        Returns:
            Callable: A wrapped version of the input function as a class method.

        Raises:
            ValueError: If the HDF file is not found.

        Usage:
            @RasHdf.hdf_operation
            def some_hdf_method(cls, hdf_file, ...):
                # Method implementation
        """
        @wraps(func)
        def wrapper(cls, hdf_input: Union[str, Path], *args: Any, **kwargs: Any) -> Any:
            from ras_commander import ras  # Import here to avoid circular import
            ras_obj = kwargs.pop('ras_object', None) or ras
            try:
                hdf_filename = cls._get_hdf_filename(hdf_input, ras_obj)
                if hdf_filename is None:
                    raise ValueError(f"HDF file {hdf_input} not found. Use a try-except block to catch this error.")
                with h5py.File(hdf_filename, 'r') as hdf_file:
                    return func(cls, hdf_file, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                return None
        return classmethod(wrapper)

    
    @classmethod
    @log_call
    def get_runtime_data(cls, hdf_input: Union[str, Path], ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract runtime and compute time data from a single HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing runtime and compute time data, or None if data extraction fails.

        Example:
            >>> runtime_df = RasHdf.get_runtime_data("path/to/file.hdf")
            >>> if runtime_df is not None:
            ...     print(runtime_df.head())
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            logger.info(f"Extracting Plan Information from: {Path(hdf_file.filename).name}")
            plan_info = hdf_file.get('/Plan Data/Plan Information')
            if plan_info is None:
                logger.warning("Group '/Plan Data/Plan Information' not found.")
                return None

            plan_name = plan_info.attrs.get('Plan Name', 'Unknown')
            plan_name = plan_name.decode('utf-8') if isinstance(plan_name, bytes) else plan_name
            logger.info(f"Plan Name: {plan_name}")

            start_time_str = plan_info.attrs.get('Simulation Start Time', 'Unknown')
            end_time_str = plan_info.attrs.get('Simulation End Time', 'Unknown')
            start_time_str = start_time_str.decode('utf-8') if isinstance(start_time_str, bytes) else start_time_str
            end_time_str = end_time_str.decode('utf-8') if isinstance(end_time_str, bytes) else end_time_str

            start_time = datetime.strptime(start_time_str, "%d%b%Y %H:%M:%S")
            end_time = datetime.strptime(end_time_str, "%d%b%Y %H:%M:%S")
            simulation_duration = end_time - start_time
            simulation_hours = simulation_duration.total_seconds() / 3600

            logger.info(f"Simulation Start Time: {start_time_str}")
            logger.info(f"Simulation End Time: {end_time_str}")
            logger.info(f"Simulation Duration (hours): {simulation_hours}")

            compute_processes = hdf_file.get('/Results/Summary/Compute Processes')
            if compute_processes is None:
                logger.warning("Dataset '/Results/Summary/Compute Processes' not found.")
                return None

            process_names = [name.decode('utf-8') for name in compute_processes['Process'][:]]
            filenames = [filename.decode('utf-8') for filename in compute_processes['Filename'][:]]
            completion_times = compute_processes['Compute Time (ms)'][:]

            compute_processes_df = pd.DataFrame({
                'Process': process_names,
                'Filename': filenames,
                'Compute Time (ms)': completion_times,
                'Compute Time (s)': completion_times / 1000,
                'Compute Time (hours)': completion_times / (1000 * 3600)
            })

            logger.debug("Compute processes DataFrame:")
            logger.debug(compute_processes_df)

            compute_processes_summary = {
                'Plan Name': [plan_name],
                'File Name': [Path(hdf_file.filename).name],
                'Simulation Start Time': [start_time_str],
                'Simulation End Time': [end_time_str],
                'Simulation Duration (s)': [simulation_duration.total_seconds()],
                'Simulation Time (hr)': [simulation_hours],
                'Completing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Geometry']['Compute Time (hours)'].values[0] if 'Completing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Preprocessing Geometry (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Preprocessing Geometry']['Compute Time (hours)'].values[0] if 'Preprocessing Geometry' in compute_processes_df['Process'].values else 'N/A'],
                'Completing Event Conditions (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Completing Event Conditions']['Compute Time (hours)'].values[0] if 'Completing Event Conditions' in compute_processes_df['Process'].values else 'N/A'],
                'Unsteady Flow Computations (hr)': [compute_processes_df[compute_processes_df['Process'] == 'Unsteady Flow Computations']['Compute Time (hours)'].values[0] if 'Unsteady Flow Computations' in compute_processes_df['Process'].values else 'N/A'],
                'Complete Process (hr)': [compute_processes_df['Compute Time (hours)'].sum()]
            }

            compute_processes_summary['Unsteady Flow Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Unsteady Flow Computations (hr)'][0] if compute_processes_summary['Unsteady Flow Computations (hr)'][0] != 'N/A' else 'N/A']
            compute_processes_summary['Complete Process Speed (hr/hr)'] = [simulation_hours / compute_processes_summary['Complete Process (hr)'][0] if compute_processes_summary['Complete Process (hr)'][0] != 'N/A' else 'N/A']

            compute_summary_df = pd.DataFrame(compute_processes_summary)
            logger.debug("Compute summary DataFrame:")
            logger.debug(compute_summary_df)

            return compute_summary_df

    # List 2D Flow Area Groups (needed for later functions that extract specific datasets)
    
    @classmethod
    @log_call
    def get_2d_flow_area_names(cls, hdf_input: Union[str, Path], ras_object=None) -> Optional[List[str]]:
        """
        List 2D Flow Area names from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[List[str]]: List of 2D Flow Area names, or None if no 2D Flow Areas are found.

        Raises:
            ValueError: If no 2D Flow Areas are found in the HDF file.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            if 'Geometry/2D Flow Areas' in hdf_file:
                group = hdf_file['Geometry/2D Flow Areas']
                group_names = [name for name in group.keys() if isinstance(group[name], h5py.Group)]
                if not group_names:
                    logger.warning("No 2D Flow Areas found in the HDF file")
                    return None
                logger.info(f"Found {len(group_names)} 2D Flow Areas")
                return group_names
            else:
                logger.warning("No 2D Flow Areas found in the HDF file")
                return None
    @classmethod
    @log_call
    def get_2d_flow_area_attributes(cls, hdf_input: Union[str, Path], ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract 2D Flow Area Attributes from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing 2D Flow Area Attributes, or None if attributes are not found.

        Example:
            >>> attributes_df = RasHdf.get_2d_flow_area_attributes("path/to/file.hdf")
            >>> if attributes_df is not None:
            ...     print(attributes_df.head())
            ... else:
            ...     print("No 2D Flow Area attributes found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            if 'Geometry/2D Flow Areas/Attributes' in hdf_file:
                attributes = hdf_file['Geometry/2D Flow Areas/Attributes'][()]
                attributes_df = pd.DataFrame(attributes)
                return attributes_df
            else:
                return None
            
    @classmethod
    @log_call
    def get_cell_info(cls, hdf_input: Union[str, Path], ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract Cell Info from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Cell Info, or None if the data is not found.

        Example:
            >>> cell_info_df = RasHdf.get_cell_info("path/to/file.hdf")
            >>> if cell_info_df is not None:
            ...     print(cell_info_df.head())
            ... else:
            ...     print("No Cell Info found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            cell_info_df = cls._extract_dataset(hdf_file, 'Geometry/2D Flow Areas/Cell Info', ['Start', 'End'])
            return cell_info_df
        
    @classmethod
    @log_call
    def get_cell_points(cls, hdf_input: Union[str, Path], ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract Cell Points from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Cell Points, or None if the data is not found.

        Example:
            >>> cell_points_df = RasHdf.get_cell_points("path/to/file.hdf")
            >>> if cell_points_df is not None:
            ...     print(cell_points_df.head())
            ... else:
            ...     print("No Cell Points found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            cell_points_df = cls._extract_dataset(hdf_file, 'Geometry/2D Flow Areas/Cell Points', ['X', 'Y'])
            return cell_points_df
    
    @classmethod
    @log_call
    def get_polygon_info_and_parts(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Polygon Info and Parts from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]: 
                Two DataFrames containing Polygon Info and Polygon Parts respectively, 
                or None for each if the corresponding data is not found.

        Example:
            >>> polygon_info_df, polygon_parts_df = RasHdf.get_polygon_info_and_parts("path/to/file.hdf")
            >>> if polygon_info_df is not None and polygon_parts_df is not None:
            ...     print("Polygon Info:")
            ...     print(polygon_info_df.head())
            ...     print("Polygon Parts:")
            ...     print(polygon_parts_df.head())
            ... else:
            ...     print("Polygon data not found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)
            base_path = f'Geometry/2D Flow Areas'
            polygon_info_df = cls._extract_dataset(hdf_file, f'{base_path}/Polygon Info', ['Column1', 'Column2', 'Column3', 'Column4'])
            polygon_parts_df = cls._extract_dataset(hdf_file, f'{base_path}/Polygon Parts', ['Start', 'Count'])
            return polygon_info_df, polygon_parts_df

    @classmethod
    @log_call
    def get_polygon_points(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract Polygon Points from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Polygon Points, or None if the data is not found.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)
            polygon_points_path = f'Geometry/2D Flow Areas/Polygon Points'
            if polygon_points_path in hdf_file:
                polygon_points = hdf_file[polygon_points_path][()]
                polygon_points_df = pd.DataFrame(polygon_points, columns=['X', 'Y'])
                return polygon_points_df
            else:
                return None
            
    @classmethod
    @log_call
    def get_cells_center_data(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Cells Center Coordinates and Manning's n from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]: 
                Two DataFrames containing Cells Center Coordinates and Manning's n respectively, 
                or None for each if the corresponding data is not found.

        Example:
            >>> coords_df, mannings_df = RasHdf.get_cells_center_data("path/to/file.hdf")
            >>> if coords_df is not None and mannings_df is not None:
            ...     print("Cell Center Coordinates:")
            ...     print(coords_df.head())
            ...     print("Manning's n:")
            ...     print(mannings_df.head())
            ... else:
            ...     print("Cell center data not found")
        """
        try:
            hdf_filename = cls._get_hdf_filename(hdf_input, ras_object)
            with h5py.File(hdf_filename, 'r') as hdf_file:
                area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)
                base_path = f'Geometry/2D Flow Areas/{area_name}'
                cells_center_coord_path = f'{base_path}/Cells Center Coordinate'
                cells_manning_n_path = f'{base_path}/Cells Center Manning\'s n'
                cells_center_coord_df = cls._extract_dataset(hdf_file, cells_center_coord_path, ['X', 'Y'])
                cells_manning_n_df = cls._extract_dataset(hdf_file, cells_manning_n_path, ['Manning\'s n'])
                return cells_center_coord_df, cells_manning_n_df
        except Exception as e:
            return None, None

    @classmethod
    @log_call
    def get_faces_area_elevation_data(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract Faces Area Elevation Values from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Faces Area Elevation Values, or None if the data is not found.

        Example:
            >>> elevation_df = RasHdf.get_faces_area_elevation_data("path/to/file.hdf")
            >>> if elevation_df is not None:
            ...     print(elevation_df.head())
            ... else:
            ...     print("No Faces Area Elevation data found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)
            base_path = f'Geometry/2D Flow Areas/{area_name}'
            area_elev_values_path = f'{base_path}/Faces Area Elevation Values'
            
            if area_elev_values_path in hdf_file:
                area_elev_values = hdf_file[area_elev_values_path][()]
                area_elev_values_df = pd.DataFrame(area_elev_values, columns=['Elevation', 'Area', 'Wetted Perimeter', 'Manning\'s n'])
                return area_elev_values_df
            else:
                return None

    @classmethod
    @log_call
    def get_faces_indexes(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Faces Cell and FacePoint Indexes from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]: 
                Two DataFrames containing Faces Cell Indexes and FacePoint Indexes respectively, 
                or None for each if the corresponding data is not found.

        Example:
            >>> cell_indexes_df, facepoint_indexes_df = RasHdf.get_faces_indexes("path/to/file.hdf")
            >>> if cell_indexes_df is not None and facepoint_indexes_df is not None:
            ...     print("Faces Cell Indexes:")
            ...     print(cell_indexes_df.head())
            ...     print("Faces FacePoint Indexes:")
            ...     print(facepoint_indexes_df.head())
            ... else:
            ...     print("Faces indexes data not found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}'
            cell_indexes_path = f'{base_path}/Faces Cell Indexes'
            facepoint_indexes_path = f'{base_path}/Faces FacePoint Indexes'
            
            cell_indexes_df = cls._extract_dataset(hdf_file, cell_indexes_path, ['Left Cell', 'Right Cell'])
            facepoint_indexes_df = cls._extract_dataset(hdf_file, facepoint_indexes_path, ['Start FacePoint', 'End FacePoint'])

            return cell_indexes_df, facepoint_indexes_df
        
    @classmethod
    @log_call
    def get_faces_elevation_data(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Faces Low Elevation Centroid and Minimum Elevation from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
                DataFrames containing Faces Low Elevation Centroid and Minimum Elevation.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}'
            low_elev_centroid = cls._extract_dataset(hdf_file, f'{base_path}/Faces Low Elevation Centroid', ['Low Elevation Centroid'])
            min_elevation = cls._extract_dataset(hdf_file, f'{base_path}/Faces Minimum Elevation', ['Minimum Elevation'])

            return low_elev_centroid, min_elevation
    
    @classmethod
    @log_call
    def get_faces_vector_data(
        cls,
        hdf_input: Union[str, Path],
        area_name: Optional[str] = None,
        ras_object=None
    ) -> Optional[pd.DataFrame]:
        """
        Extract Faces NormalUnitVector and Length from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Faces NormalUnitVector and Length.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}'
            vector_data = cls._extract_dataset(hdf_file, f'{base_path}/Faces NormalUnitVector and Length', ['NormalX', 'NormalY', 'Length'])

            return vector_data

    @classmethod
    @log_call
    def get_faces_perimeter_data(
        cls,
        hdf_input: Union[str, Path],
        area_name: Optional[str] = None,
        ras_object=None
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Faces Perimeter Info and Values from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
                DataFrames containing Faces Perimeter Info and Values.

        Raises:
            ValueError: If no HDF file is found for the given plan number.
            FileNotFoundError: If the specified HDF file does not exist.

        Example:
            >>> perimeter_info_df, perimeter_values_df = RasHdf.get_faces_perimeter_data("path/to/file.hdf")
            >>> if perimeter_info_df is not None and perimeter_values_df is not None:
            ...     print("Perimeter Info:")
            ...     print(perimeter_info_df.head())
            ...     print("Perimeter Values:")
            ...     print(perimeter_values_df.head())
            ... else:
            ...     print("Perimeter data not found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}'
            perimeter_info = cls._extract_dataset(hdf_file, f'{base_path}/Faces Perimeter Info', ['Start', 'Count'])
            perimeter_values = cls._extract_dataset(hdf_file, f'{base_path}/Faces Perimeter Values', ['X', 'Y'])

            return perimeter_info, perimeter_values

    @classmethod
    @log_call
    def get_infiltration_data(
        cls,
        hdf_input: Union[str, Path],
        area_name: Optional[str] = None,
        ras_object=None
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Infiltration Data from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
                DataFrames containing various Infiltration Data
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}/Infiltration'
            
            cell_classifications = cls._extract_dataset(hdf_file, f'{base_path}/Cell Center Classifications', ['Cell Classification'])
            face_classifications = cls._extract_dataset(hdf_file, f'{base_path}/Face Center Classifications', ['Face Classification'])
            initial_deficit = cls._extract_dataset(hdf_file, f'{base_path}/Initial Deficit', ['Initial Deficit'])
            maximum_deficit = cls._extract_dataset(hdf_file, f'{base_path}/Maximum Deficit', ['Maximum Deficit'])
            potential_percolation_rate = cls._extract_dataset(hdf_file, f'{base_path}/Potential Percolation Rate', ['Potential Percolation Rate'])

            return cell_classifications, face_classifications, initial_deficit, maximum_deficit, potential_percolation_rate
        
    @classmethod
    @log_call
    def get_percent_impervious_data(
        cls,
        hdf_input: Union[str, Path],
        area_name: Optional[str] = None,
        ras_object=None
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Extract Percent Impervious Data from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
                DataFrames containing Cell Classifications, Face Classifications, and Percent Impervious Data
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            base_path = f'Geometry/2D Flow Areas/{area_name}/Percent Impervious'
            cell_classifications = cls._extract_dataset(hdf_file, f'{base_path}/Cell Center Classifications', ['Cell Classification'])
            face_classifications = cls._extract_dataset(hdf_file, f'{base_path}/Face Center Classifications', ['Face Classification'])
            percent_impervious = cls._extract_dataset(hdf_file, f'{base_path}/Percent Impervious', ['Percent Impervious'])

            return cell_classifications, face_classifications, percent_impervious
