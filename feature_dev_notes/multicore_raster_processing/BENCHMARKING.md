# Raster performance benchmarking

## Benchmark integrity correction

The first matrix runner set `GDAL_CACHEMAX` (and, for StoreMap rows,
`GDAL_NUM_THREADS`) only in the parent Python environment. The child-scoped API
rebuilt/sanitized the helper environment, so those labels did not reach the
child. The historical StoreMap cache/thread rows, Spring cache64 rows, and
direct-VRT cache64/cache256 rows below are invalid for cache or StoreMap-thread
conclusions. The corrected runner constructs typed performance/write options,
records their full effective values, and has propagation tests. VRT one-thread
versus `ALL_CPUS` rows remain valid because that argument was passed directly.

## Purpose and scope

This benchmark characterizes the new StoreMap and terrain-processing controls
on local fixed storage and mapped network storage. Storage location is an
experimental dimension only; no scratch, staging, redirection, or copy-back
feature is proposed.

The harness profiles the real public ras-commander functions and real HEC-RAS
projects. It records:

- wall time and process-tree CPU seconds;
- peak working set and private commit;
- minimum available physical memory;
- process/thread counts;
- read/write bytes and operation counts per process;
- mean bytes per read and write;
- interval CPU, I/O throughput, IOPS, request-size, and memory timelines;
- host-wide disk throughput, IOPS, busy time, latency, and network rates;
- inferred native StoreMap, output-growth, GDAL translation, and overview
  phases;
- Python `cProfile` output;
- decoded raster pixel hashes and spatial metadata;
- HDF dataset-value signatures;
- source `.rasmap` and result-HDF preservation checks.

## Test host and storage

| Item | Value |
|---|---|
| OS | Windows |
| HEC-RAS mapping version | 7.0 |
| Logical CPUs | 8 |
| Physical memory | 34,139,926,528 bytes, 31.8 GiB |
| Local path | `C:` fixed NTFS |
| Local device | PNY CS2241 2TB SSD, NVMe |
| Local occupancy during final runs | approximately 96 to 97 percent used |
| Network path | mapped `H:` |
| Network target | `\\192.168.3.20\CLB-Engineering` over SMB |
| Network occupancy | approximately 58 percent used |

The nearly full local NVMe is a material limitation. Results compare the two
paths as they existed on this workstation; they are not generic NVMe-versus-SMB
claims.

## Fixtures

### Bald Eagle

The matched local/network copies contain the same computed project and
Terrain50 source files. This is the fast functional and settings fixture.

- final manifest:
  `scripts/benchmarks/fixtures/bald_eagle_raster_profile_matrix.json`
- run instances: 45
- final raw reports:
  `working/raster_profile_matrix_20260719/reports_clean_v2/`
- aggregate JSON/CSV/Markdown:
  `working/raster_profile_matrix_20260719/reports_clean_v2/matrix_summary.*`

### Spring River

The local and network project copies contain 82 files and 6,651,206,528 bytes
each. Plan 02, `100Yr`, uses one active terrain VRT with one source raster. The
terrain is 28,916 by 26,316 Float32 cells. Spring is therefore a large-grid and
memory-pressure fixture, not a multi-source VRT consolidation fixture.

- fixture metadata:
  `scripts/benchmarks/fixtures/spring_river_store_maps.json`
- selected matrix:
  `scripts/benchmarks/fixtures/spring_river_raster_profile_matrix.json`
- run instances: 6
- final raw reports:
  `working/raster_profile_matrix_20260719/spring_reports_clean_v1/`
- aggregate JSON/CSV/Markdown:
  `working/raster_profile_matrix_20260719/spring_reports_clean_v1/matrix_summary.*`

The Spring matrix intentionally excludes forced two-helper execution. An
earlier stress run drove system available memory to 3.17 GiB and was stopped.

## Reproduction

Run from the isolated feature worktree with no other raster matrix active:

```powershell
.venv\Scripts\python.exe scripts/benchmarks/run_raster_profile_matrix.py `
  --manifest scripts/benchmarks/fixtures/bald_eagle_raster_profile_matrix.json `
  --output-root working/raster_profile_matrix_20260719/reports_clean_v2 `
  --continue-on-error

.venv\Scripts\python.exe scripts/benchmarks/run_raster_profile_matrix.py `
  --manifest scripts/benchmarks/fixtures/spring_river_raster_profile_matrix.json `
  --output-root working/raster_profile_matrix_20260719/spring_reports_clean_v1 `
  --continue-on-error
```

