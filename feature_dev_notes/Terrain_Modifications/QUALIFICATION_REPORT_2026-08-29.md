# Native RAS Mapper terrain export qualification report

Date: 2026-08-29
Branch: `codex/native-rasmapper-terrain-export`
Base revision: `d7784fcc7714ca75632eef5338612fece28609aa`

## Outcome

The focused native helper and Python supervisor passed unit/regression tests,
bounded native HEC-RAS 6.4.1, 6.5, 6.6, and 7.0.1 exports, audit-only checks of the
installed 6.7 Beta 4/5 and 7.0.0 runtimes, and Wine exports for every supported
release. HEC-RAS 6.6 passed on both the alternate CLB09 worker and the dedicated
CLB07 CT212 worker; 6.4.1, 6.5, and 7.0.1 subsequently passed an independent
three-export-per-release matrix on CT212. An exact copy
of the notebook-316 modified project also produced identical native-Windows
and CLB07 Wine arrays, validity masks, metadata, source inventory, and receipt
semantics with a maximum valid-cell difference of 0.0 feet. All production-path
outputs were one single-band Float32 GeoTIFF with CRS and nodata metadata, exact
source-anchored grid dimensions, at least one valid value, no sidecars, and a
JSON receipt. No project registration or source project file was changed.

## Automated tests

- `tests/terrain_export_host_test.py`: 82 passed after the mixed-resolution and
  cross-platform runtime-label corrections. Coverage includes exact
  terrain selection, Path/string/Windows/UNC/space-containing and Wine path
  conversion, factors and cell-size math, negative-coordinate grid snapping,
  mixed non-integer source-resolution acceptance, unusable-grid rejection,
  overwrite protection, request/response
  schemas, GeoTIFF semantic validation, failure partial cleanup, task-local Wine
  state, packaged resources, forced-timeout owned-process cleanup, supported
  version normalization, early unsupported-version `RasPrj` rejection,
  executable-release checks, and explicit/project runtime conflict rejection.
- Focused regression set: 134 passed after the forward-open 7.1 update
  (terrain export, existing native helper packaging, GDAL runtime, terrain
  logging/creation, and terrain display settings). This includes explicit
  rejection of unqualified or new version terms.
- Opt-in real-runtime suite
  `tests/qualification/terrain_export_qualification_test.py`: 9 passed and the
  three Wine-only cases skipped on Windows. The Windows cases cover the original
  mixed-resolution Bald Eagle `Terrain50` and modification-aware and stitched
  exports on 6.4.1, 6.5, 6.6, and 7.0.1. The permanent Linux cases cover Muncie,
  the mixed-resolution terrain, and optional exact Windows-reference off/on
  parity when all reference paths are configured.

The full repository suite completed with `2,393 passed`, `62 skipped`, and
eight failures in 4 minutes 19 seconds. The failures did not touch feature
files or feature paths: five were existing in-process CLR order conflicts after
a 7.0 mapper load attempted 6.6 land-classification calls, one was a PROJ
database/environment mismatch in a benefit-area concurrency test, one was an
existing numeric sediment-plan expectation, and one was an already-executed
tutorial notebook baseline. Collection also printed pre-existing Windows GUI
extension entry-point faults (`0xc0000139`) and continued. The focused feature
and adjacent regression sets were rerun independently and remained green.

Five notebook revisions cover the public workflow: modification-aware Bald
Eagle evidence (`316`), benefit-area terrain preparation guidance (`612`), the
creation-versus-export distinction (`920`), analytical-sampler scope (`930`),
and a focused bounded stitched-terrain tutorial (`931`). The new native-export
cells remain opt-in in source, but the committed examples now include executed
review evidence. Notebook 316's safe native section was freshly executed while
its hydraulic cells were not rerun; notebooks 920, 930, and 931 were freshly
executed end to end with their heavy or hydraulic paths disabled. Their
committed outputs include terrain/source tables and review figures. Notebook
612 retains its coherent prior outputs, eight embedded images, and four final
maps without rerunning its four hydraulic simulations. JSON and Python-AST
checks cover all five notebooks (70 code cells), and the output audit found no
stored exceptions.

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

### Bald Eagle mixed-resolution terrain

Project: `BaldEagleCrkMulti2D`, original registered terrain `Terrain50`

