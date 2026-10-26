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
persist across profiles within one call. Persistent prepared contexts across
calls and direct Python bindings remain opportunities for further work.

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

The dam-break native reference contains 1,192,324 valid pixels overall;
727,879 lie in the compared 2D footprint. The project also has a standalone
storage area. Storage-area surfaces outside the 2D mesh are not mapped by
this engine, so this row does not establish whole-model image parity.

The complete numerical method runs in a bounded Rayon pool. One/four-worker
Davis Max/timestep tests and a one-worker triangular AOI test pass. Repeated
Max profiles in one request also pass, testing shared preparation separately
from the two distinct timestep checks. The five cases also pass with a Windows
x86-64 engine, including one/four-worker Davis Max/timestep pytest checks.
Full-extent eBFE remains unqualified. Davis native timestep capture retained two
successful references; a later independent WSE helper failed with exit 99,
and a separate aggregate export also failed. Neither failure is counted as
qualification, and both attempts preserve rasmap restoration/HDF identity
receipts.

Two interleaved single-map bridge-model comparisons on Windows used identical
4,852 × 6,705 output grids, including the nodata border, with the same tiled
DEFLATE storage layout and nodata value. Rust timing included the complete
mapping API using `template_raster` for direct native-grid delivery. Both complete
images matched valid/nodata masks and every finite float32 Depth/WSE value,
with no added filtering, resampling or profile concurrency:

| Pair | Native RASMapper (s) | Rust, one worker (s) | Rust, four workers (s) | Native / Rust, four workers |
|---|---:|---:|---:|---:|
| 1 | 6.42 | 4.27 | 3.64 | 1.76× |
| 2 | 6.70 | 4.46 | 3.73 | 1.80× |

The API ordinarily writes the cell/AOI extent. With `template_raster`, it
writes native-sized GeoTIFFs directly, padding nodata without an intermediate
raster read/rewrite. The template contributes metadata only; the real-model
test uses an empty template to confirm native reference pixels are not used
for mapping. Canonical terrain was prepared before timing. Source rasters
and authentic outputs were retained separately.

RASMapper used native 7.0.1; Rust used the installed 0.4.0 Windows GNU
static-CRT build. The parent and children were restricted to four CPUs;
Rust used the stated worker count. The Rust order was reversed in the second
pair. These are shared-workstation timings with warm, uncontrolled caches,
not a universal speedup claim. Comparison scanning and reference metadata
setup were outside the timed API calls. Original rasmap bytes were restored
and the result HDF hash remained unchanged.

Earlier comparisons wrote a smaller nodata border for Rust: native output
was 4,852 × 6,705, while Rust output was 4,071 × 5,941. Their values matched in
the physical footprint, but those elapsed ratios are not used in the
equal-grid table. The exploratory mixed Windows/WSL timings are also retained
separately. An intermediate equal-grid comparison included an extra delivery
rewrite; it is superseded by the direct-template table. Four workers reduced
the measured complete-call time relative to one in these pairs, while raster
delivery and preparation still limit scaling. The benchmark harness hash was
recorded alongside the timings.

Profiling identified geometry serialization as a larger cost than arithmetic.
The engine now accepts typed binary geometry arrays with small JSON
descriptors, preserving coordinate bits and avoiding per-element conversion.
An exploratory two-profile Spring River bounded run fell from 76.73 s with
the initial JSON geometry handoff to 11.27 s with the binary handoff; geometry
preparation inside Rust fell from 32.45 s to 2.08 s. Both runs matched the same
native reference exactly. These development timings are not a controlled
comparison with RASMapper. Terrain blocks are decoded in the same bounded
pool, and blocks outside ownership/AOI are skipped.

`scripts/benchmarks/fim_sloping_compare.py` reproduces raw comparisons from
an external case JSON. `tests/test_ras_fim_sloping.py` runs real-model
one/four-worker raw-bit checks when `RAS_COMMANDER_SLOPING_CASE` points to
that case. Fixtures and generated evidence remain external to the repository.
Use `--match-reference-grid` to include nodata-border delivery in the timing
and compare the entire reference image. This stricter option fails when the
reference includes valid model elements outside the engine's 2D-cell scope.

## Proposed engine packaging

Package the mapping engine separately as **`ras-commander-fast-fim`**, following
[ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf).
This is a proposed extraction, not the installation name of the retained
`ras2fim-engine` 0.4.0 test wheels retained with the plain-sloping implementation.

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