The runner uses `.matrix-running.json` with a live PID check and exclusive file
creation. A second matrix targeting the same result root fails immediately.

## Public self-profiling workflow

The benchmark scripts remain useful for controlled matrices, but ordinary
users no longer need them to collect comparable measurements. The production
APIs write the same decision-critical metrics:

```python
from ras_commander import RasProcess, StoreMapPerformanceOptions

estimate = RasProcess.estimate_store_map_resources(
    "02",
    performance=StoreMapPerformanceOptions(max_workers=None),
)

profile = RasProcess.profile_store_maps(
    "02",
    output_path="working/profile/maps",
    report_path="working/profile/store-maps.json",
    performance=StoreMapPerformanceOptions(
        max_workers=None,
        gdal_cachemax_mb=256,
    ),
)
```

For VRT consolidation, use `GeoTiffWriteOptions` with
`RasTerrain.profile_vrt_to_tiff()`. Each report contains elapsed time,
process-tree CPU and I/O, physical/private memory, Windows commit headroom,
interval samples, inferred phase summaries, and a decoded-pixel hash. The
samples expose `tree_cpu_percent` (100 percent per logical CPU), whole-machine
CPU percent, process-attributable file throughput and IOPS, mean request size,
and host-wide disk and network load. Pixel hashing reads fixed 256-row windows
rather than native TIFF blocks, so it stays comparable when the tested tile
size changes.

Process file-I/O counters include cached and SMB transfers and are the best
portable attribution to the RAS/GDAL process tree. Host disk and network
counters are machine-wide and may include unrelated work. They provide useful
corroboration, but exact device queue depth, cache misses, and SMB/server
latency still require ETW, Performance Monitor, or storage-side telemetry.

The complete settings matrix and selection procedure are in
`examples/730_raster_processing_performance_profiling.ipynb`. Both heavy run
switches are false in the committed notebook.

The final public-API Bald Eagle smoke selected two helpers from current memory
and commit headroom, completed WSE/Depth/Velocity in 7.923 seconds, observed
two simultaneous helper processes, peaked at 1,621.7 MiB private bytes, and
retained 11,211 MiB of commit headroom. Its report is under the ignored path
`working/raster_profile_matrix_20260719/public_api_smoke_20260719_1625/`.

The public Spring River estimate inspected 760,953,456 terrain cells and
estimated 12,124 MiB per helper. With 8,139 MiB reserved, the current 17,753
MiB physical availability and 16,120 MiB commit headroom permit no additional
parallel helper, so `selected_workers` remains one and the estimate carries a
headroom warning. An automatic run with enforced policy checks that warning
again before launching even the one selected helper; wait for headroom or use
`memory_policy="warn"` only after consciously accepting the measured risk.

The public VRT profiler measured the legacy-compatible LZW case at 8.793
seconds and 1,382.7 MiB peak private bytes. A 512-pixel LZW tile,
`ALL_CPUS`, and 256 MiB GDAL cache case completed in 7.158 seconds and 937.7
MiB. Their fixed-row decoded-pixel hashes match exactly. HEC-RAS 7.0's pinned
GDAL build rejected ZSTD, demonstrating why configuration failures are now
written as structured reports instead of assuming every codec is present.

### Public interval-profiler validation

The finalized interval profiler was then exercised through the public APIs.
The ignored JSON reports are:

- `working/raster_profile_matrix_20260719/public_interval_profile_spring_depth_20260719/profile.json`;
- `working/raster_profile_matrix_20260719/public_interval_profile_vrt_20260719/profile.json`;
- `working/raster_profile_matrix_20260719/public_interval_profile_bald_20260719/profile.json`.

The Spring Depth run used one helper and a conscious `memory_policy="warn"`
because the conservative estimate reported insufficient headroom for its 12.1
GiB estimate plus the 8.1 GiB reserve. The measured peak was 9,119.7 MiB
private, minimum physical availability was 9,205 MiB, and minimum commit
headroom was 6,551 MiB. This was a profiling exception, not a recommended
automatic scheduling setting.

| Spring Depth stage | Seconds | Effective logical CPUs | 8-CPU utilization | Process write MiB/s | Process write IOPS | Mean process write | Peak private MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| Native StoreMap/TiffAssist helper | 86.864 | 2.71 | 33.9% | 1.33 | 134.5 | 10.1 KiB | 9,119.7 |
| GDAL overviews | 15.071 | 1.15 | 14.4% | 12.66 | 668.6 | 19.4 KiB | 1,889.7 |
| Python/georeference/finalize | 5.816 | 0.99 | 12.4% | 144.25 | 9.6 | 15.0 MiB | 626.9 |

