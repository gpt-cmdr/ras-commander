from functools import wraps
from pathlib import Path
from typing import Union
import logging
import h5py
import inspect
import pandas as pd


def log_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.debug(f"Calling {func.__name__}")
        result = func(*args, **kwargs)
        logger.debug(f"Finished {func.__name__}")
        return result
    return wrapper

def standardize_input(file_type: str = 'plan_hdf'):
    """
    Decorator to standardize input for HDF file operations.
    
    This decorator processes various input types and converts them to a Path object
    pointing to the correct HDF file. It handles the following input types:
    - h5py.File objects
    - pathlib.Path objects
    - Strings (file paths or plan/geom numbers)
    - Integers (interpreted as plan/geom numbers)
    
    The decorator also manages RAS object references and logging.
    
    Args:
        file_type (str): Specifies whether to look for 'plan_hdf' or 'geom_hdf' files.
    
    Returns:
        A decorator that wraps the function to standardize its input to a Path object.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            
            # Check if the function expects an hdf_path parameter
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            
            # If first parameter is 'hdf_file', pass an h5py object
            if param_names and param_names[0] == 'hdf_file':
                if isinstance(args[0], h5py.File):
                    return func(*args, **kwargs)
                elif isinstance(args[0], (str, Path)):
                    with h5py.File(args[0], 'r') as hdf:
                        return func(hdf, *args[1:], **kwargs)
                else:
                    raise ValueError(f"Expected h5py.File or path, got {type(args[0])}")
                
            # Handle both static method calls and regular function calls
            if args and isinstance(args[0], type):
                # Static method call, remove the class argument
                args = args[1:]
            
            # Get hdf_input from kwargs if provided with hdf_path key, or take first positional arg
            hdf_input = kwargs.pop('hdf_path', None) if 'hdf_path' in kwargs else (args[0] if args else None)
            
            # Import ras here to ensure we get the most current instance
            from .RasPrj import ras as ras
            ras_object = kwargs.pop('ras_object', None) or (args[1] if len(args) > 1 else None)
            ras_obj = ras_object or ras

            # If no hdf_input provided, return the function unmodified
            if hdf_input is None:
                return func(*args, **kwargs)

            hdf_path = None

            # Clean and normalize string inputs
            if isinstance(hdf_input, str):
                # Clean the string (remove extra whitespace, normalize path separators)
                hdf_input = hdf_input.strip()
                
                # Check if it's a raw file path that exists
                try:
                    test_path = Path(hdf_input)
                    if test_path.is_file():
                        hdf_path = test_path
                        logger.info(f"Using HDF file from direct string path: {hdf_path}")
                except Exception as e:
                    logger.debug(f"Error converting string to path: {str(e)}")

            # If a valid path wasn't created from string processing, continue with normal flow
            if hdf_path is None:
                # If hdf_input is already a Path and exists, use it directly
                if isinstance(hdf_input, Path) and hdf_input.is_file():
                    hdf_path = hdf_input
                    logger.info(f"Using existing Path object HDF file: {hdf_path}")
                # If hdf_input is an h5py.File object, use its filename
                elif isinstance(hdf_input, h5py.File):
                    hdf_path = Path(hdf_input.filename)
                    logger.info(f"Using HDF file from h5py.File object: {hdf_path}")
                # Handle Path objects that might not be verified yet
                elif isinstance(hdf_input, Path):
                    if hdf_input.is_file():
                        hdf_path = hdf_input
                        logger.info(f"Using verified Path object HDF file: {hdf_path}")
                # Handle string inputs that are plan/geom numbers
                elif isinstance(hdf_input, str) and (hdf_input.isdigit() or (len(hdf_input) > 1 and hdf_input[0] == 'p' and hdf_input[1:].isdigit())):
                    try:
                        ras_obj.check_initialized()
                    except Exception as e:
                        raise ValueError(f"RAS object is not initialized: {str(e)}")
                        
                    # Extract the number part and strip leading zeros
                    number_str = hdf_input if hdf_input.isdigit() else hdf_input[1:]
                    stripped_number = number_str.lstrip('0')
                    if stripped_number == '':  # Handle case where input was '0' or '00'
                        stripped_number = '0'
                    number_int = int(stripped_number)
                    
                    if file_type == 'plan_hdf':
                        try:
                            # Convert plan_number column to integers for comparison after stripping zeros
                            plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'].str.lstrip('0').astype(int) == number_int]
                            if not plan_info.empty:
                                # Make sure HDF_Results_Path is a string and not None
                                hdf_path_str = plan_info.iloc[0]['HDF_Results_Path']
                                if pd.notna(hdf_path_str):
                                    hdf_path = Path(str(hdf_path_str))
                        except Exception as e:
                            logger.warning(f"Error retrieving plan HDF path: {str(e)}")


                    elif file_type == 'geom_hdf':
                        try:
                            # First try to get the geometry number from the plan
                            from ras_commander import RasPlan
                            plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'].astype(int) == number_int]
                            if not plan_info.empty:
                                # Extract the geometry number from the plan
                                geom_number = plan_info.iloc[0]['geometry_number']
                                if pd.notna(geom_number) and geom_number is not None:
                                    # Handle different types of geom_number (string or int)
                                    try:
                                        # Get the geometry path using RasPlan
                                        geom_path = RasPlan.get_geom_path(str(geom_number), ras_obj)
                                        
                                        if geom_path is not None:
                                            # Create the HDF path by adding .hdf to the geometry path
                                            hdf_path = Path(str(geom_path) + ".hdf")
                                            if hdf_path.exists():
                                                logger.info(f"Found geometry HDF file for plan {number_int}: {hdf_path}")
                                            else:
                                                # Try to find it in the geom_df if direct path doesn't exist
                                                geom_info = ras_obj.geom_df[ras_obj.geom_df['full_path'] == str(geom_path)]
                                                if not geom_info.empty and 'hdf_path' in geom_info.columns:
                                                    hdf_path_str = geom_info.iloc[0]['hdf_path']
                                                    if pd.notna(hdf_path_str):
                                                        hdf_path = Path(str(hdf_path_str))
                                                        logger.info(f"Found geometry HDF file from geom_df for plan {number_int}: {hdf_path}")
                                    except (TypeError, ValueError) as e:
                                        logger.warning(f"Error processing geometry number {geom_number}: {str(e)}")
                                else:
                                    logger.warning(f"No valid geometry number found for plan {number_int}")
                        except Exception as e:
                            logger.warning(f"Error retrieving geometry HDF path: {str(e)}")
                    else:
                        raise ValueError(f"Invalid file type: {file_type}")
                    


                
                # Handle integer inputs (assuming they're plan or geom numbers)
                elif isinstance(hdf_input, int):
                    try:
                        ras_obj.check_initialized()
                    except Exception as e:
                        raise ValueError(f"RAS object is not initialized: {str(e)}")
                        
                    number_int = hdf_input
                    
                    if file_type == 'plan_hdf':
                        try:
                            # Convert plan_number column to integers for comparison after stripping zeros
                            plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'].str.lstrip('0').astype(int) == number_int]
                            if not plan_info.empty:
                                # Make sure HDF_Results_Path is a string and not None
                                hdf_path_str = plan_info.iloc[0]['HDF_Results_Path']
                                if pd.notna(hdf_path_str):
                                    hdf_path = Path(str(hdf_path_str))
                        except Exception as e:
                            logger.warning(f"Error retrieving plan HDF path: {str(e)}")
                            
                    elif file_type == 'geom_hdf':
                        try:
                            # First try finding plan info to get geometry number
                            plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'].astype(int) == number_int]
                            if not plan_info.empty:
                                # Extract the geometry number from the plan
                                geom_number = plan_info.iloc[0]['geometry_number']
                                if pd.notna(geom_number) and geom_number is not None:
                                    # Handle different types of geom_number (string or int)
                                    try:
                                        # Get the geometry path using RasPlan
                                        from ras_commander import RasPlan
                                        geom_path = RasPlan.get_geom_path(str(geom_number), ras_obj)
                                        
                                        if geom_path is not None:
                                            # Create the HDF path by adding .hdf to the geometry path
                                            hdf_path = Path(str(geom_path) + ".hdf")
                                            if hdf_path.exists():
                                                logger.info(f"Found geometry HDF file for plan {number_int}: {hdf_path}")
                                            else:
                                                # Try to find it in the geom_df if direct path doesn't exist
                                                geom_info = ras_obj.geom_df[ras_obj.geom_df['full_path'] == str(geom_path)]
                                                if not geom_info.empty and 'hdf_path' in geom_info.columns:
                                                    hdf_path_str = geom_info.iloc[0]['hdf_path']
                                                    if pd.notna(hdf_path_str):
                                                        hdf_path = Path(str(hdf_path_str))
                                                        logger.info(f"Found geometry HDF file from geom_df for plan {number_int}: {hdf_path}")
                                    except (TypeError, ValueError) as e:
                                        logger.warning(f"Error processing geometry number {geom_number}: {str(e)}")
                                else:
                                    logger.warning(f"No valid geometry number found for plan {number_int}")
                        except Exception as e:
                            logger.warning(f"Error retrieving geometry HDF path: {str(e)}")
                    else:
                        raise ValueError(f"Invalid file type: {file_type}")

            # Final verification that the path exists
            if hdf_path is None or not hdf_path.exists():
                error_msg = f"HDF file not found: {hdf_input}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
                
            logger.info(f"Final validated HDF file path: {hdf_path}")
            
            # Now try to validate the HDF file structure (but don't fail if validation fails)
            try:
                with h5py.File(hdf_path, 'r') as test_file:
                    # Just open to verify it's a valid HDF5 file
                    logger.debug(f"Successfully opened HDF file for validation: {hdf_path}")
            except Exception as e:
                logger.warning(f"Warning: Could not validate HDF file: {str(e)}")
                # Continue anyway, let the function handle detailed validation
            
            # Pass all original arguments and keywords, replacing hdf_input with standardized hdf_path
            # If the original input was positional, replace the first argument
            if args and 'hdf_path' not in kwargs:
                new_args = (hdf_path,) + args[1:]
            else:
                new_args = args
                kwargs['hdf_path'] = hdf_path
                
            return func(*new_args, **kwargs)

        return wrapper
    return decorator