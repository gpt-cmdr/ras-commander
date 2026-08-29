# Native RAS Mapper Terrain Export

**Status**: Implemented and qualified on branch
`codex/native-rasmapper-terrain-export`; upstream review is open in pull
request #321

**Started**: 2026-08-29

**Target**: A public ras-commander API for exporting a consolidated GeoTIFF
through HEC-RAS's own RAS Mapper terrain engine, optionally rasterizing terrain
modifications while resampling.

## Implementation status (2026-08-29)

The independent research, API-consistency audit, implementation, unit tests,
and bounded real-runtime qualification are complete. See:

- `INDEPENDENT_RESEARCH_2026-08-29.md`
- `API_CONSISTENCY_AUDIT_2026-08-29.md`
- `QUALIFICATION_REPORT_2026-08-29.md`
- `HECRAS_63_COMPATIBILITY_2026-08-29.md`
- `HECRAS_VERSION_COMPATIBILITY_2026-08-29.md`

The completed public API is `RasTerrain.export_rasmapper_terrain(...)`. It
returns `TerrainExportResult`, writes a machine-readable receipt, validates the
single GeoTIFF before promotion, and never registers the derivative in the
source project.

Notebook integration is also complete. Five accepted revisions document the
feature without committing generated outputs: `316_terrain_modifications`
contains real HEC-RAS 6.6 mixed-source modification-off/on semantic and visual
evidence; `612_benefit_area_analysis` points registered terrains to the native
export while preserving loose-raster creation guidance;
`920_terrain_creation` distinguishes creation from registered-terrain export;
`930_terrain_modification_analysis` preserves the analytical sampler's scope;
and the new `931_native_rasmapper_terrain_export` provides the focused bounded
selection, result, receipt, grid, source-inventory, and review-figure workflow.

A post-implementation correction removed an invalid Python preflight that
required every source resolution to be an integer multiple of the finest
source. RAS Mapper's single-raster operation accepts mixed source resolutions
and reconciles them at the explicit `resampleCellSize`. HEC-RAS 6.6 now passes
the original Bald Eagle `Terrain50` fixture with 36.504512049933-foot and
20-foot sources, including bounded modification-off/on semantic evidence.

The follow-up version audit checked official release notes, reflected every
locally installed runtime from 6.3 through 7.0.1, and ran bounded exports on
6.4.1, 6.5, 6.6, 6.7 Beta 4/5, 7.0.0, and 7.0.1. The public API accepts exactly
6.4.1, 6.5, 6.6, and 7.0.1. It validates `RasPrj.ras_version` and the identifiable
release in `ras_exe_path`, then raises before filesystem or native work for all
other versions. HEC-RAS 7.0.0 is rejected because HEC documents a terrain-
modification export defect; the exact official 7.0.1 binary fixes that issue
and passed native qualification. Exact 7.1 is forward-open for its future
official binary, with the exact helper contract still checked at runtime.

## Original implementation gap

The March 2026 terrain-modification research already found the correct vendor
workflow:

1. RAS Mapper's **Generate New RAS Terrain** operation can export a single
   raster.
2. Its **Resample Vec Mods** option bakes terrain modifications into the
   exported values.
3. `TerrainLayer.Resample()` applies the modification surfaces through
   HEC-RAS's own terrain source ordering, stitching, masks, TINs, and
   replacement rules.

That research did not become a production export API. The implemented
`RasTerrainMod.compute_modified_terrain_raster()` instead samples profiles
row-by-row. That method is useful for small analytical rasters, but it is not
the appropriate production path for a large, stitched HEC-RAS terrain.

The missing feature is therefore not terrain-modification mathematics. It is a
thin, supervised wrapper around the native RAS Mapper export operation.

## Corrected HEC-RAS 6.6 API surface

Reflection against the installed HEC-RAS 6.6 `RasMapperLib.dll` confirmed:

