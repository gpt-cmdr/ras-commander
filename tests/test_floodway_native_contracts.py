"""Native parser/HDF regressions; these tests do not qualify hydraulic authoring.

Optional external integration inputs are read-only. Set
RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP and RAS_COMMANDER_FLOODWAY_HDF to use
the retained USACE Example 6 archive and the HEC-RAS 6.5 result fixture.
"""
import hashlib
import os
from pathlib import Path
import zipfile
from collections import Counter

import h5py
import numpy as np
import pytest

from ras_commander import RasFloodway
from ras_commander.check import RasCheck
from ras_commander.check.check_floodways import CheckFloodways


BASE = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles'
ATTRS = 'Results/Steady/Output/Geometry Info/Cross Section Attributes'
GEOM_ATTRS = 'Geometry/Cross Sections/Attributes'
LEFT = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Left'
RIGHT = f'{BASE}/Cross Sections/Additional Variables/Encroachment Station Right'
COMBINED = f'{BASE}/Cross Sections/Encroachment Stations'
COLUMNS = ['river', 'reach', 'station', 'encr_sta_l', 'encr_sta_r']


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope='module')
def native_zip():
    path = Path(os.environ.get(
        'RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP',
        r'H:\CLB-Repos\ras-commander\Example_Projects_6_6.zip',
    ))
    if not path.is_file():
        pytest.skip('USACE Example 6 archive unavailable; set RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP')
    before = _sha256(path)
    yield path
    assert _sha256(path) == before, 'Original source archive changed'


@pytest.fixture(scope='module')
def native_hdf():
    path = Path(os.environ.get(
        'RAS_COMMANDER_FLOODWAY_HDF',
        r'H:\CLB-Repos\ras-commander\feature_dev_notes\rashdf-pr\rashdf\tests\data\ras_1d\FLODENCR.p01.hdf',
    ))
    if not path.is_file():
        pytest.skip('Retained Example 6 HDF unavailable; set RAS_COMMANDER_FLOODWAY_HDF')
    before = _sha256(path)
    assert before == '4a7509cb2d9f4f1b60fed6de86c0656a817dfb880403f22fa54ccddc950cf1dc'
    yield path
    assert _sha256(path) == before, 'Original result HDF changed'


def test_native_p02_blank_values_keep_all_three_profiles(native_zip, tmp_path):
    with zipfile.ZipFile(native_zip) as archive:
        data = archive.read('Applications Guide/Example 6 - Floodway Determination/FLODENCR.P02')
    assert hashlib.sha256(data).hexdigest() == 'ec6466111515dc1d380c565a0b152c095d09ae854009e06698f0eb42023d1bc0'
    plan = tmp_path / 'FLODENCR.P02'
    plan.write_bytes(data)
    frame = RasFloodway.parse_encroachments(plan)
    assert len(frame) == 78
    assert frame['method'].eq(4).all()
    assert frame['value_2'].isna().all()
    assert set(frame['reach']) == {'Beaver Creek', 'Kentwood'}
    for _, group in frame.groupby('line_number', sort=False):
        assert group['profile_number'].tolist() == [2, 3, 4]
        # The native downstream boundary record deliberately uses 1 for all
        # profiles; other sections use the three trial targets.
        targets = [1., 1., 1.] if group.iloc[0]['node'] == '5.0' else [.8, .9, 1.]
        assert group['target_surcharge'].tolist() == targets
    assert any('*' in node for node in frame['node'])


def test_native_method5_and_mixed_method_controls(native_zip, tmp_path):
    with zipfile.ZipFile(native_zip) as archive:
        for name in ('flodencr.p01', 'FLODENCR.P05'):
            data = archive.read(f'Applications Guide/Example 6 - Floodway Determination/{name}')
            plan = tmp_path / name
            plan.write_bytes(data)
            frame = RasFloodway.parse_encroachments(plan)
            if name.endswith('p01'):
                assert hashlib.sha256(data).hexdigest() == 'a5f3d7b2fed6cbba52f98233a9574ece09b6fad3abd665bcb32a3c71bfa29eb3'
                assert len(frame) == 13
                assert frame['method'].eq(5).all()
                assert frame['target_surcharge'].eq(1).all()
                assert frame['energy_target'].eq(1.2).all()
            else:
                assert frame['method'].value_counts().to_dict() == {4: 13, 1: 13}


