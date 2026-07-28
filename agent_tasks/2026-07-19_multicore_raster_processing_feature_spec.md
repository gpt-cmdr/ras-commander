# Multicore RASMapper Raster Processing Feature Specification

Status: Implemented and benchmarked on feature branch

Target release: Pending review

Primary API: `RasProcess.store_maps()` and `RasTerrain`

Test fixtures: Bald Eagle and Spring River

## Decision summary

Add a resource-aware raster execution layer around the supported HEC-RAS and
GDAL entry points. The first production release should expose dry-run resource
estimation, bounded map-level process parallelism, GDAL cache/thread controls,
and structured performance telemetry. It must retain the existing serial
behavior by default.

Do not patch the installed HEC-RAS assemblies in the production feature. Native
queue depth, tile size, compression level, and the hard-coded 32-way producer
loop are valuable experimental variables, but changing them requires a
version- and hash-gated research harness operating on copied assemblies.

Spring River is already a suitable large-watershed fixture. Its active terrain
VRT contains one source and is therefore already consolidated; blind VRT
consolidation would add work without reducing source-open overhead.

## API consistency audit disposition

The API consistency auditor initially returned **changes requested**. Both P0
items are now resolved and regression-tested:

1. The prototype inserted new worker/memory arguments before the legacy
   `terrain_name` and `benefit_area` parameters. This breaks positional callers.
   The entire legacy positional prefix is restored and performance options are
   keyword-only.
2. The scheduling heuristic is exposed through the public, typed, read-only
   `estimate_store_map_resources()` API.

P1 corrections included in this specification are explicit floor-versus-
override memory semantics, runtime admission checks, machine-readable fallback
reasons, compatibility-first terrain threading defaults, and mapped-drive-safe
path handling with `RasUtils.safe_resolve()` instead of `Path.resolve()`.

Durable audit disposition:
`feature_dev_notes/multicore_raster_processing/API_CONSISTENCY_AUDIT_RESOLUTION.md`.

The remaining native-TIFF controls are intentionally isolated from the stable
API in a hash-pinned copied-assembly research harness.

## User outcomes

The feature must let a caller answer these questions before starting a map run:

1. How many independent maps can this machine run concurrently without memory
   exhaustion?
2. How much memory and output space will one worker probably consume?
3. Which limiter selected the final worker count: jobs, CPU, physical memory,
   commit headroom, or an explicit user cap?
4. Is the run compute-bound, native TIFF-writer-bound, overview-bound, or
   storage-bound?
5. Which supported tuning configuration is fastest on this machine and project
   without changing raster values?

## Confirmed implementation facts

The following facts come from the HEC-RAS 7.0 decompilation and the Spring River
measurements. They should be treated as version-specific and revalidated for
other HEC-RAS releases.

- `StoredResultMap` computes terrain tiles with a `Parallel.For` whose
  `MaxDegreeOfParallelism` is hard-coded to 32.
- Terrain TIFF reads and some HDF reads are protected by locks. More producer
  threads therefore do not imply linear throughput.
- The output path has one consumer task. That task calls TiffAssist
  `FloatTiffWriter.WriteTile()` for each completed data tile.
- The native tile is 256 by 256 Float32 values: 65,536 values or 256 KiB before
  compression.
- The producer queue is throttled when it exceeds 50 data tiles, approximately
  12.5 MiB of uncompressed tile payload.
- The reusable buffer pool can retain roughly 65 output buffers in the
  `StoredResultMap` path, approximately 16.25 MiB. Other mapping paths contain a
  larger 256-buffer limit and must not be assumed to behave identically.
- `FloatTiffWriter.WriteTile()` calculates per-tile statistics and rounding,
  allocates a new byte array, copies the float tile into it, then calls
  `WriteEncodedTile()`.
- The per-tile statistics implementation uses a new row-level
  `Parallel.For`/`ConcurrentBag` operation for every tile. This can add task,
  allocation, synchronization, and garbage-collection overhead even though
  there is only one TIFF consumer.
- TiffAssist writes tiled BigTIFF with Adobe Deflate, ZIP quality 1, and a
  default 256 by 256 tile. These choices are hard-coded in the installed
  assembly, not exposed by `StoreMapCommand`.
- After writing, RASMapper scans the TIFF to add a histogram, then invokes GDAL
  overview generation with Deflate compression. These phases are separate from
  the TiffAssist writer.
- `gdaladdo` runs are serialized inside one helper but independent helper
  processes can overlap them.
- An audit found that the original cache-labeled runner set `GDAL_CACHEMAX`
  only on the parent and the child-scoped API sanitized it. Those historical
  rows are invalid for cache conclusions. The corrected runner passes typed
  child options and the estimator charges an explicit cache cap per helper.
  Corrected Bald Eagle 64/256 MiB local and SMB cases are complete. A corrected
  Spring attempt did not finish project initialization within 15 minutes and
  launched no helper, so 64/128/256/512 MiB pressure cases still require
  successful reruns before a default is selected.
