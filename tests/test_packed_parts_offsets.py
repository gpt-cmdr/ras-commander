"""Native packed format edge cases; coordinates are invented unit squares/lines."""
from importlib import import_module

import h5py
import numpy as np
import pytest
from shapely.geometry import MultiLineString, MultiPolygon, Polygon

from ras_commander.hdf import HdfBase, HdfMesh

_read_lines = import_module("ras_commander.geom.GeomMesh")._hdf_polyline_features


@pytest.mark.synthetic_hdf_layout(
    "global-polyline",
    "local-polyline",
)
@pytest.mark.parametrize("consumer", ["collection", "polyline"])
@pytest.mark.parametrize("convention", ["local", "global"])
def test_nonzero_feature_start_with_numerically_overlapping_offsets(tmp_path, consumer, convention):
    path = tmp_path / "parts.g01.hdf"
    if consumer == "collection":
        first = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])
        points = np.vstack([first, first + 10, first + 20])
        count, group_path, prefix = 5, "Geometry/2D Flow Areas", "Polygon"
        expected = MultiPolygon([Polygon(first + 10), Polygon(first + 20)])
    else:
        points = np.array([[0, 0], [1, 0], [20, 0], [21, 0], [30, 0], [31, 0]])
        count, group_path, prefix = 2, "Geometry/2D Flow Area Break Lines", "Polyline"
        expected = MultiLineString([points[2:4], points[4:6]])
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(group_path)
        group["Attributes"] = np.array([(b"A",), (b"B",)], dtype=[("Name", "S16")])
        group[prefix + " Info"] = [[0, count, 0, 1], [count, 2 * count, 1, 2]]
        # The second local offset equals the feature's global start. A per-part
        # heuristic incorrectly subtracts that start only from the second part.
        offsets = [0, count] if convention == "local" else [count, 2 * count]
        group[prefix + " Parts"] = [[0, count], *[(s, count) for s in offsets]]
        group[prefix + " Points"] = points
    if consumer == "collection":
        result = HdfMesh.get_mesh_areas(path)
        assert len(result) == 2
        actual = result.geometry.iloc[1]
    else:
        with h5py.File(path, "r") as hdf:
            result = _read_lines(hdf, group_path)
        assert len(result) == 2
        actual = result[1]["geometry"]
    assert actual.equals(expected)
    for actual_part, expected_part in zip(actual.geoms, expected.geoms):
        actual_coords = actual_part.exterior.coords if consumer == "collection" else actual_part.coords
        expected_coords = expected_part.exterior.coords if consumer == "collection" else expected_part.coords
        np.testing.assert_array_equal(actual_coords, expected_coords)


@pytest.mark.parametrize("parts", [
    [[-1, 4], [4, 4]], [[0, -1]], [[0, 9]], [[0.5, 8]],
    [[4, 4], [9, 3]], [[4, 5], [8, 3]], [[4, 4], [8, 5]],
])
def test_whole_feature_rejects_invalid_bounds_and_noncovering_legacy_global(parts):
    with pytest.raises(ValueError):
        HdfBase._feature_part_ranges(np.array(parts), 4, 8)


@pytest.mark.parametrize("parts", [
    [[0, 3], [4, 4]], [[0, 5], [4, 3]], [[0, 4], [4, 3]],
])
def test_feature_local_gaps_shared_and_unused_vertices_preserve_exact_ranges(parts):
    assert HdfBase._feature_part_ranges(np.array(parts), 4, 8) == [tuple(p) for p in parts]


@pytest.mark.synthetic_hdf_layout(
    "polyline",
)
@pytest.mark.parametrize("consumer", ["collection", "polyline"])
def test_consumer_rejects_truncated_parts_table(tmp_path, consumer):
    path = tmp_path / "bad.g01.hdf"
    prefix = "Polygon" if consumer == "collection" else "Polyline"
    group_path = "Geometry/2D Flow Areas" if consumer == "collection" else "Geometry/2D Flow Area Break Lines"
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(group_path)
        group["Attributes"] = np.array([(b"A",)], dtype=[("Name", "S16")])
        group[prefix + " Info"] = [[0, 5, 0, 2]]
        group[prefix + " Points"] = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        group[prefix + " Parts"] = [[0, 5]]
    if consumer == "collection":
        # The public collection reader's established error contract is empty.
        assert HdfMesh.get_mesh_areas(path).empty
    else:
        with h5py.File(path, "r") as hdf, pytest.raises(RuntimeError, match="(?i)parts|truncated"):
            _read_lines(hdf, group_path)


@pytest.mark.parametrize("consumer", ["collection", "polyline"])
@pytest.mark.parametrize("defect", ["negative", "out_of_bounds_gap", "outside", "point_slice"])
def test_consumers_do_not_return_partial_geometry_for_malformed_slices(tmp_path, caplog, consumer, defect):
    path = tmp_path / "malformed.g01.hdf"
    polygon = consumer == "collection"
    prefix = "Polygon" if polygon else "Polyline"
    group_path = "Geometry/2D Flow Areas" if polygon else "Geometry/2D Flow Area Break Lines"
    count = 5 if polygon else 2
    shape = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]) if polygon else np.array([[0, 0], [1, 0]])
    parts = [[0, count], [0, count], [count, count]]
    info = [[0, count, 0, 1], [count, 2 * count, 1, 2]]
    if defect == "negative":
        parts[1][0] = -1
    elif defect == "out_of_bounds_gap":
        parts[2][0] += 1
    elif defect == "outside":
        parts[2][1] += 1
    else:
        info[1][1] += 1
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(group_path)
        group["Attributes"] = np.array([(b"A",), (b"B",)], dtype=[("Name", "S16")])
        group[prefix + " Info"] = info
        group[prefix + " Parts"] = parts
        group[prefix + " Points"] = np.vstack([shape, shape + 10, shape + 20])
    if polygon:
        assert HdfMesh.get_mesh_areas(path).empty
        assert "Error reading mesh areas" in caplog.text
        assert str(path) in caplog.text
    else:
        with h5py.File(path, "r") as hdf, pytest.raises(RuntimeError):
            _read_lines(hdf, group_path)
