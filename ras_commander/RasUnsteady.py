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
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasUnsteady:
- update_flow_title()
- update_restart_settings()
- extract_boundary_and_tables()
- print_boundaries_and_tables()
- identify_tables()
- parse_fixed_width_table()
- extract_tables()
- write_table_to_file()
        
"""
import os
from pathlib import Path
from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call
import pandas as pd
import numpy as np
import re
from typing import Union, Optional, Any, Tuple, Dict, List



logger = get_logger(__name__)

# Module code starts here

class RasUnsteady:
    """
    Class for all operations related to HEC-RAS unsteady flow files.
    """
    @staticmethod
    @log_call
    def update_flow_title(unsteady_file: str, new_title: str, ras_object: Optional[Any] = None) -> None:
        """
        Update the Flow Title in an unsteady flow file.
        
        Parameters:
        unsteady_file (str): Full path to the unsteady flow file
        new_title (str): New flow title (max 24 characters)
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
            
            # Update flow title
            unsteady_file = r"path/to/unsteady_file.u01"
            new_title = "New Flow Title"
            RasUnsteady.update_flow_title(unsteady_file, new_title, ras_object=ras_cmdr.ras)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        unsteady_path = Path(unsteady_file)
        new_title = new_title[:24]  # Truncate to 24 characters if longer
        
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
            if line.startswith("Flow Title="):
                old_title = line.strip().split('=')[1]
                lines[i] = f"Flow Title={new_title}\n"
                updated = True
                logger.info(f"Updated Flow Title from '{old_title}' to '{new_title}'")
                break
        
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
            logger.info(f"Applied Flow Title modification to {unsteady_file}")
        else:
            logger.warning(f"Flow Title not found in {unsteady_file}")
    
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def update_restart_settings(unsteady_file: str, use_restart: bool, restart_filename: Optional[str] = None, ras_object: Optional[Any] = None) -> None:
        """
        Update the Use Restart settings in an unsteady flow file.
        
        Parameters:
        unsteady_file (str): Full path to the unsteady flow file
        use_restart (bool): Whether to use restart (True) or not (False)
        restart_filename (str, optional): Name of the restart file (required if use_restart is True)
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
            
            # Update restart settings
            unsteady_file = r"path/to/unsteady_file.u01"
            RasUnsteady.update_restart_settings(unsteady_file, True, "restartfile.rst", ras_object=ras_cmdr.ras)
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
        restart_line_index = None
        for i, line in enumerate(lines):
            if line.startswith("Use Restart="):
                restart_line_index = i
                old_value = line.strip().split('=')[1]
                new_value = "-1" if use_restart else "0"
                lines[i] = f"Use Restart={new_value}\n"
                updated = True
                logger.info(f"Updated Use Restart from {old_value} to {new_value}")
                break
        
        if use_restart:
            if not restart_filename:
                logger.error("Restart filename must be specified when enabling restart.")
                raise ValueError("Restart filename must be specified when enabling restart.")
            if restart_line_index is not None:
                lines.insert(restart_line_index + 1, f"Restart Filename={restart_filename}\n")
                logger.info(f"Added Restart Filename: {restart_filename}")
            else:
                logger.warning("Could not find 'Use Restart' line to insert 'Restart Filename'")
        
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
            logger.info(f"Applied restart settings modification to {unsteady_file}")
        else:
            logger.warning(f"Use Restart setting not found in {unsteady_file}")
    
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def extract_boundary_and_tables(unsteady_file: str, ras_object: Optional[Any] = None) -> pd.DataFrame:
        """
        Extracts Boundary Location blocks, DSS File entries, and their associated 
        fixed-width tables from the specified unsteady file.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        table_types = [
            'Flow Hydrograph=', 
            'Gate Openings=', 
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=', 
            'Lateral Inflow Hydrograph='
        ]
        
        try:
            with open(unsteady_path, 'r') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        # Initialize variables
        boundary_data = []
        current_boundary = None
        current_tables = {}
        current_table = None
        table_values = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Check for Boundary Location line
            if line.startswith("Boundary Location="):
                # Save previous boundary if it exists
                if current_boundary is not None:
                    if current_table and table_values:
                        # Process any remaining table
                        try:
                            df = pd.DataFrame({'Value': table_values})
                            current_tables[current_table_name] = df
                        except Exception as e:
                            logger.warning(f"Error processing table {current_table_name}: {e}")
                    current_boundary['Tables'] = current_tables
                    boundary_data.append(current_boundary)
                
                # Start new boundary
                current_boundary = {
                    'Boundary Location': line.split('=', 1)[1].strip(),
                    'DSS File': '',
                    'Tables': {}
                }
                current_tables = {}
                current_table = None
                table_values = []
                
            # Check for DSS File line
            elif line.startswith("DSS File=") and current_boundary is not None:
                current_boundary['DSS File'] = line.split('=', 1)[1].strip()
                
            # Check for table headers
            elif any(line.startswith(t) for t in table_types) and current_boundary is not None:
                # If we were processing a table, save it
                if current_table and table_values:
                    try:
                        df = pd.DataFrame({'Value': table_values})
                        current_tables[current_table_name] = df
                    except Exception as e:
                        logger.warning(f"Error processing previous table: {e}")
                
                # Start new table
                try:
                    current_table = line.split('=')
                    current_table_name = current_table[0].strip()
                    num_values = int(current_table[1])
                    table_values = []
                    
                    # Read the table values
                    rows_needed = (num_values + 9) // 10  # Round up division
                    for _ in range(rows_needed):
                        i += 1
                        if i >= len(lines):
                            break
                        row = lines[i].strip()
                        # Parse fixed-width values (8 characters each)
                        j = 0
                        while j < len(row):
                            value_str = row[j:j+8].strip()
                            if value_str:
                                try:
                                    value = float(value_str)
                                    table_values.append(value)
                                except ValueError:
                                    # Try splitting merged values
                                    parts = re.findall(r'-?\d+\.?\d*', value_str)
                                    table_values.extend([float(p) for p in parts])
                            j += 8
                
                except (ValueError, IndexError) as e:
                    logger.error(f"Error processing table at line {i}: {e}")
                    current_table = None
                    
            i += 1
        
        # Add the last boundary if it exists
        if current_boundary is not None:
            if current_table and table_values:
                try:
                    df = pd.DataFrame({'Value': table_values})
                    current_tables[current_table_name] = df
                except Exception as e:
                    logger.warning(f"Error processing final table: {e}")
            current_boundary['Tables'] = current_tables
            boundary_data.append(current_boundary)
        
        # Create DataFrame
        boundaries_df = pd.DataFrame(boundary_data)
        if not boundaries_df.empty:
            # Split boundary location into components
            location_columns = ['River Name', 'Reach Name', 'River Station', 
                              'Downstream River Station', 'Storage Area Connection',
                              'Storage Area Name', 'Pump Station Name', 
                              'Blank 1', 'Blank 2']
            split_locations = boundaries_df['Boundary Location'].str.split(',', expand=True)
            # Ensure we have the right number of columns
            for i, col in enumerate(location_columns):
                if i < split_locations.shape[1]:
                    boundaries_df[col] = split_locations[i].str.strip()
                else:
                    boundaries_df[col] = ''
            boundaries_df = boundaries_df.drop(columns=['Boundary Location'])
        
        logger.info(f"Successfully extracted boundaries and tables from {unsteady_path}")
        return boundaries_df

    @staticmethod
    @log_call
    def print_boundaries_and_tables(boundaries_df: pd.DataFrame) -> None:
        """
        Prints the boundaries and their associated tables from the extracted DataFrame.
        
        Parameters:
        - boundaries_df: DataFrame containing boundary information and nested tables data
        """
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        print("\nBoundaries and Tablesin boundaries_df:")
        for idx, row in boundaries_df.iterrows():
            print(f"\nBoundary {idx+1}:")
            print(f"River Name: {row['River Name']}")
            print(f"Reach Name: {row['Reach Name']}")
            print(f"River Station: {row['River Station']}")
            print(f"DSS File: {row['DSS File']}")
            
            if row['Tables']:
                print("\nTables for this boundary:")
                for table_name, table_df in row['Tables'].items():
                    print(f"\n{table_name}:")
                    print(table_df.to_string())
            print("-" * 80)





