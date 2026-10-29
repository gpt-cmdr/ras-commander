"""Ablate retained-state/output optimizations on repeated real reach requests.

Usage: python scripts/benchmarks/fim_retained_compare.py CONFIG.json NEW_OUTPUT
CONFIG contains jobs, candidate_engine, baseline_engine, repetitions (3), passes
(2), and optional arms. No HEC-RAS execution. Output comparison covers complete
masks and valid float32 bits. Each rotated arm gets a fresh outer process and
the same CPU affinity, including compression. No depth postprocessing is added.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from fim_catalog_compare import compare, digest

ARMS = [
    "fresh",
    "baseline",
    "disabled",
    "hydraulic",
    "windows",
    "validation",
    "all",
    "native",
]


def worker(config, folder, arm):
    import psutil
    from ras_commander import RasFim
    from ras_commander.fim.RasFim import _require_dependencies

    _require_dependencies(triangulation=False)
    proc = psutil.Process()
    proc.cpu_affinity(proc.cpu_affinity()[: config.get("threads", 4)])
    jobs = config["jobs"]
    if any(j.get("interpolation", "sloping") != "sloping" for j in jobs):
        raise ValueError("This benchmark targets one source model's sloping requests")
    if len({(j["hdf_path"], j["terrain_path"]) for j in jobs}) != 1:
        raise ValueError("Provide a single shared HDF and terrain")
    selectors = list(dict.fromkeys(t for j in jobs for t in j["timesteps"]))
    aliases = {v: f"s{i:06d}" for i, v in enumerate(selectors)}
    selected = {name: value for value, name in aliases.items()}
    old = arm in ("baseline", "fresh")
    model = None
    data = dict(arm=arm, passes=[], prepare_seconds=[])
    folder.mkdir(parents=True)
    started = time.perf_counter()
    try:
        for turn in range(config.get("passes", 2)):
            tick = time.perf_counter()
            if model is None:
                prep = time.perf_counter()
                model = RasFim.prepare_sloping_model(
                    jobs[0]["hdf_path"],
                    jobs[0]["terrain_path"],
                    profiles=selected,
                    engine_path=config[
                        "baseline_engine" if old else "candidate_engine"
                    ],
                    threads=config.get("threads", 4),
                    max_working_mib=4096,
                    window_cache_mib=64
                    if old
                    else (256 if arm in ("windows", "all", "native") else 0),
                    hydraulic_cache_mib=256
                    if arm in ("hydraulic", "all", "native")
                    else 0,
                    validation_cache_mib=8
                    if arm in ("validation", "all", "native")
                    else 0,
                )
                data["prepare_seconds"].append(time.perf_counter() - prep)
            records, evidence = [], []
            for job in jobs:
                options = {
                    k: job[k]
                    for k in ("bbox", "polygon", "polygon_layer", "aoi_crs")
                    if k in job
                }
                names = list(dict.fromkeys(aliases[t] for t in job["timesteps"]))
                frame = model.map_profiles(
                    folder / f"pass{turn}" / job["job_id"],
                    profiles=names,
                    writer_threads=1,
                    product_writer="native" if arm == "native" else "rasterio",
                    **options,
                )
                evidence.append(frame.attrs["performance"])
                rows = frame.set_index("profile").to_dict("index")
                for i, t in enumerate(job["timesteps"]):
                    records.append(
                        dict(
                            rows[aliases[t]],
                            job_id=job["job_id"],
                            request_ordinal=i,
                            timestep=t,
                        )
                    )
            data["passes"].append(
                dict(
                    seconds=time.perf_counter() - tick,
                    products=records,
                    evidence=evidence,
                )
            )
            if arm == "fresh":
                model.close()
                model = None
    finally:
        if model is not None:
            model.close()
    data["seconds"] = time.perf_counter() - started
    return data


def main(config, folder):
    import psutil

    folder.mkdir(parents=True, exist_ok=False)
    cfg = folder / "config.json"
    cfg.write_text(json.dumps(config))
    sources = {
        str(Path(j[k]).resolve())
        for j in config["jobs"]
        for k in ("hdf_path", "terrain_path", "polygon")
        if isinstance(j.get(k), str)
    }
    sources.update(str(p.resolve()) for p in Path("ras_commander/fim").glob("*.py"))
    sources.update(
        [
            config["baseline_engine"],
            config["candidate_engine"],
            str(Path(__file__).resolve()),
            str(Path(__file__).with_name("fim_catalog_compare.py").resolve()),
        ]
    )
    hashes = {p: digest(p) for p in sources}
    receipt = dict(
        status="in_progress",
        config=config,
        identities=hashes,
        runs=[],
        conditions="rotated fresh outer processes; warmed imports; fixed affinity includes writers; warm passes retain model; 250ms memory samples/500ms tree refresh; shared workstation/filesystem cache uncontrolled; exact comparisons outside timing",
    )
    arms = config.get("arms", ARMS)
    reference = None
    try:
        for repeat in range(config.get("repetitions", 3)):
            for arm in arms[repeat % len(arms) :] + arms[: repeat % len(arms)]:
                target = folder / f"{arm}-{repeat}"
                print(f"START {arm} {repeat}", flush=True)
                with target.with_suffix(".log").open("wb") as log:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            __file__,
                            str(cfg),
                            str(target),
                            "--worker",
                            arm,
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    rss = private = 0
                    processes = []
                    next_tree = 0.0
                    sampler_cpu = 0.0
                    while child.poll() is None:
                        sample_start = time.process_time()
                        try:
                            if time.monotonic() >= next_tree:
                                root = psutil.Process(child.pid)
                                processes = [root] + root.children(recursive=True)
                                next_tree = time.monotonic() + 0.5
                            memory = []
                            for proc in processes:
                                try:
                                    memory.append(proc.memory_info())
                                except psutil.NoSuchProcess:
                                    pass
                            rss = max(rss, sum(m.rss for m in memory))
                            private = max(
                                private,
                                sum(getattr(m, "private", m.rss) for m in memory),
                            )
                        except psutil.NoSuchProcess:
                            pass
                        sampler_cpu += time.process_time() - sample_start
                        time.sleep(0.25)
                if child.returncode:
                    raise RuntimeError(f"Failed {target.name}; inspect log")
                row = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
                row.update(
                    repeat=repeat,
                    peak_rss_bytes=rss,
                    peak_private_bytes=private,
                    sampler_cpu_seconds=sampler_cpu,
                )
                if reference is None:
                    reference = row["passes"][0]["products"]
                for run in row["passes"]:
                    run["comparison"] = compare(run["products"], reference)
                receipt["runs"].append(row)
                (folder / "results.json").write_text(json.dumps(receipt, indent=2))
                print(
                    f"DONE {arm} {repeat}: {[round(p['seconds'], 3) for p in row['passes']]}",
                    flush=True,
                )
        receipt["unchanged"] = {p: digest(p) == v for p, v in hashes.items()}
        assert all(receipt["unchanged"].values())
        receipt["status"] = "complete"
    finally:
        (folder / "results.json").write_text(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--worker", choices=ARMS)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.worker:
        result = worker(config, args.output, args.worker)
        args.output.with_suffix(".json").write_text(json.dumps(result, indent=2))
    else:
        main(config, args.output)