```text
TerrainLayer.GenerateNewRasTerrain(
    string newTerrainTifFN,
    Extent extent,
    double resampleCellSize,
    bool resampleTo1RFI,
    bool resampleVecMods,
    ProgressReporter prog,
    Action<SpatialIndex<int>> addItemsToSpIdx,
    List<string> newRFIs,
    ref TiffMetadata<float> md
)
```

Independent reflection corrected two assumptions in the original proposal:
`GenerateNewRasTerrain` is a **private** instance method in the checked 6.4.1,
6.5, 6.6, 6.7 Beta 4/5, 7.0.0, and 7.0.1 assemblies, and there is no public
`RasterFilesInfo` collection on that newer surface.
The helper resolves the exact non-public nine-parameter contract and uses the
public `RasterFileCount` plus `RasterFileInfo(int)` inventory.

Related public API:

```text
TerrainLayer.ResampleMethod : string

ExportRasterOptions(
    bool resampleToSingle,
    double cellSize,
    ClipOption clip,
    string filename,
    bool resampleVecMods,
    double extentBuffer
)
```

`TerrainLayer` also exposes `Extent`, `Modifications`, `RasterFileCount`,
`RasterFileInfo(int)`, and the modification-aware `Resample()` overloads used
internally by the verified vendor operation.

## Required independent research before implementation

The implementation task must begin by independently auditing the repository
and the installed HEC-RAS APIs. It must not assume this document's proposed
shape is correct merely because the symbols exist.

The audit must answer:

1. Does ras-commander already expose this operation under another name or
   through an existing managed helper?
2. What is the most reliable supported way to construct the selected
   `TerrainLayer` with its raster-file priorities, stitches, masks, and
   modifications fully loaded?
3. Does construction from the terrain HDF alone preserve all semantics, or
   must the helper load the layer from `.rasmap` XML?
4. What non-null `ProgressReporter`, spatial-index callback, `newRFIs`, and
   `TiffMetadata<float>` objects does `GenerateNewRasTerrain()` require?
5. What files does the method create when `resampleTo1RFI=True`, and when is
   each file complete and unlocked?
6. Are `ResampleMethod` values stable across HEC-RAS 6.6, 7.0, and 7.0.1?
7. Can one out-of-process helper provide identical behavior on native Windows
   and under Wine?
8. Which existing ras-commander managed-host utilities can be reused without
   coupling terrain export to mesh generation?

Record the audit findings in this feature folder before changing production
code. If the audit discovers an existing equivalent API, extend or repair it
instead of adding a duplicate.

## API consistency audit

Before implementation, compare the proposed API with:

- `RasTerrain.create_terrain_hdf()` and `vrt_to_tiff()`
- `RasMap.list_terrain_layers()` and its DataFrame schema
- `RasTerrainMod` setup, profile, volume, and raster methods
- `RasGeometryCompute` managed interop and result objects
- `ras_commander.native.mesh_host` Windows/Wine supervision
- `ComputeResults` dataclass conventions
- public path, logging, error, overwrite, timeout, and `ras_object` conventions

The audit must explicitly decide:

- the final method and parameter names;
- whether the method belongs directly on `RasTerrain`;
- the appropriate typed result and whether a receipt file is optional;
- how terrain selection behaves when multiple layers exist;
- whether native-resolution consolidation uses factor 1;
- how source resolution is selected for multi-resolution terrain;
- which behavior is generic ras-commander policy and which belongs to a
  downstream application;
- whether any direct dependency declaration is missing;
- how existing `compute_modified_terrain_raster()` documentation should be
  clarified without breaking compatibility.

The public change must follow ras-commander's static namespace,
`pathlib.Path`, `@log_call`, lazy optional-import, DataFrame-first inventory,
multi-project `ras_object`, and fail-closed validation patterns.

## Proposed public API

The starting proposal is:

```python
result = RasTerrain.export_rasmapper_terrain(
    ras_project_path,
    output_tif,
    terrain_name=None,
    extent=None,
    downsample_factor=4,
    rasterize_modifications=True,
    resample_method="near",
    overwrite=False,
    timeout_seconds=1800,
    hecras_version=None,
    ras_object=None,
)
```

