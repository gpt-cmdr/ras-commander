"""Public-API qualification: HdfFluvialPluvial engine="h5py" vs engine="native".

Runs both engines on one immutable computed plan HDF, interleaved, and writes a
JSON record of semantic equality (classes, geometry, identity attributes, CRS,
columns, boundary lines) plus per-run wall time and peak process RSS.

    python qualify_public.py <plan.hdf> --out result.json [--repeats 3]
        [--min-area 0.5] [--skip-boundary] [--skip-polygons]

Each repetition runs in a fresh subprocess so imports, HDF caches and RSS are
cold-equivalent for both engines; the order alternates per repetition.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def child(args):
    """One measured public call in this process; prints a JSON record."""
    import psutil
    import ras_commander
    import ras_commander_fast_hdf
    from ras_commander.hdf.HdfFluvialPluvial import HdfFluvialPluvial
    from ras_commander.hdf import HdfFluvialNative

    started = time.perf_counter()
    if args.kind == "polygons":
        frame = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            Path(args.hdf), delta_t=args.delta_t, temporal_tolerance_hours=args.tolerance,
            min_polygon_area_acres=args.min_area, engine=args.engine)
    else:
        frame = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
            Path(args.hdf), delta_t=args.delta_t, engine=args.engine)
    wall = time.perf_counter() - started
    stages = frame.attrs.pop("fluvial_native", None)
    engine_attrs = frame.attrs.pop("fluvial_engine", None)
    frame.to_parquet(args.frame)  # GeoParquet keeps WKB exactly, plus CRS
    frame.attrs.update({"fluvial_native": stages, "fluvial_engine": engine_attrs})
    record = {
        "engine": args.engine, "kind": args.kind, "wall_seconds": wall,
        "peak_rss_bytes": psutil.Process().memory_info().peak_wset,
        "rows": len(frame), "columns": list(frame.columns),
        "native_calls": dict(HdfFluvialNative.NATIVE_CALLS),
        "engine_attrs": frame.attrs.get("fluvial_engine"),
        "native_stages": frame.attrs.get("fluvial_native"),
        "ras_commander_file": ras_commander.__file__,
        "native_module_file": ras_commander_fast_hdf.__file__,
    }
    print("RESULT " + json.dumps(record))


def run_child(args, engine, kind, frame_path):
    command = [sys.executable, __file__, "--child", "--engine", engine, "--kind", kind,
               "--frame", str(frame_path), "--delta-t", str(args.delta_t),
               "--tolerance", str(args.tolerance), args.hdf]
    if args.min_area is not None:
        command += ["--min-area", str(args.min_area)]
    completed = subprocess.run(command, capture_output=True, text=True)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("RESULT ")]
    if completed.returncode or not lines:
        return {"engine": engine, "kind": kind, "error": completed.stderr[-4000:]}
    return json.loads(lines[-1][7:])


def compare_polygons(python_path, native_path):
    import geopandas as gpd
    left, right = gpd.read_parquet(python_path), gpd.read_parquet(native_path)
    result = {"python_rows": len(left), "native_rows": len(right),
              "columns_equal": list(left.columns) == list(right.columns),
              "crs_equal": left.crs == right.crs, "classes": {}}
    if left.empty or right.empty:
        result["equal"] = False
        return result
    left, right = left.set_index("classification"), right.set_index("classification")
    result["class_sets_equal"] = sorted(left.index) == sorted(right.index)
    equal = result["columns_equal"] and result["crs_equal"] and result["class_sets_equal"]
    for name in sorted(set(left.index) | set(right.index)):
        if name not in left.index or name not in right.index:
            result["classes"][name] = {"present_in": "python" if name in left.index else "native"}
            equal = False
            continue
        a, b = left.loc[name], right.loc[name]
        sym = a.geometry.symmetric_difference(b.geometry).area
        record = {
            "topologically_equal": bool(a.geometry.equals(b.geometry)),
            "python_area": a.geometry.area, "native_area": b.geometry.area,
            "symmetric_difference_area": sym,
            "python_parts": len(getattr(a.geometry, "geoms", [a.geometry])),
            "native_parts": len(getattr(b.geometry, "geoms", [b.geometry])),
            "native_valid": bool(b.geometry.is_valid),
            "attributes_equal": all(str(a[c]) == str(b[c]) for c in left.columns if c != "geometry"),
        }
        equal = equal and record["topologically_equal"] and record["attributes_equal"]
        result["classes"][name] = record
    result["equal"] = bool(equal)
    return result


def compare_boundary(python_path, native_path):
    import geopandas as gpd
    from collections import Counter
    left, right = gpd.read_parquet(python_path), gpd.read_parquet(native_path)
    canonical = lambda frame: Counter(g.normalize().wkb_hex for g in frame.geometry)
    a, b = canonical(left), canonical(right)
    return {"python_rows": len(left), "native_rows": len(right), "crs_equal": left.crs == right.crs,
            "only_python": sum((a - b).values()), "only_native": sum((b - a).values()),
            "equal": a == b and left.crs == right.crs and len(left) > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("hdf")
    parser.add_argument("--out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--delta-t", type=float, default=12)
    parser.add_argument("--tolerance", type=float, default=1.0)
    parser.add_argument("--min-area", type=float)
    parser.add_argument("--skip-boundary", action="store_true")
    parser.add_argument("--skip-polygons", action="store_true")
    parser.add_argument("--engines", default="python,native")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--engine")
    parser.add_argument("--kind")
    parser.add_argument("--frame")
    args = parser.parse_args()
    if args.child:
        return child(args)
    hdf = Path(args.hdf).resolve()
    work = Path(args.out).with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    report = {"hdf": str(hdf), "sha256_before": sha256(hdf), "bytes": hdf.stat().st_size,
              "delta_t": args.delta_t, "tolerance": args.tolerance, "min_area": args.min_area,
              "python": sys.version, "cpu_count": os.cpu_count(), "runs": [], "comparisons": {}}
    engines = args.engines.split(",")
    kinds = [k for k in ("polygons", "boundary")
             if not (k == "polygons" and args.skip_polygons) and not (k == "boundary" and args.skip_boundary)]
    for kind in kinds:
        for repeat in range(args.repeats):
            order = engines if repeat % 2 == 0 else engines[::-1]
            for engine in order:
                frame = work / f"{kind}-{engine}-{repeat}.parquet"
                record = run_child(args, engine, kind, frame)
                record["repeat"] = repeat
                report["runs"].append(record)
                print(json.dumps({k: record.get(k) for k in ("kind", "engine", "repeat", "wall_seconds", "error")}),
                      flush=True)
        if set(engines) >= {"python", "native"}:
            python_frame, native_frame = work / f"{kind}-python-0.parquet", work / f"{kind}-native-0.parquet"
            if python_frame.exists() and native_frame.exists():
                compare = compare_polygons if kind == "polygons" else compare_boundary
                report["comparisons"][kind] = compare(python_frame, native_frame)
    report["sha256_after"] = sha256(hdf)
    report["unchanged"] = report["sha256_after"] == report["sha256_before"]
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report["comparisons"], indent=1, default=str))


if __name__ == "__main__":
    main()
