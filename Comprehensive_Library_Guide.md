# Comprehensive RAS-Commander Library Guide

## Introduction

RAS-Commander (`ras_commander`) is a Python library designed to automate and streamline operations with HEC-RAS projects. It provides a suite of tools for managing projects, executing simulations, and handling results. This guide offers a comprehensive overview of the library's key concepts, modules, best practices, and advanced usage patterns. RAS-Commander is designed to be flexible, robust, and AI-accessible, making it an ideal tool for both manual and automated HEC-RAS workflows.

RAS-Commander can be installed with the following commands:
```bash
# Install dependencies first for potentially smoother installation
pip install h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib psutil shapely fiona pathlib rtree

# Install or update ras-commander
pip install --upgrade ras-commander
```

## Key Concepts

1.  **RAS Objects (`RasPrj`)**:
    *   Represent HEC-RAS projects containing information about plans, geometries, and flow files.
    *   Support both a global `ras` object (imported from `ras_commander`) and custom named `RasPrj` instances to handle multiple projects.
    *   Include `rasmap_df` attribute providing access to spatial datasets referenced in RASMapper.

2.  **Project Initialization**:
    *   Use `init_ras_project()` to initialize projects and set up `RasPrj` objects.
    *   Handles project file (`.prj`) discovery, HEC-RAS executable path determination, and data structure setup.

3.  **File Handling**:
    *   Utilizes `pathlib.Path` for consistent, platform-independent file paths.
    *   Adheres to HEC-RAS file naming conventions (`.prj`, `.p01`, `.g01`, `.f01`, `.u01`, `.hdf`).

4.  **Data Management**:
    *   Employs Pandas DataFrames (accessible via `ras_object.plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`) to manage structured data about project components.
    *   Provides methods for accessing and updating project files, which subsequently refresh these DataFrames.

5.  **Execution Modes (`RasCmdr`)**:
    *   **Single Plan Execution**: Run individual plans with `RasCmdr.compute_plan()`.
    *   **Sequential Execution**: Run multiple plans in sequence in a test folder with `RasCmdr.compute_test_mode()`.
    *   **Parallel Execution**: Run multiple independent plans concurrently using worker folders with `RasCmdr.compute_parallel()`.

6.  **Example Projects (`RasExamples`)**:
    *   The `RasExamples` class offers functionality to download and manage official HEC-RAS example projects for testing and learning.

7.  **Utility Functions (`RasUtils`)**:
    *   Provides common utility functions for file operations (cloning, updating, removing), path handling, data conversion, error metrics calculation, and spatial queries.

8.  **AI-Accessibility**:
    *   Structured, consistent codebase with clear documentation (like this guide and docstrings) intended to facilitate easier learning and usage by AI models and developers. Code aims for predictability.

9.  **Boundary Conditions (`RasPrj.boundaries_df`)**:
    *   Represent input conditions (flow/stage hydrographs, normal depth, etc.).
    *   The `RasPrj` class extracts and manages boundary condition data parsed from unsteady flow files (`.u*`).

10. **Flexibility and Modularity**:
    *   Functions operating on projects accept an optional `ras_object` parameter, allowing use with the global `ras` or custom `RasPrj` instances.
    *   Clear separation of concerns: project management (`RasPrj`), execution (`RasCmdr`), file operations (`RasPlan`, `RasGeo`, `RasUnsteady`), HDF data retrieval (`Hdf*` classes), utilities (`RasUtils`), and examples (`RasExamples`).

11. **Error Handling and Logging**:
    *   Emphasis on robust error checking (e.g., `check_initialized`) and informative logging.
    *   Uses the `LoggingConfig` module for consistent setup (console and optional file output).
    *   `@log_call` decorator applied to most public functions for automatic call tracing at the DEBUG level.

12. **HDF Support (`Hdf*` classes)**:
    *   Comprehensive HDF file handling through specialized classes (`HdfBase`, `HdfMesh`, `HdfPlan`, `HdfResultsMesh`, `HdfResultsPlan`, `HdfResultsXsec`, `HdfStruc`, `HdfPipe`, `HdfPump`, `HdfFluvialPluvial`, `HdfInfiltration`, `HdfBndry`, `HdfXsec`, `HdfPlot`, `HdfResultsPlot`).
    *   Support for mesh, plan, cross-section geometry and results.
    *   Advanced data extraction, analysis, and plotting capabilities.

13. **Infrastructure Support (`HdfPipe`, `HdfPump`, `HdfStruc`)**:
    *   Tools for accessing geometry and results data related to pipe networks, pump stations, and other hydraulic structures from HDF files.

## Core Features

1.  **Project Management**: Initialize, load, and inspect HEC-RAS projects (`RasPrj`, `init_ras_project`).
2.  **Plan Execution**: Run single or multiple HEC-RAS plans sequentially or in parallel (`RasCmdr`).
3.  **File Operations**: Clone, modify, and manage HEC-RAS file types (plans, geometries, flows) programmatically (`RasPlan`, `RasGeo`, `RasUnsteady`, `RasUtils`).
4.  **Data Extraction**: Retrieve and process simulation results and geometry from HDF files (`Hdf*` classes).
5.  **Boundary Condition Management**: Extract and analyze boundary conditions from unsteady flow files (`RasPrj.get_boundary_conditions`).
6.  **Parallel Processing**: Optimize simulation time for multiple independent plans (`RasCmdr.compute_parallel`).
7.  **Example Project Handling**: Download and manage HEC-RAS example projects (`RasExamples`).
8.  **Utility Functions**: Perform common tasks like file manipulation, path resolution, error calculation, and spatial queries (`RasUtils`).
9.  **HDF File Handling**: Specialized classes for structured access to HEC-RAS HDF data.
10. **Infrastructure Analysis**: Tools for analyzing pipe networks, pump stations, and structures via HDF data (`HdfPipe`, `HdfPump`, `HdfStruc`).
11. **Visualization**: Basic plotting capabilities for HDF results (`HdfPlot`, `HdfResultsPlot`).

## Module Overview

1.  **RasPrj**: Manages HEC-RAS project state, including file discovery and dataframes for plans, geoms, flows, unsteady files, and boundary conditions.
2.  **RasCmdr**: Handles execution of HEC-RAS simulations via command line (single, sequential, parallel).
3.  **RasPlan**: Provides functions for plan file (`.p*`) operations (cloning, modifying parameters like geometry, flow files, cores, intervals, description).
4.  **RasGeo**: Manages geometry-related operations, primarily clearing preprocessor files (`.c*`).
5.  **RasUnsteady**: Handles unsteady flow file (`.u*`) operations (updating title, restart settings, extracting boundary tables).
6.  **RasUtils**: Offers general utility functions (file handling, path finding, data conversion, error metrics, spatial queries).
7.  **RasExamples**: Manages downloading and extracting official HEC-RAS example projects.
8.  **RasMap**: Parses HEC-RAS mapper configuration files (.rasmap) to extract paths to terrain, soil layer, land cover data, and other spatial datasets. Provides access to projection information and RASMapper settings.
9.  **HdfBase**: Provides base functionality for HDF file operations (time parsing, attribute access, projection).
10. **HdfBndry**: Handles boundary *geometry* features (BC lines, breaklines, etc.) from geometry HDF files.
11. **HdfMesh**: Manages mesh *geometry* data (cell polygons, points, faces, attributes) from HDF files.
12. **HdfPlan**: Handles plan-level information (simulation times, parameters) from plan HDF files.
13. **HdfResultsMesh**: Processes mesh *results* (WSE, velocity, depth timeseries, summaries) from plan HDF files.
14. **HdfResultsPlan**: Handles plan-level *results* (volume accounting, runtime stats) from plan HDF files.
15. **HdfResultsXsec**: Processes 1D cross-section *results* (WSE, flow, velocity timeseries) from plan HDF files.
16. **HdfStruc**: Manages structure *geometry* data (centerlines, profiles) from geometry HDF files.
17. **HdfUtils**: Provides utility functions specifically for HDF data handling (data type conversions, spatial queries).
18. **HdfXsec**: Handles 1D cross-section and river *geometry* (cut lines, centerlines, banks) from geometry HDF files.
19. **HdfPipe**: Handles pipe network geometry and results data from HDF files.
20. **HdfPump**: Manages pump station geometry and results data from HDF files.
21. **HdfFluvialPluvial**: Analyzes fluvial vs. pluvial boundaries based on results timing in plan HDF files.
22. **HdfInfiltration**: Handles infiltration layer data (parameters, maps) from geometry or `.tif.hdf` files.
23. **HdfPlot & HdfResultsPlot**: Basic visualization utilities for HDF data and results.
24. **Decorators**: Contains `@log_call` and `@standardize_input`.
25. **LoggingConfig**: Sets up and provides access to the library's logging system.

## Best Practices

### 1. RAS Object Usage (`RasPrj`)