- The Spring River terrain is 28,916 by 26,316 cells, approximately 760 million
  cells. In the final controlled matrix, automatic three-map execution used one
  helper at a time. Local fixed storage completed in 328.452 seconds, peaked at
  9.75 GiB process-tree private bytes, and retained at least 8.44 GiB available
  memory. Mapped network storage completed in 360.887 seconds, peaked at 6.61
  GiB private bytes, and retained at least 11.56 GiB available memory. The peak
  variance reinforces conservative percentile calibration and live admission.
- A forced two-helper Spring River experiment produced approximately 7.25 to
  7.55 GiB private bytes per helper, with one helper later reaching 10.955 GiB.
  Available system memory fell to 3.17 GiB, so the experiment was stopped.
- In the final controlled Bald Eagle matrix, three automatic map helpers
  measured 1.778 times local and 1.803 times network acceleration over serial
  medians. LZW GDAL VRT-to-TIFF conversion with overviews measured 1.276 times
  local and 1.268 times network acceleration with `ALL_CPUS` versus one thread.
- TiffAssist helper writes averaged approximately 3 to 5 KiB on Bald Eagle and
  9 to 10 KiB on Spring. A buffered storage-path benchmark measured 11.6 MiB/s
  for 4 KiB SMB writes, 118.9 MiB/s for 64 KiB, and 349.2 MiB/s for 8 MiB,
  making write batching a high-value copied-assembly experiment.
- A public Spring Depth interval profile measured 107.730 seconds end to end.
  The native helper stage occupied 86.864 seconds at 2.71 logical CPUs (33.9
  percent of the 8-thread machine), wrote 1.33 MiB/s at 134.5 process IOPS with
  a 10.1 KiB mean request, and peaked at 9.12 GiB private bytes. The overview
  stage occupied 15.071 seconds at 1.15 logical CPUs and 14.4 percent machine
  utilization. This directly confirms a partially parallel but serialized
  native pipeline rather than a Python single-core limit.

## Scope

### Production scope

- Public, non-mutating StoreMap resource estimator.
- Backward-compatible StoreMap execution configuration.
- Memory- and commit-aware dynamic worker dispatch.
- Supported GDAL cache and thread environment controls.
- Phase-aware process, memory, CPU, and I/O telemetry.
- Host-wide disk throughput, IOPS, latency/busy-time when available, and network
  throughput, explicitly distinguished from process-attributable cached/SMB
  file I/O.
- Terrain topology inspection and consolidation advice.
- Benchmark runner using disposable project copies.
- Bald Eagle functional/performance fixture.
- Spring River large-watershed/memory-pressure fixture.

### Research scope

- Copied-assembly experiments for native queue, buffer, tile, compression,
  statistics, and native parallelism settings.
- Spatial chunking experiments through private mapper internals.
- Alternate raster-writer pipeline experiments.

### Non-goals

- Editing DLLs in the installed HEC-RAS directory.
- Promising linear CPU scaling inside one native StoreMap operation.
- Running maps that share mutable PostProcessing HDF state concurrently.
- Treating TIFF file size as a memory estimate.
- Consolidating every multi-source VRT automatically.
- Changing raster precision, rounding, nodata, histogram, overview, or
  compression semantics without an explicit opt-in and equivalence test.
- Adding automatic local scratch, staging, or copy-back behavior. Local and
  network storage are benchmark dimensions only for this feature.

## Public API specification

The common API remains simple. Existing keyword arguments remain accepted so
current callers do not break. Advanced controls are grouped in an immutable
configuration object to prevent further `store_maps()` parameter sprawl.

### StoreMapPerformanceOptions

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union


@dataclass(frozen=True)
class StoreMapPerformanceOptions:
    """Resource and performance controls for stored-map generation."""

    max_workers: Optional[int] = 1
    memory_policy: Literal["enforce", "warn", "ignore"] = "enforce"
    minimum_worker_memory_mb: int = 600
    worker_memory_override_mb: Optional[int] = None
    reserve_memory_mb: int = 4096
    reserve_memory_fraction: float = 0.25
    gdal_cachemax_mb: Optional[int] = None
    gdal_num_threads_per_helper: Union[int, Literal["ALL_CPUS"], None] = 1
    admission_wait_timeout_seconds: float = 300.0
    admission_poll_interval_seconds: float = 1.0
