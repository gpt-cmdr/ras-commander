# API consistency audit resolution

Date: 2026-07-19

The API consistency auditor reviewed `RasProcess.store_maps()`,
`RasProcess.store_maps_at_timesteps()`, `RasMap.store_all_maps()`, the native helper, terrain
entry points, the estimator/profiler contracts, tests, and the Spring River
fixture. Its initial verdict was changes requested. This file preserves the
actionable findings and their final disposition; the auditor's raw scratch
output under `.claude/outputs/` is intentionally gitignored.

## Resolution matrix

| Priority | Finding | Final resolution |
|---|---|---|
| P0 | New StoreMap scalars broke the legacy positional tail | Full legacy positional prefix restored; advanced settings are keyword-only through frozen `StoreMapPerformanceOptions` |
| P0 | Worker selection could not be previewed | Public non-mutating `RasProcess.estimate_store_map_resources()` returns a frozen, serializable estimate |
| P1 | `memory_per_worker_mb` mixed a floor with an override | `minimum_worker_memory_mb` is a floor; `worker_memory_override_mb` is separate and requires explicit `warn`/`ignore` policy acknowledgement |
| P1 | Memory formula lacked transparent assumptions | Result includes terrain dimensions/cells, raw Float32 MiB, formula version, estimate source, multiplier, overhead, explicit per-helper GDAL cache, memory/CPU/request/job limits, warnings, and fallback reasons; mesh/HDF/output calibration and confidence fields remain future work |
| P1 | No launch-time admission | Available physical memory and Windows commit headroom are resampled before every helper launch |
| P1 | Unsupported parallel requests silently changed behavior | Explicit worker counts above one reject shared postprocessing products and unsupported map types; automatic selection logs the reason and retains the ordered serial path; estimation reports fallback reasons and the legacy default remains serial |
| P1 | Terrain threading defaults changed global behavior | Compatibility-first defaults retained; threading/cache/write options require explicit opt-in |
| P1 | `Path.resolve()` could rewrite mapped-drive spelling | HEC-facing paths retain their original mapped-drive form through repository-safe path handling |
| P2 | Profiling metadata risked changing the established map return shape | Profiling returns separate frozen result objects; normal StoreMap dictionaries remain unchanged |
| P2 | Native and GDAL TIFF controls were conflated | Stable `GeoTiffWriteOptions` applies only to GDAL output; TiffAssist controls remain in the copied research harness |

## Stable API boundary

The canonical public entry point is `RasMap.store_all_maps()`. It preserves the
historic four positional slots and adds keyword-only `mode=` and tuning
arguments. `mode="configured"` retains the historic all-configured-map behavior
through the packaged RAS Mapper helper; `mode="native"` is a deprecated alias
because `RasProcess.exe` does not honor the required interpolation/render mode.
`selected`, `timesteps`, and `all_plans` route through the configurable
stored-map APIs and accept `performance=`. `mode="auto"` keeps a plain historic
call configured while selecting a product-configured mode when advanced
arguments are present. `RasProcess.store_all_maps()` is a deprecated
compatibility forwarder, not a second implementation.

Wine is a documented runtime fallback: stored-map requests are capped to the
aggregate serial helper, the helper inherits one CPU while it runs, and the
parent affinity is restored afterward. The independent-helper terrain memory
model is not used to admit this aggregate path because it materially
overestimated the demonstrated Muncie StoreAllMaps requirement.

Mode validation is fail-fast: timestep-only selectors cannot leak into other
modes, timestep mode rejects options its underlying wrapper cannot honor, empty
plan/product selections are errors, and `output_folder` is documented as a
relative `.rasmap` StoredFilename name rather than an output destination.

Supported public controls are:

- bounded independent StoreMap helper count;
- memory policy, estimate, reserve, and live admission;
- child-scoped GDAL thread/cache settings;
- general GDAL GeoTIFF codec, tile, predictor, BigTIFF, and overview settings;
- block-streamed equivalence signatures; and
- structured interval CPU, memory, throughput, IOPS, operation-size, host
  disk/network, and inferred-phase reports.

The copied TiffAssist batch size, buffer pools, statistics mode, parallel tile
workers, queue depth, native codec, tile size, histogram behavior, and producer
constants are not stable API. They are hash/version-gated research variables.

## Verification

Regression coverage includes signature/positional binding, option validation,
non-mutating estimation, wrapper forwarding, physical/commit admission,
fallback reporting, mapped paths, child environment isolation, structured
profile serialization, output equivalence, and terrain compatibility defaults.

The focused feature suite and final auditor pass are recorded in the task
handoff after each implementation update. The notebook metadata validator
reports zero errors. The copied native
experiment additionally verifies installed-DLL immutability, source-HDF
preservation, odd edge tiles, raw-NoData tile-zero replacement, decoded pixels,
CRS, transform, NoData, required overview levels, and every exposed TIFF
metadata domain/tag (including histogram/statistics tags when exposed). Block
layout and compression are recorded but intentionally excluded from semantic
comparison so future tuning can vary them.

See [API and release handoff](API_AND_RELEASE_HANDOFF.md) for the stable
contracts and [feature specification](../../agent_tasks/2026-07-19_multicore_raster_processing_feature_spec.md)
for the complete implementation and acceptance plan.
