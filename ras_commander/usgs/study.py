"""
Primitive-first USGS observation helpers plus example-only workflow wrappers.

This module now has three layers:
- ``UsgsObservations`` exposes reusable data primitives for metadata, time
  series retrieval, normalization, and gap analysis.
- ``UsgsDrainageAreaComparison`` exposes the composable area-comparison helper.
- ``UsgsGaugeStudy``, ``UsgsModelPrepValidation``, and
  ``UsgsModelPrepReport`` remain here only as workflow scaffolding for example
  notebooks and should not be treated as the main package API.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Union
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .core import RasUsgsCore
from .time_series import TimeSeriesProcessor


logger = get_logger(__name__)


class UsgsDrainageAreaComparison:
    """
    Static helpers for comparing drainage-area estimates from multiple sources.

    The comparison can use any subset of gauge, official basin, TauDEM, and
    model areas. The first available value in the default reference priority is
    used unless a specific reference is requested.
    """

    AREA_LABELS = {
        "gauge_area_sqmi": "Gauge",
        "official_basin_area_sqmi": "Official Basin",
        "taudem_area_sqmi": "TauDEM",
        "model_area_sqmi": "Model",
    }
    REFERENCE_PRIORITY = (
        "gauge_area_sqmi",
        "official_basin_area_sqmi",
        "taudem_area_sqmi",
        "model_area_sqmi",
    )

    @staticmethod
    def _coerce_area(value: Optional[Union[int, float]]) -> Optional[float]:
        """Return a clean float or None for missing drainage-area inputs."""
        if value is None:
            return None
        if pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _agreement_status(max_abs_percent_difference: Optional[float]) -> str:
        """Classify area agreement for quick review."""
        if max_abs_percent_difference is None:
            return "insufficient_comparison_data"
        if max_abs_percent_difference <= 5.0:
            return "close"
        if max_abs_percent_difference <= 10.0:
            return "moderate"
        return "review"

    @staticmethod
    @log_call
    def compare_areas(
        gauge_area_sqmi: Optional[Union[int, float]] = None,
        official_basin_area_sqmi: Optional[Union[int, float]] = None,
        taudem_area_sqmi: Optional[Union[int, float]] = None,
        model_area_sqmi: Optional[Union[int, float]] = None,
        reference_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compare some subset of gauge, official basin, TauDEM, and model areas.

        Parameters
        ----------
        gauge_area_sqmi, official_basin_area_sqmi, taudem_area_sqmi, model_area_sqmi
            Optional drainage-area inputs in square miles.
        reference_key : str, optional
            Override the default reference priority. Must be one of the provided
            keys if specified.

        Returns
        -------
        dict
            Structured comparison report with provided areas, a reference
            baseline, per-source deltas, and pairwise differences.
        """
        raw_inputs = {
            "gauge_area_sqmi": gauge_area_sqmi,
            "official_basin_area_sqmi": official_basin_area_sqmi,
            "taudem_area_sqmi": taudem_area_sqmi,
            "model_area_sqmi": model_area_sqmi,
        }
        provided = {
            key: value
            for key, value in (
                (name, UsgsDrainageAreaComparison._coerce_area(area))
                for name, area in raw_inputs.items()
            )
            if value is not None
        }

        if not provided:
            return {
                "provided_area_count": 0,
                "areas_sqmi": {},
                "reference_key": None,
                "reference_label": None,
                "reference_area_sqmi": None,
                "comparisons": {},
                "pairwise_differences": [],
                "max_abs_percent_difference": None,
                "agreement_status": "no_area_inputs",
            }

        if reference_key not in provided:
            reference_key = next(
                (
                    key for key in UsgsDrainageAreaComparison.REFERENCE_PRIORITY
                    if key in provided
                ),
                None,
            )

        reference_area = provided[reference_key]
        comparisons = {}
        pairwise_differences = []
        percent_differences = []

        for key, area in provided.items():
            difference_sqmi = area - reference_area
            percent_difference = None
            if key != reference_key and reference_area not in (None, 0.0):
                percent_difference = (difference_sqmi / reference_area) * 100.0
                percent_differences.append(abs(percent_difference))

            comparisons[key] = {
                "label": UsgsDrainageAreaComparison.AREA_LABELS[key],
                "area_sqmi": area,
                "difference_from_reference_sqmi": difference_sqmi,
                "difference_from_reference_percent": percent_difference,
                "is_reference": key == reference_key,
            }

        for left_key, right_key in combinations(provided.keys(), 2):
            left_area = provided[left_key]
            right_area = provided[right_key]
            difference_sqmi = right_area - left_area
            percent_difference = None
            if left_area not in (None, 0.0):
                percent_difference = (difference_sqmi / left_area) * 100.0
                percent_differences.append(abs(percent_difference))

            pairwise_differences.append({
                "left_key": left_key,
                "left_label": UsgsDrainageAreaComparison.AREA_LABELS[left_key],
                "left_area_sqmi": left_area,
                "right_key": right_key,
                "right_label": UsgsDrainageAreaComparison.AREA_LABELS[right_key],
                "right_area_sqmi": right_area,
                "difference_sqmi": difference_sqmi,
                "difference_percent": percent_difference,
            })

        max_abs_percent_difference = (
            max(percent_differences) if percent_differences else None
        )

        return {
            "provided_area_count": len(provided),
            "areas_sqmi": provided,
            "reference_key": reference_key,
            "reference_label": UsgsDrainageAreaComparison.AREA_LABELS[reference_key],
            "reference_area_sqmi": reference_area,
            "comparisons": comparisons,
            "pairwise_differences": pairwise_differences,
            "max_abs_percent_difference": max_abs_percent_difference,
            "agreement_status": UsgsDrainageAreaComparison._agreement_status(
                max_abs_percent_difference
            ),
        }


