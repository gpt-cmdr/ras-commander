"""Global AOI coverage must not depend on window origin or ring orientation."""
import numpy as np
import pytest
from affine import Affine
from rasterio.windows import Window
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, MultiPolygon, box
from ras_commander.fim._aoi_lattice import mask, index_range


def test_half_open_pixel_center_edges_match_bbox_rule():
    t = Affine(1,0,0,0,-1,0)
    polygon = box(1.5,-4.5,5.5,-1.5)
    actual = mask(polygon,t,Window(0,0,8,8))
    expected = np.zeros((8,8),bool); expected[2:5,1:5] = True
    np.testing.assert_array_equal(actual,expected)
    assert index_range(1.5,5.5,0,1,8)==(1,5)
    assert index_range(-4.5,-1.5,0,-1,8)==(2,5)


@pytest.mark.parametrize('geometry',[
    box(10.5,12.5,382.5,331.5),
    Polygon([(10.5,12.5),(382.5,12.5),(200.5,331.5)]),
    Polygon([(10.5,12.5),(382.5,12.5),(382.5,331.5),(10.5,331.5)],
        holes=[[(30.5,40.5),(150.5,50.5),(100.5,240.5)]]),
    MultiPolygon([box(10.5,12.5,80.5,331.5),box(130.5,20.5,382.5,200.5)]),
])
def test_fractional_origin_crops_and_reversed_rings(geometry):
    t = Affine(28.8452448838947,0,6628329.947181307,0,-28.8452448838947,1969956.489543507)
    geometry=affine_transform(geometry,[t.a,t.b,t.d,t.e,t.c,t.f])
    full=mask(geometry,t,Window(0,0,394,345))
    for col,row,width,height in [(10,13,373,319),(11,12,100,150),(121,50,4,250)]:
        np.testing.assert_array_equal(mask(geometry,t,Window(col,row,width,height)),
            full[row:row+height,col:col+width])
    import shapely
    np.testing.assert_array_equal(mask(shapely.reverse(geometry),t,Window(0,0,394,345)),full)


def test_legacy_crop_gdal_mask_reproduces_the_original_defect():
    from rasterio.features import geometry_mask
    t=Affine(28.8452448838947,0,6628329.947181307,0,-28.8452448838947,1969956.489543507)
    geometry=affine_transform(box(10.5,12.5,382.5,331.5),[t.a,t.b,t.d,t.e,t.c,t.f])
    w=Window(10,13,373,319)
    legacy_full=geometry_mask([geometry],(345,394),t,invert=True)[13:332,10:383]
    legacy_crop=geometry_mask([geometry],(319,373),t*Affine.translation(10,13),invert=True)
    assert np.count_nonzero(legacy_full!=legacy_crop)>0
    np.testing.assert_array_equal(mask(geometry,t,w),mask(geometry,t,Window(0,0,394,345))[13:332,10:383])


def test_polygon_requires_advertised_global_lattice_capability(tmp_path, monkeypatch):
    import geopandas as gpd
    import rasterio
    import sys
    from ras_commander import RasFim
    from ras_commander.fim import _engine
    from ras_commander.fim.errors import FimEngineError
    cells=gpd.GeoDataFrame(dict(cell_idx=[0],wsel_a=[20.],geometry=[box(0,0,8,8)]),crs='EPSG:2278')
    terrain=tmp_path/'terrain.tif'
    with rasterio.open(terrain,'w',driver='GTiff',width=8,height=8,count=1,dtype='float32',
            nodata=-9999,crs=cells.crs,transform=Affine(1,0,0,0,-1,8)) as dst:
        dst.write(np.ones((8,8),np.float32),1)
    monkeypatch.setattr(_engine,'engine_method',lambda _:dict(horizontal=dict(
        method_id='horizontal-cell-constant/2',stream_outputs=True,native_ownership=True)))
    with pytest.raises(FimEngineError,match='global-terrain-lattice/1'):
        RasFim.map_horizontal_profiles(cells,terrain,tmp_path/'out',polygon=box(1,1,7,7),
            aoi_crs=cells.crs,engine_path=sys.executable,write_floodplain=False)
