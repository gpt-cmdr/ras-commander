**Agent Guide: Examples Notebooks**

Purpose: Help an agent navigate each notebook quickly and extract only the logic needed to build scripts. Treat notebooks as reference; prefer cleaned copies (no images/outputs) when available.

How agents should use notebooks
- Read code cells, ignore long outputs and images.
- Understand the intent and data flow; note any environment-specific paths.
- Extract relevant cells into a script, replacing Jupyter-only commands (e.g., `!pip install`) with `uv pip install` run in the terminal.
- Execute scripts via `uv run ...` with inputs/outputs in a writable folder (e.g., `working/`).

00_Using_RasExamples.ipynb
- Focus: Download/list/extract official example projects.
- Functions: RasExamples.get_example_projects (ras_commander/RasExamples.py), RasExamples.list_categories (ras_commander/RasExamples.py), RasExamples.list_projects (ras_commander/RasExamples.py), RasExamples.extract_project (ras_commander/RasExamples.py), RasExamples.is_project_extracted (ras_commander/RasExamples.py), RasExamples.clean_projects_directory (ras_commander/RasExamples.py).
- Pattern: Extract to a writable workspace folder (not inside repo) to avoid committing large assets.

01_project_initialization.ipynb
- Focus: Initialize a project and inspect metadata.
- Functions: init_ras_project (ras_commander/RasPrj.py), RasPrj (ras_commander/RasPrj.py), get_ras_exe (ras_commander/RasPrj.py); ras dataframes: `plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`, get_hdf_entries (ras_commander/RasPrj.py).
- Pattern: Use global `ras` for single-project workflows; prefer separate `RasPrj` instances for multi-project work.

02_plan_and_geometry_operations.ipynb
- Focus: Clone/retarget plans, geometry, and intervals.
- Functions: RasPlan.clone_plan (ras_commander/RasPlan.py), RasPlan.clone_geom (ras_commander/RasPlan.py), RasPlan.clone_unsteady (ras_commander/RasPlan.py), RasPlan.clone_steady (ras_commander/RasPlan.py), RasPlan.set_geom (ras_commander/RasPlan.py), RasPlan.set_steady (ras_commander/RasPlan.py), RasPlan.set_unsteady (ras_commander/RasPlan.py), RasPlan.set_geom_preprocessor (ras_commander/RasPlan.py), RasPlan.set_num_cores (ras_commander/RasPlan.py), RasPlan.update_run_flags (ras_commander/RasPlan.py), RasPlan.update_plan_intervals (ras_commander/RasPlan.py), RasPlan.update_simulation_date (ras_commander/RasPlan.py), RasPlan.update_plan_description (ras_commander/RasPlan.py), RasPlan.get_shortid (ras_commander/RasPlan.py)/set_shortid (ras_commander/RasPlan.py).
- Pattern: Two-digit plan numbers; clear geompre when geometry changes.

03_unsteady_flow_operations.ipynb
- Focus: Inspect/modify unsteady (.uXX) files and BC tables.
- Functions: RasUnsteady.update_flow_title (ras_commander/RasUnsteady.py), RasUnsteady.update_restart_settings (ras_commander/RasUnsteady.py), RasUnsteady.extract_boundary_and_tables (ras_commander/RasUnsteady.py), RasUnsteady.identify_tables (ras_commander/RasUnsteady.py), RasUnsteady.write_table_to_file (ras_commander/RasUnsteady.py).
- Pattern: Clone unsteady first, then edit; reassign plan to updated unsteady.

04_multiple_project_operations.ipynb
- Focus: Work with several projects at once.
- Functions: `RasPrj` per project; RasCmdr.compute_plan (ras_commander/RasCmdr.py)/compute_parallel (ras_commander/RasCmdr.py) with `ras_object`.
- Pattern: Isolate compute folders per project; do not mix global `ras` and custom `RasPrj` instances.

