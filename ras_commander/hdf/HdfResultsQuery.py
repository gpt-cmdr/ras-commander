"""
Spatial queries on HEC-RAS 2D simulation results.

Probe WSE/depth/velocity at arbitrary coordinates, extract profiles
along transects, compute flood extent, and generate domain statistics.
Uses scipy KDTree for spatial indexing -- no VTK dependency.

All methods are static. Do not instantiate.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import logging
import re

import h5py
import numpy as np
import pandas as pd
from scipy.spatial import KDTree

from .HdfMesh import HdfMesh
from .HdfPlan import HdfPlan
from .HdfResultsMesh import HdfResultsMesh
from .HdfResultsPlan import HdfResultsPlan
from ..Decorators import standardize_input, log_call
from ..RasPrj import ras

logger = logging.getLogger(__name__)

VARIABLE_MAP = {
    "wse": "Water Surface",
    "water_surface": "Water Surface",
    "depth": "Depth",
    "velocity": "Velocity",
    "velocity_x": "Velocity X",
    "velocity_y": "Velocity Y",
}

_kdtree_cache: Dict[str, Dict[str, Any]] = {}

_UNSTEADY_2D_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series/2D Flow Areas/{mesh_name}/{variable_name}"
)

_STEADY_2D_CANDIDATES = [
    (
        "Results/Steady/Output/Output Blocks/Base Output/"
        "Steady Profiles/2D Flow Areas/{mesh_name}/{variable_name}"
    ),
    (
        "Results/Steady/Output/Output Blocks/Base Output/"
        "2D Flow Areas/{mesh_name}/{variable_name}"
    ),
]


def _normalize_variable(variable: str) -> str:
    """Normalize friendly variable aliases to HDF dataset names."""
    if not isinstance(variable, str) or not variable.strip():
        raise ValueError("variable must be a non-empty string")

    cleaned = variable.strip()
    alias = cleaned.lower().replace(" ", "_")
    if alias in VARIABLE_MAP:
        return VARIABLE_MAP[alias]

    for canonical in set(VARIABLE_MAP.values()):
        if cleaned.lower() == canonical.lower():
            return canonical

    valid = sorted(VARIABLE_MAP.keys())
    raise ValueError(
        f"Unsupported variable '{variable}'. Valid aliases: {valid}"
    )


def _extract_geometry_number(raw_value: Any) -> Optional[str]:
    """Extract a 2-digit geometry number from common plan metadata formats."""
    if raw_value is None:
        return None

    if isinstance(raw_value, (bytes, np.bytes_)):
        raw_value = raw_value.decode("utf-8", errors="ignore")

    try:
        if pd.isna(raw_value):
            return None
    except Exception:
        pass

    text = str(raw_value).strip()
    if not text or text.lower() == "none":
        return None

    candidates = [text, Path(text).stem, Path(text).name]
    patterns = [r"\.g(\d{1,2})$", r"^g(\d{1,2})$", r"^(\d{1,2})$"]

    for candidate in candidates:
        for pattern in patterns:
            match = re.search(pattern, candidate, flags=re.IGNORECASE)
            if match:
                return match.group(1).zfill(2)

    return None


def _project_name_from_plan_hdf(plan_hdf_path: Path) -> str:
    """Derive project name from a standard Project.p##.hdf filename."""
    stem = plan_hdf_path.stem
    match = re.match(r"(.+)\.p\d{2}$", stem, flags=re.IGNORECASE)
    return match.group(1) if match else stem


def _paths_match(path_a: Any, path_b: Any) -> bool:
    """Compare paths without forcing symlink or UNC resolution."""
    try:
        return Path(str(path_a)).absolute() == Path(str(path_b)).absolute()
    except Exception:
        return False


def _get_global_ras() -> Any:
    """Return the global ras object if available."""
    return ras


def _resolve_geometry_hdf(
    plan_hdf_path: Union[str, Path],
    ras_object: Optional[Any] = None,
) -> Path:
    """
    Resolve a plan HDF path to its companion geometry HDF path.

    Resolution order:
    1. HDF Plan Information attribute ('Geometry File' / 'Geom File')
    2. Current ras object's plan_df / geom_df metadata (if initialized)

    Returns:
        Path to the geometry HDF file (.g##.hdf)
    """
    plan_hdf_path = Path(plan_hdf_path)
    project_folder = plan_hdf_path.parent
    project_name = _project_name_from_plan_hdf(plan_hdf_path)

    try:
        with h5py.File(plan_hdf_path, "r") as hdf_file:
            if (
                "Geometry/2D Flow Areas" in hdf_file
                or "Geometry/Pipe Networks" in hdf_file
            ):
                return plan_hdf_path
    except Exception:
        pass

    try:
        plan_info = HdfPlan.get_plan_information(plan_hdf_path)
        for key in ("Geometry File", "Geom File", "Geometry Filename"):
            geom_number = _extract_geometry_number(plan_info.get(key))
            if geom_number:
                geom_hdf_path = (
                    project_folder / f"{project_name}.g{geom_number}.hdf"
                )
                if geom_hdf_path.exists():
                    return geom_hdf_path
                raise FileNotFoundError(
                    f"Geometry HDF not found: {geom_hdf_path}"
                )
    except Exception:
        pass

    _ras = ras_object if ras_object is not None else _get_global_ras()
    plan_df = getattr(_ras, "plan_df", None)
    geom_df = getattr(_ras, "geom_df", None)

    if plan_df is not None and len(plan_df) > 0:
        plan_row = pd.DataFrame()

        if "HDF_Results_Path" in plan_df.columns:
            mask = plan_df["HDF_Results_Path"].notna() & plan_df[
                "HDF_Results_Path"
            ].map(lambda value: _paths_match(value, plan_hdf_path))
            plan_row = plan_df[mask]

        if plan_row.empty:
            plan_match = re.search(
                r"\.p(\d{2})$",
                plan_hdf_path.stem,
                flags=re.IGNORECASE,
            )
            if plan_match and "plan_number" in plan_df.columns:
                plan_number = plan_match.group(1)
                mask = (
                    plan_df["plan_number"]
                    .astype(str)
                    .str.zfill(2)
                    .eq(plan_number)
                )
                plan_row = plan_df[mask]

        if not plan_row.empty:
            row = plan_row.iloc[0]

            geom_path_value = row.get("Geom Path")
            if pd.notna(geom_path_value):
                geom_base = Path(str(geom_path_value))
                geom_hdf_path = geom_base.parent / f"{geom_base.name}.hdf"
                if geom_hdf_path.exists():
                    return geom_hdf_path

            geom_number = _extract_geometry_number(row.get("Geom File"))
            if geom_number is None:
                geom_number = _extract_geometry_number(
                    row.get("geometry_number")
                )

            if geom_number:
                if getattr(_ras, "project_folder", None) is not None:
                    project_folder = Path(_ras.project_folder)
                if getattr(_ras, "project_name", None):
                    project_name = str(_ras.project_name)

                if geom_df is not None and len(geom_df) > 0:
                    geom_mask = (
                        geom_df["geom_number"]
                        .astype(str)
                        .str.zfill(2)
                        .eq(geom_number)
                    )
                    geom_rows = geom_df[geom_mask]
                    if (
                        not geom_rows.empty
                        and "hdf_path" in geom_rows.columns
                        and pd.notna(geom_rows.iloc[0]["hdf_path"])
                    ):
                        geom_hdf_path = Path(str(geom_rows.iloc[0]["hdf_path"]))
                        if geom_hdf_path.exists():
                            return geom_hdf_path

                geom_hdf_path = (
                    project_folder / f"{project_name}.g{geom_number}.hdf"
                )
                if geom_hdf_path.exists():
                    return geom_hdf_path
                raise FileNotFoundError(
                    f"Geometry HDF not found: {geom_hdf_path}"
                )

    raise FileNotFoundError(
        "Could not resolve geometry HDF from plan HDF. "
        "Expected a valid 'Geometry File' plan attribute or plan_df entry."
    )


