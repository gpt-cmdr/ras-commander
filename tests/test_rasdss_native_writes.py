"""Native RasDss writes on real RasExamples data, read back on both backends.

The native backend writes in this process (no JVM). The Java backend writes the same
records in a worker process (``_rasdss_native_writes_java_worker.py``), which also reads
every Java-written and native-written record back through Java. The test then requires:

- Java reads the native-written files equal to the Java-written ones;
- the native reader reads both equal (same rules as the shadow comparison);
- shadow writes (Java plus a native repeat on a temporary copy) log no unexpected
  difference.

Covered: regular and irregular time series in DSS6 and DSS7 (new files, appends and a
merge into an existing block), real SHG precipitation grids (DSS6 PRECIP_2_BYTE and
ZLIB, DSS7), an instantaneous and a specified grid, and ``copy_grid_with_zero_tail``
on the real DSS6 precipitation family and on a DSS7 family. Source data:
RasExamples ``BaldEagleCrkMulti2D``.

Skips without ras_commander_fast_dss, without its writers, when the project cannot be extracted,
or when the Java bridge is unavailable.
"""

from __future__ import annotations

import os
import pickle
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss, RasExamples  # noqa: E402
from ras_commander.dss import _backend, _errors  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _backend.native_writes_available(), reason="ras-commander-fast-dss has no native writers"
)

WORKER = Path(__file__).with_name("_rasdss_native_writes_java_worker.py")
PROJECT = "BaldEagleCrkMulti2D"
TS6_SOURCE = "Bald_Eagle_Creek.dss"
TS7_SOURCE = "BaldEagleDamBrk.dss"
GRID_SOURCE = Path("Precipitation") / "precip.2018.09.dss"
GRID_FAMILY = "/SHG/RUSSIAN RIVER/PRECIP///WPC-QPF/"
MAX_VALUES = 3000
N_GRIDS = 6
UTM15N_WKT = (
    'PROJCS["NAD83 / UTM zone 15N",GEOGCS["NAD83",DATUM["North_American_Datum_1983",'
    'SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-93],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1]]'
)


@contextmanager
def backend_as(name: str):
    old_env = os.environ.pop(_backend.ENV_VAR, None)
    old_attr = RasDss.backend
    RasDss.backend = name
    try:
        yield
    finally:
        RasDss.backend = old_attr
        if old_env is not None:
            os.environ[_backend.ENV_VAR] = old_env


def _blank_d(pathname: str) -> str:
    parts = pathname.split("/")
    parts[4] = ""
    return "/".join(parts)


def _with_e(pathname: str, e_part: str, f_part: str) -> str:
    parts = pathname.split("/")
    parts[4], parts[5], parts[6] = "", e_part, f_part
    return "/".join(parts)


def _ts_sources(dss_file: Path, count: int):
    """First ``count`` regular datasets with enough values, read natively."""
    with dc.open(dss_file) as handle:
        catalog = handle.catalog()
    seen, out = set(), []
    for pathname, rtype in zip(catalog.pathname, catalog.record_type):
        if int(rtype) not in (100, 105):
            continue
        key = _blank_d(pathname)
        if key in seen:
            continue
        seen.add(key)
        try:
            frame = RasDss._read_timeseries_native(dss_file, key).iloc[:MAX_VALUES]
        except _errors.get("DssPathnameNotFoundError"):
            continue  # all-missing dataset
        if frame["value"].notna().sum() >= 20:
            out.append((key, frame))
        if len(out) == count:
            break
    return out


