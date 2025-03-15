# Comprehensive RAS-Commander Library Guide

## Introduction

RAS-Commander (`ras_commander`) is a Python library designed to automate and streamline operations with HEC-RAS projects. It provides a suite of tools for managing projects, executing simulations, and handling results. This guide offers a comprehensive overview of the library's key concepts, modules, best practices, and advanced usage patterns. RAS-Commander is designed to be flexible, robust, and AI-accessible, making it an ideal tool for both manual and automated HEC-RAS workflows.

RAS-Commander can be installed with the following commands:
```
pip install h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib ras-commander ipython psutil shapely fiona pathlib rtree
pip install --update ras-commander # This ensures you get the latest version of the library
```

## Key Concepts

1. **RAS Objects**:
   - Represent HEC-RAS projects containing information about plans, geometries, and flow files.
   - Support both a global `ras` object and custom named object to handle multiple projects.

2. **Project Initialization**:
   - Use `init_ras_project()` to initialize projects and set up RAS objects.
   - Handles project file discovery and data structure setup.

3. **File Handling**:
   - Utilizes `pathlib.Path` for consistent, platform-independent file paths.
   - Adheres to HEC-RAS file naming conventions (`.prj`, `.p01`, `.g01`, `.f01`, `.u01`).

4. **Data Management**:
   - Employs Pandas DataFrames to manage structured data about plans, geometries, and flow files.
   - Provides methods for accessing and updating these DataFrames.

5. **Execution Modes**:
   - **Single Plan Execution**: Run individual plans with `RasCmdr.compute_plan()`.
   - **Sequential Execution**: Run multiple plans in sequence with `RasCmdr.compute_test_mode()`.
   - **Parallel Execution**: Run multiple plans concurrently with `RasCmdr.compute_parallel()`.

6. **Example Projects**:
   - The `RasExamples` class offers functionality to download and manage HEC-RAS example projects for testing and learning.

7. **Utility Functions**:
   - `RasUtils` provides common utility functions for file operations, backups, error handling, and statistical analysis.

8. **Artifact System**:
   - Handles substantial, self-contained content that users might modify or reuse, displayed in a separate UI window.

9. **AI-Driven Coding Tools**:
   - Integrates AI-powered tools like ChatGPT Assistant, LLM Summaries, Cursor IDE Integration, and Jupyter Notebook Assistant.

10. **Boundary Conditions**:
    - Represent the input conditions for HEC-RAS simulations, including flow hydrographs, stage hydrographs, and other hydraulic inputs.
    - The `RasPrj` class provides functionality to extract and manage boundary conditions from unsteady flow files.

11. **Flexibility and Modularity**:
    - All classes are designed to work with either a global 'ras' object + a plan number, or with custom object.
    - Clear separation of concerns between project management (RasPrj), execution (RasCmdr), and results data retrieval (RasHdf).

12. **Error Handling and Logging**:
    - Emphasis on robust error checking and informative logging throughout the library.
    - Utilizes the `logging_config` module for consistent logging configuration.
    - `@log_call` decorator applied to relevant functions for logging function calls.

13. **AI-Accessibility**:
    - Structured, consistent codebase with clear documentation to facilitate easier learning and usage by AI models.

14. **Expanded HDF Support**:
    - Comprehensive HDF file handling through specialized classes
    - Support for mesh, plan, and cross-section results
    - Advanced data extraction and analysis capabilities

15. **Enhanced Boundary Conditions**:
    - Improved extraction and management of boundary conditions
    - Support for various boundary condition types
    - Structured representation of boundary data

16. **Infrastructure Analysis**:
    - New support for pipe networks through `HdfPipe`
    - Pump station analysis via `HdfPump`
    - Fluvial-pluvial analysis capabilities in `HdfFluvialPluvial`


## Core Features

1. **Project Management**: Initialize, load, and manage HEC-RAS projects.
2. **Plan Execution**: Run single or multiple HEC-RAS plans with various execution modes.
3. **File Operations**: Handle HEC-RAS file types (plans, geometries, flows) with ease.
4. **Data Extraction**: Retrieve and process results from HDF files.
5. **Boundary Condition Management**: Extract and analyze boundary conditions.
6. **Parallel Processing**: Optimize performance with parallel plan execution.
7. **Example Project Handling**: Download and manage HEC-RAS example projects.
8. **Utility Functions**: Perform common tasks and statistical analyses.
9. **HDF File Handling**: Specialized classes for working with HEC-RAS HDF files.
10. **Advanced HDF Analysis**: Comprehensive tools for HDF file operations
11. **Infrastructure Analysis**: Tools for pipe networks and pump stations
12. **External Tool Integration**: Connection to Go-Consequences and other tools

## Module Overview

1. **RasPrj**: Manages HEC-RAS project initialization and data, including boundary conditions.
2. **RasCmdr**: Handles execution of HEC-RAS simulations in single, sequential, or parallel modes.
3. **RasPlan**: Provides functions for plan file operations.
4. **RasGeo**: Manages geometry file operations.
5. **RasUnsteady**: Handles unsteady flow file operations.
6. **RasUtils**: Offers utility functions for common tasks and statistical analysis.
7. **RasExamples**: Manages example HEC-RAS projects.
8. **HdfBase**: Provides base functionality for HDF file operations.
9. **HdfBndry**: Handles boundary-related data in HDF files.
10. **HdfMesh**: Manages mesh-related data in HDF files.
11. **HdfPlan**: Handles plan-related data in HDF files.
12. **HdfResultsMesh**: Processes mesh results from HDF files.
13. **HdfResultsPlan**: Handles plan results from HDF files.
14. **HdfResultsXsec**: Processes cross-section results from HDF files.
15. **HdfStruc**: Manages structure data in HDF files.
16. **HdfUtils**: Provides utility functions for HDF file operations.
17. **HdfXsec**: Handles cross-section data in HDF files.
18. **HdfPipe**: Handles pipe network related data in HDF files.
19. **HdfPump**: Manages pump station related data in HDF files.
20. **HdfFluvialPluvial**: Manages fluvial and pluvial related data in HDF files.
21. **HdfPlot & HdfResultsPlot**: Visualization utilities

## Best Practices

### 1. RAS Object Usage

- **Single Project Scripts**:
  - Use the global `ras` object for simplicity.
    ```python
    from ras_commander import ras, init_ras_project

    init_ras_project("/path/to/project", "6.5")
    # Use ras object for operations
    ```

- **Multiple Projects**:
  - Create separate `RasPrj` object for each project.
    ```python
    from ras_commander import RasPrj, init_ras_project

    project1 = init_ras_project("/path/to/project1", "6.5", ras_object=your_object_name)
    project2 = init_ras_project("/path/to/project2", "6.5", ras_object=your_object_name)
    ```

