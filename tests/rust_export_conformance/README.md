# Packed PMTiles qualification

This suite exercises the native packed adapter against the pinned freestiler
pipeline. The public Python adapter and obsolete repair-module unregistration
are separate integrator patches in the export-distribution NAS delivery.
Apply those with the owned patch to reproduce the full public-API tests.

Required packages in the checkout's .venv: pytest, geopandas, pyproj, pmtiles,
mapbox-vector-tile, freestiler==0.3.0, and the locally built native extension.
Missing optional packages cause explicit collection/test skips. Qualification
requires no skips. Tests assert cwd, ras_commander source and native-module
paths so another checkout or globally installed extension cannot pass by accident.

`RAS_FAST_HDF_SOURCE` is a checkout of
[gpt-cmdr/ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf);
the extension moved there from `rust/fast-hdf`.

```powershell
uv pip install -e . pytest maturin geopandas pyproj pmtiles mapbox-vector-tile freestiler==0.3.0 psutil
$env:VIRTUAL_ENV = "$PWD/.venv"
Push-Location $env:RAS_FAST_HDF_SOURCE/python  # pyproject.toml; builds the root crate
maturin develop --release --locked --features extension-module,exports-all,exports-pmtiles
Pop-Location
$env:RAS_EXPORT_FIXTURE_ROOT = "$PWD/working/fixtures"
uv run --no-sync python -m pytest tests/rust_export_conformance tests/test_fast_hdf.py -q -rx -o junit_family=legacy
```

The optional real fixture directory contains locally copied, unmodified HDFs:
JUL2020_D100RAS.p04.hdf (stored 5.0.7), BaldEagleDamBrk.p03.hdf (6.6), and
BaldEagleDamBrk.p18.hdf (7.0). Qualification receipts contain SHA256, HDF root
attributes, selected mesh/cell identities and CRS. Model computation is not used.
The 5.x API excludes two previously diagnosed invalid source cells; this suite
exports bounded valid regions, not a full-model validity certification.

Geometry contract: coordinates are float64[N,2]; ring_offsets spans coordinates,
polygon_offsets spans rings (exterior first), feature_offsets spans polygons.
All offsets are signed int64 vectors, start at zero, end at the child count and
have strictly increasing component spans. Empty layers use [0] at every level.
IDs and property columns are per feature. Legacy offsets remains the one-ring
alternative; mixing the alternatives rejects. Source polygons must be valid;
individual rings are validated without changing their vertices. Coordinate
transformation is explicit through source_crs and pyproj. No GeoJSON is involved.

MVT integer quantization and freestiler's 5% clipping buffer are rendering
semantics. Tests compare tile cores within two extent units of source boundaries,
verify holes as empty interiors even across tile edges, and independently reopen
both PMTiles addresses and decoded MVT features. Full-resolution source equality
is not a tile-output requirement. Freestiler simplification, feature dropping,
clustering and coalescing are disabled, preserving the previous packed options.

Known distribution gap: test_distribution_gaps.py retains an explicit expected
failure for actual invalid low-zoom quantized polygons reproduced by freestiler
0.3.0 and pinned core beb64b0. It first requires exact reference geometry and
complete source feature coverage, then writes gap.json and both actual archives.
Do not count this expected failure as proof of valid output. No replacement
clipping/repair implementation is introduced.

The benchmark script under scripts/benchmarks/rust_export_conformance accepts a
retained source-regions.gpkg, uses three fresh processes per route in shuffled
order, and independently checks decoded geometry/properties. Windows whole-
process peak working set includes imports/input. A small repeated footprint is
not a whole-model scaling or speedup claim. Source IDs differ because the packed
route preserves supplied IDs while freestiler's Python route generates IDs;
output bytes are therefore reported separately, not treated as equivalent costs.
