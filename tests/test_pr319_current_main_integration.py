"""Current-main launch compatibility under structured execution safeguards.

No HEC-RAS engine runs here. These tests use exact process records, real project
declarations, and the existing deterministic launcher fixture to exercise the
merged control-flow boundaries rather than hydraulic behavior.
"""

import hashlib
from types import SimpleNamespace

import pytest

from ras_commander import RasCmdr, RasProcessInventory, RasProcessRecord
from ras_commander._process_inspection import match_plan_processes

from test_rascmdr_compute_plan_control_flow import (
    _DummyRas,
    _patch_compute_launcher,
    rascmdr_module,
)


def _project(monkeypatch, tmp_path, version):
    ras_object = _DummyRas()
    ras_object.project_folder = tmp_path
    ras_object.project_name = "Project with spaces"
    ras_object.prj_file = tmp_path / "Project with spaces.prj"
    ras_object.prj_file.write_bytes(b"Proj Title=Example\r\nCurrent Plan=p02\r\n")
    ras_object.ras_version = version
    plan_path = tmp_path / "Project with spaces.p01"
    plan_path.write_bytes(b"Plan Title=Plan 01\r\n")
    executable = _patch_compute_launcher(monkeypatch, tmp_path, ras_object)
    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan_path),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    monkeypatch.setattr(RasCmdr, "_tcu_blocks_launch", staticmethod(lambda ras: False))
    monkeypatch.setattr(
        RasCmdr,
        "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: None),
    )
    return ras_object, plan_path, executable


