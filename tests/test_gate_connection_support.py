"""Explicit gate GIS support and fail-closed native decisions."""

import hashlib
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander.geom.GeomLateral import GeomLateral
from ras_commander.geom.GeomStorage import GeomStorage
from ras_commander.schemas import DATAFRAME_SCHEMAS


@pytest.fixture
def gate_geometry(tmp_path):
    path = tmp_path / "gate.g01"
    path.write_text("Geom Title=Gate\nStorage Area=A,0,0\nBC Line Name=outlet\n")
    GeomLateral.set_connection(
        path,
        "gate",
        [(2, 5), (8, 5)],
        "A",
        "A",
        weir_width=2,
        weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0.0, 6.0], "Elevation": [10.0, 10.0]}),
    )
    GeomLateral.set_connection_gates(
        path,
        "gate",
        pd.DataFrame(
            [
                {
                    "GateName": "group",
                    "Width": 2.0,
                    "Height": 3.0,
                    "InvertElevation": 5.0,
                    "GateCoefficient": 0.6,
                    "GateType": 2,
                    "NumOpenings": 1,
                    "OpeningStations": [3.0],
                }
            ]
        ),
    )
    text = path.read_text()
    coordinates = "".join(f"{v:16.8f}" for v in [5, 3, 5, 7]) + "\n"
    path.write_text(
        text.replace(
            "Conn Gate Opening=1,Opening #1,0",
            "Conn Gate Opening=1,opening,2\n" + coordinates,
        )
    )
    return path


@pytest.mark.parametrize(
    "boundary,action",
    [
        (box(0, 0, 10, 10), "keep"),
        (box(20, 20, 30, 30), "drop"),
        (box(0, 0, 5, 10), "block"),
    ],
)
def test_gate_full_support_and_lossless_inventory(gate_geometry, boundary, action):
    before = gate_geometry.read_bytes()
    row = GeomLateral.classify_connections(
        gate_geometry, boundary, allow_extended_support=True
    ).iloc[0]
    assert row.action == action
    assert row.gate_group_count == 1
    assert row.geometry.covers(box(4.5, 3, 5.5, 7))
    GeomLateral.write_connection_data(
        gate_geometry, GeomLateral.get_connection_data(gate_geometry)
    )
    assert gate_geometry.read_bytes() == before


def test_missing_declared_gate_coordinate_holds(gate_geometry):
    gate_geometry.write_text(
        gate_geometry.read_text().replace("opening,2", "opening,3")
    )
    with pytest.raises(ValueError):
        GeomLateral.get_connection_gate_lines(gate_geometry, "gate")
    assert (
        GeomLateral.classify_connections(
            gate_geometry, box(0, 0, 10, 10), allow_extended_support=True
        )
        .iloc[0]
        .action
        == "block"
    )


def test_unknown_record_still_holds(gate_geometry):
    text = gate_geometry.read_text().replace(
        "Conn Weir WD=", "Unknown Spatial Object=4\nConn Weir WD="
    )
    gate_geometry.write_text(text)
    assert (
        GeomLateral.classify_connections(
            gate_geometry, box(0, 0, 10, 10), allow_extended_support=True
        )
        .iloc[0]
        .action
        == "block"
    )


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
    gate_geometry.write_text(
        text.replace("Connection Up SA=A", "Connection Up SA=A\nFrom 2D Area=A")
    )
    with pytest.raises(ValueError, match="ambiguous"):
        GeomLateral.remap_connection_areas(gate_geometry, {"A": "child"})


def test_nonfinite_gate_width_holds(gate_geometry):
    text = gate_geometry.read_text()
    lines = text.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("Conn Gate Name"))
    fields = lines[index + 1].rstrip().split(",")
    fields[1] = "nan"
    lines[index + 1] = ",".join(fields) + "\n"
    gate_geometry.write_text("".join(lines))
    assert (
        GeomLateral.classify_connections(
            gate_geometry, box(0, 0, 10, 10), allow_extended_support=True
        )
        .iloc[0]
        .action
        == "block"
    )


