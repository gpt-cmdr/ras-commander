"""Parent-side bounded protocol for isolated native terrain queries."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import numpy as np

from .dotnet.clr_bootstrap import find_hecras_install
from .LoggingConfig import get_logger

logger = get_logger(__name__)


@contextmanager
def _session(config: dict, timeout_seconds: float, runtime_record: str | Path | None):
    if not np.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    install = find_hecras_install("6.6")
    target = None if runtime_record is None else Path(runtime_record)
    if target is not None and target.exists():
        raise ValueError("Native runtime record destination already exists")
    worker = Path(__file__).with_name("_terrain_query_worker.py")
    process = subprocess.Popen(
        [sys.executable, "-I", str(worker), str(install), json.dumps(config)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    messages = queue.Queue(maxsize=2)
    expired = threading.Event()

    def expire():
        expired.set()
        with suppress(OSError):
            process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)

    watchdog = threading.Timer(timeout_seconds, expire)
    watchdog.daemon = True
    watchdog.start()

    def receive():
        try:
            for line in process.stdout:
                messages.put(line)
        finally:
            messages.put(None)

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds

    def response():
        try:
            line = messages.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty as exc:
            raise RuntimeError("Isolated native terrain query timed out") from exc
        if line is None:
            if expired.is_set():
                raise RuntimeError("Isolated native terrain query timed out")
            raise RuntimeError(
                "Isolated native terrain worker exited without a complete response"
            )
        message = json.loads(line)
        if "error" in message:
            raise RuntimeError(message["error"])
        return message

    try:
        ready = response()["ready"]
        if not (
            ready["dll_identity_verified"]
            and ready["managed_hdf5_threadsafe"]
            and not ready["python_gis_hdf_imported"]
        ):
            raise RuntimeError("Isolated native terrain runtime identity failed")
        logger.info("NATIVE_TERRAIN_RUNTIME %s", json.dumps(ready, sort_keys=True))
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(ready, indent=2, sort_keys=True) + "\n")

        def query(request: dict):
            if expired.is_set():
                raise RuntimeError("Isolated native terrain query timed out")
            try:
                process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
                process.stdin.flush()
            except OSError as exc:
                if expired.is_set():
                    raise RuntimeError(
                        "Isolated native terrain query timed out"
                    ) from exc
                raise RuntimeError(
                    "Isolated native terrain worker closed its input"
                ) from exc
            return response()["result"]

        yield query
        process.stdin.close()
        execution = response()["finished"]
        maximum = execution.get("sampling_max_threads")
        if not (
            execution.get("mode") == "single-clr-pool-worker-v1"
            and execution.get("called_on_pool_worker") is True
            and execution.get("runtime_restored") is True
            and isinstance(maximum, (list, tuple))
            and len(maximum) == 2
            and all(type(v) is int and v == 1 for v in maximum)
        ):
            raise RuntimeError("Isolated native sampling execution failed")
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
        if process.returncode != 0:
            raise RuntimeError(
                "Isolated native terrain worker returned a nonzero exit code"
            )
        if target is not None:
            ready.update(status="completed", sampling_execution=execution)
            target.write_text(
                json.dumps(ready, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout):
            stream.close()
        reader.join(timeout=1)


def iter_isolated_points(
    mapper,
    name,
    batches,
    cell_size,
    use_obstructions,
    nodata_values,
    timeout_seconds,
    runtime_record,
):
    from ._terrain_point_sampling import _point_elevation_batches

    if not Path(mapper).is_file():
        raise FileNotFoundError(mapper)
    if (
        not name
        or not isinstance(use_obstructions, bool)
        or not np.isfinite(cell_size)
        or cell_size <= 0
    ):
        raise ValueError(
            "A terrain name, Boolean use_obstructions and positive cell_size are required"
        )
    config = {
        "mode": "points",
        "mapper": str(Path(mapper).absolute()),
        "terrain_name": name,
        "use_obstructions": use_obstructions,
        "cell_size": float(cell_size),
    }
    with _session(config, timeout_seconds, runtime_record) as query:
        yield from _point_elevation_batches(
            batches,
            lambda points: query({"coordinates": points.tolist()}),
            nodata_values,
        )


def isolated_profile(
    mapper, geometry, x, y, tolerance, timeout_seconds, runtime_record
):
    config = {
        "mode": "profile",
        "mapper": str(Path(mapper).absolute()),
        "geometry": str(Path(geometry).absolute()),
    }
    with _session(config, timeout_seconds, runtime_record) as query:
        return query(
            {
                "coordinates": [
                    [float(a), float(b)] for a, b in zip(x, y, strict=True)
                ],
                "filter_tolerance": float(tolerance),
            }
        )


def iter_isolated_profiles(
    mapper, geometry, profiles, tolerance, timeout_seconds, runtime_record
):
    config = {
        "mode": "profile",
        "mapper": str(Path(mapper).absolute()),
        "geometry": str(Path(geometry).absolute()),
    }
    with _session(config, timeout_seconds, runtime_record) as query:
        for coordinates in profiles:
            yield query(
                {"coordinates": coordinates, "filter_tolerance": float(tolerance)}
            )
