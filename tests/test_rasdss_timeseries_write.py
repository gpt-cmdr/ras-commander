"""Focused coverage for HEC-DSS time-series writer bridge behavior."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import types

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss


def test_datetimes_to_hec_times_returns_int32_minutes() -> None:
    times = pd.DatetimeIndex(
        ["1899-12-31 00:00", "1900-01-01 00:00", "2019-09-18 13:00"]
    )

    result = RasDss._datetimes_to_hec_times(times)

    assert result.dtype == np.int32
    assert result.tolist() == [0, 1440, 62964780]


def test_datetimes_to_hec_times_supports_pre_epoch_values() -> None:
    result = RasDss._datetimes_to_hec_times(
        np.array([np.datetime64("1899-12-30T00:00", "m")])
    )

    assert result.tolist() == [-1440]


@pytest.mark.parametrize(
    ("times", "message"),
    [
        ([pd.NaT], "NaT"),
        ([pd.Timestamp("2020-01-01 00:00:01")], "whole minutes"),
        ([pd.Timestamp("2020-01-01 00:00:00.000001")], "whole minutes"),
        (
            np.array([np.datetime64("7000-01-01T00:00", "m")]),
            "int32 minute range",
        ),
    ],
)
def test_datetimes_to_hec_times_rejects_unrepresentable_values(
    times,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RasDss._datetimes_to_hec_times(times)


def test_setter_failure_occurs_before_dss_file_is_opened(
    monkeypatch,
    tmp_path,
) -> None:
    opened = []

    class FakeHecTimeArray:
        def __init__(self, values):
            self.values = values

    class FakeTimeSeriesContainer:
        def setStoreAsDoubles(self, _enabled):
            pass

        def setTimes(self, _times):
            return 1

        def setValues(self, _values):
            return 0

    class FakeHecDss:
        @staticmethod
        def open(_path):
            opened.append(True)
            raise AssertionError("DSS file must not be opened after setter failure")

    def autoclass(name):
        classes = {
            "hec.heclib.dss.HecDss": FakeHecDss,
            "hec.io.TimeSeriesContainer": FakeTimeSeriesContainer,
            "hec.heclib.util.HecTimeArray": FakeHecTimeArray,
        }
        return classes[name]

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: None))
    monkeypatch.setitem(
        sys.modules,
        "jnius",
        types.SimpleNamespace(autoclass=autoclass, cast=lambda _name, value: value),
    )

    output = tmp_path / "must-not-open.dss"
    with pytest.raises(RuntimeError, match="times=1, values=0"):
        RasDss.write_timeseries(
            output,
            "/BASIN/UPSTREAM/FLOW//5MIN/C03/",
            pd.date_range("2020-01-01", periods=2, freq="5min"),
            [1.0, 2.0],
        )

    assert opened == []
    assert not output.exists()


def test_write_timeseries_round_trips_through_real_java_bridge(tmp_path) -> None:
    output = tmp_path / "modern-timeseries.dss"
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C03_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        output = Path(sys.argv[1])
        pathname = "/BASIN/UPSTREAM/FLOW//5MIN/C03/"
        times = pd.date_range("2019-09-18 13:00", periods=4, freq="5min")
        values = np.array([1.25, 2.5, 3.75, 4.125], dtype=np.float64)
        RasDss.write_timeseries(output, pathname, times, values)
        reread = RasDss.read_timeseries(output, pathname)
        np.testing.assert_array_equal(
            reread.index.to_numpy(dtype="datetime64[m]"),
            times.to_numpy(dtype="datetime64[m]"),
        )
        np.testing.assert_array_equal(reread["value"].to_numpy(), values)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 77 and "C03_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip())

    assert completed.returncode == 0, completed.stdout + completed.stderr
