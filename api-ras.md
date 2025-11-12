# RAS Commander API Documentation

This document provides a detailed reference for the public Application Programming Interface (API) of the `ras_commander` library. It lists all public classes and functions available for interacting with HEC-RAS projects.

## Introduction to Decorators

Many functions within the `ras_commander` library utilize decorators to provide common functionality like logging and input standardization. Understanding these decorators is key to using the API effectively.

### `@log_call`

*   **Purpose:** Automatically logs the entry and exit of a function call at the DEBUG level using the library's configured logger.
*   **Usage:** Applied to most public methods in the `Ras*` and `Hdf*` classes.
*   **Benefit:** Reduces boilerplate logging code and provides a consistent way to trace function execution for debugging purposes. You can configure the overall logging level using `logging.getLogger('ras_commander').setLevel(logging.LEVEL)`.

### `@standardize_input(file_type='plan_hdf'|'geom_hdf')`

*   **Purpose:** Standardizes the input for functions that operate on HEC-RAS HDF files (`.hdf`). It ensures that the function receives a validated `pathlib.Path` object pointing to the correct HDF file, regardless of the input format provided by the user.
*   **Usage:** Primarily used by methods within the `Hdf*` classes.
*   **Accepted Inputs:** The decorator can handle various input types for the HDF file path argument (usually the first argument or `hdf_path` keyword):
    *   `str`: A plan/geometry number (e.g., "01"), a plan prefix number (e.g., "p01"), or a full file path.
    *   `int`: A plan/geometry number (e.g., 1).
    *   `pathlib.Path`: A Path object pointing to the HDF file.
    *   `h5py.File`: An opened h5py File object (the decorator extracts the filename).
*   **`file_type` Argument:**
    *   `'plan_hdf'`: When resolving numbers, the decorator looks for the corresponding plan results HDF file (e.g., `ProjectName.p01.hdf`). This is the default.
    *   `'geom_hdf'`: When resolving numbers, the decorator looks for the corresponding geometry HDF file (e.g., `ProjectName.g01.hdf`).
*   **RAS Object Context:** The decorator uses the provided `ras_object` (or the global `ras` instance) to look up file paths when numbers are given as input. Ensure the relevant `RasPrj` object is initialized.
*   **Validation:** The decorator verifies that the resulting path points to an existing file before passing it to the decorated function.

---

## Class: RasPrj

Manages HEC-RAS project data and state. Provides access to project files, plans, geometries, flows, and boundary conditions. Can be used as a global `ras` object or instantiated for multi-project workflows.

### `RasPrj.__init__()`

*   **Purpose:** Constructor for RasPrj class. Creates an uninitialized instance.
*   **Parameters:** None.
*   **Returns:** `None`. Creates a new RasPrj instance with `initialized=False`.
*   **Note:** Call `initialize()` or use `init_ras_project()` to fully initialize the instance with project data.

### `RasPrj.initialize(project_folder, ras_exe_path, suppress_logging=True)`

*   **Purpose:** Initializes a `RasPrj` instance. **Note:** Users should typically call `init_ras_project()` instead.
*   **Parameters:**
    *   `project_folder` (`str` or `Path`): Path to the HEC-RAS project folder.
    *   `ras_exe_path` (`str` or `Path`): Path to the HEC-RAS executable.
    *   `suppress_logging` (`bool`, optional, default=`True`): Suppresses detailed initialization logs if True.
*   **Returns:** `None`. Modifies the instance in place.
*   **Raises:** `ValueError` if no `.prj` file is found.

### `RasPrj.check_initialized()`

*   **Purpose:** Checks if the `RasPrj` instance has been initialized.
*   **Parameters:** None.
*   **Returns:** `None`.
*   **Raises:** `RuntimeError` if the project is not initialized.

### `RasPrj.find_ras_prj(folder_path)`

*   **Purpose:** (Static method) Finds the main HEC-RAS project file (`.prj`) within a folder using various heuristics.
*   **Parameters:**
    *   `folder_path` (`str` or `Path`): Path to the folder to search.
*   **Returns:** `Path` object for the found `.prj` file, or `None` if not found.

### `RasPrj.get_project_name()`

*   **Purpose:** Gets the name of the initialized HEC-RAS project (filename without extension).
*   **Parameters:** None.
*   **Returns:** (`str`): The project name.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_prj_entries(entry_type)`

*   **Purpose:** Retrieves entries (plans, flows, geoms, unsteady) listed in the project file (`.prj`).
*   **Parameters:**
    *   `entry_type` (`str`): Type of entry ('Plan', 'Flow', 'Unsteady', 'Geom').
*   **Returns:** `pd.DataFrame`: DataFrame containing information about the specified entry type found in the project.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_plan_entries()`

*   **Purpose:** Retrieves all plan file entries (`.p*`) listed in the project file.
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: DataFrame of plan entries with details parsed from plan files.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_flow_entries()`

*   **Purpose:** Retrieves all steady flow file entries (`.f*`) listed in the project file.
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: DataFrame of steady flow entries.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_unsteady_entries()`

*   **Purpose:** Retrieves all unsteady flow file entries (`.u*`) listed in the project file.
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: DataFrame of unsteady flow entries with details parsed from unsteady files.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_geom_entries()`

*   **Purpose:** Retrieves all geometry file entries (`.g*`) listed in the project file.
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: DataFrame of geometry entries including paths to associated `.hdf` files.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_hdf_entries()`

*   **Purpose:** Retrieves plan entries that have a corresponding HDF results file (`.p*.hdf`).
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: Filtered DataFrame of plan entries with existing HDF results files.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.print_data()`

*   **Purpose:** Prints a summary of the initialized project data (paths, file counts, dataframes) to the log (INFO level).
*   **Parameters:** None.
*   **Returns:** `None`.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj.get_plan_value(plan_number_or_path, key, ras_object=None)`

*   **Purpose:** (Static method, but often called on instance) Retrieves a specific value for a given key from a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number (e.g., "01") or full path to the plan file.
    *   `key` (`str`): The keyword in the plan file (e.g., 'Computation Interval', 'Short Identifier').
    *   `ras_object` (`RasPrj`, optional): Instance to use context from (project path). Defaults to global `ras`.
*   **Returns:** (`Any`): The value associated with the key, or `None` if not found. Type depends on the key (str, int).
*   **Raises:** `ValueError` if plan file not found, `IOError` on read error.

### `RasPrj.get_boundary_conditions()`

