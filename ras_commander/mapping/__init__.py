"""
Mapping module for RASMapper-style water surface rasterization.

This module provides functions to generate water surface elevation rasters
using the same algorithms as RASMapper, including support for both
"Horizontal" and "Sloped (Cell Corners)" interpolation modes.

Modules:
--------
sloped_interpolation
    Core computation functions for sloped WSE interpolation:
    - PlanarRegressionZ: Least-squares planar regression
    - compute_face_wse: Face WSE with hydraulic connectivity
    - compute_face_midsides: Face application points
    - compute_vertex_wse: Vertex WSE via planar regression

rasterization
    Triangle rasterization for sloped surfaces:
    - rasterize_sloped_wse: Rasterize triangulated mesh to grid

Example
-------
>>> from ras_commander.mapping import compute_sloped_wse
>>>
>>> # Generate sloped WSE raster
>>> output_path = compute_sloped_wse(
...     plan_hdf_path="project.p01.hdf",
...     terrain_path="Terrain/Terrain.tif",
...     output_path="outputs/sloped_wse.tif"
... )
"""

from .sloped_interpolation import (
    PlanarRegressionZ,
    compute_face_wse,
    compute_face_midsides,
    compute_vertex_wse,
    compute_sloped_wse_arrays,
    compute_bens_weights,
    interpolate_pixel_wse,
    HydraulicConnection,
    NODATA,
)

from .rasterization import (
    rasterize_sloped_wse,
    rasterize_sloped_wse_bens_weights,
    rasterize_sloped_wse_griddata,
    rasterize_sloped_wse_from_tif,
    build_cell_triangles,
    PlaneInterpolator,
)

__all__ = [
    # Sloped interpolation
    'PlanarRegressionZ',
    'compute_face_wse',
    'compute_face_midsides',
    'compute_vertex_wse',
    'compute_sloped_wse_arrays',
    'compute_bens_weights',
    'interpolate_pixel_wse',
    'HydraulicConnection',
    'NODATA',
    # Rasterization
    'rasterize_sloped_wse',
    'rasterize_sloped_wse_bens_weights',
    'rasterize_sloped_wse_griddata',
    'rasterize_sloped_wse_from_tif',
    'build_cell_triangles',
    'PlaneInterpolator',
]
