# Native and Vortex workflow evidence

| Source | Relevant decisions and checks |
|---|---|
| [DSS operations](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/dss-operations.md) and [native backend](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/dss-native-backend.md) | Public DSS workflows, backend selection, read/write differences, and feature-gated support. |
| [RasDssGrid source](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/dss/RasDssGrid.py) | Current wrapper covers GRIB2, Stage IV GRIB1, NetCDF, HDF5, GeoTIFF, ASCII, PRISM, SNODAS, and local Zarr v2, subject to the installed engine. `get_features()` discovers feature groups; forwarded options and return types belong to installed engine help. |
| [Notebook 732](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/732_native_gridded_import_and_grid_tools.ipynb) | Authentic AORC Zarr/NetCDF, IMERG HDF5, Stage IV GRIB1/2, and MRMS import; grid arithmetic, sanitation, clipping, normalization, shifts, resampling, eight zonal statistics and grid-to-point. This notebook does not run HEC-RAS. |
| [Notebook 916](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/916_hrrr_precipitation_forecast.ipynb) | Archived HRRR hourly APCP import with `RasDssGrid`; full-source warp/coverage checks, no-rain control, temporary/final HDF forcing, hydraulic diagnostics. Earlier qpkit comparison fails spatial qualification and is not the preferred route. |
| [Notebook 926](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/926_wpc_qpf_precipitation_forecast.ipynb) | Complete WPC cycle selection (f006–f168), 28 six-hour grids, full-source warp/readback, bounded 24-hour window, and solver consumption checks. A partial live cycle is rejected. |
| [Notebook 917](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/917_mrms_precipitation_qpe.ipynb) | MRMS acquisition and inspection, grid accumulation windows/overlap/gap checks, and uniform-boundary model comparison. Uniform application is not spatial rain-on-grid qualification. |
| [Notebook 728](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/728_extend_gridded_dss_forcing_window.ipynb) | Source-preserving DSS derivative, explicit dry tail, readback, model attachment, temporary/final HDF checks. Its grids are deterministic on a real mesh; it does not validate a meteorological product. |
| [Notebook 915](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/915_realtime_forecast_workflow.ipynb) | Timezone-explicit cycle manifest and orchestration of HRRR, coastal, MRMS, and WPC artifacts; not independent qualification of all formats or versions. |

## Keep the routes distinct

[RasDssGrid](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/dss/RasDssGrid.py) uses `ras_commander_fast_dss.gridded` without Java/Vortex; `RasDss.backend` does not select its engine. The read/write backend of `RasDss` is a separate choice with native gates and documented differences.

[VortexCli](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/precip/VortexCli.py) wraps HEC-Vortex's importer and its runtime. [MRMS native adapter](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/precip/_native_vortex.py) makes a narrower promise: one-hour QPE periods only under `PrecipMrms.to_dss(backend="native")`. Its Java/shadow paths also guard unsupported QPE durations unless the documented explicit instantaneous override is chosen; do not use that override merely to bypass a refusal.

In notebook 732, a projected target in feet still takes native importer `cell_size` in metres. IMERG timestamps alone do not supply an accumulation period. Confirm these semantics in the installed engine before adapting the example. Generic gridded variable ingestion does not establish HEC-RAS support for wind, temperature, snow, radiation, or other external forcings; verify each requested variable and model linkage independently.
