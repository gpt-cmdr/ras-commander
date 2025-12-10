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

Spatial Query Utilities:
-----------------------
find_nearest_face()
    Find the nearest mesh cell face to a given point
find_nearest_cell()
    Find the nearest mesh cell center to a given point
get_faces_along_profile_line()
    Get mesh cell faces that align with a profile line (for cross-sectional analysis)
combine_faces_to_linestring()
    Combine ordered faces into a single LineString

Each function is decorated with @standardize_input and @log_call for consistent
input handling and logging functionality.
"""
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING
import logging
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import setup_logging, get_logger

# Type hints only - not imported at runtime
if TYPE_CHECKING:
    from geopandas import GeoDataFrame

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
            logger.error(f"Error reading mesh area names from {hdf_path}: {str(e)}")
            return list()

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_areas(hdf_path: Path) -> 'GeoDataFrame':
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
        # Lazy imports for heavy dependencies
        from geopandas import GeoDataFrame
        from shapely.geometry import Polygon

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
    def get_mesh_cell_polygons(hdf_path: Path) -> 'GeoDataFrame':
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
        # Lazy imports for heavy dependencies
        from geopandas import GeoDataFrame
        from shapely.geometry import Polygon
        from shapely.ops import polygonize

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
    def get_mesh_cell_points(hdf_path: Path) -> 'GeoDataFrame':
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
        # Lazy imports for heavy dependencies
        from geopandas import GeoDataFrame
        from shapely.geometry import Point

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
    def get_mesh_cell_faces(hdf_path: Path) -> 'GeoDataFrame':
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
        # Lazy imports for heavy dependencies
        from geopandas import GeoDataFrame
        from shapely.geometry import LineString

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

    # =========================================================================
    # Spatial Query Utilities
    # =========================================================================

    @staticmethod
    def find_nearest_face(
        point,
        cell_faces_gdf: 'GeoDataFrame',
        mesh_name: str = None
    ) -> Tuple[int, float]:
        """
        Find the nearest mesh cell face to a given point.

        This is useful for locating face elements near a point of interest,
        such as when extracting timeseries data at a specific location.

        Parameters
        ----------
        point : shapely.geometry.Point or tuple
            The query point. Can be a shapely Point or (x, y) tuple.
        cell_faces_gdf : GeoDataFrame
            GeoDataFrame containing cell face geometries, typically from
            get_mesh_cell_faces().
        mesh_name : str, optional
            If provided, filter to only faces in this mesh area.

        Returns
        -------
        Tuple[int, float]
            A tuple containing:
            - face_id (int): The ID of the nearest cell face
            - distance (float): The distance to the nearest cell face

        Example
        -------
        >>> cell_faces = HdfMesh.get_mesh_cell_faces(hdf_path)
        >>> face_id, dist = HdfMesh.find_nearest_face((500000, 4000000), cell_faces)
        >>> print(f"Nearest face: {face_id}, Distance: {dist:.2f}")
        """
        from shapely.geometry import Point

        # Convert tuple to Point if needed
        if isinstance(point, tuple):
            point = Point(point)

        # Filter by mesh_name if provided
        faces = cell_faces_gdf
        if mesh_name is not None:
            faces = faces[faces['mesh_name'] == mesh_name]

        if faces.empty:
            logger.warning("No faces found to search")
            return None, None

        # Calculate distances from point to all faces
        distances = faces.geometry.distance(point)

        # Find the index of minimum distance
        min_idx = distances.idxmin()

        return int(faces.loc[min_idx, 'face_id']), float(distances[min_idx])

    @staticmethod
    def find_nearest_cell(
        point,
        cell_points_gdf: 'GeoDataFrame',
        mesh_name: str = None
    ) -> Tuple[int, float]:
        """
        Find the nearest mesh cell center to a given point.

        This is useful for locating cell elements near a point of interest,
        such as when extracting water surface elevations at a specific location.

        Parameters
        ----------
        point : shapely.geometry.Point or tuple
            The query point. Can be a shapely Point or (x, y) tuple.
        cell_points_gdf : GeoDataFrame
            GeoDataFrame containing cell center points, typically from
            get_mesh_cell_points().
        mesh_name : str, optional
            If provided, filter to only cells in this mesh area.

        Returns
        -------
        Tuple[int, float]
            A tuple containing:
            - cell_id (int): The ID of the nearest cell
            - distance (float): The distance to the nearest cell center

        Example
        -------
        >>> cell_points = HdfMesh.get_mesh_cell_points(hdf_path)
        >>> cell_id, dist = HdfMesh.find_nearest_cell((500000, 4000000), cell_points)
        >>> print(f"Nearest cell: {cell_id}, Distance: {dist:.2f}")
        """
        from shapely.geometry import Point

        # Convert tuple to Point if needed
        if isinstance(point, tuple):
            point = Point(point)

        # Filter by mesh_name if provided
        cells = cell_points_gdf
        if mesh_name is not None:
            cells = cells[cells['mesh_name'] == mesh_name]

        if cells.empty:
            logger.warning("No cells found to search")
            return None, None

        # Calculate distances from point to all cell centers
        distances = cells.geometry.distance(point)

        # Find the index of minimum distance
        min_idx = distances.idxmin()

        return int(cells.loc[min_idx, 'cell_id']), float(distances[min_idx])

    @staticmethod
    def _calculate_line_angle(line) -> float:
        """
        Calculate the bearing angle of a line segment in degrees.

        Parameters
        ----------
        line : shapely.geometry.LineString
            The line geometry to calculate angle for.

        Returns
        -------
        float
            Angle in degrees (0-360).
        """
        from shapely.geometry import LineString

        if isinstance(line, LineString):
            x_diff = line.xy[0][-1] - line.xy[0][0]
            y_diff = line.xy[1][-1] - line.xy[1][0]
        else:
            # Assume it's a tuple of coordinates
            x_diff = line[1][0] - line[0][0]
            y_diff = line[1][1] - line[0][1]

        angle = np.degrees(np.arctan2(y_diff, x_diff))
        return angle % 360 if angle >= 0 else (angle + 360) % 360

    @staticmethod
    def _angle_difference(angle1: float, angle2: float) -> float:
        """
        Calculate minimum angle difference accounting for 180 degree equivalence.

        For face selection, we consider faces perpendicular to the profile line,
        so a face at 0 degrees is equivalent to one at 180 degrees.

        Parameters
        ----------
        angle1 : float
            First angle in degrees.
        angle2 : float
            Second angle in degrees.

        Returns
        -------
        float
            Minimum angle difference in degrees (0-90).
        """
        diff = abs(angle1 - angle2) % 180
        return min(diff, 180 - diff)

    @staticmethod
    def _break_line_into_segments(
        line,
        segment_length: float
    ) -> Tuple[List, List[float]]:
        """
        Break a line into segments of specified length and calculate angles.

        Parameters
        ----------
        line : shapely.geometry.LineString
            The line to break into segments.
        segment_length : float
            Target length for each segment.

        Returns
        -------
        Tuple[List, List[float]]
            A tuple containing:
            - List of segment geometries
            - List of angles for each segment
        """
        from shapely.geometry import LineString

        segments = []
        segment_angles = []

        total_length = line.length
        num_segments = max(1, int(total_length / segment_length))

        for i in range(num_segments):
            start_dist = i * segment_length
            end_dist = min((i + 1) * segment_length, total_length)

            start_point = line.interpolate(start_dist)
            end_point = line.interpolate(end_dist)

            segment = LineString([start_point, end_point])
            segments.append(segment)
            segment_angles.append(HdfMesh._calculate_line_angle(segment))

        return segments, segment_angles

    @staticmethod
    def get_faces_along_profile_line(
        profile_line,
        cell_faces_gdf: 'GeoDataFrame',
        distance_threshold: float = 10.0,
        angle_threshold: float = 60.0,
        mesh_name: str = None,
        order_by_distance: bool = True
    ) -> 'GeoDataFrame':
        """
        Get mesh cell faces that align with a profile line.

        This function finds faces that are:
        1. Within a distance threshold of the profile line
        2. Oriented perpendicular to the profile line (within angle threshold)

        This is useful for extracting cross-sectional flow data along a
        transect or profile line.

        Parameters
        ----------
        profile_line : shapely.geometry.LineString
            The profile line to find faces along.
        cell_faces_gdf : GeoDataFrame
            GeoDataFrame containing cell face geometries, typically from
            get_mesh_cell_faces().
        distance_threshold : float, default 10.0
            Maximum distance from profile line to include a face.
        angle_threshold : float, default 60.0
            Maximum angle deviation from perpendicular (degrees).
            A value of 90 would include faces parallel to the profile.
        mesh_name : str, optional
            If provided, filter to only faces in this mesh area.
        order_by_distance : bool, default True
            If True, order faces by distance along the profile line.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing selected faces with additional columns:
            - distance_along_profile: Distance from profile start
            - angle_to_profile: Angle deviation from perpendicular

        Example
        -------
        >>> from shapely.geometry import LineString
        >>> profile = LineString([(500000, 4000000), (501000, 4000000)])
        >>> cell_faces = HdfMesh.get_mesh_cell_faces(hdf_path)
        >>> profile_faces = HdfMesh.get_faces_along_profile_line(
        ...     profile, cell_faces, distance_threshold=15, angle_threshold=45
        ... )
        >>> print(f"Found {len(profile_faces)} faces along profile")
        """
        from shapely.geometry import Point

        # Filter by mesh_name if provided
        faces = cell_faces_gdf.copy()
        if mesh_name is not None:
            faces = faces[faces['mesh_name'] == mesh_name]

        if faces.empty:
            logger.warning("No faces found to search")
            return faces

        # Break profile line into segments for angle comparison
        segments, segment_angles = HdfMesh._break_line_into_segments(
            profile_line, distance_threshold
        )

        # Find faces that match criteria
        selected_indices = set()
        face_angles = {}

        for face_idx, face_row in faces.iterrows():
            face_geom = face_row.geometry
            face_angle = HdfMesh._calculate_line_angle(face_geom)

            # Check each profile segment
            for segment, segment_angle in zip(segments, segment_angles):
                # Check distance
                if face_geom.distance(segment) <= distance_threshold:
                    # Check angle (perpendicular = 90 degree difference)
                    # We want faces perpendicular to profile, so target is segment_angle + 90
                    perpendicular_angle = (segment_angle + 90) % 360
                    angle_diff = HdfMesh._angle_difference(face_angle, perpendicular_angle)

                    if angle_diff <= angle_threshold:
                        selected_indices.add(face_idx)
                        face_angles[face_idx] = angle_diff
                        break

        # Create result GeoDataFrame
        if not selected_indices:
            logger.info("No faces found along profile line with given thresholds")
            result = faces.iloc[0:0].copy()  # Empty GeoDataFrame with same structure
            result['distance_along_profile'] = []
            result['angle_to_profile'] = []
            return result

        result = faces.loc[list(selected_indices)].copy()

        # Calculate distance along profile for each face
        profile_start = Point(profile_line.coords[0])
        result['distance_along_profile'] = result.geometry.apply(
            lambda g: profile_line.project(g.centroid)
        )
        result['angle_to_profile'] = result.index.map(face_angles)

        # Order by distance along profile if requested
        if order_by_distance:
            result = result.sort_values('distance_along_profile').reset_index(drop=True)

        logger.info(f"Found {len(result)} faces along profile line")
        return result

    @staticmethod
    def combine_faces_to_linestring(
        faces_gdf: 'GeoDataFrame',
        order_column: str = 'distance_along_profile'
    ):
        """
        Combine ordered faces into a single LineString.

        This is useful for creating a continuous line from selected profile faces.

        Parameters
        ----------
        faces_gdf : GeoDataFrame
            GeoDataFrame of faces to combine, should be ordered.
        order_column : str, default 'distance_along_profile'
            Column to use for ordering faces.

        Returns
        -------
        shapely.geometry.LineString
            A LineString combining all face geometries.
        """
        from shapely.geometry import LineString

        if faces_gdf.empty:
            return None

        # Ensure ordered
        if order_column in faces_gdf.columns:
            faces_gdf = faces_gdf.sort_values(order_column)

        coords = []
        for _, face in faces_gdf.iterrows():
            face_coords = list(face.geometry.coords)
            if not coords:
                # First face - add all coordinates
                coords.extend(face_coords)
            else:
                # Subsequent faces - add only if not duplicate
                for coord in face_coords:
                    if coord != coords[-1]:
                        coords.append(coord)

        if len(coords) < 2:
            return None

        return LineString(coords)

    # =========================================================================
    # Sloped Interpolation Topology
    # =========================================================================

    @staticmethod
    @standardize_input(file_type='plan_hdf')
    def get_mesh_sloped_topology(
        hdf_path: Path,
        mesh_name: str = None
    ) -> Dict[str, Any]:
        """
        Extract all mesh topology needed for sloped water surface interpolation.

        This function performs a single HDF read to extract all geometric and
        topological data required for RASMapper's "Sloped (Cell Corners)"
        water surface rasterization algorithm.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS plan HDF file.
        mesh_name : str, optional
            Name of the specific mesh area to extract. If None, uses the first
            mesh area found.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all topology data:

            - 'mesh_name': str - Name of the mesh area
            - 'n_cells': int - Number of cells
            - 'n_faces': int - Number of faces
            - 'n_facepoints': int - Number of facepoints (vertices)

            Coordinates:
            - 'cell_centers': ndarray (n_cells, 2) float64 - Cell center X, Y
            - 'facepoint_coords': ndarray (n_facepoints, 2) float64 - Vertex X, Y

            Minimum elevations:
            - 'cell_min_elev': ndarray (n_cells,) float32 - Min terrain per cell
            - 'face_min_elev': ndarray (n_faces,) float32 - Min terrain per face

            Face connectivity:
            - 'face_cells': ndarray (n_faces, 2) int32 - [cell_a, cell_b] per face
              (-1 indicates perimeter/boundary)
            - 'face_facepoints': ndarray (n_faces, 2) int32 - [fp_a, fp_b] per face

            Facepoint-to-face connectivity (CSR-like):
            - 'facepoint_face_info': ndarray (n_facepoints, 2) int32 - [start, count]
            - 'facepoint_face_values': ndarray (n_connections, 2) int32 - [face_idx, orientation]

            Cell-to-face connectivity (CSR-like):
            - 'cell_face_info': ndarray (n_cells, 2) int32 - [start, count]
            - 'cell_face_values': ndarray (n_connections, 2) int32 - [face_idx, orientation]

        Notes
        -----
        The CSR-like format for variable-length connectivity uses:
        - info array: [start_index, count] per element
        - values array: actual connections, accessed as values[start:start+count]

        The orientation value indicates which side of the face the element is on:
        - 0: "a" side (first cell in face_cells)
        - 1: "b" side (second cell in face_cells)

        Example
        -------
        >>> topology = HdfMesh.get_mesh_sloped_topology(plan_hdf_path)
        >>> print(f"Mesh: {topology['mesh_name']}")
        >>> print(f"Cells: {topology['n_cells']}, Faces: {topology['n_faces']}")
        >>>
        >>> # Access faces connected to facepoint 0
        >>> start, count = topology['facepoint_face_info'][0]
        >>> connected_faces = topology['facepoint_face_values'][start:start+count, 0]
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Get mesh area names
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    logger.warning(f"No 2D mesh areas found in {hdf_path}")
                    return {}

                # Select mesh
                if mesh_name is None:
                    mesh_name = mesh_area_names[0]
                    if len(mesh_area_names) > 1:
                        logger.info(f"Multiple meshes found, using first: {mesh_name}")
                elif mesh_name not in mesh_area_names:
                    logger.error(f"Mesh '{mesh_name}' not found. Available: {mesh_area_names}")
                    return {}

                base_path = f"Geometry/2D Flow Areas/{mesh_name}"

                # Read all datasets in single file context
                cell_centers = hdf_file[f"{base_path}/Cells Center Coordinate"][()]
                cell_min_elev = hdf_file[f"{base_path}/Cells Minimum Elevation"][()]
                cell_face_info = hdf_file[f"{base_path}/Cells Face and Orientation Info"][()]
                cell_face_values = hdf_file[f"{base_path}/Cells Face and Orientation Values"][()]

                face_min_elev = hdf_file[f"{base_path}/Faces Minimum Elevation"][()]
                face_cells = hdf_file[f"{base_path}/Faces Cell Indexes"][()]
                face_facepoints = hdf_file[f"{base_path}/Faces FacePoint Indexes"][()]

                facepoint_coords = hdf_file[f"{base_path}/FacePoints Coordinate"][()]
                facepoint_face_info = hdf_file[f"{base_path}/FacePoints Face and Orientation Info"][()]
                facepoint_face_values = hdf_file[f"{base_path}/FacePoints Face and Orientation Values"][()]

                # Build result dictionary
                return {
                    # Metadata
                    'mesh_name': mesh_name,
                    'n_cells': len(cell_centers),
                    'n_faces': len(face_cells),
                    'n_facepoints': len(facepoint_coords),

                    # Coordinates
                    'cell_centers': cell_centers,
                    'facepoint_coords': facepoint_coords,

                    # Minimum elevations
                    'cell_min_elev': cell_min_elev,
                    'face_min_elev': face_min_elev,

                    # Face connectivity
                    'face_cells': face_cells,
                    'face_facepoints': face_facepoints,

                    # Facepoint-to-face connectivity (CSR-like)
                    'facepoint_face_info': facepoint_face_info,
                    'facepoint_face_values': facepoint_face_values,

                    # Cell-to-face connectivity (CSR-like)
                    'cell_face_info': cell_face_info,
                    'cell_face_values': cell_face_values,
                }

        except KeyError as e:
            logger.error(f"Missing required dataset in {hdf_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error reading sloped topology from {hdf_path}: {e}")
            return {}
