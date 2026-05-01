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
Up Rating Curve= 3
      90      50      95     100     100     200
Dn Type= 4
Dn Rating Curve= 3
      80      40      85     120      90     300
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
        (90.0, 50.0),
        (95.0, 100.0),
        (100.0, 200.0),
    ]

    RasSteady.write_flow_file(output, parsed)
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
                downstream=RasSteady.rating_curve([(95.0, 100.0), (100.0, 500.0)]),
            ),
        ],
    )

    created = RasSteady.read_flow_file(path)
    assert len(created["boundaries"]) == 4
    assert created["boundaries"][1]["downstream"]["slope"] == pytest.approx(0.002)
    assert created["boundaries"][3]["upstream"]["known_ws"] == pytest.approx(101.5)
    assert created["boundaries"][3]["downstream"]["rating_curve"] == [
        (95.0, 100.0),
        (100.0, 500.0),
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
