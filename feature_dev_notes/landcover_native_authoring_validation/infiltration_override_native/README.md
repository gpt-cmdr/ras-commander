# Native Infiltration Override Authoring

## Scope

This note records the RASDecomp investigation and live qualification for both
geometry-wide infiltration Base Overrides and named infiltration-region
parameter tables. The implementation deliberately does not create or modify
the compound `/Geometry/Infiltration` schema with `h5py`; HEC-RAS owns that
schema.

## RASDecomp findings

The authoritative API baselines are under:

- `H:\CLB-Repos\RASDecomp\.artifacts\baselines\rasmapper\5.0.7`
- `H:\CLB-Repos\RASDecomp\.artifacts\baselines\rasmapper\6.0`
- `H:\CLB-Repos\RASDecomp\.artifacts\baselines\rasmapper\6.6`
- `H:\CLB-Repos\RASDecomp\.artifacts\baselines\rasmapper\7.0`

HEC-RAS 5.0.7 does not expose `InterpretationOverrideLayer` or
`RASGeometry.InfiltrationOverrideRegions`; the geometry-infiltration API is
therefore unavailable and fails closed for 5.x.

The 6.0, 6.6, and 7.0 APIs all expose:

- `RASGeometry.InfiltrationOverrideRegions` returning
  `RasMapperLib.InterpretationOverrideLayer`
- `InterpretationOverrideLayer : PolygonFeatureLayer, IGeometryLayer`
- inherited `AddFeature(Polygon)`, `SetFeatureName(...)`, and `Save()`
- public per-region `SetParameterTable(int, ParameterSet)` and
  `GetParameterTable(int)`
- `HDFLoadFeatureTable(H5Reader)` and `HDFSaveFeatureTable(H5Writer)`
- internal `ParameterSet _baseVariableOverrides`

These are separate attribution surfaces. Decompilation shows
`BaseInterpretationMergedWithLC` applying `_baseVariableOverrides` to the
classification-wide fallback. `GetOverridePolygonMap()` separately constructs
one `ParameterizedPolygon` per feature from `Polygon(fid)` and
`GetParameterTable(fid)`. The solver's parameter resampler applies the region
table inside that polygon and otherwise falls back to the geometry-wide base
map. The HDF mirrors this split:

- `/Geometry/Infiltration/Base Overrides` stores the geometry-wide
  class-to-parameter fallback;
- `/Geometry/Infiltration/Variables/<parameter>` stores one parameter-table
  row per native region.

A copied region polygon therefore does not spatially constrain Base Overrides.

The constructor accepts the geometry, layer name/subfolder, a land
classification provider, ignored parameters, and an optional base
`ParameterSet`. There is no public setter for the geometry-level base
`ParameterSet`. The implementation consequently uses reflection only after
verifying the complete private ABI fingerprint:

- declaring type:
  `RasMapperLib.InterpretationOverrideLayer`
- field name: `_baseVariableOverrides`
- field type:
  `Geospatial.Rasters.Classifications.ParameterSet`
- internal/assembly, instance, writable field

Any mismatch aborts before saving. Supporting decompilations are in:

`H:\tmp\rasdecomp_infiltration_20260725\<version>\`

## Scoped-save safety

`RASGeometry.Save()` was rejected. RASDecomp shows that it loops over every
`IGeometryLayer` and serializes all of them. That would expose unrelated
geometry datasets to a much larger mutation surface.

The implementation calls the inherited
`InterpretationOverrideLayer.Save()` instead. RASDecomp shows this opens HEC's
`H5Writer` and dispatches the selected layer's
`HDFSaveFeatureTable(H5Writer)`. HEC-RAS therefore authors the exact dataset
shapes, compound types, attributes, polygon records, and parameter rows for
the infiltration layer while leaving unrelated geometry layers outside the
save operation.

## Public API replacement and compatibility map

| Previous API | Canonical API | Status |
| --- | --- | --- |
| `create_infiltration_group(...)` | `create_infiltration_override_regions(...)` | Deprecated working wrapper; now native-only |
| `set_infiltration_baseoverrides(...)` | `set_infiltration_base_overrides(...)` | Deprecated working spelling wrapper; now native-only |
| `scale_infiltration_baseoverrides(...)` | `scale_infiltration_base_overrides(...)` | Deprecated working spelling wrapper |
| `set_infiltration_layer_data(...)` | `set_infiltration_sidecar_parameters(...)` | Deprecated sidecar compatibility alias |

The additive canonical region APIs are:

- `get_infiltration_region_overrides(...)`
- `set_infiltration_region_overrides(...)`
- `scale_infiltration_region_overrides(...)`

They do not replace or deprecate the geometry-wide Base Override family.
`get_infiltration_calibration_regions(...)` also remains available as the
bulk, variable-oriented HDF reader.

`RasCalibrate.make_infiltration_apply_fn(...)` now calls the canonical
`set_infiltration_base_overrides(...)` API and passes both its optional
explicit HEC-RAS version and the supplied project object.

Version resolution is explicit version, then supplied `ras_object`, then the
global RAS project, otherwise an error. Each process also verifies that the
loaded `RasMapperLib.dll` is the exact requested installation; a process that
already loaded a different HEC runtime must be restarted.

## Mutation gates

Before a save, the implementation requires:

- a supported HEC-RAS 6.x or 7.0.x runtime;
- the exact native layer and private-field types;
- a complete, existing associated infiltration classification sidecar and
  class map;
- exactly one input row for every native class, with no duplicates;
- only parameters exposed by HEC's current `ParameterSet`;
- valid finite parameter values or HEC's `-9999` sentinel.

Creating infiltration regions copies HEC's native Manning-region polygons
using native `Polygon` objects. Setting a partial parameter-column table
preserves omitted native parameter columns. A regional mutation resolves
exactly one current zero-based feature ID or unique name and uses only the
public `GetParameterTable` / `SetParameterTable` API.

Regional polygons containing an interior ring fail closed. HEC-RAS 6.0
through 7.0.1 persists and reloads the ring, but
`GetOverridePolygonMap()` passes the polygon through the same
`Converter.Convert(RasMapperLib.Polygon)` path that discards part boundaries
before parameter resampling. The supported replacement is explicit,
non-overlapping, hole-free polygons.

Every mutation makes a timestamped durable pre-edit backup, keeps a temporary
rollback snapshot, saves through the scoped native layer, releases/reloads the
geometry, and compares the native readback with the requested parameter
values. Regional validation additionally proves that Base Overrides, all
unselected region tables, region names, and polygons remain unchanged.

## Qualification boundary

The live tests in `LIVE_TEST_RESULTS.md` establish native creation, native
Base Overrides authoring, schema ownership, and fresh native reload for
HEC-RAS 6.0, 6.6, and 7.0. Notebook 218 provides the end-to-end 7.0 gate for
recomputed and final plan-HDF arrays. Regional mutation is accepted by spatial
attribution in those arrays; cumulative infiltration and WSE are secondary
hydraulic evidence because a valid regional parameter change need not alter a
hydraulically inactive cell.
