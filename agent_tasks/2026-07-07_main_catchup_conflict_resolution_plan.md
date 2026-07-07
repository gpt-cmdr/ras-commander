# Main Catch-Up Conflict Resolution Plan - 2026-07-07

## Context

Local feature branch:

- Branch: `feature/711-rasremote-mannings-sensitivity`
- Feature head: `d79cd753 docs(agent_tasks): record culvert fixture scan`
- Remote: `origin/feature/711-rasremote-mannings-sensitivity`
- Current status before this task document: clean and pushed

Main branch at audit time:

- `origin/main`: `e6e2324b fix(examples/319): continuous thalweg breakline + de-bold notebook (#256)`

An attempted merge of `origin/main` into the feature branch produced a broad
conflict set. The merge was aborted to keep the local branch clean. The conflict
inventory below was reproduced in a detached audit worktree:

- `G:\GH\ras-commander-conflict-audit`

## Objective

Bring the useful feature-branch improvements forward without losing independent
work already on `origin/main`.

This should not be treated as a mechanical merge. In many files, current main
has moved substantially and the right answer is to reassess the feature branch
change, then re-implement the useful logging/API behavior on top of current
main.

## Recommended Strategy

1. Keep `feature/711-rasremote-mannings-sensitivity` as the preserved aggregate
   history branch.
2. Do not merge that aggregate branch directly into `main`.
3. Work from fresh branches off `origin/main`, one review group at a time.
4. Use the existing clean PR branches as references where possible:
   - `codex/logging-verbosity`
   - `codex/hdf-diagnostics`
   - `codex/unsteady-precip-hydrograph`
   - `codex/docs-notebook-refresh`
5. For every conflicted file:
   - Inspect `origin/main`, the feature branch, and any clean PR branch that
     touched the same behavior.
   - Decide whether to accept main, port feature behavior, or combine both.
   - Re-run the most relevant focused tests or notebook.
   - Update this task document with the decision and validation.
6. Preserve notebook source/input changes only. Do not carry forward
   output-only rerun churn.

## Conflict Status Legend

- `UU`: both sides modified the file.
- `AA`: both sides added the file independently.
- `UD`: feature branch modified the file, `origin/main` deleted it.

## Conflict Summary

- Total conflict files: 41
- Notebooks: 20
- `ras_commander` API/test files: 15
- Docs/config/task files: 6

## API And Test Conflicts

| Status | File | Initial resolution plan | State |
|---|---|---|---|
| `UU` | `ras_commander/RasCmdr.py` | Combine carefully. Preserve `origin/main` execution fixes, especially stdio redirection / CLB-880 deadlock avoidance and in-place `dest_folder` behavior. Reapply feature logging policy: concise INFO for command execution, full command/path at DEBUG, and timeout behavior only if still needed and compatible with main. | Not started |
| `AA` | `ras_commander/RasMonteCarlo.py` | Treat `origin/main` as the base because the file has broad current-main evolution. Port feature logging/diagnostic improvements for missing HDFs and extraction errors if not already present. Re-run Monte Carlo stats tests. | Not started |
| `UU` | `ras_commander/RasPermutation.py` | Preserve current-main API behavior. Reapply concise logging changes and tests only where still applicable. | Not started |
| `UU` | `ras_commander/RasUnsteady.py` | Preserve current-main unsteady APIs. Check whether paired precipitation hydrograph behavior from the feature branch is already present; if not, port it with focused tests. Keep concise logging. | Not started |
| `UU` | `ras_commander/__init__.py` | Preserve current-main exports and lazy import structure. Add only missing exports from the feature branch after confirming they still exist and are public API. Watch for formatting/trailing whitespace after conflict resolution. | Not started |
| `UU` | `ras_commander/geom/GeomMesh.py` | Preserve current-main geometry/cell/culvert work. Reapply feature logging changes where they do not weaken direct API errors for missing 2D mesh data. | Not started |
| `UU` | `ras_commander/gui/screenshots.py` | Preserve current-main screenshot behavior. Reapply concise logging and any supporting tests after checking current-main API shape. | Not started |
| `UU` | `ras_commander/hdf/HdfChannelCapacity.py` | Combine. Preserve current-main HDF behavior and any channel-capacity improvements. Reapply feature diagnostics, including geometry-preprocessor guidance and cubic unit handling if still absent. Re-run HDF channel-capacity tests. | Not started |
| `UU` | `ras_commander/remote/DockerWorker.py` | Preserve current-main Docker/remote behavior. Reapply logging-level changes for concise defaults and DEBUG paths. | Not started |
| `UU` | `ras_commander/remote/Execution.py` | Preserve current-main execution behavior. Reapply concise logging and full-path-at-DEBUG policy. | Not started |
| `UU` | `ras_commander/terrain/RasTerrain.py` | Preserve current-main terrain fixes, including GDAL/PROJ environment handling and HDF validation from recent main work. Reapply feature logging changes only after re-reviewing notebook output impact. | Not started |
| `UU` | `ras_commander/terrain/Usgs3depAws.py` | Preserve current-main data acquisition behavior. Reapply concise logging and path suppression at INFO where useful. | Not started |
| `AA` | `tests/test_ras_montecarlo_stats.py` | Treat current-main test file as base; port missing feature tests for summarized warnings/debug paths if behavior is kept. | Not started |
| `UU` | `tests/test_rascalibrate_steady.py` | Preserve current-main calibration test coverage. Port only feature assertions that still match the rewritten calibration workflow. | Not started |
| `UU` | `tests/test_usgs_spatial.py` | Preserve current-main USGS spatial tests. Port concise logging/path-suppression tests if still relevant. | Not started |

