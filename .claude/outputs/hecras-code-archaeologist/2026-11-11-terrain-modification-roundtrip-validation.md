# Terrain modifications: read and write round trip against HEC-RAS 6.6 and 7.0.1 exports

**Date**: 2026-11-11
**Scope**: `RasTerrainModWriter` writers and readers, `fim/_terrain_mods.read_layers`, `fim/_terrain_scope`, `_terrain_modification_subset`
**Layout spec**: `2026-11-11-rasmapperlib-terrain-modification-layout.md` (same folder), including its section 12 (empirical corrections)

## Summary

Writer-authored modification layers now export pixel-identically to the same features authored by RAS Mapper. This holds for every supported kind, in HEC-RAS 6.6 and 7.0.1: ground lines (levee and channel; SetValue, SetIfHigher and SetIfLower; multi-feature; Max Reach below Top Width), constant polygons with holes, and ellipses including rotated ones and circles. The round trip is: read the RAS layer with ras-commander, write it into a copy of the same base terrain, export both, compare.

The writer channel defect is caused by `System Name`. The #790 writer stored the layer name there, and RAS Mapper builds any ground line with a non-empty `System Name` through its system path, even a lone feature. That path uses perpendicular cross-sections at control stations instead of offset lines, so the footprint differs at bends.

Two further defects were found and fixed:
- `add_channel_modification(depth=...)` stored `-depth` as an absolute elevation, so RAS cut channels to about -10 ft.
- RAS 7.x polygon layers, which carry a perimeter profile, were refused by the subset readers.

## Method

- Ground truth: `RasTerrain.export_rasmapper_terrain(downsample_factor=1, rasterize_modifications=True|False)` on HEC-RAS 6.6 and 7.0.1. HEC-RAS 7.0.2 is not installed on the host used, and 7.0.0 has an official modification-export defect.
- Base terrains: a 700 x 700 single-source clip (36.5 ft cells) of the public Bald Eagle Creek example DEM, created separately with each version's `CreateTerrain`. A single source avoids stitch-TIN noise: repeated exports were identical (0 px).
- RAS-authored features came from two sources:
  - Synthetic: layers created and saved through RasMapperLib's own modification-layer classes (6.6 and 7.0.1 assemblies, driven headlessly), so RAS's own serializer wrote the HDF.
  - Real: two terrains from a HEC-RAS 6.6 project whose modifications were drawn in the RAS Mapper GUI: a high-ground levee with 7 vertices, and a dam channel with Max Reach 100 below Top Width 600. This data is kept outside the repository.
- Write path: `read_layers` → `RasTerrainModWriter.add_modification_layer` into a stripped copy of the same base → export with the same version → pixel compare against the RAS-authored export, per layer and for all layers together.
- The build-host references (synthetic M1–M3) and the agency model shares were not reachable from the host used. Real-model coverage is therefore limited to the 6.6 project above.

## Version × feature matrix (fixed writer)

Pixel counts are pixels the RAS export modifies. "Diff" is writer-vs-RAS pixels with any difference (value or nodata mask). Every result was identical on 6.6 and 7.0.1.

| Feature (source) | RAS-modified px | Read correct | Write diff (6.6 / 7.0.1) | Max vertical error | #790 layout (System Name = name): diff, max |
|---|---|---|---|---|---|
| Channel, 2 features, SetIfLower (synthetic) | 2,022 | yes | 0 / 0 | 0 | 1,033 px, 793.5 ft |
| Ground line SetValue (synthetic) | 603 | yes | 0 / 0 | 0 | 218 px, 9.6 ft |
| Levee SetIfHigher (synthetic) | 642 | yes | 0 / 0 | 0 | 374 px, 715.3 ft |
| Channel, Max Reach < Top Width (synthetic) | 941 | yes | 0 / 0 | 0 | 536 px, 520.9 ft |
| Ellipses: rotated 30°, -63.5°, circle; SetValue + SetIfLower (synthetic) | 1,239 | yes | 0 / 0 | 0 | n/a |
| Polygons: with hole (SetValue) + triangle (SetIfHigher) (synthetic) | 7,428 | yes | 0 / 0 | 0 | n/a |
| All six layers together, overlapping, priorities 0–5 (synthetic) | 12,507 | yes | 0 / 0 | 0 | 2,161 px, 793.5 ft |
| GUI levee, 7 vertices (real, 6.6-authored) | 899 | yes | 0 / 0 | 0 | 212 px, 0.53 ft |
| GUI dam channel, Max Reach < Top Width (real, 6.6-authored) | 5,127 | yes | 0 / 0 | 0 | 4,819 px, 22.8 ft |
| `copy_modification_features`, ground lines (synthetic) | 2,022 / 603 / 642 / 941 | yes | 0 | 0 | n/a |
| `copy_modification_features`, SetValue polygon with hole (synthetic, 7.x layout) | 4,080 | yes (after fix) | 0 / 0 | 0 | n/a |

