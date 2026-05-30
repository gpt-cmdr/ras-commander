"""
RasMonteCarlo: General-purpose Monte Carlo uncertainty analysis for HEC-RAS.

This module generates parameter samples, runs ensemble simulations via
RasPermutation, and computes variable-agnostic ensemble statistics from HDF
outputs. The workflow can generate large cloned project folders and many
gigabytes of HDF results. Users are responsible for cleaning up batch folders
and intermediate outputs when they are no longer needed.

Scope and limitations
----------------------
- **Sensitivity analysis is OUT OF SCOPE in this version.** There are no
  Morris (``generate_morris_samples`` / mu*/sigma) or Sobol
  (``generate_sobol_samples`` / S1/ST ``sensitivity_indices``) samplers. Do
  not assume variance-based or screening sensitivity analysis is available.
  Only forward uncertainty propagation (uniform / truncated-normal / Latin
  hypercube sampling -> ensemble run -> percentile statistics) is supported.
- **Independent per-parameter sampling.** Each parameter column is sampled
  independently (LHS strata are independent across columns). There is no
  correlation structure between parameters. For spatially distributed
  roughness this can OVERSTATE uncertainty, because adjacent land-cover /
  calibration errors are typically correlated. Use a single shared
  zone-level multiplier column when correlated roughness is intended.
- **Flow multiplier semantics.** ``make_flow_multiplier_apply_fn`` writes
  ``Flow Hydrograph QMult=``, which is a UNIFORM ordinate multiplier: it
  scales the peak AND the volume of the inflow series together while
  preserving timing and hydrograph shape. It is NOT a flow-frequency / AEP
  sample, NOT a peak-only perturbation, and NOT a volume-only perturbation.
- **Bias control.** Failed / missing / extraction-error samples are surfaced
  (not silently dropped) and the statistics entry points refuse to compute
  percentiles when too large a fraction of samples were dropped (see
  ``min_valid_fraction``). Runs that finished with compute errors
  (``completed_with_errors``) are EXCLUDED by default; opt in with
  ``include_error_runs=True``.
- **Convergence.** Use :meth:`RasMonteCarlo.convergence` to check whether a
  running statistic has stabilized before trusting percentile bands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import qmc, truncnorm

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPermutation import RasPermutation


logger = get_logger(__name__)

_SUPPORTED_METHODS = {
    "truncated_normal",
    "uniform",
    "latin_hypercube",
}

_POINT_STAT_PERCENTILES = [1, 10, 50, 90, 99]

# Statuses that count as a clean, usable sample by default.
_VALID_STATUSES = {"completed"}

# Status for a run that finished but reported compute errors / instability.
# Excluded by default; admitted only when include_error_runs=True.
_ERROR_STATUS = "completed_with_errors"

# Backward-compatible alias: the full set of statuses that can be admitted
# when include_error_runs=True.
_COMPLETED_STATUSES = _VALID_STATUSES | {_ERROR_STATUS}

# Default minimum fraction of total samples that must yield usable values
# before percentile / interval statistics are computed.
_DEFAULT_MIN_VALID_FRACTION = 0.95

# Physically plausible Manning's-n bounds (USGS WSP 2339 / research_findings).
_MANNINGS_N_PHYSICAL_MIN = 0.01
_MANNINGS_N_PHYSICAL_MAX = 0.2

# Parameter "kind" hints that represent roughness coefficients.
_MANNINGS_KINDS = {"mannings_n", "manning", "mannings", "roughness", "n"}

# Parameter "kind" hints that must be non-negative.
_NONNEGATIVE_KINDS = _MANNINGS_KINDS | {"flow", "discharge", "flow_multiplier"}

_DXV_ALIASES = {
    "dxv",
    "dv",
    "depth_x_velocity",
    "depth_velocity",
}

_WSE_ALIASES = {"wse", "water_surface", "water surface"}
_DEPTH_ALIASES = {"depth"}
_VELOCITY_ALIASES = {"velocity"}
_VELOCITY_X_ALIASES = {"velocity_x", "velocity x"}
_VELOCITY_Y_ALIASES = {"velocity_y", "velocity y"}

_FLOW_MULTIPLIER_COLUMNS = (
    "flow_multiplier",
    "qmult",
    "multiplier",
    "flow_qmult",
)

_BREACH_GEOM_INDEX = {
    "centerline": 0,
    "initial_width": 1,
    "final_bottom_elev": 2,
    "left_slope": 3,
    "right_slope": 4,
    "active": 5,
    "weir_coef": 6,
    "top_elev": 7,
    "formation_method": 8,
    "formation_time": 9,
}

_BREACH_SCALAR_FIELDS = {
    "is_active",
    "method",
    "progression_mode",
    "user_growth_flag",
    "user_growth_ratio",
    "mass_wasting_option",
    "dlb_soil_type",
    "dlb_core_soil_type",
    "dlb_cover_option",
    "dlb_breach_direction",
}

_SUPPORTED_BREACH_TARGETS = (
    set(_BREACH_GEOM_INDEX) | _BREACH_SCALAR_FIELDS
)

_BREACH_INT_FIELDS = {
    "method",
    "progression_mode",
    "formation_method",
    "user_growth_flag",
    "mass_wasting_option",
    "dlb_soil_type",
    "dlb_core_soil_type",
    "dlb_cover_option",
    "dlb_breach_direction",
}

_BREACH_BOOL_FIELDS = {"active", "is_active"}

_DEFAULT_BREACH_COLUMN_MAP = {
    "initial_width": "breach_width",
    "final_bottom_elev": "breach_bottom_elev",
    "left_slope": "breach_left_slope",
    "right_slope": "breach_right_slope",
    "formation_time": "breach_formation_time",
    "method": "breach_method",
}


class RasMonteCarlo:
    """Static helpers for Monte Carlo uncertainty analysis."""

    @staticmethod
    def _validate_param_specs(
        param_specs: Dict[str, dict],
    ) -> Dict[str, dict]:
        """Validate parameter specifications and preserve input order."""
        if not isinstance(param_specs, dict) or not param_specs:
            raise ValueError("param_specs must be a non-empty dictionary")

        validated: Dict[str, dict] = {}
        for param_name, spec in param_specs.items():
            if not isinstance(param_name, str) or not param_name.strip():
                raise ValueError("Parameter names must be non-empty strings")

            if not isinstance(spec, dict):
                raise TypeError(
                    f"Specification for '{param_name}' must be a dict"
                )

            if "min" not in spec or "max" not in spec:
                raise ValueError(
                    f"Parameter '{param_name}' must define 'min' and 'max'"
                )

            minimum = float(spec["min"])
            maximum = float(spec["max"])
            if minimum > maximum:
                raise ValueError(
                    f"Parameter '{param_name}' has min > max "
                    f"({minimum} > {maximum})"
                )

            cleaned = dict(spec)
            cleaned["min"] = minimum
            cleaned["max"] = maximum

            if "mean" in cleaned and cleaned["mean"] is not None:
                cleaned["mean"] = float(cleaned["mean"])

            if "std" in cleaned and cleaned["std"] is not None:
                cleaned["std"] = float(cleaned["std"])
                if cleaned["std"] <= 0:
                    raise ValueError(
                        f"Parameter '{param_name}' must have std > 0"
                    )

            # H3: optional physical-range validation driven by a param kind
            # hint. Accept either "kind" or "param_kind".
            kind_value = cleaned.get("kind", cleaned.get("param_kind"))
            kind = None
            if kind_value is not None:
                kind = str(kind_value).strip().lower()
                cleaned["kind"] = kind

            RasMonteCarlo._warn_physical_bounds(param_name, minimum, maximum, kind)

            validated[param_name] = cleaned

        return validated

    @staticmethod
    def _warn_physical_bounds(
        param_name: str,
        minimum: float,
        maximum: float,
        kind: Optional[str],
    ) -> None:
        """Warn when parameter bounds are physically implausible.

        Always warns on physically impossible values (negative roughness or
        flow). When ``kind`` indicates a Manning's-n parameter, also warns when
        bounds fall outside the plausible roughness range
        [``_MANNINGS_N_PHYSICAL_MIN``, ``_MANNINGS_N_PHYSICAL_MAX``].
        """
        normalized_kind = (kind or "").strip().lower()

        # Always warn on physically impossible values for roughness/flow.
        if normalized_kind in _NONNEGATIVE_KINDS and minimum < 0.0:
            logger.warning(
                "Parameter '%s' (kind=%s) has a negative lower bound (%.4g); "
                "negative %s values are physically impossible.",
                param_name,
                normalized_kind,
                minimum,
                normalized_kind,
            )

        if normalized_kind in _MANNINGS_KINDS:
            if (
                minimum < _MANNINGS_N_PHYSICAL_MIN
                or maximum > _MANNINGS_N_PHYSICAL_MAX
            ):
                logger.warning(
                    "Parameter '%s' Manning's-n bounds [%.4g, %.4g] fall "
                    "outside the physically plausible range [%.2f, %.2f]. "
                    "Verify these roughness values are intended.",
                    param_name,
                    minimum,
                    maximum,
                    _MANNINGS_N_PHYSICAL_MIN,
                    _MANNINGS_N_PHYSICAL_MAX,
                )

    @staticmethod
    def _get_bounds(spec: dict) -> Tuple[float, float]:
        """Return min/max bounds from one parameter specification."""
        return float(spec["min"]), float(spec["max"])

    @staticmethod
    def _has_normal_parameters(spec: dict) -> bool:
        """Return True when a spec supports truncated normal sampling."""
        return (
            spec.get("mean") is not None
            and spec.get("std") is not None
        )

    @staticmethod
    def _sample_uniform(
        spec: dict,
        n_samples: int,
        rng: Optional[np.random.Generator] = None,
    ) -> np.ndarray:
        """Sample uniformly within min/max bounds.

        H5: uses the supplied ``Generator`` rather than the global numpy RNG.
        """
        minimum, maximum = RasMonteCarlo._get_bounds(spec)
        if minimum == maximum:
            return np.full(n_samples, minimum, dtype=float)

        if rng is None:
            rng = np.random.default_rng()
        return rng.uniform(minimum, maximum, size=n_samples)

    @staticmethod
    def _sample_truncated_normal(
        spec: dict,
        n_samples: int,
        rng: Optional[np.random.Generator] = None,
    ) -> np.ndarray:
        """Sample from a truncated normal distribution within bounds.

        H5: passes ``random_state=rng`` to ``truncnorm.rvs`` so no global RNG
        state is consumed or mutated.
        """
        if rng is None:
            rng = np.random.default_rng()

        if not RasMonteCarlo._has_normal_parameters(spec):
            return RasMonteCarlo._sample_uniform(spec, n_samples, rng=rng)

        minimum, maximum = RasMonteCarlo._get_bounds(spec)
        if minimum == maximum:
            return np.full(n_samples, minimum, dtype=float)

        mean = float(spec["mean"])
        std = float(spec["std"])
        a = (minimum - mean) / std
        b = (maximum - mean) / std
        return truncnorm.rvs(
            a,
            b,
            loc=mean,
            scale=std,
            size=n_samples,
            random_state=rng,
        )

    @staticmethod
    def _transform_lhs_column(
        unit_values: np.ndarray,
        spec: dict,
    ) -> np.ndarray:
        """Map Latin hypercube unit samples onto a bounded distribution."""
        minimum, maximum = RasMonteCarlo._get_bounds(spec)
        if minimum == maximum:
            return np.full(len(unit_values), minimum, dtype=float)

        if RasMonteCarlo._has_normal_parameters(spec):
            mean = float(spec["mean"])
            std = float(spec["std"])
            a = (minimum - mean) / std
            b = (maximum - mean) / std
            eps = np.finfo(float).eps
            clipped = np.clip(unit_values, eps, 1.0 - eps)
            return truncnorm.ppf(clipped, a, b, loc=mean, scale=std)

        return minimum + (maximum - minimum) * unit_values

    @staticmethod
    def _prepare_samples_df(samples_df: pd.DataFrame) -> pd.DataFrame:
        """Normalize and validate a samples DataFrame for execution."""
        if samples_df is None or len(samples_df) == 0:
            raise ValueError("samples_df must contain at least one sample")

        prepared = samples_df.copy().reset_index(drop=True)

        if "sample_id" not in prepared.columns:
            prepared.insert(0, "sample_id", np.arange(1, len(prepared) + 1))

        prepared["sample_id"] = pd.to_numeric(
            prepared["sample_id"],
            errors="raise",
        ).astype(int)

        if prepared["sample_id"].duplicated().any():
            raise ValueError("sample_id values must be unique")

        prepared = prepared.sort_values("sample_id").reset_index(drop=True)
        expected_ids = np.arange(1, len(prepared) + 1)
        if not np.array_equal(prepared["sample_id"].to_numpy(), expected_ids):
            raise ValueError(
                "sample_id must contain sequential integers starting at 1"
            )

        parameter_columns = [
            column for column in prepared.columns
            if column != "sample_id"
        ]
        if not parameter_columns:
            raise ValueError(
                "samples_df must contain at least one parameter column"
            )

        return prepared[["sample_id", *parameter_columns]]

    @staticmethod
    def _normalize_percentiles(
        percentiles: List[float],
    ) -> List[float]:
        """Validate percentile requests."""
        if not percentiles:
            raise ValueError("percentiles must contain at least one value")

        normalized: List[float] = []
        for percentile in percentiles:
            value = float(percentile)
            if value < 0.0 or value > 100.0:
                raise ValueError(
                    f"Percentile must be between 0 and 100: {value}"
                )
            normalized.append(value)

        return normalized

    @staticmethod
    def _normalize_confidence_level(confidence_level: float) -> float:
        """Validate confidence level in (0, 1)."""
        confidence_level = float(confidence_level)
        if confidence_level <= 0.0 or confidence_level >= 1.0:
            raise ValueError("confidence_level must be between 0 and 1")
        return confidence_level

    @staticmethod
    def _normalize_variable_key(variable: str) -> str:
        """Normalize common variable aliases used by Monte Carlo workflows."""
        if not isinstance(variable, str) or not variable.strip():
            raise ValueError("variable must be a non-empty string")

        cleaned = variable.strip()
        alias = cleaned.lower().replace(" ", "_")

        if alias in _DXV_ALIASES:
            return "dxv"
        if alias in {value.replace(" ", "_") for value in _WSE_ALIASES}:
            return "wse"
        if alias in _DEPTH_ALIASES:
            return "depth"
        if alias in {value.replace(" ", "_") for value in _VELOCITY_ALIASES}:
            return "velocity"
        if alias in {value.replace(" ", "_") for value in _VELOCITY_X_ALIASES}:
            return "velocity_x"
        if alias in {value.replace(" ", "_") for value in _VELOCITY_Y_ALIASES}:
            return "velocity_y"
        return cleaned

    @staticmethod
    def _query_variable_name(variable: str) -> Optional[str]:
        """Map a normalized Monte Carlo variable onto HdfResultsQuery input."""
        variable_key = RasMonteCarlo._normalize_variable_key(variable)
        if variable_key == "dxv":
            return None
        if variable_key == "wse":
            return "wse"
        return variable_key

    @staticmethod
    def _mesh_variable_name(variable: str) -> str:
        """Map a normalized Monte Carlo variable onto cell-timeseries names."""
        variable_key = RasMonteCarlo._normalize_variable_key(variable)
        if variable_key == "wse":
            return "Water Surface"
        if variable_key == "depth":
            return "Depth"
        if variable_key == "velocity":
            return "Velocity"
        if variable_key == "velocity_x":
            return "Velocity X"
        if variable_key == "velocity_y":
            return "Velocity Y"
        return str(variable)

    @staticmethod
    def _normalize_weights(
        weights: Optional[Dict[int, float]],
    ) -> Optional[Dict[int, float]]:
        """Validate an optional sample-id to weight mapping."""
        if weights is None:
            return None

        if not isinstance(weights, dict) or not weights:
            raise ValueError("weights must be a non-empty dict when provided")

        normalized: Dict[int, float] = {}
        for sample_id, weight in weights.items():
            normalized_id = int(sample_id)
            normalized_weight = float(weight)
            if not np.isfinite(normalized_weight):
                raise ValueError(
                    f"Weight for sample_id {normalized_id} must be finite"
                )
            if normalized_weight < 0.0:
                raise ValueError(
                    f"Weight for sample_id {normalized_id} must be >= 0"
                )
            normalized[normalized_id] = normalized_weight

        return normalized

    @staticmethod
    def status_histogram(ensemble_result: dict) -> Dict[str, int]:
        """Return a full status histogram from an ensemble result.

        Counts every distinct ``status`` value present in ``results_df`` plus
        a ``total`` key. Useful for surfacing failed / incomplete /
        completed_with_errors runs that statistics would otherwise hide.
        """
        if not isinstance(ensemble_result, dict):
            raise TypeError("ensemble_result must be a dictionary")
        results_df = ensemble_result.get("results_df")
        if not isinstance(results_df, pd.DataFrame):
            raise TypeError("ensemble_result['results_df'] must be a DataFrame")

        histogram: Dict[str, int] = {"total": int(len(results_df))}
        if "status" in results_df.columns and not results_df.empty:
            statuses = (
                results_df["status"].astype(str).str.strip().str.lower()
            )
            counts = statuses.value_counts()
            for status_value, count in counts.items():
                histogram[str(status_value)] = int(count)
        return histogram

    @staticmethod
    def _get_completed_results_df(
        ensemble_result: dict,
        include_error_runs: bool = False,
    ) -> pd.DataFrame:
        """Extract usable ensemble rows with HDF paths.

        Args:
            ensemble_result: dict with a 'results_df' DataFrame.
            include_error_runs: when True, also admit rows whose status is
                ``completed_with_errors`` (runs that finished but reported
                compute errors / instability). Excluded by default (C2).
        """
        if not isinstance(ensemble_result, dict):
            raise TypeError("ensemble_result must be a dictionary")

        if "results_df" not in ensemble_result:
            raise ValueError(
                "ensemble_result must contain a 'results_df' entry"
            )

        results_df = ensemble_result["results_df"]
        if not isinstance(results_df, pd.DataFrame):
            raise TypeError("ensemble_result['results_df'] must be a DataFrame")

        if results_df.empty:
            raise ValueError("ensemble_result['results_df'] is empty")

        required_columns = {"status", "hdf_path"}
        missing = required_columns - set(results_df.columns)
        if missing:
            raise ValueError(
                "ensemble_result['results_df'] is missing required "
                f"columns: {sorted(missing)}"
            )

        completed = results_df.copy()
        if "sample_id" in completed.columns:
            completed["sample_id"] = pd.to_numeric(
                completed["sample_id"],
                errors="coerce",
            )
        else:
            completed["sample_id"] = np.arange(1, len(completed) + 1)

        admissible = set(_VALID_STATUSES)
        if include_error_runs:
            admissible.add(_ERROR_STATUS)

        statuses = completed["status"].astype(str).str.strip().str.lower()

        # Surface error runs that are being excluded so the bias is visible.
        n_error_runs = int((statuses == _ERROR_STATUS).sum())
        if n_error_runs and not include_error_runs:
            logger.warning(
                "Excluding %d '%s' run(s) from statistics. These finished but "
                "reported compute errors/instability. Pass "
                "include_error_runs=True to admit them.",
                n_error_runs,
                _ERROR_STATUS,
            )

        completed = completed[
            statuses.isin(admissible)
            & completed["hdf_path"].notna()
            & completed["sample_id"].notna()
        ].copy()

        if completed.empty:
            raise ValueError(
                "No usable samples with HDF paths were found in results_df "
                f"(admissible statuses: {sorted(admissible)})"
            )

        completed["sample_id"] = completed["sample_id"].astype(int)
        completed = completed.sort_values("sample_id").reset_index(drop=True)
        return completed

    @staticmethod
    def _coerce_points(points: List[tuple]) -> pd.DataFrame:
        """Convert a point list into a simple indexed DataFrame."""
        if not points:
            raise ValueError("points must contain at least one (x, y) tuple")

        try:
            points_df = pd.DataFrame(points, columns=["x", "y"])
        except Exception as exc:
            raise ValueError(
                "points must be a list of (x, y) tuples"
            ) from exc

        if points_df.empty:
            raise ValueError("points must contain at least one row")

        points_df["x"] = pd.to_numeric(points_df["x"], errors="raise")
        points_df["y"] = pd.to_numeric(points_df["y"], errors="raise")
        points_df.insert(0, "point_index", np.arange(len(points_df)))
        return points_df[["point_index", "x", "y"]]

    @staticmethod
    def _paths_match(path_a: Any, path_b: Any) -> bool:
        """Compare paths without forcing UNC or symlink resolution."""
        try:
            return Path(str(path_a)).absolute() == Path(str(path_b)).absolute()
        except Exception:
            return False

    @staticmethod
    def _extract_plan_number_from_path(plan_path: Path) -> Optional[str]:
        """Extract the two-digit plan number from a `.p##` file path."""
        match = re.search(r"\.p(\d{1,2})$", plan_path.name, flags=re.IGNORECASE)
        if match:
            return match.group(1).zfill(2)
        return None

    @staticmethod
    def _read_plan_key(plan_path: Path, key: str) -> Optional[str]:
        """Read one `key=value` entry from a plaintext plan file."""
        if not plan_path.exists():
            return None

        with open(
            plan_path,
            "r",
            encoding="utf-8",
            errors="ignore",
        ) as handle:
            for line in handle:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()

        return None

    @staticmethod
    def _find_plan_row(
        plan_path: Path,
        ras_object: Any = None,
    ) -> Optional[pd.Series]:
        """Resolve a plan path against the provided ras_object plan_df."""
        if ras_object is None:
            return None

        plan_df = getattr(ras_object, "plan_df", None)
        if plan_df is None or len(plan_df) == 0:
            return None

        if "full_path" in plan_df.columns:
            mask = plan_df["full_path"].notna() & plan_df["full_path"].map(
                lambda value: RasMonteCarlo._paths_match(value, plan_path)
            )
            matched = plan_df[mask]
            if not matched.empty:
                return matched.iloc[0]

        plan_number = RasMonteCarlo._extract_plan_number_from_path(plan_path)
        if (
            plan_number is not None
            and "plan_number" in plan_df.columns
        ):
            matched = plan_df[
                plan_df["plan_number"].astype(str).str.zfill(2) == plan_number
            ]
            if not matched.empty:
                return matched.iloc[0]

        return None

    @staticmethod
    def _build_component_path(
        plan_path: Path,
        raw_reference: Any,
        prefix: str,
    ) -> Optional[Path]:
        """Build a sibling project component path from a plan-relative ref."""
        if raw_reference is None:
            return None

        try:
            if pd.isna(raw_reference):
                return None
        except Exception:
            pass

        reference = str(raw_reference).strip()
        if not reference:
            return None

        candidate = Path(reference)
        if candidate.is_absolute():
            return candidate

        project_name = plan_path.stem
        name = candidate.name

        if candidate.suffix:
            return plan_path.parent / name

        if not name.lower().startswith(prefix.lower()):
            name = f"{prefix}{name}"

        return plan_path.parent / f"{project_name}.{name}"

    @staticmethod
    def _resolve_plan_dependencies(
        plan_path: Path,
        ras_object: Any = None,
    ) -> Dict[str, Optional[Path]]:
        """Resolve geometry and unsteady file paths for a generated plan."""
        plan_path = Path(plan_path)
        plan_row = RasMonteCarlo._find_plan_row(plan_path, ras_object=ras_object)

        geom_path = None
        unsteady_path = None

        if plan_row is not None:
            geom_value = plan_row.get("Geom Path")
            if pd.notna(geom_value):
                geom_path = Path(str(geom_value))

            flow_path_value = plan_row.get("Flow Path")
            if pd.notna(flow_path_value):
                flow_candidate = Path(str(flow_path_value))
                if flow_candidate.suffix.lower().startswith(".u"):
                    unsteady_path = flow_candidate

            if unsteady_path is None:
                flow_file_value = plan_row.get("Flow File")
                unsteady_path = RasMonteCarlo._build_component_path(
                    plan_path,
                    flow_file_value,
                    prefix="u",
                )

            if geom_path is None:
                geom_path = RasMonteCarlo._build_component_path(
                    plan_path,
                    plan_row.get("Geom File"),
                    prefix="g",
                )

        if geom_path is None:
            geom_path = RasMonteCarlo._build_component_path(
                plan_path,
                RasMonteCarlo._read_plan_key(plan_path, "Geom File"),
                prefix="g",
            )

        if unsteady_path is None:
            unsteady_path = RasMonteCarlo._build_component_path(
                plan_path,
                RasMonteCarlo._read_plan_key(plan_path, "Flow File"),
                prefix="u",
            )

        geom_hdf_path = None
        if geom_path is not None:
            geom_hdf_path = Path(str(geom_path) + ".hdf")

        return {
            "plan_path": plan_path,
            "geom_path": geom_path,
            "geom_hdf_path": geom_hdf_path,
            "unsteady_path": unsteady_path,
        }

    @staticmethod
    def _resolve_geometry_hdf_from_results(
        hdf_path: Path,
        ras_object: Any = None,
    ) -> Optional[Path]:
        """Resolve the companion geometry HDF for a results HDF path."""
        companion_plan = Path(hdf_path).with_suffix("")
        dependencies = RasMonteCarlo._resolve_plan_dependencies(
            companion_plan,
            ras_object=ras_object,
        )
        return dependencies["geom_hdf_path"]

    @staticmethod
    def _require_parameter_columns(
        param_row: pd.Series,
        columns: List[str],
        context: str,
    ) -> None:
        """Ensure an apply_fn has every parameter column it needs."""
        missing = [column for column in columns if column not in param_row.index]
        if missing:
            raise ValueError(
                f"{context} is missing required parameter columns: {missing}"
            )

    @staticmethod
    def _safe_matrix_percentile(
        values: np.ndarray,
        percentile: float,
    ) -> np.ndarray:
        """Compute one percentile per column without all-NaN warnings."""
        result = np.full(values.shape[1], np.nan, dtype=float)
        for column_index in range(values.shape[1]):
            column = values[:, column_index]
            finite = column[np.isfinite(column)]
            if finite.size == 0:
                continue
            result[column_index] = float(np.percentile(finite, percentile))
        return result

    @staticmethod
    def _safe_matrix_reduction(
        values: np.ndarray,
        reducer: str,
    ) -> np.ndarray:
        """Compute one reduction per column without all-NaN warnings."""
        result = np.full(values.shape[1], np.nan, dtype=float)
        for column_index in range(values.shape[1]):
            column = values[:, column_index]
            finite = column[np.isfinite(column)]
            if finite.size == 0:
                continue
            if reducer == "min":
                result[column_index] = float(np.min(finite))
            elif reducer == "max":
                result[column_index] = float(np.max(finite))
            else:
                raise ValueError(f"Unsupported reducer: {reducer}")
        return result

    @staticmethod
    def _weighted_percentile_1d(
        values: np.ndarray,
        weights: np.ndarray,
        percentile: float,
    ) -> float:
        """Return one weighted percentile from finite values only."""
        mask = (
            np.isfinite(values)
            & np.isfinite(weights)
            & (weights > 0.0)
        )
        if not np.any(mask):
            return float("nan")

        finite_values = values[mask]
        finite_weights = weights[mask]
        order = np.argsort(finite_values, kind="mergesort")
        finite_values = finite_values[order]
        finite_weights = finite_weights[order]

        if len(finite_values) == 1:
            return float(finite_values[0])

        cumulative = np.cumsum(finite_weights)
        total_weight = float(cumulative[-1])
        if total_weight <= 0.0:
            return float("nan")

        positions = (cumulative - 0.5 * finite_weights) / total_weight
        quantile = float(np.clip(percentile / 100.0, 0.0, 1.0))
        return float(
            np.interp(
                quantile,
                positions,
                finite_values,
                left=finite_values[0],
                right=finite_values[-1],
            )
        )

    @staticmethod
    def _weighted_matrix_percentile(
        values: np.ndarray,
        weights: np.ndarray,
        percentile: float,
    ) -> np.ndarray:
        """Compute a weighted percentile per column."""
        result = np.full(values.shape[1], np.nan, dtype=float)
        for column_index in range(values.shape[1]):
            result[column_index] = RasMonteCarlo._weighted_percentile_1d(
                values[:, column_index],
                weights,
                percentile,
            )
        return result

    @staticmethod
    def _summarize_matrix(
        values: np.ndarray,
        percentiles: List[float],
        weights: Optional[np.ndarray] = None,
    ) -> Tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        Dict[float, np.ndarray],
    ]:
        """Compute counts, weight sums, moments, and percentiles per column."""
        if values.ndim != 2:
            raise ValueError("values must be a 2D matrix")

        counts = np.sum(np.isfinite(values), axis=0).astype(int)
        mean = np.full(values.shape[1], np.nan, dtype=float)
        std = np.full(values.shape[1], np.nan, dtype=float)

        if weights is None:
            weight_sums = counts.astype(float)

            for column_index in range(values.shape[1]):
                column = values[:, column_index]
                finite = column[np.isfinite(column)]
                if finite.size == 0:
                    continue
                mean[column_index] = float(np.mean(finite))
                std[column_index] = float(np.std(finite, ddof=0))

            percentile_map = {
                percentile: RasMonteCarlo._safe_matrix_percentile(
                    values,
                    percentile,
                )
                for percentile in percentiles
            }
            return counts, weight_sums, mean, std, percentile_map

        weights = np.asarray(weights, dtype=float)
        if weights.ndim != 1 or len(weights) != values.shape[0]:
            raise ValueError(
                "weights must be a 1D array aligned to the sample dimension"
            )

        if not np.all(np.isfinite(weights)):
            raise ValueError("weights must be finite")

        if np.any(weights < 0.0):
            raise ValueError("weights must be >= 0")

        weight_sums = np.zeros(values.shape[1], dtype=float)
        for column_index in range(values.shape[1]):
            column = values[:, column_index]
            mask = np.isfinite(column) & (weights > 0.0)
            if not np.any(mask):
                continue

            finite_values = column[mask]
            finite_weights = weights[mask]
            total_weight = float(np.sum(finite_weights))
            if total_weight <= 0.0:
                continue

            weight_sums[column_index] = total_weight
            mean[column_index] = float(
                np.dot(finite_weights, finite_values) / total_weight
            )
            variance = np.dot(
                finite_weights,
                np.square(finite_values - mean[column_index]),
            ) / total_weight
            std[column_index] = float(np.sqrt(max(variance, 0.0)))

        percentile_map = {
            percentile: RasMonteCarlo._weighted_matrix_percentile(
                values,
                weights,
                percentile,
            )
            for percentile in percentiles
        }
        return counts, weight_sums, mean, std, percentile_map

    @staticmethod
    def _column_exceedance_frequency(
        values: np.ndarray,
        threshold: float,
    ) -> np.ndarray:
        """Compute P(value > threshold) per column from a sample matrix."""
        valid = np.isfinite(values)
        numerator = np.sum(valid & (values > float(threshold)), axis=0)
        denominator = np.sum(valid, axis=0)
        return np.divide(
            numerator.astype(float),
            denominator.astype(float),
            out=np.full(values.shape[1], np.nan, dtype=float),
            where=denominator > 0,
        )

    @staticmethod
    def _validate_alignment(
        reference_metadata: pd.DataFrame,
        current_metadata: pd.DataFrame,
        label: str,
    ) -> None:
        """Ensure point or cell ordering remains stable across samples."""
        if len(reference_metadata) != len(current_metadata):
            raise ValueError(f"{label} length changed across samples")

        if not reference_metadata.equals(current_metadata):
            raise ValueError(
                f"{label} changed across samples; aligned aggregation is "
                "not possible"
            )

    @staticmethod
    def _validate_mesh_dataset_alignment(
        mesh_name: str,
        left_values: np.ndarray,
        right_values: np.ndarray,
        left_cell_ids: np.ndarray,
        right_cell_ids: np.ndarray,
    ) -> None:
        """Ensure paired mesh datasets share time and cell indexing."""
        if left_values.shape != right_values.shape:
            raise ValueError(
                f"Depth/velocity shape mismatch for mesh '{mesh_name}': "
                f"{left_values.shape} vs {right_values.shape}"
            )

        if not np.array_equal(left_cell_ids, right_cell_ids):
            raise ValueError(
                f"Depth/velocity cell_id mismatch for mesh '{mesh_name}'"
            )

    @staticmethod
    def _extract_point_values(
        hdf_path: Path,
        points_df: pd.DataFrame,
        variable: str,
        ras_object: Any = None,
    ) -> np.ndarray:
        """Query one HDF at all requested points."""
        variable_key = RasMonteCarlo._normalize_variable_key(variable)
        if variable_key == "dxv":
            return RasMonteCarlo._extract_point_dxv_values(
                hdf_path,
                points_df,
                ras_object=ras_object,
            )

        from .hdf import HdfResultsQuery

        queried = HdfResultsQuery.query_points(
            hdf_path,
            points_df[["x", "y"]].to_numpy(dtype=float),
            variable=RasMonteCarlo._query_variable_name(variable_key),
            time_index="max",
            ras_object=ras_object,
        )

        if len(queried) != len(points_df):
            raise ValueError(
                "Point query returned a different number of rows than "
                "requested points"
            )

        return pd.to_numeric(
            queried["value"],
            errors="coerce",
        ).to_numpy(dtype=float)

    @staticmethod
    def _extract_point_dxv_values(
        hdf_path: Path,
        points_df: pd.DataFrame,
        ras_object: Any = None,
    ) -> np.ndarray:
        """Compute max(depth * velocity) at each queried point."""
        from .hdf import HdfResultsMesh, HdfResultsQuery

        assignments = HdfResultsQuery.query_points(
            hdf_path,
            points_df[["x", "y"]].to_numpy(dtype=float),
            variable="wse",
            time_index=-1,
            ras_object=ras_object,
        )

        if len(assignments) != len(points_df):
            raise ValueError(
                "Point-to-cell assignment returned a different number of rows "
                "than requested points"
            )

        mesh_names = sorted(assignments["mesh_name"].astype(str).unique())
        depth_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            mesh_names=mesh_names,
            var="Depth",
            truncate=False,
            ras_object=ras_object,
        )
        velocity_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            mesh_names=mesh_names,
            var="Velocity",
            truncate=False,
            ras_object=ras_object,
        )

        values = np.full(len(points_df), np.nan, dtype=float)
        for mesh_name, group in assignments.groupby("mesh_name", sort=False):
            if mesh_name not in depth_datasets or mesh_name not in velocity_datasets:
                raise ValueError(
                    f"Depth/velocity datasets are unavailable for mesh "
                    f"'{mesh_name}'"
                )

            depth_dataset = depth_datasets[mesh_name]
            velocity_dataset = velocity_datasets[mesh_name]
            if "Depth" not in depth_dataset or "Velocity" not in velocity_dataset:
                raise ValueError(
                    f"Depth/velocity variables are unavailable for mesh "
                    f"'{mesh_name}'"
                )

            depth_values = np.asarray(depth_dataset["Depth"].values, dtype=float)
            velocity_values = np.asarray(
                velocity_dataset["Velocity"].values,
                dtype=float,
            )
            depth_cell_ids = np.asarray(
                depth_dataset["Depth"].coords["cell_id"].values,
                dtype=int,
            )
            velocity_cell_ids = np.asarray(
                velocity_dataset["Velocity"].coords["cell_id"].values,
                dtype=int,
            )

            RasMonteCarlo._validate_mesh_dataset_alignment(
                str(mesh_name),
                depth_values,
                velocity_values,
                depth_cell_ids,
                velocity_cell_ids,
            )

            dxv_max = RasMonteCarlo._safe_matrix_reduction(
                depth_values * velocity_values,
                "max",
            )
            cell_ids = group["cell_id"].astype(int).to_numpy()
            if np.any(cell_ids < 0) or np.any(cell_ids >= len(dxv_max)):
                raise ValueError(
                    f"Point assignment produced out-of-range cell_ids for "
                    f"mesh '{mesh_name}'"
                )
            values[group.index.to_numpy()] = dxv_max[cell_ids]

        return values

    @staticmethod
    def _extract_mesh_wse_values(
        hdf_path: Path,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Extract sorted cell-level maximum WSE values from one HDF."""
        from .hdf import HdfResultsMesh

        mesh_df = HdfResultsMesh.get_mesh_max_ws(hdf_path)
        if mesh_df.empty:
            raise ValueError(f"No mesh max WSE rows found in {hdf_path}")

        required_columns = {
            "mesh_name",
            "cell_id",
            "maximum_water_surface",
        }
        missing = required_columns - set(mesh_df.columns)
        if missing:
            raise ValueError(
                f"Mesh results are missing required columns: {sorted(missing)}"
            )

        ordered = mesh_df[
            ["mesh_name", "cell_id", "maximum_water_surface"]
        ].copy()
        ordered["mesh_name"] = ordered["mesh_name"].astype(str)
        ordered["cell_id"] = pd.to_numeric(
            ordered["cell_id"],
            errors="raise",
        ).astype(int)
        ordered["maximum_water_surface"] = pd.to_numeric(
            ordered["maximum_water_surface"],
            errors="coerce",
        )
        ordered = ordered.sort_values(
            ["mesh_name", "cell_id"]
        ).reset_index(drop=True)

        metadata = ordered[["mesh_name", "cell_id"]].copy()
        values = ordered["maximum_water_surface"].to_numpy(dtype=float)
        return metadata, values

    @staticmethod
    def _extract_mesh_timeseries_max(
        hdf_path: Path,
        variable_name: str,
        ras_object: Any = None,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Extract max-over-time values for a cell-based 2D variable."""
        from .hdf import HdfResultsMesh

        mesh_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            var=variable_name,
            truncate=False,
            ras_object=ras_object,
        )

        if not mesh_datasets:
            raise ValueError(
                f"No mesh timeseries datasets were found for '{variable_name}'"
            )

        frames: List[pd.DataFrame] = []
        for mesh_name in sorted(mesh_datasets):
            dataset = mesh_datasets[mesh_name]
            if variable_name not in dataset:
                raise ValueError(
                    f"Variable '{variable_name}' is missing for mesh "
                    f"'{mesh_name}'"
                )

            data_array = dataset[variable_name]
            if "cell_id" not in data_array.dims:
                raise ValueError(
                    f"Variable '{variable_name}' is not cell-based for mesh "
                    f"'{mesh_name}'"
                )

            values = np.asarray(data_array.values, dtype=float)
            cell_ids = np.asarray(data_array.coords["cell_id"].values, dtype=int)
            max_values = RasMonteCarlo._safe_matrix_reduction(values, "max")

            frame = pd.DataFrame(
                {
                    "mesh_name": str(mesh_name),
                    "cell_id": cell_ids,
                    "value": max_values,
                }
            )
            frames.append(frame)

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values(
            ["mesh_name", "cell_id"]
        ).reset_index(drop=True)
        return (
            combined[["mesh_name", "cell_id"]].copy(),
            combined["value"].to_numpy(dtype=float),
        )

    @staticmethod
    def _extract_mesh_dxv_values(
        hdf_path: Path,
        ras_object: Any = None,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Extract max-over-time values of depth * velocity for all cells."""
        from .hdf import HdfResultsMesh

        depth_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            var="Depth",
            truncate=False,
            ras_object=ras_object,
        )
        velocity_datasets = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            var="Velocity",
            truncate=False,
            ras_object=ras_object,
        )

        mesh_names = sorted(set(depth_datasets) | set(velocity_datasets))
        if not mesh_names:
            raise ValueError("No depth/velocity datasets were found for dxv")

        frames: List[pd.DataFrame] = []
        for mesh_name in mesh_names:
            if mesh_name not in depth_datasets or mesh_name not in velocity_datasets:
                raise ValueError(
                    f"Depth/velocity datasets are unavailable for mesh "
                    f"'{mesh_name}'"
                )

            depth_dataset = depth_datasets[mesh_name]
            velocity_dataset = velocity_datasets[mesh_name]
            if "Depth" not in depth_dataset or "Velocity" not in velocity_dataset:
                raise ValueError(
                    f"Depth/velocity variables are unavailable for mesh "
                    f"'{mesh_name}'"
                )

            depth_values = np.asarray(depth_dataset["Depth"].values, dtype=float)
            velocity_values = np.asarray(
                velocity_dataset["Velocity"].values,
                dtype=float,
            )
            depth_cell_ids = np.asarray(
                depth_dataset["Depth"].coords["cell_id"].values,
                dtype=int,
            )
            velocity_cell_ids = np.asarray(
                velocity_dataset["Velocity"].coords["cell_id"].values,
                dtype=int,
            )

            RasMonteCarlo._validate_mesh_dataset_alignment(
                str(mesh_name),
                depth_values,
                velocity_values,
                depth_cell_ids,
                velocity_cell_ids,
            )

            dxv_max = RasMonteCarlo._safe_matrix_reduction(
                depth_values * velocity_values,
                "max",
            )
            frames.append(
                pd.DataFrame(
                    {
                        "mesh_name": str(mesh_name),
                        "cell_id": depth_cell_ids,
                        "value": dxv_max,
                    }
                )
            )

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values(
            ["mesh_name", "cell_id"]
        ).reset_index(drop=True)
        return (
            combined[["mesh_name", "cell_id"]].copy(),
            combined["value"].to_numpy(dtype=float),
        )

    @staticmethod
    def _extract_full_domain_query_fallback(
        hdf_path: Path,
        variable: str,
        ras_object: Any = None,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Query all cell centers as a fallback when cell-timeseries extraction
        is unavailable for a query-supported variable.
        """
        from .hdf import HdfMesh, HdfResultsQuery

        geom_hdf_path = RasMonteCarlo._resolve_geometry_hdf_from_results(
            hdf_path,
            ras_object=ras_object,
        )
        if geom_hdf_path is None or not geom_hdf_path.exists():
            raise FileNotFoundError(
                f"Could not resolve geometry HDF for {hdf_path}"
            )

        cell_points = HdfMesh.get_mesh_cell_points(geom_hdf_path)
        if cell_points.empty:
            raise ValueError(f"No mesh cell points found in {geom_hdf_path}")

        query_points = np.column_stack(
            (
                cell_points.geometry.x.to_numpy(dtype=float),
                cell_points.geometry.y.to_numpy(dtype=float),
            )
        )
        queried = HdfResultsQuery.query_points(
            hdf_path,
            query_points,
            variable=RasMonteCarlo._query_variable_name(variable),
            time_index="max",
            ras_object=ras_object,
        )

        combined = cell_points[["mesh_name", "cell_id"]].copy()
        combined["mesh_name"] = combined["mesh_name"].astype(str)
        combined["cell_id"] = pd.to_numeric(
            combined["cell_id"],
            errors="raise",
        ).astype(int)
        combined["value"] = pd.to_numeric(
            queried["value"],
            errors="coerce",
        ).to_numpy(dtype=float)

        combined = combined.sort_values(
            ["mesh_name", "cell_id"]
        ).reset_index(drop=True)
        return (
            combined[["mesh_name", "cell_id"]].copy(),
            combined["value"].to_numpy(dtype=float),
        )

    @staticmethod
    def _extract_full_domain_values(
        hdf_path: Path,
        variable: str,
        ras_object: Any = None,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """Extract one aligned cell vector for any supported full-domain var."""
        variable_key = RasMonteCarlo._normalize_variable_key(variable)

        if variable_key == "wse":
            return RasMonteCarlo._extract_mesh_wse_values(hdf_path)

        if variable_key == "dxv":
            return RasMonteCarlo._extract_mesh_dxv_values(
                hdf_path,
                ras_object=ras_object,
            )

        try:
            return RasMonteCarlo._extract_mesh_timeseries_max(
                hdf_path,
                RasMonteCarlo._mesh_variable_name(variable_key),
                ras_object=ras_object,
            )
        except Exception as exc:
            query_variable = RasMonteCarlo._query_variable_name(variable_key)
            if query_variable is None:
                raise
            logger.debug(
                "Falling back to full-domain point queries for %s in %s: %s",
                variable,
                hdf_path,
                exc,
            )
            return RasMonteCarlo._extract_full_domain_query_fallback(
                hdf_path,
                query_variable,
                ras_object=ras_object,
            )

    @staticmethod
    def _collect_ensemble_values(
        ensemble_result: dict,
        variable: str,
        points_of_interest: Optional[List[tuple]] = None,
        weights: Optional[Dict[int, float]] = None,
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
    ) -> dict:
        """Collect aligned sample vectors from an ensemble result.

        C2: dropped samples (missing HDF, extraction failures) and excluded
        error runs are surfaced via a per-sample status accounting, and a hard
        guard refuses to proceed when too few samples are usable.

        Args:
            include_error_runs: admit ``completed_with_errors`` runs.
            min_valid_fraction: minimum n_used/total ratio required to compute
                statistics. Raises ValueError below this unless
                ``allow_low_valid_fraction=True``.
            allow_low_valid_fraction: override the min_valid_fraction guard.
        """
        total_samples = 0
        results_df = ensemble_result.get("results_df") if isinstance(
            ensemble_result, dict
        ) else None
        if isinstance(results_df, pd.DataFrame):
            total_samples = int(len(results_df))

        completed_df = RasMonteCarlo._get_completed_results_df(
            ensemble_result,
            include_error_runs=include_error_runs,
        )
        if total_samples <= 0:
            total_samples = int(len(completed_df))

        normalized_weights = RasMonteCarlo._normalize_weights(weights)

        point_metadata = None
        cell_metadata = None
        value_arrays: List[np.ndarray] = []
        sample_ids: List[int] = []
        sample_weights: List[float] = []
        dropped_missing_hdf: List[int] = []
        dropped_extraction_error: List[int] = []

        if points_of_interest is not None:
            point_metadata = RasMonteCarlo._coerce_points(points_of_interest)

        for _, row in completed_df.iterrows():
            sample_id = int(row["sample_id"])
            hdf_path = Path(str(row["hdf_path"]))

            if not hdf_path.exists():
                logger.warning(
                    "Dropping sample %s because HDF file does not exist: %s",
                    sample_id,
                    hdf_path,
                )
                dropped_missing_hdf.append(sample_id)
                continue

            if normalized_weights is None:
                sample_weight = 1.0
            else:
                if sample_id not in normalized_weights:
                    raise ValueError(
                        f"weights is missing sample_id {sample_id}"
                    )
                sample_weight = normalized_weights[sample_id]

            try:
                if point_metadata is not None:
                    values = RasMonteCarlo._extract_point_values(
                        hdf_path=hdf_path,
                        points_df=point_metadata,
                        variable=variable,
                        ras_object=ras_object,
                    )
                else:
                    current_cell_metadata, values = (
                        RasMonteCarlo._extract_full_domain_values(
                            hdf_path=hdf_path,
                            variable=variable,
                            ras_object=ras_object,
                        )
                    )
                    if cell_metadata is None:
                        cell_metadata = current_cell_metadata
                    else:
                        RasMonteCarlo._validate_alignment(
                            cell_metadata,
                            current_cell_metadata,
                            "mesh cell ordering",
                        )

                value_arrays.append(np.asarray(values, dtype=float))
                sample_ids.append(sample_id)
                sample_weights.append(float(sample_weight))

            except Exception as exc:
                logger.warning(
                    "Dropping sample %s during %s extraction: %s",
                    sample_id,
                    variable,
                    exc,
                )
                dropped_extraction_error.append(sample_id)

        if not value_arrays:
            raise ValueError("No completed ensemble samples could be aggregated")

        n_used = len(sample_ids)
        # C2: refuse to compute statistics when too many samples were dropped.
        # Dropped failures bias the tail (the conservative side of flood risk).
        if total_samples > 0:
            valid_fraction = n_used / total_samples
        else:
            valid_fraction = 1.0

        status_accounting = {
            "total_samples": int(total_samples),
            "n_samples_used": int(n_used),
            "valid_fraction": float(valid_fraction),
            "dropped_missing_hdf": dropped_missing_hdf,
            "dropped_extraction_error": dropped_extraction_error,
            "status_histogram": RasMonteCarlo.status_histogram(ensemble_result),
            "include_error_runs": bool(include_error_runs),
        }

        if (
            not allow_low_valid_fraction
            and valid_fraction < float(min_valid_fraction)
        ):
            raise ValueError(
                "Refusing to compute statistics: only "
                f"{n_used}/{total_samples} samples were usable "
                f"(valid_fraction={valid_fraction:.3f} < "
                f"min_valid_fraction={float(min_valid_fraction):.3f}). "
                "Dropped/failed runs bias the tail of flood-risk estimates. "
                "Investigate the failures, lower min_valid_fraction, or pass "
                "allow_low_valid_fraction=True to override. "
                f"Status histogram: {status_accounting['status_histogram']}."
            )

        # NOTE: exact percentile and CI calculations require an in-memory stack
        # of sample vectors. Very large ensembles on very fine meshes may exceed
        # available RAM. A future streaming quantile implementation would remove
        # this limitation.
        values_matrix = np.vstack(value_arrays)

        sample_weights_array = np.asarray(sample_weights, dtype=float)
        if np.all(sample_weights_array <= 0.0):
            raise ValueError("All sample weights are zero")

        return {
            "values_matrix": values_matrix,
            "sample_ids": sample_ids,
            "sample_weights": sample_weights_array,
            "points": point_metadata,
            "cell_metadata": cell_metadata,
            "n_samples_used": int(len(sample_ids)),
            "total_samples": int(total_samples),
            "valid_fraction": float(valid_fraction),
            "status_accounting": status_accounting,
        }

    @staticmethod
    def _normalize_breach_column_map(
        param_column_map: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Allow either target->column or column->target breach mappings."""
        normalized = dict(_DEFAULT_BREACH_COLUMN_MAP)
        if not param_column_map:
            return normalized

        for left, right in param_column_map.items():
            left_str = str(left).strip()
            right_str = str(right).strip()

            if left_str in _SUPPORTED_BREACH_TARGETS:
                normalized[left_str] = right_str
                continue

            if right_str in _SUPPORTED_BREACH_TARGETS:
                normalized[right_str] = left_str
                continue

            raise ValueError(
                "Breach mappings must use supported targets such as "
                "'initial_width', 'final_bottom_elev', 'method', "
                "'formation_time', etc."
            )

        return normalized

    @staticmethod
    def _coerce_boolean_like(value: Any) -> bool:
        """Coerce common numeric/string truthy values to bool."""
        if isinstance(value, bool):
            return value

        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y"}:
            return True
        if text in {"0", "false", "no", "n"}:
            return False

        return bool(float(value))

    @staticmethod
    def _coerce_breach_value(target: str, value: Any) -> Any:
        """Coerce param_row values onto expected breach scalar types."""
        if target in _BREACH_BOOL_FIELDS:
            return RasMonteCarlo._coerce_boolean_like(value)

        if target in _BREACH_INT_FIELDS:
            return int(float(value))

        return float(value)

    @staticmethod
    def _resolve_flow_multiplier_column(param_row: pd.Series) -> str:
        """Resolve the parameter column used by the flow-multiplier factory."""
        for column in _FLOW_MULTIPLIER_COLUMNS:
            if column in param_row.index:
                return column

        candidate_columns = [
            column
            for column in param_row.index
            if column not in {"sample_id", "absolute_perm_id"}
        ]
        if len(candidate_columns) == 1:
            return candidate_columns[0]

        raise ValueError(
            "Could not resolve a flow-multiplier parameter column. Add one "
            f"of {_FLOW_MULTIPLIER_COLUMNS} or pass only one parameter column."
        )

    @staticmethod
    def _compute_aep_interval_weights(
        aep_results: Dict[float, dict],
    ) -> Dict[float, float]:
        """
        Compute midpoint-based interval weights that partition annual
        exceedance-probability space.
        """
        if not isinstance(aep_results, dict) or not aep_results:
            raise ValueError("aep_results must be a non-empty dictionary")

        aeps = sorted(float(aep) for aep in aep_results.keys())
        if any(aep <= 0.0 or aep > 1.0 for aep in aeps):
            raise ValueError(
                "AEP keys must be fractional probabilities in (0, 1]"
            )
        if len(set(aeps)) != len(aeps):
            raise ValueError("AEP keys must be unique")

        descending = sorted(aeps, reverse=True)
        weights: Dict[float, float] = {}
        for index, aep in enumerate(descending):
            upper = 1.0 if index == 0 else 0.5 * (
                descending[index - 1] + aep
            )
            lower = 0.0 if index == len(descending) - 1 else 0.5 * (
                aep + descending[index + 1]
            )
            weights[aep] = float(max(upper - lower, 0.0))

        return weights

    @staticmethod
    @log_call
    def generate_samples(
        param_specs: Dict[str, dict],
        n_samples: int = 100,
        method: str = "truncated_normal",
        seed: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Generate Monte Carlo parameter samples.

        Args:
            param_specs: Mapping of parameter name to distribution spec. Each
                spec requires 'min' and 'max'; truncated-normal additionally
                uses 'mean' and 'std'. An optional 'kind' (or 'param_kind')
                hint such as ``"mannings_n"`` enables physical-range
                validation warnings (see H3).
            n_samples: Number of Monte Carlo samples to generate.
            method: 'truncated_normal', 'uniform', or 'latin_hypercube'.
            seed: Optional random seed for reproducible sampling.

        Returns:
            DataFrame with 'sample_id' and one column per parameter.

        Note:
            Parameters are sampled **independently** (LHS strata are
            independent across columns). There is no correlation structure
            between parameters. For spatially distributed roughness, varying
            every zone independently can OVERSTATE uncertainty because
            adjacent land-cover / calibration errors are correlated; use a
            single shared zone-level multiplier column to model correlated
            roughness.

            Reproducibility (H5): a single ``numpy.random.default_rng(seed)``
            Generator is threaded through every sampling path. The global
            numpy RNG state is never read or mutated.
        """
        n_samples = int(n_samples)
        if n_samples <= 0:
            raise ValueError("n_samples must be greater than zero")

        method = str(method).strip().lower()
        if method not in _SUPPORTED_METHODS:
            raise ValueError(
                f"Unsupported sampling method '{method}'. Supported methods: "
                f"{sorted(_SUPPORTED_METHODS)}"
            )

        validated_specs = RasMonteCarlo._validate_param_specs(param_specs)
        param_names = list(validated_specs.keys())

        # H5: one Generator threaded through all sampling paths. Never touch
        # the global np.random state.
        rng = np.random.default_rng(seed)

        sampled_columns: Dict[str, np.ndarray] = {}

        if method == "latin_hypercube":
            sampler = qmc.LatinHypercube(
                d=len(param_names),
                seed=rng,
            )
            lhs_unit = sampler.random(n=n_samples)

            for column_index, param_name in enumerate(param_names):
                sampled_columns[param_name] = (
                    RasMonteCarlo._transform_lhs_column(
                        lhs_unit[:, column_index],
                        validated_specs[param_name],
                    )
                )
        else:
            for param_name in param_names:
                spec = validated_specs[param_name]
                if method == "uniform":
                    sampled_columns[param_name] = (
                        RasMonteCarlo._sample_uniform(spec, n_samples, rng=rng)
                    )
                else:
                    sampled_columns[param_name] = (
                        RasMonteCarlo._sample_truncated_normal(
                            spec,
                            n_samples,
                            rng=rng,
                        )
                    )

        samples_df = pd.DataFrame(sampled_columns)
        samples_df.insert(0, "sample_id", np.arange(1, n_samples + 1))
        return samples_df

    @staticmethod
    @log_call
    def run_ensemble(
        template_plan: str,
        samples_df: pd.DataFrame,
        apply_fn: Callable[[Path, pd.Series, Any], None],
        suffix: str = "mc",
        max_workers: int = 2,
        num_cores: int = 2,
        max_plans_per_batch: int = 99,
        ras_object: Any = None,
        timeout_sec: Optional[int] = None,
    ) -> dict:
        """
        Run a Monte Carlo ensemble using RasPermutation as the execution engine.

        Args:
            template_plan: Source plan number used for cloning.
            samples_df: DataFrame produced by generate_samples() or equivalent.
            apply_fn: Callback that mutates one generated plan using one row.
            suffix: Folder suffix for generated batch projects.
            max_workers: Maximum parallel worker count for execution.
            num_cores: HEC-RAS core count per plan execution.
            max_plans_per_batch: Limit per batch project.
            ras_object: Optional project object for multi-project workflows.

        Returns:
            Dictionary containing the master log path, enriched results
            DataFrame, batch folders, and summary counts. ``status_histogram``
            (M1) reports counts for every status value
            (completed / completed_with_errors / failed / incomplete / ...),
            not just completed+failed.

        Bias note (C2): downstream statistics exclude
        ``completed_with_errors`` runs by default. To scan per-sample compute
        messages for instability after execution, use
        ``HdfResultsPlan.get_compute_messages(...)`` on each completed sample
        and flag ``UNSTABLE`` / ``NEGATIVE DEPTH`` / ``NOT CONVERGE`` lines per
        the Post-Execution Protocol; this module does not wire that scan into
        every sample automatically.
        """
        prepared_samples = RasMonteCarlo._prepare_samples_df(samples_df)

        plan_matrix = RasPermutation.generate_plans(
            template_plan=template_plan,
            parameters_df=prepared_samples,
            apply_fn=apply_fn,
            suffix=suffix,
            max_plans_per_batch=max_plans_per_batch,
            ras_object=ras_object,
        )

        results_df = RasPermutation.execute_and_summarize(
            plan_matrix=plan_matrix,
            max_workers=max_workers,
            num_cores=num_cores,
            ras_object=ras_object,
            timeout_sec=timeout_sec,
        )

        if "sample_id" in results_df.columns:
            results_df["sample_id"] = pd.to_numeric(
                results_df["sample_id"],
                errors="coerce",
            )
            results_df = results_df.sort_values(
                "sample_id",
                na_position="last",
            ).reset_index(drop=True)

        completed = 0
        failed = 0
        completed_with_errors = 0
        status_histogram: Dict[str, int] = {}
        if "status" in results_df.columns:
            normalized_status = (
                results_df["status"].astype(str).str.strip().str.lower()
            )
            status_histogram = {
                str(status_value): int(count)
                for status_value, count in
                normalized_status.value_counts().items()
            }
            completed = int(status_histogram.get("completed", 0))
            failed = int(status_histogram.get("failed", 0))
            completed_with_errors = int(
                status_histogram.get(_ERROR_STATUS, 0)
            )

        return {
            "master_log": Path(plan_matrix["master_log"]),
            "results_df": results_df,
            "batch_folders": [Path(folder) for folder in plan_matrix["batch_folders"]],
            "total_samples": int(len(prepared_samples)),
            "completed": completed,
            "completed_with_errors": completed_with_errors,
            "failed": failed,
            # M1: full histogram across all observed status values.
            "status_histogram": status_histogram,
        }

    @staticmethod
    @log_call
    def make_mannings_apply_fn(
        zone_column_map: Dict[str, str],
        path: str = "plaintext",
    ) -> Callable[[Path, pd.Series, Any], None]:
        """Factory: return an apply_fn that modifies Manning's n."""
        if not isinstance(zone_column_map, dict) or not zone_column_map:
            raise ValueError(
                "zone_column_map must be a non-empty dict of "
                "land-cover-class -> sample-column"
            )

        mode = str(path).strip().lower()
        if mode not in {"plaintext", "sidecar"}:
            raise ValueError("path must be either 'plaintext' or 'sidecar'")

        normalized_map = {
            str(zone_name): str(column_name)
            for zone_name, column_name in zone_column_map.items()
        }

        @log_call
        def apply_fn(
            plan_path: Path,
            param_row: pd.Series,
            ras_object: Any = None,
        ) -> None:
            from .geom import GeomLandCover
            from .hdf import HdfLandCover

            RasMonteCarlo._require_parameter_columns(
                param_row,
                list(normalized_map.values()),
                context="Manning's-n apply_fn",
            )

            dependencies = RasMonteCarlo._resolve_plan_dependencies(
                Path(plan_path),
                ras_object=ras_object,
            )

            if mode == "plaintext":
                geom_path = dependencies["geom_path"]
                if geom_path is None or not geom_path.exists():
                    raise FileNotFoundError(
                        f"Could not resolve geometry file for {plan_path}"
                    )

                mannings_df = GeomLandCover.get_base_mannings_n(geom_path).copy()
                if mannings_df.empty:
                    raise ValueError(
                        f"No base Manning's-n table found in {geom_path}"
                    )

                for zone_name, column_name in normalized_map.items():
                    mask = (
                        mannings_df["Land Cover Name"].astype(str)
                        == str(zone_name)
                    )
                    if not mask.any():
                        raise ValueError(
                            f"Land cover class '{zone_name}' was not found in "
                            f"{geom_path.name}"
                        )
                    mannings_df.loc[
                        mask,
                        "Base Mannings n Value",
                    ] = float(param_row[column_name])

                GeomLandCover.set_base_mannings_n(geom_path, mannings_df)
                return

            geom_hdf_path = dependencies["geom_hdf_path"]
            if geom_hdf_path is None or not geom_hdf_path.exists():
                raise FileNotFoundError(
                    f"Could not resolve geometry HDF for {plan_path}"
                )

            landcover_hdf = HdfLandCover.get_landcover_association(
                geom_hdf_path,
                ras_object=ras_object,
            )
            if landcover_hdf is None or not Path(landcover_hdf).exists():
                raise FileNotFoundError(
                    f"Could not resolve land-cover sidecar for {geom_hdf_path}"
                )

            class_mapping = {
                zone_name: float(param_row[column_name])
                for zone_name, column_name in normalized_map.items()
            }
            HdfLandCover.set_landcover_raster_map(
                landcover_hdf,
                class_mapping,
                ras_object=ras_object,
            )

        return apply_fn

    @staticmethod
    @log_call
    def make_breach_apply_fn(
        structure_name: str,
        param_column_map: Optional[Dict[str, str]] = None,
    ) -> Callable[[Path, pd.Series, Any], None]:
        """Factory: return an apply_fn that modifies breach parameters."""
        if not isinstance(structure_name, str) or not structure_name.strip():
            raise ValueError("structure_name must be a non-empty string")

        normalized_map = RasMonteCarlo._normalize_breach_column_map(
            param_column_map
        )

        @log_call
        def apply_fn(
            plan_path: Path,
            param_row: pd.Series,
            ras_object: Any = None,
        ) -> None:
            from .RasBreach import RasBreach

            geom_values = None
            update_kwargs: Dict[str, Any] = {}

            for target, column_name in normalized_map.items():
                if column_name not in param_row.index:
                    continue
                if pd.isna(param_row[column_name]):
                    continue

                coerced_value = RasMonteCarlo._coerce_breach_value(
                    target,
                    param_row[column_name],
                )

                if target in _BREACH_GEOM_INDEX:
                    if geom_values is None:
                        current_block = RasBreach.read_breach_block(
                            plan_path,
                            structure_name,
                            ras_object=ras_object,
                        )
                        raw_geom = current_block["values"].get("Breach Geom", "")
                        geom_values = [
                            value.strip()
                            for value in str(raw_geom).split(",")
                        ]
                        if len(geom_values) < 10:
                            raise ValueError(
                                f"Breach Geom for '{structure_name}' has "
                                f"{len(geom_values)} fields; expected 10"
                            )

                    geom_values[_BREACH_GEOM_INDEX[target]] = coerced_value
                else:
                    update_kwargs[target] = coerced_value

            if geom_values is not None:
                update_kwargs["geom_values"] = geom_values

            if not update_kwargs:
                raise ValueError(
                    "No breach parameter columns from the sample row matched "
                    "the configured mapping"
                )

            RasBreach.update_breach_block(
                plan_path,
                structure_name,
                ras_object=ras_object,
                **update_kwargs,
            )

        return apply_fn

    @staticmethod
    def _resolve_boundary_location_lines(
        unsteady_path: Path,
        target_names: List[str],
        ras_object: Any = None,
        allow_multiple_matches: bool = False,
    ) -> List[str]:
        """Resolve target boundary names to exact ``Boundary Location=`` lines.

        H1: matches against ``ras.boundaries_df`` using exact field equality on
        the river/reach, river station, 2D area, and BC line name fields. Each
        requested name must match exactly one boundary in the target unsteady
        file unless ``allow_multiple_matches=True`` is set for that name.

        Returns the list of full comma-joined boundary-location values (the
        text following ``Boundary Location=`` in the .u## file). These exact
        strings drive an unambiguous downstream update.
        """
        unsteady_path = Path(unsteady_path)

        # Read the actual boundary-location values present in this unsteady
        # file so the returned strings are exact line content.
        file_locations: List[str] = []
        with open(
            unsteady_path, "r", encoding="utf-8", errors="ignore"
        ) as handle:
            for line in handle:
                if line.startswith("Boundary Location="):
                    file_locations.append(line.split("=", 1)[1].strip())

        if not file_locations:
            raise ValueError(
                f"No 'Boundary Location=' lines found in {unsteady_path.name}"
            )

        # Candidate identity fields from boundaries_df, when available.
        bdf = getattr(ras_object, "boundaries_df", None) if ras_object else None

        def _matches(location_value: str, name: str) -> bool:
            fields = [f.strip() for f in location_value.split(",")]
            # Exact match on any non-empty identity field.
            identity_fields = []
            if len(fields) > 0:
                identity_fields.append(fields[0])  # river_reach_name
            if len(fields) > 1:
                identity_fields.append(fields[1])  # river_station
            if len(fields) > 5:
                identity_fields.append(fields[5])  # area_2d
            if len(fields) > 7:
                identity_fields.append(fields[7])  # bc_line_name
            return any(
                field and field == name.strip() for field in identity_fields
            )

        resolved: List[str] = []
        for name in target_names:
            name = str(name).strip()
            if not name:
                raise ValueError("Boundary names must be non-empty strings")

            # Cross-check against boundaries_df for early, clear errors.
            if isinstance(bdf, pd.DataFrame) and not bdf.empty:
                id_cols = [
                    c
                    for c in (
                        "river_reach_name",
                        "river_station",
                        "area_2d",
                        "bc_line_name",
                    )
                    if c in bdf.columns
                ]
                if id_cols:
                    mask = pd.Series(False, index=bdf.index)
                    for col in id_cols:
                        mask = mask | (
                            bdf[col].astype(str).str.strip() == name
                        )
                    if not mask.any():
                        raise ValueError(
                            f"Boundary '{name}' was not found in "
                            f"ras.boundaries_df (exact match on "
                            f"{id_cols})."
                        )

            matched = [loc for loc in file_locations if _matches(loc, name)]
            if not matched:
                raise ValueError(
                    f"Boundary '{name}' was not found in "
                    f"{unsteady_path.name} via exact field matching."
                )
            if len(matched) > 1 and not allow_multiple_matches:
                raise ValueError(
                    f"Boundary '{name}' matched {len(matched)} boundaries in "
                    f"{unsteady_path.name} ({matched}). Refusing ambiguous "
                    "scaling. Pass allow_multiple_matches=True to scale all "
                    "matches, or use a more specific identifier."
                )
            resolved.extend(matched)

        return resolved

    @staticmethod
    @log_call
    def make_flow_multiplier_apply_fn(
        bc_name,
        allow_multiple_matches: bool = False,
    ) -> Callable[[Path, pd.Series, Any], None]:
        """Factory: return an apply_fn that scales a UNIFORM flow multiplier.

        H2 SEMANTICS BANNER: this writes ``Flow Hydrograph QMult=``, a UNIFORM
        ordinate multiplier. It scales the inflow PEAK and VOLUME together
        while preserving the hydrograph timing and shape. It is NOT a
        flow-frequency / AEP sample, NOT a peak-only perturbation, and NOT a
        volume-only perturbation. Do not present QMult sweeps as generic
        "flow uncertainty" or as discharge-frequency-curve uncertainty.

        H1: ``bc_name`` may be a single boundary identifier or a list of
        identifiers. Each is resolved against ``ras.boundaries_df`` with exact
        field matching (river/reach, river station, 2D area, BC line name) and
        must match exactly one boundary unless ``allow_multiple_matches=True``.

        Args:
            bc_name: one boundary identifier (str) or several (list of str).
            allow_multiple_matches: permit a single name to scale multiple
                matching boundaries (opt-in).
        """
        if isinstance(bc_name, (list, tuple, set)):
            target_names = [str(n).strip() for n in bc_name]
        else:
            target_names = [str(bc_name).strip()]

        if not target_names or any(not n for n in target_names):
            raise ValueError(
                "bc_name must be a non-empty string or list of non-empty "
                "strings"
            )

        @log_call
        def apply_fn(
            plan_path: Path,
            param_row: pd.Series,
            ras_object: Any = None,
        ) -> None:
            from .RasUnsteady import RasUnsteady

            multiplier_column = RasMonteCarlo._resolve_flow_multiplier_column(
                param_row
            )
            multiplier = float(param_row[multiplier_column])

            dependencies = RasMonteCarlo._resolve_plan_dependencies(
                Path(plan_path),
                ras_object=ras_object,
            )
            unsteady_path = dependencies["unsteady_path"]
            if unsteady_path is None or not unsteady_path.exists():
                raise FileNotFoundError(
                    f"Could not resolve unsteady file for {plan_path}"
                )

            # H1: resolve each requested boundary to an exact, unambiguous
            # Boundary Location= line before updating.
            location_strings = RasMonteCarlo._resolve_boundary_location_lines(
                unsteady_path,
                target_names,
                ras_object=ras_object,
                allow_multiple_matches=allow_multiple_matches,
            )

            for location_string in location_strings:
                updated = RasUnsteady.update_flow_multiplier_by_station(
                    unsteady_path,
                    river_station=location_string,
                    new_multiplier=multiplier,
                    ras_object=ras_object,
                )
                if not updated:
                    raise ValueError(
                        f"Failed to update QMult for boundary "
                        f"'{location_string}' in {unsteady_path.name}"
                    )

        return apply_fn

    @staticmethod
    @log_call
    def make_composite_apply_fn(
        *fns: Callable[[Path, pd.Series, Any], None],
    ) -> Callable[[Path, pd.Series, Any], None]:
        """Chain multiple apply_fns into one composite callback."""
        if not fns:
            raise ValueError("At least one apply_fn is required")

        for fn in fns:
            if not callable(fn):
                raise TypeError("All composite apply_fn arguments must be callable")

        @log_call
        def combined(
            plan_path: Path,
            param_row: pd.Series,
            ras_object: Any = None,
        ) -> None:
            for fn in fns:
                fn(plan_path, param_row, ras_object)

        return combined

    @staticmethod
    @log_call
    def exceedance_probabilities(
        ensemble_result: dict,
        variable: str = "wse",
        percentiles: Optional[List[float]] = None,
        points_of_interest: Optional[List[tuple]] = None,
        weights: Optional[Dict[int, float]] = None,
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
    ) -> dict:
        """
        Compute ensemble percentiles and moments for any supported variable.

        - Point mode uses HdfResultsQuery.query_points(..., time_index='max')
          for query-supported variables and a depth*velocity timeseries path
          for `dxv`.
        - Full-domain WSE keeps the existing fast path via get_mesh_max_ws().
        - Full-domain depth/velocity/custom cell variables use
          get_mesh_cells_timeseries(...).max(axis=0), with a query-at-cell-
          centers fallback for query-supported variables.
        - If weights are provided, percentiles, mean, and std are weighted by
          sample_id.

        Percentile convention: the returned percentile values are
        non-exceedance quantiles (the value not exceeded N% of the time across
        samples). The 90th percentile is the value exceeded only 10% of the
        time -- it is NOT a 90% chance of exceedance.

        Bias controls (C2):
            include_error_runs: admit ``completed_with_errors`` runs (default
                excluded).
            min_valid_fraction: minimum n_used/total ratio (default 0.95).
            allow_low_valid_fraction: override the min_valid_fraction guard.
        """
        if percentiles is None:
            percentiles = [99, 90, 50, 10, 1]
        normalized_percentiles = RasMonteCarlo._normalize_percentiles(
            list(percentiles)
        )

        collected = RasMonteCarlo._collect_ensemble_values(
            ensemble_result=ensemble_result,
            variable=variable,
            points_of_interest=points_of_interest,
            weights=weights,
            ras_object=ras_object,
            include_error_runs=include_error_runs,
            min_valid_fraction=min_valid_fraction,
            allow_low_valid_fraction=allow_low_valid_fraction,
        )

        counts, weight_sums, mean, std, percentile_map = (
            RasMonteCarlo._summarize_matrix(
                collected["values_matrix"],
                normalized_percentiles,
                weights=(
                    collected["sample_weights"] if weights is not None else None
                ),
            )
        )

        return {
            "variable": RasMonteCarlo._normalize_variable_key(variable),
            "percentiles": percentile_map,
            "mean": mean,
            "std": std,
            "n_samples": counts.astype(int),
            "weight_sums": weight_sums,
            "n_samples_used": collected["n_samples_used"],
            "sample_ids_used": collected["sample_ids"],
            "weights_used": (
                collected["sample_weights"] if weights is not None else None
            ),
            "points": collected["points"],
            "cell_metadata": collected["cell_metadata"],
            "status_accounting": collected["status_accounting"],
        }

    @staticmethod
    @log_call
    def risk_at_points(
        ensemble_result: dict,
        points: List[tuple],
        variable: str = "wse",
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
    ) -> pd.DataFrame:
        """
        Compute point-level ensemble risk statistics for any supported variable.

        Returns:
            DataFrame with one row per point and columns including:
            point_index, x, y, n_samples, mean, std, min, max,
            p01, p10, p50, p90, p99. A ``status_accounting`` dict is attached
            via ``df.attrs['status_accounting']`` (C2).

        Bias controls (C2): see ``include_error_runs``, ``min_valid_fraction``,
        and ``allow_low_valid_fraction`` on ``exceedance_probabilities``.
        """
        collected = RasMonteCarlo._collect_ensemble_values(
            ensemble_result=ensemble_result,
            variable=variable,
            points_of_interest=points,
            ras_object=ras_object,
            include_error_runs=include_error_runs,
            min_valid_fraction=min_valid_fraction,
            allow_low_valid_fraction=allow_low_valid_fraction,
        )

        points_df = collected["points"]
        value_matrix = collected["values_matrix"]
        counts, _, mean, std, percentile_map = RasMonteCarlo._summarize_matrix(
            value_matrix,
            _POINT_STAT_PERCENTILES,
        )

        summary_df = points_df.copy()
        summary_df["n_samples"] = counts.astype(int)
        summary_df["mean"] = mean
        summary_df["std"] = std
        summary_df["min"] = RasMonteCarlo._safe_matrix_reduction(
            value_matrix,
            "min",
        )
        summary_df["max"] = RasMonteCarlo._safe_matrix_reduction(
            value_matrix,
            "max",
        )
        summary_df["p01"] = percentile_map[1.0]
        summary_df["p10"] = percentile_map[10.0]
        summary_df["p50"] = percentile_map[50.0]
        summary_df["p90"] = percentile_map[90.0]
        summary_df["p99"] = percentile_map[99.0]

        raw_rows: List[pd.DataFrame] = []
        for row_index, sample_id in enumerate(collected["sample_ids"]):
            sample_points = points_df.copy()
            sample_points.insert(0, "sample_id", int(sample_id))
            sample_points["value"] = value_matrix[row_index]
            raw_rows.append(
                sample_points[
                    ["sample_id", "point_index", "x", "y", "value"]
                ]
            )

        summary_df.attrs["raw_point_values"] = pd.concat(
            raw_rows,
            ignore_index=True,
        )
        summary_df.attrs["status_accounting"] = collected["status_accounting"]
        summary_df.attrs["n_samples_used"] = collected["n_samples_used"]

        return summary_df[
            [
                "point_index",
                "x",
                "y",
                "n_samples",
                "mean",
                "std",
                "min",
                "max",
                "p01",
                "p10",
                "p50",
                "p90",
                "p99",
            ]
        ]

    @staticmethod
    @log_call
    def confidence_intervals(
        ensemble_result: dict,
        variable: str = "wse",
        confidence_level: float = 0.90,
        points_of_interest: Optional[List[tuple]] = None,
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
        min_samples_warn: int = 30,
    ) -> dict:
        """
        Compute a central empirical PREDICTION (percentile) interval.

        M3 NOTE: despite the historical name, this returns a
        **prediction/percentile interval on the variable** (the central
        ``confidence_level`` band of the ensemble distribution), NOT a
        confidence interval on a statistic. A 90% interval returns the 5th,
        50th, and 95th empirical percentiles of the realized variable.

        The result includes ``interval_type='prediction'`` and the
        ``n_samples_used`` count. A warning is emitted when ``n_samples_used``
        is below ``min_samples_warn`` because empirical tail percentiles are
        unreliable at small N.

        Bias controls (C2): see ``include_error_runs``, ``min_valid_fraction``,
        and ``allow_low_valid_fraction``.
        """
        confidence_level = RasMonteCarlo._normalize_confidence_level(
            confidence_level
        )
        alpha = (1.0 - confidence_level) / 2.0
        lower_percentile = 100.0 * alpha
        upper_percentile = 100.0 * (1.0 - alpha)

        collected = RasMonteCarlo._collect_ensemble_values(
            ensemble_result=ensemble_result,
            variable=variable,
            points_of_interest=points_of_interest,
            ras_object=ras_object,
            include_error_runs=include_error_runs,
            min_valid_fraction=min_valid_fraction,
            allow_low_valid_fraction=allow_low_valid_fraction,
        )

        n_used = collected["n_samples_used"]
        if n_used < int(min_samples_warn):
            logger.warning(
                "Prediction interval computed from only %d sample(s) "
                "(< %d). Empirical %.0f%% tail percentiles are unreliable at "
                "this sample size; widen the ensemble before relying on the "
                "band.",
                n_used,
                int(min_samples_warn),
                confidence_level * 100.0,
            )

        _, _, _, _, percentile_map = RasMonteCarlo._summarize_matrix(
            collected["values_matrix"],
            [lower_percentile, 50.0, upper_percentile],
        )

        return {
            "variable": RasMonteCarlo._normalize_variable_key(variable),
            "interval_type": "prediction",
            "confidence_level": confidence_level,
            "lower_percentile": lower_percentile,
            "upper_percentile": upper_percentile,
            "lower": percentile_map[lower_percentile],
            "median": percentile_map[50.0],
            "upper": percentile_map[upper_percentile],
            "n_samples_used": collected["n_samples_used"],
            "sample_ids_used": collected["sample_ids"],
            "points": collected["points"],
            "cell_metadata": collected["cell_metadata"],
            "status_accounting": collected["status_accounting"],
        }

    @staticmethod
    @log_call
    def prediction_intervals(
        ensemble_result: dict,
        variable: str = "wse",
        confidence_level: float = 0.90,
        points_of_interest: Optional[List[tuple]] = None,
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
        min_samples_warn: int = 30,
    ) -> dict:
        """Alias for :meth:`confidence_intervals` with accurate naming (M3).

        Returns a central empirical prediction/percentile interval on the
        variable. See :meth:`confidence_intervals` for details.
        """
        return RasMonteCarlo.confidence_intervals(
            ensemble_result=ensemble_result,
            variable=variable,
            confidence_level=confidence_level,
            points_of_interest=points_of_interest,
            ras_object=ras_object,
            include_error_runs=include_error_runs,
            min_valid_fraction=min_valid_fraction,
            allow_low_valid_fraction=allow_low_valid_fraction,
            min_samples_warn=min_samples_warn,
        )

    @staticmethod
    @log_call
    def aep_weighted_exceedance(
        aep_results: Dict[float, dict],
        variable: str = "depth",
        threshold: float = 1.0,
        points_of_interest: Optional[List[tuple]] = None,
        ras_object: Any = None,
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = False,
    ) -> dict:
        """
        Compute P(variable > threshold) weighted by AEP interval.

        Each AEP ensemble contributes its within-ensemble exceedance frequency,
        then midpoint-based interval weights partition annual exceedance-
        probability space and are used to aggregate the final probability map.

        WARNING (H4 -- heuristic, not a defensible annual probability): the
        midpoint-interval weighting is an ad-hoc rectangle-rule approximation
        of expected exceedance over the SUPPLIED AEP set. The within-ensemble
        exceedance is a CONDITIONAL frequency given each AEP event, not an
        annual exceedance probability. The open tails are absorbed by the
        most-frequent (up to AEP=1.0) and rarest (down to AEP=0.0) supplied
        events; events beyond the sampled AEP range are ignored. This is NOT a
        substitute for HEC-FDA / HEC Quantile Map Calculator hazard-curve
        integration, and it does not separate aleatory (event AEP) from
        epistemic (parameter) uncertainty. Treat the output as a heuristic
        blended exceedance map, not a regulatory product.

        Bias controls (C2) are applied to each per-AEP ensemble.
        """
        interval_weights = RasMonteCarlo._compute_aep_interval_weights(
            aep_results
        )

        numerator = None
        denominator = None
        point_metadata = None
        cell_metadata = None
        scenario_probabilities: Dict[float, np.ndarray] = {}

        for aep in sorted(interval_weights.keys(), reverse=True):
            collected = RasMonteCarlo._collect_ensemble_values(
                ensemble_result=aep_results[aep],
                variable=variable,
                points_of_interest=points_of_interest,
                ras_object=ras_object,
                include_error_runs=include_error_runs,
                min_valid_fraction=min_valid_fraction,
                allow_low_valid_fraction=allow_low_valid_fraction,
            )

            if point_metadata is None and collected["points"] is not None:
                point_metadata = collected["points"]
            elif (
                point_metadata is not None
                and collected["points"] is not None
            ):
                RasMonteCarlo._validate_alignment(
                    point_metadata,
                    collected["points"],
                    "point ordering",
                )

            if cell_metadata is None and collected["cell_metadata"] is not None:
                cell_metadata = collected["cell_metadata"]
            elif (
                cell_metadata is not None
                and collected["cell_metadata"] is not None
            ):
                RasMonteCarlo._validate_alignment(
                    cell_metadata,
                    collected["cell_metadata"],
                    "mesh cell ordering",
                )

            exceedance = RasMonteCarlo._column_exceedance_frequency(
                collected["values_matrix"],
                threshold=float(threshold),
            )
            scenario_probabilities[aep] = exceedance

            if numerator is None:
                numerator = np.zeros_like(exceedance, dtype=float)
                denominator = np.zeros_like(exceedance, dtype=float)

            finite = np.isfinite(exceedance)
            numerator[finite] += interval_weights[aep] * exceedance[finite]
            denominator[finite] += interval_weights[aep]

        probability_map = np.divide(
            numerator,
            denominator,
            out=np.full_like(numerator, np.nan, dtype=float),
            where=denominator > 0.0,
        )

        return {
            "variable": RasMonteCarlo._normalize_variable_key(variable),
            "threshold": float(threshold),
            "probability_map": probability_map,
            "aep_interval_weights": interval_weights,
            "scenario_probabilities": scenario_probabilities,
            "points": point_metadata,
            "cell_metadata": cell_metadata,
        }

    @staticmethod
    @log_call
    def convergence(
        ensemble_result: dict,
        variable: str = "wse",
        statistic: str = "p90",
        points_of_interest: Optional[List[tuple]] = None,
        ras_object: Any = None,
        window: int = 5,
        tolerance: float = 0.02,
        aggregate: str = "mean",
        include_error_runs: bool = False,
        min_valid_fraction: float = _DEFAULT_MIN_VALID_FRACTION,
        allow_low_valid_fraction: bool = True,
    ) -> dict:
        """Assess Monte Carlo convergence of a running statistic vs sample N.

        C3: computes a running statistic (mean / std / a percentile such as
        ``"p90"``) over the first ``k`` samples for ``k = 1..N``, aggregated to
        a single scalar per ``k`` (so it works for both point and full-domain
        variables), and reports whether it has stabilized.

        Stabilization rule: the maximum relative change of the running
        statistic across the last ``window`` samples is below ``tolerance``
        (default 2%). Relative change is ``|x_k - x_{k-1}| / |x_{k-1}|``.

        Args:
            statistic: ``"mean"``, ``"std"``, or ``"pNN"`` (e.g. ``"p90"``).
            window: number of trailing samples used for the stabilization test.
            tolerance: relative-change threshold for stabilization.
            aggregate: how to reduce a per-cell/per-point statistic to one
                scalar per sample count (``"mean"``, ``"median"``, ``"max"``).
            allow_low_valid_fraction: defaults True here so convergence can be
                inspected even on partially failed ensembles.

        Returns:
            dict with ``sample_counts`` (1..N), ``running_statistic`` (array),
            ``stabilized`` (bool), ``final_relative_change`` (float),
            ``window``, ``tolerance``, ``statistic``, ``n_samples_used``.
        """
        statistic_key = str(statistic).strip().lower()
        window = int(window)
        if window < 2:
            raise ValueError("window must be >= 2")
        tolerance = float(tolerance)
        if tolerance <= 0.0:
            raise ValueError("tolerance must be > 0")

        aggregate_key = str(aggregate).strip().lower()
        if aggregate_key not in {"mean", "median", "max"}:
            raise ValueError("aggregate must be 'mean', 'median', or 'max'")

        collected = RasMonteCarlo._collect_ensemble_values(
            ensemble_result=ensemble_result,
            variable=variable,
            points_of_interest=points_of_interest,
            ras_object=ras_object,
            include_error_runs=include_error_runs,
            min_valid_fraction=min_valid_fraction,
            allow_low_valid_fraction=allow_low_valid_fraction,
        )

        values_matrix = collected["values_matrix"]
        return RasMonteCarlo._convergence_from_matrix(
            values_matrix,
            statistic_key=statistic_key,
            window=window,
            tolerance=tolerance,
            aggregate_key=aggregate_key,
            n_samples_used=collected["n_samples_used"],
        )

    @staticmethod
    def _convergence_from_matrix(
        values_matrix: np.ndarray,
        statistic_key: str,
        window: int,
        tolerance: float,
        aggregate_key: str,
        n_samples_used: int,
    ) -> dict:
        """Core convergence computation from a (samples x columns) matrix.

        Separated for direct unit testing without HDF extraction.
        """
        values_matrix = np.asarray(values_matrix, dtype=float)
        if values_matrix.ndim != 2:
            raise ValueError("values_matrix must be 2D (samples x columns)")

        n_samples = values_matrix.shape[0]

        # Parse the requested statistic.
        percentile = None
        if statistic_key in {"mean", "std"}:
            reducer = statistic_key
        elif statistic_key.startswith("p"):
            try:
                percentile = float(statistic_key[1:])
            except ValueError as exc:
                raise ValueError(
                    f"Invalid statistic '{statistic_key}'"
                ) from exc
            if percentile < 0.0 or percentile > 100.0:
                raise ValueError("percentile statistic must be in [0, 100]")
            reducer = "percentile"
        else:
            raise ValueError(
                "statistic must be 'mean', 'std', or 'pNN' (e.g. 'p90')"
            )

        def _scalar_aggregate(per_column: np.ndarray) -> float:
            finite = per_column[np.isfinite(per_column)]
            if finite.size == 0:
                return float("nan")
            if aggregate_key == "mean":
                return float(np.mean(finite))
            if aggregate_key == "median":
                return float(np.median(finite))
            return float(np.max(finite))

        running = np.full(n_samples, np.nan, dtype=float)
        for k in range(1, n_samples + 1):
            subset = values_matrix[:k, :]
            if reducer == "mean":
                per_column = RasMonteCarlo._safe_matrix_reduction_mean(subset)
            elif reducer == "std":
                per_column = RasMonteCarlo._safe_matrix_reduction_std(subset)
            else:
                per_column = RasMonteCarlo._safe_matrix_percentile(
                    subset, percentile
                )
            running[k - 1] = _scalar_aggregate(per_column)

        # Stabilization: max relative change over the trailing window.
        stabilized = False
        final_relative_change = float("nan")
        if n_samples >= window:
            tail = running[-window:]
            rel_changes = []
            for idx in range(1, len(tail)):
                prev = tail[idx - 1]
                curr = tail[idx]
                if not np.isfinite(prev) or not np.isfinite(curr):
                    rel_changes.append(np.nan)
                    continue
                denom = abs(prev)
                if denom == 0.0:
                    rel_changes.append(0.0 if curr == prev else np.inf)
                else:
                    rel_changes.append(abs(curr - prev) / denom)
            rel_changes_arr = np.asarray(rel_changes, dtype=float)
            finite_changes = rel_changes_arr[np.isfinite(rel_changes_arr)]
            if finite_changes.size:
                final_relative_change = float(np.max(finite_changes))
                stabilized = bool(final_relative_change < tolerance)

        return {
            "statistic": statistic_key,
            "aggregate": aggregate_key,
            "sample_counts": np.arange(1, n_samples + 1),
            "running_statistic": running,
            "stabilized": stabilized,
            "final_relative_change": final_relative_change,
            "window": window,
            "tolerance": tolerance,
            "n_samples_used": int(n_samples_used),
        }

    @staticmethod
    def _safe_matrix_reduction_mean(values: np.ndarray) -> np.ndarray:
        """Per-column mean over finite entries (NaN-safe)."""
        result = np.full(values.shape[1], np.nan, dtype=float)
        for column_index in range(values.shape[1]):
            column = values[:, column_index]
            finite = column[np.isfinite(column)]
            if finite.size:
                result[column_index] = float(np.mean(finite))
        return result

    @staticmethod
    def _safe_matrix_reduction_std(values: np.ndarray) -> np.ndarray:
        """Per-column population std over finite entries (NaN-safe)."""
        result = np.full(values.shape[1], np.nan, dtype=float)
        for column_index in range(values.shape[1]):
            column = values[:, column_index]
            finite = column[np.isfinite(column)]
            if finite.size:
                result[column_index] = float(np.std(finite, ddof=0))
        return result
