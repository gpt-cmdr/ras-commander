# Whole-model source-writer experiment

Run from a separate checkout of pinned d6b57fa plus the combined export patch and
the coordinator's reviewed adapter patch. Record both patch hashes and the built
native extension path/hash. Do not reuse an older separate-worker native binary.
This packet has no shared registration patch; `validate_export_wkb` remains in
the coordinator-owned binding.

```powershell
uv venv .venv --python 3.12
uv pip install -e . pytest maturin pyarrow pyogrio geopandas pyproj shapely xarray scipy requests tqdm psutil pmtiles mapbox-vector-tile freestiler==0.3.0
uv run maturin develop --release --locked --features extension-module,exports-all --manifest-path rust/fast-hdf/Cargo.toml
$env:CARGO_TARGET_DIR=(Join-Path $PWD 'rust/fast-hdf/target')
cargo build --release --locked --manifest-path tests/rust_whole_model_exports/harness/Cargo.toml
# The inherited format suite also needs its separate test-harness prerequisite.
cargo build --release --locked --manifest-path tests/rust_first_tier_exports/harness/Cargo.toml
$env:RAS_EXPORT_HARNESS=(Join-Path $PWD 'rust/fast-hdf/target/release/export-test-harness.exe')
$env:RAS_EXPORT_FIXTURE_ROOT=(Join-Path $PWD 'working/fixtures')
uv run python -m pytest tests/rust_first_tier_exports tests/rust_export_conformance tests/test_fast_hdf.py -q -rx

uv run python scripts/benchmarks/rust_whole_model_exports/prepare.py --fixture working/fixtures/BaldEagleDamBrk.p18.hdf --version 7.0 --expected 4425 --output working/prepared/cells7
uv run python scripts/benchmarks/rust_whole_model_exports/prepare.py --fixture working/fixtures/BaldEagleDamBrk.p03.hdf --version 6.6 --expected 18066 --output working/prepared/cells6
uv run python scripts/benchmarks/rust_whole_model_exports/prepare.py --fixture working/fixtures/computed7_regions.gpkg --version regions7 --expected 72 --output working/prepared/regions7
uv run python scripts/benchmarks/rust_whole_model_exports/prepare.py --fixture working/fixtures/JUL2020_D100RAS.p04.hdf --version 5.0.7 --expected 340246 --output working/prepared/cells5

uv run python scripts/benchmarks/rust_whole_model_exports/benchmark.py --prepared working/prepared/cells7 --output working/qualification/cells7 --samples 3
# Repeat for cells6 and regions7; use --samples 1 for cells5 if resource bounded.
uv run python scripts/benchmarks/rust_whole_model_exports/summarize.py --root working/qualification --output working/report
uv run python -m pytest tests/rust_whole_model_exports -q
```

Do not overwrite prepared folders or benchmark runs: the scripts reject existing
output directories so failed/slow evidence is retained. Supplied fixture access
JSON lists exact NAS copies for the coordinator; each worker copies locally once.
No new HEC-RAS computation is required. `prepare.py` uses HdfMesh/HdfResultsMesh
and HdfBase; retained final-region provenance records the prior project DataFrame
path resolution. No adjacency algorithm or custom tiler is introduced.

Every result records pass/fail status and independent full-feature equality.
Prepared extraction/encoding/transformation/IPC production are recorded once,
outside writer timing. The direct experiment preloads native Arrow batches from
IPC, records that cost, then calls export_batches with a resident iterator. It
does not demonstrate a zero-copy Python/native binding. IPC and direct routes
reuse already transformed geographic input; the adapter route still performs
the geographic transformation per export. Compare these with their preparation
costs rather than treating the native timer alone as end-to-end acceleration.

The measurement controller records child RSS and sampled disk at 20 ms intervals.
Its own verification memory and the separate HDF extraction process are excluded;
they can be substantial for the largest case. OS before-verification peaks in
Python children include imports/prepared data. Rust direct-child peaks include
resident prepared batches but no Python interpreter or controller verification.
Temporary disk is sampled, including a dedicated TEMP/TMP directory, and can miss
short-lived/deleted/unreadable files. Exact adapter IPC bytes are also captured at
native entry. These are explicit lower-bound observations, not proof of constant
whole-pipeline memory or exact filesystem high-water marks.

The Python baseline uses direct pyogrio Arrow output for GDAL formats rather than
Python row dictionaries, GeoPandas for conforming GeoParquet, and Arrow IPC for
transport. Native builds use their pinned Rust codec stack; Python binaries have
their own codec versions. Schema types, precision, compression choice and indexes
are aligned, but byte-identical metadata/codec settings are not asserted.

`profile_adapter.py` produces separate cold/warm cProfile evidence. It is excluded
from medians. An obvious future integration experiment is an optional Arrow C
stream/buffer entry to export_batches, preserving the reviewed original-WKB
validation and field metadata. This packet returns that as a proposal rather
than modifying the sibling source-writer or coordinator registration scope.

## Separate HDF extraction stage

`extraction.py` times HdfMesh.get_mesh_cell_polygons itself, separately from
summary-result reads, joins, WKB encoding, writer timers and verification. Run
three samples for cells7/cells6 and one for cells5 with --fixture, --prepared,
--output, and --samples. Explicit backend=rust has no fallback: the native
assemble_cells call is counted and Python polygonize is forbidden during the
call. Threads=2 is fixed for Rust. Full composite keys and every normalized
polygon coordinate are compared with the saved complete Python oracle. The
source HDF hash must remain unchanged.

The reviewed combined native backend rejects the largest5.x model at source
cell317422 before completing. That is a negative result, with no successful
Rust extraction time or quarantine count. The Python reference omits317422 and
339176 and returns340246valid cells; native failure is not replaced with a
fallback sample. Small-model native and reference outputs match all normalized
coordinates. One-time preparation including results and joins is a different
stage/run from isolated polygon extraction, so their times are not subtracted
or added as if they were components measured in one execution.

## Integration opt-in

These checks consume generated prepared models and benchmark reports, not committed test data. Set `$env:RAS_RUN_WHOLE_MODEL_EXPORT_TESTS="1"` only after the documented preparation/measurement steps. Without it the module skips explicitly; skips are not successful model qualification. Worker historical13passes refer to the fully prepared worker environment.
