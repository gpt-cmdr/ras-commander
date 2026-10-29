# Native FIM mapping performance

Use `RasFim.map_horizontal_profiles()` for cell-constant horizontal mapping or
`RasFim.map_sloping_profiles()` for cell-corner sloping. Both methods map
physical 2D cells, reject models containing 1D river/cross-section geometry,
and support bbox/polygon output constraints. Rust reads numeric HDF inputs,
rasterizes ownership through terrio, reconstructs sloping surfaces and maps
pixels with bounded Rayon workers. Python manages requests and GeoTIFF delivery.
Production mapping requires no HEC-RAS assemblies.

## Final implementation versus RASMapper

| Model | Physical 2D cells | Interpolation | RASMapper (s) | Final Rust pipeline (s) | RASMapper / Rust | Raw comparison |
|---|---:|---|---:|---:|---:|---|
| eBFE Spring River | 422,715 | Horizontal | 230.787 | 91.462 | 2.52× | Exact mask and values (2D) |
| eBFE Spring River | 422,715 | Sloping: cell corners | 240.726 | 79.098 | 3.04× | Exact mask and values (2D) |
| eBFE Spring Creek | 340,163 | Horizontal | 190.275 | 99.050 | 1.92× | Exact mask and values (2D) |
| eBFE Spring Creek | 340,163 | Sloping: cell corners | 209.896 | 88.724 | 2.37× | Exact mask and values (2D) |
| Bald Eagle dam break | 87,039 | Horizontal | 7.693 | 5.855 | 1.31× | Exact mask and values (2D) |
| Bald Eagle dam break | 87,039 | Sloping: cell corners | 7.393 | 5.976 | 1.24× | Exact mask and values (2D) |
| Bald Eagle bridges | 24,718 | Horizontal | 8.897 | 4.935 | 1.80× | Exact mask and values (2D) |
| Bald Eagle bridges | 24,718 | Sloping: cell corners | 8.585 | 3.157 | 2.72× | Exact mask and values (2D) |
| Davis pipes/conduits | 2,716 | Horizontal | — | — | — | Native export failed |
| Davis pipes/conduits | 2,716 | Sloping: cell corners | 1.909 | 0.527 | 3.62× | Exact mask and values (2D) |


The table reports the final qualified horizontal/sloping implementation's
2026-10-26 Windows measurements against native RASMapper 7.0.1. Both Depth and
WSE have identical complete validity masks and valid float32 bits within the
physical 2D footprint. There is no added depth cutoff, reference filtering or
resampling. Equality only where both rasters are valid is insufficient.

Native exports/times were retained from the same-day reference run; Rust 0.7.0
was measured afterwards rather than interleaved. Engine 0.7.1 removes an
unreleased control without changing these horizontal/plain-sloping kernels.
These measurements are observations, not a universal speed guarantee.

Each row maps one Max Depth/WSE pair on the complete native pixel lattice,
nodata border and storage layout. The clock includes HDF preparation, launch,
mapping and output delivery. Native/project initialization, canonical terrain
preparation and comparison scanning are outside the clocks. Sloping uses
metadata-only direct-template delivery. Horizontal includes cell-table
preparation and a matching-grid raster rewrite using one compression worker.
No floodplain polygonization or profile concurrency is included.

Processes inherit four-CPU affinity. Rust mapping and initial compression each
use four workers; native export requests one worker. The first horizontal
bridge clock includes dependency imports; later calls use warm imports.
No mapping warm-up is excluded. Filesystem caches and shared-workstation load
are uncontrolled.

