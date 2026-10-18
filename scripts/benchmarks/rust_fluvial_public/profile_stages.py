"""Per-stage wall-time attribution for one public fluvial call (either engine).

    python profile_stages.py <plan.hdf> --engine python|native --kind polygons|boundary --out stages.json

Named stage functions are wrapped with perf_counter timers (no cProfile: its
per-call overhead inflated the Python loop roughly 60x). Nested stages overlap,
so stage seconds are not additive; the remainder is everything unwrapped
(region growing, frame construction, imports already warm are excluded).
"""
import argparse
import functools
import importlib
import json
import time
from collections import defaultdict
from pathlib import Path

# (module, attribute path, stage name)
STAGES = [
    ("ras_commander.hdf.HdfMesh", "HdfMesh.get_mesh_cell_polygons", "hdf_cell_polygons"),
    ("ras_commander.hdf.HdfMesh", "HdfMesh.get_mesh_cell_faces", "hdf_cell_faces"),
    ("ras_commander.hdf.HdfMesh", "HdfMesh.get_mesh_sloped_topology", "hdf_topology"),
    ("ras_commander.hdf.HdfResultsMesh", "HdfResultsMesh.get_mesh_max_ws", "hdf_max_ws"),
    ("ras_commander.hdf.HdfFluvialPluvial", "HdfFluvialPluvial._process_cell_adjacencies", "python_adjacency"),
    ("ras_commander.hdf.HdfFluvialPluvial", "HdfFluvialPluvial._get_boundary_cell_pairs", "python_boundary_pairs"),
    ("ras_commander.hdf.HdfFluvialPluvial", "HdfFluvialPluvial._legacy_replay", "python_tie_break_replay"),
    ("geopandas", "GeoDataFrame.dissolve", "geopandas_dissolve"),
]


def wrap(totals, counts, module_name, path, name):
    owner = importlib.import_module(module_name)
    *parents, attr = path.split(".")
    for parent in parents:
        owner = getattr(owner, parent)
    raw = owner.__dict__[attr]
    is_static = isinstance(raw, staticmethod)
    function = raw.__func__ if is_static else raw

    @functools.wraps(function)
    def timed(*args, **kwargs):
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            totals[name] += time.perf_counter() - start
            counts[name] += 1
    setattr(owner, attr, staticmethod(timed) if is_static else timed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("hdf")
    parser.add_argument("--engine", default="python")
    parser.add_argument("--kind", default="polygons")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import psutil
    totals, counts = defaultdict(float), defaultdict(int)
    for spec in STAGES:
        wrap(totals, counts, *spec)
    from ras_commander.hdf.HdfFluvialPluvial import HdfFluvialPluvial
    call = (HdfFluvialPluvial.generate_fluvial_pluvial_polygons if args.kind == "polygons"
            else HdfFluvialPluvial.calculate_fluvial_pluvial_boundary)
    started = time.perf_counter()
    frame = call(Path(args.hdf), engine=args.engine)
    wall = time.perf_counter() - started
    report = {"hdf": args.hdf, "engine": args.engine, "kind": args.kind, "rows": len(frame),
              "wall_seconds": wall, "stage_seconds": dict(totals), "stage_calls": dict(counts),
              "native_internal": frame.attrs.get("fluvial_native"),
              "peak_rss_bytes": psutil.Process().memory_info().peak_wset,
              "note": "wrapped wall seconds; nested stages overlap and are not additive"}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, default=str))


if __name__ == "__main__":
    main()
