"""``write_timeseries`` refuses times HEC-DSS would store elsewhere, on every backend.

HEC-DSS stores a regular series by position from its first time. Before this check, HEC
Monolith (the ``java`` backend) silently moved values given at other times, single values
included, and reported success; the native engine refused some of them and accepted
others (PR #863 review 1). ``RasDss._check_write_times`` (``ras_commander/dss/_times.py``)
now runs once, before either writer.

The case tables are the HEC Monolith oracle cases of hms-commander PR #55 (reviews 1-3),
which ported the same rule set: inputs HEC keeps are written and read back exactly by
every available reader; inputs HEC moves are refused before any file exists; and, with
the check disabled, HEC Monolith moves the review cases (why the check exists).

Native cases run in this process. Java cases run in one worker process for the module
(the JVM starts once per process) and skip without Java, pyjnius or HEC Monolith.
"""

from __future__ import annotations

import logging
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss  # noqa: E402
from ras_commander.dss import _backend, _times  # noqa: E402

WORKER = Path(__file__).with_name("_rasdss_native_writes_java_worker.py")
HOURS = pd.date_range("2020-01-01 01:00", periods=6, freq="h")


def _t(*stamps):
    return pd.DatetimeIndex(list(stamps))


#: Inputs whose times HEC-DSS keeps (HEC Monolith oracle). Written on every backend, to
#: DSS7 and DSS6, and read back exactly.
KEPT = {
    "hourly": ("1HOUR", HOURS),
    "hourly offset 00:15": ("1HOUR", pd.date_range("2020-01-01 00:15", periods=4, freq="h")),
    "15-minute across 29 February": ("15MIN", pd.date_range("2020-02-29 23:15", periods=6, freq="15min")),
    "daily across 29 February": ("1DAY", pd.date_range("2020-02-27", periods=5, freq="D")),
    "daily at 06:00": ("1DAY", pd.date_range("2019-12-30 06:00", periods=5, freq="D")),
    "single value": ("1HOUR", HOURS[:1]),
    "monthly, month ends (2400)": ("1MON", _t("2020-02-01", "2020-03-01", "2020-04-01", "2020-05-01")),
    "monthly, leap February end": ("1MON", _t("2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01")),
    "monthly, mid-month across leap and common Februaries": (
        "1MON", pd.DatetimeIndex([pd.Timestamp("2019-11-15") + pd.DateOffset(months=i) for i in range(16)])),
    "monthly, 29 Feb 2020 12:00 offset": (
        "1MON", _t("2020-01-29 12:00", "2020-02-29 12:00", "2020-03-29 12:00", "2020-04-29 12:00")),
    "yearly from 29 February": ("1YEAR", _t("2020-02-29", "2021-03-01", "2022-03-01")),
    "yearly from 1 January": ("1YEAR", _t("2019-01-01", "2020-01-01", "2021-01-01", "2022-01-01")),
    "yearly, 15 June across a leap year (PR #863 review)": (
        "1YEAR", _t("2019-06-15", "2020-06-15", "2021-06-15")),
    "semi-month": ("SEMI-MONTH", _t("2020-01-16", "2020-02-01", "2020-02-16", "2020-03-01")),
    "tri-month across 29 February": ("TRI-MONTH", _t("2020-02-11", "2020-02-21", "2020-03-01", "2020-03-11")),
    "weekly": ("1WEEK", pd.date_range("2020-01-06", periods=5, freq="7D")),
}

#: Inputs HEC-DSS stores at other times. Refused before anything is written, everywhere.
SHIFTED = {
    "a missing hour": ("1HOUR", HOURS.delete(3), "value 3 is at"),
    "hourly under 15MIN": ("15MIN", HOURS, "value 1 is at"),
    "irregular hourly step (PR #863 review)": (
        "1HOUR", _t("2020-01-01 01:00", "2020-01-01 02:30", "2020-01-01 04:00"), "value 1 is at"),
    "a missing day": ("1DAY", _t("2020-01-01", "2020-01-02", "2020-01-04"), "value 2 is at"),
    "yearly 29 Feb then 28 Feb": ("1YEAR", _t("2020-02-29", "2021-02-28", "2022-02-28"), "value 1"),
    "monthly month-end days": ("1MON", _t("2020-02-29", "2020-03-31", "2020-04-30"), "value 0"),
    "monthly 30th with 29 February (PR #863 review)": (
        "1MON", _t("2020-01-30", "2020-02-29", "2020-03-30", "2020-04-30"), "value 1"),
    "monthly, a skipped month": ("1MON", _t("2020-02-01", "2020-03-01", "2020-04-02"), "value 2"),
    "monthly 30th across a 28-day February": (
        "1MON", _t("2019-01-30", "2019-03-02", "2019-03-30", "2019-04-30"), "value 1"),
    "monthly 30th, pandas month steps": ("1MON", _t("2019-01-30", "2019-02-28", "2019-03-30"), "value 1"),
    "semi-month off its half-month": ("SEMI-MONTH", _t("2020-01-16", "2020-02-01", "2020-02-29"), "value 2"),
    "semi-month 30th across February": (
        "SEMI-MONTH", _t("2019-01-30", "2019-02-15", "2019-03-02", "2019-03-15"), "value 2"),
    "tri-month 30th across February": (
        "TRI-MONTH", _t("2019-01-30", "2019-02-10", "2019-02-20", "2019-03-02"), "value 3"),
    "weekly from the first week of a DSS decade block": (
        "1WEEK", pd.date_range("2019-12-30", periods=4, freq="7D"), "value 0"),
}

