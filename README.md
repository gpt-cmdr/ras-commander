## RAS-Commander Library Organization

| Directory/File | Purpose |
|---|---|
| ras_commander/__init__.py | Initializes the library and defines the public API. |
| ras_commander/execution.py | Handles execution of HEC-RAS simulations. |
| ras_commander/file_operations.py | Provides functions for reading and parsing HEC-RAS project files. |
| ras_commander/geometry_operations.py | Provides functions for manipulating geometry files. |
| ras_commander/plan_operations.py | Provides functions for modifying and updating plan files. |
| ras_commander/project_config.py | Defines the ProjectConfig class for managing project-level information. |
| ras_commander/project_init.py | Provides the `init_ras_project` function to initialize a project. |
| ras_commander/project_management.py | Provides functions for managing HEC-RAS projects (e.g., copying files, updating project file). |
| ras_commander/project_setup.py | Provides helper functions for project setup (e.g., finding project file, loading project data). |
| ras_commander/unsteady_operations.py | Provides functions for manipulating unsteady flow files. |
| ras_commander/utilities.py | Provides general utility functions (e.g., file backup, directory creation). |


## Project Organization Diagram

```
ras_commander
├── execution.py
├── file_operations.py
├── geometry_operations.py
├── plan_operations.py
├── project_config.py
├── project_init.py
├── project_management.py
├── project_setup.py
├── unsteady_operations.py
└── utilities.py
```

## Functions Overview

| Function | Arguments | Purpose |
|---|---|---|
| `init_ras_project` | `ras_project_folder`, `hecras_exe_path` | Initializes a HEC-RAS project by setting up the `ProjectConfig` with project details. |
| `compute_hecras_plan` | `plan_file` | Executes a HEC-RAS plan file. |
| `compute_hecras_plan_from_folder` | `test_plan_file`, `test_folder_path` | Execute a single HEC-RAS plan from a folder other than the project path.
| `recreate_test_function` | `project_folder` | Recreates the -test function from the HEC-RAS interface, primarily by copying the project directory, forcing recomputation, and running each plan. |
| `run_plans_parallel` | `config`, `max_workers`, `cores_per_run` | Run HEC-RAS plans in parallel. |
| `run_all_plans_parallel` | `project_folder`, `hecras_exe_path` | Run all HEC-RAS plans in parallel from a project folder path. | 
| `find_hecras_project_file` | `folder_path` | Locates the HEC-RAS project file (.prj) within a given folder. |
| `get_project_name` | `project_path` | Extracts the project name from the project file path. |
| `get_plan_entries` | `project_file` | Parses the project file to extract plan file information into a DataFrame. |
| `get_flow_entries` | `project_file` | Parses the project file to extract steady flow file information into a DataFrame. |
| `get_unsteady_entries` | `project_file` | Parses the project file to extract unsteady flow file information into a DataFrame. |
| `get_geom_entries` | `project_file` | Parses the project file to extract geometry file information into a DataFrame. |
| `clear_geometry_preprocessor_files` | `plan_file` | Deletes the geometry preprocessor files (.cXX) associated with a plan file. |
| `clear_geometry_preprocessor_files_for_all_plans` |  | Deletes geometry preprocessor files for all plans in the project directory. |
| `copy_geometry_files` | `dst_folder`, `template_geom` | Copies geometry files from a template to a destination folder, assigning the next available geometry number. |
| `rename_geometry_files` | `old_number`, `new_number` | Renames geometry files (both .gXX and .gXX.hdf) in the project folder. |
| `update_geometry_reference_in_plan` | `plan_file`, `new_geometry_number` | Updates the "Geom File=" entry in a plan file to reference a new geometry number. |
| `apply_geometry_to_plan` | `plan_file`, `geometry_number` | Sets the geometry file used by a plan file. |
| `apply_flow_to_plan` | `plan_file`, `flow_number` | Sets the steady flow file used by a plan file. |
| `copy_plan_from_template` | `template_plan` | Creates a new plan file by copying a template and updates the project file with the new plan entry. |
| `get_next_available_number` | `existing_numbers` | Finds the next available number (e.g., for plans, unsteady flows) based on existing ones. |
| `apply_unsteady_to_plan` | `plan_file`, `unsteady_number` | Sets the unsteady flow file used by a plan file. |
| `set_num_cores` | `plan_file`, `num_cores` | Sets the maximum number of cores to be used for a plan file. |
| `update_geompre_flags` | `file_path`, `run_htab_value`, `use_ib_tables_value` | Updates the geometry preprocessor flags in a plan file. |
| `get_plan_full_path` | `plan_number` | Returns the full path to a plan file based on its number. |
| `get_results_full_path` | `plan_number` | Returns the full path to a plan's results file (.hdf) based on its number. |
| `get_flow_full_path` | `flow_number` | Returns the full path to a steady flow file based on its number. |
| `get_unsteady_full_path` | `unsteady_number` | Returns the full path to an unsteady flow file based on its number. |
| `get_geom_full_path` | `geometry_number` | Returns the full path to a geometry file based on its number. |
| `copy_unsteady_files` | `dst_folder`, `template_unsteady` | Copies unsteady flow files from a template to a destination folder, assigning the next available unsteady number. |
| `rename_unsteady_files` | `old_number`, `new_number` | Renames unsteady flow files (both .uXX and .uXX.hdf) in the project folder. |
| `update_unsteady_reference_in_plan` | `plan_file`, `new_unsteady_number` | Updates the "Unsteady File=" entry in a plan file to reference a new unsteady flow number. |
| `modify_unsteady_flow_parameters` | `unsteady_file`, `modifications` | Modifies parameters within an unsteady flow file based on a dictionary of changes. |
| `create_backup` | `file_path`, `backup_suffix` | Creates a backup copy of a file. |
| `restore_from_backup` | `backup_path`, `remove_backup` | Restores a file from a backup copy. |
| `safe_remove` | `file_path` | Removes a file if it exists, handling potential errors. |
| `ensure_directory` | `directory_path` | Creates a directory if it does not exist. |
| `list_files_with_extension` | `extension` | Lists files with a specific extension in the project directory. |
| `get_file_size` | `file_path` | Returns the size of a file in bytes. |
| `get_modification_time` | `file_path` | Returns the last modification time of a file. |
| `get_plan_path` | `current_plan_number` | Returns the full path to a plan file based on its number. |
| `retry_remove_folder` | `folder_path`, `max_attempts`, `initial_delay` | Attempts to remove a folder with retry and a delay. |



