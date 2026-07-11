# PR 251 Notebook Rerun Findings

Date: 2026-07-07

Status: **Closed / superseded as of 2026-07-10.** PR #251 was not merged. The
event-alignment, boundary-condition, precipitation, compute-completion, and
notebook-output work was reassessed and landed on current `main` through PR
#274. The failure evidence below is retained because it explains the corrective
scope; it no longer represents the state of notebooks 901 and 914 on `main`.

Context: PR #251 (`linear/CLB-899`) was replayed onto current `origin/main`
after the logging PRs and dependency updates landed. The PR source edits were
limited to notebook plotting/result-reporting cells:

- `examples/901_aorc_precipitation_catalog.ipynb`: code cells 21 and 23.
- `examples/914_historical_event_validation.ipynb`: code cell 8.

Both notebooks were rerun in `G:\GH\ras-commander-pr251-update` using the
repo-local `uv` environment with the notebook extras installed.

## 901 AORC Precipitation Catalog

Verdict: **REVISE / hold PR output**.

Findings:

- The notebook ran without Python exceptions.
- HEC-RAS reported `12/12` storm plan executions successful.
- No plan result HDFs were produced for the storm plans (`p07`, `p08`, `p09`,
  `p10`, `p11`, `p12`, `p14`, `p16`, `p20`, `p21`, `p22`, `p23`).
- The notebook result summary correctly reported `HDF NOT FOUND` for all
  storm plans and `Plan HDF files found: 0 of 12 storms`.
- Generated `.data_errors.txt` files report the same model issue:
  `Boundary at SA Conn: Sayers Dam ... Time series data ends before the end of
  the simulation.`
- The rerun exposed repeated `RasUnsteady` warnings from configuring gridded
  precipitation in sparse cloned unsteady files. A separate narrow API fix can
  create the missing precipitation block instead of logging repeated missing-line
  warnings.

Recommended next action:

- Do not publish the rerun output.
- Fix the storm-plan workflow before accepting this notebook output: either
  constrain simulation periods so the SA connection gate time series covers the
  event or make the notebook explicitly a precipitation-catalog-only example.
- Treat compute success as incomplete when the expected plan HDF is absent.

## 914 Historical Event Validation

Verdict: **REVISE / hold PR output**.

Findings:

- The notebook ran without Python exceptions.
- The improved coverage map plotting cell rendered and is materially better
  than the original.
- The model execution did not produce usable modeled results.
- `BaldEagleDamBrk.p07.hdf` contained compute messages and plan/geometry
  metadata but no `/Results/Unsteady` result group.
- Compute messages indicate the active event-condition precipitation does not
  overlap the 2020 validation plan period:
  the plan period is `2020-12-22` to `2020-12-27`, while the gridded
  precipitation metadata still points at the 2018 example event.
- Result extraction falls back from 1D cross-section results to 2D reference
  lines, then reports no available modeled flow time series.
- Metrics and comparison plots are skipped because aligned modeled data is not
  available.

Recommended next action:

- Do not publish the rerun output.
- Fix the precipitation/event-condition configuration so the 2020 plan uses
  the downloaded 2020 AORC NetCDF.
- Add or automate a usable modeled result extraction path, such as a reference
  line or stage extraction workflow, before presenting the notebook as an
  end-to-end validation example.

## PR Recommendation

Do not merge PR #251 as-is. The source edits are narrow and generally
reasonable, but the notebooks fail the executed-notebook review standard because
the published outputs do not demonstrate successful hydraulic results.