LEAP_YEARLY = {
    "leap year, 15 June": _t("2020-06-15", "2021-06-15", "2022-06-15"),
    "leap year, 3 March": _t("2020-03-03", "2021-03-03", "2022-03-03"),
    "leap year, 31 December": _t("2024-12-31", "2025-12-31", "2026-12-31"),
}
DSS6_YEARLY_EDGE = {
    "28 February of a leap year": _t("2020-02-28", "2021-02-28", "2022-02-28"),
    "1 March of a leap year": _t("2020-03-01", "2021-03-02", "2022-03-02"),
}

#: Single values HEC-DSS stores at other times: (E part, version, time, where HEC stores it).
SINGLE_MOVED = {
    "DSS6 yearly, leap year after 2 March (PR #863 review)": ("1YEAR", 6, "2020-06-15", "2020-06-16"),
    "DSS7 weekly, first week of a DSS decade block (PR #863 review)": ("1WEEK", 7, "2019-12-30", "2020-01-06"),
    "DSS7 monthly, 29 February (PR #863 review)": ("1MON", 7, "2020-02-29", "2020-03-01"),
    "DSS7 monthly, 31 January": ("1MON", 7, "2019-01-31", "2019-02-01"),
    "DSS7 semi-month, mid-month": ("SEMI-MONTH", 7, "2019-01-15", None),
    "DSS7 yearly, 31 December 12:00": ("1YEAR", 7, "2019-12-31 12:00", None),
}
#: Single values HEC-DSS keeps at their given time.
SINGLE_KEPT = {
    "15MIN at 00:07": ("15MIN", (6, 7), "2019-12-31 23:07"),
    "1HOUR at 00:15": ("1HOUR", (6, 7), "2020-02-29 23:15"),
    "6HOUR at 03:17": ("6HOUR", (6, 7), "2020-01-01 03:17"),
    "1DAY at 06:00": ("1DAY", (6, 7), "2020-02-29 06:00"),
    "1MON at a month end": ("1MON", (6, 7), "2020-03-01"),
    "1YEAR from 29 February": ("1YEAR", (6, 7), "2020-02-29"),
    "1WEEK": ("1WEEK", (6, 7), "2020-01-06"),
    "DSS6 1MON on the 31st": ("1MON", (6,), "2019-01-31"),
    "DSS6 SEMI-MONTH on the 15th": ("SEMI-MONTH", (6,), "2019-01-15"),
    "DSS6 TRI-MONTH on the 20th": ("TRI-MONTH", (6,), "2019-01-20"),
}
#: Refusals and the version advice their message gives: "dss6"/"dss7" = writing to that
#: version works; "none" = no version change helps.
VERSION_ADVICE = {
    "DSS7 single 1MON on the 31st": ("1MON", 7, ["2019-01-31"], "dss6"),
    "DSS7 single 1MON on 29 February": ("1MON", 7, ["2020-02-29"], "dss6"),
    "DSS7 single SEMI-MONTH on the 15th": ("SEMI-MONTH", 7, ["2019-01-15"], "dss6"),
    "DSS7 single TRI-MONTH on the 20th": ("TRI-MONTH", 7, ["2019-01-20"], "dss6"),
    "DSS7 single 1WEEK in a decade week": ("1WEEK", 7, ["2019-12-30"], "none"),
    "DSS7 single 1YEAR on 31 December 12:00": ("1YEAR", 7, ["2019-12-31 12:00"], "none"),
    "DSS6 single 1WEEK in a decade week": ("1WEEK", 6, ["2019-12-30"], "none"),
    "DSS7 multi-value 1MON from the 31st": ("1MON", 7, ["2019-01-31", "2019-03-03", "2019-03-31"], "none"),
    "DSS6 multi-value 1MON from the 31st": ("1MON", 6, ["2019-01-31", "2019-03-03", "2019-03-31"], "none"),
    "DSS6 yearly, leap start": ("1YEAR", 6, ["2020-06-15", "2021-06-15"], "dss7"),
}
#: Cases where HEC Monolith moves the values when the check is disabled (proof): (E part,
#: version, times).
MOVED_WITHOUT_CHECK = {
    "yearly 29 Feb then 28 Feb": ("1YEAR", 7, SHIFTED["yearly 29 Feb then 28 Feb"][1]),
    "monthly 30th with 29 February": ("1MON", 7, SHIFTED["monthly 30th with 29 February (PR #863 review)"][1]),
    "irregular hourly step": ("1HOUR", 7, SHIFTED["irregular hourly step (PR #863 review)"][1]),
    "DSS6 yearly leap start": ("1YEAR", 6, LEAP_YEARLY["leap year, 15 June"]),
    "single DSS6 yearly (review)": ("1YEAR", 6, _t("2020-06-15")),
    "single DSS7 weekly decade week (review)": ("1WEEK", 7, _t("2019-12-30")),
    "single DSS7 monthly 29 February (review)": ("1MON", 7, _t("2020-02-29")),
}

