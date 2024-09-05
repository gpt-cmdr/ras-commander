from pathlib import Path
from .project_setup import find_hecras_project_file, load_project_data

# Notes (do note delete):
# This ProjectConfig class is a singleton, so it will have the same values for all instances.
# The class is very important for the project setup, as it will be used to store all the project's basic information.
# Instead of having to pass around the project folder, project file, etc., we can just pass around the ProjectConfig class instance.
# The class will need to be initialized with the project folder, which will then be used to set all the other project information.
# The project information will be stored in the instance as class variables.

# Documentation Notes: 
# print each variable name and value after it is defined, so the user can easily reference the project's basic information using the self. class variables 
# example: print(f"self.project_file: {self.project_file}")

class ProjectConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProjectConfig, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def initialize(self, project_folder, hecras_exe_path):
        self.project_folder = Path(project_folder)
        print(f"self.project_folder: {self.project_folder}")
        
        self.project_file = find_hecras_project_file(self.project_folder)
        print(f"self.project_file: {self.project_file}")
        
        if self.project_file is None:
            raise ValueError(f"No HEC-RAS project file found in {self.project_folder}")
        
        self.project_name = self.project_file.stem
        print(f"self.project_name: {self.project_name}")
        
        self.hecras_exe_path = hecras_exe_path
        print(f"self.hecras_exe_path: {self.hecras_exe_path}")
        
        self._load_project_data()
        self.initialized = True
        print(f"self.initialized: {self.initialized}")

    def _load_project_data(self):
        data = load_project_data(self.project_file)
        self.ras_plan_entries = data['ras_plan_entries']
        print(f"self.ras_plan_entries: {self.ras_plan_entries}")
        
        self.ras_flow_entries = data['ras_flow_entries']
        print(f"self.ras_flow_entries: {self.ras_flow_entries}")
        
        self.ras_unsteady_entries = data['ras_unsteady_entries']
        print(f"self.ras_unsteady_entries: {self.ras_unsteady_entries}")
        
        self.ras_geom_entries = data['ras_geom_entries']
        print(f"self.ras_geom_entries: {self.ras_geom_entries}")

    @property
    def is_initialized(self):
        return self.initialized

    def check_initialized(self):
        if not self.initialized:
            raise RuntimeError("Project not initialized. Call init_ras_project() first.")