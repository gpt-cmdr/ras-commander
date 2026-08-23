"""Inspection and deterministic products for completed HEC-RAS result HDFs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

import h5py
import numpy as np
import pandas as pd

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from ..RasUtils import RasUtils
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils

logger = get_logger(__name__)


class HdfResultsProducts:
    """Static namespace for deterministic hydraulic product packages."""

    SCHEMA = "ras-commander/hydraulic-product-manifest/1.0"
    INSPECTION_SCHEMA = "ras-commander/hydraulic-result-inspection/1.0"
    FILENAMES = {
        "maximum-wse": "maximum-wse.tif",
        "maximum-depth": "maximum-depth.tif",
        "maximum-velocity": "maximum-velocity.tif",
        "hydraulic-hydrographs": "hydraulic-hydrographs.parquet",
        "result-metadata": "result-metadata.json",
        "numerical-qaqc": "numerical-qaqc.json",
        "result-footprint": "result-footprint.geojson",
        "preview": "maximum-depth-preview.png",
    }
    MANIFEST_FILENAME = "hydraulic-products.json"

    _TIME_SERIES_BASE = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Unsteady Time Series"
    )
    _SUMMARY_BASE = (
        "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output"
    )
    _COMPUTE_MESSAGES_PATH = "Results/Summary/Compute Messages (text)"

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def inspect_result(hdf_path: Union[str, Path]) -> dict[str, Any]:
        """Inspect whether an HDF can support the hydraulic product contract.

        Completion is accepted from the current HEC-RAS
        ``Event Conditions/Completed Successfully=True`` attribute or, for
        older producer files that do not contain that attribute, an embedded
        compute-message ``Complete Process`` marker. An explicit false or
        malformed completion attribute is never overridden by messages.

        The method reads the existing result HDF without creating or changing
        any HDF dataset. It validates the time axes, embedded CRS and units,
        cell/face topology, and all mesh result arrays required by
        :meth:`export`.

        Args:
            hdf_path: Existing HEC-RAS unsteady plan-result HDF.

        Returns:
            A JSON-serializable inspection record. ``hydraulic_qaqc`` remains
            ``"not_evaluated"`` because mechanical completion and product
            readiness do not constitute engineering acceptance.

        Raises:
            FileNotFoundError: If ``hdf_path`` is not a file.
            ValueError: If completion evidence, time axes, CRS, units, mesh
                geometry, topology, or required result arrays are incomplete
                or inconsistent.
            OSError: If the HDF cannot be opened or read.
        """
        source = RasUtils.safe_resolve(Path(hdf_path))
        if not source.is_file():
            raise FileNotFoundError(f"Result HDF does not exist: {source}")
        source_size = source.stat().st_size
        if source_size <= 0:
            raise ValueError(f"Result HDF is empty: {source}")

        with h5py.File(source, "r") as hdf_file:
            completion = HdfResultsProducts._completion_evidence(hdf_file)
            timestamps, timestamp_datasets = HdfResultsProducts._time_axis(
                hdf_file
            )
            timestamp_index = pd.DatetimeIndex(timestamps)
            if len(timestamp_index) < 2:
                raise ValueError(
                    "Result HDF must contain at least two unsteady timestamps"
                )
            if not timestamp_index.is_monotonic_increasing:
                raise ValueError("Result HDF time axis is not increasing")
            if timestamp_index.has_duplicates:
                raise ValueError("Result HDF time axis contains duplicates")

            crs = HdfResultsProducts._embedded_crs(hdf_file, source)
            unit_metadata = HdfResultsProducts._unit_metadata(hdf_file)
            program_version = HdfResultsProducts._first_attribute(
                hdf_file,
                (
                    ("Results/Unsteady", "Program Version"),
                    ("", "Program Version"),
                    ("", "File Version"),
                ),
            )
            meshes, checked_datasets = HdfResultsProducts._inspect_meshes(
                hdf_file,
                timestamp_count=len(timestamp_index),
            )

        intervals = np.diff(timestamp_index.asi8).astype(float) / 1e9
        regular = bool(
            intervals.size > 0
            and np.allclose(intervals, intervals[0], rtol=0.0, atol=1e-6)
        )
        interval_seconds = float(intervals[0]) if regular else None
        mesh_names = [mesh["mesh_name"] for mesh in meshes]
        logger.info(
            "Inspected existing HEC-RAS result HDF '%s' read-only: %s mesh(es), "
            "%s timestamps; hydraulic QA/QC not evaluated",
            source.name,
            len(meshes),
            len(timestamp_index),
        )
        return {
            "schema": HdfResultsProducts.INSPECTION_SCHEMA,
            "source": {
                "href": source.name,
                "size_bytes": source_size,
                "producer": "HEC-RAS",
                "access": "read_only",
            },
            "completed_successfully": True,
            "completion_evidence": completion,
            "time_axis_consistent": True,
            "hydraulic_qaqc": "not_evaluated",
            "time": {
                "start": timestamp_index[0].isoformat(),
                "end": timestamp_index[-1].isoformat(),
                "count": len(timestamp_index),
                "regular": regular,
                "interval_seconds": interval_seconds,
                "datasets": timestamp_datasets,
            },
            "mesh_names": mesh_names,
            "meshes": meshes,
            "checked_datasets": checked_datasets,
            "crs": crs,
            "program_version": program_version,
            **unit_metadata,
        }

    @staticmethod
    def _completion_evidence(hdf_file: h5py.File) -> dict[str, Any]:
        event_conditions = hdf_file.get("Event Conditions")
        raw_attribute = (
            None
            if event_conditions is None
            else event_conditions.attrs.get("Completed Successfully")
        )
        attribute = HdfResultsProducts._optional_bool(
            raw_attribute,
            label="Event Conditions/Completed Successfully",
        )
        message_text = HdfResultsProducts._dataset_text(
            hdf_file.get(HdfResultsProducts._COMPUTE_MESSAGES_PATH)
        )
        message_complete = "Complete Process" in message_text

        if attribute is False:
            if message_complete:
                raise ValueError(
                    "Result HDF has conflicting completion evidence: "
                    "Completed Successfully=False but compute messages contain "
                    "Complete Process"
                )
            raise ValueError(
                "Result HDF reports Completed Successfully=False"
            )
        if attribute is None and not message_complete:
            raise ValueError(
                "Result HDF has no accepted completion evidence: expected "
                "Completed Successfully=True or an embedded Complete Process "
                "compute-message marker"
            )

        accepted_sources = []
        if attribute is True:
            accepted_sources.append("event_conditions_attribute")
        if message_complete:
            accepted_sources.append("embedded_compute_messages")
        return {
            "event_conditions_completed_successfully": attribute,
            "embedded_compute_messages_complete_process": message_complete,
            "accepted_sources": accepted_sources,
        }

    @staticmethod
    def _time_axis(
        hdf_file: h5py.File,
    ) -> tuple[list[pd.Timestamp], list[str]]:
        axes: dict[str, pd.DatetimeIndex] = {}
        specifications = (
            ("Time Date Stamp (ms)", HdfUtils.parse_ras_datetime_ms),
            ("Time Date Stamp", HdfUtils.parse_ras_datetime),
        )
        for name, parser in specifications:
            path = f"{HdfResultsProducts._TIME_SERIES_BASE}/{name}"
            dataset = hdf_file.get(path)
            if dataset is None:
                continue
            try:
                axes[path] = pd.DatetimeIndex(
                    [parser(HdfResultsProducts._decode(value)) for value in dataset[:]]
                )
            except Exception as exc:
                raise ValueError(
                    f"Could not parse result time dataset '{path}': {exc}"
                ) from exc

        if not axes:
            raise ValueError("Result HDF contains no unsteady timestamp dataset")
        paths = list(axes)
        primary = axes[paths[0]]
        for path in paths[1:]:
            candidate = axes[path]
            if len(candidate) != len(primary) or not np.array_equal(
                candidate.asi8 // 1_000_000_000,
                primary.asi8 // 1_000_000_000,
            ):
                raise ValueError(
                    "Result HDF timestamp datasets disagree: "
                    f"'{paths[0]}' versus '{path}'"
                )
        return list(primary), paths

    @staticmethod
    def _embedded_crs(hdf_file: h5py.File, source: Path) -> str:
        raw_projection = hdf_file.attrs.get("Projection")
        if raw_projection is None:
            raise ValueError(
                "Result HDF does not contain an embedded Projection attribute"
            )
        projection = HdfResultsProducts._decode(raw_projection).strip()
        if not projection:
            raise ValueError("Result HDF contains an empty Projection attribute")
        crs = HdfBase._wkt_to_crs_string(
            projection,
            f"HDF file {source.name}",
        )
        if not crs:
            raise ValueError("Result HDF Projection attribute is not resolvable")
        return str(crs)

    @staticmethod
    def _unit_metadata(hdf_file: h5py.File) -> dict[str, str]:
        candidates: list[tuple[str, bool]] = []
        geometry = hdf_file.get("Geometry")
        if geometry is not None and "SI Units" in geometry.attrs:
            candidates.append(
                (
                    "Geometry/SI Units",
                    HdfResultsProducts._required_bool(
                        geometry.attrs["SI Units"],
                        label="Geometry/SI Units",
                    ),
                )
            )

        if "Units System" in hdf_file.attrs:
            units_text = HdfResultsProducts._decode(
                hdf_file.attrs["Units System"]
            ).strip().casefold()
            if units_text.startswith("si") or units_text in {"metric"}:
                candidates.append(("Units System", True))
            elif units_text.startswith("us") or units_text in {
                "english",
                "imperial",
            }:
                candidates.append(("Units System", False))
            else:
                raise ValueError(
                    "Result HDF has an unrecognized Units System attribute: "
                    f"{units_text!r}"
                )

        if not candidates:
            raise ValueError(
                "Result HDF contains no recognized embedded unit-system metadata"
            )
        states = {state for _, state in candidates}
        if len(states) != 1:
            evidence = ", ".join(
                f"{label}={'SI' if state else 'US Customary'}"
                for label, state in candidates
            )
            raise ValueError(
                f"Result HDF unit-system metadata is contradictory: {evidence}"
            )
        si_units = states.pop()
        length = "m" if si_units else "ft"
        return {
            "unit_system": "SI" if si_units else "US Customary",
            "length_units": length,
            "depth_units": length,
            "velocity_units": "m/s" if si_units else "ft/s",
        }

    @staticmethod
    def _inspect_meshes(
        hdf_file: h5py.File,
        *,
        timestamp_count: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        attributes_path = "Geometry/2D Flow Areas/Attributes"
        attributes = hdf_file.get(attributes_path)
        if attributes is None or len(attributes) == 0:
            raise ValueError("Result HDF contains no 2D flow areas")

        meshes: list[dict[str, Any]] = []
        checked = [attributes_path]
        for row in attributes[:]:
            mesh_name = HdfUtils.convert_ras_string(row[0])
            declared_cell_count = int(row[-1])
            if not mesh_name or declared_cell_count <= 0:
                raise ValueError(
                    "Result HDF contains an invalid 2D flow-area attribute row"
                )

            geometry_base = f"Geometry/2D Flow Areas/{mesh_name}"
            series_base = (
                f"{HdfResultsProducts._TIME_SERIES_BASE}/2D Flow Areas/"
                f"{mesh_name}"
            )
            summary_base = (
                f"{HdfResultsProducts._SUMMARY_BASE}/2D Flow Areas/{mesh_name}"
            )
            centers_path = f"{geometry_base}/Cells Center Coordinate"
            centers = HdfResultsProducts._require_numeric_dataset(
                hdf_file,
                centers_path,
                minimum_columns=2,
            )
            cell_count = int(centers.shape[0])
            if cell_count <= 0 or declared_cell_count > cell_count:
                raise ValueError(
                    f"Declared Cell Count {declared_cell_count} is incompatible "
                    f"with {cell_count} result cell centers for mesh '{mesh_name}'"
                )
            checked.append(centers_path)

            wse_path = f"{series_base}/Water Surface"
            HdfResultsProducts._require_numeric_dataset(
                hdf_file,
                wse_path,
                shape=(timestamp_count, cell_count),
            )
            checked.append(wse_path)

            maximum_wse_path = f"{summary_base}/Maximum Water Surface"
            HdfResultsProducts._require_numeric_dataset(
                hdf_file,
                maximum_wse_path,
                shape=(2, cell_count),
            )
            checked.append(maximum_wse_path)

            depth_path = f"{series_base}/Depth"
            depth = hdf_file.get(depth_path)
            if depth is not None:
                HdfResultsProducts._validate_numeric_shape(
                    depth,
                    depth_path,
                    (timestamp_count, cell_count),
                )
                depth_source = "stored_depth"
                checked.append(depth_path)
            else:
                minimum_path = f"{geometry_base}/Cells Minimum Elevation"
                HdfResultsProducts._require_numeric_dataset(
                    hdf_file,
                    minimum_path,
                    shape=(cell_count,),
                )
                depth_source = "derived_water_surface_minus_minimum_elevation"
                checked.append(minimum_path)

            velocity_path = f"{series_base}/Face Velocity"
            velocity = hdf_file.get(velocity_path)
            if velocity is None or velocity.ndim != 2:
                raise ValueError(
                    f"Required result dataset is missing or not 2D: {velocity_path}"
                )
            if velocity.shape[0] != timestamp_count or velocity.shape[1] <= 0:
                raise ValueError(
                    f"Required result dataset has shape {velocity.shape}, expected "
                    f"({timestamp_count}, positive face count): {velocity_path}"
                )
            if not np.issubdtype(velocity.dtype, np.number):
                raise ValueError(
                    f"Required result dataset is not numeric: {velocity_path}"
                )
            face_count = int(velocity.shape[1])
            checked.append(velocity_path)

            face_info_path = f"{geometry_base}/Cells Face and Orientation Info"
            face_info = HdfResultsProducts._require_numeric_dataset(
                hdf_file,
                face_info_path,
                leading_shape=(cell_count,),
                minimum_columns=2,
                require_integer=True,
            )
            face_values_path = (
                f"{geometry_base}/Cells Face and Orientation Values"
            )
            face_values = HdfResultsProducts._require_numeric_dataset(
                hdf_file,
                face_values_path,
                minimum_columns=1,
                require_integer=True,
            )
            info = np.asarray(face_info[:, :2], dtype=np.int64)
            if np.any(info < 0) or np.any(info[:, 0] + info[:, 1] > len(face_values)):
                raise ValueError(
                    f"Cell-face topology offsets are invalid for mesh '{mesh_name}'"
                )
            checked.extend((face_info_path, face_values_path))

            if centers.shape[0] != len(info):
                raise ValueError(
                    f"Cell topology count does not align for mesh '{mesh_name}'"
                )
            meshes.append(
                {
                    "mesh_name": mesh_name,
                    "cell_count": cell_count,
                    "declared_cell_count": declared_cell_count,
                    "face_count": face_count,
                    "depth_source": depth_source,
                }
            )

        return meshes, checked

    @staticmethod
    def _require_numeric_dataset(
        hdf_file: h5py.File,
        path: str,
        *,
        shape: tuple[int, ...] | None = None,
        leading_shape: tuple[int, ...] | None = None,
        minimum_columns: int | None = None,
        require_integer: bool = False,
    ) -> h5py.Dataset:
        dataset = hdf_file.get(path)
        if not isinstance(dataset, h5py.Dataset):
            raise ValueError(f"Required HDF dataset is missing: {path}")
        HdfResultsProducts._validate_numeric_shape(
            dataset,
            path,
            shape,
            leading_shape=leading_shape,
            minimum_columns=minimum_columns,
            require_integer=require_integer,
        )
        return dataset

    @staticmethod
    def _validate_numeric_shape(
        dataset: h5py.Dataset,
        path: str,
        shape: tuple[int, ...] | None,
        *,
        leading_shape: tuple[int, ...] | None = None,
        minimum_columns: int | None = None,
        require_integer: bool = False,
    ) -> None:
        if not np.issubdtype(dataset.dtype, np.number):
            raise ValueError(f"Required HDF dataset is not numeric: {path}")
        if require_integer and not np.issubdtype(dataset.dtype, np.integer):
            raise ValueError(f"Required HDF dataset is not integer-valued: {path}")
        if shape is not None and dataset.shape != shape:
            raise ValueError(
                f"Required HDF dataset has shape {dataset.shape}, expected "
                f"{shape}: {path}"
            )
        if (
            leading_shape is not None
            and dataset.shape[: len(leading_shape)] != leading_shape
        ):
            raise ValueError(
                f"Required HDF dataset has shape {dataset.shape}, expected "
                f"leading shape {leading_shape}: {path}"
            )
        if minimum_columns is not None and (
            dataset.ndim != 2 or dataset.shape[1] < minimum_columns
        ):
            raise ValueError(
                f"Required HDF dataset has shape {dataset.shape}, expected at "
                f"least {minimum_columns} columns: {path}"
            )

    @staticmethod
    def _dataset_text(dataset: h5py.Dataset | h5py.Group | None) -> str:
        if not isinstance(dataset, h5py.Dataset):
            return ""
        raw = dataset[()]
        if isinstance(raw, np.ndarray):
            return "\n".join(
                HdfResultsProducts._decode(value) for value in raw.flat
            )
        return HdfResultsProducts._decode(raw)

    @staticmethod
    def _first_attribute(
        hdf_file: h5py.File,
        candidates: tuple[tuple[str, str], ...],
    ) -> str | None:
        for group_path, attribute in candidates:
            group = hdf_file if not group_path else hdf_file.get(group_path)
            if group is None:
                continue
            value = group.attrs.get(attribute)
            if value is not None and HdfResultsProducts._decode(value).strip():
                return HdfResultsProducts._decode(value).strip()
        return None

    @staticmethod
    def _required_bool(value: Any, *, label: str) -> bool:
        parsed = HdfResultsProducts._optional_bool(value, label=label)
        if parsed is None:
            raise ValueError(f"Required boolean metadata is absent: {label}")
        return parsed

    @staticmethod
    def _optional_bool(value: Any, *, label: str) -> bool | None:
        if value is None:
            return None
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer)) and int(value) in {0, 1}:
            return bool(value)
        text = HdfResultsProducts._decode(value).strip().casefold()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        raise ValueError(f"Unrecognized boolean metadata for {label}: {text!r}")

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, np.ndarray) and value.size == 1:
            return HdfResultsProducts._decode(value.flat[0])
        return str(value)
