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
    def _update_precipitation_hdf(
        hdf_path: Path,
        netcdf_path: Path,
        netcdf_rel_path: str,
        interpolation: str = "Bilinear"
    ) -> None:
        """
        Import precipitation raster data into HDF in HEC-RAS format.

        This function imports gridded precipitation from NetCDF into the HDF file
        in the exact format HEC-RAS expects when using "Import Raster Data" in the GUI.

        The data is transformed from instantaneous rates to cumulative totals and
        flattened from (time, y, x) to (time, rows*cols) shape.

        Parameters
        ----------
        hdf_path : Path
            Path to the unsteady HDF file (.u##.hdf)
        netcdf_path : Path
            Absolute path to the NetCDF precipitation file
        netcdf_rel_path : str
            Relative path string for HDF attributes (e.g., ".\\Precipitation\\file.nc")
        interpolation : str
            Interpolation method ("Bilinear" or "Nearest")
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
        x_max = float(x_coords.max())
        y_min = float(y_coords.min())
        y_max = float(y_coords.max())

        # Raster bounds (cell edges, not centers)
        raster_left = x_min - cellsize / 2
        raster_right = x_max + cellsize / 2
        raster_bottom = y_min - cellsize / 2
        raster_top = y_max + cellsize / 2

        # Transform data: flatten spatial dims and convert to cumulative
        # Shape: (time, y, x) -> (time, rows*cols)
        precip_flat = precip_data.reshape(n_times, n_rows * n_cols)

        # Replace NaN with 0 for cumsum calculation
        precip_flat = np.nan_to_num(precip_flat, nan=0.0)

        # Convert from instantaneous rate (mm/hr) to cumulative total (mm)
        precip_cumulative = np.cumsum(precip_flat, axis=0).astype(np.float32)

        # Create timestamp strings in HEC-RAS format for Timestamp dataset
        import pandas as pd
        timestamps = pd.to_datetime(times)
        timestamp_strs = [t.strftime('%d%b%Y %H:%M:%S') for t in timestamps]
        # Create ISO 8601 format timestamps for Times attribute on Values datasets
        timestamp_iso = [t.strftime('%Y-%m-%d %H:%M:%S') for t in timestamps]

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
                precip_grp_path = 'Event Conditions/Meteorology/Precipitation'

                # Create parent groups if they don't exist
                if precip_grp_path not in f:
                    logger.info(f"Creating precipitation group hierarchy in HDF")
                    # Create Event Conditions if needed
                    if 'Event Conditions' not in f:
                        f.create_group('Event Conditions')
                    # Create Meteorology if needed
                    met_path = 'Event Conditions/Meteorology'
                    if met_path not in f:
                        f.create_group(met_path)
                    # Create Precipitation group
                    f.create_group(precip_grp_path)

                precip_grp = f[precip_grp_path]

                # Update Precipitation group attributes (use uint8 for Enabled like HEC-RAS does)
                precip_grp.attrs['Enabled'] = np.uint8(1)
                precip_grp.attrs['Mode'] = np.bytes_('Gridded')
                precip_grp.attrs['Source'] = np.bytes_('GDAL Raster File(s)')
                precip_grp.attrs['GDAL Filename'] = np.bytes_(netcdf_rel_path)
                precip_grp.attrs['GDAL Datasetname'] = np.bytes_('')
                precip_grp.attrs['GDAL Filter'] = np.bytes_('')
                precip_grp.attrs['GDAL Folder'] = np.bytes_('')
                precip_grp.attrs['Interpolation Method'] = np.bytes_(interpolation)

                # Create/update Meteorology Attributes index dataset
                # This tells HEC-RAS which meteorology variables are active
                met_attrs_path = 'Event Conditions/Meteorology/Attributes'
                if met_attrs_path in f:
                    del f[met_attrs_path]
                dt = np.dtype([('Variable', 'S32'), ('Group', 'S42')])
                attrs_data = np.array([(b'Precipitation', b'Event Conditions/Meteorology/Precipitation')], dtype=dt)
                f.create_dataset(met_attrs_path, data=attrs_data)

                # Create/recreate Imported Raster Data group
                raster_grp_path = f'{precip_grp_path}/Imported Raster Data'
                if raster_grp_path in f:
                    del f[raster_grp_path]

                raster_grp = f.create_group(raster_grp_path)

                # Raster extent attributes on group
                raster_grp.attrs['Cellsize'] = np.float64(cellsize)
                raster_grp.attrs['Cols'] = np.int32(n_cols)
                raster_grp.attrs['Rows'] = np.int32(n_rows)
                raster_grp.attrs['Left'] = np.float64(raster_left)
                raster_grp.attrs['Right'] = np.float64(raster_right)
                raster_grp.attrs['Bottom'] = np.float64(raster_bottom)
                raster_grp.attrs['Top'] = np.float64(raster_top)

                # Create Timestamp dataset
                dt = h5py.string_dtype(encoding='ascii', length=22)
                raster_grp.create_dataset('Timestamp', data=timestamp_strs, dtype=dt)

                # Common attributes for Values datasets
                values_attrs = {
                    'Data Type': np.bytes_('cumulative'),
                    'GUID': np.bytes_(guid),
                    'NoData': np.float64(-9999.0),
                    'Projection': np.bytes_(srs_wkt),
                    'Raster Cellsize': np.float64(cellsize),
                    'Raster Cols': np.int32(n_cols),
                    'Raster Left': np.float64(raster_left),
                    'Raster Rows': np.int32(n_rows),
                    'Raster Top': np.float64(raster_top),
                    'Rate Time Units': np.bytes_('Hour'),
                    'Storage Configuration': np.bytes_('Sequential'),
                    'Time Series Data Type': np.bytes_('Amount'),
                    'Times': np.array(timestamp_iso, dtype='S19'),
                    'Units': np.bytes_('mm'),
                    'Version': np.bytes_('1.0'),
                }

                # Create Values dataset - shape (n_times, n_rows*n_cols)
                # Use gzip compression, chunking, and nan fillvalue to match HEC-RAS format
                n_cells = n_rows * n_cols
                values_ds = raster_grp.create_dataset(
                    'Values',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan,
                    maxshape=(None, None)
                )
                for attr_name, attr_val in values_attrs.items():
                    values_ds.attrs[attr_name] = attr_val

                # Create Values (Vertical) dataset - same data as Values
                values_vert_ds = raster_grp.create_dataset(
                    'Values (Vertical)',
                    data=precip_cumulative,
                    dtype=np.float32,
                    chunks=(n_times, n_cells),
                    compression='gzip',
                    compression_opts=1,
                    fillvalue=np.nan,
                    maxshape=(None, None)
                )
                for attr_name, attr_val in values_attrs.items():
                    values_vert_ds.attrs[attr_name] = attr_val

                logger.info(f"  Imported {n_times} timesteps, {n_rows*n_cols} cells (cumulative)")
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