*   **Purpose:** Parses all unsteady flow files in the project to extract and structure boundary condition information.
*   **Parameters:** None.
*   **Returns:** `pd.DataFrame`: DataFrame containing detailed boundary condition data (location, type, parameters, associated unsteady file info). Returns empty DataFrame if no unsteady files or boundaries are found.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPrj` Attributes

*   `project_folder` (`Path`): Path to the project folder.
*   `project_name` (`str`): Name of the project.
*   `prj_file` (`Path`): Path to the project file.
*   `ras_exe_path` (`str`): Path to the HEC-RAS executable.
*   `plan_df` (`pd.DataFrame`): DataFrame containing plan file information.
*   `flow_df` (`pd.DataFrame`): DataFrame containing flow file information.
*   `unsteady_df` (`pd.DataFrame`): DataFrame containing unsteady flow file information.
*   `geom_df` (`pd.DataFrame`): DataFrame containing geometry file information.
*   `boundaries_df` (`pd.DataFrame`): DataFrame containing boundary condition information.
*   `rasmap_df` (`pd.DataFrame`): DataFrame containing RASMapper configuration data including paths to terrain, soil layer, infiltration, and land cover data.
*   `is_initialized` (`bool`): Read-only property indicating whether the RasPrj instance has been properly initialized with project data.

---

## Standalone Functions

These functions are available directly under the `ras_commander` import.

### `init_ras_project(ras_project_folder, ras_version=None, ras_object=None)`

*   **Purpose:** Primary function to initialize a `RasPrj` object (either global `ras` or a custom instance) for a specific HEC-RAS project.
*   **Parameters:**
    *   `ras_project_folder` (`str` or `Path`): Path to the HEC-RAS project folder.
    *   `ras_version` (`str`, optional): HEC-RAS version (e.g., "6.6") or full path to `Ras.exe`. Defaults to auto-detection or global setting.
    *   `ras_object` (`RasPrj`, optional): If `None`, initializes the global `ras` object. If a `RasPrj` instance, initializes that instance. If any other value (e.g., a string like "new"), creates and returns a *new* `RasPrj` instance. **Also updates the global `ras` object regardless.**
*   **Returns:** (`RasPrj`): The initialized `RasPrj` instance (either the one passed in, the global `ras`, or a newly created one).
*   **Raises:** `FileNotFoundError` if folder doesn't exist, `ValueError` if `.prj` file not found.

### `get_ras_exe(ras_version=None)`

*   **Purpose:** Determines the full path to the HEC-RAS executable based on version number or explicit path.
*   **Parameters:**
    *   `ras_version` (`str`, optional): Version string (e.g., "6.5") or full path to `Ras.exe`. If `None`, uses global `ras` object's path or defaults to "Ras.exe".
*   **Returns:** (`str`): Full path to the `Ras.exe` executable. Returns "Ras.exe" if lookup fails.

---

## Class: RasPlan

Contains static methods for operating on HEC-RAS plan files (`.p*`). Assumes a `RasPrj` object (defaulting to global `ras`) is initialized for context.

### `RasPlan.set_geom(plan_number, new_geom, ras_object=None)`

*   **Purpose:** Updates a plan file to use a different geometry file.
*   **Parameters:**
    *   `plan_number` (`str` or `int`): Plan number to modify (e.g., "01", 1).
    *   `new_geom` (`str` or `int`): Geometry number to assign (e.g., "02", 2).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `pd.DataFrame`: The updated *geometry* DataFrame of the `ras_object`.
*   **Raises:** `ValueError` if `new_geom` not found, `FileNotFoundError`, `IOError`.

### `RasPlan.set_steady(plan_number, new_steady_flow_number, ras_object=None)`

*   **Purpose:** Updates a plan file to use a specific steady flow file.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number (e.g., "01").
    *   `new_steady_flow_number` (`str`): Steady flow number (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `ValueError` if `new_steady_flow_number` not found, `FileNotFoundError`, `IOError`.

### `RasPlan.set_unsteady(plan_number, new_unsteady_flow_number, ras_object=None)`

*   **Purpose:** Updates a plan file to use a specific unsteady flow file.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number (e.g., "01").
    *   `new_unsteady_flow_number` (`str`): Unsteady flow number (e.g., "02").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `ValueError` if `new_unsteady_flow_number` not found, `FileNotFoundError`, `IOError`.

### `RasPlan.set_num_cores(plan_number_or_path, num_cores, ras_object=None)`

*   **Purpose:** Sets the number of cores (`UNET D1 Cores`, `UNET D2 Cores`, `PS Cores`) in a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `num_cores` (`int`): Number of cores to set (0 for 'All Available').
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `FileNotFoundError`, `IOError`.

### `RasPlan.set_geom_preprocessor(file_path, run_htab, use_ib_tables, ras_object=None)`

*   **Purpose:** Modifies the `Run HTab` and `UNET Use Existing IB Tables` settings in a plan file.
*   **Parameters:**
    *   `file_path` (`str` or `Path`): Full path to the plan file.
    *   `run_htab` (`int`): `0` (use existing) or `-1` (force recompute).
    *   `use_ib_tables` (`int`): `0` (use existing) or `-1` (force recompute).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `ValueError` for invalid flag values, `FileNotFoundError`, `IOError`.

### `RasPlan.clone_plan(template_plan, new_plan_shortid=None, ras_object=None)`

*   **Purpose:** Creates a new plan file by copying a template plan, assigns the next available plan number, optionally updates the Short Identifier, and updates the project file.
*   **Parameters:**
    *   `template_plan` (`str`): Plan number to use as template (e.g., "01").
    *   `new_plan_shortid` (`str`, optional): New Short Identifier (max 24 chars). If `None`, appends "_copy".
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The number of the newly created plan (e.g., "03").
*   **Raises:** `FileNotFoundError` if template not found, `IOError`.

### `RasPlan.clone_unsteady(template_unsteady, ras_object=None)`

*   **Purpose:** Creates a new unsteady flow file (`.u*` and associated `.hdf`) by copying a template, assigns the next available number, and updates the project file.
*   **Parameters:**
    *   `template_unsteady` (`str`): Unsteady flow number to use as template (e.g., "02").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The number of the newly created unsteady flow file (e.g., "03").
*   **Raises:** `FileNotFoundError` if template not found, `IOError`.

### `RasPlan.clone_steady(template_flow, ras_object=None)`

*   **Purpose:** Creates a new steady flow file (`.f*`) by copying a template, assigns the next available number, and updates the project file.
*   **Parameters:**
    *   `template_flow` (`str`): Steady flow number to use as template (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The number of the newly created steady flow file (e.g., "02").
*   **Raises:** `FileNotFoundError` if template not found, `IOError`.

### `RasPlan.clone_geom(template_geom, ras_object=None)`

*   **Purpose:** Creates a new geometry file (`.g*` and associated `.hdf`) by copying a template, assigns the next available number, and updates the project file.
*   **Parameters:**
    *   `template_geom` (`str`): Geometry number to use as template (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The number of the newly created geometry file (e.g., "03").
*   **Raises:** `FileNotFoundError` if template not found, `IOError`.

### `RasPlan.get_next_number(existing_numbers)`

*   **Purpose:** (Static utility) Finds the smallest unused positive integer number given a list of existing numbers (as strings), returned as a zero-padded string.
*   **Parameters:**
    *   `existing_numbers` (`list` of `str`): List of existing numbers (e.g., ['01', '03']).
*   **Returns:** (`str`): The next available number (e.g., "02").

### `RasPlan.get_plan_value(plan_number_or_path, key, ras_object=None)`

*   **Purpose:** Retrieves a specific value for a given key from a plan file. (See also `RasPrj.get_plan_value`).
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `key` (`str`): Keyword in the plan file (e.g., 'Computation Interval').
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`Any`): The value associated with the key, or `None` if not found. Type depends on the key.
*   **Raises:** `ValueError` if plan file not found, `IOError`.

### `RasPlan.get_results_path(plan_number, ras_object=None)`

*   **Purpose:** Gets the expected path to the HDF results file (`.p*.hdf`) for a given plan number. Checks if the file exists.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str` or `None`): Full path to the HDF results file if it exists, otherwise `None`.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPlan.get_plan_path(plan_number, ras_object=None)`

*   **Purpose:** Gets the full path to a plan file (`.p*`) given its number.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str` or `None`): Full path to the plan file, or `None` if not found in the project.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPlan.get_flow_path(flow_number, ras_object=None)`

*   **Purpose:** Gets the full path to a steady flow file (`.f*`) given its number.
*   **Parameters:**
    *   `flow_number` (`str`): Steady flow number (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str` or `None`): Full path to the flow file, or `None` if not found.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPlan.get_unsteady_path(unsteady_number, ras_object=None)`

*   **Purpose:** Gets the full path to an unsteady flow file (`.u*`) given its number.
*   **Parameters:**
    *   `unsteady_number` (`str`): Unsteady flow number (e.g., "02").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str` or `None`): Full path to the unsteady file, or `None` if not found.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPlan.get_geom_path(geom_number, ras_object=None)`

*   **Purpose:** Gets the full path to a geometry file (`.g*`) given its number.
*   **Parameters:**
    *   `geom_number` (`str`): Geometry number (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str` or `None`): Full path to the geometry file, or `None` if not found.
