"""Benchmark the public get_mesh_max_depth route: Python reference vs native.

Every measurement runs in a fresh child process (cold interpreter, OS file
cache warmed by the up-front fixture hash). Reference and candidate runs are
interleaved with alternating order. Two scopes are reported separately:

- ``public``: complete ``HdfResultsMesh.get_mesh_max_depth`` (HDF extraction +
  reduction + GeoDataFrame construction), with the reduction stage timed by a
  wrapper and peak process working set.
- ``kernel``: per-mesh reduction only. Python = full h5py extraction, then the
  unchanged reference loop on the in-memory array; native = the kernel's own
  setup/read(decompress)/reduce timings.

Outputs are hashed (mesh names, cell ids, ghost flags, maxima bytes, geometry
WKB) and must match between routes, otherwise the run aborts.

    python bench_max_depth.py --fixture-root DIR --fixture REL [...] --reps 3 --out OUT.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"


def _peak_rss():
    import psutil

    info = psutil.Process().memory_info()
    return int(getattr(info, "peak_wset", 0) or getattr(info, "rss", 0))


def _rss():
    import psutil

    return int(psutil.Process().memory_info().rss)


def child_public(path, backend):
    os.environ["RAS_COMMANDER_FAST_HDF"] = "required" if backend == "rust" else "0"
    started = time.perf_counter()
    import shapely
    from ras_commander import fast_results
    from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

    imported = time.perf_counter()
    rss_before = _rss()
    stage = {"reduction_seconds": 0.0, "native": []}
    original = HdfResultsMesh._get_mesh_temporal_maximum
    native_original = fast_results.native_temporal_reduce

    def timed(*args, **kwargs):
        t = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            stage["reduction_seconds"] += time.perf_counter() - t

    def native_timed(*args, **kwargs):
        result = native_original(*args, **kwargs)
        if result is not None:
            stage["native"].append(dict(result.timings))
        return result

    HdfResultsMesh._get_mesh_temporal_maximum = staticmethod(timed)
    fast_results.native_temporal_reduce = native_timed
    t = time.perf_counter()
    gdf = HdfResultsMesh.get_mesh_max_depth(path)
    total = time.perf_counter() - t
    digest = hashlib.sha256()
    for column in ("mesh_name", "cell_id", "is_ghost_cell"):
        digest.update(repr(gdf[column].tolist()).encode())
    digest.update(gdf["maximum_depth"].to_numpy().tobytes())
    digest.update(str(gdf["maximum_depth"].dtype).encode())
    digest.update(b"".join(shapely.to_wkb(gdf.geometry.values)))
    digest.update(str(gdf.crs).encode())
    if backend == "rust" and not stage["native"]:
        raise SystemExit("native route did not run")
    return dict(scope="public", backend=backend, total_seconds=total,
                reduction_seconds=stage["reduction_seconds"],
                frame_and_geometry_seconds=total - stage["reduction_seconds"],
                native_stage_seconds={k: sum(n[k] for n in stage["native"])
                                      for k in ("setup_seconds", "read_seconds", "reduce_seconds")}
                if stage["native"] else None,
                import_seconds=imported - started, rows=len(gdf), output_sha256=digest.hexdigest(),
                rss_before_call=rss_before, peak_rss=_peak_rss())


def child_kernel(path, backend):
    os.environ["RAS_COMMANDER_FAST_HDF"] = "required" if backend == "rust" else "0"
    import h5py
    import numpy as np
    from ras_commander import fast_results
    from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

    rss_before = _rss()
    stages = {"extraction_seconds": 0.0, "reduce_seconds": 0.0, "setup_seconds": 0.0}
    digest = hashlib.sha256()
    t_all = time.perf_counter()
    with h5py.File(path, "r") as hdf:
        for mesh in hdf[BASE]:
            group = hdf[f"{BASE}/{mesh}"]
            if not hasattr(group, "keys") or "Water Surface" not in group:
                continue
            if "Depth" in group:
                dataset, offset = group["Depth"], None
            else:
                dataset = group["Water Surface"]
                offset = hdf[f"Geometry/2D Flow Areas/{mesh}/Cells Minimum Elevation"][()]
                offset = offset.astype(np.float32)
            if backend == "rust":
                result = fast_results.native_temporal_reduce(dataset, offset, backend="rust")
                stages["setup_seconds"] += result.timings["setup_seconds"]
                stages["extraction_seconds"] += result.timings["read_seconds"]
                stages["reduce_seconds"] += result.timings["reduce_seconds"]
                maximum = result.maximum
            else:
                t = time.perf_counter()
                values = dataset[()]
                stages["extraction_seconds"] += time.perf_counter() - t
                t = time.perf_counter()
                maximum = HdfResultsMesh._get_mesh_temporal_maximum(values, offset)
                stages["reduce_seconds"] += time.perf_counter() - t
                del values
            digest.update(mesh.encode() + maximum.tobytes())
    return dict(scope="kernel", backend=backend, total_seconds=time.perf_counter() - t_all,
                output_sha256=digest.hexdigest(), rss_before_call=rss_before,
                peak_rss=_peak_rss(), **stages)


def hardware():
    import psutil

    cpu = platform.processor()
    try:
        cpu = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor).Name"],
                             capture_output=True, text=True, timeout=30).stdout.strip() or cpu
    except Exception:
        pass
    return dict(host=platform.node(), cpu=cpu, logical_cpus=os.cpu_count(),
                physical_cpus=psutil.cpu_count(logical=False),
                ram_gib=round(psutil.virtual_memory().total / 2**30, 1),
                native_default_threads=min(8, os.cpu_count() or 1),
                python=sys.version.split()[0], platform=platform.platform())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=["public", "kernel"])
    parser.add_argument("--path")
    parser.add_argument("--backend", choices=["python", "rust"])
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--scope", action="append", choices=["public", "kernel"])
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.child:
        run = child_public if args.child == "public" else child_kernel
        print(json.dumps(run(args.path, args.backend)))
        return

    import ras_commander
    import ras_commander_fast_hdf as native

    binary = Path(getattr(native, "ras_commander_fast_hdf", native).__file__)
    report = dict(hardware=hardware(), ras_commander=ras_commander.__file__,
                  native_binary=str(binary),
                  native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  cache_scope="fresh child process per run; OS file cache warm after fixture hash",
                  temporary_disk="none (no temporary files are written by either route)",
                  runs=[], fixtures={})
    for rel in args.fixture:
        path = args.fixture_root / rel
        report["fixtures"][rel] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                       bytes=path.stat().st_size)
        for scope in args.scope or ["public", "kernel"]:
            for rep in range(args.reps):
                order = ("python", "rust") if rep % 2 == 0 else ("rust", "python")
                for backend in order:
                    out = subprocess.run([sys.executable, __file__, "--child", scope, "--path",
                                          str(path), "--backend", backend],
                                         capture_output=True, text=True, check=True)
                    record = json.loads(out.stdout.strip().splitlines()[-1])
                    record.update(fixture=rel, rep=rep)
                    report["runs"].append(record)
                    print(f"{rel} {scope} rep{rep} {backend}: {record['total_seconds']:.3f}s "
                          f"peak {record['peak_rss'] / 2**20:.0f} MiB", flush=True)
            hashes = {r["output_sha256"] for r in report["runs"]
                      if r["fixture"] == rel and r["scope"] == scope}
            if len(hashes) != 1:
                raise SystemExit(f"outputs differ between routes for {rel} {scope}: {hashes}")
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
