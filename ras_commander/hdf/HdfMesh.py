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
get_mesh_face_hydraulic_properties_at_stage()
    Interpolates 2D face area, wetted perimeter, Manning's n, radius, and conveyance
get_reference_line_internal_faces()
    Returns native reference-line internal face connectivity
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
            - mesh_name: str - Name of the 2D flow area
            - cell_id: int - Unique cell identifier (0-indexed)
            - geometry: Polygon - Cell polygon geometry constructed from face edges
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
            A GeoDataFrame containing the 2D flow mesh cell center points with columns:
            - mesh_name: str - Name of the 2D flow area
            - cell_id: int - Unique cell identifier (0-indexed)
            - geometry: Point - Cell center point geometry
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
            A GeoDataFrame containing the 2D flow mesh cell faces with columns:
            - mesh_name: str - Name of the 2D flow area
            - face_id: int - Unique face identifier (0-indexed)
            - geometry: LineString - Face edge geometry (may include intermediate perimeter points)
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
            A DataFrame containing the 2D flow area attributes with:
            - Index: str - Attribute names (e.g., 'Name', 'Cell Count', 'Face Count')
            - Value: varies - Attribute values (decoded from HDF bytes)
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
                    logger.debug("No 2D Flow Area attributes found or invalid dataset.")
                    return pd.DataFrame()  # Return an empty DataFrame
        except Exception as e:
            logger.error(f"Error reading 2D flow area attributes from {hdf_path}: {str(e)}")
            return pd.DataFrame()  # Return an empty DataFrame

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_face_property_tables(hdf_path: Path) -> Dict[str, pd.DataFrame]:
        """
        Extract Face Property Tables for each Face in all 2D Flow Areas.

        Returns elevation-area-wetted perimeter relationships for each face,
        which define the hydraulic properties at different water surface elevations.
        This data is used internally by HEC-RAS for 2D hydraulic computations.

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
                - Face ID: unique identifier for each face (int)
                - Elevation: water surface elevation (float)
                - Area: face area at that elevation (float)
                - Wetted Perimeter: wetted perimeter length at that elevation (float)
                - Manning's n: Manning's roughness coefficient (float)
            Returns an empty dictionary if no 2D areas exist or if there's an error.
            Returns an empty DataFrame with correct columns for meshes where
            property tables don't exist.

        Notes
        -----
        The HDF path for this data is 'Geometry/2D Flow Areas/{mesh_name}/Faces Area Elevation Info'
        and 'Geometry/2D Flow Areas/{mesh_name}/Faces Area Elevation Values'.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return {}

                result = {}
                for mesh_name in mesh_area_names:
                    base_path = f"Geometry/2D Flow Areas/{mesh_name}"
                    info_path = f"{base_path}/Faces Area Elevation Info"
                    values_path = f"{base_path}/Faces Area Elevation Values"

                    if info_path not in hdf_file or values_path not in hdf_file:
                        logger.warning(f"Face property tables not found for mesh '{mesh_name}'")
                        result[mesh_name] = pd.DataFrame(columns=['Face ID', 'Elevation', 'Area', 'Wetted Perimeter', "Manning's n"])
                        continue

                    area_elevation_info = hdf_file[info_path][()]
                    area_elevation_values = hdf_file[values_path][()]

                    face_data = []
                    for face_id, (start_index, count) in enumerate(area_elevation_info):
                        face_values = area_elevation_values[start_index:start_index+count]
                        for elevation, area, wetted_perimeter, mannings_n in face_values:
                            face_data.append({
                                'Face ID': face_id,
                                'Elevation': float(elevation),
                                'Area': float(area),
                                'Wetted Perimeter': float(wetted_perimeter),
                                "Manning's n": float(mannings_n)
                            })

                    result[mesh_name] = pd.DataFrame(face_data)

                return result

        except Exception as e:
            logger.error(f"Error extracting face property tables from {hdf_path}: {str(e)}")
            return {}

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_mesh_face_hydraulic_properties_at_stage(
        hdf_path: Path,
        mesh_name: str,
        face_ids,
        water_surface,
        unit_system: str = 'us',
    ):
        """
        Interpolate 2D face hydraulic properties at supplied water-surface stages.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : str
            2D flow area name.
        face_ids : scalar or array-like
            Face IDs to evaluate.
        water_surface : scalar, 1D array, or 2D array
            Water-surface elevation(s). Scalars are broadcast to every face.
            1D arrays must contain one value per face. 2D arrays are interpreted
            as time-by-face.
        unit_system : str, default 'us'
            ``'us'``/``'customary'`` uses 1.486 in Manning's conveyance;
            ``'metric'``/``'si'`` uses 1.0.

        Returns
        -------
        xarray.Dataset
            Dataset with dimensions ``time`` and ``face_id`` containing:
            ``area``, ``wetted_perimeter``, ``mannings_n``,
            ``hydraulic_radius``, and ``conveyance``.

        Notes
        -----
        This helper is sourced from the geometry preprocessor face property
        tables stored in the geometry HDF. It is therefore a
        geometry-derived/interpolated view of face hydraulic properties, not
        the canonical native unsteady-results calculation path.

        When native face results such as ``Face Area`` or ``Face Manning's n``
        are available in the plan/results HDF, prefer
        ``HdfResultsMesh.get_mesh_faces_timeseries()`` for QAQC and direct
        comparison to native HEC-RAS output. Those values reflect the solver's
        canonical results path, including aggregation from computational time
        steps to output time steps.

        Conveyance is derived from face property tables using:
        ``K = C * A * (A / P) ** (2 / 3) / n``.

        Stages below the lowest tabulated elevation are treated as dry faces
        with zero area, wetted perimeter, hydraulic radius, and conveyance.
        """
        import xarray as xr

        try:
            coefficient = HdfMesh._manning_conveyance_coefficient(unit_system)
            face_id_array = HdfMesh._normalize_face_ids(face_ids)
            water_surface_array = HdfMesh._normalize_face_water_surface(
                water_surface, len(face_id_array)
            )

            face_property_tables = HdfMesh.get_mesh_face_property_tables(hdf_path)
            if mesh_name not in face_property_tables:
                raise ValueError(
                    f"Mesh '{mesh_name}' not found in face property tables. "
                    f"Available meshes: {list(face_property_tables.keys())}"
                )

            face_lookup = HdfMesh._build_face_property_lookup(
                face_property_tables[mesh_name]
            )

            shape = water_surface_array.shape
            area = np.full(shape, np.nan, dtype=float)
            wetted_perimeter = np.full(shape, np.nan, dtype=float)
            mannings_n = np.full(shape, np.nan, dtype=float)
            above_table_stage_count = 0
            above_table_face_ids = set()
            above_table_max_excess = 0.0

            for col_idx, face_id in enumerate(face_id_array):
                face_table = face_lookup.get(int(face_id))
                if face_table is None or face_table.empty:
                    logger.warning(
                        f"No face property table rows found for face {face_id} "
                        f"in mesh '{mesh_name}'"
                    )
                    continue

                max_table_elevation = float(face_table['Elevation'].max())
                face_water_surface = water_surface_array[:, col_idx]
                above_table_mask = (
                    np.isfinite(face_water_surface)
                    & np.isfinite(max_table_elevation)
                    & (face_water_surface > max_table_elevation)
                )
                if above_table_mask.any():
                    above_count = int(above_table_mask.sum())
                    above_table_stage_count += above_count
                    above_table_face_ids.add(int(face_id))
                    max_excess = float(
                        np.max(face_water_surface[above_table_mask] - max_table_elevation)
                    )
                    above_table_max_excess = max(above_table_max_excess, max_excess)

                interpolated = HdfMesh._interpolate_face_property_table(
                    face_table, water_surface_array[:, col_idx]
                )
                area[:, col_idx] = interpolated['area']
                wetted_perimeter[:, col_idx] = interpolated['wetted_perimeter']
                mannings_n[:, col_idx] = interpolated['mannings_n']

            above_table_face_count = len(above_table_face_ids)
            if above_table_stage_count:
                face_preview = sorted(above_table_face_ids)[:10]
                more_faces = ''
                if above_table_face_count > len(face_preview):
                    more_faces = f" and {above_table_face_count - len(face_preview)} more"
                logger.warning(
                    "Water-surface stages exceed the highest face property table "
                    f"elevation for {above_table_stage_count} stage/face value(s) "
                    f"across {above_table_face_count} face(s) in mesh '{mesh_name}'. "
                    "Values above the table are clipped to the highest tabulated "
                    f"face properties; max exceedance is {above_table_max_excess:.3f}. "
                    f"Face IDs: {face_preview}{more_faces}"
                )

            wet_mask = (area > 0) & (wetted_perimeter > 0)
            hydraulic_radius = np.divide(
                area,
                wetted_perimeter,
                out=np.zeros_like(area, dtype=float),
                where=wet_mask,
            )
            hydraulic_radius[~wet_mask & (np.isnan(area) | np.isnan(wetted_perimeter))] = np.nan

            valid_n = np.isfinite(mannings_n) & (mannings_n > 0)
            conveyance = np.divide(
                coefficient * area * np.power(hydraulic_radius, 2.0 / 3.0),
                mannings_n,
                out=np.zeros_like(area, dtype=float),
                where=wet_mask & valid_n,
            )
            conveyance[wet_mask & ~valid_n] = np.nan
            conveyance[np.isnan(area) | np.isnan(wetted_perimeter)] = np.nan

            return xr.Dataset(
                data_vars={
                    'area': (('time', 'face_id'), area),
                    'wetted_perimeter': (('time', 'face_id'), wetted_perimeter),
                    'mannings_n': (('time', 'face_id'), mannings_n),
                    'hydraulic_radius': (('time', 'face_id'), hydraulic_radius),
                    'conveyance': (('time', 'face_id'), conveyance),
                },
                coords={
                    'time': np.arange(water_surface_array.shape[0], dtype=int),
                    'face_id': face_id_array,
                },
                attrs={
                    'mesh_name': mesh_name,
                    'unit_system': unit_system,
                    'manning_conveyance_coefficient': coefficient,
                    'formula': 'K = C * A * (A / P) ** (2 / 3) / n',
                    'source': 'Geometry/2D Flow Areas/<mesh>/Faces Area Elevation',
                    'source_scope': 'geometry_preprocessor',
                    'above_table_stage_count': above_table_stage_count,
                    'above_table_face_count': above_table_face_count,
                    'above_table_max_excess': above_table_max_excess,
                    'above_table_handling': (
                        'Stages above the last tabulated elevation are clipped '
                        'to the highest tabulated face properties and logged as '
                        'a warning.'
                    ),
                    'preferred_native_alternative': (
                        'Use HdfResultsMesh.get_mesh_faces_timeseries() when '
                        "native Face Area or Face Manning's n outputs are "
                        'available in the plan/results HDF.'
                    ),
                    'dry_face_handling': (
                        'Stages below the first tabulated elevation use zero '
                        'area, wetted perimeter, hydraulic radius, and conveyance.'
                    ),
                },
            )

        except Exception as e:
            logger.error(
                f"Error computing face hydraulic properties from {hdf_path}: {str(e)}"
            )
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_reference_line_internal_faces(
        hdf_path: Path,
        mesh_name: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Return internal mesh faces associated with native HEC-RAS reference lines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        mesh_name : Optional[str], optional
            If provided, return only reference-line faces for this 2D flow area.

        Returns
        -------
        pd.DataFrame
            Rows keyed by reference line and face with columns such as
            ``reference_line_id``, ``profile_name``, ``mesh_name``, ``face_id``,
            ``fp_start_index``, ``fp_end_index``, ``station_start``,
            ``station_end``, ``station_length``, ``face_length``, and
            ``station_fraction`` where source fields are available. Returns an
            empty DataFrame when reference lines or internal faces are absent.
            ``station_fraction`` is the raw HDF-derived fraction and may be
            outside [0, 1] for unusual station data; consumers should validate
            or clip it before using it as a multiplier.
        """
        columns = [
            'reference_line_id',
            'profile_name',
            'mesh_name',
            'face_id',
            'fp_start_index',
            'fp_end_index',
            'station_start',
            'station_end',
            'station_length',
            'face_length',
            'station_fraction',
        ]

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                ref_path = "Geometry/Reference Lines"
                attrs_path = f"{ref_path}/Attributes"
                internal_faces_path = f"{ref_path}/Internal Faces"

                if attrs_path not in hdf_file or internal_faces_path not in hdf_file:
                    return pd.DataFrame(columns=columns)

                attributes = hdf_file[attrs_path][()]
                internal_faces = hdf_file[internal_faces_path][()]
                if len(attributes) == 0 or len(internal_faces) == 0:
                    return pd.DataFrame(columns=columns)

                attr_lookup = HdfMesh._reference_line_attribute_lookup(attributes)
                rows = []
                for face_row in internal_faces:
                    reference_line_id = HdfMesh._get_hdf_row_value(
                        face_row, 'Reference Line ID', default=np.nan
                    )
                    if pd.isna(reference_line_id):
                        continue

                    reference_line_id = int(reference_line_id)
                    attr = attr_lookup.get(reference_line_id, {})
                    row_mesh_name = attr.get('mesh_name') or mesh_name
                    if mesh_name is not None and row_mesh_name != mesh_name:
                        continue

                    station_start = HdfMesh._get_hdf_row_value(
                        face_row, 'Station Start', default=np.nan
                    )
                    station_end = HdfMesh._get_hdf_row_value(
                        face_row, 'Station End', default=np.nan
                    )
                    face_id = HdfMesh._get_hdf_row_value(
                        face_row, 'Face Index', default=np.nan
                    )
                    face_length = HdfMesh._get_face_length(
                        hdf_file, row_mesh_name, face_id
                    )

                    station_length = np.nan
                    if np.isfinite(station_start) and np.isfinite(station_end):
                        station_length = float(station_end) - float(station_start)

                    station_fraction = np.nan
                    if np.isfinite(station_length) and np.isfinite(face_length) and face_length > 0:
                        station_fraction = station_length / face_length

                    rows.append({
                        'reference_line_id': reference_line_id,
                        'profile_name': attr.get('profile_name'),
                        'mesh_name': row_mesh_name,
                        'face_id': HdfMesh._safe_int(face_id),
                        'fp_start_index': HdfMesh._safe_int(HdfMesh._get_hdf_row_value(
                            face_row, 'FP Start Index', default=np.nan
                        )),
                        'fp_end_index': HdfMesh._safe_int(HdfMesh._get_hdf_row_value(
                            face_row, 'FP End Index', default=np.nan
                        )),
                        'station_start': float(station_start) if np.isfinite(station_start) else np.nan,
                        'station_end': float(station_end) if np.isfinite(station_end) else np.nan,
                        'station_length': station_length,
                        'face_length': face_length,
                        'station_fraction': station_fraction,
                    })

                return pd.DataFrame(rows, columns=columns)

        except Exception as e:
            logger.error(
                f"Error reading reference line internal faces from {hdf_path}: {str(e)}"
            )
            return pd.DataFrame(columns=columns)

    @staticmethod
    def _manning_conveyance_coefficient(unit_system: str) -> float:
        """Return Manning's conveyance coefficient for a supported unit system."""
        normalized = str(unit_system).strip().lower()
        if normalized in {
            'us',
            'u.s.',
            'us customary',
            'u.s. customary',
            'english',
            'customary',
            'imperial',
        }:
            return 1.486
        if normalized in {'metric', 'si'}:
            return 1.0
        raise ValueError(
            "unit_system must be one of 'us', 'customary', 'english', "
            "'metric', or 'si'"
        )

    @staticmethod
    def _normalize_face_ids(face_ids) -> np.ndarray:
        """Normalize scalar or array-like face IDs to a 1D integer array."""
        face_id_array = np.atleast_1d(np.asarray(face_ids))
        if face_id_array.ndim != 1:
            raise ValueError("face_ids must be a scalar or 1D array-like")
        if face_id_array.size == 0:
            raise ValueError("face_ids must contain at least one face ID")
        return face_id_array.astype(int)

    @staticmethod
    def _normalize_face_water_surface(water_surface, face_count: int) -> np.ndarray:
        """Normalize scalar, per-face, or time-by-face stages to a 2D array."""
        water_surface_array = np.asarray(water_surface, dtype=float)
        if water_surface_array.ndim == 0:
            return np.full((1, face_count), float(water_surface_array), dtype=float)
        if water_surface_array.ndim == 1:
            if water_surface_array.size != face_count:
                raise ValueError(
                    "1D water_surface inputs must have one value per face ID "
                    f"({face_count}); got {water_surface_array.size}"
                )
            return water_surface_array.reshape(1, face_count)
        if water_surface_array.ndim == 2:
            if water_surface_array.shape[1] != face_count:
                raise ValueError(
                    "2D water_surface inputs must have shape time-by-face "
                    f"with {face_count} columns; got {water_surface_array.shape}"
                )
            return water_surface_array
        raise ValueError("water_surface must be scalar, 1D per-face, or 2D time-by-face")

    @staticmethod
    def _build_face_property_lookup(face_property_table: pd.DataFrame) -> Dict[int, pd.DataFrame]:
        """Build a per-face lookup with sorted, de-duplicated elevations."""
        if face_property_table.empty:
            return {}

        lookup = {}
        required = ['Face ID', 'Elevation', 'Area', 'Wetted Perimeter', "Manning's n"]
        missing = [col for col in required if col not in face_property_table.columns]
        if missing:
            raise ValueError(f"Face property table is missing columns: {missing}")

        clean_table = face_property_table.dropna(subset=['Face ID', 'Elevation']).copy()
        for face_id, face_df in clean_table.groupby('Face ID'):
            face_df = (
                face_df
                .sort_values('Elevation')
                .groupby('Elevation', as_index=False)
                .last()
                .reset_index(drop=True)
            )
            lookup[int(face_id)] = face_df
        return lookup

    @staticmethod
    def _interpolate_face_property_table(
        face_table: pd.DataFrame,
        water_surface_values: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """Interpolate face area, wetted perimeter, and Manning's n values."""
        elevations = face_table['Elevation'].to_numpy(dtype=float)
        if elevations.size == 0:
            nan_values = np.full_like(water_surface_values, np.nan, dtype=float)
            return {
                'area': nan_values.copy(),
                'wetted_perimeter': nan_values.copy(),
                'mannings_n': nan_values.copy(),
            }

        area_values = face_table['Area'].to_numpy(dtype=float)
        wetted_perimeter_values = face_table['Wetted Perimeter'].to_numpy(dtype=float)
        mannings_n_values = face_table["Manning's n"].to_numpy(dtype=float)

        area = np.interp(
            water_surface_values,
            elevations,
            area_values,
            left=0.0,
            right=area_values[-1],
        )
        wetted_perimeter = np.interp(
            water_surface_values,
            elevations,
            wetted_perimeter_values,
            left=0.0,
            right=wetted_perimeter_values[-1],
        )
        mannings_n = np.interp(
            water_surface_values,
            elevations,
            mannings_n_values,
            left=mannings_n_values[0],
            right=mannings_n_values[-1],
        )

        dry_mask = water_surface_values < elevations[0]
        area[dry_mask] = 0.0
        wetted_perimeter[dry_mask] = 0.0

        return {
            'area': area,
            'wetted_perimeter': wetted_perimeter,
            'mannings_n': mannings_n,
        }

    @staticmethod
    def _reference_line_attribute_lookup(attributes) -> Dict[int, Dict[str, Any]]:
        """Return reference-line names and mesh names keyed by reference-line ID."""
        lookup = {}
        for idx, attr in enumerate(attributes):
            profile_name = HdfMesh._decode_hdf_value(
                HdfMesh._get_hdf_row_value(attr, 'Name', default='')
            )
            mesh_value = HdfMesh._get_first_hdf_row_value(
                attr, ['SA-2D', 'SA/2D', 'mesh_name', 'Mesh Name'], default=None
            )
            lookup[idx] = {
                'profile_name': profile_name,
                'mesh_name': HdfMesh._decode_hdf_value(mesh_value) if mesh_value is not None else None,
            }
        return lookup

    @staticmethod
    def _get_face_length(hdf_file, mesh_name, face_id) -> float:
        """Read a face length from Faces NormalUnitVector and Length when available."""
        if mesh_name is None or not np.isfinite(face_id):
            return np.nan

        normals_path = f"Geometry/2D Flow Areas/{mesh_name}/Faces NormalUnitVector and Length"
        if normals_path not in hdf_file:
            return np.nan

        normals = hdf_file[normals_path]
        face_index = int(face_id)
        if face_index < 0 or face_index >= normals.shape[0] or normals.shape[1] < 3:
            return np.nan
        return float(normals[face_index, 2])

    @staticmethod
    def _get_first_hdf_row_value(row, names: List[str], default=None):
        """Return the first available named field value from a structured HDF row."""
        for name in names:
            value = HdfMesh._get_hdf_row_value(row, name, default=None)
            if value is not None:
                return value
        return default

    @staticmethod
    def _get_hdf_row_value(row, name: str, default=None):
        """Return a named field from a structured HDF row, or default."""
        dtype_names = getattr(getattr(row, 'dtype', None), 'names', None)
        if dtype_names and name in dtype_names:
            return row[name]
        return default

    @staticmethod
    def _decode_hdf_value(value) -> str:
        """Decode HDF byte/string values with RAS whitespace cleanup."""
        if value is None:
            return None
        try:
            converted = HdfUtils.convert_ras_string(value)
            return converted.strip() if isinstance(converted, str) else converted
        except Exception:
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='ignore').strip()
            return str(value).strip()

    @staticmethod
    def _safe_int(value):
        """Return an int for finite values, otherwise pandas NA."""
        try:
            if pd.isna(value):
                return pd.NA
            return int(value)
        except Exception:
            return pd.NA

    @staticmethod
    @standardize_input(file_type='geom_hdf')
    def get_mesh_cell_property_tables(hdf_path: Path) -> Dict[str, pd.DataFrame]:
        """
        Extract Cell Property Tables for each Cell in all 2D Flow Areas.

        Returns elevation-volume relationships for each cell, which define how
        cell volume changes with water surface elevation. This data is used
        internally by HEC-RAS for 2D hydraulic computations.

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
                - Elevation: water surface elevation (float)
                - Volume: cell volume at that elevation (float)
            Returns an empty dictionary if no 2D areas exist or if there's an error.

        Notes
        -----
        The HDF path for this data is 'Geometry/2D Flow Areas/{mesh_name}/Cells Volume Elevation Info'
        and 'Geometry/2D Flow Areas/{mesh_name}/Cells Volume Elevation Values'.

        Cell surface area is stored separately in 'Cells Surface Area' dataset (one value per cell),
        not in the elevation-volume table.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return {}

                result = {}
                for mesh_name in mesh_area_names:
                    base_path = f"Geometry/2D Flow Areas/{mesh_name}"
                    info_path = f"{base_path}/Cells Volume Elevation Info"
                    values_path = f"{base_path}/Cells Volume Elevation Values"

                    if info_path not in hdf_file or values_path not in hdf_file:
                        logger.warning(f"Cell property tables not found for mesh '{mesh_name}'")
                        result[mesh_name] = pd.DataFrame(columns=['Cell ID', 'Elevation', 'Volume'])
                        continue

                    cell_elevation_info = hdf_file[info_path][()]
                    cell_elevation_values = hdf_file[values_path][()]

                    cell_data = []
                    for cell_id, (start_index, count) in enumerate(cell_elevation_info):
                        cell_values = cell_elevation_values[start_index:start_index+count]
                        for elevation, volume in cell_values:
                            cell_data.append({
                                'Cell ID': cell_id,
                                'Elevation': float(elevation),
                                'Volume': float(volume),
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
    ) -> Optional[Tuple[int, float]]:
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
        Optional[Tuple[int, float]]
            A tuple containing:
            - face_id (int): The ID of the nearest cell face
            - distance (float): The distance to the nearest cell face
            Returns (None, None) if no faces found to search.

        Example
        -------
        >>> cell_faces = HdfMesh.get_mesh_cell_faces(hdf_path)
        >>> face_id, dist = HdfMesh.find_nearest_face((500000, 4000000), cell_faces)
        >>> if face_id is not None:
        ...     print(f"Nearest face: {face_id}, Distance: {dist:.2f}")
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
    ) -> Optional[Tuple[int, float]]:
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
        Optional[Tuple[int, float]]
            A tuple containing:
            - cell_id (int): The ID of the nearest cell
            - distance (float): The distance to the nearest cell center
            Returns (None, None) if no cells found to search.

        Example
        -------
        >>> cell_points = HdfMesh.get_mesh_cell_points(hdf_path)
        >>> cell_id, dist = HdfMesh.find_nearest_cell((500000, 4000000), cell_points)
        >>> if cell_id is not None:
        ...     print(f"Nearest cell: {cell_id}, Distance: {dist:.2f}")
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
            logger.debug("No faces found along profile line with given thresholds")
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
    ) -> Optional[Any]:
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
        Optional[shapely.geometry.LineString]
            A LineString combining all face geometries, or None if faces_gdf is empty
            or fewer than 2 coordinates found.
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

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_mannings_calibration_table(hdf_path: Path) -> Optional[pd.DataFrame]:
        """Retrieve the Manning's n calibration table from a HEC-RAS geometry HDF file.

        Reads the compound dataset at
        ``Geometry/Land Cover (Manning's n)/Calibration Table`` which contains
        land cover names, base Manning's n values, and per-region calibration
        factors.

        Args:
            hdf_path: Path to the HEC-RAS geometry HDF file.

        Returns:
            A DataFrame with columns for each field in the calibration table
            (land cover name, base Manning's n, and one column per calibration
            region), or ``None`` if the dataset does not exist.

        Example
        -------
        >>> df = HdfMesh.get_mannings_calibration_table("model.g01.hdf")
        >>> print(df.columns.tolist()[:3])
        ['Land Cover Name', "Base Manning's n Value", ...]
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                table_path = "Geometry/Land Cover (Manning's n)/Calibration Table"
                if table_path not in hdf_file:
                    logger.warning(f"No Manning's n calibration table found in {hdf_path}")
                    return None

                data = hdf_file[table_path][()]

                df_dict = {}
                for field_name in data.dtype.names:
                    values = data[field_name]
                    if values.dtype.kind == 'S':
                        values = [v.decode('utf-8').strip() for v in values]
                    df_dict[field_name] = values

                return pd.DataFrame(df_dict)

        except Exception as e:
            logger.error(f"Error reading Manning's n calibration table from {hdf_path}: {str(e)}")
            return None
