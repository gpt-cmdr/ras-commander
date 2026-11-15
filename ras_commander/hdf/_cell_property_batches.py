"""Bounded stored cell-volume rows; values retain the HDF's native units."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from .. import _native_scope
from ..fast_hdf import read_dataset, release_native_sessions
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@contextmanager
def _source_file(hdf_path: Path):
    """Release only this source's native sessions before returning a batch."""
    depth = _native_scope.enter()
    try:
        with h5py.File(hdf_path, "r") as source:
            yield source
    finally:
        try:
            _native_scope.leave(depth)
        finally:
            release_native_sessions(hdf_path)


def _read_batch(
    info: h5py.Dataset, values: h5py.Dataset, start: int, stop: int
) -> pd.DataFrame:
    """Read one source-cell range in the legacy cell/point order."""
    rows = read_dataset(info, (slice(start, stop), slice(None)))
    if rows.ndim != 2 or rows.shape[1] != 2 or values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("Cell volume/elevation tables require two-column datasets")
    ranges = []
    counts = []
    for offset, count in rows:
        # Match the original NumPy slice, including empty ghost-cell ranges,
        # clipping and source integer arithmetic. No values are synthesized.
        first, last, _ = slice(offset, offset + count).indices(values.shape[0])
        length = max(0, last - first)
        ranges.append((first, first + length))
        counts.append(length)
    total = sum(counts)
    if not total:
        # The legacy getter constructs DataFrame([]) for present empty tables.
        return pd.DataFrame()
    elevations = np.empty(total, dtype=np.float64)
    volumes = np.empty(total, dtype=np.float64)
    destination = 0
    i = 0
    while i < len(ranges):
        first, last = ranges[i]
        i += 1
        if first == last:
            continue
        # Coalesce adjacent referenced spans only. Gaps and out-of-order source
        # offsets must not turn a small cell batch into a model-wide read.
        while i < len(ranges) and ranges[i][0] == last:
            last = ranges[i][1]
            i += 1
        block = read_dataset(values, (slice(first, last), slice(None)))
        length = last - first
        elevations[destination : destination + length] = block[:, 0]
        volumes[destination : destination + length] = block[:, 1]
        destination += length
    cell_ids = np.repeat(np.arange(start, stop, dtype=np.int64), counts)
    return pd.DataFrame(
        {"Cell ID": cell_ids, "Elevation": elevations, "Volume": volumes}, copy=False
    )


def _iter_batches(
    hdf_path: Path, mesh_names: Sequence[str], batch_cells: int
) -> Iterator[tuple[str, pd.DataFrame]]:
    """Close HDF and native sessions before yielding each bounded frame."""
    for mesh_name in mesh_names:
        base = f"Geometry/2D Flow Areas/{mesh_name}"
        info_path = f"{base}/Cells Volume Elevation Info"
        values_path = f"{base}/Cells Volume Elevation Values"
        with _source_file(hdf_path) as source:
            missing = info_path not in source or values_path not in source
            count = 0 if missing else source[info_path].shape[0]
        if missing:
            logger.error(
                "Cell volume/elevation tables missing in %s, mesh %r",
                hdf_path,
                mesh_name,
            )
            yield mesh_name, pd.DataFrame(columns=["Cell ID", "Elevation", "Volume"])
            continue
        produced = False
        for start in range(0, count, batch_cells):
            with _source_file(hdf_path) as source:
                frame = _read_batch(
                    source[info_path],
                    source[values_path],
                    start,
                    min(start + batch_cells, count),
                )
            if not frame.empty:
                produced = True
                yield mesh_name, frame
        if not produced:
            yield mesh_name, pd.DataFrame()


def iter_cell_property_batches(
    hdf_path: Path, mesh_names: Sequence[str], batch_cells: int
) -> Iterator[tuple[str, pd.DataFrame]]:
    """Log read failures with their file context and preserve their exception."""
    try:
        yield from _iter_batches(hdf_path, mesh_names, batch_cells)
    except Exception:
        logger.exception("Error iterating cell property tables from %s", hdf_path)
        raise
