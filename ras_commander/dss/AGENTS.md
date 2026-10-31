# DSS Subpackage Contract

This file is the canonical local instruction file for `ras_commander/dss/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-DSS access through the Java-based monolith bridge,
  the optional native backend (dss-commander: reads and writes), and optional
  precipitation-grid writing through pydsstools.

## Architecture

- Public API: `RasDss`
- Private support: `_hec_monolith.py`, `_backend.py`, `_errors.py`, `_native_grid.py`
- Backends (`_backend.py`): `RasDss.backend` = `"java"` (default this
  release) | `"native"` | `"shadow"`; the environment variable
  `RAS_COMMANDER_DSS_BACKEND` overrides it when set. `RasDss.get_backend()`
  returns the effective backend.
  - `native` reads through the optional `dss_commander` package. It never calls
    `_configure_jvm()` or `_ensure_monolith()`.
  - `shadow` returns the native result, also runs the Java path, and logs
    every difference without raising.
  - `get_catalog`, `read_timeseries`, `read_multiple_timeseries`,
    `read_paired_data`, `get_file_version` and the methods built on them
    (`get_info`, `extract_boundary_timeseries`, the `check_*` /
    `is_pathname_available` validators) switch.
  - `read_grid` is gated: under `native` it raises `DssCapabilityError`
    unless `_backend.native_grid_qualified()` (the wheel lists
    `"grid_srs_monolith_parity"` in `dss_commander.FEATURES`) or the caller
    passes `allow_unqualified_native=True`. Shadow always returns Java's grid
    (and Java's error) and only compares the native grid. Never fall back to
    Java from `native`. Current dss-commander development builds advertise
    the feature, so the gate is open with them.
  - Writes switch too: `write_timeseries` (and `write_timeseries_from_dataframe`
    through it), `write_grid_timeseries`, `copy_grid_with_zero_tail` and
    `write_precip_grid_arrays`. `native` writes through dss-commander and
    requires `_backend.native_writes_available()` (the wheel exposes
    `NATIVE_WRITE_API`); otherwise `require_native_writes()` raises
    `DssCapabilityError`. Never fall back to Java. Native writes must store
    what Java stores (version rules, NaN as NaN in DSS7 and -901 in DSS6,
    doubles, DSS7 grids ZLIB, Monolith's specified-grid defaults, INST grid
    time in D); every intended difference (W1-W9) is listed in
    `docs/user-guide/dss-native-backend.md#writes`. A failed native write that
    created the file removes it.
  - `shadow` writes return Java's result: the write runs on Java, then is
    repeated natively on a temporary copy (`_shadow_write_snapshot`; targets
    above `shadow_copy_limit_bytes()` are skipped: `RasDss.shadow_copy_limit_mb`,
    default 256, overridden by `RAS_COMMANDER_DSS_SHADOW_COPY_LIMIT_MB`) and both files are read
    back natively and compared (`compare_written_timeseries`,
    `compare_written_grids`, `classify_write`; labels W1-W3; a
    `DssCapabilityError` or `DssLockedError` from the native repeat is
    `skipped`). Public writers
    called inside `_backend.forced_java_writes()` use Java under shadow (the
    shadow `copy_grid_with_zero_tail` writes through the public grid writer).
  - `copy_grid_with_zero_tail` takes its file operations from
    `_copy_grid_ops(native)`; the Java ops are looked up at call time so test
    doubles of `get_catalog`, `_read_grid_java`, `write_grid_timeseries` etc.
    still apply.
  - The Java backend must never import `dss_commander`. `_errors` resolves
    classes from `sys.modules` only, and every native import is guarded with
    `except Exception`, so a broken wheel cannot break Java.
  - Each switched method dispatches to `_<method>_java`, `_<method>_native` or
    `_<method>_shadow`. Internal Java-only code (the Java grid and
    time-series writers) must call the `_java` variant directly
    (`_read_grid_java`, `_get_file_version_java`), and tests that stub those
    paths must patch the `_java` names and pin `RasDss.backend = "java"`
    (unset `RAS_COMMANDER_DSS_BACKEND`). Native write code calls the
    `_native` variants.
  - `RasDss.get_capabilities()` reports `_backend.CAPABILITIES`; keep that
    table in step with the dispatch code.
