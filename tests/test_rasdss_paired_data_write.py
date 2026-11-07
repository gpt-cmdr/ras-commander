"""``RasDss.write_paired_data`` on the java, native and shadow backends.

The native backend writes in this process (no JVM). The Java backend writes the same
records in a worker process (``_rasdss_native_writes_java_worker.py``), which also reads
every Java-written and native-written record back through Java.

Real curves: flow-duration curves built from RasExamples ``BaldEagleCrkMulti2D`` gauge
series (the project holds no paired-data record), plus every curve of the public
fixtures in ``tests/fixtures/dss_native_public``.

Skips without ras_commander_fast_dss, without its writers, when the project cannot be
extracted, or when the Java bridge is unavailable.
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
FIXTURES = Path(__file__).parent / "fixtures" / "dss_native_public"
PROJECT = "BaldEagleCrkMulti2D"
SOURCE = "Bald_Eagle_Creek.dss"
UNITS = dict(x_units="PERCENT", y_units="CFS", x_type="PROB", y_type="LINEAR")
PD7 = "/BASIN/LOC/STAGE-DAMAGE///F/"
PDD7 = "/BASIN/LOC/FLOW-STAGE///DOUBLE/"
PD6 = "/A/B/STAGE-FLOW///SHORT/"
PDD6 = "/A/B/ELEV-STOR///LONG/"


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


def _java(requests, tmp: Path):
    """Run RasDss requests on the Java backend in one worker process."""
    req_path, out_path = tmp / "java_requests.pkl", tmp / "java_results.pkl"
    with open(req_path, "wb") as fh:
        pickle.dump(requests, fh)
    env = {k: v for k, v in os.environ.items() if k != _backend.ENV_VAR}
    proc = subprocess.run(
        [sys.executable, str(WORKER), str(req_path), str(out_path)],
        capture_output=True, text=True, errors="replace", timeout=900, env=env,
    )
    if proc.returncode == 77:
        pytest.skip(proc.stdout.strip())
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    with open(out_path, "rb") as fh:
        return pickle.load(fh)


def _flow_duration(frame: pd.DataFrame, n: int = 40) -> np.ndarray:
    """``n`` flows at evenly spaced exceedance positions of one real series."""
    flows = np.sort(frame["value"].dropna().to_numpy())[::-1]
    return flows[np.linspace(0, len(flows) - 1, n).astype(int)]


@pytest.fixture(scope="module")
def real_curves(tmp_path_factory):
    """(single-curve arrays, labelled multi-curve frame) from real gauge series."""
    root = tmp_path_factory.mktemp("rasdss_pd_project")
    try:
        project = Path(RasExamples.extract_project(PROJECT, output_path=root))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{PROJECT} could not be extracted: {exc}")
    source = project / SOURCE
    with dc.open(source) as handle:
        catalog = handle.catalog()
    curves, seen = {}, set()
    for pathname, rtype in zip(catalog.pathname, catalog.record_type):
        if int(rtype) not in (100, 105):
            continue
        parts = pathname.split("/")
        parts[4] = ""
        key = "/".join(parts)
        if key in seen or parts[3].upper() != "FLOW":
            continue
        seen.add(key)
        try:
            frame = RasDss._read_timeseries_native(source, key)
        except _errors.get("DssPathnameNotFoundError"):
            continue
        if frame["value"].notna().sum() >= 40:
            curves[parts[2][:30].strip()] = _flow_duration(frame)
        if len(curves) == 3:
            break
    assert len(curves) == 3
    exceedance = np.linspace(0.0, 100.0, 40)
    multi = pd.DataFrame(curves, index=pd.Index(exceedance, name="ordinate"))
    return exceedance, multi


def _write_cases(exceedance, multi):
    """Writes valid on both DSS versions: (pathname, kwargs without file or version)."""
    first = multi.iloc[:, 0].to_numpy()
    with_nan = first.copy()
    with_nan[3] = np.nan
    return [
        ("/BALD EAGLE/GAUGE/FREQ-FLOW///DOUBLE/", dict(x_values=exceedance, y_values=first, **UNITS)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW///FLOAT/",
         dict(x_values=exceedance.astype(np.float32), y_values=first.astype(np.float32), **UNITS)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW///CHOSEN FLOAT/",
         dict(x_values=exceedance, y_values=first, value_type="float", **UNITS)),
        ("/BALD EAGLE/ALL/FREQ-FLOW///LABELS/", dict(x_values=multi, **UNITS)),
        ("/BALD EAGLE/ALL/FREQ-FLOW///ARRAYS/",
         dict(x_values=exceedance, y_values=multi.to_numpy(), labels=list(multi.columns), **UNITS)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW///NAN/",
         dict(x_values=exceedance, y_values=with_nan, **UNITS)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW///BLANK META/", dict(x_values=exceedance, y_values=first)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW/D PART/E PART/REPLACED/",
         dict(x_values=exceedance, y_values=first, **UNITS)),
        ("/BALD EAGLE/GAUGE/FREQ-FLOW/D PART/E PART/REPLACED/",
         dict(x_values=exceedance[:10], y_values=first[:10].astype(np.float32) + 1, **UNITS)),
    ]


def _fixture_frames():
    """Every curve of the public fixtures, read natively (metadata in ``attrs``)."""
    frames = []
    for path, pathnames in ((FIXTURES / "synthetic_pd7.dss", (PD7, PDD7)),
                            (FIXTURES / "synthetic_pd6.dss", (PD6, PDD6))):
        for pathname in pathnames:
            frames.append((pathname, RasDss._read_paired_data_native(path, pathname)))
    return frames


def _no_file_attrs(frame: pd.DataFrame, *also) -> dict:
    return {k: v for k, v in frame.attrs.items() if k not in ("dss_file", *also)}


def _assert_same(a: pd.DataFrame, b: pd.DataFrame, *ignore):
    diffs, _ = _backend.compare_written_paired_data(a, b)
    diffs = [d for d in diffs if not any(d == f"attr:{key}" for key in ignore)]
    assert diffs == [], diffs


@pytest.fixture(scope="module")
def written(real_curves, tmp_path_factory):
    """The same records written natively and through Java, DSS6 and DSS7, with Java's
    read-back of every file."""
    tmp = tmp_path_factory.mktemp("rasdss_pd_write")
    exceedance, multi = real_curves
    cases = _write_cases(exceedance, multi)
    fixture_frames = _fixture_frames()
    files, java_requests, final = {}, [], {}
    with backend_as("native"):
        for version in (6, 7):
            native_file = tmp / f"native{version}.dss"
            java_file = tmp / f"java{version}.dss"
            files[version] = (native_file, java_file)
            for index, (pathname, kwargs) in enumerate(cases):
                dss_version = version if index == 0 else None
                RasDss.write_paired_data(native_file, pathname, dss_version=dss_version, **kwargs)
                java_requests.append(dict(op="write_paired_data", kwargs=dict(
                    dss_file=java_file, pathname=pathname, dss_version=dss_version, **kwargs)))
                final[pathname] = None
            for pathname, frame in fixture_frames:
                target = "/FIXTURE/" + pathname.split("/", 2)[2]
                RasDss.write_paired_data(native_file, target, frame)
                java_requests.append(dict(op="write_paired_data", kwargs=dict(
                    dss_file=java_file, pathname=target, x_values=frame)))
                final[target] = None
    pathnames = list(final)
    for version in (6, 7):
        native_file, java_file = files[version]
        for pathname in pathnames:
            read = pathname.upper() if version == 6 else pathname
            for dss_file in (native_file, java_file):
                java_requests.append(dict(op="read_paired_data", kwargs=dict(
                    dss_file=dss_file, pathname=read, ignore_d_part=False)))
    results = _java(java_requests, tmp)
    errors = [r for r in results if "error" in r]
    assert errors == [], errors
    reads = iter(results[-(2 * 2 * len(pathnames)):])
    java_reads = {}
    for version in (6, 7):
        for pathname in pathnames:
            java_reads[version, pathname, "native"] = next(reads)["result"]
            java_reads[version, pathname, "java"] = next(reads)["result"]
    return dict(files=files, pathnames=pathnames, java=java_reads, cases=cases)


@pytest.mark.parametrize("version", [6, 7])
def test_native_and_java_writes_read_equal_on_both_readers(written, version):
    native_file, java_file = written["files"][version]
    assert RasDss._get_file_version_native(native_file) == version
    assert RasDss._get_file_version_native(java_file) == version
    types_n, types_j = [
        {p.upper(): int(t) for p, t in zip(dc.open(f).catalog().pathname,
                                           dc.open(f).catalog().record_type)}
        for f in (native_file, java_file)
    ]
    assert types_n == types_j
    assert len(types_n) == len(written["pathnames"])
    for pathname in written["pathnames"]:
        read = pathname.upper() if version == 6 else pathname
        native_of_native = RasDss._read_paired_data_native(native_file, read, False)
        native_of_java = RasDss._read_paired_data_native(java_file, read, False)
        _assert_same(native_of_java, native_of_native)
        java_of_native = written["java"][version, pathname, "native"]
        java_of_java = written["java"][version, pathname, "java"]
        _assert_same(java_of_java, java_of_native)
        # Java and native read the native-written file the same (known reader differences
        # PD1, PD2, PD3 and PD4 aside). Same classification as a shadow read.
        java_of_native.attrs["dss_file"] = native_of_native.attrs["dss_file"]
        outcome, label, diffs = _backend.classify_paired_data(
            java_of_native, None, native_of_native, None
        )
        assert outcome in ("identical", "expected"), (pathname, label, diffs)


@pytest.mark.parametrize("version", [6, 7])
def test_written_records_store_the_input(written, real_curves, version):
    native_file, _ = written["files"][version]
    exceedance, multi = real_curves
    first = multi.iloc[:, 0].to_numpy()
    case = lambda f: f"/BALD EAGLE/{f}/"  # noqa: E731

    df = RasDss._read_paired_data_native(native_file, case("GAUGE/FREQ-FLOW///DOUBLE"), False)
    assert df.attrs["record_type"] == 205
    np.testing.assert_array_equal(df.index.to_numpy(), exceedance)
    np.testing.assert_array_equal(df.iloc[:, 0].to_numpy(), first)
    assert (df.attrs["x_units"], df.attrs["y_units"]) == ("PERCENT", "CFS")
    assert (df.attrs["x_type"], df.attrs["y_type"]) == ("PROB", "LINEAR")

    assert RasDss._read_paired_data_native(
        native_file, case("GAUGE/FREQ-FLOW///FLOAT"), False).attrs["record_type"] == 200
    chosen = RasDss._read_paired_data_native(
        native_file, case("GAUGE/FREQ-FLOW///CHOSEN FLOAT"), False)
    assert chosen.attrs["record_type"] == 200
    np.testing.assert_array_equal(chosen.iloc[:, 0].to_numpy(), first.astype(np.float32))

    labelled = RasDss._read_paired_data_native(native_file, case("ALL/FREQ-FLOW///LABELS"), False)
    assert list(labelled.columns) == [c.upper() if version == 6 else c for c in multi.columns] \
        or list(labelled.columns) == list(multi.columns)
    np.testing.assert_array_equal(labelled.to_numpy(), multi.to_numpy())

    nan = RasDss._read_paired_data_native(native_file, case("GAUGE/FREQ-FLOW///NAN"), False)
    assert np.isnan(nan.iloc[3, 0]) and np.isnan(nan.iloc[:, 0]).sum() == 1

    blank = RasDss._read_paired_data_native(native_file, case("GAUGE/FREQ-FLOW///BLANK META"), False)
    assert blank.attrs["x_units"].strip() == "" and blank.attrs["y_type"].strip() == ""

    # The second write replaced the first, with a type change, on both backends.
    replaced = "GAUGE/FREQ-FLOW/D PART/E PART/REPLACED"
    if version == 6:
        replaced = replaced.upper()
    df = RasDss._read_paired_data_native(native_file, case(replaced), False)
    assert df.shape == (10, 1) and df.attrs["record_type"] == 205


@pytest.mark.parametrize("version", [6, 7])
def test_fixture_frames_round_trip_through_the_writer(written, version):
    """Every fixture curve, labels and types included, comes back as read (time zone and,
    for DSS6 targets, an x precision of 0 aside)."""
    native_file, java_file = written["files"][version]
    for pathname, source in _fixture_frames():
        target = "/FIXTURE/" + pathname.split("/", 2)[2]
        read = target.upper() if version == 6 else target
        for dss_file in (native_file, java_file):
            df = RasDss._read_paired_data_native(dss_file, read, False)
            np.testing.assert_array_equal(df.index.to_numpy(), source.index.to_numpy())
            np.testing.assert_array_equal(df.to_numpy(), source.to_numpy())
            assert df.attrs["record_type"] == source.attrs["record_type"]
            assert df.attrs["labels"] == source.attrs["labels"] or version == 6
            assert list(df.columns) == list(source.columns) or version == 6
            assert df.attrs["x_parameter"] == source.attrs["x_parameter"]
            for key in ("x_units", "x_type", "y_units", "y_type"):
                assert df.attrs[key].strip() == source.attrs[key].strip()[:8 if version == 6 else None]


@pytest.mark.parametrize("version", [6, 7])
def test_read_write_read_is_identical_on_native(tmp_path, version):
    """A frame read from a written file writes back to the identical record."""
    labelled = pd.DataFrame(
        {"Existing": np.array([1.5, 2.5, 3.5], dtype=np.float32),
         "With Levee": np.array([0.5, 1.25, 2.0], dtype=np.float32)},
        index=pd.Index(np.array([10.0, 20.0, 30.0], dtype=np.float32), name="ordinate"),
    )
    with backend_as("native"):
        first = tmp_path / "first.dss"
        path = "/B/L/STAGE-DAMAGE///R/"
        RasDss.write_paired_data(first, path, labelled, x_units="FEET", y_units="$", x_type="LINEAR",
                                 y_type="LINEAR", x_precision=2, y_precision=3, dss_version=version)
        frame = RasDss.read_paired_data(first, path)
        second = tmp_path / "second.dss"
        RasDss.write_paired_data(second, path, frame, dss_version=version)
        again = RasDss.read_paired_data(second, path)
    assert frame.attrs["record_type"] == 200 and list(frame.columns) == ["Existing", "With Levee"]
    assert (frame.attrs["x_precision"], frame.attrs["y_precision"]) == (2, 3)
    _assert_same(frame, again)


# ---------------------------------------------------------------------------
# Java path: its differences, pinned (each in its own worker where order matters)
# ---------------------------------------------------------------------------


def test_java_truncates_and_replaces_where_native_refuses(tmp_path):
    def path(name):
        return tmp_path / name

    other = "//G/FLOW/01JAN2020/1HOUR/R/"
    x, y = [1.0, 2.0, 3.0], [10.0, 20.0, 30.0]
    requests = [
        dict(op="write_paired_data", kwargs=dict(
            dss_file=path("long6.dss"), pathname="/A/B/C-D///F/", x_values=x, y_values=y,
            x_units="LONGUNITSTR", y_type="CUMULATIVE", dss_version=6)),
        dict(op="read_paired_data", kwargs=dict(dss_file=path("long6.dss"), pathname="/A/B/C-D///F/")),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=path("long7.dss"), pathname="/A/B/C-D///F/", x_values=x, y_values=y,
            x_units="LONGUNITSTR", y_type="CUMULATIVE", dss_version=7)),
        dict(op="read_paired_data", kwargs=dict(dss_file=path("long7.dss"), pathname="/A/B/C-D///F/")),
        dict(op="write_timeseries", kwargs=dict(
            dss_file=path("over.dss"), pathname="//G/FLOW//1HOUR/R/",
            times=pd.date_range("2020-01-01 01:00", periods=3, freq="h"), values=y, dss_version=6)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=path("over.dss"), pathname=other, x_values=x, y_values=y)),
        dict(op="read_paired_data", kwargs=dict(dss_file=path("over.dss"), pathname=other)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=path("inf.dss"), pathname="/A/B/C-D///F/", x_values=x,
            y_values=[1.0, np.inf, 3.0], dss_version=7)),
        dict(op="read_paired_data", kwargs=dict(dss_file=path("inf.dss"), pathname="/A/B/C-D///F/")),
    ]
    results = _java(requests, tmp_path)
    assert [r for r in results if "error" in r] == []
    long6, long7, over, inf = results[1]["result"], results[3]["result"], results[6]["result"], results[8]["result"]
    assert (long6.attrs["x_units"], long6.attrs["y_type"]) == ("LONGUNIT", "CUMULATI")
    assert (long7.attrs["x_units"], long7.attrs["y_type"]) == ("LONGUNITSTR", "CUMULATIVE")
    assert over.iloc[:, 0].tolist() == y
    assert np.isinf(inf.iloc[1, 0])


def test_java_write_failures_and_file_checks(tmp_path):
    existing7 = tmp_path / "seven.dss"
    x, y = [1.0, 2.0], [3.0, 4.0]
    results = _java([
        dict(op="write_paired_data", kwargs=dict(
            dss_file=existing7, pathname="/A/B/C-D///F/", x_values=x, y_values=y, dss_version=7)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=existing7, pathname="/A/B/C-D///G/", x_values=x, y_values=y, dss_version=6)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=tmp_path / "missing.dss", pathname="/A/B/C-D///F/", x_values=x, y_values=y,
            create_if_missing=False)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=tmp_path, pathname="/A/B/C-D///F/", x_values=x, y_values=y)),
        dict(op="write_paired_data", kwargs=dict(
            dss_file=tmp_path / "many.dss", pathname="/A/B/C-D///F/", x_values=x,
            y_values=np.ones((2, 101)), dss_version=6)),
    ], tmp_path)
    assert "result" in results[0]
    assert results[1]["error"][0] == "ValueError"
    assert results[2]["error"][0] == "FileNotFoundError"
    assert results[3]["error"][0] == "IsADirectoryError"
    assert results[4]["error"][0] == "RuntimeError"
    assert not (tmp_path / "missing.dss").exists()


def test_dss6_precision_is_stored_and_kept_by_monolith(tmp_path):
    """W10: Monolith stores a DSS6 precision, then keeps it for later writes in the process
    that ask for none. Native stores what each write asks for."""
    x, y = [1.0, 2.0], [3.0, 4.0]
    p = "/A/B/C-D///F/"
    results = _java([
        dict(op="write_paired_data", kwargs=dict(dss_file=tmp_path / "unset.dss", pathname=p,
             x_values=x, y_values=y, dss_version=6)),
        dict(op="write_paired_data", kwargs=dict(dss_file=tmp_path / "set.dss", pathname=p,
             x_values=x, y_values=y, x_precision=2, y_precision=3, dss_version=6)),
        dict(op="write_paired_data", kwargs=dict(dss_file=tmp_path / "later.dss", pathname=p,
             x_values=x, y_values=y, dss_version=6)),
    ], tmp_path)
    assert [r for r in results if "error" in r] == []
    read = lambda name: RasDss._read_paired_data_native(tmp_path / name, p).attrs  # noqa: E731
    assert (read("unset.dss")["x_precision"], read("unset.dss")["y_precision"]) == (-1, -1)
    assert (read("set.dss")["x_precision"], read("set.dss")["y_precision"]) == (2, 3)
    assert (read("later.dss")["x_precision"], read("later.dss")["y_precision"]) == (2, 3)
    with backend_as("native"):
        RasDss.write_paired_data(tmp_path / "n1.dss", p, x, y, x_precision=2, y_precision=3,
                                 dss_version=6)
        RasDss.write_paired_data(tmp_path / "n2.dss", p, x, y, dss_version=6)
    assert (read("n1.dss")["x_precision"], read("n1.dss")["y_precision"]) == (2, 3)
    assert (read("n2.dss")["x_precision"], read("n2.dss")["y_precision"]) == (-1, -1)


# ---------------------------------------------------------------------------
# Shadow
# ---------------------------------------------------------------------------


def test_shadow_writes_match_and_refusals_are_labelled(real_curves, tmp_path):
    exceedance, multi = real_curves
    first = multi.iloc[:, 0].to_numpy()
    p = "/BALD EAGLE/GAUGE/FREQ-FLOW///R/"
    requests = [dict(op="set_backend", kwargs={"value": "shadow"}), dict(op="reset_shadow")]
    for version in (6, 7):
        target = tmp_path / f"shadow{version}.dss"
        requests += [
            # New file, then writes into the existing file.
            dict(op="write_paired_data", kwargs=dict(dss_file=target, pathname=p, x_values=exceedance,
                 y_values=first, dss_version=version, **UNITS)),
            dict(op="write_paired_data", kwargs=dict(dss_file=target, pathname=p.replace("/R/", "/M/"),
                 x_values=multi, **UNITS)),
            dict(op="write_paired_data", kwargs=dict(dss_file=target, pathname=p.replace("/R/", "/LOW/"),
                 x_values=exceedance, y_values=first, value_type="float", **UNITS)),
        ]
    long6 = tmp_path / "shadow6.dss"
    requests += [
        # W1: Java truncates or stores; native refuses.
        dict(op="write_paired_data", kwargs=dict(dss_file=long6, pathname=p.replace("/R/", "/LONG/"),
             x_values=exceedance, y_values=first, x_units="LONGUNITSTR")),
        dict(op="write_paired_data", kwargs=dict(dss_file=long6, pathname=p.replace("/R/", "/INF/"),
             x_values=[1.0, 2.0], y_values=[np.inf, 1.0])),
        dict(op="write_timeseries", kwargs=dict(dss_file=tmp_path / "ts.dss", pathname="//G/FLOW//1HOUR/R/",
             times=pd.date_range("2020-01-01 01:00", periods=3, freq="h"), values=[1.0, 2.0, 3.0],
             dss_version=6)),
        dict(op="write_paired_data", kwargs=dict(dss_file=tmp_path / "ts.dss",
             pathname="//G/FLOW/01JAN2020/1HOUR/R/", x_values=[1.0, 2.0], y_values=[3.0, 4.0])),
        dict(op="write_paired_data", kwargs=dict(dss_file=long6, pathname="/A/B/ELEV-STOR///BAR/",
             x_values=[1.0, 2.0], y_values=[3.0, 4.0], x_units="FT|NAVD-8")),
        # W10.
        dict(op="write_paired_data", kwargs=dict(dss_file=long6, pathname=p.replace("/R/", "/P1/"),
             x_values=[1.0, 2.0], y_values=[3.0, 4.0], x_precision=2, y_precision=3)),
        dict(op="write_paired_data", kwargs=dict(dss_file=long6, pathname=p.replace("/R/", "/P2/"),
             x_values=[1.0, 2.0], y_values=[3.0, 4.0])),
        # Java raises: the caller gets it, and there is no comparison.
        dict(op="write_paired_data", kwargs=dict(dss_file=tmp_path / "x.dss", pathname=p, x_values=[1.0],
             y_values=np.ones((1, 101)), dss_version=6)),
        dict(op="shadow_records"),
    ]
    results = _java(requests, tmp_path)
    records = results[-1]["result"]
    assert [r["error"][0] for r in results[:-1] if "error" in r] == ["RuntimeError"]
    writes = [r for r in records if r["operation"] == "write_paired_data"]
    assert [r["outcome"] for r in writes if r["outcome"] == "unexpected"] == []
    assert [r["outcome"] for r in writes[:6]] == ["identical"] * 6
    assert [r["label"] for r in writes[6:10]] == [_backend.WRITE_REFUSAL_LABEL] * 4
    assert writes[10]["outcome"] == "identical"
    assert writes[11]["outcome"] == "expected"
    assert writes[11]["label"] == _backend.PAIRED_PRECISION_LABEL
    assert len(writes) == 12
    # The Java result stands: the truncated record is in the file.
    assert RasDss._read_paired_data_native(
        long6, p.replace("/R/", "/LONG/"), False).attrs["x_units"] == "LONGUNIT"


def _java_as_native(dss_file, pathname, spec, create_if_missing=True, *, dss_version=None):
    RasDss._write_paired_data_native(dss_file, pathname, spec, create_if_missing,
                                     dss_version=dss_version)


def test_shadow_skips_large_targets_and_missing_writers(monkeypatch, tmp_path):
    monkeypatch.setattr(RasDss, "_write_paired_data_java", staticmethod(_java_as_native))
    x, y, p = [1.0, 2.0], [3.0, 4.0], "/A/B/C-D///F/"
    target = tmp_path / "t.dss"
    with backend_as("shadow"):
        _backend.reset_shadow_stats()
        RasDss.write_paired_data(target, p, x, y)
        assert _backend.SHADOW_RECORDS[-1]["outcome"] == "identical"
        monkeypatch.setattr(RasDss, "shadow_copy_limit_mb", 0)
        RasDss.write_paired_data(target, p.replace("/F/", "/G/"), x, y)
        assert _backend.SHADOW_RECORDS[-1]["outcome"] == "skipped"
        assert "copy limit" in _backend.SHADOW_RECORDS[-1]["label"]
        monkeypatch.setattr(RasDss, "shadow_copy_limit_mb", 256)
        monkeypatch.setattr(_backend, "native_writes_available", lambda: False)
        monkeypatch.setattr(RasDss, "_write_paired_data_java", staticmethod(
            lambda *a, **k: None))
        RasDss.write_paired_data(target, p.replace("/F/", "/H/"), x, y)
        assert _backend.SHADOW_RECORDS[-1]["outcome"] == "skipped"
        assert _backend.SHADOW_RECORDS[-1]["label"] == _backend.NATIVE_WRITERS_MISSING_LABEL


def test_shadow_comparison_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(RasDss, "_write_paired_data_java", staticmethod(_java_as_native))

    def boom(*a, **k):
        raise RuntimeError("comparison failed")

    monkeypatch.setattr(RasDss, "_shadow_compare_paired_data_write", staticmethod(boom))
    with backend_as("shadow"):
        RasDss.write_paired_data(tmp_path / "t.dss", "/A/B/C-D///F/", [1.0, 2.0], [3.0, 4.0])
    assert (tmp_path / "t.dss").exists()


def test_shadow_labels_a_real_difference_unexpected(monkeypatch, tmp_path):
    def other_values(dss_file, pathname, spec, create_if_missing=True, *, dss_version=None):
        spec = {**spec, "y": spec["y"] + 1.0}
        _java_as_native(dss_file, pathname, spec, create_if_missing, dss_version=dss_version)

    monkeypatch.setattr(RasDss, "_write_paired_data_java", staticmethod(other_values))
    with backend_as("shadow"):
        _backend.reset_shadow_stats()
        RasDss.write_paired_data(tmp_path / "t.dss", "/A/B/C-D///F/", [1.0, 2.0], [3.0, 4.0])
    record = _backend.SHADOW_RECORDS[-1]
    assert record["outcome"] == "unexpected"
    assert "curve_bits:0" in record["diffs"]


# ---------------------------------------------------------------------------
# Refusals and the capability gate (no JVM)
# ---------------------------------------------------------------------------


@pytest.fixture
def native(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", "native")

    def _no_jvm():
        raise AssertionError("native writes must not configure the JVM")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_no_jvm))


X, Y, P = [1.0, 2.0, 3.0], [10.0, 20.0, 30.0], "/A/B/STAGE-FLOW///F/"


@pytest.mark.parametrize("version, kwargs, error", [
    (6, dict(x_units="LONGUNITSTR"), ValueError),
    (6, dict(y_type="CUMULATIVE"), ValueError),
    (6, dict(labels=["L" * 101]), ValueError),
    (6, dict(labels=["ABC  "]), ValueError),
    (6, dict(labels=["        X"]), ValueError),
    (6, dict(x_precision=0, y_precision=3), ValueError),
    (6, dict(pathname="/A/Bé/STAGE-FLOW///F/"), ValueError),
    (7, dict(pathname="/A/Bé/STAGE-FLOW///F/"), ValueError),
    (6, dict(y_values=[1.0, np.inf, 3.0]), ValueError),
    (7, dict(y_values=[1.0, np.inf, 3.0]), ValueError),
    (7, dict(x_values=[1.0, np.inf, 3.0]), ValueError),
    (7, dict(y_values=[1.0, 1e300, 3.0], value_type="float"), ValueError),
    (6, dict(y_values=np.ones((3, 101))), ValueError),
    (7, dict(pathname="/A/B/ELEV-STORAGE///F/", x_units="FT|NAVD-88"), "DssUnsupportedRecordError"),
    (6, dict(pathname="/A/B/ELEV-STORAGE///F/", x_units="FT|NAVD"), "DssUnsupportedRecordError"),
])
def test_native_refusals_leave_no_new_file(native, tmp_path, version, kwargs, error):
    if isinstance(error, str):
        error = _errors.get(error)
    target = tmp_path / "deep" / "refused.dss"
    args = {"pathname": P, "x_values": X, "y_values": Y, **kwargs}
    with pytest.raises(error):
        RasDss.write_paired_data(target, dss_version=version, **args)
    assert not target.exists()
    assert not target.parent.exists()


def test_native_refusal_leaves_an_existing_file_unchanged(native, tmp_path):
    target = tmp_path / "keep.dss"
    RasDss.write_paired_data(target, P, X, Y, dss_version=6)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="units"):
        RasDss.write_paired_data(target, P, X, Y, x_units="LONGUNITSTR")
    assert target.read_bytes() == before


def test_native_refuses_a_record_of_another_kind(native, tmp_path):
    target = tmp_path / "ts.dss"
    RasDss.write_timeseries(target, "//G/FLOW//1HOUR/R/",
                            pd.date_range("2020-01-01 01:00", periods=3, freq="h"), Y, dss_version=6)
    before = target.read_bytes()
    with pytest.raises(_errors.get("DssUnsupportedRecordError")):
        RasDss.write_paired_data(target, "//G/FLOW/01JAN2020/1HOUR/R/", X, Y)
    assert target.read_bytes() == before


def test_native_file_checks(native, tmp_path):
    with pytest.raises(FileNotFoundError):
        RasDss.write_paired_data(tmp_path / "no.dss", P, X, Y, create_if_missing=False)
    with pytest.raises(IsADirectoryError):
        RasDss.write_paired_data(tmp_path, P, X, Y)
    target = tmp_path / "seven.dss"
    RasDss.write_paired_data(target, P, X, Y)
    assert RasDss.get_file_version(target) == 7
    with pytest.raises(ValueError, match="version 7"):
        RasDss.write_paired_data(target, P, X, Y, dss_version=6)


def test_inherited_dss6_precision_zero_does_not_block_a_copy(native, tmp_path):
    """Explicit x_precision=0 is refused on DSS6; a frame from the DSS6 reader may carry
    it, and copying that frame stores unset precision instead."""
    frame = pd.DataFrame({"A": Y}, index=pd.Index(X, name="ordinate"))
    frame.attrs.update(x_precision=0, y_precision=0, x_units="FEET", y_units="CFS")
    six, seven = tmp_path / "six.dss", tmp_path / "seven.dss"
    RasDss.write_paired_data(six, P, frame, dss_version=6)
    RasDss.write_paired_data(seven, P, frame)
    assert RasDss.read_paired_data(six, P).attrs["x_precision"] == -1
    assert RasDss.read_paired_data(seven, P).attrs["x_precision"] == 0


@pytest.mark.parametrize("backend", ["java", "native"])
@pytest.mark.parametrize("args, error", [
    (dict(pathname="/A/B/C/"), ValueError),
    (dict(pathname="/A/B/C/D/E/F/G/"), ValueError),
    (dict(pathname=3), TypeError),
    (dict(x_values=[]), ValueError),
    (dict(x_values=[[1.0, 2.0, 3.0]]), ValueError),
    (dict(y_values=[1.0, 2.0]), ValueError),
    (dict(y_values=np.ones((3, 2, 1))), ValueError),
    (dict(y_values=np.ones((3, 0))), ValueError),
    (dict(y_values=None), ValueError),
    (dict(x_values=["a", "b", "c"]), ValueError),
    (dict(y_values=[True, False, True]), ValueError),
    (dict(labels="ABC"), ValueError),
    (dict(labels=["A", "B"]), ValueError),
    (dict(labels=[1]), TypeError),
    (dict(x_units=3), TypeError),
    (dict(x_precision=2), ValueError),
    (dict(x_precision=10, y_precision=2), ValueError),
    (dict(x_precision=-1, y_precision=2), ValueError),
    (dict(value_type="float16"), ValueError),
    (dict(dss_version=8), ValueError),
])
def test_invalid_arguments_raise_the_same_class_before_any_file_or_jvm(
    monkeypatch, tmp_path, backend, args, error
):
    def _no_jvm():
        raise AssertionError("invalid arguments must not reach the JVM")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_no_jvm))
    target = tmp_path / "t.dss"
    with backend_as(backend):
        with pytest.raises(error):
            RasDss.write_paired_data(**{"dss_file": target, "pathname": P, "x_values": X,
                                        "y_values": Y, **args})
    assert not target.exists()


def test_frame_with_y_values_is_refused(native, tmp_path):
    frame = pd.DataFrame({"A": Y}, index=X)
    with pytest.raises(ValueError, match="omitted"):
        RasDss.write_paired_data(tmp_path / "t.dss", P, frame, Y)


def test_frame_metadata_rules(native, tmp_path):
    target = tmp_path / "t.dss"
    frame = pd.DataFrame({"curve_1": Y, "curve_2": X}, index=pd.Index(X, name="ordinate"))
    frame.attrs.update(labels=["Base", ""], x_units="FEET", y_units="CFS", x_type="LINEAR",
                       y_type="LOG", x_precision=1, y_precision=2)
    RasDss.write_paired_data(target, P, frame)
    out = RasDss.read_paired_data(target, P)
    assert out.attrs["labels"] == ["Base", ""]
    assert (out.attrs["x_units"], out.attrs["y_type"]) == ("FEET", "LOG")
    assert (out.attrs["x_precision"], out.attrs["y_precision"]) == (1, 2)

    # Arguments win over attrs; a subset of curves keeps its column names.
    RasDss.write_paired_data(target, "/A/B/STAGE-FLOW///G/", frame[["curve_2"]].rename(
        columns={"curve_2": "Only"}), x_units="M", x_precision=-1, y_precision=-1)
    out = RasDss.read_paired_data(target, "/A/B/STAGE-FLOW///G/")
    assert out.attrs["labels"] == ["Only"] and out.attrs["x_units"] == "M"
    assert out.attrs["x_precision"] == -1

    # Stale attrs labels (not one per curve) with default names are not used.
    subset = frame[["curve_1"]]
    RasDss.write_paired_data(target, "/A/B/STAGE-FLOW///H/", subset)
    assert RasDss.read_paired_data(target, "/A/B/STAGE-FLOW///H/").attrs["labels"] == [""]

    # A Series is one curve, labelled by its name; default integer columns are not labels.
    series = pd.Series(Y, index=X, name="Named")
    RasDss.write_paired_data(target, "/A/B/STAGE-FLOW///I/", series)
    assert RasDss.read_paired_data(target, "/A/B/STAGE-FLOW///I/").attrs["labels"] == ["Named"]
    RasDss.write_paired_data(target, "/A/B/STAGE-FLOW///J/", pd.DataFrame(np.ones((3, 2)), index=X))
    assert RasDss.read_paired_data(target, "/A/B/STAGE-FLOW///J/").attrs["labels"] == ["", ""]


def test_native_write_is_gated_on_the_writer_api(native, monkeypatch, tmp_path):
    monkeypatch.delattr(dc, "write_paired_data")
    assert not _backend.native_writes_available()
    target = tmp_path / "gated.dss"
    with pytest.raises(_errors.get("DssCapabilityError"), match="native DSS writers"):
        RasDss.write_paired_data(target, P, X, Y)
    assert not target.exists()


def test_capabilities_list_the_writer():
    row = RasDss.get_capabilities().set_index("operation").loc["write_paired_data"]
    assert (row["java"], row["native"], row["shadow"]) == ("yes", "gated", "java")


def test_public_api_contract():
    import inspect

    raw = inspect.getattr_static(RasDss, "write_paired_data")
    assert isinstance(raw, staticmethod)
    assert hasattr(raw.__func__, "__wrapped__")  # @log_call
    doc = RasDss.write_paired_data.__doc__
    for section in ("Args:", "Returns:", "Raises:", "Example:"):
        assert section in doc
