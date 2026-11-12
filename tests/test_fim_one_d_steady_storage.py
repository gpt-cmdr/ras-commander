"""Explicit stored steady axes and storage integration admission."""
import h5py
import numpy as np
import pytest
from ras_commander import HdfXsec, fast_hdf
from ras_commander.fim import RasFim, FimUnsupportedError
from ras_commander.fim._one_d import normalize_segment
from test_fim_one_d import files, inputs

BASE = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/'

@pytest.fixture
def steady(files):
    hdf, terrain = files
    with h5py.File(hdf, 'a') as f:
        attrs = f['Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/Cross Section Attributes'][()]
        del f['Results/Unsteady']
        f.create_dataset('Results/Steady/Output/Geometry Info/Cross Section Attributes', data=attrs)
        f.create_dataset(BASE+'Profile Names', data=np.array([b'Low flow', b'High flow']))
        f.create_dataset(BASE+'Cross Sections/Water Surface', data=np.array([[5, 10], [10, 20]], dtype='f4'))
    return hdf, terrain


def test_explicit_names_indices_reuse_and_no_max(steady, tmp_path):
    hdf, terrain = steady
    data = HdfXsec.get_one_d_mapping_inputs(hdf, profiles=['High flow', 0, 'High flow'])
    assert data['result_kind'] == 'steady'
    assert data['stored_profile_names'] == ['Low flow', 'High flow']
    assert [row.tolist() for row in data['levels']] == [[10, 20], [5, 10], [10, 20]]
    with pytest.raises(ValueError, match='explicit stored steady'):
        HdfXsec.get_one_d_mapping_inputs(hdf)
    prepared = RasFim.prepare_one_d_model(hdf, terrain, tmp_path/'prep', profiles={'high':'High flow','low':0}, allow_unqualified=True)
    assert prepared.validate()['result_kind'] == 'steady'
    with pytest.raises(FimUnsupportedError, match='unqualified'):
        RasFim.prepare_one_d_model(hdf, terrain, tmp_path/'refused', profiles=[0])


def test_steady_admission_identity_and_encroachment(steady, tmp_path):
    hdf, terrain = steady
    with pytest.raises(ValueError, match='admission'):
        HdfXsec.get_one_d_mapping_inputs(hdf, profiles=[0], max_bytes=1)
    with h5py.File(hdf, 'a') as f:
        f.create_dataset(BASE+'Cross Sections/Additional Variables/Encroachment Station Left', data=[[0,0],[0,0]])
    with pytest.raises(FimUnsupportedError, match='unsupported'):
        RasFim.prepare_one_d_model(hdf, terrain, tmp_path/'refused', profiles=[0], allow_unqualified=True)
    assert not (tmp_path/'refused').exists()
    with h5py.File(hdf, 'a') as f:
        ds=f['Results/Steady/Output/Geometry Info/Cross Section Attributes']; a=ds[()]; a['Station'][0]=b'wrong'; ds[:]=a
    with pytest.raises(ValueError, match='identity/order'):
        HdfXsec.get_one_d_mapping_inputs(hdf, profiles=[0])


def test_native_nearest_anchor_first_tie():
    p = inputs()['TIN Points'].copy()
    p[:,3] = np.tile([-.8, .2, .8], 2)
    actual, offsets = normalize_segment(p)
    assert offsets == pytest.approx([-.6, -.6])
    # An equally near center arriving later must not replace the first point.
    extra = p[[1,4]].copy(); extra[:,0] = 70; extra[:,3] = -.2
    result, tied = normalize_segment(np.concatenate([p,extra]))
    np.testing.assert_array_equal(actual, result[:len(p)])
    assert offsets == tied


def test_steady_auto_and_required_reader_failure(steady, monkeypatch):
    from types import SimpleNamespace
    hdf,_=steady
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF','python')
    expected=HdfXsec.get_one_d_mapping_inputs(hdf,profiles=[1])['levels'][0]
    def broken(*a,**k): raise RuntimeError('injected steady native failure')
    monkeypatch.setattr(fast_hdf,'_native',lambda mode: None if mode=='python' else SimpleNamespace(read_xs_geometry=broken))
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF','auto')
    np.testing.assert_array_equal(HdfXsec.get_one_d_mapping_inputs(hdf,profiles=[1])['levels'][0],expected)
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF','required')
    with pytest.raises(fast_hdf.FastHdfError): HdfXsec.get_one_d_mapping_inputs(hdf,profiles=[1])

