"""Deterministic Rust zero-depth contour delivery; no native vector parity claim."""

from pathlib import Path
import json
import math
import os
import subprocess
import tempfile
import time

from .. import get_logger, log_call
from . import _aoi, _engine, _sloping
from ._boundary_inputs import stage_boundary_terrain
from ._horizontal_engine import _write_geometry
from .errors import FimEngineError, FimUnsupportedError

logger = get_logger(__name__)
METHOD_ID = "deterministic-zero-depth-contours/1"
COLUMNS = ["profile", "selector", "status", "boundary_geojson", "interpolation",
           "polygons", "holes", "vertices", "area", "crs", "error"]


def _finite(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


def _atomic_json(path, value):
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with partial.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def _load_json(path, max_bytes):
    try:
        if path.is_symlink() or path.stat().st_size > max_bytes:
            raise FimEngineError(f"JSON source is linked or exceeds planned admission: {path.name}")
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise FimEngineError(f"Cannot read boundary JSON {path.name}: {exc}") from exc
    if len(data) > max_bytes:
        raise FimEngineError("JSON source grew beyond planned admission")
    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")
    try:
        return json.loads(data, parse_constant=nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise FimEngineError(f"Invalid JSON in {path.name}: {exc}") from exc


def _run_boundary_engine(engine, request, output, timeout):
    """Keep subprocess diagnostics on disk, retaining only a bounded tail."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([str(engine), "boundary", str(request), str(output)],
                                   stdout=stdout, stderr=stderr,
                                   creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        try:
            process.wait(timeout=timeout)
        except BaseException as exc:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            process.wait()
            if isinstance(exc, subprocess.TimeoutExpired):
                stderr.seek(0, 2)
                stderr.seek(max(0, stderr.tell() - 65536))
                exc.stderr = stderr.read().decode("utf-8", errors="replace")
            raise
        stderr.seek(0, 2)
        stderr.seek(max(0, stderr.tell() - 65536))
        return process.returncode, stderr.read().decode("utf-8", errors="replace")


def _validate_cells(cells):
    import numpy as np
    import shapely
    geometries = cells.geometry.to_numpy()
    if (not np.isin(shapely.get_type_id(geometries), [3]).all()
            or shapely.is_empty(geometries).any() or not shapely.is_valid(geometries).all()):
        raise FimUnsupportedError("Boundary mapping requires valid nonempty cell Polygons")
    # One query at a time and bounded predicate batches avoid N-by-N pairs.
    for i, geometry in enumerate(geometries):
        others = cells.sindex.query(geometry)
        others = others[others > i]
        for start in range(0, len(others), 4096):
            if shapely.relate_pattern(geometry, geometries[others[start:start + 4096]], "T********").any():
                raise FimUnsupportedError("Boundary cells have overlapping interiors")


def _selected_tiles(shape, transform, geometry):
    if geometry is None:
        return None
    left, bottom, right, top = geometry.bounds
    x, dx, _, y, _, dy = transform
    height, width = shape
    # Include a source-pixel halo before whole-tile selection. No sample crops.
    c0, c1 = max(0, math.floor((left-x)/dx)-1), min(width, math.ceil((right-x)/dx)+1)
    r0, r1 = max(0, math.floor((y-top)/(-dy))-1), min(height, math.ceil((y-bottom)/(-dy))+1)
    if c0 >= c1 or r0 >= r1:
        raise FimUnsupportedError("Boundary AOI does not intersect the terrain sample grid")
    columns = math.ceil(width / 256)
    return [r * columns + c for r in range(r0 // 256, (r1-1)//256 + 1)
            for c in range(c0 // 256, (c1-1)//256 + 1)]


def _read_product(path, profile, interpolation, crs, max_bytes):
    import shapely
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from shapely.geometry import shape
    product = _load_json(path, max_bytes)
    try:
        if product["type"] != "FeatureCollection" or len(product["features"]) != 1:
            raise ValueError("expected one-feature FeatureCollection")
        feature = product["features"][0]
        properties = feature["properties"]
        if (feature["type"] != "Feature" or properties["profile_id"] != profile
                or properties["interpolation"] != interpolation or properties["method_id"] != METHOD_ID
                or properties["native_vector_parity"] is not False):
            raise ValueError("feature identity or method differs from request")
        if CRS.from_user_input(product["crs"]["properties"]["name"]) != CRS.from_user_input(crs):
            raise ValueError("projected coordinate CRS differs from request")
        geometry = feature["geometry"]
        if geometry["type"] != "MultiPolygon" or not isinstance(geometry["coordinates"], list):
            raise ValueError("expected MultiPolygon geometry")
        holes = vertices = 0
        for polygon in geometry["coordinates"]:
            if not isinstance(polygon, list) or not polygon:
                raise ValueError("polygon requires an exterior ring")
            holes += len(polygon) - 1
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("rings must be closed with at least four vertices")
                for xy in ring:
                    if (not isinstance(xy, list) or len(xy) != 2
                            or any(not _finite(v) for v in xy)):
                        raise ValueError("coordinates must be finite XY pairs")
                vertices += len(ring)
        parsed = shape(geometry)
        if not shapely.is_valid(parsed):
            raise ValueError(f"invalid contour geometry: {shapely.is_valid_reason(parsed)}")
        area = float(parsed.area)
        if not _finite(area):
            raise ValueError("geometry area is nonfinite")
        return product, (len(geometry["coordinates"]), holes, vertices, area)
    except (KeyError, TypeError, ValueError, CRSError) as exc:
        raise FimEngineError(f"Invalid boundary product {path.name}: {exc}") from exc


@log_call
def map_inundation_boundaries(
    hdf_path, terrain_path, output_folder, *, terrain_hdf, profiles=None,
    interpolation="sloping", bbox=None, polygon=None, polygon_layer=None,
    aoi_crs=None, engine_path=None, threads=1, max_inflight_profiles=1,
    max_working_mib=1024, max_prepared_mib=1024, timeout=None,
    terrain_crs_fnv1a64=None,
):
    """Map deterministic zero-depth contour polygons with a required Rust engine.

    The method differs from native RAS Mapper polygon union behavior. It adds
    no depth cutoff, uses complete 2D hydraulics, and clips only final contours.
    TIFF pixels are read lazily by Rust. Memory limits are planned admission,
    including a conservative JSON/geometry allowance, not a hard RSS bound.
    """
    import numpy as np
    import pandas as pd
    import rasterio
    import shapely
    from .RasFim import RasFim, _file_identity, _positive_int, _prepare_output_folder

    if interpolation not in ("horizontal", "sloping"):
        raise ValueError("interpolation must be horizontal or sloping")
    selected = _sloping._validate_selection(profiles)
    selected = {name: int(value) if isinstance(value, np.integer) else value for name, value in selected.items()}
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1,10)), *(f"LPT{i}" for i in range(1,10))}
    if any(name.endswith(".") or name.split(".")[0].upper() in reserved for name in selected):
        raise ValueError("profile names must be safe on Windows")
    threads = _positive_int(threads, "threads")
    inflight = _positive_int(max_inflight_profiles, "max_inflight_profiles")
    working = _positive_int(max_working_mib, "max_working_mib") * (1 << 20)
    prepared_bytes = _positive_int(max_prepared_mib, "max_prepared_mib") * (1 << 20)
    if threads > 64:
        raise ValueError("threads must be <=64")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be finite and positive")
    engine = _engine.find_engine(engine_path)
    method = _engine.engine_method(engine).get("boundary", {})
    if not isinstance(method, dict) or method.get("method_id") != METHOD_ID:
        raise FimEngineError("Engine lacks deterministic boundary capability; install a matching Fast-Map engine (0.10+)")
    watched = {"hdf": Path(hdf_path).resolve(strict=True), "terrain": Path(terrain_path).resolve(strict=True),
               "terrain_hdf": Path(terrain_hdf).resolve(strict=True), "engine": engine}
    if isinstance(polygon, (str, os.PathLike)):
        watched["polygon"] = Path(polygon).resolve(strict=True)
        if watched["polygon"].suffix.lower() == ".shp":
            for suffix in (".shx", ".dbf", ".prj", ".cpg"):
                watched[f"polygon{suffix}"] = watched["polygon"].with_suffix(suffix)
    identities = {key: _file_identity(path) if path.exists() else None for key, path in watched.items()}
    def unchanged():
        if any((_file_identity(path) if path.exists() else None) != identities[key] for key, path in watched.items()):
            raise FimEngineError("Boundary mapping input source changed")
    folder = _prepare_output_folder(output_folder)
    started = time.perf_counter()
    delivered = []
    rows = []
    details = {"schema": "ras-commander-boundary-manifest/1", "method_id": METHOD_ID,
               "native_vector_parity": False, "method": method, "interpolation": interpolation,
               "status": "in_progress", "profiles": selected,
               "sources": {key: {"path": str(path), "identity": identities[key]} for key, path in watched.items()}}
    manifest = folder / "boundary_manifest.json"
    _atomic_json(manifest, details)
    try:
        with RasFim.prepare_sloping_model(hdf_path, terrain_path, profiles=selected,
                engine_path=engine, threads=threads, max_working_mib=max_working_mib,
                max_prepared_mib=max_prepared_mib, native_session=False,
            terrain_crs_fnv1a64=terrain_crs_fnv1a64) as context:
            unchanged()
            context._check_sources()
            cells = context._cells
            _validate_cells(cells)
            root = Path(context._temporary.name)
            with rasterio.open(terrain_path) as raster:
                crs, shape = raster.crs, [raster.height, raster.width]
            aoi = _aoi.resolve_aoi(bbox, polygon, polygon_layer, aoi_crs, default_crs=crs)
            geometry = _aoi.geometry_in_crs(aoi, crs) if aoi is not None else None
            tiles = _selected_tiles(shape, context._terrain_transform, geometry)
            coordinates = int(shapely.count_coordinates(cells.geometry.to_numpy()))
            transport = coordinates * 20 + len(cells) * 128
            if geometry is not None:
                transport += int(shapely.count_coordinates(geometry)) * 16 + 1024
            remaining = prepared_bytes - context._info["planned_prepared_bytes"] - transport
            if remaining <= 0:
                raise FimUnsupportedError("Boundary geometry transport exceeds max_prepared_mib")
            metadata = stage_boundary_terrain(terrain_hdf, terrain_path, root, threads=threads,
                max_staged_bytes=remaining, selected_tiles=tiles)
            _write_geometry(root / "boundary-cells.wkb", cells.geometry.to_numpy())
            lookup = {mesh["mesh_name"]: i for i, mesh in enumerate(context._meshes)}
            owners = [[lookup[row.mesh_name], int(row.cell_id)] for row in cells.itertuples()]
            model = {"schema": "ras-commander-sloping-request/1", "options": _sloping._validate_options("sloping", False, False),
                     "terrain": str(Path(terrain_path).resolve()), "epsg": context._terrain_identity["epsg"],
                     "crs_identity": context._terrain_identity["crs_identity"], "terrain_transform": context._terrain_transform,
                     "window": [0, 0, shape[1], shape[0]], "geometry_file": "boundary-cells.wkb",
                     "mesh_files": context._mesh_files, "owner_cells": owners,
                     "profiles": [context._units[name] for name in selected], "threads": threads,
                     "max_inflight_profiles": inflight, "max_working_bytes": working, "stream_outputs": False}
            if geometry is not None:
                _write_geometry(root / "boundary-aoi.wkb", [geometry])
                model["aoi_file"] = "boundary-aoi.wkb"
            request = root / "boundary-request.json"
            _atomic_json(request, {"schema": "ras-commander-boundary-request/1", "interpolation": interpolation,
                                   "model": model, "terrain_metadata": metadata})
            unchanged()
            tick = time.perf_counter()
            output = root / "boundary-engine"
            try:
                exit_code, diagnostics = _run_boundary_engine(engine, request, output, timeout)
            except subprocess.TimeoutExpired as exc:
                if (output / "report.json").is_file():
                    details["engine_report"] = _load_json(output / "report.json", min(working // 32, 16 << 20))
                raise FimEngineError(f"Boundary engine exceeded timeout={timeout}: {exc.stderr or ''}") from exc
            engine_seconds = time.perf_counter() - tick
            report = _load_json(output / "report.json", min(working // 32, 16 << 20))
            details["engine_report"] = report
            if not isinstance(report, dict):
                raise FimEngineError("Boundary report must be an object")
            if (exit_code != 0 or report.get("schema") != "ras-commander-boundary-report/1"
                    or report.get("status") != "complete" or not isinstance(report.get("method"), dict)
                    or report["method"].get("method_id") != METHOD_ID
                    or report.get("interpolation") != interpolation):
                raise FimEngineError(f"Boundary engine failed or wrote inconsistent report (exit {exit_code}): {diagnostics[-8192:]} {report.get('error', '')}")
            def integer(key):
                value = report.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise FimEngineError(f"Boundary report {key} must be a nonnegative integer")
                return value
            actual_threads = integer("threads")
            effective = integer("effective_inflight_profiles")
            shared = integer("planned_shared_bytes")
            allowance = integer("per_profile_contour_budget_bytes")
            if (actual_threads != threads or not 1 <= effective <= min(threads, inflight, len(selected))
                    or allowance == 0 or shared + effective * allowance > working):
                raise FimEngineError("Boundary report concurrency/memory admission differs from request")
            if any(not _finite(report.get(key)) or report[key] < 0 for key in ("prepare_seconds", "render_seconds")):
                raise FimEngineError("Boundary report timing is invalid")
            units = report.get("profiles")
            if not isinstance(units, list) or not all(isinstance(unit, dict) for unit in units) or [unit.get("id") for unit in units] != list(selected):
                raise FimEngineError("Boundary report profile identities/order differ from request")
            for unit in units:
                name = unit["id"]
                expected = f"{name}.geojson"
                if unit.get("file") != expected or unit.get("status") not in ("complete", "empty"):
                    raise FimEngineError("Boundary report product path/status differs from request")
                product, counts = _read_product(output / expected, name, interpolation, crs, working // 32)
                if any(isinstance(unit.get(key), bool) or not isinstance(unit.get(key), int) or unit[key] != value
                       for key, value in zip(("polygon_count", "hole_count", "vertex_count"), counts[:3])):
                    raise FimEngineError("Boundary report geometry counts differ from its product")
                if (unit["status"] == "empty") != (counts[0] == 0):
                    raise FimEngineError("Boundary report empty status differs from its product")
                if not _finite(unit.get("area")) or unit["area"] < 0:
                    raise FimEngineError("Boundary report area is invalid")
                unchanged()
                context._check_sources()
                destination = folder / expected
                _atomic_json(destination, product)
                delivered.append(destination)
                rows.append(dict(zip(COLUMNS, [name, selected[name], unit["status"], str(destination), interpolation,
                                               *counts, crs.to_string(), None])))
                del product
            unchanged()
            context._check_sources()
            details["terrain_metadata"] = metadata
            details["terrain_identity"] = context._terrain_identity
            details["terrain_crs_fnv1a64_requested"] = terrain_crs_fnv1a64
            details["performance"] = {"prepare_seconds": context.info["prepare_seconds"], "engine_seconds": engine_seconds,
                                      "total_seconds": time.perf_counter() - started, "engine": report}
        details["performance"]["total_seconds"] = time.perf_counter() - started
        unchanged()
        details.update(status="complete", products=rows)
        _atomic_json(manifest, details)
        frame = pd.DataFrame(rows, columns=COLUMNS)
        frame.attrs.update(performance=details["performance"], method_id=METHOD_ID,
                           native_vector_parity=False, manifest=str(manifest))
        return frame
    except BaseException as exc:
        for path in delivered:
            path.unlink(missing_ok=True)
        details.update(status="aborted", error=str(exc), products=[])
        try:
            _atomic_json(manifest, details)
        except OSError as manifest_error:
            exc.add_note(f"Could not write aborted boundary manifest: {manifest_error}")
        raise
