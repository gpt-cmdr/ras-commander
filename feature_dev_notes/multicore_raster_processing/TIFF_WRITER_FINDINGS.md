# TIFF writer and memory findings

## Copied-assembly parallel writer result

The version-pinned experiment confirms both the small-write hypothesis and the
feasibility of parallelizing per-tile work without modifying the HEC-RAS
installation. For the recognized HEC-RAS 7.0 hashes, an owned copied
`TiffAssist.dll` now provides seek-aware batching; bounded snapshot and encoded
queues; independent rounding/statistics/copy/Deflate workers; one destination
raw-tile commit owner; buffer pools; and stage, queue, allocation, tile, byte,
and physical-write telemetry.

The patch is inert unless `RASCOMMANDER_TIFF_EXPERIMENT=1` is present. Worker
count defaults to zero, queue depth to 2, and batch size to 256 KiB.

On the writer-isolation 8192 by 8192 fixture, the installed original median was
2.435 seconds. Eight workers completed in a 0.815-second median, 66.5 percent
faster, and occupied about 4.6 logical CPUs in one run. This proves the copied
TiffAssist stages can use multiple cores when tiles are continuously available.

Spring River plan 02 Depth Max establishes the end-to-end boundary. The
installed original completed in 112.21 seconds; batching plus one worker took
108.78 seconds, and eight workers took 109.64 seconds. The 11,715 logical writes
became 494 underlying writes. Process writes changed from 50.7 IOPS at 22.4 KiB
to 5.2 IOPS at about 224 KiB. One and eight workers both spent about 84–85
seconds in the pipeline because RASMapper did not feed tiles continuously.
Eight workers reduced input-queue blocking from 12.53 to 2.55 seconds, but raw
commit required only 0.49 seconds and aggregate Deflate calls about 25 seconds.

Every reported synthetic, Bald Eagle, and Spring output retained decoded
pixels, dimensions/types, CRS, transform, NoData, required overviews, and
exposed TIFF metadata/statistics. Layout and compression were unchanged in the
reported v2 matrix but are recorded separately from the general semantic test.
"Histogram" here means metadata exposed through TIFF tags/domains, not an
unexposed RASMapper in-memory representation. Odd dimensions and raw-NoData
tile-zero replacement are covered.
The experiment remains research-only pending HEC permission/licensing, broader
versions, failure/BigTIFF/GUI tests, and repeated large-fixture trials.

Full evidence and commands are in
`scripts/benchmarks/native_tiff_experiments/RESULTS.md`.

## Root cause

The apparent single-core behavior is a serialized-pipeline problem, not a
Pythonnet limitation.

HEC-RAS 7.0 decompilation shows that `StoredResultMap` creates map tiles with a
`.NET Parallel.For` whose default `MaxDegreeOfParallelism` is hard-coded to 32.
Completed 256 by 256 Float32 tiles enter a bounded queue. One consumer task
drains a `ConcurrentBag` and calls TiffAssist `FloatTiffWriter.WriteTile()` for
every tile. Destination writes are serialized but not guaranteed to be in
tile-number order. That
method calculates tile statistics and rounding, allocates and copies a byte
buffer, and calls LibTiff `WriteEncodedTile()`. It uses Adobe Deflate with ZIP
quality 1 and BigTIFF defaults that the public `StoreMapCommand` does not
expose.

The writer is followed by a TIFF reread for histogram/statistics and a separate
`gdaladdo` overview process. Those later GDAL controls do not reconfigure
TiffAssist.

This explains all of the observed behavior:

- one helper accumulates more CPU seconds than wall seconds because producers
  and per-tile statistics use internal threads;
- total CPU utilization remains uneven because HDF/TIFF locks and one serialized
  writer form serialization points;
- `GDAL_NUM_THREADS` improves direct GDAL translation but does not unlock the
  native writer;
- Python spends nearly all of its time waiting for native subprocesses;
- independent map helpers improve throughput when memory permits.

The Spring local three-map report makes the utilization boundary concrete.
The native helper accumulated 650.8 CPU seconds during approximately 266.6
seconds of inferred helper activity, equivalent to 2.44 logical CPUs on the
8-logical-CPU host. The overview stage accumulated 43.3 CPU seconds during
45.2 seconds, equivalent to 0.96 logical CPUs. End to end, the process tree
used 738.3 CPU seconds over 328.5 seconds, only 28.1 percent of the whole
machine. This is underutilization caused by locks, queue/ordering constraints,
one TIFF consumer, and storage waits, not proof that every stage is strictly
single-threaded.

## Small-write evidence

The native write pattern is real and materially unfavorable over SMB.

| Workload | Writer | Writes | Mean write |
|---|---|---:|---:|
| Bald Eagle, one map | TiffAssist helper | about 1,522 | 3.0 to 4.7 KiB |
| Bald Eagle, three maps serial | TiffAssist helper | 4,512 | 3.9 KiB |
| Spring Depth | TiffAssist helper | 11,714 | 10.1 KiB |
| Spring three maps | TiffAssist helper | 35,088 | 9.3 KiB |
| Bald Eagle general VRT | `gdal_translate` | 3,607 | 62.7 KiB |
| Bald Eagle general VRT overview | `gdaladdo` | about 1,608 | 61.1 KiB |