- **Consistency**:
  - Avoid mixing global and custom RAS objects in the same script.

### 2. Plan Specification

- Use plan numbers as strings (e.g., `"01"`, `"02"`) for consistency.
  ```python
  RasCmdr.compute_plan("01")
  ```

- Check available plans before specifying plan numbers.
  ```python
  print(ras.plan_df)  # Displays available plans
  ```

### 3. Geometry Preprocessor Files

- Clear geometry preprocessor files before significant changes.
  ```python
  RasGeo.clear_geompre_files()
  ```

- Use `clear_geompre=True` for a clean computation environment.
  ```python
  RasCmdr.compute_plan("01", clear_geompre=True)
  ```

### 4. Parallel Execution

- Adjust `max_workers` based on the number of physical cores, not logical cores.
  ```python
  RasCmdr.compute_parallel(max_workers=4, num_cores=2)
  ```

- Set `num_cores` to balance between single-plan performance and overall throughput.
  ```python
  # Efficiency mode (maximize throughput)
  RasCmdr.compute_parallel(max_workers=8, num_cores=2)
  
  # Performance mode (minimize individual plan runtime)
  RasCmdr.compute_parallel(max_workers=2, num_cores=8)
  ```

- Consider using 2 cores per worker for efficiency or 4-8 cores per worker for performance.

- Use `dest_folder` to organize outputs and prevent conflicts.
  ```python
  RasCmdr.compute_parallel(dest_folder="/path/to/results")
  ```

### 5. Error Handling and Logging

Proper error handling and logging are crucial for robust RAS Commander scripts. The library provides built-in logging functionality to help you track operations and diagnose issues.

1. **Logging Setup**:
   RAS Commander automatically sets up basic logging. You can adjust the log level:

   ```python
   import logging
   logging.getLogger('ras_commander').setLevel(logging.DEBUG)
   ```

2. **Using the @log_call Decorator**:
   The `@log_call` decorator automatically logs function calls:

   ```python
   from ras_commander.Decorators import log_call

   @log_call
   def my_function():
       # Function implementation
   ```

3. **Custom Logging**:
   For more detailed logging, use the logger directly:

   ```python
   from ras_commander.LoggingConfig import get_logger

   logger = get_logger(__name__)

   def my_function():
       logger.info("Starting operation")
       try:
           # Operation code
       except Exception as e:
           logger.error(f"Operation failed: {str(e)}")
   ```

4. **Error Handling Best Practices**:
   - Use specific exception types when possible.
   - Provide informative error messages.
   - Consider using custom exceptions for library-specific errors.

   ```python
   class RasCommanderError(Exception):
       pass

   def my_function():
       try:
           # Operation code
       except FileNotFoundError as e:
           raise RasCommanderError(f"Required file not found: {str(e)}")
       except ValueError as e:
           raise RasCommanderError(f"Invalid input: {str(e)}")
   ```

5. **Logging to File**:
   To save logs to a file, configure a file handler:

   ```python
   import logging
   from ras_commander.LoggingConfig import setup_logging

   setup_logging(log_file='ras_commander.log', log_level=logging.DEBUG)
   ```

### 6. File Path Handling

- Use `pathlib.Path` for robust file and directory operations.
  ```python
  from pathlib import Path
  project_path = Path("/path/to/project")
  ```

### 7. Type Hinting

- Apply type hints to improve code readability and IDE support.
  ```python
  from typing import Union, List, Optional
  def compute_plan(plan_number: str, clear_geompre: bool = False) -> bool:
      ...
  ```

## Usage Patterns

### Initializing a Project
```python
from ras_commander import init_ras_project, ras

init_ras_project("/path/to/project", "6.5")
print(f"Working with project: {ras.project_name}")
```

### Cloning a Plan

```python
from ras_commander import RasPlan

new_plan_number = RasPlan.clone_plan("01")
print(f"Created new plan: {new_plan_number}")
```

### Executing Plans

- **Single Plan Execution**:
  ```python
  from ras_commander import RasCmdr

  success = RasCmdr.compute_plan("01", num_cores=2)
  print(f"Plan execution {'successful' if success else 'failed'}")
  ```

- **Parallel Execution of Multiple Plans**:
  ```python
  from ras_commander import RasCmdr

  results = RasCmdr.compute_parallel(
      plan_number=["01", "02", "03"],
      max_workers=3,
      num_cores=4,
      dest_folder="/path/to/results",
      clear_geompre=True
  )

  for plan, success in results.items():
      print(f"Plan {plan}: {'Successful' if success else 'Failed'}")
  ```

### Working with Multiple Projects

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr

# Initialize two separate projects
project1 = init_ras_project("/path/to/project1", "6.5", ras_object=your_object_name)
project2 = init_ras_project("/path/to/project2", "6.5", ras_object=your_object_name)

# Perform operations on each project
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("02", ras_object=project2)

