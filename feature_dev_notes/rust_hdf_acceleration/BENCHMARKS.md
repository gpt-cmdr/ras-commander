# Benchmarks: pure-Rust HDF5 readers against h5py on HEC-RAS files

Measured 2026-10-17 on clb-t3, a 6-vCPU LXC container with 32 GB and local NVMe ext4.

## Readers

| Name | What it is |
|---|---|
| **h5py** | h5py 3.16.0, numpy 2.5.4, libhdf5 2.0.0 (PyPI wheel), CPython 3.11. |
| **reader** | `hdf5-reader` 0.9.1 with the compound-name fix (netcdf-rust#95). Default flate2 decompressor (miniz_oxide). |
| **reader-par** | The same, using `read_array_parallel` / `read_slice_parallel` (rayon, 6 threads). |
| **pure** | `hdf5-pure` 0.47.0 with `File::open_streaming`. |
| **`-zrs`** | Built with flate2's pure-Rust zlib-rs decompressor. |

## Method

- **Operations** mirror `ras_commander/hdf/*.py` on `origin/main` `f7aa0b8`:
  - **open_list:** the compound `Geometry/2D Flow Areas/Attributes`, name and cell count, as `get_mesh_area_names` reads it.
  - **geom:** the arrays `get_mesh_cell_polygons` reads.
  - **maxws:** the summary `Maximum Water Surface`.
  - **ws_step:** one time step, `ds[t]`.
  - **ws_full:** the full time series, `ds[:]`.
  - **cell_ts:** one cell's whole series, `ds[:, c]`.
  - **tds:** the `Time Date Stamp` strings.
  - **readall:** read every unique dataset, as fingerprinting does.
- **Runs:** a fresh process per run, as ras-commander opens files per call. Python start-up and imports (80–170 ms) are excluded. Median of 5, with libraries interleaved.
- **Warm vs cold:** "warm" means the file is in the page cache; for "cold", its pages are evicted with `posix_fadvise(DONTNEED)` before each run.
- **Correctness:** every library returned identical checksums on every read.
- **Noise:** other builds ran throughout (load average 6–20). Treat the numbers as ±10–20%; the parallel numbers are probably understated.

## LI.p01.hdf: 582 MB, LWI Little River, HEC-RAS 6.3.1, 373,395 cells × 59 steps

Times in ms, warm / cold.

| Operation | h5py | Best Rust, one thread | reader-par (zrs) | Speed-up vs h5py |
|---|---|---|---|---|
| open_list | 1.53 / 3.23 | 0.12 / 1.39 | – | 13× / 2.3× |
| geom | 96.4 / 114 | 77.9 / 112 | 38.6 / 87.6 | 1.2×; parallel 2.5× warm |
| maxws | 13.1 / 18.3 | 10.1 / 12.2 | 7.37 / 10.2 | 1.3×; parallel 1.8× |
| ws_step | 11.3 / 12.8 | 7.57 / 10.3 | – | 1.5× / 1.2× |
| **ws_full** | **487 / 609** | 396 / 483 | **131 / 153** | 1.2×; **parallel 3.8× / 4.0×** |
| **cell_ts** | **486 / 558** | 393 / 463 | **111 / 135** | 1.2×; **parallel 4.4× / 4.1×** |
| tds | 1.16 / 2.80 | 0.14 / 1.26 | – | 8× / 2.2× |
| **readall** (1.02 GB) | **7,050 / 10,473** | 4,445 / 5,283 | **2,441 / 5,108** | **1.6× / 2.0×; parallel 2.9× / 2.1×** |

## BaldEagleDamBrk.p05.hdf: 90 MB, HEC-RAS 7.0, 26,265 cells × 433 steps

| Operation | h5py | Best Rust, one thread | reader-par (zrs) |
|---|---|---|---|
| ws_full | 256 / 383 | 222 / 327 | 70.8 / 85.0 |
| cell_ts | 247 / 366 | 202 / 319 | 69.2 / 76.3 |
| readall | 904 / 1,192 | 681 / 925 | 338 / 442 |

## Peak memory (LI.p01, warm)

| Read | h5py | hdf5-reader | hdf5-reader parallel | hdf5-pure |
|---|---|---|---|---|
| ws_full | 289 MiB | 156 MiB | 163 MiB | 91 MiB |
| readall | 1,396 MiB | 550 MiB | 969 MiB | 237 MiB |

The h5py figures include about 35–40 MiB for Python, numpy and h5py.

## Notes

- **Parallel decompression only helps large, many-chunk datasets.** On small geometry arrays, thread start-up makes it slower. A backend should choose per dataset.
- **Metadata reads are 5–40× faster,** but save only milliseconds per call.
- **Correction:** an earlier study that reported hdf5-pure as 2× faster than h5py read the files over a CIFS share. On local disk the two are level in a single thread; zlib-rs and parallelism are what make the difference.
