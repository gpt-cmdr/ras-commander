# DSS Modules

Classes for reading and writing HEC-DSS files.

## RasDss

Read HEC-DSS files for boundary condition extraction and write DSS time-series
or gridded precipitation records.

### Methods

#### get_catalog(dss_file)
Get catalog of all paths in a DSS file.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file

**Returns:** DataFrame with columns A, B, C, D, E, F parts

#### read_timeseries(dss_file, pathname)
Read a single time series from DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): Full DSS pathname

**Returns:** DataFrame with datetime index and value column

#### read_multiple_timeseries(dss_file, pathnames)
Read multiple time series at once.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathnames` (list): List of DSS pathnames

**Returns:** Dict of {pathname: DataFrame}

#### write_timeseries(dss_file, pathname, times, values, ..., dss_version=None)
Write a single time series to DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): Full DSS pathname
- `times` (list|DatetimeIndex|ndarray): Datetime values
- `values` (list|ndarray): Numeric values
- `units` (str): Units, default `CFS`
- `data_type` (str): DSS data type, default `INST-VAL`
- `create_if_missing` (bool): Create a missing file, default `True`
- `dss_version` (int|None): Keyword-only DSS 6 or DSS 7 selection for new
  files. The default `None` preserves the bridge's current default. An explicit
  value must match an existing file.

Datetime values must be aligned exactly to whole minutes.

#### get_file_version(dss_file)
Return the authoritative HEC-DSS major file version.

**Parameters:**
- `dss_file` (str|Path): Existing DSS file

**Returns:** Integer `6` or `7`.

#### write_grid_timeseries(dss_file, pathname, data, times, grid_info)
Write a time-varying spatial grid series to DSS.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file
- `pathname` (str): DSS grid pathname template; A/B/C/F are preserved and D/E
  are replaced per timestep
- `data` (ndarray): Shape `(n_times, n_rows, n_cols)`
- `times` (list|DatetimeIndex|ndarray): `n_times + 1` interval boundaries or
  `n_times` interval end times
- `grid_info` (dict): Grid metadata such as `cellsize`, `origin`, `crs`,
  `units`, and `data_type`

**Returns:** List of DSS pathnames written.

#### copy_grid_with_zero_tail(source_dss, output_dss, pathname, tail_intervals, ...)

Create a non-destructive DSS grid derivative containing one selected grid
family followed by explicit zero-valued intervals.

The intended workflow is to prepare a run-local gridded precipitation or
rainfall-excess DSS derivative for a HEC-RAS rain-on-grid scenario. A caller can
keep an AORC-like source immutable, optionally express UTC grid timestamps on
the model clock with an explicitly chosen shift, optionally rename the forcing
family and apply an approved whole-cell origin translation, then append
explicit zero-forcing intervals. Those zero intervals allow the model run to
continue through post-storm routing or recession after the source rainfall
ends.

In the source PR workflow, `RasScenario` accepted this already-prepared
`forcing_excess_dss` and wired it to Gridded/DSS precipitation. The derivative
was prepared upstream; `RasScenario` did not directly call this method.

This method does not calculate rainfall or rainfall excess, scientifically
transpose a storm, reproject, resample, or interpolate grids, infer a time
zone, or decide engineering suitability. The caller remains responsible for
those scientific and study-specific decisions.

**Parameters:**

- `source_dss` (str|Path): Existing DSS6 or DSS7 source. It is never modified.
- `output_dss` (str|Path): Destination derivative. It must differ from the
  source. An output symlink, junction, or other reparse point is rejected
  before it can be followed. Only its parent directory is safely resolved;
  the requested final path component is preserved lexically through
  publication.
- `pathname` (str): Exact A/B/C/F family selector with blank D and E parts,
  such as `/SHG/BASIN/PRECIPITATION///AORC/`.
- `tail_intervals` (int): Positive number of zero-valued intervals to append.
- `time_shift_minutes` (int): Optional signed whole-minute shift applied to
  every source and tail window.
