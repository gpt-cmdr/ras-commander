# Native RAS Mapper terrain export: API consistency audit

Date: 2026-08-29
Status: approved contract, recorded before production implementation

## Audit result

No equivalent public API exists on the base revision. The feature should extend `RasTerrain` with one supervised native operation, reuse `RasMap.list_terrain_layers()` for inventory and selection, and return a bool-compatible typed result following `ComputeResults` conventions. `RasTerrainMod.compute_modified_terrain_raster()` remains unchanged and is explicitly not a production fallback.

## Final public contract

```python
RasTerrain.export_rasmapper_terrain(
    ras_project_path,
    output_tif,
    terrain_name=None,
    extent=None,
    downsample_factor=1,
    rasterize_modifications=True,
    overwrite=False,
    timeout_seconds=1800.0,
    hecras_version=None,
    ras_object=None,
    receipt_path=None,
) -> TerrainExportResult
```

Contract decisions:

- `ras_project_path`, `output_tif`, and `receipt_path` accept `str` and `Path` values. Windows drive, UNC, Wine-visible, space-containing, and ordinary POSIX paths are normalized only at the process boundary.
- `terrain_name=None` is accepted only when the registered-terrain DataFrame contains exactly one row. An explicit name must match exactly. Ambiguity is an input error, not an arbitrary first-row selection.
- `extent` is `(xmin, ymin, xmax, ymax)`. Omission exports the registered terrain extent; bounded windows are preferred for large qualification fixtures.
- `downsample_factor` is restricted to the exact source-derived set `{1, 2, 4, 8}`. A free-form target cell size and arbitrary resampling terms are intentionally not public.
- The base export always uses nearest-neighbor resampling. `rasterize_modifications` maps directly to native `resampleVecMods`.
- `overwrite` defaults to false. Output and receipt collisions are checked before native work begins.
- `hecras_version` is explicit or inherited from `ras_object.ras_version`; it is resolved through existing HEC-RAS installation conventions. The accepted exact releases are 6.4.1, 6.5, and 6.6. The later compatibility audit rejects 6.3.x, 6.4.0, 6.7 betas, 7.0.0, 7.0.1, and unqualified patch terms with version-specific guidance.
- `ras_object` must be an initialized `RasPrj` when supplied. Its version and identifiable executable release are checked before output or native work and must not conflict with an explicit exact runtime, preserving multi-project context without making global state authoritative.
- `receipt_path` defaults to `<output_tif>.receipt.json`. The receipt is always emitted for a promoted success and contains no hashes.

Input/programming errors such as a missing project, ambiguous terrain, invalid extent/factor, or protected output raise the corresponding clear exception. A started native operation returns a failed `TerrainExportResult` for helper/runtime/timeout/validation failure, consistent with compute-result patterns.

## Typed result

`TerrainExportResult` is bool-compatible and records:

- success, error, timeout flag, elapsed seconds, and diagnostic messages;
- output and receipt paths;
- selected terrain name and registered terrain HDF path;
- requested and snapped extents;
- native/output cell sizes and downsample factor;
- whether modifications were rasterized;
- the DataFrame source inventory returned by the native helper;
- semantic validation findings.

`bool(result)` is true only after semantic validation and atomic promotion succeed.

## Consistency by subsystem

### RasTerrain

The operation belongs on `RasTerrain`: it creates a terrain raster derivative and relies on the existing HEC/GDAL environment logic. A static, logged public method avoids constructing a synthetic terrain object and matches the module's utility style.

### RasMap and DataFrame-first inventory

Terrain selection begins with `RasMap.list_terrain_layers()`. That preserves the established DataFrame-first discovery API and `ras_object` multi-project behavior. The managed helper independently verifies the exact selected XML layer before export; Python inventory is not treated as authority for internal source/stitch details.

### RasTerrainMod

The row-by-row sampler is preserved for compatibility and analytical workflows. Falling back to it would silently change interpolation, masks, stitches, and modification mathematics, so native export failure is reported instead.

### RasGeometryCompute and ComputeResults

The new result follows the bool-compatible dataclass pattern and carries elapsed time/messages/error state. It is a separate result type because raster grid, source inventory, receipt, and validation fields do not fit geometry compute results.

### Native helpers and mesh-host concepts

The implementation reuses only stable concepts: a focused out-of-process helper, selected-version assemblies, task-local staging, GDAL/native dependencies, path translation, timeout, and owned-process cleanup. It does not depend on uncommitted mesh-host code and never terminates a shared Wine server.

### Paths, logging, and errors

The public entry point uses existing `@log_call` behavior. Paths are absolute before entering the helper request. User-provided display paths remain available in the typed result. Requests and helper responses are schema-validated; unexpected fields are tolerated only where explicitly versioned, while missing or contradictory required fields fail validation.

### Optional dependencies

The core operation must not require `rasterio`, `psutil`, pythonnet, or Controller COM. It uses the selected HEC-RAS runtime and bundled GDAL command-line tools for semantic validation. Optional raster libraries may be used only by qualification tests for pixel-by-pixel comparisons.

### Backward compatibility

The change is additive. Existing terrain sampling, geometry compute, imports, and project mutation behavior remain unchanged. `overwrite=False` prevents accidental replacement, and the derivative is never registered back into the source project.

## Host and artifact contract

- The helper exposes structured `inspect` and `export` operations with a versioned request/response schema.
- `inspect` returns the XML-loaded registered terrain extent and ordered raster-file inventory.
- Python calculates the authoritative source grid, validates multi-source resolution compatibility, snaps bounds, and calculates exact integer dimensions.
- `export` reloads the registered XML layer, sets `ResampleMethod="near"`, calls the exact private method, and reports `newRFIs`, progress, messages, metadata, and files observed.
- The helper writes only to a unique same-directory partial TIFF. Python validates driver, single Float32 band, dimensions, affine transform, CRS presence, nodata, and at least one valid pixel before atomic promotion.
- The final machine-readable receipt is written as a unique partial and atomically promoted after the TIFF. It records requested settings, registered sources, actual output semantics, timing, and messages, but no hashes.
- A timeout kills only the Windows Job Object or POSIX process group created for this invocation. Temporary helper/native/GDAL state and partial outputs are removed without touching unrelated processes or project files.

## Rejected alternatives

- Controller COM, `RasControl`, and UI automation: outside scope and unnecessary.
- Reimplementing vector-modification TIN math: would diverge from the native operation.
- Reconstructing `TerrainLayer` from source filenames: loses XML-defined masks, stitches, ordering, and modifications.
- Arbitrary cell sizes/resampling methods: violate exact source-derived 1x/2x/4x/8x and nearest-neighbor semantics.
- In-process pythonnet as the public execution path: provides weaker timeout and process-ownership guarantees.
- A mesh-host dependency or web service: unnecessarily broadens coupling and deployment.
