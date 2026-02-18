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
- read_unsteady_description()
- update_unsteady_description()
- update_restart_settings()
- extract_boundary_and_tables()
- print_boundaries_and_tables()
- identify_tables()
- parse_fixed_width_table()
- extract_tables()
- write_table_to_file()
- set_precipitation_hyetograph()
- set_gridded_precipitation()

Precipitation Hyetograph Functions:
- set_precipitation_hyetograph() - Write hyetograph DataFrame to unsteady file

DSS Boundary Condition Functions:
- get_dss_boundaries() - Extract all DSS-linked BCs with full path info
- get_inline_hydrograph_boundaries() - Extract inline table BCs with time series data
- update_dss_run_identifier() - Update DSS path F-part for new scenarios
- set_boundary_dss_link() - Convert inline BC to DSS-linked (complete state transition)
- set_boundary_inline_hydrograph() - Write inline hydrograph, convert DSS to inline
- get_unique_dss_subbasins() - Get unique HMS subbasin names from DSS paths
- update_dss_path_by_station() - Update DSS A-part for specific river station
- update_flow_multiplier_by_station() - Update/insert QMult for specific river station
- update_boundary_dss_paths() - Batch update DSS paths and multipliers
        
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
        Update the Flow Title in an unsteady flow file (.u*).

        The Flow Title provides a descriptive identifier for unsteady flow scenarios in HEC-RAS. 
        It appears in the HEC-RAS interface and helps differentiate between different flow files.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file or unsteady flow number
            new_title (str): New flow title (max 24 characters, will be truncated if longer)
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place and updates the ras object's unsteady dataframe

        Example:
            # Clone an existing unsteady flow file
            new_unsteady_number = RasPlan.clone_unsteady("02")
            
            # Get path to the new unsteady flow file
            new_unsteady_file = RasPlan.get_unsteady_path(new_unsteady_number)
            
            # Update the flow title
            new_title = "Modified Flow Scenario"
            RasUnsteady.update_flow_title(new_unsteady_file, new_title)
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
    def read_unsteady_description(unsteady_number_or_path: Union[str, Path], ras_object: Optional[Any] = None) -> str:
        """
        Read the description from an unsteady flow file (.u##).

        Args:
            unsteady_number_or_path (Union[str, Path]): The unsteady number (e.g., '01')
                or path to the unsteady flow file.
            ras_object (optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            str: The description text, or empty string if not found.

        Raises:
            ValueError: If the unsteady flow file is not found.
        """
        from .RasUtils import RasUtils

        unsteady_file_path = Path(unsteady_number_or_path)
        if not unsteady_file_path.is_file():
            from .RasPlan import RasPlan
            unsteady_file_path = RasPlan.get_unsteady_path(unsteady_number_or_path, ras_object)
            if unsteady_file_path is None or not Path(unsteady_file_path).exists():
                raise ValueError(f"Unsteady flow file not found: {unsteady_number_or_path}")

        return RasUtils._read_description_block(unsteady_file_path)

    @staticmethod
    @log_call
    def update_unsteady_description(unsteady_number_or_path: Union[str, Path], description: str, ras_object: Optional[Any] = None) -> bool:
        """
        Update or insert the description in an unsteady flow file (.u##).

        Args:
            unsteady_number_or_path (Union[str, Path]): The unsteady number (e.g., '01')
                or path to the unsteady flow file.
            description (str): Description text to write.
            ras_object (optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If the unsteady flow file is not found.
        """
        from .RasUtils import RasUtils

        unsteady_file_path = Path(unsteady_number_or_path)
        if not unsteady_file_path.is_file():
            from .RasPlan import RasPlan
            unsteady_file_path = RasPlan.get_unsteady_path(unsteady_number_or_path, ras_object)
            if unsteady_file_path is None or not Path(unsteady_file_path).exists():
                raise ValueError(f"Unsteady flow file not found: {unsteady_number_or_path}")

        return RasUtils._write_description_block(unsteady_file_path, description, 'Flow Title')

    @staticmethod
    @log_call
    def update_restart_settings(unsteady_file: str, use_restart: bool, restart_filename: Optional[str] = None, ras_object: Optional[Any] = None) -> None:
        """
        Update the restart file settings in an unsteady flow file.

        Restart files in HEC-RAS allow simulations to continue from a previously saved state,
        which is useful for long simulations or when making downstream changes.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            use_restart (bool): Whether to use a restart file (True) or not (False)
            restart_filename (str, optional): Path to the restart file (.rst)
                                             Required if use_restart is True
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place and updates the ras object's unsteady dataframe

        Example:
            # Enable restart file for an unsteady flow
            unsteady_file = RasPlan.get_unsteady_path("03")
            RasUnsteady.update_restart_settings(
                unsteady_file, 
                use_restart=True, 
                restart_filename="model_restart.rst"
            )
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
        Extract boundary conditions and their associated tables from an unsteady flow file.

        Boundary conditions in HEC-RAS define time-varying inputs like flow hydrographs,
        stage hydrographs, gate operations, and lateral inflows. This function parses these
        conditions and their data tables from the unsteady flow file.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            pd.DataFrame: DataFrame containing boundary conditions with the following columns:
                - River Name, Reach Name, River Station: Location information
                - DSS File: Associated DSS file path if any
                - Tables: Dictionary containing DataFrames of time-series values

        Example:
            # Get the path to unsteady flow file "02"
            unsteady_file = RasPlan.get_unsteady_path("02")
            
            # Extract boundary conditions and tables
            boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_file)
            print(f"Extracted {len(boundaries_df)} boundary conditions from the file.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        unsteady_path = Path(unsteady_file)
        table_types = [
            'Flow Hydrograph=',
            'Gate Openings=',
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=',
            'Lateral Inflow Hydrograph=',
            'Precipitation Hydrograph=',
            'Rating Curve='
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
        Print boundary conditions and their associated tables in a formatted, readable way.

        This function is useful for quickly visualizing the complex nested structure of 
        boundary conditions extracted by extract_boundary_and_tables().

        Parameters:
            boundaries_df (pd.DataFrame): DataFrame containing boundary information and 
                                         nested tables data from extract_boundary_and_tables()

        Returns:
            None: Output is printed to console

        Example:
            # Extract boundary conditions and tables
            boundaries_df = RasUnsteady.extract_boundary_and_tables(unsteady_file)
            
            # Print in a formatted way
            print("Detailed boundary conditions and tables:")
            RasUnsteady.print_boundaries_and_tables(boundaries_df)
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
        Identify the start and end line numbers of tables in an unsteady flow file.

        HEC-RAS unsteady flow files contain numeric tables in a fixed-width format.
        This function locates these tables within the file and provides their positions.

        Parameters:
            lines (List[str]): List of file lines (typically from file.readlines())

        Returns:
            List[Tuple[str, int, int]]: List of tuples where each tuple contains:
                - table_name (str): The type of table (e.g., 'Flow Hydrograph=')
                - start_line (int): Line number where the table data begins
                - end_line (int): Line number where the table data ends

        Example:
            # Read the unsteady flow file
            with open(new_unsteady_file, 'r') as f:
                lines = f.readlines()
                
            # Identify tables in the file
            tables = RasUnsteady.identify_tables(lines)
            print(f"Identified {len(tables)} tables in the unsteady flow file.")
        """
        table_types = [
            'Flow Hydrograph=',
            'Gate Openings=',
            'Stage Hydrograph=',
            'Uniform Lateral Inflow=',
            'Lateral Inflow Hydrograph=',
            'Precipitation Hydrograph=',
            'Rating Curve='
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
        Parse a fixed-width table from an unsteady flow file into a pandas DataFrame.

        HEC-RAS uses a fixed-width format (8 characters per value) for numeric tables.
        This function converts this format into a DataFrame for easier manipulation.

        Parameters:
            lines (List[str]): List of file lines (from file.readlines())
            start (int): Starting line number for table data
            end (int): Ending line number for table data

        Returns:
            pd.DataFrame: DataFrame with a single column 'Value' containing the parsed numeric values

        Example:
            # Identify tables in the file
            tables = RasUnsteady.identify_tables(lines)
            
            # Parse a specific table (e.g., first flow hydrograph)
            table_name, start_line, end_line = tables[0]
            table_df = RasUnsteady.parse_fixed_width_table(lines, start_line, end_line)
        """
        data = []
        for line in lines[start:end]:
            # Skip empty lines or lines that don't contain numeric data
            if not line.strip() or not any(c.isdigit() for c in line):
                continue
                
            # Split the line into 8-character columns and process each value
            values = []
            for i in range(0, len(line.rstrip()), 8):
                value_str = line[i:i+8].strip()
                if value_str:  # Only process non-empty strings
                    try:
                        # Handle special cases where numbers are run together
                        if len(value_str) > 8:
                            # Use regex to find all numbers in the string
                            parts = re.findall(r'-?\d+\.?\d*', value_str)
                            values.extend([float(p) for p in parts])
                        else:
                            values.append(float(value_str))
                    except ValueError:
                        # If conversion fails, try to extract any valid numbers from the string
                        parts = re.findall(r'-?\d+\.?\d*', value_str)
                        if parts:
                            values.extend([float(p) for p in parts])
                        else:
                            logger.debug(f"Skipping non-numeric value: {value_str}")
                            continue
            
            # Only add to data if we found valid numeric values
            if values:
                data.extend(values)
        
        if not data:
            logger.warning("No numeric data found in table section")
            return pd.DataFrame(columns=['Value'])
            
        return pd.DataFrame(data, columns=['Value'])
    
    @staticmethod
    @log_call
    def extract_tables(unsteady_file: str, ras_object: Optional[Any] = None) -> Dict[str, pd.DataFrame]:
        """
        Extract all tables from an unsteady flow file and return them as DataFrames.

        This function combines identify_tables() and parse_fixed_width_table() to extract
        all tables from an unsteady flow file in a single operation.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            Dict[str, pd.DataFrame]: Dictionary where:
                - Keys are table names (e.g., 'Flow Hydrograph=')
                - Values are DataFrames with a 'Value' column containing numeric data

        Example:
            # Extract all tables from the unsteady flow file
            all_tables = RasUnsteady.extract_tables(new_unsteady_file)
            print(f"Extracted {len(all_tables)} tables from the file.")
            
            # Access a specific table
            flow_tables = [name for name in all_tables.keys() if 'Flow Hydrograph=' in name]
            if flow_tables:
                flow_df = all_tables[flow_tables[0]]
                print(f"Flow table has {len(flow_df)} values")
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
        
        # Fix: Use RasUnsteady.identify_tables 
        tables = RasUnsteady.identify_tables(lines)
        extracted_tables = {}
        
        for table_name, start, end in tables:
            df = RasUnsteady.parse_fixed_width_table(lines, start, end)
            extracted_tables[table_name] = df
            logger.debug(f"Extracted table '{table_name}' with {len(df)} values")
        
        return extracted_tables

    @staticmethod
    @log_call
    def write_table_to_file(unsteady_file: str, table_name: str, df: pd.DataFrame, 
                           start_line: int, ras_object: Optional[Any] = None) -> None:
        """
        Write an updated table back to an unsteady flow file in the required fixed-width format.

        This function takes a modified DataFrame and writes it back to the unsteady flow file,
        preserving the 8-character fixed-width format that HEC-RAS requires.

        Parameters:
            unsteady_file (str): Path to the unsteady flow file
            table_name (str): Name of the table to update (e.g., 'Flow Hydrograph=')
            df (pd.DataFrame): DataFrame containing the updated values with a 'Value' column
            start_line (int): Line number where the table data begins in the file
            ras_object (optional): Custom RAS object to use instead of the global one

        Returns:
            None: The function modifies the file in-place

        Example:
            # Identify tables in the unsteady flow file
            tables = RasUnsteady.identify_tables(lines)
            table_name, start_line, end_line = tables[0]
            
            # Parse and modify the table
            table_df = RasUnsteady.parse_fixed_width_table(lines, start_line, end_line)
            table_df['Value'] = table_df['Value'] * 0.75  # Scale values to 75%
            
            # Write modified table back to the file
            RasUnsteady.write_table_to_file(new_unsteady_file, table_name, table_df, start_line)
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
            formatted_row = ''.join(f'{value:8.2f}' for value in row)
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

    @staticmethod
    @log_call
    def set_precipitation_hyetograph(
        unsteady_file: Union[str, Path],
        hyetograph_df: pd.DataFrame,
        boundary_name: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Set precipitation hyetograph in an unsteady flow file from a DataFrame.

        This method writes hyetograph data directly to the "Precipitation Hydrograph="
        section in HEC-RAS unsteady flow files (.u##). It automatically detects the
        time interval from the DataFrame and formats values in HEC-RAS fixed-width format.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01")
        hyetograph_df : pd.DataFrame
            DataFrame with columns:
            - 'hour': Time in hours from storm start (end of interval)
            - 'incremental_depth': Precipitation depth for this interval (inches)
            - 'cumulative_depth': Cumulative precipitation depth (inches)
        boundary_name : str, optional
            Name of the 2D Flow Area or Storage Area to update.
            If None, updates the first Precipitation Hydrograph found.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        None
            The function modifies the file in-place.

        Raises
        ------
        ValueError
            If DataFrame is missing required columns
        FileNotFoundError
            If unsteady flow file not found

        Example
        -------
        >>> from ras_commander import RasUnsteady, init_ras_project
        >>> from ras_commander.precip import StormGenerator
        >>>
        >>> # Generate hyetograph
        >>> gen = StormGenerator.download_from_coordinates(29.76, -95.37)
        >>> hyeto = gen.generate_hyetograph(
        ...     total_depth_inches=17.0,
        ...     duration_hours=24,
        ...     position_percent=50
        ... )
        >>>
        >>> # Write to unsteady file
        >>> RasUnsteady.set_precipitation_hyetograph("project.u01", hyeto)

        Notes
        -----
        **DataFrame Format**:
        - All methods in ras-commander.precip return DataFrames with the required columns
        - Atlas14Storm, FrequencyStorm, ScsTypeStorm (from hms-commander) also use this format

        **Interval Detection**:
        - Interval is calculated from `hour` column spacing (e.g., 1.0 → "1HOUR", 0.5 → "30MIN")
        - The Interval= line immediately preceding the Precipitation Hydrograph section is updated

        **Fixed-Width Format**:
        - Values formatted as 8-character fixed-width fields (8.2f)
        - 10 values per line
        - HEC-RAS uses (time, depth) pairs, so count = len(hyetograph) × 2

        **Depth Conservation**:
        - Total depth is logged for verification
        - Should match the total_depth_inches used in generation

        See Also
        --------
        StormGenerator.generate_hyetograph : Generate design storm hyetograph
        Atlas14Storm.generate_hyetograph : HMS-equivalent hyetograph (from hms-commander)
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use without initialized project

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            # It's an unsteady number, resolve to full path
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Validate DataFrame columns
        required_columns = ['hour', 'incremental_depth', 'cumulative_depth']
        missing_columns = [col for col in required_columns if col not in hyetograph_df.columns]
        if missing_columns:
            raise ValueError(
                f"DataFrame missing required columns: {missing_columns}. "
                f"Required columns: {required_columns}"
            )

        # Calculate interval from hour column
        hours = hyetograph_df['hour'].values
        if len(hours) < 2:
            raise ValueError("DataFrame must have at least 2 rows to determine interval")

        interval_hours = hours[1] - hours[0]

        # Convert interval to HEC-RAS format string
        if interval_hours >= 1.0:
            if interval_hours == int(interval_hours):
                interval_str = f"{int(interval_hours)}HOUR"
            else:
                # Convert to minutes if fractional hour
                interval_min = int(interval_hours * 60)
                interval_str = f"{interval_min}MIN"
        else:
            interval_min = int(interval_hours * 60)
            interval_str = f"{interval_min}MIN"

        # Read the file
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Get precipitation values (incremental depths)
        precip_values = hyetograph_df['incremental_depth'].values

        # Calculate total depth for logging
        total_depth = hyetograph_df['cumulative_depth'].iloc[-1]

        # Format values as (time, depth) pairs in HEC-RAS fixed-width format
        # HEC-RAS expects paired values: time, value, time, value, ...
        paired_values = []
        for i, (hour, depth) in enumerate(zip(hours, precip_values)):
            paired_values.append(hour)
            paired_values.append(depth)

        num_pairs = len(precip_values)

        # Format into fixed-width lines (8 chars each, 10 values per line)
        formatted_lines = []
        for i in range(0, len(paired_values), 10):
            row_values = paired_values[i:i+10]
            formatted_row = ''.join(f'{value:8.2f}' for value in row_values)
            formatted_lines.append(formatted_row + '\n')

        # Find the Precipitation Hydrograph section(s)
        precip_sections = []
        for i, line in enumerate(lines):
            if line.startswith('Precipitation Hydrograph='):
                precip_sections.append(i)

        if not precip_sections:
            raise ValueError(
                f"No 'Precipitation Hydrograph=' section found in {unsteady_path}. "
                "Ensure the unsteady file has a precipitation boundary condition defined."
            )

        # Determine which section to update
        if boundary_name is not None:
            # Find the section associated with the specified boundary
            target_section = None
            for precip_idx in precip_sections:
                # Search backwards for Boundary Location
                for j in range(precip_idx - 1, max(0, precip_idx - 50), -1):
                    if lines[j].startswith('Boundary Location='):
                        # Check if boundary name matches (usually in position 6 for storage area)
                        loc_parts = lines[j].replace('Boundary Location=', '').split(',')
                        for part in loc_parts:
                            if boundary_name.strip().lower() in part.strip().lower():
                                target_section = precip_idx
                                break
                        break
                if target_section is not None:
                    break

            if target_section is None:
                logger.warning(
                    f"Boundary '{boundary_name}' not found. "
                    f"Updating first Precipitation Hydrograph section."
                )
                target_section = precip_sections[0]
        else:
            target_section = precip_sections[0]

        precip_line_idx = target_section

        # Find the end of the old data section by scanning for next keyword line
        # Data starts right after the Precipitation Hydrograph= line
        old_data_start = precip_line_idx + 1
        old_data_end = old_data_start

        # Scan forward to find where data ends (next line with '=' keyword)
        for k in range(old_data_start, len(lines)):
            line = lines[k]
            # Data lines are numeric only; keyword lines contain '='
            if '=' in line:
                old_data_end = k
                break
            # Also check for empty lines that might mark end of section
            if not line.strip():
                # Empty line might be end of section, but continue checking
                pass
        else:
            # Reached end of file
            old_data_end = len(lines)

        # Update the Precipitation Hydrograph header line with new count
        new_precip_line = f"Precipitation Hydrograph= {num_pairs} \n"

        # Search backwards from Precipitation Hydrograph line for Interval line
        interval_updated = False
        for j in range(precip_line_idx - 1, max(0, precip_line_idx - 20), -1):
            if lines[j].startswith('Interval='):
                old_interval = lines[j].strip()
                lines[j] = f"Interval={interval_str}\n"
                interval_updated = True
                logger.debug(f"Updated {old_interval} to Interval={interval_str}")
                break

        if not interval_updated:
            logger.warning(
                f"Could not find Interval= line before Precipitation Hydrograph at line {precip_line_idx + 1}. "
                "Interval not updated."
            )

        # Replace the old data section with new formatted data
        # 1. Update header line
        lines[precip_line_idx] = new_precip_line

        # 2. Replace data lines
        new_lines = lines[:old_data_start] + formatted_lines + lines[old_data_end:]

        # Write updated content back to file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info(
            f"Updated Precipitation Hydrograph in {unsteady_path.name}: "
            f"{num_pairs} time steps, interval={interval_str}, "
            f"total depth={total_depth:.4f} inches"
        )

    @staticmethod
    def _update_precipitation_hdf(
        hdf_path: Path,
        netcdf_path: Path,
        netcdf_rel_path: str,
        interpolation: str = "Nearest"
    ) -> None:
        """
        Import precipitation raster data into HDF in HEC-RAS 6.6 format.

        This function imports gridded precipitation from NetCDF into the HDF file
        in the exact format HEC-RAS 6.6 creates when using "Import Raster Data" in the GUI.

        The data is transformed from instantaneous rates to cumulative totals and
        flattened from (time, y, x) to (time, rows*cols) shape.

        HEC-RAS 6.6 Format Requirements (verified against GUI import):
        - Timestamps in ISO 8601 format: 'YYYY-MM-DD HH:MM:SS' (|S19)
        - No separate Timestamp dataset (timestamps only in Times attribute)
        - Values dataset: chunked, gzip compressed, fillvalue=nan
        - NoData attribute as float32(-9999.0)
        - Grid extent attributes on Values dataset (not on Imported Raster Data group)
        - Meteorology/Attributes dataset preserved for proper indexing

        Parameters
        ----------
        hdf_path : Path
            Path to the unsteady HDF file (.u##.hdf)
        netcdf_path : Path
            Absolute path to the NetCDF precipitation file
        netcdf_rel_path : str
            Relative path string for HDF attributes (e.g., ".\\Precipitation\\file.nc")
        interpolation : str
            Interpolation method ("Bilinear" or "Nearest"). Default is "Nearest"
            which matches HEC-RAS 6.6 GUI default.
        """
        import h5py
        import numpy as np
        import uuid

        try:
            import xarray as xr
        except ImportError:
            logger.warning("xarray not available - cannot import precipitation into HDF")
            return

        logger.info(f"Updating precipitation in HDF: {hdf_path}")

        # Read the NetCDF file
        if not netcdf_path.exists():
            logger.warning(f"NetCDF file not found: {netcdf_path}")
            return

        try:
            ds = xr.open_dataset(netcdf_path)

            # Get precipitation variable
            precip_var = None
            for var_name in ['APCP_surface', 'APCP', 'precip', 'precipitation', 'rain']:
                if var_name in ds.data_vars:
                    precip_var = var_name
                    break

            if precip_var is None:
                logger.warning(f"Could not find precipitation variable in {netcdf_path}")
                ds.close()
                return

            precip_data = ds[precip_var].values  # Shape: (time, y, x)
            times = ds['time'].values
            x_coords = ds['x'].values
            y_coords = ds['y'].values

            ds.close()

            n_times, n_rows, n_cols = precip_data.shape
            logger.info(f"  NetCDF: {n_times} timesteps, {n_rows}x{n_cols} grid")

        except Exception as e:
            logger.warning(f"Error reading NetCDF file: {e}")
            return

        # Calculate raster extent parameters
        cellsize = abs(x_coords[1] - x_coords[0]) if len(x_coords) > 1 else 2000.0
        x_min = float(x_coords.min())
        y_min = float(y_coords.min())
        y_max = float(y_coords.max())

        # Raster bounds (cell edges, not centers)
        raster_left = x_min - cellsize / 2
        raster_top = y_max + cellsize / 2

        # Transform data: flatten spatial dims and convert to cumulative
        # Shape: (time, y, x) -> (time, rows*cols)
        precip_flat = precip_data.reshape(n_times, n_rows * n_cols)

        # Replace NaN with 0 for cumsum calculation
        precip_flat = np.nan_to_num(precip_flat, nan=0.0)

        # Convert from instantaneous rate (mm/hr) to cumulative total (mm)
        precip_cumulative = np.cumsum(precip_flat, axis=0).astype(np.float32)

        # Create timestamp strings in HEC-RAS 6.6 format (ISO 8601)
        # Format: 'YYYY-MM-DD HH:MM:SS' stored as |S19 fixed-length bytes
        import pandas as pd
        timestamps = pd.to_datetime(times)
        timestamp_strs = [t.strftime('%Y-%m-%d %H:%M:%S') for t in timestamps]

        # EPSG:5070 WKT string (NAD83 / Conus Albers)
        srs_wkt = ('PROJCS["NAD83 / Conus Albers",GEOGCS["NAD83",DATUM["North_American_Datum_1983",'
                   'SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],'
                   'AUTHORITY["EPSG","6269"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
                   'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
                   'AUTHORITY["EPSG","4269"]],PROJECTION["Albers_Conic_Equal_Area"],'
                   'PARAMETER["latitude_of_center",23],PARAMETER["longitude_of_center",-96],'
                   'PARAMETER["standard_parallel_1",29.5],PARAMETER["standard_parallel_2",45.5],'
                   'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
                   'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],'
                   'AXIS["Northing",NORTH],AUTHORITY["EPSG","5070"]]')

        # Generate GUID for dataset
        guid = str(uuid.uuid4())

        # Update the HDF file
        try:
            with h5py.File(hdf_path, 'r+') as f:
                met_path = 'Event Conditions/Meteorology'
                precip_grp_path = f'{met_path}/Precipitation'

                # Create parent groups if they don't exist
                if precip_grp_path not in f:
                    logger.info(f"Creating precipitation group hierarchy in HDF")
                    if 'Event Conditions' not in f:
                        f.create_group('Event Conditions')
                    if met_path not in f:
                        f.create_group(met_path)
                    f.create_group(precip_grp_path)

                precip_grp = f[precip_grp_path]

                # Update Precipitation group attributes
                # HEC-RAS 6.6 uses uint8 for Enabled
                precip_grp.attrs['Enabled'] = np.uint8(1)
                precip_grp.attrs['Mode'] = np.bytes_('Gridded')
                precip_grp.attrs['Source'] = np.bytes_('GDAL Raster File(s)')
                precip_grp.attrs['GDAL Filename'] = np.bytes_(netcdf_rel_path)
                precip_grp.attrs['GDAL Datasetname'] = np.bytes_('')
                precip_grp.attrs['GDAL Filter'] = np.bytes_('')
                precip_grp.attrs['GDAL Folder'] = np.bytes_('')
                precip_grp.attrs['Interpolation Method'] = np.bytes_(interpolation)

                # HEC-RAS 6.6 requires Meteorology/Attributes dataset for indexing
                attrs_path = f'{met_path}/Attributes'
                if attrs_path not in f:
                    # Create compound dtype for Attributes dataset
                    attr_dtype = np.dtype([('Variable', 'S32'), ('Group', 'S42')])
                    attr_data = np.array(
                        [(b'Precipitation', b'Event Conditions/Meteorology/Precipitation')],
                        dtype=attr_dtype
                    )
                    f.create_dataset(attrs_path, data=attr_data, chunks=(1,), compression='gzip')

                # Create/recreate Imported Raster Data group
                # HEC-RAS 6.6: NO attributes on this group (grid attrs go on Values dataset)
                raster_grp_path = f'{precip_grp_path}/Imported Raster Data'
                if raster_grp_path in f:
                    del f[raster_grp_path]
                raster_grp = f.create_group(raster_grp_path)

                # HEC-RAS 6.6: NO separate Timestamp dataset (timestamps only in Times attribute)

                # Number of cells for dataset shape
                n_cells = n_rows * n_cols

                # Common attributes for Values datasets (HEC-RAS 6.6 format)
                values_attrs = {
                    'Data Type': np.bytes_('cumulative'),
                    'GUID': np.bytes_(guid),
                    'NoData': np.float32(-9999.0),  # HEC-RAS 6.6 uses float32
                    'Projection': np.bytes_(srs_wkt),
                    'Raster Cellsize': np.float64(cellsize),
                    'Raster Cols': np.int32(n_cols),
                    'Raster Left': np.float64(raster_left),
                    'Raster Rows': np.int32(n_rows),
                    'Raster Top': np.float64(raster_top),
                    'Rate Time Units': np.bytes_('Hour'),
                    'Storage Configuration': np.bytes_('Sequential'),
                    'Time Series Data Type': np.bytes_('Amount'),
                    'Times': np.array(timestamp_strs, dtype='S19'),  # HEC-RAS 6.6: ISO format |S19
                    'Units': np.bytes_('mm'),
                    'Version': np.bytes_('1.0'),
                }

                # Create Values dataset - HEC-RAS 6.6 format:
                # - Chunked as single chunk (n_times, n_cells)
                # - gzip compression level 1
                # - fillvalue = nan
                values_ds = raster_grp.create_dataset(
                    'Values',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan
                )
                for attr_name, attr_val in values_attrs.items():
                    values_ds.attrs[attr_name] = attr_val

                # Create Values (Vertical) dataset - same format
                values_vert_ds = raster_grp.create_dataset(
                    'Values (Vertical)',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan
                )
                for attr_name, attr_val in values_attrs.items():
                    values_vert_ds.attrs[attr_name] = attr_val

                logger.info(f"  Imported {n_times} timesteps, {n_cells} cells (cumulative)")
                logger.info(f"  Precip range: {precip_cumulative.min():.1f} - {precip_cumulative.max():.1f} mm")

        except Exception as e:
            logger.error(f"Error updating HDF file: {e}")
            raise

    @staticmethod
    @log_call
    def set_gridded_precipitation(
        unsteady_file: Union[str, Path],
        netcdf_path: Union[str, Path],
        interpolation: str = "Bilinear",
        ras_object: Optional[Any] = None
    ) -> None:
        """
        Configure gridded precipitation from a NetCDF file in an unsteady flow file.

        This function modifies the meteorologic boundary conditions in an HEC-RAS
        unsteady flow file to use GDAL Raster (NetCDF) gridded precipitation instead
        of DSS or constant values.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "04")
        netcdf_path : str or Path
            Path to the NetCDF precipitation file. Can be absolute or relative to
            the project folder. The file should be in SHG projection (EPSG:5070)
            for proper import into HEC-RAS.
        interpolation : str, default "Bilinear"
            Spatial interpolation method. Options: "Bilinear", "Nearest"
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        None
            The function modifies the file in-place.

        Examples
        --------
        >>> from ras_commander import RasUnsteady, init_ras_project
        >>> init_ras_project("/path/to/project", "6.6")
        >>>
        >>> # Set gridded precipitation from AORC NetCDF
        >>> RasUnsteady.set_gridded_precipitation(
        ...     unsteady_file="04",
        ...     netcdf_path="Precipitation/aorc_april2020_shg.nc"
        ... )

        Notes
        -----
        - The NetCDF file must be in SHG projection (EPSG:5070) for HEC-RAS import
        - Use PrecipAorc.download() with default settings to create compatible files
        - This function preserves existing DSS configuration but switches source to GDAL
        - The plan file's simulation dates should match the NetCDF time range
        - Precipitation data is automatically imported into the HDF file in the format
          HEC-RAS expects (cumulative totals, flattened grid)

        See Also
        --------
        PrecipAorc.download : Download AORC precipitation data as NetCDF
        HdfProject.get_project_bounds_latlon : Get project bounds for precipitation query
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            # It's an unsteady number, resolve to full path
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Convert netcdf_path to relative path if within project folder
        netcdf_path = Path(netcdf_path)
        if netcdf_path.is_absolute():
            try:
                netcdf_rel = netcdf_path.relative_to(ras_obj.project_folder)
                netcdf_str = f".\\{netcdf_rel}".replace("/", "\\")
            except ValueError:
                netcdf_str = str(netcdf_path)
        else:
            netcdf_str = f".\\{netcdf_path}".replace("/", "\\")

        logger.info(f"Configuring gridded precipitation in {unsteady_path}")
        logger.info(f"  NetCDF file: {netcdf_str}")
        logger.info(f"  Interpolation: {interpolation}")

        # Read the file
        with open(unsteady_path, 'r') as f:
            lines = f.readlines()

        # Track what we need to update
        source_updated = False
        source_line = -1
        interp_updated = False
        gdal_filename_updated = False
        gdal_filename_line = -1

        for i, line in enumerate(lines):
            # Update Gridded Source to GDAL Raster File(s)
            if line.startswith("Met BC=Precipitation|Gridded Source="):
                lines[i] = "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)\n"
                source_updated = True
                source_line = i
                logger.debug(f"Updated Gridded Source at line {i+1}")

            # Update or add Gridded Interpolation
            elif line.startswith("Met BC=Precipitation|Gridded Interpolation="):
                lines[i] = f"Met BC=Precipitation|Gridded Interpolation={interpolation}\n"
                interp_updated = True
                logger.debug(f"Updated Gridded Interpolation at line {i+1}")

            # Update or track GDAL Filename line
            elif line.startswith("Met BC=Precipitation|Gridded GDAL Filename="):
                lines[i] = f"Met BC=Precipitation|Gridded GDAL Filename={netcdf_str}\n"
                gdal_filename_updated = True
                logger.debug(f"Updated GDAL Filename at line {i+1}")

            # Track location after DSS Pathname for inserting GDAL Filename if needed
            elif line.startswith("Met BC=Precipitation|Gridded DSS Pathname="):
                gdal_filename_line = i + 1

        # If Interpolation line didn't exist, insert it after Gridded Source
        if not interp_updated and source_line >= 0:
            lines.insert(source_line + 1, f"Met BC=Precipitation|Gridded Interpolation={interpolation}\n")
            interp_updated = True
            # Adjust line numbers for subsequent inserts
            if gdal_filename_line > source_line:
                gdal_filename_line += 1
            logger.debug(f"Inserted Gridded Interpolation at line {source_line+2}")

        # If GDAL Filename line didn't exist, insert it after DSS Pathname
        if not gdal_filename_updated and gdal_filename_line > 0:
            lines.insert(gdal_filename_line, f"Met BC=Precipitation|Gridded GDAL Filename={netcdf_str}\n")
            gdal_filename_updated = True
            logger.debug(f"Inserted GDAL Filename at line {gdal_filename_line+1}")

        # Verify all updates were made
        if not source_updated:
            logger.warning("Could not find 'Met BC=Precipitation|Gridded Source=' line")
        if not gdal_filename_updated:
            logger.warning("Could not add GDAL Filename line")

        # Write the updated file
        with open(unsteady_path, 'w') as f:
            f.writelines(lines)

        logger.info(f"Successfully configured gridded precipitation in {unsteady_path}")

        # Import precipitation data into the HDF file
        hdf_path = Path(str(unsteady_path) + '.hdf')
        if hdf_path.exists():
            # Resolve full path to NetCDF
            if netcdf_path.is_absolute():
                netcdf_full_path = netcdf_path
            else:
                netcdf_full_path = ras_obj.project_folder / netcdf_path

            RasUnsteady._update_precipitation_hdf(
                hdf_path=hdf_path,
                netcdf_path=netcdf_full_path,
                netcdf_rel_path=netcdf_str,
                interpolation=interpolation
            )
        else:
            logger.warning(f"HDF file not found: {hdf_path} - precipitation data not imported")

    # ==========================================================================
    # DSS Boundary Condition Functions
    # ==========================================================================

    @staticmethod
    @log_call
    def get_dss_boundaries(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract all DSS-linked boundary conditions from an unsteady flow file.

        This function parses .u## files and extracts boundary conditions that use
        DSS files (Use DSS=True), including the full DSS path information needed
        for updating precipitation scenarios.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - river: River name
            - reach: Reach name
            - station: River station
            - bc_type: Boundary condition type (Flow Hydrograph, Lateral Inflow, etc.)
            - interval: Time interval (e.g., 5MIN)
            - dss_file: DSS file path
            - dss_path: Full DSS path (//A/B/C/D/E/F/)
            - dss_part_a: DSS Part A (project)
            - dss_part_b: DSS Part B (location/subbasin)
            - dss_part_c: DSS Part C (parameter)
            - dss_part_d: DSS Part D (date)
            - dss_part_e: DSS Part E (interval)
            - dss_part_f: DSS Part F (run identifier)
            - use_dss: Boolean True/False
            - line_number: Line number of Boundary Location in file

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> dss_bcs = RasUnsteady.get_dss_boundaries("project.u01")
        >>> print(f"Found {len(dss_bcs)} DSS-linked boundaries")
        >>> # Get unique HMS subbasins (Part B)
        >>> subbasins = dss_bcs['dss_part_b'].unique()
        >>> print(f"Unique subbasins: {subbasins}")

        Notes
        -----
        DSS Path Format: //A/B/C/D/E/F/
        - Part A: Project identifier (often empty)
        - Part B: Location/Subbasin name (key for HMS matching)
        - Part C: Parameter (FLOW, STAGE, etc.)
        - Part D: Date reference
        - Part E: Time interval (5MIN, 1HOUR, etc.)
        - Part F: Run identifier (e.g., RUN:1%_24HR)
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use without initialized project

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        boundaries = []
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('Boundary Location='):
                bc = RasUnsteady._parse_boundary_block_dss(lines, i)
                if bc.get('use_dss') == 'True':
                    bc['line_number'] = i + 1  # 1-indexed for user reference
                    boundaries.append(bc)
            i += 1

        df = pd.DataFrame(boundaries)
        logger.info(f"Found {len(df)} DSS-linked boundaries in {unsteady_path.name}")
        return df

    @staticmethod
    def _parse_boundary_block_dss(lines: List[str], start_idx: int) -> Dict:
        """Parse a boundary block and extract DSS-related fields."""
        bc = {
            'river': '',
            'reach': '',
            'station': '',
            'bc_type': '',
            'interval': '',
            'dss_file': '',
            'dss_path': '',
            'dss_part_a': '',
            'dss_part_b': '',
            'dss_part_c': '',
            'dss_part_d': '',
            'dss_part_e': '',
            'dss_part_f': '',
            'use_dss': 'False',
            'data_count': 0
        }

        # Parse location line
        loc_line = lines[start_idx].replace('Boundary Location=', '')
        parts = [p.strip() for p in loc_line.split(',')]
        if len(parts) >= 1:
            bc['river'] = parts[0]
        if len(parts) >= 2:
            bc['reach'] = parts[1]
        if len(parts) >= 3:
            bc['station'] = parts[2]

        # Scan following lines for DSS info
        i = start_idx + 1
        while i < len(lines) and i < start_idx + 50:
            line = lines[i].strip()

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('Interval='):
                bc['interval'] = line.replace('Interval=', '').strip()
            elif line.startswith('Flow Hydrograph='):
                bc['bc_type'] = 'Flow Hydrograph'
                try:
                    bc['data_count'] = int(line.replace('Flow Hydrograph=', '').strip())
                except:
                    pass
            elif line.startswith('Lateral Inflow Hydrograph='):
                bc['bc_type'] = 'Lateral Inflow Hydrograph'
                try:
                    bc['data_count'] = int(line.replace('Lateral Inflow Hydrograph=', '').strip())
                except:
                    pass
            elif line.startswith('Uniform Lateral Inflow='):
                bc['bc_type'] = 'Uniform Lateral Inflow'
                try:
                    bc['data_count'] = int(line.replace('Uniform Lateral Inflow=', '').strip())
                except:
                    pass
            elif line.startswith('Stage Hydrograph='):
                bc['bc_type'] = 'Stage Hydrograph'
            elif line.startswith('Friction Slope='):
                bc['bc_type'] = 'Normal Depth'
            elif line.startswith('Rating Curve='):
                bc['bc_type'] = 'Rating Curve'
            elif line.startswith('DSS File='):
                bc['dss_file'] = line.replace('DSS File=', '').strip()
            elif line.startswith('DSS Path='):
                dss_path = line.replace('DSS Path=', '').strip()
                bc['dss_path'] = dss_path
                # Parse DSS path parts
                if dss_path:
                    dss_parts = RasUnsteady._parse_dss_path(dss_path)
                    bc.update(dss_parts)
            elif line.startswith('Use DSS='):
                bc['use_dss'] = line.replace('Use DSS=', '').strip()

            i += 1

        return bc

    @staticmethod
    def _parse_dss_path(dss_path: str) -> Dict:
        """
        Parse a DSS path into its component parts.

        DSS Path Format: //A/B/C/D/E/F/
        Example: //P100A/FLOW/31MAY2007/5MIN/RUN:1%_24HR/
        """
        parts = {
            'dss_part_a': '',
            'dss_part_b': '',
            'dss_part_c': '',
            'dss_part_d': '',
            'dss_part_e': '',
            'dss_part_f': ''
        }

        # Remove leading slashes and split
        clean_path = dss_path.strip('/')
        segments = clean_path.split('/')

        if len(segments) >= 1:
            parts['dss_part_a'] = segments[0]
        if len(segments) >= 2:
            parts['dss_part_b'] = segments[1]
        if len(segments) >= 3:
            parts['dss_part_c'] = segments[2]
        if len(segments) >= 4:
            parts['dss_part_d'] = segments[3]
        if len(segments) >= 5:
            parts['dss_part_e'] = segments[4]
        if len(segments) >= 6:
            parts['dss_part_f'] = segments[5]

        return parts

    @staticmethod
    @log_call
    def get_inline_hydrograph_boundaries(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract all inline hydrograph boundary conditions from an unsteady flow file.

        This function parses .u## files and extracts boundary conditions that have
        inline time series data (Use DSS=False with Flow Hydrograph or Lateral Inflow
        tables). These are the manually-entered hydrographs that need to be matched
        to HMS subbasins for DSS conversion.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - river: River name
            - reach: Reach name
            - station: River station
            - bc_type: Boundary condition type
            - interval: Time interval (e.g., 5MIN)
            - data_count: Number of data points
            - values: numpy array of hydrograph values
            - peak_value: Maximum flow value
            - peak_index: Index of peak (time step)
            - time_to_peak_hrs: Time to peak in hours
            - min_value: Minimum flow value
            - line_number: Line number of Boundary Location in file

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> inline_bcs = RasUnsteady.get_inline_hydrograph_boundaries("project.u01")
        >>> print(f"Found {len(inline_bcs)} inline hydrograph boundaries")
        >>> for idx, bc in inline_bcs.iterrows():
        ...     print(f"{bc['river']}/{bc['reach']}/{bc['station']}: "
        ...           f"Peak={bc['peak_value']:.0f} cfs @ {bc['time_to_peak_hrs']:.1f} hrs")
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass  # Allow standalone use

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        boundaries = []
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('Boundary Location='):
                bc = RasUnsteady._parse_boundary_block_inline(lines, i)
                if bc.get('has_inline_table') and bc.get('use_dss') == 'False':
                    bc['line_number'] = i + 1
                    boundaries.append(bc)
            i += 1

        df = pd.DataFrame(boundaries)

        # Remove internal fields
        if 'has_inline_table' in df.columns:
            df = df.drop(columns=['has_inline_table'])

        logger.info(f"Found {len(df)} inline hydrograph boundaries in {unsteady_path.name}")
        return df

    @staticmethod
    def _parse_boundary_block_inline(lines: List[str], start_idx: int) -> Dict:
        """Parse a boundary block and extract inline table data."""
        bc = {
            'river': '',
            'reach': '',
            'station': '',
            'bc_type': '',
            'interval': '',
            'data_count': 0,
            'values': None,
            'peak_value': None,
            'peak_index': None,
            'time_to_peak_hrs': None,
            'min_value': None,
            'use_dss': 'False',
            'has_inline_table': False
        }

        # Parse location line
        loc_line = lines[start_idx].replace('Boundary Location=', '')
        parts = [p.strip() for p in loc_line.split(',')]
        if len(parts) >= 1:
            bc['river'] = parts[0]
        if len(parts) >= 2:
            bc['reach'] = parts[1]
        if len(parts) >= 3:
            bc['station'] = parts[2]

        # Scan for boundary info and inline table
        i = start_idx + 1
        table_start = None
        expected_count = 0

        while i < len(lines) and i < start_idx + 100:
            line = lines[i].strip()

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('Interval='):
                bc['interval'] = line.replace('Interval=', '').strip()
            elif line.startswith('Flow Hydrograph='):
                bc['bc_type'] = 'Flow Hydrograph'
                try:
                    expected_count = int(line.replace('Flow Hydrograph=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Lateral Inflow Hydrograph='):
                bc['bc_type'] = 'Lateral Inflow Hydrograph'
                try:
                    expected_count = int(line.replace('Lateral Inflow Hydrograph=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Uniform Lateral Inflow='):
                bc['bc_type'] = 'Uniform Lateral Inflow'
                try:
                    expected_count = int(line.replace('Uniform Lateral Inflow=', '').strip())
                    bc['data_count'] = expected_count
                    if expected_count > 0:
                        bc['has_inline_table'] = True
                        table_start = i + 1
                except:
                    pass
            elif line.startswith('Use DSS='):
                bc['use_dss'] = line.replace('Use DSS=', '').strip()

            i += 1

        # Parse inline table if present
        if bc['has_inline_table'] and table_start and expected_count > 0:
            values = RasUnsteady._parse_inline_values(lines, table_start, expected_count)
            if values is not None and len(values) > 0:
                bc['values'] = values
                bc['min_value'] = float(np.min(values))
                bc['peak_value'] = float(np.max(values))
                bc['peak_index'] = int(np.argmax(values))

                # Calculate time to peak
                if bc['interval']:
                    interval_mins = RasUnsteady._parse_interval_to_minutes(bc['interval'])
                    if interval_mins:
                        bc['time_to_peak_hrs'] = (bc['peak_index'] * interval_mins) / 60.0

        return bc

    @staticmethod
    def _parse_inline_values(lines: List[str], start_idx: int, expected_count: int) -> np.ndarray:
        """Parse inline table values from fixed-width format (8 chars per value)."""
        values = []
        i = start_idx

        while len(values) < expected_count and i < len(lines):
            line = lines[i]

            # Check if line looks like data
            if line.strip() and (line[0].isspace() or line[0].isdigit() or line[0] == '-'):
                # Parse 8-char fixed-width format
                for j in range(0, min(len(line), 80), 8):
                    chunk = line[j:j+8].strip()
                    if chunk:
                        try:
                            values.append(float(chunk))
                        except ValueError:
                            # Try regex for merged numbers
                            nums = re.findall(r'-?\d+\.?\d*', chunk)
                            values.extend([float(n) for n in nums])
            elif '=' in line:
                # Hit a keyword, stop parsing
                break

            i += 1

            # Safety limit
            if i > start_idx + 500:
                break

        return np.array(values[:expected_count]) if values else None

    @staticmethod
    def _parse_interval_to_minutes(interval: str) -> Optional[int]:
        """Convert interval string (e.g., '5MIN', '1HOUR') to minutes."""
        interval = interval.upper().strip()

        # Try numeric + MIN
        match = re.match(r'(\d+)\s*MIN', interval)
        if match:
            return int(match.group(1))

        # Try numeric + HOUR
        match = re.match(r'(\d+)\s*HOUR', interval)
        if match:
            return int(match.group(1)) * 60

        # Try numeric + HR
        match = re.match(r'(\d+)\s*HR', interval)
        if match:
            return int(match.group(1)) * 60

        return None

    @staticmethod
    @log_call
    def update_dss_run_identifier(
        unsteady_file: Union[str, Path],
        old_run_id: str,
        new_run_id: str,
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Update the DSS path run identifier (F-part) for all matching boundaries.

        This function modifies the DSS Path values in a .u## file, changing the
        run identifier (Part F) from one value to another. This is useful when
        updating precipitation from TP40 to Atlas 14, where the run identifier
        indicates the storm scenario.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        old_run_id : str
            Current run identifier to replace (e.g., "RUN:1%_24HR")
        new_run_id : str
            New run identifier value (e.g., "RUN:1%_24HR_ATLAS14")
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Number of DSS paths updated

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Update run identifier from TP40 to Atlas 14
        >>> count = RasUnsteady.update_dss_run_identifier(
        ...     "project.u01",
        ...     old_run_id="RUN:1%_24HR",
        ...     new_run_id="RUN:1%_24HR_ATLAS14"
        ... )
        >>> print(f"Updated {count} DSS paths")

        Notes
        -----
        The DSS path format is: //A/B/C/D/E/F/
        This function modifies Part F (run identifier) while preserving all other parts.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        update_count = 0
        for i, line in enumerate(lines):
            if line.startswith('DSS Path='):
                dss_path = line.replace('DSS Path=', '').strip()
                if old_run_id in dss_path:
                    new_dss_path = dss_path.replace(old_run_id, new_run_id)
                    lines[i] = f'DSS Path={new_dss_path}\n'
                    update_count += 1
                    logger.debug(f"Updated DSS Path at line {i+1}: {dss_path} -> {new_dss_path}")

        if update_count > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated {update_count} DSS paths in {unsteady_path.name}")
        else:
            logger.warning(f"No DSS paths found with run identifier '{old_run_id}'")

        return update_count

    @staticmethod
    @log_call
    def set_boundary_dss_link(
        unsteady_file: Union[str, Path],
        river: str,
        reach: str,
        station: str,
        dss_file: str,
        dss_path: str,
        interval: str = "5MIN",
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Convert an inline hydrograph boundary to use DSS linkage.

        This function modifies a boundary condition in a .u## file to use a DSS
        file reference instead of inline table data. It performs a complete state
        transition: sets Use DSS=True, adds DSS File/Path, sets the inline table
        count to 0, and removes any inline data lines.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river : str
            River name for the boundary
        reach : str
            Reach name for the boundary
        station : str
            River station for the boundary
        dss_file : str
            Path to the DSS file (relative to project folder)
        dss_path : str
            Full DSS path (e.g., "//SUBBASIN/FLOW/DATE/5MIN/RUN:1%_24HR/")
        interval : str, default "5MIN"
            Time interval for the boundary condition
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if boundary was successfully updated, False if not found

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Link a boundary to DSS
        >>> success = RasUnsteady.set_boundary_dss_link(
        ...     "project.u01",
        ...     river="Turkey Creek",
        ...     reach="A119-00-00",
        ...     station="23601.19",
        ...     dss_file="P1000000.dss",
        ...     dss_path="//A119-01-00A/FLOW/31MAY2007/5MIN/RUN:1%_24HR/"
        ... )
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find the boundary location
        boundary_idx = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                loc_line = line.replace('Boundary Location=', '')
                parts = [p.strip() for p in loc_line.split(',')]
                if (len(parts) >= 3 and
                    parts[0] == river and
                    parts[1] == reach and
                    parts[2] == station):
                    boundary_idx = i
                    break

        if boundary_idx is None:
            logger.warning(f"Boundary not found: {river}/{reach}/{station}")
            return False

        # Inline table type keywords that may have data to remove
        TABLE_KEYWORDS = [
            'Flow Hydrograph=', 'Stage Hydrograph=', 'Lateral Inflow Hydrograph=',
            'Uniform Lateral Inflow=', 'Precipitation Hydrograph=',
            'Uniform Lateral Inflow Hydrograph='
        ]

        # Scan the boundary block to find all relevant lines and inline data
        i = boundary_idx + 1
        dss_file_idx = None
        dss_path_idx = None
        use_dss_idx = None
        interval_idx = None
        table_header_idx = None
        table_keyword = None
        inline_data_start = None
        inline_data_end = None

        while i < len(lines) and i < boundary_idx + 500:
            line = lines[i]

            if line.startswith('Boundary Location='):
                break
            elif line.startswith('DSS File='):
                dss_file_idx = i
            elif line.startswith('DSS Path='):
                dss_path_idx = i
            elif line.startswith('Use DSS='):
                use_dss_idx = i
            elif line.startswith('Interval='):
                interval_idx = i
            else:
                # Check for table header keywords
                for kw in TABLE_KEYWORDS:
                    if line.startswith(kw):
                        table_header_idx = i
                        table_keyword = kw
                        # Parse count
                        try:
                            count = int(line.replace(kw, '').strip())
                        except ValueError:
                            count = 0
                        if count > 0:
                            # Find extent of inline data lines
                            inline_data_start = i + 1
                            inline_data_end = inline_data_start
                            for k in range(inline_data_start, len(lines)):
                                data_line = lines[k]
                                if '=' in data_line or data_line.startswith('Boundary Location='):
                                    inline_data_end = k
                                    break
                                if not data_line.strip():
                                    continue
                            else:
                                inline_data_end = len(lines)
                        break
            i += 1

        # Step 1: Remove inline data lines (if any) - do this first to preserve indices
        lines_removed = 0
        if inline_data_start is not None and inline_data_end is not None and inline_data_end > inline_data_start:
            del lines[inline_data_start:inline_data_end]
            lines_removed = inline_data_end - inline_data_start
            logger.debug(f"Removed {lines_removed} inline data lines")
            # Adjust indices for removed lines
            if dss_file_idx is not None and dss_file_idx > inline_data_start:
                dss_file_idx -= lines_removed
            if dss_path_idx is not None and dss_path_idx > inline_data_start:
                dss_path_idx -= lines_removed
            if use_dss_idx is not None and use_dss_idx > inline_data_start:
                use_dss_idx -= lines_removed
            if interval_idx is not None and interval_idx > inline_data_start:
                interval_idx -= lines_removed

        # Step 2: Set table count to 0
        if table_header_idx is not None and table_keyword is not None:
            lines[table_header_idx] = f'{table_keyword} 0 \n'
            logger.debug(f"Set {table_keyword.strip()} count to 0")

        # Step 3: Update existing DSS/interval lines or insert missing ones
        if interval_idx is not None:
            lines[interval_idx] = f'Interval={interval}\n'
        if dss_file_idx is not None:
            lines[dss_file_idx] = f'DSS File={dss_file}\n'
        if dss_path_idx is not None:
            lines[dss_path_idx] = f'DSS Path={dss_path}\n'
        if use_dss_idx is not None:
            lines[use_dss_idx] = 'Use DSS=True\n'

        # Insert any missing lines after the table header (or after boundary location)
        insert_after = table_header_idx if table_header_idx is not None else boundary_idx
        insert_idx = insert_after + 1

        if interval_idx is None:
            lines.insert(insert_idx, f'Interval={interval}\n')
            insert_idx += 1
            # Adjust subsequent indices
            if dss_file_idx is not None and dss_file_idx >= insert_idx - 1:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_idx - 1:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if dss_file_idx is None:
            lines.insert(insert_idx, f'DSS File={dss_file}\n')
            insert_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_idx - 1:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if dss_path_idx is None:
            lines.insert(insert_idx, f'DSS Path={dss_path}\n')
            insert_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_idx - 1:
                use_dss_idx += 1

        if use_dss_idx is None:
            lines.insert(insert_idx, 'Use DSS=True\n')

        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        logger.info(f"Updated boundary {river}/{reach}/{station} to use DSS link "
                     f"(removed {lines_removed} inline data lines)")
        return True

    @staticmethod
    @log_call
    def set_boundary_inline_hydrograph(
        unsteady_file: Union[str, Path],
        hydrograph_df: pd.DataFrame,
        bc_type: str = "Flow Hydrograph",
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[str] = None,
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Write an inline hydrograph table to a boundary condition, converting from DSS if needed.

        This method performs a complete DSS→inline state transition: sets Use DSS=False,
        removes DSS File/Path lines, writes inline hydrograph data in HEC-RAS fixed-width
        format, and updates the table count and Interval line.

        The method follows the same pattern as ``set_precipitation_hyetograph()`` for
        inline table writing.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##) or unsteady number (e.g., "01")
        hydrograph_df : pd.DataFrame
            DataFrame with columns:

            - ``'hour'``: Time in hours from start (float)
            - ``'value'``: Hydrograph value at each time step (flow in cfs/cms or stage in ft/m)

        bc_type : str, default "Flow Hydrograph"
            Boundary condition type. Must be one of:

            - ``"Flow Hydrograph"``
            - ``"Stage Hydrograph"``
            - ``"Lateral Inflow Hydrograph"``
            - ``"Uniform Lateral Inflow"``

        river : str, optional
            River name to locate the boundary. If None, updates the first matching bc_type.
        reach : str, optional
            Reach name to locate the boundary.
        station : str, optional
            River station to locate the boundary.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if boundary was successfully updated, False if not found

        Raises
        ------
        ValueError
            If DataFrame is missing required columns or bc_type is unsupported
        FileNotFoundError
            If unsteady flow file not found

        Example
        -------
        >>> import pandas as pd
        >>> from ras_commander import RasUnsteady
        >>> # Create a simple flow hydrograph
        >>> hours = list(range(25))
        >>> flows = [100, 150, 300, 600, 1200, 2000, 3000, 4000, 5000, 4500,
        ...          4000, 3500, 3000, 2500, 2000, 1700, 1400, 1200, 1000,
        ...          800, 600, 400, 300, 200, 100]
        >>> df = pd.DataFrame({'hour': hours, 'value': flows})
        >>> RasUnsteady.set_boundary_inline_hydrograph(
        ...     "project.u01", df, bc_type="Flow Hydrograph",
        ...     river="White", reach="Muncie", station="15696.24"
        ... )

        Notes
        -----
        **Inline Hydrograph Format** (HEC-RAS .u## files):

        Flow/Stage/Lateral hydrographs store values only (not time-value pairs).
        Each value is 8 characters wide, 10 values per line. The count on the header
        line is the number of values, and time is implied from the Interval setting.

        This differs from Precipitation Hydrograph which stores (time, depth) pairs.

        **State Transition**:

        When converting from DSS mode, this method:

        1. Sets ``Use DSS=False``
        2. Removes ``DSS File=`` and ``DSS Path=`` content (sets to empty)
        3. Writes inline data after the hydrograph header line
        4. Updates the value count and Interval line

        See Also
        --------
        set_boundary_dss_link : Convert inline boundary to DSS mode
        set_precipitation_hyetograph : Write precipitation hyetograph (uses time-value pairs)
        """
        SUPPORTED_TYPES = {
            "Flow Hydrograph": "Flow Hydrograph=",
            "Stage Hydrograph": "Stage Hydrograph=",
            "Lateral Inflow Hydrograph": "Lateral Inflow Hydrograph=",
            "Uniform Lateral Inflow": "Uniform Lateral Inflow=",
            "Uniform Lateral Inflow Hydrograph": "Uniform Lateral Inflow Hydrograph=",
        }

        if bc_type not in SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported bc_type: '{bc_type}'. "
                f"Supported types: {list(SUPPORTED_TYPES.keys())}"
            )

        table_keyword = SUPPORTED_TYPES[bc_type]

        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        # Resolve unsteady file path
        if isinstance(unsteady_file, str) and len(unsteady_file) <= 2:
            unsteady_num = unsteady_file.zfill(2)
            unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{unsteady_num}"
        else:
            unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Validate DataFrame columns
        required_columns = ['hour', 'value']
        missing_columns = [col for col in required_columns if col not in hydrograph_df.columns]
        if missing_columns:
            raise ValueError(
                f"DataFrame missing required columns: {missing_columns}. "
                f"Required columns: {required_columns}"
            )

        # Extract values
        hours = hydrograph_df['hour'].values
        values = hydrograph_df['value'].values
        num_values = len(values)

        if num_values < 2:
            raise ValueError("DataFrame must have at least 2 rows")

        # Calculate interval from hour column
        interval_hours = float(hours[1] - hours[0])
        if interval_hours >= 1.0:
            if interval_hours == int(interval_hours):
                interval_str = f"{int(interval_hours)}HOUR"
            else:
                interval_min = int(interval_hours * 60)
                interval_str = f"{interval_min}MIN"
        else:
            interval_min = int(interval_hours * 60)
            interval_str = f"{interval_min}MIN"

        # Format values as fixed-width (8 chars each, 10 values per line)
        # Flow/Stage hydrographs use values only (not time-value pairs)
        formatted_lines = []
        for i in range(0, num_values, 10):
            row_values = values[i:i+10]
            formatted_row = ''.join(f'{v:8.2f}' if abs(v) < 1e7 else f'{v:8.1f}'
                                    for v in row_values)
            formatted_lines.append(formatted_row + '\n')

        # Read the file
        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Find the target boundary
        target_boundary_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                if river is not None or reach is not None or station is not None:
                    loc_line = line.replace('Boundary Location=', '')
                    parts = [p.strip() for p in loc_line.split(',')]
                    match = True
                    if river is not None and (len(parts) < 1 or parts[0] != river):
                        match = False
                    if reach is not None and (len(parts) < 2 or parts[1] != reach):
                        match = False
                    if station is not None and (len(parts) < 3 or parts[2] != station):
                        match = False
                    if match:
                        target_boundary_idx = idx
                        break
                else:
                    # No location filter - find first boundary with matching bc_type
                    # Scan ahead to check bc_type
                    for j in range(idx + 1, min(idx + 50, len(lines))):
                        if lines[j].startswith('Boundary Location='):
                            break
                        if lines[j].startswith(table_keyword):
                            target_boundary_idx = idx
                            break
                    if target_boundary_idx is not None:
                        break

        if target_boundary_idx is None:
            loc_str = f"{river}/{reach}/{station}" if river else "first matching"
            logger.warning(f"Boundary not found for {bc_type}: {loc_str}")
            return False

        # Scan the boundary block for relevant lines
        block_start = target_boundary_idx + 1
        table_header_idx = None
        interval_idx = None
        dss_file_idx = None
        dss_path_idx = None
        use_dss_idx = None
        old_data_start = None
        old_data_end = None
        block_end = len(lines)

        i = block_start
        while i < len(lines) and i < target_boundary_idx + 500:
            line = lines[i]

            if line.startswith('Boundary Location='):
                block_end = i
                break
            elif line.startswith('Interval='):
                interval_idx = i
            elif line.startswith(table_keyword):
                table_header_idx = i
                # Check if there are existing inline data lines
                try:
                    old_count = int(line.replace(table_keyword, '').strip())
                except ValueError:
                    old_count = 0
                if old_count > 0:
                    old_data_start = i + 1
                    # Find end of old data
                    for k in range(old_data_start, len(lines)):
                        data_line = lines[k]
                        if '=' in data_line or data_line.startswith('Boundary Location='):
                            old_data_end = k
                            break
                    else:
                        old_data_end = len(lines)
            elif line.startswith('DSS File='):
                dss_file_idx = i
            elif line.startswith('DSS Path='):
                dss_path_idx = i
            elif line.startswith('Use DSS='):
                use_dss_idx = i

            i += 1

        # Step 1: Remove old inline data (if any)
        lines_removed = 0
        if old_data_start is not None and old_data_end is not None and old_data_end > old_data_start:
            del lines[old_data_start:old_data_end]
            lines_removed = old_data_end - old_data_start
            # Adjust indices
            for attr in ['interval_idx', 'dss_file_idx', 'dss_path_idx', 'use_dss_idx']:
                val = locals().get(attr)
                if val is not None and val > old_data_start:
                    locals()[attr] = val - lines_removed
            # Re-read adjusted indices from locals
            if interval_idx is not None and interval_idx > old_data_start:
                interval_idx -= lines_removed
            if dss_file_idx is not None and dss_file_idx > old_data_start:
                dss_file_idx -= lines_removed
            if dss_path_idx is not None and dss_path_idx > old_data_start:
                dss_path_idx -= lines_removed
            if use_dss_idx is not None and use_dss_idx > old_data_start:
                use_dss_idx -= lines_removed

        # Step 2: Update table header with new count
        if table_header_idx is not None:
            lines[table_header_idx] = f'{table_keyword} {num_values} \n'
        else:
            # Insert table header after Interval line (or after boundary location)
            insert_pos = interval_idx + 1 if interval_idx is not None else target_boundary_idx + 1
            lines.insert(insert_pos, f'{table_keyword} {num_values} \n')
            table_header_idx = insert_pos
            # Adjust indices after insertion
            if interval_idx is not None and interval_idx >= insert_pos:
                interval_idx += 1
            if dss_file_idx is not None and dss_file_idx >= insert_pos:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= insert_pos:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= insert_pos:
                use_dss_idx += 1

        # Step 3: Insert new inline data right after table header
        insert_pos = table_header_idx + 1
        for j, data_line in enumerate(formatted_lines):
            lines.insert(insert_pos + j, data_line)
        lines_inserted = len(formatted_lines)

        # Adjust indices for inserted lines
        if interval_idx is not None and interval_idx >= insert_pos:
            interval_idx += lines_inserted
        if dss_file_idx is not None and dss_file_idx >= insert_pos:
            dss_file_idx += lines_inserted
        if dss_path_idx is not None and dss_path_idx >= insert_pos:
            dss_path_idx += lines_inserted
        if use_dss_idx is not None and use_dss_idx >= insert_pos:
            use_dss_idx += lines_inserted

        # Step 4: Update Interval line
        if interval_idx is not None:
            lines[interval_idx] = f'Interval={interval_str}\n'
        else:
            # Insert interval before table header
            lines.insert(table_header_idx, f'Interval={interval_str}\n')
            # Adjust all indices after this insertion
            if dss_file_idx is not None and dss_file_idx >= table_header_idx:
                dss_file_idx += 1
            if dss_path_idx is not None and dss_path_idx >= table_header_idx:
                dss_path_idx += 1
            if use_dss_idx is not None and use_dss_idx >= table_header_idx:
                use_dss_idx += 1

        # Step 5: Set Use DSS=False and clear DSS File/Path
        if use_dss_idx is not None:
            lines[use_dss_idx] = 'Use DSS=False\n'
        if dss_file_idx is not None:
            lines[dss_file_idx] = 'DSS File=\n'
        if dss_path_idx is not None:
            lines[dss_path_idx] = 'DSS Path=\n'

        # Write updated content back to file
        with open(unsteady_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        peak_value = float(np.max(values))
        logger.info(
            f"Updated {bc_type} inline hydrograph in {unsteady_path.name}: "
            f"{num_values} values, interval={interval_str}, "
            f"peak={peak_value:.2f}"
        )
        return True

    @staticmethod
    @log_call
    def get_unique_dss_subbasins(
        unsteady_file: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> List[str]:
        """
        Get list of unique HMS subbasin names from DSS paths in unsteady file.

        This convenience function extracts the DSS Part B (location/subbasin)
        from all DSS-linked boundaries and returns the unique values. This is
        useful for identifying which HMS subbasins are used by the RAS model.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        List[str]
            Sorted list of unique subbasin names from DSS Part B

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> subbasins = RasUnsteady.get_unique_dss_subbasins("project.u01")
        >>> print(f"Model uses {len(subbasins)} HMS subbasins:")
        >>> for sb in subbasins[:10]:
        ...     print(f"  - {sb}")
        """
        df = RasUnsteady.get_dss_boundaries(unsteady_file, ras_object)

        if df.empty:
            return []

        # Get unique Part B values (subbasin names)
        subbasins = df['dss_part_b'].dropna().unique().tolist()
        subbasins = [s for s in subbasins if s]  # Remove empty strings
        subbasins.sort()

        logger.info(f"Found {len(subbasins)} unique HMS subbasins in DSS paths")
        return subbasins

    @staticmethod
    @log_call
    def update_dss_path_by_station(
        unsteady_file: Union[str, Path],
        river_station: str,
        new_a_part: str,
        old_a_part: str = None,
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Update the DSS Path A-part for boundary conditions at a specific river station.

        This function modifies the DSS Path values in a .u## file, changing the
        A-part (first segment) from one value to another. Useful for mapping HMS
        subbasins to different DSS outputs.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river_station : str
            River station identifier (partial match supported)
        new_a_part : str
            New A-part value (e.g., "A120A")
        old_a_part : str, optional
            Only replace if current A-part matches this value. If None, replaces
            regardless of current value.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Number of DSS paths updated

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Update A-part for boundary at specific station
        >>> count = RasUnsteady.update_dss_path_by_station(
        ...     "project.u02",
        ...     river_station="23280.75",
        ...     old_a_part="A1200000_2347_J",
        ...     new_a_part="A120A"
        ... )
        >>> print(f"Updated {count} DSS paths")
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        update_count = 0
        i = 0
        while i < len(lines):
            line = lines[i]

            # Find matching Boundary Location
            if line.startswith('Boundary Location=') and river_station in line:
                # Look for DSS Path within this boundary block (search forward)
                j = i + 1
                while j < len(lines) and j < i + 50:
                    if lines[j].startswith('Boundary Location='):
                        break  # Next boundary block
                    if lines[j].startswith('DSS Path='):
                        dss_path = lines[j].replace('DSS Path=', '').strip()
                        # Parse current A-part
                        clean_path = dss_path.strip('/')
                        parts = clean_path.split('/')
                        if len(parts) >= 1:
                            current_a_part = parts[0]
                            # Check if we should update (old_a_part matches or not specified)
                            if old_a_part is None or current_a_part == old_a_part:
                                # Build new path with new A-part
                                parts[0] = new_a_part
                                new_dss_path = '//' + '/'.join(parts) + '/'
                                lines[j] = f'DSS Path={new_dss_path}\n'
                                update_count += 1
                                logger.debug(f"Updated DSS Path at line {j+1}: A-part '{current_a_part}' -> '{new_a_part}'")
                        break
                    j += 1
            i += 1

        if update_count > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated {update_count} DSS paths in {unsteady_path.name}")
        else:
            if old_a_part:
                logger.warning(f"No DSS paths found for station '{river_station}' with A-part '{old_a_part}'")
            else:
                logger.warning(f"No DSS paths found for station '{river_station}'")

        return update_count

    @staticmethod
    @log_call
    def update_flow_multiplier_by_station(
        unsteady_file: Union[str, Path],
        river_station: str,
        new_multiplier: float,
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Update or insert Flow Hydrograph QMult for boundary at specific river station.

        If the `Flow Hydrograph QMult=` line exists, it will be updated. If it doesn't
        exist, it will be inserted after the Flow Hydrograph line.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        river_station : str
            River station identifier (partial match supported)
        new_multiplier : float
            New multiplier value (e.g., 0.5, 1.0)
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        bool
            True if multiplier was updated/inserted, False if boundary not found

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> # Set flow multiplier to 0.75 for specific boundary
        >>> success = RasUnsteady.update_flow_multiplier_by_station(
        ...     "project.u02",
        ...     river_station="5714.48",
        ...     new_multiplier=0.75
        ... )
        >>> if success:
        ...     print("Multiplier updated successfully")

        Notes
        -----
        The QMult line appears in unsteady files as:
            Flow Hydrograph QMult= 0.5

        If this line doesn't exist, it will be inserted after the Flow Hydrograph line
        in the boundary block.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        updated = False
        i = 0
        while i < len(lines):
            line = lines[i]

            # Find matching Boundary Location
            if line.startswith('Boundary Location=') and river_station in line:
                boundary_idx = i
                qmult_idx = None
                flow_hydro_idx = None
                block_end_idx = None

                # Scan the boundary block
                j = i + 1
                while j < len(lines) and j < i + 50:
                    current_line = lines[j]
                    if current_line.startswith('Boundary Location='):
                        block_end_idx = j
                        break
                    if current_line.startswith('Flow Hydrograph QMult='):
                        qmult_idx = j
                    if current_line.startswith('Flow Hydrograph='):
                        flow_hydro_idx = j
                    j += 1

                if block_end_idx is None:
                    block_end_idx = len(lines)

                # Format the new QMult line
                qmult_line = f'Flow Hydrograph QMult= {new_multiplier}\n'

                if qmult_idx is not None:
                    # Update existing line
                    old_value = lines[qmult_idx].replace('Flow Hydrograph QMult=', '').strip()
                    lines[qmult_idx] = qmult_line
                    logger.debug(f"Updated QMult at line {qmult_idx+1}: {old_value} -> {new_multiplier}")
                    updated = True
                elif flow_hydro_idx is not None:
                    # Insert after Flow Hydrograph line (skip the data values first)
                    # Find the end of hydrograph data by looking for next key=value line
                    insert_idx = flow_hydro_idx + 1
                    while insert_idx < block_end_idx:
                        test_line = lines[insert_idx].strip()
                        if '=' in test_line and not test_line[0].isdigit():
                            break
                        insert_idx += 1
                    lines.insert(insert_idx, qmult_line)
                    logger.debug(f"Inserted QMult at line {insert_idx+1}: {new_multiplier}")
                    updated = True
                else:
                    # No Flow Hydrograph found, insert after Boundary Location
                    lines.insert(boundary_idx + 1, qmult_line)
                    logger.debug(f"Inserted QMult at line {boundary_idx+2}: {new_multiplier}")
                    updated = True

                break  # Found and processed the matching boundary
            i += 1

        if updated:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Updated QMult to {new_multiplier} for station '{river_station}' in {unsteady_path.name}")
        else:
            logger.warning(f"Boundary not found for station '{river_station}'")

        return updated

    @staticmethod
    @log_call
    def update_boundary_dss_paths(
        unsteady_file: Union[str, Path],
        updates: List[Dict[str, Any]],
        ras_object: Optional[Any] = None
    ) -> int:
        """
        Apply multiple DSS path and multiplier updates to boundary conditions.

        This batch method processes multiple updates in a single file read/write
        cycle for efficiency. Each update can specify any combination of A-part
        change and/or multiplier change.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        updates : List[Dict[str, Any]]
            List of update dictionaries. Each dict can contain:
            - river_station: str (required) - partial match supported
            - new_a_part: str (optional) - new DSS A-part value
            - old_a_part: str (optional) - only replace if current A-part matches
            - new_multiplier: float (optional) - new QMult value
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        int
            Total number of updates applied

        Example
        -------
        >>> from ras_commander import RasUnsteady
        >>> updates = [
        ...     {'river_station': '23280.75', 'old_a_part': 'A1200000_2347_J', 'new_a_part': 'A120A'},
        ...     {'river_station': '12727.63', 'old_a_part': 'A120D1', 'new_a_part': 'A120C'},
        ...     {'river_station': '5714.48', 'new_multiplier': 0.75},
        ...     {'river_station': '29113.3', 'new_a_part': 'A120B', 'new_multiplier': 0.5},
        ... ]
        >>> count = RasUnsteady.update_boundary_dss_paths("project.u02", updates)
        >>> print(f"Applied {count} updates")

        Notes
        -----
        This method reads the file once, applies all updates in memory, and writes
        once. This is more efficient than calling individual update methods for
        each boundary, especially when updating many boundaries.
        """
        ras_obj = ras_object or ras
        if ras_obj is not None:
            try:
                ras_obj.check_initialized()
            except:
                pass

        if not updates:
            logger.warning("No updates provided")
            return 0

        unsteady_path = Path(unsteady_file)
        if not unsteady_path.exists():
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        with open(unsteady_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        total_updates = 0

        for update in updates:
            river_station = update.get('river_station')
            if not river_station:
                logger.warning("Update missing 'river_station' key, skipping")
                continue

            new_a_part = update.get('new_a_part')
            old_a_part = update.get('old_a_part')
            new_multiplier = update.get('new_multiplier')

            # Find the boundary block
            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith('Boundary Location=') and river_station in line:
                    boundary_idx = i
                    block_end_idx = None
                    dss_path_idx = None
                    qmult_idx = None
                    flow_hydro_idx = None

                    # Scan the boundary block
                    j = i + 1
                    while j < len(lines) and j < i + 50:
                        current_line = lines[j]
                        if current_line.startswith('Boundary Location='):
                            block_end_idx = j
                            break
                        if current_line.startswith('DSS Path='):
                            dss_path_idx = j
                        if current_line.startswith('Flow Hydrograph QMult='):
                            qmult_idx = j
                        if current_line.startswith('Flow Hydrograph='):
                            flow_hydro_idx = j
                        j += 1

                    if block_end_idx is None:
                        block_end_idx = len(lines)

                    # Update DSS A-part if requested
                    if new_a_part and dss_path_idx is not None:
                        dss_path = lines[dss_path_idx].replace('DSS Path=', '').strip()
                        clean_path = dss_path.strip('/')
                        parts = clean_path.split('/')
                        if len(parts) >= 1:
                            current_a_part = parts[0]
                            if old_a_part is None or current_a_part == old_a_part:
                                parts[0] = new_a_part
                                new_dss_path = '//' + '/'.join(parts) + '/'
                                lines[dss_path_idx] = f'DSS Path={new_dss_path}\n'
                                total_updates += 1
                                logger.debug(f"Updated A-part for station '{river_station}': '{current_a_part}' -> '{new_a_part}'")

                    # Update/insert QMult if requested
                    if new_multiplier is not None:
                        qmult_line = f'Flow Hydrograph QMult= {new_multiplier}\n'

                        if qmult_idx is not None:
                            lines[qmult_idx] = qmult_line
                            total_updates += 1
                            logger.debug(f"Updated QMult for station '{river_station}': {new_multiplier}")
                        elif flow_hydro_idx is not None:
                            # Find insertion point after hydrograph data
                            insert_idx = flow_hydro_idx + 1
                            while insert_idx < block_end_idx:
                                test_line = lines[insert_idx].strip()
                                if '=' in test_line and not test_line[0].isdigit():
                                    break
                                insert_idx += 1
                            lines.insert(insert_idx, qmult_line)
                            # Adjust indices for subsequent operations
                            block_end_idx += 1
                            total_updates += 1
                            logger.debug(f"Inserted QMult for station '{river_station}': {new_multiplier}")
                        else:
                            lines.insert(boundary_idx + 1, qmult_line)
                            total_updates += 1
                            logger.debug(f"Inserted QMult for station '{river_station}': {new_multiplier}")

                    break  # Found and processed this station
                i += 1

        if total_updates > 0:
            with open(unsteady_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"Applied {total_updates} updates to {unsteady_path.name}")
        else:
            logger.warning("No matching boundaries found for any updates")

        return total_updates
