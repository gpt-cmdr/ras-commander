"""Binding-boundary regressions; existing real-model suites remain the domain oracle."""
import gc
from pathlib import Path
import tomllib

import h5py
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
DEP = tomllib.loads((ROOT / "rust/fast-hdf/Cargo.toml").read_text())["dependencies"]["ras-commander-rust"]
PIN = DEP["rev"]


def test_source_delegation_and_exact_git_pin():
    cargo = tomllib.loads((ROOT / 'rust/fast-hdf/Cargo.toml').read_text())
    dep = cargo['dependencies']['ras-commander-rust']
    assert dep['rev'] == PIN and dep['default-features'] is False
    assert dep['features'] == ['catalog', 'hdf', 'mesh', 'results']
    assert 'path' not in dep and 'hdf5-reader' not in cargo['dependencies']
    for file in ['reader.rs', 'mesh.rs', 'analysis/bindings.rs']:
        source = (ROOT / 'rust/fast-hdf/src' / file).read_text()
        assert 'ras_commander_rust' in source
        assert 'hdf5_reader' not in source
    assert 'struct Accumulator' not in (ROOT / 'rust/fast-hdf/src/analysis/mod.rs').read_text()
    assert 'validate_ring_geometry' in (ROOT / 'rust/fast-hdf/src/tiles.rs').read_text()


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    assert module.ENGINE_COMMIT == PIN
    assert tuple(module.ENGINE_FEATURES) == ('catalog', 'hdf', 'mesh', 'results')
    assert module.API_VERSION == 9
    assert module.TEXT_API_VERSION == 1
    return module


@pytest.mark.parametrize('dtype', ['i1','i2','i4','i8','u1','u2','u4','u8','f4','f8'])
def test_owned_native_numeric_buffers_and_huge_stride(native, tmp_path, dtype):
    path = tmp_path / 'numeric.h5'
    expected = np.arange(20, dtype=dtype).reshape(4, 5)
    with h5py.File(path, 'w') as f:
        f['values'] = expected
    for threads in [1, 4]:
        value = native.read_numeric(str(path), 'values', threads=threads)
        np.testing.assert_array_equal(value, expected)
        assert value.dtype == expected.dtype
        gc.collect()  # session has already been dropped by the binding
        np.testing.assert_array_equal(value, expected)
        selected = native.read_numeric(str(path), 'values', [(1,4,2**64-1),(0,5,2)], threads=threads)
        np.testing.assert_array_equal(selected, expected[1:2,::2])
        empty = native.read_numeric(str(path), 'values', [(1,1,2**64-1),(0,5,1)], threads=threads)
        assert empty.shape == (0,5)
    cap = native.numeric_capability(str(path), 'values')
    assert cap['schema_version'] == 1 and cap['supported']
    assert cap['element_size'] == expected.itemsize
    assert cap['type_class'] == ('float' if dtype[0] == 'f' else 'integer')
    assert cap['bit_precision'] == expected.itemsize * 8


def test_temporal_engine_budget_and_unavailable_split_are_explicit(native, tmp_path):
    path = tmp_path / 'series.h5'
    expected = np.arange(60, dtype='f8').reshape(12,5)
    with h5py.File(path, 'w') as f:
        f.create_dataset('values', data=expected, chunks=(3,5))
    for threads in [1,4]:
        result = native.temporal_reduce(str(path), 'values', max_block_bytes=160, threads=threads)
        np.testing.assert_array_equal(result['maximum'], expected.astype('f4').max(axis=0))
        assert result['block_rows'] == 3 and result['blocks'] == 4
        assert result['block_bytes'] == 120 and result['stored_dtype'] == 'float64'
        assert np.isnan(result['read_seconds']) and np.isnan(result['reduce_seconds'])
        assert result['engine_seconds'] >= 0
        assert result['timing_scope'] == 'engine read+reduce combined; split unavailable'


def test_engine_error_categories_and_thread_bounds(native, tmp_path):
    path = tmp_path / 'errors.h5'
    with h5py.File(path, 'w') as f:
        f['values'] = np.ones((2,3), dtype='f4')
        f['strings'] = np.array([b'ab'])
    with pytest.raises(KeyError):
        native.read_numeric(str(path), 'missing')
    with pytest.raises(native.UnsupportedError):
        native.read_numeric(str(path), 'strings')
    with pytest.raises(ValueError):
        native.read_numeric(str(path), 'values', [(0,2,0),(0,3,1)])
    for threads in [0,1025]:
        with pytest.raises(ValueError, match='between 1 and 1024'):
            native.read_numeric(str(path), 'values', threads=threads)

def test_public_temporal_timing_metadata_is_honest(native, tmp_path):
    from ras_commander.fast_results import temporal_reduce
    path = tmp_path / 'public.h5'
    expected = np.arange(30, dtype='f8').reshape(6,5)
    with h5py.File(path, 'w') as f:
        f['values'] = expected
    with h5py.File(path, 'r') as f:
        result = temporal_reduce(f['values'], backend='rust', threads=1, max_block_bytes=80)
    np.testing.assert_array_equal(result.maximum, expected.astype('f4').max(axis=0))
    assert np.isfinite(result.timings['setup_seconds'])
    assert np.isfinite(result.timings['engine_seconds'])
    assert np.isnan(result.timings['read_seconds']) and np.isnan(result.timings['reduce_seconds'])
    assert result.read_plan['timing_scope'] == 'engine read+reduce combined; split unavailable'
