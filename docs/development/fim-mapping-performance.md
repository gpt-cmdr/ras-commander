# Optional FIM engine comparison

The optional `RasFim` API uses the same Rust engine source as the ras2fim-2D
integration. `rust/step05/SOURCE_MANIFEST.json` records the matching source hashes.
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
CRS rules and explicit failure behavior. Native Windows builds and other
untested terrain/CRS combinations require additional qualification.

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
gap essentially unchanged. Matching the intended surface construction is the
useful first change: `map_horizontal_profiles` fills each cell with its own WSE
and reuses terrain-lattice ownership across profiles.

The UPGU1 p02 assessment used five reaches and seven saved timesteps, identical
terrain-grid pixels in EPSG:2278, the modifications-applied terrain export,
the same parent cell WSE, and a strict `depth > 0.5 ft` filter applied
independently to both products. No resampling was used to improve agreement.
On these 35 individual maps, there were 37,208,888 common-wet pixel-time
samples and only 13 wet/dry disagreements (3 additional, 10 missing). The minimum per-map CSI was 0.99999785; the original
triangulated maps ranged from about 0.32 to 0.81. All jointly finite WSE values
on common wet pixels agreed exactly. The reference has 539 wet pixel-time
samples with finite depth and missing WSE; those are counted separately, not
treated as agreeing values.
Depth is not identical everywhere: small residual differences reach
0.015625 ft and are consistent with the retained products' implied-terrain
differences. These are comparisons of one model, rendering mode and reference
set, not a general RAS Mapper equivalence or hydraulic-accuracy claim.

Full-call timings on one tested, polygon-constrained reach included grid
preparation, mapping, the
same 0.5 ft filter, both LZW GeoTIFF writes and the manifest. They excluded
imports, loading the already-staged cell/profile frames, and floodplain
polygonization. Five interleaved repetitions followed one excluded warm-up
pair per scenario. Both methods used one CPU; the original Rust engine used
one thread and one profile in flight. The horizontal call re-prepared its
shared ownership and terrain for each repetition.

| Profiles | Triangulated method median / IQR (s) | Horizontal method median / IQR (s) | Observed throughput ratio |
|---:|---:|---:|---:|
| 1 | 2.404 / 0.388 | 0.696 / 0.064 | 3.46 |
| 7 | 18.997 / 3.330 | 3.195 / 0.927 | 5.95 |

The run used Windows, local working storage, Python 3.13.12, NumPy 2.3.5,
SciPy 1.16.3 and rasterio 1.4.4 (GDAL 3.10.3), on a shared i9-11900KF
workstation with uncontrolled host load. These observations compare two
different, explicitly selected mapping methods. They do not establish a
speedup for unchanged ras2fim arithmetic, native stored-map generation,
sloping rendering, cold storage, whole-model calls or other models. Cell
overlap validation still queries each selected cell on every call; its cost
can dominate large unconstrained meshes. Ownership and terrain reuse currently
lasts within a call, not across separate calls.

For native **sloping** agreement, the earlier research identifies work that
cell-constant filling does not replace: hydraulically connected face/corner
stencils, side-specific WSE across barriers, shallow-water options, and
structure-specific renderers. A global Delaunay surface cannot become that
method merely by increasing precision or adding a depth cutoff. Potential
optimizations of the triangulated engine remain geometry/query-weight reuse,
batched terrain evaluation and an exactly guarded aligned-grid lookup; each
needs separate equality and throughput tests before adoption.
