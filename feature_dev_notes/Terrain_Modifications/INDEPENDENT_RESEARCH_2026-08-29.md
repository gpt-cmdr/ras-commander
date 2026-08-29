# Native RAS Mapper terrain export: independent research

Date: 2026-08-29
Status: complete before production implementation
Base revision: `d7784fcc7714ca75632eef5338612fece28609aa`

## Scope and method

This investigation independently checked the proposed native terrain-export design against the current `ras-commander` API, examples, notebooks, tests, terrain-modification notes, managed/native helpers, installed HEC-RAS assemblies, and the fixture database. The initial HEC-RAS 6.6 and 7.0.0 inspection was subsequently expanded to 6.3, 6.3.1, 6.4.1, 6.5, 6.7 Beta 4, and 6.7 Beta 5; see `HECRAS_VERSION_COMPATIBILITY_2026-08-29.md` for the controlling support decision. Small bounded probes were run against registered terrains; no project terrain registrations were changed.

## Existing upstream behavior and prior art

- No equivalent native RAS Mapper terrain export exists on the base revision.
- `RasTerrainMod.compute_modified_terrain_raster()` is an in-process, row-by-row `TerrainProfile` sampler. It remains useful for small analytical work but is neither a native RAS Mapper consolidation nor a production fallback for this feature.
- `RasMap.list_terrain_layers()` already provides the DataFrame-first registered-terrain inventory and project-aware selection surface required by the public API.
- `RasGeometryCompute` and the result classes in `ComputeResults.py` establish the public error/result conventions, but they do not expose this RAS Mapper operation.
- `_gdal_runtime.py` and `_native_helper.py` contain useful runtime-staging ideas. The new host is intentionally focused and does not introduce hashes or depend on uncommitted mesh-host work.

## Verified HEC-RAS API surface

The proposed operation exists in the installed HEC-RAS 6.4.1, 6.5, 6.6, 6.7 Beta 4/5, and 7.0.0 `RasMapperLib` assemblies, but it is **private**, not public. It is absent from 6.3 and 6.3.1:

```csharp
private void GenerateNewRasTerrain(
    string newTerrainTifFN,
    RasMapperLib.Extent extent,
    double resampleCellSize,
    bool resampleTo1RFI,
    bool resampleVecMods,
    Utility.Progress.ProgressReporter prog,
    Action<RasMapperLib.SpatialIndex<int>> addItemsToSpIdx,
    List<string> newRFIs,
    ref TiffAssist.TiffMetadata<float> md)
```

The signature is identical in the checked 6.4.1 through 7.0.0 assemblies. The implementation therefore must resolve the non-public instance method by exact parameter contract and fail closed if it changes.

Other verified details:

- `TerrainLayer` exposes constructors `()`, `(string name)`, and `(string name, string filename, bool canEdit)`.
- `TerrainLayer.ResampleMethod`, `TerrainLayer.Extent`, `TerrainLayer.Modifications`, `RasterFileCount`, and `RasterFileInfo(int)` are public. A public `RasterFilesInfo` collection is not available in the checked assemblies.
- Public raster-file information includes filename, priority, rows, columns, extent, levels, and cell sizes.
- `TerrainLayer.ResampleMethod` accepts the vendor GDAL terms `near`, `average`, `bilinear`, `cubic`, `cubicspline`, and `lanczos` in the checked families. This feature fixes the base export to `near` and exposes no free-form method parameter.
- `Extent`'s constructor order is `(maxX, minX, maxY, minY)`.
- `ProgressReporter` may be null internally, but the wrapper supplies a real reporter. Its relevant events report `(int)` progress and `(string, MessageType)` messages.
- The spatial-index callback is mandatory because the method invokes it unconditionally. The GUI-equivalent bounded callback is `index => index.Add(extent, 0)`.
- `newRFIs` must be a non-null `List<string>`; the method appends the produced TIFF.
- The by-reference `TiffMetadata<float>` argument may begin as null. With reflection, the updated value is returned in the final element of the invocation argument array.
- `ExportRasterOptions` is nested under `RasMapperLib.ExportRaster`; it is not needed by this specific private method.
- HEC-RAS 7.0.0 code adds ground-line force-render handling but preserves the checked invocation contract.

## Loading the registered terrain without losing semantics

`RASMapperCom.GetTerrainFromXML(XmlDocument, string)` is public, but its terrain-name XPath is assembled by string concatenation and is unsafe for names containing an apostrophe. The robust construction is:

