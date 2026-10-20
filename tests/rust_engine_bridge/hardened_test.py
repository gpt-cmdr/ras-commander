"""Bridge conversion contracts, with native tests skipped only when extension is absent."""
import json
import logging
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
from bridge_test import native, PIN, DEP

FIXTURES = Path(__file__).with_name('fixtures')


def test_python_backend_metadata(tmp_path):
    from ras_commander.fast_results import temporal_reduce
    path = tmp_path / 'values.h5'
    with h5py.File(path, 'w') as f:
        f.create_dataset('values', data=np.arange(30, dtype='f8').reshape(6, 5), chunks=(2, 5))
    with h5py.File(path) as f:
        r = temporal_reduce(f['values'], backend='python', max_block_bytes=80, parallel=False)
    np.testing.assert_array_equal(r.maximum, np.arange(25, 30, dtype='f4'))
    assert set(r.timings) == {'setup_seconds','read_seconds','reduce_seconds','engine_seconds'}
    assert np.isfinite(r.timings['engine_seconds'])
    assert all(np.isnan(r.timings[k]) for k in ['setup_seconds','read_seconds','reduce_seconds'])
    assert r.read_plan['timing_scope'].startswith('python read+reduce')
    assert r.read_plan['chunk_shape'] == [2, 5]
    assert r.read_plan['blocks'] == 3 and r.read_plan['block_bytes'] == 80


def test_log_call_does_not_format_arguments(caplog):
    from ras_commander.Decorators import log_call
    class Dangerous:
        def __repr__(self):
            raise AssertionError('array-like argument formatted')
    @log_call
    def operation(value):
        return value
    with caplog.at_level(logging.DEBUG):
        value = Dangerous()
        assert operation(value) is value
    messages = [r.getMessage() for r in caplog.records if r.name == operation.__module__]
    assert "Calling operation" in messages and "Finished operation" in messages


def test_capability_exports(native):
    c = native.capabilities()
    assert c['engine_commit'] == PIN and c['api_version'] == 8
    assert c['engine_features'] == DEP['features']
    assert 'mesh_inventory' in c['bindings']


def test_typed_metadata_and_crs(native):
    attrs = {a['name']:a for a in native.typed_group_attributes(FIXTURES/'tolerant.h5')}
    assert attrs['bad']['capability']['status'] == 'corrupt'
    assert attrs['Projection']['value'] == ['PROJCS["x"]']
    assert attrs['Projection']['attribute_type']['kind'] == 'fixed_string'
    assert isinstance(attrs['Projection']['raw_bytes'], bytes)
    crs = native.raw_crs_evidence(FIXTURES/'tolerant.h5')
    assert crs['kind'] == 'unvalidated'
    assert crs['evidence'][0]['exact_wkt'] == 'PROJCS["x"]'
    assert crs['hydraulic_units_evidence'][0]['capability']['status'] == 'unsupported'
    bad = native.raw_crs_evidence(FIXTURES/'corrupt-projection.h5')
    assert bad['kind'] == 'corrupt' and bad['evidence'][0]['raw_bytes']


@pytest.mark.parametrize('kind', ['steady','unsteady'])
def test_one_d_bindings(native, kind):
    path = FIXTURES/(kind+'.h5')
    assert native.plan_result_mode(path) == kind
    geometry = native.cross_sections(path)
    assert len(geometry['sections']) == 2
    assert geometry['sections'][0]['river']
    if kind == 'steady':
        assert len(native.steady_profile_names(path)) == 2
    report = native.plan_capabilities(path)
    assert report['mode'] == kind
    family = 'steady_profiles' if kind == 'steady' else 'cross_sections_unsteady'
    assert next(f for f in report['families'] if f['family']==family)['capability']['status']=='supported'
    prefix = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles' if kind=='steady' else 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'
    with h5py.File(path) as f:
        expected = f[prefix+'/Cross Sections/Flow'][:]
    for threads in [1,4]:
        a = native.read_cross_section_result(path,kind,'Flow',(0,len(expected),1),(0,2,1),threads=threads,parallel=False)
        assert a.dtype == expected.dtype
        np.testing.assert_array_equal(a, expected)
    with pytest.raises(ValueError):
        native.read_cross_section_result(path,kind,'Flow',(0,len(expected),1),(0,2,1),max_bytes=1)


