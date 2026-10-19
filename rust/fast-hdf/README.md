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

## Internal contract (API_VERSION = 3)

The Python module is `ras_commander_fast_hdf`. Applications normally use the
ras-commander adapter rather than importing these internal primitives.

```python
read_numeric(path, dataset_path, selection=None, threads=None, parallel=True)
read_numeric_batch(path, dataset_paths, threads=None, parallel=True)
assemble_cells(face_points, face_endpoints, face_perimeter_info,
               face_perimeter_values, cell_face_info, cell_face_values,
               threads=None, *, strict=True, return_diagnostics=False)
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

* hdf5-reader/core are vendored inside the pinned ras-commander-rust engine,
  based on upstream `gpt-cmdr/netcdf-rust` at
  `24ff6fcfcc79a35c30aa5d8cb3028ab4d9d00564`, MIT OR Apache-2.0.
  Engine PROVENANCE/LOCAL_PATCHES records its reviewed local patches. The bridge
  has no direct generic-reader dependency or private source copy.
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


## Hardened bridge bindings

Cargo.toml is the sole engine pin source; Cargo.lock freezes resolution and build.rs
exports ENGINE_COMMIT/ENGINE_FEATURES from the dependency declaration. API_VERSION is 3;
TEXT_API_VERSION remains 1. capabilities() returns the engine pin, feature list and
implemented binding names. File arguments accept str or os.PathLike via PathBuf.

```python
numeric_capability(path, dataset_path)
temporal_reduce(path, dataset_path, offset=None, threshold=None,
                max_block_bytes=16 << 20, threads=None, parallel=True)
raw_crs_evidence(path)
typed_group_attributes(path, group="/")
mesh_inventory(path)
cross_sections(path, max_bytes=67108864)
plan_result_mode(path)
steady_profile_names(path)
read_cross_section_result(path, kind, variable, rows, sections,
                          max_bytes=67108864, threads=None, parallel=True)
