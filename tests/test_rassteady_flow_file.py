"""Tests for steady flow file authoring through RasSteady."""

from pathlib import Path

import pytest

from ras_commander import RasSteady


FIXTURE = """Flow Title=Fixture Steady Flow
Program Version=6.60
Number of Profiles= 3
Profile Names=Q10,Q50,Q100
River Rch & RM=Main River,Upper Reach,5000
     100     200     300
River Rch & RM=Main River,Upper Reach,2500
     125     250     375
Boundary for River Rch & Prof#=Main River,Upper Reach, 1
Up Type= 2
Dn Type= 3
Dn Slope=.001
Boundary for River Rch & Prof#=Main River,Upper Reach, 2
Up Type= 1
Up Known WS=101.5
Dn Type= 1
Dn Known WS=98.25
Boundary for River Rch & Prof#=Main River,Upper Reach, 3
Up Type= 4
Up Rating Curve # Pts= 3
      50      90     100      95     200     100
Dn Type= 4
Dn Rating Curve # Pts= 3
      40      80     120      85     300      90
DSS Import StartDate=
DSS Import StartTime=
DSS Import EndDate=
DSS Import EndTime=
DSS Import GetInterval= 0
DSS Import Interval=
DSS Import GetPeak= 0
DSS Import FillOption= 0
"""


def test_read_write_round_trip_multiple_profiles(tmp_path: Path):
    source = tmp_path / "Fixture.f01"
    output = tmp_path / "RoundTrip.f02"
    source.write_text(FIXTURE, encoding="utf-8")

    parsed = RasSteady.read_flow_file(source)

    assert parsed["flow_title"] == "Fixture Steady Flow"
    assert parsed["profile_names"] == ["Q10", "Q50", "Q100"]
    assert parsed["flow_changes"][1]["flows"] == [125.0, 250.0, 375.0]
    assert parsed["boundaries"][0]["upstream"]["type"] == RasSteady.CRITICAL_DEPTH
    assert parsed["boundaries"][0]["downstream"]["slope"] == pytest.approx(0.001)
    assert parsed["boundaries"][2]["upstream"]["rating_curve"] == [
        (50.0, 90.0),
        (100.0, 95.0),
        (200.0, 100.0),
    ]

    RasSteady.write_flow_file(output, parsed)
    written_text = output.read_text(encoding="utf-8")
    assert "Up Rating Curve # Pts= 3" in written_text
    assert "Dn Rating Curve # Pts= 3" in written_text

    reparsed = RasSteady.read_flow_file(output)

    assert reparsed == parsed


def test_create_and_update_flow_file_with_compact_boundaries(tmp_path: Path):
    path = tmp_path / "Created.f01"

    RasSteady.create_flow_file(
        path,
        flow_title="Created Steady Flow",
        profile_names=["Base", "High"],
        flow_changes=[
            {
                "river": "Main River",
                "reach": "Upper Reach",
                "station": "5000",
                "flows": [1000, 2500],
            },
            {
                "river": "Tributary",
                "reach": "Lower Reach",
                "station": "100",
                "flows": [150, 300],
            },
        ],
        boundaries=[
            RasSteady.boundary(
                "Main River",
                "Upper Reach",
                upstream=RasSteady.critical_depth(),
                downstream=RasSteady.normal_depth([0.001, 0.002]),
            ),
            RasSteady.boundary(
                "Tributary",
                "Lower Reach",
                upstream=RasSteady.known_water_surface([100.5, 101.5]),
                downstream=RasSteady.rating_curve([(100.0, 95.0), (500.0, 100.0)]),
            ),
        ],
    )

    created = RasSteady.read_flow_file(path)
    assert len(created["boundaries"]) == 4
    assert created["boundaries"][1]["downstream"]["slope"] == pytest.approx(0.002)
    assert created["boundaries"][3]["upstream"]["known_ws"] == pytest.approx(101.5)
    assert created["boundaries"][3]["downstream"]["rating_curve"] == [
        (100.0, 95.0),
        (500.0, 100.0),
    ]

    RasSteady.update_flow_file(
        path,
        flow_title="Updated Steady Flow",
        flow_changes=[
            {
                "river": "Main River",
                "reach": "Upper Reach",
                "station": "5000",
                "flows": [1100, 2600],
            }
        ],
        boundaries=[
            RasSteady.boundary(
                "Main River",
                "Upper Reach",
                downstream=RasSteady.known_water_surface([99.0, 100.0]),
            )
        ],
    )

    updated = RasSteady.read_flow_file(path)
    assert updated["flow_title"] == "Updated Steady Flow"
    assert updated["flow_changes"][0]["flows"] == [1100.0, 2600.0]
    assert updated["boundaries"][1]["downstream"]["known_ws"] == pytest.approx(100.0)


def test_validate_rejects_flow_count_mismatch():
    with pytest.raises(ValueError, match="profile count"):
        RasSteady.validate_flow_file_data(
            {
                "profile_names": ["Base", "High"],
                "number_of_profiles": 2,
                "flow_changes": [
                    {
                        "river": "Main",
                        "reach": "Reach",
                        "station": "1000",
                        "flows": [1000],
                    }
                ],
            }
        )


def test_validate_rejects_boundary_count_mismatch(tmp_path: Path):
    with pytest.raises(ValueError, match="known_ws count"):
        RasSteady.create_flow_file(
            tmp_path / "not-written.f01",
            flow_title="Bad Boundary",
            profile_names=["Base", "High"],
            flow_changes=[
                {
                    "river": "Main",
                    "reach": "Reach",
                    "station": "1000",
                    "flows": [1000, 2000],
                }
            ],
            boundaries=[
                RasSteady.boundary(
                    "Main",
                    "Reach",
                    downstream=RasSteady.known_water_surface([99.0]),
                )
            ],
        )


