"""Consumer benchmark: repeated open/select/read versus whole-plan archival.

Every measurement runs in a fresh ``python -I`` worker process so peak process
RSS and process I/O are attributable to one route. Routes are interleaved and
repeated (default 3) over the same immutable local fixture copies; every route
returns the same requested slices, checked by SHA256 digest, so speed is only
reported for semantically equal output.

    python -I benchmark.py run --fixtures DIR --out DIR [--reps 3]
    python -I benchmark.py worker --route R --fixture F --mesh M --out J

Routes (read): ondemand_native, ondemand_python, archival_native,
archival_python. Routes (export): export_native_parquet, export_ref_parquet,
export_native_fgb, export_ref_fgb.

Measurement scope and limits (also written into the results):
* Windows io_counters().read_bytes counts bytes the process requested through
  ReadFile, including OS cache hits; it is not disk-physical I/O. Runs after
  the first are OS-cache warm. Imports happen before the I/O window.
* peak_wset is the process peak working set (Windows); it includes the
  interpreter, NumPy/h5py and native module and is not isolated native memory.
* chunk_plan.compressed_bytes sums h5py chunk-index sizes of every storage
  chunk a selection intersects (the minimum compressed bytes any reader must
  fetch); decompressed_bytes is what whole-chunk decompression must produce.
  Returned array size is reported separately and is not evidence of I/O.
* Copies: on-demand native decompresses touched chunks into Rust buffers and
  copies the selection into a new NumPy-owned array (no IPC). Archival native
  materialises the whole dataset as one NumPy array. Export routes stage an
  Arrow IPC temp file (measured as ipc_stage_bytes) that Rust re-reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

RESULTS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
READ_ROUTES = ["ondemand_native", "ondemand_python", "archival_native", "archival_python"]
EXPORT_ROUTES = ["export_native_parquet", "export_ref_parquet", "export_native_fgb", "export_ref_fgb"]
READ_CASES = [
    ("BaldEagleDamBrk.p07.hdf", "BaldEagleCr"),       # 6.6, 865 x 89879, row chunks
    ("JUL2020_D100RAS.p04.hdf", "D601"),              # 5.0.7, 193 x 352141, row chunks
    ("BaldEagleDamBrk.p18.hdf", "BaldEagleCr"),       # 7.0, 865 x 3947, 12-row chunks
]
EXPORT_CASE = "BaldEagleDamBrk.p07.hdf"


def _counters():
    import psutil
    proc = psutil.Process()
    io, mem = proc.io_counters(), proc.memory_info()
    return {"read_bytes": io.read_bytes, "read_count": io.read_count,
            "write_bytes": io.write_bytes, "rss": mem.rss,
            "peak_wset": getattr(mem, "peak_wset", None)}


def _requests(shape, count, width, seed=20261018):
    import numpy as np
    rng = np.random.default_rng(seed)
    times, cells = shape
    width = min(width, cells)
    return [(int(rng.integers(0, times)), int(start), int(start) + width)
            for start in rng.integers(0, cells - width + 1, size=count)]


def _chunk_plan(ds, requests):
    chunks = ds.chunks or ds.shape
    touched = set()
    for t, a, b in requests:
        for c in range(a // chunks[1], (b - 1) // chunks[1] + 1):
            touched.add((t // chunks[0] * chunks[0], c * chunks[1]))
    compressed = 0
    for coord in touched:
        info = ds.id.get_chunk_info_by_coord(coord)
        compressed += info.size
    chunk_bytes = int(chunks[0] * chunks[1] * ds.dtype.itemsize)
    return {"chunks": list(chunks), "chunks_touched": len(touched),
            "compressed_bytes": compressed, "decompressed_bytes": len(touched) * chunk_bytes,
            "dataset_bytes": int(ds.size * ds.dtype.itemsize), "storage_bytes": int(ds.id.get_storage_size())}


def worker(args):
    t0 = time.perf_counter()
    import h5py
    import numpy as np
    import ras_commander
    import ras_commander_fast_hdf as native
    from ras_commander import fast_hdf
    origin = Path(ras_commander.__file__).resolve()
    t_import = time.perf_counter() - t0
    counts = {"read_numeric": 0, "read_numeric_batch": 0, "export_ipc_file": 0}
    import functools
    for name in counts:
        original = getattr(native, name)

        def make(fn, key):
            @functools.wraps(fn)
            def wrapper(*a, **k):
                counts[key] += 1
                return fn(*a, **k)
            return wrapper
        setattr(native, name, make(original, name))
    route, path = args.route, Path(args.fixture)
    timing = {"import_seconds": t_import, "setup_seconds": 0.0, "kernel_seconds": 0.0,
              "select_seconds": 0.0, "encode_seconds": 0.0, "output_seconds": 0.0}
    digest = hashlib.sha256()
    returned = 0
    extra = {}
    if route in READ_ROUTES:
        dataset = f"{RESULTS}/2D Flow Areas/{args.mesh}/Water Surface"
        with h5py.File(path, "r") as h:
            ds = h[dataset]
            requests = _requests(ds.shape, args.requests, args.width)
            plan = _chunk_plan(ds, requests) if route.startswith("ondemand") else \
                _chunk_plan(ds, [(t, 0, ds.shape[1]) for t in range(ds.shape[0])])
        before = _counters()
        start = time.perf_counter()
        if route.startswith("ondemand"):
            backend = "rust" if route.endswith("native") else "python"
            for t, a, b in requests:
                s = time.perf_counter()
                with h5py.File(path, "r") as h:
                    ds = h[dataset]
                    timing["setup_seconds"] += time.perf_counter() - s
                    k = time.perf_counter()
                    values = fast_hdf.read_dataset(ds, (t, slice(a, b)), backend=backend)
                    timing["kernel_seconds"] += time.perf_counter() - k
                digest.update(np.ascontiguousarray(values).tobytes())
                returned += values.nbytes
        else:
            k = time.perf_counter()
            if route == "archival_native":
                whole = fast_hdf.read_datasets(path, [dataset], backend="rust")[dataset]
            else:
                with h5py.File(path, "r") as h:
                    whole = h[dataset][()]
            timing["kernel_seconds"] = time.perf_counter() - k
            s = time.perf_counter()
            for t, a, b in requests:
                values = whole[t, a:b]
                digest.update(np.ascontiguousarray(values).tobytes())
                returned += values.nbytes
            timing["select_seconds"] = time.perf_counter() - s
            extra["materialized_bytes"] = int(whole.nbytes)
            del whole
        window = time.perf_counter() - start
        after = _counters()
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq
        import geopandas as gpd
        out_dir = Path(args.scratch)
        out_dir.mkdir(parents=True, exist_ok=True)
        table = pq.read_table(args.reference)  # frozen Python reference rows (same input)
        geo_meta = json.loads(table.schema.metadata[b"geo"])
        crs = geo_meta["columns"][geo_meta["primary_column"]]["crs"]
        schema = pa.schema([pa.field("mesh_name", pa.string(), False), pa.field("cell_id", pa.int64(), False),
                            # Native export accepts float64, not float32 (explicit error);
                            # widening the float32 reference depth is lossless.
                            pa.field("geometry", pa.binary(), False), pa.field("maximum_depth", pa.float64()),
                            pa.field("is_ghost_cell", pa.bool_())])
        table = table.select(["mesh_name", "cell_id", "geometry", "maximum_depth", "is_ghost_cell"]).cast(schema)
        fmt = "parquet" if route.endswith("parquet") else "fgb"
        output = out_dir / f"{route}.{fmt}"
        if output.exists():
            output.unlink()
        sink = pa.BufferOutputStream()
        with pa.ipc.new_file(sink, schema) as w:
            w.write_table(table)
        extra["ipc_stage_bytes_estimate"] = sink.getvalue().size if route.startswith("export_native") else 0
        before = _counters()
        start = time.perf_counter()
        if route.startswith("export_native"):
            metrics = fast_hdf.export_arrow(output, table, source_crs=crs, format=fmt)
            extra["native_metrics"] = metrics
            timing["encode_seconds"] = metrics.get("write_seconds", 0.0)
            timing["output_seconds"] = metrics.get("finalize_seconds", 0.0)
        else:
            e = time.perf_counter()
            frame = gpd.GeoDataFrame(table.drop(["geometry"]).to_pandas(),
                                     geometry=gpd.GeoSeries.from_wkb(table.column("geometry").to_numpy(zero_copy_only=False)),
                                     crs=crs)
            timing["encode_seconds"] = time.perf_counter() - e
            o = time.perf_counter()
            if fmt == "parquet":
                frame.to_parquet(output)
            else:
                frame.to_file(output, driver="FlatGeobuf", engine="pyogrio")
            timing["output_seconds"] = time.perf_counter() - o
        window = time.perf_counter() - start
        after = _counters()
        # Semantic output digest from an independent reopen.
        import pyogrio
        import shapely
        if fmt == "parquet":
            back = pq.read_table(output)
            geom = back.column("geometry").to_pylist()
        else:
            _meta, back = pyogrio.read_arrow(output)
            geom = back.column(_meta.get("geometry_name") or "wkb_geometry").to_pylist()
        order = sorted(range(back.num_rows), key=lambda i: (back.column("mesh_name")[i].as_py(),
                                                            back.column("cell_id")[i].as_py()))
        norm = shapely.to_wkb(shapely.normalize(shapely.from_wkb([geom[i] for i in order])), flavor="iso")
        for i, g in zip(order, norm):
            digest.update(f"{back.column('mesh_name')[i].as_py()}|{back.column('cell_id')[i].as_py()}|"
                          f"{back.column('maximum_depth')[i].as_py()!r}|".encode())
            digest.update(g)
        returned = output.stat().st_size
        plan = None
    result = {
        "route": route, "fixture": str(path), "mesh": args.mesh, "digest": digest.hexdigest(),
        "returned_bytes": returned, "timing": timing, "window_seconds": window,
        "io": {"read_bytes": after["read_bytes"] - before["read_bytes"],
               "read_count": after["read_count"] - before["read_count"],
               "write_bytes": after["write_bytes"] - before["write_bytes"]},
        "rss_after_imports": before["rss"], "peak_wset": after["peak_wset"],
        "chunk_plan": plan, "native_calls": counts, "ras_commander": str(origin),
        "native_binary": str(Path(sys.modules["ras_commander_fast_hdf.ras_commander_fast_hdf"].__file__).resolve()),
        **extra,
    }
    if route.endswith("python") or route.startswith("export_ref"):
        assert sum(counts.values()) == 0, f"reference route made native calls: {counts}"
    elif route.startswith("ondemand"):
        assert counts["read_numeric"] == args.requests and counts["read_numeric_batch"] == 0
    elif route == "archival_native":
        assert counts["read_numeric_batch"] == 1
    elif route.startswith("export_native"):
        assert counts["export_ipc_file"] == 1
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def run(args):
    import psutil
    fixtures, out = Path(args.fixtures), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    jobs = [(name, mesh, READ_ROUTES) for name, mesh in READ_CASES]
    jobs.append((EXPORT_CASE, "BaldEagleCr", EXPORT_ROUTES))
    for name, mesh, routes in jobs:
        for rep in range(args.reps):
            order = routes[rep % len(routes):] + routes[:rep % len(routes)]  # rotate per rep
            for route in order:
                target = out / f"{Path(name).stem}-{route}-{rep}.json"
                cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "worker", "--route", route,
                       "--fixture", str(fixtures / name), "--mesh", mesh, "--requests", str(args.requests),
                       "--width", str(args.width), "--out", str(target),
                       "--scratch", str(out / "scratch"),
                       "--reference", str(Path(args.reference_dir) / f"{name}.parquet") if args.reference_dir else ""]
                start = time.perf_counter()
                subprocess.run(cmd, check=True, cwd=out)
                row = json.loads(target.read_text())
                row.update(rep=rep, position=order.index(route), process_wall_seconds=time.perf_counter() - start)
                rows.append(row)
                print(f"{name} {route} rep{rep}: wall {row['process_wall_seconds']:.2f}s "
                      f"window {row['window_seconds']:.3f}s read_bytes {row['io']['read_bytes']}", flush=True)
    meta = {
        "schema": "ras-commander/consumer-benchmark/v1",
        "host": platform.node(), "processor": platform.processor(),
        "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
        "python": sys.version, "reps": args.reps, "requests": args.requests, "width": args.width,
        "scope": "OS-cache warm after first touch; fresh process per measurement; release wheel",
        "limits": __doc__.split("Measurement scope and limits (also written into the results):")[1].strip(),
    }
    _write(out, meta, rows)


PAIRS = [("ondemand_python", "ondemand_native"), ("archival_python", "archival_native"),
         ("archival_native", "ondemand_native"), ("archival_python", "ondemand_python"),
         ("export_ref_parquet", "export_native_parquet"), ("export_ref_fgb", "export_native_fgb")]


def _summarize(rows):
    """Group by (fixture, job kind); a fixture can carry both read and export jobs."""
    summary = {}
    for kind, routes in (("read", READ_ROUTES), ("export", EXPORT_ROUTES)):
        for fixture in sorted({r["fixture"] for r in rows if r["route"] in routes}):
            sel_rows = [r for r in rows if r["fixture"] == fixture and r["route"] in routes]
            group = {}
            for route in routes:
                sel = sorted((r for r in sel_rows if r["route"] == route), key=lambda r: r["rep"])
                if not sel:
                    continue
                group[route] = {
                    "reps": [r["rep"] for r in sel], "positions": [r["position"] for r in sel],
                    "window_seconds": [r["window_seconds"] for r in sel],
                    "median_window_seconds": _median([r["window_seconds"] for r in sel]),
                    "process_wall_seconds": [r["process_wall_seconds"] for r in sel],
                    "import_seconds": [r["timing"]["import_seconds"] for r in sel],
                    "setup_seconds": [r["timing"]["setup_seconds"] for r in sel],
                    "kernel_seconds": [r["timing"]["kernel_seconds"] for r in sel],
                    "select_seconds": [r["timing"]["select_seconds"] for r in sel],
                    "encode_seconds": [r["timing"]["encode_seconds"] for r in sel],
                    "output_seconds": [r["timing"]["output_seconds"] for r in sel],
                    "read_bytes": [r["io"]["read_bytes"] for r in sel],
                    "write_bytes": [r["io"]["write_bytes"] for r in sel],
                    "peak_wset_max": max(r["peak_wset"] or 0 for r in sel),
                    "rss_after_imports_max": max(r["rss_after_imports"] for r in sel),
                    "peak_minus_import_rss_max": max((r["peak_wset"] or 0) - r["rss_after_imports"] for r in sel),
                    "chunk_plan": sel[0]["chunk_plan"], "returned_bytes": sel[0]["returned_bytes"],
                    "materialized_bytes": sel[0].get("materialized_bytes"),
                    "ipc_stage_bytes_estimate": sel[0].get("ipc_stage_bytes_estimate"),
                    "native_calls": sel[0]["native_calls"], "digests": sorted({r["digest"] for r in sel}),
                }
            ratios = {}
            for ref, cand in PAIRS:
                if ref in group and cand in group:
                    paired = [a / b for a, b in zip(group[ref]["window_seconds"], group[cand]["window_seconds"])]
                    ratios[f"{ref}/{cand}"] = {"per_rep": paired, "median": _median(paired)}
            if kind == "read":
                equal = len({r["digest"] for r in sel_rows}) == 1
            else:
                equal = all(len({r["digest"] for r in sel_rows if r["route"] in (f"export_native_{f}", f"export_ref_{f}")}) == 1
                            for f in ("parquet", "fgb"))
            summary[f"{Path(fixture).name}:{kind}"] = {"semantically_equal": equal, "routes": group,
                                                       "window_time_ratios": ratios}
    return summary


def _write(out, meta, rows):
    summary = _summarize(rows)
    (out / "consumer-benchmark.json").write_text(json.dumps({**meta, "summary": summary, "rows": rows},
                                                            indent=2, default=str))
    print(json.dumps({k: {r: round(v["median_window_seconds"], 4) for r, v in s["routes"].items()}
                      | {"equal": s["semantically_equal"]} for k, s in summary.items()}, indent=1))


def summarize(args):
    """Rebuild the summary from recorded rows (no re-measurement)."""
    out = Path(args.out)
    data = json.loads((out / "consumer-benchmark.json").read_text())
    meta = {k: v for k, v in data.items() if k not in {"summary", "rows"}}
    _write(out, meta, data["rows"])


def main():
    parser = argparse.ArgumentParser(description="consumer-contract benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worker")
    w.add_argument("--route", required=True, choices=READ_ROUTES + EXPORT_ROUTES)
    w.add_argument("--fixture", required=True)
    w.add_argument("--mesh", required=True)
    w.add_argument("--requests", type=int, default=40)
    w.add_argument("--width", type=int, default=2000)
    w.add_argument("--out", required=True)
    w.add_argument("--scratch", default="scratch")
    w.add_argument("--reference", default="")
    r = sub.add_parser("run")
    r.add_argument("--fixtures", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--reference-dir", default="")
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--requests", type=int, default=40)
    r.add_argument("--width", type=int, default=2000)
    s = sub.add_parser("summarize")
    s.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.cmd == "worker":
        worker(args)
    elif args.cmd == "summarize":
        summarize(args)
    else:
        if args.reps < 3:
            parser.error("at least 3 interleaved repetitions are required")
        run(args)


if __name__ == "__main__":
    main()
