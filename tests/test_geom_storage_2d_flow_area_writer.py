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
            "Storage Area=Existing 2D      ,10.0000000,10.0000000\n",
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
            "BreakLine Name=TestBreakline\n",
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
        recompute_centroid=True,
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
    assert "BreakLine Name=TestBreakline" in updated_text


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


def test_unchanged_perimeter_preserves_header_and_mesh_points(tmp_path):
    """No-op round-trip must preserve header X/Y, mesh points, and timestamp."""
    original_header = "Storage Area=TestArea       ,12345.6789012,67890.1234567\n"
    points_line = "Storage Area 2D Points= 42\n"
    time_line = "Storage Area 2D PointsPerimeterTime=15Mar2025 09:30:00\n"
    coords = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]

    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Preservation Test\n",
            "Program Version=6.60\n",
            original_header,
            "Storage Area Surface Line= 5\n",
            *_format_xy_rows(coords, values_per_line=2),
            "Storage Area Type= 0\n",
            "Storage Area Area=\n",
            "Storage Area Min Elev=\n",
            "Storage Area Is2D=-1\n",
            "Storage Area Point Generation Data=,,500,500\n",
            points_line,
            time_line,
            "Storage Area Mannings=0.04\n",
            "\n",
        ],
    )

    GeomStorage.set_2d_flow_area_perimeter(
        geom_file,
        "TestArea",
        coordinates=coords,
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")

    assert original_header.strip() in updated_text
    assert "Storage Area 2D Points= 42" in updated_text
    assert "Storage Area 2D PointsPerimeterTime=15Mar2025 09:30:00" in updated_text


def test_update_preserves_original_header_by_default(tmp_path):
    """When perimeter changes, header X/Y is preserved unless recompute_centroid=True."""
    original_header = "Storage Area=MyArea         ,999.1234567,888.7654321\n"
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Header Test\n",
            "Program Version=6.60\n",
            original_header,
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
            "Storage Area 2D Points= 0\n",
            "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00\n",
            "Storage Area Mannings=0.04\n",
            "\n",
        ],
    )

    # Update with new perimeter, default recompute_centroid=False
    GeomStorage.set_2d_flow_area_perimeter(
        geom_file,
        "MyArea",
        coordinates=[(50.0, 50.0), (150.0, 50.0), (150.0, 150.0), (50.0, 150.0)],
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")
    assert original_header.strip() in updated_text
    assert "Storage Area Surface Line= 5" in updated_text


def test_recompute_centroid_flag(tmp_path):
    """recompute_centroid=True recomputes header X/Y from the polygon."""
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Centroid Test\n",
            "Program Version=6.60\n",
            "Storage Area=CentroidTest    ,0.0000000,0.0000000\n",
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
            "Storage Area 2D Points= 0\n",
            "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00\n",
            "Storage Area Mannings=0.04\n",
            "\n",
        ],
    )

    GeomStorage.set_2d_flow_area_perimeter(
        geom_file,
        "CentroidTest",
        coordinates=[(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0)],
        recompute_centroid=True,
        create_backup=False,
    )

    updated_text = geom_file.read_text(encoding="utf-8")
    assert "Storage Area=CentroidTest,100.0000000,50.0000000" in updated_text


@pytest.mark.parametrize("bad_name", [
    "Area,Injected",
    "Area\nInjected",
    "Area=Injected",
    "Area\rInjected",
    "Area\x00Injected",
    "Area\tInjected",
])
def test_invalid_name_rejected(tmp_path, bad_name):
    """Names containing commas, newlines, or = must be rejected."""
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Name Validation Test\n",
            "Program Version=6.60\n",
        ],
    )
    with pytest.raises(ValueError, match="invalid characters"):
        GeomStorage.set_2d_flow_area_perimeter(
            geom_file,
            bad_name,
            coordinates=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
            create_backup=False,
        )


def test_invalid_name_rejected_in_settings(tmp_path):
    """set_2d_flow_area_settings also validates names."""
    geom_file = _write_geom_file(
        tmp_path,
        [
            "Geom Title=Name Validation Test\n",
            "Program Version=6.60\n",
        ],
    )
    with pytest.raises(ValueError, match="invalid characters"):
        GeomStorage.set_2d_flow_area_settings(
            geom_file,
            "Bad,Name",
            mannings_n=0.05,
            create_backup=False,
        )


@pytest.mark.parametrize("value,col_width", [
    (10.0, 16),
    (2009315.7, 16),
    (99999999.0, 16),
    (99.99999999999996, 16),     # rounding carry: 99.9… → 100
    (-99.99999999999996, 16),    # negative rounding carry
    (9999999.99999995, 16),      # large rounding carry
    (0.123456789, 16),           # sub-unit
    (-0.123456789, 16),          # negative sub-unit
    (0.0, 16),                   # zero
    (1e7, 16),                   # exactly 10M
])
def test_adaptive_precision_field_width(value, col_width):
    """Formatted string must never exceed column_width."""
    prec = GeomStorage._max_precision_for_field(value, col_width)
    formatted = f"{value:{col_width}.{prec}f}"
    assert len(formatted) <= col_width, (
        f"value={value}, prec={prec}, formatted={formatted!r} "
        f"is {len(formatted)} chars (max {col_width})"
    )


def test_adaptive_precision_maximizes_digits():
    """Verify precision is as high as possible within the width constraint."""
    prec = GeomStorage._max_precision_for_field(10.0, 16)
    assert prec >= 12

    prec = GeomStorage._max_precision_for_field(2009315.7, 16)
    assert prec >= 7


def test_surface_line_fields_never_exceed_16_chars():
    """End-to-end: every field in the formatted surface line fits 16 chars."""
    coords = [
        (2009315.70791633, 321138.385272103),
        (99.99999999999996, -99.99999999999996),
        (0.0, 9999999.99999995),
        (2009315.70791633, 321138.385272103),
    ]
    lines = GeomStorage._format_surface_line_lines(coords)
    for line in lines:
        raw = line.rstrip('\n')
        for i in range(0, len(raw), 16):
            field = raw[i:i+16]
            assert len(field) <= 16, f"Field {field!r} exceeds 16 chars"
