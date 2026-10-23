"""Public slicing keeps h5py semantics while direct native ranges stay strict."""
import hashlib
import json
import os
from pathlib import Path
import shutil

import h5py
import numpy as np
import pytest

DATASET = ('Results/Unsteady/Output/Output Blocks/Base Output/'
           'Unsteady Time Series/2D Flow Areas/default geometry/Water Surface')


@pytest.fixture(scope='module')
def glaise_copy(tmp_path_factory):
    manifest = os.environ.get('RAS_FIM_WAVE1_FIXTURES')
    if not manifest:
        pytest.skip('Set RAS_FIM_WAVE1_FIXTURES for the real Glaise slice oracle')
    fixture = next(f for f in json.loads(Path(manifest).read_text())
                   if Path(f['path']).name == '1101001306.p01.hdf')
    path = tmp_path_factory.mktemp('glaise-slices') / '1101001306.p01.hdf'
    shutil.copy2(fixture['path'], path)
    with path.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == fixture['sha256']
    yield path
    from ras_commander.fast_hdf import close_sessions
    close_sessions(path)
    with path.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == fixture['sha256']


SELECTIONS = [
    pytest.param((slice(0, 24), slice(0, 40)), id='stop24-clips-to21'),
    pytest.param((slice(0, 1000), slice(0, 40)), id='large-stop'),
    pytest.param((slice(-7, 24), slice(0, 40)), id='negative-start'),
    pytest.param((slice(-1000, -1, 2), slice(-30, -1, 3)), id='negative-bounds-and-steps'),
    pytest.param((slice(0, 24, 3), slice(0, 40, 2)), id='positive-steps'),
    pytest.param((slice(100, 200), slice(0, 40)), id='start-beyond-end-empty'),
    pytest.param((slice(15, 3), slice(0, 40)), id='backward-bounds-positive-step-empty'),
    pytest.param((slice(0, 24), slice(-10000000, -586900)), id='clipped-negative-columns'),
    pytest.param((Ellipsis, slice(-20, None, 2)), id='ellipsis-negative-bound'),
    pytest.param((-1, -1), id='negative-integer-scalar'),
]


@pytest.mark.parametrize('backend', ['auto', 'rust'])
@pytest.mark.parametrize('selection', SELECTIONS)
def test_public_basic_slices_match_h5py(glaise_copy, backend, selection, monkeypatch):
    from ras_commander.fast_hdf import read_dataset
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF', 'auto')
    with h5py.File(glaise_copy, 'r') as f:
        ds = f[DATASET]
        assert ds.shape == (21, 586935)
        expected = ds[selection]
        actual = read_dataset(ds, selection, backend=backend)
        assert type(actual) is type(expected)
        a, b = np.asarray(actual), np.asarray(expected)
        assert a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def test_direct_native_range_stays_strict(glaise_copy):
    import ras_commander_fast_hdf as native
    with native.HdfSession(glaise_copy) as session:
        with pytest.raises(ValueError, match='invalid mesh result row range'):
            session.read_mesh_series('default geometry', 'Water Surface', (0, 24, 1),
                                     np.array([0, 7, 11], dtype='u8'))


def test_auto_fancy_cells_use_h5py_fallback(glaise_copy, monkeypatch):
    from ras_commander.fast_hdf import FastHdfError, read_dataset
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF', 'auto')
    selection = (slice(0, 24), np.array([0, 7, 11]))
    with h5py.File(glaise_copy, 'r') as f:
        ds = f[DATASET]
        expected = ds[selection]
        actual = read_dataset(ds, selection, backend='auto')
        assert actual.dtype == expected.dtype and actual.shape == expected.shape
        assert actual.tobytes() == expected.tobytes()
        # Required-native mode exposes unsupported Python advanced indexing.
        with pytest.raises(FastHdfError, match='only integers and slices'):
            read_dataset(ds, selection, backend='rust')


def test_h5py_rejects_negative_step(glaise_copy, monkeypatch):
    from ras_commander.fast_hdf import read_dataset
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF', 'auto')
    selection = (slice(None, None, -1), slice(0, 40))
    with h5py.File(glaise_copy, 'r') as f:
        with pytest.raises(ValueError):
            f[DATASET][selection]
        with pytest.raises(ValueError):
            read_dataset(f[DATASET], selection, backend='auto')
