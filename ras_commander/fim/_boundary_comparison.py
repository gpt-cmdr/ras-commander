"""Full-geometry comparison of deterministic contours and native stored polygons."""

import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import uuid

import pandas as pd

from . import _aoi
from ._boundary import _atomic_json, _load_json
from ._sloping import _validate_selection
from .errors import FimGeometryError

COLUMNS = [
    "profile", "native_profile", "status", "interpolation",
    "candidate_polygons", "reference_polygons", "candidate_holes", "reference_holes",
    "candidate_vertices", "reference_vertices", "candidate_area", "reference_area",
    "extra_area", "missing_area", "symmetric_difference_area", "intersection_over_union",
    "hausdorff_distance", "geometry_equal", "coordinates_equal", "quantized_coordinates_equal",
    "candidate_path", "reference_path", "native_seconds", "candidate_batch_seconds",
    "comparison_seconds",
]


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink vector inputs are unsupported")
    path = path.resolve(strict=True)
    if path.suffix.lower() == ".shp":
        files = [path.with_suffix(s) for s in (".shp", ".shx", ".dbf", ".prj")]
        if not all(p.is_file() for p in files):
            raise ValueError("Reference shapefile needs SHP, SHX, DBF and PRJ")
        if path.with_suffix(".cpg").exists():
            files.append(path.with_suffix(".cpg"))
        return files
    if path.suffix.lower() == ".gpkg" and any(Path(str(path) + s).exists() for s in ("-wal", "-shm")):
        raise ValueError("Reference GeoPackage must be closed, without WAL/SHM sidecars")
    return [path]


def _identity(path):
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": _digest(path)}


def _geojson_size_counts(path):
    """Streaming lexical/structure pass, retaining no coordinate arrays."""
    class Scanner:
        def __init__(self, stream):
            self.stream, self.buffer, self.index = stream, "", 0
            self.vertices = self.features = 0

        def peek(self):
            if self.index == len(self.buffer):
                self.buffer, self.index = self.stream.read(65536), 0
            return self.buffer[self.index:self.index + 1]

        def take(self):
            value = self.peek()
            self.index += bool(value)
            return value

        def space(self):
            while self.peek() and self.peek().isspace():
                self.take()

        def expect(self, value):
            self.space()
            if self.take() != value:
                raise ValueError("Invalid GeoJSON structure during budget preflight")

        def string(self):
            self.expect('"')
            token, escaped = ['"'], False
            while True:
                char = self.take()
                if not char or len(token) > 1024 * 1024:
                    raise ValueError("Invalid or oversized GeoJSON string during budget preflight")
                token.append(char)
                if char == '"' and not escaped:
                    return json.loads("".join(token))
                escaped = char == "\\" and not escaped

        def value(self, depth=0, coordinates=False, features=False):
            if depth > 64:
                raise ValueError("GeoJSON nesting exceeds budget preflight limit")
            self.space()
            char = self.peek()
            if char == "{":
                if coordinates:
                    raise ValueError("Invalid GeoJSON coordinate structure")
                self.take()
                self.space()
                if self.peek() != "}":
                    while True:
                        key = self.string()
                        self.expect(":")
                        self.value(depth + 1, key == "coordinates", key == "features")
                        self.space()
                        if self.peek() != ",":
                            break
                        self.take()
                self.expect("}")
                return "object"
            if char == "[":
                self.take()
                self.space()
                kinds = set()
                count = 0
                if self.peek() != "]":
                    while True:
                        kinds.add(self.value(depth + 1, coordinates))
                        count += 1
                        if features:
                            self.features += 1
                        self.space()
                        if self.peek() != ",":
                            break
                        self.take()
                self.expect("]")
                if coordinates and "number" in kinds:
                    if kinds != {"number"} or count != 2:
                        raise ValueError("Polygon coordinates must be finite XY")
                    self.vertices += 1
                elif coordinates and kinds - {"array"}:
                    raise ValueError("Invalid GeoJSON coordinate structure")
                return "array"
            if char == '"':
                self.string()
                return "string"
            token = []
            while self.peek() and self.peek() not in ",]} \t\r\n":
                token.append(self.take())
                if len(token) > 1024:
                    raise ValueError("Oversized GeoJSON scalar during budget preflight")
            value = json.loads("".join(token))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("Polygon coordinates must be finite XY")
                return "number"
            return "scalar"

    with Path(path).open(encoding="utf-8") as stream:
        scanner = Scanner(stream)
        scanner.value()
        scanner.space()
        if scanner.peek():
            raise ValueError("Trailing GeoJSON data during budget preflight")
        return scanner.vertices, scanner.features


def _shp_size_counts(path):
    """Read only fixed record/count headers; no coordinate or GEOS allocation."""
    size = Path(path).stat().st_size
    vertices = features = 0
    with Path(path).open("rb") as stream:
        header = stream.read(100)
        if (len(header) != 100 or struct.unpack_from(">i", header)[0] != 9994
                or struct.unpack_from(">i", header, 24)[0] * 2 != size
                or struct.unpack_from("<ii", header, 28) != (1000, 5)):
            raise ValueError("Native large-vector admission requires an intact XY Polygon SHP")
        while stream.tell() < size:
            record = stream.read(8)
            if len(record) != 8:
                raise ValueError("Truncated SHP record header")
            length = struct.unpack(">ii", record)[1] * 2
            start = stream.tell()
            prefix = stream.read(min(length, 44))
            if length < 44 or len(prefix) != 44 or start + length > size:
                raise ValueError("Invalid SHP polygon record length")
            shape = struct.unpack_from("<i", prefix)[0]
            parts, points = struct.unpack_from("<ii", prefix, 36)
            if shape != 5 or parts < 1 or points < 4 * parts or length != 44 + 4 * parts + 16 * points:
                raise ValueError("Invalid SHP polygon counts or non-XY shape")
            vertices += points
            features += 1
            stream.seek(start + length)
    return vertices, features


