"""Native input-index contracts without requiring a physical cell collection."""

from types import SimpleNamespace

import numpy as np
import pytest

from ras_commander.geom.GeomMeshRepair import GeomMeshRepair


class Seeds(list):
    @property
    def Count(self):
        return len(self)


def points():
    return Seeds([SimpleNamespace(X=x, Y=y) for x, y in [(1, 2), (1.00001, 2), (3, 4)]])


class DuplicateMesh:
    MeshCompletionState = "DuplicatePoints"

    def __init__(self, indexes):
        self.BadIndexes = indexes

    @property
    def NonVirtualCellCount(self):
        pytest.fail("DuplicatePoints has no physical cell collection")

    def Cell(self, _index):
        pytest.fail("DuplicatePoints indexes refer to input seeds")


def test_native_duplicate_plan_preserves_inputs_and_records_index_basis():
    seeds, mesh = points(), DuplicateMesh([1, 1])
    before = [(point.X, point.Y) for point in seeds]
    plan = GeomMeshRepair.plan_native_seed_removal(mesh, seeds)
    assert plan["removed_points"] == [
        {"generated_point_index": 1, "x": 1.00001, "y": 2.0}
    ]
    assert plan["index_basis"] == "native_duplicate_points_input_seed"
    assert plan["native_bad_index_count"] == 2
    assert plan["serialized_point_count"] == 3
    assert not plan["perimeter_changed"] and not plan["features_changed"]
    assert before == [(point.X, point.Y) for point in seeds]
    assert mesh.BadIndexes == [1, 1]


@pytest.mark.parametrize(
    "indexes",
    [
        [3],
        [-1],
        [1.5],
        [True],
        [np.bool_(True)],
        [None],
        ["1"],
        ["bad"],
        [float("nan")],
        [],
        [0, 1, 2],
    ],
)
def test_native_duplicate_plan_rejects_unbound_indexes_or_exhaustion(indexes):
    with pytest.raises(ValueError):
        GeomMeshRepair.plan_native_seed_removal(DuplicateMesh(indexes), points())


def test_native_duplicate_removal_budget_is_not_a_tolerance_waiver():
    with pytest.raises(ValueError, match="budget"):
        GeomMeshRepair.plan_native_seed_removal(
            DuplicateMesh([0, 1]), points(), max_removals=1
        )
    seeds = points()
    seeds[2].X = float("nan")
    with pytest.raises(ValueError, match="finite"):
        GeomMeshRepair.plan_native_seed_removal(DuplicateMesh([1]), seeds)


def test_missing_native_indexes_hold():
    with pytest.raises(ValueError, match="unavailable"):
        GeomMeshRepair.plan_native_seed_removal(
            SimpleNamespace(MeshCompletionState="DuplicatePoints"), points()
        )


def test_native_integer_scalar_indexes_are_supported():
    plan = GeomMeshRepair.plan_native_seed_removal(
        DuplicateMesh([np.int32(1)]), points()
    )
    assert plan["removed_points"][0]["generated_point_index"] == 1


@pytest.mark.parametrize("budget", [False, 0, 8193, 1.5])
def test_native_removal_budget_requires_a_bounded_integer(budget):
    with pytest.raises(ValueError, match="budget"):
        GeomMeshRepair.plan_native_seed_removal(
            DuplicateMesh([1]), points(), max_removals=budget
        )


def test_unrelated_native_state_never_authorizes_seed_removal():
    plan = GeomMeshRepair.plan_native_seed_removal(
        SimpleNamespace(MeshCompletionState="PerimeterPolygonError"), points()
    )
    assert plan["removed_points"] == []
