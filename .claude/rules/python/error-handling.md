# Error Handling and Logging

**Context**: Centralized logging with LoggingConfig
**Priority**: High - affects all error reporting
**Auto-loads**: Yes (applies to all Python code)

## Overview

ras-commander uses a centralized logging system via `LoggingConfig` class. All errors, warnings, and informational messages are logged consistently using Python's logging module with automatic configuration.

## LoggingConfig - Centralized Logging

### Setup

```python
from ras_commander.logging_config import LoggingConfig

# Configure logging at application start
LoggingConfig.setup_logging(
    log_level='INFO',           # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_to_file=True,           # Enable file logging
    log_file='ras_commander.log' # Log file path
)
```

### Log Levels

| Level | When to Use | Example |
|-------|-------------|---------|
| **DEBUG** | Detailed diagnostic information | Variable values, execution flow |
| **INFO** | Confirmation that things work | "Plan executed successfully" |
| **WARNING** | Unexpected but recoverable | "Missing optional parameter, using default" |
| **ERROR** | Serious problem, function failed | "File not found", "Parse error" |
| **CRITICAL** | System failure, cannot continue | "Database corrupted", "Out of memory" |

### Logging in Functions

Use Python's logging module with `@log_call` decorator:

```python
from ras_commander.logging_config import log_call
import logging

logger = logging.getLogger(__name__)

@log_call
def process_geometry(geom_file):
    logger.info(f"Processing geometry file: {geom_file}")

    if not geom_file.exists():
        logger.error(f"Geometry file not found: {geom_file}")
        raise FileNotFoundError(f"File not found: {geom_file}")

    logger.debug(f"Reading file: {geom_file}")
    content = geom_file.read_text()

    logger.info("Geometry file processed successfully")
    return content
```

## Exception Patterns

### Raise Appropriate Exceptions

**✅ Use built-in exceptions when possible**:
```python
# File not found
raise FileNotFoundError(f"Geometry file not found: {geom_file}")

# Invalid parameter
raise ValueError(f"Invalid plan number: {plan_number}")

# Type error
raise TypeError(f"Expected Path, got {type(file_path)}")

# Not implemented
raise NotImplementedError("This worker type not yet supported")

# Index out of range
raise IndexError(f"Cross section {index} out of range")

# Key not found
raise KeyError(f"Plan {plan_number} not in project")
```

### Custom Exceptions (When Needed)

```python
# Define custom exception for domain-specific errors
class HecRasExecutionError(Exception):
    """Raised when HEC-RAS computation fails"""
    pass

# Use in code
if not hdf_file.exists():
    raise HecRasExecutionError(f"HEC-RAS failed to create HDF: {hdf_file}")
```

## Error Handling Patterns

### Pattern 1: Try-Except with Logging

```python
import logging
logger = logging.getLogger(__name__)

def read_plan_file(plan_file):
    try:
        content = plan_file.read_text()
        logger.info(f"Successfully read plan file: {plan_file}")
        return content
    except FileNotFoundError:
        logger.error(f"Plan file not found: {plan_file}")
        raise
    except PermissionError:
        logger.error(f"Permission denied reading: {plan_file}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error reading {plan_file}: {e}")
        raise
```

### Pattern 2: Validation with Clear Messages

```python
def validate_plan_number(plan_number):
    if not isinstance(plan_number, str):
        raise TypeError(f"Plan number must be string, got {type(plan_number)}")

    if not plan_number.isdigit():
        raise ValueError(f"Plan number must be numeric, got '{plan_number}'")

    if not (1 <= int(plan_number) <= 99):
        raise ValueError(f"Plan number must be 01-99, got '{plan_number}'")

    return plan_number
```

### Pattern 3: Graceful Degradation

```python
import logging
logger = logging.getLogger(__name__)

def get_optional_data(hdf_file, dataset_name):
    try:
        data = hdf_file[dataset_name][:]
        return data
    except KeyError:
        logger.warning(f"Optional dataset '{dataset_name}' not found")
        return None  # Graceful degradation
```

## Logging Best Practices

### ✅ Log at Appropriate Levels

```python
import logging
logger = logging.getLogger(__name__)

@log_call
def compute_plan(plan_number):
    logger.debug(f"Starting computation for plan {plan_number}")

    logger.info(f"Executing HEC-RAS plan {plan_number}")

    if optional_param is None:
        logger.warning("Optional parameter not provided, using default")

    try:
        result = hecras.compute()
    except Exception as e:
        logger.error(f"HEC-RAS computation failed: {e}")
        raise

    logger.info("Computation completed successfully")
    return result
```

### ✅ Include Context in Log Messages

**Bad** (no context):
```python
logger.error("File not found")
```

**Good** (with context):
```python
logger.error(f"Geometry file not found: {geom_file} for plan {plan_number}")
```

### ✅ Use String Formatting, Not Concatenation

**Bad**:
```python
logger.info("Processing " + str(plan_number))
```

**Good**:
```python
logger.info(f"Processing plan {plan_number}")
```

## Rotating File Logs

ras-commander uses rotating file logs to prevent unbounded growth:

```python
from ras_commander.logging_config import LoggingConfig

# Logs automatically rotate:
# - ras_commander.log (current)
# - ras_commander.log.1 (previous)
# - ras_commander.log.2 (older)
# ... up to 5 backup files

LoggingConfig.setup_logging(
    log_to_file=True,
    log_file='ras_commander.log'
)
```

**Features**:
- Max file size: 10 MB (configurable)
- Max backup files: 5 (configurable)
- Old logs automatically compressed/deleted

## Common Pitfalls

### ❌ Swallowing Exceptions

**Bad**:
```python
try:
    result = risky_operation()
except Exception:
    pass  # Exception lost!
```

**Good**:
```python
try:
    result = risky_operation()
except Exception as e:
    logger.error(f"Operation failed: {e}")
    raise  # Re-raise after logging
```

### ❌ Too Broad Exception Handling

**Bad**:
```python
try:
    process_file()
except Exception:
    # Catches everything, even KeyboardInterrupt!
    pass
```

**Good**:
```python
try:
    process_file()
except (FileNotFoundError, PermissionError) as e:
    # Specific exceptions only
    logger.error(f"File access error: {e}")
    raise
```

### ❌ Logging Without Exceptions

**Bad** (logs error but doesn't raise):
```python
if not file.exists():
    logger.error("File not found")
    return None  # Caller doesn't know error occurred!
```

**Good** (logs and raises):
```python
if not file.exists():
    logger.error(f"File not found: {file}")
    raise FileNotFoundError(f"File not found: {file}")
```

## Testing Error Handling

### Pattern: Test Expected Exceptions

```python
import pytest
from ras_commander import RasGeometry

def test_invalid_plan_number():
    with pytest.raises(ValueError, match="Plan number must be 01-99"):
        RasGeometry.validate_plan("100")

def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        RasGeometry.read_file(Path("/nonexistent/file.g01"))
```

## See Also

- **Decorators**: `.claude/rules/python/decorators.md` - @log_call decorator
- **Path Handling**: `.claude/rules/python/path-handling.md` - FileNotFoundError patterns

---

**Key Takeaway**: Use `LoggingConfig` for centralized logging, `@log_call` for automatic function logging, and raise appropriate exceptions with clear messages.
