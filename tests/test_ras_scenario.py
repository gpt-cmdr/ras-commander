"""Tests for isolated HMS-to-RAS scenario workspaces."""

import importlib
import stat
import threading
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import (
    RasBoundaryLink,
    RasScenario,
    RasScenarioWorkspace,
)


RAS_EXE = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe")


def _write_result_hdf(
    path: Path,
    *,
    completed: bool = True,
    start: str = "18Sep2019 13:00:00.000",
    end: str = "22Sep2019 13:00:00.000",
) -> None:
    with h5py.File(path, "w") as hdf_file:
        event_conditions = hdf_file.create_group("Event Conditions")
        event_conditions.attrs["Completed Successfully"] = (
            b"True" if completed else b"False"
        )
        timestamps = hdf_file.create_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/" "Unsteady Time Series"
        )
        timestamps.create_dataset(
            "Time Date Stamp (ms)",
            data=np.asarray([start, end], dtype="S24"),
        )


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
        """Geom Title=Geometry
Program Version=6.60
River Reach=River           ,Reach
Type RM Length L Ch R = 1 ,1000,0,0,0
Storage Area=Area2D,0,0
Storage Area Is2D=-1
BC Line Name=Junction
""",
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
Boundary Location=                ,                ,        ,        ,                ,SA_NotInGeometry,                ,                                ,
Boundary Name=Missing Storage
Interval=1HOUR
Flow Hydrograph= 0
DSS File=baseline.dss
DSS Path=//MISSING/FLOW/DATE/1HOUR/RUN:BASE/
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
            dss_path="//TRIBUTARY/FLOW//5MIN/RUN:FF_TEST/",
            expected_bc_type="Lateral Inflow Hydrograph",
            river="River",
            reach="Reach",
            station="1000",
        ),
        RasBoundaryLink(
            mapping_id="junction",
            dss_path="//JUNCTION/FLOW//5MIN/RUN:FF_TEST/",
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
    assert "Current Plan=p02" in prepared.project_file.read_text(encoding="utf-8")
    assert "Flow File=u02" in plan_text
    assert "Simulation Date=01JAN2020,0000,02JAN2020,0000" in plan_text
    assert unsteady_text.count("DSS File=.\\hydrology\\hms-output.dss") == 2
    assert (
        "DSS Path=//TRIBUTARY/FLOW/01JAN2020-02JAN2020/5MIN/" "RUN:FF_TEST/"
    ) in unsteady_text
    assert (
        "DSS Path=//JUNCTION/FLOW/01JAN2020-02JAN2020/5MIN/" "RUN:FF_TEST/"
    ) in unsteady_text
    assert "//MISSING/FLOW/DATE/1HOUR/RUN:BASE/" not in unsteady_text
    assert prepared.inactive_inherited_boundaries == (
        {
            "mapping_id": "inherited-boundary-002",
            "boundary_index": 2,
            "boundary_name": "Missing Storage",
            "bc_type": "Flow Hydrograph",
            "dss_file": "baseline.dss",
            "dss_path": "//MISSING/FLOW/DATE/1HOUR/RUN:BASE/",
            "river": None,
            "reach": None,
            "station": None,
            "sa_2d_name": "SA_NotInGeometry",
            "bc_line": None,
            "geometry_crosswalk": False,
            "disposition": "removed_from_clone_inactive_in_active_geometry",
            "lines_removed": 7,
        },
    )
    assert {
        path.name: path.read_bytes()
        for path in source_project.parent.iterdir()
        if path.is_file()
    } == original


@pytest.mark.skipif(not RAS_EXE.is_file(), reason="HEC-RAS 6.6 not installed")
def test_prepare_workspace_stages_and_validates_forcing_excess(tmp_path):
    source_project = _write_project(tmp_path / "source")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"hydrology")
    excess = tmp_path / "ras-excess.dss"
    excess.write_bytes(b"excess")
    link = RasBoundaryLink(
        mapping_id="tributary",
        dss_path="//TRIBUTARY/FLOW//5MIN/RUN:FF_TEST/",
        expected_bc_type="Lateral Inflow Hydrograph",
        river="River",
        reach="Reach",
        station="1000",
    )

    prepared = RasScenario.prepare_workspace(
        source_project,
        tmp_path / "workspace",
        "scenario-001",
        "01",
        hydrology,
        [link],
        datetime(2020, 1, 1),
        datetime(2020, 1, 2),
        ras_exe_path=RAS_EXE,
        forcing_excess_dss=excess,
        forcing_excess_pathname="/SHG/BASIN/PRECIPITATION///EXCESS/",
        forcing_excess_interpolation="Nearest",
    )

    assert prepared.forcing_excess_file is not None
    assert prepared.forcing_excess_file.read_bytes() == b"excess"
    checks = RasScenario.validate_workspace(prepared, [link])
    evidence = RasScenario.inspect_workspace_evidence(prepared, [link])
    assert checks["forcing_excess_link_matches"] is True
    assert checks["one_newline_convention"] is True
    assert evidence["forcing_excess"]["dss_pathname"] == (
        "/SHG/BASIN/PRECIPITATION///EXCESS/"
    )
    assert evidence["forcing_excess"]["interpolation"] == "Nearest"
    assert evidence["geometry_crosswalk"] == {"tributary": True}


