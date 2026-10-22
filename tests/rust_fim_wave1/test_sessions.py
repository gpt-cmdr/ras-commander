"""Real-file lifetime/cache and buffer contracts for API7."""
import json
import os
from pathlib import Path
import shutil

import h5py
import numpy as np
import pytest

@pytest.fixture
def fixture(tmp_path):
    manifest = os.environ.get('RAS_FIM_WAVE1_FIXTURES')
    if not manifest:
        pytest.skip('Set RAS_FIM_WAVE1_FIXTURES for real-file session tests')
    source = next(Path(f['path']) for f in json.loads(Path(manifest).read_text()) if 'Austin' in f['path'])
    path = tmp_path / source.name
    shutil.copy2(source, path)
    yield path
    from ras_commander.fast_hdf import close_sessions
    close_sessions()

def dataset(f):
    root = f['Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas']
    return next(g['Water Surface'] for g in root.values() if 'Water Surface' in g)

def exact(a,b):
    assert a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()

def test_native_session_lifetime_and_numpy_ids(fixture):
    import ras_commander_fast_hdf as native
    with h5py.File(fixture,'r') as f:
        ds=dataset(f);name=ds.name;area=name.split('/')[-2]
        with native.HdfSession(fixture) as session:
            ids=np.array([2,0,2],dtype='u8')
            result=session.read_mesh_series(area,'Water Surface',(0,24,1),ids)
            assert result['elements'].dtype == np.dtype('u8')
            exact(result['elements'],ids)
            expected=ds[:24,:][:,ids]
            exact(result['values'],expected)
        assert session.closed
        session.close()  # idempotent
        with pytest.raises(ValueError,match='closed'):
            session.read_numeric(name)
        exact(result['values'],expected)  # buffer outlives closed mapping

def test_cache_reuse_invalidation_and_opt_out(fixture,monkeypatch):
    from ras_commander import fast_hdf as fast
    fast.close_sessions();monkeypatch.setenv('RAS_COMMANDER_HDF_SESSION_CACHE','1')
    with h5py.File(fixture,'r') as f:
        ds=dataset(f)
        a=fast.read_dataset(ds,(slice(0,24),slice(0,100)),backend='rust')
        first=next(iter(fast._sessions.values()))[0]
        exact(a,fast.read_dataset(ds,(slice(0,24),slice(0,100)),backend='rust'))
        assert next(iter(fast._sessions.values()))[0] is first
        st=fixture.stat();os.utime(fixture,ns=(st.st_atime_ns,st.st_mtime_ns+1_000_000))
        exact(a,fast.read_dataset(ds,(slice(0,24),slice(0,100)),backend='rust'))
        assert first.closed
        monkeypatch.setenv('RAS_COMMANDER_HDF_SESSION_CACHE','0')
        exact(a,fast.read_dataset(ds,(slice(0,24),slice(0,100)),backend='rust'))
        assert not fast._sessions

def test_bounded_cache_and_windows_file_release(fixture,tmp_path,monkeypatch):
    from ras_commander import fast_hdf as fast
    monkeypatch.setenv('RAS_COMMANDER_HDF_SESSION_CACHE','1');fast.close_sessions()
    first=None
    for i in range(5):
        p=tmp_path/f'copy-{i}.hdf';shutil.copy2(fixture,p)
        with h5py.File(p,'r') as f:fast.read_dataset(dataset(f),backend='rust')
        if i == 0:first=next(iter(fast._sessions.values()))[0]
    assert len(fast._sessions)==4 and first.closed
    fast.close_sessions(fixture)  # harmless absent key
    sessions=[v[0] for v in fast._sessions.values()]
    fast.close_sessions();assert all(s.closed for s in sessions)
    for p in tmp_path.glob('copy-*.hdf'):
        replacement=tmp_path/'replacement.hdf';shutil.copy2(fixture,replacement)
        os.replace(replacement,p);p.unlink()
    print('file-lock verification:',os.name,'replace/delete after close_sessions PASS')

def test_size_invalidation_with_unchanged_mtime(fixture,monkeypatch):
    from ras_commander import fast_hdf as fast
    fast.close_sessions();monkeypatch.setenv('RAS_COMMANDER_HDF_SESSION_CACHE','1')
    with h5py.File(fixture,'r') as f:
        expected=fast.read_dataset(dataset(f),backend='rust')
    first=next(iter(fast._sessions.values()))[0]
    st=fixture.stat()
    # Legal unused trailing bytes change file size without changing stored HDF.
    with fixture.open('ab') as f:f.write(b'cache-size-regression')
    os.utime(fixture,ns=(st.st_atime_ns,st.st_mtime_ns))
    with h5py.File(fixture,'r') as f:
        exact(expected,fast.read_dataset(dataset(f),backend='rust'))
    assert first.closed

def test_compute_plan_releases_cache_before_execution_gate(fixture,monkeypatch):
    import importlib
    from ras_commander import fast_hdf as fast
    module=importlib.import_module('ras_commander.RasCmdr')
    with h5py.File(fixture,'r') as f:fast.read_dataset(dataset(f),backend='rust')
    session=next(iter(fast._sessions.values()))[0]
    class StopBeforeExecution(Exception):pass
    def stop(_):
        assert not fast._sessions and session.closed
        raise StopBeforeExecution
    monkeypatch.setattr(module,'_require_process_supervision',stop)
    with pytest.raises(StopBeforeExecution):module.RasCmdr.compute_plan('01')
