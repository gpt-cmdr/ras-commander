# Comprehensive RAS-Commander Library Guide

## Introduction

RAS-Commander (`ras_commander`) is a Python library designed to automate and streamline operations with HEC-RAS projects. It provides a suite of tools for managing projects, executing simulations, and handling results. This guide offers a comprehensive overview of the library's key concepts, modules, best practices, and advanced usage patterns.

---

## Table of Contents

- [Key Concepts](#key-concepts)
- [Module Overview](#module-overview)
- [Best Practices](#best-practices)
- [Usage Patterns](#usage-patterns)
  - [Initializing a Project](#initializing-a-project)
  - [Cloning a Plan](#cloning-a-plan)
  - [Executing Plans](#executing-plans)
  - [Working with Multiple Projects](#working-with-multiple-projects)
  - [Performance Optimization](#performance-optimization)
- [Advanced Usage](#advanced-usage)
  - [RasExamples](#rasexamples)
  - [RasUtils](#rasutils)
  - [Artifact System](#artifact-system)
  - [AI-Driven Coding Tools](#ai-driven-coding-tools)
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
   - `RasUtils` provides common utility functions for file operations, backups, and error handling.

8. **Artifact System**:
   - Handles substantial, self-contained content that users might modify or reuse, displayed in a separate UI window.

9. **AI-Driven Coding Tools**:
   - Integrates AI-powered tools like ChatGPT Assistant, LLM Summaries, Cursor IDE Integration, and Jupyter Notebook Assistant.

---

## Module Overview

1. **RasPrj**: Manages HEC-RAS project initialization and data.
2. **RasCmdr**: Handles execution of HEC-RAS simulations.
3. **RasPlan**: Provides functions for plan file operations.
4. **RasGeo**: Manages geometry file operations.
5. **RasUnsteady**: Handles unsteady flow file operations.
6. **RasUtils**: Offers utility functions for common tasks.
7. **RasExamples**: Manages example HEC-RAS projects.

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

### Artifact System

The artifact system in `ras_commander` is designed to handle substantial, self-contained content that users might modify or reuse. Artifacts are displayed in a separate UI window for clarity.

#### When to Use Artifacts

- **Code Snippets**: Longer than 15 lines.
- **Complex Diagrams or Charts**: Visual representations that require focus.
- **Detailed Reports or Documentation**: Extensive text content.

#### Example of Creating an Artifact

```python
# Example Function Artifact

<ANTARTIFACTLINK identifier="example-function" type="application/vnd.ant.code" language="python" title="Example Function" isClosed="true" />
```

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

---

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