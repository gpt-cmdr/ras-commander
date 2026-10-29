"""Measure a real catalog and require exact direct/candidate raster outputs.

Run: python scripts/benchmarks/fim_catalog_compare.py jobs.json NEW_OUTPUT
The JSON is an object with jobs (the RasFim.map_catalog input), optional
threads/max_working_mib/max_memory_mib and repetitions (default 3). Each arm
uses a fresh process; imports are warmed before timing, and scanning is outside
all clocks. No HEC-RAS execution or reference resampling is performed.
"""

import argparse
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def worker(config, folder, arm):
    config = {**config, **config.get("variants", {}).get(arm, {})}
    arm = config.get("mode", arm)
    import psutil
    from ras_commander import RasFim
    from ras_commander.fim.RasFim import _require_dependencies

    _require_dependencies(triangulation=False)
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[: config.get("threads", 4)])
    started = time.perf_counter()
    if arm == "serial":
        records = []
        for job in config["jobs"]:
            if job.get("interpolation", "sloping") != "sloping":
                raise ValueError(
                    "This direct-reference benchmark currently targets sloping jobs"
                )
            options = {
                k: job[k]
                for k in (
                    "polygon",
                    "polygon_layer",
                    "bbox",
                    "aoi_crs",
                    "render_mode",
                    "reduce_shallow_to_horizontal",
                    "use_depth_weighted_faces",
                    "postprocessing_hdf",
                    "corner_elevation_source",
                    "invalid_cells",
                )
                if k in job
            }
            mapped = RasFim.map_sloping_profiles(
                job["hdf_path"],
                job["terrain_path"],
                folder / job["job_id"],
                profiles={f"p{i:06d}": v for i, v in enumerate(job["timesteps"])},
                threads=config.get("threads", 4),
                writer_threads=1,
                engine_path=config.get("engine_path"),
                max_working_mib=config.get("max_working_mib", 2048),
                **options,
            )
            for ordinal, row in enumerate(mapped.to_dict("records")):
                row.update(
                    job_id=job["job_id"],
                    request_ordinal=ordinal,
                    timestep=job["timesteps"][ordinal],
                )
                records.append(row)
    else:
        mapped = RasFim.map_catalog(
            config["jobs"],
            folder,
            threads=config.get("threads", 4),
            max_workers={"reuse": 1, "parallel2": 2, "parallel4": 4}[arm],
            strategy="reuse" if arm == "reuse" else "parallel",
            writer_threads=1,
            engine_path=config.get("engine_path"),
            **config.get("catalog_options", {}),
            max_working_mib=config.get("max_working_mib", 2048),
            max_memory_mib=config.get("max_memory_mib", 16384),
        )
        records = mapped.to_dict("records")
    return dict(seconds=time.perf_counter() - started, products=records)


def compare(rows, reference):
    import numpy as np
    import rasterio

    metrics = []
    for a, b in zip(rows, reference, strict=True):
        assert (a["job_id"], a["request_ordinal"], a["timestep"]) == (
            b["job_id"],
            b["request_ordinal"],
            b["timestep"],
        )
        for band in ("depth_tif", "wse_tif"):
            if a[band] is None or b[band] is None:
                assert (
                    a[band] is None and b[band] is None and a["status"] == b["status"]
                )
                continue
            with rasterio.open(a[band]) as actual, rasterio.open(b[band]) as expected:
                assert (
                    actual.shape == expected.shape
                    and actual.transform == expected.transform
                    and actual.crs == expected.crs
                )
                x, y = actual.read(1, masked=True), expected.read(1, masked=True)
                av, ev = ~np.ma.getmaskarray(x), ~np.ma.getmaskarray(y)
                common = av & ev
                counts = dict(
                    extra=int((av & ~ev).sum()),
                    missing=int((ev & ~av).sum()),
                    different=int(
                        (x.data[common].view("u4") != y.data[common].view("u4")).sum()
                    ),
                )
                assert all(v == 0 for v in counts.values()), counts
                metrics.append(
                    dict(
                        job_id=a["job_id"],
                        ordinal=a["request_ordinal"],
                        band=band,
                        **counts,
                    )
                )
    return metrics


