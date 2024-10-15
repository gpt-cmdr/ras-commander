"""
Class: HdfBndry

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.
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
    def bc_lines(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return 2D mesh area boundary condition lines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the boundary condition lines.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                bc_lines_path = "Geometry/Boundary Condition Lines"
                if bc_lines_path not in hdf_file:
                    return gpd.GeoDataFrame()
                bc_line_data = hdf_file[bc_lines_path]
                bc_line_ids = range(bc_line_data["Attributes"][()].shape[0])
                v_conv_str = np.vectorize(HdfUtils.convert_ras_hdf_string)
                names = v_conv_str(bc_line_data["Attributes"][()]["Name"])
                mesh_names = v_conv_str(bc_line_data["Attributes"][()]["SA-2D"])
                types = v_conv_str(bc_line_data["Attributes"][()]["Type"])
                geoms = HdfBndry._get_polylines(hdf_file, bc_lines_path)
                return gpd.GeoDataFrame(
                    {
                        "bc_line_id": bc_line_ids,
                        "name": names,
                        "mesh_name": mesh_names,
                        "type": types,
                        "geometry": geoms,
                    },
                    geometry="geometry",
                    crs=HdfUtils.projection(hdf_file),
                )
        except Exception as e:
            print(f"Error reading boundary condition lines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def breaklines(hdf_path: Path) -> gpd.GeoDataFrame:
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
                    return gpd.GeoDataFrame()
                bl_line_data = hdf_file[breaklines_path]
                bl_line_ids = range(bl_line_data["Attributes"][()].shape[0])
                names = np.vectorize(HdfUtils.convert_ras_hdf_string)(
                    bl_line_data["Attributes"][()]["Name"]
                )
                geoms = HdfBndry._get_polylines(hdf_file, breaklines_path)
                return gpd.GeoDataFrame(
                    {"bl_id": bl_line_ids, "name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfUtils.projection(hdf_file),
                )
        except Exception as e:
            print(f"Error reading breaklines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def refinement_regions(hdf_path: Path) -> gpd.GeoDataFrame:
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
                names = np.vectorize(HdfUtils.convert_ras_hdf_string)(rr_data["Attributes"][()]["Name"])
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
                    {"rr_id": rr_ids, "name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfUtils.projection(hdf_file),
                )
        except Exception as e:
            print(f"Error reading refinement regions: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def reference_lines_names(hdf_path: Path, mesh_name: Optional[str] = None) -> Union[Dict[str, List[str]], List[str]]:
        """
        Return reference line names.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : Optional[str], optional
            Name of the mesh to filter by. Default is None.

        Returns
        -------
        Union[Dict[str, List[str]], List[str]]
            A dictionary of mesh names to reference line names, or a list of reference line names if mesh_name is provided.
        """
        return HdfBndry._get_reference_lines_points_names(hdf_path, "lines", mesh_name)

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def reference_points_names(hdf_path: Path, mesh_name: Optional[str] = None) -> Union[Dict[str, List[str]], List[str]]:
        """
        Return reference point names.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : Optional[str], optional
            Name of the mesh to filter by. Default is None.

        Returns
        -------
        Union[Dict[str, List[str]], List[str]]
            A dictionary of mesh names to reference point names, or a list of reference point names if mesh_name is provided.
        """
        return HdfBndry._get_reference_lines_points_names(hdf_path, "points", mesh_name)

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def reference_lines(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return the reference lines geometry and attributes.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the reference lines.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                reference_lines_path = "Geometry/Reference Lines"
                attributes_path = f"{reference_lines_path}/Attributes"
                if attributes_path not in hdf_file:
                    return gpd.GeoDataFrame()
                attributes = hdf_file[attributes_path][()]
                refline_ids = range(attributes.shape[0])
                v_conv_str = np.vectorize(HdfUtils.convert_ras_hdf_string)
                names = v_conv_str(attributes["Name"])
                mesh_names = v_conv_str(attributes["SA-2D"])
                try:
                    types = v_conv_str(attributes["Type"])
                except ValueError:
                    # "Type" field doesn't exist -- observed in some RAS HDF files
                    types = np.array([""] * attributes.shape[0])
                geoms = HdfBndry._get_polylines(hdf_file, reference_lines_path)
                return gpd.GeoDataFrame(
                    {
                        "refln_id": refline_ids,
                        "refln_name": names,
                        "mesh_name": mesh_names,
                        "type": types,
                        "geometry": geoms,
                    },
                    geometry="geometry",
                    crs=HdfUtils.projection(hdf_file),
                )
        except Exception as e:
            print(f"Error reading reference lines: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def reference_points(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Return the reference points geometry and attributes.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the reference points.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                reference_points_path = "Geometry/Reference Points"
                attributes_path = f"{reference_points_path}/Attributes"
                if attributes_path not in hdf_file:
                    return gpd.GeoDataFrame()
                ref_points_group = hdf_file[reference_points_path]
                attributes = ref_points_group["Attributes"][:]
                v_conv_str = np.vectorize(HdfUtils.convert_ras_hdf_string)
                names = v_conv_str(attributes["Name"])
                mesh_names = v_conv_str(attributes["SA/2D"])
                cell_id = attributes["Cell Index"]
                points = ref_points_group["Points"][()]
                return gpd.GeoDataFrame(
                    {
                        "refpt_id": range(attributes.shape[0]),
                        "refpt_name": names,
                        "mesh_name": mesh_names,
                        "cell_id": cell_id,
                        "geometry": list(map(Point, points)),
                    },
                    geometry="geometry",
                    crs=HdfUtils.projection(hdf_file),
                )
        except Exception as e:
            print(f"Error reading reference points: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    def _get_reference_lines_points_names(hdf_path: Path, reftype: str = "lines", mesh_name: Optional[str] = None) -> Union[Dict[str, List[str]], List[str]]:
        """
        Get the names of reference lines or points.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        reftype : str, optional
            Type of reference, either "lines" or "points" (default "lines").
        mesh_name : Optional[str], optional
            Name of the mesh to filter by. Default is None.

        Returns
        -------
        Union[Dict[str, List[str]], List[str]]
            A dictionary of mesh names to reference names, or a list of reference names if mesh_name is provided.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if reftype == "lines":
                    path = "Geometry/Reference Lines"
                    sa_2d_field = "SA-2D"
                elif reftype == "points":
                    path = "Geometry/Reference Points"
                    sa_2d_field = "SA/2D"
                else:
                    raise ValueError(
                        f"Invalid reference type: {reftype} -- must be 'lines' or 'points'."
                    )
                attributes_path = f"{path}/Attributes"
                if mesh_name is None and attributes_path not in hdf_file:
                    return {m: [] for m in HdfMesh.mesh_area_names(hdf_file)}
                if mesh_name is not None and attributes_path not in hdf_file:
                    return []
                attributes = hdf_file[attributes_path][()]
                v_conv_str = np.vectorize(HdfUtils.convert_ras_hdf_string)
                names = v_conv_str(attributes["Name"])
                if mesh_name is not None:
                    return names[v_conv_str(attributes[sa_2d_field]) == mesh_name].tolist()
                mesh_names = v_conv_str(attributes[sa_2d_field])
                return {m: names[mesh_names == m].tolist() for m in np.unique(mesh_names)}
        except Exception as e:
            print(f"Error reading reference lines/points names: {str(e)}")
            return {} if mesh_name is None else []

    @staticmethod
    def _get_polylines(hdf_file: h5py.File, path: str, info_name: str = "Polyline Info", parts_name: str = "Polyline Parts", points_name: str = "Polyline Points") -> List[Union[LineString, MultiLineString]]:
        """
        Get polyline geometries from HDF file.

        Parameters
        ----------
        hdf_file : h5py.File
            Open HDF file object.
        path : str
            Path to the polyline data in the HDF file.
        info_name : str, optional
            Name of the info dataset (default "Polyline Info").
        parts_name : str, optional
            Name of the parts dataset (default "Polyline Parts").
        points_name : str, optional
            Name of the points dataset (default "Polyline Points").

        Returns
        -------
        List[Union[LineString, MultiLineString]]
            A list of polyline geometries.
        """
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
    
    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_boundary_attributes(hdf_path: Path, boundary_type: str) -> pd.DataFrame:
        """
        Get attributes of boundary elements.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        boundary_type : str
            Type of boundary element ('bc_lines', 'breaklines', 'refinement_regions', 'reference_lines', 'reference_points').

        Returns
        -------
        pd.DataFrame
            A DataFrame containing the attributes of the specified boundary element.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if boundary_type == 'bc_lines':
                    path = "Geometry/Boundary Condition Lines/Attributes"
                elif boundary_type == 'breaklines':
                    path = "Geometry/2D Flow Area Break Lines/Attributes"
                elif boundary_type == 'refinement_regions':
                    path = "Geometry/2D Flow Area Refinement Regions/Attributes"
                elif boundary_type == 'reference_lines':
                    path = "Geometry/Reference Lines/Attributes"
                elif boundary_type == 'reference_points':
                    path = "Geometry/Reference Points/Attributes"
                else:
                    raise ValueError(f"Invalid boundary type: {boundary_type}")

                if path not in hdf_file:
                    return pd.DataFrame()

                attributes = hdf_file[path][()]
                return pd.DataFrame(attributes)
        except Exception as e:
            print(f"Error reading {boundary_type} attributes: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_boundary_count(hdf_path: Path, boundary_type: str) -> int:
        """
        Get the count of boundary elements.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        boundary_type : str
            Type of boundary element ('bc_lines', 'breaklines', 'refinement_regions', 'reference_lines', 'reference_points').

        Returns
        -------
        int
            The count of the specified boundary element.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if boundary_type == 'bc_lines':
                    path = "Geometry/Boundary Condition Lines/Attributes"
                elif boundary_type == 'breaklines':
                    path = "Geometry/2D Flow Area Break Lines/Attributes"
                elif boundary_type == 'refinement_regions':
                    path = "Geometry/2D Flow Area Refinement Regions/Attributes"
                elif boundary_type == 'reference_lines':
                    path = "Geometry/Reference Lines/Attributes"
                elif boundary_type == 'reference_points':
                    path = "Geometry/Reference Points/Attributes"
                else:
                    raise ValueError(f"Invalid boundary type: {boundary_type}")

                if path not in hdf_file:
                    return 0

                return hdf_file[path].shape[0]
        except Exception as e:
            print(f"Error getting {boundary_type} count: {str(e)}")
            return 0

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_boundary_names(hdf_path: Path, boundary_type: str) -> List[str]:
        """
        Get the names of boundary elements.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        boundary_type : str
            Type of boundary element ('bc_lines', 'breaklines', 'refinement_regions', 'reference_lines', 'reference_points').

        Returns
        -------
        List[str]
            A list of names for the specified boundary element.
        """
        try:
            df = HdfBndry.get_boundary_attributes(hdf_path, boundary_type)
            if 'Name' in df.columns:
                return df['Name'].tolist()
            else:
                return []
        except Exception as e:
            print(f"Error getting {boundary_type} names: {str(e)}")
            return []