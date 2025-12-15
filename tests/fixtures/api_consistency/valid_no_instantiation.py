"""
Example of VALID no-instantiation pattern (Rule 4).

This fixture demonstrates correct documentation and enforcement.
"""
from ras_commander.Decorators import log_call


class ValidStaticClassNoInit:
    """
    Valid static class that cannot be instantiated.

    All methods are static and this class is designed to be used
    without instantiation. Do not create instances of this class.
    """

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data statically."""
        return value * 2


class ValidStaticClassWithError:
    """
    Valid static class that raises error on instantiation.

    All methods are static - do not instantiate this class.
    """

    def __init__(self):
        """Raise error to prevent instantiation."""
        raise TypeError(
            "ValidStaticClassWithError is a static class and should not be instantiated. "
            "Use static methods directly: ValidStaticClassWithError.process_data()"
        )

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data statically."""
        return value * 2


class ValidStaticClassWithDocstring:
    """
    Valid static class with clear documentation.

    This class provides static methods for data processing. All methods
    are static and designed to be called directly on the class without
    creating instances.

    Example:
        >>> result = ValidStaticClassWithDocstring.compute(42)
        >>> # NOT: instance = ValidStaticClassWithDocstring()  # Don't do this!
    """

    @staticmethod
    @log_call
    def compute(value: int) -> int:
        """Compute result."""
        return value * 3


# Valid: Exception class (designed for instantiation)
class ValidExceptionClass:
    """
    Valid instantiable class (Exception to static rule).

    This is a data container or worker class that is designed
    to be instantiated. Maintains state across method calls.
    """

    def __init__(self, name: str):
        """Initialize with name."""
        self.name = name

    @log_call
    def process(self) -> str:
        """Process with instance state."""
        return f"Processing {self.name}"
