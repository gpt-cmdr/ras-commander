"""Public station reads and failure-before-write floodway authoring contracts."""
import os
from pathlib import Path
import zipfile

import h5py
import numpy as np
import pytest

from ras_commander import HdfResultsPlan, RasFloodway
from ras_commander.check.check_floodways import CheckFloodways


BASE = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles'
IDS = 'Results/Steady/Output/Geometry Info/Cross Section Attributes'


@pytest.fixture
def station_hdf(tmp_path):
    path = tmp_path / 'native-layout.p01.hdf'
    with h5py.File(path, 'w') as hdf:
        hdf[f'{BASE}/Profile Names'] = np.array([b'Base', b'Floodway'])
        hdf[IDS] = np.array([(b'River', b'Reach', b'5.875*')],
                            dtype=[('River', 'S16'), ('Reach', 'S16'), ('Station', 'S16')])
        hdf[f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Left'] = [[np.nan], [10.]]
        hdf[f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Right'] = [[np.nan], [20.]]
    return path


@pytest.mark.synthetic_hdf_layout
def test_public_station_reader_preserves_identity_and_base_nan(station_hdf):
    frame = HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Floodway')
    assert frame.columns.tolist() == ['river', 'reach', 'station', 'encr_sta_l', 'encr_sta_r']
    assert frame.iloc[0].tolist() == ['River', 'Reach', '5.875*', 10., 20.]
    base = HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Base')
    assert base[['encr_sta_l', 'encr_sta_r']].isna().all().all()


@pytest.mark.synthetic_hdf_layout
def test_public_station_schema_matches_reader(station_hdf):
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    schema = DATAFRAME_SCHEMAS['steady_encroachment_stations']
    frame = HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Floodway')
    assert schema['accessor'] == 'HdfResultsPlan.get_steady_encroachment_stations(hdf_path, profile_name)'
    assert not schema['extra_columns'] and not schema['dynamic']
    assert [column['name'] for column in schema['columns']] == frame.columns.tolist()
    assert [column['dtype'] for column in schema['columns']] == ['str', 'str', 'str', 'float64', 'float64']
    assert frame['encr_sta_l'].dtype == frame['encr_sta_r'].dtype == np.dtype('float64')


@pytest.mark.synthetic_hdf_layout
def test_public_station_empty_arrays_keep_declared_numeric_dtypes(station_hdf):
    with h5py.File(station_hdf, 'a') as hdf:
        dtype = hdf[IDS].dtype
        del hdf[IDS]
        hdf[IDS] = np.empty(0, dtype=dtype)
        for side in ['Left', 'Right']:
            path = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station {side}'
            del hdf[path]
            hdf[path] = np.empty((2, 0), dtype=float)
    frame = HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Floodway')
    assert frame.empty
    assert frame['encr_sta_l'].dtype == frame['encr_sta_r'].dtype == np.dtype('float64')


@pytest.mark.synthetic_hdf_layout(
    "combined_inf",
    "right_group",
    "station_bool",
    "station_complex",
    "station_neginf",
    "station_posinf",
    "station_string",
)
@pytest.mark.parametrize('failure', [
    'station_string', 'station_complex', 'station_bool', 'station_posinf', 'station_neginf',
    'left_group', 'right_group', 'profile_group', 'profile_numeric', 'profile_rank', 'profile_scalar',
    'ids_group', 'ids_rank', 'ids_plain', 'ids_numeric_field', 'ids_array_field',
    'combined_string', 'combined_group', 'combined_inf',
])
def test_public_station_reader_malformed_storage_is_contextual(station_hdf, failure, caplog):
    with h5py.File(station_hdf, 'a') as hdf:
        left = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Left'
        right = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Right'
        profile = f'{BASE}/Profile Names'
        if failure.startswith('station_'):
            del hdf[right]
            hdf[right] = {
                'station_string': np.array([[b'nan'], [b'20']]),
                'station_complex': np.array([[np.nan], [20. + 1.j]]),
                'station_bool': np.array([[False], [True]]),
                'station_posinf': np.array([[np.nan], [np.inf]]),
                'station_neginf': np.array([[np.nan], [-np.inf]]),
            }[failure]
        elif failure.endswith('_group'):
            path = {'left_group': left, 'right_group': right,
                    'profile_group': profile, 'ids_group': IDS}.get(failure)
            if failure == 'combined_group':
                del hdf[left]
                del hdf[right]
                path = f'{BASE}/Cross Sections/Encroachment Stations'
            else:
                del hdf[path]
            hdf.create_group(path)
        elif failure.startswith('profile_'):
            del hdf[profile]
            if failure == 'profile_numeric':
                hdf[profile] = np.array([1, 2])
            elif failure == 'profile_scalar':
                hdf[profile] = 'Floodway'
            else:
                hdf[profile] = np.array([[b'Base', b'Floodway']])
        elif failure.startswith('ids_'):
            values = hdf[IDS][()]
            del hdf[IDS]
            if failure == 'ids_rank':
                hdf[IDS] = values.reshape(1, 1)
            elif failure == 'ids_plain':
                hdf[IDS] = [b'not compound identifiers']
            elif failure == 'ids_numeric_field':
                hdf[IDS] = np.array([(12, b'Reach', b'5.875*')], dtype=[('River', 'i4'), ('Reach', 'S16'), ('Station', 'S16')])
            else:
                hdf[IDS] = np.zeros(1, dtype=[('River', 'S16', (2,)), ('Reach', 'S16'), ('Station', 'S16')])
        else:
            del hdf[left]
            del hdf[right]
            values = np.array([[[np.nan, np.nan], [10., 20.]]])
            if failure == 'combined_string':
                values = np.array([[[b'nan', b'nan'], [b'10', b'20']]])
            else:
                values[0, 1, 1] = np.inf
            hdf[f'{BASE}/Cross Sections/Encroachment Stations'] = values
    with pytest.raises(ValueError, match='native-layout.*profile'):
        HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Floodway')
    assert CheckFloodways._get_encroachment_stations(station_hdf, 'Floodway') is None
    assert 'Could not extract encroachment stations' in caplog.text


def test_public_station_reader_missing_is_unavailable(station_hdf):
    with h5py.File(station_hdf, 'a') as hdf:
        del hdf[f'{BASE}/Cross Sections']
    assert HdfResultsPlan.get_steady_encroachment_stations(station_hdf, 'Floodway') is None


def test_retained_native_public_station_reader():
    path = Path(os.environ.get('RAS_COMMANDER_FLOODWAY_HDF',
                               'tests/data/external/FLODENCR.p01.hdf'))
    if not path.is_file():
        pytest.skip('Set RAS_COMMANDER_FLOODWAY_HDF to the retained native Example 6 result')
    frame = HdfResultsPlan.get_steady_encroachment_stations(path, 'PF#2')
    assert len(frame) == 12
    assert frame.iloc[0][['river', 'reach', 'station']].tolist() == ['Beaver Creek', 'Kentwood', '5.99']
    assert frame.iloc[0]['encr_sta_l'] == pytest.approx(176.9155)
    assert frame.iloc[0]['encr_sta_r'] == pytest.approx(1202.3324)
    assert frame.iloc[-1]['encr_sta_l'] == pytest.approx(384.)
    assert frame.iloc[-1]['encr_sta_r'] == pytest.approx(1296.5653)


def test_fresh_native_mixed_method_final_preserves_base_and_written_stations(tmp_path):
    configured = os.environ.get('RAS_COMMANDER_FLOODWAY_NATIVE_PROJECT_ROOT')
    if not configured:
        pytest.skip('Set RAS_COMMANDER_FLOODWAY_NATIVE_PROJECT_ROOT to the retained fresh Example 6 project')
    root = Path(configured)
    trial, final = root / 'FLODENCR.p01.hdf', root / 'FLODENCR.p06.hdf'
    assert HdfResultsPlan.get_steady_profile_names(trial) == ['PF#1', 'PF#2']
    assert HdfResultsPlan.get_steady_profile_names(final) == ['PF#1', 'PF#2']
    authored = RasFloodway.parse_encroachments(root / 'FLODENCR.p06')
    assert authored['method'].value_counts().to_dict() == {1: 12, 5: 1}
    bridge = authored[authored.method == 5].iloc[0]
    assert [bridge.river, bridge.reach, bridge.node] == ['Beaver Creek', 'Kentwood', '5.4']
    pairs = HdfResultsPlan.get_steady_encroachment_stations(final, 'PF#2')
    expected = authored[authored.method == 1].rename(columns={'node': 'station'})
    matched = expected.merge(pairs, on=['river', 'reach', 'station'], validate='one_to_one')
    assert len(matched) == len(expected) == len(pairs) == 12
    np.testing.assert_allclose(matched.left_station, matched.encr_sta_l, rtol=1e-6, atol=1e-4)
    np.testing.assert_allclose(matched.right_station, matched.encr_sta_r, rtol=1e-6, atol=1e-4)
    keys = ['river', 'reach', 'node_id', 'profile']
    comparison = HdfResultsPlan.get_steady_results(trial).merge(
        HdfResultsPlan.get_steady_results(final), on=keys,
        validate='one_to_one', suffixes=('_trial', '_final'),
    )
    assert len(comparison) == 24
    base = comparison[comparison.profile == 'PF#1']
    for name in ['wsel', 'flow']:
        np.testing.assert_allclose(base[name + '_trial'], base[name + '_final'], rtol=0, atol=1e-5)
    copied = tmp_path / 'final.p06'
    copied.write_bytes((root / 'FLODENCR.p06').read_bytes())
    RasFloodway.set_encroachments(copied, authored, profile_count=2, encroach_param=(-1, 10, 10, 2))
    first = copied.read_bytes()
    RasFloodway.set_encroachments(copied, authored, profile_count=2, encroach_param=(-1, 10, 10, 2))
    assert copied.read_bytes() == first


@pytest.mark.synthetic_hdf_layout(
    "wrong_shape",
)
@pytest.mark.parametrize('failure', ['unpaired', 'unknown_profile', 'wrong_shape', 'duplicate_ids'])
def test_public_station_reader_malformed_raises_checker_retains_diagnostic(station_hdf, failure, caplog):
    profile = 'Floodway'
    with h5py.File(station_hdf, 'a') as hdf:
        right = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Right'
        if failure == 'unpaired':
            del hdf[right]
        elif failure == 'unknown_profile':
            profile = 'Unknown'
        elif failure == 'wrong_shape':
            del hdf[right]
            hdf[right] = [[20., 30.]]
        else:
            values = hdf[IDS][()]
            del hdf[IDS]
            hdf[IDS] = np.concatenate([values, values])
    with pytest.raises(ValueError, match='native-layout.*profile'):
        HdfResultsPlan.get_steady_encroachment_stations(station_hdf, profile)
    assert CheckFloodways._get_encroachment_stations(station_hdf, profile) is None
    assert 'Could not extract encroachment stations' in caplog.text


@pytest.mark.parametrize('kwargs', [
    dict(method=1, targets=[1.]),
    dict(method=2, targets=[100.]),
    dict(method=3, targets=[10.]),
    dict(method=5, targets=[1.], energy_targets=[1., 2.]),
    dict(method=5, targets=[1.e12]),
])
def test_real_example_invalid_trial_request_preserves_plan_and_flow(tmp_path, kwargs):
    archive = Path(os.environ.get('RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP',
                                  'tests/data/external/Example_Projects_6_6.zip'))
    if not archive.is_file():
        pytest.skip('Set RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP to the official 6.6 archive')
    with zipfile.ZipFile(archive) as source:
        plan_data = source.read('Applications Guide/Example 6 - Floodway Determination/flodencr.p01')
        flow_data = source.read('Applications Guide/Example 6 - Floodway Determination/FLODENCR.F01')
    plan, flow = tmp_path / 'FLODENCR.p01', tmp_path / 'FLODENCR.F01'
    plan.write_bytes(plan_data)
    flow.write_bytes(flow_data)
    with pytest.raises(ValueError):
        RasFloodway.create_trial_profiles(plan, flow_number_or_path=flow, **kwargs)
    assert plan.read_bytes() == plan_data
    assert flow.read_bytes() == flow_data


@pytest.mark.parametrize('method', [4, 5])
def test_real_example_valid_trials_append_after_existing_profiles(tmp_path, method):
    from ras_commander import RasSteady

    archive = Path(os.environ.get('RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP',
                                  'tests/data/external/Example_Projects_6_6.zip'))
    if not archive.is_file():
        pytest.skip('Set RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP to the official 6.6 archive')
    with zipfile.ZipFile(archive) as source:
        plan_data = source.read('Applications Guide/Example 6 - Floodway Determination/flodencr.p01')
        flow_data = source.read('Applications Guide/Example 6 - Floodway Determination/FLODENCR.F01')
    plan, flow = tmp_path / 'FLODENCR.p01', tmp_path / 'FLODENCR.F01'
    plan.write_bytes(plan_data)
    flow.write_bytes(flow_data)
    kwargs = dict(energy_targets=[1.2, 1.3]) if method == 5 else {}
    result = RasFloodway.create_trial_profiles(
        plan, method=method, targets=[.8, 1.], flow_number_or_path=flow,
        locations=[dict(river='Beaver Creek', reach='Kentwood', node='5.99', profile_number=99)],
        profile_names=['Trial A', 'Trial B'], **kwargs,
    )
    assert result['new_profile_numbers'] == [3, 4]
    assert RasSteady.read_flow_file(flow)['profile_names'] == ['PF#1', 'PF#2', 'Trial A', 'Trial B']
    authored = result['encroachments']
    active = authored[authored.method == method]
    assert active['profile_number'].tolist() == [3, 4]
    assert active['target_surcharge'].tolist() == [.8, 1.]
    if method == 5:
        assert active['energy_target'].tolist() == [1.2, 1.3]
