"""
RasCalibrate - thin orchestration helpers for HEC-RAS calibration workflows.

This module composes existing ras-commander infrastructure:
- RasPermutation for batch plan generation and execution
- HDF extraction helpers for 1D XS, 2D cells, ref lines, and ref points
- USGS metrics for NSE/KGE and richer validation summaries
- Geom/HDF setters for Manning's n and infiltration calibration
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import h5py
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasCmdr import RasCmdr
from .RasPermutation import RasPermutation
from .RasPlan import RasPlan
from .RasPrj import ras
from .RasUtils import RasUtils
from .geom.GeomLandCover import GeomLandCover
from .hdf.HdfInfiltration import HdfInfiltration
from .hdf.HdfLandCover import HdfLandCover
from .hdf.HdfResultsMesh import HdfResultsMesh
from .hdf.HdfResultsQuery import HdfResultsQuery
from .hdf.HdfResultsXsec import HdfResultsXsec
from .usgs.metrics import (
    calculate_all_metrics,
    kling_gupta_efficiency,
    nash_sutcliffe_efficiency,
)


logger = get_logger(__name__)

Observation = Union[float, int, pd.Series]
ApplyFn = Callable[[Path, pd.Series, Any], None]

_FULL_SERIES_SENTINELS = {None, "all", "series"}
_LOWER_IS_BETTER = {"rmse", "mae", "pbias"}
_HIGHER_IS_BETTER = {"nse", "kge"}

_XSEC_VARIABLE_MAP = {
    "wse": "Water Surface",
    "flow": "Flow",
    "velocity": "Velocity Total",
    "depth": None,
}

_REF_VARIABLE_MAP = {
    "wse": "Water Surface",
    "flow": "Flow",
    "velocity": "Velocity",
    "depth": None,
}

_MESH_VARIABLE_MAP = {
    "wse": "Water Surface",
    "flow": None,
    "velocity": "Velocity",
    "depth": "Depth",
}

_SCIPY_METHODS = {
    "nelder-mead": "Nelder-Mead",
    "powell": "Powell",
    "cg": "CG",
    "bfgs": "BFGS",
    "l-bfgs-b": "L-BFGS-B",
    "slsqp": "SLSQP",
    "tnc": "TNC",
}


@dataclass
class CalibrationPoint:
    """Observed calibration target and extraction metadata."""

    name: str
    variable: str
    extraction_method: str
    observed: Observation
    x: Optional[float] = None
    y: Optional[float] = None
    river: Optional[str] = None
    reach: Optional[str] = None
    station: Optional[str] = None
    ref_feature_name: Optional[str] = None
    time_index: Union[str, int, None] = "max"
    metric: str = "nse"               # per-point metric for composite scoring
    weight: float = 1.0               # relative weight in composite objective
    depth_datum: Optional[float] = None  # for WSE->depth conversion (if None, uses min observed)

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.variable = str(self.variable).strip().lower()
        self.extraction_method = str(
            self.extraction_method
        ).strip().lower()

        if not self.name:
            raise ValueError("CalibrationPoint.name cannot be empty")

        valid_variables = {"wse", "flow", "depth", "velocity"}
        if self.variable not in valid_variables:
            raise ValueError(
                f"Unsupported variable '{self.variable}'. "
                f"Valid values: {sorted(valid_variables)}"
            )

        valid_methods = {"1d_xs", "2d_cell", "ref_line", "ref_point"}
        if self.extraction_method not in valid_methods:
            raise ValueError(
                f"Unsupported extraction_method "
                f"'{self.extraction_method}'. "
                f"Valid values: {sorted(valid_methods)}"
            )

        if isinstance(self.time_index, str):
            normalized = self.time_index.strip().lower()
            if normalized == "max":
                self.time_index = "max"
            elif normalized in {"all", "series"}:
                self.time_index = None
            else:
                raise ValueError(
                    "time_index must be 'max', 'all', 'series', or an "
                    "integer"
                )
        elif self.time_index is not None and not isinstance(
            self.time_index, (int, np.integer)
        ):
            raise TypeError(
                "time_index must be a string sentinel or an integer"
            )

        if isinstance(self.observed, pd.Series):
            self.observed = self.observed.copy()
            if self.time_index == "max":
                self.time_index = None
            if isinstance(self.time_index, (int, np.integer)):
                raise ValueError(
                    "Time-series observations require full-series modeled "
                    "output; use the default time_index='max' to auto-promote "
                    "to series mode, or set time_index=None."
                )
        elif np.isscalar(self.observed):
            self.observed = float(self.observed)
            if self.time_index in _FULL_SERIES_SENTINELS:
                raise ValueError(
                    "Scalar observations require time_index='max' or an "
                    "integer snapshot index."
                )
        else:
            raise TypeError("observed must be a scalar or pandas Series")

        if self.x is not None:
            self.x = float(self.x)
        if self.y is not None:
            self.y = float(self.y)
        if self.river is not None:
            self.river = str(self.river).strip()
        if self.reach is not None:
            self.reach = str(self.reach).strip()
        if self.station is not None:
            self.station = str(self.station).strip()
        if self.ref_feature_name is not None:
            self.ref_feature_name = str(self.ref_feature_name).strip()

        # Validate metric and weight
        self.metric = _normalize_metric(self.metric)
        self.weight = float(self.weight)
        if self.weight <= 0:
            raise ValueError("CalibrationPoint.weight must be positive")
        if self.depth_datum is not None:
            self.depth_datum = float(self.depth_datum)

        if self.extraction_method == "2d_cell":
            if self.x is None or self.y is None:
                raise ValueError(
                    "2d_cell calibration points require x and y coordinates"
                )
        elif self.extraction_method == "1d_xs":
            if not self.river or not self.reach or not self.station:
                raise ValueError(
                    "1d_xs calibration points require river, reach, and "
                    "station"
                )
        else:
            if not self.ref_feature_name:
                raise ValueError(
                    "ref_line and ref_point calibration points require "
                    "ref_feature_name"
                )


def _normalize_metric(metric: str) -> str:
    metric_name = str(metric).strip().lower()
    valid_metrics = _LOWER_IS_BETTER | _HIGHER_IS_BETTER
    if metric_name not in valid_metrics:
        raise ValueError(
            f"Unsupported metric '{metric}'. "
            f"Valid metrics: {sorted(valid_metrics)}"
        )
    return metric_name


def _get_active_ras(ras_object: Any = None) -> Any:
    return ras_object if ras_object is not None else ras


def _coerce_calibration_points(
    calibration_points: Sequence[Union[CalibrationPoint, dict]]
) -> List[CalibrationPoint]:
    points: List[CalibrationPoint] = []
    for point in calibration_points:
        if isinstance(point, CalibrationPoint):
            points.append(point)
        elif isinstance(point, dict):
            points.append(CalibrationPoint(**point))
        else:
            raise TypeError(
                "calibration_points must contain CalibrationPoint instances "
                "or dictionaries"
            )

    if not points:
        raise ValueError("At least one calibration point is required")

    return points


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(name).strip().lower())
    return cleaned.strip("_") or "point"


def _project_name_from_plan_path(plan_path: Path) -> str:
    match = re.match(r"(.+)\.p\d{2}$", plan_path.stem, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return plan_path.stem


def _extract_two_digit_number(raw_value: str) -> str:
    digits = "".join(ch for ch in str(raw_value) if ch.isdigit())
    if not digits:
        raise ValueError(f"Could not extract a file number from '{raw_value}'")
    return digits[-2:].zfill(2)


def _read_plan_reference(plan_path: Path, key: str) -> str:
    for line in plan_path.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise ValueError(f"Could not find '{key}=' in {plan_path}")


def _resolve_geom_path_from_plan(plan_path: Path) -> Path:
    geom_value = _read_plan_reference(plan_path, "Geom File")
    geom_number = _extract_two_digit_number(geom_value)
    project_name = _project_name_from_plan_path(plan_path)
    return plan_path.parent / f"{project_name}.g{geom_number}"


def _resolve_geom_hdf_path_from_plan(plan_path: Path) -> Path:
    geom_path = _resolve_geom_path_from_plan(plan_path)
    geom_hdf_path = Path(f"{geom_path}.hdf")
    if not geom_hdf_path.exists():
        raise FileNotFoundError(
            f"Geometry HDF not found for plan '{plan_path.name}': "
            f"{geom_hdf_path}"
        )
    return geom_hdf_path


def _prefer_batch_local_copy(
    target_path: Path,
    batch_folder: Path,
) -> Path:
    try:
        if target_path.is_relative_to(batch_folder):
            return target_path
    except ValueError:
        pass

    direct_candidate = batch_folder / target_path.name
    if direct_candidate.exists():
        return direct_candidate

    matches = list(batch_folder.rglob(target_path.name))
    if len(matches) == 1:
        return matches[0]

    return target_path


def _resolve_landcover_sidecar_from_plan(
    plan_path: Path,
    ras_object: Any = None,
) -> Path:
    geom_hdf_path = _resolve_geom_hdf_path_from_plan(plan_path)
    sidecar_path = HdfLandCover.get_landcover_association(
        geom_hdf_path,
        ras_object=ras_object,
    )
    if sidecar_path is None:
        raise FileNotFoundError(
            f"Could not resolve land cover sidecar for {geom_hdf_path}"
        )
    return _prefer_batch_local_copy(Path(sidecar_path), plan_path.parent)


def _resolve_plan_hdf_path(
    plan_number: Union[str, int, float, Path],
    ras_object: Any = None,
    compute_result: Any = None,
) -> Path:
    active_ras = _get_active_ras(ras_object)
    plan_number_str = RasUtils.normalize_ras_number(plan_number)

    if (
        compute_result is not None
        and getattr(compute_result, "results_df_row", None) is not None
    ):
        hdf_value = compute_result.results_df_row.get("HDF_Results_Path")
        if pd.notna(hdf_value):
            candidate = Path(str(hdf_value))
            if candidate.exists():
                return candidate

    active_ras.plan_df = active_ras.get_plan_entries()
    matching = active_ras.plan_df[
        active_ras.plan_df["plan_number"].astype(str).str.zfill(2)
        == plan_number_str
    ]
    if not matching.empty:
        hdf_value = matching.iloc[0].get("HDF_Results_Path")
        if pd.notna(hdf_value):
            candidate = Path(str(hdf_value))
            if candidate.exists():
                return candidate

    fallback = (
        Path(active_ras.project_folder)
        / f"{active_ras.project_name}.p{plan_number_str}.hdf"
    )
    if fallback.exists():
        return fallback

    raise FileNotFoundError(
        f"Could not resolve plan HDF path for plan {plan_number_str}"
    )


def _dataset_variable_candidates(variable_name: str) -> List[str]:
    return [
        variable_name,
        variable_name.replace(" ", "_"),
        variable_name.replace("_", " "),
    ]


def _resolve_dataset_variable_name(
    dataset: Any,
    variable_name: Optional[str],
) -> str:
    if variable_name is None:
        raise ValueError("Requested variable is not available for this method")

    for candidate in _dataset_variable_candidates(variable_name):
        if candidate in dataset.data_vars:
            return candidate

    raise KeyError(
        f"Variable '{variable_name}' was not found. "
        f"Available variables: {list(dataset.data_vars)}"
    )


def _to_labeled_series(data_array: Any) -> pd.Series:
    values = np.asarray(data_array.values, dtype=float)
    if "time" in data_array.coords:
        index = pd.Index(data_array.coords["time"].values)
    else:
        index = pd.RangeIndex(start=0, stop=len(values))
    return pd.Series(values, index=index, name=getattr(data_array, "name", None))


def _apply_time_index(
    data_array: Any,
    time_index: Union[str, int, None],
) -> Union[float, pd.Series]:
    series = _to_labeled_series(data_array)

    if time_index in _FULL_SERIES_SENTINELS:
        return series

    if time_index == "max":
        return float(series.max(skipna=True))

    return float(series.iloc[int(time_index)])


def _series_like(values: Union[pd.Series, np.ndarray, list]) -> pd.Series:
    if isinstance(values, pd.Series):
        return values.copy()
    return pd.Series(np.asarray(values, dtype=float))


def _align_observed_and_modeled(
    observed: Union[pd.Series, np.ndarray, list],
    modeled: Union[pd.Series, np.ndarray, list],
) -> pd.DataFrame:
    observed_series = _series_like(observed).rename("observed")
    modeled_series = _series_like(modeled).rename("modeled")

    if isinstance(observed, pd.Series) and isinstance(modeled, pd.Series):
        aligned = pd.concat(
            [observed_series, modeled_series],
            axis=1,
            join="inner",
        ).dropna()
        if not aligned.empty:
            return aligned
        logger.warning(
            "Observed and modeled time series had no overlapping index; "
            "falling back to positional alignment."
        )

    length = min(len(observed_series), len(modeled_series))
    if length == 0:
        raise ValueError("No paired values available for comparison")

    aligned = pd.DataFrame(
        {
            "observed": pd.to_numeric(
                observed_series.iloc[:length],
                errors="coerce",
            ).to_numpy(dtype=float),
            "modeled": pd.to_numeric(
                modeled_series.iloc[:length],
                errors="coerce",
            ).to_numpy(dtype=float),
        }
    ).dropna()

    if aligned.empty:
        raise ValueError("No valid paired values available for comparison")

    return aligned


def _infer_dt_hours(index: pd.Index) -> float:
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
        return 1.0

    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return 1.0

    dt_hours = deltas.median() / pd.Timedelta(hours=1)
    return float(dt_hours) if dt_hours > 0 else 1.0


def _select_xsec_index(dataset: Any, point: CalibrationPoint) -> int:
    river = pd.Series(dataset.coords["River"].values).astype(str).str.strip()
    reach = pd.Series(dataset.coords["Reach"].values).astype(str).str.strip()
    station = (
        pd.Series(dataset.coords["Station"].values).astype(str).str.strip()
    )

    mask = (
        (river == point.river)
        & (reach == point.reach)
        & (station == point.station)
    )
    indices = np.flatnonzero(mask.to_numpy())

    if len(indices) == 0:
        raise ValueError(
            f"Cross section not found for "
            f"{point.river}/{point.reach}/{point.station}"
        )
    if len(indices) > 1:
        raise ValueError(
            f"Cross section selection was ambiguous for "
            f"{point.river}/{point.reach}/{point.station}"
        )

    return int(indices[0])


def _select_named_index(dataset: Any, coord_name: str, target_name: str) -> int:
    values = pd.Series(dataset.coords[coord_name].values).astype(str).str.strip()
    indices = np.flatnonzero(values.eq(str(target_name).strip()).to_numpy())

    if len(indices) == 0:
        raise ValueError(
            f"Feature '{target_name}' was not found in coordinate "
            f"'{coord_name}'"
        )
    if len(indices) > 1:
        raise ValueError(
            f"Feature '{target_name}' matched multiple rows in "
            f"'{coord_name}'"
        )

    return int(indices[0])


def _get_reference_dataset(
    plan_hdf: Path,
    reftype: str,
) -> Any:
    getter = (
        HdfResultsXsec.get_ref_lines_timeseries
        if reftype == "lines"
        else HdfResultsXsec.get_ref_points_timeseries
    )

    try:
        dataset = getter(plan_hdf)
        if len(dataset.data_vars) > 0:
            return dataset
    except Exception as exc:
        logger.debug(
            "Reference %s getter failed for %s; falling back to internal "
            "helper: %s",
            reftype,
            plan_hdf,
            exc,
        )

    with h5py.File(plan_hdf, "r") as hdf_file:
        return HdfResultsXsec._reference_timeseries_output(
            hdf_file,
            reftype=reftype,
        )


def _parse_infiltration_mapping_spec(
    spec: Union[Tuple[str, str], List[str], Dict[str, str]],
) -> Tuple[str, str]:
    if isinstance(spec, dict):
        row_name = (
            spec.get("row")
            or spec.get("name")
            or spec.get("region")
        )
        field_name = spec.get("field") or spec.get("column")
    elif isinstance(spec, (tuple, list)) and len(spec) == 2:
        row_name, field_name = spec
    else:
        raise TypeError(
            "Infiltration mapping values must be "
            "(row_name, field_name) tuples or dictionaries."
        )

    if not row_name or not field_name:
        raise ValueError(
            "Infiltration mapping spec requires both row and field names"
        )

    return str(row_name), str(field_name)


def _aggregate_objectives(
    values: Sequence[float],
    metric: str,
) -> float:
    metric_name = _normalize_metric(metric)
    finite = [float(value) for value in values if pd.notna(value)]
    if not finite:
        return float("nan")
    if metric_name == "pbias":
        finite = [abs(value) for value in finite]
    return float(np.mean(finite))


def _calculate_point_metrics(
    observed: Observation,
    modeled: Union[float, pd.Series],
) -> Optional[dict]:
    if not isinstance(observed, pd.Series) or not isinstance(modeled, pd.Series):
        return None

    aligned = _align_observed_and_modeled(observed, modeled)
    if len(aligned) < 10:
        return None

    time_index = (
        aligned.index
        if isinstance(aligned.index, pd.DatetimeIndex)
        else None
    )
    dt_hours = _infer_dt_hours(aligned.index)

    try:
        return calculate_all_metrics(
            aligned["observed"].to_numpy(dtype=float),
            aligned["modeled"].to_numpy(dtype=float),
            time_index=time_index,
            dt_hours=dt_hours,
        )
    except Exception as exc:
        logger.debug(
            "Full metrics were unavailable for a calibration point: %s",
            exc,
        )
        return None


def _evaluate_points(
    calibration_points: Sequence[CalibrationPoint],
    plan_hdf: Path,
    metric: str,
    ras_object: Any = None,
) -> Tuple[List[dict], float]:
    point_results: List[dict] = []
    objectives: List[float] = []

    for point in calibration_points:
        result = {
            "name": point.name,
            "variable": point.variable,
            "extraction_method": point.extraction_method,
            "time_index": point.time_index,
            "modeled": None,
            "objective": np.nan,
            "metrics": None,
            "error": None,
        }

        try:
            modeled = extract_modeled(point, plan_hdf, ras_object=ras_object)
            objective = compute_objective(
                point.observed,
                modeled,
                metric=metric,
            )
            result["modeled"] = modeled
            result["objective"] = objective
            result["metrics"] = _calculate_point_metrics(
                point.observed,
                modeled,
            )
            if pd.notna(objective):
                objectives.append(float(objective))
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning(
                "Calibration point '%s' failed for %s: %s",
                point.name,
                plan_hdf,
                exc,
            )

        point_results.append(result)

    overall_objective = _aggregate_objectives(objectives, metric)
    return point_results, overall_objective

@log_call
def extract_modeled(
    point: CalibrationPoint,
    plan_hdf: Path,
    ras_object: Any = None,
) -> Union[float, pd.Series]:
    """
    Extract modeled data for a calibration point from a plan HDF file.
    """
    plan_hdf = Path(plan_hdf)
    if not plan_hdf.exists():
        raise FileNotFoundError(f"Plan HDF not found: {plan_hdf}")

    if point.extraction_method == "1d_xs":
        dataset = HdfResultsXsec.get_xsec_timeseries(plan_hdf)
        variable_name = _resolve_dataset_variable_name(
            dataset,
            _XSEC_VARIABLE_MAP[point.variable],
        )
        xs_index = _select_xsec_index(dataset, point)
        data_array = dataset[variable_name].isel(cross_section=xs_index)
        return _apply_time_index(data_array, point.time_index)

    if point.extraction_method == "2d_cell":
        locator = HdfResultsQuery.query_points(
            plan_hdf,
            [(point.x, point.y)],
            variable=point.variable,
            time_index=-1 if point.time_index in _FULL_SERIES_SENTINELS
            else point.time_index,
            ras_object=ras_object,
        ).iloc[0]

        if point.time_index not in _FULL_SERIES_SENTINELS:
            return float(locator["value"])

        mesh_name = str(locator["mesh_name"])
        cell_id = int(locator["cell_id"])
        variable_name = _MESH_VARIABLE_MAP[point.variable]
        if variable_name is None:
            raise ValueError(
                f"2d_cell extraction does not support '{point.variable}'"
            )

        mesh_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            plan_hdf,
            mesh_names=mesh_name,
            var=variable_name,
            ras_object=ras_object,
        )
        mesh_dataset = mesh_datasets.get(mesh_name)
        if mesh_dataset is None:
            raise ValueError(
                f"Mesh '{mesh_name}' was not found in mesh timeseries output"
            )

        dataset_var = _resolve_dataset_variable_name(
            mesh_dataset,
            variable_name,
        )
        data_array = mesh_dataset[dataset_var].isel(cell_id=cell_id)
        return _apply_time_index(data_array, point.time_index)

    if point.extraction_method == "ref_line":
        dataset = _get_reference_dataset(plan_hdf, reftype="lines")
        variable_name = _resolve_dataset_variable_name(
            dataset,
            _REF_VARIABLE_MAP[point.variable],
        )
        refln_index = _select_named_index(
            dataset,
            "refln_name",
            point.ref_feature_name,
        )
        data_array = dataset[variable_name].isel(refln_id=refln_index)
        return _apply_time_index(data_array, point.time_index)

    if point.extraction_method == "ref_point":
        dataset = _get_reference_dataset(plan_hdf, reftype="points")
        variable_name = _resolve_dataset_variable_name(
            dataset,
            _REF_VARIABLE_MAP[point.variable],
        )
        refpt_index = _select_named_index(
            dataset,
            "refpt_name",
            point.ref_feature_name,
        )
        data_array = dataset[variable_name].isel(refpt_id=refpt_index)
        return _apply_time_index(data_array, point.time_index)

    raise ValueError(
        f"Unsupported extraction_method '{point.extraction_method}'"
    )


@log_call
def compute_objective(
    observed: Observation,
    modeled: Union[float, pd.Series],
    metric: str = "rmse",
) -> float:
    """
    Compute a scalar objective value from observed and modeled data.
    """
    metric_name = _normalize_metric(metric)

    if isinstance(observed, pd.Series):
        if not isinstance(modeled, pd.Series):
            raise ValueError(
                "Time-series observations require time-series modeled output"
            )

        aligned = _align_observed_and_modeled(observed, modeled)
        observed_values = aligned["observed"].to_numpy(dtype=float)
        modeled_values = aligned["modeled"].to_numpy(dtype=float)

        if metric_name == "rmse":
            return float(
                np.sqrt(np.mean((modeled_values - observed_values) ** 2))
            )
        if metric_name == "nse":
            return float(
                nash_sutcliffe_efficiency(observed_values, modeled_values)
            )
        if metric_name == "kge":
            return float(
                kling_gupta_efficiency(observed_values, modeled_values)[0]
            )
        if metric_name == "pbias":
            denominator = np.sum(observed_values)
            if denominator == 0:
                return float("nan")
            return float(
                100.0
                * np.sum(modeled_values - observed_values)
                / denominator
            )
        if metric_name == "mae":
            return float(np.mean(np.abs(modeled_values - observed_values)))

    if isinstance(modeled, pd.Series):
        raise ValueError(
            "Scalar observations require scalar modeled output"
        )

    return abs(float(modeled) - float(observed))


@log_call
def make_mannings_apply_fn(
    zone_column_map: Dict[str, str],
    path: str = "plaintext",
) -> ApplyFn:
    """
    Factory returning an apply_fn for Manning's n calibration.

    Args:
        zone_column_map: Maps DataFrame column name -> land cover class name.
            Example:
            {'n_forest': 'Deciduous Forest', 'n_urban': 'Developed'}
        path: 'plaintext' for GeomLandCover, 'sidecar' for HdfLandCover.
    """
    normalized_path = str(path).strip().lower()
    if normalized_path not in {"plaintext", "sidecar"}:
        raise ValueError("path must be 'plaintext' or 'sidecar'")

    @log_call
    def apply_fn(
        plan_path: Path,
        param_row: pd.Series,
        ras_object: Any = None,
    ) -> None:
        plan_path = Path(plan_path)

        if normalized_path == "plaintext":
            geom_path = _resolve_geom_path_from_plan(plan_path)
            current_table = GeomLandCover.get_base_mannings_n(geom_path)
            if current_table.empty:
                raise ValueError(
                    f"No Manning's n table found in geometry file {geom_path}"
                )

            updated_table = current_table.copy()
            for param_column, class_name in zone_column_map.items():
                if param_column not in param_row:
                    raise KeyError(
                        f"Parameter column '{param_column}' not found in "
                        "param_row"
                    )
                mask = (
                    updated_table["Land Cover Name"]
                    .astype(str)
                    .str.strip()
                    == str(class_name).strip()
                )
                if not mask.any():
                    raise ValueError(
                        f"Land cover class '{class_name}' was not found in "
                        f"{geom_path}"
                    )
                updated_table.loc[mask, "Base Mannings n Value"] = float(
                    param_row[param_column]
                )

            GeomLandCover.set_base_mannings_n(geom_path, updated_table)
            return

        sidecar_path = _resolve_landcover_sidecar_from_plan(
            plan_path,
            ras_object=ras_object,
        )
        class_mapping = {
            class_name: float(param_row[param_column])
            for param_column, class_name in zone_column_map.items()
        }
        HdfLandCover.set_landcover_raster_map(
            sidecar_path,
            class_mapping,
            ras_object=ras_object,
        )

    return apply_fn


@log_call
def make_infiltration_apply_fn(
    parameter_mapping: Dict[
        str,
        Union[Tuple[str, str], List[str], Dict[str, str]],
    ],
    name_column: Optional[str] = None,
) -> ApplyFn:
    """
    Factory returning an apply_fn for infiltration base overrides.

    parameter_mapping maps permutation column names to target row/field pairs.

    Example:
        {
            'cn_forest': ('Forest', 'Curve Number'),
            'iar_urban': {'row': 'Urban', 'field': 'Abstraction Ratio'},
        }
    """

    @log_call
    def apply_fn(
        plan_path: Path,
        param_row: pd.Series,
        ras_object: Any = None,
    ) -> None:
        setter = getattr(
            HdfInfiltration,
            "set_infiltration_baseoverrides",
            None,
        )
        if setter is None:
            raise NotImplementedError(
                "HdfInfiltration.set_infiltration_baseoverrides() is not "
                "currently implemented in this repository."
            )

        geom_hdf_path = _resolve_geom_hdf_path_from_plan(Path(plan_path))
        infiltration_df = HdfInfiltration.get_infiltration_baseoverrides(
            geom_hdf_path
        )
        if infiltration_df is None or infiltration_df.empty:
            raise ValueError(
                f"No infiltration base overrides found in {geom_hdf_path}"
            )

        if name_column is not None:
            resolved_name_column = name_column
        elif "Land Cover Name" in infiltration_df.columns:
            resolved_name_column = "Land Cover Name"
        else:
            resolved_name_column = "Name"
        if resolved_name_column not in infiltration_df.columns:
            raise KeyError(
                f"Could not resolve infiltration name column in "
                f"{geom_hdf_path}"
            )

        updated_df = infiltration_df.copy()
        for param_column, spec in parameter_mapping.items():
            if param_column not in param_row:
                raise KeyError(
                    f"Parameter column '{param_column}' not found in "
                    "param_row"
                )

            row_name, field_name = _parse_infiltration_mapping_spec(spec)
            if field_name not in updated_df.columns:
                raise KeyError(
                    f"Infiltration field '{field_name}' was not found in "
                    f"{geom_hdf_path}"
                )

            mask = (
                updated_df[resolved_name_column]
                .astype(str)
                .str.strip()
                == row_name.strip()
            )
            if not mask.any():
                raise ValueError(
                    f"Infiltration row '{row_name}' was not found in "
                    f"{geom_hdf_path}"
                )

            updated_df.loc[mask, field_name] = float(param_row[param_column])

        setter(geom_hdf_path, updated_df)

    return apply_fn


@log_call
def make_composite_apply_fn(*apply_fns: Union[ApplyFn, Sequence[ApplyFn]]) -> ApplyFn:
    """
    Combine multiple apply_fn callables into one apply_fn.
    """
    if len(apply_fns) == 1 and isinstance(apply_fns[0], (list, tuple)):
        flattened = list(apply_fns[0])
    else:
        flattened = list(apply_fns)

    if not flattened:
        raise ValueError("At least one apply_fn is required")

    for apply_fn in flattened:
        if not callable(apply_fn):
            raise TypeError("All composite apply_fn inputs must be callable")

    @log_call
    def composite_apply_fn(
        plan_path: Path,
        param_row: pd.Series,
        ras_object: Any = None,
    ) -> None:
        for apply_fn in flattened:
            apply_fn(plan_path, param_row, ras_object=ras_object)

    return composite_apply_fn

class RasCalibrate:
    """Static calibration orchestration helpers."""

    @staticmethod
    @log_call
    def grid_search(
        template_plan: Union[str, int, float, Path],
        parameters: Dict[str, Sequence[float]],
        apply_fn: ApplyFn,
        calibration_points: Sequence[Union[CalibrationPoint, dict]],
        metric: str = "rmse",
        suffix: str = "cal",
        max_workers: int = 2,
        num_cores: int = 2,
        force_geompre: bool = False,
        ras_object: Any = None,
    ) -> pd.DataFrame:
        """
        Run a calibration grid search on top of RasPermutation.
        """
        metric_name = _normalize_metric(metric)
        points = _coerce_calibration_points(calibration_points)

        if force_geompre:
            logger.warning(
                "grid_search(force_geompre=True) was requested, but "
                "RasPermutation.execute_and_summarize() does not currently "
                "expose force_geompre to RasCmdr.compute_parallel()."
            )

        params_df = RasPermutation.define_parameters(parameters)
        plan_matrix = RasPermutation.generate_plans(
            template_plan,
            params_df,
            apply_fn,
            suffix=suffix,
            ras_object=ras_object,
        )
        results_df = RasPermutation.execute_and_summarize(
            plan_matrix,
            max_workers=max_workers,
            num_cores=num_cores,
            ras_object=ras_object,
        )

        augmented_rows: List[dict] = []
        for row in results_df.to_dict("records"):
            row["overall_objective"] = np.nan
            row["n_points_scored"] = 0

            status = str(row.get("status", "")).strip().lower()
            hdf_path_value = row.get("hdf_path")
            if status != "completed" or pd.isna(hdf_path_value):
                augmented_rows.append(row)
                continue

            hdf_path = Path(str(hdf_path_value))
            if not hdf_path.exists():
                augmented_rows.append(row)
                continue

            point_results, overall_objective = _evaluate_points(
                points,
                hdf_path,
                metric_name,
                ras_object=ras_object,
            )
            row["overall_objective"] = overall_objective
            row["n_points_scored"] = sum(
                pd.notna(point_result["objective"])
                for point_result in point_results
            )

            for idx, point_result in enumerate(point_results, start=1):
                suffix_name = _sanitize_name(point_result["name"])
                prefix = f"point_{idx:02d}_{suffix_name}"
                row[f"{prefix}_modeled"] = point_result["modeled"]
                row[f"{prefix}_objective"] = point_result["objective"]

            augmented_rows.append(row)

        augmented_df = pd.DataFrame(augmented_rows)
        ascending = metric_name in _LOWER_IS_BETTER
        return augmented_df.sort_values(
            "overall_objective",
            ascending=ascending,
            na_position="last",
        ).reset_index(drop=True)

    @staticmethod
    @log_call
    def evaluate_single(
        plan_number: Union[str, int, float, Path],
        parameter_values: Dict[str, float],
        apply_fn: ApplyFn,
        calibration_points: Sequence[Union[CalibrationPoint, dict]],
        metric: str = "rmse",
        num_cores: int = 4,
        force_geompre: bool = False,
        ras_object: Any = None,
    ) -> dict:
        """
        Apply one parameter set to one plan, execute it, and score it.
        """
        active_ras = _get_active_ras(ras_object)
        active_ras.check_initialized()

        metric_name = _normalize_metric(metric)
        points = _coerce_calibration_points(calibration_points)
        plan_number_str = RasUtils.normalize_ras_number(plan_number)
        parameter_series = pd.Series(parameter_values, dtype="object")

        plan_path = RasPlan.get_plan_path(
            plan_number_str,
            ras_object=active_ras,
        )
        if plan_path is None or not Path(plan_path).exists():
            raise FileNotFoundError(
                f"Plan file could not be resolved for {plan_number_str}"
            )

        apply_fn(Path(plan_path), parameter_series, active_ras)

        compute_result = RasCmdr.compute_plan(
            plan_number_str,
            force_geompre=force_geompre,
            force_rerun=True,
            num_cores=num_cores,
            ras_object=active_ras,
        )
        if not compute_result:
            return {
                "success": False,
                "plan_number": plan_number_str,
                "metric": metric_name,
                "parameters": dict(parameter_series),
                "hdf_path": None,
                "point_results": [],
                "overall_objective": np.nan,
                "overall_metrics": {
                    "metric": metric_name,
                    "point_count": len(points),
                    "successful_points": 0,
                    "overall_objective": np.nan,
                },
                "error": "Plan execution failed",
            }

        hdf_path = _resolve_plan_hdf_path(
            plan_number_str,
            ras_object=active_ras,
            compute_result=compute_result,
        )
        point_results, overall_objective = _evaluate_points(
            points,
            hdf_path,
            metric_name,
            ras_object=active_ras,
        )

        successful_points = sum(
            pd.notna(point_result["objective"])
            for point_result in point_results
        )

        return {
            "success": True,
            "plan_number": plan_number_str,
            "metric": metric_name,
            "parameters": dict(parameter_series),
            "hdf_path": hdf_path,
            "point_results": point_results,
            "overall_objective": overall_objective,
            "overall_metrics": {
                "metric": metric_name,
                "point_count": len(points),
                "successful_points": int(successful_points),
                "overall_objective": overall_objective,
            },
        }

    @staticmethod
    @log_call
    def evaluate_multi_event(
        plan_numbers: Sequence[Union[str, int, float, Path]],
        parameter_values: Dict[str, float],
        apply_fn: ApplyFn,
        calibration_points_per_plan: Union[
            Dict[Union[str, int, float, Path], Sequence[Union[CalibrationPoint, dict]]],
            Sequence[Sequence[Union[CalibrationPoint, dict]]],
        ],
        metric: str = "rmse",
        num_cores: int = 4,
        force_geompre: bool = False,
        ras_object: Any = None,
    ) -> dict:
        """
        Evaluate one parameter set across multiple events/plans.
        """
        metric_name = _normalize_metric(metric)
        normalized_plan_numbers = [
            RasUtils.normalize_ras_number(plan_number)
            for plan_number in plan_numbers
        ]
        if not normalized_plan_numbers:
            raise ValueError("At least one plan number is required")

        if isinstance(calibration_points_per_plan, dict):
            point_map = {
                RasUtils.normalize_ras_number(plan): _coerce_calibration_points(
                    points
                )
                for plan, points in calibration_points_per_plan.items()
            }
            points_by_plan = [
                point_map[plan_number]
                for plan_number in normalized_plan_numbers
            ]
        else:
            if len(calibration_points_per_plan) != len(normalized_plan_numbers):
                raise ValueError(
                    "calibration_points_per_plan must align one-for-one with "
                    "plan_numbers"
                )
            points_by_plan = [
                _coerce_calibration_points(points)
                for points in calibration_points_per_plan
            ]

        event_results = []
        event_objectives: List[float] = []
        for plan_number, points in zip(
            normalized_plan_numbers,
            points_by_plan,
        ):
            event_result = RasCalibrate.evaluate_single(
                plan_number=plan_number,
                parameter_values=parameter_values,
                apply_fn=apply_fn,
                calibration_points=points,
                metric=metric_name,
                num_cores=num_cores,
                force_geompre=force_geompre,
                ras_object=ras_object,
            )
            event_results.append(event_result)
            if pd.notna(event_result.get("overall_objective")):
                event_objectives.append(
                    float(event_result["overall_objective"])
                )

        average_objective = (
            float(np.mean(event_objectives))
            if event_objectives
            else float("nan")
        )

        return {
            "metric": metric_name,
            "parameters": dict(parameter_values),
            "event_results": event_results,
            "average_objective": average_objective,
            "overall_metrics": {
                "metric": metric_name,
                "event_count": len(event_results),
                "events_scored": len(event_objectives),
                "average_objective": average_objective,
            },
        }

    @staticmethod
    @log_call
    def optimize(
        plan_number: Union[str, int, float, Path],
        parameter_bounds: Dict[
            str,
            Union[Tuple[float, float], List[float], Dict[str, float]],
        ],
        apply_fn: ApplyFn,
        calibration_points: Sequence[Union[CalibrationPoint, dict]],
        metric: str = "rmse",
        method: str = "nelder-mead",
        max_iterations: int = 50,
        num_cores: int = 4,
        force_geompre: bool = False,
        ras_object: Any = None,
    ) -> dict:
        """
        Optimize one plan against one calibration objective.
        """
        metric_name = _normalize_metric(metric)
        points = _coerce_calibration_points(calibration_points)

        parameter_names: List[str] = []
        bounds: List[Tuple[float, float]] = []
        for parameter_name, bound_spec in parameter_bounds.items():
            if isinstance(bound_spec, dict):
                lower = float(
                    bound_spec.get("min", bound_spec.get("minimum"))
                )
                upper = float(
                    bound_spec.get("max", bound_spec.get("maximum"))
                )
            else:
                lower, upper = bound_spec
                lower = float(lower)
                upper = float(upper)

            if lower >= upper:
                raise ValueError(
                    f"Invalid bounds for '{parameter_name}': "
                    f"({lower}, {upper})"
                )

            parameter_names.append(parameter_name)
            bounds.append((lower, upper))

        x0 = np.array(
            [(lower + upper) / 2.0 for lower, upper in bounds],
            dtype=float,
        )
        method_name = _SCIPY_METHODS.get(
            str(method).strip().lower(),
            method,
        )

        if method_name == "Nelder-Mead":
            logger.warning(
                "SciPy's Nelder-Mead bound handling varies by version; "
                "midpoint initialization stays inside the requested bounds, "
                "but strict bound enforcement depends on SciPy."
            )

        iteration_history: List[dict] = []
        penalty = 1.0e12

        def objective_fn(x_values: np.ndarray) -> float:
            parameter_values = {
                parameter_name: float(value)
                for parameter_name, value in zip(parameter_names, x_values)
            }

            try:
                evaluation = RasCalibrate.evaluate_single(
                    plan_number=plan_number,
                    parameter_values=parameter_values,
                    apply_fn=apply_fn,
                    calibration_points=points,
                    metric=metric_name,
                    num_cores=num_cores,
                    force_geompre=force_geompre,
                    ras_object=ras_object,
                )
                raw_objective = evaluation.get("overall_objective", np.nan)
                if pd.isna(raw_objective):
                    optimization_value = penalty
                elif metric_name in _HIGHER_IS_BETTER:
                    optimization_value = -float(raw_objective)
                else:
                    optimization_value = float(raw_objective)
                success = bool(evaluation.get("success"))
            except Exception as exc:
                raw_objective = np.nan
                optimization_value = penalty
                success = False
                logger.warning(
                    "Optimization iteration failed for parameters %s: %s",
                    parameter_values,
                    exc,
                )

            history_row = {
                "raw_objective": raw_objective,
                "optimization_value": optimization_value,
                "success": success,
            }
            history_row.update(parameter_values)
            iteration_history.append(history_row)
            return optimization_value

        optimization_result = minimize(
            objective_fn,
            x0,
            method=method_name,
            bounds=bounds,
            options={"maxiter": max_iterations},
        )

        best_parameters = {
            parameter_name: float(value)
            for parameter_name, value in zip(
                parameter_names,
                optimization_result.x,
            )
        }
        best_evaluation = RasCalibrate.evaluate_single(
            plan_number=plan_number,
            parameter_values=best_parameters,
            apply_fn=apply_fn,
            calibration_points=points,
            metric=metric_name,
            num_cores=num_cores,
            force_geompre=force_geompre,
            ras_object=ras_object,
        )

        return {
            "metric": metric_name,
            "method": method_name,
            "success": bool(optimization_result.success),
            "message": str(optimization_result.message),
            "starting_parameters": {
                parameter_name: float(value)
                for parameter_name, value in zip(parameter_names, x0)
            },
            "best_parameters": best_parameters,
            "best_objective": best_evaluation.get("overall_objective"),
            "nit": getattr(optimization_result, "nit", None),
            "nfev": getattr(optimization_result, "nfev", None),
            "bounds": {
                parameter_name: tuple(bound)
                for parameter_name, bound in zip(parameter_names, bounds)
            },
            "iteration_history": pd.DataFrame(iteration_history),
            "best_evaluation": best_evaluation,
        }
