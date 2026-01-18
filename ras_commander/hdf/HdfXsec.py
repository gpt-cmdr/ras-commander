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
from shapely.geometry import LineString, MultiLineString
from typing import List  # Import List to avoid NameError
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
                        gdf.set_crs(proj, allow_override=True)
                    
                    return gdf
                
                return gpd.GeoDataFrame()
                
        except Exception as e:
            logger.error(f"Error processing cross-section data: {str(e)}")
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
                    logger.warning("No river centerlines found in geometry file")
                    return GeoDataFrame()

                centerline_data = hdf_file["Geometry/River Centerlines"]
                
                # Get attributes directly from HDF dataset
                attrs = centerline_data["Attributes"][()]
                
                # Create initial dictionary for DataFrame
                centerline_dict = {}
                
                # Process each attribute field
                for name in attrs.dtype.names:
                    values = attrs[name]
                    if values.dtype.kind == 'S':
                        # Convert byte strings to regular strings
                        centerline_dict[name] = [val.decode('utf-8').strip() for val in values]
                    else:
                        centerline_dict[name] = values.tolist()  # Convert numpy array to list

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

                logger.info(f"Extracted {len(centerline_gdf)} river centerlines")
                return centerline_gdf

        except Exception as e:
            logger.error(f"Error reading river centerlines: {str(e)}")
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
            logger.warning("Empty centerlines GeoDataFrame provided")
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
                    return GeoDataFrame()

                river_data = hdf_file["Geometry/River Centerlines"]
                v_conv_val = np.vectorize(HdfUtils.convert_ras_string)
                river_attrs = river_data["Attributes"][()]
                river_dict = {"river_id": range(river_attrs.shape[0])}
                river_dict.update(
                    {name: v_conv_val(river_attrs[name]) for name in river_attrs.dtype.names}
                )
                
                # Get polylines for river reaches
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path, "Geometry/River Centerlines"
                )

                river_gdf = GeoDataFrame(
                    river_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path),
                )
                if datetime_to_str:
                    river_gdf["Last Edited"] = river_gdf["Last Edited"].apply(
                        lambda x: pd.Timestamp.isoformat(x)
                    )
                return river_gdf
        except Exception as e:
            logger.error(f"Error reading river reaches: {str(e)}")
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
                    logger.warning("No river edge lines found in geometry file")
                    return GeoDataFrame()

                edge_data = hdf_file["Geometry/River Edge Lines"]
                
                # Get attributes if they exist
                if "Attributes" in edge_data:
                    attrs = edge_data["Attributes"][()]
                    v_conv_val = np.vectorize(HdfUtils.convert_ras_string)
                    
                    # Create dictionary of attributes
                    edge_dict = {"edge_id": range(attrs.shape[0])}
                    edge_dict.update(
                        {name: v_conv_val(attrs[name]) for name in attrs.dtype.names}
                    )
                    
                    # Add bank side indicator
                    if edge_dict["edge_id"].size % 2 == 0:  # Ensure even number of edges
                        edge_dict["bank_side"] = ["Left", "Right"] * (edge_dict["edge_id"].size // 2)
                else:
                    edge_dict = {"edge_id": [], "bank_side": []}

                # Get polyline geometries
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path, 
                    "Geometry/River Edge Lines",
                    info_name="Polyline Info",
                    parts_name="Polyline Parts",
                    points_name="Polyline Points"
                )

                # Create GeoDataFrame
                edge_gdf = GeoDataFrame(
                    edge_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Convert datetime objects to strings if requested
                if datetime_to_str and 'Last Edited' in edge_gdf.columns:
                    edge_gdf["Last Edited"] = edge_gdf["Last Edited"].apply(
                        lambda x: pd.Timestamp.isoformat(x) if pd.notnull(x) else None
                    )

                # Add length calculation in project units
                if not edge_gdf.empty:
                    edge_gdf['length'] = edge_gdf.geometry.length

                return edge_gdf

        except Exception as e:
            logger.error(f"Error reading river edge lines: {str(e)}")
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
                    logger.warning("No river bank lines found in geometry file")
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
                    "bank_id": range(len(geoms)),
                    "bank_side": ["Left", "Right"] * (len(geoms) // 2)  # Assuming pairs of left/right banks
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
            logger.error(f"Error reading river bank lines: {str(e)}")
            return GeoDataFrame()