*   **Raises:** `RuntimeError` if not initialized.

### `RasPlan.update_run_flags(plan_number_or_path, geometry_preprocessor=None, unsteady_flow_simulation=None, run_sediment=None, post_processor=None, floodplain_mapping=None, ras_object=None)`

*   **Purpose:** Updates the run flags (e.g., `Run HTab`, `Run UNet`, `Run RASMapper`) in a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `geometry_preprocessor` (`bool`, optional): Set `Run HTab` (True=1, False=0).
    *   `unsteady_flow_simulation` (`bool`, optional): Set `Run UNet` (True=1, False=0).
    *   `run_sediment` (`bool`, optional): Set `Run Sediment` (True=1, False=0).
    *   `post_processor` (`bool`, optional): Set `Run PostProcess` (True=1, False=0).
    *   `floodplain_mapping` (`bool`, optional): Set `Run RASMapper` (True=0, False=-1). **Note inverted logic for RASMapper**.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.update_plan_intervals(plan_number_or_path, computation_interval=None, output_interval=None, instantaneous_interval=None, mapping_interval=None, ras_object=None)`

*   **Purpose:** Updates time intervals (computation, output, mapping, etc.) in a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `computation_interval` (`str`, optional): E.g., "1MIN", "10SEC", "1HOUR".
    *   `output_interval` (`str`, optional): E.g., "1HOUR", "30MIN".
    *   `instantaneous_interval` (`str`, optional): E.g., "1HOUR", "15MIN".
    *   `mapping_interval` (`str`, optional): E.g., "1HOUR", "15MIN".
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file.
*   **Raises:** `ValueError` if plan not found or interval invalid, `IOError`.

### `RasPlan.update_plan_description(plan_number_or_path, description, ras_object=None)`

*   **Purpose:** Updates the multi-line description block within a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `description` (`str`): The new description text (can be multi-line).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.read_plan_description(plan_number_or_path, ras_object=None)`

*   **Purpose:** Reads the multi-line description block from a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The description text, or "" if not found.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.update_simulation_date(plan_number_or_path, start_date, end_date, ras_object=None)`

*   **Purpose:** Updates the simulation start and end date/time in a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `start_date` (`datetime`): Simulation start datetime object.
    *   `end_date` (`datetime`): Simulation end datetime object.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and updates the `ras_object`.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.get_shortid(plan_number_or_path, ras_object=None)`

*   **Purpose:** Gets the 'Short Identifier' value from a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The Short Identifier, or "" if not found.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.set_shortid(plan_number_or_path, new_shortid, ras_object=None)`

*   **Purpose:** Sets the 'Short Identifier' value in a plan file (max 24 chars).
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `new_shortid` (`str`): New identifier (will be truncated if > 24 chars).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.get_plan_title(plan_number_or_path, ras_object=None)`

*   **Purpose:** Gets the 'Plan Title' value from a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`str`): The Plan Title, or "" if not found.
*   **Raises:** `ValueError` if plan not found, `IOError`.

### `RasPlan.set_plan_title(plan_number_or_path, new_title, ras_object=None)`

*   **Purpose:** Sets the 'Plan Title' value in a plan file.
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `new_title` (`str`): New title.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file.
*   **Raises:** `ValueError` if plan not found, `IOError`.

---

## Class: RasGeo

Contains static methods for operating on HEC-RAS geometry files (`.g*`) and associated preprocessor files. Assumes a `RasPrj` object (defaulting to global `ras`) is initialized.

### `RasGeo.clear_geompre_files(plan_files=None, ras_object=None)`

*   **Purpose:** Deletes geometry preprocessor files (`.c*`) associated with specified plan files. This forces HEC-RAS to recompute hydraulic tables based on the geometry. **Note:** Does not currently clear IB tables or HDF geometry tables.
*   **Parameters:**
    *   `plan_files` (`str`, `Path`, `List[Union[str, Path]]`, optional): Plan file path(s) or number(s). If `None`, clears for all plans in the project.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Deletes files and updates the `ras_object`'s geometry DataFrame.
