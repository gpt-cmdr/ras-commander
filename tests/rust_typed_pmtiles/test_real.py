"""Real stored-version cells/results and retained final classification regions."""
import hashlib
import json
import os
from pathlib import Path
import time
import geopandas as gpd
import numpy as np
import pyarrow as pa
import pytest
import shapely
from shapely.geometry import shape
from ras_commander import fast_hdf
from ras_commander.hdf import HdfBase,HdfMesh,HdfResultsMesh
from rust_first_tier_exports.helpers import table
from rust_export_conformance.helpers import decode
from .test_bridge import provenance,registry


@pytest.mark.parametrize('filename,version',[('JUL2020_D100RAS.p04.hdf','5.0.7'),
    ('BaldEagleDamBrk.p03.hdf','6.6'),('BaldEagleDamBrk.p18.hdf','7.0'),('computed7_regions.gpkg','final7')])
def test_real_typed_bridge(tmp_path,filename,version):
    root=os.environ.get('RAS_EXPORT_FIXTURE_ROOT')
    if not root: pytest.skip('set local immutable RAS_EXPORT_FIXTURE_ROOT')
    path=Path(root)/filename; digest=hashlib.sha256(path.read_bytes()).hexdigest()
    started=time.perf_counter()
    if version=='final7':
        source=gpd.read_file(path,layer='regions',fid_as_index=True); assert len(source)==72
        ids=source.index.to_numpy(dtype=np.int64); attrs={'source':'retained final fluvial/pluvial regions'}
        columns={'classification':pa.array(source.classification,type=pa.string()),'area_acres':pa.array(source.area_acres)}
    else:
        attrs=HdfBase.get_attrs(path,'/'); assert f'HEC-RAS {version}' in attrs['File Version']
        all_cells=HdfMesh.get_mesh_cell_polygons(path,engine='h5py')
        source=all_cells.groupby('mesh_name',sort=False).head(64).copy()
        values=HdfResultsMesh.get_mesh_max_ws(path,round_to='1ms')
        if values.empty:
            assert version=='6.6'
            columns={'max_wse':pa.nulls(len(source),type=pa.float64()),'peak':pa.nulls(len(source),type=pa.timestamp('ms'))}
        else:
            source=source.merge(values[['mesh_name','cell_id','maximum_water_surface','maximum_water_surface_time']],on=['mesh_name','cell_id'],validate='one_to_one')
            columns={'max_wse':pa.Array.from_pandas(source.maximum_water_surface).cast(pa.float64()),
                     'peak':pa.Array.from_pandas(source.maximum_water_surface_time).cast(pa.timestamp('ms'))}
        ids=source.cell_id.to_numpy()
    assert not source.empty and source.is_valid.all()
    t=table(source.geometry.to_numpy(),source.crs,mesh_names=source.mesh_name.to_numpy(),cell_ids=ids,columns=columns)
    output=tmp_path/'bundle'
    metrics=fast_hdf.export_arrow_pmtiles(output,t,source_crs=source.crs,min_zoom=12,max_zoom=12,
        max_batch_rows=17,timestamp_ms=True,threads=2)
    mapping,_=registry(output); _,_,tiles=decode(output/'tiles.pmtiles')
    seen=set(); invalid=[]
    for address,layers in tiles.items():
        for f in layers['features']['features']:
            props=f['properties']; key=(props['mesh_name'],props['cell_id'])
            assert f['id']==mapping[key];seen.add(key)
            if not shape(f['geometry']).is_valid:invalid.append([address,f['id']])
    assert seen==set(mapping)
    # Reference Python freestiler route. Attributes prepared only for reference,
    # never used to transport features into the typed production bridge.
    import freestiler
    reference_frame=source[['mesh_name','geometry']].copy();reference_frame['cell_id']=ids
    reference_frame=reference_frame.to_crs(4326)
    reference_frame.geometry=shapely.orient_polygons(reference_frame.geometry.to_numpy())
    reference=tmp_path/'reference.pmtiles'
    freestiler.freestile({'features':reference_frame},reference,min_zoom=12,max_zoom=12,simplification=False,quiet=True)
    reference_tiles=decode(reference)[2];assert tiles.keys()==reference_tiles.keys()
    lookup={(str(mesh),int(cell)):i for i,(mesh,cell) in enumerate(zip(source.mesh_name,ids))}
    for address,layers in tiles.items():
        expected={(f['properties']['mesh_name'],f['properties']['cell_id']):f['geometry'] for f in reference_tiles[address]['features']['features']}
        for f in layers['features']['features']:
            p=f['properties'];key=(p['mesh_name'],p['cell_id']);assert shape(f['geometry']).equals_exact(shape(expected[key]),0,normalize=True)
            i=lookup[key]
            for name,array in columns.items():
                value=array[i].as_py()
                if pa.types.is_timestamp(array.type) and value is not None:value=array.cast(pa.int64())[i].as_py()
                if value is None: assert name not in p
                else: assert p[name]==value
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    (tmp_path/'receipt.json').write_text(json.dumps(dict(file=filename,sha256=digest,attrs=attrs,
        rows=len(source),metrics=metrics,decoded_tiles=len(tiles),invalid=invalid,
        reference_geometry_exact=True,identity_source='GeoPackage persistent FID' if version=='final7' else 'native mesh_name/cell_id',total_seconds=time.perf_counter()-started),indent=2,default=str))


def test_typed_low_zoom_gap(tmp_path):
    root=os.environ.get('RAS_EXPORT_FIXTURE_ROOT')
    if not root:pytest.skip('set local fixture root')
    source=HdfMesh.get_mesh_cell_polygons(Path(root)/'BaldEagleDamBrk.p18.hdf',engine='h5py').to_crs(4326)
    source.geometry=shapely.orient_polygons(source.geometry.to_numpy())
    t=table(source.geometry.to_numpy(),4326,mesh_names=source.mesh_name.to_numpy(),cell_ids=source.cell_id.to_numpy())
    out=tmp_path/'bundle'
    metrics=fast_hdf.export_arrow_pmtiles(out,t,source_crs=4326,min_zoom=6,max_zoom=6,max_batch_rows=129,threads=2)
    import freestiler
    ref=tmp_path/'reference.pmtiles';freestiler.freestile({'features':source[['mesh_name','cell_id','geometry']]},ref,min_zoom=6,max_zoom=6,simplification=False,quiet=True)
    mapping,_=registry(out);tiles=decode(out/'tiles.pmtiles')[2];expected=decode(ref)[2]
    assert tiles.keys()==expected.keys();seen=set();invalid=[]
    for address,layers in tiles.items():
        want={(f['properties']['mesh_name'],f['properties']['cell_id']):f['geometry'] for f in expected[address]['features']['features']}
        for f in layers['features']['features']:
            key=(f['properties']['mesh_name'],f['properties']['cell_id']);seen.add(key)
            assert f['id']==mapping[key] and shape(f['geometry']).equals_exact(shape(want[key]),0,normalize=True)
            if not shape(f['geometry']).is_valid:invalid.append(dict(tile=address,id=f['id'],identity=key,geometry=f['geometry']))
    assert len(seen)==4425 and seen==set(mapping)
    (tmp_path/'gap.json').write_text(json.dumps(dict(metrics=metrics,seen=len(seen),invalid=invalid,reference_exact=True),indent=2))
    assert len(invalid)==36
    pytest.xfail('36 upstream invalid quantized polygons reproduced exactly by typed and freestiler routes')
