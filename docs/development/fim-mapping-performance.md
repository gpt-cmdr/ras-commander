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
is a numerical reference, not a fallback. Engine 0.3 wheels for Linux and
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

A full-domain Spring Creek p01 `Max` run compared the 0.2 Rust horizontal
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
| Rust horizontal pipeline before transport fixes | 359.1 |
| Rust horizontal with bounded array reads | 126.4 |
| Rust horizontal with bounded reads/writes, overlap prefilter and four compression workers | 56.3 |

The original native-first/Rust-second pair took 231.8 and 359.1 seconds.
Follow-up Rust runs took 126.4 seconds with bounded reads, then 56.3 seconds
with the combined optimizations. The latter is 6.38 times faster than the
initial Rust observation and 4.12 times faster than the retained native
observation. Each figure is one run on the shared Windows workstation;
the follow-ups were not interleaved with fresh native runs. There was no
excluded warm-up and cache state/external load were uncontrolled. These are
exploratory observations, not a general throughput or cold-cache claim.
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

The initial Rust engine reported 10.9 seconds preparing terrain and 260.8
seconds in its profile operation, including binary stdout transfer. That
was not a kernel-only timing. A single depth or WSE array contains about
1.65 GB; both arrays transfer about 3.29 GB through the subprocess pipe.
An isolated same-size transfer test took 62.29 seconds with one large read
and 0.60 seconds with 1 MiB `readinto` chunks. The adapter now fills NumPy
arrays directly using bounded reads, including correct partial-read and
truncation handling, without an intermediate whole-array bytes object.

The combined run retained exact agreement on all 79,872,550 wet pixels,
with no extra/missing wet pixels, missing WSE or implied-terrain residual.
Its measured stages were:

| Stage | Elapsed (s) |
|---|---:|
| Validate/rasterize ownership | 33.9 |
| Stage ownership and profile inputs | 0.44 |
| Stream reads, including native terrain preparation/calculation waits | 13.6 |
| Write depth/WSE GeoTIFFs | 7.4 |
| Full mapping call | 56.3 |

Input staging now writes bounded byte chunks and views the nonnegative int32
owner labels as uint32 bits without a whole-grid signed/unsigned copy.
Overlap validation first tests interior intersection, constructing geometry
only for those candidates before the original positive-area rejection.
Shared edges, cell order, ownership rasterization and pixel arithmetic are
unchanged. `writer_threads=4` enables lossless LZW compression workers in
addition to the four Rust pixel workers. Both processes were restricted to
four allowed logical CPUs for the full-domain observation; the two pools can
overlap across profiles, so callers should budget their combined workers.
See the [API guide](../api/fim.md) for controls and scope.

