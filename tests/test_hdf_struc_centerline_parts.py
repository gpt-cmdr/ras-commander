"""Regression for packed structure centerline Parts in HdfStruc.get_structures()."""

import h5py
import numpy as np
import pytest

from ras_commander import HdfStruc

POINTS = [[0, 0], [1, 0], [2, 0], [3, 0], [10, 5], [11, 5], [12, 5], [13, 5]]


def _write(path, info, parts, points=POINTS):
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group("Geometry/Structures")
        group["Attributes"] = np.array(
            [(f"s{i}".encode(),) for i in range(len(info))], dtype=[("Type", "S12")]
        )
        group["Centerline Info"] = np.asarray(info, dtype=np.int32)
        group["Centerline Parts"] = np.asarray(parts, dtype=np.int32)
        group["Centerline Points"] = np.asarray(points, dtype=float)


def test_single_part_centerline_is_unchanged_linestring(tmp_path):
    path = tmp_path / "single.g01.hdf"
    _write(path, [[0, 8, 0, 1]], [[0, 8]])
    geometry = HdfStruc.get_structures(path).geometry.iloc[0]
    assert geometry.geom_type == "LineString"
    assert np.asarray(geometry.coords).tolist() == POINTS


@pytest.mark.parametrize("point_start", [0, 2])
def test_multipart_centerline_returns_parts_without_connector(tmp_path, point_start):
    path = tmp_path / "multi.g01.hdf"
    points = [[90, 90]] * point_start + POINTS
    info = [[point_start, 8, 0, 2]]
    _write(path, info, [[0, 4], [4, 4]], points)
    geometry = HdfStruc.get_structures(path).geometry.iloc[0]
    assert geometry.geom_type == "MultiLineString"
    assert [np.asarray(line.coords).tolist() for line in geometry.geoms] == [
        POINTS[:4], POINTS[4:]
    ]


def test_legacy_global_centerline_parts_covering_the_feature(tmp_path):
    path = tmp_path / "global.g01.hdf"
    _write(path, [[2, 6, 0, 2]], [[2, 2], [4, 4]])
    geometry = HdfStruc.get_structures(path).geometry.iloc[0]
    assert [np.asarray(line.coords).tolist() for line in geometry.geoms] == [
        POINTS[2:4], POINTS[4:]
    ]


@pytest.mark.parametrize(
    "info, parts",
    [
        ([[0, 8, 0, 2]], [[0, 4], [4, 5]]),  # part exceeds the feature
        ([[0, 8, 0, 2]], [[0, 4]]),  # truncated Parts dataset
        ([[0, 8, 0, 2]], [[0, 1], [1, 7]]),  # single-vertex part
    ],
)
def test_invalid_centerline_parts_raise(tmp_path, info, parts):
    path = tmp_path / "bad.g01.hdf"
    _write(path, info, parts)
    with pytest.raises(ValueError, match="centerline parts"):
        HdfStruc.get_structures(path)


@pytest.mark.parametrize(
    "info, parts",
    [
        ([[0, 0, 0, 1], [0, 8, 1, 1]], [[0, 0], [0, 8]]),  # Muncie-style empty row
        ([[0, 8, 0, 1], [8, 0, 1, 1]], [[0, 8], [0, 0]]),  # empty row at array end
        ([[0, 8, 0, 1], [4, 0, 1, 1]], [[0, 8], [4, 0]]),  # legacy global empty part
        ([[0, 8, 0, 1], [4, 0, 0, 0]], [[0, 8]]),  # empty row without parts
    ],
)
def test_zero_point_centerline_returns_none_geometry(tmp_path, info, parts):
    path = tmp_path / "empty.g01.hdf"
    _write(path, info, parts)
    gdf = HdfStruc.get_structures(path)
    empty = [i for i, row in enumerate(info) if row[1] == 0]
    assert [i for i, g in enumerate(gdf.geometry) if g is None] == empty
    other = [i for i in range(len(info)) if i not in empty][0]
    assert np.asarray(gdf.geometry.iloc[other].coords).tolist() == POINTS


@pytest.mark.parametrize(
    "info, parts, match",
    [
        ([[9, 0, 0, 1]], [[0, 0]], "point range"),  # start beyond Points
        ([[-1, 0, 0, 1]], [[0, 0]], "point range"),  # negative start
        ([[0, 0, 0, 1]], [[0, 3]], "centerline parts"),  # part exceeds empty range
        ([[0, 0, 1, 1]], [[0, 0]], "centerline parts"),  # truncated Parts
        ([[0, 1, 0, 1]], [[0, 1]], "point range"),  # one-point centerline
    ],
)
def test_inconsistent_empty_or_short_centerline_raises(tmp_path, info, parts, match):
    path = tmp_path / "bad-empty.g01.hdf"
    _write(path, info, parts)
    with pytest.raises(ValueError, match=match):
        HdfStruc.get_structures(path)
