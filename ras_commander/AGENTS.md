# ras_commander Library Contract

This file is the canonical local instruction file for the `ras_commander/` package.

## Scope

- Parent guidance from the repository root `AGENTS.md` still applies.
- This file adds library-local rules for code under `ras_commander/`.
- Read a deeper `AGENTS.md` in a subpackage when the task is centered in `hdf/`, `geom/`, `remote/`, `usgs/`, `check/`, `dss/`, `fixit/`, `precip/`, or `gui/`.

## Core Module Groups

- Project management: `RasPrj`, `init_ras_project()`
- Plan execution: `RasCmdr`
- Plan and model files: `RasPlan`, `RasMap`, `RasControl`, `RasUnsteady` (includes BC CRUD: `delete_boundary()`; IC method selection: `get_initial_flow_method()`, `set_initial_flow_method()`, `get_prior_ws_filename()`, `set_prior_ws_filename()`; IC table: `get_initial_conditions()`, `set_initial_conditions()`, `validate_initial_flow_stations()`; Storage Area IC: `get_initial_storage_elevations()`, `set_initial_storage_elevation()`, `get_min_storage_elevations()`; IC from Output: `set_ic_from_output_profile()`; Non-Newtonian: `get_non_newtonian_method()`, `set_non_newtonian_method()`, `get_non_newtonian_concentration()`, `set_non_newtonian_concentration()`, `get_non_newtonian_shear()`, `set_non_newtonian_shear()`, `get_non_newtonian_herschel_bulkley()`, `set_non_newtonian_herschel_bulkley()`, `get_non_newtonian_clastic()`, `set_non_newtonian_clastic()`; Gate Openings: `get_gate_openings()`, `set_gate_openings()`; Groundwater Interflow: `get_groundwater_interflow()`, `set_groundwater_interflow()`; Navigation Dam: `get_navigation_dam()`, `set_navigation_dam()`; Rule Operations: `get_rules_bc()`, `set_rules_bc()`; Sediment Output: `get_sediment_output_variables()`, `set_sediment_output_variables()` — request optional per-cell 2D sediment outputs such as active-layer gradation, read back via `HdfResultsSediment`)
- Validation framework: `RasValidation`
- Uncertainty / ensembles: `RasPermutation` (parameter sweeps; `execute_and_summarize(workers=)` for distributed execution) and `RasMonteCarlo` (Monte Carlo uncertainty: `generate_samples()` LHS/truncnorm with a single threaded `default_rng`; `run_ensemble(workers=)` distributes plans across a remote fleet when workers are provided, falls back to local `compute_parallel()` otherwise; returns a `status_histogram` and excludes `completed_with_errors` unless `include_error_runs=True`; statistics entry points guard on `min_valid_fraction` (default 0.95); `convergence()` running-statistic stabilization check; `prediction_intervals()`/`confidence_intervals(interval_type=...)`; `make_*_apply_fn` for Manning's n / breach / flow-multiplier perturbation. Flow multiplier is a uniform peak+volume ordinate scaler, not an AEP sample. Morris/Sobol sensitivity is out of scope in this version.)
- RasProcess.exe CLI wrapper: `RasProcess` (stored maps; geometry association; `complete_geometry()` runs HEC-RAS's headless `CompleteGeometry` pipeline — the GUI-free equivalent of RASMapper "compute geometry" — authoring genuine River Edge Lines and the XS Interpolation Surface with the `Source Data Hash`, mutating the geometry HDF in place). Prefer this over GUI automation for edge-line / interpolation-surface generation.
- HDF access: `Hdf*` classes and `ras_commander/hdf/`
- USGS IC generation: `usgs/initial_conditions.py` (`generate_ic_from_usgs()`: auto-discover gauges, match to XS, generate IC table from USGS snapshot)
- Domain subpackages: `geom/`, `remote/`, `usgs/`, `check/`, `dss/`, `fixit/`, `precip/`, `gui/`, `terrain/`

## Coding Rules

- Prefer the existing static-class pattern. Most `Ras*` and `Hdf*` classes should be called directly, not instantiated.
- Use DataFrame-backed project metadata first. Prefer `ras.plan_df`, `ras.geom_df`, `ras.flow_df`, `ras.unsteady_df`, `ras.boundaries_df`, and related helpers over ad hoc filesystem scanning.
- Use `pathlib.Path` consistently for file paths.
- Keep imports ordered `stdlib -> third-party -> local`.
- Public functions should use the repo logging pattern with `get_logger()` and `@log_call`.
- Accept `str` or `Path` when local patterns already do so; avoid introducing narrower path contracts than the surrounding code.

## Multi-Project Work

- Use `RasPrj` instances and the `ras_object=` parameter when a workflow touches more than one project.
- Avoid relying on the global `ras` object in code paths that are supposed to support multiple concurrent projects.

## Execution Rules

- Preserve originals when practical. Prefer `dest_folder=` for plan execution and isolated working directories for derived artifacts.
- Be conservative with `max_workers * num_cores` when parallelizing runs.
- Remote execution details live in [ras_commander/remote/AGENTS.md](remote/AGENTS.md).

## Testing Rules

- Validate against real example projects from `RasExamples` whenever the behavior depends on HEC-RAS semantics.
- Add focused pytest coverage for public APIs or regression fixes.
- Keep generated outputs out of the tracked package tree.

## Directory Navigation

- HDF architecture and extraction patterns: [ras_commander/hdf/AGENTS.md](hdf/AGENTS.md)
- Plain-text geometry parsing: [ras_commander/geom/AGENTS.md](geom/AGENTS.md)
- Remote and distributed execution: [ras_commander/remote/AGENTS.md](remote/AGENTS.md)
- USGS workflows: [ras_commander/usgs/AGENTS.md](usgs/AGENTS.md)
- QA and repair flows: [ras_commander/check/AGENTS.md](check/AGENTS.md), [ras_commander/fixit/AGENTS.md](fixit/AGENTS.md)
- DSS and precipitation helpers: [ras_commander/dss/AGENTS.md](dss/AGENTS.md), [ras_commander/precip/AGENTS.md](precip/AGENTS.md)

## Update Discipline

- Shared library rules belong here or in deeper package `AGENTS.md` files.
- Keep `CLAUDE.md` in this directory as a thin loader only.
