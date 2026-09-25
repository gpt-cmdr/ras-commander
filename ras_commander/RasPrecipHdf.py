"""
RasPrecipHdf - Gridded precipitation payload authoring for unsteady flow HDFs.

Writes the ``Imported Raster Data`` payload that HEC-RAS's "Import Raster Data"
action produces, directly into an unsteady flow HDF (``*.u##.hdf``)::

    /Event Conditions/Meteorology/Precipitation/Imported Raster Data/
        Values
        Values (Vertical)

Why this is a legitimate direct HDF write, when most of the unsteady HDF is not:
HEC-RAS deletes and rebuilds the ``.u##.hdf`` from the ``.u##`` plaintext on every
save and every compute, so any attribute with a plaintext representation is
regenerated and cannot be authored here. ``Imported Raster Data`` is the sole
exception - it has no plaintext form, and the rebuild explicitly copies it forward.

That copy is driven by the Met BC collection parsed from the ``.u##`` text, so a
payload written for a variable that has **no** ``Met BC=`` block in the plaintext is
silently destroyed on the next save. ``write_gridded_precip_raster`` therefore
verifies the plaintext block exists before writing.

Units are honored by HEC-RAS, not decorative. The reader computes
``factor = Ratio * VerticalUnits.ConvertTo(project_precip_units)``, so a payload
mislabelled ``mm`` in a US Customary project is silently divided by 25.4. ``units``
is mandatory for that reason - there is no safe default.

The storage layout (chunk shapes, fill value, compression, attribute set) follows
HEC-RAS's own writer (``H5RasterWriter.WriteAccumulatedRaster`` and
``OptimizeForVerticalReading``). Decompressed data and dataset structure match a
native import; raw compressed bytes do not, because HEC-RAS writes pre-compressed
chunks with .NET's deflate.

Scope: precipitation only. The units vocabulary, ``Data Type`` and time-series
encoding enforced here are HEC-RAS's precipitation contract; other meteorological
variables (wind, pressure, temperature) are imported with different attribute
semantics and are not supported.

All methods are static; do not instantiate this class.
"""

from __future__ import annotations

import math
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, Tuple, Union

from .ComputeResults import PrecipRasterImportResult
from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)


# HEC-RAS chunk sizing target. A bare 1048576 literal in H5Assist; 1 MiB exactly,
# not 1,000,000. It is a soft cap on chunk HEIGHT, not a guarantee on chunk size:
# when one row already exceeds it the floor yields 0 and the max(1) clamp lets the
# chunk exceed the target.
MAX_CHUNK_BYTES = 1_048_576

# Vocabularies accepted by HEC-RAS's Precipitation.ParseDataType, which selects
# which unit parser runs. An illegal (data_type, units) pair is a hard load failure.
_LENGTH_UNITS = {"in", "inch", "inches", "mm", "millimeter", "millimeters"}
_MASS_AREA_UNITS = {"kg/m^2", "[kg/m^2]", "[kg/(m^2)]"}
_RATE_UNITS = {
    "in/hr", "inchesperhour", "iph", "inches/hour",
    "mm/hr", "millimeterperhour", "mmph",
}

_DATA_TYPE_VOCABULARY = {
    "cumulative": _LENGTH_UNITS,
    "per-cum": _LENGTH_UNITS | _MASS_AREA_UNITS,
    "per-avg": _RATE_UNITS,
    "per-aver": _RATE_UNITS,
    "inst-val": _RATE_UNITS,
}

# Labels, as found in NetCDF / CF metadata, that identify a depth unit. Rate labels
# are reduced to their depth unit by stripping a per-hour suffix first.
_MM_LABELS = {
    "mm", "millimeter", "millimeters", "millimetre", "millimetres",
    "kg/m^2", "kg/m2", "kgm-2", "kgm^-2", "[kg/m^2]", "[kg/(m^2)]",
    "mmph", "millimeterperhour",
}
_IN_LABELS = {"in", "inch", "inches", "iph", "inchesperhour"}
_PER_HOUR_SUFFIXES = ("/hour", "/hr", "/h", "hr-1", "hr^-1", "h-1", "h^-1")

