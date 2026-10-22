# DSS Read Backends (Java, Native, Shadow)

`RasDss` reads DSS catalogs and time series through one of three backends. The
default in this release is still `java`. The `native` backend reads DSS6 and
DSS7 files through the optional `dss-commander` package (a pure-Rust engine)
and never starts a JVM or downloads HEC Monolith. `shadow` runs both and logs
every difference.

This page is the migration note for the native backend: it lists every
intended difference from the Java path.

## Selecting a backend

```python
from ras_commander import RasDss

RasDss.backend = "native"     # "java" (default) | "native" | "shadow"
print(RasDss.get_backend())   # backend the next read will use
```

The environment variable `RAS_COMMANDER_DSS_BACKEND` overrides
`RasDss.backend` when set, so you can switch a whole process or test run
without changing code:

```powershell
$env:RAS_COMMANDER_DSS_BACKEND = "native"
```

An unknown name raises `ValueError`.

| Backend | Reads through | Requires | Returns |
|---|---|---|---|
| `java` | HEC Monolith via pyjnius | Java 8+, pyjnius, Monolith (auto-downloaded) | Java result (unchanged behavior) |
| `native` | dss-commander | `dss-commander` | Native result; no JVM |
| `shadow` | both | both | Native result; Java result compared and logged |

## Installing dss-commander

`dss-commander` is the optional dependency for the native backend. It joins the
`ras-commander[dss-native]` extra when the wheel is published; until then,
install the wheel file you were given:

```bash
uv pip install dss_commander-<version>-cp310-abi3-win_amd64.whl
```

If `dss-commander` is not installed:

- `backend = "native"` raises `ImportError` with installation guidance.
- `backend = "java"` is unaffected.
- `backend = "shadow"` falls back to Java and logs one warning per process.

## Which methods use the backend

| Method | Backend used |
|---|---|
| `get_catalog`, `read_timeseries`, `read_multiple_timeseries` | Selected backend |
| `get_info`, `extract_boundary_timeseries` | Selected backend (built on the methods above) |
| `check_pathname_exists`, `check_data_availability`, `check_pathname`, `is_pathname_available` | Selected backend (built on the methods above) |
| `check_pathname_format`, `is_valid_pathname`, `check_file_exists` | No DSS access |
| `write_timeseries`, `write_timeseries_from_dataframe`, `write_grid_timeseries`, `copy_grid_with_zero_tail` | Java under every backend |
| `read_grid`, `get_file_version` | Java under every backend |
| `write_precip_grid_arrays` | pydsstools (unchanged) |

Writes stay on Java until the native writers are released. A workflow that
writes, or that reads grids, still needs Java under `native`.

Under `native`, `read_multiple_timeseries` opens the file once for all
pathnames. On the RasExamples shadow run this made reads 9.6 times faster than
Java in total; with one open per call they were 3.0 times faster.

## Differences from the Java backend

Data must match. On the RasExamples corpus (53 DSS files, 11,045
comparisons) every non-missing value is bit-identical and every missing
position agrees. The differences below are intended changes or corrections
of Java-path bugs.

### Missing values are NaN

The Java path returns HEC's missing marker as a number (`-3.4028235e+38`,
after Monolith normalizes stored `-901` and `-902`). The native path returns
`NaN` at exactly those positions.

```python
# Before (Java):
valid = df[df["value"] > -900]
# Native and shadow:
valid = df[df["value"].notna()]
```

### `start_date` and `end_date` are honored

The Java path ignores `start_date` and `end_date` and always returns the
whole dataset. The native path applies the window and gives the same result
as HEC Monolith's windowed read (`HecDss.get(path, start, end)`):

- Both ends are inclusive. HEC strings (`"01JAN2020 0000"`), ISO strings and
  datetimes are accepted.
- With both ends given, each end selects the regular interval period that
  contains it. Without a time offset, an end that falls between stamps moves
  forward to the next stamp. With offset data (for example 6HOUR stamps at
  00:30), an end inside a period selects that period's stamp.
- With one end given, stamps `>= start` or `<= end` are kept.
- Leading and trailing missing values are trimmed, as for whole-dataset reads.

Callers that pass dates and rely on getting the whole dataset should drop the
dates before switching to `native`.

### Typed exceptions

Native errors come from `dss_commander` and keep the base classes callers
catch today. All are `RuntimeError` subclasses (decision D32).

