"""Plot the Ether Hollow sensitivity matrix from sensitivity_status.jsonl.

Two 1-D sweeps:
  - Yield sweep at n=0.08:  clear(τy=0), 700, 1500, 2500 Pa
  - Roughness sweep at τy=700:  n = 0.06, 0.08, 0.10
Metrics: max velocity (fps), mean depth (ft), runout extent (wet cells).
"""
import json, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Usage: python sensitivity_plot.py [sensitivity_status.jsonl]  (defaults to CWD)
A = Path(".")
jl = Path(sys.argv[1]) if len(sys.argv) > 1 else A / "sensitivity_status.jsonl"
CELL_AC = 33.0 * 33.0 / 43560.0      # nominal cell area -> acres (extent proxy)

recs = []
for line in jl.read_text().splitlines():
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("phase") != "run" or not r.get("results"):
        continue
    v = r["variant"]
    ty = 0.0 if v == "clear" else float(v.replace("bingham_ty", ""))
    recs.append({"n": round(float(r.get("mannings_n", 0.08)), 2), "ty": ty,
                 **r["results"]})

def series(filt, key, xkey):
    pts = sorted([(r[xkey], r[key]) for r in recs if filt(r)])
    # de-dup on x (keep last)
    d = {}
    for x, y in pts:
        d[x] = y
    xs = sorted(d)
    return xs, [d[x] for x in xs]

fig, axs = plt.subplots(2, 3, figsize=(15, 8))
METRICS = [("max_vel_fps", "max velocity (fps)"),
           ("mean_depth_ft", "mean depth (ft)"),
           ("wet_cells", "runout extent (wet cells)")]

# Row 0: yield sweep at n=0.08
for j, (key, lbl) in enumerate(METRICS):
    xs, ys = series(lambda r: abs(r["n"] - 0.08) < 1e-6, key, "ty")
    axs[0, j].plot(xs, ys, "o-", color="firebrick")
    axs[0, j].set_xlabel("Bingham yield stress τy (Pa)  [0 = clear water]")
    axs[0, j].set_ylabel(lbl); axs[0, j].grid(alpha=0.3)
    axs[0, j].set_title(f"Yield sweep (n=0.08): {lbl}", fontsize=10)
    for x, y in zip(xs, ys):
        axs[0, j].annotate(f"{y:g}", (x, y), fontsize=8, xytext=(0, 5),
                           textcoords="offset points", ha="center")

# Row 1: roughness sweep at τy=700
for j, (key, lbl) in enumerate(METRICS):
    xs, ys = series(lambda r: abs(r["ty"] - 700) < 1e-6, key, "n")
    axs[1, j].plot(xs, ys, "s-", color="navy")
    axs[1, j].set_xlabel("Manning's n  [τy = 700 Pa]")
    axs[1, j].set_ylabel(lbl); axs[1, j].grid(alpha=0.3)
    axs[1, j].set_title(f"Roughness sweep (τy=700): {lbl}", fontsize=10)
    for x, y in zip(xs, ys):
        axs[1, j].annotate(f"{y:g}", (x, y), fontsize=8, xytext=(0, 5),
                           textcoords="offset points", ha="center")

fig.suptitle("Ether Hollow debris-flow sensitivity — Bingham yield stress & Manning's n\n"
             "(2 h sim, Cv=0.70 bulked 3.33×, μ=100 Pa·s)", fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(A / "sensitivity.png", dpi=110, bbox_inches="tight")
print("wrote sensitivity.png\n")

# table
print(f"{'n':>5} {'ty(Pa)':>7} {'maxV':>6} {'maxD':>6} {'meanD':>6} {'wetCells':>9} {'~ac':>6}")
for r in sorted(recs, key=lambda r: (r["n"], r["ty"])):
    print(f"{r['n']:>5} {r['ty']:>7.0f} {r.get('max_vel_fps','-'):>6} "
          f"{r.get('max_depth_ft','-'):>6} {r.get('mean_depth_ft','-'):>6} "
          f"{r.get('wet_cells','-'):>9} {r.get('wet_cells',0)*CELL_AC:>6.1f}")
