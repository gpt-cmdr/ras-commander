"""
Example of INVALID @standardize_input decorator usage (Rule 3).

This fixture demonstrates violations for path parameter handling.
"""
from pathlib import Path
from typing import Union
from ras_commander.Decorators import log_call


# VIOLATION: Function with Path parameter missing @standardize_input
@log_call
def read_file_no_standardize(file_path: Union[str, Path]) -> str:
    """Read file WITHOUT @standardize_input - VIOLATION."""
    # Should have @standardize_input decorator
    file_path = Path(file_path)  # Manual conversion, but decorator is better
    return file_path.read_text()


# VIOLATION: Multiple Path parameters, no @standardize_input
@log_call
def copy_file_no_decorator(source: Union[str, Path], dest: Union[str, Path]) -> bool:
    """Copy file without @standardize_input - VIOLATION."""
    source = Path(source)
    dest = Path(dest)
    dest.write_bytes(source.read_bytes())
    return True


# VIOLATION: HDF function missing @standardize_input
@staticmethod
@log_call
def read_hdf_no_standardize(hdf_path: Path) -> dict:
    """Read HDF file without @standardize_input - VIOLATION."""
    # Should use @standardize_input(file_type='plan_hdf')
    return {"path": str(hdf_path)}


class InvalidPathClass:
    """Class with path methods missing @standardize_input."""

    # VIOLATION: Method with Path parameter missing @standardize_input
    @staticmethod
    @log_call
    def process_path(file_path: Union[str, Path]) -> str:
        """Process path without @standardize_input - VIOLATION."""
        file_path = Path(file_path)
        return file_path.name


# Valid for comparison: No Path parameters
@log_call
def process_number(value: int) -> int:
    """Process number - valid without @standardize_input (no Path params)."""
    return value * 2
