"""RasDss backend selection, native error behaviour and shadow mode (P09b).

Selection, ImportError and fallback tests need neither Java nor ras_commander_fast_dss.
Native and shadow tests read a real RasExamples project (Muncie) and skip when
ras_commander_fast_dss (a private wheel) is not installed. No test here starts a JVM: the Java
read paths are replaced where shadow mode needs a Java result.
"""

from __future__ import annotations

import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss, RasExamples
from ras_commander.dss import _backend

LOGGER = "ras_commander.dss.RasDss"


class _JavaCalled(Exception):
    """Raised by the patched JVM entry point."""


@pytest.fixture(autouse=True)
def clean_backend(monkeypatch):
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    monkeypatch.setattr(RasDss, "backend", _backend.DEFAULT_BACKEND)
    _backend.reset_fallback_warning()
    _backend.reset_shadow_stats()
    yield
    _backend.reset_fallback_warning()
    _backend.reset_shadow_stats()


@pytest.fixture
def no_jvm(monkeypatch):
    """Make any attempt to configure the JVM fail loudly."""

    def _raise():
        raise _JavaCalled("JVM configuration was attempted")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(_raise))


@pytest.fixture
def without_ras_commander_fast_dss(monkeypatch):
    """Simulate an environment where ras_commander_fast_dss is not installed."""
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss", None)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_default_backend_is_java():
    assert RasDss.backend == "java"
    assert RasDss.get_backend() == "java"


@pytest.mark.parametrize("value", ["native", "NATIVE", " shadow ", "java"])
def test_attribute_selects_backend(monkeypatch, value):
    pytest.importorskip("ras_commander_fast_dss")
    monkeypatch.setattr(RasDss, "backend", value)
    assert RasDss.get_backend() == value.strip().lower()


def test_environment_overrides_attribute(monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "shadow")
    monkeypatch.setenv(_backend.ENV_VAR, "java")
    assert RasDss.get_backend() == "java"


def test_blank_environment_value_is_ignored(monkeypatch):
    monkeypatch.setenv(_backend.ENV_VAR, "  ")
    assert RasDss.get_backend() == "java"


def test_invalid_environment_value_raises(monkeypatch):
    monkeypatch.setenv(_backend.ENV_VAR, "jython")
    with pytest.raises(ValueError, match=_backend.ENV_VAR):
        RasDss.get_backend()


def test_invalid_attribute_value_raises(monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "rust")
    with pytest.raises(ValueError, match="java, native, shadow"):
        RasDss.get_backend()


def test_java_backend_still_uses_the_jvm(no_jvm, tmp_path):
    with pytest.raises(_JavaCalled):
        RasDss.get_catalog(tmp_path / "any.dss")
    with pytest.raises(_JavaCalled):
        RasDss.read_timeseries(tmp_path / "any.dss", "/A/B/FLOW//1HOUR/F/")


# ---------------------------------------------------------------------------
# ras_commander_fast_dss missing
# ---------------------------------------------------------------------------


def test_native_without_ras_commander_fast_dss_raises_import_error(
    monkeypatch, without_ras_commander_fast_dss, no_jvm, tmp_path
):
    monkeypatch.setattr(RasDss, "backend", "native")
    for call in (
        lambda: RasDss.get_backend(),
        lambda: RasDss.get_catalog(tmp_path / "x.dss"),
        lambda: RasDss.read_timeseries(tmp_path / "x.dss", "/A/B/C//1HOUR/F/"),
        lambda: RasDss.read_multiple_timeseries(tmp_path / "x.dss", ["/A/B/C//1HOUR/F/"]),
    ):
        with pytest.raises(ImportError, match=r"ras-commander-fast-dss wheel you were given"):
            call()


def test_install_hint_names_the_unpublished_fast_dss_wheel():
    hint = _backend._NATIVE_INSTALL_HINT
    assert "ras-commander-fast-dss" in hint
    assert "ras_commander_fast_dss-<version>-<tag>.whl" in hint
    # No extra installs the unpublished wheel, and the old name is gone (no alias).
    assert "[dss-native]" not in hint
    assert "dss_commander" not in hint.replace("ras_commander_fast_dss", "")
    assert "dss-commander" not in hint.replace("ras-commander-fast-dss", "")


