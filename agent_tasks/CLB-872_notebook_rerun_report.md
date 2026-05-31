# CLB-872 notebook rerun report

Issue: [CLB-872](https://linear.app/clbengineering/issue/CLB-872/notebooks-adopt-dialogwatchdog-re-run-headless-gui-blocked-notebooks)

Persistent artifact directory: `H:/Symphony/ras-commander/CLB-872/`

## Environment

- Workspace: `C:/GH/symphony-workspaces/ras-commander/CLB-872`
- Branch: `linear/CLB-872`
- Python environment: `symphony-dev`
- `PYTHONPATH`: workspace root, set by `run_notebook_visible.py`
- Notebook runner: `C:/GH/symphony/clb/tools/run_notebook_visible.py`
- Terminal recorder: `C:/GH/symphony/clb/tools/record_terminal.py`
- HEC-RAS execution path: ras-commander APIs only

## Source changes

- `examples/113_parallel_execution.ipynb`: fixed stale worker-directory cleanup to match literal `[AllWorkers]` names. The previous glob pattern treated brackets as a character class and deleted the freshly extracted `BaldEagleCrkMulti2D_113` source project.
- `examples/701_benchmarking_versions_6.1_to_6.6.ipynb`: added `RAS_COMMANDER_RUN_BENCHMARK_SWEEP` environment override so CI/agent reruns can execute the full sweep while preserving the safe default skip for ordinary notebook opens.

## Runs

### 113 parallel execution

Command:

```powershell
python C:/GH/symphony/clb/tools/record_terminal.py --output terminal-logs --label notebook-113-rerun1 --timeout 22000 -- python C:/GH/symphony/clb/tools/run_notebook_visible.py --notebook examples/113_parallel_execution.ipynb --repo ras-commander --issue CLB-872 --env symphony-dev --workspace C:/GH/symphony-workspaces/ras-commander/CLB-872 --timeout 21600 --interval 60
```

Result:

- Exit code: 0
- Duration: about 3.17 hours
- Executed notebook: `H:/Symphony/ras-commander/CLB-872/notebooks/113_parallel_execution_executed.ipynb`
- Terminal logs:
  - `terminal-logs/20260530_072347_notebook-113-rerun1.terminal.log`
  - `H:/Symphony/ras-commander/CLB-872/terminal-logs/20260530_072347_113_parallel_execution.terminal.log`
- Audit: 0 notebook error outputs. The audit reported `error_text` only because result tables include fields such as `has_errors=False` and `vol_error_percent`.
- Figures: `H:/Symphony/ras-commander/CLB-872/figures/113/fig_01_cell23.png`
- Orphan check: no CLB-872 HEC-RAS GUI processes remained after completion.
- DialogWatchdog: INFO start/stop lines present. No dialog dismissal was recorded because no modal dialog appeared during this run.

### 701 benchmarking versions 6.1 to 6.6

Command:

```powershell
$env:RAS_COMMANDER_RUN_BENCHMARK_SWEEP = "1"
python C:/GH/symphony/clb/tools/record_terminal.py --output terminal-logs --label notebook-701 --timeout 44000 -- python C:/GH/symphony/clb/tools/run_notebook_visible.py --notebook examples/701_benchmarking_versions_6.1_to_6.6.ipynb --repo ras-commander --issue CLB-872 --env symphony-dev --workspace C:/GH/symphony-workspaces/ras-commander/CLB-872 --timeout 43200 --interval 120
```

Result:

- Exit code: 0
- Duration: about 6.14 hours
- Executed notebook: `H:/Symphony/ras-commander/CLB-872/notebooks/701_benchmarking_versions_6.1_to_6.6_executed.ipynb`
- Terminal logs:
  - `terminal-logs/20260530_105400_notebook-701.terminal.log`
  - `H:/Symphony/ras-commander/CLB-872/terminal-logs/20260530_105401_701_benchmarking_versions_6.1_to_6.6.terminal.log`
- Benchmark outputs: `examples/working/benchmark_notebooks/701_version_benchmarking/outputs/bald_eagle_plan02_20260530_105408/`
- Audit: 0 notebook error outputs. The audit reported expected stderr warnings from geometry preprocessor file discovery and false-positive `error_text` hits from volume-error metric names.
- Figures:
  - `H:/Symphony/ras-commander/CLB-872/figures/701/fig_01_cell13.png`
  - `H:/Symphony/ras-commander/CLB-872/figures/701/fig_02_cell13.png`
- Orphan check: no CLB-872 HEC-RAS GUI processes remained after completion.
- DialogWatchdog: INFO start/stop lines present for compute cases. No dialog dismissal was recorded because no modal dialog appeared during this run.

### 900 AORC precipitation

Command:

```powershell
python C:/GH/symphony/clb/tools/record_terminal.py --output terminal-logs --label notebook-900 --timeout 22000 -- python C:/GH/symphony/clb/tools/run_notebook_visible.py --notebook examples/900_aorc_precipitation.ipynb --repo ras-commander --issue CLB-872 --env symphony-dev --workspace C:/GH/symphony-workspaces/ras-commander/CLB-872 --timeout 21600 --interval 120
```

Result:

- Exit code: 0
- Duration: 11130.06 seconds, about 3.09 hours
- Executed notebook: `H:/Symphony/ras-commander/CLB-872/notebooks/900_aorc_precipitation_executed.ipynb`
- Terminal logs:
  - `terminal-logs/20260530_171857_notebook-900.terminal.log`
  - `H:/Symphony/ras-commander/CLB-872/terminal-logs/20260530_171857_900_aorc_precipitation.terminal.log`
- Audit: 0 notebook error outputs. The audit reported two stderr warnings from `HdfXsec` stating no river centerlines were found in the geometry file.
- Figures:
  - `H:/Symphony/ras-commander/CLB-872/figures/900/fig_01_cell21.png`
  - `H:/Symphony/ras-commander/CLB-872/figures/900/fig_02_cell29.png`
  - `H:/Symphony/ras-commander/CLB-872/figures/900/fig_03_cell31.png`
- Orphan check: no CLB-872 HEC-RAS GUI processes remained after completion.
- DialogWatchdog: INFO start/stop lines present for the parallel compute cell. No dialog dismissal was recorded because no modal dialog appeared during this run.
- Terminal note: after successful notebook execution, the terminal log captured an `aiohttp` unclosed-client-session cleanup warning while the event loop was closing. The command still wrote the executed notebook and exited 0.

## Combined audit

Command:

```powershell
python C:/GH/symphony/clb/tools/record_terminal.py --output terminal-logs --label audit-executed-notebooks -- python C:/GH/symphony/clb/tools/audit_ipynb.py --out-dir H:/Symphony/ras-commander/CLB-872/audits/notebooks --fail-on-error-outputs H:/Symphony/ras-commander/CLB-872/notebooks/113_parallel_execution_executed.ipynb H:/Symphony/ras-commander/CLB-872/notebooks/701_benchmarking_versions_6.1_to_6.6_executed.ipynb H:/Symphony/ras-commander/CLB-872/notebooks/900_aorc_precipitation_executed.ipynb
```

Result:

- Exit code: 0
- Report: `H:/Symphony/ras-commander/CLB-872/audits/notebooks/audit.md`
- Notebooks scanned: 3
- Notebooks with error outputs: 0
- First cell H1 OK: true for all three executed notebooks

## DialogWatchdog evidence

DialogWatchdog INFO start/stop lines are present in all three executed notebooks:

- `113_parallel_execution_executed.ipynb`: 38 matching watchdog/dialog output lines.
- `701_benchmarking_versions_6.1_to_6.6_executed.ipynb`: 32 matching watchdog/dialog output lines.
- `900_aorc_precipitation_executed.ipynb`: 24 matching watchdog/dialog output lines.

Important acceptance note: all observed watchdog stops reported `DialogWatchdog stopped - no dialogs encountered`. These reruns therefore prove the notebooks completed headless with the watchdog enabled, but they do not provide natural-run proof of a dialog being detected and dismissed on this workstation/run.

## Figure review

Extracted figures were reviewed after execution. No visual blockers were found.

- `H:/Symphony/ras-commander/CLB-872/figures/113/fig_01_cell23.png`: acceptable; minor note that the omission annotation is slightly tight against the x-axis area.
- `H:/Symphony/ras-commander/CLB-872/figures/701/fig_01_cell13.png`: acceptable four-panel benchmark layout with labeled axes, units, and legends where needed.
- `H:/Symphony/ras-commander/CLB-872/figures/701/fig_02_cell13.png`: acceptable version efficiency plot with labeled axes and useful legend/reference lines.
- `H:/Symphony/ras-commander/CLB-872/figures/900/fig_01_cell21.png`: acceptable storm catalog summary with units on relevant axes.
- `H:/Symphony/ras-commander/CLB-872/figures/900/fig_02_cell29.png`: acceptable; minor note that `green=success` in the title is informal but not blocking.
- `H:/Symphony/ras-commander/CLB-872/figures/900/fig_03_cell31.png`: acceptable annual downstream boundary condition hydrograph with `cfs` axis units, date x-axis, legend, and unobtrusive summary box.

## QAQC checkpoint

- Code quality: no public API changes; no new hardcoded execution paths in library code.
- Notebook quality: all three executed notebooks have first-cell H1 markdown and zero stored error outputs. Audit warnings are documented above.
- API consistency: `.auditor.yaml` applies to `ras_commander/**/*.py`; this task did not change Python API files.
- Process cleanup: no CLB-872 `Ras.exe`, `RasProcess.exe`, `RasPlotDriver.exe`, or `PipeServer.exe` processes remained after each completed notebook.
