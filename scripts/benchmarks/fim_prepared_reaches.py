"""Compare one-shot and prepared sloping reach sequences on computed models.

Run with --cases local.json --output new-folder --engine executable. The JSON
is a list of workloads, each containing name, hdf, terrain, profiles (name to
Max/index) and requests (AOI keyword dictionaries). Optional render_mode,
reduce_shallow_to_horizontal and use_depth_weighted_faces select the method.
Polygon requests can use vector-file paths and aoi_crs. No HEC-RAS is executed.
Preparation, mapping and close are timed; decoded pixel checks run outside
timing. Retain local receipts rather than committing generated model outputs.
"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import numpy as np
import rasterio
from rasterio.windows import Window

from ras_commander import RasFim
from ras_commander.fim.RasFim import _require_dependencies


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def compare_products(actual, expected):
    """Require identical grids, masks and valid binary32 values, without resampling."""
    checked = 0
    finite_pixels = 0
    for left, right in zip(actual, expected, strict=True):
        for a, b in zip(left, right, strict=True):
            with rasterio.open(a) as candidate, rasterio.open(b) as reference:
                if (
                    candidate.shape != reference.shape
                    or candidate.crs != reference.crs
                    or candidate.transform != reference.transform
                    or candidate.dtypes != reference.dtypes
                    or candidate.dtypes != ("float32",)
                ):
                    raise AssertionError("Prepared comparison grid/type mismatch")
                for row in range(0, candidate.height, 256):
                    window = Window(
                        0, row, candidate.width, min(256, candidate.height - row)
                    )
                    x = candidate.read(1, window=window, masked=True)
                    y = reference.read(1, window=window, masked=True)
                    np.testing.assert_array_equal(
                        np.ma.getmaskarray(x), np.ma.getmaskarray(y)
                    )
                    valid = ~np.ma.getmaskarray(x)
                    np.testing.assert_array_equal(
                        x.data[valid].view("u4"), y.data[valid].view("u4")
                    )
                    finite_pixels += int(np.count_nonzero(valid & np.isfinite(x.data)))
                checked += 1
    return dict(products=checked, finite_pixels=finite_pixels, exact=True)


def benchmark(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    engine = args.engine.resolve(strict=True)
    receipt = dict(
        engine_sha256=digest(engine),
        harness_sha256=digest(__file__),
        cases_sha256=digest(args.cases),
        threads=args.threads,
        writer_threads=args.writer_threads,
        max_inflight_profiles=args.inflight,
        max_working_mib=args.max_working_mib,
        max_prepared_mib=args.max_prepared_mib,
        repetitions=args.repetitions,
        rows=[],
        inputs={},
        scope="same engine/options/grids; no added cutoff; compare outside timing; prepare and close included in prepared sequence",
        conditions="imports warmed; alternating sequence order; shared workstation; filesystem caches uncontrolled",
        python_source_sha256={
            str(path): digest(path)
            for path in (
                Path("ras_commander/fim/RasFim.py"),
                Path("ras_commander/fim/_sloping.py"),
                Path("ras_commander/fim/_sloping_context.py"),
                Path("ras_commander/fim/_sloping_inputs.py"),
            )
        },
    )

    def save():
        (output / "results.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )

    process = None
    original_affinity = None
    if args.cpus is not None:
        import psutil

        process = psutil.Process()
        original_affinity = process.cpu_affinity()
        if len(original_affinity) < args.cpus:
            raise ValueError("Requested CPU affinity exceeds available CPUs")
        process.cpu_affinity(original_affinity[: args.cpus])
        receipt["cpu_affinity"] = process.cpu_affinity()
    try:
        _require_dependencies(triangulation=False)
        for case in cases:
            name = case["name"]
            if (
                not isinstance(name, str)
                or not name
                or Path(name).name != name
                or name in (".", "..")
            ):
                raise ValueError("Workload names must be simple folder names")
            requests = case["requests"]
            if not requests or not case["profiles"]:
                raise ValueError("Each workload needs requests and profiles")
            inputs = {
                key: dict(path=case[key], sha256=digest(case[key]))
                for key in ("hdf", "terrain")
            }
            receipt["inputs"][name] = inputs
            common = dict(
                profiles=case["profiles"],
                engine_path=engine,
                threads=args.threads,
                max_working_mib=args.max_working_mib,
                **{
                    key: case[key]
                    for key in (
                        "render_mode",
                        "reduce_shallow_to_horizontal",
                        "use_depth_weighted_faces",
                    )
                    if key in case
                },
            )
            baseline = None
            for repeat in range(args.repetitions):
                order = (
                    ("one-shot", "prepared")
                    if repeat % 2 == 0
                    else ("prepared", "one-shot")
                )
                for method in order:
                    print(f"MAP {name} repeat={repeat} method={method}", flush=True)
                    started = time.perf_counter()
                    mapper = None
                    maps = []
                    timings = []
                    performance = []
                    try:
                        if method == "prepared":
                            mapper = RasFim.prepare_sloping_model(
                                case["hdf"],
                                case["terrain"],
                                max_prepared_mib=args.max_prepared_mib,
                                **common,
                            )
                        prepared_info = mapper.info if mapper else None
                        for index, request in enumerate(requests):
                            target = output / f"{name}-{repeat}-{method}" / str(index)
                            tick = time.perf_counter()
                            controls = dict(
                                writer_threads=args.writer_threads,
                                max_inflight_profiles=args.inflight,
                                **request,
                            )
                            if mapper:
                                result = mapper.map_profiles(target, **controls)
                            else:
                                result = RasFim.map_sloping_profiles(
                                    case["hdf"],
                                    case["terrain"],
                                    target,
                                    **common,
                                    **controls,
                                )
                            timings.append(time.perf_counter() - tick)
                            performance.append(result.attrs["performance"])
                            maps.extend(
                                (row.depth_tif, row.wse_tif)
                                for row in result.itertuples()
                            )
                    finally:
                        if mapper:
                            mapper.close()
                    elapsed = time.perf_counter() - started
                    check = compare_products(
                        maps, maps if baseline is None else baseline
                    )
                    if baseline is None:
                        baseline = maps
                    row = dict(
                        workload=name,
                        repeat=repeat,
                        method=method,
                        sequence_seconds=elapsed,
                        request_seconds=timings,
                        requests=requests,
                        profiles=case["profiles"],
                        prepared_info=prepared_info,
                        performance=performance,
                        comparison=check,
                    )
                    receipt["rows"].append(row)
                    save()
                    print(
                        f"RESULT {name} {method} {elapsed:.6f}s; {check['products']} exact products",
                        flush=True,
                    )
            for source in inputs.values():
                source["unchanged"] = digest(source["path"]) == source["sha256"]
                if not source["unchanged"]:
                    raise AssertionError("Benchmark input changed")
        summaries = []
        for case in cases:
            rows = [row for row in receipt["rows"] if row["workload"] == case["name"]]
            medians = {
                method: statistics.median(
                    row["sequence_seconds"] for row in rows if row["method"] == method
                )
                for method in ("one-shot", "prepared")
            }
            summaries.append(
                dict(
                    workload=case["name"],
                    **medians,
                    speed_ratio=medians["one-shot"] / medians["prepared"],
                    prepare_seconds=statistics.median(
                        row["prepared_info"]["prepare_seconds"]
                        for row in rows
                        if row["method"] == "prepared"
                    ),
                )
            )
        receipt["summary"] = summaries
        if not all(
            digest(path) == expected
            for path, expected in receipt["python_source_sha256"].items()
        ):
            raise AssertionError("Python mapping source changed during benchmarking")
        if (
            digest(engine) != receipt["engine_sha256"]
            or digest(__file__) != receipt["harness_sha256"]
            or digest(args.cases) != receipt["cases_sha256"]
        ):
            raise AssertionError(
                "Benchmark engine, harness or case definitions changed"
            )
        receipt["status"] = "complete"
    except BaseException:
        receipt["status"] = "aborted"
        raise
    finally:
        if process is not None:
            process.cpu_affinity(original_affinity)
            receipt["affinity_restored"] = process.cpu_affinity() == original_affinity
        receipt["engine_unchanged"] = digest(engine) == receipt["engine_sha256"]
        receipt["harness_unchanged"] = digest(__file__) == receipt["harness_sha256"]
        receipt["cases_unchanged"] = digest(args.cases) == receipt["cases_sha256"]
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--writer-threads", type=int, default=1)
    parser.add_argument("--inflight", type=int, default=2)
    parser.add_argument("--max-working-mib", type=int, default=32768)
    parser.add_argument("--max-prepared-mib", type=int, default=2048)
    parser.add_argument(
        "--cpus", type=int, help="Optional process affinity count; requires psutil"
    )
    args = parser.parse_args()
    for name in (
        "repetitions",
        "threads",
        "writer_threads",
        "inflight",
        "max_working_mib",
        "max_prepared_mib",
        "cpus",
    ):
        if getattr(args, name) is not None and getattr(args, name) < 1:
            parser.error(f"{name} must be positive")
    benchmark(args)


if __name__ == "__main__":
    main()