@pytest.mark.skipif(not RAS_EXE.is_file(), reason="HEC-RAS 6.6 not installed")
def test_validate_workspace_rejects_inactive_geometry_boundary(tmp_path):
    source_project = _write_project(tmp_path / "source")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"not-a-real-dss")

    with pytest.raises(
        ValueError,
        match="all_boundaries_exist_in_active_geometry",
    ) as error:
        RasScenario.prepare_workspace(
            source_project,
            tmp_path / "workspace",
            "scenario-001",
            "01",
            hydrology,
            [
                RasBoundaryLink(
                    mapping_id="missing-storage",
                    dss_path="//MISSING/FLOW//5MIN/RUN:FF_TEST/",
                    expected_bc_type="Flow Hydrograph",
                    sa_2d_name="SA_NotInGeometry",
                )
            ],
            datetime(2020, 1, 1),
            datetime(2020, 1, 2),
            ras_exe_path=RAS_EXE,
        )
    assert "inactive mappings: missing-storage" in str(error.value)


def test_boundary_link_rejects_mixed_selector_groups():
    with pytest.raises(ValueError, match="cannot mix"):
        RasBoundaryLink(
            mapping_id="bad",
            dss_path="//A/FLOW/DATE/5MIN/RUN/",
            expected_bc_type="Flow Hydrograph",
            river="River",
            sa_2d_name="Area2D",
        )


def test_format_dss_pathname_for_window_materializes_blank_d_part():
    pathname = RasScenario.format_dss_pathname_for_window(
        "//OUTLET/FLOW//5Minute/RUN:TEST/",
        datetime(2019, 9, 18, 13),
        datetime(2019, 9, 22, 13),
    )

    assert pathname == ("//OUTLET/FLOW/18SEP2019-22SEP2019/5Minute/RUN:TEST/")


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


