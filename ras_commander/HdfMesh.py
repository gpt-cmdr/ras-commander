"""
A static class for handling mesh-related operations on HEC-RAS HDF files.

This class provides static methods to extract and analyze mesh data from HEC-RAS HDF files,
including mesh area names, mesh areas, cell polygons, cell points, cell faces, and
2D flow area attributes. No instantiation is required to use these methods.

All methods are designed to work with the mesh geometry data stored in
HEC-RAS HDF files, providing functionality to retrieve and process various aspects
of the 2D flow areas and their associated mesh structures.


List of Functions:
-----------------
get_mesh_area_names()
    Returns list of 2D mesh area names
get_mesh_areas()
    Returns 2D flow area perimeter polygons
get_mesh_cell_polygons()
    Returns 2D flow mesh cell polygons
get_mesh_cell_points()
    Returns 2D flow mesh cell center points
get_mesh_cell_faces()
    Returns 2D flow mesh cell faces
get_mesh_area_attributes()
    Returns geometry 2D flow area attributes
get_mesh_face_property_tables()
    Returns Face Property Tables for each Face in all 2D Flow Areas
get_mesh_cell_property_tables()
    Returns Cell Property Tables for each Cell in all 2D Flow Areas

Each function is decorated with @standardize_input and @log_call for consistent
input handling and logging functionality.
"""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import Polygon, Point, LineString, MultiLineString, MultiPolygon
from shapely.ops import polygonize  # Importing polygonize to resolve the undefined name error
from typing import List, Tuple, Optional, Dict, Any
import logging
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .Decorators import standardize_input, log_call
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)


