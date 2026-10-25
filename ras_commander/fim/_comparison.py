"""Native horizontal stored-map qualification with byte-preserved rasmap state."""

from pathlib import Path
import hashlib
import json
import os
import time
import uuid
from contextlib import nullcontext
import numpy as np
import pandas as pd
from .errors import FimUnsupportedError

COLUMNS = [
    "profile",
    "native_profile",
    "candidate_wet",
    "reference_wet",
    "common_wet",
    "extra_wet",
    "missing_wet",
    "csi",
    "depth_exact_fraction",
    "depth_mae",
    "depth_max_abs",
    "wse_pairs",
    "wse_exact_fraction",
    "wse_mae",
    "wse_max_abs",
    "reference_missing_wse",
    "candidate_missing_wse",
    "terrain_pairs",
    "terrain_mae",
    "terrain_max_abs",
    "depth_tif",
    "reference_depth_tif",
    "wse_tif",
    "reference_wse_tif",
    "native_seconds",
]


def compare_rasters(
    depth_path, wse_path, native_depth, native_wse, cells, constraint, threshold, terrain_path=None
):
    """Stream matching terrain pixels; never reproject or resample a reference."""
    import rasterio
    import shapely
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, bounds
    from . import _aoi, _prepare

    threshold = np.float32(float(threshold))
    counters = dict(
        candidate_wet=0,
        reference_wet=0,
        common_wet=0,
        extra_wet=0,
        missing_wet=0,
        wse_pairs=0,
        reference_missing_wse=0,
        candidate_missing_wse=0,
        terrain_pairs=0,
    )
    depth_sum = wse_sum = terrain_sum = 0.0
    depth_max = wse_max = terrain_max = 0.0
    depth_exact = wse_exact = 0
    with rasterio.open(depth_path) as d, rasterio.open(wse_path) as w, rasterio.open(
        native_depth
    ) as nd, rasterio.open(native_wse) as nw, (
        rasterio.open(terrain_path) if terrain_path else nullcontext(None)
    ) as gt:
        for other in (w, nd, nw):
            if (
                not _prepare.same_crs(d.crs, other.crs)
                or d.transform.b
                or d.transform.d
                or other.transform.b
                or other.transform.d
            ):
                raise FimUnsupportedError(
                    "comparison requires the same CRS and north-up pixel lattice"
                )
            if not np.allclose(
                [d.transform.a, d.transform.e],
                [other.transform.a, other.transform.e],
                rtol=1e-12,
                atol=0,
            ):
                raise FimUnsupportedError(
                    "comparison resolution differs; reference resampling is forbidden"
                )
            offsets = (
                (d.transform.c - other.transform.c) / d.transform.a,
                (d.transform.f - other.transform.f) / d.transform.e,
            )
            if any(abs(v - round(v)) > 1e-6 for v in offsets):
                raise FimUnsupportedError(
                    "comparison grids are not aligned at integer pixel offsets"
                )
        shape = _aoi.geometry_in_crs(constraint, _aoi.to_crs(d.crs)) if constraint else None
        index = cells.sindex
        for r in range(0, d.height, 256):
            window = Window(0, r, d.width, min(256, d.height - r))
            t = d.window_transform(window)
            dims = (int(window.height), int(window.width))
            selected = index.query(
                shapely.box(*bounds(window, d.transform)), predicate="intersects"
            )
            if not len(selected):
                continue
            inside = geometry_mask(
                cells.geometry.iloc[selected].to_list(), out_shape=dims, transform=t, invert=True
            )
            if shape is not None:
                inside &= geometry_mask([shape], out_shape=dims, transform=t, invert=True)

            def read(src):
                c = round((t.c - src.transform.c) / src.transform.a)
                y = round((t.f - src.transform.f) / src.transform.e)
                return (
                    src.read(1, window=Window(c, y, dims[1], dims[0]), boundless=True, masked=True)
                    .astype("float32")
                    .filled(np.nan)
                )

            a, b, aw, bw = read(d), read(nd), read(w), read(nw)
            ground = read(gt) if gt is not None else None
            ca = inside & np.isfinite(a) & (a > threshold)
            cb = inside & np.isfinite(b) & (b > threshold)
            common = ca & cb
            pair = common & np.isfinite(aw) & np.isfinite(bw)
            for key, value in [
                ("candidate_wet", ca),
                ("reference_wet", cb),
                ("common_wet", common),
                ("extra_wet", ca & ~cb),
                ("missing_wet", cb & ~ca),
                ("wse_pairs", pair),
                ("reference_missing_wse", cb & ~np.isfinite(bw)),
                ("candidate_missing_wse", ca & ~np.isfinite(aw)),
            ]:
                counters[key] += int(value.sum())
            delta = np.abs(a[common].astype("float64") - b[common])
            wd = np.abs(aw[pair].astype("float64") - bw[pair])
            if ground is not None:
                paired = cb & np.isfinite(bw) & np.isfinite(ground)
                residual = np.abs(
                    bw[paired].astype("float64") - b[paired].astype("float64") - ground[paired]
                )
                counters["terrain_pairs"] += int(paired.sum())
                terrain_sum += float(residual.sum())
                terrain_max = max(terrain_max, float(residual.max(initial=0)))
            depth_sum += float(delta.sum())
            wse_sum += float(wd.sum())
            depth_exact += int((delta == 0).sum())
            wse_exact += int((wd == 0).sum())
            depth_max = max(depth_max, float(delta.max(initial=0)))
            wse_max = max(wse_max, float(wd.max(initial=0)))
    n = counters["common_wet"]
    m = counters["wse_pairs"]
    union = n + counters["extra_wet"] + counters["missing_wet"]
    return {
        **counters,
        "csi": n / union if union else 1.0,
        "depth_exact_fraction": depth_exact / n if n else np.nan,
        "depth_mae": depth_sum / n if n else np.nan,
        "depth_max_abs": depth_max if n else np.nan,
        "wse_exact_fraction": wse_exact / m if m else np.nan,
        "wse_mae": wse_sum / m if m else np.nan,
        "wse_max_abs": wse_max if m else np.nan,
        "terrain_mae": (
            terrain_sum / counters["terrain_pairs"] if counters["terrain_pairs"] else np.nan
        ),
        "terrain_max_abs": terrain_max if counters["terrain_pairs"] else np.nan,
    }


