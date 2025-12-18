"""
Example of VALID @log_call decorator usage (Rule 2).

This fixture demonstrates correct decorator usage for testing.
"""
from ras_commander.Decorators import log_call


# Valid: Public function with @log_call
@log_call
def public_function(value: int) -> int:
    """Public function with proper logging."""
    return value * 2


# Valid: Multiple decorators in correct order
@log_call
def process_data(value: int) -> int:
    """Process data with logging."""
    result = _helper_function(value)
    return result * 2


# Valid: Private helper function (no @log_call required)
def _helper_function(value: int) -> int:
    """Private helper function - no @log_call needed."""
    return value + 1


# Valid: Decorator function (doesn't need @log_call)
def my_decorator(func):
    """Decorator function - doesn't need @log_call."""
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# Valid: Property (doesn't need @log_call)
class ValidClass:
    """Class with valid property."""

    @property
    def value(self):
        """Property - doesn't need @log_call."""
        return 42


# Valid: Dunder method (doesn't need @log_call)
class ValidDunder:
    """Class with valid dunder methods."""

    def __init__(self):
        """Dunder method - doesn't need @log_call."""
        self.value = 0

    def __str__(self):
        """Dunder method - doesn't need @log_call."""
        return f"Value: {self.value}"

    # But public method needs @log_call
    @log_call
    def get_value(self):
        """Public method - needs @log_call."""
        return self.value
