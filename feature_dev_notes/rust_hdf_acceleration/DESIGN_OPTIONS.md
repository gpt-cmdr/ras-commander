# Design options for a Rust-backed reader

## Options

| Option | Effort (one developer) | Verdict |
|---|---|---|
| **(a) PyO3 wheel with a task-level API** | about 1–2 weeks (~500–800 lines of Rust) plus wheel CI | **Recommended.** It targets only the paths where Rust wins. |
| (b) Read-only h5py look-alike (path access, `attrs`, slicing, structured dtypes) | about 3–5 weeks (2,000+ lines) | Effort spent where Rust gives no speed-up. |
| (c) h5py-like access through terrio's Python package | as (b), plus upstream review | Poor fit: terrio is GDAL-like (rasters and vectors). |
| (d) Keep h5py only | none | Stays the default and the fallback. |

## Sketch of the task-level API

```python
from ras_commander.fast_hdf import available  # False when the extra isn't installed

mesh_names(hdf) -> list[str]
read_summary(hdf, mesh, variable) -> np.ndarray                  # e.g. "Maximum Water Surface"
read_timeseries(hdf, mesh, variable, cells=None, times=None, parallel=True) -> np.ndarray
read_geometry_arrays(hdf, mesh) -> dict[str, np.ndarray]
cell_polygons(hdf, mesh) -> pyarrow.Table                        # WKB/GeoArrow, assembled in Rust
timestamps(hdf) -> list[str]
fingerprint(hdf, parallel=True) -> dict[str, str]                # per-dataset digests
```

- **Results:** arrays are handed to numpy without copying (`PyArray::from_vec`).
- **Fallback:** any unsupported structure raises a specific exception, and the caller falls back
  to h5py.
- **Call sites:** `HdfResultsMesh`, `HdfMesh` and the fingerprinting code call `fast_hdf` when it's
  available, unless `RAS_COMMANDER_FAST_HDF=0`.

## Crate choice

- **`hdf5-reader`:**
  - It has parallel APIs, positioned reads and slicing.
  - It needs netcdf-rust#95, so pin a fork until a release carries it.
  - It is what terrio uses, so ras-commander, terrio and RustGIS would share one reader and one
    conformance suite.
- **`hdf5-pure`:**
  - It reads HEC-RAS unpatched, uses the least memory and builds for wasm.
  - It has no parallel or column-slicing API; adding parallel chunk decompression is about 100
    lines.
- **Either way:** enable zlib-rs.

## Risks

- **Maturity:** both crates date from 2026, and the netcdf-rust upstream has one maintainer. That
  PR's response time will show whether it is alive.
- **Two HDF5 stacks to keep in agreement** (string trimming, ghost cells, fill values). The
  conformance suite is mandatory.
- **CLB owns** wheel builds for 3 operating systems.
- **Writes stay on h5py permanently.**

## When to build it

When archival or bulk-extraction work, such as ras2cng over a model library or batch
post-processing of large plans, is a measured bottleneck. Parallel decompression and Rust-side
polygon assembly are the two features that pay for it.
