# Output Intervals and HDF Compression

Short output and mapping intervals (for example 15 minutes over a 9-day
rain-on-grid event) make the plan HDF (`.p##.hdf`) very large. HEC-RAS controls
both the cadence and the HDF5 compression from keys in the plan file (`.p##`).

## Plan-file keys

| Plan key | HEC-RAS GUI name | ras-commander name |
|----------|------------------|--------------------|
| `Computation Interval` | Computation Interval | `computation` |
| `Output Interval` | Hydrograph Output Interval | `output` |
| `Instantaneous Interval` | Detailed Output Interval | `instantaneous` |
| `Mapping Interval` | Mapping Output Interval | `mapping` |
| `HDF Compression` | HDF5 Write Parameters: compression level (0 = off, 1-9) | `level` / `compression` |
| `HDF Chunk Size` | Maximum chunk size, MB (default 1) | `chunk_size_mb` |
| `HDF Spatial Parts` | spatial subdivisions of a chunk | `spatial_parts` |
| `HDF Use Max Rows` / `HDF Fixed Rows` | time rows per chunk: maximum possible, or a fixed count | `use_max_rows` / `fixed_rows` |
| `HDF Write Warmup` | write warmup time steps to the output file | `write_warmup` |
| `HDF Write Time Slices` | write time-sliced steps as well as basic steps | `write_time_slices` |
| `HDF Flush` | "Commit writes" (flush every step; slows runs, for crash diagnosis) | `hdf_flush` |
| `Write Detailed` | write detailed log output for debugging (`.bco`) | see `RasBco` |

Allowed interval strings: `0.1SEC`-`0.5SEC`, `1SEC`...`30SEC` (1-6, 10, 12, 15, 20, 30),
`1MIN`...`30MIN` (same set), `1HOUR`, `2HOUR`, `3HOUR`, `4HOUR`, `6HOUR`, `8HOUR`,
`12HOUR`, `1DAY`, `1WEEK`, `1MON`, `1YEAR`. These were checked against the string tables of Ras.exe 5.0.7,
6.3.1, 6.6 and 7.0; the HDF keys are present in all of them.

Relationships enforced by HEC-RAS (and by `RasPlan.validate_plan_intervals`):

- Hydrograph, Detailed and Mapping intervals must be at least the computation
  interval and an even multiple of it.
- A Detailed interval smaller than the Hydrograph interval is reported by Ras.exe
  ("The interval for detailed output is less than the hydrograph output interval").
  It was not confirmed to block a compute, so `validate_plan_intervals` logs a
  warning rather than raising.
- The simulation start time must be an even multiple of the Hydrograph interval
  (a start of 00:10 with a 1 hour interval will not run).

## Read and write

```python
from ras_commander import RasPlan, HdfPlan

# Intervals (strings exactly as stored in the plan; also available in ras.plan_df)
RasPlan.get_plan_intervals("01")
RasPlan.update_plan_intervals(
    "01",
    computation_interval="30SEC",
    output_interval="15MIN",       # hydrograph output; gauge calibration
    mapping_interval="15MIN",
    instantaneous_interval="1HOUR",
)  # validated against the file's existing values and Simulation Date

# Compression
RasPlan.get_hdf_compression("01")                  # raw + effective (defaulted) values
RasPlan.set_hdf_compression("01", level=1)         # 0 = off (no chunking), 1-9 gzip
RasPlan.set_hdf_output_options("01", chunk_size_mb=1, use_max_rows=False, fixed_rows=1)

# After a compute, confirm what was actually written
settings = HdfPlan.get_hdf_output_settings("01")
settings["time_series"][["name", "chunks", "compression", "ratio"]]
```

`RasPlan.clone_plan(..., intervals={...})` accepts `computation`, `output` (alias
`hydrograph`), `instantaneous` (alias `detailed`) and `mapping`.

All plan keys above also appear as `ras.plan_df` columns (values are strings as
written in the plan).

## Guidance

- HEC-RAS defaults to compression level 1 because higher levels reduce size only
  marginally while slowing writes. Prefer fewer variables and a coarser
  output/mapping interval over high gzip levels.
- Turning compression off disables chunking (per the Ras.exe help text). In one
  6.3.1 sample the uncompressed size of the time series was roughly 1.25-1.4 times the
  stored (gzip level 1) size.
- Which output reaches which cadence: reference-line and boundary-condition-line
  time series (for example gauge locations represented that way) are written at the
  Hydrograph `Output Interval`. Cell water-surface and other 2D mesh arrays are
  written only at the `Mapping Interval`, so a 15-minute cell time series needs a
  15-minute mapping interval, which is what drives HDF size.
- `HDF Flush` (Commit Writes) increases run time substantially; leave it off
  except when diagnosing a hard crash.
- Not confirmed: the effect of the compression, chunk-size, spatial-part and row
  keys on a computed HDF was not verified in a HEC-RAS compute. The key meanings come
  from the Ras.exe help text and plan files saved by HEC-RAS. Check a computed
  result with `HdfPlan.get_hdf_output_settings` before relying on them.
