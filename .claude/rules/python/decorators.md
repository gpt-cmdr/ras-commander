# Python Decorators

**Context**: Function decorators for logging and input standardization
**Priority**: High - used extensively throughout codebase
**Auto-loads**: Yes (applies to all Python code)

## Overview

ras-commander uses Python decorators for cross-cutting concerns like automatic logging and input standardization. Understanding these decorators is essential for maintaining consistency and following established patterns.

## Core Decorators

### @log_call - Automatic Function Call Logging

**Purpose**: Automatically log function calls with parameters and execution time

**Usage**:
```python
from ras_commander.logging_config import log_call

@log_call
def compute_plan(plan_number, dest_folder=None):
    # Function implementation
    pass
```

**What It Logs**:
- Function name and module
- All parameters and their values
- Execution start time
- Execution duration
- Return value (configurable)
- Exceptions (if raised)

**Log Output Example**:
```
2025-12-11 14:32:15 INFO [ras_commander.core] compute_plan() called with plan_number='01', dest_folder=None
2025-12-11 14:35:42 INFO [ras_commander.core] compute_plan() completed in 3m 27s
```

**Benefits**:
- Automatic audit trail of all function calls
- Performance profiling (execution time tracking)
- Debugging support (parameter inspection)
- No manual logging code needed

### @staticmethod - Static Method Decorator

**Purpose**: Define methods that don't require class instantiation

**Usage**:
```python
class RasCmdr:
    @staticmethod
    @log_call
    def compute_plan(plan_number, dest_folder=None):
        # No self or cls parameter needed
        pass
```

**Key Points**:
- No `self` or `cls` parameter
- Can be called directly on class: `RasCmdr.compute_plan()`
- Combines with `@log_call` (decorator stacking)
- See `.claude/rules/python/static-classes.md` for full pattern

**Decorator Order Matters**:
```python
@staticmethod    # Applied second (outer)
@log_call        # Applied first (inner)
def my_function():
    pass
```

### @standardize_input - Path and Type Standardization

**Purpose**: Automatically convert string paths to Path objects and standardize inputs

**Usage**:
```python
from ras_commander.utils import standardize_input
from pathlib import Path

@standardize_input
def read_geometry_file(geom_file):
    # geom_file is automatically converted to Path if string was passed
    assert isinstance(geom_file, Path)
```

**What It Does**:
- Converts string paths → `pathlib.Path` objects
- Handles both absolute and relative paths
- Normalizes path separators (Windows vs Unix)
- Type validation and conversion

**Benefits**:
- Consistent Path handling throughout codebase
- Functions accept both strings and Path objects
- Reduces boilerplate type conversion code

## Decorator Stacking Patterns

### Common Pattern: @staticmethod + @log_call

**Most Common in ras-commander**:
```python
@staticmethod
@log_call
def process_hdf_file(hdf_path, plan_number):
    # Implementation
    pass
```

**Order**: `@staticmethod` on outside, `@log_call` on inside

### Full Stack: All Three Decorators

```python
@staticmethod
@log_call
@standardize_input
def read_and_process(file_path, output_folder):
    # file_path and output_folder auto-converted to Path
    # Call logged automatically
    # No instantiation required
    pass
```

**Order**: `@staticmethod` → `@log_call` → `@standardize_input` (outer to inner)

## LoggingConfig Integration

The `@log_call` decorator integrates with ras-commander's centralized logging system:

```python
from ras_commander.logging_config import LoggingConfig

# Centralized configuration
LoggingConfig.setup_logging(
    log_level='DEBUG',
    log_to_file=True,
    log_file='ras_commander.log'
)

# All @log_call decorated functions use this config
@log_call
def my_function():
    pass  # Logs to file and console based on LoggingConfig
```

**See Also**: `.claude/rules/python/error-handling.md` for complete LoggingConfig usage

## Custom Decorators

### Creating a New Decorator

If you need a new decorator for ras-commander:

```python
from functools import wraps
import logging

def my_decorator(func):
    @wraps(func)  # Preserves function metadata
    def wrapper(*args, **kwargs):
        # Pre-execution logic
        logger = logging.getLogger(__name__)
        logger.debug(f"Calling {func.__name__}")

        # Execute function
        result = func(*args, **kwargs)

        # Post-execution logic
        logger.debug(f"{func.__name__} completed")

        return result
    return wrapper
```

**Best Practices**:
- Use `@wraps(func)` to preserve docstrings and metadata
- Follow existing logging patterns
- Document behavior in docstring
- Consider thread safety for parallel execution

## Common Patterns

### Pattern 1: HDF File Operations

