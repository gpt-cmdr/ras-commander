"""Engine-owned frozen time/units/inventory inputs, independently expected by manifest/h5py."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from bridge_test import native

ROOT=Path(__file__).with_name('fixtures')/'wave3'
MANIFEST=json.loads((ROOT/'manifest.json').read_text())['fixtures']
BASE='Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'

def fixture(name):
    e=MANIFEST[name];p=ROOT/e['file']
    assert hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256']
    return p,e.get('expect',{})

@pytest.mark.parametrize('name',['rollover_2400_with_ms','ms_strings_subsecond_with_stamps','ms_only','days_only'])
def test_time_axis_and_selection(native,name):
    p,e=fixture(name);a=native.unsteady_time_axis(p)
    assert a['raw_strings']==e.get('strings')
    assert a['raw_ms_strings']==e.get('ms_strings')
    assert a['raw_ms']==e.get('raw_ms')
    assert a['ms_since_epoch']==e.get('ms')
    assert a['hour_2400_rows']==e.get('hour_2400_rows',[])
    assert a['timezone'] is None and a['epoch']=='civil_unix_1970'
    if a['raw_ms'] is not None:assert a['integer_ms']['status']=='unsupported'
    if a['timestamps'] is not None:
        for text,ms in zip(a['timestamps'],a['ms_since_epoch']):
            dt=datetime.fromisoformat(text)
            assert dt.tzinfo is None
            delta=dt-datetime(1970,1,1)
            assert delta.days*86400000+delta.seconds*1000+delta.microseconds//1000==ms
        assert a['capability']['status']=='supported'
    else:assert a['capability']['status']=='unsupported'
    r=native.unsteady_row_times(p,(0,a['rows'],2))
    idx=list(range(0,a['rows'],2));assert r['row_indices']==idx
    for key in ['raw_strings','raw_ms','raw_ms_strings','ms_since_epoch','timestamps','days']:
        assert r[key]==([a[key][i] for i in idx] if a[key] is not None else None)
    assert r['hour_2400_rows']==[i for i in a['hour_2400_rows'] if i in idx]
    with pytest.raises(ValueError):native.unsteady_row_times(p,(0,a['rows'],0))

@pytest.mark.parametrize('name,exception',[('ms_strings_bad_value','CorruptDataError'),('ms_strings_bad_width','UnsupportedError')])
def test_time_refusal(native,name,exception):
    p,_=fixture(name)
    with pytest.raises(getattr(native,exception)):native.unsteady_time_axis(p)

@pytest.mark.parametrize('name',['units_full','units_real_layouts'])
def test_units_raw_provenance(native,name):
    p,_=fixture(name);report=native.result_units(p)
    assert report['variables'] and report['unit_system']
    with h5py.File(p) as f:
        for v in report['variables']:
            e=native.dataset_unit_evidence(p,v['dataset']);assert e==v['units']
            assert e['status'] in {'declared','absent','unsupported','corrupt'}
            if e['status']=='declared':
                raw=f[v['dataset']].attrs[e['source_attribute']]
                assert e['raw_bytes']==np.asarray(raw).tobytes()
                if e['source_attribute']=='Variable':raw=raw[1]
                encoding=h5py.check_string_dtype(f[v['dataset']].attrs.get_id(e['source_attribute']).dtype).encoding
                expected=raw.decode(encoding) if isinstance(raw,bytes) else str(raw)
                assert e['text']==expected
            else:assert e['text'] is None
    flow=native.dataset_unit_evidence(p,BASE+'/Cross Sections/Flow')
    assert flow['source_attribute'] in {'Units','Variable Units'}

@pytest.mark.parametrize('name,issue',[('mesh-missing','missing_group'),('mesh-extra','extra_group'),('mesh-duplicate','duplicate_attribute_name')])
def test_typed_name_diagnostics(native,name,issue):
    p,_=fixture(name);d=native.mesh_name_diagnostics(p)
    assert len(d)==1 and d[0]['issue']==issue
    with pytest.raises(native.CorruptDataError):native.mesh_inventory(p)

@pytest.mark.parametrize('name,mode,expected_count',[('mesh-blocks','unsteady',2),('mesh-steady','steady',1)])
def test_output_block_binding(native,name,mode,expected_count):
    p,_=fixture(name);assert native.mesh_name_diagnostics(p)==[]
    m=native.mesh_inventory(p)[0]
    blocks=[b for b in m['output_blocks'] if b['mode']==mode]
    assert len(blocks)==expected_count
    assert all(b['results']['capability']['status']=='supported' for b in blocks)
    assert all(b['dataset_root'].endswith('/2D Flow Areas/A') for b in blocks)

def test_temporal_chunk_shape_stays_exact(native,tmp_path):
    for chunks in [None,(2,3)]:
        p=tmp_path/('chunked.h5' if chunks else 'contiguous.h5')
        with h5py.File(p,'w') as f:f.create_dataset('v',data=np.arange(12,dtype='f8').reshape(4,3),chunks=chunks)
        r=native.temporal_reduce(p,'v',threads=1)
        assert r['chunk_shape']==(list(chunks) if chunks else None)
        np.testing.assert_array_equal(r['maximum'],[9,10,11])
