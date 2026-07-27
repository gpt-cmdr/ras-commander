# Multicore raster processing

## Outcome

The performance bottleneck is not a missing Python GIL release or one GDAL
switch. HEC-RAS 7.0 StoreMap work is a mixed pipeline:

1. `StoredResultMap` uses internal `.NET` parallel producers.
2. One TiffAssist consumer drains an unordered completed-tile bag and writes
   one 256 by 256 tile at a time.
3. TiffAssist performs per-tile statistics, rounding, allocation, and Deflate
   compression.
4. RASMapper rereads the TIFF for histogram/statistics work.
5. A separate `gdaladdo` process creates overviews.

The process can therefore accumulate more than one core-second per wall-second,
while still being constrained by a serialized writer and one public StoreMap
command per map. Pythonnet cannot change those private native constants.

The implemented prototype obtains parallelism safely at the map level by
running independent WSE, Depth, and Velocity maps in isolated native helper
processes. On the controlled Bald Eagle matrix, automatic three-map execution
reduced elapsed time by 43.8 percent locally and 44.5 percent over SMB. Spring
River does not have enough memory headroom for multiple simultaneous helpers on
the 31.8 GiB test host, so automatic scheduling correctly remains serial.

A separate copied-assembly experiment also reimplements the TiffAssist consumer
as bounded parallel rounding/statistics/copy/Deflate workers plus one raw-tile
commit owner. An isolated writer improved 66.5 percent at eight workers, proving
that these stages can use multiple cores. Spring River improved only 3.1 percent
at one worker and did not improve further at eight: tile production spanned
about 84 seconds, aggregate Deflate calls about 25 seconds, and raw commit only
0.49–0.66 seconds. The large-project bottleneck is therefore upstream
terrain/HDF/map-value production plus histogram/overview work, not destination
TIFF commit.

Batching was expanded and measured through 64 MiB. Five isolated repetitions
selected 2 MiB (0.747-second median); 4–64 MiB were slower, and 64 MiB added
about 28 MiB of writer RSS. Larger requests still improve the raw SMB storage
test, but TIFF seeks and directory updates force early buffer flushes. The
setting is therefore a profileable ceiling, not a universal "larger is faster"
knob.

## Scope decision

Automatic local scratch, staging, and copy-back are explicitly outside this
feature. Local fixed storage and mapped network storage are benchmark
dimensions only. The implementation must not redirect user output based on the
filesystem type.

## Development artifacts

- [Detailed benchmark record](BENCHMARKING.md)
- [TIFF writer and memory findings](TIFF_WRITER_FINDINGS.md)
- [API and release handoff](API_AND_RELEASE_HANDOFF.md)
- [Canonical feature specification](../../agent_tasks/2026-07-19_multicore_raster_processing_feature_spec.md)
- [API consistency audit resolution](API_CONSISTENCY_AUDIT_RESOLUTION.md)
- [Benchmark harness documentation](../../scripts/benchmarks/README.md)
- [Copied TiffAssist experiment](../../scripts/benchmarks/native_tiff_experiments/README.md)
- [Copied TiffAssist measured results](../../scripts/benchmarks/native_tiff_experiments/RESULTS.md)
- [Self-service profiling notebook](../../examples/730_raster_processing_performance_profiling.ipynb)

The current decision report and its normalized data are ignored runtime
artifacts at:

```text
working/raster_performance_decision_report_20260719/index.html
working/raster_performance_decision_report_20260719/index.data.json
```

The report now leads with observed serial-versus-parallel comparisons. It
separates map-level process scaling, threaded GDAL translation, terrain-HDF
non-scaling, isolated TiffAssist worker scaling, the Spring River end-to-end
limit, and raw local/SMB request-size sensitivity. Its Spring section also
shows a conservative one/two/three-helper available-memory budget so machines
with more free memory can make an explicit map-concurrency decision.

Large project copies, TIFFs, raw JSON reports, process timelines, and pstats
files remain under ignored `working/raster_profile_matrix_20260719/` paths.

## Current implementation status

Implemented and exercised:

- one canonical `RasMap.store_all_maps()` function with native, selected,
  timesteps, all-plans, and backward-compatible auto modes;
- process-isolated WSE/Depth/Velocity StoreMap execution;
- automatic worker selection using CPU, map count, estimated memory, and a
  reserve;
- GDAL thread controls for terrain VRT conversion and terrain creation;
- GDAL cache/thread environment propagation for StoreMap child processes;
- block-streamed output validation and decoded-pixel signatures;
- interval process-tree CPU, memory, thread, throughput, IOPS, request-size,
  inferred-phase, host-disk, and host-network telemetry;
- local/network matrix runner with an exclusive PID lock;
- Bald Eagle functional/settings matrix and selected Spring River pressure
  matrix.
- immutable `StoreMapPerformanceOptions` and `GeoTiffWriteOptions` contracts;
- a non-mutating `RasProcess.estimate_store_map_resources()` API;
- physical-memory and Windows-commit admission before every helper launch;
- `RasProcess.profile_store_maps()` and
  `RasTerrain.profile_vrt_to_tiff()` JSON reports;
- fixed-row decoded-pixel hashes that remain comparable when tile size or
  compression changes;
- a self-service example notebook whose heavy run switches default false and
  whose analysis-only path executes and writes a user-owned HTML report;
- a version/hash-gated copied TiffAssist experiment with opt-in 64 KiB through
  64 MiB writes, bounded parallel tile preparation/Deflate workers, one raw-tile
  commit owner, buffer pools, detailed sidecars, and installed-DLL immutability
  checks;
- odd-edge and raw-NoData correctness tests plus writer-only, queue-depth,
  batch-size, Bald Eagle, and Spring River matrices.

The API consistency blockers are resolved: the complete legacy positional
prefix is unchanged, advanced settings are keyword-only, the old
`RasProcess.store_all_maps()` name is a warning compatibility forwarder rather
than a second implementation, deprecated scalar aliases remain temporarily
accepted, and structured profiling results are returned separately from the
established stored-map output dictionary.

## Validation snapshot

- Bald Eagle controlled matrix: 45 of 45 complete.
- Spring River controlled matrix: 6 of 6 reports complete, but the two
  historical cache/thread labels did not reach the child and are invalid for
  cache conclusions. Six corrected Bald Eagle cache cases are complete; a
  corrected Spring attempt timed out during project initialization before any
  helper or output existed and is explicitly a non-result.
- Spring River copied-TiffAssist matrix: 4 of 4 complete and semantically
  equivalent; 11,715 logical writes reduced to 494 physical writes in the
  one-worker case.
- Focused public API, BenefitArea compatibility, native experiment, HTML report,
  benchmark, and raster regression suites: 184 passed and 1 data-dependent skip.
- Repository-wide pass after the interval-profiler addition: 1,574 passed and
  68 skipped. It also exposed 23 failures and 2 setup errors outside this
  feature. The remaining baseline failures cover missing pythonnet, docs-host
  expectations, unrelated logging/compute/precipitation tests, and the
  previously known executed terrain tutorial cell. No raster-performance test
  appears in the failure list.
- Separate unrelated baseline: `test_terrain_tutorial_notebook.py` reports an
  existing notebook execution count; this feature did not modify that notebook.
- Python compilation, Black, and Ruff: clean for the new benchmark harness and
  benchmark tests. `git diff --check` is clean for the current diff. The older
  production modules retain pre-existing repository-wide Black/Ruff findings
  and were not mechanically reformatted as part of this feature.
