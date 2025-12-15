"""
Example of VALID static class pattern (Rule 1).

This fixture demonstrates correct static class usage for testing.
"""
from pathlib import Path
from typing import Union
from ras_commander.Decorators import log_call, standardize_input


class ValidStaticClass:
    """
    Example static class following ras-commander patterns.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def process_data(input_value: int) -> int:
        """Process data with static method."""
        return input_value * 2

    @staticmethod
    @log_call
    @standardize_input
    def process_file(file_path: Union[str, Path]) -> str:
        """Process file with standardized input."""
        file_path = Path(file_path)
        return f"Processed: {file_path.name}"

    @staticmethod
    @log_call
    def get_metadata() -> dict:
        """Get metadata."""
        return {"version": "1.0", "author": "test"}


# Backward compatibility aliases
def process_data(input_value: int) -> int:
    """Convenience function. See ValidStaticClass.process_data."""
    return ValidStaticClass.process_data(input_value)


def process_file(file_path: Union[str, Path]) -> str:
    """Convenience function. See ValidStaticClass.process_file."""
    return ValidStaticClass.process_file(file_path)


def get_metadata() -> dict:
    """Convenience function. See ValidStaticClass.get_metadata."""
    return ValidStaticClass.get_metadata()