The native stage's host-wide physical-disk counters averaged 10.41 MiB/s and
236.6 write IOPS while the process itself issued only 1.33 MiB/s in 10.1 KiB
requests. Neither throughput value approaches NVMe bandwidth. The combination
of low whole-machine CPU, low physical throughput, and small process writes is
consistent with serialization, locked reads, per-tile work, and write latency;
it is not a bulk-storage-bandwidth ceiling.

The 512-tile, `ALL_CPUS`, 256 MiB-cache VRT profile showed the contrast:

| VRT stage | Seconds | Effective logical CPUs | 8-CPU utilization | Process write MiB/s | Process write IOPS | Mean process write |
|---|---:|---:|---:|---:|---:|---:|
| GDAL translate/TIFF write | 2.767 | 1.97 | 24.6% | 76.01 | 1,233.8 | 63.1 KiB |
| GDAL overviews | 3.281 | 1.13 | 14.1% | 28.28 | 516.0 | 56.1 KiB |

Windows `psutil` on this host does not expose physical-disk busy time, so that
field is correctly `null`; host throughput/IOPS and process-attributable
counters remain available. The public API also fixed relative VRT/output paths
to absolute paths before launching GDAL, whose working directory is the
HEC-RAS installation rather than the caller's directory.

The interval-profiler regression selection completed with 106 passes and one
data-dependent skip. After the canonical `RasMap.store_all_maps()` API, copied
TiffAssist experiment, and HTML decision-report tests were added, the expanded
final focused selection completed with 184 passes and one data-dependent skip.
The final repository-wide comparison completed with 1,574 passes, 68 skips, 23
unrelated failures, and two setup errors caused by missing pythonnet. No
raster-performance test is in the failure/error list. The JUnit record is under
`working/raster_profile_matrix_20260719/full_suite_after_interval_profile.xml`.

## Rejected measurements and observer correction

The original exploratory result root was invalid because two launchers
overlapped after a shell timeout left the first child running. It is not used.

The first isolated result root then exposed an observer effect: the monitor
recursively enumerated the network output folder every 0.1 seconds. One SMB
enumeration blocked in `nt.scandir` for approximately 35 seconds after native
work completed, producing a false 44.17-second worker-2 result. The monitor was
changed to scan only direct children of explicitly watched output directories.
The final paired network worker-2 runs were 9.357 and 9.256 seconds. Only
`reports_clean_v2` is authoritative.

## Primary findings

### CPU and storage utilization

The original controlled reports already prove that the Spring process is not
literally single-core. They also show why lower memory alone does not guarantee
more speed.

| Run | CPU seconds / wall second | 8-core machine CPU | Read MiB/s | Write MiB/s | Read IOPS | Write IOPS |
|---|---:|---:|---:|---:|---:|---:|
| Bald auto-3 local | 3.69 cores | 46.2% | 40.9 | 21.2 | 3,138 | 931 |
| Bald auto-3 network | 3.21 cores | 40.2% | 20.1 | 3.4 | 2,691 | 781 |
| Spring all-3 serial local | 2.25 cores | 28.1% | 13.5 | 4.3 | 729 | 132 |
| Spring all-3 serial network | 2.03 cores | 25.4% | 10.0 | 1.6 | 661 | 120 |

For Spring local, the inferred native-helper interval occupied 266.6 seconds
and accumulated 650.8 CPU seconds, or about 2.44 logical cores while active.
The three overview children occupied 45.2 seconds and accumulated 43.3 CPU
seconds, about 0.96 cores. The full job averaged only 2.25 of 8 logical cores.
That pattern is consistent with internal parallel producers feeding a locked,
serialized single-consumer TIFF path, followed by mostly one-core overview
work. The consumer drains a `ConcurrentBag`, so serialization does not imply
tile-number ordering.

The matched Spring network job performed essentially the same native work but
took 32.4 seconds longer and averaged less CPU. The local/network difference at
similar CPU seconds and process operation counts is direct evidence of storage
or SMB latency entering the serialized path. Bald auto-3 overlaps three native
helpers and therefore reaches 46.2 percent whole-machine CPU, demonstrating
that map-level process parallelism works when memory permits.