def test_old_engine_name_is_not_imported(monkeypatch):
    """The pre-rename ``dss_commander`` module is never used, even if importable."""
    import types

    monkeypatch.setitem(sys.modules, "dss_commander", types.ModuleType("dss_commander"))
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss", None)
    assert _backend._maybe_native() is None
    assert not _backend.native_available()


def test_native_env_without_ras_commander_fast_dss_raises_import_error(
    monkeypatch, without_ras_commander_fast_dss
):
    monkeypatch.setenv(_backend.ENV_VAR, "native")
    with pytest.raises(ImportError, match="ras-commander-fast-dss"):
        RasDss.get_backend()


def test_shadow_without_ras_commander_fast_dss_falls_back_to_java_with_one_warning(
    monkeypatch, without_ras_commander_fast_dss, no_jvm, caplog, tmp_path
):
    monkeypatch.setattr(RasDss, "backend", "shadow")
    caplog.set_level(logging.WARNING, logger=LOGGER)
    for _ in range(3):
        with pytest.raises(_JavaCalled):
            RasDss.get_catalog(tmp_path / "x.dss")
    assert RasDss.get_backend() == "java"
    warnings_logged = [r for r in caplog.records if "shadow" in r.getMessage()]
    assert len(warnings_logged) == 1
    assert "ras-commander-fast-dss is not installed" in warnings_logged[0].getMessage()


# ---------------------------------------------------------------------------
# Native backend on a real project
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def muncie_dss(tmp_path_factory):
    pytest.importorskip("ras_commander_fast_dss")
    root = tmp_path_factory.mktemp("p09b_backend")
    try:
        project = Path(RasExamples.extract_project("Muncie", output_path=root))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RasExamples project 'Muncie' unavailable: {type(exc).__name__}: {exc}")
    dss_file = next(project.rglob("Muncie.dss"))
    import ras_commander_fast_dss as dc

    with dc.open(dss_file) as handle:
        catalog = handle.catalog()
    ts = catalog[catalog.record_type.between(100, 119)].pathname.tolist()
    other = catalog[~catalog.record_type.between(100, 119)].pathname.tolist()
    return {"file": dss_file, "ts": ts, "other": other}


@pytest.fixture
def native(monkeypatch, no_jvm):
    pytest.importorskip("ras_commander_fast_dss")
    monkeypatch.setattr(RasDss, "backend", "native")


def test_native_catalog_and_read_never_touch_java(native, muncie_dss):
    catalog = RasDss.get_catalog(muncie_dss["file"])
    assert list(catalog.columns) == ["pathname"]
    assert catalog.attrs == {}
    assert len(catalog) == 1164
    df = RasDss.read_timeseries(muncie_dss["file"], muncie_dss["ts"][0])
    assert df.index.name == "datetime"
    assert list(df.columns) == ["value"]
    assert df["value"].dtype == np.float64
    assert list(df.attrs) == ["pathname", "units", "type", "interval", "dss_file"]
    assert df.attrs["dss_file"] == str(muncie_dss["file"].resolve())
    assert "jnius" not in sys.modules or not getattr(
        sys.modules.get("jnius_config"), "vm_running", False
    )


def test_native_honors_start_and_end(native, muncie_dss):
    full = RasDss.read_timeseries(muncie_dss["file"], muncie_dss["ts"][0])
    start, end = full.index[10], full.index[20]
    window = RasDss.read_timeseries(
        muncie_dss["file"], muncie_dss["ts"][0],
        start.strftime("%d%b%Y %H%M"), end.strftime("%d%b%Y %H%M"),
    )
    assert window.index[0] == start and window.index[-1] == end
    assert len(window) == 11
    np.testing.assert_array_equal(window["value"].to_numpy(), full["value"].to_numpy()[10:21])


