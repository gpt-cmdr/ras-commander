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
- get_bc_external_faces()  # Returns native BC-line-to-external-face associations.
- get_breaklines()         # Returns 2D mesh area breaklines as a GeoDataFrame.
- get_refinement_regions() # Returns refinement regions as a GeoDataFrame.
- get_reference_lines()    # Returns reference lines as a GeoDataFrame.
- get_reference_points()   # Returns reference points as a GeoDataFrame.



"""
from pathlib import Path
from typing import ClassVar, Optional, Union

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils

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
    _BC_EXTERNAL_FACES_PATH = "Geometry/Boundary Condition Lines/External Faces"
    _BC_ATTRIBUTES_PATH = "Geometry/Boundary Condition Lines/Attributes"
    _BC_EXTERNAL_FACE_COLUMNS: ClassVar[list[str]] = [
        "bc_line_id",
        "bc_line_name",
        "mesh_name",
        "bc_line_type",
        "face_id",
        "fp_start_index",
        "fp_end_index",
        "station_start",
        "station_end",
    ]

    @staticmethod
    def _empty_bc_external_faces(
        status: str,
        *,
        include_geometry: bool = False,
        crs=None,
    ) -> pd.DataFrame:
        """Build a typed empty native-association result."""
        result = pd.DataFrame(
            {
                "bc_line_id": pd.Series(dtype="Int64"),
                "bc_line_name": pd.Series(dtype="string"),
                "mesh_name": pd.Series(dtype="string"),
                "bc_line_type": pd.Series(dtype="string"),
                "face_id": pd.Series(dtype="int64"),
                "fp_start_index": pd.Series(dtype="Int64"),
                "fp_end_index": pd.Series(dtype="Int64"),
                "station_start": pd.Series(dtype="float64"),
                "station_end": pd.Series(dtype="float64"),
            }
        )
        result.attrs.update(
            {
                "association_status": status,
                "dataset_present": status != "absent",
                "authoritative": status != "absent",
                "source_dataset": HdfBndry._BC_EXTERNAL_FACES_PATH,
                "attributes_dataset": HdfBndry._BC_ATTRIBUTES_PATH,
                "face_count": 0,
                "unique_face_count": 0,
                "face_ownership_unique": True,
                "duplicate_face_count": 0,
                "duplicate_face_row_count": 0,
            }
        )
        if include_geometry:
            result = gpd.GeoDataFrame(
                result,
                geometry=gpd.GeoSeries([], dtype="geometry", crs=crs),
                crs=crs,
            )
            result.attrs.update(
                {
                    "association_status": status,
                    "dataset_present": status != "absent",
                    "authoritative": status != "absent",
                    "source_dataset": HdfBndry._BC_EXTERNAL_FACES_PATH,
                    "attributes_dataset": HdfBndry._BC_ATTRIBUTES_PATH,
                    "face_count": 0,
                    "unique_face_count": 0,
                    "face_ownership_unique": True,
                    "duplicate_face_count": 0,
                    "duplicate_face_row_count": 0,
                }
            )
        return result

    @staticmethod
    def _find_structured_field(
        field_names: tuple[str, ...],
        *candidates: str,
    ) -> Optional[str]:
        """Resolve a native structured-array field without punctuation sensitivity."""
        def normalized(value: str) -> str:
            return "".join(character for character in value.lower() if character.isalnum())

        available = {normalized(name): name for name in field_names}
        for candidate in candidates:
            matched = available.get(normalized(candidate))
            if matched is not None:
                return matched
        return None

    @staticmethod
    def _decode_bc_text(value) -> str:
        """Decode and trim one fixed-width HEC-RAS text value."""
        return str(HdfUtils.convert_ras_string(value)).rstrip("\x00 ")

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_bc_external_faces(
        hdf_path: Union[str, Path],
        include_geometry: bool = False,
        validate_unique_faces: bool = True,
    ) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
        """Return native BC-line-to-external-face associations.

        The association is read directly from
        ``Geometry/Boundary Condition Lines/External Faces``.  It is the
        authoritative HEC-RAS native boundary-connectivity result; this method
        does not infer faces from proximity to a BC line.

        Parameters
        ----------
        hdf_path : str or Path
            Path to a HEC-RAS geometry or plan HDF containing geometry data.
        include_geometry : bool, default False
            If ``True``, return a GeoDataFrame whose LineString geometry is
            built from only the natively associated faces.  Selected face
            rows, face-point coordinates, and any intermediate ``Faces
            Perimeter Values`` are indexed directly when the external-face
            endpoints agree with the referenced mesh face.  HEC-RAS can retain
            stale face IDs after remeshing while writing valid native endpoint
            IDs; those rows fall back to endpoint-only segments and are
            reported in ``DataFrame.attrs``.  The full mesh face network is
            never materialized.
        validate_unique_faces : bool, default True
            Require each mesh-local face to be owned by exactly one native BC
            association. Set to ``False`` only for diagnostics: all native rows
            are returned and duplicate counts are reported in ``DataFrame.attrs``.

        Returns
        -------
        pandas.DataFrame or geopandas.GeoDataFrame
            A GeoDataFrame when ``include_geometry=True``, otherwise a
            DataFrame. One row per native external-face association with columns
            ``bc_line_id``, ``bc_line_name``, ``mesh_name``,
            ``bc_line_type``, ``face_id``, ``fp_start_index``,
            ``fp_end_index``, ``station_start``, and ``station_end``.
            ``DataFrame.attrs['association_status']`` is ``'present'``,
            ``'empty'``, or ``'absent'``.  An empty-but-present native dataset
            is therefore distinguishable from geometry that has not been
            preprocessed to create the association.
            When ``include_geometry=True``, the result also has a
            ``geometry`` column and the native HDF projection.  The
            ``topology_match_count`` and ``topology_mismatch_count`` metadata
            distinguish rows that could and could not reuse mesh-face
            perimeter values.

        Raises
        ------
        ValueError
            If the native dataset has an unsupported schema, contains invalid
            BC/face identifiers, or (by default) assigns one external face more
            than once.

        Notes
        -----
        ``BC Line ID`` is the zero-based row index into the adjacent
        ``Attributes`` dataset.  Name, mesh, and type remain nullable when the
        Attributes dataset or an optional attribute field is unavailable.
        """
        with h5py.File(hdf_path, "r") as hdf_file:
            if HdfBndry._BC_EXTERNAL_FACES_PATH not in hdf_file:
                logger.debug(
                    "Native BC external-face association '%s' not found in %s.",
                    HdfBndry._BC_EXTERNAL_FACES_PATH,
                    hdf_path.name,
                )
                return HdfBndry._empty_bc_external_faces(
                    "absent",
                    include_geometry=include_geometry,
                    crs=HdfBase.get_projection(hdf_file) if include_geometry else None,
                )

            native = hdf_file[HdfBndry._BC_EXTERNAL_FACES_PATH][()]
            if len(native) == 0:
                return HdfBndry._empty_bc_external_faces(
                    "empty",
                    include_geometry=include_geometry,
                    crs=HdfBase.get_projection(hdf_file) if include_geometry else None,
                )

            field_names = native.dtype.names
            if not field_names:
                raise ValueError(
                    f"Unsupported unstructured native BC external-face schema in {hdf_path}: "
                    f"{native.dtype}"
                )

            bc_id_field = HdfBndry._find_structured_field(
                field_names,
                "BC Line ID",
                "Boundary Condition Line ID",
                "Boundary Condition ID",
            )
            face_id_field = HdfBndry._find_structured_field(
                field_names,
                "Face Index",
                "Face ID",
            )
            if face_id_field is None:
                raise ValueError(
                    f"Native BC external-face schema in {hdf_path} has no Face Index field; "
                    f"available fields: {field_names}"
                )

            optional_fields = {
                "fp_start_index": HdfBndry._find_structured_field(
                    field_names, "FP Start Index"
                ),
                "fp_end_index": HdfBndry._find_structured_field(
                    field_names, "FP End Index"
                ),
                "station_start": HdfBndry._find_structured_field(
                    field_names, "Station Start"
                ),
                "station_end": HdfBndry._find_structured_field(
                    field_names, "Station End"
                ),
            }

            row_count = len(native)
            result = pd.DataFrame(
                {
                    "bc_line_id": (
                        pd.array(native[bc_id_field], dtype="Int64")
                        if bc_id_field is not None
                        else pd.array([pd.NA] * row_count, dtype="Int64")
                    ),
                    "face_id": np.asarray(native[face_id_field], dtype=np.int64),
                    "fp_start_index": (
                        pd.array(native[optional_fields["fp_start_index"]], dtype="Int64")
                        if optional_fields["fp_start_index"] is not None
                        else pd.array([pd.NA] * row_count, dtype="Int64")
                    ),
                    "fp_end_index": (
                        pd.array(native[optional_fields["fp_end_index"]], dtype="Int64")
                        if optional_fields["fp_end_index"] is not None
                        else pd.array([pd.NA] * row_count, dtype="Int64")
                    ),
                    "station_start": (
                        np.asarray(native[optional_fields["station_start"]], dtype=np.float64)
                        if optional_fields["station_start"] is not None
                        else np.full(row_count, np.nan, dtype=np.float64)
                    ),
                    "station_end": (
                        np.asarray(native[optional_fields["station_end"]], dtype=np.float64)
                        if optional_fields["station_end"] is not None
                        else np.full(row_count, np.nan, dtype=np.float64)
                    ),
                }
            )

            if (result["face_id"] < 0).any():
                invalid = result.loc[result["face_id"] < 0, "face_id"].tolist()[:10]
                raise ValueError(
                    f"Native BC external-face association in {hdf_path} contains negative "
                    f"face IDs: {invalid}"
                )

            result["bc_line_name"] = pd.Series(pd.NA, index=result.index, dtype="string")
            result["mesh_name"] = pd.Series(pd.NA, index=result.index, dtype="string")
            result["bc_line_type"] = pd.Series(pd.NA, index=result.index, dtype="string")

            if HdfBndry._BC_ATTRIBUTES_PATH in hdf_file:
                attributes = hdf_file[HdfBndry._BC_ATTRIBUTES_PATH][()]
                attribute_fields = attributes.dtype.names or ()
                name_field = HdfBndry._find_structured_field(attribute_fields, "Name")
                mesh_field = HdfBndry._find_structured_field(
                    attribute_fields, "SA-2D", "SA/2D", "Mesh Name"
                )
                type_field = HdfBndry._find_structured_field(attribute_fields, "Type")

                known_ids = result["bc_line_id"].dropna().astype(np.int64)
                if len(known_ids) and (
                    (known_ids < 0).any() or (known_ids >= len(attributes)).any()
                ):
                    invalid = known_ids[
                        (known_ids < 0) | (known_ids >= len(attributes))
                    ].unique()[:10].tolist()
                    raise ValueError(
                        f"Native BC external-face association in {hdf_path} references BC Line "
                        f"IDs outside Attributes[0:{len(attributes)}]: {invalid}"
                    )

                valid = result["bc_line_id"].notna()
                if valid.any():
                    ids = result.loc[valid, "bc_line_id"].astype(np.int64).to_numpy()
                    if name_field is not None:
                        result.loc[valid, "bc_line_name"] = [
                            HdfBndry._decode_bc_text(value)
                            for value in attributes[name_field][ids]
                        ]
                    if mesh_field is not None:
                        result.loc[valid, "mesh_name"] = [
                            HdfBndry._decode_bc_text(value)
                            for value in attributes[mesh_field][ids]
                        ]
                    if type_field is not None:
                        result.loc[valid, "bc_line_type"] = [
                            HdfBndry._decode_bc_text(value)
                            for value in attributes[type_field][ids]
                        ]

            # Face indexes are mesh-local.  When the native Attributes join
            # supplies mesh names, audit ownership by (mesh, face); otherwise
            # the conservative fallback is global face-ID uniqueness.
            ownership_columns = (
                ["mesh_name", "face_id"]
                if result["mesh_name"].notna().all()
                else ["face_id"]
            )
            duplicate_ownership = result.duplicated(
                subset=ownership_columns,
                keep=False,
            )
            duplicate_keys = result.loc[
                duplicate_ownership,
                ownership_columns,
            ].drop_duplicates()
            if validate_unique_faces and len(duplicate_keys):
                preview = duplicate_keys.head(10).to_dict("records")
                raise ValueError(
                    f"Native BC external-face association in {hdf_path} does not have unique "
                    f"face ownership; duplicate keys: {preview}"
                )

            result = result[HdfBndry._BC_EXTERNAL_FACE_COLUMNS]
            geometry_source = None
            curved_face_count = 0
            perimeter_value_count = 0
            topology_match_count = 0
            topology_mismatch_count = 0
            if include_geometry:
                if result["mesh_name"].isna().any():
                    raise ValueError(
                        f"Cannot build native BC external-face geometry from {hdf_path} "
                        "without an SA-2D/mesh association for every row"
                    )
                if result[["fp_start_index", "fp_end_index"]].isna().any().any():
                    raise ValueError(
                        f"Cannot build native BC external-face geometry from {hdf_path} "
                        "without FP Start Index and FP End Index for every row"
                    )

                geometries = pd.Series(index=result.index, dtype="object")
                geometry_sources: set[str] = set()
                for mesh_name, mesh_rows in result.groupby("mesh_name", sort=False):
                    mesh_path = f"Geometry/2D Flow Areas/{mesh_name}"
                    face_points_path = f"{mesh_path}/Faces FacePoint Indexes"
                    coordinates_path = f"{mesh_path}/FacePoints Coordinate"
                    perimeter_info_path = f"{mesh_path}/Faces Perimeter Info"
                    perimeter_values_path = f"{mesh_path}/Faces Perimeter Values"
                    if face_points_path not in hdf_file or coordinates_path not in hdf_file:
                        raise ValueError(
                            f"Cannot build native BC external-face geometry for mesh "
                            f"{mesh_name!r} in {hdf_path}; missing {face_points_path!r} "
                            f"or {coordinates_path!r}"
                        )

                    face_points_dataset = hdf_file[face_points_path]
                    coordinates_dataset = hdf_file[coordinates_path]
                    face_ids = mesh_rows["face_id"].to_numpy(dtype=np.int64)
                    if (face_ids >= len(face_points_dataset)).any():
                        invalid = face_ids[face_ids >= len(face_points_dataset)][:10].tolist()
                        raise ValueError(
                            f"Native BC external-face association in {hdf_path} references "
                            f"face IDs outside {face_points_path}[0:{len(face_points_dataset)}]: "
                            f"{invalid}"
                        )

                    # h5py point selections must be sorted and unique. Read only
                    # selected native faces, then restore native-row order. This
                    # also supports repeated faces in diagnostic mode.
                    unique_face_ids, inverse_unique_faces = np.unique(
                        face_ids,
                        return_inverse=True,
                    )
                    selected_face_points = np.asarray(
                        face_points_dataset[unique_face_ids][inverse_unique_faces],
                        dtype=np.int64,
                    )

                    has_perimeter_info = perimeter_info_path in hdf_file
                    has_perimeter_values = perimeter_values_path in hdf_file
                    if has_perimeter_info != has_perimeter_values:
                        raise ValueError(
                            f"Cannot build complete native BC external-face geometry for mesh "
                            f"{mesh_name!r} in {hdf_path}; {perimeter_info_path!r} and "
                            f"{perimeter_values_path!r} must either both exist or both be absent"
                        )
                    if has_perimeter_info:
                        perimeter_info_dataset = hdf_file[perimeter_info_path]
                        perimeter_values_dataset = hdf_file[perimeter_values_path]
                        if len(perimeter_info_dataset) != len(face_points_dataset):
                            raise ValueError(
                                f"Native mesh topology in {hdf_path} has mismatched face and "
                                f"perimeter-info counts for mesh {mesh_name!r}"
                            )
                        unique_perimeter_info = np.asarray(
                            perimeter_info_dataset[unique_face_ids],
                            dtype=np.int64,
                        )
                        selected_perimeter_info = unique_perimeter_info[
                            inverse_unique_faces
                        ]
                        if (
                            selected_perimeter_info.ndim != 2
                            or selected_perimeter_info.shape[1] < 2
                            or (selected_perimeter_info[:, :2] < 0).any()
                            or (
                                selected_perimeter_info[:, 0]
                                + selected_perimeter_info[:, 1]
                                > len(perimeter_values_dataset)
                            ).any()
                        ):
                            raise ValueError(
                                f"Invalid native perimeter ranges in {perimeter_info_path!r} "
                                f"for selected faces in mesh {mesh_name!r}"
                            )
                        perimeter_ranges = selected_perimeter_info[:, :2]
                        curved_face_count += int(
                            (unique_perimeter_info[:, 1] > 0).sum()
                        )
                        perimeter_value_ids = np.unique(
                            np.concatenate(
                                [
                                    np.arange(start, start + count, dtype=np.int64)
                                    for start, count in perimeter_ranges
                                    if count > 0
                                ]
                            )
                            if (perimeter_ranges[:, 1] > 0).any()
                            else np.array([], dtype=np.int64)
                        )
                        selected_perimeter_values = np.asarray(
                            perimeter_values_dataset[perimeter_value_ids],
                            dtype=np.float64,
                        )
                        perimeter_lookup = {
                            int(value_id): selected_perimeter_values[index]
                            for index, value_id in enumerate(perimeter_value_ids)
                        }
                        perimeter_value_count += len(perimeter_value_ids)
                        geometry_sources.add("face_endpoints_and_perimeter_values")
                    else:
                        perimeter_ranges = np.zeros((len(mesh_rows), 2), dtype=np.int64)
                        perimeter_lookup = {}
                        geometry_sources.add("face_endpoints_only")

                    external_face_points = mesh_rows[
                        ["fp_start_index", "fp_end_index"]
                    ].to_numpy(dtype=np.int64)
                    if (
                        (external_face_points < 0).any()
                        or (external_face_points >= len(coordinates_dataset)).any()
                    ):
                        raise ValueError(
                            f"Native BC external-face association in {hdf_path} references "
                            f"face points outside {coordinates_path}[0:{len(coordinates_dataset)}]"
                        )

                    topology_matches = np.all(
                        np.sort(selected_face_points, axis=1)
                        == np.sort(external_face_points, axis=1),
                        axis=1,
                    )
                    mesh_match_count = int(topology_matches.sum())
                    mesh_mismatch_count = int((~topology_matches).sum())
                    topology_match_count += mesh_match_count
                    topology_mismatch_count += mesh_mismatch_count
                    if mesh_mismatch_count:
                        geometry_sources.add("external_face_endpoints")
                        logger.warning(
                            "Using native External Faces endpoints for %d of %d BC faces in "
                            "mesh %r because their face IDs do not match current mesh topology "
                            "in %s.",
                            mesh_mismatch_count,
                            len(mesh_rows),
                            mesh_name,
                            hdf_path.name,
                        )

                    point_ids = np.unique(external_face_points)
                    selected_coordinates = np.asarray(
                        coordinates_dataset[point_ids], dtype=np.float64
                    )
                    point_lookup = {
                        int(point_id): selected_coordinates[index]
                        for index, point_id in enumerate(point_ids)
                    }
                    selected_geometries = []
                    for row_index, (fp_start, fp_end) in enumerate(external_face_points):
                        if not topology_matches[row_index]:
                            selected_geometries.append(
                                LineString(
                                    [
                                        point_lookup[int(fp_start)],
                                        point_lookup[int(fp_end)],
                                    ]
                                )
                            )
                            continue
                        native_start, native_end = selected_face_points[row_index]
                        perimeter_start, perimeter_count = perimeter_ranges[row_index]
                        intermediate = [
                            perimeter_lookup[value_id]
                            for value_id in range(
                                int(perimeter_start),
                                int(perimeter_start + perimeter_count),
                            )
                        ]
                        if fp_start == native_start and fp_end == native_end:
                            ordered_intermediate = intermediate
                        elif fp_start == native_end and fp_end == native_start:
                            ordered_intermediate = list(reversed(intermediate))
                        else:  # Defensive; the unordered equality check above should catch this.
                            raise ValueError(
                                f"Cannot orient native face {face_ids[row_index]} in mesh "
                                f"{mesh_name!r} from its external-face point IDs"
                            )
                        selected_geometries.append(
                            LineString(
                                [
                                    point_lookup[int(fp_start)],
                                    *ordered_intermediate,
                                    point_lookup[int(fp_end)],
                                ]
                            )
                        )
                    geometries.loc[mesh_rows.index] = selected_geometries

                result = gpd.GeoDataFrame(
                    result,
                    geometry=geometries,
                    crs=HdfBase.get_projection(hdf_file),
                )
                geometry_source = "+".join(sorted(geometry_sources))
            result.attrs.update(
                {
                    "association_status": "present",
                    "dataset_present": True,
                    "authoritative": True,
                    "source_dataset": HdfBndry._BC_EXTERNAL_FACES_PATH,
                    "attributes_dataset": HdfBndry._BC_ATTRIBUTES_PATH,
                    "face_count": len(result),
                    "unique_face_count": len(
                        result[ownership_columns].drop_duplicates()
                    ),
                    "face_ownership_unique": len(duplicate_keys) == 0,
                    "duplicate_face_count": len(duplicate_keys),
                    "duplicate_face_row_count": int(duplicate_ownership.sum()),
                    "geometry_source": geometry_source,
                    "curved_face_count": curved_face_count,
                    "perimeter_value_count": perimeter_value_count,
                    "topology_match_count": topology_match_count,
                    "topology_mismatch_count": topology_mismatch_count,
                }
            )
            return result

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
        bc_lines_path = "Geometry/Boundary Condition Lines"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if bc_lines_path not in hdf_file:
                    logger.debug(
                        "Boundary condition lines group '%s' not found in %s.",
                        bc_lines_path,
                        hdf_path.name,
                    )
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
            logger.error(
                "Error reading boundary condition lines from %s (%s): %s",
                hdf_path,
                bc_lines_path,
                str(e),
            )
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

        Notes
        -----
        - Zero-length breaklines are logged and skipped. 
        - Single-point breaklines are logged and skipped.
        - These invalid breaklines should be removed in RASMapper to prevent potential issues.
        """
        breaklines_path = "Geometry/2D Flow Area Break Lines"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if breaklines_path not in hdf_file:
                    logger.debug(
                        "Breaklines group '%s' not found in %s.",
                        breaklines_path,
                        hdf_path.name,
                    )
                    return gpd.GeoDataFrame()

                bl_line_data = hdf_file[breaklines_path]
                attributes = bl_line_data["Attributes"][()]
                
                # Initialize lists to store valid breakline data
                valid_ids = []
                valid_names = []
                valid_spacing_near = []
                valid_spacing_far = []
                valid_near_repeats = []
                valid_protection_radius = []
                valid_geoms = []

                # Track invalid breaklines for summary
                zero_length_count = 0
                single_point_count = 0
                other_error_count = 0

                # Process each breakline
                for idx, (pnt_start, pnt_cnt, part_start, part_cnt) in enumerate(bl_line_data["Polyline Info"][()]):
                    name = HdfUtils.convert_ras_string(attributes["Name"][idx])

                    # Check for zero-length breaklines
                    if pnt_cnt == 0:
                        zero_length_count += 1
                        logger.debug(f"Zero-length breakline found (FID: {idx}, Name: {name})")
                        continue

                    # Check for single-point breaklines
                    if pnt_cnt == 1:
                        single_point_count += 1
                        logger.debug(f"Single-point breakline found (FID: {idx}, Name: {name})")
                        continue

                    try:
                        points = bl_line_data["Polyline Points"][()][pnt_start:pnt_start + pnt_cnt]
                        
                        # Additional validation of points array
                        if len(points) < 2:
                            single_point_count += 1
                            logger.debug(f"Invalid point count in breakline (FID: {idx}, Name: {name})")
                            continue

                        if part_cnt == 1:
                            geom = LineString(points)
                        else:
                            parts = bl_line_data["Polyline Parts"][()][part_start:part_start + part_cnt]
                            geom = MultiLineString([
                                points[part_pnt_start:part_pnt_start + part_pnt_cnt]
                                for part_pnt_start, part_pnt_cnt in parts
                                if part_pnt_cnt > 1  # Skip single-point parts
                            ])
                            # Skip if no valid parts remain
                            if len(geom.geoms) == 0:
                                other_error_count += 1
                                logger.debug(f"No valid parts in multipart breakline (FID: {idx}, Name: {name})")
                                continue

                        valid_ids.append(idx)
                        valid_names.append(name)
                        fields = attributes.dtype.names or ()
                        valid_spacing_near.append(
                            float(attributes["Cell Spacing Near"][idx])
                            if "Cell Spacing Near" in fields
                            else None
                        )
                        valid_spacing_far.append(
                            float(attributes["Cell Spacing Far"][idx])
                            if "Cell Spacing Far" in fields
                            else None
                        )
                        valid_near_repeats.append(
                            int(attributes["Near Repeats"][idx])
                            if "Near Repeats" in fields
                            else 0
                        )
                        valid_protection_radius.append(
                            int(attributes["Protection Radius"][idx])
                            if "Protection Radius" in fields
                            else 0
                        )
                        valid_geoms.append(geom)

                    except Exception as e:
                        other_error_count += 1
                        logger.debug(f"Error processing breakline {idx}: {str(e)}")
                        continue

                # Log summary of invalid breaklines
                total_invalid = zero_length_count + single_point_count + other_error_count
                if total_invalid > 0:
                    logger.debug(
                        f"Breakline processing summary:\n"
                        f"- Zero-length breaklines: {zero_length_count}\n"
                        f"- Single-point breaklines: {single_point_count}\n"
                        f"- Other invalid breaklines: {other_error_count}\n"
                        f"Consider removing these invalid breaklines using RASMapper."
                    )

                # Create GeoDataFrame with valid breaklines
                if not valid_ids:
                    logger.warning(
                        "No valid breaklines found in %s; skipped %d invalid "
                        "breaklines (zero_length=%d, single_point=%d, other=%d).",
                        hdf_path.name,
                        total_invalid,
                        zero_length_count,
                        single_point_count,
                        other_error_count,
                    )
                    return gpd.GeoDataFrame()

                return gpd.GeoDataFrame(
                    {
                        "bl_id": valid_ids,
                        "Name": valid_names,
                        "cell_spacing_near": valid_spacing_near,
                        "cell_spacing_far": valid_spacing_far,
                        "near_repeats": valid_near_repeats,
                        "protection_radius": valid_protection_radius,
                        "geometry": valid_geoms
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file)
                )

        except Exception as e:
            logger.error(
                "Error reading breaklines from %s (%s): %s",
                hdf_path,
                breaklines_path,
                str(e),
            )
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
        refinement_regions_path = "/Geometry/2D Flow Area Refinement Regions"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if refinement_regions_path not in hdf_file:
                    logger.debug(
                        "Refinement regions group '%s' not found in %s.",
                        refinement_regions_path,
                        hdf_path.name,
                    )
                    return gpd.GeoDataFrame()
                rr_data = hdf_file[refinement_regions_path]
                attributes = rr_data["Attributes"][()]
                rr_ids = range(len(attributes))
                names = [HdfUtils.convert_ras_string(name) for name in attributes["Name"]]
                polygon_points = rr_data["Polygon Points"][()]
                polygon_parts = rr_data["Polygon Parts"][()] if "Polygon Parts" in rr_data else None
                geoms = list()
                for pnt_start, pnt_cnt, part_start, part_cnt in rr_data["Polygon Info"][()]:
                    points = polygon_points[pnt_start : pnt_start + pnt_cnt]
                    if part_cnt <= 1:
                        geoms.append(Polygon(points))
                    else:
                        if polygon_parts is None:
                            raise ValueError("Multipart refinement region is missing Polygon Parts")
                        parts = polygon_parts[part_start : part_start + part_cnt]
                        global_offsets = bool(
                            len(parts) and np.all(parts[:, 0] >= pnt_start)
                            and np.all(parts[:, 0] + parts[:, 1] <= pnt_start + pnt_cnt)
                        )
                        polygons = []
                        for part_pnt_start, part_pnt_cnt in parts:
                            # Native collections may index globally or relative
                            # to this feature's point slice.
                            offset = int(part_pnt_start)
                            if global_offsets:
                                offset -= int(pnt_start)
                            ring = points[offset : offset + part_pnt_cnt]
                            if len(ring) != part_pnt_cnt or len(ring) < 3:
                                raise ValueError("Invalid refinement region polygon part")
                            polygons.append(Polygon(ring))
                        # Parts are rings: nested rings are holes, not additional
                        # shells. Containment also preserves islands within holes
                        # and disjoint shells without depending on winding order.
                        containers = [
                            [j for j, outer in enumerate(polygons)
                             if i != j and outer.contains(ring)]
                            for i, ring in enumerate(polygons)
                        ]
                        parents = [
                            min(indices, key=lambda j: polygons[j].area)
                            if indices else None
                            for indices in containers
                        ]
                        shells = [
                            Polygon(
                                ring.exterior.coords,
                                [hole.exterior.coords for j, hole in enumerate(polygons)
                                 if parents[j] == i and len(containers[j]) % 2 == 1],
                            )
                            for i, ring in enumerate(polygons)
                            if len(containers[i]) % 2 == 0
                        ]
                        geoms.append(shells[0] if len(shells) == 1 else MultiPolygon(shells))
                return gpd.GeoDataFrame(
                    {"rr_id": rr_ids, "Name": names, "geometry": geoms},
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )
        except Exception as e:
            logger.error(
                "Error reading refinement regions from %s (%s): %s",
                hdf_path,
                refinement_regions_path,
                str(e),
            )
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
        reference_lines_path = "Geometry/Reference Lines"
        attributes_path = f"{reference_lines_path}/Attributes"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if attributes_path not in hdf_file:
                    logger.debug(
                        "Reference lines attributes group '%s' not found in %s.",
                        attributes_path,
                        hdf_path.name,
                    )
                    return gpd.GeoDataFrame()
                
                attributes = hdf_file[attributes_path][()]
                refline_ids = range(attributes.shape[0])
                v_conv_str = np.vectorize(HdfUtils.convert_ras_string)
                names = v_conv_str(attributes["Name"])
                mesh_names = v_conv_str(attributes["SA-2D"])
                
                try:
                    types = v_conv_str(attributes["Type"])
                except ValueError:
                    logger.debug(
                        "Reference line Type field not found in %s (%s); "
                        "using blank Type values.",
                        hdf_path.name,
                        attributes_path,
                    )
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
            logger.error(
                "Error reading reference lines from %s (%s): %s",
                hdf_path,
                reference_lines_path,
                str(e),
            )
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
        reference_points_path = "Geometry/Reference Points"
        attributes_path = f"{reference_points_path}/Attributes"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if attributes_path not in hdf_file:
                    logger.debug(
                        "Reference points attributes group '%s' not found in %s.",
                        attributes_path,
                        hdf_path.name,
                    )
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
            logger.error(
                "Error reading reference points from %s (%s): %s",
                hdf_path,
                reference_points_path,
                str(e),
            )
            return gpd.GeoDataFrame()

    
