# Comprehensive RAS-Commander Library Guide

## Introduction

RAS-Commander (ras-commander) is a Python library designed to automate and streamline operations with HEC-RAS projects. This guide provides a comprehensive overview of the library's key concepts, best practices, and usage patterns.

## Key Concepts for ras_commander

1. **RAS Objects**: 
   - RAS objects represent HEC-RAS projects and contain information about plans, geometries, and flow files.
   - The library supports both a global 'ras' object and custom RAS objects for different projects.

2. **Project Initialization**: 
   - Use the `init_ras_project()` function to initialize a project and set up the RAS object.
   - This function handles finding the project file and setting up necessary data structures.

3. **File Handling**: 
   - The library uses `pathlib.Path` for consistent and platform-independent file path handling.
   - File naming conventions follow HEC-RAS standards (e.g., .prj, .p01, .g01, .f01, .u01).

4. **Data Management**: 
   - Pandas DataFrames are used to manage structured data about plans, geometries, and flow files.
   - The library provides methods to access and update these DataFrames.

5. **Execution Modes**: 
   - Single plan execution: Run individual plans.
   - Sequential execution: Run multiple plans in sequence.
   - Parallel execution: Run multiple plans concurrently for improved performance.

6. **Example Projects**: 
   - The RasExamples class provides functionality to download and manage HEC-RAS example projects for testing and learning purposes.

## Module Overview

1. **RasPrj**: Manages HEC-RAS project initialization and data.
2. **RasCmdr**: Handles execution of HEC-RAS simulations.
3. **RasPlan**: Provides functions for plan file operations.
4. **RasGeo**: Manages geometry file operations.
5. **RasUnsteady**: Handles unsteady flow file operations.
6. **RasUtils**: Offers utility functions for common tasks.
7. **RasExamples**: Manages example HEC-RAS projects.

## Best Practices

1. **RAS Object Usage**:
   - For simple scripts working with a single project, use the global 'ras' object:
     ```python
     from ras_commander import ras, init_ras_project
     init_ras_project("/path/to/project", "6.5")
     # Use ras object for operations
     ```
   - For complex scripts or when working with multiple projects, create and use separate RAS objects:
     ```python
     from ras_commander import RasPrj, init_ras_project
     project1 = init_ras_project("/path/to/project1", "6.5")
     project2 = init_ras_project("/path/to/project2", "6.5")
     ```
   - Be consistent: don't mix global and custom RAS object usage in the same script.

2. **Plan Specification**:
   - Use plan numbers as strings (e.g., "01", "02") for consistency:
     ```python
     RasCmdr.compute_plan("01")
     ```
   - Always check available plans before specifying plan numbers:
     ```python
     print(ras.plan_df)  # Display available plans
     ```

3. **Geometry Preprocessor Files**:
   - Clear geometry preprocessor files before significant changes:
     ```python
     RasGeo.clear_geompre_files()
     ```
   - Use `clear_geompre=True` for clean computation environment:
     ```python
     RasCmdr.compute_plan("01", clear_geompre=True)
     ```

4. **Parallel Execution**:
   - Consider available cores when setting `max_workers` and `num_cores`:
     ```python
     RasCmdr.compute_parallel(max_workers=4, num_cores=2)
     ```
   - Use `dest_folder` to keep project folder organized:
     ```python
     RasCmdr.compute_parallel(dest_folder="/path/to/results")
     ```

5. **Error Handling**:
   - Use try-except blocks to handle potential errors:
     ```python
     try:
         RasCmdr.compute_plan("01")
     except FileNotFoundError:
         print("Plan file not found")
     ```
   - Utilize logging for informative output:
     ```python
     import logging
     logging.basicConfig(level=logging.INFO)
     ```

6. **File Path Handling**:
   - Use pathlib.Path for file and directory operations:
     ```python
     from pathlib import Path
     project_path = Path("/path/to/project")
     ```

7. **Type Hinting**:
   - Use type hints to improve code readability and IDE support:
     ```python
     def compute_plan(plan_number: str, clear_geompre: bool = False) -> bool:
         ...
     ```

## Common Usage Patterns

1. **Initializing a Project**:
   ```python
   from ras_commander import init_ras_project, ras
   init_ras_project("/path/to/project", "6.5")
   print(f"Working with project: {ras.project_name}")
   ```

2. **Cloning a Plan**:
   ```python
   from ras_commander import RasPlan
   new_plan_number = RasPlan.clone_plan("01")
   print(f"Created new plan: {new_plan_number}")
   ```

3. **Updating Unsteady Flow Parameters**:
   ```python
   from ras_commander import RasUnsteady, RasPlan
   plan_path = RasPlan.get_plan_path("01")
   RasUnsteady.update_unsteady_parameters(plan_path, {"Computation Interval": "1MIN"})
   ```

4. **Executing a Single Plan**:
   ```python
   from ras_commander import RasCmdr
   success = RasCmdr.compute_plan("01", num_cores=2)
   print(f"Plan execution {'successful' if success else 'failed'}")
   ```

