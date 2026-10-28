"""Reproducible, fresh-process optional Rust benchmarks; never executes HEC-RAS.

Example (release extension must already be installed)::

    python scripts/benchmark_fast_hdf.py --hdf path/to/plan.p01.hdf \
        --geometry path/to/model.g03.hdf --threads 1 4 --repeats 5 \
        --output working/rust_hdf/benchmark.json

Cache is warmed, not flushed. Inputs retain their original location (SMB/local is
reported). HDF whole-file runs retain all numeric arrays on BOTH backends. Peak
RSS includes interpreter/dependency overhead; each sample uses a fresh process.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdf", type=Path)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--dataset", help="Default: largest numeric dataset in HDF")
    parser.add_argument("--threads", nargs="+", type=int, default=[1, 4])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("working/rust_hdf/benchmark.json"))
    parser.add_argument("--python-only", action="store_true", help="Capture baseline before extension build")
    parser.add_argument("--tiles", action="store_true", help="Also measure direct mesh PMTiles at z10..12")
    parser.add_argument("--operations", nargs="+", help="Limit to named operations (e.g. pmtiles)")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    return parser.parse_args()


def worker(task):
    # freestiler's Python binding uses Rayon's global pool rather than exposing
    # a threads argument. Set its documented environment control before import.
    os.environ["RAYON_NUM_THREADS"] = str(task["threads"])
    import gc
    import h5py
    import numpy as np
    from ras_commander import fast_hdf
    from ras_commander.hdf import HdfMesh
    operation, backend = task["operation"], task["backend"]
    path, threads = task["path"], task["threads"]
    native = None
    if backend == "rust":
        import ras_commander_fast_hdf as native
        assert native.API_VERSION == 1
    prepared_arrays = []
    projection_input = None
    if operation == "assemble_only":
        with h5py.File(path, "r") as f:
            for mesh in HdfMesh.get_mesh_area_names(path):
                prepared_arrays.append([
                    np.ascontiguousarray(f[f"Geometry/2D Flow Areas/{mesh}/{name}"][()],
                                         dtype=np.float64 if i in (0, 3) else np.int64)
                    for i, name in enumerate(fast_hdf._MESH_ARRAYS)])
    if operation == "pyproj_only":
        from pyproj import Transformer
        from ras_commander.hdf import HdfBase
        projection_input = fast_hdf.packed_meshes(path, backend="rust", threads=threads)
        transformer = Transformer.from_crs(HdfBase.get_projection(path), "EPSG:4326", always_xy=True)
    names = []
    if operation in {"whole_numeric", "dataset", "slice"}:
        with h5py.File(path, "r") as f:
            f.visititems(lambda name, obj: names.append(name) if isinstance(obj, h5py.Dataset)
                         and obj.dtype.kind in "iuf" and obj.shape is not None else None)
        # Warm filesystem pages without first decompressing through h5py. This
        # avoids giving its allocator/cache state a head start over Rust and
        # avoids counting a large warmup array in peak extraction memory.
        with open(path, "rb") as raw:
            for _ in iter(lambda: raw.read(8 * 1024 * 1024), b""):
                pass
    def run():
        if operation == "whole_numeric":
            if native:
                return native.read_numeric_batch(path, names, threads=threads, parallel=threads > 1)
            with h5py.File(path, "r") as f:
                return {name: f[name][()] for name in names}
        if operation in {"dataset", "slice"}:
            name = task["dataset"]
            with h5py.File(path, "r") as f:
                ds = f[name]
                selection = tuple(slice(0, n, 4) for n in ds.shape) if operation == "slice" else None
                if native:
                    native_selection = [(0, n, 4) for n in ds.shape] if selection else None
                    return native.read_numeric(path, name, selection=native_selection,
                                               threads=threads, parallel=threads > 1)
                return ds[selection if selection else ()]
        if operation == "polygons":
            return HdfMesh.get_mesh_cell_polygons(path, engine=backend, threads=threads)
        if operation == "packed_mesh":
            return fast_hdf.packed_meshes(path, backend="rust", threads=threads)
        if operation == "assemble_only":
            return [native.assemble_cells(*arrays, threads=threads) for arrays in prepared_arrays]
        if operation == "pyproj_only":
            return {name: np.column_stack(transformer.transform(item["coordinates"][:, 0],
                    item["coordinates"][:, 1], errcheck=True)) for name, item in projection_input.items()}
        if operation == "pmtiles":
            if backend == "python":
                import freestiler
                frame = HdfMesh.get_mesh_cell_polygons(path, engine="h5py")
                return freestiler.freestile(frame, task["destination"], layer_name="mesh_cells",
                    min_zoom=10, max_zoom=12, simplification=False, drop_rate=None, quiet=True)
            return fast_hdf.export_mesh_pmtiles(path, task["destination"], backend="rust",
                                                min_zoom=10, max_zoom=12, threads=threads)
        raise ValueError(operation)
    # Warm geometry imports/metadata as well. Timed result lives until output.
    if operation in {"polygons", "packed_mesh"}:
        run()
    gc.collect()
    try:
        import psutil
        before = psutil.Process().memory_info().rss
    except ImportError:
        before = None
    if task.get("_signal"):
        Path(task["_signal"]).write_text("running")
    start = time.perf_counter()
    result = run()
    elapsed = time.perf_counter() - start
    size = len(result) if hasattr(result, "__len__") else None
    if operation == "polygons":
        assert size, "Polygon extraction returned empty output"
    output_bytes = Path(task["destination"]).stat().st_size if operation == "pmtiles" else None
    print(json.dumps({"seconds": elapsed, "result_count": size, "rss_before_bytes": before,
                      "output_bytes": output_bytes,
                      "native_executed": native is not None and operation != "pyproj_only",
                      "dataset_count": len(names)}), flush=True)


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.absolute()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(), "location": "network" if str(path.absolute()).startswith(("H:", "\\\\")) else "local"}


def main():
    args = parse_args()
    if args.worker:
        worker(json.loads(args.worker))
        return
    if args.repeats < 1 or any(n < 1 for n in args.threads):
        raise SystemExit("repeats and threads must be positive")
    import h5py
    try:
        import psutil
    except ImportError:
        raise SystemExit("Install psutil for fresh-process peak RSS measurement")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cases = []
    backends = [("python", 1)] + ([] if args.python_only else [("rust", n) for n in args.threads])
    if args.hdf:
        with h5py.File(args.hdf, "r") as f:
            candidates = []
            f.visititems(lambda name, obj: candidates.append((obj.size * obj.dtype.itemsize, name))
                if isinstance(obj, h5py.Dataset) and obj.dtype.kind in "iuf" and obj.shape is not None else None)
            dataset = args.dataset or max(candidates)[1]
        for operation in ("whole_numeric", "dataset", "slice"):
            for backend, threads in backends:
                cases.append(dict(operation=operation, backend=backend, threads=threads,
                                  path=str(args.hdf.absolute()), dataset=dataset))
    if args.geometry:
        for backend, threads in backends:
            cases.append(dict(operation="polygons", backend=backend, threads=threads, path=str(args.geometry.absolute())))
        if args.tiles:
            for threads in args.threads:
                cases.append(dict(operation="pmtiles", backend="python", threads=threads,
                    path=str(args.geometry.absolute()), destination=str(args.output.with_suffix(f".python{threads}.pmtiles").absolute())))
        if not args.python_only:
            for threads in args.threads:
                cases.append(dict(operation="packed_mesh", backend="rust", threads=threads, path=str(args.geometry.absolute())))
                cases.append(dict(operation="assemble_only", backend="rust", threads=threads, path=str(args.geometry.absolute())))
                if args.tiles:
                    cases.append(dict(operation="pmtiles", backend="rust", threads=threads,
                        path=str(args.geometry.absolute()), destination=str(args.output.with_suffix(f".{threads}.pmtiles").absolute())))
            cases.append(dict(operation="pyproj_only", backend="rust", threads=1, path=str(args.geometry.absolute())))
    if args.operations:
        cases = [case for case in cases if case["operation"] in args.operations]
        if not cases:
            raise SystemExit("No selected operations match the supplied inputs/options")
    report = {"machine": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count(),
              "python": sys.version, "cache": "warm; no OS cache flush", "repeats": args.repeats,
              "started_unix_seconds": time.time(),
              "versions": {name: metadata.version(name) for name in ("numpy", "h5py", "shapely", "geopandas")},
              "inputs": [fingerprint(p) for p in (args.hdf, args.geometry) if p], "samples": [], "summary": []}
    for repetition in range(args.repeats):
        # Alternate ordering to reduce systematic machine/cache drift.
        for case_index, task in enumerate(cases if repetition % 2 == 0 else reversed(cases)):
            start = time.perf_counter()
            signal = args.output.parent / f".fast-hdf-{os.getpid()}-{repetition}-{case_index}.running"
            worker_task = dict(task, _signal=str(signal.absolute()))
            process = subprocess.Popen([sys.executable, str(Path(__file__).absolute()), "--worker", json.dumps(worker_task)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            peak, operation_peak = 0, 0
            proc = psutil.Process(process.pid)
            while process.poll() is None:
                try:
                    rss = sum(p.memory_info().rss for p in [proc, *proc.children(recursive=True)])
                    peak = max(peak, rss)
                    if signal.exists():
                        operation_peak = max(operation_peak, rss)
                except psutil.Error:
                    pass
                time.sleep(.02)
            stdout, stderr = process.communicate()
            signal.unlink(missing_ok=True)
            sample = dict(task, repetition=repetition, peak_rss_bytes=peak,
                          operation_peak_rss_bytes=operation_peak, memory_sample_interval_ms=20,
                          started_unix_seconds=time.time() - (time.perf_counter()-start),
                          subprocess_seconds=time.perf_counter()-start, returncode=process.returncode)
            if process.returncode:
                sample["error"] = stderr[-5000:]
            else:
                sample.update(json.loads(stdout.strip().splitlines()[-1]))
            report["samples"].append(sample)
            args.output.write_text(json.dumps(report, indent=2))
            print(json.dumps({k:sample.get(k) for k in ("operation", "backend", "threads", "repetition", "seconds", "peak_rss_bytes", "returncode")}), flush=True)
    for task in cases:
        samples = [s for s in report["samples"] if all(s[k] == v for k,v in task.items())]
        valid = [s for s in samples if s["returncode"] == 0]
        summary = dict(task, successful_samples=len(valid), failed_samples=len(samples)-len(valid))
        if valid:
            times = [s["seconds"] for s in valid]
            summary.update(median_seconds=statistics.median(times), min_seconds=min(times), max_seconds=max(times),
                           peak_rss_bytes=max(s["peak_rss_bytes"] for s in valid),
                           operation_peak_rss_bytes=max(s["operation_peak_rss_bytes"] for s in valid))
        report["summary"].append(summary)
    args.output.write_text(json.dumps(report, indent=2))
    if any(s["returncode"] for s in report["samples"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