def _ts_cases(folder: Path):
    """Time-series writes: (version, kwargs) in write order, plus read-back pathnames."""
    regular6 = _ts_sources(folder / TS6_SOURCE, 4)
    regular7 = _ts_sources(folder / TS7_SOURCE, 2)
    assert len(regular6) == 4 and len(regular7) == 2
    cases = {6: [], 7: []}
    readback = {6: [], 7: []}
    for version in (6, 7):
        first = True
        for pathname, frame in regular6 + regular7:
            cases[version].append(dict(
                pathname=pathname, times=frame.index, values=frame["value"].to_numpy(),
                units=frame.attrs["units"], data_type=frame.attrs["type"] or "INST-VAL",
                dss_version=version if first else None,
            ))
            readback[version].append(pathname)
            first = False
        # Merge into an existing block: replace 10 stored values.
        pathname, frame = regular6[0]
        part = frame.iloc[10:20]
        cases[version].append(dict(
            pathname=pathname, times=part.index, values=part["value"].to_numpy() * 2.0 + 0.5,
            units=frame.attrs["units"], data_type=frame.attrs["type"] or "INST-VAL",
            dss_version=None,
        ))
        # Irregular: real values at a deterministic subset of their stamps.
        for e_part, (src_path, frame) in (("IR-DAY", regular6[1]), ("IR-MONTH", regular7[0])):
            valid = frame[frame["value"].notna()]
            rng = np.random.default_rng(17)
            pick = np.sort(rng.choice(len(valid), size=min(80, len(valid)), replace=False))
            sub = valid.iloc[pick]
            pathname = _with_e(src_path, e_part, "R1 IRREGULAR")
            cases[version].append(dict(
                pathname=pathname, times=sub.index, values=sub["value"].to_numpy(),
                units=frame.attrs["units"], data_type="INST-VAL", dss_version=None,
            ))
            readback[version].append(pathname)
    return cases, readback


def _grid_source(folder: Path):
    """``N_GRIDS`` consecutive real SHG precipitation grids, read natively."""
    source = folder / GRID_SOURCE
    records = RasDss._select_grid_family_records(
        RasDss._get_catalog_native(source), GRID_FAMILY,
        RasDss._split_dss_pathname(GRID_FAMILY)[1],
    )[:N_GRIDS]
    grids = [RasDss._read_grid_native(source, record[2]) for record in records]
    data = np.stack([g["data"] for g in grids])
    bounds = [records[0][0]] + [record[1] for record in records]
    first = grids[0]
    lower_left = first["metadata"]["lower_left_cell"]
    grid_info = {"cellsize": first["cell_size"], "lower_left_cell_x": lower_left[0],
                 "lower_left_cell_y": lower_left[1], "crs": "SHG",
                 "units": first["units"].strip(), "data_type": "PER-CUM"}
    return data, pd.DatetimeIndex(bounds), grid_info


def _grid_cases(folder: Path):
    data, bounds, grid_info = _grid_source(folder)
    family = GRID_FAMILY
    cases = {
        6: [
            dict(pathname=family, data=data, times=bounds, grid_info=grid_info, dss_version=6),
            dict(pathname="/SHG/RUSSIAN RIVER/PRECIP///R1-ZLIB/", data=data, times=bounds,
                 grid_info=dict(grid_info, compression="ZLIB"), dss_version=None),
        ],
        7: [
            dict(pathname=family, data=data, times=bounds, grid_info=grid_info, dss_version=7),
            dict(pathname="/SHG/RUSSIAN RIVER/PRECIP-INST///R1-INST/", data=data,
                 times=bounds[1:], grid_info=dict(grid_info, data_type="INST-VAL"),
                 dss_version=None),
            dict(pathname="/UTM15N/R1/PRECIP///R1-SPEC/", data=data, times=bounds,
                 grid_info={"cellsize": 2000.0, "origin": (300000.0, 3300000.0),
                            "crs": UTM15N_WKT, "units": "IN", "compression": "ZLIB"},
                 dss_version=None),
        ],
    }
    return cases


def _tail_cases(work: Path, folder: Path):
    """``copy_grid_with_zero_tail`` arguments per side (each side gets its own source copy)."""
    out = {}
    for side in ("java", "native", "shadow"):
        source = work / side / "precip_source.dss"
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / GRID_SOURCE, source)
        out[side] = [
            dict(source_dss=source, output_dss=work / side / "tail6.dss", pathname=GRID_FAMILY,
                 tail_intervals=4, time_shift_minutes=-300,
                 output_pathname="/SHG/RUSSIAN RIVER/PRECIP///R1-TAIL/"),
            dict(source_dss=work / side / "grid7.dss", output_dss=work / side / "tail7.dss",
                 pathname=GRID_FAMILY, tail_intervals=2),
        ]
    return out