KEPT_KEY = "kept|{case}|v{version}"


def _path(e_part):
    return f"//G/FLOW//{e_part}/OBS/"


def _values(n):
    return np.arange(n, dtype=float) + 0.5


def _engine_dss6_calendar_fixed() -> bool:
    """True when the installed engine writes DSS6 yearly times HEC keeps (fixed after
    0.1.2; ``RC_NATIVE_DEFAULT_PARITY.md`` engine gap EG2)."""
    times = KEPT["yearly, 15 June across a leap year (PR #863 review)"][1]
    with tempfile.TemporaryDirectory() as folder:
        probe = str(Path(folder) / "p.dss")
        dc.create(probe, 6)
        try:
            dc.write_timeseries(probe, "/A/G/FLOW//1YEAR/P/", np.arange(3.0),
                                times=times.to_numpy(dtype="datetime64[s]"), units="", data_type="INST-VAL",
                                version=6)
        except ValueError:
            return False
        back = dc.read_timeseries(probe, "/A/G/FLOW//1YEAR/P/")
    return list(back.index) == list(times)


ENGINE_DSS6_FIXED = _engine_dss6_calendar_fixed()
#: KEPT cases engine 0.1.2's DSS6 writer refuses and its DSS6 reader misdates (EG2).
ENGINE_DSS6_GAP = {"yearly, 15 June across a leap year (PR #863 review)"}


@pytest.fixture(autouse=True)
def _auto(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "native")
    _times.reset_warning()
    yield
    _times.reset_warning()


def _native_write(target, e_part, times, values, version):
    RasDss.backend = "native"
    RasDss.write_timeseries(target, _path(e_part), times, values, dss_version=version)


def _native_read(target, e_part):
    RasDss.backend = "native"
    pathname = RasDss.get_catalog(target)["pathname"].iloc[0]
    frame = RasDss.read_timeseries(target, pathname)
    return [str(t) for t in frame.index], frame["value"].tolist()


