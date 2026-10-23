"""Frozen engine fixtures plus independent h5py values; real validation is owner-gated."""
from pathlib import Path
import hashlib,json,os
import h5py,numpy as np,pytest
from bridge_test import native
ROOT=Path(__file__).with_name('fixtures')/'structures'
FAMILIES=['sa_2d_area_connection','lateral_structure','storage_area']

def check(native,path):
    plan=native.plan_capabilities(path)
    assert {'structures','reference_lines','reference_points','boundary_conditions','calibration_regions'} <= {f['family'] for f in plan['families']}
    assert {s['family'] for s in plan['structures']}==set(FAMILIES)
    for family in FAMILIES:
        inv=native.structure_inventory(path,family)
        assert inv['capability']['status']=='supported' and inv['time_rows']==4
        with h5py.File(path) as f:
            for desc in inv['structures']:
                assert desc['identity']['row']>=0 and desc['node_pointer']['capability']['status'] in ('supported','unavailable')
                for series in desc['series']:
                    if series['capability']['status']!='supported':continue
                    data=f[series['path']][:]
                    for threads in (1,4):
                        out=native.read_structure_series(path,family,desc['name'],series['relative'],(0,4,2),(0,data.shape[1],1),threads=threads)
                        assert out.dtype==data.dtype and out.shape==data[::2].shape and out.tobytes()==data[::2].tobytes()
                    with pytest.raises(ValueError):native.read_structure_series(path,family,desc['name'],series['relative'],(0,4,1),(0,data.shape[1],1),max_bytes=1)
            for series in inv['family_series']:
                data=f[series['path']][:]
                out=native.read_structure_series(path,family,None,series['relative'],(0,4,1),(0,data.shape[1],1))
                assert out.dtype==data.dtype and out.tobytes()==data.tobytes()
    with pytest.raises(ValueError):native.structure_inventory(path,'unknown')

def test_structure_inventory_and_exact_series(native):
    manifest=json.loads((ROOT/'manifest.json').read_text())['fixtures'];p=ROOT/'good.h5'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['good']['sha256'];check(native,p)

def test_structure_corruption_and_labels(native):
    with pytest.raises(native.CorruptDataError):native.structure_inventory(ROOT/'row_count_vs_time_axis.h5','lateral_structure')
    inv=native.structure_inventory(ROOT/'label_count_mismatch.h5','lateral_structure')
    assert inv['diagnostics'] and inv['diagnostics'][0]['capability']['status']=='corrupt'
    with pytest.raises(ValueError):native.read_structure_series(ROOT/'good.h5','lateral_structure','R1 Reach1 100','../Flow',(0,4,1),(0,1,1))

def test_api4_audit_contract(native):
    import inspect
    import runpy
    EXPECTED=runpy.run_path(str(Path(__file__).parents[1]/'rust_consumer_contract/expected.py'))['EXPECTED']
    names=set(native.capabilities()['bindings'])
    assert names=={n for n,(_,gate,_) in EXPECTED.items() if gate is None or hasattr(native,n)}
    for name in ['structure_inventory','read_structure_series','unsteady_time_axis','unsteady_row_times','cross_sections','read_cross_section_result']:
        assert inspect.signature(getattr(native,name)).parameters['max_bytes'].default==64<<20
    assert inspect.signature(native.read_structure_series).parameters['threads'].default is None
    p=ROOT/'good.h5'
    inv=native.structure_inventory(p,'lateral_structure')
    s=inv['structures'][0]['series'][0]
    assert s['dataset_path']==s['path'] and np.dtype(s['dtype']).kind=='f'
    assert s['kind'] in ('f32','f64')
    for d in inv['structures']:
        for item in d['series']:
            c=item['columns']
            if c['capability']['status']=='supported':assert c['value']['source_attribute'] in ('Variable_Unit','Connections')
    cap=native.numeric_capability(p,s['path']);assert cap['dataset_path']==cap['dataset']
    for t in [0,1025]:
        with pytest.raises(ValueError):native.read_structure_series(p,'lateral_structure',inv['structures'][0]['name'],s['relative'],(0,4,1),(0,s['shape'][1],1),threads=t)
    for d in native.structure_inventory(ROOT/'label_count_mismatch.h5','lateral_structure')['diagnostics']:
        assert {'subject','message','capability'}<=d.keys()
    for family in native.plan_capabilities(ROOT/'label_count_mismatch.h5')['structures']:
        for d in family['diagnostics']:assert {'subject','message','capability'}==d.keys()