05_single_plan_execution.ipynb
- Focus: Run a single plan with options.
- Functions: RasCmdr.compute_plan (ras_commander/RasCmdr.py); RasGeo.clear_geompre_files (ras_commander/RasGeo.py); RasPlan.set_num_cores (ras_commander/RasPlan.py).
- Pattern: Use `dest_folder` and `overwrite_dest` to keep originals clean.

06_executing_plan_sets.ipynb
- Focus: Specify and execute sets of plans.
- Functions: RasCmdr.compute_plan (ras_commander/RasCmdr.py) (loop), RasCmdr.compute_parallel (ras_commander/RasCmdr.py), RasCmdr.compute_test_mode (ras_commander/RasCmdr.py).
- Pattern: Use lists for plan selection; choose sequential vs parallel based on dependencies.

07_sequential_plan_execution.ipynb
- Focus: Ordered runs with isolation.
- Functions: RasCmdr.compute_test_mode (ras_commander/RasCmdr.py) (with `plan_number`, `dest_folder_suffix`, `num_cores`, `clear_geompre`).
- Pattern: Good for dependent plans or reproducible test folders.

08_parallel_execution.ipynb
- Focus: Throughput with multiple workers.
- Functions: RasCmdr.compute_parallel (ras_commander/RasCmdr.py) (`max_workers`, `num_cores`, `dest_folder`, `overwrite_dest`).
- Pattern: Balance `max_workers * num_cores` to available cores/RAM.

09_plan_parameter_operations.ipynb
- Focus: Edit plan-level parameters.
- Functions: RasPlan.get_plan_value (ras_commander/RasPlan.py), RasPlan.update_run_flags (ras_commander/RasPlan.py), RasPlan.update_plan_intervals (ras_commander/RasPlan.py), RasPlan.update_simulation_date (ras_commander/RasPlan.py), RasPlan.update_plan_description (ras_commander/RasPlan.py), RasPlan.get_plan_title (ras_commander/RasPlan.py)/set_plan_title (ras_commander/RasPlan.py).
- Pattern: Verify changes via ras.plan_df and file reads.

10_1d_hdf_data_extraction.ipynb
- Focus: 1D geometry/results and timeseries queries.
- Functions: HdfXsec.get_cross_sections (ras_commander/HdfXsec.py), HdfResultsXsec.get_xsec_timeseries (ras_commander/HdfResultsXsec.py), HdfResultsXsec.get_ref_lines_timeseries (ras_commander/HdfResultsXsec.py), HdfResultsXsec.get_ref_points_timeseries (ras_commander/HdfResultsXsec.py); HdfResultsPlan.get_runtime_data (ras_commander/HdfResultsPlan.py).
- Notable cells: locate and print `HDF_Results_Path` and geometry HDF; demonstrate use of decorators to accept plan numbers or paths; optional GeoPandas plots for xsec lines.

11_2d_hdf_data_extraction.ipynb
- Focus: 2D mesh geometry/results basics with spatial plotting.
- Functions: HdfMesh.get_mesh_area_names (ras_commander/HdfMesh.py), HdfMesh.get_mesh_areas (ras_commander/HdfMesh.py), HdfMesh.get_mesh_cell_polygons (ras_commander/HdfMesh.py), HdfMesh.get_mesh_cell_points (ras_commander/HdfMesh.py), HdfMesh.get_mesh_cell_faces (ras_commander/HdfMesh.py), HdfBndry.get_breaklines (ras_commander/HdfBndry.py), HdfBndry.get_bc_lines (ras_commander/HdfBndry.py), HdfResultsMesh.get_mesh_max_ws (ras_commander/HdfResultsMesh.py)/get_mesh_min_ws (ras_commander/HdfResultsMesh.py)/get_mesh_max_face_v (ras_commander/HdfResultsMesh.py)/get_mesh_max_ws_err (ras_commander/HdfResultsMesh.py), HdfResultsMesh.get_mesh_timeseries (ras_commander/HdfResultsMesh.py).
- Notable cells: parse `.rasmap`, list plans, derive run windows; join result attributes back to geometry; toggle `generate_plots` to minimize output size.