These stage CPU values were reconstructed from the original process and phase
reports. The public profiler now records the interval CPU, throughput, IOPS,
host disk load, and host network load directly in each phase summary so future
runs do not require reconstruction. Phase rows cover the whole process tree;
with concurrent map helpers, intervals can contain mixed native and overview
work and the active-descendant label is therefore approximate.

### StoreMap parallelism

The repeat-pair medians for three Bald Eagle maps were:

| Storage | Serial median | Two helpers median | Auto, three helpers | Auto speedup | Auto wall reduction |
|---|---:|---:|---:|---:|---:|
| Local | 9.167 s | 8.261 s | 5.156 s | 1.778x | 43.8% |
| Network | 11.140 s | 9.307 s | 6.179 s | 1.803x | 44.5% |

Two helpers provide only 1.110x local and 1.197x network speedup because the
third map still runs in a second wave. Three independent map helpers are the
natural concurrency level when memory permits.

### Storage effect on real functions

On Bald Eagle, matched network runs were approximately 13 to 23 percent slower
than local runs for the primary StoreMap and VRT comparisons. On Spring, single
Depth timings varied enough that network was faster in the default pair but
slower in the cache-limited pair. The three-map aggregate was more stable:
328.452 seconds local versus 360.887 seconds network, a 9.9 percent network
penalty. Spring values are single samples and must not be generalized without
repeats.

### Native TIFF writes

For three Bald Eagle maps, TiffAssist helper processes made approximately 1,522
writes per map with mean write sizes of 3.0 to 4.7 KiB. A serial helper produced
4,512 writes averaging 3.9 KiB. Each `gdaladdo` child instead averaged roughly
17 to 25 KiB per write on these small outputs.

Spring amplifies the pattern. One Depth helper made 11,714 writes averaging
10.1 KiB. The three-map helper made 35,088 writes averaging 9.3 KiB. Default
`gdaladdo` used about 2,700 to 2,840 writes per map averaging roughly 31 to 33
KiB.

For the general GDAL VRT-to-TIFF path, `gdal_translate` and `gdaladdo` averaged
approximately 60 to 63 KiB per write. That request size is much more favorable
for SMB than the native StoreMap writer pattern.

### Isolated storage request-size test

`benchmark_storage_io.py` wrote and flushed one 256 MiB file per request size,
then performed an immediate warm-cache read. Windows filesystem caching was
active and there was one `fsync` after the full file, so this is a comparative
buffered-write test, not an uncached device benchmark.

| Request size | Local write MiB/s | Network write MiB/s | Local operations | Network operations |
|---:|---:|---:|---:|---:|
| 4 KiB | 551.4 | 11.6 | 65,536 | 65,536 |
| 16 KiB | 1,066.5 | 46.9 | 16,384 | 16,384 |
| 64 KiB | 1,279.9 | 118.9 | 4,096 | 4,096 |
| 1 MiB | 1,395.4 | 242.1 | 256 | 256 |
| 8 MiB | 1,299.9 | 349.2 | 32 | 32 |

The SMB path improved by about 10.3x between 4 KiB and 64 KiB requests and
30.2x between 4 KiB and 8 MiB requests. This independently supports the
TiffAssist small-write diagnosis.

Reports:

- `working/raster_profile_matrix_20260719/storage_io/local_report.json`
- `working/raster_profile_matrix_20260719/storage_io/network_report.json`

### GDAL cache behavior (corrected runner)

The original cache-labeled rows later in this document remain invalid because
their caps did not reach the child. These fresh one-sample runs use typed
options, and every JSON report records the effective child setting:

| Function and setting | Storage | Seconds | CPU s | Peak private | Read ops | Write ops |
|---|---|---:|---:|---:|---:|---:|
| StoreMaps, 64 MiB, one GDAL thread | Local | 9.813 | 19.33 | 1.11 GiB | 23,052 | 5,396 |
| StoreMaps, 256 MiB, `ALL_CPUS` | Local | 9.379 | 18.20 | 1.14 GiB | 13,504 | 4,748 |
| StoreMaps, 64 MiB, one GDAL thread | SMB | 12.390 | 19.59 | 1.13 GiB | 23,162 | 5,396 |
| StoreMaps, 256 MiB, `ALL_CPUS` | SMB | 10.720 | 17.80 | 1.19 GiB | 13,374 | 4,762 |
| Direct VRT, 64 MiB, `ALL_CPUS` | Local | 6.490 | 9.70 | 0.69 GiB | 24,352 | 6,169 |
| Direct VRT, 256 MiB, `ALL_CPUS` | Local | 6.220 | 8.70 | 0.88 GiB | 15,364 | 5,352 |