def _write_requests(side_dir: Path, ts_cases, grid_cases, tail_cases):
    requests = []
    for version, cases in ts_cases.items():
        for case in cases:
            requests.append({"op": "write_timeseries", "kwargs": dict(
                dss_file=side_dir / f"ts{version}.dss", pathname=case["pathname"],
                times=case["times"], values=case["values"], units=case["units"],
                data_type=case["data_type"], dss_version=case["dss_version"])})
    for version, cases in grid_cases.items():
        for case in cases:
            requests.append({"op": "write_grid_timeseries", "kwargs": dict(
                dss_file=side_dir / f"grid{version}.dss", pathname=case["pathname"],
                data=case["data"], times=case["times"], grid_info=case["grid_info"],
                dss_version=case["dss_version"])})
    for case in tail_cases:
        requests.append({"op": "copy_grid_with_zero_tail", "kwargs": case})
    return requests


def _run_worker(work: Path, requests):
    req_path, out_path = work / "requests.pkl", work / "results.pkl"
    with open(req_path, "wb") as fh:
        pickle.dump(requests, fh)
    env = {k: v for k, v in os.environ.items() if k != _backend.ENV_VAR}
    proc = subprocess.run(
        [sys.executable, str(WORKER), str(req_path), str(out_path)],
        capture_output=True, text=True, timeout=3600, env=env,
    )
    if proc.returncode == 77 or "R1_BRIDGE_UNAVAILABLE" in proc.stdout:
        pytest.skip("Java bridge unavailable: " + proc.stdout.strip()[-300:])
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    with open(out_path, "rb") as fh:
        return pickle.load(fh)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    work = tmp_path_factory.mktemp("r1_native_writes")
    try:
        folder = Path(RasExamples.extract_project(PROJECT, output_path=work / "projects"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RasExamples project {PROJECT!r} unavailable: {type(exc).__name__}: {exc}")
    ts_cases, ts_readback = _ts_cases(folder)
    grid_cases = _grid_cases(folder)
    tails = _tail_cases(work, folder)

    # Native side, in this process, without a JVM.
    native_dir = work / "native"
    native_results = []
    jvm_loaded_before = "jnius" in sys.modules
    with backend_as("native"):
        for req in _write_requests(native_dir, ts_cases, grid_cases, tails["native"]):
            native_results.append(getattr(RasDss, req["op"])(**req["kwargs"]))
    if not jvm_loaded_before:
        assert "jnius" not in sys.modules, "native writes loaded the Java bridge"

    # Pathnames to read back: every record the native side stored.
    grid_files = ["grid6.dss", "grid7.dss", "tail6.dss", "tail7.dss"]
    grid_paths = {name: sorted(RasDss._get_catalog_native(native_dir / name)["pathname"])
                  for name in grid_files}
    ts_paths = {v: [RasDss._readback_pathname(p, v) for p in ts_readback[v]] for v in (6, 7)}

    java_dir = work / "java"
    requests = _write_requests(java_dir, ts_cases, grid_cases, tails["java"])
    n_writes = len(requests)
    reads = []
    for side_dir in (java_dir, native_dir):
        for version in (6, 7):
            dss_file = side_dir / f"ts{version}.dss"
            reads.append(("catalog", side_dir.name, f"ts{version}.dss", None))
            requests.append({"op": "get_catalog", "kwargs": {"dss_file": dss_file}})
            for pathname in ts_paths[version]:
                reads.append(("ts", side_dir.name, f"ts{version}.dss", pathname))
                requests.append({"op": "read_timeseries",
                                 "kwargs": {"dss_file": dss_file, "pathname": pathname}})
        for name, paths in grid_paths.items():
            reads.append(("catalog", side_dir.name, name, None))
            requests.append({"op": "get_catalog", "kwargs": {"dss_file": side_dir / name}})
            for pathname in paths:
                reads.append(("grid", side_dir.name, name, pathname))
                requests.append({"op": "read_grid",
                                 "kwargs": {"dss_file": side_dir / name, "pathname": pathname}})
    # Shadow writes: Java plus the native repeat on a temporary copy.
    shadow_dir = work / "shadow"
    requests.append({"op": "set_backend", "kwargs": {"value": "shadow"}})
    requests.append({"op": "reset_shadow"})
    requests += _write_requests(shadow_dir, ts_cases, grid_cases, tails["shadow"])
    requests.append({"op": "shadow_records"})
    results = _run_worker(work, requests)

    java_writes = results[:n_writes]
    read_results = {key: res for key, res in zip(reads, results[n_writes:n_writes + len(reads)])}
    return {
        "work": work, "ts_paths": ts_paths, "grid_paths": grid_paths,
        "native_results": native_results, "java_writes": java_writes,
        "reads": read_results, "shadow_records": results[-1]["result"],
        "shadow_backend": results[n_writes + len(reads)],
    }


def _ok(entry):
    assert "error" not in entry, entry.get("error")
    return entry["result"]


def test_java_and_native_writes_succeed(corpus):
    for entry in corpus["java_writes"]:
        _ok(entry)
    assert len(corpus["native_results"]) == len(corpus["java_writes"])


def test_java_reads_native_time_series_equal_to_java_written(corpus):
    reads = corpus["reads"]
    compared = 0
    for version in (6, 7):
        name = f"ts{version}.dss"
        java_cat = sorted(_ok(reads[("catalog", "java", name, None)])["pathname"])
        native_cat = sorted(_ok(reads[("catalog", "native", name, None)])["pathname"])
        assert java_cat == native_cat
        for pathname in corpus["ts_paths"][version]:
            jj = _ok(reads[("ts", "java", name, pathname)])
            jn = _ok(reads[("ts", "native", name, pathname)])
            assert _backend.compare_written_timeseries(jj, jn) == [], (version, pathname)
            assert len(jj) > 0
            compared += 1
    assert compared == len(corpus["ts_paths"][6]) + len(corpus["ts_paths"][7])


def test_native_reads_native_time_series_equal_to_java_written(corpus):
    work = corpus["work"]
    for version in (6, 7):
        for pathname in corpus["ts_paths"][version]:
            nj = RasDss._read_timeseries_native(work / "java" / f"ts{version}.dss", pathname)
            nn = RasDss._read_timeseries_native(work / "native" / f"ts{version}.dss", pathname)
            assert _backend.compare_written_timeseries(nj, nn) == [], (version, pathname)
        assert RasDss._get_file_version_native(work / "native" / f"ts{version}.dss") == version


def test_irregular_series_are_stored_irregular(corpus):
    work = corpus["work"]
    for version in (6, 7):
        with dc.open(work / "native" / f"ts{version}.dss") as handle:
            catalog = handle.catalog()
        irregular = catalog[catalog.pathname.str.upper().str.contains("/R1 IRREGULAR/")]
        assert len(irregular) and set(irregular.record_type) == {115}


def _java_grid_meta_diffs(java_grid, native_grid):
    """Java-read metadata differences, allowing only the compressed size (and the unused
    ZLIB scale/base words): a different deflate library writes other bytes."""
    diffs = _backend._grid_meta_diffs(java_grid, native_grid)
    if "metadata.compression" in diffs:
        jc = java_grid["metadata"]["compression"]
        nc = native_grid["metadata"]["compression"]
        same = jc["method"] == nc["method"] and (
            jc["method"] != 101001
            or (jc["base"] == nc["base"] and jc["scale_factor"] == nc["scale_factor"]))
        if same:
            diffs.remove("metadata.compression")
    return diffs


def test_java_reads_native_grids_equal_to_java_written(corpus):
    reads = corpus["reads"]
    compared = 0
    for name, paths in corpus["grid_paths"].items():
        java_cat = sorted(_ok(reads[("catalog", "java", name, None)])["pathname"])
        assert java_cat == paths, name
        for pathname in paths:
            jj = _ok(reads[("grid", "java", name, pathname)])
            jn = _ok(reads[("grid", "native", name, pathname)])
            cell_diffs, _ = _backend._grid_cell_diffs(jj, jn)
            assert cell_diffs == [], (name, pathname)
            assert _java_grid_meta_diffs(jj, jn) == [], (name, pathname)
            compared += 1
    assert compared >= 2 * N_GRIDS + 120


def test_native_reads_native_grids_equal_to_java_written(corpus):
    work = corpus["work"]
    allowed = {_backend.GRID_NULL_LABEL, _backend.GRID_ZLIB_WORDS_LABEL}
    for name, paths in corpus["grid_paths"].items():
        for pathname in paths:
            nj = RasDss._read_grid_native(work / "java" / name, pathname)
            nn = RasDss._read_grid_native(work / "native" / name, pathname)
            diffs, labels = _backend.compare_written_grids(nj, nn)
            assert diffs == [] and set(labels) <= allowed, (name, pathname, diffs)


def test_instantaneous_grid_pathnames_follow_monolith(corpus):
    native_paths = corpus["native_results"]
    inst = [r for r in native_paths if isinstance(r, list) and r and "/R1-INST/" in r[0]]
    assert inst, "instantaneous grid write missing"
    stored = [p for p in corpus["grid_paths"]["grid7.dss"] if "/R1-INST/" in p]
    assert sorted(inst[0]) == stored
    assert all(p.split("/")[5] == "" for p in stored)


def test_zero_tail_results_match(corpus):
    native_tails = [r for r in corpus["native_results"] if isinstance(r, dict)]
    java_tails = [_ok(e) for e in corpus["java_writes"] if isinstance(e.get("result"), dict)]
    assert len(native_tails) == len(java_tails) == 2
    for nat, jav in zip(native_tails, java_tails):
        for key in nat:
            if key in ("source_dss", "output_dss"):
                continue
            if key == "source_sha256" and nat["dss_version"] == 7:
                continue  # the DSS7 sources are the Java- and native-written grid files
            assert nat[key] == jav[key], key
    assert native_tails[0]["dss_version"] == 6 and native_tails[1]["dss_version"] == 7
    assert native_tails[0]["source_record_count"] == 120


def test_shadow_writes_log_no_unexpected_difference(corpus):
    assert _ok(corpus["shadow_backend"]) == "shadow"
    records = corpus["shadow_records"]
    writes = [r for r in records if r["operation"] in (
        "write_timeseries", "write_grid_timeseries", "copy_grid_with_zero_tail")]
    by_op = {}
    for r in writes:
        by_op.setdefault(r["operation"], []).append(r)
    assert set(by_op) == {"write_timeseries", "write_grid_timeseries", "copy_grid_with_zero_tail"}
    assert len(by_op["copy_grid_with_zero_tail"]) == 2
    bad = [r for r in writes if r["outcome"] not in ("identical", "expected")]
    assert bad == [], bad
    refusals = [r for r in writes if r["label"] == _backend.WRITE_REFUSAL_LABEL]
    assert refusals == [], refusals


# ---------------------------------------------------------------------------
# Native write contract (no Java)
# ---------------------------------------------------------------------------


@pytest.fixture
def native(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "native")

    def _no_jvm():
        raise AssertionError("native writes must not configure the JVM")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_no_jvm))


