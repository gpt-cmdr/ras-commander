"""Regression tests for GeomParser.get_river_centerlines()."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("shapely")

from ras_commander.geom.GeomParser import GeomParser


def _format_reach_xy_lines(points, whitespace=False):
    values = []
    for x_val, y_val in points:
        values.append(f"{x_val:16.7f}")
        values.append(f"{y_val:16.7f}")

    lines = []
    for i in range(0, len(values), 4):
        chunk = values[i:i + 4]
        if whitespace:
            lines.append(" ".join(value.strip() for value in chunk))
        else:
            lines.append("".join(chunk))

    return lines


def _write_geom_file(
    tmp_path,
    points,
    *,
    include_text_markers=False,
    whitespace=False,
):
    geom_lines = [
        "Geom Title=Centerline Regression Test",
        "Program Version=6.50",
        "River Reach=TestRiver    ,TestReach",
        f"Reach XY= {len(points)}",
    ]
    geom_lines.extend(_format_reach_xy_lines(points, whitespace=whitespace))

    if include_text_markers:
        geom_lines.append(
            f"Rch Text X Y={points[0][0]:.7f},{points[0][1]:.7f}"
        )
        geom_lines.append("Reverse River Text= 0 ")

    geom_lines.append("")
    geom_lines.append(
        "Type RM Length L Ch R = 1 ,5000.000,     0.0,     0.0,     0.0"
    )

    geom_file = tmp_path / "centerline_test.g01"
    geom_file.write_text("\n".join(geom_lines) + "\n", encoding="utf-8")
    return geom_file


def test_get_river_centerlines_parses_legacy_fixed_width_rows(tmp_path):
    points = [
        (12345678.1234567 + i * 12.5, 87654321.7654321 + i * 7.25)
        for i in range(6)
    ]
    geom_file = _write_geom_file(
        tmp_path,
        points,
        include_text_markers=True,
    )

    gdf = GeomParser.get_river_centerlines(geom_file)

    assert len(gdf) == 1
    assert gdf.iloc[0]["river"] == "TestRiver"
    assert gdf.iloc[0]["reach"] == "TestReach"

    coords = list(gdf.iloc[0].geometry.coords)
    assert len(coords) == len(points)
    assert coords[0] == pytest.approx(points[0])
    assert coords[-1] == pytest.approx(points[-1])


def test_get_river_centerlines_preserves_whitespace_rows(tmp_path):
    points = [
        (1000.0, 2000.0),
        (1100.5, 2100.5),
        (1201.0, 2201.0),
        (1302.5, 2302.5),
    ]
    geom_file = _write_geom_file(
        tmp_path,
        points,
        whitespace=True,
    )

    gdf = GeomParser.get_river_centerlines(geom_file)

    assert len(gdf) == 1
    coords = list(gdf.iloc[0].geometry.coords)
    assert len(coords) == len(points)
    assert coords == pytest.approx(points)
