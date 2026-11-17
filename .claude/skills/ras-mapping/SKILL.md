---
name: ras-mapping
description: "Map computed HEC-RAS results with the supported fast-map/RasFim route, select quantities and timesteps, and compare delivered maps with RAS Mapper."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS mapping

**Cardinal rule:** For professional model revisions, build the specification with the engineer/scientist, including report-quality, relevant figures/maps that are actually visually reviewed; the engineer may explicitly defer it. For research, **proceed with approval and document** within the agreed envelope. Follow the [shared specification and reporting workflow](../../references/model-revisions/specification.md), using ras2cng for rich maps when useful. Existing authorization remains valid; do not repeat routine approval requests.

Own the hydraulic meaning and numerical checks of map products. Use `RasFim` for native fast-map preparation and supervision; route cloud-native packaging to `ras-cloud-native-export` when available.

1. Inspect the installed `ras-commander` and `ras-commander-fast-map` versions, `RasFim.get_capabilities()`, and `RasFim.inspect_model_scope()`. Separate dimensional applicability, request support, and numerical qualification. Do not silently opt into unqualified 1D/mixed routes or substitute a diagnostic method for an approved one.
2. Identify the computed plan/geometry, mesh, terrain source history, CRS, elevation units/datum, saved profile indices/timestamps, mapping method, and requested quantity. Check required velocity/shear series before selecting derived products. A maximum product is not necessarily a product of independent maxima.
3. Read [workflow and notebook evidence](references/workflows.md) for the selected mapping mode. Select method and tolerances using [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) for the model's version before execution.
4. Map into an authorized output directory through installed public APIs. Preserve global hydraulic topology when applying an AOI; a clipped output does not authorize clipping preparation dependencies. Budget shared mapping threads, writer threads, preparation waves, and memory together. Do not infer linear speedup from AOI size.
5. Validate the complete valid/nodata mask, grid alignment, selected time/aggregation, units, and finite values. For a parity task, compare the same native method, terrain, grid, depth filter, and profile; retain differences and qualification limits. Return the manifest, partial/failure status, resource settings, and checks actually performed.

Reading computed results and ordinary fast-map mapping do not require running HEC-RAS. Missing stored-corner preparation and native comparison may require a qualified HEC runtime; use Commander APIs and task authorization. Never invoke Ras.exe directly, replace input terrain silently, or treat a successful process as map parity.
