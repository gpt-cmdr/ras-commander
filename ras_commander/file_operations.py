"""
File operations for HEC-RAS project files.
"""
import re
from pathlib import Path
import pandas as pd

class FileOperations:
    """
    A class for HEC-RAS file operations.
    
    
    Revision Notes: All functions from class ProjectManager should be moved here
    
    
    """
    @staticmethod
    def find_hecras_project_file(folder_path):
        """
        Find the appropriate HEC-RAS project file (.prj) in the given folder.
        
        Parameters:
        folder_path (str or Path): Path to the folder containing HEC-RAS files.
        
        Returns:
        Path: The full path of the selected .prj file or None if no suitable file is found.
        """
        print(f"running find_hecras_project_file with folder_path: {folder_path}")
        folder_path = Path(folder_path)
        print("Searching for .prj files...")
        prj_files = list(folder_path.glob("*.prj"))
        # print(f"Found {len(prj_files)} .prj files")
        # print("Searching for .rasmap files...")
        rasmap_files = list(folder_path.glob("*.rasmap"))
        #print(f"Found {len(rasmap_files)} .rasmap files")
        if len(prj_files) == 1:
            project_file = prj_files[0]
            # print(f"Only one .prj file found. Selecting: {project_file}")
            # print(f"Full path: {project_file.resolve()}")
            return project_file.resolve()
        if len(prj_files) > 1:
            print("Multiple .prj files found.")
            if len(rasmap_files) == 1:
                base_filename = rasmap_files[0].stem
                project_file = folder_path / f"{base_filename}.prj"
                # print(f"Found single .rasmap file. Using its base name: {base_filename}")
                # print(f"Full path: {project_file.resolve()}")
                return project_file.resolve()
            print("Multiple .prj files and no single .rasmap file. Searching for 'Proj Title=' in .prj files...")
            for prj_file in prj_files:
                # print(f"Checking file: {prj_file.name}")
                with open(prj_file, 'r') as file:
                    if "Proj Title=" in file.read():
                        # print(f"Found 'Proj Title=' in file: {prj_file.name}")
                        # print(f"Full path: {prj_file.resolve()}")
                        return prj_file.resolve()
        print("No suitable .prj file found after all checks.")
        return project_file

    @staticmethod
    def get_project_name(project_path):
        """
        Extract the project name from the given project path.
        
        Parameters:
        project_path (Path): Path object representing the project file path
        
        Returns:
        str: The project name derived from the file name without extension
        """
        project_name = project_path.stem
        return project_name

    @staticmethod
    def get_plan_entries(project_file):
        """
        Parse HEC-RAS project file and create dataframe for plan entries.
        
        Parameters:
        project_file (str): Full path to HEC-RAS project file (.prj)
        
        Returns:
        pandas DataFrame: DataFrame containing plan entries
        """
        project_path = Path(project_file)
        project_name = FileOperations.get_project_name(project_path)
        project_dir = project_path.parent

        with open(project_file, 'r') as f:
            content = f.read()

        plan_entries = re.findall(r'Plan File=(.*?)(?:\n|$)', content)

        ras_plan_entries = pd.DataFrame({
            'plan_number': [re.findall(r'\d+', entry)[0] for entry in plan_entries],
            'file_name': [f"{project_name}.{entry.strip().zfill(2)}" for entry in plan_entries],
            'full_path': [str(project_dir / f"{project_name}.{entry.strip().zfill(2)}") for entry in plan_entries],
            'results_path': [str(project_dir / f"{project_name}.{entry.strip().zfill(2)}.hdf") for entry in plan_entries]
        })

        return ras_plan_entries

    @staticmethod
    def get_flow_entries(project_file):
        """
        Parse HEC-RAS project file and create dataframe for flow entries.
        
        Parameters:
        project_file (str): Full path to HEC-RAS project file (.prj)
        
        Returns:
        pandas DataFrame: DataFrame containing flow entries
        """
        project_path = Path(project_file)
        project_name = FileOperations.get_project_name(project_path)
        project_dir = project_path.parent
        with open(project_file, 'r') as f:
            content = f.read()
        flow_entries = re.findall(r'Flow File=(.*?)(?:\n|$)', content)
        ras_flow_entries = pd.DataFrame({
            'flow_number': [re.findall(r'\d+', entry)[0] for entry in flow_entries],
            'file_name': [f"{project_name}.{entry.strip().zfill(2)}" for entry in flow_entries],
            'full_path': [str(project_dir / f"{project_name}.{entry.strip().zfill(2)}") for entry in flow_entries]
        })
        return ras_flow_entries

    @staticmethod
    def get_unsteady_entries(project_file):
        """
        Parse HEC-RAS project file and create dataframe for unsteady entries.
        
        Parameters:
        project_file (str): Full path to HEC-RAS project file (.prj)
        
        Returns:
        pandas DataFrame: DataFrame containing unsteady entries
        """
        project_path = Path(project_file)
        project_name = FileOperations.get_project_name(project_path)
        project_dir = project_path.parent
        with open(project_file, 'r') as f:
            content = f.read()
        unsteady_entries = re.findall(r'Unsteady File=(.*?)(?:\n|$)', content)
        ras_unsteady_entries = pd.DataFrame({
            'unsteady_number': [re.findall(r'\d+', entry)[0] for entry in unsteady_entries],
            'file_name': [f"{project_name}.{entry.strip().zfill(2)}" for entry in unsteady_entries],
            'full_path': [str(project_dir / f"{project_name}.{entry.strip().zfill(2)}") for entry in unsteady_entries]
        })
        return ras_unsteady_entries

    @staticmethod
    def get_geom_entries(project_file):
        """
        Parse HEC-RAS project file and create dataframe for geometry entries.
        
        Parameters:
        project_file (str): Full path to HEC-RAS project file (.prj)
        
        Returns:
        pandas DataFrame: DataFrame containing geometry entries
        """
        project_path = Path(project_file)
        project_name = FileOperations.get_project_name(project_path)
        project_dir = project_path.parent
        with open(project_file, 'r') as f:
            content = f.read()
        geom_entries = re.findall(r'Geom File=(.*?)(?:\n|$)', content)
        ras_geom_entries = pd.DataFrame({
            'geom_number': [re.findall(r'\d+', entry)[0] for entry in geom_entries],
            'file_name': [f"{project_name}.{entry.strip().zfill(2)}" for entry in geom_entries],
            'full_path': [str(project_dir / f"{project_name}.{entry.strip().zfill(2)}") for entry in geom_entries]
        })
        return ras_geom_entries
