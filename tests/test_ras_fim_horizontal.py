"""Actual raster/geometry tests for explicit horizontal mapping; no solver."""
import json
from pathlib import Path

import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from ras_commander import RasFim
from ras_commander.fim import FimMappingError, FimUnsupportedError, _engine, _horizontal, _prepare, _products


@pytest.fixture
def scene(tmp_path):
    cells = gpd.GeoDataFrame({"cell_idx": [0, 1, 2, 3],
        "wsel_a": [100.5, 101.0, 102.0, np.nan],
        "wsel_b": [103.0, np.nan, 100.1, 104.0],
        "geometry": [box(0,0,10,10), box(10,0,20,10), box(0,10,10,20), box(10,10,20,20)]},
        crs="EPSG:2278")
    terrain = tmp_path / "terrain.tif"
    data = np.full((20,20),100,dtype="float32")
    data[3,3] = -9999
    with rasterio.open(terrain,"w",driver="GTiff",height=20,width=20,count=1,dtype="float32",
                       crs=cells.crs,transform=from_origin(0,20,1,1),nodata=-9999) as dst:
        dst.write(data,1)
    return cells,terrain,tmp_path


def run(scene,name="out",**kwargs):
    cells,terrain,root=scene
    return RasFim.map_horizontal_profiles(cells,terrain,root/name,write_floodplain=False,**kwargs)


