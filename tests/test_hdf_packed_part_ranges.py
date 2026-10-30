"""Regression for whole-feature packed Parts resolution (HdfBase._feature_part_ranges).

Feature-local Parts are valid when every part lies within the feature's point
count; legacy global Parts are accepted only when they cover the feature
exactly; anything else raises.
"""

import h5py
import numpy as np
import pytest
from shapely.geometry import MultiLineString, MultiPolygon, Polygon

from ras_commander.geom.GeomMesh import _hdf_polyline_features
from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfMesh import _MeshLayoutError, _strict_collection_perimeters


def _write(group, prefix, info, parts, points):
    group["Attributes"] = np.array(
        [(f"f{i}".encode(),) for i in range(len(info))], dtype=[("Name", "S8")]
    )
    group[f"{prefix} Info"] = np.asarray(info, dtype=np.int32)
    group[f"{prefix} Parts"] = np.asarray(parts, dtype=np.int32)
    group[f"{prefix} Points"] = np.asarray(points, dtype=float)


@pytest.mark.parametrize(
    "parts, expected",
    [
        ([[3, 4], [7, 4]], [(3, 4), (7, 4)]),  # local, unused leading vertices
        ([[0, 4], [3, 4]], [(0, 4), (3, 4)]),  # local, shared vertex
        ([[3, 5], [8, 6]], [(0, 5), (5, 6)]),  # legacy global, exact cover
    ],
)
def test_feature_part_ranges_accepts_local_bounds_and_global_cover(parts, expected):
    assert HdfBase._feature_part_ranges(np.array(parts), 3, 11) == expected


@pytest.mark.parametrize(
    "parts",
    [
        [[0, 4], [10, 4]],  # mixed conventions
        [[3, 4], [8, 6]],  # global with a gap
        [[-1, 4]],  # negative offset
        [[0.5, 4]],  # fractional offset
    ],
)
def test_feature_part_ranges_rejects_other_layouts(parts):
    with pytest.raises(ValueError):
        HdfBase._feature_part_ranges(np.array(parts), 3, 11)


@pytest.mark.synthetic_hdf_layout
def test_polyline_local_parts_with_unused_vertices(tmp_path):
    lead = [[88, 88], [89, 88], [88, 89]]
    feature = [[90, 90], [91, 91], [92, 92], [0, 0], [1, 1], [2, 2], [3, 3],
               [5, 0], [6, 1], [7, 2], [8, 3]]
    with h5py.File(tmp_path / "lines.hdf", "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Area Break Lines")
        _write(group, "Polyline", [[0, 3, 0, 1], [3, 11, 1, 2]],
               [[0, 3], [3, 4], [7, 4]], lead + feature)
        geometry = _hdf_polyline_features(hdf, group.name)[1]["geometry"]
    assert geometry.equals_exact(MultiLineString([feature[3:7], feature[7:]]), 0)


@pytest.mark.synthetic_hdf_layout
def test_mesh_perimeter_local_parts_with_unused_vertices(tmp_path):
    square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    shifted = [[x + 5, y] for x, y in square]
    first = [[x + 20, y + 20] for x, y in square]
    feature = [[90, 90], [91, 90], [90, 91]] + square + shifted
    with h5py.File(tmp_path / "areas.hdf", "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Areas")
        _write(group, "Polygon", [[0, 5, 0, 1], [5, 13, 1, 2]],
               [[0, 5], [3, 5], [8, 5]], first + feature)
        geometry = _strict_collection_perimeters(group, ["A", "B"])[1]
    assert geometry.equals_exact(MultiPolygon([Polygon(square), Polygon(shifted)]), 0)


@pytest.mark.synthetic_hdf_layout
def test_mesh_perimeter_mixed_conventions_fail_closed(tmp_path):
    square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    points = square + square + [[x + 5, y] for x, y in square]
    with h5py.File(tmp_path / "areas.hdf", "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Areas")
        _write(group, "Polygon", [[0, 5, 0, 1], [5, 10, 1, 2]],
               [[0, 5], [0, 5], [10, 5]], points)
        with pytest.raises(_MeshLayoutError):
            _strict_collection_perimeters(group, ["A", "B"])
