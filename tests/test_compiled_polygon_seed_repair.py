import numpy as np
import pytest

from ras_commander.geom.GeomMeshRepair import GeomMeshRepair


def row(index=1, **kwargs):
    return dict(
        cell_id=index,
        reason_code="no_polygon",
        status="omitted",
        face_count=5,
        polygon_count=0,
        mesh_name="A",
        **kwargs,
    )


def test_physical_omission_requires_complete_index_match_and_preserves_inputs():
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    diagnostics = [row(), row(3)]
    before = xy.copy()
    plan = GeomMeshRepair.plan_compiled_polygon_seed_removal(xy, xy.copy(), diagnostics)
    assert plan["removed_points"] == [
        {"generated_point_index": 1, "x": 1.0, "y": 1.0, "polygon_diagnostic": row()}
    ]
    assert plan["physical_cell_count"] == 3 and plan["perimeter_changed"] is False
    np.testing.assert_array_equal(xy, before)
    assert diagnostics == [row(), row(3)]


@pytest.mark.parametrize(
    "diagnostics",
    [
        [row(), row()],
        [row(index=1.5)],
        [{**row(), "face_count": 1}],
        [{**row(), "polygon_count": 1}],
        [{**row(), "status": "boundary_only"}],
    ],
)
def test_invalid_physical_diagnostics_fail_closed(diagnostics):
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    with pytest.raises(ValueError):
        GeomMeshRepair.plan_compiled_polygon_seed_removal(xy, xy, diagnostics)


@pytest.mark.parametrize(
    "compiled",
    [
        np.zeros((2, 2)),
        [[0, 0], [1.00001, 1], [2, 2]],
        [[0, 0], [float("nan"), 1], [2, 2]],
    ],
)
def test_no_count_or_coordinate_waiver(compiled):
    with pytest.raises(ValueError):
        GeomMeshRepair.plan_compiled_polygon_seed_removal(
            [[0, 0], [1, 1], [2, 2]], compiled, [row()]
        )


def test_budget_and_exhaustion_remain_holds():
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    with pytest.raises(ValueError, match="budget"):
        GeomMeshRepair.plan_compiled_polygon_seed_removal(
            xy, xy, [row(0), row(1)], max_removals=1
        )
    with pytest.raises(ValueError, match="budget"):
        GeomMeshRepair.plan_compiled_polygon_seed_removal(
            xy, xy, [row(i) for i in range(3)]
        )


def test_unrelated_topology_conditions_never_authorize_removal():
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    plan = GeomMeshRepair.plan_compiled_polygon_seed_removal(
        xy, xy, [{**row(), "reason_code": "missing_face_reference"}]
    )
    assert plan["removed_points"] == []