TIMES = pd.date_range("2020-01-01 01:00", periods=6, freq="h")


def test_native_writes_are_gated_on_the_writer_api(native, monkeypatch, tmp_path):
    monkeypatch.delattr(dc, "write_grid")
    assert not _backend.native_writes_available()
    target = tmp_path / "gated.dss"
    with pytest.raises(_errors.get("DssCapabilityError"), match="native DSS writers"):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    assert not target.exists()
    caps = RasDss.get_capabilities()
    assert caps.attrs["native_writes_available"] is False


def test_native_refusals_leave_no_new_file(native, tmp_path):
    target = tmp_path / "refused.dss"
    with pytest.raises(ValueError, match="infinite"):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, [1, 2, np.inf, 4, 5, 6])
    irregular_times = TIMES[:3].append(pd.DatetimeIndex(["2020-01-01 05:17"]))
    with pytest.raises(ValueError, match="not regular"):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", irregular_times, np.arange(4.0))
    with pytest.raises(ValueError):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0),
                                units="CUBIC-FEET-PER-SECOND", dss_version=6)
    assert not target.exists()


def test_native_new_file_version_and_existing_version_rules(native, tmp_path):
    default = tmp_path / "default.dss"
    RasDss.write_timeseries(default, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    assert RasDss._get_file_version_native(default) == 7
    v6 = tmp_path / "v6.dss"
    RasDss.write_timeseries(v6, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0), dss_version=6)
    RasDss.write_timeseries(v6, "/A/B/STAGE//1HOUR/F/", TIMES, np.arange(6.0), units="FT")
    assert RasDss._get_file_version_native(v6) == 6
    with pytest.raises(ValueError, match="not requested version 7"):
        RasDss.write_timeseries(v6, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0), dss_version=7)
    with pytest.raises(FileNotFoundError):
        RasDss.write_timeseries(tmp_path / "absent.dss", "/A/B/FLOW//1HOUR/F/", TIMES,
                                np.arange(6.0), create_if_missing=False)


