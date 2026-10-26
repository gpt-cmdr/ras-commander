"""Synthetic format fixtures; native qualification is a separate evidence gate."""

import datetime as dt
import struct

import pytest

from ras_commander.RasRestart import RasRestart


def write_header(tmp_path, *, start, hours=6, clock=None):
    data = bytearray(321)
    data[:64] = b"HEC-RAS 6.6 September 2024".ljust(64)
    data[64:73] = b"21May2021"
    initial = start.date() - dt.timedelta(days=start.time() == dt.time())
    end = start + dt.timedelta(hours=hours)
    if clock is None:
        clock = (end.hour + end.minute / 60 + end.second / 3600) or 24
    struct.pack_into(
        "<d3i2d",
        data,
        285,
        clock,
        initial.year,
        initial.month,
        initial.day,
        hours,
        hours,
    )
    path = tmp_path / "misleading.2359.rst"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    "start,hours",
    [
        (dt.datetime(2000, 1, 1), 96),
        (dt.datetime(2000, 1, 5, 18), 12),
        (dt.datetime(2000, 1, 5, 6), 6),
        (dt.datetime(2000, 1, 5), 25 + 22 / 60),
    ],
)
def test_native_time_uses_elapsed_not_filename(tmp_path, start, hours):
    path = write_header(tmp_path, start=start, hours=hours)
    result = RasRestart.read_header(path, simulation_start=start)
    assert result["simulation_time"] == (start + dt.timedelta(hours=hours)).isoformat()
    assert result["elapsed_hours"] == hours


def test_clock_binding_rejects_wrong_start_hour(tmp_path):
    start = dt.datetime(2000, 1, 5, 6)
    path = write_header(tmp_path, start=start)
    with pytest.raises(ValueError, match="clock differs"):
        RasRestart.read_header(path, simulation_start=start.replace(hour=7))


@pytest.mark.parametrize("offset,value", [(305, float("nan")), (313, 5), (285, 25)])
def test_bad_counters_fail(tmp_path, offset, value):
    start = dt.datetime(2000, 1, 1)
    path = write_header(tmp_path, start=start)
    data = bytearray(path.read_bytes())
    struct.pack_into("<d", data, offset, value)
    path.write_bytes(data)
    with pytest.raises(ValueError):
        RasRestart.read_header(path, simulation_start=start)


def test_unknown_layout_and_truncation_fail(tmp_path):
    path = tmp_path / "state.rst"
    for content in (b"", b"HEC-RAS 7.0".ljust(321)):
        path.write_bytes(content)
        with pytest.raises(ValueError, match="Unsupported"):
            RasRestart.read_header(path, simulation_start=dt.datetime(2000, 1, 1))


def test_wrong_initial_date_and_aware_start_fail(tmp_path):
    start = dt.datetime(2000, 1, 1)
    path = write_header(tmp_path, start=start)
    with pytest.raises(ValueError, match="initial date"):
        RasRestart.read_header(path, simulation_start=start + dt.timedelta(days=1))
    with pytest.raises(ValueError, match="naive"):
        RasRestart.read_header(
            path, simulation_start=start.replace(tzinfo=dt.timezone.utc)
        )


@pytest.mark.parametrize(
    "start,hours",
    [
        (dt.datetime(2000, 1, 1), 1e308),
        (dt.datetime(9999, 12, 31, 23), 2),
    ],
)
def test_elapsed_calendar_overflow_is_a_format_error(tmp_path, start, hours):
    path = write_header(tmp_path, start=start, hours=0, clock=0)
    data = bytearray(path.read_bytes())
    struct.pack_into("<2d", data, 305, hours, hours)
    path.write_bytes(data)
    with pytest.raises(ValueError, match="simulation calendar"):
        RasRestart.read_header(path, simulation_start=start)


def test_minimum_start_date_cannot_represent_hec_previous_day(tmp_path):
    path = write_header(tmp_path, start=dt.datetime(2000, 1, 1))
    with pytest.raises(ValueError, match="HEC simulation calendar"):
        RasRestart.read_header(path, simulation_start=dt.datetime.min)
