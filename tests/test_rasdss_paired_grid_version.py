"""RasDss paired data, grids and file version on the java, native and shadow backends.

- Classification, capability and error-class tests need no optional dependency.
- Native tests use the synthetic public fixtures in ``tests/fixtures/dss_native_public``
  and skip without ``dss_commander``.
- Shadow tests run in-process with the Java variants replaced by recorded results.
- Java tests run HEC Monolith in ``_rasdss_pd_grid_java_worker.py`` (one JVM per
  process; HEC software can modify files it opens) on temporary copies, and skip when
  pyjnius, Java or Monolith is unavailable. They author their paired-data fixtures with
  Monolith at test time and sweep a sample of RasExamples paired-data records.
"""

import json
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import ras_commander.dss as dss_pkg
from ras_commander import RasDss
from ras_commander.dss import _backend, _errors

FIXTURES = Path(__file__).parent / "fixtures" / "dss_native_public"
WORKER = Path(__file__).with_name("_rasdss_pd_grid_java_worker.py")

PD7_PATH = "/BASIN/LOC/STAGE-DAMAGE///F/"
PDD7_PATH = "/BASIN/LOC/FLOW-STAGE///DOUBLE/"
TS7_PATH = "/BASIN/LOC/FLOW/01Jan2020/1Hour/TS/"
PD6_PATH = "/A/B/STAGE-FLOW///SHORT/"
PDD6_PATH = "/A/B/ELEV-STOR///LONG/"
MODERN_GRID = "/PUBLIC/MODERN/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTH/"
ALBERS_GRID = "/PUBLIC/ALBERS/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTH/"
UNTIMED_GRID = "/PUBLIC/UNTIMED/ELEVATION///SYNTH/"

PD_ATTR_KEYS = [
    "pathname", "record_pathname", "dss_file", "record_type", "dss_version",
    "stored_dtype", "n_ordinates", "n_curves", "x_parameter", "y_parameter",
    "x_units", "x_type", "y_units", "y_type", "labels", "x_precision",
    "y_precision", "time_zone",
]
GRID_KEYS = {
    "dss_file", "pathname", "data", "shape", "units", "data_type", "grid_type",
    "crs", "cell_size", "start_time", "end_time", "metadata", "row_order",
}


@pytest.fixture(autouse=True)
def _java_default(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", _backend.DEFAULT_BACKEND)
    _backend.reset_shadow_stats()
    yield
    _backend.reset_shadow_stats()


@pytest.fixture
def no_jvm(monkeypatch):
    def _raise(*_a, **_k):
        raise AssertionError("the JVM must not be configured on this path")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_raise))


@pytest.fixture
def fixtures(tmp_path):
    """Working copies of the synthetic fixtures."""
    out = {}
    for name in ("synthetic_pd6", "synthetic_pd7", "synthetic_grid6", "synthetic_grid7"):
        dst = tmp_path / f"{name}.dss"
        shutil.copyfile(FIXTURES / f"{name}.dss", dst)
        out[name] = dst
    return out


@pytest.fixture
def native(monkeypatch, no_jvm):
    pytest.importorskip("dss_commander")
    monkeypatch.setattr(RasDss, "backend", "native")


# ---------------------------------------------------------------------------
# Error classes and capabilities (no optional dependency)
# ---------------------------------------------------------------------------


def test_error_classes_keep_builtin_bases():
    e = _errors.classes()
    assert issubclass(e.DssError, RuntimeError)
    assert issubclass(e.DssPathnameNotFoundError, ValueError)
    assert issubclass(e.DssRecordTypeError, TypeError)
    assert issubclass(e.DssRecordTypeError, e.DssUnsupportedRecordError)
    assert issubclass(e.DssInvalidFileError, ValueError)
    assert issubclass(e.DssInvalidFileError, e.DssFormatError)
    assert issubclass(e.DssCapabilityError, NotImplementedError)
    assert issubclass(e.DssCapabilityError, e.DssError)
    for name in _errors.ERROR_NAMES:
        assert getattr(dss_pkg, name) is getattr(e, name)
        assert name in dss_pkg.__all__
    with pytest.raises(AttributeError):
        dss_pkg.NoSuchError  # noqa: B018


def test_error_classes_are_dss_commander_classes_when_installed():
    dc = pytest.importorskip("dss_commander")
    assert dss_pkg.DssPathnameNotFoundError is dc.DssPathnameNotFoundError
    assert dss_pkg.DssUnsupportedRecordError is dc.DssUnsupportedRecordError
    assert issubclass(dss_pkg.DssRecordTypeError, dc.DssUnsupportedRecordError)


