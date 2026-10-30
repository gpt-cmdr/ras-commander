"""Regenerate the Muncie Automated Flow Optimization fixture (needs HEC-RAS 7.0.1).

Usage: python make_fixture.py <Muncie example folder> <work folder>

Copies the public HEC-RAS 7.0 example "2D Unsteady Flow Hydraulics/Muncie" to
<work folder>, adds one reference point to geometry g02, clones plan p03 with
native flow optimization enabled through RasFlowOptimization, computes the new
plan with HEC-RAS 7.0.1 through RasCmdr, then writes the plan text and an
excerpt of the plan HDF (see EXCERPT) next to this script.
"""
import hashlib
import shutil
import sys
from pathlib import Path

from ras_commander import RasCmdr, RasFlowOptimization, init_ras_project
from ras_commander.geom.GeomReferenceFeatures import GeomReferenceFeatures

POINT = {"name": "FlowOptPt", "x": 407550.0, "y": 1804350.0}  # a wet 2D cell centre
SETTINGS = dict(mode="stage", reference_location=POINT["name"], target_value=946.0,
                tolerance=0.1, initial_ratio=1.0, min_ratio=0.5, max_ratio=2.0,
                max_iterations=5, hydrographs=[])


def main(source, work):
    source, work = Path(source), Path(work)
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(source, work)
    GeomReferenceFeatures.add_reference_points(work / "Muncie.g02", [POINT])
    for stale in ("Muncie.g02.hdf", "Muncie.c02"):
        (work / stale).unlink(missing_ok=True)
    ras = init_ras_project(work, "7.0.1")
    plan = RasFlowOptimization.copy_plan_with_optimization(
        "03", new_plan_shortid="FlowOpt", new_title="Flow Optimization", ras_object=ras,
        **SETTINGS)
    print("plan", plan)
    result = RasFlowOptimization.compute_plan_and_get_trials(plan, ras_object=ras)
    print(result["compute_result"])
    print(result["trial_results"].to_string())
    return work, plan


EXCERPT = (
    "Plan Data/Flow Ratio Optimization",
    "Results/Unsteady/Flow Optimization Hydro Scaling",
    "Results/Summary/Compute Messages (text)",
)


def excerpt(plan_hdf, target):
    """Copy the root attributes and the EXCERPT objects (layout unchanged) to target."""
    import h5py

    with h5py.File(plan_hdf, "r") as src, h5py.File(target, "w") as dst:
        for key, value in src.attrs.items():
            dst.attrs[key] = value
        for name in EXCERPT:
            parent = name.rsplit("/", 1)[0]
            dst.require_group(parent)
            src.copy(src[name], dst[parent], name=name.rsplit("/", 1)[1])


if __name__ == "__main__":
    work, plan = main(*sys.argv[1:3])
    here = Path(__file__).resolve().parent
    shutil.copyfile(work / f"Muncie.p{plan}", here / f"Muncie.p{plan}")
    excerpt(work / f"Muncie.p{plan}.hdf", here / f"Muncie.p{plan}.flowopt.hdf")
    for path in [work / f"Muncie.p{plan}.hdf", here / f"Muncie.p{plan}", here / f"Muncie.p{plan}.flowopt.hdf"]:
        print(path.name, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
