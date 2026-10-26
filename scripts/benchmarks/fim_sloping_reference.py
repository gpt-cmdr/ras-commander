"""Capture native sloping references on a disposable computed 2D project copy.

This measures native mode differences and repeatability, not Rust sloping parity.
Use an installed HEC-RAS runtime and a public computed example project.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import shutil
import time

import numpy as np
import psutil
import rasterio

from ras_commander import (
    RasFim, RasMap, RasProcess, StoreMapPerformanceOptions, init_ras_project,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", default="05")
    parser.add_argument("--version", default="7.0.1")
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    if project.suffix.lower() != ".prj":
        parser.error("--project must name the computed project's .prj file")
    output = args.output.resolve()
    if output == project.parent or project.parent in output.parents:
        parser.error("--output must be outside the source project")
    if args.cpus < 1 or args.repetitions < 1:
        parser.error("--cpus and --repetitions must be positive")
    output.mkdir(parents=True, exist_ok=False)
    process = psutil.Process()
    previous_affinity = process.cpu_affinity()
    process.cpu_affinity(previous_affinity[:args.cpus])
    receipt = {
        "purpose": "native mode differences and repeatability; no Rust sloping implementation",
        "cpus": process.cpu_affinity(), "runtime_version": args.version,
        "source_project": str(project), "runs": [], "comparisons": [],
        "option_scope": "Bare mode names only; helper defaults, not a flag-combination matrix",
    }
    handler = logging.FileHandler(output / "native-debug.log", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    logging.getLogger("ras_commander").addHandler(handler)
    logging.getLogger("ras_commander.RasProcess").setLevel(logging.DEBUG)

    def save():
        # Convert nonfinite metrics to JSON null without changing source receipts.
        def clean(value):
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, (tuple, list)):
                return [clean(v) for v in value]
            if isinstance(value, float) and not np.isfinite(value):
                return None
            return value
        (output / "reference.json").write_text(
            json.dumps(clean(receipt), indent=2, allow_nan=False), encoding="utf-8",
        )

    try:
        model = output / "model"
        shutil.copytree(project.parent, model)
        ras = init_ras_project(
            model / project.name, args.version, ras_object="new",
            hide_intro=True, load_results_summary=False,
        )
        plan = ras.plan_df.loc[ras.plan_df.plan_number == args.plan.zfill(2)]
        if len(plan) != 1:
            raise ValueError("Select exactly one computed plan")
        hdf = Path(plan.iloc[0]["HDF_Results_Path"])
        with hdf.open("rb") as stream:
            receipt["hdf_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        cells = RasFim.get_cells_from_plan_hdf(hdf, mesh_name="*")
        receipt["physical_cells"] = len(cells)
        receipt["runtime"] = RasProcess.get_store_maps_runtime_provenance(ras)
        receipt["source_render_options"] = RasMap.get_water_surface_render_mode(ras_object=ras)
        rasmap = model / project.with_suffix(".rasmap").name
        original = rasmap.read_bytes()
        for iteration in range(args.repetitions):
            for mode in ("horizontal", "sloping", "slopingPretty"):
                record = {"iteration": iteration, "mode": mode}
                receipt["runs"].append(record)
                started = time.perf_counter()
                try:
                    paths = RasProcess.store_maps(
                        args.plan, output_path=output / f"{iteration:02d}-{mode}",
                        profile="Max", render_mode=mode, depth=True, wse=True,
                        velocity=False, ras_object=ras, ras_version=args.version,
                        fix_georef=True, timeout=180,
                        performance=StoreMapPerformanceOptions(max_workers=1),
                    )
                    record["generation_seconds"] = time.perf_counter() - started
                    products = {}
                    for band in ("depth", "wse"):
                        tifs = [Path(p) for p in paths[band] if Path(p).suffix.lower() == ".tif"]
                        if len(tifs) != 1:
                            raise ValueError("Reference requires exactly one TIFF per band")
                        with rasterio.open(tifs[0]) as src:
                            values = src.read(1, masked=True)
                            valid = int(np.count_nonzero(~np.ma.getmaskarray(values)))
                            if not valid:
                                raise ValueError(f"Empty native {band} export")
                            products[band] = {
                                "path": str(tifs[0]), "valid": valid,
                                "crs": str(src.crs), "shape": src.shape,
                                "transform": tuple(src.transform),
                            }
                    record.update(status="complete", products=products)
                except Exception as exc:
                    record.update(status="failed", error=repr(exc))
                    raise
                finally:
                    record["rasmap_restored"] = rasmap.read_bytes() == original
                    save()
                    if not record["rasmap_restored"]:
                        raise RuntimeError("Native export did not restore the .rasmap bytes")

        first = {r["mode"]: r for r in receipt["runs"] if r["iteration"] == 0}
        for record in receipt["runs"]:
            # Mode comparison and within-mode repeatability are separate metrics.
            references = [("vs-horizontal", first["horizontal"])]
            if record["iteration"]:
                references.append(("repeatability", first[record["mode"]]))
            for kind, reference in references:
                for cutoff in (0.0, 0.5, 1.0, 2.0):
                    candidate, ref = record["products"], reference["products"]
                    metrics = RasFim.compare_rasters(
                        candidate["depth"]["path"], candidate["wse"]["path"],
                        ref["depth"]["path"], ref["wse"]["path"],
                        cells=cells, min_depth=cutoff,
                    )
                    receipt["comparisons"].append({
                        "kind": kind, "mode": record["mode"],
                        "iteration": record["iteration"], "min_depth": cutoff,
                        "metrics": metrics,
                    })
                    save()
        receipt["status"] = "complete"
    except Exception:
        receipt["status"] = "failed"
        raise
    finally:
        process.cpu_affinity(previous_affinity)
        receipt["parent_affinity_restored"] = process.cpu_affinity() == previous_affinity
        save()
        logging.getLogger("ras_commander").removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    main()
