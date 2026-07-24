"""Tests for isolated HMS-to-RAS scenario workspaces."""

from datetime import datetime
from pathlib import Path

import pytest

from ras_commander import RasBoundaryLink, RasScenario


RAS_EXE = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe")


def _write_project(folder: Path) -> Path:
    folder.mkdir()
    (folder / "Example.prj").write_text(
        """Proj Title=Example
Current Plan=p01
Geom File=g01
Unsteady File=u01
Plan File=p01
""",
        encoding="utf-8",
    )
    (folder / "Example.p01").write_text(
        """Plan Title=Baseline
Program Version=6.60
Short Identifier=Baseline
Simulation Date=01JAN2020,0000,02JAN2020,0000
Geom File=g01
Flow File=u01
Unsteady Flow
""",
        encoding="utf-8",
    )
    (folder / "Example.g01").write_text(
        "Geom Title=Geometry\nProgram Version=6.60\n",
        encoding="utf-8",
    )
    (folder / "Example.u01").write_text(
        """Flow Title=Baseline
Program Version=6.60
Boundary Location=River           ,Reach           ,1000    ,        ,                ,                ,                ,                                ,
Boundary Name=Tributary
Interval=1HOUR
Lateral Inflow Hydrograph= 0
DSS File=baseline.dss
DSS Path=//TRIBUTARY/FLOW/DATE/1HOUR/RUN:BASE/
Use DSS=True
Boundary Location=                ,                ,        ,        ,                ,Area2D          ,                ,Junction                        ,
Boundary Name=Junction
Interval=1HOUR
Flow Hydrograph= 0
DSS File=baseline.dss
DSS Path=//JUNCTION/FLOW/DATE/1HOUR/RUN:BASE/
Use DSS=True
Met Point Raster Parameters=,,,,
""",
        encoding="utf-8",
    )
    return folder / "Example.prj"


@pytest.mark.skipif(not RAS_EXE.is_file(), reason="HEC-RAS 6.6 not installed")
def test_prepare_workspace_clones_plan_and_links_boundaries(tmp_path):
    source_project = _write_project(tmp_path / "source")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"not-a-real-dss")
    original = {
        path.name: path.read_bytes()
        for path in source_project.parent.iterdir()
        if path.is_file()
    }
    links = [
        RasBoundaryLink(
            mapping_id="tributary",
            dss_path="//TRIBUTARY/FLOW/01JAN2020-02JAN2020/5MIN/RUN:FF_TEST/",
            expected_bc_type="Lateral Inflow Hydrograph",
            river="River",
            reach="Reach",
            station="1000",
        ),
        RasBoundaryLink(
            mapping_id="junction",
            dss_path="//JUNCTION/FLOW/01JAN2020-02JAN2020/5MIN/RUN:FF_TEST/",
            expected_bc_type="Flow Hydrograph",
            sa_2d_name="Area2D",
            bc_line="Junction",
        ),
    ]

    prepared = RasScenario.prepare_workspace(
        source_project,
        tmp_path / "workspace",
        "scenario-001",
        "01",
        hydrology,
        links,
        datetime(2020, 1, 1),
        datetime(2020, 1, 2),
        ras_exe_path=RAS_EXE,
    )

    plan_text = prepared.plan_file.read_text(encoding="utf-8")
    unsteady_text = prepared.unsteady_file.read_text(encoding="utf-8")
    assert prepared.plan_number == "02"
    assert prepared.unsteady_number == "02"
    assert "Flow File=u02" in plan_text
    assert "Simulation Date=01JAN2020,0000,02JAN2020,0000" in plan_text
    assert unsteady_text.count("DSS File=hydrology\\hms-output.dss") == 2
    assert all(f"DSS Path={link.dss_path}" in unsteady_text for link in links)
    assert {
        path.name: path.read_bytes()
        for path in source_project.parent.iterdir()
        if path.is_file()
    } == original


def test_boundary_link_rejects_mixed_selector_groups():
    with pytest.raises(ValueError, match="cannot mix"):
        RasBoundaryLink(
            mapping_id="bad",
            dss_path="//A/FLOW/DATE/5MIN/RUN/",
            expected_bc_type="Flow Hydrograph",
            river="River",
            sa_2d_name="Area2D",
        )


def test_prepare_workspace_is_non_destructive_by_default(tmp_path):
    source_project = _write_project(tmp_path / "source")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"dss")
    destination = tmp_path / "workspace"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="Workspace already exists"):
        RasScenario.prepare_workspace(
            source_project,
            destination,
            "scenario",
            "01",
            hydrology,
            [
                RasBoundaryLink(
                    mapping_id="mapping",
                    dss_path="//A/FLOW/DATE/5MIN/RUN/",
                    expected_bc_type="Lateral Inflow Hydrograph",
                    river="River",
                    reach="Reach",
                    station="1000",
                )
            ],
            datetime(2020, 1, 1),
            datetime(2020, 1, 2),
            ras_exe_path=RAS_EXE,
        )