## Docs, Config, And Agent Task Conflicts

| Status | File | Initial resolution plan | State |
|---|---|---|---|
| `UU` | `.claude/rules/hec-ras/land-cover-mannings-n.md` | Combine. Preserve current-main land-cover/Manning guidance and add any feature-branch logging or notebook-output policy only if not already covered elsewhere. | Not started |
| `AA` | `agent_tasks/notebook_inventory_audit_2026-06-26.md` | Combine if useful, but avoid duplicate audit sections. Prefer current-main structure if it has been expanded; append feature findings only when still actionable. | Not started |
| `AA` | `docs/examples/example-projects.md` | Prefer current-main published WebGIS/MapLibre example-library content. Port feature policy text only if it adds durable guidance not already present. | Not started |
| `UU` | `docs/examples/index.md` | Prefer current-main generated or updated notebook index. Reapply renamed notebook references only if those notebooks remain after current-main renumbering. | Not started |
| `UU` | `docs/requirements-docs.txt` | Combine dependencies. Keep current-main docs requirements and add feature-only requirements only if still used by the docs build. | Not started |
| `UU` | `examples/README.md` | Prefer current-main example inventory and renumbering. Add feature notes only if they remain accurate after notebook renames. | Not started |
| `UU` | `mkdocs.yml` | Do not hand-resolve blindly. Prefer current-main navigation/generator output, then re-run or update the docs nav generator. Reapply feature notebook renames only if still valid. | Not started |

## Notebook Conflicts

General notebook policy:

- Review each notebook independently with subagents. Do not assume `origin/main`
  or the feature branch wins by default.
- Compare notebook input cells structurally, not by raw JSON diff. The feature
  branch includes intentional input-cell edits in some notebooks and output
  changes from full notebook reruns.
- Output-cell differences are not automatically discarded. If notebook source
  changes are retained, rerun the notebook to regenerate faithful current
  outputs and review those outputs for professionalism, concision, and technical
  completeness.
- Do not carry forward stale output-only churn without rerun/review. If a
  notebook is kept unchanged in source, either keep current-main outputs or
  rerun intentionally as part of the notebook review.
- After resolving a notebook, validate notebook JSON with `nbformat`.
- Execute relevant notebooks when the source change affects user-visible
  workflow behavior.
- Ask Bill when a notebook resolution depends on publication intent, naming,
  renumbering, or whether a demonstration should remain as a standalone example
  versus move into another notebook.

