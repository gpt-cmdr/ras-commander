import pytest
import pandas as pd

from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomCulvert import GeomCulvert


def _base_geometry_text() -> str:
    return """Geom Title=Culvert Authoring Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
BEGIN DESCRIPTION:
Upstream XS
END DESCRIPTION:
#XS Ineff= 2 , 0 
    0.00   40.00  104.00   60.00  100.00  104.00
Permanent Ineff=
       F       F
Type RM Length L Ch R = 2 ,100,,,
BEGIN DESCRIPTION:
Fixture culvert
END DESCRIPTION:
Bridge Culvert-0,0,1,-1, 0 
Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee
10,40,2.6,0, 2, 2, 33.7, , 0.95, 0, 0,0,,
  900.00 1100.00
   35.00   35.00
                
  900.00 1100.00
   35.00   35.00
                
BC Design=,, 0 ,, 0 ,,,,,,
BC HTab HWMax=37.2
BC Use User HTab Curves=0
Type RM Length L Ch R = 1 ,90,100,100,100
BEGIN DESCRIPTION:
Downstream XS
END DESCRIPTION:
#XS Ineff= 2 , 0 
    0.00   35.00  103.00   65.00  100.00  103.00
Permanent Ineff=
       F       F
"""


def _real_world_culvert_text() -> str:
    return """Geom Title=Existing Culvert Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
#XS Ineff= 0 , 0 
Permanent Ineff=

Type RM Length L Ch R = 2 ,100,,,
Bridge Culvert-0,0,1,-1, 0 
Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee
10,40,2.6,0, 8, 8, 33.7, , 0.95, 0, 2,2,,
     856     917     972     993    1007    1027    1095    1150
    36.1    34.8    33.9    33.8    33.8    33.7    35.7    37.2
                                                                
     856     917     972     993    1007    1027    1095    1150
    36.1    34.8    33.9    33.8    33.8    33.7    35.7    37.2
                                                                
Culvert=9,6,28,50,0.013,0.5,1,61,3,25.1,1000,25,1000,Culvert # 1 , 0 ,5
Culvert Bottom n=0.03
Culvert Bottom Depth=0.5
Multiple Barrel Culv=2,3,5,50,0.013,0.2,1,10,2,28.1,28, 2,Box         , 0 ,5
   988.5   988.5  1011.5  1011.5
Culvert Bottom n=0.013
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,90,100,100,100
#XS Ineff= 0 , 0 
Permanent Ineff=
"""


def _multi_group_culvert_text() -> str:
    """Real-world layout: a structure with TWO single-barrel culvert groups, each
    record followed by a fixed-width station line and detail lines (as HEC-RAS
    actually writes them). Inverts use 7 significant figures to exercise the
    writer's numeric precision. Mirrors Squannacook RS 41."""
    return """Geom Title=Multi-Group Culvert Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
#XS Ineff= 0 , 0
Permanent Ineff=

Type RM Length L Ch R = 2 ,100,,,
Bridge Culvert-0,0,0,0, 0
Culvert=5,1.75,3.8,31,0.019,0.5,1,41,1,311.9456,95.02,310.9502,86.98,Culvert #1  , 0 ,6.56
   95.02   86.98
BC Culvert Barrel=1,Barrel #1,0
Culvert Bottom n=0.019
Culvert=5,2.2,3.7,31,0.019,0.5,1,41,1,311.9456,99.42,310.9502,91.3,Culvert #2  , 0 ,6.56
   99.42    91.3
BC Culvert Barrel=1,Barrel #1,0
Culvert Bottom n=0.019
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,90,100,100,100
#XS Ineff= 0 , 0
Permanent Ineff=
"""


def _write_geometry(tmp_path, text=None):
    geom_file = tmp_path / "fixture.g01"
    geom_file.write_text(text or _base_geometry_text(), encoding="utf-8")
    return geom_file