# ---------------------------------------------------------------------------
# One Java worker run for the whole module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    """Native writes in this process, then every Java request in one worker.

    Returns ``{"root", "java": {key: [results]}, "native": {key: error or None}}``.
    """
    # Module scope runs before the function-level fixture that clears the environment
    # override, so clear it here too: the native writes below must be native.
    saved_env = os.environ.pop(_backend.ENV_VAR, None)
    saved_backend = RasDss.backend
    try:
        return _build_work(tmp_path_factory)
    finally:
        RasDss.backend = saved_backend
        if saved_env is not None:
            os.environ[_backend.ENV_VAR] = saved_env


def _build_work(tmp_path_factory):
    root = tmp_path_factory.mktemp("write_times")
    native = {}
    java_jobs = {}

    def job(key, *requests):
        java_jobs[key] = list(requests)

    for case, (e_part, times) in KEPT.items():
        for version in (7, 6):
            key = KEPT_KEY.format(case=case, version=version)
            nfile, jfile = root / f"n-{len(native)}.dss", root / f"j-{len(native)}.dss"
            try:
                _native_write(nfile, e_part, times, _values(len(times)), version)
                native[key] = (nfile, None)
            except Exception as exc:  # noqa: BLE001
                native[key] = (nfile, exc)
            reqs = [{"op": "write_timeseries", "kwargs": dict(
                dss_file=jfile, pathname=_path(e_part), times=times,
                values=_values(len(times)), dss_version=version)}]
            if "WEEK" not in e_part or version == 7:  # Java drops the first DSS6 weekly value (D8)
                reqs.append({"op": "read_times", "kwargs": dict(dss_file=jfile, pathname=_path(e_part))})
                if native[key][1] is None:
                    reqs.append({"op": "read_times", "kwargs": dict(dss_file=nfile, pathname=_path(e_part))})
            job(key, *reqs)
            native[key] = native[key] + (jfile,)
    for case, (e_part, times, _) in SHIFTED.items():
        for version in (7, 6):
            jfile = root / f"js-{case[:12].replace(' ', '_')}-{version}-{len(java_jobs)}.dss"
            job(f"shifted|{case}|v{version}", {"op": "write_timeseries", "kwargs": dict(
                dss_file=jfile, pathname=_path(e_part), times=times,
                values=_values(len(times)), dss_version=version)})
            native[f"shifted|{case}|v{version}"] = (jfile,)
    for case, (e_part, version, time, _) in SINGLE_MOVED.items():
        jfile = root / f"jsm-{len(java_jobs)}.dss"
        job(f"single_moved|{case}", {"op": "write_timeseries", "kwargs": dict(
            dss_file=jfile, pathname=_path(e_part), times=_t(time), values=[42.0],
            dss_version=version)})
        native[f"single_moved|{case}"] = (jfile,)
    for case, (e_part, versions, time) in SINGLE_KEPT.items():
        for version in versions:
            jfile = root / f"jsk-{len(java_jobs)}.dss"
            reqs = [{"op": "write_timeseries", "kwargs": dict(
                dss_file=jfile, pathname=_path(e_part), times=_t(time), values=[42.0],
                dss_version=version)}]
            if "WEEK" not in e_part or version == 7:
                reqs.append({"op": "read_times", "kwargs": dict(dss_file=jfile, pathname=_path(e_part))})
            job(f"single_kept|{case}|v{version}", *reqs)
    # Proof: with the check disabled, HEC Monolith moves these (one worker run; the
    # disabling op comes last so every other request above runs with the check).
    proof = []
    for case, (e_part, version, times) in MOVED_WITHOUT_CHECK.items():
        jfile = root / f"jp-{len(proof)}.dss"
        proof.append((case, [
            {"op": "write_timeseries", "kwargs": dict(
                dss_file=jfile, pathname=_path(e_part), times=times,
                values=_values(len(times)), dss_version=version)},
            {"op": "read_times", "kwargs": dict(dss_file=jfile, pathname=_path(e_part))}]))

    flat, keys = [], []
    for key, reqs in java_jobs.items():
        for r in reqs:
            flat.append(r)
            keys.append(key)
    # Review 2 reproduction: no engine in the worker, Java selected (before the proof
    # requests below; the engine stays disabled for the rest of that worker run, which
    # the proof requests do not need).
    flat.append({"op": "disable_engine"})
    keys.append("disable_engine")
    refused_file, opt_out_file = root / "noengine-refused.dss", root / "noengine-optout.dss"
    for request in (
        {"op": "write_timeseries", "kwargs": dict(
            dss_file=refused_file, pathname=_path("1MON"), times=_t("2020-02-29"), values=[42.0])},
        {"op": "write_timeseries", "kwargs": dict(
            dss_file=opt_out_file, pathname=_path("1MON"), times=_t("2020-02-29"), values=[42.0],
            allow_unverified_calendar_times=True)},
        {"op": "read_times", "kwargs": dict(dss_file=opt_out_file, pathname=_path("1MON"))},
    ):
        flat.append(request)
        keys.append("no_engine")
    flat.append({"op": "disable_time_check"})
    keys.append("disable")
    for case, reqs in proof:
        for r in reqs:
            flat.append(r)
            keys.append(f"proof|{case}")
    results = _run_worker(root, flat)
    java = {}
    if results is not None:
        for key, res in zip(keys, results):
            java.setdefault(key, []).append(res)
    return {"root": root, "java": java, "native": native, "java_available": results is not None}


def _run_worker(root: Path, requests):
    req_path, out_path = root / "requests.pkl", root / "results.pkl"
    with open(req_path, "wb") as fh:
        pickle.dump(requests, fh)
    env = {k: v for k, v in os.environ.items() if k != _backend.ENV_VAR}
    proc = subprocess.run([sys.executable, str(WORKER), str(req_path), str(out_path)],
                          capture_output=True, text=True, errors="replace", timeout=1800, env=env)
    if proc.returncode == 77 or "R1_BRIDGE_UNAVAILABLE" in proc.stdout:
        return None
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    with open(out_path, "rb") as fh:
        return pickle.load(fh)


def _java(work, key):
    if not work["java_available"]:
        pytest.skip("Java bridge unavailable (pyjnius, Java or HEC Monolith)")
    return work["java"][key]


def _as_times(times):
    return [str(t) for t in pd.DatetimeIndex(times)]


# ---------------------------------------------------------------------------
# Kept and shifted multi-value series
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [7, 6])
@pytest.mark.parametrize("case", list(KEPT))
def test_times_hec_keeps_are_written_by_native_and_read_back_exactly(work, case, version):
    e_part, times = KEPT[case]
    nfile, error, _ = work["native"][KEPT_KEY.format(case=case, version=version)]
    if version == 6 and case in ENGINE_DSS6_GAP and not ENGINE_DSS6_FIXED:
        assert isinstance(error, ValueError) and "not regular" in str(error)
        pytest.xfail("ras-commander-fast-dss 0.1.2 refuses DSS6 yearly times HEC keeps (EG2)")
    assert error is None, error
    got_times, got_values = _native_read(nfile, e_part)
    assert got_times == _as_times(times)
    np.testing.assert_array_equal(got_values, _values(len(times)))


@pytest.mark.parametrize("version", [7, 6])
@pytest.mark.parametrize("case", list(KEPT))
def test_times_hec_keeps_are_written_by_java_and_read_back_exactly(work, case, version):
    e_part, times = KEPT[case]
    results = _java(work, KEPT_KEY.format(case=case, version=version))
    assert results[0] == {"result": None}, results[0]
    expected = (_as_times(times), list(_values(len(times))))
    for res in results[1:]:  # Java reads of the Java file and of the native file
        assert res == {"result": expected}, res
    if results[1:] or ("WEEK" in e_part and version == 6):
        jfile = work["native"][KEPT_KEY.format(case=case, version=version)][2]
        if version == 6 and case in ENGINE_DSS6_GAP and not ENGINE_DSS6_FIXED:
            pytest.xfail("ras-commander-fast-dss 0.1.2 reads these DSS6 yearly times a day early (EG2)")
        assert _native_read(jfile, e_part) == expected  # native reader of the HEC-written file


@pytest.mark.parametrize("version", [7, 6])
@pytest.mark.parametrize("case", list(SHIFTED))
def test_times_hec_would_move_are_refused_by_native_before_writing(tmp_path, case, version):
    e_part, times, match = SHIFTED[case]
    target = tmp_path / "shifted.dss"
    with pytest.raises(ValueError, match="Refused before writing") as caught:
        _native_write(target, e_part, times, _values(len(times)), version)
    assert match in str(caught.value)
    assert not target.exists()


@pytest.mark.parametrize("version", [7, 6])
@pytest.mark.parametrize("case", list(SHIFTED))
def test_times_hec_would_move_are_refused_by_java_before_writing(work, case, version):
    (result,) = _java(work, f"shifted|{case}|v{version}")
    assert result["error"][0] == "ValueError", result
    assert "Refused before writing" in result["error"][1]
    assert SHIFTED[case][2] in result["error"][1]
    assert not work["native"][f"shifted|{case}|v{version}"][0].exists()


def test_shadow_refuses_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "shadow")
    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: (_ for _ in ()).throw(
        AssertionError("the check must refuse before any Java call"))))
    e_part, times, _ = SHIFTED["monthly 30th with 29 February (PR #863 review)"]
    with pytest.raises(ValueError, match="Refused before writing"):
        RasDss.write_timeseries(tmp_path / "s.dss", _path(e_part), times, _values(len(times)))
    assert not (tmp_path / "s.dss").exists()


def test_dataframe_writer_is_checked_too(tmp_path):
    e_part, times, _ = SHIFTED["irregular hourly step (PR #863 review)"]
    frame = pd.DataFrame({"value": _values(len(times))}, index=times)
    with pytest.raises(ValueError, match="value 1 is at"):
        RasDss.write_timeseries_from_dataframe(tmp_path / "df.dss", _path(e_part), frame)
    assert not (tmp_path / "df.dss").exists()


def test_existing_file_is_unchanged_by_a_refusal(tmp_path):
    import hashlib

    target = tmp_path / "existing.dss"
    _native_write(target, "1HOUR", HOURS, _values(6), 7)
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Refused before writing"):
        _native_write(target, "1MON", _t("2020-02-29"), [1.0], None)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_existing_dss6_file_decides_the_dss6_rules(tmp_path):
    """``dss_version`` omitted: the existing file's version applies (here DSS6)."""
    target = tmp_path / "v6.dss"
    _native_write(target, "1HOUR", HOURS, _values(6), 6)
    with pytest.raises(ValueError, match="to a DSS6 file"):
        _native_write(target, "1YEAR", LEAP_YEARLY["leap year, 15 June"], _values(3), None)


