**Agent Guide: Examples Notebooks**

Purpose: Help an agent navigate each notebook quickly and extract only the logic needed to build scripts. Treat notebooks as reference; prefer cleaned copies (no images/outputs) when available.

How agents should use notebooks
- Read code cells, ignore long outputs and images.
- Understand the intent and data flow; note any environment-specific paths.
- Extract relevant cells into a script, replacing Jupyter-only commands (e.g., `!pip install`) with `uv pip install` run in the terminal.
- Execute scripts via `uv run ...` with inputs/outputs in a writable folder (e.g., `working/`).

00_Using_RasExamples.ipynb
- Focus: Download/list/extract official example projects.
- Functions: [RasExamples.get_example_projects](../ras_commander/RasExamples.py), [RasExamples.list_categories](../ras_commander/RasExamples.py), [RasExamples.list_projects](../ras_commander/RasExamples.py), [RasExamples.extract_project](../ras_commander/RasExamples.py), [RasExamples.is_project_extracted](../ras_commander/RasExamples.py), [RasExamples.clean_projects_directory](../ras_commander/RasExamples.py).
- Pattern: Extract to a writable workspace folder (not inside repo) to avoid committing large assets.

01_project_initialization.ipynb
- Focus: Initialize a project and inspect metadata.
- Functions: [init_ras_project](../ras_commander/RasPrj.py), [RasPrj](../ras_commander/RasPrj.py), [get_ras_exe](../ras_commander/RasPrj.py); ras dataframes: `plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`, [get_hdf_entries](../ras_commander/RasPrj.py).
- Pattern: Use global `ras` for single-project workflows; prefer separate `RasPrj` instances for multi-project work.

02_plan_and_geometry_operations.ipynb
- Focus: Clone/retarget plans, geometry, and intervals.
- Functions: [RasPlan.clone_plan](../ras_commander/RasPlan.py), [RasPlan.clone_geom](../ras_commander/RasPlan.py), [RasPlan.clone_unsteady](../ras_commander/RasPlan.py), [RasPlan.clone_steady](../ras_commander/RasPlan.py), [RasPlan.set_geom](../ras_commander/RasPlan.py), [RasPlan.set_steady](../ras_commander/RasPlan.py), [RasPlan.set_unsteady](../ras_commander/RasPlan.py), [RasPlan.set_geom_preprocessor](../ras_commander/RasPlan.py), [RasPlan.set_num_cores](../ras_commander/RasPlan.py), [RasPlan.update_run_flags](../ras_commander/RasPlan.py), [RasPlan.update_plan_intervals](../ras_commander/RasPlan.py), [RasPlan.update_simulation_date](../ras_commander/RasPlan.py), [RasPlan.update_plan_description](../ras_commander/RasPlan.py), [RasPlan.get_shortid](../ras_commander/RasPlan.py)/[set_shortid](../ras_commander/RasPlan.py).
- Pattern: Two-digit plan numbers; clear geompre when geometry changes.

03_unsteady_flow_operations.ipynb
- Focus: Inspect/modify unsteady (.uXX) files and BC tables.
- Functions: [RasUnsteady.update_flow_title](../ras_commander/RasUnsteady.py), [RasUnsteady.update_restart_settings](../ras_commander/RasUnsteady.py), [RasUnsteady.extract_boundary_and_tables](../ras_commander/RasUnsteady.py), [RasUnsteady.identify_tables](../ras_commander/RasUnsteady.py), [RasUnsteady.write_table_to_file](../ras_commander/RasUnsteady.py).
- Pattern: Clone unsteady first, then edit; reassign plan to updated unsteady.

04_multiple_project_operations.ipynb
- Focus: Work with several projects at once.
- Functions: `RasPrj` per project; [RasCmdr.compute_plan](../ras_commander/RasCmdr.py)/[compute_parallel](../ras_commander/RasCmdr.py) with `ras_object`.
- Pattern: Isolate compute folders per project; do not mix global `ras` and custom `RasPrj` instances.

05_single_plan_execution.ipynb
- Focus: Run a single plan with options.
- Functions: [RasCmdr.compute_plan](../ras_commander/RasCmdr.py); [RasGeo.clear_geompre_files](../ras_commander/RasGeo.py); [RasPlan.set_num_cores](../ras_commander/RasPlan.py).
- Pattern: Use `dest_folder` and `overwrite_dest` to keep originals clean.

