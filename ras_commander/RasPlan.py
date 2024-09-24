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


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

class RasPlan:
    """
    A class for operations on HEC-RAS plan files.
    """

    @staticmethod
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
        
        # Log the current geometry DataFrame for debugging
        logging.debug("Current geometry DataFrame within the function:")
        logging.debug(ras_obj.geom_df)

        if new_geom not in ras_obj.geom_df['geom_number'].values:
            logging.error(f"Geometry {new_geom} not found in project.")
            raise ValueError(f"Geometry {new_geom} not found in project.")

        # Update the geometry for the specified plan
        ras_obj.plan_df.loc[ras_obj.plan_df['plan_number'] == plan_number, 'geom_number'] = new_geom

        logging.info(f"Geometry for plan {plan_number} set to {new_geom}")
        logging.debug("Updated plan DataFrame:")
        logging.debug(ras_obj.plan_df)

        # Update the project file
        prj_file_path = ras_obj.prj_file
        try:
            with open(prj_file_path, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"Project file not found: {prj_file_path}")
            raise

        plan_pattern = re.compile(rf"^Plan File=p{plan_number}", re.IGNORECASE)
        geom_pattern = re.compile(r"^Geom File=g\d+", re.IGNORECASE)
        
        for i, line in enumerate(lines):
            if plan_pattern.match(line):
                for j in range(i+1, len(lines)):
                    if geom_pattern.match(lines[j]):
                        lines[j] = f"Geom File=g{new_geom}\n"
                        logging.info(f"Updated Geom File in project file to g{new_geom} for plan {plan_number}")
                        break
                break

        try:
            with open(prj_file_path, 'w') as f:
                f.writelines(lines)
            logging.info(f"Updated project file with new geometry for plan {plan_number}")
        except IOError as e:
            logging.error(f"Failed to write to project file: {e}")
            raise

        # Re-initialize the ras object to reflect changes
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        return ras_obj.plan_df

    @staticmethod
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
        logging.info(f"Setting steady flow file to {new_steady_flow_number} in Plan {plan_number}")
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
                        
        # Update the flow dataframe in the ras instance to ensure it is current
        ras_obj.flow_df = ras_obj.get_flow_entries()
        
        if new_steady_flow_number not in ras_obj.flow_df['flow_number'].values:
            logging.error(f"Steady flow number {new_steady_flow_number} not found in project file.")
            raise ValueError(f"Steady flow number {new_steady_flow_number} not found in project file.")
        
        # Resolve the full path of the plan file
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            logging.error(f"Plan file not found: {plan_number}")
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        try:
            with open(plan_file_path, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"Plan file not found: {plan_file_path}")
            raise
        
        with open(plan_file_path, 'w') as f:
            for line in lines:
                if line.startswith("Flow File=f"):
                    f.write(f"Flow File=f{new_steady_flow_number}\n")
                    logging.info(f"Updated Flow File in {plan_file_path} to f{new_steady_flow_number}")
                else:
                    f.write(line)

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
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
        logging.info(f"Setting unsteady flow file to {new_unsteady_flow_number} in Plan {plan_number}")
        
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Update the unsteady dataframe in the ras instance to ensure it is current
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        if new_unsteady_flow_number not in ras_obj.unsteady_df['unsteady_number'].values:
            logging.error(f"Unsteady number {new_unsteady_flow_number} not found in project file.")
            raise ValueError(f"Unsteady number {new_unsteady_flow_number} not found in project file.")
        
        # Get the full path of the plan file
        plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if not plan_file_path:
            logging.error(f"Plan file not found: {plan_number}")
            raise FileNotFoundError(f"Plan file not found: {plan_number}")
        
        try:
            RasUtils.update_plan_file(plan_file_path, 'Unsteady', new_unsteady_flow_number)
            logging.info(f"Updated unsteady flow file in {plan_file_path} to u{new_unsteady_flow_number}")
        except Exception as e:
            logging.error(f"Failed to update unsteady flow file: {e}")
            raise

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
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
        logging.info(f"Setting num_cores to {num_cores} in Plan {plan_number}")
        
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        # Determine if plan_number is a path or a plan number
        if Path(plan_number).is_file():
            plan_file_path = Path(plan_number)
            if not plan_file_path.exists():
                logging.error(f"Plan file not found: {plan_file_path}. Please provide a valid plan number or path.")
                raise FileNotFoundError(f"Plan file not found: {plan_file_path}. Please provide a valid plan number or path.")
        else:
            # Update the plan dataframe in the ras instance to ensure it is current
            ras_obj.plan_df = ras_obj.get_prj_entries('Plan')
            
            # Get the full path of the plan file
            plan_file_path = RasPlan.get_plan_path(plan_number, ras_obj)
            if not plan_file_path:
                logging.error(f"Plan file not found: {plan_number}. Please provide a valid plan number or path.")
                raise FileNotFoundError(f"Plan file not found: {plan_number}. Please provide a valid plan number or path.")
        
        cores_pattern = re.compile(r"(UNET D1 Cores= )\d+")
        try:
            with open(plan_file_path, 'r') as file:
                content = file.read()
        except FileNotFoundError:
            logging.error(f"Plan file not found: {plan_file_path}")
            raise
        
        new_content = cores_pattern.sub(rf"\g<1>{num_cores}", content)
        try:
            with open(plan_file_path, 'w') as file:
                file.write(new_content)
            logging.info(f"Updated {plan_file_path} with {num_cores} cores.")
        except IOError as e:
            logging.error(f"Failed to write to plan file: {e}")
            raise
        
        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    @staticmethod
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
            logging.error("Invalid value for `Run HTab`. Expected `0` or `-1`.")
            raise ValueError("Invalid value for `Run HTab`. Expected `0` or `-1`.")
        if use_ib_tables not in [-1, 0]:
            logging.error("Invalid value for `UNET Use Existing IB Tables`. Expected `0` or `-1`.")
            raise ValueError("Invalid value for `UNET Use Existing IB Tables`. Expected `0` or `-1`.")
        try:
            logging.info(f"Reading the file: {file_path}")
            with open(file_path, 'r') as file:
                lines = file.readlines()
            logging.info("Updating the file with new settings...")
            updated_lines = []
            for line in lines:
                if line.lstrip().startswith("Run HTab="):
                    updated_line = f"Run HTab= {run_htab} \n"
                    updated_lines.append(updated_line)
                    logging.info(f"Updated 'Run HTab' to {run_htab}")
                elif line.lstrip().startswith("UNET Use Existing IB Tables="):
                    updated_line = f"UNET Use Existing IB Tables= {use_ib_tables} \n"
                    updated_lines.append(updated_line)
                    logging.info(f"Updated 'UNET Use Existing IB Tables' to {use_ib_tables}")
                else:
                    updated_lines.append(line)
            logging.info(f"Writing the updated settings back to the file: {file_path}")
            with open(file_path, 'w') as file:
                file.writelines(updated_lines)
            logging.info("File update completed successfully.")
        except FileNotFoundError:
            logging.error(f"The file '{file_path}' does not exist.")
            raise FileNotFoundError(f"The file '{file_path}' does not exist.")
        except IOError as e:
            logging.error(f"An error occurred while reading or writing the file: {e}")
            raise IOError(f"An error occurred while reading or writing the file: {e}")

        # Update the ras object's dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

    # Get Functions to retrieve file paths for plan, flow, unsteady, geometry and results files

    @staticmethod
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
        
        # Log the plan dataframe for debugging
        logging.debug("Plan DataFrame:")
        logging.debug(ras_obj.plan_df)
        
        plan_entry = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_number]
        if not plan_entry.empty:
            results_path = plan_entry['HDF_Results_Path'].iloc[0]
            if results_path and Path(results_path).exists():
                logging.info(f"Results file for Plan number {plan_number} exists at: {results_path}")
                return results_path
            else:
                logging.warning(f"Results file for Plan number {plan_number} does not exist.")
                return None
        else:
            logging.warning(f"Plan number {plan_number} not found in the entries.")
            return None

    @staticmethod
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
            logging.info(f"Plan file for Plan number {plan_number} found at: {full_path}")
            return full_path
        else:
            logging.warning(f"Plan number {plan_number} not found in the updated plan entries.")
            return None

    @staticmethod
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
            logging.info(f"Flow file for Flow number {flow_number} found at: {full_path}")
            return full_path
        else:
            logging.warning(f"Flow number {flow_number} not found in the updated flow entries.")
            return None

    @staticmethod
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
            logging.info(f"Unsteady file for Unsteady number {unsteady_number} found at: {full_path}")
            return full_path
        else:
            logging.warning(f"Unsteady number {unsteady_number} not found in the updated unsteady entries.")
            return None

    @staticmethod
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
            logging.info(f"Geometry file for Geom number {geom_number} found at: {full_path}")
            return full_path
        else:
            logging.warning(f"Geometry number {geom_number} not found in the updated geometry entries.")
            return None

    # Clone Functions to copy unsteady, flow, and geometry files from templates

    @staticmethod
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
        
        if not template_plan_path.exists():
            logging.error(f"Template plan file '{template_plan_path}' does not exist.")
            raise FileNotFoundError(f"Template plan file '{template_plan_path}' does not exist.")

        shutil.copy(template_plan_path, new_plan_path)
        logging.info(f"Copied {template_plan_path} to {new_plan_path}")

        try:
            with open(new_plan_path, 'r') as f:
                plan_lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"New plan file not found after copying: {new_plan_path}")
            raise

        shortid_pattern = re.compile(r'^Short Identifier=(.*)$', re.IGNORECASE)
        for i, line in enumerate(plan_lines):
            match = shortid_pattern.match(line.strip())
            if match:
                current_shortid = match.group(1)
                if new_plan_shortid is None:
                    new_shortid = (current_shortid + "_copy")[:24]
                else:
                    new_shortid = new_plan_shortid[:24]
                plan_lines[i] = f"Short Identifier={new_shortid}\n"
                logging.info(f"Updated 'Short Identifier' to '{new_shortid}' in {new_plan_path}")
                break

        try:
            with open(new_plan_path, 'w') as f:
                f.writelines(plan_lines)
            logging.info(f"Updated short identifier in {new_plan_path}")
        except IOError as e:
            logging.error(f"Failed to write updated short identifier to {new_plan_path}: {e}")
            raise

        try:
            with open(ras_obj.prj_file, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"Project file not found: {ras_obj.prj_file}")
            raise

        # Prepare the new Plan File entry line
        new_plan_line = f"Plan File=p{new_plan_num}\n"

        # Find the correct insertion point for the new Plan File entry
        plan_file_pattern = re.compile(r'^Plan File=p(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = plan_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number < int(new_plan_num):
                    continue
                else:
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_plan_line)
            logging.info(f"Inserted new plan line at index {insertion_index}")
        else:
            # Try to insert after the last Plan File entry
            plan_indices = [i for i, line in enumerate(lines) if plan_file_pattern.match(line.strip())]
            if plan_indices:
                last_plan_index = plan_indices[-1]
                lines.insert(last_plan_index + 1, new_plan_line)
                logging.info(f"Inserted new plan line after index {last_plan_index}")
            else:
                # Append at the end if no Plan File entries exist
                lines.append(new_plan_line)
                logging.info(f"Appended new plan line at the end of the project file")

        try:
            # Write the updated lines back to the project file
            with open(ras_obj.prj_file, 'w') as f:
                f.writelines(lines)
            logging.info(f"Updated {ras_obj.prj_file} with new plan p{new_plan_num}")
        except IOError as e:
            logging.error(f"Failed to write updated project file: {e}")
            raise

        new_plan = new_plan_num
        
        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)

        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        return new_plan

    @staticmethod
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

        if not template_unsteady_path.exists():
            logging.error(f"Template unsteady file '{template_unsteady_path}' does not exist.")
            raise FileNotFoundError(f"Template unsteady file '{template_unsteady_path}' does not exist.")

        shutil.copy(template_unsteady_path, new_unsteady_path)
        logging.info(f"Copied {template_unsteady_path} to {new_unsteady_path}")

        # Copy the corresponding .hdf file if it exists
        template_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{template_unsteady}.hdf"
        new_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.u{new_unsteady_num}.hdf"
        if template_hdf_path.exists():
            shutil.copy(template_hdf_path, new_hdf_path)
            logging.info(f"Copied {template_hdf_path} to {new_hdf_path}")
        else:
            logging.warning(f"No corresponding .hdf file found for '{template_unsteady_path}'. Skipping '.hdf' copy.")

        try:
            with open(ras_obj.prj_file, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"Project file not found: {ras_obj.prj_file}")
            raise

        # Prepare the new Unsteady Flow File entry line
        new_unsteady_line = f"Unsteady File=u{new_unsteady_num}\n"

        # Find the correct insertion point for the new Unsteady Flow File entry
        unsteady_file_pattern = re.compile(r'^Unsteady File=u(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = unsteady_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number < int(new_unsteady_num):
                    continue
                else:
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_unsteady_line)
            logging.info(f"Inserted new unsteady flow line at index {insertion_index}")
        else:
            # Try to insert after the last Unsteady Flow File entry
            unsteady_indices = [i for i, line in enumerate(lines) if unsteady_file_pattern.match(line.strip())]
            if unsteady_indices:
                last_unsteady_index = unsteady_indices[-1]
                lines.insert(last_unsteady_index + 1, new_unsteady_line)
                logging.info(f"Inserted new unsteady flow line after index {last_unsteady_index}")
            else:
                # Append at the end if no Unsteady Flow File entries exist
                lines.append(new_unsteady_line)
                logging.info(f"Appended new unsteady flow line at the end of the project file")

        try:
            # Write the updated lines back to the project file
            with open(ras_obj.prj_file, 'w') as f:
                f.writelines(lines)
            logging.info(f"Updated {ras_obj.prj_file} with new unsteady flow file u{new_unsteady_num}")
        except IOError as e:
            logging.error(f"Failed to write updated project file: {e}")
            raise

        new_unsteady = new_unsteady_num
        
        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)
        
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        return new_unsteady

    @staticmethod
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

        if not template_flow_path.exists():
            logging.error(f"Template steady flow file '{template_flow_path}' does not exist.")
            raise FileNotFoundError(f"Template steady flow file '{template_flow_path}' does not exist.")

        shutil.copy(template_flow_path, new_flow_path)
        logging.info(f"Copied {template_flow_path} to {new_flow_path}")

        # Read the contents of the project file
        try:
            with open(ras_obj.prj_file, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            logging.error(f"Project file not found: {ras_obj.prj_file}")
            raise

        # Prepare the new Steady Flow File entry line
        new_flow_line = f"Flow File=f{new_flow_num}\n"

        # Find the correct insertion point for the new Steady Flow File entry
        flow_file_pattern = re.compile(r'^Flow File=f(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = flow_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number < int(new_flow_num):
                    continue
                else:
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_flow_line)
            logging.info(f"Inserted new steady flow line at index {insertion_index}")
        else:
            # Try to insert after the last Steady Flow File entry
            flow_indices = [i for i, line in enumerate(lines) if flow_file_pattern.match(line.strip())]
            if flow_indices:
                last_flow_index = flow_indices[-1]
                lines.insert(last_flow_index + 1, new_flow_line)
                logging.info(f"Inserted new steady flow line after index {last_flow_index}")
            else:
                # Append at the end if no Steady Flow File entries exist
                lines.append(new_flow_line)
                logging.info(f"Appended new steady flow line at the end of the project file")

        try:
            # Write the updated lines back to the project file
            with open(ras_obj.prj_file, 'w') as f:
                f.writelines(lines)
            logging.info(f"Updated {ras_obj.prj_file} with new steady flow file f{new_flow_num}")
        except IOError as e:
            logging.error(f"Failed to write updated project file: {e}")
            raise

        new_steady = new_flow_num
        
        # Re-initialize the ras global object
        ras_obj.initialize(ras_obj.project_folder, ras_obj.ras_exe_path)
        
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        return new_steady

    @staticmethod
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
        logging.debug(f"Updated geometry entries:\n{ras_obj.geom_df}")

        template_geom_filename = f"{ras_obj.project_name}.g{template_geom}"
        template_geom_path = ras_obj.project_folder / template_geom_filename

        if not template_geom_path.is_file():
            logging.error(f"Template geometry file '{template_geom_path}' does not exist.")
            raise FileNotFoundError(f"Template geometry file '{template_geom_path}' does not exist.")

        next_geom_number = RasPlan.get_next_number(ras_obj.geom_df['geom_number'])

        new_geom_filename = f"{ras_obj.project_name}.g{next_geom_number}"
        new_geom_path = ras_obj.project_folder / new_geom_filename

        shutil.copyfile(template_geom_path, new_geom_path)
        logging.info(f"Copied '{template_geom_path}' to '{new_geom_path}'.")

        # Handle HDF file copy
        template_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{template_geom}.hdf"
        new_hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.g{next_geom_number}.hdf"
        if template_hdf_path.is_file():
            shutil.copyfile(template_hdf_path, new_hdf_path)
            logging.info(f"Copied '{template_hdf_path}' to '{new_hdf_path}'.")
        else:
            logging.warning(f"Template geometry HDF file '{template_hdf_path}' does not exist. Skipping '.hdf' copy.")

        try:
            with open(ras_obj.prj_file, 'r') as file:
                lines = file.readlines()
        except FileNotFoundError:
            logging.error(f"Project file not found: {ras_obj.prj_file}")
            raise

        # Prepare the new Geometry File entry line
        new_geom_line = f"Geom File=g{next_geom_number}\n"

        # Find the correct insertion point for the new Geometry File entry
        geom_file_pattern = re.compile(r'^Geom File=g(\d+)', re.IGNORECASE)
        insertion_index = None
        for i, line in enumerate(lines):
            match = geom_file_pattern.match(line.strip())
            if match:
                current_number = int(match.group(1))
                if current_number < int(next_geom_number):
                    continue
                else:
                    insertion_index = i
                    break

        if insertion_index is not None:
            lines.insert(insertion_index, new_geom_line)
            logging.info(f"Inserted new geometry line at index {insertion_index}")
        else:
            # Try to insert after the last Geometry File entry
            geom_indices = [i for i, line in enumerate(lines) if geom_file_pattern.match(line.strip())]
            if geom_indices:
                last_geom_index = geom_indices[-1]
                lines.insert(last_geom_index + 1, new_geom_line)
                logging.info(f"Inserted new geometry line after index {last_geom_index}")
            else:
                # Append at the end if no Geometry File entries exist
                lines.append(new_geom_line)
                logging.info(f"Appended new geometry line at the end of the project file")

        try:
            # Write the updated lines back to the project file
            with open(ras_obj.prj_file, 'w') as file:
                file.writelines(lines)
            logging.info(f"Updated {ras_obj.prj_file} with new geometry file g{next_geom_number}")
        except IOError as e:
            logging.error(f"Failed to write updated project file: {e}")
            raise

        new_geom = next_geom_number
        
        # Update all dataframes in the ras object
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()

        logging.debug(f"Updated geometry entries:\n{ras_obj.geom_df}")

        return new_geom

    @staticmethod
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
        ValueError: If an invalid key is provided or if the plan file is not found
        IOError: If there's an error reading the plan file

        Available keys and their expected types:
        - 'description' (str): Plan description
        - 'computation_interval' (str): Time value for computational time step (e.g., '5SEC', '2MIN')
        - 'dss_file' (str): Name of the DSS file used
        - 'flow_file' (str): Name of the flow input file
        - 'friction_slope_method' (int): Method selection for friction slope (e.g., 1, 2)
        - 'geom_file' (str): Name of the geometry input file
        - 'mapping_interval' (str): Time interval for mapping output
        - 'plan_file' (str): Name of the plan file
        - 'plan_title' (str): Title of the simulation plan
        - 'program_version' (str): Version number of HEC-RAS
        - 'run_htab' (int): Flag to run HTab module (-1 or 1)
        - 'run_post_process' (int): Flag to run post-processing (-1 or 1)
        - 'run_sediment' (int): Flag to run sediment transport module (0 or 1)
        - 'run_unet' (int): Flag to run unsteady network module (-1 or 1)
        - 'run_wqnet' (int): Flag to run water quality module (0 or 1)
        - 'short_identifier' (str): Short name or ID for the plan
        - 'simulation_date' (str): Start and end dates/times for simulation
        - 'unet_d1_cores' (int): Number of cores used in 1D calculations
        - 'unet_use_existing_ib_tables' (int): Flag for using existing internal boundary tables (-1, 0, or 1)
        - 'unet_1d_methodology' (str): 1D calculation methodology
        - 'unet_d2_solver_type' (str): 2D solver type
        - 'unet_d2_name' (str): Name of the 2D area

        Example:
        >>> computation_interval = RasPlan.get_plan_value("01", "computation_interval")
        >>> print(f"Computation interval: {computation_interval}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        valid_keys = {
            'description', 'computation_interval', 'dss_file', 'flow_file', 'friction_slope_method',
            'geom_file', 'mapping_interval', 'plan_file', 'plan_title', 'program_version',
            'run_htab', 'run_post_process', 'run_sediment', 'run_unet', 'run_wqnet',
            'short_identifier', 'simulation_date', 'unet_d1_cores', 'unet_use_existing_ib_tables',
            'unet_1d_methodology', 'unet_d2_solver_type', 'unet_d2_name'
        }

        if key not in valid_keys:
            raise ValueError(f"Invalid key: {key}. Valid keys are: {', '.join(valid_keys)}")

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r') as file:
                content = file.read()
        except IOError as e:
            logging.error(f"Error reading plan file {plan_file_path}: {e}")
            raise

        if key == 'description':
            match = re.search(r'Begin DESCRIPTION(.*?)END DESCRIPTION', content, re.DOTALL)
            return match.group(1).strip() if match else None
        else:
            pattern = f"{key.replace('_', ' ').title()}=(.*)"
            match = re.search(pattern, content)
            return match.group(1).strip() if match else None

    @staticmethod
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
        ValueError: If an invalid key is provided or if the plan file is not found
        IOError: If there's an error reading or writing the plan file

        Note: See the docstring of get_plan_value for a full list of available keys and their types.

        Example:
        >>> RasPlan.update_plan_value("01", "computation_interval", "10SEC")
        >>> RasPlan.update_plan_value("/path/to/plan.p01", "run_htab", 1)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        valid_keys = {
            'description', 'computation_interval', 'dss_file', 'flow_file', 'friction_slope_method',
            'geom_file', 'mapping_interval', 'plan_file', 'plan_title', 'program_version',
            'run_htab', 'run_post_process', 'run_sediment', 'run_unet', 'run_wqnet',
            'short_identifier', 'simulation_date', 'unet_d1_cores', 'unet_use_existing_ib_tables',
            'unet_1d_methodology', 'unet_d2_solver_type', 'unet_d2_name'
        }

        if key not in valid_keys:
            raise ValueError(f"Invalid key: {key}. Valid keys are: {', '.join(valid_keys)}")

        plan_file_path = Path(plan_number_or_path)
        if not plan_file_path.is_file():
            plan_file_path = RasPlan.get_plan_path(plan_number_or_path, ras_object)
            if plan_file_path is None or not Path(plan_file_path).exists():
                raise ValueError(f"Plan file not found: {plan_file_path}")

        try:
            with open(plan_file_path, 'r') as file:
                lines = file.readlines()
        except IOError as e:
            logging.error(f"Error reading plan file {plan_file_path}: {e}")
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
                lines.append(f"{pattern}{value}\n")

        try:
            with open(plan_file_path, 'w') as file:
                file.writelines(lines)
            logging.info(f"Updated {key} in plan file: {plan_file_path}")
        except IOError as e:
            logging.error(f"Error writing to plan file {plan_file_path}: {e}")
            raise

        # Refresh RasPrj dataframes
        ras_obj.plan_df = ras_obj.get_plan_entries()
        ras_obj.geom_df = ras_obj.get_geom_entries()
        ras_obj.flow_df = ras_obj.get_flow_entries()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()