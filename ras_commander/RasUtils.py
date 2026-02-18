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
- safe_resolve()
- find_files_by_extension()
- get_file_size()
- get_file_modification_time()
- normalize_ras_number()
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
- remove_prj_entry()
- rename_prj_entry()
- decode_byte_strings()
- perform_kdtree_query()
- find_nearest_neighbors()
- consolidate_dataframe()
- find_nearest_value()
- horizontal_distance()
- find_valid_ras_folders()
- is_valid_ras_folder()
- safe_write_geometry()      # Phase 2.1 - Atomic file write with backup
- rollback_geometry()        # Phase 2.1 - Restore from backup
- validate_geometry_file_basic()  # Phase 2.1 - Basic validation
- _read_description_block()  # Internal - Read BEGIN DESCRIPTION / END DESCRIPTION block
- _write_description_block() # Internal - Write BEGIN DESCRIPTION / END DESCRIPTION block

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
from numbers import Number
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
    def safe_resolve(path: Path) -> Path:
        """
        Resolve path while preserving Windows drive letters.

        On Windows with mapped network drives, Path.resolve() converts
        drive letters (H:\\) to UNC paths (\\\\server\\share). HEC-RAS cannot
        read from UNC paths, so we preserve the drive letter format.

        This function:
        - On non-Windows: Uses standard resolve()
        - On Windows with local drives: Uses standard resolve()
        - On Windows with mapped drives: Falls back to absolute() to preserve drive letter

        Parameters:
            path (Path): Path to resolve

        Returns:
            Path: Resolved path with drive letter preserved if applicable

        Example:
            >>> from pathlib import Path
            >>> from ras_commander import RasUtils
            >>> # Local drive - normal resolution
            >>> resolved = RasUtils.safe_resolve(Path("C:/Projects/Model.prj"))
            >>> # Mapped drive - preserves H: instead of converting to UNC
            >>> resolved = RasUtils.safe_resolve(Path("H:/Projects/Model.prj"))
        """
        # Ensure we have a Path object
        path = Path(path)

        # On non-Windows, use standard resolve
        if os.name != 'nt':
            return path.resolve()

        original_str = str(path)
        resolved = path.resolve()

        # Check if original had drive letter but resolved became UNC path
        # Drive letter format: "X:..." where X is a letter
        # UNC format: "\\..." (starts with double backslash)
        has_drive_letter = len(original_str) >= 2 and original_str[1] == ':'
        is_unc = str(resolved).startswith('\\\\')

        if has_drive_letter and is_unc:
            # Mapped network drive detected - use absolute() to preserve drive letter
            logger.debug(
                f"Mapped drive detected: {original_str} would resolve to UNC {resolved}. "
                f"Using absolute() to preserve drive letter."
            )
            return path.absolute()

        return resolved

    # Windows reserved device names (case-insensitive, without extensions)
    _WINDOWS_RESERVED_NAMES = frozenset({
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
    })

    @staticmethod
    def ignore_windows_reserved(directory, contents):
        """
        Ignore function for shutil.copytree that skips Windows reserved device names.

        Windows lists virtual device names (NUL, CON, PRN, etc.) in directory
        listings even though they are not real files. shutil.copytree fails
        when it tries to copy them. This function filters them out.

        Parameters:
            directory: The directory being copied (provided by copytree)
            contents: List of names in the directory (provided by copytree)

        Returns:
            set: Names to ignore (Windows reserved device names)
        """
        ignored = set()
        for name in contents:
            stem = Path(name).stem.upper()
            if stem in RasUtils._WINDOWS_RESERVED_NAMES:
                logger.debug(f"Skipping Windows reserved name: {name} in {directory}")
                ignored.add(name)
        return ignored

    @staticmethod
    def is_windows_reserved_name(name: str) -> bool:
        """
        Check if a filename is a Windows reserved device name.

        Parameters:
            name: Filename to check

        Returns:
            bool: True if the name is a reserved device name
        """
        stem = Path(name).stem.upper()
        return stem in RasUtils._WINDOWS_RESERVED_NAMES

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
    def normalize_ras_number(ras_number: Union[str, int, float, Path, Number]) -> str:
        """
        Normalize RAS file numbers to two-digit string format.

        HEC-RAS uses two-digit file extensions for plans (.p01), geometries (.g02),
        flows (.f03), etc. This function standardizes various input formats to ensure
        consistent file path construction.

        Parameters:
        ras_number (Union[str, int, float, Path, Number]): Input number in various formats:
            - int: 1, 2, 3, etc.
            - str: "1", "01", "001", etc.
            - float: 1.0, 2.0 (must be whole numbers)
            - Path: Path("project.p05") - extracts number from extension
            - Number: numpy.int64(1), etc.

        Returns:
        str: Normalized two-digit format ("01", "02", ..., "99")

        Raises:
        ValueError: If the number is not between 1 and 99, or cannot be converted
        TypeError: If the input type is invalid

        Examples:
        >>> RasUtils.normalize_ras_number(1)
        '01'
        >>> RasUtils.normalize_ras_number("1")
        '01'
        >>> RasUtils.normalize_ras_number("01")
        '01'
        >>> RasUtils.normalize_ras_number("001")
        '01'
        >>> RasUtils.normalize_ras_number(np.int64(5))
        '05'
        >>> RasUtils.normalize_ras_number(Path("project.p02"))
        '02'

        Notes:
        - Used for plan numbers, geometry numbers, flow file numbers, etc.
        - Ensures consistent handling across all RAS file types
        - Prevents file path construction errors from unnormalized inputs
        """
        # Handle Path objects - extract number from file extension
        if isinstance(ras_number, Path):
            # Extract from extensions like .p01, .g02, .f03, etc.
            suffix = ras_number.suffix  # e.g., ".p01"
            if len(suffix) >= 2 and suffix[0] == '.':
                # Try to extract number after the letter (e.g., "01" from ".p01")
                number_part = suffix[2:]  # Skip "." and letter
                if number_part.isdigit():
                    ras_number = number_part
                else:
                    raise ValueError(
                        f"Cannot extract RAS number from Path extension: {ras_number}. "
                        f"Expected format like 'project.p01' or 'geom.g02'"
                    )
            else:
                raise ValueError(
                    f"Cannot extract RAS number from Path: {ras_number}. "
                    f"Expected file with RAS extension like .p01, .g02, etc."
                )

        # Convert to integer for validation
        try:
            # Handle string inputs - strip leading zeros before conversion
            if isinstance(ras_number, str):
                stripped = ras_number.lstrip('0')
                if not stripped or not stripped.isdigit():
                    # Handle edge cases like "0", "00", or non-numeric strings
                    if not stripped:  # Was all zeros
                        ras_int = 0
                    else:
                        raise ValueError(f"Cannot convert '{ras_number}' to integer")
                else:
                    ras_int = int(stripped)
            else:
                # Handle numeric types (int, float, numpy types, etc.)
                ras_int = int(ras_number)

                # Check if float had decimal component
                if isinstance(ras_number, (float, np.floating)) and ras_number != ras_int:
                    raise ValueError(
                        f"RAS numbers must be integers, got float with decimals: {ras_number}"
                    )

        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Cannot convert RAS number '{ras_number}' (type: {type(ras_number).__name__}) "
                f"to integer: {e}"
            ) from e

        # Validate range (1-99 for HEC-RAS files)
        if not 1 <= ras_int <= 99:
            raise ValueError(
                f"RAS file number must be between 1 and 99, got: {ras_int}"
            )

        # Return normalized two-digit format
        normalized = f"{ras_int:02d}"
        logger.debug(f"Normalized RAS number '{ras_number}' to '{normalized}'")
        return normalized

    @staticmethod
    @log_call
    def get_plan_path(current_plan_number_or_path: Union[str, Number, Path], ras_object=None) -> Path:
        """
        Get the path for a plan file with a given plan number or path.

        Parameters:
        current_plan_number_or_path (Union[str, Number, Path]): The plan number (e.g., '01', 1, or 1.0) or full path to the plan file
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
        >>> plan_path = RasUtils.get_plan_path("01")
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

        # Handle plan number input - use centralized normalization
        try:
            current_plan_number = RasUtils.normalize_ras_number(current_plan_number_or_path)
            logger.debug(f"Normalized plan number to: {current_plan_number}")
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid plan number: {current_plan_number_or_path}. {e}")
            raise
        
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
    def convert_to_dataframe(
        data_source: Union[pd.DataFrame, Path],
        **kwargs: Any
    ) -> pd.DataFrame:
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
    def save_to_excel(
        dataframe: pd.DataFrame,
        excel_path: Path,
        **kwargs: Any
    ) -> None:
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

    # NOTE: remove_prj_entry() and rename_prj_entry() are awaiting maintainer review
    @staticmethod
    @log_call
    def remove_prj_entry(prj_file: Path, file_type: str, number: str, ras_object=None) -> None:
        """
        Remove a file entry from the .prj file.

        Parameters:
        prj_file (Path): Path to the project file
        file_type (str): Type of file entry ('Plan', 'Geom', 'Unsteady', or 'Flow')
        number (str): Two-digit number of the entry to remove (e.g., '05')
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Example:
        >>> RasUtils.remove_prj_entry(Path("project.prj"), "Plan", "05")
        # Removes the line "Plan File=p05" from the .prj file
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        prefix = file_type[0].lower()
        target = f"{file_type} File={prefix}{number}"

        try:
            with open(prj_file, 'r') as f:
                lines = f.readlines()

            new_lines = [line for line in lines if line.strip() != target]

            if len(new_lines) == len(lines):
                logger.warning(f"Entry '{target}' not found in {prj_file}")
                return

            with open(prj_file, 'w') as f:
                f.writelines(new_lines)
            logger.info(f"Removed {file_type} entry {number} from project file")
        except Exception as e:
            logger.exception(f"Failed to remove entry from project file {prj_file}")
            raise

    @staticmethod
    @log_call
    def rename_prj_entry(prj_file: Path, file_type: str, old_number: str, new_number: str, ras_object=None) -> None:
        """
        Rename a file entry in the .prj file.

        Parameters:
        prj_file (Path): Path to the project file
        file_type (str): Type of file entry ('Plan', 'Geom', 'Unsteady', or 'Flow')
        old_number (str): Current two-digit number (e.g., '05')
        new_number (str): New two-digit number (e.g., '02')
        ras_object (RasPrj, optional): RAS object to use. If None, uses the default ras object.

        Example:
        >>> RasUtils.rename_prj_entry(Path("project.prj"), "Plan", "05", "02")
        # Changes "Plan File=p05" to "Plan File=p02" in the .prj file
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        prefix = file_type[0].lower()
        old_line = f"{file_type} File={prefix}{old_number}"
        new_line_content = f"{file_type} File={prefix}{new_number}"

        try:
            with open(prj_file, 'r') as f:
                lines = f.readlines()

            found = False
            for i, line in enumerate(lines):
                if line.strip() == old_line:
                    lines[i] = new_line_content + '\n'
                    found = True
                    break

            if not found:
                logger.warning(f"Entry '{old_line}' not found in {prj_file}")
                return

            with open(prj_file, 'w') as f:
                f.writelines(lines)
            logger.info(f"Renamed {file_type} entry {old_number} to {new_number} in project file")
        except Exception as e:
            logger.exception(f"Failed to rename entry in project file {prj_file}")
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

    @staticmethod
    def find_valid_ras_folders(
        search_path: Union[str, Path],
        max_depth: Optional[int] = None,
        return_project_info: bool = False
    ) -> Union[List[Path], List[Dict[str, Any]]]:
        """
        Recursively search for valid HEC-RAS project folders.

        A valid HEC-RAS project folder contains:
        1. A .prj file with "Proj Title=" on the first line (HEC-RAS project file)
        2. At least one .pXX file where XX is 01-99 (plan files)

        This function does NOT require the global ras object to be initialized,
        making it suitable for discovery operations before project initialization.

        Args:
            search_path (Union[str, Path]): Root directory to search for HEC-RAS projects.
            max_depth (Optional[int]): Maximum folder depth to search. None means unlimited.
                Depth 0 = search_path only, 1 = immediate subdirectories, etc.
            return_project_info (bool): If True, return list of dicts with folder path,
                project name, prj file path, and plan count. If False, return list of Paths.

        Returns:
            Union[List[Path], List[Dict[str, Any]]]:
                - If return_project_info=False: List of Path objects for valid HEC-RAS folders
                - If return_project_info=True: List of dicts with keys:
                    - 'folder': Path to the project folder
                    - 'project_name': Name extracted from .prj filename
                    - 'prj_file': Path to the .prj file
                    - 'plan_count': Number of plan files found
                    - 'plan_numbers': List of plan numbers (e.g., ['01', '02', '15'])

        Example:
            >>> # Find all valid HEC-RAS project folders
            >>> folders = RasUtils.find_valid_ras_folders("C:/Projects/Hydrology")
            >>> for folder in folders:
            ...     print(f"Found project: {folder}")

            >>> # Get detailed info about each project
            >>> projects = RasUtils.find_valid_ras_folders(
            ...     "C:/Projects",
            ...     max_depth=3,
            ...     return_project_info=True
            ... )
            >>> for proj in projects:
            ...     print(f"{proj['project_name']}: {proj['plan_count']} plans")

        Note:
            This function distinguishes HEC-RAS .prj files from ESRI projection files
            by checking for "Proj Title=" on the first line of the file.
        """
        search_path = Path(search_path)
        if not search_path.exists():
            logger.warning(f"Search path does not exist: {search_path}")
            return []

        if not search_path.is_dir():
            logger.warning(f"Search path is not a directory: {search_path}")
            return []

        valid_folders = []

        def is_valid_ras_prj(prj_file: Path) -> bool:
            """Check if a .prj file is a valid HEC-RAS project file."""
            try:
                with open(prj_file, 'r', encoding='utf-8', errors='replace') as f:
                    first_line = f.readline()
                    return first_line.strip().startswith("Proj Title=")
            except Exception as e:
                logger.debug(f"Could not read .prj file {prj_file}: {e}")
                return False

        def get_plan_files(folder: Path) -> List[Tuple[str, Path]]:
            """Get all valid plan files (.p01 to .p99) in a folder."""
            plan_files = []
            for i in range(1, 100):
                plan_num = f"{i:02d}"
                # Look for files matching *.pXX pattern
                for pfile in folder.glob(f"*.p{plan_num}"):
                    plan_files.append((plan_num, pfile))
            return plan_files

        def check_folder(folder: Path) -> Optional[Dict[str, Any]]:
            """Check if a folder is a valid HEC-RAS project folder."""
            # Find .prj files
            prj_files = list(folder.glob("*.prj"))

            if not prj_files:
                return None

            # Find valid HEC-RAS .prj file (not ESRI projection file)
            valid_prj = None
            for prj_file in prj_files:
                if is_valid_ras_prj(prj_file):
                    valid_prj = prj_file
                    break

            if valid_prj is None:
                return None

            # Check for plan files
            plan_files = get_plan_files(folder)
            if not plan_files:
                return None

            # This is a valid HEC-RAS project folder
            return {
                'folder': folder,
                'project_name': valid_prj.stem,
                'prj_file': valid_prj,
                'plan_count': len(plan_files),
                'plan_numbers': [pn for pn, _ in plan_files]
            }

        def scan_directory(current_path: Path, current_depth: int):
            """Recursively scan directories for HEC-RAS projects."""
            # Check if we've exceeded max depth
            if max_depth is not None and current_depth > max_depth:
                return

            # Check current folder
            result = check_folder(current_path)
            if result:
                valid_folders.append(result)
                # Don't search subdirectories of a valid project folder
                # (nested projects are uncommon and would cause confusion)
                return

            # Scan subdirectories
            try:
                for item in current_path.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        scan_directory(item, current_depth + 1)
            except PermissionError:
                logger.debug(f"Permission denied accessing: {current_path}")
            except Exception as e:
                logger.debug(f"Error scanning {current_path}: {e}")

        # Start scanning
        logger.info(f"Searching for HEC-RAS projects in: {search_path}")
        scan_directory(search_path, 0)
        logger.info(f"Found {len(valid_folders)} valid HEC-RAS project folders")

        if return_project_info:
            return valid_folders
        else:
            return [info['folder'] for info in valid_folders]

    @staticmethod
    def is_valid_ras_folder(folder_path: Union[str, Path]) -> bool:
        """
        Check if a single folder is a valid HEC-RAS project folder.

        A valid HEC-RAS project folder contains:
        1. A .prj file with "Proj Title=" on the first line
        2. At least one .pXX file where XX is 01-99

        This function does NOT require the global ras object to be initialized.

        Args:
            folder_path (Union[str, Path]): Path to the folder to check.

        Returns:
            bool: True if the folder is a valid HEC-RAS project folder.

        Example:
            >>> if RasUtils.is_valid_ras_folder("C:/Projects/MyRASModel"):
            ...     print("This is a valid HEC-RAS project folder")
            ... else:
            ...     print("Not a valid HEC-RAS project folder")
        """
        folder_path = Path(folder_path)
        if not folder_path.exists() or not folder_path.is_dir():
            return False

        # Find .prj files
        prj_files = list(folder_path.glob("*.prj"))
        if not prj_files:
            return False

        # Check if any .prj file is a valid HEC-RAS project file
        def is_valid_ras_prj(prj_file: Path) -> bool:
            try:
                with open(prj_file, 'r', encoding='utf-8', errors='replace') as f:
                    first_line = f.readline()
                    return first_line.strip().startswith("Proj Title=")
            except Exception:
                return False

        has_valid_prj = any(is_valid_ras_prj(pf) for pf in prj_files)
        if not has_valid_prj:
            return False

        # Check for at least one plan file (.p01 to .p99)
        for i in range(1, 100):
            plan_num = f"{i:02d}"
            if list(folder_path.glob(f"*.p{plan_num}")):
                return True

        return False

    # =============================================================================
    # Atomic File Write Infrastructure (Phase 2.1 - HTAB Modification)
    # =============================================================================

    @staticmethod
    @log_call
    def safe_write_geometry(
        geom_file: Union[str, Path],
        modified_lines: List[str],
        create_backup: bool = True
    ) -> Optional[Path]:
        """
        Atomically write geometry file with backup for safe file modification.

        This function implements safe file modification for HEC-RAS geometry files,
        ensuring data integrity through atomic operations and optional backup creation.

        Process:
            1. Create timestamped backup: geom_file.YYYYMMDD_HHMMSS.bak
            2. Write to temp file: geom_file.tmp
            3. Basic validation (line count reasonable, file size reasonable)
            4. Atomic rename temp -> original (os.replace)
            5. Return backup path

        Parameters:
            geom_file (Union[str, Path]): Path to the geometry file to write.
            modified_lines (List[str]): List of lines to write to the file.
                Each line should include newline characters if needed.
            create_backup (bool): If True, create timestamped backup before modification.
                Defaults to True for safety.

        Returns:
            Optional[Path]: Path to backup file if create_backup=True and successful,
                None if create_backup=False or file didn't exist before.

        Raises:
            FileNotFoundError: If the geometry file doesn't exist (for modification).
            PermissionError: If write access is denied to the file or directory.
            ValueError: If modified_lines is empty or validation fails.
            IOError: If atomic rename fails.

        Example:
            >>> from ras_commander import RasUtils
            >>> from pathlib import Path
            >>>
            >>> # Read geometry file
            >>> geom_file = Path("project/geometry.g01")
            >>> with open(geom_file, 'r') as f:
            ...     lines = f.readlines()
            >>>
            >>> # Modify HTAB parameters (example)
            >>> modified_lines = modify_htab_params(lines, starting_el=580.0)
            >>>
            >>> # Safe write with backup
            >>> backup_path = RasUtils.safe_write_geometry(geom_file, modified_lines)
            >>> print(f"Backup created at: {backup_path}")

        Notes:
            - This function uses os.replace() for atomic rename, which is atomic on
              both Windows (NTFS) and Unix filesystems.
            - Backup files use format: filename.YYYYMMDD_HHMMSS.bak
            - If validation fails, temp file is deleted and original remains unchanged.
            - For rollback, use rollback_geometry() with the returned backup path.

        See Also:
            - rollback_geometry: Restore from backup after failed modification
            - .claude/rules/python/path-handling.md: Path handling patterns
        """
        geom_file = Path(geom_file)
        backup_path = None
        temp_path = None

        # Validate inputs
        if not modified_lines:
            raise ValueError("modified_lines cannot be empty")

        # Verify original file exists (we're modifying, not creating)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Check write permissions
        if not os.access(geom_file.parent, os.W_OK):
            raise PermissionError(f"Write permission denied for directory: {geom_file.parent}")

        try:
            # Read original file for validation comparison
            original_size = geom_file.stat().st_size
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                original_line_count = sum(1 for _ in f)

            # Step 1: Create timestamped backup
            if create_backup:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = geom_file.parent / f"{geom_file.name}.{timestamp}.bak"

                # Copy original to backup
                shutil.copy2(geom_file, backup_path)
                logger.info(f"Backup created: {backup_path}")

            # Step 2: Write to temp file
            temp_path = geom_file.parent / f"{geom_file.name}.tmp"
            with open(temp_path, 'w', encoding='utf-8', newline='') as f:
                f.writelines(modified_lines)
            logger.debug(f"Temp file written: {temp_path}")

            # Step 3: Basic validation
            temp_size = temp_path.stat().st_size
            new_line_count = len(modified_lines)

            # Validation: File shouldn't be empty
            if temp_size == 0:
                raise ValueError("Modified file would be empty - validation failed")

            # Validation: Line count shouldn't change drastically (>50% reduction suspicious)
            if new_line_count < original_line_count * 0.5:
                raise ValueError(
                    f"Line count reduced drastically ({original_line_count} -> {new_line_count}). "
                    f"This may indicate data corruption. Aborting."
                )

            # Validation: File size shouldn't shrink too much (>80% reduction suspicious)
            if temp_size < original_size * 0.2:
                raise ValueError(
                    f"File size reduced drastically ({original_size} -> {temp_size} bytes). "
                    f"This may indicate data corruption. Aborting."
                )

            logger.debug(
                f"Validation passed: {new_line_count} lines, {temp_size} bytes "
                f"(original: {original_line_count} lines, {original_size} bytes)"
            )

            # Step 4: Atomic rename temp -> original
            # os.replace() is atomic on both Windows (NTFS) and Unix
            os.replace(temp_path, geom_file)
            temp_path = None  # Mark as successfully moved
            logger.info(f"Geometry file atomically updated: {geom_file}")

            return backup_path

        except Exception as e:
            # Clean up temp file if it exists
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up temp file {temp_path}: {cleanup_error}")

            logger.error(f"Failed to write geometry file {geom_file}: {e}")
            raise

    @staticmethod
    @log_call
    def rollback_geometry(
        geom_file: Union[str, Path],
        backup_path: Union[str, Path]
    ) -> None:
        """
        Restore geometry file from backup after failed modification.

        This function restores a geometry file from a previously created backup,
        typically used when a modification operation fails or produces incorrect results.

        Process:
            1. Verify backup file exists
            2. Copy backup -> original (preserves backup for safety)
            3. Log restoration

        Parameters:
            geom_file (Union[str, Path]): Path to the geometry file to restore.
            backup_path (Union[str, Path]): Path to the backup file created by
                safe_write_geometry().

        Returns:
            None

        Raises:
            FileNotFoundError: If backup file doesn't exist.
            PermissionError: If write access is denied.
            IOError: If copy operation fails.

        Example:
            >>> from ras_commander import RasUtils
            >>> from pathlib import Path
            >>>
            >>> # Attempt modification
            >>> try:
            ...     backup = RasUtils.safe_write_geometry(geom_file, modified_lines)
            ...     # Run HEC-RAS to validate
            ...     RasCmdr.compute_plan("01", clear_geompre=True)
            ... except Exception as e:
            ...     # Modification failed - rollback
            ...     if backup:
            ...         RasUtils.rollback_geometry(geom_file, backup)
            ...         print("Geometry file restored from backup")
            ...     raise

        Notes:
            - This function copies the backup to original, preserving the backup.
            - Use shutil.copy2() to preserve file metadata (timestamps, permissions).
            - After successful rollback, you may want to delete the backup manually
              if no longer needed.

        See Also:
            - safe_write_geometry: Create backup and safely write modifications
        """
        geom_file = Path(geom_file)
        backup_path = Path(backup_path)

        # Verify backup exists
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Check write permissions
        if geom_file.exists() and not os.access(geom_file, os.W_OK):
            raise PermissionError(f"Write permission denied for file: {geom_file}")

        if not os.access(geom_file.parent, os.W_OK):
            raise PermissionError(f"Write permission denied for directory: {geom_file.parent}")

        try:
            # Copy backup to original (preserves backup for safety)
            shutil.copy2(backup_path, geom_file)
            logger.info(f"Geometry file restored from backup: {geom_file} <- {backup_path}")

        except Exception as e:
            logger.error(f"Failed to restore geometry file {geom_file} from {backup_path}: {e}")
            raise

    @staticmethod
    @log_call
    def validate_geometry_file_basic(
        geom_file: Union[str, Path],
        min_lines: int = 10,
        required_patterns: Optional[List[str]] = None
    ) -> bool:
        """
        Perform basic validation on a geometry file.

        This function checks that a geometry file meets basic structural requirements,
        useful for pre-modification validation or post-write verification.

        Parameters:
            geom_file (Union[str, Path]): Path to the geometry file to validate.
            min_lines (int): Minimum number of lines expected. Defaults to 10.
            required_patterns (Optional[List[str]]): List of strings that must appear
                somewhere in the file. Defaults to ["River Reach="] for HEC-RAS geometry.

        Returns:
            bool: True if validation passes, False otherwise.

        Example:
            >>> if RasUtils.validate_geometry_file_basic(geom_file):
            ...     print("Geometry file appears valid")
            >>>
            >>> # Custom validation
            >>> if RasUtils.validate_geometry_file_basic(
            ...     geom_file,
            ...     required_patterns=["River Reach=", "Type RM Length"]
            ... ):
            ...     print("Geometry file has cross sections")

        Notes:
            - This is a basic structural check, not a full HEC-RAS validation.
            - For comprehensive validation, use HEC-RAS geometric preprocessor.
        """
        geom_file = Path(geom_file)

        if required_patterns is None:
            # Default: Check for River Reach definition (present in most geometry files)
            required_patterns = ["River Reach="]

        if not geom_file.exists():
            logger.warning(f"Geometry file does not exist: {geom_file}")
            return False

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                lines = content.splitlines()

            # Check minimum line count
            if len(lines) < min_lines:
                logger.warning(
                    f"Geometry file has too few lines: {len(lines)} < {min_lines}"
                )
                return False

            # Check required patterns
            for pattern in required_patterns:
                if pattern not in content:
                    logger.warning(f"Required pattern not found in geometry file: {pattern}")
                    return False

            logger.debug(f"Geometry file validation passed: {geom_file}")
            return True

        except Exception as e:
            logger.error(f"Error validating geometry file {geom_file}: {e}")
            return False

    @staticmethod
    def _read_description_block(file_path: Union[str, Path]) -> str:
        """
        Read the BEGIN DESCRIPTION / END DESCRIPTION block from any HEC-RAS text file.

        HEC-RAS uses the same description block format in plan (.p##), geometry (.g##),
        unsteady (.u##), and steady flow (.f##) files.

        Parameters:
            file_path (Union[str, Path]): Path to the HEC-RAS text file.

        Returns:
            str: The description text, or empty string if no description block found.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning(f"File not found for description read: {file_path}")
            return ""

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except IOError as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return ""

        description_lines = []
        in_description = False
        for line in lines:
            stripped_upper = line.strip().upper()
            if stripped_upper in ('BEGIN DESCRIPTION:', 'BEGIN DESCRIPTION'):
                in_description = True
            elif stripped_upper in ('END DESCRIPTION:', 'END DESCRIPTION'):
                break
            elif in_description:
                description_lines.append(line.strip())

        return '\n'.join(description_lines)

    @staticmethod
    def _write_description_block(
        file_path: Union[str, Path],
        description: str,
        title_keyword: str
    ) -> bool:
        """
        Write a BEGIN DESCRIPTION / END DESCRIPTION block into any HEC-RAS text file.

        If an existing description block is found, it is replaced in place.
        If no description block exists, a new one is inserted after the title and
        Program Version lines.

        Parameters:
            file_path (Union[str, Path]): Path to the HEC-RAS text file.
            description (str): Description text to write.
            title_keyword (str): The title keyword for this file type, e.g.
                'Plan Title', 'Geom Title', 'Flow Title'. Used to determine
                insertion point when no existing description block is found.

        Returns:
            bool: True if successful, False otherwise.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found for description write: {file_path}")
            return False

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except IOError as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return False

        # Find existing description block
        desc_start_idx = None
        desc_end_idx = None
        for i, line in enumerate(lines):
            stripped_upper = line.strip().upper()
            if stripped_upper.startswith('BEGIN DESCRIPTION'):
                desc_start_idx = i
            elif stripped_upper.startswith('END DESCRIPTION'):
                desc_end_idx = i
                break

        # Prepare the new description block
        description_clean = description.rstrip()
        description_block = [
            'BEGIN DESCRIPTION:\n',
            description_clean + '\n',
            'END DESCRIPTION:\n'
        ]

        if desc_start_idx is not None and desc_end_idx is not None:
            # Replace existing description block in place
            new_lines = lines[:desc_start_idx] + description_block + lines[desc_end_idx + 1:]
        else:
            # Find insertion point: after title_keyword= and Program Version= lines
            last_header_idx = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f'{title_keyword}=') or stripped.startswith('Program Version='):
                    last_header_idx = max(last_header_idx, i)
            insertion_idx = last_header_idx + 1
            new_lines = lines[:insertion_idx] + description_block + lines[insertion_idx:]

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            logger.info(f"Updated description in {file_path}")
            return True
        except IOError as e:
            logger.error(f"Error writing description to {file_path}: {e}")
            return False
