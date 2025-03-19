"""
RasPrj.py - Manages HEC-RAS projects within the ras-commander library

This module provides a class for managing HEC-RAS projects.

Classes:
    RasPrj: A class for managing HEC-RAS projects.

Functions:
    init_ras_project: Initialize a RAS project.
    get_ras_exe: Determine the HEC-RAS executable path based on the input.

DEVELOPER NOTE:
This class is used to initialize a RAS project and is used in conjunction with the RasCmdr class to manage the execution of RAS plans.
By default, the RasPrj class is initialized with the global 'ras' object.
However, you can create multiple RasPrj instances to manage multiple projects.
Do not mix and match global 'ras' object instances and custom instances of RasPrj - it will cause errors.

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

All of the methods in this class are class methods and are designed to be used with instances of the class.

List of Functions in RasPrj:    
- initialize()
- _load_project_data()
- _get_geom_file_for_plan()
- _parse_plan_file()
- _parse_unsteady_file()
- _get_prj_entries()
- _parse_boundary_condition()
- is_initialized (property)
- check_initialized()
- find_ras_prj()
- get_project_name()
- get_prj_entries()
- get_plan_entries()
- get_flow_entries()
- get_unsteady_entries()
- get_geom_entries()
- get_hdf_entries()
- print_data()
- get_plan_value()
- get_boundary_conditions()
        
Functions in RasPrj that are not part of the class:        
- init_ras_project()
- get_ras_exe()

        
        
        
"""
import os
import re
from pathlib import Path
import pandas as pd
from typing import Union, Any, List, Dict, Tuple
import logging
from ras_commander.LoggingConfig import get_logger
from ras_commander.Decorators import log_call

logger = get_logger(__name__)

def read_file_with_fallback_encoding(file_path, encodings=['utf-8', 'latin1', 'cp1252', 'iso-8859-1']):
    """
    Attempt to read a file using multiple encodings.
    
    Args:
        file_path (str or Path): Path to the file to read
        encodings (list): List of encodings to try, in order of preference
    
    Returns:
        tuple: (content, encoding) or (None, None) if all encodings fail
    """
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as file:
                content = file.read()
                return content, encoding
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error(f"Error reading file {file_path} with {encoding} encoding: {e}")
            continue
    
    logger.error(f"Failed to read file {file_path} with any of the attempted encodings: {encodings}")
    return None, None

