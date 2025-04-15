# RAS Commander Examples

This directory contains example notebooks demonstrating how to use the `ras-commander` library for automating HEC-RAS operations. These examples cover basic to advanced usage scenarios and provide a practical guide for hydraulic modelers looking to automate their workflows.

## Overview

HEC-RAS (Hydrologic Engineering Center's River Analysis System) is widely used for hydraulic modeling. The `ras-commander` library provides a Python interface to automate HEC-RAS operations without using the graphical user interface. This enables batch processing, sensitivity analysis, and integration with other Python tools for water resources engineering.

These example notebooks are designed to:
- Demonstrate key functionalities of the `ras-commander` library
- Provide practical use cases for automation
- Guide users from basic to advanced operations
- Serve as templates for your own automation scripts

## Examples

### [00_Using_RasExamples.ipynb](00_Using_RasExamples.ipynb)

This notebook introduces the `RasExamples` class, which provides easy access to HEC-RAS example projects for testing and demonstration purposes.

**Key contents:**
- Installing `ras-commander` from pip
- Using flexible imports for development without installation
- Extracting specific HEC-RAS example projects by folder name
- Advanced usage options for managing example projects
- Listing available example projects and categories
- Working with the new pipes and conduits examples (version 6.6)

### [01_project_initialization.ipynb](01_project_initialization.ipynb)

This notebook covers initializing and working with HEC-RAS projects using the `ras-commander` library.

**Key contents:**
- Setting up and configuring the RAS Commander environment
- Downloading and extracting example HEC-RAS projects
- Initializing HEC-RAS projects using the global `ras` object
- Initializing multiple HEC-RAS projects using custom RAS objects
- Accessing various project components (plans, geometries, flows, boundaries)
- Understanding the RAS object structure and its components
- Working with boundary conditions
- Comparing multiple projects

### [02_plan_and_geometry_operations.ipynb](02_plan_and_geometry_operations.ipynb)

This notebook demonstrates operations on HEC-RAS plan and geometry files using the RAS Commander library.

**Key contents:**
- Project initialization and understanding plan/geometry files
- Cloning plans to create new simulation scenarios
- Cloning geometry files for modified versions
- Setting geometry files for plans
- Clearing geometry preprocessor files
- Configuring simulation parameters and intervals
- Setting run flags and updating descriptions
- Cloning and configuring unsteady flow files
- Computing plans and verifying results
- Working with advanced HDF data
- Best practices for plan and geometry operations

### [03_unsteady_flow_operations.ipynb](03_unsteady_flow_operations.ipynb)

This notebook demonstrates operations on unsteady flow files using the RAS Commander library.

**Key contents:**
- Understanding unsteady flow files in HEC-RAS
- Extracting boundary conditions and tables from unsteady flow files
- Inspecting and analyzing boundary condition structures
- Working with different boundary condition types (flow hydrographs, stage hydrographs, etc.)
- Modifying flow titles in unsteady flow files
- Configuring restart settings for continuing simulations
- Extracting and working with flow tables
- Modifying flow tables and writing them back to files
- Applying updated unsteady flow to a plan and computing results

### [04_multiple_project_operations.ipynb](04_multiple_project_operations.ipynb)

This notebook demonstrates how to work with multiple HEC-RAS projects simultaneously using the RAS Commander library.

**Key contents:**
- Initializing and managing multiple HEC-RAS projects
- Cloning and modifying plans across different projects
- Running computations for multiple projects in parallel
- Optimizing computing resources when working with multiple models
- Analyzing and comparing results from different projects
- Building comprehensive multi-project workflows
- Best practices for multiple project management
- Setting up compute folders for multiple projects
- Comparing project structures and results

### [05_single_plan_execution.ipynb](05_single_plan_execution.ipynb)

This notebook focuses specifically on executing a single HEC-RAS plan with various configuration options.

**Key contents:**
- Understanding the `RasCmdr.compute_plan` method and its parameters
- Executing a plan with a specified number of processor cores
- Creating and managing destination folders for computations
- Overwriting existing destination folders
- Verifying computation results
- Options for single plan execution (basic execution, destination folder, number of cores, etc.)
- Best practices for single plan execution

### [06_executing_plan_sets.ipynb](06_executing_plan_sets.ipynb)

This notebook demonstrates different ways to specify and execute HEC-RAS plans using the RAS Commander library.

**Key contents:**
- Understanding plan specification in HEC-RAS
- Sequential execution of specific plans
- Selective plan execution based on criteria
- Running only plans without HDF results
- Verifying execution results
- Best practices for plan specification
- Choosing appropriate execution methods based on scenario
- Understanding the importance of plan selection for efficiency

### [07_sequential_plan_execution.ipynb](07_sequential_plan_execution.ipynb)

This notebook demonstrates how to sequentially execute multiple HEC-RAS plans using the RAS Commander library.

**Key contents:**
- Understanding sequential execution in HEC-RAS
- Using the `RasCmdr.compute_test_mode` method
- Executing all plans in a project sequentially
- Analyzing the test folder after sequential execution
- Executing specific plans with geometry preprocessor clearing
- Best practices for sequential execution
- Environment setup and test folder management
- Benefits of sequential execution (controlled resource usage, dependency management, etc.)

### [08_parallel_execution.ipynb](08_parallel_execution.ipynb)

This notebook demonstrates how to execute multiple HEC-RAS plans in parallel to maximize computational efficiency.

**Key contents:**
- Understanding parallel execution in HEC-RAS
- Setting up a working environment for parallel execution
- Checking system resources for optimal parallel execution
- Executing all plans in a project in parallel
- Executing specific plans in parallel
- Dynamic worker allocation based on available resources
- Balancing workers and cores per worker
- Analyzing parallel execution results
- Performance comparison between different parallel configurations
- Best practices for parallel execution

### [09_plan_parameter_operations.ipynb](09_plan_parameter_operations.ipynb)

This notebook demonstrates how to perform key operations on HEC-RAS plan files, focusing on modifying simulation parameters.

**Key contents:**
- Understanding plan files in HEC-RAS
- Retrieving specific values from plan files
- Updating run flags to control which components will run
- Modifying computation and output time intervals
- Reading and updating plan descriptions
- Changing simulation start and end dates
- Verifying updated plan values
- Best practices for plan operations
- Automating parameter adjustments for sensitivity analysis
- Managing documentation through plan descriptions

### [10_1d_hdf_data_extraction.ipynb](10_1d_hdf_data_extraction.ipynb)

This notebook demonstrates how to extract and analyze 1D data from HEC-RAS HDF files using the RAS Commander library.

**Key contents:**
- Accessing and extracting base geometry attributes from HDF files
- Working with 1D cross-section data, including station-elevation profiles
- Visualizing cross-section properties like Manning's n values
- Extracting river centerlines, bank lines, and edge lines
- Analyzing runtime data and compute messages
- Processing and visualizing ineffective flow areas
- Extracting time series data for 1D cross sections
- Plotting cross-section elevation profiles with bank stations

### [11_2d_hdf_data_extraction.ipynb](11_2d_hdf_data_extraction.ipynb)

This notebook shows how to extract and analyze 2D data from HEC-RAS HDF files using the RAS Commander library.

**Key contents:**
- Working with 2D flow area attributes and perimeter polygons
- Extracting and visualizing mesh cell faces, polygons, and points
- Finding nearest faces and cells to specific points
- Extracting boundary condition lines and breaklines
- Analyzing maximum water surface elevations and timing
- Working with maximum face velocities and water surface errors
- Visualizing 2D model results with terrain data
- Extracting and interpreting cell and face time series data

### [12_2d_hdf_data_extraction_pipes_and_pumps.ipynb](12_2d_hdf_data_extraction_pipes_and_pumps.ipynb)

This notebook focuses on extracting and analyzing data related to pipes, conduits, and pump stations from HEC-RAS HDF files.

**Key contents:**
- Working with pipe conduits and associated geometries
- Extracting pipe node information and properties
- Analyzing pipe network connectivity and structures
- Visualizing pipe networks with node elevations
- Working with pump stations and pump groups
- Extracting pipe and node time series data
- Analyzing face flow, velocity, and water surface values
- Processing and visualizing pump station operation data

### [13_2d_detail_face_data_extraction.ipynb](13_2d_detail_face_data_extraction.ipynb)

This notebook demonstrates techniques for detailed face data extraction from 2D HEC-RAS models.

**Key contents:**
- Extracting and analyzing detailed face property tables
- Working with profile lines to identify cell faces
- Finding faces perpendicular to flow for discharge calculations
- Converting face velocities and flows to positive values
- Calculating discharge-weighted velocities for profile lines
- Comparing discharge-weighted and simple average velocities
- Visualizing time series data for selected faces
- Creating profile-specific result datasets for analysis

### [14_fluvial_pluvial_delineation.ipynb](14_fluvial_pluvial_delineation.ipynb)

This notebook demonstrates how to delineate fluvial and pluvial flooding areas based on the timing of maximum water surface elevations.

**Key contents:**
- Extracting maximum water surface elevation and timing data
- Identifying adjacent cells with dissimilar flood timing
- Calculating boundaries between fluvial and pluvial flooding
- Filtering boundaries based on length thresholds
- Visualizing the fluvial-pluvial boundary on a map
- Exporting boundaries to GeoJSON format
- Understanding the difference between river-driven and rainfall-driven flooding
- Using cell polygon geometry for spatial analysis

### [15_mannings_sensitivity_bulk_analysis.ipynb](15_mannings_sensitivity_bulk_analysis.ipynb)

This notebook provides tools for analyzing the sensitivity of HEC-RAS models to changes in Manning's n values applied *in bulk* across land cover types based on literature ranges.

**Key contents:**
- Defining Manning's n ranges (min/max) for various land cover types.
- Automating the creation of scenarios (min, max, current n values).
- Applying bulk changes to base and/or regional Manning's overrides.
- Running sensitivity scenarios in parallel.
- Extracting results at a point of interest.
- Comparing and visualizing the impact of bulk Manning's n changes on water surface elevation.

### [16_mannings_sensitivity_multi-interval.ipynb](16_mannings_sensitivity_multi-interval.ipynb)

This notebook performs a more detailed Manning's n sensitivity analysis by varying the roughness coefficient for *individual significant land uses* across a range of values.

**Key contents:**
- Analyzing land cover statistics within 2D mesh areas.
- Identifying significant land cover types based on area threshold.
- Generating multiple test plans by varying the n value for one land cover type at a time, across its literature-based range (min to max).
- Applying changes individually to base or regional overrides.
- Running sensitivity scenarios in parallel.
- Extracting and visualizing results to show sensitivity to specific land cover roughness.
- Estimating the number of plans to be generated and managing potential HEC-RAS limits.

### [101_Core_Sensitivity.ipynb](101_Core_Sensitivity.ipynb)

This notebook tests HEC-RAS performance with different CPU core configurations to optimize computational efficiency.

**Key contents:**
- Setting up a controlled testing environment
- Running the same plan with varying core counts
- Measuring execution time for each configuration
- Analyzing performance scaling with increased cores
- Creating visualization of performance metrics
- Calculating unit runtime based on single-core performance
- Understanding diminishing returns with multiple cores
- Identifying optimal core count for specific models

### [102_benchmarking_versions_6.1_to_6.6.ipynb](102_benchmarking_versions_6.1_to_6.6.ipynb)

This notebook compares performance across different versions of HEC-RAS by running the same plan across multiple software versions.

**Key contents:**
- Running the same model across multiple HEC-RAS versions
- Measuring preprocessing, computation, and postprocessing times
- Analyzing volume error changes between versions
- Creating visualizations of performance trends
- Identifying performance improvements between versions
- Understanding version-specific computational differences
- Setting up flexible testing environments for multiple versions
- Interpreting HEC-RAS version performance evolution

### [103_Generating_AEP_Events_from_Atlas_14.ipynb](103_Generating_AEP_Events_from_Atlas_14.ipynb)

This notebook demonstrates an end-to-end workflow for generating and analyzing multiple Annual Exceedance Probability events.

**Key contents:**
- Generating hyetographs from NOAA Atlas 14 precipitation frequency data
- Parsing duration strings and interpolating precipitation depths
- Applying the Alternating Block Method for hyetograph creation
- Cloning and configuring HEC-RAS plans for different AEP events
- Executing multiple plans in parallel with resource optimization
- Extracting and visualizing results for multiple AEP scenarios
- Creating a complete workflow from data to flood analysis
- Comparing results across different return period events


## Contributing

If you have suggestions for additional examples or improvements to existing ones, please feel free to contribute by submitting pull requests or opening issues in the repository.