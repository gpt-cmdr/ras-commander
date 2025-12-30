"""
ras-commander terrain subpackage: HEC-RAS terrain creation and manipulation.

This subpackage provides terrain creation capabilities for HEC-RAS projects,
including HDF terrain creation via RasProcess.exe and VRT to TIFF conversion.

Key Capabilities:
    - Create HEC-RAS terrain HDF from input rasters using RasProcess.exe CreateTerrain
    - Convert VRT mosaics to single optimized TIFF files using HEC-RAS GDAL tools
    - Generate ESRI PRJ files from raster coordinate reference systems
    - Support for multiple HEC-RAS versions (6.3+)

Main Class:
    RasTerrain: Static methods for terrain operations
        - create_terrain_hdf(): Create HEC-RAS terrain HDF from input rasters
        - vrt_to_tiff(): Convert VRT to single TIFF with optional overviews

Requirements:
    - HEC-RAS 6.3+ installed (for RasProcess.exe and GDAL tools)
    - No additional Python packages required for core functionality
    - Optional: rasterio for advanced raster analysis

Usage:
    from ras_commander.terrain import RasTerrain
    from pathlib import Path

    # Create terrain HDF from TIFF files
    terrain_hdf = RasTerrain.create_terrain_hdf(
        input_rasters=[Path("dem.tif")],
        output_hdf=Path("Terrain/Terrain.hdf"),
        projection_prj=Path("Terrain/Projection.prj"),
        units="Feet",
        hecras_version="6.6"
    )

    # Convert VRT mosaic to single TIFF
    output_tiff = RasTerrain.vrt_to_tiff(
        vrt_path=Path("combined.vrt"),
        output_path=Path("combined.tif"),
        compression="LZW"
    )

See Also:
    - feature_dev_notes/HEC-RAS_Terrain_CLI/CLAUDE.md for design documentation
    - examples/800_terrain_creation.ipynb for complete workflow
"""

from .RasTerrain import RasTerrain
from .Usgs3depAws import Usgs3depAws

__all__ = ['RasTerrain', 'Usgs3depAws']
