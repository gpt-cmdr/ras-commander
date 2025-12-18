# Notebook Utilities

Small, repo-local helpers for auditing and running Jupyter notebooks without
loading large `.ipynb` outputs into an LLM context.

## `audit_ipynb.py`

Scans notebooks for:
- Stored exception outputs (`output_type: "error"`)
- `stderr` stream outputs
- Traceback/error-like text in outputs
- High-signal “unexpected behavior” phrases (empty results, missing files, etc.)
- Absolute path leakage (e.g., `C:\Users\...`)

Writes a condensed digest to `working/notebook_runs/<timestamp>/` by default:
- `audit.json`
- `audit.md`

### Examples

Audit all example notebooks:

```bash
python scripts/notebooks/audit_ipynb.py
```

Audit a single notebook and choose an output folder:

```bash
python scripts/notebooks/audit_ipynb.py examples/11_2d_hdf_data_extraction.ipynb ^
  --out-dir working/notebook_runs/manual_run_01
```

Fail CI if any stored error outputs exist:

```bash
python scripts/notebooks/audit_ipynb.py --fail-on-error-outputs
```

## How This Ties Into Subagents

- `notebook-runner` should generate `audit.md`/`audit.json` after runs.
- `notebook-output-auditor` and `notebook-anomaly-spotter` should review the
  digest files (not the full notebook) and report cell indices + summaries.

