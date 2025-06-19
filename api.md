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

### `RasExamples.extract_project(project_names)`

*   **Purpose:** Extracts one or more specified projects from the zip file into the `example_projects` directory. Overwrites if already extracted.
*   **Parameters:**
    *   `project_names` (`str` or `List[str]`): Name(s) of the project(s) to extract.
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

## Class: RasCmdr

Contains static methods for executing HEC-RAS simulations. Assumes a `RasPrj` object (defaulting to global `ras`) is initialized.

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

## Class: HdfBase

Contains fundamental static methods for interacting with HEC-RAS HDF files. Used by other `Hdf*` classes. Requires an open `h5py.File` object or uses `@standardize_input`.

### `HdfBase.get_simulation_start_time(hdf_file)`

*   **Purpose:** Extracts the simulation start time attribute from the Plan Information group.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
*   **Returns:** (`datetime`): Simulation start time.
*   **Raises:** `ValueError` if path not found or time parsing fails.

### `HdfBase.get_unsteady_timestamps(hdf_file)`

*   **Purpose:** Extracts the list of unsteady output timestamps (usually in milliseconds format) and converts them to datetime objects.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
*   **Returns:** `List[datetime]`: List of datetime objects for each output time step.

### `HdfBase.get_2d_flow_area_names_and_counts(hdf_path)`

*   **Purpose:** Gets the names and cell counts of all 2D Flow Areas defined in the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry HDF).
*   **Returns:** `List[Tuple[str, int]]`: List of tuples `(area_name, cell_count)`.
*   **Raises:** `ValueError` on read errors.

### `HdfBase.get_projection(hdf_path)`

*   **Purpose:** Retrieves the spatial projection information (WKT string) from the HDF file attributes or associated `.rasmap` file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** (`str` or `None`): Well-Known Text (WKT) string of the projection, or `None` if not found.

### `HdfBase.get_attrs(hdf_file, attr_path)`

*   **Purpose:** Retrieves all attributes from a specific group or dataset within the HDF file.
*   **Parameters:**
    *   `hdf_file` (`h5py.File`): Open HDF file object.
    *   `attr_path` (`str`): Internal HDF path to the group/dataset (e.g., "Plan Data/Plan Information").
*   **Returns:** `Dict[str, Any]`: Dictionary of attributes. Returns empty dict if path not found.

### `HdfBase.get_dataset_info(file_path, group_path='/')`

