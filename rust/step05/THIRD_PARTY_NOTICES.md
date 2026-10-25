# Mapping engine provenance

The Step05 workflow and its sample-preparation method originate in RAS2FIM-2D,
Copyright (c) 2026, The University of Texas at Austin. The repository's BSD
3-Clause license and notices remain in effect for that work.
The full notice is retained in [licenses/ras2fim-LICENSE.txt](licenses/ras2fim-LICENSE.txt).

The Rust interpolation and point-location implementation follows SciPy's
`LinearNDInterpolator` and Delaunay transform/walk logic. The Python adapter
uses SciPy to prepare the ordered triangulation and transforms. SciPy is
distributed under the BSD 3-Clause license; its notice is retained in
[`licenses/scipy-LICENSE.txt`](licenses/scipy-LICENSE.txt). Relevant sources:

- [SciPy interpolation source, v1.18.1](https://github.com/scipy/scipy/blob/v1.18.1/scipy/interpolate/_interpnd.pyx)
- [SciPy Delaunay source, v1.18.1](https://github.com/scipy/scipy/blob/v1.18.1/scipy/spatial/_qhull.pyx)

Raster I/O, approximate reprojection and horizontal polygon rasterization use the statically linked
[`terrio` 0.4.2](https://github.com/opengeos/terrio) dependency, under its MIT
license, retained in `licenses/terrio-LICENSE.txt`. Terrio ports GDAL scanline
rasterization rules; its ownership fill preserves feature order and pixel-centre
inclusion. `wbvector` 0.1.6 and `wbraster` 0.2.1 provide geometry and typed raster
data; their MIT/Apache notices are retained in `licenses/`.
The engine does not link GDAL. The surrounding Python workflow
continues to use rasterio and its raster stack for preparation and file output.

Other Rust dependencies and their exact resolved versions are recorded in
`Cargo.lock`. Retain their applicable notices when distributing compiled
binaries. This provenance describes software reuse; it does not imply
endorsement by upstream projects.