def _shape_specs():
    return {
        int(shape["code"]): shape
        for shape in GeomCulvert.CULVERT_TAXONOMY["shapes"]
    }


def _first_chart_scale(shape_code):
    shape = _shape_specs()[shape_code]
    chart = shape["allowed_charts"][0]
    scale = chart["allowed_scales"][0]
    return int(chart["chart_id"]), int(scale["scale_id"])


def _record_for_shape(shape_code, index=0, **overrides):
    shape = _shape_specs()[shape_code]
    chart_id, scale_id = _first_chart_scale(shape_code)
    required_dimensions = set(shape["dimension_model"]["required_geometry_fields"])

    record = {
        "ShapeName": "ConSpan" if shape_code == 9 else shape["ras_commander_shape_name"],
        "Span": 5.0 + index,
        "Length": 40.0 + index,
        "ManningsN": 0.013 + (index * 0.001),
        "EntranceLoss": 0.2,
        "ExitLoss": 1.0,
        "InletType": chart_id,
        "OutletType": scale_id,
        "UpstreamInvert": 25.0 + index,
        "UpstreamStation": 970.0 + (index * 5.0),
        "DownstreamInvert": 24.5 + index,
        "DownstreamStation": 970.0 + (index * 5.0),
        "CulvertName": f"{shape['ras_commander_shape_name']} {index + 1}",
    }
    if "Rise" in required_dimensions:
        record["Rise"] = 3.0 + index
    record.update(overrides)
    return record


def _culvert_records():
    return [
        {
            "ShapeName": "Circular",
            "Span": 6,
            "Length": 40,
            "ManningsN": 0.013,
            "EntranceLoss": 0.5,
            "ExitLoss": 1,
            "InletType": 1,
            "OutletType": 1,
            "UpstreamInvert": 25.1,
            "UpstreamStation": 996,
            "DownstreamInvert": 25,
            "DownstreamStation": 996,
            "CulvertName": "Circular One",
            "BottomN": 0.013,
            "ChartNumber": 5,
        },
        {
            "Shape": 2,
            "Span": 3,
            "Rise": 5,
            "Length": 50,
            "ManningsN": 0.014,
            "EntranceLoss": 0.2,
            "ExitLoss": 1,
            "InletType": 10,
            "OutletType": 2,
            "UpstreamInvert": 28.1,
            "UpstreamStation": 988.5,
            "DownstreamInvert": 28,
            "DownstreamStation": 988.5,
            "CulvertName": "Box One",
            "BottomDepth": 0.5,
            "ChartNumber": 5,
        },
        {
            "ShapeName": "Box",
            "Span": 4,
            "Rise": 4,
            "Length": 55,
            "ManningsN": 0.015,
            "EntranceLoss": 0.3,
            "ExitLoss": 1,
            "InletType": 8,
            "OutletType": 1,
            "UpstreamInvert": 27.5,
            "DownstreamInvert": 27,
            "NumBarrels": 3,
            "BarrelStations": [(980, 980), (1000, 1000), (1020, 1020)],
            "CulvertName": "Triple Box",
            "BottomN": 0.02,
            "ChartNumber": 30,
        },
    ]


