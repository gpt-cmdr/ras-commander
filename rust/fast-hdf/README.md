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

## Internal contract (API_VERSION = 5)

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

The exporter writes MVT PMTiles, zooms 0â€“22, with dropping, clustering,
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
`threads` values must be 1â€“1024. Outer parallel workflows should set a smaller
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
exports ENGINE_COMMIT/ENGINE_FEATURES from the dependency declaration. API_VERSION is 5;
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


## Time/units bindings (introduced in Wave 3; current API 5)

Pin: Cargo.toml only, exported by build.rs; ENGINE_FEATURES remains catalog/hdf/mesh/results.
TEXT_API_VERSION remains 1. Full-feature ABI now has 33 explicitly listed entrypoints.
All existing function signatures, array dtypes, result keys and exception classes remain;
reports gain the new fields below. The public fast_* facade requires native API5 or uses
its existing auto fallback policy. Python fallback computation/metadata is unchanged.

```python
unsteady_time_axis(path, max_bytes=67108864)
unsteady_row_times(path, rows, max_bytes=67108864)
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

## Structure bridge contract (introduced in W5; current API_VERSION = 5)
The single Cargo dependency pin is engine 3895026ba9b0e25d2a80f41d0d67286021ad73e4.
TEXT_API_VERSION remains 1. Full-feature ABI explicitly lists 33 entrypoints.
Existing public call signatures and exception classes remain unchanged; the Python
adapter requires API 4. Historical API 3 migration notes above remain applicable.

structure_inventory(path, family, max_bytes=67108864)
read_structure_series(path, family, structure, relative, rows, columns,
                      max_bytes=67108864, threads=None, parallel=True)

Family keys: sa2d_area_connection, lateral_structure, storage_area. Rows/columns
are (start, stop, stride). structure=None selects only storage-area family series.
Inventory returns source group, time_rows, identities, Node Pointer evidence,
series shape/kind/capability, exact label bytes and units, static dataset paths,
and label diagnostics. Successful inventory status certifies the engine's layout
validation; it does not certify every column-label table. Per-series columns and
inventory diagnostics retain unsupported/corrupt label evidence. No identity,
unit or absent series is invented. Reads retain F32/F64 dtype/shape/bit values,
engine path validation, explicit byte budgets and standard error mapping.

plan_capabilities adds structures (per-family capability/datasets/diagnostics),
and maps boundary_conditions/calibration_regions explicitly alongside reference
lines/points. These statuses certify stored evidence, never solver success.
Frozen structure fixtures and generators are copied byte-for-byte from the pinned
engine's tests/fixtures/structures; its manifest is the hash oracle. No real
fixture is copied into this checkout. Main owns MSVC/real-file qualification.


API audit follow-up: all existing max_bytes parameters default to 64 MiB (the
meaning remains the engine-specific raw table/metadata or selected output budget;
it is not a whole-session allocation limit). Structure reads use threads=None
and the shared bounded reader thread validation. Existing inventory/metadata
signatures without thread/budget controls await engine-supported limits.
capabilities()["bindings"] is the sorted actual registration set, including the
NativeAnalysis class and excluding exception classes, so optional feature builds
report only what was registered. The explicit 33-entry full-feature contract
remains an independent test oracle.

Column labels expose source_attribute (source remains an alias). Dataset results
expose dataset_path alongside existing dataset/path keys. Structure kind preserves
f32/f64 wire names via explicit mappings, while dtype uses the common NumPy dtype
spelling. engine_kind preserves existing CamelCase wire names via explicit
mapping until engine-owned stable strings arrive; no Debug-derived public names.

New structure diagnostics and mesh-name diagnostics share subject/message/
capability fields. None means evidence was not supplied by the engine; no status
is inferred from diagnostic prose. Existing path/mesh_name/issue fields remain.
Legacy assemble_cells diagnostics remain tuples for compatibility. Engine status,
identity and diagnostic enum unification is deferred to ENGINE-API-HARDEN-5; this
bridge does not create replacement engine vocabularies. Structure entrypoints are
internal native APIs; existing public fast_* signatures are unchanged. Sessions
and pools remain per call; no optimization or shared session is introduced.


## H5 repin — native ABI 5 / engine API 5
Pin: 7894a3b98583c64170fc6bb4bef007ebc4a79d7a (Cargo.toml single source).
TEXT_API_VERSION=1; explicit full-feature registration set remains 33 entrypoints.
capabilities() adds engine_api_version, engine_capabilities (the engine's compiled
features and owner/name/feature entrypoints), and default_max_bytes. bindings is
still generated from actual module registrations, independently checked by EXPECTED.

All capability dictionaries have exactly status/code/reason, using engine as_str().
Evidence dictionaries contain kind/value/raw_bytes/capability; XS fields, units,
column labels and node pointers use Reported<T> accessors. Kind describes evidence,
not a competing availability status. Unit-system evidence has unit_system_kind.
CRS kind retains lexical labels (e.g. unvalidated); capability Supported means
lexically readable text ONLY, never a validated semantic CRS. exact_wkt is retained
verbatim, including when a lexical capability refuses it. Raw bytes may be None
where the engine supplies none. Old internal native status/text/labels evidence
keys are replaced under ABI5; corresponding public fast_* signatures are unchanged.

XS, mesh and structure identities carry source/table/row plus existing domain
names. Compatibility index/source/path aliases remain where already exposed.
Enum strings use engine methods, including engine_kind on errors (now snake_case)
and engine_code (optional unsupported code). Python exception classes are unchanged.
Canonical structure family output is sa_2d_area_connection; the former
sa2d_area_connection input remains an explicit compatibility alias.

mesh_inventory, mesh_name_diagnostics, plan_capabilities, steady_profile_names and
result_units accept optional max_bytes=67108864. Existing positional calls remain
valid. read_cross_section_result appends keyword-only metadata_max_bytes=67108864;
max_bytes still bounds selected returned bytes. Defaults are compile-time checked
against engine DEFAULT_MAX_BYTES. Metadata budgets bound each raw stored object,
not aggregate memory; the engine's profile/packed-name 8 MiB exception remains.
The unit binding delegates dataset_units, preserving its historical Python name.

Native diagnostics use subject/message/capability plus context fields. Cell
omissions add cell_id/kind; return_diagnostics=True now returns dictionaries under
ABI5. The adapter preserves public polygon diagnostic records and exception types.
The ignored attribution test shares this conversion to remain semantically exact.
Engine string-only diagnostics carry an explicit unavailable capability with a
reason that typed capability evidence was not supplied; prose is never classified.

Full-feature MSVC/runtime-capture and real fixture qualification remain Main-owned.
Historical W3/W5 sections above describe introductions; this section supersedes
any earlier wire-shape/default examples. No engine source, optimization, routing,
public wrapper signatures or publication is changed by this re-pin.

## FIM bridge additions (API_VERSION = 6)

Engine pin: 131910a59f72d2884dc22ba150589bfbce490ff1. TEXT_API_VERSION
remains 1. The full registration contract now lists 45 entrypoints.
`src/fim.rs` adds mesh summary/series/BC inventories and reads, extrema with
first stored indices, geometry arrays and packed families, exact identity
comparison, layer inventory, and typed run-summary attributes. Numeric buffers
move into NumPy with their stored dtype; no float widening occurs. Every bounded
entrypoint defaults its byte budgets to engine DEFAULT_MAX_BYTES (67108864).
Selections retain element order and duplicates. Capability and Identity dictionaries
use the API5 shapes. Geometry compound tables include exact raw bytes and typed
column metadata; Python scalar lists are decoded views, not float-bit oracles.

`fast_hdf.read_dataset` dispatches bounded Base Output summary/series/BC reads
to typed readers under the existing backend policy. Explicit thread controls and
reads larger than the typed budget retain the generic native reader. Metadata,
geometry construction, ghost filtering, timestamps and public exceptions remain
in the existing Python adapters. h5py remains the automatic unsupported fallback.
HEC-RAS 7.0 `Cell Hydraulic Depth` is passed through exactly; no `Depth` alias is
introduced. The existing xarray name normalizer only lowercases and replaces
punctuation/spaces (producing `cell_hydraulic_depth`).

## Wave 2 / Wave 8 typed bindings (API_VERSION = 9)

Bridge API 9 added these with engine pin 527bdf3 (engine API 7). Bridge API 10 re-pins to
e9afad3d3271adfc5ea7ac05546cc50312c4bb5e (ras-commander-rust main, engine API 8); see "Wave 3 typed bindings" below.
TEXT_API_VERSION remains 1. Full-feature registration set at API 9: 67 entrypoints.

Wave 8 additions (src/fim.rs): `mesh_geometry` (field descriptors), `mesh_geometry_tables`
(exact Attributes compound + Cell Info), `geometry_family_capability`, `mesh_boundary_links`.
Wave 2 additions (src/one_d.rs): `xs_geometry_inventory`, `read_xs_geometry`,
`one_d_line_family`, `river_reaches`, `river_junctions`, `xs_interpolation_surfaces`,
`xs_result_inventory`, `read_xs_result`, `unsteady_row_window`, `one_d_summary_inventory`,
`read_one_d_summary`, `structure_geometry`, `one_d_geometry_group`, `pump_stations`,
`one_d_structure_inventory`, `one_d_structure_capabilities` (with the engine
`OneDStructureKind::qualified` flag), `read_one_d_structure_series`.

Conventions are unchanged: path-first module functions, `max_bytes`/`metadata_max_bytes`
default to DEFAULT_MAX_BYTES (64 MiB), capability dicts `{status, code, reason}`, Identity
`{source, table, row}`, enum strings from engine `as_str()`, `Reported<T>` as
`{capability, value}`, compounds as `{shape, raw_bytes, columns}` with exact stored bytes,
numeric arrays in their stored NumPy dtype, and the existing typed exception mapping
(engine_kind/engine_code annotations). Python routing lives in
`ras_commander/_fast_hdf_typed.py` (`fast_hdf.read_typed`).

## Wave 3 typed bindings (API_VERSION = 10)

Engine pin e9afad3d3271adfc5ea7ac05546cc50312c4bb5e (ras-commander-rust main; Wave 3, 3B,
3C and 3D merged with Wave 2 and PERF-3; engine API 8). Full-feature registration set:
75 entrypoints. New module `src/wave3.rs`:

| Binding | Engine API | Returns |
|---|---|---|
| `read_families()` | `READ_FAMILIES` | family names (`pipe_geometry`, `pipe_results`, `reference_line_results`, `reference_point_results`, `breach`, `plan_metadata`, `land_cover`, `infiltration`, `sediment`, `encroachments`, `terrain`, `event_conditions`, `steady_output`, ...) |
| `read_family_inventory(path, family, metadata_max_bytes)` | `read_family_inventory` | `{family, capability, datasets, groups}`; each dataset has path, identity, shape, kind/dtype, storage, capability, typed attributes, role, domain, time_group, identity_table, locations, names, geometry_locations, `stored_location_ids` (stored-dtype array or None), time_of_extreme_row |
| `read_family_dataset(path, family, dataset, slices=None, metadata_max_bytes, max_bytes)` | `read_family_dataset` | stored values (below) |
| `output_block_inventory(path, max_bytes)` | `output_block_inventory` | non-Base blocks with stored descriptors |
| `read_output_block(path, block, relative, slices=None, max_bytes)` | `read_output_block` | stored values |
| `reference_point_geometry(path, max_bytes)` | `reference_point_geometry` | `Reported`: Attributes compound, Points array, features (identity, name, area, stored i32 cell_index, point_row) |
| `classification_catalogue(path, family, max_bytes)` | `classification_catalogue` | `Reported`: layout, entries (pixel_id as stored int, name, variable_rows, capability), unmatched_variables |
| `stored_family_index(path, metadata_max_bytes)` | all family inventories + output blocks | compact routing index: `{datasets: [{owner, path, storage, shape, dtype, status, code}], failures, output_blocks}` |

Stored values are `{"storage": "numeric", "values": ndarray}` (stored dtype),
`{"storage": "compound", "values": {shape, raw_bytes, columns}}`,
`{"storage": "bitfield_bytes", "shape", "raw_bytes"}` (exact bytes; h5py reads these
1-byte bitfields as `uint8`) or `{"storage": "strings", "shape", "values"}` (engine-decoded
text, trailing NULs removed). Slices are `(start, stop, step)` per dimension and apply to
numeric storage only. Family-level errors in `stored_family_index` are reported in
`failures`, never dropped; since bridge API 11 the Python router also surfaces them in
required-mode refusals and in the trace.

## Engine API 9 bindings (API_VERSION = 11)

Engine pin 435ddb4b35c30507127a2656dae5d85b214553ea (ras-commander-rust engine/route2-gaps-20261021,
engine API 9). Full-feature registration set: 77 entrypoints.

| Binding | Engine API | Returns |
|---|---|---|
| `typed_dataset_attributes(path, dataset, max_bytes)` | `typed_dataset_attributes` | `{capability, value}`; value is a list of typed attributes (as `typed_group_attributes`) for any dataset, inside or outside the read families. Absent dataset: Unavailable; group path: `invalid_request` |
| `raw_fixed_strings(path, dataset, max_bytes)` | `raw_fixed_strings` | `{capability, value: {shape, dataspace, width, padding, charset, raw_bytes}}`: stored bytes with padding kept (h5py's bytes follow after the NULLPAD conversion) |

Every typed attribute carries `dataspace` (`scalar`, `simple` or `null`; `null` is h5py
`Empty`) and bitfields are `attribute_type = {kind: "bitfield", bytes, byte_order}` with
the exact stored bytes as `value`. Compound tables and stored family datasets carry
`dataspace`. Mesh series descriptors and catalogue mesh-result layers carry
`domain_rule` (`stored_location`, `legacy_exact_name`, `labelled_summary`,
`boundary_columns`, `unqualified`).

`fast_hdf.read_typed` uses `stored_family_index` as the membership oracle for datasets
outside the Wave 8/Wave 2 routes: supported numeric, compound and bitfield datasets are
read typed; listed-but-unqualified datasets (for example Davis pipe summaries with no
stored `Location`) keep their exact literal values through the generic reader; strings
stay on h5py (the documented metadata exception), because decoded text cannot prove
h5py's fixed-length bytes. Compound members stored NULLTERM or SPACEPAD are converted the
way HDF5 converts them into h5py's NULLPAD memory type (cut at the first NUL / strip
trailing spaces, zero-fill), from the engine's member padding evidence.
