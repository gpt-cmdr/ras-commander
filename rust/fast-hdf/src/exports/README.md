# Typed source exports

`ras-export` is a reusable library inside the optional native backend. It reads
no HDF files, runs no model and performs no coordinate transformation. Its public
entry point accepts a schema and an iterator of `Result<RecordBatch>`. Python can
use the separate integrator proposal `fast_hdf.export_arrow` to stream an Arrow
table/reader to temporary IPC and call the native extension. There is no required
production executable. The test harness is only a qualification transport.

## Contract v1

Every schema requires `mesh_name: Utf8` and `cell_id: Int64`, both nonnullable.
The stable identity is their ordered pair, never local cell ID alone. Region,
cross-section and structure producers supply their own layer/mesh namespace and
stable local identifier. Negative local IDs reject. Uniqueness within a batch
is enforced. **Global uniqueness across batches is a caller precondition**;
writers retain duplicates across batch boundaries instead of maintaining an
unbounded in-memory identity registry. No global PMTiles integer ID is invented.

`geometry: Binary` contains nullable XY OGC WKB with extension `geoarrow.wkb`.
Geometry metadata must declare `crs_type: projjson` and the resolved PROJJSON.
Point, LineString, Polygon, MultiPoint, MultiLineString and MultiPolygon support
both byte orders. Polygons preserve holes and multipart membership. Z/M, EWKB,
embedded SRIDs, geometry collections, empty points (NaN coordinates), malformed
counts, truncated/trailing WKB, short/unclosed rings and nonfinite coordinates
reject. Empty lines/polygons/multi geometries and null geometry are supported
except indexed FlatGeobuf, which rejects them explicitly. There is no topology
repair: producers are responsible for full valid polygon topology.

Attributes are nullable Int64, UInt64, Float64, Boolean, Utf8, Binary and timezone
free Timestamp(Millisecond). Time means UTC Unix milliseconds; dates outside a
container's supported calendar reject there. Timezone normalization is a producer
operation. NaN/infinity reject; supply Arrow null explicitly. Nested/dictionary
arrays, narrower numeric widths and LargeUtf8/LargeBinary reject. Convert them
explicitly before export. Case-insensitive duplicate, empty/NUL and reserved
`fid`/`_ras_fid` field names reject. Arrow schemas must remain exactly equal,
including metadata, and each input batch must satisfy `max_batch_rows`.

Schema metadata `ras:export:v1` is JSON with WKT, PROJJSON, units, `axis_order:xy`,
`resolved:true`, and `geographic_wgs84`. Semantic CRS resolution/conflict checks
belong to the producer (pyproj in the Python adapter). Rust checks evidence is
present and consistent with the GeoArrow metadata; it does not parse or compare
WKT using a second CRS engine. A `resolved` flag is a producer assertion, not
independent evidence that a CRS was detected correctly. WKT without an EPSG
match is supported. Buffer coordinate order is always x/y, regardless of
authority axis ordering. Metres, US survey feet and international feet remain
native in binary outputs. No unit-based coordinate conversion is guessed.

## Format profile

| Writer | Geometry and CRS | Attribute conversion and limits |
| --- | --- | --- |
| Arrow IPC file | Original WKB, schema and metadata | Exact supported Arrow types, nulls and full uint64 |
| GeoParquet | WKB GeoParquet metadata, native PROJJSON, bbox/type finalization | Exact supported types, Snappy, 65536-row groups |
| FlatGeobuf | Official writer, native WKT, spatial index, mixed geometries; empty/null rejects | uint64 converts to checked signed64; larger values reject because GDAL otherwise rounds ULong to float64. Time stored as integer milliseconds, schema metadata carries contract. Null properties omitted in feature storage and reopen as null |
| GeoPackage | Complete SQLite container, feature table, SRS/WKT2 extension, RTree and contents tables | SQLite signed64 (larger uint64 rejects), bool, real, UTF8, blob, nullable fields; timestamp stored as UTC ISO text with millisecond precision. Field metadata beyond CRS is not archived |
| GeoJSON / Lines | WGS84 longitude/latitude only, CCW exterior/CW holes; Python transforms and orients | Nullable scalar properties; integers outside ±(2**53-1) become decimal strings. Millisecond timestamps remain JSON integers. Binary attributes reject. No full Arrow schema/field metadata archive. Lines is one feature per newline, with no RFC8142 record separator |

GeoJSON timestamp integers outside JavaScript's exact integer range require a
consumer with an exact integer parser; year3000 timestamps are inside that range.
GeoJSON has no fidelity claim for the original Arrow type schema. Binary source
exports retain geometry coordinates, without rendering simplification or tiling.
PMTiles/freestiler remains the separate rendering path and owner.

## Lifecycle and memory

Writers validate and consume one batch at a time. Each operation stages inside a
private temporary sibling directory; malformed later input, iterator failure,
writer error or finalization failure removes only that directory. Finalized files
are synchronized and installed using no-clobber persistence. Existing targets
reject. This is single-file atomic installation, not crash-proof multi-file
transactionality or an append/multi-layer API. GeoPackage currently creates one
`features` layer per output. Python IPC spool size is proportional to total input.

Parquet buffers its configured row group. FlatGeobuf's official writer spools
features to disk and retains feature offsets/index nodes; indexed FGB memory is
not constant in total feature count. Do not claim whole-pipeline bounded memory
merely from a bounded input batch. The source Python table may also be eager.
Metrics separate validation, writer calls, finalization and total time. Encoding,
compression and index work internal to dependency calls is grouped, not falsely
reported as independently measured stages.

## Build and dependencies

```powershell
cargo test --locked --manifest-path rust/fast-hdf/src/exports/Cargo.toml --features all-writers
cargo clippy --locked --manifest-path rust/fast-hdf/src/exports/Cargo.toml --all-features -- -D warnings
cargo build --locked --manifest-path tests/rust_first_tier_exports/harness/Cargo.toml
uv run python -m pytest tests/rust_first_tier_exports
```

With the separate parent registration patch, build the Python extension:

```powershell
uv pip install maturin pyarrow pyproj shapely
uv run maturin develop --release --locked --features extension-module,exports-all --manifest-path rust/fast-hdf/Cargo.toml
```

Default library features include Arrow IPC only. Opt in with `geojson`,
`flatgeobuf`, `geoparquet`, `geopackage` or `all-writers`. Parent proposal features
are `exports-arrow`, `exports-geojson`, `exports-flatgeobuf`,
`exports-geoparquet`, `exports-geopackage`, `exports-all`. Basic HDF builds gain
no mandatory GDAL or SQLite dependency. The GeoPackage feature bundles SQLite C
and needs a C toolchain. This writer crate needs no GDAL; GDAL/pyogrio are
independent qualification readers. Python reprojection uses pyproj/PROJ. The
parent freestiler dependency still includes native compression dependencies.

Direct pins: Arrow/Parquet59.0.0 (Apache-2.0), GeoParquet0.9.0 and
GeoZero0.15.1 (MIT OR Apache-2.0), FlatGeobuf6.0.1 (BSD-2-Clause),
GeoPackage0.10.0 (MIT OR Apache-2.0). Lockfiles pin transitive resolution.
Separate metadata license inventory is delivered as evidence; it is not a full
legal redistribution audit. Only Windows x64/Python3.12 has been built here;
cross-platform/abi3 Python and NumPy wheel matrices, SQLite/PROJ redistribution,
license notices and optional wheel feature packaging remain integrator work.
RustGIS can use this library without PyO3. External RustGIS/terrio were not edited.
