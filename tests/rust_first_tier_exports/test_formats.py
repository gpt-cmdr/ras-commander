import json
from pathlib import Path
import sqlite3

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio
import pytest
from pyproj import CRS
import shapely
from shapely.geometry import Polygon, MultiPolygon, LineString, Point

from .helpers import ROOT, export, table

FORMATS = ['arrow', 'parquet', 'fgb', 'geojson', 'jsonl', 'gpkg']


def geometries():
    donut = Polygon([(0,0),(4,0),(4,4),(0,4),(0,0)], [[(1,1),(1,2),(2,2),(2,1),(1,1)]])
    return [donut, MultiPolygon([donut, shapely.box(6,0,7,1)]), LineString([(0,0),(1,1)]), Point(2,3)]


@pytest.mark.parametrize('fmt', FORMATS)
def test_typed_independent_reopen(tmp_path, fmt):
    t = table(geometries(), 4326, cell_ids=[2**53+1, 2**53+2, 3, 4], columns={
        'very_long_Unicode_水_depth_name': pa.array([1.25, None, 3.5, 4.5]),
        'nullable_integer': pa.array([-(2**63), None, 2**53+3, 0], type=pa.int64()),
        'flag': pa.array([True, None, False, True]),
        'label': pa.array(['水é', None, 'long'*100, '']),
        'time_ms': pa.array([32503680000123, None, 0, -1], type=pa.timestamp('ms'))})
    output, metrics = export(t, tmp_path, fmt)
    assert metrics['rows'] == 4 and metrics['batches'] == 2
    assert metrics['output_bytes'] == output.stat().st_size
    if fmt == 'arrow':
        actual = pa.ipc.open_file(output).read_all()
        assert actual.equals(t)
        return
    if fmt == 'parquet':
        actual = pq.read_table(output)
        for name in t.column_names:
            assert actual[name].equals(t[name]), name
        geo = json.loads(pq.read_metadata(output).metadata[b'geo'])
        assert geo['columns']['geometry']['encoding'] == 'WKB'
        assert CRS.from_json_dict(geo['columns']['geometry']['crs']).equals(CRS(4326))
        return
    if fmt in ('geojson', 'jsonl'):
        text = output.read_text(encoding='utf-8')
        features = json.loads(text)['features'] if fmt == 'geojson' else [json.loads(line) for line in text.splitlines()]
        assert features[0]['properties']['cell_id'] == str(2**53+1)
        assert features[0]['properties']['time_ms'] == 32503680000123
        assert features[0]['properties']['nullable_integer'] == str(-(2**63))
        assert features[1]['properties']['flag'] is None
        geoms = [shapely.geometry.shape(f['geometry']) for f in features]
    else:
        metadata, result = pyogrio.read_arrow(output)
        # FlatGeobuf spatial index intentionally changes order.
        order = np.argsort(result['cell_id'].to_numpy())
        wanted = np.argsort(t['cell_id'].to_numpy())
        result = result.take(pa.array(order))
        original = t.take(pa.array(wanted))
        assert result['cell_id'].equals(original['cell_id'])
        assert result['mesh_name'].equals(original['mesh_name'])
        assert result['label'].equals(original['label'])
        assert result['flag'].to_pylist() == original['flag'].to_pylist()
        assert result['nullable_integer'].to_pylist() == original['nullable_integer'].to_pylist()
        assert result['very_long_Unicode_水_depth_name'].to_pylist() == original['very_long_Unicode_水_depth_name'].to_pylist()
        if fmt == 'fgb':
            assert result['time_ms'].to_pylist() == original['time_ms'].cast(pa.int64()).to_pylist()
        else:
            assert result['time_ms'].cast(pa.timestamp('ms')).equals(original['time_ms'])
        assert CRS(metadata['crs']).equals(CRS(4326), ignore_axis_order=True)
        geoms = shapely.from_wkb(result[metadata['geometry_name'] or 'wkb_geometry'].to_numpy())
        assert shapely.equals_exact(geoms, shapely.from_wkb(original['geometry'].to_numpy()), 0).all()
        if fmt == 'gpkg':
            with sqlite3.connect(output) as db:
                assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
                assert db.execute('select count(*) from gpkg_geometry_columns').fetchone()[0] == 1
                assert db.execute('select count(*) from rtree_features_geometry').fetchone()[0] == 4
        return
    assert shapely.equals_exact(geoms, geometries(), 0).all()


