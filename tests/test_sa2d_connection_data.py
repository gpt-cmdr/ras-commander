"""Lossless inventory and conservative full-support SA/2D decisions."""

import shutil

import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander import GeomLateral, GeomStorage, RasExamples


@pytest.fixture
def geometry(tmp_path):
    path = tmp_path / "test.g01"
    path.write_text(
        "Geom Title=Connection Data\nStorage Area=A,0,0\nStorage Area=B,0,0\nBC Line Name=outlet\n"
    )
    GeomLateral.set_connection(
        path,
        "internal",
        [(2, 5), (8, 5)],
        "A",
        "A",
        weir_width=2,
        weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0.0, 6.0], "Elevation": [10.0, 10.0]}),
    )
    return path


@pytest.mark.parametrize(
    "project,filename",
    [
        ("BaldEagleCrkMulti2D", "BaldEagleDamBrk.g13"),
        ("BaldEagleCrkMulti2D", "BaldEagleDamBrk.g03"),
        ("Muncie", "Muncie.g01"),
    ],
)
def test_real_inventory_exact_round_trip(tmp_path, project, filename):
    extracted = RasExamples.extract_project(project, output_path=tmp_path / "examples")
    path = tmp_path / filename
    shutil.copy2(extracted / filename, path)
    before = path.read_bytes()
    inventory = GeomLateral.get_connection_data(path)
    assert not inventory.empty
    assert all(isinstance(v, pd.DataFrame) for v in inventory["CrestProfile"])
    backup = GeomLateral.write_connection_data(path, inventory)
    assert backup.read_bytes() == before
    assert path.read_bytes() == before
    after = GeomLateral.get_connection_data(path)
    assert inventory["RawBlock"].tolist() == after["RawBlock"].tolist()


def test_unknown_records_mixed_newlines_are_preserved(geometry):
    raw = geometry.read_bytes().replace(
        b"Conn Weir WD=2\r\n", b"Vendor Unknown=\xff\nConn Weir WD=2\r\n"
    )
    geometry.write_bytes(raw)
    inventory = GeomLateral.get_connection_data(geometry)
    assert inventory.iloc[0]["UnknownRecords"]
    GeomLateral.write_connection_data(geometry, inventory, create_backup=False)
    assert geometry.read_bytes() == raw
    classified = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10))
    assert classified.iloc[0]["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


def test_authoring_requires_explicit_physics_and_records_defaults(geometry):
    before = geometry.read_bytes()
    with pytest.raises(ValueError, match="weir_width"):
        GeomLateral.set_connection(geometry, "new", [(0, 0), (1, 1)], "A", "B")
    assert geometry.read_bytes() == before
    GeomLateral.set_connection(
        geometry, "new", [(0, 0), (1, 1)], "A", "B", allow_defaults=True
    )
    row = GeomLateral.get_connection_data(geometry).set_index("Name").loc["new"]
    assert row["DefaultsUsed"] == [
        "WeirWidth",
        "WeirCoefficient",
        "CrestProfile(flat_zero_elevation)",
    ]
    assert row["WeirWidth"] == 100
    assert row["CrestProfile"]["Elevation"].tolist() == [0, 0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connection_name": "x" * 17},
        {"upstream_area": "missing"},
        {"weir_width": 0},
        {"weir_coef": float("nan")},
        {"coordinates": [(0, 0), (float("inf"), 0)]},
        {"crest_profile": pd.DataFrame({"Station": [1, 0], "Elevation": [1, 1]})},
    ],
)
def test_invalid_physics_cannot_mutate(geometry, kwargs):
    before = geometry.read_bytes()
    inputs = dict(
        connection_name="new",
        coordinates=[(1, 1), (2, 2)],
        upstream_area="A",
        downstream_area="B",
        weir_width=2,
        weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0, 2], "Elevation": [1, 1]}),
    )
    inputs.update(kwargs)
    with pytest.raises(ValueError):
        GeomLateral.set_connection(geometry, **inputs)
    assert geometry.read_bytes() == before


@pytest.mark.parametrize(
    "coordinates,stations",
    [
        ([(1, 1), (2, 2)], [0, 0.0001]),
        ([(1000000000.0, 1000000000.0), (1000000000.000001, 1000000000.0)], [0, 1]),
        ([(1, 1), (2, 2)], [10000.0001, 10000.0002]),
    ],
)
def test_native_precision_collapse_rejected_before_mutation(
    geometry, coordinates, stations
):
    before = geometry.read_bytes()
    backup = geometry.with_suffix(".g01.bak")
    backup_before = backup.read_bytes()
    with pytest.raises(ValueError, match="native fixed-width precision"):
        GeomLateral.set_connection(
            geometry,
            "new",
            coordinates,
            "A",
            "B",
            weir_width=2,
            weir_coef=3,
            crest_profile=pd.DataFrame({"Station": stations, "Elevation": [1, 1]}),
        )
    assert geometry.read_bytes() == before
    assert backup.read_bytes() == backup_before