# Compare results
results1 = project1.get_hdf_entries()
results2 = project2.get_hdf_entries()
```

## Advanced Usage

### Working with HDF Files

RAS Commander provides extensive support for working with HDF files through various specialized classes. Here's an overview of key operations:

1. **Reading HDF Data**:
   Use `HdfUtils.get_hdf_paths_with_properties()` to explore the structure of an HDF file:

   ```python
   from ras_commander import HdfUtils

   hdf_paths = HdfUtils.get_hdf_paths_with_properties(hdf_path)
   print(hdf_paths)
   ```

2. **Extracting Mesh Results**:
   Use `HdfResultsMesh` to extract mesh-related results:

   ```python
   from ras_commander import HdfResultsMesh

   water_surface = HdfResultsMesh.mesh_timeseries_output(hdf_path, mesh_name, "Water Surface")
   print(water_surface)
   ```

3. **Working with Plan Results**:
   Use `HdfResultsPlan` for plan-specific results:

   ```python
   from ras_commander import HdfResultsPlan

   runtime_data = HdfResultsPlan.get_runtime_data(hdf_path)
   print(runtime_data)
   ```

4. **Cross-Section Results**:
   Extract cross-section data using `HdfResultsXsec`:

   ```python
   from ras_commander import HdfResultsXsec

   wsel_data = HdfResultsXsec.cross_sections_wsel(hdf_path)
   print(wsel_data)
   ```

These classes provide a high-level interface to HDF data, making it easier to extract and analyze HEC-RAS results programmatically.

### Working with Pipe Networks and Pump Stations

RAS Commander provides specialized classes for handling pipe networks and pump stations data from HEC-RAS HDF files.

1. **Pipe Network Operations**:
   Use `HdfPipe` to extract and analyze pipe network data:

   ```python
   from ras_commander import HdfPipe
   from pathlib import Path

   hdf_path = Path("path/to/your/hdf_file.hdf")

   # Extract pipe conduit data
   pipe_conduits = HdfPipe.get_pipe_conduits(hdf_path)
   print(pipe_conduits)

   # Extract pipe node data
   pipe_nodes = HdfPipe.get_pipe_nodes(hdf_path)
   print(pipe_nodes)

   # Get pipe network timeseries data
   water_surface = HdfPipe.get_pipe_network_timeseries(hdf_path, "Cell Water Surface")
   print(water_surface)

   # Get pipe network summary
   summary = HdfPipe.get_pipe_network_summary(hdf_path)
   print(summary)

   # Get pipe profile for a specific conduit
   profile = HdfPipe.get_pipe_profile(hdf_path, conduit_id=0)
   print(profile)
   ```

2. **Pump Station Operations**:
   Use `HdfPump` to work with pump station data:

   ```python
   from ras_commander import HdfPump
   from pathlib import Path

   hdf_path = Path("path/to/your/hdf_file.hdf")

   # Extract pump station data
   pump_stations = HdfPump.get_pump_stations(hdf_path)
   print(pump_stations)

   # Get pump group data
   pump_groups = HdfPump.get_pump_groups(hdf_path)
   print(pump_groups)

   # Get pump station timeseries data
   pump_data = HdfPump.get_pump_station_timeseries(hdf_path, "Pump Station 1")
   print(pump_data)

   # Get pump station summary
   summary = HdfPump.get_pump_station_summary(hdf_path)
   print(summary)

   # Get pump operation data
   operation_data = HdfPump.get_pump_operation_data(hdf_path, "Pump Station 1")
   print(operation_data)
   ```

These classes provide powerful tools for analyzing and visualizing pipe network and pump station data from HEC-RAS simulations. They allow you to easily access geometric information, time series data, and summary statistics for these hydraulic structures.

### Working with Multiple HEC-RAS Projects

RAS Commander allows you to work with multiple HEC-RAS projects simultaneously, which is useful for comparing different river systems, running scenario analyses across multiple watersheds, or managing a suite of related models.

#### Creating Custom RAS Objects

When working with multiple projects, you should create separate RAS objects for each project:

```python
# Initialize multiple project instances with custom RAS objects
project1 = RasPrj()
init_ras_project(path1, "6.6", ras_object=project1)
project2 = RasPrj()
init_ras_project(path2, "6.6", ras_object=project2)

# This allows RasPrj Instances to be accessed as follows:
print(f"Project 1: {project1.project_name}")
print(f"Project 2: {project2.project_name}")




```

#### Best Practices for Multiple Project Management

1. **Name Your Objects Clearly**: Use descriptive variable names for your RAS objects (e.g., `bald_eagle_ras`, `muncie_ras`).
2. **Be Consistent**: Always pass the appropriate RAS object to functions when working with multiple projects.
3. **Avoid Using Global 'ras'**: When working with multiple projects, avoid using the global `ras` object to prevent confusion.
4. **Separate Compute Folders**: Use different destination folders for each project's computations.
5. **Resource Management**: Be mindful of CPU and memory usage when running multiple projects in parallel.

#### Example Workflow

```python
# Initialize two projects
project1 = init_ras_project(path1, "6.6")
project2 = init_ras_project(path2, "6.6")

# Create a comparison function
def compare_project_structures(ras_object1, name1, ras_object2, name2):
    """Compare the structures of two HEC-RAS projects and display differences."""
    # Create a comparison dictionary
    comparison = {
        'Project Name': [ras_object1.project_name, ras_object2.project_name],
        'Plan Count': [len(ras_object1.plan_df), len(ras_object2.plan_df)],
        'Geometry Count': [len(ras_object1.geom_df), len(ras_object2.geom_df)],
        'Flow Count': [len(ras_object1.flow_df), len(ras_object2.flow_df)],
        'Unsteady Count': [len(ras_object1.unsteady_df), len(ras_object2.unsteady_df)]
    }
    
    # Create a DataFrame for the comparison
    comparison_df = pd.DataFrame(comparison, index=[name1, name2])
    return comparison_df

# Perform operations on each project
RasCmdr.compute_plan("01", ras_object=project1, dest_folder=folder1)
RasCmdr.compute_plan("01", ras_object=project2, dest_folder=folder2)

# Compare projects
comparison_df = compare_project_structures(
    project1, "Project 1", 
    project2, "Project 2"
)
print(comparison_df)
```

#### Application Examples

Working with multiple projects unlocks advanced applications such as:

1. **Model Comparison**: Compare results from different river systems
2. **Basin-wide Analysis**: Analyze connected river systems in parallel
3. **Parameter Sweep**: Test a range of parameters across multiple models
4. **Model Development**: Develop and test models simultaneously
5. **Batch Processing**: Process large sets of models in an automated pipeline

### Plan Execution Modes

RAS Commander provides three different modes for executing HEC-RAS plans, each with its own advantages and use cases.

#### Single Plan Execution

The `compute_plan()` method is designed for running a single HEC-RAS plan.

```python
success = RasCmdr.compute_plan(
    plan_number="01",              # The plan to execute
    dest_folder="/path/to/results", # Where to run the simulation
    num_cores=2,                    # Number of processor cores to use
    clear_geompre=True,             # Whether to clear geometry preprocessor files
    overwrite_dest=True             # Whether to overwrite the destination folder
)
```

This approach is best when you need to:
- Run a single plan with specific parameters
- Control execution details precisely
- Monitor immediate results
- Need to use the results immediately after computation

#### Sequential Execution

The `compute_test_mode()` method runs multiple plans sequentially in a test folder.

```python
results = RasCmdr.compute_test_mode(
    plan_number=["01", "02", "03"], # Plans to execute sequentially
    dest_folder_suffix="[Test]",    # Suffix for the test folder
    clear_geompre=True,             # Whether to clear geometry preprocessor files
    num_cores=2                     # Number of cores for each plan
)
```

This approach is best when you need to:
- Run plans in a specific order
- Ensure consistent resource usage
- Keep all results in a dedicated test folder
- Handle plans that depend on each other's results

#### Parallel Execution

The `compute_parallel()` method runs multiple plans simultaneously for improved performance.

```python
results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"], # Plans to execute in parallel
    max_workers=3,                  # Maximum number of concurrent workers
    num_cores=2,                    # Cores per plan
    dest_folder="/path/to/results", # Destination folder
    clear_geompre=True              # Whether to clear geometry preprocessor files
)
```

This approach is best when you need to:
- Maximize computational efficiency
- Run multiple independent plans
- Make better use of available CPU cores
- Reduce overall execution time

#### Choosing the Right Execution Mode

Choose based on:
- **Dependency between plans**: Use sequential for dependent plans, parallel for independent plans
- **Resource constraints**: Use single or sequential on limited hardware
- **Time constraints**: Use parallel for faster overall execution
- **Result organization**: Use test_mode for clean test environments

#### Return Values

All execution methods return information about the success of each plan:

- `compute_plan()`: Returns a boolean indicating success or failure
- `compute_test_mode()`: Returns a dictionary mapping plan numbers to success status
- `compute_parallel()`: Returns a dictionary mapping plan numbers to success status

```python
# Example of checking results
results = RasCmdr.compute_parallel(plan_number=["01", "02", "03"])
for plan_num, success in results.items():
    print(f"Plan {plan_num}: {'Success' if success else 'Failed'}")