The independent API audit may rename or reorganize this contract, but it must
preserve the following capabilities:

- select a registered terrain by name;
- consolidate one or more source rasters into one GeoTIFF;
- request a bounded extent;
- derive the output resolution from the authoritative source grid;
- use nearest-neighbor resampling on an exactly aligned grid;
- rasterize vector terrain modifications through RAS Mapper;
- run on native Windows and under Wine;
- supervise and terminate only owned processes;
- return structured output metadata and validation.

## Resolution and grid policy

The normal workflow must accept a source-derived scale factor rather than a
rounded target resolution.

- Factor 1 means native-resolution consolidation.
- Normal downsample products use power-of-two factors such as 2, 4, and 8.
- The exact output cell size is
  `native_cell_size * downsample_factor` in project coordinate units.
- Do not round a source expressed in US survey feet to a nominal metre value.
- Snap the output extent outward to the authoritative source-grid origin.
- Cell-size divisibility without origin alignment is insufficient.
- Record both the requested and snapped extents.

For example, a source cell size of 3.280833 US survey feet produces:

| Factor | Exact requested output size |
|---:|---:|
| 2 | 6.561666 feet |
| 4 | 13.123332 feet |
| 8 | 26.246664 feet |

For a multi-source terrain, inventory every participating raster and fail if a
source lacks a finite, positive level-zero cell size. Source origins and source
resolutions do not otherwise need to be commensurate. Select the finest source
(then native priority and registered order) as the authoritative grid, derive
the exact factor-based output cell size from it, and pass that cell size to
RAS Mapper with **Export to Single Raster** enabled. RAS Mapper, not Python,
owns consolidation and downsampling across its XML-loaded priority/order,
stitches, masks, and modifications.

## Proposed implementation architecture

```text
RasTerrain public method
  -> RasMap.list_terrain_layers() for project-aware terrain selection
  -> request validation and source-grid policy
  -> managed terrain-export host
       -> load exact HEC-RAS managed assemblies
       -> load the selected TerrainLayer
       -> set ResampleMethod = "near"
       -> call GenerateNewRasTerrain(...)
            resampleTo1RFI = true
            resampleVecMods = requested flag
       -> close managed TIFF and terrain resources
       -> write a machine-readable receipt
  -> independently validate the completed GeoTIFF
  -> return TerrainExportResult
```

### Managed host

Prefer a focused out-of-process helper for both Windows and Wine:

- `ras_commander/native/RasMapperTerrainExportHelper.cs`
- `ras_commander/native/terrain_export_host.py`

The helper should reuse the established managed-host concepts used by mesh
generation: exact HEC-RAS installation binding, task-local staging, GDAL
runtime setup, Wine path conversion, bounded execution, owned-process cleanup,
and JSON receipts.

The helper should write to a unique partial output in the destination folder.
The Python wrapper should promote it to the requested filename only after
validation. Existing outputs must not be replaced unless `overwrite=True`.

Do not expose managed callbacks or `ref` parameters in the public Python API.
The helper owns those implementation details.

### Result object

Add a bool-compatible `TerrainExportResult` following `ComputeResults`
conventions. Candidate fields:

- success and error
- output path
- selected terrain name and HDF path
- exact HEC-RAS version
- source-raster inventory
- native cell size
- downsample factor and exact output cell size
- requested and snapped extents
- output width, height, CRS, units, data type, and NoData
- resampling method
- modification-rasterization flag
- single-raster flag
- elapsed time and timeout state
- managed-host messages
- semantic validation checks

Do not add model, executable, input, or output hashes to this feature.

## Validation requirements

An export is successful only if all applicable checks pass:

- the managed helper returns a completed receipt;
- exactly one expected output GeoTIFF exists;
- the file can be reopened after the managed process exits;
- it contains one readable elevation band;
- CRS and units agree with the selected terrain;
- pixel size equals the source-derived target within a declared numerical
  tolerance;
