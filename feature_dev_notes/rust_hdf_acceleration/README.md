# Rust-accelerated HDF reading (optional `fast-hdf` backend)

Status: research complete (2026-10-17). Tracking issue: [#544](https://github.com/gpt-cmdr/ras-commander/issues/544).

Update: the backend shipped as the optional `ras-commander-fast-hdf` extension
([user guide](../../docs/native-engine.md)). Its source, engine included, now lives in
[gpt-cmdr/ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf);
install it with `pip install ras-commander[fast]`. The notes below are the original research.

## Outcome

A pure-Rust HDF5 reader can read every HEC-RAS geometry and plan dataset byte-identical to h5py.
The gains that matter are decompressing chunks in parallel and using less memory, not speed in a
single thread.

- **Single-threaded:** about level with h5py out of the box. With flate2's pure-Rust zlib-rs
  decompressor, about **1.2× faster on bulk reads and 1.6–2.0× faster on "read every dataset"**,
  the archival and fingerprinting pattern.
- **Parallel chunk decompression:** 3.6–4.8× faster than h5py for a mesh's full time series and
  for single-cell hydrographs (the worst case for HEC-RAS's one-chunk-per-time-step layout), and
  2–3× for reading a whole plan. libhdf5's global lock makes this impossible through h5py.
- **Memory:** 2–6× lower peak use. A full `Water Surface` on a 582 MB plan peaks at 289 MiB with
  h5py, 156 MiB with hdf5-reader and 91 MiB with hdf5-pure.

## Why it matters for ras-commander

**Archival operations.** These read entire plans: ras2cng archives, bulk GeoParquet export, model
fingerprinting and revision hashing, and batch post-processing of many large plans.
- Reading a 582 MB LWI plan end to end took 7.1 s warm (10.5 s cold) through h5py, against
  2.4 s (5.1 s) with parallel Rust.
- Across a model library of hundreds of plans, that's the difference between hours and minutes.

**Mesh results extraction is slow in many cases.** `HdfResultsMesh` time series and
many-cell or face hydrographs decompress the whole (time × cells) dataset, even for one cell,
because HEC-RAS stores one time step per chunk. Parallel decompression cuts that 3.6–4.8×.

**The HDF decode isn't the only cost.** On BaldEagle p05:
- `HdfMesh.get_mesh_cell_polygons` takes about 1.2 s for 24,718 cells;
- the raw arrays it needs take about 10 ms to read.

The rest is Python polygon assembly. A Rust backend should therefore return *assembled* results
(cell polygons as WKB or GeoArrow, joined result columns), not only raw arrays. That's where the
largest end-to-end gains are.

## Recommendation

1. **Keep h5py as the default and for every write.** ras-commander opens HDF files for writing
   in 41 places across 20 modules.
2. **Add an optional `ras-commander[fast-hdf]` extra:**
   - a small PyO3/maturin wheel (abi3, for Windows, macOS and Linux) with a read-only,
     task-level API;
   - h5py as the fallback whenever the extra is missing or meets an unsupported structure.
3. **First targets:**
   - `HdfResultsMesh` full and multi-cell time series;
   - face and cell hydrographs;
   - summary arrays;
   - cell-polygon assembly;
   - read-everything fingerprinting;
   - ras2cng bulk export.
4. **Gate every path behind a conformance suite** against h5py raw bytes and ras-commander
   outputs on the fixture set. Ship a path only once it passes.

See [BENCHMARKS.md](BENCHMARKS.md), [CONFORMANCE.md](CONFORMANCE.md) and
[DESIGN_OPTIONS.md](DESIGN_OPTIONS.md).

## Related work

- **Upstream reader fix:** [roteiro-gis/netcdf-rust#95](https://github.com/roteiro-gis/netcdf-rust/pull/95)
  fixes the two `hdf5-reader` bugs that made HEC-RAS files unreadable.
- **terrio:** [opengeos/terrio](https://github.com/opengeos/terrio) is a pure-Rust GDAL-like
  I/O library by RustGIS's maintainer.
  - It uses the same reader; [opengeos/terrio#98](https://github.com/opengeos/terrio/pull/98)
    builds it against the fix.
  - A native HEC-RAS vector driver for terrio (and through it RustGIS) is in development. It will
    share this reader and this conformance suite.
- **Python package:** terrio's Python package is not a substitute for h5py in ras-commander. Its
  model is GDAL-like rasters, with no compound tables, typed attributes, slicing or edits.
