"""Coordinate-neutral native ring regressions for the containment reader."""
from functools import reduce
from importlib import import_module

import h5py
import numpy as np
import pytest
from shapely.geometry import Polygon

from ras_commander.hdf import HdfBndry

_read = import_module("ras_commander.geom.GeomMesh")._hdf_polygon_features
GROUP = "Geometry/2D Flow Area Refinement Regions"


def square(lo, hi):
    return [(lo, lo), (hi, lo), (hi, hi), (lo, hi), (lo, lo)]


def write_regions(path, rings, parts=None):
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(GROUP)
        group["Attributes"] = np.array([(b"Region",)], dtype=[("Name", "S16")])
        group["Polygon Info"] = [[0, sum(map(len, rings)), 0, len(rings)]]
        group["Polygon Points"] = np.vstack(rings)
        group["Polygon Parts"] = parts if parts is not None else [
            (i * 5, 5) for i in range(len(rings))
        ]


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("order", [(0,), (0, 1), (2, 0, 3, 1), (3, 1, 0, 2)])
def test_containment_reader_preserves_shell_hole_island_and_disjoint_shell(tmp_path, order):
    rings = [square(0, 10), square(2, 8), square(4, 6), square(20, 22)]
    selected = [rings[i] for i in order]
    path = tmp_path / "rings.g01.hdf"
    write_regions(path, selected)
    with h5py.File(path, "r") as hdf:
        feature = _read(hdf, GROUP)[0]
    actual = feature["geometry"]
    expected = reduce(lambda a, b: a.symmetric_difference(b), map(Polygon, selected))
    assert feature["parse_error"] == ""
    assert actual.is_valid
    assert actual.equals(expected)
    polygons = [actual] if actual.geom_type == "Polygon" else actual.geoms
    vertices = [list(p.exterior.coords) for p in polygons]
    vertices += [list(r.coords) for p in polygons for r in p.interiors]
    assert sorted(vertices) == sorted(selected)
    public = HdfBndry.get_refinement_regions(path)
    assert len(public) == 1
    assert public.geometry.iloc[0].equals(expected)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("parts", [
    [(-1, 5), (5, 5)], [(0, 5), (6, 4)], [(0, 6), (5, 5)],
    [(0, 5), (5, 6)], [(0, 5), (5, 4)], [(0, 5), (5.5, 4.5)],
])
def test_containment_reader_rejects_malformed_ring_spans(tmp_path, parts):
    path = tmp_path / "bad.g01.hdf"
    write_regions(path, [square(0, 10), square(2, 8)], parts)
    with h5py.File(path, "r") as hdf, pytest.raises(RuntimeError, match="Polygon Parts"):
        _read(hdf, GROUP)
