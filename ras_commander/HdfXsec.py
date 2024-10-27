"""
Class: HdfXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
"""

from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from typing import List  # Import List to avoid NameError
from .Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .LoggingConfig import get_logger
import logging



logger = get_logger(__name__)

class HdfXsec:
    """
    HdfXsec class for handling cross-section related operations on HEC-RAS HDF files.

    This class provides methods to extract and process cross-section data, elevation information,
    and river reach data from HEC-RAS HDF geometry files. It includes functionality to retrieve
    cross-section attributes, elevation profiles, and river reach geometries.

    The class uses static methods, allowing for direct calls without instantiation. It relies on
    utility functions from HdfBase and HdfUtils classes for various operations such as projection
    handling and data conversion.

    Note:
        This class is designed to work with HEC-RAS geometry HDF files and requires them to have
        a specific structure and naming convention for the data groups and attributes.
        """
    @staticmethod
    @log_call
    def cross_sections(hdf_path: str, datetime_to_str: bool = True, ras_object=None) -> gpd.GeoDataFrame:
        """
        Extract cross sections from HDF geometry file and return as GeoDataFrame
        
        Parameters
        ----------
        hdf_path : str
            Path to HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, by default True
        ras_object : RasPrj, optional
            RAS project object, by default None
            
        Returns
        -------
        gpd.GeoDataFrame
            GeoDataFrame containing cross section geometries and attributes including:
            - River name
            - Reach name 
            - River station
            - Name
            - Description
            - Left/Channel/Right lengths
            - Bank stations
            - Friction mode
            - Contraction/Expansion coefficients
            - Levee information
            - Hydraulic property parameters
            - Block modes
            - Last edited timestamp
            - Manning's n values and stations
            - Ineffective blocks data
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Extract datasets
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
                
                # Get ineffective blocks data
                ineff_blocks = hdf['/Geometry/Cross Sections/Ineffective Blocks'][:]
                ineff_info = hdf['/Geometry/Cross Sections/Ineffective Info'][:]
                
                # Initialize lists to store data
                geometries = []
                station_elevations = []
                mannings_n = []
                ineffective_blocks = []
                
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
                        
                        # Extract ineffective blocks data
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
                
                # Create GeoDataFrame
                if geometries:
                    # Create DataFrame from attributes
                    data = {
                        'geometry': geometries,
                        'station_elevation': station_elevations,
                        'mannings_n': mannings_n,
                        'ineffective_blocks': ineffective_blocks,
                        'River': [x['River'].decode('utf-8').strip() for x in xs_attrs],
                        'Reach': [x['Reach'].decode('utf-8').strip() for x in xs_attrs],
                        'RS': [x['RS'].decode('utf-8').strip() for x in xs_attrs],
                        'Name': [x['Name'].decode('utf-8').strip() for x in xs_attrs],
                        'Description': [x['Description'].decode('utf-8').strip() for x in xs_attrs],
                        'Len Left': xs_attrs['Len Left'],
                        'Len Channel': xs_attrs['Len Channel'],
                        'Len Right': xs_attrs['Len Right'], 
                        'Left Bank': xs_attrs['Left Bank'],
                        'Right Bank': xs_attrs['Right Bank'],
                        'Friction Mode': [x['Friction Mode'].decode('utf-8').strip() for x in xs_attrs],
                        'Contr': xs_attrs['Contr'],
                        'Expan': xs_attrs['Expan'],
                        'Left Levee Sta': xs_attrs['Left Levee Sta'],
                        'Left Levee Elev': xs_attrs['Left Levee Elev'],
                        'Right Levee Sta': xs_attrs['Right Levee Sta'],
                        'Right Levee Elev': xs_attrs['Right Levee Elev'],
                        'HP Count': xs_attrs['HP Count'],
                        'HP Start Elev': xs_attrs['HP Start Elev'],
                        'HP Vert Incr': xs_attrs['HP Vert Incr'],
                        'HP LOB Slices': xs_attrs['HP LOB Slices'],
                        'HP Chan Slices': xs_attrs['HP Chan Slices'],
                        'HP ROB Slices': xs_attrs['HP ROB Slices'],
                        'Ineff Block Mode': xs_attrs['Ineff Block Mode'],
                        'Obstr Block Mode': xs_attrs['Obstr Block Mode'],
                        'Default Centerline': xs_attrs['Default Centerline'],
                        'Last Edited': [x['Last Edited'].decode('utf-8').strip() for x in xs_attrs]
                    }
                
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
            logging.error(f"Error processing cross-section data: {str(e)}")
            return gpd.GeoDataFrame()


    @staticmethod
    @log_call
    def _get_polylines(hdf_path: Path, path: str, info_name: str = "Polyline Info", parts_name: str = "Polyline Parts", points_name: str = "Polyline Points") -> List[LineString]:
        """
        Helper method to extract polylines from HDF file.
        
        [rest of docstring remains the same]
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                polyline_info_path = f"{path}/{info_name}"
                polyline_parts_path = f"{path}/{parts_name}"
                polyline_points_path = f"{path}/{points_name}"

                polyline_info = hdf_file[polyline_info_path][()]
                polyline_parts = hdf_file[polyline_parts_path][()]
                polyline_points = hdf_file[polyline_points_path][()]

                geoms = []
                for pnt_start, pnt_cnt, part_start, part_cnt in polyline_info:
                    points = polyline_points[pnt_start : pnt_start + pnt_cnt]
                    if part_cnt == 1:
                        geoms.append(LineString(points))
                    else:
                        parts = polyline_parts[part_start : part_start + part_cnt]
                        geoms.append(
                            MultiLineString(
                                list(
                                    points[part_pnt_start : part_pnt_start + part_pnt_cnt]
                                    for part_pnt_start, part_pnt_cnt in parts
                                )
                            )
                        )
                return geoms
        except Exception as e:
            logger.error(f"Error getting polylines: {str(e)}")
            return []


    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def river_centerlines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extract river centerlines from HDF geometry file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, by default False

        Returns
        -------
        GeoDataFrame
            GeoDataFrame containing river centerline geometries and attributes including:
            - River Name
            - Reach Name
            - Upstream Type and Name
            - Downstream Type and Name
            - Junction distances
            - Geometry
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    logger.warning("No river centerlines found in geometry file")
                    return GeoDataFrame()

                centerline_data = hdf_file["Geometry/River Centerlines"]
                
                # Get attributes
                attrs = centerline_data["Attributes"][()]
                v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                
                # Create dictionary of attributes
                centerline_dict = {"centerline_id": range(attrs.shape[0])}
                centerline_dict.update(
                    {name: v_conv_val(attrs[name]) for name in attrs.dtype.names}
                )

                # Get polyline geometries
                geoms = HdfXsec._get_polylines(
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
                    crs=HdfUtils.projection(hdf_path)
                )

                # Decode string columns after creation
                str_columns = ['River Name', 'Reach Name', 'US Type', 
                             'US Name', 'DS Type', 'DS Name']
                for col in str_columns:
                    if col in centerline_gdf.columns:
                        centerline_gdf[col] = centerline_gdf[col].apply(
                            lambda x: x.decode('utf-8').strip() if isinstance(x, bytes) else x
                        )

                # Clean up column names and add length calculation
                if not centerline_gdf.empty:
                    # Calculate length in project units
                    centerline_gdf['length'] = centerline_gdf.geometry.length
                    
                    # Clean string columns
                    str_columns = ['River Name', 'Reach Name', 'US Type',
                                 'US Name', 'DS Type', 'DS Name']
                    for col in str_columns:
                        if col in centerline_gdf.columns:
                            centerline_gdf[col] = centerline_gdf[col].str.strip()

                return centerline_gdf

        except Exception as e:
            logger.error(f"Error reading river centerlines: {str(e)}")
            return GeoDataFrame()



    @staticmethod
    @log_call
    def get_river_stationing(centerlines_gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Calculate river stationing along centerlines.

        Parameters
        ----------
        centerlines_gdf : GeoDataFrame
            GeoDataFrame containing river centerline geometries from river_centerlines()

        Returns
        -------
        GeoDataFrame
            Original GeoDataFrame with additional columns:
            - station_start: Starting station for each reach
            - station_end: Ending station for each reach
            - stations: Array of stations along the centerline
            - points: Array of point geometries along the centerline
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
                if row['upstream_type'] == 'Junction' and row['downstream_type'] != 'Junction':
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
        """Helper method to interpolate station along a line"""
        if distance <= 0:
            return line.coords[0]
        elif distance >= line.length:
            return line.coords[-1]
        return line.interpolate(distance).coords[0]



    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def river_reaches(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
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
            A GeoDataFrame containing the river reaches with their attributes and geometries.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    return GeoDataFrame()

                river_data = hdf_file["Geometry/River Centerlines"]
                v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                river_attrs = river_data["Attributes"][()]
                river_dict = {"river_id": range(river_attrs.shape[0])}
                river_dict.update(
                    {name: v_conv_val(river_attrs[name]) for name in river_attrs.dtype.names}
                )
                
                # Get polylines for river reaches
                geoms = HdfXsec._get_polylines(hdf_path, "Geometry/River Centerlines")
                
                river_gdf = GeoDataFrame(
                    river_dict,
                    geometry=geoms,
                    crs=HdfUtils.projection(hdf_path),
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
    def river_edge_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
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
            A GeoDataFrame containing river edge lines with their attributes and geometries.
            Each row represents a river bank (left or right) with associated attributes.
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
                    v_conv_val = np.vectorize(HdfUtils._convert_ras_hdf_value)
                    
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
                geoms = HdfXsec._get_polylines(
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
                    crs=HdfUtils.projection(hdf_path)
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
    def river_bank_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
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
            GeoDataFrame containing river bank line geometries with attributes:
            - bank_id: Unique identifier for each bank line
            - bank_side: Left or Right bank indicator
            - geometry: LineString geometry of the bank
            - length: Length of the bank line in project units
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Bank Lines" not in hdf_file:
                    logger.warning("No river bank lines found in geometry file")
                    return GeoDataFrame()

                # Get polyline geometries using existing helper method
                geoms = HdfXsec._get_polylines(
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
                    crs=HdfUtils.projection(hdf_path)
                )

                # Add length calculation in project units
                if not bank_gdf.empty:
                    bank_gdf['length'] = bank_gdf.geometry.length

                return bank_gdf

        except Exception as e:
            logger.error(f"Error reading river bank lines: {str(e)}")
            return GeoDataFrame()

