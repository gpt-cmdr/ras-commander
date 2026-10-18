"""Measure identical PMTiles workloads through packed and ras2cng-style inputs.

Run from this checkout, with its own .venv. Input is a locally retained
source-regions.gpkg from test_real_regions.py. No models are run or modified.
Each sample uses a fresh process; peak_wset is the whole process high-water
working set, including imports/input. Fine-grained codec/temp-I/O costs are
not measured. This is a small adapter benchmark, not a general tiler ranking.
"""
import argparse
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/rust_export_conformance"))


def child(args):
    os.environ["RAYON_NUM_THREADS"] = "2"
    import geopandas as gpd
    import pandas as pd
    import psutil
    import ras_commander
    import ras_commander_fast_hdf as native
    from ras_commander import fast_hdf
    from helpers import pack
    import freestiler
    assert Path.cwd().resolve() == ROOT
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT / "ras_commander")
    assert Path(native.__file__).resolve().is_relative_to(ROOT / ".venv")
    started = time.perf_counter()
    source = gpd.read_file(args.input)
    frame = gpd.GeoDataFrame(pd.concat([source] * args.repeat, ignore_index=True), crs=source.crs)
    frame["batch_id"] = range(len(frame))
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    if args.child == "packed":
        layer = pack(list(frame.geometry))
        layer["properties"] = {key: frame[key].tolist() for key in frame.columns if key != frame.geometry.name}
        coordinate_count = len(layer["coordinates"])
    else:
        coordinate_count = int(frame.geometry.count_coordinates().sum())
    prepare_seconds = time.perf_counter() - started
    started = time.perf_counter()
    destination = Path(args.output) / f"{args.child}-{args.repeat}-{args.sample}.pmtiles"
    if args.child == "packed":
        fast_hdf.export_pmtiles(destination, {"regions": layer}, source_crs=frame.crs,
            min_zoom=17, max_zoom=18, backend="rust", threads=2)
    else:
        freestiler.freestile({"regions": frame}, destination, min_zoom=17, max_zoom=18,
                            simplification=False, quiet=True)
    seconds = time.perf_counter() - started
    memory = psutil.Process().memory_info()
    report = dict(backend=args.child, features=len(frame), coordinates=coordinate_count,
        load_seconds=load_seconds, prepare_seconds=prepare_seconds, export_seconds=seconds,
        adapter_and_export_seconds=seconds+prepare_seconds,
        process_peak_working_set_bytes=memory.peak_wset, output_bytes=destination.stat().st_size,
        output=str(destination), python=sys.version, native=native.__file__)
    (Path(args.output) / f"{args.child}-{args.repeat}-{args.sample}.json").write_text(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--child", choices=["packed", "freestiler"])
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    jobs = [(backend, i) for backend in ["packed", "freestiler"] for i in range(args.samples)]
    random.Random(17).shuffle(jobs)
    reports = []
    for backend, i in jobs:
        subprocess.run([sys.executable, __file__, "--input", args.input, "--output", args.output,
            "--repeat", str(args.repeat), "--sample", str(i), "--child", backend], check=True)
        reports.append(json.loads((output / f"{backend}-{args.repeat}-{i}.json").read_text()))
    # Independent reopen and per-feature semantic comparison, not byte size alone.
    from helpers import decode
    for i in range(args.samples):
        native = decode(output / f"packed-{args.repeat}-{i}.pmtiles")[2]
        reference = decode(output / f"freestiler-{args.repeat}-{i}.pmtiles")[2]
        assert native.keys() == reference.keys()
        for address, layers in native.items():
            def records(layer):
                return {f["properties"]["batch_id"]: (f["geometry"], f["properties"]) for f in layer["features"]}
            assert records(layers["regions"]) == records(reference[address]["regions"])
    summary = {backend: {key: statistics.median(r[key] for r in reports if r["backend"] == backend)
        for key in ["prepare_seconds", "export_seconds", "adapter_and_export_seconds", "process_peak_working_set_bytes", "output_bytes"]}
        for backend in ["packed", "freestiler"]}
    result = dict(samples=reports, medians=summary, decoded_semantics_equal=True,
        limitations="Whole-process peak working set; no isolated codec/temp I/O measurement; small repeated real geometry, not independent spatial scaling.")
    (output / "benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
