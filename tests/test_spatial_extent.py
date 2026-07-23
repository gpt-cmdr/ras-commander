"""Unit coverage for the shared authoritative-extent contract."""

from dataclasses import dataclass

import pytest

from ras_commander._spatial_extent import (
    _normalize_extent_bounds,
    _normalize_extent_geometry,
)
from ras_commander._land_classification_helper import normalize_restrict_to_extent


@dataclass
class _BoundsObject:
    left: float
    bottom: float
    right: float
    top: float


class _FakeRasMapperExtent:
    """Portable stand-in exposing the RasMapperLib.Extent coordinate contract."""

    def __init__(self, min_x, min_y, max_x, max_y):
        self.MinX = min_x
        self.MinY = min_y
        self.MaxX = max_x
        self.MaxY = max_y


@pytest.mark.parametrize(
    "extent",
    [
        (1, 2, 5, 8),
        [1, 2, 5, 8],
        {"xmin": 1, "ymin": 2, "xmax": 5, "ymax": 8},
        {"left": 1, "bottom": 2, "right": 5, "top": 8},
        _BoundsObject(1, 2, 5, 8),
        _FakeRasMapperExtent(1, 2, 5, 8),
    ],
)
def test_legacy_bounds_shapes_normalize_consistently(extent):
    assert _normalize_extent_bounds(extent) == (1.0, 2.0, 5.0, 8.0)


def test_polygon_and_buffer_derive_expected_bounds():
    from shapely.geometry import box

    polygon = box(10, 20, 30, 50)

    assert _normalize_extent_bounds(
        polygon,
        buffer_distance=5.0,
    ) == (5.0, 15.0, 35.0, 55.0)


def test_land_classification_regression_normalizer_accepts_polygon_unchanged():
    from shapely.geometry import box

    assert normalize_restrict_to_extent(box(0, 0, 1, 1)) == (
        0.0,
        0.0,
        1.0,
        1.0,
    )


def test_single_effective_part_multipolygon_normalizes_to_polygon():
    from shapely import from_wkt

    extent = from_wkt(
        "MULTIPOLYGON (EMPTY, ((0 0, 4 0, 4 3, 0 3, 0 0)))"
    )

    normalized = _normalize_extent_geometry(extent)

    assert normalized.geom_type == "Polygon"
    assert normalized.bounds == (0.0, 0.0, 4.0, 3.0)


def test_true_multipart_geometry_fails_closed():
    from shapely.geometry import MultiPolygon, box

    extent = MultiPolygon([box(0, 0, 1, 1), box(3, 3, 4, 4)])

    with pytest.raises(ValueError, match="ambiguous.*found 2"):
        _normalize_extent_bounds(extent)


def test_empty_polygon_fails_explicitly():
    from shapely.geometry import Polygon

    with pytest.raises(ValueError, match="geometry is empty"):
        _normalize_extent_bounds(Polygon())


def test_invalid_polygon_fails_explicitly():
    from shapely.geometry import Polygon

    bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

    with pytest.raises(ValueError, match="geometry is invalid"):
        _normalize_extent_bounds(bowtie)


@pytest.mark.parametrize("geometry_type", ["Point", "LineString", "GeometryCollection"])
def test_non_polygon_geometry_fails_explicitly(geometry_type):
    from shapely.geometry import GeometryCollection, LineString, Point

    geometries = {
        "Point": Point(0, 0),
        "LineString": LineString([(0, 0), (1, 1)]),
        "GeometryCollection": GeometryCollection([Point(0, 0)]),
    }

    with pytest.raises(ValueError, match=rf"got {geometry_type}"):
        _normalize_extent_bounds(geometries[geometry_type])


def test_one_effective_geodataframe_geometry_is_supported():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon, box

    extent = geopandas.GeoDataFrame(
        geometry=[Polygon(), box(1, 2, 5, 8)],
        crs="EPSG:2271",
    )

    assert _normalize_extent_bounds(extent) == (1.0, 2.0, 5.0, 8.0)


def test_rasmapper_extent_can_be_rebuilt_after_buffering():
    source = _FakeRasMapperExtent(1, 2, 5, 8)

    normalized = _normalize_extent_bounds(
        source,
        buffer_distance=1.0,
        extent_cls=_FakeRasMapperExtent,
    )

    assert isinstance(normalized, _FakeRasMapperExtent)
    assert (normalized.MinX, normalized.MinY, normalized.MaxX, normalized.MaxY) == (
        0.0,
        1.0,
        6.0,
        9.0,
    )


@pytest.mark.parametrize(
    "extent",
    [
        (0, 0, 0, 1),
        (0, 0, float("nan"), 1),
        {"xmin": 0, "ymin": 0, "xmax": 1},
    ],
)
def test_invalid_legacy_bounds_fail_explicitly(extent):
    with pytest.raises(ValueError, match="bounds|must be"):
        _normalize_extent_bounds(extent)


def test_buffer_that_erases_polygon_fails_explicitly():
    from shapely.geometry import box

    with pytest.raises(ValueError, match="buffer_distance=-1.0 produced an unusable"):
        _normalize_extent_bounds(box(0, 0, 1, 1), buffer_distance=-1.0)
