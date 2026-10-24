"""Opt-in real failing-shape regressions; private geometry is never committed."""

import importlib
import json
import os
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString
from shapely.geometry.polygon import orient

from ras_commander.geom._cookie_containment import _plan_face_containment_perimeter


@pytest.fixture
def cases():
    path = os.environ.get("RAS_COOKIE_REGRESSION_CASES")
    if not path:
        pytest.skip(
            "set RAS_COOKIE_REGRESSION_CASES to the private failing-shape packet"
        )
    return json.loads(Path(path).read_text())


def test_real_native_face_crossing_concavity(cases):
    case = cases["face_concavity"]
    perimeters = gpd.read_parquet(case["perimeters"])
    perimeter = perimeters[perimeters.kind == "compiled"].geometry.item()
    faces = gpd.read_parquet(case["faces"])
    face = faces[faces.face_id == case["face_id"]].geometry.item()
    assert not perimeter.covers(face)
    assert face.difference(perimeter).length == pytest.approx(
        case["outside_length"], abs=1e-5
    )
    revised, evidence = _plan_face_containment_perimeter(
        perimeter, [face], case["cell_size"]
    )
    assert revised.covers(face)
    assert revised.difference(perimeter).area > 0
    assert evidence["area_lost"] == 0 and evidence["area_gained_fraction"] <= 0.001


def test_real_native_breakline_numeric_deficit(cases):
    case = cases["breakline_numeric"]
    perimeters = gpd.read_parquet(case["perimeters"])
    perimeter = perimeters[perimeters.kind == "compiled"].geometry.item()
    # The native collection ring is clockwise; the named-area public layer
    # retains the opposite orientation. Keep the real erosion input order.
    perimeter = orient(perimeter, sign=case["native_ring_orientation"])
    lines = gpd.read_parquet(case["breaklines"])
    line = lines[lines.Name == case["name"]].geometry.item()
    assert line.difference(
        perimeter.buffer(-case["cell_size"])
    ).length == pytest.approx(case["outside_length"], abs=1e-8)
    owner = importlib.import_module("ras_commander.RasBreakout2D")
    specs, evidence = owner._plan_numeric_breakline_containment(
        perimeter,
        [{"name": "Retained", "coords": list(line.coords)}],
        {"Retained"},
        case["cell_size"],
    )
    revised = LineString(specs[0]["coords"])
    assert perimeter.buffer(-case["cell_size"]).covers(revised)
    assert evidence["repairs"][0]["geometry_displacement"] <= 0.01
