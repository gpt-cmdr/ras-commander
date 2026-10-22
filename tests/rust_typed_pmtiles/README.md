# Typed PMTiles bridge qualification

This packet adds only exports/pmtiles_bridge.rs and this test directory. Shared
Cargo/module/PyO3/Python changes are separate integrator proposals. Base source
is d6b57fa plus combined-exports.patch (d2df6f...d1567a) and the coordinator's
review-adapter-fixes.patch (2eb8c3...fce52). Preserve validate_export_wkb and its
original-buffer validation and geometry metadata retention when integrating.

The Rust entry accepts Arrow59 RecordBatch iterators with the existing
ras:export:v1/geoarrow.wkb contract. It validates batches, decodes polygon and
multipolygon WKB using established geozero, reads scalar columns directly and
passes owned features to the pinned freestiler engine. It does not implement
a tiler or change source batches. Python stages typed IPC and performs explicit
always_xy pyproj transformation; original WKB buffers are validated before
Shapely can normalize unsupported SRID/trailing encodings.

Native callers must declare resolved WGS84 geographic degree coordinates and
consistent GeoArrow CRS metadata. Rust trusts the producer's semantic CRS
resolution, rather than parsing WKT with a second CRS engine. The Python API
requires source_crs, rejects missing/conflicting declarations and preserves
source CRS evidence plus arbitrary geometry-field metadata in the manifest.
Web Mercator latitude limits are checked before tiling. Points/lines/null/empty
geometry reject in this bounded polygon bridge; the shared master contract
retains those richer geometry capabilities.

Output is a NEW bundle directory: tiles.pmtiles, identities.arrow and
manifest.json. No overwrite/append. Composite (mesh_name,cell_id) is the source
identity; duplicate identities reject across the entire input stream, even in
later batches. Initial IDs enumerate sorted composite keys, independent of
batch partition/order. Reuse a previous bundle explicitly with reuse_from to
retain those IDs across later/subset/extended exports. New composite identities
append in sorted order after the existing maximum; overflow rejects. Previously
known but absent identities remain in the inverse Arrow registry with
present=false. Omitting reuse_from creates a new registry: IDs need not remain
stable when the identity set changes. No row-position identity or lossy hash.

The registry is an explicit trusted local input; malformed versions, schema,
nulls, duplicate identities/IDs, negative IDs and exhausted ranges reject. It
is not an authenticated/tamper-proof database. The manifest records producer
CRS/schema/field metadata, exact conversion policies and options. Arrow carries
exact i64 provenance; do not depend on JavaScript JSON number precision for
large source identifiers.

PMTiles attributes: Int64 exact; UInt64 checked to signed i64; Float64 finite;
Boolean/Utf8 preserved; nulls omit MVT property values. Timestamp[ms] rejects
unless timestamp_ms=True explicitly converts UTC Unix milliseconds to signed
integer properties. Binary attributes reject even if all-null. Rich master
Arrow types remain unchanged. MVT stores large integer values exactly, but
consumer-specific JavaScript/viewer precision is not qualified here.

All validation/identity/type checks finish before freestiler runs or publication
starts. Late producer errors and failures remove the private stage. A successful
bundle publishes through directory rename after syncing its files. An exclusive
sibling lock coordinates bridge writers and is never stolen. Existing output
rejects; no crash-proof transaction or noncooperating Unix rename-race guarantee.
Publication is qualified on this Windows host. Source bundles are immutable;
reuse writes a separate new bundle. Crashed lock recovery is a coordinator task.

freestiler clipping, buffered tiles and integer quantization apply. No repair,
simplification, dropping, clustering or coalescing. The known 36-invalid-low-zoom
regression remains an explicit expected failure after independent reference
geometry and complete ID coverage pass. Optional strict validation proposal:
decode staged tiles and reject invalid output before publication, without
altering geometry. It is not implemented by this bounded bridge.

Input batches have a size cap, but freestiler retains the complete feature set
and bridge identity maps in memory. No bounded whole-stream memory claim.
Measurements separate validation/native conversion/tiling/provenance and Python
transport costs; temporary-disk polling is only an observed lower bound. The
repeated real footprint benchmark is not whole-model spatial scaling.

Build with proposed registrations/features:

```powershell
uv pip install -e . maturin pytest pyarrow geopandas pyproj pmtiles mapbox-vector-tile freestiler==0.3.0 psutil
uv run --no-sync maturin develop --release --locked --features extension-module,exports-all,exports-pmtiles --manifest-path rust/fast-hdf/Cargo.toml
$env:RAS_EXPORT_FIXTURE_ROOT = "$PWD/working/fixtures"
uv run --no-sync python -m pytest tests/rust_typed_pmtiles tests/rust_first_tier_exports/test_binding.py tests/rust_first_tier_exports/test_review_regressions.py
uv run --no-sync python tests/rust_typed_pmtiles/measure.py --fixture working/fixtures/computed7_regions.gpkg --output working/measurements --count 512 --samples 3
```

The tiny harness is only a test transport for existing source-writer regression
tests. It delegates to the same ras-export crate and ships no production CLI.
No external repository edits, original-model changes, HEC-RAS computation,
upstream posting or release are included.

Runtime finding: the retained 72 final regions also yield three invalid decoded polygons at z12, exactly matching the established freestiler route. The real-region conformance test requires normalized coordinate/property/ID parity and records this validity count; its passing conversion check is not a valid-polygon guarantee. Retained receipts and archives make this separate rendering limitation reviewable.

The final-region fixture uses its stored GeoPackage FID as source local identity, not GeoDataFrame row position. This is stable for the immutable input file, not a promise across independently regenerated region datasets. Benchmark replicas preserve source FID and use explicit replica mesh namespaces. Provenance checks cover the loaded native .pyd itself as well as the Python package wrapper.