def test_set_culverts_round_trips_circular_box_and_multi_barrel(tmp_path):
    geom_file = _write_geometry(tmp_path)

    result = GeomCulvert.set_culverts(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        _culvert_records(),
    )

    assert result["culverts_written"] == 3
    assert (tmp_path / "fixture.g01.bak").exists()

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert culverts["CulvertName"].tolist() == ["Circular One", "Box One", "Triple Box"]
    assert culverts["Shape"].tolist() == [1, 2, 2]
    assert culverts["ShapeName"].tolist() == ["Circular", "Box", "Box"]
    assert pd.isna(culverts.loc[0, "Rise"])
    assert culverts.loc[1, "BottomDepth"] == pytest.approx(0.5)
    assert culverts.loc[2, "RecordType"] == "Multiple Barrel Culv"
    assert culverts.loc[2, "NumBarrels"] == 3
    assert culverts.loc[2, "BarrelStations"] == [(980.0, 980.0), (1000.0, 1000.0), (1020.0, 1020.0)]
    assert culverts.loc[2, "BottomN"] == pytest.approx(0.02)
    assert culverts.loc[2, "ChartNumber"] == 30
    # Backward compat: records carry ChartNumber but no UsDistance key. The
    # trailing field must still serialize from ChartNumber (legacy behavior), so
    # UsDistance reads back equal to ChartNumber.
    assert culverts.loc[0, "UsDistance"] == pytest.approx(5)
    assert culverts.loc[2, "UsDistance"] == pytest.approx(30)

    all_culverts = GeomCulvert.get_all(geom_file)
    assert all_culverts[["River", "Reach", "RS"]].drop_duplicates().values.tolist() == [
        ["Test River", "Reach 1", "100"]
    ]
    assert len(all_culverts) == 3


def test_set_culverts_round_trips_all_taxonomy_shapes(tmp_path):
    geom_file = _write_geometry(tmp_path)
    records = [
        _record_for_shape(shape_code, index)
        for index, shape_code in enumerate(sorted(_shape_specs()))
    ]

    result = GeomCulvert.set_culverts(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        records,
    )

    assert result["culverts_written"] == 9
    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    expected_shapes = sorted(_shape_specs())
    expected_names = [
        _shape_specs()[shape_code]["ras_commander_shape_name"]
        for shape_code in expected_shapes
    ]

    assert culverts["Shape"].tolist() == expected_shapes
    assert culverts["ShapeName"].tolist() == expected_names
    assert culverts.loc[8, "ShapeName"] == "Con Span"

    for index, shape_code in enumerate(expected_shapes):
        chart_id, scale_id = _first_chart_scale(shape_code)
        assert culverts.loc[index, "InletType"] == chart_id
        assert culverts.loc[index, "OutletType"] == scale_id
        assert culverts.loc[index, "Span"] == pytest.approx(records[index]["Span"])
        assert culverts.loc[index, "Length"] == pytest.approx(records[index]["Length"])
        if "Rise" in records[index]:
            assert culverts.loc[index, "Rise"] == pytest.approx(records[index]["Rise"])
        else:
            assert pd.isna(culverts.loc[index, "Rise"])


def test_reader_parses_existing_culvert_and_multiple_barrel_records(tmp_path):
    geom_file = _write_geometry(tmp_path, _real_world_culvert_text())

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")

    assert len(culverts) == 2
    assert culverts.loc[0, "RecordType"] == "Culvert"
    assert culverts.loc[0, "ShapeName"] == "Con Span"
    assert culverts.loc[0, "UpstreamStation"] == pytest.approx(1000)
    assert culverts.loc[0, "BottomDepth"] == pytest.approx(0.5)
    assert culverts.loc[1, "RecordType"] == "Multiple Barrel Culv"
    assert culverts.loc[1, "ShapeName"] == "Box"
    assert culverts.loc[1, "NumBarrels"] == 2
    assert culverts.loc[1, "BarrelStations"] == [(988.5, 988.5), (1011.5, 1011.5)]


def test_reader_exposes_us_distance(tmp_path):
    # The trailing record field is the structure's US Distance (offset of the
    # upstream face into the reach), not the chart number. Both fixture records
    # carry US Distance = 5.
    geom_file = _write_geometry(tmp_path, _real_world_culvert_text())

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")

    assert "UsDistance" in culverts.columns
    assert culverts.loc[0, "UsDistance"] == pytest.approx(5.0)
    assert culverts.loc[1, "UsDistance"] == pytest.approx(5.0)