```

### Plan Parameter Operations

RAS Commander provides several functions for working with plan parameters, allowing you to view and modify various simulation settings programmatically without opening the HEC-RAS GUI.

#### Retrieving Plan Values

The `get_plan_value()` method retrieves specific parameters from a plan file:

```python
# Get the current computation interval
interval = RasPlan.get_plan_value("01", "Computation Interval")
print(f"Current computation interval: {interval}")

# Get the number of cores
cores = RasPlan.get_plan_value("01", "UNET D1 Cores")
print(f"Current cores setting: {cores}")
```

Common keys to query include:
- `Computation Interval`: Time step for calculations
- `Short Identifier`: Brief name/ID for the plan
- `Simulation Date`: Start and end dates for simulation
- `UNET D1 Cores`: Number of processor cores to use
- `Plan Title`: Full title of the plan
- `Geom File`: Associated geometry file
- `Flow File`: Associated flow file (for steady flow)
- `Unsteady File`: Associated unsteady flow file
- `Friction Slope Method`: Method for calculating friction slopes
- `Run HTab`: Whether to run the geometry preprocessor
- `UNET Use Existing IB Tables`: Whether to use existing internal boundary tables

#### Updating Run Flags

The `update_run_flags()` method controls which components of the simulation are executed:

```python
RasPlan.update_run_flags(
    "01",
    geometry_preprocessor=True,    # Run the geometry preprocessor
    unsteady_flow_simulation=True, # Run unsteady flow simulation
    post_processor=True,           # Run post-processing
    floodplain_mapping=False       # Skip floodplain mapping
)
```

This allows you to selectively enable or disable different simulation components, which is useful for focusing on specific parts of the computation or for troubleshooting.

#### Setting Time Intervals

The `update_plan_intervals()` method modifies the time intervals used in the simulation:

```python
RasPlan.update_plan_intervals(
    "01",
    computation_interval="10SEC",  # Time step for calculations
    output_interval="1MIN",        # How often to save results
    mapping_interval="15MIN"       # How often to save mapping data
)
```

Valid interval values must be specified in HEC-RAS format:
- Seconds: `1SEC`, `2SEC`, `3SEC`, `4SEC`, `5SEC`, `6SEC`, `10SEC`, `15SEC`, `20SEC`, `30SEC`
- Minutes: `1MIN`, `2MIN`, `3MIN`, `4MIN`, `5MIN`, `6MIN`, `10MIN`, `15MIN`, `20MIN`, `30MIN`
- Hours: `1HOUR`, `2HOUR`, `3HOUR`, `4HOUR`, `6HOUR`, `8HOUR`, `12HOUR`
- Days: `1DAY`

#### Working with Simulation Dates

The `update_simulation_date()` method changes the start and end times for the simulation:

```python
from datetime import datetime

start_date = datetime(2023, 1, 1, 0, 0)  # January 1, 2023, 00:00
end_date = datetime(2023, 1, 5, 23, 59)  # January 5, 2023, 23:59

RasPlan.update_simulation_date("01", start_date, end_date)
```

Considerations for simulation dates:
1. **Hydrograph Coverage**: The simulation period should fully encompass your hydrographs
2. **Warm-Up Period**: Include time before the main event for model stabilization
3. **Cool-Down Period**: Include time after the main event for complete drainage
4. **Computational Efficiency**: Avoid unnecessarily long periods to reduce runtime
5. **Consistency**: Ensure dates match available boundary condition data

#### Managing Plan Descriptions

RAS Commander provides methods to read and update plan descriptions:

```python
# Read the current description
current_description = RasPlan.read_plan_description("01")
print(f"Current description: {current_description}")

# Update the description
new_description = """Modified plan for climate change scenario
Increased rainfall intensity: 20%
Extended simulation period: 5 days
Modified Manning's n values"""

