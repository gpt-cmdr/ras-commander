"""Tests for RasUnsteady.delete_boundary().

The tests use real HEC-RAS example projects and verify deletion at the byte
level so non-target boundary blocks remain untouched.
"""

from pathlib import Path

import pytest

from ras_commander import RasExamples, RasUnsteady, init_ras_project


def _extract_project(project_name: str, tmp_path: Path, suffix: str) -> Path:
    try:
        project = RasExamples.extract_project(
            project_name,
            output_path=tmp_path,
            suffix=suffix,
        )
    except Exception as exc:
        pytest.skip(f"{project_name} example project not available: {exc}")
    if isinstance(project, list):
        project = project[0]
    return Path(project)


def _boundary_blocks(raw: bytes):
    lines = raw.splitlines(keepends=True)
    starts = [
        idx for idx, line in enumerate(lines)
        if line.startswith(b"Boundary Location=")
    ]
    blocks = []
    offset_by_line = []
    offset = 0
    for line in lines:
        offset_by_line.append(offset)
        offset += len(line)

    for boundary_index, start_line in enumerate(starts):
        end_line = starts[boundary_index + 1] if boundary_index + 1 < len(starts) else len(lines)
        start_byte = offset_by_line[start_line]
        end_byte = offset_by_line[end_line] if end_line < len(lines) else len(raw)
        block = b"".join(lines[start_line:end_line])
        first_line = lines[start_line].decode("utf-8", errors="ignore")
        loc_value = first_line.split("=", 1)[1].rstrip("\r\n")
        parts = [part.strip() for part in loc_value.split(",")]
        blocks.append({
            "boundary_index": boundary_index,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "block": block,
            "loc_value": loc_value,
            "parts": parts,
        })
    return blocks


def _first_lateral_block(unsteady_file: Path):
    raw = unsteady_file.read_bytes()
    for block in _boundary_blocks(raw):
        if b"Lateral Inflow Hydrograph=" in block["block"]:
            return raw, block
    pytest.skip(f"No Lateral Inflow Hydrograph block in {unsteady_file.name}")


def test_delete_lateral_inflow_removes_exact_block_and_preserves_other_bcs(tmp_path):
    project = _extract_project("Dam Breaching", tmp_path, "delete_boundary")
    unsteady_file = project / "BaldEagleDamBrk.u01"
    if not unsteady_file.exists():
        pytest.skip("BaldEagleDamBrk.u01 not found")

    before_raw, target = _first_lateral_block(unsteady_file)
    all_blocks = _boundary_blocks(before_raw)
    target_block = target["block"]
    other_blocks = [
        block["block"] for block in all_blocks
        if block["boundary_index"] != target["boundary_index"]
    ]
    river, reach, station = target["parts"][:3]

    river_matches = [
        block for block in all_blocks
        if len(block["parts"]) >= 1 and block["parts"][0] == river
    ]
    if len(river_matches) > 1:
        with pytest.raises(ValueError, match="ambiguous"):
            RasUnsteady.delete_boundary(unsteady_file, river=river)

    result = RasUnsteady.delete_boundary(
        unsteady_file,
        river=river,
        boundary_index=target["boundary_index"],
    )

    after_raw = unsteady_file.read_bytes()
    expected_after = before_raw[:target["start_byte"]] + before_raw[target["end_byte"]:]

    assert result["deleted"] is True
    assert result["bc_type"] == "Lateral Inflow Hydrograph"
    assert result["name"] == f"{river}/{reach}/{station}"
    assert result["lines_removed"] == len(target_block.splitlines())
    assert result["required_boundary"] is False
    assert Path(result["backup_path"]).read_bytes() == before_raw
    assert after_raw == expected_after
    assert target_block not in after_raw
    for block in other_blocks:
        assert block in after_raw


def test_required_external_boundary_requires_force_and_does_not_write_backup(tmp_path):
    project = _extract_project("Muncie", tmp_path, "delete_boundary_guard")
    unsteady_file = project / "Muncie.u01"
    if not unsteady_file.exists():
        pytest.skip("Muncie.u01 not found")

    before_raw = unsteady_file.read_bytes()
    backup_path = Path(str(unsteady_file) + ".bak")

    with pytest.raises(ValueError, match="force=True"):
        RasUnsteady.delete_boundary(unsteady_file, boundary_index=0)

    assert unsteady_file.read_bytes() == before_raw
    assert not backup_path.exists()


def test_force_delete_final_required_boundary_preserves_global_trailer(tmp_path):
    project = _extract_project("Muncie", tmp_path, "delete_boundary_force")
    unsteady_file = project / "Muncie.u01"
    if not unsteady_file.exists():
        pytest.skip("Muncie.u01 not found")

    before_raw = unsteady_file.read_bytes()
    assert b"Met Point Raster Parameters=" in before_raw

    result = RasUnsteady.delete_boundary(
        unsteady_file,
        boundary_index=1,
        force=True,
    )

    after_raw = unsteady_file.read_bytes()
    assert result["bc_type"] == "Normal Depth"
    assert result["required_boundary"] is True
    assert b"Friction Slope=0.00064,0" not in after_raw
    assert b"Met Point Raster Parameters=" in after_raw
    assert b"Precipitation Mode=Disable" in after_raw
    assert Path(result["backup_path"]).read_bytes() == before_raw


def test_delete_boundary_refreshes_boundaries_df(tmp_path):
    project = _extract_project("Dam Breaching", tmp_path, "delete_boundary_refresh")
    prj_files = [p for p in project.glob("*.prj") if not p.name.endswith(".rasprj.json")]
    if not prj_files:
        pytest.skip("No .prj file found")

    try:
        ras_obj = init_ras_project(project, "7.0")
    except Exception as exc:
        pytest.skip(f"Could not initialize Dam Breaching project: {exc}")

    unsteady_file = project / "BaldEagleDamBrk.u01"
    _, target = _first_lateral_block(unsteady_file)
    before_count = len(ras_obj.boundaries_df)
    before_u01_lateral_count = (
        (ras_obj.boundaries_df["unsteady_number"] == "01")
        & (ras_obj.boundaries_df["bc_type"] == "Lateral Inflow Hydrograph")
    ).sum()

    result = RasUnsteady.delete_boundary(
        unsteady_file,
        boundary_index=target["boundary_index"],
        ras_object=ras_obj,
    )

    assert result["boundaries_df_refreshed"] is True
    assert len(ras_obj.boundaries_df) == before_count - 1
    after_u01_lateral_count = (
        (ras_obj.boundaries_df["unsteady_number"] == "01")
        & (ras_obj.boundaries_df["bc_type"] == "Lateral Inflow Hydrograph")
    ).sum()
    assert after_u01_lateral_count == before_u01_lateral_count - 1
