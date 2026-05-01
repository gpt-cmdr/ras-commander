"""
Class: HdfResultsMesh

Attribution: A substantial amount of code in this file is sourced or derived
from the https://github.com/fema-ffrd/rashdf library,
released under MIT license and Copyright (c) 2024 fema-ffrd

The file has been forked and modified for use in RAS Commander.

-----

All methods in this class are static and designed to be used without instantiation.

## xarray Return Type Conventions

This module uses xarray data structures for efficient multi-dimensional array operations.
Understanding when each return type is used:

**xr.DataArray - Single Variable**:
- Use when returning a SINGLE variable with labeled dimensions
- Example: Water surface elevation time series for one mesh
- Methods: get_mesh_timeseries(), _get_mesh_timeseries_output()
- Structure: Single variable with dimensions (time, cell_id/face_id)

**xr.Dataset - Multiple Variables (Single Mesh)**:
- Use when returning MULTIPLE variables for ONE mesh area
- Example: Face velocity + face flow for a mesh
- Methods: get_mesh_faces_timeseries(), get_boundary_conditions_timeseries()
- Structure: Multiple data variables sharing common dimensions

**Dict[str, xr.Dataset] - Multiple Mesh Areas**:
- Use when returning data for MULTIPLE mesh areas
- Example: All variables for all mesh areas in a model
- Methods: get_mesh_cells_timeseries(), _get_mesh_cells_timeseries_output()
- Structure: Dictionary with mesh names as keys, Dataset for each mesh
- Allows different meshes to have different dimensions

**pandas DataFrame/GeoDataFrame - Summary/Spatial Data**:
- Use for summary statistics (max/min) with geometry
- Methods: get_mesh_max_ws(), get_mesh_min_ws(), get_mesh_max_iter()
- Structure: Tabular data with spatial reference

## Public Functions
- get_mesh_summary(): Get summary output data for a variable → gpd.GeoDataFrame
- get_mesh_timeseries(): Get timeseries for one mesh/variable → xr.DataArray
- get_mesh_faces_timeseries(): Get face variables for one mesh → xr.Dataset
- get_mesh_cells_timeseries(): Get cell timeseries for all meshes → Dict[str, xr.Dataset]
- get_mesh_last_iter(): Get last iteration count → pd.DataFrame
- get_mesh_max_ws(): Get maximum water surface → gpd.GeoDataFrame
- get_mesh_min_ws(): Get minimum water surface → gpd.GeoDataFrame
- get_mesh_max_face_v(): Get maximum face velocity → pd.DataFrame
- get_mesh_min_face_v(): Get minimum face velocity → pd.DataFrame
- get_mesh_max_ws_err(): Get maximum water surface error → pd.DataFrame
- get_mesh_max_iter(): Get maximum iteration count → gpd.GeoDataFrame
- get_boundary_conditions_timeseries(): Get all BC timeseries → xr.Dataset

## Private Functions
- _get_mesh_timeseries_output_path(): Get HDF path for timeseries output
- _get_mesh_cells_timeseries_output(): Internal handler for cell timeseries
- _get_mesh_timeseries_output(): Internal handler for mesh timeseries
- _get_mesh_timeseries_output_values_units(): Get values and units
- _get_available_meshes(): Get list of available meshes in HDF
- get_mesh_summary_output(): Internal handler for summary output
- get_mesh_summary_output_group(): Get HDF group for summary output

The class works with HEC-RAS version 6.0+ plan HDF files and uses HdfBase and
HdfUtils for common operations. Methods use @log_call decorator for logging and
@standardize_input decorator to handle different input types.









"""

import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
import h5py
from typing import Union, List, Optional, Dict, Any, Tuple
from .HdfMesh import HdfMesh
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import setup_logging, get_logger
import geopandas as gpd

logger = get_logger(__name__)

