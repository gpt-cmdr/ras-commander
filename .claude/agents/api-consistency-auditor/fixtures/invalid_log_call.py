"""
Example of INVALID @log_call decorator usage (Rule 2).

This fixture demonstrates violations for testing the auditor.
"""
from ras_commander.Decorators import log_call


# VIOLATION: Public function missing @log_call
def public_function_no_decorator(value: int) -> int:
    """Public function WITHOUT @log_call - VIOLATION."""
    return value * 2


# VIOLATION: Another public function missing @log_call
def process_data_no_logging(value: int) -> int:
    """Process data without logging - VIOLATION."""
    return value * 3


# VIOLATION: Public API function missing @log_call
def calculate_result(a: int, b: int) -> int:
    """Calculate result - public function missing @log_call."""
    return a + b


class InvalidClass:
    """Class with methods missing @log_call."""

    # Valid: __init__ doesn't need @log_call
    def __init__(self):
        """Init method is valid without @log_call."""
        self.value = 0

    # VIOLATION: Public method missing @log_call
    @staticmethod
    def compute(value: int) -> int:
        """Public method missing @log_call - VIOLATION."""
        return value * 2

    # VIOLATION: Another public method without @log_call
    def get_result(self) -> int:
        """Public method without @log_call - VIOLATION."""
        return self.value


# Valid: Private function doesn't need @log_call
def _private_helper(value: int) -> int:
    """Private helper - valid without @log_call."""
    return value + 1
