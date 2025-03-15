# RAS Commander (ras-commander) Style Guide

## Table of Contents
1. [Naming Conventions](#1-naming-conventions)
2. [Code Structure and Organization](#2-code-structure-and-organization)
3. [Documentation and Comments](#3-documentation-and-comments)
4. [Code Style](#4-code-style)
5. [Error Handling](#5-error-handling)
6. [Testing](#6-testing)
7. [Version Control](#7-version-control)
8. [Type Hinting](#8-type-hinting)
9. [Project-Specific Conventions](#9-project-specific-conventions)
10. [Inheritance](#10-inheritance)
11. [RasUtils Usage](#11-rasutils-usage)
12. [Working with RasExamples](#12-working-with-rasexamples)
13. [Logging](#13-logging)
14. [Decorator Usage](#14-decorator-usage)
15. [Static Class Pattern](#15-static-class-pattern)

## 1. Naming Conventions

### 1.1 General Rules
- Use `snake_case` for all function and variable names
- Use `PascalCase` for class names
- Use `UPPER_CASE` for constants

### 1.2 Library-Specific Naming
- Informal Name: RAS Commander
- Package Name and GitHub Library Name: ras-commander (with a hyphen)
- Import Name: ras_commander (with an underscore)
- Main Class of functions for HEC-RAS Automation: RasCmdr

### 1.3 Function Naming
- Start function names with a verb describing the action
- Use clear, descriptive names
- Common verbs and their uses:
  - `get_`: retrieve data
  - `set_`: set values or properties
  - `compute_`: execute or calculate
  - `clone_`: copy
  - `clear_`: remove or reset data
  - `find_`: search
  - `update_`: modify existing data

### 1.4 Abbreviations
Use the following abbreviations consistently throughout the codebase:

- ras: HEC-RAS
- prj: Project
- geom: Geometry
- pre: Preprocessor
- geompre: Geometry Preprocessor
- num: Number
- init: Initialize
- XS: Cross Section
- DSS: Data Storage System
- GIS: Geographic Information System
- BC: Boundary Condition
- IC: Initial Condition
- TW: Tailwater

Use these abbreviations in lowercase for function and variable names (e.g., `geom`, not `Geom` or `GEOM`).

### 1.5 Class Naming
- Use `PascalCase` for class names (e.g., `FileOperations`, `PlanOperations`, `RasCmdr`)
- Class names should be nouns or noun phrases

### 1.6 Variable Naming
- Use descriptive names indicating purpose or content
- Prefix boolean variables with `is_`, `has_`, or similar

### 1.7 HDF Class Method Naming

For HDF class methods, follow these naming conventions:
- `get_` prefix for methods that extract data from HDF files
- Use specific entity names in method names: `get_mesh_max_ws()` instead of just `get_max_ws()`
- For methods that return GeoDataFrame objects, include the relevant geometry type in the name: `get_mesh_cell_polygons()`
- Prefix private helper methods with underscore: `_get_mesh_timeseries_output_path()`
- Use consistent suffixes for related methods: `get_mesh_max_ws()`, `get_mesh_min_ws()`

## 2. Code Structure and Organization

### 2.1 File Organization
- Group related functions into appropriate classes
- Keep each class in its own file, named after the class

### 2.2 Function Organization
- Order functions logically within a class
- Place common or important functions at the top of the class

### 2.3 Module Structure
- Use the following order for module contents:
  1. Module-level docstring
  2. Imports (grouped and ordered)
  3. Constants
  4. Classes
  5. Functions

## 3. Documentation and Comments

### 3.1 Docstrings
- Use docstrings for all modules, classes, methods, and functions
- Follow Google Python Style Guide format
- Include parameters, return values, and a brief description
- For complex functions, include examples in the docstring

### 3.2 Comments
- Use inline comments sparingly, only for complex logic
- Keep comments up-to-date with code changes
- Use TODO comments for future work, formatted as: `# TODO: description`

## 4. Code Style

### 4.1 Imports
- Order imports as follows:
  1. Standard library imports
  2. Third-party library imports
  3. Local application imports
- Use absolute imports
- Use `import ras_commander as ras` for shortening the library name in examples

### 4.2 Whitespace
- Follow PEP 8 guidelines
- Use 4 spaces for indentation (no tabs)
- Use blank lines to separate logical sections of code

### 4.3 Line Length
- Limit lines to 79 characters for code, 72 for comments and docstrings
- Use parentheses for line continuation in long expressions

## 5. Error Handling

**Use Logging Instead of Prints**
Ensure that every operation that can fail or needs to provide feedback to the user is logged instead of using `print`. This will help in debugging and improve monitoring during execution.

   ```python
   logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
   ```

   Example of replacing a `print` with logging:
   ```python
   logging.info('Starting HEC-RAS simulation...')
   ```

- Use explicit exception handling with try/except blocks
- Raise custom exceptions when appropriate, with descriptive messages
- Use logging for error reporting and debugging information
- Use specific exception types when raising errors (e.g., `ValueError`, `FileNotFoundError`)
- Provide informative error messages that include relevant details
- Implement proper cleanup in finally blocks when necessary
- For user-facing functions, consider wrapping internal exceptions in custom exceptions specific to ras-commander

Example:
```python
try:
    result = compute_plan(plan_number)
except FileNotFoundError as e:
    raise RasCommanderError(f"Plan file not found: {e}")
except ValueError as e:
    raise RasCommanderError(f"Invalid plan parameter: {e}")
except Exception as e:
    raise RasCommanderError(f"Unexpected error during plan computation: {e}")
```

### 5.1 Logging Configuration

- Always use the module-specific logger from `LoggingConfig`:
  ```python
  from .LoggingConfig import get_logger
  logger = get_logger(__name__)
  ```

- Use appropriate log levels:
  - DEBUG: Detailed information useful for debugging
  - INFO: Confirmation of expected operations
  - WARNING: Something unexpected happened but execution continues
  - ERROR: An operation failed but the program can continue
  - CRITICAL: Program cannot continue

- Include informative context in log messages:
  ```python
  logger.info(f"Processing file: {file_path}")
  logger.error(f"Failed to read HDF file {hdf_path}: {str(e)}")
  ```

- Use the `@log_call` decorator for automatic function entry/exit logging

## 6. Testing

- The RasExamples() Class is provided for testing directly with HEC Example projects
- The library eschews traditional unit testing in favor of this approach
- The unit tests double as useful examples that can be extended by end users 
- Any notebooks in the repo should include a working model (hosted elsewhere) 

## 7. Version Control

- Use meaningful commit messages that clearly describe the changes made
- Create feature branches for new features or significant changes
- Submit pull requests for code review before merging into the main branch
- Keep commits focused and atomic (one logical change per commit)
- Use git tags for marking releases
- Follow semantic versioning for release numbering

## 8. Type Hinting

- Use type hints for all function parameters and return values
- Use the `typing` module for complex types (e.g., `List`, `Dict`, `Optional`)
- Include type hints in function signatures and docstrings
- Use `Union` for parameters that can accept multiple types
- For methods that don't return a value, use `-> None`

Example:
```python
from typing import List, Optional

def process_plans(plan_numbers: List[str], max_workers: Optional[int] = None) -> bool:
    # Function implementation
    return True
```

## 9. Project-Specific Conventions

### 9.1 RAS Instance Handling
- Design functions to accept an optional `ras_object` parameter:
  ```python
  def some_function(param1, param2, ras_object=None):
      ras_obj = ras_object or ras
      ras_obj.check_initialized()
      # Function implementation
  ```

### 9.2 File Path Handling
- Use `pathlib.Path` for file and directory path manipulations
- Convert string paths to Path objects at the beginning of functions

### 9.3 DataFrame Handling
- Use pandas for data manipulation and storage where appropriate
- Prefer method chaining for pandas operations to improve readability

### 9.4 Parallel Execution
- Follow the guidelines in the "Benchmarking is All You Need" blog post for optimal core usage in parallel plan execution

### 9.5 Function Return Values
- Prefer returning meaningful values over modifying global state
- Use tuple returns for multiple values instead of modifying input parameters
- Use consistent return types across related functions:
  - Use GeoDataFrame for functions returning spatial data
  - Use pandas DataFrame for tabular data
  - Use xarray DataArray/Dataset for multi-dimensional data with coordinates
  - Use Optional[Type] for functions that might return None

- Provide clear error handling for function returns:
  - Return empty DataFrame/GeoDataFrame instead of None when appropriate
  - Use Optional typing for functions that might return None
  - Document possible return values in docstrings


## 10. RasUtils Usage

- Use RasUtils for general-purpose utility functions that don't fit into other specific classes
- When adding new utility functions, ensure they are static methods of the RasUtils class
- Keep utility functions focused and single-purpose
- Document utility functions thoroughly, including examples of usage

Example:
```python
class RasUtils:
    @staticmethod
    def create_backup(file_path: Path, backup_suffix: str = "_backup") -> Path:
        """
        Create a backup of the specified file.

        Args:
            file_path (Path): Path to the file to be backed up
            backup_suffix (str): Suffix to append to the backup file name

        Returns:
            Path: Path to the created backup file

        Example:
            >>> backup_path = RasUtils.create_backup(Path("project.prj"))
            >>> print(f"Backup created at: {backup_path}")
        """
        # Function implementation
```

## 11. Working with RasExamples

- Use RasExamples for managing and loading example HEC-RAS projects
- Always check if example projects are already downloaded before attempting to download them again
- Use the `list_categories()` and `list_projects()` methods to explore available examples
- When extracting projects, use meaningful names and keep track of extracted paths
- Clean up extracted projects when they are no longer needed using `clean_projects_directory()`

Example:
```python
ras_examples = RasExamples()
if not ras_examples.is_project_extracted("Bald Eagle Creek"):
    extracted_path = ras_examples.extract_project("Bald Eagle Creek")[0]
    # Use the extracted project
    # ...
    # Clean up when done
    RasUtils.remove_with_retry(extracted_path, is_folder=True)
```

Remember, consistency is key. When in doubt, prioritize readability and clarity in your code. Always consider the maintainability and extensibility of the codebase when making design decisions.

## 12. Logging

Instructions for setting up a minimal logging decorator and applying it to functions:

1. Create logging_config.py:
```python
import logging
import functools

def setup_logging(level=logging.INFO):
    logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def log_call(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.info(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

setup_logging()
```

2. In each module file (e.g., RasPrj.py, RasPlan.py):
   - Add at the top: `from ras_commander.logging_config import log_call`
   - Remove all existing logging configurations and logger instantiations

3. Apply the decorator to functions:
   - Replace existing logging statements with the `@log_call` decorator
   - Remove any manual logging within the function body

Example changes to functions:

Before:
```python
def compute_plan(plan_number, dest_folder=None, ras_object=None, clear_geompre=False, num_cores=None):
    logging.info(f"Computing plan {plan_number}")
    # ... function logic ...
    logging.info(f"Plan {plan_number} computation complete")
    return result
```

After:
```python
@log_call
def compute_plan(plan_number, dest_folder=None, ras_object=None, clear_geompre=False, num_cores=None):
    # ... function logic ...
    return result
```

Apply this pattern across all functions in the library. This approach will significantly reduce the code footprint while maintaining basic logging functionality.

## 13. Decorator Usage for Ras* and Hdf* Classes to Simplify Inputs

- Use the `@log_call` decorator for all public methods to enable automatic logging of function entry and exit
- Use the `@standardize_input` decorator for methods that accept HDF file paths to ensure consistent handling
- Place decorators on separate lines for better readability when multiple decorators are used
- Order decorators consistently: `@staticmethod` first, followed by `@log_call`, then `@standardize_input`

Example:
```python
@staticmethod
@log_call
@standardize_input(file_type='plan_hdf')
def get_mesh_max_ws(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
    # Function implementation
```

## 15. Static Class Pattern

Many classes in the ras-commander library follow a static method pattern where:
- All methods are decorated with `@staticmethod`
- The class serves as a namespace for related functionality
- No instantiation is required to use the methods

When implementing such classes:
- Include a note in the class docstring stating "All methods in this class are static and designed to be used without instantiation"
- Use consistent method organization, typically starting with core methods followed by helper methods
- Private helper methods should still use the underscore prefix (e.g., `_parse_file`)
- Avoid storing state in class variables unless absolutely necessary

Example:
```python
class HdfMesh:
    """
    A class for handling mesh-related operations on HEC-RAS HDF files.
    
    All methods in this class are static and designed to be used without instantiation.
    """
    
    @staticmethod
    @log_call
    def get_mesh_area_names(hdf_path: Path) -> List[str]:
        # Method implementation
        
    @staticmethod
    def _parse_mesh_data(data: np.ndarray) -> Dict:
        # Helper method implementation
```