def run(
    plan_number,
    terrain_path,
    output_folder,
    *,
    cells,
    profiles,
    mesh_name,
    bbox,
    polygon,
    polygon_layer,
    aoi_crs,
    min_depth,
    engine_path,
    threads,
    max_working_mib,
    terrain_name,
    ras_object,
    ras_version,
    timeout,
):
    from ..RasProcess import RasProcess, _serialize_store_maps
    from ..RasMap import RasMap
    from ..RasPrj import ras
    from ..RasUtils import RasUtils
    from ..RasPlan import RasPlan
    from .RasFim import RasFim, _prepare_output_folder, _require_path, _validate_cells
    from . import _aoi

    obj = ras_object or ras
    obj.check_initialized()
    plan = RasUtils.normalize_ras_number(plan_number)
    matches = obj.plan_df.loc[obj.plan_df.plan_number.astype(str).str.zfill(2) == plan]
    if len(matches) != 1:
        raise ValueError(f"plan {plan!r} does not identify exactly one plan")
    plan_path = RasPlan.get_plan_path(plan, ras_object=obj)
    if plan_path is None:
        raise FileNotFoundError(f"plan {plan} has no resolved plan path")
    hdf = _require_path(Path(str(plan_path) + ".hdf"), "plan HDF")
    if cells is None:
        if profiles is not None:
            raise ValueError(
                "profiles requires an explicit cells table; automatic extraction maps Max only"
            )
        cells = RasFim.get_cells_from_plan_hdf(hdf, mesh_name=mesh_name)
        profiles = {"wsel_max": "Max"}
    elif profiles is None:
        raise ValueError("provide profiles={WSE_column: exact native profile} with cells")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("profiles must be a nonempty mapping of WSE columns to native profiles")
    names = _validate_cells(cells, list(profiles), "wsel")
    available = (
        RasProcess.get_plan_timestamps(plan, obj)
        if any(v != "Max" for v in profiles.values())
        else []
    )
    if any(
        not isinstance(v, str) or (v != "Max" and v not in available) for v in profiles.values()
    ):
        raise ValueError(
            "native profiles must be Max or exact available stored timestamps; no nearest-time fallback"
        )
    if (
        isinstance(min_depth, bool)
        or not np.isfinite(min_depth)
        or min_depth < 0
        or min_depth > np.finfo(np.float32).max
    ):
        raise ValueError("min_depth must be finite and >= 0 in model elevation units")
    terrain = _require_path(terrain_path, "terrain_path")
    constraint = _aoi.resolve_aoi(
        bbox=bbox,
        polygon=polygon,
        polygon_layer=polygon_layer,
        aoi_crs=aoi_crs,
        default_crs=cells.crs,
    )
    layers = RasMap.list_terrain_layers(obj.project_folder, ras_object=obj)
    if terrain_name is None:
        if len(layers) != 1:
            raise ValueError(
                "select terrain_name explicitly when native terrain registration is ambiguous"
            )
        terrain_name = str(layers.iloc[0]["name"])
    selected = layers.loc[layers["name"] == terrain_name]
    if len(selected) != 1:
        raise ValueError("terrain_name must identify exactly one registered terrain")
    registered = _require_path(selected.iloc[0]["resolved_path"], "registered terrain HDF")
    folder = _prepare_output_folder(output_folder)
    state = {
        "schema": "ras-commander-fim-comparison/1",
        "status": "in_progress",
        "plan": plan,
        "render_mode": "horizontal",
        "min_depth": float(min_depth),
        "effective_float32_threshold": float(np.float32(float(min_depth))),
        "profiles": profiles,
        "comparison": "same lattice; no reference resampling; strict depth filter independently applied",
        "scope": "selected 2D cells and AOI; native sloping/1D/structures not qualified",
    }

    def sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for data in iter(lambda: stream.read(8 << 20), b""):
                digest.update(data)
        return digest.hexdigest()

    state["terrain"] = {
        "path": str(terrain),
        "size": terrain.stat().st_size,
        "mtime_ns": terrain.stat().st_mtime_ns,
        "sha256": sha256(terrain),
        "registered_name": terrain_name,
        "registered_hdf_sha256": sha256(registered),
        "registration": selected.iloc[0].to_dict(),
    }
    state["plan_hdf"] = {"path": str(hdf), "sha256": sha256(hdf)}
    identities = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (hdf, terrain)}
    report = folder / "comparison.json"

    def write():
        partial = report.with_suffix(".json.partial")
        with partial.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, report)

    write()

    # Reuse the exact same project lock as native StoreMaps, including across processes.
    @_serialize_store_maps
    def execute(*, ras_object, timeout):
        path = RasMap.get_rasmap_path(ras_object)
        if path is None:
            raise FileNotFoundError("comparison requires a project .rasmap")
        path = Path(path)
        original = path.read_bytes()
        state["rasmap_sha256_before"] = hashlib.sha256(original).hexdigest()
        if ras_version is None:
            state["runtime"] = RasProcess.get_store_maps_runtime_provenance(ras_object)
        else:
            from .._native_helper import store_maps_runtime_provenance

            state["runtime"] = store_maps_runtime_provenance(
                Path(RasProcess.find_rasprocess(ras_version)).parent
            )
        rows = []
        try:
            started = time.perf_counter()
            mapped = RasFim.map_horizontal_profiles(
                cells,
                terrain,
                folder / "rust",
                profiles=names,
                bbox=bbox,
                polygon=polygon,
                polygon_layer=polygon_layer,
                aoi_crs=aoi_crs,
                min_depth=min_depth,
                engine_path=engine_path,
                threads=threads,
                max_working_mib=max_working_mib,
                timeout=timeout,
                write_floodplain=False,
            )
            state["candidate_batch_seconds"] = time.perf_counter() - started
            for i, name in enumerate(names):
                candidate = mapped.loc[mapped.profile == name].iloc[0]
                if candidate.status not in ("complete", "no_flooded_pixels"):
                    raise FimUnsupportedError(
                        f"comparison cannot evaluate {candidate.status}: {name}"
                    )
                native_dir = folder / f"native-{i:04d}"
                native_dir.mkdir()
                tick = time.perf_counter()
                products = RasProcess.store_maps(
                    plan,
                    output_path=native_dir,
                    profile=profiles[name],
                    render_mode="horizontal",
                    wse=True,
                    depth=True,
                    velocity=False,
                    terrain_name=terrain_name,
                    ras_object=ras_object,
                    ras_version=ras_version,
                    timeout=timeout,
                )
                native_seconds = time.perf_counter() - tick
                if not path.exists() or path.read_bytes() != original:
                    raise RuntimeError("StoreMaps did not restore the original rasmap bytes")

                def one(kind):
                    paths = products.get(kind, [])
                    if len(paths) != 1:
                        raise FimUnsupportedError(
                            f"comparison requires exactly one {kind} mosaic; got {len(paths)}; select terrain_name"
                        )
                    return Path(paths[0])

                nd, nw = one("depth"), one("wse")
                values = compare_rasters(
                    candidate.depth_tif,
                    candidate.wse_tif,
                    nd,
                    nw,
                    cells,
                    constraint,
                    min_depth,
                    terrain,
                )
                rows.append(
                    {
                        "profile": name,
                        "native_profile": profiles[name],
                        **values,
                        "depth_tif": candidate.depth_tif,
                        "wse_tif": candidate.wse_tif,
                        "reference_depth_tif": str(nd),
                        "reference_wse_tif": str(nw),
                        "native_seconds": native_seconds,
                    }
                )
            changed = [
                str(path)
                for path, before in identities.items()
                if (path.stat().st_size, path.stat().st_mtime_ns) != before
            ]
            if changed:
                raise RuntimeError(f"comparison inputs changed: {changed}")
            return pd.DataFrame(rows, columns=COLUMNS)
        finally:
            if not path.exists() or path.read_bytes() != original:
                restore = path.with_name(path.name + f".{uuid.uuid4().hex}.restore")
                restore.write_bytes(original)
                os.replace(restore, path)
            state["rasmap_sha256_after"] = hashlib.sha256(path.read_bytes()).hexdigest()
            state["rasmap_restored"] = path.read_bytes() == original
            if not state["rasmap_restored"]:
                raise RuntimeError("failed to restore original rasmap")

    try:
        result = execute(ras_object=obj, timeout=timeout)
        result.to_csv(folder / "comparison.csv", index=False)
        state["status"] = "complete"
        state["rows"] = json.loads(result.to_json(orient="records"))
        result.attrs.update(
            comparison_report=str(report),
            candidate_batch_seconds=state["candidate_batch_seconds"],
            rasmap_restored=True,
        )
        return result
    except BaseException as exc:
        state["status"] = "aborted"
        state["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write()
