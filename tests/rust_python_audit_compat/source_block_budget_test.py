"""A05: observe actual HDF read slabs before float32 narrowing.

Synthetic HDF precision/boundary cases supplement the immutable real RAS
fixture check; their oracle reduces full columns independently of slab size.
"""
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_results


class ObservedDataset:
    """Trace actual h5py reads, without substituting stored values."""
    def __init__(self, dataset):
        self.dataset = dataset
        self.shape, self.ndim, self.dtype = dataset.shape, dataset.ndim, dataset.dtype
        self.reads = []

    def __getitem__(self, selection):
        values = self.dataset[selection]
        self.reads.append((values.shape, values.nbytes))
        return values


def expected(values, offset=None, threshold=None):
    values = values.astype(np.float32)
    if offset is not None:
        values -= offset
        values[np.isfinite(values) & (values < 0)] = 0
    maxima, peaks, counts, exceeds, firsts = [], [], [], [], []
    for col in values.T:
        valid = [(i, float(v)) for i, v in enumerate(col) if np.isfinite(v)]
        best = max((v for _, v in valid), default=np.nan)
        maxima.append(best)
        peaks.append(next((i for i, v in valid if v == best), -1))
        counts.append(len(valid))
        hits = [i for i, v in valid if threshold is not None and v >= np.float32(threshold)]
        exceeds.append(len(hits))
        firsts.append(hits[0] if hits else -1)
    return maxima, peaks, counts, exceeds, firsts


@pytest.mark.parametrize('dtype', ['<f4', '<f8', '>f8'])
@pytest.mark.parametrize('budget', [1, 55, 56, 112, 10000])
@pytest.mark.parametrize('with_offset', [False, True])
def test_actual_stored_slabs_follow_dtype_budget(tmp_path, dtype, budget, with_offset):
    data = (np.arange(63).reshape(9, 7) % 11 - 4).astype(dtype)
    data[0, 0] = data[7, 0] = 50  # first tie across slabs
    data[2, 1], data[3, 2], data[:, 3] = np.nan, np.inf, np.nan
    offset = np.arange(7, dtype=np.float32) if with_offset else None
    path = tmp_path / 'stored.h5'
    with h5py.File(path, 'w') as h:
        h.create_dataset('series', data=data, chunks=(9, 7), compression='gzip')
    with h5py.File(path, 'r') as h:
        observed = ObservedDataset(h['series'])
        got = fast_results.temporal_reduce(observed, offset, threshold=2.0,
                                            backend='python', max_block_bytes=budget)
    bound = max(budget, data.shape[1] * data.dtype.itemsize)
    assert observed.reads and max(size for _, size in observed.reads) <= bound
    want = expected(data, offset, 2.0)
    for array, oracle in zip((got.maximum, got.peak_index, got.finite_count,
                              got.exceed_count, got.first_exceed_index), want):
        np.testing.assert_array_equal(array, oracle)
    assert got.maximum.dtype == np.float32 and got.rows == 9 and got.backend == 'python'


@pytest.mark.parametrize('shape', [(0, 7), (9, 0), (0, 0)])
def test_zero_dimensions_do_not_read(tmp_path, shape):
    with h5py.File(tmp_path / 'empty.h5', 'w') as h:
        observed = ObservedDataset(h.create_dataset('series', shape=shape, dtype='f8'))
        got = fast_results.temporal_reduce(observed, backend='python', max_block_bytes=1)
        assert not observed.reads
        assert got.rows == shape[0] and got.maximum.shape == (shape[1],)
        assert np.isnan(got.maximum).all() and (got.peak_index == -1).all()


@pytest.mark.parametrize('budget', [0, -1, -100])
def test_invalid_budget_rejected_before_read(tmp_path, budget):
    with h5py.File(tmp_path / 'invalid.h5', 'w') as h:
        observed = ObservedDataset(h.create_dataset('series', data=np.ones((4, 7))))
        with pytest.raises(ValueError, match='positive'):
            fast_results.temporal_reduce(observed, backend='python', max_block_bytes=budget)
        assert not observed.reads


def test_real_two_mesh_ras_full_reduction():
    root = os.environ.get('RAS_PY_AUDIT_FIXTURES')
    if not root:
        pytest.skip('RAS_PY_AUDIT_FIXTURES not supplied: real RAS coverage unavailable')
    path = Path(root) / 'BaldEagleDamBrk.p18.hdf'
    with h5py.File(path, 'r') as h:
        for mesh in ['BaldEagleCr', 'Upper 2D Area']:
            ds = h[f'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{mesh}/Water Surface']
            observed = ObservedDataset(ds)
            budget = 128 * 1024
            got = fast_results.temporal_reduce(observed, threshold=500, backend='python', max_block_bytes=budget)
            want = expected(ds[()], threshold=500)
            for array, oracle in zip((got.maximum, got.peak_index, got.finite_count,
                                      got.exceed_count, got.first_exceed_index), want):
                np.testing.assert_array_equal(array, oracle)
            assert max(size for _, size in observed.reads) <= max(budget, ds.shape[1] * ds.dtype.itemsize)
