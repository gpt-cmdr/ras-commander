"""
Operations for handling unsteady flow files in HEC-RAS projects.
"""
from pathlib import Path
from .RasPrj import ras
import re

class RasUnsteady:
    """
    Class for all operations related to HEC-RAS unsteady flow files.
    """
    
    @staticmethod
    def update_unsteady_parameters(unsteady_file, modifications, ras_object=None):
        """
        Modify parameters in an unsteady flow file.
        
        Parameters:
        unsteady_file (str): Full path to the unsteady flow file
        modifications (dict): Dictionary of modifications to apply, where keys are parameter names and values are new values
        ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
        
        Returns:
        None

        Note:
            This function updates the ras object's unsteady dataframe after modifying the unsteady flow file.
        
        Example:
            from ras_commander import RasCmdr
            
            # Initialize RAS project
            ras_cmdr = RasCmdr()
            ras_cmdr.init_ras_project(project_folder, ras_version)
            
            # Update unsteady parameters
            unsteady_file = r"path/to/unsteady_file.u01"
            modifications = {"Parameter1": "NewValue1", "Parameter2": "NewValue2"}
            RasUnsteady.update_unsteady_parameters(unsteady_file, modifications, ras_object=ras_cmdr.ras)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
        
        unsteady_path = Path(unsteady_file)
        try:
            with open(unsteady_path, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")
        except PermissionError:
            raise PermissionError(f"Permission denied when reading unsteady flow file: {unsteady_path}")
        
        updated = False
        for i, line in enumerate(lines):
            for param, new_value in modifications.items():
                if line.startswith(f"{param}="):
                    lines[i] = f"{param}={new_value}\n"
                    updated = True
                    print(f"Updated {param} to {new_value}")
        if updated:
            try:
                with open(unsteady_path, 'w') as f:
                    f.writelines(lines)
            except PermissionError:
                raise PermissionError(f"Permission denied when writing to unsteady flow file: {unsteady_path}")
            except IOError as e:
                raise IOError(f"Error writing to unsteady flow file: {unsteady_path}. {str(e)}")
            print(f"Applied modifications to {unsteady_file}")
        else:
            print(f"No matching parameters found in {unsteady_file}")

        ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