@pytest.mark.parametrize("case", list(MOVED_WITHOUT_CHECK))
def test_java_moves_the_refused_cases_without_the_check(work, case):
    """Why the check exists: HEC Monolith stores these values at other times."""
    write, read = _java(work, f"proof|{case}")
    assert write == {"result": None}, write
    times = MOVED_WITHOUT_CHECK[case][2]
    assert read["result"][0] != _as_times(times)


# ---------------------------------------------------------------------------
# DSS6 leap-year rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", list(LEAP_YEARLY))
def test_dss6_yearly_from_late_in_a_leap_year_is_refused(tmp_path, case):
    times = LEAP_YEARLY[case]
    with pytest.raises(ValueError, match="DSS6 file"):
        _native_write(tmp_path / "leap6.dss", "1YEAR", times, _values(3), 6)
    assert not (tmp_path / "leap6.dss").exists()


@pytest.mark.parametrize("case", list(LEAP_YEARLY))
def test_dss7_yearly_from_late_in_a_leap_year_is_kept(tmp_path, case):
    times = LEAP_YEARLY[case]
    target = tmp_path / "leap7.dss"
    _native_write(target, "1YEAR", times, _values(3), 7)
    assert _native_read(target, "1YEAR") == (_as_times(times), list(_values(3)))