def _get_kdtree(
    geom_hdf_path: Union[str, Path],
    ras_object: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build and cache a KDTree over all mesh cell centers in the geometry HDF."""
    geom_hdf_path = Path(geom_hdf_path)
    cache_key = str(geom_hdf_path.absolute())

    if cache_key in _kdtree_cache:
        return _kdtree_cache[cache_key]

    cell_points = HdfMesh.get_mesh_cell_points(geom_hdf_path)
    if cell_points.empty:
        raise ValueError(
            f"No 2D mesh cell centers found in geometry HDF: {geom_hdf_path}"
        )

    coords = np.column_stack(
        (
            cell_points.geometry.x.to_numpy(dtype=float),
            cell_points.geometry.y.to_numpy(dtype=float),
        )
    )
    mesh_names = cell_points["mesh_name"].astype(str).to_numpy()
    cell_ids = cell_points["cell_id"].to_numpy(dtype=int)

    mesh_order: List[str] = []
    mesh_slices: Dict[str, slice] = {}
    start = 0
    for mesh_name, group in cell_points.groupby("mesh_name", sort=False):
        count = len(group)
        mesh_name = str(mesh_name)
        mesh_order.append(mesh_name)
        mesh_slices[mesh_name] = slice(start, start + count)
        start += count

    cache_entry = {
        "tree": KDTree(coords),
        "coords": coords,
        "mesh_names": mesh_names,
        "cell_ids": cell_ids,
        "mesh_order": mesh_order,
        "mesh_slices": mesh_slices,
    }
    _kdtree_cache[cache_key] = cache_entry
    return cache_entry


def _coerce_points_dataframe(points: Any) -> pd.DataFrame:
    """Convert supported point inputs to a simple x/y DataFrame."""
    if hasattr(points, "geometry"):
        if len(points) == 0:
            return pd.DataFrame(columns=["x", "y"])
        geom = points.geometry
        if not all(getattr(g, "geom_type", None) == "Point" for g in geom):
            raise ValueError("GeoDataFrame input must contain Point geometries")
        return pd.DataFrame(
            {
                "x": geom.x.to_numpy(dtype=float),
                "y": geom.y.to_numpy(dtype=float),
            }
        )

    array = np.asarray(points, dtype=float)
    if array.ndim == 1:
        if array.size != 2:
            raise ValueError(
                "Points array must have shape (N, 2) or represent a single "
                "(x, y) pair"
            )
        array = array.reshape(1, 2)

    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("Points input must have shape (N, 2)")

    return pd.DataFrame(array, columns=["x", "y"])


def _read_geometry_cell_dataset(
    geom_hdf_path: Path,
    cache: Dict[str, Any],
    dataset_name: str,
) -> np.ndarray:
    """Read a per-cell geometry dataset and concatenate in KDTree order."""
    values: List[np.ndarray] = []
    with h5py.File(geom_hdf_path, "r") as hdf_file:
        for mesh_name in cache["mesh_order"]:
            dataset_path = (
                f"Geometry/2D Flow Areas/{mesh_name}/{dataset_name}"
            )
            if dataset_path not in hdf_file:
                raise KeyError(
                    f"Dataset not found in geometry HDF: {dataset_path}"
                )
            mesh_values = np.asarray(hdf_file[dataset_path][()], dtype=float)
            values.append(mesh_values)

    return np.concatenate(values) if values else np.array([], dtype=float)


def _select_time_slice(values: np.ndarray, time_index: int) -> np.ndarray:
    """Return one timestep from a (time, cell) array, handling negative indices."""
    if values.ndim == 1:
        return np.asarray(values, dtype=float)

    if values.ndim != 2:
        raise ValueError(
            f"Expected a 1D or 2D array, got shape {values.shape}"
        )

    n_times = values.shape[0]
    idx = int(time_index)
    if idx < 0:
        idx += n_times
    if idx < 0 or idx >= n_times:
        raise IndexError(
            f"time_index {time_index} is out of bounds for {n_times} timesteps"
        )

    return np.asarray(values[idx, :], dtype=float)


def _collapse_steady_dataset(
    values: np.ndarray,
    mesh_name: str,
    variable_name: str,
) -> np.ndarray:
    """
    Collapse steady 2D output to a single per-cell array.

    If multiple steady profiles are present, the last profile is used because
    query methods do not currently expose a profile selector.
    """
    if values.ndim == 1:
        return np.asarray(values, dtype=float)

    if values.ndim == 2:
        if values.shape[0] > 1:
            logger.info(
                "Steady 2D dataset for mesh '%s' variable '%s' contains "
                "%s profiles; using the last profile.",
                mesh_name,
                variable_name,
                values.shape[0],
            )
        return np.asarray(values[-1, :], dtype=float)

    raise ValueError(
        f"Unsupported steady 2D dataset shape for {mesh_name} "
        f"{variable_name}: {values.shape}"
    )


def _read_steady_mesh_dataset(
    hdf_file: h5py.File,
    mesh_name: str,
    variable_name: str,
) -> np.ndarray:
    """Read a steady 2D dataset from one of the known candidate locations."""
    for template in _STEADY_2D_CANDIDATES:
        dataset_path = template.format(
            mesh_name=mesh_name,
            variable_name=variable_name,
        )
        if dataset_path in hdf_file:
            return np.asarray(hdf_file[dataset_path][()], dtype=float)

    raise KeyError(
        "Steady 2D dataset not found for "
        f"mesh '{mesh_name}', variable '{variable_name}'."
    )


def _get_steady_variable_values(
    plan_hdf_path: Path,
    geom_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
) -> np.ndarray:
    """Read steady 2D mesh values, ignoring time_index as required."""
    logger.debug("Steady plan detected; time_index is ignored.")

    values: List[np.ndarray] = []
    cell_min_elev = None

    with h5py.File(plan_hdf_path, "r") as hdf_file:
        for mesh_name in cache["mesh_order"]:
            if variable_name == "Depth":
                ws_values = _read_steady_mesh_dataset(
                    hdf_file,
                    mesh_name,
                    "Water Surface",
                )
                ws_values = _collapse_steady_dataset(
                    ws_values,
                    mesh_name,
                    "Water Surface",
                )
                if cell_min_elev is None:
                    cell_min_elev = _read_geometry_cell_dataset(
                        geom_hdf_path,
                        cache,
                        "Cells Minimum Elevation",
                    )
                mesh_slice = cache["mesh_slices"][mesh_name]
                mesh_bed = cell_min_elev[mesh_slice]
                values.append(np.maximum(ws_values - mesh_bed, 0.0))
                continue

            mesh_values = _read_steady_mesh_dataset(
                hdf_file,
                mesh_name,
                variable_name,
            )
            mesh_values = _collapse_steady_dataset(
                mesh_values,
                mesh_name,
                variable_name,
            )
            values.append(mesh_values)

    return np.concatenate(values) if values else np.array([], dtype=float)


def _read_unsteady_direct(
    plan_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
    time_index: int,
) -> np.ndarray:
    """Read one timestep of an unsteady 2D result directly from HDF."""
    values: List[np.ndarray] = []

    with h5py.File(plan_hdf_path, "r") as hdf_file:
        for mesh_name in cache["mesh_order"]:
            dataset_path = _UNSTEADY_2D_PATH.format(
                mesh_name=mesh_name,
                variable_name=variable_name,
            )
            if dataset_path not in hdf_file:
                raise KeyError(
                    f"Dataset not found in plan HDF: {dataset_path}"
                )
            dataset_values = np.asarray(hdf_file[dataset_path][()], dtype=float)
            values.append(_select_time_slice(dataset_values, time_index))

    return np.concatenate(values) if values else np.array([], dtype=float)


def _get_unsteady_variable_values(
    plan_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
    time_index: int,
    geom_hdf_path: Optional[Path] = None,
) -> np.ndarray:
    """Read one timestep of a cell-centered unsteady 2D result variable.

    Falls back to computed values when the requested variable is not stored
    directly in the plan HDF (e.g., Depth from WSE minus cell min elevation,
    Velocity magnitude from X/Y components).
    """
    try:
        return _read_unsteady_direct(
            plan_hdf_path, cache, variable_name, time_index,
        )
    except KeyError as exc:
        direct_read_error = exc

    if variable_name == "Depth":
        if geom_hdf_path is None:
            raise KeyError(
                "Variable 'Depth' not found in plan HDF and geometry HDF "
                "path was not provided for fallback computation."
            ) from direct_read_error
        logger.debug(
            "'Depth' dataset not found; computing from Water Surface "
            "minus Cells Minimum Elevation."
        )
        wse = _read_unsteady_direct(
            plan_hdf_path, cache, "Water Surface", time_index,
        )
        cell_min_elev = _read_geometry_cell_dataset(
            geom_hdf_path, cache, "Cells Minimum Elevation",
        )
        return np.maximum(wse - cell_min_elev, 0.0)

    if variable_name == "Velocity":
        try:
            logger.debug(
                "'Velocity' dataset not found; computing from Velocity X "
                "and Velocity Y."
            )
            vx = _read_unsteady_direct(
                plan_hdf_path, cache, "Velocity X", time_index,
            )
            vy = _read_unsteady_direct(
                plan_hdf_path, cache, "Velocity Y", time_index,
            )
            return np.sqrt(vx**2 + vy**2)
        except KeyError:
            logger.warning(
                "Neither 'Velocity' nor 'Velocity X'/'Velocity Y' found "
                "in plan HDF time series. Returning NaN. Use "
                "time_index='max' for velocity from face envelope data."
            )
            return np.full(len(cache["cell_ids"]), np.nan)

    raise KeyError(
        f"Variable '{variable_name}' not found in plan HDF and no "
        "fallback is available."
    ) from direct_read_error


def _get_unsteady_variable_max_values(
    plan_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
) -> np.ndarray:
    """Read per-cell maximum values directly from the unsteady time series."""
    values: List[np.ndarray] = []

    with h5py.File(plan_hdf_path, "r") as hdf_file:
        for mesh_name in cache["mesh_order"]:
            dataset_path = _UNSTEADY_2D_PATH.format(
                mesh_name=mesh_name,
                variable_name=variable_name,
            )
            if dataset_path not in hdf_file:
                raise KeyError(
                    f"Dataset not found in plan HDF: {dataset_path}"
                )
            dataset_values = np.asarray(hdf_file[dataset_path][()], dtype=float)
            if dataset_values.ndim == 1:
                mesh_values = dataset_values
            elif dataset_values.ndim == 2:
                mesh_values = np.nanmax(dataset_values, axis=0)
            else:
                raise ValueError(
                    f"Unsupported dataset shape for {dataset_path}: "
                    f"{dataset_values.shape}"
                )
            values.append(np.asarray(mesh_values, dtype=float))

    return np.concatenate(values) if values else np.array([], dtype=float)


def _summary_values_by_mesh(
    summary_df: pd.DataFrame,
    value_column: str,
    cache: Dict[str, Any],
) -> np.ndarray:
    """Concatenate summary-output values in the same order as KDTree cells."""
    values: List[np.ndarray] = []

    for mesh_name in cache["mesh_order"]:
        mesh_df = (
            summary_df[summary_df["mesh_name"] == mesh_name]
            .sort_values("cell_id")
            .reset_index(drop=True)
        )
        expected_count = (
            cache["mesh_slices"][mesh_name].stop
            - cache["mesh_slices"][mesh_name].start
        )
        if len(mesh_df) != expected_count:
            raise ValueError(
                f"Summary output count mismatch for mesh '{mesh_name}': "
                f"expected {expected_count}, found {len(mesh_df)}"
            )
        values.append(mesh_df[value_column].to_numpy(dtype=float))

    return np.concatenate(values) if values else np.array([], dtype=float)


def _get_max_wse_values(
    plan_hdf_path: Path,
    cache: Dict[str, Any],
) -> np.ndarray:
    """Return maximum water surface values in KDTree order."""
    max_ws = HdfResultsMesh.get_mesh_max_ws(plan_hdf_path)
    if max_ws.empty:
        raise ValueError("Maximum Water Surface summary output is empty")
    return _summary_values_by_mesh(
        max_ws,
        "maximum_water_surface",
        cache,
    )


def _get_cell_averaged_max_velocity(
    plan_hdf_path: Path,
    geom_hdf_path: Path,
    cache: Dict[str, Any],
) -> np.ndarray:
    """
    Approximate cell-centered maximum velocity using average max face velocity.

    This follows the QA guidance to use Maximum Face Velocity envelope data,
    then map those face values back to cells using mesh topology.
    """
    max_face_v = HdfResultsMesh.get_mesh_max_face_v(plan_hdf_path)
    if max_face_v.empty:
        raise ValueError("Maximum Face Velocity summary output is empty")

    values: List[np.ndarray] = []
    with h5py.File(geom_hdf_path, "r") as geom_hdf:
        for mesh_name in cache["mesh_order"]:
            mesh_faces = max_face_v[max_face_v["mesh_name"] == mesh_name]
            if mesh_faces.empty:
                raise ValueError(
                    f"No Maximum Face Velocity rows found for mesh '{mesh_name}'"
                )

            max_face_id = int(mesh_faces["face_id"].max())
            face_values = np.full(max_face_id + 1, np.nan, dtype=float)
            face_ids = mesh_faces["face_id"].to_numpy(dtype=int)
            face_values[face_ids] = mesh_faces[
                "maximum_face_velocity"
            ].to_numpy(dtype=float)

            info_path = (
                f"Geometry/2D Flow Areas/{mesh_name}/"
                "Cells Face and Orientation Info"
            )
            values_path = (
                f"Geometry/2D Flow Areas/{mesh_name}/"
                "Cells Face and Orientation Values"
            )
            if info_path not in geom_hdf or values_path not in geom_hdf:
                raise KeyError(
                    f"Missing cell-face topology datasets for mesh '{mesh_name}'"
                )

            cell_face_info = geom_hdf[info_path][()]
            cell_face_values = geom_hdf[values_path][()][:, 0].astype(int)

            mesh_cell_values = np.full(len(cell_face_info), np.nan, dtype=float)
            for cell_id, (start, count) in enumerate(cell_face_info[:, :2]):
                face_subset = cell_face_values[start : start + count]
                face_subset = face_subset[
                    (face_subset >= 0) & (face_subset < len(face_values))
                ]
                if len(face_subset) > 0:
                    mesh_cell_values[cell_id] = np.nanmean(
                        face_values[face_subset]
                    )

            values.append(mesh_cell_values)

    return np.concatenate(values) if values else np.array([], dtype=float)


def _get_max_envelope_values(
    plan_hdf_path: Path,
    geom_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
) -> np.ndarray:
    """Return maximum-envelope values for supported variables."""
    if variable_name == "Water Surface":
        return _get_max_wse_values(plan_hdf_path, cache)

    if variable_name == "Depth":
        max_ws = _get_max_wse_values(plan_hdf_path, cache)
        cell_min_elev = _read_geometry_cell_dataset(
            geom_hdf_path,
            cache,
            "Cells Minimum Elevation",
        )
        return np.maximum(max_ws - cell_min_elev, 0.0)

    if variable_name == "Velocity":
        return _get_cell_averaged_max_velocity(
            plan_hdf_path,
            geom_hdf_path,
            cache,
        )

    return _get_unsteady_variable_max_values(
        plan_hdf_path,
        cache,
        variable_name,
    )


def _get_variable_values(
    plan_hdf_path: Path,
    geom_hdf_path: Path,
    cache: Dict[str, Any],
    variable_name: str,
    time_index: Union[int, str],
    steady_plan: bool,
) -> np.ndarray:
    """Return one value per cell in KDTree order for the requested variable."""
    if steady_plan:
        return _get_steady_variable_values(
            plan_hdf_path,
            geom_hdf_path,
            cache,
            variable_name,
        )

    if time_index == "max":
        return _get_max_envelope_values(
            plan_hdf_path,
            geom_hdf_path,
            cache,
            variable_name,
        )

    if not isinstance(time_index, (int, np.integer)):
        raise ValueError(
            "time_index must be an integer or the string 'max'"
        )

    return _get_unsteady_variable_values(
        plan_hdf_path,
        cache,
        variable_name,
        int(time_index),
        geom_hdf_path=geom_hdf_path,
    )


def _validate_value_length(
    values: np.ndarray,
    cache: Dict[str, Any],
    variable_name: str,
) -> None:
    """Ensure a variable array aligns with the cached KDTree cell count."""
    expected = len(cache["cell_ids"])
    actual = len(values)
    if actual != expected:
        raise ValueError(
            f"Variable '{variable_name}' returned {actual} values but the "
            f"KDTree contains {expected} cells"
        )


def _decode_hdf_attr(value: Any) -> Any:
    """Decode common byte-valued HDF attributes."""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="ignore")
    return value


def _read_unit_metadata(geom_hdf_path: Path) -> Dict[str, str]:
    """Read project unit metadata from a geometry HDF."""
    raw_si_units = None
    raw_unit_system = None
    with h5py.File(geom_hdf_path, "r") as hdf_file:
        geometry_group = hdf_file.get("Geometry")
        if geometry_group is not None:
            raw_si_units = _decode_hdf_attr(geometry_group.attrs.get("SI Units"))
        raw_unit_system = _decode_hdf_attr(hdf_file.attrs.get("Units System"))

    unit_text = str(raw_unit_system or "").strip().lower()
    si_units = str(raw_si_units).strip().lower() in {
        "true",
        "1",
        "yes",
        "si",
    } or unit_text.startswith("si")

    length_units = "m" if si_units else "ft"
    return {
        "unit_system": "SI" if si_units else "US Customary",
        "length_units": length_units,
        "velocity_units": "m/s" if si_units else "ft/s",
        "depth_units": length_units,
    }


def _read_ras_version(plan_hdf_path: Path) -> Optional[str]:
    """Read a compact HEC-RAS version string from a plan HDF."""
    candidates: List[Any] = []
    with h5py.File(plan_hdf_path, "r") as hdf_file:
        candidates.extend(
            [
                hdf_file.attrs.get("File Version"),
                hdf_file.attrs.get("Program Version"),
            ]
        )
        for path in ("Results/Unsteady", "Results/Steady"):
            if path in hdf_file:
                candidates.extend(
                    [
                        hdf_file[path].attrs.get("Program Version"),
                        hdf_file[path].attrs.get("File Version"),
                    ]
                )

    for value in candidates:
        text = str(_decode_hdf_attr(value) or "").strip()
        match = re.search(r"(\d+\.\d+)", text)
        if match:
            return match.group(1)
    return None


def _coerce_linestring(polyline: Any):
    """Validate and normalize a shapely LineString-like input."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    if getattr(polyline, "geom_type", None) == "LinearRing":
        polyline = LineString(polyline)
    elif isinstance(polyline, MultiLineString):
        polyline = linemerge(polyline)
        if getattr(polyline, "geom_type", None) == "MultiLineString":
            polyline = max(polyline.geoms, key=lambda geom: geom.length)
    elif not isinstance(polyline, LineString):
        try:
            polyline = LineString(polyline)
        except Exception as exc:
            raise ValueError(
                "polyline must be a shapely LineString or coordinate sequence"
            ) from exc

    if polyline.is_empty or not np.isfinite(polyline.length) or polyline.length <= 0:
        raise ValueError("polyline must have positive length")

    return polyline


def _resolve_profile_sample_spacing(sample_spacing: Optional[float]) -> float:
    """Validate explicit sample spacing or use the RAS Mapper fixture default."""
    spacing = 50.0 if sample_spacing is None else float(sample_spacing)
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("sample_spacing must be a positive finite value")
    return spacing


def _reject_unsupported_2d_bridge_meshes(
    plan_hdf_path: Path,
    mesh_names: List[str],
) -> None:
    """Reject HDFs with native 2D bridge velocity output groups."""
    with h5py.File(plan_hdf_path, "r") as hdf_file:
        if "Geometry/2D Bridges" in hdf_file or "Geometry/2D Bridge" in hdf_file:
            raise NotImplementedError(
                "2D bridge velocity profile extraction is not supported. "
                "RAS Mapper uses VelocityRenderer2DBridge for those meshes."
            )

        for mesh_name in mesh_names:
            base_path = (
                "Results/Unsteady/Output/Output Blocks/Base Output/"
                "Unsteady Time Series/2D Flow Areas/"
                f"{mesh_name}"
            )
            if base_path not in hdf_file:
                continue
            group_names = {name.lower() for name in hdf_file[base_path].keys()}
            if {"2d bridge", "2d bridges"} & group_names:
                raise NotImplementedError(
                    "2D bridge velocity profile extraction is not supported. "
                    "RAS Mapper uses VelocityRenderer2DBridge for those meshes."
                )


def _polyline_profile_inputs(
    hdf_path: Path,
    polyline: Any,
    sample_spacing: Optional[float],
    terrain_raster: Optional[Union[str, Path]],
    ras_object: Optional[Any],
) -> tuple[np.ndarray, Path, float, Optional[Path]]:
    """Resolve common HDF, geometry, polyline, spacing, and terrain inputs."""
    geom_hdf_path = _resolve_geometry_hdf(hdf_path, ras_object=ras_object)
    mesh_names = HdfMesh.get_mesh_area_names(geom_hdf_path)
    _reject_unsupported_2d_bridge_meshes(hdf_path, mesh_names)

    line = _coerce_linestring(polyline)
    coords = np.asarray(line.coords, dtype=float)
    if coords.ndim != 2 or coords.shape[1] < 2:
        raise ValueError("polyline must provide at least x/y coordinates")

    terrain_hdf_path = Path(terrain_raster) if terrain_raster is not None else None
    return (
        coords[:, :2],
        geom_hdf_path,
        _resolve_profile_sample_spacing(sample_spacing),
        terrain_hdf_path,
    )


def _profile_dataframe(
    profile_data: Dict[str, Any],
    columns: List[str],
    hdf_path: Path,
    geom_hdf_path: Path,
    sample_spacing: float,
    source_key: str,
    source_value: str,
) -> pd.DataFrame:
    """Build a profile DataFrame with standard RAS metadata attrs."""
    result_df = pd.DataFrame({column: profile_data[column] for column in columns})
    result_df.attrs.update(_read_unit_metadata(geom_hdf_path))
    result_df.attrs["sample_spacing"] = float(sample_spacing)
    result_df.attrs[source_key] = [source_value]
    result_df.attrs["ras_version"] = _read_ras_version(hdf_path)
    return result_df[columns]


def _timeseries_dataframe(
    profile_data: Dict[str, Any],
    columns: List[str],
    hdf_path: Path,
    geom_hdf_path: Path,
    sample_spacing: float,
    source_key: str,
    source_value: str,
    value_column: str,
    wide: bool,
) -> pd.DataFrame:
    """Build a long or station-by-time profile time-series DataFrame."""
    result_df = _profile_dataframe(
        profile_data,
        columns,
        hdf_path,
        geom_hdf_path,
        sample_spacing,
        source_key,
        source_value,
    )
    parsed_time = pd.to_datetime(
        result_df["time"],
        format="%d%b%Y %H:%M:%S:%f",
        errors="coerce",
    )
    if parsed_time.notna().any():
        result_df["time"] = parsed_time
    if wide:
        return result_df.pivot_table(
            index="station",
            columns="time_index",
            values=value_column,
            aggfunc="first",
        )
    return result_df


def _warn_on_large_distances(distances: np.ndarray) -> None:
    """Warn when nearest-cell distances suggest a CRS mismatch."""
    distances = np.asarray(distances, dtype=float)
    large = distances > 1000.0
    if not np.any(large):
        return

    count = int(np.sum(large))
    max_distance = float(np.max(distances[large]))
    logger.warning(
        "Nearest-cell distance exceeds 1000 model units for %s query "
        "point(s) (max distance %.2f). This often indicates a CRS mismatch.",
        count,
        max_distance,
    )


def _safe_stat(values: np.ndarray, func: Any) -> float:
    """Apply a NumPy reduction only to finite values."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    return float(func(finite))


def _idw_query(
    tree: KDTree,
    values: np.ndarray,
    point: np.ndarray,
    k: int = 4,
    power: int = 2,
) -> float:
    """Inverse-distance-weighted interpolation from nearest cells."""
    if len(values) == 0:
        return float("nan")

    k = min(k, len(values))
    distances, indices = tree.query(point, k=k)
    distances = np.atleast_1d(np.asarray(distances, dtype=float))
    indices = np.atleast_1d(np.asarray(indices, dtype=int))

    if distances[0] == 0:
        return float(values[indices[0]])

    neighbor_values = np.asarray(values[indices], dtype=float)
    valid = np.isfinite(neighbor_values) & np.isfinite(distances)
    if not np.any(valid):
        return float("nan")

    distances = distances[valid]
    neighbor_values = neighbor_values[valid]

    weights = 1.0 / np.power(distances, power)
    weights /= weights.sum()
    return float(np.dot(weights, neighbor_values))


def _query_points_core(
    plan_hdf_path: Path,
    points_df: pd.DataFrame,
    variable: str,
    time_index: Union[int, str],
    method: str,
    ras_object: Optional[Any] = None,
) -> pd.DataFrame:
    """Shared implementation for single-point and batch point queries."""
    method = method.lower().strip()
    if method not in {"nearest", "idw"}:
        raise ValueError("method must be 'nearest' or 'idw'")

    variable_name = _normalize_variable(variable)
    geom_hdf_path = _resolve_geometry_hdf(plan_hdf_path, ras_object=ras_object)
    cache = _get_kdtree(geom_hdf_path, ras_object=ras_object)
    steady_plan = HdfResultsPlan.is_steady_plan(plan_hdf_path)

    values = _get_variable_values(
        plan_hdf_path,
        geom_hdf_path,
        cache,
        variable_name,
        time_index,
        steady_plan,
    )
    _validate_value_length(values, cache, variable_name)

    query_coords = points_df[["x", "y"]].to_numpy(dtype=float)
    distances, indices = cache["tree"].query(query_coords, k=1)
    distances = np.atleast_1d(np.asarray(distances, dtype=float))
    indices = np.atleast_1d(np.asarray(indices, dtype=int))

    if method == "nearest":
        queried_values = values[indices]
    else:
        queried_values = np.array(
            [_idw_query(cache["tree"], values, point) for point in query_coords],
            dtype=float,
        )

    _warn_on_large_distances(distances)

    return pd.DataFrame(
        {
            "x": query_coords[:, 0],
            "y": query_coords[:, 1],
            "value": queried_values.astype(float),
            "cell_id": cache["cell_ids"][indices].astype(int),
            "mesh_name": cache["mesh_names"][indices].astype(str),
            "distance": distances.astype(float),
        }
    )


class HdfResultsQuery:
    """Spatial query utilities for 2D HEC-RAS results."""

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_point(
        hdf_path: Path,
        x: float,
        y: float,
        variable: str = "wse",
        time_index: Union[int, str] = -1,
        method: str = "nearest",
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Query one arbitrary point against the nearest mesh cell or IDW.

        Returns:
            dict with keys: value, cell_id, mesh_name, distance, x, y
        """
        points_df = pd.DataFrame({"x": [float(x)], "y": [float(y)]})
        result_df = _query_points_core(
            hdf_path,
            points_df,
            variable,
            time_index,
            method,
            ras_object=ras_object,
        )
        row = result_df.iloc[0]
        return {
            "value": float(row["value"]),
            "cell_id": int(row["cell_id"]),
            "mesh_name": str(row["mesh_name"]),
            "distance": float(row["distance"]),
            "x": float(row["x"]),
            "y": float(row["y"]),
        }

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_points(
        hdf_path: Path,
        points: Any,
        variable: str = "wse",
        time_index: Union[int, str] = -1,
        method: str = "nearest",
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Query many points against the nearest mesh cells in one call.

        Accepted point formats:
        - list of (x, y) tuples
        - numpy array with shape (N, 2)
        - GeoDataFrame with Point geometries
        """
        points_df = _coerce_points_dataframe(points)
        result_df = _query_points_core(
            hdf_path,
            points_df,
            variable,
            time_index,
            method,
            ras_object=ras_object,
        )
        return result_df[
            ["x", "y", "value", "cell_id", "mesh_name", "distance"]
        ]

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_profile(
        hdf_path: Path,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        variable: str = "wse",
        n_points: int = 100,
        time_index: Union[int, str] = -1,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Sample evenly spaced points along a transect.

        Returns:
            DataFrame with station, x, y, value, cell_id, mesh_name, distance
        """
        n_points = int(n_points)
        if n_points <= 0:
            raise ValueError("n_points must be a positive integer")

        fractions = np.linspace(0.0, 1.0, n_points)
        xs = x1 + (x2 - x1) * fractions
        ys = y1 + (y2 - y1) * fractions
        stations = np.linspace(
            0.0,
            float(np.hypot(x2 - x1, y2 - y1)),
            n_points,
        )

        points_df = HdfResultsQuery.query_points(
            hdf_path,
            np.column_stack((xs, ys)),
            variable=variable,
            time_index=time_index,
            method="nearest",
            ras_object=ras_object,
        )
        points_df.insert(0, "station", stations)
        return points_df[
            [
                "station",
                "x",
                "y",
                "value",
                "cell_id",
                "mesh_name",
                "distance",
            ]
        ]

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_velocity_profile(
        hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Extract RAS Mapper velocity/depth/terrain samples along a profile line.

        This method delegates velocity computation to
        ``RasMapperLib.Render.VelocityRenderer.Compute`` through pythonnet.

        Returns:
            DataFrame with station, x, y, mesh_name, face_id, velocity_x,
            velocity_y, velocity_mag, depth, and terrain_elev columns.
        """
        if isinstance(time_index, str) and time_index.strip().lower() == "max":
            raise ValueError(
                "time_index='max' is not supported for RAS Mapper velocity "
                "profile extraction; pass a concrete profile index or name."
            )

        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )

        from ..dotnet._profile_interop import query_polyline_velocity

        profile_data = query_polyline_velocity(
            hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )

        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "velocity_x",
            "velocity_y",
            "velocity_mag",
            "depth",
            "terrain_elev",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "velocity_source",
            "RasMapperLib.Render.VelocityRenderer",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_wse_profile(
        hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Extract RAS Mapper WSE/depth/terrain samples along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_wse

        profile_data = query_polyline_wse(
            hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "wse",
            "depth",
            "terrain_elev",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "wse_source",
            "RasMapperLib.Render.WaterSurfaceRenderer",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_flow_profile(
        hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Extract RAS Mapper flow/depth/terrain samples along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_flow

        profile_data = query_polyline_flow(
            hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "flow",
            "depth",
            "terrain_elev",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "flow_source",
            "RasMapperLib.Render.FlowRenderer",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_velocity_timeseries(
        hdf_path: Path,
        polyline: Any,
        time_range: Optional[tuple[int, int]] = None,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
        wide: bool = False,
    ) -> pd.DataFrame:
        """
        Extract RAS Mapper velocity time series along a profile line.

        ``time_range`` uses Python slicing semantics: ``(start, stop)`` includes
        ``start`` and excludes ``stop``. ``None`` returns all profiles.
        """
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_velocity_timeseries

        profile_data = query_polyline_velocity_timeseries(
            hdf_path,
            polyline_xy,
            time_range=time_range,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "time_index",
            "time",
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "velocity_x",
            "velocity_y",
            "velocity_mag",
            "depth",
            "terrain_elev",
        ]
        return _timeseries_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "velocity_source",
            "RasMapperLib.Render.VelocityTimeSeries",
            "velocity_mag",
            wide,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_wse_timeseries(
        hdf_path: Path,
        polyline: Any,
        time_range: Optional[tuple[int, int]] = None,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
        wide: bool = False,
    ) -> pd.DataFrame:
        """Extract RAS Mapper WSE time series along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_wse_timeseries

        profile_data = query_polyline_wse_timeseries(
            hdf_path,
            polyline_xy,
            time_range=time_range,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "time_index",
            "time",
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "wse",
            "depth",
            "terrain_elev",
        ]
        return _timeseries_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "wse_source",
            "RasMapperLib.Render.WaterSurfaceTimeSeries",
            "wse",
            wide,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_flow_timeseries(
        hdf_path: Path,
        polyline: Any,
        time_range: Optional[tuple[int, int]] = None,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
        wide: bool = False,
    ) -> pd.DataFrame:
        """Extract RAS Mapper flow time series along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_flow_timeseries

        profile_data = query_polyline_flow_timeseries(
            hdf_path,
            polyline_xy,
            time_range=time_range,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "time_index",
            "time",
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "flow",
            "depth",
            "terrain_elev",
        ]
        return _timeseries_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "flow_source",
            "RasMapperLib.Render.FlowRenderer",
            "flow",
            wide,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_pipe_velocity_profile(
        hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Extract RAS Mapper pipe velocity samples along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_pipe_velocity

        profile_data = query_polyline_pipe_velocity(
            hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "velocity_mag",
            "depth",
            "terrain_elev",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "velocity_source",
            "RasMapperLib.Render.VelocityRendererPipe",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_pipe_flow_profile(
        hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Extract RAS Mapper pipe flow samples along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_pipe_flow

        profile_data = query_polyline_pipe_flow(
            hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "flow",
            "depth",
            "terrain_elev",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "flow_source",
            "RasMapperLib.Render.FlowRendererPipe",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_pipe_velocity_timeseries(
        hdf_path: Path,
        polyline: Any,
        time_range: Optional[tuple[int, int]] = None,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
        wide: bool = False,
    ) -> pd.DataFrame:
        """Extract RAS Mapper pipe velocity time series along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_pipe_velocity_timeseries

        profile_data = query_polyline_pipe_velocity_timeseries(
            hdf_path,
            polyline_xy,
            time_range=time_range,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "time_index",
            "time",
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "velocity_mag",
            "depth",
            "terrain_elev",
        ]
        return _timeseries_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "velocity_source",
            "RasMapperLib.Render.VelocityPipeTimeSeries",
            "velocity_mag",
            wide,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_pipe_flow_timeseries(
        hdf_path: Path,
        polyline: Any,
        time_range: Optional[tuple[int, int]] = None,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
        wide: bool = False,
    ) -> pd.DataFrame:
        """Extract RAS Mapper pipe flow time series along a profile line."""
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_pipe_flow_timeseries

        profile_data = query_polyline_pipe_flow_timeseries(
            hdf_path,
            polyline_xy,
            time_range=time_range,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "time_index",
            "time",
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "flow",
            "depth",
            "terrain_elev",
        ]
        return _timeseries_dataframe(
            profile_data,
            columns,
            hdf_path,
            geom_hdf_path,
            spacing,
            "flow_source",
            "RasMapperLib.Render.FlowPipeTimeSeries",
            "flow",
            wide,
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_wse_difference(
        base_hdf_path: Path,
        compare_hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Compare RAS Mapper water-surface profiles between two plan HDFs."""
        compare_hdf_path = Path(compare_hdf_path)
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            base_hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_wse_difference

        profile_data = query_polyline_wse_difference(
            base_hdf_path,
            compare_hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "wse_base",
            "wse_compare",
            "wse_delta",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            base_hdf_path,
            geom_hdf_path,
            spacing,
            "wse_difference_source",
            "RasMapperLib.Render.WaterSurfaceDifferenceRenderer",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def query_polyline_velocity_difference(
        base_hdf_path: Path,
        compare_hdf_path: Path,
        polyline: Any,
        time_index: int,
        sample_spacing: Optional[float] = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_object: Optional[Any] = None,
    ) -> pd.DataFrame:
        """Compare RAS Mapper velocity profiles between two plan HDFs."""
        compare_hdf_path = Path(compare_hdf_path)
        polyline_xy, geom_hdf_path, spacing, terrain_hdf_path = _polyline_profile_inputs(
            base_hdf_path,
            polyline,
            sample_spacing,
            terrain_raster,
            ras_object,
        )
        from ..dotnet._profile_interop import query_polyline_velocity_difference

        profile_data = query_polyline_velocity_difference(
            base_hdf_path,
            compare_hdf_path,
            polyline_xy,
            time_index,
            sample_spacing=spacing,
            geometry_hdf_path=geom_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
        )
        columns = [
            "station",
            "x",
            "y",
            "mesh_name",
            "face_id",
            "velocity_x_base",
            "velocity_y_base",
            "velocity_mag_base",
            "velocity_x_compare",
            "velocity_y_compare",
            "velocity_mag_compare",
            "velocity_x_delta",
            "velocity_y_delta",
            "velocity_mag_delta",
        ]
        return _profile_dataframe(
            profile_data,
            columns,
            base_hdf_path,
            geom_hdf_path,
            spacing,
            "velocity_difference_source",
            "RasMapperLib.Render.VelocityDifferenceRenderer",
        )

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def flood_extent(
        hdf_path: Path,
        depth_threshold: float = 0.1,
        dv_threshold: Optional[float] = None,
        precip_depth_threshold: Optional[float] = None,
        ponding_velocity_max: float = 0.1,
        time_index: Union[int, str] = -1,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Compute domain-wide wet/dry extent statistics for a 2D result state.

        Active filters are AND-combined.
        """
        geom_hdf_path = _resolve_geometry_hdf(hdf_path, ras_object=ras_object)
        cache = _get_kdtree(geom_hdf_path, ras_object=ras_object)
        steady_plan = HdfResultsPlan.is_steady_plan(hdf_path)

        depth = _get_variable_values(
            hdf_path,
            geom_hdf_path,
            cache,
            "Depth",
            time_index,
            steady_plan,
        )
        _validate_value_length(depth, cache, "Depth")

        wet_mask = depth >= float(depth_threshold)
        filters_applied = ["depth_threshold"]
        velocity = None
        dv = None

        if dv_threshold is not None or precip_depth_threshold is not None:
            velocity = _get_variable_values(
                hdf_path,
                geom_hdf_path,
                cache,
                "Velocity",
                time_index,
                steady_plan,
            )
            _validate_value_length(velocity, cache, "Velocity")

        if dv_threshold is not None:
            dv = depth * velocity
            wet_mask &= dv >= float(dv_threshold)
            filters_applied.append("dv_threshold")

        ponding_excluded_cells = None
        if precip_depth_threshold is not None:
            ponding_mask = (
                (depth <= float(precip_depth_threshold))
                & (velocity < float(ponding_velocity_max))
            )
            ponding_excluded_cells = int(np.sum(ponding_mask))
            wet_mask &= ~ponding_mask
            filters_applied.append("precip_depth_threshold")

        cell_areas = _read_geometry_cell_dataset(
            geom_hdf_path,
            cache,
            "Cells Surface Area",
        )
        _validate_value_length(cell_areas, cache, "Cells Surface Area")

        wet_cells = int(np.sum(wet_mask))
        total_cells = int(len(depth))
        dry_cells = total_cells - wet_cells
        wet_area_sqft = float(np.nansum(cell_areas[wet_mask]))
        wet_depths = depth[wet_mask]

        result = {
            "total_cells": total_cells,
            "wet_cells": wet_cells,
            "dry_cells": dry_cells,
            "wet_fraction": (
                float(wet_cells / total_cells) if total_cells > 0 else 0.0
            ),
            "wet_area_sqft": wet_area_sqft,
            "wet_area_acres": wet_area_sqft / 43560.0,
            "max_depth": _safe_stat(depth, np.max),
            "mean_wet_depth": _safe_stat(wet_depths, np.mean),
            "filters_applied": filters_applied,
        }

        if dv_threshold is not None:
            result["max_dv"] = _safe_stat(dv, np.max)

        if precip_depth_threshold is not None:
            result["ponding_excluded_cells"] = ponding_excluded_cells

        return result

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def result_statistics(
        hdf_path: Path,
        variable: str = "depth",
        time_index: Union[int, str] = -1,
        wet_only: bool = True,
        depth_threshold: float = 0.1,
        ras_object: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Return summary statistics for a per-cell result variable."""
        variable_name = _normalize_variable(variable)
        geom_hdf_path = _resolve_geometry_hdf(hdf_path, ras_object=ras_object)
        cache = _get_kdtree(geom_hdf_path, ras_object=ras_object)
        steady_plan = HdfResultsPlan.is_steady_plan(hdf_path)

        values = _get_variable_values(
            hdf_path,
            geom_hdf_path,
            cache,
            variable_name,
            time_index,
            steady_plan,
        )
        _validate_value_length(values, cache, variable_name)

        if wet_only:
            if variable_name == "Depth":
                depth = values
            else:
                depth = _get_variable_values(
                    hdf_path,
                    geom_hdf_path,
                    cache,
                    "Depth",
                    time_index,
                    steady_plan,
                )
                _validate_value_length(depth, cache, "Depth")
            values = values[depth >= float(depth_threshold)]

        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values)]

        if values.size == 0:
            return {
                "min": float("nan"),
                "max": float("nan"),
                "mean": float("nan"),
                "median": float("nan"),
                "std": float("nan"),
                "count": 0,
                "p10": float("nan"),
                "p25": float("nan"),
                "p75": float("nan"),
                "p90": float("nan"),
                "p99": float("nan"),
            }

        return {
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": float(np.std(values)),
            "count": int(values.size),
            "p10": float(np.percentile(values, 10)),
            "p25": float(np.percentile(values, 25)),
            "p75": float(np.percentile(values, 75)),
            "p90": float(np.percentile(values, 90)),
            "p99": float(np.percentile(values, 99)),
        }