*   **Single Project Scripts**:
    *   Use the global `ras` object for simplicity after initializing it.
    ```python
    from ras_commander import ras, init_ras_project

    # Initialize the global 'ras' object
    init_ras_project("/path/to/project", "6.5")
    # Use ras object for operations
    print(ras.plan_df)
    ```

*   **Multiple Projects**:
    *   Create separate `RasPrj` instances for each project using `init_ras_project` with the `ras_object` parameter set to a new instance or a unique identifier string. Always pass the specific `ras_object` to functions that need project context.
    ```python
    from ras_commander import RasPrj, init_ras_project, RasCmdr

    # Initialize two separate projects using new instances
    project1 = init_ras_project("/path/to/project1", "6.5", ras_object=RasPrj())
    project2 = init_ras_project("/path/to/project2", "6.5", ras_object=RasPrj())

    # Pass the specific object when calling functions
    RasCmdr.compute_plan("01", ras_object=project1)
    RasCmdr.compute_plan("02", ras_object=project2)
    ```

*   **Consistency**:
    *   Avoid mixing global `ras` usage and custom `RasPrj` instances within the same logical part of your script to prevent confusion. When using multiple projects, *always* pass the `ras_object` parameter.

### 2. Plan Specification

*   Use plan numbers as strings (e.g., `"01"`, `"02"`) for consistency with file naming conventions when calling functions like `compute_plan`.
    ```python
    RasCmdr.compute_plan("01")
    ```

*   Check available plans before specifying plan numbers using the `plan_df` attribute.
    ```python
    print(ras.plan_df) # Displays available plans and their details
    available_plans = ras.plan_df['plan_number'].tolist()
    print(f"Available plans: {available_plans}")
    ```

### 3. Geometry Preprocessor Files (`.c*`)

*   Clear geometry preprocessor files (`.c*`) using `RasGeo.clear_geompre_files()` *before* running a plan if the underlying geometry (`.g*`) file has been significantly modified. This forces HEC-RAS to recalculate hydraulic tables.
    ```python
    from ras_commander import RasPlan, RasGeo
    plan_path = RasPlan.get_plan_path("01") # Get path if needed
    RasGeo.clear_geompre_files(plan_path) # Clear for a specific plan
    # Or clear for all plans: RasGeo.clear_geompre_files()
    ```
*   Alternatively, use `clear_geompre=True` in `RasCmdr` functions for a clean computation environment, though calling `RasGeo.clear_geompre_files` directly offers more control.
    ```python
    RasCmdr.compute_plan("01", clear_geompre=True)
    ```

### 4. Parallel Execution (`RasCmdr.compute_parallel`)

*   Adjust `max_workers` (number of parallel HEC-RAS instances) based on available **physical CPU cores** and **RAM**. Each worker needs significant RAM (2-4GB+).
*   Set `num_cores` (cores *per worker*) to balance single-plan speed vs. overall throughput. Common values are 2-4 cores per worker.
    ```python
    import psutil
    physical_cores = psutil.cpu_count(logical=False)
    cores_per_worker = 2
    max_workers_cpu = max(1, physical_cores // cores_per_worker)
    # Consider RAM constraints as well - may need fewer workers than CPU allows
    max_workers = min(max_workers_cpu, 4) # Example: Limit to 4 workers regardless of CPU

    RasCmdr.compute_parallel(max_workers=max_workers, num_cores=cores_per_worker)
    ```

*   Use `dest_folder` to organize outputs from parallel runs and prevent conflicts with the original project or other runs. Use `overwrite_dest=True` cautiously.
    ```python
    results_dir = Path("./parallel_run_output")
    RasCmdr.compute_parallel(dest_folder=results_dir, overwrite_dest=True)
    ```

### 5. Error Handling and Logging

Proper error handling and logging are crucial for robust `ras_commander` scripts.

1.  **Logging Setup**:
    The library automatically sets up basic console logging at the INFO level. You can change the level or add file logging.
    ```python
    import logging
    from ras_commander import setup_logging, get_logger

    # Change console log level to DEBUG
    logging.getLogger('ras_commander').setLevel(logging.DEBUG)

    # Or, setup file logging as well
    # setup_logging(log_file='my_ras_script.log', log_level=logging.DEBUG)

    # Get a logger for your script
    script_logger = get_logger(__name__)
    script_logger.info("Script starting...")
    ```

2.  **Using the `@log_call` Decorator**:
    Most public library functions already use `@log_call`, automatically logging function entry/exit at the DEBUG level.

3.  **Custom Logging**:
    Use the logger obtained via `get_logger()` for more detailed script-specific logging.
    ```python
    logger = get_logger(__name__)
    def my_custom_ras_step():
        logger.info("Starting custom step...")
        try:
            # Perform operations using ras_commander functions
            result = RasCmdr.compute_plan("01")
            if not result:
                logger.warning("Plan 01 computation reported failure.")
            # Process result...
            logger.info("Custom step completed.")
        except Exception as e:
            logger.error(f"Custom step failed: {str(e)}", exc_info=True) # Log exception details
            # Handle error appropriately
    ```

4.  **Error Handling Best Practices**:
    *   Use `try...except` blocks around library calls that might fail (e.g., file operations, computations).
    *   Catch specific exceptions (`FileNotFoundError`, `ValueError`, `subprocess.CalledProcessError`) where possible.
    *   Check return values from functions like `compute_plan` which return `True`/`False`.
    *   Provide informative error messages in your logs or exceptions.
    ```python
    try:
        plan_path = RasPlan.get_plan_path("99") # Plan likely doesn't exist
        if plan_path is None:
             raise ValueError("Plan 99 does not exist in the project.")
        # ... more operations
    except ValueError as ve:
        script_logger.error(f"Configuration error: {ve}")
    except FileNotFoundError as fnf:
        script_logger.error(f"File access error: {fnf}")
    except Exception as ex:
        script_logger.critical(f"An unexpected error occurred: {ex}", exc_info=True)
    ```

### 6. File Path Handling

*   Use `pathlib.Path` objects for robust file and directory operations within your scripts. Library functions generally accept `str` or `Path`.
    ```python
    from pathlib import Path
    project_dir = Path("/path/to/my/project")
    results_dir = project_dir.parent / "results"
    # Pass Path objects to library functions
    init_ras_project(project_dir, "6.5")
    RasCmdr.compute_plan("01", dest_folder=results_dir)
    ```

### 7. Type Hinting

*   Apply type hints in your own functions that use `ras_commander` to improve code readability, maintainability, and IDE support.
    ```python
    from ras_commander import RasPrj, RasCmdr
    from typing import Dict, List

    def run_specific_plans(project: RasPrj, plans_to_run: List[str]) -> Dict[str, bool]:
        """Runs a list of plans for the given project."""
        results = RasCmdr.compute_parallel(
            plan_number=plans_to_run,
            ras_object=project,
            max_workers=2,
            num_cores=2
        )
        return results
    ```

## Usage Patterns

### Initializing a Project (Global `ras`)

```python
from ras_commander import init_ras_project, ras

# Initializes the global 'ras' object
init_ras_project("/path/to/project", "6.5")
print(f"Working with project: {ras.project_name}")
print(f"Available plans:\n{ras.plan_df}")
```

### Cloning a Plan

```python
from ras_commander import RasPlan, ras, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Clone plan "01", automatically assigns next number (e.g., "02")
new_plan_number = RasPlan.clone_plan("01", new_plan_shortid="Cloned Plan Test")
print(f"Created new plan: {new_plan_number}")

# The 'ras' object is automatically refreshed after cloning
print(f"Updated plan list:\n{ras.plan_df}")
```

### Executing Plans (`RasCmdr`)

*   **Single Plan Execution**:
    ```python
    from ras_commander import RasCmdr, init_ras_project

    init_ras_project("/path/to/project", "6.5")
    success = RasCmdr.compute_plan("01", num_cores=2)
    print(f"Plan '01' execution {'successful' if success else 'failed'}")
    ```

*   **Parallel Execution of Multiple Plans**:
    ```python
    from ras_commander import RasCmdr, init_ras_project
    from pathlib import Path

    init_ras_project("/path/to/project", "6.5")
    results_folder = Path("./parallel_results")

    results = RasCmdr.compute_parallel(
        plan_number=["01", "02", "03"],
        max_workers=3,
        num_cores=2, # 2 cores per worker
        dest_folder=results_folder,
        overwrite_dest=True,
        clear_geompre=False
    )

    print("Parallel execution results:")
    for plan, success in results.items():
        print(f"  Plan {plan}: {'Successful' if success else 'Failed'}")
    ```
*   **Sequential Execution in Test Folder**:
    ```python
    from ras_commander import RasCmdr, init_ras_project

    init_ras_project("/path/to/project", "6.5")

    results = RasCmdr.compute_test_mode(
        plan_number=["01", "02"],
        dest_folder_suffix="[SequentialTest]",
        num_cores=4,
        overwrite_dest=True
    )
    print("Sequential execution results:")
    for plan, success in results.items():
        print(f"  Plan {plan}: {'Successful' if success else 'Failed'}")
    ```