def test_writer_rejects_tampered_decoded_fields(geometry):
    before = geometry.read_bytes()
    inventory = GeomLateral.get_connection_data(geometry)
    inventory.at[0, "WeirWidth"] = 999
    with pytest.raises(ValueError, match="does not agree"):
        GeomLateral.write_connection_data(geometry, inventory)
    assert geometry.read_bytes() == before


def test_writer_rejects_duplicate_and_mismatched_name(geometry):
    inventory = GeomLateral.get_connection_data(geometry)
    with pytest.raises(ValueError, match="unique"):
        GeomLateral.write_connection_data(geometry, pd.concat([inventory, inventory]))
    inventory.at[0, "Name"] = "wrong"
    with pytest.raises(ValueError, match="Name does not agree"):
        GeomLateral.write_connection_data(geometry, inventory)


def test_full_width_footprint_classification(geometry):
    kept = GeomLateral.classify_connections(
        geometry, box(0, 0, 10, 10), retained_area_names={"A"}
    )
    assert kept.iloc[0]["action"] == "keep"
    assert kept.iloc[0].geometry.bounds == pytest.approx((1, 4, 9, 6))
    crossing = GeomLateral.classify_connections(
        geometry, box(1.5, 0, 10, 10), tolerance=100
    )
    assert crossing.iloc[0]["reason"] == "CONNECTION_CROSSES_CHILD_BOUNDARY"
    external = GeomLateral.classify_connections(geometry, box(20, 20, 30, 30))
    assert external.iloc[0]["action"] == "drop"
    removed = GeomLateral.classify_connections(
        geometry, box(0, 0, 10, 10), retained_area_names={"B"}
    )
    assert removed.iloc[0]["reason"] == "CONNECTION_ENDPOINT_REMOVED"


def test_tolerance_guards_external_separation_without_expanding_containment(geometry):
    child = box(-10, 0, 0.5, 10)
    assert GeomLateral.classify_connections(geometry, child).iloc[0]["action"] == "drop"
    near = GeomLateral.classify_connections(geometry, child, tolerance=1).iloc[0]
    assert near["action"] == "block"
    assert near["reason"] == "CONNECTION_NEAR_CHILD_BOUNDARY"
    assert (
        GeomLateral.classify_connections(
            geometry, box(0, 0, 10, 10), tolerance=100
        ).iloc[0]["action"]
        == "keep"
    )
    crossing = GeomLateral.classify_connections(
        geometry, box(1.5, 0, 10, 10), tolerance=100
    ).iloc[0]
    assert crossing["reason"] == "CONNECTION_CROSSES_CHILD_BOUNDARY"


def test_culvert_barrel_crossing_is_not_hidden_by_crest(geometry):
    inventory = GeomLateral.get_connection_data(geometry)
    raw = inventory.iloc[0]["RawBlock"]
    raw += (
        "Connection Culv=2,2,2,20,.03,.5,1,1,1,0,0,1,culvert,,\n"
        "   0.000   0.000\nConn Culvert Barrel=1,barrel,2\n"
        "               5               5              15               5\n"
        "Conn Culv Bottom n=.03\n\n"
    )
    GeomLateral.write_connection_data(
        geometry, pd.DataFrame([{"Name": "internal", "RawBlock": raw}])
    )
    classified = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10))
    assert classified.iloc[0]["reason"] == "CONNECTION_CROSSES_CHILD_BOUNDARY"


@pytest.mark.parametrize(
    "record", ["Conn BR: Bridge=1\n", "Breach Data=1\n", "Vendor Spatial Extension=1\n"]
)
def test_unknown_extent_fails_closed(geometry, record):
    inventory = GeomLateral.get_connection_data(geometry)
    raw = inventory.iloc[0]["RawBlock"] + record
    GeomLateral.write_connection_data(
        geometry, pd.DataFrame([{"Name": "internal", "RawBlock": raw}])
    )
    result = GeomLateral.classify_connections(geometry, box(20, 20, 30, 30))
    assert result.iloc[0]["action"] == "block"
    assert result.iloc[0]["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


def test_empty_schema_and_explicit_removal(geometry):
    inventory = GeomLateral.get_connection_data(geometry)
    before = geometry.read_bytes()
    raw = inventory.iloc[0]["RawBlock"].encode()
    GeomLateral.write_connection_data(geometry, inventory.iloc[:0])
    assert geometry.read_bytes() == before.replace(raw, b"")
    empty = GeomLateral.get_connection_data(geometry)
    assert empty.empty
    assert empty.columns.tolist() == GeomLateral.CONNECTION_DATA_COLUMNS
    assert GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).empty


