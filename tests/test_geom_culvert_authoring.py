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
