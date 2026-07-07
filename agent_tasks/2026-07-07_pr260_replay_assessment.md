# PR 260 Replay Assessment

Date: 2026-07-07

Context: PR #260 (`codex/docs-notebook-refresh`) was replayed onto current
`origin/main` after the logging/API/documentation PRs landed. The replay applies
one large notebook/docs commit and conflicts only in generated docs navigation
files (`docs/examples/index.md`, `mkdocs.yml`), which should stay aligned with
current `main` and be regenerated after notebook decisions.

## Overall Decision

Do **not** merge PR #260 as a bulk refresh. It mixes useful notebook source
updates with stale output churn, duplicate notebooks, generated-doc rollbacks,
and notebook regressions that would undo work already on `main`.

The replay should be split into targeted branches:

1. API-migration notebook updates that can be rerun and reviewed.
2. Small markdown-only narrative corrections that do not require reruns.
3. Dedicated 601 rename/title work, with metadata/docs/redirects handled
   explicitly.
4. Separate human-reviewed feature notebooks such as 711.

## Drop From Replay

Drop these non-notebook/docs changes because they regress current `main`:

- `.claude/rules/documentation/mkdocs-config.md`:
  reverts canonical `rascommander.info` guidance to older
  GitHub Pages/ReadTheDocs wording.
- `.claude/scripts/prepare_notebooks_for_docs.py`:
  removes generated notebook navigation and shared title/section helpers.
- `docs/requirements-docs.txt`:
  removes `mkdocs-llmstxt`, `folium`, and `branca`.
- `docs/examples/example-projects.md`:
  reverts live MapLibre/New Orleans public artifact content to older pending
  GeoLibre wording.
- `examples/README.md`:
  wholesale stale rewrite with obsolete filenames and numbering.

Drop these duplicate/stale added notebooks:

- `examples/211_fixit_blocked_obstructions.ipynb`:
  exact duplicate of existing `examples/225_fixit_blocked_obstructions.ipynb`.
- `examples/315_validating_dss_paths.ipynb`:
  source-identical duplicate of existing `examples/318_validating_dss_paths.ipynb`
  and collides with existing `315_2d_computation_options.ipynb` numbering.
- `examples/911a_usgs_study_package_from_primitives.ipynb`:
  source-identical duplicate of existing `examples/921_usgs_study_package_from_primitives.ipynb`.
- `examples/918_model_validation_with_usgs.ipynb`:
  stale/code-identical duplicate of existing `examples/922_model_validation_with_usgs.ipynb`.
- `examples/919_stofs3d_coastal_boundary.ipynb`:
  stale duplicate of existing `examples/923_stofs3d_coastal_boundary.ipynb`;
  removes committed sample-data fallback and references the wrong notebook.

Drop or rewrite manually:

- `100_using_ras_examples.ipynb`: backs out current Klawitter coverage.
- `101_project_initialization.ipynb`: replaces exact returned extraction paths
  with reconstructed names.
- `113_parallel_execution.ipynb`: regresses documented long runtime/timeout and
  changes literal `[AllWorkers]` glob behavior.
- `220_calibration_workflow.ipynb`: deletes delivered calibration/validation
  sections and path-sanitizing display helpers.
- `222_steady_flow_calibration.ipynb`: removes first-cell H1 convention.
- `300_unsteady_flow_operations.ipynb`: removes lateral-inflow deletion section.
- `301_flow_hydrograph_optimization.ipynb`: removes first-cell H1 convention.
- `312_boundary_df_qmult_dss_paths.ipynb`: removes important guards and numeric
  comparisons.
- `314_reference_line_generation.ipynb`: weakens validation failures into
  warnings/skips; any `HdfResultsAnalysis` addition should be reimplemented
  cleanly.
- `320_1d_boundary_condition_visualization.ipynb`: contains a Python syntax
  error and flips GUI visualization on by default.
