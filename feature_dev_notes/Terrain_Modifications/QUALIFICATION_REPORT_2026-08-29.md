# Native RAS Mapper terrain export qualification report

Date: 2026-08-29
Branch: `codex/native-rasmapper-terrain-export`
Base revision: `d7784fcc7714ca75632eef5338612fece28609aa`

## Outcome

The focused native helper and Python supervisor passed unit/regression tests,
bounded native HEC-RAS 6.4.1, 6.5, 6.6, and 7.0.1 exports, audit-only checks of the
installed 6.7 Beta 4/5 and 7.0.0 runtimes, and a Wine export using the HEC-RAS
6.6 mapper runtime. All production-path outputs
were one single-band Float32 GeoTIFF with CRS and nodata metadata, exact source-
anchored grid dimensions, at least one valid value, no sidecars, and a JSON
receipt. No project registration or source project file was changed.

## Automated tests

- `tests/terrain_export_host_test.py`: 72 passed. Coverage includes exact
  terrain selection, Path/string/Windows/UNC/space-containing and Wine path
  conversion, factors and cell-size math, negative-coordinate grid snapping,
  source resolution compatibility, overwrite protection, request/response
  schemas, GeoTIFF semantic validation, failure partial cleanup, task-local Wine
  state, packaged resources, forced-timeout owned-process cleanup, supported
  version normalization, early unsupported-version `RasPrj` rejection,
  executable-release checks, and explicit/project runtime conflict rejection.
- Focused regression set: 128 passed after the 7.0.1 qualification update
  (terrain export, existing native helper packaging, GDAL runtime, terrain
  logging/creation, and terrain display settings). This includes explicit
  rejection of unqualified or new version terms.
- Opt-in real-runtime suite
  `tests/qualification/terrain_export_qualification_test.py`: 8 passed and the
  Wine-only case skipped on Windows. The eight cases cover modification-aware
  and stitched exports on 6.4.1, 6.5, 6.6, and 7.0.1. The equivalent production Wine
  invocation was run with the 6.6 runtime on the controlled Linux worker
  described below.

The full repository suite completed with `2,393 passed`, `62 skipped`, and
eight failures in 4 minutes 19 seconds. The failures did not touch feature
files or feature paths: five were existing in-process CLR order conflicts after
a 7.0 mapper load attempted 6.6 land-classification calls, one was a PROJ
database/environment mismatch in a benefit-area concurrency test, one was an
existing numeric sediment-plan expectation, and one was an already-executed
tutorial notebook baseline. Collection also printed pre-existing Windows GUI
extension entry-point faults (`0xc0000139`) and continued. The focused feature
and adjacent regression sets were rerun independently and remained green.

## Native Windows HEC-RAS 6.6

### UPGU3 modification window

Project: `UPGU3`, registered terrain `Terrain`
Requested bounds: `(1996495.92929205, 13858745.25719928,
1996712.46429205, 13859060.217199279)`

| Export | Cell size (ft) | Grid | Time | Semantic result |
|---|---:|---:|---:|---|
| 2x, modifications off | 6.561666666666625 | 33 x 48 | 2.7 s | pass |
| 2x, modifications on | 6.561666666666625 | 33 x 48 | 2.7 s | pass |
| 4x, modifications on | 13.12333333333325 | 17 x 24 | 2.8 s | pass |

At 2x, all 1,584 cells were valid. Enabling native vector modifications changed
73 cells across the known channel and left 1,511 control cells unchanged. Every
changed value was lower: delta range `-27.0625` to `-0.09375` feet, mean
absolute delta `12.703767` feet. A top-left 8 x 8 unaffected control block was
pixel-identical. This demonstrates that `resampleVecMods` changes the intended
feature without introducing broad raster drift.

The exact 33 x 48 result also closes the scratch-probe extra-row issue: the
production host calculated integer dimensions and used the bounded inward far
edge solely for the vendor `Ceiling` call, while preserving the requested
source-grid origin and validated final bounds.

### Muncie stitched terrain

Project: `Muncie`, registered terrain `TerrainWithChannel`
Requested bounds: `(404147.258781418, 1801881.85296284,
404307.258781418, 1802111.85296284)`

The HEC-RAS 6.6 production export completed in 1.7 seconds at 10-foot (2x)
resolution with a 16 x 23 grid. The native XML-loaded inventory contained both
registered sources; both intersected the output, one source deterministically
anchored the authoritative grid, and the registered stitch behavior completed
without requiring aligned source origins.

## HEC-RAS 7.0-family compatibility evidence

The same packaged helper, compiled against the verified 6.6 signature, loaded
the checked 7.0.0 mapper assemblies and exported the bounded Muncie window
in 1.6 seconds. Its pixels, affine transform, CRS, dimensions, nodata, and GDAL
band checksum were identical to the 6.6 output. The helper accepts no
free-form resampling vocabulary: it asserts the exact private method contract
and hard-codes `near`, so new vendor terms cannot be accepted silently. This
successful window is not support evidence: HEC's official 7.0 known-issues
record says terrain export can omit the minimum-Y part of a modification.
Consequently 7.0.0 is rejected. The exact official 7.0.1 installer was later
downloaded and its Authenticode signature validated as U.S. Army Corps of
Engineers. The installed `Ras.exe` reports 7.00.0001; exact reflection found
the same private nine-parameter contract and completion behavior.

