"""Explicit Rust horizontal batch adapter; no numerical fallback."""

from contextlib import contextmanager
import json
import struct
from pathlib import Path
import tempfile
import shutil
import subprocess
import threading
import time
import numpy as np
from . import _engine
from .errors import FimEngineError, FimUnsupportedError


def _write_array(path, array):
    """Stage contiguous little-endian bytes with bounded operating-system writes."""
    view = memoryview(array).cast("B")
    with path.open("wb") as destination:
        for start in range(0, len(view), 1 << 20):
            chunk = view[start : start + (1 << 20)]
            if destination.write(chunk) != len(chunk):
                raise FimEngineError("short horizontal staging write")


def _write_geometry(path, geometries):
    """Write ordered, length-framed 2D WKB without Python coordinate dictionaries."""
    import shapely

    with path.open("wb") as destination:
        for start in range(0, len(geometries), 4096):
            chunk = shapely.to_wkb(
                geometries[start : start + 4096],
                output_dimension=2,
                byte_order=1,
                include_srid=False,
            )
            for value in chunk:
                destination.write(struct.pack("<I", len(value)))
                destination.write(value)


def _read_f32(stream, shape, expired, timeout, product):
    """Fill one array with bounded reads, preserving partial reads and float bits."""
    array = np.empty(shape, dtype="<f4")
    view = memoryview(array).cast("B")
    position = 0
    while position < len(view):
        size = stream.readinto(view[position : position + (1 << 20)])
        if not size:
            if expired.is_set():
                raise FimEngineError(f"horizontal engine timed out after {timeout} seconds")
            raise FimEngineError(f"truncated horizontal {product} stream")
        position += size
    array.setflags(write=False)
    return array


