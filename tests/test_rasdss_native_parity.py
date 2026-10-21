"""Native-vs-Java parity for RasDss read methods on real RasExamples projects (P09b).

The Java backend runs in a separate process (``_rasdss_parity_java_worker.py``); the
native backend runs in-process with the JVM entry point disabled. Frames are compared
with the shadow-mode rules (``ras_commander.dss._backend``): values bitwise after
mapping Java's missing markers to NaN, index stamps, dtypes and attrs. Differences that
the migration note lists as intended (D15, Java-path bugs) are allowed; anything else
fails.

Skips cleanly when dss_commander is not installed (it is a private wheel), when the
example projects cannot be extracted, or when the Java bridge is unavailable.
"""

from __future__ import annotations

import json
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("dss_commander")

from ras_commander import RasDss, RasExamples, init_ras_project  # noqa: E402
from ras_commander.dss import _backend  # noqa: E402

PROJECTS = ("Muncie", "BaldEagleCrkMulti2D", "Chippewa_2D")
MAX_DATASETS_PER_FILE = 60
WORKER = Path(__file__).with_name("_rasdss_parity_java_worker.py")


def _dataset_key(pathname: str) -> str:
    parts = pathname.split("/")
    if len(parts) != 8:
        return pathname.upper()
    parts[4] = ""
    return "/".join(parts).upper()


def _blank_d(pathname: str) -> str:
    parts = pathname.split("/")
    if len(parts) == 8:
        parts[4] = ""
    return "/".join(parts)