```python
@staticmethod
@log_call
@standardize_input
def read_hdf_results(hdf_path, plan_number=None):
    """
    Read HDF file results.

    Args:
        hdf_path: Path to HDF file (str or Path)
        plan_number: Optional plan number

    Returns:
        Results dataframe
    """
    # hdf_path automatically converted to Path
    # Call automatically logged
    # No instantiation needed
    ...
```

### Pattern 2: Geometry Operations

```python
@staticmethod
@log_call
def get_cross_sections(geom_file, river=None, reach=None):
    """
    Extract cross sections from geometry file.

    @log_call handles all logging automatically
    @staticmethod allows direct class call
    """
    ...
```

### Pattern 3: Remote Execution

```python
# Worker classes are instantiated, so NO @staticmethod
class PsexecWorker:
    @log_call
    def execute_plan(self, plan_number):
        """
        Execute plan on remote worker.

        Note: No @staticmethod (class is instantiated)
        Still uses @log_call for logging
        """
        ...
```

## Performance Considerations

### @log_call Overhead

**Minimal Impact**:
- Logging overhead: <1ms per call typically
- File I/O: Asynchronous, non-blocking
- Benefit: Worth the cost for debugging and audit trail

**Disable if Needed**:
```python
# Temporarily disable for performance testing
LoggingConfig.setup_logging(log_level='WARNING')  # Reduce log verbosity
```

### Decorator Stacking Order

**Performance**: Order matters for efficiency

**Efficient**:
```python
@staticmethod      # Free (compile-time)
@log_call          # Minimal overhead
@standardize_input # Type conversion (small overhead)
def my_function():
    pass
```

**Reasoning**: Cheapest decorators on outside, expensive on inside

## Testing with Decorators

### Unit Testing Decorated Functions

```python
from ras_commander import RasExamples

def test_decorated_function():
    # Decorators execute normally in tests
    path = RasExamples.extract_project("Muncie")

    # @log_call will log to test output
    # @standardize_input will convert types
    # Function behavior unchanged
    assert path.exists()
```

### Mocking Decorators (If Needed)

```python
from unittest.mock import patch

def test_without_logging():
    # Patch logging to avoid test output clutter
    with patch('ras_commander.logging_config.log_call', lambda f: f):
        # Decorator bypassed, function executes normally
        result = some_decorated_function()
```

## Common Pitfalls

### ❌ Wrong Decorator Order

**Problem**:
```python
@log_call        # Should be AFTER @staticmethod
@staticmethod
def my_function():
    pass
```

**Solution**:
```python
@staticmethod    # Outer
@log_call        # Inner
def my_function():
    pass
```

### ❌ Forgetting @log_call on New Functions

**Problem**: New functions not logged, inconsistent with codebase

**Solution**: Add `@log_call` to all public functions

**Check During Code Review**:
```bash
# Find public functions without @log_call
grep -n "def [a-z_].*:" ras_commander/*.py | grep -v "@log_call"
```

### ❌ Using @staticmethod on Instantiated Classes

**Problem**:
```python
class PsexecWorker:
    @staticmethod
    def execute_plan(self, plan_number):  # Contradiction!
        pass
```

**Solution**: Remove `@staticmethod` from instantiated classes
```python
class PsexecWorker:
    @log_call
    def execute_plan(self, plan_number):
        pass
```

## Guidelines for New Code

**When adding new functions**:

1. ✅ **Always use @log_call** on public functions
2. ✅ **Use @staticmethod** if following static class pattern
3. ✅ **Use @standardize_input** if accepting path parameters
4. ✅ **Stack decorators in correct order** (static → log → standardize)
5. ✅ **Document decorator behavior** in docstring

**Example Template**:
```python
@staticmethod
@log_call
@standardize_input
def my_new_function(file_path, output_folder=None):
    """
    Brief description.

    Args:
        file_path: Path to input file (str or Path, auto-converted)
        output_folder: Optional output folder (str or Path, auto-converted)

    Returns:
        Description of return value

    Note:
        This function is logged via @log_call decorator.
        Path inputs are automatically standardized.
    """
    # Implementation
    pass
```

## See Also

- **Static Classes**: `.claude/rules/python/static-classes.md` - @staticmethod pattern
- **Error Handling**: `.claude/rules/python/error-handling.md` - LoggingConfig setup
- **Path Handling**: `.claude/rules/python/path-handling.md` - pathlib.Path usage
- **Naming Conventions**: `.claude/rules/python/naming-conventions.md` - Function naming

---

**Key Takeaway**: Use `@log_call` on all public functions for automatic logging. Stack with `@staticmethod` for static classes and `@standardize_input` for path handling.