12_2d_hdf_data_extraction pipes and pumps.ipynb
- Focus: New 6.6+ pipe networks: conduits, nodes, pumps, timeseries.
- Functions: HdfPipe.get_pipe_conduits (ras_commander/HdfPipe.py), HdfPipe.get_pipe_nodes (ras_commander/HdfPipe.py), HdfPipe.get_pipe_network_timeseries (ras_commander/HdfPipe.py), HdfPipe.get_pipe_conduit_timeseries (ras_commander/HdfPipe.py), HdfPump.get_pump_stations (ras_commander/HdfPump.py), HdfPump.get_pump_groups (ras_commander/HdfPump.py), HdfPump.get_pump_station_timeseries (ras_commander/HdfPump.py).
- Notable cells: build network GeoDataFrames, summarize pump groups, plot selected elements; record plan run and extract pump/conduit curves.

13_2d_detail_face_data_extraction.ipynb
- Focus: Face-level analytics along profile lines; unique notebook-only helpers.
- Functions: HdfMesh.get_mesh_face_property_tables (ras_commander/HdfMesh.py), HdfMesh.get_mesh_cell_property_tables (ras_commander/HdfMesh.py); HdfResultsMesh.get_mesh_faces_timeseries (ras_commander/HdfResultsMesh.py).
- Notable cells:
  - Extract `mesh_cell_faces` GeoDataFrame and preview attributes.
  - Unique function `find_nearest_cell_face(point, cell_faces_df)`; returns `(face_id, distance)` and supports plotting the nearest face vs all faces.
  - Profile-line selection along perpendicular faces; compute discharge-weighted velocity; enforce positive flow direction before aggregation.

14_fluvial_pluvial_delineation.ipynb
- Focus: Classify flooding mechanism by timing.
- Functions: HdfResultsMesh.get_mesh_max_ws (ras_commander/HdfResultsMesh.py), plus HdfMesh/HdfBndry for polygons/lines.
- Notable cells: compare timing in adjacent cells; map and export boundaries (GeoJSON) after smoothing/filtering short segments.

15_a_floodplain_mapping_gui.ipynb
- Focus: Floodplain mapping via GUI automation (last resort method).
- Functions: RasMap.postprocess_stored_maps (ras_commander/RasMap.py), RasMap.ensure_rasmap_compatible (ras_commander/RasMap.py).
- Notable cells: Win32 COM automation to open HEC-RAS, navigate menus, generate maps via GUI. Includes .rasmap compatibility checking (upgrades 5.0.7→6.x).
- Performance: Slow (60+ seconds), fragile. Use 15_b or 15_c instead.

15_b_floodplain_mapping_rasprocess.ipynb
- Focus: Floodplain mapping via RasProcess CLI (recommended for Windows).
- Functions: RasProcess.store_maps (ras_commander/RasProcess.py), RasProcess.get_plan_timestamps (ras_commander/RasProcess.py), RasProcess.store_all_maps (ras_commander/RasProcess.py), RasMap.ensure_rasmap_compatible (ras_commander/RasMap.py).
- Notable cells: Fastest method (8-10 seconds), all variables (WSE, Depth, Velocity, Froude, Shear, D*V), time-series analysis, batch processing, georeferencing fix.
- Performance: ⭐⭐⭐ Fastest, ⭐⭐⭐ Excellent reliability, 100% matches native HEC-RAS output.

15_c_floodplain_mapping_python_gis.ipynb
- Focus: Floodplain mapping via pure Python mesh rasterization (cloud-compatible, 2D only).
- Functions: RasMap.map_ras_results (ras_commander/RasMap.py), HdfMesh.get_mesh_cell_polygons (ras_commander/hdf/HdfMesh.py), HdfResultsMesh.get_mesh_max_ws (ras_commander/hdf/HdfResultsMesh.py).
- Notable cells: No HEC-RAS required after computation, horizontal interpolation algorithm, wet cell filtering, mesh boundary clipping. Works on Linux/Mac/Windows.
- Performance: Moderate (15-20 seconds), matches HEC-RAS to 0.01' for 2D horizontal interpolation (99.93% pixel match, RMSE 0.000000).
- Limitations: 2D mesh only (no 1D), WSE/Depth/Velocity only (no Froude/Shear yet), horizontal interpolation only.