def test_native_errors_are_typed_and_compatible(native, muncie_dss, tmp_path):
    import ras_commander_fast_dss as dc

    with pytest.raises(dc.DssPathnameNotFoundError) as info:
        RasDss.read_timeseries(muncie_dss["file"], "/NOT/IN/THIS/FILE//1HOUR/P09B/")
    assert isinstance(info.value, ValueError) and isinstance(info.value, RuntimeError)

    with pytest.raises(dc.DssUnsupportedRecordError) as info:
        RasDss.read_timeseries(muncie_dss["file"], muncie_dss["other"][0])
    assert isinstance(info.value, RuntimeError)

    missing = tmp_path / "missing.dss"
    with pytest.raises(FileNotFoundError):
        RasDss.get_catalog(missing)
    assert not missing.exists()

    junk = tmp_path / "junk.dss"
    junk.write_bytes(b"not a dss file" * 100)
    before = junk.read_bytes()
    with pytest.raises(dc.DssFormatError) as info:
        RasDss.get_catalog(junk)
    assert isinstance(info.value, RuntimeError)
    assert junk.read_bytes() == before


def test_native_read_multiple_keeps_none_contract(native, muncie_dss, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    paths = muncie_dss["ts"][:3] + ["/NOT/IN/THIS/FILE//1HOUR/P09B/", muncie_dss["other"][0]]
    result = RasDss.read_multiple_timeseries(muncie_dss["file"], paths)
    assert list(result) == paths
    assert all(isinstance(result[p], pd.DataFrame) for p in paths[:3])
    assert result[paths[3]] is None and result[paths[4]] is None
    assert sum("Could not read DSS pathname" in r.getMessage() for r in caplog.records) == 2

    missing = RasDss.read_multiple_timeseries(tmp_path / "missing.dss", paths[:2])
    assert missing == {paths[0]: None, paths[1]: None}
    assert not (tmp_path / "missing.dss").exists()


def test_native_validators_and_info(native, muncie_dss):
    info = RasDss.get_info(muncie_dss["file"])
    assert info["total_paths"] == 1164 and len(info["first_5_paths"]) == 5
    pathname = muncie_dss["ts"][0]
    assert RasDss.is_pathname_available(muncie_dss["file"], pathname) is True
    assert RasDss.check_data_availability(muncie_dss["file"], pathname).passed is True
    missing = RasDss.check_pathname_exists(muncie_dss["file"], "/NOT/IN/THIS/FILE//1HOUR/P09B/")
    assert missing.passed is False


def test_shutdown_jvm_is_deprecated_noop_under_native(native):
    with pytest.warns(DeprecationWarning, match="no-op under the native"):
        RasDss.shutdown_jvm()


def test_shutdown_jvm_is_silent_under_java():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        RasDss.shutdown_jvm()


# ---------------------------------------------------------------------------
# Shadow mode (Java results substituted; no JVM)
# ---------------------------------------------------------------------------


@pytest.fixture
def shadow(monkeypatch, no_jvm):
    pytest.importorskip("ras_commander_fast_dss")
    monkeypatch.setattr(RasDss, "backend", "shadow")


def _native_frame(dss_file, pathname):
    return RasDss._read_timeseries_native(dss_file, pathname)


def test_shadow_identical_and_d1_markers(shadow, monkeypatch, muncie_dss, caplog):
    pathname = muncie_dss["ts"][0]
    reference = _native_frame(muncie_dss["file"], pathname)


    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(lambda f, p: reference.copy()))
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    result = RasDss.read_timeseries(muncie_dss["file"], pathname)
    pd.testing.assert_frame_equal(result, reference)
    assert _backend.summary() == {"read_timeseries|identical|identical": 1}

    # A Java frame with -FLT_MAX where native has NaN is the expected D1 mapping.
    marker_frame = reference.copy()
    marker_frame.attrs = dict(reference.attrs)
    native_nan = reference.copy()
    native_nan.attrs = dict(reference.attrs)
    native_nan.iloc[0, 0] = np.nan
    marker_frame.iloc[0, 0] = float(-np.finfo(np.float32).max)
    outcome, label, _ = _backend.classify_timeseries(pathname, marker_frame, None, native_nan, None)
    assert (outcome, label) == ("expected", "D1 missing markers mapped to NaN")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_shadow_logs_unexpected_difference_and_returns_native(
    shadow, monkeypatch, muncie_dss, caplog
):
    pathname = muncie_dss["ts"][0]
    reference = _native_frame(muncie_dss["file"], pathname)

    def java_changed(dss_file, path):
        df = reference.copy()
        df.attrs = dict(reference.attrs)
        df["value"] = df["value"] + 1.0
        return df

    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(java_changed))
    caplog.set_level(logging.WARNING, logger=LOGGER)
    result = RasDss.read_timeseries(muncie_dss["file"], pathname)
    pd.testing.assert_frame_equal(result, reference)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("UNEXPECTED" in m and "values_bits" in m for m in messages)