@pytest.mark.skipif(not RAS_EXE.is_file(), reason="HEC-RAS 6.6 not installed")
def test_validate_workspace_rejects_bare_relative_dss_reference(tmp_path):
    source_project = _write_project(tmp_path / "source")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"not-a-real-dss")
    links = [
        RasBoundaryLink(
            mapping_id="tributary",
            dss_path="//TRIBUTARY/FLOW/DATE/5MIN/RUN:FF_TEST/",
            expected_bc_type="Lateral Inflow Hydrograph",
            river="River",
            reach="Reach",
            station="1000",
        ),
        RasBoundaryLink(
            mapping_id="junction",
            dss_path="//JUNCTION/FLOW/DATE/5MIN/RUN:FF_TEST/",
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
    text = prepared.unsteady_file.read_text(encoding="utf-8")
    prepared.unsteady_file.write_text(
        text.replace(
            r"DSS File=.\hydrology\hms-output.dss",
            r"DSS File=hydrology\hms-output.dss",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="all_dss_file_references_resolvable",
    ):
        RasScenario.validate_workspace(prepared, links)


@pytest.mark.skipif(not RAS_EXE.is_file(), reason="HEC-RAS 6.6 not installed")
def test_prepare_workspace_preserves_linked_asset_sibling_layout(tmp_path):
    source_package = tmp_path / "source-package"
    source_package.mkdir()
    source_project = _write_project(source_package / "project")
    terrain = source_package / "Terrain"
    terrain.mkdir()
    (terrain / "terrain.hdf").write_bytes(b"terrain")
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"dss")

    prepared = RasScenario.prepare_workspace(
        source_project,
        tmp_path / "attempt" / "project",
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
        linked_asset_directories=[terrain],
    )

    assert prepared.project_folder == tmp_path / "attempt" / "project"
    assert (
        prepared.project_folder.parent / "Terrain" / "terrain.hdf"
    ).read_bytes() == b"terrain"
    assert (terrain / "terrain.hdf").read_bytes() == b"terrain"


def test_execute_cancels_plan_after_timeout(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = RasScenarioWorkspace(
        scenario_id="scenario",
        source_project=project / "source.prj",
        project_folder=project,
        project_file=project / "Example.prj",
        plan_number="02",
        plan_file=project / "Example.p02",
        unsteady_number="02",
        unsteady_file=project / "Example.u02",
        hydrology_source=tmp_path / "source.dss",
        hydrology_file=project / "hydrology.dss",
        result_hdf=project / "Example.p02.hdf",
        boundary_mapping_ids=("mapping",),
    )
    project_object = object()
    released = threading.Event()
    calls = {}
    scenario_module = importlib.import_module("ras_commander.RasScenario")

    monkeypatch.setattr(
        scenario_module,
        "init_ras_project",
        lambda *args, **kwargs: project_object,
    )

    def compute_plan(plan_number, **kwargs):
        calls["compute"] = (plan_number, kwargs)
        released.wait(timeout=1)
        return False

    def cancel_plan(plan_number, **kwargs):
        calls["cancel"] = (plan_number, kwargs)
        released.set()
        return True

    monkeypatch.setattr(
        scenario_module.RasCmdr,
        "compute_plan",
        compute_plan,
    )
    monkeypatch.setattr(
        scenario_module.RasCmdr,
        "cancel_plan",
        cancel_plan,
    )

    with pytest.raises(TimeoutError, match="cancellation requested=True"):
        RasScenario.execute(
            workspace,
            ras_exe_path=RAS_EXE,
            timeout=0.01,
            num_cores=4,
        )

    assert calls["compute"] == (
        "02",
        {
            "ras_object": project_object,
            "num_cores": 4,
            "verify": True,
        },
    )
    assert calls["cancel"] == (
        "02",
        {"ras_object": project_object},
    )


def test_execute_requires_hdf_completion_and_matching_time_axis(
    monkeypatch,
    tmp_path,
):
    project = tmp_path / "project"
    project.mkdir()
    result_hdf = project / "Example.p02.hdf"
    _write_result_hdf(result_hdf)
    workspace = RasScenarioWorkspace(
        scenario_id="scenario",
        source_project=project / "source.prj",
        project_folder=project,
        project_file=project / "Example.prj",
        plan_number="02",
        plan_file=project / "Example.p02",
        unsteady_number="02",
        unsteady_file=project / "Example.u02",
        hydrology_source=tmp_path / "source.dss",
        hydrology_file=project / "hydrology.dss",
        result_hdf=result_hdf,
        boundary_mapping_ids=("mapping",),
        simulation_start="2019-09-18T13:00:00-05:00",
        simulation_end="2019-09-22T13:00:00-05:00",
    )
    scenario_module = importlib.import_module("ras_commander.RasScenario")
    monkeypatch.setattr(
        scenario_module,
        "init_ras_project",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        scenario_module.RasCmdr,
        "compute_plan",
        lambda *args, **kwargs: True,
    )

    artifact = RasScenario.execute(
        workspace,
        ras_exe_path=RAS_EXE,
    )

    assert artifact.status == "succeeded"
    assert artifact.compute_returned_successfully
    assert artifact.hdf_completed_successfully
    assert artifact.time_window_matches
    assert artifact.output_start == "2019-09-18T13:00:00"
    assert artifact.output_end == "2019-09-22T13:00:00"
    assert artifact.hdf_inspection_error is None


def test_execute_fails_when_hdf_time_axis_does_not_match(
    monkeypatch,
    tmp_path,
):
    project = tmp_path / "project"
    project.mkdir()
    result_hdf = project / "Example.p02.hdf"
    _write_result_hdf(result_hdf, end="22Sep2019 12:00:00.000")
    workspace = RasScenarioWorkspace(
        scenario_id="scenario",
        source_project=project / "source.prj",
        project_folder=project,
        project_file=project / "Example.prj",
        plan_number="02",
        plan_file=project / "Example.p02",
        unsteady_number="02",
        unsteady_file=project / "Example.u02",
        hydrology_source=tmp_path / "source.dss",
        hydrology_file=project / "hydrology.dss",
        result_hdf=result_hdf,
        boundary_mapping_ids=("mapping",),
        simulation_start="2019-09-18T13:00:00",
        simulation_end="2019-09-22T13:00:00",
    )
    scenario_module = importlib.import_module("ras_commander.RasScenario")
    monkeypatch.setattr(
        scenario_module,
        "init_ras_project",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        scenario_module.RasCmdr,
        "compute_plan",
        lambda *args, **kwargs: True,
    )

    artifact = RasScenario.execute(
        workspace,
        ras_exe_path=RAS_EXE,
    )

    assert artifact.status == "failed"
    assert artifact.hdf_completed_successfully
    assert not artifact.time_window_matches


def test_linked_asset_cache_adopts_existing_copy_and_reuses_it(tmp_path, monkeypatch):
    source = tmp_path / "source" / "Terrain"
    source.mkdir(parents=True)
    (source / "terrain.hdf").write_bytes(b"immutable terrain")
    cache_root = tmp_path / "cache"
    cached = cache_root / "Terrain"
    cached.mkdir(parents=True)
    (cached / "terrain.hdf").write_bytes(b"immutable terrain")
    cache_key = "a" * 64

    adopted = RasScenario._prepare_linked_asset_cache(
        cache_root, (source.resolve(),), cache_key
    )

    assert adopted["status"] == "adopted"
    assert adopted["size_bytes"] == len(b"immutable terrain")
    manifest = cache_root / RasScenario.LINKED_ASSET_CACHE_MANIFEST
    assert manifest.is_file()

    scenario_module = importlib.import_module("ras_commander.RasScenario")
    monkeypatch.setattr(
        scenario_module.shutil,
        "copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache reuse must not copy linked assets")
        ),
    )
    reused = RasScenario._prepare_linked_asset_cache(
        cache_root, (source.resolve(),), cache_key
    )

    assert reused["status"] == "reused"
    assert reused["manifest"] == str(manifest)


def test_linked_asset_cache_refuses_cached_file_drift(tmp_path):
    source = tmp_path / "source" / "Terrain"
    source.mkdir(parents=True)
    (source / "terrain.hdf").write_bytes(b"immutable terrain")
    cache_root = tmp_path / "cache"
    RasScenario._prepare_linked_asset_cache(cache_root, (source.resolve(),), "b" * 64)
    cached_file = cache_root / "Terrain" / "terrain.hdf"
    cached_file.chmod(stat.S_IREAD | stat.S_IWRITE)
    cached_file.write_bytes(b"tampered terrain")

    with pytest.raises(ValueError, match="cache copy Terrain metadata drifted"):
        RasScenario._prepare_linked_asset_cache(
            cache_root, (source.resolve(),), "b" * 64
        )


def test_scenario_clone_excludes_generated_outputs_but_keeps_geometry_hdf(tmp_path):
    source = tmp_path / "Model"
    nested = source / "Maps"
    nested.mkdir(parents=True)
    files = {
        source / "Model.dss": 10,
        source / "Model.p01.hdf": 20,
        source / "Model.p02.tmp.hdf": 30,
        nested / "PostProcessing.hdf": 40,
        source / "Model.g01.hdf": 50,
        source / "Model.prj": 60,
    }
    for path, size in files.items():
        path.write_bytes(b"x" * size)

    exclusions = RasScenario._scenario_output_exclusions(source, "Model")
    root_ignored = RasScenario._scenario_copy_ignore("Model")(
        str(source), [path.name for path in source.iterdir()]
    )
    nested_ignored = RasScenario._scenario_copy_ignore("Model")(
        str(nested), [path.name for path in nested.iterdir()]
    )

    assert exclusions["file_count"] == 4
    assert exclusions["size_bytes"] == 100
    assert "Model.dss" in root_ignored
    assert "Model.p01.hdf" in root_ignored
    assert "Model.p02.tmp.hdf" in root_ignored
    assert "PostProcessing.hdf" in nested_ignored
    assert "Model.g01.hdf" not in root_ignored
    assert "Model.prj" not in root_ignored


def test_newline_inspection_ignores_generated_compute_artifacts(tmp_path):
    project_file = _write_project(tmp_path / "source")
    compute_artifact = project_file.parent / "Example.c04"
    compute_artifact.write_bytes(b"generated\r\ncompute\nartifact\x00")

    evidence = RasScenario.inspect_newlines(project_file.parent)

    assert evidence["consistent"] is True
    assert str(compute_artifact) not in evidence["files"]