16_automating_ras_with_win32com.ipynb
- Focus: Open HEC‑RAS/RAS Mapper to refresh stored-map configs using win32 automation.
- Functions: RasMap.parse_rasmap (ras_commander/RasMap.py), RasGuiAutomation.open_rasmapper (ras_commander/RasGuiAutomation.py), RasGuiAutomation.handle_already_running_dialog (ras_commander/RasGuiAutomation.py).
- Notable cells: manual steps to update mapper, then resume automation; demonstrates window enumeration and button clicking patterns.
- Key: Library functions automatically handle the "already running" dialog - no manual intervention needed.

17_extracting_profiles_with_hecrascontroller.ipynb
- Focus: Extract steady AND unsteady results from legacy HEC-RAS versions (3.x-4.x) using RasControl.
- Functions: RasControl.run_plan (ras_commander/RasControl.py), RasControl.get_steady_results (ras_commander/RasControl.py), RasControl.get_unsteady_results (ras_commander/RasControl.py), RasControl.get_output_times (ras_commander/RasControl.py), RasControl.set_current_plan (ras_commander/RasControl.py).
- Pattern: ras-commander style API - use plan numbers ("02") not file paths. Open-operate-close pattern. Integrates with init_ras_project().
- Notable cells: Steady workflow (Plan 02), unsteady workflow (Plan 01), time series visualization, DataFrame exports.
- Supported versions: 3.1, 4.1, 5.0.x (501, 503, 505, 506), 6.0, 6.3, 6.6.
- Key: Must specify version in init_ras_project(path, "4.1") for RasControl to work.

24_aorc_precipitation.ipynb
- Focus: Download and apply NOAA AORC gridded precipitation for rain-on-grid models.
- Functions: PrecipAorc.get_info (ras_commander/precip/PrecipAorc.py), PrecipAorc.check_availability (ras_commander/precip/PrecipAorc.py), PrecipAorc.download (ras_commander/precip/PrecipAorc.py), PrecipAorc.get_storm_catalog (ras_commander/precip/PrecipAorc.py), PrecipAorc.create_storm_plans (ras_commander/precip/PrecipAorc.py), RasUnsteady.set_gridded_precipitation (ras_commander/RasUnsteady.py).
- Pattern: Define WGS84 bounds → generate storm catalog → download AORC data → configure unsteady files → batch create plans.
- Notable cells: Storm catalog generation with configurable parameters (inter_event_hours, min_depth_inches, buffer_hours, percentile_threshold); batch plan creation from storm catalog.
- Dependencies: xarray, zarr, s3fs, netCDF4, rioxarray (optional for reprojection).
- Key: AORC data reprojected to SHG (EPSG:5070) at 2000m resolution for HEC-RAS GDAL Raster import.

24_1d_boundary_condition_visualization.ipynb
- Focus: Visualize 1D boundary conditions in RASMapper with DSS path labels.
- Functions: RasUnsteady.extract_boundary_and_tables (ras_commander/RasUnsteady.py), HdfXsec.get_cross_sections (ras_commander/hdf/HdfXsec.py), HdfBase.get_projection (ras_commander/hdf/HdfBase.py), RasMap.list_map_layers (ras_commander/RasMap.py), RasMap.add_map_layer (ras_commander/RasMap.py), RasMap.remove_map_layer (ras_commander/RasMap.py), RasMap.list_geometries (ras_commander/RasMap.py), RasMap.set_geometry_visibility (ras_commander/RasMap.py), RasMap.set_all_geometries_visibility (ras_commander/RasMap.py), RasGuiAutomation.open_rasmapper (ras_commander/RasGuiAutomation.py).
- Pattern: Extract XS geometry → parse boundary conditions from unsteady file → match boundaries to XS → create GeoJSON with DSS path attributes → add to RASMapper → configure geometry visibility → open for visualization.
- Notable cells: DSS path parsing to identify HMS basin connections; GeoJSON creation with boundary type classification; geometry visibility management (show only relevant geometry); before/after layer listing; GUI automation to open RASMapper.
- Key: Creates output in `1D_Boundary_Conditions/` subfolder within project; supports labeling with DSS path to show HMS linkage; GeoJSON files MUST be in WGS84 (EPSG:4326) for RASMapper.

