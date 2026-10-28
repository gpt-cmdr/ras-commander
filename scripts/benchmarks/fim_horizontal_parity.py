"""Qualify complete horizontal masks and float32 values on retained native maps.

Run from the repository root with --cases local.json --engine executable
--output new-folder. Cases is a JSON list of objects with name, hdf, terrain,
mesh_name and references {depth: path, wse: path}. Native references must use
horizontal rendering, the same effective terrain and Max profile, and no added
depth cutoff. Native generation is separate and uses Commander APIs.
No HEC-RAS execution, resampling or reference filtering occurs in this runner.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import psutil

from ras_commander import RasFim
from ras_commander.fast_hdf import backend_scope
from scripts.benchmarks.fim_sloping_compare import compare_raw, deliver_reference_grid


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--writer-threads", type=int, default=4)
    parser.add_argument("--cpus", type=int, default=4)
    parser.add_argument("--max-working-mib", type=int, default=32768)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    engine = args.engine.resolve(strict=True)
    sources = [
        Path(__file__),
        Path("scripts/benchmarks/fim_sloping_compare.py"),
        Path("ras_commander/fim/RasFim.py"),
        Path("ras_commander/fim/_horizontal_engine.py"),
    ]
    receipt = dict(
        schema="horizontal-native-parity/1",
        engine_sha256=digest(engine),
        method=RasFim.get_engine_info(engine)["method"]["horizontal"],
        sources={str(path): digest(path) for path in sources},
        cases_sha256=digest(args.cases),
        rows=[],
        status="in_progress",
        threads=args.threads,
        writer_threads=args.writer_threads,
        extra_depth_cutoff=None,
        scope="complete physical-2D footprint; extra/missing/bit-different/outside pixels all required zero; no postfilter",
        timing_scope="cell table preparation, engine, GIS writes and matching-grid delivery; comparison/hashing excluded; first case may include dependency imports; no excluded mapping warm-up; retained native timing not interleaved",
    )

    def save():
        (output / "results.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )

    process = psutil.Process()
    affinity = process.cpu_affinity()
    if args.cpus < 1 or args.cpus > len(affinity):
        raise ValueError("cpus must fit available affinity")
    process.cpu_affinity(affinity[: args.cpus])
    receipt["affinity"] = process.cpu_affinity()
    try:
        for case in cases:
            name = case["name"]
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or name in ("", ".", "..")
            ):
                raise ValueError("case name must be a folder name")
            unit = output / name
            before = {key: digest(case[key]) for key in ("hdf", "terrain")}
            references_before = {
                key: digest(path) for key, path in case["references"].items()
            }
            print(f"MAP {name}", flush=True)
            started = time.perf_counter()
            with backend_scope("rust"):
                cells = RasFim.get_cells_from_plan_hdf(
                    case["hdf"], mesh_name=case["mesh_name"], min_depth=0
                )
            result = RasFim.map_horizontal_profiles(
                cells,
                case["terrain"],
                unit / "rust",
                profiles=["wsel_max"],
                min_depth=0,
                engine_path=engine,
                threads=args.threads,
                writer_threads=args.writer_threads,
                max_working_mib=args.max_working_mib,
                write_floodplain=False,
                hdf_path=case["hdf"],
            )
            paths = {}
            for band in ("depth", "wse"):
                paths[band] = unit / f"{band}-matched.tif"
                deliver_reference_grid(
                    result.iloc[0][f"{band}_tif"], case["references"][band], paths[band]
                )
            elapsed = time.perf_counter() - started
            print(f"COMPARE {name} after {elapsed:.3f}s", flush=True)
            # The physical cell table already supplies independently rasterized
            # footprint geometry; cell_idx/geometry are not inferred from overlap.
            metrics = {
                band: compare_raw(path, case["references"][band], cells, chunk_rows=256)
                for band, path in paths.items()
            }
            exact = all(
                metric["common"] > 0
                and all(
                    metric[key] == 0
                    for key in ("extra", "missing", "different", "outside_footprint")
                )
                for metric in metrics.values()
            )
            row = dict(
                name=name,
                physical_cells=len(cells),
                seconds=elapsed,
                native_seconds=case.get("native_seconds"),
                metrics=metrics,
                exact=exact,
                inputs_unchanged=all(
                    digest(case[key]) == expected for key, expected in before.items()
                ),
                references_unchanged=all(
                    digest(case["references"][key]) == expected
                    for key, expected in references_before.items()
                ),
            )
            receipt["rows"].append(row)
            save()
            print(json.dumps(row), flush=True)
            if (
                not exact
                or not row["inputs_unchanged"]
                or not row["references_unchanged"]
            ):
                raise AssertionError(f"Horizontal qualification failed: {name}")
        if (
            digest(engine) != receipt["engine_sha256"]
            or digest(args.cases) != receipt["cases_sha256"]
            or any(
                digest(path) != expected
                for path, expected in receipt["sources"].items()
            )
        ):
            raise AssertionError("Qualification code, engine or cases changed")
        receipt["status"] = "complete"
    except BaseException:
        receipt["status"] = "aborted"
        raise
    finally:
        process.cpu_affinity(affinity)
        receipt["affinity_restored"] = process.cpu_affinity() == affinity
        save()


if __name__ == "__main__":
    main()
