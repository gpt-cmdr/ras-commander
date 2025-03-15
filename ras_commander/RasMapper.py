"""
Class: RasMapper

List of Functions:
    get_raster_map(hdf_path: Path) 
    clip_raster_with_boundary(raster_path: Path, boundary_path: Path) 
    calculate_zonal_stats(boundary_path: Path, raster_data, transform, nodata) 

"""



from pathlib import Path
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask
import h5py
from .Decorators import log_call, standardize_input
from .HdfInfiltration import HdfInfiltration

class RasMapper:
    """Class for handling RAS Mapper operations and data extraction"""
    # PLACEHOLDER FOR FUTURE DEVELOPMENT