101_Core_Sensitivity(.ipynb, _aircooled)
- Focus: Runtime vs core count experiments.
- Functions: RasCmdr.compute_plan (ras_commander/RasCmdr.py); RasPlan.set_num_cores (ras_commander/RasPlan.py).
- Notable cells: sweep cores, record walltime, plot scaling; choose efficient settings.

102_benchmarking_versions_6.1_to_6.6.ipynb
- Focus: Cross-version performance comparison.
- Functions: init_ras_project (ras_commander/RasPrj.py) (vary Ras.exe), RasCmdr.compute_plan (ras_commander/RasCmdr.py), HdfResultsPlan.get_runtime_data (ras_commander/HdfResultsPlan.py).
- Notable cells: control versioned runs, tabulate walltimes per version; keep outputs isolated per version.

103_Running_AEP_Events_from_Atlas_14.ipynb
- Focus: Generate hyetographs from NOAA Atlas 14 and batch scenarios.
- Functions: RasPlan.clone_plan (ras_commander/RasPlan.py)/set_unsteady (ras_commander/RasPlan.py), RasUnsteady.* (ras_commander/RasUnsteady.py), RasCmdr.compute_parallel (ras_commander/RasCmdr.py), HdfResultsMesh (ras_commander/HdfResultsMesh.py)/HdfResultsPlan (ras_commander/HdfResultsPlan.py).
- Notable cells:
  - Read precipitation frequency from Atlas 14 CSVs in `examples/data` and generate balanced storm hyetographs via Alternating Block Method.
  - Parameterize AEP events, clone plans, write unsteady settings, and compute in parallel.
  - Aggregate key metrics from mesh/plan results; optional plots (disable to keep outputs light).

Notebook‑only utilities and unique logic
- `find_nearest_cell_face(...)` (13_2d_detail_face_data_extraction): nearest face selection and plotting; not part of the library API.
- Hyetograph generation for Atlas 14 AEP events (103_*): end‑to‑end pattern from CSV → plan clones → batch compute.
- Profile‑based face aggregation (13_*): discharge‑weighted velocity and flow‑direction normalization.

---

## Notebook Import Cell Management

All example notebooks follow a standardized 2-cell import pattern:

**Cell 0 (Code - ACTIVE by default):**
```python
# Uncomment to install/upgrade ras-commander from pip
#!pip install --upgrade ras-commander

#Import the ras-commander package
from ras_commander import *
```

**Cell 1 (Markdown - INACTIVE by default):**
Contains development mode instructions with code block for local copy usage.

**Cell 2 (Code - When needed):**
Notebook-specific imports (numpy, pandas, matplotlib, etc.)

### Toggling Between Pip and Dev Modes

**For pip-installed package testing (default state):**
- Cell 0 remains as code (active)
- Cell 1 remains as markdown (inactive)
- Run notebooks as-is

**For local development copy testing:**
1. Convert Cell 1 from markdown to code
2. Convert Cell 0 from code to markdown
3. Run the modified notebooks
4. **IMPORTANT:** Restore to default state before committing

**Warning:** Never have both Cell 0 and Cell 1 as code cells simultaneously. This will cause import conflicts.

---

## Running Notebook Tests

### Prerequisites
- Install test dependencies: `uv pip install notebook jupyter ipykernel`
- Ensure HEC-RAS is installed and in PATH
- Verify sufficient disk space for example projects (~5 GB)

### Testing All Notebooks with Subagents

**For pip-installed package:**
```python
# Launch subagent to run all notebooks and review results
# Default state (Cell 0=code, Cell 1=markdown) is correct
task_prompt = """
Run all example notebooks in C:\\GH\\ras-commander\\examples\\ and verify:
1. No import errors
2. No unhandled exceptions
3. Warnings are reviewed and acceptable
4. Long-running cells complete successfully
5. Results match expected patterns

Report any failures, unexpected warnings, or behavioral changes.
"""
```

