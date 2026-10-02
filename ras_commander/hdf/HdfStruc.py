"""
Class: HdfStruc

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in HdfStruc:
- get_structures()
- get_geom_structures_attrs()
- get_culvert_hydraulics()
- get_storage_area_polygons()
"""
from pathlib import Path
from typing import List, Union

import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from shapely.geometry import (
    LineString,
    Polygon,
)

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils

logger = get_logger(__name__)

class HdfStruc:
    """
    Handles 2D structure geometry data extraction from HEC-RAS HDF files.

    This class provides static methods for extracting and analyzing structure geometries
    and their attributes from HEC-RAS geometry HDF files. All methods are designed to work
    without class instantiation.

    Notes
    -----
    - 1D Structure data should be accessed via the HdfResultsXsec class
    - All methods use @standardize_input for consistent file handling
    - All methods use @log_call for operation logging
    - Returns GeoDataFrames with both geometric and attribute data
    """

    SA_2D_CONN_RESULTS_PATH = (
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
        "SA 2D Area Conn"
    )

    CONNECTION_ATTACHMENT_COLUMNS = [
        "Name",
        "From",
        "To",
        "from_cells",
        "from_faces",
        "to_cells",
        "to_faces",
        "attachment_verified",
        "reason_code",
        "orientation_verified",
        "flux_sign_verified",
        "evidence_paths",
        "details",
        "source_hdf",
        "native_version",
    ]

    @staticmethod
    def _connection_side_attachment(hdf, result_group, area_name, side):
        """Read schema-qualified 6.6 native cell IDs and exact mesh topology."""
        cell_path = f"{result_group.name}/{side} Cells"
        point_path = f"{result_group.name}/Geometric Info/{side} Face Points"
        mesh_path = f"Geometry/2D Flow Areas/{area_name}"
        required = [
            cell_path,
            point_path,
            f"{mesh_path}/Faces FacePoint Indexes",
            f"{mesh_path}/Faces Cell Indexes",
            f"{mesh_path}/Cells Surface Area",
            f"{mesh_path}/FacePoints Coordinate",
        ]
        if any(path not in hdf for path in required):
            return (), (), (), "Native side datasets or active-cell topology absent"
        if any(not isinstance(hdf[path], h5py.Dataset) for path in required):
            return (), (), tuple(required), "Unsupported native dataset objects"
        cells = hdf[cell_path][()]
        points = hdf[point_path][()]
        if (
            cells.ndim != 1
            or points.ndim != 1
            or cells.dtype.kind not in "iu"
            or points.dtype.kind not in "iu"
            or not len(cells)
            or len(points) != len(cells) + 1
        ):
            return (), (), tuple(required), "Unsupported native side dataset layout"
        surface = hdf[f"{mesh_path}/Cells Surface Area"]
        coordinates = hdf[f"{mesh_path}/FacePoints Coordinate"]
        if surface.ndim != 1 or coordinates.ndim != 2 or coordinates.shape[1] != 2:
            return (
                (),
                (),
                tuple(required),
                "Unsupported native active-cell or face-point layout",
            )
        faces = hdf[f"{mesh_path}/Faces FacePoint Indexes"][()]
        adjacency = hdf[f"{mesh_path}/Faces Cell Indexes"][()]
        point_count = len(coordinates)
        if (
            faces.ndim != 2
            or faces.shape[1] != 2
            or adjacency.shape != faces.shape
            or faces.dtype.kind not in "iu"
            or adjacency.dtype.kind not in "iu"
            or np.any(points < 0)
            or np.any(points >= point_count)
            or np.any(faces < 0)
            or np.any(faces >= point_count)
            or np.any(adjacency < -1)
            or np.any(adjacency >= len(surface))
            or np.any(cells < 0)
            or np.any(cells >= len(surface))
        ):
            return (), (), tuple(required), "Invalid native cells or face topology"
        if any(
            not np.isfinite(surface[int(cell)]) or surface[int(cell)] <= 0
            for cell in cells
        ):
            return (
                (),
                (),
                tuple(required),
                "Native attachment references inactive cells",
            )
        lookup = {}
        for face_id, pair in enumerate(faces):
            lookup.setdefault(tuple(sorted(map(int, pair))), []).append(face_id)
        face_ids = []
        for cell, first, second in zip(cells, points[:-1], points[1:]):
            candidates = lookup.get(tuple(sorted((int(first), int(second)))), [])
            matches = [face for face in candidates if int(cell) in adjacency[face]]
            if len(matches) != 1:
                return (
                    tuple(map(int, cells)),
                    (),
                    tuple(required),
                    "Ambiguous or missing native face/cell incidence",
                )
            face_ids.append(matches[0])
        return tuple(map(int, cells)), tuple(face_ids), tuple(required), ""

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def get_connection_attachments(
        hdf_path: str | Path,
        connections_df: pd.DataFrame | None = None,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """Verify both SA/2D ends from native result cell and face receipts.

        Args:
            hdf_path: Geometry or result HDF path (str or Path), or a plan
                number resolved to result HDF by the input decorator.
                Geometry-only preprocessing normally lacks solver receipts.
            connections_df: Expected Name/From/To inventory. Every expected
                connection receives a row, including missing native ones.
            ras_object: Explicit project context for resolving plan numbers.

        Returns:
            DataFrame with Name, From, To, from_cells, from_faces, to_cells,
            to_faces, attachment_verified, reason_code, orientation_verified,
            flux_sign_verified, evidence_paths, details, source_hdf and
            native_version. IDs are zero-based mesh-local native indices;
            repeated segment cell IDs are preserved. No mutation is performed.

        Raises:
            FileNotFoundError: The resolved HDF is absent.
            ValueError: Expected identity columns are missing or input cannot
                be resolved by the HDF decorator.
            OSError: Native HDF cannot be read.

        Notes
        -----
        The supported result layout is qualified against HEC-RAS 6.6 native
        BaldEagleCrkMulti2D output. Other versions fail closed until qualified.
        Storage-area ends, missing/ambiguous identities, absent native datasets,
        and invalid cell/face incidence return
        ``CONNECTION_ATTACHMENT_UNVERIFIED``. No distance or geometric proximity
        establishes attachment. Exact native face-point IDs map to mesh faces;
        cells must be active and incident to those faces. Attachment alone does
        not qualify hydraulic equivalence, flow sign, or head loss. Orientation
        and flux sign remain explicitly unverified by this method.
        """
        columns = HdfStruc.CONNECTION_ATTACHMENT_COLUMNS
        if connections_df is not None and not {"Name", "From", "To"}.issubset(
            connections_df.columns
        ):
            raise ValueError("connections_df requires Name, From, and To columns")
        with h5py.File(hdf_path, "r") as hdf:
            native = []
            attrs_path = "Geometry/Structures/Attributes"
            if attrs_path in hdf:
                attrs = HdfStruc._decode_bytes_columns(
                    pd.DataFrame(hdf[attrs_path][()])
                )
                required = {"Type", "Connection", "US SA/2D", "DS SA/2D"}
                if required.issubset(attrs.columns):
                    native = [
                        {
                            "Name": row["Connection"].strip(),
                            "From": row["US SA/2D"].strip(),
                            "To": row["DS SA/2D"].strip(),
                        }
                        for _, row in attrs.iterrows()
                        if row["Type"].strip() == "Connection"
                    ]
            expected = (
                connections_df[["Name", "From", "To"]].to_dict("records")
                if connections_df is not None
                else native
            )
            version = HdfUtils.convert_ras_string(hdf.attrs.get("File Version", ""))
            file_type = HdfUtils.convert_ras_string(hdf.attrs.get("File Type", ""))
            qualified = (
                str(version).startswith("HEC-RAS 6.6 ")
                and file_type == "HEC-RAS Results"
            )
            result_base = hdf.get(HdfStruc.SA_2D_CONN_RESULTS_PATH)
            rows = []
            for connection in expected:
                record = dict(
                    connection,
                    from_cells=(),
                    from_faces=(),
                    to_cells=(),
                    to_faces=(),
                    attachment_verified=False,
                    reason_code="CONNECTION_ATTACHMENT_UNVERIFIED",
                    orientation_verified=False,
                    flux_sign_verified=False,
                    evidence_paths=(),
                    details="Native result attachment evidence absent",
                    source_hdf=str(hdf_path),
                    native_version=str(version),
                )
                matches = [
                    item for item in native if item["Name"] == connection["Name"]
                ]
                duplicated = (
                    sum(item["Name"] == connection["Name"] for item in expected) != 1
                )
                if duplicated or len(matches) != 1 or matches[0] != connection:
                    record["details"] = (
                        "Missing, ambiguous, or mismatched native connection identity"
                    )
                elif not qualified:
                    record["details"] = (
                        "Native attachment schema is not qualified for this HEC-RAS version"
                    )
                elif result_base is not None:
                    candidates = {
                        connection["Name"],
                        f"{connection['From']} {connection['Name']}",
                    }
                    groups = [
                        result_base[name] for name in candidates if name in result_base
                    ]
                    if len(groups) != 1:
                        record["details"] = (
                            "Missing or ambiguous native result connection group"
                        )
                    else:
                        evidence, problems = [], []
                        for end, side in (("from", "Headwater"), ("to", "Tailwater")):
                            cells, faces, paths, problem = (
                                HdfStruc._connection_side_attachment(
                                    hdf,
                                    groups[0],
                                    connection["From" if end == "from" else "To"],
                                    side,
                                )
                            )
                            record[f"{end}_cells"], record[f"{end}_faces"] = (
                                cells,
                                faces,
                            )
                            evidence.extend(paths)
                            if problem:
                                problems.append(f"{end}: {problem}")
                        record["evidence_paths"] = tuple(evidence)
                        record["details"] = "; ".join(problems)
                        record["attachment_verified"] = not problems
                        if not problems:
                            record["reason_code"] = "CONNECTION_ATTACHMENT_VERIFIED"
                rows.append(record)
            return pd.DataFrame(rows, columns=columns)

    @staticmethod
    def _decode_bytes_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Decode HDF byte-string columns in place and return the DataFrame."""
        for col in df.columns:
            if df[col].dtype.kind in {'S', 'a'}:
                df[col] = df[col].str.decode('utf-8', errors='ignore')
            elif df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda x: x.decode('utf-8', errors='ignore')
                    if isinstance(x, (bytes, np.bytes_))
                    else x
                )
        return df

    @staticmethod
    def _list_sa2d_connections_from_hdf(
        hdf_file: h5py.File,
        hdf_path: Path,
    ) -> List[str]:
        base_path = HdfStruc.SA_2D_CONN_RESULTS_PATH
        if base_path not in hdf_file:
            logger.debug(f"No SA 2D Area Conn data found in {hdf_path.name}")
            return []

        structures = list(hdf_file[base_path].keys())
        logger.debug(
            f"Found {len(structures)} SA/2D connection structures in "
            f"{hdf_path.name}: {structures}"
        )
        return structures
    
    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_structures(hdf_path: Union[Path, str], datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extracts structure data from a HEC-RAS geometry HDF5 file.

        Missing structure layers return an empty frame. A present empty group,
        or one containing only an empty ``Property Tables`` subgroup, returns
        a typed empty GeoDataFrame preserving source CRS/group attributes with
        ``attrs["structure_status"]="empty_placeholder"``. Populated property
        tables, unknown child layouts, missing required datasets in nonempty
        layers and read errors are logged and raised. This is read-only; native
        coordinate/elevation units are unchanged.

        Parameters
        ----------
        hdf_path : Path or str
            Path to the HEC-RAS geometry HDF5 file
        datetime_to_str : bool, optional
            If True, converts datetime objects to ISO format strings, by default False

        Returns
        -------
        GeoDataFrame
            Structure data with columns:
            - Structure ID: unique identifier
            - Geometry: LineString of structure centerline
            - Various attribute columns from the HDF file
            - Profile_Data: list of station/elevation dictionaries
            - Bridge coefficient attributes (if present)
            - Table info attributes (if present)

        Notes
        -----
        - Group-level attributes are stored in GeoDataFrame.attrs['group_attributes']
        - Invalid centerline geometry raises an exception
        - All byte strings are decoded to UTF-8
        - CRS is preserved from the source file
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if "Geometry/Structures" not in hdf:
                    logger.debug(
                        f"No Geometry/Structures group in {hdf_path.name}; "
                        "returning empty GeoDataFrame."
                    )
                    return GeoDataFrame()
                
                # Native geometry may retain an empty Structures placeholder
                # containing only an empty Property Tables group. This is not a
                # partially populated structure layer. Reject every other layout
                # lacking required datasets rather than discarding structures.
                structure_group = hdf["Geometry/Structures"]
                empty_placeholder = len(structure_group) == 0 or (
                    set(structure_group.keys()) == {"Property Tables"}
                    and isinstance(structure_group["Property Tables"], h5py.Group)
                    and len(structure_group["Property Tables"]) == 0
                )
                if empty_placeholder:
                    logger.debug("Empty Geometry/Structures placeholder in %s", hdf_path.name)
                    result = GeoDataFrame(
                        {"Structure ID": pd.Series(dtype="int64")},
                        geometry=[], crs=HdfBase.get_projection(hdf),
                    )
                    result.attrs["group_attributes"] = HdfBase.get_attrs(hdf, "Geometry/Structures")
                    result.attrs["structure_status"] = "empty_placeholder"
                    return result

                # Check if required datasets exist
                required_datasets = [
                    "Geometry/Structures/Attributes",
                    "Geometry/Structures/Centerline Info",
                    "Geometry/Structures/Centerline Points"
                ]
                
                for dataset in required_datasets:
                    if dataset not in hdf:
                        raise ValueError(f"Required structure dataset missing: {dataset}")

                def get_dataset_df(path: str) -> pd.DataFrame:
                    """
                    Converts an HDF5 dataset to a pandas DataFrame.

                    Parameters
                    ----------
                    path : str
                        Dataset path within the HDF5 file

                    Returns
                    -------
                    pd.DataFrame
                        DataFrame containing the dataset values.
                        - For compound datasets, column names match field names
                        - For simple datasets, generic column names (Value_0, Value_1, etc.)
                        - Empty DataFrame if dataset not found

                    Notes
                    -----
                    Automatically decodes byte strings to UTF-8 with error handling.
                    """
                    if path not in hdf:
                        logger.debug(
                            f"Optional structure dataset not found in {hdf_path.name}: {path}"
                        )
                        return pd.DataFrame()
                    
                    data = hdf[path][()]
                    
                    if data.dtype.names:
                        df = pd.DataFrame(data)
                        return HdfStruc._decode_bytes_columns(df)
                    else:
                        # If no named fields, assign generic column names
                        return pd.DataFrame(data, columns=[f'Value_{i}' for i in range(data.shape[1])])

                # Extract relevant datasets
                group_attrs = HdfBase.get_attrs(hdf, "Geometry/Structures")
                struct_attrs = get_dataset_df("Geometry/Structures/Attributes")
                bridge_coef_path = "Geometry/Structures/Bridge Coefficient Attributes"
                table_info_path = "Geometry/Structures/Table Info"
                profile_data_path = "Geometry/Structures/Profile Data"
                bridge_coef_present = bridge_coef_path in hdf
                table_info_present = table_info_path in hdf
                profile_data_present = profile_data_path in hdf
                bridge_coef = get_dataset_df(bridge_coef_path)
                table_info = get_dataset_df(table_info_path)
                profile_data = get_dataset_df(profile_data_path)

                # Assign 'Structure ID' based on index (starting from 1)
                struct_attrs.reset_index(drop=True, inplace=True)
                struct_attrs['Structure ID'] = range(1, len(struct_attrs) + 1)
                logger.debug(f"Assigned Structure IDs: {struct_attrs['Structure ID'].tolist()}")

                # Check if 'Structure ID' was successfully assigned
                if 'Structure ID' not in struct_attrs.columns:
                    logger.error("'Structure ID' column could not be assigned to Structures/Attributes.")
                    return GeoDataFrame()

                # Get centerline geometry
                centerline_info = hdf["Geometry/Structures/Centerline Info"][()]
                centerline_points = hdf["Geometry/Structures/Centerline Points"][()]
                
                # Create LineString geometries for each structure
                geoms = []
                for i in range(len(centerline_info)):
                    start_idx = centerline_info[i][0]  # Point Starting Index
                    point_count = centerline_info[i][1]  # Point Count
                    points = HdfBase.plan_vertex_ordinates(
                        centerline_points[start_idx:start_idx + point_count]
                    )
                    if start_idx < 0 or point_count < 2 or len(points) != point_count:
                        raise ValueError(f"Invalid centerline point range for structure {i}")
                    geoms.append(LineString(points))

                # Create base GeoDataFrame with Structures Attributes and geometries
                struct_gdf = GeoDataFrame(
                    struct_attrs,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Merge Bridge Coefficient Attributes on 'Structure ID'
                if not bridge_coef.empty and 'Structure ID' in bridge_coef.columns:
                    struct_gdf = struct_gdf.merge(
                        bridge_coef,
                        on='Structure ID',
                        how='left',
                        suffixes=('', '_bridge_coef')
                    )
                    logger.debug("Merged Bridge Coefficient Attributes successfully.")
                else:
                    if bridge_coef_present:
                        logger.warning(
                            f"Bridge Coefficient Attributes in {hdf_path.name} "
                            "could not be merged because 'Structure ID' is missing."
                        )
                    else:
                        logger.debug(
                            f"Bridge Coefficient Attributes dataset absent in {hdf_path.name}; "
                            "continuing without bridge coefficient attributes."
                        )

                # Merge Table Info based on the DataFrame index (one-to-one correspondence)
                if not table_info.empty:
                    if len(table_info) != len(struct_gdf):
                        logger.warning(
                            f"Table Info row count ({len(table_info)}) does not match "
                            f"structure count ({len(struct_gdf)}) in {hdf_path.name}; "
                            "skipping Table Info merge."
                        )
                    else:
                        struct_gdf = pd.concat([struct_gdf, table_info.reset_index(drop=True)], axis=1)
                        logger.debug("Merged Table Info successfully.")
                else:
                    if table_info_present:
                        logger.debug(f"Table Info dataset is empty in {hdf_path.name}.")
                    else:
                        logger.debug(f"Table Info dataset is absent in {hdf_path.name}.")

                # Process Profile Data based on Table Info
                if not profile_data.empty and not table_info.empty:
                    # Only process if merge succeeded and columns exist in struct_gdf
                    if ('Centerline Profile (Index)' in struct_gdf.columns and
                        'Centerline Profile (Count)' in struct_gdf.columns):
                        struct_gdf['Profile_Data'] = struct_gdf.apply(
                            lambda row: [
                                {'Station': float(profile_data.iloc[i, 0]),
                                 'Elevation': float(profile_data.iloc[i, 1])}
                                for i in range(
                                    int(row['Centerline Profile (Index)']),
                                    int(row['Centerline Profile (Index)']) + int(row['Centerline Profile (Count)'])
                                )
                            ],
                            axis=1
                        )
                        logger.debug("Processed Profile Data successfully.")
                    else:
                        logger.warning(
                            f"Profile Data in {hdf_path.name} could not be processed; "
                            "expected Table Info columns 'Centerline Profile (Index)' "
                            "and 'Centerline Profile (Count)'."
                        )
                else:
                    missing = []
                    if not profile_data_present:
                        missing.append("Profile Data")
                    elif profile_data.empty:
                        missing.append("non-empty Profile Data")
                    if not table_info_present:
                        missing.append("Table Info")
                    elif table_info.empty:
                        missing.append("non-empty Table Info")
                    logger.debug(
                        f"Skipping Profile Data processing for {hdf_path.name}; "
                        f"missing {', '.join(missing)}."
                    )

                # Convert datetime columns to string if requested
                if datetime_to_str:
                    datetime_cols = struct_gdf.select_dtypes(include=['datetime64']).columns
                    for col in datetime_cols:
                        struct_gdf[col] = struct_gdf[col].dt.isoformat()
                        logger.debug(f"Converted datetime column '{col}' to string.")

                # Ensure all byte strings are decoded (if any remain)
                struct_gdf = HdfStruc._decode_bytes_columns(struct_gdf)

                # Final GeoDataFrame
                logger.debug("Successfully extracted structures GeoDataFrame.")

                # Add group attributes to the GeoDataFrame's attrs['group_attributes']
                struct_gdf.attrs['group_attributes'] = group_attrs

                logger.debug("Successfully extracted structures GeoDataFrame with attributes.")
                
                return struct_gdf

        except Exception as e:
            logger.error(f"Error reading structures from {hdf_path} (Geometry/Structures): {str(e)}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_geom_structures_attrs(hdf_path: Path) -> pd.DataFrame:
        """
        Extracts structure attributes from a HEC-RAS geometry HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file

        Returns
        -------
        pd.DataFrame
            DataFrame containing structure attributes from the Geometry/Structures group.
            Returns empty DataFrame if no structures are found.

        Notes
        -----
        Attributes are extracted from the HDF5 group 'Geometry/Structures'.
        All byte strings in attributes are automatically decoded to UTF-8.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/Structures" not in hdf_file:
                    logger.debug(f"No structures found in the geometry file: {hdf_path}")
                    return pd.DataFrame()
                
                # Get attributes and decode byte strings
                attrs_dict = {}
                for key, value in dict(hdf_file["Geometry/Structures"].attrs).items():
                    if isinstance(value, bytes):
                        attrs_dict[key] = value.decode('utf-8')
                    else:
                        attrs_dict[key] = value
                
                # Create DataFrame with a single row index
                return pd.DataFrame(attrs_dict, index=[0])

        except Exception as e:
            logger.error(f"Error reading geometry structures attributes from {hdf_path}: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_culvert_hydraulics(hdf_path: Path, datetime_to_str: bool = False) -> pd.DataFrame:
        """
        Extract culvert hydraulic properties from geometry HDF.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            If True, converts datetime objects to ISO format strings, by default False

        Returns
        -------
        pd.DataFrame
            Culvert hydraulic data with columns:
            - Structure_ID: unique culvert identifier
            - Flow_Regime: flow regime setting (e.g., "Pressure Flow", "Open Channel")
            - Entrance_Coefficient: entrance loss coefficient (Ke)
            - Exit_Coefficient: exit loss coefficient (Kx)
            - Scale_Factor: culvert scale factor
            - Chart: chart selection for culvert analysis
            - Additional culvert-specific hydraulic attributes

        Notes
        -----
        Returns empty DataFrame if no culverts found in geometry file.
        Includes flow regime setting and all hydraulic coefficients.
        All byte strings are decoded to UTF-8.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check if culvert data exists
                if "Geometry/Structures" not in hdf_file:
                    logger.debug(f"No structures found in geometry file: {hdf_path}")
                    return pd.DataFrame()

                # Get structure attributes to identify culverts
                if "Geometry/Structures/Attributes" not in hdf_file:
                    logger.debug(f"No structure attributes found: {hdf_path}")
                    return pd.DataFrame()

                struct_attrs = hdf_file["Geometry/Structures/Attributes"][()]
                struct_df = pd.DataFrame(struct_attrs)
                struct_df = HdfStruc._decode_bytes_columns(struct_df)

                # Filter for culverts only (assuming Type field exists)
                if 'Type' in struct_df.columns:
                    type_series = struct_df['Type'].astype(str)
                    culvert_df = struct_df[
                        type_series.str.contains('Culvert', case=False, na=False)
                    ].copy()
                else:
                    logger.warning(
                        f"No 'Type' column in structure attributes for {hdf_path.name}; "
                        f"returning all {len(struct_df)} structure row(s)."
                    )
                    culvert_df = struct_df.copy()

                if culvert_df.empty:
                    logger.debug(f"No culverts found in geometry file: {hdf_path}")
                    return pd.DataFrame()

                # Assign Structure ID based on index
                culvert_df.reset_index(drop=True, inplace=True)
                culvert_df['Structure_ID'] = range(1, len(culvert_df) + 1)

                # Extract culvert-specific data if available
                culvert_data_path = "Geometry/Structures/Culvert Data"
                if culvert_data_path in hdf_file:
                    culvert_data = hdf_file[culvert_data_path][()]
                    culvert_data_df = pd.DataFrame(culvert_data)
                    culvert_data_df = HdfStruc._decode_bytes_columns(culvert_data_df)

                    # Merge culvert-specific data with structure attributes
                    # Note: We assume culvert data is in same order as culvert structures
                    if len(culvert_data_df) == len(culvert_df):
                        result_df = pd.concat([culvert_df, culvert_data_df], axis=1)
                    else:
                        logger.warning(
                            f"Culvert Data row count ({len(culvert_data_df)}) does not match "
                            f"culvert structure count ({len(culvert_df)}) in {hdf_path.name}; "
                            "returning structure attributes only."
                        )
                        result_df = culvert_df
                else:
                    logger.warning(
                        f"Culvert structures found in {hdf_path.name}, but "
                        "Geometry/Structures/Culvert Data is absent; returning "
                        "structure attributes only."
                    )
                    result_df = culvert_df

                # Standardize column names to match API specification
                # Map HDF column names to expected names (adjust based on actual HDF structure)
                column_mapping = {
                    'Entrance Loss Coefficient': 'Entrance_Coefficient',
                    'Exit Loss Coefficient': 'Exit_Coefficient',
                    'Scale': 'Scale_Factor',
                    'Chart': 'Chart',
                    # Add more mappings as needed based on actual HDF structure
                }

                result_df = result_df.rename(columns=column_mapping)

                # Convert datetime columns to string if requested
                if datetime_to_str:
                    datetime_cols = result_df.select_dtypes(include=['datetime64']).columns
                    for col in datetime_cols:
                        result_df[col] = result_df[col].dt.isoformat()

                # Ensure all byte strings are decoded (if any remain)
                result_df = HdfStruc._decode_bytes_columns(result_df)

                logger.debug(f"Successfully extracted hydraulic data for {len(result_df)} culverts")
                return result_df

        except Exception as e:
            logger.error(f"Error reading culvert hydraulics from {hdf_path}: {str(e)}")
            return pd.DataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def list_sa2d_connections(hdf_path: Path, *, ras_object=None) -> List[str]:
        """
        List all SA/2D Area Connection structures in HDF results file.

        This includes both breach structures and regular SA/2D connections with
        time series results.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        List[str]
            Names of all SA/2D Area Connection structures with time series results.
            Returns empty list if no SA/2D connections found.

        Examples
        --------
        >>> structures = HdfStruc.list_sa2d_connections("02")
        >>> print(structures)
        ['Laxton_Dam', 'PineCreek#1_Dam', 'US_2DArea_Res2']

        Notes
        -----
        - Not all structures returned have breach capability
        - Use get_sa2d_breach_info() to determine which have "Breaching Variables"
        - Empty list returned if no SA/2D connections in results
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfStruc._list_sa2d_connections_from_hdf(hdf_file, hdf_path)

        except Exception as e:
            logger.error(f"Error listing SA/2D connection structures: {e}")
            return []

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_sa2d_breach_info(hdf_path: Path, *, ras_object=None) -> pd.DataFrame:
        """
        Get information about which SA/2D connection structures have breach capability.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - structure: Structure name
            - has_breach: Boolean, True if "Breaching Variables" dataset exists
            - breach_at_time: Time of breach initiation (if available)
            - breach_at_date: Date/time of breach (if available)
            - centerline_breach: Centerline station for breach (if available)

        Examples
        --------
        >>> info = HdfStruc.get_sa2d_breach_info("02")
        >>> breach_dams = info[info['has_breach']]['structure'].tolist()
        >>> print(f"Breach structures: {breach_dams}")

        Notes
        -----
        - Returns empty DataFrame if no SA/2D connections found
        - Only structures with "Breaching Variables" have has_breach=True
        - Use in conjunction with RasBreach for reading/modifying breach parameters
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                structures = HdfStruc._list_sa2d_connections_from_hdf(hdf_file, hdf_path)

                if not structures:
                    return pd.DataFrame()

                base_path = HdfStruc.SA_2D_CONN_RESULTS_PATH

                info_list = []
                for struct_name in structures:
                    struct_path = f"{base_path}/{struct_name}"
                    breach_var_path = f"{struct_path}/Breaching Variables"

                    info = {'structure': struct_name}

                    # Check if breach variables exist
                    if breach_var_path in hdf_file:
                        info['has_breach'] = True

                        # Extract breach metadata from attributes
                        breach_dataset = hdf_file[breach_var_path]
                        if 'Breach at' in breach_dataset.attrs:
                            breach_at = breach_dataset.attrs['Breach at']
                            info['breach_at_date'] = breach_at.decode('utf-8') if isinstance(breach_at, bytes) else breach_at
                        else:
                            info['breach_at_date'] = None

                        if 'Breach at Time (Days)' in breach_dataset.attrs:
                            info['breach_at_time'] = float(breach_dataset.attrs['Breach at Time (Days)'])
                        else:
                            info['breach_at_time'] = None

                        if 'Centerline Breach' in breach_dataset.attrs:
                            info['centerline_breach'] = float(breach_dataset.attrs['Centerline Breach'])
                        else:
                            info['centerline_breach'] = None
                    else:
                        info['has_breach'] = False
                        info['breach_at_date'] = None
                        info['breach_at_time'] = None
                        info['centerline_breach'] = None

                    info_list.append(info)

                return pd.DataFrame(info_list)

        except Exception as e:
            logger.error(f"Error getting SA/2D breach info: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_storage_area_polygons(hdf_path: Path, *, ras_object=None) -> GeoDataFrame:
        """
        Extract storage area polygon geometry from HEC-RAS HDF file.

        Works on both geometry HDF (.g##.hdf) and plan HDF (.p##.hdf) —
        both contain identical ``/Geometry/Storage Areas/`` data.
        Pass a geometry number string (e.g. ``"12"``) to resolve via
        ``geom_df``; pass a full ``Path`` object to use directly.

        Parameters
        ----------
        hdf_path : Path
            Path to geometry or plan HDF file (str, Path, or geometry number).
        ras_object : RasPrj, optional
            RAS object for multi-project workflows.

        Returns
        -------
        GeoDataFrame
            GeoDataFrame with columns:
            - Name (str): Storage area name
            - geometry (Polygon): Perimeter polygon in project CRS
            - avg_area (float): Average surface area from HDF attributes
            - min_elev (float): Minimum elevation from HDF attributes
            - mode (str): Storage area mode

        Returns empty GeoDataFrame if no storage areas found in file.

        Notes
        -----
        Multi-part polygons (rings/holes) are fully supported via the
        ``Polygon Parts`` dataset; the first ring is the exterior, subsequent
        rings are interiors (holes).
        """
        _empty = GeoDataFrame(
            columns=['Name', 'geometry', 'avg_area', 'min_elev', 'mode'],
            geometry='geometry'
        )
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if 'Geometry/Storage Areas' not in hdf:
                    logger.debug(f"No Storage Areas group found in HDF: {hdf_path}")
                    return _empty

                sa_group = hdf['Geometry/Storage Areas']

                if 'Polygon Points' not in sa_group or 'Polygon Info' not in sa_group:
                    logger.debug(
                        f"Missing Polygon Points or Polygon Info in Storage Areas: {hdf_path}"
                    )
                    return _empty

                polygon_points = sa_group['Polygon Points'][:]   # (total_pts, 2) float64
                polygon_info   = sa_group['Polygon Info'][:]     # (num_sa, 4) int32

                # Polygon Parts for multi-ring (holes) support
                polygon_parts = None
                if 'Polygon Parts' in sa_group:
                    polygon_parts = sa_group['Polygon Parts'][:]  # (total_parts, 2) int32

                # Attributes: Name S16, Mode S16, Avg Area f4, Min Elev f4, ...
                attrs = None
                if 'Attributes' in sa_group:
                    attrs = sa_group['Attributes'][:]

                num_sa = len(polygon_info)
                records = []

                for i in range(num_sa):
                    start      = int(polygon_info[i, 0])  # global start in Polygon Points
                    count      = int(polygon_info[i, 1])  # total points for this SA
                    part_start = int(polygon_info[i, 2])  # start in Polygon Parts
                    part_count = int(polygon_info[i, 3])  # number of rings

                    sa_points = polygon_points[start: start + count]

                    # Build polygon: single-part or multi-part (exterior + holes)
                    if polygon_parts is not None and part_count > 0:
                        sa_parts = polygon_parts[part_start: part_start + part_count]
                        rings = []
                        for p in range(part_count):
                            local_offset = int(sa_parts[p, 0])
                            ring_count   = int(sa_parts[p, 1])
                            rings.append(sa_points[local_offset: local_offset + ring_count])
                        if len(rings) == 1:
                            polygon = Polygon(rings[0])
                        else:
                            polygon = Polygon(rings[0], rings[1:])
                    else:
                        polygon = Polygon(sa_points)

                    # Extract attributes from structured array
                    sa_name  = f"SA_{i}"
                    avg_area = None
                    min_elev = None
                    mode     = None

                    if attrs is not None and i < len(attrs):
                        attr_row   = attrs[i]
                        dt_names   = attr_row.dtype.names or ()

                        if 'Name' in dt_names:
                            raw = attr_row['Name']
                            sa_name = (
                                raw.decode('utf-8', errors='replace').strip()
                                if isinstance(raw, (bytes, np.bytes_))
                                else str(raw).strip()
                            )
                        if 'Avg Area' in dt_names:
                            avg_area = float(attr_row['Avg Area'])
                        if 'Min Elev' in dt_names:
                            min_elev = float(attr_row['Min Elev'])
                        if 'Mode' in dt_names:
                            raw = attr_row['Mode']
                            mode = (
                                raw.decode('utf-8', errors='replace').strip()
                                if isinstance(raw, (bytes, np.bytes_))
                                else str(raw).strip()
                            )

                    records.append({
                        'Name':     sa_name,
                        'geometry': polygon,
                        'avg_area': avg_area,
                        'min_elev': min_elev,
                        'mode':     mode,
                    })

                if not records:
                    return _empty

                gdf = GeoDataFrame(records, geometry='geometry')
                logger.debug(
                    f"Found {len(gdf)} storage area polygon(s) in {hdf_path.name}"
                )
                return gdf

        except Exception as e:
            logger.error(f"Error reading storage area polygons from {hdf_path}: {str(e)}")
            raise