The registered inventory contains a 36.504512049933-foot source followed by a
20-foot source. Those level-zero resolutions have a non-integer ratio, which
is valid input to RAS Mapper's **Export to Single Raster** operation. Python
selects the finer 20-foot source as the authoritative output-grid anchor;
factor 2 produces an exact 40-foot `resampleCellSize`. The managed receipt
confirms `resampleTo1RFI=true` and `ResampleMethod="near"`, and both registered
sources intersect the bounded output.

A clean HEC-RAS 6.6 qualification of the original registration produced one
61 x 61 TIFF in 2.42 seconds. A separate isolated project copy wrote a
high-ground modification directly to the original `Terrain50` HDF--no
replacement terrain was created or registered--then exported the same window
with modifications off and on. The final reproducibility run completed in
1.611 and 1.726 seconds. Across 3,721 valid
cells, 264 cells rose by 0.15625 to 9.625 feet and 1,769 geometric control
cells remained exactly unchanged (maximum absolute control delta 0.0). The
off/on checksums were 49168 and 48517. This closes the premature preflight
rejection that had required source resolutions to be integer multiples.

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
what distinguishes the accepted patch from known-defective 7.0.0. The operator
directed that the dedicated triangular-nose/minimum-Y regression fixture be
skipped, so this matrix does not claim that defect-specific geometry.

The official downloads page and HEC release repository contain no HEC-RAS
Classic 7.1 release. No 7.1 package could therefore be installed or qualified;
the exact 7.1 release term is nevertheless forward-open so the future official
installation can run behind the helper's exact runtime contract check.

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
4. The first Bald Eagle evidence harness used an exact decimal assertion for
   the coarse source's reported cell size and stopped after both native exports
   had succeeded because the managed inventory reports 36.504512049933 rather
   than the rounded 36.504512 fixture label. The production test now uses an
   explicit floating tolerance; the native outputs and receipts were retained
   and independently validated.
5. A repeat harness directory whose fully qualified helper response path
   exceeded the legacy .NET 260-character limit failed cleanly before export.
   Repeating from the shorter task-local `working/mr50b` path passed. Extreme
   Windows path length therefore remains a runtime limitation; ordinary
   `Path`/string, UNC, Wine, and space-containing cases retain their existing
   coverage.

The production host now stages the required `bin32` libraries beside the helper
and clones a configured Wine prefix into per-call state by default. It never
issues a global `wineserver` termination; timeouts target only the owned POSIX
process group. An already task-owned prefix may be reused only through the
explicit environment declaration documented in the public API guide.

### Independent CLB07 CT212 run

The dedicated CLB07 worker was subsequently available for an independent run
using CT212, Ubuntu 24.04, Wine 11.0, and HEC-RAS 6.6. The strict runtime
preflight passed before any export. A bounded two-source Muncie 2x export
produced the expected 16 x 23 grid at 10-foot cells in 58.18 seconds. The
original mixed-resolution Bald Eagle `Terrain50` consolidated its registered
36.504512049933-foot and 20-foot sources into one 61 x 61 GeoTIFF at the
explicit 40-foot cell size in 58.09 seconds.

An isolated CLB07 project copy with a task-written high-ground modification
also passed modification-disabled and modification-enabled exports in 58.30
and 58.29 seconds. Of 3,721 valid cells, 311 rose by 0.28125 to 18.15625 feet;
all 1,769 geometric control cells were unchanged. This first independent run
used a different crest profile than notebook 316, so its intrinsic semantic
checks passed but it was not used as a Windows parity gate.

A second CLB07 run then staged the exact existing notebook-316 modified Bald
Eagle project and HDF used for the fresh native-Windows reference. The Windows
off/on exports took 1.748 and 1.994 seconds; the Wine pair took 117.483 seconds.
For both modification conditions, the Float32 arrays and validity masks were
exactly equal between Windows and Wine, with maximum valid-cell absolute
difference 0.0 feet. Transform, bounds, CRS, nodata, shape, semantic validation
fields, source order and inventory after path-prefix normalization, and receipt
semantics also matched. The affected-cell and unaffected-control masks were
identical: 264 cells rose by 0.15625 to 9.625 feet while all 1,769 control cells
remained exactly unchanged. This closes the exact-input Windows/Wine parity gap
for the qualified HEC-RAS 6.6 bounded mixed-resolution workflow.

