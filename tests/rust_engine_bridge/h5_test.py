"""H5 engine-owned statuses, identities, budgets and numeric failure semantics."""
import hashlib,json,inspect
from pathlib import Path
import numpy as np,pytest
from bridge_test import native
ROOT=Path(__file__).with_name('fixtures')

def capabilities(value):
    if isinstance(value,dict):
        if 'capability' in value:
            c=value['capability'];assert isinstance(c,dict) and set(c)=={'status','code','reason'}
            assert c['status'] in {'supported','unavailable','unsupported','corrupt','delegated'}
        for v in value.values():capabilities(v)
    elif isinstance(value,(tuple,list)):
        for v in value:capabilities(v)

def test_engine_contract_and_evidence(native):
    c=native.capabilities();assert c['api_version']==11
    assert c['engine_api_version']==c['engine_capabilities']['api_version']==10
    # engine_features is the documented four; engine 0.3.0 release wheels (python-arrow)
    # also report 'arrow' in engine_capabilities.features (fast-hdf extension contract).
    f,base=list(c['engine_capabilities']['features']),list(c['engine_features'])
    assert f[:len(base)]==base and set(f[len(base):])<={'arrow'}
    assert any(e['owner']=='ReadOnlyHdfSession' and e['name']=='read_structure_series' for e in c['engine_capabilities']['entrypoints'])
    assert c['default_max_bytes']==64<<20
    p=ROOT/'structures/good.h5';inv=native.structure_inventory(p,'lateral_structure');capabilities(inv)
    d=inv['structures'][0];assert {'source','table','row'} <= d['identity'].keys()
    for e in [d['node_pointer'],d['series'][0]['columns'],d['series'][0]['units']]:
        assert {'kind','value','raw_bytes','capability'}<=e.keys()
        assert 'status' not in e
    xs=native.cross_sections(ROOT/'unsteady.h5')['sections'][0]
    assert {'source','table','row'}==xs['identity'].keys()
    assert {'kind','value','raw_bytes','capability'}<=xs['name'].keys()
    for f in [native.raw_crs_evidence,native.typed_group_attributes,native.result_units]:capabilities(f(p))
    assert native.structure_inventory(p,'sa2d_area_connection')['family']=='sa_2d_area_connection'
    assert inspect.signature(native.read_cross_section_result).parameters['metadata_max_bytes'].default==64<<20

def test_xs_budgets_and_time_mismatch(native):
    folder=ROOT/'h5_xs_time';manifest=json.loads((folder/'manifest.json').read_text())
    for n,h in manifest.items():assert hashlib.sha256((folder/n).read_bytes()).hexdigest()==h
    p=folder/'xs_time_ok.h5'
    family=lambda report:next(f['capability'] for f in report['families'] if f['family']=='cross_sections_unsteady')
    assert family(native.plan_capabilities(p))['status']=='supported'
    assert family(native.plan_capabilities(p,max_bytes=1))['code']=='resource_limit'
    with pytest.raises(ValueError) as err:native.read_cross_section_result(p,'unsteady','Water Surface',(0,3,1),(0,2,1),metadata_max_bytes=1)
    assert err.value.engine_kind=='invalid_request' and err.value.engine_code=='resource_limit'
    data=native.read_cross_section_result(p,'unsteady','Water Surface',(0,3,1),(0,2,1))
    assert data.dtype==np.dtype('<f4') and data.tobytes()==np.arange(6,dtype='<f4').reshape(3,2).tobytes()
    p=folder/'xs_time_mismatch.h5';assert family(native.plan_capabilities(p))['status']=='corrupt'
    with pytest.raises(native.CorruptDataError):native.read_cross_section_result(p,'unsteady','Water Surface',(0,3,1),(0,2,1))

def test_cell_diagnostic_envelope(native):
    args=[np.array([[0,0],[2,2],[0,2],[2,0]],dtype='f8'),np.array([[0,1],[1,2],[2,3],[3,0]],dtype='i8'),np.zeros((4,2),dtype='i8'),np.zeros((0,2),dtype='f8'),np.array([[0,4]],dtype='i8'),np.array([[0,0],[1,0],[2,0],[3,0]],dtype='i8')]
    for threads in (1,4):
        *_,diagnostics=native.assemble_cells(*args,threads=threads,strict=False,return_diagnostics=True)
        assert len(diagnostics)==1 and diagnostics[0]['cell_id']==0 and diagnostics[0]['kind']=='invalid_geometry'
        capabilities(diagnostics);assert diagnostics[0]['capability']['status']=='corrupt'
