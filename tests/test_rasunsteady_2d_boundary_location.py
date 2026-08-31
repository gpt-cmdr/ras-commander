from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasUnsteady


def _write_geometry(
    path: Path,
    *,
    area_name: str = "Breakout Area",
    line_name: str = "Breakout Inflow",
    duplicate: bool = False,
) -> Path:
    block = (
        f"BC Line Name={line_name:<40}\r\n"
        f"BC Line Storage Area={area_name:<16}\r\n"
        "BC Line Start Position= 0 , 0 \r\n"
        "BC Line End Position= 0 , 10 \r\n"
        "BC Line Arc= 2 \r\n"
        "               0               0               0              10\r\n"
        "BC Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308 \r\n"
    )
    path.write_bytes(("Geom Title=breakout\r\n" + block * (2 if duplicate else 1)).encode())
    return path


def _write_geometry_locations(path: Path, locations: list[tuple[str, str]]) -> Path:
    blocks = []
    for area_name, line_name in locations:
        blocks.append(
            f"BC Line Name={line_name:<40}\r\n"
            f"BC Line Storage Area={area_name:<16}\r\n"
            "BC Line Start Position= 0 , 0 \r\n"
            "BC Line End Position= 0 , 10 \r\n"
            "BC Line Arc= 2 \r\n"
            "               0               0               0              10\r\n"
            "BC Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308 \r\n"
        )
    path.write_bytes(("Geom Title=breakout\r\n" + "".join(blocks)).encode())
    return path


def _existing_boundary(area_name: str, line_name: str) -> str:
    fields = (
        ("", 16),
        ("", 16),
        ("", 8),
        ("", 8),
        ("", 16),
        (area_name, 16),
        ("", 16),
        (line_name, 32),
    )
    return "Boundary Location=" + ",".join(
        f"{value:<{width}}" for value, width in fields
    )


def _write_unsteady(path: Path) -> Path:
    text = (
        "Flow Title=breakout\r\n"
        "Program Version=6.60\r\n"
        "Use Restart= 0 \r\n"
        f"{_existing_boundary('Parent Area', 'Parent Outflow')}\r\n"
        "Friction Slope=0.0003\r\n"
        "Precipitation Mode=Disable\r\n"
    )
    path.write_bytes(text.encode())
    return path


def _boundary_block(text: str, area_name: str, line_name: str) -> str:
    marker = _existing_boundary(area_name, line_name).rstrip()
    start = text.index(marker)
    next_boundary = text.find("Boundary Location=", start + len(marker))
    return text[start:] if next_boundary < 0 else text[start:next_boundary]


def test_ensure_location_then_author_inline_flow_hydrograph(tmp_path):
    geometry = _write_geometry(tmp_path / "breakout.g02")
    unsteady = _write_unsteady(tmp_path / "breakout.u02")

    created = RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )

    assert created["created"] is True
    assert created["geometry_match_count"] == 1
    assert created["boundary_count_before"] == 1
    assert created["boundary_count_after"] == 2

    hydrograph = pd.DataFrame(
        {"hour": [0.0, 0.5, 1.0, 1.5, 2.0], "value": [10, 25, 50, 25, 10]}
    )
    assert RasUnsteady.set_boundary_inline_hydrograph(
        unsteady,
        hydrograph,
        bc_type="Flow Hydrograph",
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )
    slope = RasUnsteady.set_flow_hydrograph_slope(
        unsteady,
        0.0005,
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )
    assert slope["new_eg_slope"] == 0.0005

    raw = unsteady.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode()
    block = _boundary_block(text, "Breakout Area", "Breakout Inflow")
    assert "Interval=30MIN\r\n" in block
    assert "Flow Hydrograph= 5 \r\n" in block
    assert "Flow Hydrograph Slope= 0.0005 " in block
    assert "Use DSS=False\r\n" in block
    assert block.index("   10.00") < block.index("Use DSS=False")

    before = unsteady.read_bytes()
    existing = RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )
    assert existing["created"] is False
    assert unsteady.read_bytes() == before