06_executing_plan_sets.ipynb
- Focus: Specify and execute sets of plans.
- Functions: [RasCmdr.compute_plan](../ras_commander/RasCmdr.py) (loop), [RasCmdr.compute_parallel](../ras_commander/RasCmdr.py), [RasCmdr.compute_test_mode](../ras_commander/RasCmdr.py).
- Pattern: Use lists for plan selection; choose sequential vs parallel based on dependencies.

07_sequential_plan_execution.ipynb
- Focus: Ordered runs with isolation.
- Functions: [RasCmdr.compute_test_mode](../ras_commander/RasCmdr.py) (with `plan_number`, `dest_folder_suffix`, `num_cores`, `clear_geompre`).
- Pattern: Good for dependent plans or reproducible test folders.

08_parallel_execution.ipynb
- Focus: Throughput with multiple workers.
- Functions: [RasCmdr.compute_parallel](../ras_commander/RasCmdr.py) (`max_workers`, `num_cores`, `dest_folder`, `overwrite_dest`).
- Pattern: Balance `max_workers * num_cores` to available cores/RAM.

09_plan_parameter_operations.ipynb
- Focus: Edit plan-level parameters.
- Functions: [RasPlan.get_plan_value](../ras_commander/RasPlan.py), [RasPlan.update_run_flags](../ras_commander/RasPlan.py), [RasPlan.update_plan_intervals](../ras_commander/RasPlan.py), [RasPlan.update_simulation_date](../ras_commander/RasPlan.py), [RasPlan.update_plan_description](../ras_commander/RasPlan.py), [RasPlan.get_plan_title](../ras_commander/RasPlan.py)/[set_plan_title](../ras_commander/RasPlan.py).
- Pattern: Verify changes via ras.plan_df and file reads.

10_1d_hdf_data_extraction.ipynb
- Focus: 1D geometry/results and timeseries queries.
- Functions: [HdfXsec.get_cross_sections](../ras_commander/HdfXsec.py), [HdfResultsXsec.get_xsec_timeseries](../ras_commander/HdfResultsXsec.py), [HdfResultsXsec.get_ref_lines_timeseries](../ras_commander/HdfResultsXsec.py), [HdfResultsXsec.get_ref_points_timeseries](../ras_commander/HdfResultsXsec.py); [HdfResultsPlan.get_runtime_data](../ras_commander/HdfResultsPlan.py).
- Notable cells: locate and print `HDF_Results_Path` and geometry HDF; demonstrate use of decorators to accept plan numbers or paths; optional GeoPandas plots for xsec lines.

11_2d_hdf_data_extraction.ipynb
- Focus: 2D mesh geometry/results basics with spatial plotting.
- Functions: [HdfMesh.get_mesh_area_names](../ras_commander/HdfMesh.py), [HdfMesh.get_mesh_areas](../ras_commander/HdfMesh.py), [HdfMesh.get_mesh_cell_polygons](../ras_commander/HdfMesh.py), [HdfMesh.get_mesh_cell_points](../ras_commander/HdfMesh.py), [HdfMesh.get_mesh_cell_faces](../ras_commander/HdfMesh.py), [HdfBndry.get_breaklines](../ras_commander/HdfBndry.py), [HdfBndry.get_bc_lines](../ras_commander/HdfBndry.py), [HdfResultsMesh.get_mesh_max_ws](../ras_commander/HdfResultsMesh.py)/[get_mesh_min_ws](../ras_commander/HdfResultsMesh.py)/[get_mesh_max_face_v](../ras_commander/HdfResultsMesh.py)/[get_mesh_max_ws_err](../ras_commander/HdfResultsMesh.py), [HdfResultsMesh.get_mesh_timeseries](../ras_commander/HdfResultsMesh.py).
- Notable cells: parse `.rasmap`, list plans, derive run windows; join result attributes back to geometry; toggle `generate_plots` to minimize output size.

12_2d_hdf_data_extraction pipes and pumps.ipynb
- Focus: New 6.6+ pipe networks: conduits, nodes, pumps, timeseries.
- Functions: [HdfPipe.get_pipe_conduits](../ras_commander/HdfPipe.py), [HdfPipe.get_pipe_nodes](../ras_commander/HdfPipe.py), [HdfPipe.get_pipe_network_timeseries](../ras_commander/HdfPipe.py), [HdfPipe.get_pipe_conduit_timeseries](../ras_commander/HdfPipe.py), [HdfPump.get_pump_stations](../ras_commander/HdfPump.py), [HdfPump.get_pump_groups](../ras_commander/HdfPump.py), [HdfPump.get_pump_station_timeseries](../ras_commander/HdfPump.py).
- Notable cells: build network GeoDataFrames, summarize pump groups, plot selected elements; record plan run and extract pump/conduit curves.