| Condition | Java backend | Native backend |
|---|---|---|
| Pathname not in file, or every value missing | `TypeError` (accidental, raised while building the index) | `DssPathnameNotFoundError` (a `ValueError` and `RuntimeError`) |
| Malformed pathname | `jnius.JavaException` | `DssPathnameNotFoundError` |
| Paired data, grid or other non-time-series record in `read_timeseries` | JVM crash (the Python process dies) | `DssUnsupportedRecordError` |
| Missing file | `get_catalog` creates an empty DSS7 file and returns 0 rows | `FileNotFoundError`; no file is created |
| File is not DSS | `get_catalog` returns 0 rows | `DssFormatError` |

`read_multiple_timeseries`, `extract_boundary_timeseries` and the validators
already catch `Exception`. Their control flow is unchanged:
`check_pathname_exists` on a missing file now reports "Failed to read DSS
catalog" instead of creating the file.

### Data the Java path cannot read

These datasets fail or return wrong data through the Java path and read
correctly through `native`:

| # | Case | Java backend | Native backend |
|---|---|---|---|
| D3 | First block of a dataset all missing | May return no data | Returns the valid values; any disagreement requires investigation |
| D5 | Pattern records (`TS-PATTERN` D part) | `TypeError` | Values stamped from 01JAN3000 |
| D7 | Latin-1 pathnames (DSS6) | `TypeError` | Reads the dataset |
| D8 | Weekly (`1WEEK`) DSS6 data | Drops the first value | All stored values |
| J1 (fixed) | Records with a base date (type 115) | Corrected by #591 | Correct stamps |
| J2 (fixed) | Sub-minute data (for example `3Second`, `15Second`) | Stamps and interval corrected by #591 | Same corrected clock and fractional-minute interval |
| J2b | Sub-minute data whose last value is not on a whole minute | Also drops the trailing values after the last whole minute | All stored values; same as HEC's C library |
| D9 | Blank data type | 19 spaces | `""` |

### Other changes

- `get_catalog` keeps Java's row order and dtype. The frame has no `attrs`.
- `read_timeseries` attrs keep the same keys and order: `pathname`, `units`,
  `type`, `interval`, `dss_file`. `interval` is `0` for irregular data and a
  float for sub-minute intervals.
- `RasDss.shutdown_jvm()` is a deprecated no-op under `native` and emits
  `DeprecationWarning`. It will be removed with the Java backend.

## Shadow mode

Use `shadow` for one release to check `native` against your own files before
switching:

```python
import logging
from ras_commander import RasDss

logging.getLogger("ras_commander.dss.RasDss").setLevel(logging.INFO)
RasDss.backend = "shadow"
df = RasDss.read_timeseries("model.dss", "/BASIN/LOC/FLOW//1HOUR/RUN/")
```

Each read returns the native result, then runs the Java path and compares:
columns, index name, dtype and stamps, value dtype, missing positions,
non-missing values bitwise, and every `attrs` key. With a window, the Java
whole-dataset frame is cut to the same window first.

- Identical results are logged at DEBUG.
- Known differences from the table above are logged at INFO. D1 (NaN mapping)
  is logged at DEBUG.
- Any other difference is logged at WARNING with the text `UNEXPECTED`.
  Please report those.
- The comparison never raises. If native raises, shadow raises the native
  error.
- Java is not run where it is unsafe or has nothing to compare:
  - native reports a non-time-series record (Java would crash the JVM);
  - the file is missing (Java would create it);
  - the arguments are invalid.

  These cases are logged as `skipped`.
- Shadow mode opens files with HEC software as the Java path does. HEC
  software can modify a file it opens, so run shadow mode on copies when files
  must stay byte-identical.

## Removal plan

`java` stays the default for this release. `native` becomes the default after
the shadow release. The Java read path and pyjnius are then removed (decision
D4).

### Shadow acceptance after Java timestamp corrections

Base-date shifts, sub-minute clock or interval differences, and Java errors with
native data are unexpected differences. An exception alone does not establish an
all-missing first block. Historical J1/J2 allowances no longer suppress them.
The remaining J2b tail allowance requires exactly matching values and timestamps
through Java's final whole-minute stamp, equal metadata, and less than a minute
of additional native data. Investigate all other truncations.

The earlier 11,045-comparison evidence used the historical classification rules.
It is retained as migration evidence, but does not establish zero unexpected
differences under these stricter rules. Rerun native/Java corpus qualification
with the optional wheel and Java runtime before accepting that claim.

## Related

- [DSS Operations](dss-operations.md)
- [DSS API reference](../api/dss.md)

