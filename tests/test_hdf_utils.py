from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf.HdfUtils import HdfUtils


LOGGER_NAME = "ras_commander.hdf.HdfUtils"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def test_convert_ras_string_duration_uses_public_duration_parser(caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        value = HdfUtils.convert_ras_string("01:02:03")

    assert value == timedelta(hours=1, minutes=2, seconds=3)
    assert _records(caplog) == []


def test_convert_ras_string_datetime_range():
    value = HdfUtils.convert_ras_string(
        "01JAN2024 00:00:00 to 02JAN2024 12:30:45"
    )

    assert value == [
        datetime(2024, 1, 1, 0, 0, 0),
        datetime(2024, 1, 2, 12, 30, 45),
    ]


def test_parse_run_time_window_returns_start_and_end_without_logs(caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        begin, end = HdfUtils.parse_run_time_window(
            "01JAN2024 00:00:00 to 02JAN2024 12:30:45"
        )

    assert begin == datetime(2024, 1, 1, 0, 0, 0)
    assert end == datetime(2024, 1, 2, 12, 30, 45)
    assert _records(caplog) == []


def test_parse_run_time_window_invalid_format_is_actionable():
    with pytest.raises(ValueError) as exc_info:
        HdfUtils.parse_run_time_window("01JAN2024 00:00:00")

    assert "DDMMMYYYY HH:MM:SS to DDMMMYYYY HH:MM:SS" in str(exc_info.value)


def test_parse_ras_datetime_ms_single_public_definition_is_silent(caplog):
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        value = HdfUtils.parse_ras_datetime_ms("01JAN2024 00:00:00:123")

    assert value == datetime(2024, 1, 1, 0, 0, 0, 123000)
    assert _records(caplog) == []


def test_parse_duration_public_method():
    assert HdfUtils.parse_duration("24:00:01") == timedelta(
        days=1,
        seconds=1,
    )


def test_window_datetime_reads_end_of_day_2400():
    from datetime import datetime
    from ras_commander.hdf import HdfUtils
    assert HdfUtils.parse_ras_window_datetime("02JAN1900 2400") == datetime(1900, 1, 3)
    assert HdfUtils.parse_ras_window_datetime("31DEC1999 2400") == datetime(2000, 1, 1)
    assert HdfUtils.parse_ras_window_datetime("02JAN1900 0130") == datetime(1900, 1, 2, 1, 30)


@pytest.mark.parametrize("time_unit,unit,seconds_per_unit", [("days", "D", 86400), ("hours", "h", 3600)])
@pytest.mark.parametrize("round_to", ["100ms", "1us", "1ns"])
def test_ordinary_timestamps_preserve_legacy_precision_and_rounding(time_unit, unit, seconds_per_unit, round_to):
    start = datetime(2020, 1, 1, microsecond=123)
    offsets = np.array([0, .0504, .00025, .000000321, -0.0504]) / seconds_per_unit
    expected = pd.DatetimeIndex(start + pd.to_timedelta(offsets, unit=unit)).round(round_to)
    actual = HdfUtils.convert_timesteps_to_datetimes(offsets, start, time_unit, round_to)
    pd.testing.assert_index_equal(actual, expected)
    assert actual.dtype == np.dtype("datetime64[ns]")


@pytest.mark.parametrize("start,offsets", [
    (datetime(3000, 1, 1), [0, 1]),
    (datetime(1500, 1, 1), [0, 1]),
    (datetime(2262, 4, 11), [0, 1]),
    (datetime(1677, 9, 22), [0, -2]),
])
@pytest.mark.parametrize("time_unit,multiplier", [("days", 1), ("hours", 24)])
def test_out_of_range_sequence_uses_checked_microseconds(start, offsets, time_unit, multiplier):
    actual = HdfUtils.convert_timesteps_to_datetimes(np.array(offsets) * multiplier, start, time_unit)
    expected = np.array([start + timedelta(days=offset) for offset in offsets], dtype="datetime64[us]")
    np.testing.assert_array_equal(actual.to_numpy(), expected)
    assert actual.dtype == np.dtype("datetime64[us]")


def test_future_timestamps_retain_microseconds_before_requested_rounding():
    result = HdfUtils.convert_timesteps_to_datetimes(
        np.array([.00025, .0504]) / 86400, datetime(3000, 1, 1), round_to="1us"
    )
    assert result[0].microsecond == 250
    assert result[1].microsecond == 50400
    rounded = HdfUtils.convert_timesteps_to_datetimes(
        np.array([.0504]) / 86400, datetime(3000, 1, 1)
    )
    assert rounded[0].microsecond == 100000


@pytest.mark.parametrize("start", [datetime(2020, 1, 1), datetime(3000, 1, 1)])
def test_timestamp_empty_and_missing_values(start):
    assert HdfUtils.convert_timesteps_to_datetimes(np.array([]), start).empty
    result = HdfUtils.convert_timesteps_to_datetimes(np.array([0, np.nan]), start)
    assert result[0].year == start.year
    assert pd.isna(result[1])


@pytest.mark.parametrize("start,offset", [(datetime(9999, 12, 31), 1), (datetime(1, 1, 1), -1), (datetime(3000, 1, 1), 1e30)])
def test_timestamp_overflow_raises_instead_of_wrapping(start, offset):
    try:
        result = HdfUtils.convert_timesteps_to_datetimes(np.array([offset]), start)
    except OverflowError:
        return  # Python's checked fallback rejects dates beyond years 1-9999.
    # pandas 3 can represent dates beyond Python datetime's range natively.
    assert abs(offset) == 1
    expected = np.datetime64(start, "us") + np.timedelta64(offset, "D")
    assert result.to_numpy()[0] == expected


@pytest.mark.parametrize("value", [np.inf, -np.inf])
def test_invalid_infinite_offsets_are_rejected(value):
    with pytest.raises((ValueError, OverflowError)):
        HdfUtils.convert_timesteps_to_datetimes(np.array([value]), datetime(3000, 1, 1))


def test_rounding_across_nanosecond_boundary_uses_microseconds():
    start = datetime(2262, 4, 11, 23, 47, 16, 854775)
    result = HdfUtils.convert_timesteps_to_datetimes(np.array([0]), start)
    assert result.dtype == np.dtype("datetime64[us]")
    assert result[0].to_pydatetime() == datetime(2262, 4, 11, 23, 47, 16, 900000)