def test_set_culverts_round_trips_non_integer_us_distance(tmp_path):
    # US Distance is a float in real models (e.g. 17.07). It must survive a
    # read -> set -> read cycle without being truncated to an int (the field was
    # previously mislabeled/parsed as the integer ChartNumber).
    geom_file = _write_geometry(tmp_path)
    record = {**_culvert_records()[0], "UsDistance": 17.07}

    GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100", [record])
    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert culverts.loc[0, "UsDistance"] == pytest.approx(17.07)

    # round-trip the read-back records and confirm the value is stable
    GeomCulvert.set_culverts(
        geom_file, "Test River", "Reach 1", "100", culverts.to_dict("records")
    )
    again = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert again.loc[0, "UsDistance"] == pytest.approx(17.07)


def test_reader_reads_details_after_station_line(tmp_path):
    # Real HEC-RAS writes a fixed-width station line after a single-barrel
    # Culvert= record; the reader must skip it and still read the Bottom n /
    # Bottom Depth detail lines that follow (regression: it used to stop at the
    # station line and drop the details).
    geom_file = _write_geometry(tmp_path, _multi_group_culvert_text())

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert len(culverts) == 2
    assert culverts.loc[0, "BottomN"] == pytest.approx(0.019)
    assert culverts.loc[1, "BottomN"] == pytest.approx(0.019)
    # stations are still read from the inline record fields
    assert culverts.loc[0, "BarrelStations"] == [(95.02, 86.98)]
    assert culverts.loc[1, "BarrelStations"] == [(99.42, 91.3)]


def test_multiple_culvert_groups_round_trip_no_orphan(tmp_path):
    # A structure with two culvert groups must round-trip to exactly two records.
    # Regression: the writer's replacement range stopped at the station line after
    # the first record, leaving the second original record orphaned (2 -> 3).
    geom_file = _write_geometry(tmp_path, _multi_group_culvert_text())

    before = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert len(before) == 2
    assert before["CulvertName"].str.strip().tolist() == ["Culvert #1", "Culvert #2"]

    GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100",
                             before.to_dict("records"))
    after = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert len(after) == 2, f"expected 2 groups, got {after['CulvertName'].tolist()}"
    assert after["CulvertName"].str.strip().tolist() == ["Culvert #1", "Culvert #2"]
    for col in ["Span", "Rise", "Length", "UpstreamInvert", "DownstreamInvert",
                "InletType", "UsDistance", "BottomN"]:
        assert before[col].tolist() == pytest.approx(after[col].tolist(), nan_ok=True)


def test_writer_preserves_invert_precision(tmp_path):
    # The trailing-digit of a 7-significant-figure invert must survive a write.
    # Regression: _format_value used "{:g}" (6 sig figs) and truncated
    # 310.9502 -> 310.95 / 311.9456 -> 311.946.
    geom_file = _write_geometry(tmp_path, _multi_group_culvert_text())
    before = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100",
                             before.to_dict("records"))
    after = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert after.loc[0, "UpstreamInvert"] == pytest.approx(311.9456)
    assert after.loc[0, "DownstreamInvert"] == pytest.approx(310.9502)
    # raw text must contain the full-precision value, not the 6-sig-fig truncation
    raw = geom_file.read_text()
    assert "311.9456" in raw and "310.9502" in raw
    assert "311.946," not in raw and ",310.95," not in raw


def test_format_value_precision_and_integer_floats():
    # Unit-level guard for the formatter: integer-valued floats drop ".0";
    # non-integers keep full precision without 6-sig-fig truncation.
    assert GeomCulvert._format_value(8.0) == "8"
    assert GeomCulvert._format_value(17.07) == "17.07"
    assert GeomCulvert._format_value(310.9502) == "310.9502"
    assert GeomCulvert._format_value(311.9456) == "311.9456"
    assert GeomCulvert._format_value(0.019) == "0.019"