**For local development copy:**
```python
# First toggle cells, then test
task_prompt = """
1. For each notebook in C:\\GH\\ras-commander\\examples\\:
   - Convert Cell 0 (pip mode) from code to markdown
   - Convert Cell 1 (dev mode) from markdown to code
2. Run all notebooks and verify functionality
3. After testing, restore default state:
   - Convert Cell 0 back to code
   - Convert Cell 1 back to markdown
4. Report results and any issues
"""
```

### Expected Execution Times
- **Quick notebooks** (<30 seconds): 00, 01, 02, 03, 09
- **Medium notebooks** (1-5 minutes): 10, 11, 13, 14
- **Long-running notebooks** (5-30 minutes): 04, 05, 06, 07, 08, 12, 15, 101, 102, 103
- **Manual intervention required:** 16 (GUI automation)

### Reviewing Results

Check for:
- **Import errors:** Indicates missing dependencies or broken imports
- **HEC-RAS errors:** Check HDF files exist and compute messages are clean
- **Warnings:** Review pandas/numpy/geopandas deprecation warnings
- **Data quality:** Spot-check DataFrames, plots, and extracted values
- **Performance:** Note if runtimes significantly increase/decrease

---

## Pre-Commit Checklist for Notebooks

Before committing modified notebooks:

1. **Verify Import Cell State:**
   - [ ] Cell 0 is code (pip mode active)
   - [ ] Cell 1 is markdown (dev mode inactive)
   - [ ] Notebook-specific imports in Cell 2 (if applicable)

2. **Clear All Outputs:**
   ```python
   # Run this to clear outputs from all notebooks
   python -c "import json; from pathlib import Path; import glob;
   notebooks = glob.glob(r'C:\GH\ras-commander\examples\*.ipynb');
   [json.dump((lambda nb: (nb.update({'cells': [dict(cell, outputs=[], execution_count=None)
   if cell['cell_type'] == 'code' else cell for cell in nb['cells']]}) or nb))
   (json.load(open(nb, encoding='utf-8'))), open(nb, 'w', encoding='utf-8'),
   indent=1, ensure_ascii=False) for nb in notebooks]"
   ```

3. **Verify Notebook-Specific Imports Preserved:**
   - Check notebooks 03, 04-09, 12, 16, 101, 102, 105 retain their special imports
   - Ensure imports are consolidated in Cell 2, not scattered

4. **Git Diff Review:**
   - Verify only intended cells were modified
   - Check no accidental deletions of content cells
   - Ensure no large binary outputs were committed

---

General Tips
- Use two-digit plan numbers (e.g., "01").
- Keep original projects immutable; use `dest_folder`/suffixes.
- Plotting: GeoPandas for spatial layers; xarray/pandas for timeseries.
- Logging: library functions are decorated; prefer `get_logger(__name__)` for extra context.

---

## RasGuiAutomation - Windows GUI Automation

The `RasGuiAutomation` class provides win32-based automation for HEC-RAS GUI operations that don't have API support.

**Module**: `ras_commander/RasGuiAutomation.py`

### Core Functions

| Function | Purpose |
|----------|---------|
| `open_rasmapper(prj_file, ras_exe, ...)` | Open RASMapper via GIS Tools menu |
| `open_and_compute(prj_file, plan_number, ...)` | Open HEC-RAS, set plan, navigate menus |
| `run_multiple_plans(prj_file, plan_numbers, ...)` | Automate "Run Multiple Plans" workflow |
| `handle_already_running_dialog(timeout=5)` | Auto-click Yes on "already running" dialog |

### Dialog Handling (Automatic)

When HEC-RAS is launched while another instance is running, a dialog appears:
> "There is already an instance of HEC-RAS running on the system, do you want to start another?"

**Library functions automatically handle this** - no manual intervention needed:
- `open_rasmapper()` calls `handle_already_running_dialog()` internally
- `open_and_compute()` calls `handle_already_running_dialog()` internally
- `run_multiple_plans()` calls `handle_already_running_dialog()` internally

