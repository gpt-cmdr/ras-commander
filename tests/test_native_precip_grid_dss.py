"""Real native DSS7 readback; no Java, Vortex, or hydraulic execution."""

import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('pydsstools', minversion='3.1.0')
from affine import Affine
from pyproj import CRS
from pydsstools.heclib.dss.HecDss import Open
from pydsstools.core.gridinfo import DataType, GridType

from ras_commander import RasDss


@pytest.fixture
def inputs(tmp_path):
    # Actual raw values from NOAA tx100yr24ha.zip, 6x6 Houston crop
    # (-95.45,29.70,-95.40,29.75), obtained 2026-10-03; divided by 1000
    # per https://hdsc.nws.noaa.gov/pfds/meta/na14_vol11_tx_grid_metadata.xml.
    # A projected test layout is deliberate: this exercises serialization,
    # not reprojection or the hydrological suitability of a two-block storm.
    depth = np.array([[16905, 16921, 16938], [16908, 16930, 16945]]) / 1000
    return dict(
        dss_file=tmp_path / 'rain.dss', pathname='/UTM15/HOUSTON/PRECIP///ATLAS14/',
        data=np.stack([depth * .25, depth * .75]),
        interval_bounds=pd.to_datetime(['2020-01-01 23:00', '2020-01-02 00:00', '2020-01-02 00:06']),
        transform=Affine(100, 0, 300000, 0, -100, 3300000),
        crs='EPSG:26915', units='inches',
    )


def test_real_dss_roundtrip_metadata_orientation_missing_and_times(inputs):
    java_was_loaded = 'jnius' in sys.modules
    inputs['data'][0, 0, 1] = np.nan
    inputs['data'][1, 1, 0] = -9
    original = inputs['data'].copy()
    paths = RasDss.write_precip_grid_arrays(**inputs, nodata=-9)
    assert paths == [
        '/UTM15/HOUSTON/PRECIP/01JAN2020:2300/01JAN2020:2400/ATLAS14/',
        '/UTM15/HOUSTON/PRECIP/02JAN2020:0000/02JAN2020:0006/ATLAS14/',
    ]
    expected = np.where(original == -9, np.nan, original)
    np.testing.assert_equal(inputs['data'], original)
    with Open(str(inputs['dss_file'])) as reader:
        assert reader.version == 7
        for i, path in enumerate(paths):
            grid = reader.read_grid(path)
            np.testing.assert_allclose(grid.read().filled(np.nan), expected[i], rtol=1e-6, equal_nan=True)
            info = grid.gridinfo
            assert info.grid_type == GridType.specified_time
            assert info.data_type == DataType.per_cum
            assert info.data_units == 'IN'
            assert info.cell_size == 100
            assert tuple(info.shape) == (2, 3)
            assert tuple(info.coords_cell0) == (300000, 3299800)
            assert tuple(info.lower_left_cell) == (0, 0)
            assert CRS.from_user_input(info.crs).equals(CRS.from_epsg(26915))
            assert info.is_interval
    assert ('jnius' in sys.modules) == java_was_loaded


def test_masked_mm_and_preserve_existing_file(inputs):
    inputs['units'] = 'mm'
    inputs['data'] = np.ma.array(inputs['data'], mask=False)
    inputs['data'].mask[0, 1, 2] = True
    paths = RasDss.write_precip_grid_arrays(**inputs)
    before = inputs['dss_file'].read_bytes()
    with pytest.raises(FileExistsError):
        RasDss.write_precip_grid_arrays(**inputs)
    assert inputs['dss_file'].read_bytes() == before
    with Open(str(inputs['dss_file'])) as reader:
        record = reader.read_grid(paths[0])
        assert record.gridinfo.data_units == 'MM'
        assert record.read().mask[1, 2]
    inputs['data'] = inputs['data'] * 2
    RasDss.write_precip_grid_arrays(**inputs, overwrite=True)
    with Open(str(inputs['dss_file'])) as reader:
        assert reader.read_grid(paths[1]).read()[0, 0] == pytest.approx(inputs['data'][1, 0, 0])


@pytest.mark.parametrize(('key', 'value', 'message'), [
    ('crs', 'EPSG:4326', 'projected'),
    ('units', 'mm/hr', 'interval depth'),
    ('transform', Affine(100, 0, 0, 0, -200, 0), 'square'),
    ('transform', Affine(100, 1, 0, 0, -100, 0), 'unrotated'),
    ('transform', Affine(100, 0, 0, 0, 100, 0), 'north-up'),
    ('interval_bounds', ['2020-01-01', '2020-01-02'], 'n_times'),
    ('interval_bounds', ['2020-01-01', '2020-01-01', '2020-01-02'], 'increasing'),
    ('interval_bounds', pd.date_range('2020-01-01', periods=3, tz='UTC'), 'timezone'),
    ('interval_bounds', ['2020-01-01', 'NaT', '2020-01-02'], 'NaT'),
    ('interval_bounds', pd.date_range('2020-01-01 00:00:01', periods=3), 'whole-minute'),
    ('pathname', '/A/B/PRECIP/01JAN2020/02JAN2020/F/', 'blank'),
    ('pathname', '/A/B/FLOW///F/', 'PRECIP'),
    ('data', np.array([[1, 2]]), 'shape'),
    ('data', np.ones((0, 2, 3)), 'nonempty'),
    ('data', np.full((2, 2, 3), -1), 'nonnegative'),
    ('data', np.full((2, 2, 3), np.inf), 'finite'),
])
def test_reject_ambiguous_or_invalid_inputs_before_creating_output(inputs, key, value, message):
    inputs[key] = value
    with pytest.raises(ValueError, match=message):
        RasDss.write_precip_grid_arrays(**inputs)
    assert not inputs['dss_file'].exists()


def test_invalid_overwrite_preserves_original(inputs):
    RasDss.write_precip_grid_arrays(**inputs)
    before = inputs['dss_file'].read_bytes()
    inputs['data'][0, 0, 0] = -1
    with pytest.raises(ValueError):
        RasDss.write_precip_grid_arrays(**inputs, overwrite=True)
    assert inputs['dss_file'].read_bytes() == before


def test_missing_optional_backend_has_installation_guidance(inputs, monkeypatch):
    import builtins
    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name.startswith('pydsstools'):
            raise ImportError('optional dependency unavailable')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', unavailable)
    with pytest.raises(ImportError, match=r'ras-commander\[dss-native\]'):
        RasDss.write_precip_grid_arrays(**inputs)
    assert not inputs['dss_file'].exists()


def test_native_failure_does_not_publish_partial_file(inputs, monkeypatch):
    RasDss.write_precip_grid_arrays(**inputs)
    before = inputs['dss_file'].read_bytes()

    def failure(*args, **kwargs):
        raise RuntimeError('injected native failure')

    monkeypatch.setattr(Open, 'put_grid', failure)
    with pytest.raises(RuntimeError, match='native failure'):
        RasDss.write_precip_grid_arrays(**inputs, overwrite=True)
    assert inputs['dss_file'].read_bytes() == before
    assert not list(inputs['dss_file'].parent.glob('.rain.*.dss'))


def test_entirely_missing_frame_is_preserved(inputs):
    inputs['data'][0] = np.nan
    paths = RasDss.write_precip_grid_arrays(**inputs)
    with Open(str(inputs['dss_file'])) as reader:
        assert np.ma.getmaskarray(reader.read_grid(paths[0]).read()).all()