### Working with Multiple Projects

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr
from pathlib import Path

# Initialize two separate projects using new instances
project1 = init_ras_project("/path/to/project1", "6.5", ras_object=RasPrj())
project2 = init_ras_project("/path/to/project2", "6.5", ras_object=RasPrj())

results_folder1 = Path("./results_proj1")
results_folder2 = Path("./results_proj2")

# Perform operations on each project, passing the correct object
print(f"Running plan 01 for {project1.project_name}")
RasCmdr.compute_plan("01", ras_object=project1, dest_folder=results_folder1, overwrite_dest=True)

print(f"Running plan 02 for {project2.project_name}")
RasCmdr.compute_plan("02", ras_object=project2, dest_folder=results_folder2, overwrite_dest=True)

# Compare results (example: number of plans)
print(f"{project1.project_name} has {len(project1.plan_df)} plans.")
print(f"{project2.project_name} has {len(project2.plan_df)} plans.")

# Access HDF results (assuming computations were successful)
# Note: Need to re-initialize RasPrj for the output folders to access results easily,
# or construct HDF paths manually.
# Example: Re-initialize to read results from project 1's output
results_proj1 = init_ras_project(results_folder1, "6.5", ras_object=RasPrj())
hdf_df1 = results_proj1.get_hdf_entries()
print(f"HDF results found for Project 1 run:\n{hdf_df1}")

```

## Advanced Usage

### Working with HDF Files

`ras_commander` provides extensive support for reading HEC-RAS HDF files through specialized `Hdf*` classes. These methods typically accept a path identifier (string, Path, number) which is standardized by the `@standardize_input` decorator.

1.  **Exploring HDF Structure**:
    Use `HdfBase.get_dataset_info()` to print the internal structure of an HDF file.
    ```python
    from ras_commander import HdfBase, init_ras_project, RasPlan

    init_ras_project("/path/to/project", "6.5")
    # Assume plan 01 has been computed and has results
    hdf_results_path = RasPlan.get_results_path("01")
    if hdf_results_path:
        print(f"Exploring HDF file: {hdf_results_path}")
        HdfBase.get_dataset_info(hdf_results_path, group_path="/Results/Unsteady/Output/Output Blocks/Base Output/Summary Output")
    else:
        print("No HDF results found for plan 01.")
    ```

2.  **Extracting Mesh Results (`HdfResultsMesh`)**:
    Use `HdfResultsMesh` methods to get timeseries or summary results for 2D areas.
    ```python
    from ras_commander import HdfResultsMesh, init_ras_project, RasPlan
    import xarray as xr

    init_ras_project("/path/to/project", "6.5")
    hdf_results_path = RasPlan.get_results_path("01") # Path to .p01.hdf

    if hdf_results_path:
        try:
            # Get Water Surface time series for the first mesh area
            mesh_names = HdfMesh.get_mesh_area_names(hdf_results_path)
            if mesh_names:
                first_mesh = mesh_names[0]
                ws_timeseries: xr.DataArray = HdfResultsMesh.get_mesh_timeseries(
                    hdf_results_path, first_mesh, "Water Surface"
                )
                print(f"Water Surface timeseries for mesh '{first_mesh}':\n{ws_timeseries}")

                # Get Max Water Surface summary for all meshes
                max_ws_summary = HdfResultsMesh.get_mesh_max_ws(hdf_results_path)
                print(f"\nMax Water Surface Summary:\n{max_ws_summary}")
            else:
                print("No mesh areas found in HDF.")
        except Exception as e:
            print(f"Error reading mesh results: {e}")
    else:
        print("No HDF results found for plan 01.")
    ```

3.  **Working with Plan Results (`HdfResultsPlan`)**:
    Use `HdfResultsPlan` for plan-level results like runtime or volume accounting.
    ```python
    from ras_commander import HdfResultsPlan, init_ras_project, RasPlan

    init_ras_project("/path/to/project", "6.5")
    hdf_results_path = RasPlan.get_results_path("01")

    if hdf_results_path:
        runtime_data = HdfResultsPlan.get_runtime_data(hdf_results_path)
        print(f"Runtime Data:\n{runtime_data}")

        volume_accounting = HdfResultsPlan.get_volume_accounting(hdf_results_path)
        print(f"\nVolume Accounting:\n{volume_accounting}")
    else:
        print("No HDF results found for plan 01.")
    ```

4.  **Cross-Section Results (`HdfResultsXsec`)**:
    Extract 1D cross-section time series results using `HdfResultsXsec`.
    ```python
    from ras_commander import HdfResultsXsec, init_ras_project, RasPlan
    import xarray as xr

    init_ras_project("/path/to/project", "6.5")
    hdf_results_path = RasPlan.get_results_path("01")

    if hdf_results_path:
        xsec_results: xr.Dataset = HdfResultsXsec.get_xsec_timeseries(hdf_results_path)
        print(f"Cross Section Results Dataset:\n{xsec_results}")
        # Example: Access Water Surface for the first cross section
        # first_xs_name = xsec_results['cross_section'][0].item()
        # ws_first_xs = xsec_results['Water_Surface'].sel(cross_section=first_xs_name)
        # print(f"\nWater Surface for first cross section ({first_xs_name}):\n{ws_first_xs}")
    else:
        print("No HDF results found for plan 01.")
    ```

### Working with Pipe Networks and Pump Stations

`ras_commander` provides specialized classes (`HdfPipe`, `HdfPump`) for handling pipe network and pump station data from HEC-RAS HDF files.

1.  **Pipe Network Operations (`HdfPipe`)**:
    Extract geometry and results for pipe networks.
    ```python
    from ras_commander import HdfPipe, init_ras_project, RasPlan, HdfMesh
    from pathlib import Path

    init_ras_project("/path/to/project_with_pipes", "6.5")
    # Assume plan 01 computed results for a project with pipes
    hdf_plan_path = RasPlan.get_results_path("01")
    # Geometry HDF is needed for geometric data
    hdf_geom_path = HdfMesh.get_mesh_cell_polygons(hdf_plan_path) # Infer geom HDF from plan

    if hdf_plan_path and hdf_geom_path:
        # Extract pipe conduit geometry
        pipe_conduits_gdf = HdfPipe.get_pipe_conduits(hdf_geom_path)
        print(f"Pipe Conduits:\n{pipe_conduits_gdf}")

        # Extract pipe node geometry
        pipe_nodes_gdf = HdfPipe.get_pipe_nodes(hdf_geom_path)
        print(f"\nPipe Nodes:\n{pipe_nodes_gdf}")

        # Get pipe network timeseries results (e.g., Node Depth)
        node_depth_ts = HdfPipe.get_pipe_network_timeseries(hdf_plan_path, "Nodes/Depth")
        print(f"\nNode Depth Timeseries:\n{node_depth_ts}")

        # Get pipe network summary results
        summary_df = HdfPipe.get_pipe_network_summary(hdf_plan_path)
        print(f"\nPipe Network Summary:\n{summary_df}")

        # Get profile for a specific conduit (e.g., conduit index 0)
        # profile_df = HdfPipe.get_pipe_profile(hdf_geom_path, conduit_id=0)
        # print(f"\nProfile for Conduit 0:\n{profile_df}")
    else:
        print("Could not find HDF plan or geometry files.")
    ```

2.  **Pump Station Operations (`HdfPump`)**:
    Work with pump station geometry and results data.
    ```python
    from ras_commander import HdfPump, init_ras_project, RasPlan, HdfMesh

    init_ras_project("/path/to/project_with_pumps", "6.5")
    # Assume plan 01 computed results
    hdf_plan_path = RasPlan.get_results_path("01")
    hdf_geom_path = HdfMesh.get_mesh_cell_polygons(hdf_plan_path) # Infer geom HDF

    if hdf_plan_path and hdf_geom_path:
        # Extract pump station locations
        pump_stations_gdf = HdfPump.get_pump_stations(hdf_geom_path)
        print(f"Pump Stations:\n{pump_stations_gdf}")

        # Get pump group details (like efficiency curves)
        pump_groups_df = HdfPump.get_pump_groups(hdf_geom_path)
        print(f"\nPump Groups:\n{pump_groups_df}")

        # Get pump station timeseries results (replace "Pump Station 1" with actual name)
        try:
            pump_ts = HdfPump.get_pump_station_timeseries(hdf_plan_path, "Pump Station 1")
            print(f"\nTimeseries for Pump Station 1:\n{pump_ts}")
        except ValueError as e:
            print(f"\nError getting timeseries: {e}")


        # Get pump station summary results
        summary_df = HdfPump.get_pump_station_summary(hdf_plan_path)
        print(f"\nPump Station Summary:\n{summary_df}")

        # Get pump operation timeseries (replace "Pump Station 1" with actual name)
        try:
            operation_df = HdfPump.get_pump_operation_timeseries(hdf_plan_path, "Pump Station 1")
            print(f"\nOperation Timeseries for Pump Station 1:\n{operation_df}")
        except ValueError as e:
             print(f"\nError getting operation timeseries: {e}")
    else:
        print("Could not find HDF plan or geometry files.")
    ```

### Working with Multiple HEC-RAS Projects

Manage multiple projects by creating separate `RasPrj` instances.

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr, RasPlan
import pandas as pd

# Initialize multiple project instances
# Use ras_object=RasPrj() to ensure distinct instances
project1 = init_ras_project("/path/to/project1", "6.5", ras_object=RasPrj())
project2 = init_ras_project("/path/to/project2", "6.6", ras_object=RasPrj())

# This allows RasPrj Instances to be accessed independently
print(f"Project 1: {project1.project_name} ({len(project1.plan_df)} plans)")
print(f"Project 2: {project2.project_name} ({len(project2.plan_df)} plans)")

# --- Best Practices ---
# 1. Clear Naming: Use descriptive variable names (e.g., bald_eagle_proj, muncie_proj).
# 2. Pass Objects: Always pass the correct ras_object to functions.
# 3. Avoid Global 'ras': Don't rely on the global 'ras' when managing multiple projects.
# 4. Separate Outputs: Use distinct dest_folder paths for computations.
# 5. Resource Awareness: Monitor CPU/RAM when running computations for multiple projects, especially in parallel.

# --- Example Workflow ---
# Function to compare basic project structures
def compare_project_structures(ras_obj1: RasPrj, name1: str, ras_obj2: RasPrj, name2: str) -> pd.DataFrame:
    """Compare the structures of two HEC-RAS projects."""
    comparison = {
        'Project Name': [ras_obj1.project_name, ras_obj2.project_name],
        'Plan Count': [len(ras_obj1.plan_df), len(ras_obj2.plan_df)],
        'Geometry Count': [len(ras_obj1.geom_df), len(ras_obj2.geom_df)],
        'Flow Count': [len(ras_obj1.flow_df), len(ras_obj2.flow_df)],
        'Unsteady Count': [len(ras_obj1.unsteady_df), len(ras_obj2.unsteady_df)]
    }
    return pd.DataFrame(comparison, index=[name1, name2])

# Perform operations on each project
RasCmdr.compute_plan("01", ras_object=project1, dest_folder="./proj1_run")
RasCmdr.compute_plan("01", ras_object=project2, dest_folder="./proj2_run")

# Compare structures
comparison_df = compare_project_structures(project1, "Project 1", project2, "Project 2")
print("\nProject Structure Comparison:")
print(comparison_df)

# --- Application Examples ---
# 1. Model Comparison: Run same scenarios on different river models.
# 2. Basin-wide Analysis: Process connected or related models.
# 3. Parameter Sweep: Test parameter variations across multiple baseline models.
# 4. Batch Processing: Automate runs for a large inventory of models.
```