class HdfMesh:
    """
    A class for handling mesh-related operations on HEC-RAS HDF files.

    This class provides methods to extract and analyze mesh data from HEC-RAS HDF files,
    including mesh area names, mesh areas, cell polygons, cell points, cell faces, and
    2D flow area attributes.

    Methods in this class are designed to work with the mesh geometry data stored in
    HEC-RAS HDF files, providing functionality to retrieve and process various aspects
    of the 2D flow areas and their associated mesh structures.

    Note: This class relies on HdfBase and HdfUtils for some underlying operations.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_mesh_area_names(hdf_path: Path) -> List[str]:
        """
        Return a list of the 2D mesh area names from the RAS geometry.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        List[str]
            A list of the 2D mesh area names within the RAS geometry.
            Returns an empty list if no 2D areas exist or if there's an error.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/2D Flow Areas" not in hdf_file:
                    return list()
                return list(
                    [
                        HdfUtils.convert_ras_string(n.decode('utf-8'))
                        for n in hdf_file["Geometry/2D Flow Areas/Attributes"][()]["Name"]
                    ]
                )
        except Exception as e:
            self.logger.error(f"Error reading mesh area names from {hdf_path}: {str(e)}")
            return list()

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_areas(hdf_path: Path) -> GeoDataFrame:
        """
        Return 2D flow area perimeter polygons.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the 2D flow area perimeter polygons if 2D areas exist.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return GeoDataFrame()
                mesh_area_polygons = [
                    Polygon(hdf_file["Geometry/2D Flow Areas/{}/Perimeter".format(n)][()])
                    for n in mesh_area_names
                ]
                return GeoDataFrame(
                    {"mesh_name": mesh_area_names, "geometry": mesh_area_polygons},
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
        except Exception as e:
            logger.error(f"Error reading mesh areas from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_cell_polygons(hdf_path: Path) -> GeoDataFrame:
        """
        Return 2D flow mesh cell polygons.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the 2D flow mesh cell polygons with columns:
            - mesh_name: name of the mesh area
            - cell_id: unique identifier for each cell
            - geometry: polygon geometry of the cell
            Returns an empty GeoDataFrame if no 2D areas exist or if there's an error.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return GeoDataFrame()

                # Get face geometries once
                face_gdf = HdfMesh.get_mesh_cell_faces(hdf_path)
                
                # Pre-allocate lists for better memory efficiency
                all_mesh_names = []
                all_cell_ids = []
                all_geometries = []

                for mesh_name in mesh_area_names:
                    # Get cell face info in one read
                    cell_face_info = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Face and Orientation Info"][()]
                    cell_face_values = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Face and Orientation Values"][()][:, 0]
                    
                    # Create face lookup dictionary for this mesh
                    mesh_faces_dict = dict(face_gdf[face_gdf.mesh_name == mesh_name][["face_id", "geometry"]].values)

                    # Process each cell
                    for cell_id, (start, length) in enumerate(cell_face_info[:, :2]):
                        face_ids = cell_face_values[start:start + length]
                        face_geoms = [mesh_faces_dict[face_id] for face_id in face_ids]
                        
                        # Create polygon
                        polygons = list(polygonize(face_geoms))
                        if polygons:
                            all_mesh_names.append(mesh_name)
                            all_cell_ids.append(cell_id)
                            all_geometries.append(Polygon(polygons[0]))

                # Create GeoDataFrame in one go
                return GeoDataFrame(
                    {
                        "mesh_name": all_mesh_names,
                        "cell_id": all_cell_ids,
                        "geometry": all_geometries
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file)
                )

        except Exception as e:
            logger.error(f"Error reading mesh cell polygons from {hdf_path}: {str(e)}")
            return GeoDataFrame()
        
    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_mesh_cell_points(hdf_path: Path) -> GeoDataFrame:
        """
        Return 2D flow mesh cell center points.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the 2D flow mesh cell center points.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return GeoDataFrame()
                
                # Pre-allocate lists
                all_mesh_names = []
                all_cell_ids = []
                all_points = []

                for mesh_name in mesh_area_names:
                    # Get all cell centers in one read
                    cell_centers = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Center Coordinate"][()]
                    cell_count = len(cell_centers)
                    
                    # Extend lists efficiently
                    all_mesh_names.extend([mesh_name] * cell_count)
                    all_cell_ids.extend(range(cell_count))
                    all_points.extend(Point(coords) for coords in cell_centers)

                # Create GeoDataFrame in one go
                return GeoDataFrame(
                    {
                        "mesh_name": all_mesh_names,
                        "cell_id": all_cell_ids,
                        "geometry": all_points
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file)
                )

        except Exception as e:
            logger.error(f"Error reading mesh cell points from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_mesh_cell_faces(hdf_path: Path) -> GeoDataFrame:
        """
        Return 2D flow mesh cell faces.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the 2D flow mesh cell faces.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return GeoDataFrame()

                # Pre-allocate lists
                all_mesh_names = []
                all_face_ids = []
                all_geometries = []

                for mesh_name in mesh_area_names:
                    # Read all data at once
                    facepoints_index = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Faces FacePoint Indexes"][()]
                    facepoints_coords = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/FacePoints Coordinate"][()]
                    faces_perim_info = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Faces Perimeter Info"][()]
                    faces_perim_values = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Faces Perimeter Values"][()]

                    # Process each face
                    for face_id, ((pnt_a_idx, pnt_b_idx), (start_row, count)) in enumerate(zip(facepoints_index, faces_perim_info)):
                        coords = [facepoints_coords[pnt_a_idx]]
                        
                        if count > 0:
                            coords.extend(faces_perim_values[start_row:start_row + count])
                            
                        coords.append(facepoints_coords[pnt_b_idx])
                        
                        all_mesh_names.append(mesh_name)
                        all_face_ids.append(face_id)
                        all_geometries.append(LineString(coords))

                # Create GeoDataFrame in one go
                return GeoDataFrame(
                    {
                        "mesh_name": all_mesh_names,
                        "face_id": all_face_ids,
                        "geometry": all_geometries
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file)
                )

        except Exception as e:
            logger.error(f"Error reading mesh cell faces from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_area_attributes(hdf_path: Path) -> pd.DataFrame:
        """
        Return geometry 2D flow area attributes from a HEC-RAS HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        pd.DataFrame
            A DataFrame containing the 2D flow area attributes.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                d2_flow_area = hdf_file.get("Geometry/2D Flow Areas/Attributes")
                if d2_flow_area is not None and isinstance(d2_flow_area, h5py.Dataset):
                    result = {}
                    for name in d2_flow_area.dtype.names:
                        try:
                            value = d2_flow_area[name][()]
                            if isinstance(value, bytes):
                                value = value.decode('utf-8')  # Decode as UTF-8
                            result[name] = value if not isinstance(value, bytes) else value.decode('utf-8')
                        except Exception as e:
                            logger.warning(f"Error converting attribute '{name}': {str(e)}")
                    return pd.DataFrame.from_dict(result, orient='index', columns=['Value'])
                else:
                    logger.info("No 2D Flow Area attributes found or invalid dataset.")
                    return pd.DataFrame()  # Return an empty DataFrame
        except Exception as e:
            logger.error(f"Error reading 2D flow area attributes from {hdf_path}: {str(e)}")
            return pd.DataFrame()  # Return an empty DataFrame

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_face_property_tables(hdf_path: Path) -> Dict[str, pd.DataFrame]:
        """
        Extract Face Property Tables for each Face in all 2D Flow Areas.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        Dict[str, pd.DataFrame]
            A dictionary where:
            - keys: mesh area names (str)
            - values: DataFrames with columns:
                - Face ID: unique identifier for each face
                - Z: elevation
                - Area: face area
                - Wetted Perimeter: wetted perimeter length
                - Manning's n: Manning's roughness coefficient
            Returns an empty dictionary if no 2D areas exist or if there's an error.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return {}

                result = {}
                for mesh_name in mesh_area_names:
                    area_elevation_info = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Faces Area Elevation Info"][()]
                    area_elevation_values = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Faces Area Elevation Values"][()]
                    
                    face_data = []
                    for face_id, (start_index, count) in enumerate(area_elevation_info):
                        face_values = area_elevation_values[start_index:start_index+count]
                        for z, area, wetted_perimeter, mannings_n in face_values:
                            face_data.append({
                                'Face ID': face_id,
                                'Z': str(z),
                                'Area': str(area), 
                                'Wetted Perimeter': str(wetted_perimeter),
                                "Manning's n": str(mannings_n)
                            })
                    
                    result[mesh_name] = pd.DataFrame(face_data)
                
                return result

        except Exception as e:
            logger.error(f"Error extracting face property tables from {hdf_path}: {str(e)}")
            return {}

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_cell_property_tables(hdf_path: Path) -> Dict[str, pd.DataFrame]:
        """
        Extract Cell Property Tables for each Cell in all 2D Flow Areas.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        Dict[str, pd.DataFrame]
            A dictionary where:
            - keys: mesh area names (str)
            - values: DataFrames with columns:
                - Cell ID: unique identifier for each cell
                - Z: elevation
                - Volume: cell volume
                - Surface Area: cell surface area
            Returns an empty dictionary if no 2D areas exist or if there's an error.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return {}

                result = {}
                for mesh_name in mesh_area_names:
                    cell_elevation_info = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Elevation Volume Info"][()]
                    cell_elevation_values = hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Elevation Volume Values"][()]
                    
                    cell_data = []
                    for cell_id, (start_index, count) in enumerate(cell_elevation_info):
                        cell_values = cell_elevation_values[start_index:start_index+count]
                        for z, volume, surface_area in cell_values:
                            cell_data.append({
                                'Cell ID': cell_id,
                                'Z': str(z),
                                'Volume': str(volume),
                                'Surface Area': str(surface_area)
                            })
                    
                    result[mesh_name] = pd.DataFrame(cell_data)
                
                return result

        except Exception as e:
            logger.error(f"Error extracting cell property tables from {hdf_path}: {str(e)}")
            return {}
