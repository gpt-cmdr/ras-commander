---
name: ras-gridded-precipitation
description: "Prepare and attach observed, forecast, or design rain-on-grid inputs to HEC-RAS plans and verify solver-consumed rainfall. Use for Atlas 14, AORC, MRMS, HRRR, WPC, NetCDF, GeoTIFF/GRIB, and gridded DSS precipitation workflows."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# Gridded precipitation

Own precipitation method selection, plan attachment, and source-to-solver verification. Delegate acquisition/conversion to `ras-meteorological-forcings` when needed. Land-use/soils parameterization is a separate workflow; do not modify infiltration merely to obtain a desired rainfall response.

## Planning

Read the rainfall and meteorology topics in [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) for the target release before choosing an import route or design method. Read [workflow evidence](references/workflow-evidence.md) for the applicable product and actual checks. Record installed versions and query `RasUnsteady.get_gridded_precipitation_capabilities()` or `PrecipCapabilities` for exact-release/route evidence. Vendor GDAL ingestion (`native`) and library-authored HDF (`native_hdf`) are distinct routes.

Establish observed versus forecast versus design intent, selected source/method, model clock/timezone, simulation and warmup interval, domain/CRS, timestep, units and missing-data policy. Do not infer a NOAA temporal region or treat rainfall AEP as flood AEP.

## Author and attach

- Inspect the plan's unsteady/geometry dependencies, existing meteorology, gates, and rainfall ratio before cloning authorized scenarios. Preserve source projects and unrelated settings.
- Discover current public methods from installed help. Prefer the implemented `PrecipAorc.download`, storm/grid classes, and `RasUnsteady` precipitation setters; legacy agent examples may advertise nonexistent AORC methods.
- Choose a documented method: spatial duration-dependent ABM and a single-duration raster times one NOAA temporal pattern are different designs. `StormGenerator` is not generally HMS-equivalent.
- Preserve interval semantics. `amount` and `rate` timestamps are interval-ending; explicit `units` is the depth unit even for rates. Set first-interval duration when needed, or retain an explicit zero baseline. Make any dry tail through plan end deliberate. Never convert missing source coverage into no rain.
- For observed/analysis rainfall choose `historic=True` or explicit `ratio=1.0`; clear unintended inherited scaling. Design ARF requires an explicit reviewed choice. Use the public gridded-DSS attachment API for a validated catalog family, or public NetCDF/GeoTIFF/GRIB authoring APIs with durable source artifacts.

## Prove consumption at the permitted stage

Read back meteorology config and durable authoring HDF/NetCDF. If authorized, preprocess through `RasPreprocess` and compare temporary-plan-HDF timestamps, interval/cumulative depth, domain coverage and units against intended forcing. If compute is authorized, use `RasCmdr`, compare final per-cell precipitation, verify final dry-tail behavior, and inspect hydraulic response, runtime messages and mass-balance diagnostics. Never invoke `Ras.exe` directly.

Report source-to-input, input-to-preprocessor, and completed-solver checks separately. Require quantitative depth/volume and spatial coverage comparisons appropriate to the product; a positive-rainfall assertion or successful process exit is insufficient. Return the selected method, versions, artifact paths, plan linkage, assumptions and unresolved discrepancies. Do not claim calibration, forecast skill, or regulatory acceptance from a successful input-fidelity check.