### Plan Execution Modes (`RasCmdr`)

`ras_commander` offers three modes for running HEC-RAS plans:

#### Single Plan Execution (`compute_plan`)

Runs one plan, optionally in a separate destination folder. Best for targeted runs or when immediate results are needed.

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

success = RasCmdr.compute_plan(
    plan_number="01",              # Plan to execute
    dest_folder="/path/to/single_run_results", # Optional: Where to run
    num_cores=4,                   # Optional: Cores for this run
    clear_geompre=True,            # Optional: Force geometry preprocess
    overwrite_dest=True            # Optional: Overwrite dest if exists
)
print(f"Plan 01 execution status: {success}")
```

#### Sequential Execution (`compute_test_mode`)

Runs multiple plans one after another in a dedicated test folder (copy of the project). Best for plans with dependencies or for controlled resource usage.

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

results = RasCmdr.compute_test_mode(
    plan_number=["01", "02", "03"], # Plans to run in order
    dest_folder_suffix="[SequentialRun]", # Suffix for test folder name
    clear_geompre=True,            # Optional: Clear before each plan
    num_cores=4,                   # Optional: Cores for each plan
    overwrite_dest=True            # Optional: Overwrite test folder
)
print("Sequential results:", results)
```

#### Parallel Execution (`compute_parallel`)

Runs multiple independent plans concurrently using temporary worker folders, consolidating results afterward. Best for maximizing speed on multi-core systems with independent plans.

```python
from ras_commander import RasCmdr, init_ras_project

init_ras_project("/path/to/project", "6.5")

results = RasCmdr.compute_parallel(
    plan_number=["01", "02", "03"], # Plans to run in parallel
    max_workers=3,                 # Max concurrent HEC-RAS instances
    num_cores=2,                   # Cores assigned to each worker
    dest_folder="/path/to/parallel_results", # Final results location
    clear_geompre=False,           # Optional: Clear in worker folders
    overwrite_dest=True            # Optional: Overwrite final results folder
)
print("Parallel results:", results)
```

#### Choosing the Right Mode

*   **Dependency:** Sequential (`compute_test_mode`) for dependent plans; Parallel (`compute_parallel`) for independent plans.
*   **Resources:** Single (`compute_plan`) or Sequential for limited hardware; Parallel for multi-core systems.
*   **Speed:** Parallel is usually fastest overall for multiple plans; Single is fastest for one specific plan.
*   **Debugging:** Single or Sequential are often easier to debug.
*   **Isolation:** `compute_test_mode` and `compute_parallel` (with `dest_folder`) provide isolated run environments.

#### Return Values

*   `compute_plan()`: Returns `bool` (success/failure).
*   `compute_test_mode()`: Returns `Dict[str, bool]` mapping plan number to success status.
*   `compute_parallel()`: Returns `Dict[str, bool]` mapping plan number to success status.

```python
# Example checking results from parallel run
results = RasCmdr.compute_parallel(plan_number=["01", "02", "03"])
for plan_num, success in results.items():
    print(f"Plan {plan_num}: {'Success' if success else 'Failed'}")
    if not success:
        print(f"  Check logs related to plan {plan_num} execution.")
```

### Plan Parameter Operations (`RasPlan`)

Modify plan file (`.p*`) settings programmatically without the HEC-RAS GUI.

#### Retrieving Plan Values (`get_plan_value`)

Read specific parameters directly from a plan file.

```python
from ras_commander import RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get the computation interval for plan 01
interval = RasPlan.get_plan_value("01", "Computation Interval")
print(f"Plan 01 Computation Interval: {interval}")

# Get the number of cores assigned (0 means 'all available')
cores = RasPlan.get_plan_value("01", "UNET D2 Cores") # For 2D cores
print(f"Plan 01 UNET D2 Cores setting: {cores}")

# Get the associated geometry file number
geom_file_str = RasPlan.get_plan_value("01", "Geom File") # Returns e.g., "g01"
geom_num = geom_file_str[1:] if geom_file_str else "N/A"
print(f"Plan 01 uses Geometry: {geom_num}")
```

Common keys include: `Computation Interval`, `Short Identifier`, `Simulation Date`, `UNET D1 Cores`, `UNET D2 Cores`, `Plan Title`, `Geom File`, `Flow File` (or `Unsteady File`), `Friction Slope Method`, `Run HTab`, `UNET Use Existing IB Tables`.

#### Updating Run Flags (`update_run_flags`)

Control which simulation components HEC-RAS executes.

```python
from ras_commander import RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Example: Enable geometry preprocessing and unsteady sim, disable others
RasPlan.update_run_flags(
    "01",
    geometry_preprocessor=True,    # Run HTab = 1
    unsteady_flow_simulation=True, # Run UNet = 1
    post_processor=False,          # Run PostProcess = 0
    floodplain_mapping=False       # Run RASMapper = -1 (Note: False maps to -1 for RASMapper)
)
print("Updated run flags for plan 01.")
```

#### Setting Time Intervals (`update_plan_intervals`)

Modify simulation time steps and output frequencies.

```python
from ras_commander import RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Set computation to 10 sec, output to 1 min, mapping to 15 min
RasPlan.update_plan_intervals(
    "01",
    computation_interval="10SEC",
    output_interval="1MIN",
    mapping_interval="15MIN"
    # instantaneous_interval="1HOUR" # Also available
)
print("Updated time intervals for plan 01.")
```

Valid interval values (must match HEC-RAS exactly): `1SEC`..`30SEC`, `1MIN`..`30MIN`, `1HOUR`..`12HOUR`, `1DAY`.

#### Working with Simulation Dates (`update_simulation_date`)

Change the simulation window (start and end times).

```python
from ras_commander import RasPlan, init_ras_project
from datetime import datetime

init_ras_project("/path/to/project", "6.5")

start_dt = datetime(2024, 1, 1, 12, 0) # Jan 1, 2024, 12:00 PM
end_dt = datetime(2024, 1, 5, 0, 0)   # Jan 5, 2024, 00:00 AM

RasPlan.update_simulation_date("01", start_date=start_dt, end_date=end_dt)
print(f"Updated simulation dates for plan 01 to {start_dt} - {end_dt}.")
```

