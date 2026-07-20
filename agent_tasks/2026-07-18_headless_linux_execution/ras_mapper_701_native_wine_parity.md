# HEC-RAS 7.0.1 RAS Mapper native-Windows/Wine parity snapshot

Date: 2026-07-19

## Decision

Three bounded RAS Mapper slices now pass exact content parity between native
Windows HEC-RAS 7.0.1 and the same Windows installation under pinned Wine:

1. initial mesh generation, regeneration, refinement-region mutation, and
   breakline mutation;
2. projection selection plus ordered multi-source terrain creation, pyramid
   construction, and geometry association; and
3. result-layer creation plus WSE, depth, and velocity GeoTIFF export.

This is **not** a full Windows-under-Wine qualification. The 2D hydraulic
property-table builder still does not return reliably under Wine, a fresh
HEC-RAS 7.0.1 computation golden has not yet been compared, and several
required workflow/recovery actions remain open.

[ras-commander PR #287](https://github.com/gpt-cmdr/ras-commander/pull/287)
removed the first-run TCU dialog from the technical critical path by adding
read-only acceptance detection and an explicit opt-in transfer from an already
accepted donor state. The parity results below remain independent technical
evidence; TCU state does not qualify any Mapper operation.

HEC documents 7.0.1 as a primarily bug-fix release that runs on 64-bit Windows.
Wine therefore remains an independently qualified compatibility path, not a
vendor-supported Linux build:

- [HEC-RAS 7.0.1 release notes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest)
- [HEC-RAS 2D mesh guidance](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/development-of-a-2d-or-combined-1d-2d-model/development-of-the-2d-computational-mesh)

## Qualification controls

The native and Wine runs used the same HEC-RAS 7.0.1 component identities. Each
Wine task used a fresh isolated prefix and a task-local project clone. Source
fixtures and the prepared prefix template were fingerprinted before and after
each run and remained unchanged. Terrain creation was restricted to one logical
CPU because the multicore Wine path has produced nondeterministic CLR access
violations and non-returning calls.

The tests accepted content, not process exit codes. Receipts reopen the produced
RAS Mapper/HDF artifacts and inspect topology, feature inventories, boundary
assignments, raster georeferencing, masks, and values. No configured action was
skipped. The slice receipts nevertheless have `runner_passed=false` because the
production profile deliberately marks every other required but unconfigured
operation as failed. They must not be presented as a zero-skip full-suite pass.

## Function and action status under Wine

| Qualification action | ras-commander surface exercised | Status | Content gate |
|---|---|---|---|
| `mesh.generate_initial` | `GeomMesh.generate()` and the isolated managed Mapper host | Passed exact native/Wine parity | 4,362 cells, 9,500 faces, ordered topology, quality, three boundary assignments, fresh reopen |
| `mesh.regenerate` | `GeomMesh.generate()` regeneration path | Passed exact native/Wine parity | 4,362 cells, 9,500 faces and the same initial topology fingerprint |
| `mesh.refinement_region` | refinement feature write, reload, and regeneration | Passed exact native/Wine parity | 4,426 cells, 9,661 faces, feature attributes/polygon and complete topology |
| `mesh.breakline` | breakline feature write, reload, and regeneration | Passed exact native/Wine parity | 4,431 cells, 9,656 faces, feature attributes/line and complete topology |
| `projection.select` | `projection_select()` | Passed exact native/Wine parity | exact PRJ SHA-256 and normalized EPSG:2965 |
| `terrain.import` | `RasTerrain.create_terrain_hdf()` via `terrain_import()` | Passed exact native/Wine parity on one CPU | ordered two-raster priority, produced raster content, TIN/stitch content, semantic HDF fingerprint |
| `terrain.build_pyramids` | `terrain_build_pyramids()` | Passed exact native/Wine parity | exact per-layer pyramid-level inventory |
| `terrain.associate` | managed Mapper geometry-to-terrain association | Passed exact native/Wine parity | exact geometry reference, units flag, unchanged mesh topology |
| `mapper.result_layers` | `mapper_result_layers()` / RAS Mapper layer creation | Passed exact native/Wine parity on the result fixture | reopened WSE, depth, and velocity XML definitions match requested plan/profile/terrain |
| `mapper.export_geotiff` | `mapper_export_geotiff()` / map storage helper | Passed exact native/Wine parity on the result fixture | readable georeferenced GTiffs for every requested type |
| raster comparison | `RasQualification.compare_rasters()` | Passed exact mode for all three maps | same grid/CRS/dtype/mask, zero value difference, overlap 1.0 |
| isolated project staging | `RasQualification.stage_project()` | Passed regression and live Wine rerun | writable private clone; immutable source mode and content unchanged |

## Mesh sequence parity

The Bald Eagle sequence is cumulative: the refinement region is added after
regeneration, then the breakline is added to the refined geometry. The older
4,367-cell / 9,495-face number belongs to a separate isolated breakline control
and is not the final value for this qualified sequence.

| Step | Cells | Faces | Topology fingerprint |
|---|---:|---:|---|
| Initial generation | 4,362 | 9,500 | `35fbcd5c2bb69adc5e53ab7662b2b0d0d8e2a0f241b3f15491dbf3c494d6d916` |
| Regeneration | 4,362 | 9,500 | `35fbcd5c2bb69adc5e53ab7662b2b0d0d8e2a0f241b3f15491dbf3c494d6d916` |
| Refinement region | 4,426 | 9,661 | `4a6c8d73160c57775d91c1ce165f3fe75aae04cb909f2f4babf49a314153ed82` |
| Breakline after refinement | 4,431 | 9,656 | `a9dba9ab0a147c07ede5820ee51427b7883c59f717c7795f0d2d84832611467d` |

For every step, native Windows and Wine match the exact ordered nonvirtual cell
centers, ordered face/index payload, mesh-quality metrics, and all three
boundary assignments. The receipts also require all topology cross-reference,
CSR-contiguity, bounds, finite-coordinate, normal-vector, perimeter, capacity,
and fresh-reopen checks to pass.

Wine exposed two persistence defects during qualification. First, the product's
`RASD2FlowArea.Save()` path could fail to return. The bounded fallback retains
RasMapperLib-generated seed centers, writes the product-derived feature-table
cell count, calls the public mesh save/reload surface, transactionally replaces
the private geometry copy, and accepts it only after a fresh reopen passes the
full topology contract. Second, RAS Mapper could ignore a valid HDF update when
the text and HDF timestamps were not coherent. The persistence path now advances
the HDF modification time by exactly 1,000,000 ns and fails closed if that
relationship is not observed. The retained v52 failure proves the stale-time
case; v53 proves the corrected native/Wine sequence.

## Projection and multi-source terrain parity

The Muncie fixture project fingerprint is
`242d2f4a3a00a583260076578775a5ab5b921367888319888aaf83da4228e945`.
The selected PRJ SHA-256 is
`37e32315f2b7f484e53e91fc5cfe163b832f68e00586aac46f06472ce352f6d8`
and normalizes to EPSG:2965. Inputs are ordered channel-only first and base DEM
second, with output priorities 0 and 1 respectively.

| Terrain content | Exact native/Wine value |
|---|---|
| Channel-only pyramid levels | 0, 1, 2, 3 |
| Base-raster pyramid levels | 0, 1, 2, 3, 4, 5 |
| Stitch TIN points | 16,754 rows; `beb247e7da5e8ecb62041364c17398bc2bdf6170815d24a7cde6d3cffd4929ec` |
| Stitch TIN triangles | 16,556 rows; `94d106dbd3b71b07f99300175014450fe262987e16307ba2692223ef7e480670` |
| Stitches | 41,308 rows; `d2d620d850ae9df984bd66dc65515acbee50319efb5e6214815937f0ecd08d1b` |
| Semantic terrain HDF | `da7e4e8d47491fbe184be4cd4142074bd49923a58b57bb6765a37c849e9bba8f` |
| Produced terrain data | `368ae3c17a7702caa5212ffcdf06621b9dbf5648b2471920bdf990f87101e0ca` |

The associated g02 geometry remains exactly 5,391 cells / 11,164 faces with
topology fingerprint
`cc19416ce04521f57e9e17541d4b9508d046ed73b2213a47d4489a0a9fb652b0`.
Native v54 established the golden, native v55 repeated it, and Wine v56 matched
it. Whole-file HDF SHA-256 values are not equal because the product writes
dynamic timestamp/GUID metadata; canonical HDF datasets and produced raster
data are equal and are the acceptance contract.

## Result-layer and GeoTIFF export parity

The export fixture is a minimized Bald Eagle plan-07 project with fingerprint
`7cc070ecbd7126b5ee6411b9e09be796233efc6d6f66a6a6597b7e1112d31b07`.
It contains an existing legacy pre-7.0 example result. This slice proves that
HEC-RAS 7.0.1 RAS Mapper under Wine can reopen that result, create the requested
layers, and export the same rasters as native Windows. It does **not** prove
fresh 7.0.1 compute parity.

All three Max-profile rasters are 6,705 by 4,852, single-band float32, and have
1,345,691 valid cells. `compare_rasters()` was run with exact-grid production
mode, `max_abs=0`, `rmse=0`, and minimum valid-mask overlap 1.0. WSE, depth, and
velocity each returned `comparison_mode="exact"`, semantic CRS equality, exact
transform/dtype/mask, overlap 1.0, maximum absolute difference 0, and RMSE 0.
The content fingerprints are:

| Map | Data fingerprint |
|---|---|
| WSE | `9bbeb52f45160451d76d628bf4a408661602a3994726f774ddfd8068658ef465` |
| Depth | `6a90fb589ae5eab0c78c97a3966d46cbb69eb2065fe0b523c2aea1cb04ce137d` |
| Velocity | `0b6fbf0f3a9c0dfbfff48374fb09db6715b7b4018d828484d99193fe23a1ba5c` |

Raw TIFF hashes differ because equivalent CRS/metadata serialization differs;
raw-byte identity is not claimed. The pixel, mask, grid, dtype, and semantic CRS
contract is exact.

The first Wine export attempt (v58) failed before HEC-RAS because an immutable
fixture's read-only mode was copied into the task-local clone. `stage_project()`
now adds owner write permission only to the isolated clone, verifies every
copied entry, and rechecks that source permissions and content did not change.
The regression test and live v59 rerun both pass.

## Qualification-framework hardening and regression

The work supporting these real-product tests adds or strengthens:

- transactional mesh persistence with timestamp coherence and a fail-closed
  fresh-reopen topology contract;
- exact projection SHA/EPSG expectations;
- keyed per-type raster receipts for WSE, depth, and velocity;
- fail-closed missing/unreadable/non-georeferenced/empty export handling;
- all-band, exact-first raster comparison with explicit per-type tolerances;
- read-only-source to writable-private-clone staging; and
- direct `RasProcess.exe` argument-vector launch with timeout/nonzero-exit
  propagation for terrain creation.

The consolidated focused regression result is:

```text
252 passed, 5 skipped, 1 warning in 37.06 seconds
```

The warning is the expected Rasterio `NotGeoreferencedWarning` in a synthetic
rewrite test. The five local skips are platform/private integration gates; they
are not evidence of the required production zero-skip acceptance run.

## Evidence index

Only archive basenames and hashes belong in repository documentation. The
archives themselves remain in the controlled private evidence store.

| Evidence archive | SHA-256 |
|---|---|
| `native-701-bald-eagle-mesh-sequence-v53-evidence.tar.gz` | `CD5DD924F0F3641A8DC4EF1CE25B67C4FE181407A2E3FDA76F3EEE90E27E1F17` |
| `rasq-v53-bald-eagle-mesh-sequence-parity-evidence.tar.gz` | `F8DC24FF0C9DBB1824A5821F6B85AE975CB3DDC16A4424598388A1ED2746BD1F` |
| `native-701-muncie-terrain-multi-v54-v55-evidence.tar.gz` | `ECDE25A06AC55BA323883E085F4C9C6FF9B35347DCA18083789545873E66A5BA` |
| `rasq-v56-muncie-terrain-multi-native-parity-evidence.tar.gz` | `3A93DD433A1F8962F7695FB90DF4348EE3D49612221F1C365588224BDE95AD98` |
| `native-701-bald-eagle-plan07-export-v57-evidence.tar.gz` | `9B861B3397362938C83C8DC81517438C2EB2C99E03B5F8F0C0256C4875340901` |
| `rasq-v59-bald-eagle-plan07-export-native-parity-evidence.tar.gz` | `696E1E778E052F8D607DF6D2907A6E748682C05948466FC348C85A84691A65D4` |
| `rasq-v52-bald-eagle-sequence-stale-timestamp-evidence.tar.gz` (retained failure) | `9A0C6FA7C312624BE5A9AFE9ED241B9160D7FA7844D30DA707519EBF423B0393` |
| `rasq-v58-bald-eagle-export-readonly-stage-failure-evidence.tar.gz` (retained failure) | `34D88D492C2D11F991A85AABF7CD7366F9CAE01AC0A7B4D3023AB243BAB22476` |

## Remaining gates and operating policy

The following remain open:

1. `properties.geometry_tables`: real `CompleteGeometryCommand` and direct
   `ComputePropertyTablesCommand` calls have timed out or failed to return on
   both Bald Eagle and Muncie. This is the principal unsupported-preparation
   blocker.
2. Full end-to-end 2D-area creation/perimeter editing and boundary-conflict
   repair are not yet native/Wine qualified.
3. A fresh 7.0.1 plan preprocessing/computation golden, engineering result
   tolerances, and native-Linux engine comparison are not complete.
4. Restart/recovery and failed-run diagnostic parity remain open.
5. No complete production manifest has passed every required operation with
   zero critical skips; Spring Creek promotion therefore remains blocked.

Use HEC's officially compiled native Linux executables exclusively for stages
they support, including native flow computation and classic 1D geometry/HTAB
preprocessing. Use Wine only for preparation gaps that have no official native
path, and only within the exact slice boundaries established above.