- output origin and extent are aligned to the reference grid;
- output dimensions agree with the snapped extent;
- finite elevations are present;
- NoData coverage is plausible for the requested extent;
- the receipt records the requested resampling and modification flags;
- no owned processes remain after success, failure, or timeout.

Modification qualification must use known features. At minimum, compare a
small export crossing a known modification with `resampleVecMods=False` and
`True`; affected cells must change in the appropriate direction while nearby
control cells remain stable.

## Tests and fixtures

### Unit tests

- terrain-layer selection, including ambiguous and missing names;
- `str`/`Path`, Windows, Wine, UNC, relative, and space-containing paths;
- factor and resolution validation;
- source-grid snapping, including negative coordinates;
- mixed-resolution multi-raster acceptance and unusable-grid rejection;
- output overwrite protection;
- request and receipt schema validation;
- missing, malformed, stale, and incomplete receipts;
- temporary-output cleanup;
- forced timeout proving no owned helper processes survive.

### Real HEC-RAS tests

- a small single-source terrain with modifications;
- a small multi-source stitched terrain;
- a bounded UPGU3 window crossing one or more known `SetIfLower` channel
  modifications;
- UPGU3 2x and 4x products;
- native Windows HEC-RAS 6.6;
- the matching HEC-RAS 6.6 managed helper under Wine;
- audit-only version-surface checks through available 7.0-family fixtures
  without accepting unverified signatures, semantics, or version terms.

Use the project-fixture database to locate additional candidates. Do not run a
full-domain hydraulic computation merely to qualify terrain export.

## Production-code changes expected

The final file list should be determined by the audit, but the likely scope is:

- `ras_commander/terrain/RasTerrain.py`: public orchestration method;
- `ras_commander/native/RasMapperTerrainExportHelper.cs`: native call;
- `ras_commander/native/terrain_export_host.py`: compile, stage, execute, and
  supervise the helper;
- `ras_commander/native/__init__.py`: internal host exports;
- `ras_commander/ComputeResults.py`: typed result;
- `ras_commander/terrain/__init__.py`: public documentation/export adjustments;
- `setup.py`: packaged helper source and any direct optional dependency;
- focused unit, integration, and qualification tests;
- `docs/api/terrain.md` and a concise real-project example.

Keep `RasTerrainMod.compute_modified_terrain_raster()` for compatibility and
small analytical uses. Document that it is not the production fallback for
large consolidated terrain export.

## Explicit non-goals

- Reimplementing HEC-RAS terrain-modification TIN mathematics in Python.
- Adding a web service.
- Driving the RAS Mapper export dialog.
- Using RasControl or the HEC-RAS Controller COM interface.
- Mutating or registering the derived GeoTIFF in the source project.
- Running TauDEM or hydraulic computations.
- Adding downstream domain-reduction or hydrofabric logic.
- Removing the existing row-by-row analytical function.

## Worktree and review requirements

- Start from the latest `main` in a new isolated local worktree and feature
  branch.
- Preserve the current shared checkout and all unrelated dirty changes.
- Follow the CLB Git Runner policy for any working tree under `H:\CLB-Repos`.
- Complete the independent research and API-consistency report before editing
  production code.
- Stage exact files and inspect the cached diff before committing.
- Run focused tests first, then real Windows and Wine qualifications.
- Preserve useful failed experiments in this feature-development folder.
- Frame the upstream pull request as generic RAS Mapper terrain export; do not
  mention a downstream repository in the PR title or description.
- Do not open or merge the pull request until the implementation evidence is
  reviewed.

## Completion gates

- Independent prior-art research is written down.
- API-consistency audit is complete and any departure from this proposal is
  justified.
- Public API and managed helper are implemented.
- Unit tests pass.
- A real modification-aware export passes on Windows.
- A real modification-aware export passes under Wine.
- 2x/4x resolution and grid alignment are demonstrated.
- A multi-source terrain export is demonstrated.
- Forced-timeout cleanup passes.
- Public documentation is updated.
- The implementation is committed and pushed on its isolated branch.
- Upstream PR text is prepared for review but is not opened without explicit
  authorization.
