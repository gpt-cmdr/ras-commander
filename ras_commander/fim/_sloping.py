"""Explicit experimental sloping API adapter; no arithmetic fallback."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import _aoi, _engine, _horizontal, _products
from ._horizontal_engine import _read_f32, _write_array, _write_geometry
from ._sloping_inputs import write_binary_mesh_inputs
from .errors import FimEngineError


def _validate_options(
    render_mode, reduce_shallow_to_horizontal, use_depth_weighted_faces
):
    if render_mode not in ("sloping", "slopingPretty"):
        raise ValueError("render_mode must be 'sloping' or 'slopingPretty'")
    if not isinstance(reduce_shallow_to_horizontal, bool) or not isinstance(
        use_depth_weighted_faces, bool
    ):
        raise ValueError("sloping option flags must be booleans")
    if render_mode == "sloping" and (
        reduce_shallow_to_horizontal or use_depth_weighted_faces
    ):
        raise ValueError("shallow and depth-weighted controls require slopingPretty")
    selected_options = dict(
        render_mode=render_mode,
        reduce_shallow_to_horizontal=reduce_shallow_to_horizontal,
        use_depth_weighted_faces=use_depth_weighted_faces,
    )
    return selected_options


def _validate_selection(profiles):
    selected = {"Max": "Max"} if profiles is None else dict(profiles)
    if not selected or any(
        not isinstance(name, str)
        or not _engine._SAFE_ID.fullmatch(name)
        or name in (".", "..")
        for name in selected
    ):
        raise ValueError(
            "profiles must map safe output names to 'Max' or nonnegative timestep indices"
        )
    if len({name.casefold() for name in selected}) != len(selected):
        raise ValueError("profile names must be unique ignoring case")
    for value in selected.values():
        if value != "Max" and (
            isinstance(value, bool)
            or not isinstance(value, (int, np.integer))
            or value < 0
        ):
            raise ValueError(
                "profile selectors must be 'Max' or nonnegative timestep indices"
            )
    return selected


def _validate_method(method, render_mode, max_inflight_profiles):
    concurrency_supported = method.get("bounded_profile_concurrency") is True
    if max_inflight_profiles > 1 and not concurrency_supported:
        raise FimEngineError(
            "engine lacks bounded sloping profile concurrency; install engine 0.6 or newer"
        )
    if method.get("method_id") != "rasmapper-plain-sloping/1" or not method.get(
        "stream_outputs"
    ):
        raise FimEngineError(
            "engine lacks rasmapper-plain-sloping/1; install a matching engine"
        )
    if render_mode == "slopingPretty" and not method.get("enhanced_options"):
        raise FimEngineError(
            "engine lacks additional sloping options; install a matching engine"
        )
    if render_mode == "slopingPretty" and not method.get("native_donation_history"):
        raise FimEngineError("Cell-face sloping requires native donation history (engine 0.8+)")
    selected_method_id = (
        method.get("enhanced_method_id")
        if render_mode == "slopingPretty"
        else method["method_id"]
    )
    return concurrency_supported, selected_method_id


def _stage_profiles(
    hdf, root, meshes, max_values, selected, *, deduplicate=False, max_staged_bytes=None,
    chunk_bytes=8 * 1024 * 1024,
):
    """Stage selected numeric rows in bounded native-HDF spatial slabs."""
    import h5py
    from .. import HdfResultsMesh
    from ..fast_hdf import backend_scope, read_dataset
    from .errors import FimUnsupportedError
    from .RasFim import _file_identity

    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 4:
        raise ValueError("chunk_bytes must be an integer >= 4")
    before = _file_identity(hdf)
    staged_bytes = 0
    cached = {}
    units = []
    profile_views = {}
    for profile_index, (name, selector) in enumerate(selected.items()):
        if deduplicate and selector in cached:
            units.append(dict(id=name, values_files=list(cached[selector])))
            continue
        values_files = []
        for i, mesh in enumerate(meshes):
            size = mesh["cell_count"]
            if max_staged_bytes is not None and staged_bytes + size * 4 > max_staged_bytes:
                raise FimUnsupportedError("Prepared sloping inputs exceed max_prepared_mib")
            filename = f"values-{profile_index}-{i}.bin"
            destination = root / filename
            partial = destination.with_suffix(".partial")
            if selector == "Max":
                source = max_values[i]
                dataset_path = source["dataset"] if isinstance(source, dict) else None
                time_index = 0
            else:
                with backend_scope("rust"):
                    if i not in profile_views:
                        profile_views[i] = HdfResultsMesh.get_mesh_timeseries(
                            hdf,
                            mesh["mesh_name"],
                            "Water Surface",
                            truncate=False,
                            return_type="view",
                            include_ghost_cells=True,
                        )
                    view = profile_views[i].select(time=int(selector))
                    if view.shape != (1, size):
                        raise ValueError("Sloping profile source dimensions changed")
                    dataset_path = view.dataset_path
                    time_index = int(selector)
            try:
                with h5py.File(hdf, "r") as handle, partial.open("wb") as stream:
                    dataset = handle[dataset_path] if dataset_path is not None else None
                    if dataset is not None and (len(dataset.shape) != 2 or dataset.shape[1] != size):
                        raise ValueError("Sloping profile source dimensions changed")
                    source_itemsize = dataset.dtype.itemsize if dataset is not None else np.asarray(source).dtype.itemsize
                    chunk_cells = max(1, chunk_bytes // max(4, source_itemsize))
                    for start in range(0, size, chunk_cells):
                        stop = min(size, start + chunk_cells)
                        values = (
                            read_dataset(dataset, (slice(time_index, time_index + 1), slice(start, stop)), backend="rust")
                            if dataset is not None else source[start:stop]
                        )
                        array = np.asarray(values, dtype="<f4").reshape(-1)
                        if len(array) != stop - start or not np.isfinite(array).all():
                            raise ValueError(f"Invalid complete cell profile {name!r} for {mesh['mesh_name']!r}")
                        stream.write(memoryview(np.ascontiguousarray(array)).cast("B"))
                if _file_identity(hdf) != before:
                    raise FimEngineError("HDF source changed during chunked staging")
                partial.replace(destination)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            values_files.append(filename)
            staged_bytes += size * 4
        cached[selector] = values_files
        units.append(dict(id=name, values_files=values_files))
    return units, len(profile_views), staged_bytes


def map_profiles(
    hdf_path,
    terrain_path,
    output_folder,
    *,
    profiles=None,
    render_mode="sloping",
    reduce_shallow_to_horizontal=False,
    use_depth_weighted_faces=False,
    postprocessing_hdf=None,
    corner_elevation_source="auto",
    bbox=None,
    polygon=None,
    polygon_layer=None,
    aoi_crs=None,
    engine_path=None,
    threads=1,
    writer_threads=1,
    max_inflight_profiles=1,
    max_working_mib=1024,
    timeout=None,
    write_floodplain=False,
    template_raster=None,
    _prepared=None,
):
    from .. import HdfMesh, HdfResultsMesh
    from ..fast_hdf import backend_scope
    from .RasFim import (
        RasFim,
        MANIFEST_COLUMNS,
        _empty_row,
        _file_identity,
        _positive_int,
        _prepare_output_folder,
    )

    selected_options = _validate_options(
        render_mode, reduce_shallow_to_horizontal, use_depth_weighted_faces
    )
    started = time.perf_counter()
    preparation = {}
    phase = started
    threads = _positive_int(threads, "threads")
    writer_threads = _positive_int(writer_threads, "writer_threads")
    max_inflight_profiles = _positive_int(
        max_inflight_profiles, "max_inflight_profiles"
    )
    if max_inflight_profiles > 64:
        raise ValueError("max_inflight_profiles must be <= 64")
    if writer_threads > 64:
        raise ValueError("writer_threads must be <= 64")
    budget = _positive_int(max_working_mib, "max_working_mib")
    if threads > 64:
        raise ValueError("threads must be <= 64")
    if timeout is not None and (
        isinstance(timeout, bool) or not np.isfinite(timeout) or timeout <= 0
    ):
        raise ValueError("timeout must be positive and finite, or None")
    hdf = Path(hdf_path).resolve(strict=True)
    terrain = Path(terrain_path).resolve(strict=True)
    if _prepared is None:
        model_scope = RasFim.validate_2d_model(hdf)
    else:
        from copy import deepcopy

        model_scope = deepcopy(_prepared._model_scope)
    selected = _validate_selection(profiles)
    engine = (
        _engine.find_engine(engine_path) if _prepared is None else _prepared._engine
    )
    method = (
        _engine.engine_method(engine).get("sloping", {})
        if _prepared is None
        else _prepared._method
    )
    concurrency_supported, selected_method_id = _validate_method(
        method, render_mode, max_inflight_profiles
    )
    if use_depth_weighted_faces and not method.get("depth_weighted_faces"):
        raise FimEngineError("Depth weighting requires an engine advertising depth_weighted_faces (0.8+)")
    watched = {"hdf": hdf, "terrain": terrain, "engine": engine}
    if postprocessing_hdf is not None:
        watched["postprocessing_hdf"] = Path(postprocessing_hdf).resolve(strict=True)
        if (watched["postprocessing_hdf"].parent / "corner_elevation_receipt.json").exists():
            from ._corner_preparation import validate_receipt
            _, corner_sources = validate_receipt(hdf, watched["postprocessing_hdf"])
            watched.update(corner_sources)
    if _prepared is not None:
        watched.update(_prepared._watched)
    if template_raster is not None:
        template_raster = Path(template_raster).resolve(strict=True)
        watched["template_raster"] = template_raster
    if isinstance(polygon, (str, os.PathLike)):
        watched["polygon"] = Path(polygon).resolve(strict=True)
    before = {key: _file_identity(path) for key, path in watched.items()}
    preparation["preflight_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    if _prepared is None:
        with backend_scope("rust"):
            cells = HdfMesh.get_mesh_cell_polygons(
                hdf, strict=True, engine="native", threads=threads
            )
    else:
        cells = _prepared._cells
    preparation["cell_polygon_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    if cells.empty:
        raise ValueError("sloping mapping requires physical 2D cell polygons")
    constraint = _aoi.resolve_aoi(
        bbox=bbox,
        polygon=polygon,
        polygon_layer=polygon_layer,
        aoi_crs=aoi_crs,
        default_crs=cells.crs,
    )
    # Windowing selects output pixels; the complete mesh remains available for
    # face connectivity and corner reconstruction across an AOI boundary.
    plan = _horizontal.plan_grid(cells, terrain, constraint, budget, native=True)
    layout = None
    buffer_bytes = 0
    if template_raster is not None and all(plan.shape):
        from . import _sloping_products

        layout = _sloping_products.template_profile(template_raster, plan)
        buffer_bytes = layout["planned_buffer_bytes"]
        if plan.planned_bytes + buffer_bytes > budget * (1 << 20):
            from .errors import FimUnsupportedError

            raise FimUnsupportedError(
                "sloping template delivery exceeds planned array budget"
            )
    preparation["grid_plan_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    _horizontal.prepare_grid(
        cells, terrain, plan, False
    )  # validates polygons and overlap
    preparation["cell_validation_seconds"] = time.perf_counter() - phase
    folder = _prepare_output_folder(output_folder)
    rows = {name: _empty_row(name, "not_run") for name in selected}
    details = dict(
        method="RAS Mapper sloping / Rust",
        method_id=selected_method_id,
        backend="rust",
        model_scope=model_scope,
        mapping_scope="physical 2D cells only; standalone storage-area surfaces excluded",
        output_grid_reference=(
            str(template_raster) if template_raster is not None else "terrain window"
        ),
        status="in_progress",
        options={
            **selected_options,
            "extra_depth_cutoff": None,
            "threads": threads,
            "writer_threads": writer_threads,
            "max_inflight_profiles": max_inflight_profiles,
            "max_working_mib": budget,
            "write_floodplain": bool(write_floodplain),
        },
        source_profiles=selected,
        aoi=constraint.describe() if constraint else None,
        inputs={
            k: {"path": str(p), "size": before[k][0], "mtime_ns": before[k][1]}
            for k, p in watched.items()
        },
        qualification="experimental native 7.0.1; plain five-model physical-2D corpus (bounded eBFE); enhanced combinations on Bald Eagle bridges Max and Davis timesteps",
    )

    def manifest():
        frame = pd.DataFrame(list(rows.values()), columns=MANIFEST_COLUMNS)
        frame.attrs["performance"] = details.get("performance", {})
        frame.attrs["mapping_scope"] = details["mapping_scope"]
        frame.attrs["model_scope"] = model_scope
        return frame

    RasFim._write_manifest(folder, manifest(), details)
    try:
        if not all(plan.shape):
            rows = {
                name: _empty_row(name, "empty_aoi", crs=plan.crs.to_string())
                for name in selected
            }
        else:
            tick = time.perf_counter()
            identity = (
                _engine.terrain_identity(engine, terrain, cells.crs)
                if _prepared is None
                else _prepared._terrain_identity
            )
            with tempfile.TemporaryDirectory(
                prefix=".sloping-", dir=folder
            ) as temporary:
                root = Path(temporary)
                if _prepared is None:
                    mesh_files, meshes, max_values = write_binary_mesh_inputs(
                        hdf,
                        root,
                        threads=threads,
                        include_max="Max" in selected.values(),
                        include_vertex_elevations=use_depth_weighted_faces,
                        postprocessing_hdf=postprocessing_hdf,
                        corner_elevation_source=corner_elevation_source,
                    )
                else:
                    mesh_files, meshes = _prepared._mesh_files, _prepared._meshes
                details["corner_elevations"] = {
                    mesh["mesh_name"]: mesh["corner_elevations"]
                    for mesh in meshes if "corner_elevations" in mesh
                }
                lookup = {mesh["mesh_name"]: i for i, mesh in enumerate(meshes)}
                addresses = [
                    [lookup[row.mesh_name], int(row.cell_id)]
                    for row in cells.iloc[plan.cell_positions].itertuples()
                ]
                _write_geometry(
                    root / "cells.wkb",
                    cells.geometry.iloc[plan.cell_positions].to_numpy(),
                )
                fields = {}
                if plan.mask_geometry:
                    _write_geometry(root / "aoi.wkb", [plan.geometry])
                    fields["aoi_file"] = "aoi.wkb"
                if _prepared is None:
                    units, profile_view_count, _ = _stage_profiles(
                        hdf, root, meshes, max_values, selected
                    )
                else:
                    units = [_prepared._units[name] for name in selected]
                    profile_view_count = 0
                import rasterio

                if _prepared is None:
                    with rasterio.open(terrain) as src:
                        full_transform = list(src.transform.to_gdal())
                else:
                    full_transform = _prepared._terrain_transform
                request = dict(
                    schema="ras-commander-sloping-request/1",
                    **(
                        {"options": {key: value for key, value in selected_options.items()
                                     if key != "use_depth_weighted_faces" or method.get("depth_weighted_faces")}}
                        if method.get("enhanced_options")
                        else {}
                    ),
                    terrain=str(terrain),
                    epsg=identity["epsg"],
                    crs_identity=identity["crs_identity"],
                    terrain_transform=full_transform,
                    window=[int(v) for v in plan.window.flatten()],
                    geometry_file="cells.wkb",
                    mesh_files=mesh_files,
                    owner_cells=addresses,
                    profiles=units,
                    threads=threads,
                    max_working_bytes=budget * (1 << 20) - buffer_bytes,
                    stream_outputs=True,
                    **fields,
                )
                if concurrency_supported:
                    request["max_inflight_profiles"] = max_inflight_profiles
                (root / "request.json").write_text(
                    json.dumps(request), encoding="utf-8"
                )
                from importlib.metadata import PackageNotFoundError, version

                try:
                    hdf_version = version("ras-commander-fast-hdf")
                except PackageNotFoundError:
                    hdf_version = None
                details["performance"] = {
                    "corner_elevations": details.get("corner_elevations", {}),
                    "native_hdf": {
                        "package": "ras-commander-fast-hdf",
                        "version": hdf_version,
                        "numeric_payload_backend": "rust-required",
                    },
                    "preparation": preparation,
                    "profile_views_prepared": profile_view_count,
                    "hdf_and_staging_seconds": time.perf_counter() - tick,
                    "product_write_seconds": {},
                }
                if _prepared is not None:
                    details["performance"]["prepared_context"] = _prepared.info
                tick = time.perf_counter()
                expired = threading.Event()
                persistent = _prepared is not None and _prepared._reuse_native
                if persistent and _prepared._native_session is None:
                    from ._native_session import NativeSlopingSession
                    _prepared._native_session = NativeSlopingSession(engine)
                from contextlib import nullcontext
                # Delete-on-close stderr avoids a Windows cleanup race when a
                # terminated child briefly retains its inherited file handle.
                with (nullcontext(_prepared._native_session.errors) if persistent else tempfile.TemporaryFile(mode="w+b")) as errors:
                    errors.seek(0)
                    errors.truncate()
                    process = (_prepared._native_session.submit(root / "request.json", root / "out") if persistent else subprocess.Popen(
                        [
                            str(engine),
                            "sloping",
                            str(root / "request.json"),
                            str(root / "out"),
                        ],
                        stdout=subprocess.PIPE,
                        stderr=errors,
                    ))

                    def expire():
                        if process.poll() is None:
                            expired.set()
                            process.kill()

                    timer = (
                        threading.Timer(float(timeout), expire)
                        if timeout is not None
                        else None
                    )
                    if timer:
                        timer.daemon = True
                        timer.start()
                    try:
                        for name in selected:
                            header = process.stdout.readline(65537)
                            if len(header) > 65536 or not header.endswith(b"\n"):
                                raise FimEngineError(
                                    "Missing or invalid sloping stream header"
                                )
                            try:
                                unit = json.loads(header)
                            except (ValueError, UnicodeError) as exc:
                                raise FimEngineError(
                                    "Invalid sloping stream header JSON"
                                ) from exc
                            if (
                                not isinstance(unit, dict)
                                or unit.get("id") != name
                                or unit.get("status") != "complete"
                                or unit.get("pixels") != int(np.prod(plan.shape))
                            ):
                                raise FimEngineError(
                                    "Sloping stream profile or dimensions mismatch"
                                )
                            depth = _read_f32(
                                process.stdout, plan.shape, expired, timeout, "depth"
                            )
                            wse = _read_f32(
                                process.stdout, plan.shape, expired, timeout, "wse"
                            )
                            result = SimpleNamespace(
                                profile=name,
                                depth=depth,
                                wse=wse,
                                transform=plan.transform,
                                unit={"window": list(plan.window.flatten())},
                            )
                            write_tick = time.perf_counter()
                            with rasterio.Env(GDAL_NUM_THREADS=str(writer_threads)):
                                if layout is None:
                                    products = RasFim._write_products(
                                        folder, result, plan.crs, write_floodplain
                                    )
                                else:
                                    products = _sloping_products.write_products(
                                        folder,
                                        result,
                                        plan.crs,
                                        write_floodplain,
                                        layout,
                                    )
                            rows[name].update(products)
                            details["performance"]["product_write_seconds"][name] = (
                                time.perf_counter() - write_tick
                            )
                            del depth, wse, result
                        if persistent:
                            terminal = process.stdout.readline(65537)
                            if len(terminal) > 65536 or not terminal.endswith(b"\n") or json.loads(terminal) != {"command_status": "complete"}:
                                raise FimEngineError("Invalid native session completion frame")
                            if process.poll() is not None:
                                raise FimEngineError("Native session exited unexpectedly")
                            code = 0
                        else:
                            if process.stdout.read(1):
                                raise FimEngineError("Unexpected trailing sloping stream bytes")
                            code = process.wait()
                        if expired.is_set():
                            raise FimEngineError(
                                f"Sloping engine timed out after {timeout} seconds"
                            )
                        try:
                            report = json.loads(
                                (root / "out/report.json").read_text(encoding="utf-8")
                            )
                        except (OSError, ValueError, UnicodeError) as exc:
                            raise FimEngineError(
                                "Missing or invalid sloping engine report"
                            ) from exc
                        expected = list(selected)
                        units = (
                            report.get("profiles") if isinstance(report, dict) else None
                        )
                        if not isinstance(units, list) or any(
                            not isinstance(p, dict) for p in units
                        ):
                            raise FimEngineError("Invalid sloping report profile table")
                        reported_method = report.get("method")
                        if concurrency_supported:
                            effective = report.get("effective_inflight_profiles")
                            if (
                                type(report.get("requested_inflight_profiles"))
                                is not int
                                or report.get("requested_inflight_profiles")
                                != max_inflight_profiles
                                or isinstance(effective, bool)
                                or not isinstance(effective, int)
                                or not 1
                                <= effective
                                <= min(max_inflight_profiles, threads, len(selected))
                                or report.get("threads") != threads
                                or type(report.get("planned_bytes")) is not int
                                or not 0
                                < report["planned_bytes"]
                                <= request["max_working_bytes"]
                            ):
                                raise FimEngineError(
                                    "Invalid sloping concurrency report"
                                )
                        if (
                            code != 0
                            or report.get("status") != "complete"
                            or not isinstance(reported_method, dict)
                            or reported_method.get("method_id") != selected_method_id
                            or reported_method.get("options")
                            != {
                                "CellRenderMode": "Sloping",
                                "CellStencilMode": (
                                    "WithFaces"
                                    if render_mode == "slopingPretty"
                                    else "JustFacepoints"
                                ),
                                "FacepointAdjustmentMode": "None",
                                "ShallowBehaviorMode": (
                                    "ReduceToHorizontal"
                                    if reduce_shallow_to_horizontal
                                    else "None"
                                ),
                                "UseDepthWeightedFaces": use_depth_weighted_faces,
                                "FaceWSMode": "Adjusted",
                            }
                            or [p.get("id") for p in units] != expected
                            or any(p.get("status") != "complete" for p in units)
                        ):
                            raise FimEngineError(
                                f"Sloping engine failed with exit {code}: {report.get('error', 'invalid report')}"
                            )
                        details["performance"]["engine_report"] = report
                        if _prepared is not None:
                            _prepared._info["native_state_reused"] = bool(report.get("session", {}).get("geometry_reused"))
                            details["performance"]["prepared_context"] = _prepared.info
                    except BaseException:
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        errors.seek(0)
                        details["engine_stderr"] = errors.read().decode(
                            "utf-8", errors="replace"
                        )[-4000:]
                        raise
                    finally:
                        if timer:
                            timer.cancel()
                        if not persistent:
                            process.stdout.close()
                        elif process.poll() is not None:
                            _prepared._native_session.close()
                            _prepared._native_session = None
                details["performance"]["engine_and_delivery_seconds"] = (
                    time.perf_counter() - tick
                )
        if _prepared is not None:
            _prepared._check_sources()
        if postprocessing_hdf is not None and (Path(postprocessing_hdf).parent / "corner_elevation_receipt.json").exists():
            from ._corner_preparation import validate_receipt
            validate_receipt(hdf, postprocessing_hdf)
        changed = [
            key for key, path in watched.items() if _file_identity(path) != before[key]
        ]
        if changed:
            raise FimEngineError(f"Inputs changed during sloping mapping: {changed}")
        details["status"] = "complete"
    except BaseException as exc:
        details["status"] = "aborted"
        for name in selected:
            for product in _products.product_paths(folder, name):
                product.unlink(missing_ok=True)
            rows[name] = _empty_row(
                name, "failed", error=f"{type(exc).__name__}: {exc}"
            )
        raise
    finally:
        details.setdefault("performance", {})["total_seconds"] = (
            time.perf_counter() - started
        )
        RasFim._write_manifest(folder, manifest(), details)
    return manifest()
