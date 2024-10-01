"""
RasHdf Module

This module provides utilities for working with HDF files in HEC-RAS projects.
It contains the RasHdf class, which offers various static methods for extracting,
analyzing, and manipulating data from HEC-RAS HDF files.

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

    @classmethod
    @log_call
    def get_perimeter_data(
        cls,
        hdf_input: Union[str, Path],
        area_name: Optional[str] = None,
        ras_object=None
    ) -> Optional[pd.DataFrame]:
        """
        Extract Perimeter Data from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area to extract data from.
                If None, uses the first 2D Area Name found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: DataFrame containing Perimeter Data

        Example:
            >>> perimeter_df = RasHdf.get_perimeter_data("path/to/file.hdf")
            >>> if perimeter_df is not None:
            ...     print(perimeter_df.head())
            ... else:
            ...     print("Perimeter data not found")
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            area_name = cls._get_area_name(hdf_file, area_name, hdf_file.filename)

            perimeter_path = f'Geometry/2D Flow Areas/{area_name}/Perimeter'
            perimeter_df = cls._extract_dataset(hdf_file, perimeter_path, ['X', 'Y'])

            return perimeter_df

    @classmethod
    @log_call
    def _get_area_name(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> str:
        """
        Get the 2D Flow Area name from the HDF file.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): The provided area name, if any.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            str: The 2D Flow Area name.

        Raises:
            ValueError: If no 2D Flow Areas are found in the HDF file or if the specified area name is not found.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            if area_name is None:
                area_names = [name for name in hdf_file['Geometry/2D Flow Areas'].keys() if isinstance(hdf_file['Geometry/2D Flow Areas'][name], h5py.Group)]
                if not area_names:
                    raise ValueError("No 2D Flow Areas found in the HDF file")
                area_name = area_names[0]
            else:
                if area_name not in hdf_file['Geometry/2D Flow Areas']:
                    raise ValueError(f"2D Flow Area '{area_name}' not found in the HDF file")
        return area_name

    @classmethod
    @log_call
    def _extract_dataset(cls, hdf_input: Union[str, Path], dataset_path: str, column_names: List[str], ras_object=None) -> Optional[pd.DataFrame]:
        """
        Extract a dataset from the HDF file and convert it to a DataFrame.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            dataset_path (str): The path to the dataset within the HDF file.
            column_names (List[str]): The names to assign to the DataFrame columns.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[pd.DataFrame]: The extracted data as a DataFrame, or None if the dataset is not found.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            try:
                dataset = hdf_file[dataset_path][()]
                df = pd.DataFrame(dataset, columns=column_names)
                return df
            except KeyError:
                return None

    @classmethod
    @log_call
    def read_hdf_to_dataframe(cls, hdf_input: Union[str, Path], dataset_path: str, fill_value: Union[int, float, str] = -9999, ras_object=None) -> pd.DataFrame:
        """
        Reads an HDF5 dataset and converts it into a pandas DataFrame, handling byte strings and missing values.

        Args:
            hdf_input (Union[str, Path]): Path to the HDF file or plan number.
            dataset_path (str): Path to the dataset within the HDF file.
            fill_value (Union[int, float, str], optional): The value to use for filling missing data. Defaults to -9999.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: The resulting DataFrame with byte strings decoded and missing values replaced.

        Raises:
            KeyError: If the dataset is not found in the HDF file.
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            try:
                hdf_dataset = hdf_file[dataset_path]
                hdf_dataframe = cls.convert_to_dataframe_array(hdf_dataset)
                byte_columns = [col for col in hdf_dataframe.columns if isinstance(hdf_dataframe[col].iloc[0], (bytes, bytearray))]
                
                hdf_dataframe[byte_columns] = hdf_dataframe[byte_columns].applymap(lambda x: x.decode('utf-8') if isinstance(x, (bytes, bytearray)) else x)
                hdf_dataframe = hdf_dataframe.replace({fill_value: np.NaN})
                
                return hdf_dataframe
            except KeyError:
                raise
        
    @classmethod
    @log_call
    def get_group_attributes_as_df(cls, hdf_input: Union[str, Path], group_path: str, ras_object=None) -> pd.DataFrame:
        """
        Convert attributes inside a given HDF group to a DataFrame.

        Args:
            hdf_input (Union[str, Path]): Path to the HDF file or plan number.
            group_path (str): Path of the group in the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame of all attributes in the specified group with their properties.

        Raises:
            KeyError: If the specified group_path is not found in the file.

        Example:
            >>> attributes_df = RasHdf.get_group_attributes_as_df("path/to/file.hdf", "/Results/Unsteady/Output")
            >>> print(attributes_df.head())
        """
        hdf_filename = cls._get_hdf_filename(hdf_input, ras_object)
        
        with h5py.File(hdf_filename, 'r') as hdf_file:
            try:
                group = hdf_file[group_path]
                attributes = []
                for attr in group.attrs:
                    value = group.attrs[attr]
                    attr_info = {
                        'Attribute': attr,
                        'Value': value,
                        'Type': type(value).__name__,
                        'Shape': value.shape if isinstance(value, np.ndarray) else None,
                        'Size': value.size if isinstance(value, np.ndarray) else None,
                        'Dtype': value.dtype if isinstance(value, np.ndarray) else None
                    }
                    if isinstance(value, bytes):
                        attr_info['Value'] = value.decode('utf-8')
                    elif isinstance(value, np.ndarray):
                        if value.dtype.kind == 'S':
                            attr_info['Value'] = [v.decode('utf-8') for v in value]
                        elif value.dtype.kind in ['i', 'f', 'u']:
                            attr_info['Value'] = value.tolist()
                    attributes.append(attr_info)
                
                return pd.DataFrame(attributes)
            except KeyError:
                logger.critical(f"Group path '{group_path}' not found in HDF file '{hdf_filename}'")

    # Last functions from PyHMT2D:

    from ras_commander.logging_config import log_call

    @classmethod
    @log_call
    def get_2d_area_solution_times(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[np.ndarray]:
        """
        Retrieve solution times for a specified 2D Flow Area.
        
        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, uses the first area found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[np.ndarray]: Array of solution times, or None if not found.
        
        Example:
            >>> solution_times = RasHdf.get_2d_area_solution_times("03", area_name="Area1")
            >>> print(solution_times)
            [0.0, 0.5, 1.0, ...]
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            try:
                solution_times = np.array(
                    hdf_file['Results']['Unsteady']['Output']['Output Blocks']
                    ['Base Output']['Unsteady Time Series']['Time']
                )
                return solution_times
            except KeyError:
                return None

    @classmethod
    @log_call
    def get_2d_area_solution_time_dates(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[np.ndarray]:
        """
        Retrieve solution time dates for a specified 2D Flow Area.
        
        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, uses the first area found.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[np.ndarray]: Array of solution time dates, or None if not found.
        
        Example:
            >>> solution_time_dates = RasHdf.get_2d_area_solution_time_dates("03", area_name="Area1")
            >>> print(solution_time_dates)
            ['2024-01-01T00:00:00', '2024-01-01T00:30:00', ...]
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            try:
                solution_time_dates = np.array(
                    hdf_file['Results']['Unsteady']['Output']['Output Blocks']
                    ['Base Output']['Unsteady Time Series']['Time Date Stamp']
                )
                return solution_time_dates
            except KeyError:
                return None

    @classmethod
    @log_call
    def load_2d_area_solutions(
        cls,
        hdf_file: h5py.File,
        ras_object=None
    ) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Load 2D Area Solutions (Water Surface Elevation and Face Normal Velocity) from the HDF file
        and provide them as pandas DataFrames.

        **Note:** 
            - This function has only been tested with HEC-RAS version 6.5.
            - Ensure that the HDF file structure matches the expected paths.

        Args:
            hdf_file (h5py.File): An open HDF5 file object.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[Dict[str, pd.DataFrame]]: A dictionary containing:
                - 'solution_times': DataFrame of solution times.
                - For each 2D Flow Area:
                    - '{Area_Name}_WSE': Water Surface Elevation DataFrame.
                    - '{Area_Name}_Face_Velocity': Face Normal Velocity DataFrame.
        """
        try:
            solution_times_path = '/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time'
            if solution_times_path not in hdf_file:
                return None

            solution_times = hdf_file[solution_times_path][()]
            solution_times_df = pd.DataFrame({
                'Time_Step': solution_times
            })

            solutions_dict = {
                'solution_times': solution_times_df
            }

            two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
            if not two_d_area_names:
                return solutions_dict

            for area in two_d_area_names:
                wse_path = f'/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}/Water Surface'
                face_velocity_path = f'/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}/Face Velocity'

                if wse_path not in hdf_file:
                    continue

                wse_data = hdf_file[wse_path][()]
                cell_center_coords_path = f'/Geometry/2D Flow Areas/{area}/Cell Center Coordinate'
                if cell_center_coords_path not in hdf_file:
                    continue

                cell_center_coords = hdf_file[cell_center_coords_path][()]
                if cell_center_coords.shape[0] != wse_data.shape[1]:
                    continue

                wse_df = pd.DataFrame({
                    'Time_Step': np.repeat(solution_times, wse_data.shape[1]),
                    'Cell_ID': np.tile(np.arange(wse_data.shape[1]), wse_data.shape[0]),
                    'X': cell_center_coords[:, 0].repeat(wse_data.shape[0]),
                    'Y': cell_center_coords[:, 1].repeat(wse_data.shape[0]),
                    'WSE': wse_data.flatten()
                })
                solutions_dict[f'{area}_WSE'] = wse_df

                if face_velocity_path not in hdf_file:
                    continue

                face_velocity_data = hdf_file[face_velocity_path][()]
                face_center_coords_path = f'/Geometry/2D Flow Areas/{area}/Face Points Coordinates'
                if face_center_coords_path not in hdf_file:
                    continue

                face_center_coords = hdf_file[face_center_coords_path][()]
                if face_center_coords.shape[0] != face_velocity_data.shape[1]:
                    continue

                face_velocity_df = pd.DataFrame({
                    'Time_Step': np.repeat(solution_times, face_velocity_data.shape[1]),
                    'Face_ID': np.tile(np.arange(face_velocity_data.shape[1]), face_velocity_data.shape[0]),
                    'X': face_center_coords[:, 0].repeat(face_velocity_data.shape[0]),
                    'Y': face_center_coords[:, 1].repeat(face_velocity_data.shape[0]),
                    'Normal_Velocity_ft_s': face_velocity_data.flatten()
                })
                solutions_dict[f'{area}_Face_Velocity'] = face_velocity_df

            return solutions_dict

        except Exception as e:
            return None

    @classmethod
    @log_call
    def get_hdf_paths_with_properties(cls, hdf_input: Union[str, Path], ras_object=None) -> pd.DataFrame:
        """
        List all paths in the HDF file with their properties.

        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            pd.DataFrame: DataFrame of all paths and their properties in the HDF file.

        Example:
            >>> paths_df = RasHdf.get_hdf_paths_with_properties("path/to/file.hdf")
            >>> print(paths_df.head())
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            paths = []
            def visitor_func(name: str, node: h5py.Group) -> None:
                path_info = {
                    "HDF_Path": name,
                    "Type": type(node).__name__,
                    "Shape": getattr(node, "shape", None),
                    "Size": getattr(node, "size", None),
                    "Dtype": getattr(node, "dtype", None)
                }
                paths.append(path_info)
            hdf_file.visititems(visitor_func)
            return pd.DataFrame(paths)
        
    @classmethod
    @log_call
    def build_2d_area_face_hydraulic_information(cls, hdf_input: Union[str, Path, h5py.File], area_name: Optional[str] = None, ras_object=None) -> Optional[List[List[np.ndarray]]]:
        """
        Build face hydraulic information tables (elevation, area, wetted perimeter, Manning's n) for each face in 2D Flow Areas.
        
        Args:
            hdf_input (Union[str, Path, h5py.File]): The HDF5 file path or open HDF5 file object.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, builds for all areas.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[List[List[np.ndarray]]]: Nested lists containing hydraulic information for each face in each 2D Flow Area.
        
        Example:
            >>> hydraulic_info = RasHdf.build_2d_area_face_hydraulic_information("03")
            >>> print(hydraulic_info[0][0])  # First face of first area
            [[Elevation1, Area1, WettedPerim1, ManningN1],
             [Elevation2, Area2, WettedPerim2, ManningN2],
             ...]
        """
        try:
            ras_obj = ras_object if ras_object is not None else ras
            with h5py.File(cls._get_hdf_filename(hdf_input, ras_obj), 'r') as hdf_file:
                two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
                hydraulic_info_table = []

                for area in two_d_area_names:
                    face_elev_info = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Faces Area Elevation Info'])
                    face_elev_values = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Faces Area Elevation Values'])
                    
                    area_hydraulic_info = []
                    for face in face_elev_info:
                        start_row, count = face
                        face_data = face_elev_values[start_row:start_row + count].copy()
                        area_hydraulic_info.append(face_data)
                    
                    hydraulic_info_table.append(area_hydraulic_info)

                return hydraulic_info_table

        except KeyError:
            return None

    @classmethod
    @log_call
    def build_2d_area_face_point_coordinates_list(cls, hdf_input: Union[str, Path, h5py.File], area_name: Optional[str] = None, ras_object=None) -> Optional[List[np.ndarray]]:
        """
        Build a list of face point coordinates for each 2D Flow Area.
        
        Args:
            hdf_input (Union[str, Path, h5py.File]): The HDF5 file path or open HDF5 file object.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, builds for all areas.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[List[np.ndarray]]: List containing arrays of face point coordinates for each 2D Flow Area.
        
        Example:
            >>> face_coords_list = RasHdf.build_2d_area_face_point_coordinates_list("03")
            >>> print(face_coords_list[0])  # Coordinates for first area
            [[X1, Y1], [X2, Y2], ...]
        """
        try:
            with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
                two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
                face_point_coords_list = []

                for area in two_d_area_names:
                    face_points = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Face Points Coordinates'])
                    face_point_coords_list.append(face_points)

                return face_point_coords_list

        except KeyError:
            return None

    @classmethod
    @log_call
    def build_2d_area_face_profile(cls, hdf_input: Union[str, Path, h5py.File], area_name: Optional[str] = None, ras_object=None, n_face_profile_points: int = 10) -> Optional[List[np.ndarray]]:
        """
        Build face profiles representing sub-grid terrain for each face in 2D Flow Areas.
        
        Args:
            hdf_input (Union[str, Path, h5py.File]): The HDF5 file path or open HDF5 file object.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, builds for all areas.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
            n_face_profile_points (int): Number of points to interpolate along each face profile.
        
        Returns:
            Optional[List[np.ndarray]]: List containing arrays of profile points for each face in each 2D Flow Area.
        
        Example:
            >>> face_profiles = RasHdf.build_2d_area_face_profile("03", n_face_profile_points=20)
            >>> print(face_profiles[0][0])  # Profile points for first face of first area
            [[X1, Y1, Z1], [X2, Y2, Z2], ...]
        """
        try:
            with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
                two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
                face_profiles = []

                for area in two_d_area_names:
                    face_faces = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Faces FacePoint Indexes'])
                    face_point_coords = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Face Points Coordinates'])
                    profile_points_all_faces = []

                    for face in face_faces:
                        face_start, face_end = face
                        start_coords = face_point_coords[face_start]
                        end_coords = face_point_coords[face_end]
                        
                        length = cls.horizontal_distance(start_coords, end_coords)
                        stations = np.linspace(0, length, n_face_profile_points, endpoint=True)
                        
                        interpolated_points = np.array([
                            start_coords + (end_coords - start_coords) * i / (n_face_profile_points - 1)
                            for i in range(n_face_profile_points)
                        ])
                        
                        interpolated_points = cls.interpolate_z_coords(interpolated_points)
                        
                        profile_points_all_faces.append(interpolated_points)

                    face_profiles.append(profile_points_all_faces)

                return face_profiles

        except KeyError as e:
            logging.error(f"Error building face profiles: {e}")
            return None

    @classmethod
    @log_call
    def build_face_facepoints(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[List[np.ndarray]]:
        """
        Build face's facepoint list for each 2D Flow Area.
        
        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, builds for all areas.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[List[np.ndarray]]: List containing arrays of face point indexes for each face in each 2D Flow Area.
        
        Example:
            >>> face_facepoints = RasHdf.build_face_facepoints("03")
            >>> print(face_facepoints[0][0])  # FacePoint indexes for first face of first area
            [start_idx, end_idx]
        """
        try:
            with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
                two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
                face_facepoints_list = []

                for area in two_d_area_names:
                    face_facepoints = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Faces FacePoint Indexes'])
                    face_facepoints_list.append(face_facepoints)

                return face_facepoints_list

        except KeyError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error building face facepoints list: {e}")
            return None

    @classmethod
    @log_call
    def build_2d_area_boundaries(cls, hdf_input: Union[str, Path], area_name: Optional[str] = None, ras_object=None) -> Optional[Tuple[int, np.ndarray, List[str], List[str], List[str], np.ndarray, np.ndarray]]:
        """
        Build boundaries with their point lists for each 2D Flow Area.
        
        Args:
            hdf_input (Union[str, Path]): The plan number or full path to the HDF file.
            area_name (Optional[str]): Name of the 2D Flow Area. If None, builds for all areas.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.
        
        Returns:
            Optional[Tuple[int, np.ndarray, List[str], List[str], List[str], np.ndarray, np.ndarray]]:
                Tuple containing total boundaries, boundary IDs, boundary names, associated 2D Flow Area names, boundary types,
                total points per boundary, and boundary point lists.
        
        Example:
            >>> total_boundaries, boundary_ids, boundary_names, flow_area_names, boundary_types, total_points, boundary_points = RasHdf.build_2d_area_boundaries("03")
            >>> print(total_boundaries)
            5
        """
        try:
            with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
                two_d_area_names = cls.get_2d_flow_area_names(hdf_file, ras_object=ras_object)
                total_boundaries = 0
                boundary_ids = []
                boundary_names = []
                flow_area_names = []
                boundary_types = []
                total_points_per_boundary = []
                boundary_points_list = []

                for area in two_d_area_names:
                    boundary_points = np.array(hdf_file[f'Geometry/2D Flow Areas/{area}/Boundary Points'])
                    if boundary_points.size == 0:
                        logger = logging.getLogger(__name__)
                        logger.warning(f"No boundary points found for 2D Flow Area: {area}")
                        continue

                    current_boundary_id = boundary_points[0][0]
                    current_boundary_points = [boundary_points[0][2], boundary_points[0][3]]
                    boundary_id = current_boundary_id

                    for point in boundary_points[1:]:
                        if point[0] == current_boundary_id:
                            current_boundary_points.append(point[3])
                        else:
                            # Save the completed boundary
                            boundary_ids.append(current_boundary_id)
                            boundary_names.append(point[0])  # Assuming boundary name is stored here
                            flow_area_names.append(area)
                            boundary_types.append(point[2])  # Assuming boundary type is stored here
                            total_points_per_boundary.append(len(current_boundary_points))
                            boundary_points_list.append(np.array(current_boundary_points))
                            total_boundaries += 1

                            # Start a new boundary
                            current_boundary_id = point[0]
                            current_boundary_points = [point[2], point[3]]

                    # Save the last boundary
                    boundary_ids.append(current_boundary_id)
                    boundary_names.append(boundary_points[-1][0])  # Assuming boundary name is stored here
                    flow_area_names.append(area)
                    boundary_types.append(boundary_points[-1][2])  # Assuming boundary type is stored here
                    total_points_per_boundary.append(len(current_boundary_points))
                    boundary_points_list.append(np.array(current_boundary_points))
                    total_boundaries += 1

                return (total_boundaries, np.array(boundary_ids), boundary_names, flow_area_names, boundary_types, np.array(total_points_per_boundary), np.array(boundary_points_list))

        except KeyError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error building boundaries: {e}")
            return None

    # Helper Methods for New Functionalities

    @classmethod
    @log_call
    def horizontal_distance(cls, coord1: np.ndarray, coord2: np.ndarray) -> float:
        """
        Calculate the horizontal distance between two coordinate points.
        
        Args:
            coord1 (np.ndarray): First coordinate point [X, Y].
            coord2 (np.ndarray): Second coordinate point [X, Y].
        
        Returns:
            float: Horizontal distance.
        
        Example:
            >>> distance = RasHdf.horizontal_distance([0, 0], [3, 4])
            >>> print(distance)
            5.0
        """
        return np.linalg.norm(coord2 - coord1)

    @classmethod
    @log_call
    def interpolate_z_coords(cls, points: np.ndarray) -> np.ndarray:
        """
        Interpolate Z coordinates for a set of points.
        
        Args:
            points (np.ndarray): Array of points with [X, Y].
        
        Returns:
            np.ndarray: Array of points with [X, Y, Z].
        
        Example:
            >>> interpolated = RasHdf.interpolate_z_coords(np.array([[0,0], [1,1]]))
            >>> print(interpolated)
            [[0, 0, Z0],
             [1, 1, Z1]]
        """
        # Placeholder for actual interpolation logic
        # This should be replaced with the appropriate interpolation method
        z_coords = np.zeros((points.shape[0], 1))  # Assuming Z=0 for simplicity
        return np.hstack((points, z_coords))

    @classmethod
    @log_call
    def extract_string_from_hdf(
        cls,
        hdf_input: Union[str, Path],
        hdf_path: str,
        ras_object: Optional["RasPrj"] = None
    ) -> str:
        """
        Extract string from HDF object at a given path.

        Args:
            hdf_input (Union[str, Path]): Either the plan number or the full path to the HDF file.
            hdf_path (str): Path of the object in the HDF file.
            ras_object (Optional["RasPrj"]): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            str: Extracted string from the specified HDF object.

        Raises:
            ValueError: If no HDF file is found for the given plan number.
            FileNotFoundError: If the specified HDF file does not exist.
            KeyError: If the specified hdf_path is not found in the file.

        Example:
            >>> result = RasHdf.extract_string_from_hdf("path/to/file.hdf", "/Results/Summary/Compute Messages (text)")
            >>> print(result)
        """
        with h5py.File(cls._get_hdf_filename(hdf_input, ras_object), 'r') as hdf_file:
            try:
                hdf_object = hdf_file[hdf_path]
                if isinstance(hdf_object, h5py.Group):
                    return f"Group: {hdf_path}\nContents: {list(hdf_object.keys())}"
                elif isinstance(hdf_object, h5py.Dataset):
                    data = hdf_object[()]
                    if isinstance(data, bytes):
                        return data.decode('utf-8')
                    elif isinstance(data, np.ndarray) and data.dtype.kind == 'S':
                        return [v.decode('utf-8') for v in data]
                    else:
                        return str(data)
                else:
                    return f"Unsupported object type: {type(hdf_object)}"
            except KeyError:
                logger = logging.getLogger(__name__)
                logger.error(f"Path not found: {hdf_path}")
                raise KeyError(f"Path not found: {hdf_path}")

    @classmethod
    @log_call
    def decode_byte_strings(dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Decodes byte strings in a DataFrame to regular string objects.

        This function converts columns with byte-encoded strings (e.g., b'string') into UTF-8 decoded strings.

        Args:
            dataframe (pd.DataFrame): The DataFrame containing byte-encoded string columns.

        Returns:
            pd.DataFrame: The DataFrame with byte strings decoded to regular strings.

        Example:
            >>> df = pd.DataFrame({'A': [b'hello', b'world'], 'B': [1, 2]})
            >>> decoded_df = RasHdf.decode_byte_strings(df)
            >>> print(decoded_df)
                A  B
            0  hello  1
            1  world  2
        """
        str_df = dataframe.select_dtypes(['object'])
        str_df = str_df.stack().str.decode('utf-8').unstack()
        for col in str_df:
            dataframe[col] = str_df[col]
        return dataframe

    @classmethod
    @log_call
    def perform_kdtree_query(
        reference_points: np.ndarray,
        query_points: np.ndarray,
        max_distance: float = 2.0
    ) -> np.ndarray:
        """
        Performs a KDTree query between two datasets and returns indices with distances exceeding max_distance set to -1.

        Args:
            reference_points (np.ndarray): The reference dataset for KDTree.
            query_points (np.ndarray): The query dataset to search against KDTree of reference_points.
            max_distance (float, optional): The maximum distance threshold. Indices with distances greater than this are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices from reference_points that are nearest to each point in query_points. 
                        Indices with distances > max_distance are set to -1.

        Example:
            >>> ref_points = np.array([[0, 0], [1, 1], [2, 2]])
            >>> query_points = np.array([[0.5, 0.5], [3, 3]])
            >>> result = RasHdf.perform_kdtree_query(ref_points, query_points)
            >>> print(result)
            array([ 0, -1])
        """
        dist, snap = KDTree(reference_points).query(query_points, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        return snap

    @classmethod
    @log_call
    def find_nearest_neighbors(points: np.ndarray, max_distance: float = 2.0) -> np.ndarray:
        """
        Creates a self KDTree for dataset points and finds nearest neighbors excluding self, 
        with distances above max_distance set to -1.

        Args:
            points (np.ndarray): The dataset to build the KDTree from and query against itself.
            max_distance (float, optional): The maximum distance threshold. Indices with distances 
                                            greater than max_distance are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices representing the nearest neighbor in points for each point in points. 
                        Indices with distances > max_distance or self-matches are set to -1.

        Example:
            >>> points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
            >>> result = RasHdf.find_nearest_neighbors(points)
            >>> print(result)
            array([1, 0, 1, -1])
        """
        dist, snap = KDTree(points).query(points, k=2, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        
        snp = pd.DataFrame(snap, index=np.arange(len(snap)))
        snp = snp.replace(-1, np.nan)
        snp.loc[snp[0] == snp.index, 0] = np.nan
        snp.loc[snp[1] == snp.index, 1] = np.nan
        filled = snp[0].fillna(snp[1])
        snapped = filled.fillna(-1).astype(np.int64).to_numpy()
        return snapped

    @classmethod
    @log_call
    def consolidate_dataframe(
        dataframe: pd.DataFrame,
        group_by: Optional[Union[str, List[str]]] = None,
        pivot_columns: Optional[Union[str, List[str]]] = None,
        level: Optional[int] = None,
        n_dimensional: bool = False,
        aggregation_method: Union[str, Callable] = 'list'
    ) -> pd.DataFrame:
        """
        Consolidate rows in a DataFrame by merging duplicate values into lists or using a specified aggregation function.

        Args:
            dataframe (pd.DataFrame): The DataFrame to consolidate.
            group_by (Optional[Union[str, List[str]]]): Columns or indices to group by.
            pivot_columns (Optional[Union[str, List[str]]]): Columns to pivot.
            level (Optional[int]): Level of multi-index to group by.
            n_dimensional (bool): If True, use a pivot table for N-Dimensional consolidation.
            aggregation_method (Union[str, Callable]): Aggregation method, e.g., 'list' to aggregate into lists.

        Returns:
            pd.DataFrame: The consolidated DataFrame.

        Example:
            >>> df = pd.DataFrame({'A': [1, 1, 2], 'B': [4, 5, 6], 'C': [7, 8, 9]})
            >>> result = RasHdf.consolidate_dataframe(df, group_by='A')
            >>> print(result)
            B         C
            A            
            1  [4, 5]  [7, 8]
            2  [6]     [9]
        """
        if aggregation_method == 'list':
            agg_func = lambda x: tuple(x)
        else:
            agg_func = aggregation_method

        if n_dimensional:
            result = dataframe.pivot_table(group_by, pivot_columns, aggfunc=agg_func)
        else:
            result = dataframe.groupby(group_by, level=level).agg(agg_func).applymap(list)

        return result
    
    @classmethod
    @log_call
    def find_nearest_value(array: Union[list, np.ndarray], target_value: Union[int, float]) -> Union[int, float]:
        """
        Finds the nearest value in a NumPy array to the specified target value.

        Args:
            array (Union[list, np.ndarray]): The array to search within.
            target_value (Union[int, float]): The value to find the nearest neighbor to.

        Returns:
            Union[int, float]: The nearest value in the array to the specified target value.

        Example:
            >>> arr = np.array([1, 3, 5, 7, 9])
            >>> result = RasHdf.find_nearest_value(arr, 6)
            >>> print(result)
            5
        """
        array = np.asarray(array)
        idx = (np.abs(array - target_value)).argmin()
        return array[idx]
    
    @staticmethod
    @log_call
    def _get_hdf_filename(hdf_input: Union[str, Path, h5py.File], ras_object=None) -> Optional[Path]:
        """
        Get the HDF filename from the input.

        Args:
            hdf_input (Union[str, Path, h5py.File]): The plan number, full path to the HDF file as a string, a Path object, or an h5py.File object.
            ras_object (RasPrj, optional): The RAS project object. If None, uses the global ras instance.

        Returns:
            Optional[Path]: The full path to the HDF file as a Path object, or None if an error occurs.

        Note:
            This method logs critical errors instead of raising exceptions.
        """

        # If hdf_input is already an h5py.File object, return its filename
        if isinstance(hdf_input, h5py.File):
            return Path(hdf_input.filename)

        # Convert to Path object if it's a string
        if isinstance(hdf_input, str):
            hdf_input = Path(hdf_input)

        # If hdf_input is a file path, return it directly
        if isinstance(hdf_input, Path) and hdf_input.is_file():
            return hdf_input

        # If hdf_input is not a file path, assume it's a plan number and require ras_object
        ras_obj = ras_object or ras
        if not ras_obj.initialized:
            logger.critical("ras_object is not initialized. ras_object is required when hdf_input is not a direct file path.")
            return None

        plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == str(hdf_input)]
        if plan_info.empty:
            logger.critical(f"No HDF file found for plan number {hdf_input}")
            return None

        hdf_filename = plan_info.iloc[0]['HDF_Results_Path']
        if hdf_filename is None:
            logger.critical(f"HDF_Results_Path is None for plan number {hdf_input}")
            return None

        hdf_path = Path(hdf_filename)
        if not hdf_path.is_file():
            logger.critical(f"HDF file not found: {hdf_path}")
            return None

        return hdf_path



@log_call
def save_dataframe_to_hdf(
    dataframe: pd.DataFrame,
    hdf_parent_group: h5py.Group,
    dataset_name: str,
    attributes: Optional[Dict[str, Union[int, float, str]]] = None,
    fill_value: Union[int, float, str] = -9999,
    **kwargs: Any
) -> h5py.Dataset:
    """
    Save a pandas DataFrame to an HDF5 dataset within a specified parent group.

    This function addresses limitations of `pd.to_hdf()` by using h5py to create and save datasets.

    Args:
        dataframe (pd.DataFrame): The DataFrame to save.
        hdf_parent_group (h5py.Group): The parent HDF5 group where the dataset will be created.
        dataset_name (str): The name of the new dataset to add in the HDF5 parent group.
        attributes (Optional[Dict[str, Union[int, float, str]]]): A dictionary of attributes to add to the dataset.
        fill_value (Union[int, float, str]): The value to use for filling missing data.
        **kwargs: Additional keyword arguments passed to `hdf_parent_group.create_dataset()`.

    Returns:
        h5py.Dataset: The created HDF5 dataset within the parent group.

    Raises:
        ValueError: If the DataFrame columns are not consistent.

    Example:
        >>> df = pd.DataFrame({'A': [1, 2, 3], 'B': ['a', 'b', 'c']})
        >>> with h5py.File('data.h5', 'w') as f:
        ...     group = f.create_group('my_group')
        ...     dataset = save_dataframe_to_hdf(df, group, 'my_dataset')
        >>> print(dataset)
    """
    df = dataframe.copy()

    # Replace '/' in column names with '-' to avoid issues in HDF5
    if df.columns.dtype == 'O':
        df.columns = df.columns.str.replace('/', '-', regex=False)
    
    # Fill missing values with the specified fill_value
    df = df.fillna(fill_value)
    
    # Identify string columns and ensure consistency
    string_cols = df.select_dtypes(include=['object']).columns
    if not string_cols.equals(df.select_dtypes(include=['object']).columns):
        logger.error("Inconsistent string columns detected")
        raise ValueError("Inconsistent string columns detected")
    
    # Encode string columns to bytes
    df[string_cols] = df[string_cols].applymap(lambda x: x.encode('utf-8')).astype('bytes')

    # Prepare data for HDF5 dataset creation
    arr = df.to_records(index=False) if not isinstance(df.columns, pd.RangeIndex) else df.values
    
    # Remove existing dataset if it exists
    if dataset_name in hdf_parent_group:
        logger.warning(f"Existing dataset {dataset_name} will be overwritten")
        del hdf_parent_group[dataset_name]
    
    # Create the dataset in the HDF5 file
    dataset = hdf_parent_group.create_dataset(dataset_name, data=arr, **kwargs)
    
    # Update dataset attributes if provided
    if attributes:
        dataset.attrs.update(attributes)
    
    logger.info(f"Successfully saved DataFrame to dataset: {dataset_name}")
    return dataset
