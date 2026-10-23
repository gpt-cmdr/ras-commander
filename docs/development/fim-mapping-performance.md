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