The dam-break reference also renders standalone storage-area surfaces outside
physical 2D cells. Those pixels are excluded from comparison, but their native
rendering time is included. Its ratio therefore compares the measured workflows,
not equal work outside the supported scope. Davis horizontal native export
failed with exit 99; no time or ratio is claimed. See issue
[#678](https://github.com/gpt-cmdr/ras-commander/issues/678).

## Plain sloping development qualification

Native 7.0.1 Max qualification covers Spring River (422,715 physical cells),
Spring Creek (340,163), Bald Eagle dam break (87,039), Bald Eagle bridges
(24,718), and Davis pipes/conduits (2,716). Windows checks cover the full
physical 2D footprints; Linux eBFE evidence is bounded while retaining global
topology. Davis also covers stored timestep indices 54 and 108. Other native
versions, 1D surfaces, and standalone storage areas remain outside this evidence.

The optional unweighted `render_mode="slopingPretty"` adds cell faces.
Its shallow-to-horizontal control can be off or on. Both settings match raw
native bridge Max and Davis 54/108 masks and float32 bits with one/four workers
on Windows and Linux. No elapsed-time comparison is claimed for this mode here.

## Complete horizontal validity

`horizontal-cell-constant/2` evaluates native binary32
`WSE >= float32(terrain + 0.001)` before depth subtraction. A post-subtraction
cutoff is not equivalent. Zero optional `min_depth` adds no cutoff and preserves
native-valid zero depths. Rust and the explicit NumPy reference use this rule;
older /1 engines raise explicitly.

Full Windows Spring River, Spring Creek, dam and bridge Max checks have zero
extra, missing, bit-different or outside-footprint pixels for both bands.
Spring River, Spring Creek and bridges also match the entire native raster
grid, including nodata borders, without a footprint mask. The dam reference
contains 464,445 standalone storage-area pixels outside physical 2D scope.
Comparison metrics retain valid zero depths and compare float32 bits, including
signed zero.

## Catalog throughput

```python
manifest = RasFim.map_sloping_profiles(
    "model.p02.hdf", "canonical_terrain.tif", "reach_catalog",
    profiles={"maximum": "Max", "t0054": 54},
    polygon="reach_boundary.gpkg",  # or bbox=(xmin, ymin, xmax, ymax)
    threads=4, writer_threads=1, max_inflight_profiles=2,
)
```

Geometry, stencils, terrain and ownership are shared across profiles in one
request. Effective profile concurrency is capped by requested concurrency,
worker count, profile count and planned memory. One Rayon pool bounds native
work. Results stream in request order. The default remains one in-flight
profile. Memory admission is planned rather than a hard RSS limit.

AOIs constrain terrain/ownership/output pixels while retaining the complete
hydraulic topology and cell results needed at boundaries. Omit
`template_raster` for compact catalog outputs; a metadata-only template supports
delivery on the complete native grid. Compression workers have a separate
budget and may overlap native workers. GDAL settings are restored on success
and failure.

## Prepared model contexts across reach requests

For repeated reach requests, use `RasFim.prepare_sloping_model()` as a context
manager. It retains physical cell polygons/indexing, scope, terrain metadata and
complete staged mesh/WSE files. Repeated selectors share files. With
`native_session=True` (default), capable engines also retain a serialized native
process, geometry/stencils and decoded terrain tiles. Released Fast-Map 0.10.1
retains one bounded last-window cache and reconstructs hydraulic values per
profile. Development engines with `hydraulic_cache` and `multi_window_cache`
also reuse reconstructed timesteps and retain multiple windows under explicit
ceilings; see the retained-state measurements below. `native_session=False`
explicitly uses a fresh CLI per request. Source size/mtime changes invalidate the
context; close waits for active calls and releases the process and staging.
The catalog study below separates setup costs from warm-call observations.

## Caller-supplied WSEL qualification

The `wsel_profiles=` input on `map_sloping_profiles()` and
`prepare_sloping_model()` was checked against their existing HDF-selector path
on 2026-10-27 using the computed public Davis pipes/conduits model. The complete
input has two meshes, 2,716 physical cells and 261 ghost cells. Three supplied
columns reproduce Max and stored indices 54/108. Rows are shuffled before
mapping. Source HDF and terrain hashes are checked before and after the run.

Both plain sloping and unweighted cell-face sloping have **zero complete-mask
differences and zero valid float32-bit differences** for Depth and WSE on each
135,930-pixel output grid. These checks include one-shot supplied mapping and
prepared mapping after the original DataFrame is changed. Supplied calls block
stored-result reader entry points to detect selector fallback. Invalid missing
rows are rejected even for an empty AOI. Separate checks compare explicit NaN
dryness with the documented finite marker, and selector/supplied mapping on a
task-owned modified terrain TIFF; the source terrain remains unchanged.

| Platform | Method | HDF-selector call (s) | Supplied-WSEL call (s) |
|---|---|---:|---:|
| Windows x64, Python 3.13.12 | Sloping: cell corners | 0.705 | 0.388 |
| Windows x64, Python 3.13.12 | Sloping: corners + unweighted faces | 0.388 | 0.394 |
| Linux x64 (WSL), Python 3.11.15 | Sloping: cell corners | 2.040 | 1.025 |
| Linux x64 (WSL), Python 3.11.15 | Sloping: corners + unweighted faces | 1.069 | 0.916 |

Each clock maps all three profiles and includes preparation, launch and delivery.
Building the supplied table is outside its mapping clock; comparison scanning
is outside both clocks. The selector uses one worker/one in-flight profile;
the supplied call uses four workers/two in-flight profiles. These are single
qualification observations with uncontrolled caches and workstation load,
**not a throughput comparison or a speedup ratio**. There is no added depth
cutoff. Engine wheels are Fast-Map 0.8.0 and Fast-HDF 0.2.3 on both platforms;
Commander is an unreleased source change based on 0.110.1.

This proves that supplied vectors matching selectors retain the existing
reconstruction on this fixture. It does not establish RAS Mapper parity for
arbitrary window aggregates, healed terrains or other option combinations.
No new native RAS Mapper exports or hydraulic computations were run for this
input-contract change. Existing native qualification above remains separate.

Run `scripts/benchmarks/fim_supplied_wsel_compare.py case.json new_output` with
`hdf`, `terrain` and a `profiles` object mapping names to `"Max"` or integer
indices; `engine` is optional. The receipt records canonical input-vector hashes,
source/engine hashes, timings and complete-mask/bit metrics. Opt-in pytest uses
`RAS_COMMANDER_SUPPLIED_WSEL_CASE` with the same case file. See the
[input contract and CSV example](../api/fim.md#supply-cell-wsel-profiles).

## Global-lattice AOI qualification (engine 0.10.1)

On 2026-10-28, the global-lattice polygon rule passed **96 bounded-map cases**
and **480 Depth/WSE band comparisons** on Windows x64/Python 3.13.12, using a
locally built and installed Fast-Map 0.10.1 release wheel and Fast-HDF 0.2.3.
Davis pipes/conduits covers Max, indices 54/108 and a supplied cell-level
maximum of the two timesteps rounded to three decimals. Bald Eagle bridges
covers Max. Both retain complete physical/ghost input coverage.

Each model runs horizontal, plain sloping and all four face-weighting/shallow
combinations, with a bbox, triangle, concave polygon, holed polygon, multipart
polygon, narrow diagonal sliver, tile-crossing polygon and a deliberate
pixel-center edge case. Both source terrains use 256 × 256 tiles. Four native
workers are used; sloping allows two in-flight profiles. No depth cutoff is
added. All extra/missing and valid float32-bit difference counts are zero.

The reference is the full Rust result masked on the **global source lattice**
by a separate NumPy implementation of the declared half-open rule. Missing
reference-valid pixels outside a candidate's raster extent also fail the
comparison. All 12 unbounded model/method combinations additionally match the
retained pre-fix products exactly: 60 band comparisons, complete masks and
valid float32 bits. Source HDF, terrain and executable hashes bracket the run.
This checks crop invariance; no new RAS Mapper export or hydraulic computation
was performed, and it does not qualify native parity for the supplied aggregate.

Linux x64/Python 3.11.15, using the CI-built manylinux 2.28 wheel, additionally
passes Davis bbox and pixel-center-edge AOIs for all six configurations:
12 cases and 96 band comparisons. Its full and bounded Davis products also
match Windows in 144 cross-platform band comparisons. Seven global-mask unit
tests pass on Linux. A prepared, depth-weighted/shallow Davis context separately
passes the pixel-center-edge full/crop check on Windows. Other Linux model/shape
combinations were not run for this change.

The original GDAL full-grid versus cropped-grid mask fails six Davis
pixel-center edge cases. The new rule intentionally replaces that ambiguous
coverage; these results are **not** a claim of equality to legacy GDAL masks at
boundary ties. See the [explicit coverage contract](../api/fim.md#global-terrain-lattice-aoi-coverage-engine-0101).

A synthetic 2048 × 2048 rectangular-mask observation with four workers and
20 warm iterations took 19.8 ms per mask through terrio and 24.7 ms through the
new global-lattice kernel. It measures the mask kernel, not catalog throughput;
the approximately 4.9 ms difference is shared once per mapping request, rather
than repeated for each profile. This is one uncontrolled workstation observation,
not a speed guarantee or an end-to-end performance comparison.

Run `scripts/benchmarks/fim_aoi_full_crop_compare.py CASE.json NEW_OUTPUT` from
the checkout with its root on `PYTHONPATH`. The case contains `engine`,
`commander_commit` and `models`: each model has `label`, `hdf`, `terrain`,
`profiles` and optional `max_working_mib`. Optional `modes`/`shapes` lists bound
the qualification scope. `baseline_root` optionally checks retained unbounded
products organized as `label/method/full/fim_manifest.json`. Receipts preserve
per-band counts, geometry, grids, versions and hashes, including failures.
The opt-in real test uses `RAS_COMMANDER_AOI_LATTICE_CASE`. Datasets and generated
rasters stay external to the repository.

## Reproduce comparisons

`scripts/benchmarks/fim_sloping_compare.py` maps an external case and compares
raw Depth/WSE masks and float32 bits to retained native references. Use
`--match-reference-grid` for nodata-border delivery. Its receipt separates
mapping time from comparison scanning and records input/reference identities.
`scripts/benchmarks/fim_horizontal_parity.py` reproduces horizontal qualification
without invoking HEC-RAS or filtering the references.

Real-model pytest cases use `RAS_COMMANDER_SLOPING_CASE` and
`RAS_COMMANDER_SLOPING_OPTIONS_CASES`; datasets and generated rasters stay
external. The latter selects all four face-weighting/shallow combinations. Tests cover single/multiple
workers, AOIs, timesteps, bounded concurrency, delivery failures and context
lifecycle. Installed-wheel smoke covers file and streaming delivery on Windows,
Linux and glibc 2.28. Retained wheel hashes and source provenance from that
qualification remain in the [pre-extraction source snapshot](https://github.com/gpt-cmdr/ras-commander/tree/c7f910139af3c4df18ae421473dfbebbcf85fec5/wheels).
Current builds and releases belong to the external
[ras-commander-fast-map repository](https://github.com/gpt-cmdr/ras-commander-fast-map).
Step05 remains a separate ras2fim-2D method; its products are not
RASMapper sloping products.

## Depth-weighted sloping faces (engine 0.8)

Use `render_mode="slopingPretty", use_depth_weighted_faces=True` with
`RasFim.map_sloping_profiles()` or `prepare_sloping_model()`. Stored corner ground
elevations come from the native HDF reader. When absent from the plan, call
`RasFim.prepare_corner_elevations()` explicitly on Windows/HEC-RAS 7.0.1, then
pass its `postprocessing_hdf` to mapping. Preparation uses the registered terrain
and native corner sampler or stored property-table values. A receipt binds the
cache to its plan and terrain sources. Preparation is a separate operation and
clock; ordinary mapping loads no HEC-RAS runtime.

The final 0.8.0 Windows engine produced these Max-profile results against native
7.0.1 **Sloping (Cell Corners + Cell Faces)**, with depth weighting and
shallow-to-horizontal enabled. No additional depth cutoff or reference
resampling was applied. Each Depth and WSE comparison has zero extra valid,
missing valid, differing float32-bit, or outside-footprint pixels.

| Model | Valid pixels per band | RASMapper mapping (s) | Rust mapping (s) | RASMapper / Rust |
|---|---:|---:|---:|---:|
| Spring River | 42,633,555 | 467.13 | 63.68 | 7.34× |
| Spring Creek | 111,408,171 | 418.99 | 76.17 | 5.50× |
| Bald Eagle dam break | 727,989 | 11.54 | 6.50 | 1.78× |
| Bald Eagle bridges | 974,256 | 12.50 | 4.43 | 2.82× |
| Davis pipes/conduits | 21,114 | 3.44 | 0.71 | 4.81× |

River, Creek and bridges match the complete native raster grid, including
nodata borders. Dam and Davis use the physical 2D footprint; standalone
storage-area surfaces are excluded. The dam native call includes additional
storage-area work. These are workflow mapping times, not isolated kernel times.
The Rust clock includes HDF staging, mapping and Depth/WSE delivery. Comparison
scanning and explicit corner preparation are excluded. Fresh corner preparation
took 38.78 s for River, 57.51 s for Creek and 1.84 s for Davis; the first two ran
while builds competed for resources, so they are not controlled preparation
benchmarks. Reuse prepared corners across timesteps and catalog requests.

Both processes had the same four-CPU affinity budget. Rust used four workers
and four compression workers, with one in-flight profile. Native export used
one stored-map worker. Calls ran sequentially per model on a shared workstation;
the River native reference was retained from an earlier same-day call and
compared to the final engine afterward. These are single observations with
uncontrolled filesystem caches, not repeated or interleaved benchmark estimates.
Source HDF hashes and original rasmap bytes were verified unchanged; affinity
was restored. This table does not re-time horizontal or plain sloping in 0.8.

Matching cell-face output also requires native donation history. Where adjacent
clipped corner weights sum to zero, the native implementation retains donor
scratch values from preceding pixels inside fixed 256-point ranges, per source
terrain tile. The engine detects affected cells and replays their complete
physical geometry in parallel by cell. Ordinary pixels retain the independent
parallel path. AOIs replay the required predecessor geometry outside the output
mask without reading extra terrain there. Clearing scratch independently per
pixel changes the native output and must not be substituted as an optimization.

Qualification preserves the native source TIFF grid and 256-square tile layout.
Arbitrarily cropped/retiled terrain and multi-source terrain mosaics are not
qualified for cell-face matching. Mapping-time bbox/polygon constraints preserve
that original grid and history. A difficult River bbox and polygon both match
raw native masks and bits with one/four workers. Windows and Linux cache-only
Davis mapping also match with one/four workers, and changed caches invalidate
prepared contexts. All four face/shallow combinations and Davis timesteps
54/108 pass on Windows and Linux. Full-extent Linux eBFE, other native versions,
and terrain-modification-specific cases remain outside this evidence.

`HdfMesh.get_mesh_corner_elevations()` supports native reads and an explicit
h5py fallback; production FIM requires the native entry point. Qualification
used fast-HDF commit `6920fd8efb36831c32161156eee6c7635eee0229`, CI run
`40351630621`. Its development wheels still identify as 0.2.2; published 0.2.2
predates the feature. Capability detection is required. The 0.8 wheel build
metadata records these dependency artifact hashes. Cache-only real-model tests
use `RAS_FIM_CORNER_CASE`; no model data or generated rasters are committed.
The required corner reader is now available in published fast-HDF 0.2.3.

To reproduce a weighted comparison, supply an external JSON case to
`scripts/benchmarks/fim_sloping_compare.py`. Set `render_mode` to `slopingPretty`,
`use_depth_weighted_faces` and `reduce_shallow_to_horizontal` to true, and provide
`postprocessing_hdf` when using a prepared cache. The case also contains `hdf`,
`terrain`, `engine`, `profiles`, and `references` (profile name to Depth/WSE
paths). Use `--match-reference-grid` to include native nodata borders. The same
cache arguments are accepted by the prepared-reach benchmark. The native
reference must use the same options and original terrain source layout.

## Reach timestep catalog throughput

Use `RasFim.map_catalog()` for known reach/timestep groups. The final API was
measured on Spring Creek eBFE (340,163 physical cells), with four groups across
three unmodified NextGen watershed polygons: `wb-2408204`, `wb-2408158` and
`wb-2408326`. Their lists contain 4, 8, 2 and 4 requested occurrences, including
a repeated reach and duplicate selectors. Each catalog produces 18 Depth/WSE
pairs (36 TIFFs). Saved indices are 48, 49, 50, 51, 52, 54, 96, 100, 104 and
108; there are no Max aliases or added depth cutoffs in this comparison.

| Final workflow | Median s (range) | Max sampled RSS GiB | Max sampled private GiB |
|---|---:|---:|---:|
| Direct sloping batch per reach, sequential | 14.592 (14.210–15.185) | 1.055 | 1.290 |
| Catalog, source reuse, one worker | 9.137 (8.783–9.501) | 1.210 | 1.836 |
| Catalog, independent jobs, two workers | 14.305 (14.031–14.472) | 2.141 | 3.015 |
| Catalog, independent jobs, four workers | 12.683 (12.104–12.772) | 3.852 | 5.253 |

Source reuse improved median whole-catalog throughput by **1.60×** in this
workload. More workers did not improve its median. Reuse requires extra Python
worker/coordinator state compared with direct calls, so it does not reduce
private memory versus that bounded baseline. It avoids the much larger raster
work of full-model exports; those earlier full/bounded measurements remain
separate. These are shared-workstation observations, not a universal speedup
or an automatic dispatch threshold.

There are three rotated repetitions per arm, with warmed imports in a fresh
outer process and an equal four-logical-CPU affinity envelope. Catalog startup,
preparation, final LZW TIFF delivery, duplicate-output copies and close are
included. Native workers and compression share each worker's CPU partition;
profile concurrency and writer threads are one. Memory columns are maximum
simultaneously sampled outer Python plus worker/native descendants across all
three repetitions (20-ms requested interval), including process startup. The
public API's own telemetry excludes its caller. Sampled RSS/private memory are
not hard OS limits. Source/file caches and workstation load are uncontrolled.
The engine is published Fast-Map 0.10.1 with Fast-HDF 0.2.4, on Windows x64 and
Python 3.13.12. The native per-request admission limit is 2,048 MiB and the
catalog budget is 16,384 MiB; these are plans, not the measured peaks.

All **324 optimized Depth/WSE band comparisons** against the direct path have
zero extra, missing or differing float32 bits. The receipt contains 432 band
checks including reference self/repeat checks. Six additional independent
full-source-lattice comparisons at saved timestep 48 cover all three watershed
polygons; they also have zero mask/bit differences, including reference-valid
pixels outside any candidate extent. HDF, terrain, polygons, engine and
benchmark/mapping source hashes were unchanged. No RASMapper exports or
hydraulic computations were performed: these checks qualify catalog/direct
Rust consistency, not additional native RASMapper parity.

### Choosing batches and workers

Batch a known timestep list before adding workers. A single-use context has
setup costs; repeated small requests benefit from prepared/native state. The
earlier exploratory Spring Creek study observed a benefit by four timesteps
and tested lists of 1, 4, 16 and 64. Its fitted two-timestep break-even is an
estimate, not a measured threshold. The final table above replaces prototype
mixed-catalog timings as the public API measurement. Start with one worker and
measure `strategy="parallel"` for independent models, larger windows or
different encodings before increasing the count.

The source Water Surface array has shape `(145, 343014)`, gzip chunks
`(1, 343014)`: each selected timestep occupies a whole compressed cell row.
Spatial slices still require that row's decompression. Staging therefore keeps
complete selected rows, deduplicates selectors, and combines contiguous times
when their source payload fits its bounded 8-MiB read cache. Larger rows retain
bounded spatial slabs. This does not spatially prune sloping dependencies.
Terrain already reads only intersecting source TIFF blocks. Plain-sloping
weights and window data follow the engine's bounded cache admission; larger
windows can disable weight caching without changing results.

Run `scripts/benchmarks/fim_catalog_compare.py jobs.json NEW_OUTPUT` from an
installed source checkout. The JSON contains `jobs` in the
[catalog API format](../api/fim.md#schedule-reachtimestep-catalogs), optional
`threads`, `max_working_mib`, `max_memory_mib`, and `repetitions` (default three).
The direct-reference harness currently targets sloping jobs. It rotates all
four arms, records identities/time/memory and checks every emitted band outside
the timing clocks. Real-model tests use `RAS_COMMANDER_FIM_CATALOG_CASE` with
`hdf`, `terrain`, `polygon`, optional `polygon_layer`, and `timesteps`. Tests
never execute HEC-RAS. Model data and generated products stay external.

## Retained-state and native-output optimization

Keep one `RasFim.prepare_sloping_model()` context open across reach requests
when their timestep union is known. Development Fast-Map commit `6ec2be0b`
adds bounded hydraulic and multiple-window LRU caches. Commander also retains
passed geometry validation for identical cell subsets and exposes optional
direct terrio LZW GeoTIFF output. These changes retain complete global
hydraulic dependencies, existing interpolation options and the source terrain
lattice. No depth cutoff is added.

### Complete catalog calls

The final Windows comparison uses Spring Creek eBFE (340,163 physical cells),
the three unmodified NextGen watershed polygons `wb-2408204`, `wb-2408158` and
`wb-2408326`, and four reach groups containing 18 requested Depth/WSE pairs.
There are 10 distinct saved timestep selectors. The catalog writes 36 TIFFs,
including separate ordinal products for duplicate requests.

Each arm runs in a fresh outer process with warmed imports and four logical
CPUs, including compression. Clocks include worker startup, model preparation,
HDF staging, mapping, duplicate delivery, GeoTIFF writes and cleanup. All arms
use plain sloping, one in-flight profile, one compression worker, a 4 GiB
working allowance and a 1 GiB prepared allowance per actor. The large-cache
case needs more than the default 2 GiB planned working allowance on the largest
reach; its earlier refusal is excluded from these timings.

| Complete catalog configuration | Median time, s (range) | Maximum sampled RSS, GiB | Maximum sampled private memory, GiB |
|---|---:|---:|---:|
| Previous catalog implementation (`32269cf`), released engine 0.10.1 | 9.276 (8.965–11.750) | 1.201 | 1.833 |
| Updated implementation, default cache ceilings, Rasterio output | 8.617 (8.612–10.934) | 1.269 | 1.910 |
| Updated implementation, 256 MiB hydraulic + 256 MiB window ceilings, Rasterio | 9.094 (8.583–9.233) | 1.458 | 2.159 |
| Updated implementation, those larger ceilings, native terrio output | 8.126 (8.120–9.627) | 1.373 | 2.073 |

These are three rotated observations per arm on a shared workstation. The
final native-output configuration is **1.14 times as fast** by the ratio of
medians; its maximum sampled RSS is about 0.17 GiB higher. Larger caches alone
show little benefit for this single cold catalog and do not establish a
general speedup. No new RAS Mapper generation timing is claimed here.

### Repeated prepared requests

A separate 24-run ablation repeats the same four reach groups twice per
process. The second pass uses an already prepared context, except the explicit
fresh-context arm. Returned duplicate selectors reference the same written
profile within each request; this harness does not add catalog ordinal copies.

| Second-pass configuration | Median time, s (range) | Maximum sampled RSS across both passes, GiB |
|---|---:|---:|
| Close and prepare a new context for each pass, released engine | 7.238 (6.686–12.019) | 1.068 |
| Keep the existing context open, released engine | 4.021 (3.689–6.380) | 1.070 |
| New engine, all optional retention disabled | 4.090 (3.720–8.321) | 1.061 |
| Hydraulic retention only, 256 MiB | 3.503 (3.102–4.722) | 1.263 |
| Multiple-window retention only, 256 MiB | 4.123 (3.581–4.703) | 1.118 |
| Passed-validation retention only, 8 MiB ceiling | 3.195 (3.107–3.881) | 1.067 |
| Combined retention, Rasterio output | 2.498 (2.477–3.670) | 1.308 |
| Combined retention, native terrio output | 1.606 (1.565–4.693) | 1.256 |

The final native-output second pass is **2.50 times as fast** as the previous
open-context path by median ratio. Hydraulic hits avoid reconstructing shared
timesteps; window and validation retention pay off when their entries survive
until a reach is revisited. Multiple-window retention alone did not improve
the median here. Budgets must fit the retained state and active work; increasing
cache ceilings or worker counts does not guarantee higher throughput.

### Paired writer check and SIMD experiment

Five additional alternating writer pairs use one shared warm context, identical
requests, cache ceilings and four-core affinity. Rasterio delivery takes a
median **2.483 s** (2.398–3.142); direct terrio delivery takes **1.549 s**
(1.525–1.610), a **1.60 times** median wall-time ratio. Median aggregate
Python/native process CPU time is 2.969 s and 3.344 s respectively: the observed
wall-time improvement is not a claim of lower total CPU consumption. Rasterio
remains the default; native output is an explicit option, currently excluding
templates, floodplain polygonization and velocity.

A safe SIMD nodata/counting candidate preserves randomized and special-value
float32 bits, but shows no demonstrated performance benefit. On 4,000,003
pixels with four threads and 10 rotated repetitions, the scalar median is
3.839 ms and the SIMD median is 3.999 ms. SIMD remains a test-only experiment;
production keeps the scalar finalizer and the unsafe-code prohibition.

### Numerical checks and reproduction

All **1,728** retained-state ablation band checks, **432** complete-catalog
checks and **360** paired-writer checks pass. Each comparison requires equal
grid/CRS, complete validity masks and identical float32 bits at every valid
pixel. Input, engine and harness/source hashes remain unchanged throughout
each completed experiment. Interrupted development trials are excluded.

An additional five-model check passes **256** band comparisons against released
Fast-Map 0.10.1: Davis pipes/conduits and Bald Eagle bridges use depth-weighted
cell-face sloping with shallow-to-horizontal reduction; Spring River, Spring
Creek and Bald Eagle dam break use plain sloping. Bboxes and polygons are
revisited after intervening requests, with both Rasterio and native writers.
The eBFE checks are bounded; complete topology is retained. This verifies
preservation of the qualified engine output, not a new native RAS Mapper run
or broader native-version qualification. An isolated installed Windows wheel
also passes the CLI capability check and four one-shot native-output band
comparisons on Davis.

The setup uses native Fast-HDF 0.2.4, Rasterio 1.5.2, NumPy 2.5.4 and Shapely
2.2.0. Filesystem caches and workstation load are uncontrolled. External memory
samples occur about every 250 ms, with descendant discovery every 500 ms;
shorter peaks may be missed. Reported peaks include the outer caller and owned
native/worker processes. Catalog admission/telemetry separately excludes its
caller and remains a sampled guard, not a hard RSS limit.

Run `scripts/benchmarks/fim_retained_compare.py`,
`scripts/benchmarks/fim_writer_compare.py` and
`scripts/qualification/qualify_fim_retained.py` with external fixture configs.
The complete-call harness `scripts/benchmarks/fim_catalog_compare.py` also
accepts named `variants` with an explicit interpreter, matching checkout `cwd`,
engine and catalog options, so previous and current worker modules come from
their intended versions. The Rust test-only SIMD experiment is reproducible
with `cargo test --release --lib benchmark_scalar_and_safe_simd -- --ignored
--nocapture`. Model files, generated rasters and raw receipts stay external.

## Roadmap and dependencies

Bounded HDF staging, persistent native terrain/stencil reuse and bounded plain
pixel-weight caches are integrated through prepared contexts and catalog
mapping. The development throughput implementation adds shared hydraulic
reconstruction across windows, bounded multi-window retention and reuse of
passed validation for identical cell subsets. Qualified spatial dependency
pruning remains future work; output masks retain complete hydraulic topology.
The engine is now separately packaged as `ras-commander-fast-map` on PyPI and
crates.io, with Windows/Linux wheels and independent release CI. Extraction
retains the qualified 0.8 numerical modules and their source fingerprints;
the tables above remain the original mapping measurements, not new timing
claims for the packaging change.

## UPGU1 wet-extent report (#628)

Use `RasFim.map_horizontal_profiles()` when comparing cell-constant horizontal
surfaces. `map_profiles()` retains the triangulated ras2fim-2D Step 05 method;
its grid anchor and polygon constraint do not change that interpolation method.
The following bounded qualification addresses the large wet-extent discrepancy
reported in [#628](https://github.com/gpt-cmdr/ras-commander/issues/628).

The 2026-10-28 check reuses the original five UPGU1 reaches and seven saved
p02 indices (198, 199, 201, 215, 216, 217, 220), parent-extract WSE, 500-ft cell
selection buffer, strict reach domains, modifications-applied native terrain
export and retained native horizontal Depth/WSE maps. Cell selection remains
`WSE - minimum_elevation > 0`; no source values, hydraulic model or thresholds
were changed. The terrain SHA256 is
`7aeee3b977cabbc02025b6fb93ae703d94c7804973011d1992ae998eeb31b0be`.

Both the explicit NumPy polygon path and released Fast-Map 0.8.0 Rust bbox path
completed all 35 reach/time cases. Each was independently compared on the
entire strict-domain bounding window of the native lattice. Native wet pixels
outside a candidate extent count as missing. The same strict-domain mask is
applied to both products; no reprojection or resampling occurs.

| Strict depth cutoff (ft) | Candidate wet samples | Native wet samples | Extra / missing samples | Minimum per-case CSI |
|---|---:|---:|---:|---:|
| 0 | 46,602,055 | 46,602,057 | 2 / 4 | 0.999998255 |
| 0.5 | 37,208,891 | 37,208,898 | 3 / 10 | 0.999997854 |
| 2 | 23,574,365 | 23,574,367 | 2 / 4 | 0.999997731 |

Counts sum raster samples across the 35 cases, not unique area or a seven-time
maximum envelope. NumPy and Rust have the same reported counts. WSE values are
exact on common-wet samples where both WSE bands are valid; maximum common-wet depth difference is
0.015625 ft. The retained native maps have missing WSE at 580 positive-depth
samples (539 above 0.5 ft, 357 above 2 ft); those gaps are reported, not filled
from candidate values. These observations do not establish complete-band bit
parity or resolve every native Depth/WSE/terrain inconsistency. No new numerical
tolerance or threshold adjustment was introduced.

The former 1.3–2.0 wet-area ratio is absent in this horizontal-method check.
This supports surface-construction choice as the cause of the large discrepancy
in the triangulated workflow. Existing triangulated products remain labelled
with their own method; their results and defaults are not silently changed.

Fast-Map 0.8.0 lacks `global-terrain-lattice/1`; it is qualified here only for bbox
mapping followed by independent strict-domain comparison. Native polygon
requests still require a capable newer engine and reject older wheels. The
NumPy reference explicitly supports the current polygon rule; it is never an
automatic fallback. This check reused historical native maps, so it provides no
new native-generation timing or native/Rust speed ratio.

Recheck retained products with
`scripts/qualification/compare_horizontal_reach_products.py`. Supply product,
domain and native-reference folders plus the reach IDs and saved indices. It
checks full-AOI coverage, lattice/CRS, independent Depth/WSE validity, thresholds
and band errors, and writes a JSON receipt. Large source/results stay outside
the repository.