def test_mesh_inventory_and_unavailable(native, tmp_path):
    path = tmp_path/'mesh.h5'
    with h5py.File(path,'w') as f:
        g=f.create_group('Geometry/2D Flow Areas')
        g['Attributes']=np.array([(b'A',2)],dtype=[('Name','S8'),('Cell Count','<i4')])
        g['A/Cells Center Coordinate']=np.zeros((3,2),dtype='f8')
    m=native.mesh_inventory(path)[0]
    assert (m['physical_cells'],m['stored_cells'],m['ghost_cells'])==(2,3,1)
    assert m['results']['capability']['status']=='unavailable'


def test_error_subclasses_and_path(native,tmp_path):
    path=tmp_path/'missing.h5'
    with pytest.raises(FileNotFoundError) as exc:
        native.read_numeric(path,'x')
    assert exc.value.filename == str(path)
    path.write_bytes(b'broken')
    with pytest.raises(native.CorruptDataError):
        native.read_numeric(path,'x')
    assert issubclass(native.CorruptDataError,ValueError)
    assert issubclass(native.TopologyError,ValueError)


def test_backend_metadata_parity(native,tmp_path):
    from ras_commander.fast_results import temporal_reduce
    path=tmp_path/'values.h5'
    with h5py.File(path,'w') as f:f['v']=np.arange(30,dtype='f8').reshape(6,5)
    with h5py.File(path) as f:
        py=temporal_reduce(f['v'],backend='python',max_block_bytes=80)
        rust=temporal_reduce(f['v'],backend='rust',max_block_bytes=80,parallel=False)
    assert py.timings.keys()==rust.timings.keys()
    assert py.read_plan.keys()==rust.read_plan.keys()
    np.testing.assert_array_equal(py.maximum,rust.maximum)
    np.testing.assert_array_equal(py.peak_index,rust.peak_index)
    np.testing.assert_array_equal(py.finite_count,rust.finite_count)
    for key in ["block_rows", "blocks", "block_bytes"]:
        assert py.read_plan[key] == rust.read_plan[key]


@pytest.mark.skipif(not os.environ.get('RAS_1D_UNSTEADY_FIXTURE'),reason='real computed 1D fixture owner gate')
def test_real_unsteady(native):
    path=Path(os.environ['RAS_1D_UNSTEADY_FIXTURE'])
    assert native.plan_result_mode(path)=='unsteady'
    assert len(native.cross_sections(path)['sections'])==1769
    a=native.read_cross_section_result(path,'unsteady','Flow',(0,193,24),(0,1769,97),threads=4)
    with h5py.File(path) as f:
        expected=f['Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/Flow'][0:193:24,0:1769:97]
    np.testing.assert_array_equal(a,expected)


@pytest.mark.skipif(not os.environ.get('RAS_NATIVE_FIXTURES'),reason='real fixture owner gate')
def test_real_metadata(native):
    root=Path(os.environ['RAS_NATIVE_FIXTURES'])
    files=list(root.rglob('*.hdf'))
    assert files, 'configured fixture root contains no HDF files'
    for path in files[:3]:
        assert isinstance(native.typed_group_attributes(path),list)
        assert native.raw_crs_evidence(path)['kind'] in {'unknown','unvalidated','invalid','conflict','unsupported','corrupt'}

def test_vlen_projection_and_names_only_fail_closed(native,tmp_path):
    path=tmp_path/'vlen.h5'
    with h5py.File(path,'w') as f:
        f.attrs.create('Projection','PROJCS["x"]',dtype=h5py.string_dtype())
        f['Geometry/2D Flow Areas/Names']=np.array([b'A'])
    r=native.raw_crs_evidence(path)
    assert r['kind']=='unsupported'
    assert r['evidence'][0]['raw_bytes']
    with pytest.raises((KeyError,native.UnsupportedError)):
        native.mesh_inventory(path)
