# First-tier source export qualification

Run from the pinned isolated local checkout, never from the NAS source tree.
The harness's Cargo manifest references only the owned export library. The
optional binding tests require the separately proposed parent/Python patches.
Tests assert source/extension provenance. Missing native bindings or an unset
`RAS_EXPORT_FIXTURE_ROOT` skip those external prerequisites explicitly.

```powershell
uv venv .venv --python 3.12
uv pip install -e . pytest maturin pyarrow pyogrio geopandas pyproj shapely xarray scipy requests tqdm psutil
cargo build --locked --manifest-path tests/rust_first_tier_exports/harness/Cargo.toml
$env:RAS_EXPORT_FIXTURE_ROOT=(Join-Path $PWD 'working/fixtures')
uv run python -m pytest tests/rust_first_tier_exports -q
```

Fixture names: `JUL2020_D100RAS.p04.hdf` (stored5.0.7),
`BaldEagleDamBrk.p03.hdf` (stored6.6), `BaldEagleDamBrk.p18.hdf` (stored7.0).
Use immutable local copies from RasExamples/retained qualification artifacts.
The6.6 fixture lacks the maximum-WSE summary, so that sample explicitly exports
null result fields. Tests do not invent a run or summary. Real geometry is
extracted through HdfMesh, results through HdfResultsMesh, and available line
layers through HdfXsec/HdfStruc. Existing path-qualified copies are inputs;
no model-file glob discovery replaces project DataFrame metadata.

Final-region fixture `computed7_regions.gpkg`/`computed7.json` comes from the
previous fluvial-graph qualification's stored7.0 computed plan:72 final regions,
including holes/multipart. Its receipt names source resolution via RasPrj.plan_df,
source hashes, classifications and extraction method. This packet independently
reopens it and tests actual exported source geometry. It does not rerun or
reimplement the separate classifier.

PyArrow independently reopens Arrow/Parquet; GDAL via pyogrio independently
reopens spatial formats, and SQLite checks the GeoPackage container and RTree.
JSON parsing verifies exact large-integer strings and year3000 milliseconds.
The official Rust writers' own readers are not the qualification oracle.
Small format edge cases supplement, rather than replace, real RAS fixtures.
