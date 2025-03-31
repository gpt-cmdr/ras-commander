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
        
        
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasGeo:
- clear_geompre_files()
        
        
"""
import os
from pathlib import Path
from typing import List, Union
import pandas as pd  # Added pandas import
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
        Clear HEC-RAS geometry preprocessor files for specified plan files.

        Geometry preprocessor files (.c* extension) contain computed hydraulic properties derived
        from the geometry. These should be cleared when the geometry changes to ensure that
        HEC-RAS recomputes all hydraulic tables with updated geometry information.

        Limitations/Future Work:
        - This function only deletes the geometry preprocessor file.
        - It does not clear the IB tables.
        - It also does not clear geometry preprocessor tables from the geometry HDF.
        - All of these features will need to be added to reliably remove geometry preprocessor 
          files for 1D and 2D projects.
        
        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional): 
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object: An optional RAS object instance.
        
        Returns:
            None: The function deletes files and updates the ras object's geometry dataframe

        Example:
            # Clone a plan and geometry
            new_plan_number = RasPlan.clone_plan("01")
            new_geom_number = RasPlan.clone_geom("01")
            
            # Set the new geometry for the cloned plan
            RasPlan.set_geom(new_plan_number, new_geom_number)
            plan_path = RasPlan.get_plan_path(new_plan_number)
            
            # Clear geometry preprocessor files to ensure clean results
            RasGeo.clear_geompre_files(plan_path)
            print(f"Cleared geometry preprocessor files for plan {new_plan_number}")
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



    @staticmethod
    def get_mannings_override_tables(geom_file_path, ras_object=None):
        """
        Extracts Manning's override region tables from a HEC-RAS geometry file.
        
        Args:
            geom_file_path (str or Path): Geometry file path or geometry number (e.g., "01").
            ras_object (RasPrj, optional): RAS project object for context. Defaults to global 'ras'.
        
        Returns:
            pd.DataFrame: DataFrame containing Manning's override region tables with columns:
                - Region Name: Name of the override region
                - Land Use Type: Land use type or description
                - Mannings N Value: Manning's n value for the land use type
                - Polygon Value: Polygon value or ID associated with the region
                
        Raises:
            FileNotFoundError: If the geometry file doesn't exist.
            ValueError: If the geometry file number is invalid.
        """
        # Get the full path to the geometry file if a number was provided
        if isinstance(geom_file_path, (str, int)) and not str(geom_file_path).endswith('.g'):
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            geom_file_path = RasPlan.get_geom_path(str(geom_file_path), ras_object=ras_obj)
            if geom_file_path is None:
                raise ValueError(f"Geometry file number '{geom_file_path}' not found in project")
        
        geom_file_path = Path(geom_file_path)
        if not geom_file_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file_path}")
        
        # Lists for storing data
        region_names, land_use_types, mannings_values, polygon_values = [], [], [], []
        
        region_name, table_value, polygon_value = "", 0, ""
        
        with open(geom_file_path, 'r') as file:
            lines = file.readlines()
            
            i = 0  # Initialize line counter
            while i < len(lines):
                line = lines[i].strip()
                
                if "LCMann Region Name=" in line:
                    region_name = line.split("=")[1]
                    i += 1  # Move to the next line
                    continue
                    
                if "LCMann Region Table=" in line:
                    table_value = int(line.split("=")[1])
                    i += 1  # Skip to the next line which starts the table entries
                    for j in range(table_value):
                        if i+j < len(lines):
                            # Handle multiple commas by splitting from the right
                            parts = lines[i+j].strip().rsplit(",", 1)
                            if len(parts) == 2:
                                land_use, mannings = parts
                                try:
                                    mannings_float = float(mannings)
                                    region_names.append(region_name)
                                    land_use_types.append(land_use)
                                    mannings_values.append(mannings_float)
                                    polygon_values.append(polygon_value)  # This will repeat the last polygon_value
                                except ValueError:
                                    # Skip if Manning's value is not a valid float
                                    pass
                    
                    i += table_value  # Skip past the table entries
                    continue
                    
                if "LCMann Region Polygon=" in line:
                    polygon_value = line.split("=")[1]
                    i += 1  # Move to the next line
                    continue
                    
                i += 1  # Move to the next line if none of the conditions above are met
        
        # Create DataFrame
        mannings_tables = pd.DataFrame({
            "Region Name": region_names,
            "Land Use Type": land_use_types,
            "Mannings N Value": mannings_values,
            "Polygon Value": polygon_values
        })
        
        return mannings_tables



    @staticmethod
    @log_call
    def set_mannings_override_tables(geom_file_path, mannings_df, ras_object=None):
        """
        Updates Manning's override region tables in a HEC-RAS geometry file based on provided dataframe.
        
        This function takes a dataframe of Manning's values (similar to the one returned by
        extract_mannings_override_tables) and updates the corresponding values in the geometry file.
        If Region Name is specified in the dataframe, only updates that specific region.
        If no Region Name is given for a row, it updates all instances of the Land Use Type
        across all regions in the geometry file.
        
        Args:
            geom_file_path (str or Path): Geometry file path or geometry number (e.g., "01").
            mannings_df (pd.DataFrame): DataFrame containing Manning's override values with columns:
                - Land Use Type: Land use type or description (required)
                - Mannings N Value: Manning's n value for the land use type (required)
                - Region Name: Name of the override region (optional)
            ras_object (RasPrj, optional): RAS project object for context. Defaults to global 'ras'.
                    
        Returns:
            bool: True if successful, False otherwise.
            
        Raises:
            FileNotFoundError: If the geometry file doesn't exist.
            ValueError: If the geometry file number is invalid or required columns are missing.
            
        Example:
            # Get existing Manning's tables
            mannings_tables = RasGeo.extract_mannings_override_tables("01")
            
            # Update specific values
            mannings_tables.loc[mannings_tables['Land Use Type'] == 'Open Water', 'Mannings N Value'] = 0.030
            
            # Update all forest types in all regions
            forest_updates = pd.DataFrame({
                'Land Use Type': ['Mixed Forest', 'Deciduous Forest', 'Evergreen Forest'],
                'Mannings N Value': [0.040, 0.042, 0.045]
            })
            
            # Apply the changes
            RasGeo.set_mannings_override_tables("01", mannings_tables)
            # Or apply just the forest updates to all regions
            RasGeo.set_mannings_override_tables("01", forest_updates)
        """
        # Get the full path to the geometry file if a number was provided
        if isinstance(geom_file_path, (str, int)) and not str(geom_file_path).endswith('.g'):
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            geom_file_path = RasPlan.get_geom_path(str(geom_file_path), ras_object=ras_obj)
            if geom_file_path is None:
                raise ValueError(f"Geometry file number '{geom_file_path}' not found in project")
        
        geom_file_path = Path(geom_file_path)
        if not geom_file_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file_path}")
        
        # Verify required columns exist
        required_columns = ['Land Use Type', 'Mannings N Value']
        if not all(col in mannings_df.columns for col in required_columns):
            raise ValueError(f"DataFrame must contain columns: {required_columns}")
        
        # Create a dictionary for easier lookups
        update_dict = {}
        for _, row in mannings_df.iterrows():
            land_use = row['Land Use Type']
            manning_value = row['Mannings N Value']
            region_name = row.get('Region Name', None)  # Optional column
            
            if region_name:
                if region_name not in update_dict:
                    update_dict[region_name] = {}
                update_dict[region_name][land_use] = manning_value
            else:
                # Special key for updates that apply to all regions
                if 'ALL_REGIONS' not in update_dict:
                    update_dict['ALL_REGIONS'] = {}
                update_dict['ALL_REGIONS'][land_use] = manning_value
        
        logger.info(f"Updating Manning's n values in geometry file: {geom_file_path}")
        
        # Read the entire file
        with open(geom_file_path, 'r') as file:
            lines = file.readlines()
        
        # Process the file line by line
        modified_lines = []
        current_region = None
        in_table = False
        table_start_index = -1
        table_size = 0
        
        i = 0
        while i < len(lines):
            line = lines[i]
            modified_lines.append(line)  # Add line by default, may modify later
            
            if "LCMann Region Name=" in line:
                current_region = line.split("=")[1].strip()
                in_table = False
            
            elif "LCMann Region Table=" in line:
                in_table = True
                table_start_index = len(modified_lines)
                try:
                    table_size = int(line.split("=")[1].strip())
                except ValueError:
                    logger.warning(f"Invalid table size at line: {line}")
                    table_size = 0
            
            elif in_table and table_size > 0:
                # We're inside a Manning's table
                land_use_entry = line.strip()
                if "," in land_use_entry:
                    parts = land_use_entry.rsplit(",", 1)
                    if len(parts) == 2:
                        land_use, _ = parts
                        
                        # Check if we should update this entry
                        update_value = None
                        
                        # First check region-specific updates
                        if current_region in update_dict and land_use in update_dict[current_region]:
                            update_value = update_dict[current_region][land_use]
                        
                        # Then check global updates (ALL_REGIONS)
                        elif 'ALL_REGIONS' in update_dict and land_use in update_dict['ALL_REGIONS']:
                            update_value = update_dict['ALL_REGIONS'][land_use]
                        
                        if update_value is not None:
                            # Replace the last entry in modified_lines with updated Manning's value
                            modified_lines[-1] = f"{land_use},{update_value}\n"
                            logger.debug(f"Updated '{land_use}' in region '{current_region}' to {update_value}")
                
                # Decrement counter for table entries
                table_size -= 1
                if table_size == 0:
                    in_table = False
            
            i += 1
        
        # Write the file back
        with open(geom_file_path, 'w') as file:
            file.writelines(modified_lines)
        
        logger.info(f"Successfully updated Manning's n values in geometry file: {geom_file_path}")
        return True