RasPlan.update_plan_description("01", new_description)
```

Effective plan descriptions should include:
1. Purpose of the simulation
2. Key parameters and settings
3. Date of creation or modification
4. Author or organization
5. Any special considerations or notes

#### Core Allocation

The `set_num_cores()` method allows you to configure how many processor cores a plan will use:

```python
RasPlan.set_num_cores("01", 4)  # Set the plan to use 4 cores
```

Considerations for core allocation:
- For 1D models, 2-4 cores typically offer the best performance
- For 2D models, 4-8 cores may provide better performance depending on mesh size
- Using too many cores can actually decrease performance due to overhead
- Consider your system's physical core count rather than logical cores

These operations allow you to programmatically customize HEC-RAS simulations for batch processing, parameter studies, or automated workflows.

### Performance Optimization

Optimizing performance in RAS Commander involves balancing between execution speed and resource utilization. Here are detailed strategies:

1. **Parallel Execution**:
   Use `RasCmdr.compute_parallel()` for running multiple plans concurrently:

   ```python
   from ras_commander import RasCmdr

   results = RasCmdr.compute_parallel(
       plan_numbers=["01", "02", "03"],
       max_workers=3,
       num_cores=4
   )
   ```

   - Adjust `max_workers` based on the number of plans and available system resources.
   - Set `num_cores` to balance between single-plan performance and overall throughput.

2. **Geometry Preprocessing**:
   Preprocess geometry to avoid redundant calculations:

   ```python
   from ras_commander import RasPlan

   RasPlan.set_geom_preprocessor(plan_path, run_htab=1, use_ib_tables=0)
   ```

   - Set `run_htab=1` to force geometry preprocessing.
   - Use `use_ib_tables=0` to recompute internal boundary tables.

3. **Memory Management**:
   When working with large datasets, use chunking and iterative processing:

   ```python
   import dask.array as da
   from ras_commander import HdfResultsMesh

   data = HdfResultsMesh.mesh_timeseries_output(hdf_path, mesh_name, "Water Surface")
   dask_array = da.from_array(data.values, chunks=(1000, 1000))
   ```

4. **I/O Optimization**:
   Minimize disk I/O by batching read/write operations:

   ```python
   from ras_commander import HdfUtils

   with h5py.File(hdf_path, 'r') as hdf_file:
       datasets = HdfUtils.get_hdf_paths_with_properties(hdf_file)
       # Process multiple datasets in a single file open operation
   ```

5. **Profiling and Monitoring**:
   Use Python's built-in profiling tools to identify performance bottlenecks:

   ```python
   import cProfile

   cProfile.run('RasCmdr.compute_plan("01")')
   ```

By applying these strategies, you can significantly improve the performance of your RAS Commander scripts, especially when dealing with large projects or multiple simulations.

### Working with Boundary Conditions

RAS Commander provides powerful tools for managing and analyzing boundary conditions in HEC-RAS projects. Here's how to work effectively with boundary conditions:

1. **Accessing Boundary Conditions**:
   Use the `boundaries_df` attribute of the RasPrj object:

   ```python
   from ras_commander import init_ras_project

   project = init_ras_project("/path/to/project", "6.5")
   boundary_conditions = project.boundaries_df
   print(boundary_conditions)
   ```

2. **Filtering Boundary Conditions**:
   You can easily filter boundary conditions by type or location:

   ```python
   # Get all flow hydrographs
   flow_hydrographs = boundary_conditions[boundary_conditions['bc_type'] == 'Flow Hydrograph']

   # Get boundary conditions for a specific river
   river_boundaries = boundary_conditions[boundary_conditions['river_reach_name'] == 'Main River']
   ```

3. **Analyzing Boundary Condition Data**:
   Extract detailed information from boundary conditions:

   ```python
   for _, bc in flow_hydrographs.iterrows():
       print(f"River: {bc['river_reach_name']}")
       print(f"Station: {bc['river_station']}")
       print(f"Number of values: {bc['hydrograph_num_values']}")
       print("---")
   ```

4. **Modifying Boundary Conditions**:
   While direct modification of boundary conditions is not supported, you can use RAS Commander to update unsteady flow files:

   ```python
   from ras_commander import RasUnsteady

   RasUnsteady.update_unsteady_parameters(unsteady_file_path, {"Parameter1": "NewValue1"})
   ```

5. **Visualizing Boundary Conditions**:
   Use pandas and matplotlib to visualize boundary condition data:

   ```python
   import matplotlib.pyplot as plt

   bc = flow_hydrographs.iloc[0]
   plt.plot(bc['hydrograph_values'])
   plt.title(f"Flow Hydrograph: {bc['name']}")
   plt.xlabel("Time Step")
   plt.ylabel("Flow")
   plt.show()
   ```

By leveraging these capabilities, you can effectively analyze and manage boundary conditions in your HEC-RAS projects using RAS Commander.

### Advanced Data Processing with RasUtils

RasUtils provides a set of powerful tools for data processing and analysis. Here are some advanced techniques:

1. **Data Conversion**:
   Convert various data sources to pandas DataFrames:

   ```python
   from ras_commander import RasUtils
   from pathlib import Path

   csv_data = RasUtils.convert_to_dataframe(Path("results.csv"))
   excel_data = RasUtils.convert_to_dataframe(Path("data.xlsx"), sheet_name="Sheet1")
   ```

2. **Statistical Analysis**:
   Perform statistical calculations on simulation results:

   ```python
   import numpy as np

   observed = np.array([100, 120, 140, 160, 180])
   predicted = np.array([105, 125, 135, 165, 175])

   rmse = RasUtils.calculate_rmse(observed, predicted)
   percent_bias = RasUtils.calculate_percent_bias(observed, predicted, as_percentage=True)
   metrics = RasUtils.calculate_error_metrics(observed, predicted)

   print(f"RMSE: {rmse}")
   print(f"Percent Bias: {percent_bias}%")
   print(f"Metrics: {metrics}")
   ```

3. **Spatial Operations**:
   Perform spatial queries and nearest neighbor searches:

   ```python
   import numpy as np

   points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
   query_points = np.array([[0.5, 0.5], [5, 5]])

   nearest = RasUtils.perform_kdtree_query(points, query_points)
   neighbors = RasUtils.find_nearest_neighbors(points)

   print(f"Nearest points: {nearest}")
   print(f"Neighbors: {neighbors}")
   ```

4. **Data Consolidation**:
   Consolidate and pivot complex datasets:

   ```python
   import pandas as pd

   df = pd.DataFrame({'A': [1, 1, 2], 'B': [4, 5, 6], 'C': [7, 8, 9]})
   consolidated = RasUtils.consolidate_dataframe(df, group_by='A', aggregation_method='list')

   print(consolidated)
   ```

5. **File Operations**:
   Perform advanced file operations with built-in error handling:

   ```python
   from pathlib import Path

   directory = Path("output")
   RasUtils.create_directory(directory)

   file_path = directory / "data.txt"
   RasUtils.check_file_access(file_path, mode='w')

   # Perform file operation here

   RasUtils.remove_with_retry(file_path, is_folder=False)
   ```

By utilizing these advanced data processing capabilities of RasUtils, you can efficiently handle complex data manipulation tasks in your RAS Commander workflows.

### Optimizing Parallel Execution with RAS Commander

Efficient parallel execution is crucial for maximizing the performance of HEC-RAS simulations, especially when dealing with multiple plans or large models. RAS Commander offers several strategies for optimizing parallel execution based on your specific needs and system resources.

#### Strategy 1: Efficiency Mode for Multiple Plans

This strategy maximizes overall throughput and efficiency when running multiple plans, although individual plan turnaround times may be longer.

**Key Points:**
- Use 2 real cores per plan
- Utilize only physical cores, not hyperthreaded cores

**Example:**
```python
from ras_commander import RasCmdr

# Assuming 8 physical cores on the system
RasCmdr.compute_parallel(
    plan_number=["01", "02", "03", "04"],
    max_workers=4,  # 8 cores / 2 cores per plan
    num_cores=2
)
```

#### Strategy 2: Performance Mode for Single Plans

This strategy maximizes single plan performance by using more cores. It results in less overall efficiency but shortens single plan runtime, making it optimal for situations where individual plan performance is critical.

**Key Points:**
- Use 8-16 cores per plan, depending on system capabilities
- Suitable for running a single plan or a small number of high-priority plans

**Example:**
```python
from ras_commander import RasCmdr

RasCmdr.compute_plan(
    plan_number="01",
    num_cores=12  # Adjust based on your system's capabilities
)
```

#### Strategy 3: Background Run Operation

This strategy balances performance and system resource usage, allowing for other operations to be performed concurrently.

**Key Points:**
- Limit total core usage to 50-80% of physical cores
- Combines aspects of Strategies 1 and 2
- Allows overhead for user to complete other operations while calculations are running

**Example:**
```python
import psutil
from ras_commander import RasCmdr