def test_shadow_comparison_never_raises(shadow, monkeypatch, muncie_dss, caplog):
    pathname = muncie_dss["ts"][0]
    reference = _native_frame(muncie_dss["file"], pathname)
    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(lambda f, p: reference.copy()))

    def broken(*_args, **_kwargs):
        raise RuntimeError("comparison bug")

    monkeypatch.setattr(_backend, "classify_timeseries", broken)
    monkeypatch.setattr(_backend, "classify_catalog", broken)
    caplog.set_level(logging.WARNING, logger=LOGGER)
    pd.testing.assert_frame_equal(RasDss.read_timeseries(muncie_dss["file"], pathname), reference)
    monkeypatch.setattr(RasDss, "_get_catalog_java", staticmethod(lambda f: pd.DataFrame()))
    assert len(RasDss.get_catalog(muncie_dss["file"])) == 1164
    assert sum("comparison failed" in r.getMessage() for r in caplog.records) == 2


def test_shadow_java_failure_is_recorded_not_raised(shadow, monkeypatch, muncie_dss):
    pathname = muncie_dss["ts"][0]

    def java_fails(dss_file, path):
        raise RuntimeError("Java exploded")

    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(java_fails))
    df = RasDss.read_timeseries(muncie_dss["file"], pathname)
    assert len(df) > 0
    assert _backend.summary() == {"read_timeseries|unexpected|native data, Java error": 1}


def test_shadow_skips_java_where_java_is_unsafe(shadow, monkeypatch, muncie_dss, tmp_path):
    import ras_commander_fast_dss as dc

    def java_must_not_run(*_args):
        raise AssertionError("Java must not run for this request")

    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(java_must_not_run))
    monkeypatch.setattr(RasDss, "_get_catalog_java", staticmethod(java_must_not_run))
    # Paired data: the Java path crashes the JVM.
    with pytest.raises(dc.DssUnsupportedRecordError):
        RasDss.read_timeseries(muncie_dss["file"], muncie_dss["other"][0])
    # Missing file: the Java path would create it.
    missing = tmp_path / "missing.dss"
    with pytest.raises(FileNotFoundError):
        RasDss.get_catalog(missing)
    with pytest.raises(FileNotFoundError):
        RasDss.read_timeseries(missing, muncie_dss["ts"][0])
    assert not missing.exists()
    assert all(k.split("|")[1] == "skipped" for k in _backend.summary())


def test_shadow_window_compares_against_cut_java_frame(shadow, monkeypatch, muncie_dss):
    pathname = muncie_dss["ts"][0]
    full = _native_frame(muncie_dss["file"], pathname)
    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(lambda f, p: full.copy()))
    start = full.index[10] + pd.Timedelta(minutes=1)
    end = full.index[20] + pd.Timedelta(minutes=1)
    window = RasDss.read_timeseries(muncie_dss["file"], pathname, start, end)
    assert window.index[0] == full.index[11] and window.index[-1] == full.index[21]
    assert _backend.summary() == {"read_timeseries|identical|identical": 1}


