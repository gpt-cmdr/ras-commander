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


def _continuous_paths(segments, snap_ft=2.0, max_paths=1):
    """Stitch TauDEM stream segments into CONTINUOUS centerlines.

    ``linemerge`` splits the main stem at every confluence (a degree-3 node), so
    picking the longest merged pieces yields disjoint chunks with gaps. Instead,
    build a graph on the segment endpoints (snapped to ``snap_ft``) and extract the
    longest path (the main stem, head→outlet) as one continuous polyline; repeat on
    the remaining components for up to ``max_paths`` centerlines. Returns a list of
    coordinate lists, longest first.
    """
    from collections import defaultdict

    def snap(p):
        return (round(p[0] / snap_ft) * snap_ft, round(p[1] / snap_ft) * snap_ft)

    def explode(geoms):
        for g in geoms:
            if g is None or g.is_empty:
                continue
            for ln in (g.geoms if g.geom_type == "MultiLineString" else [g]):
                if ln.length > 0 and len(ln.coords) >= 2:
                    yield list(ln.coords)

    adj = defaultdict(list)  # node -> [(neighbor, ordered_coords, length)]
    for coords in explode(segments):
        a, b = snap(coords[0]), snap(coords[-1])
        if a == b:
            continue
        length = sum(((coords[i][0] - coords[i + 1][0]) ** 2 +
                      (coords[i][1] - coords[i + 1][1]) ** 2) ** 0.5
                     for i in range(len(coords) - 1))
        adj[a].append((b, coords, length))
        adj[b].append((a, coords[::-1], length))

    def farthest(start):
        # weighted DFS over a (near-)tree component: node with max cumulative distance
        best, best_d = start, 0.0
        parent, pedge, seen = {start: None}, {start: None}, {start}
        stack = [(start, 0.0)]
        while stack:
            node, d = stack.pop()
            if d > best_d:
                best_d, best = d, node
            for nb, ecoords, length in adj[node]:
                if nb not in seen:
                    seen.add(nb)
                    parent[nb], pedge[nb] = node, ecoords
                    stack.append((nb, d + length))
        return best, best_d, parent, pedge, seen

    def stitch(end, parent, pedge):
        segs, node = [], end
        while parent[node] is not None:
            segs.append(pedge[node])
            node = parent[node]
        segs.reverse()
        out = []
        for s in segs:
            out.extend(s if not out else s[1:])
        return out

    paths, visited = [], set()
    for node0 in list(adj):
        if node0 in visited:
            continue
        u, _, _, _, comp = farthest(node0)          # one endpoint of the diameter
        v, dist, parent, pedge, _ = farthest(u)     # the far endpoint
        visited |= comp
        if dist > 0:
            paths.append((dist, stitch(v, parent, pedge)))
    paths.sort(key=lambda p: p[0], reverse=True)
    return [c for _, c in paths[:max_paths]]


def _plot_delineation(dem, domain_geom, net, defs, out_png):
    """Diagnostic figure: terrain hillshade + 2D domain + all streams + the
    continuous main-stem centerline(s) authored as breaklines."""
    import numpy as np
    import rasterio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from shapely.geometry import LineString

    with rasterio.open(dem) as ds:
        band = ds.read(1).astype(float)
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        ext = [ds.bounds.left, ds.bounds.right, ds.bounds.bottom, ds.bounds.top]
        hs = LightSource(315, 45).hillshade(np.nan_to_num(band, nan=np.nanmin(band)),
                                            vert_exag=2, dx=ds.res[0], dy=ds.res[1])
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(hs, extent=ext, cmap="gray", origin="upper")
    for geom in net.geometry:                       # all TauDEM streams (context)
        for ln in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
            xs, ys = ln.xy
            ax.plot(xs, ys, color="white", lw=0.6, alpha=0.7, zorder=2)
    dx, dy = domain_geom.exterior.xy
    ax.plot(dx, dy, color="cyan", lw=1.2, zorder=3, label="2D domain")
    for i, d in enumerate(defs):
        c = np.array(d["coords"])
        ax.plot(c[:, 0], c[:, 1], color=["red", "orange", "yellow"][i % 3], lw=2.2,
                zorder=4, label=f"{d['name']} ({_len_ft(c):.0f} ft)")
    ax.set_aspect("equal")
    ax.set_xlabel("ft")
    ax.set_ylabel("ft")
    ax.set_title("TauDEM channel delineation — continuous main-stem centerline\n"
                 "(white = all streams, red = thalweg used as the mesh breakline)")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"[delineate] wrote diagnostic figure -> {out_png}")


def _len_ft(coords):
    import numpy as np
    c = np.asarray(coords)
    return float(np.sum(np.hypot(*np.diff(c, axis=0).T))) if len(c) > 1 else 0.0


def delineate(dem, domain_geom, out_json, *, stream_area_km2=0.04,
              simplify_ft=10.0, max_lines=1, processes=4, taudem_dir=None,
              workdir=None, plot_png=None):
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
    # Extract CONTINUOUS main-stem centerline(s) from the clipped network graph
    # (linemerge alone splits the trunk at every confluence -> gaps). See _continuous_paths.
    from shapely.geometry import LineString
    clipped = list(net.clip(domain_geom).geometry.values)
    paths = _continuous_paths(clipped, snap_ft=max(res * unit_m / 0.3048 * 2, 2.0),
                              max_paths=max_lines)
    defs = [{"name": f"Thalweg{i}",
             "coords": [[float(x), float(y)] for x, y in
                        LineString(coords).simplify(simplify_ft, preserve_topology=True).coords]}
            for i, coords in enumerate(paths) if len(coords) >= 2]
    Path(out_json).write_text(json.dumps(defs), encoding="utf-8")
    print(f"[delineate] threshold {stream_area_km2} km2 = {thresh} cells; "
          f"wrote {len(defs)} continuous centerline(s) "
          f"({[len(d['coords']) for d in defs]} verts) -> {out_json}")
    if plot_png:
        _plot_delineation(dem, domain_geom, net.clip(domain_geom), defs, plot_png)
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
    ap.add_argument("--max-lines", type=int, default=1,
                    help="number of continuous centerlines to keep (main stem first)")
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--taudem-dir", type=Path, default=None,
                    help="dir holding the TauDEM .exe files (else found on PATH)")
    ap.add_argument("--plot", type=Path, default=None,
                    help="also write a diagnostic PNG (hillshade + domain + streams + thalweg)")
    args = ap.parse_args()

    from shapely.geometry import Polygon
    if args.domain.suffix.lower() == ".json":
        domain = Polygon(json.loads(args.domain.read_text(encoding="utf-8")))
    else:
        import geopandas as gpd
        domain = gpd.read_file(args.domain).geometry.iloc[0]
    delineate(args.dem, domain, args.out, stream_area_km2=args.stream_area_km2,
              simplify_ft=args.simplify_ft, max_lines=args.max_lines,
              processes=args.processes, taudem_dir=args.taudem_dir, plot_png=args.plot)


if __name__ == "__main__":
    main()