@pytest.mark.parametrize("case", list(DSS6_YEARLY_EDGE))
def test_dss6_yearly_up_to_the_leap_boundary_is_not_refused_by_the_check(case):
    stamps = DSS6_YEARLY_EDGE[case].to_numpy(dtype="datetime64[s]")
    _times.check_regular_stamps(_path("1YEAR"), "1YEAR", stamps, 6)


def test_one_and_two_dss6_yearly_values_from_the_same_leap_start_are_refused(tmp_path):
    for times in (_t("2020-06-15"), _t("2020-06-15", "2021-06-15")):
        with pytest.raises(ValueError, match="DSS6 file"):
            _native_write(tmp_path / "leap.dss", "1YEAR", times, _values(len(times)), 6)
    assert not (tmp_path / "leap.dss").exists()


def test_the_dss6_leap_message_names_a_remedy_that_works(tmp_path):
    times = LEAP_YEARLY["leap year, 15 June"]
    with pytest.raises(ValueError, match="DSS7 file") as caught:
        _native_write(tmp_path / "a.dss", "1YEAR", times, _values(3), 6)
    assert "2020-06-16" in str(caught.value)
    target = tmp_path / "b.dss"
    _native_write(target, "1YEAR", times, _values(3), 7)
    assert _native_read(target, "1YEAR") == (_as_times(times), list(_values(3)))


# ---------------------------------------------------------------------------
# Single values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", list(SINGLE_MOVED))
def test_a_single_value_hec_would_move_is_refused_by_native(tmp_path, case):
    e_part, version, time, stored_at = SINGLE_MOVED[case]
    with pytest.raises(ValueError, match="Refused before writing") as caught:
        _native_write(tmp_path / "one.dss", e_part, _t(time), [42.0], version)
    assert not (tmp_path / "one.dss").exists()
    if stored_at:
        assert stored_at in str(caught.value)
    assert "separately" not in str(caught.value)


@pytest.mark.parametrize("case", list(SINGLE_MOVED))
def test_a_single_value_hec_would_move_is_refused_by_java(work, case):
    (result,) = _java(work, f"single_moved|{case}")
    assert result["error"][0] == "ValueError" and "Refused before writing" in result["error"][1]
    assert not work["native"][f"single_moved|{case}"][0].exists()


@pytest.mark.parametrize("case", list(SINGLE_KEPT))
def test_a_single_value_hec_keeps_is_written_at_its_time(tmp_path, case):
    e_part, versions, time = SINGLE_KEPT[case]
    for version in versions:
        target = tmp_path / f"one{version}.dss"
        _native_write(target, e_part, _t(time), [42.0], version)
        assert _native_read(target, e_part) == (_as_times(_t(time)), [42.0])


@pytest.mark.parametrize("case", list(SINGLE_KEPT))
def test_a_single_value_hec_keeps_is_written_by_java_at_its_time(work, case):
    e_part, versions, time = SINGLE_KEPT[case]
    for version in versions:
        results = _java(work, f"single_kept|{case}|v{version}")
        assert results[0] == {"result": None}, results[0]
        for res in results[1:]:
            assert res == {"result": (_as_times(_t(time)), [42.0])}, res


def test_dss6_only_single_offsets_are_still_refused_in_dss7(tmp_path):
    with pytest.raises(ValueError, match="2019-02-01"):
        _native_write(tmp_path / "x7.dss", "1MON", _t("2019-01-31"), [42.0], 7)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def test_a_dss6_over_refusal_says_the_version_does_not_help(tmp_path):
    times = _t("2019-01-31", "2019-03-03", "2019-03-31")   # kept by HEC-DSS 6
    for version in (6, 7):
        with pytest.raises(ValueError) as caught:
            _native_write(tmp_path / f"o{version}.dss", "1MON", times, _values(3), version)
        text = str(caught.value)
        assert "Changing the DSS version does not help" in text
        assert ("cannot write those times" in text) is (version == 6)