def _append_connection_records(geometry, records):
    inventory = GeomLateral.get_connection_data(geometry)
    raw = inventory.iloc[0]["RawBlock"] + records
    GeomLateral.write_connection_data(
        geometry,
        pd.DataFrame([{"Name": "internal", "RawBlock": raw}]),
        create_backup=False,
    )
    return GeomLateral.get_connection_data(geometry).iloc[0]


@pytest.mark.parametrize(
    "record",
    ["Connection Centerline Profile=0\n"]
    + [
        f"Conn BR: {prefix} {kind}={side},0\n"
        for prefix in ("BR", "XS")
        for kind in ("SE", "Mann")
        for side in (1, 2)
    ],
)
def test_zero_count_profiles_are_recognized_empty(geometry, record):
    row = _append_connection_records(geometry, record)
    assert row["EmptyRecords"] == [record]
    assert row["UnknownRecords"] == []
    assert row["ParseIssues"] == []
    assert (
        GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]["action"]
        == "keep"
    )


@pytest.mark.parametrize(
    "record",
    [f"Connection Centerline Profile={count}\n" for count in ("1", "-1", "x", "")]
    + [
        f"Conn BR: {prefix} {kind}={side},{count}\n"
        for prefix in ("BR", "XS")
        for kind in ("SE", "Mann")
        for side, count in ((1, "1"), (2, "-1"), (1, "x"), (3, "0"), (1, ""))
    ],
)
def test_active_or_invalid_profiles_remain_unknown(geometry, record):
    row = _append_connection_records(geometry, record)
    assert record in row["UnknownRecords"]
    assert record not in row["EmptyRecords"]
    result = GeomLateral.classify_connections(geometry, box(20, 20, 30, 30)).iloc[0]
    assert result["action"] == "block"
    assert result["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


def test_empty_bridge_skeleton_preserves_raw_lines_and_spatial_decisions(geometry):
    records = "".join(GeomLateral._build_empty_bridge_skeleton())
    row = _append_connection_records(geometry, records)
    assert row["EmptyRecords"] == records.splitlines(keepends=True)
    assert row["UnknownRecords"] == []
    assert row["ParseIssues"] == []
    kept = GeomLateral.classify_connections(
        geometry, box(0, 0, 10, 10), retained_area_names={"A"}
    ).iloc[0]
    assert kept["action"] == "keep"
    assert kept.geometry.bounds == pytest.approx((1, 4, 9, 6))
    crossing = GeomLateral.classify_connections(geometry, box(1.5, 0, 10, 10)).iloc[0]
    assert crossing["reason"] == "CONNECTION_CROSSES_CHILD_BOUNDARY"
    assert (
        GeomLateral.classify_connections(geometry, box(20, 20, 30, 30)).iloc[0][
            "action"
        ]
        == "drop"
    )
    removed = GeomLateral.classify_connections(
        geometry, box(0, 0, 10, 10), retained_area_names={"B"}
    ).iloc[0]
    assert removed["reason"] == "CONNECTION_ENDPOINT_REMOVED"


def test_delivered_salt_draw_empty_bridge_variant_is_retained(geometry):
    lines = GeomLateral._build_empty_bridge_skeleton()
    lines[0] = "Conn BR: Bridge=0,0,0,0, 0 ,0.3,0.5\n"
    lines[2] = ",10,3,0, 0, 0, , , 0.98, 0, 0,0,,\n"
    lines[9] = "Conn BR: BR Coef=-1 , 0 , 0 ,,,0.8,-1,,0,\n"
    records = "Connection Centerline Profile=0\n" + "".join(lines)
    row = _append_connection_records(geometry, records)
    assert row["EmptyRecords"] == records.splitlines(keepends=True)
    assert row["UnknownRecords"] == []
    assert row["ParseIssues"] == []
    result = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]
    assert result["action"] == "keep"


