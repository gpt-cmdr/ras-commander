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
"""
import os
import re
import logging
from pathlib import Path
import shutil
from typing import Union, Optional
import pandas as pd
from .RasPrj import RasPrj, ras
from .RasUtils import RasUtils
from pathlib import Path
from typing import Union, Any
import logging
import re
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

class RasPlan:
    """
    A class for operations on HEC-RAS plan files.
    """
    
    @staticmethod
    @log_call
    def set_geom(plan_number: Union[str, int], new_geom: Union[str, int], ras_object=None) -> pd.DataFrame:
        """
        Set the geometry for the specified plan.

        Parameters:
            plan_number (Union[str, int]): The plan number to update.
            new_geom (Union[str, int]): The new geometry number to set.
            ras_object: An optional RAS object instance.

        Returns:
            pd.DataFrame: The updated geometry DataFrame.

        Example:
            updated_geom_df = RasPlan.set_geom('02', '03')

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Ensure plan_number and new_geom are strings
        plan_number = str(plan_number).zfill(2)
        new_geom = str(new_geom).zfill(2)

        # Before doing anything, make sure the plan, geom, flow, and unsteady dataframes are current
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        if new_geom not in ras_obj.geom_df['geom_number'].values:
            logger.error(f"Geometry {new_geom} not found in project.")
            raise ValueError(f"Geometry {new_geom} not found in project.")

        # Update the geometry for the specified plan
        ras_obj.plan_df.loc[ras_obj.plan_df['plan_number'] == plan_number, 'geom_number'] = new_geom

        logger.info(f"Geometry for plan {plan_number} set to {new_geom}")
        logger.debug("Updated plan DataFrame:")
        logger.debug(ras_obj.plan_df)

        # Update the project file
        prj_file_path = ras_obj.prj_file
        RasUtils.update_file(prj_file_path, RasPlan._update_geom_in_file, plan_number, new_geom)

        # Re-initialize the ras object to reflect changes
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        return ras_obj.plan_df

    @staticmethod
    def _update_geom_in_file(lines, plan_number, new_geom):
        plan_pattern = re.compile(rf"^Plan File=p{plan_number}", re.IGNORECASE)
        geom_pattern = re.compile(r"^Geom File=g\d+", re.IGNORECASE)
        
        for i, line in enumerate(lines):
            if plan_pattern.match(line):
                for j in range(i+1, len(lines)):
                    if geom_pattern.match(lines[j]):
                        lines[j] = f"Geom File=g{new_geom}\n"
                        logger.info(f"Updated Geom File in project file to g{new_geom} for plan {plan_number}")
                        break
                break
        return lines

    @staticmethod
    @log_call
    def set_steady(plan_number: str, new_steady_flow_number: str, ras_object=None):
        """
        Apply a steady flow file to a plan file.
        
        Parameters:
        plan_number (str): Plan number (e.g., '02')
        new_steady_flow_number (str): Steady flow number to apply (e.g., '01')
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
                        
        # Update the flow dataframe in the ras instance to ensure it is current
        ras_obj.flow_df = ras_obj.get_flow_entries()
        
        if new_steady_flow_number not in ras_obj.flow_df['flow_number'].values:
            raise ValueError(f"Steady flow number {new_steady_flow_number} not found in project file.")
        
        # Resolve the full path of the plan file
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        RasUtils.update_file(plan_file_path, RasPlan._update_steady_in_file, new_steady_flow_number)

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    def _update_steady_in_file(lines, new_steady_flow_number):
        return [f"Flow File=f{new_steady_flow_number}\n" if line.startswith("Flow File=f") else line for line in lines]

    @staticmethod
    @log_call
    def set_unsteady(plan_number: str, new_unsteady_flow_number: str, ras_object=None):
        """
        Apply an unsteady flow file to a plan file.
        
        Parameters:
        plan_number (str): Plan number (e.g., '04')
        new_unsteady_flow_number (str): Unsteady flow number to apply (e.g., '01')
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
        
        # Update the unsteady dataframe in the ras instance to ensure it is current
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        if new_unsteady_flow_number not in ras_obj.unsteady_df['unsteady_number'].values:
            raise ValueError(f"Unsteady number {new_unsteady_flow_number} not found in project file.")
        
        # Get the full path of the plan file
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        try:
            RasUtils.update_file(plan_file_path, RasPlan._update_unsteady_in_file, new_unsteady_flow_number)
        except Exception as e:
            raise Exception(f"Failed to update unsteady flow file: {e}")

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
    def _update_unsteady_in_file(lines, new_unsteady_flow_number):
        return [f"Unsteady File=u{new_unsteady_flow_number}\n" if line.startswith("Unsteady File=u") else line for line in lines]
    @staticmethod
    @log_call
    def set_num_cores(plan_number, num_cores, ras_object=None):
        """
        Update the maximum number of cores to use in the HEC-RAS plan file.
        
        Parameters:
        plan_number (str): Plan number (e.g., '02') or full path to the plan file
        num_cores (int): Maximum number of cores to use
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

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
                if "UNET D1 Cores=" in line:
                    parts = line.split("=")
                    updated_lines.append(f"{parts[0]}= {num_cores}\n")
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
    def get_results_path(plan_number: str, ras_object=None) -> Optional[str]:
        """
        Retrieve the results file path for a given HEC-RAS plan number.

        Args:
            plan_number (str): The HEC-RAS plan number for which to find the results path.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
            Optional[str]: The full path to the results file if found and the file exists, or None if not found.

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
        
        # Ensure plan_number is a string
        plan_number = str(plan_number).zfill(2)
        
        plan_entry = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_number]
        if not plan_entry.empty:
            results_path = plan_entry['HDF_Results_Path'].iloc[0]
            if results_path and Path(results_path).exists():
                return results_path
            else:
                return None
        else:
            return None

    @staticmethod
    @log_call
    def get_plan_path(plan_number: str, ras_object=None) -> Optional[str]:
        """
        Return the full path for a given plan number.
        
        This method ensures that the latest plan entries are included by refreshing
        the plan dataframe before searching for the requested plan number.
        
        Args:
        plan_number (str): The plan number to search for.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        Optional[str]: The full path of the plan file if found, None otherwise.
        
        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> plan_path = ras_plan.get_plan_path('01')
        >>> if plan_path:
        ...     print(f"Plan file found at: {plan_path}")
        ... else:
        ...     print("Plan file not found.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Use updated plan dataframe
        plan_df = ras_obj.get_plan_entries()
        
        plan_path = plan_df[plan_df['plan_number'] == plan_number]
        
        if not plan_path.empty:
            full_path = plan_path['full_path'].iloc[0]
            return full_path
        else:
            return None

    @staticmethod
    @log_call
    def get_flow_path(flow_number: str, ras_object=None) -> Optional[str]:
        """
        Return the full path for a given flow number.

        Args:
        flow_number (str): The flow number to search for.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[str]: The full path of the flow file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> flow_path = ras_plan.get_flow_path('01')
        >>> if flow_path:
        ...     print(f"Flow file found at: {flow_path}")
        ... else:
        ...     print("Flow file not found.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Use updated flow dataframe
        ras_obj.flow_df = ras_obj.get_prj_entries('Flow')
        
        flow_path = ras_obj.flow_df[ras_obj.flow_df['flow_number'] == flow_number]
        if not flow_path.empty:
            full_path = flow_path['full_path'].iloc[0]
            return full_path
        else:
            return None

    @staticmethod
    @log_call
    def get_unsteady_path(unsteady_number: str, ras_object=None) -> Optional[str]:
        """
        Return the full path for a given unsteady number.

        Args:
        unsteady_number (str): The unsteady number to search for.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[str]: The full path of the unsteady file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> unsteady_path = ras_plan.get_unsteady_path('01')
        >>> if unsteady_path:
        ...     print(f"Unsteady file found at: {unsteady_path}")
        ... else:
        ...     print("Unsteady file not found.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Use updated unsteady dataframe
        ras_obj.unsteady_df = ras_obj.get_prj_entries('Unsteady')
        
        unsteady_path = ras_obj.unsteady_df[ras_obj.unsteady_df['unsteady_number'] == unsteady_number]
        if not unsteady_path.empty:
            full_path = unsteady_path['full_path'].iloc[0]
            return full_path
        else:
            return None

    @staticmethod
    @log_call
    def get_geom_path(geom_number: str, ras_object=None) -> Optional[str]:
        """
        Return the full path for a given geometry number.

        Args:
        geom_number (str): The geometry number to search for.
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        Optional[str]: The full path of the geometry file if found, None otherwise.

        Raises:
        RuntimeError: If the project is not initialized.

        Example:
        >>> ras_plan = RasPlan()
        >>> geom_path = ras_plan.get_geom_path('01')
        >>> if geom_path:
        ...     print(f"Geometry file found at: {geom_path}")
        ... else:
        ...     print("Geometry file not found.")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Use updated geom dataframe
        ras_obj.geom_df = ras_obj.get_prj_entries('Geom')
        
        geom_path = ras_obj.geom_df[ras_obj.geom_df['geom_number'] == geom_number]
        if not geom_path.empty:
            full_path = geom_path['full_path'].iloc[0]
            return full_path
        else:
            return None

    # Clone Functions to copy unsteady, flow, and geometry files from templates

    @staticmethod
    @log_call
    def clone_plan(template_plan, new_plan_shortid=None, ras_object=None):
        """
        Create a new plan file based on a template and update the project file.
        
        Parameters:
        template_plan (str): Plan number to use as template (e.g., '01')
        new_plan_shortid (str, optional): New short identifier for the plan file
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        str: New plan number
        
        Example:
        >>> ras_plan = RasPlan()
        >>> new_plan_number = ras_plan.clone_plan('01', new_plan_shortid='New Plan')
        >>> print(f"New plan created with number: {new_plan_number}")

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Update plan entries without reinitializing the entire project
        ras_obj.plan_df = ras_obj.get_prj_entries('Plan')

        new_plan_num = RasPlan.get_next_number(ras_obj.plan_df['plan_number'])
        template_plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{template_plan}"
        new_plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{new_plan_num}"

        def update_shortid(lines):
            shortid_pattern = re.compile(r'^Short Identifier=(.*)$', re.IGNORECASE)
            for i, line in enumerate(lines):
                match = shortid_pattern.match(line.strip())
                if match:
                    current_shortid = match.group(1)
                    if new_plan_shortid is None:
                        new_shortid = (current_shortid + "_copy")[:24]
                    else:
                        new_shortid = new_plan_shortid[:24]
                    lines[i] = f"Short Identifier={new_shortid}\n"
                    break
            return lines

        # Use RasUtils to clone the file and update the short identifier
        RasUtils.clone_file(template_plan_path, new_plan_path, update_shortid)

        # Use RasUtils to update the project file
        RasUtils.update_project_file(ras_obj.prj_file, 'Plan', new_plan_num, ras_object=ras_obj)

        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        return new_plan_num

    @staticmethod
    @log_call
    def clone_unsteady(template_unsteady, ras_object=None):
        """
        Copy unsteady flow files from a template, find the next unsteady number,
        and update the project file accordingly.

        Parameters:
        template_unsteady (str): Unsteady flow number to be used as a template (e.g., '01')
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Returns:
        str: New unsteady flow number (e.g., '03')

        Example:
        >>> ras_plan = RasPlan()
        >>> new_unsteady_num = ras_plan.clone_unsteady('01')
        >>> print(f"New unsteady flow file created: u{new_unsteady_num}")

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Update unsteady entries without reinitializing the entire project
        ras_obj.unsteady_df = ras_obj.get_prj_entries('Unsteady')

        new_unsteady_num = RasPlan.get_next_number(ras_obj.unsteady_df['unsteady_number'])
        template_unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{template_unsteady}"
        new_unsteady_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{new_unsteady_num}"

        # Use RasUtils to clone the file
        RasUtils.clone_file(template_unsteady_path, new_unsteady_path)

        # Copy the corresponding .hdf file if it exists
        template_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{template_unsteady}.hdf"
        new_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{new_unsteady_num}.hdf"
        if template_hdf_path.exists():
            shutil.copy(template_hdf_path, new_hdf_path)

        # Use RasUtils to update the project file
        RasUtils.update_project_file(ras_obj.prj_file, 'Unsteady', new_unsteady_num, ras_object=ras_obj)

        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        return new_unsteady_num


    @staticmethod
    @log_call
    def clone_steady(template_flow, ras_object=None):
        """
        Copy steady flow files from a template, find the next flow number,
        and update the project file accordingly.
        
        Parameters:
        template_flow (str): Flow number to be used as a template (e.g., '01')
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        str: New flow number (e.g., '03')

        Example:
        >>> ras_plan = RasPlan()
        >>> new_flow_num = ras_plan.clone_steady('01')
        >>> print(f"New steady flow file created: f{new_flow_num}")

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Update flow entries without reinitializing the entire project
        ras_obj.flow_df = ras_obj.get_prj_entries('Flow')

        new_flow_num = RasPlan.get_next_number(ras_obj.flow_df['flow_number'])
        template_flow_path = ras_obj.project_folder / f"{ras_obj.project_name}.f{template_flow}"
        new_flow_path = ras_obj.project_folder / f"{ras_obj.project_name}.f{new_flow_num}"

        # Use RasUtils to clone the file
        RasUtils.clone_file(template_flow_path, new_flow_path)

        # Use RasUtils to update the project file
        RasUtils.update_project_file(ras_obj.prj_file, 'Flow', new_flow_num, ras_object=ras_obj)

        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)
        
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        return new_flow_num

    @staticmethod
    @log_call
    def clone_geom(template_geom, ras_object=None):
        """
        Copy geometry files from a template, find the next geometry number,
        and update the project file accordingly.
        
        Parameters:
        template_geom (str): Geometry number to be used as a template (e.g., '01')
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        str: New geometry number (e.g., '03')

        Note:
            This function updates the ras object's dataframes after modifying the project structure.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Update geometry entries without reinitializing the entire project
        ras_obj.geom_df = ras_obj.get_prj_entries('Geom')

        new_geom_num = RasPlan.get_next_number(ras_obj.geom_df['geom_number'])
        template_geom_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{template_geom}"
        new_geom_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{new_geom_num}"

        # Use RasUtils to clone the file
        RasUtils.clone_file(template_geom_path, new_geom_path)

        # Handle HDF file copy
        template_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{template_geom}.hdf"
        new_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{new_geom_num}.hdf"
        if template_hdf_path.is_file():
            RasUtils.clone_file(template_hdf_path, new_hdf_path)

        # Use RasUtils to update the project file
        RasUtils.update_project_file(ras_obj.prj_file, 'Geom', new_geom_num, ras_object=ras_obj)

        # Update all dataframes in the ras object
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        return new_geom_num

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
        - 'Run HTAB' (int): Flag to run HTab module (-1 or 1)
        - 'Run Post Process' (int): Flag to run post-processing (-1 or 1)
        - 'Run Sediment' (int): Flag to run sediment transport module (0 or 1)
        - 'Run UNET' (int): Flag to run unsteady network module (-1 or 1)
        - 'Run WQNET' (int): Flag to run water quality module (0 or 1)
        - 'Short Identifier' (str): Short name or ID for the plan
        - 'Simulation Date' (str): Start and end dates/times for simulation
        - 'UNET D1 Cores' (int): Number of cores used in 1D calculations
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
            'Run HTAB', 'Run Post Process', 'Run Sediment', 'Run UNET', 'Run WQNET',
            'Short Identifier', 'Simulation Date', 'UNET D1 Cores', 'UNET Use Existing IB Tables',
            'UNET 1D Methodology', 'UNET D2 Solver Type', 'UNET D2 Name', 'Run RASMapper'
        }

        if key not in supported_plan_keys:
            logger = logging.getLogger(__name__)
            logger.warning(f"Unknown key: {key}. Valid keys are: {', '.join(supported_plan_keys)}\n Add more keys and explanations in get_plan_value() as needed.")

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r') as file:
                content = file.read()
        except IOError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        if key == 'Description':
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
    def update_plan_value(
        plan_number_or_path: Union[str, Path],
        key: str,
        value: Any,
        ras_object=None
    ) -> None:
        """
        Update a specific key-value pair in a HEC-RAS plan file.

        Parameters:
        plan_number_or_path (Union[str, Path]): The plan number (1 to 99) or full path to the plan file
        key (str): The key to update in the plan file
        value (Any): The new value to set for the key
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.

        Raises:
        ValueError: If the plan file is not found
        IOError: If there's an error reading or writing the plan file

        Note: See the docstring of get_plan_value for a full list of available keys and their types.

        Example:
        >>> RasPlan.update_plan_value("01", "computation_interval", "10SEC")
        >>> RasPlan.update_plan_value("/path/to/plan.p01", "run_htab", 1)
        >>> RasPlan.update_plan_value("01", "run_rasmapper", 0)  # Turn on Floodplain Mapping
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        supported_plan_keys = {
            'Description', 'Computation Interval', 'DSS File', 'Flow File', 'Friction Slope Method',
            'Geom File', 'Mapping Interval', 'Plan File', 'Plan Title', 'Program Version',
            'Run HTAB', 'Run Post Process', 'Run Sediment', 'Run UNET', 'Run WQNET',
            'Short Identifier', 'Simulation Date', 'UNET D1 Cores', 'UNET Use Existing IB Tables',
            'UNET 1D Methodology', 'UNET D2 Solver Type', 'UNET D2 Name', 'Run RASMapper'
        }
        logger = logging.getLogger(__name__)
        if key not in supported_plan_keys:
            logger.warning(f"Unknown key: {key}. Valid keys are: {', '.join(supported_plan_keys)}")

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r') as file:
                lines = file.readlines()
        except IOError as e:
            logger.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        # Special handling for description
        if key == 'description':
            description_start = None
            description_end = None
            for i, line in enumerate(lines):
                if line.strip() == 'Begin DESCRIPTION':
                    description_start = i
                elif line.strip() == 'END DESCRIPTION':
                    description_end = i
                    break
            if description_start is not None and description_end is not None:
                lines[description_start+1:description_end] = [f"{value}\n"]
            else:
                lines.append(f"Begin DESCRIPTION\n{value}\nEND DESCRIPTION\n")
        else:
            # For other keys
            pattern = f"{key.replace('_', ' ').title()}="
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(pattern):
                    lines[i] = f"{pattern}{value}\n"
                    updated = True
                    break
            if not updated:
                logger.error(f"Key '{key}' not found in the plan file.")
                return

        try:
            with open(plan_file_path, 'w') as file:
                file.writelines(lines)
            logger.info(f"Updated {key} in plan file: {plan_file_path}")
        except IOError as e:
            logger.error(f"Error writing to plan file {plan_file_path}: {e}")
            raise

        # Refresh RasPrj dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()