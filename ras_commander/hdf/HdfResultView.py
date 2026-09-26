"""Lazy, source-backed views over large HEC-RAS HDF result datasets."""

from __future__ import annotations

import operator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Optional, SupportsIndex, Union

import h5py
import numpy as np
import pandas as pd
import xarray as xr
from numpy.typing import DTypeLike

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils

Selection = Optional[Union[SupportsIndex, slice]]

logger = get_logger(__name__)


def _normalized_slice(selection: Selection, size: int, label: str) -> slice:
    """Normalize an integer or forward slice while preserving the dimension."""
    if selection is None:
        return slice(0, size, 1)
    if isinstance(selection, (bool, np.bool_)):
        raise TypeError(f"{label} selection must be an integer or slice")
    if not isinstance(selection, slice):
        try:
            index = operator.index(selection)
        except TypeError as exc:
            raise TypeError(
                f"{label} selection must be an integer or slice"
            ) from exc
        index = index + size if index < 0 else index
        if index < 0 or index >= size:
            raise IndexError(f"{label} index {selection} is out of range for {size}")
        return slice(index, index + 1, 1)
    start, stop, step = selection.indices(size)
    if step <= 0:
        raise ValueError(f"{label} selection must use a positive slice step")
    return slice(start, stop, step)


def _slice_size(selection: slice) -> int:
    """Return the number of indexes represented by a normalized slice."""
    return len(range(selection.start, selection.stop, selection.step))