physical_cores = psutil.cpu_count(logical=False)
max_cores_to_use = int(physical_cores * 0.7)  # Using 70% of physical cores

RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"],
    max_workers=max_cores_to_use // 2,
    num_cores=2
)
```

#### Optimizing Geometry Preprocessing

To avoid repeated geometry preprocessing for each run, follow these steps:

1. **Preprocess Geometry:**
   ```python
   from ras_commander import RasPlan
   
   # For each plan you want to preprocess
   RasPlan.update_plan_value(plan_number, "Run HTab", 1)
   RasPlan.update_plan_value(plan_number, "Run UNet", -1)
   RasPlan.update_plan_value(plan_number, "Run PostProcess", -1)
   RasPlan.update_plan_value(plan_number, "Run RASMapper", -1)
   
   # Run the plan to preprocess geometry
   RasCmdr.compute_plan(plan_number)
   ```

2. **Run Simulations:**
   After preprocessing, update the flags for actual simulations:
   ```python
   RasPlan.update_plan_value(plan_number, "Run HTab", -1)
   RasPlan.update_plan_value(plan_number, "Run UNet", 1)
   RasPlan.update_plan_value(plan_number, "Run PostProcess", 1)
   RasPlan.update_plan_value(plan_number, "Run RASMapper", 0)
   ```

This approach preprocesses the geometry once, preventing redundant preprocessing when multiple plans use the same geometry.

#### Best Practices for Parallel Execution

- **Balance Cores:** Find the right balance between the number of parallel plans and cores per plan based on your system's capabilities.
- **Consider I/O Operations:** Be aware that disk I/O can become a bottleneck in highly parallel operations.
- **Test and Iterate:** Experiment with different configurations to find the optimal setup for your specific models and system.

By leveraging these strategies and best practices, you can significantly improve the performance and efficiency of your HEC-RAS simulations using RAS Commander.

## Troubleshooting

### 1. Project Initialization Issues

- **Ensure Correct Paths**: Verify that the project path is accurate and the `.prj` file exists.
- **HEC-RAS Version**: Confirm that the specified HEC-RAS version is installed on your system.

### 2. Execution Failures

- **File Existence**: Check that all referenced plan, geometry, and flow files exist.
- **Executable Path**: Ensure the HEC-RAS executable path is correctly set.
- **Log Files**: Review HEC-RAS log files for specific error messages.

### 3. Parallel Execution Problems

- **Resource Allocation**: Reduce `max_workers` if encountering memory issues.
- **System Capabilities**: Adjust `num_cores` based on your system's capacity.
- **Clean Environment**: Use `clear_geompre=True` to prevent conflicts.

### 4. File Access Errors

- **Permissions**: Verify read/write permissions for the project directory.
- **File Locks**: Close any open HEC-RAS instances that might lock files.

### 5. Inconsistent Results

- **Geometry Files**: Clear geometry preprocessor files when making changes.
- **Plan Parameters**: Ensure all plan parameters are correctly set before execution.

### 6. Infrastructure Analysis Issues
- Verify network connectivity in pipe systems
- Check pump station configurations
- Validate time series data consistency

### 7. HDF File Problems
- Check file permissions and access
- Verify HDF structure using HdfUtils
- Use proper file type specification with @standardize_input

### 8. Performance Optimization
- Monitor system resources during parallel execution
- Balance worker count with system capabilities
- Use appropriate chunking for large datasets

## Approaching Your End User Needs with Ras Commander

### Understanding Data Sources and Strategies

RAS Commander is designed to work efficiently with HEC-RAS projects by focusing on easily accessible data sources. This approach allows for powerful automation while avoiding some of the complexities inherent in HEC-RAS data management. Here's what you need to know:

1. **Data Sources in HEC-RAS Projects**:
   - ASCII input files (plan files, unsteady files, boundary conditions)
   - DSS (Data Storage System) files for inputs
   - HDF (Hierarchical Data Format) files for outputs

2. **RAS Commander's Focus**:
   - Primarily works with plain text inputs and HDF outputs
   - Avoids direct manipulation of DSS files due to their complexity

3. **Strategy for Handling DSS Inputs**:
   - Run the plan or preprocess geometry and event conditions
   - Access the resulting HDF tables, which contain the DSS inputs in an accessible format
   - Define time series directly in the ASCII file instead of as DSS inputs

4. **Accessing Project Data**:
   - Basic project data is loaded from ASCII text files by the RasPrj routines
   - Plan details are available in the HDF file
   - Geometry data is in the dynamically generated geometry HDF file

### Working with RAS Commander

1. **Initialization and Data Loading**:
   - Use `init_ras_project()` to load project data from ASCII files
   - Access plan information from HDF files using provided functions

2. **Handling Geometry Data**:
   - Geometry data is dynamically generated in HDF format
   - Focus on working with the HDF geometry data rather than plain text editing

3. **Workflow for Complex Operations**:
   - Perform the desired operation manually once
   - Provide an example to RAS Commander's AI GPT of what you're changing and why
   - Use this example to develop project-specific functions and code

4. **Example: Replacing DSS-defined Boundary Conditions**:
   - Open the data in HDF View
   - Extract the relevant dataset
   - Manually enter the time series based on the HDF dataset
   - Verify the model works with this change
   - Use this example to create an automated function for similar operations

### Best Practices

1. **Understanding Your Data**:
   - Familiarize yourself with the structure of your HEC-RAS project
   - Identify which data is stored in ASCII, DSS, and HDF formats

2. **Leveraging HDF Outputs**:
   - Whenever possible, use HDF outputs for data analysis and manipulation
   - This approach provides easy access to data without DSS complexities

3. **Iterative Development**:
   - Start with manual operations to understand the process
   - Gradually automate these processes using RAS Commander functions
   - Always check with the HEC-RAS GUI to verify the changes before finalizing the automation

4. **Documentation**:
   - Keep detailed notes on your workflow and changes
   - This documentation will be invaluable for creating automated processes

5. **Flexibility**:
   - Be prepared to adapt your approach based on specific project needs
   - RAS Commander provides a framework, but project-specific solutions will always require custom scripting
   - With an AI assistant, you can quickly leverage this library or your own custom functions to automate your workflows.

By following these strategies and best practices, you can effectively use RAS Commander to automate and streamline your HEC-RAS workflows, working around limitations and leveraging the strengths of the library's approach to data management.



# RAS-Commander Dataframe Examples

## Project Data Access

After initializing a HEC-RAS project with `init_ras_project()`, RAS-Commander provides several dataframes to access project data. These dataframes contain detailed information about plans, geometries, flow files, and boundary conditions. This section provides examples of these dataframes based on actual HEC-RAS projects.

### Project Information

The RasPrj object contains basic project information including:

```python
print(f"Project Name: {ras.project_name}")
print(f"Project Folder: {ras.project_folder}")
print(f"PRJ File: {ras.prj_path}")
print(f"HEC-RAS Executable Path: {ras.ras_exe_path}")
```

Example output:
```
Project Name: Muncie
Project Folder: c:\GH\ras-commander\examples\example_projects\Muncie
PRJ File: C:\GH\ras-commander\examples\example_projects\Muncie\Muncie.prj
HEC-RAS Executable Path: C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe
```

### Plan Files DataFrame (plan_df)

The `plan_df` dataframe contains information about all plan files in the project:

```python
print(ras.plan_df)
```

Key columns include:
- `plan_number`: The plan identifier (e.g., "01", "03")
- `full_path`: Complete path to the plan file
- `UNET D1 Cores` & `UNET D2 Cores`: Core allocation for 1D and 2D calculations
- `Computation Interval`: Simulation time step
- `Geom File`: Associated geometry file
- `Flow File` or `Unsteady File`: Associated flow file
- `Short Identifier`: Brief descriptive name for the plan
- `Simulation Date`: Start and end dates for the simulation
- `Run UNet`, `Run HTab`: Run flags for different simulation components
- `UNET Use Existing IB Tables`: Flag for using existing internal boundary tables
- `HDF_Results_Path`: Path to HDF results file (if available)
- `UNET 1D Methodology`, `UNET D2 SolverType`: Solver methods for 1D and 2D areas

Example from Muncie project:
```
  plan_number                                          full_path UNET D1 Cores UNET D2 Cores PS Cores Computation Interval DSS File Flow File Friction Slope Method Geom File ...  Run UNet Run WQNet    Short Identifier                   Simulation Date UNET Use Existing IB Tables HDF_Results_Path UNET 1D Methodology    UNET D2 SolverType     UNET D2 Name                                           Geom_File