The production-path 7.0.1 UPGU3 2x modification-off/on and 4x-on exports
completed in 2.67, 3.87, and 3.67 seconds. They produced the expected 33 x 48
and 17 x 24 grids, 73 changed cells, 1,511 unchanged controls, and a delta
range of `-27.0625` to `-0.09375` feet. The two-source Muncie export completed
in 1.49 seconds with the expected 16 x 23 grid and checksum 4221. These checked
pixels are identical to 7.0.0 and 6.6, but HEC's explicit 7.0.1 fix notice is
what distinguishes the accepted patch from known-defective 7.0.0. The local
fixtures do not contain the exact triangular-nose/minimum-Y regression.

The official downloads page and HEC release repository contain no HEC-RAS
Classic 7.1 release. No 7.1 package could therefore be installed or qualified;
HEC-RAS 2025 was not substituted because it is a different product.

## HEC-RAS 6.3 and 6.3.1 compatibility decision

Both locally installed 6.3-family mapper assemblies were reflected and
decompiled. Neither contains the private nine-parameter
`GenerateNewRasTerrain` method used by the supported production path, and neither
contains `ExportRasterOptions`. Their public
`ExportResampleToSingleFile(string, double, TiffMetadata<float>,
ProgressReporter)` method uses `TerrainLayer.Extent` directly and cannot accept
a bounded extent. Their separate clip implementation copies source tile
subsets and carries modification definitions into a new terrain HDF; it does
not emit one bounded GeoTIFF with modifications baked into the cells.

Consequently, 6.3 and 6.3.1 are explicitly unsupported. A supplied
`RasPrj.ras_version` is validated before output directories are created, and
the public API raises an actionable `ValueError` rather than falling through
to helper reflection or the analytical row sampler. See
`HECRAS_63_COMPATIBILITY_2026-08-29.md` for the checked surface and rationale.
The public guard was also exercised with a real `RasPrj` initialized for the
Muncie fixture and HEC-RAS 6.3. It raised before creating the deliberately
absent destination directory.

## Wine HEC-RAS 6.6

The dedicated CLB07 HEC-RAS 6.6 worker did not accept SSH connections during
qualification. A controlled alternate Linux worker (CLB09) was therefore used
with:

- Wine 10.0;
- Wine Mono 10.0 installed in a prefix owned by this qualification task;
- the HEC-RAS 6.6 mapper assemblies, 32-bit HDF native libraries, and bundled
  GDAL runtime staged into that task-local prefix;
- the production packaged helper and supervisor, with
  `RAS_COMMANDER_TERRAIN_WINE_PREFIX_IS_TASK_LOCAL=1` declaring the already
  isolated prefix.

The bounded Muncie 2x production export completed successfully in 17.2 seconds.
It returned the expected two-source inventory, 16 x 23 grid, Float32/nodata/CRS
semantics, no sidecars, and GDAL band checksum `4221`. Copying the resulting
GeoTIFF back to the Windows qualification host confirmed pixel-identical data,
an identical affine transform, an identical CRS, and identical dimensions to
the native Windows HEC-RAS 6.6 production result.

Earlier useful failures were retained as findings rather than hidden:

1. The first Wine probe failed because Wine Mono was absent.
2. The next failed because `hdf5.dll` was not present beside the x86 helper.
3. Installing Mono into the task prefix and staging the HEC-RAS 6.6 `bin32`
   HDF libraries resolved those runtime prerequisites.

The production host now stages the required `bin32` libraries beside the helper
and clones a configured Wine prefix into per-call state by default. It never
issues a global `wineserver` termination; timeouts target only the owned POSIX
process group. An already task-owned prefix may be reused only through the
explicit environment declaration documented in the public API guide.

## Artifact and receipt checks

- Native `resampleTo1RFI=true` produced exactly one TIFF in all bounded runs.
- Semantic validation checked GTiff driver, exact size, affine transform,
  source-derived cell, CRS, one Float32 band, finite nodata, valid-value range,
  file size, and absence of `.aux.xml`, `.ovr`, `.tfw`, and `.prj` sidecars.
- Requests, helper responses, public results, logs, and receipts contain no
  model, input, output, installer, dependency, or executable hashes.
- Success promoted a unique same-directory partial TIFF and prepared receipt.
  Failure/timeout tests removed owned partials and unique staging directories.

## Qualification gaps and limitations

- CLB07 availability remains an infrastructure gap. The alternate-worker Wine
  result qualifies the exact HEC-RAS 6.6 mapper runtime under Wine, but does not
  prove the unavailable CLB07 image configuration.
- Exactly HEC-RAS 6.4.1, 6.5, 6.6, and 7.0.1 are accepted. All four passed the
  native Windows modification-aware and stitched matrix. Wine qualification
  covers 6.6; matching 6.4.1, 6.5, and 7.0.1 Wine runs remain a qualification gap.
- HEC-RAS 6.3/6.3.1 lack the required contract, 6.4.0 is associated with an
  official terrain-elevation defect, 6.7 has only prerelease builds, and 7.0.0
  has an official terrain-modification export defect. There is no published
  HEC-RAS Classic 7.1 release.
  See `HECRAS_VERSION_COMPATIBILITY_2026-08-29.md` for the full matrix.
- Full-domain UPGU3 export was intentionally not attempted. Bounded windows
  satisfy feature semantics without multi-gigabyte derivative cost.
- The output is a derivative GeoTIFF only. Terrain HDF construction,
  registration, UI actions, hydraulic simulation, and modification-math
  reimplementation remain out of scope.
- `mkdocs build --strict` reached the repository's pre-existing
  `docs/api/core.md` collection failure for
  `ras_commander.inspect_project_assets`; direct Python imports confirmed that
  symbol exists. The edited terrain page introduced no reported Markdown or
  navigation error before that unrelated abort.
