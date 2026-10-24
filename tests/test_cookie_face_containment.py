"""Complete native face chords can cross a small re-entrant boundary wedge."""

import pytest
from shapely.geometry import LineString, Point, Polygon

from ras_commander.geom._cookie_containment import _plan_face_containment_perimeter


def test_face_with_inside_endpoints_crosses_concavity_then_is_contained():
    perimeter = Polygon(
        [(0, 0), (200, 0), (200, 200), (110, 200), (100, 199.5), (90, 200), (0, 200)]
    )
    face = LineString([(50, 199.8), (150, 199.8)])
    assert all(perimeter.covers(Point(p)) for p in face.coords)
    assert not perimeter.covers(face)
    revised, record = _plan_face_containment_perimeter(perimeter, [face], 200)
    assert revised.covers(face) and revised.covers(perimeter)
    assert record["area_lost"] == 0 and 0 < record["area_gained_fraction"] < 0.001
    assert (
        record["maximum_displacement"] == 1
        and record["native_completion_check_unchanged"]
    )
    assert not perimeter.covers(face)  # source remains unchanged


def test_material_face_protrusion_is_not_waived():
    perimeter = Polygon(
        [(0, 0), (200, 0), (200, 200), (110, 200), (100, 190), (90, 200), (0, 200)]
    )
    with pytest.raises(ValueError, match="bounds"):
        _plan_face_containment_perimeter(
            perimeter, [LineString([(50, 199), (150, 199)])], 200
        )


def test_already_contained_faces_do_not_change_the_perimeter():
    with pytest.raises(ValueError, match="No compiled face containment failure"):
        _plan_face_containment_perimeter(
            Polygon([(0, 0), (200, 0), (200, 200), (0, 200)]),
            [LineString([(10, 10), (30, 30)])],
            200,
        )
