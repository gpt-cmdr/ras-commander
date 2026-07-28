# Raster performance benchmarks

`benchmark_store_maps_memory.py` measures wall time, process-tree CPU, I/O,
threads, RSS/private memory, available system memory, and decoded raster pixel
signatures for real RASMapper StoreMap jobs.

The report includes per-process read/write byte and operation counts, mean I/O
request sizes, interval CPU/throughput/IOPS, and memory timelines. These fields
help distinguish TiffAssist compression/allocation overhead from a small-write
or storage-latency bottleneck.

For ordinary user profiling, prefer the public
`RasProcess.profile_store_maps()` and `RasTerrain.profile_vrt_to_tiff()` APIs
demonstrated in `examples/730_raster_processing_performance_profiling.ipynb`.
Their JSON reports add inferred phase summaries plus host-wide disk throughput,
IOPS, latency/busy-time when the platform exposes it, and host network rates.
Process counters are workload-attributable but include cached/SMB transfers;
host counters are corroborating machine-wide load and may include unrelated
activity.

`generate_raster_performance_report.py` combines selected raw JSON files into
a self-contained HTML decision report with accessible inline SVG charts and a
normalized `.data.json` sidecar. Pass repeated `--synthetic`,
`--store-map-batch`, and `--storage` arguments so the evidence set is explicit
and auditable; `--spring` adds the large-watershed stage and resource timeline.
Pass the controlled benchmark summaries with `--profile-matrix` to add
like-for-like serial-versus-parallel comparisons for map products, VRT
translation, and terrain HDF work. Repeated `--writer-scaling` inputs add the
isolated TiffAssist worker curve so the report can distinguish a scalable
substage from the full application pipeline.

```powershell
.venv\Scripts\python.exe scripts/benchmarks/generate_raster_performance_report.py `
  --synthetic working/native_tiff_experiments/writer-r1/summary.json `
  --synthetic working/native_tiff_experiments/writer-r2/summary.json `
  --store-map-batch working/native_tiff_experiments/store-map-r1/summary.json `
  --spring working/native_tiff_experiments/spring/summary.json `
  --storage working/storage-local.json `
  --storage working/storage-network.json `
  --profile-matrix working/bald-eagle-matrix-summary.json `
  --profile-matrix working/spring-river-matrix-summary.json `
  --writer-scaling working/writer-worker-sweep-r1.json `
  --output working/raster-performance-report/index.html
```

Always run it against a disposable project copy. StoreMap temporarily edits the
project `.rasmap`, and a terminated native helper can leave partial rasters or a
lock file. The benchmark verifies that the project `.rasmap` and selected plan
HDF are unchanged after a completed run.

Spring River is the large-watershed fixture in
`fixtures/spring_river_store_maps.json`. Its active `Terrain (2).vrt` already
contains one 28,916 by 26,316 source raster, so it is a memory-pressure fixture,
not a multi-source VRT consolidation fixture.

```powershell
uv run python scripts/benchmarks/benchmark_store_maps_memory.py `
  --project-folder 'H:\path\to\disposable\Spring River\RAS Model' `
  --plan-number 02 `
  --ras-version 7.0 `
  --maps wse,depth,velocity `
  --max-workers auto `
  --output-path 'H:\path\to\fresh\outputs' `
  --report-path 'H:\path\to\report.json'
```

Automatic worker selection is deliberately conservative. It combines the CPU
limit with available physical memory, reserves at least 25 percent of system
RAM, and estimates large-terrain worker memory from the uncompressed Float32
grid. On the 32 GiB validation workstation, Spring River is scheduled with one
helper; smaller projects can still run independent WSE, Depth, and Velocity
helpers concurrently.

## Terrain functions

`benchmark_terrain_functions.py` profiles each modified public terrain entry
point with the same process-tree telemetry and output signatures:

- `RasTerrain.vrt_to_tiff()`;
- `RasTerrain.create_terrain_hdf()`;
- `RasTerrain.create_terrain_from_rasters()`.

It exposes threads, GDAL cache, compression, overview, stitch, projection, and
terrain-creation settings as benchmark arguments. Outputs must be new or empty.

## Matrix runner

`run_raster_profile_matrix.py` executes explicit JSON manifests, stores each
run's command/stdout/stderr/report/pstats separately, and creates JSON, CSV, and
Markdown summaries. It holds a PID lock in the output root so two matrices
cannot overlap accidentally. Stale locks are reclaimed only when their owner
PID no longer exists.

```powershell
.venv\Scripts\python.exe scripts/benchmarks/run_raster_profile_matrix.py `
  --manifest scripts/benchmarks/fixtures/bald_eagle_raster_profile_matrix.json `
  --output-root working/raster_profile_matrix_20260719/reports_clean_v2 `
  --continue-on-error
```

The Bald Eagle manifest covers 45 local/network run instances across the three
StoreMap wrappers and three terrain functions. The Spring River manifest is a
selected six-run memory-safe pressure test; it does not force concurrent
helpers on the 32 GiB validation host.

The monitor scans only direct children of explicitly watched directories.
Recursive output polling is prohibited because SMB enumeration can become an
observer effect and inflate measured time.

## Storage request-size benchmark

`benchmark_storage_io.py` is a comparative storage-path profiler, not a staging
feature. It creates one owned file at a time, measures buffered sequential
writes at writer-relevant request sizes, flushes once, performs an immediate
warm-cache read, and deletes the file by default.

```powershell
.venv\Scripts\python.exe scripts/benchmarks/benchmark_storage_io.py `
  --directory 'H:\path\to\benchmark-output' `
  --report-path working/storage-network.json `
  --size-mb 256
```

Automatic local scratch, output redirection, and copy-back are outside the
feature. Local and network locations are reported benchmark dimensions only.

## Copied TiffAssist research harness

`native_tiff_experiments/` contains the separate HEC-RAS 7.0 hash-gated
experiment for 64 KiB through 64 MiB TIFF write batching, reusable tile buffers,
statistics/allocation modes, bounded parallel tile preparation/Deflate workers,
one destination raw-tile commit owner, and exact writer-stage sidecars. It
operates only on copied assemblies, is inert without an explicit environment
opt-in, and never modifies the installed HEC-RAS directory. See its `README.md`
for safety and reproduction and `RESULTS.md` for writer-only, queue/batch, Bald
Eagle, and Spring River measurements.