1. Load the project's exact `.rasmap` XML.
2. Set `SharedData.RasMapFilename` to that file.
3. Set `SharedData.SRSFilename` from `RASMapperCom.GetSRSFromRasmapDoc(...)`.
4. Apply the `/RASMapper/Units` value through `SharedData.SetUnitsSystem(...)`.
5. Find the exact `/RASMapper/Terrains/Layer` element by ordinal comparison of its `Name` attribute.
6. Construct `TerrainLayer(name)` and call its public `XMLLoad(XmlElement)`.

That path loads the original registered HDF references and preserves source order/priority, masks, stitches, and vector modifications. Reconstructing a terrain from loose raster filenames would lose those semantics and is rejected.

## Completion behavior of `resampleTo1RFI=true`

The checked implementation:

- chooses the minimum source level-zero cell size when the requested cell size is negative;
- computes rows and columns with `Ceiling(extent dimension / cell size)`;
- anchors the output at `extent.MinX` and `extent.MaxY` without snapping to a source grid;
- writes one Float32 tiled GeoTIFF with nodata metadata, disposes the writer, calculates a histogram, and applies spatial-reference/georeference work;
- appends that TIFF to `newRFIs`;
- does not create the terrain HDF or register a derivative. Those are later GUI workflow steps and are outside this wrapper.

Small bounded probes produced one TIFF and no persistent overview or sidecar files. Because the vendor uses floating-point `Ceiling`, an apparently integral extent can gain a row or column. The host must calculate integer grid dimensions first, keep the desired MinX/MaxY origin exact, and pass an inward-adjusted far edge solely to avoid a floating-point overrun. Semantic validation must then enforce the intended dimensions and grid.

## Grid and multi-source findings

- Output resolution is source-derived: native level-zero cell size multiplied by the allowed factor `1`, `2`, `4`, or `8`.
- Requested bounds are snapped outward to the output grid, anchored on an authoritative native-resolution source's MinX and MaxY.
- The authoritative source is selected among sources at the finest native resolution, using terrain priority and then registered order as deterministic tie-breakers.
- Other registered sources need valid positive resolution and compatible integer resolution ratios. Their origins need not align: the native terrain layer and its stitch data resolve seams. Rejecting non-aligned origins would incorrectly reject the Muncie stitched fixture.
- Nearest-neighbor is required for the base export path. Vendor overview generation may use its own averaging behavior; that does not change the exported base raster.

## Fixture selection and qualification evidence

Fixture database candidates were inspected rather than inferred from filenames:

- **UPGU3**, project database id 1412: `UPGU3.rasmap` registers `Terrain`, one approximately 1 m / 3.280833 US survey foot source, and 806 `SetIfLower` channel modifications. It is the modification-intensive bounded-window fixture.
- **Muncie**, project database id 29: `TerrainWithChannel` has two 5-foot sources, explicit stitches, and different source origins. It is the multi-source stitched fixture.
- **Turkey Gully**, project database id 800: `Terrain.Terrain COH Prefer` has one source and one polygon modification. It is a small modification smoke fixture.

Pre-implementation probes established the following evidence:

- Native HEC-RAS 6.6, bounded Turkey Gully 2x: 1,129 of 4,214 valid cells changed with modifications enabled; 3,085 control cells were unchanged.
- Native HEC-RAS 6.6, bounded UPGU3 2x: 73 of 1,632 valid cells changed across a known channel; all observed changes lowered elevation, with a minimum delta of -27.0625 feet. The remaining 1,559 valid cells were unaffected controls.
- Native HEC-RAS 6.6, bounded UPGU3 4x: completed successfully. The scratch probe also reproduced the vendor extra-row/column floating-point issue, justifying exact grid validation in the host.
- Native HEC-RAS 6.6, bounded Muncie 2x: completed with both sources loaded and stitch information preserved.
- Native HEC-RAS 7.0.0, bounded Muncie 2x: completed and was pixel-identical to the 6.6 result for the checked window. This remains audit-only evidence because HEC documents a separate terrain-modification export defect in 7.0.0.
- Wine 10.0 with Wine Mono 10.0, using the HEC-RAS 6.6 mapper/native runtime staged into a task-local prefix: bounded Muncie 2x completed in 0.68 seconds, reached approximately 150 MiB maximum resident memory, and was pixel-identical to native Windows 6.6. The dedicated CLB07 worker was unreachable, so this is exact 6.6 runtime parity evidence on a controlled alternate worker, not qualification of that unavailable worker image.

## Implementation consequences

- Use a focused x86 managed helper and invoke the exact non-public method reflectively.
- Load only a registered terrain from its project `.rasmap`; never build a loose-source approximation.
- Emit structured helper results and preserve progress/messages for diagnosis.
- Use task-local runtime state and terminate only the process/session created by the call.
- Produce a same-directory unique partial TIFF, validate its semantics, and promote atomically.
- Add no model, input, output, installer, dependency, or executable hashes to requests, receipts, logs, or documentation.
