# Rain-on-grid workflow evidence

| Source | What to reuse and what it establishes |
|---|---|
| [Gridded precipitation guide](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/user-guide/gridded-precipitation.md) | Current setters, interval semantics, observed ratio policy, durable import artifacts, and staged validation. |
| [Version matrix](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/gridded-precipitation-version-matrix.md) | Exact-release and route evidence; a successful example on one release is not universal support. |
| [Precipitation contract](https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/precip/AGENTS.md) | Method distinctions, conservation requirements, native/Vortex limits and current source entry points. |
| [Notebook 720](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/720_precipitation_methods_comprehensive.ipynb) and [721](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/721_precipitation_hyetograph_comparison.ipynb) | Compare design-storm methods before selecting a hyetograph; preserve the stated HMS-equivalence scope. |
| [Notebook 727](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/727_atlas14_gridded_rain_on_grid_hecras.ipynb) | Spatial Atlas 14 ABM versus equivalent-uniform/no-rain controls: projected rate grids, zero baseline, explicit storm/forcing ends, inherited gate preservation, temporary/final HDF checks, mesh-area-weighted rainfall and hydraulic differences on HEC-RAS 7.0. |
| [Notebook 728](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/728_extend_gridded_dss_forcing_window.ipynb) | Extend a regular DSS family into an explicitly dry plan tail while preserving source hashes; verify temporary/final rainfall plateau. |
| [Notebook 729](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/729_direct_geotiff_gridded_rain_on_grid.ipynb) | Direct raster authoring route, temporary HDF and completed rainfall/hydraulic response. |
| [Notebook 900](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/900_aorc_precipitation.ipynb) and [901](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/901_aorc_precipitation_catalog.ipynb) | AORC storm catalog and cloned plans. Notebook 900 verifies one deterministic event, forcing window, durable/temporary/final HDFs, messages, hydraulic output and BCO mass balance. |
| [Notebook 924](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/924_mrms_netcdf_rain_on_grid.ipynb) | Interval-ending MRMS QPE becomes cumulative NetCDF with a zero baseline, then final cumulative surface is compared at physical mesh cells and rate returns to zero. |
| [Notebook 916](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/916_hrrr_precipitation_forecast.ipynb) and [926](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/926_wpc_qpf_precipitation_forecast.ipynb) | Forecast DSS families with full-source warp checks, no-rain controls, exact temporary-HDF comparisons and completed forcing/hydraulic diagnostics. |

## Common adaptation errors

- An amount ending 10:00 represents the preceding interval; a plan beginning 10:00 excludes that interval. Cover the simulation start explicitly.
- Source depth units (`mm`, `in`) do not become rate-unit strings in explicit forcing API arguments; `value_type` carries the temporal interpretation.
- `historic=True` applies to observed/analysis rainfall; forecasts still need explicit reviewed ratio semantics. A design ARF is not a default observed multiplier.
- The imported unsteady HDF is authoring evidence, temporary plan HDF is precompute evidence, and final plan HDF is post-compute evidence. A filename assignment alone proves none of these.
- Animation frame alignment is a display contract. Do not sum repeated display frames to derive rainfall totals; integrate original source intervals.
