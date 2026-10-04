"""Schema checks for the reader; real engine qualification lives in the QA run."""
import h5py
import numpy as np
import pytest
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