0         01  c:\GH\ras-commander\examples\example_projects\...            0            0     None               15SEC      dss      u01                    1      g01 ...         1         0             9-SAs  02JAN1900,0000,02JAN1900,2400                         -1            None                NaN                  NaN             NaN  c:\GH\ras-commander\examples\example_projects\...
1         03  c:\GH\ras-commander\examples\example_projects\...            0            4     None               10SEC      dss      u01                    1      g02 ...        -1         0      2D 50ft Grid  02JAN1900,0000,02JAN1900,2400                         -1            None  Finite Difference  Pardiso (Direct)  2D Interior Area  c:\GH\ras-commander\examples\example_projects\...
2         04  c:\GH\ras-commander\examples\example_projects\...            0            6     None               10SEC      dss      u01                    1      g04 ...         1         0  50ft User n Regions  02JAN1900,0000,02JAN1900,2400                         -1            None  Finite Difference  Pardiso (Direct)  2D Interior Area  c:\GH\ras-commander\examples\example_projects\...
```

Example from BaldEagleDamBrk project (abbreviated):
```
  plan_number                                          full_path UNET D1 Cores UNET D2 Cores PS Cores Computation Interval DSS File Flow File Friction Slope Method Geom File ...  Run UNet Run WQNet      Short Identifier                   Simulation Date UNET Use Existing IB Tables UNET 1D Methodology    UNET D2 SolverType   UNET D2 Name HDF_Results_Path                                           Geom_File
0         13  c:\GH\ras-commander\examples\example_projects\...            0            8     None               30SEC      dss      u07                    1      g06 ...         1         0        PMF Multi 2D  01JAN1999,1200,04JAN1999,1200                         -1  Finite Difference  Pardiso (Direct)           193            None  c:\GH\ras-commander\examples\example_projects\...
1         15  c:\GH\ras-commander\examples\example_projects\...            0            6     None               20SEC      dss      u12                    1      g08 ...         1         0  1D-2D Refined Grid  01JAN1999,1200,04JAN1999,1200                         -1  Finite Difference                NaN  BaldEagleCr            None  c:\GH\ras-commander\examples\example_projects\...
...
```

### Flow Files DataFrame (flow_df)

The `flow_df` dataframe contains information about steady flow files in the project:

```python
print(ras.flow_df)
```

Columns include:
- `flow_number`: The flow file identifier
- `full_path`: Complete path to the flow file

Example:
```
  flow_number                                          full_path
0         01  c:\GH\ras-commander\examples\example_projects\...
```

### Unsteady Flow Files DataFrame (unsteady_df)

The `unsteady_df` dataframe contains information about unsteady flow files:

```python
print(ras.unsteady_df)
```

Columns include:
- `unsteady_number`: The unsteady flow file identifier
- `full_path`: Complete path to the unsteady flow file
- `Flow Title`: The title of the flow file
- `Program Version`: HEC-RAS version used to create the file
- `Use Restart`: Flag for using restart files
- `Precipitation Mode`, `Wind Mode`: Settings for meteorological conditions
- `Met BC=Precipitation|Expanded View`: Flag for expanded view of precipitation data
- `Met BC=Precipitation|Gridded Source`: Source for gridded precipitation data

Example from Muncie project:
```
  unsteady_number                                          full_path             Flow Title Program Version Use Restart Precipitation Mode   Wind Mode Met BC=Precipitation|Expanded View Met BC=Precipitation|Gridded Source
0             01  c:\GH\ras-commander\examples\example_projects\...  Flow Boundary Conditions           6.30           0            Disable  No Wind Forces                                0                               DSS
```

Example from BaldEagleDamBrk project (abbreviated):
```
  unsteady_number                                          full_path                     Flow Title Program Version Use Restart Precipitation Mode   Wind Mode Met BC=Precipitation|Mode Met BC=Evapotranspiration|Mode Met BC=Precipitation|Expanded View Met BC=Precipitation|Constant Units Met BC=Precipitation|Gridded Source
0             07  c:\GH\ras-commander\examples\example_projects\...        PMF with Multi 2D Areas           5.00           0                NaN        NaN                     NaN                           NaN                            NaN                             NaN                               NaN
...
9             03  c:\GH\ras-commander\examples\example_projects\...           Gridded Precipitation           6.00           0            Enable  No Wind Forces                Gridded                        None                             -1                           mm/hr                               DSS
```

### Geometry Files DataFrame (geom_df)

The `geom_df` dataframe contains information about geometry files:

```python
print(ras.geom_df)
```

Columns include:
- `geom_file`: The geometry file name (e.g., "g01")
- `geom_number`: The geometry file identifier
- `full_path`: Complete path to the geometry file
- `hdf_path`: Path to the associated HDF file (if available)

Example from Muncie project:
```
  geom_file geom_number                                          full_path                                           hdf_path
