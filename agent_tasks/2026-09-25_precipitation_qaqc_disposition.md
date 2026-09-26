# PR #376 independent review disposition

Claude Code Fable reviewed `c86e7866f..b2200a6f1` and concurrent work read-only.
Session: `ed557e77-044d-4536-88af-add2cc5023c4`. Full handoff/report are retained
locally in ignored `TASK.md`, `OUTPUT.md`, and `working/claude-fable-qaqc.json`.
The independent SOL API audit also confirmed the transform, beta, and path
issues and checked the notebook call signatures and NOAA AORC semantics.

| Finding | Disposition |
|---|---|
| F1 Wine DSS overclaim | Superseded by new controlled CLB07 success. Combined disabling DLL override caused prior timeout; matrix preserves diagnosis and exact tested scope. |
| F2 beta qualification inheritance | Fixed; all source routes retain historical-beta status, including stable-looking executable directories with matching explicit beta identity. |
| F3 GDAL GeoTransform ordering | Fixed writer and cache validation with `to_gdal()`; independent rasterio reopen checks transform, extent, CRS, values. |
| F4 native NetCDF evidence ambiguity | Fixed by separate `netcdf_hdf_qualification` / `native_hdf` route. Proven library-native-HDF evidence is preserved; vendor GDAL import remains `documented`. |
| F5 stale opt-in assertion and receipt | Assertion fixed. Fresh Windows 6.6 opt-in qualification passed; refreshed notebook execution and compact matrix receipt retained. |
| F6 raw executable path version regex | Fixed shared resolution to inspect executable parent labels, preserve beta identity, and fall back to unsteady header. Ancestor version numbers cannot reject a newer runtime. |
| F7 6.3 shim evidence label | Fixed: Windows-qualified status is separate from the available WMIC compatibility fallback. |
| F8 interval-ending timestamps | Added to both raster setter docstrings and guide; explicit depth-unit semantics clarified. |
| F9 unknown-version `inconclusive` | Documented existing vocabulary rather than expanding the public enum; receipt version plus warnings distinguish unknown version from blocked runtime qualification. |
| F10 shared API contracts | Updated library and precipitation AGENTS.md with the new APIs and route distinction. |
| F11 late interpolation validation | Fixed before raster I/O/cache creation; regression verifies no source read or mutation for invalid interpolation. |
| F12 optional dependencies/harness/GRIB metadata | Optional rasterio/h5py test imports now skip cleanly. Public RasExamples pipeline is exercised by opt-in tests. Broader matrix-harness deterministic coverage and automatic GRIB timestamp/span inference remain follow-ups: the public adapter intentionally requires caller-selected bands, interval-ending times, and accumulation semantics; product-level qualification must verify these against source metadata. |
| F13 DSS write ordering | HDF update now precedes text publication; failure regression confirms a locked HDF leaves text unchanged. Full cross-file transactional rollback is outside this focused fix. |

Additional corrections from source/visual review: AORC first-hour preservation,
notebook 727 depth-unit override, 729/924 interval-depth plot labels, obsolete
722 raw edits, and nonexistent methods in the old AORC guide.

Validation includes a fresh Windows 6.6 notebook 729 execution with source,
temporary-HDF, and final rainfall/hydraulic figures; opt-in GeoTIFF model
qualification; AORC clone/authoring HDF regression; focused pytest; all changed
notebook code compilation; metadata validation; and MkDocs build. The final
focused suite passed 179 tests (1 opt-in skip), and three sequential repo-env
GeoTIFF runtime qualifications passed (37.58, 44.62, and 40.65 seconds). A first
global Python 3.14 opt-in run observed missing tmp HDF after a readiness signal;
the repo Python 3.12 runs did not reproduce it. The cause is unproven and the
artifact-loss observation remains open. No speculative preprocessing change
was made; the failed diagnostic log remains in `working/`.

Remaining product/version qualifications are tracked in the detailed support
plan. This disposition is not a claim that all live NOAA notebooks or all
native formats have been executed across every 5.x–7.x release.