- `output_pathname` (str|None): Optional output A/B/C/F family, also with blank
  D/E parts. When omitted, the caller selector's A/B/C/F casing is preserved;
  source selection itself remains case-insensitive and rejects case-ambiguous
  families.
- `x_shift`, `y_shift` (float): Optional origin translations in the grid's
  horizontal units. Each must be an exact whole-cell increment.
- `overwrite` (bool): If `True`, atomically replace an existing destination
  after complete temporary readback. If `False`, publish atomically with a
  create-if-absent hard link; a filesystem without hard-link support fails
  closed and never falls back to replacement.

**Returns:** A summary dictionary containing DSS version, accepted source
SHA-256, source/output coverage, interval, translations, rewritten source
paths, and appended paths.

The output always contains only the selected family plus its tail; unrelated
source records are not copied. The source DSS major version is preserved. All
matched records must form one unambiguous, uniform, contiguous family with
consistent shape, spatial reference, resolution, origin, parameter metadata,
NoData value and footprint, and compression configuration. Tail cells are zero
where the source footprint contains data and remain NoData everywhere else.
The safe-rewrite path currently supports Albers/SHG and specified grids; other
grid metadata classes fail closed rather than being converted implicitly.
Accepted legacy double-leading pathname syntax is canonicalized to the normal
single-leading `/A/B/C/D/E/F/` form before records are written. D/E parts must
use exact minute-granularity `DDMMMYYYY:HHMM` syntax with English uppercase
month tokens. The narrow valid `2400` spelling means next-day midnight;
`24:01` through `24:59` are rejected. Native HEC-DSS grid catalogs spell a
midnight record end as prior-day `2400` and the same instant as a following
record start as next-day `0000`. Returned derivative pathnames use this
role-specific native spelling, while raw timing and parsed instants must still
match exactly.

The method validates the source in a streaming first pass, then rereads and
writes one source frame per writer call and reuses one zero frame for the tail.
It does not stack the source family or materialize the complete tail in memory.
The source file is hashed in chunks before catalog access, after prevalidation,
and after the write-read pass. Any detected digest mismatch aborts before
publication; these checkpoints are not a continuous file lock.

After writing, the temporary derivative must preserve the source DSS major
version and contain the independently derived exact catalog. Every temporary
record is then reopened one at a time. Rewritten source frames must match an
exact normalized float32 digest (canonical NaN and signed zero), tails must
contain exact zero on data cells and the stable source NoData mask, raw timing
must match the expected window, and all write-relevant metadata must match the
source reference except for the requested mechanical origin translation.

For `overwrite=False`, hard-link creation is the atomic no-clobber instruction:
if another writer wins the final race, `FileExistsError` is raised and that
destination is preserved. Unsupported hard links raise `OSError` and leave the
destination absent. For `overwrite=True`, same-directory `os.replace()` is
atomic, but the new derivative replaces the old destination's timestamps,
permissions/ACL details, hard-link identity, and other file metadata.
Because the final output component is not resolved or followed after its
initial reparse-point check, a competing entry at that exact name either wins
the no-clobber hard-link race or is itself replaced under `overwrite=True`;
the implementation does not redirect publication through that entry to a
different target.

Time, pathname, and origin changes are lexical/mechanical metadata transforms,
not scientific transformations of the forcing.

Stable failures include `FileNotFoundError` for a missing source,
`FileExistsError` for no-clobber conflicts, `IsADirectoryError` for non-file DSS
paths, `ValueError` for unsafe inputs/families/metadata, `ImportError` when the
optional Java bridge is unavailable, `OSError` for filesystem publication
failures, and `RuntimeError` for source-stability or DSS I/O/readback failures.

