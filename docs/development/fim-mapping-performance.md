# Native FIM mapping performance

Use `RasFim.map_horizontal_profiles()` for cell-constant horizontal mapping or
`RasFim.map_sloping_profiles()` for cell-corner sloping. Both methods map
physical 2D cells, reject models containing 1D river/cross-section geometry,
and support bbox/polygon output constraints. Rust reads numeric HDF inputs,
rasterizes ownership through terrio, reconstructs sloping surfaces and maps
pixels with bounded Rayon workers. Python manages requests and GeoTIFF delivery.
Production mapping requires no HEC-RAS assemblies.

## Deterministic vector boundary qualification

Use `RasFim.map_inundation_boundaries()` for
`deterministic-zero-depth-contours/1`, with no additional depth filtering.
This is a distinct vector method with stable union order and canonical rings;
the raster parity tables below do not establish native polygon equality.
See the [boundary API](../api/fim.md#deterministic-inundation-boundaries)
for original-terrain requirements and unsupported options.

Development qualification on 27 October 2026 used Fast-Map 0.10.0, required-native
Fast-HDF bitfield support from PR #31, and public computed Davis pipes/conduits.
Horizontal and plain sloping each mapped Max, timestep 54 and timestep 108.
All product bytes matched across two repeated batches at 1 worker/1 in-flight
profile, 4 workers/1 profile, and 4 workers/4 profiles. Six Windows GNU release
products also matched Linux release bytes. Bbox and polygon-with-hole tests
retained deterministic output across workers, respected the selected extent,
and retained the polygon exclusion. The standalone Rust concurrency test also
passed on the staged real model. These checks establish repeatability for the
listed inputs, rather than native vector parity.

A public eBFE Spring River reach test also passed for horizontal and plain
sloping Max. A 4,000-by-4,000 projected-unit bbox selected nine source tiles;
full model hydraulics and stitch connectivity remained staged. Products matched
byte-for-byte at 1/1, 4/1 and 4/4 requested worker/profile settings. With one
profile the effective in-flight count was one. The sloping product contained
42 polygons, 38 holes and 12,257 vertices. This bounded reach test does not
qualify a full-terrain vector export or native polygon parity for Spring River.

Fresh native references were generated through `RasProcess.store_maps()` on an
isolated Davis project copy with RASMapper 7.0.1 and plain sloping. The rasmap
and complete project-file inventory were unchanged after both native calls.
The Rust call used four workers and two in-flight profiles. Raw workflow times
on the shared workstation were:

| Work | Native stored-map calls (s) | Rust batch (s) |
| --- | ---: | ---: |
| Davis Max and timestep 108, plain sloping | 85.165 (54.059 + 31.106) | 3.537 |

The Rust batch includes shared Python preparation, native contour generation
and GeoJSON delivery once. Native clocks cover two complete stored-map calls.
Source hashing and geometry comparison are outside these clocks. These are
observed workflow times, with no speed ratio because the vector methods and
output formats differ. They are not a dedicated uncontended benchmark.

The fresh native comparison measured the complete geometry, without repair,
resampling, reference rounding or a depth cutoff. Areas below are square US
survey feet in EPSG:2871; vertex counts include ring closure coordinates.

| Profile | Rust / native polygons | Rust / native holes | Rust / native vertices | Rust-only area | Native-only area |
| --- | ---: | ---: | ---: | ---: | ---: |
| Max | 274 / 274 | 66 / 65 | 47,426 / 47,396 | 0.001034 | 7,423.028321 |
| Timestep 108 | 469 / 469 | 10 / 9 | 35,616 / 35,587 | 0.004348 | 2,647.603286 |

Both topological equality and quantized-coordinate equality were false.
A separately retained timestep-108 export had 10 holes and 35,614 vertices;
its symmetric difference from Rust was 0.009367 square feet. Thus the fresh
timestamp export also differed from its retained native reference. Native
variation is not restricted to Max. The comparison receipt retains the
particular reference identities and each direction of difference rather than
selecting a favorable native run. Hausdorff distance was omitted because the
vertex-pair product exceeded its 25-million admission limit.

Reproduce Rust repeatability with
`scripts/benchmarks/fim_boundary_compare.py case.json output_folder`.
The external case supplies `hdf_path`, original `terrain_path`, `terrain_hdf`,
`profiles` and `engine_path`; optionally supply `bbox`, `polygon`, `aoi_crs`
and an independently verified `terrain_crs_fnv1a64`. Optional retained exports
use `native_boundaries={"sloping": {"Max": "reference.shp"}}`, with every
selected profile named for each supplied interpolation method. The script
checks source hashes before/after and rejects product-byte differences across
worker configurations. It never executes HEC-RAS. Use the comparison API on a
project copy to generate fresh references and collect native timings.

Initial boundaries require one original unmodified terrain source, matching
terrain-HDF sample metadata, horizontal or plain sloping, and physical 2D
geometry. Multi-source mosaics, terrain modifications, cell-face/shallow/weighted
boundary options and native vector equality remain outside this qualification.

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
| Davis pipes/conduits | 2,716 | Horizontal | 4.235 | 1.046 | 4.05× | Exact mask and values (2D); fresh rerun |
| Davis pipes/conduits | 2,716 | Sloping: cell corners | 1.909 | 0.527 | 3.62× | Exact mask and values (2D) |


The table reports the final qualified horizontal/sloping implementation's
2026-10-26 Windows measurements against native RASMapper 7.0.1. Both Depth and
WSE have identical complete validity masks and valid float32 bits within the
physical 2D footprint. There is no added depth cutoff, reference filtering or
resampling. Equality only where both rasters are valid is insufficient.

Except for the Davis horizontal rerun described below, native exports/times
were retained from the same-day reference run; Rust 0.7.0
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
not equal work outside the supported scope.

The Davis horizontal row replaces an earlier failed reference export with a
fresh 2026-10-26 rerun using the published Fast-Map 0.8.0 engine and Fast-HDF
0.2.3. Native aggregate export succeeded with four-CPU affinity and one
stored-map worker; Rust used four mapping and compression workers. Each band
has 20,560 valid physical-2D pixels, with zero extra, missing or differing
float32 pixels. Both comparison directions cover the complete physical
footprint, without depth filtering or resampling. The Rust clock includes cell
preparation and output delivery on its terrain grid; unlike the older
horizontal rows, it excludes a nodata-border rewrite. Native and candidate
affine resolutions differ by about 2.7e-13 map units per pixel; the comparison
checks their lattice alignment within 1e-8 map units without modifying either
output. The copied project's rasmap bytes, source HDF and terrain hashes, and
process affinity were verified restored or unchanged. Rust was measured after
earlier grid-delivery checks had already run mapping; imports and filesystem
caches were warm. These are single-call observations, not a repeated or
interleaved benchmark.

This successful export does not establish a repair of the intermittent native
pipe-rendering failure tracked in issue
[#678](https://github.com/gpt-cmdr/ras-commander/issues/678).
PR [#677](https://github.com/gpt-cmdr/ras-commander/pull/677) fixed Commander's
false-success reporting. Failed export attempts remain excluded from ratios.

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
complete staged mesh/WSE files. Repeated selectors share files. Numeric profile
staging uses bounded 8 MiB source slabs through the native HDF backend.
Fast-Map 0.9 adds capability-detected persistent native sessions: one process
retains mesh/stencils, a Rayon pool and decoded terrain blocks. A separate
64 MiB bound admits at most the last small output window and up to 32 MiB of
plain-sloping weights. Face rendering preserves its existing donor-history
path. Source size/mtime changes invalidate the context; close waits for active
calls, stops the native process and releases staging. `native_session=False`
retains the CLI-per-request control for comparisons and constrained workloads.

The 0.9 development engine's three-repetition rotated Windows comparison uses
four requests per sequence, four allowed CPUs, four native and four compression
workers, and one in-flight profile. All three columns below use the same final
engine; they select its one-shot, prepared CLI, or persistent-session modes.
The clock includes preparation, all requests and close; raw comparison and
hashing are outside it. The 432 output products include 384 comparisons to
separately generated one-shot baselines; those grids, complete masks and valid
float32 bits are identical. Each workload includes wet pixels.

| Workload | One-shot sequence (s) | Prepared, fresh CLI per request (s) | Prepared native session (s) | Fresh CLI / session |
|---|---:|---:|---:|---:|
| Davis: Max + timesteps 54/108, four full requests | 2.257 | 1.824 | 1.568 | 1.16× |
| Bald Eagle bridges: two Max aliases, four small bbox requests | 3.024 | 1.236 | 0.842 | 1.47× |
| Spring River: Max, four wet reach bbox requests | 14.137 | 10.505 | 5.498 | 1.91× |

These are median sequence times on a shared workstation with warm imports and
uncontrolled filesystem caches. They measure catalog reuse, not an isolated
kernel or a new RASMapper comparison. Source identities, executable/harness
hashes and restored CPU affinity were checked. The River workload retains all
422,715 physical cells for reconstruction while mapping two repeated small
reach windows. One-shot calls do not allocate or populate persistent caches.
Use `scripts/benchmarks/fim_prepared_reaches.py --compare-native-session` to
rotate these three modes; `--no-native-session` selects the fresh-CLI control.

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

Chunked profile staging, persistent native terrain/stencil reuse and bounded
plain-sloping pixel-weight caching are implemented in the Fast-Map 0.9 session
path described above. Future work includes broader weight-cache coverage for
cell-face rendering, larger-window policies and additional corpus benchmarks;
these require the same complete mask/float32 checks before adoption.
The engine is now separately packaged as `ras-commander-fast-map` on PyPI and
crates.io, with Windows/Linux wheels and independent release CI. Extraction
retains the qualified 0.8 numerical modules and their source fingerprints;
the tables above remain the original mapping measurements, not new timing
claims for the packaging change.

Rust-native inundation boundaries remain separate qualification work. They need
a reproducible native reference and complete contour topology/coordinate checks
before adoption; see the [boundary tracking issue](https://github.com/gpt-cmdr/ras-commander-fast-map/issues/4).
