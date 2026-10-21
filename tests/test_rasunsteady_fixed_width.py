"""Fixed-width (8-character field) formatting and round-trip tests for RasUnsteady.

HEC-RAS unsteady tables are ten adjacent 8-character fields per row with no
separator; full-width values touch (HEC-authored ``BaldEagleDamBrk.u01``:
``   7200070666.6669333.34   68000``).  These tests pin the field formatter,
the readers that must slice 8-character fields rather than split on
whitespace, and every RasUnsteady inline-table writer.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasUnsteady

FIXTURES = Path(__file__).parent / "fixtures" / "rasunsteady_fixed_width"
BALD_EAGLE_U02 = FIXTURES / "BaldEagleDamBrk.u02"

# Touching full-width values: "-1234.56  150000123456.7       7       8"
TOUCHING = [-1234.56, 150000.0, 123456.7, 7.0, 8.0]
# Gate/nav tables keep the legacy %g rule (six significant figures); these
# values fill all eight characters and touch: "-1234.56-9876.5412345678       7"
GATE_TOUCHING = [-1234.56, -9876.54, 12345678.0, 7.0]


def _fields(line: str) -> list[str]:
    line = line.rstrip("\r\n")
    return [line[k:k + 8] for k in range(0, len(line), 8)]


def _data_rows(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    idx = next(i for i, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[idx + 1:]:
        if "=" in line or not line.strip():
            break
        rows.append(line)
    return rows


# ---------------------------------------------------------------------------
# _format_fixed_width_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, kwargs, expected",
    [
        (1234.5, {}, " 1234.50"),
        (99999.999, {}, "100000.0"),  # rounding carry re-checked per precision
        (123456.78, {}, "123456.8"),
        (99999999.0, {}, "99999999"),
        (-9999999.0, {}, "-9999999"),
        (-123456.7, {}, " -123457"),
        (2.0, {"trim_trailing_zeros": True, "max_decimals": 6}, "       2"),
        (0.0, {"zero_as_blank": True}, "        "),
        (1.5, {"min_decimals": 2}, "    1.50"),
    ],
)
def test_format_fixed_width_value_cases(value, kwargs, expected):
    assert RasUnsteady._format_fixed_width_value(value, **kwargs) == expected


@pytest.mark.parametrize("value", [-0.0, -0.004, -1e-9, -1e-7])
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"min_decimals": 2}, {"max_decimals": 1}, {"trim_trailing_zeros": True}],
)
def test_format_fixed_width_value_never_emits_negative_zero(value, kwargs):
    text = RasUnsteady._format_fixed_width_value(value, **kwargs)
    assert len(text) == 8
    assert "-" not in text
    assert float(text) == 0


@pytest.mark.parametrize("value", [99999999.5, -9999999.5, 1e8, -1e7])
def test_format_fixed_width_value_rejects_overflow(value):
    with pytest.raises(ValueError, match="8-character"):
        RasUnsteady._format_fixed_width_value(value)


def test_format_fixed_width_value_precipitation_min_decimals_rejects():
    with pytest.raises(ValueError):
        RasUnsteady._format_fixed_width_value(100000.0, min_decimals=2)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, None, "12.5", "abc"])
def test_format_fixed_width_value_rejects_non_numeric(value):
    with pytest.raises(ValueError):
        RasUnsteady._format_fixed_width_value(value)


def test_format_fixed_width_value_validates_decimal_bounds():
    with pytest.raises(ValueError):
        RasUnsteady._format_fixed_width_value(1.0, max_decimals=1, min_decimals=2)
    with pytest.raises(ValueError):
        RasUnsteady._format_fixed_width_value(1.0, min_decimals=-1)


# ---------------------------------------------------------------------------
# Gate / navigation-dam formatter (legacy %8g)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [2.0, 0.5, 18777.81, 111.5698, -5.25, 0.0001, 99999.99, -123456.7, 1e-7, -1e-7],
)
def test_general_formatter_matches_legacy_8g_when_it_fit(value):
    legacy = f"{value:8g}"
    assert len(legacy) == 8
    assert RasUnsteady._format_general_fixed_width_value(value) == legacy


@pytest.mark.parametrize(
    "value, expected",
    [
        (1e-7, "   1e-07"),
        (-1e-7, "  -1e-07"),
        (1.234e-5, "1.23e-05"),  # legacy %8g emitted 9 characters
        (-1.234567e-6, "-1.2e-06"),
        (1e6, " 1000000"),  # legacy "   1e+06"; plain decimal now
        (1234567.8, " 1234568"),  # legacy "1.23457e+06" overflowed
        (-0.0, "       0"),  # legacy "      -0"
    ],
)
def test_general_formatter_preserves_small_values_and_avoids_overflow(value, expected):
    text = RasUnsteady._format_general_fixed_width_value(value)
    assert text == expected
    if value != 0:
        assert float(text) != 0
        assert math.isclose(float(text), value, rel_tol=0.05)


def test_general_formatter_rejects_unrepresentable():
    with pytest.raises(ValueError):
        RasUnsteady._format_general_fixed_width_value(1e9)
    with pytest.raises(ValueError):
        RasUnsteady._format_general_fixed_width_value(math.nan)


# ---------------------------------------------------------------------------
# Legacy "int if integral else %8.Nf" formatter (groundwater, rating, lateral)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, decimals, expected",
    [
        (12.0, 2, "      12"),
        (79564.2, 2, "79564.20"),
        (-1234.56, 2, "-1234.56"),
        (150000.0, 2, "150000.0"),  # legacy "150000.00" overflowed
        (59649.96, 1, " 59650.0"),
        (150000.0, 1, "150000.0"),
        (12345678.0, 1, "12345678"),
        (-0.04, 1, "     0.0"),  # legacy "    -0.0"
    ],
)
def test_legacy_integer_or_fixed(value, decimals, expected):
    assert RasUnsteady._format_legacy_integer_or_fixed(value, decimals) == expected


# ---------------------------------------------------------------------------
# Gate openings: real HEC-RAS example and touching fields
# ---------------------------------------------------------------------------


def _bald_eagle_copy(tmp_path: Path) -> Path:
    target = tmp_path / "BaldEagleDamBrk.u02"
    shutil.copyfile(BALD_EAGLE_U02, target)
    return target


def test_get_gate_openings_reads_real_bald_eagle_example(tmp_path):
    u02 = _bald_eagle_copy(tmp_path)
    gate = RasUnsteady.get_gate_openings(u02)
    assert gate["gate_name"] == "Gate #1"
    assert gate["count"] == 100
    assert gate["values"] == [2.0] * 100


def test_set_gate_openings_bald_eagle_identity_rewrite_is_byte_identical(tmp_path):
    u02 = _bald_eagle_copy(tmp_path)
    RasUnsteady.set_gate_openings(u02, [2.0] * 100)
    assert u02.read_bytes() == BALD_EAGLE_U02.read_bytes()


def test_set_gate_openings_bald_eagle_touching_fields_round_trip(tmp_path):
    u02 = _bald_eagle_copy(tmp_path)
    original_lines = BALD_EAGLE_U02.read_bytes().splitlines(keepends=True)
    tail_start = next(
        i for i, line in enumerate(original_lines) if line.startswith(b"Boundary Location=")
        and i > 40
    )
    tail = b"".join(original_lines[tail_start:])

    values = GATE_TOUCHING * 4
    RasUnsteady.set_gate_openings(u02, values)
    rows = _data_rows(u02.read_text(), "Gate Openings=")
    assert rows[0][:32] == "-1234.56-9876.5412345678       7"
    assert all(len(row) % 8 == 0 for row in rows)
    assert RasUnsteady.get_gate_openings(u02)["values"] == values

    # Second rewrite (shorter) must replace exactly the old rows and keep
    # the following Boundary Location= block and everything after it.
    RasUnsteady.set_gate_openings(u02, [1.0, 2.0])
    data = u02.read_bytes()
    assert data.endswith(tail)
    assert RasUnsteady.get_gate_openings(u02)["values"] == [1.0, 2.0]


def _two_gate_file(tmp_path: Path) -> Path:
    block = (
        "Boundary Location=                ,                ,        ,        ,"
        "Dam             ,                ,                ,                                \n"
        "Gate Name=Gate #1\n"
        "Gate DSS Path=\n"
        "Gate Use DSS=False\n"
        "Gate Time Interval=1HOUR\n"
        "Gate Use Fixed Start Time=False\n"
        "Gate Fixed Start Date/Time=,\n"
        "Gate Openings= 3 \n"
        "       1       2       3\n"
        "Gate Name=Gate #2\n"
        "Gate DSS Path=\n"
        "Gate Use DSS=False\n"
        "Gate Time Interval=1HOUR\n"
        "Gate Use Fixed Start Time=False\n"
        "Gate Fixed Start Date/Time=,\n"
        "Gate Openings= 2 \n"
        "       4       5\n"
    )
    path = tmp_path / "gates.u01"
    path.write_text("Flow Title=gates\nProgram Version=6.60\n" + block)
    return path


def test_set_gate_openings_never_consumes_next_gate_name(tmp_path):
    u01 = _two_gate_file(tmp_path)
    RasUnsteady.set_gate_openings(u01, GATE_TOUCHING)
    text = u01.read_text()
    assert "-1234.56-9876.5412345678       7\nGate Name=Gate #2" in text
    assert RasUnsteady.get_gate_openings(u01)["values"] == GATE_TOUCHING

    # Second rewrite after full-width fields were written.
    RasUnsteady.set_gate_openings(u01, [1e-7, 0.25])
    text = u01.read_text()
    assert text.count("Gate Name=") == 2
    assert "Gate Name=Gate #2" in text
    assert RasUnsteady.get_gate_openings(u01)["values"] == [1e-7, 0.25]
    lines = text.splitlines()
    i = lines.index("Gate Name=Gate #2")
    assert lines[i - 1] == "   1e-07    0.25"
    assert lines[i - 2] == "Gate Openings= 2 "


# ---------------------------------------------------------------------------
# Groundwater interflow
# ---------------------------------------------------------------------------


def _gw_file(tmp_path: Path) -> Path:
    text = (
        "Flow Title=gw\n"
        "Program Version=6.60\n"
        "Boundary Location=                ,                ,        ,        ,"
        "                ,Area1           ,                ,GW Line                         \n"
        "Interval=1HOUR\n"
        "Ground Water Interflow= 3 \n"
        "     100     101     102\n"
        "Ground Water Darcy K=0.5\n"
        "Ground Water Darcy K/day=43200\n"
        "Ground Water Darcy Distance=100\n"
        "DSS Path=\n"
        "Use DSS=False\n"
        "Boundary Location=                ,                ,        ,        ,"
        "                ,Area1           ,                ,Next Line                       \n"
        "Interval=1HOUR\n"
    )
    path = tmp_path / "gw.u01"
    path.write_text(text)
    return path


def test_groundwater_interflow_touching_fields_round_trip(tmp_path):
    u01 = _gw_file(tmp_path)
    RasUnsteady.set_groundwater_interflow(u01, TOUCHING)
    rows = _data_rows(u01.read_text(), "Ground Water Interflow=")
    assert rows == ["-1234.56150000.0123456.7       7       8"]
    gw = RasUnsteady.get_groundwater_interflow(u01)
    assert gw["values"] == TOUCHING
    assert gw["darcy_k"] == 0.5
    assert gw["darcy_distance"] == 100.0

    values = [float(v) + 0.25 for v in range(23)]
    RasUnsteady.set_groundwater_interflow(u01, values, darcy_k=0.75)
    text = u01.read_text()
    gw = RasUnsteady.get_groundwater_interflow(u01)
    assert gw["values"] == values
    assert gw["darcy_k"] == 0.75
    assert "Ground Water Darcy Distance=100" in text
    assert text.count("Boundary Location=") == 2
    assert text.rstrip().endswith("Next Line                       \nInterval=1HOUR")


def test_groundwater_interflow_legacy_bytes_preserved(tmp_path):
    u01 = _gw_file(tmp_path)
    RasUnsteady.set_groundwater_interflow(u01, [12.0, 79564.2, -3.5])
    rows = _data_rows(u01.read_text(), "Ground Water Interflow=")
    assert rows == ["      1279564.20   -3.50"]


# ---------------------------------------------------------------------------
# Navigation dam SFT table
# ---------------------------------------------------------------------------


def test_navigation_dam_sft_round_trip_with_small_and_wide_values(tmp_path):
    u01 = tmp_path / "nav.u01"
    u01.write_text(
        "Flow Title=nav\n"
        "Boundary Location=River           ,Reach           ,100     ,        ,"
        "                ,                ,                ,                                \n"
        "Navigation Dam=1,2,3\n"
        "Navigation Dam SFT= 2 \n"
        "       1       2\n"
        "       3       4\n"
        "       5       6\n"
        "Navigation Dam Flow Monitor RRR=River,Reach,200\n"
        "Boundary Location=River           ,Reach           ,50      ,        ,"
        "                ,                ,                ,                                \n"
    )
    flow = [150000.25, 1234567.8, 1e-7]
    stage_open = [-0.0, 111.5698, 18777.81]
    stage_closed = [1.0, 2.0, 3.0]
    RasUnsteady.set_navigation_dam(
        u01, sft_flow=flow, sft_stage_open=stage_open, sft_stage_closed=stage_closed
    )
    text = u01.read_text()
    lines = text.splitlines()
    i = lines.index("Navigation Dam SFT= 3 ")
    assert lines[i + 1] == "  150000 1234568   1e-07"
    assert lines[i + 2] == "       0  111.57 18777.8"
    assert lines[i + 3] == "       1       2       3"
    assert lines[i + 4] == "Navigation Dam Flow Monitor RRR=River,Reach,200"
    nav = RasUnsteady.get_navigation_dam(u01)
    assert nav["sft_flow"] == [150000.0, 1234568.0, 1e-7]
    assert nav["sft_stage_open"] == [0.0, 111.57, 18777.8]
    assert nav["flow_monitor_rrr"] == "River,Reach,200"


# ---------------------------------------------------------------------------
# write_table_to_file, rating curve, lateral, uniform lateral, stage/flow
# ---------------------------------------------------------------------------


class _InitializedRas:
    def check_initialized(self):
        return None


def test_write_table_to_file_full_width_fields(tmp_path):
    u01 = tmp_path / "table.u01"
    u01.write_text(
        "Flow Title=t\n"
        "Flow Hydrograph= 3 \n"
        "       1       2       3\n"
        "DSS Path=\n"
    )
    df = pd.DataFrame({"Value": [123456.78, -0.004, 99999999.0]})
    RasUnsteady.write_table_to_file(
        str(u01), "Flow Hydrograph=", df, 2, ras_object=_InitializedRas()
    )
    lines = u01.read_text().splitlines()
    assert lines[2] == "123456.8    0.0099999999"
    assert lines[3] == "DSS Path="
    with pytest.raises(ValueError):
        RasUnsteady.write_table_to_file(
            str(u01), "Flow Hydrograph=", pd.DataFrame({"Value": [1e8]}), 2,
            ras_object=_InitializedRas(),
        )


def _boundary_line(river: str, reach: str, station: str, downstream: str = "") -> str:
    return (
        f"Boundary Location={river:<16},{reach:<16},{station:<8},{downstream:<8},"
        f"{'':<16},{'':<16},{'':<16},{'':<32}\n"
    )


def test_set_rating_curve_full_width_and_legacy_bytes(tmp_path):
    u01 = tmp_path / "rc.u01"
    u01.write_text(
        "Flow Title=rc\n"
        + _boundary_line("River", "Reach", "0")
        + "Rating Curve= 2 \n"
        + "     100       0     110     500\n"
        + "DSS Path=\n"
    )
    rc = pd.DataFrame(
        {"stage": [100.0, 110.25, 120.0], "discharge": [59649.96, 150000.0, 12345678.0]}
    )
    RasUnsteady.set_rating_curve(u01, rc, river="River", reach="Reach", station="0")
    rows = _data_rows(u01.read_text(), "Rating Curve=")
    assert rows == ["     100 59650.0   110.2150000.0     12012345678"]
    back = RasUnsteady.get_rating_curve(u01, river="River", reach="Reach", station="0")
    assert back["discharge"].tolist() == [59650.0, 150000.0, 12345678.0]
    assert back["stage"].tolist() == [100.0, 110.2, 120.0]


def _lateral_file(tmp_path: Path, header: str, downstream: str = "") -> Path:
    u01 = tmp_path / "lat.u01"
    u01.write_text(
        "Flow Title=lat\n"
        + _boundary_line("River", "Reach", "1000", downstream)
        + "Interval=1HOUR\n"
        + f"{header} 3 \n"
        + "     100     200     300\n"
        + "Flow Hydrograph Slope= 0.001 \n"
        + "DSS Path=\n"
        + "Use DSS=False\n"
    )
    return u01


def test_set_lateral_inflow_hydrograph_full_width(tmp_path):
    u01 = _lateral_file(tmp_path, "Lateral Inflow Hydrograph=")
    flows = [150000.25, -123456.7, 59649.96, 12.0]
    RasUnsteady.set_lateral_inflow_hydrograph(
        u01, pd.DataFrame({"flow": flows}), river="River", reach="Reach", station="1000"
    )
    rows = _data_rows(u01.read_text(), "Lateral Inflow Hydrograph=")
    assert rows == ["150000.2 -123457 59650.0      12"]
    back = RasUnsteady.get_lateral_inflow_hydrograph(
        u01, river="River", reach="Reach", station="1000"
    )
    assert back["flow"].tolist() == [150000.2, -123457.0, 59650.0, 12.0]


def test_set_uniform_lateral_inflow_hydrograph_full_width(tmp_path):
    u01 = _lateral_file(tmp_path, "Uniform Lateral Inflow Hydrograph=", downstream="500")
    flows = [150000.25, 99999.0, 100000.0]
    RasUnsteady.set_uniform_lateral_inflow_hydrograph(
        u01, pd.DataFrame({"flow": flows}), river="River", reach="Reach", station="1000"
    )
    rows = _data_rows(u01.read_text(), "Uniform Lateral Inflow Hydrograph=")
    assert rows == ["150000.2   99999100000.0"]
    back = RasUnsteady.get_uniform_lateral_inflow_hydrograph(
        u01, river="River", reach="Reach", station="1000"
    )
    assert back["flow"].tolist() == [150000.2, 99999.0, 100000.0]


def test_set_stage_flow_hydrograph_full_width(tmp_path):
    u01 = tmp_path / "sf.u01"
    u01.write_text(
        "Flow Title=sf\n"
        + _boundary_line("River", "Reach", "750")
        + "Interval=1HOUR\n"
        + "DSS Path=\n"
        + "Use DSS=False\n"
    )
    df = pd.DataFrame({"stage": [612.345678, 0.0], "flow": [150000.25, 1234567.8]})
    RasUnsteady.set_stage_flow_hydrograph(
        u01, df, river="River", reach="Reach", station="750"
    )
    rows = _data_rows(u01.read_text(), "Observed Stage and Flow Hydrograph=")
    assert rows == ["612.3457150000.2         1234568"]
    back = RasUnsteady.get_stage_flow_hydrograph(
        u01, river="River", reach="Reach", station="750"
    )
    assert back["stage"].tolist() == [612.3457, 0.0]
    assert back["flow"].tolist() == [150000.2, 1234568.0]