- `410_2d_hdf_data_extraction.ipynb`: reverts current helper setup and has
  inconsistent plan selection.
- `415_2d_spatial_result_queries.ipynb`: reverts current setup helpers and
  strips outputs.
- `430_1d_channel_capacity_analysis.ipynb`: regresses quieter logging, robust
  repo-root detection, HEC-RAS 7.0 migration note, workspace behavior, and
  existing/proposed comparison.
- `500_remote_execution_psexec.ipynb`: removes UNC authentication before cleanup.
- `510_linux_execution.ipynb`: removes cross-cell Linux guard.
- `610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.ipynb`:
  adds generic/regulatory prose, introduces `datframe` typo, and weakens method
  description.
- `723_storm_generator_abm_validation.ipynb`: introduces stale/wrong-cased
  notebook reference.
- `910_usgs_gauge_catalog.ipynb`: changes to a nonexistent notebook reference.
- `915_realtime_forecast_workflow.ipynb`: introduces nonexistent
  `examples/720_atlas14_aep_events.ipynb` reference.
- `930_terrain_modification_analysis.ipynb`: removes first-cell H1 markdown.

## Candidate Targeted Work

API-migration notebooks, rerun/review required:

- `103_plan_and_geometry_operations.ipynb`: `RasGeo` -> `GeomPreprocessor`.
- `121_legacy_hecrascontroller_and_rascontrol.ipynb`: small API naming/doc update.
- `201_1d_plaintext_geometry.ipynb`: `RasGeometry` -> `GeomCrossSection`.
- `202_2d_plaintext_geometry.ipynb`: split to `GeomStorage` / `GeomLateral`.
- `203_htab_parameter_optimization.ipynb`: `GeomCrossSection` cleanup.
- `316_terrain_modifications.ipynb`: `HdfBenefitAreas` demonstration and
  local artifact path cleanup.
- `400_1d_hdf_data_extraction.ipynb`: adds `HdfStorageArea` volume-elevation
  demo and replaces huge xarray displays with summaries.
- `700_core_sensitivity.ipynb`, `701_benchmarking_versions_6.1_to_6.6.ipynb`,
  and `710_mannings_sensitivity_bulk_analysis.ipynb`: preserve
  `RasGeo`/land-cover API migrations, but clean and rerun `700`/`701`.

Markdown-only candidates, no notebook rerun normally required:

- `914_historical_event_validation.ipynb`: avoid implying nonexistent
  `RasGeometry2D.create_lateral_bc_from_gauge` API, but coordinate with held
  PR #251.
- `916_hrrr_precipitation_forecast.ipynb`.
- `917_mrms_precipitation_qpe.ipynb`.
- `918_hms_ras_coupled_forecast.ipynb`.
- `919_operational_forecast_cycling.ipynb`.
- `950_ebfe_spring_creek.ipynb`.
- `951_ebfe_north_galveston_bay.ipynb`.
- `952_ebfe_upper_guadalupe_cascade.ipynb`.

Dedicated 601 rename/title work:

- Replace `601_floodplain_mapping_rasprocess.ipynb` with
  `601_headless_stored_map_generation_rasmapper.ipynb` only in a dedicated PR.
- Update `examples/notebooks.yml`, generated docs/index data, navigation, and
  redirects in the same PR.
- Rerun and independently review the notebook before publication.

Dedicated human-reviewed feature work:

- `711_mannings_sensitivity_multi_interval.ipynb` is a substantive remote/Sabinal
  workflow rewrite and should not be bundled with notebook cleanup.

## Output-Only / Metadata-Only

Generally drop output-only and metadata-only churn unless the objective is an
explicit, reviewed notebook-output refresh.

Examples: `102`, `104`, `110`, `111`, `112`, `115`, `120`, `150`, `206`, `207`,
`211_final`, `217`, `231`, `310`, `401`, `420`, `560`, `725`, `801`, `911`,
`920`, `925`, `958`.
