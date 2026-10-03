"""Optional native DSS7 grid writer using gyanz/pydsstools (MIT).

Calls upstream's public API; no upstream implementation is vendored.
https://github.com/gyanz/pydsstools
"""

import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd


def write_precip_grid_arrays(dss_file, pathname, data, interval_bounds, *,
                             transform, crs, units, nodata=None, overwrite=False):
    """Implementation for RasDss.write_precip_grid_arrays; imports remain lazy."""
    try:
        from affine import Affine
        from pyproj import CRS
        from pydsstools.core import UNDEFINED
        from pydsstools.core.gridinfo import GridInfoCreate, GridType, DataType
        from pydsstools.heclib.dss.HecDss import Open
    except ImportError as exc:
        raise ImportError(
            "Native grid writing requires ras-commander[dss-native] "
            "(pydsstools>=3.1,<4). Install on a Python/platform with a "
            "pydsstools wheel; Python 3.12 is supported."
        ) from exc

    target = Path(dss_file).resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"DSS output already exists: {target}")
    if target.is_dir():
        raise IsADirectoryError(str(target))
    parts = pathname.split('/')
    if len(parts) != 8 or parts[0] or parts[-1]:
        raise ValueError("pathname must contain six DSS parts: /A/B/PRECIP///F/")
    parts = parts[1:-1]
    if parts[2].upper() != 'PRECIP' or parts[3] or parts[4]:
        raise ValueError("pathname C part must be PRECIP and D/E parts must be blank")
    if any(not part or any(c in part for c in '*?\n\r') for part in (parts[0], parts[1], parts[5])):
        raise ValueError("pathname A, B and F parts must be nonempty without wildcards")
    canonical_units = {'in': 'IN', 'inch': 'IN', 'inches': 'IN',
                       'mm': 'MM', 'millimeter': 'MM', 'millimeters': 'MM'}.get(str(units).lower())
    if canonical_units is None:
        raise ValueError("units must be inches or mm; input is interval depth, not intensity")
    values = np.ma.asarray(data, dtype=np.float64).filled(np.nan)
    if values.ndim != 3 or any(size == 0 for size in values.shape):
        raise ValueError("data must have nonempty shape (time, row, column)")
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)
    if np.isinf(values).any() or np.any(values < 0) or np.any(values > np.finfo(np.float32).max):
        raise ValueError("precipitation must be nonnegative finite float32 depth or NaN/NoData")

    bounds = pd.DatetimeIndex(interval_bounds)
    if bounds.tz is not None or bounds.hasnans:
        raise ValueError("interval_bounds must be timezone-naive and contain no NaT")
    if len(bounds) != values.shape[0] + 1 or not bounds.is_monotonic_increasing or bounds.has_duplicates:
        raise ValueError("provide exactly n_times+1 strictly increasing interval boundaries")
    if any(t.second or t.microsecond or t.nanosecond for t in bounds):
        raise ValueError("DSS grid interval boundaries must have whole-minute precision")
    if any(t.year < 1600 or t.year > 9999 for t in bounds):
        raise ValueError("DSS grid dates must be in years 1600 through 9999")

    affine = transform if isinstance(transform, Affine) else Affine(*transform)
    if (not np.isfinite(tuple(affine)).all() or affine.a <= 0 or affine.e >= 0
            or affine.b != 0 or affine.d != 0
            or affine.g != 0 or affine.h != 0 or affine.i != 1
            or not np.isclose(affine.a, -affine.e, rtol=1e-10, atol=0)):
        raise ValueError("transform must describe north-up, unrotated square cells")
    projection = CRS.from_user_input(crs)
    if not projection.is_projected:
        raise ValueError("crs must be projected; reproject geographic Atlas 14 arrays first")

    def stamp(value, end=False):
        # DSS end-of-interval midnight convention; locale-independent months.
        midnight = end and value.hour == value.minute == 0
        day = value - timedelta(days=1) if midnight else value
        month = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')[day.month - 1]
        clock = '2400' if midnight else f'{value.hour:02d}{value.minute:02d}'
        return f'{day.day:02d}{month}{day.year:04d}:{clock}'

    paths = []
    for start, end in zip(bounds[:-1], bounds[1:]):
        paths.append('/' + '/'.join(parts[:3] + [stamp(start), stamp(end, True), parts[5]]) + '/')
    info = GridInfoCreate(
        grid_type=GridType.specified_time, data_type=DataType.per_cum,
        shape=values.shape[1:], cell_size=affine.a,
        crs=projection.to_wkt(version='WKT1_GDAL'), crs_name=projection.name,
        data_units=canonical_units, nodata=UNDEFINED, is_interval=True,
        min_xy=(affine.c, affine.f + affine.e * values.shape[1]),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.{target.stem}.{uuid4().hex}.dss')
    try:
        with Open(str(temporary), version=7) as writer:
            for path, frame in zip(paths, values):
                writer.put_grid(frame, path, info, flipud=True, inplace=False)
        # Reopen after close: upstream may log native failures instead of raising.
        with Open(str(temporary)) as reader:
            for path in paths:
                record = reader.read_grid(path, metadata_only=True)
                if record is None or tuple(record.gridinfo.shape) != values.shape[1:]:
                    raise RuntimeError(f"DSS grid write verification failed: {path}")
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic no-clobber publication on Windows and POSIX. Both paths
            # are siblings on the same filesystem; never replace a racing writer.
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return paths
