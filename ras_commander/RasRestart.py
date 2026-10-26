"""Read native HEC-RAS restart timing without modifying hydraulic state."""

from __future__ import annotations

import datetime as dt
import math
import struct
from pathlib import Path

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)


class RasRestart:
    """Read-only access to the observed HEC-RAS 6.6 binary restart header.

    This reader supports the little-endian ``21May2021`` header written by
    HEC-RAS 6.6. Unknown layouts fail explicitly. It never derives time from a
    filename. The simulation start must come from the producing plan: the
    header stores elapsed hours and the initial calendar date, but does not
    independently identify the initial clock hour.
    """

    @staticmethod
    @log_call
    def read_header(restart_file: str | Path, *, simulation_start: dt.datetime) -> dict:
        """Return JSON-compatible native timing fields and the bound state time.

        Read only the first 321 bytes; no model, restart or HDF is changed.
        Times use the plan's naive simulation calendar (no time zone), and
        elapsed/clock values are hours. ``simulation_start`` must be the
        producing plan's start, not a value inferred from the filename.

        The observed 6.6 layout contains an initial HEC calendar date at byte
        293, elapsed-hour doubles at 305 and 313, and the current clock-hour
        double at 285. HEC represents a midnight start as the previous date
        at 24:00. Both elapsed counters must agree and the calculated state
        time must agree with the independently stored clock within 1 ms.
        Unsupported/truncated headers or inconsistent bindings raise
        ``ValueError``; filesystem errors propagate.

        Args:
            restart_file: Native restart file path (string or Path).
            simulation_start: Producing plan's naive simulation start datetime.

        Returns:
            dict: Header format, clock/date fields, elapsed hours and bound
            ISO simulation time, with a 1 ms validation tolerance.

        Raises:
            ValueError: Unsupported/malformed header or inconsistent plan binding.
            OSError: Restart file cannot be read.
        """
        if (
            not isinstance(simulation_start, dt.datetime)
            or simulation_start.tzinfo is not None
        ):
            raise ValueError("simulation_start must be a naive simulation datetime")
        path = Path(restart_file)
        with path.open("rb") as stream:
            header = stream.read(321)
        if (
            len(header) != 321
            or not header[:64].startswith(b"HEC-RAS 6.6 ")
            or header[64:73] != b"21May2021"
        ):
            raise ValueError(
                "Unsupported or truncated native restart header (expected HEC-RAS 6.6/21May2021)"
            )
        clock_h = struct.unpack_from("<d", header, 285)[0]
        year, month, day = struct.unpack_from("<3i", header, 293)
        elapsed_h, elapsed_check_h = struct.unpack_from("<2d", header, 305)
        if (
            not all(math.isfinite(v) for v in (clock_h, elapsed_h, elapsed_check_h))
            or elapsed_h < 0
            or not 0 <= clock_h <= 24.000000001
            or abs(elapsed_h - elapsed_check_h) * 3600 > 0.001
        ):
            raise ValueError("Invalid or inconsistent native restart timing counters")
        initial_date = dt.date(year, month, day)
        expected_date = simulation_start.date()
        if simulation_start.time() == dt.time():
            try:
                expected_date -= dt.timedelta(days=1)
            except OverflowError as exc:
                raise ValueError(
                    "Producing plan start exceeds the HEC simulation calendar"
                ) from exc
        if initial_date != expected_date:
            raise ValueError(
                "Native restart initial date differs from producing plan start"
            )
        try:
            simulation_time = simulation_start + dt.timedelta(hours=elapsed_h)
        except OverflowError as exc:
            raise ValueError(
                "Native restart elapsed time exceeds the simulation calendar"
            ) from exc
        calculated_clock_h = (
            simulation_time
            - simulation_time.replace(hour=0, minute=0, second=0, microsecond=0)
        ).total_seconds() / 3600
        clock_error_h = abs((calculated_clock_h - clock_h + 12) % 24 - 12)
        if clock_error_h * 3600 > 0.001:
            raise ValueError(
                "Native restart clock differs from elapsed-time/plan-start binding"
            )
        return {
            "format": "hec-ras-6.6/21May2021",
            "engine_header": header[:64].decode("ascii").rstrip(),
            "initial_date": initial_date.isoformat(),
            "clock_hour": clock_h,
            "elapsed_hours": elapsed_h,
            "elapsed_check_hours": elapsed_check_h,
            "simulation_start": simulation_start.isoformat(),
            "simulation_time": simulation_time.isoformat(),
            "time_tolerance_seconds": 0.001,
        }