def _ts_pathnames(dss_file: Path) -> list:
    """First catalog pathname of every time-series dataset (sampled evenly)."""
    with dc.open(dss_file) as handle:
        catalog = handle.catalog()
    ts = catalog[catalog.record_type.between(100, 119)]
    seen, firsts = set(), []
    for pathname in ts.pathname:
        key = _dataset_key(pathname)
        if key not in seen:
            seen.add(key)
            firsts.append(pathname)
    if len(firsts) > MAX_DATASETS_PER_FILE:
        idx = np.linspace(0, len(firsts) - 1, MAX_DATASETS_PER_FILE).round().astype(int)
        firsts = [firsts[i] for i in sorted(set(idx.tolist()))]
    return firsts


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Extract the projects and list their DSS files and DSS boundaries."""
    root = tmp_path_factory.mktemp("p09b_parity")
    projects = {}
    for name in PROJECTS:
        try:
            projects[name] = Path(RasExamples.extract_project(name, output_path=root))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"RasExamples project {name!r} unavailable: {type(exc).__name__}: {exc}")
    files = {}
    for name, folder in projects.items():
        for dss_file in sorted(folder.rglob("*")):
            if dss_file.is_file() and dss_file.suffix.lower() == ".dss":
                files[str(dss_file)] = _ts_pathnames(dss_file)
    boundaries = {}
    for name, folder in projects.items():
        ras = init_ras_project(folder, "7.0", hide_intro=True)
        bdf = ras.boundaries_df
        if bdf is None or "Use DSS" not in bdf.columns:
            continue
        mask = (bdf["Use DSS"] == True) | (bdf["Use DSS"] == "True")  # noqa: E712
        if mask.any():
            pickle_path = root / f"{name}_boundaries.pkl"
            bdf.to_pickle(pickle_path)
            boundaries[name] = (str(folder), str(pickle_path), int(mask.sum()))
    assert files, "no DSS files found in the extracted projects"
    return {"root": root, "files": files, "boundaries": boundaries}


def _windows(df: pd.DataFrame):
    n = len(df)
    a, b = df.index[n // 4], df.index[(3 * n) // 4]
    one_min = pd.Timedelta(minutes=1)
    return {
        "on_stamp_hec_strings": (a.strftime("%d%b%Y %H%M"), b.strftime("%d%b%Y %H%M")),
        "off_stamp": (a + one_min, b + one_min),
        "start_only": (a, None),
        "end_only": (None, b),
    }


@pytest.fixture(scope="module")
def java(corpus):
    """Run every request on the Java backend in a worker process."""
    requests = []
    for dss_file, pathnames in corpus["files"].items():
        requests.append({"op": "catalog", "dss_file": dss_file})
        requests.append({"op": "info", "dss_file": dss_file})
        for pathname in pathnames:
            requests.append({"op": "ts", "dss_file": dss_file, "pathname": pathname})
        for pathname in pathnames[:5]:
            requests.append({"op": "ts", "dss_file": dss_file, "pathname": _blank_d(pathname)})
        requests.append({"op": "multiple", "dss_file": dss_file, "pathnames": pathnames[:20]})
        probes = pathnames[:3] + ["/NOT/IN/THIS/FILE//1HOUR/P09B/"]
        for pathname in probes:
            for op in ("check_pathname_exists", "check_data_availability",
                       "check_pathname", "is_pathname_available"):
                requests.append({"op": op, "dss_file": dss_file, "pathname": pathname})
    for name, (folder, pickle_path, _count) in corpus["boundaries"].items():
        requests.append({"op": "boundaries", "project_dir": folder,
                         "boundaries_pickle": pickle_path, "name": name})
    req_path = corpus["root"] / "java_requests.json"
    out_path = corpus["root"] / "java_results.pkl"
    req_path.write_text(json.dumps(requests), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(WORKER), str(req_path), str(out_path)],
        capture_output=True, text=True, timeout=3600,
    )
    if completed.returncode == 77 and "P09B_BRIDGE_UNAVAILABLE:" in completed.stdout:
        marker = completed.stdout[completed.stdout.index("P09B_BRIDGE_UNAVAILABLE:"):]
        pytest.skip(" ".join(marker.split()))
    assert completed.returncode == 0, completed.stderr[-2000:]
    with open(out_path, "rb") as fh:
        results = pickle.load(fh)
    return {_key(r): res for r, res in zip(requests, results)}


def _key(req):
    return (req["op"], req.get("dss_file") or req.get("name"), req.get("pathname"))


@pytest.fixture
def native(monkeypatch):
    """Native backend with the JVM entry point disabled."""
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "native")

    def _no_jvm():
        raise AssertionError("native backend must not configure the JVM")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_no_jvm))
    return RasDss


def _classify(pathname, java_entry, native_call):
    native_df, native_exc = None, None
    try:
        native_df = native_call()
    except Exception as exc:  # noqa: BLE001
        native_exc = exc
    java_df = java_entry.get("result")
    java_exc = TypeError(java_entry["error"][1]) if "error" in java_entry else None
    if java_exc is not None and java_entry["error"][0] != "TypeError":
        java_exc = RuntimeError(java_entry["error"][1])
    return _backend.classify_timeseries(pathname, java_df, java_exc, native_df, native_exc)


def test_get_catalog_parity(corpus, java, native):
    for dss_file in corpus["files"]:
        java_cat = java[("catalog", dss_file, None)]["result"]
        native_cat = RasDss.get_catalog(dss_file)
        assert list(native_cat.columns) == ["pathname"]
        assert native_cat.attrs == {}
        assert native_cat["pathname"].tolist() == java_cat["pathname"].tolist(), dss_file
        assert str(native_cat["pathname"].dtype) == str(java_cat["pathname"].dtype)


def test_read_timeseries_parity(corpus, java, native):
    tally = {}
    for dss_file, pathnames in corpus["files"].items():
        forms = [(p, p) for p in pathnames] + [(_blank_d(p), p) for p in pathnames[:5]]
        for pathname, _ in forms:
            outcome, label, diffs = _classify(
                pathname, java[("ts", dss_file, pathname)],
                lambda: RasDss.read_timeseries(dss_file, pathname),
            )
            tally[(outcome, label)] = tally.get((outcome, label), 0) + 1
            assert outcome != "unexpected", (dss_file, pathname, label, diffs)
    assert tally.get(("identical", "identical"), 0) + tally.get(
        ("expected", "D1 missing markers mapped to NaN"), 0
    ) > 100, tally


def test_read_timeseries_window_parity(corpus, java, native):
    """Native honors start/end; Java's whole-dataset frame cut to the window matches."""
    checked = 0
    for dss_file, pathnames in corpus["files"].items():
        for pathname in pathnames[:8]:
            java_df = java[("ts", dss_file, pathname)].get("result")
            if java_df is None or len(java_df) < 4:
                continue
            native_full = RasDss.read_timeseries(dss_file, pathname)
            interval = native_full.attrs["interval"]
            for form, (start, end) in _windows(native_full).items():
                native_df = RasDss.read_timeseries(dss_file, pathname, start, end)
                cut = _backend.cut_window(java_df, start, end, interval, dc)
                outcome, label, diffs = _backend.classify_timeseries(
                    pathname, cut, None, native_df, None
                )
                assert outcome != "unexpected", (dss_file, pathname, form, label, diffs)
                assert len(native_df) < len(native_full) or form in ("start_only", "end_only")
                checked += 1
    assert checked >= 40


