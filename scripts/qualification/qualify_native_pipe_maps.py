"""Qualify native stored-map CPU mitigation on a staged, computed public model.

Creates a disposable project copy and fresh outputs. Does not compute a plan.
Native calls go through RasProcess.store_maps; no vendor binary is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import time
from pathlib import Path

import numpy as np
import psutil
import rasterio

from ras_commander import RasControl, RasPrj, RasProcess, StoreMapPerformanceOptions, init_ras_project


def digest(path):
    with Path(path).open("rb") as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
        return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="Complete, computed public project with staged dependencies")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--runtime", default="7.0.1")
    parser.add_argument("--output", required=True, type=Path, help="New disposable qualification directory")
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--controls", type=int, default=6)
    args = parser.parse_args()
    if args.repeats < 1 or args.controls < 1:
        raise ValueError("Repetition counts must be positive")
    if args.output.exists():
        raise FileExistsError("Use a new qualification output directory")
    inventory = RasControl.inspect_processes()
    project = args.output / "project"
    input_max = max((len(str(p.relative_to(args.project))) for p in args.project.rglob("*") if p.is_file()), default=0)
    if max(len(str(project.resolve())) + input_max, len(str(args.output.resolve())) + 96) > 240:
        raise ValueError("Choose a shorter qualification root to preserve native path headroom")
    shutil.copytree(args.project, project)
    for path in project.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    ras = RasPrj()
    init_ras_project(project, args.runtime, ras_object=ras, hide_intro=True)
    plan = ras.plan_df.loc[ras.plan_df.plan_number == str(args.plan).zfill(2)].iloc[0]
    hdf = Path(plan.HDF_Results_Path)
    if not hdf.is_file():
        raise ValueError("A completed result HDF is required; this harness does not run the solver")
    source_hdf = args.project / hdf.relative_to(project)
    if digest(source_hdf) != digest(hdf):
        raise RuntimeError("Result HDF changed while staging the disposable copy")
    rasmap = project / (ras.project_name + ".rasmap")
    hashes = {"result_hdf": digest(hdf), "rasmap": digest(rasmap)}
    affinity = psutil.Process().cpu_affinity()
    receipt = {"runtime": RasProcess.get_store_maps_runtime_provenance(ras_object=ras),
               "initial_inventory": inventory.to_dict(), "source_hashes": hashes,
               "caller_affinity": affinity, "cases": []}
    reference = {}
    for route, limit, count in (("aggregate", None, args.controls), ("aggregate", 1, args.repeats), ("independent", 1, args.repeats)):
        for repeat in range(count):
            row = {"route": route, "native_cpu_limit": limit, "repeat": repeat}
            started = time.monotonic()
            try:
                result = RasProcess.store_maps(str(args.plan).zfill(2), output_path=args.output / "maps" / f"{route}-{limit}-{repeat}",
                    profile="Max", render_mode="horizontal", depth=True, wse=True, velocity=False,
                    ras_object=ras, ras_version=args.runtime, timeout=120,
                    performance=StoreMapPerformanceOptions(max_workers=1 if route == "aggregate" else 2,
                        native_cpu_limit=limit, memory_policy="ignore", reserve_memory_mb=0, reserve_memory_fraction=0))
                row["products"] = {}
                for kind in ("depth", "wse"):
                    if len(result[kind]) != 1:
                        raise RuntimeError(f"Expected one {kind} product")
                    with rasterio.open(result[kind][0]) as dataset:
                        array = dataset.read(1, masked=True)
                        if not array.count() or dataset.crs is None:
                            raise RuntimeError(f"Empty or ungeoreferenced {kind}")
                        grid = (dataset.shape, dataset.transform, dataset.crs)
                        if kind not in reference:
                            reference[kind] = (array.copy(), grid)
                        else:
                            prior, prior_grid = reference[kind]
                            if grid != prior_grid or not np.array_equal(np.ma.getmaskarray(array), np.ma.getmaskarray(prior)) or not np.array_equal(array.compressed(), prior.compressed()):
                                raise RuntimeError(f"{kind} differs from the first successful reference")
                        row["products"][kind] = {"valid_pixels": int(array.count()), "shape": dataset.shape, "crs": str(dataset.crs)}
                row["success"] = True
            except Exception as error:
                row.update(success=False, error=str(error))
            row.update(seconds=time.monotonic() - started,
                       result_hdf_restored=digest(hdf) == hashes["result_hdf"],
                       source_hdf_unchanged=digest(source_hdf) == hashes["result_hdf"],
                       rasmap_restored=digest(rasmap) == hashes["rasmap"],
                       caller_affinity_restored=psutil.Process().cpu_affinity() == affinity)
            receipt["cases"].append(row)
            (args.output / "qualification.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n")
            print(json.dumps(row), flush=True)
            if not all(row[key] for key in ("result_hdf_restored", "source_hdf_unchanged", "rasmap_restored", "caller_affinity_restored")):
                raise RuntimeError("Restoration failed; qualification stopped")
    if any(not row["success"] for row in receipt["cases"] if row["native_cpu_limit"] == 1):
        raise SystemExit("One-CPU qualification failed; inspect retained evidence")


if __name__ == "__main__":
    main()