@pytest.fixture
def steady_storage(steady):
    import os
    from pathlib import Path
    import rasterio
    hdf,terrain=steady
    with h5py.File(hdf,'a') as f:
        group=f.create_group('Geometry/Storage Areas')
        group.create_dataset('Attributes',data=np.array([(b'Pool',)],dtype=[('Name','S16')]))
        group.create_dataset('Polygon Info',data=[[0,5,0,1]])
        group.create_dataset('Polygon Parts',data=[[0,5]])
        group.create_dataset('Polygon Points',data=[[0.,0.],[50.,0.],[50.,100.],[0.,100.],[0.,0.]])
        sg=f.create_group(BASE+'Storage Areas')
        sg.create_dataset('Water Surface',data=np.array([[0.],[30.]],dtype='f4'))
        ds=sg.create_dataset('Pool/Storage Area Variables',data=np.array([[0.],[30.]],dtype='f4'))
        ds.attrs['Variable_Unit']=np.array([[b'Stage',b'ft']],dtype='S8')
    return hdf, terrain


def test_steady_storage_canonical_dry_suppression_and_hashes(steady_storage, tmp_path):
    import os
    from pathlib import Path
    import rasterio
    engine = os.environ.get('RAS_COMMANDER_STORAGE_ENGINE')
    if not engine:
        pytest.skip('set RAS_COMMANDER_STORAGE_ENGINE to exercise storage CLI')
    hdf, terrain = steady_storage
    p=RasFim.prepare_one_d_model(hdf,terrain,tmp_path/'prep',profiles={'dry':0,'wet':'High flow'},allow_unqualified=True)
    rows=p.map_profiles(tmp_path/'out',profiles=['dry'],allow_unqualified=True,engine_path=engine,bbox=(0,0,100,100),max_working_mib=64)
    assert rows.attrs['method_id'] == 'one-d-two-d-storage-coverage-first-diagnostic/1'
    assert rows.attrs['request_schema'] == 'fast-map-coupled-diagnostic/2'
    assert rows.attrs['method_record']['method_id'] == rows.attrs['method_id']
    assert rows.attrs['component_contracts']['xs']['method_id'] == 'one-d-xs-surface-diagnostic/5'
    with rasterio.open(rows.iloc[0].wse_tif) as source:
        values=source.read(1,masked=True)
        assert np.ma.getmaskarray(values)[:,:50].all()
        assert (~np.ma.getmaskarray(values)[:,50:]).any()
    receipt=p.validate()
    Path(receipt['storage']['levels'][0]).write_bytes(b'changed')
    with pytest.raises(FimUnsupportedError,match='storage profile byte count|changed'):
        p.validate()


@pytest.mark.parametrize('axis', ['vlen', 'matrix', 'numeric'])
def test_unsupported_steady_axis_is_not_read(steady, monkeypatch, axis):
    import importlib
    module = importlib.import_module('ras_commander.hdf.HdfXsec')
    hdf, _ = steady
    path = BASE + 'Profile Names'
    with h5py.File(hdf, 'a') as source:
        del source[path]
        if axis == 'vlen':
            source.create_dataset(path, data=['Low flow', 'High flow'], dtype=h5py.string_dtype())
        else:
            source.create_dataset(path, data=np.array([[b'Low', b'High']]) if axis == 'matrix' else [1, 2])
    original = module.read_typed
    def read(dataset, *args, **kwargs):
        assert dataset.name.lstrip('/') != path, 'unsupported axis was read'
        return original(dataset, *args, **kwargs)
    monkeypatch.setattr(module, 'read_typed', read)
    with pytest.raises(ValueError, match='one-dimensional string axis'):
        HdfXsec.get_one_d_mapping_inputs(hdf, profiles=[0])


def test_ambiguous_result_regime_refuses_before_selection(steady):
    hdf, _ = steady
    with h5py.File(hdf, 'a') as source:
        source.create_group('Results/Unsteady')
    with pytest.raises(ValueError, match='ambiguous'):
        HdfXsec.get_one_d_mapping_inputs(hdf, profiles=[0])
    from ras_commander.fim import _storage_areas
    with pytest.raises(FimUnsupportedError, match='ambiguous'):
        _storage_areas.profile_values(hdf, None, {'profile': 0})


def test_mismatched_composition_report_cannot_publish(steady_storage, tmp_path, monkeypatch):
    import json
    import os
    from pathlib import Path
    from ras_commander.fim import _engine, FimMappingError
    engine = os.environ.get('RAS_COMMANDER_STORAGE_ENGINE')
    if not engine:
        pytest.skip('set RAS_COMMANDER_STORAGE_ENGINE to exercise storage CLI')
    from ras_commander.fim import _one_d
    monkeypatch.setattr(_one_d, '_inline_storage', lambda flags: False)  # separate composition call
    original = _engine.run_engine
    def run(args, *other, **kwargs):
        result = original(args, *other, **kwargs)
        if args[1] == 'coupled-diagnostic':
            path = Path(args[3]) / 'report.json'
            report = json.loads(path.read_text())
            report['method']['method_id'] = 'wrong-composition/1'
            path.write_text(json.dumps(report))
        return result
    monkeypatch.setattr(_engine, 'run_engine', run)
    output = tmp_path / 'out'
    with pytest.raises(FimMappingError, match='mismatched composition'):
        RasFim.map_one_d_profiles(*steady_storage, output, profiles={'dry': 0},
                                 allow_unqualified=True, engine_path=engine,
                                 bbox=(0, 0, 100, 100), max_working_mib=64)
    assert not list(output.glob('*.tif'))
    assert json.loads((output/'fim_manifest.json').read_text())['status'] == 'failed'


