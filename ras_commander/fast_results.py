"""Optional native temporal reductions of HEC-RAS result time series.

Reduces a ``(time, element)`` HDF dataset to per-element maximum, first peak
row, finite-sample count and optional threshold exceedance in bounded row
blocks. Memory contract: each read block holds at most ``max_block_bytes`` of
stored values (minimum one complete row; float64 blocks also need a half-size
float32 copy). HDF5 decompresses whole storage chunks, so a storage chunk
larger than the budget is resident while it is decompressed; the native
reader's per-file chunk cache (``read_plan["chunk_cache_bytes"]``) retains
decompressed chunks up to its size. Narrowing copies, finite masks, reduction
temporaries and accumulators are additional working memory: the block budget
is not a total process RSS limit. Neither route returns or accumulates the
complete series. Policy follows :mod:`ras_commander.fast_hdf`:
``RAS_COMMANDER_FAST_HDF=0`` selects Python, ``required`` forbids fallback, and
an explicit ``backend`` overrides the environment.

Semantics (identical for both backends):

- Values are reduced as ``float32``; ``float64`` storage is rounded first.
- ``offset`` (for example ``Cells Minimum Elevation``) is subtracted in
  ``float32`` and the difference is clipped below at zero. Without an offset,
  valid negative stored values are kept. Magnitude never implies "dry".
- NaN and +/-infinity, before or after the offset, are missing samples. An
  element without finite samples has maximum NaN, peak index -1 and count 0.
- Ties keep the first row. Indices are row positions, not times.
- ``threshold`` is finite, rounded to ``float32`` and inclusive
  (``value >= threshold``). Counts are samples, not durations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
from typing import Mapping, Optional, Sequence

import h5py
import numpy as np

from .Decorators import log_call
from .LoggingConfig import get_logger
from .fast_hdf import FastHdfError, _mode, _native, _safe_file, _threads, _unsupported

logger = get_logger(__name__)

__all__ = [
    "TemporalReduction", "temporal_reduce", "native_temporal_reduce", "peak_times_ms",
    "cross_plan_maximum",
]

# Matches the reference route's 16 MiB read bound (HdfResultsMesh).
_DEFAULT_BLOCK_BYTES = 16 * 1024 * 1024
_EPOCH = datetime(1970, 1, 1)
_MS = timedelta(milliseconds=1)


@dataclass(frozen=True)
class TemporalReduction:
    """Per-element reduction of a ``(time, element)`` series.

    Engine-backed reductions report a combined ``engine_seconds`` timing.
    Separate read/reduce timings are NaN when that engine cannot measure the
    split; ``read_plan['timing_scope']`` explains the available measurement.
    """

    maximum: np.ndarray
    peak_index: np.ndarray
    finite_count: np.ndarray
    exceed_count: Optional[np.ndarray]
    first_exceed_index: Optional[np.ndarray]
    rows: int
    backend: str
    timings: Mapping[str, float] = field(default_factory=dict)
    read_plan: Mapping[str, object] = field(default_factory=dict)


def _threshold(threshold):
    if threshold is None:
        return None
    value = float(threshold)
    if not np.isfinite(value):
        raise ValueError("threshold must be finite")
    with np.errstate(over="ignore"):  # overflow is rejected just below
        single = np.float32(value)
    if not np.isfinite(single):
        raise ValueError("threshold is outside the float32 range")
    return float(single)


def _offset(dataset, offset):
    if offset is None:
        return None
    values = np.ascontiguousarray(offset, dtype=np.float32)
    if values.ndim != 1 or values.shape[0] != dataset.shape[1]:
        raise ValueError(
            f"offset shape {values.shape} does not match {dataset.shape[1]} elements"
        )
    return values


def _check_shape(dataset):
    if dataset.ndim != 2:
        raise ValueError(
            f"temporal reduction needs a 2-D (time, element) dataset, not {dataset.shape}"
        )


@log_call
def native_temporal_reduce(dataset, offset=None, *, threshold=None, backend="auto",
                           threads=None, max_block_bytes=_DEFAULT_BLOCK_BYTES):
    """Run the native reduction, or return ``None`` where policy permits Python.

    Returns ``None`` in Python mode, or in auto mode when the extension or this
    dataset is unsupported. Rust mode and native failures raise ``FastHdfError``.
    """
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    if module is None:
        return None
    eligible = (
        isinstance(dataset, h5py.Dataset)
        and dataset.shape is not None
        and dataset.ndim == 2
        and dataset.dtype.kind == "f"
        and dataset.dtype.itemsize in {4, 8}
        and _safe_file(dataset)
        and hasattr(module, "temporal_reduce")
    )
    if not eligible:
        if mode == "rust":
            raise FastHdfError(f"Series cannot be reduced natively: {getattr(dataset, 'name', dataset)!r}")
        return None
    threshold = _threshold(threshold)
    offset = _offset(dataset, offset)
    if max_block_bytes <= 0:
        raise ValueError("max_block_bytes must be positive")
    try:
        raw = module.temporal_reduce(
            os.fsdecode(dataset.file.filename), dataset.name, offset=offset,
            threshold=threshold, max_block_bytes=int(max_block_bytes), threads=threads,
        )
    except Exception as exc:
        if mode == "auto" and _unsupported(module, exc):
            logger.debug("Python reduction for %s: %s", dataset.name, exc)
            return None
        raise FastHdfError(f"Native reduction failed for {dataset.name}: {exc}") from exc
    elements = dataset.shape[1]
    expected = {"maximum": np.float32, "peak_index": np.int64, "finite_count": np.uint64}
    if threshold is not None:
        expected.update(exceed_count=np.uint64, first_exceed_index=np.int64)
    for key, dtype in expected.items():
        array = raw.get(key)
        if not isinstance(array, np.ndarray) or array.dtype != dtype or array.shape != (elements,):
            raise FastHdfError(f"Native reduction returned an invalid {key!r} array")
    if int(raw["rows"]) != dataset.shape[0]:
        raise FastHdfError("Native reduction row count disagrees with the dataset")
    timings = {k: float(raw[k]) for k in ("setup_seconds", "read_seconds", "reduce_seconds")}
    read_plan = {k: raw[k] for k in ("block_rows", "blocks", "block_bytes", "max_block_bytes",
                                    "chunk_shape", "storage_chunk_bytes", "chunk_cache_bytes",
                                    "stored_dtype")}
    if "engine_seconds" in raw:
        timings["engine_seconds"] = float(raw["engine_seconds"])
        read_plan["timing_scope"] = raw["timing_scope"]
    return TemporalReduction(
        maximum=raw["maximum"], peak_index=raw["peak_index"],
        finite_count=raw["finite_count"], exceed_count=raw["exceed_count"],
        first_exceed_index=raw["first_exceed_index"], rows=int(raw["rows"]), backend="rust",
        timings=timings, read_plan=read_plan,
    )


def _python_reduce(dataset, offset, threshold, max_block_bytes):
    times, elements = dataset.shape
    maximum = np.full(elements, np.nan, dtype=np.float32)
    peak = np.full(elements, -1, dtype=np.int64)
    count = np.zeros(elements, dtype=np.uint64)
    exceed = first = None
    if threshold is not None:
        exceed = np.zeros(elements, dtype=np.uint64)
        first = np.full(elements, -1, dtype=np.int64)
    columns = np.arange(elements)
    rows = max(1, int(max_block_bytes) // max(1, elements * dataset.dtype.itemsize))
    for start in range(0, times if elements else 0, rows):
        values = np.array(dataset[start:start + rows, :], dtype=np.float32, copy=True)
        if offset is not None:
            np.subtract(values, offset[np.newaxis, :], out=values)
        finite = np.isfinite(values)
        if offset is not None:
            values[finite & (values < 0)] = 0.0
        count += finite.sum(axis=0, dtype=np.uint64)
        # -inf never survives as a finite sample, so argmax finds the first maximum.
        filled = np.where(finite, values, np.float32(-np.inf))
        index = filled.argmax(axis=0)
        block_max = filled[index, columns]
        better = finite.any(axis=0) & (np.isnan(maximum) | (block_max > maximum))
        maximum[better] = block_max[better]
        peak[better] = start + index[better]
        if threshold is not None:
            hit = finite & (values >= np.float32(threshold))
            exceed += hit.sum(axis=0, dtype=np.uint64)
            new = hit.any(axis=0) & (first < 0)
            first[new] = start + hit.argmax(axis=0)[new]
    return TemporalReduction(maximum, peak, count, exceed, first, times, "python")


@log_call
def temporal_reduce(dataset, offset=None, *, threshold=None, backend="auto", threads=None,
                    max_block_bytes=_DEFAULT_BLOCK_BYTES) -> TemporalReduction:
    """Reduce a ``(time, element)`` dataset with the module semantics."""
    _check_shape(dataset)
    result = native_temporal_reduce(dataset, offset, threshold=threshold, backend=backend,
                                    threads=threads, max_block_bytes=max_block_bytes)
    if result is not None:
        return result
    if max_block_bytes <= 0:
        raise ValueError("max_block_bytes must be positive")
    return _python_reduce(dataset, _offset(dataset, offset), _threshold(threshold), max_block_bytes)


def _epoch_ms(value) -> int:
    if not isinstance(value, datetime):
        raise TypeError("timestamps must be datetime objects")
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    # Integer timedelta arithmetic: no nanosecond range limit (year 3000 is valid).
    return (value - _EPOCH) // _MS


@log_call
def peak_times_ms(timestamps: Sequence[datetime], index: np.ndarray) -> np.ma.MaskedArray:
    """Map row indices to epoch milliseconds; ``-1`` indices are masked.

    Naive timestamps are treated as the model's wall-clock time (no timezone
    is inferred). Duplicate or irregular timestamps map row-for-row.
    """
    index = np.asarray(index)
    if index.dtype.kind not in "iu":
        raise TypeError("index must be an integer array")
    if index.size and (index.max() >= len(timestamps) or index.min() < -1):
        raise IndexError("peak index outside the timestamp sequence")
    times = np.fromiter((_epoch_ms(t) for t in timestamps), dtype=np.int64, count=len(timestamps))
    valid = index >= 0
    values = np.zeros(index.shape, dtype=np.int64)
    values[valid] = times[index[valid]]
    return np.ma.MaskedArray(values, mask=~valid)


@log_call
def cross_plan_maximum(maxima: Sequence[np.ndarray]):
    """Envelope of per-element maxima from several plans of one model.

    Arrays must be 1-D ``float32`` with identical length; the caller asserts
    element identity (for example identical mesh geometry) before combining.
    NaN is ignored, an element missing in every plan stays NaN with plan index
    -1, and ties keep the first plan. Returns ``(envelope, plan_index)``.
    """
    arrays = [np.asarray(m) for m in maxima]
    if not arrays:
        raise ValueError("at least one plan is required")
    shape = arrays[0].shape
    for array in arrays:
        if array.ndim != 1 or array.shape != shape or array.dtype != np.float32:
            raise ValueError("plan maxima must be aligned 1-D float32 arrays")
    values = np.stack(arrays)
    finite = ~np.isnan(values)
    filled = np.where(finite, values, np.float32(-np.inf))
    plan = filled.argmax(axis=0)
    has = finite.any(axis=0)
    envelope = np.where(has, filled[plan, np.arange(shape[0])], np.float32(np.nan))
    return envelope.astype(np.float32), np.where(has, plan, -1).astype(np.int64)
