"""Focused tests for storage-area-backed 2D flow area writing in .g## files."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

shapely = pytest.importorskip("shapely")
from shapely.geometry import Polygon

from ras_commander.geom import GeomParser, GeomStorage


def _format_xy_rows(points, *, values_per_line):
    values = []
    for x_coord, y_coord in points:
        values.extend([x_coord, y_coord])
    return GeomParser.format_fixed_width(
        values,
        column_width=16,
        values_per_line=values_per_line,
        precision=7,
    )


def _write_geom_file(tmp_path, lines):
    geom_file = tmp_path / "storage_2d_writer.g01"
    geom_file.write_text("".join(lines), encoding="utf-8")
    return geom_file


def test_set_2d_flow_area_perimeter_updates_existing_block_and_preserves_breaklines(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=2D Writer Regression Test\n",
            "Program Version=6.60\n",
            "Storage Area=Existing 2D,10.0000000,10.0000000\n",
            "Storage Area Surface Line= 4\n",
            *_format_xy_rows(
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)],
                values_per_line=2,
            ),
            "Storage Area Type= 0\n",
            "Storage Area Area=\n",
            "Storage Area Min Elev=\n",
            "Storage Area Is2D=-1\n",
            "Storage Area Point Generation Data=,,100,100\n",
            "Storage Area 2D Points= 2\n",
            *_format_xy_rows([(999.0, 999.0), (1001.0, 1001.0)], values_per_line=4),
            "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00\n",
            "Storage Area Mannings=0.04\n",
            "2D Cell Volume Filter Tolerance=0.01\n",
            "\n",
            "BreakLine BL-1\n",
            "River Reach=TestRiver    ,TestReach\n",
        ],
    )

    GeomStorage.set_2d_flow_area_perimeter(
        geom_file,
        "Existing 2D",
        coordinates=[
            (100.0, 200.0),
            (150.0, 200.0),
            (150.0, 250.0),
            (100.0, 250.0),
        ],
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")

    assert "Storage Area=Existing 2D,125.0000000,225.0000000" in updated_text
    assert "Storage Area Surface Line= 5" in updated_text
    assert "Storage Area 2D Points= 0" in updated_text
    assert "999.0000000" not in updated_text
    assert "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00" not in updated_text
    assert "Storage Area Point Generation Data=,,100,100" in updated_text
    assert "Storage Area Mannings=0.04" in updated_text
    assert "BreakLine BL-1" in updated_text


def test_set_2d_flow_area_perimeter_creates_new_block_from_polygon(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=2D Writer Regression Test\n",
            "Program Version=6.60\n",
            "River Reach=TestRiver    ,TestReach\n",
        ],
    )

    GeomStorage.set_2d_flow_area_perimeter(
        geom_file,
        "Watershed Area",
        geometry=Polygon([
            (0.0, 0.0),
            (20.0, 0.0),
            (20.0, 10.0),
            (0.0, 10.0),
        ]),
        point_generation_data=[None, None, 50, 75],
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")

    assert updated_text.index("Storage Area=Watershed Area") < updated_text.index("River Reach=")
    assert "Storage Area=Watershed Area,10.0000000,5.0000000" in updated_text
    assert "Storage Area Surface Line= 5" in updated_text
    assert "Storage Area Is2D=-1" in updated_text
    assert "Storage Area Point Generation Data=,,50,75" in updated_text
    assert "Storage Area Mannings=0.04" in updated_text
    assert "Storage Area 2D PointsPerimeterTime=" in updated_text


def test_set_2d_flow_area_settings_updates_text_settings_without_resetting_mesh_points(tmp_path):
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=2D Writer Regression Test\n",
            "Program Version=6.60\n",
            "Storage Area=Configurable 2D,10.0000000,10.0000000\n",
            "Storage Area Surface Line= 5\n",
            *_format_xy_rows(
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
                values_per_line=2,
            ),
            "Storage Area Type= 0\n",
            "Storage Area Area=\n",
            "Storage Area Min Elev=\n",
            "Storage Area Is2D=-1\n",
            "Storage Area Point Generation Data=,,100,100\n",
            "Storage Area 2D Points= 2\n",
            *_format_xy_rows([(999.0, 999.0), (1001.0, 1001.0)], values_per_line=4),
            "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00\n",
            "Storage Area Mannings=0.04\n",
            "2D Cell Volume Filter Tolerance=0.01\n",
            "\n",
            "River Reach=TestRiver    ,TestReach\n",
        ],
    )

    GeomStorage.set_2d_flow_area_settings(
        geom_file,
        "Configurable 2D",
        mannings_n=0.055,
        spatially_varied_mann_on_faces=True,
        composite_classification=False,
        cell_vol_tol=0.25,
        cell_min_area_fraction=0.15,
        face_profile_tol=0.35,
        face_area_tol=0.45,
        face_conv_ratio=0.55,
        laminar_depth=0.65,
        min_face_length_ratio=0.75,
        point_generation_data=[None, None, 125, 150],
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")
    settings_df = GeomStorage.get_2d_flow_area_settings(geom_file)
    row = settings_df.loc[settings_df["name"] == "Configurable 2D"].iloc[0]

    assert "Storage Area 2D Points= 2" in updated_text
    assert "999.0000000" in updated_text
    assert "Storage Area Point Generation Data=,,125,150" in updated_text
    assert "2D Multiple Face Mann n=-1" in updated_text
    assert "2D Composite LC=-1" not in updated_text

    assert row["mannings_n"] == pytest.approx(0.055)
    assert bool(row["spatially_varied_mann_on_faces"]) is True
    assert bool(row["composite_classification"]) is False
    assert row["cell_vol_tol"] == pytest.approx(0.25)
    assert row["cell_min_area_fraction"] == pytest.approx(0.15)
    assert row["face_profile_tol"] == pytest.approx(0.35)
    assert row["face_area_tol"] == pytest.approx(0.45)
    assert row["face_conv_ratio"] == pytest.approx(0.55)
    assert row["laminar_depth"] == pytest.approx(0.65)
    assert row["min_face_length_ratio"] == pytest.approx(0.75)
    assert row["point_generation_data"] == ",,125,150"
