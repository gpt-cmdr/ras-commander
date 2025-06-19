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
        
        
All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasGeo:
- clear_geompre_files(): Clears geometry preprocessor files for specified plan files
- get_mannings_baseoverrides(): Reads base Manning's n table from a geometry file
- get_mannings_regionoverrides(): Reads Manning's n region overrides from a geometry file
- set_mannings_baseoverrides(): Writes base Manning's n values to a geometry file
- set_mannings_regionoverrides(): Writes regional Manning's n overrides to a geometry file
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
    @log_call
    def get_mannings_baseoverrides(geom_file_path):
        """
        Reads the base Manning's n table from a HEC-RAS geometry file.
        
        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        
        Returns:
        --------
        pandas.DataFrame
            DataFrame with Table Number, Land Cover Name, and Base Manning's n Value
            
        Example:
        --------
        >>> geom_path = RasPlan.get_geom_path("01")
        >>> mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
        >>> print(mannings_df)
        """
        import pandas as pd
        from pathlib import Path
        
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)
        
        base_table_rows = []
        table_number = None
        
        # Read the geometry file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()
        
        # Parse the file
        reading_base_table = False
        for line in lines:
            line = line.strip()
            
            # Find the table number
            if line.startswith('LCMann Table='):
                table_number = line.split('=')[1]
                reading_base_table = True
                continue
            
            # Stop reading when we hit a line without a comma or starting with LCMann
            if reading_base_table and (not ',' in line or line.startswith('LCMann')):
                reading_base_table = False
                continue
                
            # Parse data rows in base table
            if reading_base_table and ',' in line:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts
                
                try:
                    base_table_rows.append([table_number, name, float(value)])
                except ValueError:
                    # Log the error and continue
                    print(f"Error parsing line: {line}")
                    continue
        
        # Create DataFrame
        if base_table_rows:
            df = pd.DataFrame(base_table_rows, columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])
            return df
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])


    @staticmethod
    @log_call
    def get_mannings_regionoverrides(geom_file_path):
        """
        Reads the Manning's n region overrides from a HEC-RAS geometry file.
        
        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        
        Returns:
        --------
        pandas.DataFrame
            DataFrame with Table Number, Land Cover Name, MainChannel value, and Region Name
            
        Example:
        --------
        >>> geom_path = RasPlan.get_geom_path("01")
        >>> region_overrides_df = RasGeo.get_mannings_regionoverrides(geom_path)
        >>> print(region_overrides_df)
        """
        import pandas as pd
        from pathlib import Path
        
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)
        
        region_rows = []
        current_region = None
        current_table = None
        
        # Read the geometry file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()
        
        # Parse the file
        reading_region_table = False
        for line in lines:
            line = line.strip()
            
            # Find region name
            if line.startswith('LCMann Region Name='):
                current_region = line.split('=')[1]
                continue
                
            # Find region table number
            if line.startswith('LCMann Region Table='):
                current_table = line.split('=')[1]
                reading_region_table = True
                continue
            
            # Stop reading when we hit a line without a comma or starting with LCMann
            if reading_region_table and (not ',' in line or line.startswith('LCMann')):
                reading_region_table = False
                continue
                
            # Parse data rows in region table
            if reading_region_table and ',' in line and current_region is not None:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts
                
                try:
                    region_rows.append([current_table, name, float(value), current_region])
                except ValueError:
                    # Log the error and continue
                    print(f"Error parsing line: {line}")
                    continue
        
        # Create DataFrame
        if region_rows:
            return pd.DataFrame(region_rows, columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])
        


    @staticmethod
    @log_call
    def set_mannings_baseoverrides(geom_file_path, mannings_data):
        """
        Writes base Manning's n values to a HEC-RAS geometry file.
        
        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        mannings_data : DataFrame
            DataFrame with columns 'Table Number', 'Land Cover Name', and 'Base Manning\'s n Value'
        
        Returns:
        --------
        bool
            True if successful
        """
        from pathlib import Path
        import shutil
        import pandas as pd
        import datetime
        
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)
        
        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)
        
        # Read the entire file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()
        
        # Find the Manning's table section
        table_number = str(mannings_data['Table Number'].iloc[0])
        start_idx = None
        end_idx = None
        
        for i, line in enumerate(lines):
            if line.strip() == f"LCMann Table={table_number}":
                start_idx = i
                # Find the end of this table (next LCMann directive or end of file)
                for j in range(i+1, len(lines)):
                    if lines[j].strip().startswith('LCMann'):
                        end_idx = j
                        break
                if end_idx is None:  # If we reached the end of the file
                    end_idx = len(lines)
                break
        
        if start_idx is None:
            raise ValueError(f"Manning's table {table_number} not found in the geometry file")
        
        # Extract existing land cover names from the file
        existing_landcover = []
        for i in range(start_idx+1, end_idx):
            line = lines[i].strip()
            if ',' in line:
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                else:
                    name = parts[0]
                existing_landcover.append(name)
        
        # Check if all land cover names in the dataframe match the file
        df_landcover = mannings_data['Land Cover Name'].tolist()
        if set(df_landcover) != set(existing_landcover):
            missing = set(existing_landcover) - set(df_landcover)
            extra = set(df_landcover) - set(existing_landcover)
            error_msg = "Land cover names don't match between file and dataframe.\n"
            if missing:
                error_msg += f"Missing in dataframe: {missing}\n"
            if extra:
                error_msg += f"Extra in dataframe: {extra}"
            raise ValueError(error_msg)
        
        # Create new content for the table
        new_content = [f"LCMann Table={table_number}\n"]
        
        # Add base table entries
        for _, row in mannings_data.iterrows():
            new_content.append(f"{row['Land Cover Name']},{row['Base Manning''s n Value']}\n")
        
        # Replace the section in the original file
        updated_lines = lines[:start_idx] + new_content + lines[end_idx:]
        
        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(updated_lines):
            if line.strip().startswith("LCMann Time="):
                updated_lines[i] = f"LCMann Time={current_time}\n"
                break
        
        # Write the updated file
        with open(geom_file_path, 'w') as f:
            f.writelines(updated_lines)
        
        return True







    @staticmethod
    @log_call
    def set_mannings_regionoverrides(geom_file_path, mannings_data):
        """
        Writes regional Manning's n overrides to a HEC-RAS geometry file.
        
        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        mannings_data : DataFrame
            DataFrame with columns 'Table Number', 'Land Cover Name', 'MainChannel', and 'Region Name'
        
        Returns:
        --------
        bool
            True if successful
        """
        from pathlib import Path
        import shutil
        import pandas as pd
        import datetime
        
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)
        
        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)
        
        # Read the entire file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()
        
        # Group data by region
        regions = mannings_data.groupby('Region Name')
        
        # Find the Manning's region sections
        for region_name, region_data in regions:
            table_number = str(region_data['Table Number'].iloc[0])
            
            # Find the region section
            region_start_idx = None
            region_table_idx = None
            region_end_idx = None
            region_polygon_line = None
            
            for i, line in enumerate(lines):
                if line.strip() == f"LCMann Region Name={region_name}":
                    region_start_idx = i
                
                if region_start_idx is not None and line.strip() == f"LCMann Region Table={table_number}":
                    region_table_idx = i
                    
                    # Find the end of this region (next LCMann Region or end of file)
                    for j in range(i+1, len(lines)):
                        if lines[j].strip().startswith('LCMann Region Name=') or lines[j].strip().startswith('LCMann Region Polygon='):
                            if lines[j].strip().startswith('LCMann Region Polygon='):
                                region_polygon_line = lines[j]
                            region_end_idx = j
                            break
                    if region_end_idx is None:  # If we reached the end of the file
                        region_end_idx = len(lines)
                    break
            
            if region_start_idx is None or region_table_idx is None:
                raise ValueError(f"Region {region_name} with table {table_number} not found in the geometry file")
            
            # Extract existing land cover names from the file
            existing_landcover = []
            for i in range(region_table_idx+1, region_end_idx):
                line = lines[i].strip()
                if ',' in line and not line.startswith('LCMann'):
                    parts = line.split(',')
                    if len(parts) > 2:
                        # Handle case where land cover name contains commas
                        name = ','.join(parts[:-1])
                    else:
                        name = parts[0]
                    existing_landcover.append(name)
            
            # Check if all land cover names in the dataframe match the file
            df_landcover = region_data['Land Cover Name'].tolist()
            if set(df_landcover) != set(existing_landcover):
                missing = set(existing_landcover) - set(df_landcover)
                extra = set(df_landcover) - set(existing_landcover)
                error_msg = f"Land cover names for region {region_name} don't match between file and dataframe.\n"
                if missing:
                    error_msg += f"Missing in dataframe: {missing}\n"
                if extra:
                    error_msg += f"Extra in dataframe: {extra}"
                raise ValueError(error_msg)
            
            # Create new content for the region
            new_content = [
                f"LCMann Region Name={region_name}\n",
                f"LCMann Region Table={table_number}\n"
            ]
            
            # Add region table entries
            for _, row in region_data.iterrows():
                new_content.append(f"{row['Land Cover Name']},{row['MainChannel']}\n")
            
            # Add the region polygon line if it exists
            if region_polygon_line:
                new_content.append(region_polygon_line)
            
            # Replace the section in the original file
            if region_polygon_line:
                # If we have a polygon line, include it in the replacement
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx+1:]
            else:
                # If no polygon line, just replace up to the end index
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx:]
            
            # Update the lines for the next region
            lines = updated_lines
        
        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(lines):
            if line.strip().startswith("LCMann Region Time="):
                lines[i] = f"LCMann Region Time={current_time}\n"
                break
        
        # Write the updated file
        with open(geom_file_path, 'w') as f:
            f.writelines(lines)
        
        return True