def _native_vector_info(path, budget):
    paths = _files(path)
    file_bytes = sum(p.stat().st_size for p in paths)
    if any(p.is_symlink() for p in paths) or file_bytes * 8 + (64 << 20) > budget:
        raise ValueError("Native vector input exceeds planned geometry file budget")
    suffix = Path(path).suffix.lower()
    if suffix in (".json", ".geojson"):
        vertices, features = _geojson_size_counts(path)
    elif suffix == ".shp":
        vertices, features = _shp_size_counts(path)
    elif suffix == ".gpkg":
        # No safe variable-length geometry scan yet: retain the old hard limit.
        import pyogrio
        info = pyogrio.read_info(path)
        features = info["features"]
        if features < 0 or features > min(100_000, budget // 4096):
            raise ValueError("Unbounded reference feature count")
        vertices = min(500_000, budget // 1024)
    else:
        raise ValueError("Boundary reference must be SHP, GPKG or GeoJSON")
    return dict(vertices=vertices, features=features, file_bytes=file_bytes)


def _admit_native_pair(infos, budget):
    estimate = ((64 << 20) + sum(768 * i["vertices"] + 4096 * i["features"]
                                + 8 * i["file_bytes"] for i in infos))
    if estimate > budget:
        raise ValueError(f"Native comparison pair exceeds planned geometry budget ({estimate} > {budget} bytes)")
    return estimate


def _native_pair_plan(candidate, reference, budget):
    paths = [Path(p) for p in (candidate, reference) if p is not None]
    infos = [_native_vector_info(path, budget) for path in paths]
    _admit_native_pair(infos, budget)
    return {str(path.resolve()): info for path, info in zip(paths, infos)}


def _read_geometry(path, model_crs, budget, *, native_plan=None):
    """Admit bounded vector files before parsing; never repair or reproject."""
    import numpy as np
    import shapely
    from pyproj import CRS

    paths = _files(path)
    vertex_limit = min(500_000, budget // 1024)
    feature_limit = min(100_000, budget // 4096)
    file_limit = budget // 32
    if native_plan is not None:
        info = native_plan[str(Path(path).resolve())]
        vertex_limit, feature_limit, file_limit = info["vertices"], info["features"], info["file_bytes"]
    if any(p.is_symlink() for p in paths) or sum(p.stat().st_size for p in paths) > file_limit:
        raise ValueError("Vector input exceeds planned geometry file budget")
    suffix = Path(path).suffix.lower()
    if suffix in (".geojson", ".json"):
        data = _load_json(Path(path), file_limit)
        crs = data.get("crs", {}).get("properties", {}).get("name")
        if not crs:
            raise ValueError("Reference GeoJSON requires an explicit stored CRS")
        features = data.get("features")
        if data.get("type") != "FeatureCollection" or not isinstance(features, list):
            raise ValueError("Expected polygon FeatureCollection")
        if len(features) > feature_limit:
            raise ValueError("Vector feature count exceeds planned budget")
        # Count positions before allocating GEOS geometries.
        def positions(value):
            if not isinstance(value, list):
                raise ValueError("Invalid coordinate array")
            if value and isinstance(value[0], (float, int)):
                if len(value) != 2 or not all(not isinstance(v, bool) and math.isfinite(v) for v in value):
                    raise ValueError("Polygon coordinates must be finite XY")
                return 1
            return sum(positions(child) for child in value)
        count = sum(positions(f["geometry"]["coordinates"]) for f in features)
        if count > vertex_limit:
            raise ValueError("Vector vertices exceed planned geometry budget")
        for feature in features:
            raw = feature["geometry"]
            polygons = [raw["coordinates"]] if raw["type"] == "Polygon" else raw["coordinates"]
            if raw["type"] not in ("Polygon", "MultiPolygon"):
                raise ValueError("Boundary contains non-polygon geometry")
            for polygon in polygons:
                if not isinstance(polygon, list) or not polygon:
                    raise ValueError("Boundary polygon requires an exterior ring")
                for ring in polygon:
                    if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError("Boundary rings must be closed with at least four vertices")
        geometries = [shapely.geometry.shape(f["geometry"]) for f in features]
    elif suffix in (".shp", ".gpkg"):
        import pyogrio
        layers = pyogrio.list_layers(path)
        if len(layers) != 1:
            raise ValueError("Reference vector must contain exactly one polygon layer")
        info = pyogrio.read_info(path)
        if info["features"] < 0 or info["features"] > feature_limit:
            raise ValueError("Unbounded reference feature count")
        frame = pyogrio.read_dataframe(path)
        crs, geometries = frame.crs, list(frame.geometry)
    else:
        raise ValueError("Boundary reference must be SHP, GPKG or GeoJSON")
    same_crs = crs is not None and CRS.from_user_input(crs).equals(CRS.from_user_input(model_crs))
    if native_plan is not None and crs is not None:
        from ._source_crs import source_crs
        same_crs = source_crs(crs).equals(source_crs(model_crs))
    if not same_crs:
        raise ValueError("Boundary CRS differs from model CRS; reprojection is forbidden")
    if sum(int(shapely.count_coordinates(g)) for g in geometries) > vertex_limit:
        if native_plan is not None and suffix == ".gpkg":
            raise ValueError("Native GeoPackage large-vector admission is unsupported; vertices exceed the retained bounded geometry budget")
        raise ValueError("Vector vertices exceed planned geometry budget")
    for geometry in geometries:
        if geometry is None or geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Boundary contains a missing or non-polygon geometry")
        if not np.isfinite(shapely.get_coordinates(geometry)).all():
            raise ValueError("Boundary geometry is nonfinite; repair is forbidden")
    reason = next((str(shapely.is_valid_reason(g)) for g in geometries if not g.is_valid), None)
    if reason is not None:
        # A topology refusal must not conceal malformed/unclosed stored SHP parts.
        geometries = geometry = data = features = raw = feature = polygons = polygon = ring = frame = None
        if suffix == ".shp":
            from . import _boundary_raw
            info = _boundary_raw._headers(path, budget)
            _boundary_raw._admit([info], budget)
            _boundary_raw._scan(_boundary_raw._prepare(info, model_crs))
        if suffix == ".gpkg":
            raise ValueError("Boundary geometry is invalid; raw GeoPackage diagnostics are unsupported")
        raise FimGeometryError(f"Boundary geometry is invalid: {reason}; repair is forbidden",
                               validity_reason=reason)
    # Preserve every stored vertex. Unary union can discard collinear points
    # or merge parts, which would conceal coordinate/topology differences.
    if len(geometries) == 1:
        return geometries[0]
    parts = []
    for geometry in geometries:
        parts.extend([geometry] if geometry.geom_type == "Polygon" else geometry.geoms)
    geometry = shapely.MultiPolygon(parts)
    if not geometry.is_valid:
        reason = str(shapely.is_valid_reason(geometry))
        geometry = geometries = parts = data = features = raw = feature = polygons = polygon = ring = frame = None
        if suffix == ".shp":
            from . import _boundary_raw
            info = _boundary_raw._headers(path, budget)
            _boundary_raw._admit([info], budget)
            _boundary_raw._scan(_boundary_raw._prepare(info, model_crs))
        if suffix == ".gpkg":
            raise ValueError("Combined boundary parts are invalid; raw GeoPackage diagnostics are unsupported")
        raise FimGeometryError(f"Combined boundary parts are invalid: {reason}; union repair is forbidden",
                               validity_reason=reason)
    return geometry


def _rotate(sequence):
    """Lexicographically minimal cyclic rotation in linear time (Booth)."""
    if not sequence:
        return ()
    doubled, n = sequence + sequence, len(sequence)
    i, j, k = 0, 1, 0
    while i < n and j < n and k < n:
        a, b = doubled[i + k], doubled[j + k]
        if a == b:
            k += 1
        else:
            if a > b:
                i += k + 1
                if i <= j:
                    i = j + 1
            else:
                j += k + 1
                if j <= i:
                    j = i + 1
            k = 0
    start = min(i, j)
    return tuple(doubled[start:start + n])


def _canonical(geometry, *, quantized=True):
    def ring(value):
        points = []
        for x, y in value.coords:
            if max(abs(x), abs(y)) * 1000 >= 2**61:
                raise ValueError("Coordinate exceeds safe 0.001-unit quantization range")
            points.append((round(x * 1000), round(y * 1000)) if quantized else (x, y))
        if points and points[0] == points[-1]:
            points.pop()
        return min(_rotate(points), _rotate(list(reversed(points))))
    parts = [] if geometry.is_empty else ([geometry] if geometry.geom_type == "Polygon" else geometry.geoms)
    return tuple(sorted((ring(p.exterior), tuple(sorted(ring(h) for h in p.interiors))) for p in parts))


def _stats(geometry):
    import shapely
    parts = [] if geometry.is_empty else ([geometry] if geometry.geom_type == "Polygon" else geometry.geoms)
    return len(parts), sum(len(p.interiors) for p in parts), int(shapely.count_coordinates(geometry))


def _metrics(candidate, reference):
    import shapely
    cp, ch, cv = _stats(candidate)
    rp, rh, rv = _stats(reference)
    extra, missing = candidate.difference(reference).area, reference.difference(candidate).area
    union = candidate.union(reference).area
    hausdorff = None
    if not candidate.is_empty and not reference.is_empty and cv * rv <= 25_000_000:
        hausdorff = float(shapely.hausdorff_distance(candidate, reference))
    elif candidate.is_empty and reference.is_empty:
        hausdorff = 0.0
    return dict(candidate_polygons=cp, reference_polygons=rp, candidate_holes=ch,
        reference_holes=rh, candidate_vertices=cv, reference_vertices=rv,
        candidate_area=candidate.area, reference_area=reference.area, extra_area=extra,
        missing_area=missing, symmetric_difference_area=extra + missing,
        intersection_over_union=candidate.intersection(reference).area / union if union else 1.0,
        hausdorff_distance=hausdorff, geometry_equal=bool(candidate.equals(reference)),
        coordinates_equal=_canonical(candidate, quantized=False) == _canonical(reference, quantized=False),
        quantized_coordinates_equal=_canonical(candidate) == _canonical(reference))


def run(hdf_path, terrain_path, output_folder, *, terrain_hdf, profiles=None,
        interpolation="sloping", native_boundaries=None, plan_number=None, terrain_name=None,
        native_performance=None,
        ras_object=None, ras_version=None, bbox=None, polygon=None, polygon_layer=None,
        aoi_crs=None, engine_path=None, threads=1, max_inflight_profiles=1,
        max_working_mib=1024, max_prepared_mib=1024, timeout=None,
        terrain_crs_fnv1a64=None, method="deterministic", allow_unqualified=False,
        preserve_raw_geometry=False):
    """Compare complete vector geometry; native vector parity is not presumed."""
    import rasterio
    from .RasFim import RasFim, _prepare_output_folder, _require_path, _positive_int
    from .._execution_types import StoreMapPerformanceOptions

    from . import _boundary_raw
    _boundary_raw.validate_options(preserve_raw_geometry, method=method,
        allow_unqualified=allow_unqualified, bbox=bbox, polygon=polygon,
        polygon_layer=polygon_layer, aoi_crs=aoi_crs)
    if method not in ("deterministic", "native_serial"):
        raise ValueError("boundary method must be deterministic or native_serial")
    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be boolean")
    if method == "native_serial" and not allow_unqualified:
        from .errors import FimUnsupportedError
        raise FimUnsupportedError("native-order boundary comparison requires allow_unqualified=True")

    if native_performance is not None and not isinstance(native_performance, StoreMapPerformanceOptions):
        raise TypeError("native_performance must be StoreMapPerformanceOptions or None")
    if native_boundaries is not None and native_performance is not None:
        raise ValueError("native_performance cannot affect retained native boundaries")
    if (native_performance is not None and native_performance.native_polygon_serial
            and native_performance.max_workers != 1):
        raise ValueError("serial native boundary generation requires max_workers=1")
    if method == "native_serial" and native_boundaries is None and (
            native_performance is None or not native_performance.native_polygon_serial):
        raise ValueError("native-order comparison generation requires native_polygon_serial=True")

    if method == "native_serial":
        from ._one_d import _profile_selection
        names, selectors = _profile_selection(profiles)
        selected = dict(zip(names, selectors))
    else:
        selected = {key: int(value) if value != "Max" else value for key, value in _validate_selection(profiles).items()}
    if interpolation not in ("horizontal", "sloping"):
        raise ValueError("Boundary comparison supports horizontal or plain sloping")
    budget = _positive_int(max_working_mib, "max_working_mib") * 1024**2
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be positive and finite")
    hdf, terrain, terrain_hdf = [_require_path(v, name) for v, name in
        ((hdf_path, "plan HDF"), (terrain_path, "terrain TIFF"), (terrain_hdf, "terrain HDF"))]
    with rasterio.open(terrain) as source:
        crs = source.crs
    if crs is None:
        raise ValueError("Terrain requires a CRS")
    constraint = _aoi.resolve_aoi(bbox=bbox, polygon=polygon, polygon_layer=polygon_layer,
                                 aoi_crs=aoi_crs, default_crs=crs)
    clip = _aoi.geometry_in_crs(constraint, crs) if constraint is not None else None
    references = None
    if native_boundaries is not None:
        references = dict(native_boundaries)
        if set(references) != set(selected):
            raise ValueError("native_boundaries must match all selected profile names exactly")
        references = {key: _require_path(value, "native boundary") for key, value in references.items()}
    folder = _prepare_output_folder(output_folder)
    report = folder / "boundary_comparison.json"
    watched = {hdf, terrain, terrain_hdf}
    if references is not None:
        for path in references.values():
            watched.update(_files(path))
    if isinstance(polygon, (str, os.PathLike)):
        watched.update(_files(Path(polygon)))
    state = dict(schema="ras-commander-boundary-comparison/1", status="in_progress",
        interpolation=interpolation, native_vector_parity=False,
        method=("rasmapper-serial-zero-depth-contours/1" if method == "native_serial" else "deterministic-zero-depth-contours/1"),
        method_difference=("Candidate targets serial native ordering; equality requires complete geometry and unrounded vertex comparison."
            if method == "native_serial" else "Deterministic all-subject NonZero union differs from native stored vector collection; native Max exports may vary."),
        issue="https://github.com/gpt-cmdr/ras-commander-fast-map/issues/4",
        profiles=selected, aoi=constraint.describe() if constraint is not None else None)
    state["preserve_raw_geometry"] = preserve_raw_geometry
    state["native_performance_requested"] = native_performance.to_dict() if native_performance else None
    identities = {str(p): _identity(p) for p in sorted(watched)}
    state["sources"] = identities
    _atomic_json(report, state)
    def unchanged():
        if any(_identity(Path(p)) != identity for p, identity in identities.items()):
            raise RuntimeError("Boundary comparison source changed")
    try:
        # Retained invalid references are preserved before mapping, but do not
        # prevent the candidate from producing independently bound evidence.
        retained = references is not None
        reference_errors, reference_receipts = {}, {}
        state["raw_reference_receipts"] = reference_receipts
        raw_root = folder / "raw_geometry"
        def retain_reference(name, error):
            raw_root.mkdir(exist_ok=True)
            receipt = _boundary_raw.retain_raw_geometry(references[name], raw_root / f"reference-{name}",
                crs, budget, validity_reason=error.validity_reason, topology_valid=False,
                check_sources=unchanged)
            reference_errors[name] = error.validity_reason
            reference_receipts[name] = receipt
        if retained:
            for name, path in references.items():
                plan = _native_pair_plan(path, None, budget) if method == "native_serial" else None
                try:
                    _read_geometry(path, crs, budget, native_plan=plan)
                except FimGeometryError as exc:
                    if not preserve_raw_geometry:
                        raise
                    unchanged()
                    retain_reference(name, exc)
        started = time.perf_counter()
        candidate_error = None
        candidate = None
        try:
            candidate = RasFim.map_inundation_boundaries(hdf, terrain, folder / "rust",
                terrain_hdf=terrain_hdf, profiles=selected, interpolation=interpolation,
                bbox=bbox, polygon=polygon, polygon_layer=polygon_layer, aoi_crs=aoi_crs,
                engine_path=engine_path, threads=threads, max_inflight_profiles=max_inflight_profiles,
                max_working_mib=max_working_mib, max_prepared_mib=max_prepared_mib, timeout=timeout,
                terrain_crs_fnv1a64=terrain_crs_fnv1a64, method=method, allow_unqualified=allow_unqualified,
                preserve_raw_geometry=preserve_raw_geometry)
        except FimGeometryError as exc:
            if not preserve_raw_geometry:
                raise
            unchanged()
            candidate_error = exc
            from types import SimpleNamespace
            candidate = SimpleNamespace(attrs={"manifest": exc.diagnostic_manifest})
        batch_seconds = time.perf_counter() - started
        if candidate_error is None and (len(candidate) != len(selected) or set(candidate.profile) != set(selected)
                or not candidate.status.isin(["complete", "empty"]).all()):
            raise RuntimeError("Candidate report is incomplete or unsuccessful")
        if method == "native_serial":
            _adopt_candidate_terrain_sources(candidate, folder / "rust", budget, terrain, identities, terrain_hdf)
            unchanged()
        if candidate_error is not None:
            candidate_paths, candidate_receipts, candidate_errors = _raw_candidate_outputs(
                candidate_error, folder / "rust", selected, budget, identities)
            unchanged()
        else:
            candidate_paths = {}
            candidate_receipts, candidate_errors = {}, {}
            for item in candidate.itertuples():
                path = _require_path(item.boundary_geojson, "candidate boundary")
                if not path.is_relative_to((folder / "rust").resolve()):
                    raise RuntimeError("Candidate product is outside its fresh output folder")
                candidate_paths[item.profile] = path
        preclipped = False if candidate_error is not None else _candidate_preclipped(candidate, method, clip, crs)
        native_profiles = {key: value for key, value in selected.items()}
        native_times = {key: None for key in selected}
        if references is None:
            references, native_profiles, native_times = _generate_native(
                hdf, terrain_hdf, folder, selected, interpolation, plan_number, terrain_name,
                ras_object, ras_version, timeout, state, native_performance=native_performance)
            if preserve_raw_geometry:
                for name, path in references.items():
                    watched.update(_files(path))
                    for source in _files(path):
                        identities[str(source)] = _identity(source)
                    try:
                        _read_geometry(path, crs, budget, native_plan=_native_pair_plan(path, None, budget))
                    except FimGeometryError as exc:
                        unchanged()
                        retain_reference(name, exc)
        if reference_errors or candidate_error is not None:
            _finish_raw_comparison(state, report, raw_root, selected, candidate_paths, references,
                candidate_receipts, reference_receipts, candidate_errors, reference_errors,
                crs, budget, unchanged)
        rows = []
        for name in selected:
            item = candidate.loc[candidate.profile == name].iloc[0]
            path = _require_path(item.boundary_geojson, "candidate boundary")
            if not path.is_relative_to((folder / "rust").resolve()):
                raise RuntimeError("Candidate product is outside its fresh output folder")
            start = time.perf_counter()
            plan = _native_pair_plan(path, references[name], budget) if method == "native_serial" else None
            cg = _read_geometry(path, crs, budget, native_plan=plan)
            rg = _read_geometry(references[name], crs, budget, native_plan=plan)
            if clip is not None:
                if not preclipped:
                    cg = cg.intersection(clip)
                rg = rg.intersection(clip)
                # Intersections can contain zero-area lines; retain polygonal components only.
                cg, rg = _polygonal(cg), _polygonal(rg)
            if plan is not None:
                # Original pair counts stay reserved during clipping. Check the
                # resulting pair before metric/canonical scratch is allocated.
                import shapely
                infos = [dict(vertices=int(shapely.count_coordinates(g)), features=_stats(g)[0],
                              file_bytes=plan[str(Path(p).resolve())]["file_bytes"])
                         for g, p in ((cg, path), (rg, references[name]))]
                _admit_native_pair(infos, budget)
            values = _metrics(cg, rg)
            rows.append(dict(profile=name, native_profile=native_profiles[name], status="complete",
                interpolation=interpolation, **values, candidate_path=str(path),
                reference_path=str(references[name]), native_seconds=native_times[name],
                candidate_batch_seconds=batch_seconds, comparison_seconds=time.perf_counter() - start))
        unchanged()
        result = pd.DataFrame(rows, columns=COLUMNS)
        performance = dict(candidate_batch_seconds=batch_seconds,
            native_store_maps_seconds=sum(native_times.values()) if not retained else None,
            comparison_seconds=float(result.comparison_seconds.sum()), profile_count=len(selected),
            ratio_eligible=False, observed_native_to_candidate_ratio=None,
            ratio_exclusions=["Native-order model qualification is pending" if method == "native_serial" else "Vector methods differ by design"] +
                (["Retained references have no measured native generation clock"] if retained else []) +
                (["Native full-map generation precedes comparison-only AOI clipping"] if clip is not None else []),
            scope="Candidate batch includes all shared preparation once; repeated batch columns are not per-profile timings. Native clocks cover full stored-map calls. Hashing and comparison are excluded.",
            hausdorff_policy="GEOS discrete Hausdorff; null for empty-versus-nonempty or vertex products above 25 million. No densification.")
        if method == "native_serial":
            performance["geometry_admission"] = {
                "method": "native-vector-pair/1", "max_working_bytes": budget,
                "fixed_bytes": 64 << 20, "bytes_per_pair_vertex": 768,
                "input_file_multiplier": 8, "bytes_per_feature": 4096,
                "scope": "both full input geometries, parsing, GIS overlay and canonical/metrics scratch; planned estimate, not a hard RSS cap",
                "gpkg_large_vector_extension": False}
        result.attrs.update(performance=performance, comparison_report=str(report), native_vector_parity=False)
        from ._manifest_json import records
        state.update(status="complete", performance=performance, rows=records(result))
        result.to_csv(folder / "boundary_comparison.csv", index=False)
        return result
    except BaseException as exc:
        state.update(status="aborted", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        active_error = sys.exc_info()[1]
        try:
            _atomic_json(report, state)
        except OSError as manifest_error:
            if active_error is None:
                raise
            if hasattr(active_error, "add_note"):
                active_error.add_note(f"Could not write aborted boundary comparison receipt: {manifest_error}")


def _raw_candidate_outputs(error, folder, selected, budget, identities):
    """Recheck aborted-map provenance and retained byte identities, without trust shortcuts."""
    folder = folder.resolve()
    manifest = Path(error.diagnostic_manifest).resolve(strict=True)
    if manifest != folder / "boundary_manifest.json":
        raise RuntimeError("Raw candidate manifest is outside its fresh output folder")
    details = _load_json(manifest, budget // 32)
    raw = details.get("raw_geometry", {})
    if (details.get("schema") != "ras-commander-boundary-manifest/1"
            or details.get("status") != "aborted" or details.get("aoi") is not None
            or details.get("method_id") != "rasmapper-serial-zero-depth-contours/1"
            or raw.get("provenance_verified") is not True or raw.get("diagnostic_only") is not True
            or raw.get("qualified") is not False or not isinstance(raw.get("profiles"), dict)
            or not isinstance(raw.get("invalid_profiles"), dict) or not raw["invalid_profiles"]):
        raise RuntimeError("Raw candidate has no verified aborted geometry receipt")
    sources = details.get("sources")
    if not isinstance(sources, dict) or not {"hdf", "terrain", "terrain_hdf", "engine"}.issubset(sources):
        raise RuntimeError("Raw candidate source provenance is incomplete")
    for record in sources.values():
        path = Path(record["path"]).resolve(strict=True)
        identity = _identity(path)
        if (record.get("sha256") != identity["sha256"]
                or record.get("identity") != [identity["size"], identity["mtime_ns"]]):
            raise RuntimeError("Raw candidate source changed")
        if str(path) in identities and identities[str(path)] != identity:
            raise RuntimeError("Raw candidate source identity differs from comparison")
        identities[str(path)] = identity
    paths, receipts = {}, {}
    for name, receipt in raw["profiles"].items():
        if name not in selected or not isinstance(receipt, dict):
            raise RuntimeError("Raw candidate profile differs from comparison")
        receipt_path = Path(receipt.get("diagnostic_manifest", "")).resolve(strict=True)
        if not receipt_path.is_relative_to(folder / "raw_geometry"):
            raise RuntimeError("Raw candidate receipt escaped its owned output folder")
        if _load_json(receipt_path, budget // 32) != receipt:
            raise RuntimeError("Raw candidate retained receipt changed")
        if (receipt.get("schema") != "ras-commander-raw-boundary-artifacts/1"
                or receipt.get("status") != "aborted" or receipt.get("diagnostic_only") is not True
                or receipt.get("qualified") is not False or receipt.get("native_vector_parity") is not False
                or not isinstance(receipt.get("artifacts"), list) or len(receipt["artifacts"]) != 1):
            raise RuntimeError("Raw candidate artifact receipt is incomplete")
        record = receipt["artifacts"][0]
        path = Path(record["path"]).resolve(strict=True)
        if path != receipt_path.parent / "artifacts" / f"{name}.geojson" or path.is_symlink():
            raise RuntimeError("Raw candidate artifact escaped its owned profile folder")
        from ._boundary_raw import _identity as raw_identity, _regular
        identity = raw_identity(_regular(path))
        if identity != record.get("retained_identity") or identity["sha256"] != record.get("sha256"):
            raise RuntimeError("Raw candidate artifact changed")
        paths[name], receipts[name] = path, receipt
    invalid = raw["invalid_profiles"]
    if any(name not in selected or not isinstance(reason, str) or not reason for name, reason in invalid.items()):
        raise RuntimeError("Raw candidate invalid-profile receipt is inconsistent")
    return paths, receipts, invalid


def _finish_raw_comparison(state, report, raw_root, selected, candidates, references,
        candidate_receipts, reference_receipts, candidate_errors, reference_errors,
        crs, budget, unchanged):
    """Publish aborted raw-only evidence; never produce normal metric rows."""
    from . import _boundary_raw
    raw_root.mkdir(exist_ok=True)
    diagnostics = []
    all_artifacts = []
    for name in selected:
        cp, rp = candidates.get(name), references.get(name)
        row = {"profile": name, "candidate_available": cp is not None,
            "reference_available": rp is not None, "diagnostic_only": True,
            "normal_comparison_eligible": False, "qualified": False,
            "candidate_topology_valid": name not in candidate_errors if cp is not None else None,
            "reference_topology_valid": name not in reference_errors if rp is not None else None}
        for side, path, receipts, errors in (("candidate", cp, candidate_receipts, candidate_errors),
                                            ("reference", rp, reference_receipts, reference_errors)):
            if path is None:
                continue
            if name not in receipts:
                # Normal candidate delivery is independently rechecked before raw retention.
                try:
                    _read_geometry(path, crs, budget, native_plan=_native_pair_plan(path, None, budget))
                except FimGeometryError as exc:
                    errors[name] = exc.validity_reason
                    row[f"{side}_topology_valid"] = False
                receipts[name] = _boundary_raw.retain_raw_geometry(path, raw_root / f"{side}-{name}",
                    crs, budget, validity_reason=errors.get(name, "Valid topology paired with invalid boundary"),
                    topology_valid=name not in errors, check_sources=unchanged)
            row[f"{side}_receipt"] = receipts[name]
            all_artifacts.extend(artifact["path"] for artifact in receipts[name]["artifacts"])
        if cp is not None and rp is not None:
            row["raw_comparison"] = _boundary_raw.compare_raw_geometry(cp, rp, crs, budget,
                check_sources=unchanged)
        diagnostics.append(row)
    unchanged()
    complete = all(row["candidate_available"] and row["reference_available"] for row in diagnostics)
    state.update(status="aborted", diagnostic_only=True, qualified=False,
        normal_comparison_eligible=False, ratio_eligible=False, rows=[],
        complete_raw_profile_coverage=complete, raw_profiles=diagnostics,
        raw_profile_missing=[row["profile"] for row in diagnostics
                             if not row["candidate_available"] or not row["reference_available"]],
        topology_invalid={"candidate": candidate_errors, "reference": reference_errors})
    _atomic_json(report, state)
    raise FimGeometryError("Boundary topology invalid; raw comparisons are diagnostic only",
        diagnostic_manifest=str(report), artifacts=all_artifacts,
        validity_reason="; ".join(f"{side} {name}: {reason}" for side, errors in
            (("candidate", candidate_errors), ("reference", reference_errors)) for name, reason in errors.items()))


def _adopt_candidate_terrain_sources(candidate, folder, budget, primary, identities, terrain_hdf=None):
    """Keep every original mosaic source bound through native comparison."""
    manifest = Path(candidate.attrs.get("manifest", folder / "boundary_manifest.json")).resolve(strict=True)
    if manifest != (folder / "boundary_manifest.json").resolve():
        raise RuntimeError("Candidate terrain receipt is outside its fresh output folder")
    details = _load_json(manifest, budget // 32)
    receipt = details.get("terrain_source_receipt", {})
    records = receipt.get("source_identities")
    extras = details.get("additional_terrains")
    if (receipt.get("schema") != "ras-commander-boundary-terrain-sources/1"
            or not isinstance(records, list) or not records or not isinstance(extras, list)
            or len(records) != len(extras) + 1):
        raise RuntimeError("Candidate ordered terrain source receipt is incomplete")
    expected = [primary] + [Path(source["terrain"]).resolve(strict=True) for source in extras]
    if len(set(expected)) != len(expected):
        raise RuntimeError("Candidate ordered terrain source receipt repeats a TIFF")
    for index, (record, path) in enumerate(zip(records, expected)):
        identity = _identity(path)
        if (not isinstance(record, dict) or type(record.get("effective_index")) is not int
                or record["effective_index"] != index or record.get("path") != str(path)
                or any(record.get(key) != value for key, value in identity.items())
                or (str(path) in identities and identities[str(path)] != identity)):
            raise RuntimeError("Boundary comparison terrain source changed or receipt is inconsistent")
        identities[str(path)] = identity
    evidence = receipt.get("terrain_crs_evidence") or {}
    if evidence.get("kind") == "registered-vrt-source-identity/1":
        path = Path(evidence["path"]).resolve(strict=True)
        identity = _identity(path)
        if (terrain_hdf is None or path != terrain_hdf.with_suffix(".vrt")
                or evidence.get("source_files") != [str(p) for p in expected]
                or any(evidence.get(key) != value for key, value in identity.items())):
            raise RuntimeError("Boundary comparison registered VRT changed or receipt is inconsistent")
        identities[str(path)] = identity


def _candidate_preclipped(candidate, method, clip, crs):
    """Skip a second GIS clip only when the exact delivered AOI is bound."""
    if (clip is None or method != "native_serial"
            or candidate.attrs.get("aoi_clipping_method") != "unrounded-geos-intersection/1"):
        return False
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    aoi = candidate.attrs.get("aoi")
    try:
        matched = (isinstance(aoi, dict)
            and aoi.get("clip_geometry_wkb_hex") == clip.wkb_hex
            and CRS.from_user_input(aoi.get("clip_crs")) == CRS.from_user_input(crs))
    except (TypeError, ValueError, CRSError):
        matched = False
    if not matched:
        raise RuntimeError("Candidate GIS clipping receipt does not match the exact comparison AOI")
    return True


def _polygonal(geometry):
    import shapely
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    parts = []
    for part in getattr(geometry, "geoms", []):
        if part.geom_type == "Polygon":
            parts.append(part)
        elif part.geom_type in ("MultiPolygon", "GeometryCollection"):
            parts.extend(shapely.get_parts(_polygonal(part)))
    return shapely.union_all(parts)


def _generate_native(hdf, terrain_hdf, folder, selected, interpolation, plan_number,
                     terrain_name, ras_object, ras_version, timeout, state, native_performance=None):
    from ..RasProcess import RasProcess, _serialize_store_maps
    from ..RasPlan import RasPlan
    from ..RasPrj import ras
    from ..RasMap import RasMap
    from ..RasUtils import RasUtils
    if plan_number is None:
        raise ValueError("plan_number is required to generate native boundaries")
    obj = ras_object or ras
    obj.check_initialized()
    plan = RasUtils.normalize_ras_number(plan_number)
    matches = obj.plan_df.loc[obj.plan_df.plan_number.astype(str).str.zfill(2) == plan]
    if len(matches) != 1:
        raise ValueError("Plan number must resolve to exactly one initialized plan")
    plan_path = Path(RasPlan.get_plan_path(plan, ras_object=obj)).resolve(strict=True)
    if Path(str(plan_path) + ".hdf").resolve(strict=True) != hdf:
        raise ValueError("Native plan HDF differs from candidate HDF")
    layers = RasMap.list_terrain_layers(obj.project_folder, ras_object=obj)
    if terrain_name is None:
        if len(layers) != 1:
            raise ValueError("Select terrain_name explicitly for multiple native terrains")
        terrain_name = str(layers.iloc[0]["name"])
    match = layers.loc[layers["name"] == terrain_name]
    if len(match) != 1 or Path(match.iloc[0]["resolved_path"]).resolve(strict=True) != terrain_hdf:
        raise ValueError("Registered native terrain differs from terrain_hdf")
    steady_names = None
    if native_performance is not None and native_performance.native_polygon_serial:
        from ..hdf.HdfResultsPlan import HdfResultsPlan
        if HdfResultsPlan.is_steady_plan(hdf):
            steady_names = HdfResultsPlan.get_steady_profile_names(hdf)
    timestamps = (RasProcess.get_plan_timestamps(plan, ras_object=obj)
        if steady_names is None and any(v != "Max" for v in selected.values()) else [])
    native_profiles = {}
    for name, selector in selected.items():
        if steady_names is not None:
            if isinstance(selector, int):
                if not 0 <= selector < len(steady_names):
                    raise ValueError("Stored steady profile index is unavailable")
                profile = steady_names[selector]
            else:
                profile = selector
            if steady_names.count(profile) != 1:
                raise ValueError("Select an exact, unambiguous stored steady profile; Max aggregation is not defined")
            native_profiles[name] = profile
            continue
        if selector != "Max" and (not isinstance(selector, int) or selector < 0):
            raise ValueError("Unsteady native boundaries require Max or a stored timestep index")
        if selector != "Max" and selector >= len(timestamps):
            raise ValueError(f"Stored timestep index {selector} is unavailable")
        native_profiles[name] = "Max" if selector == "Max" else timestamps[selector]
        if selector != "Max" and timestamps.count(native_profiles[name]) != 1:
            raise ValueError("Native timestamp string is ambiguous across stored indices")
    paths, clocks = {}, {}
    serial_reference = native_performance is not None and native_performance.native_polygon_serial
    @_serialize_store_maps
    def execute(*, ras_object, timeout):
        path = Path(RasMap.get_rasmap_path(ras_object))
        original = path.read_bytes()
        state["rasmap_sha256_before"] = hashlib.sha256(original).hexdigest()
        original_inputs = {str(p): _identity(p) for p in (hdf, terrain_hdf, plan_path)}
        if serial_reference:
            state["native_runtime_requested"] = ras_version
            state["native_runtime_before"] = RasProcess.get_store_maps_runtime_provenance(ras_object)
        try:
            for name, profile in native_profiles.items():
                output = folder / "native" / name
                if output.exists():
                    raise FileExistsError("Native evidence output must be fresh")
                start = time.perf_counter()
                products = RasProcess.store_maps(plan, output_path=output, profile=profile,
                    render_mode=interpolation, wse=False, depth=False, velocity=False,
                    inundation_boundary=True, terrain_name=terrain_name, ras_object=ras_object,
                    ras_version=ras_version, timeout=timeout, performance=native_performance)
                clocks[name] = time.perf_counter() - start
                if not path.exists() or path.read_bytes() != original:
                    raise RuntimeError("Native stored maps did not restore original rasmap")
                values = products.get("inundation_boundary", [])
                if len(values) != 1:
                    raise RuntimeError("Native export did not return exactly one fresh boundary")
                product = Path(values[0]).resolve(strict=True)
                if not product.is_relative_to(output.resolve()):
                    raise RuntimeError("Native boundary is outside fresh evidence folder")
                _files(product)
                paths[name] = product
                state.setdefault("native_products", {})[name] = str(product)
            if any(_identity(Path(p)) != identity for p, identity in original_inputs.items()):
                raise RuntimeError("Native export changed original plan or terrain HDF")
            state["native_sources"] = original_inputs
        finally:
            # Source auditing must never prevent restoration of project state.
            try:
                if serial_reference:
                    try:
                        state["native_runtime_after"] = RasProcess.get_store_maps_runtime_provenance(ras_object)
                        state["native_runtime_unchanged"] = state["native_runtime_before"] == state["native_runtime_after"]
                    except Exception as runtime_error:
                        state["native_runtime_unchanged"] = False
                        state["native_runtime_audit_error"] = str(runtime_error)
                state["native_sources"] = original_inputs
                try:
                    state["native_sources_unchanged"] = all(
                        Path(p).is_file() and _identity(Path(p)) == identity
                        for p, identity in original_inputs.items())
                except OSError as audit_error:
                    state["native_sources_unchanged"] = False
                    state["native_source_audit_error"] = str(audit_error)
            finally:
                if not path.exists() or path.read_bytes() != original:
                    restore = path.with_name(path.name + f".{uuid.uuid4().hex}.restore")
                    try:
                        restore.write_bytes(original)
                        os.replace(restore, path)
                    finally:
                        restore.unlink(missing_ok=True)
                restored = path.read_bytes()
                state["rasmap_sha256_after"] = hashlib.sha256(restored).hexdigest()
                state["rasmap_restored"] = restored == original
                if not state["rasmap_restored"]:
                    raise RuntimeError("Failed to restore original rasmap")
        if serial_reference and not state["native_runtime_unchanged"]:
            raise RuntimeError("Native export runtime/helper identity changed")
    execute(ras_object=obj, timeout=600 if timeout is None else timeout)
    return paths, native_profiles, clocks
