"""Qualify deterministic contours on caller-owned, computed 2D example models.

Run with ``uv run python scripts/benchmarks/fim_boundary_compare.py case.json out``.
The JSON case supplies hdf_path, terrain_path, terrain_hdf, profiles and optional
engine_path, terrain_crs_fnv1a64, bbox or polygon. Optional native_boundaries is
an interpolation -> profile -> retained-export-path mapping, for example
{"sloping": {"Max": "reference.shp"}}. No HEC-RAS run is launched.
Products and receipts belong outside the repository. Native references are
compared without repair or rounding; different vector methods have no speed ratio.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from ras_commander import RasFim


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    case = json.loads(args.case.read_text())
    references = case.pop("native_boundaries", None)
    if references is not None:
        if (not isinstance(references, dict) or not references
                or set(references) - {"horizontal", "sloping"}):
            parser.error("native_boundaries must map horizontal/sloping to profile-path mappings")
        for method, paths in references.items():
            if (not isinstance(paths, dict) or set(paths) != set(case.get("profiles", {"Max": "Max"}))
                    or any(not isinstance(path, str) or not Path(path).is_file() for path in paths.values())):
                parser.error(f"native_boundaries[{method}] must name every selected profile and existing export")
    case.setdefault("max_working_mib", 2048)
    case.setdefault("max_prepared_mib", 1024)
    args.output.mkdir(parents=True, exist_ok=False)
    paths = [args.case, Path(__file__), *(Path(case[k]) for k in
             ("hdf_path", "terrain_path", "terrain_hdf", "engine_path") if k in case)]
    before = {str(p): sha256(p) for p in paths}
    receipt = {"schema": "fim-boundary-qualification/1", "status": "in_progress",
               "native_vector_parity": False, "sources": before, "runs": []}
    receipt_path = args.output / "qualification.json"

    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2))

    save()
    try:
        for method in ("horizontal", "sloping"):
            baseline = None
            for repeat in range(args.repeats):
                # Rotate order to expose order/cache effects rather than always
                # warming the larger worker configuration with the serial run.
                configs = [(1, 1), (4, 1), (4, 4)]
                configs = configs[repeat % 3:] + configs[:repeat % 3]
                for threads, inflight in configs:
                    folder = args.output / f"{method}-{repeat}-{threads}-{inflight}"
                    started = time.perf_counter()
                    frame = RasFim.map_inundation_boundaries(**case,
                        output_folder=folder, interpolation=method, threads=threads,
                        max_inflight_profiles=inflight)
                    elapsed = time.perf_counter() - started
                    products = {row.profile: sha256(row.boundary_geojson)
                                for row in frame.itertuples()}
                    if baseline is None:
                        baseline = products
                    if products != baseline:
                        raise AssertionError(f"Product bytes changed across workers/repeats: {method}")
                    receipt["runs"].append(dict(method=method, repeat=repeat,
                        threads=threads, requested_inflight=inflight, seconds=elapsed,
                        performance=frame.attrs["performance"], product_sha256=products,
                        rows=frame.to_dict("records")))
                    save()
            if references is not None and method in references:
                frame = RasFim.compare_inundation_boundaries(**case,
                    output_folder=args.output / f"compare-{method}", interpolation=method,
                    native_boundaries=references[method], threads=4,
                    max_inflight_profiles=4)
                receipt.setdefault("comparisons", {})[method] = frame.to_dict("records")
        after = {str(p): sha256(p) for p in paths}
        if after != before:
            raise RuntimeError("Qualification source changed")
        receipt["status"] = "complete"
    except BaseException as exc:
        receipt.update(status="aborted", error=str(exc))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
