# Buffered FlatGeobuf finalization

This follow-up branches from the clean whole-model qualification revision
a3e28c952126b36b6cc8df5f6126c8d3697c2601. Preserve the installed prior release
package under working/fgb-finalization/baseline before rebuilding the candidate.
Record the inner extension module's `.pyd` hash, not just package `__init__.py`.
Workers load that pinned baseline or the newly built candidate in fresh processes.

`RAS_FAST_HDF_SOURCE` is a checkout of
[gpt-cmdr/ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf);
the extension moved there from `rust/fast-hdf`.

```powershell
uv run --project $PWD --directory $env:RAS_FAST_HDF_SOURCE/python maturin develop --release --locked --features extension-module,exports-all
uv run python scripts/benchmarks/rust_fgb_finalization/benchmark.py --prepared working/prepared/cells7 --output working/fgb-finalization/measurements/cells7 --samples 3
# Repeat with cells6 and cells5. Do not overwrite previous measurement folders.
uv run python -m pytest tests/rust_fgb_finalization -q
cargo test --release --locked --manifest-path $env:RAS_FAST_HDF_SOURCE/Cargo.toml --lib --features exports-flatgeobuf exports::
cargo test --release --locked --manifest-path tests/rust_fgb_finalization/Cargo.toml
uv run python scripts/benchmarks/rust_fgb_finalization/policy_probe.py --output working/fgb-finalization/strict-policy.json
```

The prepared whole-model files are unchanged: 4425 cells in stored7.0,18066 in
6.6 and 1872746 cells in 5.0.7 (the public FEMA eBFE `AustinOyster.p03` plan).
Two builds x three samples per complete case, alternating which runs first.
Every output independently reopens all geometry, composite IDs, properties and
CRS through GDAL/pyogrio. A spatial-index bbox query is checked against the source
geometry predicate. Tests also require byte-identical baseline/candidate files.
No timing assertion or synthetic speed threshold determines correctness.

The timed native IPC entry reads identical pre-spooled batches in both builds.
HDF extraction, Python preparation and independent verification are outside its
timer. Existing20ms monitor records process RSS and output/system-temp disk;
temporary high-water observations are lower bounds. RSS before verification
includes imports/input but excludes GDAL reopen. Earlier Python timings belong
to the previous experiment and are context only, not a controlled third route.

The implementation buffers the official writer's per-feature writes in1MiB,
then explicitly flushes before the existing file sync and atomic no-clobber
publication. Fault-injection unit tests verify buffered-write and sink-flush
errors propagate. Separate tests use actual source batches to verify late
producer failure cleanup and existing-output preservation without consuming input.

Policy probing is read-only. Required Rust extraction rejects the malformed5.x
cell for both strict=False and strict=True, with different exception classes.
No quarantine/repair/auto fallback is implemented here. Shared binding, CRS,
HdfMesh and mesh.rs sources remain unchanged, including validate_export_wkb.

The report-validation pytest module requires `$env:RAS_RUN_FGB_MEASUREMENTS="1"` after the baseline/candidate runs. Default skips do not count as qualification. Rust lifecycle tests require the documented real prepared cells7 input.
