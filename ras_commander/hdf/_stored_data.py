"""Literal labels and civil observation dates for stored HDF data readers."""

from datetime import datetime, timedelta


def _stored_label(value):
    """Decode padding without interpreting a label as a number, bool or date."""
    if not isinstance(value, (bytes, str)):
        raise ValueError("Stored identity labels must be text")  # noqa: TRY004 -- malformed stored schema
    return (
        value.decode("utf-8").rstrip("\x00 ")
        if isinstance(value, bytes)
        else value.rstrip("\x00 ")
    )


def _observation_datetime(text):
    """Parse the sample's own date, including end-of-day 24:00."""
    try:
        date, clock = text.strip().split()
    except ValueError as exc:
        raise ValueError(f"Invalid stored observation date: {text!r}") from exc
    next_day = clock in ("2400", "24:00", "24:00:00")
    if next_day:
        clock = {"2400": "0000", "24:00": "00:00", "24:00:00": "00:00:00"}[clock]
    for fmt in ("%d%b%Y %H:%M:%S.%f", "%d%b%Y %H:%M:%S", "%d%b%Y %H:%M", "%d%b%Y %H%M"):
        try:
            parsed = datetime.strptime(f"{date} {clock}", fmt)
            return parsed + timedelta(days=int(next_day))
        except ValueError:
            continue
    raise ValueError(f"Invalid stored observation date: {text!r}")