def _multi_barrel_with_bc_barrel_lines() -> str:
    """A 3-barrel record followed by per-barrel ``BC Culvert Barrel=`` references
    (as production HEC-RAS models write them). The first field of those lines is
    the barrel INDEX, not the count."""
    return """Geom Title=Multi-Barrel BC Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
#XS Ineff= 0 , 0

Type RM Length L Ch R = 2 ,100,,,
Bridge Culvert-0,0,0,0, 0
Multiple Barrel Culv=2,6,10,230,0.014,0.5,1,8,1,227.9,227.6, 3,Culvert #1  , 0 ,100
    1470    1210    1482    1222    1494    1234
BC Culvert Barrel=1,Barrel #1,0
BC Culvert Barrel=2,Barrel #2,0
BC Culvert Barrel=3,Barrel #3,0
Culvert Bottom n=0.014
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,90,100,100,100
#XS Ineff= 0 , 0
"""


def test_multi_barrel_numbarrels_not_collapsed_by_bc_barrel_lines(tmp_path):
    # NumBarrels must come from the record/station line (3), not the index of the
    # first BC Culvert Barrel reference. Regression: a "BC Culvert Barrel=1" line
    # used to overwrite NumBarrels with 1, collapsing a 3-barrel culvert.
    geom_file = _write_geometry(tmp_path, _multi_barrel_with_bc_barrel_lines())
    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert len(culverts) == 1
    assert culverts.loc[0, "NumBarrels"] == 3
    assert len(culverts.loc[0, "BarrelStations"]) == 3
    assert culverts.loc[0, "BarrelStations"] == [(1470.0, 1210.0), (1482.0, 1222.0), (1494.0, 1234.0)]


def _two_structures_with_distant_header(pad_lines: int) -> str:
    # Structure A (RS 100) with a culvert, then `pad_lines` of GIS-like filler
    # (numeric, no Type RM), then Structure B (RS 80) with its own culvert. When
    # B's header is far from A's, structure-end detection must still find it.
    pad = "\n".join("588679.07 3071901.03 588679.46 3071897.87" for _ in range(pad_lines))
    return f"""Geom Title=Distant Header Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
#XS Ineff= 0 , 0

Type RM Length L Ch R = 2 ,100,,,
Bridge Culvert-0,0,0,0, 0
Culvert=1,3,3,40,0.013,0.5,1,1,1,290.4,66.69,290.7,99.15,Culvert #1  , 0 ,17
   66.69   99.15
Culvert Bottom n=0.013
XS GIS Cut Line={pad_lines}
{pad}
Type RM Length L Ch R = 2 ,80,,,
Bridge Culvert-0,0,0,0, 0
Culvert=1,4,4,50,0.013,0.5,1,1,1,280.4,40.73,280.7,57.93,Culvert #2  , 0 ,9
   40.73   57.93
Culvert Bottom n=0.013
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,70,100,100,100
"""


def test_get_culverts_scopes_structure_with_distant_next_header(tmp_path):
    # Structure A's next structure header is >200 lines away. get_culverts(A) must
    # return ONLY A's culvert, not bleed downstream into structure B. Regression:
    # a fixed 200-line cap made structure-end return EOF, swallowing B's culverts.
    geom_file = _write_geometry(tmp_path, _two_structures_with_distant_header(260))
    a = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    b = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "80")
    assert a["CulvertName"].str.strip().tolist() == ["Culvert #1"]
    assert b["CulvertName"].str.strip().tolist() == ["Culvert #2"]


def _type4_multiple_opening_text() -> str:
    # Culverts can live under a Type-4 "Multiple Opening" node, not just Type-2.
    return """Geom Title=Type-4 Multiple Opening Fixture
River Reach=Test River,Reach 1
Type RM Length L Ch R = 1 ,110,100,100,100
#XS Ineff= 0 , 0

Type RM Length L Ch R = 4 ,100,,,
Bridge Culvert-0,0,0,0, 0
Multiple Barrel Culv=2,5,5,97,0.011,0.4,1,8,1,151.5,150, 5,Culvert #1  , 0 ,40
     500     480     510     490     520     500     530     510     540     520
Culvert Bottom n=0.011
Multiple Barrel Culv=2,6,6,97,0.011,0.4,1,8,1,154.5,154, 2,Culvert #2  , 0 ,40
     550     530     560     540
Culvert Bottom n=0.011
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,90,100,100,100
"""