Ensure the simulation window covers your boundary condition data and includes appropriate warm-up/cool-down periods.

#### Managing Plan Descriptions (`read_plan_description`, `update_plan_description`)

Read or modify the multi-line description block in the plan file.

```python
from ras_commander import RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Read current description
current_desc = RasPlan.read_plan_description("01")
print(f"Current description for plan 01:\n{current_desc}\n-----------------")

# Update the description
new_desc = f"""
Run Date: {datetime.now().strftime('%Y-%m-%d')}
Scenario: Test with updated Manning's values.
Source Geometry: g02
Source Flow: u03
Notes: Increased roughness in floodplain by 15%.
"""
RasPlan.update_plan_description("01", new_desc)
print("Updated description for plan 01.")
```

#### Core Allocation (`set_num_cores`)

Configure the number of processor cores a plan should use (sets `UNET D1 Cores`, `UNET D2 Cores`, `PS Cores` simultaneously).

```python
from ras_commander import RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Set plan 01 to use 4 cores
RasPlan.set_num_cores("01", 4)
print("Set plan 01 to use 4 cores.")

# Set plan 02 to use all available cores (value 0)
RasPlan.set_num_cores("02", 0)
print("Set plan 02 to use all available cores.")
```

Consider system resources. 2-8 cores are typically effective. Using too many can decrease performance.

### Performance Optimization

Strategies to improve execution speed and resource usage.

1.  **Parallel Execution (`RasCmdr.compute_parallel`)**:
    *   Run independent plans simultaneously.
    *   Balance `max_workers` and `num_cores` based on CPU/RAM.
    ```python
    # Example: 8 physical cores, run 4 plans in parallel, 2 cores each
    RasCmdr.compute_parallel(plan_number=["01", "02", "03", "04"], max_workers=4, num_cores=2)
    ```

2.  **Optimized Geometry Preprocessing**:
    *   Avoid redundant calculations if multiple plans use the same geometry. Preprocess once, then run simulations.
    ```python
    from ras_commander import RasPlan, RasCmdr, init_ras_project

    init_ras_project("/path/to/project", "6.5")
    plan_to_preprocess = "01" # Plan using the geometry to preprocess
    geom_file_to_use = RasPlan.get_plan_value(plan_to_preprocess, "Geom File") # e.g., "g01"

    # Step 1: Force geometry preprocessing for the target geometry via one plan
    print(f"Preprocessing geometry {geom_file_to_use} using plan {plan_to_preprocess}...")
    RasPlan.update_run_flags(
        plan_to_preprocess,
        geometry_preprocessor=True,    # Run HTab = 1
        unsteady_flow_simulation=False # Run UNet = 0 (or -1 if available)
        # Set other flags as needed (e.g., post_processor=False)
    )
    RasCmdr.compute_plan(plan_to_preprocess) # This run primarily generates .c* files

    # Step 2: Run actual simulations using the preprocessed geometry
    plans_using_geom = ["01", "03", "05"] # Plans that use the same geometry
    for plan_num in plans_using_geom:
        print(f"Running simulation for plan {plan_num} using preprocessed geometry...")
        RasPlan.update_run_flags(
            plan_num,
            geometry_preprocessor=False,   # Run HTab = 0 (use existing tables)
            unsteady_flow_simulation=True  # Run UNet = 1
            # Set other flags as needed
        )
        # Run the plan (can be single, parallel, or test mode)
        RasCmdr.compute_plan(plan_num)
    ```

3.  **Memory Management (Large Datasets)**:
    *   When reading large HDF results (especially 2D time series), process data in chunks if memory becomes an issue. `xarray` (returned by `get_mesh_timeseries`) supports lazy loading and chunking.
    ```python
    import xarray as xr
    # ws_timeseries = HdfResultsMesh.get_mesh_timeseries(...)
    # If ws_timeseries is too large:
    # ws_chunked = ws_timeseries.chunk({'time': 100, 'cell_id': 10000}) # Example chunking
    # result = ws_chunked.mean(dim='cell_id').compute() # Perform computation
    ```

4.  **I/O Optimization**:
    *   Minimize repeated file opening/closing when reading multiple datasets from the *same* HDF file. Open it once with `h5py.File`.
    ```python
    import h5py
    from ras_commander import HdfBase, HdfResultsMesh # ... and other Hdf classes

    hdf_path = "/path/to/results.p01.hdf"
    try:
        with h5py.File(hdf_path, 'r') as hdf_file:
            # Perform multiple reads within this block
            start_time = HdfBase.get_simulation_start_time(hdf_file)
            timestamps = HdfBase.get_unsteady_timestamps(hdf_file)
            # summary_ws = HdfResultsMesh.get_mesh_summary_output(hdf_file, "Maximum Water Surface") # Requires adapting func to take h5py.File
            print(f"Start time: {start_time}, Found {len(timestamps)} timestamps.")
            # ... more operations using the open hdf_file
    except Exception as e:
        print(f"Error accessing HDF file {hdf_path}: {e}")
    ```
    *(Note: Most `Hdf*` methods currently use `@standardize_input` which handles file opening/closing internally. Adapting them to accept open `h5py.File` objects might be needed for extreme I/O optimization).*

5.  **Profiling**:
    *   Use Python's `cProfile` to identify bottlenecks in your scripts.
    ```python
    import cProfile
    from ras_commander import RasCmdr, init_ras_project

    init_ras_project("/path/to/project", "6.5")
    # Profile a specific function call
    # cProfile.run('RasCmdr.compute_plan("01", num_cores=2)')
    ```

### Working with Boundary Conditions (`RasPrj.boundaries_df`)

Access and analyze boundary conditions extracted from unsteady flow files.

1.  **Accessing Boundary Conditions**:
    The `boundaries_df` attribute holds the parsed data.
    ```python
    from ras_commander import init_ras_project, ras

    init_ras_project("/path/to/project", "6.5")
    boundary_conditions = ras.boundaries_df
    if boundary_conditions is not None and not boundary_conditions.empty:
        print(f"Found {len(boundary_conditions)} boundary conditions:")
        print(boundary_conditions.head())
    else:
        print("No boundary conditions found or project not initialized correctly.")
    ```

2.  **Filtering Boundary Conditions**:
    Use standard pandas filtering.
    ```python
    if boundary_conditions is not None and not boundary_conditions.empty:
        # Get all flow hydrographs
        flow_hydrographs = boundary_conditions[boundary_conditions['bc_type'] == 'Flow Hydrograph']
        print(f"\nFlow Hydrographs:\n{flow_hydrographs[['river_reach_name', 'river_station', 'hydrograph_num_values']]}")

        # Get boundary conditions for a specific river/reach
        # main_river_boundaries = boundary_conditions[boundary_conditions['river_reach_name'] == 'Main River']
    ```

3.  **Analyzing Boundary Condition Data**:
    Access columns for details. Hydrograph values are often stored as strings or lists.
    ```python
    if 'flow_hydrographs' in locals() and not flow_hydrographs.empty:
        for index, bc in flow_hydrographs.iterrows():
            print(f"\n--- BC {index} ---")
            print(f"  Location: {bc['river_reach_name']} @ RS {bc['river_station']}")
            print(f"  Num Values: {bc['hydrograph_num_values']}")
            # Note: 'hydrograph_values' might be a list of strings or numbers depending on parsing
            # print(f"  Values (first 5): {bc.get('hydrograph_values', [])[:5]}")
    ```

4.  **Modifying Boundary Conditions**:
    *Direct modification via the library is generally NOT supported.* The `boundaries_df` is read-only representation. Modifying boundary conditions typically requires:
    *   Using `RasUnsteady` functions (`extract_tables`, `write_table_to_file`) to modify numeric tables.
    *   Manually editing the `.u*` files for structural changes.
    *   Creating custom functions to parse/rewrite specific parts of the `.u*` file.