def test_historical_java_errors_stay_visible_but_whitespace_is_expected(muncie_dss):
    pytest.importorskip("ras_commander_fast_dss")
    pathname = muncie_dss["ts"][0]
    native_df = _native_frame(muncie_dss["file"], pathname)

    j1 = native_df.copy()
    j1.attrs = dict(native_df.attrs)
    j1.index = pd.DatetimeIndex(
        (native_df.index - pd.Timedelta(days=40178)).as_unit("s"), name="datetime"
    )
    assert _backend.classify_timeseries(pathname, j1, None, native_df, None)[1] == (
        "frame difference"
    )

    d9_java = native_df.copy()
    d9_java.attrs = dict(native_df.attrs, type=native_df.attrs["type"] + "   ")
    assert _backend.classify_timeseries(pathname, d9_java, None, native_df, None)[1] == (
        "D9 blank units/type whitespace"
    )

    outcome, label, _ = _backend.classify_timeseries(
        pathname, None, TypeError("NaT"), native_df, None
    )
    assert (outcome, label) == ("unexpected", "native data, Java error")


@pytest.mark.parametrize("window_result", ["match", "changed", "error"])
def test_shadow_verifies_java_window_after_whole_read_failure(
    shadow, monkeypatch, muncie_dss, window_result
):
    pathname = muncie_dss["ts"][0]
    reference = _native_frame(muncie_dss["file"], pathname)
    calls = []

    def java_whole_or_window(dss_file, path, **kwargs):
        calls.append(kwargs)
        if not kwargs:
            raise ValueError(f"No data found for pathname: {path}")
        if window_result == "error":
            raise RuntimeError("window read failed")
        result = reference.copy()
        result.attrs = dict(reference.attrs)
        if window_result == "changed":
            result.iloc[0, 0] += 1
        return result

    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(java_whole_or_window))
    actual = RasDss.read_timeseries(muncie_dss["file"], pathname)
    pd.testing.assert_frame_equal(actual, reference)
    assert len(calls) == 2 and set(calls[1]) == {"start_date", "end_date"}
    record = list(_backend.SHADOW_RECORDS)[-1]
    assert record["java_window_verified"] == (window_result == "match")
    assert record["outcome"] == ("expected" if window_result == "match" else "unexpected")


# ---------------------------------------------------------------------------
# HEC DSS6 "no data" rule (ras-commander-fast-dss no_data="refuse", parity labelling only)
# ---------------------------------------------------------------------------


def _java_no_data(dss_file, path, **_kwargs):
    raise ValueError(f"No data found for pathname: {path}")


@pytest.mark.parametrize("route", ["single", "multiple"])
def test_shadow_labels_hec_no_data_rule_without_changing_result(
    shadow, monkeypatch, muncie_dss, route
):
    import ras_commander_fast_dss as dc

    if not hasattr(dc, "DssNoDataError"):
        pytest.skip("installed ras-commander-fast-dss has no DssNoDataError")
    pathname = "/NO/SUCH/FLOW//1HOUR/RECORD/"
    calls = []
    original = dc.DssFile.read_timeseries

    def read_timeseries(self, path, start=None, end=None, **kwargs):
        calls.append(kwargs)
        if kwargs.get("no_data") == "refuse":
            raise dc.DssNoDataError("no data", pathname=path)
        return original(self, path, start, end, **kwargs)

    monkeypatch.setattr(dc.DssFile, "read_timeseries", read_timeseries)
    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(_java_no_data))
    if route == "single":
        with pytest.raises(dc.DssPathnameNotFoundError) as info:
            RasDss.read_timeseries(muncie_dss["file"], pathname)
        # The returned error is the default native one, never the refusal.
        assert not isinstance(info.value, dc.DssNoDataError)
    else:
        assert RasDss.read_multiple_timeseries(muncie_dss["file"], [pathname]) == {pathname: None}
    assert calls == [{}, {"no_data": "refuse"}]
    assert _backend.summary() == {f"read_timeseries|expected|{_backend.HEC_NO_DATA_LABEL}": 1}
    assert list(_backend.SHADOW_RECORDS)[-1]["native_hec_no_data"] is True


