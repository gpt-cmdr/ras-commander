"""Interleaved release benchmarks: native text adapter vs current Python parser.

Cases (same immutable input, semantically equal full output):

* ``all_station_elevation`` - every listed node's station/elevation table of
  one geometry file. Reference: ``GeomCrossSection.get_cross_sections`` plus
  ``get_station_elevation`` per node (the current public path). Candidate:
  ``FastText.get_all_station_elevation(backend='rust')``.
* ``cross_sections`` - ``get_cross_sections`` listing.
* ``batch_edit`` - K station/elevation (+0.5 elevation) and K Manning's n
  (x1.1) edits written to a copy. Reference: sequential
  ``set_station_elevation(create_backup=False)``/``set_mannings_n`` on a
  copy. Candidate: one ``FastText.edit_geometry`` batch. Equality is checked
  by reading every edited table back with the Python readers.

Every measurement runs in a fresh subprocess (isolated peak RSS: Windows
``peak_wset``), alternating reference/candidate order per repetition. Each
worker reports import time, the first call (cold in-process; OS file cache
warm after the first repetition) and a second warm call, plus native stage
timings (read, kernel, adapter decode). Usage::

    python scripts/benchmarks/rust_text_public/bench_text.py \
        --corpus <dir> --out results.json --reps 5 --files 4 --edit-xs 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CASES = ("all_station_elevation", "cross_sections", "batch_edit")


def frame_digest(frame) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(list(frame.columns)).encode())
    for column in frame.columns:
        values = frame[column].to_numpy()
        h.update(values.tobytes() if values.dtype.kind in "fiub" else "\x1f".join(map(str, values)).encode())
    return h.hexdigest()


def edit_plan(path: Path, k: int):
    from ras_commander.fast_text import FastText

    index = FastText.geometry_index(path)
    nodes = index.nodes
    chosen = []
    for i in nodes.index[nodes["Type"] == 1]:
        key = (nodes.at[i, "River"], nodes.at[i, "Reach"], nodes.at[i, "RS"])
        if (index.find_node(*key) == i and index.raw["station_elevation"]["status"][i] == 1
                and index.raw["mannings_n"]["status"][i] == 1):
            chosen.append((key, index.station_elevation(i).copy(), index.mannings_n(i).copy()))
        if len(chosen) == 2 * k:
            break
    sta = [(key, se) for key, se, _ in chosen[:k]]
    mann = [(key, mn) for key, _, mn in chosen[k:2 * k]]
    for _, se in sta:
        se[:, 1] = se[:, 1].round(2) + 0.5
    for _, mn in mann:
        mn[:, 1] = (mn[:, 1] * 1.1).round(3)
    return sta, mann


def readback(path: Path, sta, mann) -> str:
    from ras_commander.geom.GeomCrossSection import GeomCrossSection as G

    h = hashlib.sha256()
    for key, _ in sta:
        h.update(G.get_station_elevation(path, *key).to_numpy().tobytes())
    for key, _ in mann:
        h.update(G.get_mannings_n(path, *key)[["Station", "n_value"]].to_numpy().tobytes())
    return h.hexdigest()


def worker(case: str, backend: str, path: Path, k: int) -> dict:
    import psutil

    t0 = time.perf_counter()
    import pandas as pd
    from ras_commander import fast_text
    from ras_commander.fast_text import FastText
    from ras_commander.geom.GeomCrossSection import GeomCrossSection as G

    import_s = time.perf_counter() - t0
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    tmp = Path(tempfile.mkdtemp(prefix="bench-text-"))
    stages = {}
    temp_bytes = 0

    def run():
        nonlocal temp_bytes
        if case == "all_station_elevation":
            return frame_digest(FastText.get_all_station_elevation(path, backend=backend))
        if case == "cross_sections":
            if backend == "python":
                return frame_digest(G.get_cross_sections(path))
            return frame_digest(FastText.get_cross_sections(path, backend="rust"))
        sta, mann = plan
        dest = tmp / f"{time.perf_counter_ns()}" / path.name
        dest.parent.mkdir()
        if backend == "python":
            shutil.copy2(path, dest)
            for key, se in sta:
                G.set_station_elevation(dest, *key, pd.DataFrame({"Station": se[:, 0], "Elevation": se[:, 1]}),
                                        create_backup=False)
            for key, mn in mann:
                G.set_mannings_n(dest, *key, pd.DataFrame({"Station": mn[:, 0], "n_value": mn[:, 1]}))
        else:
            edits = [{"op": "station_elevation", "river": r, "reach": h, "rs": s, "values": se}
                     for (r, h, s), se in sta]
            edits += [{"op": "mannings_n", "river": r, "reach": h, "rs": s, "values": mn}
                      for (r, h, s), mn in mann]
            FastText.edit_geometry(path, dest, edits)
        temp_bytes = max(temp_bytes, dest.stat().st_size)
        return dest

    plan = edit_plan(path, k) if case == "batch_edit" else None
    t = time.perf_counter()
    first = run()
    first_s = time.perf_counter() - t
    t = time.perf_counter()
    second = run()
    warm_s = time.perf_counter() - t
    if case == "batch_edit":
        digest = readback(first, *plan)
        assert digest == readback(second, *plan)
    else:
        digest = first
        assert first == second
    if backend == "rust" and case != "batch_edit":
        module = fast_text._require_native()
        t = time.perf_counter()
        data = path.read_bytes()
        stages["read_s"] = time.perf_counter() - t
        t = time.perf_counter()
        module.text_geometry_index(data, case == "all_station_elevation")
        stages["kernel_s"] = time.perf_counter() - t
        stages["adapter_decode_s"] = max(0.0, warm_s - stages["read_s"] - stages["kernel_s"])
    shutil.rmtree(tmp, ignore_errors=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source_sha, "input mutated"
    mem = psutil.Process().memory_info()
    return {
        "case": case, "backend": backend, "file": str(path), "import_s": import_s,
        "first_call_s": first_s, "warm_call_s": warm_s, "stages": stages,
        "output_digest": digest, "peak_rss_bytes": getattr(mem, "peak_wset", mem.rss),
        "temp_output_bytes": temp_bytes, "native_calls": dict(fast_text.NATIVE_CALLS),
        "source_sha256": source_sha,
    }


def hardware() -> dict:
    import psutil

    info = {
        "platform": platform.platform(), "python": sys.version.split()[0],
        "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
        "ram_bytes": psutil.virtual_memory().total, "processor": platform.processor(),
        "native_threads": "single-threaded text kernel (no rayon pool used)",
    }
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            info["cpu_name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--files", type=int, default=4)
    parser.add_argument("--edit-xs", type=int, default=10)
    parser.add_argument("--paths", nargs="*", help="manifest-relative geometry paths (overrides --files)")
    parser.add_argument("--worker", nargs=3, metavar=("CASE", "BACKEND", "FILE"))
    args = parser.parse_args()
    if args.worker:
        case, backend, file = args.worker
        print(json.dumps(worker(case, backend, Path(file), args.edit_xs)))
        return
    import ras_commander
    from ras_commander import fast_text

    manifest = json.loads((args.corpus / "corpus-manifest.json").read_text(encoding="utf-8"))
    geoms = [f for f in manifest["files"] if f["family"] == "g" and f["resolved_by_ras_prj"]]
    seen, selected = set(), []
    if args.paths:
        wanted = {Path(p).as_posix() for p in args.paths}
        selected = [f for f in geoms if Path(f["path"]).as_posix() in wanted]
        missing = wanted - {Path(f["path"]).as_posix() for f in selected}
        if missing:
            raise SystemExit(f"fixtures unavailable: {sorted(missing)}")
        geoms = []
    for f in sorted(geoms, key=lambda f: -f["bytes"]):
        if f["sha256"] not in seen:  # distinct content only
            seen.add(f["sha256"])
            selected.append(f)
        if len(selected) == args.files:
            break
    module = fast_text._require_native()
    pyd = next(Path(module.__file__).parent.glob("ras_commander_fast_hdf*.pyd"))
    runs = []
    for rep in range(args.reps):
        for f in selected:
            path = args.corpus / f["path"]
            for case in CASES:
                order = ("python", "rust") if rep % 2 == 0 else ("rust", "python")
                for backend in order:
                    out = subprocess.run(
                        [sys.executable, __file__, "--worker", case, backend, str(path),
                         "--edit-xs", str(args.edit_xs)],
                        capture_output=True, text=True, check=True,
                        env={**os.environ, "RAS_COMMANDER_FAST_TEXT": "auto"},
                    )
                    result = json.loads(out.stdout.strip().splitlines()[-1])
                    result["rep"] = rep
                    result["stored_version"] = f["stored_version"]
                    runs.append(result)
                    print(case, backend, Path(f["path"]).name, rep, round(result["warm_call_s"], 4), flush=True)
    summary = {}
    for f in selected:
        for case in CASES:
            key = f"{case}:{f['path']}"
            rows = {b: [r for r in runs if r["case"] == case and r["file"] == str(args.corpus / f["path"])
                        and r["backend"] == b] for b in ("python", "rust")}
            digests = {b: {r["output_digest"] for r in rows[b]} for b in rows}
            med = lambda b, k: sorted(r[k] for r in rows[b])[len(rows[b]) // 2]
            summary[key] = {
                "bytes": f["bytes"], "stored_version": f["stored_version"], "reps": len(rows["rust"]),
                "equal_output": digests["python"] == digests["rust"] and len(digests["rust"]) == 1,
                "python_warm_median_s": med("python", "warm_call_s"),
                "rust_warm_median_s": med("rust", "warm_call_s"),
                "python_first_median_s": med("python", "first_call_s"),
                "rust_first_median_s": med("rust", "first_call_s"),
                "warm_speedup_median": med("python", "warm_call_s") / med("rust", "warm_call_s"),
                "python_peak_rss_median": med("python", "peak_rss_bytes"),
                "rust_peak_rss_median": med("rust", "peak_rss_bytes"),
                "rust_stage_medians": {
                    s: sorted(r["stages"][s] for r in rows["rust"])[len(rows["rust"]) // 2]
                    for s in (rows["rust"][0]["stages"] if rows["rust"] else {})
                },
                "native_calls_in_rust_worker": rows["rust"][0]["native_calls"] if rows["rust"] else None,
                "native_calls_in_python_worker": rows["python"][0]["native_calls"] if rows["python"] else None,
            }
    report = {
        "hardware": hardware(),
        "ras_commander_file": ras_commander.__file__,
        "native_binary": str(pyd),
        "native_binary_sha256": hashlib.sha256(pyd.read_bytes()).hexdigest(),
        "scope": "subprocess per measurement; first call = cold in-process (OS cache warm after rep 0); "
                 "warm = second call in same process; RSS = process peak working set incl. interpreter/pandas",
        "selected_files": [{k: f[k] for k in ("path", "bytes", "sha256", "stored_version")} for f in selected],
        "summary": summary,
        "runs": runs,
    }
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