5.  **Visualizing Boundary Conditions**:
    Use pandas and matplotlib with the extracted table data.
    ```python
    from ras_commander import RasUnsteady # Needed for table extraction
    import matplotlib.pyplot as plt

    if 'flow_hydrographs' in locals() and not flow_hydrographs.empty:
        # Example for the first flow hydrograph found
        first_flow_bc = flow_hydrographs.iloc[0]
        unsteady_file_path = first_flow_bc['full_path'] # Get path from merged df
        
        # Extract tables for this unsteady file
        tables = RasUnsteady.extract_tables(unsteady_file_path)
        
        # Find the correct table (assuming one flow hydrograph per location)
        flow_table_name = 'Flow Hydrograph='
        if flow_table_name in tables:
            flow_data = tables[flow_table_name]
            
            # Need time interval to create time axis (get from boundary_df or parse file)
            interval_str = first_flow_bc.get('Interval', '1HOUR') # Example: Get interval
            # Convert interval_str to timedelta (requires parsing logic, simplified here)
            # time_delta = pd.Timedelta(interval_str) # Simplistic example
            # time_axis = [i * time_delta for i in range(len(flow_data))]

            plt.figure(figsize=(10, 5))
            plt.plot(flow_data['Value']) # Plot against index if time axis is complex
            plt.title(f"Flow Hydrograph: {first_flow_bc['river_reach_name']} RS {first_flow_bc['river_station']}")
            plt.xlabel("Time Step Index")
            plt.ylabel("Flow")
            plt.grid(True)
            plt.show()
        else:
            print(f"Could not find table '{flow_table_name}' in {unsteady_file_path}")

    ```

### Advanced Data Processing with RasUtils

`RasUtils` provides tools beyond basic file operations.

1.  **Data Conversion (`convert_to_dataframe`)**:
    Load data from various file types into pandas DataFrames.
    ```python
    from ras_commander import RasUtils
    from pathlib import Path

    try:
        csv_df = RasUtils.convert_to_dataframe(Path("results.csv"))
        excel_df = RasUtils.convert_to_dataframe(Path("data.xlsx"), sheet_name="Sheet1")
        print("DataFrames loaded successfully.")
    except FileNotFoundError:
        print("Input file not found.")
    except NotImplementedError as e:
        print(f"Error: {e}")
    ```

2.  **Statistical Analysis (Error Metrics)**:
    Calculate common metrics for model calibration/validation.
    ```python
    from ras_commander import RasUtils
    import numpy as np

    observed = np.array([100, 120, 140, 160, 180])
    predicted = np.array([105, 125, 135, 165, 175])

    rmse = RasUtils.calculate_rmse(observed, predicted, normalized=False)
    percent_bias = RasUtils.calculate_percent_bias(observed, predicted, as_percentage=True)
    metrics = RasUtils.calculate_error_metrics(observed, predicted)

    print(f"RMSE: {rmse:.2f}")
    print(f"Percent Bias: {percent_bias:.2f}%")
    print(f"All Metrics: {metrics}")
    ```

3.  **Spatial Operations (KDTree)**:
    Perform nearest neighbor searches efficiently.
    ```python
    from ras_commander import RasUtils
    import numpy as np

    # Find nearest point in 'points' for each point in 'query_points' within 5 units
    points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
    query_points = np.array([[0.5, 0.5], [5, 5], [9, 9]])
    nearest_indices = RasUtils.perform_kdtree_query(points, query_points, max_distance=5.0)
    # Returns indices from 'points': e.g., [1, -1, 3] (-1 if no point within max_distance)
    print(f"Nearest point indices: {nearest_indices}")

    # Find nearest neighbor within the 'points' dataset itself (excluding self)
    # neighbors_indices = RasUtils.find_nearest_neighbors(points, max_distance=3.0)
    # print(f"Nearest neighbor indices within dataset: {neighbors_indices}")
    ```

4.  **Data Consolidation (`consolidate_dataframe`)**:
    Group and aggregate DataFrame rows, often merging values into lists.
    ```python
    from ras_commander import RasUtils
    import pandas as pd

    df = pd.DataFrame({'Group': ['A', 'A', 'B', 'B', 'A'],
                       'Value': [10, 20, 30, 40, 50],
                       'Type': ['X', 'Y', 'X', 'Y', 'X']})

    # Consolidate by 'Group', merging 'Value' and 'Type' into lists
    consolidated = RasUtils.consolidate_dataframe(df, group_by='Group', aggregation_method='list')
    print("Consolidated DataFrame:")
    print(consolidated)
    # Output might look like:
    #              Value       Type
    # Group
    # A      [10, 20, 50]  [X, Y, X]
    # B          [30, 40]     [X, Y]
    ```

### Optimizing Parallel Execution (`RasCmdr.compute_parallel`)

Fine-tune parallel runs based on goals and resources.

#### Strategy 1: Efficiency (Maximize Throughput)

Use fewer cores per worker to run more workers simultaneously (if RAM allows). Good for many small/medium independent plans.

```python
from ras_commander import RasCmdr
import psutil

physical_cores = psutil.cpu_count(logical=False)
cores_per_worker = 2 # Minimal cores per HEC-RAS instance
max_workers = max(1, physical_cores // cores_per_worker)
# Check available RAM and potentially reduce max_workers if needed

print(f"Efficiency Mode: Running up to {max_workers} workers with {cores_per_worker} cores each.")
RasCmdr.compute_parallel(
    plan_number=["01", "02", "03", "04", "05", "06"], # Example plans
    max_workers=max_workers,
    num_cores=cores_per_worker
)
```

#### Strategy 2: Performance (Minimize Single Plan Runtime)

Assign more cores per worker, reducing the number of concurrent workers. Good if individual plan speed is critical or for few, large plans.

```python
from ras_commander import RasCmdr
import psutil

physical_cores = psutil.cpu_count(logical=False)
cores_per_worker = max(4, min(8, physical_cores // 2)) # Use 4-8 cores, but not more than half the system
max_workers = max(1, physical_cores // cores_per_worker)

print(f"Performance Mode: Running up to {max_workers} workers with {cores_per_worker} cores each.")
RasCmdr.compute_parallel(
    plan_number=["LargePlan01", "LargePlan02"], # Example large plans
    max_workers=max_workers,
    num_cores=cores_per_worker
)
```

#### Strategy 3: Background Run (Balanced)

Limit total core usage to leave resources free for other tasks.

```python
from ras_commander import RasCmdr
import psutil

physical_cores = psutil.cpu_count(logical=False)
max_total_cores = int(physical_cores * 0.75) # Use up to 75% of physical cores
cores_per_worker = 2
max_workers = max(1, max_total_cores // cores_per_worker)

print(f"Background Mode: Running up to {max_workers} workers, using max {max_total_cores} total cores.")
RasCmdr.compute_parallel(
    max_workers=max_workers,
    num_cores=cores_per_worker
)
```

#### Optimizing Geometry Preprocessing in Parallel Runs

If many plans share the same geometry, preprocess it *once* before the parallel run, then run the parallel simulations without geometry preprocessing.

1.  **Preprocess Geometry (Single Run)**:
    ```python
    from ras_commander import RasPlan, RasCmdr, init_ras_project

    init_ras_project("/path/to/project", "6.5")
    plan_for_preprocessing = "01" # Choose one plan that uses the target geometry

    print("Preprocessing geometry...")
    RasPlan.update_run_flags(
        plan_for_preprocessing,
        geometry_preprocessor=True,
        unsteady_flow_simulation=False # Don't run the full simulation yet
    )
    RasCmdr.compute_plan(plan_for_preprocessing)
    print("Geometry preprocessing complete.")
    ```

2.  **Run Parallel Simulations (Without Preprocessing)**:
    ```python
    plans_to_run = ["01", "03", "05"] # Plans sharing the preprocessed geometry

    print("Running parallel simulations without geometry preprocessing...")
    RasCmdr.compute_parallel(
        plan_number=plans_to_run,
        max_workers=3,
        num_cores=2,
        clear_geompre=False # Important: Don't clear the files we just created
        # Ensure update_run_flags is set correctly *inside* compute_parallel
        # if needed, or ensure plans are pre-configured correctly.
        # Best practice: Ensure plans are saved with Run HTab = 0 before parallel run.
    )
    print("Parallel simulations complete.")
    ```
    *Self-Correction:* `compute_parallel` doesn't directly take `update_run_flags`. The flags should be set *before* calling `compute_parallel`. It might be better to modify the *template* plans to have `Run HTab=0` before the parallel run, or modify them in the worker folders (more complex). The easiest is often to ensure the `.p*` files are saved correctly beforehand.


### Working with RASMapper Data

RAS Commander now provides access to RASMapper configuration data through the `rasmap_df` attribute of the `RasPrj` class, which is initialized automatically when a project is loaded. This enables integration with spatial datasets referenced in RASMapper.

When you run init_ras_project, rasmap_df is populated with data from the project's .rasmap file

The `rasmap_df` contains paths to:
- Terrain data (DEM)
- Soil layers (Hydrologic Soil Groups)  
- Land cover datasets
- Infiltration data
- Profile lines and other features
- Project settings and current visualization state

This allows programmatic access to the same spatial data being used in RASMapper visualizations.

### Modifying Manning's n Values

RAS Commander provides functions for reading and writing Manning's n values in geometry files through the `RasGeo` class. This allows automation of roughness coefficient adjustments for calibration and sensitivity analysis.

