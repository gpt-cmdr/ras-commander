"""
Example of INVALID no-instantiation pattern (Rule 4).

This fixture demonstrates violations of static class documentation.
"""
from ras_commander.Decorators import log_call


class InvalidStaticClassAmbiguous:
    """
    VIOLATION: Ambiguous class that looks like it should be instantiated.

    Missing documentation about whether this is a static class or instantiable.
    Has static methods but docstring doesn't clarify usage pattern.
    """

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data."""
        return value * 2


class InvalidStaticClassWithInit:
    """
    VIOLATION: Claims to be static but has real __init__ method.

    This class says it's static but allows instantiation, creating confusion.
    """

    def __init__(self, config: dict):
        """Init that stores state - contradicts static class pattern."""
        self.config = config

    @staticmethod
    @log_call
    def process_data(value: int) -> int:
        """Process data statically."""
        return value * 2


class InvalidMixedPattern:
    """
    VIOLATION: Mixes static methods with instance methods without clear purpose.

    Has both static and instance methods without clear documentation about
    when to use which pattern.
    """

    def __init__(self):
        """Init method exists."""
        self.state = 0

    @staticmethod
    @log_call
    def static_method(value: int) -> int:
        """Static method."""
        return value * 2

    @log_call
    def instance_method(self) -> int:
        """Instance method."""
        return self.state


class InvalidPoorDocumentation:
    """
    VIOLATION: Minimal documentation, unclear usage pattern.
    """

    @staticmethod
    @log_call
    def compute(value: int) -> int:
        """Compute."""
        return value * 2
