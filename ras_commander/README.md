"""
# Developer's README

These notes should be followed by any developer who wants to use this library orcontribute to this project.

-----


# Developer's README for ras_commander

## Project Overview

ras_commander is a Python library for automating HEC-RAS operations. It provides a set of classes and functions to interact with HEC-RAS project files, execute simulations, and manage project data.

## Project Structure

The library is organized into several key modules:

- `RasPrj.py`: Handles project initialization and manages project-level information.
- `RasCommander.py`: Manages execution of HEC-RAS simulations.
- `RasPlan.py`: Provides functions for modifying and updating plan files.
- `RasGeo.py`: Handles operations related to geometry files.
- `RasUnsteady.py`: Manages unsteady flow file operations.
- `RasUtils.py`: Contains utility functions for file operations and data management.

## Key Concepts

### RAS Instance Management

The library supports both a global `ras` instance and the ability to create multiple instances for different projects:

- Use the global `ras` instance for simple, single-project scenarios.
- Create multiple `RasPrj` instances for working with multiple projects simultaneously.

### Function Design

Most functions in the library follow this pattern:

```python
def some_function(param1, param2, ras_object=None):
    ras_obj = ras_object or ras
    ras_obj.check_initialized()
    # Function implementation
```

This design allows for flexibility in using either the global instance or a specific project instance.

## ras_commander Best Practices

1. Always check if a project is initialized before performing operations:
   ```python
   ras_obj.check_initialized()
   ```

2. Use the `ras_object` parameter in functions to specify which project instance to use.

3. For complex projects with multiple HEC-RAS folders, prefer passing explicit `ras_object` instances to functions for clarity.

4. Use type hints and descriptive variable names to improve code readability.

5. Handle exceptions appropriately, especially for file operations and HEC-RAS interactions.

6. When adding new functionality, consider its placement within the existing class structure.

7. Update the `__init__.py` file when adding new modules or significant functionality.

## Testing

- Write unit tests for all new functions and methods.
- Ensure tests cover both single-project and multi-project scenarios.
- Use the `unittest` framework for consistency with existing tests.

## Documentation

- Keep docstrings up-to-date with any changes to function signatures or behavior.
- Update the main README.md file when adding new features or changing existing functionality.
- Consider adding or updating example scripts in the `examples/` directory for new features.
- Build a notebook first!  We have AI to help us integrate functions into the library once we have a working example. 


## Performance Considerations

- For parallel execution of plans, refer to the "Benchmarking is All You Need" blog post in the HEC-Commander repository for guidance on optimal core usage.

## Abbreviations

Consistently use these abbreviations throughout the codebase:

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

## Future Development

Refer to the "Future Development Roadmap" for planned enhancements and features to be implemented.

By following these guidelines, we can maintain consistency, readability, and reliability across the ras_commander library.






















# Understanding and Using RAS Instances in ras_commander

The `RasPrj` class now supports both a global instance named `ras` and the ability to create multiple instances for different projects.

Key points about RAS instances:

1. **Global Instance**: A default global instance named `ras` is still available for backwards compatibility and simple use cases.
2. **Multiple Instances**: Users can create and manage multiple `RasPrj` instances for different projects.
3. **Flexible Function Calls**: Most functions now accept an optional `ras_object` parameter, allowing use of specific project instances.
4. **Consistent State**: Each instance maintains its own project state, ensuring data consistency within each project context.

## Using RAS Instances

### Global Instance
For simple, single-project scenarios:

```python
from ras_commander import ras, init_ras_project

# Initialize the global instance
init_ras_project("/path/to/project", "6.5")

# Use the global instance
print(f"Working with project: {ras.project_name}")
plan_file = ras.get_plan_path("01")
```

### Multiple Instances
For working with multiple projects:

```python
from ras_commander import RasPrj, init_ras_project

# Create and initialize separate instances
project1 = init_ras_project("/path/to/project1", "6.5")
project2 = init_ras_project("/path/to/project2", "6.5")

# Use specific instances in function calls
RasPlan.set_geom("01", "02", ras_object=project1)
RasPlan.set_geom("01", "03", ras_object=project2)
```

### Best Practices
1. Always check if a project is initialized before using:
   ```python
   def my_function(ras_object=None):
       ras_obj = ras_object or ras
       ras_obj.check_initialized()
       # Proceed with operations using ras_obj
   ```

2. Use the `ras_object` parameter in functions to specify which project instance to use.

3. For any advance usage with multiple projects, you shouldprefer passing explicit `ras_object` instances to functions for clarity and to avoid unintended use of the global instance.

By supporting both a global instance and multiple instances, ras_commander provides flexibility for various usage scenarios while maintaining simplicity for basic use cases.

"""