def test_shadow_absent_pathname_keeps_d4_label(shadow, monkeypatch, muncie_dss):
    import ras_commander_fast_dss as dc

    monkeypatch.setattr(RasDss, "_read_timeseries_java", staticmethod(_java_no_data))
    with pytest.raises(dc.DssPathnameNotFoundError):
        RasDss.read_timeseries(muncie_dss["file"], "/NO/SUCH/FLOW//1HOUR/RECORD/")
    assert _backend.summary() == {"read_timeseries|expected|D4/D6 no data: typed native error": 1}
    assert list(_backend.SHADOW_RECORDS)[-1]["native_hec_no_data"] is False


def test_native_refuses_no_data_rules(monkeypatch):
    class NotFound(ValueError):
        pass

    class NoData(NotFound):
        pass

    engine = type("Engine", (), {"DssPathnameNotFoundError": NotFound, "DssNoDataError": NoData})
    monkeypatch.setattr(_backend, "_maybe_native", lambda: engine)
    calls = []

    def refusing(**kwargs):
        calls.append(kwargs)
        raise NoData("no data")

    def absent(**kwargs):
        calls.append(kwargs)
        raise NotFound("absent")

    def returns(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame()

    assert _backend.native_refuses_no_data(refusing, NotFound("x")) is True
    assert _backend.native_refuses_no_data(absent, NotFound("x")) is False
    assert _backend.native_refuses_no_data(returns, NotFound("x")) is False
    assert calls == [{"no_data": "refuse"}] * 3
    calls.clear()
    # Not a not-found error: no re-read.
    assert _backend.native_refuses_no_data(refusing, RuntimeError("x")) is False
    assert calls == []
    # Older wheels without DssNoDataError: no re-read, broader labels stay.
    old = type("Old", (), {"DssPathnameNotFoundError": NotFound})
    monkeypatch.setattr(_backend, "_maybe_native", lambda: old)
    assert _backend.native_refuses_no_data(refusing, NotFound("x")) is False
    assert calls == []


def test_classify_hec_no_data_label(muncie_dss):
    import ras_commander_fast_dss as dc

    pathname = muncie_dss["ts"][0]
    err = dc.DssPathnameNotFoundError("no values")
    java_error = ValueError(f"No data found for pathname: {pathname}")
    assert _backend.classify_timeseries(pathname, None, java_error, None, err)[1] == (
        "D4/D6 no data: typed native error"
    )
    assert _backend.classify_timeseries(
        pathname, None, java_error, None, err, native_hec_no_data=True
    ) == ("expected", _backend.HEC_NO_DATA_LABEL, [])
    markers = pd.DataFrame(
        {"value": [-901.0, float(-np.finfo(np.float32).max)]},
        index=pd.DatetimeIndex(["2000-01-01", "2000-01-02"], name="datetime"),
    )
    assert _backend.classify_timeseries(pathname, markers, None, None, err)[1] == (
        "D4 all-missing dataset (error type)"
    )
    assert _backend.classify_timeseries(
        pathname, markers, None, None, err, native_hec_no_data=True
    )[1] == _backend.HEC_NO_DATA_LABEL


def test_cut_window_keeps_stored_nan_like_ztstrim():
    pytest.importorskip("ras_commander_fast_dss")
    import ras_commander_fast_dss as dc

    flt_max = float(-np.finfo(np.float32).max)
    index = pd.date_range("2000-01-01", periods=6, freq="D", name="datetime")
    java_df = pd.DataFrame({"value": [-901.0, np.nan, 1.0, np.nan, flt_max, -902.0]}, index=index)
    cut = _backend.cut_window(java_df, index[0], index[-1], 1440, dc)
    assert len(cut) == 3
    assert np.isnan(cut["value"].iloc[0]) and np.isnan(cut["value"].iloc[-1])