The handler detects the dialog by:
- Window class `#32770` (standard Windows dialog)
- Keywords in child controls: "already", "another", "instance"
- Clicks "Yes" button (supports "Yes", "&Yes", "Ja", "&Ja")
- Falls back to Enter key if button not found

### Helper Functions

| Function | Purpose |
|----------|---------|
| `get_windows_by_pid(pid)` | Return all windows for a process ID |
| `find_main_hecras_window(windows)` | Identify main HEC-RAS window |
| `enumerate_all_menus(hwnd)` | List all menu items |
| `click_menu_item(hwnd, menu_id)` | Trigger a menu item |
| `find_dialog_by_title(pattern, exact)` | Find dialog by title |
| `find_button_by_text(hwnd, text)` | Find button in dialog |
| `click_button(button_hwnd)` | Simulate button click |
| `find_combobox_by_neighbor(hwnd, text)` | Find combo box near label |
| `select_combobox_item_by_text(combo, text)` | Select combo item by text |
| `set_current_plan(hwnd, plan_number, ...)` | Set current plan in dropdown |
| `wait_for_window(find_window_func, ...)` | Wait for window with timeout |
| `close_window(hwnd)` | Close window via WM_CLOSE |

---

## RasMap - Map Layer and Geometry Management

The `RasMap` class provides functions for managing RASMapper configuration files (.rasmap).

**Module**: `ras_commander/RasMap.py`

### Map Layer Functions

| Function | Purpose |
|----------|---------|
| `list_map_layers(ras_object=None)` | List all custom map layers |
| `add_map_layer(layer_name, file_path, ...)` | Add GeoJSON/shapefile layer |
| `remove_map_layer(layer_name, ras_object=None)` | Remove layer by name |

**Example: Adding a GeoJSON layer**
```python
from ras_commander import init_ras_project, RasMap

init_ras_project("/path/to/project", "6.6")

# Add boundary conditions layer
RasMap.add_map_layer(
    layer_name="1D Boundary Conditions",
    file_path="./1D_Boundary_Conditions/boundaries.geojson",
    layer_type="PolylineFeatureLayer"
)
```

**WGS84 Requirement**: GeoJSON files for RASMapper MUST be in WGS84 (EPSG:4326):
```python
# Always reproject before saving GeoJSON for RASMapper
gdf_wgs84 = gdf.to_crs("EPSG:4326")
gdf_wgs84.to_file("output.geojson", driver="GeoJSON")
```

### Geometry Visibility Functions

| Function | Purpose |
|----------|---------|
| `list_geometries(ras_object=None)` | List all geometry layers with visibility status |
| `set_geometry_visibility(geom_id, visible, ...)` | Show/hide specific geometry |
| `set_all_geometries_visibility(visible, except_geom, ...)` | Bulk visibility control |

**Example: Show only one geometry**
```python
from ras_commander import init_ras_project, RasMap

init_ras_project("/path/to/project", "6.6")

# List all geometries
geoms = RasMap.list_geometries()
for g in geoms:
    print(f"{g['geom_number']}: {g['name']} - Visible: {g['checked']}")

# Hide all geometries except G08
RasMap.set_all_geometries_visibility(visible=False, except_geom="08")
RasMap.set_geometry_visibility("08", visible=True)
```

**Geometry identifier formats** (all valid):
- Geometry number: `"08"` or `"8"`
- With prefix: `"g08"` or `"G08"`
- By name: `"1D-2D Dam Break Model Refined Grid"`
- Filename pattern: `"g08.hdf"`

### Other RasMap Functions

| Function | Purpose |
|----------|---------|
| `parse_rasmap(ras_object=None)` | Parse .rasmap XML into dict |
| `ensure_rasmap_compatible(ras_object=None)` | Upgrade 5.0.7 format to 6.x |
| `postprocess_stored_maps(ras_object=None)` | Post-process stored map configurations |
| `map_ras_results(...)` | Pure Python mesh rasterization |

