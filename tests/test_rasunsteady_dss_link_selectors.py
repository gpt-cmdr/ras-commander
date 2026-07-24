"""Exact boundary selector coverage for HMS-to-RAS DSS links."""

from pathlib import Path

import pytest

from ras_commander import RasUnsteady


def _write_unsteady(path: Path) -> Path:
    path.write_text(
        """Flow Title=Selector Test
Boundary Location=OuachitaRv      ,10.6            ,91744   ,        ,                ,                ,                ,                                ,
Boundary Name=S_OuachiRi_2
Interval=1HOUR
Lateral Inflow Hydrograph= 0
DSS File=old.dss
DSS Path=//OLD/FLOW/DATE/1HOUR/RUN:OLD/
Use DSS=True
Boundary Location=                ,                ,        ,        ,                ,OuaRiW2         ,                ,J_ByDeLout_2                    ,
Boundary Name=J_ByDeLout_2
Interval=1HOUR
Flow Hydrograph= 0
DSS File=old.dss
DSS Path=//OLD_JUNCTION/FLOW/DATE/1HOUR/RUN:OLD/
Use DSS=True
Boundary Location=                ,                ,        ,        ,                ,OuaRiW2         ,                ,Other                           ,
Boundary Name=Other
Flow Hydrograph= 0
DSS File=other.dss
DSS Path=//OTHER/FLOW/DATE/1HOUR/RUN:OLD/
Use DSS=True
Met Point Raster Parameters=,,,,
""",
        encoding="utf-8",
    )
    return path


def test_set_boundary_dss_link_selects_2d_bc_line_exactly(tmp_path):
    unsteady = _write_unsteady(tmp_path / "project.u01")
    dss_path = "//J_BYDELOUT_2/FLOW/18SEP2019-20SEP2019/5MIN/RUN:FF_TEST/"

    changed = RasUnsteady.set_boundary_dss_link(
        unsteady,
        river=None,
        reach=None,
        station=None,
        dss_file=r".\hydrology\scenario.dss",
        dss_path=dss_path,
        interval="5MIN",
        sa_2d_name="OuaRiW2",
        bc_line="J_ByDeLout_2",
        expected_bc_type="Flow Hydrograph",
    )

    content = unsteady.read_text(encoding="utf-8")
    assert changed is True
    assert f"DSS Path={dss_path}" in content
    assert r"DSS File=.\hydrology\scenario.dss" in content
    assert "DSS Path=//OTHER/FLOW/DATE/1HOUR/RUN:OLD/" in content


def test_set_boundary_dss_link_preserves_legacy_1d_selector(tmp_path):
    unsteady = _write_unsteady(tmp_path / "project.u01")

    changed = RasUnsteady.set_boundary_dss_link(
        unsteady,
        river="OuachitaRv",
        reach="10.6",
        station="91744",
        dss_file="scenario.dss",
        dss_path="//S_OUACHIRI_2/FLOW/DATE/5MIN/RUN:FF_TEST/",
        expected_bc_type="Lateral Inflow Hydrograph",
    )

    assert changed is True
    assert "DSS Path=//S_OUACHIRI_2/FLOW/DATE/5MIN/RUN:FF_TEST/" in (
        unsteady.read_text(encoding="utf-8")
    )


def test_set_boundary_dss_link_rejects_ambiguous_partial_2d_selector(tmp_path):
    unsteady = _write_unsteady(tmp_path / "project.u01")

    with pytest.raises(ValueError, match="ambiguous"):
        RasUnsteady.set_boundary_dss_link(
            unsteady,
            river=None,
            reach=None,
            station=None,
            dss_file="scenario.dss",
            dss_path="//J/FLOW/DATE/5MIN/RUN/",
            sa_2d_name="OuaRiW2",
        )


def test_set_boundary_dss_link_checks_boundary_type_before_write(tmp_path):
    unsteady = _write_unsteady(tmp_path / "project.u01")
    original = unsteady.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="expected 'Flow Hydrograph'"):
        RasUnsteady.set_boundary_dss_link(
            unsteady,
            river="OuachitaRv",
            reach="10.6",
            station="91744",
            dss_file="scenario.dss",
            dss_path="//S/FLOW/DATE/5MIN/RUN/",
            expected_bc_type="Flow Hydrograph",
        )

    assert unsteady.read_text(encoding="utf-8") == original


def test_get_dss_boundaries_retains_exact_2d_selectors_and_name(tmp_path):
    unsteady = _write_unsteady(tmp_path / "project.u01")

    boundaries = RasUnsteady.get_dss_boundaries(unsteady)
    junction = boundaries[boundaries["bc_line"] == "J_ByDeLout_2"].iloc[0]

    assert junction["dss_part_a"] == ""
    assert junction["dss_part_b"] == "OLD_JUNCTION"
    assert junction["dss_part_c"] == "FLOW"
    assert junction["sa_2d_name"] == "OuaRiW2"
    assert junction["bc_line"] == "J_ByDeLout_2"
    assert junction["boundary_name"] == "J_ByDeLout_2"
    assert junction["bc_type"] == "Flow Hydrograph"
    assert junction["boundary_index"] == 1
