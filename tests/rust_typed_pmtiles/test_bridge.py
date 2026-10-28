"""Independent decoded qualification of the shared typed/WKB rendering bridge."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
pa = pytest.importorskip('pyarrow')
pytest.importorskip('geopandas')
import shapely
from shapely.geometry import Polygon, MultiPolygon, box, Point, shape
from ras_commander import fast_hdf
import ras_commander
native = pytest.importorskip('ras_commander_fast_hdf')
from rust_first_tier_exports.helpers import table
from rust_export_conformance.helpers import decode

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def provenance():
    assert Path.cwd().resolve() == ROOT
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT/'ras_commander')
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    extension = sys.modules['ras_commander_fast_hdf.ras_commander_fast_hdf']
    assert Path(extension.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert Path(extension.__file__).suffix.lower() in {'.pyd', '.so'}
    assert hasattr(native, 'validate_export_wkb')
    assert hasattr(native, 'export_pmtiles_ipc_file')


def source():
    donut = Polygon(box(-77.1,40,-77,40.1).exterior.coords,
                    [box(-77.08,40.02,-77.02,40.08).exterior.coords])
    return table([donut, MultiPolygon([donut,box(-76.99,40,-76.98,40.01)])],4326,
        mesh_names=['b','a'],cell_ids=[2**53+1,2**53+1],columns={
            'signed':pa.array([-(2**53+1),2**53+1],type=pa.int64()),
            'unsigned':pa.array([2**63-1,None],type=pa.uint64()),
            'time':pa.array([32503680000123,None],type=pa.timestamp('ms')),
            'wet':pa.array([True,False]), 'value':pa.array([1.25,None]),
            'name':pa.array(['河川','basin']), 'null_int':pa.array([None,None],type=pa.int64())})


def export(output, t, **kwargs):
    return fast_hdf.export_arrow_pmtiles(output,t,source_crs=4326,min_zoom=6,max_zoom=8,
        timestamp_ms=True,max_batch_rows=1,threads=2,**kwargs)


def registry(output):
    rows=pa.ipc.open_file(output/'identities.arrow').read_all().to_pylist()
    return {(r['mesh_name'],r['cell_id']):r['export_id'] for r in rows},rows


def test_typed_holes_identity_metadata_and_reference(tmp_path):
    t=source(); before=t.combine_chunks(); output=tmp_path/'bundle'
    metrics=export(output,t)
    assert metrics['rows']==2 and metrics['batches']==2 and metrics['registry_rows']==2
    assert t.equals(before,check_metadata=True)
    ids,rows=registry(output)
    assert ids=={('a',2**53+1):0,('b',2**53+1):1}
    assert all(r['present'] for r in rows)
    manifest=json.loads((output/'manifest.json').read_text())
    assert manifest['crs']['geographic_wgs84'] and manifest['options']['timestamp_ms']
    header,metadata,tiles=decode(output/'tiles.pmtiles')
    assert (header['min_zoom'],header['max_zoom'])==(6,8)
    fields=metadata['vector_layers'][0]['fields']
    assert fields['signed']=='Number' and fields['unsigned']=='Number' and fields['wet']=='Boolean'
    seen={z:set() for z in range(6,9)}
    for (z,x,y),layers in tiles.items():
        for f in layers['features']['features']:
            props=f['properties']; key=(props['mesh_name'],props['cell_id'])
            assert f['id']==ids[key]; seen[z].add(key)
            i=0 if key[0]=='b' else 1
            for name in t.column_names:
                if name=='geometry': continue
                want=t[name][i].as_py()
                if name=='time' and want is not None: want=32503680000123
                if want is None: assert name not in props
                else: assert props[name]==want
    assert all(keys==set(ids) for keys in seen.values())
    # Existing packed adapter/freestiler route, independent input representation.
    from rust_export_conformance.helpers import pack
    packed=pack(list(shapely.from_wkb(t['geometry'].to_numpy())),[ids[('b',2**53+1)],ids[('a',2**53+1)]])
    packed['properties']={'mesh_name':['b','a'],'cell_id':[2**53+1]*2}
    reference=tmp_path/'reference.pmtiles'
    fast_hdf.export_pmtiles(reference,{'features':packed},min_zoom=6,max_zoom=8,backend='rust',threads=2)
    expected=decode(reference)[2]
    assert tiles.keys()==expected.keys()
    for address,layers in tiles.items():
        want={f['id']:f['geometry'] for f in expected[address]['features']['features']}
        for f in layers['features']['features']:
            assert shape(f['geometry']).equals_exact(shape(want[f['id']]),0,normalize=True)


def test_batch_order_and_registry_extension(tmp_path):
    t=source(); export(tmp_path/'first',t)
    export(tmp_path/'shuffled',t.take(pa.array([1,0])))
    assert registry(tmp_path/'first')[0]==registry(tmp_path/'shuffled')[0]
    new=source().slice(0,1)
    cols=list(new.columns); cols[0]=pa.chunked_array([pa.array(['0-new'])])
    new=pa.Table.from_arrays(cols,schema=new.schema)
    both=pa.concat_tables([new,t.slice(1,1)])
    export(tmp_path/'continued',both,reuse_from=tmp_path/'first')
    ids,rows=registry(tmp_path/'continued')
    assert ids[('a',2**53+1)]==0 and ids[('b',2**53+1)]==1 and ids[('0-new',2**53+1)]==2
    assert {r['mesh_name']:r['present'] for r in rows}=={'0-new':True,'a':True,'b':False}


@pytest.mark.parametrize('failure',['duplicate','u64','binary','timestamp','null_geom','empty_geom','point','nan','schema','cancel'])
def test_late_failures_publish_nothing(tmp_path,failure):
    t=source()
    if failure=='duplicate': t=pa.concat_tables([t,t.slice(0,1)])
    elif failure=='u64': t=t.set_column(t.schema.get_field_index('unsigned'),'unsigned',pa.array([1,2**64-1],type=pa.uint64()))
    elif failure=='binary': t=t.append_column('blob',pa.array([b'abc',None],type=pa.binary()))
    elif failure=='timestamp': pass
    elif failure in ('null_geom','empty_geom','point'):
        geometries=shapely.from_wkb(t['geometry'].to_numpy()); geometries[1]={'null_geom':None,'empty_geom':Polygon(),'point':Point(1,1)}[failure]
        t=t.set_column(t.schema.get_field_index('geometry'),t.schema.field('geometry'),pa.array(shapely.to_wkb(geometries),type=pa.binary()))
    elif failure=='nan': t=t.set_column(t.schema.get_field_index('value'),'value',pa.array([1.,float('nan')]))
    if failure in ('schema','cancel'):
        original = t
        def batches():
            yield original.slice(0,1).to_batches()[0]
            if failure=='cancel': raise RuntimeError('producer cancelled')
            yield original.slice(1,1).rename_columns([*original.column_names[:-1],'changed']).to_batches()[0]
        t=pa.RecordBatchReader.from_batches(t.schema,batches())
    with pytest.raises((ValueError,RuntimeError,pa.ArrowException)):
        fast_hdf.export_arrow_pmtiles(tmp_path/'out',t,source_crs=4326,min_zoom=6,max_zoom=6,
            max_batch_rows=1,timestamp_ms=failure!='timestamp')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('crs',[None,3857])
def test_crs_conflict(tmp_path,crs):
    with pytest.raises(ValueError):
        fast_hdf.export_arrow_pmtiles(tmp_path/'out',source(),source_crs=crs,timestamp_ms=True)
    assert not list(tmp_path.iterdir())


def test_projected_source_and_original_wkb_metadata(tmp_path):
    t=source().drop(['time'])
    from pyproj import Transformer
    geometries=shapely.transform(shapely.from_wkb(t['geometry'].to_numpy()),Transformer.from_crs(4326,2271,always_xy=True).transform,interleaved=False)
    projected=table(geometries,2271,mesh_names=['b','a'],cell_ids=[2**53+1]*2)
    field=projected.schema.field('geometry').with_metadata({**projected.schema.field('geometry').metadata,b'units_note':b'original feet'})
    projected=projected.cast(projected.schema.set(projected.schema.get_field_index('geometry'),field))
    out=tmp_path/'feet'
    fast_hdf.export_arrow_pmtiles(out,projected,source_crs=2271,min_zoom=6,max_zoom=6)
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['field_metadata']['geometry']['units_note']=='original feet'
    assert 'Foot' in manifest['schema_metadata']['ras:pmtiles:source_crs'] or 'foot' in manifest['schema_metadata']['ras:pmtiles:source_crs']
    for malformed in [shapely.to_wkb(Point(1,2))+b'trailing', shapely.to_wkb(shapely.set_srid(Point(1,2),4326),include_srid=True)]:
        bad=projected.set_column(projected.schema.get_field_index('geometry'),field,pa.array([malformed,malformed]))
        with pytest.raises(ValueError): fast_hdf.export_arrow_pmtiles(tmp_path/'bad',bad,source_crs=2271)
    assert not (tmp_path/'bad').exists()


def test_no_overwrite_and_bad_registry(tmp_path):
    t=source(); export(tmp_path/'existing',t)
    old=(tmp_path/'existing/tiles.pmtiles').read_bytes()
    with pytest.raises(ValueError): export(tmp_path/'existing',t)
    assert (tmp_path/'existing/tiles.pmtiles').read_bytes()==old
    (tmp_path/'existing/manifest.json').write_text('{"bridge_version":999}')
    with pytest.raises(ValueError,match='registry version'): export(tmp_path/'new',t,reuse_from=tmp_path/'existing')
    assert {p.name for p in tmp_path.iterdir()}=={'existing'}

@pytest.mark.parametrize('kind',['missing','conflicting','projected'])
def test_native_crs_gate_and_original_input_immutable(tmp_path,kind):
    from rust_first_tier_exports.helpers import write_input
    t=source()
    if kind=='missing':t=t.replace_schema_metadata({})
    elif kind=='conflicting':
        field=t.schema.field('geometry');metadata=dict(field.metadata)
        meta=json.loads(metadata[b'ARROW:extension:metadata']);meta['crs']={'type':'GeographicCRS','name':'conflict'}
        metadata[b'ARROW:extension:metadata']=json.dumps(meta).encode()
        schema=t.schema.set(t.schema.get_field_index('geometry'),field.with_metadata(metadata))
        t=pa.Table.from_arrays(t.columns,schema=schema)
    else:
        t=table([box(1000000,2000000,1000100,2000100)],2277)
    ipc=tmp_path/'input.arrow';write_input(t,ipc,1);original=ipc.read_bytes()
    options=json.dumps(dict(layer='features',min_zoom=0,max_zoom=0,max_batch_rows=1,timestamp_ms=True,reuse_from=None))
    with pytest.raises(ValueError):native.export_pmtiles_ipc_file(ipc,tmp_path/'out',options,threads=1)
    assert ipc.read_bytes()==original and {p.name for p in tmp_path.iterdir()}=={'input.arrow'}