def test_undeclared_extra_gate_coordinates_hold(gate_geometry):
    lines = gate_geometry.read_text().splitlines(keepends=True)
    index = next(
        i for i, line in enumerate(lines) if line.startswith("Conn Gate Opening=")
    )
    lines.insert(index + 2, f"{8:16.8f}{9:16.8f}\n")
    gate_geometry.write_text("".join(lines))
    with pytest.raises(ValueError, match="coordinates"):
        GeomLateral.get_connection_gate_lines(gate_geometry, "gate")


@pytest.fixture
def clipping_gate(tmp_path):
    """Exact synthetic geometry from the default-writer compatibility gate."""
    seed = Path(__file__).parent / "data" / "gate_clip_compatibility.g01"
    raw = seed.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest()
        == "b034c7c62913933c8a773f7bcec2521ef1c2758c14100bc2e1ef9b2b2de79664"
    )
    path = tmp_path / "clip.g01"
    path.write_bytes(raw)
    return path


def test_default_gate_clipping_blocks_before_mutation(clipping_gate):
    before = clipping_gate.read_bytes()
    child = box(20, 20, 30, 30)
    decisions = GeomLateral.classify_connections(clipping_gate, child)
    assert decisions.columns.tolist() == [
        "Name",
        "From",
        "To",
        "action",
        "reason",
        "geometry",
    ]
    assert decisions.iloc[0].action == "block"
    assert decisions.iloc[0].reason == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"
    # The default support remains the crest alone, as in the previous API.
    assert decisions.geometry.iloc[0].bounds == (1.0, 4.0, 9.0, 6.0)
    with pytest.raises(
        ValueError,
        match="blocked before mutation.*CONNECTION_SPATIAL_EXTENT_UNVERIFIED",
    ):
        GeomStorage.clip_2d_flow_area(clipping_gate, "Area", child, create_backup=False)
    assert clipping_gate.read_bytes() == before
    assert GeomLateral.get_connections(clipping_gate).Name.tolist() == ["gate"]


@pytest.mark.parametrize("opt_in,action", [(False, "block"), (True, "drop")])
def test_breakout_gate_classification_requires_explicit_choice(
    clipping_gate, opt_in, action
):
    mod = import_module("ras_commander.RasBreakout2D")
    before = clipping_gate.read_bytes()
    child = box(20, 20, 30, 30)
    spec = mod.Breakout2DSpec(
        "01", "Area", child, "gate", allow_extended_connection_support=opt_in
    )
    row = mod._classify_outside_connections(
        clipping_gate, child, 0, spec.allow_extended_connection_support
    )[0]
    assert row["action"] == action
    assert row["gate_group_count"] == int(opt_in)
    assert clipping_gate.read_bytes() == before


def test_expanded_gate_classification_is_read_only_and_default_writer_stays_blocked(
    clipping_gate,
):
    before = clipping_gate.read_bytes()
    child = box(20, 20, 30, 30)
    decisions = GeomLateral.classify_connections(
        clipping_gate, child, allow_extended_support=True
    )
    assert decisions.iloc[0].action == "drop"
    assert decisions.iloc[0].reason == "CONNECTION_OUTSIDE_CHILD"
    assert decisions.iloc[0].gate_group_count == 1
    assert decisions.geometry.iloc[0].covers(box(4.5, 3, 5.5, 7))
    assert clipping_gate.read_bytes() == before
    with pytest.raises(ValueError, match="blocked before mutation"):
        GeomStorage.clip_2d_flow_area(clipping_gate, "Area", child, create_backup=False)
    assert clipping_gate.read_bytes() == before


