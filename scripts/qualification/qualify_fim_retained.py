"""Compare retained/native-delivery sloping products to a prior engine.

Usage: python scripts/qualification/qualify_fim_retained.py CASES.json
       BASELINE_ENGINE CANDIDATE_ENGINE NEW_OUTPUT

Each case contains name, hdf, terrain, profiles, requests (bbox/polygon kwargs),
and optional ordinary sloping rendering options. Source models stay read-only.
Every AOI is revisited after the intervening requests. No HEC-RAS execution,
resampling or depth cutoff. Generated evidence remains outside the repository.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from fim_catalog_compare import compare


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main(cases, baseline, candidate, output):
    from ras_commander import RasFim

    output.mkdir(parents=True, exist_ok=False)
    paths = {baseline, candidate}
    for case in cases:
        paths.update([case["hdf"], case["terrain"]])
        paths.update(
            r["polygon"] for r in case["requests"] if isinstance(r.get("polygon"), str)
        )
    before = {str(p): digest(p) for p in paths}
    receipt = dict(status="in_progress", identities=before, cases=[])
    try:
        for case in cases:
            options = {
                k: case[k]
                for k in (
                    "render_mode",
                    "reduce_shallow_to_horizontal",
                    "use_depth_weighted_faces",
                    "postprocessing_hdf",
                    "corner_elevation_source",
                    "invalid_cells",
                )
                if k in case
            }
            common = dict(
                profiles=case["profiles"], threads=4, max_working_mib=4096, **options
            )
            records = []
            with RasFim.prepare_sloping_model(
                case["hdf"],
                case["terrain"],
                engine_path=candidate,
                window_cache_mib=256,
                hydraulic_cache_mib=256,
                **common,
            ) as model:
                selections = case["requests"]
                for i, request in enumerate(selections + selections):
                    reference = RasFim.map_sloping_profiles(
                        case["hdf"],
                        case["terrain"],
                        output / case["name"] / f"reference-{i}",
                        engine_path=baseline,
                        **common,
                        **request,
                    )
                    expected = [
                        dict(
                            row,
                            job_id=case["name"],
                            request_ordinal=j,
                            timestep=case["profiles"][row["profile"]],
                        )
                        for j, row in enumerate(reference.to_dict("records"))
                    ]
                    for writer in ("rasterio", "native"):
                        actual = model.map_profiles(
                            output / case["name"] / f"{writer}-{i}",
                            product_writer=writer,
                            max_inflight_profiles=2,
                            **request,
                        )
                        products = [
                            dict(
                                row,
                                job_id=case["name"],
                                request_ordinal=j,
                                timestep=case["profiles"][row["profile"]],
                            )
                            for j, row in enumerate(actual.to_dict("records"))
                        ]
                        report = actual.attrs["performance"]["engine_report"]
                        assert report["session"]["retained_window_bytes"] <= 256 << 20
                        assert (
                            report["session"]["retained_hydraulic_bytes"] <= 256 << 20
                        )
                        checks = compare(products, expected)
                        for left, right in zip(products, expected, strict=True):
                            assert (
                                left["depth_finite_pixels"]
                                == right["depth_finite_pixels"]
                            )
                            assert left["flooded_pixels"] == right["flooded_pixels"]
                        records.append(
                            dict(
                                request=i,
                                writer=writer,
                                checks=checks,
                                performance=actual.attrs["performance"],
                            )
                        )
            receipt["cases"].append(
                dict(name=case["name"], options=options, records=records)
            )
            (output / "results.json").write_text(json.dumps(receipt, indent=2))
            print(
                f"{case['name']}: {sum(len(r['checks']) for r in records)} exact band checks",
                flush=True,
            )
        receipt["unchanged"] = {p: digest(p) == v for p, v in before.items()}
        assert all(receipt["unchanged"].values())
        receipt["status"] = "complete"
    finally:
        (output / "results.json").write_text(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(
        json.loads(args.cases.read_text(encoding="utf-8")),
        args.baseline,
        args.candidate,
        args.output,
    )
