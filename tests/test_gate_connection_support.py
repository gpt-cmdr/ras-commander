"""Explicit gate GIS support and fail-closed native decisions."""

import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander.geom.GeomLateral import GeomLateral


@pytest.fixture
def gate_geometry(tmp_path):
    path = tmp_path / "gate.g01"
    path.write_text("Geom Title=Gate\nStorage Area=A,0,0\nBC Line Name=outlet\n")
    GeomLateral.set_connection(
        path, "gate", [(2, 5), (8, 5)], "A", "A", weir_width=2, weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0., 6.], "Elevation": [10., 10.]}),
    )
    GeomLateral.set_connection_gates(path, "gate", pd.DataFrame([{
        "GateName": "group", "Width": 2., "Height": 3., "InvertElevation": 5.,
        "GateCoefficient": .6, "GateType": 2, "NumOpenings": 1,
        "OpeningStations": [3.],
    }]))
    text = path.read_text()
    coordinates = "".join(f"{v:16.8f}" for v in [5, 3, 5, 7]) + "\n"
    path.write_text(text.replace(
        "Conn Gate Opening=1,Opening #1,0", "Conn Gate Opening=1,opening,2\n" + coordinates
    ))
    return path


@pytest.mark.parametrize("boundary,action", [
    (box(0, 0, 10, 10), "keep"), (box(20, 20, 30, 30), "drop"),
    (box(0, 0, 5, 10), "block"),
])
def test_gate_full_support_and_lossless_inventory(gate_geometry, boundary, action):
    before = gate_geometry.read_bytes()
    row = GeomLateral.classify_connections(gate_geometry, boundary).iloc[0]
    assert row.action == action
    assert row.gate_group_count == 1
    assert row.geometry.covers(box(4.5, 3, 5.5, 7))
    GeomLateral.write_connection_data(gate_geometry, GeomLateral.get_connection_data(gate_geometry))
    assert gate_geometry.read_bytes() == before


def test_missing_declared_gate_coordinate_holds(gate_geometry):
    gate_geometry.write_text(gate_geometry.read_text().replace("opening,2", "opening,3"))
    with pytest.raises(ValueError):
        GeomLateral.get_connection_gate_lines(gate_geometry, "gate")
    assert GeomLateral.classify_connections(gate_geometry, box(0, 0, 10, 10)).iloc[0].action == "block"


def test_unknown_record_still_holds(gate_geometry):
    text = gate_geometry.read_text().replace("Conn Weir WD=", "Unknown Spatial Object=4\nConn Weir WD=")
    gate_geometry.write_text(text)
    assert GeomLateral.classify_connections(gate_geometry, box(0, 0, 10, 10)).iloc[0].action == "block"


def test_duplicate_opening_index_holds(gate_geometry):
    text = gate_geometry.read_text()
    start = text.index("Conn Gate Opening=")
    end = text.index("BC Line Name=", start)
    gate_geometry.write_text(text[:end] + text[start:end] + text[end:])
    with pytest.raises(ValueError, match="indexes"):
        GeomLateral.get_connection_gate_lines(gate_geometry, "gate")


def test_area_mapping_changes_only_endpoint_records_on_a_clone(gate_geometry, tmp_path):
    before = gate_geometry.read_bytes()
    mapped = GeomLateral.remap_connection_areas(str(gate_geometry), {"A": "child"})
    assert gate_geometry.read_bytes() == before
    expected = GeomLateral.get_connection_data(gate_geometry).RawBlock.iloc[0]
    expected = expected.replace("Connection Up SA=A", "Connection Up SA=child")
    expected = expected.replace("Connection Dn SA=A", "Connection Dn SA=child")
    assert mapped.RawBlock.iloc[0] == expected
    child = tmp_path / "child.g01"
    child.write_text("Geom Title=Child\nStorage Area=child,0,0\nBC Line Name=outlet\n")
    GeomLateral.write_connection_data(child, mapped)
    decoded = GeomLateral.get_connection_data(child).iloc[0]
    assert decoded.From == decoded.To == "child"
    assert decoded.RawBlock == expected


def test_area_mapping_rejects_ambiguous_endpoints_and_invalid_names(gate_geometry):
    with pytest.raises(ValueError):
        GeomLateral.remap_connection_areas(gate_geometry, {"A": "bad\nname"})
    text = gate_geometry.read_text()
    gate_geometry.write_text(text.replace("Connection Up SA=A", "Connection Up SA=A\nFrom 2D Area=A"))
    with pytest.raises(ValueError, match="ambiguous"):
        GeomLateral.remap_connection_areas(gate_geometry, {"A": "child"})


def test_nonfinite_gate_width_holds(gate_geometry):
    text = gate_geometry.read_text()
    lines = text.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("Conn Gate Name"))
    fields = lines[index + 1].rstrip().split(',')
    fields[1] = "nan"
    lines[index + 1] = ','.join(fields) + '\n'
    gate_geometry.write_text(''.join(lines))
    assert GeomLateral.classify_connections(gate_geometry, box(0, 0, 10, 10)).iloc[0].action == "block"


def test_undeclared_extra_gate_coordinates_hold(gate_geometry):
    lines = gate_geometry.read_text().splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("Conn Gate Opening="))
    lines.insert(index + 2, f"{8:16.8f}{9:16.8f}\n")
    gate_geometry.write_text(''.join(lines))
    with pytest.raises(ValueError, match="coordinates"):
        GeomLateral.get_connection_gate_lines(gate_geometry, "gate")
