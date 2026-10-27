"""Qualify supplied cell profiles against existing HDF-selector mapping.

Run: python scripts/benchmarks/fim_supplied_wsel_compare.py case.json new_output
Case: hdf, terrain, profiles (names -> Max/timestep), optional engine and
max_working_mib. This reads computed results only; it never runs HEC-RAS.
Complete masks and every valid float32 bit must agree. No native-parity claim
is made for aggregate profiles, modified terrains or unqualified options.
"""

from pathlib import Path
import argparse
import hashlib
import json
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from ras_commander import HdfMesh, HdfResultsMesh, RasFim
from ras_commander.fast_hdf import backend_scope


def selector_table(hdf, profiles):
    """Build a complete table through public, required-native readers only."""
    with backend_scope("rust"):
        keys = HdfMesh.get_mesh_cell_points(hdf, include_ghost_cells=True, include_geometry=False)
        table = keys[["mesh_name", "cell_id"]].copy()
        for name, selector in profiles.items():
            if selector == "Max":
                source = HdfResultsMesh.get_mesh_max_ws(hdf, include_ghost_cells=True, include_geometry=False)
                source = source[["mesh_name", "cell_id", "maximum_water_surface"]].rename(
                    columns={"maximum_water_surface": name})
            else:
                chunks = []
                for mesh in table.mesh_name.unique():
                    view = HdfResultsMesh.get_mesh_timeseries(hdf, mesh, "Water Surface",
                        truncate=False, return_type="view", include_ghost_cells=True)
                    values = view.select(time=int(selector)).to_numpy(dtype=np.float32).reshape(-1)
                    chunks.append(pd.DataFrame(dict(mesh_name=mesh,
                        cell_id=np.arange(len(values), dtype=np.int64), **{name: values})))
                source = pd.concat(chunks, ignore_index=True)
            joined = table.merge(source, on=["mesh_name", "cell_id"],
                validate="one_to_one", how="outer", indicator=True)
            assert (joined["_merge"] == "both").all(), "Selector omitted or added source cell IDs"
            table = joined.drop(columns="_merge")
    table.attrs["fim_source_hdf"] = str(Path(hdf).resolve())
    return table


def compare_products(actual, expected):
    import rasterio
    assert list(actual.profile) == list(expected.profile)
    metrics = []
    for a, b in zip(actual.itertuples(), expected.itertuples()):
        for band in ("depth_tif", "wse_tif"):
            with rasterio.open(getattr(a, band)) as candidate, rasterio.open(getattr(b, band)) as reference:
                assert candidate.shape == reference.shape
                assert candidate.crs == reference.crs and candidate.transform == reference.transform
                assert candidate.dtypes == reference.dtypes == ("float32",)
                x, y = candidate.read(1, masked=True), reference.read(1, masked=True)
                mx, my = np.ma.getmaskarray(x), np.ma.getmaskarray(y)
                differences = int(np.count_nonzero(mx != my))
                assert differences == 0, f"Complete validity masks differ: {a.profile}/{band}"
                valid = ~mx
                value_differences = int(np.count_nonzero(x.data[valid].view("u4") != y.data[valid].view("u4")))
                assert value_differences == 0, f"Float32 bits differ: {a.profile}/{band}"
                metrics.append(dict(profile=a.profile, band=band, pixels=x.size,
                    valid_pixels=int(valid.sum()), mask_differences=differences, float32_differences=value_differences))
    return metrics


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            result.update(block)
    return result.hexdigest()


def qualify(case, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    hdf, terrain = case["hdf"], case["terrain"]
    engine = case.get("engine")
    profiles = case["profiles"]
    inputs = [hdf, terrain, RasFim.get_engine_info(engine)["engine_path"]]
    before = {str(path): sha256(path) for path in inputs}
    table = selector_table(hdf, profiles).sample(frac=1, random_state=791)
    receipt = dict(status="in_progress", sources=before, runs=[], engine=RasFim.get_engine_info(engine)["method"]["engine"])
    try:
        for mode in case.get("render_modes", ["sloping", "slopingPretty"]):
            options = dict(engine_path=engine, render_mode=mode, max_working_mib=case.get("max_working_mib", 2048))
            tick = time.perf_counter()
            reference = RasFim.map_sloping_profiles(hdf, terrain, output / f"{mode}-selector",
                profiles=profiles, threads=1, **options)
            selector_seconds = time.perf_counter() - tick
            # Any fallback to a stored selector while supplied data is active is a failure.
            blocked = dict(side_effect=AssertionError("Unexpected HDF profile read"))
            with patch.object(HdfResultsMesh, "get_mesh_timeseries", **blocked), \
                 patch.object(HdfResultsMesh, "get_mesh_summary_output_group", **blocked):
                tick = time.perf_counter()
                supplied = RasFim.map_sloping_profiles(hdf, terrain, output / f"{mode}-supplied",
                    wsel_profiles=table, threads=4, max_inflight_profiles=2, **options)
                supplied_seconds = time.perf_counter() - tick
                equality = compare_products(supplied, reference)
                with RasFim.prepare_sloping_model(hdf, terrain, wsel_profiles=table,
                        threads=4, max_prepared_mib=2048, **options) as prepared:
                    owned = table.copy(deep=True)
                    table.loc[:, list(profiles)] = 999999.
                    retained = prepared.map_profiles(output / f"{mode}-prepared", max_inflight_profiles=2)
                    equality += compare_products(retained, reference)
                    table = owned
                    assert prepared.info["profile_views_prepared"] == 0
            receipt["runs"].append(dict(mode=mode, selector_seconds=selector_seconds,
                supplied_seconds=supplied_seconds, metrics=equality,
                profile_source=supplied.attrs["profile_source"]))
        assert {str(path): sha256(path) for path in inputs} == before
        receipt["status"] = "complete"
    except BaseException as exc:
        receipt.update(status="aborted", error=str(exc))
        raise
    finally:
        (output / "qualification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = qualify(json.loads(args.case.read_text(encoding="utf-8")), args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
