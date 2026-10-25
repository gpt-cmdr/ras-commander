# Optional FIM engine comparison

The optional `RasFim` API contains the reviewed ras2fim-2D Step05 numerical
core and a separate horizontal cell-constant kernel.
`rust/step05/SOURCE_MANIFEST.json` records the retained engine source hashes.
Build it explicitly from a repository checkout; Python does not build or
download it. The Python API is installed with the `fim` extra.

The engine was compared with the ras2fim-2D Step05 method on one public
19-profile model. Exact finite float32 values, nodata masks and grids agreed
for full maps, bounding boxes and polygons. These checks establish agreement
with that catalog method under the tested conditions, not equivalence to
RAS Mapper stored maps or hydraulic accuracy.

Development throughput observations from the **ras2fim adapter**, rather than
this new `RasFim` wrapper, were 1.58× for one full map and 1.49–1.61× for
19-profile constrained maps. Full-domain catalog throughput remains unqualified
pending controlled remeasurement.
Those results used four logical CPUs on a shared Intel i9-11900KF workstation,
x86-64 WSL/Linux, tmpfs working storage, Python 3.13.17, SciPy 1.16.3 and
rasterio 1.4.4 (GDAL 3.10.3), with five interleaved repetitions and an excluded
warm-up pair. Host load was uncontrolled. The results do not establish the
performance of this wrapper or a general catalog speedup.

Python still prepares global samples and SciPy transforms and writes the
GeoTIFF/floodplain products. Native profile concurrency shares one terrain
cache and thread pool but does not parallelize those Python stages. Decoded
cache limits and planned allocation admission are not total-process RSS caps.
An AOI reduces source-pixel work while retaining a full-grid geometry lookup
and, when required, the serial interpolation fallback.

See [the API guide](../api/fim.md) for installation, inputs, bounds, polygon
CRS rules and explicit failure behavior. Untested terrain/CRS combinations
require additional qualification.

Both retained engine wheels passed installed synthetic shared-terrain batch,
bbox and polygon-mask tests. The Windows wheel additionally passed a local
Commander public-model full/bbox/multipart-polygon-with-hole crop test.
`wheels/BUILD.json` identifies the public build and `wheels/SHA256SUMS.txt`
records the retained artifacts. These platform checks are distinct from the
Linux 19-profile numerical qualification and from performance measurements.

## Horizontal mapping assessment, 2026-10-24