def _storage_engine_inline(final_format=None):
    import os
    from ras_commander.fim import _one_d
    engine = os.environ.get('RAS_COMMANDER_STORAGE_ENGINE')
    if not engine:
        pytest.skip('set RAS_COMMANDER_STORAGE_ENGINE to exercise storage CLI')
    flags = RasFim.get_capabilities(engine).methods['one_d_clipped_diagnostic'].flags
    if not _one_d._inline_storage(flags):
        pytest.skip('engine lacks inline_storage')
    if final_format is not None and 'native_final_format' not in flags:
        pytest.skip('engine lacks 1D native_final_format')
    return engine


@pytest.mark.parametrize('final_format', [None, {'nodata': -9999.0, 'block_size': 16}])
def test_inline_storage_matches_separate_composition_bits(steady_storage, tmp_path, monkeypatch, final_format):
    import rasterio
    from ras_commander.fim import _one_d
    engine = _storage_engine_inline(final_format)
    hdf, terrain = steady_storage
    prepared = RasFim.prepare_one_d_model(hdf, terrain, tmp_path / 'prep', profiles={'dry': 0, 'wet': 'High flow'},
                                          allow_unqualified=True)
    kwargs = dict(profiles=['dry', 'wet'], allow_unqualified=True, engine_path=engine,
                  bbox=(0, 0, 100, 100), max_working_mib=64, threads=3)
    inline = prepared.map_profiles(tmp_path / 'inline', final_format=final_format, **kwargs)
    assert inline.attrs['storage_inline'] is True
    assert inline.attrs['method_id'] == 'one-d-two-d-storage-coverage-first-diagnostic/1'
    monkeypatch.setattr(_one_d, '_inline_storage', lambda flags: False)
    separate = prepared.map_profiles(tmp_path / 'separate', **kwargs)
    assert separate.attrs['storage_inline'] is False
    for a, b in zip(inline.itertuples(), separate.itertuples()):
        assert (a.depth_finite_pixels, a.flooded_pixels) == (b.depth_finite_pixels, b.flooded_pixels)
        for column in ('depth_tif', 'wse_tif'):
            with rasterio.open(getattr(a, column)) as x, rasterio.open(getattr(b, column)) as y:
                got, expected = x.read(1), y.read(1)
                valid = ~np.isnan(expected)
                missing = np.isnan(got) if final_format is None else got == final_format['nodata']
                assert np.array_equal(missing, ~valid)
                np.testing.assert_array_equal(got[valid].view('<u4'), expected[valid].view('<u4'))


def _corrupt_composition(top, profiles):
    for report in profiles or [top]:
        report['composition']['method']['method_id'] = 'wrong-composition/1'
    return len(profiles or [top])


def _corrupt_summary(top, profiles):
    if not profiles:
        pytest.skip('engine lacks multi_profile summaries')
    top['profiles'][0]['levels_file'] += '.other'
    return 1


def _corrupt_grid(top, profiles):
    for report in profiles or [top]:
        report['geo_transform'][0] += 1.0
    return len(profiles or [top])


@pytest.mark.parametrize('corrupt,message', [
    (_corrupt_composition, 'inline storage composition'),
    (_corrupt_summary, 'profile summary does not match'),
    (_corrupt_grid, 'grid differs from the request window')])
def test_inline_storage_report_mismatch_cannot_publish(steady_storage, tmp_path, monkeypatch, corrupt, message):
    """Each inline-storage report check is exercised on the engine's actual report layout."""
    import json
    from pathlib import Path
    from ras_commander.fim import _engine, FimMappingError
    engine = _storage_engine_inline()
    original = _engine.run_engine
    corrupted = []
    def run(args, *other, **kwargs):
        result = original(args, *other, **kwargs)
        if args[1] == 'one-d-diagnostic' and result.returncode == 0:
            out = Path(args[3])
            top = json.loads((out / 'report.json').read_text())
            paths = sorted(out.glob('profile-*/report.json'))
            profiles = [json.loads(path.read_text()) for path in paths]
            corrupted.append(corrupt(top, profiles))
            (out / 'report.json').write_text(json.dumps(top))
            for path, report in zip(paths, profiles):
                path.write_text(json.dumps(report))
        return result
    monkeypatch.setattr(_engine, 'run_engine', run)
    output = tmp_path / 'out'
    with pytest.raises(FimMappingError, match=message):
        RasFim.map_one_d_profiles(*steady_storage, output, profiles={'dry': 0},
                                 allow_unqualified=True, engine_path=engine,
                                 bbox=(0, 0, 100, 100), max_working_mib=64)
    assert corrupted and all(corrupted), 'no engine report was altered'
    assert not list(output.glob('*.tif'))
