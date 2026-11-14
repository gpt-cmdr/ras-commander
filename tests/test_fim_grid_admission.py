"""Native layout admission, metadata binding and mixed-route failure contracts."""
import copy
import inspect
import json
import math
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio

from ras_commander.fim import RasFim, FimPreparedCoupledModel, FimMappingError, FimUnsupportedError
from ras_commander.fim import _coupled, _native_grid, _engine
from test_fim_coupled import files, one_d_files, _prep_environment, _complete_engine  # noqa: F401
from test_fim_coupled_native_grid import _grid


def _write_terrain(path, grid):
    with rasterio.open(path, 'w', driver='GTiff', width=grid['width'], height=grid['height'],
                       count=1, dtype='float32', crs='EPSG:6588', tiled=True,
                       blockxsize=256, blockysize=256, nodata=float('nan'),
                       transform=rasterio.Affine.from_gdal(*grid['geo_transform'])) as target:
        target.write(np.zeros((grid['height'], grid['width']), dtype='<f4'), 1)


def test_unsupported_layout_refuses_before_source_hashes_or_payload_staging(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    grid = dict(width=257, height=513, tile_size=256,
                geo_transform=[0., .1, 0., 0., 0., -.1])
    _write_terrain(files[1], grid)
    monkeypatch.setattr(_coupled, 'digest', lambda *args: pytest.fail('bulk hash before layout admission'))
    monkeypatch.setattr(_coupled, '_alignment', lambda *args: pytest.fail('payload metadata before layout admission'))
    monkeypatch.setattr(_coupled, '_stage_mesh', lambda *args: pytest.fail('payload staging before layout admission'))
    with pytest.raises(FimUnsupportedError, match='logical tile centers differ'):
        RasFim.prepare_coupled_model(*files, tmp_path/'prep', allow_unqualified=True,
                                    grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path/'prep').exists()


def test_change_during_metadata_admission_refuses_before_hashing(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    derive = _native_grid.derive
    def changed(grid):
        result = derive(grid)
        with Path(files[0]).open('ab') as source:
            source.write(b'changed during metadata inspection')
        return result
    monkeypatch.setattr(_native_grid, 'derive', changed)
    monkeypatch.setattr(_coupled, 'digest', lambda *args: pytest.fail('hash after metadata-source change'))
    with pytest.raises(FimUnsupportedError, match='changed during metadata admission'):
        RasFim.prepare_coupled_model(*files, tmp_path/'prep', allow_unqualified=True,
                                    grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path/'prep').exists()


def test_change_during_hashing_refuses_before_staging(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    digest = _coupled.digest
    def changed(path):
        value = digest(path)
        if Path(path) == files[0]:
            with files[0].open('ab') as source:
                source.write(b'changed after hash')
        return value
    monkeypatch.setattr(_coupled, 'digest', changed)
    monkeypatch.setattr(_coupled, '_alignment', lambda *args: pytest.fail('staging after hash-source change'))
    with pytest.raises(FimUnsupportedError, match='changed during source hashing'):
        RasFim.prepare_coupled_model(*files, tmp_path/'prep', allow_unqualified=True,
                                    grid_contract=_native_grid.CONTRACT)
    assert not (tmp_path/'prep').exists()


def test_byte_identical_source_touch_during_staging_is_still_refused(files, tmp_path, monkeypatch):
    _prep_environment(tmp_path, monkeypatch)
    stage = _coupled._stage_mesh
    baseline = files[0].read_bytes()
    def changed(*args):
        result = stage(*args)
        stat = files[0].stat()
        os.utime(files[0], ns=(stat.st_atime_ns, stat.st_mtime_ns+10_000_000))
        return result
    monkeypatch.setattr(_coupled, '_stage_mesh', changed)
    with pytest.raises(FimUnsupportedError, match='changed during preparation'):
        RasFim.prepare_coupled_model(*files, tmp_path/'prep', allow_unqualified=True,
                                    grid_contract=_native_grid.CONTRACT)
    assert files[0].read_bytes() == baseline
    assert not (tmp_path/'prep').exists()


def test_constant_scratch_layout_verification_has_no_memory_budget_parameter():
    assert tuple(inspect.signature(_native_grid.derive).parameters) == ('grid',)
    assert tuple(inspect.signature(_native_grid.validate).parameters) == ('record', 'grid')
    # Verification work exceeded a 1MiB artificial charge in the earlier adapter,
    # but needs constant scratch and stays well below the Rust fixed tile cap.
    grid = dict(width=8192, height=8192, tile_size=256,
                geo_transform=[0., 1., 0., 8192., 0., -1.])
    assert _native_grid.derive(grid)['output_geo_transform'] == grid['geo_transform']


def test_prepare_validate_and_map_share_layout_admission_while_render_budget_remains(files, tmp_path, monkeypatch):
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = []
    for budget in (1, 64):
        prepared.append(RasFim.prepare_coupled_model(*files, tmp_path/f'prep-{budget}',
            profiles={'p': 0}, allow_unqualified=True, grid_contract=_native_grid.CONTRACT,
            max_working_mib=budget))
    assert prepared[0].validate()['grid_contract'] == prepared[1].validate()['grid_contract']
    _complete_engine(monkeypatch, tmp_path, engine)
    with pytest.raises(FimUnsupportedError, match='planned coupled delivery/component geometry exceeds'):
        prepared[0].map_profiles(tmp_path/'too-small', bbox=(0, 0, 5, 5),
                                 allow_unqualified=True, max_working_mib=1)
    assert not (tmp_path/'too-small').exists()
    result = prepared[1].map_profiles(tmp_path/'maps', bbox=(0, 0, 5, 5),
                                      allow_unqualified=True, max_working_mib=64)
    assert result.status.tolist() == ['complete']


def test_prepared_map_checks_native_capabilities_before_payload_validation(files, tmp_path, monkeypatch):
    require_engine = _coupled._require_engine
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path/'prep', profiles={'p': 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    monkeypatch.setattr(_coupled, '_require_engine', require_engine)
    monkeypatch.setattr(_engine, 'find_engine', lambda _: engine)
    monkeypatch.setattr(RasFim, 'get_capabilities', lambda _: SimpleNamespace(methods={}, raw_record={}))
    monkeypatch.setattr(FimPreparedCoupledModel, 'validate', lambda *args: pytest.fail('payload validation before capabilities'))
    with pytest.raises(FimUnsupportedError, match='engine lacks coupled component contract'):
        prepared.map_profiles(tmp_path/'maps', allow_unqualified=True)
    assert not (tmp_path/'maps').exists()


@pytest.mark.parametrize('descriptor', [{}, {'id': 'unknown/1'}, [], False])
def test_resealed_malformed_descriptor_refuses_cleanly_before_engine(files, tmp_path, monkeypatch, descriptor):
    _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path/'prep', profiles={'p': 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    receipt = prepared.receipt
    receipt['grid_contract'] = descriptor
    path = prepared.folder/'coupled_preparation.json'
    path.write_text(json.dumps(receipt))
    forged = FimPreparedCoupledModel._from_preparation(prepared.folder, _coupled.digest(path))
    monkeypatch.setattr(_coupled, '_require_engine', lambda *args: pytest.fail('engine before malformed descriptor'))
    with pytest.raises(FimUnsupportedError, match='invalid prepared native grid descriptor'):
        forged.map_profiles(tmp_path/'maps', allow_unqualified=True)
    assert not (tmp_path/'maps').exists()


@pytest.mark.parametrize('raise_on_failure', [False, True])
def test_native_interrupt_rolls_back_completed_profile_and_preserves_original(files, tmp_path, monkeypatch, raise_on_failure):
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path/'prep', profiles={'a': 0, 'b': 1},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    _complete_engine(monkeypatch, tmp_path, engine)
    run = _engine.run_engine
    interruption = KeyboardInterrupt('native route interruption')
    def interrupted(args, what, timeout=None):
        request = json.loads(Path(args[2]).read_text())
        if args[1] == 'sloping' and request['profiles'][0]['id'] == 'b':
            raise interruption
        return run(args, what, timeout)
    monkeypatch.setattr(_engine, 'run_engine', interrupted)
    output = tmp_path/'maps'
    with pytest.raises(KeyboardInterrupt) as caught:
        prepared.map_profiles(output, bbox=(0, 0, 5, 5), allow_unqualified=True,
            max_working_mib=64, raise_on_failure=raise_on_failure)
    assert caught.value is interruption
    assert not list(output.glob('*.tif*'))
    manifest = json.loads((output/'fim_manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [row['status'] for row in manifest['profiles']] == ['failed', 'failed']


def test_native_and_legacy_nonraising_failure_manifests_have_same_row_contract(files, tmp_path, monkeypatch):
    engine = _prep_environment(tmp_path, monkeypatch)
    results = []
    for name, contract in [('legacy', None), ('native', _native_grid.CONTRACT)]:
        prepared = RasFim.prepare_coupled_model(*files, tmp_path/(name+'-prep'),
            profiles={'a': 0, 'b': 1}, allow_unqualified=True, grid_contract=contract)
        _complete_engine(monkeypatch, tmp_path, engine, fail_profile='b')
        output = tmp_path/(name+'-maps')
        manifest = prepared.map_profiles(output, bbox=(0, 0, 5, 5), allow_unqualified=True,
                                          max_working_mib=64, raise_on_failure=False)
        results.append(manifest)
        assert manifest.status.tolist() == ['failed', 'failed']
        assert not list(output.glob('*.tif*'))
        assert json.loads((output/'fim_manifest.json').read_text())['status'] == 'failed'
    assert list(results[0].columns) == list(results[1].columns)
    assert results[0][['profile', 'status', 'error']].to_dict('records') == results[1][['profile', 'status', 'error']].to_dict('records')


_FRAME_FIELDS = [('one-d-diagnostic', 'source_geo_transform'),
                 ('one-d-diagnostic', 'output_geo_transform'),
                 ('one-d-diagnostic', 'geo_transform'),
                 ('sloping', 'source_geo_transform'),
                 ('sloping', 'output_geo_transform'),
                 ('sloping', 'geo_transform'),
                 ('sloping', 'physical_ownership.geo_transform'),
                 ('coupled-diagnostic', 'geo_transform')]


@pytest.mark.parametrize('component,field', _FRAME_FIELDS)
@pytest.mark.parametrize('change', ['one_ulp', 'signed_zero'])
def test_native_report_bitwise_framing_checks_fail_atomically(files, tmp_path, monkeypatch, component, field, change):
    engine = _prep_environment(tmp_path, monkeypatch)
    prepared = RasFim.prepare_coupled_model(*files, tmp_path/'prep', profiles={'p': 0},
        allow_unqualified=True, grid_contract=_native_grid.CONTRACT)
    _complete_engine(monkeypatch, tmp_path, engine)
    run = _engine.run_engine
    def corrupt(args, what, timeout=None):
        result = run(args, what, timeout)
        if args[1] == component:
            path = Path(args[3])/'report.json'
            report = json.loads(path.read_text())
            holder = report
            keys = field.split('.')
            for key in keys[:-1]:
                holder = holder[key]
            values = holder[keys[-1]]
            if change == 'one_ulp':
                values[1] = math.nextafter(values[1], math.inf)
            else:
                assert values[2] == 0.
                values[2] = -0.0
            path.write_text(json.dumps(report))
        return result
    monkeypatch.setattr(_engine, 'run_engine', corrupt)
    output = tmp_path/'maps'
    with pytest.raises(FimMappingError, match='mismatched'):
        prepared.map_profiles(output, bbox=(0, 0, 5, 5), allow_unqualified=True, max_working_mib=64)
    assert not list(output.glob('*.tif*'))
    assert json.loads((output/'fim_manifest.json').read_text())['status'] == 'failed'


def test_shared_rust_golden_rounded_extent_window_and_centers():
    # Shared vector ID: stored-tile-grid-rounded-extent/1. Rust companion is
    # tests/stored_grid_golden.rs; all expected binary64 constants are identical.
    bits = lambda value: struct.unpack('<Q', struct.pack('<d', value))[0]
    grid = _grid()
    original = copy.deepcopy(grid)
    descriptor = _native_grid.derive(grid)
    gt = descriptor['output_geo_transform']
    assert grid == original
    assert list(map(bits, gt)) == [0x412e848000000000, 0x3ff1999999999800, 0,
                                   0x416312d000000000, 0, 0xbff1999999999800]
    window = [255, 255, 257, 1]
    transform = rasterio.windows.transform(rasterio.windows.Window(*window), rasterio.Affine.from_gdal(*gt))
    assert list(map(bits, transform.to_gdal())) == [0x412e86b100000000, 0x3ff1999999999800, 0,
                                                   0x416312acf0000000, 0, 0xbff1999999999800]
    for row, col, expected in [(0, 0, [0x412e84811999999a, 0x416312cfee666666]),
                               (0, 255, [0x412e86b219999999, 0x416312cfee666666]),
                               (0, 256, [0x412e86b44ccccccd, 0x416312cfee666666]),
                               (255, 511, [0x412e88e54ccccccc, 0x416312acde666666])]:
        assert [bits(gt[0]+gt[1]*(col+.5)), bits(gt[3]-gt[1]*(row+.5))] == expected
