# 2026-07-06 Precipitation Suite Follow-Up

## Context

During the `PrecipAorc` logging cleanup, a narrow validation set passed:

```powershell
uv run pytest tests\test_precip_aorc_logging.py tests\test_rasunsteady_logging.py -q
```

Result: `9 passed`.

A broader nearby precipitation run was attempted as a hygiene check, but it exposed failures that were outside the approved `PrecipAorc` logging scope. No code changes were made for these issues.

## Attempted Broader Command

```powershell
uv run pytest `
  tests\test_precip_aorc_logging.py `
  tests\test_rasunsteady_logging.py `
  tests\test_precip_hrrr_basin_average.py `
  tests\test_precip_mrms.py `
  tests\test_rasunsteady_gridded_dss_precipitation.py `
  tests\test_rasunsteady_met_precip_config.py `
  tests\test_rasunsteady_precipitation.py `
  -q
```

Observed result: `52 passed`, `3 failed`, plus a Windows fatal exception trace from the NetCDF stack after the MRMS test failure context.

## Failures To Investigate Later

### `tests/test_precip_mrms.py::test_flood_animation_accepts_stored_map_rasters`

Failure:

```text
_tkinter.TclError: invalid command name "tcl_findLibrary"
```

Where:

```text
ras_commander\precip\PrecipMrms.py:1917 in _animate_grid_stack
fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
```

Likely investigation path:
- Confirm whether this is a local Matplotlib/Tk backend configuration issue.
- Consider forcing a non-interactive backend in the test or animation helper only where appropriate.
- Do not assume this is related to `PrecipAorc`; it surfaced only because the broader precipitation suite included MRMS animation coverage.

### `tests/test_rasunsteady_precipitation.py::TestSetPrecipitationHyetograph::test_writes_paired_values`

Failure:

```text
AssertionError: Expected hour 1.0, got 0.1
```

Observed log:

```text
Updated Precipitation Hydrograph in test.u01: 24 time steps, interval=1HOUR, total depth=16.5000 inches
```

Likely investigation path:
- Inspect `RasUnsteady.set_precipitation_hyetograph()` output formatting versus the test parser assumption.
- Determine whether the file writer intentionally writes depth-only values or time-depth pairs.
- Update implementation or tests only after confirming the expected HEC-RAS unsteady file format.

### `tests/test_rasunsteady_precipitation.py::TestStormGeneratorIntegration::test_depth_conservation_in_file`

Failure:

```text
AssertionError: Expected total depth 10.0, got 5.0
```

Observed log:

```text
Updated Precipitation Hydrograph in storm.u01: 10 time steps, interval=1HOUR, total depth=10.0000 inches
```

Likely investigation path:
- This appears related to the same fixed-width parsing or writer-format assumption as `test_writes_paired_values`.
- Validate against actual HEC-RAS unsteady precipitation hydrograph expectations before changing behavior.

### NetCDF Runtime Trace During MRMS Coverage

The broader run also emitted a Windows fatal exception trace from the NetCDF/xarray stack:

```text
Windows fatal exception: code 0xc0000139
...
xarray\backends\netCDF4_.py in open_store_variable
...
tests\test_precip_mrms.py:268 in test_direct_mrms_hyetograph_and_netcdf_exports
```

Likely investigation path:
- Check local `netCDF4` / HDF5 DLL compatibility in the `uv` environment.
- Re-run the specific MRMS NetCDF test in isolation before changing package code.
- Determine whether the test should use a different xarray backend or skip when the local NetCDF runtime is broken.

## Deferred Reason

These failures are not caused by the approved `PrecipAorc` logging changes and touch different APIs or local runtime dependencies. They should be handled in a separate approved work item.