All four StoreMap runs produced the same three decoded-pixel hashes and
preserved both the `.rasmap` and plan HDF byte-for-byte. Both VRT runs produced
pixel hash `bc7fc8d5dbe4...` with identical dimensions, CRS, transform, and
NoData. The StoreMap pairs change both cache and thread count, so they describe
tested configurations rather than isolate cache. The VRT pair isolates 64
versus 256 MiB: 256 MiB was 4.2 percent faster and used fewer operations but
about 0.19 GiB more private memory in this single sample. This is insufficient
to choose a default; repeat 64, 128, 256, and 512 MiB cases before doing so.

Raw corrected reports are under
`working/raster_profile_matrix_20260719/corrected_settings_v2/`. A corrected
Spring cache rerun was attempted separately, but project initialization did not
finish within 15 minutes: no native helper launched and no output or report was
produced. That attempt is a setup timeout, not a TIFF/cache measurement. The
historical Spring cache rows therefore remain invalid for cache conclusions.

### GDAL threading and compression

For Bald Eagle LZW VRT conversion with overviews:

| Storage | One thread | `ALL_CPUS` | Speedup | Wall reduction |
|---|---:|---:|---:|---:|
| Local | 8.562 s | 6.708 s | 1.276x | 21.7% |
| Network | 10.319 s | 8.139 s | 1.268x | 21.1% |

Terrain HDF creation did not materially improve with `ALL_CPUS`: local was
8.730 versus 8.711 seconds, and network was 9.312 versus 9.206 seconds. The
Python profile shows that this public function waits for a native terrain
subprocess; its dominant stage is not the same threaded GDAL translation path.

DEFLATE with `ALL_CPUS` and overviews was much slower than LZW in this fixture:
14.701 versus 6.708 seconds local and 15.850 versus 8.139 seconds network. It
used about 34 CPU seconds compared with about 10 for LZW, while creating smaller
files. This is a space/CPU tradeoff, not a default performance win.

Removing overviews reduced LZW one-thread time from 8.562 to 5.164 seconds
locally and from 10.319 to 5.789 seconds over SMB. Overviews remain necessary
for the normal mapped product, so suppression is a diagnostic comparison rather
than a production default.

### Python profile

`cProfile` consistently attributes the outer duration to waits on helper or
GDAL subprocesses:

- Spring three-map local: 312.34 of 328.43 seconds in the StoreMap helper
  subprocess call;
- terrain HDF: 8.67 of 8.70 seconds in the native subprocess call;
- VRT conversion: 6.67 of 6.70 seconds in the two GDAL subprocess calls.

The Python orchestration is not the computational bottleneck. `cProfile` cannot
inspect native executables, which is why process-tree telemetry and decompiled
call tracing are required.

## Full controlled result table

### Bald Eagle, 45 runs

