# API and release handoff

## Audit disposition

The API consistency auditor reviewed the StoreMap wrappers, native helper,
terrain functions, tests, fixture, estimator concept, and profiling contract.
Its initial verdict was changes requested before merge. All blocking items
below are now resolved in the implementation and covered by focused tests.

The auditor's scratch/staging recommendations predate the product direction in
this task and are superseded. No scratch fields or automatic staging behavior
belong in the feature API. Local and network paths remain profile/report
dimensions.

## Blocking corrections

Resolution status:

| Audit item | Resolution |
|---|---|
| Legacy positional prefix | Preserved; `RasMap.store_all_maps()` keeps its first four slots and all new controls are keyword-only |
| Typed estimator | `RasProcess.estimate_store_map_resources()` returns a frozen result |
| Memory semantics | Floor and explicit override are separate, with override policy validation |
| Live admission | Physical memory and Windows commit are checked before every launch |
| Mapped-drive spelling | Absolute mapped paths are preserved; no UNC coercion is performed |
| Terrain defaults | Existing child runtime behavior remains the default (`None`) |
| Profiling return contract | Separate frozen StoreMap and generic raster profile results |
| TIFF options | Separate frozen `GeoTiffWriteOptions`; no implication for native TiffAssist |

### 1. Restore positional compatibility

The prototype inserted `max_workers`, `memory_per_worker_mb`, and
`reserve_memory_mb` before the legacy `terrain_name` and `benefit_area` slots in
`RasProcess.store_maps()`. Existing positional calls can bind incorrectly.

Keep every legacy positional slot unchanged and append one keyword-only
configuration object:

```python
def store_maps(
    # unchanged legacy parameters in unchanged order
    _log_summary: bool = True,
    terrain_name: Optional[str] = None,
    benefit_area: Optional[BenefitAreaConfig] = None,
    *,
    performance: Optional[StoreMapPerformanceOptions] = None,
) -> Dict[str, List[Path]]:
    ...
```

Add an `inspect.signature()` regression test and positional tests for
`terrain_name` and `benefit_area`.

### 2. Add a typed, non-mutating estimator

Users need to preview worker selection and memory assumptions before editing a
project or launching a helper:

```python
RasProcess.estimate_store_map_resources(
    plan_number: str,
    map_types: Sequence[str] = ("wse", "depth", "velocity"),
    *,
    terrain_name: Optional[str] = None,
    performance: Optional[StoreMapPerformanceOptions] = None,
    ras_object=None,
) -> StoreMapResourceEstimate
```

This method must not edit `.rasmap`, create output folders, or start native
processes.

### 3. Make memory semantics explicit

The prototype's `memory_per_worker_mb` is a minimum floor, not an estimate or a
true override. Rename and separate those meanings. `max_workers` is a ceiling,
not a promise.

### 4. Add live admission control

The original prototype sampled memory once before submitting jobs. The
release implementation must resample available physical memory and Windows
commit headroom immediately before every helper launch. It should stop admitting
new work below the reserve, cancel queued jobs after a failure, and terminate
only process trees owned by the current invocation when explicit emergency
termination is enabled.

### 5. Preserve mapped-drive spelling

Do not call `Path.resolve()` on paths passed to HEC-RAS. Use the repository's
safe path handling and preserve mapped drive letters such as `H:`.

### 6. Restore compatibility-first terrain defaults

Appending `gdal_num_threads` is signature-safe, but changing every terrain
creation call to `ALL_CPUS` by default is a global behavior change. Use `None`
for `create_terrain_hdf()` and `create_terrain_from_rasters()` unless an
explicit optimized option is requested. Direct `vrt_to_tiff()` likewise uses
`gdal_num_threads=None` unless the caller explicitly opts into threading.

## Proposed stable contracts

### StoreMapPerformanceOptions

```python
@dataclass(frozen=True)
class StoreMapPerformanceOptions:
    max_workers: Optional[int] = 1
    memory_policy: Literal["enforce", "warn", "ignore"] = "enforce"
    minimum_worker_memory_mb: int = 600
    worker_memory_override_mb: Optional[int] = None
    reserve_memory_mb: int = 4096
    reserve_memory_fraction: float = 0.25
    gdal_num_threads_per_helper: Optional[Union[int, Literal["ALL_CPUS"]]] = 1
    gdal_cachemax_mb: Optional[int] = None
    admission_wait_timeout_seconds: float = 300.0
    admission_poll_interval_seconds: float = 1.0
```

