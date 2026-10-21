"""Interval-end contract regressions grounded in the HEC-RAS precipitation table format."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from ras_commander import RasUnsteady


class _Initialized:
    def check_initialized(self):
        pass


def frame(values, *, anchor=False, step=1):
    values = np.asarray(values, dtype=float)
    hours = np.arange(1, len(values) + 1, dtype=float) * step
    if anchor:
        values = np.r_[0., values]
        hours = np.r_[0., hours]
    return pd.DataFrame(dict(hour=hours, incremental_depth=values,
                             cumulative_depth=np.cumsum(values)))


def boundary(name='area2', interval='1HOUR'):
    return (f'Boundary Location=,,,,,{name},,,\nInterval={interval}\n'
            'Precipitation Hydrograph= 3\n    0.00    0.25    0.50\n'
            'DSS Path=\nUse DSS=False\nUse Fixed Start Time=True\n'
            'Fixed Start Date/Time=10JAN2000,1200\n')


@pytest.fixture
def native_file(tmp_path):
    p = tmp_path / 'precip.u01'
    p.write_text('Flow Title=Davis format regression\n' + boundary())
    return p


def values(path):
    return RasUnsteady.extract_tables(path, ras_object=_Initialized())[
        'Precipitation Hydrograph=']['Value'].to_numpy()


@pytest.mark.parametrize('anchor', [False, True])
@pytest.mark.parametrize('step', [1, 0.5, 1/12])
def test_interval_end_values_have_exactly_one_zero_anchor(native_file, anchor, step):
    df = frame([.22, .32, .37, .4, 0, 0], anchor=anchor, step=step)
    RasUnsteady.set_precipitation_hyetograph(native_file, df, boundary_name='area2')
    np.testing.assert_allclose(values(native_file), [0, .22, .32, .37, .4, 0, 0])
    assert 'Use Fixed Start Time=True\nFixed Start Date/Time=10JAN2000,1200' in native_file.read_text()


def test_cumulative_rounding_bounds_error_without_creating_negative_depth(native_file):
    # Independent increment rounding would erase 0.096 inches of real rainfall.
    df = frame([.004] * 24)
    RasUnsteady.set_precipitation_hyetograph(native_file, df)
    written = values(native_file)
    assert written[0] == 0 and len(written) == 25
    assert written.sum() == pytest.approx(.10)
    assert np.all(written >= 0)
    np.testing.assert_allclose(np.cumsum(written)[1:], df.cumulative_depth, rtol=0, atol=.00500001)
    np.testing.assert_allclose(written[1:], df.incremental_depth, rtol=0, atol=.01000001)


def test_explicit_anchor_and_repeated_authoring_are_idempotent(native_file):
    df = frame([.014, .037, .062])
    RasUnsteady.set_precipitation_hyetograph(native_file, df)
    once = native_file.read_bytes()
    RasUnsteady.set_precipitation_hyetograph(native_file, frame([.014, .037, .062], anchor=True))
    assert native_file.read_bytes() == once
    RasUnsteady.set_precipitation_hyetograph(native_file, df)
    assert native_file.read_bytes() == once


@pytest.mark.parametrize('change', [
    lambda d: d.assign(hour=[1, 3, 4]),
    lambda d: d.assign(hour=[1, 1, 2]),
    lambda d: d.assign(hour=[2, 3, 4]),
    lambda d: d.assign(hour=[0, 1, 2]),
    lambda d: d.assign(hour=[1/120, 2/120, 3/120]),
    lambda d: d.assign(incremental_depth=[.1, np.nan, .1]),
    lambda d: d.assign(incremental_depth=[.1, np.inf, .1]),
    lambda d: d.assign(incremental_depth=[.1, -.1, .1]),
    lambda d: d.assign(cumulative_depth=[.1, .2, .4]),
    lambda d: frame([100000, 0, 0]),
    lambda d: frame([99999.999, 0, 0]),
    lambda d: frame([1e308, 0, 0]),
])
def test_invalid_input_leaves_native_file_byte_identical(native_file, change):
    before = native_file.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.set_precipitation_hyetograph(native_file, change(frame([.1, .1, .1])))
    assert native_file.read_bytes() == before


@pytest.mark.parametrize('name', ['', ' ', 3, 'missing', 'area'])
def test_selector_does_not_fall_back_or_match_partial_name(native_file, name):
    before = native_file.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.set_precipitation_hyetograph(native_file, frame([.1, .2]), boundary_name=name)
    assert native_file.read_bytes() == before


@pytest.mark.parametrize('encoding', ['utf-8', 'cp1252'])
@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('terminal_newline', [False, True])
def test_exact_area_selection_preserves_neighbors_encoding_and_writes_crlf(
    tmp_path, encoding, newline, terminal_newline,
):
    p = tmp_path / 'precip.u01'
    before = ('Flow Title=Río\n' + boundary('area20') + boundary('area2') +
              'Precipitation Mode=Disable\n').replace('\n', newline).encode(encoding)
    if not terminal_newline:
        before = before[:-len(newline)]
    p.write_bytes(before)
    RasUnsteady.set_precipitation_hyetograph(p, frame([.1, .2]), boundary_name=' AREA2 ')
    after = p.read_bytes()
    untouched = ('Flow Title=Río\n' + boundary('area20')).replace('\n', '\r\n').encode(encoding)
    assert after.startswith(untouched)
    suffix = 'Precipitation Mode=Disable' + ('\r\n' if terminal_newline else '')
    assert after.endswith(suffix.encode(encoding))
    assert after.endswith(b'\r\n') is terminal_newline
    assert b'\n' not in after.replace(b'\r\n', b'')
    assert b'\r' not in after.replace(b'\r\n', b'')


@pytest.mark.parametrize('bad_block', [boundary()+boundary(), boundary().replace('Interval=1HOUR\n',''),
                                       boundary().replace('Use DSS=False','Use DSS=True')])
def test_invalid_boundary_leaves_original_bytes(tmp_path, bad_block):
    p = tmp_path/'bad.u01';p.write_text(bad_block);before=p.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.set_precipitation_hyetograph(p, frame([.1, .2]), boundary_name='area2')
    assert p.read_bytes() == before

@pytest.mark.parametrize('depths', [[0., 0., 0.], [.01, .32, 2.10, .07, 0.]])
def test_cent_rounded_frames_extra_columns_and_zero_baseline_are_unchanged(native_file, depths):
    df = frame(depths)
    df['time'] = pd.date_range('2000-01-10 13:00', periods=len(df), freq='h')
    before = df.copy(deep=True)
    RasUnsteady.set_precipitation_hyetograph(native_file, df)
    np.testing.assert_allclose(values(native_file), np.r_[0., depths], rtol=0, atol=1e-14)
    pd.testing.assert_frame_equal(df, before)


def test_tolerated_cumulative_noise_cannot_create_negative_rain(native_file):
    df = frame([.5, .505, 0.])
    df['cumulative_depth'] = [.5, 1.0050000001, 1.0049999999]
    RasUnsteady.set_precipitation_hyetograph(native_file, df)
    noisy = native_file.read_bytes()
    assert (values(native_file) >= 0).all()
    RasUnsteady.set_precipitation_hyetograph(native_file, frame([.5, .505, 0.]))
    assert native_file.read_bytes() == noisy
