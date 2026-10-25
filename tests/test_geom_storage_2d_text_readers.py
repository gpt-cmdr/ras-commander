"""Read native 16-character XY records independently of compiled geometry.

Fixtures retain the saved packed-coordinate layouts, including a one-point
breakline; no engine execution or derived mesh generation is involved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ras_commander.geom.GeomStorage import GeomStorage


def _coords(*pairs: tuple[float, float]) -> str:
    """Two pairs per 16-char fixed-width line: the 2D Points / BreakLine layout."""
    flat: list[float] = []
    for x, y in pairs:
        flat.extend([x, y])
    out = []
    for i in range(0, len(flat), 4):
        out.append("".join(f"{v:16.6f}" for v in flat[i:i + 4]))
    return "\n".join(out) + "\n"


def _surface_coords(*pairs: tuple[float, float]) -> str:
    """ONE pair per line: the Storage Area Surface Line layout.

    The two layouts genuinely differ, and the difference is load-bearing.
    Measured in 08040207/LowerOuachita.g12: a Surface Line row is 32 columns
    (one pair) while a 2D Points row and a BreakLine Polyline row are both 64
    (two pairs). ``get_storage_area_polygons`` consumes exactly ``count``
    LINES, so a fixture that packs two pairs per surface line reads half the
    ring and then tries to float() the next keyword.
    """
    return "".join(f"{x:16.6f}{y:16.6f}\n" for x, y in pairs)


# `Breakline 495` is verbatim from 12060204/NorthBosque1.g01, including the
# empty CellSize fields and `Protection Radius=-1` that the 6.10 writer emits.
_DEGENERATE_BLOCK = (
    "BreakLine Name=Breakline 495\n"
    "BreakLine CellSize Min=\n"
    "BreakLine CellSize Max=\n"
    "BreakLine Near Repeats=0\n"
    "BreakLine Protection Radius=-1\n"
    "BreakLine Polyline= 1 \n"
    "2981557.5399785110695300.2920647\n"
)


def _geom(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "model.g01"
    path.write_text(body, encoding="utf-8")
    return path


def _two_d_area() -> str:
    return (
        "Geom Title=Fixture\n"
        "Program Version=6.10\n"
        "Storage Area=Perimeter 1     ,,\n"
        "Storage Area Surface Line= 4 \n"
        + _surface_coords((0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0))
        + "Storage Area Type= 1 \n"
        "Storage Area Is2D=-1\n"
        "Storage Area 2D Points= 4 \n"
        + _coords((250.0, 250.0), (750.0, 250.0)) + _coords((750.0, 750.0), (250.0, 750.0))
        + "Storage Area Mannings=0.06\n"
    )


# --------------------------------------------------------------- breaklines

def test_breaklines_are_read_with_their_spacing(tmp_path):
    body = _two_d_area() + (
        "BreakLine Name=WestLevee\n"
        "BreakLine CellSize Min=25\n"
        "BreakLine CellSize Max=75\n"
        "BreakLine Near Repeats=0\n"
        "BreakLine Polyline= 3 \n"
        + _coords((10.0, 10.0), (20.0, 20.0)) + _coords((30.0, 30.0))
    )
    frame = GeomStorage.get_breaklines(_geom(tmp_path, body))
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["Name"] == "WestLevee"
    assert row["cell_size_min"] == 25.0
    assert row["cell_size_max"] == 75.0
    assert row["declared_points"] == 3
    assert list(row.geometry.coords) == [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]
    assert frame.attrs["skipped_degenerate"] == []


def test_a_one_point_breakline_is_skipped_not_fatal(tmp_path):
    """The real NorthBosque1 case: one bad block must not cost the other good one."""
    body = _two_d_area() + _DEGENERATE_BLOCK + (
        "BreakLine Name=GoodLine\n"
        "BreakLine CellSize Min=\n"
        "BreakLine CellSize Max=\n"
        "BreakLine Polyline= 2 \n"
        + _coords((0.0, 0.0), (100.0, 100.0))
    )
    frame = GeomStorage.get_breaklines(_geom(tmp_path, body))
    assert list(frame["Name"]) == ["GoodLine"]
    assert frame.attrs["skipped_degenerate"] == ["Breakline 495"]
    # A blank CellSize is None, not 0.0 -- those mean different things to RAS.
    assert frame.iloc[0]["cell_size_min"] is None


def test_breakline_vertices_reconcile_against_their_declaration(tmp_path):
    body = _two_d_area() + (
        "BreakLine Name=Long\n"
        "BreakLine Polyline= 5 \n"
        + _coords((0.0, 0.0), (1.0, 1.0)) + _coords((2.0, 2.0), (3.0, 3.0))
        + _coords((4.0, 4.0))
    )
    frame = GeomStorage.get_breaklines(_geom(tmp_path, body))
    row = frame.iloc[0]
    assert len(row.geometry.coords) == row["declared_points"] == 5


def test_no_breaklines_returns_an_empty_typed_frame(tmp_path):
    frame = GeomStorage.get_breaklines(_geom(tmp_path, _two_d_area()))
    assert frame.empty
    assert "geometry" in frame.columns
    assert frame.attrs["skipped_degenerate"] == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        GeomStorage.get_breaklines(tmp_path / "absent.g01")


# ------------------------------------------------------- computation points

def test_computation_points_are_read_and_reconcile(tmp_path):
    frame = GeomStorage.get_2d_computation_points(_geom(tmp_path, _two_d_area()))
    assert len(frame) == 4
    assert frame.attrs["declared_counts"] == {"Perimeter 1": 4}
    assert len(frame) == sum(frame.attrs["declared_counts"].values())
    assert set(frame["flow_area"]) == {"Perimeter 1"}
    assert sorted((p.x, p.y) for p in frame.geometry) == [
        (250.0, 250.0), (250.0, 750.0), (750.0, 250.0), (750.0, 750.0)]


def test_the_declared_count_is_reported_even_when_filtered_out(tmp_path):
    frame = GeomStorage.get_2d_computation_points(
        _geom(tmp_path, _two_d_area()), flow_area_name="Nope")
    assert frame.empty
    # The declaration is still visible, so a caller can tell "filtered out"
    # from "the block was not there".
    assert frame.attrs["declared_counts"] == {"Perimeter 1": 4}




@pytest.mark.parametrize("count,payload", [
    ("-1", ""), ("bad", ""), ("2", _coords((0, 0))),
    ("1", _coords((0, 0), (1, 1))), ("1", _coords((float("nan"), 0))),
    ("1", "1 2\n"), ("1", _coords((0, 0)) + _coords((1, 1))),
])
@pytest.mark.parametrize("kind", ["breakline", "points"])
def test_malformed_payloads_raise_instead_of_returning_partial_data(tmp_path, count, payload, kind):
    if kind == "breakline":
        text = f"BreakLine Name=Broken\nBreakLine Polyline={count}\n" + payload
        reader = GeomStorage.get_breaklines
    else:
        text = f"Storage Area=Area,,\nStorage Area 2D Points={count}\n" + payload
        reader = GeomStorage.get_2d_computation_points
    with pytest.raises(ValueError):
        reader(_geom(tmp_path, text))


def test_multi_area_point_order_filter_and_read_only_contract(tmp_path):
    path = _geom(tmp_path, _two_d_area() + "Storage Area=Second,,\nStorage Area 2D Points=1\n" + _coords((1, 2)))
    before = path.read_bytes()
    frame = GeomStorage.get_2d_computation_points(str(path), "Second")
    assert frame.attrs["declared_counts"] == {"Perimeter 1": 4, "Second": 1}
    assert list(frame.point_index) == [0]
    assert list(frame.flow_area) == ["Second"]
    assert frame.crs is None
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))


def test_filtered_malformed_points_are_not_silently_accepted(tmp_path):
    path = _geom(tmp_path, "Storage Area=Other,,\nStorage Area 2D Points=2\n" + _coords((1, 2)))
    with pytest.raises(ValueError):
        GeomStorage.get_2d_computation_points(path, "Selected")


def test_empty_frames_match_declared_schemas(tmp_path):
    from ras_commander.schemas import DATAFRAME_SCHEMAS
    path = _geom(tmp_path, "Geom Title=Empty\n")
    for key, reader in [("geometry_breaklines", GeomStorage.get_breaklines),
                        ("geometry_2d_computation_points", GeomStorage.get_2d_computation_points)]:
        frame = reader(path)
        assert list(frame.columns) == [col["name"] for col in DATAFRAME_SCHEMAS[key]["columns"]]
        assert frame.crs is None and frame.empty
        integer_column = "declared_points" if key == "geometry_breaklines" else "point_index"
        assert str(frame[integer_column].dtype) == "int64"


def test_real_chippewa_points_and_breakline_writer_roundtrip(tmp_path):
    from ras_commander import RasExamples
    project = Path(RasExamples.extract_project("Chippewa_2D", output_path=tmp_path))
    # No initialized RasPrj/DataFrame exists: inspect the extracted source file.
    path = project / "Chippewa_2D.g01"
    before = path.read_bytes()
    points = GeomStorage.get_2d_computation_points(path)
    assert points.attrs["declared_counts"] == {"Perimeter 1": 354}
    assert len(points) == 354
    assert points.iloc[0].geometry.x == pytest.approx(1026293.68220132)
    assert points.iloc[0].geometry.y == pytest.approx(7857287.29329869)
    assert path.read_bytes() == before
    coords = [(point.x, point.y) for point in points.geometry.iloc[:3]]
    GeomStorage.set_breaklines(path, "Perimeter 1", [{
        "name": "Reader roundtrip", "coords": coords,
        "cell_size_near": 25, "cell_size_far": 75,
    }])
    authored = path.read_bytes()
    lines = GeomStorage.get_breaklines(path)
    row = lines.loc[lines.Name == "Reader roundtrip"].iloc[0]
    assert list(row.geometry.coords) == pytest.approx(coords, abs=1e-6)
    assert row.cell_size_min == 25 and row.cell_size_max == 75
    assert path.read_bytes() == authored


@pytest.mark.parametrize("reader", [GeomStorage.get_breaklines, GeomStorage.get_2d_computation_points])
def test_both_readers_reject_missing_files(tmp_path, reader):
    with pytest.raises(FileNotFoundError):
        reader(tmp_path / "missing.g01")


@pytest.mark.parametrize("text", [
    "Storage Area 2D Points=0\n",
    "Storage Area=A,,\nStorage Area 2D Points=0\nStorage Area=A,,\nStorage Area 2D Points=0\n",
])
def test_points_require_unique_named_area_declarations(tmp_path, text):
    with pytest.raises(ValueError):
        GeomStorage.get_2d_computation_points(_geom(tmp_path, text))


def test_breakline_missing_polyline_does_not_borrow_next_blocks_coordinates(tmp_path):
    text = "BreakLine Name=Missing\nBreakLine Name=Next\nBreakLine Polyline=2\n" + _coords((1, 2), (3, 4))
    with pytest.raises(ValueError, match="no polyline"):
        GeomStorage.get_breaklines(_geom(tmp_path, text))


@pytest.mark.parametrize("spacing", ["nan", "inf", "invalid"])
def test_breakline_spacing_must_be_finite_or_blank(tmp_path, spacing):
    text = f"BreakLine Name=Bad\nBreakLine CellSize Min={spacing}\nBreakLine Polyline=2\n" + _coords((1, 2), (3, 4))
    with pytest.raises(ValueError):
        GeomStorage.get_breaklines(_geom(tmp_path, text))