*   **Purpose:** Prints a recursive listing of the structure (groups, datasets, attributes, shapes, dtypes) within an HDF5 file, starting from `group_path`.
*   **Parameters:**
    *   `file_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
    *   `group_path` (`str`, optional): Internal HDF path to start exploration from. Default is root ('/').
*   **Returns:** `None`. Prints to console.

### `HdfBase.get_polylines_from_parts(hdf_path, path, info_name="Polyline Info", parts_name="Polyline Parts", points_name="Polyline Points")`

*   **Purpose:** Reconstructs Shapely LineString or MultiLineString geometries from HEC-RAS's standard polyline representation in HDF (using Info, Parts, Points datasets).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
    *   `path` (`str`): Internal HDF base path containing the polyline datasets (e.g., "Geometry/River Centerlines").
    *   `info_name` (`str`, optional): Name of the dataset containing polyline start/count info. Default "Polyline Info".
    *   `parts_name` (`str`, optional): Name of the dataset defining parts for multi-part lines. Default "Polyline Parts".
    *   `points_name` (`str`, optional): Name of the dataset containing all point coordinates. Default "Polyline Points".
*   **Returns:** `List[LineString or MultiLineString]`: List of reconstructed Shapely geometries.

### `HdfBase.print_attrs(name, obj)`

*   **Purpose:** Helper method to print the attributes of an HDF5 object (Group or Dataset) during exploration (used by `get_dataset_info`).
*   **Parameters:**
    *   `name` (`str`): Name of the HDF5 object.
    *   `obj` (`h5py.Group` or `h5py.Dataset`): The HDF5 object.
*   **Returns:** `None`. Prints to console.

---

## Class: HdfBndry

Contains static methods for extracting boundary-related *geometry* features (BC Lines, Breaklines, Refinement Regions, Reference Lines/Points) from HEC-RAS HDF files (typically geometry HDF). Returns GeoDataFrames.

### `HdfBndry.get_bc_lines(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Boundary Condition Lines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes (Name, SA-2D, Type, etc.).

### `HdfBndry.get_breaklines(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Break Lines. Skips invalid (zero-length, single-point) breaklines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString/MultiLineString geometries and attributes (bl_id, Name).

### `HdfBndry.get_refinement_regions(hdf_path)`

*   **Purpose:** Extracts 2D Flow Area Refinement Regions.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon/MultiPolygon geometries and attributes (rr_id, Name).

### `HdfBndry.get_reference_lines(hdf_path, mesh_name=None)`

*   **Purpose:** Extracts Reference Lines used for profile output, optionally filtering by mesh name.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
    *   `mesh_name` (`str`, optional): Filter results to this specific mesh area.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString/MultiLineString geometries and attributes (refln_id, Name, mesh_name, Type).

### `HdfBndry.get_reference_points(hdf_path, mesh_name=None)`

*   **Purpose:** Extracts Reference Points used for point output, optionally filtering by mesh name.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier (usually geometry HDF).
    *   `mesh_name` (`str`, optional): Filter results to this specific mesh area.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes (refpt_id, Name, mesh_name, Cell Index).

---

## Class: HdfFluvialPluvial

Contains static methods for analyzing fluvial-pluvial boundaries based on simulation results.

### `HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf_path, delta_t=12)`

*   **Purpose:** Calculates the boundary line between areas dominated by fluvial (riverine) vs. pluvial (rainfall/local) flooding, based on the timing difference of maximum water surface elevation between adjacent 2D cells. Attempts to join adjacent boundary segments.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF file.
    *   `delta_t` (`float`, optional): Time difference threshold in hours. Adjacent cells with max WSE time differences greater than this are considered part of the boundary. Default is 12.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing LineString geometries representing the calculated boundary. CRS matches the input HDF.
*   **Raises:** `ValueError` if required mesh or results data is missing.

---

## Class: HdfInfiltration

Contains static methods for handling infiltration data within HEC-RAS HDF files (typically geometry HDF).

### `HdfInfiltration.get_infiltration_baseoverrides(hdf_path: Path) -> Optional[pd.DataFrame]`

*   **Purpose:** Retrieves current infiltration parameters from a HEC-RAS geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Optional[pd.DataFrame]`: DataFrame containing infiltration parameters if successful, None if operation fails.

### `HdfInfiltration.get_infiltration_layer_data(hdf_path: Path) -> Optional[pd.DataFrame]`

*   **Purpose:** Retrieves current infiltration parameters from a HEC-RAS infiltration layer HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the infiltration layer HDF.
*   **Returns:** `Optional[pd.DataFrame]`: DataFrame containing infiltration parameters if successful, None if operation fails.

### `HdfInfiltration.set_infiltration_layer_data(hdf_path: Path, infiltration_df: pd.DataFrame) -> Optional[pd.DataFrame]`

*   **Purpose:** Sets infiltration layer data in the infiltration layer HDF file directly from the provided DataFrame.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the infiltration layer HDF.
    *   `infiltration_df` (`pd.DataFrame`): DataFrame containing infiltration parameters.
*   **Returns:** `Optional[pd.DataFrame]`: The infiltration DataFrame if successful, None if operation fails.

### `HdfInfiltration.scale_infiltration_data(hdf_path: Path, infiltration_df: pd.DataFrame, scale_factors: Dict[str, float]) -> Optional[pd.DataFrame]`

*   **Purpose:** Updates infiltration parameters in the HDF file with scaling factors.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `infiltration_df` (`pd.DataFrame`): DataFrame containing infiltration parameters.
    *   `scale_factors` (`Dict[str, float]`): Dictionary mapping column names to their scaling factors.
*   **Returns:** `Optional[pd.DataFrame]`: The updated infiltration DataFrame if successful, None if operation fails.

### `HdfInfiltration.get_infiltration_map(hdf_path: Path = None, ras_object: Any = None) -> dict`

*   **Purpose:** Reads the infiltration raster map from HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `dict`: Dictionary mapping raster values to mukeys.

### `HdfInfiltration.calculate_soil_statistics(zonal_stats: list, raster_map: dict) -> pd.DataFrame`

*   **Purpose:** Calculates soil statistics from zonal statistics.
*   **Parameters:**
    *   `zonal_stats` (`list`): List of zonal statistics.
    *   `raster_map` (`dict`): Dictionary mapping raster values to mukeys.
*   **Returns:** `pd.DataFrame`: DataFrame with soil statistics including percentages and areas.

### `HdfInfiltration.get_significant_mukeys(soil_stats: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame`

*   **Purpose:** Gets mukeys with percentage greater than threshold.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `threshold` (`float`, optional): Minimum percentage threshold. Default 1.0.
*   **Returns:** `pd.DataFrame`: DataFrame with significant mukeys and their statistics.

### `HdfInfiltration.calculate_total_significant_percentage(significant_mukeys: pd.DataFrame) -> float`

*   **Purpose:** Calculates total percentage covered by significant mukeys.
*   **Parameters:**
    *   `significant_mukeys` (`pd.DataFrame`): DataFrame of significant mukeys.
*   **Returns:** `float`: Total percentage covered by significant mukeys.

### `HdfInfiltration.save_statistics(soil_stats: pd.DataFrame, output_path: Path, include_timestamp: bool = True)`

*   **Purpose:** Saves soil statistics to CSV.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `output_path` (`Path`): Path to save CSV file.
    *   `include_timestamp` (`bool`, optional): Whether to include timestamp in filename. Default True.
*   **Returns:** None

### `HdfInfiltration.get_infiltration_parameters(hdf_path: Path = None, mukey: str = None, ras_object: Any = None) -> dict`

*   **Purpose:** Gets infiltration parameters for a specific mukey from HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df.
    *   `mukey` (`str`): Mukey identifier.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `dict`: Dictionary of infiltration parameters.

### `HdfInfiltration.calculate_weighted_parameters(soil_stats: pd.DataFrame, infiltration_params: dict) -> dict`

*   **Purpose:** Calculates weighted infiltration parameters based on soil statistics.
*   **Parameters:**
    *   `soil_stats` (`pd.DataFrame`): DataFrame with soil statistics.
    *   `infiltration_params` (`dict`): Dictionary of infiltration parameters by mukey.
*   **Returns:** `dict`: Dictionary of weighted average infiltration parameters.

---

## Class: HdfMesh

Contains static methods for extracting 2D mesh geometry information from HEC-RAS HDF files (typically geometry or plan HDF).

### `HdfMesh.get_mesh_area_names(hdf_path)`

*   **Purpose:** Retrieves the names of all 2D Flow Areas defined in the HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `List[str]`: List of 2D Flow Area names.

### `HdfMesh.get_mesh_areas(hdf_path)`

*   **Purpose:** Extracts the outer perimeter polygons for each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon geometries and 'mesh_name' attribute.

### `HdfMesh.get_mesh_cell_polygons(hdf_path)`

*   **Purpose:** Reconstructs the individual cell polygons for all 2D Flow Areas by assembling cell faces.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Polygon geometries and attributes 'mesh_name', 'cell_id'.

### `HdfMesh.get_mesh_cell_points(hdf_path)`

*   **Purpose:** Extracts the center point coordinates for each cell in all 2D Flow Areas.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes 'mesh_name', 'cell_id'.

### `HdfMesh.get_mesh_cell_faces(hdf_path)`

*   **Purpose:** Extracts the face line segments that form the boundaries of the mesh cells.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes 'mesh_name', 'face_id'.

### `HdfMesh.get_mesh_area_attributes(hdf_path)`

*   **Purpose:** Retrieves the main attributes associated with the 2D Flow Areas group in the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the attributes (e.g., Manning's n values).

### `HdfMesh.get_mesh_face_property_tables(hdf_path)`

*   **Purpose:** Extracts the detailed hydraulic property tables (Elevation vs. Area, Wetted Perimeter, Roughness) associated with each *face* in each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Dict[str, pd.DataFrame]`: Dictionary mapping mesh names to DataFrames. Each DataFrame contains columns ['Face ID', 'Z', 'Area', 'Wetted Perimeter', "Manning's n"].

### `HdfMesh.get_mesh_cell_property_tables(hdf_path)`

*   **Purpose:** Extracts the detailed hydraulic property tables (Elevation vs. Volume, Surface Area) associated with each *cell* in each 2D Flow Area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `Dict[str, pd.DataFrame]`: Dictionary mapping mesh names to DataFrames. Each DataFrame contains columns ['Cell ID', 'Z', 'Volume', 'Surface Area'].

---

## Class: HdfPipe

Contains static methods for handling pipe network geometry and results data from HEC-RAS HDF files.

### `HdfPipe.get_pipe_conduits(hdf_path, crs="EPSG:4326")`

*   **Purpose:** Extracts pipe conduit centerlines, attributes, and terrain profiles from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `crs` (`str`, optional): Coordinate Reference System string. Default "EPSG:4326".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries ('Polyline'), attributes, and 'Terrain_Profiles' (list of (station, elevation) tuples).

### `HdfPipe.get_pipe_nodes(hdf_path)`

*   **Purpose:** Extracts pipe node locations and attributes from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes.

### `HdfPipe.get_pipe_network(hdf_path, pipe_network_name=None, crs="EPSG:4326")`

*   **Purpose:** Extracts the detailed geometry of a specific pipe network, including cell polygons, faces, nodes, and connectivity information from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `pipe_network_name` (`str`, optional): Name of the network. If `None`, uses the first network found.
    *   `crs` (`str`, optional): Coordinate Reference System string. Default "EPSG:4326".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame primarily representing cells (Polygon geometry), with related face and node info included as attributes or object columns.
*   **Raises:** `ValueError` if `pipe_network_name` not found.

### `HdfPipe.get_pipe_profile(hdf_path, conduit_id)`

*   **Purpose:** Extracts the station-elevation terrain profile data for a specific pipe conduit from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
    *   `conduit_id` (`int`): Zero-based index of the conduit.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Station', 'Elevation'].
*   **Raises:** `KeyError`, `IndexError`.

### `HdfPipe.get_pipe_network_timeseries(hdf_path, variable)`

*   **Purpose:** Extracts time series results for a specified variable across all elements (cells, faces, pipes, nodes) of a pipe network.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `variable` (`str`): The results variable name (e.g., "Cell Water Surface", "Pipes/Pipe Flow DS", "Nodes/Depth").
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'location') containing the time series values. Includes units attribute.
*   **Raises:** `ValueError` for invalid variable name, `KeyError`.

### `HdfPipe.get_pipe_network_summary(hdf_path)`

*   **Purpose:** Extracts summary statistics (min/max values, timing) for pipe network results from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the summary statistics. Returns empty DataFrame if data not found.
*   **Raises:** `KeyError`.

### `HdfPipe.extract_timeseries_for_node(plan_hdf_path, node_id)`

*   **Purpose:** Extracts time series data specifically for a single pipe node (Depth, Drop Inlet Flow, Water Surface).
*   **Parameters:**
    *   `plan_hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `node_id` (`int`): Zero-based index of the node.
*   **Returns:** `Dict[str, xr.DataArray]`: Dictionary mapping variable names to their respective DataArrays (time dimension only).

### `HdfPipe.extract_timeseries_for_conduit(plan_hdf_path, conduit_id)`

*   **Purpose:** Extracts time series data specifically for a single pipe conduit (Flow US/DS, Velocity US/DS).
*   **Parameters:**
    *   `plan_hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `conduit_id` (`int`): Zero-based index of the conduit.
*   **Returns:** `Dict[str, xr.DataArray]`: Dictionary mapping variable names to their respective DataArrays (time dimension only).

---

## Class: HdfPlan

Contains static methods for extracting general plan-level information and attributes from HEC-RAS HDF files (plan or geometry HDF).

### `HdfPlan.get_plan_start_time(hdf_path)`

*   **Purpose:** Gets the simulation start time from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** (`datetime`): Simulation start time.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_end_time(hdf_path)`

*   **Purpose:** Gets the simulation end time from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** (`datetime`): Simulation end time.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_timestamps_list(hdf_path)`

*   **Purpose:** Gets the list of simulation output timestamps from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `List[datetime]`: List of output datetime objects.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_information(hdf_path)`

*   **Purpose:** Extracts all attributes from the 'Plan Data/Plan Information' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `Dict[str, Any]`: Dictionary of plan information attributes.
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_parameters(hdf_path)`

*   **Purpose:** Extracts all attributes from the 'Plan Data/Plan Parameters' group in the plan HDF file and returns them as a DataFrame. Includes the plan number extracted from the filename.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Plan', 'Parameter', 'Value'].
*   **Raises:** `ValueError`.

### `HdfPlan.get_plan_met_precip(hdf_path)`

*   **Purpose:** Extracts precipitation attributes from the 'Event Conditions/Meteorology/Precipitation' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan HDF.
*   **Returns:** `Dict[str, Any]`: Dictionary of precipitation attributes. Returns empty dict if not found.

### `HdfPlan.get_geometry_information(hdf_path)`

*   **Purpose:** Extracts root-level attributes (like Version, Units, Projection) from the 'Geometry' group in a geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Value'] and index ['Attribute Name'].
*   **Raises:** `ValueError`.

---

## Class: HdfPlot

Contains static methods for creating basic plots from HEC-RAS HDF data using `matplotlib`.

### `HdfPlot.plot_mesh_cells(cell_polygons_df, projection, title='2D Flow Area Mesh Cells', figsize=(12, 8))`

*   **Purpose:** Plots 2D mesh cell outlines from a GeoDataFrame.
*   **Parameters:**
    *   `cell_polygons_df` (`gpd.GeoDataFrame`): GeoDataFrame containing cell polygons (requires 'geometry' column).
    *   `projection` (`str`): CRS string to assign if `cell_polygons_df` doesn't have one.
    *   `title` (`str`, optional): Plot title. Default '2D Flow Area Mesh Cells'.
    *   `figsize` (`Tuple[int, int]`, optional): Figure size. Default (12, 8).
*   **Returns:** (`gpd.GeoDataFrame` or `None`): The input GeoDataFrame (with CRS possibly assigned), or `None` if input was empty. Displays the plot.

### `HdfPlot.plot_time_series(df, x_col, y_col, title=None, figsize=(12, 6))`

*   **Purpose:** Creates a simple line plot for time series data from a DataFrame.
*   **Parameters:**
    *   `df` (`pd.DataFrame`): DataFrame containing the data.
    *   `x_col` (`str`): Column name for the x-axis (usually time).
    *   `y_col` (`str`): Column name for the y-axis.
    *   `title` (`str`, optional): Plot title. Default `None`.
    *   `figsize` (`Tuple[int, int]`, optional): Figure size. Default (12, 6).
*   **Returns:** `None`. Displays the plot.

---

## Class: HdfPump

Contains static methods for handling pump station geometry and results data from HEC-RAS HDF files.

### `HdfPump.get_pump_stations(hdf_path)`

*   **Purpose:** Extracts pump station locations and attributes from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with Point geometries and attributes including 'station_id'.
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_groups(hdf_path)`

*   **Purpose:** Extracts pump group attributes and efficiency curve data from the geometry HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`): Path identifier for the HDF file (usually geometry or plan HDF).
*   **Returns:** `pd.DataFrame`: DataFrame containing pump group attributes and 'efficiency_curve' data (list of values).
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_station_timeseries(hdf_path, pump_station)`

*   **Purpose:** Extracts time series results (Flow, Stage HW, Stage TW, Pumps On) for a specific pump station from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `pump_station` (`str`): Name of the pump station as defined in HEC-RAS.
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'variable') containing the time series. Includes units attribute.
*   **Raises:** `KeyError`, `ValueError` if pump station not found.

### `HdfPump.get_pump_station_summary(hdf_path)`

*   **Purpose:** Extracts summary statistics (min/max values, volumes, durations) for all pump stations from the plan results HDF.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the summary statistics. Returns empty DataFrame if data not found.
*   **Raises:** `KeyError`.

### `HdfPump.get_pump_operation_timeseries(hdf_path, pump_station)`

*   **Purpose:** Extracts detailed pump operation time series data (similar to `get_pump_station_timeseries` but often from a different HDF group, potentially DSS Profile Output) for a specific pump station. Returns as a DataFrame.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `pump_station` (`str`): Name of the pump station.
*   **Returns:** `pd.DataFrame`: DataFrame with columns ['Time', 'Flow', 'Stage HW', 'Stage TW', 'Pump Station', 'Pumps on'].
*   **Raises:** `KeyError`, `ValueError` if pump station not found.

---

## Class: HdfResultsMesh

Contains static methods for extracting and analyzing 2D mesh *results* data from HEC-RAS plan HDF files.

### `HdfResultsMesh.get_mesh_summary(hdf_path, var, round_to="100ms")`

*   **Purpose:** Extracts summary output (e.g., max/min values and times) for a specific variable across all cells/faces in all 2D areas. Merges with geometry (points for cells, lines for faces).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `var` (`str`): The summary variable name (e.g., "Maximum Water Surface", "Maximum Face Velocity", "Cell Last Iteration").
    *   `round_to` (`str`, optional): Time rounding precision for timestamps. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing the summary results, geometry, and mesh/element IDs.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_timeseries(hdf_path, mesh_name, var, truncate=True)`

