"""
Class: HdfPipe

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfPipe:
Geometry Retrieval Functions:
- get_pipe_conduits() - Get pipe conduit geometries and attributes
- get_pipe_nodes() - Get pipe node geometries and attributes
- get_pipe_inlets() - Get top and side inlet attributes for pipe nodes
- get_pipe_network() - Get complete pipe network data
- get_pipe_profile() - Get elevation profile for a specific conduit

Results Retrieval Functions:
- get_pipe_network_timeseries() - Get timeseries data for pipe network variables
- get_pipe_network_summary() - Get summary statistics for pipe networks
- extract_timeseries_for_node() - Get timeseries data for a specific node
- extract_timeseries_for_conduit() - Get timeseries data for a specific conduit

Note: All functions use the @standardize_input decorator to validate input paths
and the @log_call decorator for logging function calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import h5py
import numpy as np
import pandas as pd

from .._optional_deps import optional_module, require_module
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..fast_hdf import read_attr, read_attrs, read_typed

gpd = optional_module("geopandas", "Returning GeoDataFrame results from HdfPipe")
xr = optional_module("xarray", "Returning xarray results from HdfPipe")

logger = get_logger(__name__)


_PIPE_GEOMETRY_PREPROCESSOR_ACTION = (
    "Run the HEC-RAS geometry preprocessor, then retry if pipe geometry data is expected."
)
_PIPE_RESULTS_ACTION = (
    "Compute the plan with pipe-network output enabled, or request an available pipe-network variable."
)


def _missing_hdf_object_message(context: str, hdf_path: str, action: str) -> str:
    return f"{context} requires HDF object '{hdf_path}', but it was not found. {action}"


def _format_available_items(items: List[str], max_items: int = 12) -> str:
    if not items:
        return "none"

    shown = items[:max_items]
    suffix = f", ... ({len(items) - max_items} more)" if len(items) > max_items else ""
    return ", ".join(shown) + suffix


def _list_hdf_datasets(group: h5py.Group) -> List[str]:
    datasets = []

    def collect_dataset(name, obj):
        if isinstance(obj, h5py.Dataset):
            datasets.append(name)

    group.visititems(collect_dataset)
    return sorted(datasets)


def _text(value) -> str:
    return value.decode("utf-8").rstrip("\x00") if isinstance(value, bytes) else str(value)


def _network_name(hdf, requested):
    path = "Geometry/Pipe Networks/Attributes"
    if path not in hdf:
        raise KeyError(f"Pipe network selection requires '{path}'")
    names = [_text(row['Name']) for row in read_typed(hdf[path])]
    if not names:
        raise ValueError("No pipe networks in Geometry/Pipe Networks/Attributes")
    name = names[0] if requested is None else str(requested)
    if name not in names:
        raise ValueError(f"Pipe network '{name}' not found. Available networks: {', '.join(names)}")
    if f"Geometry/Pipe Networks/{name}" not in hdf:
        raise KeyError(f"Pipe network geometry group '{name}' is missing")
    return name


# Stored Location is authoritative, never a variable-name or count heuristic.
_PIPE_DOMAINS = {
    "Cell Water Surface": ("cell", "Cell Polygons Info", None),
    "Face Flow": ("face", "Face Polylines Info", None),
    "Face Velocity": ("face", "Face Polylines Info", None),
    "Face Water Surface": ("face", "Face Polylines Info", None),
    "Nodes": ("node", "Node Indices", "node_id"),
    "Pipe Links": ("conduit", "Conduit Indices", "conduit_id"),
}


def _domain(hdf, dataset, network):
    raw = np.asarray(read_attr(dataset, "Location", []))
    if raw.shape not in [(), (1,)] or raw.size != 1:
        raise ValueError(f"{dataset.name}: missing or non-scalar stored Location")
    location = _text(raw.reshape(-1)[0])
    if location not in _PIPE_DOMAINS:
        raise ValueError(f"{dataset.name}: unsupported stored Location {location!r}")
    domain, table, coord = _PIPE_DOMAINS[location]
    identity = hdf[f"Geometry/Pipe Networks/{network}/{table}"]
    if dataset.ndim != 2 or dataset.shape[1] != identity.shape[0]:
        raise ValueError(f"{dataset.name}: stored Location {location!r} contradicts geometry count")
    ids = None
    if coord:
        ids = read_typed(identity)
        if ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(np.unique(ids)) != len(ids):
            raise ValueError(f"{identity.name}: expected unique rank-one integer stored IDs")
    return domain, location, coord, ids


def _part_geometries(info, parts, points, polygon=False):
    from shapely.geometry import LineString, MultiLineString, Polygon
    result = []
    for start, count, part_start, part_count in info:
        start, count, part_start, part_count = map(int, (start, count, part_start, part_count))
        if min(start, count, part_start, part_count) < 0 or start + count > len(points) or part_start + part_count > len(parts):
            raise ValueError("Pipe geometry Info slice is out of bounds")
        feature = points[start:start + count, :2]
        geometries = []
        for offset, size in parts[part_start:part_start + part_count]:
            offset, size = int(offset), int(size)
            if offset < 0 or size < (3 if polygon else 2) or offset + size > count:
                raise ValueError("Pipe geometry Parts slice is out of bounds")
            coords = feature[offset:offset + size]
            geometries.append(Polygon(coords) if polygon else LineString(coords))
        if not geometries:
            result.append(None)
        elif len(geometries) == 1:
            result.append(geometries[0])
        else:
            if polygon:
                raise ValueError("Multipart pipe cell polygon topology is unqualified")
            result.append(MultiLineString(geometries))
    return result


class HdfPipe:
    """
    Static methods for handling pipe network data from HEC-RAS HDF files.

    Contains methods for:
    - Geometry retrieval (nodes, conduits, networks, profiles)
    - Results retrieval (timeseries and summary data)

    All methods use @standardize_input for path validation and @log_call
    """

    # Geometry Retrieval Functions
    
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_conduits(hdf_path: Union[str, Path, int, h5py.File], crs: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Extracts pipe conduit geometries and attributes from HDF5 file.

        Parameters:
            hdf_path: HDF path (str or Path), open h5py.File, or plan number
            crs: Coordinate Reference System override (default: stored projection)

        Returns:
            GeoDataFrame with columns:
            - Attributes from HDF5
            - Polyline: LineString geometries
            - Terrain_Profiles: List of (station, elevation) tuples

        Raises:
            KeyError: If required geometry or one terrain-profile table is missing.
            ValueError: If geometry rows or profile slices are inconsistent.

        Example:
            >>> conduits = HdfPipe.get_pipe_conduits("model.p02.hdf")
        """
        with h5py.File(hdf_path, 'r') as f:
            if '/Geometry/Pipe Conduits' not in f:
                raise KeyError(_missing_hdf_object_message(
                    "Pipe conduit extraction",
                    "/Geometry/Pipe Conduits",
                    _PIPE_GEOMETRY_PREPROCESSOR_ACTION,
                ))

            group = f['/Geometry/Pipe Conduits/']
            
            # --- Read and Process Attributes ---
            for dataset_name in ["Attributes", "Polyline Info", "Polyline Points"]:
                if dataset_name not in group:
                    raise KeyError(_missing_hdf_object_message(
                        "Pipe conduit extraction",
                        f"/Geometry/Pipe Conduits/{dataset_name}",
                        _PIPE_GEOMETRY_PREPROCESSOR_ACTION,
                    ))

            attributes = read_typed(group['Attributes'], slice(None))
            attr_df = pd.DataFrame(attributes)
            
            # Decode byte string fields to UTF-8 strings
            string_columns = attr_df.select_dtypes([object]).columns
            for col in string_columns:
                attr_df[col] = attr_df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
            
            # --- Read Polyline Data ---
            polyline_info = read_typed(group['Polyline Info'], slice(None))  # Shape (132,4) - point_start_idx, point_count, part_start_idx, part_count
            polyline_points = read_typed(group['Polyline Points'], slice(None))  # Shape (396,2) - x,y coordinates
            
            if 'Polyline Parts' not in group:
                raise KeyError("Pipe conduit geometry requires Polyline Parts")
            polyline_geometries = _part_geometries(
                polyline_info, read_typed(group['Polyline Parts']), polyline_points)
            if len(attributes) != len(polyline_geometries):
                raise ValueError("Pipe conduit Attributes/Polyline row mismatch")

            # --- Read Terrain Profiles Data (optional) ---
            attr_df['Polyline'] = polyline_geometries

            has_profile_info = 'Terrain Profiles Info' in group
            has_profile_values = 'Terrain Profiles Values' in group
            if has_profile_info != has_profile_values:
                raise KeyError(
                    "Pipe conduit terrain profiles are partially present: both "
                    "'Terrain Profiles Info' and 'Terrain Profiles Values' are required")
            if has_profile_info and has_profile_values:
                terrain_info = read_typed(group['Terrain Profiles Info'], slice(None))
                terrain_values = read_typed(group['Terrain Profiles Values'], slice(None))
                if len(terrain_info) != len(attr_df):
                    raise ValueError("Pipe conduit Attributes/Terrain Profiles Info row mismatch")
                terrain_coords = list(zip(terrain_values[:, 0], terrain_values[:, 1]))

                terrain_profiles_list: List[List[Tuple[float, float]]] = []
                for i in range(len(terrain_info)):
                    start_idx, count = map(int, terrain_info[i])
                    if start_idx < 0 or count < 0 or start_idx + count > len(terrain_coords):
                        raise ValueError(f"Pipe terrain profile slice is out of bounds for conduit row {i}")
                    segment = terrain_coords[start_idx : start_idx + count]
                    terrain_profiles_list.append(segment)

                attr_df['Terrain_Profiles'] = terrain_profiles_list
            
            # Initialize GeoDataFrame with Polyline geometries
            gdf = gpd.GeoDataFrame(attr_df, geometry='Polyline', crs=crs if crs is not None else HdfBase.get_projection(hdf_path))
            
            return gdf


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_nodes(hdf_path: Union[str, Path, int, h5py.File], crs: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Creates a GeoDataFrame for Pipe Node points and their attributes from an HDF5 file.

        Reads ``Geometry/Pipe Nodes/Attributes`` (compound dtype) and
        ``Geometry/Pipe Nodes/Points`` (x, y, z coordinates), merging them into a
        single GeoDataFrame.

        Args:
            hdf_path (Union[str, Path, int, h5py.File]): HDF path, open file, or plan number.
            crs (Optional[str]): Coordinate Reference System override (default: stored projection).

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing pipe node attributes and
                Point geometries.

        Raises:
            KeyError: If the required pipe node geometry datasets are missing.

        Example:
            >>> nodes_gdf = HdfPipe.get_pipe_nodes("path/to/plan.hdf")
        """
        shapely_geometry = require_module("shapely.geometry", "Returning GeoDataFrame results from HdfPipe")
        Point = shapely_geometry.Point

        with h5py.File(hdf_path, 'r') as f:
            if '/Geometry/Pipe Nodes' not in f:
                raise KeyError(_missing_hdf_object_message(
                    "Pipe node extraction",
                    "/Geometry/Pipe Nodes",
                    _PIPE_GEOMETRY_PREPROCESSOR_ACTION,
                ))

            group = f['/Geometry/Pipe Nodes/']

            # --- Read and Process Attributes ---
            for dataset_name in ["Attributes", "Points"]:
                if dataset_name not in group:
                    raise KeyError(_missing_hdf_object_message(
                        "Pipe node extraction",
                        f"/Geometry/Pipe Nodes/{dataset_name}",
                        _PIPE_GEOMETRY_PREPROCESSOR_ACTION,
                    ))

            attributes = read_typed(group['Attributes'], slice(None))
            attr_df = pd.DataFrame(attributes)

            # Decode byte string fields to UTF-8 strings
            string_columns = attr_df.select_dtypes([object]).columns
            for col in string_columns:
                attr_df[col] = attr_df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)

            # --- Read Points Data ---
            points = read_typed(group['Points'], slice(None))
            # Create Shapely Point geometries
            if len(points) != len(attributes):
                raise ValueError("Pipe node Attributes/Points row mismatch")
            geometries = [Point(xy) for xy in points]

            # --- Combine Attributes and Geometries into GeoDataFrame ---
            gdf = gpd.GeoDataFrame(attr_df, geometry=geometries, crs=crs if crs is not None else HdfBase.get_projection(hdf_path))

            return gdf
        
        


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_inlets(hdf_path: Union[str, Path, int, h5py.File]) -> pd.DataFrame:
        """
        Reads top and side inlet attributes from a HEC-RAS geometry HDF file.

        Reads ``Geometry/Pipe Nodes/Top Inlets/Attributes`` and
        ``Geometry/Pipe Nodes/Side Inlets/Attributes`` and combines them into a
        single DataFrame with an ``inlet_type`` column indicating ``'top'`` or
        ``'side'``.

        Args:
            hdf_path (Union[str, Path, int, h5py.File]): HDF path, open file, or plan number.

        Returns:
            pd.DataFrame: DataFrame containing inlet attributes with an
                ``inlet_type`` column.  Returns an empty DataFrame if neither
                inlet group exists in the HDF file.

        Raises:
            KeyError: If a group exists but its Attributes dataset is missing.

        Example:
            >>> inlets_df = HdfPipe.get_pipe_inlets("path/to/plan.hdf")
        """
        frames = []

        with h5py.File(hdf_path, 'r') as f:
            for inlet_type, group_path in [
                ('top', '/Geometry/Pipe Nodes/Top Inlets/Attributes'),
                ('side', '/Geometry/Pipe Nodes/Side Inlets/Attributes'),
            ]:
                if group_path not in f:
                    if group_path.rsplit("/", 1)[0] in f:
                        raise KeyError(f"Pipe inlet group is missing {group_path}")
                    logger.debug(f"{group_path} not found in HDF file, skipping")
                    continue

                data = read_typed(f[group_path], slice(None))
                df = pd.DataFrame(data)

                # Decode byte string fields to UTF-8 strings
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(
                        lambda x: x.decode('utf-8') if isinstance(x, bytes) else x
                    )

                df['inlet_type'] = inlet_type
                frames.append(df)

        if not frames:
            logger.debug("No inlet attribute data found in HDF file")
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network(hdf_path: Union[str, Path, int, h5py.File], pipe_network_name: Optional[str] = None, crs: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Creates a GeoDataFrame for a pipe network's geometry.

        Parameters:
            hdf_path: HDF path (str or Path), open h5py.File, or plan number
            pipe_network_name: Name of network (uses first if None)
            crs: Coordinate Reference System override (default: stored projection)

        Returns:
            GeoDataFrame containing:
            - Cell polygons (primary geometry)
            - Face polylines
            - Node points resolved through stored Node Indices
            - Associated attributes

        Raises:
            KeyError: If required network geometry is missing.
            ValueError: If the network name, stored IDs, or geometry slices are invalid.

        Example:
            >>> cells = HdfPipe.get_pipe_network("model.p02.hdf")
        """
        with h5py.File(hdf_path, 'r') as f:
            if '/Geometry/Pipe Networks' not in f:
                raise KeyError(_missing_hdf_object_message(
                    "Pipe network extraction",
                    "/Geometry/Pipe Networks",
                    _PIPE_GEOMETRY_PREPROCESSOR_ACTION,
                ))

            pipe_networks_group = f['/Geometry/Pipe Networks/']

            selected_network_name = _network_name(f, pipe_network_name)
            network_group_path = f"/Geometry/Pipe Networks/{selected_network_name}"
            network_group = f[network_group_path]

            required_network_datasets = [
                "Cell Polygons Info",
                "Cell Polygons Parts",
                "Cell Polygons Points",
                "Face Polylines Info",
                "Face Polylines Parts",
                "Face Polylines Points",
                "Node Connectivity Info",
                "Node Connectivity Values",
                "Node Indices",
                "Node Surface Connectivity",
                "Cell Property Table",
                "Cells DS Face Indices Info",
                "Cells DS Face Indices Values",
                "Cells Face Indices Info",
                "Cells Face Indices Values",
                "Cells Minimum Elevations",
                "Cells Node and Conduit IDs",
                "Cells US Face Indices Info",
                "Cells US Face Indices Values",
                "Conduit Indices",
                "Face Property Table",
                "Faces Conduit ID and Stations",
            ]
            missing_network_datasets = [
                f"{network_group_path}/{dataset_name}"
                for dataset_name in required_network_datasets
                if dataset_name not in network_group
            ]
            if missing_network_datasets:
                raise KeyError(
                    "Pipe network extraction found an incomplete pipe network geometry group. "
                    f"Missing: {_format_available_items(missing_network_datasets)}. "
                    f"{_PIPE_GEOMETRY_PREPROCESSOR_ACTION}"
                )
            
            # --- Helper Functions ---
            def decode_bytes(df: pd.DataFrame) -> pd.DataFrame:
                """Decode byte string columns to UTF-8."""
                string_columns = df.select_dtypes([object]).columns
                for col in string_columns:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8') if isinstance(x, bytes) else x)
                return df
            
            def build_polygons(info, parts, points):
                return _part_geometries(info, parts, points, polygon=True)

            def build_multilinestring(info, parts, points):
                return _part_geometries(info, parts, points)

            # --- Read and Process Cell Polygons ---
            cell_polygons_info = read_typed(network_group['Cell Polygons Info'], slice(None))
            cell_polygons_parts = read_typed(network_group['Cell Polygons Parts'], slice(None))
            cell_polygons_points = read_typed(network_group['Cell Polygons Points'], slice(None))
            
            cell_polygons_geometries = build_polygons(cell_polygons_info, cell_polygons_parts, cell_polygons_points)
            
            # --- Read and Process Face Polylines ---
            face_polylines_info = read_typed(network_group['Face Polylines Info'], slice(None))
            face_polylines_parts = read_typed(network_group['Face Polylines Parts'], slice(None))
            face_polylines_points = read_typed(network_group['Face Polylines Points'], slice(None))
            
            face_polylines_geometries = build_multilinestring(face_polylines_info, face_polylines_parts, face_polylines_points)
            
            # Network Node Indices are stored IDs into the global Pipe Nodes rows.
            node_indices = read_typed(network_group['Node Indices'])
            points = read_typed(f['Geometry/Pipe Nodes/Points'])
            if node_indices.dtype.kind not in 'iu' or np.any(node_indices < 0) or np.any(node_indices >= len(points)):
                raise ValueError("Pipe network Node Indices exceed global Pipe Nodes/Points")
            from shapely.geometry import Point
            node_geometries = {int(i): Point(points[i]) for i in node_indices}

            # --- Read and Process Cell Property Table ---
            cell_property_table = read_typed(network_group['Cell Property Table'], slice(None))
            cell_property_df = pd.DataFrame(cell_property_table)
            
            # Decode byte strings if any
            cell_property_df = decode_bytes(cell_property_df)
            
            # --- Read and Process Cells DS Face Indices ---
            cells_ds_face_info = read_typed(network_group['Cells DS Face Indices Info'], slice(None))
            cells_ds_face_values = read_typed(network_group['Cells DS Face Indices Values'], slice(None))
            
            # Create lists of DS Face Indices per cell
            cells_ds_face_indices = []
            for i in range(len(cells_ds_face_info)):
                info = cells_ds_face_info[i]
                start_idx, count = info
                indices = cells_ds_face_values[start_idx : start_idx + count]
                cells_ds_face_indices.append(indices.tolist())
            
            # --- Read and Process Cells Face Indices ---
            cells_face_info = read_typed(network_group['Cells Face Indices Info'], slice(None))
            cells_face_values = read_typed(network_group['Cells Face Indices Values'], slice(None))
            
            # Create lists of Face Indices per cell
            cells_face_indices = []
            for i in range(len(cells_face_info)):
                info = cells_face_info[i]
                start_idx, count = info
                indices = cells_face_values[start_idx : start_idx + count]
                cells_face_indices.append(indices.tolist())
            
            # --- Read and Process Cells Minimum Elevations ---
            cells_min_elevations = read_typed(network_group['Cells Minimum Elevations'], slice(None))
            cells_min_elevations_df = pd.DataFrame(cells_min_elevations, columns=['Minimum_Elevation'])
            
            # --- Read and Process Cells Node and Conduit IDs ---
            cells_node_conduit_ids = read_typed(network_group['Cells Node and Conduit IDs'], slice(None))
            cells_node_conduit_df = pd.DataFrame(cells_node_conduit_ids, columns=['Node_ID', 'Conduit_ID'])
            
            # --- Read and Process Cells US Face Indices ---
            cells_us_face_info = read_typed(network_group['Cells US Face Indices Info'], slice(None))
            cells_us_face_values = read_typed(network_group['Cells US Face Indices Values'], slice(None))
            
            # Create lists of US Face Indices per cell
            cells_us_face_indices = []
            for i in range(len(cells_us_face_info)):
                info = cells_us_face_info[i]
                start_idx, count = info
                indices = cells_us_face_values[start_idx : start_idx + count]
                cells_us_face_indices.append(indices.tolist())
            
            # --- Read and Process Conduit Indices ---
            conduit_indices = read_typed(network_group['Conduit Indices'], slice(None))
            conduit_indices_df = pd.DataFrame(conduit_indices, columns=['Conduit_ID'])
            
            # --- Read and Process Face Property Table ---
            face_property_table = read_typed(network_group['Face Property Table'], slice(None))
            face_property_df = pd.DataFrame(face_property_table)
            
            # Decode byte strings if any
            face_property_df = decode_bytes(face_property_df)
            
            # --- Read and Process Face Conduit ID and Stations ---
            faces_conduit_id_stations = read_typed(network_group['Faces Conduit ID and Stations'], slice(None))
            faces_conduit_df = pd.DataFrame(faces_conduit_id_stations, columns=['ConduitID', 'ConduitStation', 'CellUS', 'CellDS', 'Elevation'])
            
            # --- Read and Process Node Connectivity Info and Values ---
            node_connectivity_info = read_typed(network_group['Node Connectivity Info'], slice(None))
            node_connectivity_values = read_typed(network_group['Node Connectivity Values'], slice(None))
            
            # Create lists of connected nodes per node
            node_connectivity = []
            for i in range(len(node_connectivity_info)):
                info = node_connectivity_info[i]
                start_idx, count = info
                connections = node_connectivity_values[start_idx : start_idx + count]
                node_connectivity.append(connections.tolist())
            
            # --- Read and Process Node Indices ---
            node_indices = read_typed(network_group['Node Indices'], slice(None))
            node_indices_df = pd.DataFrame(node_indices, columns=['Node_ID'])
            
            # --- Read and Process Node Surface Connectivity ---
            node_surface_connectivity = read_typed(network_group['Node Surface Connectivity'], slice(None))
            # Read with native HDF field names, then rename to match downstream code
            node_surface_connectivity_df = pd.DataFrame(node_surface_connectivity)
            node_surface_connectivity_df.columns = ['Node_ID', 'Layer', 'Layer_ID', 'Sublayer_ID']
            
            # --- Combine All Cell-Related Data ---
            cells_df = pd.DataFrame({
                'Cell_ID': range(len(cell_polygons_geometries)),
                'Conduit_ID': cells_node_conduit_df['Conduit_ID'],
                'Node_ID': cells_node_conduit_df['Node_ID'],
                'Minimum_Elevation': cells_min_elevations_df['Minimum_Elevation'],
                'DS_Face_Indices': cells_ds_face_indices,
                'Face_Indices': cells_face_indices,
                'US_Face_Indices': cells_us_face_indices,
                'Cell_Property_Info_Index': cell_property_df['Info Index'],
                # Add other cell properties as needed
            })
            
            if len(cell_property_df) != len(cells_df):
                raise ValueError("Cell Property Table/geometry row mismatch")
            # Property rows align with cells; Info Index addresses a separate lookup table.
            cells_df = pd.concat([cells_df, cell_property_df], axis=1)
            
            # --- Combine All Face-Related Data ---
            faces_df = pd.DataFrame({
                'Face_ID': range(len(face_polylines_geometries)),
                'Conduit_ID': faces_conduit_df['ConduitID'],
                'Conduit_Station': faces_conduit_df['ConduitStation'],
                'Cell_US': faces_conduit_df['CellUS'],
                'Cell_DS': faces_conduit_df['CellDS'],
                'Elevation': faces_conduit_df['Elevation'],
                'Face_Property_Info_Index': face_property_df['Info Index'],
                # Add other face properties as needed
            })
            
            # Merge with face property table
            faces_df = pd.concat([faces_df, face_property_df], axis=1)
            
            # --- Combine All Node-Related Data ---
            nodes_df = pd.DataFrame({
                'Node_ID': node_indices_df['Node_ID'],
                'Connected_Nodes': node_connectivity,
                # Add other node properties as needed
            })
            
            # Merge with node surface connectivity
            nodes_df = nodes_df.merge(node_surface_connectivity_df, on='Node_ID', how='left')
            
            # --- Create GeoDataFrame ---
            # Main DataFrame will be cells with their polygons
            cells_df['Cell_Polygon'] = cell_polygons_geometries
            
            # Add face polylines as a separate column (list of geometries)
            cells_df['Face_Polylines'] = cells_df['Face_Indices'].apply(lambda indices: [face_polylines_geometries[i] for i in indices if 0 <= i < len(face_polylines_geometries)])
            
            # Negative cell node IDs indicate that a cell belongs to a conduit.
            cells_df['Node_Point'] = cells_df['Node_ID'].apply(lambda nid: node_geometries.get(int(nid)))
            
            # Initialize GeoDataFrame with Cell Polygons
            gdf = gpd.GeoDataFrame(cells_df, geometry='Cell_Polygon', crs=crs if crs is not None else HdfBase.get_projection(hdf_path))
            
            # Optionally, add Face Polylines and Node Points as separate columns
            # Note: GeoPandas primarily supports one geometry column, so these are stored as object columns
            gdf['Face_Polylines'] = cells_df['Face_Polylines']
            gdf['Node_Point'] = cells_df['Node_Point']
            
            # You can further expand this GeoDataFrame by merging with faces_df and nodes_df if needed
            
            return gdf
        
        
        
        
        


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_profile(hdf_path: Union[str, Path, int, h5py.File], conduit_id: int) -> pd.DataFrame:
        """
        Extract the profile data for a specific pipe conduit.

        Args:
            hdf_path (Union[str, Path, int, h5py.File]): HDF path, open file, or plan number.
            conduit_id (int): Stored conduit ID (global Geometry/Pipe Conduits row, not network position).

        Returns:
            pd.DataFrame: DataFrame containing the pipe profile data.

        Raises:
            KeyError: If the required datasets are not found in the HDF file.
            IndexError: If the specified conduit_id is out of range.
            ValueError: If the terrain profile slice is out of bounds.

        Example:
            >>> profile = HdfPipe.get_pipe_profile("model.p02.hdf", 0)
        """
        profile_info_path = "/Geometry/Pipe Conduits/Terrain Profiles Info"
        profile_values_path = "/Geometry/Pipe Conduits/Terrain Profiles Values"

        with h5py.File(hdf_path, 'r') as hdf:
            missing_paths = [
                path for path in [profile_info_path, profile_values_path] if path not in hdf
            ]
            if missing_paths:
                raise KeyError(
                    "Pipe conduit terrain profile data is absent from the HDF file. "
                    f"Missing: {_format_available_items(missing_paths)}. "
                    f"{_PIPE_GEOMETRY_PREPROCESSOR_ACTION}"
                )

            terrain_profiles_info = read_typed(hdf[profile_info_path])

            if conduit_id < 0 or conduit_id >= len(terrain_profiles_info):
                raise IndexError(
                    f"conduit_id {conduit_id} is out of range for "
                    f"{len(terrain_profiles_info)} pipe terrain profiles."
                )

            start, count = map(int, terrain_profiles_info[conduit_id])
            if start < 0 or count < 0 or start + count > len(hdf[profile_values_path]):
                raise ValueError("Pipe terrain profile slice is out of bounds")
            profile_values = read_typed(hdf[profile_values_path], slice(start, start+count))

            return pd.DataFrame(profile_values, columns=['Station', 'Elevation'])
        
        
   









# RESULTS FUNCTIONS: 

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network_summary(hdf_path: Union[str, Path, int, h5py.File], pipe_network_name: Optional[str] = None) -> pd.DataFrame:
        """Read literal Base summary rows and pipe-network volume-accounting attributes.

        Select the first geometry network when pipe_network_name is omitted.
        Return long-form columns network, source, path, row, location, row_variable,
        units, value. Each stored summary row is retained; a one-row minimum never
        receives an invented time row. Labels/units are literal source metadata,
        even where the file's labels appear inconsistent. Summary datasets without
        Location do not claim a node/conduit domain or stored-ID mapping.
        Volume-accounting attributes use null row/location/units: the group's
        'Vol Accounting in' attribute (itself returned as a row) names the volume
        unit and is not applied per attribute (e.g. 'Error Percent' is a
        percentage). DataFrame.attrs retains
        source shapes and complete dataset/group attributes. Missing both sources
        raises KeyError; malformed present datasets raise ValueError. A legacy
        Summary/Pipe Network table without geometry identities retains its original
        DataFrame shape when no network name is requested.

        Args:
            hdf_path: HDF path (str or Path), open h5py.File, or plan number.
            pipe_network_name: Network name; defaults to the first geometry network.

        Returns:
            pd.DataFrame: Literal summary rows and volume-accounting attributes.

        Raises:
            KeyError: If the network or both summary sources are missing.
            ValueError: If a stored summary or volume attribute is malformed.

        Example:
            >>> summary = HdfPipe.get_pipe_network_summary("model.p02.hdf")
        """
        records, metadata = [], {}
        with h5py.File(hdf_path, 'r') as hdf:
            legacy = "Results/Unsteady/Summary/Pipe Network"
            if "Geometry/Pipe Networks/Attributes" not in hdf:
                if legacy in hdf and pipe_network_name is None:
                    # Retain the historical table contract when that dataset exists.
                    return pd.DataFrame(read_typed(hdf[legacy]))
                raise KeyError("No pipe-network summary output with geometry network identities")
            name = _network_name(hdf, pipe_network_name)
            base = f"Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/Pipe Networks/{name}"
            volume = f"Results/Unsteady/Summary/Volume Accounting/Volume Accounting Pipe Networks/{name}"
            if base not in hdf and volume not in hdf:
                raise KeyError(f"No pipe-network summary or volume accounting for {name!r}")
            if base in hdf:
                for variable in _list_hdf_datasets(hdf[base]):
                    ds = hdf[f"{base}/{variable}"]
                    if ds.ndim != 2 or ds.shape[0] not in (1, 2) or ds.dtype.kind not in 'iuf':
                        raise ValueError(f"{ds.name}: unqualified pipe summary shape/type {ds.shape}")
                    attrs = read_attrs(ds);metadata[ds.name] = dict(shape=ds.shape, attributes=attrs)
                    labels = np.asarray(attrs.get('Rows Variables', [])).reshape(-1)
                    units = np.asarray(attrs.get('Units', [])).reshape(-1)
                    values = read_typed(ds)
                    for row in range(ds.shape[0]):
                        for col, value in enumerate(values[row]):
                            records.append(dict(network=name, source='summary', path=ds.name,
                                row=row, location=col, row_variable=_text(labels[row]) if row < len(labels) else None,
                                units=_text(units[row]) if row < len(units) else None, value=value))
            if volume in hdf:
                attrs = read_attrs(hdf[volume]);metadata[hdf[volume].name] = dict(attributes=attrs)
                for key, value in attrs.items():
                    if np.asarray(value).ndim != 0:
                        raise ValueError(f"{volume}: non-scalar volume attribute {key!r}")
                    records.append(dict(network=name, source='volume_accounting', path=hdf[volume].name,
                        row=None, location=None, row_variable=key, units=None,
                        value=_text(value) if isinstance(value, bytes) else value))
        df = pd.DataFrame(records, columns=['network', 'source', 'path', 'row', 'location', 'row_variable', 'units', 'value'])
        df.attrs['source_metadata'] = metadata
        df.attrs['pipe_network'] = name
        return df


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def extract_timeseries_for_node(plan_hdf_path: Union[str, Path, int, h5py.File], node_id: int, pipe_network_name: Optional[str] = None,
                                    output_block: str = "DSS Hydrograph Output", *,
                                    ras_object=None) -> Dict[str, xr.DataArray]:
        """
        Extract time series data for a specific node.
        
        Parameters:
        -----------
        plan_hdf_path : str, Path, int or h5py.File
            Results HDF path, open file, or plan number resolved against ras_object.
        node_id : int
            Stored node ID from Node Indices, not a network column position.
        pipe_network_name : Optional[str]
            Network name (default: first geometry network).
        output_block : str
            Base Output or DSS Hydrograph Output (default).
        ras_object : RasPrj, optional
            Project used to resolve plan numbers; defaults to the global project.
            
        Returns:
        --------
        Dict[str, xr.DataArray]: Dictionary containing time series data for:
            - Depth
            - Drop Inlet Flow
            - Water Surface

        Raises:
            KeyError: If the stored node ID, network, or variable is missing.
            ValueError: If the output block, domain, or timestamps are invalid.

        Example:
            >>> series = HdfPipe.extract_timeseries_for_node("model.p02.hdf", 121)
        """
        node_variables = ["Nodes/Depth", "Nodes/Drop Inlet Flow", "Nodes/Water Surface"]
        node_data = {}

        for variable in node_variables:
            data = HdfPipe.get_pipe_network_timeseries(plan_hdf_path, variable=variable,
                pipe_network_name=pipe_network_name, output_block=output_block, ras_object=ras_object)
            try:
                node_data[variable] = data.swap_dims({"location": "node_id"}).sel(node_id=node_id)
            except KeyError as exc:
                raise KeyError(
                    f"Pipe node id {node_id} was not found in timeseries variable '{variable}'."
                ) from exc

        return node_data

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def extract_timeseries_for_conduit(plan_hdf_path: Union[str, Path, int, h5py.File], conduit_id: int, pipe_network_name: Optional[str] = None,
                                    output_block: str = "DSS Hydrograph Output", *,
                                    ras_object=None) -> Dict[str, xr.DataArray]:
        """
        Extract time series data for a specific conduit.
        
        Parameters:
        -----------
        plan_hdf_path : str, Path, int or h5py.File
            Results HDF path, open file, or plan number resolved against ras_object.
        conduit_id : int
            Stored conduit ID from Conduit Indices, not a network column position.
        pipe_network_name : Optional[str]
            Network name (default: first geometry network).
        output_block : str
            Base Output or DSS Hydrograph Output (default).
        ras_object : RasPrj, optional
            Project used to resolve plan numbers; defaults to the global project.
            
        Returns:
        --------
        Dict[str, xr.DataArray]: Dictionary containing time series data for:
            - Pipe Flow (US/DS)
            - Velocity (US/DS)

        Raises:
            KeyError: If the stored conduit ID, network, or variable is missing.
            ValueError: If the output block, domain, or timestamps are invalid.

        Example:
            >>> series = HdfPipe.extract_timeseries_for_conduit("model.p02.hdf", 85)
        """
        conduit_variables = ["Pipes/Pipe Flow DS", "Pipes/Pipe Flow US",
                            "Pipes/Vel DS", "Pipes/Vel US"]
        conduit_data = {}

        for variable in conduit_variables:
            data = HdfPipe.get_pipe_network_timeseries(plan_hdf_path, variable=variable,
                pipe_network_name=pipe_network_name, output_block=output_block, ras_object=ras_object)
            try:
                conduit_data[variable] = data.swap_dims({"location": "conduit_id"}).sel(conduit_id=conduit_id)
            except KeyError as exc:
                raise KeyError(
                    f"Pipe conduit id {conduit_id} was not found in timeseries variable '{variable}'."
                ) from exc

        return conduit_data


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_pipe_network_timeseries(
        hdf_path: Union[str, Path, int, h5py.File],
        variable: str,
        pipe_network_name: Optional[str] = None,
        output_block: str = "DSS Hydrograph Output",
    ) -> xr.DataArray:
        """
        Extracts timeseries data for a pipe network variable.

        Parameters:
            hdf_path: HDF path (str or Path), open h5py.File, or plan number
            variable: Variable name to extract. Valid options:
                - Cell: Courant, Water Surface
                - Face: Flow, Velocity, Water Surface
                - Pipes: Pipe Flow (DS/US), Vel (DS/US)
                - Nodes: Depth, Drop Inlet Flow, Water Surface
            pipe_network_name: Pipe network to read. When omitted, the first
                Geometry/Pipe Networks/Attributes entry is selected.
            output_block: Base Output or DSS Hydrograph Output. DSS remains the
                default for compatibility. Timestamps come only from that block;
                absent or mismatched timestamps raise ValueError.
                location remains positional; node_id/conduit_id are stored IDs.
                attrs records domain, stored_location, network and output_block.

        Returns:
            xarray.DataArray with dimensions (time, location).

        Raises:
            KeyError: If the network geometry or requested results are missing.
            ValueError: If the variable, output block, domain, or timestamps are invalid.

        Example:
            >>> depth = HdfPipe.get_pipe_network_timeseries(
            ...     "model.p02.hdf", "Nodes/Depth", output_block="Base Output")
        """
        valid_variables = [
            "Cell Courant", "Cell Water Surface", "Face Flow", "Face Velocity",
            "Face Water Surface", "Pipes/Pipe Flow DS", "Pipes/Pipe Flow US",
            "Pipes/Vel DS", "Pipes/Vel US", "Nodes/Depth", "Nodes/Drop Inlet Flow",
            "Nodes/Water Surface"
        ]

        if variable not in valid_variables:
            raise ValueError(f"Invalid variable. Must be one of: {', '.join(valid_variables)}")

        if output_block not in ("Base Output", "DSS Hydrograph Output"):
            raise ValueError("output_block must be 'Base Output' or 'DSS Hydrograph Output'")
        with h5py.File(hdf_path, 'r') as hdf:
            if "Geometry/Pipe Networks/Attributes" not in hdf:
                root = f"Results/Unsteady/Output/Output Blocks/{output_block}/Unsteady Time Series/Pipe Networks"
                available = _list_hdf_datasets(hdf[root]) if root in hdf else []
                raise KeyError(f"Cannot qualify pipe variable '{variable}': geometry network Attributes absent. "
                    f"Available result datasets: {_format_available_items(available)}. {_PIPE_RESULTS_ACTION}")
            network_name = _network_name(hdf, pipe_network_name)
            base = f"Results/Unsteady/Output/Output Blocks/{output_block}/Unsteady Time Series"
            path = f"{base}/Pipe Networks/{network_name}/{variable}"
            if path not in hdf:
                raise KeyError(f"Pipe timeseries dataset '{path}' not found. {_PIPE_RESULTS_ACTION}")
            dataset = hdf[path]
            domain, location, coord, ids = _domain(hdf, dataset, network_name)
            time = None
            for stamp, parse in [("Time Date Stamp (ms)", HdfUtils.parse_ras_datetime_ms),
                                 ("Time Date Stamp", HdfUtils.parse_ras_datetime)]:
                if f"{base}/{stamp}" in hdf:
                    ds = hdf[f"{base}/{stamp}"]
                    if ds.shape != (dataset.shape[0],):
                        raise ValueError(f"{path}: {output_block} timestamp count/shape mismatch")
                    time = [parse(_text(x)) for x in read_typed(ds)]
                    break
            if time is None:
                raise ValueError(f"{path}: no timestamps in selected output block")
            if f"{base}/Time" in hdf and hdf[f"{base}/Time"].shape != (dataset.shape[0],):
                raise ValueError(f"{path}: selected block Time row mismatch")
            coords = {'time': time, 'location': np.arange(dataset.shape[1])}
            if coord:
                coords[coord] = ('location', ids)
            da = xr.DataArray(read_typed(dataset), dims=['time', 'location'], coords=coords, name=variable)
            da.attrs.update(units=_text(read_attr(dataset, 'Units', b'')), variable=variable,
                domain=domain, stored_location=location, pipe_network=network_name, output_block=output_block)
            return da
