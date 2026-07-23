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
- `200s` - plain-text geometry parsing, structures, roughness, geometry authoring, calibration, and mesh workflows
- `300s` - unsteady flow files, DSS boundaries, HMS matching, terrain modifications, and boundary visualization
- `400s` - HDF geometry, hydraulic results, breach results, velocity profiles, and channel-capacity extraction
- `500s` - remote execution, Linux execution, and ModPuls result extraction
- `600s` - floodplain mapping, fluvial-pluvial delineation, and map-layer validation
- `700s` - sensitivity testing, benchmarking, Atlas 14, design storms, and precipitation workflows
- `800s` - QA and validation workflows
- `900s` - AORC, USGS, real-time forecasting, STOFS-3D, terrain, and operational workflows
- `950s` - FEMA eBFE model organization and validation
- `960s` - cloud-native export workflows

## High-Value Reference Notebooks

- `100_using_ras_examples.ipynb` - extracting official example projects
- `101_project_initialization.ipynb` - project metadata and DataFrame patterns
- `110_single_plan_execution.ipynb` and `113_parallel_execution.ipynb` - execution patterns
- `510_linux_execution.ipynb` and `511_headless_linux_wine_ras2cng.ipynb` - vendor Linux solver execution and qualified Wine/Ras2Cng setup
- `201_1d_plaintext_geometry.ipynb`, `203_htab_parameter_optimization.ipynb`, `205_extract_xs_xyz_from_geometry.ipynb` - geometry parsing and HTAB work
- `218_infiltration_base_override_authoring.ipynb` and `225_fixit_blocked_obstructions.ipynb` - infiltration and repair workflows
- `312_boundary_df_qmult_dss_paths.ipynb` and `318_validating_dss_paths.ipynb` - DSS workflows
- `410_2d_hdf_data_extraction.ipynb`, `412_2d_detail_face_data_extraction.ipynb`, `413_profile_line_flow_extraction.ipynb`, and `416_2d_velocity_profile_line.ipynb` - mesh and results extraction
- `910_usgs_gauge_catalog.ipynb` through `919_operational_forecast_cycling.ipynb` - USGS, AORC validation, and forecast workflows
- `921_usgs_study_package_from_primitives.ipynb` through `923_stofs3d_coastal_boundary.ipynb` - USGS study, validation, and coastal boundary workflows
- `924_mrms_netcdf_rain_on_grid.ipynb` - direct MRMS NetCDF rain-on-grid validation on a RasExamples project
- `720_precipitation_methods_comprehensive.ipynb`, `721_precipitation_hyetograph_comparison.ipynb`, `725_atlas14_spatial_variance.ipynb`, and `726_abm_hyetograph_grid.ipynb` - precipitation methods
- `915_realtime_forecast_workflow.ipynb` through `919_operational_forecast_cycling.ipynb` - operational forecast patterns
- `920_terrain_creation.ipynb`, `925_xs_interpolation_surface.ipynb`, and `930_terrain_modification_analysis.ipynb` - terrain and geometry surface workflows
- `950_ebfe_spring_creek.ipynb` through `958_model_sources_showcase.ipynb` - eBFE delivery and model source workflows
- `960_cloud_native_geometry_export.ipynb` through `962_cloud_native_cog_results_export.ipynb` - `ras2cng` export patterns

## Import Cell Convention

- Default committed state:
  - Cell 0 is markdown with an H1 title matching the notebook topic.
  - The first setup code cell keeps the active import/development toggle state used by that notebook.
- For local development testing, temporarily adjust setup toggles, then restore the committed state before finishing.

## Notebook-Only Logic

- If a notebook contains logic that should become a reusable API, call it out explicitly and extract it instead of duplicating it elsewhere.
- Examples already document some notebook-only patterns such as face aggregation, forecast-cycle loops, and specialized visualization helpers.

## Data And Outputs

- Do not commit extracted example datasets, heavy outputs, or ad hoc images.
- Small reference assets under `examples/data/` are read-only. Use root-level working folders for generated data.

## Where To Go Next

- Package code changes belong under [ras_commander/AGENTS.md](../ras_commander/AGENTS.md).
- Online example docs live under `docs/examples/`.
