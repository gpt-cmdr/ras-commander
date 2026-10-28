# DSS Subpackage Contract

This file is the canonical local instruction file for `ras_commander/dss/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-DSS access through the Java-based monolith bridge,
  the optional native read backend (dss-commander), and optional native
  precipitation-grid writing through pydsstools.

## Architecture

- Public API: `RasDss`
- Private support: `_hec_monolith.py`, `_backend.py`, `_native_grid.py`
- Read backends (`_backend.py`): `RasDss.backend` = `"java"` (default this
  release) | `"native"` | `"shadow"`; the environment variable
  `RAS_COMMANDER_DSS_BACKEND` overrides it when set. `RasDss.get_backend()`
  returns the effective backend.
  - `native` reads through the optional `dss_commander` package. It never calls
    `_configure_jvm()` or `_ensure_monolith()`.
  - `shadow` returns the native result, also runs the Java path, and logs
    every difference without raising.
  - Only `get_catalog`, `read_timeseries`, `read_multiple_timeseries` and the
    methods built on them (`get_info`, `extract_boundary_timeseries`, the
    `check_*` / `is_pathname_available` validators) switch. Writes,
    `read_grid` and `get_file_version` stay on Java under every backend.
  - Each switched method dispatches to `_<method>_java`, `_<method>_native` or
    `_<method>_shadow`. Internal Java-only code must call the `_java` variant
    directly.
- Native direct arrays: `RasDss.write_precip_grid_arrays()` and private
  `_native_grid.py`, using optional `dss-native` dependencies loaded on call.
  This API writes DSS7 PER-CUM specified-time grids with explicit units,
  projected square-cell geometry, and interval boundaries, without Java/Vortex.
- Loading is intentionally staged:
  1. parent package lazy-import
  2. lightweight subpackage import
  3. JVM and pyjnius initialization (java/shadow) or `dss_commander` import
     (native/shadow) on first real DSS call

## Critical Rules

- Configure the JVM before importing Java classes with `jnius`.
- Resolve DSS paths to absolute paths before opening files.
- Close DSS handles in `finally` blocks (native: `with dss_commander.open(...)`).
  On the Java path, `HecDss.done()` and `GriddedData.done()` do not close the
  native file; follow each with
  `RasDss._release_dss_file(<exact path string used to open>)`. Never call
  `HecDSSFileAccess.closeAllFiles()`, which closes every DSS file in the JVM.
- Remember that the JVM can only be started once per process.
- Keep Part D blank when writing standard DSS pathnames unless the method explicitly requires otherwise.
- Never wrap `dss_commander` exceptions in new types. They already subclass
  `RuntimeError` (and `ValueError` for not-found).
- Shadow comparisons must never raise. Do not run Java in shadow mode where
  the native result shows it is unsafe:
  - non-time-series records (Java crashes the JVM);
  - missing files (Java creates them).
- Keep `java` the default until the shadow release ends (decision D4).

## Dependency Rules

- `pyjnius` and Java are optional runtime prerequisites and should fail with clear installation guidance when missing.
- `dss_commander` is optional. It joins the `dss-native` extra in `setup.py`
  only when the wheel is published on PyPI (adding an unpublished name to a
  public extra breaks that extra and invites name squatting). `native` without it raises `ImportError`. `shadow` without it
  falls back to Java and logs one warning.
- Keep the monolith download flow lazy and on-demand.

## Common API Surface (quick reference)

```python
from ras_commander import RasDss

RasDss.backend = "native"            # or env RAS_COMMANDER_DSS_BACKEND=native
RasDss.get_backend()                 # effective backend

cat = RasDss.get_catalog("file.dss")                   # DataFrame['pathname']
df = RasDss.read_timeseries("file.dss", "/A/B/FLOW//1HOUR/F/")
win = RasDss.read_timeseries("file.dss", path, "01JAN2020 0000", "02JAN2020 2400")  # dates honored by native/shadow
many = RasDss.read_multiple_timeseries("file.dss", paths)  # one open file under native
info = RasDss.get_info("file.dss")
RasDss.check_pathname("file.dss", path); RasDss.is_pathname_available("file.dss", path)
RasDss.write_timeseries(...)          # Java under every backend
```

Under native/shadow:

- Missing values are NaN (Java returns `-3.4028235e38`).
- Not-found raises `dss_commander.DssPathnameNotFoundError`.
- Paired data and grids raise `DssUnsupportedRecordError`.
- A missing file raises `FileNotFoundError` and nothing is created.
- `shutdown_jvm()` is a deprecated no-op.

The full migration note is `docs/user-guide/dss-native-backend.md`.

## Testing

- Validate against real DSS files and pathnames whenever possible.
- Be careful with notebook or REPL sessions that already started a JVM.
- Backend tests: `tests/test_rasdss_backend.py` (selection, fallback, native
  errors, shadow) and `tests/test_rasdss_native_parity.py` (native vs Java on
  RasExamples projects; Java runs in `tests/_rasdss_parity_java_worker.py`).
  Both skip cleanly without `dss_commander`; the parity tests also skip
  without Java.
- Run the existing DSS tests under each backend with
  `RAS_COMMANDER_DSS_BACKEND=native` (or `shadow`).