"Read correct" means `read_layers` returned geometry, profile, attributes and priority such that the written layer re-exports identically. Large maximum errors in the named column come from profiles far above or below the ground (the system path moves the template footprint by whole cells near bends).

## Root cause of the writer channel defect

- RasMapperLib (6.6, 7.0, 7.0.1) treats a ground line as part of a system whenever `System Name` is non-empty, including a single unjoined feature. Such features are built by the advanced (system) ground-line layer. That layer places perpendicular trapezoidal cross-sections at control stations and blends between them; the plain path offsets the centreline. The two give the same centreline elevations but different footprints around bends and joints.
- The #790 writer wrote `System Name` = layer name for every ground line. Every writer channel and levee therefore took the system path. RAS-Mapper-authored lines store an empty `System Name`: confirmed in GUI-authored 6.6 files and in layers saved by RasMapperLib 6.6 and 7.0.1.
- Evidence: on every measured case the named variant differs from the RAS-authored feature, and the differences concentrate at interior joints. On the real levee, 57% of differing pixels lie within 12 cells of an interior vertex and 12% near the ends. With the name blank, the difference is 0 px in all cases. This matches Fast-Map's measurement (1,506 px between the named and blank 22.5 km channel) and explains its 1,502 px writer-channel discrepancy.

## Fixes (code, test, export evidence)

