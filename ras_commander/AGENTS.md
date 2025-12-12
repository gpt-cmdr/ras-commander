**Note**: This AGENTS.md file is being migrated to CLAUDE.md format for broader LLM compatibility. See `ras_commander/CLAUDE.md` for Claude Code guidance. This file will be maintained through v0.90.0 and deprecated in v0.91.0+.

**Scope**
- Guidance for agents working inside `ras_commander/` (the core library). Inherits root policies; adds coding and API usage specifics.

**Module Layout (key classes)**
- `RasPrj` (`RasPrj.py`): Initialize and manage a RAS project. Exposes dataframes: `plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`. Helpers: `init_ras_project()`, `get_ras_exe()`.
- `RasPlan` (`RasPlan.py`): Clone/retarget plans, update intervals, cores, run flags, titles/descriptions, geometry/unsteady bindings.
- `RasCmdr` (`RasCmdr.py`): Execute plans (single/sequential/parallel). `compute_plan()`, `compute_parallel()`, `compute_test_mode()`.
- `RasControl` (`RasControl.py`): Legacy HEC-RAS support (3.x-4.x) via COM interface. ras-commander style API with plan numbers. `run_plan()`, `get_steady_results()`, `get_unsteady_results()`, `get_output_times()`, `set_current_plan()`.
- `RasMap` (`RasMap.py`): Parse `.rasmap`, post-process stored maps.
- `Hdf*` modules: Geometry and results accessors.
  - `HdfBase`, `HdfUtils`: shared helpers.
  - `HdfMesh`, `HdfBndry`, `HdfXsec`, `HdfStruc`, `HdfPlan`.
  - `HdfResultsMesh`, `HdfResultsPlan`, `HdfResultsXsec`, `HdfResultsPlot`.
  - `HdfPipe`, `HdfPump`, `HdfInfiltration`, `HdfFluvialPluvial`.
  - `HdfPlot`: convenience plotting helpers.

**Conventions**
- Static namespaces: Many classes expose only `@staticmethod`s. Do not instantiate unless design requires state.
- Plan numbers: Use two digits (e.g., "01"). Helpers accept both strings and paths.
- Logging: `from ras_commander import get_logger, log_call`; then `logger = get_logger(__name__)`; decorate public methods with `@log_call`.
- Imports: stdlib → third‑party → local; keep ≤79 chars where practical.

**Input Normalization (standardize_input)**
- Most HDF-facing functions are decorated with `@standardize_input(file_type=...)` and accept:
  - An `h5py.File`, a `Path`, a string path, or a plan/geom number (e.g., "01", "p01").
  - A `ras_object` kwarg to disambiguate when multiple projects are active.
- `file_type='plan_hdf'` or `'geom_hdf'` resolves plan/geometry HDF paths via the active `RasPrj`.
- Functions may also accept `hdf_file` as the first arg to work directly with an open `h5py.File`.

**Common Recipes**
- Initialize and compute:
  - `from ras_commander import init_ras_project, RasCmdr`
  - `init_ras_project(<project_folder>, <path_to_Ras.exe>)`
  - `RasCmdr.compute_plan("01", dest_folder="working/run01", overwrite_dest=True)`
- 2D mesh basics:
  - `from ras_commander import HdfMesh, HdfResultsMesh`
  - `cells = HdfMesh.get_mesh_cell_polygons("06")`
  - `faces = HdfMesh.get_mesh_cell_faces("06")`
  - `ts = HdfResultsMesh.get_mesh_timeseries("06", variables=["Water Surface"] )`
- 1D cross sections:
  - `from ras_commander import HdfXsec, HdfResultsXsec`
  - `xsecs = HdfXsec.get_cross_sections("01")`
  - `xs_ts = HdfResultsXsec.get_xsec_timeseries("01", river="...")`
- Pipes and pumps (HEC-RAS 6.6+):
  - `from ras_commander import HdfPipe, HdfPump`
  - `pipes = HdfPipe.get_pipe_conduits("02")`
  - `pumps = HdfPump.get_pump_stations("02")`
- Legacy version extraction (HEC-RAS 3.x-4.x):
  - `from ras_commander import init_ras_project, RasControl`
  - `init_ras_project(path, "4.1")  # Specify version`
  - `RasControl.run_plan("02")  # Use plan numbers`
  - `df_steady = RasControl.get_steady_results("02")`
  - `df_unsteady = RasControl.get_unsteady_results("01", max_times=10)`
  - Note: Uses plan numbers like HDF methods; automatically closes HEC-RAS to prevent conflicts

**Face/Cell Utilities (from examples, not library)**
- The examples include a notebook-only helper `find_nearest_cell_face(point, cell_faces_df)` that computes nearest faces to a point and plots selections. It is not part of the library API; port into scripts as needed.

**Performance & Execution**
- `RasCmdr.compute_plan(..., num_cores=N)`: choose modest N (2–8) unless models benefit from higher parallelism.
- `RasCmdr.compute_parallel(...)`: multiply `max_workers * num_cores` conservatively relative to physical cores/RAM.
- Use `dest_folder` or temporary copies to keep originals immutable.

**Testing & Examples**
- Prefer `ras_commander.RasExamples` to extract official models into a writable location. Avoid committing extracted content.
- See `examples/AGENTS.md` for a task-oriented index of notebooks and unique snippets.

**Out of Scope for Agents**
- `ai_tools/` knowledge base generation. Do not read or run those scripts; they are maintainer-only.

