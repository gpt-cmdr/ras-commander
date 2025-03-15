"""
Class: HdfInfiltration

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfInfiltration:
- scale_infiltration_data(): Updates infiltration parameters in HDF file with scaling factors
- get_infiltration_data(): Retrieves current infiltration parameters from HDF file
- get_infiltration_map(): Reads the infiltration raster map from HDF file
- calculate_soil_statistics(): Calculates soil statistics from zonal statistics
- get_significant_mukeys(): Gets mukeys with percentage greater than threshold
- calculate_total_significant_percentage(): Calculates total percentage covered by significant mukeys
- save_statistics(): Saves soil statistics to CSV
- get_infiltration_parameters(): Gets infiltration parameters for a specific mukey
- calculate_weighted_parameters(): Calculates weighted infiltration parameters based on soil statistics

Each function is decorated with @standardize_input to ensure consistent handling of HDF file paths
and @log_call for logging function calls and errors. Functions return various data types including
DataFrames, dictionaries, and floating-point values depending on their purpose.

The class provides comprehensive functionality for analyzing and modifying infiltration-related
data in HEC-RAS HDF files, including parameter scaling, soil statistics calculation, and
weighted parameter computation.
"""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any
import logging
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)
        
from pathlib import Path
import pandas as pd
import geopandas as gpd
import h5py
from rasterstats import zonal_stats
from .Decorators import log_call, standardize_input

