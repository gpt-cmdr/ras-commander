# Qualification evidence

The initial Windows release wheel passed 1,142 exact numeric dataset comparisons
across nine real HDF files and polygon comparisons covering 141,070 cells in six
geometry files. Comparisons checked dtype, shape, bytes, original cell IDs,
topology, CRS, bounds, area, and retained perimeter coordinates.

All 304 decoded PMTiles passed geometry validity, source association, properties,
coverage, and source identity at every tested zoom. Cases include BaldEagle g01
(87,039 cells, zooms 10–15) and the two-mesh g11 geometry (4,425 cells, zooms 6–12).
Integer-grid repair corrected 64 invalid features found in the original export.
The integrated suite passed 57 tests with five explicit fixture skips; an
additional unsupported-LZF-filter regression passed. The fixture gaps include
small plans without computed 2D results and an absent Depth dataset.

The qualified wheel SHA256 was
`ad28b85fa1b739b9896f40cb01b31d9c3e68b804c5914f74a911cbe0e3dae63e`.
This identifies the measured prototype, before the final source-ring validity
guard and current-API integration. Later checks must identify their wheel
separately. It is not a cross-platform qualification or the earlier research
suite of 16,889 datasets.

## Measured prototype performance

Three fresh-process samples per case, alternating backend order, warm filesystem
cache without a cache flush; Windows, four logical CPUs, Python 3.13.13,
NumPy 2.3.3, h5py 3.14.0, Shapely 2.1.2 and GeoPandas 1.1.1. Input files were
local. Whole-plan reads retained all numeric arrays on both backends. Peak
process-tree RSS was sampled every 20 ms and includes interpreter overhead;
short-lived allocation peaks can be missed.

The computed BaldEagle p07 plan contains 383 numeric datasets, about 1.09 GB
decoded, in a 482,604,388-byte HDF file. Polygon measurements use the g03
geometry with 24,718 cells. These are measurements of the shared legacy
integration prototype, not timings of the later lazy-view/diagnostic adapter.

| Operation | Python median (s) | Rust, 1 thread (s) | Rust, 4 threads (s) |
|---|---:|---:|---:|
| Whole-plan numeric arrays | 3.676 | 2.740 | 1.009 |
| Largest dataset | 1.554 | 0.947 | 0.291 |
| Every fourth row and column | 3.979 | 1.272 | 0.507 |
| Polygon GeoDataFrame | 1.548 | 0.066 | 0.050 |

Whole-plan peak RSS increased from 1,276 MiB to 1,467 MiB at four Rust threads.
The selected-read case decreased from 720 MiB to 340 MiB. Faster extraction
therefore does not imply uniformly lower memory usage.

End-to-end PMTiles samples also completed, but a later matched-thread matrix
was not completed. No PMTiles speed multiplier is claimed here. Both routes
disable configured feature dropping and simplification; the native route also
repairs quantized rings.

Reproduce with `scripts/benchmark_fast_hdf.py`; exact local source paths,
fixture hashes, all samples, and sampled memory are retained in the task's
`working/rust_hdf/validation/local_final.json` evidence. No solver was run.

## Delivery and broader integration

The delivery branch is based on PR #548 and preserves the current lazy result
view, selection, bounded batching, ghost-cell, and polygon diagnostic contracts.
The final current-API suites passed 112 tests with one fixture skip, including
all six real polygon cases, a multilayer PMTiles export, and rejection of
self-crossing and zero-area rings. A separate test proved that selected and
bounded result-view reads invoke the native binding. The final wheel SHA256 is
`358f0835b080cbbfa89144b25538c225f4a19911a092923d52ce7cc9c7441ca6`.

Fourteen final Rust unit tests pass. A separate three-sample final-wheel polygon
comparison produced medians of 2.196 s for Python and 0.093 s for four-thread
Rust (about 24×). The Python samples ranged from 1.552 to 3.865 s and Rust from
0.089 to 0.106 s; this variability limits precision. These timings include the
current diagnostic contract and final source-ring validity checks. The local
evidence file is `working/current-polygons.json` in the delivery checkout.

Remaining qualification includes cross-platform wheel CI, the full terrio
fixture matrix, and actual browser/wasm instantiation. The stricter terrio
comparison currently passes 23 of 31 layers across three fixtures. Its remaining
field, CRS, Z, depth-source, and reference-reader differences are explicit
failures. This evidence does not establish full terrio/RustGIS completion or
hydraulic engineering validity.
