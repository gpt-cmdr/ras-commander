# Example Notebook Inventory Audit - 2026-06-26

## Purpose

Audit the `examples/*.ipynb` inventory for naming clarity, navigation order,
demonstration completeness, and hydrologic/hydraulic usefulness. This audit was
requested after reviewing the published 900-series forecast pages, especially
the operational forecast workflow notebooks.

## Current Inventory Findings

- Top-level inventory: 116 notebooks.
- Saved-output status from committed notebooks: 72 have saved outputs, 44 have
  no saved outputs, and 0 have stored error outputs.
- The docs pipeline relies on saved notebook outputs, so no-output notebooks
  currently publish as templates or code walkthroughs rather than demonstrated
  workflows.

## Naming and Navigation Problems

### Duplicate or Conflicting Numbers

- `116_hdf_output_options_benchmark.ipynb`
- `116_monte_carlo_uncertainty.ipynb`
- `211_final_mannings_and_infiltration.ipynb`
- `211_fixit_blocked_obstructions.ipynb`
- `315_2d_computation_options.ipynb`
- `315_validating_dss_paths.ipynb`
- `918_hms_ras_coupled_forecast.ipynb`
- `918_model_validation_with_usgs.ipynb`
- `919_operational_forecast_cycling.ipynb`
- `919_stofs3d_coastal_boundary.ipynb`
- `911_usgs_gauge_data_integration.ipynb` / `911a_usgs_study_package_from_primitives.ipynb`

### Title and Convention Problems

- `721_Precipitation_Hyetograph_Comparison.ipynb` violates the lowercase
  underscore filename convention.
- Example titles should describe the HEC-RAS task or hydraulic/hydrologic
  workflow. Do not use filler such as `with ras-commander`, `using
  ras-commander`, or `RAS Commander:` in notebook H1s; the library context is
  implied by the documentation site.
- `900_aorc_precipitation.ipynb` and `901_aorc_precipitation_catalog.ipynb`
  have the same H1.
- Legacy page titles remain in the 900-series:
  `912_usgs_real_time_monitoring.ipynb` says `Example 30`,
  `913_bc_generation_from_live_gauge.ipynb` says `Example 31`, and
  `918_model_validation_with_usgs.ipynb` says `Example 32`.
- Several notebooks violate the first-cell markdown H1 convention, including
  `122`, `123`, `124`, `209`, `210`, `213`, `216`, `222`, `223`, `224`,
  `301`, `311`, `314`, `315_2d_computation_options`, `413`, and
  `930_terrain_modification_analysis.ipynb`.

### Broken or Risky Navigation

- `docs/examples/index.md` and `mkdocs.yml` reference
  `232_weise_2d_sediment_mesh_sensitivity.ipynb`, but that file is not present.
- Renaming notebooks changes published URLs because docs pages are generated
  from notebook filenames. There is no redirect policy in `mkdocs.yml` today.

## 900-Series Recommended Renumbering

Preserve old URLs with redirects if these files are renamed.

| Current | Proposed |
|---|---|
| `911a_usgs_study_package_from_primitives.ipynb` | `912_usgs_study_package_from_primitives.ipynb` |
| `912_usgs_real_time_monitoring.ipynb` | `913_usgs_real_time_monitoring.ipynb` |
| `913_bc_generation_from_live_gauge.ipynb` | `914_bc_generation_from_live_gauge.ipynb` |
| `914_historical_event_validation.ipynb` | `915_historical_event_validation.ipynb` |
| `918_model_validation_with_usgs.ipynb` | `916_model_validation_with_usgs.ipynb` |
| `915_realtime_forecast_workflow.ipynb` | `920_realtime_forecast_workflow_overview.ipynb` |
| `916_hrrr_precipitation_forecast.ipynb` | `921_hrrr_precipitation_forecast.ipynb` |
| `917_mrms_precipitation_qpe.ipynb` | `922_mrms_precipitation_qpe.ipynb` |
| `918_hms_ras_coupled_forecast.ipynb` | `923_hms_ras_coupled_forecast.ipynb` |
| `919_operational_forecast_cycling.ipynb` | `924_operational_forecast_cycling.ipynb` |
| `919_stofs3d_coastal_boundary.ipynb` | `925_stofs3d_coastal_boundary.ipynb` |
| `920_terrain_creation.ipynb` | `930_terrain_creation.ipynb` |
| `925_xs_interpolation_surface.ipynb` | `931_xs_interpolation_surface.ipynb` |
| `930_terrain_modification_analysis.ipynb` | `932_terrain_modification_analysis.ipynb` |

## Highest Priority Content Gaps

1. `919_operational_forecast_cycling.ipynb`: was template-only with placeholder
   paths and random peak WSE. This pass replaced that with deterministic
   forecast-cycle hydrology, routed hydrographs, stage thresholds, and
   convergence figures. Follow-up should connect the same cycle loop to a real
   HEC-RAS project and extract WSE/depth/velocity after each run.
2. `915_realtime_forecast_workflow.ipynb`: currently an overview/template.
   Rename as an overview or expand into a runnable capstone.
3. `918_hms_ras_coupled_forecast.ipynb`: useful coupling pattern, but weak
   evidence when `hms-commander` or a real HMS project is absent. Expand with
   a real HMS/RAS handoff or rename as a template.
4. `914_historical_event_validation.ipynb` and
   `918_model_validation_with_usgs.ipynb`: should become the validation
   backbone with saved hydrographs, scatter/residual plots, NSE/KGE/RMSE/PBIAS,
   and peak timing error.
5. `930_terrain_modification_analysis.ipynb`: should be rebuilt as a
   before/after terrain plus computed WSE/depth/velocity difference workflow.
6. `911_usgs_gauge_data_integration.ipynb`: strong data retrieval and QAQC,
   but needs a model/gauge/boundary overview map and either a clearer retrieval
   name or expansion into a full downstream simulation/validation workflow.

## Evidence Patterns to Add Across the Inventory

- Model overview maps with basin, model extent, gauge locations, boundary
  condition locations, structures, and decision points.
- Boundary-condition plots before and after modification.
- Result comparisons by practical hydraulic quantity: WSE, depth, velocity,
  flow, inundation extent, or threshold exceedance duration.
- Observed validation for event notebooks: USGS stage/flow hydrographs,
  residuals, error metrics, and peak timing errors.
- Tables with units and reviewable precision.
- Cleaner stored outputs: avoid huge local-path-heavy notebooks unless the
  notebook is explicitly labeled as heavy/advanced.

## Immediate Follow-Up Checklist

- Add redirects before file renames are merged.
- Fix missing `232_weise_2d_sediment_mesh_sensitivity.ipynb` nav references.
- Normalize 900-series H1 titles and remove stale `Example 30/31/32` labels.
- Keep title cleanup scoped to names/headings; retain `ras-commander` mentions
  in API explanation, installation comments, and code where the library name is
  semantically useful.
- Decide whether `915`, `918_hms_ras`, and `919_operational` remain separate
  notebooks or are combined into one forecast operations chapter with
  supporting input-data appendices.
- Execute enriched notebooks and run notebook-review before accepting them as
  production examples.