```python
result = RasDss.copy_grid_with_zero_tail(
    "source.dss",
    "derivative.dss",
    "/SHG/BASIN/PRECIPITATION///AORC/",
    3,
    time_shift_minutes=-300,
    output_pathname="/SHG/BASIN/PRECIPITATION///AORC-SHIFTED/",
    x_shift=2000,
    y_shift=3000,
)
print(result["appended_pathnames"])
```

Common SHG precipitation metadata:

```python
grid_info = {
    "cellsize": 2000,
    "origin": (1096000, 1516000),
    "crs": "SHG",
    "units": "mm",
    "data_type": "PER-CUM",
}
```

#### extract_boundary_timeseries(boundaries_df, ras_object)
Extract all DSS boundary conditions from a project.

**Parameters:**
- `boundaries_df` (DataFrame): From ras.boundaries_df
- `ras_object` (RasPrj): Project object

**Returns:** Dict of {boundary_name: DataFrame}

#### get_info(dss_file)
Get DSS file information.

**Parameters:**
- `dss_file` (str|Path): Path to DSS file

**Returns:** Dict with filepath, filename, file size, total pathname count, and
a preview of the first five catalog rows.

## Usage

```python
from ras_commander.dss import RasDss

# Get catalog of DSS contents
catalog = RasDss.get_catalog("/path/to/file.dss")
print(catalog)

# Read time series
pathname = "/BASIN/GAGE1/FLOW/01JAN2020/1HOUR/OBS/"
df = RasDss.read_timeseries("/path/to/file.dss", pathname)
print(df)

# Write a small SHG gridded precipitation DSS
import numpy as np
import pandas as pd

data = np.arange(5 * 10 * 10, dtype="float32").reshape(5, 10, 10)
times = pd.date_range("2020-01-01 01:00", periods=5, freq="h")
written = RasDss.write_grid_timeseries(
    "/path/to/precip.dss",
    "/SHG/WATERSHED/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTHETIC/",
    data,
    times,
    {
        "cellsize": 2000,
        "origin": (1096000, 1516000),
        "crs": "SHG",
        "units": "mm",
        "data_type": "PER-CUM",
    },
)
print(written)

# Extract all boundary conditions from project
from ras_commander import init_ras_project, ras
init_ras_project("/path/to/project", "6.5")
bc_data = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras)
```

## Grid Java API Mapping

`write_grid_timeseries()` uses the same lazy pyjnius/HEC Monolith setup as the
time-series methods. The Python inputs map to Java objects as follows:

| Python input | HEC Monolith class/member |
| --- | --- |
| `dss_file` | `hec.heclib.grid.GriddedData.setDSSFileName()` |
| A/B/C/F parts of `pathname` | `GriddedData.setGriddedPathnameParts()` |
| Generated D/E timestep windows | `GridInfo.setGridTimes()` and `GriddedData.setGriddedTimeWindow()` |
| `data[i]` flattened row-major | `hec.heclib.grid.GridData(float[], GridInfo)` |
| `grid_info["crs"] == "SHG"` | `hec.heclib.grid.AlbersInfo` with NAD83 SHG parameters |
| Other WKT CRS strings | `hec.heclib.grid.SpecifiedGridInfo.setSpatialReference()` |
| `cellsize`, `origin`, cell counts | `GridInfo.setCellInfo()` |
| `units`, `data_type` | `GridInfo.setParameterInfo()` |
| compression settings | `GridInfo.setCompressionInfo()` |

The bundled HEC Monolith exposes `hec.io.GridContainer`, but the ras-commander
Monolith cache does not include a `SpatialGridBean` class. The equivalent grid
payload is `GridData` plus a `GridInfo` subclass (`AlbersInfo`,
`SpecifiedGridInfo`, or `HrapInfo`). This writer stores records through
`GriddedData.storeGriddedData()` because that is the stable grid write path from
pyjnius for the Monolith version used by ras-commander.

## Requirements

- `pip install pyjnius`
- Java 8+ (JRE or JDK)
- HEC Monolith libraries (auto-downloaded on first use)
