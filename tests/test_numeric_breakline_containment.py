"""Bound numeric endpoint repairs without relaxing compiled containment."""

from copy import deepcopy
from importlib import import_module

import pytest
from shapely.geometry import LineString, Polygon, box

module = import_module("ras_commander.RasBreakout2D")


def test_numeric_endpoint_repair_keeps_identity_controls_and_inputs():
    perimeter = box(0, 0, 100, 100)
    specs = [
        {
            "name": "Road",
            "coords": [(9.999, 50), (60, 50)],
            "cell_size_near": 2,
            "cell_size_far": 4,
            "near_repeats": 3,
            "protection_radius": 5,
        },
        {"name": "Inside", "coords": [(30, 20), (40, 20)]},
    ]
    original = deepcopy(specs)
    revised, record = module._plan_numeric_breakline_containment(
        perimeter, specs, {"Road"}, 10
    )
    assert specs == original
    assert revised[1] == specs[1]
    assert {key: value for key, value in revised[0].items() if key != "coords"} == {
        key: value for key, value in specs[0].items() if key != "coords"
    }
    assert perimeter.buffer(-10).covers(LineString(revised[0]["coords"]))
    assert 0 < record["repairs"][0]["geometry_displacement"] < 0.01
    assert record["perimeter_unchanged"] and record["native_controls_unchanged"]


@pytest.mark.parametrize("coords", [[(9.98, 50), (60, 50)], [(0, 0), (1, 0)]])
def test_material_deficit_or_empty_fragment_is_rejected(coords):
    with pytest.raises(ValueError):
        module._plan_numeric_breakline_containment(
            box(0, 0, 100, 100), [{"name": "Road", "coords": coords}], {"Road"}, 10
        )


def test_disconnected_repair_cannot_split_a_retained_line():
    perimeter = Polygon(
        [(0, 0), (10, 0), (10, 10), (6, 10), (6, 4), (4, 4), (4, 10), (0, 10)]
    )
    with pytest.raises(ValueError, match="drop or split"):
        module._plan_numeric_breakline_containment(
            perimeter, [{"name": "Road", "coords": [(2, 8), (8, 8)]}], {"Road"}, 0.1
        )
