"""delineate_channels.py — TauDEM channel-centerline delineation for 2D breaklines.

Runs the standard TauDEM stream-network sequence on a (projected) DEM and writes
the channel centerlines, clipped to the 2D-area domain and simplified, as
``channel_breakline_ft.json`` for ``ether_hollow_debris_flow.py --phase build
--breaklines`` to author as mesh breaklines along the thalweg.

    PitRemove -> D8FlowDir -> AreaD8 -> Threshold -> StreamNet -> net.shp

Stream definition is a flow-accumulation threshold (``--stream-area-km2``).

Prerequisites (external, not pip):
  * TauDEM 5.x binaries on PATH (PitRemove, D8FlowDir, AreaD8, Threshold,
    StreamNet) — https://hydrology.usu.edu/taudem/
  * MS-MPI (mpiexec) on PATH for multi-process runs (optional; falls back to a
    single process if absent).
  * GDAL + geopandas/rasterio/shapely/pyproj.

Run this where TauDEM is installed (e.g. locally); stage the resulting JSON to
the build host. The DEM should be projected; the centerlines are written in the
DEM's CRS (use the model's feet CRS so they drop straight into the .g## text).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

# TauDEM CLI name -> the on-disk executable basename
_EXE = {"PitRemove": "PitRemove", "D8FlowDir": "D8FlowDir", "AreaD8": "AreaD8",
        "Threshold": "Threshold", "StreamNet": "StreamNet"}


def _which(name: str, exe_dir: Path | None) -> str:
    if exe_dir:
        for cand in (exe_dir / name, exe_dir / f"{name}.exe"):
            if cand.exists():
                return str(cand)
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if not found:
        raise FileNotFoundError(f"TauDEM executable '{name}' not on PATH "
                                "(install TauDEM 5.x or pass --taudem-dir)")
    return found


def _run(name, args, outputs, *, processes, exe_dir):
    exe = _which(_EXE[name], exe_dir)
    mpi = shutil.which("mpiexec") or shutil.which("mpiexec.exe")
    cmd = ([mpi, "-n", str(processes), exe] if (mpi and processes > 1) else [exe]) + args
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    for o in outputs:
        if not Path(o).exists():
            raise RuntimeError(f"{name} did not produce {o}")


def delineate(dem, domain_geom, out_json, *, stream_area_km2=0.04,
              simplify_ft=10.0, max_lines=3, processes=4, taudem_dir=None,
              workdir=None):
    """Run TauDEM on ``dem`` and write the top channel centerlines (clipped to
    ``domain_geom``, simplified) to ``out_json``. Returns the list of breakline
    definitions ``[{"name", "coords"}, ...]``."""
    import rasterio
    import geopandas as gpd
    from shapely.ops import unary_union, linemerge

    dem = Path(dem)
    wd = Path(workdir) if workdir else dem.parent / "taudem"
    wd.mkdir(parents=True, exist_ok=True)
    exe_dir = Path(taudem_dir) if taudem_dir else None

    with rasterio.open(dem) as ds:
        res = abs(ds.transform.a)
        crs = ds.crs
    # cell area in km2 from the linear unit (ft if a feet CRS, else m).
    # rasterio's CRS exposes the linear unit via .linear_units (not pyproj's .axis_info).
    unit_name = (getattr(crs, "linear_units", "") or "").lower()
    unit_m = 0.3048 if (crs and crs.is_projected and "foot" in unit_name) else 1.0
    cell_km2 = (res * unit_m / 1000.0) ** 2
    thresh = max(int(stream_area_km2 / max(cell_km2, 1e-12)), 1)

    f = lambda n: str(wd / n)
    _run("PitRemove", ["-z", str(dem), "-fel", f("fel.tif")], [f("fel.tif")],
         processes=processes, exe_dir=exe_dir)
    _run("D8FlowDir", ["-fel", f("fel.tif"), "-p", f("p.tif"), "-sd8", f("sd8.tif")],
         [f("p.tif")], processes=processes, exe_dir=exe_dir)
    _run("AreaD8", ["-p", f("p.tif"), "-ad8", f("ad8.tif"), "-nc"],
         [f("ad8.tif")], processes=processes, exe_dir=exe_dir)
    _run("Threshold", ["-ssa", f("ad8.tif"), "-src", f("src.tif"), "-thresh", str(float(thresh))],
         [f("src.tif")], processes=processes, exe_dir=exe_dir)
    _run("StreamNet", ["-fel", f("fel.tif"), "-p", f("p.tif"), "-ad8", f("ad8.tif"),
                       "-src", f("src.tif"), "-ord", f("ord.tif"), "-tree", f("tree.dat"),
                       "-coord", f("coord.dat"), "-net", f("net.shp"), "-w", f("w.tif")],
         [f("net.shp")], processes=processes, exe_dir=exe_dir)

    net = gpd.read_file(wd / "net.shp")
    if net.crs is None and crs is not None:
        net = net.set_crs(crs, allow_override=True)
    merged = linemerge(unary_union(net.clip(domain_geom).geometry.values))
    lines = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    lines = sorted([ln for ln in lines if ln.length > 0], key=lambda ln: ln.length, reverse=True)
    defs = [{"name": f"Thalweg{i}",
             "coords": [[float(x), float(y)] for x, y in
                        ln.simplify(simplify_ft, preserve_topology=True).coords]}
            for i, ln in enumerate(lines[:max_lines])]
    Path(out_json).write_text(json.dumps(defs), encoding="utf-8")
    print(f"[delineate] threshold {stream_area_km2} km2 = {thresh} cells; "
          f"{len(lines)} channel(s) in domain; wrote {len(defs)} centerline(s) "
          f"({[len(d['coords']) for d in defs]} verts) -> {out_json}")
    return defs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dem", required=True, type=Path, help="projected DEM (feet CRS preferred)")
    ap.add_argument("--domain", required=True, type=Path,
                    help="2D-area perimeter: a polygon shapefile/GeoPackage, or a "
                         "JSON ring [[x,y],...] (basin_perimeter_ft.json)")
    ap.add_argument("--out", type=Path, default=Path("channel_breakline_ft.json"))
    ap.add_argument("--stream-area-km2", type=float, default=0.04)
    ap.add_argument("--simplify-ft", type=float, default=10.0)
    ap.add_argument("--max-lines", type=int, default=3)
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--taudem-dir", type=Path, default=None,
                    help="dir holding the TauDEM .exe files (else found on PATH)")
    args = ap.parse_args()

    from shapely.geometry import Polygon
    if args.domain.suffix.lower() == ".json":
        domain = Polygon(json.loads(args.domain.read_text(encoding="utf-8")))
    else:
        import geopandas as gpd
        domain = gpd.read_file(args.domain).geometry.iloc[0]
    delineate(args.dem, domain, args.out, stream_area_km2=args.stream_area_km2,
              simplify_ft=args.simplify_ft, max_lines=args.max_lines,
              processes=args.processes, taudem_dir=args.taudem_dir)


if __name__ == "__main__":
    main()
