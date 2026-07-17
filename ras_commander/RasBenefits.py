"""Rasterized benefit-area analysis from pre/post depth comparisons.

This module compares pre- and post-project depth rasters.  It intentionally does
not use water-surface elevation to qualify benefit cells: post-project NoData is
treated as dry (zero effective depth) inside the valid pre-project domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union
from uuid import uuid4
import warnings

import geopandas as gpd
import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS as PyprojCRS
from rasterio.features import geometry_mask, geometry_window, shapes
from rasterio.windows import Window
from scipy import ndimage
from shapely import make_valid
from shapely.geometry import mapping, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

_OUTPUT_LOCKS: Dict[str, threading.RLock] = {}
_OUTPUT_LOCKS_GUARD = threading.Lock()
_OUTPUT_LOCK_STATE = threading.local()


def _serialize_benefit_outputs(func):
    """Serialize direct writers that share a raster or polygon destination."""

    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        output_value = bound.arguments.get("output_tif")
        if output_value is None:
            return func(*args, **kwargs)
        output_path = Path(output_value).resolve()
        targets = [output_path]
        polygon_value = bound.arguments.get("polygon_output")
        if polygon_value is True:
            targets.append(output_path.with_suffix(".gpkg"))
        elif polygon_value:
            targets.append(Path(polygon_value).resolve())
        target_by_key = {
            os.path.normcase(os.path.abspath(path)): path
            for path in targets
        }
        ordered = sorted(target_by_key.items())
        timeout = max(float(bound.arguments.get("lock_timeout", 600.0)), 0.0)
        deadline = time.monotonic() + timeout

        acquired_thread_locks = []
        try:
            for key, target in ordered:
                with _OUTPUT_LOCKS_GUARD:
                    thread_lock = _OUTPUT_LOCKS.setdefault(
                        key,
                        threading.RLock(),
                    )
                remaining = max(0.0, deadline - time.monotonic())
                if not thread_lock.acquire(timeout=remaining):
                    raise TimeoutError(
                        f"Timed out waiting to write BenefitArea output: {target}"
                    )
                acquired_thread_locks.append((key, target, thread_lock))

            depths = getattr(_OUTPUT_LOCK_STATE, "depths", None)
            if depths is None:
                depths = {}
                _OUTPUT_LOCK_STATE.depths = depths
            acquired_directories = []
            try:
                for key, target, _ in acquired_thread_locks:
                    depth = depths.get(key, 0)
                    lock_dir = None
                    if depth == 0:
                        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
                        lock_dir = (
                            Path(tempfile.gettempdir())
                            / f"ras-commander-benefit-{digest}.lock"
                        )
                        while True:
                            try:
                                os.mkdir(lock_dir)
                                break
                            except FileExistsError:
                                if time.monotonic() >= deadline:
                                    raise TimeoutError(
                                        "Timed out waiting for a cross-process "
                                        f"BenefitArea output lock for {target}. If no "
                                        f"writer is active, remove {lock_dir}."
                                    )
                                time.sleep(0.1)
                        try:
                            (lock_dir / "target.txt").write_text(
                                str(target),
                                encoding="utf-8",
                            )
                        except OSError:
                            pass
                    depths[key] = depth + 1
                    acquired_directories.append((key, lock_dir))
                return func(*args, **kwargs)
            finally:
                for key, lock_dir in reversed(acquired_directories):
                    remaining_depth = depths[key] - 1
                    if remaining_depth:
                        depths[key] = remaining_depth
                        continue
                    depths.pop(key, None)
                    if lock_dir is not None:
                        try:
                            (lock_dir / "target.txt").unlink(missing_ok=True)
                        except OSError as exc:
                            logger.warning(
                                "Could not remove BenefitArea lock metadata %s: %s",
                                lock_dir / "target.txt",
                                exc,
                            )
                        try:
                            os.rmdir(lock_dir)
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            logger.warning(
                                "Could not release BenefitArea output lock %s: %s",
                                lock_dir,
                                exc,
                            )
        finally:
            for _, _, thread_lock in reversed(acquired_thread_locks):
                thread_lock.release()

    return wrapper


class BenefitCategory(IntEnum):
    """Cell values written to a BenefitArea categorical raster."""

    NODATA = 0
    NO_CHANGE = 1
    PARTIALLY_BENEFITED = 2
    FULLY_BENEFITED = 3


BENEFIT_STATUS = {
    BenefitCategory.NO_CHANGE: "No Change",
    BenefitCategory.PARTIALLY_BENEFITED: "Partially Benefited",
    BenefitCategory.FULLY_BENEFITED: "Fully Benefited",
}

BENEFIT_COLORMAP = {
    BenefitCategory.NODATA: (0, 0, 0, 0),
    BenefitCategory.NO_CHANGE: (88, 135, 176, 255),
    BenefitCategory.PARTIALLY_BENEFITED: (255, 191, 0, 255),
    BenefitCategory.FULLY_BENEFITED: (35, 139, 69, 255),
}


@dataclass(frozen=True)
class BenefitAreaConfig:
    """Pair-aware configuration used by :meth:`RasProcess.store_maps`.

    ``pre_plan_number`` is the baseline plan; the ``plan_number`` supplied to
    ``store_maps`` is the post-project plan.
    """

    pre_plan_number: str
    terrain_tif: Union[str, Path]
    terrain_name: Optional[str] = None
    include_wse: bool = False
    flood_min_depth: float = 0.05
    benefit_min_depth: float = 0.25
    minimum_region_pixels: Optional[int] = 16
    analysis_boundary: Any = None
    improvement_boundary: Any = None
    polygon_output: Optional[Union[bool, str, Path]] = None
    polygon_simplify_tolerance: Optional[float] = None

    def __post_init__(self) -> None:
        if self.pre_plan_number is None or not str(self.pre_plan_number).strip():
            raise ValueError("pre_plan_number is required for BenefitArea mapping")
        if self.terrain_tif is None or not str(self.terrain_tif).strip():
            raise ValueError(
                "terrain_tif is required for BenefitArea mapping. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        RasBenefits._validate_thresholds(
            self.flood_min_depth,
            self.benefit_min_depth,
        )
        RasBenefits._validate_minimum_region_pixels(self.minimum_region_pixels)
        RasBenefits._validate_polygon_simplify_tolerance(
            self.polygon_simplify_tolerance
        )


@dataclass(frozen=True)
class BenefitAreaResult:
    """Paths, source provenance, and class statistics for one comparison."""

    raster_path: Path
    polygon_path: Optional[Path]
    pre_depth_path: Path
    post_depth_path: Path
    terrain_path: Path
    statistics: Dict[str, Dict[str, Union[int, float]]]
    flood_min_depth: float
    benefit_min_depth: float
    minimum_region_pixels: Optional[int]
    polygon_simplify_tolerance: Optional[float] = None


@dataclass(frozen=True)
class _RasterMetadata:
    width: int
    height: int
    transform: Affine
    crs: rasterio.crs.CRS
    bounds: rasterio.coords.BoundingBox
    profile: Dict[str, Any]


class RasBenefits:
    """Static namespace for depth-raster BenefitArea generation."""

    TERRAIN_REMEDIATION = (
        "Benefit analysis requires one readable, georeferenced, one-band single "
        "GeoTIFF terrain. Consolidate a VRT with RasTerrain.vrt_to_tiff(); "
        "create the HEC-RAS terrain with RasTerrain.create_terrain_from_rasters() "
        "or RasTerrain.create_terrain_hdf(); register its HDF with "
        "RasMap.add_terrain_layer(); associate both plan geometries with it using "
        "RasMap.associate_geometry_layers(); recompute the plans; and select it "
        "for mapping with RasMap.set_terrain_layer_visibility(..., exclusive=True)."
    )

    @staticmethod
    def _read_raster_band(src, *, window=None, mask: bool = False) -> np.ndarray:
        """Read through Rasterio while silencing its NumPy 2.5 shim warning."""

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Setting the shape on a NumPy array has been deprecated.*",
                category=DeprecationWarning,
            )
            if mask:
                return src.read_masks(1, window=window)
            return src.read(1, window=window)

    @staticmethod
    def _validate_thresholds(
        flood_min_depth: float,
        benefit_min_depth: float,
    ) -> None:
        try:
            finite = np.isfinite(float(flood_min_depth)) and np.isfinite(
                float(benefit_min_depth)
            )
        except (TypeError, ValueError) as exc:
            raise TypeError("Depth thresholds must be finite numbers") from exc
        if not finite:
            raise ValueError("Depth thresholds must be finite numbers")
        if flood_min_depth < 0 or benefit_min_depth < 0:
            raise ValueError("Depth thresholds must be non-negative")

    @staticmethod
    def _validate_minimum_region_pixels(value: Optional[int]) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError("minimum_region_pixels must be a positive integer or None")
        if int(value) <= 0:
            raise ValueError("minimum_region_pixels must be positive or None")

    @staticmethod
    def _validate_polygon_simplify_tolerance(value: Optional[float]) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
            raise TypeError(
                "polygon_simplify_tolerance must be a nonnegative number or None"
            )
        if not np.isfinite(float(value)) or float(value) < 0:
            raise ValueError(
                "polygon_simplify_tolerance must be a nonnegative finite number or None"
            )

    @staticmethod
    @log_call
    def validate_terrain_tif(terrain_tif: Union[str, Path]) -> Path:
        """Validate and return a required single-file terrain GeoTIFF path."""

        if terrain_tif is None or not str(terrain_tif).strip():
            raise ValueError(
                "terrain_tif is required for BenefitArea analysis. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        path = Path(terrain_tif)
        if path.suffix.lower() not in {".tif", ".tiff"}:
            raise ValueError(
                f"Terrain must be supplied as a single GeoTIFF, got: {path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        if not path.is_file():
            raise FileNotFoundError(
                f"Terrain GeoTIFF was not found: {path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )

        try:
            with rasterio.open(path) as src:
                if src.driver != "GTiff":
                    raise ValueError(
                        f"Terrain is not a GeoTIFF dataset (driver={src.driver!r}): {path}"
                    )
                if src.count != 1:
                    raise ValueError(
                        f"Benefit terrain must contain one raster band, found {src.count}: {path}"
                    )
                if src.crs is None:
                    raise ValueError(
                        f"Benefit terrain has no coordinate reference system: {path}"
                    )
                if not src.crs.is_projected:
                    raise ValueError(
                        f"Benefit terrain must use a projected coordinate system: {path}"
                    )
                if src.transform.is_identity or abs(src.transform.determinant) == 0:
                    raise ValueError(
                        f"Benefit terrain does not have a valid georeferencing transform: {path}"
                    )
                sample_window = Window(
                    0,
                    0,
                    min(src.width, 64),
                    min(src.height, 64),
                )
                sample = RasBenefits._read_raster_band(
                    src,
                    window=sample_window,
                )
                if sample.size == 0:
                    raise ValueError(
                        f"Benefit terrain has no readable raster cells: {path}"
                    )
        except rasterio.errors.RasterioIOError as exc:
            raise ValueError(
                f"Terrain GeoTIFF could not be opened or sampled: {path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            ) from exc
        except ValueError as exc:
            if RasBenefits.TERRAIN_REMEDIATION in str(exc):
                raise
            raise ValueError(f"{exc}. {RasBenefits.TERRAIN_REMEDIATION}") from exc

        return path

    @staticmethod
    @log_call
    def get_registered_terrain_source(terrain_hdf: Union[str, Path]) -> Path:
        """Return the one TIFF source recorded in a registered terrain HDF.

        HEC-RAS records each source surface on a child of ``/Terrain`` using a
        ``File`` attribute.  BenefitArea requires exactly one such source so
        RAS Mapper emits one Depth GeoTIFF per plan.
        """

        import h5py

        hdf_path = Path(terrain_hdf)
        if not hdf_path.is_file():
            raise FileNotFoundError(
                f"Registered terrain HDF was not found: {hdf_path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        file_values = []
        try:
            with h5py.File(hdf_path, "r") as hdf:
                terrain_group = hdf.get("Terrain")
                if terrain_group is not None:
                    def collect_file_attribute(_name, obj) -> None:
                        value = obj.attrs.get("File")
                        if value is None:
                            return
                        if isinstance(value, (bytes, np.bytes_)):
                            text = bytes(value).decode("utf-8", errors="strict")
                        else:
                            text = str(value)
                        text = text.strip().strip("\"'").rstrip("\x00")
                        if text:
                            file_values.append(text)

                    terrain_group.visititems(collect_file_attribute)
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"Registered terrain HDF could not be inspected: {hdf_path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            ) from exc

        source_paths = []
        seen = set()
        for text in file_values:
            if os.name != "nt":
                windows_path = PureWindowsPath(text)
                if windows_path.is_absolute():
                    raise ValueError(
                        "Registered terrain uses an absolute Windows source path "
                        f"that cannot be resolved on this host: {text}. "
                        f"{RasBenefits.TERRAIN_REMEDIATION}"
                    )
                raw_path = (
                    Path(*windows_path.parts)
                    if "\\" in text
                    else Path(text)
                )
            else:
                raw_path = Path(text)
            source = raw_path if raw_path.is_absolute() else hdf_path.parent / raw_path
            source = source.resolve()
            key = str(source).casefold()
            if key not in seen:
                seen.add(key)
                source_paths.append(source)

        if len(source_paths) != 1:
            raise ValueError(
                f"Registered terrain {hdf_path.name!r} records {len(source_paths)} "
                "source rasters; BenefitArea requires exactly one consolidated "
                f"GeoTIFF terrain. {RasBenefits.TERRAIN_REMEDIATION}"
            )

        source_path = source_paths[0]
        if source_path.suffix.lower() not in {".tif", ".tiff"}:
            raise ValueError(
                f"Registered terrain source is not a single GeoTIFF: {source_path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Registered terrain source was not found: {source_path}. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        return source_path

    @staticmethod
    @log_call
    def validate_registered_terrain_source(
        terrain_hdf: Union[str, Path],
        terrain_tif: Union[str, Path],
    ) -> Path:
        """Require ``terrain_tif`` to be a registered HDF's sole TIFF source."""

        terrain_path = RasBenefits.validate_terrain_tif(terrain_tif).resolve()
        source_path = RasBenefits.get_registered_terrain_source(terrain_hdf)
        if source_path != terrain_path:
            raise ValueError(
                f"terrain_tif must be the single GeoTIFF recorded by the registered "
                f"terrain HDF: {source_path}. {RasBenefits.TERRAIN_REMEDIATION}"
            )
        return source_path

    @staticmethod
    def _array_and_valid_mask(
        values: np.ndarray,
        explicit_valid_mask: Optional[np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray]:
        if np.ma.isMaskedArray(values):
            data = np.asarray(np.ma.getdata(values))
            valid = ~np.ma.getmaskarray(values)
        else:
            data = np.asarray(values)
            valid = np.ones(data.shape, dtype=bool)
        if data.ndim != 2:
            raise ValueError("Depth arrays must be two-dimensional")
        valid &= np.isfinite(data)
        if explicit_valid_mask is not None:
            explicit = np.asarray(explicit_valid_mask, dtype=bool)
            if explicit.shape != data.shape:
                raise ValueError("Explicit valid mask must match the depth-array shape")
            valid &= explicit
        return data, valid

    @staticmethod
    def _classify_unfiltered(
        pre: np.ndarray,
        post: np.ndarray,
        pre_valid: np.ndarray,
        post_valid: np.ndarray,
        in_analysis: np.ndarray,
        *,
        flood_min_depth: float,
        benefit_min_depth: float,
    ) -> np.ndarray:
        """Classify one aligned in-memory window without component filtering."""

        domain = pre_valid & in_analysis
        post_valid_in_analysis = post_valid & in_analysis
        pre_flooded = domain & (pre > flood_min_depth)
        post_flooded = domain & post_valid_in_analysis & (
            post > flood_min_depth
        )

        effective_post = np.where(post_valid_in_analysis, post, 0.0)
        qualifies = pre_flooded & (
            (pre - effective_post) >= benefit_min_depth
        )

        classified = np.zeros(pre.shape, dtype=np.uint8)
        classified[domain & post_flooded & ~qualifies] = BenefitCategory.NO_CHANGE
        classified[qualifies & post_flooded] = BenefitCategory.PARTIALLY_BENEFITED
        classified[qualifies & ~post_flooded] = BenefitCategory.FULLY_BENEFITED
        return classified

    @staticmethod
    @log_call
    def classify_depth_arrays(
        pre_depth: np.ndarray,
        post_depth: np.ndarray,
        *,
        pre_valid_mask: Optional[np.ndarray] = None,
        post_valid_mask: Optional[np.ndarray] = None,
        analysis_mask: Optional[np.ndarray] = None,
        flood_min_depth: float = 0.05,
        benefit_min_depth: float = 0.25,
        minimum_region_pixels: Optional[int] = 16,
    ) -> np.ndarray:
        """Classify aligned pre/post depths into BenefitArea category codes.

        Flooding uses a strict ``>`` comparison.  Benefit uses an inclusive
        ``>=`` comparison.  Post-project NoData is dry with zero effective
        depth, but only cells valid in the pre-project raster are classified.
        """

        RasBenefits._validate_thresholds(flood_min_depth, benefit_min_depth)
        RasBenefits._validate_minimum_region_pixels(minimum_region_pixels)

        pre, pre_valid = RasBenefits._array_and_valid_mask(
            pre_depth, pre_valid_mask
        )
        post, post_valid = RasBenefits._array_and_valid_mask(
            post_depth, post_valid_mask
        )
        if pre.shape != post.shape:
            raise ValueError("Pre- and post-project depth arrays must have the same shape")

        if analysis_mask is None:
            in_analysis = np.ones(pre.shape, dtype=bool)
        else:
            in_analysis = np.asarray(analysis_mask, dtype=bool)
            if in_analysis.shape != pre.shape:
                raise ValueError("analysis_mask must match the depth-array shape")

        classified = RasBenefits._classify_unfiltered(
            pre,
            post,
            pre_valid,
            post_valid,
            in_analysis,
            flood_min_depth=flood_min_depth,
            benefit_min_depth=benefit_min_depth,
        )

        return RasBenefits.filter_small_regions(
            classified,
            minimum_region_pixels=minimum_region_pixels,
        )

    @staticmethod
    @log_call
    def filter_small_regions(
        classified: np.ndarray,
        minimum_region_pixels: Optional[int] = 16,
    ) -> np.ndarray:
        """Delete small class components using four-cell connectivity.

        Filtering is independent for classes 1-3.  Components strictly smaller
        than ``minimum_region_pixels`` are changed to NoData/background; a
        component exactly equal to the threshold is retained.
        """

        RasBenefits._validate_minimum_region_pixels(minimum_region_pixels)
        output = np.asarray(classified, dtype=np.uint8).copy()
        if output.ndim != 2:
            raise ValueError("classified must be a two-dimensional array")
        if minimum_region_pixels is None:
            return output

        structure = np.array(
            [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
            dtype=np.uint8,
        )
        threshold = int(minimum_region_pixels)
        for category in BENEFIT_STATUS:
            labels, component_count = ndimage.label(
                output == int(category),
                structure=structure,
            )
            if component_count == 0:
                continue
            sizes = np.bincount(labels.ravel())
            remove = sizes < threshold
            remove[0] = False
            output[remove[labels]] = BenefitCategory.NODATA
        return output

    @staticmethod
    def _read_depth_raster(
        path: Union[str, Path],
    ) -> Tuple[np.ndarray, np.ndarray, _RasterMetadata]:
        raster_path = Path(path)
        if not raster_path.is_file():
            raise FileNotFoundError(f"Depth raster not found: {raster_path}")
        with rasterio.open(raster_path) as src:
            if src.count != 1:
                raise ValueError(
                    f"Depth raster must contain one band, found {src.count}: {raster_path}"
                )
            if src.crs is None:
                raise ValueError(f"Depth raster has no CRS: {raster_path}")
            data = RasBenefits._read_raster_band(src)
            valid = (
                RasBenefits._read_raster_band(src, mask=True) != 0
            ) & np.isfinite(data)
            metadata = _RasterMetadata(
                width=src.width,
                height=src.height,
                transform=src.transform,
                crs=src.crs,
                bounds=src.bounds,
                profile=src.profile.copy(),
            )
        return data, valid, metadata

    @staticmethod
    def _validate_depth_grids(
        pre: _RasterMetadata,
        post: _RasterMetadata,
    ) -> None:
        same_grid = (
            pre.width == post.width
            and pre.height == post.height
            and pre.crs == post.crs
            and pre.transform.almost_equals(post.transform)
        )
        if not same_grid:
            raise ValueError(
                "Pre- and post-project Depth rasters must use the same grid "
                "(shape, CRS, resolution, and origin). Generate both maps from "
                "the same registered single-TIFF terrain."
            )

    @staticmethod
    def _validate_terrain_context(
        terrain_path: Path,
        depth: _RasterMetadata,
    ) -> None:
        with rasterio.open(terrain_path) as terrain:
            if terrain.crs != depth.crs:
                raise ValueError(
                    "Terrain and Depth rasters must use the same coordinate reference system"
                )
            terrain_bounds = terrain.bounds
            depth_bounds = depth.bounds
            coordinate_scale = max(
                1.0,
                *(abs(value) for value in (*terrain_bounds, *depth_bounds)),
            )
            # Permit only floating-point/geotransform roundoff.  A former
            # whole-cell tolerance could accept a Depth grid that genuinely
            # protruded beyond the required terrain source.
            tolerance = coordinate_scale * 1.0e-9
            terrain_footprint = Polygon(
                [
                    terrain.transform * (0, 0),
                    terrain.transform * (terrain.width, 0),
                    terrain.transform * (terrain.width, terrain.height),
                    terrain.transform * (0, terrain.height),
                ]
            )
            depth_footprint = Polygon(
                [
                    depth.transform * (0, 0),
                    depth.transform * (depth.width, 0),
                    depth.transform * (depth.width, depth.height),
                    depth.transform * (0, depth.height),
                ]
            )
            covers = terrain_footprint.buffer(tolerance).covers(depth_footprint)
            if not covers:
                raise ValueError(
                    "The required single-TIFF terrain does not cover the pre-project "
                    "Depth raster extent"
                )

    @staticmethod
    def _load_boundary_geometry(
        boundary: Any,
        target_crs: rasterio.crs.CRS,
        *,
        boundary_role: str = "boundary",
    ) -> Optional[BaseGeometry]:
        if boundary is None:
            return None

        if isinstance(boundary, BaseGeometry):
            geometry = boundary
        else:
            layer = None
            source = boundary
            if (
                isinstance(boundary, tuple)
                and len(boundary) == 2
                and isinstance(boundary[0], (str, Path))
            ):
                source, layer = boundary

            if isinstance(source, gpd.GeoDataFrame):
                frame = source.copy()
            elif isinstance(source, gpd.GeoSeries):
                frame = gpd.GeoDataFrame(geometry=source)
            elif isinstance(source, (str, Path)):
                read_kwargs = {"layer": layer} if layer is not None else {}
                frame = gpd.read_file(source, **read_kwargs)
            else:
                try:
                    geometries = list(source)
                except TypeError as exc:
                    raise TypeError(
                        "Boundary must be a geometry, GeoDataFrame, vector path, "
                        "(path, layer) tuple, or iterable of geometries"
                    ) from exc
                frame = gpd.GeoDataFrame(geometry=geometries, crs=target_crs)

            if frame.empty:
                if boundary_role == "analysis":
                    raise ValueError(
                        "analysis_boundary was supplied but contains no features"
                    )
                return None
            if frame.crs is None:
                raise ValueError("Boundary data must define a coordinate reference system")
            if frame.crs != target_crs:
                frame = frame.to_crs(target_crs)
            valid_geometries = [
                make_valid(item)
                for item in frame.geometry
                if item is not None and not item.is_empty
            ]
            if not valid_geometries:
                if boundary_role == "analysis":
                    raise ValueError(
                        "analysis_boundary was supplied but contains no valid geometry"
                    )
                return None
            geometry = unary_union(valid_geometries)

        if geometry is None or geometry.is_empty:
            if boundary_role == "analysis":
                raise ValueError(
                    "analysis_boundary was supplied but contains no valid geometry"
                )
            return None
        geometry = make_valid(geometry)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            parameter_name = f"{boundary_role}_boundary"
            raise ValueError(
                f"{parameter_name} must contain polygon geometry; "
                f"found {geometry.geom_type}"
            )
        return geometry

    @staticmethod
    def _build_analysis_mask(
        shape_: Tuple[int, int],
        transform: Affine,
        crs: rasterio.crs.CRS,
        analysis_boundary: Any,
        improvement_boundary: Any,
    ) -> np.ndarray:
        analysis = RasBenefits._load_boundary_geometry(
            analysis_boundary,
            crs,
            boundary_role="analysis",
        )
        improvement = RasBenefits._load_boundary_geometry(
            improvement_boundary,
            crs,
            boundary_role="improvement",
        )

        return RasBenefits._analysis_mask_for_window(
            shape_,
            transform,
            analysis,
            improvement,
        )

    @staticmethod
    def _analysis_mask_for_window(
        shape_: Tuple[int, int],
        transform: Affine,
        analysis: Optional[BaseGeometry],
        improvement: Optional[BaseGeometry],
    ) -> np.ndarray:
        """Rasterize effective analysis bounds at cell centers for one window."""

        if analysis is None:
            mask = np.ones(shape_, dtype=bool)
        else:
            mask = geometry_mask(
                [mapping(analysis)],
                out_shape=shape_,
                transform=transform,
                all_touched=False,
                invert=True,
            )

        if improvement is not None:
            improvement_mask = geometry_mask(
                [mapping(improvement)],
                out_shape=shape_,
                transform=transform,
                all_touched=False,
                invert=True,
            )
            mask &= ~improvement_mask
        return mask

    @staticmethod
    def _statistics(
        classified: np.ndarray,
        transform: Affine,
        crs: rasterio.crs.CRS,
    ) -> Dict[str, Dict[str, Union[int, float]]]:
        counts = {
            int(category): int(np.count_nonzero(classified == int(category)))
            for category in BENEFIT_STATUS
        }
        return RasBenefits._statistics_from_counts(counts, transform, crs)

    @staticmethod
    def _statistics_from_counts(
        counts: Dict[int, int],
        transform: Affine,
        crs: rasterio.crs.CRS,
    ) -> Dict[str, Dict[str, Union[int, float]]]:
        pixel_area = abs(transform.determinant)
        pyproj_crs = PyprojCRS.from_user_input(crs)
        horizontal_axis = pyproj_crs.axis_info[0]
        unit_name = str(horizontal_axis.unit_name or "").casefold()
        if "foot" in unit_name or "feet" in unit_name:
            # Engineering acre accounting is 43,560 square feet for either
            # international-foot or US-survey-foot projected grids.
            acre_conversion = 1.0 / 43560.0
        else:
            unit_to_metre = horizontal_axis.unit_conversion_factor
            acre_conversion = (unit_to_metre ** 2) / 4046.8564224

        statistics: Dict[str, Dict[str, Union[int, float]]] = {}
        for category, status in BENEFIT_STATUS.items():
            cell_count = int(counts.get(int(category), 0))
            area_map_units = float(cell_count * pixel_area)
            statistics[status] = {
                "code": int(category),
                "cell_count": cell_count,
                "area_map_units": area_map_units,
                "area_acres": float(area_map_units * acre_conversion),
            }
        return statistics

    @staticmethod
    def _output_profile(source: _RasterMetadata) -> Dict[str, Any]:
        profile = source.profile.copy()
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile.update(
            driver="GTiff",
            dtype="uint8",
            count=1,
            nodata=int(BenefitCategory.NODATA),
            compress="DEFLATE",
            predictor=1,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            BIGTIFF="IF_SAFER",
        )
        profile.pop("photometric", None)
        return profile

    @staticmethod
    def _write_raster_metadata(
        dst,
        *,
        pre_depth_path: Path,
        post_depth_path: Path,
        terrain_path: Path,
        flood_min_depth: float,
        benefit_min_depth: float,
        minimum_region_pixels: Optional[int],
    ) -> None:
        dst.set_band_description(1, "Benefit Area")
        dst.write_colormap(
            1,
            {int(key): value for key, value in BENEFIT_COLORMAP.items()},
        )
        dst.update_tags(
            benefit_area_schema="benefit-area-depth-v1",
            class_0="NoData / Unclassified",
            class_1="No Change",
            class_2="Partially Benefited",
            class_3="Fully Benefited",
            flood_min_depth=str(flood_min_depth),
            benefit_min_depth=str(benefit_min_depth),
            minimum_region_pixels=(
                "disabled"
                if minimum_region_pixels is None
                else str(minimum_region_pixels)
            ),
            connectivity="4",
            pre_depth=str(pre_depth_path),
            post_depth=str(post_depth_path),
            terrain_tif=str(terrain_path),
        )

    @staticmethod
    def _iter_windows(
        width: int,
        height: int,
        window_size: int = 1024,
    ):
        """Yield bounded-memory raster windows independent of source tiling."""

        for row_off in range(0, height, window_size):
            window_height = min(window_size, height - row_off)
            for col_off in range(0, width, window_size):
                window_width = min(window_size, width - col_off)
                yield Window(col_off, row_off, window_width, window_height)

    @staticmethod
    def _metadata_from_dataset(src, path: Path) -> _RasterMetadata:
        if src.count != 1:
            raise ValueError(
                f"Depth raster must contain one band, found {src.count}: {path}"
            )
        if src.crs is None:
            raise ValueError(f"Depth raster has no CRS: {path}")
        if src.transform.is_identity or abs(src.transform.determinant) == 0:
            raise ValueError(
                f"Depth raster does not have a valid georeferencing transform: {path}"
            )
        return _RasterMetadata(
            width=src.width,
            height=src.height,
            transform=src.transform,
            crs=src.crs,
            bounds=src.bounds,
            profile=src.profile.copy(),
        )

    @staticmethod
    def _classify_to_raster(
        pre_src,
        post_src,
        output_path: Path,
        source: _RasterMetadata,
        *,
        analysis: Optional[BaseGeometry],
        improvement: Optional[BaseGeometry],
        flood_min_depth: float,
        benefit_min_depth: float,
        pre_depth_path: Path,
        post_depth_path: Path,
        terrain_path: Path,
        minimum_region_pixels: Optional[int],
        window_size: int = 1024,
    ) -> Dict[int, int]:
        """Classify aligned rasters by window into a provisional uint8 TIFF."""

        counts = {int(category): 0 for category in BENEFIT_STATUS}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            output_path,
            "w",
            **RasBenefits._output_profile(source),
        ) as dst:
            RasBenefits._write_raster_metadata(
                dst,
                pre_depth_path=pre_depth_path,
                post_depth_path=post_depth_path,
                terrain_path=terrain_path,
                flood_min_depth=flood_min_depth,
                benefit_min_depth=benefit_min_depth,
                minimum_region_pixels=minimum_region_pixels,
            )
            for window in RasBenefits._iter_windows(
                source.width,
                source.height,
                window_size,
            ):
                pre = RasBenefits._read_raster_band(pre_src, window=window)
                post = RasBenefits._read_raster_band(post_src, window=window)
                pre_valid = (
                    RasBenefits._read_raster_band(
                        pre_src,
                        window=window,
                        mask=True,
                    )
                    != 0
                ) & np.isfinite(pre)
                post_valid = (
                    RasBenefits._read_raster_band(
                        post_src,
                        window=window,
                        mask=True,
                    )
                    != 0
                ) & np.isfinite(post)
                window_shape = (int(window.height), int(window.width))
                analysis_mask = RasBenefits._analysis_mask_for_window(
                    window_shape,
                    pre_src.window_transform(window),
                    analysis,
                    improvement,
                )
                classified = RasBenefits._classify_unfiltered(
                    pre,
                    post,
                    pre_valid,
                    post_valid,
                    analysis_mask,
                    flood_min_depth=flood_min_depth,
                    benefit_min_depth=benefit_min_depth,
                )
                dst.write(classified, 1, window=window)
                window_counts = np.bincount(classified.ravel(), minlength=4)
                for category in BENEFIT_STATUS:
                    counts[int(category)] += int(window_counts[int(category)])
        return counts

    @staticmethod
    def _copy_classified_raster(
        source_path: Path,
        output_path: Path,
        source: _RasterMetadata,
        *,
        pre_depth_path: Path,
        post_depth_path: Path,
        terrain_path: Path,
        flood_min_depth: float,
        benefit_min_depth: float,
        minimum_region_pixels: Optional[int],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(source_path) as src, rasterio.open(
            output_path,
            "w",
            **RasBenefits._output_profile(source),
        ) as dst:
            RasBenefits._write_raster_metadata(
                dst,
                pre_depth_path=pre_depth_path,
                post_depth_path=post_depth_path,
                terrain_path=terrain_path,
                flood_min_depth=flood_min_depth,
                benefit_min_depth=benefit_min_depth,
                minimum_region_pixels=minimum_region_pixels,
            )
            for _, window in src.block_windows(1):
                dst.write(
                    RasBenefits._read_raster_band(src, window=window),
                    1,
                    window=window,
                )

    @staticmethod
    def _filter_raster_components(
        provisional_path: Path,
        output_path: Path,
        source: _RasterMetadata,
        counts: Dict[int, int],
        minimum_region_pixels: int,
        *,
        pre_depth_path: Path,
        post_depth_path: Path,
        terrain_path: Path,
        flood_min_depth: float,
        benefit_min_depth: float,
    ) -> Dict[int, int]:
        """Apply a global four-connected pixel sieve without full-array labels."""

        RasBenefits._copy_classified_raster(
            provisional_path,
            output_path,
            source,
            pre_depth_path=pre_depth_path,
            post_depth_path=post_depth_path,
            terrain_path=terrain_path,
            flood_min_depth=flood_min_depth,
            benefit_min_depth=benefit_min_depth,
            minimum_region_pixels=minimum_region_pixels,
        )
        filtered_counts = dict(counts)
        pixel_area = abs(source.transform.determinant)

        with rasterio.open(provisional_path) as src, rasterio.open(
            output_path,
            "r+",
        ) as dst:
            components = shapes(
                rasterio.band(src, 1),
                mask=rasterio.band(src, 1),
                connectivity=4,
                transform=source.transform,
            )
            for geometry_mapping, value in components:
                code = int(value)
                if code not in filtered_counts:
                    continue
                geometry = shape(geometry_mapping)
                cell_count = int(round(abs(geometry.area) / pixel_area))
                if cell_count >= minimum_region_pixels:
                    continue

                window = geometry_window(dst, [geometry_mapping])
                data = RasBenefits._read_raster_band(dst, window=window)
                component_mask = geometry_mask(
                    [geometry_mapping],
                    out_shape=(int(window.height), int(window.width)),
                    transform=dst.window_transform(window),
                    all_touched=False,
                    invert=True,
                )
                remove = component_mask & (data == code)
                removed_count = int(np.count_nonzero(remove))
                if removed_count:
                    data[remove] = int(BenefitCategory.NODATA)
                    dst.write(data, 1, window=window)
                    filtered_counts[code] -= removed_count
        return filtered_counts

    @staticmethod
    def _require_geoparquet_support() -> None:
        """Fail early with the installation command required for GeoParquet."""

        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "GeoParquet polygon output requires the optional 'pyarrow' "
                "dependency. Install it with "
                "`pip install 'ras-commander[geoparquet]'`."
            ) from exc

    @staticmethod
    def _write_polygons(
        polygon_path: Path,
        raster_path: Path,
        source: _RasterMetadata,
        statistics: Dict[str, Dict[str, Union[int, float]]],
        *,
        simplify_tolerance: Optional[float] = None,
    ) -> Path:
        if polygon_path.suffix.lower() in {".parquet", ".geoparquet"}:
            RasBenefits._require_geoparquet_support()

        grouped: Dict[int, list[BaseGeometry]] = {
            int(category): [] for category in BENEFIT_STATUS
        }
        with rasterio.open(raster_path) as src:
            for geometry_mapping, value in shapes(
                rasterio.band(src, 1),
                mask=rasterio.band(src, 1),
                connectivity=4,
                transform=source.transform,
            ):
                code = int(value)
                if code in grouped:
                    grouped[code].append(shape(geometry_mapping))

        records = []
        for category, status in BENEFIT_STATUS.items():
            geometries = grouped[int(category)]
            if not geometries:
                continue
            geometry = unary_union(geometries)
            if simplify_tolerance:
                geometry = geometry.simplify(
                    float(simplify_tolerance),
                    preserve_topology=True,
                )
            record = {
                "benefit_code": int(category),
                "benefit_status": status,
                "condition": "Post Project",
                "cell_count": statistics[status]["cell_count"],
                "area_map_units": statistics[status]["area_map_units"],
                "area_acres": statistics[status]["area_acres"],
                "geometry": geometry,
            }
            records.append(record)

        if records:
            frame = gpd.GeoDataFrame(records, geometry="geometry", crs=source.crs)
        else:
            frame = gpd.GeoDataFrame(
                columns=[
                    "benefit_code",
                    "benefit_status",
                    "condition",
                    "cell_count",
                    "area_map_units",
                    "area_acres",
                    "geometry",
                ],
                geometry="geometry",
                crs=source.crs,
            )
        polygon_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = polygon_path.suffix.lower()
        if suffix == ".gpkg":
            frame.to_file(polygon_path, layer="benefit_area", driver="GPKG")
        elif suffix == ".shp":
            frame.to_file(polygon_path, driver="ESRI Shapefile")
        elif suffix in {".geojson", ".json"}:
            frame.to_file(polygon_path, driver="GeoJSON")
        elif suffix in {".parquet", ".geoparquet"}:
            frame.to_parquet(polygon_path, compression="zstd")
        else:
            raise ValueError(
                "polygon_output must use .gpkg, .shp, .geojson, or .parquet"
            )
        return polygon_path

    @staticmethod
    def _polygon_dataset_files(path: Path) -> list[Path]:
        """Return a staged vector's files, including Shapefile sidecars."""

        if path.suffix.lower() != ".shp":
            return [path] if path.exists() else []
        shapefile_suffixes = {
            ".shp",
            ".shx",
            ".dbf",
            ".prj",
            ".cpg",
            ".qix",
            ".sbn",
            ".sbx",
            ".fbn",
            ".fbx",
            ".ain",
            ".aih",
            ".ixs",
            ".mxs",
            ".shp.xml",
        }
        files = []
        for candidate in path.parent.glob(f"{path.stem}.*"):
            trailing_name = candidate.name[len(path.stem):].lower()
            if trailing_name in shapefile_suffixes or trailing_name.startswith(".atx"):
                files.append(candidate)
        return sorted(files)

    @staticmethod
    def _publish_staged_polygon(staged_path: Path, output_path: Path) -> None:
        """Publish a completely written staged polygon dataset."""

        if output_path.suffix.lower() != ".shp":
            os.replace(staged_path, output_path)
            return

        staged_files = RasBenefits._polygon_dataset_files(staged_path)
        if not any(item.suffix.lower() == ".shp" for item in staged_files):
            raise RuntimeError("Staged BenefitArea Shapefile is incomplete")
        for staged_file in staged_files:
            trailing_name = staged_file.name[len(staged_path.stem):]
            destination = output_path.with_name(output_path.stem + trailing_name)
            os.replace(staged_file, destination)

    @staticmethod
    def _publish_output_transaction(
        staged_raster_path: Path,
        output_raster_path: Path,
        staged_polygon_path: Optional[Path] = None,
        output_polygon_path: Optional[Path] = None,
    ) -> None:
        """Publish raster/vector outputs together and roll back on failure."""

        if (staged_polygon_path is None) != (output_polygon_path is None):
            raise ValueError(
                "staged_polygon_path and output_polygon_path must be supplied together"
            )

        existing_paths = (
            [output_raster_path] if output_raster_path.exists() else []
        )
        if output_polygon_path is not None:
            existing_paths.extend(
                RasBenefits._polygon_dataset_files(output_polygon_path)
            )

        backups: list[Tuple[Path, Path]] = []
        try:
            for original in existing_paths:
                backup = original.with_name(
                    f".{original.name}.{uuid4().hex}.rollback"
                )
                os.replace(original, backup)
                backups.append((original, backup))
        except Exception:
            for original, backup in reversed(backups):
                if backup.exists():
                    os.replace(backup, original)
            raise

        try:
            os.replace(staged_raster_path, output_raster_path)
            if staged_polygon_path is not None and output_polygon_path is not None:
                RasBenefits._publish_staged_polygon(
                    staged_polygon_path,
                    output_polygon_path,
                )
        except Exception as publication_error:
            cleanup_errors = []
            try:
                output_raster_path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append((output_raster_path, exc))
            if output_polygon_path is not None:
                for published_file in RasBenefits._polygon_dataset_files(
                    output_polygon_path
                ):
                    try:
                        published_file.unlink(missing_ok=True)
                    except OSError as exc:
                        cleanup_errors.append((published_file, exc))

            restore_errors = []
            for original, backup in reversed(backups):
                if not backup.exists():
                    continue
                try:
                    os.replace(backup, original)
                except OSError as exc:
                    restore_errors.append((original, exc))
            if restore_errors:
                details = "; ".join(
                    f"{path}: {error}" for path, error in restore_errors
                )
                raise RuntimeError(
                    "BenefitArea output publication failed and rollback was "
                    f"incomplete: {details}"
                ) from publication_error
            if cleanup_errors:
                logger.warning(
                    "BenefitArea rollback could not remove %d partially "
                    "published file(s); prior outputs were restored",
                    len(cleanup_errors),
                )
            raise
        else:
            for _, backup in backups:
                try:
                    backup.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(
                        "Could not remove BenefitArea rollback file %s: %s",
                        backup,
                        exc,
                    )

    @staticmethod
    @_serialize_benefit_outputs
    @log_call
    def create_benefit_area(
        pre_depth_tif: Union[str, Path],
        post_depth_tif: Union[str, Path],
        terrain_tif: Union[str, Path],
        output_tif: Union[str, Path],
        *,
        flood_min_depth: float = 0.05,
        benefit_min_depth: float = 0.25,
        minimum_region_pixels: Optional[int] = 16,
        analysis_boundary: Any = None,
        improvement_boundary: Any = None,
        polygon_output: Optional[Union[bool, str, Path]] = None,
        polygon_simplify_tolerance: Optional[float] = None,
        lock_timeout: float = 600.0,
    ) -> BenefitAreaResult:
        """Create a categorical BenefitArea GeoTIFF and optional polygon file."""

        terrain_path = RasBenefits.validate_terrain_tif(terrain_tif)
        pre_depth_path = Path(pre_depth_tif)
        post_depth_path = Path(post_depth_tif)
        output_path = Path(output_tif)
        if output_path.suffix.lower() not in {".tif", ".tiff"}:
            raise ValueError("output_tif must be a GeoTIFF path")
        if not pre_depth_path.is_file():
            raise FileNotFoundError(f"Depth raster not found: {pre_depth_path}")
        if not post_depth_path.is_file():
            raise FileNotFoundError(f"Depth raster not found: {post_depth_path}")
        RasBenefits._validate_thresholds(flood_min_depth, benefit_min_depth)
        RasBenefits._validate_minimum_region_pixels(minimum_region_pixels)
        RasBenefits._validate_polygon_simplify_tolerance(
            polygon_simplify_tolerance
        )

        resolved_inputs = {
            path.resolve()
            for path in (pre_depth_path, post_depth_path, terrain_path)
        }
        if output_path.resolve() in resolved_inputs:
            raise ValueError(
                "output_tif must not overwrite a pre Depth, post Depth, or terrain input"
            )

        polygon_path: Optional[Path] = None
        if polygon_output:
            polygon_path = (
                output_path.with_suffix(".gpkg")
                if polygon_output is True
                else Path(polygon_output)
            )
            if polygon_path.suffix.lower() not in {
                ".gpkg",
                ".shp",
                ".geojson",
                ".json",
                ".parquet",
                ".geoparquet",
            }:
                raise ValueError(
                    "polygon_output must use .gpkg, .shp, .geojson, or .parquet"
                )
            if polygon_path.suffix.lower() in {".parquet", ".geoparquet"}:
                RasBenefits._require_geoparquet_support()
            protected_vectors = []
            for boundary in (analysis_boundary, improvement_boundary):
                source = boundary[0] if isinstance(boundary, tuple) else boundary
                if isinstance(source, (str, Path)):
                    protected_vectors.append(Path(source).resolve())
            if polygon_path.resolve() in resolved_inputs or (
                polygon_path.resolve() in protected_vectors
            ):
                raise ValueError("polygon_output must not overwrite an input dataset")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        staged_output_path = output_path.with_name(
            f".{output_path.stem}.{uuid4().hex}.staged{output_path.suffix}"
        )
        provisional_path = staged_output_path
        temporary_provisional = minimum_region_pixels is not None
        if temporary_provisional:
            provisional_path = output_path.with_name(
                f".{output_path.stem}.{uuid4().hex}.unfiltered.tif"
            )

        staged_polygon_path: Optional[Path] = None
        try:
            # GDAL otherwise caches about 5% of physical RAM (3.2 GiB on the
            # validation workstation).  A fixed cache keeps production-scale
            # benefits generation bounded independently of host memory.
            with rasterio.Env(GDAL_CACHEMAX=256 * 1024 * 1024):
                with rasterio.open(pre_depth_path) as pre_src, rasterio.open(
                    post_depth_path
                ) as post_src:
                    pre_meta = RasBenefits._metadata_from_dataset(
                        pre_src,
                        pre_depth_path,
                    )
                    post_meta = RasBenefits._metadata_from_dataset(
                        post_src,
                        post_depth_path,
                    )
                    RasBenefits._validate_depth_grids(pre_meta, post_meta)
                    RasBenefits._validate_terrain_context(terrain_path, pre_meta)

                    analysis = RasBenefits._load_boundary_geometry(
                        analysis_boundary,
                        pre_meta.crs,
                        boundary_role="analysis",
                    )
                    improvement = RasBenefits._load_boundary_geometry(
                        improvement_boundary,
                        pre_meta.crs,
                        boundary_role="improvement",
                    )
                    counts = RasBenefits._classify_to_raster(
                        pre_src,
                        post_src,
                        provisional_path,
                        pre_meta,
                        analysis=analysis,
                        improvement=improvement,
                        flood_min_depth=flood_min_depth,
                        benefit_min_depth=benefit_min_depth,
                        pre_depth_path=pre_depth_path,
                        post_depth_path=post_depth_path,
                        terrain_path=terrain_path,
                        minimum_region_pixels=minimum_region_pixels,
                    )

                if minimum_region_pixels is not None:
                    counts = RasBenefits._filter_raster_components(
                        provisional_path,
                        staged_output_path,
                        pre_meta,
                        counts,
                        int(minimum_region_pixels),
                        pre_depth_path=pre_depth_path,
                        post_depth_path=post_depth_path,
                        terrain_path=terrain_path,
                        flood_min_depth=flood_min_depth,
                        benefit_min_depth=benefit_min_depth,
                    )

                with rasterio.open(staged_output_path) as staged:
                    if (
                        staged.count != 1
                        or staged.width != pre_meta.width
                        or staged.height != pre_meta.height
                        or staged.crs != pre_meta.crs
                    ):
                        raise RuntimeError(
                            "Staged BenefitArea raster failed output validation"
                        )

            statistics = RasBenefits._statistics_from_counts(
                counts,
                pre_meta.transform,
                pre_meta.crs,
            )
            with rasterio.open(staged_output_path, "r+") as staged:
                staged.update_tags(
                    benefit_statistics=json.dumps(
                        statistics,
                        sort_keys=True,
                    )
                )

            # Polygonize this call's private staged raster.  This prevents a
            # concurrent writer from swapping the shared destination between
            # classification and polygonization, and a polygon-generation
            # failure leaves any prior authoritative raster untouched.
            if polygon_path is not None:
                staged_polygon_path = polygon_path.with_name(
                    f".{polygon_path.stem}.{uuid4().hex}.staged"
                    f"{polygon_path.suffix}"
                )
                with rasterio.Env(GDAL_CACHEMAX=256 * 1024 * 1024):
                    RasBenefits._write_polygons(
                        staged_polygon_path,
                        staged_output_path,
                        pre_meta,
                        statistics,
                        simplify_tolerance=polygon_simplify_tolerance,
                    )
            RasBenefits._publish_output_transaction(
                staged_output_path,
                output_path,
                staged_polygon_path,
                polygon_path,
            )
        finally:
            if temporary_provisional and provisional_path.exists():
                try:
                    provisional_path.unlink()
                except OSError as exc:
                    logger.warning(
                        "Could not remove BenefitArea provisional raster %s: %s",
                        provisional_path,
                        exc,
                    )
            if staged_output_path.exists():
                try:
                    staged_output_path.unlink()
                except OSError as exc:
                    logger.warning(
                        "Could not remove BenefitArea staged raster %s: %s",
                        staged_output_path,
                        exc,
                    )
            if staged_polygon_path is not None:
                for staged_file in RasBenefits._polygon_dataset_files(
                    staged_polygon_path
                ):
                    try:
                        staged_file.unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(
                            "Could not remove BenefitArea staged vector file %s: %s",
                            staged_file,
                            exc,
                        )

        logger.info(
            "BenefitArea complete: classes=%d; cells=%d; polygon=%s",
            sum(1 for values in statistics.values() if values["cell_count"]),
            sum(int(values["cell_count"]) for values in statistics.values()),
            polygon_path is not None,
        )
        logger.debug("BenefitArea raster path: %s", output_path)
        if polygon_path is not None:
            logger.debug("BenefitArea polygon path: %s", polygon_path)

        return BenefitAreaResult(
            raster_path=output_path,
            polygon_path=polygon_path,
            pre_depth_path=pre_depth_path,
            post_depth_path=post_depth_path,
            terrain_path=terrain_path,
            statistics=statistics,
            flood_min_depth=flood_min_depth,
            benefit_min_depth=benefit_min_depth,
            minimum_region_pixels=minimum_region_pixels,
            polygon_simplify_tolerance=polygon_simplify_tolerance,
        )
