# DSS Read and Write Backends (Java, Native, Shadow)

`RasDss` reads and writes DSS files through one of three backends. The
default in this release is still `java`. The `native` backend reads and writes
DSS6 and DSS7 files through the optional `ras-commander-fast-dss` package (a pure-Rust
engine) and never starts a JVM or downloads HEC Monolith. `shadow` runs both
and logs every difference.

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
| `native` | ras-commander-fast-dss | `ras-commander-fast-dss` | Native result; no JVM |
| `shadow` | both | both | Native result; Java result compared and logged |

## Installing ras-commander-fast-dss

`ras-commander-fast-dss` (import name `ras_commander_fast_dss`) is the optional
dependency for the native backend. It is not yet published, and no
ras-commander extra installs it. Install the `ras-commander-fast-dss` wheel you
were given:

```bash
uv pip install ras_commander_fast_dss-<version>-cp310-abi3-win_amd64.whl
```

If `ras-commander-fast-dss` is not installed:

- `backend = "native"` raises `ImportError` with installation guidance.
- `backend = "java"` is unaffected.
- `backend = "shadow"` falls back to Java and logs one warning per process.

## Which methods use the backend

| Method | Backend used |
|---|---|
| `get_catalog`, `read_timeseries`, `read_multiple_timeseries` | Selected backend |
| `read_paired_data`, `get_file_version` | Selected backend |
| `read_grid` | `java`: Java. `native`: native when qualified or explicitly opted in (see [Grids](#grids-gated-native-route)). `shadow`: returns Java's grid; native results are compared only |
| `get_info`, `extract_boundary_timeseries` | Selected backend (built on the methods above) |
| `check_pathname_exists`, `check_data_availability`, `check_pathname`, `is_pathname_available` | Selected backend (built on the methods above) |
| `check_pathname_format`, `is_valid_pathname`, `check_file_exists` | No DSS access |
| `write_timeseries`, `write_timeseries_from_dataframe`, `write_paired_data`, `write_grid_timeseries`, `copy_grid_with_zero_tail` | `java`: Java. `native`: ras-commander-fast-dss writers (see [Writes](#writes)). `shadow`: Java; the write is repeated natively on a temporary copy and compared |
| `write_precip_grid_arrays` | `java`: pydsstools (unchanged). `native`: ras-commander-fast-dss. `shadow`: pydsstools, compared with a native copy |

`RasDss.get_capabilities()` returns this matrix as a DataFrame (`operation`,
`java`, `native`, `shadow`, `note`; values `yes`, `gated`, `java`, `no`).
`attrs["native_writes_available"]` tells whether the installed wheel has the
writers.

Under `native`, an operation the backend does not support raises
`DssCapabilityError`; it never falls back to Java. A `native` workflow that
reads and writes DSS needs no Java at all.

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

Native errors come from `ras_commander_fast_dss` and keep the base classes callers
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
- All-missing DSS6 data is a known Java/native difference with two causes
  that raise the same error type. HEC Monolith reports a DSS6 regular request
  whose values are all -901 or -902 as not found (heclib's DSS6 "no data"
  rule, `zrrtsi.f` status 4). The native engine finds those blocks and, after
  its default trim of missing values, raises `DssPathnameNotFoundError` ("no
  values"), the same type as an absent pathname. When native raises
  not-found, shadow repeats the native read with the engine's opt-in
  `no_data="refuse"`, which applies HEC's rule and raises `DssNoDataError`
  (`status == 4`). A refusal is logged as
  `D4 HEC DSS6 no-data rule (native refusal, status 4)`; other not-found
  cases keep the D4 labels. The option exists for this parity check and for
  testing. Shadow still returns the default native result, as `native` does.
  A ras-commander-fast-dss wheel without `DssNoDataError` skips the re-read.
- Stored NaN values are values, not missing markers. The native trim and the
  window cut that shadow applies to the Java frame remove only HEC missing
  markers (-901, -902, -3.4028235e38) at the ends, as heclib's `ztsTrim`
  does.
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
For the exact Java no-data error, shadow may verify a minute-aligned native
span using Monolith's actual windowed read. Only exact values, missing positions,
timestamps, dtypes and attributes establish the expected D3 whole-read defect.
A failed or differing window remains unexpected. This verifies the returned
span; it does not independently prove whole-dataset completeness.
The remaining J2b tail allowance requires exactly matching values and timestamps
through Java's final whole-minute stamp, equal metadata, and less than a minute
of additional native data. Investigate all other truncations.

The earlier comparison evidence used broader historical rules. A fresh
2026-10-22 run under the stricter rules completed all 11,045 comparisons across
53 public RasExamples DSS files, sampling 4,108 time-series datasets, with zero
unexpected differences and no source or working-copy hash changes. It used
HEC Monolith 3.3.27, Java 17.0.11 and a development build of the ras-commander-fast-dss
engine.

The 506 expected comparisons comprise 468 missing-marker mappings, 16 typed
no-data outcomes, 15 whole-minute tail truncations and seven whole-read failures
verified by actual Java window reads. Six additional direct Monolith window
probes match native clocks and values exactly. The seven Davis datasets affected
by tail truncation also match HEC's C library in timestamps, missing positions
and all non-missing value bits.

This is sampled read-contract qualification for these artifacts and runtimes,
not a claim that every possible DSS record or native-engine version is covered.
The optional native wheel remains unpublished; Java remains the default.
Future engine or comparison changes require a fresh corpus run.

## Paired data on each backend

`read_paired_data()` returns the same frame on every backend: every curve,
the ordinates as the index, and the full metadata in `attrs` (see the
[canonical API](#canonical-dss-api-for-consumers-hms-conformance-target)).
Values keep the stored precision: the Java path reads doubles and narrows PD
(type 200) records back to their stored `float32`, which is exact.

Shadow compares the index, every curve bitwise, the column names and every
`attrs` key. Known differences are logged as `expected`:

| Label | Difference |
|---|---|
| PD1 | DSS6 only. The Java DSS6 reader strips leading blanks from curve labels (`" 5%LIMIT"` reads `"5%LIMIT"`). Native keeps them, as HEC's C library does. Labels agree after removing leading blanks. |
| PD2 | Java does not expose the DSS7 paired-data time zone; native reports it in `attrs["time_zone"]`. |
| PD3 | Unit or type strings that differ only in whitespace. |
| PD4 | DSS6 only. Monolith reports precision `-1`; native decodes the stored `KIPREC` word to a value `>= 0` (often `0`). |

Java runs in shadow only when native returned data or `DssPathnameNotFoundError`.
A record of another kind is not compared. The Java path raises
`DssPathnameNotFoundError` only when no matching record exists; when a record
exists but HEC Monolith cannot read it, Java raises `DssReadError`. HEC
Monolith 3.3.27 cannot read the paired-data records of the synthetic test
fixture `synthetic_pd6.dss`; native reads them.

The native and Java backends were compared on every paired-data record of the
public RasExamples DSS files, using HEC Monolith 3.3.27 on Java 17.0.11 and a
development build of the ras-commander-fast-dss engine. Differences were limited to the
classified labels above; ordinates and curve values matched bit for bit.

## Grids: gated native route

`read_grid()` keeps the Java dictionary schema on every backend. Row zero is
the southern row on both. The result carries the key `row_order="south_up"`,
which is new in this release; it is additive and existing keys are unchanged.
The native route runs only with an engine whose grid CRS strings are
qualified against HEC Monolith (current engine builds are; see the end of
this section).

- `backend="native"` raises `DssCapabilityError` (a `NotImplementedError`)
  unless one of two conditions holds. Either the installed ras-commander-fast-dss
  advertises the feature `"grid_srs_monolith_parity"` in
  `ras_commander_fast_dss.FEATURES`, or the caller passes
  `allow_unqualified_native=True`. It does not fall back to Java.
- `backend="shadow"` always returns Java's grid; the native grid is only
  compared. This does not change when a qualified engine is installed. If the
  Java read fails, shadow raises Java's error even when the native read
  succeeded. Use `backend="native"` to read grids without Java.
- `allow_unqualified_native=True` is ignored, with a warning, under `java` and
  `shadow`.
- `metadata["crs_qualified"]` reports whether the wheel advertises
  qualification. `metadata["native"]` holds every native field: null value,
  extent, SRS name and type, statistics, compression and raw times.

Shadow judges cells and metadata separately; diffs are prefixed `cells:` or
`meta:`. A cell bit difference is always unexpected. Known differences:

| Label | Difference |
|---|---|
| G-CRS | CRS strings differ while the native grid CRS is unqualified. Once the engine advertises qualification, a CRS difference is unexpected. |
| G1 | Native maps the grid null value and -901/-902 to NaN; Java maps only -3.4028235e38. |
| G2 | Whitespace-only differences (Java pads legacy unit strings, for example `"MM  "`). |
| G3 | Untimed grid records: native reports no time; Java reports the header times. |
| G4 | `metadata["number_missing"]`: Java's count against native's NaN-cell count. |

The native and Java backends were compared on every grid record of the public
RasExamples DSS files and on synthetic grid fixtures. Cells matched bit for bit,
and the remaining differences were limited to the classified labels above.

A ras-commander-fast-dss build whose grid CRS strings, null values and DSS7 Albers
parameters follow HEC Monolith advertises `grid_srs_monolith_parity`. With
such a build the gate is open: `backend = "native"` reads grids natively by
default and `metadata["crs_qualified"]` is `True`. With it, 250 records sampled from the ten grid families of the
RasExamples file `BaldEagleCrkMulti2D/Precipitation/precip.2018.09.dss`
(DSS6, SHG Albers, PRECIP_2_BYTE) read identical on both backends (cells,
CRS and every metadata key; no G-label difference). Builds without the
feature keep the gate closed. Shadow behavior does not change.

## Writes

Under `backend = "native"`, `write_timeseries`,
`write_timeseries_from_dataframe`, `write_paired_data`, `write_grid_timeseries`,
`copy_grid_with_zero_tail` and `write_precip_grid_arrays` write through
ras-commander-fast-dss. They start no JVM and never fall back to Java.

```python
RasDss.backend = "native"
caps = RasDss.get_capabilities()
assert caps.attrs["native_writes_available"]   # build has writer support
RasDss.write_timeseries("bc.dss", "/BASIN/LOC/FLOW//1HOUR/RUN/", times, values)
```

The writers need a ras-commander-fast-dss build with writer support (DSS7 and DSS6,
regular and irregular time series, paired data, grids). `native_writes_available()`
checks the installed package's API (`create`, `write_timeseries`,
`write_paired_data`, `write_grid`, `HEC_MISSING_DSS6`, `GRID_NODATA`), not a version number;
`get_capabilities().attrs["native_writes_available"]` reports it. Without the writers, a native write raises
`DssCapabilityError` and creates no file.

### Contract kept from the Java path

- **Files.** An existing file keeps its DSS version, and an explicit
  `dss_version` must match it. A new file is DSS7 unless `dss_version=6`, the
  Java default (HEC Monolith 3.3.27 creates DSS7). `create_if_missing`,
  `FileNotFoundError` and `IsADirectoryError` behave as before.
- **Time series.** The arguments are checked as before: timezone-naive,
  whole-minute stamps and equal lengths. Values are stored as doubles (record
  types 105 and 115). The E part decides regular or irregular storage
  (`IR-DAY` to `IR-CENTURY`). The D part is replaced by each block's start
  date. Values replace the stored values at the same times, and the rest of
  the block is kept (HEC's default). `NaN` is stored as Monolith stores it:
  as `NaN` in DSS7 files and as -901 in DSS6 files. DSS6 pathnames are stored
  in upper case.
- **Paired data.** `write_paired_data` takes the ordinates and curves as arrays,
  or the DataFrame from `read_paired_data`, whose `attrs` supply the units, types,
  labels and display precision. Float32 input stores a PD record (type 200) and
  anything else a PDD record (type 205), or choose with `value_type`. A record at
  the pathname is replaced whole, and `NaN` keeps its stored bits on both DSS
  versions, as Monolith stores it. `pathname` needs exactly six parts, and invalid
  arguments raise the same classes on every backend, before any file changes. The
  record time zone that `read_paired_data` reports is not written on any backend,
  because `PairedDataContainer` does not store it. A DSS6 frame that carries
  `x_precision` 0 (the native reader reports it for some records with no precision
  set) is written with unset precision, because DSS6 cannot store 0.
- **Grids.** Pathnames, time windows, row order (row zero south), the lower-left
  cell (explicit indexes, or `origin` rounded to whole cells from cell zero) and
  the grid type inferred from `crs` all follow the Java path. `NaN`, infinite
  cells and `grid_info["nodata_value"]` are stored as no data.
  - Compression: DSS7 grids are always ZLIB compressed, because Monolith ignores
    the requested method on DSS7 (verified for PRECIP_2_BYTE, ZLIB, NONE and
    `None`). DSS6 grids use PRECIP_2_BYTE (the default) or ZLIB.
  - Specified grids keep Monolith's defaults: name `Specified Grid`, time zone
    UTC, interval flag set.
  - Instantaneous grids store their time in part D and leave E blank, as
    Monolith does.
- **`copy_grid_with_zero_tail`.** The source is read, and the derivative written
  and verified, through ras-commander-fast-dss, with the same family, timing,
  metadata, NoData and SHA-256 checks and the same atomic publication. The
  source's DSS version and its PRECIP_2_BYTE scale and base are kept. The
  unused scale and base words of ZLIB grids are not compared.
- **`write_precip_grid_arrays`.** The method stores the records pydsstools
  stores: DSS7 specified grids, PER-CUM, ZLIB, the WKT1_GDAL CRS and its name,
  and no time zone. It needs `affine` and `pyproj` but not pydsstools.

### Intended differences

| # | Case | Java backend | Native backend |
|---|---|---|---|
| W1 | Regular E part with times that are not exactly regular | Stores the values with a time offset, shifted onto the interval | `ValueError` |
| W1 | DSS6 time-series units or type longer than 8 characters; DSS6 grid units longer than 12 | Truncated | `ValueError` |
| W1 | Pathname without exactly 7 slashes, or with non-ASCII characters | Stores a truncated pathname or drops the characters, or raises a Java error | `ValueError` |
| W1 | Infinite time-series values | Stored | `ValueError` |
| W1 | Paired data: DSS6 units or types longer than 8 characters | Truncated | `ValueError` |
| W1 | Paired data: DSS6 label over 100 characters, or with trailing blanks, or no label non-blank in its first 8 characters | Truncated, blanks dropped, or the labels lost | `ValueError` |
| W1 | Paired data: DSS6 `x_precision=0` | Stores another precision | `ValueError` |
| W1 | Paired data: non-ASCII pathname | Stores the bytes as a replacement character | `ValueError` |
| W1 | Paired data: infinite values, or values that overflow float32 under `value_type="float"` | Stored as infinity | `ValueError` |
| W1 | Paired data: a time series or other record already at the pathname | Replaced | `DssUnsupportedRecordError`, file unchanged |
| W1 | Paired data: `ELEV` parameter with a <code>&#124;</code> in an elevation-side unit, or (DSS7) a location record holding vertical-datum information | The unit is stored as given and truncated on DSS6; HEC's datum handling applies to the location case (not exercised here) | `DssUnsupportedRecordError`, file unchanged |
| W1 | Grid data type `FREQ`, `PER-MIN` or `PER-MAX` | Stored with a code the readers do not name | `ValueError` |
| W1 | DSS6 grid with `compression="NONE"` | Writes a record that ras-commander-fast-dss cannot decode (invalid PRECIP_2_BYTE scale/base) | `DssUnsupportedRecordError` |
| W1 | DSS6 PRECIP_2_BYTE cells that the given scale and base would store as missing | Stored as missing | `ValueError` |
| W4 | DSS6 PRECIP_2_BYTE scale and base | `compression_base` and `compression_scale_factor` reach Monolith's setter in swapped positions. `dss_version=6` therefore supplies swapped defaults; a write into an existing DSS6 file without `dss_version` stores scale 0 and base 100, which ras-commander-fast-dss cannot decode | Stored as named. Without them, scale and base are chosen as Monolith chooses them (100 and 0, adjusted for negative minima and wide ranges). No workaround is needed |
| W5 | Negative DSS6 PRECIP_2_BYTE cells with the default scale and base | Stored as missing | Stored |
| W2 | Null value of DSS7 HRAP and Albers grids | 0.0 | -FLT_MAX. Neither reader treats it as data |
| W3 | DSS6 ZLIB scale and base header words (unused) | 0 and 100 | -FLT_MAX |
| W6 | Return value of instantaneous grid writes | D/E-filled names that are not in the catalog | The stored names (time in D, E blank) |
| W7 | A failed write that created the file | The file stays | The file is removed |
| W8 | File held open by HEC software (HEC-RAS, HEC-DSSVue, ...) | Written | `DssLockedError` (a `RuntimeError`), file unchanged |
| W9 | Write errors | `RuntimeError` wrapping the Java exception | `ValueError` for refused input; typed `DssError` subclasses (all `RuntimeError`) otherwise |
| W10 | DSS6 paired-data display precision after an earlier write in the process set one | Monolith keeps the earlier precision, even when the later write asks for none | Stored as each write asks |

Compressed grid bytes differ, because a different deflate library writes the
same cells, and new DSS7 files carry HEC's `7-JA` version string (Monolith
writes `7-IU`). Neither affects the stored values.

### Evidence

`tests/test_rasdss_native_writes.py` writes the same records natively and
through Java (in a worker process), from RasExamples `BaldEagleCrkMulti2D`:

- six regular series (DSS6 `Bald_Eagle_Creek.dss` and DSS7
  `BaldEagleDamBrk.dss`, 15-minute, hourly and 1-minute data), a merge into an
  existing block, and two irregular series (`IR-DAY`, `IR-MONTH`), each into a
  DSS6 and a DSS7 file;
- six real SHG precipitation grids into DSS6 (PRECIP_2_BYTE and ZLIB) and DSS7,
  plus an instantaneous and a specified grid;
- `copy_grid_with_zero_tail` on the 120-record WPC-QPF family of
  `precip.2018.09.dss` (DSS6) and on a DSS7 family.

Java reads every native-written record (16 time-series datasets and 162 grids)
equal to the Java-written one: values bitwise, missing positions, stamps,
attributes, catalogs, grid cells and metadata, apart from the compressed size.
The native reader reads both files equal, apart from W2 and W3. The
`copy_grid_with_zero_tail` results are equal. The run used HEC Monolith
3.3.27, Java 17 and a development build of ras-commander-fast-dss with writer support.

`tests/test_rasdss_paired_data_write.py` writes the same paired-data records
natively and through Java into DSS6 and DSS7 files: flow-duration curves built from
the `Bald_Eagle_Creek.dss` gauge series (one to three curves, float32 and float64,
labels, `NaN`, blank metadata, a replacement that changes the record type), plus every
curve of the public fixtures. `BaldEagleCrkMulti2D` holds no paired-data record, so
the curves are derived from its series. Both readers read the native-written and
Java-written records equal, apart from the known reader differences PD1 to PD4.

### Shadow writes

Under `shadow`, writes run on Java and the caller gets Java's result and
errors. The write is then repeated natively on a temporary copy of the target
(a temporary new file when the target did not exist), and both files are read
back through the native reader and compared. `copy_grid_with_zero_tail`
builds a second derivative natively in a temporary directory.
`write_precip_grid_arrays` writes with pydsstools and compares a native copy.
The comparison never raises and logs like the read comparisons:

- `identical` at DEBUG;
- `expected` at INFO, labelled `W1` (native refusal), `W2`, `W3` or `W10`;
- anything else at WARNING as `UNEXPECTED`.

A comparison that cannot run is logged as `skipped`: an installed
ras-commander-fast-dss without writer support, a temporary copy that HEC software has
locked, or a target above the copy limit.

Each shadow write into an existing file first copies the whole file, so N
writes into one file cost N copies plus N native writes. Targets larger than
the copy limit are not copied and not compared. The limit is 256 MB by
default. Set `RasDss.shadow_copy_limit_mb`, or the environment variable
`RAS_COMMANDER_DSS_SHADOW_COPY_LIMIT_MB` (which takes precedence), to change
it; `0` skips the comparison for every existing file. An invalid value is
logged as `skipped` and never breaks the write. On the test
corpus, 18 time-series writes compared `identical`. Of 5 grid writes, 2 were
`identical` and 3 `expected` (W2, W3). Of 2 zero-tail copies, 1 was
`identical` and 1 `expected` (W2).

## File version

`get_file_version()` uses the selected backend. Native reads the header
without a JVM. A file that is not DSS6/DSS7 raises `DssInvalidFileError` (a
`ValueError` and `DssFormatError`) on both backends.

## Canonical DSS API for consumers (HMS conformance target)

This is the generic read contract that `RasDss` offers to other consumers,
including the planned hms-commander conformance. Every method is a static
method, accepts `str` or `pathlib.Path`, never creates or modifies the file it
reads, and raises the same exception classes on every backend.

| Method | Returns |
|---|---|
| `RasDss.get_catalog(dss_file)` | DataFrame with column `pathname` (catalog order) |
| `RasDss.read_timeseries(dss_file, pathname, start_date=None, end_date=None)` | DataFrame, `DatetimeIndex` named `datetime`, column `value` (float64; NaN for missing under native); `attrs`: `pathname`, `units`, `type`, `interval` (minutes; 0 irregular), `dss_file` |
| `RasDss.read_multiple_timeseries(dss_file, pathnames)` | `{pathname: DataFrame or None}` |
| `RasDss.read_paired_data(dss_file, pathname, *, ignore_d_part=True, dtype="stored")` | Paired-data frame (below) |
| `RasDss.read_grid(dss_file, pathname, *, allow_unqualified_native=False)` | Grid dictionary (below) |
| `RasDss.get_file_version(dss_file)` | `6` or `7` |
| `RasDss.get_capabilities()` | Support matrix DataFrame |

**Paired-data frame.**

- Index: the ordinates, named `"ordinate"`, in stored order.
- Columns: one per curve, in stored order, named after the curve labels when
  every curve has a distinct non-blank label, otherwise `curve_1..curve_n`.
- dtype: `float32` (PD, type 200) or `float64` (PDD, type 205) with
  `dtype="stored"`; `float64` with `dtype="float64"`.
- HEC missing markers are kept as stored.
- `attrs`, always in this order:
  - `pathname` and `record_pathname`: the pathname requested and the record
    read (they differ when the D part was ignored).
  - `dss_file`, `record_type`, `dss_version` and `stored_dtype`.
  - `n_ordinates` and `n_curves`.
  - `x_parameter` and `y_parameter`, from the C part.
  - `x_units`, `x_type`, `y_units` and `y_type`, for example `LINEAR`, `LOG`
    or `PROB`.
  - `labels`: one string per curve, `""` when absent; trailing blanks are
    removed and leading blanks kept.
  - `x_precision` and `y_precision`: `-1` when unset.
  - `time_zone`: DSS7 only, otherwise `None`; it is never applied.

An Atlas 14 temporal pattern is a single-curve record: `index` holds the hours
and the curve holds cumulative fractions. A multi-curve rating or damage table
keeps every curve. Consumers that need hms-commander's old first-curve
dictionary can derive it: `x_values=df.index`, `y_values=df.iloc[:, 0]`,
`x_units`/`y_units` from `attrs`, and `x_label`/`y_label` from `x_type`/`y_type`.
That dictionary is not part of this contract.

**Grid dictionary.**

| Key | Contents |
|---|---|
| `dss_file`, `pathname` | Resolved file path and the exact pathname |
| `data` | `float32` array `(rows, columns)`; row zero south, columns west to east; missing cells are NaN |
| `row_order` | `"south_up"`; flip rows for north-up rasters |
| `shape` | `(rows, columns)` |
| `units`, `data_type` | Data units and `PER-AVER`/`PER-CUM`/`INST-VAL`/`INST-CUM` |
| `grid_type` | `albers`, `specified`, `hrap`, or the HEC grid-info class name |
| `crs` | HEC spatial-reference string (WKT where available) |
| `cell_size` | Cell size in CRS units |
| `start_time`, `end_time` | Naive `pandas.Timestamp` from parts D/E (or the record), else `None` |
| `metadata` | `pathname_parts`, `grid_class`, `grid_type_code`, `data_type_code`, `shape`, `number_of_cells_x/y`, `lower_left_cell`, `origin` (lower-left corner; Albers/specified), `projection` (cell-zero coordinates; Albers parameters), `number_missing`, `nodata_value`, `compression`, `timing`; native route adds `crs_qualified` and `native` |

**Exceptions** (importable from `ras_commander.dss`). The first four are the
ras-commander-fast-dss classes once the native engine has been imported by a `native` or
`shadow` call, and local classes with the same names and bases otherwise. The
Java backend never imports ras-commander-fast-dss, so a missing or broken native wheel
cannot affect it.

| Class | Bases | Raised when |
|---|---|---|
| `DssError` | `RuntimeError` | Any other DSS failure |
| `DssFormatError` | `DssError` | Damaged or non-DSS file (native reads) |
| `DssUnsupportedRecordError` | `DssError` | Record encoding not decoded |
| `DssPathnameNotFoundError` | `DssError`, `ValueError` | No record or no data for the pathname |
| `DssRecordTypeError` | `DssUnsupportedRecordError`, `TypeError` | The record is another kind (`read_paired_data`, `read_grid`) |
| `DssInvalidFileError` | `DssFormatError`, `ValueError` | `get_file_version` on a non-DSS6/DSS7 file |
| `DssReadError` | `DssFormatError` | The record exists but the backend failed to read it (cause chained) |
| `DssCapabilityError` | `DssError`, `NotImplementedError` | The selected backend does not support or has not qualified the operation |

A missing file raises `FileNotFoundError` and a directory raises
`IsADirectoryError`. Invalid arguments raise `ValueError`. A missing optional
engine (pyjnius for `java`, ras-commander-fast-dss for `native`) raises `ImportError`.

Not yet in the contract: profile and location writes, and `read_timeseries` errors under Java (Java still raises its historical
untyped errors; see the table above).

## Related

- [Native Rust Engines: DSS engine](../native-engine.md#dss-engine)
- [DSS Operations](dss-operations.md)
- [DSS API reference](../api/dss.md)