def test_native_missing_values_follow_the_java_convention(native, tmp_path):
    values = np.array([1.0, np.nan, 3.0, 4.0, 5.0, 6.0])
    for version, stored in ((7, None), (6, -901.0)):
        target = tmp_path / f"nan{version}.dss"
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, values, dss_version=version)
        with dc.open(target) as handle:
            raw = handle.read_arrays("/A/B/FLOW//1HOUR/F/")["values"]
        if stored is None:
            assert np.isnan(raw[1])
        else:
            assert raw[1] == stored
        frame = RasDss.read_timeseries(target, "/A/B/FLOW//1HOUR/F/")
        assert np.isnan(frame["value"].iloc[1])


def test_native_grid_refusals(native, tmp_path):
    data = np.ones((1, 3, 4), dtype=np.float32)
    info = {"cellsize": 2000, "origin": (0, 0), "crs": "SHG"}
    bounds = pd.date_range("2020-01-01", periods=2, freq="h")
    with pytest.raises(ValueError):
        RasDss.write_grid_timeseries(tmp_path / "permax.dss", "/SHG/B/PRECIP///F/", data,
                                     bounds, dict(info, data_type="PER-MAX"))
    with pytest.raises(_errors.get("DssUnsupportedRecordError")):
        RasDss.write_grid_timeseries(tmp_path / "none6.dss", "/SHG/B/PRECIP///F/", data,
                                     bounds, dict(info, compression="NONE"), dss_version=6)
    assert not (tmp_path / "permax.dss").exists() and not (tmp_path / "none6.dss").exists()


