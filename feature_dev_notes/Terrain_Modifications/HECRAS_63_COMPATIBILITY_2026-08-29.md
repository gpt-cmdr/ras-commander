# HEC-RAS 6.3 native terrain-export compatibility

Date: 2026-08-29

## Decision

`RasTerrain.export_rasmapper_terrain()` does not support HEC-RAS 6.3 or 6.3.1.
The supported runtime families remain HEC-RAS 6.6.x and checked 7.0.x. The
public API now checks an explicitly supplied `RasPrj.ras_version` before any
filesystem or native work and raises `ValueError` for 6.3, for other
unsupported versions, or for a conflicting explicit runtime family.

This is an intentional fail-closed compatibility boundary, not an assumption
that 6.3 terrain modifications are unusable in every context.

## Independent 6.3 inspection

The installed 6.3 and 6.3.1 `RasMapperLib.dll` assemblies were reflected and
decompiled independently after the 6.6/7.0 implementation was complete. Both
identify themselves as `RasMapperLib, Version=2.0.0.0`, and both expose the
same checked terrain-export surface described below.

| Installed folder | Mapper file/product version | File timestamp |
|------------------|-----------------------------|----------------|
| `HEC-RAS\6.3` | `2.0.0.0` | 2022-08-25 13:06:42 |
| `HEC-RAS\6.3.1` | `2.0.0.0` | 2022-09-30 13:52:54 |

The checked 6.3 `TerrainLayer` exposes:

- `RasterFilesInfo` as an array of the older `RasterFileInfo` type;
- `ResampleMethod` and native `Resample(...)` overloads;
- `ExportResampleToSingleFile(string, double, TiffMetadata<float>, ProgressReporter)`;
- XML loading and `RASMapperCom.GetTerrainFromXML`.

It does not expose the nine-parameter private method used by 6.6/7.0:

```text
GenerateNewRasTerrain(
    string, Extent, double, bool, bool, ProgressReporter,
    Action<SpatialIndex<int>>, List<string>, ref TiffMetadata<float>)
```

It also lacks `ExportRasterOptions`, and therefore lacks the checked bounded
`resampleTo1RFI` plus `resampleVecMods` invocation contract.

## Why the older methods are not a safe substitute

Decompilation confirms that 6.3
`TerrainLayer.ExportResampleToSingleFile(...)` obtains its bounds directly from
`TerrainLayer.Extent`. It accepts no requested extent and writes tiled output
covering the complete terrain. Its internal `Resample(...)` call does apply the
loaded modification group and source stitches, but the method cannot implement
this API's required bounded derivative contract.

The 6.3 `ClipTerrainToExtent(...)` path is also not equivalent. It copies
subsets of individual source TIFF tiles, builds a new RAS terrain, and then
copies the modification definitions into the new terrain HDF. It does not
produce the requested single GeoTIFF with the modifications baked into its
cells. Driving that UI path is out of scope, and manually reconstructing the
writer around lower-level `Resample(...)` calls would cease to be the thin
wrapper around RAS Mapper's own terrain export operation that this feature
requires.

## Compatibility contract

| HEC-RAS family | API status | Qualification status |
|----------------|------------|----------------------|
| 6.6.x | Accepted | Native Windows and Wine qualified |
| 7.0.x | Accepted | Checked native API and bounded stitched output |
| 6.3.x | Rejected | Inspected; required bounded export contract absent |
| all others | Rejected | Not qualified; no private-API guessing |

Workflows that initialize a project with HEC-RAS 6.3 receive an actionable
error before export staging begins. They must run this export with a project
initialized to a matching supported HEC-RAS runtime. The legacy
row-sampled `RasTerrainMod.compute_modified_terrain_raster()` remains available
for its existing analytical use, but it is not used as a production fallback.

A real `RasPrj` was initialized against the repository's Muncie fixture with
`ras_version="6.3"`, with result/HDF metadata loading disabled. Calling the
public terrain export with that object raised the documented `ValueError`; the
requested output parent directory did not exist before the call and was still
absent afterward. This confirms that the public guard runs before terrain
enumeration, staging, or output filesystem mutation.
