"""Private bounded-memory renderers for :mod:`HdfResultsProducts`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from .HdfMesh import HdfMesh
from .HdfResultsMesh import HdfResultsMesh


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


class _ProductRenderers:
    """Implementation-only product renderers behind the public facade."""

    MAX_RASTER_CELLS = 16_777_216

    @staticmethod
    def maximum_velocity_points(source: Path, inspection: dict[str, Any]):
        import geopandas as gpd

        points = HdfMesh.get_mesh_cell_points(source)
        if points.empty or points.crs is None:
            raise ValueError("Result HDF produced no CRS-aware mesh cell points")

        frames = []
        series_base = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series/2D Flow Areas"
        )
        with h5py.File(source, "r") as hdf_file:
            for mesh in inspection["meshes"]:
                mesh_name = mesh["mesh_name"]
                cell_count = int(mesh["cell_count"])
                face_count = int(mesh["face_count"])
                velocity_path = f"{series_base}/{mesh_name}/Face Velocity"
                geometry_base = f"Geometry/2D Flow Areas/{mesh_name}"
                info_path = (
                    f"{geometry_base}/Cells Face and Orientation Info"
                )
                values_path = (
                    f"{geometry_base}/Cells Face and Orientation Values"
                )
                maximum_face = _ProductRenderers.reduce_temporal_max_abs(
                    hdf_file[velocity_path]
                )
                if len(maximum_face) != face_count:
                    raise ValueError(
                        f"Velocity face count changed for mesh '{mesh_name}'"
                    )

                cell_face_info = np.asarray(
                    hdf_file[info_path][:, :2],
                    dtype=np.int64,
                )
                cell_face_ids = np.asarray(
                    hdf_file[values_path][:, 0],
                    dtype=np.int64,
                )
                if len(cell_face_info) != cell_count:
                    raise ValueError(
                        f"Velocity cell topology changed for mesh '{mesh_name}'"
                    )
                if np.any(cell_face_ids < 0) or np.any(
                    cell_face_ids >= face_count
                ):
                    raise ValueError(
                        f"Velocity topology has invalid face IDs for mesh "
                        f"'{mesh_name}'"
                    )

                maximum_cell = np.full(cell_count, np.nan, dtype=np.float32)
                for cell_id, (start, count) in enumerate(cell_face_info):
                    face_ids = cell_face_ids[start : start + count]
                    face_values = maximum_face[face_ids]
                    finite = face_values[np.isfinite(face_values)]
                    if finite.size:
                        maximum_cell[cell_id] = np.max(finite)

                mesh_points = points.loc[
                    points["mesh_name"] == mesh_name,
                    ["mesh_name", "cell_id", "geometry"],
                ].sort_values("cell_id")
                if len(mesh_points) != cell_count or not np.array_equal(
                    mesh_points["cell_id"].to_numpy(dtype=int),
                    np.arange(cell_count),
                ):
                    raise ValueError(
                        f"Velocity points do not align with mesh '{mesh_name}'"
                    )
                mesh_points = mesh_points.copy()
                mesh_points["maximum_velocity"] = maximum_cell
                frames.append(mesh_points)

        return gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True),
            geometry="geometry",
            crs=points.crs,
        )

    @staticmethod
    def reduce_temporal_max_abs(
        result_ds,
        *,
        max_chunk_bytes: int = 16 * 1024 * 1024,
        max_chunk_rows: int = 32,
    ) -> np.ndarray:
        """Return a temporal absolute maximum using slice-only HDF reads."""
        if result_ds.ndim != 2 or result_ds.shape[1] <= 0:
            raise ValueError(
                f"Velocity time series must be 2D with faces, got "
                f"{result_ds.shape}"
            )
        time_count, face_count = result_ds.shape
        itemsize = max(4, int(getattr(result_ds.dtype, "itemsize", 4)))
        maximum = np.full(face_count, np.nan, dtype=np.float32)
        column_chunk = max(1, max_chunk_bytes // itemsize)
        for column_start in range(0, face_count, column_chunk):
            column_stop = min(face_count, column_start + column_chunk)
            chunk_width = column_stop - column_start
            byte_limited_rows = max(
                1,
                max_chunk_bytes // (chunk_width * itemsize),
            )
            chunk_rows = max(1, min(max_chunk_rows, byte_limited_rows))
            column_selection = (
                slice(None)
                if column_start == 0 and column_stop == face_count
                else slice(column_start, column_stop)
            )
            for start in range(0, time_count, chunk_rows):
                stop = min(time_count, start + chunk_rows)
                values = np.array(
                    result_ds[start:stop, column_selection],
                    dtype=np.float32,
                    copy=True,
                )
                finite = np.isfinite(values)
                np.abs(values, out=values)
                values[~finite] = -np.inf
                chunk_maximum = np.max(values, axis=0)
                target = maximum[column_start:column_stop]
                valid = np.isfinite(chunk_maximum) & (
                    chunk_maximum != -np.inf
                )
                target[valid] = np.where(
                    np.isfinite(target[valid]),
                    np.maximum(target[valid], chunk_maximum[valid]),
                    chunk_maximum[valid],
                )
        return maximum

    @staticmethod
    def mesh_areas(source: Path, inspection: dict[str, Any]):
        areas = HdfMesh.get_mesh_areas(source)
        if areas.empty or areas.crs is None:
            raise ValueError("Result HDF produced no CRS-aware 2D mesh footprint")
        if areas["mesh_name"].duplicated().any():
            raise ValueError("Result HDF contains duplicate 2D mesh footprints")
        expected = set(inspection["mesh_names"])
        actual = set(areas["mesh_name"].astype(str))
        if actual != expected:
            raise ValueError(
                "2D mesh footprint names do not match inspected result meshes: "
                f"expected {sorted(expected)}, got {sorted(actual)}"
            )
        if areas.geometry.isna().any() or areas.geometry.is_empty.any():
            raise ValueError("Result HDF contains an empty 2D mesh footprint")
        if not areas.geometry.is_valid.all():
            raise ValueError("Result HDF contains an invalid 2D mesh footprint")
        return areas.sort_values("mesh_name", kind="stable").reset_index(drop=True)

    @staticmethod
    def grid_spec(
        bbox: tuple[float, float, float, float],
        *,
        resolution: float | None,
        max_dimension: int,
    ) -> dict[str, Any]:
        from rasterio.transform import from_origin

        minx, miny, maxx, maxy = (float(value) for value in bbox)
        if not np.isfinite((minx, miny, maxx, maxy)).all():
            raise ValueError(f"Result footprint has nonfinite bounds: {bbox}")
        span_x = maxx - minx
        span_y = maxy - miny
        if span_x <= 0 or span_y <= 0:
            raise ValueError(f"Result footprint has invalid bounds: {bbox}")
        if resolution is None:
            resolution = max(span_x, span_y) / float(max_dimension)
        raw_columns = np.ceil(span_x / resolution)
        raw_rows = np.ceil(span_y / resolution)
        if (
            not np.isfinite((raw_columns, raw_rows)).all()
            or raw_columns > max_dimension
            or raw_rows > max_dimension
        ):
            raise ValueError(
                f"Requested resolution exceeds max_dimension={max_dimension}"
            )
        columns = max(2, int(raw_columns))
        rows = max(2, int(raw_rows))
        if columns > max_dimension or rows > max_dimension:
            raise ValueError(
                f"Requested resolution creates at least a {columns} by {rows} "
                "raster, "
                f"exceeding max_dimension={max_dimension}"
            )
        cell_count = columns * rows
        if cell_count > _ProductRenderers.MAX_RASTER_CELLS:
            raise ValueError(
                f"Requested raster has {cell_count:,} cells, exceeding the "
                f"bounded-memory limit of "
                f"{_ProductRenderers.MAX_RASTER_CELLS:,}"
            )
        raster_maxx = minx + columns * resolution
        raster_miny = maxy - rows * resolution
        raster_bbox = (minx, raster_miny, raster_maxx, maxy)
        transform = from_origin(minx, maxy, resolution, resolution)
        return {
            "bbox": raster_bbox,
            "width": columns,
            "height": rows,
            "transform": transform,
            "resolution": (float(resolution), float(resolution)),
        }

    @staticmethod
    def rasterize_points_by_mesh(
        frame,
        value_column: str,
        mesh_areas,
        grid: dict[str, Any],
    ) -> tuple[np.ndarray, np.ndarray]:
        from rasterio.features import geometry_mask
        from scipy.spatial import cKDTree

        output = np.full(
            (grid["height"], grid["width"]),
            np.nan,
            dtype=np.float32,
        )
        support = np.zeros(output.shape, dtype=bool)
        x_resolution, y_resolution = grid["resolution"]
        minx, miny, maxx, maxy = grid["bbox"]
        x_coordinates = np.linspace(
            minx + x_resolution / 2.0,
            maxx - x_resolution / 2.0,
            grid["width"],
        )
        y_coordinates = np.linspace(
            maxy - y_resolution / 2.0,
            miny + y_resolution / 2.0,
            grid["height"],
        )

        for area in mesh_areas.itertuples(index=False):
            mesh_name = str(area.mesh_name)
            subset = frame.loc[frame["mesh_name"] == mesh_name].sort_values(
                "cell_id",
                kind="stable",
            )
            if subset.empty:
                raise ValueError(f"No {value_column} rows for mesh '{mesh_name}'")
            coordinate_values = np.column_stack(
                (
                    subset.geometry.x.to_numpy(dtype=float),
                    subset.geometry.y.to_numpy(dtype=float),
                )
            )
            finite_coordinates = (
                subset.geometry.notna()
                & ~subset.geometry.is_empty
                & np.isfinite(coordinate_values).all(axis=1)
            )
            if not bool(finite_coordinates.any()):
                raise ValueError(
                    f"Nonfinite or empty cell points for mesh '{mesh_name}'"
                )
            values = subset[value_column].to_numpy(dtype=np.float32)
            finite_values = np.isfinite(values)
            if not finite_values.any():
                raise ValueError(
                    f"No finite {value_column} values for mesh '{mesh_name}'"
                )
            finite_observations = (
                finite_coordinates.to_numpy(dtype=bool) & finite_values
            )
            if not finite_observations.any():
                raise ValueError(
                    "No finite coordinate/value pairs for "
                    f"{value_column} in mesh '{mesh_name}'"
                )
            # Nonfinite result cells are not interpolation observations. Keep
            # their mesh footprint in ``support``, but exclude their point/value
            # pairs from the nearest-neighbor index so they cannot introduce
            # nodata holes into otherwise finite derived rasters.
            xy = coordinate_values[finite_observations]
            values = values[finite_observations]
            tree = cKDTree(xy)
            area_mask = geometry_mask(
                [area.geometry],
                out_shape=output.shape,
                transform=grid["transform"],
                invert=True,
            )
            if np.any(support & area_mask):
                raise ValueError(
                    "2D mesh footprints overlap on the requested raster grid; "
                    "cell ownership would be ambiguous"
                )
            support |= area_mask
            row_chunk = max(1, min(256, grid["height"]))
            for row_start in range(0, grid["height"], row_chunk):
                row_stop = min(grid["height"], row_start + row_chunk)
                local_rows, columns = np.nonzero(area_mask[row_start:row_stop])
                if not len(local_rows):
                    continue
                rows = local_rows + row_start
                query_points = np.column_stack(
                    (x_coordinates[columns], y_coordinates[rows])
                )
                _, nearest = tree.query(query_points, workers=1)
                output[rows, columns] = values[nearest]
        return output, support

    @staticmethod
    def apply_masks(
        values: np.ndarray,
        support: np.ndarray,
        *,
        wet_mask: np.ndarray | None,
        nodata: float,
    ) -> np.ndarray:
        valid = support & np.isfinite(values)
        if wet_mask is not None:
            valid &= wet_mask
        if np.any(values[valid] == nodata):
            raise ValueError(
                f"Raster nodata value {nodata} collides with valid result data"
            )
        return np.where(valid, values, nodata).astype(np.float32)

    @staticmethod
    def write_cog(
        path: Path,
        values: np.ndarray,
        grid: dict[str, Any],
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
            overview_resampling="nearest",
            num_threads=1,
            BIGTIFF="IF_SAFER",
        ) as destination:
            destination.write(values, 1)
            destination.update_tags(
                product_key=product_key,
                units=units,
                derivation=derivation,
                generated_by="ras-commander",
                source_access="read-only",
            )

        with rasterio.open(path) as result:
            if result.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
                raise RuntimeError(
                    f"Raster driver did not produce a COG for {path.name}"
                )
            if (
                result.width != grid["width"]
                or result.height != grid["height"]
                or result.count != 1
                or result.nodata != nodata
                or result.transform != grid["transform"]
            ):
                raise RuntimeError(f"COG metadata readback failed for {path.name}")
            for _, window in result.block_windows(1):
                row_start = int(window.row_off)
                row_stop = row_start + int(window.height)
                column_start = int(window.col_off)
                column_stop = column_start + int(window.width)
                if not np.array_equal(
                    result.read(1, window=window),
                    values[row_start:row_stop, column_start:column_stop],
                ):
                    raise RuntimeError(
                        f"COG value readback failed for {path.name}"
                    )

    @staticmethod
    def write_hydrographs(source: Path, path: Path) -> dict[str, Any]:
        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = pa.schema(
            [
                pa.field("time", pa.timestamp("ns"), nullable=True),
                pa.field("bc_name", pa.string(), nullable=True),
                pa.field("variable", pa.string(), nullable=True),
                pa.field("value", pa.float64(), nullable=True),
                pa.field("units", pa.string(), nullable=True),
                pa.field("area_2d", pa.string(), nullable=True),
            ]
        )
        frames: list[pd.DataFrame] = []
        units_by_variable: dict[str, list[str]] = {}
        with h5py.File(source, "r") as hdf_file:
            boundary_group = hdf_file.get(
                "Results/Unsteady/Output/Output Blocks/Base Output/"
                "Unsteady Time Series/Boundary Conditions"
            )
            has_boundaries = boundary_group is not None and len(boundary_group) > 0

        if has_boundaries:
            dataset = HdfResultsMesh.get_boundary_conditions_timeseries(source)
            for variable in ("flow", "stage"):
                if variable not in dataset.data_vars:
                    continue
                frame = dataset[variable].to_dataframe(name="value").reset_index()
                numeric_values = pd.to_numeric(
                    frame["value"],
                    errors="coerce",
                ).to_numpy(dtype=float)
                if not np.isfinite(numeric_values).any():
                    continue
                frame.insert(2, "variable", variable)
                units_name = f"{variable}_units"
                if units_name in dataset.coords:
                    unit_lookup = {
                        str(name): str(unit)
                        for name, unit in zip(
                            dataset["bc_name"].values,
                            dataset[units_name].values,
                        )
                    }
                    frame["units"] = frame["bc_name"].astype(str).map(
                        unit_lookup
                    )
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
                    frame["area_2d"] = frame["bc_name"].astype(str).map(
                        area_lookup
                    )
                else:
                    frame["area_2d"] = ""
                frame["bc_name"] = frame["bc_name"].astype(str)
                frame["time"] = pd.to_datetime(frame["time"])
                frames.append(frame[list(schema.names)])
                units_by_variable[variable] = sorted(
                    {
                        value
                        for value in frame["units"].fillna("").astype(str)
                        if value.strip()
                    }
                )

        if frames:
            pandas_table = pd.concat(frames, ignore_index=True).sort_values(
                ["time", "bc_name", "variable"],
                kind="stable",
            )
            pandas_table.reset_index(drop=True, inplace=True)
            table = pa.Table.from_pandas(
                pandas_table,
                schema=schema,
                preserve_index=False,
                safe=True,
            )
        else:
            table = pa.Table.from_arrays(
                [pa.array([], type=field.type) for field in schema],
                schema=schema,
            )

        pq.write_table(
            table,
            path,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
            version="2.6",
            data_page_version="1.0",
        )
        reopened = pq.ParquetFile(path)
        if (
            reopened.schema_arrow.remove_metadata() != schema
            or reopened.metadata.num_rows != len(table)
        ):
            raise RuntimeError("Hydrograph Parquet schema/row-count readback failed")
        variables = sorted(
            set(table.column("variable").to_pylist()) - {None}
        )
        times = table.column("time").to_pylist()
        nonnull_times = [value for value in times if value is not None]
        return {
            "row_count": reopened.metadata.num_rows,
            "columns": [
                {"name": field.name, "type": str(field.type)} for field in schema
            ],
            "variables": variables,
            "units": units_by_variable,
            "missing_value_count": table.column("value").null_count,
            "time_start": (
                pd.Timestamp(min(nonnull_times)).isoformat()
                if nonnull_times
                else None
            ),
            "time_end": (
                pd.Timestamp(max(nonnull_times)).isoformat()
                if nonnull_times
                else None
            ),
            "empty_reason": (
                None
                if frames
                else (
                    "no_available_flow_or_stage_series_in_result"
                    if has_boundaries
                    else "no_boundary_series_in_result"
                )
            ),
        }

    @staticmethod
    def write_footprint(path: Path, mesh_areas, *, source_name: str) -> dict[str, Any]:
        from shapely.geometry import mapping

        geographic = mesh_areas.to_crs("EPSG:4326")
        features = []
        for area in geographic.itertuples(index=False):
            features.append(
                {
                    "type": "Feature",
                    "id": str(area.mesh_name),
                    "properties": {
                        "mesh_name": str(area.mesh_name),
                        "source": source_name,
                        "source_access": "read_only",
                    },
                    "geometry": mapping(area.geometry),
                }
            )
        bounds = tuple(float(value) for value in geographic.total_bounds)
        payload = {
            "type": "FeatureCollection",
            "bbox": list(bounds),
            "features": features,
        }
        _write_json(path, payload)
        reopened = json.loads(path.read_text(encoding="utf-8"))
        normalized = json.loads(
            json.dumps(payload, sort_keys=True, allow_nan=False)
        )
        if reopened != normalized:
            raise RuntimeError("Result footprint GeoJSON readback failed")
        return {"bbox_wgs84": list(bounds), "feature_count": len(features)}

    @staticmethod
    def write_preview(depth_path: Path, preview_path: Path, *, units: str) -> None:
        import rasterio
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        with rasterio.open(depth_path) as source:
            depth = source.read(1, masked=True)
            extent = (
                source.bounds.left,
                source.bounds.right,
                source.bounds.bottom,
                source.bounds.top,
            )
        figure = Figure(figsize=(10, 7), dpi=120)
        FigureCanvasAgg(figure)
        axis = figure.subplots()
        try:
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
        finally:
            figure.clear()
        if not preview_path.is_file() or preview_path.stat().st_size <= 0:
            raise RuntimeError("Maximum-depth preview was not created")

    @staticmethod
    def raster_asset(path: Path, *, units: str) -> dict[str, Any]:
        import rasterio

        with rasterio.open(path) as source:
            minimum: float | None = None
            maximum: float | None = None
            for _, window in source.block_windows(1):
                finite = source.read(1, window=window, masked=True).compressed()
                if not finite.size:
                    continue
                block_minimum = float(np.min(finite))
                block_maximum = float(np.max(finite))
                minimum = (
                    block_minimum
                    if minimum is None
                    else min(minimum, block_minimum)
                )
                maximum = (
                    block_maximum
                    if maximum is None
                    else max(maximum, block_maximum)
                )
            return _ProductRenderers.file_asset(
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
                            "spatial_resolution": [
                                float(abs(source.transform.a)),
                                float(abs(source.transform.e)),
                            ],
                            "statistics": {
                                "minimum": minimum,
                                "maximum": maximum,
                            },
                        }
                    ],
                    "cog": {
                        "layout": source.tags(ns="IMAGE_STRUCTURE").get(
                            "LAYOUT"
                        ),
                        "overviews": source.overviews(1),
                    },
                },
            )

    @staticmethod
    def file_asset(
        path: Path,
        *,
        media_type: str,
        roles: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        asset: dict[str, Any] = {
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
    def validate_asset(stage: Path, asset: dict[str, Any]) -> None:
        path = stage / asset["href"]
        if not path.is_file():
            raise RuntimeError(f"Product asset is missing: {path.name}")
        if path.stat().st_size != asset["size_bytes"]:
            raise RuntimeError(f"Product asset size changed: {path.name}")
        if _sha256(path) != asset["sha256"]:
            raise RuntimeError(f"Product asset checksum changed: {path.name}")