@dataclass(frozen=True)
class HdfResultView:
    """Serializable lazy view that reopens its HDF source for each operation.

    The view stores dataset metadata and selections but no open HDF handle and
    no result values. This makes file ownership explicit: each materialization,
    reduction, or batch iterator opens the source read-only and closes it when
    that operation completes. A size/mtime fingerprint detects ordinary source
    replacement and modification before or during an operation.
    """

    source_path: Path
    dataset_path: str
    time_path: str
    mesh_name: str
    variable: str
    units: str
    id_dim: str
    source_shape: tuple[int, ...]
    source_dtype: str
    source_size: int
    source_mtime_ns: int
    time_selection: Selection = None
    spatial_selection: Selection = None
    truncate: bool = False

    def __post_init__(self) -> None:
        """Normalize the persisted path and validate supported source rank."""
        object.__setattr__(self, "source_path", Path(self.source_path).resolve())
        if len(self.source_shape) not in (1, 2):
            raise ValueError(
                "HdfResultView supports one- or two-dimensional result datasets"
            )

    @property
    def shape(self) -> tuple[int, ...]:
        """Return the shape that materialization will produce.

        A ``truncate=True`` view performs the same bounded active-window scan
        used by batch iteration and reduction so this property remains
        consistent with ``to_numpy()`` and ``to_xarray()``.
        """
        time_slice, spatial_slice = self._selections()
        if self.truncate and _slice_size(time_slice):
            with self._open_source() as hdf_file:
                time_slice, spatial_slice = self._effective_selections(
                    hdf_file[self.dataset_path]
                )
            self._validate_source_fingerprint()
        result = (_slice_size(time_slice),)
        if spatial_slice is not None:
            result += (_slice_size(spatial_slice),)
        return result

    @property
    def dtype(self) -> np.dtype:
        """Return the source NumPy dtype."""
        return np.dtype(self.source_dtype)

    @log_call
    def select(
        self,
        *,
        time: Selection = None,
        spatial: Selection = None,
    ) -> "HdfResultView":
        """Return a new view with source-coordinate time/spatial selections.

        Integer selections preserve their dimension as a length-one slice.
        Selections use source indexes rather than indexes relative to a prior
        selection, which keeps serialized views unambiguous. Passing ``None``
        preserves an existing selection; use a full ``slice(None)`` to reset
        that dimension.

        Args:
            time: Python/NumPy integer or positive-step slice in source time
                coordinates.
            spatial: Python/NumPy integer or positive-step slice in source
                cell/face coordinates.

        Returns:
            A new immutable view over the same fingerprinted source.

        Raises:
            TypeError: If a selection is not integer-like or a slice.
            IndexError: If an integer selection is outside the source extent.
            ValueError: If a slice step is nonpositive or a spatial selection
                is supplied for a one-dimensional dataset.
        """
        time_value = self.time_selection if time is None else time
        spatial_value = self.spatial_selection if spatial is None else spatial
        _normalized_slice(time_value, self.source_shape[0], "time")
        if len(self.source_shape) == 1:
            if spatial_value is not None:
                raise ValueError("spatial selection requires a 2D result dataset")
        else:
            _normalized_slice(spatial_value, self.source_shape[1], "spatial")
        return replace(
            self,
            time_selection=time_value,
            spatial_selection=spatial_value,
        )

    @log_call
    def to_numpy(self, dtype: Optional[DTypeLike] = None) -> np.ndarray:
        """Materialize only the selected values as a NumPy array.

        The eager path reads the selected HDF slab once. When truncation is
        enabled, leading and trailing zero-only rows are trimmed in memory;
        an all-zero selection retains its full time extent for compatibility.

        Args:
            dtype: Optional NumPy-compatible output dtype.

        Returns:
            Selected result values with a stable time dimension.

        Raises:
            FileNotFoundError: If the source path no longer exists.
            KeyError: If the source dataset was removed.
            RuntimeError: If the source fingerprint, shape, or dtype changed.
        """
        with self._open_source() as hdf_file:
            dataset = hdf_file[self.dataset_path]
            time_slice, spatial_slice = self._selections()
            key = (
                time_slice
                if spatial_slice is None
                else (time_slice, spatial_slice)
            )
            values = np.asarray(dataset[key])
            if self.truncate:
                values, time_slice = self._trim_materialized(values, time_slice)
        self._validate_source_fingerprint()
        if dtype is not None:
            values = values.astype(dtype, copy=False)
        return values

    @log_call
    def to_xarray(self, dtype: Optional[DTypeLike] = None) -> xr.DataArray:
        """Materialize the selection as a labeled xarray DataArray.

        Result values are read once. Truncation is evaluated over the selected
        spatial subset, so a subset can have a narrower active time window than
        the complete mesh.

        Args:
            dtype: Optional NumPy-compatible output dtype.

        Returns:
            DataArray labeled by timestamps and source cell/face identifiers.

        Raises:
            FileNotFoundError: If the source path no longer exists.
            KeyError: If a required source dataset was removed.
            RuntimeError: If the source fingerprint, shape, or dtype changed.
        """
        with self._open_source() as hdf_file:
            dataset = hdf_file[self.dataset_path]
            time_slice, spatial_slice = self._selections()
            key = (
                time_slice
                if spatial_slice is None
                else (time_slice, spatial_slice)
            )
            values = np.asarray(dataset[key])
            if self.truncate:
                values, time_slice = self._trim_materialized(values, time_slice)
            result = self._build_dataarray(
                hdf_file,
                values,
                time_slice,
                spatial_slice,
                dtype=dtype,
            )
        self._validate_source_fingerprint()
        return result

    @log_call
    def to_pandas(
        self,
        dtype: Optional[DTypeLike] = None,
    ) -> Union[pd.Series, pd.DataFrame]:
        """Materialize the selection using xarray's pandas representation.

        Args:
            dtype: Optional NumPy-compatible output dtype.

        Returns:
            Series for one-dimensional sources or DataFrame for two-dimensional
            sources.

        Raises:
            FileNotFoundError: If the source path no longer exists.
            RuntimeError: If the source changed after view creation.
        """
        return self.to_xarray(dtype=dtype).to_pandas()

    @log_call
    def to_arrow(self, dtype: Optional[DTypeLike] = None) -> Any:
        """Materialize the selection as an optional PyArrow table.

        Args:
            dtype: Optional NumPy-compatible output dtype.

        Returns:
            A PyArrow Table in long form, with time, optional spatial
            identifier, and value columns. ``Any`` is used as the static return
            annotation so importing ras-commander does not require PyArrow.

        Raises:
            ImportError: If PyArrow is not installed.
            FileNotFoundError: If the source path no longer exists.
            RuntimeError: If the source changed after view creation.
        """
        try:
            import pyarrow as pa
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "HdfResultView.to_arrow() requires the optional 'pyarrow' package"
            ) from exc

        frame = self.to_xarray(dtype=dtype).to_dataframe(
            name=self.variable
        ).reset_index()
        return pa.Table.from_pandas(frame, preserve_index=False)

    @log_call
    def iter_batches(
        self,
        *,
        batch_size: Optional[int] = None,
        max_chunk_bytes: int = 16 * 1024 * 1024,
        dtype: Optional[DTypeLike] = None,
    ) -> Iterator[xr.DataArray]:
        """Return a generator of time-major batches from one HDF handle.

        Args:
            batch_size: Optional explicit number of selected timesteps per
                batch.
            max_chunk_bytes: Target value bytes per batch when ``batch_size``
                is omitted.
            dtype: Optional NumPy-compatible output dtype used in byte sizing
                and conversion.

        Returns:
            Generator yielding labeled xarray DataArray batches. The generator
            logs and validates completion when exhausted or closed.

        Raises:
            ValueError: If a batch limit is nonpositive.
            FileNotFoundError: If the source path no longer exists.
            RuntimeError: If the source changes before or during consumption.
        """
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_chunk_bytes <= 0:
            raise ValueError("max_chunk_bytes must be positive")

        return self._iter_batches_generator(
            batch_size=batch_size,
            max_chunk_bytes=max_chunk_bytes,
            dtype=dtype,
        )

    def _iter_batches_generator(
        self,
        *,
        batch_size: Optional[int],
        max_chunk_bytes: int,
        dtype: Optional[DTypeLike],
    ) -> Iterator[xr.DataArray]:
        """Own the read handle and completion log while batches are consumed."""
        logger.debug("Starting iter_batches consumption")

        try:
            with self._open_source() as hdf_file:
                dataset = hdf_file[self.dataset_path]
                time_slice, spatial_slice = self._effective_selections(dataset)
                indexes = range(
                    time_slice.start,
                    time_slice.stop,
                    time_slice.step,
                )
                spatial_count = (
                    1
                    if spatial_slice is None
                    else max(1, _slice_size(spatial_slice))
                )
                target_dtype = np.dtype(dtype or dataset.dtype)
                row_bytes = max(1, spatial_count * target_dtype.itemsize)
                rows = batch_size or max(1, max_chunk_bytes // row_bytes)
                selected_count = len(indexes)

                for offset in range(0, selected_count, rows):
                    batch_count = min(rows, selected_count - offset)
                    batch_start = time_slice.start + offset * time_slice.step
                    batch_stop = batch_start + batch_count * time_slice.step
                    batch_time = slice(
                        batch_start,
                        batch_stop,
                        time_slice.step,
                    )
                    yield self._read_dataarray(
                        hdf_file,
                        dataset,
                        batch_time,
                        spatial_slice,
                        dtype=dtype,
                    )
        finally:
            self._validate_source_fingerprint()
            logger.debug("Finished iter_batches consumption")

    @log_call
    def reduce(
        self,
        operation: str,
        *,
        max_chunk_bytes: int = 16 * 1024 * 1024,
        dtype: Optional[DTypeLike] = None,
    ) -> xr.DataArray:
        """Reduce the selected time axis with bounded memory.

        Supported operations are ``max``, ``min``, ``mean``, and ``argmax``.
        NaN and infinite samples are ignored. ``argmax`` returns source time
        indexes and uses ``-1`` for a spatial element with no finite samples.
        An explicit ``dtype`` must be floating point so NaN/infinite filtering
        cannot be destroyed by a pre-reduction integer cast.

        Args:
            operation: One of ``max``, ``min``, ``mean``, or ``argmax``.
            max_chunk_bytes: Maximum target value bytes per source batch.
            dtype: Optional floating-point computation/output dtype.

        Returns:
            DataArray over the selected spatial dimension, or a scalar
            DataArray for a one-dimensional source. Argmax values are source
            time indexes and use ``-1`` when no finite sample exists.

        Raises:
            ValueError: If the operation or chunk target is invalid.
            TypeError: If the source is nonnumeric or ``dtype`` is not floating
                point.
            FileNotFoundError: If the source path no longer exists.
            RuntimeError: If the source changes after view creation.
        """
        operation = str(operation).lower()
        if operation not in {"max", "min", "mean", "argmax"}:
            raise ValueError("operation must be max, min, mean, or argmax")
        if max_chunk_bytes <= 0:
            raise ValueError("max_chunk_bytes must be positive")

        with self._open_source() as hdf_file:
            dataset = hdf_file[self.dataset_path]
            time_slice, spatial_slice = self._effective_selections(dataset)
            if dataset.ndim == 1:
                spatial_slice = None
                spatial_count = 1
            else:
                spatial_count = _slice_size(spatial_slice)

            dataset_dtype = np.dtype(dataset.dtype)
            if not np.issubdtype(dataset_dtype, np.number):
                raise TypeError("bounded reductions require a numeric dataset")
            requested_dtype = np.dtype(dtype) if dtype is not None else None
            if requested_dtype is not None and not np.issubdtype(
                requested_dtype,
                np.floating,
            ):
                raise TypeError("reduction dtype must be a floating-point dtype")
            source_dtype = requested_dtype or dataset_dtype
            reduction_dtype = (
                source_dtype
                if np.issubdtype(source_dtype, np.floating)
                else np.dtype("float64")
            )

            if operation == "argmax":
                result = np.full(spatial_count, -1, dtype=np.int64)
                best = np.full(spatial_count, -np.inf, dtype=np.float64)
            elif operation == "min":
                result = np.full(spatial_count, np.nan, dtype=reduction_dtype)
            elif operation == "mean":
                totals = np.zeros(spatial_count, dtype=np.float64)
                counts = np.zeros(spatial_count, dtype=np.int64)
                result = None
            else:
                result = np.full(spatial_count, np.nan, dtype=reduction_dtype)

            for batch in self._iter_numpy_batches(
                dataset,
                time_slice,
                spatial_slice,
                max_chunk_bytes=max_chunk_bytes,
                dtype=source_dtype,
            ):
                values, source_indexes = batch
                if values.ndim == 1:
                    values = values[:, np.newaxis]
                finite = np.isfinite(values)

                if operation == "max":
                    if np.issubdtype(values.dtype, np.floating):
                        values[~finite] = np.nan
                    np.fmax(result, np.fmax.reduce(values, axis=0), out=result)
                elif operation == "min":
                    if np.issubdtype(values.dtype, np.floating):
                        values[~finite] = np.nan
                    np.fmin(result, np.fmin.reduce(values, axis=0), out=result)
                elif operation == "mean":
                    totals += np.sum(
                        values,
                        axis=0,
                        where=finite,
                        dtype=np.float64,
                    )
                    counts += finite.sum(axis=0)
                else:
                    if np.issubdtype(values.dtype, np.floating):
                        values[~finite] = -np.inf
                    local_rows = np.argmax(values, axis=0)
                    local_values = values[
                        local_rows,
                        np.arange(spatial_count),
                    ]
                    update = local_values > best
                    best[update] = local_values[update]
                    result[update] = source_indexes[local_rows[update]]

            if operation == "mean":
                reduced = np.full(spatial_count, np.nan, dtype=np.float64)
                np.divide(totals, counts, out=reduced, where=counts > 0)
                result = reduced.astype(reduction_dtype, copy=False)

        self._validate_source_fingerprint()

        if len(self.source_shape) == 1:
            dims = ()
            coords = None
            data = result[0]
        else:
            dims = (self.id_dim,)
            spatial_indexes = np.arange(self.source_shape[1])[spatial_slice]
            coords = {self.id_dim: spatial_indexes}
            data = result
        return xr.DataArray(
            data,
            dims=dims,
            coords=coords,
            name=f"{operation}_{self.variable}",
            attrs={
                "units": "source time index" if operation == "argmax" else self.units,
                "mesh_name": self.mesh_name,
                "variable": self.variable,
                "reduction": operation,
            },
        )

    def _selections(self) -> tuple[slice, Optional[slice]]:
        time_slice = _normalized_slice(
            self.time_selection,
            self.source_shape[0],
            "time",
        )
        spatial_slice = None
        if len(self.source_shape) == 2:
            spatial_slice = _normalized_slice(
                self.spatial_selection,
                self.source_shape[1],
                "spatial",
            )
        return time_slice, spatial_slice

    def _effective_selections(self, dataset) -> tuple[slice, Optional[slice]]:
        time_slice, spatial_slice = self._selections()
        if not self.truncate or _slice_size(time_slice) == 0:
            return time_slice, spatial_slice

        first = None
        last = None
        for values, source_indexes in self._iter_numpy_batches(
            dataset,
            time_slice,
            spatial_slice,
            max_chunk_bytes=16 * 1024 * 1024,
            dtype=None,
        ):
            active = (
                values != 0
                if values.ndim == 1
                else np.any(values != 0, axis=1)
            )
            positions = np.flatnonzero(active)
            if len(positions):
                batch_first = int(source_indexes[positions[0]])
                batch_last = int(source_indexes[positions[-1]])
                first = batch_first if first is None else min(first, batch_first)
                last = batch_last if last is None else max(last, batch_last)
        if first is None:
            return time_slice, spatial_slice
        return slice(first, last + time_slice.step, time_slice.step), spatial_slice

    @staticmethod
    def _trim_materialized(
        values: np.ndarray,
        time_slice: slice,
    ) -> tuple[np.ndarray, slice]:
        """Trim active rows from one eager read while retaining all-zero data."""
        active = (
            values != 0
            if values.ndim == 1
            else np.any(values != 0, axis=1)
        )
        positions = np.flatnonzero(active)
        if not len(positions):
            return values, time_slice
        first_position = int(positions[0])
        last_position = int(positions[-1])
        trimmed = values[first_position:last_position + 1]
        start = time_slice.start + first_position * time_slice.step
        stop = time_slice.start + (last_position + 1) * time_slice.step
        return trimmed, slice(start, stop, time_slice.step)

    def _iter_numpy_batches(
        self,
        dataset,
        time_slice: slice,
        spatial_slice: Optional[slice],
        *,
        max_chunk_bytes: int,
        dtype,
    ):
        spatial_count = (
            1 if spatial_slice is None else max(1, _slice_size(spatial_slice))
        )
        target_dtype = np.dtype(dtype or dataset.dtype)
        row_bytes = max(1, spatial_count * target_dtype.itemsize)
        rows = max(1, max_chunk_bytes // row_bytes)
        indexes = range(time_slice.start, time_slice.stop, time_slice.step)
        selected_count = len(indexes)
        for offset in range(0, selected_count, rows):
            batch_count = min(rows, selected_count - offset)
            start = time_slice.start + offset * time_slice.step
            stop = start + batch_count * time_slice.step
            batch_slice = slice(start, stop, time_slice.step)
            key = batch_slice if spatial_slice is None else (batch_slice, spatial_slice)
            values = np.asarray(dataset[key], dtype=target_dtype)
            source_indexes = np.arange(start, stop, time_slice.step, dtype=np.int64)
            yield values, source_indexes

    def _read_dataarray(
        self,
        hdf_file,
        dataset,
        time_slice: slice,
        spatial_slice: Optional[slice],
        *,
        dtype,
    ) -> xr.DataArray:
        key = time_slice if spatial_slice is None else (time_slice, spatial_slice)
        values = np.asarray(dataset[key])
        return self._build_dataarray(
            hdf_file,
            values,
            time_slice,
            spatial_slice,
            dtype=dtype,
        )

    def _build_dataarray(
        self,
        hdf_file,
        values: np.ndarray,
        time_slice: slice,
        spatial_slice: Optional[slice],
        *,
        dtype: Optional[DTypeLike],
    ) -> xr.DataArray:
        """Build the established labeled result schema from materialized values."""
        if dtype is not None:
            values = values.astype(dtype, copy=False)
        raw_times = np.asarray(hdf_file[self.time_path][time_slice])
        start_time = HdfBase.get_simulation_start_time(hdf_file)
        times = HdfUtils.convert_timesteps_to_datetimes(raw_times, start_time)
        dims = ["time"]
        coords = {"time": times}
        if spatial_slice is not None:
            dims.append(self.id_dim)
            coords[self.id_dim] = np.arange(self.source_shape[1])[spatial_slice]
        return xr.DataArray(
            values,
            dims=dims,
            coords=coords,
            attrs={
                "units": self.units,
                "mesh_name": self.mesh_name,
                "variable": self.variable,
            },
        )

    def _open_source(self):
        self._validate_source_fingerprint()
        hdf_file = h5py.File(self.source_path, "r")
        if self.dataset_path not in hdf_file:
            hdf_file.close()
            raise KeyError(f"Dataset no longer exists: {self.dataset_path}")
        if tuple(hdf_file[self.dataset_path].shape) != self.source_shape:
            hdf_file.close()
            raise RuntimeError("HDF result dataset shape changed after view creation")
        if hdf_file[self.dataset_path].dtype.str != self.source_dtype:
            hdf_file.close()
            raise RuntimeError("HDF result dataset dtype changed after view creation")
        return hdf_file

    def _validate_source_fingerprint(self) -> None:
        """Fail if the source path, size, or modification time changed."""
        if not self.source_path.is_file():
            raise FileNotFoundError(
                f"HDF result source no longer exists: {self.source_path}"
            )
        stat = self.source_path.stat()
        if (
            stat.st_size != self.source_size
            or stat.st_mtime_ns != self.source_mtime_ns
        ):
            raise RuntimeError(
                "HDF result source changed after this view was created; "
                "create a new view"
            )
