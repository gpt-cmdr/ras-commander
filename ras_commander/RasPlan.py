"""
RasPlan - Operations for handling plan files in HEC-RAS projects

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

List of Functions in RasPlan:
- set_geom(): Set the geometry for a specified plan
- set_steady(): Apply a steady flow file to a plan file
- set_unsteady(): Apply an unsteady flow file to a plan file
- set_num_cores(): Update the maximum number of cores to use
- set_geom_preprocessor(): Update geometry preprocessor settings
- clone_plan(): Create a new plan file based on a template
- clone_unsteady(): Copy unsteady flow files from a template
- clone_steady(): Copy steady flow files from a template
- clone_geom(): Copy geometry files from a template
- get_next_number(): Determine the next available number from a list
- get_plan_value(): Retrieve a specific value from a plan file
- get_results_path(): Get the results file path for a plan
- get_plan_path(): Get the full path for a plan number
- get_flow_path(): Get the full path for a flow number
- get_unsteady_path(): Get the full path for an unsteady number
- get_geom_path(): Get the full path for a geometry number
- update_run_flags(): Update various run flags in a plan file
- update_plan_intervals(): Update computation and output intervals
- update_plan_description(): Update the description in a plan file
- read_plan_description(): Read the description from a plan file
- read_geom_description(): Read the description from a geometry file
- update_geom_description(): Update the description in a geometry file
- read_flow_description(): Read the description from a steady flow file
- update_flow_description(): Update the description in a steady flow file
- update_simulation_date(): Update simulation start and end dates
- get_restart_output_settings(): Parse restart/Hot Start output settings
- set_restart_output_settings(): Configure restart/Hot Start output settings
- get_shortid(): Get the Short Identifier from a plan file
- set_shortid(): Set the Short Identifier in a plan file
- get_plan_title(): Get the Plan Title from a plan file
- set_plan_title(): Set the Plan Title in a plan file
- delete_plan(): Delete a plan and its associated files
- renumber_plan(): Renumber a plan file and update references
- delete_geom(): Delete a geometry file and its associated files
- renumber_geom(): Renumber a geometry file and update references
- delete_unsteady(): Delete an unsteady flow file
- renumber_unsteady(): Renumber an unsteady flow file and update references
- delete_steady(): Delete a steady flow file
- renumber_steady(): Renumber a steady flow file and update references


        
"""
import os
import re
import logging
from pathlib import Path
import shutil
from typing import Union, Optional, List, Dict, Any, Tuple
from numbers import Number
import pandas as pd
from .RasPrj import RasPrj, ras
from .RasUtils import RasUtils
from pathlib import Path
from datetime import datetime

import logging
import re
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

