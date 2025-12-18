"""
Example of INVALID backward compatibility pattern (Rule 5).

This fixture demonstrates violations when migrating from standalone
functions to static classes without maintaining compatibility.
"""
from typing import Union, List
from pathlib import Path
from ras_commander.Decorators import log_call, standardize_input


# VIOLATION: Converted to static class without providing aliases
class NewClassNoAliases:
    """
    New static class that BREAKS backward compatibility.

    These methods used to be standalone functions:
    - process_data() -> NewClassNoAliases.process_data()
    - read_file() -> NewClassNoAliases.read_file()

    VIOLATION: No backward compatibility aliases provided!
    Old code using process_data() will break.
    """

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data - was standalone function before."""
        return value * 2

    @staticmethod
    @log_call
    @standardize_input
    def read_file(file_path: Union[str, Path]) -> str:
        """Read file - was standalone function before."""
        file_path = Path(file_path)
        return file_path.read_text()


# VIOLATION: Old functions now exist but don't match signatures
class NewClassWrongAliases:
    """Static class with incorrect backward compatibility."""

    @staticmethod
    @log_call
    def compute(value: int, multiplier: int = 2) -> int:
        """Compute with new parameter."""
        return value * multiplier


# VIOLATION: Alias has different signature than static method
def compute(value: int) -> int:
    """
    Old function signature doesn't match new static method.

    NewClassWrongAliases.compute() has 'multiplier' parameter,
    but this alias doesn't accept it. Breaks compatibility.
    """
    return value * 2  # Hardcoded, not calling static method


# VIOLATION: Incomplete aliases (some functions missing)
class PartialAliases:
    """Static class with some but not all aliases."""

    @staticmethod
    @log_call
    def method_one(value: int) -> int:
        """Method one."""
        return value * 2

    @staticmethod
    @log_call
    def method_two(value: int) -> int:
        """Method two."""
        return value * 3

    @staticmethod
    @log_call
    def method_three(value: int) -> int:
        """Method three."""
        return value * 4


# Only one alias provided - others missing!
def method_one(value: int) -> int:
    """Alias for method_one only."""
    return PartialAliases.method_one(value)

# VIOLATION: method_two and method_three aliases are missing!


# VIOLATION: Aliases not in __all__
__all__ = [
    'NewClassNoAliases',
    'NewClassWrongAliases',
    'PartialAliases',
    # VIOLATION: Convenience functions not listed in __all__
]