@pytest.mark.parametrize('fmt', FORMATS)
def test_null_empty_geometry(tmp_path, fmt):
    t = table([None, Polygon(), MultiPolygon([]), LineString([])], 4326)
    output, result = export(t, tmp_path, fmt, check=fmt != 'fgb')
    if fmt == 'fgb':
        assert result.returncode and not output.exists()
        assert 'null geometry' in result.stderr
    elif fmt == 'arrow':
        assert pa.ipc.open_file(output).read_all().equals(t)
    elif fmt == 'parquet':
        assert pq.read_table(output)['geometry'].equals(t['geometry'])
    elif fmt == 'gpkg':
        with sqlite3.connect(output) as db:
            assert db.execute('select count(*) from features').fetchone()[0] == 4
            assert db.execute('select count(*) from features where geometry is null').fetchone()[0] == 1
    else:
        features = json.loads(output.read_text())['features'] if fmt == 'geojson' else [json.loads(l) for l in output.read_text().splitlines()]
        assert len(features) == 4 and features[0]['geometry'] is None


@pytest.mark.parametrize('fmt', FORMATS)
def test_late_failure_cleanup_and_no_clobber(tmp_path, fmt):
    t = table(geometries(), 4326)
    arrays = list(t.columns)
    arrays[1] = pa.chunked_array([pa.array([0,1,-1,3], type=pa.int64())])
    invalid = pa.Table.from_arrays(arrays, schema=t.schema)
    before = set(tmp_path.iterdir())
    out, result = export(invalid, tmp_path, fmt, check=False)
    assert result.returncode and not out.exists()
    assert set(tmp_path.iterdir()) - before == {tmp_path/'output.input.arrow'}
    out, _ = export(t, tmp_path, fmt)
    contents = out.read_bytes()
    _, result = export(t, tmp_path, fmt, check=False)
    assert result.returncode and 'already exists' in result.stderr
    assert out.read_bytes() == contents


@pytest.mark.parametrize('fmt', FORMATS)
def test_batch_limit(tmp_path, fmt):
    out, result = export(table(geometries(), 4326), tmp_path, fmt, max_rows=1, check=False)
    assert result.returncode and 'max_batch_rows' in result.stderr and not out.exists()


def test_module_provenance():
    import ras_commander
    assert Path.cwd().resolve() == ROOT
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT)


@pytest.mark.parametrize('epsg', [26915, 2277, 2227,
    '+proj=tmerc +lat_0=0 +lon_0=-93 +k=0.9998 +x_0=123456 +y_0=654321 +datum=NAD83 +units=ft +type=crs'])
@pytest.mark.parametrize('fmt', ['parquet','fgb','gpkg','geojson'])
def test_crs_native_and_geojson(tmp_path, epsg, fmt):
    crs = CRS(epsg)
    source = [Point(1000000, 2000000)]
    t = table(source, crs, target_geojson=fmt == 'geojson')
    out, _ = export(t, tmp_path, fmt)
    if fmt == 'geojson':
        from pyproj import Transformer
        x,y = Transformer.from_crs(crs, 4326, always_xy=True).transform(1000000,2000000)
        assert json.loads(out.read_text())['features'][0]['geometry']['coordinates'] == [x,y]
    elif fmt == 'parquet':
        assert pq.read_table(out)['geometry'].equals(t['geometry'])
        geo = json.loads(pq.read_metadata(out).metadata[b'geo'])
        assert CRS.from_json_dict(geo['columns']['geometry']['crs']).equals(crs)
    else:
        meta, read = pyogrio.read_arrow(out)
        assert CRS(meta['crs']).equals(crs)
        assert shapely.equals_exact(shapely.from_wkb(read[meta['geometry_name'] or 'wkb_geometry'].to_numpy()), source, 0).all()