def test_native_dss6_precip_keeps_negative_cells(native, tmp_path):
    """The Java path stores cells below base 0 as missing; native chooses the base."""
    data = np.array([[[-2.5, 0.0], [1.25, 3.0]]], dtype=np.float32)
    bounds = pd.date_range("2020-01-01", periods=2, freq="h")
    target = tmp_path / "neg6.dss"
    paths = RasDss.write_grid_timeseries(
        target, "/SHG/B/TEMP///F/", data, bounds,
        {"cellsize": 2000, "origin": (0, 0), "crs": "SHG", "data_type": "PER-AVER"},
        dss_version=6,
    )
    grid = RasDss.read_grid(target, paths[0])
    np.testing.assert_array_equal(grid["data"], data[0])
    assert grid["metadata"]["compression"]["method"] == 101001


def _atlas14_precip_kwargs():
    affine = pytest.importorskip("affine")
    # NOAA Atlas 14 raw values (tx100yr24ha, Houston crop; see test_native_precip_grid_dss).
    depth = np.array([[16905, 16921, 16938], [16908, 16930, 16945]]) / 1000
    data = np.stack([depth * 0.25, depth * 0.75])
    data[0, 0, 1] = np.nan
    return dict(
        pathname="/UTM15/HOUSTON/PRECIP///ATLAS14/", data=data,
        interval_bounds=pd.to_datetime(["2020-01-01 23:00", "2020-01-02 00:00",
                                        "2020-01-02 00:06"]),
        transform=affine.Affine(100, 0, 300000, 0, -100, 3300000), crs="EPSG:26915",
        units="inches",
    )