```python
from ras_commander import RasGeo, RasPlan, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get the geometry file path
geom_path = RasPlan.get_geom_path("01")

# Read base Manning's n values
mannings_df = RasGeo.get_mannings_baseoverrides(geom_path)
print(f"Current Manning's n values:\n{mannings_df}")

# Read region-specific Manning's n overrides
region_df = RasGeo.get_mannings_regionoverrides(geom_path)
print(f"Regional Manning's n overrides:\n{region_df}")

# Modify Manning's n values (example: increase all values by 20%)
mannings_df['Base Manning\'s n Value'] *= 1.2
RasGeo.set_mannings_baseoverrides(geom_path, mannings_df)
print("Updated Manning's n values in geometry file")

# Clear preprocessor files to ensure geometry changes take effect
RasGeo.clear_geompre_files()
```

Common applications include:
- Automated calibration workflows
- Sensitivity analysis by batch-modifying roughness values
- Scenario analysis using different roughness sets
- Seasonal roughness adjustments

### Advanced Infiltration Data Handling

The enhanced `HdfInfiltration` class provides comprehensive tools for working with soil and infiltration data in HEC-RAS projects.

```python
from ras_commander import HdfInfiltration, init_ras_project

init_ras_project("/path/to/project", "6.5")

# Get the infiltration layer HDF path from the RASMapper configuration
infiltration_path = ras.rasmap_df['infiltration_hdf_path'][0][0]

# Read current infiltration parameters
infil_df = HdfInfiltration.get_infiltration_baseoverrides(infiltration_path)
print(f"Current infiltration parameters:\n{infil_df}")

# Scale infiltration parameters
scale_factors = {
    'Maximum Deficit': 1.2,  # Increase by 20%
    'Initial Deficit': 1.0,  # No change
    'Potential Percolation Rate': 0.8  # Decrease by 20%
}
updated_df = HdfInfiltration.scale_infiltration_data(
    infiltration_path, infil_df, scale_factors
)
print("Updated infiltration parameters")

# Get infiltration map (raster value to mukey mapping)
infil_map = HdfInfiltration.get_infiltration_map()

# Calculate weighted parameters based on soil coverage
significant_soils = HdfInfiltration.get_significant_mukeys(soil_stats, threshold=1.0)
weighted_params = HdfInfiltration.calculate_weighted_parameters(
    significant_soils, infiltration_params
)
print(f"Weighted infiltration parameters:\n{weighted_params}")
```

Key capabilities include:
- Retrieving and modifying infiltration parameters
- Scaling parameter values for sensitivity analysis
- Calculating soil statistics from raster data
- Computing area-weighted infiltration parameters
- Extracting and analyzing soil map unit data


## Approaching Your End User Needs with Ras Commander

### Understanding Data Sources and Strategies

RAS Commander interacts primarily with HEC-RAS project definition files (ASCII text: `.prj`, `.p*`, `.g*`, `.u*`, `.f*`) and HDF output files (`.hdf`), aiming for accessibility and automation without needing the complexities of the HEC-RAS GUI or DSS manipulation.

1.  **Data Sources in HEC-RAS Projects**:
    *   ASCII input files (plans, unsteady flows, geometry definitions, project structure).
    *   DSS (Data Storage System) files (often used for time-series inputs like hydrographs, observed data).
    *   HDF (Hierarchical Data Format) files (contain detailed geometry tables and simulation results).

2.  **RAS Commander's Focus**:
    *   **Reading/Writing ASCII:** Parses `.prj` for structure. Reads/writes parameters in `.p*`, `.u*`, `.g*` files using `RasPlan`, `RasUnsteady`, `RasGeo`.
    *   **Reading HDF:** Extensive capabilities to read geometry and results from `.g*.hdf` and `.p*.hdf` files using `Hdf*` classes.
    *   **Avoiding Direct DSS Manipulation:** The library generally avoids reading from or writing to DSS files directly due to their binary format complexity and reliance on HEC libraries.

3.  **Strategy for Handling DSS Inputs**:
    *   **Option 1 (Recommended): Define Time Series in ASCII:** Instead of referencing DSS paths in your unsteady flow file (`.u*`), define hydrographs directly within the file using the fixed-width table format. You can use `RasUnsteady.extract_tables` to read existing tables and `RasUnsteady.write_table_to_file` to write modified/new ones.
    *   **Option 2 (Workaround): Read DSS Data via HDF:** If a simulation *using* DSS inputs has already been run, the HDF results file often contains the time-series data that was originally sourced from DSS (e.g., boundary condition flows). You can extract this from the HDF using `ras_commander` (e.g., via `HdfResultsXsec`) and potentially use it to construct ASCII tables for future runs.

4.  **Accessing Project Data**:
    *   **Project Structure:** `ras.plan_df`, `ras.geom_df`, `ras.flow_df`, `ras.unsteady_df` provide DataFrames parsed from the `.prj` file and associated plan/unsteady files.
    *   **Plan/Unsteady Parameters:** Use `RasPlan.get_plan_value` or read specific lines via `RasPlan`/`RasUnsteady` functions. Modify using `set_`/`update_` functions.
    *   **Geometry Data:** Detailed geometry (mesh, cross-sections, structures) is best accessed from the HDF geometry file (`.g*.hdf`) using `HdfMesh`, `HdfXsec`, `HdfStruc`, `HdfPipe`, `HdfPump`.
    *   **Results Data:** Simulation outputs are read from the HDF results file (`.p*.hdf`) using `HdfResultsMesh`, `HdfResultsPlan`, `HdfResultsXsec`, etc.
    *   **Boundary Conditions:** Parsed summary and table data available in `ras.boundaries_df` and via `RasUnsteady.extract_tables`.

### Working with RAS Commander

1.  **Initialization**: Start with `init_ras_project()` to load the project structure into a `RasPrj` object (usually the global `ras`).
2.  **Inspection**: Use the `.df` attributes (`ras.plan_df`, etc.) and `get_*_entries()` methods to understand the project components.
3.  **Modification**: Use `RasPlan`, `RasUnsteady`, `RasGeo` methods to change parameters, clone components, or update file references. Remember these often refresh the `ras` object's DataFrames.
4.  **Execution**: Use `RasCmdr` methods (`compute_plan`, `compute_parallel`, `compute_test_mode`) to run simulations.
5.  **Results Analysis**: After successful computation, use `Hdf*` classes to read geometry and results data from the relevant `.hdf` files (geometry or plan results). Use `RasPlan.get_results_path()` to find the results HDF.

### Example Workflow: Modifying and Running a Boundary Condition

```python
from ras_commander import (
    init_ras_project, ras, RasPlan, RasUnsteady, RasCmdr, HdfResultsXsec
)
import pandas as pd

# 1. Initialize Project
init_ras_project("/path/to/project", "6.5")

# 2. Identify and Clone Components
template_plan = "01"
template_unsteady = ras.plan_df.loc[ras.plan_df['plan_number'] == template_plan, 'unsteady_number'].iloc[0]

new_plan_num = RasPlan.clone_plan(template_plan, new_plan_shortid="Scaled_Flow_Test")
new_unsteady_num = RasPlan.clone_unsteady(template_unsteady)

# 3. Link Cloned Components
RasPlan.set_unsteady(new_plan_num, new_unsteady_num) # Link new unsteady to new plan
print(f"Plan {new_plan_num} created, using Unsteady {new_unsteady_num}")

# 4. Modify Unsteady Flow Data
new_unsteady_path = RasPlan.get_unsteady_path(new_unsteady_num)

# Find the flow hydrograph table within the new unsteady file
try:
    with open(new_unsteady_path, 'r') as f:
        lines = f.readlines()
    tables_info = RasUnsteady.identify_tables(lines)
    
    flow_table_info = None
    for name, start, end in tables_info:
        if "Flow Hydrograph" in name:
            flow_table_info = (name, start, end)
            break
            
    if not flow_table_info:
        raise ValueError("Flow Hydrograph table not found in unsteady file.")

    flow_table_name, flow_start_line, flow_end_line = flow_table_info
    
    # Parse the table
    flow_df = RasUnsteady.parse_fixed_width_table(lines, flow_start_line, flow_end_line)
    
    # Modify the values (e.g., scale by 1.2)
    flow_df['Value'] = flow_df['Value'] * 1.2
    print(f"Scaled {len(flow_df)} flow values by 1.2")
    
    # Write the modified table back
    RasUnsteady.write_table_to_file(new_unsteady_path, flow_table_name, flow_df, flow_start_line)
    print("Modified unsteady flow file saved.")

except Exception as e:
    print(f"Error modifying unsteady file: {e}")
    # Handle error exit

# 5. Execute the Modified Plan
print(f"Running plan {new_plan_num}...")
success = RasCmdr.compute_plan(new_plan_num, num_cores=2)

# 6. Analyze Results (if successful)
if success:
    print("Computation successful. Analyzing results...")
    hdf_path = RasPlan.get_results_path(new_plan_num)
    if hdf_path:
        xsec_results = HdfResultsXsec.get_xsec_timeseries(hdf_path)
        max_flow = xsec_results['Maximum_Flow'].max().item() # Get overall max flow from results
        print(f"Overall maximum cross-section flow in results: {max_flow:.2f}")
    else:
        print("Could not find HDF results file.")
else:
    print("Computation failed.")

```

