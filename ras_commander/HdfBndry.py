"""
Class: HdfBndry

A utility class for extracting and processing boundary-related features from HEC-RAS HDF files,
including boundary conditions, breaklines, refinement regions, and reference features.

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfBndry:
- get_bc_lines()           # Returns boundary condition lines as a GeoDataFrame.
- get_breaklines()         # Returns 2D mesh area breaklines as a GeoDataFrame.
- get_refinement_regions() # Returns refinement regions as a GeoDataFrame.
- get_reference_lines()    # Returns reference lines as a GeoDataFrame.
- get_reference_points()   # Returns reference points as a GeoDataFrame.



"""
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon, Point
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .HdfMesh import HdfMesh
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)


class HdfBndry:
    """
    A class for handling boundary-related data from HEC-RAS HDF files.

    This class provides methods to extract and process various boundary elements
    such as boundary condition lines, breaklines, refinement regions, and reference
    lines/points from HEC-RAS geometry HDF files.

    Methods in this class return data primarily as GeoDataFrames, making it easy
    to work with spatial data in a geospatial context.

    Note:
        This class relies on the HdfBase and HdfUtils classes for some of its
        functionality. Ensure these classes are available in the same package.
    """
    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_bc_lines(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return 2D mesh area boundary condition lines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the boundary condition lines and their attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                bc_lines_path = "Geometry/Boundary Condition Lines"
                if bc_lines_path not in hdf_file:
                    return gpd.GeoDataFrame()
                
                # Get geometries
                bc_line_data = hdf_file[bc_lines_path]
                geoms = HdfBase.get_polylines_from_parts(hdf_path, bc_lines_path)
                
                # Get attributes
                attributes = pd.DataFrame(bc_line_data["Attributes"][()])
                
                # Convert string columns
                str_columns = ['Name', 'SA-2D', 'Type']
                for col in str_columns:
                    if col in attributes.columns:
                        attributes[col] = attributes[col].apply(HdfUtils.convert_ras_string)
                
                # Create GeoDataFrame with all attributes
                gdf = gpd.GeoDataFrame(
                    attributes,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_file)
                )
                
                # Add ID column if not present
                if 'bc_line_id' not in gdf.columns:
                    gdf['bc_line_id'] = range(len(gdf))
                    
                return gdf

        except Exception as e:
            logger.error(f"Error reading boundary condition lines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_breaklines(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return 2D mesh area breaklines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the breaklines.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                breaklines_path = "Geometry/2D Flow Area Break Lines"
                if breaklines_path not in hdf_file:
                    logger.warning(f"Breaklines path '{breaklines_path}' not found in HDF file.")
                    return gpd.GeoDataFrame()
                bl_line_data = hdf_file[breaklines_path]
                bl_line_ids = range(bl_line_data["Attributes"][()].shape[0])
                names = np.vectorize(HdfUtils.convert_ras_string)(
                    bl_line_data["Attributes"][()]["Name"]
                )
                geoms = HdfBase.get_polylines_from_parts(hdf_path, breaklines_path)
                return gpd.GeoDataFrame(
                    {"bl_id": bl_line_ids, "Name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
        except Exception as e:
            logger.error(f"Error reading breaklines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_refinement_regions(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return 2D mesh area refinement regions.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the refinement regions.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                refinement_regions_path = "/Geometry/2D Flow Area Refinement Regions"
                if refinement_regions_path not in hdf_file:
                    return gpd.GeoDataFrame()
                rr_data = hdf_file[refinement_regions_path]
                rr_ids = range(rr_data["Attributes"][()].shape[0])
                names = np.vectorize(HdfUtils.convert_ras_string)(rr_data["Attributes"][()]["Name"])
                geoms = list()
                for pnt_start, pnt_cnt, part_start, part_cnt in rr_data["Polygon Info"][()]:
                    points = rr_data["Polygon Points"][()][pnt_start : pnt_start + pnt_cnt]
                    if part_cnt == 1:
                        geoms.append(Polygon(points))
                    else:
                        parts = rr_data["Polygon Parts"][()][part_start : part_start + part_cnt]
                        geoms.append(
                            MultiPolygon(
                                list(
                                    points[part_pnt_start : part_pnt_start + part_pnt_cnt]
                                    for part_pnt_start, part_pnt_cnt in parts
                                )
                            )
                        )
                return gpd.GeoDataFrame(
                    {"rr_id": rr_ids, "Name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
        except Exception as e:
            logger.error(f"Error reading refinement regions: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_reference_lines(hdf_path: Path, mesh_name: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Return the reference lines geometry and attributes.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : Optional[str], optional
            Name of the mesh to filter by. Default is None.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the reference lines. If mesh_name is provided,
            returns only lines for that mesh.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                reference_lines_path = "Geometry/Reference Lines"
                attributes_path = f"{reference_lines_path}/Attributes"
                if attributes_path not in hdf_file:
                    return gpd.GeoDataFrame()
                
                attributes = hdf_file[attributes_path][()]
                refline_ids = range(attributes.shape[0])
                v_conv_str = np.vectorize(HdfUtils.convert_ras_string)
                names = v_conv_str(attributes["Name"])
                mesh_names = v_conv_str(attributes["SA-2D"])
                
                try:
                    types = v_conv_str(attributes["Type"])
                except ValueError:
                    types = np.array([""] * attributes.shape[0])
                
                geoms = HdfBase.get_polylines_from_parts(hdf_path, reference_lines_path)
                
                gdf = gpd.GeoDataFrame(
                    {
                        "refln_id": refline_ids,
                        "Name": names,
                        "mesh_name": mesh_names,
                        "Type": types,
                        "geometry": geoms,
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
                
                # Filter by mesh_name if provided
                if mesh_name is not None:
                    gdf = gdf[gdf['mesh_name'] == mesh_name]
                
                return gdf
                
        except Exception as e:
            logger.error(f"Error reading reference lines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_reference_points(hdf_path: Path, mesh_name: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Return the reference points geometry and attributes.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : Optional[str], optional
            Name of the mesh to filter by. Default is None.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the reference points. If mesh_name is provided,
            returns only points for that mesh.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                reference_points_path = "Geometry/Reference Points"
                attributes_path = f"{reference_points_path}/Attributes"
                if attributes_path not in hdf_file:
                    return gpd.GeoDataFrame()
                
                ref_points_group = hdf_file[reference_points_path]
                attributes = ref_points_group["Attributes"][:]
                v_conv_str = np.vectorize(HdfUtils.convert_ras_string)
                names = v_conv_str(attributes["Name"])
                mesh_names = v_conv_str(attributes["SA/2D"])
                cell_id = attributes["Cell Index"]
                points = ref_points_group["Points"][()]
                
                gdf = gpd.GeoDataFrame(
                    {
                        "refpt_id": range(attributes.shape[0]),
                        "Name": names,
                        "mesh_name": mesh_names,
                        "Cell Index": cell_id,
                        "geometry": list(map(Point, points)),
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
                
                # Filter by mesh_name if provided
                if mesh_name is not None:
                    gdf = gdf[gdf['mesh_name'] == mesh_name]
                
                return gdf
                
        except Exception as e:
            logger.error(f"Error reading reference points: {str(e)}")
            return gpd.GeoDataFrame()

    