class RasPlan:
    """
    A class for operations on HEC-RAS plan files.
    """

    HDF_WRITE_PARAMETER_KEYS = {
        "write_warmup": "HDF Write Warmup",
        "write_time_slices": "HDF Write Time Slices",
        "hdf_flush": "HDF Flush",
        "compression": "HDF Compression",
        "chunk_size_mb": "HDF Chunk Size",
        "spatial_parts": "HDF Spatial Parts",
        "use_max_rows": "HDF Use Max Rows",
        "fixed_rows": "HDF Fixed Rows",
    }

    HDF_OUTPUT_SETTING_PROFILES = {
        "balanced": {
            "write_warmup": True,
            "write_time_slices": False,
            "hdf_flush": False,
            "compression": 4,
            "chunk_size_mb": 4,
            "spatial_parts": 1,
            "use_max_rows": True,
            "fixed_rows": 1,
        },
        "speed": {
            "write_warmup": True,
            "write_time_slices": False,
            "hdf_flush": False,
            "compression": 1,
            "chunk_size_mb": 4,
            "spatial_parts": 1,
            "use_max_rows": True,
            "fixed_rows": 1,
        },
        "size": {
            "write_warmup": True,
            "write_time_slices": False,
            "hdf_flush": False,
            "compression": 6,
            "chunk_size_mb": 4,
            "spatial_parts": 1,
            "use_max_rows": True,
            "fixed_rows": 1,
        },
        "nas": {
            "write_warmup": True,
            "write_time_slices": False,
            "hdf_flush": False,
            "compression": 6,
            "chunk_size_mb": 2,
            "spatial_parts": 1,
            "use_max_rows": True,
            "fixed_rows": 1,
        },
    }

    TWO_D_EQUATION_SET_ALIASES = {
        "0": 0,
        "DWE": 0,
        "DW": 0,
        "DIFFUSION": 0,
        "DIFFUSION WAVE": 0,
        "DIFFUSION WAVE EQUATIONS": 0,
        "DIFFUSION WAVE EQUATION": 0,
        "1": 1,
        "SWE": 1,
        "SWE-ELM": 1,
        "SWE ELM": 1,
        "SHALLOW WATER": 1,
        "SHALLOW WATER EQUATIONS": 1,
        "SHALLOW WATER EQUATION": 1,
        "FULL MOMENTUM": 1,
    }

    TWO_D_EQUATION_CODE_TO_NAME = {
        0: "DWE",
        1: "SWE-ELM",
    }

    TWO_D_FLOW_AREA_OPTION_KEYS = {
        "theta": {"plan_key": "UNET D2 Theta", "type": "float", "min_version": 5.0},
        "theta_warmup": {"plan_key": "UNET D2 Theta Warmup", "type": "float", "min_version": 5.0},
        "water_surface_tolerance": {"plan_key": "UNET D2 Z Tol", "type": "float", "min_version": 5.0},
        "volume_tolerance": {"plan_key": "UNET D2 Volume Tol", "type": "float", "min_version": 5.0},
        "max_iterations": {"plan_key": "UNET D2 Max Iterations", "type": "int", "min_version": 5.0},
        "equation_set": {"plan_key": "UNET D2 Equation", "type": "equation", "min_version": 5.0},
        "initial_conditions_time_hours": {"plan_key": "UNET D2 TotalICTime", "type": "float", "min_version": 5.0},
        "ramp_up_fraction": {"plan_key": "UNET D2 RampUpFraction", "type": "float", "min_version": 5.0},
        "time_slices": {"plan_key": "UNET D2 TimeSlices", "type": "int", "min_version": 5.0},
        "eddy_viscosity": {"plan_key": "UNET D2 Eddy Viscosity", "type": "float", "min_version": 5.0},
        "transverse_eddy_viscosity": {"plan_key": "UNET D2 Transverse Eddy Viscosity", "type": "float", "min_version": 5.0},
        "smagorinsky_mixing": {"plan_key": "UNET D2 Smagorinsky Mixing", "type": "float", "min_version": 5.0},
        "boundary_condition_volume_check": {"plan_key": "UNET D2 BCVolumeCheck", "type": "bool", "min_version": 5.0},
        "latitude": {"plan_key": "UNET D2 Latitude", "type": "float", "min_version": 5.0},
        "cores": {"plan_key": "UNET D2 Cores", "type": "int", "min_version": 5.0},
        "solver_type": {"plan_key": "UNET D2 SolverType", "type": "str", "min_version": 5.0},
        "coriolis": {"plan_key": "UNET D2 Coriolis", "type": "bool", "min_version": 5.0},
    }

    TWO_D_FLOW_AREA_OPTION_ORDER = [
        "UNET D2 Name",
        "UNET D2 Coriolis",
        "UNET D2 Theta",
        "UNET D2 Theta Warmup",
        "UNET D2 Z Tol",
        "UNET D2 Volume Tol",
        "UNET D2 Max Iterations",
        "UNET D2 Equation",
        "UNET D2 TotalICTime",
        "UNET D2 RampUpFraction",
        "UNET D2 TimeSlices",
        "UNET D2 Eddy Viscosity",
        "UNET D2 Transverse Eddy Viscosity",
        "UNET D2 Smagorinsky Mixing",
        "UNET D2 BCVolumeCheck",
        "UNET D2 Latitude",
        "UNET D2 Cores",
        "UNET D2 SolverType",
    ]

    TWO_D_PLAN_OPTION_KEYS = {
        "computation_interval": {"plan_key": "Computation Interval", "type": "interval", "min_version": 5.0},
        "time_step_use_courant": {"plan_key": "Computation Time Step Use Courant", "type": "bool", "min_version": 5.0},
        "time_step_use_time_series": {"plan_key": "Computation Time Step Use Time Series", "type": "bool", "min_version": 5.0},
        "time_step_max_courant": {"plan_key": "Computation Time Step Max Courant", "type": "float", "min_version": 5.0},
        "time_step_min_courant": {"plan_key": "Computation Time Step Min Courant", "type": "float", "min_version": 5.0},
        "time_step_count_to_double": {"plan_key": "Computation Time Step Count To Double", "type": "int", "min_version": 5.0},
        "time_step_max_doubling": {"plan_key": "Computation Time Step Max Doubling", "type": "int", "min_version": 5.0},
        "time_step_max_halving": {"plan_key": "Computation Time Step Max Halving", "type": "int", "min_version": 5.0},
        "time_step_residence_courant": {"plan_key": "Computation Time Step Residence Courant", "type": "bool", "min_version": 5.0},
    }

    VALID_PLAN_INTERVALS = [
        '1SEC', '2SEC', '3SEC', '4SEC', '5SEC', '6SEC', '10SEC', '15SEC', '20SEC', '30SEC',
        '1MIN', '2MIN', '3MIN', '4MIN', '5MIN', '6MIN', '10MIN', '15MIN', '20MIN', '30MIN',
        '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'
    ]

    HDF_ADDITIONAL_OUTPUT_VARIABLES = [
        "Cell Cumulative Excess Depth",
        "Cell Cumulative Infiltration Depth",
        "Cell Cumulative Percolation Depth",
        "Cell Cumulative Precipitation Depth",
        "Cell Eddy Viscosity",
        "Cell Cumulative Evapotranspiration Depth",
        "Cell Evapotranspiration Potential Rate",
        "Cell Evapotranspiration Rate",
        "Cell Excess Rate",
        "Cell Flow Balance (inflows - outflows)",
        "Cell Hydraulic Depth",
        "Cell Infiltration Rate",
        "Cell Invert Depth (WSE - Cell Min Elev)",
        "Cell Percolation Rate",
        "Cell Potential Infiltration Rate",
        "Cell Precipitation Rate",
        "Cell Saturated Wetting Front Depth",
        "Cell Soil Moisture Deficit",
        "Cell Unsaturated Water Content",
        "Cell Unsaturated Wetting Front Depth",
        "Cell Velocity",
        "Cell Volume",
        "Cell Volume Error",
        "Cell Water Surface Error",
        "Cell Courant",
        "Face Courant",
        "Face Manning's n",
        "Face Air Density",
        "Face Dispersive Stress",
        "Face Eddy Viscosity",
        "Face Flow",
        "Face Period-Average Flow",
        "Face Cumulative Volume",
        "Face Area",
        "Face Mixture Dynamic Viscosity",
        "Face Point (Node) Velocities*",
        "Face Shear Stress",
        "Face Tangential Velocity (Both sides of each face)",
        "Face Viscous Stress",
        "Face Water Surface",
        "Face Wind Shear Stress",
        "Face Wind Velocity",
        "Face Yield Stress",
        "Governing Equation Terms",
    ]

    RESTART_OUTPUT_PARAMETER_KEYS = {
        "enabled": "Write IC File",
        "save_at_fixed_datetime": "Write IC File at Fixed DateTime",
        "save_time": "IC Time",
        "recurrence_interval_hours": "Write IC File Reoccurance",
        "write_at_sim_end": "Write IC File at Sim End",
    }

    RESTART_OUTPUT_FILE_PATTERN = "ProjectName.p##.DDMMMYYYY hhmm.rst"

    RESTART_OUTPUT_COMPATIBILITY_NOTE = (
        "HEC-RAS labels restart output as Initial Conditions or Hot Start files. "
        "In HEC-RAS 5.x through 7.0 these output-save settings are stored in the "
        "plan file using Write IC File keys. Restart-file usage remains separate "
        "in the unsteady-flow file as Use Restart and Restart Filename."
    )
    
    @staticmethod
    @log_call
    def set_geom(plan_number: Union[str, Number], new_geom: Union[str, Number], ras_object=None) -> pd.DataFrame:
        """
        Set the geometry for the specified plan by updating only the plan file.

        Parameters:
            plan_number (Union[str, Number]): The plan number to update (accepts int, float, numpy types, etc.).
            new_geom (Union[str, Number]): The new geometry number to set (accepts int, float, numpy types, etc.).
            ras_object: An optional RAS object instance.

        Returns:
            pd.DataFrame: The updated geometry DataFrame.

        Example:
            updated_geom_df = RasPlan.set_geom('02', '03')

        Note:
            This function updates the Geom File= line in the plan file and 
            updates the ras object's dataframes without modifying the PRJ file.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan and geometry numbers to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)
        new_geom = RasUtils.normalize_ras_number(new_geom)

        # Update all dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        
        if new_geom not in ras_obj.geom_df['geom_number'].values:
            logger.error(f"Geometry {new_geom} not found in project.")
            raise ValueError(f"Geometry {new_geom} not found in project.")

        # Get the plan file path
        plan_file_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
        if not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_file_path}")
            raise ValueError(f"Plan file not found: {plan_file_path}")
        
        # Read the plan file and update the Geom File line
        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            
            for i, line in enumerate(lines):
                if line.startswith("Geom File="):
                    lines[i] = f"Geom File=g{new_geom}\n"
                    logger.debug(
                        "Updated Geom File in plan file %s to g%s",
                        plan_file_path.name,
                        new_geom,
                    )
                    break
                
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)
        except Exception as e:
            logger.error(f"Error updating plan file: {e}")
            raise
        # Update the plan_df without reinitializing
        mask = ras_obj.plan_df['plan_number'] == plan_number
        ras_obj.plan_df.loc[mask, 'geom_number'] = new_geom
        ras_obj.plan_df.loc[mask, 'geometry_number'] = new_geom  # Update geometry_number column
        ras_obj.plan_df.loc[mask, 'Geom File'] = f"g{new_geom}"
        geom_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{new_geom}"
        ras_obj.plan_df.loc[mask, 'Geom Path'] = str(geom_path)

        logger.info("Set geometry for plan p%s to g%s", plan_number, new_geom)
        logger.debug("Updated plan DataFrame:")
        logger.debug(ras_obj.plan_df)

        return ras_obj.plan_df

    @staticmethod
    @log_call
    def set_steady(plan_number: Union[str, Number], new_steady_flow_number: Union[str, Number], ras_object=None):
        """
        Apply a steady flow file to a plan file.

        Parameters:
        plan_number (Union[str, Number]): Plan number (e.g., '02', 2, or 2.0)
        new_steady_flow_number (Union[str, Number]): Steady flow number to apply (e.g., '01', 1, or 1.0)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Raises:
        ValueError: If the specified steady flow number is not found in the project file
        FileNotFoundError: If the specified plan file is not found

        Example:
        >>> RasPlan.set_steady('02', '01')

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan and flow numbers to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)
        new_steady_flow_number = RasUtils.normalize_ras_number(new_steady_flow_number)

        ras_obj.flow_df = ras_obj.get_flow_entries()

        if new_steady_flow_number not in ras_obj.flow_df['flow_number'].values:
            raise ValueError(f"Steady flow number {new_steady_flow_number} not found in project file.")
        
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        try:
            RasUtils.update_file(plan_file_path, RasPlan._update_steady_in_file, new_steady_flow_number)
            
            # Update all dataframes
            ras_obj.plan_df = ras_obj.get_plan_entries()
            
            # Update flow-related columns
            mask = ras_obj.plan_df['plan_number'] == plan_number
            flow_path = ras_obj.project_folder / f"{ras_obj.project_name}.f{new_steady_flow_number}"
            ras_obj.plan_df.loc[mask, 'Flow File'] = f"f{new_steady_flow_number}"
            ras_obj.plan_df.loc[mask, 'Flow Path'] = str(flow_path)
            ras_obj.plan_df.loc[mask, 'unsteady_number'] = None
            
            # Update remaining dataframes
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            
        except Exception as e:
            raise IOError(f"Failed to update steady flow file: {e}")

    @staticmethod
    def _update_steady_in_file(lines, new_steady_flow_number):
        return [f"Flow File=f{new_steady_flow_number}\n" if line.startswith("Flow File=f") else line for line in lines]

    @staticmethod
    @log_call
    def set_unsteady(plan_number: Union[str, Number], new_unsteady_flow_number: Union[str, Number], ras_object=None):
        """
        Apply an unsteady flow file to a plan file.

        Parameters:
        plan_number (Union[str, Number]): Plan number (e.g., '04', 4, or 4.0)
        new_unsteady_flow_number (Union[str, Number]): Unsteady flow number to apply (e.g., '01', 1, or 1.0)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Raises:
        ValueError: If the specified unsteady number is not found in the project file
        FileNotFoundError: If the specified plan file is not found

        Example:
        >>> RasPlan.set_unsteady('04', '01')

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan and unsteady flow numbers to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)
        new_unsteady_flow_number = RasUtils.normalize_ras_number(new_unsteady_flow_number)

        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        if new_unsteady_flow_number not in ras_obj.unsteady_df['unsteady_number'].values:
            raise ValueError(f"Unsteady number {new_unsteady_flow_number} not found in project file.")
        
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        try:
            # Read the plan file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Update the Flow File line
            for i, line in enumerate(lines):
                if line.startswith("Flow File="):
                    lines[i] = f"Flow File=u{new_unsteady_flow_number}\n"
                    break
            
            # Write back to the plan file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as f:
                f.writelines(lines)
            
            # Update all dataframes
            ras_obj.plan_df = ras_obj.get_plan_entries()
            
            # Update flow-related columns
            mask = ras_obj.plan_df['plan_number'] == plan_number
            flow_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{new_unsteady_flow_number}"
            ras_obj.plan_df.loc[mask, 'Flow File'] = f"u{new_unsteady_flow_number}"
            ras_obj.plan_df.loc[mask, 'Flow Path'] = str(flow_path)
            ras_obj.plan_df.loc[mask, 'unsteady_number'] = new_unsteady_flow_number
            
            # Update remaining dataframes
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            
        except Exception as e:
            raise IOError(f"Failed to update unsteady flow file: {e}")

    @staticmethod
    def _update_unsteady_in_file(lines, new_unsteady_flow_number):
        return [f"Unsteady File=u{new_unsteady_flow_number}\n" if line.startswith("Unsteady File=u") else line for line in lines]
    
    @staticmethod
    @log_call
    def set_num_cores(plan_number: Union[str, Number], num_cores: int, ras_object=None):
        """
        Update the maximum number of cores to use in the HEC-RAS plan file.

        Parameters:
        plan_number (Union[str, Number]): Plan number (e.g., '02', 2, or 2.0) or full path to the plan file
        num_cores (int): Maximum number of cores to use
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Number of cores is controlled by the following parameters in the plan file corresponding to 1D, 2D, Pipe Systems and Pump Stations:
        UNET D1 Cores=  
        UNET D2 Cores=
        PS Cores=

        Where a value of "0" is used for "All Available" cores, and values of 1 or more are used to specify the number of cores to use.
        For complex 1D/2D models with pipe systems, a more complex approach may be needed to optimize performance.  (Suggest writing a custom function based on this code).
        This function simply sets the "num_cores" parameter for ALL instances of the above parameters in the plan file.


        Notes on setting num_cores in HEC-RAS:
        The recommended setting for num_cores is 2 (most efficient) to 8 (most performant)
        More details in the HEC-Commander Repository Blog "Benchmarking is All You Need"
        https://github.com/billk-FM/HEC-Commander/blob/main/Blog/7._Benchmarking_Is_All_You_Need.md
        
        Microsoft Windows has a maximum of 64 cores that can be allocated to a single Ras.exe process. 

        Example:
        >>> # Using plan number
        >>> RasPlan.set_num_cores('02', 4)
        >>> # Using full path to plan file
        >>> RasPlan.set_num_cores('/path/to/project.p02', 4)

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        plan_file_path = RasUtils.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            raise FileNotFoundError(f"Plan file not found: {plan_number}. Please provide a valid plan number or path.")
        
        def update_num_cores(lines):
            updated_lines = []
            for line in lines:
                if any(param in line for param in ["UNET D1 Cores=", "UNET D2 Cores=", "PS Cores="]):
                    param_name = line.split("=")[0]
                    updated_lines.append(f"{param_name}= {num_cores}\n")
                else:
                    updated_lines.append(line)
            return updated_lines
        
        try:
            RasUtils.update_file(plan_file_path, update_num_cores)
        except Exception as e:
            raise IOError(f"Failed to update number of cores in plan file: {e}")
        
        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def set_geom_preprocessor(file_path, run_htab, use_ib_tables, ras_object=None):
        """
        Update the simulation plan file to modify the `Run HTab` and `UNET Use Existing IB Tables` settings.
        
        Parameters:
        file_path (str): Path to the simulation plan file (.p06 or similar) that you want to modify.
        run_htab (int): Value for the `Run HTab` setting:
            - `0` : Do not run the geometry preprocessor, use existing geometry tables.
            - `-1` : Run the geometry preprocessor, forcing a recomputation of the geometry tables.
        use_ib_tables (int): Value for the `UNET Use Existing IB Tables` setting:
            - `0` : Use existing interpolation/boundary (IB) tables without recomputing them.
            - `-1` : Do not use existing IB tables, force a recomputation.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Raises:
        ValueError: If `run_htab` or `use_ib_tables` are not integers or not within the accepted values (`0` or `-1`).
        FileNotFoundError: If the specified file does not exist.
        IOError: If there is an error reading or writing the file.

        Example:
        >>> RasPlan.set_geom_preprocessor('/path/to/project.p06', run_htab=-1, use_ib_tables=0)

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        if run_htab not in [-1, 0]:
            raise ValueError("Invalid value for `Run HTab`. Expected `0` or `-1`.")
        if use_ib_tables not in [-1, 0]:
            raise ValueError("Invalid value for `UNET Use Existing IB Tables`. Expected `0` or `-1`.")
        
        def update_geom_preprocessor(lines, run_htab, use_ib_tables):
            updated_lines = []
            for line in lines:
                if line.lstrip().startswith("Run HTab="):
                    updated_lines.append(f"Run HTab= {run_htab} \n")
                elif line.lstrip().startswith("UNET Use Existing IB Tables="):
                    updated_lines.append(f"UNET Use Existing IB Tables= {use_ib_tables} \n")
                else:
                    updated_lines.append(line)
            return updated_lines
        
        try:
            RasUtils.update_file(file_path, update_geom_preprocessor, run_htab, use_ib_tables)
        except FileNotFoundError:
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")
        except IOError as e:
            raise IOError(f"An error occurred while reading or writing the file: {e}")

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    @log_call
    def get_results_path(plan_number: Union[str, Number], ras_object=None) -> Optional[Path]:
        """
        Retrieve the results file path for a given HEC-RAS plan number.

        Args:
            plan_number (Union[str, Number]): The HEC-RAS plan number for which to find the results path (e.g., '02', 2, or 2.0).
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            Optional[Path]: The full path to the results file if found and the file exists, or None if not found.

        Raises:
            RuntimeError: If the project is not initialized.

        Example:
            >>> ras_plan = RasPlan()
            >>> results_path = ras_plan.get_results_path('01')
            >>> if results_path:
            ...     print(f"Results file found at: {results_path}")
            ... else:
            ...     print("Results file not found.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Update the plan dataframe in the ras instance to ensure it is current
        ras_obj.plan_df = ras_obj.get_plan_entries()

        # Normalize plan number to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)
        
        plan_entry = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_number]
        if not plan_entry.empty:
            results_path = plan_entry['HDF_Results_Path'].iloc[0]
            if results_path and Path(results_path).exists():
                return Path(results_path)
            else:
                return None
        else:
            return None

    @staticmethod
    @log_call
    def get_plan_path(plan_number: Union[str, Number], ras_object=None) -> Optional[Path]:
        """
        Return the full path for a given plan number.

        This method ensures that the latest plan entries are included by refreshing
        the plan dataframe before searching for the requested plan number.

        Args:
        plan_number (Union[str, Number]): The plan number to search for (e.g., '01', 1, or 1.0).
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[Path]: The full path of the plan file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> plan_path = ras_plan.get_plan_path('01')
        >>> if plan_path:
        ...     print(f"Plan file found at: {plan_path}")
        ... else:
        ...     print("Plan file not found.")
        >>> # Integer input also works
        >>> plan_path = ras_plan.get_plan_path(1)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan number to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)
        
        plan_df = ras_obj.get_plan_entries()
        
        plan_path = plan_df[plan_df['plan_number'] == plan_number]

        if not plan_path.empty:
            if 'full_path' in plan_path.columns and not pd.isna(plan_path['full_path'].iloc[0]):
                return Path(plan_path['full_path'].iloc[0])
            else:
                # Fallback to constructing path
                return ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
        return None

    @staticmethod
    @log_call
    def get_flow_path(flow_number: Union[str, Number], ras_object=None) -> Optional[Path]:
        """
        Return the full path for a given flow number.

        Args:
        flow_number (Union[str, Number]): The flow number to search for (e.g., '01', 1, or 1.0).
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[Path]: The full path of the flow file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> flow_path = ras_plan.get_flow_path('01')
        >>> if flow_path:
        ...     print(f"Flow file found at: {flow_path}")
        ... else:
        ...     print("Flow file not found.")
        >>> # Integer input also works
        >>> flow_path = ras_plan.get_flow_path(1)
        """
        return RasPlan._get_component_path(
            component_number=flow_number,
            df_attr='flow_df',
            number_column='flow_number',
            prj_entry_type='Flow',
            file_prefix='f',
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def get_unsteady_path(unsteady_number: Union[str, Number], ras_object=None) -> Optional[Path]:
        """
        Return the full path for a given unsteady number.

        Args:
        unsteady_number (Union[str, Number]): The unsteady number to search for (e.g., '01', 1, or 1.0).
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[Path]: The full path of the unsteady file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> unsteady_path = ras_plan.get_unsteady_path('01')
        >>> if unsteady_path:
        ...     print(f"Unsteady file found at: {unsteady_path}")
        ... else:
        ...     print("Unsteady file not found.")
        >>> # Integer input also works
        >>> unsteady_path = ras_plan.get_unsteady_path(1)
        """
        return RasPlan._get_component_path(
            component_number=unsteady_number,
            df_attr='unsteady_df',
            number_column='unsteady_number',
            prj_entry_type='Unsteady',
            file_prefix='u',
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def get_geom_path(geom_number: Union[str, Number], ras_object=None) -> Optional[Path]:
        """
        Return the full path for a given geometry number.

        Args:
        geom_number (Union[str, Number]): The geometry number to search for (e.g., '01', 1, or 1.0).
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[Path]: The full path of the geometry file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> geom_path = ras_plan.get_geom_path('01')
        >>> if geom_path:
        ...     print(f"Geometry file found at: {geom_path}")
        ... else:
        ...     print("Geometry file not found.")
        >>> # Integer input also works
        >>> geom_path = ras_plan.get_geom_path(1)
        """
        _logger = get_logger(__name__)

        if geom_number is None:
            _logger.warning("Provided geometry number is None")
            return None

        try:
            result = RasPlan._get_component_path(
                component_number=geom_number,
                df_attr='geom_df',
                number_column='geom_number',
                prj_entry_type='Geom',
                file_prefix='g',
                ras_object=ras_object,
            )
            if result is not None:
                _logger.debug("Found geometry path: %s", result)
            else:
                _logger.warning(f"No geometry file found with number: {geom_number}")
            return result
        except Exception as e:
            _logger.error(f"Error in get_geom_path: {str(e)}")
            return None

    # Clone Functions to copy unsteady, flow, and geometry files from templates

    @staticmethod
    @log_call
    def clone_plan(
        template_plan: Union[str, Number],
        new_shortid=None,
        new_plan_shortid=None,
        new_title=None,
        geometry: Union[str, Number] = None,
        unsteady_flow: Union[str, Number] = None,
        steady_flow: Union[str, Number] = None,
        num_cores: int = None,
        intervals: Dict = None,
        run_flags: Dict = None,
        description: str = None,
        ras_object=None
    ) -> str:
        """
        Create a new plan file based on a template and optionally configure it.

        This function clones a plan file and can optionally configure multiple
        settings in one call, reducing the need for separate function calls.

        Parameters:
        template_plan (Union[str, Number]): Plan number to use as template (e.g., '01', 1, or 1.0)
        new_shortid (str, optional): New short identifier for the plan file (max 24 chars).
                                     If not provided, appends '_copy' to original.
                                     Alias: new_plan_shortid (for improved clarity)
        new_plan_shortid (str, optional): Alias for new_shortid. If both are provided,
                                          new_plan_shortid takes precedence.
        new_title (str, optional): New plan title (max 32 chars, updates "Plan Title=" line).
                                   If not provided, keeps original title.
        geometry (Union[str, Number], optional): Geometry file number to assign to the new plan.
        unsteady_flow (Union[str, Number], optional): Unsteady flow file number to assign.
        steady_flow (Union[str, Number], optional): Steady flow file number to assign.
        num_cores (int, optional): Number of compute cores to use.
        intervals (Dict, optional): Plan intervals to set. Keys can include:
            - 'computation' or 'computation_interval': e.g., '5SEC', '1MIN'
            - 'output' or 'output_interval': e.g., '15MIN', '1HOUR'
            - 'mapping' or 'mapping_interval': e.g., '1HOUR'
            - 'hydrograph' or 'hydrograph_output_interval': e.g., '15MIN'
        run_flags (Dict, optional): Run flags to set. Keys can include:
            - 'geometry_preprocessor': bool
            - 'unsteady_flow_simulation': bool
            - 'post_processor': bool
            - 'floodplain_mapping': bool
            - 'sediment': bool
            - 'water_quality': bool
        description (str, optional): Plan description text.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        str: New plan number

        Example:
        >>> # Simple clone (original behavior)
        >>> new_plan = RasPlan.clone_plan('01')
        >>>
        >>> # Clone with full configuration in one call
        >>> new_plan = RasPlan.clone_plan(
        ...     '01',
        ...     new_plan_shortid='Sensitivity_01',
        ...     geometry='01',
        ...     unsteady_flow='02',
        ...     num_cores=4,
        ...     intervals={'computation': '5SEC', 'output': '1MIN'},
        ...     run_flags={'geometry_preprocessor': True, 'unsteady_flow_simulation': True},
        ...     description='Sensitivity run with modified Manning\'s n'
        ... )

        Note:
            Both new_shortid and new_title are optional.
            new_plan_shortid is an alias for new_shortid for improved clarity.
            Configuration parameters are applied after the clone is created.
            This function updates the ras object's dataframes after modifying the project structure.
        """
        # Handle parameter aliasing: new_plan_shortid takes precedence if both provided
        if new_plan_shortid is not None:
            new_shortid = new_plan_shortid

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan number to two-digit format
        template_plan = RasUtils.normalize_ras_number(template_plan)

        # Validate new_title length if provided
        if new_title is not None and len(new_title) > 32:
            raise ValueError(
                f"Plan title must be 32 characters or less. "
                f"Got {len(new_title)} characters: '{new_title}'"
            )

        # Update plan entries without reinitializing the entire project
        ras_obj.plan_df = ras_obj.get_prj_entries('Plan')

        new_plan_num = RasPlan.get_next_number(ras_obj.plan_df['plan_number'])
        template_plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{template_plan}"
        new_plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{new_plan_num}"

        def update_plan_metadata(lines):
            """Update both Plan Title and Short Identifier"""
            title_pattern = re.compile(r'^Plan Title=(.*)$', re.IGNORECASE)
            shortid_pattern = re.compile(r'^Short Identifier=(.*)$', re.IGNORECASE)

            for i, line in enumerate(lines):
                # Update Plan Title if new_title provided
                title_match = title_pattern.match(line.strip())
                if title_match and new_title is not None:
                    lines[i] = f"Plan Title={new_title[:32]}\n"
                    continue

                # Update Short Identifier
                shortid_match = shortid_pattern.match(line.strip())
                if shortid_match:
                    current_shortid = shortid_match.group(1)
                    if new_shortid is None:
                        new_shortid_value = (current_shortid + "_copy")[:24]
                    else:
                        new_shortid_value = new_shortid[:24]
                    lines[i] = f"Short Identifier={new_shortid_value}\n"

            return lines

        # Use RasUtils to clone the file and update metadata
        RasUtils.clone_file(template_plan_path, new_plan_path, update_plan_metadata)

        # Use RasUtils to update the project file
        RasUtils.update_project_file(ras_obj.prj_file, 'Plan', new_plan_num, ras_object=ras_obj)

        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        # Apply optional configuration parameters
        if geometry is not None:
            RasPlan.set_geom(new_plan_num, geometry, ras_object=ras_obj)

        if unsteady_flow is not None:
            RasPlan.set_unsteady(new_plan_num, unsteady_flow, ras_object=ras_obj)

        if steady_flow is not None:
            RasPlan.set_steady(new_plan_num, steady_flow, ras_object=ras_obj)

        if num_cores is not None:
            RasPlan.set_num_cores(new_plan_num, num_cores, ras_object=ras_obj)

        if intervals is not None:
            # Map flexible keys to actual parameter names
            interval_kwargs = {}
            key_mapping = {
                'computation': 'computation_interval',
                'computation_interval': 'computation_interval',
                'output': 'output_interval',
                'output_interval': 'output_interval',
                'mapping': 'mapping_interval',
                'mapping_interval': 'mapping_interval',
                'hydrograph': 'hydrograph_output_interval',
                'hydrograph_output_interval': 'hydrograph_output_interval',
            }
            for key, value in intervals.items():
                mapped_key = key_mapping.get(key.lower().replace(' ', '_'))
                if mapped_key:
                    interval_kwargs[mapped_key] = value
            if interval_kwargs:
                RasPlan.update_plan_intervals(new_plan_num, ras_object=ras_obj, **interval_kwargs)

        if run_flags is not None:
            RasPlan.update_run_flags(new_plan_num, ras_object=ras_obj, **run_flags)

        if description is not None:
            RasPlan.update_plan_description(new_plan_num, description, ras_object=ras_obj)

        return new_plan_num

    @staticmethod
    @log_call
    def clone_unsteady(template_unsteady: Union[str, Number], new_title=None, ras_object=None):
        """
        Copy unsteady flow files from a template, find the next unsteady number,
        and update the project file accordingly.

        Parameters:
        template_unsteady (Union[str, Number]): Unsteady flow number to use as template (e.g., '01', 1, or 1.0)
        new_title (str, optional): New flow title (max 32 chars, updates "Flow Title=" line)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        str: New unsteady flow number (e.g., '03')

        Example:
        >>> # String input
        >>> new_unsteady_num = RasPlan.clone_unsteady('01',
        ...                                           new_title='Unsteady - HEC-RAS 4.1')
        >>> print(f"New unsteady flow file created: u{new_unsteady_num}")
        >>> # Integer input also works
        >>> new_unsteady_num = RasPlan.clone_unsteady(1)

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        return RasPlan._clone_component(
            template_number=template_unsteady,
            component_type='Unsteady',
            file_prefix='u',
            df_attr='unsteady_df',
            number_column='unsteady_number',
            new_title=new_title,
            title_keyword='Flow Title',
            copy_hdf=True,
            ras_object=ras_object,
        )


    @staticmethod
    @log_call
    def clone_steady(template_flow: Union[str, Number], new_title=None, ras_object=None):
        """
        Copy steady flow files from a template, find the next flow number,
        and update the project file accordingly.

        Parameters:
        template_flow (Union[str, Number]): Flow number to use as template (e.g., '01', 1, or 1.0)
        new_title (str, optional): New flow title (max 32 chars, updates "Flow Title=" line)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        str: New flow number (e.g., '03')

        Example:
        >>> # String input
        >>> new_flow_num = RasPlan.clone_steady('01',
        ...                                      new_title='Steady Flow - HEC-RAS 4.1')
        >>> print(f"New steady flow file created: f{new_flow_num}")
        >>> # Integer input also works
        >>> new_flow_num = RasPlan.clone_steady(1)

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        return RasPlan._clone_component(
            template_number=template_flow,
            component_type='Flow',
            file_prefix='f',
            df_attr='flow_df',
            number_column='flow_number',
            new_title=new_title,
            title_keyword='Flow Title',
            copy_hdf=False,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def clone_geom(template_geom: Union[str, Number], ras_object=None) -> str:
        """
        Copy geometry files from a template, find the next geometry number,
        and update the project file accordingly.

        .. deprecated::
            Use :meth:`RasGeo.clone_geom` instead, which supports
            ``new_title`` and ``description`` parameters.

        Parameters:
        template_geom (Union[str, Number]): Geometry number to use as template (e.g., '01', 1, or 1.0)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        str: New geometry number (e.g., '03')

        Example:
        >>> # String input
        >>> new_geom_num = RasPlan.clone_geom('01')
        >>> # Integer input also works
        >>> new_geom_num = RasPlan.clone_geom(1)

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        from .RasGeo import RasGeo
        return RasGeo.clone_geom(template_geom, ras_object=ras_object)

    @staticmethod
    @log_call
    def get_next_number(existing_numbers):
        """
        Determine the next available number from a list of existing numbers.
        
        Parameters:
        existing_numbers (list): List of existing numbers as strings
        
        Returns:
        str: Next available number as a zero-padded string
        
        Example:
        >>> existing_numbers = ['01', '02', '04']
        >>> RasPlan.get_next_number(existing_numbers)
        '03'
        >>> existing_numbers = ['01', '02', '03']
        >>> RasPlan.get_next_number(existing_numbers)
        '04'
        """
        existing_numbers = sorted(int(num) for num in existing_numbers)
        next_number = 1
        for num in existing_numbers:
            if num == next_number:
                next_number += 1
            else:
                break
        return f"{next_number:02d}"

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

        Available keys and their expected types:
        - 'Computation Interval' (str): Time value for computational time step (e.g., '5SEC', '2MIN')
        - 'DSS File' (str): Name of the DSS file used
        - 'Flow File' (str): Name of the flow input file
        - 'Friction Slope Method' (int): Method selection for friction slope (e.g., 1, 2)
        - 'Geom File' (str): Name of the geometry input file
        - 'Mapping Interval' (str): Time interval for mapping output
        - 'Plan File' (str): Name of the plan file
        - 'Plan Title' (str): Title of the simulation plan
        - 'Program Version' (str): Version number of HEC-RAS
        - 'Run HTab' (int): Flag to run HTab module (-1 or 1)
        - 'Run Post Process' (int): Flag to run post-processing (-1 or 1)
        - 'Run Sediment' (int): Flag to run sediment transport module (0 or 1)
        - 'Run UNET' (int): Flag to run unsteady network module (-1 or 1)
        - 'Run WQNET' (int): Flag to run water quality module (0 or 1)
        - 'Short Identifier' (str): Short name or ID for the plan
        - 'Simulation Date' (str): Start and end dates/times for simulation
        - 'UNET D1 Cores' (int): Number of cores used in 1D calculations
        - 'UNET D2 Cores' (int): Number of cores used in 2D calculations
        - 'PS Cores' (int): Number of cores used in parallel simulation
        - 'UNET Use Existing IB Tables' (int): Flag for using existing internal boundary tables (-1, 0, or 1)
        - 'UNET 1D Methodology' (str): 1D calculation methodology
        - 'UNET D2 Solver Type' (str): 2D solver type
        - 'UNET D2 Name' (str): Name of the 2D area
        - 'Run RASMapper' (int): Flag to run RASMapper for floodplain mapping (-1 for off, 0 for on)
        
        Note: 
        Writing Multi line keys like 'Description' are not supported by this function.

        Example:
        >>> computation_interval = RasPlan.get_plan_value("01", "Computation Interval")
        >>> print(f"Computation interval: {computation_interval}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        supported_plan_keys = {
            'Description', 'Computation Interval', 'DSS File', 'Flow File', 'Friction Slope Method',
            'Geom File', 'Mapping Interval', 'Plan File', 'Plan Title', 'Program Version',
            'Run HTab', 'Run Post Process', 'Run Sediment', 'Run UNet', 'Run UNET', 'Run WQNET',
            'Short Identifier', 'Simulation Date', 'UNET D1 Cores', 'UNET D2 Cores', 'PS Cores',
            'UNET Use Existing IB Tables', 'UNET 1D Methodology', 'UNET D2 Solver Type', 
            'UNET D2 Name', 'Run RASMapper', 'Run HTab', 'Run UNET',
            'Write IC File', 'Write IC File at Fixed DateTime', 'IC Time',
            'Write IC File Reoccurance', 'Write IC File at Sim End'
        }

        if key not in supported_plan_keys:
            logger = logging.getLogger(__name__)
            logger.warning("Unknown plan key requested: %s", key)
            logger.debug(
                "Supported plan keys for get_plan_value(): %s",
                ", ".join(sorted(supported_plan_keys)),
            )

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read()
        except IOError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        # Handle core settings specially to convert to integers
        core_keys = {'UNET D1 Cores', 'UNET D2 Cores', 'PS Cores'}
        if key in core_keys:
            pattern = f"{key}=(.*)"
            match = re.search(pattern, content)
            if match:
                try:
                    return int(match.group(1).strip())
                except ValueError:
                    logger = logging.getLogger(__name__)
                    logger.error(f"Could not convert {key} value to integer")
                    return None
            else:
                logger = logging.getLogger(__name__)
                logger.error(f"Key '{key}' not found in the plan file.")
                return None
        elif key == 'Description':
            match = re.search(r'Begin DESCRIPTION(.*?)END DESCRIPTION', content, re.DOTALL)
            return match.group(1).strip() if match else None
        else:
            pattern = f"{key}=(.*)"
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()
            else:
                logger = logging.getLogger(__name__)
                logger.error(f"Key '{key}' not found in the plan file.")
                return None





    @staticmethod
    @log_call
    def update_run_flags(
        plan_number_or_path: Union[str, Path],
        geometry_preprocessor: bool = None,
        unsteady_flow_simulation: bool = None,
        run_sediment: bool = None,
        post_processor: bool = None,
        floodplain_mapping: bool = None,
        ras_object=None
    ) -> None:
        """
        Update the run flags in a HEC-RAS plan file.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        geometry_preprocessor (bool, optional): Set Geometry Preprocessor (Run HTab, -1 = ON, 0 = OFF)
        unsteady_flow_simulation (bool, optional): Set Unsteady Flow (Run UNet, -1 = ON, 0 = OFF)
        run_sediment (bool, optional): Set Run Sediment (Run Sediment, -1 = ON, 0 = OFF)
        post_processor (bool, optional): Set Post Processor (Run PostProcess, -1 = ON, 0 = OFF)
        floodplain_mapping (bool, optional): Set Floodplain Mapping (Run RASMapper, -1 = ON, 0 = OFF)
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Raises:
        ValueError: If the plan file is not found
        IOError: If there's an error reading or writing the plan file

        Notes:
        - -1 is ON, 0 is OFF
        - Lines affected in plan file:
            Run HTab= -1           # geometry_preprocessor
            Run UNet= -1           # unsteady_flow_simulation
            Run Sediment= 0        # run_sediment
            Run PostProcess= -1    # post_processor
            Run RASMapper= 0       # floodplain_mapping

        Example:
        >>> RasPlan.update_run_flags("01", geometry_preprocessor=True, unsteady_flow_simulation=True, run_sediment=False, post_processor=True, floodplain_mapping=False)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        # Map arguments to plan keys (string in file : argument, ON=-1, OFF=0)
        flag_map = [
            ("Run HTab", geometry_preprocessor),
            ("Run UNet", unsteady_flow_simulation),
            ("Run Sediment", run_sediment),
            ("Run PostProcess", post_processor),
            ("Run RASMapper", floodplain_mapping)
        ]

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Annotate which flags got edited for logger
            updated_lines = 0

            for flag, value in flag_map:
                if value is not None:
                    # Find and update the line
                    found = False
                    for idx, line in enumerate(lines):
                        if line.strip().startswith(f"{flag}="):
                            lines[idx] = f"{flag}= {-1 if value else 0}\n"
                            updated_lines += 1
                            found = True
                            break
                    if not found:
                        # If not present, add the line at end (optional; original HEC-RAS behavior retains missing as OFF)
                        lines.append(f"{flag}= {-1 if value else 0}\n")
                        updated_lines += 1

            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as f:
                f.writelines(lines)

            logger = get_logger(__name__)
            logger.info(
                "Updated run flags in plan file: %s (flags modified: %d)",
                plan_file_path.name,
                updated_lines,
            )
            logger.debug("Updated run flags in plan file path: %s", plan_file_path)

        except IOError as e:
            logger = get_logger(__name__)
            logger.error(f"Error updating run flags in plan file {plan_file_path}: {e}")
            raise


    @staticmethod
    @log_call
    def update_plan_intervals(
        plan_number_or_path: Union[str, Path],
        computation_interval: Optional[str] = None,
        output_interval: Optional[str] = None,
        instantaneous_interval: Optional[str] = None,
        mapping_interval: Optional[str] = None,
        ras_object=None
    ) -> None:
        """
        Update the computation and output intervals in a HEC-RAS plan file.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        computation_interval (Optional[str]): The new computation interval. Valid entries include:
            '1SEC', '2SEC', '3SEC', '4SEC', '5SEC', '6SEC', '10SEC', '15SEC', '20SEC', '30SEC',
            '1MIN', '2MIN', '3MIN', '4MIN', '5MIN', '6MIN', '10MIN', '15MIN', '20MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'
        output_interval (Optional[str]): The new output interval. Valid entries are the same as computation_interval.
        instantaneous_interval (Optional[str]): The new instantaneous interval. Valid entries are the same as computation_interval.
        mapping_interval (Optional[str]): The new mapping interval. Valid entries are the same as computation_interval.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Raises:
        ValueError: If the plan file is not found or if an invalid interval is provided
        IOError: If there's an error reading or writing the plan file

        Note: This function does not check if the intervals are equal divisors. Ensure you use valid values from HEC-RAS.

        Example:
        >>> RasPlan.update_plan_intervals("01", computation_interval="5SEC", output_interval="1MIN", instantaneous_interval="1HOUR", mapping_interval="5MIN")
        >>> RasPlan.update_plan_intervals("/path/to/plan.p01", computation_interval="10SEC", output_interval="30SEC")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        valid_intervals = [
            '1SEC', '2SEC', '3SEC', '4SEC', '5SEC', '6SEC', '10SEC', '15SEC', '20SEC', '30SEC',
            '1MIN', '2MIN', '3MIN', '4MIN', '5MIN', '6MIN', '10MIN', '15MIN', '20MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'
        ]

        interval_mapping = {
            'Computation Interval': computation_interval,
            'Output Interval': output_interval,
            'Instantaneous Interval': instantaneous_interval,
            'Mapping Interval': mapping_interval
        }

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            for i, line in enumerate(lines):
                for key, value in interval_mapping.items():
                    if value is not None:
                        if value.upper() not in valid_intervals:
                            raise ValueError(f"Invalid {key}: {value}. Must be one of {valid_intervals}")
                        if line.strip().startswith(key):
                            lines[i] = f"{key}={value.upper()}\n"

            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger = logging.getLogger(__name__)
            logger.info("Updated intervals in plan file: %s", Path(plan_file_path).name)
            logger.debug("Updated intervals in plan file path: %s", plan_file_path)

        except IOError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error updating intervals in plan file {plan_file_path}: {e}")
            raise
     
     




    @staticmethod
    @log_call
    def read_plan_description(plan_number_or_path: Union[str, Path], ras_object: Optional['RasPrj'] = None) -> str:
        """
        Read the description from the plan file.

        Args:
            plan_number_or_path (Union[str, Path]): The plan number or path to the plan file.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            str: The description from the plan file.

        Raises:
            ValueError: If the plan file is not found.
            IOError: If there's an error reading from the plan file.
        """
        logger = logging.getLogger(__name__)

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
        except IOError as e:
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        description_lines = []
        in_description = False
        description_found = False
        for line in lines:
            stripped_upper = line.strip().upper()
            if stripped_upper in ('BEGIN DESCRIPTION:', 'BEGIN DESCRIPTION'):
                in_description = True
                description_found = True
            elif stripped_upper in ('END DESCRIPTION:', 'END DESCRIPTION'):
                break
            elif in_description:
                description_lines.append(line.strip())

        if not description_found:
            logger.debug("No description found in plan file: %s", plan_file_path.name)
            logger.debug("Plan file path without description: %s", plan_file_path)
            return ""

        description = '\n'.join(description_lines)
        logger.debug("Read description from plan file: %s", plan_file_path)
        return description


    @staticmethod
    @log_call
    def update_plan_description(plan_number: Union[str, Number], description: str, ras_object=None):
        """
        Update or insert plan description in the correct location within a plan file.

        The description block will be placed after initial plan parameters
        (Plan Title, Program Version, Short Identifier, Simulation Date, Geom File,
        Flow File, and flow type) but before the Computation Interval line.

        Parameters:
        -----------
        plan_number : Union[str, Number]
            Plan number to update (e.g., '01', 1, or 1.0)
        description : str
            Description text to insert. Will be automatically wrapped in
            BEGIN DESCRIPTION/END DESCRIPTION blocks.
        ras_object : RasPrj, optional
            RAS project object. If None, uses global 'ras' object.
        
        Returns:
        --------
        bool : True if successful, False otherwise
        
        Examples:
        ---------
        >>> RasPlan.update_plan_description('02', 
        ...     'Atlas 14 Uncertainty Analysis\\n' +
        ...     'AEP: 100 years\\n' +
        ...     'Duration: 24 hours\\n' +
        ...     'Confidence Level: upper')
        True
        """
        logger = get_logger(__name__)
        try:
            # Get the RAS object
            if ras_object is None:
                ras_obj = ras
            else:
                ras_obj = ras_object
            
            # Get plan path
            plan_path = RasPlan.get_plan_path(plan_number, ras_object=ras_obj)
            
            # Read the plan file
            with open(plan_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            # Find existing description block if it exists
            desc_start_idx = None
            desc_end_idx = None
            
            for i, line in enumerate(lines):
                if line.strip().upper().startswith('BEGIN DESCRIPTION'):
                    desc_start_idx = i
                elif line.strip().upper().startswith('END DESCRIPTION'):
                    desc_end_idx = i
                    break
            
            # Find the correct insertion point (before Computation Interval)
            insertion_idx = None
            
            # Primary method: Find Computation Interval line
            for i, line in enumerate(lines):
                if line.strip().startswith('Computation Interval='):
                    insertion_idx = i
                    break
            
            # Fallback method 1: Look for common parameter lines that come after description
            if insertion_idx is None:
                fallback_markers = [
                    'K Sum by GR=',
                    'Std Step Tol=',
                    'Critical Tol=',
                    'Num of Std Step Trials=',
                    'Max Error Tol=',
                    'Flow Tol Ratio=',
                    'Split Flow NTrial=',
                    'Split Flow Tol=',
                    'Split Flow Ratio=',
                    'Log Output Level=',
                    'Friction Slope Method=',
                    'Unsteady Friction Slope Method='
                ]
                
                for i, line in enumerate(lines):
                    for marker in fallback_markers:
                        if line.strip().startswith(marker):
                            insertion_idx = i
                            break
                    if insertion_idx is not None:
                        break
            
            # Fallback method 2: Insert after initial parameters and flow type
            if insertion_idx is None:
                # Find the last of the initial parameters
                initial_params = [
                    'Plan Title=',
                    'Program Version=',
                    'Short Identifier=',
                    'Simulation Date=',
                    'Geom File=',
                    'Flow File='
                ]
                
                last_param_idx = 0
                for i, line in enumerate(lines):
                    for param in initial_params:
                        if line.strip().startswith(param):
                            last_param_idx = max(last_param_idx, i)
                
                # Check for flow type lines after Flow File
                flow_types = ['Subcritical Flow', 'Mixed Flow', 'Supercritical Flow']
                for i in range(last_param_idx + 1, min(last_param_idx + 5, len(lines))):
                    if i < len(lines) and lines[i].strip() in flow_types:
                        last_param_idx = i
                
                insertion_idx = last_param_idx + 1
            
            # Prepare the new description block
            # Ensure description doesn't have trailing newline for proper formatting
            description_clean = description.rstrip()

            description_block = [
                'BEGIN DESCRIPTION:\n',
                description_clean + '\n',
                'END DESCRIPTION:\n'
            ]
            
            # Build the new file content
            if desc_start_idx is not None and desc_end_idx is not None:
                # Replace existing description block
                # Keep it in its current location if it's already in the right place
                # Otherwise move it to the correct location
                if desc_start_idx < insertion_idx:
                    # Description is already before insertion point, replace in place
                    new_lines = lines[:desc_start_idx] + description_block + lines[desc_end_idx + 1:]
                else:
                    # Description is after insertion point, need to move it
                    # Remove old description
                    lines_without_desc = lines[:desc_start_idx] + lines[desc_end_idx + 1:]
                    # Insert at correct location
                    new_lines = lines_without_desc[:insertion_idx] + description_block + lines_without_desc[insertion_idx:]
            else:
                # No existing description, insert new one
                new_lines = lines[:insertion_idx] + description_block + lines[insertion_idx:]
            
            # Write the modified content back to the file
            with open(plan_path, 'w', encoding='utf-8', errors='replace') as f:
                f.writelines(new_lines)
            
            # Validate the result (optional debug check)
            if __debug__:  # Only in debug mode
                with open(plan_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                # Check that description comes before Computation Interval
                if 'Begin DESCRIPTION' in content and 'Computation Interval=' in content:
                    desc_pos = content.find('Begin DESCRIPTION')
                    comp_pos = content.find('Computation Interval=')
                    if desc_pos > comp_pos:
                        logger.warning(
                            "Description block may be in wrong position in plan %s",
                            plan_number,
                        )
            
            return True
            
        except FileNotFoundError:
            logger.error("Plan file not found for plan %s", plan_number)
            return False
        except IOError as e:
            logger.error("IO error updating plan %s: %s", plan_number, e)
            return False
        except Exception as e:
            logger.error("Unexpected error updating plan %s: %s", plan_number, e)
            logger.debug("Unexpected error updating plan description", exc_info=True)
            return False

    @staticmethod
    @log_call
    def read_geom_description(geom_number_or_path: Union[str, Number, Path], ras_object=None) -> str:
        """
        Read the description from a geometry file (.g##).

        Args:
            geom_number_or_path (Union[str, Number, Path]): The geometry number (e.g., '01')
                or path to the geometry file.
            ras_object (RasPrj, optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            str: The description text, or empty string if not found.

        Raises:
            ValueError: If the geometry file is not found.
        """
        geom_file_path = Path(geom_number_or_path)
        if not geom_file_path.is_file():
            geom_file_path = RasPlan.get_geom_path(geom_number_or_path, ras_object)
            if geom_file_path is None or not Path(geom_file_path).exists():
                raise ValueError(f"Geometry file not found: {geom_number_or_path}")

        return RasUtils._read_description_block(geom_file_path)

    @staticmethod
    @log_call
    def update_geom_description(geom_number_or_path: Union[str, Number, Path], description: str, ras_object=None) -> bool:
        """
        Update or insert the description in a geometry file (.g##).

        Args:
            geom_number_or_path (Union[str, Number, Path]): The geometry number (e.g., '01')
                or path to the geometry file.
            description (str): Description text to write.
            ras_object (RasPrj, optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If the geometry file is not found.
        """
        geom_file_path = Path(geom_number_or_path)
        if not geom_file_path.is_file():
            geom_file_path = RasPlan.get_geom_path(geom_number_or_path, ras_object)
            if geom_file_path is None or not Path(geom_file_path).exists():
                raise ValueError(f"Geometry file not found: {geom_number_or_path}")

        return RasUtils._write_description_block(geom_file_path, description, 'Geom Title')

    @staticmethod
    @log_call
    def read_flow_description(flow_number_or_path: Union[str, Number, Path], ras_object=None) -> str:
        """
        Read the description from a steady flow file (.f##).

        Args:
            flow_number_or_path (Union[str, Number, Path]): The flow number (e.g., '01')
                or path to the flow file.
            ras_object (RasPrj, optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            str: The description text, or empty string if not found.

        Raises:
            ValueError: If the flow file is not found.
        """
        flow_file_path = Path(flow_number_or_path)
        if not flow_file_path.is_file():
            flow_file_path = RasPlan.get_flow_path(flow_number_or_path, ras_object)
            if flow_file_path is None or not Path(flow_file_path).exists():
                raise ValueError(f"Flow file not found: {flow_number_or_path}")

        return RasUtils._read_description_block(flow_file_path)

    @staticmethod
    @log_call
    def update_flow_description(flow_number_or_path: Union[str, Number, Path], description: str, ras_object=None) -> bool:
        """
        Update or insert the description in a steady flow file (.f##).

        Args:
            flow_number_or_path (Union[str, Number, Path]): The flow number (e.g., '01')
                or path to the flow file.
            description (str): Description text to write.
            ras_object (RasPrj, optional): RAS project object. If None, uses global 'ras' object.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If the flow file is not found.
        """
        flow_file_path = Path(flow_number_or_path)
        if not flow_file_path.is_file():
            flow_file_path = RasPlan.get_flow_path(flow_number_or_path, ras_object)
            if flow_file_path is None or not Path(flow_file_path).exists():
                raise ValueError(f"Flow file not found: {flow_number_or_path}")

        return RasUtils._write_description_block(flow_file_path, description, 'Flow Title')



    




    @staticmethod
    @log_call
    def update_simulation_date(plan_number_or_path: Union[str, Number, Path], start_date: datetime, end_date: datetime, ras_object: Optional['RasPrj'] = None) -> None:
        """
        Update the simulation date for a given plan.

        Args:
            plan_number_or_path (Union[str, Number, Path]): The plan number (str, int, or float)
                or path to the plan file.
            start_date (datetime): The start date and time for the simulation.
            end_date (datetime): The end date and time for the simulation.
            ras_object (Optional['RasPrj']): The RAS project object. Defaults to None.

        Raises:
            ValueError: If the plan file is not found or if there's an error updating the file.
        """

        # Get the plan file path
        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        # Format the dates
        formatted_date = f"{start_date.strftime('%d%b%Y').upper()},{start_date.strftime('%H%M')},{end_date.strftime('%d%b%Y').upper()},{end_date.strftime('%H%M')}"

        try:
            # Read the file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            # Update the Simulation Date line
            updated = False
            for i, line in enumerate(lines):
                if line.startswith("Simulation Date="):
                    lines[i] = f"Simulation Date={formatted_date}\n"
                    updated = True
                    break

            # If Simulation Date line not found, raise instead of silently appending
            if not updated:
                raise ValueError(
                    f"'Simulation Date=' line not found in plan file: {plan_file_path}. "
                    "Cannot update simulation date."
                )

            # Write the updated content back to the file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger.info("Updated simulation date in plan file: %s", plan_file_path.name)
            logger.debug("Updated simulation date in plan file path: %s", plan_file_path)

        except OSError as e:
            logger.error(f"Error updating simulation date in plan file {plan_file_path}: {e}")
            raise

        # Refresh RasPrj dataframes
        if ras_object:
            ras_object.plan_df = ras_object.get_plan_entries()
            ras_object.unsteady_df = ras_object.get_unsteady_entries()

    @staticmethod
    @log_call
    def get_shortid(plan_number_or_path: Union[str, Number, Path], ras_object=None) -> str:
        """
        Get the Short Identifier from a HEC-RAS plan file.

        Args:
            plan_number_or_path (Union[str, Path]): The plan number or path to the plan file.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            str: The Short Identifier from the plan file.

        Raises:
            ValueError: If the plan file is not found.
            IOError: If there's an error reading from the plan file.

        Example:
            >>> shortid = RasPlan.get_shortid('01')
            >>> print(f"Plan's Short Identifier: {shortid}")
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get the Short Identifier using get_plan_value
        shortid = RasPlan.get_plan_value(plan_number_or_path, "Short Identifier", ras_obj)
        
        if shortid is None:
            logger.warning(f"Short Identifier not found in plan: {plan_number_or_path}")
            return ""
        
        logger.debug("Retrieved Short Identifier: %s", shortid)
        return shortid

    @staticmethod
    @log_call
    def set_shortid(plan_number_or_path: Union[str, Number, Path], new_shortid: str, ras_object=None) -> None:
        """
        Set the Short Identifier in a HEC-RAS plan file.

        Args:
            plan_number_or_path (Union[str, Path]): The plan number or path to the plan file.
            new_shortid (str): The new Short Identifier to set (max 24 characters).
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Raises:
            ValueError: If the plan file is not found or if new_shortid is too long.
            IOError: If there's an error updating the plan file.

        Example:
            >>> RasPlan.set_shortid('01', 'NewShortIdentifier')
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Ensure new_shortid is not too long (HEC-RAS limits short identifiers to 24 characters)
        if len(new_shortid) > 24:
            logger.warning(
                "Short Identifier exceeds 24 characters (received %d); truncating",
                len(new_shortid),
            )
            logger.debug("Original Short Identifier before truncation: %s", new_shortid)
            new_shortid = new_shortid[:24]

        # Get the plan file path
        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasUtils.get_plan_path(plan_number_or_path, ras_obj)
            if not plan_file_path.exists():
                logger.error(f"Plan file not found: {plan_file_path}")
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            # Read the file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            # Update the Short Identifier line
            updated = False
            for i, line in enumerate(lines):
                if line.startswith("Short Identifier="):
                    lines[i] = f"Short Identifier={new_shortid}\n"
                    updated = True
                    break

            # If Short Identifier line not found, add it after Plan Title
            if not updated:
                for i, line in enumerate(lines):
                    if line.startswith("Plan Title="):
                        lines.insert(i+1, f"Short Identifier={new_shortid}\n")
                        updated = True
                        break
                
                # If Plan Title not found either, add at the beginning
                if not updated:
                    lines.insert(0, f"Short Identifier={new_shortid}\n")

            # Write the updated content back to the file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger.info("Updated Short Identifier in plan file to: %s", new_shortid)
            logger.debug("Updated Short Identifier in plan file path: %s", plan_file_path)

        except IOError as e:
            logger.error(f"Error updating Short Identifier in plan file {plan_file_path}: {e}")
            raise ValueError(f"Error updating Short Identifier: {e}")

        # Refresh RasPrj dataframes if ras_object provided
        if ras_object:
            ras_object.plan_df = ras_object.get_plan_entries()

    @staticmethod
    @log_call
    def get_plan_title(plan_number_or_path: Union[str, Number, Path], ras_object=None) -> str:
        """
        Get the Plan Title from a HEC-RAS plan file.

        Args:
            plan_number_or_path (Union[str, Path]): The plan number or path to the plan file.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            str: The Plan Title from the plan file.

        Raises:
            ValueError: If the plan file is not found.
            IOError: If there's an error reading from the plan file.

        Example:
            >>> title = RasPlan.get_plan_title('01')
            >>> print(f"Plan Title: {title}")
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get the Plan Title using get_plan_value
        title = RasPlan.get_plan_value(plan_number_or_path, "Plan Title", ras_obj)
        
        if title is None:
            logger.warning(f"Plan Title not found in plan: {plan_number_or_path}")
            return ""
        
        logger.debug("Retrieved Plan Title: %s", title)
        return title

    @staticmethod
    @log_call
    def set_plan_title(plan_number_or_path: Union[str, Number, Path], new_title: str, ras_object=None) -> None:
        """
        Set the Plan Title in a HEC-RAS plan file.

        Args:
            plan_number_or_path (Union[str, Path]): The plan number or path to the plan file.
            new_title (str): The new Plan Title to set.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Raises:
            ValueError: If the plan file is not found.
            IOError: If there's an error updating the plan file.

        Example:
            >>> RasPlan.set_plan_title('01', 'Updated Plan Scenario')
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get the plan file path
        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasUtils.get_plan_path(plan_number_or_path, ras_obj)
            if not plan_file_path.exists():
                logger.error(f"Plan file not found: {plan_file_path}")
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            # Read the file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            # Update the Plan Title line
            updated = False
            for i, line in enumerate(lines):
                if line.startswith("Plan Title="):
                    lines[i] = f"Plan Title={new_title}\n"
                    updated = True
                    break

            # If Plan Title line not found, add it at the beginning
            if not updated:
                lines.insert(0, f"Plan Title={new_title}\n")

            # Write the updated content back to the file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger.info("Updated Plan Title in plan file to: %s", new_title)
            logger.debug("Updated Plan Title in plan file path: %s", plan_file_path)

        except IOError as e:
            logger.error(f"Error updating Plan Title in plan file {plan_file_path}: {e}")
            raise ValueError(f"Error updating Plan Title: {e}")

        # Refresh RasPrj dataframes if ras_object provided
        if ras_object:
            ras_object.plan_df = ras_object.get_plan_entries()

    @staticmethod
    def _split_plan_key_value(line: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Split a HEC-RAS text-file key/value line without losing empty values.
        """
        if "=" not in line:
            return None, None
        key, value = line.rstrip("\r\n").split("=", 1)
        return key.strip(), value.strip()

    @staticmethod
    def _parse_plan_program_version(lines: List[str]) -> Optional[str]:
        """
        Return the Program Version value from plan-file lines when present.
        """
        for line in lines:
            key, value = RasPlan._split_plan_key_value(line)
            if key == "Program Version":
                return value
        return None

    @staticmethod
    def _version_to_float(version: Optional[str]) -> Optional[float]:
        """
        Convert a HEC-RAS version string to a major.minor float for capability gates.
        """
        if not version:
            return None
        match = re.search(r"(\d+)(?:\.(\d+))?", str(version))
        if not match:
            return None
        major = match.group(1)
        minor = match.group(2) or "0"
        return float(f"{major}.{minor}")

    @staticmethod
    def _normalize_2d_equation_set(equation_set: Any) -> int:
        """
        Normalize a 2D equation-set value to the plan-file integer code.
        """
        if isinstance(equation_set, bool):
            raise ValueError("equation_set must be DWE, SWE-ELM, 0, or 1")
        if isinstance(equation_set, Number):
            code = int(equation_set)
            if code in RasPlan.TWO_D_EQUATION_CODE_TO_NAME:
                return code
        normalized = str(equation_set).strip().upper().replace("_", "-")
        normalized = re.sub(r"\s+", " ", normalized)
        if normalized in RasPlan.TWO_D_EQUATION_SET_ALIASES:
            return RasPlan.TWO_D_EQUATION_SET_ALIASES[normalized]
        valid = ", ".join(sorted({"DWE", "SWE-ELM", "Diffusion Wave", "Shallow Water"}))
        raise ValueError(f"Unknown 2D equation set '{equation_set}'. Valid values include: {valid}")

    @staticmethod
    def _parse_bool_like(value: Any) -> Optional[bool]:
        """
        Parse HEC-RAS boolean encodings such as -1/0 and True/False.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, Number):
            if pd.isna(value):
                return None
            return int(value) != 0
        normalized = str(value).strip().upper()
        if normalized == "":
            return None
        if normalized in {"TRUE", "T", "YES", "Y", "-1", "1"}:
            return True
        if normalized in {"FALSE", "F", "NO", "N", "0"}:
            return False
        raise ValueError(f"Cannot parse boolean value: {value}")

    @staticmethod
    def _coerce_2d_option_value(api_key: str, raw_value: Any) -> Any:
        """
        Convert raw plan/HDF option values to Python types.
        """
        meta = (
            RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.get(api_key)
            or RasPlan.TWO_D_PLAN_OPTION_KEYS.get(api_key)
        )
        if not meta:
            raise ValueError(f"Unknown 2D flow option '{api_key}'")

        if raw_value is None:
            return None
        if isinstance(raw_value, float) and pd.isna(raw_value):
            return None
        if isinstance(raw_value, str) and raw_value.strip() == "":
            return None

        value_type = meta["type"]
        if value_type == "equation":
            code = RasPlan._normalize_2d_equation_set(raw_value)
            return RasPlan.TWO_D_EQUATION_CODE_TO_NAME[code]
        if value_type == "bool":
            return RasPlan._parse_bool_like(raw_value)
        if value_type == "int":
            return int(float(str(raw_value).strip()))
        if value_type == "float":
            return float(str(raw_value).strip())
        if value_type == "interval":
            interval = str(raw_value).strip().upper()
            if interval and interval not in RasPlan.VALID_PLAN_INTERVALS:
                raise ValueError(
                    f"Invalid computation_interval: {raw_value}. "
                    f"Must be one of {RasPlan.VALID_PLAN_INTERVALS}"
                )
            return interval
        return str(raw_value).strip()

    @staticmethod
    def _format_2d_option_value(api_key: str, value: Any) -> str:
        """
        Convert Python option values to HEC-RAS plan-file strings.
        """
        meta = (
            RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.get(api_key)
            or RasPlan.TWO_D_PLAN_OPTION_KEYS.get(api_key)
        )
        if not meta:
            raise ValueError(f"Unknown 2D flow option '{api_key}'")

        if value is None:
            return ""

        value_type = meta["type"]
        if value_type == "equation":
            return str(RasPlan._normalize_2d_equation_set(value))
        if value_type == "bool":
            return "-1" if RasPlan._parse_bool_like(value) else "0"
        if value_type == "int":
            int_value = int(value)
            if int_value < 0:
                raise ValueError(f"{api_key} must be >= 0")
            return str(int_value)
        if value_type == "float":
            float_value = float(value)
            if api_key in {
                "initial_conditions_time_hours",
                "time_step_max_courant",
                "time_step_min_courant",
            } and float_value < 0:
                raise ValueError(f"{api_key} must be >= 0")
            if api_key == "ramp_up_fraction" and not 0 <= float_value <= 1:
                raise ValueError("ramp_up_fraction must be between 0 and 1")
            return f"{float_value:g}"
        if value_type == "interval":
            return RasPlan._coerce_2d_option_value(api_key, value)
        return str(value)

    @staticmethod
    def _format_2d_plan_line(plan_key: str, value: str) -> str:
        """
        Format one HEC-RAS plan-file option line.
        """
        if value == "":
            return f"{plan_key}=\n"
        if plan_key.startswith("Computation Time Step Use"):
            return f"{plan_key}=        {value}\n"
        if plan_key in {
            "Computation Interval",
            "UNET D2 RampUpFraction",
            "UNET D2 BCVolumeCheck",
        }:
            return f"{plan_key}={value}\n"
        return f"{plan_key}= {value} \n"

    @staticmethod
    def _collect_2d_sections(lines: List[str]) -> List[Dict[str, Any]]:
        """
        Identify default and named 2D option sections in plan-file lines.
        """
        default_section = {
            "name": None,
            "name_index": None,
            "indices": {},
            "last_index": None,
        }
        sections = [default_section]
        current = default_section
        area_plan_keys = {
            meta["plan_key"]
            for meta in RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.values()
        }

        for index, line in enumerate(lines):
            key, value = RasPlan._split_plan_key_value(line)
            if key == "UNET D2 Name":
                current = {
                    "name": value.strip(),
                    "name_index": index,
                    "indices": {"UNET D2 Name": index},
                    "last_index": index,
                }
                sections.append(current)
                continue
            if key in area_plan_keys:
                current["indices"][key] = index
                current["last_index"] = index

        return sections

    @staticmethod
    def _collect_plan_option_indices(lines: List[str]) -> Dict[str, int]:
        """
        Locate plan-level 2D computation option lines.
        """
        plan_keys = {
            meta["plan_key"]
            for meta in RasPlan.TWO_D_PLAN_OPTION_KEYS.values()
        }
        indices = {}
        for index, line in enumerate(lines):
            key, _ = RasPlan._split_plan_key_value(line)
            if key in plan_keys and key not in indices:
                indices[key] = index
        return indices

    @staticmethod
    def _find_plan_option_insert_index(lines: List[str], plan_key: str) -> int:
        """
        Find a stable insertion point for plan-level 2D options.
        """
        ordered_keys = [
            meta["plan_key"]
            for meta in RasPlan.TWO_D_PLAN_OPTION_KEYS.values()
        ]
        target_index = ordered_keys.index(plan_key)
        for previous_key in reversed(ordered_keys[:target_index]):
            for index, line in enumerate(lines):
                key, _ = RasPlan._split_plan_key_value(line)
                if key == previous_key:
                    return index + 1

        insert_index = len(lines)
        for index, line in enumerate(lines):
            key, _ = RasPlan._split_plan_key_value(line)
            if key in {"Output Interval", "Instantaneous Interval", "Mapping Interval"}:
                insert_index = index + 1
            elif key == "Run HTab":
                return index
        return insert_index

    @staticmethod
    def _find_area_option_insert_index(section: Dict[str, Any], plan_key: str) -> int:
        """
        Find a stable insertion point within a 2D flow-area option section.
        """
        ordered_keys = RasPlan.TWO_D_FLOW_AREA_OPTION_ORDER
        target_index = ordered_keys.index(plan_key)
        for previous_key in reversed(ordered_keys[:target_index]):
            if previous_key in section["indices"]:
                return section["indices"][previous_key] + 1
        if section.get("name_index") is not None:
            return section["name_index"] + 1
        if section.get("last_index") is not None:
            return section["last_index"] + 1
        return 0

    @staticmethod
    def _shift_2d_section_indices(
        sections: List[Dict[str, Any]],
        plan_indices: Dict[str, int],
        insert_index: int
    ) -> None:
        """
        Adjust cached line indices after inserting one line.
        """
        for section in sections:
            if section.get("name_index") is not None and section["name_index"] >= insert_index:
                section["name_index"] += 1
            if section.get("last_index") is not None and section["last_index"] >= insert_index:
                section["last_index"] += 1
            for key, index in list(section["indices"].items()):
                if index >= insert_index:
                    section["indices"][key] = index + 1
        for key, index in list(plan_indices.items()):
            if index >= insert_index:
                plan_indices[key] = index + 1

    @staticmethod
    def _validate_2d_option_compatibility(
        updates: Dict[str, Any],
        program_version: Optional[str]
    ) -> None:
        """
        Validate option availability against the plan Program Version.
        """
        version_value = RasPlan._version_to_float(program_version)
        for api_key in updates:
            meta = (
                RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.get(api_key)
                or RasPlan.TWO_D_PLAN_OPTION_KEYS.get(api_key)
            )
            if not meta:
                raise ValueError(f"Unknown 2D flow option '{api_key}'")
            min_version = meta.get("min_version")
            if version_value is not None and min_version is not None and version_value < min_version:
                raise ValueError(
                    f"Option '{api_key}' requires HEC-RAS {min_version:g}+; "
                    f"plan Program Version is {program_version}"
                )

    @staticmethod
    def _normalize_2d_option_updates(
        options: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Merge explicit keyword options with an option dictionary and validate keys.
        """
        valid_keys = set(RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS) | set(RasPlan.TWO_D_PLAN_OPTION_KEYS)
        updates = {}
        if options:
            unknown = sorted(set(options) - valid_keys)
            if unknown:
                valid = ", ".join(sorted(valid_keys))
                raise ValueError(f"Unknown 2D flow option(s): {unknown}. Valid options: {valid}")
            updates.update(options)

        for key, value in kwargs.items():
            if value is not None:
                updates[key] = value

        unknown = sorted(set(updates) - valid_keys)
        if unknown:
            valid = ", ".join(sorted(valid_keys))
            raise ValueError(f"Unknown 2D flow option(s): {unknown}. Valid options: {valid}")
        return updates

    @staticmethod
    def _resolve_2d_target_sections(
        sections: List[Dict[str, Any]],
        mesh_name: Optional[str],
        include_default: bool
    ) -> List[Dict[str, Any]]:
        """
        Select named/default 2D sections to update.
        """
        default_sections = [section for section in sections if section["name"] is None]
        named_sections = [section for section in sections if section["name"] is not None]

        if mesh_name is None:
            targets = list(named_sections)
            if include_default:
                targets = default_sections + targets
            if not targets and default_sections:
                targets = default_sections
            return targets

        normalized = mesh_name.strip().lower()
        targets = [
            section for section in named_sections
            if section["name"].strip().lower() == normalized
        ]
        if include_default:
            targets = default_sections + targets
        if not targets:
            available = ", ".join(section["name"].strip() for section in named_sections) or "none"
            raise ValueError(f"2D flow area '{mesh_name}' not found. Available areas: {available}")
        return targets

    @staticmethod
    @log_call
    def list_2d_flow_option_names() -> Dict[str, str]:
        """
        List public 2D flow option names and their HEC-RAS plan-file keys.

        Returns:
            Dict[str, str]: ras-commander option names mapped to plan-file keys.
        """
        options = {}
        for api_key, meta in RasPlan.TWO_D_PLAN_OPTION_KEYS.items():
            options[api_key] = meta["plan_key"]
        for api_key, meta in RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.items():
            options[api_key] = meta["plan_key"]
        return options

    @staticmethod
    @log_call
    def get_2d_flow_options(
        plan_number_or_path: Union[str, Number, Path],
        mesh_name: Optional[str] = None,
        ras_object=None
    ) -> Dict[str, Any]:
        """
        Parse 2D unsteady computation options from a HEC-RAS plan file.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            mesh_name: Optional 2D flow area name to filter the returned areas.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            Dict[str, Any]: Parsed options with ``plan``, ``default``, and
                ``areas`` sections. Equation-set values are normalized to
                ``"DWE"`` or ``"SWE-ELM"``.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            raise ValueError(f"Plan file not found: {plan_number_or_path}")

        with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
            lines = file.readlines()

        area_key_to_api_key = {
            meta["plan_key"]: api_key
            for api_key, meta in RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS.items()
        }
        plan_key_to_api_key = {
            meta["plan_key"]: api_key
            for api_key, meta in RasPlan.TWO_D_PLAN_OPTION_KEYS.items()
        }

        plan_options = {}
        default_options = {}
        areas = []
        current_area = None

        for line in lines:
            key, raw_value = RasPlan._split_plan_key_value(line)
            if key is None:
                continue
            if key == "UNET D2 Name":
                current_area = {"name": raw_value.strip()}
                areas.append(current_area)
                continue
            if key in plan_key_to_api_key:
                api_key = plan_key_to_api_key[key]
                plan_options[api_key] = RasPlan._coerce_2d_option_value(api_key, raw_value)
            elif key in area_key_to_api_key:
                api_key = area_key_to_api_key[key]
                target = current_area if current_area is not None else default_options
                target[api_key] = RasPlan._coerce_2d_option_value(api_key, raw_value)

        if mesh_name is not None:
            normalized = mesh_name.strip().lower()
            areas = [
                area for area in areas
                if area.get("name", "").strip().lower() == normalized
            ]
            if not areas:
                raise ValueError(f"2D flow area '{mesh_name}' not found in {plan_file_path.name}")

        return {
            "source": "plan",
            "plan_path": str(plan_file_path),
            "program_version": RasPlan._parse_plan_program_version(lines),
            "plan": plan_options,
            "default": default_options,
            "areas": areas,
        }

    @staticmethod
    @log_call
    def set_2d_flow_options(
        plan_number_or_path: Union[str, Number, Path],
        mesh_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        equation_set: Optional[Union[str, int]] = None,
        initial_conditions_time_hours: Optional[float] = None,
        theta: Optional[float] = None,
        theta_warmup: Optional[float] = None,
        water_surface_tolerance: Optional[float] = None,
        volume_tolerance: Optional[float] = None,
        max_iterations: Optional[int] = None,
        ramp_up_fraction: Optional[float] = None,
        time_slices: Optional[int] = None,
        eddy_viscosity: Optional[float] = None,
        transverse_eddy_viscosity: Optional[float] = None,
        smagorinsky_mixing: Optional[float] = None,
        boundary_condition_volume_check: Optional[bool] = None,
        latitude: Optional[float] = None,
        cores: Optional[int] = None,
        solver_type: Optional[str] = None,
        coriolis: Optional[bool] = None,
        computation_interval: Optional[str] = None,
        time_step_use_courant: Optional[bool] = None,
        time_step_use_time_series: Optional[bool] = None,
        time_step_max_courant: Optional[float] = None,
        time_step_min_courant: Optional[float] = None,
        time_step_count_to_double: Optional[int] = None,
        time_step_max_doubling: Optional[int] = None,
        time_step_max_halving: Optional[int] = None,
        time_step_residence_courant: Optional[bool] = None,
        include_default: bool = False,
        ras_object=None
    ) -> bool:
        """
        Set typed 2D unsteady computation options in a HEC-RAS plan file.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            mesh_name: Optional 2D flow area name. If omitted, all named
                2D flow-area sections are updated.
            options: Optional mapping of public option names to values.
            equation_set: ``"DWE"``/``0`` or ``"SWE-ELM"``/``1``.
            initial_conditions_time_hours: 2D initial conditions ramp-up time.
            include_default: Also update the default unnamed 2D settings block.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            bool: True when the plan file was written or already matched.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        updates = RasPlan._normalize_2d_option_updates(
            options=options,
            equation_set=equation_set,
            initial_conditions_time_hours=initial_conditions_time_hours,
            theta=theta,
            theta_warmup=theta_warmup,
            water_surface_tolerance=water_surface_tolerance,
            volume_tolerance=volume_tolerance,
            max_iterations=max_iterations,
            ramp_up_fraction=ramp_up_fraction,
            time_slices=time_slices,
            eddy_viscosity=eddy_viscosity,
            transverse_eddy_viscosity=transverse_eddy_viscosity,
            smagorinsky_mixing=smagorinsky_mixing,
            boundary_condition_volume_check=boundary_condition_volume_check,
            latitude=latitude,
            cores=cores,
            solver_type=solver_type,
            coriolis=coriolis,
            computation_interval=computation_interval,
            time_step_use_courant=time_step_use_courant,
            time_step_use_time_series=time_step_use_time_series,
            time_step_max_courant=time_step_max_courant,
            time_step_min_courant=time_step_min_courant,
            time_step_count_to_double=time_step_count_to_double,
            time_step_max_doubling=time_step_max_doubling,
            time_step_max_halving=time_step_max_halving,
            time_step_residence_courant=time_step_residence_courant,
        )
        if not updates:
            logger.debug("No 2D flow options requested")
            return True

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            raise ValueError(f"Plan file not found: {plan_number_or_path}")

        with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
            lines = file.readlines()
        original_lines = list(lines)

        program_version = RasPlan._parse_plan_program_version(lines)
        RasPlan._validate_2d_option_compatibility(updates, program_version)

        sections = RasPlan._collect_2d_sections(lines)
        plan_indices = RasPlan._collect_plan_option_indices(lines)

        area_updates = {
            key: value
            for key, value in updates.items()
            if key in RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS
        }
        plan_updates = {
            key: value
            for key, value in updates.items()
            if key in RasPlan.TWO_D_PLAN_OPTION_KEYS
        }

        for api_key, value in plan_updates.items():
            plan_key = RasPlan.TWO_D_PLAN_OPTION_KEYS[api_key]["plan_key"]
            formatted_value = RasPlan._format_2d_option_value(api_key, value)
            new_line = RasPlan._format_2d_plan_line(plan_key, formatted_value)
            if plan_key in plan_indices:
                lines[plan_indices[plan_key]] = new_line
            else:
                insert_index = RasPlan._find_plan_option_insert_index(lines, plan_key)
                lines.insert(insert_index, new_line)
                RasPlan._shift_2d_section_indices(sections, plan_indices, insert_index)
                plan_indices[plan_key] = insert_index

        if area_updates:
            target_sections = RasPlan._resolve_2d_target_sections(
                sections,
                mesh_name=mesh_name,
                include_default=include_default,
            )
            if not target_sections:
                raise ValueError(f"No 2D flow-area sections found in {plan_file_path.name}")

            area_plan_key_order = {
                plan_key: index
                for index, plan_key in enumerate(RasPlan.TWO_D_FLOW_AREA_OPTION_ORDER)
            }
            ordered_area_updates = sorted(
                area_updates.items(),
                key=lambda item: area_plan_key_order[
                    RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS[item[0]]["plan_key"]
                ],
            )

            for section in target_sections:
                for api_key, value in ordered_area_updates:
                    plan_key = RasPlan.TWO_D_FLOW_AREA_OPTION_KEYS[api_key]["plan_key"]
                    formatted_value = RasPlan._format_2d_option_value(api_key, value)
                    new_line = RasPlan._format_2d_plan_line(plan_key, formatted_value)
                    if plan_key in section["indices"]:
                        lines[section["indices"][plan_key]] = new_line
                    else:
                        insert_index = RasPlan._find_area_option_insert_index(section, plan_key)
                        lines.insert(insert_index, new_line)
                        RasPlan._shift_2d_section_indices(sections, plan_indices, insert_index)
                        section["indices"][plan_key] = insert_index
                        section["last_index"] = max(section.get("last_index") or insert_index, insert_index)

        if lines == original_lines:
            logger.debug("2D flow options already current in plan file: %s", plan_file_path.name)
            return True

        with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
            file.writelines(lines)

        logger.info(f"Updated 2D flow options in plan file: {plan_file_path.name}")
        return True

    @staticmethod
    @log_call
    def set_2d_equation_set(
        plan_number_or_path: Union[str, Number, Path],
        equation_set: Union[str, int],
        mesh_name: Optional[str] = None,
        computation_interval: Optional[str] = None,
        initial_conditions_time_hours: Optional[float] = None,
        include_default: bool = False,
        ras_object=None
    ) -> bool:
        """
        Switch a plan's 2D equation set between DWE and SWE-ELM.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            equation_set: ``"DWE"``/``0`` or ``"SWE-ELM"``/``1``.
            mesh_name: Optional 2D flow area name. If omitted, all named areas
                are updated.
            computation_interval: Optional plan computation interval to update
                with the equation-set change.
            initial_conditions_time_hours: Optional 2D initial conditions time.
            include_default: Also update the default unnamed 2D settings block.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            bool: True when the plan file was updated or already matched.
        """
        return RasPlan.set_2d_flow_options(
            plan_number_or_path,
            mesh_name=mesh_name,
            equation_set=equation_set,
            computation_interval=computation_interval,
            initial_conditions_time_hours=initial_conditions_time_hours,
            include_default=include_default,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def list_available_hdf_output_variables() -> List[str]:
        """
        List additional 2D HDF output variables known to HEC-RAS plan files.

        Returns:
            List[str]: Variable names accepted by
                ``HDF Additional Output Variable=...`` plan-file entries.
        """
        return list(RasPlan.HDF_ADDITIONAL_OUTPUT_VARIABLES)

    @staticmethod
    @log_call
    def list_hdf_output_setting_profiles() -> Dict[str, Dict[str, Any]]:
        """
        List named HDF write-parameter profiles.

        Returns:
            Dict[str, Dict[str, Any]]: Profile names mapped to write parameters.
        """
        return {
            name: dict(settings)
            for name, settings in RasPlan.HDF_OUTPUT_SETTING_PROFILES.items()
        }

    @staticmethod
    def _resolve_plan_file_path(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None
    ) -> Optional[Path]:
        """
        Resolve a plan number or explicit path to a plan file path.
        """
        if isinstance(plan_number_or_path, (str, Path)):
            plan_file_path = Path(plan_number_or_path)
            if plan_file_path.is_file():
                return plan_file_path

        ras_obj = ras_object or ras
        return RasPlan.get_plan_path(plan_number_or_path, ras_obj)

    @staticmethod
    def _format_hdf_parameter_value(value: Any) -> str:
        """
        Convert Python values to HEC-RAS plan-file HDF parameter values.
        """
        if isinstance(value, bool):
            return "-1" if value else "0"
        return str(value)

    @staticmethod
    def _find_hdf_insert_index(lines: List[str]) -> int:
        """
        Find a stable insertion point for HDF write parameters.
        """
        for i, line in enumerate(lines):
            if line.startswith("Calibration Method="):
                return i

        insert_index = None
        for i, line in enumerate(lines):
            if line.startswith("HDF "):
                insert_index = i + 1

        if insert_index is not None:
            return insert_index

        for i, line in enumerate(lines):
            if line.startswith("Write HDF5 File="):
                return i
            if line.startswith("UNET "):
                insert_index = i + 1

        return insert_index if insert_index is not None else len(lines)

    @staticmethod
    def _parse_restart_flag(raw_value: Optional[str]) -> Optional[bool]:
        """
        Parse HEC-RAS integer/string flags used by restart-output settings.
        """
        if raw_value is None:
            return None
        value = str(raw_value).strip().lower()
        if value in {"-1", "1", "true"}:
            return True
        if value in {"0", "false"}:
            return False
        return None

    @staticmethod
    def _coerce_restart_number(raw_value: Optional[Any]) -> Optional[Any]:
        """
        Convert numeric restart-output values while preserving nonnumeric text.
        """
        if raw_value is None:
            return None
        value = str(raw_value).strip()
        if value == "":
            return None
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number

    @staticmethod
    def _format_restart_number(value: Any) -> str:
        """
        Format restart-output hour values without unnecessary decimals.
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            raise ValueError("Restart hour values must be numeric, not boolean")
        if isinstance(value, Number):
            number = float(value)
            return str(int(number)) if number.is_integer() else str(number)
        return str(value).strip()

    @staticmethod
    def _parse_restart_ic_time(raw_value: Optional[str]) -> Dict[str, Optional[Any]]:
        """
        Parse the HEC-RAS IC Time line into relative-hour and fixed-date parts.
        """
        result = {
            "save_time_hours": None,
            "save_date": None,
            "save_time": None,
            "save_datetime": None,
        }
        if raw_value is None:
            return result

        parts = [part.strip() for part in str(raw_value).strip().split(",")]
        while len(parts) < 3:
            parts.append("")

        hours, save_date, save_time = parts[:3]
        result["save_time_hours"] = RasPlan._coerce_restart_number(hours)
        result["save_date"] = save_date or None
        result["save_time"] = save_time or None
        if result["save_date"] and result["save_time"]:
            result["save_datetime"] = f"{result['save_date']},{result['save_time']}"
        return result

    @staticmethod
    def _format_restart_datetime(value: Union[str, Tuple[str, str], datetime]) -> Tuple[str, str]:
        """
        Format a fixed restart-save datetime as HEC-RAS date and hhmm strings.
        """
        if isinstance(value, datetime):
            return value.strftime("%d%b%Y").upper(), value.strftime("%H%M")

        if isinstance(value, (tuple, list)) and len(value) == 2:
            save_date, save_time = value
            return str(save_date).strip().upper(), str(save_time).strip()

        if isinstance(value, str):
            raw = value.strip().lstrip(",")
            parts = [part for part in re.split(r"[,\s]+", raw) if part]
            if len(parts) == 2:
                return parts[0].upper(), parts[1]

        raise ValueError(
            "save_datetime must be a datetime, a (date, time) pair, or "
            "a 'DDMMMYYYY,hhmm' string"
        )

    @staticmethod
    def _find_restart_output_insert_index(lines: List[str]) -> int:
        """
        Find a stable insertion point for restart-output plan settings.
        """
        for i, line in enumerate(lines):
            if line.startswith("DSS File="):
                return i + 1

        for i, line in enumerate(lines):
            if (
                line.startswith("Echo Input=")
                or line.startswith("Echo Parameters=")
                or line.startswith("Echo Output=")
                or line.startswith("Write Detailed=")
                or line.startswith("HDF ")
                or line.startswith("Calibration Method=")
                or line.startswith("Met Data")
                or line.startswith("Sim Duration")
            ):
                return i

        return len(lines)

    @staticmethod
    def _expected_restart_filename(plan_file_path: Path, save_date: Optional[str], save_time: Optional[str]) -> Optional[str]:
        """
        Return the HEC-RAS restart filename for a fixed date/time save.
        """
        if not save_date or not save_time:
            return None
        return f"{plan_file_path.name}.{save_date} {save_time}.rst"

    @staticmethod
    @log_call
    def get_restart_output_settings(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None
    ) -> Dict[str, Optional[Any]]:
        """
        Get restart/Hot Start output settings from a HEC-RAS plan file.

        HEC-RAS stores restart-file creation settings in the plan file using
        ``Write IC File`` keys. These settings control writing restart files.
        They do not control whether a subsequent unsteady-flow file uses a
        restart file; use ``RasUnsteady.get_restart_settings()`` and
        ``RasUnsteady.set_restart_settings()`` for that separate usage setting.

        Args:
            plan_number_or_path: Plan number or explicit plan-file path.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            Dict[str, Optional[Any]]: Parsed restart-output settings, including
                raw HEC-RAS keys for auditability.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        raw_values = {
            plan_key: None
            for plan_key in RasPlan.RESTART_OUTPUT_PARAMETER_KEYS.values()
        }
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return {
                "enabled": None,
                "save_at_fixed_datetime": None,
                "save_time_hours": None,
                "save_date": None,
                "save_time": None,
                "save_datetime": None,
                "recurrence_interval_hours": None,
                "write_at_sim_end": None,
                "expected_filename": None,
                "output_filename_pattern": RasPlan.RESTART_OUTPUT_FILE_PATTERN,
                "raw": raw_values,
                "compatibility_note": RasPlan.RESTART_OUTPUT_COMPATIBILITY_NOTE,
            }

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                for line in file:
                    if "=" not in line:
                        continue
                    key, raw_value = line.split("=", 1)
                    key = key.strip()
                    if key in raw_values:
                        raw_values[key] = raw_value.strip()

            ic_time = RasPlan._parse_restart_ic_time(raw_values["IC Time"])
            expected_filename = RasPlan._expected_restart_filename(
                plan_file_path,
                ic_time["save_date"],
                ic_time["save_time"],
            )

            return {
                "enabled": RasPlan._parse_restart_flag(raw_values["Write IC File"]),
                "save_at_fixed_datetime": RasPlan._parse_restart_flag(
                    raw_values["Write IC File at Fixed DateTime"]
                ),
                "save_time_hours": ic_time["save_time_hours"],
                "save_date": ic_time["save_date"],
                "save_time": ic_time["save_time"],
                "save_datetime": ic_time["save_datetime"],
                "recurrence_interval_hours": RasPlan._coerce_restart_number(
                    raw_values["Write IC File Reoccurance"]
                ),
                "write_at_sim_end": RasPlan._parse_restart_flag(
                    raw_values["Write IC File at Sim End"]
                ),
                "expected_filename": expected_filename,
                "output_filename_pattern": RasPlan.RESTART_OUTPUT_FILE_PATTERN,
                "raw": raw_values,
                "compatibility_note": RasPlan.RESTART_OUTPUT_COMPATIBILITY_NOTE,
            }
        except IOError as e:
            logger.error(f"Error reading restart output settings from {plan_file_path}: {e}")
            raise

    @staticmethod
    @log_call
    def set_restart_output_settings(
        plan_number_or_path: Union[str, Number, Path],
        enabled: bool = True,
        save_time_hours: Optional[Union[int, float, str]] = None,
        save_datetime: Optional[Union[str, Tuple[str, str], datetime]] = None,
        recurrence_interval_hours: Optional[Union[int, float, str]] = None,
        write_at_sim_end: bool = False,
        ras_object=None
    ) -> bool:
        """
        Configure a plan to write HEC-RAS restart/Hot Start files.

        HEC-RAS stores these output-save settings in the plan file as
        ``Write IC File`` keys. A restart file written by a run is named by
        HEC-RAS from the project name, plan number, and save time
        (``ProjectName.p##.DDMMMYYYY hhmm.rst``); the output filename itself is
        not an independent plan-file field in HEC-RAS 5.x through 7.0.

        Args:
            plan_number_or_path: Plan number or explicit plan-file path.
            enabled: Enable restart output. False clears save timing settings.
            save_time_hours: First save time in hours from simulation start.
            save_datetime: First save as ``datetime``, ``(DDMMMYYYY, hhmm)``,
                or ``"DDMMMYYYY,hhmm"``.
            recurrence_interval_hours: Hours between subsequent restart writes.
            write_at_sim_end: Also write a restart file at the final time step.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            bool: True when the plan file was updated or already current.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if save_time_hours is not None and save_datetime is not None:
            raise ValueError("Specify either save_time_hours or save_datetime, not both")
        if recurrence_interval_hours is not None and save_time_hours is None and save_datetime is None:
            raise ValueError("recurrence_interval_hours requires save_time_hours or save_datetime")
        if enabled and save_time_hours is None and save_datetime is None and not write_at_sim_end:
            raise ValueError(
                "Enable restart output with save_time_hours, save_datetime, "
                "or write_at_sim_end=True"
            )

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return False

        if not enabled:
            line_values = {
                "Write IC File": " 0 ",
                "Write IC File at Fixed DateTime": "0",
                "IC Time": ",,",
                "Write IC File Reoccurance": "",
                "Write IC File at Sim End": "0",
            }
        else:
            fixed_datetime = save_datetime is not None
            if fixed_datetime:
                save_date, save_time = RasPlan._format_restart_datetime(save_datetime)
                ic_time = f",{save_date},{save_time}"
            elif save_time_hours is not None:
                ic_time = f"{RasPlan._format_restart_number(save_time_hours)},,"
            else:
                ic_time = ",,"

            line_values = {
                "Write IC File": " 1 ",
                "Write IC File at Fixed DateTime": "-1" if fixed_datetime else "0",
                "IC Time": ic_time,
                "Write IC File Reoccurance": RasPlan._format_restart_number(
                    recurrence_interval_hours
                ),
                "Write IC File at Sim End": "-1" if write_at_sim_end else "0",
            }

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            original_lines = list(lines)

            managed_keys = set(line_values)
            existing_indexes = [
                i for i, line in enumerate(lines)
                if "=" in line and line.split("=", 1)[0].strip() in managed_keys
            ]
            insert_index = (
                min(existing_indexes)
                if existing_indexes
                else RasPlan._find_restart_output_insert_index(lines)
            )

            retained_lines = []
            adjusted_insert_index = 0
            for i, line in enumerate(lines):
                key = line.split("=", 1)[0].strip() if "=" in line else None
                if i < insert_index and key not in managed_keys:
                    adjusted_insert_index += 1
                if key in managed_keys:
                    continue
                retained_lines.append(line)

            new_block = [
                f"{key}={line_values[key]}\n"
                for key in RasPlan.RESTART_OUTPUT_PARAMETER_KEYS.values()
            ]
            retained_lines[adjusted_insert_index:adjusted_insert_index] = new_block
            lines = retained_lines

            if lines == original_lines:
                logger.debug(
                    "Restart output settings already current in plan file: %s",
                    plan_file_path.name,
                )
                return True

            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            if hasattr(ras_obj, "get_plan_entries"):
                ras_obj.plan_df = ras_obj.get_plan_entries()

            logger.info(f"Updated restart output settings in plan file: {plan_file_path.name}")
            return True
        except IOError as e:
            logger.error(f"Error updating restart output settings in {plan_file_path}: {e}")
            return False

    @staticmethod
    @log_call
    def get_hdf_write_parameters(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None
    ) -> Dict[str, Optional[Any]]:
        """
        Get HDF write parameters configured in a HEC-RAS plan file.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            Dict[str, Optional[Any]]: HDF write settings keyed by ras-commander
                parameter name. Missing settings are returned as None.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return {key: None for key in RasPlan.HDF_WRITE_PARAMETER_KEYS}

        values = {key: None for key in RasPlan.HDF_WRITE_PARAMETER_KEYS}
        plan_key_to_api_key = {
            plan_key: api_key
            for api_key, plan_key in RasPlan.HDF_WRITE_PARAMETER_KEYS.items()
        }

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                for line in file:
                    if "=" not in line:
                        continue
                    key, raw_value = line.split("=", 1)
                    api_key = plan_key_to_api_key.get(key.strip())
                    if not api_key:
                        continue
                    raw_value = raw_value.strip()
                    if api_key in {"write_warmup", "write_time_slices", "hdf_flush", "use_max_rows"}:
                        values[api_key] = raw_value == "-1"
                    else:
                        try:
                            values[api_key] = int(raw_value)
                        except ValueError:
                            values[api_key] = raw_value
            return values
        except IOError as e:
            logger.error(f"Error reading HDF write parameters from {plan_file_path}: {e}")
            return values

    @staticmethod
    @log_call
    def get_hdf_output_options(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None
    ) -> Dict[str, Optional[Any]]:
        """
        Get HDF output options configured in a HEC-RAS plan file.

        Alias for ``get_hdf_write_parameters()`` using output-control naming.
        """
        return RasPlan.get_hdf_write_parameters(
            plan_number_or_path,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def set_hdf_write_parameters(
        plan_number_or_path: Union[str, Number, Path],
        write_warmup: Optional[bool] = None,
        write_time_slices: Optional[bool] = None,
        hdf_flush: Optional[bool] = None,
        compression: Optional[int] = None,
        chunk_size_mb: Optional[int] = None,
        spatial_parts: Optional[int] = None,
        use_max_rows: Optional[bool] = None,
        fixed_rows: Optional[int] = None,
        ras_object=None
    ) -> bool:
        """
        Set HEC-RAS HDF5 write parameters in a plan file.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            write_warmup: Write warmup time steps to output file.
            write_time_slices: Write time-sliced steps in addition to basic time steps.
            hdf_flush: Commit writes every time step for crash diagnostics.
            compression: Gzip/deflate compression level, 1 to 9.
            chunk_size_mb: Maximum chunk size in MB.
            spatial_parts: Number of spatial column groups.
            use_max_rows: Use maximum possible time rows per chunk.
            fixed_rows: Fixed number of time rows when ``use_max_rows`` is False.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            bool: True when the plan file was updated, False on error.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if compression is not None and not 1 <= compression <= 9:
            raise ValueError("compression must be between 1 and 9")
        if chunk_size_mb is not None and chunk_size_mb < 1:
            raise ValueError("chunk_size_mb must be >= 1")
        if spatial_parts is not None and spatial_parts < 1:
            raise ValueError("spatial_parts must be >= 1")
        if fixed_rows is not None and fixed_rows < 1:
            raise ValueError("fixed_rows must be >= 1")

        requested = {
            "write_warmup": write_warmup,
            "write_time_slices": write_time_slices,
            "hdf_flush": hdf_flush,
            "compression": compression,
            "chunk_size_mb": chunk_size_mb,
            "spatial_parts": spatial_parts,
            "use_max_rows": use_max_rows,
            "fixed_rows": fixed_rows,
        }
        requested = {
            key: value for key, value in requested.items()
            if value is not None
        }
        if not requested:
            logger.debug("No HDF write parameters requested")
            return True

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return False

        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
            original_lines = list(lines)

            updated_keys = set()
            for i, line in enumerate(lines):
                if "=" not in line:
                    continue
                line_key = line.split("=", 1)[0].strip()
                for api_key, plan_key in RasPlan.HDF_WRITE_PARAMETER_KEYS.items():
                    if line_key == plan_key and api_key in requested:
                        value = RasPlan._format_hdf_parameter_value(requested[api_key])
                        lines[i] = f"{plan_key}= {value} \n"
                        updated_keys.add(api_key)

            missing_keys = [key for key in requested if key not in updated_keys]
            if missing_keys:
                insert_index = RasPlan._find_hdf_insert_index(lines)
                new_lines = []
                for api_key in RasPlan.HDF_WRITE_PARAMETER_KEYS:
                    if api_key not in missing_keys:
                        continue
                    plan_key = RasPlan.HDF_WRITE_PARAMETER_KEYS[api_key]
                    value = RasPlan._format_hdf_parameter_value(requested[api_key])
                    new_lines.append(f"{plan_key}= {value} \n")
                lines[insert_index:insert_index] = new_lines

            if lines == original_lines:
                logger.debug("HDF write parameters already current in plan file: %s", plan_file_path.name)
                return True

            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger.info(f"Updated HDF write parameters in plan file: {plan_file_path.name}")
            return True

        except IOError as e:
            logger.error(f"Error updating HDF write parameters in {plan_file_path}: {e}")
            return False

    @staticmethod
    @log_call
    def set_hdf_output_options(
        plan_number_or_path: Union[str, Number, Path],
        write_warmup: Optional[bool] = None,
        write_time_slices: Optional[bool] = None,
        hdf_flush: Optional[bool] = None,
        compression: Optional[int] = None,
        chunk_size_mb: Optional[int] = None,
        spatial_parts: Optional[int] = None,
        use_max_rows: Optional[bool] = None,
        fixed_rows: Optional[int] = None,
        ras_object=None
    ) -> bool:
        """
        Set HDF output options in a HEC-RAS plan file.

        Alias for ``set_hdf_write_parameters()`` using output-control naming.
        """
        return RasPlan.set_hdf_write_parameters(
            plan_number_or_path,
            write_warmup=write_warmup,
            write_time_slices=write_time_slices,
            hdf_flush=hdf_flush,
            compression=compression,
            chunk_size_mb=chunk_size_mb,
            spatial_parts=spatial_parts,
            use_max_rows=use_max_rows,
            fixed_rows=fixed_rows,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def apply_hdf_output_profile(
        plan_number_or_path: Union[str, Number, Path],
        profile: str = "balanced",
        additional_variables: Optional[List[str]] = None,
        ras_object=None
    ) -> bool:
        """
        Apply a named HDF write-parameter profile and optional output variables.

        Args:
            plan_number_or_path: Plan number or path to the plan file.
            profile: One of ``balanced``, ``speed``, ``size``, or ``nas``.
            additional_variables: Optional additional HDF output variables to enable.
            ras_object: Optional RAS project object. If None, uses global ``ras``.

        Returns:
            bool: True when all requested updates succeeded.
        """
        profile_key = profile.lower()
        if profile_key not in RasPlan.HDF_OUTPUT_SETTING_PROFILES:
            valid = ", ".join(sorted(RasPlan.HDF_OUTPUT_SETTING_PROFILES))
            raise ValueError(f"Unknown HDF output profile '{profile}'. Valid profiles: {valid}")

        settings = RasPlan.HDF_OUTPUT_SETTING_PROFILES[profile_key]
        success = RasPlan.set_hdf_write_parameters(
            plan_number_or_path,
            ras_object=ras_object,
            **settings
        )

        for variable in additional_variables or []:
            success = (
                RasPlan.set_hdf_output_variable(
                    plan_number_or_path,
                    variable,
                    enabled=True,
                    ras_object=ras_object
                )
                and success
            )

        return success

    @staticmethod
    @log_call
    def use_optimal_hdf_settings(
        plan_number_or_path: Union[str, Number, Path],
        profile: str = "balanced",
        additional_variables: Optional[List[str]] = None,
        ras_object=None
    ) -> bool:
        """
        Apply ras-commander's recommended HDF write settings to a plan file.

        This is an alias for ``apply_hdf_output_profile()`` using the balanced
        profile by default.
        """
        return RasPlan.apply_hdf_output_profile(
            plan_number_or_path,
            profile=profile,
            additional_variables=additional_variables,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def set_hdf_output_variable(
        plan_number_or_path: Union[str, Number, Path],
        variable: str,
        enabled: bool = True,
        ras_object=None
    ) -> bool:
        """
        Enable or disable one additional HDF output variable in a plan file.
        """
        if enabled:
            return RasPlan.add_hdf_output_variable(
                plan_number_or_path,
                variable,
                ras_object=ras_object
            )
        return RasPlan.remove_hdf_output_variable(
            plan_number_or_path,
            variable,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def enable_hdf_output_variable(
        plan_number_or_path: Union[str, Number, Path],
        variable_name: str,
        ras_object=None
    ) -> bool:
        """
        Enable one additional HDF output variable in a plan file.
        """
        return RasPlan.add_hdf_output_variable(
            plan_number_or_path,
            variable_name,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def disable_hdf_output_variable(
        plan_number_or_path: Union[str, Number, Path],
        variable_name: str,
        ras_object=None
    ) -> bool:
        """
        Disable one additional HDF output variable in a plan file.
        """
        return RasPlan.remove_hdf_output_variable(
            plan_number_or_path,
            variable_name,
            ras_object=ras_object
        )

    @staticmethod
    @log_call
    def set_hdf_output_variables(
        plan_number_or_path: Union[str, Number, Path],
        variables: List[str],
        enabled: bool = True,
        ras_object=None
    ) -> bool:
        """
        Enable or disable multiple additional HDF output variables in a plan file.
        """
        success = True
        for variable in variables:
            success = (
                RasPlan.set_hdf_output_variable(
                    plan_number_or_path,
                    variable,
                    enabled=enabled,
                    ras_object=ras_object
                )
                and success
            )
        return success

    @staticmethod
    @log_call
    def add_hdf_output_variable(
        plan_number_or_path: Union[str, Number, Path],
        variable: str,
        ras_object=None
    ) -> bool:
        """
        Add an HDF output variable to a HEC-RAS plan file.

        This enables additional output variables in the HDF results file, such as
        Face Flow, which is needed for discharge-weighted velocity calculations.

        Args:
            plan_number_or_path (Union[str, Number, Path]): The plan number or path to the plan file.
            variable (str): The variable name to add (e.g., "Face Flow", "Face Shear Stress").
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            bool: True if variable was added or already exists, False on error.

        Supported Variables:
            - "Face Flow" - Flow rate across each face (needed for discharge-weighted velocity)
            - "Face Shear Stress" - Shear stress at each face
            - "Face Cumulative Volume" - Cumulative volume through each face
            - "Cell Cumulative Precipitation" - Cumulative precipitation per cell
            - "Cell Courant" - Courant number per cell

        Example:
            >>> # Enable Face Flow output before running a plan
            >>> RasPlan.add_hdf_output_variable('02', 'Face Flow')
            >>> RasCmdr.compute_plan('02')
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return False

        try:
            # Read the file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            # Check if this variable already exists
            target_line = f"HDF Additional Output Variable={variable}"
            for line in lines:
                if line.strip() == target_line:
                    logger.debug("HDF output variable %r already exists in plan", variable)
                    return True

            # Find the best location to insert (near other HDF settings)
            insert_index = None
            for i, line in enumerate(lines):
                if line.startswith("HDF Compression="):
                    # Insert before HDF Compression
                    insert_index = i
                    break
                elif line.startswith("HDF "):
                    # Track last HDF line as fallback
                    insert_index = i + 1

            # If no HDF settings found, find Write HDF5 File or end of UNET settings
            if insert_index is None:
                for i, line in enumerate(lines):
                    if line.startswith("Write HDF5 File="):
                        insert_index = i
                        break
                    elif line.startswith("UNET "):
                        insert_index = i + 1

            # Fallback to end of file
            if insert_index is None:
                insert_index = len(lines)

            # Insert the new variable
            lines.insert(insert_index, f"{target_line}\n")

            # Write the updated content back to the file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(lines)

            logger.info(f"Added HDF output variable '{variable}' to plan file: {plan_file_path.name}")
            return True

        except IOError as e:
            logger.error(f"Error adding HDF output variable to plan file {plan_file_path}: {e}")
            return False

    @staticmethod
    @log_call
    def get_hdf_output_variables(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None
    ) -> List[str]:
        """
        Get list of additional HDF output variables configured in a plan file.

        Args:
            plan_number_or_path (Union[str, Number, Path]): The plan number or path to the plan file.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            List[str]: List of variable names configured for HDF output.

        Example:
            >>> vars = RasPlan.get_hdf_output_variables('02')
            >>> print(vars)  # ['Face Flow', 'Face Shear Stress']
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return []

        variables = []
        try:
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                for line in file:
                    if line.startswith("HDF Additional Output Variable="):
                        var_name = line.split("=", 1)[1].strip()
                        variables.append(var_name)

            logger.debug("Found %d HDF output variables in plan", len(variables))
            return variables

        except IOError as e:
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            return []

    @staticmethod
    @log_call
    def get_plan_flow_type(plan_number: str, ras_object=None) -> str:
        """
        Get flow type for a plan from plan metadata (fast, no HDF required).

        Args:
            plan_number: Plan number (e.g., "01", "08")
            ras_object: Optional RAS object instance

        Returns:
            str: 'Steady', 'Unsteady', or 'Unknown'

        Notes:
            - Uses plan file metadata (already parsed by ras-commander)
            - Deterministic: plans with unsteady_number are Unsteady, others are Steady
            - Does NOT require HDF file to exist
            - Much faster than HDF inspection (reads from memory)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        try:
            plan_num = RasUtils.normalize_ras_number(plan_number)
            plan_row = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_num]

            if plan_row.empty:
                logger.debug(f"Plan {plan_num} not found in plan_df")
                return 'Unknown'

            # Use flow_type column if available (preferred)
            if 'flow_type' in plan_row.columns:
                flow_type = plan_row.iloc[0]['flow_type']
                logger.debug(f"Plan {plan_num}: {flow_type} (from plan_df)")
                return flow_type

            if 'unsteady_number' not in plan_row.columns:
                logger.debug(
                    "Plan %s flow type unknown; plan_df missing unsteady_number column",
                    plan_num,
                )
                return 'Unknown'

            # Fallback: determine from unsteady_number
            import pandas as pd
            unsteady_num = plan_row.iloc[0]['unsteady_number']
            flow_type = 'Unsteady' if pd.notna(unsteady_num) else 'Steady'
            logger.debug(f"Plan {plan_num}: {flow_type} (from unsteady_number)")
            return flow_type

        except Exception:
            logger.debug("Could not determine flow type for plan %s", plan_number, exc_info=True)
            return 'Unknown'

    @staticmethod
    @log_call
    def is_plan_steady_state(plan_number: str, ras_object=None) -> bool:
        """
        Check if a plan is steady state.

        Args:
            plan_number: Plan number (e.g., "01", "08")
            ras_object: Optional RAS object instance

        Returns:
            bool: True if steady state, False otherwise
        """
        flow_type = RasPlan.get_plan_flow_type(plan_number, ras_object)
        return flow_type == 'Steady'

    @staticmethod
    @log_call
    def remove_hdf_output_variable(
        plan_number_or_path: Union[str, Number, Path],
        variable: str,
        ras_object=None
    ) -> bool:
        """
        Remove an HDF output variable from a HEC-RAS plan file.

        Args:
            plan_number_or_path (Union[str, Number, Path]): The plan number or path to the plan file.
            variable (str): The variable name to remove.
            ras_object (Optional[RasPrj]): The RAS project object. If None, uses the global 'ras' object.

        Returns:
            bool: True if variable was removed, False if not found or on error.

        Example:
            >>> RasPlan.remove_hdf_output_variable('02', 'Face Flow')
        """
        logger = get_logger(__name__)
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        plan_file_path = RasPlan._resolve_plan_file_path(plan_number_or_path, ras_obj)
        if not plan_file_path or not plan_file_path.exists():
            logger.error(f"Plan file not found: {plan_number_or_path}")
            return False

        try:
            # Read the file
            with open(plan_file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()

            # Find and remove the variable line
            target_line = f"HDF Additional Output Variable={variable}"
            new_lines = []
            removed = False
            for line in lines:
                if line.strip() == target_line:
                    removed = True
                else:
                    new_lines.append(line)

            if not removed:
                logger.debug("HDF output variable %r not found in plan", variable)
                return False

            # Write the updated content back to the file
            with open(plan_file_path, 'w', encoding='utf-8', errors='replace') as file:
                file.writelines(new_lines)

            logger.info(
                "Removed HDF output variable %r from plan file: %s",
                variable,
                plan_file_path.name,
            )
            return True

        except IOError as e:
            logger.error(f"Error removing HDF output variable from plan file {plan_file_path}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Delete and Renumber Operations
    # NOTE: These methods are awaiting maintainer review and testing before release
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Private helpers for deduplication
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_component_path(
        component_number: Union[str, Number],
        df_attr: str,
        number_column: str,
        prj_entry_type: str,
        file_prefix: str,
        ras_object=None,
    ) -> Optional[Path]:
        """
        Generic path resolution helper for flow, unsteady, and geometry components.

        Resolves a component number to its full filesystem path by looking up the
        component DataFrame on the ras object.

        Parameters:
            component_number: The component number (e.g., '01', 1)
            df_attr: Name of the DataFrame attribute on ras_obj (e.g., 'flow_df')
            number_column: Column name for the number (e.g., 'flow_number')
            prj_entry_type: PRJ entry type for get_prj_entries() (e.g., 'Flow')
            file_prefix: File prefix letter (e.g., 'f', 'u', 'g')
            ras_object: Optional RAS object instance.

        Returns:
            Optional[Path]: Full path if found, None otherwise.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        component_number = RasUtils.normalize_ras_number(component_number)

        # Refresh the relevant DataFrame
        setattr(ras_obj, df_attr, ras_obj.get_prj_entries(prj_entry_type))
        df = getattr(ras_obj, df_attr)

        matching = df[df[number_column] == component_number]
        if not matching.empty:
            full_path = matching['full_path'].iloc[0]
            if full_path:
                return Path(full_path)
            # No fallback here - callers (e.g., get_geom_path) add their own if needed
            return None
        else:
            return None

    @staticmethod
    def _clone_component(
        template_number: Union[str, Number],
        component_type: str,
        file_prefix: str,
        df_attr: str,
        number_column: str,
        new_title: Optional[str] = None,
        title_keyword: str = 'Flow Title',
        copy_hdf: bool = False,
        ras_object=None,
    ) -> str:
        """
        Generic clone helper for unsteady, steady, and geometry components.

        Clones a component file, optionally updates its title, optionally copies
        the companion HDF file, updates the PRJ file, and refreshes DataFrames.

        Parameters:
            template_number: Number of the template to clone (e.g., '01')
            component_type: PRJ entry type (e.g., 'Flow', 'Unsteady', 'Geom')
            file_prefix: File prefix letter (e.g., 'f', 'u', 'g')
            df_attr: DataFrame attribute name (e.g., 'flow_df')
            number_column: Column for the component number (e.g., 'flow_number')
            new_title: Optional new title (max 32 chars). None keeps original.
            title_keyword: Keyword in file for title line (e.g., 'Flow Title')
            copy_hdf: Whether to copy the companion .hdf file.
            ras_object: Optional RAS object instance.

        Returns:
            str: The new component number.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        template_number = RasUtils.normalize_ras_number(template_number)

        # Validate new_title length if provided
        if new_title is not None and len(new_title) > 32:
            raise ValueError(
                f"{title_keyword} must be 32 characters or less. "
                f"Got {len(new_title)} characters: '{new_title}'"
            )

        # Refresh the relevant DataFrame
        setattr(ras_obj, df_attr, ras_obj.get_prj_entries(component_type))
        df = getattr(ras_obj, df_attr)

        new_num = RasPlan.get_next_number(df[number_column])
        template_path = ras_obj.project_folder / f"{ras_obj.project_name}.{file_prefix}{template_number}"
        new_path = ras_obj.project_folder / f"{ras_obj.project_name}.{file_prefix}{new_num}"

        def update_title(lines):
            """Update title line in cloned file."""
            title_pattern = re.compile(rf'^{re.escape(title_keyword)}=(.*)$', re.IGNORECASE)
            for i, line in enumerate(lines):
                if title_pattern.match(line.strip()):
                    lines[i] = f"{title_keyword}={new_title[:32]}\n"
                    break
            return lines

        # Clone the file (with optional title update)
        if new_title is not None:
            RasUtils.clone_file(template_path, new_path, update_title)
        else:
            RasUtils.clone_file(template_path, new_path)

        # Copy companion HDF if requested
        if copy_hdf:
            template_hdf = ras_obj.project_folder / f"{ras_obj.project_name}.{file_prefix}{template_number}.hdf"
            new_hdf = ras_obj.project_folder / f"{ras_obj.project_name}.{file_prefix}{new_num}.hdf"
            if template_hdf.is_file():
                if file_prefix == 'g':
                    RasUtils.clone_file(template_hdf, new_hdf)
                else:
                    shutil.copy(template_hdf, new_hdf)

        # Update .prj file
        RasUtils.update_project_file(ras_obj.prj_file, component_type, new_num, ras_object=ras_obj)

        # Re-initialize and refresh DataFrames
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        return new_num

    @staticmethod
    def _delete_component(
        component_number: Union[str, Number],
        component_type: str,
        file_prefix: str,
        df_attr: str,
        number_column: str,
        associated_suffixes: List[str],
        reference_check_fn=None,
        force: bool = False,
        permanent_delete: bool = False,
        ras_object=None,
    ) -> Optional[Path]:
        """
        Generic delete helper for geometry, unsteady, and steady components.

        Verifies the component exists, optionally checks for referencing plans,
        removes the component files (backing up or permanently deleting),
        removes the PRJ entry, and refreshes all DataFrames.

        Parameters:
            component_number: Number to delete (e.g., '06')
            component_type: PRJ entry type (e.g., 'Geom', 'Unsteady', 'Flow')
            file_prefix: File prefix letter (e.g., 'g', 'u', 'f')
            df_attr: DataFrame attribute name (e.g., 'geom_df')
            number_column: Column for the component number (e.g., 'geom_number')
            associated_suffixes: List of file suffixes to delete (e.g., ['.hdf', ''] where
                '' means the base file itself). Each suffix is appended to
                "{project_name}.{prefix}{number}".
            reference_check_fn: Optional callable(ras_obj, number) -> pd.DataFrame.
                If it returns a non-empty DataFrame, deletion is blocked unless force=True.
            force: If True, skip reference checks.
            permanent_delete: If True, permanently delete files. If False (default),
                move files to {project_folder}/Backup/{timestamp}_{label}/.
            ras_object: Optional RAS object instance.

        Returns:
            Optional[Path]: Path to backup folder if files were backed up, None if
                permanently deleted or no files existed.

        Raises:
            ValueError: If component doesn't exist or is referenced and force=False.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        component_number = RasUtils.normalize_ras_number(component_number)

        # Refresh and verify existence
        if component_type in ('Flow', 'Unsteady', 'Geom'):
            if component_type == 'Geom':
                ras_obj.geom_df = ras_obj.get_geom_entries()
            elif component_type == 'Unsteady':
                ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            elif component_type == 'Flow':
                ras_obj.flow_df = ras_obj.get_flow_entries()

        df = getattr(ras_obj, df_attr)
        if component_number not in df[number_column].values:
            raise ValueError(f"{component_type} {component_number} does not exist in the project")

        # Check for referencing plans
        if not force and reference_check_fn is not None:
            referencing = reference_check_fn(ras_obj, component_number)
            if not referencing.empty:
                plan_nums = referencing['plan_number'].tolist()
                raise ValueError(
                    f"Cannot delete {component_type.lower()} {component_number}: "
                    f"referenced by plan(s) {plan_nums}. Use force=True to delete anyway."
                )

        # Build list of files to remove
        base = ras_obj.project_folder / f"{ras_obj.project_name}"
        files_to_remove = [
            Path(f"{base}.{file_prefix}{component_number}{suffix}")
            for suffix in associated_suffixes
        ]

        if permanent_delete:
            backup_dir = None
            for file_path in files_to_remove:
                if file_path.exists():
                    file_path.unlink()
                    logger.debug(f"Permanently deleted {file_path.name}")
        else:
            label = f"deleted_{file_prefix}{component_number}"
            backup_dir = RasUtils.backup_files(
                files_to_remove, ras_obj.project_folder, label
            )

        # Remove from .prj
        RasUtils.remove_prj_entry(ras_obj.prj_file, component_type, component_number, ras_object=ras_obj)

        # Refresh all DataFrames
        RasPlan._refresh_all_dataframes(ras_obj)

        return backup_dir

    @staticmethod
    def _renumber_component(
        old_number: Union[str, Number],
        new_number: Union[str, Number],
        component_type: str,
        file_prefix: str,
        df_attr: str,
        number_column: str,
        companion_extensions: List[str],
        plan_ref_key: str,
        plan_ref_column: str,
        plan_ref_filter_fn=None,
        ras_object=None,
    ) -> str:
        """
        Generic renumber helper for geometry, unsteady, and steady components.

        Renames files, updates the PRJ entry, and updates all plan files that
        reference this component.

        Parameters:
            old_number: Current component number (e.g., '06')
            new_number: New component number (e.g., '02')
            component_type: PRJ entry type (e.g., 'Geom', 'Unsteady', 'Flow')
            file_prefix: File prefix letter (e.g., 'g', 'u', 'f')
            df_attr: DataFrame attribute name (e.g., 'geom_df')
            number_column: Column for the component number (e.g., 'geom_number')
            companion_extensions: Additional file extensions to rename (e.g., ['.hdf'] for .g01.hdf).
                The base file (no extension) is always included.
            plan_ref_key: Key in plan files to update (e.g., 'Geom File', 'Flow File')
            plan_ref_column: Column in plan_df to match against old_number
                (e.g., 'Geom File', 'unsteady_number', 'Flow File')
            plan_ref_filter_fn: Optional callable(row) -> bool for additional filtering
                of which plan rows should be updated. If None, all matching rows are updated.
            ras_object: Optional RAS object instance.

        Returns:
            str: The new component number.

        Raises:
            ValueError: If old doesn't exist or new already exists.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        old_number = RasUtils.normalize_ras_number(old_number)
        new_number = RasUtils.normalize_ras_number(new_number)

        # Refresh and verify
        if component_type == 'Geom':
            ras_obj.geom_df = ras_obj.get_geom_entries()
        elif component_type == 'Unsteady':
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        elif component_type == 'Flow':
            ras_obj.flow_df = ras_obj.get_flow_entries()

        df = getattr(ras_obj, df_attr)
        if old_number not in df[number_column].values:
            raise ValueError(f"{component_type} {old_number} does not exist in the project")
        if new_number in df[number_column].values:
            raise ValueError(f"{component_type} {new_number} already exists in the project")

        # Rename files: base file + companion extensions
        base = ras_obj.project_folder / f"{ras_obj.project_name}"
        rename_pairs = [
            (Path(f"{base}.{file_prefix}{old_number}"), Path(f"{base}.{file_prefix}{new_number}")),
        ]
        for ext in companion_extensions:
            rename_pairs.append(
                (Path(f"{base}.{file_prefix}{old_number}{ext}"), Path(f"{base}.{file_prefix}{new_number}{ext}"))
            )

        for old_path, new_path in rename_pairs:
            if old_path.exists():
                old_path.rename(new_path)
                logger.debug(f"Renamed {old_path.name} -> {new_path.name}")

        # Update .prj entry
        RasUtils.rename_prj_entry(ras_obj.prj_file, component_type, old_number, new_number, ras_object=ras_obj)

        # Update plan files that reference this component
        ras_obj.plan_df = ras_obj.get_plan_entries()
        for _, row in ras_obj.plan_df.iterrows():
            should_update = (row.get(plan_ref_column) == old_number)
            if should_update and plan_ref_filter_fn is not None:
                should_update = plan_ref_filter_fn(row)
            if should_update:
                plan_path = Path(row['full_path'])
                if plan_path.exists():
                    RasPlan._update_plan_file_reference(
                        plan_path, plan_ref_key, f'{file_prefix}{old_number}', f'{file_prefix}{new_number}'
                    )

        # Refresh all DataFrames
        RasPlan._refresh_all_dataframes(ras_obj)
        return new_number

    # -------------------------------------------------------------------------
    # Private helpers (original)
    # -------------------------------------------------------------------------

    @staticmethod
    def _refresh_all_dataframes(ras_obj) -> None:
        """
        Refresh all project DataFrames after structural changes.

        Refreshes plan_df, geom_df, flow_df, unsteady_df, and boundaries_df
        to ensure all state is current after delete/renumber operations.

        This matches the clone_* pattern but without the heavy initialize() call.
        """
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        ras_obj.boundaries_df = ras_obj.get_boundary_conditions()

    @staticmethod
    def _update_plan_file_reference(plan_path: Path, key: str, old_value: str, new_value: str) -> bool:
        """
        Update a key=value reference inside a plan file.

        Parameters:
        plan_path (Path): Path to the .pXX file
        key (str): Key to find (e.g., 'Geom File', 'Flow File')
        old_value (str): Current value (e.g., 'g06')
        new_value (str): New value (e.g., 'g02')

        Returns:
        bool: True if file was modified, False if key/value not found.
        """
        try:
            with open(plan_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            target = f"{key}={old_value}"
            replacement = f"{key}={new_value}"
            modified = False

            for i, line in enumerate(lines):
                if line.strip() == target:
                    lines[i] = replacement + '\n'
                    modified = True
                    break

            if modified:
                with open(plan_path, 'w', encoding='utf-8', errors='replace') as f:
                    f.writelines(lines)
                logger.debug(
                    "Updated %s from %s to %s in %s",
                    key,
                    old_value,
                    new_value,
                    plan_path.name,
                )

            return modified
        except Exception as e:
            logger.error(f"Error updating reference in {plan_path}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Delete and Renumber operations
    # -------------------------------------------------------------------------

    @staticmethod
    @log_call
    def delete_plan(plan_number: Union[str, Number], permanent_delete: bool = False, ras_object=None) -> None:
        """
        Delete a plan and its associated files from the project.

        By default, moves the .pXX file and any associated .pXX.hdf, .pXX.computeMsgs.txt,
        and .pXX.comp_msgs.txt files to a timestamped Backup folder, then removes the
        entry from the .prj file.

        Parameters:
        plan_number (Union[str, Number]): Plan number to delete (e.g., '05', 5)
        permanent_delete (bool): If True, permanently delete files. If False (default),
            move files to {project_folder}/Backup/{timestamp}_deleted_p{number}/.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Raises:
        ValueError: If the plan doesn't exist.

        Note:
        If deleting the Current Plan, a warning is logged but deletion proceeds.
        HEC-RAS will open without errors, but no plan will be active.

        Example:
        >>> RasPlan.delete_plan("05")  # Backs up to Backup/ folder
        >>> RasPlan.delete_plan("05", permanent_delete=True)  # Permanently deletes
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        plan_number = RasUtils.normalize_ras_number(plan_number)

        # Verify plan exists
        ras_obj.plan_df = ras_obj.get_plan_entries()
        if plan_number not in ras_obj.plan_df['plan_number'].values:
            raise ValueError(f"Plan {plan_number} does not exist in the project")

        # Check if this is the current plan - warn but allow deletion
        with open(ras_obj.prj_file, 'r', encoding='utf-8', errors='replace') as f:
            prj_content = f.read()
        if f"Current Plan=p{plan_number}" in prj_content:
            logger.warning(
                f"Deleting Current Plan {plan_number}. HEC-RAS will open without errors, "
                f"but no plan will be active until a new Current Plan is set."
            )

        # Build list of files to remove
        base = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
        files_to_remove = [
            base,
            Path(str(base) + '.hdf'),
            Path(str(base) + '.computeMsgs.txt'),
            Path(str(base) + '.comp_msgs.txt'),
        ]

        if permanent_delete:
            for f in files_to_remove:
                if f.exists():
                    f.unlink()
                    logger.debug(f"Permanently deleted {f.name}")
        else:
            label = f"deleted_p{plan_number}"
            RasUtils.backup_files(files_to_remove, ras_obj.project_folder, label)

        # Remove from .prj
        RasUtils.remove_prj_entry(ras_obj.prj_file, 'Plan', plan_number, ras_object=ras_obj)

        # Remove Current Plan line if it references this plan
        with open(ras_obj.prj_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        new_lines = [line for line in lines if line.strip() != f"Current Plan=p{plan_number}"]
        if len(new_lines) < len(lines):
            with open(ras_obj.prj_file, 'w', encoding='utf-8', errors='replace') as f:
                f.writelines(new_lines)
            logger.debug("Removed Current Plan=p%s line from .prj", plan_number)

        # Refresh all DataFrames
        RasPlan._refresh_all_dataframes(ras_obj)

    @staticmethod
    @log_call
    def renumber_plan(old_number: Union[str, Number], new_number: Union[str, Number], ras_object=None) -> str:
        """
        Renumber a plan file and update all project references.

        Renames the .pXX file and associated files (.hdf, .computeMsgs.txt, .comp_msgs.txt),
        updates the .prj file entry, and updates Current Plan if applicable.

        Parameters:
        old_number (Union[str, Number]): Current plan number (e.g., '05', 5)
        new_number (Union[str, Number]): New plan number (e.g., '02', 2)
        ras_object (RasPrj, optional): Specific RAS object to use.

        Returns:
        str: The new plan number.

        Raises:
        ValueError: If old plan doesn't exist or new plan number already exists.

        Example:
        >>> RasPlan.renumber_plan("13", "01")
        '01'
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        old_number = RasUtils.normalize_ras_number(old_number)
        new_number = RasUtils.normalize_ras_number(new_number)

        # Verify old exists, new doesn't
        ras_obj.plan_df = ras_obj.get_plan_entries()
        if old_number not in ras_obj.plan_df['plan_number'].values:
            raise ValueError(f"Plan {old_number} does not exist in the project")
        if new_number in ras_obj.plan_df['plan_number'].values:
            raise ValueError(f"Plan {new_number} already exists in the project")

        # Build rename pairs
        base_old = ras_obj.project_folder / f"{ras_obj.project_name}.p{old_number}"
        base_new = ras_obj.project_folder / f"{ras_obj.project_name}.p{new_number}"
        rename_pairs = [
            (base_old, base_new),
            (Path(str(base_old) + '.hdf'), Path(str(base_new) + '.hdf')),
            (Path(str(base_old) + '.computeMsgs.txt'), Path(str(base_new) + '.computeMsgs.txt')),
            (Path(str(base_old) + '.comp_msgs.txt'), Path(str(base_new) + '.comp_msgs.txt')),
        ]

        for old_path, new_path in rename_pairs:
            if old_path.exists():
                old_path.rename(new_path)
                logger.debug(f"Renamed {old_path.name} -> {new_path.name}")

        # Update .prj entry
        RasUtils.rename_prj_entry(ras_obj.prj_file, 'Plan', old_number, new_number, ras_object=ras_obj)

        # Update Current Plan if it references the old number
        with open(ras_obj.prj_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.strip() == f"Current Plan=p{old_number}":
                lines[i] = f"Current Plan=p{new_number}\n"
                with open(ras_obj.prj_file, 'w', encoding='utf-8', errors='replace') as f:
                    f.writelines(lines)
                logger.debug("Updated Current Plan from p%s to p%s", old_number, new_number)
                break

        # Refresh all DataFrames
        RasPlan._refresh_all_dataframes(ras_obj)
        return new_number

    @staticmethod
    @log_call
    def delete_geom(geom_number: Union[str, Number], force: bool = False, permanent_delete: bool = False, ras_object=None) -> None:
        """
        Delete a geometry file and its associated files from the project.

        By default, moves the .gXX, .gXX.hdf, and .cXX files to a timestamped Backup
        folder, then removes the entry from the .prj file.

        Parameters:
        geom_number (Union[str, Number]): Geometry number to delete (e.g., '06', 6)
        force (bool): If True, allow deletion even if plans reference this geometry. Default False.
        permanent_delete (bool): If True, permanently delete files. If False (default),
            move files to {project_folder}/Backup/{timestamp}_deleted_g{number}/.
        ras_object (RasPrj, optional): Specific RAS object to use.

        Raises:
        ValueError: If the geometry doesn't exist, or if plans reference it and force=False.

        Example:
        >>> RasPlan.delete_geom("06")  # Backs up to Backup/ folder
        >>> RasPlan.delete_geom("06", force=True, permanent_delete=True)  # Permanently deletes
        """
        def _geom_ref_check(ras_obj, number):
            ras_obj.plan_df = ras_obj.get_plan_entries()
            return ras_obj.plan_df[ras_obj.plan_df['Geom File'] == number]

        backup_dir = RasPlan._delete_component(
            component_number=geom_number,
            component_type='Geom',
            file_prefix='g',
            df_attr='geom_df',
            number_column='geom_number',
            associated_suffixes=['', '.hdf'],
            reference_check_fn=_geom_ref_check,
            force=force,
            permanent_delete=permanent_delete,
            ras_object=ras_object,
        )
        # Also handle .cXX preprocessor file
        ras_obj = ras_object or ras
        number = RasUtils.normalize_ras_number(geom_number)
        c_file = ras_obj.project_folder / f"{ras_obj.project_name}.c{number}"
        if c_file.exists():
            if permanent_delete:
                c_file.unlink()
                logger.debug(f"Permanently deleted {c_file.name}")
            elif backup_dir:
                shutil.move(str(c_file), str(backup_dir / c_file.name))
                logger.debug(f"Backed up {c_file.name} to {backup_dir}")
            else:
                label = f"deleted_g{number}"
                RasUtils.backup_files([c_file], ras_obj.project_folder, label)

    @staticmethod
    @log_call
    def renumber_geom(old_number: Union[str, Number], new_number: Union[str, Number], ras_object=None) -> str:
        """
        Renumber a geometry file and update all project references.

        Renames .gXX, .gXX.hdf, and .cXX files, updates the .prj file, and updates
        all plan files that reference this geometry.

        Parameters:
        old_number (Union[str, Number]): Current geometry number (e.g., '06', 6)
        new_number (Union[str, Number]): New geometry number (e.g., '02', 2)
        ras_object (RasPrj, optional): Specific RAS object to use.

        Returns:
        str: The new geometry number.

        Raises:
        ValueError: If old geometry doesn't exist or new number already exists.

        Example:
        >>> RasPlan.renumber_geom("06", "02")
        '02'
        """
        result = RasPlan._renumber_component(
            old_number=old_number,
            new_number=new_number,
            component_type='Geom',
            file_prefix='g',
            df_attr='geom_df',
            number_column='geom_number',
            companion_extensions=['.hdf'],
            plan_ref_key='Geom File',
            plan_ref_column='Geom File',
            ras_object=ras_object,
        )
        # Also rename the .cXX preprocessor file
        ras_obj = ras_object or ras
        old_num = RasUtils.normalize_ras_number(old_number)
        new_num = RasUtils.normalize_ras_number(new_number)
        base = ras_obj.project_folder / f"{ras_obj.project_name}"
        c_old = Path(f"{base}.c{old_num}")
        c_new = Path(f"{base}.c{new_num}")
        if c_old.exists():
            c_old.rename(c_new)
            logger.debug("Renamed %s -> %s", c_old.name, c_new.name)
        return result

    @staticmethod
    @log_call
    def delete_unsteady(unsteady_number: Union[str, Number], force: bool = False, permanent_delete: bool = False, ras_object=None) -> None:
        """
        Delete an unsteady flow file from the project.

        By default, moves the .uXX file and its .hdf companion to a timestamped Backup
        folder, then removes the entry from the .prj file.

        Parameters:
        unsteady_number (Union[str, Number]): Unsteady number to delete (e.g., '07', 7)
        force (bool): If True, allow deletion even if plans reference it. Default False.
        permanent_delete (bool): If True, permanently delete files. If False (default),
            move files to {project_folder}/Backup/{timestamp}_deleted_u{number}/.
        ras_object (RasPrj, optional): Specific RAS object to use.

        Raises:
        ValueError: If the unsteady file doesn't exist, or if plans reference it and force=False.

        Example:
        >>> RasPlan.delete_unsteady("07")  # Backs up to Backup/ folder
        >>> RasPlan.delete_unsteady("07", permanent_delete=True)  # Permanently deletes
        """
        def _unsteady_ref_check(ras_obj, number):
            ras_obj.plan_df = ras_obj.get_plan_entries()
            return ras_obj.plan_df[ras_obj.plan_df['unsteady_number'] == number]

        RasPlan._delete_component(
            component_number=unsteady_number,
            component_type='Unsteady',
            file_prefix='u',
            df_attr='unsteady_df',
            number_column='unsteady_number',
            associated_suffixes=['', '.hdf'],
            reference_check_fn=_unsteady_ref_check,
            force=force,
            permanent_delete=permanent_delete,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def renumber_unsteady(old_number: Union[str, Number], new_number: Union[str, Number], ras_object=None) -> str:
        """
        Renumber an unsteady flow file and update all project references.

        Renames .uXX and .uXX.hdf files, updates the .prj file, and updates
        all plan files that reference this unsteady flow.

        Parameters:
        old_number (Union[str, Number]): Current unsteady number (e.g., '07', 7)
        new_number (Union[str, Number]): New unsteady number (e.g., '02', 2)
        ras_object (RasPrj, optional): Specific RAS object to use.

        Returns:
        str: The new unsteady number.

        Raises:
        ValueError: If old unsteady doesn't exist or new number already exists.

        Example:
        >>> RasPlan.renumber_unsteady("07", "02")
        '02'
        """
        return RasPlan._renumber_component(
            old_number=old_number,
            new_number=new_number,
            component_type='Unsteady',
            file_prefix='u',
            df_attr='unsteady_df',
            number_column='unsteady_number',
            companion_extensions=['.hdf'],
            plan_ref_key='Flow File',
            plan_ref_column='unsteady_number',
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def delete_steady(flow_number: Union[str, Number], force: bool = False, permanent_delete: bool = False, ras_object=None) -> None:
        """
        Delete a steady flow file from the project.

        By default, moves the .fXX file to a timestamped Backup folder, then removes
        the entry from the .prj file.

        Parameters:
        flow_number (Union[str, Number]): Flow number to delete (e.g., '01', 1)
        force (bool): If True, allow deletion even if plans reference it. Default False.
        permanent_delete (bool): If True, permanently delete files. If False (default),
            move files to {project_folder}/Backup/{timestamp}_deleted_f{number}/.
        ras_object (RasPrj, optional): Specific RAS object to use.

        Raises:
        ValueError: If the flow file doesn't exist, or if plans reference it and force=False.

        Example:
        >>> RasPlan.delete_steady("01")  # Backs up to Backup/ folder
        >>> RasPlan.delete_steady("01", permanent_delete=True)  # Permanently deletes
        """
        def _steady_ref_check(ras_obj, number):
            ras_obj.plan_df = ras_obj.get_plan_entries()
            return ras_obj.plan_df[
                (ras_obj.plan_df['unsteady_number'].isna()) &
                (ras_obj.plan_df['Flow File'] == number)
            ]

        RasPlan._delete_component(
            component_number=flow_number,
            component_type='Flow',
            file_prefix='f',
            df_attr='flow_df',
            number_column='flow_number',
            associated_suffixes=[''],
            reference_check_fn=_steady_ref_check,
            force=force,
            permanent_delete=permanent_delete,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def renumber_steady(old_number: Union[str, Number], new_number: Union[str, Number], ras_object=None) -> str:
        """
        Renumber a steady flow file and update all project references.

        Renames the .fXX file, updates the .prj file, and updates all plan files
        that reference this steady flow.

        Parameters:
        old_number (Union[str, Number]): Current flow number (e.g., '01', 1)
        new_number (Union[str, Number]): New flow number (e.g., '02', 2)
        ras_object (RasPrj, optional): Specific RAS object to use.

        Returns:
        str: The new flow number.

        Raises:
        ValueError: If old flow doesn't exist or new number already exists.

        Example:
        >>> RasPlan.renumber_steady("01", "02")
        '02'
        """
        return RasPlan._renumber_component(
            old_number=old_number,
            new_number=new_number,
            component_type='Flow',
            file_prefix='f',
            df_attr='flow_df',
            number_column='flow_number',
            companion_extensions=[],
            plan_ref_key='Flow File',
            plan_ref_column='Flow File',
            plan_ref_filter_fn=lambda row: pd.isna(row.get('unsteady_number')),
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def create_plan_variants(
        base_plan: Union[str, Number],
        variants: pd.DataFrame,
        naming_template: str = "{variant_name}",
        ras_object=None
    ) -> pd.DataFrame:
        """
        Create multiple plan variants from a base plan driven by a DataFrame.

        Wraps clone_plan() in a loop, applying per-variant settings from the
        variants DataFrame. Each row creates one new plan.

        Parameters
        ----------
        base_plan : str or Number
            Plan number to use as template (e.g., '01' or 1)
        variants : pd.DataFrame
            DataFrame with variant specifications. Required column:
            - variant_name: str — name/title for the new plan
            Optional columns (applied if present):
            - unsteady_flow: str or Number — unsteady flow file number
            - steady_flow: str or Number — steady flow file number
            - geometry: str or Number — geometry file number
            - num_cores: int — number of computation cores
            - computation_interval: str — e.g., '5MIN', '1MIN'
            - output_interval: str — e.g., '15MIN', '1HOUR'
            - description: str — plan description text
        naming_template : str, default '{variant_name}'
            Template for plan title. Supports {variant_name}, {index},
            {base_plan} substitutions.
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            Report with columns:
            - variant_name: Name from input DataFrame
            - plan_number: New plan number assigned
            - plan_path: Full path to created plan file
            - status: 'created' or 'error'
            - message: Details or error message

        Example
        -------
        >>> import pandas as pd
        >>> from ras_commander import RasPlan
        >>> variants = pd.DataFrame({
        ...     'variant_name': ['6hr Storm', '12hr Storm', '24hr Storm'],
        ...     'unsteady_flow': ['01', '02', '03'],
        ...     'description': ['6-hour design storm', '12-hour design storm', '24-hour design storm']
        ... })
        >>> report = RasPlan.create_plan_variants('01', variants)
        >>> print(report[['variant_name', 'plan_number', 'status']])

        Notes
        -----
        Plans are created sequentially to ensure proper numbering. After all
        variants are created, DataFrames are refreshed once via plan_df.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        base_plan = RasUtils.normalize_ras_number(base_plan)
        report_rows = []

        for idx, row in variants.iterrows():
            variant_name = str(row.get('variant_name', f'Variant_{idx}'))

            # Build title from template
            title = naming_template.format(
                variant_name=variant_name,
                index=idx,
                base_plan=base_plan
            )
            # Truncate to 32 chars (HEC-RAS limit)
            if len(title) > 32:
                original_title = title
                title = title[:32]
                logger.warning(
                    "Plan title exceeds 32 characters (received %d); truncating",
                    len(original_title),
                )
                logger.debug("Original plan title before truncation: %s", original_title)

            # Build clone_plan kwargs from variant row
            clone_kwargs = {
                'new_title': title,
            }

            if 'geometry' in row.index and pd.notna(row.get('geometry')):
                clone_kwargs['geometry'] = row['geometry']
            if 'unsteady_flow' in row.index and pd.notna(row.get('unsteady_flow')):
                clone_kwargs['unsteady_flow'] = row['unsteady_flow']
            if 'steady_flow' in row.index and pd.notna(row.get('steady_flow')):
                clone_kwargs['steady_flow'] = row['steady_flow']
            if 'num_cores' in row.index and pd.notna(row.get('num_cores')):
                clone_kwargs['num_cores'] = int(row['num_cores'])
            if 'description' in row.index and pd.notna(row.get('description')):
                clone_kwargs['description'] = str(row['description'])

            # Build intervals dict if interval columns present
            intervals = {}
            if 'computation_interval' in row.index and pd.notna(row.get('computation_interval')):
                intervals['computation_interval'] = row['computation_interval']
            if 'output_interval' in row.index and pd.notna(row.get('output_interval')):
                intervals['output_interval'] = row['output_interval']
            if intervals:
                clone_kwargs['intervals'] = intervals

            try:
                new_plan_num = RasPlan.clone_plan(
                    template_plan=base_plan,
                    ras_object=ras_obj,
                    **clone_kwargs
                )

                # Get the plan path
                plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{new_plan_num}"

                report_rows.append({
                    'variant_name': variant_name,
                    'plan_number': new_plan_num,
                    'plan_path': str(plan_path),
                    'status': 'created',
                    'message': f"Created from plan {base_plan}"
                })
                logger.debug("Created variant %r as plan p%s", variant_name, new_plan_num)

            except Exception as e:
                report_rows.append({
                    'variant_name': variant_name,
                    'plan_number': None,
                    'plan_path': None,
                    'status': 'error',
                    'message': str(e)
                })
                logger.error(f"Failed to create variant '{variant_name}': {e}")

        report = pd.DataFrame(report_rows)
        n_created = len(report[report['status'] == 'created'])
        logger.info(f"Created {n_created}/{len(variants)} plan variants from plan p{base_plan}")
        return report