def test_crs_fail_closed(tmp_path):
    with pytest.raises(ValueError, match='missing'):
        table(geometries(), None)
    with pytest.raises(ValueError, match='conflicting'):
        table(geometries(), 4326, declared_crs=3857)
    native = table([Point(1000,2000)], 3857)
    out,result = export(native,tmp_path,'geojson',check=False)
    assert result.returncode and 'WGS84' in result.stderr and not out.exists()
    missing = native.replace_schema_metadata({})
    out,result = export(missing,tmp_path,'arrow',check=False)
    assert result.returncode and 'CRS' in result.stderr and not out.exists()


@pytest.mark.parametrize('case', ['nested','nonfinite','wkb','conflict','time_ns','duplicate'])
def test_contract_rejects(tmp_path, case):
    t = table(geometries(), 4326)
    if case == 'nested': t=t.append_column('bad',pa.array([[1]]*4))
    if case == 'nonfinite': t=t.append_column('bad',pa.array([float('nan')]*4))
    if case == 'time_ns': t=t.append_column('bad',pa.array([0]*4,type=pa.timestamp('ns')))
    if case == 'wkb': t=t.set_column(2,t.schema.field('geometry'),pa.array([b'\x01\x03']*4,type=pa.binary()))
    if case == 'conflict':
        evidence=json.loads(t.schema.metadata[b'ras:export:v1']); evidence['projjson']={'bad':'crs'}
        t=t.replace_schema_metadata({'ras:export:v1':json.dumps(evidence)})
    if case == 'duplicate': t=t.set_column(1,t.schema.field('cell_id'),pa.array([0,0,2,3],type=pa.int64()))
    out,result=export(t,tmp_path,'arrow',check=False)
    assert result.returncode and not out.exists()


@pytest.mark.parametrize('fmt', FORMATS)
def test_uint64_and_binary_policy(tmp_path,fmt):
    columns={'u64':pa.array([2**64-1],type=pa.uint64()),'blob':pa.array([b'\x00\xff'],type=pa.binary())}
    t=table([Point(1,2)],4326,columns=columns)
    out,result=export(t,tmp_path,fmt,check=False)
    if fmt in ('geojson','jsonl','gpkg','fgb'):
        assert result.returncode and not out.exists()
        return
    assert isinstance(result,dict)
    if fmt=='arrow': actual=pa.ipc.open_file(out).read_all()
    elif fmt=='parquet': actual=pq.read_table(out)
    else: _,actual=pyogrio.read_arrow(out)
    assert actual['u64'].to_pylist()==[2**64-1]
    assert actual['blob'].to_pylist()==[b'\x00\xff']


@pytest.mark.parametrize('fmt', FORMATS)
def test_empty_table(tmp_path,fmt):
    t=table([],4326)
    out,metrics=export(t,tmp_path,fmt)
    assert metrics['rows']==0 and metrics['batches']==0 and out.exists()


def test_geojson_winding_and_xy_policy(tmp_path):
    wrong=shapely.orient_polygons(geometries()[0],exterior_cw=True)
    t=table([wrong],4326)
    out,result=export(t,tmp_path,'geojson',check=False)
    assert result.returncode and 'CCW' in result.stderr and not out.exists()
    t=table([wrong],4326,target_geojson=True)
    export(t,tmp_path,'geojson')
    with pytest.raises(ValueError,match='XY'):
        table([Point(1,2,3)],4326)


@pytest.mark.parametrize('fmt',['fgb','gpkg'])
def test_index_query_and_checked_unsigned_binary(tmp_path,fmt):
    geoms=[shapely.box(0,0,1,1),shapely.box(10,10,11,11)]
    t=table(geoms,4326,columns={'u64':pa.array([2**53+1,None],type=pa.uint64()),
        'blob':pa.array([b'\x00\xff',None],type=pa.binary())})
    out,_=export(t,tmp_path,fmt)
    _,read=pyogrio.read_arrow(out,bbox=(-1,-1,2,2))
    assert read.num_rows==1 and read['cell_id'].to_pylist()==[0]
    assert read['u64'].to_pylist()==[2**53+1]
    assert read['blob'].to_pylist()==[b'\x00\xff']
