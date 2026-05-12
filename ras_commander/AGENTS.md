# ras_commander Library Contract

This file is the canonical local instruction file for the `ras_commander/` package.

## Scope

- Parent guidance from the repository root `AGENTS.md` still applies.
- This file adds library-local rules for code under `ras_commander/`.
- Read a deeper `AGENTS.md` in a subpackage when the task is centered in `hdf/`, `geom/`, `remote/`, `usgs/`, `check/`, `dss/`, `fixit/`, `precip/`, or `gui/`.

## Core Module Groups

- Project management: `RasPrj`, `init_ras_project()`
- Plan execution: `RasCmdr`
- Plan and model files: `RasPlan`, `RasMap`, `RasControl`, `RasUnsteady` (includes IC method selection: `get_initial_flow_method()`, `set_initial_flow_method()`, `get_prior_ws_filename()`, `set_prior_ws_filename()`; IC table: `get_initial_conditions()`, `set_initial_conditions()`, `validate_initial_flow_stations()`; Non-Newtonian: `get_non_newtonian_method()`, `set_non_newtonian_method()`)
- Validation framework: `RasValidation`
- HDF access: `Hdf*` classes and `ras_commander/hdf/`
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
