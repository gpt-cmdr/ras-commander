"""Compare grid-anchor options for one child 2D area against its parent (point generation only, no solve).

Windows, HEC-RAS 6.6 (RasMapperLib through pythonnet) and this repository on the import path. The child HDF is
copied before any edit; the source files are not changed.

    python probe_grid_anchor.py PARENT.g##.hdf PARENT_AREA CHILD.g##.hdf CHILD_AREA OUT.json [HECRAS_DIR]

Modes (all on copies of the child geometry HDF):
  native       GeomMesh's RAS Mapper regeneration (lattice from the child's bounding box)
  a_shift      option (a): the child's Shift dx/dy attributes set to the phase shift, then regenerate
  b_self       control: anchored path with the child's own anchor (must equal `native`)
  b_anchor     option (b): anchored path with the parent's anchor (GeomMesh grid_anchor)
  c_translate  option (c): move breaklines, regions and structure lines by -v, regenerate, move points by +v, refill
               parent-lattice points in the uncovered perimeter strip

Metrics count child points strictly inside the child perimeter. "identical" means within 0.01 project units of a
parent cell center; "interior" excludes points within one base cell of the child perimeter.
"""

import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.affinity import translate
from shapely.geometry import Polygon

gm = importlib.import_module("ras_commander.geom.GeomMesh")
PA = "Geometry/2D Flow Areas"
FEATURES = (
    "Geometry/2D Flow Area Break Lines/Polyline Points",
    "Geometry/2D Flow Area Refinement Regions/Polygon Points",
    "Geometry/Structures/Centerline Points",
)
TOL = 0.01


def area_ring(path, area):
    with h5py.File(path, "r") as h:
        names = [n.decode().strip() for n in h[f"{PA}/Attributes"]["Name"]]
        i = names.index(area)
        info, pts = h[f"{PA}/Polygon Info"][()], h[f"{PA}/Polygon Points"][()]
    return i, pts[info[i][0] : info[i][0] + info[i][1]]


def cell_centers(path, area):
    with h5py.File(path, "r") as h:
        names = [n.decode().strip() for n in h[f"{PA}/Attributes"]["Name"]]
        n = int(h[f"{PA}/Attributes"][names.index(area)]["Cell Count"])
        return h[f"{PA}/{area}/Cells Center Coordinate"][:n]


def xy_of(points):
    return np.array([(float(points[i].X), float(points[i].Y)) for i in range(points.Count)])


def metrics(xy, P, parent_xy, parent_in, dx, anchor):
    xy = xy[shapely.contains_xy(P, xy[:, 0], xy[:, 1])]
    d1 = cKDTree(parent_xy).query(xy)[0]
    band = shapely.distance(shapely.points(xy), P.exterior) <= dx
    d2 = cKDTree(xy).query(parent_in)[0]
    pband = shapely.distance(shapely.points(parent_in), P.exterior) <= dx
    tx, ty = anchor.phase
    rx = np.abs(((xy[:, 0] - tx + dx / 2) % dx) - dx / 2)
    ry = np.abs(((xy[:, 1] - ty + dx / 2) % dx) - dx / 2)
    return {
        "points_inside": len(xy),
        "identical_share": round(float((d1 < TOL).mean()), 4),
        "identical_interior_share": round(float((d1[~band] < TOL).mean()), 4),
        "parent_reproduced_share": round(float((d2 < TOL).mean()), 4),
        "parent_reproduced_interior_share": round(float((d2[~pband] < TOL).mean()), 4),
        "on_parent_lattice_share": round(float(((rx < TOL) & (ry < TOL)).mean()), 4),
    }


def main(parent_hdf, parent_area, child_hdf, child_area, out_json, hecras_dir=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"):
    gm._load_dlls(hecras_dir)
    ns = gm._imports()
    work = Path(tempfile.mkdtemp(prefix="grid-anchor-probe-"))
    base = work / "child.hdf"
    shutil.copy2(child_hdf, base)
    fid, ring = area_ring(base, child_area)
    P = Polygon(ring)
    parent = gm._grid_anchor_from_hdf(parent_hdf, parent_area)
    child = gm._grid_anchor_from_hdf(base, child_area)
    dx = parent.spacing_dx
    pxy = cell_centers(parent_hdf, parent_area)
    pin = pxy[shapely.contains_xy(P, pxy[:, 0], pxy[:, 1])]
    ax = (parent.phase[0] - child.phase[0]) % dx
    ay = (parent.phase[1] - child.phase[1]) % dx
    vx = ax - dx if ax > dx / 2 else ax
    vy = ay - dx if ay > dx / 2 else ay
    res = {"spacing": dx, "phase_shift": [ax, ay], "translation": [vx, vy], "parent_points_inside": len(pin)}
    pts = {}

    def run(name, path, **kw):
        ev = {}
        xy = xy_of(gm._generate_seeds_via_net(str(path), ns, fid=fid, evidence=ev, **kw))
        pts[name] = xy
        res[name] = metrics(xy, P, pxy, pin, dx, parent)
        print(name, res[name], flush=True)

    run("native", base)
    t = work / "a_shift.hdf"
    shutil.copy2(base, t)
    with h5py.File(t, "r+") as h:
        at = h[f"{PA}/Attributes"][()]
        at["Shift dx"][fid], at["Shift dy"][fid] = ax, ay
        h[f"{PA}/Attributes"][...] = at
    run("a_shift", t)
    run("b_self", base, grid_anchor=child)
    a, b = pts["native"], pts["b_self"]
    res["b_self_equals_native"] = bool(len(a) == len(b) and cKDTree(a).query(b)[0].max() < 1e-6)
    run("b_anchor", base, grid_anchor=parent)
    t = work / "c_translate.hdf"
    shutil.copy2(base, t)
    with h5py.File(t, "r+") as h:
        for ds in FEATURES:
            if ds in h and h[ds].shape[0]:
                arr = h[ds][()]
                arr[:, 0] -= vx
                arr[:, 1] -= vy
                h[ds][...] = arr
    raw = xy_of(gm._generate_seeds_via_net(str(t), ns, fid=fid)) + np.array([vx, vy])
    inside = shapely.contains_xy(P, raw[:, 0], raw[:, 1])
    tx, ty = parent.phase
    lat = (np.abs(((raw[:, 0] - tx + dx / 2) % dx) - dx / 2) < TOL) & (np.abs(((raw[:, 1] - ty + dx / 2) % dx) - dx / 2) < TOL)
    gx = np.arange(np.floor((P.bounds[0] - tx) / dx) * dx + tx, P.bounds[2] + dx, dx)
    gy = np.arange(np.floor((P.bounds[1] - ty) / dx) * dx + ty, P.bounds[3] + dx, dx)
    lattice = np.stack(np.meshgrid(gx, gy), axis=-1).reshape(-1, 2)
    lattice = lattice[shapely.contains_xy(P, lattice[:, 0], lattice[:, 1])]
    strip = lattice[~shapely.contains_xy(translate(P, vx, vy), lattice[:, 0], lattice[:, 1])]
    feat = raw[inside & ~lat]
    far = cKDTree(feat).query(strip)[0] > dx / 2 if len(feat) and len(strip) else np.ones(len(strip), bool)
    xy = np.vstack([raw[inside], strip[far]])
    res["c_translate"] = {"refill": int(far.sum()), **metrics(xy, P, pxy, pin, dx, parent)}
    print("c_translate", res["c_translate"], flush=True)
    Path(out_json).write_text(json.dumps(res, indent=1))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