class HdfResultsMesh:
    """
    Handles mesh-related results from HEC-RAS HDF files.

    Provides methods to extract and analyze:
    - Mesh summary outputs
    - Timeseries data
    - Water surface elevations
    - Velocities
    - Error metrics

    Works with HEC-RAS 6.0+ plan HDF files.
    """
    MESH_CELL_TIME_SERIES_OUTPUT_VARS = [
        "Water Surface", "Depth", "Velocity", "Velocity X", "Velocity Y",
        "Froude Number", "Courant Number", "Shear Stress", "Bed Elevation",
        "Precipitation Rate", "Infiltration Rate", "Evaporation Rate",
        "Percolation Rate", "Groundwater Elevation", "Groundwater Depth",
        "Groundwater Flow", "Groundwater Velocity", "Groundwater Velocity X",
        "Groundwater Velocity Y"
    ]

    MESH_FACE_TIME_SERIES_OUTPUT_VARS = [
        "Face Flow", "Face Velocity", "Face Water Surface", "Face Area",
        "Face Manning's n", "Face Courant", "Face Cumulative Volume",
        "Face Eddy Viscosity", "Face Flow Period Average",
        "Face Friction Term", "Face Pressure Gradient Term",
        "Face Shear Stress", "Face Tangential Velocity"
    ]

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_summary(hdf_path: Path, var: str, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (Path): Path to the HDF file
            mesh_name (str): Name of the mesh
            var (str): Variable to retrieve (see valid options below)
            truncate (bool): Whether to truncate trailing zeros (default True)

        Returns:
            xr.DataArray: DataArray with dimensions:
                - time: Timestamps
                - face_id/cell_id: IDs for faces/cells
                And attributes:
                - units: Variable units
                - mesh_name: Name of mesh
                - variable: Variable name

        Valid variables include:
            "Water Surface", "Face Velocity", "Cell Velocity X"...
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, var, round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_summary: {str(e)}")
            logger.error(f"Variable: {var}")
            raise ValueError(f"Failed to get summary output: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_timeseries(hdf_path: Path, mesh_name: str, var: str, truncate: bool = True) -> xr.DataArray:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (Path): Path to the HDF file
            mesh_name (str): Name of the mesh
            var (str): Variable to retrieve (see valid options below)
            truncate (bool): Whether to truncate trailing zeros (default True)

        Returns:
            xr.DataArray: **Single variable** time series data.
                Use DataArray when extracting ONE variable for ONE mesh.

                Dimensions:
                    - time: Timestamps
                    - face_id/cell_id: IDs for faces/cells

                Attributes:
                    - units: Variable units
                    - mesh_name: Name of mesh
                    - variable: Variable name

                When to use: Single variable extraction for focused analysis.
                For multiple variables, use get_mesh_cells_timeseries() → Dict[str, Dataset].

        Valid variables include:
            "Water Surface", "Face Velocity", "Cell Velocity X"...
        """
        with h5py.File(hdf_path, 'r') as hdf_path:
            return HdfResultsMesh._get_mesh_timeseries_output(hdf_path, mesh_name, var, truncate)

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_profile_line_flow_timeseries(
        hdf_path: Path,
        line_name: str,
        mesh_name: Optional[str] = None,
        profile_lines_path: Optional[Union[str, Path]] = None,
        direction: str = "absolute",
        truncate: bool = False,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Return a flow time series across a RAS Mapper profile/reference line.

        The method first looks for native HEC-RAS reference-line internal-face
        metadata in the plan HDF. If no matching native reference line is found,
        it reads the RAS Mapper Profile Lines feature file and uses
        ``HdfMesh.get_faces_along_profile_line()`` to select mesh faces
        geometrically. Face flows are read through ``get_mesh_timeseries()``.

        Parameters
        ----------
        hdf_path : Path
            Plan HDF path, plan number, or other input accepted by
            ``@standardize_input(file_type='plan_hdf')``.
        line_name : str
            Profile/reference line name to extract.
        mesh_name : Optional[str], optional
            2D flow area name. Required when the line resolves to more than one
            mesh area.
        profile_lines_path : Optional[Union[str, Path]], optional
            Explicit RAS Mapper Profile Lines feature path. If omitted, the
            method attempts to use ``ras_object.rasmap_df.profile_lines_path``.
        direction : str, default "absolute"
            ``"absolute"`` sums absolute face flows to avoid face-normal sign
            cancellation. ``"signed"`` preserves native HEC-RAS face-flow signs;
            orientation is controlled by the underlying face normals.
        truncate : bool, default False
            Passed to ``get_mesh_timeseries()``.
        ras_object : Optional[Any], optional
            RAS project object used for plan-number and rasmap path resolution.

        Returns
        -------
        pd.DataFrame
            Columns: ``time``, ``flow``, ``line_name``, ``mesh_name``,
            ``direction``, ``face_count``, and ``selection_source``.
        """
        direction = HdfResultsMesh._normalize_profile_line_direction(direction)
        selected_faces, resolved_mesh_name, selection_source = (
            HdfResultsMesh._resolve_profile_line_faces(
                hdf_path=hdf_path,
                line_name=line_name,
                mesh_name=mesh_name,
                profile_lines_path=profile_lines_path,
                ras_object=ras_object,
            )
        )

        face_ids = HdfResultsMesh._unique_int_values(selected_faces['face_id'])
        if not face_ids:
            raise ValueError(f"No valid face IDs resolved for profile line '{line_name}'.")

        face_flow = HdfResultsMesh.get_mesh_timeseries(
            hdf_path,
            resolved_mesh_name,
            "Face Flow",
            truncate=truncate,
        )
        if "face_id" not in face_flow.coords:
            raise ValueError(
                f"Face Flow output for mesh '{resolved_mesh_name}' does not include face_id coordinates."
            )

        available_face_ids = {
            int(face_id) for face_id in face_flow.coords["face_id"].values.tolist()
        }
        missing_face_ids = [
            face_id for face_id in face_ids if face_id not in available_face_ids
        ]
        if missing_face_ids:
            preview = missing_face_ids[:10]
            more = "" if len(missing_face_ids) <= len(preview) else (
                f" and {len(missing_face_ids) - len(preview)} more"
            )
            raise ValueError(
                f"Face Flow output for mesh '{resolved_mesh_name}' is missing selected "
                f"face IDs: {preview}{more}"
            )

        selected_flow = face_flow.sel(face_id=face_ids)
        values = np.asarray(selected_flow.values, dtype=float)
        if values.ndim == 1:
            values = values.reshape((-1, 1))

        if direction == "absolute":
            flow = np.abs(values).sum(axis=1)
        else:
            flow = values.sum(axis=1)

        result = pd.DataFrame({
            "time": pd.to_datetime(face_flow.coords["time"].values),
            "flow": flow,
            "line_name": str(line_name),
            "mesh_name": resolved_mesh_name,
            "direction": direction,
            "face_count": len(face_ids),
            "selection_source": selection_source,
        })
        result.attrs["face_ids"] = face_ids
        result.attrs["units"] = face_flow.attrs.get("units", "")
        result.attrs["variable"] = "Face Flow"
        return result

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_profile_line_peak_flow(
        hdf_path: Path,
        line_name: str,
        mesh_name: Optional[str] = None,
        profile_lines_path: Optional[Union[str, Path]] = None,
        direction: str = "absolute",
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Return peak flow across a RAS Mapper profile/reference line.

        For ``direction="absolute"``, the peak is the maximum absolute-flow
        sum. For ``direction="signed"``, the peak timestep is selected by
        maximum signed-flow magnitude and the returned ``peak_flow`` preserves
        the native sign at that timestep.
        """
        flow_df = HdfResultsMesh.get_profile_line_flow_timeseries(
            hdf_path=hdf_path,
            line_name=line_name,
            mesh_name=mesh_name,
            profile_lines_path=profile_lines_path,
            direction=direction,
            truncate=False,
            ras_object=ras_object,
        )
        if flow_df.empty:
            return pd.DataFrame(
                columns=[
                    "line_name",
                    "mesh_name",
                    "peak_time",
                    "peak_flow",
                    "direction",
                    "face_count",
                    "selection_source",
                ]
            )

        peak_index = flow_df["flow"].abs().idxmax()
        peak_row = flow_df.loc[peak_index]
        return pd.DataFrame([{
            "line_name": peak_row["line_name"],
            "mesh_name": peak_row["mesh_name"],
            "peak_time": peak_row["time"],
            "peak_flow": peak_row["flow"],
            "direction": peak_row["direction"],
            "face_count": peak_row["face_count"],
            "selection_source": peak_row["selection_source"],
        }])

    @staticmethod
    def _normalize_profile_line_direction(direction: str) -> str:
        normalized = str(direction).strip().lower()
        if normalized not in {"absolute", "signed"}:
            raise ValueError("direction must be either 'absolute' or 'signed'")
        return normalized

    @staticmethod
    def _resolve_profile_line_faces(
        hdf_path: Path,
        line_name: str,
        mesh_name: Optional[str],
        profile_lines_path: Optional[Union[str, Path]],
        ras_object: Optional[Any],
    ) -> Tuple[pd.DataFrame, str, str]:
        native_faces = HdfResultsMesh._get_native_profile_line_faces(
            hdf_path=hdf_path,
            line_name=line_name,
            mesh_name=mesh_name,
            ras_object=ras_object,
        )
        if not native_faces.empty:
            resolved_mesh_name = HdfResultsMesh._resolve_single_mesh_name(
                native_faces,
                mesh_name,
                line_name,
            )
            return native_faces, resolved_mesh_name, "reference_line_internal_faces"

        resolved_profile_lines_path = HdfResultsMesh._resolve_profile_lines_path(
            profile_lines_path=profile_lines_path,
            ras_object=ras_object,
        )
        if resolved_profile_lines_path is None:
            raise ValueError(
                f"Profile/reference line '{line_name}' was not found in native HDF "
                "reference-line internal faces, and no RAS Mapper profile-lines "
                "feature path could be resolved. Pass profile_lines_path or initialize "
                "a ras_object with rasmap_df."
            )

        cell_faces = HdfMesh.get_mesh_cell_faces(hdf_path)
        if cell_faces is None or cell_faces.empty:
            raise ValueError(f"No mesh cell faces found in HDF file: {hdf_path}")

        profile_line = HdfResultsMesh._read_profile_line_geometry(
            profile_lines_path=resolved_profile_lines_path,
            line_name=line_name,
            target_crs=getattr(cell_faces, "crs", None),
        )
        selected_faces = HdfMesh.get_faces_along_profile_line(
            profile_line=profile_line,
            cell_faces_gdf=cell_faces,
            mesh_name=mesh_name,
        )
        if selected_faces is None or selected_faces.empty:
            raise ValueError(
                f"No mesh faces found along profile line '{line_name}'. "
                "Check that the line crosses the target mesh and that the HDF "
                "and feature file use compatible coordinates."
            )

        resolved_mesh_name = HdfResultsMesh._resolve_single_mesh_name(
            selected_faces,
            mesh_name,
            line_name,
        )
        selected_faces = selected_faces[selected_faces["mesh_name"] == resolved_mesh_name]
        return selected_faces, resolved_mesh_name, "profile_lines_geometry"

    @staticmethod
    def _get_native_profile_line_faces(
        hdf_path: Path,
        line_name: str,
        mesh_name: Optional[str],
        ras_object: Optional[Any],
    ) -> pd.DataFrame:
        reference_hdf_path = HdfResultsMesh._resolve_reference_line_hdf_path(
            hdf_path,
            ras_object=ras_object,
        )
        reference_faces = HdfMesh.get_reference_line_internal_faces(
            reference_hdf_path,
            mesh_name=mesh_name,
        )
        if reference_faces.empty or "profile_name" not in reference_faces.columns:
            return reference_faces.iloc[0:0].copy()

        target_name = str(line_name).strip()
        profile_names = reference_faces["profile_name"].fillna("").astype(str).str.strip()
        selected = reference_faces.loc[profile_names == target_name].copy()
        if selected.empty:
            selected = reference_faces.loc[
                profile_names.str.lower() == target_name.lower()
            ].copy()

        if selected.empty:
            return selected

        selected["face_id"] = pd.to_numeric(selected["face_id"], errors="coerce")
        selected = selected.dropna(subset=["face_id"]).copy()
        selected["face_id"] = selected["face_id"].astype(int)
        if "station_start" in selected.columns:
            selected = selected.sort_values(
                ["mesh_name", "station_start", "station_end", "face_id"],
                na_position="last",
            )
        return selected.reset_index(drop=True)

    @staticmethod
    def _resolve_reference_line_hdf_path(
        hdf_path: Path,
        ras_object: Optional[Any],
    ) -> Path:
        hdf_path = Path(hdf_path)
        reference_faces_path = "Geometry/Reference Lines/Internal Faces"
        if HdfResultsMesh._hdf_contains_path(hdf_path, reference_faces_path):
            return hdf_path

        geom_hdf_path = (
            HdfResultsMesh._geometry_hdf_from_ras_object(hdf_path, ras_object)
            or HdfResultsMesh._geometry_hdf_from_plan_hdf_path(hdf_path)
        )
        if geom_hdf_path is not None and geom_hdf_path.exists():
            return geom_hdf_path
        return hdf_path

    @staticmethod
    def _hdf_contains_path(hdf_path: Path, hdf_internal_path: str) -> bool:
        try:
            with h5py.File(hdf_path, "r") as hdf_file:
                return hdf_internal_path in hdf_file
        except Exception:
            return False

    @staticmethod
    def _geometry_hdf_from_ras_object(
        hdf_path: Path,
        ras_object: Optional[Any],
    ) -> Optional[Path]:
        if ras_object is None:
            return None

        plan_df = getattr(ras_object, "plan_df", None)
        if plan_df is None or plan_df.empty:
            return None

        target = HdfResultsMesh._normalized_path_string(hdf_path)
        for _, row in plan_df.iterrows():
            result_paths = []
            for column in ("HDF_Results_Path", "hdf_path", "results_path"):
                if column in row and pd.notna(row[column]):
                    result_paths.append(row[column])

            if not any(
                HdfResultsMesh._normalized_path_string(path_value) == target
                for path_value in result_paths
            ):
                continue

            plan_number = row.get("plan_number")
            if pd.notna(plan_number) and hasattr(ras_object, "get_hdf_paths"):
                try:
                    paths = ras_object.get_hdf_paths(str(plan_number))
                    geom_hdf_path = paths.get("geometry")
                    if geom_hdf_path is not None and Path(geom_hdf_path).exists():
                        return Path(geom_hdf_path)
                except Exception:
                    pass

            geom_path = row.get("Geom Path")
            if pd.notna(geom_path):
                geom_hdf_path = Path(str(geom_path) + ".hdf")
                if geom_hdf_path.exists():
                    return geom_hdf_path

        return None

    @staticmethod
    def _geometry_hdf_from_plan_hdf_path(hdf_path: Path) -> Optional[Path]:
        if hdf_path.suffix.lower() != ".hdf":
            return None

        plan_path = Path(str(hdf_path)[:-4])
        if not plan_path.exists():
            return None

        geom_file = None
        try:
            with open(plan_path, "r", encoding="utf-8", errors="ignore") as plan_file:
                for line in plan_file:
                    if line.startswith("Geom File="):
                        geom_file = line.split("=", 1)[1].strip()
                        break
        except Exception:
            return None

        if not geom_file:
            return None

        plan_name = plan_path.name
        if "." not in plan_name:
            return None
        project_name = plan_name.rsplit(".", 1)[0]
        geom_hdf_path = hdf_path.parent / f"{project_name}.{geom_file}.hdf"
        return geom_hdf_path if geom_hdf_path.exists() else None

    @staticmethod
    def _normalized_path_string(path_value) -> str:
        try:
            return str(Path(str(path_value)).resolve()).lower()
        except Exception:
            return str(path_value).lower()

    @staticmethod
    def _resolve_single_mesh_name(
        selected_faces: pd.DataFrame,
        mesh_name: Optional[str],
        line_name: str,
    ) -> str:
        if mesh_name is not None:
            return str(mesh_name)

        mesh_names = [
            str(value)
            for value in selected_faces.get("mesh_name", pd.Series(dtype=object)).dropna().unique()
        ]
        if len(mesh_names) == 1:
            return mesh_names[0]
        if not mesh_names:
            raise ValueError(
                f"Profile line '{line_name}' did not resolve a mesh name. "
                "Specify mesh_name explicitly."
            )
        raise ValueError(
            f"Profile line '{line_name}' intersects multiple mesh areas: {mesh_names}. "
            "Specify mesh_name explicitly."
        )

    @staticmethod
    def _resolve_profile_lines_path(
        profile_lines_path: Optional[Union[str, Path]],
        ras_object: Optional[Any],
    ) -> Optional[Path]:
        candidate_paths = []
        if profile_lines_path is not None:
            candidate_paths.append(profile_lines_path)
        else:
            ras_obj = ras_object
            if ras_obj is None:
                try:
                    from ..RasPrj import ras as ras_obj
                except Exception:
                    ras_obj = None

            rasmap_df = getattr(ras_obj, "rasmap_df", None)
            if rasmap_df is not None and not rasmap_df.empty and "profile_lines_path" in rasmap_df.columns:
                for value in rasmap_df["profile_lines_path"].tolist():
                    if isinstance(value, (list, tuple, set)):
                        candidate_paths.extend(value)
                    elif pd.notna(value):
                        candidate_paths.append(value)

        project_folder = getattr(ras_object, "project_folder", None)
        for candidate in candidate_paths:
            if candidate is None or (not isinstance(candidate, (list, tuple, set)) and pd.isna(candidate)):
                continue
            path = Path(candidate)
            if not path.is_absolute() and project_folder is not None:
                path = Path(project_folder) / path

            resolved = HdfResultsMesh._resolve_profile_lines_file(path)
            if resolved is not None:
                return resolved
        return None

    @staticmethod
    def _resolve_profile_lines_file(path: Path) -> Optional[Path]:
        if path.is_file():
            return path
        if path.is_dir():
            for pattern in ("*.shp", "*.geojson", "*.json", "*.gpkg"):
                matches = sorted(path.glob(pattern))
                if matches:
                    return matches[0]
        return None

    @staticmethod
    def _read_profile_line_geometry(
        profile_lines_path: Path,
        line_name: str,
        target_crs: Optional[Any] = None,
    ):
        from shapely.geometry import LineString
        from shapely.ops import linemerge, unary_union

        profile_lines_gdf = gpd.read_file(profile_lines_path)
        if profile_lines_gdf.empty:
            raise ValueError(f"No profile-line features found in {profile_lines_path}")

        name_column = HdfResultsMesh._profile_line_name_column(profile_lines_gdf)
        target_name = str(line_name).strip()
        names = profile_lines_gdf[name_column].fillna("").astype(str).str.strip()
        selected = profile_lines_gdf.loc[names == target_name].copy()
        if selected.empty:
            selected = profile_lines_gdf.loc[names.str.lower() == target_name.lower()].copy()

        if selected.empty:
            available_names = sorted(names[names != ""].unique().tolist())
            raise ValueError(
                f"Profile line '{line_name}' not found in {profile_lines_path}. "
                f"Available profile lines: {available_names}"
            )

        if (
            target_crs is not None
            and selected.crs is not None
            and selected.crs != target_crs
        ):
            selected = selected.to_crs(target_crs)

        geometries = [geom for geom in selected.geometry if geom is not None and not geom.is_empty]
        if not geometries:
            raise ValueError(f"Profile line '{line_name}' has no valid geometry.")

        if len(geometries) == 1:
            profile_line = geometries[0]
        else:
            merged_geometry = unary_union(geometries)
            if merged_geometry.geom_type in {"LineString", "LinearRing"}:
                profile_line = merged_geometry
            else:
                profile_line = linemerge(merged_geometry)
        if profile_line.geom_type == "MultiLineString":
            profile_line = max(profile_line.geoms, key=lambda geom: geom.length)

        if profile_line.geom_type == "LinearRing":
            profile_line = LineString(profile_line)
        if profile_line.geom_type != "LineString":
            raise ValueError(
                f"Profile line '{line_name}' geometry must be a LineString; "
                f"got {profile_line.geom_type}."
            )
        return profile_line

    @staticmethod
    def _profile_line_name_column(profile_lines_gdf: gpd.GeoDataFrame) -> str:
        for candidate in (
            "Name",
            "name",
            "Profile",
            "ProfileName",
            "profile_name",
            "LineName",
            "line_name",
        ):
            if candidate in profile_lines_gdf.columns:
                return candidate

        non_geometry_columns = [
            column
            for column in profile_lines_gdf.columns
            if column != profile_lines_gdf.geometry.name
        ]
        if len(non_geometry_columns) == 1:
            return non_geometry_columns[0]
        raise ValueError(
            "Could not identify a profile-line name column. Expected one of "
            "Name, name, Profile, ProfileName, profile_name, LineName, or line_name."
        )

    @staticmethod
    def _unique_int_values(values) -> List[int]:
        result = []
        seen = set()
        for value in pd.to_numeric(pd.Series(values), errors="coerce").dropna():
            int_value = int(value)
            if int_value not in seen:
                seen.add(int_value)
                result.append(int_value)
        return result

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_faces_timeseries(
        hdf_path: Path,
        mesh_name: str,
        truncate: bool = True
    ) -> xr.Dataset:
        """
        Get timeseries output for all face-based variables of a specific mesh.

        Args:
            hdf_path (Path): Path to the HDF file.
            mesh_name (str): Name of the mesh.
            truncate (bool): Whether to truncate leading/trailing zero-only
                timesteps for each variable. Defaults to True for backward
                compatibility with the previous behavior.

        Returns:
            xr.Dataset: **Multiple variables for ONE mesh**.
                Use Dataset when extracting MULTIPLE variables for a SINGLE mesh area.

                Data variables:
                    Any available face-based HDF time-series outputs listed in
                    MESH_FACE_TIME_SERIES_OUTPUT_VARS, normalized to lowercase
                    names such as face_velocity, face_flow,
                    face_water_surface, face_area, and face_mannings_n.
                    Each variable shares common dimensions.

                Dimensions:
                    - time: Timestamps
                    - face_id: Face IDs

                When to use: Combined face analysis for single mesh.
                For single variable, use get_mesh_timeseries() → DataArray.
                For multiple meshes, use get_mesh_cells_timeseries() → Dict[str, Dataset].
        """
        datasets = []

        with h5py.File(hdf_path, 'r') as hdf_file:
            for var in HdfResultsMesh.MESH_FACE_TIME_SERIES_OUTPUT_VARS:
                path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, var)
                if path not in hdf_file:
                    logger.debug(f"Variable '{var}' not found for mesh '{mesh_name}'. Skipping.")
                    continue

                try:
                    da = HdfResultsMesh._get_mesh_timeseries_output(
                        hdf_file,
                        mesh_name,
                        var,
                        truncate=truncate,
                    )
                    # Assign the variable name as the DataArray name
                    da.name = HdfResultsMesh._mesh_data_var_name(var)
                    datasets.append(da)
                except Exception as e:
                    logger.warning(f"Failed to process {var} for mesh {mesh_name}: {str(e)}")
        
        if not datasets:
            logger.error(f"No valid data found for mesh {mesh_name}")
            return xr.Dataset()
        
        try:
            return xr.merge(datasets)
        except Exception as e:
            logger.error(f"Failed to merge datasets: {str(e)}")
            return xr.Dataset()

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_cells_timeseries(hdf_path: Path, mesh_names: Optional[Union[str, List[str]]] = None, var: Optional[str] = None, truncate: bool = False, ras_object: Optional[Any] = None) -> Dict[str, xr.Dataset]:
        """
        Get mesh cells timeseries output.

        Args:
            hdf_path (Path): Path to HDF file
            mesh_names (str|List[str], optional): Mesh name(s). If None, processes all meshes
            var (str, optional): Variable name. If None, retrieves all variables
            truncate (bool): Remove trailing zeros if True
            ras_object (Any, optional): RAS object if available

        Returns:
            Dict[str, xr.Dataset]: **Multiple mesh areas with multiple variables**.
                Use Dict[str, Dataset] when extracting data for MULTIPLE mesh areas.

                Structure:
                    {
                        'Mesh1': Dataset(vars=['Water Surface', 'Velocity', ...]),
                        'Mesh2': Dataset(vars=['Water Surface', 'Velocity', ...]),
                        ...
                    }

                Each Dataset contains:
                    Data variables: All cell/face variables for that mesh
                    Dimensions: time, cell_id/face_id (specific to each mesh)
                    Attributes: mesh_name, start_time

                When to use: Model-wide analysis across multiple mesh areas.
                For single mesh, use get_mesh_faces_timeseries() → Dataset.
                For single variable, use get_mesh_timeseries() → DataArray.

                Why dictionary: Different meshes may have different:
                    - Number of cells/faces
                    - Available variables
                    - Time series lengths
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_path:
                return HdfResultsMesh._get_mesh_cells_timeseries_output(hdf_path, mesh_names, var, truncate)
        except Exception as e:
            logger.error(f"Error in get_mesh_cells_timeseries: {str(e)}")
            raise ValueError(f"Error processing timeseries output data: {e}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_last_iter(hdf_file: Path) -> pd.DataFrame:
        """
        Get last iteration count for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            pd.DataFrame: DataFrame containing last iteration counts.
        """
        return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Last Iteration")


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_ws(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get maximum water surface elevation for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing maximum water surface elevations with geometry.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Maximum Water Surface", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_ws: {str(e)}")
            raise ValueError(f"Failed to get maximum water surface: {str(e)}")
        




    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_min_ws(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get minimum water surface elevation for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing minimum water surface elevations with geometry.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Minimum Water Surface", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_min_ws: {str(e)}")
            raise ValueError(f"Failed to get minimum water surface: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_face_v(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get maximum face velocity for each mesh face.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing maximum face velocities.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Maximum Face Velocity", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_face_v: {str(e)}")
            raise ValueError(f"Failed to get maximum face velocity: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_min_face_v(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get minimum face velocity for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing minimum face velocities.

        Raises:
            ValueError: If there's an error processing the minimum face velocity data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Minimum Face Velocity", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_min_face_v: {str(e)}")
            raise ValueError(f"Failed to get minimum face velocity: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_ws_err(hdf_path: Path, round_to: str = "100ms") -> pd.DataFrame:
        """
        Get maximum water surface error for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            pd.DataFrame: DataFrame containing maximum water surface errors.

        Raises:
            ValueError: If there's an error processing the maximum water surface error data.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Maximum Water Surface Error", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_ws_err: {str(e)}")
            raise ValueError(f"Failed to get maximum water surface error: {str(e)}")


    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_iter(hdf_path: Path, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get maximum iteration count for each mesh cell.

        Args:
            hdf_path (Path): Path to the HDF file.
            round_to (str): Time rounding specification (default "100ms").

        Returns:
            gpd.GeoDataFrame: GeoDataFrame containing maximum iteration counts with geometry.
                Includes columns:
                - mesh_name: Name of the mesh
                - cell_id: ID of the cell
                - cell_last_iteration: Maximum number of iterations
                - cell_last_iteration_time: Time when max iterations occurred
                - geometry: Point geometry representing cell center
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                return HdfResultsMesh.get_mesh_summary_output(hdf_file, "Cell Last Iteration", round_to)
        except Exception as e:
            logger.error(f"Error in get_mesh_max_iter: {str(e)}")
            raise ValueError(f"Failed to get maximum iteration count: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_max_depth(hdf_path: Path) -> gpd.GeoDataFrame:
        """
        Get the maximum depth for each 2D mesh cell by reading the full Depth
        time series and computing np.max(axis=0) per cell.

        Attribution: Implementation pattern derived from ras-agent
        (https://github.com/gheistand/ras-agent) by Glenn Heistand / CHAMP —
        Illinois State Water Survey. See results.py:extract_max_depth().

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            gpd.GeoDataFrame: GeoDataFrame with columns:
                - mesh_name (str): Name of the 2D flow area
                - cell_id (int): Cell index
                - maximum_depth (float): Maximum depth at that cell
                - geometry (Point): Cell center point geometry
        """
        from shapely.geometry import Point

        try:
            dfs = []
            with h5py.File(hdf_path, 'r') as hdf_file:
                d2_flow_areas = hdf_file.get("Geometry/2D Flow Areas/Attributes")
                if d2_flow_areas is None:
                    logger.info("No 2D Flow Areas found in HDF file")
                    return gpd.GeoDataFrame()

                for d2_flow_area in d2_flow_areas[:]:
                    mesh_name = HdfUtils.convert_ras_string(d2_flow_area[0])

                    # Read cell centers
                    cc_path = f"Geometry/2D Flow Areas/{mesh_name}/Cells Center Coordinate"
                    cc_ds = hdf_file.get(cc_path)
                    if cc_ds is None:
                        logger.warning(f"Cell centers not found for mesh '{mesh_name}'")
                        continue
                    xy = np.array(cc_ds, dtype=np.float64)

                    # Read depth time series
                    depth_path = (
                        f"Results/Unsteady/Output/Output Blocks/Base Output/"
                        f"Unsteady Time Series/2D Flow Areas/{mesh_name}/Depth"
                    )
                    depth_ds = hdf_file.get(depth_path)
                    if depth_ds is None:
                        logger.warning(f"Depth dataset not found for mesh '{mesh_name}'")
                        continue

                    depths = np.array(depth_ds, dtype=np.float32)  # (T, N)
                    max_depth = np.max(depths, axis=0)  # (N,)

                    geom = [Point(x, y) for x, y in xy]
                    df = gpd.GeoDataFrame({
                        "mesh_name": [mesh_name] * len(max_depth),
                        "cell_id": range(len(max_depth)),
                        "maximum_depth": max_depth,
                    }, geometry=geom)
                    dfs.append(df)

            if not dfs:
                return gpd.GeoDataFrame()

            result = pd.concat(dfs, ignore_index=True)

            # Set CRS
            with h5py.File(hdf_path, 'r') as hdf_file:
                crs = HdfBase.get_projection(hdf_file)
            if crs:
                result.set_crs(crs, inplace=True)

            logger.info(f"Extracted max depth for {len(result)} cells")
            return result

        except Exception as e:
            logger.error(f"Error in get_mesh_max_depth: {str(e)}")
            raise ValueError(f"Failed to get maximum depth: {str(e)}")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def export_max_depth_raster(
        hdf_path: Path,
        output_path: Union[str, Path] = None,
        resolution_m: float = 3.0,
        crs=None,
        method: str = "linear",
        nodata: float = -9999.0,
    ) -> Path:
        """
        Export maximum depth as a Cloud-Optimized GeoTIFF raster.

        Attribution: Implementation pattern derived from ras-agent
        (https://github.com/gheistand/ras-agent) by Glenn Heistand / CHAMP —
        Illinois State Water Survey. See results.py:cells_to_raster().

        Reads cell centers and max depth from the HDF file, interpolates onto
        a regular grid using scipy.interpolate.griddata, and writes a COG with
        LZW compression and overviews.

        Args:
            hdf_path (Path): Path to the HDF file.
            output_path (Union[str, Path], optional): Output GeoTIFF path.
                If None, writes to a temporary file.
            resolution_m (float): Grid cell size in CRS units (default 3.0).
            crs: Output CRS. If None, uses the CRS from the HDF file.
            method (str): Interpolation method for griddata (default "linear").
            nodata (float): Nodata value for the raster (default -9999.0).

        Returns:
            Path: Path to the written GeoTIFF file.
        """
        import rasterio
        from rasterio.transform import from_bounds
        from scipy.interpolate import griddata as scipy_griddata

        gdf = HdfResultsMesh.get_mesh_max_depth(hdf_path)
        if gdf.empty:
            raise ValueError("No depth data found in HDF file")

        xy = np.column_stack([gdf.geometry.x, gdf.geometry.y])
        values = gdf["maximum_depth"].values

        if output_path is None:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
            output_path = Path(tmp.name)
            tmp.close()
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        if crs is None:
            crs = gdf.crs

        x, y = xy[:, 0], xy[:, 1]
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()

        cols = max(2, int(np.ceil((x_max - x_min) / resolution_m)) + 1)
        rows = max(2, int(np.ceil((y_max - y_min) / resolution_m)) + 1)
        grid_x = np.linspace(x_min, x_max, cols)
        grid_y = np.linspace(y_max, y_min, rows)
        gx, gy = np.meshgrid(grid_x, grid_y)

        grid_vals = scipy_griddata(
            points=xy,
            values=values.astype(np.float64),
            xi=(gx, gy),
            method=method,
            fill_value=nodata,
        ).astype(np.float32)

        grid_vals = np.where(np.isnan(grid_vals), nodata, grid_vals)
        transform = from_bounds(x_min, y_min, x_max, y_max, cols, rows)

        with rasterio.open(
            str(output_path), "w",
            driver="GTiff", height=rows, width=cols, count=1,
            dtype=np.float32, crs=crs, transform=transform, nodata=nodata,
            compress="lzw", tiled=True, blockxsize=256, blockysize=256,
            BIGTIFF="IF_SAFER",
        ) as dst:
            dst.write(grid_vals, 1)
            dst.build_overviews([2, 4, 8, 16], rasterio.enums.Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")

        logger.info(f"Wrote max depth raster ({rows}x{cols} px, {resolution_m}m): {output_path}")
        return output_path

    @staticmethod
    @log_call
    def get_flood_extent_polygon(
        plan_number: str,
        profile: str = "Max",
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600,
    ) -> gpd.GeoDataFrame:
        """
        Generate the canonical RASMapper inundation boundary polygon via
        RasProcess.exe StoreAllMaps.

        This uses the same algorithm RASMapper uses in the GUI to produce
        inundation boundary shapefiles — the authoritative HEC-RAS flood
        extent. Requires an initialized ras-commander project and HEC-RAS
        installed.

        Args:
            plan_number (str): Plan number (e.g., "01").
            profile (str): Profile to map — "Max", "Min", or timestamp string.
            ras_object: Optional RAS project object.
            ras_version (str): Optional HEC-RAS version for RasProcess.exe.
            timeout (int): RasProcess.exe timeout in seconds (default 600).

        Returns:
            gpd.GeoDataFrame: Inundation boundary polygon(s) read from the
                shapefile generated by RASMapper. Returns empty GeoDataFrame
                if generation fails or no flood extent is produced.

        Raises:
            FileNotFoundError: If RasProcess.exe or plan HDF not found.
            RuntimeError: If RasProcess.exe command fails.

        Example:
            >>> from ras_commander import init_ras_project
            >>> from ras_commander.hdf import HdfResultsMesh
            >>> init_ras_project("/path/to/project", "7.0")
            >>> flood_gdf = HdfResultsMesh.get_flood_extent_polygon("01")
        """
        from ..RasProcess import RasProcess

        results = RasProcess.store_maps(
            plan_number=plan_number,
            profile=profile,
            wse=False,
            depth=False,
            velocity=False,
            inundation_boundary=True,
            fix_georef=False,
            ras_object=ras_object,
            ras_version=ras_version,
            timeout=timeout,
        )

        shp_files = results.get('inundation_boundary', [])
        if not shp_files:
            logger.warning("RasProcess did not produce an inundation boundary shapefile")
            return gpd.GeoDataFrame()

        # Read the first shapefile
        shp_path = shp_files[0]
        gdf = gpd.read_file(shp_path)
        logger.info(
            f"Read inundation boundary from {shp_path.name}: "
            f"{len(gdf)} feature(s), "
            f"{gdf.geometry.area.sum() / 1e6:.3f} km² total area"
        )
        return gdf

    @staticmethod
    def _get_mesh_timeseries_output_path(mesh_name: str, var_name: str) -> str:
        """
        Get the HDF path for mesh timeseries output.

        Args:
            mesh_name (str): Name of the mesh.
            var_name (str): Name of the variable.

        Returns:
            str: The HDF path for the specified mesh and variable.
        """
        return f"Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{mesh_name}/{var_name}"


    @staticmethod
    def _get_mesh_cells_timeseries_output(hdf_path: h5py.File,
                                         mesh_names: Optional[Union[str, List[str]]] = None,
                                         var: Optional[str] = None,
                                         truncate: bool = False) -> Dict[str, xr.Dataset]:
        """
        Get mesh cells timeseries output for specified meshes and variables.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_names (Optional[Union[str, List[str]]]): Name(s) of the mesh(es). If None, processes all available meshes.
            var (Optional[str]): Name of the variable to retrieve. If None, retrieves all variables.
            truncate (bool): If True, truncates the output to remove trailing zeros.

        Returns:
            Dict[str, xr.Dataset]: **Dictionary of Datasets for multiple meshes**.
                Internal implementation of get_mesh_cells_timeseries().

                Why Dict[str, Dataset]:
                    - Each mesh area has independent dimensions (cell count, time steps)
                    - Cannot combine into single Dataset due to incompatible dimensions
                    - Dictionary allows accessing each mesh independently

                Each value (Dataset) contains:
                    - Multiple data variables (Water Surface, Velocity, etc.)
                    - Common dimensions for that mesh (time, cell_id/face_id)
                    - Mesh-specific attributes

        Raises:
            ValueError: If there's an error processing the timeseries output data.
        """
        TIME_SERIES_OUTPUT_VARS = {
            "cell": HdfResultsMesh.MESH_CELL_TIME_SERIES_OUTPUT_VARS,
            "face": HdfResultsMesh.MESH_FACE_TIME_SERIES_OUTPUT_VARS
        }

        try:
            start_time = HdfBase.get_simulation_start_time(hdf_path)
            time_stamps = HdfBase.get_unsteady_timestamps(hdf_path)

            if mesh_names is None:
                mesh_names = HdfResultsMesh._get_available_meshes(hdf_path)
            elif isinstance(mesh_names, str):
                mesh_names = [mesh_names]

            if var:
                variables = [var]
            else:
                variables = TIME_SERIES_OUTPUT_VARS["cell"] + TIME_SERIES_OUTPUT_VARS["face"]

            datasets = {}
            for mesh_name in mesh_names:
                data_vars = {}
                for variable in variables:
                    try:
                        path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, variable)
                        dataset = hdf_path[path]
                        values = dataset[:]
                        units = HdfResultsMesh._decode_hdf_attr(
                            dataset.attrs.get("Units", "")
                        )

                        if truncate:
                            if values.ndim == 2:
                                non_zero_time = np.where(np.any(values != 0, axis=1))[0]
                            else:
                                non_zero_time = np.nonzero(values)[0]

                            if len(non_zero_time) > 0:
                                start, end = non_zero_time[0], non_zero_time[-1] + 1
                                values = values[start:end]
                                truncated_time_stamps = time_stamps[start:end]
                            else:
                                values = values[:0]
                                truncated_time_stamps = time_stamps[:0]
                        else:
                            truncated_time_stamps = time_stamps

                        if values.shape[0] != len(truncated_time_stamps):
                            logger.warning(f"Mismatch between time steps ({len(truncated_time_stamps)}) and data shape ({values.shape}) for variable {variable}")
                            continue

                        # Determine if this is a face-based or cell-based variable
                        id_dim = "face_id" if variable in TIME_SERIES_OUTPUT_VARS["face"] else "cell_id"

                        data_vars[variable] = xr.DataArray(
                            data=values,
                            dims=['time', id_dim],
                            coords={'time': truncated_time_stamps, id_dim: np.arange(values.shape[1])},
                            attrs={'units': units}
                        )
                    except KeyError:
                        logger.warning(f"Variable '{variable}' not found in the HDF file for mesh '{mesh_name}'. Skipping.")
                    except Exception as e:
                        logger.error(f"Error processing variable '{variable}' for mesh '{mesh_name}': {str(e)}")

                if data_vars:
                    datasets[mesh_name] = xr.Dataset(
                        data_vars=data_vars,
                        attrs={'mesh_name': mesh_name, 'start_time': start_time}
                    )
                else:
                    logger.warning(f"No valid data variables found for mesh '{mesh_name}'")

            return datasets
        except Exception as e:
            logger.error(f"Error in _mesh_cells_timeseries_output: {str(e)}")
            raise ValueError(f"Error processing timeseries output data: {e}")



    @staticmethod
    def _get_mesh_timeseries_output(hdf_path: h5py.File, mesh_name: str, var: str, truncate: bool = True) -> xr.DataArray:
        """
        Get timeseries output for a specific mesh and variable.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Variable name to retrieve.
            truncate (bool): Whether to truncate the output to remove trailing zeros (default True).

        Returns:
            xr.DataArray: **Single variable time series**.
                Internal implementation of get_mesh_timeseries().

                Returns DataArray (not Dataset) because:
                    - Only ONE variable being extracted
                    - No need for Dataset overhead
                    - Direct array access for plotting/analysis

                Structure:
                    - Data: 2D array (time × cell/face)
                    - Dimensions: time, cell_id/face_id
                    - Attributes: units, mesh_name, variable

        Raises:
            ValueError: If the specified path is not found in the HDF file or if there's an error processing the data.
        """
        try:
            path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, var)
            
            if path not in hdf_path:
                raise ValueError(f"Path {path} not found in HDF file")

            dataset = hdf_path[path]
            values = dataset[:]
            units = HdfResultsMesh._decode_hdf_attr(
                dataset.attrs.get("Units", "")
            )
            
            # Get start time and timesteps
            start_time = HdfBase.get_simulation_start_time(hdf_path)
            # Updated to use the new function name from HdfUtils
            timesteps = HdfUtils.convert_timesteps_to_datetimes(
                np.array(hdf_path["Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time"][:]),
                start_time
            )

            if truncate:
                non_zero = np.nonzero(values)[0]
                if len(non_zero) > 0:
                    start, end = non_zero[0], non_zero[-1] + 1
                    values = values[start:end]
                    timesteps = timesteps[start:end]

            # Determine if this is a face-based or cell-based variable
            id_dim = "face_id" if "Face" in var else "cell_id"
            dims = ["time", id_dim] if values.ndim == 2 else ["time"]
            coords = {"time": timesteps}
            if values.ndim == 2:
                coords[id_dim] = np.arange(values.shape[1])

            return xr.DataArray(
                values,
                coords=coords,
                dims=dims,
                attrs={"units": units, "mesh_name": mesh_name, "variable": var},
            )
        except Exception as e:
            logger.error(f"Error in get_mesh_timeseries_output: {str(e)}")
            raise ValueError(f"Failed to get timeseries output: {str(e)}")


    @staticmethod
    def _get_mesh_timeseries_output_values_units(hdf_path: h5py.File, mesh_name: str, var: str) -> Tuple[np.ndarray, str]:
        """
        Get the mesh timeseries output values and units for a specific variable from the HDF file.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Variable name to retrieve.

        Returns:
            Tuple[np.ndarray, str]: A tuple containing the output values and units.
        """
        path = HdfResultsMesh._get_mesh_timeseries_output_path(mesh_name, var)
        group = hdf_path[path]
        values = group[:]
        units = HdfResultsMesh._decode_hdf_attr(group.attrs.get("Units"))
        return values, units

    @staticmethod
    def _decode_hdf_attr(value: object) -> str:
        """Decode optional HDF string attributes to plain strings."""
        if value is None:
            return ""
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode("utf-8")
        if isinstance(value, np.ndarray):
            if value.size == 0:
                return ""
            return HdfResultsMesh._decode_hdf_attr(value.flat[0])
        return str(value)

    @staticmethod
    def _mesh_data_var_name(variable: str) -> str:
        """Normalize HDF output variable names for xarray Dataset keys."""
        return (
            variable.lower()
            .replace("'", "")
            .replace("/", "_")
            .replace("-", "_")
            .replace(" ", "_")
        )


    @staticmethod
    def _get_available_meshes(hdf_path: h5py.File) -> List[str]:
        """
        Get the names of all available meshes in the HDF file.

        Args:
            hdf_path (h5py.File): Open HDF file object.

        Returns:
            List[str]: A list of mesh names.
        """
        return HdfMesh.get_mesh_area_names(hdf_path)
    
    
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_mesh_summary_output(hdf_file: h5py.File, var: str, round_to: str = "100ms") -> gpd.GeoDataFrame:
        """
        Get the summary output data for a given variable from the HDF file.

        Parameters
        ----------
        hdf_path : h5py.File
            Open HDF file object.
        var : str
            The summary output variable to retrieve.
        round_to : str, optional
            The time unit to round the datetimes to. Default is "100ms".

        Returns
        -------
        gpd.GeoDataFrame
            A GeoDataFrame containing the summary output data with decoded attributes as metadata.
            Returns empty GeoDataFrame if variable is not found.
        """
        try:
            dfs = []
            start_time = HdfBase.get_simulation_start_time(hdf_file)
            
            logger.info(f"Processing summary output for variable: {var}")
            d2_flow_areas = hdf_file.get("Geometry/2D Flow Areas/Attributes")
            if d2_flow_areas is None:
                logger.info("No 2D Flow Areas found in HDF file")
                return gpd.GeoDataFrame()

            for d2_flow_area in d2_flow_areas[:]:
                mesh_name = HdfUtils.convert_ras_string(d2_flow_area[0])
                cell_count = d2_flow_area[-1]
                logger.debug(f"Processing mesh: {mesh_name} with {cell_count} cells")
                
                try:
                    group = HdfResultsMesh.get_mesh_summary_output_group(hdf_file, mesh_name, var)
                except ValueError:
                    logger.info(f"Variable '{var}' not present in output file for mesh '{mesh_name}', skipping")
                    continue
                
                data = group[:]
                logger.debug(f"Data shape for {var} in {mesh_name}: {data.shape}")
                logger.debug(f"Data type: {data.dtype}")
                logger.debug(f"Attributes: {dict(group.attrs)}")
                
                if data.ndim == 2 and data.shape[0] == 2:
                    # Handle 2D datasets (e.g. Maximum Water Surface)
                    row_variables = group.attrs.get('Row Variables', [b'Value', b'Time'])
                    row_variables = [v.decode('utf-8').strip() if isinstance(v, bytes) else v for v in row_variables]
                    
                    df = pd.DataFrame({
                        "mesh_name": [mesh_name] * data.shape[1],
                        "cell_id" if "Face" not in var else "face_id": range(data.shape[1]),
                        f"{var.lower().replace(' ', '_')}": data[0, :],
                        f"{var.lower().replace(' ', '_')}_time": HdfUtils.convert_timesteps_to_datetimes(
                            data[1, :], start_time, time_unit="days", round_to=round_to
                        )
                    })
                    
                elif data.ndim == 1:
                    # Handle 1D datasets (e.g. Cell Last Iteration)
                    df = pd.DataFrame({
                        "mesh_name": [mesh_name] * len(data),
                        "cell_id" if "Face" not in var else "face_id": range(len(data)),
                        var.lower().replace(' ', '_'): data
                    })
                    
                else:
                    raise ValueError(f"Unexpected data shape for {var} in {mesh_name}. "
                                  f"Got shape {data.shape}")
                
                # Add geometry based on variable type
                if "Face" in var:
                    face_df = HdfMesh.get_mesh_cell_faces(hdf_file)
                    if not face_df.empty:
                        df = df.merge(face_df[['mesh_name', 'face_id', 'geometry']], 
                                    on=['mesh_name', 'face_id'], 
                                    how='left')
                else:
                    cell_df = HdfMesh.get_mesh_cell_points(hdf_file)
                    if not cell_df.empty:
                        df = df.merge(cell_df[['mesh_name', 'cell_id', 'geometry']], 
                                    on=['mesh_name', 'cell_id'], 
                                    how='left')
                
                # Add group attributes as metadata with proper decoding
                df.attrs['mesh_name'] = mesh_name
                for attr_name, attr_value in group.attrs.items():
                    if isinstance(attr_value, bytes):
                        # Decode single byte string
                        decoded_value = attr_value.decode('utf-8')
                    elif isinstance(attr_value, np.ndarray):
                        if attr_value.dtype.kind in {'S', 'a'}:  # Array of byte strings
                            # Decode array of byte strings
                            decoded_value = [v.decode('utf-8') if isinstance(v, bytes) else v for v in attr_value]
                        else:
                            # Convert other numpy arrays to list
                            decoded_value = attr_value.tolist()
                    else:
                        decoded_value = attr_value
                    df.attrs[attr_name] = decoded_value
                
                dfs.append(df)
            
            if not dfs:
                return gpd.GeoDataFrame()
                
            result = pd.concat(dfs, ignore_index=True)
            
            # Convert to GeoDataFrame
            gdf = gpd.GeoDataFrame(result, geometry='geometry')
            
            # Get CRS from HdfUtils
            crs = HdfBase.get_projection(hdf_file)
            if crs:
                gdf.set_crs(crs, inplace=True)
            
            # Combine attributes from all meshes with decoded values
            combined_attrs = {}
            for df in dfs:
                for key, value in df.attrs.items():
                    if key not in combined_attrs:
                        combined_attrs[key] = value
                    elif combined_attrs[key] != value:
                        combined_attrs[key] = f"Multiple values: {combined_attrs[key]}, {value}"
            
            gdf.attrs.update(combined_attrs)
            
            logger.info(f"Processed {len(gdf)} rows of summary output data")
            return gdf
        
        except Exception as e:
            logger.error(f"Error processing summary output data: {e}")
            raise ValueError(f"Error processing summary output data: {e}")

    @staticmethod
    def get_mesh_summary_output_group(hdf_file: h5py.File, mesh_name: str, var: str) -> Union[h5py.Group, h5py.Dataset]:
        """
        Return the HDF group for a given mesh and summary output variable.

        Args:
            hdf_path (h5py.File): Open HDF file object.
            mesh_name (str): Name of the mesh.
            var (str): Name of the summary output variable.

        Returns:
            Union[h5py.Group, h5py.Dataset]: The HDF group or dataset for the specified mesh and variable.

        Raises:
            ValueError: If the specified group or dataset is not found in the HDF file.
        """
        output_path = f"Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/{mesh_name}/{var}"
        output_item = hdf_file.get(output_path)
        if output_item is None:
            raise ValueError(f"Dataset not found at path '{output_path}'")
        return output_item

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_boundary_conditions_timeseries(hdf_path: Path) -> xr.Dataset:
        """
        Get timeseries output for all boundary conditions as a single combined xarray Dataset.

        Args:
            hdf_path (Path): Path to the HDF file.

        Returns:
            xr.Dataset: **Multiple variables with shared structure**.
                Use Dataset when returning MULTIPLE variables that share common dimensions.

                Data variables:
                    - stage: Water surface elevation at each BC
                    - flow: Flow at each BC
                    - flow_per_face: Flow distribution across faces (3D)
                    - stage_per_face: Stage distribution across faces (3D)

                Dimensions:
                    - time: Timestamps
                    - bc_name: Boundary condition names
                    - face_id: Face IDs (for per-face variables)

                Coordinates:
                    Metadata from HDF attributes (BC types, locations, etc.)

                When to use: Boundary condition analysis across model.
                All BCs combined in single Dataset for easy comparison.

        Example:
            >>> bc_data = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)
            >>> print(bc_data)
            >>> # Plot flow for all boundary conditions
            >>> bc_data.flow.plot(x='time', hue='bc_name')
            >>> # Extract data for a specific boundary condition
            >>> upstream_data = bc_data.sel(bc_name='Upstream Inflow')
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Get the base path and check if boundary conditions exist
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                bc_base_path = f"{base_path}/Boundary Conditions"
                
                if bc_base_path not in hdf_file:
                    logger.warning(f"No boundary conditions found in HDF file")
                    return xr.Dataset()
                
                # Get timestamps
                start_time = HdfBase.get_simulation_start_time(hdf_file)
                time_data = hdf_file[f"{base_path}/Time"][:]
                timestamps = HdfUtils.convert_timesteps_to_datetimes(time_data, start_time)
                
                # Get all boundary condition names (excluding those with " - Flow per Face" or " - Stage per Face" suffix)
                bc_names = [name for name in hdf_file[bc_base_path].keys() 
                        if " - Flow per Face" not in name and " - Stage per Face" not in name]
                
                if not bc_names:
                    logger.warning(f"No boundary conditions found in HDF file")
                    return xr.Dataset()
                
                # Initialize arrays for main stage and flow data
                num_timesteps = len(timestamps)
                num_bcs = len(bc_names)
                
                stage_data = np.full((num_timesteps, num_bcs), np.nan)
                flow_data = np.full((num_timesteps, num_bcs), np.nan)
                
                # Dictionary to store face-specific data
                face_data = {
                    'flow_per_face': {},
                    'stage_per_face': {}
                }
                
                # Extract metadata from all boundary conditions
                bc_metadata = {}
                
                # Process each boundary condition
                for bc_idx, bc_name in enumerate(bc_names):
                    bc_path = f"{bc_base_path}/{bc_name}"
                    
                    try:
                        # Extract main boundary data
                        bc_data = hdf_file[bc_path][:]
                        bc_attrs = dict(hdf_file[bc_path].attrs)
                        
                        # Store metadata
                        bc_metadata[bc_name] = {
                            k: v.decode('utf-8') if isinstance(v, bytes) else v 
                            for k, v in bc_attrs.items()
                        }
                        
                        # Get column indices for Stage and Flow
                        if 'Columns' in bc_attrs:
                            columns = [col.decode('utf-8') if isinstance(col, bytes) else col 
                                    for col in bc_attrs['Columns']]
                            
                            stage_idx = columns.index('Stage') if 'Stage' in columns else None
                            flow_idx = columns.index('Flow') if 'Flow' in columns else None
                            
                            if stage_idx is not None:
                                stage_data[:, bc_idx] = bc_data[:, stage_idx]
                            if flow_idx is not None:
                                flow_data[:, bc_idx] = bc_data[:, flow_idx]
                        
                        # Extract Flow per Face data
                        flow_face_path = f"{bc_path} - Flow per Face"
                        if flow_face_path in hdf_file:
                            flow_face_data = hdf_file[flow_face_path][:]
                            flow_face_attrs = dict(hdf_file[flow_face_path].attrs)
                            
                            # Get face IDs
                            face_ids = flow_face_attrs.get('Faces', [])
                            if isinstance(face_ids, np.ndarray):
                                face_ids = face_ids.tolist()
                            else:
                                face_ids = list(range(flow_face_data.shape[1]))
                            
                            face_data['flow_per_face'][bc_name] = {
                                'data': flow_face_data,
                                'faces': face_ids,
                                'attrs': {
                                    k: v.decode('utf-8') if isinstance(v, bytes) else v 
                                    for k, v in flow_face_attrs.items()
                                }
                            }
                        
                        # Extract Stage per Face data
                        stage_face_path = f"{bc_path} - Stage per Face"
                        if stage_face_path in hdf_file:
                            stage_face_data = hdf_file[stage_face_path][:]
                            stage_face_attrs = dict(hdf_file[stage_face_path].attrs)
                            
                            # Get face IDs
                            face_ids = stage_face_attrs.get('Faces', [])
                            if isinstance(face_ids, np.ndarray):
                                face_ids = face_ids.tolist()
                            else:
                                face_ids = list(range(stage_face_data.shape[1]))
                            
                            face_data['stage_per_face'][bc_name] = {
                                'data': stage_face_data,
                                'faces': face_ids,
                                'attrs': {
                                    k: v.decode('utf-8') if isinstance(v, bytes) else v 
                                    for k, v in stage_face_attrs.items()
                                }
                            }
                    
                    except Exception as e:
                        logger.warning(f"Error processing boundary condition '{bc_name}': {str(e)}")
                        continue
                
                # Create base dataset with stage and flow data
                ds = xr.Dataset(
                    data_vars={
                        'stage': xr.DataArray(
                            stage_data,
                            dims=['time', 'bc_name'],
                            coords={
                                'time': timestamps,
                                'bc_name': bc_names
                            },
                            attrs={'description': 'Water surface elevation at boundary condition'}
                        ),
                        'flow': xr.DataArray(
                            flow_data,
                            dims=['time', 'bc_name'],
                            coords={
                                'time': timestamps,
                                'bc_name': bc_names
                            },
                            attrs={'description': 'Flow at boundary condition'}
                        )
                    },
                    attrs={
                        'source': 'HEC-RAS HDF Boundary Conditions',
                        'start_time': start_time
                    }
                )
                
                # Add metadata as coordinates
                for key in bc_metadata[bc_names[0]]:
                    if key != 'Columns':  # Skip Columns attribute as it's used for Stage/Flow
                        try:
                            values = [bc_metadata[bc].get(key, '') for bc in bc_names]
                            ds = ds.assign_coords({f'{key.lower()}': ('bc_name', values)})
                        except Exception as e:
                            logger.debug(f"Could not add metadata coordinate '{key}': {str(e)}")
                
                # Add face-specific data variables if available
                if face_data['flow_per_face']:
                    # First determine the maximum number of faces across all BCs
                    all_flow_faces = set()
                    for bc_name in face_data['flow_per_face']:
                        all_flow_faces.update(face_data['flow_per_face'][bc_name]['faces'])
                    
                    # Create a merged array with NaN values for missing faces
                    all_flow_faces = sorted(list(all_flow_faces))
                    flow_face_data = np.full((num_timesteps, num_bcs, len(all_flow_faces)), np.nan)
                    
                    # Fill in the data where available
                    for bc_idx, bc_name in enumerate(bc_names):
                        if bc_name in face_data['flow_per_face']:
                            bc_faces = face_data['flow_per_face'][bc_name]['faces']
                            bc_data = face_data['flow_per_face'][bc_name]['data']
                            
                            for face_idx, face_id in enumerate(bc_faces):
                                if face_id in all_flow_faces:
                                    target_idx = all_flow_faces.index(face_id)
                                    flow_face_data[:, bc_idx, target_idx] = bc_data[:, face_idx]
                    
                    # Add to the dataset
                    ds['flow_per_face'] = xr.DataArray(
                        flow_face_data,
                        dims=['time', 'bc_name', 'face_id'],
                        coords={
                            'time': timestamps,
                            'bc_name': bc_names,
                            'face_id': all_flow_faces
                        },
                        attrs={'description': 'Flow per face at boundary condition'}
                    )
                
                # Similar approach for stage per face
                if face_data['stage_per_face']:
                    all_stage_faces = set()
                    for bc_name in face_data['stage_per_face']:
                        all_stage_faces.update(face_data['stage_per_face'][bc_name]['faces'])
                    
                    all_stage_faces = sorted(list(all_stage_faces))
                    stage_face_data = np.full((num_timesteps, num_bcs, len(all_stage_faces)), np.nan)
                    
                    for bc_idx, bc_name in enumerate(bc_names):
                        if bc_name in face_data['stage_per_face']:
                            bc_faces = face_data['stage_per_face'][bc_name]['faces']
                            bc_data = face_data['stage_per_face'][bc_name]['data']
                            
                            for face_idx, face_id in enumerate(bc_faces):
                                if face_id in all_stage_faces:
                                    target_idx = all_stage_faces.index(face_id)
                                    stage_face_data[:, bc_idx, target_idx] = bc_data[:, face_idx]
                    
                    ds['stage_per_face'] = xr.DataArray(
                        stage_face_data,
                        dims=['time', 'bc_name', 'face_id'],
                        coords={
                            'time': timestamps,
                            'bc_name': bc_names,
                            'face_id': all_stage_faces
                        },
                        attrs={'description': 'Water surface elevation per face at boundary condition'}
                    )
                
                return ds
                
        except Exception as e:
            logger.error(f"Error getting all boundary conditions timeseries: {str(e)}")
            return xr.Dataset()
