"""Placement check of regular time-series times before any DSS write (all backends).

HEC-DSS stores a regular series by position from its first time. HEC Monolith (the
``java`` backend) silently stores values given at other times where its own placement
puts them, a single value included, and reports success. This module refuses such input
before either writer runs, so a ``RasDss`` write never changes the times it was given:

- Minute, hour and day intervals need a constant step. An offset start such as 00:15 for
  ``1HOUR`` is kept, as HEC keeps it, and a single value at any whole minute is kept.
- Week, month, semi-month, tri-month and year intervals follow HEC-DSS's calendar
  placement (leap years, month lengths, the weekly decade block). The series is written
  to a temporary DSS7 file by the ras-commander-fast-dss engine's public API and read
  back; every value must come back at its given time. The caller's file is not touched.
- HEC's DSS6 library stores a yearly series whose first time falls in a leap year after
  2 March 00:00 one day later; for DSS6 targets that is refused.
- A single DSS6 monthly, semi-monthly or tri-monthly value is also qualified by a DSS6
  dry run (HEC keeps exactly those the engine's DSS6 writer and reader keep).

The rules and their HEC Monolith evidence come from hms-commander (PR #55, reviews 1-3):
11,992 multi-value and 7,774 single-value cases, 0 accepted values that HEC moves.
Because the calendar check applies HEC-DSS 7's placement to DSS6 files too, it refuses
some multi-value DSS6 offset series that HEC's DSS6 library would keep; the message says
so. Without the engine the calendar part is skipped with one warning; fixed intervals are
always checked. Irregular (``IR-``) E parts are not checked here.

This module is private.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd

from . import _backend

logger = logging.getLogger("ras_commander.dss.RasDss")

#: Regular E-part units of fixed length, in minutes. Weeks are calendar units: HEC-DSS
#: places weekly values by calendar blocks.
FIXED_INTERVAL_MINUTES = {
    "MIN": 1, "MINUTE": 1, "MINUTES": 1,
    "HOUR": 60, "HOURS": 60,
    "DAY": 1440, "DAYS": 1440,
}
#: E-part units whose times follow HEC-DSS's calendar placement.
CALENDAR_INTERVAL_UNITS = frozenset({
    "WEEK", "WEEKS", "MON", "MONTH", "MONTHS", "YEAR", "YEARS",
    "SEMI-MONTH", "SEMIMONTH", "TRI-MONTH", "TRIMONTH",
})
#: Units for which a single DSS6 value may also be qualified by a DSS6 dry run. Weekly
#: DSS6 values are excluded: HEC Monolith's reader drops the first weekly value (shadow
#: label D8), so there is no independent HEC read to qualify them with.
DSS6_SINGLE_VALUE_UNITS = frozenset({
    "MON", "MONTH", "MONTHS", "SEMI-MONTH", "SEMIMONTH", "TRI-MONTH", "TRIMONTH",
})
#: Text of the engine's refusal of ``times=``: value index, given and expected time.
_ENGINE_TIMES_REFUSAL = re.compile(r"value (\d+) is at (\S+), expected (\S+)")
#: Text of a newer engine's refusal of a series whose values HEC-DSS would store at one
#: time (a day of the month that a shorter month lacks): the two value indexes.
_ENGINE_COLLISION_REFUSAL = re.compile(r"values (\d+) and (\d+) at one time")

_calendar_check_warned = False


def reset_warning() -> None:
    """Allow the no-engine warning to be logged again (tests)."""
    global _calendar_check_warned
    _calendar_check_warned = False


def write_stamps(pathname: str, times: Any, values: Any) -> Optional[Tuple[str, np.ndarray]]:
    """``(e_part, stamps)`` for a regular-interval write that this check applies to, else None.

    Returns None (no check) for irregular E parts, unparsable pathnames, and arguments the
    writers refuse themselves (length mismatch, empty, NaT, time-zone aware, not whole
    minutes, not strictly increasing): the writers keep raising their own errors for those.
    """
    parts = str(pathname).split("/")
    if len(parts) != 8:
        return None
    e_part = parts[5].strip()
    if not e_part or e_part.upper().startswith("IR-"):
        return None
    try:
        index = pd.DatetimeIndex(times)
        n_values = len(values)
    except Exception:
        return None
    if index.tz is not None or len(index) != n_values or len(index) == 0 or index.hasnans:
        return None
    stamps = index.to_numpy(dtype="datetime64[ns]")
    ns = stamps.astype(np.int64)
    if np.any(ns % 60_000_000_000) or (len(ns) > 1 and np.any(np.diff(ns) <= 0)):
        return None
    return e_part, stamps.astype("datetime64[s]")


def check_regular_stamps(pathname: str, e_part: str, stamps: np.ndarray,
                         version: Optional[int] = None) -> None:
    """``ValueError`` when HEC-DSS would not store every value at its given time.

    ``version`` is the target file's DSS version (6 or 7; None when unknown). See the
    module docstring for the rules.
    """
    if len(stamps) == 0:
        return
    match = re.fullmatch(r"(\d*)\s*([A-Z]+(?:-[A-Z]+)?)", e_part.strip().upper())
    if not match:
        return
    count, unit = int(match.group(1) or 1), match.group(2)
    if unit in FIXED_INTERVAL_MINUTES:
        if len(stamps) < 2:
            return
        step = np.timedelta64(count * FIXED_INTERVAL_MINUTES[unit], "m")
        expected = (stamps[0] + step * np.arange(len(stamps))).astype("datetime64[s]")
        bad = np.flatnonzero(stamps != expected)
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"Refused before writing {pathname!r}: times are not regular for the E part "
                f"{e_part!r}: value {i} is at {pd.Timestamp(stamps[i])}, expected "
                f"{pd.Timestamp(expected[i])}. HEC-DSS stores a regular series by position "
                "from its first time, so this value would be stored at the expected time. "
                "What works: write each regular run of times separately, fill the gaps with "
                "NaN (stored as missing), or use an irregular E part (IR-DAY .. IR-CENTURY).")
    elif unit in CALENDAR_INTERVAL_UNITS:
        if version == 6 and unit in ("YEAR", "YEARS"):
            _check_dss6_yearly_start(pathname, e_part, stamps)
        _check_calendar_stamps(pathname, e_part, stamps, version)


def _check_dss6_yearly_start(pathname: str, e_part: str, stamps: np.ndarray) -> None:
    """HEC's DSS6 library moves a yearly series (one value or more) by a day when its first
    time falls in a leap year after 2 March 00:00 (checked with HEC Monolith for 1904,
    2000, 2016, 2020 and 2024). The same times are kept in a DSS7 file."""
    first = pd.Timestamp(stamps[0])
    if first.is_leap_year and first > pd.Timestamp(first.year, 3, 2):
        raise ValueError(
            f"Refused before writing {pathname!r} to a DSS6 file: HEC-DSS 6 stores a "
            f"{e_part} series whose first time falls in a leap year after 2 March one day "
            f"later (first time {first} would be stored at {first + pd.Timedelta(days=1)}). "
            "What works: write the same times to a DSS7 file (dss_version=7, or a new or "
            "existing DSS7 file), where HEC-DSS keeps them.")


def _calendar_refusal(pathname: str, e_part: str, stamps: np.ndarray, i: int,
                      stored_at: Optional[Any], version: Optional[int],
                      dss6_keeps: bool = False, collides_with: Optional[int] = None) -> ValueError:
    """The error for a calendar series HEC-DSS would not keep: which value, where HEC
    places it, and what works. ``dss6_keeps``: a single value a DSS6 file keeps.
    ``collides_with``: HEC-DSS would store value ``i`` at the same time as this value."""
    given = pd.Timestamp(stamps[min(i, len(stamps) - 1)])
    if collides_with is not None:
        where = (f"would store it at the same time as value {collides_with}, so one of "
                 "the two values would be lost")
    elif stored_at is None:
        where = "would not store it at all"
    else:
        where = f"places it at {pd.Timestamp(stored_at)}"
    what = "this value" if len(stamps) == 1 else f"value {i}"
    message = [
        f"Refused before writing {pathname!r}: HEC-DSS keeps a {e_part} series on its "
        f"calendar placement from the first time, and {what} (given at {given}) does not "
        f"fit it: HEC-DSS {where}.",
    ]
    if dss6_keeps:
        message.append(
            "In a DSS6 file HEC-DSS keeps this single value at its given time, so writing "
            "it to a DSS6 file works (dss_version=6, or an existing DSS6 file).")
    else:
        message.append(
            "Changing the DSS version does not help: this check applies HEC-DSS 7's "
            "placement to DSS6 and DSS7 files alike"
            + (", so a DSS6 file refuses this value too." if version != 6 else "."))
    if collides_with is not None:
        message.append(
            "What works: start the series on a day of the month that every month has "
            "(the 1st to the 28th), or on a time HEC-DSS keeps; a day of the month that a "
            "shorter month lacks (the 29th to 31st) has no time HEC keeps for it.")
    elif stored_at is not None:
        message.append(
            f"What works: give {what} at {pd.Timestamp(stored_at)}, where HEC-DSS stores "
            "it, with the later times following the same placement. A day of the month "
            "that a shorter month lacks (the 29th to 31st), or a weekly series starting in "
            "the week that contains 1 January of a DSS decade block, has no time HEC keeps "
            "for it; use a time HEC keeps.")
    if version == 6:
        message.append(
            "Note: HEC-DSS 6's own library keeps some day-of-month and day-of-year "
            "offset series that this check refuses (a conservative restriction of "
            "ras-commander's writers); ras-commander cannot write those times.")
    return ValueError(" ".join(message))


def _round_trip(dc: Any, version: int, check_path: str, stamps: np.ndarray,
                values: np.ndarray) -> Tuple[Optional[int], Optional[Any], Optional[str]]:
    """Write ``stamps`` to a temporary file of ``version`` with the engine and read them
    back. Returns ``(i, stored_at, engine_message)``: ``i`` is None when every value comes
    back at its time; otherwise the first value that does not, where HEC-DSS stores it
    (None if nowhere), and the engine's refusal text if it refused."""
    sync = {"sync": "none"} if _backend.takes_keyword(dc.write_timeseries, "sync") else {}
    with tempfile.TemporaryDirectory(prefix="ras-commander-dss-times-") as folder:
        probe = str(Path(folder) / "times.dss")
        if _backend.takes_keyword(dc.create, "sync"):
            dc.create(probe, version, sync="none")
        else:
            dc.create(probe, version)
        try:
            dc.write_timeseries(probe, check_path, values, times=stamps, units="",
                                data_type="INST-VAL", version=version, **sync)
        except ValueError as exc:
            found = _ENGINE_TIMES_REFUSAL.search(str(exc))
            if found:
                return int(found.group(1)), np.datetime64(found.group(3)), str(exc)
            collision = _ENGINE_COLLISION_REFUSAL.search(str(exc))
            if collision:
                # The first of the two is the value that does not fit HEC's placement.
                return int(collision.group(1)), ("collides", int(collision.group(2))), str(exc)
            return 0, None, str(exc)
        back = dc.read_timeseries(probe, check_path)
    got_times = back.index.to_numpy(dtype="datetime64[s]")
    got_values = back["value"].to_numpy(dtype=np.float64)
    n = min(len(got_times), len(stamps))
    bad = np.flatnonzero((got_times[:n] != stamps[:n]) | (got_values[:n] != values[:n]))
    if bad.size or len(got_times) != len(stamps):
        i = int(bad[0]) if bad.size else n
        return i, (got_times[i] if i < len(got_times) else None), None
    return None, None, None