class UsgsObservations:
    """
    Primitive-first USGS observation helpers for composable gauge workflows.

    These methods intentionally work in memory and do not assume a workspace
    layout. ``UsgsGaugeStudy`` uses them when callers want a packaged study.
    """

    @staticmethod
    def resolve_services(
        services: Optional[Mapping[str, Callable[..., Any]]] = None
    ) -> Dict[str, Callable[..., Any]]:
        """Return the effective service boundary map for observation retrieval."""
        return UsgsGaugeStudy._resolve_services(services)

    @staticmethod
    @log_call
    def get_gauge_metadata(
        site_id: str,
        services: Optional[Mapping[str, Callable[..., Any]]] = None,
    ) -> Dict[str, Any]:
        """Return metadata for a USGS gauge."""
        resolved_services = UsgsObservations.resolve_services(services)
        return dict(resolved_services["metadata"](site_id))

    @staticmethod
    @log_call
    def get_peak_flow_data(
        site_id: str,
        start_datetime: Optional[Union[str, datetime]] = None,
        end_datetime: Optional[Union[str, datetime]] = None,
        urlopen_func: Callable[..., Any] = urlopen,
    ) -> pd.DataFrame:
        """Return normalized USGS peak-flow observations."""
        return UsgsGaugeStudy.retrieve_peak_flow_data(
            site_id=site_id,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            urlopen_func=urlopen_func,
        )

    @staticmethod
    def _dataset_definition(dataset_id: str) -> Dict[str, str]:
        """Return the dataset spec used by the packaged study wrapper."""
        definitions = {
            "continuous_flow": {
                "dataset_id": "continuous_flow",
                "parameter": "flow",
                "observation_type": "continuous",
                "service_key": "continuous_flow",
                "file_name": "continuous_flow.csv",
            },
            "daily_flow": {
                "dataset_id": "daily_flow",
                "parameter": "flow",
                "observation_type": "daily",
                "service_key": "daily_flow",
                "file_name": "daily_flow.csv",
            },
            "peak_flow": {
                "dataset_id": "peak_flow",
                "parameter": "flow",
                "observation_type": "peak",
                "service_key": "peak_flow",
                "file_name": "peak_flow.csv",
            },
            "continuous_stage": {
                "dataset_id": "continuous_stage",
                "parameter": "stage",
                "observation_type": "continuous",
                "service_key": "continuous_stage",
                "file_name": "continuous_stage.csv",
            },
            "daily_stage": {
                "dataset_id": "daily_stage",
                "parameter": "stage",
                "observation_type": "daily",
                "service_key": "daily_stage",
                "file_name": "daily_stage.csv",
            },
        }
        if dataset_id not in definitions:
            raise ValueError(f"Unsupported dataset_id: {dataset_id}")
        return definitions[dataset_id]

    @staticmethod
    @log_call
    def get_dataset(
        site_id: str,
        dataset_id: str,
        start_datetime: Optional[Union[str, datetime]] = None,
        end_datetime: Optional[Union[str, datetime]] = None,
        services: Optional[Mapping[str, Callable[..., Any]]] = None,
    ) -> pd.DataFrame:
        """Return one normalized observation dataset by its stable dataset id."""
        spec = UsgsObservations._dataset_definition(dataset_id)
        resolved_services = UsgsObservations.resolve_services(services)
        raw_frame = resolved_services[spec["service_key"]](
            site_id,
            start_datetime,
            end_datetime,
        )
        return UsgsGaugeStudy._normalize_observation_frame(
            raw_frame,
            dataset_id=dataset_id,
        )

    @staticmethod
    @log_call
    def summarize_dataset(
        dataset_id: str,
        frame: pd.DataFrame,
        status: str = "ok",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return manifest/report-ready summary fields for a single dataset."""
        spec = UsgsObservations._dataset_definition(dataset_id)
        return UsgsGaugeStudy._summarize_dataset(
            dataset_id=dataset_id,
            observation_type=spec["observation_type"],
            parameter=spec["parameter"],
            file_name=spec["file_name"],
            frame=frame,
            status=status,
            error=error,
        )

    @staticmethod
    @log_call
    def analyze_gaps(
        dataset_id: str,
        frame: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Return the standardized gap analysis for a single dataset."""
        spec = UsgsObservations._dataset_definition(dataset_id)
        return UsgsGaugeStudy._build_gap_analysis(
            dataset_id=dataset_id,
            frame=frame,
            observation_type=spec["observation_type"],
        )


class UsgsGaugeStudy:
    """
    Convenience workspace builders built on the USGS observation primitives.

    This workflow is intentionally independent of ``init_ras_project()`` so it
    can run at the basin and gauge study stage before a HEC-RAS model exists.
    """

    SCHEMA_VERSION = "1.0"
    DEFAULT_PARAMETERS = ("flow", "stage")
    PEAK_SERVICE_URL = "https://nwis.waterdata.usgs.gov/nwis/peak"
    DATASET_UNITS = {
        "continuous_flow": "cfs",
        "daily_flow": "cfs",
        "peak_flow": "cfs",
        "continuous_stage": "ft",
        "daily_stage": "ft",
    }

    @staticmethod
    def _slugify(text: str) -> str:
        """Create a filesystem-friendly study slug."""
        cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(text).strip().lower())
        return cleaned.strip("-")

    @staticmethod
    def _as_path(path_like: Union[str, Path]) -> Path:
        """Normalize user paths to ``Path`` objects."""
        return Path(path_like)

    @staticmethod
    def _utc_now_iso() -> str:
        """Return a UTC timestamp suitable for JSON output."""
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _normalize_datetime(value: Union[str, datetime]) -> str:
        """Normalize date/datetime inputs into ISO strings for reports."""
        if isinstance(value, datetime):
            return value.isoformat()
        return pd.to_datetime(value).isoformat()

    @staticmethod
    def _serialize_json(data: Any) -> Any:
        """Recursively convert Paths, datetimes, and numpy objects for JSON."""
        if isinstance(data, Path):
            return str(data)
        if isinstance(data, (datetime, pd.Timestamp)):
            return data.isoformat()
        if isinstance(data, date):
            return data.isoformat()
        if isinstance(data, np.datetime64):
            return pd.Timestamp(data).isoformat()
        if isinstance(data, np.timedelta64):
            return str(pd.Timedelta(data))
        if isinstance(data, np.generic):
            return data.item()
        if isinstance(data, (np.ndarray, pd.Index, pd.Series)):
            return [UsgsGaugeStudy._serialize_json(item) for item in data.tolist()]
        if isinstance(data, Mapping):
            return {
                str(key): UsgsGaugeStudy._serialize_json(value)
                for key, value in data.items()
            }
        if isinstance(data, (list, tuple)):
            return [UsgsGaugeStudy._serialize_json(item) for item in data]
        return data

    @staticmethod
    def _relative_to(root: Path, target: Path) -> str:
        """Return POSIX-style relative paths for manifest/report files."""
        return target.relative_to(root).as_posix()

    @staticmethod
    def _normalize_observation_frame(
        frame: Optional[pd.DataFrame],
        dataset_id: str
    ) -> pd.DataFrame:
        """Normalize fetched observation frames to a stable CSV/report shape."""
        if frame is None:
            return pd.DataFrame(columns=["datetime", "value"])

        df = frame.copy()
        if "datetime" not in df.columns:
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index()
                first_col = df.columns[0]
                df = df.rename(columns={first_col: "datetime"})
            elif "date" in df.columns:
                df = df.rename(columns={"date": "datetime"})

        if "value" not in df.columns and len(df.columns) == 1:
            df = df.rename(columns={df.columns[0]: "value"})

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)

        if dataset_id == "peak_flow" and "datetime" not in df.columns:
            raise ValueError("Peak-flow observations must include a 'datetime' column.")

        return df

    @staticmethod
    def _dataset_specs(
        parameters: Sequence[str],
        include_continuous: bool,
        include_daily: bool,
        include_peak: bool
    ) -> Iterable[Dict[str, str]]:
        """Yield the requested dataset definitions in a stable order."""
        normalized = {str(parameter).strip().lower() for parameter in parameters}

        if include_continuous and "flow" in normalized:
            yield {
                "dataset_id": "continuous_flow",
                "parameter": "flow",
                "observation_type": "continuous",
                "service_key": "continuous_flow",
                "file_name": "continuous_flow.csv",
            }
        if include_daily and "flow" in normalized:
            yield {
                "dataset_id": "daily_flow",
                "parameter": "flow",
                "observation_type": "daily",
                "service_key": "daily_flow",
                "file_name": "daily_flow.csv",
            }
        if include_peak and "flow" in normalized:
            yield {
                "dataset_id": "peak_flow",
                "parameter": "flow",
                "observation_type": "peak",
                "service_key": "peak_flow",
                "file_name": "peak_flow.csv",
            }
        if include_continuous and "stage" in normalized:
            yield {
                "dataset_id": "continuous_stage",
                "parameter": "stage",
                "observation_type": "continuous",
                "service_key": "continuous_stage",
                "file_name": "continuous_stage.csv",
            }
        if include_daily and "stage" in normalized:
            yield {
                "dataset_id": "daily_stage",
                "parameter": "stage",
                "observation_type": "daily",
                "service_key": "daily_stage",
                "file_name": "daily_stage.csv",
            }

    @staticmethod
    def _default_services() -> Dict[str, Callable[..., Any]]:
        """Return the default network-backed study services."""
        return {
            "metadata": RasUsgsCore.get_gauge_metadata,
            "continuous_flow": (
                lambda site_id, start_datetime, end_datetime:
                RasUsgsCore.retrieve_flow_data(
                    site_id=site_id,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    data_type="iv",
                )
            ),
            "daily_flow": (
                lambda site_id, start_datetime, end_datetime:
                RasUsgsCore.retrieve_flow_data(
                    site_id=site_id,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    data_type="dv",
                )
            ),
            "continuous_stage": (
                lambda site_id, start_datetime, end_datetime:
                RasUsgsCore.retrieve_stage_data(
                    site_id=site_id,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    data_type="iv",
                )
            ),
            "daily_stage": (
                lambda site_id, start_datetime, end_datetime:
                RasUsgsCore.retrieve_stage_data(
                    site_id=site_id,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    data_type="dv",
                )
            ),
            "peak_flow": UsgsGaugeStudy.retrieve_peak_flow_data,
        }

    @staticmethod
    def _resolve_services(
        services: Optional[Mapping[str, Callable[..., Any]]] = None
    ) -> Dict[str, Callable[..., Any]]:
        """Merge caller-supplied mock services with default implementations."""
        resolved = UsgsGaugeStudy._default_services()
        if services:
            resolved.update(dict(services))
        return resolved

    @staticmethod
    def _guess_expected_interval(frame: pd.DataFrame) -> Optional[str]:
        """Infer the nearest HEC-RAS interval code from observation timestamps."""
        if "datetime" not in frame.columns or len(frame) < 2:
            return None

        times = pd.to_datetime(frame["datetime"]).sort_values()
        deltas = times.diff().dropna()
        if deltas.empty:
            return None

        median_seconds = float(deltas.dt.total_seconds().median())
        interval_seconds = {
            "1MIN": 60,
            "5MIN": 300,
            "10MIN": 600,
            "15MIN": 900,
            "30MIN": 1800,
            "1HOUR": 3600,
            "2HOUR": 7200,
            "3HOUR": 10800,
            "4HOUR": 14400,
            "6HOUR": 21600,
            "8HOUR": 28800,
            "12HOUR": 43200,
            "1DAY": 86400,
        }
        return min(
            interval_seconds.items(),
            key=lambda item: abs(item[1] - median_seconds),
        )[0]

    @staticmethod
    def _build_gap_analysis(
        dataset_id: str,
        frame: pd.DataFrame,
        observation_type: str
    ) -> Dict[str, Any]:
        """Build a stable data-gap summary for time-based observations."""
        if frame.empty:
            return {
                "dataset_id": dataset_id,
                "status": "empty",
                "expected_interval": None,
                "has_gaps": False,
                "gap_count": 0,
                "data_coverage": 0.0,
                "message": "No records available.",
            }

        if observation_type == "peak":
            return {
                "dataset_id": dataset_id,
                "status": "not_applicable",
                "expected_interval": None,
                "has_gaps": None,
                "gap_count": None,
                "data_coverage": None,
                "message": "Peak observations are event records, not a regular interval series.",
            }

        if "datetime" not in frame.columns or len(frame) < 2:
            return {
                "dataset_id": dataset_id,
                "status": "insufficient_records",
                "expected_interval": None,
                "has_gaps": False,
                "gap_count": 0,
                "data_coverage": 1.0 if len(frame) == 1 else 0.0,
                "message": "At least two timestamps are required for gap analysis.",
            }

        expected_interval = UsgsGaugeStudy._guess_expected_interval(frame)
        if expected_interval is None:
            return {
                "dataset_id": dataset_id,
                "status": "unknown_interval",
                "expected_interval": None,
                "has_gaps": None,
                "gap_count": None,
                "data_coverage": None,
                "message": "Unable to infer an expected interval from timestamps.",
            }

        gap_analysis = TimeSeriesProcessor.check_data_gaps(
            frame[["datetime", "value"]].copy(),
            expected_interval=expected_interval,
            time_column="datetime",
        )
        gap_analysis.update({
            "dataset_id": dataset_id,
            "status": "ok",
            "expected_interval": expected_interval,
        })
        return gap_analysis

    @staticmethod
    def _summarize_dataset(
        dataset_id: str,
        observation_type: str,
        parameter: str,
        file_name: str,
        frame: pd.DataFrame,
        status: str,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build dataset inventory metadata shared by the manifest and report."""
        summary = {
            "dataset_id": dataset_id,
            "observation_type": observation_type,
            "parameter": parameter,
            "status": status,
            "units": UsgsGaugeStudy.DATASET_UNITS.get(dataset_id),
            "record_count": int(len(frame)),
            "file_name": file_name,
            "columns": frame.columns.tolist(),
            "start_datetime": None,
            "end_datetime": None,
            "error": error,
        }

        if "datetime" in frame.columns and not frame.empty:
            datetimes = pd.to_datetime(frame["datetime"])
            summary["start_datetime"] = datetimes.min().isoformat()
            summary["end_datetime"] = datetimes.max().isoformat()

        return summary

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        """Write JSON outputs with stable formatting."""
        path.write_text(
            json.dumps(
                UsgsGaugeStudy._serialize_json(payload),
                indent=2,
                sort_keys=False,
                default=lambda value: (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else str(value)
                ),
            ),
            encoding="utf-8",
        )

    @staticmethod
    @log_call
    def build_workspace(
        base_folder: Union[str, Path],
        site_id: str,
        study_name: Optional[str] = None,
        create: bool = True
    ) -> Dict[str, Path]:
        """
        Build the standardized workspace folder for a basin-first gauge study.

        Parameters
        ----------
        base_folder : str or Path
            Parent folder where the gauge study workspace should live.
        site_id : str
            USGS site identifier.
        study_name : str, optional
            Optional study label appended to the folder name.
        create : bool, default True
            If True, create the folder structure on disk.

        Returns
        -------
        dict
            Paths for the root workspace, observation folder, and standard JSON
            output files.
        """
        base_path = UsgsGaugeStudy._as_path(base_folder)
        suffix = f"_{UsgsGaugeStudy._slugify(study_name)}" if study_name else ""
        root = base_path / f"USGS-{site_id}{suffix}"

        workspace = {
            "root": root,
            "observations": root / "observations",
            "metadata_path": root / "metadata.json",
            "manifest_path": root / "manifest.json",
            "report_path": root / "report.json",
            "data_gap_analysis_path": root / "data_gap_analysis.json",
        }

        if create:
            workspace["observations"].mkdir(parents=True, exist_ok=True)

        return workspace

    @staticmethod
    @log_call
    def retrieve_peak_flow_data(
        site_id: str,
        start_datetime: Optional[Union[str, datetime]] = None,
        end_datetime: Optional[Union[str, datetime]] = None,
        urlopen_func: Callable[..., Any] = urlopen
    ) -> pd.DataFrame:
        """
        Retrieve annual/event peak-flow observations from the USGS peak service.

        Parameters
        ----------
        site_id : str
            USGS site identifier.
        start_datetime, end_datetime : str or datetime, optional
            Optional filter window. Returned peaks are clipped to this range.
        urlopen_func : callable, default urllib.request.urlopen
            Injectable boundary for testing.

        Returns
        -------
        pandas.DataFrame
            Standardized peak-flow observations with ``datetime`` and ``value``
            columns plus any available peak-specific metadata columns.
        """
        query = urlencode({
            "site_no": site_id,
            "agency_cd": "USGS",
            "format": "rdb",
        })
        url = f"{UsgsGaugeStudy.PEAK_SERVICE_URL}?{query}"

        with urlopen_func(url) as response:
            text = response.read().decode("utf-8", errors="replace")

        data_lines = [
            line for line in text.splitlines()
            if line and not line.startswith("#")
        ]
        if len(data_lines) < 3:
            return pd.DataFrame(columns=["datetime", "value"])

        # RDB responses include a field-width descriptor row after the header.
        parsed = pd.read_csv(
            io.StringIO("\n".join([data_lines[0]] + data_lines[2:])),
            sep="\t",
            dtype=str,
        )

        if parsed.empty:
            return pd.DataFrame(columns=["datetime", "value"])

        date_column = next(
            (column for column in ("peak_dt", "peak_dt_va", "peak_tm") if column in parsed.columns),
            None,
        )
        if date_column is None:
            raise ValueError("Peak-flow response did not include a peak date column.")

        value_column = next(
            (column for column in ("peak_va", "peak_flow", "peak_discharge") if column in parsed.columns),
            None,
        )
        if value_column is None:
            raise ValueError("Peak-flow response did not include a peak discharge column.")

        result = parsed.copy()
        result["datetime"] = pd.to_datetime(result[date_column], errors="coerce")
        result["value"] = pd.to_numeric(result[value_column], errors="coerce")

        if "gage_ht" in result.columns:
            result["gage_height_ft"] = pd.to_numeric(result["gage_ht"], errors="coerce")
        elif "gage_ht_va" in result.columns:
            result["gage_height_ft"] = pd.to_numeric(result["gage_ht_va"], errors="coerce")

        result = result.dropna(subset=["datetime", "value"]).reset_index(drop=True)

        if start_datetime is not None:
            result = result[result["datetime"] >= pd.to_datetime(start_datetime)]
        if end_datetime is not None:
            result = result[result["datetime"] <= pd.to_datetime(end_datetime)]

        ordered_columns = ["datetime", "value"]
        if "gage_height_ft" in result.columns:
            ordered_columns.append("gage_height_ft")
        remaining_columns = [
            column for column in result.columns
            if column not in ordered_columns
        ]
        result = result[ordered_columns + remaining_columns]
        result.attrs["site_id"] = site_id
        result.attrs["parameter"] = "flow"
        result.attrs["parameter_code"] = "peak_flow"
        result.attrs["units"] = "cfs"
        result.attrs["data_type"] = "peak"

        return result

    @staticmethod
    @log_call
    def collect_observed_data(
        site_id: str,
        start_datetime: Union[str, datetime],
        end_datetime: Union[str, datetime],
        parameters: Sequence[str] = DEFAULT_PARAMETERS,
        include_continuous: bool = True,
        include_daily: bool = True,
        include_peak: bool = True,
        services: Optional[Mapping[str, Callable[..., Any]]] = None
    ) -> Dict[str, Any]:
        """
        Retrieve gauge metadata and requested observed-data inventories.

        Parameters
        ----------
        site_id : str
            USGS site identifier.
        start_datetime, end_datetime : str or datetime
            Requested study window.
        parameters : sequence of str, default ('flow', 'stage')
            Observation parameters to package.
        include_continuous, include_daily, include_peak : bool
            Toggle continuous, daily, and peak dataset retrieval.
        services : mapping, optional
            Injectable network/service boundaries. Supported keys are
            ``metadata``, ``continuous_flow``, ``daily_flow``,
            ``continuous_stage``, ``daily_stage``, and ``peak_flow``.

        Returns
        -------
        dict
            Structured metadata, inventory, in-memory data frames, and
            gap-analysis results aligned with the study package contract.
        """
        resolved_services = UsgsObservations.resolve_services(services)
        metadata_error = None

        try:
            metadata = UsgsObservations.get_gauge_metadata(
                site_id=site_id,
                services=resolved_services,
            )
        except Exception as exc:
            metadata_error = str(exc)
            logger.warning("Metadata retrieval failed for site %s: %s", site_id, exc)
            metadata = {"site_id": site_id}

        dataset_summaries = {}
        dataset_frames = {}
        gap_analysis = {}

        for spec in UsgsGaugeStudy._dataset_specs(
            parameters=parameters,
            include_continuous=include_continuous,
            include_daily=include_daily,
            include_peak=include_peak,
        ):
            dataset_id = spec["dataset_id"]

            try:
                frame = UsgsObservations.get_dataset(
                    site_id=site_id,
                    dataset_id=dataset_id,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    services=resolved_services,
                )
                status = "ok" if not frame.empty else "empty"
                error = None
            except Exception as exc:
                logger.warning(
                    "Dataset retrieval failed for %s (%s): %s",
                    site_id,
                    dataset_id,
                    exc,
                )
                frame = pd.DataFrame(columns=["datetime", "value"])
                status = "error"
                error = str(exc)

            dataset_frames[dataset_id] = frame
            dataset_summaries[dataset_id] = UsgsObservations.summarize_dataset(
                dataset_id=dataset_id,
                frame=frame,
                status=status,
                error=error,
            )
            gap_analysis[dataset_id] = UsgsObservations.analyze_gaps(
                dataset_id=dataset_id,
                frame=frame,
            )

        total_records = sum(
            summary["record_count"] for summary in dataset_summaries.values()
        )
        datasets_ok = sum(
            1 for summary in dataset_summaries.values()
            if summary["status"] == "ok"
        )

        return {
            "site_id": site_id,
            "requested_window": {
                "start_datetime": UsgsGaugeStudy._normalize_datetime(start_datetime),
                "end_datetime": UsgsGaugeStudy._normalize_datetime(end_datetime),
            },
            "metadata": metadata,
            "metadata_error": metadata_error,
            "inventory": dataset_summaries,
            "dataframes": dataset_frames,
            "data_gap_analysis": gap_analysis,
            "summary": {
                "dataset_count": len(dataset_summaries),
                "datasets_ok": datasets_ok,
                "datasets_with_errors": sum(
                    1 for summary in dataset_summaries.values()
                    if summary["status"] == "error"
                ),
                "total_records": total_records,
            },
        }

    @staticmethod
    @log_call
    def package_gauge_study(
        base_folder: Union[str, Path],
        site_id: str,
        start_datetime: Union[str, datetime],
        end_datetime: Union[str, datetime],
        study_name: Optional[str] = None,
        parameters: Sequence[str] = DEFAULT_PARAMETERS,
        include_continuous: bool = True,
        include_daily: bool = True,
        include_peak: bool = True,
        drainage_areas: Optional[Mapping[str, Optional[Union[int, float]]]] = None,
        services: Optional[Mapping[str, Callable[..., Any]]] = None,
        write_outputs: bool = True
    ) -> Dict[str, Any]:
        """
        Build a basin-first USGS gauge study package.

        This method creates a standardized study workspace, retrieves metadata
        plus continuous/daily/peak observations, computes simple gap analyses,
        and writes ``manifest.json``, ``report.json``, and
        ``data_gap_analysis.json`` outputs when requested.
        """
        workspace = UsgsGaugeStudy.build_workspace(
            base_folder=base_folder,
            site_id=site_id,
            study_name=study_name,
            create=write_outputs,
        )

        collected = UsgsGaugeStudy.collect_observed_data(
            site_id=site_id,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            parameters=parameters,
            include_continuous=include_continuous,
            include_daily=include_daily,
            include_peak=include_peak,
            services=services,
        )

        drainage_area_inputs = dict(drainage_areas or {})
        if (
            "gauge_area_sqmi" not in drainage_area_inputs
            and collected["metadata"].get("drainage_area_sqmi") is not None
        ):
            drainage_area_inputs["gauge_area_sqmi"] = collected["metadata"].get(
                "drainage_area_sqmi"
            )
        drainage_area_comparison = UsgsDrainageAreaComparison.compare_areas(
            **drainage_area_inputs
        )

        manifest = {
            "schema_version": UsgsGaugeStudy.SCHEMA_VERSION,
            "package_type": "usgs_gauge_study",
            "site_id": site_id,
            "study_name": study_name,
            "generated_at_utc": UsgsGaugeStudy._utc_now_iso(),
            "workspace_root": str(workspace["root"]),
            "metadata_path": UsgsGaugeStudy._relative_to(
                workspace["root"], workspace["metadata_path"]
            ),
            "report_path": UsgsGaugeStudy._relative_to(
                workspace["root"], workspace["report_path"]
            ),
            "data_gap_analysis_path": UsgsGaugeStudy._relative_to(
                workspace["root"], workspace["data_gap_analysis_path"]
            ),
            "datasets": [],
        }

        for dataset_id, summary in collected["inventory"].items():
            dataset_entry = dict(summary)
            dataset_entry["path"] = UsgsGaugeStudy._relative_to(
                workspace["root"],
                workspace["observations"] / summary["file_name"],
            )
            manifest["datasets"].append(dataset_entry)

        report = {
            "schema_version": UsgsGaugeStudy.SCHEMA_VERSION,
            "package_type": "usgs_gauge_study",
            "site_id": site_id,
            "study_name": study_name,
            "generated_at_utc": manifest["generated_at_utc"],
            "requested_window": collected["requested_window"],
            "summary": collected["summary"],
            "metadata_error": collected["metadata_error"],
            "metadata": collected["metadata"],
            "inventory": collected["inventory"],
            "drainage_area_comparison": drainage_area_comparison,
        }

        if write_outputs:
            workspace["root"].mkdir(parents=True, exist_ok=True)
            workspace["observations"].mkdir(parents=True, exist_ok=True)
            UsgsGaugeStudy._write_json(
                workspace["metadata_path"],
                collected["metadata"],
            )

            for dataset_id, frame in collected["dataframes"].items():
                file_name = collected["inventory"][dataset_id]["file_name"]
                frame.to_csv(
                    workspace["observations"] / file_name,
                    index=False,
                    encoding="utf-8",
                )

            UsgsGaugeStudy._write_json(
                workspace["manifest_path"],
                manifest,
            )
            UsgsGaugeStudy._write_json(
                workspace["report_path"],
                report,
            )
            UsgsGaugeStudy._write_json(
                workspace["data_gap_analysis_path"],
                collected["data_gap_analysis"],
            )

        return {
            "workspace": {key: str(value) for key, value in workspace.items()},
            "manifest": manifest,
            "report": report,
            "data_gap_analysis": collected["data_gap_analysis"],
            "inventory": collected["inventory"],
            "metadata": collected["metadata"],
            "metadata_error": collected["metadata_error"],
            "drainage_area_comparison": drainage_area_comparison,
        }


class UsgsModelPrepValidation:
    """
    Primitive-first validation helpers for model-prep readiness checks.

    These methods expose the reusable validation pieces directly. The report
    builder class composes them when callers want the shared-contract JSON
    outputs written to disk.
    """

    @staticmethod
    def _coerce_drainage_area_input(
        comparison: Optional[Mapping[str, Any]],
    ) -> Optional[Mapping[str, Any]]:
        """Accept either raw area values or a precomputed comparison payload."""
        if comparison is None:
            return None
        if "provided_area_count" in comparison:
            return comparison

        area_keys = {
            "gauge_area_sqmi",
            "official_basin_area_sqmi",
            "taudem_area_sqmi",
            "model_area_sqmi",
            "reference_key",
        }
        if any(key in comparison for key in area_keys):
            return UsgsDrainageAreaComparison.compare_areas(**dict(comparison))

        return comparison

    @staticmethod
    @log_call
    def load_study_context(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Load the normalized context used by model-prep validation."""
        return UsgsModelPrepReport._load_study_context(study_package_or_root)

    @staticmethod
    @log_call
    def validate_observed_data_package(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Validate the observed-data package independent of report generation."""
        ctx = UsgsModelPrepValidation.load_study_context(study_package_or_root)
        return UsgsModelPrepReport._observed_data_validation(ctx)

    @staticmethod
    @log_call
    def validate_drainage_area_comparison(
        comparison: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Validate drainage-area readiness independent of report generation."""
        normalized = UsgsModelPrepValidation._coerce_drainage_area_input(comparison)
        return UsgsModelPrepReport._drainage_area_validation(normalized)

    @staticmethod
    @log_call
    def validate_geometry_handoff(
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        """Validate geometry handoff readiness independent of report generation."""
        return UsgsModelPrepReport._geometry_handoff_validation(geometry_handoff)

    @staticmethod
    @log_call
    def validate_model_prep(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
        drainage_area_comparison: Optional[Mapping[str, Any]] = None,
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Return the combined readiness status without building report JSON."""
        normalized = UsgsModelPrepValidation._coerce_drainage_area_input(
            drainage_area_comparison
        )
        return UsgsModelPrepReport.validate_model_prep(
            study_package_or_root=study_package_or_root,
            drainage_area_comparison=normalized,
            geometry_handoff=geometry_handoff,
        )


class UsgsModelPrepReport:
    """
    Convenience shared-contract report builders for model-prep workflows.

    This class consumes the basin-first ``UsgsGaugeStudy`` package outputs and
    emits machine-readable ``report.json`` and ``data_gap_analysis.json``
    documents aligned with the shared base engineering report contract.
    """

    REPORT_SCHEMA_VERSION = "base-engineering-report/v1"
    GAP_SCHEMA_VERSION = "data-gap-analysis/v1"

    @staticmethod
    def _make_gap(
        gap_id: str,
        category: str,
        severity: str,
        status: str,
        description: str,
        affected_artifact: str,
        owner_repo: str,
        blocking_for: Optional[Sequence[str]],
        recommended_action: str,
        issue_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a standardized gap entry."""
        return {
            "id": gap_id,
            "category": category,
            "severity": severity,
            "status": status,
            "description": description,
            "affected_artifact": affected_artifact,
            "owner_repo": owner_repo,
            "issue_url": issue_url,
            "blocking_for": list(blocking_for or []),
            "recommended_action": recommended_action,
        }

    @staticmethod
    def _issue_url(
        issue_urls: Optional[Mapping[str, Optional[str]]],
        *keys: str
    ) -> Optional[str]:
        """Return the first matching non-empty issue URL for the requested keys."""
        if not issue_urls:
            return None

        for key in keys:
            value = issue_urls.get(key)
            if value:
                return value
        return None

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        """Load a JSON file when present."""
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _coerce_workspace_paths(
        workspace: Optional[Mapping[str, Any]],
        root: Optional[Path]
    ) -> Dict[str, Optional[Path]]:
        """Normalize workspace path records from study-package outputs."""
        normalized = {}
        for key, value in (workspace or {}).items():
            if value is None:
                normalized[key] = None
            else:
                normalized[key] = Path(value)

        if root is None:
            root_value = normalized.get("root")
            root = root_value if isinstance(root_value, Path) else None

        normalized.setdefault("root", root)
        if root is not None:
            normalized.setdefault("manifest_path", root / "manifest.json")
            normalized.setdefault("report_path", root / "report.json")
            normalized.setdefault("data_gap_analysis_path", root / "data_gap_analysis.json")
            normalized.setdefault("metadata_path", root / "metadata.json")
            normalized.setdefault("observations", root / "observations")

        return normalized

    @staticmethod
    def _load_study_context(
        study_package_or_root: Union[str, Path, Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """Resolve an in-memory study package or workspace path into one context."""
        if isinstance(study_package_or_root, Mapping):
            workspace = study_package_or_root.get("workspace", {})
            root = None
            if workspace and workspace.get("root"):
                root = Path(workspace["root"])
            elif "root" in study_package_or_root:
                root = Path(study_package_or_root["root"])

            paths = UsgsModelPrepReport._coerce_workspace_paths(workspace, root)
            manifest = study_package_or_root.get("manifest")
            report = study_package_or_root.get("report")
            gap_analysis = study_package_or_root.get("data_gap_analysis")
            metadata = study_package_or_root.get("metadata")
            inventory = study_package_or_root.get("inventory")
            drainage_area_comparison = study_package_or_root.get("drainage_area_comparison")
        else:
            root = Path(study_package_or_root)
            paths = UsgsModelPrepReport._coerce_workspace_paths({}, root)
            manifest = None
            report = None
            gap_analysis = None
            metadata = None
            inventory = None
            drainage_area_comparison = None

        manifest = manifest or UsgsModelPrepReport._read_json(paths["manifest_path"])
        report = report or UsgsModelPrepReport._read_json(paths["report_path"])
        gap_analysis = gap_analysis or UsgsModelPrepReport._read_json(
            paths["data_gap_analysis_path"]
        )
        metadata = metadata or UsgsModelPrepReport._read_json(paths["metadata_path"]) or {}
        inventory = inventory or (report or {}).get("inventory") or {}
        drainage_area_comparison = (
            drainage_area_comparison
            or (report or {}).get("drainage_area_comparison")
        )

        if paths["root"] is None:
            raise ValueError("Unable to resolve study workspace root for model-prep reporting.")

        return {
            "root": paths["root"],
            "paths": paths,
            "manifest": manifest or {},
            "report": report or {},
            "data_gap_analysis": gap_analysis or {},
            "metadata": metadata,
            "inventory": inventory,
            "drainage_area_comparison": drainage_area_comparison or {},
        }

    @staticmethod
    def _relative_path(root: Path, path: Optional[Path]) -> Optional[str]:
        """Return a stable relative path for report artifacts."""
        if path is None:
            return None
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _observed_data_validation(ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the basin-first observed-data package for model-prep use."""
        required_paths = {
            "manifest": ctx["paths"]["manifest_path"],
            "report": ctx["paths"]["report_path"],
            "data_gap_analysis": ctx["paths"]["data_gap_analysis_path"],
            "metadata": ctx["paths"]["metadata_path"],
        }
        missing_required_artifacts = [
            name for name, path in required_paths.items()
            if path is None or not path.exists()
        ]

        inventory = ctx["inventory"] or {}
        dataset_statuses = {
            dataset_id: details.get("status", "unknown")
            for dataset_id, details in inventory.items()
        }
        dataset_errors = [
            dataset_id for dataset_id, status in dataset_statuses.items()
            if status == "error"
        ]
        dataset_empty = [
            dataset_id for dataset_id, status in dataset_statuses.items()
            if status == "empty"
        ]

        if missing_required_artifacts:
            status = "missing"
        elif dataset_errors:
            status = "partial"
        else:
            status = "complete"

        return {
            "status": status,
            "package_type": ctx["manifest"].get("package_type"),
            "schema_version": ctx["manifest"].get("schema_version"),
            "missing_required_artifacts": missing_required_artifacts,
            "dataset_count": len(inventory),
            "dataset_statuses": dataset_statuses,
            "dataset_errors": dataset_errors,
            "empty_dataset_ids": dataset_empty,
            "datasets_ok": sum(
                1 for status in dataset_statuses.values()
                if status == "ok"
            ),
        }

    @staticmethod
    def _drainage_area_validation(
        comparison: Optional[Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """Validate drainage-area comparison readiness for model prep."""
        comparison = dict(comparison or {})
        provided_area_count = int(comparison.get("provided_area_count", 0) or 0)
        agreement_status = comparison.get("agreement_status", "no_area_inputs")

        if provided_area_count == 0:
            status = "missing"
        elif provided_area_count < 2 or agreement_status == "insufficient_comparison_data":
            status = "partial"
        elif agreement_status == "review":
            status = "review"
        else:
            status = "complete"

        return {
            "status": status,
            "provided_area_count": provided_area_count,
            "reference_key": comparison.get("reference_key"),
            "reference_area_sqmi": comparison.get("reference_area_sqmi"),
            "agreement_status": agreement_status,
            "max_abs_percent_difference": comparison.get("max_abs_percent_difference"),
            "areas_sqmi": comparison.get("areas_sqmi", {}),
        }

    @staticmethod
    def _geometry_handoff_validation(
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]]
    ) -> Dict[str, Any]:
        """Normalize geometry handoff input into a reusable validation record."""
        if geometry_handoff is None:
            return {
                "status": "missing",
                "artifact_path": None,
                "artifact_exists": False,
                "ready_for_geometry": False,
                "notes": None,
            }

        if isinstance(geometry_handoff, (str, Path)):
            path = Path(geometry_handoff)
            exists = path.exists()
            return {
                "status": "complete" if exists else "missing",
                "artifact_path": str(path),
                "artifact_exists": exists,
                "ready_for_geometry": exists,
                "notes": None,
            }

        artifact_value = (
            geometry_handoff.get("artifact_path")
            or geometry_handoff.get("path")
        )
        path = Path(artifact_value) if artifact_value else None
        exists = path.exists() if path is not None else False
        ready = geometry_handoff.get("ready_for_geometry")
        if ready is None:
            ready = geometry_handoff.get("handoff_ready")
        if ready is None:
            ready = exists
        ready = bool(ready)

        status = geometry_handoff.get("status")
        if status is None:
            if ready and exists:
                status = "complete"
            elif exists:
                status = "partial"
            else:
                status = "missing"

        return {
            "status": status,
            "artifact_path": str(path) if path is not None else None,
            "artifact_exists": exists,
            "ready_for_geometry": ready,
            "notes": geometry_handoff.get("notes"),
        }

    @staticmethod
    @log_call
    def validate_model_prep(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
        drainage_area_comparison: Optional[Mapping[str, Any]] = None,
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Return machine-readable validation status for model-prep readiness."""
        ctx = UsgsModelPrepReport._load_study_context(study_package_or_root)
        normalized_drainage = UsgsModelPrepValidation._coerce_drainage_area_input(
            drainage_area_comparison or ctx["drainage_area_comparison"]
        )
        observed = UsgsModelPrepReport._observed_data_validation(ctx)
        drainage = UsgsModelPrepReport._drainage_area_validation(normalized_drainage)
        geometry = UsgsModelPrepReport._geometry_handoff_validation(geometry_handoff)

        statuses = [observed["status"], drainage["status"], geometry["status"]]
        if all(status == "complete" for status in statuses):
            overall_status = "complete"
        elif "missing" in statuses:
            overall_status = "partial"
        elif "review" in statuses or "partial" in statuses:
            overall_status = "partial"
        else:
            overall_status = "partial"

        return {
            "status": overall_status,
            "workspace_dir": str(ctx["root"]),
            "observed_data_package": observed,
            "drainage_area_comparison": drainage,
            "geometry_handoff": geometry,
        }

    @staticmethod
    @log_call
    def build_gap_analysis(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
        drainage_area_comparison: Optional[Mapping[str, Any]] = None,
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]] = None,
        issue_urls: Optional[Mapping[str, Optional[str]]] = None,
        generated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build shared-contract ``data_gap_analysis.json`` payload for model prep."""
        ctx = UsgsModelPrepReport._load_study_context(study_package_or_root)
        generated_at = generated_at or UsgsGaugeStudy._utc_now_iso()
        validation = UsgsModelPrepReport.validate_model_prep(
            ctx,
            drainage_area_comparison=drainage_area_comparison,
            geometry_handoff=geometry_handoff,
        )
        gaps = []

        observed = validation["observed_data_package"]
        if observed["missing_required_artifacts"]:
            missing_text = ", ".join(observed["missing_required_artifacts"])
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="observed-data-package-missing-artifacts",
                category="data",
                severity="high",
                status="open",
                description=(
                    "The basin-first observed-data package is missing required study artifacts: "
                    f"{missing_text}."
                ),
                affected_artifact="observed_data_package",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "observed_data_package",
                    "ras_commander_report_contract",
                ),
                blocking_for=["model-prep-report", "geometry_creation"],
                recommended_action=(
                    "Rebuild the USGS gauge study package so manifest, report, data-gap, "
                    "and metadata artifacts are present before model-prep reporting."
                ),
            ))

        if observed["dataset_errors"]:
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="observed-data-package-errors",
                category="data",
                severity="medium",
                status="open",
                description=(
                    "One or more observed-data datasets failed during packaging: "
                    f"{', '.join(observed['dataset_errors'])}."
                ),
                affected_artifact="observed_data_package",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "observed_data_package",
                    "ras_commander_report_contract",
                ),
                blocking_for=["calibration_inputs"],
                recommended_action=(
                    "Inspect the failed dataset retrievals, correct the service or input "
                    "issue, and regenerate the basin-first package."
                ),
            ))

        drainage = validation["drainage_area_comparison"]
        if drainage["status"] in {"missing", "partial"}:
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="drainage-area-comparison-incomplete",
                category="analysis",
                severity="medium",
                status="open",
                description=(
                    "Drainage-area comparison does not yet include enough inputs to support "
                    "model-prep review."
                ),
                affected_artifact="drainage_area_comparison",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "drainage_area_comparison",
                    "ras_commander_drainage_area",
                ),
                blocking_for=["model-readiness"],
                recommended_action=(
                    "Provide at least two comparable drainage-area values such as gauge, "
                    "official basin, TauDEM, or model area inputs."
                ),
            ))
        elif drainage["status"] == "review":
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="drainage-area-comparison-review",
                category="analysis",
                severity="medium",
                status="open",
                description=(
                    "Drainage-area comparison indicates a mismatch that should be resolved "
                    "before geometry promotion."
                ),
                affected_artifact="drainage_area_comparison",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "drainage_area_comparison",
                    "ras_commander_drainage_area",
                ),
                blocking_for=["model-readiness"],
                recommended_action=(
                    "Review gauge, official basin, TauDEM, and model drainage areas and "
                    "document the accepted engineering basis."
                ),
            ))

        geometry = validation["geometry_handoff"]
        if geometry["status"] == "missing":
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="geometry-handoff-missing",
                category="tooling",
                severity="medium",
                status="open",
                description=(
                    "No geometry handoff artifact is available for promoting the basin-first "
                    "study package into model construction."
                ),
                affected_artifact="geometry_handoff",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "geometry_handoff",
                    "ras_commander_geometry_builder",
                ),
                blocking_for=["geometry_creation"],
                recommended_action=(
                    "Create or attach a geometry handoff artifact that documents the inputs "
                    "required by the downstream model-building workflow."
                ),
            ))
        elif geometry["status"] != "complete" or not geometry["ready_for_geometry"]:
            gaps.append(UsgsModelPrepReport._make_gap(
                gap_id="geometry-handoff-incomplete",
                category="tooling",
                severity="medium",
                status="open",
                description=(
                    "A geometry handoff artifact exists, but it is not yet marked ready "
                    "for downstream geometry creation."
                ),
                affected_artifact="geometry_handoff",
                owner_repo="ras-commander",
                issue_url=UsgsModelPrepReport._issue_url(
                    issue_urls,
                    "geometry_handoff",
                    "ras_commander_geometry_builder",
                ),
                blocking_for=["geometry_creation"],
                recommended_action=(
                    "Finalize the geometry handoff notes and mark the handoff ready before "
                    "starting model geometry generation."
                ),
            ))

        study_name = (
            ctx["manifest"].get("study_name")
            or ctx["report"].get("study_name")
            or ctx["metadata"].get("station_name")
            or f"USGS {ctx['metadata'].get('site_id', 'study')}"
        )
        return {
            "schema_version": UsgsModelPrepReport.GAP_SCHEMA_VERSION,
            "generated_at": generated_at,
            "study_name": f"{study_name} Model Prep Report",
            "workspace_dir": str(ctx["root"]),
            "status": validation["status"],
            "gap_count": len(gaps),
            "gaps": gaps,
        }

    @staticmethod
    @log_call
    def build_report_json(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
        drainage_area_comparison: Optional[Mapping[str, Any]] = None,
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]] = None,
        gap_analysis: Optional[Mapping[str, Any]] = None,
        generated_at: Optional[str] = None,
        report_json_path: Optional[Union[str, Path]] = None,
        gap_analysis_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Build shared-contract ``report.json`` payload for model-prep use."""
        ctx = UsgsModelPrepReport._load_study_context(study_package_or_root)
        generated_at = generated_at or UsgsGaugeStudy._utc_now_iso()
        validation = UsgsModelPrepReport.validate_model_prep(
            ctx,
            drainage_area_comparison=drainage_area_comparison,
            geometry_handoff=geometry_handoff,
        )
        gap_analysis = gap_analysis or UsgsModelPrepReport.build_gap_analysis(
            ctx,
            drainage_area_comparison=drainage_area_comparison,
            geometry_handoff=geometry_handoff,
            generated_at=generated_at,
        )

        report_json_path = Path(report_json_path) if report_json_path else None
        gap_analysis_path = Path(gap_analysis_path) if gap_analysis_path else None

        study_name = (
            ctx["manifest"].get("study_name")
            or ctx["report"].get("study_name")
            or ctx["metadata"].get("station_name")
            or f"USGS {ctx['metadata'].get('site_id', 'study')}"
        )
        site_id = ctx["metadata"].get("site_id") or ctx["manifest"].get("site_id")
        inventory = ctx["inventory"] or {}

        return {
            "schema_version": UsgsModelPrepReport.REPORT_SCHEMA_VERSION,
            "generated_at": generated_at,
            "study": {
                "name": f"{study_name} Model Prep Report",
                "workspace_dir": str(ctx["root"]),
                "primary_gauge_id": site_id,
                "study_type": "usgs_gauge_model_prep",
                "git_commit": None,
            },
            "artifacts": {
                "report_json": UsgsModelPrepReport._relative_path(ctx["root"], report_json_path),
                "data_gap_analysis": UsgsModelPrepReport._relative_path(ctx["root"], gap_analysis_path),
                "observed_data_manifest": UsgsModelPrepReport._relative_path(
                    ctx["root"], ctx["paths"]["manifest_path"]
                ),
                "observed_data_report": UsgsModelPrepReport._relative_path(
                    ctx["root"], ctx["paths"]["report_path"]
                ),
                "observed_data_gap_analysis": UsgsModelPrepReport._relative_path(
                    ctx["root"], ctx["paths"]["data_gap_analysis_path"]
                ),
                "geometry_handoff": validation["geometry_handoff"].get("artifact_path"),
            },
            "gauge": {
                "site_id": site_id,
                "station_name": ctx["metadata"].get("station_name"),
                "available_parameters": ctx["metadata"].get("available_parameters", []),
                "observed_dataset_count": len(inventory),
                "observed_datasets_ok": validation["observed_data_package"]["datasets_ok"],
                "empty_dataset_ids": validation["observed_data_package"]["empty_dataset_ids"],
            },
            "basin": {
                "drainage_area_comparison": validation["drainage_area_comparison"],
            },
            "provenance": {
                "source_package_type": ctx["manifest"].get("package_type"),
                "source_schema_version": ctx["manifest"].get("schema_version"),
                "source_report_generated_at": ctx["report"].get("generated_at_utc"),
            },
            "validation": validation,
            "data_gaps": {
                "count": gap_analysis.get("gap_count", 0),
                "ids": [gap["id"] for gap in gap_analysis.get("gaps", [])],
            },
        }

    @staticmethod
    @log_call
    def write_report_package(
        study_package_or_root: Union[str, Path, Mapping[str, Any]],
        output_dir: Optional[Union[str, Path]] = None,
        drainage_area_comparison: Optional[Mapping[str, Any]] = None,
        geometry_handoff: Optional[Union[str, Path, Mapping[str, Any]]] = None,
        issue_urls: Optional[Mapping[str, Optional[str]]] = None,
    ) -> Dict[str, Path]:
        """Write model-prep ``report.json`` and ``data_gap_analysis.json`` outputs."""
        ctx = UsgsModelPrepReport._load_study_context(study_package_or_root)
        output_root = Path(output_dir) if output_dir else ctx["root"] / "model_prep"
        output_root.mkdir(parents=True, exist_ok=True)

        generated_at = UsgsGaugeStudy._utc_now_iso()
        gap_path = output_root / "data_gap_analysis.json"
        report_path = output_root / "report.json"

        gap_analysis = UsgsModelPrepReport.build_gap_analysis(
            ctx,
            drainage_area_comparison=drainage_area_comparison,
            geometry_handoff=geometry_handoff,
            issue_urls=issue_urls,
            generated_at=generated_at,
        )
        report_json = UsgsModelPrepReport.build_report_json(
            ctx,
            drainage_area_comparison=drainage_area_comparison,
            geometry_handoff=geometry_handoff,
            gap_analysis=gap_analysis,
            generated_at=generated_at,
            report_json_path=report_path,
            gap_analysis_path=gap_path,
        )

        UsgsGaugeStudy._write_json(gap_path, gap_analysis)
        UsgsGaugeStudy._write_json(report_path, report_json)

        return {
            "report_json": report_path,
            "data_gap_analysis": gap_path,
        }
