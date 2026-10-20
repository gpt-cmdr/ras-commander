"""PERF-2 read contracts on immutable real fixtures (copies for mutation tests)."""
import h5py
import numpy as np
import pytest

import json
import os
import shutil
from pathlib import Path

BASE='Results/Unsteady/Output/Output Blocks/Base Output'
@pytest.fixture
def fixture(tmp_path):
    manifest=os.environ.get('RAS_FIM_WAVE1_FIXTURES')
    if not manifest:pytest.skip('RAS_FIM_WAVE1_FIXTURES required for real PERF-2 cases')
    source=next(Path(x['path']) for x in json.loads(Path(manifest).read_text()) if 'Austin' in x['path'])
    path=tmp_path/source.name
    shutil.copy2(source,path)
    yield path
    from ras_commander.fast_hdf import close_sessions
    close_sessions()

def dataset(f):
    return f[f'{BASE}/Unsteady Time Series/2D Flow Areas/Perimeter 1/Water Surface']

def exact(a,b):
    assert a.dtype==b.dtype and a.shape==b.shape and a.tobytes()==b.tobytes()

def test_values_only_and_cache_controls(fixture):
    import ras_commander_fast_hdf as native
    with h5py.File(fixture) as f, native.HdfSession(fixture,cache_bytes=32768,cache_slots=7) as s:
        ds=dataset(f); area=ds.name.split('/')[-2]
        root=f[f'{BASE}/Summary Output/2D Flow Areas/{area}']
        ds=root['Maximum Water Surface']
        exact(s.read_mesh_summary_values(area,ds.name.split('/')[-1]),ds[()])
        for budget in [1,16]:
            for method in [s.read_mesh_summary,s.read_mesh_summary_values]:
                with pytest.raises(Exception) as e:method(area,ds.name.split('/')[-1],max_bytes=budget)
                assert e.value.engine_code=='resource_limit'
        name=dataset(f).name
        before=s.cache_stats()
        exact(s.read_numeric(name),f[name][()])
        after=s.cache_stats()
        assert before==after  # entire dataset exceeds the configured retention limit
        assert after['max_bytes']==32768 and after['max_slots']==7
    with pytest.raises(Exception):native.HdfSession(fixture,cache_slots=0)

def test_bc_batch_named_all_and_public_route(fixture):
    import ras_commander_fast_hdf as native
    from ras_commander import fast_hdf as fast
    with h5py.File(fixture) as f, native.HdfSession(fixture) as s:
        area=dataset(f).name.split('/')[-2]
        root=f[f'{BASE}/Unsteady Time Series/2D Flow Areas/{area}/Boundary Conditions']
        names=list(root)
        assert names, 'real fixture must have BC lines'
        nr=next(iter(root.values())).shape[0]
        for subset in [None,names[:2],list(reversed(names[:2]))]:
            actual=s.read_mesh_boundary_batch(area,(1,nr,3),subset)
            assert list(actual)==(names if subset is None else subset)
            for name,r in actual.items():exact(r['values'],root[name][1:nr:3])
        paths=[root[name].name for name in names]
        actual=fast.read_datasets(f,paths,backend='rust')
        assert list(actual)==paths
        for path in paths:exact(actual[path],f[path][()])
        with pytest.raises(Exception) as e:s.read_mesh_boundary_batch(area,(0,nr,1),max_bytes=1)
        assert e.value.engine_code=='resource_limit'
        with pytest.raises(Exception) as e:s.read_mesh_boundary_batch(area,(0,nr,1),['absent'])
        assert e.value.engine_kind=='not_found'


def test_requested_bc_does_not_decode_corrupt_sibling(fixture):
    import ras_commander_fast_hdf as native
    with h5py.File(fixture) as f:
        area=dataset(f).name.split('/')[-2]
        root=f[f'{BASE}/Unsteady Time Series/2D Flow Areas/{area}/Boundary Conditions']
        names=list(root)
        name=names[0]
        expected=root[name][()]
        address=h5py.h5o.get_info(root[names[-1]].id).addr
    with fixture.open('r+b') as stream:
        stream.seek(address);stream.write(b'BAD!')
    with native.HdfSession(fixture) as s:
        exact(s.read_mesh_boundary_series(area,name,(0,len(expected),1))['values'],expected)
        exact(s.read_mesh_boundary_batch(area,(0,len(expected),1),[name])[name]['values'],expected)
        with pytest.raises(Exception) as error:s.mesh_boundary_inventory(area)
        assert error.value.engine_kind=='corrupt'