def _check_calendar_stamps(pathname: str, e_part: str, stamps: np.ndarray,
                           version: Optional[int] = None) -> None:
    """``ValueError`` unless HEC-DSS stores every value at its given time. Uses the
    engine's public writer and reader on a temporary DSS7 file (and, for a single DSS6
    monthly, semi-monthly or tri-monthly value, a temporary DSS6 file)."""
    global _calendar_check_warned
    dc = _backend._maybe_native()
    if dc is None or not all(callable(getattr(dc, name, None))
                             for name in ("create", "write_timeseries", "read_timeseries")):
        if not _calendar_check_warned:
            _calendar_check_warned = True
            logger.warning(
                "Times of %s series are not checked against HEC-DSS's calendar placement "
                "because ras-commander-fast-dss is not installed or failed to load "
                "(install it with 'pip install ras-commander-fast-dss'). HEC-DSS stores a "
                "regular series by position from its first time, so values given at "
                "other times are stored at different times.", e_part)
        return
    parts = pathname.split("/")
    check_path = f"/{parts[1]}/{parts[2]}/{parts[3]}//{parts[5]}/{parts[6]}/"
    values = np.arange(len(stamps), dtype=np.float64)
    unit = re.sub(r"^\d+\s*", "", e_part.strip().upper())
    try:
        i, stored_at, engine_message = _round_trip(dc, 7, check_path, stamps, values)
        dss6_keeps = False
        if i is not None and len(stamps) == 1 and unit in DSS6_SINGLE_VALUE_UNITS:
            dss6_keeps = _round_trip(dc, 6, check_path, stamps, values)[0] is None
            if dss6_keeps and version == 6:
                return  # a single DSS6 value HEC's DSS6 library keeps
    except Exception as exc:  # an engine failure must not block the write
        logger.warning("Could not check the times of %s against HEC-DSS's calendar "
                       "placement (%s: %s); the write goes ahead unchecked.",
                       pathname, type(exc).__name__, exc)
        return
    if i is None:
        return
    if isinstance(stored_at, tuple):  # ("collides", other value index)
        raise _calendar_refusal(pathname, e_part, stamps, i, None, version,
                                collides_with=stored_at[1])
    if stored_at is None and engine_message:
        remedy = ("In a DSS6 file HEC-DSS keeps this single value at its given time, so "
                  "writing it to a DSS6 file works." if dss6_keeps else
                  "Changing the DSS version does not help.")
        raise ValueError(
            f"Refused before writing {pathname!r}: HEC-DSS would not keep these "
            f"{e_part} times ({engine_message}). {remedy}")
    raise _calendar_refusal(pathname, e_part, stamps, i, stored_at, version,
                            dss6_keeps=dss6_keeps)
