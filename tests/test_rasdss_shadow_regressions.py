"""Negative shadow controls run without Java or the optional native wheel."""

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss
from ras_commander.dss import _backend


def frame(freq="h", interval=60, periods=3):
    result = pd.DataFrame({"value": np.arange(periods, dtype=float)},
                          index=pd.date_range("2020-01-01", periods=periods,
                                              freq=freq, name="datetime"))
    result.attrs["interval"] = interval
    return result


@pytest.mark.parametrize("days", [-40178, -1, 1, 40178])
def test_day_shift_is_unexpected_after_java_timestamp_fix(days):
    java = frame()
    native = java.copy()
    native.index += pd.Timedelta(days=days)
    assert _backend.classify_timeseries("/A/B/FLOW//1HOUR/F/", java, None,
                                       native, None)[0] == "unexpected"


@pytest.mark.parametrize("seconds", [-60, -2, 2, 60])
def test_subminute_shift_is_unexpected_after_java_timestamp_fix(seconds):
    java = frame("3s", .05)
    native = java.copy()
    native.index += pd.Timedelta(seconds=seconds)
    assert _backend.classify_timeseries("/A/B/FLOW//3SECOND/F/", java, None,
                                       native, None)[0] == "unexpected"


@pytest.mark.parametrize("error", [TypeError("wrapper regression"),
                                  ValueError("No data found for pathname: /A/B/FLOW//1HOUR/F/")])
def test_java_error_with_native_data_is_not_assumed_first_block_missing(error):
    assert _backend.classify_timeseries("/A/B/FLOW//1HOUR/F/", None, error,
                                       frame(), None)[0] == "unexpected"


def test_interval_disagreement_is_unexpected():
    java = frame("3s", .05)
    native = java.copy()
    native.attrs["interval"] = .25
    assert _backend.classify_timeseries("/A/B/FLOW//3SECOND/F/", java, None,
                                       native, None)[0] == "unexpected"


def test_known_whole_minute_tail_requires_matching_timestamped_prefix():
    native = frame("3s", .05, 22)
    java = native.iloc[:21].copy()  # last Java stamp is 00:01:00
    assert _backend.classify_timeseries("/A/B/FLOW//3SECOND/F/", java, None,
                                       native, None)[0] == "expected"
    shifted = native.copy()
    shifted.index += pd.Timedelta(days=1)
    assert _backend.classify_timeseries("/A/B/FLOW//3SECOND/F/", java, None,
                                       shifted, None)[0] == "unexpected"


def test_get_backend_follows_public_logging_contract():
    assert hasattr(RasDss.get_backend, "__wrapped__")


@pytest.mark.parametrize("pathname,year", [
    ("/A/B/FLOW/TS-PATTERN/1HOUR/F/", 3000),
    ("/A/Caf\u00e9/FLOW//1HOUR/F/", 2020),
])
def test_unrelated_java_errors_are_not_hidden_for_special_pathnames(pathname, year):
    native = frame()
    if year == 3000:
        native.index = pd.date_range("3000-01-01", periods=3, freq="h", unit="s")
    assert _backend.classify_timeseries(pathname, None, TypeError("wrapper regression"),
                                       native, None)[0] == "unexpected"