@pytest.mark.parametrize("case", list(VERSION_ADVICE))
def test_the_version_advice_in_each_refusal_is_true(tmp_path, case):
    e_part, version, times, advice = VERSION_ADVICE[case]
    times = _t(*times)
    values = _values(len(times))
    with pytest.raises(ValueError) as caught:
        _native_write(tmp_path / "refused.dss", e_part, times, values, version)
    text = str(caught.value)
    assert not (tmp_path / "refused.dss").exists()
    other = 6 if version == 7 else 7
    if advice == "none":
        assert "Changing the DSS version does not help" in text
        with pytest.raises(ValueError):
            _native_write(tmp_path / "other.dss", e_part, times, values, other)
        assert ("cannot write those times" in text) is (version == 6)
    else:
        assert "does not help" not in text
        assert f"DSS{other} file" in text and "works" in text
        target = tmp_path / "advised.dss"
        _native_write(target, e_part, times, values, other)
        assert _native_read(target, e_part) == (_as_times(times), list(values))


def test_fixed_interval_refusal_names_the_remedies():
    with pytest.raises(ValueError, match="fill the gaps with NaN") as caught:
        _times.check_regular_stamps(_path("1HOUR"), "1HOUR",
                                    HOURS.delete(2).to_numpy(dtype="datetime64[s]"), 7)
    assert "IR-DAY" in str(caught.value)


# ---------------------------------------------------------------------------
# Scope and failure handling
# ---------------------------------------------------------------------------


def test_irregular_e_parts_are_not_checked(tmp_path):
    times = _t("2020-01-01 01:00", "2020-01-01 02:30", "2020-02-29")
    target = tmp_path / "ir.dss"
    _native_write(target, "IR-MONTH", times, _values(3), 7)
    assert _native_read(target, "IR-MONTH")[0] == _as_times(times)


def test_invalid_arguments_keep_the_writers_own_errors(tmp_path):
    with pytest.raises(ValueError, match="same length"):
        RasDss.write_timeseries(tmp_path / "x.dss", _path("1HOUR"), HOURS, [1.0])


class _BrokenEngine:
    """An engine whose placement probe fails (its temporary file cannot be created)."""

    @staticmethod
    def create(*args, **kwargs):
        raise OSError("disk full")

    write_timeseries = read_timeseries = staticmethod(lambda *a, **k: None)


class _OldEngine:
    """An engine too old to probe: its writer takes no ``times=``."""

    create = read_timeseries = staticmethod(lambda *a, **k: None)

    @staticmethod
    def write_timeseries(path, pathname, values, *, units, data_type, version):
        raise AssertionError("never called")


UNQUALIFIED = {
    "engine missing": lambda: None,
    "engine too old": lambda: _OldEngine(),
    "probe fails": lambda: _BrokenEngine(),
}
UNQUALIFIED_CAUSE = {
    "engine missing": "not installed or failed to load",
    "engine too old": "too old to probe",
    "probe fails": "probe failed (OSError: disk full)",
}


def _capability_error():
    from ras_commander.dss import _errors

    return _errors.get("DssCapabilityError")


def _forbid_writers(monkeypatch):
    """Any backend writer call fails the test: a refusal must come before them."""
    def boom(*args, **kwargs):
        raise AssertionError("a writer ran although the times were not qualified")

    for name in ("_write_timeseries_java", "_write_timeseries_native", "_write_timeseries_shadow"):
        monkeypatch.setattr(RasDss, name, staticmethod(boom))


@pytest.mark.parametrize("cause", list(UNQUALIFIED))
@pytest.mark.parametrize("backend", ["java", "native", "shadow"])
def test_unqualified_calendar_times_are_refused_before_the_target(tmp_path, monkeypatch,
                                                                  cause, backend):
    """PR #863 review 2: placement that cannot be qualified is refused, not written."""
    monkeypatch.setattr(_backend, "_maybe_native", UNQUALIFIED[cause])
    monkeypatch.setattr(RasDss, "backend", backend)
    _forbid_writers(monkeypatch)
    target = tmp_path / "new.dss"
    with pytest.raises(_capability_error(), match="Refused before writing") as caught:
        RasDss.write_timeseries(target, _path("1MON"), _t("2020-02-29"), [42.0])
    text = str(caught.value)
    assert UNQUALIFIED_CAUSE[cause] in text
    assert "ras-commander-fast-dss>=0.1.3" in text and "allow_unverified_calendar_times=True" in text
    assert not target.exists()