class HdfInfiltration:
        
    """
    A class for handling infiltration-related operations on HEC-RAS HDF files.

    This class provides methods to extract and modify infiltration data from HEC-RAS HDF files,
    including base overrides and infiltration parameters.
    """

    # Constants for unit conversion
    SQM_TO_ACRE = 0.000247105
    SQM_TO_SQMILE = 3.861e-7
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    @log_call
    def scale_infiltration_data(
        hdf_path: Path,
        infiltration_df: pd.DataFrame,
        scale_md: float = 1.0,
        scale_id: float = 1.0,
        scale_pr: float = 1.0
    ) -> Optional[pd.DataFrame]:
        """
        Update infiltration parameters in the HDF file with optional scaling factors.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        infiltration_df : pd.DataFrame
            DataFrame containing infiltration parameters with columns:
            ['Name', 'Maximum Deficit', 'Initial Deficit', 'Potential Percolation Rate']
        scale_md : float, optional
            Scaling factor for Maximum Deficit, by default 1.0
        scale_id : float, optional
            Scaling factor for Initial Deficit, by default 1.0
        scale_pr : float, optional
            Scaling factor for Potential Percolation Rate, by default 1.0

        Returns
        -------
        Optional[pd.DataFrame]
            The updated infiltration DataFrame if successful, None if operation fails
        """
        try:
            hdf_path_to_overwrite = '/Geometry/Infiltration/Base Overrides'
            
            # Apply scaling factors
            infiltration_df = infiltration_df.copy()
            infiltration_df['Maximum Deficit'] *= scale_md
            infiltration_df['Initial Deficit'] *= scale_id
            infiltration_df['Potential Percolation Rate'] *= scale_pr

            with h5py.File(hdf_path, 'a') as hdf_file:
                # Delete existing dataset if it exists
                if hdf_path_to_overwrite in hdf_file:
                    del hdf_file[hdf_path_to_overwrite]

                # Define dtype for structured array
                dt = np.dtype([
                    ('Land Cover Name', 'S7'),
                    ('Maximum Deficit', 'f4'),
                    ('Initial Deficit', 'f4'),
                    ('Potential Percolation Rate', 'f4')
                ])

                # Create structured array
                structured_array = np.zeros(infiltration_df.shape[0], dtype=dt)
                structured_array['Land Cover Name'] = np.array(infiltration_df['Name'].astype(str).values.astype('|S7'))
                structured_array['Maximum Deficit'] = infiltration_df['Maximum Deficit'].values.astype(np.float32)
                structured_array['Initial Deficit'] = infiltration_df['Initial Deficit'].values.astype(np.float32)
                structured_array['Potential Percolation Rate'] = infiltration_df['Potential Percolation Rate'].values.astype(np.float32)

                # Create new dataset
                hdf_file.create_dataset(
                    hdf_path_to_overwrite,
                    data=structured_array,  
                    dtype=dt,
                    compression='gzip',
                    compression_opts=1,
                    chunks=(100,),
                    maxshape=(None,)
                )

            return infiltration_df

        except Exception as e:
            logger.error(f"Error updating infiltration data in {hdf_path}: {str(e)}")
            return None

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    @log_call
    def get_infiltration_data(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Retrieve current infiltration parameters from the HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file

        Returns
        -------
        Optional[pd.DataFrame]
            DataFrame containing infiltration parameters if successful, None if operation fails
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if '/Geometry/Infiltration/Base Overrides' not in hdf_file:
                    logger.warning(f"No infiltration data found in {hdf_path}")
                    return None

                data = hdf_file['/Geometry/Infiltration/Base Overrides'][()]
                
                # Convert structured array to DataFrame
                df = pd.DataFrame({
                    'Name': [name.decode('utf-8').strip() for name in data['Land Cover Name']],
                    'Maximum Deficit': data['Maximum Deficit'],
                    'Initial Deficit': data['Initial Deficit'],
                    'Potential Percolation Rate': data['Potential Percolation Rate']
                })
                
                return df

        except Exception as e:
            logger.error(f"Error reading infiltration data from {hdf_path}: {str(e)}")
            return None
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        


    @staticmethod
    @log_call
    @standardize_input
    def get_infiltration_map(hdf_path: Path) -> dict:
        """Read the infiltration raster map from HDF file
        
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
    def calculate_soil_statistics(zonal_stats: list, raster_map: dict) -> pd.DataFrame:
        """Calculate soil statistics from zonal statistics
        
        Args:
            zonal_stats: List of zonal statistics
            raster_map: Dictionary mapping raster values to mukeys
            
        Returns:
            DataFrame with soil statistics including percentages and areas
        """
        # Initialize areas dictionary
        mukey_areas = {mukey: 0 for mukey in raster_map.values()}
        
        # Calculate total area and mukey areas
        total_area_sqm = 0
        for stat in zonal_stats:
            for raster_val, area in stat.items():
                mukey = raster_map.get(raster_val)
                if mukey:
                    mukey_areas[mukey] += area
                total_area_sqm += area

        # Create DataFrame rows
        rows = []
        for mukey, area_sqm in mukey_areas.items():
            if area_sqm > 0:
                rows.append({
                    'mukey': mukey,
                    'Percentage': (area_sqm / total_area_sqm) * 100,
                    'Area in Acres': area_sqm * HdfInfiltration.SQM_TO_ACRE,
                    'Area in Square Miles': area_sqm * HdfInfiltration.SQM_TO_SQMILE
                })
        
        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    def get_significant_mukeys(soil_stats: pd.DataFrame, 
                             threshold: float = 1.0) -> pd.DataFrame:
        """Get mukeys with percentage greater than threshold
        
        Args:
            soil_stats: DataFrame with soil statistics
            threshold: Minimum percentage threshold (default 1.0)
            
        Returns:
            DataFrame with significant mukeys and their statistics
        """
        significant = soil_stats[soil_stats['Percentage'] > threshold].copy()
        significant.sort_values('Percentage', ascending=False, inplace=True)
        return significant

    @staticmethod
    @log_call
    def calculate_total_significant_percentage(significant_mukeys: pd.DataFrame) -> float:
        """Calculate total percentage covered by significant mukeys
        
        Args:
            significant_mukeys: DataFrame of significant mukeys
            
        Returns:
            Total percentage covered by significant mukeys
        """
        return significant_mukeys['Percentage'].sum()

    @staticmethod
    @log_call
    def save_statistics(soil_stats: pd.DataFrame, output_path: Path, 
                       include_timestamp: bool = True):
        """Save soil statistics to CSV
        
        Args:
            soil_stats: DataFrame with soil statistics
            output_path: Path to save CSV file
            include_timestamp: Whether to include timestamp in filename
        """
        if include_timestamp:
            timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
            output_path = output_path.with_name(
                f"{output_path.stem}_{timestamp}{output_path.suffix}")
        
        soil_stats.to_csv(output_path, index=False)

    @staticmethod
    @log_call
    @standardize_input
    def get_infiltration_parameters(hdf_path: Path, mukey: str) -> dict:
        """Get infiltration parameters for a specific mukey from HDF file
        
        Args:
            hdf_path: Path to the HDF file
            mukey: Mukey identifier
            
        Returns:
            Dictionary of infiltration parameters
        """
        with h5py.File(hdf_path, 'r') as hdf:
            if 'Infiltration Parameters' not in hdf:
                raise KeyError("No infiltration parameters found in HDF file")
                
            params = hdf['Infiltration Parameters'][:]
            for row in params:
                if row[0].decode('utf-8') == mukey:
                    return {
                        'Initial Loss (in)': float(row[1]),
                        'Constant Loss Rate (in/hr)': float(row[2]),
                        'Impervious Area (%)': float(row[3])
                    }
        return None

    @staticmethod
    @log_call
    def calculate_weighted_parameters(soil_stats: pd.DataFrame, 
                                   infiltration_params: dict) -> dict:
        """Calculate weighted infiltration parameters based on soil statistics
        
        Args:
            soil_stats: DataFrame with soil statistics
            infiltration_params: Dictionary of infiltration parameters by mukey
            
        Returns:
            Dictionary of weighted average infiltration parameters
        """
        total_weight = soil_stats['Percentage'].sum()
        
        weighted_params = {
            'Initial Loss (in)': 0.0,
            'Constant Loss Rate (in/hr)': 0.0,
            'Impervious Area (%)': 0.0
        }
        
        for _, row in soil_stats.iterrows():
            mukey = row['mukey']
            weight = row['Percentage'] / total_weight
            
            if mukey in infiltration_params:
                for param in weighted_params:
                    weighted_params[param] += (
                        infiltration_params[mukey][param] * weight
                    )
        
        return weighted_params

# Example usage:
"""
from pathlib import Path

# Initialize paths
raster_path = Path('input_files/gSSURGO_InfiltrationDC.tif')
boundary_path = Path('input_files/WF_Boundary_Simple.shp')
hdf_path = raster_path.with_suffix('.hdf')

# Get infiltration mapping
infil_map = HdfInfiltration.get_infiltration_map(hdf_path)

# Get zonal statistics (using RasMapper class)
clipped_data, transform, nodata = RasMapper.clip_raster_with_boundary(
    raster_path, boundary_path)
stats = RasMapper.calculate_zonal_stats(
    boundary_path, clipped_data, transform, nodata)

# Calculate soil statistics
soil_stats = HdfInfiltration.calculate_soil_statistics(stats, infil_map)

# Get significant mukeys (>1%)
significant = HdfInfiltration.get_significant_mukeys(soil_stats, threshold=1.0)

# Calculate total percentage of significant mukeys
total_significant = HdfInfiltration.calculate_total_significant_percentage(significant)
print(f"Total percentage of significant mukeys: {total_significant}%")

# Get infiltration parameters for each significant mukey
infiltration_params = {}
for mukey in significant['mukey']:
    params = HdfInfiltration.get_infiltration_parameters(hdf_path, mukey)
    if params:
        infiltration_params[mukey] = params

# Calculate weighted parameters
weighted_params = HdfInfiltration.calculate_weighted_parameters(
    significant, infiltration_params)
print("Weighted infiltration parameters:", weighted_params)

# Save results
HdfInfiltration.save_statistics(soil_stats, Path('soil_statistics.csv'))
"""