# Additional functions from the AWS webinar where the code was developed
# Need to add examples

    @staticmethod
    @log_call
    def identify_tables(lines: List[str]) -> List[Tuple[str, int, int]]:
        """
        Identify the start and end of each table in the unsteady flow file.
        
        Parameters:
        lines (List[str]): List of file lines
        
        Returns:
        List[Tuple[str, int, int]]: List of tuples containing (table_name, start_line, end_line)
        """
        table_types = [
            'Flow Hydrograph=', 
            'Gate Openings=', 
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=', 
            'Lateral Inflow Hydrograph='
        ]
        tables = []
        current_table = None
        
        for i, line in enumerate(lines):
            if any(table_type in line for table_type in table_types):
                if current_table:
                    tables.append((current_table[0], current_table[1], i-1))
                table_name = line.strip().split('=')[0] + '='
                try:
                    num_values = int(line.strip().split('=')[1])
                    current_table = (table_name, i+1, num_values)
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing table header at line {i}: {e}")
                    continue
        
        if current_table:
            tables.append((current_table[0], current_table[1], 
                          current_table[1] + (current_table[2] + 9) // 10))
        
        logger.debug(f"Identified {len(tables)} tables in the file")
        return tables

    @staticmethod
    @log_call
    def parse_fixed_width_table(lines: List[str], start: int, end: int) -> pd.DataFrame:
        """
        Parse a fixed-width table into a pandas DataFrame.
        
        Parameters:
        lines (List[str]): List of file lines
        start (int): Starting line number for table
        end (int): Ending line number for table
        
        Returns:
        pd.DataFrame: DataFrame containing parsed table values
        """
        data = []
        for line in lines[start:end]:
            # Split the line into 8-character columns
            values = [line[i:i+8].strip() for i in range(0, len(line), 8)]
            # Convert to float and handle cases where values are run together
            parsed_values = []
            for value in values:
                try:
                    if len(value) > 8:  # If values are run together
                        parts = re.findall(r'-?\d+\.?\d*', value)
                        parsed_values.extend([float(p) for p in parts])
                    elif value:  # Only add non-empty values
                        parsed_values.append(float(value))
                except ValueError as e:
                    logger.warning(f"Could not parse value '{value}': {e}")
                    continue
            data.extend(parsed_values)
        
        return pd.DataFrame(data, columns=['Value'])

    @staticmethod
    @log_call
    def extract_tables(unsteady_file: str, ras_object: Optional[Any] = None) -> Dict[str, pd.DataFrame]:
        """
        Extract all tables from the unsteady file and return them as DataFrames.
        
        Parameters:
        unsteady_file (str): Path to the unsteady flow file
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        Dict[str, pd.DataFrame]: Dictionary of table names to DataFrames
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        tables = RasBndry.identify_tables(lines)
        extracted_tables = {}
        
        for table_name, start, end in tables:
            df = RasBndry.parse_fixed_width_table(lines, start, end)
            extracted_tables[table_name] = df
            logger.debug(f"Extracted table '{table_name}' with {len(df)} values")
        
        return extracted_tables

    @staticmethod
    @log_call
    def write_table_to_file(unsteady_file: str, table_name: str, df: pd.DataFrame, 
                           start_line: int, ras_object: Optional[Any] = None) -> None:
        """
        Write updated table back to file in fixed-width format.
        
        Parameters:
        unsteady_file (str): Path to the unsteady flow file
        table_name (str): Name of the table to update
        df (pd.DataFrame): DataFrame containing the updated values
        start_line (int): Line number where the table starts
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r') as file:
                lines = file.readlines()
            logger.debug(f"Successfully read unsteady flow file: {unsteady_path}")
        except FileNotFoundError:
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise
        except PermissionError:
            logger.error(f"Permission denied when reading unsteady flow file: {unsteady_path}")
            raise
        
        # Format values into fixed-width strings
        formatted_values = []
        for i in range(0, len(df), 10):
            row = df['Value'].iloc[i:i+10]
            formatted_row = ''.join(f'{value:8.0f}' for value in row)
            formatted_values.append(formatted_row + '\n')
        
        # Replace old table with new formatted values
        lines[start_line:start_line+len(formatted_values)] = formatted_values
        
        try:
            with open(unsteady_path, 'w') as file:
                file.writelines(lines)
            logger.info(f"Successfully updated table '{table_name}' in {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            raise
        except IOError as e:
            logger.error(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            raise








'''



Flow Title=Single 2D Area with Bridges
Program Version=6.60
Use Restart= 0 
Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth                   ,                                
Friction Slope=0.0003,0
Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DS2NormalD                      ,                                
Friction Slope=0.0003,0
Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,Upstream Inflow                 ,                                
Interval=1HOUR
Flow Hydrograph= 200 
    1000    3000    6500    8000    9500   11000   12500   14000   15500   17000
   18500   20000   22000   24000   26000   28000   30000   34000   38000   42000
   46000   50000   54000   58000   62000   66000   70000   73000   76000   79000
   82000   85000   87200   89400   91600   93800   96000   96800   97600   98400
   99200  100000   99600   99200   98800   98400   98000   96400   94800   93200
   91600   90000   88500   87000   85500   84000   82500   81000   79500   78000
   76500   75000   73500   7200070666.6669333.34   6800066666.6665333.33   64000
62666.6761333.33   6000058666.6757333.33   5600054666.6753333.33   5200050666.67
49333.33   4800046666.6745333.33   4400042666.6741333.33   4000039166.6738333.33
   3750036666.6735833.33   3500034166.6733333.33   3250031666.6730833.33   30000
29166.6728333.33   2750026666.6725833.33   2500024166.6723333.33   2250021666.67
20833.33   2000019655.1719310.3518965.5218620.6918275.8617931.0417586.2117241.38
16896.5516551.72 16206.915862.0715517.2415172.4114827.5914482.7614137.93 13793.1
13448.2813103.4512758.6212413.7912068.9711724.1411379.3111034.4810689.6610344.83
   10000 9915.25 9830.51 9745.76 9661.02 9576.27 9491.53 9406.78 9322.03 9237.29
 9152.54  9067.8 8983.05 8898.31 8813.56 8728.81 8644.07 8559.32 8474.58 8389.83
 8305.09 8220.34 8135.59 8050.85  7966.1 7881.36 7796.61 7711.86 7627.12 7542.37
 7457.63 7372.88 7288.14 7203.39 7118.64  7033.9 6949.15 6864.41 6779.66 6694.92
 6610.17 6525.42 6440.68 6355.93 6271.19 6186.44  6101.7 6016.95  5932.2 5847.46
 5762.71 5677.97 5593.22 5508.48 5423.73 5338.98 5254.24 5169.49 5084.75    5000
Stage Hydrograph TW Check=0
Flow Hydrograph QMult= 0.5 
Flow Hydrograph Slope= 0.0005 
DSS Path=
Use DSS=False
Use Fixed Start Time=False
Fixed Start Date/Time=,
Is Critical Boundary=False
Critical Boundary Flow=
Boundary Location=                ,                ,        ,        ,Sayers Dam      ,                ,                ,                                ,                                
Gate Name=Gate #1     
Gate DSS Path=
Gate Use DSS=False
Gate Time Interval=1HOUR
Gate Use Fixed Start Time=False
Gate Fixed Start Date/Time=,
Gate Openings= 100 
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
       2       2       2       2       2       2       2       2       2       2
Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DS2NormalDepth                  ,                                
Friction Slope=0.0003,0
Met Point Raster Parameters=,,,,
Precipitation Mode=Disable
Wind Mode=No Wind Forces
Air Density Mode=
Wave Mode=No Wave Forcing
Met BC=Precipitation|Expanded View=0
Met BC=Precipitation|Point Interpolation=Nearest
Met BC=Precipitation|Gridded Source=DSS
Met BC=Precipitation|Gridded Interpolation=
Met BC=Evapotranspiration|Expanded View=0
Met BC=Evapotranspiration|Point Interpolation=Nearest
Met BC=Evapotranspiration|Gridded Source=DSS
Met BC=Evapotranspiration|Gridded Interpolation=
Met BC=Wind Speed|Expanded View=0
Met BC=Wind Speed|Constant Units=ft/s
Met BC=Wind Speed|Point Interpolation=Nearest
Met BC=Wind Speed|Gridded Source=DSS
Met BC=Wind Speed|Gridded Interpolation=
Met BC=Wind Direction|Expanded View=0
Met BC=Wind Direction|Point Interpolation=Nearest
Met BC=Wind Direction|Gridded Source=DSS
Met BC=Wind Direction|Gridded Interpolation=
Met BC=Wind Velocity X|Expanded View=0
Met BC=Wind Velocity X|Constant Units=ft/s
Met BC=Wind Velocity X|Point Interpolation=Nearest
Met BC=Wind Velocity X|Gridded Source=DSS
Met BC=Wind Velocity X|Gridded Interpolation=
Met BC=Wind Velocity Y|Expanded View=0
Met BC=Wind Velocity Y|Constant Units=ft/s
Met BC=Wind Velocity Y|Point Interpolation=Nearest
Met BC=Wind Velocity Y|Gridded Source=DSS
Met BC=Wind Velocity Y|Gridded Interpolation=
Met BC=Wave Forcing X|Expanded View=0
Met BC=Wave Forcing X|Point Interpolation=Nearest
Met BC=Wave Forcing X|Gridded Source=DSS
Met BC=Wave Forcing X|Gridded Interpolation=
Met BC=Wave Forcing Y|Expanded View=0
Met BC=Wave Forcing Y|Point Interpolation=Nearest
Met BC=Wave Forcing Y|Gridded Source=DSS
Met BC=Wave Forcing Y|Gridded Interpolation=
Met BC=Air Density|Mode=Constant
Met BC=Air Density|Expanded View=0
Met BC=Air Density|Constant Value=1.225
Met BC=Air Density|Constant Units=kg/m3
Met BC=Air Density|Point Interpolation=Nearest
Met BC=Air Density|Gridded Source=DSS
Met BC=Air Density|Gridded Interpolation=
Met BC=Air Temperature|Expanded View=0
Met BC=Air Temperature|Point Interpolation=Nearest
Met BC=Air Temperature|Gridded Source=DSS
Met BC=Air Temperature|Gridded Interpolation=
Met BC=Humidity|Expanded View=0
Met BC=Humidity|Point Interpolation=Nearest
Met BC=Humidity|Gridded Source=DSS
Met BC=Humidity|Gridded Interpolation=
Met BC=Air Pressure|Mode=Constant
Met BC=Air Pressure|Expanded View=0
Met BC=Air Pressure|Constant Value=1013.2
Met BC=Air Pressure|Constant Units=mb
Met BC=Air Pressure|Point Interpolation=Nearest
Met BC=Air Pressure|Gridded Source=DSS
Met BC=Air Pressure|Gridded Interpolation=
Non-Newtonian Method= 0 , 
Non-Newtonian Constant Vol Conc=0
Non-Newtonian Yield Method= 0 , 
Non-Newtonian Yield Coef=0, 0
User Yeild=   0
Non-Newtonian Sed Visc= 0 , 
Non-Newtonian Obrian B=0
User Viscosity=0
User Viscosity Ratio=0
Herschel-Bulkley Coef=0, 0
Clastic Method= 0 , 
Coulomb Phi=0
Voellmy X=0
Non-Newtonian Hindered FV= 0 
Non-Newtonian FV K=0
Non-Newtonian ds=0
Non-Newtonian Max Cv=0
Non-Newtonian Bulking Method= 0 , 
Non-Newtonian High C Transport= 0 , 
Lava Activation= 0 
Temperature=1300,15,,15,14,980
Heat Ballance=1,1200,0.5,1,70,0.95
Viscosity=1000,,,
Yield Strength=,,,
Consistency Factor=,,,
Profile Coefficient=4,1.3,
Lava Param=,2500,




'''