@pytest.mark.parametrize("version", ["5.0", "5.0.7", "6.3", "6.6"])
def test_merged_launch_keeps_legacy_command_environment_and_provenance(
    monkeypatch, tmp_path, version
):
    ras_object, plan_path, executable = _project(monkeypatch, tmp_path, version)
    selected_plans = []
    events = []
    environment = {"PATH": "controlled-WMIC-directory", "RAS_TEST_MARKER": version}
    temporary_compatibility = SimpleNamespace(cleanup=lambda: events.append("cleanup"))
    monkeypatch.setattr(
        RasCmdr,
        "_legacy_wmic_subprocess_env",
        staticmethod(lambda ras: (environment, temporary_compatibility)),
    )

    def set_current_plan(plan_number):
        assert ras_object.process_inspection_calls == [("01", ras_object)]
        selected_plans.append(plan_number)
        ras_object.prj_file.write_bytes(b"Proj Title=Example\r\nCurrent Plan=p01\r\n")

    ras_object.set_current_plan = set_current_plan
    fake_launcher = rascmdr_module.subprocess.Popen
    observed = {}

    def launch(command, **kwargs):
        events.append("launch")
        observed.update(command=command, **kwargs)
        return fake_launcher(command, **kwargs)

    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", launch)
    result = RasCmdr.compute_plan(
        "01", ras_object=ras_object, force_rerun=True,
        dialog_watchdog=False, max_runtime=30,
    )

    assert result.success is True
    project_path = ras_object.prj_file.resolve()
    if version.startswith("5."):
        expected = f'"{executable.resolve()}" "{project_path}" -c'
        assert selected_plans == ["01"]
        assert str(plan_path) not in observed["command"]
    else:
        expected = f'"{executable.resolve()}" -c "{project_path}" "{plan_path.resolve()}"'
        assert selected_plans == []
        assert b"Current Plan=p02" in ras_object.prj_file.read_bytes()
    assert observed["command"] == expected
    assert observed["shell"] is False
    assert observed["env"] is environment
    assert observed["executable"] == str(executable.resolve())
    assert events == ["launch", "cleanup"]
    details = result.execution_details
    assert details["actual_engine_provenance_confirmed"] is True
    assert details["solver_quiescence_confirmed"] is True
    assert details["result_artifacts_finalized"] is True
    assert details["selected_executable_sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert details["launch_details"]["command"] == expected
    assert details["launch_details"]["max_runtime_seconds"] == 30


def test_wmic_cleanup_failure_does_not_bypass_structured_finalization(
    monkeypatch, tmp_path
):
    ras_object, _, _ = _project(monkeypatch, tmp_path, "6.3")

    def cleanup():
        raise PermissionError("WMIC shim is temporarily locked")

    monkeypatch.setattr(
        RasCmdr,
        "_legacy_wmic_subprocess_env",
        staticmethod(lambda ras: ({}, SimpleNamespace(cleanup=cleanup))),
    )
    result = RasCmdr.compute_plan(
        "01", ras_object=ras_object, force_rerun=True, dialog_watchdog=False,
    )
    assert result.success is True
    assert result.execution_details["result_artifacts_finalized"] is True
    assert result.execution_details["solver_quiescence_confirmed"] is True
    assert result.execution_details["compatibility_cleanup_error"] == {
        "error_type": "PermissionError",
        "error_detail": "WMIC shim is temporarily locked",
    }


@pytest.mark.parametrize("decision", ["skip", "incomplete_preflight", "active_preflight"])
def test_legacy_current_plan_is_unchanged_when_launch_is_not_allowed(
    monkeypatch, tmp_path, decision
):
    ras_object, _, _ = _project(monkeypatch, tmp_path, "5.0.7")
    before = ras_object.prj_file.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("A skipped or unsafe launch changed Current Plan or launched a process")

    ras_object.set_current_plan = forbidden
    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", forbidden)
    monkeypatch.setattr(
        RasCmdr, "_legacy_wmic_subprocess_env", staticmethod(lambda ras: (None, None))
    )
    if decision == "skip":
        monkeypatch.setattr(RasCmdr, "_verify_result", staticmethod(lambda *a, **k: True))
    else:
        monkeypatch.setattr(
            RasCmdr,
            "inspect_plan_processes",
            staticmethod(lambda *a, **k: SimpleNamespace(
                complete=decision != "incomplete_preflight",
                matched=[object()] if decision == "active_preflight" else [],
            )),
        )

    result = RasCmdr.compute_plan(
        "01", ras_object=ras_object, force_rerun=True,
        skip_existing=decision == "skip", dialog_watchdog=False,
    )
    assert result.success is (decision == "skip")
    assert result.execution_details["calculation_attempted"] is False
    assert ras_object.prj_file.read_bytes() == before


def _match(tmp_path, command, project_contents):
    project_path = tmp_path / "Project.prj"
    if project_contents is not None:
        project_path.write_bytes(project_contents)
    plan_path = tmp_path / "Project.p01"
    plan_path.write_bytes(b"Plan Title=Plan 01\nGeom File=g03\n")
    process = RasProcessRecord(
        pid=120, create_time=2.0, name="Ras.exe",
        executable_path=str(tmp_path / "Ras.exe"),
        command_line=tuple(command), working_directory=str(tmp_path),
    )
    inventory = RasProcessInventory(observed_at=3.0, complete=True, processes=(process,))
    result = match_plan_processes(
        inventory, plan_number="01", project_path=project_path,
        plan_path=plan_path, tmp_hdf_path=tmp_path / "Project.p01.tmp.hdf",
    )
    return result, process


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_exact_project_only_launcher_requires_current_plan(tmp_path, newline):
    result, process = _match(
        tmp_path,
        ["Ras.exe", str(tmp_path / "Project.prj"), "-c"],
        newline.join([b"Proj Title=Example", b" Current Plan = P01 ", b""]),
    )
    assert result.complete is True
    assert result.matched == (process,)


@pytest.mark.parametrize("contents", [
    None,
    b"Proj Title=Example\n",
    b"Current Plan=p02\n",
    b"Current Plan=p01\nCurrent Plan=p01\n",
    b"Current Plan=p01\nCurrent Plan=p02\n",
])
def test_ambiguous_project_only_launcher_prevents_quiescence(tmp_path, contents):
    result, _ = _match(
        tmp_path, ["Ras.exe", str(tmp_path / "Project.prj"), "-c"], contents,
    )
    assert result.complete is False
    assert result.matched == ()
    assert result.query_errors[0].reason_code == "project_current_plan_identity_unavailable"


@pytest.mark.parametrize("command", [
    ["Ras.exe", "Project.prj.backup", "-c"],
    ["Ras.exe", "Project.prj", "-not-c"],
    ["Ras.exe", "-c", "Project.prj", "Project.p02"],
    ["Ras.exe", "Project.prj", "-c", "Project.p02"],
])
def test_other_project_or_explicit_plan_cannot_fall_back_to_current_plan(tmp_path, command):
    result, _ = _match(tmp_path, command, b"Current Plan=p01\n")
    assert result.complete is True
    assert result.matched == ()