Both CLB07 runs supervised only task-owned processes. After validation, no
owned Wine/helper/`gdalinfo` process, stage directory, or partial output
remained. CT212 was gracefully stopped, verified stopped, and retained
`onboot=0`; CT100 and CT213 remained healthy. Task-owned ephemeral runtime
copies were removed after evidence capture. Logical scratch usage was restored,
but no manual host-wide trim or discard was run; physical thin-pool reclamation
is deferred to the scheduled guest trim, and no further infrastructure action
was taken.

The first CLB07 host-test pass also exposed one diagnostic-only portability
defect: a Windows-style `ras_exe_path` was rejected correctly on Linux but its
runtime label was empty. The branch now parses Windows and UNC executable paths
with Windows path semantics and includes a focused cross-platform regression;
the rejection message reports the expected runtime release.

### Independent CLB07 6.4.1, 6.5, and 7.0.1 matrix

CT212 was reused for a separate Ubuntu 24.04, Wine 11.0 qualification of the
three remaining supported releases. Exact installed runtime payloads, a known-
good .NET Framework 4.8 Wine prefix, and source projects were copied into
task-local state. Each runtime independently passed the helper's exact private
nine-parameter reflection check, including the final by-reference
`TiffMetadata<float>` parameter, and produced three successful receipts:

| Runtime | Muncie stitched 2x | `Terrain50` modifications off | `Terrain50` modifications on | Total |
|---|---:|---:|---:|---:|
| 6.4.1 | 58.208 s | 58.300 s | 58.389 s | 174.993 s |
| 6.5 | 58.240 s | 58.385 s | 58.477 s | 175.124 s |
| 7.0.1 | 58.266 s | 58.415 s | 58.492 s | 175.196 s |

All nine receipts confirmed nearest-neighbor resampling, one output RFI,
`resampleTo1RFI=True`, the requested modification flag, and semantic GeoTIFF
validation. For every runtime, Muncie consolidated both registered sources to
one 16 x 23 Float32 raster at 10-foot cells. `Terrain50` consolidated its
registered 36.504512049933-foot and 20-foot sources to one 61 x 61 Float32
raster at 40-foot cells. Enabling modifications raised 264 of 3,721 valid cells
by 0.15625 to 9.625 feet; all 1,769 geometric control cells remained exactly
unchanged. The Muncie, modifications-off, and modifications-on arrays and
validity masks were pixel-identical across 6.4.1, 6.5, and 7.0.1, with a maximum
valid-cell absolute difference of 0.0 feet.

Recursive comparison found no source-project mutation or derivative
registration. No partial, stage directory, helper, GDAL, Wine, or `wineserver`
process survived. CT212 was stopped with `onboot=0`, the admission lock was
released, and the neighboring guests remained stopped and unchanged. The
first 6.4.1 Muncie export itself succeeded, but an independent harness
diagnostic initially expected `.NET` primitive spelling `System.Double`
instead of the reflected signature's `Double`; that useful failed experiment
was preserved before the corrected complete rerun.

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

- Exactly HEC-RAS 6.4.1, 6.5, 6.6, and 7.0.1 are accepted. All four passed the
  native Windows modification-aware and stitched matrix and real Wine export.
- HEC-RAS 6.3/6.3.1 lack the required contract, 6.4.0 is associated with an
  official terrain-elevation defect, 6.7 has only prerelease builds, and 7.0.0
  has an official terrain-modification export defect. HEC-RAS Classic 7.1 is
  forward-open but remains unqualified until an official binary is published.
  See `HECRAS_VERSION_COMPATIBILITY_2026-08-29.md` for the full matrix.
- The operator explicitly directed that the dedicated triangular-nose/minimum-Y
  regression fixture be skipped. The broader 7.0.1 modification evidence and
  HEC's official fix notice support acceptance, but no defect-specific fixture
  result is claimed.
- Full-domain UPGU3 export was intentionally not attempted. Bounded windows
  satisfy feature semantics without multi-gigabyte derivative cost.
- The output is a derivative GeoTIFF only. Terrain HDF construction,
  registration, UI actions, hydraulic simulation, and modification-math
  reimplementation remain out of scope.
- The final production-equivalent non-strict `mkdocs build` passed in 39.43
  seconds. Strict mode completed content processing and then aborted on 33
  existing git-history and missing-notebook-link warnings; no terrain page,
  feature note, navigation, or API-collection error occurred.