*   **Raises:** `PermissionError`, `OSError`.

### `RasGeo.get_mannings_baseoverrides(geom_file_path)`

*   **Purpose:** Reads the base Manning's n table from a HEC-RAS geometry file.
*   **Parameters:**
    *   `geom_file_path` (Input handled by `@standardize_input`): Path identifier for the geometry file (.g##).
*   **Returns:** `pd.DataFrame`: DataFrame with Table Number, Land Cover Name, and Base Manning's n Value.

### `RasGeo.get_mannings_regionoverrides(geom_file_path)`

*   **Purpose:** Reads the Manning's n region overrides from a HEC-RAS geometry file.
*   **Parameters:**
    *   `geom_file_path` (Input handled by `@standardize_input`): Path identifier for the geometry file (.g##).
*   **Returns:** `pd.DataFrame`: DataFrame with Table Number, Land Cover Name, MainChannel value, and Region Name.

### `RasGeo.set_mannings_baseoverrides(geom_file_path, mannings_data)`

*   **Purpose:** Writes base Manning's n values to a HEC-RAS geometry file.
*   **Parameters:**
    *   `geom_file_path` (Input handled by `@standardize_input`): Path identifier for the geometry file (.g##).
    *   `mannings_data` (`pd.DataFrame`): DataFrame with columns 'Table Number', 'Land Cover Name', and 'Base Manning\'s n Value'.
*   **Returns:** `bool`: True if successful.

### `RasGeo.set_mannings_regionoverrides(geom_file_path, mannings_data)`

*   **Purpose:** Writes regional Manning's n overrides to a HEC-RAS geometry file.
*   **Parameters:**
    *   `geom_file_path` (Input handled by `@standardize_input`): Path identifier for the geometry file (.g##).
    *   `mannings_data` (`pd.DataFrame`): DataFrame with columns 'Table Number', 'Land Cover Name', 'MainChannel', and 'Region Name'.
*   **Returns:** `bool`: True if successful.

---

## Class: RasUnsteady

Contains static methods for operating on HEC-RAS unsteady flow files (`.u*`). Assumes a `RasPrj` object (defaulting to global `ras`) is initialized.

### `RasUnsteady.update_flow_title(unsteady_file, new_title, ras_object=None)`

*   **Purpose:** Updates the 'Flow Title' line within an unsteady flow file (max 24 chars).
*   **Parameters:**
    *   `unsteady_file` (`str` or `Path`): Unsteady flow number or full path.
    *   `new_title` (`str`): The new title (will be truncated if > 24 chars).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the file and updates the `ras_object`.
*   **Raises:** `FileNotFoundError`, `PermissionError`, `IOError`.

### `RasUnsteady.update_restart_settings(unsteady_file, use_restart, restart_filename=None, ras_object=None)`

*   **Purpose:** Enables or disables the use of a restart file (`.rst`) in an unsteady flow file.
*   **Parameters:**
    *   `unsteady_file` (`str` or `Path`): Unsteady flow number or full path.
    *   `use_restart` (`bool`): `True` to enable restart, `False` to disable.
    *   `restart_filename` (`str`, optional): Path to the `.rst` file (required if `use_restart` is `True`).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the file and updates the `ras_object`.
*   **Raises:** `ValueError` if `restart_filename` missing, `FileNotFoundError`, `PermissionError`, `IOError`.

### `RasUnsteady.extract_boundary_and_tables(unsteady_file, ras_object=None)`

*   **Purpose:** Parses an unsteady flow file to extract boundary condition definitions and associated time-series data tables (e.g., Flow Hydrograph).
*   **Parameters:**
    *   `unsteady_file` (`str` or `Path`): Unsteady flow number or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `pd.DataFrame`: DataFrame where each row represents a boundary condition. Includes columns for location (`River Name`, `Reach Name`, etc.), `DSS File`, and a `Tables` column containing a dictionary of `pd.DataFrame` objects for each time-series table found.
*   **Raises:** `FileNotFoundError`, `PermissionError`.

### `RasUnsteady.print_boundaries_and_tables(boundaries_df)`

*   **Purpose:** Prints the boundary conditions and tables (extracted by `extract_boundary_and_tables`) to the console in a readable format.
*   **Parameters:**
    *   `boundaries_df` (`pd.DataFrame`): DataFrame returned by `extract_boundary_and_tables`.
*   **Returns:** `None`.

### `RasUnsteady.identify_tables(lines)`

*   **Purpose:** (Static utility) Scans lines from an unsteady file and identifies the name and line ranges of data tables.
*   **Parameters:**
    *   `lines` (`List[str]`): List of lines read from the unsteady file.
*   **Returns:** `List[Tuple[str, int, int]]`: List of tuples `(table_name, start_line_index, end_line_index)`.

### `RasUnsteady.parse_fixed_width_table(lines, start, end)`

*   **Purpose:** (Static utility) Parses the fixed-width numeric data within identified table lines.
*   **Parameters:**
    *   `lines` (`List[str]`): List of lines read from the unsteady file.
    *   `start` (`int`): Starting line index (inclusive) of the table data.
    *   `end` (`int`): Ending line index (exclusive) of the table data.
*   **Returns:** `pd.DataFrame`: DataFrame with a single 'Value' column containing the numeric data.

### `RasUnsteady.extract_tables(unsteady_file, ras_object=None)`

*   **Purpose:** Extracts all numeric data tables (like hydrographs, gate openings) from an unsteady file into a dictionary of DataFrames.
*   **Parameters:**
    *   `unsteady_file` (`str` or `Path`): Unsteady flow number or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `Dict[str, pd.DataFrame]`: Dictionary mapping table names (e.g., 'Flow Hydrograph=') to DataFrames containing the table values.
*   **Raises:** `FileNotFoundError`, `PermissionError`.

### `RasUnsteady.write_table_to_file(unsteady_file, table_name, df, start_line, ras_object=None)`

*   **Purpose:** Writes a modified DataFrame back into an unsteady flow file, formatting it correctly into the fixed-width structure required by HEC-RAS.
*   **Parameters:**
    *   `unsteady_file` (`str` or `Path`): Unsteady flow number or full path.
    *   `table_name` (`str`): Name of the table being written (must match the header in the file).
    *   `df` (`pd.DataFrame`): DataFrame containing the new values (must have a 'Value' column).
    *   `start_line` (`int`): Line index where the original table data started.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the file.
*   **Raises:** `FileNotFoundError`, `PermissionError`, `IOError`.

---

## Class: RasUtils

Contains general static utility functions used across the `ras_commander` library.

### `RasUtils.create_directory(directory_path, ras_object=None)`

*   **Purpose:** Ensures a directory exists, creating it (and any parent directories) if necessary.
*   **Parameters:**
    *   `directory_path` (`Path`): The directory path to ensure.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`Path`): The ensured directory path.
*   **Raises:** `OSError` on creation failure.

### `RasUtils.find_files_by_extension(extension, ras_object=None)`

*   **Purpose:** Lists all files within the initialized project directory matching a specific extension.
*   **Parameters:**
    *   `extension` (`str`): The file extension (e.g., '.prj', '.p*').
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`list` of `str`): List of full file paths.

### `RasUtils.get_file_size(file_path, ras_object=None)`

*   **Purpose:** Gets the size of a file in bytes.
*   **Parameters:**
    *   `file_path` (`Path`): Path to the file.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`int` or `None`): File size in bytes, or `None` if file not found.

### `RasUtils.get_file_modification_time(file_path, ras_object=None)`

*   **Purpose:** Gets the last modification timestamp of a file.
*   **Parameters:**
    *   `file_path` (`Path`): Path to the file.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`float` or `None`): Unix timestamp of last modification, or `None` if file not found.

