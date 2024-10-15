# RAS Commander (ras-commander) v0.43.0

RAS Commander is a Python library for automating HEC-RAS operations, providing a comprehensive set of tools to interact with HEC-RAS project files, execute simulations, and manage project data. This library is an evolution of the RASCommander 1.0 Python Notebook Application, now offering enhanced capabilities and improved integration with HEC-RAS version 6.0 and later.

## Table of Contents

1. [Introduction](#introduction)
2. [Features](#features)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Key Components](#key-components)
6. [HDF File Handling](#hdf-file-handling)
7. [Project Organization](#project-organization)
8. [Logging System](#logging-system)
9. [Standardized Input Handling](#standardized-input-handling)
10. [Error Handling and Logging Best Practices](#error-handling-and-logging-best-practices)
11. [Working with HDF Files](#working-with-hdf-files)
12. [Accessing HEC Examples through RasExamples](#accessing-hec-examples-through-rasexamples)
13. [Performance Optimization](#performance-optimization)
14. [Jupyter Notebooks](#jupyter-notebooks)
15. [Examples](#examples)
16. [Backwards Compatibility and Breaking Changes](#backwards-compatibility-and-breaking-changes)
17. [Contributing](#contributing)
18. [Related Resources](#related-resources)
19. [Acknowledgments](#acknowledgments)
20. [License](#license)

## Introduction

RAS Commander is designed to streamline and automate workflows for water resources engineers working with HEC-RAS. It provides a Pythonic interface to HEC-RAS operations, enabling users to programmatically manage projects, execute simulations, and analyze results. With the addition of comprehensive HDF file handling capabilities, RAS Commander now offers powerful tools for working with HEC-RAS output data.

## Features

- Automate HEC-RAS project management and simulations
- Support for both single and multiple project instances
- Parallel execution of HEC-RAS plans
- Comprehensive HDF file handling and analysis
- Utilities for managing geometry, plan, and unsteady flow files
- Example project management for testing and development
- Two primary operation modes: "Run Missing" and "Build from DSS"
- Advanced logging and error handling system
- Standardized input handling across the library
- Performance optimization for large-scale simulations
- Integration with data analysis and visualization libraries

## Installation

To install RAS Commander and its dependencies, use the following commands:

```bash
pip install h5py numpy pandas requests tqdm scipy
pip install ras-commander
```

If you encounter dependency issues, particularly with numpy, try clearing your local pip packages and creating a new virtual environment:

```bash
rm -rf C:\Users\your_username\AppData\Roaming\Python\
python -m venv new_environment
source new_environment/bin/activate  # On Windows, use: new_environment\Scripts\activate
pip install ras-commander
```

Requirements:
- Python 3.10 or later
- HEC-RAS 6.2 or later (earlier versions may work but are not officially supported)

## Quick Start

Here's a quick example demonstrating some of the core functionalities of RAS Commander, including HDF file handling:

```python
from ras_commander import init_ras_project, RasCmdr, RasPlan, HdfResultsMesh
import matplotlib.pyplot as plt

# Initialize a project
project = init_ras_project(r"/path/to/project", "6.5")

# Execute a single plan
RasCmdr.compute_plan("01", dest_folder=r"/path/to/results", overwrite_dest=True)

# Modify a plan
RasPlan.set_geom("01", "02")

# Extract and plot mesh results
plan_hdf_path = RasPlan.get_results_path("01")
mesh_name = "2D Flow Area"
water_surface = HdfResultsMesh.mesh_timeseries_output(plan_hdf_path, mesh_name, "Water Surface")

plt.figure(figsize=(10, 6))
plt.plot(water_surface.time, water_surface.mean(axis=1))
plt.title("Average Water Surface Elevation Over Time")
plt.xlabel("Time")
plt.ylabel("Water Surface Elevation (ft)")
plt.show()
```

This example demonstrates project initialization, plan execution, plan modification, and HDF result extraction and visualization.

## Key Components

- `RasPrj`: Manages HEC-RAS projects, handling initialization and data loading
- `RasCmdr`: Handles execution of HEC-RAS simulations
- `RasPlan`: Provides functions for modifying and updating plan files
- `RasGeo`: Handles operations related to geometry files
- `RasUnsteady`: Manages unsteady flow file operations
- `RasUtils`: Contains utility functions for file operations and data management
- `RasExamples`: Manages and loads HEC-RAS example projects
- `RasHdf`: Provides utilities for working with HDF files in HEC-RAS projects
- `HdfBase`: Fundamental HDF file operations
- `HdfBndry`: Boundary condition data handling
- `HdfMesh`: Mesh-related operations
- `HdfPlan`: Plan file HDF operations
- `HdfResultsMesh`: Mesh result processing
- `HdfResultsPlan`: Plan result management
- `HdfResultsXsec`: Cross-section result handling
- `HdfStruc`: Structure data management
- `HdfUtils`: HDF utility functions
- `HdfXsec`: Cross-section operations

## HDF File Handling

RAS Commander now includes a suite of classes for working with HEC-RAS HDF files:

- `HdfBase`: Provides fundamental methods for interacting with HEC-RAS HDF files.
- `HdfBndry`: Handles boundary-related data from HEC-RAS HDF files.
- `HdfMesh`: Manages mesh-related operations on HEC-RAS HDF files.
- `HdfPlan`: Handles operations on HEC-RAS plan HDF files.
- `HdfResultsMesh`: Processes mesh-related results from HEC-RAS HDF files.
- `HdfResultsPlan`: Manages plan-related results from HEC-RAS HDF files.
- `HdfResultsXsec`: Handles cross-section results from HEC-RAS HDF files.
- `HdfStruc`: Manages structure-related data in HEC-RAS HDF files.
- `HdfUtils`: Provides utility functions for HDF file operations.
- `HdfXsec`: Handles cross-section related operations on HEC-RAS HDF files.

These classes enable efficient extraction, analysis, and manipulation of data stored in HEC-RAS HDF files, enhancing the library's capabilities for advanced hydraulic modeling tasks.

## Project Organization

The RAS Commander project is organized as follows:

```
ras_commander
├── .github
│   └── workflows
│       └── python-package.yml
├── ras_commander
│   ├── __init__.py
│   ├── _version.py
│   ├── RasCmdr.py
│   ├── RasExamples.py
│   ├── RasGeo.py
│   ├── RasHdf.py
│   ├── RasPlan.py
│   ├── RasPrj.py
│   ├── RasUnsteady.py
│   ├── RasUtils.py
│   ├── HdfBase.py
│   ├── HdfBndry.py
│   ├── HdfMesh.py
│   ├── HdfPlan.py
│   ├── HdfResultsMesh.py
│   ├── HdfResultsPlan.py
│   ├── HdfResultsXsec.py
│   ├── HdfStruc.py
│   ├── HdfUtils.py
│   └── HdfXsec.py
├── examples
│   └── ... (example files)
├── tests
│   └── ... (test files)
├── .gitignore
├── LICENSE
├── README.md
├── STYLE_GUIDE.md
├── Comprehensive_Library_Guide.md
├── pyproject.toml
├── setup.cfg
├── setup.py
└── requirements.txt
```

## Logging System

RAS Commander now features a robust logging system to enhance debugging and traceability. The system is configured in the `logging_config.py` file and provides the following features:

- Centralized logging configuration
- Multiple log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Console and file logging
- Automatic function call logging with the `@log_call` decorator

To use logging in your scripts:

```python
from ras_commander import get_logger, log_call

logger = get_logger(__name__)

@log_call
def my_function():
    logger.debug("Additional debug information")
    # Function logic here
```

This system allows for consistent and informative logging across the entire library and your custom scripts.

## Standardized Input Handling

The `@standardize_input` decorator has been introduced to streamline input handling across the library. This decorator automatically processes various input types and converts them to a standardized format, ensuring consistency and reducing boilerplate code.

Usage example:

```python
from ras_commander import standardize_input

@standardize_input(file_type='plan_hdf')
def my_function(hdf_path: Path):
    # Function logic here
    pass

# Can be called with various input types
my_function("path/to/file.hdf")
my_function(Path("path/to/file.hdf"))
my_function(h5py.File("path/to/file.hdf", 'r'))
```

This decorator handles different input types (string paths, Path objects, h5py.File objects) and ensures that the function receives a standardized Path object.


## Error Handling and Logging Best Practices

RAS Commander emphasizes robust error handling and informative logging. Follow these best practices in your scripts:

1. Use try-except blocks to catch and handle specific exceptions:

```python
try:
    result = RasCmdr.compute_plan(plan_number)
except FileNotFoundError as e:
    logger.error(f"Plan file not found: {e}")
except ValueError as e:
    logger.error(f"Invalid plan parameter: {e}")
except Exception as e:
    logger.error(f"Unexpected error during plan computation: {e}")
```

2. Use the logging system instead of print statements:

```python
logger.info("Starting HEC-RAS simulation...")
logger.debug(f"Using parameters: {params}")
logger.warning("Deprecated feature used. Consider updating.")
logger.error(f"Failed to execute plan: {error_message}")
```

3. Set appropriate log levels for different environments:

```python
import logging
logging.getLogger('ras_commander').setLevel(logging.DEBUG)  # For development
logging.getLogger('ras_commander').setLevel(logging.INFO)   # For production
```

4. Use the `@log_call` decorator for automatic function call logging:

```python
@log_call
def my_function(arg1, arg2):
    # Function logic here
    pass
```

By following these practices, you'll create more robust and maintainable scripts that integrate well with RAS Commander's error handling and logging system.

## Working with HDF Files

RAS Commander provides a comprehensive set of tools for working with HEC-RAS HDF files. Here's an overview of some key operations:

1. Accessing HDF file metadata:
```python
from ras_commander import HdfUtils

hdf_paths = HdfUtils.get_hdf_paths_with_properties(plan_hdf_path)
print(hdf_paths)
```

2. Extracting mesh results:
```python
from ras_commander import HdfResultsMesh

water_surface = HdfResultsMesh.mesh_timeseries_output(plan_hdf_path, mesh_name, "Water Surface")
print(water_surface)
```

3. Working with plan results:
```python
from ras_commander import HdfResultsPlan

runtime_data = HdfResultsPlan.get_runtime_data(plan_hdf_path)
print(runtime_data)
```

4. Analyzing cross-section data:
```python
from ras_commander import HdfResultsXsec

wsel_data = HdfResultsXsec.cross_sections_wsel(plan_hdf_path)
print(wsel_data)
```

These classes provide a high-level interface to HDF data, making it easier to extract and analyze HEC-RAS results programmatically. For more detailed information on working with HDF files, refer to the comprehensive library guide.

## Accessing HEC Examples through RasExamples

The `RasExamples` class has been enhanced to provide more robust functionality for managing HEC-RAS example projects:

```python
from ras_commander import RasExamples

# Initialize RasExamples
ras_examples = RasExamples()

# Download and extract example projects
ras_examples.get_example_projects("6.6")

# List available project categories
categories = ras_examples.list_categories()
print(f"Available categories: {categories}")

# List projects in a specific category
steady_flow_projects = ras_examples.list_projects("Steady Flow")
print(f"Steady Flow projects: {steady_flow_projects}")

# Extract specific projects
extracted_paths = ras_examples.extract_project(["Bald Eagle Creek", "Muncie"])
for path in extracted_paths:
    print(f"Extracted project to: {path}")

# Clean up extracted projects when done
ras_examples.clean_projects_directory()

# Download FEMA BLE models
ras_examples.download_fema_ble_model("12345678", output_dir="path/to/output")
```

These methods allow for easy access, management, and cleanup of example projects, facilitating testing and development with real-world HEC-RAS models.

Certainly. Here are the final sections of the revised README:

```markdown
## Jupyter Notebooks

RAS Commander now includes several Jupyter notebooks in the `examples/` folder to demonstrate advanced usage and analysis techniques:

1. `14_Core_Sensitivity.ipynb`: This notebook demonstrates how to perform a sensitivity analysis on the number of cores used for HEC-RAS computations. It helps in determining the optimal core count for your specific model and hardware.

2. `18_2d_hdf_data_extraction.ipynb`: This notebook showcases techniques for extracting and analyzing 2D data from HEC-RAS HDF files. It covers topics such as mesh data extraction, result visualization, and time series analysis.

3. `19_benchmarking_version_6.6.ipynb`: This notebook provides a framework for benchmarking different versions of HEC-RAS (6.6, 6.5, etc.) using RAS Commander. It helps in comparing performance across versions and identifying potential improvements or regressions.

These notebooks serve as both examples and templates for your own analysis tasks. They can be found in the `examples/` directory of the RAS Commander repository.

## Examples

The `examples/` directory contains a variety of scripts and notebooks demonstrating the use of RAS Commander, including the new HDF-related functionalities:

1. Basic project initialization and plan execution
2. Parallel execution of multiple plans
3. Geometry and unsteady flow file operations
4. HDF file analysis and data extraction
5. Result visualization using matplotlib
6. Performance optimization techniques
7. Integration with data analysis libraries like pandas and numpy

Here's a quick example of extracting and plotting 2D mesh results:

```python
from ras_commander import HdfResultsMesh
import matplotlib.pyplot as plt

# Extract water surface data
water_surface = HdfResultsMesh.mesh_timeseries_output(hdf_path, mesh_name, "Water Surface")

# Calculate average water surface elevation over time
mean_ws = water_surface.mean(axis=1)

# Plot the results
plt.figure(figsize=(10, 6))
plt.plot(water_surface.time, mean_ws)
plt.title("Average Water Surface Elevation Over Time")
plt.xlabel("Time")
plt.ylabel("Water Surface Elevation (ft)")
plt.show()
```

For more examples, refer to the scripts and notebooks in the `examples/` directory.

## Backwards Compatibility and Breaking Changes

RAS Commander strives to maintain backwards compatibility where possible. However, the introduction of new features, especially related to HDF file handling, has led to some changes that users should be aware of:

1. HDF File Handling: The new HDF-related classes (`HdfBase`, `HdfBndry`, etc.) replace some older methods of accessing HDF data. While the old methods are still supported, we recommend transitioning to the new classes for improved performance and functionality.

2. Logging System: The introduction of the centralized logging system may require updates to existing scripts that used custom logging setups.

3. Input Standardization: The `@standardize_input` decorator changes how some functions handle input parameters. While it generally improves usability, it may require adjustments in scripts that relied on specific input formats.

4. RAS Version Support: RAS Commander now primarily supports HEC-RAS version 6.0 and later. While it may still work with earlier versions, full functionality is not guaranteed.

If you encounter any issues when upgrading to the latest version of RAS Commander, please refer to the migration guide in the documentation or open an issue on the GitHub repository.

## Contributing

We welcome contributions to RAS Commander! Here are some guidelines for contributing, especially when working with the new HDF-related classes:

1. Follow the [Style Guide](STYLE_GUIDE.md) for code formatting and conventions.
2. When adding new HDF-related functionality:
   - Ensure compatibility with existing HDF classes
   - Add appropriate error handling and logging
   - Include type hints for function parameters and return values
   - Write comprehensive docstrings with examples
3. Add unit tests for new functions or methods in the `tests/` directory.
4. Update the Comprehensive Library Guide with any new functionality.
5. For significant changes, create a feature branch and submit a pull request.
6. Ensure all tests pass before submitting a pull request.
7. Update the README.md file if your changes affect the library's usage or features.

For more detailed information on contributing, please refer to our [Contributing Guide](CONTRIBUTING.md).

## Related Resources

- [HEC-Commander Blog](https://github.com/billk-FM/HEC-Commander/tree/main/Blog): In-depth articles on HEC-RAS automation and advanced modeling techniques.
- [GPT-Commander YouTube Channel](https://www.youtube.com/@GPT_Commander): Video tutorials and demonstrations of RAS Commander capabilities.
- [ChatGPT Examples for Water Resources Engineers](https://github.com/billk-FM/HEC-Commander/tree/main/ChatGPT%20Examples): AI-assisted problem-solving for hydraulic modeling tasks.
- [HEC-RAS Documentation](https://www.hec.usace.army.mil/software/hec-ras/documentation.aspx): Official documentation for HEC-RAS, including details on HDF file structure.
- [h5py Documentation](https://docs.h5py.org/en/stable/): Documentation for the h5py library, which RAS Commander uses for low-level HDF file operations.
- [Dask Documentation](https://docs.dask.org/en/latest/): Information on using Dask for large-scale data processing, which can be helpful when working with large HEC-RAS models.

## Acknowledgments

RAS Commander is based on the HEC-Commander project's "Command Line is All You Need" approach, leveraging the HEC-RAS command-line interface for automation. We would like to acknowledge the following contributions and influences:

1. Sean Micek's [`funkshuns`](https://github.com/openSourcerer9000/funkshuns), [`TXTure`](https://github.com/openSourcerer9000/TXTure), and [`RASmatazz`](https://github.com/openSourcerer9000/RASmatazz) libraries provided inspiration and utility functions adapted for use in RAS Commander.

2. The [`rashdf`](https://github.com/fema-ffrd/rashdf) library by Thomas Williams, PE (Sr. Software Engineer / Water Resources Engineer @ WSP), which provided substantial code and inspiration for HDF file handling in RAS Commander.

3. Chris Goodell's "Breaking the HEC-RAS Code" - Used as a reference for understanding the inner workings of HEC-RAS.

4. The [HEC-Commander Tools](https://github.com/billk-FM/HEC-Commander) repository, which served as the initial inspiration and code base for RAS Commander.

5. The HEC-RAS development team at the US Army Corps of Engineers for their ongoing work on HEC-RAS and its file formats.

6. The open-source community, particularly the developers of h5py, numpy, pandas, and other libraries that RAS Commander relies on.

7. The [`pyHMT2D`](https://github.com/psu-efd/pyHMT2D/) project by Xiaofeng Liu, which provided insights into HDF file handling methods for HEC-RAS outputs.
We are grateful for these contributions and the broader community of water resources engineers and developers who continue to push the boundaries of hydraulic modeling and automation.

## License

RAS Commander is released under the MIT License. See the [LICENSE](LICENSE) file for details.
```

This completes the fully revised README. It now includes comprehensive information about the library's features, usage, and recent updates, with a focus on the new HDF-related functionalities and best practices for using RAS Commander.