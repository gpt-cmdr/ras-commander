"""Native ring serialization must not introduce zero-length perimeter edges."""

import pytest
from ras_commander.geom.GeomStorage import GeomStorage


def test_plan_removes_only_adjacent_serialized_duplicates_without_mutation(tmp_path):
    x, y = 2_000_000.0, 14_000_000.0
    points = [
        (x, y),
        (x + 2e-10, y),
        (x + 100, y),
        (x + 100, y + 100),
        (x + 100 - 0.003, y + 100),
        (x, y + 100),
        (x, y),
    ]
    original = list(points)
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=points)
    assert points == original
    assert plan["removed_adjacent_vertex_indexes"] == [1]
    assert plan["source_vertex_count"] == 6 and plan["authored_vertex_count"] == 5
    assert plan["coordinates"][2:4] == points[3:5]
    path = tmp_path / "test.g01"
    path.write_text("Geom Title=Test\n")
    GeomStorage.set_2d_flow_area_perimeter(
        path, "AREA", coordinates=points, create_backup=False
    )
    ring = GeomStorage.get_storage_area_polygons(path, exclude_2d=False).geometry.iloc[
        0
    ]
    coords = list(ring.exterior.coords)
    assert all(a != b for a, b in zip(coords[:-1], coords[1:]))
    assert len(coords) == 6
    assert ring.is_valid


def test_serialized_closing_duplicate_is_removed_and_ring_closed():
    points = [(2e6, 14e6), (2e6 + 100, 14e6), (2e6, 14e6 + 100), (2e6 + 2e-10, 14e6)]
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=points)
    assert plan["coordinates"][0] == plan["coordinates"][-1]
    assert plan["authored_vertex_count"] == 3


def test_collapsed_ring_fails_closed():
    with pytest.raises(ValueError, match="distinct serialized"):
        GeomStorage.plan_2d_flow_area_perimeter(
            coordinates=[(2e6, 14e6), (2e6 + 2e-9, 14e6), (2e6, 14e6 + 2e-9)]
        )


def test_repeated_closure_duplicates_keep_original_source_indexes():
    points = [
        (2e6, 14e6),
        (2e6 + 100, 14e6),
        (2e6, 14e6 + 100),
        (2e6 + 2e-10, 14e6),
        (2e6 + 4e-10, 14e6),
    ]
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=points)
    assert plan["removed_adjacent_vertex_indexes"] == [3, 4]
    assert plan["coordinates"] == points[:3] + [points[0]]
    assert plan["source_valid"] is False
    assert plan["authored_valid"] is True


def test_near_duplicate_normalization_preserves_real_small_edges_and_records_geometry():
    from shapely.geometry import Polygon
    import hashlib

    x, y = 2e6, 14e6
    points = [
        (x, y),
        (x + 4e-7, y),
        (x + 100, y),
        (x + 100, y + 100),
        (x + 100 - 0.003, y + 100),
        (x, y + 100),
    ]
    original = list(points)
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=points)
    assert points == original
    assert plan["removed_adjacent_vertex_indexes"] == [1]
    assert plan["reason_code"] == "ADJACENT_NEAR_DUPLICATE_PERIMETER"
    assert plan["near_duplicate_tolerance"] == 1e-6
    assert plan["coordinates"][2:4] == points[3:5]
    assert (
        plan["source_ring_wkb_sha256"]
        == hashlib.sha256(Polygon(points).wkb).hexdigest()
    )
    assert plan["authored_valid"] and plan["source_valid"]
    assert plan["boundary_displacement"] <= 1e-6
    assert abs(plan["area_change"]) < 1e-3


def test_adjacent_near_duplicate_chains_do_not_accumulate_displacement():
    x, y = 2e6, 14e6
    points = [
        (x, y),
        (x + 0.8e-6, y),
        (x + 1.6e-6, y),
        (x + 2.4e-6, y),
        (x + 100, y),
        (x + 100, y + 100),
        (x, y + 100),
    ]
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=points)
    assert plan["removed_adjacent_vertex_indexes"] == [1, 3]
    assert points[2] in plan["coordinates"]


def test_invalid_normalized_ring_fails_closed():
    with pytest.raises(ValueError, match="valid polygons"):
        GeomStorage.plan_2d_flow_area_perimeter(
            coordinates=[(0, 0), (100, 100), (0, 100), (100, 0)]
        )
