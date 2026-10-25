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

### Paired throughput measurements

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