_VALUE_TYPES = ("amount", "rate", "cumulative")

_SUPPORTED_MET_VARIABLES = ("Precipitation",)
_IMPORTED_RASTER_GROUP = "Event Conditions/Meteorology/{variable}/Imported Raster Data"

# Relative tolerance for regular / square grid checks.
_GRID_RTOL = 1e-4


class RasPrecipHdf:
    """
    Author gridded precipitation payloads into unsteady flow HDF files.

    All methods are static; do not instantiate this class.
    """

    # ---------------------------------------------------------------- chunking

    @staticmethod
    @log_call
    def get_values_chunks(n_times: int, n_cells: int, itemsize: int = 4) -> Tuple[int, int]:
        """
        Chunk shape HEC-RAS uses for the ``Values`` dataset.

        Mirrors ``H5Writer.OptimalChunking``: the chunk spans the full dataset
        width; only the time axis is computed, by floor division, then clamped to
        ``[1, n_times]``.

        Parameters
        ----------
        n_times : int
            Number of time steps (dataset height).
        n_cells : int
            Number of raster cells (dataset width).
        itemsize : int, default 4
            Bytes per value (HEC-RAS uses the element size of the dataset type).

        Returns
        -------
        tuple
            ``(rows_per_chunk, n_cells)``.

        Raises
        ------
        ValueError
            If a dimension is not positive. HEC-RAS throws OverflowException for a
            zero width rather than returning a degenerate chunk.
        """
        RasPrecipHdf._require_positive_dimensions(n_times, n_cells)
        rows = int(math.floor(MAX_CHUNK_BYTES / float(n_cells * itemsize)))
        rows = max(min(rows, n_times), 1)
        return (rows, n_cells)

    @staticmethod
    @log_call
    def get_vertical_chunks(n_times: int, n_cells: int) -> Tuple[int, int]:
        """
        Chunk shape HEC-RAS uses for the ``Values (Vertical)`` dataset.

        Mirrors ``H5Reader.ColumnChunkSize``. Two deliberate differences from
        :meth:`get_values_chunks`: it rounds up rather than down, and HEC-RAS
        hardcodes 4 bytes per value at the call site.

        Parameters
        ----------
        n_times : int
            Number of time steps (dataset height).
        n_cells : int
            Number of raster cells (dataset width).

        Returns
        -------
        tuple
            ``(n_times, cols_per_chunk)``.

        Raises
        ------
        ValueError
            If a dimension is not positive.
        """
        RasPrecipHdf._require_positive_dimensions(n_times, n_cells)
        cols = int(math.ceil(MAX_CHUNK_BYTES / float(n_times * 4)))
        cols = max(min(cols, n_cells), 1)
        return (n_times, cols)

    # ------------------------------------------------------------------- units

    @staticmethod
    @log_call
    def normalize_units(units: str) -> str:
        """
        Normalize a units argument to one HEC-RAS accepts under ``cumulative``.

        ``kg/m^2`` and its bracketed spellings are numerically identical to mm but
        are legal only under ``per-cum``; they are folded to ``mm`` so the common
        ``cumulative`` path stays valid. Recognized spellings of inches and
        millimetres collapse to ``in`` / ``mm``. Anything else is returned stripped
        and left for :meth:`validate_data_type_units` to judge.

        Parameters
        ----------
        units : str
            Units label supplied by the caller.

        Returns
        -------
        str
            ``"in"``, ``"mm"``, or the stripped input when unrecognized.

        Raises
        ------
        ValueError
            If the label is empty. HEC-RAS hard-errors on an empty ``Units``.
        """
        if units is None or not str(units).strip():
            raise ValueError(
                "units must be a non-empty string; HEC-RAS raises a hard load "
                "error when the Units attribute is empty"
            )
        clean = str(units).strip().lower()
        if clean in _MASS_AREA_UNITS or clean in {"mm", "millimeter", "millimeters"}:
            return "mm"
        if clean in {"in", "inch", "inches"}:
            return "in"
        return str(units).strip()

    @staticmethod
    @log_call
    def infer_depth_units(label: Optional[str]) -> Optional[str]:
        """
        Infer the depth unit a metadata units label refers to.

        Accepts depth labels and per-hour rate labels in common HEC-RAS and CF
        spellings (``"mm"``, ``"kg m-2"``, ``"mm/hr"``, ``"in/hr"``...). Per-second
        labels are deliberately not recognized: they describe a different time base,
        not merely a different depth unit.

        Parameters
        ----------
        label : str or None
            A ``units`` attribute value.

        Returns
        -------
        str or None
            ``"mm"`` or ``"in"``, or None when the label is absent or unrecognized.
        """
        if label is None:
            return None
        clean = str(label).strip().lower().replace(" ", "")
        if not clean:
            return None
        for suffix in _PER_HOUR_SUFFIXES:
            if clean.endswith(suffix) and len(clean) > len(suffix):
                clean = clean[: -len(suffix)]
                break
        if clean in _MM_LABELS:
            return "mm"
        if clean in _IN_LABELS:
            return "in"
        return None

    @staticmethod
    @log_call
    def classify_temporal_units(
        label: Optional[str],
    ) -> Literal["depth", "rate_per_hour", "rate_other", "unknown"]:
        """Classify a precipitation-units label without losing its time basis.

        HEC-RAS and precipitation products use several equivalent spellings for
        hourly rates (for example ``mm/hr``, ``mmph``, and ``mm h^-1``).  Depth
        inference alone intentionally removes that suffix, so callers that must
        validate temporal semantics should use this classifier first.
        """
        if label is None:
            return "unknown"
        clean = str(label).strip().lower().replace(" ", "")
        if not clean:
            return "unknown"

        normalized_rate_units = {
            value.replace(" ", "") for value in _RATE_UNITS
        }
        if clean in normalized_rate_units or any(
            clean.endswith(suffix) and len(clean) > len(suffix)
            for suffix in _PER_HOUR_SUFFIXES
        ):
            return "rate_per_hour"

        other_rate_suffixes = (
            "/second",
            "/sec",
            "/s",
            "second-1",
            "second^-1",
            "sec-1",
            "sec^-1",
            "s-1",
            "s^-1",
            "/day",
            "/d",
            "day-1",
            "day^-1",
            "d-1",
            "d^-1",
        )
        if any(
            clean.endswith(suffix) and len(clean) > len(suffix)
            for suffix in other_rate_suffixes
        ):
            return "rate_other"
        if RasPrecipHdf.infer_depth_units(label) is not None:
            return "depth"
        return "unknown"

    @staticmethod
    @log_call
    def validate_data_type_units(data_type: str, units: str) -> None:
        """
        Validate a (``Data Type``, ``Units``) pair against HEC-RAS's parser table.

        ``Data Type`` selects which unit vocabulary HEC-RAS accepts. An illegal
        pair - ``per-avg`` with ``mm``, for instance - is a hard load failure inside
        HEC-RAS, so it is rejected here rather than written.

        Parameters
        ----------
        data_type : str
            ``cumulative``, ``per-cum``, ``per-avg``, ``per-aver`` or ``inst-val``.
        units : str
            Units label to check against that data type's vocabulary.

        Raises
        ------
        ValueError
            If ``data_type`` is unknown, or ``units`` is not legal for it.
        """
        if not data_type or not str(data_type).strip():
            raise ValueError(
                "data_type must be non-empty; HEC-RAS hard-errors on an empty "
                "Data Type attribute"
            )
        key = str(data_type).strip().lower()
        if key not in _DATA_TYPE_VOCABULARY:
            raise ValueError(
                f"Unknown Data Type {data_type!r}. "
                f"Legal values: {sorted(_DATA_TYPE_VOCABULARY)}"
            )
        allowed = _DATA_TYPE_VOCABULARY[key]
        if str(units).strip().lower() not in allowed:
            raise ValueError(
                f"Units {units!r} is not valid for Data Type {data_type!r}. "
                f"HEC-RAS accepts {sorted(allowed)} for this Data Type, and a "
                f"mismatch is a hard load failure."
            )

    # -------------------------------------------------------------------- grid

    @staticmethod
    @log_call
    def get_grid_from_coords(
        x_coords: Any,
        y_coords: Any,
        default_cell_size: Optional[float] = None,
    ) -> Tuple[float, float, float, int, int]:
        """
        Derive the HEC-RAS raster definition from cell-centre coordinates.

        HEC-RAS stores ``Raster Left`` / ``Raster Top`` as the outer cell EDGES
        (GDAL geotransform ``GT[0]`` / ``GT[3]``), with a single square cell size.

        Parameters
        ----------
        x_coords, y_coords : array-like
            Cell-centre coordinates. Each must be monotonic and regularly spaced;
            either direction is accepted.
        default_cell_size : float, optional
            Used, with a warning, when the grid is 1 x 1 and the spacing cannot be
            measured. When omitted, a 1 x 1 grid raises.

        Returns
        -------
        tuple
            ``(raster_left, raster_top, cell_size, n_rows, n_cols)``.

        Raises
        ------
        ValueError
            If spacing is irregular or non-monotonic, cells are not square, or the
            cell size cannot be determined. Writing a single cell size for such a
            grid would silently misplace it.
        """
        import numpy as np

        x = np.asarray(x_coords, dtype=np.float64).ravel()
        y = np.asarray(y_coords, dtype=np.float64).ravel()
        if x.size == 0 or y.size == 0:
            raise ValueError("x_coords and y_coords must be non-empty")

        def _spacing(coords: Any, axis_name: str) -> Optional[float]:
            if coords.size < 2:
                return None
            steps = np.diff(coords)
            step = float(steps[0])
            if step == 0 or not np.allclose(steps, step, rtol=_GRID_RTOL, atol=0.0):
                raise ValueError(
                    f"{axis_name} coordinates are not monotonic and regularly spaced; "
                    f"HEC-RAS raster data requires a regular grid"
                )
            return abs(step)

        dx = _spacing(x, "x")
        dy = _spacing(y, "y")
        if dx is not None and dy is not None:
            if not math.isclose(dx, dy, rel_tol=_GRID_RTOL):
                raise ValueError(
                    f"Grid cells are not square (dx={dx}, dy={dy}); HEC-RAS stores a "
                    f"single Raster Cellsize"
                )
            cell_size = dx
        elif dx is not None or dy is not None:
            cell_size = dx if dx is not None else dy
        elif default_cell_size is not None:
            cell_size = float(default_cell_size)
            logger.warning(
                "Cannot measure cell size from a 1 x 1 grid; using default %s",
                cell_size,
            )
        else:
            raise ValueError(
                "Cannot determine cell size from a 1 x 1 grid; pass default_cell_size"
            )

        raster_left = float(x.min()) - cell_size / 2.0
        raster_top = float(y.max()) + cell_size / 2.0
        return raster_left, raster_top, float(cell_size), int(y.size), int(x.size)

    @staticmethod
    @log_call
    def orient_north_up(values: Any, x_coords: Any, y_coords: Any) -> Tuple[Any, Any, Any]:
        """
        Reorder a ``(time, y, x)`` field so row 0 is north and column 0 is west.

        HEC-RAS flattens the grid in C order with row 0 at ``Raster Top``. A source
        stored south-first (ascending y) or east-first (descending x) would
        otherwise be written mirrored with no error.

        Parameters
        ----------
        values : array-like
            ``(time, y, x)`` field.
        x_coords, y_coords : array-like
            Coordinates matching the x and y axes of ``values``.

        Returns
        -------
        tuple
            ``(values, x_coords, y_coords)``, reordered. Reordering returns views.

        Raises
        ------
        ValueError
            If ``values`` is not three-dimensional.
        """
        import numpy as np

        arr = np.asarray(values)
        if arr.ndim != 3:
            raise ValueError(f"values must be 3-D (time, y, x), got shape {arr.shape}")
        x = np.asarray(x_coords)
        y = np.asarray(y_coords)
        if y.size > 1 and y[-1] > y[0]:
            arr = arr[:, ::-1, :]
            y = y[::-1]
        if x.size > 1 and x[-1] < x[0]:
            arr = arr[:, :, ::-1]
            x = x[::-1]
        return arr, x, y

    # ------------------------------------------------------------- accumulation

    @staticmethod
    @log_call
    def convert_to_cumulative(
        values: Any,
        times: Sequence[Any],
        value_type: str,
        first_timestep_hours: Optional[float] = None,
    ) -> Tuple[Any, list]:
        """
        Convert a per-interval field to the cumulative payload HEC-RAS stores.

        HEC-RAS reads row 0 as the accumulation datum and delivers
        ``row[i] - row[i-1]``. Band ``i`` is taken to cover the interval ending at
        ``times[i]``. The first band has no preceding timestamp, so - exactly as in
        the HEC-RAS import dialog - it is only delivered when
        ``first_timestep_hours`` is supplied (the dialog's "First Timestep
        Duration"). That prepends a zero row at ``times[0] - first_timestep_hours``
        and yields ``n+1`` rows.

        Leaving it ``None`` reproduces the dialog's default, which drops the first
        band. A warning reports the magnitude whenever that discards non-zero data.

        The caller's array is not modified; the conversion works on a single float32
        copy.

        Parameters
        ----------
        values : array-like
            Per-interval field with time on axis 0, e.g. ``(n_times, rows, cols)``.
            NaN is treated as zero.
        times : sequence
            ``n_times`` timestamps, strictly increasing.
        value_type : {"amount", "rate", "cumulative"}
            ``amount`` - per-interval depths.
            ``rate`` - rates per hour, weighted by each interval's duration.
            ``cumulative`` - already cumulative; returned as float32, unchanged.
        first_timestep_hours : float, optional
            Duration of the first band's interval, in hours. Must be positive.

        Returns
        -------
        tuple
            ``(cumulative_values, times_out)``.

        Raises
        ------
        ValueError
            Unknown ``value_type``, non-increasing ``times``, a length mismatch, or a
            non-positive ``first_timestep_hours``.
        """
        import numpy as np
        import pandas as pd

        if value_type not in _VALUE_TYPES:
            raise ValueError(
                f"value_type must be one of {_VALUE_TYPES}, got {value_type!r}"
            )

        arr = np.array(values, dtype=np.float32)
        if arr.ndim < 2:
            raise ValueError(
                f"values must have time on axis 0 plus spatial axes, got shape {arr.shape}"
            )

        stamps = list(pd.to_datetime(list(times)))
        n_times = arr.shape[0]
        if len(stamps) != n_times:
            raise ValueError(
                f"times has {len(stamps)} entries but values has {n_times} time steps"
            )
        deltas = np.array(
            [(stamps[i] - stamps[i - 1]).total_seconds() / 3600.0 for i in range(1, n_times)],
            dtype=np.float64,
        )
        if deltas.size and (not np.all(np.isfinite(deltas)) or np.any(deltas <= 0)):
            raise ValueError("times must be strictly increasing")

        if value_type == "cumulative":
            if first_timestep_hours is not None:
                raise ValueError(
                    "first_timestep_hours does not apply to value_type='cumulative'"
                )
            return arr, stamps

        ftd: Optional[float] = None
        if first_timestep_hours is not None:
            ftd = float(first_timestep_hours)
            if not math.isfinite(ftd) or ftd <= 0:
                raise ValueError(
                    f"first_timestep_hours must be positive, got {first_timestep_hours!r}"
                )

        np.nan_to_num(arr, copy=False, nan=0.0)

        if ftd is None and n_times and np.any(arr[0] != 0):
            label = "depth" if value_type == "amount" else "rate"
            logger.warning(
                "First time step (%s) is not delivered: HEC-RAS treats row 0 as the "
                "accumulation datum. Maximum %s discarded: %.6g. Pass "
                "first_timestep_hours (the import dialog's 'First Timestep Duration') "
                "to preserve it.",
                stamps[0], label, float(np.max(np.abs(arr[0]))),
            )

        if value_type == "rate":
            weights = np.concatenate([[ftd if ftd is not None else 0.0], deltas])
            arr *= weights.astype(np.float32).reshape((n_times,) + (1,) * (arr.ndim - 1))
        elif ftd is None:
            arr[0] = 0.0

        if ftd is None:
            np.cumsum(arr, axis=0, out=arr)
            return arr, stamps

        cumulative = np.empty((n_times + 1,) + arr.shape[1:], dtype=np.float32)
        cumulative[0] = 0.0
        np.cumsum(arr, axis=0, out=cumulative[1:])
        return cumulative, [stamps[0] - pd.Timedelta(hours=ftd)] + stamps

    # ------------------------------------------------------------------ writer

    @staticmethod
    @log_call
    def write_gridded_precip_raster(
        unsteady_hdf_path: Union[str, Path],
        cumulative_values: Any,
        times: Sequence[Any],
        raster_left: float,
        raster_top: float,
        cell_size: float,
        projection: Optional[str],
        units: str,
        met_variable: str = "Precipitation",
        nodata: Optional[float] = -9999.0,
        require_met_bc_block: bool = True,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> PrecipRasterImportResult:
        """
        Write an ``Imported Raster Data`` payload into an unsteady flow HDF.

        Parameters
        ----------
        unsteady_hdf_path : str or Path
            Unsteady flow HDF (``*.u##.hdf``). Created if it does not exist; HEC-RAS
            rebuilds the rest of the file from the ``.u##`` text on the next save
            and copies this payload forward.
        cumulative_values : array-like
            ``(n_times, rows, cols)`` cumulative field, row 0 = north, column 0 =
            west, first row the accumulation datum (normally zeros). See
            :meth:`convert_to_cumulative` and :meth:`orient_north_up`.
        times : sequence
            ``n_times`` timestamps, strictly increasing.
        raster_left, raster_top : float
            Outer WEST and NORTH cell edges, in ``projection`` units (GDAL
            geotransform ``GT[0]`` / ``GT[3]``).
        cell_size : float
            Square cell size, in ``projection`` units.
        projection : str or None
            ASCII WKT of the grid's CRS. HEC-RAS reprojects to the model; it does
            not have to match the model CRS. ``None`` omits the attribute, which
            leaves HEC-RAS to assume the project CRS - only correct if the grid is
            already in it.
        units : str
            ``in`` or ``mm`` (``kg/m^2`` is accepted and written as ``mm``). HEC-RAS
            converts from these units to the project's, so this must describe the
            data, not the project.
        met_variable : str, default "Precipitation"
            Meteorology variable group. Only ``"Precipitation"`` is supported.
        nodata : float or None, default -9999.0
            ``NoData`` attribute value. ``None`` omits it, as HEC-RAS does when the
            source declares none. HEC-RAS does not substitute this value into the
            payload.
        require_met_bc_block : bool, default True
            Require a ``Met BC=<met_variable>|`` block in the sibling ``.u##`` text.
            Without it HEC-RAS destroys this payload on the next save.
        overwrite : bool, default False
            Replace an existing payload. When False and one exists, nothing is
            written and the result is marked skipped.
        dry_run : bool, default False
            Validate inputs and report the layout without writing.

        Returns
        -------
        PrecipRasterImportResult

        Raises
        ------
        ValueError
            Invalid shape, times, grid, units, projection text, variable, or a
            missing Met BC block.
        FileNotFoundError
            The parent folder, or a required ``.u##`` text file, does not exist.
        """
        import h5py
        import numpy as np
        import pandas as pd

        started = time.perf_counter()
        hdf_path = Path(unsteady_hdf_path)

        if met_variable not in _SUPPORTED_MET_VARIABLES:
            raise ValueError(
                f"met_variable {met_variable!r} is not supported; only "
                f"{list(_SUPPORTED_MET_VARIABLES)}. The units vocabulary, Data Type "
                f"and time-series encoding written here are HEC-RAS's precipitation "
                f"contract; other meteorological variables use different attributes."
            )

        units_out = RasPrecipHdf.normalize_units(units)
        RasPrecipHdf.validate_data_type_units("cumulative", units_out)

        arr = np.asarray(cumulative_values, dtype=np.float32)
        if arr.ndim != 3:
            raise ValueError(
                f"cumulative_values must be 3-D (n_times, rows, cols), got shape {arr.shape}"
            )
        n_times, n_rows, n_cols = arr.shape
        if n_times < 1 or n_rows < 1 or n_cols < 1:
            raise ValueError(f"cumulative_values has an empty dimension: {arr.shape}")

        stamps = list(pd.to_datetime(list(times)))
        if len(stamps) != n_times:
            raise ValueError(
                f"times has {len(stamps)} entries but cumulative_values has {n_times} rows"
            )
        for i in range(1, n_times):
            if stamps[i] <= stamps[i - 1]:
                raise ValueError("times must be strictly increasing")

        for name, value in (
            ("raster_left", raster_left),
            ("raster_top", raster_top),
            ("cell_size", cell_size),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite, got {value!r}")
        if float(cell_size) <= 0:
            raise ValueError(f"cell_size must be positive, got {cell_size!r}")
        if nodata is not None and not math.isfinite(float(nodata)):
            raise ValueError(f"nodata must be finite or None, got {nodata!r}")

        if projection is None:
            logger.warning(
                "No projection supplied for %s; HEC-RAS will assume the grid is in "
                "the project CRS",
                hdf_path.name,
            )
        else:
            RasPrecipHdf._require_ascii("projection", str(projection))

        # Row-at-a-time checks: no full-size temporaries on large grids.
        previous = np.nan_to_num(arr[0], nan=0.0)
        if np.any(previous != 0):
            logger.warning(
                "First row of the cumulative payload is not zero (max %.6g). HEC-RAS "
                "treats row 0 as the datum, so that amount is never delivered.",
                float(np.max(np.abs(previous))),
            )
        for i in range(1, n_times):
            current = np.nan_to_num(arr[i], nan=0.0)
            if np.any(current - previous < -1e-6):
                logger.warning(
                    "Cumulative payload decreases over time in some cells; HEC-RAS "
                    "will deliver negative precipitation there."
                )
                break
            previous = current

        n_cells = n_rows * n_cols
        values_chunks = RasPrecipHdf.get_values_chunks(n_times, n_cells, itemsize=4)
        vertical_chunks = RasPrecipHdf.get_vertical_chunks(n_times, n_cells)

        if require_met_bc_block:
            text_path = hdf_path.with_suffix("")
            if not text_path.exists():
                raise FileNotFoundError(
                    f"Unsteady flow text file not found beside {hdf_path.name}: "
                    f"{text_path}. Pass require_met_bc_block=False only when the text "
                    f"is managed separately."
                )
            if not RasPrecipHdf._has_met_bc_block(text_path, met_variable):
                raise ValueError(
                    f"{text_path.name} has no 'Met BC={met_variable}|' block. HEC-RAS "
                    f"copies Imported Raster Data forward only for variables present in "
                    f"the text, so this payload would be destroyed on the next save. "
                    f"Configure the variable first (e.g. "
                    f"RasUnsteady.set_gridded_precipitation)."
                )

        if not hdf_path.parent.exists():
            raise FileNotFoundError(f"Folder does not exist: {hdf_path.parent}")

        group_path = _IMPORTED_RASTER_GROUP.format(variable=met_variable)
        existed = hdf_path.exists()

        skipped = False
        if existed and not overwrite:
            with h5py.File(hdf_path, "r") as f:
                skipped = group_path in f

        def _result(**kwargs: Any) -> PrecipRasterImportResult:
            return PrecipRasterImportResult(
                success=True,
                unsteady_hdf_path=hdf_path,
                met_variable=met_variable,
                shape=(n_times, n_cells),
                units=units_out,
                values_chunks=values_chunks,
                vertical_chunks=vertical_chunks,
                elapsed_seconds=time.perf_counter() - started,
                **kwargs,
            )

        if skipped:
            logger.info(
                "Imported Raster Data already present in %s; skipped (overwrite=False)",
                hdf_path.name,
            )
            return _result(skipped=True, dry_run=dry_run)
        if dry_run:
            return _result(dry_run=True)

        flat = np.ascontiguousarray(arr.reshape(n_times, n_cells), dtype=np.float32)
        guid = str(uuid.uuid4())
        time_strings = np.array(
            [t.strftime("%Y-%m-%d %H:%M:%S").encode("ascii") for t in stamps],
            dtype="S19",
        )

        # Creation order follows H5RasterWriter.WriteAccumulatedRaster / SignRaster.
        attributes: list = []
        if nodata is not None:
            attributes.append(("NoData", np.float32(nodata)))
        attributes.extend([
            ("Raster Rows", np.int32(n_rows)),
            ("Raster Cols", np.int32(n_cols)),
            ("Raster Left", np.float64(raster_left)),
            ("Raster Top", np.float64(raster_top)),
            ("Raster Cellsize", np.float64(cell_size)),
            ("Storage Configuration", "Sequential"),
            ("GUID", guid),
            ("Version", "1.0"),
            ("Times", time_strings),
            ("Time Series Data Type", "Amount"),  # exact case; HEC-RAS matches ordinally
            ("Rate Time Units", "Hour"),
            ("Units", units_out),
            ("Data Type", "cumulative"),
        ])
        if projection is not None:
            attributes.append(("Projection", str(projection)))

        with h5py.File(hdf_path, "a") as f:
            if group_path in f:
                del f[group_path]
            group = f.require_group(group_path)
            for name, chunks in (
                ("Values", values_chunks),
                ("Values (Vertical)", vertical_chunks),
            ):
                dataset = group.create_dataset(
                    name,
                    data=flat,
                    dtype="<f4",
                    chunks=chunks,
                    maxshape=(None, None),
                    compression="gzip",
                    compression_opts=1,
                    fillvalue=np.float32(np.nan),
                )
                for attr_name, attr_value in attributes:
                    RasPrecipHdf._write_attr(dataset, attr_name, attr_value)

        logger.debug(
            "Wrote %s Imported Raster Data to %s: %d time steps, %d x %d cells, units=%s",
            met_variable, hdf_path.name, n_times, n_rows, n_cols, units_out,
        )
        return _result(created_hdf=not existed)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _require_positive_dimensions(n_times: int, n_cells: int) -> None:
        if n_cells <= 0:
            raise ValueError(f"n_cells must be positive, got {n_cells}")
        if n_times <= 0:
            raise ValueError(f"n_times must be positive, got {n_times}")

    @staticmethod
    def _require_ascii(name: str, value: str) -> None:
        try:
            value.encode("ascii")
        except UnicodeEncodeError as e:
            raise ValueError(
                f"{name} must be ASCII; HEC-RAS writes attributes with ASCII encoding "
                f"and would replace non-ASCII characters with '?'"
            ) from e

    @staticmethod
    def _write_attr(obj: Any, name: str, value: Any) -> None:
        """Write an attribute the way H5Writer does: fixed-length ASCII strings."""
        import numpy as np

        if isinstance(value, str):
            RasPrecipHdf._require_ascii(name, value)
            encoded = value.encode("ascii")
            obj.attrs.create(name, np.bytes_(encoded), dtype=f"S{max(len(encoded), 1)}")
        else:
            obj.attrs.create(name, value)

    @staticmethod
    def _has_met_bc_block(text_path: Path, met_variable: str) -> bool:
        """True when the ``.u##`` text carries a ``Met BC=<met_variable>|`` line."""
        prefix = f"Met BC={met_variable}|"
        with open(text_path, "r", encoding="utf-8", errors="replace") as f:
            return any(line.startswith(prefix) for line in f)
