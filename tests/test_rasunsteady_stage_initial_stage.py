"""Byte-preserving exact 2D stage-initialization flag edits."""
from pathlib import Path

import pytest
from ras_commander import RasUnsteady

LOCATION = "Boundary Location=,,,,,Area,,Outlet,\n"
STAGE = LOCATION + "Interval=1HOUR\nStage Hydrograph=2\n  100.00  101.00\nUse DSS=False\n"
OTHER = "Boundary Location=,,,,,Area,,Inlet,\nFlow Hydrograph=2\n  100.00  100.00\nUse DSS=False\n"

@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("existing", [None, "0", "1"])
@pytest.mark.parametrize("enabled", [False, True])
def test_exact_flag_change_preserves_ordinates_siblings_and_line_endings(tmp_path, newline, existing, enabled):
    body = STAGE
    if existing is not None:
        body = body.replace("Use DSS=", "Stage Hydrograph Use Initial Stage=" + existing + "\nUse DSS=")
    raw = ("Flow Title=caf\xe9\n" + OTHER + body + "Met BC=Precipitation|None\n").replace("\n", newline).encode("latin-1")
    path = tmp_path / "child.u08"
    path.write_bytes(raw)
    result = RasUnsteady.set_stage_hydrograph_initial_stage(path, enabled, area_2d="Area", bc_line="Outlet")
    flag = b"Stage Hydrograph Use Initial Stage=" + str(int(enabled)).encode() + newline.encode()
    if existing is None:
        expected = raw.replace(("Use DSS=False" + newline + "Met BC=").encode(), flag + ("Use DSS=False" + newline + "Met BC=").encode())
    else:
        expected = raw.replace(("Stage Hydrograph Use Initial Stage=" + existing + newline).encode(), flag)
    assert path.read_bytes() == expected
    assert result["use_initial_stage"] is enabled
    assert result["previous_use_initial_stage"] == (None if existing is None else existing == "1")

@pytest.mark.parametrize("body,selector", [(OTHER, "Inlet"), (STAGE + STAGE, "Outlet"), (STAGE, "Missing"), (STAGE.replace("Use DSS=", "Stage Hydrograph Use Initial Stage=2\nUse DSS="), "Outlet")])
def test_invalid_or_ambiguous_boundary_does_not_write(tmp_path, body, selector):
    path = tmp_path / "child.u08"
    path.write_text(body)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.set_stage_hydrograph_initial_stage(path, False, area_2d="Area", bc_line=selector)
    assert path.read_bytes() == original

def test_type_and_exact_selector_validation(tmp_path):
    path = tmp_path / "child.u08"
    path.write_text(STAGE)
    with pytest.raises(TypeError):
        RasUnsteady.set_stage_hydrograph_initial_stage(str(path), 0, area_2d="Area", bc_line="Outlet")
    with pytest.raises(ValueError):
        RasUnsteady.set_stage_hydrograph_initial_stage(path, False, area_2d="Area", bc_line="Out,let")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("count", [2, 6000])
def test_inline_stage_dss_flag_stays_before_global_meteorology(tmp_path, newline, count):
    import pandas as pd

    path = tmp_path / "child.u08"
    trailer = "Met Point Raster Parameters=,,,,\nMet BC=Precipitation|Mode=None\nUse DSS=True\n"
    before = "Flow Title=stage\n" + OTHER + LOCATION + "Friction Slope=0.001\n" + trailer
    path.write_bytes(before.replace("\n", newline).encode())
    series = pd.DataFrame({"hour": [i / 12 for i in range(count)], "value": [100.25] * count})
    assert RasUnsteady.set_boundary_inline_hydrograph(path, series, bc_type="Stage Hydrograph", area_2d="Area", bc_line="Outlet")
    raw = path.read_bytes()
    assert raw.decode().replace("\r\n", "\n").endswith(trailer)
    data = raw.decode().splitlines(keepends=True)
    block = RasUnsteady._find_boundary_blocks(data)[-1]
    body = "".join(data[block['start_idx']:block['end_idx']])
    assert "Use DSS=False" in body
    assert "Met BC=" not in body
    # A second, longer write must still update the selected flag and preserve
    # the global Use DSS=True value beyond the boundary block.
    assert RasUnsteady.set_boundary_inline_hydrograph(path, series, bc_type="Stage Hydrograph", area_2d="Area", bc_line="Outlet")
    assert path.read_bytes().decode().replace("\r\n", "\n").endswith(trailer)
