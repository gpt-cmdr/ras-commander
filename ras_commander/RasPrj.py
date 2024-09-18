"""RasPrj.py

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
"""
# Example Terminal Output for RasPrj Functions:
# print(f"\n----- INSERT TEXT HERE -----\n")

from pathlib import Path
import pandas as pd
import re

class RasPrj:
    def __init__(self):
        self.initialized = False

    def initialize(self, project_folder, ras_exe_path):
        """
        Initialize a RasPrj instance.

        This method sets up the RasPrj instance with the given project folder and RAS executable path.
        It finds the project file, loads project data, and sets the initialization flag.

        Args:
            project_folder (str or Path): Path to the HEC-RAS project folder.
            ras_exe_path (str or Path): Path to the HEC-RAS executable.

        Raises:
            ValueError: If no HEC-RAS project file is found in the specified folder.

        Note:
            This method is intended for internal use. External users should use the init_ras_project function instead.
        """
        self.project_folder = Path(project_folder)
        self.prj_file = self.find_ras_prj(self.project_folder)
        if self.prj_file is None:
            raise ValueError(f"No HEC-RAS project file found in {self.project_folder}")
        self.project_name = Path(self.prj_file).stem
        self.ras_exe_path = ras_exe_path
        self._load_project_data()
        self.initialized = True
        print(f"\n-----Initialization complete for project: {self.project_name}-----")
        print(f"Plan entries: {len(self.plan_df)}, Flow entries: {len(self.flow_df)}, Unsteady entries: {len(self.unsteady_df)}, Geometry entries: {len(self.geom_df)}\n")

    def _load_project_data(self):
        """
        Load project data from the HEC-RAS project file.

        This method initializes DataFrames for plan, flow, unsteady, and geometry entries
        by calling the _get_prj_entries method for each entry type.
        """
        # Initialize DataFrames
        self.plan_df = self._get_prj_entries('Plan')
        self.flow_df = self._get_prj_entries('Flow')
        self.unsteady_df = self._get_prj_entries('Unsteady')
        self.geom_df = self._get_prj_entries('Geom')

    def _get_prj_entries(self, entry_type):
        """
        Extract entries of a specific type from the HEC-RAS project file.

        Args:
            entry_type (str): The type of entry to extract (e.g., 'Plan', 'Flow', 'Unsteady', 'Geom').

        Returns:
            pd.DataFrame: A DataFrame containing the extracted entries.

        Note:
            This method reads the project file and extracts entries matching the specified type.
            For 'Plan' entries, it also checks for the existence of HDF results files.
        """
        # Initialize an empty list to store entries
        entries = []
        # Create a regex pattern to match the specific entry type
        pattern = re.compile(rf"{entry_type} File=(\w+)")

        # Open and read the project file
        with open(self.prj_file, 'r') as file:
            for line in file:
                # Check if the line matches the pattern
                match = pattern.match(line.strip())
                if match:
                    # Extract the file name from the matched pattern
                    file_name = match.group(1)
                    # Create a dictionary for the current entry
                    entry = {
                        f'{entry_type.lower()}_number': file_name[1:],
                        'full_path': str(self.project_folder / f"{self.project_name}.{file_name}")
                    }

                    # Special handling for Plan entries
                    if entry_type == 'Plan':
                        # Construct the path for the HDF results file
                        hdf_results_path = self.project_folder / f"{self.project_name}.p{file_name[1:]}.hdf"
                        # Add the results_path to the entry, if the file exists
                        entry['HDF_Results_Path'] = str(hdf_results_path) if hdf_results_path.exists() else None

                    # Add the entry to the list
                    entries.append(entry)

        # Convert the list of entries to a DataFrame and return it
        return pd.DataFrame(entries)

    @property
    def is_initialized(self):
        """
        Check if the RasPrj instance has been initialized.

        Returns:
            bool: True if the instance has been initialized, False otherwise.
        """
        return self.initialized

    def check_initialized(self):
        """
        Ensure that the RasPrj instance has been initialized.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        if not self.initialized:
            raise RuntimeError("Project not initialized. Call init_ras_project() first.")

    @staticmethod
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
                return prj_file.resolve()
            for prj_file in prj_files:
                with open(prj_file, 'r') as file:
                    if "Proj Title=" in file.read():
                        return prj_file.resolve()
        print("No suitable .prj file found after all checks.")
        return None

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

    def get_geom_entries(self):
        """
        Get all geometry entries from the HEC-RAS project.

        Returns:
            pd.DataFrame: A DataFrame containing all geometry entries.

        Raises:
            RuntimeError: If the project has not been initialized.
        """
        self.check_initialized()
        return self._get_prj_entries('Geom')
    
    def get_hdf_entries(self):
        """
        Get HDF entries for plans that have results.
        
        Returns:
        pd.DataFrame: A DataFrame containing plan entries with HDF results.
                  Returns an empty DataFrame if no HDF entries are found.
        """
        self.check_initialized()
        
        # Filter the plan_df to include only entries with existing HDF results
        hdf_entries = self.plan_df[self.plan_df['HDF_Results_Path'].notna()].copy()
        
        # If no HDF entries are found, return an empty DataFrame with the correct columns
        if hdf_entries.empty:
            return pd.DataFrame(columns=self.plan_df.columns)
        
        return hdf_entries
    
    def print_data(self):
        """Print all RAS Object data for this instance.
           If any objects are added, add them to the print statements below."""
        print(f"\n--- Data for {self.project_name} ---")
        print(f"Project folder: {self.project_folder}")
        print(f"PRJ file: {self.prj_file}")
        print(f"HEC-RAS executable: {self.ras_exe_path}")
        print("\nPlan files:")
        print(self.plan_df)
        print("\nFlow files:")
        print(self.flow_df)
        print("\nUnsteady flow files:")
        print(self.unsteady_df)
        print("\nGeometry files:")
        print(self.geom_df)
        print("\nHDF entries:")
        print(self.get_hdf_entries())
        print("----------------------------\n")


# Create a global instance named 'ras'
ras = RasPrj()

def init_ras_project(ras_project_folder, ras_version, ras_instance=None):
    """
    Initialize a RAS project.

    USE THIS FUNCTION TO INITIALIZE A RAS PROJECT, NOT THE INITIALIZE METHOD OF THE RasPrj CLASS.
    The initialize method of the RasPrj class only modifies the global 'ras' object.

    This function creates or initializes a RasPrj instance, providing a safer and more
    flexible interface than directly using the 'initialize' method.

    Parameters:
    -----------
    ras_project_folder : str
        The path to the RAS project folder.
    ras_version : str
        The version of RAS to use (e.g., "6.5").
        The version can also be a full path to the Ras.exe file. (Useful when calling ras objects for folder copies.)
    ras_instance : RasPrj, optional
        An instance of RasPrj to initialize. If None, the global 'ras' instance is used.

    Returns:
    --------
    RasPrj
        An initialized RasPrj instance.

    Usage:
    ------
    1. For general use with a single project:
        init_ras_project("/path/to/project", "6.5")
        # Use the global 'ras' object after initialization

    2. For managing multiple projects:
        project1 = init_ras_project("/path/to/project1", "6.5", ras_instance=RasPrj())
        project2 = init_ras_project("/path/to/project2", "6.5", ras_instance=RasPrj())

    Notes:
    ------
    - This function is preferred over directly calling the 'initialize' method.
    - It supports both the global 'ras' object and custom instances.
    - Be consistent in your approach: stick to either the global 'ras' object
      or custom instances throughout your script or application.
    - Document your choice of approach clearly in your code.

    Warnings:
    ---------
    Avoid mixing use of the global 'ras' object and custom instances to prevent
    confusion and potential bugs.
    """

    if not Path(ras_project_folder).exists():
        raise FileNotFoundError(f"The specified RAS project folder does not exist: {ras_project_folder}. Please check the path and try again.")

    ras_exe_path = get_ras_exe(ras_version)

    if ras_instance is None:
        print(f"\n-----Initializing global 'ras' object via init_ras_project function-----")
        ras_instance = ras
    elif not isinstance(ras_instance, RasPrj):
        print(f"\n-----Initializing custom RasPrj instance via init_ras_project function-----")
        raise TypeError("ras_instance must be an instance of RasPrj or None.")

    # Initialize the RasPrj instance
    ras_instance.initialize(ras_project_folder, ras_exe_path)

    #print(f"\n-----HEC-RAS project initialized via init_ras_project function: {ras_instance.project_name}-----\n")
    return ras_instance


def get_ras_exe(ras_version):
    """
    Determine the HEC-RAS executable path based on the input.
    
    Args:
    ras_version (str): Either a version number or a full path to the HEC-RAS executable.
    
    Returns:
    str: The full path to the HEC-RAS executable.
    
    Raises:
    ValueError: If the input is neither a valid version number nor a valid file path.
    FileNotFoundError: If the executable file does not exist at the specified or constructed path.
    """
    ras_version_numbers = [
        "6.5", "6.4.1", "6.3.1", "6.3", "6.2", "6.1", "6.0",
        "5.0.7", "5.0.6", "5.0.5", "5.0.4", "5.0.3", "5.0.1", "5.0",
        "4.1", "4.0", "3.1.3", "3.1.2", "3.1.1", "3.0", "2.2"
    ]
    
    hecras_path = Path(ras_version)
    
    if hecras_path.is_file() and hecras_path.suffix.lower() == '.exe':
        return str(hecras_path)
    
    if ras_version in ras_version_numbers:
        default_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/Ras.exe")
        if default_path.is_file():
            return str(default_path)
        else:
            raise FileNotFoundError(f"HEC-RAS executable not found at the expected path: {default_path}")
    
    try:
        version_float = float(ras_version)
        if version_float > max(float(v) for v in ras_version_numbers):
            newer_version_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/Ras.exe")
            if newer_version_path.is_file():
                return str(newer_version_path)
            else:
                raise FileNotFoundError(f"Newer version of HEC-RAS was specified. Check the version number or pass the full Ras.exe path as the function argument instead of the version number. The script looked for the executable at: {newer_version_path}")
    except ValueError:
        pass
    
    raise ValueError(f"Invalid HEC-RAS version or path: {ras_version}. "
                     f"Please provide a valid version number from {ras_version_numbers} "
                     "or a full path to the HEC-RAS executable.")