| Fix | Unit test (synthetic, no model data) | Export evidence |
|---|---|---|
| Ground lines written as RAS saves them: `System Name` empty unless `system_name=` is passed (with a warning); `Transition Percent` and `Top Elevation` NaN; no `Profile` dataset or empty `Control Points` group; `Column`/`Row`/`Feature Type` metadata; gzip | `test_ground_line_layout_matches_ras_mapper`, `test_named_system_is_opt_in`, `test_add_high_ground_modification_writes_hdf_and_rasmap` | Matrix rows 1–4, 8–9: 0 px on 6.6 and 7.0.1 |
| Channel invert is an absolute profile (`profile_points`, `elevation`, polyline Z). `depth` now means below the terrain source sampled at each vertex. It used to write `-depth` absolute: RAS cut to -10 ft, up to 1,825 ft below ground | `test_channel_depth_is_measured_below_the_sampled_terrain`, `test_add_channel_modification_keeps_take_lower_mode` | Experiment "System Name" (6.6, 7.0.1): writer channel with depth 10 produced cells of -10…+10 ft |
| New layers go on top (Priority 0, which wins) and existing layers are renumbered 0..n-1, as RAS Mapper's GUI and group save do; `priority=` places a layer explicitly. The `.rasmap` element is inserted first | `test_layers_get_unique_priorities_newest_on_top` | All-layers row: 0 px with overlapping layers |
| `add_ellipse_modification` (Type Circle, `Circles` [n,5], rotation in degrees) and `add_modification_layer` (writes a `read_layers` layer back, multi-feature) | `test_constant_polygon_and_ellipse_writers`, `test_read_layers_round_trips_through_add_modification_layer` | Ellipse row: 0 px |
| Polygons: `elevation=` for constant polygons. Varying `shape_z`/`provided` boundaries stored as vertex Z with Use ShapeFile Z on and Generate off, the only varying form all versions read from storage | `test_varying_polygon_boundary_is_stored_as_vertex_z` | Constant polygons: 0 px. Vertex-Z form: layout per spec, not export-measured |
| `get_modification_profile` and sampling helpers read `Profile Values` (what RAS reads), not the `Profile` dataset older writers added. `sample_modification_surface` uses Max Reach as total width (half per side), raises channel sides instead of lowering them, and reads NaN slope as 3 and 0 as 0.001 | `test_profile_readback_reads_profile_values_like_ras_mapper`, `test_sample_modification_surface_follows_ras_template` | Straight-segment helper; no export claim |
| `read_layers` (Fast-Map request schema 2): adds `system_name` per ground-line feature, `rotation` per ellipse, `length_units` per ground-line layer (from the project's `SI Units`/`English Units`) | `test_qualified_layers_are_staged`, `test_project_length_units_follow_the_ras_project` | — |
| `read_layers` refusal changes: refuses any non-empty `System Name`, unknown or mis-cased `Subtype`, and RAS-applied types it cannot stage (Rectangle, Triangle, Encroachment Polygon, Levee1, Pier, Tree). Accepts ground-line SetValue, Max Reach ≤ Top Width and rotated ellipses. Skips, with a warning, types RAS Mapper ignores (including legacy `Type=Channel`) and features whose `Elevation Value` is NaN. Reads NaN slopes as 3 | `test_forms_the_engine_now_applies_are_staged`, `test_unqualified_forms_are_refused`, `test_types_ras_mapper_ignores_are_skipped`, `test_nan_elevation_features_are_skipped_and_nan_slope_reads_as_three` | Legacy `Type=Channel`: 0 px changed on 6.6 and 7.0.1 |
| `.rasmap` gate: with a rasmap whose terrain layer lacks an `ElevationModificationGroup`, the effective-terrain scope reports no modifications, because RAS applies none | `test_hdf_modifications_need_the_rasmap_modification_group` | No group: 0 px. Empty group, partial list, or all unchecked: 12,507 px (6.6 and 7.0.1) |
| Subset readers (`get_modification_features`, `copy_`/`export_modification_features`) accept the 7.x polygon layout with `Profile Info`/`Profile Values` and subset it per feature | `test_ras_7x_polygon_profile_tables_are_accepted_and_subset` | RAS 7.0.1- and 6.6-authored SetValue polygon copied: 0 of 4,080 px |

`Transition Percent` 0.5 vs NaN on an unnamed line: 0 px on both versions. The per-feature path ignores it, so the NaN default only matches RAS's own files.

## Version-specific behaviour (explicit)

- 6.6 skips ground lines whose Max Reach is not wider than one cell at export. 7.0 and 7.0.1 burn them in. Measured: Max Reach 20 ft on 36.5 ft cells gives 0 px on 6.6 and 171 px on 7.0.1. A writer cannot make one file behave identically in both, and `read_layers` does not carry the target version.
- 6.6 stores no polygon perimeter profile; 7.0 and 7.0.1 do. Constant polygons ignore it in all versions. Generate-boundary polygons follow the stored profile only in 7.x; 6.6 samples the terrain.
- Everything else measured here was identical between 6.6 and 7.0.1.

## What remains unsupported or unverified

> **Update (ras-commander-fast-map#40 and the final `read_layers`):** the engine now reproduces named systems, ground-line control points, ground-line `Add`, NaN templates, and polygons with boundary elevations from perimeter control points or a stored profile. `read_layers` stages them, with `system_name`, `transition_percent`, `elev_pt_tolerance`, layer `control_points`, polygon `generate_boundary`, `use_shape_z`, `profile`, `vertex_z` and `length_units`. The request also carries `hecras_version` (`"6.6"`, or 7.0.1 rules for every other version). The list below states only what is still refused or unverified.

- Refused by `read_layers` and the engine:
  - boundary elevations sampled from the terrain (no stored profile and no perimeter control point);
  - shape-Z polygons without boundary elevations;
  - multi-part polygons that need a TIN;
  - named ground lines with control points or a NaN template;
  - named ground lines and terrain-sampled boundaries under 6.6;
  - a NaN Top Width with a finite Max Reach;
  - RAS types Rectangle, Triangle, Encroachment Polygon, Levee1, Pier and Tree.

  The writers still write `system_name` and Add on explicit request, and Generate polygons via `boundary_from_terrain`; none of these writer paths is round-trip-qualified.
- Vertex-Z polygon writing follows the code reading but has no export measurement yet.
- `copy_modification_features`/`get_modification_features` still refuse ellipse layers, and refuse a whole polygon group when any of its features is not a constant SetValue polygon, even if that feature is not selected.
- `list_modifications` reports the first feature's attributes per layer (now with `feature_count` and `system_names`).
- No measurements on HEC-RAS 7.0.2 (not installed on the host), on the build-host M1–M3 projects, or on the agency models (not reachable from the host).

## Fields Fast-Map needed (now provided)

- The target HEC-RAS version: `build_effective_terrain(hecras_version=...)`, else the `ras_object` or the project's newest `Program Version`.
- The `.rasmap` `ElevationModificationGroup` gate is still applied by the effective-terrain caller only when it is given `rasmap_path`.
- `elev_pt_tolerance` and `Transition Percent` are now sent, because the engine's system path and control-point search use them. Feature names are not sent; they have no effect.

---
*Prose findings only; no decompiled source reproduced. Scratch harnesses and exports were kept outside the repository.*
