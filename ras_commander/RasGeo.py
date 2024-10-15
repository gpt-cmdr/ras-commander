"""
RasGeo - Operations for handling geometry files in HEC-RAS projects

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
import os
from pathlib import Path
from typing import List, Union
from .RasPlan import RasPlan
from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

class RasGeo:
    """
    A class for operations on HEC-RAS geometry files.
    """
    
    @staticmethod
    @log_call
    def clear_geompre_files(
        plan_files: Union[str, Path, List[Union[str, Path]]] = None,
        ras_object = None
    ) -> None:
        """
        Clear HEC-RAS geometry preprocessor files for specified plan files or all plan files in the project directory.
        
        Limitations/Future Work:
        - This function only deletes the geometry preprocessor file.
        - It does not clear the IB tables.
        - It also does not clear geometry preprocessor tables from the geometry HDF.
        - All of these features will need to be added to reliably remove geometry preprocessor files for 1D and 2D projects.
        
        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional): 
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object: An optional RAS object instance.
        
        Returns:
            None
        
        Examples:
            # Clear all geometry preprocessor files in the project directory
            RasGeo.clear_geompre_files()
            
            # Clear a single plan file
            RasGeo.clear_geompre_files(r'path/to/plan.p01')
            
            # Clear multiple plan files
            RasGeo.clear_geompre_files([r'path/to/plan1.p01', r'path/to/plan2.p02'])

        Note:
            This function updates the ras object's geometry dataframe after clearing the preprocessor files.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        def clear_single_file(plan_file: Union[str, Path], ras_obj) -> None:
            plan_path = Path(plan_file)
            geom_preprocessor_suffix = '.c' + ''.join(plan_path.suffixes[1:]) if plan_path.suffixes else '.c'
            geom_preprocessor_file = plan_path.with_suffix(geom_preprocessor_suffix)
            if geom_preprocessor_file.exists():
                try:
                    geom_preprocessor_file.unlink()
                    logger.info(f"Deleted geometry preprocessor file: {geom_preprocessor_file}")
                except PermissionError:
                    logger.error(f"Permission denied: Unable to delete geometry preprocessor file: {geom_preprocessor_file}")
                    raise PermissionError(f"Unable to delete geometry preprocessor file: {geom_preprocessor_file}. Permission denied.")
                except OSError as e:
                    logger.error(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
                    raise OSError(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
            else:
                logger.warning(f"No geometry preprocessor file found for: {plan_file}")
        
        if plan_files is None:
            logger.info("Clearing all geometry preprocessor files in the project directory.")
            plan_files_to_clear = list(ras_obj.project_folder.glob(r'*.p*'))
        elif isinstance(plan_files, (str, Path)):
            plan_files_to_clear = [plan_files]
            logger.info(f"Clearing geometry preprocessor file for single plan: {plan_files}")
        elif isinstance(plan_files, list):
            plan_files_to_clear = plan_files
            logger.info(f"Clearing geometry preprocessor files for multiple plans: {plan_files}")
        else:
            logger.error("Invalid input type for plan_files.")
            raise ValueError("Invalid input. Please provide a string, Path, list of paths, or None.")
        
        for plan_file in plan_files_to_clear:
            clear_single_file(plan_file, ras_obj)
        
        try:
            ras_obj.geom_df = ras_obj.get_geom_entries()
            logger.info("Geometry dataframe updated successfully.")
        except Exception as e:
            logger.error(f"Failed to update geometry dataframe: {str(e)}")
            raise








