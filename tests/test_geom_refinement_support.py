"""Geometric repair plans retain source controls and clipped coverage."""

import numpy as np
import pytest
from shapely.geometry import Point, box

from ras_commander.geom.GeomMeshRepair import GeomMeshRepair

plan_refinement_support = GeomMeshRepair.plan_refinement_support


@pytest.mark.parametrize("alteration", ["existing", "outside", "hash"])
def test_apply_rejects_unbound_or_exterior_point_plan(tmp_path, alteration):
    import hashlib

    apply_refinement_support = GeomMeshRepair.apply_refinement_support

    path = tmp_path / "child.g01"

    def coordinates(values):
        return "".join(f"{v:16.8f}" for v in values) + "\n"

    path.write_text(
        "Storage Area=A,0,0\nStorage Area Surface Line= 5\n"
        + coordinates([0, 0, 10, 0])
        + coordinates([10, 10, 0, 10])
        + coordinates([0, 0])
        + "Storage Area Is2D=-1\nStorage Area 2D Points= 1\n"
        + coordinates([2, 2]),
        encoding="utf-8",
    )
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    original = [[3, 3]] if alteration == "existing" else [[2, 2]]
    added = [[11, 11]] if alteration == "outside" else [[5, 5]]
    with pytest.raises(ValueError):
        apply_refinement_support(
            path,
            "A",
            original,
            {"added_points": added},
            expected_geometry_sha256="0" * 64 if alteration == "hash" else digest,
        )
    assert path.read_bytes() == before


def test_invalid_crossing_refinement_is_repaired_before_preflight_intersection():
    from importlib import import_module

    import geopandas as gpd
    import pandas as pd
    from shapely import make_valid
    from shapely.geometry import Polygon

    module = import_module("ras_commander.RasBreakout2D")
    source = Polygon([(1, 1), (9, 9), (1, 9), (9, 1)])
    child = box(0, 0, 5, 10)
    parent = gpd.GeoDataFrame(
        {"mesh_name": ["A"]}, geometry=[box(0, 0, 10, 10)], crs=2277
    )
    regions = gpd.GeoDataFrame(
        {"rr_id": [121], "Name": ["invalid"]}, geometry=[source], crs=2277
    )
    before = source.wkb
    actions = module._build_feature_actions(
        parent, child, {"refinement_region": regions}, pd.DataFrame(), child
    )
    row = actions.loc[actions.feature_type.eq("refinement_region")].iloc[0]
    assert row.action == "clip"
    assert row.geometry.equals(make_valid(source).intersection(child))
    assert row.reason.startswith("repaired_source_refinement_geometry:")
    assert source.wkb == before


def test_native_seed_removal_requires_identical_indexed_cell_point():
    from types import SimpleNamespace

    plan_native_seed_removal = GeomMeshRepair.plan_native_seed_removal

    class Seeds(list):
        @property
        def Count(self):
            return len(self)

    seeds = Seeds([SimpleNamespace(X=1, Y=2), SimpleNamespace(X=3, Y=4)])
    mesh = SimpleNamespace(
        MeshCompletionState="CellMinFaceError",
        NonVirtualCellCount=2,
        CellFacesCount=lambda i: 2,
        Cell=lambda i: SimpleNamespace(Point=seeds[0]),
    )
    result = plan_native_seed_removal(mesh, seeds)
    assert result["removed_points"] == [
        {"generated_point_index": 0, "x": 1.0, "y": 2.0}
    ]
    assert not result["perimeter_changed"]
    mesh.MeshCompletionState = "UnknownError"
    assert not plan_native_seed_removal(mesh, seeds)["removed_points"]


def test_sliver_support_includes_interior_grid_and_preserves_inputs():
    perimeter, region = box(0, 0, 100, 100), box(30, 30, 31, 32)
    existing = np.array([[20.0, 20.0], [40.0, 40.0]])
    before = existing.copy(), region.wkb
    controls = [
        {"name": "sliver", "geometry": region, "spacing_dx": 10, "spacing_dy": 10}
    ]
    result = plan_refinement_support(perimeter, controls, existing)
    assert any(region.contains(Point(p)) for p in result["added_points"])
    assert all(perimeter.contains(Point(p)) for p in result["added_points"])
    assert result["regions"][0]["support_spacing"] <= 1 / 6
    assert result["regions"][0]["source_spacing"] == [10.0, 10.0]
    np.testing.assert_array_equal(existing, before[0])
    assert region.wkb == before[1]
    assert not result["features_changed"]
    assert not result["source_spacing_changed"]