def test_horizontal_depth_filter_ownership_nodata_and_shared_prepare(scene,monkeypatch):
    cells,terrain,root=scene
    before=terrain.read_bytes()
    original=_horizontal.prepare_grid
    calls=[]
    def prepare(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(_horizontal,"prepare_grid",prepare)
    def forbidden(*args,**kwargs):
        raise AssertionError("horizontal mapping must not invoke triangulation or an external engine")
    monkeypatch.setattr(_engine,"find_engine",forbidden)
    monkeypatch.setattr(_prepare,"prepare_profile",forbidden)
    rows=run(scene,min_depth=0.5)
    assert len(calls)==1 and len(rows)==2
    with rasterio.open(rows.iloc[0].depth_tif) as ds:
        depth=ds.read(1)
        assert ds.crs.to_epsg()==2278 and ds.transform==from_origin(0,20,1,1)
    assert np.isnan(depth[10:, :10]).all()  # exactly 0.5 is removed
    assert (depth[10:,10:]==1).all()
    assert np.isnan(depth[:10,10:]).all()  # dry cell
    assert np.isnan(depth[3,3])  # terrain nodata
    assert np.all(depth[:10,:10][np.isfinite(depth[:10,:10])]==2)
    assert terrain.read_bytes()==before
    assert cells.wsel_a.iloc[0]==100.5
    doc=json.loads((root/'out/fim_manifest.json').read_text())
    assert doc['status']=='complete' and 'NumPy' in doc['method']
    assert not (root/'out/fim_manifest.json.partial').exists()


def test_horizontal_polygon_hole_is_masked_crop(scene):
    full=run(scene,'full',min_depth=0.5)
    polygon=Polygon([(1,1),(19,1),(19,19),(1,19)],holes=[[(5,5),(15,5),(15,15),(5,15)]])
    cut=run(scene,'cut',min_depth=0.5,polygon=polygon,aoi_crs='EPSG:2278')
    with rasterio.open(full.iloc[0].depth_tif) as ds:
        expected=ds.read(1)[1:19,1:19]
    expected[4:14,4:14]=np.nan
    with rasterio.open(cut.iloc[0].depth_tif) as ds:
        np.testing.assert_array_equal(ds.read(1),expected)
        assert ds.transform==from_origin(1,19,1,1)


def test_horizontal_preallocation_budget_and_fresh_folder(scene,monkeypatch):
    def forbidden(*args):
        raise AssertionError('raster arrays must not load before admission')
    monkeypatch.setattr(_horizontal,'prepare_grid',forbidden)
    with pytest.raises(FimUnsupportedError,match='planned'):
        run(scene,max_working_mib=1)
    assert not (scene[2]/'out').exists()
    (scene[2]/'out').mkdir()
    sentinel=scene[2]/'out/keep.txt'; sentinel.write_text('keep')
    with pytest.raises(FileExistsError):
        run(scene)
    assert sentinel.read_text()=='keep'


def test_horizontal_overlaps_fail_with_manifest(scene):
    scene[0].loc[1,'geometry']=box(5,0,20,10)
    with pytest.raises(FimUnsupportedError,match='overlapping'):
        run(scene)
    document=json.loads((scene[2]/'out/fim_manifest.json').read_text())
    assert document['status']=='aborted'
    assert all(p['status']=='not_run' for p in document['profiles'])
    assert not list((scene[2]/'out').glob('*.tif'))


def test_horizontal_profile_write_error_is_not_success(scene,monkeypatch):
    writer=_products.write_raster
    def failing(path,*args):
        if Path(path).name.startswith('10_wsel_a'):
            raise OSError('injected write failure')
        return writer(path,*args)
    monkeypatch.setattr(_products,'write_raster',failing)
    rows=run(scene,raise_on_failure=False)
    assert list(rows.status)==['failed','complete']
    assert not (scene[2]/'out/09_wsel_a_depth_nudge.tif').exists()
    assert json.loads((scene[2]/'out/fim_manifest.json').read_text())['status']=='failed'


def test_horizontal_empty_aoi_and_infinite_profile(scene):
    rows=run(scene,'empty',bbox=(50,50,60,60),max_working_mib=1)
    assert (rows.status=='empty_aoi').all()
    scene[0].loc[0,'wsel_a']=np.inf
    with pytest.raises(FimMappingError) as caught:
        run(scene,'invalid')
    assert list(caught.value.manifest.status)==['failed','complete']


def test_horizontal_rejects_crs_mismatch(scene):
    scene[0].set_crs('EPSG:3857',allow_override=True,inplace=True)
    with pytest.raises(FimUnsupportedError,match='share a CRS'):
        run(scene)


def test_horizontal_floodplain_uses_filtered_depth(scene):
    cells,terrain,root=scene
    rows=RasFim.map_horizontal_profiles(cells,terrain,root/'floodplain',min_depth=0.5)
    frame=gpd.read_file(rows.iloc[0].floodplain_gpkg)
    assert frame.crs.to_epsg()==2278
    assert frame.geometry.area.sum()==199.0  # two wet cells minus one terrain-nodata pixel


def test_horizontal_normalizes_float64_wse_before_depth_filter(scene):
    scene[0].loc[0,'wsel_a']=100.5000001
    rows=run(scene,min_depth=0.5)
    with rasterio.open(rows.iloc[0].depth_tif) as src:
        assert np.isnan(src.read(1)[10:,:10]).all()


def test_horizontal_requires_declared_terrain_nodata(scene):
    with rasterio.open(scene[1],'r+') as dst:
        dst.nodata=None
    with pytest.raises(FimUnsupportedError,match='declare its nodata'):
        run(scene)


def test_horizontal_aoi_between_disconnected_cells_is_empty(scene):
    cells,terrain,root=scene
    cells=cells.iloc[:2].copy()
    cells.geometry=[box(0,0,5,20),box(15,0,20,20)]
    rows=RasFim.map_horizontal_profiles(cells,terrain,root/'gap',bbox=(6,5,14,15),max_working_mib=1)
    assert (rows.status=='empty_aoi').all()
    assert not list((root/'gap').glob('*.tif'))


def test_horizontal_ignores_overlapping_cells_outside_aoi(scene):
    cells,terrain,root=scene
    extra=gpd.GeoDataFrame({'cell_idx':[8,9],'wsel_a':[110.,120.],
                           'wsel_b':[110.,120.],
                           'geometry':[box(100,100,110,110),box(101,101,111,111)]},crs=cells.crs)
    import pandas as pd
    extended=gpd.GeoDataFrame(pd.concat([cells,extra],ignore_index=True),crs=cells.crs)
    rows=RasFim.map_horizontal_profiles(extended,terrain,root/'out',bbox=(0,0,20,20),write_floodplain=False)
    assert (rows.status=='complete').all()
    assert rows.iloc[0].wet_cells==3


def test_horizontal_abort_removes_committed_products_and_marks_manifest(scene,monkeypatch):
    writer=_products.write_raster
    def interrupted(path,*args):
        if 'wsel_b' in Path(path).name:
            raise KeyboardInterrupt()
        return writer(path,*args)
    monkeypatch.setattr(_products,'write_raster',interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(scene)
    assert not list((scene[2]/'out').glob('*.tif'))
    doc=json.loads((scene[2]/'out/fim_manifest.json').read_text())
    assert doc['status']=='aborted' and all(row['status']=='not_run' for row in doc['profiles'])


def test_horizontal_changed_input_manifest_and_exception_agree(scene,monkeypatch):
    from ras_commander.fim.RasFim import _file_identity
    import importlib
    module=importlib.import_module('ras_commander.fim.RasFim')
    calls=[]
    def changed(path):
        size,mtime=_file_identity(path)
        calls.append(1)
        return size,mtime+int(len(calls)>1)
    monkeypatch.setattr(module,'_file_identity',changed)
    with pytest.raises(FimMappingError) as caught:
        run(scene)
    assert (caught.value.manifest.status=='not_run').all()
    assert json.loads((scene[2]/'out/fim_manifest.json').read_text())['status']=='aborted'
    assert not list((scene[2]/'out').glob('*.tif'))


@pytest.mark.parametrize("other", [box(0,0,10,10), box(2,2,8,8)])
def test_horizontal_rejects_coincident_and_contained_cells(scene,other):
    scene[0].loc[1,'geometry']=other
    with pytest.raises(FimUnsupportedError,match='overlapping'):
        run(scene)
