"""Deterministic client-oriented products from a qualified RAS result HDF."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

import h5py
import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfMesh import HdfMesh
from .HdfProject import HdfProject
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
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(_json_value(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _frame_records(frame: Optional[pd.DataFrame]) -> list[Dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [_json_value(record) for record in frame.to_dict(orient="records")]


class HdfResultsProducts:
    """Static namespace for deterministic hydraulic product extraction."""

    SCHEMA = "ras-commander/hydraulic-product-manifest/1.0"
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

    @staticmethod
    @log_call
    def inspect_result(
        hdf_path: Union[str, Path],
    ) -> Dict[str, Any]:
        """Validate completion and required result time axes without mutation."""
        source = Path(hdf_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Result HDF does not exist: {source}")
        if source.stat().st_size <= 0:
            raise ValueError(f"Result HDF is empty: {source}")

        with h5py.File(source, "r") as hdf_file:
            event_conditions = hdf_file.get("Event Conditions")
            if event_conditions is None:
                raise ValueError("Event Conditions group is missing")
            completed = HdfResultsProducts._decode(
                event_conditions.attrs.get("Completed Successfully")
            )
            if str(completed).strip().casefold() != "true":
                raise ValueError(
                    "Result HDF does not report Completed Successfully=True"
                )

            timestamps = HdfBase.get_unsteady_timestamps(hdf_file)
            if len(timestamps) < 2:
                raise ValueError(
                    "Result HDF must contain at least two unsteady timestamps"
                )
            timestamp_index = pd.DatetimeIndex(timestamps)
            if not timestamp_index.is_monotonic_increasing:
                raise ValueError("Result HDF time axis is not increasing")
            if timestamp_index.has_duplicates:
                raise ValueError("Result HDF time axis contains duplicates")

            mesh_names = HdfMesh.get_mesh_area_names(hdf_file)
            if not mesh_names:
                raise ValueError("Result HDF contains no 2D flow areas")

            base = (
                "Results/Unsteady/Output/Output Blocks/Base Output/"
                "Unsteady Time Series"
            )
            checked_datasets: list[str] = []
            for mesh_name in mesh_names:
                for variable in ("Water Surface", "Face Velocity"):
                    dataset_path = (
                        f"{base}/2D Flow Areas/{mesh_name}/{variable}"
                    )
                    if dataset_path not in hdf_file:
                        raise ValueError(
                            f"Required result dataset is missing: {dataset_path}"
                        )
                    dataset = hdf_file[dataset_path]
                    if dataset.ndim != 2:
                        raise ValueError(
                            f"Required result dataset is not two-dimensional: "
                            f"{dataset_path}"
                        )
                    if dataset.shape[0] != len(timestamps):
                        raise ValueError(
                            f"Time-axis mismatch for {dataset_path}: "
                            f"{dataset.shape[0]} rows != {len(timestamps)} "
                            "timestamps"
                        )
                    checked_datasets.append(dataset_path)

            intervals = (
                timestamp_index.to_series(index=range(len(timestamp_index)))
                .diff()
                .dropna()
                .dt.total_seconds()
                .to_numpy(dtype=float)
            )
            regular = bool(np.allclose(intervals, intervals[0]))
            interval_seconds = (
                float(intervals[0]) if regular and len(intervals) else None
            )
            projection = HdfBase.get_projection(hdf_file)
            unit_metadata = HdfResultsProducts._unit_metadata(hdf_file)
            program_version = HdfResultsProducts._first_attribute(
                hdf_file,
                (
                    ("Results/Unsteady", "Program Version"),
                    ("", "Program Version"),
                    ("", "File Version"),
                ),
            )

        return {
            "completed_successfully": True,
            "time_axis_consistent": True,
            "time": {
                "start": timestamp_index[0].isoformat(),
                "end": timestamp_index[-1].isoformat(),
                "count": len(timestamp_index),
                "regular": regular,
                "interval_seconds": interval_seconds,
            },
            "mesh_names": mesh_names,
            "checked_datasets": checked_datasets,
            "crs": str(projection) if projection else None,
            "program_version": program_version,
            **unit_metadata,
        }

    @staticmethod
    @log_call
    def export(
        hdf_path: Union[str, Path],
        output_directory: Union[str, Path],
        *,
        resolution: Optional[float] = None,
        max_dimension: int = 2048,
        nodata: float = -9999.0,
        include_preview: bool = True,
    ) -> Dict[str, Any]:
        """Export a deterministic hydraulic product package.

        Args:
            hdf_path: Qualified HEC-RAS plan-result HDF.
            output_directory: New directory for the product package. It must
                not already exist.
            resolution: Optional raster cell size in model CRS units.
            max_dimension: Maximum raster width or height when resolution is
                inferred.
            nodata: Nodata value for all raster products.
            include_preview: Create a deterministic depth PNG when matplotlib
                is available.

        Returns:
            JSON-serializable hydraulic product manifest.

        Raises:
            ValueError: If completion, time axes, result variables, CRS, or
                product metadata are incomplete.
            FileExistsError: If the output directory already exists.
        """
        source = Path(hdf_path).resolve()
        output = Path(output_directory).resolve()
        if output.exists():
            raise FileExistsError(
                f"Hydraulic product directory already exists: {output}"
            )
        if max_dimension < 64:
            raise ValueError("max_dimension must be at least 64")
        if resolution is not None and resolution <= 0:
            raise ValueError("resolution must be positive")
        if not np.isfinite(nodata):
            raise ValueError("nodata must be finite")

        inspection = HdfResultsProducts.inspect_result(source)
        if not inspection["crs"]:
            raise ValueError("Result HDF does not contain a resolvable CRS")

        source_size = source.stat().st_size
        source_hash = _sha256(source)
        output.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}-",
            dir=output.parent,
        ) as stage_name:
            stage = Path(stage_name)
            manifest = HdfResultsProducts._build_products(
                source,
                stage,
                inspection,
                source_size=source_size,
                source_hash=source_hash,
                resolution=resolution,
                max_dimension=max_dimension,
                nodata=nodata,
                include_preview=include_preview,
            )
            current_size = source.stat().st_size
            current_hash = _sha256(source)
            if current_size != source_size or current_hash != source_hash:
                raise RuntimeError(
                    "Source result HDF changed during product extraction"
                )
            _write_json(stage / HdfResultsProducts.MANIFEST_FILENAME, manifest)
            stage.replace(output)

        logger.info(
            "Exported %s hydraulic products to %s",
            len(manifest["assets"]),
            output.name,
        )
        logger.debug("Hydraulic product directory: %s", output)
        return manifest

    @staticmethod
    def _build_products(
        source: Path,
        stage: Path,
        inspection: Dict[str, Any],
        *,
        source_size: int,
        source_hash: str,
        resolution: Optional[float],
        max_dimension: int,
        nodata: float,
        include_preview: bool,
    ) -> Dict[str, Any]:
        import geopandas as gpd
        from shapely.geometry import mapping

        footprint, bbox = HdfProject.get_project_extent(
            source,
            buffer_percent=0.0,
            fill_holes=False,
        )
        if footprint.empty or footprint.geometry.is_empty.all():
            raise ValueError("Result HDF produced an empty project footprint")
        footprint_geometry = footprint.geometry.union_all()
        if footprint_geometry.is_empty:
            raise ValueError("Result HDF produced an empty project footprint")

        wse = HdfResultsMesh.get_mesh_max_ws(source)
        depth = HdfResultsMesh.get_mesh_max_depth(source)
        velocity = HdfResultsProducts._maximum_velocity_points(source)
        required_frames = {
            "maximum WSE": wse,
            "maximum depth": depth,
            "maximum velocity": velocity,
        }
        for label, frame in required_frames.items():
            if frame.empty:
                raise ValueError(f"Result HDF produced no {label} values")
            if frame.crs is None:
                raise ValueError(f"Result HDF produced {label} without a CRS")

        depth = depth.copy()
        depth["maximum_depth"] = depth["maximum_depth"].clip(lower=0.0)
        wse = wse.merge(
            depth[["mesh_name", "cell_id", "maximum_depth"]],
            on=["mesh_name", "cell_id"],
            how="left",
            validate="one_to_one",
        )
        wse = gpd.GeoDataFrame(wse, geometry="geometry", crs=depth.crs)
        invalid_wse = (
            (wse["maximum_depth"] <= 0.0)
            | (wse["maximum_water_surface"] <= 0.0)
        )
        wse.loc[invalid_wse, "maximum_water_surface"] = np.nan

        grid = HdfResultsProducts._grid_spec(
            bbox,
            resolution=resolution,
            max_dimension=max_dimension,
        )
        depth_grid = HdfResultsProducts._interpolate_points(
            depth,
            "maximum_depth",
            grid,
        )
        wet_mask = np.isfinite(depth_grid) & (depth_grid > 0.0)

        raster_specs = {
            "maximum-wse": (
                wse,
                "maximum_water_surface",
                inspection["length_units"],
                "maximum cell water-surface elevation; dry cells are nodata",
            ),
            "maximum-depth": (
                depth,
                "maximum_depth",
                inspection["depth_units"],
                "maximum of stored Depth or WSE minus cell minimum elevation",
            ),
            "maximum-velocity": (
                velocity,
                "maximum_velocity",
                inspection["velocity_units"],
                "maximum absolute adjacent-face velocity across time",
            ),
        }
        assets: Dict[str, Any] = {}
        for key, (frame, column, units, derivation) in raster_specs.items():
            values = (
                depth_grid
                if key == "maximum-depth"
                else HdfResultsProducts._interpolate_points(frame, column, grid)
            )
            values = HdfResultsProducts._apply_masks(
                values,
                footprint_geometry,
                grid,
                wet_mask=wet_mask if key != "maximum-depth" else None,
                nodata=nodata,
            )
            raster_path = stage / HdfResultsProducts.FILENAMES[key]
            HdfResultsProducts._write_cog(
                raster_path,
                values,
                grid,
                crs=inspection["crs"],
                nodata=nodata,
                units=units,
                product_key=key,
                derivation=derivation,
            )
            assets[key] = HdfResultsProducts._raster_asset(
                raster_path,
                units=units,
            )

        hydrograph_path = (
            stage / HdfResultsProducts.FILENAMES["hydraulic-hydrographs"]
        )
        hydrograph_metadata = HdfResultsProducts._write_hydrographs(
            source,
            hydrograph_path,
        )
        assets["hydraulic-hydrographs"] = HdfResultsProducts._file_asset(
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
        assets["result-metadata"] = HdfResultsProducts._file_asset(
            metadata_path,
            media_type="application/json",
            roles=["metadata"],
        )

        qaqc = HdfResultsProducts._numerical_qaqc(source)
        qaqc_path = stage / HdfResultsProducts.FILENAMES["numerical-qaqc"]
        _write_json(qaqc_path, qaqc)
        assets["numerical-qaqc"] = HdfResultsProducts._file_asset(
            qaqc_path,
            media_type="application/json",
            roles=["metadata", "quality"],
        )

        footprint_payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "result-footprint",
                    "properties": {
                        "crs": inspection["crs"],
                        "source": source.name,
                    },
                    "geometry": mapping(footprint_geometry),
                }
            ],
        }
        footprint_path = stage / HdfResultsProducts.FILENAMES["result-footprint"]
        _write_json(footprint_path, footprint_payload)
        assets["result-footprint"] = HdfResultsProducts._file_asset(
            footprint_path,
            media_type="application/geo+json",
            roles=["metadata", "footprint"],
            extra={
                "proj:bbox": [float(value) for value in bbox],
                "proj:code": inspection["crs"],
            },
        )

        omissions: list[Dict[str, str]] = []
        if include_preview:
            preview_path = stage / HdfResultsProducts.FILENAMES["preview"]
            try:
                HdfResultsProducts._write_preview(
                    stage / HdfResultsProducts.FILENAMES["maximum-depth"],
                    preview_path,
                    units=inspection["depth_units"],
                )
                assets["preview"] = HdfResultsProducts._file_asset(
                    preview_path,
                    media_type="image/png",
                    roles=["overview", "visual"],
                )
            except ImportError as exc:
                omissions.append(
                    {
                        "asset_key": "preview",
                        "reason": f"renderer unavailable: {exc}",
                    }
                )

        return {
            "schema": HdfResultsProducts.SCHEMA,
            "source": {
                "href": source.name,
                "size_bytes": source_size,
                "sha256": source_hash,
                "roles": ["source", "engineering-result"],
            },
            "status": {
                "completed_successfully": inspection["completed_successfully"],
                "time_axis_consistent": inspection["time_axis_consistent"],
                "hydraulic_qaqc": "not_evaluated",
            },
            "time": inspection["time"],
            "spatial": {
                "crs": inspection["crs"],
                "bbox": [float(value) for value in bbox],
                "footprint_asset": "result-footprint",
            },
            "assets": dict(sorted(assets.items())),
            "omissions": omissions,
        }

    @staticmethod
    def _maximum_velocity_points(source: Path):
        import geopandas as gpd

        points = HdfMesh.get_mesh_cell_points(source)
        if points.empty:
            return gpd.GeoDataFrame(
                columns=[
                    "mesh_name",
                    "cell_id",
                    "maximum_velocity",
                    "geometry",
                ],
                geometry="geometry",
            )

        frames = []
        base = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series/2D Flow Areas"
        )
        with h5py.File(source, "r") as hdf_file:
            for mesh_name in HdfMesh.get_mesh_area_names(hdf_file):
                velocity_path = f"{base}/{mesh_name}/Face Velocity"
                info_path = (
                    f"Geometry/2D Flow Areas/{mesh_name}/"
                    "Cells Face and Orientation Info"
                )
                values_path = (
                    f"Geometry/2D Flow Areas/{mesh_name}/"
                    "Cells Face and Orientation Values"
                )
                for required in (velocity_path, info_path, values_path):
                    if required not in hdf_file:
                        raise ValueError(
                            f"Maximum velocity input is missing: {required}"
                        )

                face_timeseries = np.asarray(
                    hdf_file[velocity_path],
                    dtype=float,
                )
                finite_face = np.any(np.isfinite(face_timeseries), axis=0)
                maximum_face = np.full(face_timeseries.shape[1], np.nan)
                maximum_face[finite_face] = np.nanmax(
                    np.abs(face_timeseries[:, finite_face]),
                    axis=0,
                )

                cell_face_info = np.asarray(hdf_file[info_path])
                cell_face_values = np.asarray(hdf_file[values_path])[:, 0].astype(
                    int
                )
                maximum_cell = np.full(len(cell_face_info), np.nan)
                for cell_id, (start, count) in enumerate(
                    cell_face_info[:, :2]
                ):
                    face_ids = cell_face_values[start : start + count]
                    face_ids = face_ids[
                        (face_ids >= 0) & (face_ids < len(maximum_face))
                    ]
                    finite = maximum_face[face_ids]
                    finite = finite[np.isfinite(finite)]
                    if finite.size:
                        maximum_cell[cell_id] = float(np.max(finite))

                mesh_points = (
                    points[points["mesh_name"] == mesh_name]
                    .sort_values("cell_id")
                    .copy()
                )
                if len(mesh_points) != len(maximum_cell):
                    raise ValueError(
                        f"Velocity cell count mismatch for mesh '{mesh_name}': "
                        f"{len(maximum_cell)} values != {len(mesh_points)} "
                        "cell points"
                    )
                mesh_points["maximum_velocity"] = maximum_cell
                frames.append(
                    mesh_points[
                        ["mesh_name", "cell_id", "maximum_velocity", "geometry"]
                    ]
                )

        return gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True),
            geometry="geometry",
            crs=points.crs,
        )

    @staticmethod
    def _grid_spec(
        bbox: tuple[float, float, float, float],
        *,
        resolution: Optional[float],
        max_dimension: int,
    ) -> Dict[str, Any]:
        from rasterio.transform import from_bounds

        minx, miny, maxx, maxy = (float(value) for value in bbox)
        width = maxx - minx
        height = maxy - miny
        if width <= 0 or height <= 0:
            raise ValueError(f"Result footprint has invalid bounds: {bbox}")
        if resolution is None:
            resolution = max(width, height) / float(max_dimension)
        columns = max(2, int(np.ceil(width / resolution)))
        rows = max(2, int(np.ceil(height / resolution)))
        transform = from_bounds(minx, miny, maxx, maxy, columns, rows)
        return {
            "bbox": (minx, miny, maxx, maxy),
            "width": columns,
            "height": rows,
            "transform": transform,
            "resolution": (
                float(transform.a),
                float(abs(transform.e)),
            ),
        }

    @staticmethod
    def _interpolate_points(
        frame,
        value_column: str,
        grid: Dict[str, Any],
    ) -> np.ndarray:
        from scipy.spatial import cKDTree

        valid = (
            frame.geometry.notna()
            & ~frame.geometry.is_empty
            & np.isfinite(frame[value_column].to_numpy(dtype=float))
        )
        source = frame.loc[valid]
        if source.empty:
            raise ValueError(f"No finite values available for {value_column}")
        xy = np.column_stack(
            [
                source.geometry.x.to_numpy(dtype=float),
                source.geometry.y.to_numpy(dtype=float),
            ]
        )
        values = source[value_column].to_numpy(dtype=float)
        minx, miny, maxx, maxy = grid["bbox"]
        width = grid["width"]
        height = grid["height"]
        x_resolution, y_resolution = grid["resolution"]
        x = np.linspace(
            minx + x_resolution / 2.0,
            maxx - x_resolution / 2.0,
            width,
        )
        y = np.linspace(
            maxy - y_resolution / 2.0,
            miny + y_resolution / 2.0,
            height,
        )
        gx, gy = np.meshgrid(x, y)
        tree = cKDTree(xy)
        _, nearest = tree.query(np.column_stack([gx.ravel(), gy.ravel()]))
        return values[nearest].reshape((height, width)).astype(np.float32)

    @staticmethod
    def _apply_masks(
        values: np.ndarray,
        footprint,
        grid: Dict[str, Any],
        *,
        wet_mask: Optional[np.ndarray],
        nodata: float,
    ) -> np.ndarray:
        from rasterio.features import geometry_mask

        valid_footprint = geometry_mask(
            [footprint],
            out_shape=(grid["height"], grid["width"]),
            transform=grid["transform"],
            invert=True,
        )
        valid = valid_footprint & np.isfinite(values)
        if wet_mask is not None:
            valid &= wet_mask
        return np.where(valid, values, nodata).astype(np.float32)

    @staticmethod
    def _write_cog(
        path: Path,
        values: np.ndarray,
        grid: Dict[str, Any],
        *,
        crs: str,
        nodata: float,
        units: str,
        product_key: str,
        derivation: str,
    ) -> None:
        import rasterio

        with rasterio.open(
            path,
            "w",
            driver="COG",
            height=grid["height"],
            width=grid["width"],
            count=1,
            dtype="float32",
            crs=crs,
            transform=grid["transform"],
            nodata=nodata,
            compress="DEFLATE",
            blocksize=512,
            overview_resampling="average",
            num_threads=1,
            BIGTIFF="IF_SAFER",
        ) as destination:
            destination.write(values, 1)
            destination.update_tags(
                product_key=product_key,
                units=units,
                derivation=derivation,
            )

        with rasterio.open(path) as source:
            layout = source.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
            if layout != "COG":
                raise RuntimeError(
                    f"Raster driver did not produce a COG for {path.name}"
                )

    @staticmethod
    def _write_hydrographs(
        source: Path,
        path: Path,
    ) -> Dict[str, Any]:
        dataset = HdfResultsMesh.get_boundary_conditions_timeseries(source)
        required = {"flow", "stage"}
        missing = required - set(dataset.data_vars)
        if missing:
            raise ValueError(
                "Boundary hydrograph variables are missing: "
                + ", ".join(sorted(missing))
            )

        frames = []
        units_by_variable: Dict[str, list[str]] = {}
        for variable in ("flow", "stage"):
            frame = (
                dataset[variable]
                .to_dataframe(name="value")
                .reset_index()
            )
            frame.insert(2, "variable", variable)
            units_coordinate = f"{variable}_units"
            if units_coordinate in dataset.coords:
                unit_lookup = {
                    str(name): str(unit)
                    for name, unit in zip(
                        dataset["bc_name"].values,
                        dataset[units_coordinate].values,
                    )
                }
                frame["units"] = frame["bc_name"].map(unit_lookup)
            else:
                frame["units"] = ""
            if "area_2d" in dataset.coords:
                area_lookup = {
                    str(name): str(area)
                    for name, area in zip(
                        dataset["bc_name"].values,
                        dataset["area_2d"].values,
                    )
                }
                frame["area_2d"] = frame["bc_name"].map(area_lookup)
            else:
                frame["area_2d"] = ""
            frames.append(frame)
            units_by_variable[variable] = sorted(
                {
                    value
                    for value in frame["units"].astype(str)
                    if value.strip()
                }
            )

        table = pd.concat(frames, ignore_index=True)
        table = table[
            ["time", "bc_name", "variable", "value", "units", "area_2d"]
        ].sort_values(
            ["time", "bc_name", "variable"],
            kind="stable",
        )
        table.reset_index(drop=True, inplace=True)
        table.to_parquet(
            path,
            index=False,
            engine="pyarrow",
            compression="zstd",
        )
        return {
            "row_count": len(table),
            "columns": [
                {"name": "time", "type": "timestamp"},
                {"name": "bc_name", "type": "string"},
                {"name": "variable", "type": "string"},
                {"name": "value", "type": "float64"},
                {"name": "units", "type": "string"},
                {"name": "area_2d", "type": "string"},
            ],
            "variables": ["flow", "stage"],
            "units": units_by_variable,
            "missing_value_count": int(table["value"].isna().sum()),
            "time_start": pd.Timestamp(table["time"].min()).isoformat(),
            "time_end": pd.Timestamp(table["time"].max()).isoformat(),
        }

    @staticmethod
    def _result_metadata(
        source: Path,
        inspection: Dict[str, Any],
        bbox: tuple[float, float, float, float],
        *,
        source_size: int,
        source_hash: str,
    ) -> Dict[str, Any]:
        return {
            "schema": "ras-commander/result-hdf-metadata/1.0",
            "source": {
                "href": source.name,
                "size_bytes": source_size,
                "sha256": source_hash,
            },
            "completion": {
                "completed_successfully": inspection[
                    "completed_successfully"
                ],
                "time_axis_consistent": inspection["time_axis_consistent"],
            },
            "time": inspection["time"],
            "spatial": {
                "crs": inspection["crs"],
                "bbox": [float(value) for value in bbox],
                "mesh_names": inspection["mesh_names"],
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
                    "maximum stored Depth or Water Surface minus Cells "
                    "Minimum Elevation, clipped at zero"
                ),
                "maximum-velocity": (
                    "maximum absolute adjacent-face velocity across time"
                ),
            },
        }

    @staticmethod
    def _numerical_qaqc(source: Path) -> Dict[str, Any]:
        unsteady_summary = HdfResultsPlan.get_unsteady_summary(source)
        volume_accounting = HdfResultsPlan.get_volume_accounting(source)
        maximum_wse_error = HdfResultsMesh.get_mesh_max_ws_err(source)
        messages = HdfResultsPlan.get_compute_messages_hdf_only(source)

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
        findings: Dict[str, Any] = {}
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
                    "maximum": (
                        max(iteration_counts) if iteration_counts else None
                    ),
                    "reported_row_count": len(iteration_counts),
                    "source": "compute messages",
                },
                "maximum_water_surface_error": {
                    "row_count": len(maximum_wse_error),
                    "maximum": HdfResultsProducts._numeric_max(
                        maximum_wse_error,
                        "cell_maximum_water_surface_error",
                    ),
                },
            },
            "compute_message_findings": findings,
            "compute_message_sha256": hashlib.sha256(
                messages.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _numeric_max(frame: pd.DataFrame, column: str) -> Optional[float]:
        if frame.empty or column not in frame:
            return None
        values = pd.to_numeric(frame[column], errors="coerce")
        if not values.notna().any():
            return None
        return float(values.max())

    @staticmethod
    def _raster_asset(path: Path, *, units: str) -> Dict[str, Any]:
        import rasterio

        with rasterio.open(path) as source:
            band = source.read(1, masked=True)
            finite = band.compressed()
            asset = HdfResultsProducts._file_asset(
                path,
                media_type=(
                    "image/tiff; application=geotiff; "
                    "profile=cloud-optimized"
                ),
                roles=["data", "visual"],
                extra={
                    "proj:code": source.crs.to_string(),
                    "proj:bbox": [float(value) for value in source.bounds],
                    "proj:shape": [source.height, source.width],
                    "proj:transform": [
                        float(value) for value in source.transform[:6]
                    ],
                    "raster:bands": [
                        {
                            "data_type": source.dtypes[0],
                            "nodata": source.nodata,
                            "unit": units,
                            "spatial_resolution": float(abs(source.transform.a)),
                            "statistics": {
                                "minimum": (
                                    float(np.min(finite))
                                    if finite.size
                                    else None
                                ),
                                "maximum": (
                                    float(np.max(finite))
                                    if finite.size
                                    else None
                                ),
                            },
                        }
                    ],
                    "cog": {
                        "layout": source.tags(
                            ns="IMAGE_STRUCTURE"
                        ).get("LAYOUT"),
                        "overviews": source.overviews(1),
                    },
                },
            )
        return asset

    @staticmethod
    def _file_asset(
        path: Path,
        *,
        media_type: str,
        roles: list[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        asset = {
            "href": path.name,
            "type": media_type,
            "roles": roles,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if extra:
            asset.update(extra)
        return asset

    @staticmethod
    def _write_preview(
        depth_path: Path,
        preview_path: Path,
        *,
        units: str,
    ) -> None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import rasterio

        with rasterio.open(depth_path) as source:
            depth = source.read(1, masked=True)
            extent = (
                source.bounds.left,
                source.bounds.right,
                source.bounds.bottom,
                source.bounds.top,
            )
        figure, axis = plt.subplots(figsize=(10, 7), dpi=120)
        image = axis.imshow(
            depth,
            extent=extent,
            cmap="Blues",
            origin="upper",
        )
        axis.set_title("Maximum Depth")
        axis.set_xlabel("Model X")
        axis.set_ylabel("Model Y")
        colorbar = figure.colorbar(image, ax=axis, shrink=0.82)
        colorbar.set_label(f"Depth ({units})")
        figure.tight_layout()
        figure.savefig(
            preview_path,
            metadata={"Software": "ras-commander"},
        )
        plt.close(figure)

    @staticmethod
    def _unit_metadata(hdf_file: h5py.File) -> Dict[str, str]:
        geometry = hdf_file.get("Geometry")
        raw_si = (
            HdfResultsProducts._decode(geometry.attrs.get("SI Units"))
            if geometry is not None
            else None
        )
        raw_system = HdfResultsProducts._decode(
            hdf_file.attrs.get("Units System")
        )
        text = str(raw_system or "").strip().casefold()
        si_units = str(raw_si or "").strip().casefold() in {
            "true",
            "1",
            "yes",
            "si",
        } or text.startswith("si")
        length = "m" if si_units else "ft"
        return {
            "unit_system": "SI" if si_units else "US Customary",
            "length_units": length,
            "depth_units": length,
            "velocity_units": "m/s" if si_units else "ft/s",
        }

    @staticmethod
    def _first_attribute(
        hdf_file: h5py.File,
        candidates: tuple[tuple[str, str], ...],
    ) -> Optional[str]:
        for group_path, attribute in candidates:
            group = hdf_file if not group_path else hdf_file.get(group_path)
            if group is None:
                continue
            value = HdfResultsProducts._decode(group.attrs.get(attribute))
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _decode(value: Any) -> Any:
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, np.ndarray) and value.size == 1:
            return HdfResultsProducts._decode(value.flat[0])
        return value