def test_native_field_layout_preserves_blanks_and_adjacent_full_width_values():
    # Literal fields are independent of the library's writer.
    raw = '       4      .8               4      .9               4       1        '
    assert RasFloodway._parse_node_slots(raw, 3) == [[4, .8, None], [4, .9, None], [4, 1., None]]
    assert RasFloodway._parse_node_slots('       1-123.45612345.67', 1) == [[1, -123.456, 12345.67]]
    assert RasFloodway._parse_node_slots('                        ' + raw[:24], 3) == [
        [None, None, None], [4, .8, None], [None, None, None],
    ]
    assert RasFloodway._parse_node_slots('       4      .8', 1) == [[4, .8, None]]
    assert RasFloodway._parse_node_slots(raw + ' ' * 8, 3) == [[4, .8, None], [4, .9, None], [4, 1., None]]
    assert RasFloodway._parse_node_slots(raw + ' ' * 24, 3) == [[4, .8, None], [4, .9, None], [4, 1., None]]


def test_unambiguous_compact_complete_triplets_remain_supported():
    assert RasFloodway._parse_node_slots('1 -10 20 5 1 1.2', 2) == [[1, -10., 20.], [5, 1., 1.2]]


def test_writer_field_positions_have_independent_expected_values(tmp_path):
    path = tmp_path / 'written.p01'
    path.write_text('Plan Title=Field regression\n', encoding='utf-8')
    frame = RasFloodway.set_encroachments(path, [{
        'river': 'River', 'reach': 'Reach', 'node': '5.875*',
        'profiles': [{'method': 4, 'target_surcharge': .8},
                     {'method': 5, 'target_surcharge': 1., 'energy_target': 1.2}],
    }])
    lines = path.read_text(encoding='utf-8').splitlines()
    values = lines[lines.index('Encroach Node=5.875*') + 1]
    assert len(values) == 48
    assert [float(values[i:i + 8]) for i in range(0, 48, 8)] == [4, .8, 0, 5, 1, 1.2]
    assert frame['method'].tolist() == [4, 5]
    assert frame['target_surcharge'].tolist() == [.8, 1.]


def test_rewrite_consumes_full_width_values_and_all_old_nodes(tmp_path):
    path = tmp_path / 'rewrite.p01'
    path.write_text('Plan Title=Rewrite regression\nCheckData=True\nOther=Preserved\n', encoding='utf-8')
    records = [dict(river='River', reach='Reach', node=node, method=1,
                    left_station=176.9155, right_station=1202.3324)
               for node in ('5.99', '5.875*')]
    RasFloodway.set_encroachments(path, records)
    first = path.read_bytes()
    result = RasFloodway.set_encroachments(path, records)
    assert result['node'].tolist() == ['5.99', '5.875*']
    assert path.read_bytes() == first
    assert 'Other=Preserved' in path.read_text(encoding='utf-8')


def test_native_station_rewrite_is_idempotent(native_zip, native_hdf, tmp_path):
    path = tmp_path / 'native.p01'
    with zipfile.ZipFile(native_zip) as archive:
        path.write_bytes(archive.read('Applications Guide/Example 6 - Floodway Determination/flodencr.p01'))
    stations = CheckFloodways._get_encroachment_stations(native_hdf, 'PF#2')
    records = [dict(river=row.river, reach=row.reach, node=row.station, method=1,
                    left_station=row.encr_sta_l, right_station=row.encr_sta_r)
               for row in stations.itertuples(index=False)]
    first = RasFloodway.set_encroachments(path, records)
    first_bytes = path.read_bytes()
    second = RasFloodway.set_encroachments(path, records)
    assert len(first) == len(second) == 12
    assert second['node'].tolist() == stations['station'].tolist()
    assert path.read_bytes() == first_bytes


