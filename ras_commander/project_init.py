from .project_config import ProjectConfig
from pathlib import Path

def init_ras_project(ras_project_folder, hecras_version_or_path):
    """
    Initialize a HEC-RAS project.

    This function sets up a HEC-RAS project by validating the project folder,
    determining the HEC-RAS executable path, and initializing the project configuration.

    Args:
        ras_project_folder (str): Path to the HEC-RAS project folder.
        hecras_version_or_path (str): Either the HEC-RAS version number or the full path to the HEC-RAS executable.

    Returns:
        ProjectConfig: An initialized ProjectConfig object containing the project configuration.

    Raises:
        FileNotFoundError: If the specified RAS project folder does not exist.

    Note:
        This function prints a confirmation message upon successful initialization.
        
    Future Development Roadmap: 
    
    1. Load critical keys and values from the project files into the project config
        Implemented:
        - Project Name
        - Project Folder
        - Lists of plan, flow, unsteady, and geometry files
        - HEC-RAS Executable Path
        
        Not Implemented:
        - Units 
        - Coordinate System 
        - rasmap file path (replace prj file path extension with ".rasmap" and add it to the project config)
        - Current Plan
        - Description (including checks to see if it is a valid string and within the default max length)
        - DSS Start Date=01JAN1999 (note format is MMDDYYY)
        - DSS Start Time=1200 (note format is HHMM)
        - DSS End Date=04JAN1999 (note format is MMDDYYY)
        - DSS End Time=1200 (note format is HHMM)
        - DSS File=dss
        - DSS File=Bald_Eagle_Creek.dss 
              
    Other not implemented:
    
    2. Load critical keys and lists of string values from the plan files into the project config
        - Plan Title
        - Plan Shortid
        - Simulation Date
        - Geometry File
        - Flow File (may not be present) - if present, the plan is a 1D steady plan
        - Unsteady File (may not be present) - if present, the plan is a 1D or 2D unsteady plan
        - UNET D2 Name (may not be present) - if present, the plan is a 2D plan
        - Type (1D Steady, 1D Unsteady, 1D/2D, or 2D)
        - UNET 1D Methodology
       
    3. Load critical keys and strings from the unsteady flow files into the project config
        - Flow Title
        - Pandas Dataframe for any Boundary Conditions present and whether they are defined in the file or whether they use a DSS file input
           - One dataframe for all unsteady flow files, with each Boundary Location in each file having its own row
           - For each unsteady flow filereturn an appended dataframe with each boundary condition and it's "Boundary Name", "Interval", "DSS Path", "Flow Hydrograph Slope", and whether Use DSS is True or False
           - Need to incorporate knowledge from the excel methods we used for setting boundary conditions
           
    4. Load critical keys and strings from the steady flow files into the project config
        - Flow Title
        - Since steady models are not as commonly used, this is a low priority integration (external contributions are welcome)
               
    
    5. Load critical keys and values from the rasmap file into the project config
        - rasmap_projection_string
        - Version   #Ex: <Version>2.0.0</Version> 
        - RASProjectionFilename Filename=".\Terrain\Projection.prj"
        
        - List of ras terrains as pandas dataframes
            - for each, list of tiff files and order
            - flag whether terrain mods exist 
            
        - List of Infiltration hdf files as pandas dataframes
            - Mapping of infiltration layers to geometries
            
        - List of land cover hdf files as pandas dataframes
            - Mapping of land cover to geometries
        
        - List of all Mannings N layers, hdf files and mapping to geometries as pandas dataframes
            
    6. Create a list of all valid hdf plan files are present in the project folder, and flag whether they contain a completed simulation
    
    This roadmap for the project_init function will provide the basic information needed to support most basic hec-ras automation workflows.  
    
    Remember, this project init might be called multiple times.  Every time, it should clear any previously created datafrarmes and variables and replace them.  It is important that revisions can be made, init be re-run, and information is current and reflects the current state of the project. 

        
        
    """
    # Check if the provided paths exist
    if not Path(ras_project_folder).exists():
        raise FileNotFoundError(f"The specified RAS project folder does not exist: {ras_project_folder}, Please check the path and try again.")
    
    hecras_exe_path = get_hecras_exe_path(hecras_version_or_path)
    
    config = ProjectConfig()
    config.initialize(ras_project_folder, hecras_exe_path)
    print(f"HEC-RAS project initialized: {config.project_name}")
    return config


def get_hecras_exe_path(hecras_version_or_path):
    """
    Determine the HEC-RAS executable path based on the input.
    
    Args:
    hecras_version_or_path (str): Either a version number or a full path to the HEC-RAS executable.
    
    Returns:
    str: The full path to the HEC-RAS executable.
    
    Raises:
    ValueError: If the input is neither a valid version number nor a valid file path.
    FileNotFoundError: If the executable file does not exist at the specified or constructed path.
    """
    
    
    # hecras_exe_path should be changed to hecras_version_or_path
    # Based on whether a full path is provided, or a version number is provided, the path will be set accordingly
    # By default, HEC-RAS is installed in the Program Files (x86) folder 
    # For example: hecras_exe_path = r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe" for version 6.5
    # an f string to build the path based on the version number
    # hecras_exe_path = f"C:\Program Files (x86)\HEC\HEC-RAS\{hecras_version}\Ras.exe"
    # where hecras_version is one of the following: 
    
    # List of HEC-RAS version numbers
    ras_version_numbers = [
        "6.5", "6.4.1", "6.3.1", "6.3", "6.2", "6.1", "6.0",
        "5.0.7", "5.0.6", "5.0.5", "5.0.4", "5.0.3", "5.0.1", "5.0",
        "4.1", "4.0", "3.1.3", "3.1.2", "3.1.1", "3.0", "2.2"
    ]
    
    hecras_path = Path(hecras_version_or_path)
    
    # Check if the input is a full path
    if hecras_path.is_file() and hecras_path.suffix.lower() == '.exe':
        return str(hecras_path)
    
    # Check if the input is a version number
    if hecras_version_or_path in ras_version_numbers:
        default_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{hecras_version_or_path}/Ras.exe")
        if default_path.is_file():
            return str(default_path)
        else:
            raise FileNotFoundError(f"HEC-RAS executable not found at the expected path: {default_path}")
    
    # Check if it's a newer version
    try:
        version_float = float(hecras_version_or_path)
        if version_float > max(float(v) for v in ras_version_numbers):
            newer_version_path = Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{hecras_version_or_path}/Ras.exe")
            if newer_version_path.is_file():
                return str(newer_version_path)
            else:
                raise FileNotFoundError(f"Newer version of HEC-RAS was specified. Check the version number or pass the full Ras.exe path as the function argument instead of the version number. The script looked for the executable at: {newer_version_path}")
    except ValueError:
        pass  # Not a valid float, so not a version number
    
    raise ValueError(f"Invalid HEC-RAS version or path: {hecras_version_or_path}. "
                     f"Please provide a valid version number from {ras_version_numbers} "
                     "or a full path to the HEC-RAS executable.")
    # Return the validated HEC-RAS executable path
    return hecras_exe_path