13_2d_detail_face_data_extraction.ipynb
- Focus: Face-level analytics along profile lines; unique notebook-only helpers.
- Functions: [HdfMesh.get_mesh_face_property_tables](../ras_commander/HdfMesh.py), [HdfMesh.get_mesh_cell_property_tables](../ras_commander/HdfMesh.py); [HdfResultsMesh.get_mesh_faces_timeseries](../ras_commander/HdfResultsMesh.py).
- Notable cells:
  - Extract `mesh_cell_faces` GeoDataFrame and preview attributes.
  - Unique function `find_nearest_cell_face(point, cell_faces_df)`; returns `(face_id, distance)` and supports plotting the nearest face vs all faces.
  - Profile-line selection along perpendicular faces; compute discharge-weighted velocity; enforce positive flow direction before aggregation.

14_fluvial_pluvial_delineation.ipynb
- Focus: Classify flooding mechanism by timing.
- Functions: [HdfResultsMesh.get_mesh_max_ws](../ras_commander/HdfResultsMesh.py), plus HdfMesh/HdfBndry for polygons/lines.
- Notable cells: compare timing in adjacent cells; map and export boundaries (GeoJSON) after smoothing/filtering short segments.

15_stored_map_generation.ipynb
- Focus: Automate stored map outputs.
- Functions: [RasMap.parse_rasmap](../ras_commander/RasMap.py), [RasMap.postprocess_stored_maps](../ras_commander/RasMap.py).
- Notable cells: backup/modify `.rasmap` and plan flags, launch RAS to bake maps, restore originals after generation.

16_automating_ras_with_win32com.ipynb
- Focus: Open HEC‑RAS/RAS Mapper to refresh stored-map configs.
- Functions: [RasMap.parse_rasmap](../ras_commander/RasMap.py); external `subprocess` to `Ras.exe`.
- Notable cells: manual steps to update mapper, then resume automation.

101_Core_Sensitivity(.ipynb, _aircooled)
- Focus: Runtime vs core count experiments.
- Functions: [RasCmdr.compute_plan](../ras_commander/RasCmdr.py); [RasPlan.set_num_cores](../ras_commander/RasPlan.py).
- Notable cells: sweep cores, record walltime, plot scaling; choose efficient settings.

102_benchmarking_versions_6.1_to_6.6.ipynb
- Focus: Cross-version performance comparison.
- Functions: [init_ras_project](../ras_commander/RasPrj.py) (vary Ras.exe), [RasCmdr.compute_plan](../ras_commander/RasCmdr.py), [HdfResultsPlan.get_runtime_data](../ras_commander/HdfResultsPlan.py).
- Notable cells: control versioned runs, tabulate walltimes per version; keep outputs isolated per version.

103_Running_AEP_Events_from_Atlas_14.ipynb
- Focus: Generate hyetographs from NOAA Atlas 14 and batch scenarios.
- Functions: [RasPlan.clone_plan](../ras_commander/RasPlan.py)/[set_unsteady](../ras_commander/RasPlan.py), [RasUnsteady.*](../ras_commander/RasUnsteady.py), [RasCmdr.compute_parallel](../ras_commander/RasCmdr.py), [HdfResultsMesh](../ras_commander/HdfResultsMesh.py)/[HdfResultsPlan](../ras_commander/HdfResultsPlan.py).
- Notable cells:
  - Read precipitation frequency from Atlas 14 CSVs in `examples/data` and generate balanced storm hyetographs via Alternating Block Method.
  - Parameterize AEP events, clone plans, write unsteady settings, and compute in parallel.
  - Aggregate key metrics from mesh/plan results; optional plots (disable to keep outputs light).

Notebook‑only utilities and unique logic
- `find_nearest_cell_face(...)` (13_2d_detail_face_data_extraction): nearest face selection and plotting; not part of the library API.
- Hyetograph generation for Atlas 14 AEP events (103_*): end‑to‑end pattern from CSV → plan clones → batch compute.
- Profile‑based face aggregation (13_*): discharge‑weighted velocity and flow‑direction normalization.

General Tips
- Use two-digit plan numbers (e.g., "01").
- Keep original projects immutable; use `dest_folder`/suffixes.
- Plotting: GeoPandas for spatial layers; xarray/pandas for timeseries.
- Logging: library functions are decorated; prefer `get_logger(__name__)` for extra context.

