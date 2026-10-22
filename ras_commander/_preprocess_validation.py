"""Shared checks for completed, writer-free preprocessing HDF files."""

import h5py
import numpy as np

from .fast_hdf import read_attr


def _scalar_text(value) -> str:
    """Decode a scalar HDF attribute without treating 'False' as truthy."""
    array = np.asarray(value)
    if array.size != 1:
        return ""
    value = array.reshape(-1)[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).strip().casefold()


def _hdf_ras_major_version(hdf):
    """Return the HEC-RAS major version recorded in the HDF ``File Version``."""
    import re

    text = _scalar_text(read_attr(hdf, "File Version", None))
    match = re.search(r"hec-ras\s+(\d+)\.", text)
    return int(match.group(1)) if match else None


def _event_condition_errors(hdf, precipitation_mode=None) -> list[str]:
    """Check completion and materialized point/gridded rain without reading arrays.

    The ``Completed Successfully`` flag is required for HEC-RAS 6 and later
    (and files without a parseable ``File Version``); HEC-RAS 5.x does not
    write it.

    ``precipitation_mode`` comes from active text inputs when available, so a
    missing HDF precipitation group cannot hide enabled rainfall. Otherwise
    use the HDF's explicit mode. Uniform rainfall has a different layout and
    does not require the point/gridded Values dataset.
    """
    problems = []
    event = hdf.get("Event Conditions")
    major = _hdf_ras_major_version(hdf)
    if not isinstance(event, h5py.Group):
        problems.append("Event Conditions attribute 'Completed Successfully' must be True (Event Conditions group is missing)")
    elif (major is None or major >= 6) and _scalar_text(
        read_attr(event, "Completed Successfully", None)
    ) not in {"true", "1"}:
        # HEC-RAS 5.x never writes this flag; its completion evidence is the
        # owned engine start plus the computed-geometry (.c##) file.
        problems.append("Event Conditions attribute 'Completed Successfully' must be True")

    base = "Event Conditions/Meteorology/Precipitation"
    precipitation = hdf.get(base)
    if precipitation_mode is None:
        mode = (
            _scalar_text(read_attr(precipitation, "Mode", None))
            if isinstance(precipitation, h5py.Group) else ""
        )
    else:
        mode = str(precipitation_mode).strip().casefold()
    if mode in {"point", "gridded"}:
        values = hdf.get(f"{base}/Values")
        if not isinstance(values, h5py.Dataset) or values.ndim != 2 or not all(values.shape):
            problems.append(f"missing or empty two-dimensional {base}/Values ({mode} precipitation)")
    return problems