- Direct arrays: `RasDss.write_precip_grid_arrays()` and private
  `_native_grid.py` (`_prepare` validation shared by the pydsstools writer,
  used under `java`/`shadow`, and the dss-commander writer, used under
  `native`). Both write DSS7 PER-CUM specified-time grids with explicit units,
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
- Typed errors live in `_errors.py` and are exported lazily from
  `ras_commander.dss`. The four base classes are the `dss_commander` classes
  when installed (local stand-ins otherwise). Do not wrap native exceptions in
  unrelated types. The only additions are subclasses that keep a historical
  builtin (D32): `DssRecordTypeError` (`TypeError`), `DssInvalidFileError`
  (`ValueError`), `DssReadError` (`DssFormatError`; existing record failed to read),
  `DssCapabilityError` (`NotImplementedError`). New APIs must
  raise the same class on the Java and native paths.
- Shadow comparisons must never raise. Do not run Java in shadow mode where
  the native result shows it is unsafe:
  - non-time-series records in `read_timeseries` (Java crashes the JVM);
  - a record of another kind in `read_paired_data`;
  - missing files (Java creates them).
- Shadow classifications (`_backend.classify_*`) name every known difference
  (D*, J*, PD1-PD4, G-CRS, G1-G4; G-CRS only while the grid CRS is unqualified). Anything else is `unexpected`; do not widen
  an allowance without corpus evidence.
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
pdf = RasDss.read_paired_data("file.dss", "/A/B/STAGE-FLOW///F/")  # every curve, attrs metadata
RasDss.get_file_version("file.dss")   # 6 or 7, selected backend
g = RasDss.read_grid("file.dss", grid_path)   # Java; native gated (allow_unqualified_native=True)
RasDss.get_capabilities()             # support matrix
RasDss.check_pathname("file.dss", path); RasDss.is_pathname_available("file.dss", path)
RasDss.write_timeseries(...)          # selected backend (native: dss-commander writers)
RasDss.get_capabilities().attrs["native_writes_available"]
```

Under native/shadow:

- Missing values are NaN (Java returns `-3.4028235e38`).
- Not-found raises `dss_commander.DssPathnameNotFoundError`.
- Paired data and grids in `read_timeseries` raise `DssUnsupportedRecordError`.
- A missing file raises `FileNotFoundError` and nothing is created.
- `shutdown_jvm()` is a deprecated no-op.

The full migration note, with the canonical consumer (HMS conformance) API, is
`docs/user-guide/dss-native-backend.md`.

## Testing

- Validate against real DSS files and pathnames whenever possible.
- Be careful with notebook or REPL sessions that already started a JVM.
- Backend tests: `tests/test_rasdss_backend.py` (selection, fallback, native
  errors, shadow) and `tests/test_rasdss_native_parity.py` (native vs Java on
  RasExamples projects; Java runs in `tests/_rasdss_parity_java_worker.py`).
  Both skip cleanly without `dss_commander`; the parity tests also skip
  without Java.
- Paired data, grids, file version and typed errors:
  `tests/test_rasdss_paired_grid_version.py` (synthetic public fixtures in
  `tests/fixtures/dss_native_public/`, Java in
  `tests/_rasdss_pd_grid_java_worker.py`, which also authors Java-written PD
  fixtures at test time). Java bridge workers drop
  `RAS_COMMANDER_DSS_BACKEND`, because they test the Java path.
- Native writes: `tests/test_rasdss_native_writes.py` (RasExamples
  `BaldEagleCrkMulti2D` series, grids and zero-tail copies written natively
  and through Java in `tests/_rasdss_native_writes_java_worker.py`, read back
  on both backends; shadow write records; native refusals and the gate).
- Run the existing DSS tests under each backend with
  `RAS_COMMANDER_DSS_BACKEND=native` (or `shadow`).