@pytest.mark.parametrize("opt_in", [False, True])
def test_preparation_rechecks_gate_with_same_opt_in(clipping_gate, monkeypatch, opt_in):
    mod = import_module("ras_commander.RasBreakout2D")
    child = box(20, 20, 30, 30)
    unsteady = clipping_gate.with_suffix(".u01")
    unsteady.write_bytes(b"Flow Title=Gate test\n")
    # Supply a drop approval to prove a default clone recheck cannot accept it.
    preflight = SimpleNamespace(
        is_ready=True,
        feature_actions=gpd.GeoDataFrame(
            [
                {
                    "feature_type": "sa_2d_connection",
                    "name": "gate",
                    "action": "drop",
                    "geometry": None,
                }
            ],
            crs=3857,
        ),
        child_boundary=gpd.GeoDataFrame(geometry=[child], crs=3857),
        spec=mod.Breakout2DSpec(
            "01", "Area", child, "gate", allow_extended_connection_support=opt_in
        ),
        connection_data=GeomLateral.get_connection_data(clipping_gate),
    )
    clone = SimpleNamespace(
        boundaries_unchanged=True,
        unsteady_path=unsteady,
        cloned_unsteady_sha256=mod._sha256_file(unsteady),
        geometry_path=clipping_gate,
    )

    def stop_after_recheck(_):
        raise RuntimeError("expanded gate recheck passed")

    monkeypatch.setattr(mod, "_retained_breakline_specs", stop_after_recheck)
    before = clipping_gate.read_bytes()
    if opt_in:
        with pytest.raises(RuntimeError, match="expanded gate recheck passed"):
            mod.RasBreakout2D.prepare_cloned_geometry(
                preflight, clone, ras_object=None, refresh_hdf=True, remesh=False
            )
    else:
        with pytest.raises(ValueError):
            mod.RasBreakout2D.prepare_cloned_geometry(
                preflight, clone, ras_object=None, refresh_hdf=True, remesh=False
            )
    assert clipping_gate.read_bytes() == before


@pytest.mark.parametrize(
    "opt_in,schema",
    [
        (False, "connection_classification"),
        (True, "connection_classification_extended"),
    ],
)
def test_classification_columns_match_selected_schema(gate_geometry, opt_in, schema):
    for path in (gate_geometry, gate_geometry.parent / "empty.g01"):
        if path != gate_geometry:
            path.write_text("Geom Title=Empty\n")
        result = GeomLateral.classify_connections(
            path, box(0, 0, 10, 10), allow_extended_support=opt_in
        )
        assert result.columns.tolist() == [
            c["name"] for c in DATAFRAME_SCHEMAS[schema]["columns"]
        ]


@pytest.mark.parametrize(
    "record", ["Conn CellSize Min=2\n", "Conn CellSize Max=5\n", "extended_bridge"]
)
def test_expanded_metadata_acceptance_requires_opt_in(tmp_path, record):
    path = tmp_path / "metadata.g01"
    path.write_text("Geom Title=Metadata\nStorage Area=A,0,0\nBC Line Name=outlet\n")
    GeomLateral.set_connection(
        path,
        "control",
        [(2, 5), (8, 5)],
        "A",
        "A",
        weir_width=2,
        weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0.0, 6.0], "Elevation": [10.0, 10.0]}),
    )
    if record == "extended_bridge":
        record = "".join(GeomLateral._build_empty_bridge_skeleton()).replace(
            "Conn BR: Bridge=-1,0,-1,-1,0\n", "Conn BR: Bridge=-1,0,-1,-1,0,0.3,0.5\n"
        )
    inventory = GeomLateral.get_connection_data(path)
    inventory.loc[0, "RawBlock"] += record
    GeomLateral.write_connection_data(path, inventory[["Name", "RawBlock"]])
    before = path.read_bytes()
    default = GeomLateral.classify_connections(path, box(0, 0, 10, 10)).iloc[0]
    assert default.action == "block"
    assert default.reason == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"
    assert (
        GeomLateral.classify_connections(
            path, box(0, 0, 10, 10), allow_extended_support=True
        )
        .iloc[0]
        .action
        == "keep"
    )
    assert path.read_bytes() == before
