"""Debris-flow hazard products from the variant result HDFs.

Per cell: max depth, max velocity, time-synchronized depth x velocity intensity
(max over time of d(t)*v(t), not max(d)*max(v)), hazard class, and first-wetting
arrival time. Cell velocity is the max |face velocity| over a cell's faces.

Hazard intensity classes (debris-flow, Swiss/Austrian style, converted to US ft):
  HIGH : depth >= 3.28 ft  OR  d*v >= 10.76 ft^2/s   (>=1 m / 1 m^2/s)
  MED  : depth >= 1.64 ft  OR  d*v >=  5.38 ft^2/s   (>=0.5 m / 0.5 m^2/s)
  LOW  : wet (depth > 0.1 ft) but below MED
"""
import h5py, numpy as np, rasterio
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, ListedColormap, BoundaryNorm
from pathlib import Path
import sys

# A = directory holding EtherHollow.g01.hdf + result_<variant>.p01.hdf + the feet
# terrain (defaults to CWD). Usage: python hazard_maps.py [results_dir] [terrain.tif]
A = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
TERRAIN = Path(sys.argv[2]) if len(sys.argv) > 2 else A / "EtherHollow_terrain_ft.tif"
G = A / "EtherHollow.g01.hdf"
area = "DebrisFlowArea"
base = f"Geometry/2D Flow Areas/{area}"
sumb = f"Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas/{area}"
tsb = f"Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}"
VARIANTS = [("clear", "result_clear.p01.hdf", "Clear water"),
            ("ty700", "result_bingham_ty700.p01.hdf", "Bingham τy=700 Pa"),
            ("ty2500", "result_bingham_ty2500.p01.hdf", "Bingham τy=2500 Pa")]
ACRE = 43560.0
HI_D, HI_I = 3.28, 10.76
MD_D, MD_I = 1.64, 5.38

with h5py.File(G, "r") as g:
    cc = g[f"{base}/Cells Center Coordinate"][:]
    cmin = g[f"{base}/Cells Minimum Elevation"][:]
    csa = g[f"{base}/Cells Surface Area"][:]
    fci = g[f"{base}/Faces Cell Indexes"][:]
    bcp = g["Geometry/Boundary Condition Lines/Polyline Points"][:]
    bpi = g["Geometry/Boundary Condition Lines/Polyline Info"][:]
C = len(cmin)


def cell_metrics(hdf):
    with h5py.File(hdf, "r") as f:
        WS = f[f"{tsb}/Water Surface"][:]          # (T, C)
        FV = np.abs(f[f"{tsb}/Face Velocity"][:])  # (T, F)
    T = WS.shape[0]
    # dry cells carry NaN / sentinel water-surface in the time series -> depth 0
    depth_t = WS[:, :C] - cmin[None, :]
    depth_t = np.nan_to_num(depth_t, nan=0.0, posinf=0.0, neginf=0.0)
    depth_t = np.clip(depth_t, 0, None)
    # per-cell velocity each step = max |face velocity| over the cell's faces
    a, b = fci[:, 0], fci[:, 1]
    va, vb = a >= 0, b >= 0
    cellvel = np.zeros((T, C), np.float32)
    for t in range(T):
        cv = np.zeros(C, np.float32)
        np.maximum.at(cv, a[va], FV[t, va])
        np.maximum.at(cv, b[vb], FV[t, vb])
        cellvel[t] = cv
    inten_t = depth_t * cellvel                    # time-synchronized d*v
    maxd = depth_t.max(0)
    maxv = cellvel.max(0)
    maxi = inten_t.max(0)
    wet_t = depth_t > 0.5
    ever = wet_t.any(0)
    arr = np.where(ever, wet_t.argmax(0).astype(float), np.nan)  # minutes (1-min output)
    return maxd, maxv, maxi, arr


def hazard_class(maxd, maxi):
    cls = np.zeros(C, int)               # 0 dry,1 low,2 med,3 high
    wet = maxd > 0.1
    cls[wet] = 1
    cls[(maxd >= MD_D) | (maxi >= MD_I)] = 2
    cls[(maxd >= HI_D) | (maxi >= HI_I)] = 3
    return cls


