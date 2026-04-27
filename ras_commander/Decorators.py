from functools import wraps
from pathlib import Path
from typing import Callable
import inspect
import logging

import h5py


def log_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.debug(f"Calling {func.__name__}")
        result = func(*args, **kwargs)
        logger.debug(f"Finished {func.__name__}")
        return result
    return wrapper


def standardize_input(_func: Callable = None, file_type: str = 'plan_hdf'):
    """
    Decorator to standardize HDF path inputs.

    Supports direct HDF paths, h5py.File objects, plan selectors, and geometry
    selectors. Path resolution is delegated to RasPrjAssets so HDF-facing
    APIs share one selector policy.
    """
    if callable(_func):
        return standardize_input(file_type=file_type)(_func)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())

            if args and isinstance(args[0], type):
                args = args[1:]

            ras_object_provided = 'ras_object' in kwargs
            ras_object = kwargs.pop('ras_object', None)

            if param_names and param_names[0] == 'hdf_file':
                if not args:
                    raise ValueError("Expected h5py.File or path input")
                if isinstance(args[0], h5py.File):
                    if ras_object_provided and 'ras_object' in param_names:
                        kwargs['ras_object'] = ras_object
                    return func(*args, **kwargs)

                hdf_path = _resolve_hdf_input(args[0], file_type, ras_object, logger)
                with h5py.File(hdf_path, 'r') as hdf:
                    new_args = (hdf,) + args[1:]
                    if ras_object_provided and 'ras_object' in param_names:
                        kwargs['ras_object'] = ras_object
                    return func(*new_args, **kwargs)

            hdf_input_from_kwargs = 'hdf_path' in kwargs
            hdf_input = kwargs.pop('hdf_path', None) if hdf_input_from_kwargs else (
                args[0] if args else None
            )

            if hdf_input is None:
                if ras_object_provided and 'ras_object' in param_names:
                    kwargs['ras_object'] = ras_object
                return func(*args, **kwargs)

            hdf_path = _resolve_hdf_input(hdf_input, file_type, ras_object, logger)

            if 'hdf' in file_type:
                try:
                    with h5py.File(hdf_path, 'r') as test_file:
                        logger.debug(f"Successfully opened HDF file for validation: {test_file.filename}")
                except Exception as e:
                    logger.warning(f"Warning: Could not validate HDF file: {str(e)}")

            if hdf_input_from_kwargs or not args:
                kwargs['hdf_path'] = hdf_path
                new_args = args
            else:
                new_args = (hdf_path,) + args[1:]

            if ras_object_provided and 'ras_object' in param_names:
                kwargs['ras_object'] = ras_object

            logger.info(f"Final validated file path: {hdf_path}")
            return func(*new_args, **kwargs)

        return wrapper
    return decorator


def _resolve_hdf_input(hdf_input, file_type: str, ras_object, logger) -> Path:
    from .RasPrj import ras as default_ras
    from .RasPrjAssets import RasPrjAssets

    ras_obj = ras_object or default_ras

    if isinstance(hdf_input, h5py.File):
        return Path(hdf_input.filename)

    if isinstance(hdf_input, (str, Path)):
        candidate = Path(str(hdf_input).strip())
        if candidate.is_file():
            logger.info(f"Using direct file path: {candidate}")
            return candidate

    try:
        if hasattr(ras_obj, 'check_initialized'):
            ras_obj.check_initialized()
    except Exception as e:
        raise ValueError(f"RAS object is not initialized: {str(e)}") from e

    if file_type == 'plan_hdf':
        resolved = RasPrjAssets.plan_results_hdf(
            hdf_input,
            ras_object=ras_obj,
            must_exist=True,
        )
    elif file_type == 'geom_hdf':
        resolved = RasPrjAssets.geometry_hdf(
            hdf_input,
            ras_object=ras_obj,
            selector_kind="auto",
            must_exist=True,
        )
    elif file_type == 'plan':
        resolved = RasPrjAssets.plan_path(
            hdf_input,
            ras_object=ras_obj,
            must_exist=True,
        )
    else:
        raise ValueError(f"Invalid file type: {file_type}")

    if resolved is None or not Path(resolved).exists():
        file_type_name = "HDF file" if 'hdf' in file_type else "file"
        error_msg = f"{file_type_name} not found: {hdf_input}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    return Path(resolved)
