# Precipitation Contract

This file is the canonical local instruction file for `ras_commander/precip/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles precipitation retrieval, design-storm generation, spatial Atlas 14 analysis, forecast ingestion, and grid-to-DSS tooling.

## Method Selection

- Use `Atlas14Storm`, `FrequencyStorm`, or `ScsTypeStorm` when the task requires HMS-equivalent design-storm behavior.
- Use `StormGenerator` when the task needs flexible peak placement and does not need HMS equivalence.
- Use `PrecipAorc` for historical precipitation and calibration workflows.
- Use `Atlas14Grid`, `Atlas14Variance`, and `AbmHyetographGrid` for spatial Atlas 14 analysis and rain-on-grid workflows.
- Use `PrecipHrrr` for HRRR forecast download and `VortexCli` when the workflow needs gridded met conversion to DSS.

## Critical Rules

- Keep units explicit. Depth, duration, timestep, and interval handling must stay unambiguous.
- Preserve exact-depth conservation behavior for storm-generation methods that promise it.
- Do not describe `StormGenerator` as HMS-equivalent.
- Respect NOAA data-source assumptions, bounds, and duration limitations when exposing Atlas 14 methods.
- Keep forecast and gridded-met workflows honest about external prerequisites such as `cfgrib`, HEC-Vortex, or NOAA service availability.

## Validation

- Prefer real NOAA, Atlas 14, AORC, or HRRR data in examples and tests.
- Keep spatial variance decisions reviewable with explicit statistics or plots.

## Reference Notebooks

- `examples/720_atlas14_aep_events.ipynb`
- `examples/725_atlas14_spatial_variance.ipynb`
- `examples/726_abm_hyetograph_grid.ipynb`
- `examples/900_aorc_precipitation.ipynb`
- `examples/915_realtime_forecast_workflow.ipynb`
- `examples/916_hrrr_precipitation_forecast.ipynb`
- `examples/919_operational_forecast_cycling.ipynb`
