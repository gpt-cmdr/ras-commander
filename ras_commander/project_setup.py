# REVISION NOTE: We should be able to move these functions into the project_management.py file and delete this file. 

from pathlib import Path
from .file_operations import FileOperations

def find_hecras_project_file(folder_path):
    return FileOperations.find_hecras_project_file(folder_path)

def load_project_data(project_file):
    return {
        'ras_plan_entries': FileOperations.get_plan_entries(project_file),
        'ras_flow_entries': FileOperations.get_flow_entries(project_file),
        'ras_unsteady_entries': FileOperations.get_unsteady_entries(project_file),
        'ras_geom_entries': FileOperations.get_geom_entries(project_file)
    }