class RasPrj:
    
    def __init__(self):
        self.initialized = False
        self.boundaries_df = None  # New attribute to store boundary conditions
        self.suppress_logging = False  # Add suppress_logging as instance variable

    @log_call
    def initialize(self, project_folder, ras_exe_path, suppress_logging=True):
        """
        Initialize a RasPrj instance.

        This method sets up the RasPrj instance with the given project folder and RAS executable path.
        It finds the project file, loads project data, sets the initialization flag, and now also
        extracts boundary conditions.

        Args:
            project_folder (str or Path): Path to the HEC-RAS project folder.
            ras_exe_path (str or Path): Path to the HEC-RAS executable.
            suppress_logging (bool): If True, suppresses initialization logging messages.

        Raises:
            ValueError: If no HEC-RAS project file is found in the specified folder.

        Note:
            This method is intended for internal use. External users should use the init_ras_project function instead.
        """
        self.suppress_logging = suppress_logging  # Store suppress_logging state
        self.project_folder = Path(project_folder)
        self.prj_file = self.find_ras_prj(self.project_folder)
        if self.prj_file is None:
            logger.error(f"No HEC-RAS project file found in {self.project_folder}")
            raise ValueError(f"No HEC-RAS project file found in {self.project_folder}")
        self.project_name = Path(self.prj_file).stem
        self.ras_exe_path = ras_exe_path
        self._load_project_data()
        self.boundaries_df = self.get_boundary_conditions()  # Extract boundary conditions
        self.initialized = True
        
        if not suppress_logging:
            logger.info(f"Initialization complete for project: {self.project_name}")
            logger.info(f"Plan entries: {len(self.plan_df)}, Flow entries: {len(self.flow_df)}, "
                         f"Unsteady entries: {len(self.unsteady_df)}, Geometry entries: {len(self.geom_df)}, "
                         f"Boundary conditions: {len(self.boundaries_df)}")
            logger.info(f"Geometry HDF files found: {self.plan_df['Geom_File'].notna().sum()}")

    @log_call
    def _load_project_data(self):
        """
        Load project data from the HEC-RAS project file.

        This method initializes DataFrames for plan, flow, unsteady, and geometry entries
        and ensures all required columns are present with appropriate paths.
        """
        try:
            # Load data frames
            self.unsteady_df = self._get_prj_entries('Unsteady')
            self.plan_df = self._get_prj_entries('Plan')
            self.flow_df = self._get_prj_entries('Flow')
            self.geom_df = self.get_geom_entries()
            
            # Ensure required columns exist
            self._ensure_required_columns()
            
            # Set paths for geometry and flow files
            self._set_file_paths()
            
            # Make sure all plan paths are properly set
            self._set_plan_paths()
            
        except Exception as e:
            logger.error(f"Error loading project data: {e}")
            raise

    def _ensure_required_columns(self):
        """Ensure all required columns exist in plan_df."""
        required_columns = [
            'plan_number', 'unsteady_number', 'geometry_number',
            'Geom File', 'Geom Path', 'Flow File', 'Flow Path', 'full_path'
        ]
        
        for col in required_columns:
            if col not in self.plan_df.columns:
                self.plan_df[col] = None
        
        if not self.plan_df['full_path'].any():
            self.plan_df['full_path'] = self.plan_df['plan_number'].apply(
                lambda x: str(self.project_folder / f"{self.project_name}.p{x}")
            )

    def _set_file_paths(self):
        """Set geometry and flow paths in plan_df."""
        for idx, row in self.plan_df.iterrows():
            try:
                self._set_geom_path(idx, row)
                self._set_flow_path(idx, row)
                
                if not self.suppress_logging:
                    logger.info(f"Plan {row['plan_number']} paths set up")
            except Exception as e:
                logger.error(f"Error processing plan file {row['plan_number']}: {e}")

    def _set_geom_path(self, idx: int, row: pd.Series):
        """Set geometry path for a plan entry."""
        if pd.notna(row['Geom File']):
            geom_path = self.project_folder / f"{self.project_name}.g{row['Geom File']}"
            self.plan_df.at[idx, 'Geom Path'] = str(geom_path)

    def _set_flow_path(self, idx: int, row: pd.Series):
        """Set flow path for a plan entry."""
        if pd.notna(row['Flow File']):
            prefix = 'u' if pd.notna(row['unsteady_number']) else 'f'
            flow_path = self.project_folder / f"{self.project_name}.{prefix}{row['Flow File']}"
            self.plan_df.at[idx, 'Flow Path'] = str(flow_path)

    def _set_plan_paths(self):
        """Set full path information for plan files and their associated geometry and flow files."""
        if self.plan_df.empty:
            logger.debug("Plan DataFrame is empty, no paths to set")
            return
        
        # Ensure full path is set for all plan entries
        if 'full_path' not in self.plan_df.columns or self.plan_df['full_path'].isna().any():
            self.plan_df['full_path'] = self.plan_df['plan_number'].apply(
                lambda x: str(self.project_folder / f"{self.project_name}.p{x}")
            )
        
        # Create the Geom Path and Flow Path columns if they don't exist
        if 'Geom Path' not in self.plan_df.columns:
            self.plan_df['Geom Path'] = None
        if 'Flow Path' not in self.plan_df.columns:
            self.plan_df['Flow Path'] = None
        
        # Update paths for each plan entry
        for idx, row in self.plan_df.iterrows():
            try:
                # Set geometry path if Geom File exists and Geom Path is missing or invalid
                if pd.notna(row['Geom File']):
                    geom_path = self.project_folder / f"{self.project_name}.g{row['Geom File']}"
                    self.plan_df.at[idx, 'Geom Path'] = str(geom_path)
                
                # Set flow path if Flow File exists and Flow Path is missing or invalid
                if pd.notna(row['Flow File']):
                    # Determine the prefix (u for unsteady, f for steady flow)
                    prefix = 'u' if pd.notna(row['unsteady_number']) else 'f'
                    flow_path = self.project_folder / f"{self.project_name}.{prefix}{row['Flow File']}"
                    self.plan_df.at[idx, 'Flow Path'] = str(flow_path)
                
                if not self.suppress_logging:
                    logger.debug(f"Plan {row['plan_number']} paths set up")
            except Exception as e:
                logger.error(f"Error setting paths for plan {row.get('plan_number', idx)}: {e}")

    def _get_geom_file_for_plan(self, plan_number):
        """
        Get the geometry file path for a given plan number.
        
        Args:
            plan_number (str): The plan number to find the geometry file for.
        
        Returns:
            str: The full path to the geometry HDF file, or None if not found.
        """
        plan_file_path = self.project_folder / f"{self.project_name}.p{plan_number}"
        content, encoding = read_file_with_fallback_encoding(plan_file_path)
        
        if content is None:
            return None
        
        try:
            for line in content.splitlines():
                if line.startswith("Geom File="):
                    geom_file = line.strip().split('=')[1]
                    geom_hdf_path = self.project_folder / f"{self.project_name}.{geom_file}.hdf"
                    if geom_hdf_path.exists():
                        return str(geom_hdf_path)
                    else:
                        return None
        except Exception as e:
            logger.error(f"Error reading plan file for geometry: {e}")
        return None


    @staticmethod
    @log_call
    def get_plan_value(
        plan_number_or_path: Union[str, Path],
        key: str,
        ras_object=None
    ) -> Any:
        """
        Retrieve a specific value from a HEC-RAS plan file.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        key (str): The key to retrieve from the plan file
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Any: The value associated with the specified key

        Raises:
        ValueError: If the plan file is not found
        IOError: If there's an error reading the plan file
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # These must exactly match the keys in supported_plan_keys from _parse_plan_file
        valid_keys = {
            'Computation Interval',
            'DSS File',
            'Flow File',
            'Friction Slope Method',
            'Geom File',
            'Mapping Interval',
            'Plan Title',
            'Program Version',
            'Run HTab',
            'Run PostProcess',
            'Run Sediment',
            'Run UNet',
            'Run WQNet',
            'Short Identifier',
            'Simulation Date',
            'UNET D1 Cores',
            'UNET D2 Cores',
            'PS Cores',
            'UNET Use Existing IB Tables',
            'UNET 1D Methodology',
            'UNET D2 SolverType',
            'UNET D2 Name',
            'description'  # Special case for description block
        }

        if key not in valid_keys:
            logger.warning(f"Unknown key: {key}. Valid keys are: {', '.join(sorted(valid_keys))}")
            return None

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasUtils.get_plan_path(plan_number_or_path, ras_object)
            if not plan_file_path.exists():
                logger.error(f"Plan file not found: {plan_file_path}")
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r') as file:
                content = file.read()
        except IOError as e:
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        if key == 'description':
            match = re.search(r'Begin DESCRIPTION(.*?)END DESCRIPTION', content, re.DOTALL)
            return match.group(1).strip() if match else None
        else:
            pattern = f"{key}=(.*)"
            match = re.search(pattern, content)
            if match:
                value = match.group(1).strip()
                # Convert core values to integers
                if key in ['UNET D1 Cores', 'UNET D2 Cores', 'PS Cores']:
                    try:
                        return int(value)
                    except ValueError:
                        logger.warning(f"Could not convert {key} value '{value}' to integer")
                        return None
                return value
            
            # Use DEBUG level for missing core values, ERROR for other missing keys
            if key in ['UNET D1 Cores', 'UNET D2 Cores', 'PS Cores']:
                logger.debug(f"Core setting '{key}' not found in plan file")
            else:
                logger.error(f"Key '{key}' not found in the plan file")
            return None

    def _parse_plan_file(self, plan_file_path):
        """
        Parse a plan file and extract critical information.
        
        Args:
            plan_file_path (Path): Path to the plan file.
        
        Returns:
            dict: Dictionary containing extracted plan information.
        """
        plan_info = {}
        content, encoding = read_file_with_fallback_encoding(plan_file_path)
        
        if content is None:
            logger.error(f"Could not read plan file {plan_file_path} with any supported encoding")
            return plan_info
        
        try:
            # Extract description
            description_match = re.search(r'Begin DESCRIPTION(.*?)END DESCRIPTION', content, re.DOTALL)
            if description_match:
                plan_info['description'] = description_match.group(1).strip()
            
            # BEGIN Exception to Style Guide, this is needed to keep the key names consistent with the plan file keys.
            
            # Extract other critical information
            supported_plan_keys = {
                'Computation Interval': r'Computation Interval=(.+)',
                'DSS File': r'DSS File=(.+)',
                'Flow File': r'Flow File=(.+)',
                'Friction Slope Method': r'Friction Slope Method=(.+)',
                'Geom File': r'Geom File=(.+)',
                'Mapping Interval': r'Mapping Interval=(.+)',
                'Plan Title': r'Plan Title=(.+)',
                'Program Version': r'Program Version=(.+)',
                'Run HTab': r'Run HTab=(.+)',
                'Run PostProcess': r'Run PostProcess=(.+)',
                'Run Sediment': r'Run Sediment=(.+)',
                'Run UNet': r'Run UNet=(.+)',
                'Run WQNet': r'Run WQNet=(.+)',
                'Short Identifier': r'Short Identifier=(.+)',
                'Simulation Date': r'Simulation Date=(.+)',
                'UNET D1 Cores': r'UNET D1 Cores=(.+)',
                'UNET D2 Cores': r'UNET D2 Cores=(.+)',
                'PS Cores': r'PS Cores=(.+)',
                'UNET Use Existing IB Tables': r'UNET Use Existing IB Tables=(.+)',
                'UNET 1D Methodology': r'UNET 1D Methodology=(.+)',
                'UNET D2 SolverType': r'UNET D2 SolverType=(.+)',
                'UNET D2 Name': r'UNET D2 Name=(.+)'
            }
            
            # END Exception to Style Guide
            
            # First, explicitly set None for core values
            core_keys = ['UNET D1 Cores', 'UNET D2 Cores', 'PS Cores']
            for key in core_keys:
                plan_info[key] = None
            
            for key, pattern in supported_plan_keys.items():
                match = re.search(pattern, content)
                if match:
                    value = match.group(1).strip()
                    # Convert core values to integers if they exist
                    if key in core_keys and value:
                        try:
                            value = int(value)
                        except ValueError:
                            logger.warning(f"Could not convert {key} value '{value}' to integer in plan file {plan_file_path}")
                            value = None
                    plan_info[key] = value
                elif key in core_keys:
                    logger.debug(f"Core setting '{key}' not found in plan file {plan_file_path}")
            
            logger.debug(f"Parsed plan file: {plan_file_path} using {encoding} encoding")
        except Exception as e:
            logger.error(f"Error parsing plan file {plan_file_path}: {e}")
        
        return plan_info

    @log_call
    def _get_prj_entries(self, entry_type):
        """
        Extract entries of a specific type from the HEC-RAS project file.
        
        Args:
            entry_type (str): The type of entry to extract (e.g., 'Plan', 'Flow', 'Unsteady', 'Geom').
        
        Returns:
            pd.DataFrame: A DataFrame containing the extracted entries.
        
        Raises:
            Exception: If there's an error reading or processing the project file.
        """
        entries = []
        pattern = re.compile(rf"{entry_type} File=(\w+)")

        try:
            with open(self.prj_file, 'r', encoding='utf-8') as file:
                for line in file:
                    match = pattern.match(line.strip())
                    if match:
                        file_name = match.group(1)
                        full_path = str(self.project_folder / f"{self.project_name}.{file_name}")
                        entry_number = file_name[1:]
                        
                        entry = {
                            f'{entry_type.lower()}_number': entry_number,
                            'full_path': full_path
                        }
                        
                        # Handle Unsteady entries
                        if entry_type == 'Unsteady':
                            entry.update(self._process_unsteady_entry(entry_number, full_path))
                        else:
                            entry.update(self._process_default_entry())
                        
                        # Handle Plan entries
                        if entry_type == 'Plan':
                            entry.update(self._process_plan_entry(entry_number, full_path))
                        
                        entries.append(entry)
            
            df = pd.DataFrame(entries)
            return self._format_dataframe(df, entry_type)
        
        except Exception as e:
            logger.error(f"Error in _get_prj_entries for {entry_type}: {e}")
            raise

    def _process_unsteady_entry(self, entry_number: str, full_path: str) -> dict:
        """Process unsteady entry data."""
        entry = {'unsteady_number': entry_number}
        unsteady_info = self._parse_unsteady_file(Path(full_path))
        entry.update(unsteady_info)
        return entry

    def _process_default_entry(self) -> dict:
        """Process default entry data."""
        return {
            'unsteady_number': None,
            'geometry_number': None
        }

    def _process_plan_entry(self, entry_number: str, full_path: str) -> dict:
        """Process plan entry data."""
        entry = {}
        plan_info = self._parse_plan_file(Path(full_path))
        
        if plan_info:
            entry.update(self._process_flow_file(plan_info))
            entry.update(self._process_geom_file(plan_info))
            
            # Add remaining plan info
            for key, value in plan_info.items():
                if key not in ['Flow File', 'Geom File']:
                    entry[key] = value
            
            # Add HDF results path
            hdf_results_path = self.project_folder / f"{self.project_name}.p{entry_number}.hdf"
            entry['HDF_Results_Path'] = str(hdf_results_path) if hdf_results_path.exists() else None
        
        return entry

    def _process_flow_file(self, plan_info: dict) -> dict:
        """Process flow file information from plan info."""
        flow_file = plan_info.get('Flow File')
        if flow_file and flow_file.startswith('u'):
            return {
                'unsteady_number': flow_file[1:],
                'Flow File': flow_file[1:]
            }
        return {
            'unsteady_number': None,
            'Flow File': flow_file[1:] if flow_file and flow_file.startswith('f') else None
        }

    def _process_geom_file(self, plan_info: dict) -> dict:
        """Process geometry file information from plan info."""
        geom_file = plan_info.get('Geom File')
        if geom_file and geom_file.startswith('g'):
            return {
                'geometry_number': geom_file[1:],
                'Geom File': geom_file[1:]
            }
        return {
            'geometry_number': None,
            'Geom File': None
        }

    def _parse_unsteady_file(self, unsteady_file_path):
        """
        Parse an unsteady flow file and extract critical information.
        
        Args:
            unsteady_file_path (Path): Path to the unsteady flow file.
        
        Returns:
            dict: Dictionary containing extracted unsteady flow information.
        """
        unsteady_info = {}
        content, encoding = read_file_with_fallback_encoding(unsteady_file_path)
        
        if content is None:
            return unsteady_info
        
        try:
            # BEGIN Exception to Style Guide, this is needed to keep the key names consistent with the unsteady file keys.
            
            supported_unsteady_keys = {
                'Flow Title': r'Flow Title=(.+)',
                'Program Version': r'Program Version=(.+)',
                'Use Restart': r'Use Restart=(.+)',
                'Precipitation Mode': r'Precipitation Mode=(.+)',
                'Wind Mode': r'Wind Mode=(.+)',
                'Met BC=Precipitation|Mode': r'Met BC=Precipitation\|Mode=(.+)',
                'Met BC=Evapotranspiration|Mode': r'Met BC=Evapotranspiration\|Mode=(.+)',
                'Met BC=Precipitation|Expanded View': r'Met BC=Precipitation\|Expanded View=(.+)',
                'Met BC=Precipitation|Constant Units': r'Met BC=Precipitation\|Constant Units=(.+)',
                'Met BC=Precipitation|Gridded Source': r'Met BC=Precipitation\|Gridded Source=(.+)'
            }
            
            # END Exception to Style Guide
            
            for key, pattern in supported_unsteady_keys.items():
                match = re.search(pattern, content)
                if match:
                    unsteady_info[key] = match.group(1).strip()
        
        except Exception as e:
            logger.error(f"Error parsing unsteady file {unsteady_file_path}: {e}")
        
        return unsteady_info

    @property
    def is_initialized(self):
        """
        Check if the RasPrj instance has been initialized.

        Returns:
            bool: True if the instance has been initialized, False otherwise.
        """
        return self.initialized

    @log_call
    def check_initialized(self):
        """
        Ensure that the RasPrj instance has been initialized.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        if not self.initialized:
            raise RuntimeError("Project not initialized. Call init_ras_project() first.")

    @staticmethod
    @log_call
    def find_ras_prj(folder_path):
        """
        Find the appropriate HEC-RAS project file (.prj) in the given folder.
        
        Parameters:
        folder_path (str or Path): Path to the folder containing HEC-RAS files.
        
        Returns:
        Path: The full path of the selected .prj file or None if no suitable file is found.
        """
        folder_path = Path(folder_path)
        prj_files = list(folder_path.glob("*.prj"))
        rasmap_files = list(folder_path.glob("*.rasmap"))
        if len(prj_files) == 1:
            return prj_files[0].resolve()
        if len(prj_files) > 1:
            if len(rasmap_files) == 1:
                base_filename = rasmap_files[0].stem
                prj_file = folder_path / f"{base_filename}.prj"
                if prj_file.exists():
                    return prj_file.resolve()
            for prj_file in prj_files:
                try:
                    with open(prj_file, 'r') as file:
                        content = file.read()
                        if "Proj Title=" in content:
                            return prj_file.resolve()
                except Exception:
                    continue
        return None


    @log_call
    def get_project_name(self):
        """
        Get the name of the HEC-RAS project.

        Returns:
            str: The name of the project.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self.project_name

    @log_call
    def get_prj_entries(self, entry_type):
        """
        Get entries of a specific type from the HEC-RAS project.

        Args:
            entry_type (str): The type of entry to retrieve (e.g., 'Plan', 'Flow', 'Unsteady', 'Geom').

        Returns:
            pd.DataFrame: A DataFrame containing the requested entries.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self._get_prj_entries(entry_type)

    @log_call
    def get_plan_entries(self):
        """
        Get all plan entries from the HEC-RAS project.

        Returns:
            pd.DataFrame: A DataFrame containing all plan entries.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self._get_prj_entries('Plan')

    @log_call
    def get_flow_entries(self):
        """
        Get all flow entries from the HEC-RAS project.

        Returns:
            pd.DataFrame: A DataFrame containing all flow entries.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self._get_prj_entries('Flow')

    @log_call
    def get_unsteady_entries(self):
        """
        Get all unsteady flow entries from the HEC-RAS project.

        Returns:
            pd.DataFrame: A DataFrame containing all unsteady flow entries.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self._get_prj_entries('Unsteady')

    @log_call
    def get_geom_entries(self):
        """
        Get geometry entries from the project file.

        Returns:
            pd.DataFrame: DataFrame containing geometry entries.
        """
        geom_pattern = re.compile(r'Geom File=(\w+)')
        geom_entries = []

        try:
            with open(self.prj_file, 'r') as f:
                for line in f:
                    match = geom_pattern.search(line)
                    if match:
                        geom_entries.append(match.group(1))
        
            geom_df = pd.DataFrame({'geom_file': geom_entries})
            geom_df['geom_number'] = geom_df['geom_file'].str.extract(r'(\d+)$')
            geom_df['full_path'] = geom_df['geom_file'].apply(lambda x: str(self.project_folder / f"{self.project_name}.{x}"))
            geom_df['hdf_path'] = geom_df['full_path'] + ".hdf"
            
            if not self.suppress_logging:  # Only log if suppress_logging is False
                logger.info(f"Found {len(geom_df)} geometry entries")
            return geom_df
        except Exception as e:
            logger.error(f"Error reading geometry entries from project file: {e}")
            raise
    
    @log_call
    def get_hdf_entries(self):
        """
        Get HDF entries for plans that have results.
        
        Returns:
            pd.DataFrame: A DataFrame containing plan entries with HDF results.
                      Returns an empty DataFrame if no HDF entries are found.
        """
        self.check_initialized()
        
        hdf_entries = self.plan_df[self.plan_df['HDF_Results_Path'].notna()].copy()
        
        if hdf_entries.empty:
            return pd.DataFrame(columns=self.plan_df.columns)
        
        return hdf_entries
    
    
    @log_call
    def print_data(self):
        """Print all RAS Object data for this instance."""
        self.check_initialized()
        logger.info(f"--- Data for {self.project_name} ---")
        logger.info(f"Project folder: {self.project_folder}")
        logger.info(f"PRJ file: {self.prj_file}")
        logger.info(f"HEC-RAS executable: {self.ras_exe_path}")
        logger.info("Plan files:")
        logger.info(f"\n{self.plan_df}")
        logger.info("Flow files:")
        logger.info(f"\n{self.flow_df}")
        logger.info("Unsteady flow files:")
        logger.info(f"\n{self.unsteady_df}")
        logger.info("Geometry files:")
        logger.info(f"\n{self.geom_df}")
        logger.info("HDF entries:")
        logger.info(f"\n{self.get_hdf_entries()}")
        logger.info("Boundary conditions:")
        logger.info(f"\n{self.boundaries_df}")
        logger.info("----------------------------")

    @log_call
    def get_boundary_conditions(self) -> pd.DataFrame:
        """
        Extract boundary conditions from unsteady flow files and create a DataFrame.

        This method parses unsteady flow files to extract boundary condition information.
        It creates a DataFrame with structured data for known boundary condition types
        and parameters, and associates this information with the corresponding unsteady flow file.

        Note:
        Any lines in the boundary condition blocks that are not explicitly parsed and
        incorporated into the DataFrame are captured in a multi-line string. This string
        is logged at the DEBUG level for each boundary condition. This feature is crucial
        for developers incorporating new boundary condition types or parameters, as it
        allows them to see what information might be missing from the current parsing logic.
        If no unsteady flow files are present, it returns an empty DataFrame.

        Returns:
            pd.DataFrame: A DataFrame containing detailed boundary condition information,
                                      linked to the unsteady flow files.

        Usage:
            To see the unparsed lines, set the logging level to DEBUG before calling this method:
            
            import logging
            getLogger().setLevel(logging.DEBUG)
            
            boundaries_df = ras_project.get_boundary_conditions()
                          linked to the unsteady flow files. Returns an empty DataFrame if
                          no unsteady flow files are present.
        """
        boundary_data = []
        
        # Check if unsteady_df is empty
        if self.unsteady_df.empty:
            logger.info("No unsteady flow files found in the project.")
            return pd.DataFrame()  # Return an empty DataFrame
        
        for _, row in self.unsteady_df.iterrows():
            unsteady_file_path = row['full_path']
            unsteady_number = row['unsteady_number']
            
            try:
                with open(unsteady_file_path, 'r') as file:
                    content = file.read()
            except IOError as e:
                logger.error(f"Error reading unsteady file {unsteady_file_path}: {e}")
                continue
                
            bc_blocks = re.split(r'(?=Boundary Location=)', content)[1:]
            
            for i, block in enumerate(bc_blocks, 1):
                bc_info, unparsed_lines = self._parse_boundary_condition(block, unsteady_number, i)
                boundary_data.append(bc_info)
                
                if unparsed_lines:
                    logger.debug(f"Unparsed lines for boundary condition {i} in unsteady file {unsteady_number}:\n{unparsed_lines}")
        
        if not boundary_data:
            logger.info("No boundary conditions found in unsteady flow files.")
            return pd.DataFrame()  # Return an empty DataFrame if no boundary conditions were found
        
        boundaries_df = pd.DataFrame(boundary_data)
        
        # Merge with unsteady_df to get relevant unsteady flow file information
        merged_df = pd.merge(boundaries_df, self.unsteady_df, 
                             left_on='unsteady_number', right_on='unsteady_number', how='left')
        
        return merged_df

    def _parse_boundary_condition(self, block: str, unsteady_number: str, bc_number: int) -> Tuple[Dict, str]:
        lines = block.split('\n')
        bc_info = {
            'unsteady_number': unsteady_number,
            'boundary_condition_number': bc_number
        }
        
        parsed_lines = set()
        
        # Parse Boundary Location
        boundary_location = lines[0].split('=')[1].strip()
        fields = [field.strip() for field in boundary_location.split(',')]
        bc_info.update({
            'river_reach_name': fields[0] if len(fields) > 0 else '',
            'river_station': fields[1] if len(fields) > 1 else '',
            'storage_area_name': fields[2] if len(fields) > 2 else '',
            'pump_station_name': fields[3] if len(fields) > 3 else ''
        })
        parsed_lines.add(0)
        
        # Determine BC Type
        bc_types = {
            'Flow Hydrograph=': 'Flow Hydrograph',
            'Lateral Inflow Hydrograph=': 'Lateral Inflow Hydrograph',
            'Uniform Lateral Inflow Hydrograph=': 'Uniform Lateral Inflow Hydrograph',
            'Stage Hydrograph=': 'Stage Hydrograph',
            'Friction Slope=': 'Normal Depth',
            'Gate Name=': 'Gate Opening'
        }
        
        bc_info['bc_type'] = 'Unknown'
        bc_info['hydrograph_type'] = None
        for i, line in enumerate(lines[1:], 1):
            for key, bc_type in bc_types.items():
                if line.startswith(key):
                    bc_info['bc_type'] = bc_type
                    if 'Hydrograph' in bc_type:
                        bc_info['hydrograph_type'] = bc_type
                    parsed_lines.add(i)
                    break
            if bc_info['bc_type'] != 'Unknown':
                break
        
        # Parse other fields
        known_fields = ['Interval', 'DSS Path', 'Use DSS', 'Use Fixed Start Time', 'Fixed Start Date/Time',
                        'Is Critical Boundary', 'Critical Boundary Flow', 'DSS File']
        for i, line in enumerate(lines):
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                if key in known_fields:
                    bc_info[key] = value.strip()
                    parsed_lines.add(i)
        
        # Handle hydrograph values
        bc_info['hydrograph_num_values'] = 0
        if bc_info['hydrograph_type']:
            hydrograph_key = f"{bc_info['hydrograph_type']}="
            hydrograph_line = next((line for i, line in enumerate(lines) if line.startswith(hydrograph_key)), None)
            if hydrograph_line:
                hydrograph_index = lines.index(hydrograph_line)
                values_count = int(hydrograph_line.split('=')[1].strip())
                bc_info['hydrograph_num_values'] = values_count
                if values_count > 0:
                    values = ' '.join(lines[hydrograph_index + 1:]).split()[:values_count]
                    bc_info['hydrograph_values'] = values
                    parsed_lines.update(range(hydrograph_index, hydrograph_index + (values_count // 5) + 2))
        
        # Collect unparsed lines
        unparsed_lines = '\n'.join(line for i, line in enumerate(lines) if i not in parsed_lines and line.strip())
        
        if unparsed_lines:
            logger.debug(f"Unparsed lines for boundary condition {bc_number} in unsteady file {unsteady_number}:\n{unparsed_lines}")
        
        return bc_info, unparsed_lines

    @log_call
    def _format_dataframe(self, df, entry_type):
        """
        Format the DataFrame according to the desired column structure.
        
        Args:
            df (pd.DataFrame): The DataFrame to format.
            entry_type (str): The type of entry (e.g., 'Plan', 'Flow', 'Unsteady', 'Geom').
        
        Returns:
            pd.DataFrame: The formatted DataFrame.
        """
        if df.empty:
            return df
        
        if entry_type == 'Plan':
            # Set required column order
            first_cols = ['plan_number', 'unsteady_number', 'geometry_number']
            
            # Standard plan key columns in the exact order specified
            plan_key_cols = [
                'Plan Title', 'Program Version', 'Short Identifier', 'Simulation Date',
                'Std Step Tol', 'Computation Interval', 'Output Interval', 'Instantaneous Interval',
                'Mapping Interval', 'Run HTab', 'Run UNet', 'Run Sediment', 'Run PostProcess',
                'Run WQNet', 'Run RASMapper', 'UNET Use Existing IB Tables', 'HDF_Results_Path',
                'UNET 1D Methodology', 'Write IC File', 'Write IC File at Fixed DateTime',
                'IC Time', 'Write IC File Reoccurance', 'Write IC File at Sim End'
            ]
            
            # Additional convenience columns
            file_path_cols = ['Geom File', 'Geom Path', 'Flow File', 'Flow Path']
            
            # Special columns that must be preserved
            special_cols = ['HDF_Results_Path']
            
            # Build the final column list
            all_cols = first_cols.copy()
            
            # Add plan key columns if they exist
            for col in plan_key_cols:
                if col in df.columns and col not in all_cols and col not in special_cols:
                    all_cols.append(col)
            
            # Add any remaining columns not explicitly specified
            other_cols = [col for col in df.columns if col not in all_cols + file_path_cols + special_cols + ['full_path']]
            all_cols.extend(other_cols)
            
            # Add HDF_Results_Path if it exists (ensure it comes before file paths)
            for special_col in special_cols:
                if special_col in df.columns and special_col not in all_cols:
                    all_cols.append(special_col)
            
            # Add file path columns at the end
            all_cols.extend(file_path_cols)
            
            # Rename plan_number column
            df = df.rename(columns={f'{entry_type.lower()}_number': 'plan_number'})
            
            # Fill in missing columns with None
            for col in all_cols:
                if col not in df.columns:
                    df[col] = None
            
            # Make sure full_path column is preserved and included
            if 'full_path' in df.columns and 'full_path' not in all_cols:
                all_cols.append('full_path')
            
            # Return DataFrame with specified column order
            cols_to_return = [col for col in all_cols if col in df.columns]
            return df[cols_to_return]
        
        return df

    @log_call
    def _get_prj_entries(self, entry_type):
        """
        Extract entries of a specific type from the HEC-RAS project file.
        """
        entries = []
        pattern = re.compile(rf"{entry_type} File=(\w+)")

        try:
            with open(self.prj_file, 'r') as file:
                for line in file:
                    match = pattern.match(line.strip())
                    if match:
                        file_name = match.group(1)
                        full_path = str(self.project_folder / f"{self.project_name}.{file_name}")
                        entry = self._create_entry(entry_type, file_name, full_path)
                        entries.append(entry)
        
            return self._format_dataframe(pd.DataFrame(entries), entry_type)
        
        except Exception as e:
            logger.error(f"Error in _get_prj_entries for {entry_type}: {e}")
            raise

    def _create_entry(self, entry_type, file_name, full_path):
        """Helper method to create entry dictionary."""
        entry_number = file_name[1:]
        entry = {
            f'{entry_type.lower()}_number': entry_number,
            'full_path': full_path,
            'unsteady_number': None,
            'geometry_number': None
        }
        
        if entry_type == 'Unsteady':
            entry['unsteady_number'] = entry_number
            entry.update(self._parse_unsteady_file(Path(full_path)))
        elif entry_type == 'Plan':
            self._update_plan_entry(entry, entry_number, full_path)
        
        return entry

    def _update_plan_entry(self, entry, entry_number, full_path):
        """Helper method to update plan entry with additional information."""
        plan_info = self._parse_plan_file(Path(full_path))
        if plan_info:
            # Handle Flow File
            flow_file = plan_info.get('Flow File')
            if flow_file:
                if flow_file.startswith('u'):
                    entry.update({'unsteady_number': flow_file[1:], 'Flow File': flow_file[1:]})
                else:
                    entry['Flow File'] = flow_file[1:] if flow_file.startswith('f') else None
            
            # Handle Geom File
            geom_file = plan_info.get('Geom File')
            if geom_file and geom_file.startswith('g'):
                entry.update({'geometry_number': geom_file[1:], 'Geom File': geom_file[1:]})
            
            # Add remaining plan info
            entry.update({k: v for k, v in plan_info.items() if k not in ['Flow File', 'Geom File']})
            
            # Add HDF results path
            hdf_path = self.project_folder / f"{self.project_name}.p{entry_number}.hdf"
            entry['HDF_Results_Path'] = str(hdf_path) if hdf_path.exists() else None


# Create a global instance named 'ras'
# Defining the global instance allows the init_ras_project function to initialize the project.
# This only happens on the library initialization, not when the user calls init_ras_project.
ras = RasPrj()

# END OF CLASS DEFINITION


# START OF FUNCTION DEFINITIONS

@log_call
def init_ras_project(ras_project_folder, ras_version=None, ras_object=None):
    """
    Initialize a RAS project.

    USE THIS FUNCTION TO INITIALIZE A RAS PROJECT, NOT THE INITIALIZE METHOD OF THE RasPrj CLASS.

    Parameters:
    -----------
    ras_project_folder : str
        The path to the RAS project folder.
    ras_version : str, optional
        The version of RAS to use (e.g., "6.6").
        The version can also be a full path to the Ras.exe file.
        If None, the function will attempt to use the version from the global 'ras' object or a default path.
    ras_object : RasPrj or str, optional
        If None, the global 'ras' object is updated.
        If a RasPrj instance, that instance is updated.
        If any other value is provided, a new RasPrj instance is created and returned.

    Returns:
    --------
    RasPrj
        An initialized RasPrj instance.
    """
    if not Path(ras_project_folder).exists():
        logger.error(f"The specified RAS project folder does not exist: {ras_project_folder}")
        raise FileNotFoundError(f"The specified RAS project folder does not exist: {ras_project_folder}. Please check the path and try again.")

    ras_exe_path = get_ras_exe(ras_version)

    # Determine which RasPrj instance to use
    if ras_object is None:
        # Use the global 'ras' object
        logger.info("Initializing global 'ras' object via init_ras_project function.")
        ras_object = ras
    elif not isinstance(ras_object, RasPrj):
        # Create a new RasPrj instance
        logger.info("Creating a new RasPrj instance.")
        ras_object = RasPrj()

    # Initialize the RasPrj instance
    ras_object.initialize(ras_project_folder, ras_exe_path)
    
    # Always update the global ras object as well
    if ras_object is not ras:
        ras.initialize(ras_project_folder, ras_exe_path)
        logger.info("Global 'ras' object also updated to match the new project.")
    
    logger.info(f"Project initialized. ras_object project folder: {ras_object.project_folder}")
    return ras_object

@log_call
def get_ras_exe(ras_version=None):
    """
    Determine the HEC-RAS executable path based on the input.
    
    Args:
        ras_version (str, optional): Either a version number or a full path to the HEC-RAS executable.
                                     If None, the function will first check the global 'ras' object for a path.
                                     or a default path.
    
    Returns:
        str: The full path to the HEC-RAS executable.
    
    Raises:
        ValueError: If the input is neither a valid version number nor a valid file path.
    
    Notes:
        - If ras_version is not provided, the function will first check the global 'ras' object for a path.
        - If the global 'ras' object is not initialized or doesn't have a path, a default path will be used.
        - The default path allows the library to function in environments without HEC-RAS installed.
        - This enables the HEC-Commander GPT to operate without stopping, even if HEC-RAS is not present.
        - End users MUST use logging to check for operational errors, as full code stops prevent the GPT from running.
    """
    if ras_version is None:
        if hasattr(ras, 'ras_exe_path') and ras.ras_exe_path:
            logger.debug(f"Using HEC-RAS executable from global 'ras' object: {ras.ras_exe_path}")
            return ras.ras_exe_path
        else:
            default_path = Path("Ras.exe")
            logger.warning(f"No HEC-RAS version specified and global 'ras' object not initialized or missing ras_exe_path. Using default path: {default_path}. The RAS Commander (ras-commander) Library Assistant can ignore this error since it does not have HEC-RAS installed.")
            return str(default_path)
    
    ras_version_numbers = [
        "6.6", "6.5", "6.4.1", "6.3.1", "6.3", "6.2", "6.1", "6.0",
        "5.0.7", "5.0.6", "5.0.5", "5.0.4", "5.0.3", "5.0.1", "5.0",
        "4.1", "4.0", "3.1.3", "3.1.2", "3.1.1", "3.0", "2.2"
    ]
    
    hecras_path = Path(ras_version)
    
    if hecras_path.is_file() and hecras_path.suffix.lower() == '.exe':
        logger.debug(f"HEC-RAS executable found at specified path: {hecras_path}")
        return str(hecras_path)
    
    if ras_version in ras_version_numbers:
        default_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/Ras.exe")
        if default_path.is_file():
            logger.debug(f"HEC-RAS executable found at default path: {default_path}")
            return str(default_path)
        else:
            logger.critical(f"HEC-RAS executable not found at the expected path: {default_path}")
    
    try:
        version_float = float(ras_version)
        if version_float > max(float(v) for v in ras_version_numbers):
            newer_version_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/Ras.exe")
            if newer_version_path.is_file():
                logger.debug(f"Newer version of HEC-RAS executable found at: {newer_version_path}")
                return str(newer_version_path)
            else:
                logger.critical("Newer version of HEC-RAS was specified, but the executable was not found.")
    except ValueError:
        pass
    
    logger.error(f"Invalid HEC-RAS version or path: {ras_version}, returning default path: {default_path}")
    return str(default_path)
    
