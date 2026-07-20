"""Regression tests for DSS pathname validation."""

from ras_commander import RasDss


def test_blank_a_part_is_a_valid_six_part_dss_pathname():
    pathname = "//SUBBASIN-27/FLOW/23MAR2023/5MIN/RUN:MARCH23_2023 -SPL/"

    result = RasDss.check_pathname_format(pathname)

    assert result.passed is True
    assert result.severity.name == "WARNING"
    assert result.details["parts"] == {
        "basin": "",
        "location": "SUBBASIN-27",
        "parameter": "FLOW",
        "date": "23MAR2023",
        "interval": "5MIN",
        "scenario": "RUN:MARCH23_2023 -SPL",
    }
    assert RasDss.is_valid_pathname(pathname) is True


def test_extra_leading_component_is_not_a_six_part_dss_pathname():
    result = RasDss.check_pathname_format("//A/B/C/D/E/F/")

    assert result.passed is False
    assert result.details["actual_parts"] == 7