def test_culverts_under_type4_multiple_opening_node(tmp_path):
    # A culvert under a Type-4 node is attributed to that node's RS and reachable
    # via get_culverts (not only Type-2 structures).
    geom_file = _write_geometry(tmp_path, _type4_multiple_opening_text())
    allc = GeomCulvert.get_all(geom_file)
    assert allc["RS"].astype(str).tolist() == ["100", "100"]
    cv = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert cv["CulvertName"].str.strip().tolist() == ["Culvert #1", "Culvert #2"]
    assert cv.loc[0, "NumBarrels"] == 5
    assert cv.loc[1, "NumBarrels"] == 2


def test_set_culverts_hydraulic_data_round_trips_bc_barrel_not_preserved(tmp_path):
    # Documented behavior: hydraulic culvert data round-trips faithfully, but the
    # per-barrel "BC Culvert Barrel=" references are intentionally NOT re-emitted
    # (HEC-RAS regenerates them). This test pins that contract.
    geom_file = _write_geometry(tmp_path, _multi_barrel_with_bc_barrel_lines())
    before = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100",
                             before.to_dict("records"))
    after = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    # hydraulic fields preserved
    for col in ["Shape", "Span", "Rise", "Length", "ManningsN", "EntranceLoss",
                "ExitLoss", "InletType", "OutletType", "UpstreamInvert",
                "DownstreamInvert", "NumBarrels", "UsDistance", "BottomN"]:
        assert before[col].tolist() == pytest.approx(after[col].tolist(), nan_ok=True)
    assert after.loc[0, "NumBarrels"] == 3
    # BC Culvert Barrel lines are not preserved (documented)
    assert "BC Culvert Barrel=" not in geom_file.read_text()


def test_set_culvert_updates_existing_record_and_appends(tmp_path):
    geom_file = _write_geometry(tmp_path)
    GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100", [_culvert_records()[0]])

    GeomCulvert.set_culvert(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        culvert_name="Circular One",
        Span=7.5,
        BottomDepth=0.25,
    )

    GeomCulvert.set_culvert(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        culvert=_culvert_records()[1],
    )

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert len(culverts) == 2
    assert culverts.loc[0, "CulvertName"] == "Circular One"
    assert culverts.loc[0, "Span"] == pytest.approx(7.5)
    assert culverts.loc[0, "BottomDepth"] == pytest.approx(0.25)
    assert culverts.loc[1, "CulvertName"] == "Box One"


def test_set_culverts_validates_shape_required_fields_and_barrel_pairs(tmp_path):
    geom_file = _write_geometry(tmp_path)
    valid = _culvert_records()[0]

    with pytest.raises(ValueError, match="Unsupported HEC-RAS Shape"):
        GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100", [{**valid, "Shape": 99}])

    missing_span = dict(valid)
    missing_span.pop("Span")
    with pytest.raises(ValueError, match="Span"):
        GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100", [missing_span])

    bad_barrels = {**_culvert_records()[2], "NumBarrels": 4}
    with pytest.raises(ValueError, match="# Barrels=4"):
        GeomCulvert.set_culverts(geom_file, "Test River", "Reach 1", "100", [bad_barrels])


