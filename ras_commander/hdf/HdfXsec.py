"""
Class: HdfXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

This source code has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

Available Functions:
- get_cross_sections(): Extract cross sections from HDF geometry file
- get_river_centerlines(): Extract river centerlines from HDF geometry file
- get_river_stationing(): Calculate river stationing along centerlines
- get_river_reaches(): Return the model 1D river reach lines
- get_river_edge_lines(): Return the model river edge lines
- get_river_bank_lines(): Extract river bank lines from HDF geometry file
- get_river_flow_paths(): Extract river flow paths from HDF geometry file
- get_xs_interpolation_surface(): Extract XS interpolation surface (TIN) from HDF
- generate_river_edge_lines(): Generate edge lines from XS cut-line end points
- set_river_edge_lines(): DEPRECATED - use RasGeometryCompute.generate_edge_lines()
- get_1d_footprint(): Build 1D model footprint polygon(s) from edge lines
- _interpolate_station(): Private helper method for station interpolation

All functions follow the get_ prefix convention for methods that return data.
Private helper methods use the underscore prefix convention.

Each function returns a GeoDataFrame containing geometries and associated attributes
specific to the requested feature type. All functions include proper error handling
and logging.
"""

from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon
from typing import List, Optional  # Import List to avoid NameError
from ..Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..LoggingConfig import get_logger
import logging



logger = get_logger(__name__)