```

Semantics:

- `max_workers=1` preserves serial execution.
- `max_workers=None` asks the scheduler to choose automatically.
- An integer greater than one is a ceiling, not a promise.
- `memory_policy="enforce"` applies both the estimate and runtime admission
  checks. `"warn"` records that the request exceeds the estimate but honors the
  worker ceiling. `"ignore"` is an explicit expert override and still records
  telemetry.
- `minimum_worker_memory_mb` is only a floor for missing or small terrain
  estimates. It is not an exact allocation.
- `worker_memory_override_mb` replaces the heuristic only with an explicit
  non-default policy and is logged prominently.
- The effective reserve is the larger of `reserve_memory_mb` and
  `reserve_memory_fraction * physical RAM`.
- `gdal_cachemax_mb=None` leaves GDAL's process default unchanged. A bounded
  cache such as 256 MiB is an explicit profile candidate, not a global default.
- `gdal_num_threads_per_helper` controls only descendant GDAL operations that
  implement threading. It does not override TiffAssist or RASMapper's private
  parallel loops.
- Validation belongs in `__post_init__`.

The prototype's three scalar tuning arguments may remain for one development
window only as keyword-only aliases after every legacy positional parameter.
Passing both aliases and `performance` is an error. No new tuning parameter may
be inserted before legacy `terrain_name` or `benefit_area` slots.

### StoreMapResourceEstimate

```python
@dataclass(frozen=True)
class StoreMapResourceEstimate:
    plan_number: str
    hecras_version: Optional[str]
    map_types: tuple[str, ...]
    job_count: int
    terrain: tuple[TerrainResourceEstimate, ...]
    formula_version: str
    estimate_source: Literal["heuristic", "override", "floor"]
    surface_multiplier: float
    fixed_overhead_mb: int
    estimated_gdal_cache_mb: int
    estimated_worker_private_mb: int
    total_physical_mb: int
    available_physical_mb: int
    commit_total_mb: Optional[int]
    commit_limit_mb: Optional[int]
    commit_headroom_mb: Optional[int]
    effective_reserve_mb: int
    cpu_limit: int
    memory_limit: int
    request_limit: int
    job_limit: int
    selected_workers: int
    parallel_eligible: bool
    fallback_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
```

This is the implemented v1 contract. Result-HDF bytes, mesh cells/faces,
estimated output size, calibration IDs/confidence, and explicit limiting-factor
fields remain future calibration work and are not promised by the current API.

### Resource estimator

```python
class RasProcess:
    @staticmethod
    @log_call
    def estimate_store_map_resources(
        plan_number: str,
        map_types: Optional[Sequence[str]] = None,
        *,
        terrain_name: Optional[str] = None,
        performance: Optional[StoreMapPerformanceOptions] = None,
        ras_object=None,
    ) -> StoreMapResourceEstimate:
        ...
```

This method is read-only. It resolves the plan and active terrain through the
same project APIs used by `store_maps()`, not ad hoc project globbing.
The result provides a JSON-serializable `to_dict()` and must not edit `.rasmap`,
create output directories, or launch a native helper.

### Stored-map execution

Preserve every existing parameter in its existing position, including
`terrain_name` and `benefit_area`, then add the following keyword-only option:

```python
*,
performance: Optional[StoreMapPerformanceOptions] = None
```

Propagate the same keyword through `RasProcess.store_maps_at_timesteps()` and
the configured `selected`, `timesteps`, and `all_plans` modes of
`RasMap.store_all_maps()`. That method is the canonical orchestration surface;
its `native` mode preserves the historic command and first four positional
slots. `RasProcess.store_all_maps()` remains only as a warning compatibility
forwarder.
Keep `plan_number`, flexible `str`/`Path` inputs,
`ras_object`, `@staticmethod`, and `@log_call` consistent with the existing
static namespace API. Reject non-default options when a fallback path cannot
honor them instead of silently ignoring the request.

### Performance report and public profiler (implemented)

```python
@dataclass(frozen=True)
class StoreMapProfileResult:
    resource_estimate: StoreMapResourceEstimate
    settings: Dict[str, Any]
    generated_files: Dict[str, Tuple[Path, ...]]
    elapsed_seconds: float
    peak_tree_rss_mb: float
    peak_tree_private_mb: Optional[float]
    minimum_available_memory_mb: int
    minimum_commit_headroom_mb: Optional[int]
    cpu_seconds_by_process: Dict[str, float]
    read_bytes_by_process: Dict[str, int]
    write_bytes_by_process: Dict[str, int]
    read_operations_by_process: Dict[str, int]
    write_operations_by_process: Dict[str, int]
    maximum_simultaneous_helpers: int
    samples: Tuple[StoreMapResourceSample, ...]
    performance_summary: Dict[str, Any]
    phase_summary: Dict[str, Dict[str, Any]]
    output_signatures: Dict[str, Dict[str, Any]]
    report_path: Path
