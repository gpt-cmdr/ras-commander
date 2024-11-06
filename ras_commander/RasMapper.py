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

    @staticmethod
    @log_call
    def get_raster_map(hdf_path: Path) -> dict:
        """Read the raster map from HDF file and create value mapping
        
        Args:
            hdf_path: Path to the HDF file
            
        Returns:
            Dictionary mapping raster values to mukeys
        """
        with h5py.File(hdf_path, 'r') as hdf:
            raster_map_data = hdf['Raster Map'][:]
            return {int(item[0]): item[1].decode('utf-8') for item in raster_map_data}

    @staticmethod
    @log_call 
    def clip_raster_with_boundary(raster_path: Path, boundary_path: Path):
        """Clip a raster using a boundary polygon
        
        Args:
            raster_path: Path to the raster file
            boundary_path: Path to the boundary shapefile
            
        Returns:
            Tuple of (clipped_image, transform, nodata_value)
        """
        watershed = gpd.read_file(boundary_path)
        raster = rasterio.open(raster_path)
        
        out_image, out_transform = mask(raster, watershed.geometry, crop=True)
        nodata = raster.nodatavals[0]
        
        return out_image[0], out_transform, nodata

    @staticmethod
    @log_call
    def calculate_zonal_stats(boundary_path: Path, raster_data, transform, nodata):
        """Calculate zonal statistics for a boundary
        
        Args:
            boundary_path: Path to boundary shapefile
            raster_data: Numpy array of raster values
            transform: Raster transform
            nodata: Nodata value
            
        Returns:
            List of statistics by zone
        """
        watershed = gpd.read_file(boundary_path)
        return zonal_stats(watershed, raster_data, 
                         affine=transform, 
                         nodata=nodata,
                         categorical=True)

# Example usage:
"""
# Initialize paths
raster_path = Path('input_files/gSSURGO_InfiltrationDC.tif')
boundary_path = Path('input_files/WF_Boundary_Simple.shp')
hdf_path = raster_path.with_suffix('.hdf')

# Get raster mapping
raster_map = RasMapper.get_raster_map(hdf_path)

# Clip raster with boundary
clipped_data, transform, nodata = RasMapper.clip_raster_with_boundary(
    raster_path, boundary_path)

# Calculate zonal statistics
stats = RasMapper.calculate_zonal_stats(
    boundary_path, clipped_data, transform, nodata)

# Calculate soil statistics
soil_stats = HdfInfiltration.calculate_soil_statistics(
    stats, raster_map)

# Get significant mukeys (>1%)
significant_mukeys = HdfInfiltration.get_significant_mukeys(
    soil_stats, threshold=1.0)
"""