def test_candidate_budget_fails_before_mutation():
    existing = np.array([[1.0, 1.0]])
    controls = [
        {
            "name": "long sliver",
            "geometry": box(10, 10, 99, 10.01),
            "spacing_dx": 10,
            "spacing_dy": 10,
        }
    ]
    with pytest.raises(ValueError, match="budget"):
        plan_refinement_support(box(0, 0, 100, 100), controls, existing)
    np.testing.assert_array_equal(existing, [[1.0, 1.0]])


def test_retry_is_bounded_and_deterministic():
    controls = [
        {
            "name": "region",
            "geometry": box(10, 10, 12, 12),
            "spacing_dx": 1,
            "spacing_dy": 1,
        }
    ]
    points = np.empty((0, 2))
    first = plan_refinement_support(box(0, 0, 20, 20), controls, points)
    retry = plan_refinement_support(box(0, 0, 20, 20), controls, points, attempt=1)
    assert (
        retry["regions"][0]["support_spacing"]
        == first["regions"][0]["support_spacing"] / 2
    )
    assert retry == plan_refinement_support(
        box(0, 0, 20, 20), controls, points, attempt=1
    )
    with pytest.raises(ValueError, match="bounded"):
        plan_refinement_support(box(0, 0, 20, 20), controls, points, attempt=3)


def test_rotated_support_uses_bounded_sites_on_the_identical_lattice():
    import math

    from shapely.affinity import rotate

    region = rotate(box(30, 30, 60, 31), 45)
    controls = [
        {"name": "rotated", "geometry": region, "spacing_dx": 10, "spacing_dy": 10}
    ]
    original = np.array([[20.0, 20.0]])
    before = original.copy(), region.wkb
    perimeter = box(0, 0, 100, 100)
    result = plan_refinement_support(perimeter, controls, original)
    assert result["candidate_count"] > 8192
    assert result["candidate_generation"] == "bounded_support_column_intersections"
    assert len(result["added_points"]) <= result["examined_candidate_count"] <= 8192
    assert result == plan_refinement_support(perimeter, controls, original)
    anchor = region.representative_point()
    spacing = result["regions"][0]["support_spacing"]
    support = region.buffer(spacing).intersection(perimeter)
    left, bottom, right, top = support.bounds
    expected = [
        [anchor.x + ix * spacing, anchor.y + iy * spacing]
        for ix in range(
            math.floor((left - anchor.x) / spacing),
            math.ceil((right - anchor.x) / spacing) + 1,
        )
        for iy in range(
            math.floor((bottom - anchor.y) / spacing),
            math.ceil((top - anchor.y) / spacing) + 1,
        )
        if support.contains(Point(anchor.x + ix * spacing, anchor.y + iy * spacing))
        and perimeter.contains(Point(anchor.x + ix * spacing, anchor.y + iy * spacing))
    ]
    assert result["added_points"] == expected
    assert result["regions"][0]["source_spacing"] == [10, 10]
    assert not result["perimeter_changed"] and not result["features_changed"]
    assert not result["source_spacing_changed"]
    np.testing.assert_array_equal(original, before[0])
    assert region.wkb == before[1]


def test_column_support_budget_accumulates_across_regions():
    from shapely.affinity import rotate

    region = rotate(box(30, 30, 60, 31), 45)
    record = {"name": "rotated", "geometry": region, "spacing_dx": 10, "spacing_dy": 10}
    original = np.array([[20.0, 20.0]])
    one = plan_refinement_support(box(0, 0, 100, 100), [record], original)
    with pytest.raises(ValueError, match="budget"):
        plan_refinement_support(
            box(0, 0, 100, 100),
            [record, {**record, "name": "second"}],
            original,
            max_points=one["examined_candidate_count"],
        )
    np.testing.assert_array_equal(original, [[20.0, 20.0]])
