# Building the optional Rust backend

`ras-commander-fast-hdf` is an optional extension. ras-commander installs and
works without it; `RAS_COMMANDER_FAST_HDF=required` or `backend="rust"` turns
its absence into an explicit `FastHdfError` instead of a silent Python
fallback. This page describes how to build and qualify a local wheel. Nothing
here publishes a wheel, pushes a dependency fork or contacts a registry
beyond the Cargo/PyPI downloads a normal build performs.

## Why a dependency preparation step exists

`rust/fast-hdf/Cargo.toml` pins `hdf5-reader` from `gpt-cmdr/netcdf-rust` at
`24ff6fcfcc79a35c30aa5d8cb3028ab4d9d00564`. The extension also needs two
reviewed fixes to that dependency (shared-message v2/v3 locations and
filtered fixed-array chunk-size widths). They are not upstream, so the
committed `Cargo.lock` records `hdf5-reader`/`hdf5-core` as **path**
packages. Consequently

```text
cargo build --locked --manifest-path rust/fast-hdf/Cargo.toml
```

fails with *cannot update the lock file* unless a `[patch]` override points
at a prepared copy of the patched dependency. `scripts/build_rust_backend/`
recreates that copy reproducibly:

| File | Purpose |
|------|---------|
| `dependency.json` | Pinned commit, base tree, patched tree, license, patch SHA256s |
| `patches/*.patch` | The two reviewed dependency patches (byte-exact, LF) |
| `prepare_dependency.py` | Clone, verify commit/tree, verify patch hashes, apply, verify patched tree |
| `build_wheel.py` | Prepare the dependency and build a release wheel with a fresh target |
| `verify_install.py` | Install into clean environments and run `tests/rust_distribution` |

The prepared dependency's tree is `5cf92f94e6594bab9e792fc9d50a1e4e49ed28bc`
whether it is cloned from GitHub or from a local Cargo Git cache. Preparation
refuses an existing directory that is not the expected patched tree and never
resets it.

## Requirements

- Rust stable with the platform linker (Windows: Visual Studio C++ Build
  Tools). The export crate declares `rust-version = 1.95`.