@contextmanager
def run_batch(
    engine,
    terrain,
    grid,
    ordered,
    names,
    min_depth,
    threads,
    budget,
    details,
    scratch_folder,
    timeout,
    terrain_scope=None,
):
    """Stage shared ownership once, run all profiles, validate every committed unit."""
    method = _engine.engine_method(engine).get("horizontal")
    if terrain_scope is not None:
        from . import _terrain_scope

        _terrain_scope.require_engine(method, "horizontal")
    if (
        not isinstance(method, dict)
        or method.get("method_id") != "horizontal-cell-constant/2"
        or method.get("stream_outputs") is not True
    ):
        raise FimEngineError(
            "engine does not support horizontal-cell-constant/2; install the matching wheel"
        )
    if grid.owner is None and method.get("native_ownership") is not True:
        raise FimEngineError(
            "engine lacks native terrio ownership; install ras-commander-fast-map 0.8 or newer"
        )
    if grid.plan.mask_geometry and method.get("aoi_mask") != "global-terrain-lattice/1":
        raise FimEngineError("Polygon masking requires Fast-Map global-terrain-lattice/1 (0.10.1+)")
    if grid.plan.geometry is not None:
        details["aoi_mask"] = "global-terrain-lattice/1"
    identity = _engine.terrain_identity(engine, terrain, ordered.crs)
    details["engine"] = {"path": str(engine), "method": method}
    pixels = int(np.prod(grid.plan.shape))
    required = (
        (grid.plan.geometry_bytes if grid.owner is None else pixels * 4)
        + len(grid.plan.cell_positions) * 4 * len(names)
        + (64 << 20)
    )
    if shutil.disk_usage(scratch_folder).free < required:
        raise FimEngineError(
            f"horizontal staging needs at least {required} free bytes on the output volume"
        )
    with tempfile.TemporaryDirectory(prefix=".horizontal-", dir=scratch_folder) as tmp:
        root = Path(tmp)
        staging_started = time.perf_counter()
        geometry_fields = {}
        if grid.owner is None:
            _write_geometry(
                root / "cells.wkb",
                ordered.geometry.iloc[grid.plan.cell_positions].to_numpy(),
            )
            geometry_fields["geometry_file"] = "cells.wkb"
            if grid.plan.mask_geometry:
                _write_geometry(root / "aoi.wkb", [grid.plan.geometry])
                geometry_fields["aoi_file"] = "aoi.wkb"
        else:
            owner = grid.owner.astype("<i4", copy=False).view("<u4")
            _write_array(root / "owner.bin", owner)
            geometry_fields["owner_file"] = "owner.bin"
            del owner
        details.setdefault("timings", {})[
            "geometry_staging_seconds" if grid.owner is None else "owner_staging_seconds"
        ] = (time.perf_counter() - staging_started)
        profiles = []
        failures = {}
        for i, name in enumerate(names):
            try:
                values = (
                    ordered[name]
                    .iloc[grid.plan.cell_positions]
                    .to_numpy(dtype=np.float64, na_value=np.nan)
                )
                if (
                    np.isinf(values).any()
                    or (np.abs(values[np.isfinite(values)]) > np.finfo(np.float32).max).any()
                ):
                    raise FimUnsupportedError(
                        "horizontal WSE must be finite float32-range values or NaN"
                    )
                _write_array(root / f"values-{i}.bin", values.astype("<f4"))
                profiles.append({"id": name, "values_file": f"values-{i}.bin"})
            except Exception as exc:
                failures[name] = f"{type(exc).__name__}: {exc}"
        if not profiles:
            yield lambda name: {"status": "failed", "error": failures[name]}
            return
        request = {
            "schema": "ras2fim-horizontal-request/1",
            "terrain": str(terrain),
            "epsg": identity["epsg"],
            "crs_identity": identity["crs_identity"],
            "terrain_transform": list(grid.plan.transform.to_gdal()),
            "window": [int(v) for v in grid.plan.window.flatten()],
            **geometry_fields,
            "cell_count": len(grid.plan.cell_positions),
            "profiles": profiles,
            "min_depth": float(min_depth),
            "threads": threads,
            "max_working_bytes": budget * (1 << 20),
            "stream_outputs": True,
        }
        if terrain_scope is not None:
            from . import _terrain_scope

            request["terrain_scope"] = _terrain_scope.stage(terrain_scope, root)
        # Transform above belongs to the window; terrain identity is its full source transform.
        import rasterio

        with rasterio.open(terrain) as src:
            request["terrain_transform"] = list(src.transform.to_gdal())
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        timings = details.setdefault("timings", {})
        timings["engine_staging_seconds"] = time.perf_counter() - staging_started
        timings["stream_read_seconds"] = {}
        expected_names = [p["id"] for p in profiles]
        received = []
        received_statuses = {}
        with (root / "stderr.txt").open("w+b") as errors:
            proc = subprocess.Popen(
                [
                    str(engine),
                    "horizontal",
                    str(root / "request.json"),
                    str(root / "out"),
                ],
                stdout=subprocess.PIPE,
                stderr=errors,
            )
            expired = threading.Event()

            def stop_expired():
                if proc.poll() is None:
                    try:
                        expired.set()
                        proc.kill()
                    except OSError:
                        pass

            timer = threading.Timer(float(timeout), stop_expired) if timeout is not None else None
            if timer is not None:
                timer.daemon = True
                timer.start()

            def finish_report():
                code = proc.wait()
                if expired.is_set():
                    raise FimEngineError(f"horizontal engine timed out after {timeout} seconds")
                path = root / "out/report.json"
                errors.seek(0)
                diagnostic = errors.read().decode("utf-8", errors="replace")[-4000:]
                if not path.is_file():
                    refusal = _engine.engine_refusal(diagnostic)
                    if refusal is not None:
                        raise refusal
                    raise FimEngineError(f"horizontal engine exit {code}: {diagnostic}")
                report = json.loads(path.read_text(encoding="utf-8"))
                details["engine_report"] = report
                if report.get("status") == "aborted":
                    refusal = _engine.engine_refusal(report.get("error"))
                    if refusal is not None:
                        raise refusal
                    raise FimEngineError(
                        f"horizontal session aborted: {report.get('error', diagnostic)}"
                    )
                units = report.get("profiles", [])
                if (
                    code not in (0, 2)
                    or report.get("schema") != "ras2fim-horizontal-report/1"
                    or report.get("status") not in ("complete", "failed")
                    or report.get("window") != request["window"]
                    or report.get("method", {}).get("method_id") != "horizontal-cell-constant/2"
                    or [u.get("id") for u in units] != expected_names
                    or received != expected_names
                    or any(received_statuses.get(u.get("id")) != u.get("status") for u in units)
                    or any(u.get("status") not in ("complete", "failed") for u in units)
                    or (code == 0) != (report["status"] == "complete")
                    or (report["status"] == "complete")
                    != all(u["status"] == "complete" for u in units)
                ):
                    raise FimEngineError(
                        f"inconsistent horizontal engine report (exit {code}): {diagnostic}"
                    )
                for unit in units:
                    committed = json.loads(
                        (root / "out" / unit["id"] / "unit.json").read_text(encoding="utf-8")
                    )
                    if committed != unit:
                        raise FimEngineError("horizontal unit differs from session report")

            def next_result(name):
                if name in failures:
                    return {"status": "failed", "error": failures[name]}
                read_started = time.perf_counter()
                line = proc.stdout.readline(16385)
                if not line or not line.endswith(b"\n") or len(line) > 16384:
                    if expired.is_set():
                        raise FimEngineError(f"horizontal engine timed out after {timeout} seconds")
                    # EOF reports the actual engine error instead of a false empty product.
                    if not line:
                        finish_report()
                    raise FimEngineError("invalid/truncated horizontal stream header")
                try:
                    header = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise FimEngineError("invalid horizontal stream JSON") from exc
                if not isinstance(header, dict):
                    raise FimEngineError("horizontal stream header is not an object")
                if header.get("id") != name or header.get("status") not in (
                    "complete",
                    "failed",
                ):
                    raise FimEngineError("horizontal stream profile/order mismatch")
                received.append(name)
                received_statuses[name] = header["status"]
                if header["status"] == "failed":
                    return header
                if header.get("pixels") != pixels:
                    raise FimEngineError("horizontal stream pixel count mismatch")
                result = {"status": "complete"}
                for product in ("depth", "wse"):
                    result[product] = _read_f32(
                        proc.stdout, grid.plan.shape, expired, timeout, product
                    )
                timings["stream_read_seconds"][name] = time.perf_counter() - read_started
                return result

            try:
                yield next_result
                if proc.stdout.read(1):
                    raise FimEngineError("unexpected bytes after horizontal profiles")
                finish_report()
            finally:
                if timer is not None:
                    timer.cancel()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