[Issue #628](https://github.com/gpt-cmdr/ras-commander/issues/628) compares the
triangulated ras2fim method with **horizontal** RAS Mapper products. A follow-up
using a terrain export with RAS Mapper modifications applied left the extent
gap essentially unchanged. Matching the surface construction closes most of
that gap: `map_horizontal_profiles` fills each cell with its own WSE and reuses
terrain-lattice ownership across profiles.

The Rust backend reads the constrained terrain blocks through terrio once,
then reuses terrain and ownership for every profile. Pixel arithmetic runs
in its bounded Rayon pool. Profiles stream directly to Python's GIS writer;
no per-profile binary scratch rasters accumulate. The explicit NumPy backend
is a numerical reference, not a fallback. Engine 0.2 wheels for Linux and
Windows include both the unchanged Step05 path and the horizontal capability.

### Agreement evidence

The UPGU1 p02 assessment used five reaches and seven saved timesteps, identical
terrain-grid pixels in EPSG:2278, the modifications-applied terrain export,
the same parent cell WSE, and a strict `depth > 0.5 ft` filter applied
independently to both products. No reference resampling was used.
On those 35 maps, there were 37,208,888 common-wet pixel-time samples and
13 wet/dry disagreements (3 additional, 10 missing). The minimum per-map CSI
was 0.99999785; the original triangulated maps ranged from about 0.32 to 0.81.
All jointly finite WSE pairs on common wet pixels agreed exactly. The native
reference has 539 wet pixel-time samples with missing WSE and finite depth;
these are counted separately. Small depth differences reach 0.015625 ft and
are consistent with the retained products' implied-terrain differences.
Their precise origin is unresolved. Rust reproduced all 70 retained NumPy
depth/WSE arrays exactly.

Three additional computed corpus models were mapped by the native HEC-RAS
7.0.1 mapper in horizontal mode, with bounded exports of the exact registered
terrain. The comparison used one maximum-result map and a 10,000-foot square
AOI per model, restricted to its selected physical 2D cells:

| Model / mesh | Physical cells in mesh | Compared wet pixels | Wet-mask CSI | Maximum depth / finite-WSE difference (ft) |
|---|---:|---:|---:|---:|
| eBFE Spring River / Spring | 422,715 | 77,370 | 1.0 | 0 / 0 |
| eBFE Spring Creek / SPR_Mesh | 340,163 | 489,984 | 1.0 | 0 / 0 |
| RasExamples BaldEagle / BaldEagleCr | 87,039 | 23,068 | 1.0 | 0 / 0 |

The total was 590,422 wet pixels, with no additional/missing wet pixels,
missing WSE or implied-terrain residual in these AOIs after the same strict
0.5 ft filter. CRS coverage was EPSG:3433, 2278 and 2271. Spring River and
Spring Creek results were produced by HEC-RAS 6.1 and 5.0.7 respectively;
the mapper version is recorded separately. BaldEagle used retained computed
7.0 results. Source projects remained unchanged; mapping used isolated
copies, and every native call restored its original `.rasmap` bytes.

These are horizontal comparisons on selected AOIs and saved results. They do
not establish whole-model, native sloping, mixed 1D/2D or structure-renderer
parity. The example notebook and `compare_with_rasmapper` API make the checks
repeatable and record terrain identities, runtime, grid/threshold semantics,
missing-WSE counts and configuration-restoration hashes.

### Direct comparison with native horizontal RAS Mapper

A full-domain Spring Creek p01 `Max` run compared the current Rust horizontal
pipeline with native HEC-RAS 7.0.1 horizontal stored maps. Both used the
original registered terrain, all 340,163 physical cells, four allowed logical
CPUs, the same strict `depth > 0.5 ft` filter, and depth/WSE LZW delivery
GeoTIFFs. There was no AOI. Inputs and imports were staged before timing;
floodplain polygonization and numerical comparison were excluded. Native
timing includes its stored-map call and the filter/rewrite needed to deliver
the same thresholded products. Rust applies the filter while mapping.

| Full-domain Spring Creek: one maximum-result profile | End-to-end elapsed (s) |
|---|---:|
| Native horizontal RAS Mapper | 231.8 |
| Rust horizontal pipeline | 359.1 |

Rust took 1.55 times the native elapsed time in this observation. This was
one native-first/Rust-second pair, without an excluded warm-up or interleaved
repetitions, on the shared Windows workstation. It is an exploratory
measurement, not a general throughput result or a cold-cache comparison.
The native grid contained 447,487,929 pixels; Rust trimmed blank terrain
margins to the physical mesh bounds and wrote 411,674,756 pixels. Both cover
the evaluated 2D mesh; the coverage check also counts all native wet pixels
so that wet output outside the comparison footprint cannot be hidden.

On the full physical mesh, all **79,872,550 wet pixels** matched: zero
additional/missing wet pixels, exact depth and finite WSE, and no missing WSE.
The independent count of all native wet pixels was also 79,872,550, confirming
that the comparison did not omit native wet output outside its footprint.
Native implied-terrain residuals were zero. This is one maximum-result
full-domain case, not all-timestep or all-mode parity.

The Rust engine reported 10.9 seconds preparing terrain and 260.8 seconds in
its profile operation, which includes writing the binary stdout stream. The
latter is not a kernel-only timing. This full-domain request transfers about
3.29 GB of depth/WSE arrays across the subprocess pipe. These observations
make direct bindings and persistent prepared arrays relevant optimization
candidates; they do not prove how much time either change would save.

### Secondary comparison with triangulated mapping

Five rotated, interleaved repetitions followed an excluded warm-up triplet on
one polygon-constrained reach. Each method used one CPU; Rust threads and
Step05 profiles in flight were both one. Inputs were staged before timing.
Full calls included fresh preparation, mapping, identical strict 0.5 ft
filtering, both LZW GeoTIFF writes and the manifest. Imports, staged-frame
loading and floodplain polygonization were excluded. The triangulated call
used `grid_anchor="terrain"` and `coplanar="ignore"`.

| Profiles | Rust triangulated median / IQR (s) | Rust horizontal median / IQR (s) | NumPy horizontal reference median / IQR (s) | Horizontal Rust throughput ratio vs triangulated |
|---:|---:|---:|---:|---:|
| 1 | 2.083 / 0.088 | 0.727 / 0.013 | 0.614 / 0.016 | 2.86 |
| 7 | 15.235 / 1.509 | 2.439 / 0.268 | 1.986 / 0.091 | 6.25 |

The same-method Rust/NumPy outputs matched bitwise in every timed repetition.
The NumPy reference remained faster on this reach; the Rust process boundary,
input staging and terrain decoder still cost time around a simple,
memory-bound kernel. The observed improvement over triangulated mapping
comes from the selected horizontal construction and shared preparation.
These observations do not demonstrate that Rust outperforms vectorized NumPy.

The run used Windows, local working storage, Python 3.13.12, NumPy 2.3.5,
SciPy 1.16.3 and rasterio 1.4.4 (GDAL 3.10.3), on a shared i9-11900KF
workstation with uncontrolled external host load. This session ran no native
stored-map jobs during the timed repetitions. Results compare explicitly
different surface methods and do not establish cold-storage or whole-model
throughput. Per-cell overlap validation can dominate unconstrained meshes;
prepared ownership and terrain currently persist within a call only.
Native whole-model stored-map timings are deliberately not divided by the
bounded Rust timings because their workloads differ.

### Further work

Native **sloping** agreement requires hydraulically connected face/corner
stencils, side-specific WSE across barriers, shallow-water options and
structure-specific renderers. A global Delaunay surface cannot become that
method by increasing precision or adding a depth cutoff.

For unchanged triangulated mapping, candidate optimizations remain guarded
geometry/query-weight reuse, batched terrain evaluation and exact aligned-grid
shortcuts. Horizontal scaling opportunities include bounded bulk overlap
validation, persistent prepared-grid reuse and reducing the process boundary.
Each needs separate equality and paired-throughput evidence before adoption.

## Proposed engine packaging

Package the mapping engine separately as **`ras-commander-fast-fim`**, following
[ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf).
This is a proposed extraction, not the installation name of the retained
`ras2fim-engine` 0.2.0 test wheels in this PR.

The separate repository should own the Rust mapping crate, method contracts,
CLI, optional PyO3 bindings, native tests, notices and platform-wheel release
workflow. Rust consumers should use an ordinary library crate without Python;
Python consumers should import `ras_commander_fast_fim` from `abi3` wheels
built with maturin. Keep a CLI
for ras2fim-2D and other process-isolated callers. Preserve the current CLI and
request contracts during migration rather than changing names silently.

Commander should retain HEC-RAS execution, HDF-to-cell table construction,
project locking, native comparison, GeoPandas-facing validation, product
orchestration and notebooks. The mapping package should not depend on
Commander or invoke HEC-RAS. Both Commander and ras2fim-2D can then depend on
one versioned engine instead of maintaining duplicate source trees.

An in-process binding could remove executable startup and owner/WSE staging
costs observed in the current CLI path. It should expose a prepared mapping
context that owns terrain/ownership for repeated or chunked profile batches,
releases the GIL during native computation, bounds allocations and threads,
and converts native errors/panics to explicit exceptions. Python array
ownership and lifetimes need tests; a binding alone does not guarantee a
speedup. Persistent-context parity and throughput must be measured before
making that backend the default.

Keep installation optional through the mapping extra initially. Qualify
Windows x86-64 and Linux x86-64 wheels against both method contracts before
release; add other platforms only with their own evidence. Preserve upstream
ras2fim and SciPy acknowledgments and bundled dependency notices. Extraction
should first reproduce the existing tests and three-model comparison, then
introduce the binding as a separately reviewable change. No new engine
repository or package publication is performed by this PR.
