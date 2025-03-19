"""
RasUtils - Utility functions for the ras-commander library

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

Example:
    @log_call
    def my_function():
        logger.debug("Additional debug information")
        # Function logic here
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasUtils:
- create_directory()
- find_files_by_extension()
- get_file_size()
- get_file_modification_time()
- get_plan_path()
- remove_with_retry()
- update_plan_file()
- check_file_access()
- convert_to_dataframe()
- save_to_excel()
- calculate_rmse()
- calculate_percent_bias()
- calculate_error_metrics()
- update_file()
- get_next_number()
- clone_file()
- update_project_file()
- decode_byte_strings()
- perform_kdtree_query()
- find_nearest_neighbors()
- consolidate_dataframe()
- find_nearest_value()
- horizontal_distance()
    
        
"""
import os
from pathlib import Path
from .RasPrj import ras
from typing import Union, Optional, Dict, Callable, List, Tuple, Any
import pandas as pd
import numpy as np
import shutil
import re
from scipy.spatial import KDTree
import datetime
import time
import h5py
from datetime import timedelta
from .LoggingConfig import get_logger
from .Decorators import log_call


logger = get_logger(__name__)
# Module code starts here

class RasUtils:
    """
    A class containing utility functions for the ras-commander library.
    When integrating new functions that do not clearly fit into other classes, add them here.
    """

    @staticmethod
    @log_call
    def create_directory(directory_path: Path, ras_object=None) -> Path:
        """
        Ensure that a directory exists, creating it if necessary.

        Parameters:
        directory_path (Path): Path to the directory
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Path to the ensured directory

        Example:
        >>> ensured_dir = RasUtils.create_directory(Path("output"))
        >>> print(f"Directory ensured: {ensured_dir}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(directory_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Directory ensured: {path}")
        except Exception as e:
            logger.error(f"Failed to create directory {path}: {e}")
            raise
        return path

    @staticmethod
    @log_call
    def find_files_by_extension(extension: str, ras_object=None) -> list:
        """
        List all files in the project directory with a specific extension.

        Parameters:
        extension (str): File extension to filter (e.g., '.prj')
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        list: List of file paths matching the extension

        Example:
        >>> prj_files = RasUtils.find_files_by_extension('.prj')
        >>> print(f"Found {len(prj_files)} .prj files")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        try:
            files = list(ras_obj.project_folder.glob(f"*{extension}"))
            file_list = [str(file) for file in files]
            logger.info(f"Found {len(file_list)} files with extension '{extension}' in {ras_obj.project_folder}")
            return file_list
        except Exception as e:
            logger.error(f"Failed to find files with extension '{extension}': {e}")
            raise

    @staticmethod
    @log_call
    def get_file_size(file_path: Path, ras_object=None) -> Optional[int]:
        """
        Get the size of a file in bytes.

        Parameters:
        file_path (Path): Path to the file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Optional[int]: Size of the file in bytes, or None if the file does not exist

        Example:
        >>> size = RasUtils.get_file_size(Path("project.prj"))
        >>> print(f"File size: {size} bytes")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            try:
                size = path.stat().st_size
                logger.info(f"Size of {path}: {size} bytes")
                return size
            except Exception as e:
                logger.error(f"Failed to get size for {path}: {e}")
                raise
        else:
            logger.warning(f"File not found: {path}")
            return None

    @staticmethod
    @log_call
    def get_file_modification_time(file_path: Path, ras_object=None) -> Optional[float]:
        """
        Get the last modification time of a file.

        Parameters:
        file_path (Path): Path to the file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Optional[float]: Last modification time as a timestamp, or None if the file does not exist

        Example:
        >>> mtime = RasUtils.get_file_modification_time(Path("project.prj"))
        >>> print(f"Last modified: {mtime}")
        """
        
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        path = Path(file_path)
        if path.exists():
            try:
                mtime = path.stat().st_mtime
                logger.info(f"Last modification time of {path}: {mtime}")
                return mtime
            except Exception as e:
                logger.exception(f"Failed to get modification time for {path}")
                raise
        else:
            logger.warning(f"File not found: {path}")
            return None

    @staticmethod
    @log_call
    def get_plan_path(current_plan_number_or_path: Union[str, Path], ras_object=None) -> Path:
        """
        Get the path for a plan file with a given plan number or path.

        Parameters:
        current_plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        Path: Full path to the plan file

        Raises:
        ValueError: If plan number is not between 1 and 99
        TypeError: If input type is invalid
        FileNotFoundError: If the plan file does not exist

        Example:
        >>> plan_path = RasUtils.get_plan_path(1)
        >>> print(f"Plan file path: {plan_path}")
        >>> plan_path = RasUtils.get_plan_path("path/to/plan.p01")
        >>> print(f"Plan file path: {plan_path}")
        """
        # Validate RAS object
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Handle direct file path input
        plan_path = Path(current_plan_number_or_path)
        if plan_path.is_file():
            logger.info(f"Using provided plan file path: {plan_path}")
            return plan_path
        
        # Handle plan number input
        try:
            plan_num = int(current_plan_number_or_path)
            if not 1 <= plan_num <= 99:
                raise ValueError(f"Plan number must be between 1 and 99, got: {plan_num}")
            current_plan_number = f"{plan_num:02d}"  # Ensure two-digit format
            logger.debug(f"Converted plan number to two-digit format: {current_plan_number}")
        except (ValueError, TypeError) as e:
            if isinstance(e, TypeError):
                logger.error(f"Invalid input type: {type(current_plan_number_or_path)}. Expected string, number, or Path.")
                raise TypeError(f"Invalid input type: {type(current_plan_number_or_path)}. Expected string, number, or Path.")
            logger.error(f"Invalid plan number: {current_plan_number_or_path}. Expected a number from 1 to 99.")
            raise ValueError(f"Invalid plan number: {current_plan_number_or_path}. Expected a number from 1 to 99.")
        
        # Construct and validate plan path
        plan_name = f"{ras_obj.project_name}.p{current_plan_number}"
        full_plan_path = ras_obj.project_folder / plan_name
        
        if not full_plan_path.exists():
            logger.error(f"Plan file does not exist: {full_plan_path}")
            raise FileNotFoundError(f"Plan file does not exist: {full_plan_path}")
        
        logger.info(f"Constructed plan file path: {full_plan_path}")
        return full_plan_path

    @staticmethod
    @log_call
    def remove_with_retry(
        path: Path,
        max_attempts: int = 5,
        initial_delay: float = 1.0,
        is_folder: bool = True,
        ras_object=None
    ) -> bool:
        """
        Attempts to remove a file or folder with retry logic and exponential backoff.

        Parameters:
        path (Path): Path to the file or folder to be removed.
        max_attempts (int): Maximum number of removal attempts.
        initial_delay (float): Initial delay between attempts in seconds.
        is_folder (bool): If True, the path is treated as a folder; if False, it's treated as a file.
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Returns:
        bool: True if the file or folder was successfully removed, False otherwise.

        Example:
        >>> success = RasUtils.remove_with_retry(Path("temp_folder"), is_folder=True)
        >>> print(f"Removal successful: {success}")
        """
        
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        path = Path(path)
        for attempt in range(1, max_attempts + 1):
            try:
                if path.exists():
                    if is_folder:
                        shutil.rmtree(path)
                        logger.info(f"Folder removed: {path}")
                    else:
                        path.unlink()
                        logger.info(f"File removed: {path}")
                else:
                    logger.info(f"Path does not exist, nothing to remove: {path}")
                return True
            except PermissionError as pe:
                if attempt < max_attempts:
                    delay = initial_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logger.warning(
                        f"PermissionError on attempt {attempt} to remove {path}: {pe}. "
                        f"Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Failed to remove {path} after {max_attempts} attempts due to PermissionError: {pe}. Skipping."
                    )
                    return False
            except Exception as e:
                logger.exception(f"Failed to remove {path} on attempt {attempt}")
                return False
        return False

    @staticmethod
    @log_call
    def update_plan_file(
        plan_number_or_path: Union[str, Path],
        file_type: str,
        entry_number: int,
        ras_object=None
    ) -> None:
        """
        Update a plan file with a new file reference.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        file_type (str): Type of file to update ('Geom', 'Flow', or 'Unsteady')
        entry_number (int): Number (from 1 to 99) to set
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Raises:
        ValueError: If an invalid file_type is provided
        FileNotFoundError: If the plan file doesn't exist

        Example:
        >>> RasUtils.update_plan_file(1, "Geom", 2)
        >>> RasUtils.update_plan_file("path/to/plan.p01", "Geom", 2)
        """
        
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        valid_file_types = {'Geom': 'g', 'Flow': 'f', 'Unsteady': 'u'}
        if file_type not in valid_file_types:
            logger.error(
                f"Invalid file_type '{file_type}'. Expected one of: {', '.join(valid_file_types.keys())}"
            )
            raise ValueError(
                f"Invalid file_type. Expected one of: {', '.join(valid_file_types.keys())}"
            )

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasUtils.get_plan_path(plan_number_or_path, ras_object)
            if not plan_file_path.exists():
                logger.error(f"Plan file not found: {plan_file_path}")
                raise FileNotFoundError(f"Plan file not found: {plan_file_path}")
        
        file_prefix = valid_file_types[file_type]
        search_pattern = f"{file_type} File="
        formatted_entry_number = f"{int(entry_number):02d}"  # Ensure two-digit format

        try:
            RasUtils.check_file_access(plan_file_path, 'r')
            with plan_file_path.open('r') as file:
                lines = file.readlines()
        except Exception as e:
            logger.exception(f"Failed to read plan file {plan_file_path}")
            raise

        updated = False
        for i, line in enumerate(lines):
            if line.startswith(search_pattern):
                lines[i] = f"{search_pattern}{file_prefix}{formatted_entry_number}\n"
                logger.info(
                    f"Updated {file_type} File in {plan_file_path} to {file_prefix}{formatted_entry_number}"
                )
                updated = True
                break

        if not updated:
            logger.warning(
                f"Search pattern '{search_pattern}' not found in {plan_file_path}. No update performed."
            )

        try:
            with plan_file_path.open('w') as file:
                file.writelines(lines)
            logger.info(f"Successfully updated plan file: {plan_file_path}")
        except Exception as e:
            logger.exception(f"Failed to write updates to plan file {plan_file_path}")
            raise

        # Refresh RasPrj dataframes
        try:
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            logger.info("RAS object dataframes have been refreshed.")
        except Exception as e:
            logger.exception("Failed to refresh RasPrj dataframes")
            raise

    @staticmethod
    @log_call
    def check_file_access(file_path: Path, mode: str = 'r') -> None:
        """
        Check if the file can be accessed with the specified mode.

        Parameters:
        file_path (Path): Path to the file
        mode (str): Mode to check ('r' for read, 'w' for write, etc.)

        Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If the required permissions are not met
        """
        
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if mode in ('r', 'rb'):
            if not os.access(path, os.R_OK):
                logger.error(f"Read permission denied for file: {file_path}")
                raise PermissionError(f"Read permission denied for file: {file_path}")
            else:
                logger.debug(f"Read access granted for file: {file_path}")
        
        if mode in ('w', 'wb', 'a', 'ab'):
            parent_dir = path.parent
            if not os.access(parent_dir, os.W_OK):
                logger.error(f"Write permission denied for directory: {parent_dir}")
                raise PermissionError(f"Write permission denied for directory: {parent_dir}")
            else:
                logger.debug(f"Write access granted for directory: {parent_dir}")


    @staticmethod
    @log_call
    def convert_to_dataframe(data_source: Union[pd.DataFrame, Path], **kwargs) -> pd.DataFrame:
        """
        Converts input to a pandas DataFrame. Supports existing DataFrames or file paths (CSV, Excel, TSV, Parquet).

        Args:
            data_source (Union[pd.DataFrame, Path]): The input to convert to a DataFrame. Can be a file path or an existing DataFrame.
            **kwargs: Additional keyword arguments to pass to pandas read functions.

        Returns:
            pd.DataFrame: The resulting DataFrame.

        Raises:
            NotImplementedError: If the file type is unsupported or input type is invalid.

        Example:
            >>> df = RasUtils.convert_to_dataframe(Path("data.csv"))
            >>> print(type(df))
            <class 'pandas.core.frame.DataFrame'>
        """
        if isinstance(data_source, pd.DataFrame):
            logger.debug("Input is already a DataFrame, returning a copy.")
            return data_source.copy()
        elif isinstance(data_source, Path):
            ext = data_source.suffix.replace('.', '', 1)
            logger.info(f"Converting file with extension '{ext}' to DataFrame.")
            if ext == 'csv':
                return pd.read_csv(data_source, **kwargs)
            elif ext.startswith('x'):
                return pd.read_excel(data_source, **kwargs)
            elif ext == "tsv":
                return pd.read_csv(data_source, sep="\t", **kwargs)
            elif ext in ["parquet", "pq", "parq"]:
                return pd.read_parquet(data_source, **kwargs)
            else:
                logger.error(f"Unsupported file type: {ext}")
                raise NotImplementedError(f"Unsupported file type {ext}. Should be one of csv, tsv, parquet, or xlsx.")
        else:
            logger.error(f"Unsupported input type: {type(data_source)}")
            raise NotImplementedError(f"Unsupported type {type(data_source)}. Only file path / existing DataFrame supported at this time")

    @staticmethod
    @log_call
    def save_to_excel(dataframe: pd.DataFrame, excel_path: Path, **kwargs) -> None:
        """
        Saves a pandas DataFrame to an Excel file with retry functionality.

        Args:
            dataframe (pd.DataFrame): The DataFrame to save.
            excel_path (Path): The path to the Excel file where the DataFrame will be saved.
            **kwargs: Additional keyword arguments passed to `DataFrame.to_excel()`.

        Raises:
            IOError: If the file cannot be saved after multiple attempts.

        Example:
            >>> df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
            >>> RasUtils.save_to_excel(df, Path('output.xlsx'))
        """
        saved = False
        max_attempts = 3
        attempt = 0

        while not saved and attempt < max_attempts:
            try:
                dataframe.to_excel(excel_path, **kwargs)
                logger.info(f'DataFrame successfully saved to {excel_path}')
                saved = True
            except IOError as e:
                attempt += 1
                if attempt < max_attempts:
                    logger.warning(f"Error saving file. Attempt {attempt} of {max_attempts}. Please close the Excel document if it's open.")
                else:
                    logger.error(f"Failed to save {excel_path} after {max_attempts} attempts.")
                    raise IOError(f"Failed to save {excel_path} after {max_attempts} attempts. Last error: {str(e)}")

    @staticmethod
    @log_call
    def calculate_rmse(observed_values: np.ndarray, predicted_values: np.ndarray, normalized: bool = True) -> float:
        """
        Calculate the Root Mean Squared Error (RMSE) between observed and predicted values.

        Args:
            observed_values (np.ndarray): Actual observations time series.
            predicted_values (np.ndarray): Estimated/predicted time series.
            normalized (bool, optional): Whether to normalize RMSE to a percentage of observed_values. Defaults to True.

        Returns:
            float: The calculated RMSE value.

        Example:
            >>> observed = np.array([1, 2, 3])
            >>> predicted = np.array([1.1, 2.2, 2.9])
            >>> RasUtils.calculate_rmse(observed, predicted)
            0.06396394
        """
        rmse = np.sqrt(np.mean((predicted_values - observed_values) ** 2))
        
        if normalized:
            rmse = rmse / np.abs(np.mean(observed_values))
        
        logger.debug(f"Calculated RMSE: {rmse}")
        return rmse

    @staticmethod
    @log_call
    def calculate_percent_bias(observed_values: np.ndarray, predicted_values: np.ndarray, as_percentage: bool = False) -> float:
        """
        Calculate the Percent Bias between observed and predicted values.

        Args:
            observed_values (np.ndarray): Actual observations time series.
            predicted_values (np.ndarray): Estimated/predicted time series.
            as_percentage (bool, optional): If True, return bias as a percentage. Defaults to False.

        Returns:
            float: The calculated Percent Bias.

        Example:
            >>> observed = np.array([1, 2, 3])
            >>> predicted = np.array([1.1, 2.2, 2.9])
            >>> RasUtils.calculate_percent_bias(observed, predicted, as_percentage=True)
            3.33333333
        """
        multiplier = 100 if as_percentage else 1
        
        percent_bias = multiplier * (np.mean(predicted_values) - np.mean(observed_values)) / np.mean(observed_values)
        
        logger.debug(f"Calculated Percent Bias: {percent_bias}")
        return percent_bias

    @staticmethod
    @log_call
    def calculate_error_metrics(observed_values: np.ndarray, predicted_values: np.ndarray) -> Dict[str, float]:
        """
        Compute a trio of error metrics: correlation, RMSE, and Percent Bias.

        Args:
            observed_values (np.ndarray): Actual observations time series.
            predicted_values (np.ndarray): Estimated/predicted time series.

        Returns:
            Dict[str, float]: A dictionary containing correlation ('cor'), RMSE ('rmse'), and Percent Bias ('pb').

        Example:
            >>> observed = np.array([1, 2, 3])
            >>> predicted = np.array([1.1, 2.2, 2.9])
            >>> RasUtils.calculate_error_metrics(observed, predicted)
            {'cor': 0.9993, 'rmse': 0.06396, 'pb': 0.03333}
        """
        correlation = np.corrcoef(observed_values, predicted_values)[0, 1]
        rmse = RasUtils.calculate_rmse(observed_values, predicted_values)
        percent_bias = RasUtils.calculate_percent_bias(observed_values, predicted_values)
        
        metrics = {'cor': correlation, 'rmse': rmse, 'pb': percent_bias}
        logger.info(f"Calculated error metrics: {metrics}")
        return metrics

    
    @staticmethod
    @log_call
    def update_file(file_path: Path, update_function: Callable, *args) -> None:
        """
        Generic method to update a file.

        Parameters:
        file_path (Path): Path to the file to be updated
        update_function (Callable): Function to update the file contents
        *args: Additional arguments to pass to the update_function

        Raises:
        Exception: If there's an error updating the file

        Example:
        >>> def update_content(lines, new_value):
        ...     lines[0] = f"New value: {new_value}\\n"
        ...     return lines
        >>> RasUtils.update_file(Path("example.txt"), update_content, "Hello")
        """
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            updated_lines = update_function(lines, *args) if args else update_function(lines)
            
            with open(file_path, 'w') as f:
                f.writelines(updated_lines)
            logger.info(f"Successfully updated file: {file_path}")
        except Exception as e:
            logger.exception(f"Failed to update file {file_path}")
            raise

    @staticmethod
    @log_call
    def get_next_number(existing_numbers: list) -> str:
        """
        Determine the next available number from a list of existing numbers.

        Parameters:
        existing_numbers (list): List of existing numbers as strings

        Returns:
        str: Next available number as a zero-padded string

        Example:
        >>> RasUtils.get_next_number(["01", "02", "04"])
        "05"
        """
        existing_numbers = sorted(int(num) for num in existing_numbers)
        next_number = max(existing_numbers, default=0) + 1
        return f"{next_number:02d}"

    @staticmethod
    @log_call
    def clone_file(template_path: Path, new_path: Path, update_function: Optional[Callable] = None, *args) -> None:
        """
        Generic method to clone a file and optionally update it.

        Parameters:
        template_path (Path): Path to the template file
        new_path (Path): Path where the new file will be created
        update_function (Optional[Callable]): Function to update the cloned file
        *args: Additional arguments to pass to the update_function

        Raises:
        FileNotFoundError: If the template file doesn't exist

        Example:
        >>> def update_content(lines, new_value):
        ...     lines[0] = f"New value: {new_value}\\n"
        ...     return lines
        >>> RasUtils.clone_file(Path("template.txt"), Path("new.txt"), update_content, "Hello")
        """
        if not template_path.exists():
            logger.error(f"Template file '{template_path}' does not exist.")
            raise FileNotFoundError(f"Template file '{template_path}' does not exist.")

        shutil.copy(template_path, new_path)
        logger.info(f"File cloned from {template_path} to {new_path}")

        if update_function:
            RasUtils.update_file(new_path, update_function, *args)
    @staticmethod
    @log_call
    def update_project_file(prj_file: Path, file_type: str, new_num: str, ras_object=None) -> None:
        """
        Update the project file with a new entry.

        Parameters:
        prj_file (Path): Path to the project file
        file_type (str): Type of file being added (e.g., 'Plan', 'Geom')
        new_num (str): Number of the new file entry
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Example:
        >>> RasUtils.update_project_file(Path("project.prj"), "Plan", "02")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        try:
            with open(prj_file, 'r') as f:
                lines = f.readlines()
            
            new_line = f"{file_type} File={file_type[0].lower()}{new_num}\n"
            lines.append(new_line)
            
            with open(prj_file, 'w') as f:
                f.writelines(lines)
            logger.info(f"Project file updated with new {file_type} entry: {new_num}")
        except Exception as e:
            logger.exception(f"Failed to update project file {prj_file}")
            raise
        
  
        
        
    # From FunkShuns
        
    @staticmethod
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
            >>> decoded_df = RasUtils.decode_byte_strings(df)
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

    @staticmethod
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
            >>> result = RasUtils.perform_kdtree_query(ref_points, query_points)
            >>> print(result)
            array([ 0, -1])
        """
        dist, snap = KDTree(reference_points).query(query_points, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        return snap

    @staticmethod
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
            >>> result = RasUtils.find_nearest_neighbors(points)
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

    @staticmethod
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
            >>> result = RasUtils.consolidate_dataframe(df, group_by='A')
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

    @staticmethod
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
            >>> result = RasUtils.find_nearest_value(arr, 6)
            >>> print(result)
            5
        """
        array = np.asarray(array)
        idx = (np.abs(array - target_value)).argmin()
        return array[idx]
    
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
            >>> distance = RasUtils.horizontal_distance(np.array([0, 0]), np.array([3, 4]))
            >>> print(distance)
            5.0
        """
        return np.linalg.norm(coord2 - coord1)
    
    
    
    
    