| Run | Repeat | Seconds | CPU s | Peak private GiB | Min avail GiB | Read ops | Write ops | Helpers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `store_depth_serial_local` | 1 | 3.618 | 6.438 | 1.11 | 16.72 | 6,345 | 1,607 | 1 |
| `store_depth_serial_network` | 1 | 4.463 | 7.281 | 1.10 | 16.84 | 6,361 | 1,624 | 1 |
| `store_all3_serial_local` | 1 | 8.946 | 18.703 | 1.18 | 16.57 | 13,270 | 4,744 | 1 |
| `store_all3_serial_local` | 2 | 9.387 | 18.719 | 1.24 | 16.57 | 13,580 | 4,763 | 1 |
| `store_all3_serial_network` | 1 | 11.036 | 19.188 | 1.17 | 16.78 | 13,774 | 4,791 | 1 |
| `store_all3_serial_network` | 2 | 11.244 | 18.812 | 1.17 | 16.64 | 13,598 | 4,768 | 1 |
| `store_all3_workers2_local` | 1 | 8.232 | 20.297 | 1.62 | 16.15 | 16,324 | 4,805 | 2 |
| `store_all3_workers2_local` | 2 | 8.289 | 19.062 | 1.58 | 16.27 | 16,425 | 4,819 | 2 |
| `store_all3_workers2_network` | 1 | 9.357 | 19.984 | 1.62 | 16.28 | 16,656 | 4,841 | 2 |
| `store_all3_workers2_network` | 2 | 9.256 | 21.234 | 1.64 | 16.32 | 16,636 | 4,836 | 2 |
| `store_all3_auto_local` | 1 | 5.156 | 19.047 | 2.08 | 15.70 | 16,179 | 4,799 | 3 |
| `store_all3_auto_network` | 1 | 6.179 | 19.859 | 2.16 | 15.80 | 16,629 | 4,823 | 3 |
| `store_serial_cache64_gdal1_local` (invalid setting label) | 1 | 8.809 | 18.062 | 1.07 | 16.91 | 23,114 | 5,389 | 1 |
| `store_serial_cache64_gdal1_network` (invalid setting label) | 1 | 10.674 | 19.172 | 1.06 | 17.05 | 23,003 | 5,390 | 1 |
| `store_serial_cache256_gdalall_local` (invalid setting label) | 1 | 8.285 | 16.422 | 1.18 | 16.88 | 13,255 | 4,747 | 1 |
| `store_serial_cache256_gdalall_network` (invalid setting label) | 1 | 10.800 | 18.938 | 1.20 | 16.93 | 13,470 | 4,769 | 1 |
| `store_workers2_memory4g_reserve8g_local` | 1 | 8.119 | 20.047 | 1.59 | 16.35 | 16,249 | 4,788 | 2 |
| `store_workers2_memory8g_reserve8g_local` | 1 | 9.716 | 18.750 | 1.21 | 16.69 | 13,340 | 4,742 | 1 |
| `store_all3_serial_no_georef_local` | 1 | 8.771 | 16.875 | 1.22 | 16.74 | 11,218 | 4,726 | 1 |
| `timesteps_depth_serial_local` | 1 | 3.467 | 6.047 | 1.11 | 16.94 | 6,210 | 1,586 | 1 |
| `timesteps_depth_serial_network` | 1 | 4.276 | 7.188 | 1.12 | 16.99 | 6,206 | 1,589 | 1 |
| `timesteps_all3_workers2_local` | 1 | 7.311 | 17.984 | 1.49 | 16.54 | 16,531 | 4,762 | 2 |
| `timesteps_all3_workers2_network` | 1 | 8.510 | 20.156 | 1.60 | 16.47 | 16,657 | 4,781 | 2 |
| `store_all_plans_depth_serial_local` | 1 | 10.469 | 18.578 | 1.18 | 16.85 | 18,892 | 4,829 | 1 |
| `store_all_plans_depth_serial_network` | 1 | 13.694 | 20.266 | 1.13 | 16.87 | 18,954 | 4,842 | 1 |
| `store_all_plans_all3_workers2_local` | 1 | 23.683 | 60.547 | 1.65 | 16.52 | 49,899 | 14,435 | 2 |
| `store_all_plans_all3_workers2_network` | 1 | 28.051 | 58.797 | 1.58 | 16.63 | 50,070 | 14,480 | 2 |
| `terrain_hdf_threads1_local` | 1 | 8.730 | 14.906 | 0.81 | 17.26 | 8,766 | 2,435 | 0 |
| `terrain_hdf_allcpus_local` | 1 | 8.711 | 14.609 | 0.78 | 17.19 | 8,769 | 2,433 | 0 |
| `terrain_hdf_threads1_network` | 1 | 9.312 | 15.312 | 0.81 | 17.22 | 8,565 | 2,423 | 0 |
| `terrain_hdf_allcpus_network` | 1 | 9.206 | 15.844 | 0.79 | 17.40 | 8,582 | 2,432 | 0 |
| `terrain_convenience_threads1_local` | 1 | 8.912 | 15.031 | 0.85 | 17.13 | 9,605 | 2,435 | 0 |
| `terrain_convenience_allcpus_local` | 1 | 8.736 | 15.109 | 0.79 | 17.09 | 9,620 | 2,446 | 0 |
| `terrain_convenience_threads1_network` | 1 | 9.007 | 15.281 | 0.82 | 17.26 | 9,436 | 2,434 | 0 |
| `terrain_convenience_allcpus_network` | 1 | 9.051 | 15.094 | 0.82 | 17.30 | 9,442 | 2,431 | 0 |
| `vrt_lzw_threads1_overviews_local` | 1 | 8.562 | 9.062 | 1.35 | 16.77 | 6,953 | 5,217 | 0 |
| `vrt_lzw_allcpus_overviews_local` | 1 | 6.708 | 9.953 | 1.35 | 16.52 | 7,067 | 5,219 | 0 |
| `vrt_lzw_threads1_no_overviews_local` | 1 | 5.164 | 5.594 | 1.34 | 16.44 | 1,607 | 3,609 | 0 |
| `vrt_deflate_allcpus_overviews_local` | 1 | 14.701 | 34.188 | 1.34 | 16.41 | 7,234 | 3,518 | 0 |
| `vrt_lzw_allcpus_cache64_local` (invalid setting label) | 1 | 5.821 | 8.312 | 0.69 | 16.97 | 24,137 | 5,707 | 0 |
| `vrt_lzw_allcpus_cache256_local` (invalid setting label) | 1 | 6.012 | 8.953 | 0.88 | 16.71 | 15,379 | 5,667 | 0 |
| `vrt_lzw_threads1_overviews_network` | 1 | 10.319 | 9.641 | 1.34 | 16.41 | 7,254 | 5,256 | 0 |
| `vrt_lzw_allcpus_overviews_network` | 1 | 8.139 | 9.578 | 1.35 | 16.57 | 7,254 | 5,256 | 0 |
| `vrt_lzw_threads1_no_overviews_network` | 1 | 5.789 | 5.344 | 1.34 | 16.68 | 1,607 | 3,609 | 0 |
| `vrt_deflate_allcpus_overviews_network` | 1 | 15.850 | 34.344 | 1.34 | 16.75 | 7,254 | 3,518 | 0 |

