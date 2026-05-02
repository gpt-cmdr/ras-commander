"""
ras-commander terrain subpackage: HEC-RAS terrain creation, manipulation, and analysis.

This subpackage provides terrain capabilities for HEC-RAS projects:
- Terrain HDF creation from rasters via RasProcess.exe CreateTerrain
- VRT mosaic to single TIFF conversion via HEC-RAS GDAL tools
- USGS 3DEP elevation data download from AWS
- Terrain modification writing for channel, high-ground, and fill-surface layers
- Terrain modification analysis (cut/fill, no-net-fill) via RasMapperLib.dll

Main Classes:
    RasTerrain: Terrain HDF creation and VRT conversion (RasProcess.exe CLI)
        - create_terrain_hdf(): Create terrain HDF from input rasters
        - vrt_to_tiff(): Convert VRT to single TIFF with overviews

    Usgs3depAws: USGS 3DEP elevation tile download from AWS S3
        - find_tiles_for_bbox(): Find tiles covering a bounding box
        - download_tiles(): Download tiles with concurrent threads

    RasTerrainMod: Terrain modification analysis via pythonnet (Windows only)
        - get_terrain_profile(): Sample terrain with modifications applied
        - get_terrain_volume_elevation(): Elevation-volume curve for polygons
        - compare_terrain_profiles(): Cut/fill analysis between terrains
        - compare_terrain_volumes(): No-net-fill compliance checking
        - compute_modified_terrain_raster(): Full-resolution GeoTIFF of modified terrain
        Requires: pythonnet, HEC-RAS 6.6+ with bundled GDAL

    RasTerrainModWriter: Terrain modification HDF and .rasmap writer
        - add_channel_modification(): add TakeLower channel cuts
        - add_high_ground_modification(): add TakeHigher levee/road lines
        - add_fill_surface_modification(): add SetValue fill surfaces
        - list_modifications(): inspect terrain modification sidecar groups

Requirements:
    - HEC-RAS 6.3+ installed (for RasProcess.exe and GDAL tools)
    - Optional: pythonnet for RasTerrainMod (terrain modification analysis)
    - Optional: rasterio for advanced raster analysis

Usage:
    from ras_commander.terrain import RasTerrain, RasTerrainMod

    # Create terrain HDF from TIFF files
    terrain_hdf = RasTerrain.create_terrain_hdf(
        input_rasters=[Path("dem.tif")],
        output_hdf=Path("Terrain/Terrain.hdf"),
        projection_prj=Path("Terrain/Projection.prj"),
    )

    # Sample terrain with modifications (no GUI required)
    RasTerrainMod.setup_gdal_bridge()  # optional explicit preflight
    profile = RasTerrainMod.get_terrain_profile(
        "project.rasmap", "project.g01.hdf",
        x_coords=[3400000, 3410000], y_coords=[612000, 612000]
    )

See Also:
    - examples/920_terrain_creation.ipynb for terrain creation workflow
    - examples/930_terrain_modification_analysis.ipynb for cut/fill analysis
"""

from .RasTerrain import RasTerrain
from .Usgs3depAws import Usgs3depAws
from .RasTerrainModWriter import RasTerrainModWriter

# Conditional import - RasTerrainMod requires pythonnet (Windows only)
try:
    from .RasTerrainMod import RasTerrainMod
    __all__ = ['RasTerrain', 'Usgs3depAws', 'RasTerrainMod', 'RasTerrainModWriter']
except ImportError:
    __all__ = ['RasTerrain', 'Usgs3depAws', 'RasTerrainModWriter']
