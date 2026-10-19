# Rust consumer contract

Installed-wheel acceptance for consumers of the optional native backend
(`ras_commander_fast_hdf`) through the public `ras_commander` API, plus a
static source/ABI inventory. Owner packet: `consumer-contract` of run
`nas-parallel-38e2858a6fcd45c69718e6752eeb7f00`.

| File | Scope |
|---|---|
| `inventory.py` | Source-only inventory: registrations incl. `register(m)` delegation and `add_class`, features, git pins, PyO3/NumPy/filesystem coupling |
| `test_source_inventory.py` | Explicit 26-entry full-feature registration set, reconciled with the accepted runtime ABI when a receipt is supplied |
| `test_native_gate.py` | Wheel archive SHA + RECORD, inner `.pyd/.so` SHA, Python wheel vs accepted commit blobs, non-editable import origins, runtime ABI, isolated cwd |
| `test_native_consumer.py` | Real-fixture behaviour: required-native slices with call counts and no fallback, Python reference, physical I/O bound, buffer ownership, composite identity/CRS/units, D601 policy, native max depth vs frozen reference, year-3000 ms, per-format independent reopen, PMTiles/MVT spec decode |
| `contract.py` | Shared helpers: call recorder (signature preserving), PMTiles v3 / MVT decoder, chunk planning |

Native tests skip unless all environment inputs exist:

```
RAS_CONSUMER_ACCEPTANCE_RECEIPT=<accepted-source-build.json>
RAS_CONSUMER_FIXTURES=<local fixture copies>
RAS_CONSUMER_SOURCE_CHECKOUT=<isolated checkout of the accepted commit>
RAS_CONSUMER_REFERENCE_DEPTH=<frozen reference-depth parquet folder>
RAS_CONSUMER_EVIDENCE=<output folder for observations/hashes>   (optional)
```

Run from an empty directory that is not an ancestor of the source checkout
or the venv, with the wheels installed non-editably:

```
python -I -m pytest <checkout>/tests/rust_consumer_contract --rootdir=<empty cwd> -p no:cacheprovider -o addopts= -rA
```

Benchmarks: `scripts/benchmarks/rust_consumer_contract/benchmark.py run`
(fresh process per measurement, >=3 interleaved repetitions, digest-checked
equal output). Its docstring states the measurement limits.


Hardened bridge activation: engine commit is read from the activated checkout's
Cargo.toml; API_VERSION=2, TEXT_API_VERSION=1. expected.py explicitly lists all 26
entrypoints, including nine hardened domain bindings. Old 17-entry runtime inventories
are rejected, not silently upgraded. After installing the newly built full-feature wheel,
run `python tests/rust_consumer_contract/capture_runtime.py --source-commit COMMIT
--output NEW_RUNTIME.json` and point the new acceptance receipt at that artifact. Preserve
old receipts. The capture fails on any missing/extra entrypoint; retain exact signatures,
source commit and loaded extension binary hash. Parent still supplies wheel hashes,
noneditable/isolated import proof, full source tree and fixture evidence.
