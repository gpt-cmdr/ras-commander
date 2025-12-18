"""
Example of VALID @standardize_input decorator usage (Rule 3).

This fixture demonstrates correct usage for path parameters.
"""
from pathlib import Path
from typing import Union
from ras_commander.Decorators import log_call, standardize_input


# Valid: Function with Path parameter uses @standardize_input
@log_call
@standardize_input
def read_file(file_path: Union[str, Path]) -> str:
    """Read file with standardized input."""
    file_path = Path(file_path)  # Now guaranteed to be Path
    return file_path.read_text()


# Valid: Multiple Path parameters
@log_call
@standardize_input
def copy_file(source: Union[str, Path], dest: Union[str, Path]) -> bool:
    """Copy file with standardized inputs."""
    source = Path(source)
    dest = Path(dest)
    dest.write_bytes(source.read_bytes())
    return True


# Valid: HDF-specific standardize_input
@staticmethod
@log_call
@standardize_input(file_type='plan_hdf')
def read_hdf(hdf_path: Path) -> dict:
    """Read HDF file with plan_hdf standardization."""
    # @standardize_input handles path resolution and validation
    return {"path": str(hdf_path)}


# Valid: Function without Path parameters doesn't need @standardize_input
@log_call
def process_number(value: int) -> int:
    """Process number - no Path parameters, no @standardize_input needed."""
    return value * 2


# Valid: Function that explicitly documents string-only parameter
@log_call
def get_filename(file_path: str) -> str:
    """
    Get filename from path.

    Args:
        file_path (str): String path (not Path object)

    Returns:
        str: Filename

    Note: This function explicitly requires string input, not Path.
    """
    return file_path.split('/')[-1]