def test_set_culverts_validates_taxonomy_chart_scale_and_numeric_ranges(tmp_path):
    geom_file = _write_geometry(tmp_path)

    pipe_arch = _record_for_shape(3)
    box_chart_id, _ = _first_chart_scale(2)
    with pytest.raises(ValueError, match="Chart #"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [{**pipe_arch, "InletType": box_chart_id}],
        )

    chart_specific_scale = _record_for_shape(1, InletType=3, OutletType=3)
    with pytest.raises(ValueError, match=r"Scale# 3.*Chart # 3"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [chart_specific_scale],
        )

    missing_rise = _record_for_shape(4)
    missing_rise.pop("Rise")
    with pytest.raises(ValueError, match="Rise"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [missing_rise],
        )

    semi_circle_without_rise = _record_for_shape(6)
    assert "Rise" not in semi_circle_without_rise
    GeomCulvert.set_culverts(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        [semi_circle_without_rise],
    )

    with pytest.raises(ValueError, match="positive value"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [{**_record_for_shape(1), "Span": 0}],
        )

    with pytest.raises(ValueError, match="nonnegative value"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [{**_record_for_shape(1), "EntranceLoss": -0.1}],
        )


def test_set_culverts_validates_group_and_identical_barrel_limits(tmp_path):
    geom_file = _write_geometry(tmp_path)

    too_many_groups = [
        _record_for_shape(1, index=i)
        for i in range(GeomCulvert.MAX_CULVERT_GROUPS_PER_CROSSING + 1)
    ]
    with pytest.raises(ValueError, match="at most 10.*Culvert Group"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            too_many_groups,
        )

    too_many_barrels = _record_for_shape(
        2,
        NumBarrels=GeomCulvert.MAX_IDENTICAL_BARRELS_PER_GROUP + 1,
        BarrelStations=[
            (900 + i, 900 + i)
            for i in range(GeomCulvert.MAX_IDENTICAL_BARRELS_PER_GROUP + 1)
        ],
    )
    with pytest.raises(ValueError, match="# Barrels=26"):
        GeomCulvert.set_culverts(
            geom_file,
            "Test River",
            "Reach 1",
            "100",
            [too_many_barrels],
        )


def test_set_culverts_accepts_chart_scale_aliases(tmp_path):
    geom_file = _write_geometry(tmp_path)
    record = _record_for_shape(7)
    chart_id = record.pop("InletType")
    scale_id = record.pop("OutletType")
    record["ChartID"] = chart_id
    record["ScaleID"] = scale_id

    GeomCulvert.set_culverts(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        [record],
    )

    culverts = GeomCulvert.get_culverts(geom_file, "Test River", "Reach 1", "100")
    assert culverts.loc[0, "InletType"] == chart_id
    assert culverts.loc[0, "OutletType"] == scale_id


def test_adjacent_cross_sections_coordinate_ineffective_flow_updates(tmp_path):
    geom_file = _write_geometry(tmp_path)

    adjacent = GeomCulvert.get_adjacent_cross_sections(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
    )
    assert adjacent["upstream"]["RS"] == "110"
    assert adjacent["downstream"]["RS"] == "90"

    result = GeomCulvert.set_adjacent_ineffective_flow(
        geom_file,
        "Test River",
        "Reach 1",
        "100",
        upstream_ineffective=[
            {"left_station": 0, "right_station": 45, "elevation": 105},
            {"left_station": 55, "right_station": 100, "elevation": 105},
        ],
        downstream_ineffective=[
            {"left_station": 0, "right_station": 35, "elevation": 103},
            {"left_station": 65, "right_station": 100, "elevation": 103},
        ],
        upstream_permanent_flags=[True, False],
        downstream_permanent_flags=[False, True],
    )

    assert result["updated"] == ["upstream", "downstream"]
    up_df, _, up_flags = GeomCrossSection.get_ineffective_flow(
        geom_file, "Test River", "Reach 1", "110"
    )
    dn_df, _, dn_flags = GeomCrossSection.get_ineffective_flow(
        geom_file, "Test River", "Reach 1", "90"
    )
    assert up_df["right_station"].tolist() == [45.0, 100.0]
    assert dn_df["left_station"].tolist() == [0.0, 65.0]
    assert up_flags == [True, False]
    assert dn_flags == [False, True]
