"""Parse rigor_status.jsonl into convergence + sensitivity panels.

Studies (each varies ONE parameter from the reference ty700, 1 h, 1 s, Cv=0.70,
viscosity=100 Pa*s): timestep convergence, Cv, viscosity, yield stress.
"""
import json, sys, re
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Usage: python rigor_analysis.py [rigor_status.jsonl]  (defaults to CWD)
A = Path(".")
jl = Path(sys.argv[1]) if len(sys.argv) > 1 else A / "rigor_status.jsonl"
recs = []
for ln in jl.read_text().splitlines():
    try:
        r = json.loads(ln)
    except Exception:
        continue
    if r.get("phase") != "run" or r.get("variant") == "clear" or not r.get("results"):
        continue
    nn = r.get("nn") or {}
    dt = float(re.sub("SEC", "", str(r.get("comp_interval", "1SEC")), flags=re.I))
    recs.append({"dt": dt, "sim": r.get("sim_hours"),
                 "cv": nn.get("cv"), "ty": nn.get("user_yield"),
                 "mu": nn.get("user_viscosity"), **r["results"]})

def is_ref(r, **over):  # reference point with some fields overridden/free
    base = {"sim": 1.0, "dt": 1.0, "cv": 0.70, "ty": 700.0, "mu": 100.0}
    base.update(over)
    return all(r.get(k) == v for k, v in base.items() if v is not None)

def sweep(xkey, free):  # collect (x, metrics) varying xkey, others at reference
    fixed = {"sim": 1.0, "dt": 1.0, "cv": 0.70, "ty": 700.0, "mu": 100.0}
    del fixed[xkey]
    pts = {}
    for r in recs:
        if all(r.get(k) == v for k, v in fixed.items()) and r.get(xkey) is not None:
            pts[r[xkey]] = r
    return sorted(pts.items())

PANELS = [("dt", "computation interval (s)", "Timestep convergence"),
          ("cv", "Cv (volumetric concentration)", "Concentration / bulking"),
          ("mu", "Bingham viscosity (Pa·s)", "Viscosity"),
          ("ty", "Bingham yield stress (Pa)", "Yield stress")]
fig, axs = plt.subplots(2, 2, figsize=(13, 9))
print(f"{'study':14}{'x':>9}{'maxV':>7}{'maxD':>7}{'meanD':>7}{'wet':>6}{'inflowQ':>9}")
for ax, (xk, xl, ttl) in zip(axs.ravel(), PANELS):
    s = sweep(xk, None)
    if not s:
        ax.set_title(f"{ttl}: (no data)"); continue
    xs = [x for x, _ in s]
    ax.plot(xs, [r["max_vel_fps"] for _, r in s], "o-", label="max V (fps)", color="firebrick")
    ax.plot(xs, [r["mean_depth_ft"] for _, r in s], "s-", label="mean D (ft)", color="navy")
    ax2 = ax.twinx()
    ax2.plot(xs, [r["wet_cells"] for _, r in s], "^--", label="wet cells", color="green", alpha=0.6)
    ax2.set_ylabel("wet cells", color="green")
    if xk in ("mu",):
        ax.set_xscale("log")
    ax.set_xlabel(xl); ax.set_ylabel("fps / ft"); ax.set_title(ttl); ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    for x, r in s:
        print(f"{ttl[:13]:14}{x:>9}{r['max_vel_fps']:>7}{r['max_depth_ft']:>7}"
              f"{r['mean_depth_ft']:>7}{r['wet_cells']:>6}{r.get('inflow_peak_cfs','-'):>9}")
fig.suptitle("Ether Hollow debris-flow — convergence & parameter sensitivity (corrected bulking)\n"
             "reference: Bingham τy=700 Pa, Cv=0.70, μ=100 Pa·s, 1 h, 1 s; one parameter varied per panel",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(A / "rigor_sensitivity.png", dpi=110, bbox_inches="tight")
print("\nwrote rigor_sensitivity.png")