The isolated SMB benchmark achieved only 11.6 MiB/s with 4 KiB writes, versus
118.9 MiB/s at 64 KiB and 349.2 MiB/s at 8 MiB. Windows can coalesce cached
writes, so application operation sizes are not identical to SMB packet sizes,
but the matched request-size curve strongly supports a small-write latency
cost.

Python cannot wrap or batch these writes after calling `StoreMapCommand`: the
native process owns the TiffAssist/LibTiff writer and the file handle. Larger
Python buffers or releasing the GIL cannot change it.

## What can be controlled safely now

| Control | Native StoreMap effect | GDAL terrain/VRT effect | Status |
|---|---|---|---|
| Independent map helpers | Runs WSE/Depth/Velocity concurrently | Not applicable | High-value prototype |
| Memory-aware admission | Prevents unsafe helper overlap | Can protect concurrent conversions | Required before release |
| `GDAL_CACHEMAX` | Caps descendant `gdaladdo`, not TiffAssist | Caps GDAL block cache | Supported, profile first |
| `GDAL_NUM_THREADS` | May affect descendant GDAL only | Speeds supported GTiff compression/decompression | Supported, allocate a host budget |
| LZW vs DEFLATE | Native codec is hard-coded | Public GDAL output choice | LZW was much faster here |
| Overview levels/resampling | Native workflow owns normal overviews | Public GDAL output choice | Supported for general GDAL output |
| Block-streamed validation | Avoids Python whole-raster allocation | Same | Implemented |
| Output storage location | Measures actual path behavior | Measures actual path behavior | Reporting dimension only |

Automatic local scratch/staging is not part of this feature.

## TiffAssist optimization status and remaining experiments

These require a copied, version-pinned assembly or a new writer and must not be
exposed as stable options until output equivalence and HEC-RAS compatibility are
proved.

### 1. Batch encoded writes — implemented in the copied harness

The copied harness accepts LibTiff client-I/O commit ceilings from 64 KiB
through 64 MiB. A five-repeat 8192-square sweep selected 2 MiB as the benchmark
runner default (0.747-second median); 4–64 MiB did not improve latency and
64 MiB raised median writer RSS by about 28 MiB. The assembly fallback remains
256 KiB. It preserves LibTiff's logical
seek/write semantics, tile offsets, and byte counts; Python still cannot
interpose on the installed native file handle.

Acceptance should show fewer write operations, larger mean writes, identical
decoded values and metadata, and repeatable improvement over SMB. A local-only
win is not sufficient because the strongest benefit is expected on network
storage.

### 2. Remove per-tile task/allocation overhead — partially implemented

`WriteTile()` creates per-tile statistics work using row-level
`Parallel.For`/`ConcurrentBag` behavior and allocates a new byte array. The
copied harness now profiles and implements:

- one serial-within-tile min/max/valid-count pass;
- producer-side statistics carried with the tile;
- pooled float, byte, and compressed arrays;
- piggybacked whole-raster statistics that avoid a later reread.

This is likely a better CPU/allocation target than simply raising the producer
thread count, because producer parallelism already exists.

### 3. Change tile size only in a compatibility harness

A 256 by 256 Float32 tile is 256 KiB before compression but often becomes only
a few KiB on disk. A 512 or 1024 tile could create larger encoded writes and
reduce tile-call overhead. It also increases working buffers, queue memory, and
latency, and RAS TIFF validation expects the native 256 by 256 layout. Profile
256, 512, and 1024 only against copied assemblies and verify HEC-RAS can reopen
the products.

### 4. Separate parallel compression from destination commit — implemented

Multiple threads do not call the destination LibTiff writer. Each worker uses a
private in-memory LibTiff/Deflate context and passes the raw payload plus tile
number to one commit task. BitMiracle maintains the destination tile tables and
directory bookkeeping. Commit order follows worker completion, which is
compatible with the installed consumer's unordered `ConcurrentBag`. The raw
commit resets the destination write offset before replacing a seeded tile, so
tile zero remains correct.

### 5. Compression tradeoffs

The native Deflate level is hard-coded. In the general GDAL path, DEFLATE used
about 3.4 times the CPU seconds and 2.2 times the wall time of LZW while creating
a smaller file. Test native no-compression, LZW, Deflate levels, and ZSTD only in
the copied-assembly harness. A bigger file may still be faster if compression
CPU is dominant, but on SMB it may exchange CPU time for network time.

### 6. Defer and bound overviews

Overview creation consumed about 45 to 50 seconds of the full Spring three-map
run. Multiple map helpers can overlap independent `gdaladdo` children, but
giving every child `ALL_CPUS` can oversubscribe the host. Use a total core and
memory budget; consider generating base maps first and then processing a bounded
overview queue.

## Memory model

### Why TIFF file size is not a memory estimate