### `RasUtils.get_plan_path(current_plan_number_or_path, ras_object=None)`

*   **Purpose:** Resolves a plan number or path string into a full, validated `Path` object for a plan file.
*   **Parameters:**
    *   `current_plan_number_or_path` (`str` or `Path`): Plan number (1-99) or full path.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`Path`): The validated path to the plan file.
*   **Raises:** `ValueError`, `TypeError`, `FileNotFoundError`.

### `RasUtils.remove_with_retry(path, max_attempts=5, initial_delay=1.0, is_folder=True, ras_object=None)`

*   **Purpose:** Safely removes a file or folder, retrying with exponential backoff if a `PermissionError` occurs.
*   **Parameters:**
    *   `path` (`Path`): Path to remove.
    *   `max_attempts` (`int`, optional): Max removal attempts. Default is 5.
    *   `initial_delay` (`float`, optional): Initial delay in seconds. Default is 1.0.
    *   `is_folder` (`bool`, optional): `True` if path is a folder, `False` if a file. Default is `True`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** (`bool`): `True` if removal succeeded, `False` otherwise.

### `RasUtils.update_plan_file(plan_number_or_path, file_type, entry_number, ras_object=None)`

*   **Purpose:** Updates a line in a plan file to reference a different associated file (geometry, flow, unsteady).
*   **Parameters:**
    *   `plan_number_or_path` (`str` or `Path`): Plan number or full path.
    *   `file_type` (`str`): Type of file link to update ('Geom', 'Flow', 'Unsteady').
    *   `entry_number` (`int`): The number (1-99) of the new associated file.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the plan file and refreshes the `ras_object`.
*   **Raises:** `ValueError`, `FileNotFoundError`.

### `RasUtils.check_file_access(file_path, mode='r')`

*   **Purpose:** Verifies if a file exists and can be accessed with the specified mode ('r', 'w', etc.).
*   **Parameters:**
    *   `file_path` (`Path`): Path to the file.
    *   `mode` (`str`, optional): Access mode to check. Default is 'r'.
*   **Returns:** `None`.
*   **Raises:** `FileNotFoundError`, `PermissionError`.

### `RasUtils.convert_to_dataframe(data_source, **kwargs)`

*   **Purpose:** Converts various inputs (existing DataFrame, CSV, Excel, TSV, Parquet file path) into a pandas DataFrame.
*   **Parameters:**
    *   `data_source` (`pd.DataFrame` or `Path`): Input data or file path.
    *   `**kwargs`: Additional arguments for pandas read functions (e.g., `sheet_name` for Excel).
*   **Returns:** `pd.DataFrame`.
*   **Raises:** `NotImplementedError` for unsupported types.

### `RasUtils.save_to_excel(dataframe, excel_path, **kwargs)`

*   **Purpose:** Saves a DataFrame to an Excel file, with retries to handle potential file locking issues.
*   **Parameters:**
    *   `dataframe` (`pd.DataFrame`): DataFrame to save.
    *   `excel_path` (`Path`): Output Excel file path.
    *   `**kwargs`: Additional arguments for `DataFrame.to_excel()`.
*   **Returns:** `None`.
*   **Raises:** `IOError` if saving fails after retries.

### `RasUtils.calculate_rmse(observed_values, predicted_values, normalized=True)`

*   **Purpose:** Calculates Root Mean Squared Error (RMSE), optionally normalized.
*   **Parameters:**
    *   `observed_values` (`np.ndarray`): Array of actual values.
    *   `predicted_values` (`np.ndarray`): Array of predicted values.
    *   `normalized` (`bool`, optional): If `True`, normalize by the mean of observed values. Default is `True`.
*   **Returns:** (`float`): Calculated RMSE.

### `RasUtils.calculate_percent_bias(observed_values, predicted_values, as_percentage=False)`

*   **Purpose:** Calculates Percent Bias (PBIAS).
*   **Parameters:**
    *   `observed_values` (`np.ndarray`): Array of actual values.
    *   `predicted_values` (`np.ndarray`): Array of predicted values.
    *   `as_percentage` (`bool`, optional): If `True`, returns result multiplied by 100. Default is `False`.
*   **Returns:** (`float`): Calculated Percent Bias.

### `RasUtils.calculate_error_metrics(observed_values, predicted_values)`

*   **Purpose:** Calculates a dictionary of common error metrics (correlation, RMSE, Percent Bias).
*   **Parameters:**
    *   `observed_values` (`np.ndarray`): Array of actual values.
    *   `predicted_values` (`np.ndarray`): Array of predicted values.
*   **Returns:** `Dict[str, float]`: Dictionary with keys 'cor', 'rmse', 'pb'.

### `RasUtils.update_file(file_path, update_function, *args)`

*   **Purpose:** Generic function to read a file, apply a modification function to its lines, and write it back.
*   **Parameters:**
    *   `file_path` (`Path`): Path to the file.
    *   `update_function` (`Callable`): A function that takes a list of lines (and optionally `*args`) and returns a modified list of lines.
    *   `*args`: Additional arguments passed to `update_function`.
*   **Returns:** `None`.
*   **Raises:** Exceptions from file I/O or `update_function`.

### `RasUtils.get_next_number(existing_numbers)`