- `git` and [uv](https://docs.astral.sh/uv/).
- Python 3.10 or later. The wheel is `abi3` (`cp310-abi3`), so one wheel per
  platform serves every supported CPython.
- maturin is obtained by `uv tool run --from maturin==1.15.0`; it is the build
  backend declared in `rust/fast-hdf/pyproject.toml`.

No global toolchain changes are made by these scripts.

## Build

Use a local work directory, never a network share. Each work directory gets
its own `CARGO_TARGET_DIR`; no previously built `.pyd`/`.so` is reused.

```powershell
python -I scripts/build_rust_backend/build_wheel.py `
    --work-dir C:/scratch/fast-hdf-build `
    --python <path-to-python-3.10+>
```

Optional: `--dep-source <local netcdf-rust clone>` avoids a GitHub clone; the
commit and tree are verified either way. The default features are
`extension-module` (from pyproject), `exports-all` and `exports-pmtiles`.

maturin does not pass `--config` to `cargo metadata`, so the script writes
the `[patch]` table to `<work-dir>/.cargo/config.toml` and runs maturin from
the work directory. Cargo reads configuration from the current directory, so
nothing is written into the source checkout, and standalone writer manifests
(`rust/fast-hdf/src/exports`) built from elsewhere are unaffected.

`<work-dir>/build-receipt.json` records the source commit/tree and any dirty
paths, the dependency receipt (commit, patched tree, patch and license
hashes), toolchain versions, build seconds, and the wheel and inner extension
SHA256 and sizes.

To run Cargo directly, prepare the dependency and pass the override:

```powershell
python -I scripts/build_rust_backend/prepare_dependency.py --dest C:/scratch/netcdf-rust-patched
# prints cargo_config_args, e.g.
cargo test --locked --manifest-path rust/fast-hdf/Cargo.toml `
    --config 'patch."https://github.com/gpt-cmdr/netcdf-rust".hdf5-reader.path="C:/scratch/netcdf-rust-patched/hdf5-reader"'
```

## Qualify a clean install

```powershell
python -I scripts/build_rust_backend/verify_install.py `
    --work-dir C:/scratch/fast-hdf-build --python 3.12 --fixtures C:/scratch/fixtures
```

This creates `env-python` (ras-commander only) and `env-native`
(ras-commander plus the wheel), both installed non-editably, and runs
`tests/rust_distribution` from an empty directory. The native suite asserts
that `ras_commander` and `ras_commander_fast_hdf` import from the clean
environment, that the loaded binary's SHA256 equals the wheel's, the `abi3`
tag, numeric reads against h5py and mesh polygons against the Python backend
on stored HEC-RAS 5.0.7, 6.6 and 7.0 results, and Arrow/first-tier/PMTiles
smoke exports. The Python-only suite proves that import, `available()`,
auto-mode reads and mesh polygons work without the extension and that
required/rust mode rejects. Missing fixtures are reported as skipped
(unavailable), never as passes.

`tests/rust_distribution/test_dependency_preparation.py` needs only git and
pytest; set `RAS_DIST_DEP_SOURCE` to also prepare the real dependency.

## Routed reads: what required mode proves

Routed `Hdf*` readers use `fast_hdf.read_typed`. The routing policy and backend
modes are described in the HDF API reference (*Routed HDF reads and backend
modes*). In short:

- Auto falls back to h5py on any native failure of a routed read, so public
  outcomes are the h5py ones. Since PY-ROUTE-2 this includes `HdfResultsMesh`
  result readers: `read_dataset` (and the native temporal reduction) no longer
  treat a native Corrupt refusal as fatal in auto mode.
- Required mode raises `FastHdfError` on any refusal. It reads all numeric
  values and all attribute values natively. Text datasets, text-only compound
  identity tables and structure walks stay on h5py (the documented metadata
  exception); a compound with a numeric member and no typed route is refused.
  Attributes of every group and dataset come from `fast_hdf.read_attrs` /
  `read_attr` (engine typed group and dataset attributes, bridge API 11) and
  refuse in required mode when a value cannot be reproduced or the dataset is
  virtual/external.
- `trace_reads()` records only reads made through the adapter. It is not a
  complete I/O audit. `tests/rust_route_1` independently intercepts
  `h5py.Dataset.__getitem__`/`read_direct` and `h5py.AttributeManager.__getitem__`
  in required mode; every attribute value read through h5py is an offender. It also checks
  injected engine failures and physically damaged copies (a flipped Fletcher32
  checksum byte, and a virtual dataset).
- `tests/rust_route_2` (gate `RAS_ROUTE2_FIXTURES`; optional `projects` for
  multi-file land-cover/infiltration methods) applies the same three-mode,
  h5py-interception and injected-failure contract to the Wave 3 families
  (bridge API 10, engine `e9afad3`), plus binding-boundary tests and an edited
  sediment copy whose contradictory unit attribute is removed.
- `tests/rust_route_3` (bridge API 11, engine `435ddb4`, engine API 9):
  attribute fidelity on a synthetic h5py fixture (NULL dataspaces, bitfields,
  vlen, virtual datasets), engine family failures in refusals, the API 9
  binding boundary, and the native 2D series domain against PR #565's rule
  (`RAS_ROUTE3_LEGACY_EXCERPTS` adds the engine's legacy-Location excerpts; a
  `requires_pr565` test compares the library's own rule after #565 merges).
- H5PY in the coverage inventory is a qualification label, not an enforced
  backend selection.

## Platform status

Only configurations that were actually built and tested are qualified. See
the qualification output for the current matrix; a cross-compile alone is
not a pass. Linux and macOS builds require the same dependency preparation
and their own native toolchains.

## Licenses

The wheel's `licenses/` directory carries notices for hdf5-reader (MIT, from
the MIT OR Apache-2.0 dual license), freestiler (MIT and ISC), i_overlay and
i_float. The patched dependency keeps its upstream `LICENSE-MIT` and
`LICENSE-APACHE`; their hashes are in the dependency receipt.
