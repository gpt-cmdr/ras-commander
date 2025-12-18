"""
Example of VALID backward compatibility pattern (Rule 5).

This fixture demonstrates correct migration from standalone functions
to static class methods while maintaining backward compatibility.
"""
from typing import Union, List
from pathlib import Path
from ras_commander.Decorators import log_call, standardize_input


# Static class with new API
class NewStaticClass:
    """
    New static class with organized methods.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data using static method."""
        return value * 2

    @staticmethod
    @log_call
    @standardize_input
    def read_file(file_path: Union[str, Path]) -> str:
        """Read file using static method."""
        file_path = Path(file_path)
        return file_path.read_text()

    @staticmethod
    @log_call
    def compute_list(values: List[int]) -> List[int]:
        """Process list of values."""
        return [v * 2 for v in values]


# Backward compatibility aliases (OLD API still works)
def process_data(value: int) -> int:
    """
    Process data.

    This is a convenience function that calls NewStaticClass.process_data().
    See NewStaticClass.process_data() for full documentation.

    Args:
        value: Integer to process

    Returns:
        Processed value
    """
    return NewStaticClass.process_data(value)


def read_file(file_path: Union[str, Path]) -> str:
    """
    Read file.

    Convenience function that calls NewStaticClass.read_file().
    See NewStaticClass.read_file() for full documentation.

    Args:
        file_path: Path to file

    Returns:
        File contents
    """
    return NewStaticClass.read_file(file_path)


def compute_list(values: List[int]) -> List[int]:
    """
    Process list of values.

    Convenience function. See NewStaticClass.compute_list() for full documentation.
    """
    return NewStaticClass.compute_list(values)


# Module __all__ includes both class and convenience functions
__all__ = [
    'NewStaticClass',
    'process_data',
    'read_file',
    'compute_list',
]
