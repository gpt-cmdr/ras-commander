"""
Class: HdfInfiltration

A comprehensive class for handling infiltration-related operations in HEC-RAS HDF geometry files.
This class provides methods for managing infiltration parameters, soil statistics, and raster data processing.

Key Features:
- Infiltration parameter management (scaling, setting, retrieving)
- Soil statistics calculation and analysis
- Raster data processing and mapping
- Weighted parameter calculations
- Data export and file management

Methods:
1. Geometry File Base Override Management:
   - scale_infiltration_data(): Updates infiltration parameters with scaling factors in geometry file
   - get_infiltration_data(): Retrieves current infiltration parameters from geometry file
   - set_infiltration_table(): Sets infiltration parameters directly in geometry file

2. Raster and Mapping Operations (uses rasmap_df HDF files):
   - get_infiltration_map(): Reads infiltration raster map from rasmap_df HDF file
   - calculate_soil_statistics(): Processes zonal statistics for soil analysis

3. Soil Analysis (uses rasmap_df HDF files):
   - get_significant_mukeys(): Identifies mukeys above percentage threshold
   - calculate_total_significant_percentage(): Computes total coverage of significant mukeys
   - get_infiltration_parameters(): Retrieves parameters for specific mukey
   - calculate_weighted_parameters(): Computes weighted average parameters

4. Data Management (uses rasmap_df HDF files):
   - save_statistics(): Exports soil statistics to CSV

Constants:
- SQM_TO_ACRE: Conversion factor from square meters to acres (0.000247105)
- SQM_TO_SQMILE: Conversion factor from square meters to square miles (3.861e-7)

Dependencies:
- pathlib: Path handling
- pandas: Data manipulation
- geopandas: Geospatial data processing
- h5py: HDF file operations
- rasterstats: Zonal statistics calculation (optional)

Note:
- Methods in section 1 work with base overrides in geometry files
- Methods in sections 2-4 work with HDF files from rasmap_df by default
- All methods are static and decorated with @standardize_input and @log_call
- The class is designed to work with both HEC-RAS geometry files and rasmap_df HDF files
"""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List, Tuple
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

from .Decorators import log_call, standardize_input