## Potential Uses of RAS-Commander Functions

The RAS-Commander library offers a wide range of functionalities that can be used to automate various aspects of HEC-RAS modeling workflows. Here are some potential uses:

**1. Automated Plan Creation and Execution:**

* **Batch processing of multiple scenarios:** RAS-Commander allows you to create new plan files based on templates, modify plan parameters (e.g., geometry, flow, unsteady flow files, number of cores), and execute them in parallel. This can be useful for analyzing multiple scenarios with different inputs or model configurations.
* **Sensitivity analysis and optimization:** By combining RAS-Commander with other libraries (e.g., for parameter sampling or optimization), you can automate sensitivity analysis and parameter optimization studies.
* **Monte Carlo simulations:** RAS-Commander can be used to automate the execution of Monte Carlo simulations by creating multiple plan files with randomly sampled input parameters.

**2. Project Management and Organization:**

* **Automated file management:** Functions for copying, renaming, and updating file references help maintain consistency and organization within your HEC-RAS project.
* **Backup and restore functionalities:** Ensure project integrity by creating backups of project files and restoring them when needed.
* **Project setup and initialization:** Streamline the process of setting up new HEC-RAS projects with standardized configurations.

**3. Advanced Modeling Techniques:**

* **Coupled modeling:** RAS-Commander can be used to automate the setup and execution of coupled models (e.g., HEC-RAS with other hydrodynamic or hydrologic models).
* **Data assimilation and calibration:** By integrating RAS-Commander with data assimilation or calibration tools, you can automate the process of updating model parameters based on observed data.
* **Post-processing and analysis:** RAS-Commander can be used to extract results from HEC-RAS output files and perform post-processing and analysis tasks.


**4. Integration with Other Tools:**

* **Python scripting and automation:** RAS-Commander can be easily integrated into Python scripts and workflows for more complex automation tasks.
* **Web applications and dashboards:** Develop web applications and dashboards that allow users to interact with HEC-RAS models and visualize results through a user-friendly interface.
* **Integration with GIS software:** RAS-Commander can be used to link HEC-RAS models with GIS software for spatial analysis and visualization.


**Examples:**

* **Floodplain mapping:** Automate the creation of floodplain maps for different return periods by creating and executing multiple plan files with varying flow conditions.
* **Dam break analysis:** Automate the setup and execution of dam break simulations by modifying unsteady flow parameters and boundary conditions.
* **Bridge scour analysis:** Automate the assessment of bridge scour potential by integrating HEC-RAS with bridge scour analysis tools.


By automating repetitive tasks and providing a framework for managing complex workflows, RAS-Commander can significantly improve the efficiency and reproducibility of HEC-RAS modeling projects. This can lead to better decision-making and more accurate and reliable results. 