def test_rassteady_export_and_constants():
    assert RasSteady.KNOWN_WS == 1
    assert RasSteady.NORMAL_DEPTH == 3
    assert callable(RasSteady.read)


# --- 8-character fixed-width fields ---------------------------------------

_EDGE_VALUES = [
    0.0818,
    0.08179469,
    1e-5,
    -1e-5,
    0.0,
    -0.0,
    12345678,
    12345678.4,
    -1234567,
    -0.0123456,
    268.153,
    2680.8,
    26220,
    9999999.96,
]


@pytest.mark.parametrize("value", _EDGE_VALUES)
def test_fixed_width_field_is_exactly_eight_characters(value):
    text = RasSteady._format_fixed_width_field(value)

    assert len(text) == RasSteady.FIXED_WIDTH_FIELD_WIDTH
    assert "e" not in text.lower()
    assert float(text) == pytest.approx(
        value, rel=RasSteady.FIXED_WIDTH_RELATIVE_TOLERANCE, abs=0.0
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (268.153, " 268.153"),
        (2680.8, "  2680.8"),
        (26220, "   26220"),
        (0.08179469, ".0817947"),
        (0.0818, "  0.0818"),
        (1e-5, " 0.00001"),
        (12345678, "12345678"),
        (-0.0123456, "-.012346"),
        (0, "       0"),
        (268.15312, "268.1531"),
    ],
)
def test_fixed_width_field_uses_hec_ras_trimmed_decimals(value, expected):
    assert RasSteady._format_fixed_width_field(value) == expected


@pytest.mark.parametrize(
    "value",
    [1e9, 1e8, 123456789, -12345678, 1.23456e-7, 1.23456e-5, float("nan"), float("inf"), "x"],
)
def test_fixed_width_field_rejects_unrepresentable_values(value):
    with pytest.raises(ValueError, match="8-character|finite|numeric"):
        RasSteady._format_fixed_width_field(value)


def test_edge_values_round_trip_through_flow_file(tmp_path: Path):
    path = tmp_path / "Edge.f01"
    flows = [float(value) for value in _EDGE_VALUES]
    names = [f"PF {index + 1}" for index in range(len(flows))]

    RasSteady.create_flow_file(
        path,
        flow_title="Edge values",
        profile_names=names,
        flow_changes=[
            {"river": "River", "reach": "Reach", "station": "1000", "flows": flows}
        ],
        boundaries=[
            RasSteady.boundary(
                "River",
                "Reach",
                upstream=RasSteady.known_water_surface([1234.5678] * len(flows)),
                downstream=RasSteady.normal_depth([0.000123456] * len(flows)),
            )
        ],
    )

    parsed = RasSteady.read_flow_file(path)
    assert parsed["flow_changes"][0]["flows"] == pytest.approx(
        flows, rel=RasSteady.FIXED_WIDTH_RELATIVE_TOLERANCE, abs=0.0
    )
    for boundary in parsed["boundaries"]:
        assert boundary["upstream"]["known_ws"] == pytest.approx(1234.568)
        assert boundary["downstream"]["slope"] == pytest.approx(0.0001235)
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            assert len(line) % 8 == 0
        elif line.startswith(("Up Known WS=", "Dn Slope=")):
            assert len(line.split("=", 1)[1]) == 8


def test_small_proportional_flow_keeps_ten_per_line_column_alignment(tmp_path: Path):
    """Regression: 0.08179469 was written as 10 characters and shifted columns."""
    path = tmp_path / "Cedar.f01"
    flows = [0.08179469, 268.153, 2680.8, 26220, 5.5, 71.25, 812.4, 1500, 9.75, 33333.3]
    path.write_text(FIXTURE, encoding="utf-8")

    RasSteady.update_flow_file(
        path,
        profile_names=[f"PF {index + 1}" for index in range(len(flows))],
        flow_changes=[
            {
                "river": "CEDAR CREEK",
                "reach": "Reach-1",
                "station": "238994.0",
                "flows": flows,
            }
        ],
        boundaries=[
            RasSteady.boundary(
                "CEDAR CREEK",
                "Reach-1",
                upstream=RasSteady.critical_depth(),
                downstream=RasSteady.normal_depth([0.001] * len(flows)),
            )
        ],
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    row = lines[lines.index("River Rch & RM=CEDAR CREEK,Reach-1,238994.0") + 1]
    assert len(row) == 80
    fields = [row[start : start + 8] for start in range(0, 80, 8)]
    assert fields == [
        ".0817947",
        " 268.153",
        "  2680.8",
        "   26220",
        "     5.5",
        "   71.25",
        "   812.4",
        "    1500",
        "    9.75",
        " 33333.3",
    ]
    parsed = RasSteady.read_flow_file(path)
    assert parsed["flow_changes"][0]["flows"] == pytest.approx(flows, rel=5e-6, abs=1e-6)


def test_unrepresentable_flow_raises_before_writing(tmp_path: Path):
    path = tmp_path / "Fixture.f01"
    path.write_text(FIXTURE, encoding="utf-8")

    with pytest.raises(ValueError, match="8-character"):
        RasSteady.update_flow_file(
            path,
            flow_changes=[
                {"river": "Main River", "reach": "Upper Reach", "station": "5000", "flows": [1e9, 1, 2]}
            ],
        )

    assert path.read_text(encoding="utf-8") == FIXTURE