5. **Parallel Execution of Multiple Plans**:
   ```python
   from ras_commander import RasCmdr
   results = RasCmdr.compute_parallel(plan_numbers=["01", "02"], max_workers=2, num_cores=2)
   for plan, success in results.items():
       print(f"Plan {plan}: {'Successful' if success else 'Failed'}")
   ```

6. **Working with Example Projects**:
   ```python
   from ras_commander import RasExamples
   ras_examples = RasExamples()
   project_paths = ras_examples.extract_project(["Balde Eagle Creek", "Muncie"])
   for path in project_paths:
       print(f"Extracted project to: {path}")
   ```

## Advanced Usage

1. **Working with Multiple Projects**:
   ```python
   from ras_commander import init_ras_project, RasCmdr, RasPlan

   project1 = init_ras_project("/path/to/project1", "6.5")
   project2 = init_ras_project("/path/to/project2", "6.5")

   # Clone plans in both projects
   new_plan1 = RasPlan.clone_plan("01", ras_object=project1)
   new_plan2 = RasPlan.clone_plan("01", ras_object=project2)

   # Execute plans in both projects
   RasCmdr.compute_plan(new_plan1, ras_object=project1, num_cores=2)
   RasCmdr.compute_plan(new_plan2, ras_object=project2, num_cores=2)
   ```

2. **Using ThreadPoolExecutor for Simultaneous Execution**:
   ```python
   from concurrent.futures import ThreadPoolExecutor
   from ras_commander import RasCmdr

   def execute_plan(plan, project, compute_folder):
       return RasCmdr.compute_plan(plan, ras_object=project, compute_folder=compute_folder, num_cores=2)

   with ThreadPoolExecutor(max_workers=2) as executor:
       futures = [
           executor.submit(execute_plan, "01", project1, "compute_folder1"),
           executor.submit(execute_plan, "01", project2, "compute_folder2")
       ]
       for future in futures:
           print(f"Plan execution result: {future.result()}")
   ```

3. **Creating and Using Plan Sets**:
   ```python
   import pandas as pd
   from ras_commander import RasPlan, RasCmdr

   def create_plan_set(base_plan, num_copies):
       plan_set = []
       for _ in range(num_copies):
           new_plan = RasPlan.clone_plan(base_plan)
           plan_set.append({'plan_number': new_plan})
       return pd.DataFrame(plan_set)

   plan_set = create_plan_set("01", 5)
   results = RasCmdr.compute_parallel(plan_numbers=plan_set['plan_number'].tolist(), num_cores=2)
   ```

4. **Custom Error Handling and Logging**:
   ```python
   import logging
   from ras_commander import RasCmdr

   logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
   logger = logging.getLogger(__name__)

   try:
       RasCmdr.compute_plan("01", num_cores=2)
   except FileNotFoundError as e:
       logger.error(f"Plan file not found: {e}")
   except Exception as e:
       logger.exception(f"An unexpected error occurred: {e}")
   ```

5. **Advanced DataFrame Operations for Result Analysis**:
   ```python
   import pandas as pd
   from ras_commander import ras

   # Assuming we have executed multiple plans and have results
   results_df = ras.get_hdf_entries()

   # Filter and analyze results
   successful_runs = results_df[results_df['HDF_Results_Path'].notna()]
   print(f"Number of successful runs: {len(successful_runs)}")

   # You could add more advanced analysis here, such as comparing results across different plans
   ```

## Troubleshooting

1. **Project Initialization Issues**:
   - Ensure the project path is correct and the .prj file exists.
   - Verify that the specified HEC-RAS version is installed on your system.

2. **Execution Failures**:
   - Check that the plan, geometry, and flow files referenced in the plan exist.
   - Ensure the HEC-RAS executable path is correct.
   - Review HEC-RAS log files for specific error messages.

3. **Parallel Execution Problems**:
   - Reduce the number of `max_workers` if you're experiencing memory issues.
   - Ensure each worker has sufficient resources (cores, memory) to run a plan.
   - Adjust `num_cores` based on your system's capabilities and the complexity of your models.

4. **File Access Errors**:
   - Verify that you have read/write permissions for the project directory.
   - Close any open HEC-RAS instances that might be locking files.

5. **Inconsistent Results**:
   - Always clear geometry preprocessor files (`clear_geompre=True`) when making geometry changes.
   - Ensure that plan parameters are correctly set before execution.

## Conclusion

The RAS-Commander (ras-commander) library provides a powerful set of tools for automating HEC-RAS operations. By following the best practices outlined in this guide and leveraging the library's features, you can efficiently manage and execute complex HEC-RAS projects programmatically.

Remember to always refer to the latest documentation and the library's source code for the most up-to-date information. As you become more familiar with RAS-Commander, you'll discover more ways to optimize your HEC-RAS workflows and increase your productivity.

For further assistance, bug reports, or feature requests, please refer to the library's GitHub repository (https://github.com/billk-FM/ras-commander) and issue tracker. Happy modeling!