@pytest.mark.parametrize('explicit_locations', [False, True])
def test_native_plan_parse_failure_precedes_trial_flow_mutation(native_zip, tmp_path, explicit_locations):
    path, flow = tmp_path / 'bad.p01', tmp_path / 'FLODENCR.F01'
    with zipfile.ZipFile(native_zip) as archive:
        plan_bytes = archive.read('Applications Guide/Example 6 - Floodway Determination/flodencr.p01')
        flow_bytes = archive.read('Applications Guide/Example 6 - Floodway Determination/FLODENCR.F01')
    path.write_bytes(plan_bytes.replace(b'       5       1     1.2', b'      .9       1     1.2', 1))
    flow.write_bytes(flow_bytes)
    before_plan = path.read_bytes()
    locations = [dict(river='Beaver Creek', reach='Kentwood', node='5.99')] if explicit_locations else None
    with pytest.raises(ValueError, match='invalid method'):
        RasFloodway.create_trial_profiles(path, method=4, targets=[.8],
                                         flow_number_or_path=flow, locations=locations)
    assert path.read_bytes() == before_plan
    assert flow.read_bytes() == flow_bytes


@pytest.mark.parametrize('record, count, error', [
    ('      .9       1       2', 1, 'invalid method'),
    ('       6       1       2', 1, 'invalid method'),
    ('      -1       1       2', 1, 'invalid method'),
    ('       4     bad        ', 1, 'invalid numeric field'),
    ('       4     nan        ', 1, 'non-finite'),
    ('               1       2', 1, 'values but no method'),
    ('       4      .8       0       5       1     1.2', 1, 'header allows'),
    ('       4      .', 1, 'incomplete eight-character'),
    ('4 .8', 1, 'incomplete eight-character'),
])
def test_malformed_native_records_fail_without_token_recovery(record, count, error):
    with pytest.raises(ValueError, match=error):
        RasFloodway._parse_node_slots(record, count)