def test_local_fallback_classes_have_the_same_contract():
    class BrokenModule:
        def __getattr__(self, name):
            raise OSError("simulated broken native extension")

    for dc in (None, BrokenModule()):
        local = _errors._build(dc)
        assert local.DssError.__module__ == "ras_commander.dss"
        assert issubclass(local.DssPathnameNotFoundError, ValueError)
        assert issubclass(local.DssRecordTypeError, local.DssUnsupportedRecordError)
        assert issubclass(local.DssRecordTypeError, TypeError)
        assert issubclass(local.DssReadError, local.DssFormatError)
        assert local.DssRecordTypeError.__qualname__ == "DssRecordTypeError"


def test_java_path_never_imports_dss_commander(tmp_path):
    """Resolving errors and running the Java dispatch must not load the native engine."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import os, sys\n"
        "os.environ.pop('RAS_COMMANDER_DSS_BACKEND', None)\n"
        "import ras_commander.dss as d\n"
        "from ras_commander import RasDss\n"
        "from ras_commander.dss import _errors\n"
        "assert RasDss.get_backend() == 'java'\n"
        "for name in _errors.ERROR_NAMES:\n"
        "    getattr(d, name)\n"
        "try:\n"
        "    RasDss.read_paired_data(sys.argv[1], '/A/B/C///F/')\n"
        "except FileNotFoundError:\n"
        "    pass\n"
        "print('IMPORTED' if 'dss_commander' in sys.modules else 'NOT_IMPORTED')\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "missing.dss")],
        capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip().splitlines()[-1] == "NOT_IMPORTED"


def test_broken_native_wheel_cannot_break_java(monkeypatch, no_jvm):
    """A native engine whose import raises OSError counts as absent."""
    import importlib

    real = importlib.import_module

    def broken(name, *a, **k):
        if name == "dss_commander":
            raise OSError("simulated DLL load failure")
        return real(name, *a, **k)

    monkeypatch.setattr(_backend.importlib, "import_module", broken)
    assert _backend._maybe_native() is None
    assert _backend.native_available() is False
    assert _backend.native_grid_qualified() is False
    assert _backend.native_writes_available() is False
    caps = RasDss.get_capabilities()
    assert caps.attrs["native_installed"] is False
    assert caps.attrs["native_writes_available"] is False
    monkeypatch.setattr(RasDss, "backend", "shadow")
    _backend.reset_fallback_warning()
    assert RasDss.get_backend() == "java"
    monkeypatch.setattr(RasDss, "backend", "native")
    with pytest.raises(ImportError) as exc:
        RasDss.get_backend()
    assert isinstance(exc.value.__cause__, OSError)


def test_capabilities_matrix(no_jvm):
    caps = RasDss.get_capabilities()
    assert list(caps.columns) == ["operation", "java", "native", "shadow", "note"]
    table = caps.set_index("operation")
    assert table.loc["read_paired_data", "native"] == "yes"
    assert table.loc["get_file_version", "native"] == "yes"
    assert table.loc["read_grid", "native"] == "gated"
    for op in ("write_timeseries", "write_timeseries_from_dataframe", "write_grid_timeseries",
               "copy_grid_with_zero_tail", "write_precip_grid_arrays"):
        assert table.loc[op, "native"] == "gated"
    assert table.loc["write_timeseries", "shadow"] == "java"
    assert set(caps.attrs) == {"requested_backend", "native_installed", "native_grid_qualified",
                               "native_writes_available"}
    assert caps.attrs["requested_backend"] == "java"


def test_native_grid_qualification_is_an_advertised_feature(monkeypatch):
    dc = pytest.importorskip("dss_commander")
    monkeypatch.setattr(dc, "FEATURES", frozenset(), raising=False)
    assert not _backend.native_grid_qualified()
    monkeypatch.setattr(dc, "FEATURES", frozenset({_backend.NATIVE_GRID_FEATURE}), raising=False)
    assert _backend.native_grid_qualified()
    monkeypatch.setattr(dc, "FEATURES", [_backend.NATIVE_GRID_FEATURE], raising=False)
    assert _backend.native_grid_qualified()
    monkeypatch.setattr(dc, "FEATURES", {_backend.NATIVE_GRID_FEATURE: False}, raising=False)
    assert not _backend.native_grid_qualified()
    monkeypatch.setattr(dc, "FEATURES", {_backend.NATIVE_GRID_FEATURE: True}, raising=False)
    assert _backend.native_grid_qualified()
    # A bare string is not a feature collection ("in" would match substrings).
    monkeypatch.setattr(dc, "FEATURES", _backend.NATIVE_GRID_FEATURE, raising=False)
    assert not _backend.native_grid_qualified()
    monkeypatch.setattr(dc, "FEATURES", [b"grid_srs_monolith_parity"], raising=False)
    assert not _backend.native_grid_qualified()


# ---------------------------------------------------------------------------
# Native backend (synthetic public fixtures)
# ---------------------------------------------------------------------------


def test_native_paired_data_schema_dss7(native, fixtures):
    df = RasDss.read_paired_data(fixtures["synthetic_pd7"], PD7_PATH)
    assert list(df.attrs) == PD_ATTR_KEYS
    assert list(df.columns) == ["Total", "Residential", "Commercial"]
    assert df.index.name == "ordinate"
    assert df.index.dtype == np.float32 and all(df.dtypes == np.float32)
    np.testing.assert_array_equal(df.index.to_numpy(), np.float32([1.0, 2.0, 3.5]))
    # Missing markers stay as stored.
    assert df["Commercial"].iloc[0] == np.float32(-901.0)
    a = df.attrs
    assert (a["record_type"], a["dss_version"], a["stored_dtype"]) == (200, 7, "float32")
    assert (a["n_ordinates"], a["n_curves"]) == (3, 3)
    assert (a["x_parameter"], a["y_parameter"]) == ("STAGE", "DAMAGE")
    assert (a["x_units"], a["x_type"], a["y_units"], a["y_type"]) == ("FEET", "Linear", "DOLLARS", "Log")
    assert (a["x_precision"], a["y_precision"], a["time_zone"]) == (2, 1, "UTC")
    assert a["record_pathname"] == PD7_PATH


def test_native_paired_data_keeps_stored_double_bits(native, fixtures):
    df = RasDss.read_paired_data(fixtures["synthetic_pd7"], PDD7_PATH)
    assert df.attrs["record_type"] == 205 and df.attrs["stored_dtype"] == "float64"
    assert list(df.columns) == ["curve_1"] and df.attrs["labels"] == [""]
    values = df["curve_1"].to_numpy()
    assert values[0] == np.finfo(np.float64).tiny
    assert values[1] == 0.0 and np.signbit(values[1])
    assert df.attrs["x_precision"] == -1


def test_native_paired_data_dss6_labels_and_widening(native, fixtures):
    df = RasDss.read_paired_data(fixtures["synthetic_pd6"], PD6_PATH)
    assert df.attrs["labels"] == ["  5%LIMIT", "MEDIAN"]  # leading blanks kept
    assert df.shape == (3, 2)
    wide = RasDss.read_paired_data(fixtures["synthetic_pd6"], PD6_PATH, dtype="float64")
    assert all(wide.dtypes == np.float64) and wide.index.dtype == np.float64
    np.testing.assert_array_equal(wide.to_numpy(), df.to_numpy().astype(np.float64))
    assert wide.attrs["stored_dtype"] == "float32"


def test_native_paired_data_ignores_d_part(native, fixtures):
    with_d = "/BASIN/LOC/STAGE-DAMAGE/01JAN2020//F/"
    df = RasDss.read_paired_data(fixtures["synthetic_pd7"], with_d)
    assert df.attrs["pathname"] == with_d and df.attrs["record_pathname"] == PD7_PATH
    with pytest.raises(dss_pkg.DssPathnameNotFoundError):
        RasDss.read_paired_data(fixtures["synthetic_pd7"], with_d, ignore_d_part=False)


def test_native_paired_data_errors(native, fixtures, tmp_path):
    f = fixtures["synthetic_pd7"]
    with pytest.raises(dss_pkg.DssPathnameNotFoundError) as nf:
        RasDss.read_paired_data(f, "/NO/SUCH/STAGE-FLOW///X/")
    assert isinstance(nf.value, ValueError)
    with pytest.raises(dss_pkg.DssRecordTypeError) as wrong:
        RasDss.read_paired_data(f, TS7_PATH)
    assert isinstance(wrong.value, TypeError)
    with pytest.raises(ValueError):
        RasDss.read_paired_data(f, PD7_PATH, dtype="float16")
    missing = tmp_path / "missing.dss"
    with pytest.raises(FileNotFoundError):
        RasDss.read_paired_data(missing, PD7_PATH)
    assert not missing.exists()


def test_native_file_version(native, fixtures, tmp_path):
    assert RasDss.get_file_version(fixtures["synthetic_pd6"]) == 6
    assert RasDss.get_file_version(str(fixtures["synthetic_grid7"])) == 7
    bad = tmp_path / "not_dss.dss"
    bad.write_bytes(b"not a dss file" * 64)
    with pytest.raises(dss_pkg.DssInvalidFileError) as exc:
        RasDss.get_file_version(bad)
    assert isinstance(exc.value, ValueError)
    with pytest.raises(FileNotFoundError):
        RasDss.get_file_version(tmp_path / "missing.dss")


def test_native_grid_is_gated_without_qualification(native, fixtures, monkeypatch):
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: False)
    with pytest.raises(dss_pkg.DssCapabilityError) as exc:
        RasDss.read_grid(fixtures["synthetic_grid7"], MODERN_GRID)
    assert isinstance(exc.value, NotImplementedError)
    assert "allow_unqualified_native" in str(exc.value)


def test_native_grid_opt_in_returns_read_grid_schema(native, fixtures, monkeypatch):
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: False)
    g = RasDss.read_grid(fixtures["synthetic_grid7"], MODERN_GRID, allow_unqualified_native=True)
    assert set(g) == GRID_KEYS
    assert g["row_order"] == "south_up" and g["shape"] == (3, 3)
    assert g["data"].dtype == np.float32
    # Native maps the grid null value and NaN payloads to NaN; row 0 is the south row.
    np.testing.assert_array_equal(g["data"][0], np.float32([0, 1, 2]))
    assert np.isnan(g["data"][1, 1]) and np.isnan(g["data"][2, 1])
    md = g["metadata"]
    assert md["crs_qualified"] is False
    assert md["grid_class"] == "hec.heclib.grid.SpecifiedGridInfo"
    assert md["grid_type_code"] == 430 and md["data_type_code"] == 1
    assert md["origin"] == (6.0, 26.0) and md["lower_left_cell"] == (-2, 3)
    assert g["start_time"] == pd.Timestamp("2020-01-01 00:00")
    assert md["timing"]["end"] == "1 January 2020, 01:00"


def test_native_grid_runs_when_wheel_advertises_qualification(native, fixtures, monkeypatch):
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: True)
    g = RasDss.read_grid(fixtures["synthetic_grid6"], ALBERS_GRID)
    assert g["grid_type"] == "albers" and g["metadata"]["projection"]["datum_code"] == 2
    untimed = RasDss.read_grid(fixtures["synthetic_grid6"], UNTIMED_GRID)
    assert untimed["start_time"] is None and untimed["metadata"]["timing"]["start"] is None


def test_native_grid_errors(native, fixtures, monkeypatch):
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: True)
    with pytest.raises(dss_pkg.DssPathnameNotFoundError):
        RasDss.read_grid(fixtures["synthetic_grid7"], MODERN_GRID.replace("MODERN", "NONE"))
    with pytest.raises(TypeError):
        RasDss.read_grid(fixtures["synthetic_pd7"], TS7_PATH)
    with pytest.raises(ValueError):
        RasDss.read_grid(fixtures["synthetic_grid7"], "/A/B/*/D/E/F/")


def test_midnight_end_time_text_matches_monolith():
    assert RasDss._format_hec_time_text(pd.Timestamp("2018-09-23"), end_of_period=True) == \
        "22 September 2018, 24:00"
    assert RasDss._format_hec_time_text(pd.Timestamp("2018-09-23")) == "23 September 2018, 00:00"


# ---------------------------------------------------------------------------
# Shadow (in-process, Java variants replaced)
# ---------------------------------------------------------------------------


@pytest.fixture
def shadow(monkeypatch):
    pytest.importorskip("dss_commander")
    monkeypatch.setattr(RasDss, "backend", "shadow")


def _records(operation):
    return [r for r in _backend.SHADOW_RECORDS if r["operation"] == operation]


def test_shadow_paired_data_identical_and_returns_native(shadow, fixtures, monkeypatch):
    f = fixtures["synthetic_pd7"]
    reference = RasDss._read_paired_data_native(f, PD7_PATH)
    java = reference.copy()
    java.attrs = dict(reference.attrs)
    monkeypatch.setattr(RasDss, "_read_paired_data_java", staticmethod(lambda *a, **k: java))
    out = RasDss.read_paired_data(f, PD7_PATH)
    assert out.attrs["time_zone"] == "UTC"
    rec = _records("read_paired_data")[-1]
    assert (rec["outcome"], rec["label"]) == ("identical", "identical")


def test_shadow_paired_data_known_and_unexpected(shadow, fixtures, monkeypatch, caplog):
    f = fixtures["synthetic_pd6"]
    native_df = RasDss._read_paired_data_native(f, PD6_PATH)
    java = native_df.copy()
    java.columns = ["5%LIMIT", "MEDIAN"]
    java.attrs = dict(native_df.attrs, labels=["5%LIMIT", "MEDIAN"], x_precision=-1, y_precision=-1)
    monkeypatch.setattr(RasDss, "_read_paired_data_java", staticmethod(lambda *a, **k: java))
    RasDss.read_paired_data(f, PD6_PATH)
    rec = _records("read_paired_data")[-1]
    assert rec["outcome"] == "expected"
    assert "PD1" in rec["label"] and "PD4" in rec["label"]

    changed = java.copy()
    changed.iloc[0, 0] = np.float32(99.0)
    changed.attrs = dict(java.attrs)
    monkeypatch.setattr(RasDss, "_read_paired_data_java", staticmethod(lambda *a, **k: changed))
    out = RasDss.read_paired_data(f, PD6_PATH)
    assert out.iloc[0, 0] == np.float32(10.0)  # native result returned
    rec = _records("read_paired_data")[-1]
    assert rec["outcome"] == "unexpected" and "curve_bits:0" in rec["diffs"]
    assert "UNEXPECTED" in caplog.text


def test_shadow_paired_data_never_raises_on_java_failure(shadow, fixtures, monkeypatch):
    def java_fails(*_a, **_k):
        raise RuntimeError("Java not found")

    monkeypatch.setattr(RasDss, "_read_paired_data_java", staticmethod(java_fails))
    df = RasDss.read_paired_data(fixtures["synthetic_pd7"], PD7_PATH)
    assert df.shape == (3, 3)
    assert _records("read_paired_data")[-1]["outcome"] == "skipped"


def test_shadow_paired_data_skips_java_for_wrong_type(shadow, fixtures, monkeypatch):
    def java_must_not_run(*_a, **_k):
        raise AssertionError("Java must not run")

    monkeypatch.setattr(RasDss, "_read_paired_data_java", staticmethod(java_must_not_run))
    with pytest.raises(dss_pkg.DssRecordTypeError):
        RasDss.read_paired_data(fixtures["synthetic_pd7"], TS7_PATH)
    assert _records("read_paired_data")[-1]["outcome"] == "skipped"


def test_shadow_grid_returns_java_and_classifies_crs(shadow, fixtures, monkeypatch):
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: False)
    f = fixtures["synthetic_grid7"]
    native_grid = RasDss._read_grid_native(f, ALBERS_GRID)
    java = dict(native_grid, crs="JAVA-ONLY-CRS", units="MM  ", metadata=dict(native_grid["metadata"]))
    java["data"] = native_grid["data"].copy()
    monkeypatch.setattr(RasDss, "_read_grid_java", staticmethod(lambda *a: java))
    out = RasDss.read_grid(f, ALBERS_GRID)
    assert out is java
    rec = _records("read_grid")[-1]
    assert rec["outcome"] == "expected" and rec["label"].startswith("G-CRS")
    assert "G2" in rec["label"] and rec["returned"] == "java"

    # Shadow always returns Java's grid, even when opted in or qualified.
    out = RasDss.read_grid(f, ALBERS_GRID, allow_unqualified_native=True)
    assert out is java
    monkeypatch.setattr(_backend, "native_grid_qualified", lambda: True)
    assert RasDss.read_grid(f, ALBERS_GRID) is java
    rec = _records("read_grid")[-1]
    # Once the engine is qualified, a CRS difference is no longer expected.
    assert rec["returned"] == "java" and rec["outcome"] == "unexpected"


def test_shadow_grid_raises_java_error_even_when_native_succeeds(shadow, fixtures, monkeypatch):
    def java_fails(*_a):
        raise RuntimeError("Java not found")

    monkeypatch.setattr(RasDss, "_read_grid_java", staticmethod(java_fails))
    with pytest.raises(RuntimeError, match="Java not found"):
        RasDss.read_grid(fixtures["synthetic_grid7"], MODERN_GRID)
    assert _records("read_grid")[-1]["outcome"] == "skipped"


def test_allow_unqualified_native_is_ignored_with_warning_under_java(fixtures, monkeypatch, caplog):
    sentinel = {"from": "java"}
    monkeypatch.setattr(RasDss, "_read_grid_java", staticmethod(lambda *a: sentinel))
    assert RasDss.read_grid(fixtures["synthetic_grid7"], MODERN_GRID,
                            allow_unqualified_native=True) is sentinel
    assert "allow_unqualified_native=True is ignored" in caplog.text


def test_paired_data_known_labels_require_dss6():
    idx = pd.Index(np.float32([1.0, 2.0]), name="ordinate")

    def frame(version, labels, xp):
        df = pd.DataFrame({"curve_1": np.float32([3.0, 4.0])}, index=idx)
        df.attrs = {"dss_version": version, "labels": labels, "x_precision": xp,
                    "y_precision": xp, "time_zone": None}
        return df

    java6, native6 = frame(6, ["A"], -1), frame(6, [" A"], 0)
    outcome, label, _ = _backend.classify_paired_data(java6, None, native6, None)
    assert outcome == "expected" and "PD1" in label and "PD4" in label
    java7, native7 = frame(7, ["A"], -1), frame(7, [" A"], 0)
    assert _backend.classify_paired_data(java7, None, native7, None)[0] == "unexpected"
    # PD4 requires a decoded native precision >= 0.
    assert _backend.classify_paired_data(frame(6, ["A"], -1), None, frame(6, ["A"], -5),
                                         None)[0] == "unexpected"


def test_shadow_grid_cell_difference_is_unexpected(shadow, fixtures, monkeypatch):
    f = fixtures["synthetic_grid7"]
    native_grid = RasDss._read_grid_native(f, MODERN_GRID)
    java = dict(native_grid)
    java["data"] = native_grid["data"].copy()
    java["data"][0, 0] = 42.0
    monkeypatch.setattr(RasDss, "_read_grid_java", staticmethod(lambda *a: java))
    RasDss.read_grid(f, MODERN_GRID)
    rec = _records("read_grid")[-1]
    assert rec["outcome"] == "unexpected" and "cells:cells_bits" in rec["diffs"]


def test_shadow_file_version(shadow, fixtures, monkeypatch):
    monkeypatch.setattr(RasDss, "_get_file_version_java", staticmethod(lambda f: 7))
    assert RasDss.get_file_version(fixtures["synthetic_pd7"]) == 7
    assert _records("file_version")[-1]["outcome"] == "identical"
    assert RasDss.get_file_version(fixtures["synthetic_pd6"]) == 6
    assert _records("file_version")[-1]["outcome"] == "unexpected"


def test_classify_grid_known_null_mapping():
    java = {"data": np.float32([[1.0, -9999.0]]), "metadata": {}}
    native = {"data": np.float32([[1.0, np.nan]]),
              "metadata": {"native": {"null_value": -9999.0, "record_type": 430}}}
    outcome, label, _ = _backend.classify_grid(java, None, native, None)
    assert outcome == "expected" and label.startswith("G1")
    java_bad = {"data": np.float32([[1.0, 5.0]]), "metadata": {}}
    assert _backend.classify_grid(java_bad, None, native, None)[0] == "unexpected"


# ---------------------------------------------------------------------------
# Java backend (isolated worker process)
# ---------------------------------------------------------------------------


def _run_java(requests, work: Path):
    req = work / "requests.json"
    out = work / "results.pkl"
    req.write_text(json.dumps(requests), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(WORKER), str(req), str(out)],
        capture_output=True, text=True, timeout=1800,
    )
    marker = next((ln for ln in completed.stdout.splitlines()
                   if ln.startswith("PDGRID_BRIDGE_UNAVAILABLE:")), None)
    if completed.returncode == 77 or marker:
        pytest.skip(" ".join((marker or "Java bridge unavailable").split()))
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    with open(out, "rb") as fh:
        return pickle.load(fh)


JAVA_PD_RECORDS = [
    {"pathname": "/TEST/RATING/STAGE-FLOW///JAVA/", "x": [1.0, 2.0, 3.25],
     "y": [[10.0, 20.5, 31.0], [11.0, 21.0, 0.1]], "x_units": "FEET", "y_units": "CFS",
     "x_type": "UNT", "y_type": "UNT", "labels": ["LOW", "HIGH"], "doubles": False},
    {"pathname": "/TEST/ATLAS14/TIME-PRECIP///50%/", "x": [0.0, 0.5, 12.0, 24.0],
     "y": [[0.0, 0.01, 0.6, 1.0]], "x_units": "HOURS", "y_units": "FRACTION",
     "x_type": "TIME", "y_type": "CUMULATIVE", "doubles": True},
]


@pytest.fixture(scope="module")
def java_results(tmp_path_factory):
    work = tmp_path_factory.mktemp("p18_java")
    requests = []
    for version in (6, 7):
        f = work / f"java_pd{version}.dss"
        requests.append({"op": "write_pd", "dss_file": str(f), "version": version,
                         "records": JAVA_PD_RECORDS})
        for rec in JAVA_PD_RECORDS:
            requests.append({"op": "pd", "dss_file": str(f), "pathname": rec["pathname"]})
        requests.append({"op": "version", "dss_file": str(f)})
        requests.append({"op": "pd", "dss_file": str(f), "pathname": "/TEST/NONE/STAGE-FLOW///X/"})
    grid7 = work / "synthetic_grid7.dss"
    shutil.copyfile(FIXTURES / "synthetic_grid7.dss", grid7)
    pd7 = work / "synthetic_pd7.dss"
    shutil.copyfile(FIXTURES / "synthetic_pd7.dss", pd7)
    for p in (MODERN_GRID, ALBERS_GRID, UNTIMED_GRID):
        requests.append({"op": "grid", "dss_file": str(grid7), "pathname": p})
    requests.append({"op": "pd", "dss_file": str(pd7), "pathname": PD7_PATH})
    pd6 = work / "synthetic_pd6.dss"
    shutil.copyfile(FIXTURES / "synthetic_pd6.dss", pd6)
    requests.append({"op": "pd", "dss_file": str(pd6), "pathname": PD6_PATH})
    requests.append({"op": "pd", "dss_file": str(pd6), "pathname": "/A/B/STAGE-FLOW///NONE/"})
    requests.append({"op": "pd", "dss_file": str(pd7), "pathname": TS7_PATH})
    requests.append({"op": "grid", "dss_file": str(pd7), "pathname": PDD7_PATH})
    requests.append({"op": "shadow_pd", "dss_file": str(work / "java_pd7.dss"),
                     "pathname": JAVA_PD_RECORDS[0]["pathname"]})
    requests.append({"op": "shadow_grid", "dss_file": str(grid7), "pathname": ALBERS_GRID})
    requests.append({"op": "shadow_version", "dss_file": str(grid7)})
    results = _run_java(requests, work)
    return {"work": work, "results": results, "requests": requests}


def _result(java_results, op, dss_name, pathname=None):
    for req, res in zip(java_results["requests"], java_results["results"]):
        if req["op"] == op and Path(req["dss_file"]).name == dss_name and req.get("pathname") == pathname:
            return res
    raise KeyError((op, dss_name, pathname))


@pytest.mark.parametrize("version", [6, 7])
def test_java_and_native_paired_data_agree(java_results, version, monkeypatch, no_jvm):
    pytest.importorskip("dss_commander")
    monkeypatch.setattr(RasDss, "backend", "native")
    name = f"java_pd{version}.dss"
    f = java_results["work"] / name
    for rec in JAVA_PD_RECORDS:
        java = _result(java_results, "pd", name, rec["pathname"])
        assert isinstance(java, pd.DataFrame), java
        assert list(java.attrs) == PD_ATTR_KEYS
        nat = RasDss.read_paired_data(f, rec["pathname"])
        outcome, label, diffs = _backend.classify_paired_data(java, None, nat, None)
        assert outcome in ("identical", "expected"), (label, diffs)
        if version == 7:
            assert outcome == "identical", diffs
        np.testing.assert_array_equal(nat.index.to_numpy(np.float64), rec["x"])
        assert nat.shape[1] == len(rec["y"])
        expected_type = 205 if rec["doubles"] else 200
        assert java.attrs["record_type"] == nat.attrs["record_type"] == expected_type
    assert _result(java_results, "version", name) == version == RasDss.get_file_version(f)


def test_java_errors_match_native_classes(java_results):
    nf = _result(java_results, "pd", "java_pd7.dss", "/TEST/NONE/STAGE-FLOW///X/")
    assert nf["error"] == "DssPathnameNotFoundError" and nf["is_value_error"]
    wrong = _result(java_results, "pd", "synthetic_pd7.dss", TS7_PATH)
    assert wrong["error"] == "DssRecordTypeError" and wrong["is_type_error"]
    grid_wrong = _result(java_results, "grid", "synthetic_pd7.dss", PDD7_PATH)
    assert grid_wrong["error"] == "DssRecordTypeError" and grid_wrong["is_type_error"]


def test_java_read_failure_on_existing_record_is_not_not_found(java_results):
    """Monolith cannot read this synthetic DSS6 record; that is a read error."""
    failed = _result(java_results, "pd", "synthetic_pd6.dss", PD6_PATH)
    if isinstance(failed, pd.DataFrame):
        pytest.skip("this Monolith build reads the synthetic DSS6 paired data")
    assert failed["error"] == "DssReadError", failed
    assert "DssFormatError" in failed["mro"] and not failed["is_value_error"]
    absent = _result(java_results, "pd", "synthetic_pd6.dss", "/A/B/STAGE-FLOW///NONE/")
    assert absent["error"] == "DssPathnameNotFoundError"


def test_java_reads_synthetic_dss7_paired_data_like_native(java_results, monkeypatch, no_jvm):
    pytest.importorskip("dss_commander")
    java = _result(java_results, "pd", "synthetic_pd7.dss", PD7_PATH)
    nat = RasDss._read_paired_data_native(FIXTURES / "synthetic_pd7.dss", PD7_PATH)
    java.attrs["dss_file"] = nat.attrs["dss_file"]
    outcome, label, diffs = _backend.classify_paired_data(java, None, nat, None)
    assert outcome == "expected" and label.startswith("PD2"), diffs


@pytest.mark.parametrize("pathname", [MODERN_GRID, ALBERS_GRID, UNTIMED_GRID])
def test_java_and_native_grids_agree_on_cells(java_results, pathname):
    pytest.importorskip("dss_commander")
    java = _result(java_results, "grid", "synthetic_grid7.dss", pathname)
    assert isinstance(java, dict) and java["row_order"] == "south_up"
    nat = RasDss._read_grid_native(java["dss_file"], pathname)
    outcome, label, diffs = _backend.classify_grid(java, None, nat, None)
    assert not any(d.startswith("cells:") and d != "cells:cells_missing_native_only" for d in diffs)
    assert outcome in ("identical", "expected"), (label, diffs)


def test_worker_shadow_runs(java_results):
    pytest.importorskip("dss_commander")
    shadow_pd = _result(java_results, "shadow_pd", "java_pd7.dss", JAVA_PD_RECORDS[0]["pathname"])
    assert isinstance(shadow_pd["value"], pd.DataFrame)
    assert [r["outcome"] for r in shadow_pd["records"]] == ["identical"]
    shadow_grid = _result(java_results, "shadow_grid", "synthetic_grid7.dss", ALBERS_GRID)
    assert isinstance(shadow_grid["value"], dict)
    assert all(r["outcome"] != "unexpected" for r in shadow_grid["records"])
    shadow_version = _result(java_results, "shadow_version", "synthetic_grid7.dss")
    assert shadow_version["value"] == 7
    assert shadow_version["records"][0]["outcome"] == "identical"


def test_shadow_sweep_rasexamples_paired_data(tmp_path):
    """Shadow every 20th paired-data record of a public RasExamples DSS file."""
    dc = pytest.importorskip("dss_commander")
    from ras_commander import RasExamples

    try:
        project = Path(RasExamples.extract_project("Muncie", output_path=tmp_path))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RasExamples Muncie unavailable: {type(exc).__name__}: {exc}")
    dss_files = sorted(p for p in project.rglob("*") if p.suffix.lower() == ".dss")
    requests = []
    for f in dss_files:
        with dc.open(f) as handle:
            cat = handle.catalog()
        paths = [p for p, t in zip(cat.pathname, cat.record_type) if int(t) in (200, 205)]
        requests += [{"op": "shadow_pd", "dss_file": str(f), "pathname": p} for p in paths[::20]]
    if not requests:
        pytest.skip("no paired-data records in the Muncie DSS files")
    results = _run_java(requests, tmp_path)
    outcomes = [rec["outcome"] for res in results for rec in res["records"]]
    assert len(outcomes) == len(requests)
    assert "unexpected" not in outcomes