### Best Practices for Workflow Development

1.  **Understand Your Data**: Know where key information resides (ASCII vs. HDF) and how HEC-RAS uses it.
2.  **Leverage HDF**: Use the `Hdf*` classes for reading detailed geometry and results – it's often easier than parsing ASCII geometry or complex results formats.
3.  **Iterate**: Start simple. Manually perform a step in HEC-RAS, understand the file changes, then automate that step using `ras_commander`. Verify with the GUI.
4.  **Isolate Runs**: Use `dest_folder` in `RasCmdr` functions or `compute_test_mode` to avoid modifying your original project during testing and development.
5.  **Log Extensively**: Use `logger.info()`, `logger.debug()`, etc., in your scripts to track progress and diagnose issues. Configure logging levels appropriately.
6.  **Use AI Assistance**: Leverage the AI-friendly structure. Provide relevant code snippets, this guide, or specific examples to an AI assistant (like ChatGPT, Claude) to help generate code for your specific tasks using the `ras_commander` API.

By following these strategies, you can effectively use `ras_commander` to automate complex HEC-RAS workflows, even navigating around limitations like direct DSS interaction by focusing on ASCII parameter files and HDF data extraction.

## RAS-Commander Dataframe Examples

After initializing a HEC-RAS project with `init_ras_project()`, `ras_commander` provides several pandas DataFrames accessible via the `RasPrj` object (e.g., `ras.plan_df`) to inspect the project's structure and components.

### Project Information

Basic info stored directly on the `RasPrj` object:

```python
from ras_commander import ras, init_ras_project
init_ras_project(r"C:\path\to\your\Muncie_Project", "6.5") # Example path

print(f"Project Name: {ras.project_name}")
print(f"Project Folder: {ras.project_folder}")
print(f"PRJ File: {ras.prj_file}")
print(f"HEC-RAS Executable Path: {ras.ras_exe_path}")
```
*Example output:*
```
Project Name: Muncie
Project Folder: C:\path\to\your\Muncie_Project
PRJ File: C:\path\to\your\Muncie_Project\Muncie.prj
HEC-RAS Executable Path: C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe
```

### Plan Files DataFrame (`ras.plan_df`)

Contains information parsed from the `.prj` file and individual `.p*` files about each plan.

```python
print(f"\nPlan Files DataFrame ({len(ras.plan_df)} plans):")
display(ras.plan_df) # Use display() in notebooks for better formatting
```

*Key columns include:*
*   `plan_number`: Plan identifier ("01", "02", ...).
*   `full_path`: Path to the `.p*` file.
*   `Short Identifier`: User-defined short name.
*   `Plan Title`: User-defined full title.
*   `Geom File`: Geometry file number used (`gXX`).
*   `Flow File`: Flow file number used (`fXX` or `uXX`).
*   `unsteady_number`: Unsteady flow number if used (`uXX`), else `None`.
*   `geometry_number`: Geometry number used (`gXX`).
*   `Simulation Date`: Start/end dates/times string.
*   `Computation Interval`: Time step (e.g., "2MIN").
*   `Run HTab`, `Run UNet`, etc.: Run flags (parsed value).
*   `UNET D1 Cores`, `UNET D2 Cores`: Core settings (parsed integer).
*   `HDF_Results_Path`: Path to `.p*.hdf` results file, if it exists.
*   `Geom Path`, `Flow Path`: Calculated paths to associated geometry and flow files.

*(See original guide for example table structure)*

### Flow Files DataFrame (`ras.flow_df`)

Lists steady flow files (`.f*`) found in the `.prj` file.

```python
print(f"\nSteady Flow Files DataFrame ({len(ras.flow_df)} files):")
display(ras.flow_df)
```
*Key columns:*
*   `flow_number`: Flow file identifier ("01", "02", ...).
*   `full_path`: Path to the `.f*` file.

*(See original guide for example table structure)*

### Unsteady Flow Files DataFrame (`ras.unsteady_df`)

Lists unsteady flow files (`.u*`) found in the `.prj` file, with metadata parsed from the files.

```python
print(f"\nUnsteady Flow Files DataFrame ({len(ras.unsteady_df)} files):")
display(ras.unsteady_df)
```
*Key columns:*
*   `unsteady_number`: Unsteady file identifier ("01", "02", ...).
*   `full_path`: Path to the `.u*` file.
*   `Flow Title`: Title parsed from the `.u*` file.
*   `Program Version`: Version parsed from the `.u*` file.
*   `Use Restart`: Restart flag parsed from the `.u*` file.
*   Other parsed metadata (Precipitation, Wind modes etc.).

*(See original guide for example table structure)*

### Geometry Files DataFrame (`ras.geom_df`)

Lists geometry files (`.g*`) found in the `.prj` file.

```python
print(f"\nGeometry Files DataFrame ({len(ras.geom_df)} files):")
display(ras.geom_df)
```
*Key columns:*
*   `geom_number`: Geometry file identifier ("01", "02", ...).
*   `full_path`: Path to the `.g*` file.
*   `geom_file`: Base name (`gXX`).
*   `hdf_path`: Calculated path to the corresponding geometry HDF file (`.g*.hdf`).

*(See original guide for example table structure)*

### HDF Entries DataFrame (`ras.get_hdf_entries()`)

Filters `plan_df` to show only plans where the HDF results file exists.

```python
hdf_entries_df = ras.get_hdf_entries()
print(f"\nHDF Entries DataFrame ({len(hdf_entries_df)} plans with results):")
display(hdf_entries_df)
```
*Structure:* Same columns as `plan_df`, but only includes rows where `HDF_Results_Path` points to an existing file.

*(See original guide for example table structure)*

### Boundary Conditions DataFrame (`ras.boundaries_df`)

Detailed information about boundary conditions parsed from *all* unsteady flow files (`.u*`) in the project.

```python
print(f"\nBoundary Conditions DataFrame ({len(ras.boundaries_df)} conditions):")
display(ras.boundaries_df)
```
*Key columns include:*
*   `unsteady_number`: Links to the `.u*` file.
*   `boundary_condition_number`: Sequential ID within the unsteady file.
*   `river_reach_name`, `river_station`: Location (for river boundaries).
*   `storage_area_name`, `pump_station_name`: Location (for SA/Pump boundaries).
*   `bc_type`: Type of boundary (e.g., "Flow Hydrograph", "Normal Depth", "Gate Opening").
*   `hydrograph_type`: Specific type if it's a hydrograph.
*   `Interval`: Time interval for hydrograph data.
*   `hydrograph_num_values`: Number of points in the hydrograph table.
*   `hydrograph_values`: List of hydrograph values (often as strings or numbers).
*   Columns inherited from `unsteady_df` via merge (`Flow Title`, `Program Version`, etc.).

*(See original guide for example table structure)*

### Accessing and Using Dataframes

Use standard pandas operations to query and analyze this structured project data.

```python
import pandas as pd
# Assuming 'ras' is initialized

# Find all plans using geometry "01"
g01_plans = ras.plan_df[ras.plan_df['geometry_number'] == '01']
print(f"\nPlans using Geometry 01: {g01_plans['plan_number'].tolist()}")

# Get details for a specific plan
plan_02_details = ras.plan_df[ras.plan_df['plan_number'] == '02'].iloc[0]
print(f"\nDetails for Plan 02 - Short ID: {plan_02_details['Short Identifier']}")

# Count boundary conditions by type across the whole project
if ras.boundaries_df is not None and not ras.boundaries_df.empty:
    bc_counts = ras.boundaries_df['bc_type'].value_counts()
    print("\nBoundary Condition Counts:")
    print(bc_counts)
else:
    print("\nNo boundary conditions found in project.")

# Find unsteady files using a restart file
restart_files = ras.unsteady_df[ras.unsteady_df['Use Restart'] == 'True'] # Check actual parsed value
print(f"\nUnsteady files using restart: {restart_files['unsteady_number'].tolist()}")
```

These DataFrames provide a powerful way to programmatically understand and interact with the structure and components of your HEC-RAS projects.

## Conclusion

The RAS-Commander (`ras_commander`) library provides a robust and flexible Python interface for automating HEC-RAS workflows. By leveraging its classes and functions for project management, execution, file operations, and HDF data extraction, users can significantly streamline their modeling processes. Adhering to the best practices outlined in this guide, particularly regarding RAS object management, file handling, and error checking, will lead to more efficient and reliable automation scripts.

Remember to consult the specific docstrings of functions for detailed parameter information and refer to the library's source code for the most up-to-date implementation details.

For further assistance, bug reports, or feature requests, please refer to the library's [GitHub repository](https://github.com/billk-FM/ras-commander) and issue tracker.

**Happy Modeling!**