def test_native_precip_arrays_match_pydsstools(native, monkeypatch, tmp_path):
    pytest.importorskip("pydsstools", minversion="3.1.0")
    kwargs = _atlas14_precip_kwargs()
    for reference in (None, (0.0, 0.0)):
        name = "ref" if reference else "local"
        native_paths = RasDss.write_precip_grid_arrays(
            dss_file=tmp_path / f"native_{name}.dss", grid_reference_origin=reference, **kwargs)
        monkeypatch.setattr(RasDss, "backend", "java")
        pyd_paths = RasDss.write_precip_grid_arrays(
            dss_file=tmp_path / f"pyd_{name}.dss", grid_reference_origin=reference, **kwargs)
        monkeypatch.setattr(RasDss, "backend", "native")
        assert native_paths == pyd_paths
        for pathname in pyd_paths:
            pyd = RasDss._read_grid_native(tmp_path / f"pyd_{name}.dss", pathname)
            nat = RasDss._read_grid_native(tmp_path / f"native_{name}.dss", pathname)
            diffs, labels = _backend.compare_written_grids(pyd, nat)
            assert diffs == [] and labels == [], (name, pathname, diffs, labels)


def test_shadow_precip_arrays_write_pydsstools_and_compare_native(monkeypatch, tmp_path):
    pytest.importorskip("pydsstools", minversion="3.1.0")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "shadow")
    _backend.reset_shadow_stats()
    target = tmp_path / "shadow_precip.dss"
    paths = RasDss.write_precip_grid_arrays(dss_file=target, **_atlas14_precip_kwargs())
    assert target.is_file() and len(paths) == 2
    records = [r for r in _backend.SHADOW_RECORDS
               if r["operation"] == "write_precip_grid_arrays"]
    assert [(r["outcome"], r["label"]) for r in records] == [("identical", "identical")]
    assert list(tmp_path.iterdir()) == [target]


# ---------------------------------------------------------------------------
# Shadow-write robustness (no JVM: the Java writer is replaced by the native one,
# which is enough to exercise the snapshot, comparison, classification and cleanup)
# ---------------------------------------------------------------------------


@pytest.fixture
def shadow_no_jvm(monkeypatch, tmp_path):
    import tempfile

    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.delenv(_backend.SHADOW_COPY_LIMIT_ENV, raising=False)
    monkeypatch.setattr(RasDss, "backend", "shadow")
    monkeypatch.setattr(RasDss, "_write_timeseries_java",
                        staticmethod(RasDss._write_timeseries_native))
    scratch = tmp_path / "tempdir"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    _backend.reset_shadow_stats()
    return scratch


def _shadow_ts_records():
    return [r for r in _backend.SHADOW_RECORDS if r["operation"] == "write_timeseries"]


def test_shadow_write_compares_and_cleans_up(shadow_no_jvm, tmp_path):
    target = tmp_path / "out" / "bc.dss"
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES[:2], [10.0, 11.0])
    assert [(r["outcome"], r["label"]) for r in _shadow_ts_records()] == [
        ("identical", "identical"), ("identical", "identical")]
    assert list(shadow_no_jvm.iterdir()) == []  # temporary copies removed


def test_shadow_copy_limit_skips_large_targets(shadow_no_jvm, monkeypatch, tmp_path):
    target = tmp_path / "bc.dss"
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    monkeypatch.setattr(RasDss, "shadow_copy_limit_mb", 0)
    RasDss.write_timeseries(target, "/A/B/STAGE//1HOUR/F/", TIMES, np.arange(6.0))
    monkeypatch.setattr(RasDss, "shadow_copy_limit_mb", 256)
    monkeypatch.setenv(_backend.SHADOW_COPY_LIMIT_ENV, "0.000001")  # the variable wins
    RasDss.write_timeseries(target, "/A/B/ELEV//1HOUR/F/", TIMES, np.arange(6.0))
    monkeypatch.setenv(_backend.SHADOW_COPY_LIMIT_ENV, "not-a-number")
    RasDss.write_timeseries(target, "/A/B/TEMP//1HOUR/F/", TIMES, np.arange(6.0))
    outcomes = [(r["outcome"], r["label"]) for r in _shadow_ts_records()]
    assert outcomes[0] == ("identical", "identical")
    assert [o for o, _ in outcomes[1:]] == ["skipped"] * 3
    assert "shadow copy limit" in outcomes[1][1] and "shadow copy limit" in outcomes[2][1]
    assert "invalid shadow copy limit" in outcomes[3][1]
    assert len(RasDss._get_catalog_native(target)) == 4  # every Java write happened
    assert list(shadow_no_jvm.iterdir()) == []
    monkeypatch.delenv(_backend.SHADOW_COPY_LIMIT_ENV)
    assert _backend.shadow_copy_limit_bytes(1) == 1024 * 1024


