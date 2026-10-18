"""Immutable stored-version qualification via ras-commander extraction APIs."""
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio
import pytest
import shapely
from ras_commander.hdf import HdfBase, HdfMesh, HdfResultsMesh, HdfXsec, HdfStruc
from .helpers import export, table


@pytest.fixture(scope='module', params=[('JUL2020_D100RAS.p04.hdf','5.0.7'),
    ('BaldEagleDamBrk.p03.hdf','6.6'),('BaldEagleDamBrk.p18.hdf','7.0')])
def real(request):
    root = os.environ.get('RAS_EXPORT_FIXTURE_ROOT')
    if not root:
        pytest.skip('set RAS_EXPORT_FIXTURE_ROOT to local immutable qualification copies')
    filename, version = request.param
    path = Path(root)/filename
    assert path.exists(), path
    before = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    attrs = HdfBase.get_attrs(path, '/')
    assert f'HEC-RAS {version}' in attrs['File Version']
    start=time.perf_counter()
    cells=HdfMesh.get_mesh_cell_polygons(path,backend='python')
    values=HdfResultsMesh.get_mesh_max_ws(path,round_to='1ms')
    keys=['mesh_name','cell_id']
    selected=cells.groupby('mesh_name',sort=False).head(128)
    selected=selected[selected.is_valid & ~selected.is_empty].copy()
    if values.empty:
        # This actual 6.6 plan has no Maximum Water Surface summary dataset.
        assert version == '6.6'
        joined=selected.copy()
        joined['maximum_water_surface']=np.nan
        joined['maximum_water_surface_time']=pd.NaT
    else:
        joined=selected.merge(values[keys+['maximum_water_surface','maximum_water_surface_time']],on=keys,validate='one_to_one')
        assert joined.maximum_water_surface_time.notna().any()
    assert len(joined)>16
    yield joined, dict(file=filename,version=version,sha256=before,attrs=attrs,
        source_rows=len(cells),sample_rows=len(joined),result_summary_available=not values.empty,extraction_seconds=time.perf_counter()-start), path
    assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==before


@pytest.mark.parametrize('fmt',['arrow','parquet','fgb','geojson','jsonl','gpkg'])
def test_real_cells_results(real,tmp_path,fmt):
    source,receipt,_=real
    numeric=source.maximum_water_surface.to_numpy(dtype=float)
    numeric=pa.array(numeric,mask=~np.isfinite(numeric))
    times=pa.Array.from_pandas(source.maximum_water_surface_time).cast(pa.timestamp('ms'))
    t=table(source.geometry.to_numpy(), source.crs,target_geojson=fmt in ('geojson','jsonl'),
        mesh_names=source.mesh_name.to_numpy(),cell_ids=source.cell_id.to_numpy(),
        columns={'max_wse':numeric,'peak_ms':times})
    out,metrics=export(t,tmp_path,fmt,batch_size=31)
    assert metrics['rows']==len(source)
    if fmt in ('arrow','parquet'):
        read=pa.ipc.open_file(out).read_all() if fmt=='arrow' else pq.read_table(out)
        for name in t.column_names: assert read[name].equals(t[name]),name
    else:
        meta,read=pyogrio.read_arrow(out)
        geom_name=meta['geometry_name'] or 'wkb_geometry'
        actual=shapely.from_wkb(read[geom_name].to_numpy())
        keys=list(zip(read['mesh_name'].to_pylist(),read['cell_id'].to_pylist()))
        original=list(zip(t['mesh_name'].to_pylist(),t['cell_id'].to_pylist()))
        order=[original.index(k) for k in keys]
        wanted=t.take(pa.array(order))
        assert set(keys)==set(original)
        assert shapely.equals_exact(actual,shapely.from_wkb(wanted['geometry'].to_numpy()),1e-12).all()
        assert np.allclose(read['max_wse'].cast(pa.float64()).to_numpy(),wanted['max_wse'].to_numpy(),equal_nan=True)
    (tmp_path/'receipt.json').write_text(json.dumps({**receipt,'format':fmt,'metrics':metrics},indent=2,default=str))


@pytest.mark.parametrize('fmt',['arrow','parquet','fgb','geojson','jsonl','gpkg'])
def test_final_fluvial_pluvial(tmp_path,fmt):
    root=os.environ.get('RAS_EXPORT_FIXTURE_ROOT')
    if not root: pytest.skip('set local retained final-region fixture root')
    path=Path(root)/'computed7_regions.gpkg'
    if not path.exists(): pytest.skip('retained fluvial-graph final region fixture unavailable')
    import geopandas as gpd
    source=gpd.read_file(path,layer='regions')
    assert len(source)==72 and source.is_valid.all()
    assert any(g.geom_type=='MultiPolygon' or (g.geom_type=='Polygon' and len(g.interiors)) for g in source.geometry)
    t=table(source.geometry.to_numpy(),source.crs,target_geojson=fmt in ('geojson','jsonl'),
        mesh_names=source.mesh_name.to_numpy(),cell_ids=np.arange(len(source)),
        columns={'classification':pa.array(source.classification,type=pa.string()),'area_acres':pa.array(source.area_acres)})
    out,metrics=export(t,tmp_path,fmt,batch_size=13)
    if fmt in ('arrow','parquet'):
        read=pa.ipc.open_file(out).read_all() if fmt=='arrow' else pq.read_table(out)
        assert read['geometry'].equals(t['geometry'])
    else:
        meta,read=pyogrio.read_arrow(out)
        order=np.argsort(read['cell_id'].to_numpy());read=read.take(pa.array(order))
        assert shapely.equals_exact(shapely.from_wkb(read[meta['geometry_name'] or 'wkb_geometry'].to_numpy()),
            shapely.from_wkb(t['geometry'].to_numpy()),1e-12).all()
        assert read['classification'].equals(t['classification'])
    (tmp_path/'receipt.json').write_text(json.dumps({'source':str(path),'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
        'fixture_provenance':json.loads((Path(root)/'computed7.json').read_text()),'metrics':metrics},indent=2))


def test_available_cross_sections_structures(real,tmp_path):
    _,receipt,path=real
    inventory={}
    for name,extract in [('cross_sections',HdfXsec.get_cross_sections),('structures',HdfStruc.get_structures)]:
        frame=extract(path)
        inventory[name]=len(frame)
        if frame.empty: continue
        assert frame.crs is not None
        t=table(frame.geometry.to_numpy(),frame.crs,mesh_names=[name]*len(frame),cell_ids=np.arange(len(frame)))
        for fmt in ['arrow','parquet','fgb','gpkg']:
            out,_=export(t,tmp_path,fmt,batch_size=31,name=name+fmt)
            if fmt in ('fgb','gpkg'):
                meta,read=pyogrio.read_arrow(out)
                assert read.num_rows==len(frame)
                read=read.take(pa.array(np.argsort(read['cell_id'].to_numpy())))
                assert shapely.equals_exact(shapely.from_wkb(read[meta['geometry_name'] or 'wkb_geometry'].to_numpy()),frame.geometry.to_numpy(),0).all()
    (tmp_path/'inventory.json').write_text(json.dumps({'fixture':receipt,'layers':inventory},indent=2,default=str))
