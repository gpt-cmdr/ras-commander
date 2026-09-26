"""Normalize GeoTIFF precipitation into durable HEC-RAS NetCDF forcing."""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..ComputeResults import PrecipRasterImportResult
from ..LoggingConfig import get_logger
from ..RasPrecipHdf import RasPrecipHdf
from .PrecipCapabilities import QualificationStatus

logger = get_logger(__name__)

ValueType = Literal["rate", "amount", "cumulative"]
NodataPolicy = Literal["error", "zero"]
CachePolicy = Literal["reuse", "refresh", "error"]
SourceFormat = Literal["geotiff", "grib"]
RouteName = Literal["translated_netcdf_with_native_hdf"]
PathLike = Union[str, os.PathLike[str]]
BandSelection = Union[Sequence[int], Sequence[Sequence[int]]]


@dataclass(frozen=True)
class PrecipitationCube:
    """Canonical cumulative precipitation cube ready for HEC-RAS."""

    values: np.ndarray
    timestamps: pd.DatetimeIndex
    x: np.ndarray
    y: np.ndarray
    transform: Any
    crs_wkt: str
    units: str
    source_value_type: ValueType
    source_paths: tuple[Path, ...]
    source_hashes: tuple[str, ...]
    selected_bands: tuple[tuple[int, ...], ...]
    nodata_policy: NodataPolicy
    nodata_count: int
    content_hash: str


@dataclass(frozen=True)
class PrecipitationNetcdfResult:
    """Durable NetCDF cache created from a normalized raster cube."""

    path: Path
    content_hash: str
    reused: bool


@dataclass(frozen=True)
class GriddedPrecipitationImportResult:
    """Auditable result of one translated raster-precipitation import."""

    source_format: SourceFormat
    source_paths: tuple[Path, ...]
    source_hashes: tuple[str, ...]
    selected_bands: tuple[tuple[int, ...], ...]
    cache_path: Path
    cache_hash: str
    cache_reused: bool
    hdf_result: PrecipRasterImportResult
    hec_ras_version: Optional[str]
    selected_route: RouteName
    route_qualification: "QualificationStatus"
    shape: tuple[int, int, int]
    timestamps: pd.DatetimeIndex
    crs_wkt: str
    transform: Any
    units: str
    value_type: ValueType
    nodata_policy: NodataPolicy
    nodata_count: int


