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
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class HdfInfiltration:
        
    """
    A class for handling infiltration-related operations on HEC-RAS HDF geometry files.

    This class provides methods to extract and modify infiltration data from HEC-RAS HDF geometry files,
    including base overrides of infiltration parameters.
    """

    # Constants for unit conversion
    SQM_TO_ACRE = 0.000247105
    SQM_TO_SQMILE = 3.861e-7

    # Valid infiltration variables for preprocessed cell-level data
    INFILTRATION_VARIABLES = [
        'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate',
        'Maximum Deficit', 'Initial Deficit', 'Potential Percolation Rate',
        'Wetting Front Suction', 'Saturated Hydraulic Conductivity',
        'Initial Soil Water Content', 'Saturated Soil Water Content',
    ]

    @staticmethod
    def _is_nodata_value(value: Any, no_data: Any) -> bool:
        """Return True when a categorical raster value should be ignored."""
        if value is None:
            return True
        if no_data is None:
            return False
        try:
            if pd.isna(no_data) and pd.isna(value):
                return True
        except TypeError:
            pass
        return value == no_data

    @staticmethod
    def _get_linear_unit_to_meter(crs: Any) -> float:
        """Return the linear-unit conversion factor from CRS units to meters."""
        if crs is None:
            raise ValueError(
                "Raster CRS is missing. Cannot compute area_sqm, area_acres, "
                "or area_sqmiles without a projected CRS."
            )

        if getattr(crs, 'is_geographic', False):
            raise ValueError(
                "Raster CRS is geographic. Cannot compute area_sqm, "
                "area_acres, or area_sqmiles from angular units."
            )

        linear_units_factor = getattr(crs, 'linear_units_factor', None)
        if linear_units_factor is None:
            raise ValueError(
                "Raster CRS does not report a linear unit factor. Cannot "
                "compute area_sqm, area_acres, or area_sqmiles."
            )

        if isinstance(linear_units_factor, tuple):
            linear_units_factor = linear_units_factor[1]

        return float(linear_units_factor)

    @staticmethod
    def _get_raster_cell_area_sqm(raster_src: Any) -> float:
        """Return raster cell area in square meters."""
        transform = raster_src.transform
        cell_area_native = abs(
            (transform.a * transform.e) - (transform.b * transform.d)
        )
        if cell_area_native <= 0:
            raise ValueError(
                "Raster transform does not define a positive cell area."
            )
        linear_unit_to_meter = HdfInfiltration._get_linear_unit_to_meter(
            getattr(raster_src, 'crs', None)
        )
        return cell_area_native * (linear_unit_to_meter ** 2)

    @staticmethod
    def _categorical_counts_to_area_sqm(
        stats: Dict[Any, Any],
        no_data: Any,
        cell_area_sqm: float,
    ) -> Tuple[Dict[Any, float], float]:
        """Convert categorical pixel counts into square-meter areas."""
        area_by_value = {}
        total_area_sqm = 0.0

        for raster_val, pixel_count in stats.items():
            if HdfInfiltration._is_nodata_value(raster_val, no_data):
                continue

            area_sqm = float(pixel_count) * cell_area_sqm
            area_by_value[raster_val] = area_sqm
            total_area_sqm += area_sqm

        return area_by_value, total_area_sqm

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_preprocessed_infiltration(
        hdf_path: Path,
        mesh_name: Optional[str] = None,
        variable: str = 'Curve Number',
        ras_object=None
    ) -> pd.DataFrame:
        """
        Read preprocessed per-cell infiltration values from geometry HDF.

        Returns the exact per-cell infiltration parameter values that HEC-RAS
        uses in computation, from
        ``/Geometry/2D Flow Areas/{mesh}/Infiltration/{variable}``.
        These reflect all overrides (base + calibration regions) as resolved
        during geometry preprocessing.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            mesh_name: Specific 2D flow area. If None, reads all.
            variable: Infiltration variable name. Common values:
                'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: mesh_name, cell_id, value

        Example:
            >>> cn = HdfInfiltration.get_preprocessed_infiltration("01", variable='Curve Number')
        """
        results = []

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                areas_path = "Geometry/2D Flow Areas"
                if areas_path not in hdf_file:
                    logger.warning(f"No 2D Flow Areas found in {hdf_path}")
                    return pd.DataFrame(columns=['mesh_name', 'cell_id', 'value'])

                areas_group = hdf_file[areas_path]

                for area_name in areas_group:
                    # Skip datasets - only process groups (mesh perimeters)
                    if not isinstance(areas_group[area_name], h5py.Group):
                        continue
                    if mesh_name is not None and area_name != mesh_name:
                        continue

                    area = areas_group[area_name]
                    var_path = f"Infiltration/{variable}"

                    if var_path not in area:
                        logger.debug(f"No '{variable}' data for mesh '{area_name}'")
                        continue

                    values = area[var_path][()]
                    n_cells = len(values)

                    area_df = pd.DataFrame({
                        'mesh_name': [area_name] * n_cells,
                        'cell_id': range(n_cells),
                        'value': values.astype(float),
                    })
                    results.append(area_df)

        except Exception as e:
            logger.error(f"Error reading preprocessed infiltration from {hdf_path}: {e}")
            return pd.DataFrame(columns=['mesh_name', 'cell_id', 'value'])

        if not results:
            return pd.DataFrame(columns=['mesh_name', 'cell_id', 'value'])

        return pd.concat(results, ignore_index=True)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_preprocessed_infiltration_stats(
        hdf_path: Path,
        mesh_name: Optional[str] = None,
        variable: str = 'Curve Number',
        ras_object=None
    ) -> pd.DataFrame:
        """
        Compute statistics on preprocessed per-cell infiltration values.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            mesh_name: Specific 2D flow area. If None, computes for all.
            variable: Infiltration variable name.
            ras_object: Optional RasPrj object.

        Returns:
            DataFrame with columns: mesh_name, variable, n_cells,
            min_val, max_val, mean_val, median_val, std_val
        """
        df = HdfInfiltration.get_preprocessed_infiltration(
            hdf_path, mesh_name, variable, ras_object
        )

        if len(df) == 0:
            return pd.DataFrame(columns=[
                'mesh_name', 'variable', 'n_cells',
                'min_val', 'max_val', 'mean_val', 'median_val', 'std_val'
            ])

        stats = df.groupby('mesh_name').agg(
            n_cells=('value', 'count'),
            min_val=('value', 'min'),
            max_val=('value', 'max'),
            mean_val=('value', 'mean'),
            median_val=('value', 'median'),
            std_val=('value', 'std'),
        ).reset_index()
        stats['variable'] = variable

        return stats

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
    @standardize_input(file_type='geom_hdf')
    def get_infiltration_region_names(hdf_path: Path) -> Optional[List[str]]:
        """Retrieve infiltration region names from a HEC-RAS geometry HDF file.

        Reads the ``Name`` field from the structured array at
        ``Geometry/Infiltration/Attributes``.

        Args:
            hdf_path: Path to the HEC-RAS geometry HDF file.

        Returns:
            A list of infiltration region name strings, or ``None`` if the
            dataset does not exist.

        Example
        -------
        >>> names = HdfInfiltration.get_infiltration_region_names("model.g01.hdf")
        >>> print(names)
        ['Grass', 'Paving - Concrete', 'Detention Pond']
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                attrs_path = "Geometry/Infiltration/Attributes"
                if attrs_path not in hdf_file:
                    logger.warning(f"No infiltration attributes found in {hdf_path}")
                    return None

                data = hdf_file[attrs_path][()]
                names = list(np.vectorize(HdfUtils.convert_ras_string)(data['Name']))
                return names

        except Exception as e:
            logger.error(f"Error reading infiltration region names from {hdf_path}: {str(e)}")
            return None

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_infiltration_calibration_regions(hdf_path: Path) -> Optional[Dict[str, pd.DataFrame]]:
        """Retrieve infiltration calibration region data from a HEC-RAS geometry HDF file.

        Reads compound datasets from ``Geometry/Infiltration/Variables`` (e.g.
        Curve Number, Abstraction Ratio, Minimum Infiltration Rate) and builds
        a DataFrame for each, indexed by the infiltration region names from
        ``Geometry/Infiltration/Attributes``.

        Args:
            hdf_path: Path to the HEC-RAS geometry HDF file.

        Returns:
            A dictionary mapping variable names (e.g. ``"Curve Number"``) to
            DataFrames where rows are regions and columns are land cover / soil
            combinations, or ``None`` if the required paths do not exist.

        Example
        -------
        >>> regions = HdfInfiltration.get_infiltration_calibration_regions("model.g01.hdf")
        >>> print(regions.keys())
        dict_keys(['Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'])
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                variables_path = "Geometry/Infiltration/Variables"
                attrs_path = "Geometry/Infiltration/Attributes"

                if variables_path not in hdf_file or attrs_path not in hdf_file:
                    logger.warning(f"No infiltration variables or attributes found in {hdf_path}")
                    return None

                # Read region names
                attrs_data = hdf_file[attrs_path][()]
                region_names = list(np.vectorize(HdfUtils.convert_ras_string)(attrs_data['Name']))

                result = {}
                variables_group = hdf_file[variables_path]

                for ds_name in variables_group:
                    data = variables_group[ds_name][()]
                    df_dict = {}
                    for field_name in data.dtype.names:
                        values = data[field_name]
                        if values.dtype.kind == 'S':
                            values = [v.decode('utf-8').strip() for v in values]
                        df_dict[field_name] = values

                    df = pd.DataFrame(df_dict)
                    if len(df) == len(region_names):
                        df.index = region_names
                    result[ds_name] = df

                return result

        except Exception as e:
            logger.error(f"Error reading infiltration calibration regions from {hdf_path}: {str(e)}")
            return None

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_infiltration_region_polygons(hdf_path: Path) -> 'gpd.GeoDataFrame':
        """Retrieve infiltration region polygons from a HEC-RAS geometry HDF file.

        Reads polygon geometry from ``Geometry/Infiltration/Polygon Info``,
        ``Polygon Parts``, ``Polygon Points``, and region names from
        ``Geometry/Infiltration/Attributes``.

        Args:
            hdf_path: Path to the HEC-RAS geometry HDF file.

        Returns:
            A GeoDataFrame with columns ``region_id``, ``Name``, and
            ``geometry``. Returns an empty GeoDataFrame if the required
            datasets do not exist.

        Example
        -------
        >>> gdf = HdfInfiltration.get_infiltration_region_polygons("model.g01.hdf")
        >>> print(gdf[['Name', 'geometry']].head())
        """
        import geopandas as gpd
        from shapely.geometry import Polygon

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                infiltration_path = "Geometry/Infiltration"
                if infiltration_path not in hdf_file:
                    return gpd.GeoDataFrame()

                infil_data = hdf_file[infiltration_path]

                if ("Polygon Info" not in infil_data or
                    "Attributes" not in infil_data or
                    "Polygon Points" not in infil_data):
                    return gpd.GeoDataFrame()

                region_ids = range(infil_data["Attributes"][()].shape[0])
                names = np.vectorize(HdfUtils.convert_ras_string)(infil_data["Attributes"][()]["Name"])

                geoms = []
                for pnt_start, pnt_cnt, part_start, part_cnt in infil_data["Polygon Info"][()]:
                    points = infil_data["Polygon Points"][()][
                        pnt_start : pnt_start + pnt_cnt
                    ]

                    if part_cnt <= 1:
                        geoms.append(Polygon(points))
                        continue

                    if "Polygon Parts" not in infil_data:
                        logger.warning(
                            "Multi-part infiltration polygon but "
                            "'Polygon Parts' dataset missing"
                        )
                        geoms.append(Polygon(points))
                        continue

                    parts = infil_data["Polygon Parts"][()][
                        part_start : part_start + part_cnt
                    ]
                    rings = [
                        points[part_pnt_start : part_pnt_start + part_pnt_cnt]
                        for part_pnt_start, part_pnt_cnt in parts
                    ]

                    if len(rings) == 1:
                        geoms.append(Polygon(rings[0]))
                    else:
                        # HEC-RAS stores polygon parts as rings:
                        # first ring exterior, remaining rings interiors.
                        geoms.append(Polygon(rings[0], rings[1:]))

                return gpd.GeoDataFrame(
                    {"region_id": region_ids, "Name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )

        except Exception as e:
            logger.error(f"Error reading infiltration region polygons from {hdf_path}: {str(e)}")
            return gpd.GeoDataFrame()

    # set_infiltration_baseoverrides goes here, once finalized tested and fixed.

    # Since the infiltration base overrides are in the geometry file, the above functions work on the geometry files
    # The below functions work on the infiltration layer HDF files.  Changes only take effect if no base overrides are present. 
           
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
    @log_call
    @standardize_input(file_type='geom_hdf')
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



    # Need to reorganize these soil staatistics functions so they are more straightforward.  


    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_soils_raster_stats(
        geom_hdf_path: Path,
        soil_hdf_path: Path = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Calculate soil group statistics for each 2D flow area using the area's perimeter.
        
        Parameters
        ----------
        geom_hdf_path : Path
            Path to the HEC-RAS geometry HDF file containing the 2D flow areas
        soil_hdf_path : Path, optional
            Path to the soil HDF file. If None, uses soil_layer_path from rasmap_df
        ras_object : Any, optional
            Optional RAS object. If not provided, uses global ras instance
            
        Returns
        -------
        pd.DataFrame
            DataFrame with soil statistics for each 2D flow area, including:
            - mesh_name: Name of the 2D flow area
            - mukey: Soil mukey identifier
            - percentage: Percentage of 2D flow area covered by this soil type
            - area_sqm: Area in square meters
            - area_acres: Area in acres
            - area_sqmiles: Area in square miles
        
        Notes
        -----
        Requires the rasterstats package to be installed. Area outputs are
        derived from categorical pixel counts scaled by raster cell area.
        """
        try:
            from rasterstats import zonal_stats
            import shapely
            import geopandas as gpd
            import numpy as np
            import tempfile
            import os
        except ImportError as e:
            logger.error(f"Failed to import required package: {e}. Please run 'pip install rasterstats shapely geopandas'")
            raise e
        
        # Import here to avoid circular imports
        from .HdfMesh import HdfMesh
        
        # Get the soil HDF path
        if soil_hdf_path is None:
            if ras_object is None:
                from ..RasPrj import ras
                ras_object = ras
            
            # Try to get soil_layer_path from rasmap_df
            try:
                soil_hdf_path = Path(ras_object.rasmap_df.loc[0, 'soil_layer_path'][0])
                if not soil_hdf_path.exists():
                    logger.warning(f"Soil HDF path from rasmap_df does not exist: {soil_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving soil_layer_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get infiltration map - pass as hdf_path to ensure standardize_input works correctly
        try:
            raster_map = HdfInfiltration.get_infiltration_map(hdf_path=soil_hdf_path, ras_object=ras_object)
            if not raster_map:
                logger.error(f"No infiltration map found in {soil_hdf_path}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting infiltration map: {str(e)}")
            return pd.DataFrame()
        
        # Get 2D flow areas
        mesh_areas = HdfMesh.get_mesh_areas(geom_hdf_path)
        if mesh_areas.empty:
            logger.warning(f"No 2D flow areas found in {geom_hdf_path}")
            return pd.DataFrame()
        
        # Extract the raster data for analysis
        tif_path = soil_hdf_path.with_suffix('.tif')
        if not tif_path.exists():
            logger.error(f"No raster file found at {tif_path}")
            return pd.DataFrame()
            
        # Read the raster data and info
        import rasterio
        with rasterio.open(tif_path) as src:
            grid_data = src.read(1)
            transform = src.transform
            no_data = src.nodata if src.nodata is not None else -9999
            cell_area_sqm = HdfInfiltration._get_raster_cell_area_sqm(src)
            
            # List to store all results
            all_results = []
            
            # Calculate zonal statistics for each 2D flow area
            for _, mesh_row in mesh_areas.iterrows():
                mesh_name = mesh_row['mesh_name']
                mesh_geom = mesh_row['geometry']
                
                # Get zonal statistics directly using numpy array
                try:
                    stats = zonal_stats(
                        mesh_geom,
                        grid_data,
                        affine=transform,
                        categorical=True,
                        nodata=no_data
                    )[0]
                    
                    # Skip if no stats
                    if not stats:
                        logger.warning(f"No soil data found for 2D flow area: {mesh_name}")
                        continue

                    area_by_value, total_area_sqm = (
                        HdfInfiltration._categorical_counts_to_area_sqm(
                            stats,
                            no_data=no_data,
                            cell_area_sqm=cell_area_sqm,
                        )
                    )
                    if not area_by_value:
                        logger.warning(
                            f"No non-NoData soil pixels found for 2D flow area: "
                            f"{mesh_name}"
                        )
                        continue

                    # Process each mukey
                    for raster_val, area_sqm in area_by_value.items():
                             
                        try:
                            mukey = raster_map.get(int(raster_val), f"Unknown-{raster_val}")
                        except (ValueError, TypeError):
                            mukey = f"Unknown-{raster_val}"
                            
                        percentage = (area_sqm / total_area_sqm) * 100 if total_area_sqm > 0 else 0
                        
                        all_results.append({
                            'mesh_name': mesh_name,
                            'mukey': mukey,
                            'percentage': percentage,
                            'area_sqm': area_sqm,
                            'area_acres': area_sqm * HdfInfiltration.SQM_TO_ACRE,
                            'area_sqmiles': area_sqm * HdfInfiltration.SQM_TO_SQMILE
                        })
                except Exception as e:
                    logger.error(f"Error calculating statistics for mesh {mesh_name}: {str(e)}")
                    continue
        
        # Create DataFrame with results
        results_df = pd.DataFrame(all_results)
        
        # Sort by mesh_name and percentage (descending)
        if not results_df.empty:
            results_df = results_df.sort_values(['mesh_name', 'percentage'], ascending=[True, False])
        
        return results_df






    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_soil_raster_stats(
        geom_hdf_path: Path,
        landcover_hdf_path: Path = None,
        soil_hdf_path: Path = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Calculate combined land cover and soil infiltration statistics for each 2D flow area.
        
        This function processes both land cover and soil data to calculate statistics
        for each combination (Land Cover : Soil Type) within each 2D flow area.
        
        Parameters
        ----------
        geom_hdf_path : Path
            Path to the HEC-RAS geometry HDF file containing the 2D flow areas
        landcover_hdf_path : Path, optional
            Path to the land cover HDF file. If None, uses landcover_hdf_path from rasmap_df
        soil_hdf_path : Path, optional
            Path to the soil HDF file. If None, uses soil_layer_path from rasmap_df
        ras_object : Any, optional
            Optional RAS object. If not provided, uses global ras instance
            
        Returns
        -------
        pd.DataFrame
            DataFrame with combined statistics for each 2D flow area, including:
            - mesh_name: Name of the 2D flow area
            - combined_type: Combined land cover and soil type (e.g. "Mixed Forest : B")
            - percentage: Percentage of 2D flow area covered by this combination
            - area_sqm: Area in square meters
            - area_acres: Area in acres
            - area_sqmiles: Area in square miles
            - curve_number: Curve number for this combination
            - abstraction_ratio: Abstraction ratio for this combination
            - min_infiltration_rate: Minimum infiltration rate for this combination
        
        Notes
        -----
        Requires the rasterstats package to be installed.
        """
        try:
            from rasterstats import zonal_stats
            import shapely
            import geopandas as gpd
            import numpy as np
            import tempfile
            import os
            import rasterio
            from rasterio.merge import merge
        except ImportError as e:
            logger.error(f"Failed to import required package: {e}. Please run 'pip install rasterstats shapely geopandas rasterio'")
            raise e
        
        # Import here to avoid circular imports
        from .HdfMesh import HdfMesh
        
        # Get RAS object
        if ras_object is None:
            from ..RasPrj import ras
            ras_object = ras
        
        # Get the landcover HDF path
        if landcover_hdf_path is None:
            try:
                landcover_hdf_path = Path(ras_object.rasmap_df.loc[0, 'landcover_hdf_path'][0])
                if not landcover_hdf_path.exists():
                    logger.warning(f"Land cover HDF path from rasmap_df does not exist: {landcover_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving landcover_hdf_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get the soil HDF path
        if soil_hdf_path is None:
            try:
                soil_hdf_path = Path(ras_object.rasmap_df.loc[0, 'soil_layer_path'][0])
                if not soil_hdf_path.exists():
                    logger.warning(f"Soil HDF path from rasmap_df does not exist: {soil_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving soil_layer_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get land cover map (raster to ID mapping)
        try:
            with h5py.File(landcover_hdf_path, 'r') as hdf:
                if '//Raster Map' not in hdf:
                    logger.error(f"No Raster Map found in {landcover_hdf_path}")
                    return pd.DataFrame()
                
                landcover_map_data = hdf['//Raster Map'][()]
                landcover_map = {int(item[0]): item[1].decode('utf-8').strip() for item in landcover_map_data}
        except Exception as e:
            logger.error(f"Error reading land cover data from HDF: {str(e)}")
            return pd.DataFrame()
        
        # Get soil map (raster to ID mapping)
        try:
            soil_map = HdfInfiltration.get_infiltration_map(hdf_path=soil_hdf_path, ras_object=ras_object)
            if not soil_map:
                logger.error(f"No soil map found in {soil_hdf_path}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting soil map: {str(e)}")
            return pd.DataFrame()
        
        # Get infiltration parameters
        try:
            infiltration_params = HdfInfiltration.get_infiltration_layer_data(soil_hdf_path)
            if infiltration_params is None or infiltration_params.empty:
                logger.warning(f"No infiltration parameters found in {soil_hdf_path}")
                infiltration_params = pd.DataFrame(columns=['Name', 'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'])
        except Exception as e:
            logger.error(f"Error getting infiltration parameters: {str(e)}")
            infiltration_params = pd.DataFrame(columns=['Name', 'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'])
        
        # Get 2D flow areas
        mesh_areas = HdfMesh.get_mesh_areas(geom_hdf_path)
        if mesh_areas.empty:
            logger.warning(f"No 2D flow areas found in {geom_hdf_path}")
            return pd.DataFrame()
        
        # Check for the TIF files with same name as HDF
        landcover_tif_path = landcover_hdf_path.with_suffix('.tif')
        soil_tif_path = soil_hdf_path.with_suffix('.tif')
        
        if not landcover_tif_path.exists():
            logger.error(f"No land cover raster file found at {landcover_tif_path}")
            return pd.DataFrame()
        
        if not soil_tif_path.exists():
            logger.error(f"No soil raster file found at {soil_tif_path}")
            return pd.DataFrame()
        
        # List to store all results
        all_results = []
        
        # Read the raster data
        try:
            with rasterio.open(landcover_tif_path) as landcover_src, rasterio.open(soil_tif_path) as soil_src:
                landcover_nodata = landcover_src.nodata if landcover_src.nodata is not None else -9999
                soil_nodata = soil_src.nodata if soil_src.nodata is not None else -9999
                
                # Calculate zonal statistics for each 2D flow area
                for _, mesh_row in mesh_areas.iterrows():
                    mesh_name = mesh_row['mesh_name']
                    mesh_geom = mesh_row['geometry']
                    
                    # Get zonal statistics for land cover
                    try:
                        landcover_stats = zonal_stats(
                            mesh_geom,
                            landcover_tif_path,
                            categorical=True,
                            nodata=landcover_nodata
                        )[0]
                        
                        # Get zonal statistics for soil
                        soil_stats = zonal_stats(
                            mesh_geom,
                            soil_tif_path,
                            categorical=True,
                            nodata=soil_nodata
                        )[0]
                        
                        # Skip if no stats
                        if not landcover_stats or not soil_stats:
                            logger.warning(f"No land cover or soil data found for 2D flow area: {mesh_name}")
                            continue
                        
                        # Calculate total area
                        landcover_total = sum(landcover_stats.values())
                        soil_total = sum(soil_stats.values())
                        
                        # Create a cross-tabulation of land cover and soil types
                        # This is an approximation since we don't have the exact pixel-by-pixel overlap
                        mesh_area_sqm = mesh_row['geometry'].area
                        
                        # Calculate percentage of each land cover type
                        landcover_pct = {k: v/landcover_total for k, v in landcover_stats.items() if k is not None and k != landcover_nodata}
                        
                        # Calculate percentage of each soil type
                        soil_pct = {k: v/soil_total for k, v in soil_stats.items() if k is not None and k != soil_nodata}
                        
                        # Generate combinations
                        for lc_id, lc_pct in landcover_pct.items():
                            lc_name = landcover_map.get(int(lc_id), f"Unknown-{lc_id}")
                            
                            for soil_id, soil_pct in soil_pct.items():
                                try:
                                    soil_name = soil_map.get(int(soil_id), f"Unknown-{soil_id}")
                                except (ValueError, TypeError):
                                    soil_name = f"Unknown-{soil_id}"
                                
                                # Calculate combined percentage (approximate)
                                # This is a simplification; actual overlap would require pixel-by-pixel analysis
                                combined_pct = lc_pct * soil_pct * 100
                                combined_area_sqm = mesh_area_sqm * (combined_pct / 100)
                                
                                # Create combined name
                                combined_name = f"{lc_name} : {soil_name}"
                                
                                # Look up infiltration parameters
                                param_row = infiltration_params[infiltration_params['Name'] == combined_name]
                                if param_row.empty:
                                    # Try with NoData for soil type
                                    param_row = infiltration_params[infiltration_params['Name'] == f"{lc_name} : NoData"]
                                
                                if not param_row.empty:
                                    curve_number = param_row.iloc[0]['Curve Number']
                                    abstraction_ratio = param_row.iloc[0]['Abstraction Ratio']
                                    min_infiltration_rate = param_row.iloc[0]['Minimum Infiltration Rate']
                                else:
                                    curve_number = None
                                    abstraction_ratio = None
                                    min_infiltration_rate = None
                                
                                all_results.append({
                                    'mesh_name': mesh_name,
                                    'combined_type': combined_name,
                                    'percentage': combined_pct,
                                    'area_sqm': combined_area_sqm,
                                    'area_acres': combined_area_sqm * HdfInfiltration.SQM_TO_ACRE,
                                    'area_sqmiles': combined_area_sqm * HdfInfiltration.SQM_TO_SQMILE,
                                    'curve_number': curve_number,
                                    'abstraction_ratio': abstraction_ratio,
                                    'min_infiltration_rate': min_infiltration_rate
                                })
                    except Exception as e:
                        logger.error(f"Error calculating statistics for mesh {mesh_name}: {str(e)}")
                        continue
        except Exception as e:
            logger.error(f"Error opening raster files: {str(e)}")
            return pd.DataFrame()
        
        # Create DataFrame with results
        results_df = pd.DataFrame(all_results)
        
        # Sort by mesh_name, percentage (descending)
        if not results_df.empty:
            results_df = results_df.sort_values(['mesh_name', 'percentage'], ascending=[True, False])
        
        return results_df






    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_infiltration_stats(
        geom_hdf_path: Path,
        landcover_hdf_path: Path = None,
        soil_hdf_path: Path = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Calculate combined land cover and soil infiltration statistics for each 2D flow area.
        
        This function processes both land cover and soil data to calculate statistics
        for each combination (Land Cover : Soil Type) within each 2D flow area.
        
        Parameters
        ----------
        geom_hdf_path : Path
            Path to the HEC-RAS geometry HDF file containing the 2D flow areas
        landcover_hdf_path : Path, optional
            Path to the land cover HDF file. If None, uses landcover_hdf_path from rasmap_df
        soil_hdf_path : Path, optional
            Path to the soil HDF file. If None, uses soil_layer_path from rasmap_df
        ras_object : Any, optional
            Optional RAS object. If not provided, uses global ras instance
            
        Returns
        -------
        pd.DataFrame
            DataFrame with combined statistics for each 2D flow area, including:
            - mesh_name: Name of the 2D flow area
            - combined_type: Combined land cover and soil type (e.g. "Mixed Forest : B")
            - percentage: Percentage of 2D flow area covered by this combination
            - area_sqm: Area in square meters
            - area_acres: Area in acres
            - area_sqmiles: Area in square miles
            - curve_number: Curve number for this combination
            - abstraction_ratio: Abstraction ratio for this combination
            - min_infiltration_rate: Minimum infiltration rate for this combination
        
        Notes
        -----
        Requires the rasterstats package to be installed.
        """
        try:
            from rasterstats import zonal_stats
            import shapely
            import geopandas as gpd
            import numpy as np
            import tempfile
            import os
            import rasterio
            from rasterio.merge import merge
        except ImportError as e:
            logger.error(f"Failed to import required package: {e}. Please run 'pip install rasterstats shapely geopandas rasterio'")
            raise e
        
        # Import here to avoid circular imports
        from .HdfMesh import HdfMesh
        
        # Get RAS object
        if ras_object is None:
            from ..RasPrj import ras
            ras_object = ras
        
        # Get the landcover HDF path
        if landcover_hdf_path is None:
            try:
                landcover_hdf_path = Path(ras_object.rasmap_df.loc[0, 'landcover_hdf_path'][0])
                if not landcover_hdf_path.exists():
                    logger.warning(f"Land cover HDF path from rasmap_df does not exist: {landcover_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving landcover_hdf_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get the soil HDF path
        if soil_hdf_path is None:
            try:
                soil_hdf_path = Path(ras_object.rasmap_df.loc[0, 'soil_layer_path'][0])
                if not soil_hdf_path.exists():
                    logger.warning(f"Soil HDF path from rasmap_df does not exist: {soil_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving soil_layer_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get land cover map (raster to ID mapping)
        try:
            with h5py.File(landcover_hdf_path, 'r') as hdf:
                if '//Raster Map' not in hdf:
                    logger.error(f"No Raster Map found in {landcover_hdf_path}")
                    return pd.DataFrame()
                
                landcover_map_data = hdf['//Raster Map'][()]
                landcover_map = {int(item[0]): item[1].decode('utf-8').strip() for item in landcover_map_data}
        except Exception as e:
            logger.error(f"Error reading land cover data from HDF: {str(e)}")
            return pd.DataFrame()
        
        # Get soil map (raster to ID mapping)
        try:
            soil_map = HdfInfiltration.get_infiltration_map(hdf_path=soil_hdf_path, ras_object=ras_object)
            if not soil_map:
                logger.error(f"No soil map found in {soil_hdf_path}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting soil map: {str(e)}")
            return pd.DataFrame()
        
        # Get infiltration parameters
        try:
            infiltration_params = HdfInfiltration.get_infiltration_layer_data(soil_hdf_path)
            if infiltration_params is None or infiltration_params.empty:
                logger.warning(f"No infiltration parameters found in {soil_hdf_path}")
                infiltration_params = pd.DataFrame(columns=['Name', 'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'])
        except Exception as e:
            logger.error(f"Error getting infiltration parameters: {str(e)}")
            infiltration_params = pd.DataFrame(columns=['Name', 'Curve Number', 'Abstraction Ratio', 'Minimum Infiltration Rate'])
        
        # Get 2D flow areas
        mesh_areas = HdfMesh.get_mesh_areas(geom_hdf_path)
        if mesh_areas.empty:
            logger.warning(f"No 2D flow areas found in {geom_hdf_path}")
            return pd.DataFrame()
        
        # Check for the TIF files with same name as HDF
        landcover_tif_path = landcover_hdf_path.with_suffix('.tif')
        soil_tif_path = soil_hdf_path.with_suffix('.tif')
        
        if not landcover_tif_path.exists():
            logger.error(f"No land cover raster file found at {landcover_tif_path}")
            return pd.DataFrame()
        
        if not soil_tif_path.exists():
            logger.error(f"No soil raster file found at {soil_tif_path}")
            return pd.DataFrame()
        
        # List to store all results
        all_results = []
        
        # Read the raster data
        try:
            with rasterio.open(landcover_tif_path) as landcover_src, rasterio.open(soil_tif_path) as soil_src:
                landcover_nodata = landcover_src.nodata if landcover_src.nodata is not None else -9999
                soil_nodata = soil_src.nodata if soil_src.nodata is not None else -9999
                
                # Calculate zonal statistics for each 2D flow area
                for _, mesh_row in mesh_areas.iterrows():
                    mesh_name = mesh_row['mesh_name']
                    mesh_geom = mesh_row['geometry']
                    
                    # Get zonal statistics for land cover
                    try:
                        landcover_stats = zonal_stats(
                            mesh_geom,
                            landcover_tif_path,
                            categorical=True,
                            nodata=landcover_nodata
                        )[0]
                        
                        # Get zonal statistics for soil
                        soil_stats = zonal_stats(
                            mesh_geom,
                            soil_tif_path,
                            categorical=True,
                            nodata=soil_nodata
                        )[0]
                        
                        # Skip if no stats
                        if not landcover_stats or not soil_stats:
                            logger.warning(f"No land cover or soil data found for 2D flow area: {mesh_name}")
                            continue
                        
                        # Calculate total area
                        landcover_total = sum(landcover_stats.values())
                        soil_total = sum(soil_stats.values())
                        
                        # Create a cross-tabulation of land cover and soil types
                        # This is an approximation since we don't have the exact pixel-by-pixel overlap
                        mesh_area_sqm = mesh_row['geometry'].area
                        
                        # Calculate percentage of each land cover type
                        landcover_pct = {k: v/landcover_total for k, v in landcover_stats.items() if k is not None and k != landcover_nodata}
                        
                        # Calculate percentage of each soil type
                        soil_pct = {k: v/soil_total for k, v in soil_stats.items() if k is not None and k != soil_nodata}
                        
                        # Generate combinations
                        for lc_id, lc_pct in landcover_pct.items():
                            lc_name = landcover_map.get(int(lc_id), f"Unknown-{lc_id}")
                            
                            for soil_id, soil_pct in soil_pct.items():
                                try:
                                    soil_name = soil_map.get(int(soil_id), f"Unknown-{soil_id}")
                                except (ValueError, TypeError):
                                    soil_name = f"Unknown-{soil_id}"
                                
                                # Calculate combined percentage (approximate)
                                # This is a simplification; actual overlap would require pixel-by-pixel analysis
                                combined_pct = lc_pct * soil_pct * 100
                                combined_area_sqm = mesh_area_sqm * (combined_pct / 100)
                                
                                # Create combined name
                                combined_name = f"{lc_name} : {soil_name}"
                                
                                # Look up infiltration parameters
                                param_row = infiltration_params[infiltration_params['Name'] == combined_name]
                                if param_row.empty:
                                    # Try with NoData for soil type
                                    param_row = infiltration_params[infiltration_params['Name'] == f"{lc_name} : NoData"]
                                
                                if not param_row.empty:
                                    curve_number = param_row.iloc[0]['Curve Number']
                                    abstraction_ratio = param_row.iloc[0]['Abstraction Ratio']
                                    min_infiltration_rate = param_row.iloc[0]['Minimum Infiltration Rate']
                                else:
                                    curve_number = None
                                    abstraction_ratio = None
                                    min_infiltration_rate = None
                                
                                all_results.append({
                                    'mesh_name': mesh_name,
                                    'combined_type': combined_name,
                                    'percentage': combined_pct,
                                    'area_sqm': combined_area_sqm,
                                    'area_acres': combined_area_sqm * HdfInfiltration.SQM_TO_ACRE,
                                    'area_sqmiles': combined_area_sqm * HdfInfiltration.SQM_TO_SQMILE,
                                    'curve_number': curve_number,
                                    'abstraction_ratio': abstraction_ratio,
                                    'min_infiltration_rate': min_infiltration_rate
                                })
                    except Exception as e:
                        logger.error(f"Error calculating statistics for mesh {mesh_name}: {str(e)}")
                        continue
        except Exception as e:
            logger.error(f"Error opening raster files: {str(e)}")
            return pd.DataFrame()
        
        # Create DataFrame with results
        results_df = pd.DataFrame(all_results)
        
        # Sort by mesh_name, percentage (descending)
        if not results_df.empty:
            results_df = results_df.sort_values(['mesh_name', 'percentage'], ascending=[True, False])
        
        return results_df



















    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
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
                from ..RasPrj import ras
                ras_object = ras
            hdf_path = Path(ras_object.rasmap_df.iloc[0]['infiltration_hdf_path'][0])
            
        with h5py.File(hdf_path, 'r') as hdf:
            raster_map_data = hdf['Raster Map'][:]
            return {int(item[0]): item[1].decode('utf-8') for item in raster_map_data}

    @staticmethod
    @log_call
    def calculate_soil_statistics(
        zonal_stats: list,
        raster_map: dict,
        cell_area_sqm: Optional[float] = None,
        no_data: Any = None,
    ) -> pd.DataFrame:
        """Calculate soil statistics from zonal statistics
        
        Args:
            zonal_stats: List of zonal statistics
            raster_map: Dictionary mapping raster values to mukeys
            cell_area_sqm: Area represented by one raster cell in square
                meters. Must be provided by the caller.
            no_data: Optional NoData raster value to exclude.
             
        Returns:
            DataFrame with soil statistics including percentages and areas
        """
        if cell_area_sqm is None or cell_area_sqm <= 0:
            raise ValueError(
                "cell_area_sqm must be provided as a positive square-meter "
                "area per raster cell."
            )

        # Initialize areas dictionary
        mukey_areas = {mukey: 0.0 for mukey in raster_map.values()}
        
        # Calculate total area and mukey areas
        total_area_sqm = 0.0
        for stat in zonal_stats:
            area_by_value, stat_total_area_sqm = (
                HdfInfiltration._categorical_counts_to_area_sqm(
                    stat,
                    no_data=no_data,
                    cell_area_sqm=cell_area_sqm,
                )
            )
            total_area_sqm += stat_total_area_sqm

            for raster_val, area_sqm in area_by_value.items():
                mukey = raster_map.get(raster_val)
                if mukey:
                    mukey_areas[mukey] += area_sqm

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
    def get_infiltration_parameters(hdf_path: Path = None, mukey: str = None, ras_object: Any = None) -> Optional[Dict[str, float]]:
        """Get infiltration parameters for a specific mukey from HDF file

        Args:
            hdf_path: Optional path to the HDF file. If not provided, uses first infiltration_hdf_path from rasmap_df
            mukey: Mukey identifier
            ras_object: Optional RAS object. If not provided, uses global ras instance

        Returns:
            Optional[Dict[str, float]]: Dictionary of infiltration parameters, or None if mukey not found
        """
        if hdf_path is None:
            if ras_object is None:
                from ..RasPrj import ras
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
    @standardize_input(file_type='geom_hdf')
    def get_landcover_raster_stats(
        geom_hdf_path: Path,
        landcover_hdf_path: Path = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Calculate land cover statistics for each 2D flow area using the area's perimeter.
        
        Parameters
        ----------
        geom_hdf_path : Path
            Path to the HEC-RAS geometry HDF file containing the 2D flow areas
        landcover_hdf_path : Path, optional
            Path to the land cover HDF file. If None, uses landcover_hdf_path from rasmap_df
        ras_object : Any, optional
            Optional RAS object. If not provided, uses global ras instance
            
        Returns
        -------
        pd.DataFrame
            DataFrame with land cover statistics for each 2D flow area, including:
            - mesh_name: Name of the 2D flow area
            - land_cover: Land cover classification name
            - percentage: Percentage of 2D flow area covered by this land cover type
            - area_sqm: Area in square meters
            - area_acres: Area in acres
            - area_sqmiles: Area in square miles
            - mannings_n: Manning's n value for this land cover type
            - percent_impervious: Percent impervious for this land cover type
        
        Notes
        -----
        Requires the rasterstats package to be installed. Area outputs are
        derived from categorical pixel counts scaled by raster cell area.
        """
        try:
            from rasterstats import zonal_stats
            import shapely
            import geopandas as gpd
            import numpy as np
            import tempfile
            import os
            import rasterio
        except ImportError as e:
            logger.error(f"Failed to import required package: {e}. Please run 'pip install rasterstats shapely geopandas rasterio'")
            raise e
        
        # Import here to avoid circular imports
        from .HdfMesh import HdfMesh
        
        # Get the landcover HDF path
        if landcover_hdf_path is None:
            if ras_object is None:
                from ..RasPrj import ras
                ras_object = ras
            
            # Try to get landcover_hdf_path from rasmap_df
            try:
                landcover_hdf_path = Path(ras_object.rasmap_df.loc[0, 'landcover_hdf_path'][0])
                if not landcover_hdf_path.exists():
                    logger.warning(f"Land cover HDF path from rasmap_df does not exist: {landcover_hdf_path}")
                    return pd.DataFrame()
            except (KeyError, IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error retrieving landcover_hdf_path from rasmap_df: {str(e)}")
                return pd.DataFrame()
        
        # Get land cover map (raster to ID mapping)
        try:
            with h5py.File(landcover_hdf_path, 'r') as hdf:
                if '//Raster Map' not in hdf:
                    logger.error(f"No Raster Map found in {landcover_hdf_path}")
                    return pd.DataFrame()
                
                raster_map_data = hdf['//Raster Map'][()]
                raster_map = {int(item[0]): item[1].decode('utf-8').strip() for item in raster_map_data}
                
                # Get land cover variables (mannings_n and percent_impervious)
                variables = {}
                if '//Variables' in hdf:
                    var_data = hdf['//Variables'][()]
                    for row in var_data:
                        name = row[0].decode('utf-8').strip()
                        mannings_n = float(row[1])
                        percent_impervious = float(row[2])
                        variables[name] = {
                            'mannings_n': mannings_n,
                            'percent_impervious': percent_impervious
                        }
        except Exception as e:
            logger.error(f"Error reading land cover data from HDF: {str(e)}")
            return pd.DataFrame()
        
        # Get 2D flow areas
        mesh_areas = HdfMesh.get_mesh_areas(geom_hdf_path)
        if mesh_areas.empty:
            logger.warning(f"No 2D flow areas found in {geom_hdf_path}")
            return pd.DataFrame()
        
        # Check for the TIF file with same name as HDF
        tif_path = landcover_hdf_path.with_suffix('.tif')
        if not tif_path.exists():
            logger.error(f"No raster file found at {tif_path}")
            return pd.DataFrame()
        
        # List to store all results
        all_results = []
        
        # Read the raster data and info
        try:
            with rasterio.open(tif_path) as src:
                no_data = src.nodata if src.nodata is not None else -9999
                cell_area_sqm = HdfInfiltration._get_raster_cell_area_sqm(src)
                
                # Calculate zonal statistics for each 2D flow area
                for _, mesh_row in mesh_areas.iterrows():
                    mesh_name = mesh_row['mesh_name']
                    mesh_geom = mesh_row['geometry']
                    
                    # Get zonal statistics directly using rasterio grid
                    try:
                        stats = zonal_stats(
                            mesh_geom,
                            tif_path,
                            categorical=True,
                            nodata=no_data
                        )[0]
                        
                        # Skip if no stats
                        if not stats:
                            logger.warning(f"No land cover data found for 2D flow area: {mesh_name}")
                            continue

                        area_by_value, total_area_sqm = (
                            HdfInfiltration._categorical_counts_to_area_sqm(
                                stats,
                                no_data=no_data,
                                cell_area_sqm=cell_area_sqm,
                            )
                        )
                        if not area_by_value:
                            logger.warning(
                                f"No non-NoData land cover pixels found for 2D "
                                f"flow area: {mesh_name}"
                            )
                            continue

                        # Process each land cover type
                        for raster_val, area_sqm in area_by_value.items():
                                
                            try:
                                # Get land cover name from raster map
                                land_cover = raster_map.get(int(raster_val), f"Unknown-{raster_val}")
                                
                                # Get Manning's n and percent impervious
                                mannings_n = variables.get(land_cover, {}).get('mannings_n', None)
                                percent_impervious = variables.get(land_cover, {}).get('percent_impervious', None)
                                
                                percentage = (area_sqm / total_area_sqm) * 100 if total_area_sqm > 0 else 0
                                
                                all_results.append({
                                    'mesh_name': mesh_name,
                                    'land_cover': land_cover,
                                    'percentage': percentage,
                                    'area_sqm': area_sqm,
                                    'area_acres': area_sqm * HdfInfiltration.SQM_TO_ACRE,
                                    'area_sqmiles': area_sqm * HdfInfiltration.SQM_TO_SQMILE,
                                    'mannings_n': mannings_n,
                                    'percent_impervious': percent_impervious
                                })
                            except Exception as e:
                                logger.warning(f"Error processing raster value {raster_val}: {e}")
                                continue
                    except Exception as e:
                        logger.error(f"Error calculating statistics for mesh {mesh_name}: {str(e)}")
                        continue
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error opening raster file {tif_path}: {str(e)}")
            return pd.DataFrame()
        
        # Create DataFrame with results
        results_df = pd.DataFrame(all_results)
        
        # Sort by mesh_name, percentage (descending)
        if not results_df.empty:
            results_df = results_df.sort_values(['mesh_name', 'percentage'], ascending=[True, False])
        
        return results_df



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
