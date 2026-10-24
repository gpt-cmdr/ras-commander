"""Schema checks for the reader; real engine qualification lives in the QA run."""
import h5py
import numpy as np
import pytest
import hashlib
from ras_commander import HdfPlan


def test_preserves_raw_arrays_and_metadata(tmp_path):
    path = tmp_path / 'rain.p01.hdf'
    values = np.array([[.2, .4], [.5, .8]], dtype='float32')
    times = np.array([1., 2.], dtype='float64')
    with h5py.File(path, 'w') as hdf:
        group = hdf.create_group('Event Conditions/Meteorology/Precipitation')
        group.attrs['Units'] = np.bytes_('mm')
        group.attrs['Literal'] = np.bytes_('True')
        group.create_dataset('Values', data=values)
        group.create_dataset('Timestamp', data=times)
    result = HdfPlan.get_plan_met_precip_values(path)
    np.testing.assert_array_equal(result['values'], values)
    np.testing.assert_array_equal(result['timestamps'], times)
    assert result['attributes']['Units'] == 'mm'
    assert result['attributes']['Literal'] == 'True'
    np.testing.assert_array_equal(HdfPlan.get_plan_met_precip_values(str(path))['values'], values)


def test_imported_only_payload_is_not_solver_data(tmp_path):
    path = tmp_path / 'rain.p01.hdf'
    with h5py.File(path, 'w') as hdf:
        hdf.create_group('Event Conditions/Meteorology/Precipitation/Imported Raster Data')
    with pytest.raises(KeyError, match='Materialized precipitation'):
        HdfPlan.get_plan_met_precip_values(path)


def test_mismatched_time_axis_rejected(tmp_path):
    path = tmp_path / 'rain.p01.hdf'
    with h5py.File(path, 'w') as hdf:
        group = hdf.create_group('Event Conditions/Meteorology/Precipitation')
        group.create_dataset('Values', data=np.zeros((2, 3)))
        group.create_dataset('Timestamp', data=[0.])
    with pytest.raises(ValueError, match='Inconsistent precipitation shapes'):
        HdfPlan.get_plan_met_precip_values(path)


def test_retained_snapshot_requires_explicit_group_and_preserves_source(tmp_path):
    path = tmp_path / 'retained-meteorology.h5'
    values = np.array([[0., .2], [.4, .7]], dtype='float32')
    timestamps = np.array([b'01JAN2020 00:06:00', b'01JAN2020 00:12:00'], dtype='S22')
    with h5py.File(path, 'w') as hdf:
        group = hdf.create_group('Meteorology/Precipitation')
        group.attrs['Units'] = np.bytes_('in')
        group.attrs['Ratio'] = np.float32(.8768)
        group.create_dataset('Values', data=values)
        group.create_dataset('Timestamp', data=timestamps)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(KeyError, match='Materialized precipitation'):
        HdfPlan.get_plan_met_precip_values(path)
    result = HdfPlan.get_plan_met_precip_values(str(path), group_path='Meteorology/Precipitation')
    np.testing.assert_array_equal(result['values'], values)
    np.testing.assert_array_equal(result['timestamps'], timestamps)
    assert result['values'].dtype == values.dtype
    assert result['timestamps'].dtype == timestamps.dtype
    assert result['attributes']['Units'] == 'in'
    assert result['attributes']['Ratio'] == np.float32(.8768)
    result['values'][0, 0] = 99
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert HdfPlan.get_plan_met_precip_values(path, group_path='/Meteorology/Precipitation/')['values'][0, 0] == 0


@pytest.mark.parametrize('group_path', ['', '/', None, 42])
def test_invalid_explicit_group_rejected(tmp_path, group_path):
    path = tmp_path / 'retained.h5'
    with h5py.File(path, 'w'):
        pass
    with pytest.raises(ValueError, match='group_path'):
        HdfPlan.get_plan_met_precip_values(path, group_path=group_path)


def test_snapshot_shape_validation_matches_compiled_plan(tmp_path):
    path = tmp_path / 'retained.h5'
    with h5py.File(path, 'w') as hdf:
        group = hdf.create_group('Meteorology/Precipitation')
        group.create_dataset('Values', data=np.ones((2, 3)))
        group.create_dataset('Timestamp', data=[0.])
    with pytest.raises(ValueError, match='Inconsistent precipitation shapes'):
        HdfPlan.get_plan_met_precip_values(path, group_path='Meteorology/Precipitation')