*   **Purpose:** Finds the smallest unused positive integer number given a list of existing numbers (as strings), returned as a zero-padded string. (Same as `RasPlan.get_next_number`)
*   **Parameters:**
    *   `existing_numbers` (`list` of `str`): List of existing numbers (e.g., ['01', '03']).
*   **Returns:** (`str`): The next available number (e.g., "02").

### `RasUtils.clone_file(template_path, new_path, update_function=None, *args)`

*   **Purpose:** Copies a template file to a new path and optionally applies a modification function to the new file's content.
*   **Parameters:**
    *   `template_path` (`Path`): Path to the source file.
    *   `new_path` (`Path`): Path for the new copied file.
    *   `update_function` (`Callable`, optional): Function to modify the lines of the new file. Takes a list of lines (and optionally `*args`).
    *   `*args`: Additional arguments for `update_function`.
*   **Returns:** `None`.
*   **Raises:** `FileNotFoundError` if template doesn't exist.

### `RasUtils.update_project_file(prj_file, file_type, new_num, ras_object=None)`

*   **Purpose:** Appends a new file entry line (e.g., `Plan File=p03`) to the project file (`.prj`).
*   **Parameters:**
    *   `prj_file` (`Path`): Path to the `.prj` file.
    *   `file_type` (`str`): Type of entry ('Plan', 'Geom', 'Flow', 'Unsteady').
    *   `new_num` (`str`): The two-digit number for the new entry (e.g., "03").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`. Modifies the project file.

### `RasUtils.decode_byte_strings(dataframe)`

*   **Purpose:** Decodes all byte string (`b'...'`) columns in a DataFrame to UTF-8 strings.
*   **Parameters:**
    *   `dataframe` (`pd.DataFrame`): Input DataFrame.
*   **Returns:** `pd.DataFrame`: DataFrame with byte strings decoded.

### `RasUtils.perform_kdtree_query(reference_points, query_points, max_distance=2.0)`

*   **Purpose:** Finds the nearest point in `reference_points` for each point in `query_points` using KDTree, within a maximum distance.
*   **Parameters:**
    *   `reference_points` (`np.ndarray`): NxD array of reference points.
    *   `query_points` (`np.ndarray`): MxD array of query points.
    *   `max_distance` (`float`, optional): Maximum distance for a match. Default 2.0.
*   **Returns:** (`np.ndarray`): Array of length M containing indices of nearest reference points. Index is -1 if no point found within `max_distance`.

### `RasUtils.find_nearest_neighbors(points, max_distance=2.0)`

*   **Purpose:** Finds the nearest neighbor for each point within the same dataset using KDTree, excluding self-matches and points beyond `max_distance`.
*   **Parameters:**
    *   `points` (`np.ndarray`): NxD array of points.
    *   `max_distance` (`float`, optional): Maximum distance for a match. Default 2.0.
*   **Returns:** (`np.ndarray`): Array of length N containing indices of the nearest neighbor for each point. Index is -1 if no neighbor found within `max_distance`.

### `RasUtils.consolidate_dataframe(dataframe, group_by=None, pivot_columns=None, level=None, n_dimensional=False, aggregation_method='list')`

*   **Purpose:** Aggregates rows in a DataFrame based on grouping criteria, typically merging values into lists.
*   **Parameters:**
    *   `dataframe` (`pd.DataFrame`): Input DataFrame.
    *   `group_by` (`str` or `List[str]`, optional): Column(s) or index level(s) to group by.
    *   `pivot_columns` (`str` or `List[str]`, optional): Column(s) to use for pivoting (if `n_dimensional`).
    *   `level` (`int`, optional): Index level to group by.
    *   `n_dimensional` (`bool`, optional): Use `pivot_table` if `True`. Default `False`.
    *   `aggregation_method` (`str` or `Callable`, optional): How to aggregate ('list', 'sum', 'mean', etc.). Default 'list'.
*   **Returns:** `pd.DataFrame`: The consolidated DataFrame.

### `RasUtils.find_nearest_value(array, target_value)`

*   **Purpose:** Finds the element in an array that is numerically closest to a target value.
*   **Parameters:**
    *   `array` (`list` or `np.ndarray`): Array of numbers to search within.
    *   `target_value` (`int` or `float`): The value to find the nearest match for.
*   **Returns:** (`int` or `float`): The value from the array closest to `target_value`.

### `RasUtils.horizontal_distance(coord1, coord2)`

*   **Purpose:** Calculates the 2D Euclidean distance between two points.
*   **Parameters:**
    *   `coord1` (`np.ndarray`): [X, Y] coordinates of the first point.
    *   `coord2` (`np.ndarray`): [X, Y] coordinates of the second point.
*   **Returns:** (`float`): The horizontal distance.

---

## Class: RasExamples

Provides methods to download, manage, and access HEC-RAS example projects included with the official HEC-RAS releases. Useful for testing and demonstration.

### `RasExamples.get_example_projects(version_number='6.6')`

*   **Purpose:** Downloads the example projects zip file for a specific HEC-RAS version if it doesn't already exist locally. Initializes the class to read the zip file structure.
*   **Parameters:**
    *   `version_number` (`str`, optional): HEC-RAS version string (e.g., "6.6", "6.5"). Default is "6.6".
*   **Returns:** (`Path`): Path to the directory where projects will be extracted (`example_projects`).
*   **Raises:** `ValueError` for invalid version, `requests.exceptions.RequestException` on download failure.

### `RasExamples.list_categories()`

*   **Purpose:** Lists the categories (top-level folders) available in the example projects zip file.
*   **Parameters:** None.
*   **Returns:** (`List[str]`): List of category names.

### `RasExamples.list_projects(category=None)`

*   **Purpose:** Lists the project names available, optionally filtered by category.
*   **Parameters:**
    *   `category` (`str`, optional): If provided, lists projects only within this category.
*   **Returns:** (`List[str]`): List of project names.

### `RasExamples.extract_project(project_names, output_path=None)`

*   **Purpose:** Extracts one or more specified projects from the zip file. Overwrites if already extracted.
*   **Parameters:**
    *   `project_names` (`str` or `List[str]`): Name(s) of the project(s) to extract.
    *   `output_path` (`str` or `Path`, optional): Path where the project folder will be placed. Can be a relative path (creates subfolder in current directory) or an absolute path. If `None`, uses default `example_projects` folder.
*   **Returns:** (`Path` or `List[Path]`): Path(s) to the extracted project folder(s). Returns a single `Path` if one name was given, a list otherwise.
*   **Raises:** `ValueError` if a project name is not found.

### `RasExamples.is_project_extracted(project_name)`

*   **Purpose:** Checks if a specific project has already been extracted into the `example_projects` directory.
*   **Parameters:**
    *   `project_name` (`str`): Name of the project to check.
*   **Returns:** (`bool`): `True` if the project folder exists, `False` otherwise.

### `RasExamples.clean_projects_directory()`

*   **Purpose:** Removes the entire `example_projects` directory and its contents, then recreates the empty directory.
*   **Parameters:** None.
*   **Returns:** `None`.

### `RasExamples.download_fema_ble_model(huc8, output_dir=None)`

*   **Purpose:** (Placeholder) Intended to download FEMA Base Level Engineering models. *Currently not implemented.*
*   **Parameters:**
    *   `huc8` (`str`): 8-digit HUC code.
    *   `output_dir` (`str`, optional): Directory to save files.
*   **Returns:** (`str`): Path to the extracted model directory.

---

## Class: RasControl

Provides legacy HEC-RAS version support via the HECRASController COM interface. Wraps the COM API with ras-commander style conventions (plan numbers instead of file paths). Supports HEC-RAS versions 3.1, 4.1, 5.0.x (501-507), 6.0, 6.3, 6.6. **Requires version specification when initializing project with `init_ras_project()`.**

### Key Features

*   **Plan Number Interface**: Use plan numbers (e.g., "02") instead of file paths
*   **Auto-sets Current Plan**: Automatically sets the current plan before operations
*   **Steady & Unsteady Support**: Extract both steady state profiles and unsteady time series
*   **Open-Operate-Close Pattern**: Opens HEC-RAS, performs operation, closes completely (no GUI left open)
*   **Blocking Execution**: `run_plan()` waits for computation to complete before returning
*   **Version Migration**: Perfect for validating model migration across HEC-RAS versions

### `RasControl.run_plan(plan_number, ras_object=None)`

*   **Purpose:** Runs a HEC-RAS plan using the COM interface. Automatically sets the plan as current, starts computation, waits for completion, and closes HEC-RAS.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number to run (e.g., "01", "02").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`. **Must be initialized with a version string** (e.g., `init_ras_project(path, "4.1")`).
*   **Returns:** `Tuple[bool, List[str]]`: `(success, messages)` where `success` is `True` if computation completed, `messages` is a list of computation messages from HEC-RAS.
*   **Raises:** `RuntimeError` if RAS not initialized with version, `ValueError` if plan not found, `Exception` from COM interface errors.
*   **Note:** Blocks until computation completes. Terminates any remaining ras.exe processes after closing.