# terrain hillshade backdrop
ds = rasterio.open(TERRAIN)
dem = ds.read(1).astype(float); dem[dem == ds.nodata] = np.nan
ext = [ds.bounds.left, ds.bounds.right, ds.bounds.bottom, ds.bounds.top]
hs = LightSource(315, 45).hillshade(np.nan_to_num(dem, nan=np.nanmin(dem)),
                                    vert_exag=2, dx=ds.res[0], dy=ds.res[1])
ds.close()


def draw_bc(ax):
    o = 0
    for k, info in enumerate(bpi):
        n = info[2]; seg = bcp[o:o + n]; o += n
        ax.plot(seg[:, 0], seg[:, 1], lw=2, color=["lime", "magenta"][k % 2])


metrics = {k: cell_metrics(A / h) for k, h, _ in VARIANTS}

# ---- Figure 1: hazard-class maps ----
hzcol = ListedColormap(["#ffe680", "#ff9933", "#cc0000"])
fig, axs = plt.subplots(1, 3, figsize=(19, 7), sharex=True, sharey=True)
rows = []
for ax, (k, h, ttl) in zip(axs, VARIANTS):
    maxd, maxv, maxi, arr = metrics[k]
    cls = hazard_class(maxd, maxi)
    ax.imshow(hs, extent=ext, cmap="gray", origin="upper")
    for lvl, col in [(1, "#ffe680"), (2, "#ff9933"), (3, "#cc0000")]:
        m = cls == lvl
        ax.scatter(cc[m, 0], cc[m, 1], s=7, c=col, marker="s", linewidths=0)
    draw_bc(ax)
    a_lo = csa[cls == 1].sum() / ACRE; a_md = csa[cls == 2].sum() / ACRE
    a_hi = csa[cls == 3].sum() / ACRE
    ax.set_title(f"{ttl}\nhazard area: low {a_lo:.1f} / med {a_md:.1f} / high {a_hi:.1f} ac",
                 fontsize=11)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    rows.append((k, a_lo, a_md, a_hi, a_lo + a_md + a_hi, float(maxi.max()),
                 float(maxv.max()), float(maxd.max())))
from matplotlib.patches import Patch
fig.legend(handles=[Patch(color="#ffe680", label="Low"), Patch(color="#ff9933", label="Medium"),
                    Patch(color="#cc0000", label="High")], loc="lower center", ncol=3)
fig.suptitle("Ether Hollow debris-flow HAZARD INTENSITY (depth x velocity, time-synchronized)\n"
             "classes: High >=3.3 ft or 10.8 ft²/s | Med >=1.6 ft or 5.4 ft²/s",
             fontsize=12)
plt.savefig(A / "hazard_intensity.png", dpi=105, bbox_inches="tight")
plt.close()

# ---- Figure 2: arrival time ----
fig, axs = plt.subplots(1, 3, figsize=(19, 7), sharex=True, sharey=True)
for ax, (k, h, ttl) in zip(axs, VARIANTS):
    maxd, maxv, maxi, arr = metrics[k]
    ax.imshow(hs, extent=ext, cmap="gray", origin="upper")
    m = np.isfinite(arr)
    sc = ax.scatter(cc[m, 0], cc[m, 1], s=7, c=arr[m], cmap="plasma", vmin=0, vmax=120, marker="s")
    draw_bc(ax)
    amax = np.nanmax(arr) if m.any() else 0
    ax.set_title(f"{ttl}\nfront reaches outflow by ~{amax:.0f} min", fontsize=11)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
fig.colorbar(sc, ax=axs, shrink=0.6, label="arrival time (min, depth>0.5 ft)", pad=0.01)
fig.suptitle("Ether Hollow debris-flow ARRIVAL TIME (first wetting)\n"
             "higher yield stress slows propagation", fontsize=12)
plt.savefig(A / "hazard_arrival.png", dpi=105, bbox_inches="tight")
plt.close()

print("wrote hazard_intensity.png, hazard_arrival.png")
print(f"\n{'variant':22s}{'low':>7}{'med':>7}{'high':>7}{'tot(ac)':>9}"
      f"{'maxI':>7}{'maxV':>7}{'maxD':>7}")
for ttl, lo, md, hi, tot, mi, mv, md_ in rows:
    print(f"{ttl:22s}{lo:7.1f}{md:7.1f}{hi:7.1f}{tot:9.1f}{mi:7.1f}{mv:7.1f}{md_:7.1f}")
