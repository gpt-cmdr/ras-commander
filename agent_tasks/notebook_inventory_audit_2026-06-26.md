# Example Notebook Inventory Audit - 2026-06-26

## Purpose

Audit the `examples/*.ipynb` inventory for naming clarity, navigation order,
demonstration completeness, and hydrologic/hydraulic usefulness. This audit was
requested after reviewing the published forecast pages, especially `915`, `918`,
and `919`.

## Current Inventory Findings

- Top-level inventory on current `main`: 124 notebooks.
- Saved-output status from committed notebooks: 118 have saved outputs, 6 have
  no saved outputs, and 0 have stored error outputs.
- All top-level notebooks currently have a markdown H1 title.
- One duplicate numeric prefix remains: `219_1d_bridge_xs_plotting.ipynb` and
  `219_mannings_region_polygon_authoring.ipynb`.
- The docs pipeline relies on saved notebook outputs, so no-output notebooks
  publish as templates or code walkthroughs rather than demonstrated workflows.

## Changes Applied In This Pass

- Renamed `610_fluvial_pluvial_delineation.ipynb` to
  `610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.ipynb`.
- Added a MkDocs redirect from the old 610 URL to the new 610 URL.
- Removed generic `with ras-commander` / `using ras-commander` wording from
  notebook titles and headings touched in this pass.
- Grouped generated docs sections into practical sub-series so the forecast
  sequence is readable:
  - `915`, `918_hms`, and `919_operational` now appear together as the
    operational forecast sequence.
  - `916`, `917`, `923`, and `924` are grouped as forecast inputs.
  - `920`, `925`, and `930` are grouped as terrain and surface workflows.
  - `950s` and `960s` are no longer buried under the broad 900s group.
- Regenerated `docs/examples/index.md` and `examples/README.md` from the actual
  notebook inventory.

## Hydrologic/Hydraulic Relevance

`919_operational_forecast_cycling.ipynb` was the highest-priority content gap.
It previously read like a scheduling template: placeholder project paths,
random peak WSE values, and no decision-relevant figures.

This pass replaced that with deterministic forecast-cycle hydrology:

- Four issued forecast cycles for the same event window.
- Basin-average QPF hyetographs in inches/hour.
- Routed outlet flow hydrographs in cfs.
- A simple monotonic stage response in feet.
- Action, flood, and major-flood thresholds.
- Stored figures comparing precipitation, flow, stage, peak-stage convergence,
  and flood-threshold exceedance duration.

The notebook is still an educational demonstration, not a production forecast
model. The next improvement should connect the same cycle loop to a real
HEC-RAS project and extract WSE/depth/velocity after each RAS run.

## Remaining Naming And Completeness Issues

- `219_1d_bridge_xs_plotting.ipynb` and
  `219_mannings_region_polygon_authoring.ipynb` still share the `219` prefix.
- Some 900-series notebooks remain template-like and would benefit from real
  model/gauge evidence:
  - `915_realtime_forecast_workflow.ipynb` is best treated as an overview unless
    expanded into a runnable capstone.
  - `918_hms_ras_coupled_forecast.ipynb` should eventually use a real HMS/RAS
    handoff with saved hydrographs and boundary evidence.
  - `914_historical_event_validation.ipynb` and
    `922_model_validation_with_usgs.ipynb` should become the validation backbone
    with observed hydrographs, residuals, NSE/KGE/RMSE/PBIAS, and peak timing
    error.
  - `930_terrain_modification_analysis.ipynb` should be rebuilt as a before/after
    terrain plus WSE/depth/velocity difference workflow.
  - `911_usgs_gauge_data_integration.ipynb` has useful retrieval and QAQC logic
    but needs a model/gauge/boundary overview map and a clearer simulation or
    validation end point.

## Evidence Patterns To Add Across The Inventory

- Model overview maps with basin, model extent, gauge locations, boundary
  locations, structures, and decision points.
- Boundary-condition plots before and after modification.
- Result comparisons by practical hydraulic quantity: WSE, depth, velocity,
  flow, inundation extent, or threshold exceedance duration.
- Observed validation for event notebooks: USGS stage/flow hydrographs,
  residuals, error metrics, and peak timing errors.
- Tables with units and reviewable precision.
- Cleaner stored outputs: avoid huge local-path-heavy notebooks unless the
  notebook is explicitly labeled as heavy/advanced.

## Immediate Follow-Up Checklist

- Decide whether the remaining duplicate `219` notebooks should be renumbered or
  combined.
- Expand the overview/template forecast notebooks into real model examples or
  label them explicitly as conceptual patterns.
- Continue applying redirects whenever notebook filenames change.