These changes leave the compiled engine and its numerical method unchanged.
The tests cover short reads, truncation, signed zero and NaN payload bits,
staging bytes, nested writer configuration restoration, invalid worker
counts and one/four-worker numerical equality. Terrain and ownership already
persist across profiles within one call. The later
[prepared-model increment](#prepared-model-contexts-across-reach-requests)
adds Python-side reuse across calls; persistent native state and direct Python
bindings remain opportunities for further work.

### Seven-profile catalog observation

A follow-up mapped seven actual saved Spring Creek timesteps, at source
indices 0, 24, 48, 72, 96, 120 and 144 (12-hour intervals from the initial
state through 72 hours). Fast-HDF 0.2.1 in required-native mode read the
selected Water Surface and Depth rows and assembled the WSE columns in
0.86 seconds; geometry was already staged. Mapping all seven profiles in
one call took 101.9 seconds, including preparation and both LZW GeoTIFFs
per profile. Terrain and ownership were shared. Four Rust workers and four
writer workers were allowed within a four-CPU affinity limit.

All 14 delivered rasters matched the NumPy horizontal reference bit-for-bit
at every output pixel, including NaNs. There were 182,956,389 wet pixel-time
samples; the initial saved time was entirely dry. This tests transport,
worker-count and batch reuse semantics on saved results. These seven maps
were not independently regenerated by native RAS Mapper in this experiment;
the direct native equality evidence above is the maximum-result map.

This was one catalog observation, without interleaved native catalog
repetitions. It is not a measured speed ratio against a seven-map native
run. The API's existing batch interface amortizes preparation; a prepared
native context retained across separate calls is still future work.

### Secondary comparison with triangulated mapping

These secondary timings predate the transport, staging and writer changes
above; they are retained as a comparison of surface methods. Five rotated,
interleaved repetitions followed an excluded warm-up triplet on
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

The next implementation target is **RAS Mapper sloping-interpolation parity**, with
performance gains demonstrated by the same kind of executable notebook proof.
Horizontal qualification was merged in PR #644. Sloping reference capture
has started; a Rust sloping renderer is not yet implemented. Its acceptance evidence
must compare native sloping and Rust on the same terrain, grid, saved states
and varying depth cutoffs; report wet masks, depth/WSE differences, missing
values and configuration restoration. Profile single-map and multi-timestep
throughput under equal CPU budgets, and retain structure/barrier cases and
boundary diagnostics. Similar performance gains are a goal to measure, not
an established result.

Native **sloping** agreement requires hydraulically connected face/corner
stencils, side-specific WSE across barriers, shallow-water options and
structure-specific renderers. A global Delaunay surface cannot become that
method by increasing precision or adding a depth cutoff.

For unchanged triangulated mapping, candidate optimizations remain guarded
geometry/query-weight reuse, batched terrain evaluation and exact aligned-grid
shortcuts. Horizontal scaling opportunities include bounded bulk overlap
validation, persistent prepared-grid reuse and reducing the process boundary.
Each needs separate equality and paired-throughput evidence before adoption.

### Sloping reference groundwork, 2026-10-25

`scripts/benchmarks/fim_sloping_reference.py` captures native horizontal,
`sloping` and `slopingPretty` Max products through `RasProcess.store_maps()` on
a disposable copy of a computed 2D-only project. It rejects an existing output
directory, restores its parent CPU affinity, checks `.rasmap` restoration after
each export and compares matching terrain-grid pixels without resampling.
Its JSON distinguishes differences between modes from repeatability within a
mode. Outputs remain outside tracked source. This harness is not a Rust sloping
parity or speed benchmark.

The first run used the public Bald Eagle p05 bridge fixture (24,718 physical
2D cells), Windows HEC-RAS 7.0.1 and four allowed logical CPUs. All six exports
completed. Each mode matched its second run exactly for depth/WSE values and
wet masks at strict depth cutoffs of 0.0, 0.5, 1.0 and 2.0 ft. All project
configuration restoration checks passed. Sloping modes differed from horizontal
at the 0.5 ft cutoff: cell-corner sloping had 1,449 additional and 816 missing
wet pixels relative to horizontal, with a maximum common-wet WSE difference
of 8.26904296875 ft. These are differences between rendering methods, not errors
against a sloping oracle. No Rust sloping parity claim follows from this run.

Reference preparation also exposed a Commander defect: normalization discarded
the configured shallow-water and depth-weighting flags before invoking the
helper. Preserve both flags through repeated normalization so native references
reflect the selected options. A separate native check exercised all four
`slopingPretty` flag combinations on this fixture: all produced nonempty
Depth/WSE maps and restored the selected configuration. Native valid-pixel
counts differed between combinations, confirming that the flags are material.
The three-mode baseline used bare mode defaults; it is not the full flag matrix.

## Native terrio ownership rebuild, 2026-10-25

Engine 0.3 moves horizontal cell ownership and polygon masking into Rust,
using terrio 0.4.2 inside the bounded Rayon pool. Python validates the selected
cell topology and stages compact, framed 2D WKB. Rust consumes the returned
integer ownership buffer directly and reuses it with terrain across profiles.
The native path avoids GDAL rasterization and full-grid ownership staging.
The float32 gather, subtraction and strict depth cutoff are unchanged.

Both rebuilt x86-64 wheels pass installed Step05 and horizontal file/stream
smoke tests and 49 horizontal tests per platform. Rust suites pass 46 tests
on Linux and 45 on Windows; five external-fixture tests are ignored on each.
The local Windows API/schema run passes 131 tests with four external-fixture
skips. Real-model qualification covers Spring River, Spring Creek and Bald
Eagle: bbox and multipart polygons with holes at 1, 4 and 8 requested workers,
18 checks per platform. All float32 depth/WSE bits agree with the explicit
NumPy/GDAL reference. These worker-count checks establish equality, not a
throughput scaling curve. Wheel/source hashes and build provenance are in
`wheels/BUILD.json`.

The full Spring Creek benchmark compares the retained 0.2 engine with GDAL
ownership against the rebuilt 0.3 engine. Both use the same physical cells,
terrain, profiles, float32 arithmetic, LZW products and strict >0.5-ft filter.
Input loading and selected HDF reads are outside timing. Complete calls
include geometry validation, preparation, staging, mapping, product writing
and manifests. Four Rust workers and four compression workers share the same
four-logical-CPU affinity budget. All primary pairs use C: NVMe terrain,
output and scratch. Completed outputs and discarded diagnostics were moved
to G: with per-file SHA-256 verification before the catalog rerun; source
models remain on C:.

| Workload / pair | 0.2 with GDAL ownership (s) | 0.3 native terrio (s) | Observed ratio |
|---|---:|---:|---:|
| Single maximum map / first pair | 128.835 | 51.078 | 2.52× |
| Single maximum map / reversed-order pair | 66.559 | 43.950 | 1.51× |
| Seven actual timesteps / one paired catalog | 311.435 | 162.775 | 1.91× |

These are shared-workstation observations with uncontrolled load and cache
state. Ownership setup is amortized across catalog profiles; profile
arithmetic and GIS output remain common costs. These observations do not
isolate the effect of storage speed or host contention. The single-map second
pair spends 39.1 s in old Python validation/rasterization versus 19.2 s in new
Python validation and 1.2 s in Rust ownership preparation. Rust ownership
timing includes WKB decoding, shape preparation and fill. Pipeline stream
reads include waits and engine timing includes output backpressure; do not
add overlapping stages as independent compute costs.

All 18 full-model delivery comparisons match grids, metadata and every
float32 pixel bit, including nodata. Each raster contains 411,674,756 pixels;
the maximum map has 79,872,550 wet pixels. The seven 12-hour saved timesteps
span the dry initial state through 72 hours and total 182,956,389 wet
pixel-times. A dry timestep is a valid `no_flooded_pixels` product. This rebuild
comparison uses the retained engine and reference; native RAS Mapper
evidence remains the separately scoped comparison above.

Primary timings have no process/RSS sampling thread. An initial instrumented
run was excluded because process-tree sampling consumed substantial CPU.
An unpaired local catalog sample and a legacy scratch-space preflight failure
are also excluded. The earlier paired G: catalog experiment is retained as
secondary evidence; the table reports the C: rerun.
No sampled peak-memory claim is made. Native ownership avoids staging the
approximately 1.65-GB integer grid, and planned admission includes geometry
storage; admission remains a plan rather than a hard process RSS limit.

## Structure coverage and native timing, 2026-10-25

The example notebook `602_rust_horizontal_mapping_comparison.ipynb` now
drives five computed models through `RasFim.compare_with_rasmapper`.
The public API returns timing columns and an additional dictionary at
`comparison.attrs["performance"]`, also persisted in its JSON report.
Native generation and independent depth-filtered delivery writes are
separate from the comparison scan. Rust applies the same optional pixel
filter during mapping. Native raw rasters remain available.

| Computed fixture | Physical 2D cells | Inspected model elements |
|---|---:|---|
| eBFE Spring River p02 | 422,715 | One mesh; no SA/2D connections |
| eBFE Spring Creek p01 | 340,163 | One mesh; no SA/2D connections |
| BaldEagleCrkMulti2D p02 | 87,039 | Gated SA-to-2D dam and three internal levee connections |
| BaldEagleCrkMulti2D p05 | 24,718 | Seven bridge connections, gated dam and three levee connections |
| Davis p02 | 2,716 | Both meshes (`area2`, `DS Channel`); 132 conduits and 133 pipe nodes |

None of these accepted fixtures contains river-centerline or cross-section
geometry. Model-backed entry points now reject those 1D elements across the
whole source model, including mixed models when only a 2D mesh is selected.
The Muncie mixed model (one reach, 61 cross sections) and separate Bald Eagle
Creek river example (one reach, 178 cross sections) are rejection fixtures.
Pipe hydraulic tables under an HDF Cross Sections group are distinguished
from river cross-section geometry, so Davis remains supported. A dedicated
SA/2D culvert fixture was omitted from qualification; no culvert-specific
coverage is claimed.

Davis requires explicit terrain CRS-key canonicalization for terrio 0.4.2:
the retained custom HARN GeoTIFF keys are not interpreted identically by the
two readers. `RasFim.canonicalize_terrain_crs` writes an equivalent EPSG
encoding and verifies every pixel bit and the grid without reprojection or
resampling. This preparation is outside the mapping clock. CRS identity
checks remain enabled.

An initial corpus execution stopped at Davis: its aggregate native WSE
contained 3,979 missing wet-pixel values despite exact depth. Two diagnostic
aggregate reruns had 4,883 missing WSE values, while another matched
completely. GDAL reported malformed nodata metadata in the incomplete files.
These failed reference runs are retained and excluded from successful timing
evidence. Rust remained stable. Five repetitions using Commander's
independent depth/WSE helpers matched all 4,883 wet pixels exactly.
The final notebook uses `native_performance=StoreMapPerformanceOptions(max_workers=2)`
for Davis; other fixtures retain aggregate native generation. The API
requires a sole terrain registration for independent helpers and records the
requested policy. No reference values are repaired or substituted, and no
automatic retry is introduced. The API withholds speed ratios for missing
WSE or any other compared depth/WSE/wet-mask disagreement.

Follow-up diagnosis on 2026-10-25 captured a native pipe-rendering cache
exception: `DataTable` record allocation/`DataRow.set_Item`, reached through
`RASPipeNetworks.RenderMeshPipeRenderOptions.SetLastMesh` during parallel
pipe rasterization. Project PRJ, result HDF and original terrain all resolve
to EPSG:2871. Failures occur with Python georeferencing repair disabled;
explicit projection initialization still failed in 5/8 four-CPU aggregate
calls. A separate four-CPU diagnostic control also failed in 5/8 calls.
This native failure is distinct from the terrio terrain-key preparation above.

All 20 aggregate calls restricted to one inherited logical CPU completed.
All 10 repaired comparisons exactly matched depth/WSE and wet masks on
4,883 pixels after strict depth > 0.5 ft filtering. These controls support a
native concurrency defect, with no vendor runtime modification. Independent
exports are not a guaranteed workaround; a later independent export also failed.
The two native helpers are separate processes of the same Commander
`RasStoreMapHelper.exe`: aggregate calls use native `StoreAllMapsCommand`,
while independent calls use `StoreMapCommand` factories and headless native
storage. `max_workers=1` does not constrain their internal native threads.

[PR #677](https://github.com/gpt-cmdr/ras-commander/pull/677) fixes a separate
Commander defect: native fatal progress messages were discarded, allowing
the aggregate helper to report success after a failed export. The rebuilt
helper surfaced all four failures in 12 four-CPU verification calls; all
12 one-CPU verification calls passed, including six exact filtered
comparisons. The reporting fix does not repair the native race or automatically
apply Windows affinity restrictions. These diagnostic runs do not replace
the authentic notebook outputs or baseline timings below.

The comparison uses strict float32 `depth > 0.5` in model elevation units
(feet for these fixtures), applied independently to depth and WSE. Set
`min_depth=0.0` to retain positive depths without the half-foot cutoff.
The result qualifies horizontal 2D surfaces on the tested computed states,
not bridge/pipe hydraulic calculations or native sloping/1D rendering.

| Fixture | RAS Mapper (s) | Native Engine — Rust (s) | RAS Mapper / Native Engine |
|---|---:|---:|---:|
| spring-river | 313.980 | 60.865 | 5.16× |
| spring-creek | 266.934 | 55.545 | 4.81× |
| bald-eagle | 8.059 | 6.108 | 1.32× |
| bald-bridges | 7.596 | 3.142 | 2.42× |
| davis | 1.700 | 0.257 | 6.62× |

Ratios use the unrounded recorded mapping times. Separate native depth-filtering and delivery postprocessing are excluded. Rust applies its depth cutoff within the measured mapping pass; both timings include raster output.


This five-case notebook execution on Windows x86-64 used HEC-RAS mapper 7.0.1, engine 0.3.0,
C: NVMe inputs/output/scratch, four Rust workers and four compression
workers sharing four allowed logical CPUs. Davis uses two independent native
depth/WSE helpers; other fixtures use aggregate StoreAllMaps. Each case maps one maximum-result
profile over all physical 2D cells, without an AOI. Input extraction, terrain
preparation, identity hashing and comparison scanning are excluded from
mapping totals. The table compares native stored-map generation with the Rust mapping pipeline; separate native postprocessing is excluded.

All five comparisons have nonempty common wet coverage, zero extra/missing
wet pixels, exact finite depth/WSE and no missing WSE on the evaluated 2D
footprints. Every native call restored the original `.rasmap` bytes. Native
grids can include blank margins and storage-area surfaces outside the 2D
cells; those surfaces are outside the equality claim. The API withholds
ratios for storage-area scope; the descriptive table ratios above are elapsed-time quotients, not workload-normalized speedups. These are single Rust-first observations on
a shared workstation with uncontrolled load/cache, not a scaling curve or
general speed guarantee. The earlier repeated terrio/GDAL observations
remain separately scoped above.

All four baseline notebook code cells completed. The additional fifth
cutoff-proof cell was then executed separately against the retained raw
Davis reference, without repeating the baseline timing runs. The committed notebook retains authentic baseline and cutoff-proof outputs,
with their separate execution scopes stated explicitly. Logs, tables and
plots were not edited. Comparison receipts and large model/raster files
remain in ignored working folders; no local path-bearing evidence is published.

### Varying depth-postprocessing proof

The notebook applies 0.0, 0.5, 1.0 and 2.0 ft cutoffs to Davis using
the new public `RasFim.compare_rasters` API and fresh Rust delivery maps.
The qualified raw native depth/WSE surfaces are held fixed, avoiding
unnecessary native export and isolating postprocessing from generation.
Both delivered bands use the depth mask; wet counts decrease monotonically.

| Cutoff (ft), strict > | Rust wet pixels | Native wet pixels | Extra / missing Rust wet pixels | Max depth / WSE difference (ft), common wet |
|---|---:|---:|---:|---:|
| 0 | 20,610 | 20,560 | 50 / 0 | 0 / 0 |
| 0.5 | 4,883 | 4,883 | 0 / 0 | 0 / 0 |
| 1 | 1,607 | 1,607 | 0 / 0 | 0 / 0 |
| 2 | 268 | 268 | 0 / 0 | 0 / 0 |

The zero-cutoff differences are 50 Rust-only pixels with positive depths
from 0.00005340576 to 0.0009918213 ft. Common-wet depth/WSE values match
exactly. This is not zero-cutoff wet-mask parity. The 0.5, 1.0 and 2.0 ft
cases match exactly, so the established half-foot qualification is unchanged.
The native near-zero behavior remains unresolved; no suppression rule has
been inferred or added to Rust. The notebook retains this diagnostic beside
the successful cutoffs instead of excluding it.

## Plain sloping development qualification

The experimental `rasmapper-plain-sloping/1` method is separate from the
horizontal evidence above. It reconstructs native 7.0.1 plain cell-corner
sloping without an additional depth cutoff. Direct HDF inputs, Rust face
application points, hydraulic connectivity, side-specific corner regression,
general polygon weights and the native square-cell fast path are qualified
against captured native components and raw stored maps. Production mapping
does not load HEC-RAS assemblies.

Raw valid/nodata masks and every common float32 Depth/WSE value match in the
physical 2D footprint on these cases:

| Model / profile | Physical cells | Valid pixels compared | Extent |
|---|---:|---:|---|
| Davis pipes/conduits, Max | 2,716 across two meshes | 22,041 | Full physical footprint |
| Davis, timestep 54 | 2,716 | 15,860 | Full physical footprint |
| Davis, timestep 108 | 2,716 | 11,970 | Full physical footprint |
| Bald Eagle dam break, Max | 87,039 | 727,879 | Full physical footprint |
| Bald Eagle bridges, Max | 24,718 | 973,902 | Full physical footprint |
| Spring River eBFE, Max | 422,715 | 977,194 | Bounded window; complete mesh reconstruction |
| Spring Creek eBFE, Max | 340,163 | 1,826,754 | Bounded window; complete mesh reconstruction |
| Spring River eBFE, Max, final Windows run | 422,715 | 56,822,200 | Full physical footprint |
| Spring Creek eBFE, Max, final Windows run | 340,163 | 107,934,719 | Full physical footprint |

The dam-break native reference contains 1,192,324 valid pixels overall;
727,879 lie in the compared 2D footprint. The project also has a standalone
storage area. Storage-area surfaces outside the 2D mesh are not mapped by
this engine, so this row does not establish whole-model image parity.

The complete numerical method runs in a bounded Rayon pool. One/four-worker
Davis Max/timestep tests and a one-worker triangular AOI test pass. Repeated
Max profiles in one request also pass, testing shared preparation separately
from the two distinct timestep checks. The five cases also pass with a Windows
x86-64 engine, including one/four-worker Davis Max/timestep pytest checks.
The final matrix below adds full-physical-footprint Windows Max checks for both
eBFE fixtures; full-extent Linux and enhanced eBFE remain unqualified.
Davis native timestep capture retained two
successful references; a later independent WSE helper failed with exit 99,
and a separate aggregate export also failed. Neither failure is counted as
qualification, and both attempts preserve rasmap restoration/HDF identity
receipts.

Performance reporting below compares only the final implementation against
RASMapper. Sloping template delivery reads only layout metadata and writes the
matching native-sized output directly, without resampling or an intermediate
raster rewrite. The ordinary API can instead write compact cell/AOI extents.

Typed binary geometry arrays preserve coordinate bits and avoid per-element
JSON conversion. Terrain blocks are decoded in the bounded worker pool, and
blocks outside ownership/AOI are skipped.

`scripts/benchmarks/fim_sloping_compare.py` reproduces raw comparisons from
an external case JSON. `tests/test_ras_fim_sloping.py` runs real-model
one/four-worker raw-bit checks when `RAS_COMMANDER_SLOPING_CASE` points to
that case. Fixtures and generated evidence remain external to the repository.
Use `--match-reference-grid` to include nodata-border delivery in the timing
and compare the entire reference image. This stricter option fails when the
reference includes valid model elements outside the engine's 2D-cell scope.

## Enhanced sloping option qualification

Engine 0.5 adds `rasmapper-sloping-with-faces/1` through
`render_mode="slopingPretty"`. Native corner-to-face donation, optional
`use_depth_weighted_faces`, and optional `reduce_shallow_to_horizontal` retain
their native float32 operation order. Depth normalization uses the native
binary64 denominator and binary32 accumulation. The shallow branch selects
cells from hydraulic connectivity and avoids evaluating their polygon weights.
No added depth cutoff is applied; plain sloping remains the default.

All four shallow/depth-weighting combinations match raw native 7.0.1 masks
and finite float32 bits for Bald Eagle bridges Max and Davis timesteps 54/108.
The complete matrix passes with one and four workers on Windows and Linux
x86-64. Each platform checks 48 enhanced Depth/WSE products across the matrix;
the extra triangular Davis AOI check compares native pixels without changing
global connectivity. The bridge variants compare the entire native raster grid,
including its nodata border. Their native-valid pixel counts are:

| Shallow reduces to horizontal | Depth weighting | Valid pixels |
|---|---|---:|
| False | False | 974,095 |
| False | True | 974,216 |
| True | False | 974,142 |
| True | True | 974,256 |

Two initial Davis exports failed with native exit 99. Both succeeded on retained
retries with one native export worker; source HDF hashes stayed unchanged and
original rasmap bytes were restored. Failed attempts remain separate from the
successful reference evidence. No enhanced-option qualification is claimed for
Spring River/Spring Creek or other HEC-RAS versions. Standalone storage-area
surfaces remain outside the mapping scope.

The final-version model/method performance matrix below reports the enhanced
method with both flags enabled. Option-matrix parity checks remain separate
from elapsed-time measurements.

Set `RAS_COMMANDER_SLOPING_OPTIONS_CASES` to an external JSON list of case
records to run `tests/test_ras_fim_sloping.py`. Each case supplies the normal
HDF/terrain/engine/profiles/references fields plus the three option keywords.
The comparison runner accepts those keywords in its single-case JSON as well.
Stored `FacePoints Elevation` arrays are mandatory only when depth weighting
is enabled; missing inputs raise without changing the HDF or approximating
corner elevations. Older engine 0.4 requests remain usable for plain mapping;
enhanced requests require the new capability record.

## Preparation and compression optimization after Astra review

An independent Astra read-only review identified Python geometry validation and
GeoTIFF delivery as larger costs than Rust interpolation in the profiled bridge
case. The adopted changes leave the retained 0.5.0 Rust sources, executable and
binary32 arithmetic unchanged:

- Use current-main typed HDF cell coordinates without creating Shapely points.
- Evaluate overlap predicates in bounded batches of at most 4,096 candidate
  pairs, retaining every candidate and the same positive-area rejection rule.
- Reuse immutable, source-indexed timestep views per mesh, with source identity
  checks on every payload read. Max profiles retain their bulk native read.
- Pass the requested native thread budget to polygon extraction, avoid the
  unnecessary direct SciPy triangulation import, and record preparation clocks.
- Expose `writer_threads` for ordinary and template GeoTIFF compression. Its
  default of one explicitly overrides ambient GDAL settings during writes;
  the enclosing setting is restored on success and failure. Compression and
  mapping pools can overlap, so their budgets are separate.

Current `main` at `a898333f4` was merged before this work. Both qualification
environments use `ras-commander-fast-hdf` 0.2.2, the latest PyPI release checked
for this run. Numeric payload reads require Rust; h5py remains in metadata
inspection. Version metadata is now included in the performance return. No HDF
backend replacement or arithmetic rewrite was needed.

The final-version matrix below replaces development-version speed comparisons.
Final Astra review found no remaining implementation blocker. Windows affected
checks total 152 passing and four optional skips across the targeted runs;
Linux checks include 24 distinct sloping and 70 horizontal passes. Both
platforms cover compression layout/value preservation and restoration after
writer exceptions. That review preceded the prepared-model increment below
and does not cover its implementation. Persistent native state and an
in-process binding remain candidates for later measurement. SIMD changes to interpolation are
deferred: profiling did not justify changing arithmetic order.

The subsequent catalog-mask check exercises both an interior bbox and a
triangular polygon on Davis timesteps 54/108 with both enhanced flags enabled.
Each mask maps both profiles in one request. All eight Depth/WSE products per
platform match native masks and finite float32 bits within the selected AOI;
both tests pass on Windows and Linux. Geometry and results stay global while
terrain/ownership/output are windowed. The API documentation includes compact
reach-scale catalog examples and distinguishes full-grid template delivery.

## Final implementation versus RASMapper: model/method matrix

| Model | Physical 2D cells | Interpolation | RASMapper (s) | Final Rust pipeline (s) | RASMapper / Rust | Raw comparison |
|---|---:|---|---:|---:|---:|---|
| eBFE Spring River | 422,715 | Horizontal | 230.787 | 83.648 | 2.76× | Differences present² |
| eBFE Spring River | 422,715 | Sloping: cell corners | 240.726 | 50.016 | 4.81× | Exact in physical 2D scope |
| eBFE Spring River | 422,715 | Sloping: corners + faces¹ | — | — | — | Stored corner elevations absent |
| eBFE Spring Creek | 340,163 | Horizontal | 190.275 | 81.023 | 2.35× | Differences present² |
| eBFE Spring Creek | 340,163 | Sloping: cell corners | 209.896 | 49.400 | 4.25× | Exact in physical 2D scope |
| eBFE Spring Creek | 340,163 | Sloping: corners + faces¹ | — | — | — | Stored corner elevations absent |
| Bald Eagle dam break | 87,039 | Horizontal | 7.693 | 6.193 | 1.24× | Differences present² |
| Bald Eagle dam break | 87,039 | Sloping: cell corners | 7.393 | 4.634 | 1.60× | Exact in physical 2D scope |
| Bald Eagle dam break | 87,039 | Sloping: corners + faces¹ | 16.480 | 4.340 | 3.80× | Exact in physical 2D scope |
| Bald Eagle bridges | 24,718 | Horizontal | 8.897 | 5.006 | 1.78× | Differences present² |
| Bald Eagle bridges | 24,718 | Sloping: cell corners | 8.585 | 2.418 | 3.55× | Exact in physical 2D scope |
| Bald Eagle bridges | 24,718 | Sloping: corners + faces¹ | 13.018 | 2.425 | 5.37× | Exact in physical 2D scope |
| Davis pipes/conduits | 2,716 | Horizontal | — | — | — | Native export failed |
| Davis pipes/conduits | 2,716 | Sloping: cell corners | 1.909 | 0.448 | 4.26× | Exact in physical 2D scope |
| Davis pipes/conduits | 2,716 | Sloping: corners + faces¹ | 2.628 | 0.365 | 7.20× | Exact in physical 2D scope |

¹ Enhanced sloping enables both depth-weighted faces and shallow-to-horizontal rendering. Those are options of the same interpolation method, not additional table methods. The two eBFE HDFs lack stored `FacePoints Elevation` arrays required by this configuration; no substitute elevations or ratio are reported.

² A timing ratio does not assert raw parity. At zero added cutoff, the completed horizontal rows have extra valid pixels but no missing pixels or differences in common finite float32 values. No 0.5 ft cutoff is applied to hide those mask differences.

Native exports/times are retained from the same-day RASMapper run; final Rust 0.6 times were remeasured afterwards, not interleaved with those native calls. Complete final rasters match the earlier qualified candidate masks/finite bits, retaining the stated native comparison scope. One observation per model/method on 2026-10-26, on Windows using RASMapper 7.0.1, the final Python integration and retained engine 0.6.0 Windows binary (`264b67533456ee68d7e0d9b22ec4f677ade45b4cd1e979b381392ef006e7a53c`). Parent/native/Rust processes inherit four-CPU affinity. Rust mapping and initial product compression each use four workers. Native export requests one worker, except the documented Davis horizontal independent-helper retry using two. These are shared-workstation observations with uncontrolled caches, no excluded mapping warm-up and no universal speed guarantee.

Each row maps one Max Depth/WSE pair on the complete native pixel lattice, nodata and storage layout. Time includes HDF preparation, launch, mapping and output delivery. Native/project initialization, canonical terrain preparation and comparison scanning are outside the clocks. Sloping uses metadata-only direct-template delivery. Horizontal includes cell-table preparation and an additional matching-grid raster rewrite (single-worker compression), included in its reported time. No resampling, added depth cutoff, floodplain polygonization or profile concurrency is used.

Raw comparison is within physical 2D cells. The Bald Eagle dam-break native export also renders a standalone storage area outside that scope; the native call includes that extra work. Ratios describe these measured workflows, not equal work for excluded storage-area surfaces. Every completed measurement verifies source HDF identity and restoration of original rasmap bytes. Missing/failed rows are not speedup evidence.

Horizontal mask observations (Depth and WSE): eBFE Spring River: 9,271 extra valid pixels; eBFE Spring Creek: 53,345 extra valid pixels; Bald Eagle dam break: 14 extra valid pixels; Bald Eagle bridges: 16 extra valid pixels.

Davis horizontal native export failed with exit 99 on both the aggregate call and a two-helper retry (depth AggregateException). No mapping time or ratio is reported for that row. Other Davis sloping exports succeeded. This is the native failure profile tracked in issue #678.


## Bounded timestep concurrency: final engine 0.6

`map_sloping_profiles(..., threads=4, writer_threads=1,
max_inflight_profiles=2)` maps several profiles in the same bounded Rust pool.
Geometry, stencils, terrain and ownership are shared. Effective concurrency is
capped by threads, profile count and planned memory, and is recorded in the
report. Bounded batches emit in request order. The default stays at one;
earlier engines retain sequential compatibility and reject concurrency requests.

| Workload / 19 timesteps | In flight 1 (s) | In flight 2 (s) | In flight 4 (s) |
|---|---:|---:|---:|
| Davis, full extent | 0.664 | 0.643 | 0.617 |
| Bald Eagle bridges, 400 × 400 pixel reach bbox | 0.956 | 0.808 | 0.806 |
| Bald Eagle bridges, full physical extent | 17.428 | 17.536 | 18.263 |

These are median complete API times from three rotated/interleaved repetitions
per configuration, with four-CPU affinity, one compression worker and 19 distinct
computed timesteps. Both enhanced flags are enabled; no extra depth cutoff,
floodplain generation or matching-grid rewrite is used. Compact extent/AOI
delivery is identical across configurations. Python dependency imports are warm;
no mapping warm-up was excluded. Caches remain uncontrolled on a shared host.
All 27 runs (513 profiles, 1,026 products) match sequential raw masks and finite
float32 bits; source HDF identity, engine/harness hashes and restored affinity
are checked. Comparison scans are outside the clocks.

The reach bbox median falls about 16%, and Davis about 7%, with four in flight.
The full bridge domain demonstrates no throughput benefit. Use concurrency for
measured catalog workloads rather than increasing it by default. This is a
same-final-engine scheduling comparison, not a comparison with older builds.
It does not establish native RASMapper parity for all 19 benchmark timesteps;
native qualification remains the separately stated Max/timestep/option cases.

HDF reads/staging and Python product writes remain sequential. GDAL compression
may overlap native work and has a separate worker budget. Per-profile native
wall-stage times overlap and must not be summed as total wall time. Admission
is conservative planned memory, not an enforced process RSS limit.

## Prepared model contexts across reach requests

`RasFim.prepare_sloping_model` adds explicit Python-side reuse for repeated
sloping reach requests on one model and terrain. A context retains physical
cell polygons/spatial indexing, model scope, engine capabilities, terrain
metadata and complete staged mesh/profile inputs. It prepares a fixed set of
named Max/timestep profiles and deduplicates repeated selectors. Closing the
context releases its temporary files. HDF, terrain or engine identity changes
invalidate and close it; sources are never refreshed silently. The source-text
geometry file is also watched when resolved by the 2D-model guard. Identity
uses file size and nanosecond modification time, rather than content hashing.
When no source-text geometry was initially available, the context rechecks the
model scope; a newly resolved geometry file requires preparation again.

This increment leaves the 0.6 engine binary and numerical arithmetic unchanged.
Each request still launches a fresh CLI process, prepares native interpolation
stencils, decodes terrain, constructs AOI ownership and computes profile
hydraulics. AOI windows, selected overlap validation, output arrays and delivery
remain per request. Global topology and selected results remain complete at
reach boundaries. It does not introduce persistent native terrain/stencil
state, pixel-weight caching or chunked HDF staging.

The prepared-state budget combines a retained-geometry estimate and actual
staged-file bytes; the fixed profile set bounds growth between requests.
Admission is not a process RSS ceiling. Context calls are serialized, and close
waits for an active request. These lifetime and cache controls are documented
in the [API guide](../api/fim.md#reuse-prepared-models-across-reach-requests).

### Three-reach sequence observation

On Windows, three repeated reach requests per model took the following median
complete sequence times over three repetitions. Prepared sequence times include
initial preparation, all three requests and close; preparation is also reported
separately and must not be added again.

| Model / method | One-shot sequence (s) | Prepared sequence (s) | Preparation (s) | One-shot / prepared |
|---|---:|---:|---:|---:|
| Davis, corners + faces with both flags | 1.013 | 0.665 | 0.112 | 1.52× |
| Bald Eagle bridges, corners + faces with both flags | 1.599 | 1.012 | 0.205 | 1.58× |
| Spring River eBFE, plain cell corners | 8.644 | 5.731 | 1.839 | 1.51× |

Each sequence mapped three profiles at each of two bboxes and one triangular
file-polygon AOI. The bboxes span 400 × 400 terrain pixels before clipping to
the physical mapping grid; the triangle occupies the corresponding central
reach. Davis used stored timesteps 54/108/162; bridges used Max and 108/216;
Spring River used Max and 0/1. Complete model preparation retained 2,716,
24,718 and 422,715 physical cells, respectively. Planned retained geometry plus
staged inputs totaled 1,642,070, 15,523,972 and 267,606,929 bytes; these are
cache admission estimates, not measured peak memory.

The 2026-10-26 run used the unchanged engine 0.6.0 Windows binary identified in
the final model/method matrix above. One-shot/prepared sequence order alternated
across repetitions. Four-CPU affinity, four Rust workers, one compression
worker and two profiles in flight were used; effective concurrency was two in
every request. Planned working/prepared budgets were 32,768/2,048 MiB. There was
no added cutoff, floodplain polygonization or template-grid delivery.

All 18 sequences completed: 54 reach requests, 162 profiles and 324 Depth/WSE
products. The first one-shot sequence per workload supplied the reference
(54 products, self-checked). The remaining 270 products matched those references
in decoded grid, valid/nodata masks and valid float32 bits. Comparison scans
were outside timing. HDF/terrain content hashes, engine/harness/case/Python
source identities and restored affinity were checked. The final local receipt
is `working/prepared-benchmark-03/results.json`; exploratory runs are excluded.

These measurements compare preparation reuse against the one-shot API using
the same final engine and options. They add no RAS Mapper executions or native
qualification for the additional benchmark timesteps. Shared-host cache
conditions were uncontrolled. The observed sequence reductions apply to these
three-reach workloads; they do not establish a general speed guarantee or the
benefit of a persistent native context.

`scripts/benchmarks/fim_prepared_reaches.py` compares complete one-shot and
prepared reach sequences without running HEC-RAS. Its external cases JSON
supplies model/terrain paths, named profiles, interpolation options and a list
of AOI keyword dictionaries. It alternates sequence order, includes context
preparation and close in the prepared sequence clock, records each request
separately and checks decoded grids, masks and valid float32 bits outside the
clocks. Input, engine, harness and Python source hashes are retained in its local receipt.
Generated products and private case paths remain outside version control.

Run the harness from the repository root in the configured FIM environment:

```bash
python -m scripts.benchmarks.fim_prepared_reaches --cases local-cases.json --output new-results --engine /path/to/ras2fim-batch --cpus 4
```

`new-results` must not exist. The default controls are three repetitions, four
Rust workers, one writer worker, two profiles in flight, 32,768 MiB planned
working memory and 2,048 MiB prepared state. A local cases file is a JSON array;
this example shows its structure, not a recorded qualification case:

```json
[
  {
    "name": "local-reaches",
    "hdf": "/local/model.p02.hdf",
    "terrain": "/local/canonical_terrain.tif",
    "profiles": {"t0054": 54, "t0108": 108},
    "render_mode": "slopingPretty",
    "reduce_shallow_to_horizontal": true,
    "use_depth_weighted_faces": true,
    "requests": [
      {"polygon": "/local/reach_one.gpkg"},
      {"polygon": "/local/reach_two.gpkg"}
    ]
  }
]
```

Requests can instead contain `bbox` and `aoi_crs`. Use computed profiles and
AOIs from the actual model; enhanced depth weighting requires stored corner
elevations. Dependency imports are warmed before timing. Filesystem caches
remain uncontrolled; no mapping warm-up is excluded.

### Next performance opportunities

1. Measure persistent native state across reach requests. The explicit context
   now reuses Python geometry and staged global inputs. Native stencils and
   decoded terrain are still rebuilt by each CLI request; retaining them would
   require a separate engine lifetime and bounded-cache contract. Each new AOI
   still needs its own ownership window.
2. Read selected HDF rows in bounded chunks and pipeline staging with native
   processing. This removes repeated opens and the current all-profiles-upfront
   barrier while retaining virtual cells and per-read source checks.
3. Extend direct-template delivery to horizontal mapping. Its comparison path
   currently includes an intermediate GIS write/read/rewrite. Continue profiling
   compression and delivery before replacing compiled GDAL writing.
4. Test a bounded geometry-weight cache or tile-first profile batches. Pixel
   geometry weights can potentially be reused across timesteps, while hydraulic
   connectivity, face-depth weighting and shallow decisions remain per profile.
   Preserve f64 weight bits and operation order; include cache memory admission.

SIMD is a lower priority until profiling identifies a suitable hot loop.
Fast-math, fused operations and reordered reductions cannot be adopted without
exact-output qualification. The current full Spring River profile spends much
more time in geometry validation and raster delivery than hydraulic arithmetic;
the large-map stage clocks remain in the returned performance record. In the final Windows Spring River serial run, validation took 13.63 s, product writes 20.91 s, hydraulic reconstruction 0.083 s and rendering 4.01 s. These nested stage clocks identify candidates for optimization; they are not additive independent workloads.

## Proposed engine packaging

Package the mapping engine separately as **`ras-commander-fast-fim`**, following
[ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf).
This is a proposed extraction, not the installation name of the retained
`ras2fim-engine` 0.6.0 test wheels retained with configurable sloping.

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

An in-process binding could remove executable startup and geometry/WSE staging
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
should first reproduce the existing tests and qualified comparison corpus, then
introduce the binding as a separately reviewable change. No new engine
repository or package publication is performed by this PR.
