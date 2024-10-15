"""
RasUnsteady - Operations for handling unsteady flow files in HEC-RAS projects.

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
"""
import os
from pathlib import Path
from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Module code starts here

class RasUnsteady:
    """
    Class for all operations related to HEC-RAS unsteady flow files.
    """
    
    @staticmethod
    @log_call
    def update_unsteady_parameters(unsteady_file, modifications, ras_object=None):
        """
        Modify parameters in an unsteady flow file.
        
        Parameters:
        unsteady_file (str): Full path to the unsteady flow file
        modifications (dict): Dictionary of modifications to apply, where keys are parameter names and values are new values
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Note:
            This function updates the ras object's unsteady dataframe after modifying the unsteady flow file.
        
        Example:
            from ras_commander import RasCmdr
            
            # Initialize RAS project
            ras_cmdr = RasCmdr()
            ras_cmdr.init_ras_project(project_folder, ras_version)
            
            # Update unsteady parameters
            unsteady_file = r"path/to/unsteady_file.u01"
            modifications = {"Parameter1": "NewValue1", "Parameter2": "NewValue2"}
            RasUnsteady.update_unsteady_parameters(unsteady_file, modifications, ras_object=ras_cmdr.ras)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r') as f:
                lines = f.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")
        
        updated = False
        for i, line in enumerate(lines):
            for param, new_value in modifications.items():
                if line.startswith(f"{param}="):
                    old_value = line.strip().split('=')[1]
                    lines[i] = f"{param}={new_value}\n"
                    updated = True
                    logger.info(f"Updated {param} from {old_value} to {new_value}")
        
        if updated:
            try:
                with open(unsteady_path, 'w') as f:
                    f.writelines(lines)
                logger.debug(f"Successfully wrote modifications to unsteady flow file: {unsteady_path}")
            except PermissionError:
                logger.error(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
                raise PermissionError(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            except IOError as e:
                logger.error(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
                raise IOError(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            logger.info(f"Applied modifications to {unsteady_file}")
        else:
            logger.warning(f"No matching parameters found in {unsteady_file}")
    
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