@pytest.mark.parametrize("cause", list(UNQUALIFIED))
def test_unqualified_calendar_times_leave_an_existing_file_unchanged(tmp_path, monkeypatch, cause):
    import hashlib

    target = tmp_path / "existing.dss"
    _native_write(target, "1HOUR", HOURS, _values(6), 7)
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.setattr(_backend, "_maybe_native", UNQUALIFIED[cause])
    monkeypatch.setattr(RasDss, "backend", "java")
    # Without the engine the existing file's version is read through Java; keep the JVM
    # out of this process (the Java side runs in the worker).
    monkeypatch.setattr(RasDss, "_get_file_version_java", staticmethod(lambda path: 7))
    _forbid_writers(monkeypatch)
    with pytest.raises(_capability_error()):
        RasDss.write_timeseries(target, _path("1YEAR"), _t("2020-01-01", "2021-01-01"), [1.0, 2.0])
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("cause", list(UNQUALIFIED))
def test_the_dataframe_writer_refuses_unqualified_calendar_times(tmp_path, monkeypatch, cause):
    monkeypatch.setattr(_backend, "_maybe_native", UNQUALIFIED[cause])
    monkeypatch.setattr(RasDss, "backend", "java")
    _forbid_writers(monkeypatch)
    frame = pd.DataFrame({"value": [1.0, 2.0]}, index=_t("2020-03-01", "2020-04-01"))
    with pytest.raises(_capability_error(), match=UNQUALIFIED_CAUSE[cause].split(" (")[0]):
        RasDss.write_timeseries_from_dataframe(tmp_path / "df.dss", _path("1MON"), frame)
    assert not (tmp_path / "df.dss").exists()


@pytest.mark.parametrize("cause", list(UNQUALIFIED))
def test_the_opt_out_warns_and_writes_unchecked(tmp_path, monkeypatch, caplog, cause):
    monkeypatch.setattr(_backend, "_maybe_native", UNQUALIFIED[cause])
    monkeypatch.setattr(RasDss, "backend", "java")
    calls = []
    monkeypatch.setattr(RasDss, "_write_timeseries_java",
                        staticmethod(lambda *args, **kwargs: calls.append(args)))
    frame = pd.DataFrame({"value": [42.0]}, index=_t("2020-02-29"))
    with caplog.at_level(logging.WARNING, logger="ras_commander.dss.RasDss"):
        RasDss.write_timeseries(tmp_path / "a.dss", _path("1MON"), _t("2020-02-29"), [42.0],
                                allow_unverified_calendar_times=True)
        RasDss.write_timeseries_from_dataframe(tmp_path / "b.dss", _path("1MON"), frame,
                                               allow_unverified_calendar_times=True)
    assert len(calls) == 2
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("allow_unverified_calendar_times=True" in w and UNQUALIFIED_CAUSE[cause].split(" (")[0] in w
               for w in warnings)


def test_the_opt_out_does_not_skip_a_check_that_can_run(tmp_path):
    """With a working engine, the opt-out changes nothing: moved times are still refused."""
    with pytest.raises(ValueError, match="Refused before writing"):
        RasDss.write_timeseries(tmp_path / "x.dss", _path("1MON"), _t("2020-02-29"), [42.0],
                                allow_unverified_calendar_times=True)
    assert not (tmp_path / "x.dss").exists()


def test_the_opt_out_does_not_skip_the_dss6_leap_rule(tmp_path, monkeypatch):
    """The DSS6 leap-year rule needs no engine and is never skipped."""
    monkeypatch.setattr(_backend, "_maybe_native", lambda: None)
    with pytest.raises(ValueError, match="DSS6 file"):
        RasDss.write_timeseries(tmp_path / "leap6.dss", _path("1YEAR"), LEAP_YEARLY["leap year, 15 June"],
                                _values(3), dss_version=6, allow_unverified_calendar_times=True)


@pytest.mark.parametrize("cause", list(UNQUALIFIED))
def test_fixed_intervals_and_irregular_series_need_no_engine(tmp_path, monkeypatch, cause):
    monkeypatch.setattr(_backend, "_maybe_native", UNQUALIFIED[cause])
    with pytest.raises(ValueError, match="value 3 is at"):
        _times.check_regular_stamps(_path("1HOUR"), "1HOUR",
                                    HOURS.delete(3).to_numpy(dtype="datetime64[s]"), 7)
    _times.check_regular_stamps(_path("1HOUR"), "1HOUR", HOURS.to_numpy(dtype="datetime64[s]"), 7)
    assert _times.write_stamps(_path("IR-MONTH"), _t("2020-02-29", "2020-03-31"), [1.0, 2.0]) is None


def test_java_with_no_engine_refuses_by_default_and_moves_with_the_opt_out(work):
    """The review 2 reproduction through HEC Monolith: Java selected, no engine. The
    default refuses before the file exists; the opt-out writes, and HEC Monolith stores
    the 29 February monthly value on 1 March (the documented risk of the opt-out)."""
    refused, written, read = _java(work, "no_engine")
    assert refused["error"][0] == "DssCapabilityError", refused
    assert "ras-commander-fast-dss>=0.1.3" in refused["error"][1]
    assert written == {"result": None}, written
    assert read["result"][0] == ["2020-03-01 00:00:00"]


def test_the_check_leaves_no_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    _times.check_regular_stamps(_path("1YEAR"), "1YEAR",
                                _t("2020-02-29", "2021-03-01").to_numpy(dtype="datetime64[s]"), 7)
    assert list(tmp_path.iterdir()) == []
