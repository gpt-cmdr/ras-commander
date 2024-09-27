"""
Operations for handling geometry files in HEC-RAS projects.
"""
from pathlib import Path
from typing import List, Union
from .RasPlan import RasPlan
from .RasPrj import ras
import logging
import re

# Configure logging at the module level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    # You can add a filename parameter here to log to a file
    # filename='rasgeo.log',
    # Uncomment the above line to enable file logging
)

class RasGeo:
    """
    A class for operations on HEC-RAS geometry files.
    """
    
    @staticmethod
    def clear_geompre_files(
        plan_files: Union[str, Path, List[Union[str, Path]]] = None,
        ras_object = None
    ) -> None:
        """
        Clear HEC-RAS geometry preprocessor files for specified plan files or all plan files in the project directory.
        
        Limitations/Future Work:
        - This function only deletes the geometry preprocessor file.
        - It does not clear the IB tables.
        - It also does not clear geometry preprocessor tables from the geometry HDF.
        - All of these features will need to be added to reliably remove geometry preprocessor files for 1D and 2D projects.
        
        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional): 
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object: An optional RAS object instance.
        
        Returns:
            None
        
        Examples:
            # Clear all geometry preprocessor files in the project directory
            RasGeo.clear_geompre_files()
            
            # Clear a single plan file
            RasGeo.clear_geompre_files(r'path/to/plan.p01')
            
            # Clear multiple plan files
            RasGeo.clear_geompre_files([r'path/to/plan1.p01', r'path/to/plan2.p02'])

        Note:
            This function updates the ras object's geometry dataframe after clearing the preprocessor files.
        """
        ## Explicit Function Steps
        # 1. Initialize the ras_object, defaulting to the global ras if not provided.
        # 2. Define a helper function to clear a single geometry preprocessor file.
        # 3. Determine the list of plan files to process based on the input.
        # 4. Iterate over each plan file and clear its geometry preprocessor file.
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        def clear_single_file(plan_file: Union[str, Path], ras_obj) -> None:
            plan_path = Path(plan_file)
            geom_preprocessor_suffix = '.c' + ''.join(plan_path.suffixes[1:]) if plan_path.suffixes else '.c'
            geom_preprocessor_file = plan_path.with_suffix(geom_preprocessor_suffix)
            if geom_preprocessor_file.exists():
                try:
                    logging.info(f"Deleting geometry preprocessor file: {geom_preprocessor_file}")
                    geom_preprocessor_file.unlink()
                    logging.info("File deletion completed successfully.")
                except PermissionError:
                    logging.error(f"Permission denied: Unable to delete geometry preprocessor file: {geom_preprocessor_file}.")
                    raise PermissionError(f"Unable to delete geometry preprocessor file: {geom_preprocessor_file}. Permission denied.")
                except OSError as e:
                    logging.error(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
                    raise OSError(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
            else:
                logging.warning(f"No geometry preprocessor file found for: {plan_file}")
        
        if plan_files is None:
            logging.info("Clearing all geometry preprocessor files in the project directory.")
            plan_files_to_clear = list(ras_obj.project_folder.glob(r'*.p*'))
        elif isinstance(plan_files, (str, Path)):
            plan_files_to_clear = [plan_files]
            logging.info(f"Clearing geometry preprocessor file for single plan: {plan_files}")
        elif isinstance(plan_files, list):
            plan_files_to_clear = plan_files
            logging.info(f"Clearing geometry preprocessor files for multiple plans: {plan_files}")
        else:
            logging.error("Invalid input type for plan_files.")
            raise ValueError("Invalid input. Please provide a string, Path, list of paths, or None.")
        
        for plan_file in plan_files_to_clear:
            clear_single_file(plan_file, ras_obj)
        
        # Update the geometry dataframe
        try:
            ras_obj.geom_df = ras_obj.get_geom_entries()
            logging.info("Geometry dataframe updated successfully.")
        except Exception as e:
            logging.error(f"Failed to update geometry dataframe: {str(e)}")
            raise
