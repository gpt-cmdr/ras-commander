"""Canonical 1D delivery AOIs: global lattice, final composition and admission.

Synthetic HDF/GeoTIFF formats isolate delivery geometry; real release-engine
checks do not establish native model parity or run a hydraulic solver.
"""
import json
import os

import numpy as np
import pytest
import rasterio
import shapely
from affine import Affine
from pyproj import Transformer
from rasterio.windows import Window
from shapely.affinity import affine_transform
from shapely.geometry import MultiPolygon, Polygon, box

from ras_commander.fim import FimUnsupportedError, RasFim
from ras_commander.fim import _aoi, _aoi_lattice, _one_d
from test_fim_one_d import files, _fake_engine  # noqa: F401
from test_fim_one_d_steady_storage import steady, steady_storage  # noqa: F401



def forbid_terrain_reads(monkeypatch):
    from contextlib import contextmanager
    original = rasterio.open

    class MetadataOnly:
        def __init__(self, source):
            self.source = source

        def __getattr__(self, name):
            return getattr(self.source, name)

        def read(self, *args, **kwargs):
            pytest.fail('terrain pixels read before admission/empty refusal')

    @contextmanager
    def open_metadata(*args, **kwargs):
        with original(*args, **kwargs) as source:
            yield MetadataOnly(source)

    monkeypatch.setattr(rasterio, 'open', open_metadata)


def grid(transform, width=120, height=120):
    return dict(width=width, height=height, crs='EPSG:6588',
                geo_transform=list(transform.to_gdal()))


def in_world(geometry, transform):
    return affine_transform(geometry, [transform.a, transform.b, transform.d,
                                       transform.e, transform.c, transform.f])


SHAPES = [
    box(10.5, 12.5, 108.5, 100.5),
    Polygon([(10.5, 12.5), (108.5, 12.5), (65.5, 100.5)]),
    Polygon([(10.5, 12.5), (108.5, 12.5), (108.5, 100.5), (10.5, 100.5)],
            holes=[[(30.5, 25.5), (80.5, 25.5), (55.5, 75.5)]]),
    MultiPolygon([box(10.5, 12.5, 40.5, 100.5), box(60.5, 20.5, 108.5, 95.5)]),
]


@pytest.mark.parametrize('shape', SHAPES)
@pytest.mark.parametrize('reverse', [False, True])
def test_planned_window_is_exact_global_crop(shape, reverse):
    t = Affine(28.8452448838947, 0, 6628329.947181307,
               0, -28.8452448838947, 1969956.489543507)
    shape = in_world(shapely.reverse(shape) if reverse else shape, t)
    constraint = _aoi.resolve_aoi(polygon=shape, aoi_crs='EPSG:6588')
    window, projected, scratch = _one_d._plan_delivery_aoi(constraint, t, grid(t), 64 << 20)
    assert projected.equals_exact(shape, 0) and scratch > 0
    full = _aoi_lattice.mask(shape, t, Window(0, 0, 120, 120))
    c, r, w, h = map(int, window.flatten())
    actual = _aoi_lattice.mask(projected, t, window)
    np.testing.assert_array_equal(actual, full[r:r+h, c:c+w])
    outside = full.copy(); outside[r:r+h, c:c+w] = False
    assert not outside.any(), 'planning dropped globally selected pixels'


def test_exact_pixel_center_ties_and_unmasked_bbox():
    t = Affine(1, 0, .25, 0, -1, 100.25)
    shape = box(1.75, 95.75, 5.75, 98.75)
    for kind in ('polygon', 'bbox'):
        constraint = _aoi.resolve_aoi(**{kind: shape if kind == 'polygon' else shape.bounds},
                                      aoi_crs='EPSG:6588')
        window, geometry, _ = _one_d._plan_delivery_aoi(constraint, t, grid(t), 64 << 20)
        assert window == Window(1, 2, 4, 3)
        if kind == 'bbox':
            assert geometry is None
        else:
            full = _aoi_lattice.mask(geometry, t, Window(0, 0, 10, 10))
            expected = np.zeros((10, 10), bool); expected[2:5, 1:5] = True
            np.testing.assert_array_equal(full, expected)


