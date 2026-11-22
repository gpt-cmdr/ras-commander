"""GeomMesh.generate(premesh_policy=...): opt-in warn-only pre-mesh containment."""

import logging
import os
import platform
from pathlib import Path

import pytest

from ras_commander import RasExamples, RasPlan, RasPrj, init_ras_project
from ras_commander.geom import GeomMesh
from ras_commander.geom.GeomMesh import _apply_premesh_policy, _check_premesh_policy
from ras_commander.geom.GeomMeshDataclasses import (
    DomainContainmentResult,
    DomainContainmentViolation,
    MeshResult,
)

HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"


def _bald_eagle(tmp_path):
    project = Path(RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path))
    return project, init_ras_project(project, "7.0.1", ras_object=RasPrj())


def test_invalid_policy_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="premesh_policy"):
        _check_premesh_policy("lenient")
    _project, ras = _bald_eagle(tmp_path)
    with pytest.raises(ValueError, match="premesh_policy"):
        GeomMesh.generate("02", ras_object=ras, premesh_policy="off")


def test_strict_default_still_refuses_real_near_perimeter_breakline(tmp_path):
    project, ras = _bald_eagle(tmp_path)
    before = (project / "BaldEagleDamBrk.g02").read_bytes()
    result = GeomMesh.generate("02", ras_object=ras, allow_boundary_connections=True)
    assert not result.ok
    assert "Pre-mesh domain containment failed" in result.error_message
    assert "Breakline 1" in result.error_message
    assert result.premesh_policy == "strict" and result.premesh_warnings == []
    assert (project / "BaldEagleDamBrk.g02").read_bytes() == before


def _containment(violations):
    return DomainContainmentResult(
        mesh_name="Area", geom_hdf_path="Area.g01.hdf", base_cell_spacing=100.0,
        inward_buffer_distance=100.0, admissible_geometry_type="Polygon",
        checked_counts={"breakline": 2}, violations=violations,
    )


def test_warn_records_and_logs_every_violation(caplog):
    violations = [
        DomainContainmentViolation("breakline", "BL 1", 4, "LineString", "outside_one_cell_inward_buffer"),
        DomainContainmentViolation("breakline", "BL 2", 5, "", "fewer_than_two_points"),
    ]
    result = MeshResult(mesh_name="Area", status="error", premesh_policy="warn")
    with caplog.at_level(logging.WARNING):
        assert _apply_premesh_policy(_containment(violations), "warn", result, "initial")
    assert [w["feature_name"] for w in result.premesh_warnings] == ["BL 1", "BL 2"]
    assert {w["stage"] for w in result.premesh_warnings} == {"initial"}
    assert "fewer_than_two_points" in caplog.text and "BL 2" in caplog.text


def test_strict_stops_and_passing_audit_continues():
    violation = DomainContainmentViolation("structure", "", 0, "LineString", "outside")
    result = MeshResult(mesh_name="Area", status="error")
    assert not _apply_premesh_policy(_containment([violation]), "strict", result, "initial")
    assert _apply_premesh_policy(_containment([]), "strict", result, "initial")
    assert _apply_premesh_policy(_containment([]), "warn", result, "initial")
    assert result.premesh_warnings == []


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
@pytest.mark.parametrize("geom, breakline", [("02", "Breakline 1"), ("03", "SayersDam")])
def test_warn_meshes_real_area_and_hecras_preprocesses_it(tmp_path, geom, breakline):
    from ras_commander.geom import GeomPreprocessor

    project, ras = _bald_eagle(tmp_path)
    result = GeomMesh.generate(
        geom, ras_object=ras, allow_boundary_connections=True, premesh_policy="warn"
    )
    assert result.ok, result.error_message
    assert [w["feature_name"] for w in result.premesh_warnings] == [breakline]
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    plans = ras.plan_df.loc[ras.plan_df.geometry_number == geom, "plan_number"].tolist()
    if plans:
        plan = plans[0]
    else:
        plan = ras.plan_df.plan_number.iloc[0]
        RasPlan.set_geom(plan, geom, ras_object=ras)
        ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    pre = GeomPreprocessor.run_geometry_preprocessor(plan, ras_object=ras, max_wait=3600)
    assert pre.success, pre.error
