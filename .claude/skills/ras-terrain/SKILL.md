---
name: ras-terrain
description: "Create, modify, associate, sample, and validate HEC-RAS terrain through Commander, including source priority, terrain modifications, and native registered-terrain export."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS terrain

Own the elevation surface and its project dependencies. Use the installed public `RasTerrain`, `RasTerrainModWriter`, `RasTerrainMod`, and `RasMap` APIs. Route hydraulic result mapping to `ras-mapping`, land-cover/infiltration parameters to `ras-land-surface`, and cloud-native packaging to `ras-cloud-native-export` when available.

1. Identify whether the task creates base terrain, authors modifications, changes geometry associations, samples the effective surface, or exports an existing registered terrain. Record installed Commander and HEC-RAS releases, selected terrain and geometry/plan, source order, horizontal CRS/units, elevation units/datum, resolution, nodata, and intended outputs. Source `main` is not proof of installed capability; inspect current signatures and version gates.
2. During planning, use the terrain topics in the [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) and [workflow evidence](references/workflows.md). Agree on channel invert, fill/raise semantics, side slopes, overlap priority, source data coverage, and tolerances relevant to the requested edit. Do not infer vertical datum from CRS, silently convert elevations, or treat a nominal cell size as an exact source grid.
3. Preserve original rasters, terrain HDF, Mapper configuration, and geometry/results. Stage a complete authorized project copy and record proposed changes. Reuse public acquisition/preparation APIs for source terrain; missing bathymetry is a data gap, not permission to fabricate it. Creation and registration are distinct: creating an HDF does not associate it with geometry, and registering an existing HDF does not create terrain.
4. For modifications, use public writers and inspect fresh HDF plus Mapper readback. Check enable flags, modification mode, native group registration, priority, and complete footprint. A written modification can be ignored by native export if Mapper registration is wrong. Read the selected notebook's semantic checks before using a line, polygon, or ellipse writer.
5. Audit geometry terrain/classification/projection associations and stale result-map terrain names. Preserve unaffected associations. Recompute affected geometry property tables through Commander when the task requires the model to consume the edited terrain; regenerate dependent computation/maps only within authorized scope. Do not treat existing hydraulic results or previously staged mapping inputs as current after a material terrain edit. Prepare fresh mapping inputs or use documented invalidation instead of manually deleting caches.
6. Validate the intended surface with affected and unchanged control locations, valid/nodata masks, grid and bounds, priority overlaps, and elevations/profile/volume evidence appropriate to the edit. If preprocessing or solving is authorized, verify final geometry/plan dependencies and completion separately from terrain acceptance. Record pending regeneration when it is outside the task.
7. For a GeoTIFF of an already registered terrain, use `RasTerrain.export_rasmapper_terrain()` with exact terrain selection and explicit modification policy. Retain the typed result and JSON receipt; inspect semantic validation and failure kind. Do not fall back to a numerically different row sampler or register the derivative back into the project unless requested.

Native terrain creation, analytical sampling, modification writing, and registered-terrain export have different runtime requirements. Discover the selected operation's actual support rather than assuming that Windows, Wine, or a newer HEC release qualifies all of them. Never invoke Ras.exe directly or substitute hand-written HDF edits for a supported Commander operation.

Return source/target identity, versions, CRS/datum/units, edit and priority summary, artifact/receipt paths, actual checks, association state, and remaining regeneration or runtime blockers. A valid terrain export is not hydraulic adequacy or regulatory approval.
