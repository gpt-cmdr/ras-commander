from .project_config import ProjectConfig

def init_ras_project(ras_project_folder, hecras_exe_path):
    config = ProjectConfig()
    config.initialize(ras_project_folder, hecras_exe_path)
    print(f"HEC-RAS project initialized: {config.project_name}")
    return config