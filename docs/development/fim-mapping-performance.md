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
complete staged mesh/WSE files. Repeated selectors share files. Each request
still starts a fresh native process, reconstructs stencils and decodes its
terrain window. Source size/mtime changes invalidate the context; close waits
for active calls and releases staging. No current prepared-context speed ratio
is claimed on this page.

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

## Roadmap and dependencies

Later performance work includes chunked HDF staging, persistent native terrain
and stencil reuse across reach requests, and bounded pixel-weight caches.
The engine is now separately packaged as `ras-commander-fast-map` on PyPI and
crates.io, with Windows/Linux wheels and independent release CI. Extraction
retains the qualified 0.8 numerical modules and their source fingerprints;
the tables above remain the original mapping measurements, not new timing
claims for the packaging change.