def test_shadow_without_writers_is_skipped(shadow_no_jvm, monkeypatch, tmp_path):
    target = tmp_path / "bc.dss"
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    monkeypatch.setattr(_backend, "native_writes_available", lambda: False)
    monkeypatch.setattr(RasDss, "_write_timeseries_java", staticmethod(
        lambda *a, **k: None))  # the Java write itself still succeeds
    RasDss.write_timeseries(target, "/A/B/STAGE//1HOUR/F/", TIMES, np.arange(6.0))
    last = _shadow_ts_records()[-1]
    assert (last["outcome"], last["label"]) == ("skipped", _backend.NATIVE_WRITERS_MISSING_LABEL)
    assert "DssCapabilityError" in last["native_error"]
    assert list(shadow_no_jvm.iterdir()) == []


def test_shadow_writes_never_raise_for_the_comparison(shadow_no_jvm, monkeypatch, tmp_path,
                                                       caplog):
    target = tmp_path / "bc.dss"

    def broken(*args, **kwargs):
        raise RuntimeError("comparison exploded")

    monkeypatch.setattr(_backend, "compare_written_timeseries", broken)
    RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    assert "comparison failed" in caplog.text
    assert target.is_file()

    def native_crash(*args, **kwargs):
        raise RuntimeError("native writer crashed")

    real_java = RasDss._write_timeseries_java
    monkeypatch.setattr(RasDss, "_write_timeseries_native", staticmethod(native_crash))
    monkeypatch.setattr(RasDss, "_write_timeseries_java", staticmethod(real_java))
    RasDss.write_timeseries(target, "/A/B/STAGE//1HOUR/F/", TIMES, np.arange(6.0))
    last = _shadow_ts_records()[-1]
    assert (last["outcome"], last["label"]) == ("unexpected", "native write error")
    assert list(shadow_no_jvm.iterdir()) == []


def test_locked_file_is_refused_and_shadow_skips(native, monkeypatch, tmp_path):
    """W8: ras-commander-fast-dss refuses files HEC software holds (simulated lock refusal)."""
    def locked(*args, **kwargs):
        raise dc.DssLockedError("held by HEC software (simulated)")

    monkeypatch.setattr(dc, "write_timeseries", locked)
    target = tmp_path / "new" / "locked.dss"
    with pytest.raises(dc.DssLockedError):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, np.arange(6.0))
    assert not target.exists() and not target.parent.exists()
    outcome, label, _ = _backend.classify_write(dc.DssLockedError("x"), [], [])
    assert (outcome, label) == ("skipped", "native write: temporary copy locked")


def test_refused_write_leaves_no_new_directories(native, tmp_path):
    target = tmp_path / "a" / "b" / "refused.dss"
    with pytest.raises(ValueError):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/", TIMES, [1, 2, np.inf, 4, 5, 6])
    with pytest.raises(ValueError):
        RasDss.write_timeseries(target, "/A/B/FLOW//1HOUR/F/X/", TIMES, np.arange(6.0))
    with pytest.raises(ValueError):
        RasDss.write_grid_timeseries(
            target, "/SHG/B/PRECIP///F/", np.ones((1, 2, 2), dtype=np.float32),
            pd.date_range("2020-01-01", periods=2, freq="h"),
            {"cellsize": 2000, "crs": "SHG", "data_type": "PER-MAX"})
    assert list(tmp_path.iterdir()) == []
    existing = tmp_path / "keep"
    existing.mkdir()
    with pytest.raises(ValueError):
        RasDss.write_timeseries(existing / "x.dss", "/A/B/FLOW//1HOUR/F/X/", TIMES,
                                np.arange(6.0))
    assert existing.is_dir()  # directories that existed before are never removed
