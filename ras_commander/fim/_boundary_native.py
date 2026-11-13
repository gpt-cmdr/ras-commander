"""Explicitly gated native-order contour delivery over canonical model inputs."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import math
import os
import shutil
import subprocess
import tempfile
import time

from .. import log_call
from . import _aoi, _boundary, _boundary_inputs, _boundary_model, _engine, _one_d, _sloping, _storage_areas
from ._boundary_terrain_sources import stage_native_terrain_sources
from ._horizontal_engine import _write_geometry
from .errors import FimEngineError, FimGeometryError, FimUnsupportedError

METHOD_ID = "rasmapper-serial-zero-depth-contours/1"
REQUEST_SCHEMA = "ras-commander-boundary-request/2"
AOI_CLIPPING_METHOD = "unrounded-geos-intersection/1"


def _terrain_header(hdf, terrain, declared_crs=None):
    import rasterio
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from ..hdf.HdfBase import HdfBase
    from ._source_crs import source_crs

    with rasterio.open(terrain) as source:
        # A RAS Mapper source with no CRS tags takes the terrain HDF's CRS (crs_any only).
        crs = source_crs(source.crs) if source.crs else (
            source_crs(declared_crs) if declared_crs is not None else None)
        gt = source.transform.to_gdal()
        if (crs is None or not crs.is_projected
                or any(abs(axis.unit_conversion_factor - 1200 / 3937) > 1e-12 for axis in crs.axis_info[:2])):
            raise FimUnsupportedError("native boundaries require a projected CRS in US survey feet; explicit conversion required")
        if (source.driver != "GTiff" or source.count != 1 or source.dtypes != ("float32",)
                or source.block_shapes != [(256, 256)] or not source.profile.get("tiled", False)
                or gt[1] <= 0 or gt[1] != -gt[5] or gt[2] or gt[4]
                or not all(math.isfinite(v) for v in gt)
                or source.nodata is None or not math.isfinite(source.nodata)
                or source.scales != (1.0,) or source.offsets != (0.0,)):
            raise FimUnsupportedError("native boundaries require original unmodified float32 256-tiled terrain")
        shape = [source.height, source.width]
    try:
        model_crs = source_crs(HdfBase.get_projection(hdf))
    except (CRSError, ValueError, TypeError) as exc:
        raise FimUnsupportedError("model has no valid projected CRS") from exc
    if crs != model_crs:
        raise FimUnsupportedError("model and terrain CRS differ; no relabelling or reprojection")
    units = HdfBase.get_result_unit_metadata(hdf)
    if units.get("unit_system") != "US Customary" or units.get("warnings") or units.get("contradictions"):
        raise FimUnsupportedError("native boundaries require unambiguous English result units")
    return crs, shape, list(gt), units


def _absolute(path, root):
    path = Path(path)
    return str((path if path.is_absolute() else root / path).resolve(strict=True))


def _validate_aoi_source(shape, transform, geometry, additional_terrains=()):
    if geometry is None:
        return
    if geometry.has_z or getattr(geometry, "has_m", False):
        raise FimUnsupportedError("native boundary AOIs require two-dimensional XY polygons")
    left, bottom, right, top = geometry.bounds
    grids = [(shape, transform)] + [(source["terrain_metadata"]["shape"],
        source["terrain_metadata"]["transform"]) for source in additional_terrains]
    for grid_shape, grid_transform in grids:
        x, dx, _, y, _, dy = grid_transform
        if (right > x and left < x + grid_shape[1] * dx
                and top > y + grid_shape[0] * dy and bottom < y):
            return
    raise FimUnsupportedError("Native boundary AOI does not intersect any original terrain sample grid")


def _watch_terrain_sources(staged, primary, terrain_hdf, watched, snapshots, hashes):
    """Bind the ordered preparation receipt to every original source through use."""
    records = staged.get("source_identities")
    extras = staged.get("additional_terrains")
    hdf_record = staged.get("terrain_hdf_identity")
    if (not isinstance(records, list) or not records or not isinstance(extras, list)
            or len(records) != len(extras) + 1 or not isinstance(hdf_record, dict)):
        raise FimEngineError("Native terrain source receipt cardinality is invalid")
    expected = [primary] + [Path(source["terrain"]).resolve(strict=True) for source in extras]
    if len(set(expected)) != len(expected):
        raise FimEngineError("Native terrain source receipt repeats a TIFF")
    for index, (record, path) in enumerate(zip(records, expected)):
        if (not isinstance(record, dict) or isinstance(record.get("effective_index"), bool)
                or record.get("effective_index") != index
                or record.get("path") != str(path)
                or record.get("size") != path.stat().st_size
                or record.get("mtime_ns") != path.stat().st_mtime_ns
                or not isinstance(record.get("sha256"), str)
                or len(record["sha256"]) != 64):
            raise FimEngineError("Native terrain ordered source receipt differs from its original TIFF")
        key = "terrain" if index == 0 else f"terrain_source_{index:04d}"
        if key in hashes and hashes[key] != record["sha256"]:
            raise FimEngineError("Native terrain source changed after initial admission")
        watched[key], snapshots[key], hashes[key] = path, (record["size"], record["mtime_ns"]), record["sha256"]
    if (hdf_record.get("path") != str(terrain_hdf)
            or (hdf_record.get("size"), hdf_record.get("mtime_ns")) != snapshots["terrain_hdf"]
            or hdf_record.get("sha256") != hashes["terrain_hdf"]):
        raise FimEngineError("Native terrain HDF receipt differs from admitted terrain")
    evidence = staged.get("terrain_crs_evidence", {})
    if evidence.get("kind") == "registered-vrt-source-identity/1":
        path = terrain_hdf.with_suffix(".vrt")
        if (evidence.get("path") != str(path) or path.is_symlink()
                or evidence.get("source_files") != [str(p) for p in expected]
                or evidence.get("size") != path.stat().st_size
                or evidence.get("mtime_ns") != path.stat().st_mtime_ns
                or not isinstance(evidence.get("sha256"), str) or len(evidence["sha256"]) != 64):
            raise FimEngineError("Native registered terrain VRT receipt is inconsistent")
        watched["terrain_crs_vrt"] = path
        snapshots["terrain_crs_vrt"] = (evidence["size"], evidence["mtime_ns"])
        hashes["terrain_crs_vrt"] = evidence["sha256"]


def _stage_storage(hdf, root, selected, budget):
    areas = _storage_areas.read(hdf, max_bytes=budget // 4,
                              geometry_policy=_storage_areas.NATIVE_EVEN_ODD)
    if areas is None:
        raise FimUnsupportedError("declared storage scope has no canonical storage polygons")
    if len(areas) * len(selected) * 4 > budget // 4:
        raise FimUnsupportedError("storage profile staging exceeds boundary preparation admission")
    values = _storage_areas.profile_values(hdf, areas, selected, max_bytes=budget // 4)
    fields = _storage_areas.stage_polygons(areas, root)
    return {"count": fields["storage_area_count"], "names": list(areas.names),
            "polygons": _absolute(fields["storage_areas_file"], root),
            "levels": [_absolute(_storage_areas.stage_values(root, name, values[name]), root)
                       for name in selected], "geometry": _storage_areas.geometry_metadata(areas)}


@contextmanager
def _prepare(hdf, terrain, root, selected, scope, engine, threads, working_mib,
             prepared_mib, terrain_pin):
    import shapely
    from .RasFim import RasFim

    dimension = scope.dimension
    if dimension == "2d":
        with RasFim.prepare_sloping_model(hdf, terrain, profiles=selected,
                engine_path=engine, threads=threads, max_working_mib=working_mib,
                max_prepared_mib=prepared_mib, native_session=False,
                terrain_crs_fnv1a64=terrain_pin) as context:
            context._check_sources()
            _boundary._validate_cells(context._cells)
            native_root = Path(context._temporary.name)
            coordinates = int(shapely.count_coordinates(context._cells.geometry.to_numpy()))
            retained = context._info["planned_prepared_bytes"] + coordinates * 20 + len(context._cells) * 128
            if retained > prepared_mib << 20:
                raise FimUnsupportedError("native boundary geometry exceeds max_prepared_mib")
            geometry = root / "boundary-cells.wkb"
            _write_geometry(geometry, context._cells.geometry.to_numpy())
            lookup = {mesh["mesh_name"]: i for i, mesh in enumerate(context._meshes)}
            profiles = []
            for name in selected:
                unit = deepcopy(context._units[name])
                unit["values_files"] = [_absolute(path, native_root) for path in unit["values_files"]]
                profiles.append(unit)
            mesh = {"geometry_file": str(geometry),
                    "mesh_files": [_absolute(path, native_root) for path in context._mesh_files],
                    "owner_cells": [[lookup[row.mesh_name], int(row.cell_id)]
                                    for row in context._cells.itertuples()], "profiles": profiles}
            storage = (_stage_storage(hdf, root, selected, prepared_mib << 20)
                       if scope.storage_area_names else None)
            yield {"mesh": mesh, "storage": storage, "xs": None, "receipt": None,
                   "retained": retained, "check": context._check_sources}
            context._check_sources()
    elif dimension in ("1d", "mixed_1d_2d"):
        with _boundary_model.prepare_boundary_xs(hdf, terrain, root, selected,
                engine_path=engine, threads=threads,
                max_working_mib=min(working_mib, prepared_mib),
                scope="one_d" if dimension == "1d" else "coupled") as inputs:
            receipt = inputs["receipt"]
            retained = (receipt["point_count"] * 128 + receipt["triangle_count"] * 256
                        + receipt["cross_section_count"] * 64)
            yield {**inputs, "retained": retained, "check": lambda: None}
    elif dimension == "storage_only":
        storage = _stage_storage(hdf, root, selected, prepared_mib << 20)
        yield {"mesh": None, "storage": storage, "xs": None, "receipt": None,
               "retained": 0, "check": lambda: None}
    else:
        raise FimUnsupportedError("unsupported native boundary model dimension")


def _report(report, selected, interpolation, threads, inflight, working, exit_code, diagnostics):
    if (not isinstance(report, dict) or exit_code != 0
            or report.get("schema") != "ras-commander-boundary-report/1"
            or report.get("status") != "complete" or not isinstance(report.get("method"), dict)
            or report["method"].get("method_id") != METHOD_ID
            or report.get("interpolation") != interpolation):
        raise FimEngineError(f"Native boundary engine/report mismatch (exit {exit_code}): {diagnostics[-8192:]}")
    def integer(key):
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FimEngineError(f"Native boundary report {key} must be a nonnegative integer")
        return value
    effective = integer("effective_inflight_profiles")
    allowance = integer("per_profile_contour_budget_bytes")
    if (integer("threads") != threads or not 1 <= effective <= min(threads, inflight, len(selected))
            or not allowance or integer("planned_shared_bytes") + effective * allowance > working):
        raise FimEngineError("Native boundary report concurrency/memory differs from request")
    if any(not _boundary._finite(report.get(key)) or report[key] < 0
           for key in ("prepare_seconds", "render_seconds")):
        raise FimEngineError("Native boundary report timing is invalid")
    units = report.get("profiles")
    if (not isinstance(units, list) or not all(isinstance(unit, dict) for unit in units)
            or [unit.get("id") for unit in units] != list(selected)):
        raise FimEngineError("Native boundary report profile identities/order differ")
    return units


def _clip_product(product, geometry, full_counts, max_working_bytes):
    """Apply only final GIS delivery intersection; retain original double XY."""
    import numpy as np
    import shapely
    from shapely.geometry import MultiPolygon, mapping, shape
    from ._boundary_comparison import _polygonal

    planned = (full_counts[2] + int(shapely.count_coordinates(geometry))) * 768 + 65536
    if planned > max_working_bytes:
        raise FimUnsupportedError("native boundary GIS clipping exceeds planned working bytes")
    feature = product["features"][0]
    clipped = _polygonal(shape(feature["geometry"]).intersection(geometry))
    if clipped.is_empty:
        clipped = MultiPolygon([])
    elif clipped.geom_type == "Polygon":
        clipped = MultiPolygon([clipped])
    if clipped.geom_type != "MultiPolygon" or not shapely.is_valid(clipped):
        raise FimEngineError("native boundary final GIS clipping produced invalid polygon geometry")
    polygons = len(clipped.geoms)
    holes = sum(len(polygon.interiors) for polygon in clipped.geoms)
    vertices = int(shapely.count_coordinates(clipped))
    area = float(clipped.area)
    if not math.isfinite(area) or not bool(np.isfinite(shapely.get_coordinates(clipped)).all()):
        raise FimEngineError("native boundary final GIS clipping produced nonfinite coordinates/area")
    feature["geometry"] = mapping(clipped)
    feature["properties"]["aoi_clipping_method"] = AOI_CLIPPING_METHOD
    return product, (polygons, holes, vertices, area)


@log_call
def map_native_boundaries(hdf_path, terrain_path, output_folder, *, terrain_hdf,
        profiles=None, interpolation="sloping", bbox=None, polygon=None,
        polygon_layer=None, aoi_crs=None, engine_path=None, threads=1,
        max_inflight_profiles=1, max_working_mib=1024, max_prepared_mib=1024,
        timeout=None, terrain_crs_fnv1a64=None, allow_unqualified=False,
        preserve_raw_geometry=False):
    """Map canonical signed surfaces with explicit unqualified native-order opt-in.

    Terrain sampling and vector merging run in Rust. Commander applies any final
    AOI through an unrounded GIS intersection after validating full engine vectors.
    Original source terrain and complete model geometry are preserved.
    Numerical/native-vector qualification remains separate and false here.
    """
    import pandas as pd
    import shapely
    from .RasFim import RasFim, _file_identity, _positive_int, _prepare_output_folder

    from . import _boundary_raw
    _boundary_raw.validate_options(preserve_raw_geometry, method="native_serial",
        allow_unqualified=allow_unqualified, bbox=bbox, polygon=polygon,
        polygon_layer=polygon_layer, aoi_crs=aoi_crs)
    started = time.perf_counter()
    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be a boolean")
    if not allow_unqualified:
        raise FimUnsupportedError("native-order boundary mapping is unqualified; allow_unqualified=True is required")
    if interpolation not in ("horizontal", "sloping"):
        raise ValueError("interpolation must be horizontal or sloping")
    names, selectors = _one_d._profile_selection(profiles)
    selected = dict(zip(names, selectors))
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(name.endswith(".") or name.split(".")[0].upper() in reserved for name in selected):
        raise ValueError("profile names must be safe on Windows")
    threads = _positive_int(threads, "threads")
    inflight = _positive_int(max_inflight_profiles, "max_inflight_profiles")
    working_mib = _positive_int(max_working_mib, "max_working_mib")
    prepared_mib = _positive_int(max_prepared_mib, "max_prepared_mib")
    working, prepared_bytes = working_mib << 20, prepared_mib << 20
    if threads > 64:
        raise ValueError("threads must be <=64")
    if timeout is not None and (not _boundary._finite(timeout) or timeout <= 0):
        raise ValueError("timeout must be finite and positive")
    engine = _engine.find_engine(engine_path)
    registry = _engine.engine_method(engine)
    method = registry.get("native_boundary", {}) if isinstance(registry, dict) else None
    if not isinstance(method, dict) or method.get("method_id") != METHOD_ID:
        raise FimEngineError("Engine lacks the native-order boundary capability")
    from ._capabilities import _parse_capabilities
    support = _parse_capabilities(engine, registry).methods.get("native_boundary")
    if (support is None or support.method_id != METHOD_ID
            or REQUEST_SCHEMA not in support.request_schemas):
        raise FimEngineError("Engine lacks the native-order boundary /2 request capability")
    hdf, terrain = Path(hdf_path).resolve(strict=True), Path(terrain_path).resolve(strict=True)
    terrain_hdf = Path(terrain_hdf).resolve(strict=True)
    scope = RasFim.inspect_model_scope(hdf)
    any_crs = _engine.crs_any(method)
    declared = None
    if any_crs:
        from ._effective_terrain import _terrain_hdf_crs
        declared = _terrain_hdf_crs(terrain_hdf)
    crs, shape, transform, units = _terrain_header(hdf, terrain, declared)
    keys_folder = Path(tempfile.mkdtemp(prefix=".native-boundary-crs-"))
    try:
        identity = _engine.source_identity(engine, terrain, crs, terrain_crs_fnv1a64, crs_any=any_crs,
                                           declared_crs=declared, keys_folder=keys_folder, timeout=timeout,
                                           source_crs_identity=True)
    finally:
        shutil.rmtree(keys_folder, ignore_errors=True)
    watched = {"hdf": hdf, "terrain": terrain, "terrain_hdf": terrain_hdf, "engine": engine}
    # A modified single-source terrain maps on its stored-map effective
    # terrain; tile metadata comes from the source the terrain HDF registers.
    stored = _boundary_inputs.stored_map_terrain(terrain, terrain_hdf)
    staging_primary = stored["source"] if stored is not None else terrain
    if stored is not None:
        # The ordered source receipt binds "terrain" to the original source.
        watched["terrain"], watched["effective_terrain"] = staging_primary, terrain
    if getattr(scope, "geometry_path", None) is not None:
        watched["geometry"] = Path(scope.geometry_path).resolve(strict=True)
    if isinstance(polygon, (str, os.PathLike)):
        watched["polygon"] = Path(polygon).resolve(strict=True)
        if watched["polygon"].suffix.lower() == ".shp":
            for suffix in (".shx", ".dbf", ".prj", ".cpg"):
                watched[f"polygon{suffix}"] = watched["polygon"].with_suffix(suffix)
    snapshots = {key: _file_identity(path) if path.exists() else None for key, path in watched.items()}
    hashes = {key: _one_d.digest(path) if path.exists() else None for key, path in watched.items()}
    def unchanged(*, full=False):
        for key, path in watched.items():
            if ((_file_identity(path) if path.exists() else None) != snapshots[key]
                    or full and (_one_d.digest(path) if path.exists() else None) != hashes[key]):
                raise FimEngineError("Native boundary mapping input source changed")
    folder = _prepare_output_folder(output_folder)
    rows, delivered = [], []
    invalid_profiles = {}
    pending_geometry_error = None
    details = {"schema": "ras-commander-boundary-manifest/1", "request_schema": REQUEST_SCHEMA,
        "method_id": METHOD_ID, "native_vector_parity": False, "qualified": False,
        "method": method, "interpolation": interpolation, "profiles": selected,
        "aoi_clipping_method": None, "full_engine_products": [],
        "engine_returncode": None, "engine_stderr_tail": "",
        "status": "in_progress", "scope": scope.to_dict(), "units": units,
        "engine_path": str(engine), "aoi": None,
        "options": {"profiles": selected, "allow_unqualified": True, "threads": threads,
                    "max_inflight_profiles": inflight, "max_working_mib": working_mib,
                    "max_prepared_mib": prepared_mib, "timeout": timeout,
                    "preserve_raw_geometry": preserve_raw_geometry},
        "sources": {key: {"path": str(path), "identity": snapshots[key], "sha256": hashes[key]}
                    for key, path in watched.items()}}
    manifest = folder / "boundary_manifest.json"
    _boundary._atomic_json(manifest, details)
    try:
        with tempfile.TemporaryDirectory(prefix="native-boundary-") as temporary:
            root = Path(temporary)
            with _prepare(hdf, terrain, root, selected, scope, engine, threads,
                    working_mib, prepared_mib, terrain_crs_fnv1a64) as prepared:
                unchanged()
                prepared["check"]()
                constraint = _aoi.resolve_aoi(bbox, polygon, polygon_layer, aoi_crs, default_crs=crs)
                geometry = _aoi.geometry_in_crs(constraint, crs) if constraint is not None else None
                if geometry is not None and (geometry.has_z or getattr(geometry, "has_m", False)):
                    raise FimUnsupportedError("native boundary AOIs require two-dimensional XY polygons")
                staged = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
                aoi_bytes = (int(shapely.count_coordinates(geometry)) * 128 + 4096
                             if geometry is not None else 0)
                remaining = prepared_bytes - prepared["retained"] - staged - aoi_bytes
                if remaining <= 0:
                    raise FimUnsupportedError("native boundary preparation exceeds max_prepared_mib")
                # Native merging depends on global predecessor/first-subject
                # order. AOIs clip final vectors; they never prune source tiles.
                terrain_sources = stage_native_terrain_sources(terrain_hdf, staging_primary, root,
                    engine_path=engine, threads=threads, model_crs=crs,
                    max_staged_bytes=remaining, timeout=timeout,
                    primary_crs_pin=terrain_crs_fnv1a64, crs_any=any_crs,
                    primary_identity=identity,
                    effective_terrain=terrain if stored is not None else None)
                _watch_terrain_sources(terrain_sources, staging_primary, terrain_hdf, watched, snapshots, hashes)
                metadata = terrain_sources["terrain_metadata"]
                extras = terrain_sources["additional_terrains"]
                if terrain_sources["crs_identity"] != identity["crs_identity"]:
                    raise FimEngineError("Native terrain primary CRS identity changed during preparation")
                _validate_aoi_source(shape, transform, geometry, extras)
                mesh = prepared["mesh"]
                model = {"schema": "ras-commander-sloping-request/1",
                    "options": _sloping._validate_options("sloping", False, False),
                    "terrain": str(terrain), **_engine.request_crs(identity),
                    "crs_identity": identity["crs_identity"], "terrain_transform": transform,
                    "window": [0, 0, shape[1], shape[0]],
                    "geometry_file": mesh["geometry_file"] if mesh else "",
                    "mesh_files": mesh["mesh_files"] if mesh else [],
                    "owner_cells": mesh["owner_cells"] if mesh else [],
                    "profiles": deepcopy(mesh["profiles"]) if mesh else [{"id": name, "values_files": []} for name in selected],
                    "threads": threads, "max_inflight_profiles": inflight,
                    "max_working_bytes": working, "stream_outputs": False}
                storage = prepared["storage"]
                if storage is not None:
                    if len(storage["levels"]) != len(selected):
                        raise FimUnsupportedError("native boundary storage profile cardinality differs")
                    model.update(storage_areas_file=storage["polygons"], storage_area_count=storage["count"])
                    for unit, levels in zip(model["profiles"], storage["levels"]):
                        unit["storage_area_values_file"] = levels
                if geometry is not None:
                    details["aoi"] = {**constraint.describe(), "clip_crs": crs.to_string(),
                                      "clip_geometry_wkb_hex": geometry.wkb_hex}
                    details["aoi_clipping_method"] = AOI_CLIPPING_METHOD
                request_data = {"schema": REQUEST_SCHEMA, "interpolation": interpolation,
                    "contour_method": METHOD_ID, "model": model, "terrain_metadata": metadata,
                    "additional_terrains": extras}
                if identity["epsg"] is None:
                    # GDAL's WKT of the model CRS labels the GeoJSON verbatim.
                    request_data["crs_wkt"] = crs.to_wkt()
                if prepared["xs"] is not None:
                    request_data["one_d"] = prepared["xs"]
                request = root / "boundary-request.json"
                _boundary._atomic_json(request, request_data)
                details.update(preparation=prepared["receipt"], storage=storage,
                    terrain_metadata=metadata, terrain_identity=identity,
                    additional_terrains=extras,
                    terrain_source_receipt={"schema": "ras-commander-boundary-terrain-sources/1",
                        "source_identities": terrain_sources["source_identities"],
                        "terrain_hdf_identity": terrain_sources["terrain_hdf_identity"],
                        "terrain_crs_evidence": terrain_sources.get("terrain_crs_evidence"),
                        "staged_bytes": terrain_sources["staged_bytes"]},
                    terrain_crs_fnv1a64_requested=terrain_crs_fnv1a64)
                details["sources"] = {key: {"path": str(path), "identity": snapshots[key], "sha256": hashes[key]}
                                      for key, path in watched.items()}
                unchanged(full=True)
                tick = time.perf_counter()
                output = root / "boundary-engine"
                try:
                    exit_code, diagnostics = _boundary._run_boundary_engine(engine, request, output, timeout)
                except subprocess.TimeoutExpired as exc:
                    details["engine_stderr_tail"] = (exc.stderr or "")[-8192:]
                    if (output / "report.json").is_file():
                        try:
                            details["engine_report"] = _boundary._load_json(
                                output / "report.json", min(working // 32, 16 << 20))
                        except FimEngineError as report_error:
                            details["engine_report_error"] = str(report_error)
                    raise FimEngineError(f"Native boundary engine exceeded timeout={timeout}: {exc.stderr or ''}") from exc
                engine_seconds = time.perf_counter() - tick
                details["engine_returncode"] = exit_code
                details["engine_stderr_tail"] = diagnostics[-8192:]
                if exit_code != 0:
                    if (output / "report.json").is_file():
                        try:
                            details["engine_report"] = _boundary._load_json(
                                output / "report.json", min(working // 32, 16 << 20))
                        except FimEngineError as report_error:
                            details["engine_report_error"] = str(report_error)
                    raise FimEngineError(f"Native boundary engine failed (exit {exit_code}): {diagnostics[-8192:]}")
                try:
                    report = _boundary._load_json(output / "report.json", min(working // 32, 16 << 20))
                except FimEngineError as report_error:
                    raise FimEngineError(f"Native boundary report unavailable/invalid (exit {exit_code}): {diagnostics[-8192:]} {report_error}") from report_error
                details["engine_report"] = report
                products = _report(report, selected, interpolation, threads, inflight, working, exit_code, diagnostics)
                gis_delivery_seconds = 0.0
                for unit in products:
                    name = unit["id"]
                    expected = f"{name}.geojson"
                    if unit.get("file") != expected or unit.get("status") not in ("complete", "empty"):
                        raise FimEngineError("Native boundary product path/status differs from request")
                    try:
                        product, counts = _boundary._read_product(output / expected, name, interpolation,
                            crs, working // 32, method_id=METHOD_ID)
                    except FimGeometryError as exc:
                        if not preserve_raw_geometry:
                            raise
                        invalid_profiles[name] = exc.validity_reason
                        counts = (*exc._boundary_counts, None)
                        product = None
                    if any(isinstance(unit.get(key), bool) or not isinstance(unit.get(key), int) or unit[key] != value
                           for key, value in zip(("polygon_count", "hole_count", "vertex_count"), counts[:3])):
                        raise FimEngineError("Native boundary geometry counts differ from product")
                    if (unit["status"] == "empty") != (counts[0] == 0):
                        raise FimEngineError("Native boundary empty status differs from product")
                    if (not _boundary._finite(unit.get("area")) or unit["area"] < 0
                            or counts[3] is not None and not math.isclose(
                                unit["area"], counts[3], rel_tol=1e-12, abs_tol=1e-6)):
                        raise FimEngineError("Native boundary area report differs from product geometry")
                    details["full_engine_products"].append({"profile": name, "status": unit["status"],
                        "polygons": counts[0], "holes": counts[1], "vertices": counts[2], "area": counts[3]})
                    if product is None:
                        continue
                    if geometry is not None:
                        clip_tick = time.perf_counter()
                        product, counts = _clip_product(product, geometry, counts, working)
                        gis_delivery_seconds += time.perf_counter() - clip_tick
                    status = "empty" if counts[0] == 0 else "complete"
                    unchanged()
                    prepared["check"]()
                    destination = folder / expected
                    if destination.exists() or destination.is_symlink():
                        raise FimEngineError("Native boundary destination changed during mapping")
                    _boundary._atomic_json(destination, product)
                    delivered.append(destination)
                    rows.append(dict(zip(_boundary.COLUMNS, [name, selected[name], status,
                        str(destination), interpolation, *counts, crs.to_string(), None])))
                prepared["check"]()
                if invalid_profiles:
                    raw_folder = folder / "raw_geometry"
                    raw_folder.mkdir()
                    receipts = {}
                    def check_raw_sources():
                        unchanged(full=True)
                        prepared["check"]()
                    for name in selected:
                        receipts[name] = _boundary_raw.retain_raw_geometry(
                            output / f"{name}.geojson", raw_folder / name, crs, working,
                            validity_reason=invalid_profiles.get(name, "Valid topology in an aborted profile batch"),
                            topology_valid=name not in invalid_profiles, check_sources=check_raw_sources)
                    details["raw_geometry"] = {"diagnostic_only": True, "qualified": False,
                        "profiles": receipts, "invalid_profiles": invalid_profiles,
                        "provenance_verified": False, "complete_raw_profile_coverage": True}
                    pending_geometry_error = FimGeometryError(
                        "Native boundary topology is invalid; retained raw geometry is diagnostic only",
                        diagnostic_manifest=str(manifest),
                        artifacts=[artifact["path"] for receipt in receipts.values()
                                   for artifact in receipt["artifacts"]],
                        validity_reason="; ".join(f"{name}: {reason}" for name, reason in invalid_profiles.items()))
                details["performance"] = {"prepare_seconds": tick - started,
                    "engine_seconds": engine_seconds,
                    "gis_delivery_seconds": gis_delivery_seconds,
                    "total_seconds": time.perf_counter() - started, "engine": report}
            unchanged(full=True)
        if pending_geometry_error is not None:
            details["raw_geometry"]["provenance_verified"] = True
            raise pending_geometry_error
        details["performance"]["total_seconds"] = time.perf_counter() - started
        details.update(status="complete", products=rows)
        _boundary._atomic_json(manifest, details)
        frame = pd.DataFrame(rows, columns=_boundary.COLUMNS)
        frame.attrs.update(performance=details["performance"], method_id=METHOD_ID,
            native_vector_parity=False, qualified=False, manifest=str(manifest),
            aoi_clipping_method=details["aoi_clipping_method"], aoi=details["aoi"])
        return frame
    except BaseException as exc:
        for path in delivered:
            path.unlink(missing_ok=True)
        details.update(status="aborted", error=str(exc), products=[])
        try:
            _boundary._atomic_json(manifest, details)
        except OSError as manifest_error:
            if hasattr(exc, "add_note"):
                exc.add_note(f"Could not write aborted native boundary manifest: {manifest_error}")
        raise
