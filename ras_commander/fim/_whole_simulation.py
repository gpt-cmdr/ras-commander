"""Whole-simulation products through the engine's ``whole-simulation`` command.

Method ``native-whole-simulation-horizontal/1``: every stored output time is
rendered with the horizontal cell-constant method over the physical 2D cells
and accumulated per pixel. A pixel is wet at an output time when its rendered
depth is strictly greater than ``threshold`` and its cell passes the
thresholded cell gate ``wse > cell minimum elevation + threshold`` (float32).

- ``arrival_time``: first wet output time, in hours since the plan's
  simulation start (float32).
- ``percent_inundated``: ``100 * wet output times / all output times``.
- ``duration`` (opt-in, unqualified): hours from arrival to the first dry
  output time after the last wet one, or to the last wet time when that dry
  time is the final output or there is none.

Pixels that are never wet are NaN. Python stages the cell polygons, the cell
minimum elevations and one WSE vector per stored output time; it performs no
mapping arithmetic.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import _engine, _horizontal, _products
from ._horizontal_engine import _write_array, _write_geometry
from .errors import FimEngineError, FimUnsupportedError

METHOD_ID = "native-whole-simulation-horizontal/1"
REQUEST_SCHEMA = "ras-commander-whole-simulation-request/1"
REPORT_SCHEMA = "ras-commander-whole-simulation-report/1"
PRODUCTS = ("arrival_time", "duration", "percent_inundated")
QUALIFIED_PRODUCTS = ("arrival_time", "percent_inundated")
DEFAULT_PRODUCTS = ("arrival_time", "percent_inundated")
UNITS = {"arrival_time": "hours", "duration": "hours", "percent_inundated": "percent"}
MANIFEST_COLUMNS = [
    "product",
    "status",
    "tif",
    "units",
    "threshold",
    "output_times",
    "wet_pixels",
    "qualified",
    "col_off",
    "row_off",
    "width",
    "height",
    "transform",
    "crs",
    "error",
]


def _validate(products, threshold, allow_unqualified):
    if isinstance(products, str):
        raise ValueError("products must be a sequence of product names")
    products = tuple(products)
    if (
        not products
        or len(set(products)) != len(products)
        or any(product not in PRODUCTS for product in products)
    ):
        raise ValueError(f"products must be unique names from {PRODUCTS}")
    if not isinstance(allow_unqualified, bool):
        raise ValueError("allow_unqualified must be a boolean")
    if "duration" in products and not allow_unqualified:
        raise FimUnsupportedError(
            "duration is not qualified against RAS Mapper (some recession pixels end one output "
            "interval later than native); pass allow_unqualified=True to deliver it"
        )
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float, np.integer, np.floating))
        or not np.isfinite(threshold)
        or threshold < 0
        or threshold > np.finfo(np.float32).max
    ):
        raise ValueError("threshold must be finite and >= 0 in model vertical units")
    return products, float(threshold)


def _require_methods(method):
    whole = method.get("whole_simulation")
    if not isinstance(whole, dict) or whole.get("method_id") != METHOD_ID:
        raise FimUnsupportedError(
            f"engine lacks {METHOD_ID}; install ras-commander-fast-map with whole-simulation support"
        )
    horizontal = method.get("horizontal")
    if (
        not isinstance(horizontal, dict)
        or horizontal.get("method_id") != "horizontal-cell-constant/2"
        or horizontal.get("native_ownership") is not True
    ):
        raise FimUnsupportedError("engine lacks native horizontal-cell-constant/2 ownership")
    return whole, horizontal


def output_hours(hdf):
    """Stored output times in hours since the simulation start, and their stamps."""
    from ..hdf.HdfBase import HdfBase

    start = HdfBase.get_simulation_start_time(hdf)
    stamps = HdfBase.get_unsteady_timestamps(hdf)
    hours = [(stamp - start).total_seconds() / 3600.0 for stamp in stamps]
    if not hours or any(b <= a for a, b in zip(hours, hours[1:])):
        raise FimUnsupportedError("stored output times must exist and strictly increase")
    return hours, start, stamps


def map_whole_simulation(
    hdf_path,
    terrain_path,
    output_folder,
    *,
    products=DEFAULT_PRODUCTS,
    threshold,
    allow_unqualified=False,
    terrain_hdf=None,
    threads=1,
    writer_threads=1,
    max_working_mib=1024,
    timeout=None,
    engine_path=None,
    invalid_cells="repair",
):
    from .. import HdfMesh, HdfResultsMesh
    from ..fast_hdf import backend_scope, read_datasets
    from .RasFim import RasFim, _file_identity, _positive_int, _prepare_output_folder

    from . import _invalid_cells

    started = time.perf_counter()
    _invalid_cells.validate_policy(invalid_cells)
    products, threshold = _validate(products, threshold, allow_unqualified)
    threads = _positive_int(threads, "threads")
    writer_threads = _positive_int(writer_threads, "writer_threads")
    if threads > 64 or writer_threads > 64:
        raise ValueError("threads and writer_threads must be <= 64")
    budget = _positive_int(max_working_mib, "max_working_mib")
    if timeout is not None and (
        isinstance(timeout, bool) or not np.isfinite(timeout) or timeout <= 0
    ):
        raise ValueError("timeout must be positive and finite, or None")
    hdf = Path(hdf_path).resolve(strict=True)
    terrain = Path(terrain_path).resolve(strict=True)
    model_scope = RasFim.validate_2d_model(hdf)
    if model_scope.get("storage_areas"):
        raise FimUnsupportedError(
            "whole-simulation products render physical 2D cells only; plans with storage areas "
            f"({model_scope['storage_areas']} found) are refused. Use RAS Mapper for these plans"
        )
    scope_info = None
    if terrain_hdf is not None:
        from . import _terrain_scope

        scope_info = _terrain_scope.resolve(terrain_hdf, terrain)
    engine = _engine.find_engine(engine_path)
    method = _engine.engine_method(engine)
    whole_method, horizontal_method = _require_methods(method)
    if scope_info is not None:
        _terrain_scope.require_engine(horizontal_method, "horizontal")
    watched = {"hdf": hdf, "terrain": terrain, "engine": engine}
    if scope_info is not None:
        watched["terrain_hdf"] = scope_info["terrain_hdf"]
    before = {key: _file_identity(path) for key, path in watched.items()}
    hours, start, stamps = output_hours(hdf)
    timings = {}
    tick = time.perf_counter()
    def strict_cells():
        with backend_scope("rust"):
            return HdfMesh.get_mesh_cell_polygons(hdf, strict=True, engine="native", threads=threads)

    cells, invalid_records = _invalid_cells.load_plan_cells(
        hdf, policy=invalid_cells, threads=threads, strict_loader=strict_cells)
    if cells.empty and not invalid_records:
        raise FimUnsupportedError("whole-simulation mapping requires physical 2D cell polygons")
    _invalid_cells.require_cells(cells, invalid_records, invalid_cells, "whole-simulation mapping")
    # No AOI: "raise" refuses any affected cell.
    _invalid_cells.check_scope(invalid_records, invalid_cells, None)
    plan = _horizontal.plan_grid(cells, terrain, None, budget, native=True)
    _horizontal.prepare_grid(cells, terrain, plan, False)  # validates polygons and overlap
    timings["cell_and_grid_seconds"] = time.perf_counter() - tick
    folder = _prepare_output_folder(output_folder)
    crs = plan.crs.to_string()
    rows = {
        product: {name: None for name in MANIFEST_COLUMNS} | {
            "product": product, "status": "not_run", "units": UNITS[product],
            "threshold": threshold, "output_times": len(hours),
            "qualified": product in QUALIFIED_PRODUCTS,
        }
        for product in products
    }
    details = {
        "method": "RAS Mapper whole-simulation products / Rust horizontal",
        "method_id": METHOD_ID,
        "backend": "rust",
        "model_scope": model_scope,
        "mapping_scope": "physical 2D cells only; plans with storage areas are refused",
        "options": {
            "products": list(products),
            "threshold": threshold,
            "allow_unqualified": allow_unqualified,
            "threads": threads,
            "writer_threads": writer_threads,
            "max_working_mib": budget,
        },
        "time_reference": {
            "simulation_start": start.isoformat(),
            "first_output": stamps[0].isoformat(),
            "last_output": stamps[-1].isoformat(),
            "units": "hours since simulation start",
        },
        "inputs": {
            key: {"path": str(path), "size": before[key][0], "mtime_ns": before[key][1]}
            for key, path in watched.items()
        },
        "engine": {"path": str(engine), "method": whole_method},
        "status": "in_progress",
        "invalid_cells": _invalid_cells.describe(invalid_records, invalid_cells, None),
    }
    if scope_info is not None:
        details["terrain_scope"] = _terrain_scope.describe(scope_info)

    def manifest():
        frame = pd.DataFrame([rows[product] for product in products], columns=MANIFEST_COLUMNS)
        frame.attrs["performance"] = details.get("performance", {})
        frame.attrs["method_id"] = METHOD_ID
        frame.attrs["model_scope"] = model_scope
        frame.attrs["time_reference"] = details["time_reference"]
        frame.attrs["invalid_cells"] = details["invalid_cells"]
        for key in ("terrain_scope", "unqualified"):
            if key in details:
                frame.attrs[key] = details[key]
        return frame

    RasFim._write_manifest(folder, manifest(), details)
    try:
        if not all(plan.shape):
            for product in products:
                rows[product].update(status="empty_aoi", crs=crs)
        else:
            _run(
                engine, hdf, terrain, cells, plan, hours, products, threshold,
                allow_unqualified, scope_info, threads, writer_threads, budget,
                timeout, folder, rows, details, timings, crs,
                HdfResultsMesh, backend_scope, read_datasets,
            )
        changed = [key for key, path in watched.items() if _file_identity(path) != before[key]]
        if changed:
            raise FimEngineError(f"Inputs changed during whole-simulation mapping: {changed}")
        details["status"] = "complete"
    except BaseException as exc:
        details["status"] = "aborted"
        for product in products:
            (folder / f"{product}.tif").unlink(missing_ok=True)
            rows[product].update(status="failed", tif=None, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        timings["total_seconds"] = time.perf_counter() - started
        details["performance"] = {**details.get("performance", {}), **timings}
        RasFim._write_manifest(folder, manifest(), details)
    return manifest()


def _run(
    engine, hdf, terrain, cells, plan, hours, products, threshold, allow_unqualified,
    scope_info, threads, writer_threads, budget, timeout, folder, rows, details, timings,
    crs, HdfResultsMesh, backend_scope, read_datasets,
):
    import h5py
    import rasterio

    selected = cells.iloc[plan.cell_positions]
    count = len(selected)
    required = count * 4 * (len(hours) + 1) + (64 << 20)
    if shutil.disk_usage(folder).free < required:
        raise FimEngineError(
            f"whole-simulation staging needs at least {required} free bytes on the output volume"
        )
    identity = _engine.terrain_identity(engine, terrain, cells.crs)
    with tempfile.TemporaryDirectory(prefix=".whole-simulation-", dir=folder) as temporary:
        root = Path(temporary)
        tick = time.perf_counter()
        _write_geometry(root / "cells.wkb", selected.geometry.to_numpy())
        mesh_names = list(dict.fromkeys(selected["mesh_name"]))
        positions = {
            name: np.flatnonzero(selected["mesh_name"].to_numpy() == name) for name in mesh_names
        }
        cell_ids = {
            name: selected["cell_id"].to_numpy(dtype=np.int64)[positions[name]] for name in mesh_names
        }
        minimum = np.empty(count, dtype="<f4")
        with h5py.File(hdf, "r") as source:
            paths = [f"Geometry/2D Flow Areas/{name}/Cells Minimum Elevation" for name in mesh_names]
            arrays = read_datasets(source, paths, backend="rust", threads=threads)
            for name in mesh_names:
                series = source.get(
                    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
                    f"2D Flow Areas/{name}/Water Surface"
                )
                if series is None or series.ndim != 2 or series.shape[0] != len(hours):
                    raise FimUnsupportedError(
                        f"Water Surface series of mesh {name!r} does not match the {len(hours)} output times"
                    )
        for name, path in zip(mesh_names, paths):
            values = np.asarray(arrays[path], dtype=np.float32).reshape(-1)
            ids = cell_ids[name]
            if ids.min(initial=0) < 0 or ids.max(initial=-1) >= len(values):
                raise ValueError(f"cell ids exceed Cells Minimum Elevation for mesh {name!r}")
            minimum[positions[name]] = values[ids]
        if not np.isfinite(minimum).all():
            raise FimUnsupportedError("cell minimum elevations must be finite")
        _write_array(root / "cell_minimum.bin", minimum)
        (root / "wse").mkdir()
        views = {}
        with backend_scope("rust"):
            for name in mesh_names:
                views[name] = HdfResultsMesh.get_mesh_timeseries(
                    hdf, name, "Water Surface", truncate=False, return_type="view",
                    include_ghost_cells=True,
                )
            profiles = []
            vector = np.empty(count, dtype="<f4")
            for k in range(len(hours)):
                for name in mesh_names:
                    values = views[name].select(time=k).to_numpy(dtype=np.float32).reshape(-1)
                    ids = cell_ids[name]
                    if ids.max(initial=-1) >= len(values):
                        raise ValueError(f"Water Surface at output {k} is shorter than mesh {name!r}")
                    vector[positions[name]] = values[ids]
                if not np.isfinite(vector).all():
                    raise ValueError(f"Water Surface at output {k} contains non-finite values")
                filename = f"wse/t{k}.bin"
                _write_array(root / filename, vector)
                profiles.append({"id": f"t{k}", "values_file": filename})
        with rasterio.open(terrain) as src:
            full_transform = list(src.transform.to_gdal())
        horizontal = {
            "schema": "ras2fim-horizontal-request/1",
            "terrain": str(terrain),
            "epsg": identity["epsg"],
            "crs_identity": identity["crs_identity"],
            "terrain_transform": full_transform,
            "window": [int(v) for v in plan.window.flatten()],
            "geometry_file": "cells.wkb",
            "cell_count": count,
            "profiles": profiles,
            "min_depth": 0.0,
            "threads": threads,
            "max_working_bytes": budget * (1 << 20),
            "stream_outputs": False,
        }
        if scope_info is not None:
            from . import _terrain_scope

            horizontal["terrain_scope"] = _terrain_scope.stage(scope_info, root)
        request = {
            "schema": REQUEST_SCHEMA,
            "horizontal": horizontal,
            "times_hours": hours,
            "threshold": threshold,
            "cell_minimum_file": "cell_minimum.bin",
            "products": list(products),
            "allow_unqualified": allow_unqualified,
        }
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        timings["hdf_and_staging_seconds"] = time.perf_counter() - tick
        tick = time.perf_counter()
        proc = _engine.run_engine(
            [str(engine), "whole-simulation", str(root / "request.json"), str(root / "out")],
            "whole-simulation",
            timeout,
        )
        timings["engine_seconds"] = time.perf_counter() - tick
        stderr = (proc.stderr or "")[-4000:]
        report_path = root / "out" / "report.json"
        report = None
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise FimEngineError("invalid whole-simulation engine report") from exc
        if proc.returncode != 0 or not isinstance(report, dict) or report.get("status") != "complete":
            refusal = _engine.engine_refusal(
                report.get("error") if isinstance(report, dict) else None, stderr
            )
            if isinstance(report, dict):
                details["engine_report"] = report
                ws = report.get("whole_simulation")
                if isinstance(ws, dict) and "unqualified" in ws:
                    details["unqualified"] = ws["unqualified"]
            if refusal is not None:
                raise refusal
            raise FimEngineError(
                f"whole-simulation engine failed with exit {proc.returncode}: "
                f"{(report or {}).get('error') if isinstance(report, dict) else ''} {stderr}".strip()
            )
        details["engine_report"] = report
        ws = report.get("whole_simulation")
        if (
            report.get("schema") != REPORT_SCHEMA
            or not isinstance(ws, dict)
            or ws.get("status") != "complete"
            or not isinstance(ws.get("method"), dict)
            or ws["method"].get("method_id") != METHOD_ID
            or sorted(ws.get("products") or []) != sorted(products)
            or ws.get("times") != len(hours)
            or report.get("window") not in (None, horizontal["window"])
        ):
            raise FimEngineError("inconsistent whole-simulation engine report")
        details["unqualified"] = ws.get("unqualified")
        wet_pixels = ws.get("wet_pixels")
        tick = time.perf_counter()
        shape = plan.shape
        for product in products:
            path = root / "out" / "whole_simulation" / f"{product}.bin"
            if not path.is_file() or path.stat().st_size != int(np.prod(shape)) * 4:
                raise FimEngineError(f"whole-simulation product {product} is missing or truncated")
            values = np.fromfile(path, dtype="<f4").reshape(shape)
            target = folder / f"{product}.tif"
            with rasterio.Env(GDAL_NUM_THREADS=str(writer_threads)):
                _products.write_raster(target, values, plan.transform, plan.crs)
            rows[product].update(
                status="complete",
                tif=str(target),
                wet_pixels=wet_pixels,
                width=int(shape[1]),
                height=int(shape[0]),
                transform=tuple(float(v) for v in tuple(plan.transform)[:6]),
                crs=crs,
                error=None,
            )
            window = [int(v) for v in plan.window.flatten()]
            rows[product].update(col_off=window[0], row_off=window[1])
            del values
        timings["product_write_seconds"] = time.perf_counter() - tick
