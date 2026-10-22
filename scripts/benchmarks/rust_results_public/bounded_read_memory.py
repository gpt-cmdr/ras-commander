"""Peak-memory evidence for native reads of one large all-time storage chunk.

Writes synthetic float32 series whose single storage chunk spans every
timestep, then reduces each with several block budgets in fresh child
processes, reporting peak working set above the pre-call baseline next to the
reported read plan. One chunk fits the 64 MiB per-file chunk cache, one does
not (re-decompressed per block).

    python bounded_read_memory.py --work DIR --out OUT.json
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

CASES = {"chunk_52mb_cached": (865, 15000), "chunk_87mb_uncached": (865, 25000)}
BUDGETS = [1 << 20, 16 << 20, 1 << 30]


def child(path, budget):
    import h5py
    import psutil
    from ras_commander import fast_results

    process = psutil.Process()
    with h5py.File(path, "r") as hdf:
        before = process.memory_info().rss
        started = time.perf_counter()
        result = fast_results.native_temporal_reduce(hdf["series"], backend="rust",
                                                     max_block_bytes=budget)
        seconds = time.perf_counter() - started
    peak = process.memory_info().peak_wset
    return dict(budget=budget, seconds=seconds, rss_before=before, peak=peak,
                peak_above_before_mib=round((peak - before) / 2**20, 1),
                read_plan={k: v for k, v in result.read_plan.items()},
                timings=dict(result.timings))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=2)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(args.child[0], int(args.child[1]))))
        return
    import h5py
    import numpy as np

    args.work.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, shape in CASES.items():
        path = args.work / f"{name}.h5"
        if not path.exists():
            rng = np.random.default_rng(5)
            with h5py.File(path, "w") as hdf:
                hdf.create_dataset("series", data=rng.normal(size=shape).astype(np.float32),
                                   chunks=shape, compression="gzip", compression_opts=1)
        runs = []
        for budget in BUDGETS:
            out = subprocess.run([sys.executable, __file__, "--child", str(path), str(budget)],
                                 capture_output=True, text=True, check=True)
            runs.append(json.loads(out.stdout.strip().splitlines()[-1]))
            r = runs[-1]
            print(f"{name} budget {budget >> 20} MiB: blocks {r['read_plan']['blocks']} x "
                  f"{r['read_plan']['block_rows']} rows, block {r['read_plan']['block_bytes'] / 2**20:.1f} MiB, "
                  f"peak +{r['peak_above_before_mib']} MiB, {r['seconds']:.2f}s", flush=True)
        report[name] = dict(shape=shape, series_mib=round(shape[0] * shape[1] * 4 / 2**20, 1), runs=runs)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