Spring's terrain contains approximately 760.8 million cells. One Float32 grid
is about 2.83 GiB before metadata, masks, geometry/HDF caches, output buffers,
compression state, and CLR allocations. A compressed output around 180 to 240
MiB says little about those in-memory structures.

The known writer buffers are not large enough to explain the peak by themselves:

- 50 queued 256 by 256 Float32 tiles: about 12.5 MiB;
- roughly 65 retained output buffers in the StoreMap path: about 16.25 MiB;
- even the larger 257-buffer code path: about 64.25 MiB.

Measured Spring helper peaks of roughly 5 to 10 GiB must therefore include
terrain, mesh/geometry, HDF, CLR, intermediate map, statistics, compression,
and other native caches.

The parallel writer does not materially change that estimate. Spring's
eight-worker, depth-2 run owned at most 12 tiles while processing 1.265 GB of
uncompressed tile payload over the full run. Its bounded live tile storage is
only on the order of tens of MiB; the measured helper tree still peaked near
9.51 GiB. Queue depths above 2 increased owned tiles and private memory in the
isolated writer without improving elapsed time.

Reducing that peak increases safe concurrency only when physical memory or
Windows commit headroom is the scheduler's active limiter. It does not make the
single TIFF consumer faster. On Spring, memory is the reason a second helper is
unsafe; on one active helper, the serialized writer/locked read pipeline and
storage latency remain the throughput limit. Both constraints must be measured
instead of treating memory reduction as an automatic CPU-speed improvement.

### Proposed estimate

For each map job, inspect the active terrain and calculate:

```text
cells = width * height
raw_float_grid_bytes = cells * 4
native_estimate = fixed_overhead + raw_float_grid_bytes * calibrated_multiplier
gdal_estimate = configured_cache_bytes + measured_gdal_process_overhead
worker_estimate = max(minimum_floor, native_estimate, gdal_estimate,
                      calibrated_p95_for_version_map_and_size_class)
```

The final worker count should be:

```text
physical_budget = available_physical - max(reserve_mb, reserve_fraction * RAM)
commit_budget = commit_limit - committed - commit_reserve
usable_budget = min(physical_budget, commit_budget) when both are available
memory_limit = floor(usable_budget / worker_estimate)
selected = max(1, min(job_count, cpu_limit, requested_limit, memory_limit))
```

Treat this as a conservative admission estimate, not a prediction of exact peak
bytes. Store measurements keyed by HEC-RAS version, DLL hashes, map type,
terrain cell class, and settings. Use a high percentile plus a safety margin.

### Live governor

Static estimates cannot see other workloads or allocation variance. Before
launching each queued helper:

1. resample available physical memory and Windows commit headroom;
2. require the configured reserve plus one estimated worker;
3. wait with a bounded timeout if the threshold is not met;
4. stop launching new work if pressure crosses a warning threshold;
5. normally let active helpers finish so partial rasters and project state can
   be restored cleanly.

The controlled Spring results validate this requirement. Automatic execution
selected one helper. Forced two-helper exploration previously reduced available
memory to 3.17 GiB.

### What the GDAL cache result means

The original cache-labeled matrix set `GDAL_CACHEMAX` only on the parent while
the child-scoped API rebuilt its environment. Those rows do not measure the
named caps and are invalid for cache conclusions. The corrected runner passes a
typed child option and charges the explicit cache cap to each worker's admission
estimate. Corrected Bald Eagle runs now prove propagation at 64 and 256 MiB on
local and SMB storage. A 15-minute Spring rerun never completed project
initialization and launched no helper, so it is not a cache result. Repeat the
full 64/128/256/512 MiB matrix, including successful Spring pressure runs,
before selecting a default.

## Chunking and other realistic options

The investigated paths are not exhaustive. Realistic options, in priority
order, are:

1. map-level WSE/Depth/Velocity helper processes with memory admission;
2. bounded plan/timestep concurrency using isolated project copies and unique
   output names;
3. GDAL translation/cache/thread tuning for terrain and overview phases;
4. writer batching, allocation reduction, and statistics changes in a copied
   TiffAssist harness;
5. derive Depth block-by-block from stored WSE and terrain, only if pixel-level
   equivalence including wet/dry and NoData behavior can be proved;
6. a new native batch helper that initializes geometry/HDF state once and
   creates multiple map types without sharing unsafe static state;
7. explicit coarser output resolution where the user accepts the product
   change;
8. spatial extent/resample methods exposed internally by RASMapper, researched
   for seams and cache reload cost before any public API;
9. distribute independent maps/plans to existing RasRemote workers when one
   workstation lacks memory.

Splitting a terrain into source tiles is not automatically a memory fix. The
current Spring VRT has one source, but the dominant caches may still cover the
full result domain. Tiled-terrain experiments must compare one-source and
multi-source cases with seam, pixel, time, and peak-memory validation.

Pagefile growth, global CLR thread-pool limits, processor affinity, reflection
into private fields, or merely increasing the writer queue are not production
solutions. They can prevent failure or alter a profile, but they do not remove
the serialized writer and may cause paging, starvation, or deadlock.