class HdfInfiltration:
        
    """
    A class for handling infiltration-related operations on HEC-RAS HDF geometry files.

    This class provides methods to extract and modify infiltration data from HEC-RAS HDF geometry files,
    including base overrides of infiltration parameters.
    """

    # Constants for unit conversion
    SQM_TO_ACRE = 0.000247105
    SQM_TO_SQMILE = 3.861e-7
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _get_table_info(hdf_file: h5py.File, table_path: str) -> Tuple[List[str], List[str], List[str]]:
        """Get column names and types from HDF table
        
        Args:
            hdf_file: Open HDF file object
            table_path: Path to table in HDF file
            
        Returns:
            Tuple of (column names, numpy dtypes, column descriptions)
        """
        if table_path not in hdf_file:
            return [], [], []
            
        dataset = hdf_file[table_path]
        dtype = dataset.dtype
        
        # Extract column names and types
        col_names = []
        col_types = []
        col_descs = []
        
        for name in dtype.names:
            col_names.append(name)
            col_types.append(dtype[name].str)
            col_descs.append(name)  # Could be enhanced to get actual descriptions
            
        return col_names, col_types, col_descs

    @staticmethod
    @log_call 
    def get_infiltration_baseoverrides(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Retrieve current infiltration parameters from a HEC-RAS geometry HDF file.
        Dynamically reads whatever columns are present in the table.

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
                table_path = '/Geometry/Infiltration/Base Overrides'
                if table_path not in hdf_file:
                    logger.warning(f"No infiltration data found in {hdf_path}")
                    return None

                # Get column info
                col_names, _, _ = HdfInfiltration._get_table_info(hdf_file, table_path)
                if not col_names:
                    logger.error(f"No columns found in infiltration table")
                    return None
                    
                # Read data
                data = hdf_file[table_path][()]
                
                # Convert to DataFrame
                df_dict = {}
                for col in col_names:
                    values = data[col]
                    # Convert byte strings to regular strings if needed
                    if values.dtype.kind == 'S':
                        values = [v.decode('utf-8').strip() for v in values]
                    df_dict[col] = values
                
                return pd.DataFrame(df_dict)

        except Exception as e:
            logger.error(f"Error reading infiltration data from {hdf_path}: {str(e)}")
            return None
        
    @staticmethod
    @log_call 
    def get_infiltration_layer_data(hdf_path: Path) -> Optional[pd.DataFrame]:
        """
        Retrieve current infiltration parameters from a HEC-RAS infiltration layer HDF file.
        Extracts the Variables dataset which contains the layer data.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS infiltration layer HDF file

        Returns
        -------
        Optional[pd.DataFrame]
            DataFrame containing infiltration parameters if successful, None if operation fails
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                variables_path = '//Variables'
                if variables_path not in hdf_file:
                    logger.warning(f"No Variables dataset found in {hdf_path}")
                    return None
                
                # Read data from Variables dataset
                data = hdf_file[variables_path][()]
                
                # Convert to DataFrame
                df_dict = {}
                for field_name in data.dtype.names:
                    values = data[field_name]
                    # Convert byte strings to regular strings if needed
                    if values.dtype.kind == 'S':
                        values = [v.decode('utf-8').strip() for v in values]
                    df_dict[field_name] = values
                
                return pd.DataFrame(df_dict)

        except Exception as e:
            logger.error(f"Error reading infiltration layer data from {hdf_path}: {str(e)}")
            return None

    @staticmethod
    @log_call
    def set_infiltration_layer_data(
        hdf_path: Path,
        infiltration_df: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """
        Set infiltration layer data in the infiltration layer HDF file directly from the provided DataFrame.
        # NOTE: This will not work if there are base overrides present in the Geometry HDF file. 
        Updates the Variables dataset with the provided data.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS infiltration layer HDF file
        infiltration_df : pd.DataFrame
            DataFrame containing infiltration parameters with columns:
            - Name (string)
            - Curve Number (float)
            - Abstraction Ratio (float)
            - Minimum Infiltration Rate (float)

        Returns
        -------
        Optional[pd.DataFrame]
            The infiltration DataFrame if successful, None if operation fails
        """
        try:
            variables_path = '//Variables'
            
            # Validate required columns
            required_columns = ['Name', 'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate']
            missing_columns = [col for col in required_columns if col not in infiltration_df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            with h5py.File(hdf_path, 'a') as hdf_file:
                # Delete existing dataset if it exists
                if variables_path in hdf_file:
                    del hdf_file[variables_path]

                # Create dtype for structured array
                dt = np.dtype([
                    ('Name', f'S{infiltration_df["Name"].str.len().max()}'),
                    ('Curve Number', 'f4'),
                    ('Abstraction Ratio', 'f4'),
                    ('Minimum Infiltration Rate', 'f4')
                ])

                # Create structured array
                structured_array = np.zeros(infiltration_df.shape[0], dtype=dt)
                
                # Fill structured array
                structured_array['Name'] = infiltration_df['Name'].values.astype(f'|S{dt["Name"].itemsize}')
                structured_array['Curve Number'] = infiltration_df['Curve Number'].values
                structured_array['Abstraction Ratio'] = infiltration_df['Abstraction Ratio'].values
                structured_array['Minimum Infiltration Rate'] = infiltration_df['Minimum Infiltration Rate'].values

                # Create new dataset
                hdf_file.create_dataset(
                    variables_path,
                    data=structured_array,
                    dtype=dt,
                    compression='gzip',
                    compression_opts=1,
                    chunks=(100,),
                    maxshape=(None,)
                )

            return infiltration_df

        except Exception as e:
            logger.error(f"Error setting infiltration layer data in {hdf_path}: {str(e)}")
            return None
    @staticmethod
    @standardize_input(file_type='geom_hdf')
    @log_call
    def scale_infiltration_data(
        hdf_path: Path,
        infiltration_df: pd.DataFrame,
        scale_factors: Dict[str, float]
    ) -> Optional[pd.DataFrame]:
        """
        Update infiltration parameters in the HDF file with scaling factors.
        Supports any numeric columns present in the DataFrame.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        infiltration_df : pd.DataFrame
            DataFrame containing infiltration parameters
        scale_factors : Dict[str, float]
            Dictionary mapping column names to their scaling factors

        Returns
        -------
        Optional[pd.DataFrame]
            The updated infiltration DataFrame if successful, None if operation fails
        """
        try:
            # Make a copy to avoid modifying the input DataFrame
            infiltration_df = infiltration_df.copy()
            
            # Apply scaling factors to specified columns
            for col, factor in scale_factors.items():
                if col in infiltration_df.columns and pd.api.types.is_numeric_dtype(infiltration_df[col]):
                    infiltration_df[col] *= factor
                else:
                    logger.warning(f"Column {col} not found or not numeric - skipping scaling")

            # Use set_infiltration_table to write the scaled data
            return HdfInfiltration.set_infiltration_table(hdf_path, infiltration_df)

        except Exception as e:
            logger.error(f"Error scaling infiltration data in {hdf_path}: {str(e)}")
            return None

    @staticmethod
    @log_call
    @standardize_input
    def get_infiltration_map(hdf_path: Path = None, ras_object: Any = None) -> dict:
        """Read the infiltration raster map from HDF file
        
        Args:
            hdf_path: Optional path to the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df
            ras_object: Optional RAS object. If not provided, uses global ras instance
            
        Returns:
            Dictionary mapping raster values to mukeys
        """
        if hdf_path is None:
            if ras_object is None:
                from .RasPrj import ras
                ras_object = ras
            hdf_path = Path(ras_object.rasmap_df.iloc[0]['infiltration_hdf_path'][0])
            
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
        
        try:
            from rasterstats import zonal_stats
        except ImportError as e:
            logger.error("Failed to import rasterstats. Please run 'pip install rasterstats' and try again.")
            raise e
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
    def get_infiltration_parameters(hdf_path: Path = None, mukey: str = None, ras_object: Any = None) -> dict:
        """Get infiltration parameters for a specific mukey from HDF file
        
        Args:
            hdf_path: Optional path to the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df
            mukey: Mukey identifier
            ras_object: Optional RAS object. If not provided, uses global ras instance
            
        Returns:
            Dictionary of infiltration parameters
        """
        if hdf_path is None:
            if ras_object is None:
                from .RasPrj import ras
                ras_object = ras
            hdf_path = Path(ras_object.rasmap_df.iloc[0]['infiltration_hdf_path'][0])
            
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





'''

THIS FUNCTION IS VERY CLOSE BUT DOES NOT WORK BECAUSE IT DOES NOT PRESERVE THE EXACT STRUCTURE OF THE HDF FILE.
WHEN RAS LOADS THE HDF, IT IGNORES THE DATA IN THE TABLE AND REPLACES IT WITH NULLS.


    @staticmethod
    @log_call
    def set_infiltration_baseoverrides(
        hdf_path: Path,
        infiltration_df: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """
        Set base overrides for infiltration parameters in the HDF file while preserving
        the exact structure of the existing dataset.
        
        This function ensures that the HDF structure is maintained exactly as in the
        original file, including field names, data types, and string lengths. It updates
        the values while preserving all dataset attributes.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        infiltration_df : pd.DataFrame
            DataFrame containing infiltration parameters with columns matching HDF structure.
            The first column should be 'Name' or 'Land Cover Name'.

        Returns
        -------
        Optional[pd.DataFrame]
            The infiltration DataFrame if successful, None if operation fails
        """
        try:
            # Make a copy to avoid modifying the input DataFrame
            infiltration_df = infiltration_df.copy()
            
            # Check for and rename the first column if needed
            if "Land Cover Name" in infiltration_df.columns:
                name_col = "Land Cover Name"
            else:
                name_col = "Name"
                # Rename 'Name' to 'Land Cover Name' for HDF dataset
                infiltration_df = infiltration_df.rename(columns={"Name": "Land Cover Name"})
                
            table_path = '/Geometry/Infiltration/Base Overrides'
            
            with h5py.File(hdf_path, 'r') as hdf_file_read:
                # Check if dataset exists
                if table_path not in hdf_file_read:
                    logger.warning(f"No infiltration data found in {hdf_path}. Creating new dataset.")
                    # If dataset doesn't exist, use the standard set_infiltration_baseoverrides method
                    return HdfInfiltration.set_infiltration_baseoverrides(hdf_path, infiltration_df)
                
                # Get the exact dtype of the existing dataset
                existing_dtype = hdf_file_read[table_path].dtype
                
                # Extract column names from the existing dataset
                existing_columns = existing_dtype.names
                
                # Check if all columns in the DataFrame exist in the HDF dataset
                for col in infiltration_df.columns:
                    hdf_col = col
                    if col == "Name" and "Land Cover Name" in existing_columns:
                        hdf_col = "Land Cover Name"
                    
                    if hdf_col not in existing_columns:
                        logger.warning(f"Column {col} not found in existing dataset - it will be ignored")
                
                # Get current dataset to preserve structure for non-updated fields
                existing_data = hdf_file_read[table_path][()]
            
            # Create a structured array with the exact same dtype as the existing dataset
            structured_array = np.zeros(len(infiltration_df), dtype=existing_dtype)
            
            # Copy data from DataFrame to structured array, preserving existing structure
            for col in existing_columns:
                df_col = col
                # Map 'Land Cover Name' to 'Name' if needed
                if col == "Land Cover Name" and name_col == "Name":
                    df_col = "Name"
                    
                if df_col in infiltration_df.columns:
                    # Handle string fields - need to maintain exact string length
                    if existing_dtype[col].kind == 'S':
                        # Get the exact string length from dtype
                        max_str_len = existing_dtype[col].itemsize
                        # Convert to bytes with correct length
                        structured_array[col] = infiltration_df[df_col].astype(str).values.astype(f'|S{max_str_len}')
                    else:
                        # Handle numeric fields - ensure correct numeric type
                        if existing_dtype[col].kind in ('f', 'i'):
                            structured_array[col] = infiltration_df[df_col].values.astype(existing_dtype[col])
                        else:
                            # For any other type, just copy as is
                            structured_array[col] = infiltration_df[df_col].values
                else:
                    logger.warning(f"Column {col} not in DataFrame - using default values")
                    # Use zeros for numeric fields or empty strings for string fields
                    if existing_dtype[col].kind == 'S':
                        structured_array[col] = np.array([''] * len(infiltration_df), dtype=f'|S{existing_dtype[col].itemsize}')
            
            # Write back to HDF file
            with h5py.File(hdf_path, 'a') as hdf_file_write:
                # Delete existing dataset
                if table_path in hdf_file_write:
                    del hdf_file_write[table_path]
                
                # Create new dataset with exact same properties as original
                dataset = hdf_file_write.create_dataset(
                    table_path,
                    data=structured_array,
                    dtype=existing_dtype,
                    compression='gzip',
                    compression_opts=1,
                    chunks=(100,),
                    maxshape=(None,)
                )
            
            # Return the DataFrame with columns matching what was actually written
            result_df = pd.DataFrame()
            for col in existing_columns:
                if existing_dtype[col].kind == 'S':
                    # Convert bytes back to string
                    result_df[col] = [val.decode('utf-8').strip() for val in structured_array[col]]
                else:
                    result_df[col] = structured_array[col]
                    
            return result_df

        except Exception as e:
            logger.error(f"Error setting infiltration data in {hdf_path}: {str(e)}")
            return None






'''