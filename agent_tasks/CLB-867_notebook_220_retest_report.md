# CLB-867 Notebook 220 Retest Report

## Scope

Retested `examples/220_calibration_workflow.ipynb` on branch
`linear/CLB-867` at current `origin/main` to verify the CLB-219 follow-up
failure modes:

- first-cell calibration API import blocker
- post-grid-search encoding/OSError failure
- Nelder-Mead kernel crash during optimization

## Findings

- Static import check passed in `symphony-dev` with `PYTHONPATH` pointed at
  this workspace. `RasCalibrate`, `CalibrationPoint`, and
  `make_mannings_apply_fn` import from the local source checkout.
- Full visible notebook execution passed. The final run wrote
  `H:/Symphony/ras-commander/CLB-867/notebooks/220_calibration_workflow_executed.ipynb`.
- Grid search completed without the prior encoding/OSError failure.
- Nelder-Mead completed without a kernel crash and reported
  `Optimization terminated successfully`.
- The executed notebook has zero cell errors and zero warning-like cell
  outputs. The only warning in the terminal log is the Windows Jupyter/ZMQ
  event-loop runtime warning emitted before notebook cell execution.
- Final figure extraction produced two figures under
  `H:/Symphony/ras-commander/CLB-867/figures/220_calibration_workflow/`.
- Figure QA findings were addressed in the committed notebook source: the
  optimization plot reports function evaluations instead of the requested
  iteration cap, and both RMSE displays are constrained to non-negative axes or
  colorbar ticks.

## Code And Notebook Changes

- `RasPermutation._extract_max_wse()` now suppresses expected 1D WSE probe
  warnings before its planned 2D fallback path.
- `HdfChannelCapacity.extract_max_wse()` gained a backward-compatible
  `warn_on_missing` option for callers that intentionally probe for 1D WSE.
- The Nelder-Mead SciPy bounds note is logged as INFO instead of WARNING.
- Notebook 220 is restored to an output-free committed state and its figures
  now label function evaluations accurately. The grid-search color scale guards
  against misleading negative RMSE ticks when all plotted RMSE values are zero.
- Notebook-generated `examples/calibration_grid_search.png` and
  `examples/calibration_optimization.png` are ignored.

## Validation Commands

- `conda run -n symphony-dev pytest tests/test_hdf_channel_capacity.py -q`
- `conda run -n symphony-dev python -c "<static import and notebook structure checks>"`
- `python C:/GH/symphony/clb/tools/run_notebook_visible.py --notebook examples/220_calibration_workflow.ipynb --repo ras-commander --issue CLB-867 --env symphony-dev --workspace <workspace> --timeout 5400`
- `python C:/GH/symphony/clb/tools/extract_notebook_figures.py H:/Symphony/ras-commander/CLB-867/notebooks/220_calibration_workflow_executed.ipynb --output-dir H:/Symphony/ras-commander/CLB-867/figures/220_calibration_workflow --metadata`

## Artifacts

Persistent artifact root:

`H:/Symphony/ras-commander/CLB-867/`

Key final artifacts:

- `notebooks/220_calibration_workflow_executed.ipynb`
- `terminal-logs/20260531_130458_220_calibration_workflow.terminal.log`
- `figures/220_calibration_workflow/figures_metadata.json`
- `figures/220_calibration_workflow/fig_01_cell14.png`
- `figures/220_calibration_workflow/fig_02_cell17.png`