@pytest.mark.parametrize(
    "old,new",
    [
        ("BR SE=1,0", "BR SE=1,1"),
        ("XS Mann=2,0", "XS Mann=2,1"),
        ("0,0,0,0, 0, 0,", "0,0,0,0, 1, 0,"),
        ("0,0,0,0, 0, 0,", "0,0,0,0, -1, 0,"),
        ("0,0,0,0, 0, 0,", "0,0,0,0, x, 0,"),
        ("0,0,0,0, 0, 0,", "malformed deck payload"),
        ("BR Bank Stations=1,,", "BR Bank Stations=1,0,1"),
        ("XS Bank Stations=2,,", "XS Bank Stations=2,0,"),
    ],
)
def test_bridge_skeleton_with_active_or_malformed_support_blocks(geometry, old, new):
    records = "".join(GeomLateral._build_empty_bridge_skeleton())
    assert old in records
    row = _append_connection_records(geometry, records.replace(old, new))
    assert row["UnknownRecords"]
    result = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]
    assert result["action"] == "block"
    assert result["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


@pytest.mark.parametrize(
    "unknown",
    [
        "Conn BR: Vendor Spatial Extension=0\n",
        "Conn BR: Vendor Spatial Extension\n",
        "  Conn BR: Vendor Spatial Extension\n",
    ],
)
def test_unknown_bridge_extension_cannot_be_hidden_by_empty_skeleton(geometry, unknown):
    records = "".join(GeomLateral._build_empty_bridge_skeleton())
    row = _append_connection_records(geometry, records + unknown)
    assert unknown in row["UnknownRecords"]
    assert unknown not in row["EmptyRecords"]
    result = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]
    assert result["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


@pytest.mark.parametrize(
    "records",
    [
        "Connection Centerline Profile=0\nConn BR: Vendor Spatial Extension\n",
        "Connection Centerline Profile=0\n  Conn BR: Vendor Spatial Extension\n",
        "Conn BR: BR SE=1,0\nConn BR: Vendor Spatial Extension\n",
        "Conn BR: XS SE=2,0\nConn BR: Vendor Spatial Extension\n",
        "Conn BR: Deck malformed\n",
    ],
)
def test_unknown_bridge_headers_without_equals_block(geometry, records):
    row = _append_connection_records(geometry, records)
    unknown = records.splitlines(keepends=True)[-1]
    assert unknown in row["UnknownRecords"]
    assert unknown not in row["EmptyRecords"]
    result = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]
    assert result["action"] == "block"
    assert result["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


@pytest.mark.parametrize(
    "records",
    [
        "Connection Centerline Profile=0\n   1.000   2.000\n",
        "Conn BR: XS Mann=2,0\n   1.000   2.000\n",
        "".join(GeomLateral._build_empty_bridge_skeleton()) + "   1.000   2.000\n",
    ],
)
def test_unlabelled_payload_after_empty_profile_blocks(geometry, records):
    _append_connection_records(geometry, records)
    result = GeomLateral.classify_connections(geometry, box(0, 0, 10, 10)).iloc[0]
    assert result["action"] == "block"
    assert result["reason"] == "CONNECTION_SPATIAL_EXTENT_UNVERIFIED"


def test_empty_records_lossless_mixed_newlines_and_tamper_rejection(geometry):
    lines = ["Connection Centerline Profile=0\n"]
    lines += GeomLateral._build_empty_bridge_skeleton()
    records = "".join(
        line.replace("\n", "\r\n") if i % 2 else line for i, line in enumerate(lines)
    )
    _append_connection_records(geometry, records)
    before = geometry.read_bytes()
    inventory = GeomLateral.get_connection_data(geometry)
    assert inventory.iloc[0]["EmptyRecords"] == records.splitlines(keepends=True)
    GeomLateral.write_connection_data(geometry, inventory, create_backup=False)
    assert geometry.read_bytes() == before
    inventory.at[0, "EmptyRecords"] = []
    with pytest.raises(ValueError, match="EmptyRecords does not agree"):
        GeomLateral.write_connection_data(geometry, inventory)
    assert geometry.read_bytes() == before


def test_clipping_retains_empty_profiles_losslessly(tmp_path):
    geometry = tmp_path / "clip.g01"
    geometry.write_bytes(b"Geom Title=Clipping\r\nLCMann Time=0\r\n")
    GeomStorage.set_2d_flow_area_perimeter(
        geometry, "Area", geometry=box(0, 0, 40, 40), create_backup=False
    )
    GeomLateral.set_connection(
        geometry,
        "internal",
        [(5, 5), (10, 5)],
        "Area",
        "Area",
        weir_width=2,
        weir_coef=3,
        crest_profile=pd.DataFrame({"Station": [0, 5], "Elevation": [10, 10]}),
        create_backup=False,
    )
    records = "Connection Centerline Profile=0\n"
    records += "".join(GeomLateral._build_empty_bridge_skeleton())
    row = _append_connection_records(geometry, records)
    before = geometry.read_bytes()
    actions = GeomStorage.clip_2d_flow_area(geometry, "Area", box(0, 0, 20, 20))
    assert actions.iloc[0]["action"] == "keep"
    assert actions.attrs["backup_path"].read_bytes() == before
    after = GeomLateral.get_connection_data(geometry).iloc[0]
    assert after["RawBlock"] == row["RawBlock"]
    assert after["EmptyRecords"] == row["EmptyRecords"]