class RasPrecipGrid:
    """Read precipitation rasters and write a HEC-RAS-compatible NetCDF cache."""

    @staticmethod
    def _as_paths(
        paths: Union[str, Path, Sequence[Union[str, Path]]],
        *,
        source_kind: str,
        allowed_suffixes: set[str],
    ) -> tuple[Path, ...]:
        if isinstance(paths, (str, os.PathLike)):
            result = (Path(paths),)
        else:
            result = tuple(Path(path) for path in paths)
        if not result:
            raise ValueError(f"At least one {source_kind} path is required")
        missing = [path for path in result if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{source_kind} precipitation file not found: {missing[0]}"
            )
        invalid = [path for path in result if path.suffix.lower() not in allowed_suffixes]
        if invalid:
            raise ValueError(
                f"Unsupported {source_kind} filename extension: {invalid[0].name}"
            )
        return result

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _normalize_timestamps(
        timestamps: Sequence[Any],
        *,
        source_timezone: Optional[str],
        model_timezone: Optional[str],
    ) -> pd.DatetimeIndex:
        raw = list(timestamps)
        if not raw:
            raise ValueError("timestamps must not be empty")

        parsed: list[pd.Timestamp] = []
        awareness: set[bool] = set()
        for value in raw:
            stamp = pd.Timestamp(value)
            if pd.isna(stamp):
                raise ValueError("timestamps must not contain null values")
            aware = stamp.tzinfo is not None and stamp.utcoffset() is not None
            awareness.add(aware)
            parsed.append(stamp)
        if len(awareness) != 1:
            raise ValueError("timestamps must not mix timezone-aware and naive values")

        if True in awareness:
            index = pd.DatetimeIndex(parsed)
            target_timezone = model_timezone or source_timezone
            if target_timezone:
                index = index.tz_convert(target_timezone)
            index = index.tz_localize(None)
        else:
            index = pd.DatetimeIndex(parsed)
            if source_timezone:
                try:
                    index = index.tz_localize(
                        source_timezone,
                        ambiguous="raise",
                        nonexistent="raise",
                    )
                except Exception as exc:
                    raise ValueError(
                        f"Could not localize timestamps to {source_timezone!r}: {exc}"
                    ) from exc
                index = index.tz_convert(model_timezone or source_timezone).tz_localize(None)
            elif model_timezone:
                raise ValueError(
                    "model_timezone requires source_timezone for timezone-naive timestamps"
                )

        if index.has_duplicates:
            raise ValueError("timestamps must be unique")
        deltas = np.diff(index.asi8)
        if deltas.size and np.any(deltas <= 0):
            raise ValueError("timestamps must be strictly increasing")
        return index

    @staticmethod
    def _raster_units(dataset: Any, band: int) -> Optional[str]:
        tags: dict[str, Any] = {}
        tags.update(dataset.tags())
        tags.update(dataset.tags(band))
        for key, value in tags.items():
            if str(key).strip().lower() in {
                "units",
                "unit",
                "unittype",
                "precipitation_units",
                "grib_unit",
            }:
                clean = str(value).strip()
                if clean:
                    return clean
        return None

    @staticmethod
    def _same_nodata(left: Optional[float], right: Optional[float]) -> bool:
        if left is None or right is None:
            return left is right
        if math.isnan(left) or math.isnan(right):
            return math.isnan(left) and math.isnan(right)
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=0.0)

    @staticmethod
    def _validate_transform(transform: Any, source_kind: str) -> None:
        if not math.isclose(float(transform.b), 0.0, abs_tol=1e-12):
            raise ValueError(
                f"{source_kind} transform is rotated or sheared; north-up is required"
            )
        if not math.isclose(float(transform.d), 0.0, abs_tol=1e-12):
            raise ValueError(
                f"{source_kind} transform is rotated or sheared; north-up is required"
            )
        if float(transform.a) <= 0 or float(transform.e) >= 0:
            raise ValueError(
                f"{source_kind} must be north-up with positive x scale and negative y scale"
            )
        if not math.isclose(
            abs(float(transform.a)),
            abs(float(transform.e)),
            rel_tol=1e-4,
        ):
            raise ValueError(
                f"{source_kind} cells must be square for HEC-RAS gridded precipitation"
            )

    @staticmethod
    def _content_hash(
        *,
        source_hashes: tuple[str, ...],
        timestamps: pd.DatetimeIndex,
        bands: tuple[tuple[int, ...], ...],
        units: str,
        value_type: ValueType,
        first_timestep_hours: Optional[float],
        nodata_policy: NodataPolicy,
        crs_wkt: str,
        transform: Any,
        shape: tuple[int, ...],
    ) -> str:
        payload = {
            "schema": "ras-commander-precipitation-cube/v2",
            "source_hashes": list(source_hashes),
            "timestamps": [stamp.isoformat() for stamp in timestamps],
            "bands": [list(file_bands) for file_bands in bands],
            "units": units,
            "value_type": value_type,
            "first_timestep_hours": first_timestep_hours,
            "nodata_policy": nodata_policy,
            "crs_wkt": crs_wkt,
            "transform": [float(value) for value in tuple(transform)],
            "shape": list(shape),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _from_raster(
        geotiff_paths: Union[PathLike, Sequence[PathLike]],
        *,
        timestamps: Sequence[Any],
        units: str,
        value_type: ValueType,
        first_timestep_hours: Optional[float] = None,
        bands: Optional[BandSelection] = None,
        source_timezone: Optional[str] = None,
        model_timezone: Optional[str] = None,
        nodata_policy: NodataPolicy = "error",
        source_kind: str,
        allowed_suffixes: set[str],
    ) -> PrecipitationCube:
        """Read one multiband raster or a sequence of single-band rasters."""
        try:
            import rasterio
        except ImportError as exc:
            raise ImportError(
                f"rasterio is required for {source_kind} precipitation; install with "
                "pip install ras-commander[precip]"
            ) from exc

        if nodata_policy not in {"error", "zero"}:
            raise ValueError("nodata_policy must be 'error' or 'zero'")
        if value_type not in {"rate", "amount", "cumulative"}:
            raise ValueError("value_type must be 'rate', 'amount', or 'cumulative'")
        units_out = RasPrecipHdf.normalize_units(units)
        RasPrecipHdf.validate_data_type_units("cumulative", units_out)

        paths = RasPrecipGrid._as_paths(
            geotiff_paths,
            source_kind=source_kind,
            allowed_suffixes=allowed_suffixes,
        )
        source_hashes = tuple(RasPrecipGrid._hash_file(path) for path in paths)
        times = RasPrecipGrid._normalize_timestamps(
            timestamps,
            source_timezone=source_timezone,
            model_timezone=model_timezone,
        )

        frames: list[np.ndarray] = []
        selected_bands: list[tuple[int, ...]] = []
        nodata_count = 0
        reference: Optional[dict[str, Any]] = None

        common_bands: Optional[tuple[int, ...]] = None
        per_file_bands: Optional[tuple[tuple[int, ...], ...]] = None
        if bands is not None:
            requested = list(bands)
            if requested and all(isinstance(value, numbers.Integral) for value in requested):
                common_bands = tuple(int(value) for value in requested)
            elif len(requested) == len(paths) and all(
                not isinstance(value, (str, bytes, numbers.Integral))
                for value in requested
            ):
                per_file_bands = tuple(
                    tuple(int(band) for band in file_selection)
                    for file_selection in requested
                )
            else:
                raise ValueError(
                    "bands must be a sequence of band numbers applied to every file, "
                    "or one sequence of band numbers per input file"
                )

        for path_index, path in enumerate(paths):
            with rasterio.open(path) as dataset:
                if dataset.crs is None:
                    raise ValueError(f"{source_kind} has no CRS: {path.name}")
                if not dataset.crs.is_projected:
                    raise ValueError(
                        f"{source_kind} CRS must be projected, not geographic/angular: {path.name}"
                    )
                RasPrecipGrid._validate_transform(dataset.transform, source_kind)

                if common_bands is not None:
                    file_bands = common_bands
                elif per_file_bands is not None:
                    file_bands = per_file_bands[path_index]
                elif len(paths) == 1:
                    file_bands = tuple(int(band) for band in dataset.indexes)
                else:
                    if dataset.count != 1:
                        raise ValueError(
                            f"A multiband {source_kind} sequence requires an explicit "
                            f"bands selection; {path.name} has {dataset.count} bands"
                        )
                    file_bands = (1,)

                if not file_bands:
                    raise ValueError(f"No bands were selected for {path.name}")

                for band in file_bands:
                    if band not in dataset.indexes:
                        raise ValueError(f"Band {band} does not exist in {path.name}")

                current = {
                    "shape": (dataset.height, dataset.width),
                    "crs": dataset.crs,
                    "transform": dataset.transform,
                    "nodata": dataset.nodata,
                }
                if reference is None:
                    reference = current
                else:
                    if current["shape"] != reference["shape"]:
                        raise ValueError(f"{source_kind} sequence has inconsistent raster shapes")
                    if current["crs"] != reference["crs"]:
                        raise ValueError(f"{source_kind} sequence has inconsistent CRS definitions")
                    if not np.allclose(
                        tuple(current["transform"]),
                        tuple(reference["transform"]),
                        rtol=0.0,
                        atol=1e-10,
                    ):
                        raise ValueError(f"{source_kind} sequence has inconsistent affine transforms")
                    if not RasPrecipGrid._same_nodata(
                        current["nodata"], reference["nodata"]
                    ):
                        raise ValueError(f"{source_kind} sequence has inconsistent NoData definitions")

                for band in file_bands:
                    declared_units = RasPrecipGrid._raster_units(dataset, band)
                    if declared_units:
                        temporal_units = RasPrecipHdf.classify_temporal_units(
                            declared_units
                        )
                        if temporal_units == "rate_other":
                            raise ValueError(
                                f"{path.name} band {band} declares non-hourly rate units "
                                f"{declared_units!r}; convert them explicitly before import"
                            )
                        if temporal_units == "rate_per_hour" and value_type != "rate":
                            raise ValueError(
                                f"{path.name} band {band} declares rate units "
                                f"{declared_units!r} but value_type={value_type!r}"
                            )
                        if temporal_units == "depth" and value_type == "rate":
                            raise ValueError(
                                f"{path.name} band {band} declares depth units "
                                f"{declared_units!r} but value_type='rate'"
                            )
                        inferred = RasPrecipHdf.infer_depth_units(declared_units)
                        if inferred is not None and inferred != units_out:
                            raise ValueError(
                                f"{path.name} band {band} declares {declared_units!r} "
                                f"({inferred}) but units={units_out!r} was requested"
                            )

                    masked = dataset.read(band, masked=True)
                    mask = np.ma.getmaskarray(masked)
                    count = int(np.count_nonzero(mask))
                    nodata_count += count
                    if count and nodata_policy == "error":
                        raise ValueError(
                            f"{path.name} band {band} contains {count} NoData pixels; "
                            "pass nodata_policy='zero' only when dry-cell substitution is intended"
                        )
                    values = np.asarray(masked.filled(0.0), dtype=np.float32)
                    if not np.all(np.isfinite(values)):
                        raise ValueError(
                            f"{path.name} band {band} contains NaN or infinite precipitation"
                        )
                    minimum = float(values.min())
                    if minimum < -1e-6:
                        raise ValueError(
                            f"{path.name} band {band} contains negative precipitation "
                            f"({minimum})"
                        )
                    np.maximum(values, 0.0, out=values)
                    frames.append(values)
                selected_bands.append(tuple(file_bands))

        if len(times) != len(frames):
            raise ValueError(
                f"timestamps has {len(times)} entries but the selected {source_kind} input "
                f"contains {len(frames)} precipitation bands"
            )
        if not frames:
            raise ValueError(f"No {source_kind} bands were selected")
        assert reference is not None

        source_values = np.stack(frames, axis=0)
        if not np.any(np.isfinite(source_values)):
            raise ValueError(f"{source_kind} precipitation contains no finite values")
        if value_type in {"rate", "amount"}:
            if first_timestep_hours is None and np.any(source_values[0] != 0):
                raise ValueError(
                    f"first_timestep_hours is required when the first {source_kind} frame "
                    "contains nonzero rate or amount precipitation"
                )
        else:
            if first_timestep_hours is not None:
                raise ValueError(
                    "first_timestep_hours does not apply to cumulative precipitation"
                )
            differences = np.diff(source_values, axis=0)
            if differences.size and np.any(differences < -1e-6):
                raise ValueError(f"Cumulative {source_kind} precipitation must not decrease")

        cumulative, cumulative_times = RasPrecipHdf.convert_to_cumulative(
            source_values,
            times,
            value_type,
            first_timestep_hours,
        )
        transform = reference["transform"]
        width = reference["shape"][1]
        height = reference["shape"][0]
        x = np.asarray(
            [transform.c + (column + 0.5) * transform.a for column in range(width)],
            dtype=np.float64,
        )
        y = np.asarray(
            [transform.f + (row + 0.5) * transform.e for row in range(height)],
            dtype=np.float64,
        )
        crs_wkt = reference["crs"].to_wkt(version="WKT1_GDAL")
        cumulative_index = pd.DatetimeIndex(cumulative_times)
        digest = RasPrecipGrid._content_hash(
            source_hashes=source_hashes,
            timestamps=times,
            bands=tuple(selected_bands),
            units=units_out,
            value_type=value_type,
            first_timestep_hours=first_timestep_hours,
            nodata_policy=nodata_policy,
            crs_wkt=crs_wkt,
            transform=transform,
            shape=tuple(source_values.shape),
        )
        return PrecipitationCube(
            values=np.asarray(cumulative, dtype=np.float32),
            timestamps=cumulative_index,
            x=x,
            y=y,
            transform=transform,
            crs_wkt=crs_wkt,
            units=units_out,
            source_value_type=value_type,
            source_paths=paths,
            source_hashes=source_hashes,
            selected_bands=tuple(selected_bands),
            nodata_policy=nodata_policy,
            nodata_count=nodata_count,
            content_hash=digest,
        )

    @staticmethod
    @log_call
    def from_geotiff(
        geotiff_paths: Union[PathLike, Sequence[PathLike]],
        *,
        timestamps: Sequence[Any],
        units: str,
        value_type: ValueType,
        first_timestep_hours: Optional[float] = None,
        bands: Optional[BandSelection] = None,
        source_timezone: Optional[str] = None,
        model_timezone: Optional[str] = None,
        nodata_policy: NodataPolicy = "error",
    ) -> PrecipitationCube:
        """Read one multiband GeoTIFF or a sequence of single-band GeoTIFFs."""
        return RasPrecipGrid._from_raster(
            geotiff_paths,
            timestamps=timestamps,
            units=units,
            value_type=value_type,
            first_timestep_hours=first_timestep_hours,
            bands=bands,
            source_timezone=source_timezone,
            model_timezone=model_timezone,
            nodata_policy=nodata_policy,
            source_kind="GeoTIFF",
            allowed_suffixes={".tif", ".tiff"},
        )

    @staticmethod
    @log_call
    def from_grib(
        grib_paths: Union[PathLike, Sequence[PathLike]],
        *,
        timestamps: Sequence[Any],
        units: str,
        value_type: ValueType,
        first_timestep_hours: Optional[float] = None,
        bands: Optional[BandSelection] = None,
        source_timezone: Optional[str] = None,
        model_timezone: Optional[str] = None,
        nodata_policy: NodataPolicy = "error",
    ) -> PrecipitationCube:
        """Read projected GRIB/GRIB2 through GDAL with explicit time semantics."""
        return RasPrecipGrid._from_raster(
            grib_paths,
            timestamps=timestamps,
            units=units,
            value_type=value_type,
            first_timestep_hours=first_timestep_hours,
            bands=bands,
            source_timezone=source_timezone,
            model_timezone=model_timezone,
            nodata_policy=nodata_policy,
            source_kind="GRIB",
            allowed_suffixes={".grb", ".grib", ".grb2", ".grib2"},
        )

    @staticmethod
    @log_call
    def default_cache_path(cube: PrecipitationCube, project_folder: Path) -> Path:
        """Return the content-addressed project-local NetCDF cache path."""
        return (
            Path(project_folder)
            / "Precipitation"
            / "_ras_commander_cache"
            / f"precip-{cube.content_hash[:16]}.nc"
        )

    @staticmethod
    def _valid_cached_netcdf(path: Path, cube: PrecipitationCube) -> bool:
        try:
            import xarray as xr

            dataset = None
            for engine in ("h5netcdf", "scipy"):
                try:
                    dataset = xr.open_dataset(path, engine=engine)
                    break
                except Exception:
                    continue
            if dataset is None:
                return False
            try:
                if dataset.attrs.get("ras_commander_precip_digest") != cube.content_hash:
                    return False
                if "precipitation" not in dataset.data_vars:
                    return False
                precip = dataset["precipitation"]
                if tuple(precip.shape) != tuple(cube.values.shape):
                    return False
                if precip.attrs.get("units") != cube.units:
                    return False
                if precip.attrs.get("source_value_type") != cube.source_value_type:
                    return False
                if "spatial_ref" not in dataset:
                    return False
                spatial_attrs = dataset["spatial_ref"].attrs
                if spatial_attrs.get("crs_wkt") != cube.crs_wkt:
                    return False
                expected_transform = " ".join(
                    str(float(value)) for value in cube.transform.to_gdal()
                )
                if spatial_attrs.get("GeoTransform") != expected_transform:
                    return False
                if not np.array_equal(
                    np.asarray(dataset["time"].values).astype("datetime64[ns]"),
                    np.asarray(cube.timestamps.values).astype("datetime64[ns]"),
                ):
                    return False
                if not np.array_equal(np.asarray(dataset["x"].values), cube.x):
                    return False
                if not np.array_equal(np.asarray(dataset["y"].values), cube.y):
                    return False
                return np.array_equal(
                    np.asarray(precip.values, dtype=np.float32), cube.values
                )
            finally:
                dataset.close()
        except Exception:
            return False

    @staticmethod
    @log_call
    def to_ras_netcdf(
        cube: PrecipitationCube,
        output_path: Union[str, Path],
        *,
        cache_policy: CachePolicy = "reuse",
    ) -> PrecipitationNetcdfResult:
        """Write a cumulative, CF/GDAL-readable NetCDF transactionally."""
        if cache_policy not in {"reuse", "refresh", "error"}:
            raise ValueError("cache_policy must be 'reuse', 'refresh', or 'error'")
        try:
            import xarray as xr
        except ImportError as exc:
            raise ImportError(
                "xarray is required to create the GeoTIFF "
                "precipitation cache; install with pip install ras-commander[precip]"
            ) from exc

        try:
            import h5netcdf  # noqa: F401

            engine = "h5netcdf"
        except ImportError:
            try:
                import scipy  # noqa: F401

                engine = "scipy"
            except ImportError as exc:
                raise ImportError(
                    "h5netcdf or scipy is required to write the precipitation cache; "
                    "install with pip install ras-commander[precip]"
                ) from exc

        destination = Path(output_path)
        if destination.suffix.lower() not in {".nc", ".nc4"}:
            raise ValueError("output_path must use a .nc or .nc4 extension")
        if destination.exists():
            if cache_policy == "error":
                raise FileExistsError(f"Precipitation cache already exists: {destination}")
            if cache_policy == "reuse" and RasPrecipGrid._valid_cached_netcdf(
                destination, cube
            ):
                return PrecipitationNetcdfResult(
                    path=destination,
                    content_hash=cube.content_hash,
                    reused=True,
                )
            if cache_policy == "reuse":
                logger.warning("Replacing invalid precipitation cache: %s", destination)

        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.partial.nc"
        )
        source_manifest = [
            {"path": str(path), "sha256": digest}
            for path, digest in zip(cube.source_paths, cube.source_hashes)
        ]
        spatial_ref = xr.DataArray(
            np.int32(0),
            attrs={
                "spatial_ref": cube.crs_wkt,
                "crs_wkt": cube.crs_wkt,
                "GeoTransform": " ".join(str(float(value)) for value in cube.transform.to_gdal()),
            },
        )
        dataset = xr.Dataset(
            data_vars={
                "precipitation": (
                    ("time", "y", "x"),
                    cube.values,
                    {
                        "long_name": "Cumulative precipitation depth",
                        "standard_name": "precipitation_amount",
                        "units": cube.units,
                        "grid_mapping": "spatial_ref",
                        "source_value_type": cube.source_value_type,
                    },
                ),
                "spatial_ref": spatial_ref,
            },
            coords={"time": cube.timestamps, "y": cube.y, "x": cube.x},
            attrs={
                "title": "HEC-RAS gridded precipitation forcing",
                "ras_commander_precip_schema": "2",
                "ras_commander_precip_digest": cube.content_hash,
                "ras_commander_nodata_policy": cube.nodata_policy,
                "ras_commander_nodata_count": cube.nodata_count,
                "ras_commander_sources": json.dumps(source_manifest, sort_keys=True),
            },
        )
        encoding = {"precipitation": {"dtype": "float32", "_FillValue": -9999.0}}
        if engine == "h5netcdf":
            encoding["precipitation"].update({"zlib": True, "complevel": 1})
        try:
            dataset.to_netcdf(temp_path, engine=engine, encoding=encoding)
            dataset.close()
            if not RasPrecipGrid._valid_cached_netcdf(temp_path, cube):
                raise ValueError("Generated precipitation NetCDF failed validation")
            os.replace(temp_path, destination)
        except Exception:
            dataset.close()
            temp_path.unlink(missing_ok=True)
            raise

        return PrecipitationNetcdfResult(
            path=destination,
            content_hash=cube.content_hash,
            reused=False,
        )


__all__ = [
    "GriddedPrecipitationImportResult",
    "PrecipitationCube",
    "PrecipitationNetcdfResult",
    "RasPrecipGrid",
]
