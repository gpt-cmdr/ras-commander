from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
