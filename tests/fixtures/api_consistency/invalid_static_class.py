"""
Example of INVALID static class pattern (Rule 1).

This fixture demonstrates violations for testing the auditor.
"""
from pathlib import Path
from typing import Union


class InvalidStaticClass:
    """
    Example class that VIOLATES static class pattern.

    Violations:
    - Missing @staticmethod decorator on methods
    - Missing @log_call decorator
    - Has __init__ method (should not be present in static classes)
    """

    def __init__(self):
        """This should not exist in a static class."""
        self.state = {}

    # VIOLATION: Missing @staticmethod and @log_call
    def process_data(self, input_value: int) -> int:
        """Process data without proper decorators."""
        return input_value * 2

    # VIOLATION: Missing @staticmethod (but has @log_call would still be wrong)
    def process_file(self, file_path: Union[str, Path]) -> str:
        """Process file without @staticmethod."""
        return f"Processed: {file_path}"

    # VIOLATION: Has @staticmethod but missing @log_call
    @staticmethod
    def get_metadata() -> dict:
        """Get metadata - missing @log_call."""
        return {"version": "1.0"}


# VIOLATION: No backward compatibility aliases provided
# If these were converted from standalone functions, aliases should exist