0       g01          01  c:\GH\ras-commander\examples\example_projects\...  c:\GH\ras-commander\examples\example_projects\...
1       g02          02  c:\GH\ras-commander\examples\example_projects\...  c:\GH\ras-commander\examples\example_projects\...
2       g04          04  c:\GH\ras-commander\examples\example_projects\...  c:\GH\ras-commander\examples\example_projects\...
```

### HDF Entries DataFrame (hdf_df)

The `hdf_df` dataframe contains information about HDF results files generated from plan computations:

```python
print(ras.hdf_df)
```

This dataframe has the same structure as `plan_df` but includes an additional `HDF_Results_Path` column pointing to the generated HDF file. In the examples provided, no HDF results have been generated yet, so the dataframe is empty:

```
Empty DataFrame
Columns: [plan_number, full_path, UNET D1 Cores, UNET D2 Cores, PS Cores, Computation Interval, DSS File, Flow File, Friction Slope Method, Geom File, ... HDF_Results_Path, UNET 1D Methodology, UNET D2 SolverType, UNET D2 Name, Geom_File]
0 rows × 26 columns
```

### Boundary Conditions DataFrame (boundaries_df)

The `boundaries_df` dataframe contains detailed information about boundary conditions defined in unsteady flow files:

```python
print(ras.boundaries_df)
```

Key columns include:
- `unsteady_number`: The unsteady flow file identifier
- `boundary_condition_number`: Sequential number of the boundary condition
- `river_reach_name`, `river_station`: Location of the boundary condition
- `storage_area_name`, `pump_station_name`: Associated storage areas or pump stations
- `bc_type`: Type of boundary condition (e.g., "Flow Hydrograph", "Normal Depth")
- `hydrograph_type`: Type of hydrograph for the boundary
- `Interval`: Time interval for hydrograph data
- `DSS Path`: Path to DSS file with boundary data
- `hydrograph_num_values`: Number of values in the hydrograph
- `hydrograph_values`: Array of values for the hydrograph

Example from Muncie project:
```
  unsteady_number  boundary_condition_number river_reach_name river_station storage_area_name pump_station_name          bc_type       hydrograph_type Interval  DSS Path ... hydrograph_num_values                                   hydrograph_values                                          full_path             Flow Title Program Version Use Restart Precipitation Mode   Wind Mode Met BC=Precipitation|Expanded View Met BC=Precipitation|Gridded Source
0             01                        1           White     Muncie       15696.24                     Flow Hydrograph  Flow Hydrograph    1HOUR        ...                 65  [13500, 14000, 14500, 15000, 15500, 16000, 165...  c:\GH\ras-commander\examples\example_projects\...  Flow Boundary Conditions           6.30           0            Disable  No Wind Forces                                0                               DSS
1             01                        2           White     Muncie         237.6455                     Normal Depth           None      NaN        NaN ...                  0                                                NaN  c:\GH\ras-commander\examples\example_projects\...  Flow Boundary Conditions           6.30           0            Disable  No Wind Forces                                0                               DSS
```

Example from BaldEagleDamBrk project (abbreviated):
```
  unsteady_number  boundary_condition_number river_reach_name    river_station storage_area_name pump_station_name                      bc_type                hydrograph_type Interval                DSS File ...             Flow Title Program Version Use Restart Precipitation Mode   Wind Mode Met BC=Precipitation|Mode Met BC=Evapotranspiration|Mode Met BC=Precipitation|Expanded View Met BC=Precipitation|Constant Units Met BC=Precipitation|Gridded Source
0             07                        1  Bald Eagle Cr.      Lock Haven       137520                     Flow Hydrograph           Flow Hydrograph    1HOUR  Bald_Eagle_Creek.dss ...  PMF with Multi 2D Areas           5.00           0                NaN        NaN                     NaN                           NaN                            NaN                             NaN                               NaN
1             07                        2  Bald Eagle Cr.      Lock Haven        81454                         Gate Opening                  None      NaN               NaN ...  PMF with Multi 2D Areas           5.00           0                NaN        NaN                     NaN                           NaN                            NaN                             NaN                               NaN
...
```

## Accessing and Using Dataframes

These dataframes provide structured access to HEC-RAS project data. Here are some example operations:

### Finding Plans by Description

```python
# Find all 2D plans
two_d_plans = ras.plan_df[ras.plan_df['Short Identifier'].str.contains('2D', na=False)]
print(two_d_plans[['plan_number', 'Short Identifier']])
```

### Examining Computation Intervals

```python
# Get all unique computation intervals
intervals = ras.plan_df['Computation Interval'].unique()
print(f"Computation intervals used: {intervals}")

# Find plans with specific interval
fast_plans = ras.plan_df[ras.plan_df['Computation Interval'] == '5SEC']
print(fast_plans[['plan_number', 'Short Identifier']])
```

### Analyzing Boundary Conditions

```python
# Count boundary conditions by type
bc_counts = ras.boundaries_df['bc_type'].value_counts()
print(bc_counts)

# Get all flow hydrographs
flow_hydrographs = ras.boundaries_df[ras.boundaries_df['bc_type'] == 'Flow Hydrograph']
print(flow_hydrographs[['unsteady_number', 'river_reach_name', 'river_station']])
```

### Finding Plans with Specific Solver Settings

```python
# Find plans using the Pardiso solver
pardiso_plans = ras.plan_df[ras.plan_df['UNET D2 SolverType'].str.contains('Pardiso', na=False)]
print(pardiso_plans[['plan_number', 'Short Identifier', 'UNET D2 SolverType']])
```

### Examining Core Allocation

```python
# Analyze core usage
ras.plan_df[['plan_number', 'Short Identifier', 'UNET D1 Cores', 'UNET D2 Cores']]
```

These examples demonstrate how to access and utilize the rich project data available through RAS-Commander's dataframes after initializing a project.



## Conclusion

The RAS-Commander (`ras_commander`) library provides a powerful set of tools for automating HEC-RAS operations. By following the best practices outlined in this guide and leveraging the library's features, you can efficiently manage and execute complex HEC-RAS projects programmatically.

Remember to refer to the latest documentation and the library's source code for up-to-date information. As you become more familiar with `ras_commander`, you'll discover more ways to optimize your HEC-RAS workflows and increase productivity.

For further assistance, bug reports, or feature requests, please refer to the library's [GitHub repository](https://github.com/billk-FM/ras-commander) and issue tracker.

**Happy Modeling!**

**Note on Module Naming Convention:**
While the library now uses capitalized names for the `Decorators.py` and `LoggingConfig.py` modules, it's worth noting that this deviates from the PEP 8 style guide, which recommends lowercase names for modules. Future versions of the library may revert to lowercase naming for consistency with Python conventions. Users should be aware of this potential change in future updates.