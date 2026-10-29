"""Pair Rasterio and native terrio delivery on one warm prepared model.

Usage: python scripts/benchmarks/fim_writer_compare.py CONFIG ENGINE NEW_OUTPUT
CONFIG uses the single-source jobs format of fim_retained_compare.py. The
default is five pairs with alternating order, after one untimed warm-up pass.
Clocks include all mapping/delivery work; complete raster checks run afterward.
"""

import argparse
import json
from pathlib import Path
import time

from fim_catalog_compare import compare, digest


def main(config, engine, folder):
    import psutil
    from ras_commander import RasFim

    folder.mkdir(parents=True, exist_ok=False)
    parent = psutil.Process()
    parent.cpu_affinity(parent.cpu_affinity()[: config.get("threads", 4)])
    jobs = config["jobs"]
    if len({(j["hdf_path"], j["terrain_path"]) for j in jobs}) != 1:
        raise ValueError("Provide a single shared HDF and terrain")
    selectors = list(dict.fromkeys(t for j in jobs for t in j["timesteps"]))
    aliases = {t: f"s{i:06d}" for i, t in enumerate(selectors)}
    paths = {engine, str(Path(__file__).resolve())}
    paths.update(str(p.resolve()) for p in Path("ras_commander/fim").glob("*.py"))
    paths.update(
        j[k]
        for j in jobs
        for k in ("hdf_path", "terrain_path", "polygon")
        if isinstance(j.get(k), str)
    )
    hashes = {p: digest(p) for p in paths}
    receipt = dict(
        status="in_progress",
        config=config,
        identities=hashes,
        runs=[],
        conditions="one shared warm context; alternating writer order; four-core affinity includes encoding; complete clocks; comparison outside timing; shared host/filesystem cache uncontrolled",
    )

    def execute(model, target, writer):
        rows = []
        evidence = []
        started = time.perf_counter()
        for job in jobs:
            options = {
                k: job[k]
                for k in ("polygon", "polygon_layer", "bbox", "aoi_crs")
                if k in job
            }
            result = model.map_profiles(
                target / job["job_id"],
                profiles=list(dict.fromkeys(aliases[t] for t in job["timesteps"])),
                product_writer=writer,
                writer_threads=1,
                **options,
            )
            indexed = result.set_index("profile").to_dict("index")
            for i, t in enumerate(job["timesteps"]):
                rows.append(
                    dict(
                        indexed[aliases[t]],
                        job_id=job["job_id"],
                        request_ordinal=i,
                        timestep=t,
                    )
                )
            evidence.append(result.attrs["performance"])
        return dict(
            seconds=time.perf_counter() - started, products=rows, evidence=evidence
        )

    try:
        with RasFim.prepare_sloping_model(
            jobs[0]["hdf_path"],
            jobs[0]["terrain_path"],
            profiles={v: k for k, v in aliases.items()},
            engine_path=engine,
            threads=config.get("threads", 4),
            max_working_mib=4096,
            window_cache_mib=256,
            hydraulic_cache_mib=256,
        ) as model:
            reference = execute(model, folder / "warmup", "rasterio")["products"]
            native = psutil.Process(model._native_session.process.pid)
            for repeat in range(config.get("writer_repetitions", 5)):
                order = (
                    ["rasterio", "native"]
                    if repeat % 2 == 0
                    else ["native", "rasterio"]
                )
                for writer in order:
                    before = [p.cpu_times() for p in (parent, native)]
                    row = execute(model, folder / f"{writer}-{repeat}", writer)
                    after = [p.cpu_times() for p in (parent, native)]
                    row.update(
                        writer=writer,
                        repeat=repeat,
                        process_tree_cpu_seconds=sum(
                            b.user + b.system - a.user - a.system
                            for a, b in zip(before, after, strict=True)
                        ),
                    )
                    row["comparison"] = compare(row["products"], reference)
                    receipt["runs"].append(row)
                    (folder / "results.json").write_text(
                        json.dumps(receipt, indent=2), encoding="utf-8"
                    )
                    print(writer, repeat, round(row["seconds"], 3), flush=True)
        receipt["unchanged"] = {p: digest(p) == v for p, v in hashes.items()}
        assert all(receipt["unchanged"].values())
        receipt["status"] = "complete"
    finally:
        (folder / "results.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("engine")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(json.loads(args.config.read_text(encoding="utf-8")), args.engine, args.output)