```

`store_maps()` continues returning its existing dictionary. Do not put
telemetry into that dictionary and do not introduce a conditional return type.
The benchmark CLI and public `RasProcess.profile_store_maps()` API produce this
report. Profiling requires a disposable project destination and supports an
explicit report path. `to_dict()` identifies the report as
`ras-commander.store-map-profile/1` with `status="complete"`.

Phase detection can initially infer native writer, histogram, and overview
phases from helper output messages and descendant process names. Native queue
depth remains unavailable without a research hook and should be `None` in
production reports.

### GeoTiffWriteOptions

General GDAL-backed terrain output has more supported controls than native
TiffAssist output. Keep those controls in a separate immutable object instead
of adding unrelated scalars to `RasTerrain.vrt_to_tiff()`:

```python
@dataclass(frozen=True)
class GeoTiffWriteOptions:
    compression: Literal["LZW", "DEFLATE", "ZSTD", "NONE"] = "LZW"
    compression_level: Optional[int] = None
    predictor: Optional[Literal[1, 2, 3]] = None
    tile_size: Optional[int] = None
    bigtiff: Literal["IF_SAFER", "IF_NEEDED", "YES", "NO"] = "IF_SAFER"
    gdal_num_threads: Union[int, Literal["ALL_CPUS"], None] = None
    gdal_cachemax_mb: Optional[int] = None
    create_overviews: bool = True
    overview_levels: tuple[int, ...] = (2, 4, 8, 16, 32)
    overview_resampling: Literal[
        "nearest", "average", "average_mp", "average_magphase", "cubic",
        "cubicspline", "lanczos", "gauss", "mode"
    ] = "average"
    overview_compression: Optional[str] = None
```

Add keyword-only `write_options=None` after every existing
`vrt_to_tiff()` argument. Reject conflicts with transitional scalar arguments.
Validate codec-specific compression levels and require tile sizes to be
positive and divisible by 16.

`GeoTiffWriteOptions` does not apply to native StoreMap TIFFs. RAS-native
outputs remain fixed at 256-cell tiles until a version-pinned equivalence test
proves otherwise.

Use a compatibility-first default for `create_terrain_hdf()` and
`create_terrain_from_rasters()`: `gdal_num_threads=None` unless explicit write
options request threading. The direct GDAL `vrt_to_tiff()` path may retain its
documented optimized default. In all cases, state that GDAL thread controls do
not change native TiffAssist or .NET `Parallel.For` behavior.

## Memory-estimation model

### Why compressed TIFF size is not sufficient

Stored maps operate on uncompressed terrain cells, mesh/result caches, output
tile buffers, per-thread state, .NET allocations, TIFF compression buffers, and
GDAL overview caches. A 500 MiB compressed TIFF can therefore require several
GiB of private committed memory.

### Initial formula

Use a versioned, deliberately conservative formula:

```text
terrain_surface_bytes = sum(width * height * max(dtype_size, 4))

native_worker_bytes =
    512 MiB
    + alpha * terrain_surface_bytes
    + beta * result_working_set_bytes
    + managed_tile_allowance

gdal_phase_bytes = configured_GDAL_CACHEMAX + gdal_process_overhead

estimated_worker_private_bytes =
    max(minimum_worker_memory, native_worker_bytes, calibrated_p95)
    + overlap_allowance(native_worker_bytes, gdal_phase_bytes)
