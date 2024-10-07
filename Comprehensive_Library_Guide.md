# Comprehensive RAS-Commander Library Guide

## Introduction

RAS-Commander (`ras_commander`) is a Python library designed to automate and streamline operations with HEC-RAS projects. It provides a suite of tools for managing projects, executing simulations, and handling results. This guide offers a comprehensive overview of the library's key concepts, modules, best practices, and advanced usage patterns. RAS-Commander is designed to be flexible, robust, and AI-accessible, making it an ideal tool for both manual and automated HEC-RAS workflows.

RAS-Commander can be installed with the following commands:
```
pip install h5py numpy pandas requests tqdm scipy
pip install ras-commander
```

---

## Table of Contents

- [Key Concepts](#key-concepts)
- [Core Features](#core-features)
- [Module Overview](#module-overview)
- [Best Practices](#best-practices)
- [Usage Patterns](#usage-patterns)
  - [Initializing a Project](#initializing-a-project)
  - [Cloning a Plan](#cloning-a-plan)
  - [Executing Plans](#executing-plans)
  - [Working with Multiple Projects](#working-with-multiple-projects)
  - [Performance Optimization](#performance-optimization)
  - [Working with Boundary Conditions](#working-with-boundary-conditions)
  - [Using RasUtils Statistical Methods](#using-rasutils-statistical-methods)
- [Advanced Usage](#advanced-usage)
  - [RasExamples](#rasexamples)
  - [RasUtils](#rasutils)
  - [Artifact System](#artifact-system)
  - [AI-Driven Coding Tools](#ai-driven-coding-tools)
  - [Working with Boundary Conditions](#working-with-boundary-conditions-1)
  - [Advanced Data Processing with RasUtils](#advanced-data-processing-with-rasutils)
- [RasHdf](#rashdf)
- [Troubleshooting](#troubleshooting)
- [Conclusion](#conclusion)

---

## Key Concepts

1. **RAS Objects**:
   - Represent HEC-RAS projects containing information about plans, geometries, and flow files.
   - Support both a global `ras` object and custom `RasPrj` instances for different projects.

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
   - **Single Plan Execution**: Run individual plans.
   - **Sequential Execution**: Run multiple plans in sequence.
   - **Parallel Execution**: Run multiple plans concurrently for improved performance.

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
    - All classes are designed to work with either a global 'ras' object + a plan number, or with custom project instances.
    - Clear separation of concerns between project management (RasPrj), execution (RasCmdr), and results data retrieval (RasHdf).

12. **Error Handling and Logging**:
    - Emphasis on robust error checking and informative logging throughout the library.
    - Utilizes the `logging_config` module for consistent logging configuration.
    - `@log_call` decorator applied to relevant functions for logging function calls.

13. **AI-Accessibility**:
    - Structured, consistent codebase with clear documentation to facilitate easier learning and usage by AI models.

---


## Module Overview

1. **RasPrj**: Manages HEC-RAS project initialization and data, including boundary conditions.
2. **RasCmdr**: Handles execution of HEC-RAS simulations.
3. **RasPlan**: Provides functions for plan file operations.
4. **RasGeo**: Manages geometry file operations.
5. **RasUnsteady**: Handles unsteady flow file operations.
6. **RasUtils**: Offers utility functions for common tasks and statistical analysis.
7. **RasExamples**: Manages example HEC-RAS projects.
8. **RasHdf**: Provides utilities for working with HDF files in HEC-RAS projects.

---

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
  - Create separate `RasPrj` instances for each project.
    ```python
    from ras_commander import RasPrj, init_ras_project

    project1 = init_ras_project("/path/to/project1", "6.5", ras_instance=RasPrj())
    project2 = init_ras_project("/path/to/project2", "6.5", ras_instance=RasPrj())
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

- Adjust `max_workers` and `num_cores` based on system capabilities.
  ```python
  RasCmdr.compute_parallel(max_workers=4, num_cores=2)
  ```

- Use `dest_folder` to organize outputs and prevent conflicts.
  ```python
  RasCmdr.compute_parallel(dest_folder="/path/to/results")
  ```

### 5. Error Handling

- Implement try-except blocks to handle potential errors.
  ```python
  try:
      RasCmdr.compute_plan("01")
  except FileNotFoundError:
      print("Plan file not found")
  ```

- Utilize logging for informative output.
  ```python
  import logging
  logging.basicConfig(level=logging.INFO)
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
  def compute_plan(plan_number: str, clear_geompre: bool = False) -> bool:
      ...
  ```

---

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
      plan_numbers=["01", "02", "03"],
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
project1 = init_ras_project("/path/to/project1", "6.5", ras_instance=RasPrj())
project2 = init_ras_project("/path/to/project2", "6.5", ras_instance=RasPrj())

# Perform operations on each project
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("02", ras_object=project2)

# Compare results
results1 = project1.get_hdf_entries()
results2 = project2.get_hdf_entries()
```

### Performance Optimization

```python
from ras_commander import RasCmdr

results = RasCmdr.compute_parallel(
    plan_numbers=["01", "02", "03"],
    max_workers=3,
    num_cores=4,
    dest_folder="/path/to/results",
    clear_geompre=True
)

for plan, success in results.items():
    print(f"Plan {plan}: {'Successful' if success else 'Failed'}")
```

- **Best Practices**:
  - Use `compute_parallel()` for concurrent plan execution.
  - Adjust `max_workers` and `num_cores` based on system capabilities.
  - Organize outputs with `dest_folder`.
  - Use `clear_geompre=True` for clean computations.

### Working with Boundary Conditions

```python
from ras_commander import init_ras_project

# Initialize a project
project = init_ras_project("/path/to/project", "6.5")

# Access boundary conditions
boundary_conditions = project.boundaries_df

# Display boundary condition information
print(boundary_conditions)

# Filter boundary conditions for a specific river
river_boundaries = boundary_conditions[boundary_conditions['river_reach_name'] == 'Main River']
print(river_boundaries)
```

### Using RasUtils Statistical Methods

```python
from ras_commander import RasUtils
import numpy as np

# Example observed and predicted values
observed = np.array([100, 120, 140, 160, 180])
predicted = np.array([105, 125, 135, 165, 175])

# Calculate error metrics
metrics = RasUtils.calculate_error_metrics(observed, predicted)

print(f"Correlation: {metrics['cor']:.4f}")
print(f"RMSE: {metrics['rmse']:.4f}")
print(f"Percent Bias: {metrics['pb']:.4f}")

# Calculate individual metrics
rmse = RasUtils.calculate_rmse(observed, predicted)
percent_bias = RasUtils.calculate_percent_bias(observed, predicted, as_percentage=True)

print(f"RMSE: {rmse:.4f}")
print(f"Percent Bias: {percent_bias:.2f}%")
```

---

## Advanced Usage

### RasExamples

The `RasExamples` class provides functionality for managing HEC-RAS example projects. This is particularly useful for testing, learning, and development purposes.

#### Key Concepts

- **Example Project Management**: Access and manipulate example projects.
- **Automatic Downloading and Extraction**: Fetches projects from official sources.
- **Project Categorization**: Organizes projects into categories for easy navigation.

#### Usage Patterns

```python
from ras_commander import RasExamples

# Initialize RasExamples
ras_examples = RasExamples()

# Download example projects (if not already present)
ras_examples.get_example_projects()

# List available categories
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
```

### RasUtils

The `RasUtils` class provides utility functions for common tasks in the `ras_commander` library.

#### Key Concepts

- **File and Directory Operations**: Create, delete, and manage files and directories.
- **Backup and Restoration**: Safeguard original files with backups.
- **Error Handling and Retries**: Robust methods to handle common file system errors.
- **Statistical Analysis**: Perform calculations such as RMSE, correlation, and percent bias.

#### Usage Patterns

```python
from ras_commander import RasUtils
from pathlib import Path

# Create a backup of a file
original_file = Path("project.prj")
backup_file = RasUtils.create_backup(original_file)

# Ensure a directory exists
output_dir = RasUtils.create_directory(Path("output"))

# Find files by extension
prj_files = RasUtils.find_files_by_extension(".prj")

# Get file information
file_size = RasUtils.get_file_size(original_file)
mod_time = RasUtils.get_file_modification_time(original_file)

# Update a plan file
RasUtils.update_plan_file("01", "Geom", 2)

# Remove a file or folder with retry logic
RasUtils.remove_with_retry(Path("temp_folder"), is_folder=True)
```

Certainly! I'll expand the Comprehensive Library Guide with more detailed information on RAS Objects, project initialization, file handling, and consistent file path management. Here's an enhanced version of those sections:

# Comprehensive RAS-Commander Library Guide

## Key Concepts

### RAS Objects

RAS Objects are central to the ras-commander library. They represent HEC-RAS projects and contain all the necessary information about plans, geometries, flow files, and other project components.

1. **Global 'ras' Object**: 
   - By default, the library uses a global 'ras' object.
   - This object is automatically initialized when you call `init_ras_project()`.
   - Suitable for simple scripts working with a single project.

2. **Custom RAS Objects**:
   - For more complex scenarios or when working with multiple projects, you can create custom RAS objects.
   - These are instances of the `RasPrj` class.
   - Allow you to manage multiple projects simultaneously.

3. **Key Attributes of RAS Objects**:
   - `project_folder`: Path to the project folder
   - `prj_file`: Path to the project file
   - `project_name`: Name of the project
   - `ras_exe_path`: Path to the HEC-RAS executable
   - `plan_df`: DataFrame containing plan information
   - `geom_df`: DataFrame containing geometry information
   - `flow_df`: DataFrame containing flow information
   - `unsteady_df`: DataFrame containing unsteady flow information

4. **Importance of Initialization**:
   - RAS objects must be initialized before use.
   - Initialization loads all project data and sets up necessary attributes.
   - Always check if a RAS object is initialized before performing operations.

Example of using custom RAS objects:

```python
from ras_commander import init_ras_project, RasPrj

project1 = init_ras_project("/path/to/project1", "6.5", ras_instance=RasPrj())
project2 = init_ras_project("/path/to/project2", "6.5", ras_instance=RasPrj())

# Now you can work with project1 and project2 independently
```

### Project Initialization and File Handling

Proper project initialization is crucial for the correct functioning of the ras-commander library. The `init_ras_project()` function is the primary method for setting up a project.

1. **Project Initialization Process**:
   - Locates the project folder and HEC-RAS executable
   - Finds the main project file (.prj)
   - Loads all plan, geometry, and flow file information
   - Sets up DataFrames for easy access to project components

2. **File Discovery**:
   - The library automatically scans the project folder for relevant files
   - Files are categorized based on their extensions (e.g., .p* for plans, .g* for geometries)
   - File information is stored in respective DataFrames (plan_df, geom_df, etc.)

3. **Error Handling During Initialization**:
   - Checks for the existence of the project folder and necessary files
   - Raises informative errors if critical components are missing

4. **Post-Initialization**:
   - After initialization, you can access project information through the RAS object
   - Always check if the RAS object is initialized before performing operations

Example of project initialization:

```python
from ras_commander import init_ras_project, ras

init_ras_project("/path/to/project", "6.5")

# Now you can use the global 'ras' object
print(ras.project_name)
print(ras.plan_df)
```

### Consistent File Path Management

Consistent file path management is critical for reliable operation across different operating systems and environments. The ras-commander library uses `pathlib.Path` for all file and directory operations.

1. **Why Use pathlib.Path**:
   - Operating system independent
   - Provides an object-oriented interface for file path operations
   - Simplifies path manipulation and file operations

2. **Best Practices**:
   - Always use `Path` objects for file and directory paths
   - Use forward slashes ('/') in path strings, which work across all operating systems
   - Use relative paths when possible for better portability

3. **Path Resolution**:
   - The library resolves relative paths to absolute paths during initialization
   - Always work with absolute paths after initialization to avoid ambiguity

4. **Examples from the Library**:

```python
from pathlib import Path

# In RasPrj.py
self.project_folder = Path(project_folder)
self.prj_file = self.find_ras_prj(self.project_folder)

# In RasUtils.py
def create_backup(file_path: Path, backup_suffix: str = "_backup") -> Path:
    original_path = Path(file_path)
    backup_path = original_path.with_name(f"{original_path.stem}{backup_suffix}{original_path.suffix}")
    # ... rest of the function

# In user scripts
from ras_commander import init_ras_project, RasUtils

init_ras_project(Path("/path/to/project"), "6.5")
RasUtils.create_backup(Path("project.prj"))
```

5. **Handling User Input**:
   - When accepting file paths from users, always convert them to Path objects
   - Use `Path(user_input).resolve()` to get the absolute path

6. **Working with Multiple Projects**:
   - Keep paths relative to each project's base directory
   - Use `Path.relative_to()` when needed to get relative paths

By following these practices for file path management, you ensure that your scripts using the ras-commander library will work consistently across different systems and project structures.










### AI-Driven Coding Tools

`ras_commander` integrates several AI-powered tools to enhance the coding experience.

#### Tools and Features

1. **ChatGPT Assistant**:
   - Use for general questions about the library and its usage.
   - Provides code suggestions and explanations.

2. **LLM Summaries**:
   - Utilize large language models for up-to-date context on the codebase.
   - Available in two versions: full codebase and examples/docstrings only.

3. **Cursor IDE Integration**:
   - Offers context-aware suggestions and documentation.
   - Automatically includes a `.cursorrules` file when opening the `ras_commander` folder.

4. **Jupyter Notebook Assistant**:
   - Dynamic code summarization and API interaction.
   - Allows for real-time querying and exploration of the library.

#### Best Practices

- **Documentation First**: Start with the provided documentation and examples.
- **Specific Queries**: Use the ChatGPT Assistant for specific questions or clarifications.
- **LLM Summaries**: Leverage when working with external AI models.
- **IDE Integration**: Use Cursor IDE for the most integrated coding experience.
- **Interactive Learning**: Explore the Jupyter Notebook Assistant for experimentation.


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


### Working with Boundary Conditions

The `RasPrj` class now provides detailed information about boundary conditions in HEC-RAS projects. This can be particularly useful for advanced analysis and automation tasks.

```python
from ras_commander import init_ras_project

project = init_ras_project("/path/to/project", "6.5")

# Get all boundary conditions
all_boundaries = project.boundaries_df

# Filter for specific boundary condition types
flow_hydrographs = all_boundaries[all_boundaries['bc_type'] == 'Flow Hydrograph']
stage_hydrographs = all_boundaries[all_boundaries['bc_type'] == 'Stage Hydrograph']

# Analyze boundary conditions
for _, boundary in flow_hydrographs.iterrows():
    print(f"River: {boundary['river_reach_name']}")
    print(f"Station: {boundary['river_station']}")
    print(f"Number of values: {boundary['hydrograph_num_values']}")
    print("---")

# Access specific boundary condition details
if 'hydrograph_values' in flow_hydrographs.columns:
    first_hydrograph = flow_hydrographs.iloc[0]['hydrograph_values']
    print("First 5 values of the first flow hydrograph:")
    print(first_hydrograph[:5])
```

### Advanced Data Processing with RasUtils

RasUtils now includes methods for data conversion and statistical analysis, which can be useful for post-processing HEC-RAS results.

```python
from ras_commander import RasUtils
from pathlib import Path
import pandas as pd
import numpy as np

# Convert various data sources to DataFrame
csv_data = RasUtils.convert_to_dataframe(Path("results.csv"))
excel_data = RasUtils.convert_to_dataframe(Path("data.xlsx"), sheet_name="Sheet1")

# Combine data from different sources
combined_data = pd.concat([csv_data, excel_data])

# Perform statistical analysis
observed = combined_data['observed_values'].values
predicted = combined_data['predicted_values'].values

metrics = RasUtils.calculate_error_metrics(observed, predicted)
print("Error Metrics:", metrics)

# Save results to Excel with retry functionality
results_df = pd.DataFrame({
    'Metric': ['Correlation', 'RMSE', 'Percent Bias'],
    'Value': [metrics['cor'], metrics['rmse'], metrics['pb']]
})
RasUtils.save_to_excel(results_df, Path("analysis_results.xlsx"))
```

---

## RasHdf

The `RasHdf` class provides utilities for working with HDF (Hierarchical Data Format) files in HEC-RAS projects. HDF files are commonly used in HEC-RAS for storing large datasets and simulation results.

### Key Features of `RasHdf`:

1. **Reading HDF Tables**: Convert HDF5 datasets to pandas DataFrames.
2. **Writing DataFrames to HDF**: Save pandas DataFrames as HDF5 datasets.
3. **Spatial Operations**: Perform KDTree queries and find nearest neighbors.
4. **Data Consolidation**: Merge duplicate values in DataFrames.
5. **Byte String Handling**: Decode byte strings in DataFrames.

### Example Usage:

```python
from ras_commander import RasHdf
import h5py
import pandas as pd

# Read an HDF table
with h5py.File('results.hdf', 'r') as f:
    dataset = f['water_surface_elevations']
    df = RasHdf.read_hdf_to_dataframe(dataset)

print(df.head())

# Save a DataFrame to HDF
new_data = pd.DataFrame({'A': [1, 2, 3], 'B': ['a', 'b', 'c']})
with h5py.File('new_results.hdf', 'w') as f:
    group = f.create_group('my_results')
    RasHdf.save_dataframe_to_hdf(new_data, group, 'my_dataset')

# Perform a KDTree query
import numpy as np
reference_points = np.array([[0, 0], [1, 1], [2, 2]])
query_points = np.array([[0.5, 0.5], [1.5, 1.5]])
results = RasHdf.perform_kdtree_query(reference_points, query_points)
print("KDTree query results:", results)
```




## HDF Paths Supported

This is a list of HDF paths that are directly supported by specialized library functions: 


1. General Paths:
   - '/Results/Summary/Compute Messages (text)'
   - '/Plan Data/Plan Parameters'
   - '/Results/Unsteady/Summary/Volume Accounting/Volume Accounting 2D'

2. Geometry Paths:
   - '/Geometry/2D Flow Areas'
   - '/Geometry/2D Flow Areas/{area_name}/Cell Info'
   - '/Geometry/2D Flow Areas/{area_name}/Cell Points'
   - '/Geometry/2D Flow Areas/{area_name}/Polygon Info'
   - '/Geometry/2D Flow Areas/{area_name}/Polygon Parts'
   - '/Geometry/2D Flow Areas/{area_name}/Polygon Points'
   - '/Geometry/2D Flow Areas/{area_name}/Cells Center Coordinate'
   - '/Geometry/2D Flow Areas/{area_name}/Cells Center Manning\'s n'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Area Elevation Values'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Cell Indexes'
   - '/Geometry/2D Flow Areas/{area_name}/Faces FacePoint Indexes'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Low Elevation Centroid'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Minimum Elevation'
   - '/Geometry/2D Flow Areas/{area_name}/Faces NormalUnitVector and Length'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Perimeter Info'
   - '/Geometry/2D Flow Areas/{area_name}/Faces Perimeter Values'
   - '/Geometry/2D Flow Areas/{area_name}/Face Points Coordinates'
   - '/Geometry/2D Flow Areas/{area_name}/Perimeter'
   - '/Geometry/Boundary Condition Lines/Attributes'

3. Results Paths:
   - '/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time'
   - '/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp'
   - '/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area_name}/Water Surface'  # PLACEHOLDER ONLY, DOES NOT WORK
   - '/Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area_name}/Face Velocity'  # PLACEHOLDER ONLY, DOES NOT WORK
   - '/Results/Summary/Compute Processes'

4. Infiltration Paths:
   - '/Geometry/2D Flow Areas/{area_name}/Infiltration/Cell Center Classifications'
   - '/Geometry/2D Flow Areas/{area_name}/Infiltration/Face Center Classifications'
   - '/Geometry/2D Flow Areas/{area_name}/Infiltration/Initial Deficit'
   - '/Geometry/2D Flow Areas/{area_name}/Infiltration/Maximum Deficit'
   - '/Geometry/2D Flow Areas/{area_name}/Infiltration/Potential Percolation Rate'

5. Percent Impervious Paths:
   - '/Geometry/2D Flow Areas/{area_name}/Percent Impervious/Cell Center Classifications'
   - '/Geometry/2D Flow Areas/{area_name}/Percent Impervious/Face Center Classifications'
   - '/Geometry/2D Flow Areas/{area_name}/Percent Impervious/Percent Impervious'


## RasHdf class structure, methods, decorators, and their significance:

1. Class Structure:
   - RasHdf is a utility class designed to work with HDF files produced by HEC-RAS.
   - It contains only static methods, meaning no instance of the class needs to be created to use its functionality.
   - The class serves as a namespace for grouping related HDF file operations.

2. Primary Decorator:
   - @staticmethod: Used on all methods in the class.
   - Significance: Allows methods to be called on the class itself rather than an instance, fitting the utility nature of the class.

3. Custom Decorator:
   - @hdf_operation: A custom decorator defined within the RasHdf class.
   - Purpose: Provides a consistent way to handle HDF file operations, including error handling and file opening/closing.
   - Significance: Centralizes common HDF file handling logic, reducing code duplication and ensuring consistent error handling across methods.

4. Key Methods and Their Purposes:
   a. get_hdf_paths_with_properties(): Lists all paths in the HDF file with their properties.
   b. get_runtime_data(): Extracts runtime and compute time data.
   c. get_2d_flow_area_names(): Lists 2D Flow Area names.
   d. get_2d_flow_area_attributes(): Extracts 2D Flow Area attributes.
   e. get_cell_info(), get_cell_points(): Extract cell-related information.
   f. get_polygon_info_and_parts(), get_polygon_points(): Handle polygon data.
   g. get_cells_center_data(): Extracts cell center coordinates and Manning's n values.
   h. get_faces_area_elevation_data(): Extracts face area elevation data.
   i. load_2d_area_solutions(): Loads 2D area solutions including water surface elevations and velocities.
   j. Methods for infiltration and percent impervious data extraction.

5. Method Structure:
   - Most methods follow a pattern of accepting an hdf_input (which can be a plan number or file path) and an optional ras_object.
   - This structure allows flexibility in how the methods are called, supporting both plan-based and direct file path-based access.

6. Error Handling:
   - Centralized in the @hdf_operation decorator.
   - Catches and logs exceptions, returning None on failure.
   - Provides consistent error reporting across all HDF operations.

7. Flexibility in Usage:
   - Methods can be used with either a global RAS object, a custom RAS object, or by directly providing an HDF file path.
   - This flexibility allows the class to be used in various contexts within the larger ras-commander library.

8. Integration with RasPrj:
   - Many methods rely on the RasPrj class to resolve plan numbers to actual file paths.
   - This integration allows for a high-level, project-oriented approach to working with HDF data.

9. Data Extraction and Conversion:
   - Most methods extract data from the HDF file and convert it to pandas DataFrames.
   - This approach makes the extracted data easily manipulable using standard pandas operations.

10. Significance within the Library:
    - RasHdf serves as the primary interface for extracting and analyzing HEC-RAS output data.
    - It bridges the gap between raw HDF files and usable Python data structures.
    - Enables advanced analysis and post-processing of HEC-RAS results within the ras-commander ecosystem.

11. Extensibility:
    - The class structure allows for easy addition of new methods to support additional HDF data extraction as needed.
    - The @hdf_operation decorator makes it straightforward to add new HDF file operations while maintaining consistent error handling and file management.

12. Performance Considerations:
    - Methods are designed to work with potentially large datasets.
    - Some methods (like load_2d_area_solutions) may be memory-intensive for large models and may require optimization for very large datasets.

This structure makes RasHdf a powerful and flexible tool for working with HEC-RAS output data, providing a pythonic interface to the complex structure of HEC-RAS HDF files. Its integration with the broader ras-commander library allows for seamless incorporation of data analysis into HEC-RAS automation workflows.



---


## Optimizing Parallel Execution with RAS Commander

Efficient parallel execution is crucial for maximizing the performance of HEC-RAS simulations, especially when dealing with multiple plans or large models. RAS Commander offers several strategies for optimizing parallel execution based on your specific needs and system resources.  For more information about these strategies and how to optimize your hardware for HEC-RAS CPU based simulations, see the following blog posts: 

- [10x Engineering in Water Resources with AI](https://github.com/billk-FM/HEC-Commander/blob/main/Blog/1.%2010x%20Engineering%20in%20Water%20Resources%20with%20AI.md)
- [10X Engineering By The Numbers](https://github.com/billk-FM/HEC-Commander/blob/main/Blog/2.%2010XEngineering_By_The_Numbers.md)
- [Think Like A Bootlegger for HEC-RAS Modeling Machines](https://github.com/billk-FM/HEC-Commander/blob/main/Blog/4._Think_Like_A_Bootlegger_for_HEC-RAS_Modeling_Machines.md)
- [Benchmarking Is All You Need](https://github.com/billk-FM/HEC-Commander/blob/main/Blog/7._Benchmarking_Is_All_You_Need.md)
- [Avoiding The Bitter Lesson In RAS Modeling](https://github.com/billk-FM/HEC-Commander/blob/main/Blog/9.Avoiding_The_Bitter_Lesson_In_RAS_Modeling.md)


### Strategy 1: Efficiency Mode for Multiple Plans

This strategy maximizes overall throughput and efficiency when running multiple plans, although individual plan turnaround times may be longer.

**Key Points:**
- Use 2 real cores per plan
- Utilize only physical cores, not hyperthreaded cores

**Example:**
```python
from ras_commander import RasCmdr

# Assuming 8 physical cores on the system
RasCmdr.compute_parallel(
    plan_numbers=["01", "02", "03", "04"],
    max_workers=4,  # 8 cores / 2 cores per plan
    num_cores=2
)
```

### Strategy 2: Performance Mode for Single Plans

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

### Strategy 3: Background Run Operation

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
    plan_numbers=["01", "02", "03"],
    max_workers=max_cores_to_use // 2,
    num_cores=2
)
```

### Optimizing Geometry Preprocessing

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

### Best Practices for Parallel Execution

**Balance Cores:** Find the right balance between the number of parallel plans and cores per plan based on your system's capabilities.
**Consider I/O Operations:** Be aware that disk I/O can become a bottleneck in highly parallel operations.
**Test and Iterate:** Experiment with different configurations to find the optimal setup for your specific models and system.

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

---

## Conclusion

The RAS-Commander (`ras_commander`) library provides a powerful set of tools for automating HEC-RAS operations. By following the best practices outlined in this guide and leveraging the library's features, you can efficiently manage and execute complex HEC-RAS projects programmatically.

Remember to refer to the latest documentation and the library's source code for up-to-date information. As you become more familiar with `ras_commander`, you'll discover more ways to optimize your HEC-RAS workflows and increase productivity.

For further assistance, bug reports, or feature requests, please refer to the library's [GitHub repository](https://github.com/billk-FM/ras-commander) and issue tracker.

---

**Happy Modeling!**