### Spring River, 6 runs

| Run | Seconds | CPU s | Peak private GiB | Min avail GiB | Read ops | Write ops | Helpers |
|---|---:|---:|---:|---:|---:|---:|---:|
| `spring_depth_serial_local` | 135.677 | 264.828 | 8.67 | 9.31 | 82,693 | 14,609 | 1 |
| `spring_depth_serial_network` | 123.265 | 250.531 | 7.91 | 10.42 | 81,918 | 14,612 | 1 |
| `spring_depth_cache64_gdal1_local` (invalid setting label) | 117.234 | 252.734 | 10.01 | 8.20 | 215,228 | 23,142 | 1 |
| `spring_depth_cache64_gdal1_network` (invalid setting label) | 127.465 | 253.859 | 5.60 | 12.43 | 214,544 | 23,172 | 1 |
| `spring_all3_auto_local` | 328.452 | 738.250 | 9.75 | 8.44 | 239,369 | 43,292 | 1 |
| `spring_all3_auto_network` | 360.887 | 733.000 | 6.61 | 11.56 | 238,637 | 43,298 | 1 |

## Copied TiffAssist parallel-tile matrix

The final copied-assembly experiment adds exact native-writer markers that the
portable process profiler cannot infer: tile snapshot, queue waits,
round/statistics, byte copy, Deflate, raw commit, allocations, queue high-water
marks, logical writes, and underlying stream writes.

### Writer-only scaling

The 8192 by 8192 writer-only fixture reused 16 prepared input tiles so the
foreground generator did not starve TiffAssist. The installed-original median
was 2.435 seconds. Parallel pipeline results were 1.832 seconds at two workers,
1.095 at four, and a 0.815-second median at eight: 66.5 percent faster than the
original. One worker was slower at 3.394 seconds because it paid snapshot,
queue, and private-encoder overhead without parallel compression.

At eight workers, queue depths 1 and 2 were fastest and retained the fewest
tiles. Depth 2 took 0.776 seconds with 13 maximum owned tiles. Depth 32 took
0.813 seconds, retained 73 tiles, and used more private memory.

A five-repeat 64 KiB–64 MiB sweep replaced the earlier one-sample comparison.
The fastest median was 0.747 seconds at 2 MiB. The medians at 4, 8, 16, 32,
and 64 MiB were 0.847, 0.818, 0.833, 0.835, and 0.854 seconds. The 64 MiB
request used about 100.0 MiB RSS versus 71.8 MiB at 2 MiB. The runner now
proposes queue depth 2 and 2 MiB; the copied assembly keeps its conservative
256 KiB fallback until the experiment is explicitly configured.

### Spring River plan 02 Depth Max

| Case | Total s | Native StoreMap s | Native cores | Write IOPS | Mean write | Overview s | Overview cores | Peak private GiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Installed original | 112.21 | 95.62 | 2.84 | 50.7 | 22.4 KiB | 16.17 | 1.36 | 9.32 |
| Batched, workers off | 110.31 | 93.90 | 2.91 | 5.4 | 224.5 KiB | 15.64 | 1.35 | 10.68 |
| Batched, one worker | 108.78 | 92.38 | 2.91 | 5.2 | 224.6 KiB | 15.78 | 1.36 | 6.86 |
| Batched, eight workers | 109.64 | 93.24 | 2.87 | 5.2 | 223.5 KiB | 15.87 | 1.34 | 9.51 |