def test_reprojected_bbox_retains_complete_projected_identity(files, tmp_path, monkeypatch):
    _fake_engine(monkeypatch, tmp_path)
    to_geo = Transformer.from_crs('EPSG:6588', 'EPSG:4326', always_xy=True)
    xmin, ymin = to_geo.transform(10, 10)
    xmax, ymax = to_geo.transform(90, 90)
    bounds = (xmin, ymin, xmax, ymax)
    constraint = _aoi.resolve_aoi(bbox=bounds, aoi_crs='EPSG:4326')
    projected = _aoi.geometry_in_crs(constraint, 'EPSG:6588')
    calls = []
    original = _aoi_lattice.mask
    def mask(geometry, transform, window):
        calls.append((geometry, transform, window))
        return original(geometry, transform, window)
    monkeypatch.setattr(_aoi_lattice, 'mask', mask)
    result = RasFim.map_one_d_profiles(*files, tmp_path/'mapped', bbox=bounds,
        aoi_crs='EPSG:4326', profiles={'peak': 'Max', 'early': 0},
        allow_unqualified=True, max_working_mib=64)
    assert result.status.tolist() == ['complete', 'complete']
    assert len(calls) == 1
    assert calls[0][0].wkb_hex == projected.wkb_hex
    assert calls[0][1] == Affine(1, 0, 0, 0, -1, 256)
    description = result.attrs['aoi']
    assert result.attrs['aoi_mask'] == _aoi_lattice.METHOD
    assert description['geometry_wkb_hex'] == constraint.geometry.wkb_hex
    assert description['crs'] == 'EPSG:4326'
    assert description['projected_geometry_wkb_hex'] == projected.wkb_hex
    assert description['projected_crs_wkt'] == result.attrs['preparation']['grid']['crs']


@pytest.mark.parametrize('case', ['pixels', 'coordinates', 'intersections'])
def test_budget_refuses_before_mask_coordinates_or_terrain(files, tmp_path, monkeypatch, case):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path/'prepared', allow_unqualified=True)
    _fake_engine(monkeypatch, tmp_path)
    if case == 'pixels':
        shape = box(0, -256, 512, 256)
    elif case == 'coordinates':
        shape = shapely.Point(50, 50).buffer(10, quad_segs=1024)
    else:
        # Fits geometry-only admission, but not delivery + mask + edge scratch.
        shape = shapely.Point(50, 50).buffer(15, quad_segs=250)
    def forbidden(*args, **kwargs):
        pytest.fail('allocation/read occurred before admission')
    monkeypatch.setattr(_aoi_lattice, 'mask', forbidden)
    forbid_terrain_reads(monkeypatch)
    # resolve_aoi validation itself obtains coordinates; only the lattice mask
    # and terrain payload read must be deferred past delivery admission.
    with pytest.raises(FimUnsupportedError, match='exceeds max_working_mib'):
        prepared.map_profiles(tmp_path/'mapped', polygon=shape, aoi_crs='EPSG:6588',
                              allow_unqualified=True, max_working_mib=1)
    assert not (tmp_path/'mapped').exists()


@pytest.mark.parametrize('shape', [box(1000, 1000, 1001, 1001),
                                  Polygon([(0, .1), (9, 9.1), (9, 9.11)])])
def test_empty_coverage_refuses_before_terrain(files, tmp_path, monkeypatch, shape):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path/'prepared', allow_unqualified=True)
    _fake_engine(monkeypatch, tmp_path)
    forbid_terrain_reads(monkeypatch)
    with pytest.raises(FimUnsupportedError, match='no source-grid pixels'):
        prepared.map_profiles(tmp_path/'mapped', polygon=shape, aoi_crs='EPSG:6588',
                              allow_unqualified=True, max_working_mib=64)
    assert not (tmp_path/'mapped').exists()