*   **Purpose:** Extracts the full time series for a specific variable for all cells or faces within a *single* specified 2D mesh area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_name` (`str`): Name of the 2D Flow Area.
    *   `var` (`str`): Results variable name (e.g., "Water Surface", "Face Velocity", "Depth").
    *   `truncate` (`bool`, optional): If `True`, remove trailing zero-value time steps. Default `True`.
*   **Returns:** `xr.DataArray`: DataArray with dimensions ('time', 'cell_id' or 'face_id') containing the time series. Includes units attribute.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_faces_timeseries(hdf_path, mesh_name)`

*   **Purpose:** Extracts time series for all standard *face-based* variables ("Face Velocity", "Face Flow") for a specific mesh area.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_name` (`str`): Name of the 2D Flow Area.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each face variable, indexed by time and face_id.

### `HdfResultsMesh.get_mesh_cells_timeseries(hdf_path, mesh_names=None, var=None, truncate=False, ras_object=None)`

*   **Purpose:** Extracts time series for specified (or all) *cell-based* variables for specified (or all) mesh areas.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `mesh_names` (`str` or `List[str]`, optional): Name(s) of mesh area(s). If `None`, processes all.
    *   `var` (`str`, optional): Specific variable name. If `None`, retrieves all available cell and face variables.
    *   `truncate` (`bool`, optional): Remove trailing zero time steps. Default `False`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `Dict[str, xr.Dataset]`: Dictionary mapping mesh names to Datasets containing the requested variable(s) as DataArrays, indexed by time and cell_id/face_id.
*   **Raises:** `ValueError`.

### `HdfResultsMesh.get_mesh_last_iter(hdf_path)`

*   **Purpose:** Shortcut to get the summary output for "Cell Last Iteration".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: DataFrame containing the last iteration count for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_ws(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Maximum Water Surface".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing max WSE and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_min_ws(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Minimum Water Surface".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing min WSE and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_face_v(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Maximum Face Velocity".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing max velocity and time for each face (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_min_face_v(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Minimum Face Velocity".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing min velocity and time for each face (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_ws_err(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Cell Maximum Water Surface Error".
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `pd.DataFrame`: DataFrame containing max WSE error and time for each cell (via `get_mesh_summary`).

### `HdfResultsMesh.get_mesh_max_iter(hdf_path, round_to="100ms")`

*   **Purpose:** Shortcut to get the summary output for "Cell Last Iteration" (often used as max iteration indicator).
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `round_to` (`str`, optional): Time rounding precision. Default "100ms".
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame containing max iteration count and time for each cell (via `get_mesh_summary`).

---

## Class: HdfResultsPlan

Contains static methods for extracting general plan-level *results* and summary information from HEC-RAS plan HDF files.

### `HdfResultsPlan.get_unsteady_info(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the unsteady results attributes.
*   **Raises:** `FileNotFoundError`, `KeyError`, `RuntimeError`.

### `HdfResultsPlan.get_unsteady_summary(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady/Summary' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the unsteady summary attributes.
*   **Raises:** `FileNotFoundError`, `KeyError`, `RuntimeError`.

### `HdfResultsPlan.get_volume_accounting(hdf_path)`

*   **Purpose:** Extracts attributes from the 'Results/Unsteady/Summary/Volume Accounting' group in the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** (`pd.DataFrame` or `None`): Single-row DataFrame containing volume accounting attributes, or `None` if the group doesn't exist.
*   **Raises:** `FileNotFoundError`, `RuntimeError`.

### `HdfResultsPlan.get_runtime_data(hdf_path)`

*   **Purpose:** Extracts detailed computational performance metrics (durations, speeds) for different simulation processes (Geometry, Preprocessing, Unsteady Flow) from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** (`pd.DataFrame` or `None`): Single-row DataFrame containing runtime statistics, or `None` if data is missing or parsing fails.

### `HdfResultsPlan.get_reference_timeseries(hdf_path, reftype)`

*   **Purpose:** Extracts time series results for all Reference Lines or Reference Points from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `reftype` (`str`): Type of reference feature ('lines' or 'points').
*   **Returns:** `pd.DataFrame`: DataFrame containing time series data for the specified reference type. Each column represents a reference feature, indexed by time step. Returns empty DataFrame if data not found.

### `HdfResultsPlan.get_reference_summary(hdf_path, reftype)`

*   **Purpose:** Extracts summary results (e.g., max/min values) for all Reference Lines or Reference Points from the plan HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
    *   `reftype` (`str`): Type of reference feature ('lines' or 'points').
*   **Returns:** `pd.DataFrame`: DataFrame containing summary data for the specified reference type. Returns empty DataFrame if data not found.

---

## Class: HdfResultsPlot

Contains static methods for plotting specific HEC-RAS *results* data using `matplotlib`.

### `HdfResultsPlot.plot_results_max_wsel(max_ws_df)`

*   **Purpose:** Creates a scatter plot showing the spatial distribution of maximum water surface elevation (WSE) per mesh cell.
*   **Parameters:**
    *   `max_ws_df` (`gpd.GeoDataFrame`): GeoDataFrame containing max WSE results (requires 'geometry' and 'maximum_water_surface' columns, typically from `HdfResultsMesh.get_mesh_max_ws`).
*   **Returns:** `None`. Displays the plot.

### `HdfResultsPlot.plot_results_max_wsel_time(max_ws_df)`

*   **Purpose:** Creates a scatter plot showing the spatial distribution of the *time* at which maximum water surface elevation occurred for each mesh cell. Also prints timing statistics.
*   **Parameters:**
    *   `max_ws_df` (`gpd.GeoDataFrame`): GeoDataFrame containing max WSE results (requires 'geometry' and 'maximum_water_surface_time' columns, typically from `HdfResultsMesh.get_mesh_max_ws`).
*   **Returns:** `None`. Displays the plot and prints statistics.

### `HdfResultsPlot.plot_results_mesh_variable(variable_df, variable_name, colormap='viridis', point_size=10)`

*   **Purpose:** Creates a generic scatter plot for visualizing any scalar mesh variable (e.g., max depth, max velocity) spatially across cell points.
*   **Parameters:**
    *   `variable_df` (`gpd.GeoDataFrame` or `pd.DataFrame`): (Geo)DataFrame containing the variable data and either a 'geometry' column (Point) or 'x', 'y' columns.
    *   `variable_name` (`str`): The name of the column in `variable_df` containing the data to plot and label.
    *   `colormap` (`str`, optional): Matplotlib colormap name. Default 'viridis'.
    *   `point_size` (`int`, optional): Size of scatter plot points. Default 10.
*   **Returns:** `None`. Displays the plot.
*   **Raises:** `ValueError` if coordinates or variable column are missing.

---

## Class: HdfResultsXsec

Contains static methods for extracting 1D cross-section and related *results* data from HEC-RAS plan HDF files.

### `HdfResultsXsec.get_xsec_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Water Surface, Velocity, Flow, etc.) for all 1D cross-sections. Includes cross-section attributes (River, Reach, Station) and calculated maximum values as coordinates/variables.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and cross_section name/identifier. Includes coordinates for attributes and max values.
*   **Raises:** `KeyError`.

### `HdfResultsXsec.get_ref_lines_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Flow, Velocity, Water Surface) for all 1D Reference Lines.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and reference line ID/name. Returns empty dataset if data not found.
*   **Raises:** `FileNotFoundError`, `KeyError`.

### `HdfResultsXsec.get_ref_points_timeseries(hdf_path)`

*   **Purpose:** Extracts time series results (Flow, Velocity, Water Surface) for all 1D Reference Points.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='plan_hdf'`): Path identifier for the plan results HDF.
*   **Returns:** `xr.Dataset`: Dataset containing DataArrays for each variable, indexed by time and reference point ID/name. Returns empty dataset if data not found.
*   **Raises:** `FileNotFoundError`, `KeyError`.

---

## Class: HdfStruc

Contains static methods for extracting hydraulic structure *geometry* data from HEC-RAS HDF files (typically geometry HDF).

### `HdfStruc.get_structures(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts geometry and attributes for all structures (bridges, culverts, inline structures, lateral structures) defined in the geometry HDF. Includes centerline geometry, profile data, and other specific attributes like bridge coefficients.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to ISO strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries (centerlines) and numerous attribute columns, including nested profile data ('Profile_Data'). Returns empty GeoDataFrame if no structures found.

### `HdfStruc.get_geom_structures_attrs(hdf_path)`

*   **Purpose:** Extracts the top-level attributes associated with the 'Geometry/Structures' group in the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
*   **Returns:** `pd.DataFrame`: Single-row DataFrame containing the group attributes. Returns empty DataFrame if group not found.

---

## Class: HdfUtils

Contains general static utility methods used for HDF processing, data conversion, and calculations.

### `HdfUtils.convert_ras_string(value)`

*   **Purpose:** Converts byte strings or regular strings potentially containing HEC-RAS specific formats (dates, durations, booleans) into appropriate Python objects (`bool`, `datetime`, `List[datetime]`, `timedelta`, `str`).
*   **Parameters:**
    *   `value` (`str` or `bytes`): Input string or byte string.
*   **Returns:** (`bool`, `datetime`, `List[datetime]`, `timedelta`, `str`): Converted Python object.

### `HdfUtils.convert_ras_hdf_value(value)`

*   **Purpose:** General converter for values read directly from HDF datasets (handles `np.nan`, byte strings, numpy types).
*   **Parameters:**
    *   `value` (`Any`): Value read from HDF.
*   **Returns:** (`None`, `bool`, `str`, `List[str]`, `int`, `float`, `List[int]`, `List[float]`): Converted Python object.

### `HdfUtils.convert_df_datetimes_to_str(df)`

*   **Purpose:** Converts all columns of dtype `datetime64` in a DataFrame to ISO format strings (`YYYY-MM-DD HH:MM:SS`).
*   **Parameters:**
    *   `df` (`pd.DataFrame`): Input DataFrame.
*   **Returns:** `pd.DataFrame`: DataFrame with datetime columns converted to strings.

### `HdfUtils.convert_hdf5_attrs_to_dict(attrs, prefix=None)`

*   **Purpose:** Converts HDF5 attributes (from `.attrs`) into a Python dictionary, applying `convert_ras_hdf_value` to each value.
*   **Parameters:**
    *   `attrs` (`h5py.AttributeManager` or `Dict`): Attributes object or dictionary.
    *   `prefix` (`str`, optional): Prefix to add to keys in the resulting dictionary.
*   **Returns:** `Dict[str, Any]`: Dictionary of converted attributes.

### `HdfUtils.convert_timesteps_to_datetimes(timesteps, start_time, time_unit="days", round_to="100ms")`

*   **Purpose:** Converts an array of numeric time steps (relative to a start time) into a pandas `DatetimeIndex`.
*   **Parameters:**
    *   `timesteps` (`np.ndarray`): Array of time step values.
    *   `start_time` (`datetime`): The reference start datetime.
    *   `time_unit` (`str`, optional): Unit of the `timesteps` ('days' or 'hours'). Default 'days'.
    *   `round_to` (`str`, optional): Pandas frequency string for rounding. Default '100ms'.
*   **Returns:** `pd.DatetimeIndex`: Index of datetime objects.

### `HdfUtils.perform_kdtree_query(reference_points, query_points, max_distance=2.0)`

*   **Purpose:** Finds nearest point in `reference_points` for each point in `query_points` using KDTree, within `max_distance`. Returns index or -1. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.perform_kdtree_query`.
*   **Returns:** (`np.ndarray`): Array of indices or -1.

### `HdfUtils.find_nearest_neighbors(points, max_distance=2.0)`

*   **Purpose:** Finds nearest neighbor for each point within the same dataset using KDTree, excluding self and points beyond `max_distance`. Returns index or -1. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.find_nearest_neighbors`.
*   **Returns:** (`np.ndarray`): Array of indices or -1.

### `HdfUtils.parse_ras_datetime(datetime_str)`

*   **Purpose:** Parses HEC-RAS standard datetime string format ("ddMMMYYYY HH:MM:SS").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object.

### `HdfUtils.parse_ras_window_datetime(datetime_str)`

*   **Purpose:** Parses HEC-RAS simulation window datetime string format ("ddMMMYYYY HHMM").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object.

### `HdfUtils.parse_duration(duration_str)`

*   **Purpose:** Parses HEC-RAS duration string format ("HH:MM:SS").
*   **Parameters:**
    *   `duration_str` (`str`): String to parse.
*   **Returns:** (`timedelta`): Parsed timedelta object.

### `HdfUtils.parse_ras_datetime_ms(datetime_str)`

*   **Purpose:** Parses HEC-RAS datetime string format that includes milliseconds ("ddMMMYYYY HH:MM:SS:fff").
*   **Parameters:**
    *   `datetime_str` (`str`): String to parse.
*   **Returns:** (`datetime`): Parsed datetime object with microseconds.

### `HdfUtils.parse_run_time_window(window)`

*   **Purpose:** Parses a HEC-RAS time window string ("datetime1 to datetime2") into start and end datetime objects.
*   **Parameters:**
    *   `window` (`str`): Time window string.
*   **Returns:** `Tuple[datetime, datetime]`: Tuple containing (start_datetime, end_datetime).

### `HdfUtils.decode_byte_strings(dataframe)`

*   **Purpose:** Decodes all byte string (`b'...'`) columns in a DataFrame to UTF-8 strings. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.decode_byte_strings`.
*   **Returns:** `pd.DataFrame`.

### `HdfUtils.consolidate_dataframe(...)`

*   **Purpose:** Aggregates rows in a DataFrame based on grouping criteria. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.consolidate_dataframe`.
*   **Returns:** `pd.DataFrame`.

### `HdfUtils.find_nearest_value(...)`

*   **Purpose:** Finds the element in an array numerically closest to a target value. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.find_nearest_value`.
*   **Returns:** (`int` or `float`).

### `HdfUtils.horizontal_distance(...)`

*   **Purpose:** Calculates the 2D Euclidean distance between two points. (See `RasUtils` for identical function).
*   **Parameters:** See `RasUtils.horizontal_distance`.
*   **Returns:** (`float`).

---

## Class: HdfXsec

Contains static methods for extracting 1D cross-section *geometry* data from HEC-RAS HDF files (typically geometry HDF).

### `HdfXsec.get_cross_sections(hdf_path, datetime_to_str=True, ras_object=None)`

*   **Purpose:** Extracts detailed cross-section geometry, attributes, station-elevation data, Manning's n values, and ineffective flow areas from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `True`.
    *   `ras_object` (`RasPrj`, optional): Instance for context. Defaults to global `ras`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries (cross-section cut lines) and numerous attributes including nested lists/dicts for profile data ('station_elevation'), roughness ('mannings_n'), and ineffective areas ('ineffective_blocks').

### `HdfXsec.get_river_centerlines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river centerline geometries and attributes from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes like 'River Name', 'Reach Name', 'length'.

### `HdfXsec.get_river_stationing(centerlines_gdf)`

*   **Purpose:** Calculates stationing values along river centerlines, interpolating points and determining direction based on upstream/downstream connections.
*   **Parameters:**
    *   `centerlines_gdf` (`gpd.GeoDataFrame`): GeoDataFrame obtained from `get_river_centerlines`.
*   **Returns:** `gpd.GeoDataFrame`: The input GeoDataFrame with added columns: 'station_start', 'station_end', 'stations' (array), 'points' (array of Shapely Points).

### `HdfXsec.get_river_reaches(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts 1D river reach lines (often identical to centerlines but potentially simplified) from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes.

### `HdfXsec.get_river_edge_lines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river edge lines (representing the extent of the 1D river schematic) from the geometry HDF file. Usually includes Left and Right edges.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes including 'bank_side' ('Left'/'Right').

### `HdfXsec.get_river_bank_lines(hdf_path, datetime_to_str=False)`

*   **Purpose:** Extracts river bank lines (defining the main channel within the cross-section) from the geometry HDF file.
*   **Parameters:**
    *   `hdf_path` (Input handled by `@standardize_input`, `file_type='geom_hdf'`): Path identifier for the geometry HDF.
    *   `datetime_to_str` (`bool`, optional): Convert datetime attributes to strings. Default `False`.
*   **Returns:** `gpd.GeoDataFrame`: GeoDataFrame with LineString geometries and attributes 'bank_id', 'bank_side'.

---

## Logging Configuration Functions

### `get_logger(name)`

*   **Purpose:** Retrieves a configured logger instance for use within the library or user scripts. Ensures logging is set up.
*   **Parameters:**
    *   `name` (`str`): Name for the logger (typically `__name__`).
*   **Returns:** (`logging.Logger`): A standard Python logger instance.

---

## Class: RasMap

Contains static methods for parsing and accessing information from HEC-RAS mapper configuration files (.rasmap) and automating post-processing tasks.

### `RasMap.parse_rasmap(rasmap_path: Union[str, Path], ras_object=None) -> pd.DataFrame`

*   **Purpose:** Parse a .rasmap file and extract relevant information, including paths to terrain, soil layers, land cover, and other spatial datasets.
*   **Parameters:**
    *   `rasmap_path` (`Union[str, Path]`): Path to the .rasmap file.
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `pd.DataFrame`: A single-row DataFrame containing extracted information from the .rasmap file.
*   **Raises:** Various exceptions for file access or parsing failures.

### `RasMap.get_rasmap_path(ras_object=None) -> Optional[Path]`

*   **Purpose:** Get the path to the .rasmap file based on the current project.
*   **Parameters:**
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `Optional[Path]`: Path to the .rasmap file if found, None otherwise.

### `RasMap.initialize_rasmap_df(ras_object=None) -> pd.DataFrame`

*   **Purpose:** Initialize the `rasmap_df` as part of project initialization. This is typically called internally by `init_ras_project`.
*   **Parameters:**
    *   `ras_object` (`RasPrj`, optional): Specific RAS object to use. If None, uses the global ras instance.
*   **Returns:** `pd.DataFrame`: DataFrame containing information from the .rasmap file.

### `RasMap.get_terrain_names(rasmap_path: Union[str, Path]) -> List[str]`
*   **Purpose:** Extracts all terrain layer names from a given `.rasmap` file.
*   **Parameters:**
    *   `rasmap_path` (`Union[str, Path]`): Path to the `.rasmap` file.
*   **Returns:** (`List[str]`): A list of terrain names.
*   **Raises:** `FileNotFoundError`, `ValueError`.

### `RasMap.postprocess_stored_maps(plan_number: str, specify_terrain: Optional[str] = None, layers: Union[str, List[str]] = None, ras_object: Optional[Any] = None) -> bool`
*   **Purpose:** Automates the generation of stored floodplain map outputs (e.g., `.tif` files) for a specific plan.
*   **Parameters:**
    *   `plan_number` (`str`): The plan to generate maps for.
    *   `specify_terrain` (`str`, optional): The name of a specific terrain to use for mapping. If provided, other terrains are temporarily ignored.
    *   `layers` (`Union[str, List[str]]`, optional): A list of map layers to generate. Defaults to `['WSEL', 'Velocity', 'Depth']`.
    *   `ras_object` (`RasPrj`, optional): The RAS project object to use.
*   **Returns:** (`bool`): `True` if the process completed successfully, `False` otherwise.
*   **Workflow:**
    1.  Backs up the original plan and `.rasmap` files.
    2.  Modifies the plan file to only run floodplain mapping.
    3.  Modifies the `.rasmap` file to include the specified stored map layers.
    4.  Runs `RasCmdr.compute_plan` to generate the maps.
    5.  Restores the original plan and `.rasmap` files, but keeps the newly added map layer definitions in the `.rasmap` file for future use.