```

When `worker_memory_override_mb` is present, replace the heuristic result and
set `estimate_source="override"`; do not present the value as measured. The
`memory_policy` determines whether the resulting worker limit is enforced,
warned, or ignored.

Initial values:

- `alpha = 4.0`, based on the Spring River forced-concurrency stress result.
- `beta = 0.0` until mesh/result predictors are measured reliably. Record HDF
  sizes now so calibration can determine whether they explain residual error.
- `managed_tile_allowance = 128 MiB` for buffers, byte-array churn, statistics,
  and GC slack.
- `gdal_process_overhead = 128 MiB` plus the configured cache.
- Treat the native and GDAL phases as overlapping when multiple helpers are
  active, because one helper can build overviews while another still maps.

For a multi-file terrain, report both the sum and largest member. Use the sum in
the first conservative release. Calibration can move to the largest active
member only after telemetry proves RASMapper processes terrain members
sequentially without retaining shared caches.

### Worker selection

```text
reserve = max(user reserve, 25% physical RAM)
physical_budget = max(0, available physical RAM - reserve)
commit_budget = max(0, commit headroom - commit reserve), when available
memory_budget = min(physical_budget, commit_budget), when both are known
memory_limit = floor(memory_budget / estimated_worker_private_bytes)
selected = max(1, min(job_limit, cpu_limit, requested_ceiling, memory_limit))
```

Always return at least one worker so the established serial path remains
usable. Emit a warning if even one worker does not fit the estimate.

Examples using the current conservative Spring River estimate of approximately
12.1 GiB per worker:

- A 32 GiB workstation with about 18 GiB available selects one worker.
- A 64 GiB workstation with about 50 GiB available and a 16 GiB reserve can
  select two workers.
- A 128 GiB workstation with about 100 GiB available and a 32 GiB reserve can
  fit five workers by memory, but a WSE/Depth/Velocity job is capped at three.

These are planning estimates, not guarantees. The dynamic governor remains
authoritative during execution.

### Calibration

Each successful benchmark may write a portable calibration record keyed by:

- HEC-RAS version and hashes of `RasMapperLib.dll` and `TiffAssist.dll`.
- CPU logical/physical count.
- Physical RAM class.
- Terrain cell-count band and source-count band.
- Map type.
- Storage class: local NVMe, local SATA, SMB/shared storage, or unknown.
- GDAL cache/thread settings.

Use the measured p95 peak private-byte ratio plus a 25 percent safety factor.
Never let calibration reduce the configured floor. A calibration from another
HEC-RAS DLL hash is advisory only.

## Dynamic memory governor

Static estimates cannot catch fragmentation, other workloads, or a late GDAL
overview spike. The scheduler must sample the full helper process tree every
0.25 to 1.0 seconds.

At every dispatch decision:

1. Recalculate physical available memory and Windows commit headroom.
2. Do not start another job unless one estimated worker plus the reserve fits.
3. Pause queued jobs below the soft threshold.
4. Log a structured warning when a running worker exceeds its estimate.
5. By default, let an active helper finish rather than destroying a partially
   written map.
6. If explicit emergency abort is enabled and the hard threshold is crossed,
   terminate the helper tree, quarantine partial files, restore the `.rasmap`,
   and raise an exception containing the telemetry report.

## TIFF-writer optimization plan

The TIFF path must be profiled as a pipeline. Changing only the number of
mapping workers can hide or amplify its bottlenecks.

### Implemented copied-assembly result

The strongest proposed native experiment is complete for the pinned HEC-RAS
7.0 build. A copied `TiffAssist.dll` now uses bounded parallel tile snapshots,
serial-within-tile statistics, byte copy, independent Deflate encoders, pooled
buffers, and one raw destination commit owner. Client-I/O writes accept 64 KiB
through 64 MiB. The assembly fallback remains 256 KiB, queue depth 2, and zero
workers until explicitly selected; the benchmark runner now proposes 2 MiB
after a five-repeat 64 KiB–64 MiB sweep.

The isolated 8192 by 8192 writer improved from a 2.435-second original median
to 0.815 seconds at eight workers. Spring River plan 02 Depth Max improved from
112.21 seconds to 108.78 seconds at one worker but took 109.64 seconds at eight.
Spring's 4,825 data tiles arrived across an 84–85-second pipeline while
aggregate Deflate calls consumed about 25 seconds and raw commit under 0.7
seconds. Thus the reimplementation is correct and multicore-capable, but the
large-watershed run is upstream producer-paced.

The Spring pipeline coalesced 11,715 logical LibTiff writes into 494 underlying
writes. All installed/copy safety hashes, odd edge tiles, raw-NoData tile-zero
replacement, decoded pixels, TIFF layout/tags/statistics, and source HDF hashes
passed. Distribution and stable API exposure remain out of scope.

The expanded isolated sweep found a 2 MiB median of 0.747 seconds versus 0.797
seconds at 1 MiB. Requests from 4 through 64 MiB were not faster; 64 MiB took
0.854 seconds and raised median writer RSS from 71.8 to 100.0 MiB. Larger raw
storage writes can still help SMB, but TIFF seek/directory boundaries flush the
encoded buffer before its requested maximum is consistently reached.

### Production-safe controls

#### 1. Storage-location profiling

Run the same disposable project and output layout once on local fixed storage
and once on mapped/network storage. This is a benchmark dimension, not a
product feature: `store_maps()` will not stage, copy back, or redirect output
automatically.

The comparison must include project/input location as well as requested output
location because the compatible `StoreAllMaps` path initially writes beside the
project. Label every report with storage type, resolved drive spelling, and
project/output filesystem. Preserve mapped drive letters for HEC-RAS calls.

#### 2. GDAL cache cap

Set `GDAL_CACHEMAX` in each helper environment so descendant `gdaladdo`
processes inherit it. Profile 64, 128, 256, 512 MiB, and native default.

This setting targets overview memory and cache behavior. It does not change the
TiffAssist writer's memory allocation or queue.

#### 3. GDAL overview threading

Profile `GDAL_NUM_THREADS` values 1, 2, 4, and `ALL_CPUS` with each cache class.
GTiff can use threads for supported compression/decompression paths, but the
exact benefit depends on the GDAL version bundled with HEC-RAS.

Avoid `ALL_CPUS` for every concurrent helper by default. A scheduler should
allocate a total core budget across active helpers.

#### 4. Storage-aware reporting

Do not change scheduling based on filesystem type in this feature. Report local
versus network behavior so a later scheduling decision is evidence-based.
Production phase detection can treat an active helper plus no `gdaladdo` child
as native mapping/writing and a `gdaladdo` child as overview generation. Exact
native writer start/stop markers require helper instrumentation.

#### 5. I/O telemetry

Record read/write bytes and operation counts per process. Calculate mean bytes
per write and write IOPS. On Windows, supplement process counters with ETW/WPR
in the opt-in benchmark when available to capture actual request-size
distributions and latency.

The key diagnosis matrix is:

| Signal | Likely limiter |
|---|---|
| High writer CPU, low disk queue | Deflate, statistics, allocations, or GC |
| Low writer CPU, high write latency/queue | Storage or SMB small-write cost |
| High `gdaladdo` CPU and memory | Overview compression/cache phase |
| Producer queue near 50 continuously | Single TIFF consumer cannot keep up |
| Producer queue near zero | Terrain/HDF reads or map computation cannot feed writer |

### Writer variables for the research harness

The copied-assembly harness should make one change at a time and record the DLL
hash and patch manifest.

1. Tile dimensions: 256, 512, and 1024.
2. Producer queue high-water mark: 16, 50, 128, and 256 tiles.
3. Reusable buffer pool: 16, 64, 128, and 256 buffers.
4. Producer `MaxDegreeOfParallelism`: 1, 2, 4, 8, 16, 32.
5. TIFF ZIP quality: 1, 3, 6, and 9.
6. TIFF compression: Deflate level 1, uncompressed, LZW, and other codecs only
   when supported by the bundled library.
7. Statistics implementation: existing per-row `Parallel.For`, one serial
   vectorized pass, producer-side reduction, and no stats plus verified
   post-write GDAL statistics.
8. Byte-buffer allocation: allocate per tile, pool byte arrays, or reuse a
   writer-owned conversion buffer.
9. Consumer design: current single consumer versus the now-implemented bounded
   parallel compression plus single-owner raw-tile commit.
10. Histogram timing: native reread, piggyback on producer statistics, or one
    combined GDAL statistics/overview pass.
11. Overview strategy: inline serial, deferred after all base maps, or bounded
    parallel overview jobs.

Increasing the queue or tile size can reduce coordination/write-call overhead
but increases memory and latency. A 1024 by 1024 Float32 tile is 4 MiB; a
50-tile queue would then represent approximately 200 MiB before byte copies and
compression state. Queue and tile settings must therefore be modeled together.

Parallel calls into one destination TiffAssist/LibTiff writer remain unsafe.
The implemented design uses one private in-memory LibTiff encoder per worker and
one destination commit owner. Payloads carry tile numbers, and the commit order
may follow worker completion because the installed `ConcurrentBag` consumer is
also unordered. Exact decoded pixels, offsets interpreted by LibTiff, tags, edge
tiles, and raw-NoData replacement have been verified.

## Performance-profile matrix

Run each configuration at least three times after one warm-up on Bald Eagle.
Run the most promising and the safest configurations once on a disposable
Spring River copy, then repeat the winner to check variance.

### Supported matrix

| Dimension | Values |
|---|---|
| Map workers | 1, 2, auto |
| Cores per helper | unset, 2, 4, 8 |
| GDAL cache MiB | 64, 128, 256, 512, default |
| GDAL threads | 1, 2, 4, ALL_CPUS |
| Project/output storage | local fixed disk, mapped/network disk |
| Map set | WSE, Depth, Velocity, all three |
| Terrain layout | one TIFF, many-source VRT where available |

Use a fractional factorial design for the first pass; do not run the full
Cartesian product on Spring River.

### Metrics

- Wall time for configure, native map/write, histogram, overview, move, georef
  validation, and total.
- Per-process CPU seconds and maximum thread count.
- Peak RSS and private committed bytes for the process tree.
- Minimum physical available memory and commit headroom.
- Read/write bytes, operations, average request size, throughput, and latency.
- Output size and compression ratio against uncompressed cell bytes.
- Raster decoded-pixel hash plus CRS, transform, nodata, dimensions, block
  shape, compression, and overview levels.
- `.rasmap` and result HDF before/after hashes.

## Other realistic optimization options

The current implementation is not exhaustive. The following options remain,
ordered by expected value and supportability.

### High-value, supported or wrapper-level

1. Use independent helper processes for independent map types, bounded by
   memory and CPU budgets.
2. Cap per-helper GDAL cache to avoid a five-percent-of-machine cache in every
   concurrent overview process.
3. Allocate GDAL thread counts across helpers instead of giving every helper
   all CPUs.
4. Compare local and network project execution under identical settings and use
   the evidence for deployment guidance, without adding staging behavior.
5. Consolidate a many-source VRT only when source-open/seek overhead is measured
   and the consolidated raster will not create a large sparse bounding box.
6. Cache a validated consolidated terrain keyed by source hashes so the copy
   cost is paid once.
7. Schedule map jobs across existing RasRemote workers when local memory is the
   limiter and project staging cost is acceptable.
8. Keep Python-side validation and georeferencing block-streamed, as already
    implemented, so postprocessing never reads a whole raster into memory.

### Moderate-risk runtime experiments

1. Process affinity to limit nested oversubscription.
2. .NET ThreadPool minimum-thread tuning to reduce ramp latency. Raising the
   minimum can increase memory and context switching, so it is profile-only.
3. .NET workstation/server GC and concurrent-GC configuration in the packaged
   helper. Profile memory as carefully as time.
4. Process I/O priority and Windows file-cache behavior.
5. Deferred, bounded overview construction after all base maps finish.
6. Separate concurrency budgets for compute-heavy, writer-heavy, and
   overview-heavy phases.

### Invasive research options

1. Patch copied RASMapperLib/TiffAssist assemblies for queue, tile, buffer,
   statistics, compression, and native parallelism experiments.
2. Replace TiffAssist output with a custom GDAL/COG writer only if map values can
   be obtained tile-by-tile without unsupported shared state.
3. Use private `MapProcessingEngine` resample/extent methods to test spatial
   windows.
4. Reimplement the stored-map tile pipeline around public HEC result/terrain
   data. This is the largest effort and must reproduce HEC rendering semantics.

## Chunking and memory-pressure reduction

### What can be chunked safely now

- Python raster inspection, checksums, georeferencing, validation, and copying
  can operate block by block.
- Timesteps can be queued sequentially and dispatched through the same memory
  governor.
- Independent map types can be scheduled as separate jobs.
- Independent plans or disposable project copies can be distributed to remote
  workers.
- A many-file terrain can remain a VRT so the native code sees the established
  terrain members rather than one enormous new file.

### What cannot currently be chunked through the public StoreMap API

The public `StoreMapCommand` has no output window, extent, or tile-range
parameter. RAS Commander cannot ask it to compute rows 0 through N and then
resume. Spatial chunking therefore requires private native APIs, a patched
assembly, or a reimplementation.

### Research design for spatial chunks

If pursued, use overlapping windows aligned to the 256-cell native tile grid:

1. Partition the terrain extent into complete tile windows.
2. Add a halo sufficient for interpolation/rendering dependencies.
3. Compute each window into an isolated file and project copy.
4. Trim halos and stitch only complete inner tiles.
5. Preserve nodata, precision, statistics, CRS, and transform exactly.
6. Build global histogram and overviews after the mosaic is complete.
7. Compare the stitched raster pixel-for-pixel with native unchunked output,
   especially at window boundaries, breaklines, 1D interpolation surfaces, and
   2D mesh edges.

This remains research-only until pixel equivalence is proven across 1D, 2D,
and combined geometries. A smaller memory footprint is not acceptable if it
changes wet/dry boundaries or interpolation.

### Multi-terrain VRT guidance

Do not equate a named RAS Mapper terrain with one TIFF. The terrain HDF/VRT may
refer to multiple component rasters, and RASMapper can emit one stored-map TIFF
per component plus a VRT.

The preflight report should calculate:

- Source count.
- Sum of source cells and bytes.
- Union bounding-box cells at the target resolution.
- Overlap fraction.
- Estimated consolidated size and BigTIFF requirement.
- Local/remote storage classification.
- Expected source-open count per map.

Recommend consolidation only if repeated source-open/seek costs are material,
the union raster is not mostly sparse, and the cached consolidated terrain will
be reused enough to amortize conversion. Spring River's active one-source VRT
does not qualify.

## Test and acceptance plan

### Unit tests

- `inspect.signature()` locks the legacy positional prefix, including positional
  `terrain_name` and `benefit_area`, and verifies new controls are keyword-only.
- Resource estimate fields and formula version.
- Worker selection at simulated 16, 32, 64, and 128 GiB memory states.
- Physical-memory and commit-headroom limiting cases.
- Legacy keyword and configuration conflict handling.
- `GDAL_CACHEMAX` and `GDAL_NUM_THREADS` propagation to helper descendants.
- Storage classification and report labeling for local and mapped/network paths.
- No parallel path for shared derived-map HDF products.
- Unsupported/benefit-area paths return fallback reasons and reject rather than
  ignore non-default unsupported performance settings.
- Static namespace, decorator, path-type, and `plan_number` API conventions.

### Bald Eagle integration

- Serial-default output remains pixel-identical.
- Two-worker WSE/Depth/Velocity run achieves at least 1.6 times speedup on the
  reference machine unless telemetry identifies storage saturation.
- Local-storage and network-storage runs produce identical decoded raster hashes.
- Failure restores the `.rasmap` and stops all helper descendants.

### Spring River integration

- Preflight identifies one terrain source and does not recommend consolidation.
- Automatic scheduling selects one worker on the current 32 GiB machine.
- Minimum available memory remains above the configured reserve.
- Output decoded-pixel hashes match the established fixture:
  - WSE: `3c75b6bf28380c191a02ba456c3683d70fba0b3c0b14d9023478456cbb5a413a`
  - Depth: `aa74abd3e99871adf9ec2c945460ef290dd0c6ed7ad80d51c9fee84f65fc61e1`
  - Velocity: `dda7ef4464ab744f47616d89283c095e0312de2d8091ac7c5d30b27cd364e4ac`
- `.rasmap` and result HDF hashes are unchanged after the run.
- Profile default, 128 MiB, 256 MiB, and 512 MiB GDAL caches. Select a new
  default only if peak memory improves materially without more than a 15
  percent wall-time regression.
- Compare identical disposable projects on network and local storage and report
  native writer time, write operation count, average write size, and overview
  time separately.

### Research acceptance gates

Any copied-assembly optimization must satisfy all of the following before it is
considered for a supported path:

- Exact HEC-RAS version and input DLL hashes are recognized.
- Patched assemblies live only in a unique scratch directory.
- The installed HEC-RAS directory is not modified.
- All output raster decoded-pixel hashes, geospatial metadata, nodata,
  statistics, histograms, and overview layouts match unless the experiment
  explicitly targets a format difference.
- At least 20 percent repeatable wall-time improvement or 30 percent peak-memory
  improvement on a target fixture.
- Clean cancellation, partial-file quarantine, and reproducible patch manifest.
- Explicit opt-in warning that the path is experimental and unsupported by HEC.

## Delivery phases

### Phase 1: estimator and telemetry

- Restore the complete legacy `store_maps()` positional signature and add only
  keyword-only performance controls.
- Add public configuration and estimate/report dataclasses.
- Promote the current private estimator into the public read-only API.
- Add commit-headroom checks and versioned JSON telemetry.
- Add I/O operation counts and phase timing to the benchmark.
- Document Spring River baseline and formula calibration.

### Phase 2: supported tuning

- Propagate `GDAL_CACHEMAX` and core-budgeted `GDAL_NUM_THREADS`.
- Add dynamic memory admission and detailed local/network storage reporting.
- Benchmark Bald Eagle and Spring River and select conservative defaults.

### Phase 3: terrain optimization

- Add terrain topology report and consolidation recommendation.
- Add cached, opt-in VRT consolidation with space estimation and validation.

### Phase 4: native research harness

- Implement copied-assembly patch manifests.
- Profile statistics/allocation, tile size, queue depth, compression, and
  producer parallelism independently.
- Decide from evidence whether any native optimization is supportable.

## API and documentation checklist

- Replace feature-path `Path.resolve()` calls with
  `RasUtils.safe_resolve()` so mapped-drive spelling remains usable by HEC-RAS.
- Export new public dataclasses through the appropriate package `__all__`.
- Add docstrings and API docs with supported versus research settings clearly
  labeled.
- Do not change DataFrame columns; `schemas.py` requires no change unless a new
  public DataFrame is introduced.
- Keep original projects immutable in benchmarks by using disposable copies.
- Keep large rasters, extracted projects, DLL copies, patch artifacts, and
  benchmark outputs under ignored working directories.
- Add a feature-development note linking the API consistency audit, this spec,
  benchmark commands, and final acceptance evidence.

## Reference documentation

- GDAL configuration options, including `GDAL_CACHEMAX`, `GDAL_NUM_THREADS`,
  and `GDAL_SWATH_SIZE`: https://gdal.org/en/stable/user/configoptions.html
- GDAL GTiff threading and compression options:
  https://gdal.org/en/stable/drivers/raster/gtiff.html
- GDAL overview generation: https://gdal.org/en/stable/programs/gdaladdo.html
- .NET `ParallelOptions.MaxDegreeOfParallelism`:
  https://learn.microsoft.com/en-us/dotnet/api/system.threading.tasks.paralleloptions.maxdegreeofparallelism
- .NET ThreadPool maximum and minimum controls:
  https://learn.microsoft.com/en-us/dotnet/api/system.threading.threadpool.setmaxthreads
  and
  https://learn.microsoft.com/en-us/dotnet/api/system.threading.threadpool.setminthreads