def test_read_multiple_timeseries_parity(corpus, java, native):
    for dss_file, pathnames in corpus["files"].items():
        java_map = java[("multiple", dss_file, None)]["result"]
        native_map = RasDss.read_multiple_timeseries(dss_file, pathnames[:20])
        assert list(native_map) == list(java_map)
        for pathname, java_df in java_map.items():
            native_df = native_map[pathname]
            outcome, label, diffs = _backend.classify_timeseries(
                pathname,
                java_df, None if java_df is not None else TypeError("Java read failed"),
                native_df, None if native_df is not None else dc.DssPathnameNotFoundError(pathname),
            )
            assert outcome != "unexpected", (dss_file, pathname, label, diffs)


def test_get_info_parity(corpus, java, native):
    for dss_file in corpus["files"]:
        java_info = java[("info", dss_file, None)]["result"]
        native_info = RasDss.get_info(dss_file)
        assert native_info.keys() == java_info.keys()
        for key in ("filepath", "filename", "file_size_mb", "total_paths"):
            assert native_info[key] == java_info[key], key
        pd.testing.assert_frame_equal(native_info["first_5_paths"], java_info["first_5_paths"])


VALIDATORS = ("check_pathname_exists", "check_data_availability", "check_pathname",
              "is_pathname_available")


def _summary(result):
    if isinstance(result, bool):
        return result
    if hasattr(result, "results"):
        return {"is_valid": result.is_valid, "results": [_summary(r) for r in result.results]}
    return {
        "check_name": result.check_name, "severity": str(result.severity),
        "passed": result.passed, "message": result.message, "details": result.details,
    }


def test_validator_parity(corpus, java, native):
    for dss_file, pathnames in corpus["files"].items():
        for pathname in pathnames[:3] + ["/NOT/IN/THIS/FILE//1HOUR/P09B/"]:
            for op in VALIDATORS:
                java_entry = java[(op, dss_file, pathname)]
                native_result = _summary(getattr(RasDss, op)(dss_file, pathname))
                if op == "check_data_availability" and not java_entry["result"]["passed"]:
                    # D15: the Java failure text is an accidental TypeError; compare the verdict.
                    assert native_result["passed"] is False
                    assert native_result["check_name"] == java_entry["result"]["check_name"]
                    continue
                assert native_result == java_entry["result"], (dss_file, pathname, op)


def test_extract_boundary_timeseries_parity(corpus, java, native):
    if not corpus["boundaries"]:
        pytest.skip("no DSS-defined boundaries in the selected projects")
    compared = 0
    for name, (folder, pickle_path, count) in corpus["boundaries"].items():
        java_df = java[("boundaries", name, None)]["result"]
        native_df = RasDss.extract_boundary_timeseries(pd.read_pickle(pickle_path), project_dir=folder)
        assert list(native_df.index) == list(java_df.index)
        for idx in java_df.index:
            j, n = java_df.at[idx, "dss_timeseries"], native_df.at[idx, "dss_timeseries"]
            assert (j is None) == (n is None), (name, idx)
            if j is not None:
                outcome, label, diffs = _backend.classify_timeseries("", j, None, n, None)
                assert outcome != "unexpected", (name, idx, label, diffs)
                compared += 1
    assert compared >= 1
