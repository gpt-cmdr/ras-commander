# Optional native HDF and mesh kernels

`ras-commander-fast-hdf` is a separate optional Python extension. The main
ras-commander package remains installable without a Rust compiler. This source
does not imply that public wheels have been released.

## Build

Use a Rust toolchain with an installed platform linker and Python 3.10 or later:

```text
uv tool run --from maturin maturin build --release --locked --manifest-path rust/fast-hdf/Cargo.toml
uv pip install --python <your-python> <resulting-wheel>
cargo test --locked --manifest-path rust/fast-hdf/Cargo.toml
```

On a shared checkout, set `CARGO_TARGET_DIR` to a local cache directory rather
than placing build outputs on SMB. Windows needs Visual Studio C++ BuildTools.
`PYO3_PYTHON` can select the interpreter explicitly. The wheel uses the CPython
3.10 stable ABI; cross-platform wheel compatibility must be tested on each
platform. `extension-module` is enabled by maturin, while plain `cargo test`
links Python normally.

## Internal contract (API_VERSION = 1)

The Python module is `ras_commander_fast_hdf`. Applications normally use the
ras-commander adapter rather than importing these internal primitives.

```python
read_numeric(path, dataset_path, selection=None, threads=None, parallel=True)
read_numeric_batch(path, dataset_paths, threads=None, parallel=True)
assemble_cells(face_points, face_endpoints, face_perimeter_info,
               face_perimeter_values, cell_face_info, cell_face_values,
               threads=None)
write_pmtiles(layers, output, min_zoom, max_zoom, threads=None)
```

Numeric reads return NumPy arrays with their native numeric dtype and original
rank. Supported types are signed/unsigned 8/16/32/64-bit integers and 32/64-bit
floats in native byte order. Other datatypes and nonnative byte order raise
`UnsupportedError`; use h5py for those. Selection is a list of nonnegative
`(start, stop, step)` triples, one per axis, with positive steps and exclusive
stops. Bounds must already be normalized. Integer axis squeezing and arbitrary
advanced indexing belong to the Python adapter. Batch reads reuse one file
context and return a dictionary keyed by dataset path. Arrays own their memory
after return; they do not depend on an open HDF handle.

Mesh inputs are two-dimensional NumPy arrays: coordinates are float64 and
indices/offsets are int64. Coordinates have two columns. Face endpoints and
perimeter info have at least two columns; cell face info has at least two;
cell face values have at least one (face ID). The kernel accepts strided arrays
and copies inputs before releasing the GIL, protecting against concurrent
mutation of borrowed Python memory. Output is `(coordinates, offsets, cell_ids)`:
float64 coordinates of shape `(N, 2)`, int64 offsets of length `C+1`, and int64
original cell IDs of length `C`. Each offset interval contains one closed ring.

Assembly follows face endpoint connectivity, reversing complete face chains
when necessary. Every intermediate perimeter coordinate is retained. Zero-face
cells and one-open-face boundary ghost cells are omitted without renumbering.
Disconnected, branching, self-loop, or
unclosed topology raises `TopologyError`; the Python compatibility path can
polygonize such cases. This kernel handles simple single-ring cell boundaries,
not arbitrary polygonization or automatic geometry repair.

`write_pmtiles` takes a list of dictionaries with keys:

* `name`: unique nonempty layer name.
* `coordinates`: float64 `(N, 2)` WGS84 longitude/latitude coordinates.
* `offsets`: int64 ring offsets, length `C+1`.
* `cell_ids`: int64 nonnegative IDs unique within the layer.
* `properties`: dictionary of column names to Python lists of length `C`.

Property values are strings, signed 64-bit integers, floats, booleans, or None.
Nonfinite property floats become null; out-of-range integers raise. Coordinates
must be finite and within Web Mercator latitude limits. pyproj transforms the
packed coordinate arrays outside this kernel; no GeoJSON, WKB, or GeoDataFrame
serialization is required for the native tile path.

The exporter writes MVT PMTiles, zooms 0–22, with dropping, clustering,
coalescing, and presimplification disabled. Clipping and MVT quantization still
apply. The pinned freestiler encoder replaces a collapsed exterior with a
one-pixel square at its centroid, preserving visibility rather than exact
subpixel geometry. PMTiles are a visualization product; packed source polygons
remain the analytical geometry. Source features remain
in memory; upstream freestiler spools encoded tile chunks to temporary storage.
The Python adapter supplies a staged output path and atomically publishes it
after success. The underlying PMTiles writer also stages archive assembly
before replacing its destination.

The native tile orchestrator uses freestiler's assignment, clipping, MVT,
compression, and PMTiles writer kernels, inserting an integer-grid topology
repair before compression. Actual BaldEagle exports exposed rounding-induced
backtracking spikes and self-intersections despite valid source polygons.
Simple single-ring features bypass overlay; pathological or multipart rings
are reconstructed with `i_overlay` using nonzero winding. Splits remain parts
of the same feature with unchanged IDs and property tags. Repair operates on
the final tile grid, avoiding a second projection or quantization. Processing
uses batches of 32 tiles and spools compressed output. Eight decoded real
failures, with source mesh/cell/tile metadata, are retained as compact Rust
regression fixtures under `tests/quantized_regressions.json`.

## Threads and errors

Expensive HDF reads, topology assembly, and tiling release the GIL. Thread pools
are reused by effective thread count; at most eight configurations are cached.
The default is the smaller of eight and the available CPU count. Explicit
`threads` values must be 1–1024. Outer parallel workflows should set a smaller
count to avoid oversubscription. Serial numeric reads use `parallel=False`.

`UnsupportedError` identifies capability gaps, `TopologyError` identifies mesh
construction failures, missing datasets use KeyError, I/O failures use OSError,
and invalid arguments/data use ValueError. Automatic fallback should never
catch every exception indiscriminately or hide corrupt inputs.

## Dependency provenance

* hdf5-reader: `gpt-cmdr/netcdf-rust`, revision
  `24ff6fcfcc79a35c30aa5d8cb3028ab4d9d00564`, MIT OR Apache-2.0.
* freestiler-core: `walkerke/freestiler`, revision
  `beb64b0d4414da895ec67d02b2f91db6ab6acc37`, MIT AND ISC. Its crate is
  unpublished; Cargo resolves the pinned Git source.
* PyO3/rust-numpy provide the binding. ndarray allocations transfer to NumPy on
  numeric return. Owned input copies are intentional and are not zero-copy.
* flate2 enables zlib-rs. Cargo feature unification also enables upstream
  rust_backend; flate2 selects the explicitly requested zlib-rs backend.
* `i_overlay` 1.9.4 and `i_float` 1.6.0 (already in freestiler's dependency tree)
  supply integer-grid repair; their license notices are included. `prost` uses
  the same 0.13 version as freestiler, preserving MVT field representations.

Cargo.lock records exact transitive dependencies. Retain upstream license
notices when distributing wheels. Consult the repository implementation plan
and validation report for tested datasets, measured timings, and limitations;
prior research timings are not measurements of this extension.