def main(config, output):
    import psutil
    from ras_commander import RasFim

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    engine = RasFim.get_engine_info()
    paths = {
        str(Path(j[k]).resolve())
        for j in config["jobs"]
        for k in ("hdf_path", "terrain_path", "polygon")
        if isinstance(j.get(k), str)
    }
    paths.update(str(p.resolve()) for p in Path("ras_commander/fim").glob("*.py"))
    paths.update([str(Path(__file__).resolve()), engine["engine_path"]])
    for variant in config.get("variants", {}).values():
        if variant.get("engine_path"):
            paths.add(variant["engine_path"])
        for root in variant.get("source_roots", []):
            paths.update(str(p.resolve()) for p in Path(root).glob("*.py"))
    identities = {p: digest(p) for p in paths}
    receipt = dict(
        status="in_progress",
        conditions="fresh processes; imports warmed; affinity envelope includes writers; rotated arms; filesystem caches/shared workstation uncontrolled; 250ms RSS/private samples,500ms tree discovery; no cutoff; compare outside clocks",
        identities=identities,
        config=config,
        versions={
            p: md.version(p)
            for p in (
                "ras-commander",
                "ras-commander-fast-map",
                "ras-commander-fast-hdf",
            )
        },
        runs=[],
    )
    arms = config.get("arms", ["serial", "reuse", "parallel2", "parallel4"])
    reference = None
    try:
        for repeat in range(config.get("repetitions", 3)):
            order = arms[repeat % len(arms) :] + arms[: repeat % len(arms)]
            for arm in order:
                folder = output / f"{arm}-{repeat}"
                config_path = output / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                print(f"START {arm} {repeat}", flush=True)
                with (output / f"{arm}-{repeat}.log").open("wb") as log:
                    child = subprocess.Popen(
                        [
                            config.get("variants", {})
                            .get(arm, {})
                            .get("python", sys.executable),
                            __file__,
                            str(config_path),
                            str(folder),
                            "--worker",
                            arm,
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        cwd=config.get("variants", {}).get(arm, {}).get("cwd"),
                    )
                    peak_rss = peak_private = 0
                    processes = []
                    next_tree = 0.0
                    sampler_cpu = 0.0
                    while child.poll() is None:
                        sample_start = time.process_time()
                        rss = private = 0
                        try:
                            if time.monotonic() >= next_tree:
                                root = psutil.Process(child.pid)
                                processes = [root] + root.children(recursive=True)
                                next_tree = time.monotonic() + 0.5
                        except psutil.NoSuchProcess:
                            pass
                        for proc in processes:
                            try:
                                memory = proc.memory_info()
                                rss += memory.rss
                                private += getattr(memory, "private", memory.rss)
                            except psutil.NoSuchProcess:
                                pass
                        peak_rss, peak_private = (
                            max(peak_rss, rss),
                            max(peak_private, private),
                        )
                        sampler_cpu += time.process_time() - sample_start
                        time.sleep(0.25)
                if child.returncode:
                    raise RuntimeError(f"{arm} failed; inspect its log")
                row = json.loads(folder.with_suffix(".json").read_text())
                row.update(
                    arm=arm,
                    repeat=repeat,
                    peak_tree_rss_bytes=peak_rss,
                    peak_tree_private_bytes=peak_private,
                    sampler_cpu_seconds=sampler_cpu,
                )
                if reference is None:
                    reference = row["products"]
                row["comparison"] = compare(row["products"], reference)
                receipt["runs"].append(row)
                (output / "results.json").write_text(json.dumps(receipt, indent=2))
                print(f"DONE {arm} {repeat}: {row['seconds']:.3f}s", flush=True)
        receipt["unchanged"] = {p: digest(p) == v for p, v in identities.items()}
        assert all(receipt["unchanged"].values())
        receipt["status"] = "complete"
    finally:
        (output / "results.json").write_text(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--worker")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.worker:
        data = worker(config, args.output, args.worker)
        args.output.with_suffix(".json").write_text(json.dumps(data, indent=2))
    else:
        main(config, args.output)