@pytest.mark.parametrize('with_storage', [False, True])
@pytest.mark.parametrize('shape', SHAPES)
def test_real_engine_final_products_preserve_masks_bits_and_pool_precedence(
        files, steady_storage, tmp_path, monkeypatch, with_storage, shape):
    engine = os.environ.get('RAS_COMMANDER_FIM_ENGINE')
    if not engine:
        pytest.skip('explicit installed release-engine opt-in')
    scene = steady_storage if with_storage else files
    # Both fixtures share the same HDF; steady_storage converts it to steady.
    # Use explicit steady selections for both scenes and remove storage only
    # in the XS-only case, before any preparation/source identities are bound.
    if not with_storage:
        import h5py
        from test_fim_one_d_steady_storage import BASE
        with h5py.File(scene[0], 'a') as source:
            del source['Geometry/Storage Areas']
            del source[BASE+'Storage Areas']
    t = Affine(.7, 0, .1, 0, -.7, 100.3)
    with rasterio.open(scene[1], 'r+') as source:
        source.transform = t
    before = [_one_d.digest(path) for path in scene]
    prepared = RasFim.prepare_one_d_model(*scene, tmp_path/'prepared',
        profiles={'dry': 0, 'wet': 1}, allow_unqualified=True)
    full = prepared.map_profiles(tmp_path/'full', allow_unqualified=True,
        engine_path=engine, threads=4, max_working_mib=64)
    geometry = in_world(shape, t)
    calls = []
    mask = _aoi_lattice.mask
    def observed(projected, transform, window):
        calls.append((projected, transform, window))
        return mask(projected, transform, window)
    monkeypatch.setattr(_aoi_lattice, 'mask', observed)
    aoi = prepared.map_profiles(tmp_path/'aoi', polygon=geometry, aoi_crs='EPSG:6588',
        allow_unqualified=True, engine_path=engine, threads=4, max_working_mib=64)
    assert full.status.tolist() == aoi.status.tolist() == ['complete', 'complete']
    assert len(calls) == 1 and calls[0][1] == t
    assert calls[0][0].wkb_hex == geometry.wkb_hex
    global_mask = mask(geometry, t, Window(0, 0, 512, 512))
    for index in range(2):
        row = aoi.iloc[index]
        r, c, h, w = map(int, (row.row_off, row.col_off, row.height, row.width))
        keep = global_mask[r:r+h, c:c+w]
        for product in ('depth_tif', 'wse_tif'):
            with rasterio.open(full.iloc[index][product]) as source:
                expected = source.read(1)[r:r+h, c:c+w].copy()
            expected[~keep] = np.nan
            with rasterio.open(row[product]) as source:
                actual = source.read(1)
                assert source.transform == t @ Affine.translation(c, r)
            valid = np.isfinite(expected)
            np.testing.assert_array_equal(np.isfinite(actual), valid)
            np.testing.assert_array_equal(actual[valid].view('u4'), expected[valid].view('u4'))
            assert valid.any()
    if with_storage:
        with rasterio.open(aoi.iloc[0].wse_tif) as source:
            values = source.read(1)
        # Dry physical pool suppresses otherwise-wet XS even after AOI masking.
        xs = t.c + (np.arange(c, c+w) + .5) * t.a
        assert not np.isfinite(values[:, xs < 50]).any()
        assert np.isfinite(values[:, xs >= 50]).any()
    assert before == [_one_d.digest(path) for path in scene]
    receipt = json.loads((tmp_path/'aoi'/'fim_manifest.json').read_text())
    assert receipt['qualified'] is False
    assert receipt['aoi_mask'] == _aoi_lattice.METHOD


def test_reprojection_coordinates_admitted_before_densification(monkeypatch):
    t = Affine(1, 0, 0, 0, -1, 256)
    constraint = _aoi.resolve_aoi(bbox=(-97, 30, -96, 31), aoi_crs='EPSG:4326')
    def forbidden(*args, **kwargs):
        pytest.fail('projected coordinates allocated before admission')
    monkeypatch.setattr(_aoi, 'geometry_in_crs', forbidden)
    with pytest.raises(FimUnsupportedError, match='AOI geometry exceeds'):
        _one_d._plan_delivery_aoi(constraint, t, grid(t), 1 << 20)


@pytest.mark.parametrize('raise_on_failure', [False, True])
def test_polygon_batch_write_failure_rolls_back_all_products(files, tmp_path, monkeypatch,
                                                            raise_on_failure):
    from ras_commander.fim import FimMappingError, _products
    _fake_engine(monkeypatch, tmp_path)
    original = _products.write_raster
    calls = 0
    def write(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('injected second-profile write failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(_products, 'write_raster', write)
    output = tmp_path/'mapped'
    def map_profiles():
        return RasFim.map_one_d_profiles(*files, output,
            profiles={'peak': 'Max', 'early': 0}, polygon=Polygon([(0, 0), (10, 0), (0, 10)]),
            aoi_crs='EPSG:6588', allow_unqualified=True, raise_on_failure=raise_on_failure,
            max_working_mib=64)
    if raise_on_failure:
        with pytest.raises(FimMappingError, match='second-profile write failure') as error:
            map_profiles()
        result = error.value.manifest
    else:
        result = map_profiles()
    assert result.status.tolist() == ['failed', 'failed']
    assert result.depth_tif.isna().all() and result.wse_tif.isna().all()
    assert not list(output.glob('*.tif')) and not list(output.glob('*.partial'))
    document = json.loads((output/'fim_manifest.json').read_text())
    assert document['status'] == 'failed' and document['aoi_mask'] == _aoi_lattice.METHOD