def test_ensure_location_supports_empty_unsteady_boundary_collection(tmp_path):
    geometry = _write_geometry(tmp_path / "breakout.g02")
    unsteady = tmp_path / "breakout.u02"
    unsteady.write_bytes(
        b"Flow Title=breakout\r\nProgram Version=6.60\r\nUse Restart= 0 \r\n"
        b"Precipitation Mode=Disable\r\n"
    )

    result = RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )

    lines = unsteady.read_text(encoding="utf-8").splitlines()
    assert result["insert_index"] == 3
    assert lines[3].startswith("Boundary Location=")
    assert lines[4] == "Precipitation Mode=Disable"


def test_ensure_location_then_author_normal_depth_outflow(tmp_path):
    geometry = _write_geometry(
        tmp_path / "breakout.g02",
        line_name="Breakout Outflow",
    )
    unsteady = _write_unsteady(tmp_path / "breakout.u02")
    RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="Breakout Area",
        bc_line="Breakout Outflow",
    )

    result = RasUnsteady.set_normal_depth_boundary(
        unsteady,
        friction_slope=0.0004,
        area_2d="Breakout Area",
        bc_line="Breakout Outflow",
    )

    assert result["previous_bc_type"] is None
    assert result["new_friction_slope"] == 0.0004
    assert result["lines_inserted"] == 1
    block = _boundary_block(
        unsteady.read_text(encoding="utf-8"),
        "Breakout Area",
        "Breakout Outflow",
    )
    assert "Friction Slope=0.0004\n" in block


def test_replace_2d_locations_removes_complete_2d_blocks_and_preserves_non_2d(tmp_path):
    geometry = _write_geometry_locations(
        tmp_path / "breakout.g02",
        [
            ("Breakout Area", "Breakout Inflow"),
            ("Breakout Area", "Breakout Outflow"),
        ],
    )
    unsteady = tmp_path / "breakout.u02"
    area_wide_fields = ["", "", "", "", "", "Parent Area", "", ""]
    one_d_fields = ["River", "Reach", "100", "", "", "", "", ""]
    gate_fields = ["", "", "", "", "Storage Area", "", "", ""]
    unsteady.write_bytes(
        (
            "Flow Title=breakout\r\n"
            "Program Version=6.60\r\n"
            "Use Restart= 0 \r\n"
            f"{_existing_boundary('Parent Area', 'Parent Inflow')}\r\n"
            "Interval=1HOUR\r\n"
            "Flow Hydrograph= 2 \r\n"
            "    1.00    2.00\r\n"
            "Use DSS=False\r\n"
            f"Boundary Location={','.join(area_wide_fields)}\r\n"
            "Precipitation Hydrograph= 2 \r\n"
            "    0.10    0.20\r\n"
            f"Boundary Location={','.join(one_d_fields)}\r\n"
            "Friction Slope=0.0003,0\r\n"
            f"Boundary Location={','.join(gate_fields)}\r\n"
            "Gate Name=Gate 1\r\n"
            "Precipitation Mode=Enable\r\n"
        ).encode()
    )

    result = RasUnsteady.replace_2d_boundary_locations(
        unsteady,
        geometry,
        [
            {"area_2d": "Breakout Area", "bc_line": "Breakout Inflow"},
            {"area_2d": "Breakout Area", "bc_line": "Breakout Outflow"},
        ],
    )

    assert result["removed_locations"] == [
        {"area_2d": "Parent Area", "bc_line": "Parent Inflow"},
        {"area_2d": "Parent Area", "bc_line": ""},
    ]
    assert result["preserved_non_2d_block_count"] == 2
    assert result["inserted_locations"] == [
        {"area_2d": "Breakout Area", "bc_line": "Breakout Inflow"},
        {"area_2d": "Breakout Area", "bc_line": "Breakout Outflow"},
    ]
    text = unsteady.read_text(encoding="utf-8")
    assert "Parent Inflow" not in text
    assert "Precipitation Hydrograph=" not in text
    assert "    1.00    2.00" not in text
    assert "River,Reach,100" in text
    assert "Gate Name=Gate 1" in text
    assert text.count("Breakout Inflow") == 1
    assert text.count("Breakout Outflow") == 1