def test_public_parser_error_includes_native_identity_and_line(tmp_path):
    path = tmp_path / 'bad.p01'
    path.write_text('Encroach Param=-1,0,0,2\nEncroach River=River\n'
                    'Encroach Reach=Reach\nEncroach Node=5.875*\n'
                    '      .9       1       2\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'line 5.*River/Reach/5\.875\*'):
        RasFloodway.parse_encroachments(path)


def _station_hdf(path, profiles=(b'Base', b'Floodway')):
    """Small adversarial layouts supplement, rather than replace, native evidence."""
    dtype = [('River', 'S16'), ('Reach', 'S16'), ('Station', 'S16')]
    identities = np.array([(b'River', b'Reach', b'5.875*'), (b'River', b'Reach', b'5.0')], dtype=dtype)
    with h5py.File(path, 'w') as hdf:
        hdf[f'{BASE}/Profile Names'] = np.array(profiles)
        hdf[ATTRS] = identities
        hdf[GEOM_ATTRS] = identities[::-1]  # Same count, deliberately wrong order.
        hdf[LEFT] = np.array([[np.nan, np.nan], [-10., 20.]])[:len(profiles)]
        hdf[RIGHT] = np.array([[np.nan, np.nan], [100., 200.]])[:len(profiles)]
    return path


def test_native_additional_variables_select_profile_and_preserve_nan(native_hdf):
    frame = CheckFloodways._get_encroachment_stations(native_hdf, 'PF#2')
    assert frame is not None
    assert frame.columns.tolist() == COLUMNS
    assert len(frame) == 12
    assert frame.iloc[0][['river', 'reach', 'station']].tolist() == ['Beaver Creek', 'Kentwood', '5.99']
    assert frame.iloc[1]['station'] == '5.875*'
    assert frame.iloc[0]['encr_sta_l'] == pytest.approx(176.9155)
    assert frame.iloc[0]['encr_sta_r'] == pytest.approx(1202.3324)
    assert frame.iloc[-1]['encr_sta_l'] == pytest.approx(384.)
    assert frame.iloc[-1]['encr_sta_r'] == pytest.approx(1296.5653)
    base = CheckFloodways._get_encroachment_stations(native_hdf, 'PF#1')
    assert base[['encr_sta_l', 'encr_sta_r']].isna().all().all()
    assert CheckFloodways._get_encroachment_stations(native_hdf, 'missing') is None


def test_native_public_checker_does_not_guess_methods_or_station_distances(native_hdf):
    result = RasCheck.check_floodways(native_hdf, native_hdf, 'PF#1', 'PF#2')
    assert len(result.floodway_summary) == 12
    assert Counter(message.message_id for message in result.messages) == {
        'FW_SC_01': 3, 'FW_SC_04': 5, 'FW_SC_02': 1,
        'FW_SW_01': 1, 'FW_SW_02': 1, 'FW_SW_04': 1,
    }
    # PF#1 is deliberately selected as a missing-station control, not a
    # hydraulically encroached floodway. No authored method can be inferred.
    missing = RasCheck.check_floodways(native_hdf, native_hdf, 'PF#1', 'PF#1')
    assert Counter(message.message_id for message in missing.messages) == {
        'FW_SC_03': 12, 'FW_EM_04': 12, 'FW_SW_01': 1, 'FW_SW_04': 1, 'FW_SW_05': 1,
    }
    station_messages = [message for message in missing.messages if message.message_id == 'FW_EM_04']
    assert all('results unavailable' in message.message for message in station_messages)
    assert all('do not establish' in message.help_text for message in station_messages)


def test_result_identifiers_take_precedence_over_reordered_geometry(tmp_path):
    path = _station_hdf(tmp_path / 'stations.hdf')
    frame = CheckFloodways._get_encroachment_stations(path, 'Floodway')
    assert frame.columns.tolist() == COLUMNS  # No invented encr_method.
    assert frame['station'].tolist() == ['5.875*', '5.0']
    assert frame['encr_sta_l'].tolist() == [-10., 20.]
    assert frame['encr_sta_r'].tolist() == [100., 200.]


@pytest.mark.parametrize('case, diagnostic', [
    ('unknown_profile', 'must occur exactly once'),
    ('duplicate_profile', 'must occur exactly once'),
    ('missing_profile_names', 'missing steady profile names'),
    ('missing_right', 'missing paired'),
    ('wrong_shape', 'paired station shapes'),
    ('missing_result_ids', 'missing cross-section identifiers'),
    ('wrong_id_count', 'paired station shapes'),
    ('duplicate_ids', 'duplicate cross-section identifiers'),
    ('ambiguous_combined', 'ambiguous combined station shape'),
])
def test_incomplete_or_ambiguous_station_data_is_diagnosed(tmp_path, caplog, case, diagnostic):
    path = _station_hdf(tmp_path / 'stations.hdf')
    profile = 'Floodway'
    with h5py.File(path, 'a') as hdf:
        if case == 'unknown_profile':
            profile = 'Other'
        elif case == 'duplicate_profile':
            hdf[f'{BASE}/Profile Names'][:] = [b'Floodway', b'Floodway']
        elif case == 'missing_profile_names':
            del hdf[f'{BASE}/Profile Names']
        elif case == 'missing_right':
            del hdf[RIGHT]
        elif case == 'wrong_shape':
            del hdf[RIGHT]
            hdf[RIGHT] = np.zeros((2, 3))
        elif case == 'missing_result_ids':
            del hdf[ATTRS]
        elif case == 'wrong_id_count':
            attrs = hdf[ATTRS][()][:1]
            del hdf[ATTRS]
            hdf[ATTRS] = attrs
        elif case == 'duplicate_ids':
            hdf[ATTRS][1] = hdf[ATTRS][0]
        elif case == 'ambiguous_combined':
            del hdf[LEFT]
            del hdf[RIGHT]
            hdf[COMBINED] = np.array([[10., 100.], [20., 200.]])
    assert CheckFloodways._get_encroachment_stations(path, profile) is None
    assert diagnostic in caplog.text


def test_legacy_combined_explicit_three_dimensional_axes(tmp_path):
    path = _station_hdf(tmp_path / 'combined.hdf')
    with h5py.File(path, 'a') as hdf:
        del hdf[LEFT]
        del hdf[RIGHT]
        hdf[COMBINED] = np.array([[[np.nan, np.nan], [10., 100.]],
                                  [[np.nan, np.nan], [20., 200.]]])
    frame = CheckFloodways._get_encroachment_stations(path, 'Floodway')
    assert frame['encr_sta_l'].tolist() == [10., 20.]
    assert frame['encr_sta_r'].tolist() == [100., 200.]


def test_combined_two_dimensional_layout_requires_single_profile(tmp_path):
    path = _station_hdf(tmp_path / 'single.hdf', profiles=(b'Floodway',))
    with h5py.File(path, 'a') as hdf:
        del hdf[LEFT]
        del hdf[RIGHT]
        hdf[COMBINED] = np.array([[10., 100.], [20., 200.]])
    frame = CheckFloodways._get_encroachment_stations(path, 'Floodway')
    assert frame['encr_sta_l'].tolist() == [10., 20.]
