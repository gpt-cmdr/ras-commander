"""Coastal source metadata and unit/authoring contracts, not solver qualification."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ras_commander.boundaries import CoastalBoundary

SAMPLE = Path(__file__).parents[1] / 'examples/data/stofs3d_gulf/stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc'


@pytest.fixture
def wse():
    return CoastalBoundary.extract_wse_at_point(SAMPLE, 29.35, -94.77)


@pytest.fixture
def stage_file(tmp_path):
    # Minimal native-format serialization fixture, not a hydraulic model.
    path = tmp_path / 'contract.u01'
    path.write_text('Flow Title=Contract fixture\nBoundary Location=,,,,,Bay,,Outlet,\nInterval=1HOUR\nStage Hydrograph= 2\n    1.00    2.00\nUse DSS=False\nBoundary Location=,,,,,Bay,,Other,\nInterval=1HOUR\nStage Hydrograph= 2\n    3.00    4.00\nUse DSS=False\n')
    return path


def read_stage(path):
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('Stage Hydrograph='))
    count = int(lines[start].split('=')[1])
    values = ''.join(lines[start + 1:start + 1 + (count + 9) // 10])
    return np.array([float(values[i:i + 8]) for i in range(0, len(values), 8)])


def test_real_archive_preserves_datum_and_both_units(wse):
    assert wse.attrs['source_datum'] == 'NAVD88'
    assert 'navd88' in wse.attrs['datum_evidence']['variable.standard_name']
    assert len(wse) == 1200
    assert wse.datetime.iloc[0] == pd.Timestamp('2026-04-20 12:06')
    np.testing.assert_allclose(wse.wse_ft * 0.3048, wse.wse_m)


@pytest.mark.parametrize('units', ['feet', 'meters'])
@pytest.mark.parametrize('offset_ft', [-2.5, 0.0, 3.280839895013123])
def test_offset_always_in_feet(stage_file, wse, units, offset_ft):
    values = wse.iloc[:3].copy()
    untouched = stage_file.read_text().split('Boundary Location=,,,,,Bay,,Other,')[1]
    CoastalBoundary.generate_stage_bc(values, stage_file, 'Outlet', units, offset_ft,
                                      target_datum='NAVD88')
    expected_m = values.wse_m.to_numpy() + offset_ft * 0.3048
    expected = expected_m / 0.3048 if units == 'feet' else expected_m
    np.testing.assert_allclose(read_stage(stage_file), expected, atol=0.005)
    assert 'Interval=6MIN' in stage_file.read_text()
    assert stage_file.read_text().split('Boundary Location=,,,,,Bay,,Other,')[1] == untouched


@pytest.mark.parametrize('units', ['ft', 'm', 'Feet', '', None])
def test_invalid_units_rejected_before_write(stage_file, wse, units):
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='units'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', units)
    with pytest.raises(ValueError, match='units'):
        CoastalBoundary.extract_wse_at_point(SAMPLE, 29.35, -94.77, units=units)
    assert stage_file.read_bytes() == before


def test_different_datums_require_offset_provenance(stage_file, wse):
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='datum_adjustment_source'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', target_datum='LMSL')
    assert stage_file.read_bytes() == before
    # Unit/contract test only: this citation is not a real NAVD88/LMSL correction.
    CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, 'Outlet',
        datum_adjustment_ft=0.0, target_datum='LMSL',
        datum_adjustment_source='Explicit test-only zero-offset contract')


def test_conflicting_source_override_rejected(wse, stage_file):
    with pytest.raises(ValueError, match='conflicts'):
        CoastalBoundary.extract_wse_at_point(SAMPLE, 29.35, -94.77, source_datum='LMSL')
    with pytest.raises(ValueError, match='conflicts'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', source_datum='LMSL')


def test_unknown_source_stays_unknown(tmp_path, stage_file):
    # Derived metadata variants use the genuine NOAA values/coordinates.
    with xr.open_dataset(SAMPLE) as source:
        data = source.load()
    data.zeta.attrs = {'units': 'm'}
    path = tmp_path / 'metadata_absent.nc'
    data.to_netcdf(path)
    with pytest.warns(UserWarning, match='Source vertical datum is unknown'):
        result = CoastalBoundary.extract_wse_at_point(path, 29.35, -94.77)
    assert result.attrs['source_datum'] == 'unknown'
    with pytest.raises(ValueError, match='known source_datum'):
        CoastalBoundary.generate_stage_bc(result, stage_file, 'Outlet', target_datum='NAVD88')
    resolved = CoastalBoundary.extract_wse_at_point(path, 29.35, -94.77, source_datum='LMSL')
    assert resolved.attrs['source_datum'] == 'LMSL'
    assert resolved.attrs['datum_evidence']['caller.source_datum'] == 'LMSL'


def test_legacy_call_warns_unverified_target(stage_file, wse):
    with pytest.warns(UserWarning, match='Target vertical datum is unverified'):
        CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, 'Outlet')


@pytest.mark.parametrize('issue', ['nan', 'infinity', 'irregular', 'reversed'])
def test_invalid_series_never_mutates(stage_file, wse, issue):
    data = wse.iloc[:4].copy()
    if issue == 'nan':
        data.loc[data.index[1], 'wse_ft'] = np.nan
    elif issue == 'infinity':
        data.loc[data.index[1], 'wse_ft'] = np.inf
    elif issue == 'irregular':
        data.loc[data.index[1], 'datetime'] += pd.Timedelta(minutes=1)
    else:
        data = data.iloc[::-1]
    before = stage_file.read_bytes()
    with pytest.raises(ValueError):
        CoastalBoundary.generate_stage_bc(data, stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes() == before


def test_no_stage_in_target_cannot_overwrite_next_boundary(stage_file, wse):
    stage_file.write_text(stage_file.read_text().replace('Stage Hydrograph= 2', 'Flow Hydrograph= 2', 1))
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='already contain a Stage Hydrograph'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes() == before


def test_current_product_contract():
    assert CoastalBoundary.VALID_CYCLES == [12]
    assert CoastalBoundary.FORECAST_HOURS == 96
    assert CoastalBoundary.get_info()['current_datums']['station_netcdf'] == 'LMSL'

@pytest.mark.parametrize('offset', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_offset_rejected(stage_file, wse, offset):
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='datum_adjustment_ft must be finite'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', datum_adjustment_ft=offset)
    assert stage_file.read_bytes() == before


@pytest.mark.parametrize('target', ['Out', 'Unknown'])
def test_selector_is_exact(stage_file, wse, target):
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='not found'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, target, target_datum='NAVD88')
    assert stage_file.read_bytes() == before


def test_dss_active_rejected(stage_file, wse):
    stage_file.write_text(stage_file.read_text().replace('Use DSS=False', 'Use DSS=True', 1))
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='uses DSS'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes() == before

@pytest.mark.parametrize('selector', ['', '  ', '\t\n', None, 7, ['Outlet']])
def test_empty_or_nonstring_selector_never_writes(stage_file, wse, selector):
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='bc_location must be a nonempty string'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, selector, target_datum='NAVD88')
    assert stage_file.read_bytes() == before


def test_area_name_is_not_a_boundary_line_selector(stage_file, wse):
    # Make the area name unique, so an any-field selector would incorrectly succeed.
    stage_file.write_text(stage_file.read_text().replace('Bay,,Other', 'Elsewhere,,Other'))
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='not found'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Bay', target_datum='NAVD88')
    assert stage_file.read_bytes() == before


def test_1d_selection_uses_exact_station_not_river_or_reach(stage_file, wse):
    stage_file.write_text(stage_file.read_text().replace(',,,,,Bay,,Outlet,', 'River,Reach,123.45,,,,,,'))
    before = stage_file.read_bytes()
    for selector in ['River', 'Reach']:
        with pytest.raises(ValueError, match='not found'):
            CoastalBoundary.generate_stage_bc(wse, stage_file, selector, target_datum='NAVD88')
        assert stage_file.read_bytes() == before
    CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, '123.45', target_datum='NAVD88')
    assert len(read_stage(stage_file)) == 3


@pytest.mark.parametrize('value', [100000.0, -10000.0, 99999.996, -9999.996, 1e100])
def test_fixed_width_overflow_never_writes(stage_file, wse, value):
    data = wse.iloc[:3].copy()
    data.loc[data.index[0], 'wse_ft'] = value
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='8.2f field width after rounding'):
        CoastalBoundary.generate_stage_bc(data, stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes() == before


@pytest.mark.parametrize('argument', ['source_datum', 'target_datum', 'datum_adjustment_source'])
@pytest.mark.parametrize('value', ['', '   ', 123])
def test_empty_or_nonstring_datum_inputs_never_write(stage_file, wse, argument, value):
    before = stage_file.read_bytes()
    kwargs = {'target_datum': 'NAVD88', argument: value}
    with pytest.raises(ValueError, match='nonempty string'):
        CoastalBoundary.generate_stage_bc(wse, stage_file, 'Outlet', **kwargs)
    assert stage_file.read_bytes() == before


def test_blank_inherited_source_datum_never_writes(stage_file, wse):
    data = wse.copy()
    data.attrs['source_datum'] = '   '
    before = stage_file.read_bytes()
    with pytest.raises(ValueError, match='nonempty string'):
        CoastalBoundary.generate_stage_bc(data, stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes() == before


@pytest.mark.parametrize('source_datum', ['', '   ', 123])
def test_extraction_rejects_invalid_source_label(source_datum):
    with pytest.raises(ValueError, match='source_datum must be a nonempty string'):
        CoastalBoundary.extract_wse_at_point(SAMPLE, 29.35, -94.77, source_datum=source_datum)


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
@pytest.mark.parametrize('terminal_newline', [True, False])
def test_authoring_preserves_newline_style(stage_file, wse, newline, terminal_newline):
    original = stage_file.read_text().rstrip('\n').replace('\n', newline.decode()).encode()
    if terminal_newline:
        original += newline
    stage_file.write_bytes(original)
    CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, ' Outlet ',
                                      source_datum=' NAVD88 ', target_datum=' NAVD88 ')
    written = stage_file.read_bytes()
    assert written.endswith(newline) == terminal_newline
    if newline == b'\r\n':
        assert b'\n' not in written.replace(b'\r\n', b'')
    else:
        assert b'\r' not in written
    marker = b'Boundary Location=,,,,,Bay,,Other,'
    assert written.split(marker)[1] == original.split(marker)[1]

@pytest.mark.parametrize('encoding', ['cp1252', 'utf-8'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_native_encoding_and_accented_boundary_roundtrip(stage_file, wse, encoding, newline):
    content = stage_file.read_text().replace('Contract fixture', 'Río – Côte')
    content = content.replace('Bay,,Outlet', 'Bay,,Déversoir')
    content = content.replace('Bay,,Other', 'Baie côtière,,Autre')
    original = content.replace('\n', newline).encode(encoding)
    stage_file.write_bytes(original)
    CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, 'Déversoir', target_datum='NAVD88')
    written = stage_file.read_bytes()
    # Header and adjacent boundary retain their original native bytes exactly.
    marker = 'Boundary Location=,,,,,Baie côtière,,Autre,'.encode(encoding)
    assert written.split(marker)[1] == original.split(marker)[1]
    assert written.split(b'Boundary Location=')[0] == original.split(b'Boundary Location=')[0]
    assert 'Bay,,Déversoir'.encode(encoding) in written
    assert ('Stage Hydrograph= 3' + newline).encode(encoding) in written
    assert written.endswith(newline.encode())
    if newline == '\r\n':
        assert b'\n' not in written.replace(b'\r\n', b'')
    else:
        assert b'\r' not in written


def test_unassigned_legacy_bytes_preserved(stage_file, wse):
    original = stage_file.read_bytes().replace(b'Contract fixture', b'Legacy title \x81')
    stage_file.write_bytes(original)
    CoastalBoundary.generate_stage_bc(wse.iloc[:3], stage_file, 'Outlet', target_datum='NAVD88')
    assert stage_file.read_bytes().split(b'Boundary Location=')[0] == original.split(b'Boundary Location=')[0]
