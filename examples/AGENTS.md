# Examples Notebook Contract

This file is the canonical local instruction file for `examples/`.

## Scope

- Parent guidance from the repository root `AGENTS.md` still applies.
- Notebooks are reference workflows for humans. Extract repeatable logic into scripts or library changes instead of leaving important automation only in notebooks.

## Notebook Workflow

1. Read code cells first. Ignore long outputs and images unless the task depends on them.
2. Understand the data flow and any environment-specific paths.
3. Extract useful logic into a script, CLI, or library change.
4. Execute derived scripts in a writable working folder such as `working/`.
5. Keep notebook modifications minimal and restore import cells to the standard committed state before finishing.

## Notebook Families

- `100s` - project initialization, plan operations, execution, callbacks
- `200s` - plain-text geometry parsing and HTAB workflows
- `300s` - unsteady flow files, DSS boundaries, boundary visualization
- `400s` - HDF geometry and results extraction
- `700s` - Atlas 14, design storms, and precipitation workflows
- `800s` - QA and validation workflows
- `900s` - forecasting, terrain, USGS, and operational workflows
- `950s` - FEMA eBFE model organization
- `960s` - cloud-native export workflows

## High-Value Reference Notebooks

- `100_using_ras_examples.ipynb` - extracting official example projects
- `101_project_initialization.ipynb` - project metadata and DataFrame patterns
- `110_single_plan_execution.ipynb` and `113_parallel_execution.ipynb` - execution patterns
- `201_1d_plaintext_geometry.ipynb`, `203_htab_parameter_optimization.ipynb`, `205_extract_xs_xyz_from_geometry.ipynb` - geometry parsing and HTAB work
- `218_infiltration_base_override_authoring.ipynb` - programmatic infiltration group creation and Base Override round-trip
- `310_validating_dss_paths.ipynb` and `312_boundary_df_qmult_dss_paths.ipynb` - DSS workflows
- `410_2d_hdf_data_extraction.ipynb` and `412_2d_detail_face_data_extraction.ipynb` - mesh and results extraction
- `421_usgs_gauge_data_integration.ipynb` through `424_model_validation_with_usgs.ipynb` - USGS integration
- `720_atlas14_aep_events.ipynb`, `725_atlas14_spatial_variance.ipynb`, `726_abm_hyetograph_grid.ipynb` - precipitation methods
- `915_realtime_forecast_workflow.ipynb` through `919_operational_forecast_cycling.ipynb` - operational forecast patterns
- `930_terrain_modification_analysis.ipynb` - terrain modification workflows
- `960_cloud_native_geometry_export.ipynb` through `962_cloud_native_cog_results_export.ipynb` - `ras2cng` export patterns

## Import Cell Convention

- Default committed state:
  - Cell 0 is active pip-mode import code.
  - Cell 1 is markdown containing dev-mode instructions.
- For local development testing, temporarily flip those cells, then restore the committed state before finishing.
- Never leave both cells active as code.

## Notebook-Only Logic

- If a notebook contains logic that should become a reusable API, call it out explicitly and extract it instead of duplicating it elsewhere.
- Examples already document some notebook-only patterns such as face aggregation, forecast-cycle loops, and specialized visualization helpers.

## Data And Outputs

- Do not commit extracted example datasets, heavy outputs, or ad hoc images.
- Small reference assets under `examples/data/` are read-only. Use root-level working folders for generated data.

## Where To Go Next

- Package code changes belong under [ras_commander/AGENTS.md](../ras_commander/AGENTS.md).
- Online example docs live under `docs/examples/`.
