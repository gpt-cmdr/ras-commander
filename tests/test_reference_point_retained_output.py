"""Read-only qualification of recovered notebook207 native reference output."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from ras_commander import HdfBndry, HdfResultsXsec


def test_recovered_reference_output_matches_retained_evidence():
    source = os.environ.get('RAS_REFERENCE_POINT_HDF')
    if not source:
        pytest.skip('Set RAS_REFERENCE_POINT_HDF to the retained notebook207 HDF')
    path = Path(source)
    assert path.is_file(), f'Configured reference output is missing: {path}'
    manifest = json.loads((Path(__file__).parent / 'fixtures/reference_points/qualification_evidence.json').read_text())
    digest = lambda: hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest() == manifest['computed_hdf_sha256']
    expected = manifest['verified_output']
    points = HdfBndry.get_reference_points(path)
    assert list(points.Name) == expected['reference_point_names']
    np.testing.assert_array_equal([[p.x, p.y] for p in points.geometry], expected['reference_points_xy'])
    np.testing.assert_array_equal(points['Cell Index'], expected['point_cell_indices'])
    point_data = HdfResultsXsec.get_ref_points_timeseries(path)
    line_data = HdfResultsXsec.get_ref_lines_timeseries(path)
    assert list(point_data.refpt_name.values) == expected['reference_point_names']
    assert list(line_data.refln_name.values) == ['RL_Mid']
    for data, key in [(point_data, 'point_series'), (line_data, 'line_series')]:
        oracle = expected[key]
        assert dict(data.sizes) == oracle['sizes']
        assert str(data.time.values[0]) == oracle['time_start']
        assert str(data.time.values[-1]) == oracle['time_end']
        assert set(data.data_vars) == set(oracle['variables'])
        for variable, array in data.data_vars.items():
            fingerprint = oracle['variables'][variable]
            assert list(array.shape) == fingerprint['shape']
            assert str(array.dtype) == fingerprint['dtype']
            assert hashlib.sha256(array.values.tobytes()).hexdigest() == fingerprint['values_sha256']
    np.testing.assert_array_equal(point_data.time, line_data.time)
    assert np.all(np.diff(point_data.time.values) == np.timedelta64(10, 'm'))
    assert np.any(line_data.Flow.values < 0)
    assert digest() == manifest['computed_hdf_sha256']
