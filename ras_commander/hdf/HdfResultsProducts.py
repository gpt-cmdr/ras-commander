"""Inspection and deterministic products for completed HEC-RAS result HDFs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Union

import h5py
import numpy as np
import pandas as pd

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from ..RasUtils import RasUtils
from .HdfBase import HdfBase
from .HdfResultsMesh import HdfResultsMesh
from .HdfResultsPlan import HdfResultsPlan
from .HdfUtils import HdfUtils

logger = get_logger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(
            _json_value(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [_json_value(record) for record in frame.to_dict(orient="records")]


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
    _COMPLETE_PROCESS_LINE = re.compile(
        r"^Complete Process(?:\s+(?:(?:\d+\s*:\s*)+\d+|\d+(?:\.\d+)?[xX]?))?\s*$"
    )

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

        timestamp_ns = timestamp_index.to_numpy(
            dtype="datetime64[ns]"
        ).astype("int64")
        intervals = np.diff(timestamp_ns).astype(float) / 1e9
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
    @log_call
    @standardize_input(file_type="plan_hdf")
    def export(
        hdf_path: Union[str, Path],
        output_directory: Union[str, Path],
        *,
        resolution: float | None = None,
        max_dimension: int = 2048,
        nodata: float = -9999.0,
        include_preview: bool = True,
    ) -> dict[str, Any]:
        """Generate a deterministic hydraulic product package.

        The source is an existing HEC-RAS producer HDF opened read-only. The
        COG, Parquet, GeoJSON, JSON, and optional PNG files are newly generated
        ras-commander product artifacts; they are not HEC-RAS model output.
        The source digest is checked before and after inspection, rendering,
        and publication.

        The output directory must not exist. It is claimed atomically, assets
        are hard-linked from a same-parent staging directory without
        overwriting names, and the checksum-pinned manifest is published last.
        Consumers must treat the package as complete only when
        :attr:`MANIFEST_FILENAME` exists.

        Args:
            hdf_path: Completed HEC-RAS unsteady plan-result HDF.
            output_directory: New directory for the generated product package.
            resolution: Optional raster cell size in model CRS units.
            max_dimension: Maximum raster width and height. Defaults to 2048;
                total raster cells are also bounded for memory safety.
            nodata: Finite float32 nodata value for all three COGs. Inputs are
                normalized to the value that will actually be stored.
            include_preview: Generate ``maximum-depth-preview.png``.

        Returns:
            The JSON-serializable manifest also written to the package.

        Raises:
            FileNotFoundError: If the source HDF does not exist.
            FileExistsError: If the output directory already exists or is
                claimed concurrently.
            ValueError: If inputs, the result HDF, spatial support, or rendered
                metadata are invalid or inconsistent.
            RuntimeError: If the source changes, asset verification fails, or
                publication cannot preserve the no-overwrite contract.
            OSError: If source reads, staging, hard links, or publication fail.
        """
        source = RasUtils.safe_resolve(Path(hdf_path))
        raw_output = Path(output_directory)
        if raw_output.name in {"", ".", ".."}:
            raise ValueError("output_directory must name a new child directory")
        output_parent = RasUtils.safe_resolve(raw_output.parent)
        output = output_parent / raw_output.name
        if (
            output.exists()
            or output.is_symlink()
            or HdfResultsProducts._is_reparse_point(output)
        ):
            raise FileExistsError(
                f"Hydraulic product directory already exists: {output}"
            )
        resolution_value = HdfResultsProducts._optional_positive_float(
            resolution,
            label="resolution",
        )
        if isinstance(max_dimension, bool) or not isinstance(
            max_dimension,
            Integral,
        ):
            raise ValueError("max_dimension must be an integer")
        max_dimension_value = int(max_dimension)
        if max_dimension_value < 64:
            raise ValueError("max_dimension must be at least 64")
        nodata_value = HdfResultsProducts._finite_float32(
            nodata,
            label="nodata",
        )
        if not isinstance(include_preview, bool):
            raise ValueError("include_preview must be True or False")

        source_hash = _sha256(source)
        source_size = source.stat().st_size
        inspection = HdfResultsProducts.inspect_result(source)
        HdfResultsProducts._require_unchanged_source(
            source,
            expected_size=source_size,
            expected_hash=source_hash,
            checkpoint="after inspection",
        )
        output_parent.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any]
        published = False
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}-",
            dir=output_parent,
        ) as stage_name:
            stage = Path(stage_name)
            manifest = HdfResultsProducts._build_products(
                source,
                stage,
                inspection,
                source_size=source_size,
                source_hash=source_hash,
                resolution=resolution_value,
                max_dimension=max_dimension_value,
                nodata=nodata_value,
                include_preview=include_preview,
            )
            _write_json(stage / HdfResultsProducts.MANIFEST_FILENAME, manifest)
            HdfResultsProducts._validate_package(stage, manifest)
            HdfResultsProducts._require_unchanged_source(
                source,
                expected_size=source_size,
                expected_hash=source_hash,
                checkpoint="after rendering",
            )
            HdfResultsProducts._publish_package(stage, output, manifest)
            published = True
            try:
                HdfResultsProducts._validate_package(output, manifest)
                HdfResultsProducts._require_unchanged_source(
                    source,
                    expected_size=source_size,
                    expected_hash=source_hash,
                    checkpoint="after publication",
                )
            except Exception:
                HdfResultsProducts._cleanup_published_package(
                    stage,
                    output,
                    manifest,
                )
                published = False
                raise

        if not published:
            raise RuntimeError("Hydraulic product package was not published")
        logger.info(
            "Generated ras-commander hydraulic product package '%s' from "
            "existing HEC-RAS result '%s' read-only; no HEC-RAS model output "
            "was created or modified; hydraulic QA/QC not evaluated",
            output.name,
            source.name,
        )
        return manifest

    @staticmethod
    def _build_products(
        source: Path,
        stage: Path,
        inspection: dict[str, Any],
        *,
        source_size: int,
        source_hash: str,
        resolution: float | None,
        max_dimension: int,
        nodata: float,
        include_preview: bool,
    ) -> dict[str, Any]:
        from pyproj import CRS

        from ._HdfResultsProductRenderers import _ProductRenderers

        mesh_areas = _ProductRenderers.mesh_areas(source, inspection)
        expected_crs = CRS.from_user_input(inspection["crs"])
        if CRS.from_user_input(mesh_areas.crs) != expected_crs:
            raise ValueError("2D mesh footprint CRS differs from inspected CRS")
        bbox = tuple(float(value) for value in mesh_areas.total_bounds)
        grid = _ProductRenderers.grid_spec(
            bbox,
            resolution=resolution,
            max_dimension=max_dimension,
        )

        depth = HdfResultsMesh.get_mesh_max_depth(source)
        HdfResultsProducts._validate_product_frame(
            depth,
            value_column="maximum_depth",
            label="maximum depth",
            inspection=inspection,
            expected_crs=expected_crs,
        )
        finite_depth = depth["maximum_depth"].to_numpy(dtype=float)
        if np.any(np.isfinite(finite_depth) & (finite_depth < 0.0)):
            raise ValueError("Maximum depth contains finite negative values")

        depth_grid, support = _ProductRenderers.rasterize_points_by_mesh(
            depth,
            "maximum_depth",
            mesh_areas,
            grid,
        )
        wet_mask = support & np.isfinite(depth_grid) & (depth_grid > 0.0)
        assets: dict[str, Any] = {}

        depth_path = stage / HdfResultsProducts.FILENAMES["maximum-depth"]
        rendered_depth = _ProductRenderers.apply_masks(
            depth_grid,
            support,
            wet_mask=None,
            nodata=nodata,
        )
        _ProductRenderers.write_cog(
            depth_path,
            rendered_depth,
            grid,
            crs=inspection["crs"],
            nodata=nodata,
            units=inspection["depth_units"],
            product_key="maximum-depth",
            derivation=(
                "maximum stored Depth or Water Surface minus Cells Minimum "
                "Elevation"
            ),
        )
        del rendered_depth
        assets["maximum-depth"] = _ProductRenderers.raster_asset(
            depth_path,
            units=inspection["depth_units"],
        )
        del depth, depth_grid, finite_depth

        sequential_rasters = {
            "maximum-wse": (
                HdfResultsMesh.get_mesh_max_ws,
                "maximum_water_surface",
                "maximum WSE",
                inspection["length_units"],
                "HEC-RAS Maximum Water Surface summary; ever-dry cells are nodata",
            ),
            "maximum-velocity": (
                lambda path: _ProductRenderers.maximum_velocity_points(
                    path,
                    inspection,
                ),
                "maximum_velocity",
                "maximum velocity",
                inspection["velocity_units"],
                "maximum absolute adjacent-face velocity across time",
            ),
        }
        for key, (
            reader,
            column,
            label,
            units,
            derivation,
        ) in sequential_rasters.items():
            frame = reader(source)
            HdfResultsProducts._validate_product_frame(
                frame,
                value_column=column,
                label=label,
                inspection=inspection,
                expected_crs=expected_crs,
            )
            values, value_support = _ProductRenderers.rasterize_points_by_mesh(
                frame,
                column,
                mesh_areas,
                grid,
            )
            if not np.array_equal(value_support, support):
                raise RuntimeError(
                    f"Raster support changed while rendering {key}"
                )
            rendered = _ProductRenderers.apply_masks(
                values,
                value_support,
                wet_mask=wet_mask,
                nodata=nodata,
            )
            path = stage / HdfResultsProducts.FILENAMES[key]
            _ProductRenderers.write_cog(
                path,
                rendered,
                grid,
                crs=inspection["crs"],
                nodata=nodata,
                units=units,
                product_key=key,
                derivation=derivation,
            )
            del rendered
            assets[key] = _ProductRenderers.raster_asset(path, units=units)
            del frame, values

        hydrograph_path = (
            stage / HdfResultsProducts.FILENAMES["hydraulic-hydrographs"]
        )
        hydrograph_metadata = _ProductRenderers.write_hydrographs(
            source,
            hydrograph_path,
        )
        assets["hydraulic-hydrographs"] = _ProductRenderers.file_asset(
            hydrograph_path,
            media_type="application/vnd.apache.parquet",
            roles=["data", "hydrograph"],
            extra={"table": hydrograph_metadata},
        )

        metadata = HdfResultsProducts._result_metadata(
            source,
            inspection,
            bbox,
            source_size=source_size,
            source_hash=source_hash,
        )
        metadata_path = stage / HdfResultsProducts.FILENAMES["result-metadata"]
        _write_json(metadata_path, metadata)
        assets["result-metadata"] = _ProductRenderers.file_asset(
            metadata_path,
            media_type="application/json",
            roles=["metadata"],
        )

        numerical_qaqc = HdfResultsProducts._numerical_qaqc(source)
        qaqc_path = stage / HdfResultsProducts.FILENAMES["numerical-qaqc"]
        _write_json(qaqc_path, numerical_qaqc)
        assets["numerical-qaqc"] = _ProductRenderers.file_asset(
            qaqc_path,
            media_type="application/json",
            roles=["metadata", "quality"],
        )

        footprint_path = stage / HdfResultsProducts.FILENAMES["result-footprint"]
        footprint_metadata = _ProductRenderers.write_footprint(
            footprint_path,
            mesh_areas,
            source_name=source.name,
        )
        assets["result-footprint"] = _ProductRenderers.file_asset(
            footprint_path,
            media_type="application/geo+json",
            roles=["metadata", "footprint"],
            extra={
                "bbox": footprint_metadata["bbox_wgs84"],
                "proj:bbox": list(bbox),
                "proj:code": inspection["crs"],
                "feature_count": footprint_metadata["feature_count"],
            },
        )

        omissions: list[dict[str, str]] = []
        if include_preview:
            preview_path = stage / HdfResultsProducts.FILENAMES["preview"]
            _ProductRenderers.write_preview(
                stage / HdfResultsProducts.FILENAMES["maximum-depth"],
                preview_path,
                units=inspection["depth_units"],
            )
            assets["preview"] = _ProductRenderers.file_asset(
                preview_path,
                media_type="image/png",
                roles=["overview", "visual"],
            )
        else:
            omissions.append(
                {"asset_key": "preview", "reason": "disabled_by_request"}
            )

        manifest = {
            "schema": HdfResultsProducts.SCHEMA,
            "source": {
                "href": source.name,
                "size_bytes": source_size,
                "sha256": source_hash,
                "producer": "HEC-RAS",
                "access": "read_only",
                "roles": ["source", "engineering-result"],
            },
            "product_package": {
                "generated_by": "ras-commander",
                "artifact_type": "derived_hydraulic_products",
                "hec_ras_model_output_generated": False,
            },
            "status": {
                "completed_successfully": True,
                "time_axis_consistent": True,
                "hydraulic_qaqc": "not_evaluated",
            },
            "completion_evidence": inspection["completion_evidence"],
            "time": inspection["time"],
            "spatial": {
                "crs": inspection["crs"],
                "bbox": list(bbox),
                "footprint_asset": "result-footprint",
                "support": "2d_flow_area_footprints",
            },
            "assets": dict(sorted(assets.items())),
            "omissions": omissions,
        }
        for asset in manifest["assets"].values():
            _ProductRenderers.validate_asset(stage, asset)
        return _json_value(manifest)

    @staticmethod
    def _validate_product_frame(
        frame,
        *,
        value_column: str,
        label: str,
        inspection: dict[str, Any],
        expected_crs,
    ) -> None:
        from pyproj import CRS

        required = {"mesh_name", "cell_id", value_column, "geometry"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                f"{label} output is missing columns: {sorted(missing)}"
            )
        if frame.empty or frame.crs is None:
            raise ValueError(f"{label} output is empty or has no CRS")
        if CRS.from_user_input(frame.crs) != expected_crs:
            raise ValueError(f"{label} output CRS differs from inspected CRS")
        if frame.duplicated(["mesh_name", "cell_id"]).any():
            raise ValueError(f"{label} output contains duplicate mesh/cell IDs")

        expected_names = set(inspection["mesh_names"])
        actual_names = set(frame["mesh_name"].astype(str))
        if actual_names != expected_names:
            raise ValueError(
                f"{label} mesh names differ from inspection: expected "
                f"{sorted(expected_names)}, got {sorted(actual_names)}"
            )
        for mesh in inspection["meshes"]:
            mesh_name = mesh["mesh_name"]
            cell_count = int(mesh["cell_count"])
            subset = frame.loc[frame["mesh_name"] == mesh_name].sort_values(
                "cell_id",
                kind="stable",
            )
            cell_ids = subset["cell_id"].to_numpy(dtype=np.int64)
            if len(subset) != cell_count or not np.array_equal(
                cell_ids,
                np.arange(cell_count, dtype=np.int64),
            ):
                raise ValueError(
                    f"{label} rows do not align with mesh '{mesh_name}'"
                )
            values = pd.to_numeric(subset[value_column], errors="coerce")
            if not np.isfinite(values.to_numpy(dtype=float)).any():
                raise ValueError(
                    f"{label} contains no finite values for mesh '{mesh_name}'"
                )
            geometry = subset.geometry
            if (
                geometry.isna().any()
                or geometry.is_empty.any()
                or not np.isfinite(geometry.x.to_numpy(dtype=float)).all()
                or not np.isfinite(geometry.y.to_numpy(dtype=float)).all()
            ):
                raise ValueError(
                    f"{label} contains invalid cell points for mesh '{mesh_name}'"
                )

    @staticmethod
    def _result_metadata(
        source: Path,
        inspection: dict[str, Any],
        bbox: tuple[float, float, float, float],
        *,
        source_size: int,
        source_hash: str,
    ) -> dict[str, Any]:
        return {
            "schema": "ras-commander/result-hdf-metadata/1.0",
            "source": {
                "href": source.name,
                "size_bytes": source_size,
                "sha256": source_hash,
                "producer": "HEC-RAS",
                "access": "read_only",
            },
            "product_artifacts": {
                "generated_by": "ras-commander",
                "hec_ras_model_output_generated": False,
            },
            "completion": {
                "completed_successfully": inspection[
                    "completed_successfully"
                ],
                "time_axis_consistent": inspection["time_axis_consistent"],
                "evidence": inspection["completion_evidence"],
            },
            "time": inspection["time"],
            "spatial": {
                "crs": inspection["crs"],
                "bbox": [float(value) for value in bbox],
                "mesh_names": inspection["mesh_names"],
                "meshes": inspection["meshes"],
            },
            "units": {
                "system": inspection["unit_system"],
                "length": inspection["length_units"],
                "depth": inspection["depth_units"],
                "velocity": inspection["velocity_units"],
            },
            "program_version": inspection["program_version"],
            "checked_datasets": inspection["checked_datasets"],
            "derivations": {
                "maximum-wse": "HEC-RAS Maximum Water Surface summary",
                "maximum-depth": (
                    "maximum stored Depth or Water Surface minus Cells Minimum "
                    "Elevation, clipped at zero"
                ),
                "maximum-velocity": (
                    "maximum absolute adjacent-face velocity across time"
                ),
                "hydraulic-hydrographs": (
                    "available HEC-RAS boundary Flow and Stage series serialized "
                    "with required-core pyarrow; an empty schema-correct table is "
                    "generated when the producer HDF has no boundary series"
                ),
            },
        }

    @staticmethod
    def _numerical_qaqc(source: Path) -> dict[str, Any]:
        unsteady_summary = HdfResultsPlan.get_unsteady_summary(source)
        volume_accounting = HdfResultsPlan.get_volume_accounting(source)
        with h5py.File(source, "r") as hdf_file:
            messages = HdfResultsProducts._dataset_text(
                hdf_file.get(HdfResultsProducts._COMPUTE_MESSAGES_PATH)
            )
            maximum_wse_error = HdfResultsProducts._mesh_wse_error_summary(
                hdf_file
            )

        patterns = {
            "ignored_boundary": r"not used because",
            "precipitation_out_of_bounds": r"out-of-bounds",
            "maximum_iteration": r"maximum iteration",
            "volume_accounting": r"volume accounting",
            "wsel_error": r"(?:wsel|water surface).*error",
        }
        message_lines = [line.strip() for line in messages.splitlines()]
        iteration_counts = []
        for line in message_lines:
            match = re.match(
                r"^\d{2}[A-Za-z]{3}\d{4}\s+\d{2}:\d{2}:\d{2}"
                r".*\s(\d+)\s*$",
                line,
            )
            if match:
                iteration_counts.append(int(match.group(1)))
        findings: dict[str, Any] = {}
        for key, pattern in patterns.items():
            matches = [
                line
                for line in message_lines
                if line and re.search(pattern, line, flags=re.IGNORECASE)
            ]
            findings[key] = {
                "count": len(matches),
                "messages": list(dict.fromkeys(matches)),
            }

        return {
            "schema": "ras-commander/numerical-qaqc-summary/1.0",
            "acceptance": "not_evaluated",
            "unsteady_summary": _frame_records(unsteady_summary),
            "volume_accounting": _frame_records(volume_accounting),
            "mesh": {
                "maximum_iterations_observed": {
                    "maximum": max(iteration_counts) if iteration_counts else None,
                    "reported_row_count": len(iteration_counts),
                    "source": "embedded HEC-RAS compute messages",
                },
                "maximum_water_surface_error": maximum_wse_error,
            },
            "compute_message_findings": findings,
            "compute_message_sha256": hashlib.sha256(
                messages.encode("utf-8")
            ).hexdigest(),
            "compute_message_source": "embedded_hdf_only",
        }

    @staticmethod
    def _mesh_wse_error_summary(hdf_file: h5py.File) -> dict[str, Any]:
        attributes = hdf_file.get("Geometry/2D Flow Areas/Attributes")
        if attributes is None:
            return {
                "row_count": 0,
                "maximum": None,
                "datasets": [],
                "missing_meshes": [],
            }
        row_count = 0
        maximum: float | None = None
        datasets = []
        missing_meshes = []
        for row in attributes[:]:
            mesh_name = HdfUtils.convert_ras_string(row[0])
            path = (
                f"{HdfResultsProducts._SUMMARY_BASE}/2D Flow Areas/"
                f"{mesh_name}/Cell Maximum Water Surface Error"
            )
            dataset = hdf_file.get(path)
            if not isinstance(dataset, h5py.Dataset):
                missing_meshes.append(mesh_name)
                continue
            if not np.issubdtype(dataset.dtype, np.number) or not (
                dataset.ndim == 1
                or (dataset.ndim == 2 and dataset.shape[0] == 2)
            ):
                raise ValueError(
                    f"Maximum water-surface error dataset is invalid: {path}"
                )
            datasets.append(path)
            value_count = int(dataset.shape[-1])
            row_count += value_count
            chunk_size = max(1, min(1_000_000, value_count))
            for start in range(0, value_count, chunk_size):
                selection = (
                    slice(start, start + chunk_size)
                    if dataset.ndim == 1
                    else (0, slice(start, start + chunk_size))
                )
                values = np.asarray(dataset[selection], dtype=float)
                finite = values[np.isfinite(values)]
                if finite.size:
                    chunk_maximum = float(np.max(finite))
                    maximum = (
                        chunk_maximum
                        if maximum is None
                        else max(maximum, chunk_maximum)
                    )
        return {
            "row_count": row_count,
            "maximum": maximum,
            "datasets": datasets,
            "missing_meshes": missing_meshes,
        }

    @staticmethod
    def _validate_package(
        directory: Path,
        manifest: dict[str, Any],
    ) -> None:
        from ._HdfResultsProductRenderers import _ProductRenderers

        manifest_path = directory / HdfResultsProducts.MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise RuntimeError("Hydraulic product manifest is missing")
        reopened_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if reopened_manifest != _json_value(manifest):
            raise RuntimeError("Hydraulic product manifest readback changed")

        assets = manifest.get("assets")
        if not isinstance(assets, dict) or not assets:
            raise RuntimeError("Hydraulic product manifest contains no assets")
        expected_files = {HdfResultsProducts.MANIFEST_FILENAME}
        for key, asset in assets.items():
            if key not in HdfResultsProducts.FILENAMES:
                raise RuntimeError(f"Unknown hydraulic product asset key: {key}")
            if not isinstance(asset, dict):
                raise RuntimeError(f"Invalid hydraulic product asset: {key}")
            expected_href = HdfResultsProducts.FILENAMES[key]
            href = asset.get("href")
            if href != expected_href or Path(str(href)).name != href:
                raise RuntimeError(
                    f"Hydraulic product asset has an unsafe or unstable href: {key}"
                )
            if href in expected_files:
                raise RuntimeError(f"Duplicate hydraulic product href: {href}")
            expected_files.add(href)
            _ProductRenderers.validate_asset(directory, asset)

        actual_files = {
            path.name for path in directory.iterdir() if path.is_file()
        }
        if actual_files != expected_files:
            raise RuntimeError(
                "Hydraulic product package file set differs from manifest: "
                f"expected {sorted(expected_files)}, got {sorted(actual_files)}"
            )
        if any(path.is_dir() for path in directory.iterdir()):
            raise RuntimeError("Hydraulic product package contains a directory")

    @staticmethod
    def _publish_package(
        stage: Path,
        output: Path,
        manifest: dict[str, Any],
    ) -> None:
        output.mkdir(exist_ok=False)
        linked: list[str] = []
        try:
            assets = manifest["assets"]
            for asset in sorted(assets.values(), key=lambda item: item["href"]):
                href = asset["href"]
                os.link(stage / href, output / href)
                linked.append(href)
            manifest_name = HdfResultsProducts.MANIFEST_FILENAME
            os.link(stage / manifest_name, output / manifest_name)
            linked.append(manifest_name)
        except Exception:
            HdfResultsProducts._cleanup_linked_files(
                stage,
                output,
                linked,
            )
            raise

    @staticmethod
    def _cleanup_published_package(
        stage: Path,
        output: Path,
        manifest: dict[str, Any],
    ) -> None:
        names = [
            asset["href"] for asset in manifest.get("assets", {}).values()
        ]
        names.append(HdfResultsProducts.MANIFEST_FILENAME)
        HdfResultsProducts._cleanup_linked_files(stage, output, names)

    @staticmethod
    def _cleanup_linked_files(
        stage: Path,
        output: Path,
        names: list[str],
    ) -> None:
        for name in reversed(names):
            staged = stage / name
            published = output / name
            try:
                if (
                    staged.is_file()
                    and published.is_file()
                    and os.path.samefile(staged, published)
                ):
                    published.unlink()
            except OSError as exc:
                logger.warning(
                    "Could not remove incomplete generated product '%s': %s",
                    published,
                    exc,
                )
        try:
            output.rmdir()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning(
                "Incomplete hydraulic product directory remains at '%s': %s",
                output,
                exc,
            )

    @staticmethod
    def _require_unchanged_source(
        source: Path,
        *,
        expected_size: int,
        expected_hash: str,
        checkpoint: str,
    ) -> None:
        try:
            size = source.stat().st_size
            digest = _sha256(source)
        except OSError as exc:
            raise RuntimeError(
                f"Source result HDF cannot be verified {checkpoint}: {source}"
            ) from exc
        if size != expected_size or digest != expected_hash:
            raise RuntimeError(
                f"Source result HDF changed {checkpoint}: {source.name}"
            )

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        try:
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        except FileNotFoundError:
            return False
        marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(marker and attributes & marker)

    @staticmethod
    def _finite_float(value: Any, *, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{label} must be a finite real number")
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} must be a finite real number") from exc
        if not np.isfinite(numeric):
            raise ValueError(f"{label} must be a finite real number")
        return numeric

    @staticmethod
    def _optional_positive_float(value: Any, *, label: str) -> float | None:
        if value is None:
            return None
        numeric = HdfResultsProducts._finite_float(value, label=label)
        if numeric <= 0.0:
            raise ValueError(f"{label} must be greater than zero")
        return numeric

    @staticmethod
    def _finite_float32(value: Any, *, label: str) -> float:
        numeric = HdfResultsProducts._finite_float(value, label=label)
        limit = float(np.finfo(np.float32).max)
        if numeric < -limit or numeric > limit:
            raise ValueError(f"{label} must be representable as float32")
        return float(np.float32(numeric))

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
        message_complete = any(
            HdfResultsProducts._COMPLETE_PROCESS_LINE.fullmatch(line)
            is not None
            for line in message_text.splitlines()
        )

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
            candidate_seconds = (
                candidate.to_numpy(dtype="datetime64[ns]").astype("int64")
                // 1_000_000_000
            )
            primary_seconds = (
                primary.to_numpy(dtype="datetime64[ns]").astype("int64")
                // 1_000_000_000
            )
            if len(candidate) != len(primary) or not np.array_equal(
                candidate_seconds,
                primary_seconds,
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
            face_ids = np.asarray(face_values[:, 0], dtype=np.int64)
            if np.any(face_ids < 0) or np.any(face_ids >= face_count):
                raise ValueError(
                    f"Cell-face topology IDs are invalid for mesh '{mesh_name}'"
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
