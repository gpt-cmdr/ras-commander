from functools import wraps
from pathlib import Path
from typing import Union
import logging
import h5py
import inspect


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
            
            # If first parameter is 'hdf_file', skip path processing
            if param_names and param_names[0] == 'hdf_file':
                return func(*args, **kwargs)
                
            # Handle both static method calls and regular function calls
            if args and isinstance(args[0], type):
                # Static method call, remove the class argument
                args = args[1:]
            
            hdf_input = kwargs.pop('hdf_path', None) or kwargs.pop('hdf_input', None) or (args[0] if args else None)
            
            # Import ras here to ensure we get the most current instance
            from .RasPrj import ras as ras
            ras_object = kwargs.pop('ras_object', None) or (args[1] if len(args) > 1 else None)
            ras_obj = ras_object or ras

            # If no hdf_input provided, return the function unmodified
            if hdf_input is None:
                return func(*args, **kwargs)

            # NEW: If input is already a Path and exists, use it directly regardless of file_type
            if isinstance(hdf_input, Path) and hdf_input.is_file():
                logger.info(f"Using existing HDF file: {hdf_input}")
                new_args = (hdf_input,) + args[1:]
                return func(*new_args, **kwargs)

            hdf_path = None

            # If hdf_input is already an h5py.File object, use its filename
            if isinstance(hdf_input, h5py.File):
                hdf_path = Path(hdf_input.filename)
            # Handle Path objects
            elif isinstance(hdf_input, Path):
                if hdf_input.is_file():
                    hdf_path = hdf_input
            # Handle string inputs
            elif isinstance(hdf_input, str):
                # Check if it's a file path
                if Path(hdf_input).is_file():
                    hdf_path = Path(hdf_input)
                # Check if it's a number (with or without 'p' prefix)
                elif hdf_input.isdigit() or (len(hdf_input) == 3 and hdf_input[0] == 'p' and hdf_input[1:].isdigit()):
                    try:
                        ras_obj.check_initialized()
                    except Exception as e:
                        raise ValueError(f"RAS object is not initialized: {str(e)}")
                        
                    number = hdf_input if hdf_input.isdigit() else hdf_input[1:]
                    
                    if file_type == 'plan_hdf':
                        plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == number]
                        if not plan_info.empty:
                            hdf_path = Path(plan_info.iloc[0]['HDF_Results_Path'])
                    elif file_type == 'geom_hdf':
                        geom_info = ras_obj.geom_df[ras_obj.geom_df['geom_number'] == number]
                        if not geom_info.empty:
                            hdf_path = Path(geom_info.iloc[0]['HDF_Path'])
                    else:
                        raise ValueError(f"Invalid file type: {file_type}")
            # Handle integer inputs (assuming they're plan or geom numbers)
            elif isinstance(hdf_input, int):
                try:
                    ras_obj.check_initialized()
                except Exception as e:
                    raise ValueError(f"RAS object is not initialized: {str(e)}")
                    
                number = f"{hdf_input:02d}"
                
                if file_type == 'plan_hdf':
                    plan_info = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == number]
                    if not plan_info.empty:
                        hdf_path = Path(plan_info.iloc[0]['HDF_Results_Path'])
                elif file_type == 'geom_hdf':
                    geom_info = ras_obj.geom_df[ras_obj.geom_df['geom_number'] == number]
                    if not geom_info.empty:
                        hdf_path = Path(geom_info.iloc[0]['HDF_Path'])
                else:
                    raise ValueError(f"Invalid file type: {file_type}")

            if hdf_path is None or not hdf_path.is_file():
                error_msg = f"HDF file not found: {hdf_input}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)

            logger.info(f"Using HDF file: {hdf_path}")
            
            # Pass all original arguments and keywords, replacing hdf_input with standardized hdf_path
            new_args = (hdf_path,) + args[1:]
            return func(*new_args, **kwargs)

        return wrapper
    return decorator