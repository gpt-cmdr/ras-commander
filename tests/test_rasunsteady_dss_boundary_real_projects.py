"""Real-project integration tests for DSS boundary inventory and mutation.

These tests extract official HEC-RAS example projects into pytest temporary
directories. They inspect and mutate only those extracted copies; they never
invoke HEC-RAS.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from ras_commander import RasExamples, RasUnsteady, init_ras_project

BALD_EAGLE_DSS_PARTS = {
    0: ("", "BALD EAGLE 40", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
    2: ("", "FISHING CREEK", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
    4: ("", "RESERVOIR LOCAL", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
    5: (
        "",
        "LOCAL DOWNSTREAM OF DAM",
        "FLOW",
        "01JAN1999",
        "15MIN",
        "RUN:PMF-EVENT",
    ),
    6: ("", "MARSH CREEK", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
    7: ("", "BEECH CREEK FLOW", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
    8: ("", "BALD EAGLE LOCAL", "FLOW", "01JAN1999", "15MIN", "RUN:PMF-EVENT"),
}

CHIPPEWA_DSS_PATH = "//LAKE PEPIN/FLOW/01JAN2019/1DAY/RUN:C02/"
MUNCIE_DSS_PATH = "//MUNCIE INFLOW/FLOW/01JAN1900/1HOUR/RUN:C02/"


def _extract_and_initialize(
    project_name: str,
    tmp_path: Path,
    suffix: str,
):
    """Extract one official project and initialize a separate RasPrj object."""
    try:
        project_path = RasExamples.extract_project(
            project_name,
            output_path=tmp_path,
            suffix=suffix,
        )
    except Exception as exc:
        pytest.skip(
            f"RasExamples project {project_name!r} is unavailable: "
            f"{type(exc).__name__}: {exc}"
        )

    project_path = Path(project_path)
    ras_object = init_ras_project(
        project_path,
        "7.0",
        ras_object="new",
        load_results_summary=False,
        hide_intro=True,
    )
    return project_path, ras_object


def _unsteady_path(ras_object, unsteady_number: str) -> Path:
    """Resolve one unsteady file through project metadata."""
    normalized = ras_object.unsteady_df["unsteady_number"].astype(str).str.zfill(2)
    matches = ras_object.unsteady_df.loc[normalized == unsteady_number]
    assert len(matches) == 1, (
        f"Expected one u{unsteady_number} metadata row, found {len(matches)}"
    )
    path = Path(matches.iloc[0]["full_path"])
    assert path.is_file()
    return path


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _boundary_blocks(raw: bytes) -> list[bytes]:
    """Return Boundary Location blocks without decoding or newline conversion."""
    starts = [
        match.start()
        for match in re.finditer(rb"(?m)^Boundary Location=", raw)
    ]
    return [
        raw[start : starts[index + 1] if index + 1 < len(starts) else len(raw)]
        for index, start in enumerate(starts)
    ]


def _assert_crlf_with_terminal_newline(raw: bytes) -> None:
    """Assert the serialization used by the selected official fixtures."""
    assert b"\r\n" in raw
    without_crlf = raw.replace(b"\r\n", b"")
    assert b"\r" not in without_crlf
    assert b"\n" not in without_crlf
    assert raw.endswith(b"\r\n")


def test_bald_eagle_real_dss_inventory_is_exact_and_read_only(
    tmp_path: Path,
) -> None:
    _, ras_object = _extract_and_initialize(
        "BaldEagleCrkMulti2D",
        tmp_path,
        "c02_real_inventory",
    )
    unsteady_file = _unsteady_path(ras_object, "07")
    before = unsteady_file.read_bytes()
    before_hash = _sha256(before)
    _assert_crlf_with_terminal_newline(before)

    result = RasUnsteady.get_dss_boundaries(
        unsteady_file,
        ras_object=ras_object,
    )

    assert result["boundary_index"].tolist() == [0, 2, 4, 5, 6, 7, 8]
    assert len(result) == len(BALD_EAGLE_DSS_PARTS)

    for boundary_index, expected_parts in BALD_EAGLE_DSS_PARTS.items():
        row = result.loc[result["boundary_index"] == boundary_index].iloc[0]
        actual_parts = tuple(row[f"dss_part_{part}"] for part in "abcdef")
        assert actual_parts == expected_parts

    upstream = result.loc[result["boundary_index"] == 0].iloc[0]
    assert upstream["river"] == "Bald Eagle Cr."
    assert upstream["reach"] == "Lock Haven"
    assert upstream["station"] == "137520"
    assert upstream["bc_type"] == "Flow Hydrograph"
    assert upstream["area_2d"] == ""
    assert upstream["bc_line_name"] == ""
    assert upstream["sa_2d_name"] == ""
    assert upstream["bc_line"] == ""
    assert result["area_2d"].equals(result["sa_2d_name"])
    assert result["bc_line_name"].equals(result["bc_line"])

    uniform = result.loc[
        result["bc_type"] == "Uniform Lateral Inflow Hydrograph"
    ].set_index("boundary_index")
    assert uniform.index.tolist() == [4, 5, 8]
    assert uniform["downstream_station"].to_dict() == {
        4: "82303",
        5: "67130",
        8: "1",
    }

    after = unsteady_file.read_bytes()
    assert _sha256(after) == before_hash
    assert after == before


def test_chippewa_real_exact_2d_mutation_preserves_other_blocks(
    tmp_path: Path,
) -> None:
    _, ras_object = _extract_and_initialize(
        "Chippewa_2D",
        tmp_path,
        "c02_real_exact_2d",
    )
    unsteady_file = _unsteady_path(ras_object, "04")
    before = unsteady_file.read_bytes()
    before_blocks = _boundary_blocks(before)
    _assert_crlf_with_terminal_newline(before)
    assert len(before_blocks) == 5
    assert b",Chippewa        ,                ,Lake Pepin" in before_blocks[1]
    assert b"Flow Hydrograph= 93 " in before_blocks[1]

    changed = RasUnsteady.set_boundary_dss_link(
        unsteady_file,
        None,
        None,
        None,
        r"inputs\c02.dss",
        CHIPPEWA_DSS_PATH,
        "1DAY",
        ras_object,
        sa_2d_name="Chippewa",
        bc_line="Lake Pepin",
        boundary_index=1,
        expected_bc_type="Flow Hydrograph",
    )

    assert changed is True
    after = unsteady_file.read_bytes()
    after_blocks = _boundary_blocks(after)
    _assert_crlf_with_terminal_newline(after)
    assert len(after_blocks) == len(before_blocks)

    for index in (0, 2, 3, 4):
        assert after_blocks[index] == before_blocks[index]

    target = after_blocks[1]
    assert b"Flow Hydrograph= 0 \r\n" in target
    assert b"   11800   12300   12400" not in target
    assert b"DSS File=.\\inputs\\c02.dss\r\n" in target
    assert f"DSS Path={CHIPPEWA_DSS_PATH}\r\n".encode() in target
    assert b"Use DSS=True\r\n" in target

    inventory = RasUnsteady.get_dss_boundaries(
        unsteady_file,
        ras_object=ras_object,
    )
    selected = inventory.loc[inventory["boundary_index"] == 1]
    assert len(selected) == 1
    row = selected.iloc[0]
    assert row["area_2d"] == "Chippewa"
    assert row["bc_line_name"] == "Lake Pepin"
    assert row["sa_2d_name"] == "Chippewa"
    assert row["bc_line"] == "Lake Pepin"
    assert row["bc_type"] == "Flow Hydrograph"
    assert tuple(row[f"dss_part_{part}"] for part in "abcdef") == (
        "",
        "LAKE PEPIN",
        "FLOW",
        "01JAN2019",
        "1DAY",
        "RUN:C02",
    )


def test_chippewa_real_selection_guards_are_fail_closed(
    tmp_path: Path,
) -> None:
    _, ras_object = _extract_and_initialize(
        "Chippewa_2D",
        tmp_path,
        "c02_real_guards",
    )
    unsteady_file = _unsteady_path(ras_object, "04")
    before = unsteady_file.read_bytes()
    before_hash = _sha256(before)
    _assert_crlf_with_terminal_newline(before)

    common_args = (
        unsteady_file,
        None,
        None,
        None,
        r"inputs\c02.dss",
        CHIPPEWA_DSS_PATH,
        "1DAY",
        ras_object,
    )

    with pytest.raises(ValueError, match="ambiguous"):
        RasUnsteady.set_boundary_dss_link(
            *common_args,
            sa_2d_name="Chippewa",
        )
    assert _sha256(unsteady_file.read_bytes()) == before_hash

    with pytest.raises(ValueError, match="does not match"):
        RasUnsteady.set_boundary_dss_link(
            *common_args,
            sa_2d_name="Chippewa",
            bc_line="Lake Pepin",
            boundary_index=2,
        )
    assert _sha256(unsteady_file.read_bytes()) == before_hash

    with pytest.raises(ValueError, match="not the expected"):
        RasUnsteady.set_boundary_dss_link(
            *common_args,
            sa_2d_name="Chippewa",
            bc_line="LD4",
            boundary_index=2,
            expected_bc_type="Flow Hydrograph",
        )

    after = unsteady_file.read_bytes()
    assert _sha256(after) == before_hash
    assert after == before


def test_muncie_real_legacy_positional_1d_mutation_is_compatible(
    tmp_path: Path,
) -> None:
    _, ras_object = _extract_and_initialize(
        "Muncie",
        tmp_path,
        "c02_real_legacy_1d",
    )
    unsteady_file = _unsteady_path(ras_object, "01")
    before = unsteady_file.read_bytes()
    before_blocks = _boundary_blocks(before)
    _assert_crlf_with_terminal_newline(before)
    assert len(before_blocks) == 2
    assert b"Boundary Location=White           ,Muncie" in before_blocks[0]
    assert b"Flow Hydrograph= 65 " in before_blocks[0]

    changed = RasUnsteady.set_boundary_dss_link(
        unsteady_file,
        "White",
        "Muncie",
        "15696.24",
        "forcing.dss",
        MUNCIE_DSS_PATH,
        "1HOUR",
        ras_object,
        expected_bc_type="Flow Hydrograph",
    )

    assert changed is True
    after = unsteady_file.read_bytes()
    after_blocks = _boundary_blocks(after)
    _assert_crlf_with_terminal_newline(after)
    assert len(after_blocks) == len(before_blocks)
    assert after_blocks[1] == before_blocks[1]

    target = after_blocks[0]
    assert b"Flow Hydrograph= 0 \r\n" in target
    assert b"DSS File=.\\forcing.dss\r\n" in target
    assert f"DSS Path={MUNCIE_DSS_PATH}\r\n".encode() in target
    assert b"Use DSS=True\r\n" in target
    assert b"Flow Hydrograph= 65 " not in target

    inventory = RasUnsteady.get_dss_boundaries(
        unsteady_file,
        ras_object=ras_object,
    )
    selected = inventory.loc[inventory["boundary_index"] == 0]
    assert len(selected) == 1
    row = selected.iloc[0]
    assert (row["river"], row["reach"], row["station"]) == (
        "White",
        "Muncie",
        "15696.24",
    )
    assert tuple(row[f"dss_part_{part}"] for part in "abcdef") == (
        "",
        "MUNCIE INFLOW",
        "FLOW",
        "01JAN1900",
        "1HOUR",
        "RUN:C02",
    )
