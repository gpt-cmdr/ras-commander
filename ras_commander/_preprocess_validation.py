"""Shared checks for completed, writer-free preprocessing HDF files."""

import h5py
import numpy as np


def _scalar_text(value) -> str:
    """Decode a scalar HDF attribute without treating 'False' as truthy."""
    array = np.asarray(value)
    if array.size != 1:
        return ""
    value = array.reshape(-1)[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).strip().casefold()


def _event_condition_errors(hdf, precipitation_mode=None) -> list[str]:
    """Check completion and materialized point/gridded rain without reading arrays.

    ``precipitation_mode`` comes from active text inputs when available, so a
    missing HDF precipitation group cannot hide enabled rainfall. Otherwise
    use the HDF's explicit mode. Uniform rainfall has a different layout and
    does not require the point/gridded Values dataset.
    """
    problems = []
    event = hdf.get("Event Conditions")
    if not isinstance(event, h5py.Group) or _scalar_text(
        event.attrs.get("Completed Successfully")
    ) not in {"true", "1"}:
        problems.append("Event Conditions attribute 'Completed Successfully' must be True")

    base = "Event Conditions/Meteorology/Precipitation"
    precipitation = hdf.get(base)
    if precipitation_mode is None:
        mode = (
            _scalar_text(precipitation.attrs.get("Mode"))
            if isinstance(precipitation, h5py.Group) else ""
        )
    else:
        mode = str(precipitation_mode).strip().casefold()
    if mode in {"point", "gridded"}:
        values = hdf.get(f"{base}/Values")
        if not isinstance(values, h5py.Dataset) or values.ndim != 2 or not all(values.shape):
            problems.append(f"missing or empty two-dimensional {base}/Values ({mode} precipitation)")
    return problems