The one-worker case coalesced 11,715 logical LibTiff writes into 494 physical
writes and was 3.1 percent faster end to end. One and eight workers had nearly
identical pipeline walls, 84.28 and 84.92 seconds. Eight workers reduced
input-queue wait from 12.53 to 2.55 seconds, but aggregate Deflate calls were
only about 25 seconds and raw destination commit only 0.49–0.66 seconds.

This is direct evidence that Spring is producer-paced: terrain/HDF locking,
map-value production, and intermittent tile availability limit the writer.
Parallel Deflate is real but cannot consume work that has not been produced.
The later histogram reread remains inside RASMapper, and overview generation
remains a separate roughly 1.35-core, 15.6–16.2-second phase.

All four outputs shared decoded pixel SHA-256
`aa74abd3e99871adf9ec2c945460ef290dd0c6ed7ad80d51c9fee84f65fc61e1`
and equivalent layout, CRS, transform, NoData, compression, histogram, and
numeric statistics. Source HDF hashes were unchanged.

Raw reports:

```text
working/native_tiff_experiments/spring-river-parallel-v2/
working/native_tiff_experiments/parallel_writer_only_8192/
working/native_tiff_experiments/parallel_writer_only_8192_trial2/
working/native_tiff_experiments/parallel_writer_only_8192_trial3/
working/native_tiff_experiments/parallel_writer_queue_8192/
working/native_tiff_experiments/parallel_writer_batch_8192/
working/native_tiff_experiments/extended_batch_8192_r1/ through r5/
```

## Decision report

`scripts/benchmarks/generate_raster_performance_report.py` converts the raw
JSON into a self-contained HTML report with inline SVG figures and a normalized
JSON sidecar. The current report includes batch latency/memory/write operations,
paired real StoreMap speedups, Spring River stage/timeline CPU-memory-I/O, and
local/network request-size throughput. It also includes the previously missing
like-for-like scaling context: three-product map-process parallelism, threaded
VRT translation, terrain-HDF non-scaling, a three-repeat isolated writer-worker
curve, the Spring end-to-end limit, and a conservative Spring helper-memory
admission table:

```text
working/raster_performance_decision_report_20260719/index.html
working/raster_performance_decision_report_20260719/index.data.json
```

## Equivalence and preservation

- All 45 Bald Eagle reports and all 6 Spring reports completed successfully.
- Every StoreMap report confirmed that its `.rasmap` and result HDF state was
  restored. Bald Eagle used full SHA-256 hashes. Spring hashed the small
  `.rasmap` and compared HDF size/mtime to avoid warming a 0.88 GiB result file
  before every timed run.
- All Bald Eagle plan-15 StoreMap settings produced one decoded pixel hash per
  map type and one spatial-metadata variant.
- All Spring settings and storage locations produced the expected hashes:
  Depth `aa74abd3e998...`, Velocity `dda7ef4464ab...`, and WSE
  `3c75b6bf2838...`.
- All direct VRT conversions, regardless of compression, threads,
  overviews, or storage, had pixel hash `bc7fc8d5dbe4...` and identical CRS,
  dimensions, transform, and NoData.
- All eight terrain HDF outputs had 42 datasets, 133,786,928 value bytes, and
  dataset-value hash `9cf0d96be726...`.

File sizes can differ slightly because HDF storage layout and TIFF overview or
compression metadata can differ while decoded values remain identical.

## Limitations and next benchmark work

- Repeat all Spring winner/default cases after a warm-up. Current Spring values
  are one sample each and show substantial native-memory variance.
- Add 128 and 512 MiB GDAL cache cases before selecting a production default.
- Add GDAL thread counts 2 and 4 to allocate a fixed host core budget rather
  than giving every helper `ALL_CPUS`.
- Capture ETW/WPR file-I/O latency and request-size histograms. Process counters
  report application operations, not necessarily the final SMB packets or
  physical device requests after Windows caching.
- Extend the version/hash matrix beyond the currently pinned HEC-RAS 7.0
  `TiffAssist.dll` and `RasMapperLib.dll` build.
- Run the final matrix on a local volume with at least 20 percent free space.
- Treat process-level phase inference as approximate. The copied TiffAssist
  sidecar supplies exact writer-stage aggregates, but exact producer lock wait,
  HDF/terrain stage boundaries, device latency, and per-operation physical queue
  depth still require RASMapper instrumentation and ETW/PerfMon.