### `RasControl.get_steady_results(plan_number, ras_object=None)`

*   **Purpose:** Extracts steady state profile results (WSE, velocity, flow, etc.) from a completed HEC-RAS plan using the COM interface.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number to extract results from (e.g., "02").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `pd.DataFrame`: DataFrame with columns: `river`, `reach`, `node_id`, `profile`, `wsel`, `min_ch_el`, `velocity`, `flow`, `froude`, `energy`, `max_depth`. One row per cross-section per profile.
*   **Raises:** `RuntimeError` if RAS not initialized with version, `ValueError` if plan not found or is not steady, `Exception` from COM interface errors.
*   **Note:** Automatically sets the plan as current before extraction. Closes HEC-RAS after extraction.

### `RasControl.get_unsteady_results(plan_number, max_times=None, ras_object=None)`

*   **Purpose:** Extracts unsteady time series results from a completed HEC-RAS plan using the COM interface. Includes special "Max WS" timestep containing maximum values from any computational timestep.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number to extract results from (e.g., "01").
    *   `max_times` (`int`, optional): Maximum number of timesteps to extract. If `None`, extracts all output times. **Note:** This limits extracted timesteps, not computational timesteps.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `pd.DataFrame`: DataFrame with columns: `river`, `reach`, `node_id`, `time_index`, `time_string`, `wsel`, `min_ch_el`, `velocity`, `flow`, `froude`, `energy`, `max_depth`. First row (time_index=1) is always "Max WS" containing peak values from entire simulation.
*   **Raises:** `RuntimeError` if RAS not initialized with version, `ValueError` if plan not found or is not unsteady, `Exception` from COM interface errors.
*   **Note:** Automatically sets the plan as current before extraction. Closes HEC-RAS after extraction. Filter `time_string != 'Max WS'` for time series plotting.

### `RasControl.get_output_times(plan_number, ras_object=None)`

*   **Purpose:** Retrieves the list of output times available for an unsteady plan.
*   **Parameters:**
    *   `plan_number` (`str`): Plan number to query (e.g., "01").
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `List[str]`: List of time strings (e.g., `["Max WS", "18FEB1999 0000", "18FEB1999 0200", ...]`). First entry is always "Max WS".
*   **Raises:** `RuntimeError` if RAS not initialized with version, `ValueError` if plan not found, `Exception` from COM interface errors.
*   **Note:** Automatically sets the plan as current. Closes HEC-RAS after query.

### `RasControl.set_current_plan(plan_title, ras_object=None)`

*   **Purpose:** Sets the current plan in HEC-RAS by plan title (as shown in the GUI).
*   **Parameters:**
    *   `plan_title` (`str`): The "Plan Title" from the plan file (not the plan number or short ID).
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `None`.
*   **Raises:** `RuntimeError` if RAS not initialized with version, `ValueError` if plan title not found, `Exception` from COM interface errors.
*   **Note:** This is a low-level method. Most users should rely on automatic plan setting in `run_plan()`, `get_steady_results()`, and `get_unsteady_results()`.

### `RasControl.get_comp_msgs(plan, ras_object=None)`

*   **Purpose:** Extracts computation messages from .txt file with automatic fallback to HDF extraction. Computation messages contain detailed information about the computation process, including warnings, errors, convergence information, and performance metrics.
*   **Parameters:**
    *   `plan` (`str` or `Path`): Plan number (e.g., "01", "02") or path to .prj file.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `str`: String containing computation messages, or empty string if unavailable.
*   **Raises:** No exceptions raised. Returns empty string gracefully if messages unavailable.
*   **Version Support:**
    *   HEC-RAS 3.x-5.x: Reads from `.comp_msgs.txt` file
    *   HEC-RAS 6.x+: Reads from `.computeMsgs.txt` file
    *   Falls back to HDF extraction if .txt files not found
*   **Note:** This method checks for both .txt naming patterns and automatically falls back to HDF if neither exists. Logging messages (WARNING level) indicate when fallback occurs. Function naming follows legacy HECRASController conventions (`comp_msgs` abbreviation).