| Status | Notebook | Initial resolution plan | State |
|---|---|---|---|
| `UU` | `examples/101_project_initialization.ipynb` | Subagent compare input cells, then rerun if source changes are kept. Specifically assess concise project initialization output, welcome/docs links, and DataFrame presentation. | Not started |
| `UU` | `examples/103_plan_and_geometry_operations.ipynb` | Subagent compare input cells, then rerun if source changes are kept. Assess plan/geometry DataFrame usage and concise logging. | Not started |
| `UU` | `examples/202_2d_plaintext_geometry.ipynb` | Subagent compare input cells, then rerun if source changes are kept. Assess whether feature edits improve 2D geometry API usage or logging clarity on current main. | Not started |
| `UU` | `examples/203_htab_parameter_optimization.ipynb` | Subagent compare input cells, then rerun if source changes are kept. Preserve HTAB API demonstrations that remain accurate. | Not started |
| `UU` | `examples/220_calibration_workflow.ipynb` | Subagent compare feature source edits against current-main Kalamazoo rewrite. Ask Bill before discarding a distinct methodology or merging demonstrations. Rerun if source changes are kept. | Not started |
| `UU` | `examples/230_mesh_sensitivity_analysis.ipynb` | Subagent compare input cells and current-main mesh sensitivity changes. Rerun if source changes are kept. | Not started |
| `UU` | `examples/510_linux_execution.ipynb` | Subagent compare input cells. Assess Linux execution updates plus concise logging behavior. Rerun or validate as environment permits. | Not started |
| `UU` | `examples/600_floodplain_mapping_gui.ipynb` | Subagent compare input cells. Ask Bill if benefit/adverse-impact explanation belongs here or in fluvial/pluvial notebook. Rerun if source changes are kept. | Not started |
| `UU` | `examples/610_generate_fluvial_pluvial_delineations_max_wse_arrival_time.ipynb` | Subagent compare input cells and naming/renumbering. Evaluate benefits-evaluation wording, adverse impact polygons, and downstream impact interpretation. Rerun if retained. | Not started |
| `UU` | `examples/700_core_sensitivity.ipynb` | Subagent compare input cells. Assess sensitivity API/logging changes and rerun if retained. | Not started |
| `UU` | `examples/701_benchmarking_versions_6.1_to_6.6.ipynb` | Subagent compare input cells. Assess version/executable logging demonstration and rerun if retained. | Not started |
| `UU` | `examples/914_historical_event_validation.ipynb` | Subagent compare input cells under current 900-series structure. Rerun if source changes are retained. | Not started |
| `UU` | `examples/915_realtime_forecast_workflow.ipynb` | Subagent compare input cells and determine whether feature changes remain useful with current forecast workflow organization. Rerun if retained. | Not started |
| `UU` | `examples/916_hrrr_precipitation_forecast.ipynb` | Subagent compare input cells and cross-check deferred precipitation suite notes. Rerun if source changes are retained and environment supports it. | Not started |
| `UU` | `examples/917_mrms_precipitation_qpe.ipynb` | Subagent compare input cells. Do not hide known MRMS/Tk/netCDF follow-up issues. Rerun/review if retained and environment supports it. | Not started |
| `UU` | `examples/918_hms_ras_coupled_forecast.ipynb` | Subagent compare input cells under current forecast/coupling organization. Ask Bill if split/merge publication intent is unclear. Rerun if retained. | Not started |
| `UU` | `examples/919_operational_forecast_cycling.ipynb` | Subagent compare input cells and determine whether feature changes belong in the current deterministic forecast-cycle workflow. Rerun if retained. | Not started |
| `UD` | `examples/919_stofs3d_coastal_boundary.ipynb` | Main deleted or moved this notebook. Subagent compare against current-main replacement, likely `examples/923_stofs3d_coastal_boundary.ipynb`. Ask Bill before resurrecting old path. Rerun replacement if feature source is ported. | Not started |
| `UU` | `examples/950_ebfe_spring_creek.ipynb` | Subagent compare input cells under current eBFE organization. Rerun if retained. | Not started |

## Non-Conflict But High-Risk Auto-Merge Areas

The attempted merge also auto-merged many files from `origin/main`. When working
case by case, check these areas because they may interact with the conflict
resolutions even if they did not report conflicts:

- docs viewer / example library assets
- notebook renumbering and generated docs navigation
- new culvert and geometry APIs
- new HEC-RAS template resources
- recent terrain/GDAL fixes
- new Linux/remote execution tests and modules
- new precipitation fixtures

## Validation Plan

Use focused validation per group rather than one giant run:

1. API logging group:
   - Run focused logging tests for the touched module family.
   - Run `python -m py_compile` on touched modules.
2. HDF group:
   - Run HDF-specific tests for touched files.
   - Execute or inspect one HDF extraction notebook when notebook source changes.
3. Unsteady precipitation group:
   - Run precipitation and normal-depth tests.
   - Confirm paired precipitation hydrograph format against current-main tests.
4. Docs/notebook group:
   - Validate notebook JSON with `nbformat`.
   - Use subagent notebook review for each resolved notebook or notebook family.
   - Run `mkdocs build` after nav/config changes.
   - Re-run notebooks where source behavior changed, and review outputs before
     committing. Output cells should be current and faithful to the resolved
     source.

## Progress Log

- 2026-07-07: Cleaned and pushed `feature/711-rasremote-mannings-sensitivity`.
- 2026-07-07: Attempted merge of `origin/main`; conflict set was too broad for
  a safe monolithic resolution.
- 2026-07-07: Reproduced conflict inventory in detached audit worktree and
  created this tracking document.