Rules:

- `max_workers=1` preserves legacy execution.
- `max_workers=None` means automatic selection.
- `max_workers=N` remains a ceiling subject to safety limits.
- automatic selection retains the ordered one-helper path for explicit terrain,
  arrival/duration, inundation-boundary, and other non-independent products;
  an explicit worker count above one rejects those combinations.
- `worker_memory_override_mb` is valid only with an explicit non-default policy
  and must be prominently logged.
- the effective reserve is the larger of the absolute and fractional reserve;
- environment changes must be confined to child-process environments;
- the object is forwarded unchanged through `store_maps_at_timesteps()` and
  configured modes of `RasMap.store_all_maps()`.

### Unified RasMap entry point

`RasMap.store_all_maps()` is the one canonical orchestration function:

- `mode="native"` invokes the historic all-configured-map command;
- `mode="selected"` generates selected products for one or more plans;
- `mode="timesteps"` generates selected timestep products;
- `mode="all_plans"` runs the selected-product pipeline for every plan with a
  result HDF; and
- `mode="auto"` preserves a plain historic call while inferring configured
  modes from keyword-only arguments.

All modes return a consistent summary with `success`, `mode`, `plans`, and
`render_mode`. The old `RasProcess.store_all_maps()` name warns, forwards to
`mode="all_plans"`, and temporarily unwraps the legacy dictionary shape.

| Mode | Plan selection | Product defaults | Output controls | Rejected controls |
|---|---|---|---|---|
| `native` | one or more explicit plans | existing `.rasmap` configuration | existing native Plan ShortID paths | every configured-map keyword |
| `selected` | one or more explicit plans | WSE, Depth, Velocity | `output_folder` is the relative `.rasmap` StoredFilename name; `output_path` is the real destination | timestep selectors |
| `timesteps` | one or more explicit plans | Depth only | `output_path` only; multiple plans receive `plan_XX` children | `output_folder`, `profile`, `arrival_depth`, `terrain_name`, `benefit_area`, and whole-simulation products |
| `all_plans` | omit `plan_number`; plans without result HDF are skipped | WSE, Depth, Velocity | one `plan_XX` destination child per plan | timestep selectors and an explicit `plan_number` |
| `auto` | inferred | historic plain calls stay native; advanced calls route as above | follows the resolved mode | follows the resolved mode |

An explicit product selection must contain at least one enabled product. Empty
native plan sequences and empty configured selections raise before any project
mutation. Every successful mode summary is directly `json.dumps()` compatible.

### StoreMapResourceEstimate

Use a frozen public dataclass containing at least:

- normalized plan number, requested map types, and job count;
- active terrain paths, dimensions, cells, dtype, and raw Float32 MiB;
- formula version, heuristic/override/floor source, multiplier, fixed overhead,
  explicit per-helper GDAL cache cap, and estimated peak private memory per
  worker;
- total/available physical memory and Windows commit headroom;
- absolute and fractional reserve;
- CPU, memory, request, and job limits plus the selected worker count;
- warnings and fallback reasons, including fail-closed selection when active
  terrain dimensions cannot be inspected;
- CPU, memory, request, and job-count limits;
- selected worker count;
- `parallel_eligible` and typed `fallback_reasons`;
- warnings and a JSON-serializable `to_dict()`.

### Profiling result

Profiling is promoted through a separate result and does not add metadata to
the established map-list dictionary:

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

The opt-in profiler accepts a dedicated destination and writes a report there
by default; callers can supply an explicit report path. The example notebook
uses unique output roots and keeps all heavy switches disabled by default.
Every interval sample contains CPU utilization, process-attributable throughput
and IOPS, mean request size, private/RSS memory, physical and commit headroom,
host-wide disk/network counters, and an inferred native/GDAL/Python phase.
Host counters are explicitly labeled machine-wide; process counters include
cached and SMB transfers. Exact physical queue depth remains an ETW/PerfMon
benchmark concern rather than a portable API promise.

### GeoTiffWriteOptions

General GDAL TIFF creation has supported controls that native TiffAssist does
not. Keep the contracts separate:

```python
@dataclass(frozen=True)
class GeoTiffWriteOptions:
    compression: Literal["LZW", "DEFLATE", "ZSTD", "NONE"] = "LZW"
    compression_level: Optional[int] = None
    predictor: Optional[Literal[1, 2, 3]] = None
    tile_size: Optional[int] = None
    bigtiff: Literal["IF_SAFER", "IF_NEEDED", "YES", "NO"] = "IF_SAFER"
    gdal_num_threads: Optional[Union[int, Literal["ALL_CPUS"]]] = None
    gdal_cachemax_mb: Optional[int] = None
    create_overviews: bool = True
    overview_levels: Tuple[int, ...] = (2, 4, 8, 16, 32)
    overview_resampling: Literal[
        "nearest", "average", "average_mp", "average_magphase", "cubic",
        "cubicspline", "lanczos", "gauss", "mode"
    ] = "average"
    overview_compression: Optional[str] = None
```

Append `write_options=` as keyword-only without changing existing scalar slots.
Reject conflicting scalar and object values. Validate codec-specific levels,
supported predictor values, tile sizes divisible by 16, and overview levels
before starting GDAL. Do not imply that these options affect native StoreMap
TIFFs.

## Public versus experimental controls

| Control | Stable API | Experimental harness only |
|---|---|---|
| Number of independent map helpers | Yes | |
| Memory policy/reserve/admission | Yes | |
| Child GDAL threads/cache | Yes | |
| General GDAL TIFF codec/tile/overview options | Yes | |
| Native TiffAssist tile size | | Yes |
| Native writer queue/buffer pool | | Yes |
| Native tile preparation/Deflate workers | | Yes |
| Native client-I/O batch size | | Yes |
| Native Deflate level/codec | | Yes |
| Native producer parallelism | | Yes |
| Native histogram/statistics suppression | | Yes |
| CLR GC/thread-pool/affinity overrides | | Diagnostic only |

## Release phases

### Phase 1: API and safety

- restore positional compatibility;
- add frozen public option and estimate dataclasses;
- implement read-only estimation;
- implement live physical/commit admission;
- preserve serial defaults and mapped paths;
- forward options consistently through all wrappers;
- add package exports and API docs.

### Phase 2: supported optimization

- enable bounded independent map helpers only when requested;
- add child-scoped GDAL cache/thread controls;
- add general GDAL TIFF write options;
- keep profile scripts opt-in and raw artifacts ignored;
- add future mesh/result-HDF/output predictors and calibrate memory by
  HEC-RAS/DLL version, map type, and terrain size class.

### Phase 3: native writer research

- maintain the implemented copied-assembly, DLL-hashed benchmark mode;
- retain the implemented write batching, statistics/allocation, bounded queue,
  buffer-pool, and parallel compression controls as experimental only;
- continue unimplemented tile-size, codec/level, producer, histogram, and
  overview experiments;
- promote nothing without pixel, metadata, GUI-open, memory, and repeated timing
  evidence.

The HEC-RAS 7.0 research result is technically successful but not a stable API:
an isolated writer was 66.5 percent faster at eight workers, while Spring River
improved only 3.1 percent at one worker and did not improve at eight. Spring's
tile producer spanned about 84 seconds versus about 25 aggregate Deflate-call
seconds and under 0.7 seconds of raw commit. This makes `pipeline_workers` a
profile-selected experimental setting, not an automatic production default.

The safe copied-harness defaults are 256 KiB client-I/O batches, queue depth 2,
serial-within-tile statistics, and zero pipeline workers. The manifest pins all
input hashes and confirms the installed files were never opened for write.

## Acceptance criteria

- Legacy calls have identical default behavior and positional binding.
- Automatic worker selection is explainable through a read-only estimate.
- Spring River never launches a second helper under the tested 32 GiB memory
  conditions.
- Bald Eagle three-map auto retains at least a repeatable 30 percent wall-time
  reduction on both local and network paths.
- Decoded pixels, CRS, transform, NoData, dimensions, and required overviews are
  equivalent across serial and optimized modes.
- `.rasmap` and HDF state are restored on success and failure.
- No benchmark observer performs recursive network enumeration during timing.
- No automatic scratch, staging, or copy-back behavior is present.
- Copied-assembly edge tiles, raw-NoData tile zero, metadata, statistics, and
  source-HDF preservation remain equivalent to the installed runtime.
