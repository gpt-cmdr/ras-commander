"""Focused tests for DSS boundary inventory and pathname parsing."""

from pathlib import Path

import pytest

from ras_commander import RasUnsteady

EXISTING_COLUMNS = {
    "river",
    "reach",
    "station",
    "bc_type",
    "interval",
    "dss_file",
    "dss_path",
    "dss_part_a",
    "dss_part_b",
    "dss_part_c",
    "dss_part_d",
    "dss_part_e",
    "dss_part_f",
    "use_dss",
    "data_count",
    "line_number",
}

ADDITIVE_COLUMNS = {
    "downstream_station",
    "sa_2d_name",
    "bc_line",
    "boundary_name",
    "boundary_index",
}


def _location(*fields: str) -> str:
    """Build an eight- or nine-field Boundary Location record."""
    assert len(fields) in {8, 9}
    return f"Boundary Location={','.join(fields)}"


def _write_unsteady(tmp_path: Path, lines: list[str]) -> Path:
    unsteady_file = tmp_path / "Example.u01"
    unsteady_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return unsteady_file


def test_inventory_extracts_1d_and_2d_identity_and_unfiltered_index(
    tmp_path: Path,
) -> None:
    unsteady_file = _write_unsteady(
        tmp_path,
        [
            "Flow Title=Inventory regression",
            _location("River A", "Reach 1", "1200", "1100", "", "", "", "", ""),
            "Boundary Name=Inline boundary filtered from DSS inventory",
            "Flow Hydrograph= 2",
            "Use DSS=False",
            _location("River A", "Reach 1", "1000", "900", "", "", "", "", ""),
            "Boundary Name=Downstream 1D flow",
            "Flow Hydrograph= 0",
            "Interval=1HOUR",
            "DSS File=.\\hydrology\\inflow.dss",
            "DSS Path=/PROJECT/ONE-D/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            "Use DSS=True",
            _location("", "", "", "", "", "Lower Area", "", "West Inflow"),
            "Boundary Name=West 2D inflow line",
            "Stage Hydrograph= 0",
            "Interval=15MIN",
            "DSS File=.\\hydrology\\stage.dss",
            "DSS Path=//WEST-LINE/STAGE/01JAN2020/15MIN/RUN:BASE/",
            "Use DSS=True",
        ],
    )

    result = RasUnsteady.get_dss_boundaries(unsteady_file)

    assert result["boundary_index"].tolist() == [1, 2]

    one_d = result.iloc[0]
    assert one_d["river"] == "River A"
    assert one_d["reach"] == "Reach 1"
    assert one_d["station"] == "1000"
    assert one_d["downstream_station"] == "900"
    assert one_d["boundary_name"] == "Downstream 1D flow"
    assert one_d["sa_2d_name"] == ""
    assert one_d["bc_line"] == ""

    two_d = result.iloc[1]
    assert two_d["river"] == ""
    assert two_d["reach"] == ""
    assert two_d["station"] == ""
    assert two_d["downstream_station"] == ""
    assert two_d["sa_2d_name"] == "Lower Area"
    assert two_d["bc_line"] == "West Inflow"
    assert two_d["boundary_name"] == "West 2D inflow line"


@pytest.mark.parametrize(
    ("pathname", "expected"),
    [
        (
            "//LOCATION/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            ("", "LOCATION", "FLOW", "01JAN2020", "1HOUR", "RUN:BASE"),
        ),
        (
            "//LOCATION/FLOW//1HOUR/RUN/",
            ("", "LOCATION", "FLOW", "", "1HOUR", "RUN"),
        ),
        (
            "//LOCATION/FLOW/01JAN2020/1HOUR//",
            ("", "LOCATION", "FLOW", "01JAN2020", "1HOUR", ""),
        ),
        (
            "//PROJECT/LOCATION/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            ("PROJECT", "LOCATION", "FLOW", "01JAN2020", "1HOUR", "RUN:BASE"),
        ),
        (
            "/PROJECT/LOCATION/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            ("PROJECT", "LOCATION", "FLOW", "01JAN2020", "1HOUR", "RUN:BASE"),
        ),
        (
            "/PROJECT/LOCATION/FLOW/01JAN2020/1HOUR//",
            ("PROJECT", "LOCATION", "FLOW", "01JAN2020", "1HOUR", ""),
        ),
        ("", ("", "", "", "", "", "")),
    ],
    ids=[
        "empty-a-five-b-through-f-fields",
        "empty-a-with-blank-d-part",
        "empty-a-with-blank-f-part",
        "legacy-double-leading-six-populated-parts",
        "canonical-single-leading-six-populated-parts",
        "canonical-with-blank-f-part",
        "empty-path",
    ],
)
def test_parse_dss_path_preserves_all_six_parts(
    pathname: str,
    expected: tuple[str, str, str, str, str, str],
) -> None:
    parsed = RasUnsteady._parse_dss_path(pathname)

    assert tuple(parsed[f"dss_part_{part}"] for part in "abcdef") == expected


def test_inventory_distinguishes_uniform_lateral_boundary_types(tmp_path: Path) -> None:
    location = _location("River A", "Reach 1", "1000", "900", "", "", "", "", "")
    unsteady_file = _write_unsteady(
        tmp_path,
        [
            location,
            "Uniform Lateral Inflow= 0",
            "DSS File=uniform.dss",
            "DSS Path=//REACH/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            "Use DSS=True",
            location,
            "Uniform Lateral Inflow Hydrograph= 0",
            "DSS File=uniform-hydrograph.dss",
            "DSS Path=//REACH/FLOW/01JAN2020/1HOUR/RUN:BASE/",
            "Use DSS=True",
        ],
    )

    result = RasUnsteady.get_dss_boundaries(unsteady_file)

    assert result["bc_type"].tolist() == [
        "Uniform Lateral Inflow",
        "Uniform Lateral Inflow Hydrograph",
    ]


def test_missing_dss_path_keeps_all_part_columns_empty(tmp_path: Path) -> None:
    unsteady_file = _write_unsteady(
        tmp_path,
        [
            _location("River A", "Reach 1", "1000", "900", "", "", "", "", ""),
            "Flow Hydrograph= 0",
            "DSS File=missing-path.dss",
            "Use DSS=True",
        ],
    )

    result = RasUnsteady.get_dss_boundaries(unsteady_file)

    assert len(result) == 1
    assert result.iloc[0][[f"dss_part_{part}" for part in "abcdef"]].tolist() == [
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def test_inventory_retains_existing_columns_when_no_dss_boundaries(
    tmp_path: Path,
) -> None:
    unsteady_file = _write_unsteady(
        tmp_path,
        [
            _location("River A", "Reach 1", "1000", "900", "", "", "", "", ""),
            "Flow Hydrograph= 2",
            "Use DSS=False",
        ],
    )

    result = RasUnsteady.get_dss_boundaries(unsteady_file)

    assert result.empty
    assert EXISTING_COLUMNS <= set(result.columns)
    assert ADDITIVE_COLUMNS <= set(result.columns)