class HdfXsec:
    """
    Handles cross-section and river geometry data extraction from HEC-RAS HDF files.

    This class provides static methods to extract and process:
    - Cross-section geometries and attributes
    - River centerlines and reaches
    - River edge and bank lines
    - Station-elevation profiles

    All methods are designed to return GeoDataFrames with standardized geometries 
    and attributes following the HEC-RAS data structure.

    Note:
        Requires HEC-RAS geometry HDF files with standard structure and naming conventions.
        All methods use proper error handling and logging.
    """
    CROSS_SECTION_GROUP = "Geometry/Cross Sections"
    CROSS_SECTION_REQUIRED_DATASETS = (
        f"{CROSS_SECTION_GROUP}/Polyline Info",
        f"{CROSS_SECTION_GROUP}/Polyline Parts",
        f"{CROSS_SECTION_GROUP}/Polyline Points",
        f"{CROSS_SECTION_GROUP}/Station Elevation Info",
        f"{CROSS_SECTION_GROUP}/Station Elevation Values",
        f"{CROSS_SECTION_GROUP}/Attributes",
        f"{CROSS_SECTION_GROUP}/Manning's n Info",
        f"{CROSS_SECTION_GROUP}/Manning's n Values",
    )
    CROSS_SECTION_CORE_GEOMETRY_DATASETS = (
        f"{CROSS_SECTION_GROUP}/Polyline Info",
        f"{CROSS_SECTION_GROUP}/Polyline Parts",
        f"{CROSS_SECTION_GROUP}/Polyline Points",
    )

    @staticmethod
    def _filename(hdf_path) -> str:
        return Path(hdf_path).name

    @staticmethod
    def _convert_hdf_value(value):
        if isinstance(value, (bytes, np.bytes_)):
            converted = HdfUtils.convert_ras_string(value)
            return converted.strip() if isinstance(converted, str) else converted
        if isinstance(value, np.str_):
            converted = HdfUtils.convert_ras_string(str(value))
            return converted.strip() if isinstance(converted, str) else converted
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _datetime_value_to_str(value):
        if pd.isna(value):
            return None
        try:
            return pd.Timestamp(value).isoformat()
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _structured_array_to_dict(attrs) -> dict:
        if not getattr(attrs.dtype, "names", None):
            return {}
        return {
            name: [HdfXsec._convert_hdf_value(value) for value in attrs[name]]
            for name in attrs.dtype.names
        }

    @staticmethod
    def _alternating_bank_sides(count: int) -> List[str]:
        return ["Left" if idx % 2 == 0 else "Right" for idx in range(count)]

    @staticmethod
    @log_call
    def get_cross_sections(hdf_path: str, datetime_to_str: bool = True, ras_object=None) -> gpd.GeoDataFrame:
        """
        Extracts cross-section geometries and attributes from a HEC-RAS geometry HDF file.

        Parameters
        ----------
        hdf_path : str
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, defaults to True
        ras_object : RasPrj, optional
            RAS project object for additional context, defaults to None

        Returns
        -------
        gpd.GeoDataFrame
            Cross-section data with columns:
            - geometry: LineString - Cross-section polyline geometry
            - station_elevation: ndarray - Station-elevation profile (Nx2 array: [station, elevation])
            - mannings_n: dict - Raw Manning's n data with keys 'Station' and 'Mann n' (lists)
            - n_lob: float - Left overbank Manning's n (computed from bank stations)
            - n_channel: float - Main channel Manning's n (computed from bank stations)
            - n_rob: float - Right overbank Manning's n (computed from bank stations)
            - ineffective_blocks: list - List of dicts with keys: 'Left Sta', 'Right Sta', 'Elevation', 'Permanent'
            - River: str - River name
            - Reach: str - Reach name
            - RS: str - River station identifier
            - Name: str - Cross-section name
            - Description: str - Cross-section description
            - Len Left: float - Left overbank flow path length
            - Len Channel: float - Main channel flow path length
            - Len Right: float - Right overbank flow path length
            - Left Bank: float - Left bank station location
            - Right Bank: float - Right bank station location
            - Friction Mode: str - Friction method used
            - Contr: float - Contraction coefficient
            - Expan: float - Expansion coefficient
            - Left Levee Sta: float - Left levee station (if exists)
            - Left Levee Elev: float - Left levee elevation (if exists)
            - Right Levee Sta: float - Right levee station (if exists)
            - Right Levee Elev: float - Right levee elevation (if exists)
            - HP Count: int - Hydraulic table point count
            - HP Start Elev: float - Hydraulic table starting elevation
            - HP Vert Incr: float - Hydraulic table vertical increment
            - HP LOB Slices: int - Left overbank slices count
            - HP Chan Slices: int - Main channel slices count
            - HP ROB Slices: int - Right overbank slices count
            - Ineff Block Mode: int - Ineffective area block mode
            - Obstr Block Mode: int - Obstruction block mode
            - Default Centerline: int - Default centerline flag
            - Last Edited: str - Last edit timestamp

        Notes
        -----
        The returned GeoDataFrame includes the coordinate system from the HDF file
        when available. All byte strings are converted to regular strings.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if HdfXsec.CROSS_SECTION_GROUP not in hdf:
                    logger.debug(
                        "No Geometry/Cross Sections group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return gpd.GeoDataFrame()

                missing_datasets = [
                    dataset
                    for dataset in HdfXsec.CROSS_SECTION_REQUIRED_DATASETS
                    if dataset not in hdf
                ]
                if missing_datasets:
                    if all(
                        dataset in missing_datasets
                        for dataset in HdfXsec.CROSS_SECTION_CORE_GEOMETRY_DATASETS
                    ):
                        logger.debug(
                            "No cross-section geometry datasets found in %s; missing %s; returning empty GeoDataFrame.",
                            HdfXsec._filename(hdf_path),
                            ", ".join(missing_datasets),
                        )
                    else:
                        logger.warning(
                            "Cross-section geometry in %s is missing required dataset(s): %s; returning empty GeoDataFrame.",
                            HdfXsec._filename(hdf_path),
                            ", ".join(missing_datasets),
                        )
                    return gpd.GeoDataFrame()

                # Extract required datasets
                poly_info = hdf['/Geometry/Cross Sections/Polyline Info'][:]
                poly_parts = hdf['/Geometry/Cross Sections/Polyline Parts'][:]
                poly_points = hdf['/Geometry/Cross Sections/Polyline Points'][:]
                
                station_info = hdf['/Geometry/Cross Sections/Station Elevation Info'][:]
                station_values = hdf['/Geometry/Cross Sections/Station Elevation Values'][:]
                
                # Get attributes for cross sections
                xs_attrs = hdf['/Geometry/Cross Sections/Attributes'][:]
                
                # Get Manning's n data
                mann_info = hdf["/Geometry/Cross Sections/Manning's n Info"][:]
                mann_values = hdf["/Geometry/Cross Sections/Manning's n Values"][:]
                
                # Get ineffective blocks data if they exist
                if '/Geometry/Cross Sections/Ineffective Blocks' in hdf:
                    ineff_blocks = hdf['/Geometry/Cross Sections/Ineffective Blocks'][:]
                    ineff_info = hdf['/Geometry/Cross Sections/Ineffective Info'][:]
                else:
                    ineff_blocks = None
                    ineff_info = None
                
                # Initialize lists to store data
                geometries = []
                station_elevations = []
                mannings_n = []
                ineffective_blocks = []
                n_lob_list = []
                n_channel_list = []
                n_rob_list = []
                
                # Process each cross section
                for i in range(len(poly_info)):
                    # Extract polyline info
                    point_start_idx = poly_info[i][0]
                    point_count = poly_info[i][1]
                    part_start_idx = poly_info[i][2]
                    part_count = poly_info[i][3]
                    
                    # Extract parts for current polyline
                    parts = poly_parts[part_start_idx:part_start_idx + part_count]
                    
                    # Collect all points for this cross section
                    xs_points = []
                    for part in parts:
                        part_point_start = point_start_idx + part[0]
                        part_point_count = part[1]
                        points = poly_points[part_point_start:part_point_start + part_point_count]
                        xs_points.extend(points)
                    
                    # Create LineString geometry
                    if len(xs_points) >= 2:
                        geometry = LineString(xs_points)
                        geometries.append(geometry)
                        
                        # Extract station-elevation data
                        start_idx = station_info[i][0]
                        count = station_info[i][1]
                        station_elev = station_values[start_idx:start_idx + count]
                        station_elevations.append(station_elev)
                        
                        # Extract Manning's n data
                        mann_start_idx = mann_info[i][0]
                        mann_count = mann_info[i][1]
                        mann_n_section = mann_values[mann_start_idx:mann_start_idx + mann_count]
                        mann_n_dict = {
                            'Station': mann_n_section[:, 0].tolist(),
                            'Mann n': mann_n_section[:, 1].tolist()
                        }
                        mannings_n.append(mann_n_dict)

                        # Compute LOB/Channel/ROB Manning's n values
                        # Get bank stations for this XS
                        left_bank = float(xs_attrs[i]['Left Bank'])
                        right_bank = float(xs_attrs[i]['Right Bank'])

                        # Map n values to LOB/Channel/ROB based on stations
                        if mann_count == 0:
                            n_lob_val = n_channel_val = n_rob_val = np.nan
                        elif mann_count == 3:
                            # Simple LOB/Channel/ROB model (most common)
                            n_lob_val = float(mann_n_section[0, 1])
                            n_channel_val = float(mann_n_section[1, 1])
                            n_rob_val = float(mann_n_section[2, 1])
                        elif mann_count == 2:
                            # Two regions
                            sta1, n1 = float(mann_n_section[0, 0]), float(mann_n_section[0, 1])
                            sta2, n2 = float(mann_n_section[1, 0]), float(mann_n_section[1, 1])
                            if sta1 < left_bank and sta2 >= left_bank:
                                n_lob_val, n_channel_val, n_rob_val = n1, n2, n2
                            else:
                                n_lob_val, n_channel_val, n_rob_val = n1, n1, n2
                        elif mann_count >= 4:
                            # Variable n - map by station regions
                            n_lob_val = n_channel_val = n_rob_val = None
                            for j in range(mann_count):
                                sta, n_val = float(mann_n_section[j, 0]), float(mann_n_section[j, 1])
                                if sta < left_bank:
                                    n_lob_val = n_val
                                elif sta < right_bank:
                                    if n_channel_val is None:
                                        n_channel_val = n_val
                                else:
                                    if n_rob_val is None:
                                        n_rob_val = n_val
                            # Fill missing
                            if n_lob_val is None:
                                n_lob_val = float(mann_n_section[0, 1])
                            if n_channel_val is None:
                                n_channel_val = n_lob_val
                            if n_rob_val is None:
                                n_rob_val = n_channel_val
                        else:
                            # Single value
                            n_lob_val = n_channel_val = n_rob_val = float(mann_n_section[0, 1])

                        # Append computed Manning's n values
                        n_lob_list.append(n_lob_val)
                        n_channel_list.append(n_channel_val)
                        n_rob_list.append(n_rob_val)

                        # Extract ineffective blocks data
                        if ineff_info is not None and ineff_blocks is not None:
                            ineff_start_idx = ineff_info[i][0]
                            ineff_count = ineff_info[i][1]
                            if ineff_count > 0:
                                blocks = ineff_blocks[ineff_start_idx:ineff_start_idx + ineff_count]
                                blocks_list = []
                                for block in blocks:
                                    block_dict = {
                                        'Left Sta': float(block['Left Sta']),
                                        'Right Sta': float(block['Right Sta']), 
                                        'Elevation': float(block['Elevation']),
                                        'Permanent': bool(block['Permanent'])
                                    }
                                    blocks_list.append(block_dict)
                                ineffective_blocks.append(blocks_list)
                            else:
                                ineffective_blocks.append([])
                        else:
                            ineffective_blocks.append([])
                
                # Create base dictionary with required fields
                data = {
                    'geometry': geometries,
                    'station_elevation': station_elevations,
                    'mannings_n': mannings_n,
                    'n_lob': n_lob_list,
                    'n_channel': n_channel_list,
                    'n_rob': n_rob_list,
                    'ineffective_blocks': ineffective_blocks,
                }
                
                # Define field mappings with default values
                field_mappings = {
                    'River': ('River', ''),
                    'Reach': ('Reach', ''),
                    'RS': ('RS', ''),
                    'Name': ('Name', ''),
                    'Description': ('Description', ''),
                    'Len Left': ('Len Left', 0.0),
                    'Len Channel': ('Len Channel', 0.0),
                    'Len Right': ('Len Right', 0.0),
                    'Left Bank': ('Left Bank', 0.0),
                    'Right Bank': ('Right Bank', 0.0),
                    'Friction Mode': ('Friction Mode', ''),
                    'Contr': ('Contr', 0.0),
                    'Expan': ('Expan', 0.0),
                    'Left Levee Sta': ('Left Levee Sta', None),
                    'Left Levee Elev': ('Left Levee Elev', None),
                    'Right Levee Sta': ('Right Levee Sta', None),
                    'Right Levee Elev': ('Right Levee Elev', None),
                    'HP Count': ('HP Count', 0),
                    'HP Start Elev': ('HP Start Elev', 0.0),
                    'HP Vert Incr': ('HP Vert Incr', 0.0),
                    'HP LOB Slices': ('HP LOB Slices', 0),
                    'HP Chan Slices': ('HP Chan Slices', 0),
                    'HP ROB Slices': ('HP ROB Slices', 0),
                    'Ineff Block Mode': ('Ineff Block Mode', 0),
                    'Obstr Block Mode': ('Obstr Block Mode', 0),
                    'Default Centerline': ('Default Centerline', 0),
                    'Last Edited': ('Last Edited', '')
                }
                
                # Add fields that exist in xs_attrs
                for field_name, (attr_name, default_value) in field_mappings.items():
                    if attr_name in xs_attrs.dtype.names:
                        if xs_attrs[attr_name].dtype.kind == 'S':
                            # Handle string fields
                            data[field_name] = [x[attr_name].decode('utf-8').strip() 
                                              for x in xs_attrs]
                        else:
                            # Handle numeric fields
                            data[field_name] = xs_attrs[attr_name]
                    else:
                        # Use default value if field doesn't exist
                        data[field_name] = [default_value] * len(geometries)
                        logger.debug(f"Field {attr_name} not found in attributes, using default value")
                
                if geometries:
                    gdf = gpd.GeoDataFrame(data)
                    
                    # Set CRS if available
                    if 'Projection' in hdf['/Geometry'].attrs:
                        proj = hdf['/Geometry'].attrs['Projection']
                        if isinstance(proj, bytes):
                            proj = proj.decode('utf-8')
                        gdf = gdf.set_crs(proj, allow_override=True)
                    
                    return gdf
                
                return gpd.GeoDataFrame()
                
        except Exception as e:
            logger.error(f"Error processing cross-section data from {hdf_path}: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_centerlines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extracts river centerline geometries and attributes from HDF geometry file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, defaults to False

        Returns
        -------
        GeoDataFrame
            River centerline data with columns:
            - geometry: LineString - River centerline geometry
            - River Name: str - Name of the river
            - Reach Name: str - Name of the reach
            - US Type: str - Upstream connection type (e.g., 'Junction', 'External')
            - US Name: str - Upstream connection name
            - DS Type: str - Downstream connection type (e.g., 'Junction', 'External')
            - DS Name: str - Downstream connection name
            - length: float - Centerline length in project coordinate units (computed)

            Note: Additional HDF attributes may be included depending on HEC-RAS version.
            Use datetime_to_str=True to convert any datetime columns to ISO format strings.

        Notes
        -----
        Returns an empty GeoDataFrame if no centerlines are found.
        All string attributes are stripped of whitespace.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Centerlines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                centerline_data = hdf_file["Geometry/River Centerlines"]
                
                # Get attributes directly from HDF dataset
                attrs = centerline_data["Attributes"][()]
                
                # Create initial dictionary for DataFrame
                centerline_dict = HdfXsec._structured_array_to_dict(attrs)

                # Get polylines using utility function
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path, 
                    "Geometry/River Centerlines",
                    info_name="Polyline Info",
                    parts_name="Polyline Parts",
                    points_name="Polyline Points"
                )

                # Create GeoDataFrame
                centerline_gdf = GeoDataFrame(
                    centerline_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Clean up string columns
                str_columns = ['River Name', 'Reach Name', 'US Type', 
                            'US Name', 'DS Type', 'DS Name']
                for col in str_columns:
                    if col in centerline_gdf.columns:
                        centerline_gdf[col] = centerline_gdf[col].str.strip()

                # Add length calculation in project units
                if not centerline_gdf.empty:
                    centerline_gdf['length'] = centerline_gdf.geometry.length
                    
                    # Convert datetime columns if requested
                    if datetime_to_str:
                        datetime_cols = centerline_gdf.select_dtypes(
                            include=['datetime64']).columns
                        for col in datetime_cols:
                            centerline_gdf[col] = centerline_gdf[col].dt.strftime(
                                '%Y-%m-%d %H:%M:%S')

                logger.debug(f"Extracted {len(centerline_gdf)} river centerlines")
                return centerline_gdf

        except Exception as e:
            logger.error(f"Error reading river centerlines from {hdf_path}: {str(e)}")
            return GeoDataFrame()



    @staticmethod
    @log_call
    def get_river_stationing(centerlines_gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Calculates stationing along river centerlines with interpolated points.

        Parameters
        ----------
        centerlines_gdf : GeoDataFrame
            River centerline geometries from get_river_centerlines()

        Returns
        -------
        GeoDataFrame
            Original centerlines with additional columns:
            - station_start: float - Starting station value (0.0 or total_length, depends on US/DS connections)
            - station_end: float - Ending station value (total_length or 0.0, depends on US/DS connections)
            - stations: ndarray - Array of 100 evenly-spaced station values along centerline
            - points: list - List of shapely Point geometries at each station location

            All original columns from centerlines_gdf are preserved (geometry, River Name, Reach Name, etc.).

        Notes
        -----
        Station direction (increasing/decreasing) is determined by
        upstream/downstream junction connections. Stations are calculated
        at 100 evenly spaced points along each centerline.
        """
        if centerlines_gdf.empty:
            logger.debug("Empty centerlines GeoDataFrame provided; returning unchanged.")
            return centerlines_gdf

        try:
            # Create copy to avoid modifying original
            result_gdf = centerlines_gdf.copy()
            
            # Initialize new columns
            result_gdf['station_start'] = 0.0
            result_gdf['station_end'] = 0.0
            result_gdf['stations'] = None
            result_gdf['points'] = None
            
            # Process each centerline
            for idx, row in result_gdf.iterrows():
                # Get line geometry
                line = row.geometry
                
                # Calculate length
                total_length = line.length
                
                # Generate points along the line
                distances = np.linspace(0, total_length, num=100)  # Adjust num for desired density
                points = [line.interpolate(distance) for distance in distances]
                
                # Store results
                result_gdf.at[idx, 'station_start'] = 0.0
                result_gdf.at[idx, 'station_end'] = total_length
                result_gdf.at[idx, 'stations'] = distances
                result_gdf.at[idx, 'points'] = points
                
                # Add stationing direction based on upstream/downstream info
                if row['US Type'] == 'Junction' and row['DS Type'] != 'Junction':
                    # Reverse stationing if upstream is junction
                    result_gdf.at[idx, 'station_start'] = total_length
                    result_gdf.at[idx, 'station_end'] = 0.0
                    result_gdf.at[idx, 'stations'] = total_length - distances
            
            return result_gdf

        except Exception as e:
            logger.error(f"Error calculating river stationing: {str(e)}")
            return centerlines_gdf

    @staticmethod
    def _interpolate_station(line, distance):
        """
        Interpolates a point along a line at a given distance.

        Parameters
        ----------
        line : LineString
            Shapely LineString geometry
        distance : float
            Distance along the line to interpolate

        Returns
        -------
        tuple
            (x, y) coordinates of interpolated point
        """
        if distance <= 0:
            return line.coords[0]
        elif distance >= line.length:
            return line.coords[-1]
        return line.interpolate(distance).coords[0]



    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_reaches(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model 1D river reach lines.

        This method extracts river reach data from the HEC-RAS geometry HDF file,
        including attributes and geometry information.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            River reach data with columns:
            - geometry: LineString - River reach line geometry
            - river_id: int - Unique identifier for each reach (0-indexed)
            - River Name: str - Name of the river
            - Reach Name: str - Name of the reach
            - US Type: str - Upstream connection type
            - US Name: str - Upstream connection name
            - DS Type: str - Downstream connection type
            - DS Name: str - Downstream connection name
            - Last Edited: datetime or str - Last edit timestamp (str if datetime_to_str=True)

            Note: Additional HDF attributes may be included depending on HEC-RAS version.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Centerlines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                river_data = hdf_file["Geometry/River Centerlines"]
                river_attrs = river_data["Attributes"][()]
                river_dict = {"river_id": list(range(river_attrs.shape[0]))}
                river_dict.update(HdfXsec._structured_array_to_dict(river_attrs))
                
                # Get polylines for river reaches
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path, "Geometry/River Centerlines"
                )

                river_gdf = GeoDataFrame(
                    river_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path),
                )
                if datetime_to_str and "Last Edited" in river_gdf.columns:
                    river_gdf["Last Edited"] = river_gdf["Last Edited"].apply(
                        HdfXsec._datetime_value_to_str
                    )
                return river_gdf
        except Exception as e:
            logger.error(f"Error reading river reaches from {hdf_path}: {str(e)}")
            return GeoDataFrame()


    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_edge_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model river edge lines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            River edge line data with columns:
            - geometry: LineString - River edge line geometry
            - edge_id: int - Unique identifier for each edge line (0-indexed)
            - bank_side: str - Bank side indicator ('Left' or 'Right')
            - length: float - Length of edge line in project coordinate units (computed)
            - Last Edited: datetime or str - Last edit timestamp (str if datetime_to_str=True, if available)

            Note: Each row represents one river bank (left or right). Additional HDF attributes
            may be included depending on HEC-RAS version.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Edge Lines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Edge Lines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                edge_data = hdf_file["Geometry/River Edge Lines"]
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path,
                    "Geometry/River Edge Lines",
                    info_name="Polyline Info",
                    parts_name="Polyline Parts",
                    points_name="Polyline Points"
                )

                # Genuine HEC-RAS edge lines carry no "Attributes" dataset, so the
                # geometry count is the source of truth for edge_id/bank_side (bank
                # side alternates Left/Right per reach: RASEdgeLines' IsLeft = i % 2 == 0).
                if "Attributes" in edge_data:
                    attrs = edge_data["Attributes"][()]

                    # Create dictionary of attributes
                    edge_dict = {"edge_id": list(range(attrs.shape[0]))}
                    edge_dict.update(HdfXsec._structured_array_to_dict(attrs))
                else:
                    edge_dict = {"edge_id": list(range(len(geoms)))}
                edge_dict["bank_side"] = HdfXsec._alternating_bank_sides(len(geoms))

                # Create GeoDataFrame
                edge_gdf = GeoDataFrame(
                    edge_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Convert datetime objects to strings if requested
                if datetime_to_str and 'Last Edited' in edge_gdf.columns:
                    edge_gdf["Last Edited"] = edge_gdf["Last Edited"].apply(
                        HdfXsec._datetime_value_to_str
                    )

                # Add length calculation in project units
                if not edge_gdf.empty:
                    edge_gdf['length'] = edge_gdf.geometry.length

                return edge_gdf

        except Exception as e:
            logger.error(f"Error reading river edge lines from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_bank_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extract river bank lines from HDF geometry file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, by default False

        Returns
        -------
        GeoDataFrame
            River bank line data with columns:
            - geometry: LineString - River bank line geometry
            - bank_id: int - Unique identifier for each bank line (0-indexed)
            - bank_side: str - Bank side indicator ('Left' or 'Right')
            - length: float - Length of the bank line in project coordinate units (computed)

            Note: Bank lines are assumed to be in pairs (left/right). If odd number of geometries
            exist, the bank_side pattern may not align perfectly.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Bank Lines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Bank Lines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                # Get polyline geometries using existing helper method
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path, 
                    "Geometry/River Bank Lines",
                    info_name="Polyline Info",
                    parts_name="Polyline Parts",
                    points_name="Polyline Points"
                )

                # Create basic attributes
                bank_dict = {
                    "bank_id": list(range(len(geoms))),
                    "bank_side": HdfXsec._alternating_bank_sides(len(geoms)),
                }

                # Create GeoDataFrame
                bank_gdf = GeoDataFrame(
                    bank_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Add length calculation in project units
                if not bank_gdf.empty:
                    bank_gdf['length'] = bank_gdf.geometry.length

                return bank_gdf

        except Exception as e:
            logger.error(f"Error reading river bank lines from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_flow_paths(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model river flow paths (``Geometry/River Flow Paths``).

        RASMapper's *Create Flow Paths from XS Layout* artifact: the flow-path
        polylines (left overbank, channel, right overbank) that drive 1D reach
        lengths. Pure h5py read; the group must already exist. Generate it with
        ``RasGeometryCompute.generate_flow_paths()`` when absent.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            Accepted for signature parity with the other river-layer readers;
            flow paths carry no timestamp attribute, so this is a no-op.

        Returns
        -------
        GeoDataFrame
            Columns ``flow_path_id`` (int), ``geometry`` (LineString), and
            ``length`` (project units). Empty GeoDataFrame when no flow paths
            are stored.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Flow Paths" not in hdf_file:
                    logger.warning("No river flow paths found in geometry file")
                    return GeoDataFrame()

            geoms = HdfBase.get_polylines_from_parts(
                hdf_path,
                "Geometry/River Flow Paths",
                info_name="Flow Path Lines Info",
                parts_name="Flow Path Lines Parts",
                points_name="Flow Path Lines Points",
            )
            if not geoms:
                return GeoDataFrame()

            flow_gdf = GeoDataFrame(
                {"flow_path_id": list(range(len(geoms)))},
                geometry=geoms,
                crs=HdfBase.get_projection(hdf_path),
            )
            flow_gdf['length'] = flow_gdf.geometry.length
            return flow_gdf

        except Exception as e:
            logger.error(f"Error reading river flow paths: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_xs_interpolation_surface(hdf_path: Path) -> GeoDataFrame:
        """
        Return the cross-section interpolation surface.

        RASMapper's *Compute XS Interpolation Surface* artifact
        (``Geometry/Cross Section Interpolation Surfaces``): the triangulated
        surface HEC-RAS builds between each pair of adjacent cross sections. The
        stored TIN is returned as one dissolved polygon per XS-to-XS segment,
        tagged with the upstream/downstream cross-section ids and the stored
        area. Pure h5py read; the group must already exist. Generate it with
        ``RasGeometryCompute.generate_interpolation_surface()`` when absent.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            One row per interpolation segment with columns ``surface_id`` (int),
            ``us_xs_id`` / ``ds_xs_id`` (int, when ``XSIDs`` present), ``area``
            (float, when ``Areas`` present), and ``geometry`` ((Multi)Polygon of
            the segment's TIN triangles). Empty GeoDataFrame when no surface is
            stored.
        """
        base = "Geometry/Cross Section Interpolation Surfaces"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if base not in hdf_file:
                    logger.warning("No XS interpolation surface found in geometry file")
                    return GeoDataFrame()
                grp = hdf_file[base]
                if "TIN Info" not in grp or "TIN Points" not in grp or "TIN Triangles" not in grp:
                    logger.warning("XS interpolation surface group missing TIN datasets")
                    return GeoDataFrame()
                tin_info = grp["TIN Info"][()]
                tin_points = grp["TIN Points"][()]
                tin_tris = grp["TIN Triangles"][()]
                xsids = grp["XSIDs"][()] if "XSIDs" in grp else None
                areas = grp["Areas"][()] if "Areas" in grp else None

            from shapely.ops import unary_union

            n_pts = len(tin_points)
            n_tris = len(tin_tris)
            rows = []
            for i, (pnt_start, pnt_cnt, tri_start, tri_cnt) in enumerate(tin_info):
                try:
                    # Bounds-check the segment slices before use; a single corrupt
                    # segment must not drop the whole surface.
                    if (pnt_start < 0 or tri_start < 0
                            or pnt_start + pnt_cnt > n_pts
                            or tri_start + tri_cnt > n_tris):
                        logger.warning(
                            f"Interpolation surface segment {i}: slice out of bounds; skipping")
                        continue
                    # Triangle vertex indices are LOCAL to this segment's point slice.
                    seg_pts = tin_points[pnt_start:pnt_start + pnt_cnt][:, :2]
                    seg_tris = tin_tris[tri_start:tri_start + tri_cnt]
                    tri_polys = []
                    for a, b, c in seg_tris:
                        if not (0 <= a < pnt_cnt and 0 <= b < pnt_cnt and 0 <= c < pnt_cnt):
                            continue
                        poly = Polygon([seg_pts[a], seg_pts[b], seg_pts[c]])
                        if poly.is_valid and poly.area > 0:
                            tri_polys.append(poly)
                    if not tri_polys:
                        continue
                    geom = unary_union(tri_polys)
                    if geom is None or geom.is_empty:
                        continue
                    row = {"surface_id": i, "geometry": geom}
                    if xsids is not None and i < len(xsids):
                        row["us_xs_id"] = int(xsids[i, 0])
                        row["ds_xs_id"] = int(xsids[i, 1])
                    if areas is not None and i < len(areas):
                        row["area"] = float(areas[i])
                    rows.append(row)
                except Exception as seg_exc:
                    logger.warning(
                        f"Interpolation surface segment {i} unreadable; skipping: {seg_exc}")
                    continue

            if not rows:
                return GeoDataFrame()
            return GeoDataFrame(rows, geometry="geometry", crs=HdfBase.get_projection(hdf_path))

        except Exception as e:
            logger.error(f"Error reading XS interpolation surface: {str(e)}")
            return GeoDataFrame()

    # ------------------------------------------------------------------
    # Edge-line generation and 1D footprint polygonization
    # ------------------------------------------------------------------

    @staticmethod
    def _as_single_linestring(geometry):
        """Return a simple 2D LineString from single- or multi-part line geometry."""
        from shapely.ops import linemerge

        if geometry is None or getattr(geometry, "is_empty", True):
            return None
        if isinstance(geometry, LineString):
            return geometry if len(geometry.coords) >= 2 else None
        if isinstance(geometry, MultiLineString):
            merged = linemerge(geometry)
            if isinstance(merged, LineString):
                return merged if len(merged.coords) >= 2 else None
            if isinstance(merged, MultiLineString) and len(merged.geoms) > 0:
                longest = max(merged.geoms, key=lambda g: g.length)
                return longest if len(longest.coords) >= 2 else None
        if hasattr(geometry, "geoms"):
            parts = [
                p for p in geometry.geoms
                if isinstance(p, LineString) and len(p.coords) >= 2
            ]
            if parts:
                return max(parts, key=lambda g: g.length)
        return None

    @staticmethod
    def _cutline_interior(start_pt, end_pt, cut_lines, tolerance):
        """Interior vertices of the cut line spanning start_pt -> end_pt.

        Searches ``cut_lines`` for a cut line whose two end points match
        ``start_pt`` and ``end_pt`` (in either order) within ``tolerance``, and
        returns that cut line's interior vertices oriented start -> end. Returns
        None when no cut line matches, in which case the caller falls back to a
        straight closing chord.
        """
        from math import hypot

        def close(a, b):
            return hypot(a[0] - b[0], a[1] - b[1]) <= tolerance

        for line in cut_lines:
            cut = HdfXsec._as_single_linestring(line)
            if cut is None:
                continue
            coords = [tuple(c[:2]) for c in cut.coords]
            if len(coords) < 3:
                # Two-point cut line: the straight chord already IS the cut line.
                continue
            first, last = coords[0], coords[-1]
            if close(first, start_pt) and close(last, end_pt):
                return coords[1:-1]
            if close(last, start_pt) and close(first, end_pt):
                return list(reversed(coords[1:-1]))
        return None

    @staticmethod
    def _polygon_from_edge_pair(left_line, right_line, cut_lines=None,
                                snap_tolerance=None):
        """Close a left/right edge-line pair into a polygon.

        The ring runs along the left edge, across the downstream cross section,
        back up the reversed right edge, and across the upstream cross section.
        When ``cut_lines`` (the end cross-section cut lines for the reach) are
        supplied, each end cap follows the real cut-line geometry, including its
        interior vertices. Without them - or when an edge-line end point does not
        land on a cut-line limit (possible for HEC-RAS stored edge lines) - the
        end cap falls back to a straight chord between the edge-line end points.
        """
        left = HdfXsec._as_single_linestring(left_line)
        right = HdfXsec._as_single_linestring(right_line)
        if left is None or right is None:
            return None

        left_coords = [tuple(c[:2]) for c in left.coords]
        right_coords = [tuple(c[:2]) for c in right.coords]
        if len(left_coords) + len(right_coords) < 4:
            return None

        cut_lines = list(cut_lines) if cut_lines else []
        if cut_lines and snap_tolerance is None:
            lengths = [
                cut.length for cut in
                (HdfXsec._as_single_linestring(c) for c in cut_lines)
                if cut is not None and cut.length > 0
            ]
            # 1% of a typical cut-line width: tight enough to reject a mismatched
            # cut line, loose enough for stored edge lines with rounded coords.
            snap_tolerance = 0.01 * (sum(lengths) / len(lengths)) if lengths else 0.0

        # Downstream cap: left edge end -> right edge end.
        far_cap = HdfXsec._cutline_interior(
            left_coords[-1], right_coords[-1], cut_lines, snap_tolerance
        ) if cut_lines else None
        # Upstream cap: right edge start -> left edge start (closes the ring).
        near_cap = HdfXsec._cutline_interior(
            right_coords[0], left_coords[0], cut_lines, snap_tolerance
        ) if cut_lines else None

        coords = (
            left_coords
            + (far_cap or [])
            + list(reversed(right_coords))
            + (near_cap or [])
        )
        if len(coords) < 4:
            return None
        polygon = Polygon(coords)
        if not polygon.is_valid:
            # A bent cut line spliced into the ring can self-intersect; repair.
            polygon = polygon.buffer(0)
        if polygon is None or polygon.is_empty:
            return None
        return polygon

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def generate_river_edge_lines(hdf_path: Path, ras_object=None) -> GeoDataFrame:
        """
        Generate river edge lines from cross-section cut-line end points.

        Pure-Python equivalent of RASMapper's "Create Edge Lines at XS Limits".
        For each (River, Reach), the left end points of consecutive cross-section
        cut lines are connected into a left edge line and the right end points
        into a right edge line. HEC-RAS stores cut lines left(start) -> right(end)
        looking downstream, so ``coords[0]`` is the left limit and ``coords[-1]``
        is the right limit of each cross section.

        Use this when a geometry has no stored ``Geometry/River Edge Lines``
        (e.g. the XS interpolation surface has not been computed) or to derive a
        1D footprint boundary directly from cross sections. This is a simplified
        XS-endpoint construction; for HEC-RAS's own bank-line-anchored
        offset-curve edge lines (written to the geometry HDF with the group-level
        ``Source Data Hash``), use ``RasGeometryCompute.generate_edge_lines()``.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        ras_object : RasPrj, optional
            RAS project object for path resolution context.

        Returns
        -------
        GeoDataFrame
            Generated edge lines with columns matching ``get_river_edge_lines``:
            - edge_id : int
            - River : str
            - Reach : str
            - bank_side : str ('Left' or 'Right')
            - geometry : LineString
            - length : float (project units)
            Empty GeoDataFrame when no cross sections are available.
        """
        xs_gdf = HdfXsec.get_cross_sections(hdf_path, ras_object=ras_object)
        if xs_gdf is None or xs_gdf.empty:
            logger.warning("No cross sections found; cannot generate river edge lines")
            return GeoDataFrame()

        if not {"River", "Reach"}.issubset(xs_gdf.columns):
            logger.warning("Cross sections missing River/Reach columns; cannot group edge lines")
            return GeoDataFrame()

        rows = []
        edge_id = 0
        # Preserve reach order (HDF file order) while grouping.
        for (river, reach), group in xs_gdf.groupby(["River", "Reach"], sort=False):
            left_pts: List = []
            right_pts: List = []
            for geom in group.geometry:
                line = HdfXsec._as_single_linestring(geom)
                if line is None:
                    continue
                coords = list(line.coords)
                left_pts.append(tuple(coords[0][:2]))
                right_pts.append(tuple(coords[-1][:2]))

            for side, pts in (("Left", left_pts), ("Right", right_pts)):
                # Drop consecutive duplicate points so LineString stays valid.
                unique_pts = []
                for c in pts:
                    if not unique_pts or c != unique_pts[-1]:
                        unique_pts.append(c)
                if len(unique_pts) >= 2:
                    edge = LineString(unique_pts)
                    rows.append({
                        "edge_id": edge_id,
                        "River": river,
                        "Reach": reach,
                        "bank_side": side,
                        "geometry": edge,
                        "length": edge.length,
                    })
                    edge_id += 1

        crs = xs_gdf.crs if xs_gdf.crs is not None else HdfBase.get_projection(hdf_path)
        if not rows:
            logger.warning("Could not generate any river edge lines from cross sections")
            return GeoDataFrame()
        return GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def set_river_edge_lines(hdf_path: Path, edge_lines: Optional[GeoDataFrame] = None,
                             ras_object=None) -> int:
        """
        Write river edge lines into ``Geometry/River Edge Lines`` of a geometry HDF.

        .. deprecated::
            Use ``RasGeometryCompute.generate_edge_lines()`` instead, which drives
            HEC-RAS's own edge-line generation in-process (real bank-line-anchored
            offset-curve geometry with the group-level ``Source Data Hash`` that
            HEC-RAS honors). This pure-Python writer produces only a simplified
            approximation that HEC-RAS may silently recompute. Scheduled for
            removal in a future release.

        Pure-Python authoring of the artifact RASMapper's *Create Edge Lines at XS
        Limits* produces. Writing the edge lines directly makes them readable by
        ``get_river_edge_lines()`` and usable by ``get_1d_footprint(edge_source=
        'stored')`` without a RASMapper GUI round trip. Any existing
        ``Geometry/River Edge Lines`` group is replaced.

        Edge lines are stored one polyline per bank in ``Left, Right`` order per
        reach (the convention HEC-RAS derives from row order via ``IsLeft = i %
        2 == 0``). Geometry uses the native RAS polyline encoding — ``Polyline
        Info`` / ``Polyline Parts`` / ``Polyline Points`` (``float64`` points),
        each stamped with the same ``Row`` / ``Column`` / ``Feature Type`` HDF5
        attributes HEC-RAS writes. HEC-RAS stores no ``Attributes`` dataset for
        this layer, so none is written.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file (opened for in-place update).
        edge_lines : GeoDataFrame, optional
            Edge lines to write, with a ``geometry`` column of LineStrings in
            ``Left, Right`` row order per reach (as returned by
            ``generate_river_edge_lines`` or ``get_river_edge_lines``). When None,
            edge lines are generated from cross-section end points via
            ``generate_river_edge_lines()``.
        ras_object : RasPrj, optional
            RAS project object for path resolution context.

        Returns
        -------
        int
            Number of edge-line polylines written. 0 when no edge lines are
            available (nothing is written in that case).

        Notes
        -----
        This writes the geometry-HDF representation that ras-commander reads. It
        does **not** write the group-level ``Source Data Hash`` (the SHA-256 over
        cross-section geometry and bank stations that HEC-RAS uses for cache
        invalidation), nor does it update the ``.rasmap``. As a result HEC-RAS may
        recompute and overwrite these edge lines the next time it opens or
        completes the geometry. For edge lines that survive a HEC-RAS round trip,
        use HEC-RAS's own headless geometry completion (RasProcess.exe
        ``CompleteGeometry``) instead. ``generate_river_edge_lines`` is a
        simplified XS-endpoint construction and does not reproduce HEC-RAS's
        bank-line-anchored offset-curve edge lines vertex-for-vertex.
        """
        import warnings
        warnings.warn(
            "HdfXsec.set_river_edge_lines() is deprecated; use "
            "RasGeometryCompute.generate_edge_lines() for HEC-RAS-authoritative "
            "edge lines with a Source Data Hash.",
            DeprecationWarning,
            stacklevel=2,
        )
        if edge_lines is None:
            edge_lines = HdfXsec.generate_river_edge_lines(hdf_path, ras_object=ras_object)
        if edge_lines is None or edge_lines.empty:
            logger.warning("No edge lines to write; Geometry/River Edge Lines unchanged")
            return 0

        lines = [HdfXsec._as_single_linestring(g) for g in edge_lines.geometry]
        lines = [ln for ln in lines if ln is not None]
        if not lines:
            logger.warning("Edge lines contained no valid LineStrings; nothing written")
            return 0

        # Native RAS polyline encoding: a flat float64 point array indexed by a
        # per-polyline [pnt_start, pnt_cnt, part_start, part_cnt] Info row, with
        # one single-part Parts row [local_pnt_start, pnt_cnt] per polyline.
        points: List = []
        info_rows: List = []
        parts_rows: List = []
        pnt_offset = 0
        for idx, line in enumerate(lines):
            coords = [(float(x), float(y)) for x, y in (c[:2] for c in line.coords)]
            points.extend(coords)
            n = len(coords)
            info_rows.append((pnt_offset, n, idx, 1))
            parts_rows.append((0, n))
            pnt_offset += n

        points_arr = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        info_arr = np.asarray(info_rows, dtype=np.int32)
        parts_arr = np.asarray(parts_rows, dtype=np.int32)

        with h5py.File(hdf_path, "a") as hdf_file:
            geom = hdf_file.require_group("Geometry")
            if "River Edge Lines" in geom:
                del geom["River Edge Lines"]
            grp = geom.create_group("River Edge Lines")

            info_ds = grp.create_dataset("Polyline Info", data=info_arr)
            info_ds.attrs.create("Row", np.bytes_("Feature"))
            info_ds.attrs.create("Column", np.array(
                [b"Point Starting Index", b"Point Count",
                 b"Part Starting Index", b"Part Count"], dtype="S20"))
            info_ds.attrs.create("Feature Type", np.bytes_("Polyline"))

            parts_ds = grp.create_dataset("Polyline Parts", data=parts_arr)
            parts_ds.attrs.create("Row", np.bytes_("Part"))
            parts_ds.attrs.create("Column", np.array(
                [b"Point Starting Index", b"Point Count"], dtype="S20"))

            points_ds = grp.create_dataset("Polyline Points", data=points_arr)
            points_ds.attrs.create("Row", np.bytes_("Points"))
            points_ds.attrs.create("Column", np.array([b"X", b"Y"], dtype="S1"))

        logger.info(f"Wrote {len(lines)} river edge lines to {Path(hdf_path).name}")
        return len(lines)

    @staticmethod
    def _reach_end_cutlines(hdf_path: Path, ras_object=None):
        """Map (River, Reach) -> [first cut line, last cut line] for the reach.

        These are the cross sections that close the upstream and downstream ends
        of the reach footprint ring.
        """
        xs_gdf = HdfXsec.get_cross_sections(hdf_path, ras_object=ras_object)
        if xs_gdf is None or xs_gdf.empty:
            return {}
        if not {"River", "Reach"}.issubset(xs_gdf.columns):
            return {}

        end_cutlines = {}
        for key, group in xs_gdf.groupby(["River", "Reach"], sort=False):
            geoms = [g for g in group.geometry if g is not None]
            if not geoms:
                continue
            end_cutlines[key] = [geoms[0], geoms[-1]]
        return end_cutlines

    @staticmethod
    def _reach_edge_pairs(hdf_path: Path, edge_source: str, ras_object=None):
        """Return (River, Reach, left_line, right_line, source, cut_lines) tuples.

        Labels (River/Reach) always come from the generated (XS-endpoint) edge
        lines, which are reliably grouped by reach. When stored edge lines are
        present and requested, their geometry replaces the generated geometry by
        reach order, giving HEC-RAS's own edge lines with correct reach labels.
        ``cut_lines`` carries the reach's end cross-section cut lines so the
        footprint ring can be closed on real cut-line geometry.
        """
        generated = HdfXsec.generate_river_edge_lines(hdf_path, ras_object=ras_object)
        if generated.empty:
            return []
        end_cutlines = HdfXsec._reach_end_cutlines(hdf_path, ras_object=ras_object)

        # Build ordered (river, reach) -> {Left, Right} from generated edge lines.
        gen_pairs = []
        seen = {}
        for _, row in generated.iterrows():
            key = (row["River"], row["Reach"])
            if key not in seen:
                seen[key] = {"River": row["River"], "Reach": row["Reach"],
                             "Left": None, "Right": None}
                gen_pairs.append(seen[key])
            seen[key][row["bank_side"]] = row.geometry

        use_stored = edge_source in ("stored", "auto")
        stored_lines = None
        if use_stored:
            try:
                stored = HdfXsec.get_river_edge_lines(hdf_path)
            except Exception as e:
                logger.debug(f"Could not read stored river edge lines: {e}")
                stored = GeoDataFrame()
            if stored is not None and not stored.empty and len(stored) % 2 == 0:
                # Stored edge lines come as alternating Left/Right per reach.
                stored_lines = list(stored.geometry)

        if edge_source == "stored" and stored_lines is None:
            logger.warning("No usable stored river edge lines; returning empty pairs")
            return []

        pairs = []
        for idx, gp in enumerate(gen_pairs):
            source = "generated_edge_lines"
            left = gp["Left"]
            right = gp["Right"]
            if stored_lines is not None and (2 * idx + 1) < len(stored_lines) \
                    and len(stored_lines) == 2 * len(gen_pairs):
                left = stored_lines[2 * idx]
                right = stored_lines[2 * idx + 1]
                source = "stored_edge_lines"
            if left is None or right is None:
                continue
            cut_lines = end_cutlines.get((gp["River"], gp["Reach"]), [])
            pairs.append((gp["River"], gp["Reach"], left, right, source, cut_lines))
        return pairs

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_1d_footprint(
        hdf_path: Path,
        edge_source: str = "auto",
        dissolve: bool = False,
        close_with_end_xs: bool = True,
        ras_object=None,
    ) -> GeoDataFrame:
        """
        Build the 1D model footprint polygon(s) from river edge lines.

        For each (River, Reach) the left and right edge lines are closed into a
        polygon ring: left edge, downstream cross section, reversed right edge,
        upstream cross section. The end caps follow the real cut-line geometry of
        the end cross sections, including their interior vertices, so a bent cut
        line is reproduced instead of chorded. This is the true 1D study
        footprint, not a bounding box.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        edge_source : {'auto', 'stored', 'generate'}, default 'auto'
            - 'stored'   : use ``Geometry/River Edge Lines`` only.
            - 'generate' : always generate edge lines from XS end points.
            - 'auto'     : use stored edge lines when present, otherwise generate.
        dissolve : bool, default False
            If True, dissolve the per-reach polygons into a single (multi)polygon
            row. If False, return one polygon row per (River, Reach).
        close_with_end_xs : bool, default True
            Close each ring on the end cross-section cut-line geometry. Set False
            for the legacy behavior, a straight chord between the edge-line end
            points. When an edge-line end point does not land on a cut-line limit
            (possible for stored edge lines), that end cap falls back to the
            straight chord regardless of this setting.
        ras_object : RasPrj, optional
            RAS project object for path resolution context.

        Returns
        -------
        GeoDataFrame
            Columns River, Reach, source, geometry (Polygon). When
            ``dissolve=True``, a single row with a (Multi)Polygon and
            ``source='1d_footprint'``. Empty GeoDataFrame when no 1D geometry is
            available.
        """
        if edge_source not in ("auto", "stored", "generate"):
            raise ValueError(
                f"edge_source must be 'auto', 'stored', or 'generate', got '{edge_source}'"
            )

        crs = HdfBase.get_projection(hdf_path)
        pairs = HdfXsec._reach_edge_pairs(hdf_path, edge_source, ras_object=ras_object)
        if not pairs:
            logger.warning("No 1D edge-line pairs available; returning empty footprint")
            return GeoDataFrame()

        rows = []
        for river, reach, left, right, source, cut_lines in pairs:
            polygon = HdfXsec._polygon_from_edge_pair(
                left, right,
                cut_lines=cut_lines if close_with_end_xs else None,
            )
            if polygon is None:
                logger.debug(f"Could not polygonize reach {river}/{reach}")
                continue
            rows.append({
                "River": river,
                "Reach": reach,
                "source": source,
                "geometry": polygon,
            })

        if not rows:
            logger.warning("Could not build any 1D footprint polygons")
            return GeoDataFrame()

        footprint_gdf = GeoDataFrame(rows, geometry="geometry", crs=crs)

        if dissolve:
            from shapely.ops import unary_union

            combined = unary_union(footprint_gdf.geometry.tolist())
            return GeoDataFrame(
                {"source": ["1d_footprint"]},
                geometry=[combined],
                crs=crs,
            )

        return footprint_gdf