@pytest.mark.parametrize(
    ("geometry_area", "geometry_line", "requested_area", "requested_line", "match"),
    [
        ("Other Area", "Breakout Inflow", "Breakout Area", "Breakout Inflow", "attached"),
        ("Breakout Area", "Other Inflow", "Breakout Area", "Breakout Inflow", "does not contain"),
    ],
)
def test_ensure_location_rejects_geometry_mismatch(
    tmp_path,
    geometry_area,
    geometry_line,
    requested_area,
    requested_line,
    match,
):
    geometry = _write_geometry(
        tmp_path / "breakout.g02",
        area_name=geometry_area,
        line_name=geometry_line,
    )
    unsteady = _write_unsteady(tmp_path / "breakout.u02")

    with pytest.raises(ValueError, match=match):
        RasUnsteady.ensure_2d_boundary_location(
            unsteady,
            geometry,
            area_2d=requested_area,
            bc_line=requested_line,
        )


def test_ensure_location_rejects_duplicate_geometry_records(tmp_path):
    geometry = _write_geometry(tmp_path / "breakout.g02", duplicate=True)
    unsteady = _write_unsteady(tmp_path / "breakout.u02")

    with pytest.raises(ValueError, match="not exactly once"):
        RasUnsteady.ensure_2d_boundary_location(
            unsteady,
            geometry,
            area_2d="Breakout Area",
            bc_line="Breakout Inflow",
        )


def test_ensure_location_rejects_existing_name_on_other_area(tmp_path):
    geometry = _write_geometry(tmp_path / "breakout.g02")
    unsteady = _write_unsteady(tmp_path / "breakout.u02")
    text = unsteady.read_text(encoding="utf-8").replace(
        "Parent Outflow",
        "Breakout Inflow",
    )
    unsteady.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="already attached"):
        RasUnsteady.ensure_2d_boundary_location(
            unsteady,
            geometry,
            area_2d="Breakout Area",
            bc_line="Breakout Inflow",
        )


@pytest.mark.parametrize(
    "hours",
    [
        [1.0, 1.5, 2.0],
        [0.0, 1.0, 0.5],
        [0.0, 0.5, 1.25],
        [0.0, 0.001, 0.002],
    ],
)
def test_inline_hydrograph_rejects_invalid_time_axis(tmp_path, hours):
    geometry = _write_geometry(tmp_path / "breakout.g02")
    unsteady = _write_unsteady(tmp_path / "breakout.u02")
    RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="Breakout Area",
        bc_line="Breakout Inflow",
    )

    with pytest.raises(ValueError, match="Hydrograph"):
        RasUnsteady.set_boundary_inline_hydrograph(
            unsteady,
            pd.DataFrame({"hour": hours, "value": [1.0, 2.0, 3.0]}),
            area_2d="Breakout Area",
            bc_line="Breakout Inflow",
        )


def test_inline_hydrograph_rejects_mixed_selector_groups(tmp_path):
    unsteady = _write_unsteady(tmp_path / "breakout.u02")

    with pytest.raises(ValueError, match="not both"):
        RasUnsteady.set_boundary_inline_hydrograph(
            unsteady,
            pd.DataFrame({"hour": [0.0, 1.0], "value": [1.0, 2.0]}),
            river="River",
            reach="Reach",
            station="1",
            area_2d="Breakout Area",
            bc_line="Breakout Inflow",
        )


def test_real_bald_eagle_existing_2d_location_round_trips_read_only(tmp_path):
    fixture = Path(__file__).parents[1] / "example_projects" / "BaldEagleCrkMulti2D"
    source_geometry = fixture / "BaldEagleDamBrk.g09"
    source_unsteady = fixture / "BaldEagleDamBrk.u03"
    if not source_geometry.is_file() or not source_unsteady.is_file():
        pytest.skip("BaldEagleCrkMulti2D g09/u03 fixture is unavailable")
    geometry = Path(shutil.copy2(source_geometry, tmp_path / source_geometry.name))
    unsteady = Path(shutil.copy2(source_unsteady, tmp_path / source_unsteady.name))
    before = unsteady.read_bytes()

    result = RasUnsteady.ensure_2d_boundary_location(
        unsteady,
        geometry,
        area_2d="BaldEagleCr",
        bc_line="Upstream Inflow",
    )

    assert result["created"] is False
    assert result["geometry_match_count"] == 1
    assert unsteady.read_bytes() == before
