"""Connection retention through real geometry text writers and clipped perimeters."""

from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander import GeomLateral, GeomStorage

breakout = import_module("ras_commander.RasBreakout2D")


def _project(tmp_path):
    geom_file = tmp_path / "clip.g01"
    geom_file.write_bytes(b"Geom Title=Clipping\r\nLCMann Time=0\r\n")
    GeomStorage.set_2d_flow_area_perimeter(
        geom_file, "Area", geometry=box(0, 0, 40, 40), create_backup=False
    )
    return geom_file


def _connection(geom_file, name, coordinates, width=2):
    GeomLateral.set_connection(
        geom_file,
        name,
        coordinates,
        "Area",
        "Area",
        weir_width=width,
        weir_coef=1.5,
        crest_profile=pd.DataFrame({"Station": [0.0, 8.0], "Elevation": [3.0, 4.0]}),
        create_backup=False,
    )


def test_clip_retains_internal_control_and_reports_external_drop(tmp_path):
    geom_file = _project(tmp_path)
    _connection(geom_file, "Inside", [(5, 5), (10, 5)])
    _connection(geom_file, "Outside", [(30, 30), (35, 30)])
    before_bytes = geom_file.read_bytes()
    before = GeomLateral.get_connection_data(geom_file).set_index("Name")
    actions = GeomStorage.clip_2d_flow_area(geom_file, "Area", box(0, 0, 20, 20))
    assert actions.set_index("Name")["action"].to_dict() == {
        "Inside": "keep",
        "Outside": "drop",
    }
    assert actions["reason"].notna().all()
    assert actions.attrs["attachment_status"] == "CONNECTION_ATTACHMENT_UNVERIFIED"
    assert actions.attrs["backup_path"].read_bytes() == before_bytes
    after = GeomLateral.get_connection_data(geom_file).set_index("Name")
    assert list(after.index) == ["Inside"]
    assert after.loc["Inside", "RawBlock"] == before.loc["Inside", "RawBlock"]
    assert before.loc["Inside", "RawBlock"].encode("utf-8") in geom_file.read_bytes()
    assert (
        GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
        .geometry.iloc[0]
        .equals(box(0, 0, 20, 20))
    )


@pytest.mark.parametrize(
    "coordinates,width",
    [
        ([(10, 5), (30, 5)], 2),
        ([(19.5, 5), (19.5, 10)], 2),  # centerline inside, physical width crosses
        ([(20.01, 5), (20.01, 10)], 2),
    ],
)
def test_clip_blocks_partial_physical_support_before_mutation(
    tmp_path, coordinates, width
):
    geom_file = _project(tmp_path)
    _connection(geom_file, "Crossing", coordinates, width)
    before = geom_file.read_bytes()
    with pytest.raises(ValueError, match="Connection clipping blocked"):
        GeomStorage.clip_2d_flow_area(
            geom_file, "Area", box(0, 0, 20, 20), containment_tolerance=1
        )
    assert geom_file.read_bytes() == before
    assert not geom_file.with_suffix(".g01.bak").exists()


def test_clip_leaves_unrelated_area_control_unchanged(tmp_path):
    geom_file = _project(tmp_path)
    GeomStorage.set_2d_flow_area_perimeter(
        geom_file, "Other", geometry=box(50, 0, 90, 40), create_backup=False
    )
    GeomLateral.set_connection(
        geom_file,
        "Unrelated",
        [(60, 5), (70, 5)],
        "Other",
        "Other",
        weir_width=2,
        weir_coef=1.5,
        crest_profile=pd.DataFrame({"Station": [0.0, 10.0], "Elevation": [3.0, 4.0]}),
        create_backup=False,
    )
    before = GeomLateral.get_connection_data(geom_file).iloc[0]["RawBlock"]
    actions = GeomStorage.clip_2d_flow_area(geom_file, "Area", box(0, 0, 20, 20))
    assert actions.empty
    assert GeomLateral.get_connection_data(geom_file).iloc[0]["RawBlock"] == before


@pytest.mark.parametrize("geometry", [box(-1, 0, 20, 20), box(0, 0, 0, 0)])
def test_invalid_child_never_mutates(tmp_path, geometry):
    geom_file = _project(tmp_path)
    before = geom_file.read_bytes()
    with pytest.raises(ValueError):
        GeomStorage.clip_2d_flow_area(geom_file, "Area", geometry)
    assert geom_file.read_bytes() == before


def test_breakout_reports_same_area_internal_connection_as_keep(tmp_path):
    geom_file = _project(tmp_path)
    _connection(geom_file, "Inside", [(5, 5), (10, 5)])
    actions = breakout._classify_outside_connections(geom_file, box(0, 0, 20, 20), 0.01)
    assert actions[0]["action"] == "keep"
    assert actions[0]["retained_fraction"] == 1
    assert actions[0]["reason"]


def test_breakout_text_preparation_retains_mixed_newline_control(tmp_path):
    geom_file = _project(tmp_path)
    _connection(geom_file, "Inside", [(5, 5), (10, 5)])
    _connection(geom_file, "Outside", [(30, 30), (35, 30)])
    raw = geom_file.read_bytes()
    # The existing source contains a vendor record with a distinct newline style.
    raw = raw.replace(b"Conn Weir Coef=1.5\r\n", b"Conn Weir Coef=1.5\n")
    geom_file.write_bytes(raw)
    before = GeomLateral.get_connection_data(geom_file).set_index("Name")
    preflight = SimpleNamespace(
        spec=SimpleNamespace(source_2d_area="Area"), source_features={},
        source_geometry_path=geom_file,
    )
    clone = SimpleNamespace(geometry_path=geom_file)
    decisions = pd.DataFrame(
        {"name": ["Inside", "Outside"], "action": ["keep", "drop"]}
    )
    breakout._prepare_geometry_text(
        preflight, clone, box(0, 0, 20, 20), decisions, [], []
    )
    after = GeomLateral.get_connection_data(geom_file).set_index("Name")
    assert list(after.index) == ["Inside"]
    assert after.loc["Inside", "RawBlock"] == before.loc["Inside", "RawBlock"]
    assert before.loc["Inside", "RawBlock"].encode("utf-8") in geom_file.read_bytes()


def test_official_example_internal_levees_retained_by_clip(tmp_path):
    from ras_commander import RasExamples

    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path)
    geom_file = project / "BaldEagleDamBrk.g13"
    data = GeomLateral.get_connection_data(geom_file)
    # This retention test isolates the three internal levees. The gated SA-to-2D
    # dam requires additional footprint evidence and is explicitly omitted from
    # this disposable test copy, never bypassed in production preflight.
    levees = data[data["Name"] != "Dam"].copy()
    GeomLateral.write_connection_data(geom_file, levees, create_backup=False)
    parent = GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
    parent = parent.set_index("Name").loc["BaldEagleCr", "geometry"]
    actions = GeomStorage.clip_2d_flow_area(geom_file, "BaldEagleCr", parent)
    assert len(actions) == 3
    assert actions["action"].eq("keep").all()
    assert (
        GeomLateral.get_connection_data(geom_file)["RawBlock"].tolist()
        == levees["RawBlock"].tolist()
    )
