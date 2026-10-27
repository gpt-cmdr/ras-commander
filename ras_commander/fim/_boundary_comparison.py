"""Full-geometry comparison of deterministic contours and native stored polygons."""

import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

import pandas as pd

from . import _aoi
from ._boundary import _atomic_json, _load_json
from ._sloping import _validate_selection

COLUMNS = [
    "profile", "native_profile", "status", "interpolation",
    "candidate_polygons", "reference_polygons", "candidate_holes", "reference_holes",
    "candidate_vertices", "reference_vertices", "candidate_area", "reference_area",
    "extra_area", "missing_area", "symmetric_difference_area", "intersection_over_union",
    "hausdorff_distance", "geometry_equal", "quantized_coordinates_equal",
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


def _read_geometry(path, model_crs, budget):
    """Admit bounded vector files before parsing; never repair or reproject."""
    import numpy as np
    import shapely
    from pyproj import CRS

    paths = _files(path)
    if any(p.is_symlink() for p in paths) or sum(p.stat().st_size for p in paths) > budget // 32:
        raise ValueError("Vector input exceeds planned geometry file budget")
    suffix = Path(path).suffix.lower()
    if suffix in (".geojson", ".json"):
        data = _load_json(Path(path), budget // 32)
        crs = data.get("crs", {}).get("properties", {}).get("name")
        if not crs:
            raise ValueError("Reference GeoJSON requires an explicit stored CRS")
        features = data.get("features")
        if data.get("type") != "FeatureCollection" or not isinstance(features, list):
            raise ValueError("Expected polygon FeatureCollection")
        if len(features) > min(100_000, budget // 4096):
            raise ValueError("Vector feature count exceeds planned budget")
        # Count positions before allocating GEOS geometries.
        def positions(value):
            if not isinstance(value, list):
                raise ValueError("Invalid coordinate array")
            if value and isinstance(value[0], (float, int)):
                if len(value) != 2 or not all(math.isfinite(v) for v in value):
                    raise ValueError("Polygon coordinates must be finite XY")
                return 1
            return sum(positions(child) for child in value)
        count = sum(positions(f["geometry"]["coordinates"]) for f in features)
        if count > min(500_000, budget // 1024):
            raise ValueError("Vector vertices exceed planned geometry budget")
        geometries = [shapely.geometry.shape(f["geometry"]) for f in features]
    elif suffix in (".shp", ".gpkg"):
        import pyogrio
        layers = pyogrio.list_layers(path)
        if len(layers) != 1:
            raise ValueError("Reference vector must contain exactly one polygon layer")
        info = pyogrio.read_info(path)
        if info["features"] < 0 or info["features"] > min(100_000, budget // 4096):
            raise ValueError("Unbounded reference feature count")
        frame = pyogrio.read_dataframe(path)
        crs, geometries = frame.crs, list(frame.geometry)
    else:
        raise ValueError("Boundary reference must be SHP, GPKG or GeoJSON")
    if crs is None or not CRS.from_user_input(crs).equals(CRS.from_user_input(model_crs)):
        raise ValueError("Boundary CRS differs from model CRS; reprojection is forbidden")
    if sum(int(shapely.count_coordinates(g)) for g in geometries) > min(500_000, budget // 1024):
        raise ValueError("Vector vertices exceed planned geometry budget")
    for geometry in geometries:
        if geometry is None or geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Boundary contains a missing or non-polygon geometry")
        if not geometry.is_valid or not np.isfinite(shapely.get_coordinates(geometry)).all():
            raise ValueError("Boundary geometry is invalid or nonfinite; repair is forbidden")
    # Preserve every stored vertex. Unary union can discard collinear points
    # or merge parts, which would conceal coordinate/topology differences.
    if len(geometries) == 1:
        return geometries[0]
    parts = []
    for geometry in geometries:
        parts.extend([geometry] if geometry.geom_type == "Polygon" else geometry.geoms)
    geometry = shapely.MultiPolygon(parts)
    if not geometry.is_valid:
        raise ValueError("Combined boundary parts overlap or are invalid; union repair is forbidden")
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


def _canonical(geometry):
    def ring(value):
        points = []
        for x, y in value.coords:
            if max(abs(x), abs(y)) * 1000 >= 2**61:
                raise ValueError("Coordinate exceeds safe 0.001-unit quantization range")
            points.append((round(x * 1000), round(y * 1000)))
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
        quantized_coordinates_equal=_canonical(candidate) == _canonical(reference))


def run(hdf_path, terrain_path, output_folder, *, terrain_hdf, profiles=None,
        interpolation="sloping", native_boundaries=None, plan_number=None, terrain_name=None,
        ras_object=None, ras_version=None, bbox=None, polygon=None, polygon_layer=None,
        aoi_crs=None, engine_path=None, threads=1, max_inflight_profiles=1,
        max_working_mib=1024, max_prepared_mib=1024, timeout=None,
        terrain_crs_fnv1a64=None):
    """Compare complete vector geometry; native vector parity is not presumed."""
    import rasterio
    from .RasFim import RasFim, _prepare_output_folder, _require_path, _positive_int

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
        method="deterministic-zero-depth-contours/1",
        method_difference="Deterministic all-subject NonZero union differs from native stored vector collection; native Max exports may vary.",
        issue="https://github.com/gpt-cmdr/ras-commander-fast-map/issues/4",
        profiles=selected, aoi=constraint.describe() if constraint is not None else None)
    identities = {str(p): _identity(p) for p in sorted(watched)}
    state["sources"] = identities
    _atomic_json(report, state)
    def unchanged():
        if any(_identity(Path(p)) != identity for p, identity in identities.items()):
            raise RuntimeError("Boundary comparison source changed")
    try:
        # Admit retained references before starting an expensive candidate batch.
        retained = references is not None
        if retained:
            for path in references.values():
                _read_geometry(path, crs, budget)
        started = time.perf_counter()
        candidate = RasFim.map_inundation_boundaries(hdf, terrain, folder / "rust",
            terrain_hdf=terrain_hdf, profiles=selected, interpolation=interpolation,
            bbox=bbox, polygon=polygon, polygon_layer=polygon_layer, aoi_crs=aoi_crs,
            engine_path=engine_path, threads=threads, max_inflight_profiles=max_inflight_profiles,
            max_working_mib=max_working_mib, max_prepared_mib=max_prepared_mib, timeout=timeout,
            terrain_crs_fnv1a64=terrain_crs_fnv1a64)
        batch_seconds = time.perf_counter() - started
        if len(candidate) != len(selected) or set(candidate.profile) != set(selected) or not candidate.status.isin(["complete", "empty"]).all():
            raise RuntimeError("Candidate report is incomplete or unsuccessful")
        native_profiles = {key: value for key, value in selected.items()}
        native_times = {key: None for key in selected}
        if references is None:
            references, native_profiles, native_times = _generate_native(
                hdf, terrain_hdf, folder, selected, interpolation, plan_number, terrain_name,
                ras_object, ras_version, timeout, state)
        rows = []
        for name in selected:
            item = candidate.loc[candidate.profile == name].iloc[0]
            path = _require_path(item.boundary_geojson, "candidate boundary")
            if not path.is_relative_to((folder / "rust").resolve()):
                raise RuntimeError("Candidate product is outside its fresh output folder")
            start = time.perf_counter()
            cg = _read_geometry(path, crs, budget)
            rg = _read_geometry(references[name], crs, budget)
            if clip is not None:
                cg, rg = cg.intersection(clip), rg.intersection(clip)
                # Intersections can contain zero-area lines; retain polygonal components only.
                cg, rg = _polygonal(cg), _polygonal(rg)
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
            ratio_exclusions=["Vector methods differ by design"] +
                (["Retained references have no measured native generation clock"] if retained else []) +
                (["Native full-map generation precedes comparison-only AOI clipping"] if clip is not None else []),
            scope="Candidate batch includes all shared preparation once; repeated batch columns are not per-profile timings. Native clocks cover full stored-map calls. Hashing and comparison are excluded.",
            hausdorff_policy="GEOS discrete Hausdorff; null for empty-versus-nonempty or vertex products above 25 million. No densification.")
        result.attrs.update(performance=performance, comparison_report=str(report), native_vector_parity=False)
        state.update(status="complete", performance=performance, rows=json.loads(result.to_json(orient="records")))
        result.to_csv(folder / "boundary_comparison.csv", index=False)
        return result
    except BaseException as exc:
        state.update(status="aborted", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _atomic_json(report, state)


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
                     terrain_name, ras_object, ras_version, timeout, state):
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
    timestamps = RasProcess.get_plan_timestamps(plan, ras_object=obj) if any(v != "Max" for v in selected.values()) else []
    native_profiles = {}
    for name, selector in selected.items():
        if selector != "Max" and selector >= len(timestamps):
            raise ValueError(f"Stored timestep index {selector} is unavailable")
        native_profiles[name] = "Max" if selector == "Max" else timestamps[selector]
        if selector != "Max" and timestamps.count(native_profiles[name]) != 1:
            raise ValueError("Native timestamp string is ambiguous across stored indices")
    paths, clocks = {}, {}
    @_serialize_store_maps
    def execute(*, ras_object, timeout):
        path = Path(RasMap.get_rasmap_path(ras_object))
        original = path.read_bytes()
        state["rasmap_sha256_before"] = hashlib.sha256(original).hexdigest()
        original_inputs = {str(p): _identity(p) for p in (hdf, terrain_hdf, plan_path)}
        try:
            for name, profile in native_profiles.items():
                output = folder / "native" / name
                if output.exists():
                    raise FileExistsError("Native evidence output must be fresh")
                start = time.perf_counter()
                products = RasProcess.store_maps(plan, output_path=output, profile=profile,
                    render_mode=interpolation, wse=False, depth=False, velocity=False,
                    inundation_boundary=True, terrain_name=terrain_name, ras_object=ras_object,
                    ras_version=ras_version, timeout=timeout)
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
    execute(ras_object=obj, timeout=600 if timeout is None else timeout)
    return paths, native_profiles, clocks
