# Contributing Guide

Thank you for your interest in contributing to RAS Commander!

## Development Setup

### Clone and Install

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/ras-commander.git
cd ras-commander

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Linux/Mac

# Install in editable mode
pip install -e .

# Install development dependencies
pip install pytest jupyter rasterio pyproj
```

### Using uv (Recommended)

```bash
uv venv .venv
.venv\Scripts\activate
uv pip install -e .
```

## Code Style

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Functions | snake_case | `compute_plan()` |
| Classes | PascalCase | `RasCmdr` |
| Constants | UPPER_CASE | `DEFAULT_VERSION` |
| Variables | snake_case | `plan_number` |

### Common Abbreviations

Use these consistently:

- `ras` - HEC-RAS
- `prj` - Project
- `geom` - Geometry
- `geompre` - Geometry Preprocessor
- `num` - Number
- `init` - Initialize
- `BC` - Boundary Condition
- `IC` - Initial Condition

### Function Naming

Start with verbs:
- `get_` - retrieve data
- `set_` - set values
- `compute_` - execute/calculate
- `clone_` - copy
- `clear_` - remove/reset
- `find_` - search
- `update_` - modify

### Docstrings

Use Google Python Style:

```python
def compute_plan(plan_number: str, num_cores: int = None) -> bool:
    """Execute a single HEC-RAS plan.

    Args:
        plan_number: Plan identifier (e.g., "01", "02")
        num_cores: Optional number of CPU cores

    Returns:
        True if execution succeeded, False otherwise

    Raises:
        FileNotFoundError: If plan file not found
        ValueError: If plan_number is invalid

    Examples:
        >>> success = RasCmdr.compute_plan("01")
        >>> print(f"Plan {'succeeded' if success else 'failed'}")
    """
```

### Decorators

Always use `@log_call` on public methods:

```python
from ras_commander.Decorators import log_call

class RasExample:
    @staticmethod
    @log_call
    def my_function(param: str) -> bool:
        """My function docstring."""
        pass
```

### Static Class Pattern

Use static methods (no instantiation):

```python
class RasExample:
    @staticmethod
    @log_call
    def do_something(param: str) -> bool:
        """Perform an operation."""
        return True

# Usage: RasExample.do_something("value")
# NOT: RasExample().do_something("value")
```

## Testing

### Test-Driven Development

RAS Commander uses HEC-RAS example projects for testing instead of mocks:

```python
from ras_commander import RasExamples, init_ras_project

# Extract example project
path = RasExamples.extract_project("Muncie")
init_ras_project(path, "6.5")

# Test your functionality
# ...
```

### Running Tests

```bash
# Run test scripts
python tests/test_ras_examples_initialization.py

# Run example notebooks (manual verification)
jupyter notebook examples/
```

## Pull Request Process

1. **Fork** the repository
2. **Create branch**: `git checkout -b feature/my-feature`
3. **Make changes** following style guide
4. **Test** with example notebooks
5. **Commit**: `git commit -m "Add feature X"`
6. **Push**: `git push origin feature/my-feature`
7. **Create PR** against `main` branch

### PR Checklist

- [ ] Code follows naming conventions
- [ ] Functions have docstrings with Args, Returns, Examples
- [ ] `@log_call` decorator on public methods
- [ ] Tested with HEC-RAS example project
- [ ] No hardcoded paths
- [ ] No new dependencies without justification

## Logging

Use logging, not print:

```python
from ras_commander import get_logger

logger = get_logger(__name__)

# In your function:
logger.info("Starting operation...")
logger.debug(f"Processing {count} items")
logger.warning("Unexpected condition")
logger.error(f"Operation failed: {error}")
```

## Error Handling

```python
def my_function(param: str) -> bool:
    """Function with proper error handling."""
    if not param:
        raise ValueError("param cannot be empty")

    try:
        # Operation that might fail
        result = risky_operation(param)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False

    return True
```

## Questions?

- Open an issue for questions
- Tag maintainers for review
- Join discussions in GitHub Discussions