plan_capabilities(path)
```

rows/sections are (start, exclusive_stop, positive_step). kind is steady/unsteady;
variable is Water Surface/Flow. Read results are owned NumPy arrays preserving dtype.
All other new reports use plain dict/list/bytes values. Attribute types and capability
status/code/reason are explicit; raw bytes remain available for unsupported/corrupt
attributes. Floating metadata preserves Python float NaN/infinity (not coerced to null).
CRS statuses are raw lexical evidence: unvalidated never implies EPSG/authority.
Hydraulic-unit evidence is separate. Cross-section identities and bank/name field
availability retain engine semantics. Plan capabilities never certify solver success.

mesh_inventory delegates the accepted bounded initial_2d_inventory. It reports
physical/stored/ghost counts and per-variable capability, but only the qualified
Unsteady Base Output layout. It does not claim deferred output-block/steady inventory
or the future mesh-name cross-check. Names-only layouts fail closed.

| Engine error | Native Python exception |
|---|---|
| NotFound (object) | KeyError |
| FileNotFound | FileNotFoundError, filename and errno=2 |
| Io | OSError |
| Unsupported | UnsupportedError(ValueError) |
| InvalidRequest | ValueError |
| Corrupt | CorruptDataError(ValueError) |
| StructuralTopology / InvalidGeometry | TopologyError(ValueError), mesh_structure_error True / False |
| Internal / future kind | RuntimeError |

These Python exception types are exported by the extension. Central mapping attaches
engine_kind, subject and source_path; reader and mesh use the same mapper. Existing
public fast_* adapter failure policy and FastHdfError wrapping are preserved. Batch
read_numeric_batch returns a dict: repeated identical paths collapse to one key (the
last returned value wins), not separate array entries.

Python temporal fallback now supplies all timing/read-plan keys, with NaN for unavailable
setup/splits and a timing_scope explaining the combined measurement. Native setup is
measured; both engines expose engine_seconds. These NaNs are Python float values, not
strict JSON. Serialize with an explicit missing-value policy. parallel is forwarded to
native session and reduction; the Python fallback is serial. log_call logs function
names only and never formats array arguments/results (covered by regression).

Wave3 resolves the duplicate capability-query remainder through the accepted engine
chunk_shape field; see the API3 section. Authoritative MSVC full-feature/real qualification
remains Main's gate. No engine source is changed by this bridge packet.

### Repin follow-up compatibility notes

Minimum supported Rust is 1.88 (fixed-array as_chunks). Build metadata parses Cargo.toml
as TOML, accepting inline or table-form engine dependencies and producing an explicit
bridge-build error for invalid/missing rev or features. API_VERSION has one Rust constant.
Engine exception str(exc) now includes the engine kind prefix (`Kind: message`); callers
should catch exception types rather than parse strings. Internal errors use RuntimeError.
Annotation failure preserves the original exception rather than replacing its category.

Fallback read_plan.chunk_cache_bytes is the h5py/HDF5 configured raw-data chunk cache
capacity from the file access property list; native reports the engine file cache's maximum
capacity. These are distinct backend configurations, not measured bytes read or process
RSS. Equality of this key is not a backend-parity promise. Block plan/count/value and
peak/count arrays are tested for parity. log_call regression requires both DEBUG records
to be captured and uses an argument whose repr raises, so disabled logging cannot pass it.

Fixture PROVENANCE.json uses engine-relative paths for engine-owned attribute fixtures;
the two 1D files are supplemental synthetic evidence regenerated by the committed
fixtures/generate_1d.py (hash recorded), not engine-owned real model outputs.


## Wave 3 engine repin (API 3)

Pin: Cargo.toml only, exported by build.rs; ENGINE_FEATURES remains catalog/hdf/mesh/results.
TEXT_API_VERSION remains 1. Full-feature ABI now has 31 explicitly listed entrypoints.
All existing function signatures, array dtypes, result keys and exception classes remain;
reports gain the new fields below. The public fast_* facade requires native API3 or uses
its existing auto fallback policy. Python fallback computation/metadata is unchanged.

```python
unsteady_time_axis(path, max_bytes=16777216)
unsteady_row_times(path, rows, max_bytes=16777216)
result_units(path)
dataset_unit_evidence(path, dataset)
mesh_name_diagnostics(path)
```

Time dictionaries retain raw_strings, raw_ms_strings, raw_ms, days, ms_since_epoch,
timestamps (ISO-like .mmm strings with no zone), hour_2400_rows and capability. Axis
reports group, rows, epoch=civil_unix_1970 and ms_source; selection reports original
row_indices and selected hour2400 indices (not renumbered). timezone is None, never UTC.
Epoch is a civil 1970 origin, not a UTC instant. Integer-ms sources retain a separate
integer_ms Unsupported capability: no epoch is invented from raw integers. If valid
stamp strings independently prove civil timestamps, overall capability is Supported
while integer_ms still reports its limitation. Days-only axes remain unsupported for
civil conversion. Missing/malformed axes follow the central typed exception mapper.
Selection validates the full axis under max_bytes, then applies (start,stop,step).

Unit dictionaries include status (declared/absent/unsupported/corrupt), text, raw_bytes,
capability, source_attribute and quantity_name. result_units returns variables (family,
area, variable, dataset, units) and unit_system evidence (source group, kind, value).
Known quantity labels and exact source text come from the engine; the bridge does not
normalize units, infer CRS, resolve unit-system conflicts or convert numeric values.

mesh_inventory delegates canonical engine inventory, retaining legacy results and adding
output_blocks with mode/block_name/dataset_root/results. mesh_name_diagnostics returns
mesh_name + typed issue strings missing_group/extra_group/duplicate_attribute_name/invalid_name.
Inventory disagreement raises CorruptDataError, never a partial successful inventory.
Steady absence versus unsupported layouts and block corruption follow engine capabilities.

Temporal reduction now uses output.chunk_shape and output.values rows/maximum length;
the duplicate numeric_capability query is removed. chunk_shape None covers layouts with
no chunk dimensions; it does not promise support for every compact/virtual layout.

Main captures a fresh full-feature runtime inventory and receipt. Prior API2/26-entry
inventories are historical and must fail the current exact ABI gate. Requalify installed
full-feature wheels with all consumer, bridge and unchanged audit-compat suites; GNU
local import is supplementary. No wheel publication is implied.
