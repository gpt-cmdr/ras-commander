"""Explicit Rust horizontal batch adapter; no numerical fallback."""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import threading
import numpy as np
from . import _engine
from .errors import FimEngineError, FimUnsupportedError


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
):
    """Stage shared ownership once, run all profiles, validate every committed unit."""
    method = _engine.engine_method(engine).get("horizontal")
    if (
        not isinstance(method, dict)
        or method.get("method_id") != "horizontal-cell-constant/1"
        or method.get("stream_outputs") is not True
    ):
        raise FimEngineError(
            "engine does not support horizontal-cell-constant/1; install the matching wheel"
        )
    identity = _engine.terrain_identity(engine, terrain, ordered.crs)
    details["engine"] = {"path": str(engine), "method": method}
    required = grid.owner.size * 4 + len(grid.plan.cell_positions) * 4 * len(names) + (64 << 20)
    if shutil.disk_usage(scratch_folder).free < required:
        raise FimEngineError(
            f"horizontal staging needs at least {required} free bytes on the output volume"
        )
    with tempfile.TemporaryDirectory(prefix=".horizontal-", dir=scratch_folder) as tmp:
        root = Path(tmp)
        grid.owner.astype("<u4", copy=False).tofile(root / "owner.bin")
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
                values.astype("<f4").tofile(root / f"values-{i}.bin")
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
            "owner_file": "owner.bin",
            "cell_count": len(grid.plan.cell_positions),
            "profiles": profiles,
            "min_depth": float(min_depth),
            "threads": threads,
            "max_working_bytes": budget * (1 << 20),
            "stream_outputs": True,
        }
        # Transform above belongs to the window; terrain identity is its full source transform.
        import rasterio

        with rasterio.open(terrain) as src:
            request["terrain_transform"] = list(src.transform.to_gdal())
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        expected_names = [p["id"] for p in profiles]
        received = []
        received_statuses = {}
        with (root / "stderr.txt").open("w+b") as errors:
            proc = subprocess.Popen(
                [str(engine), "horizontal", str(root / "request.json"), str(root / "out")],
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
                    raise FimEngineError(f"horizontal engine exit {code}: {diagnostic}")
                report = json.loads(path.read_text(encoding="utf-8"))
                details["engine_report"] = report
                if report.get("status") == "aborted":
                    raise FimEngineError(
                        f"horizontal session aborted: {report.get('error', diagnostic)}"
                    )
                units = report.get("profiles", [])
                if (
                    code not in (0, 2)
                    or report.get("schema") != "ras2fim-horizontal-report/1"
                    or report.get("status") not in ("complete", "failed")
                    or report.get("window") != request["window"]
                    or report.get("method", {}).get("method_id") != "horizontal-cell-constant/1"
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
                if header.get("id") != name or header.get("status") not in ("complete", "failed"):
                    raise FimEngineError("horizontal stream profile/order mismatch")
                received.append(name)
                received_statuses[name] = header["status"]
                if header["status"] == "failed":
                    return header
                if header.get("pixels") != grid.owner.size:
                    raise FimEngineError("horizontal stream pixel count mismatch")
                result = {"status": "complete"}
                for product in ("depth", "wse"):
                    expected = grid.owner.size * 4
                    data = proc.stdout.read(expected)
                    if len(data) != expected:
                        if expired.is_set():
                            raise FimEngineError(
                                f"horizontal engine timed out after {timeout} seconds"
                            )
                        raise FimEngineError(f"truncated horizontal {product} stream")
                    result[product] = np.frombuffer(data, dtype="<f4").reshape(grid.plan.shape)
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
