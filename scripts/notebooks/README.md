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

```bat
python scripts\notebooks\audit_ipynb.py
```

Audit a single notebook and choose an output folder:

```bat
python scripts\notebooks\audit_ipynb.py examples\11_2d_hdf_data_extraction.ipynb ^
  --out-dir working\notebook_runs\manual_run_01
```

Fail CI if any stored error outputs exist:

```bat
python scripts\notebooks\audit_ipynb.py --fail-on-error-outputs
```

## `read_notebook_source.py`

Extracts only code + markdown cells (no outputs) into markdown, so reviewers can
reason about notebook intent without context bloat.

```bat
python scripts\notebooks\read_notebook_source.py examples\312_boundary_df_qmult_dss_paths.ipynb ^
  --out working\notebook_runs\manual_run_01\source.md
```