**Example:**
```python
from ras_commander import init_ras_project, RasControl

# Initialize project with legacy version
init_ras_project(r"C:/models/BaldEagle/BaldEagle.prj", "4.1")

# Extract computation messages
msgs = RasControl.get_comp_msgs("01")

if msgs:
    print("Computation Messages:")
    print(msgs)
else:
    print("No computation messages available")
```

### Version Support and Initialization

RasControl requires the HEC-RAS version to be specified when initializing a project:

```python
# Initialize with version string
init_ras_project(project_path, "4.1")     # HEC-RAS 4.1
init_ras_project(project_path, "5.0.6")   # HEC-RAS 5.0.6
init_ras_project(project_path, "6.6")     # HEC-RAS 6.6

# Flexible version formats accepted
init_ras_project(project_path, "41")      # Same as "4.1"
init_ras_project(project_path, "506")     # Same as "5.0.6"
init_ras_project(project_path, "66")      # Same as "6.6"
```

**Supported Versions:** 3.1, 4.1, 5.0.1-5.0.7, 6.0, 6.3, 6.6

### Understanding "Max WS" in Unsteady Results

When extracting unsteady results, the first row always contains `time_string="Max WS"` and `time_index=1`. This special timestep contains the **maximum values that occurred at ANY computational timestep** during the simulation, not just at output intervals.

**Why this matters:**
- Output intervals (e.g., every 1 hour) may miss the peak
- Computational timesteps (e.g., every 30 seconds) capture the true maximum
- "Max WS" provides the absolute peak values for the entire simulation

**Usage pattern:**
```python
# Extract unsteady results
df_unsteady = RasControl.get_unsteady_results("01", max_times=20)

# Separate Max WS from time series
max_ws = df_unsteady[df_unsteady['time_string'] == 'Max WS']
timeseries = df_unsteady[df_unsteady['time_string'] != 'Max WS']

# Plot time series with Max WS as reference
import matplotlib.pyplot as plt
xs_data = timeseries[timeseries['node_id'] == '12345']
plt.plot(xs_data['time_index'], xs_data['wsel'], label='WSE')
plt.axhline(max_ws[max_ws['node_id'] == '12345']['wsel'].iloc[0],
            color='r', linestyle='--', label='Max WS')
```

### When to Use RasControl vs RasCmdr

| Use RasControl | Use RasCmdr |
|----------------|-------------|
| HEC-RAS 3.x - 4.x | HEC-RAS 6.0+ |
| No HDF file support needed | Need HDF data access |
| Version migration validation | Modern workflows |
| Legacy model support | Better performance |
| Steady profile extraction | 2D mesh analysis |

For HEC-RAS 6.0+, prefer using HDF-based methods (`HdfResultsPlan`, `HdfResultsXsec`) for better performance and more detailed data access.

---

## Class: RasCmdr

Contains static methods for executing HEC-RAS simulations via command line interface. Assumes a `RasPrj` object (defaulting to global `ras`) is initialized.

### `RasCmdr.compute_plan(plan_number, dest_folder=None, ras_object=None, clear_geompre=False, num_cores=None, overwrite_dest=False)`

*   **Purpose:** Executes a single HEC-RAS plan computation using the command line. Optionally copies the project to a destination folder first.
*   **Parameters:**
    *   `plan_number` (`str` or `Path`): Plan number (e.g., "01") or full path to plan file.
    *   `dest_folder` (`str` or `Path`, optional): Folder name (relative to project parent) or full path for computation. If `None`, runs in the original project folder.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
    *   `clear_geompre` (`bool`, optional): Clear `.c*` files before running. Default `False`.
    *   `num_cores` (`int`, optional): Number of cores to set in the plan file before running. Default `None` (use plan's current setting).
    *   `overwrite_dest` (`bool`, optional): If `True`, overwrite `dest_folder` if it exists. Default `False`.
*   **Returns:** (`bool`): `True` if execution succeeded (process completed without error), `False` otherwise.
*   **Raises:** `ValueError` if `dest_folder` exists and `overwrite_dest` is False, `FileNotFoundError`, `PermissionError`, `subprocess.CalledProcessError`.

### `RasCmdr.compute_parallel(plan_number=None, max_workers=2, num_cores=2, clear_geompre=False, ras_object=None, dest_folder=None, overwrite_dest=False)`

*   **Purpose:** Executes multiple HEC-RAS plans in parallel by creating temporary worker copies of the project. Consolidates results into a final destination folder.
*   **Parameters:**
    *   `plan_number` (`str` or `List[str]`, optional): Plan number(s) to run. If `None`, runs all plans in the project.
    *   `max_workers` (`int`, optional): Max number of parallel HEC-RAS instances. Default 2.
    *   `num_cores` (`int`, optional): Cores assigned to *each* worker instance. Default 2.
    *   `clear_geompre` (`bool`, optional): Clear `.c*` files in worker folders. Default `False`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
    *   `dest_folder` (`str` or `Path`, optional): Final folder for consolidated results. If `None`, creates `ProjectName [Computed]` folder.
    *   `overwrite_dest` (`bool`, optional): Overwrite `dest_folder` if it exists. Default `False`.
*   **Returns:** `Dict[str, bool]`: Dictionary mapping plan numbers to their execution success status (`True`/`False`).
*   **Raises:** `ValueError`, `FileNotFoundError`, `PermissionError`, `RuntimeError`.

### `RasCmdr.compute_test_mode(plan_number=None, dest_folder_suffix="[Test]", clear_geompre=False, num_cores=None, ras_object=None, overwrite_dest=False)`

*   **Purpose:** Executes specified HEC-RAS plans sequentially within a dedicated test folder (a copy of the project).
*   **Parameters:**
    *   `plan_number` (`str` or `List[str]`, optional): Plan number(s) to run. If `None`, runs all plans.
    *   `dest_folder_suffix` (`str`, optional): Suffix for the test folder name (e.g., `ProjectName [Test]`). Default "[Test]".
    *   `clear_geompre` (`bool`, optional): Clear `.c*` files before running each plan. Default `False`.
    *   `num_cores` (`int`, optional): Cores to set for each plan execution. Default `None`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
    *   `overwrite_dest` (`bool`, optional): Overwrite test folder if it exists. Default `False`.
*   **Returns:** `Dict[str, bool]`: Dictionary mapping plan numbers to their execution success status (`True`/`False`).
*   **Raises:** `ValueError`, `FileNotFoundError`, `PermissionError`.

---

