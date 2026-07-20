"""Process-isolation tests for the executable qualification runner."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ras_commander import (
    ExecutorProfile,
    QualificationActionSpec,
    QualificationRunConfig,
    RasQualification,
    RasQualificationRunner,
)
from ras_commander.RasQualificationRunner import DEFAULT_ACTION_HANDLER


def _write_project(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "Runner.prj").write_text(
        "Proj Title=Runner Fixture\nCurrent Plan=p01\nPlan File=p01\n",
        encoding="utf-8",
    )
    (path / "Runner.p01").write_text(
        "Plan Title=Runner\nProgram Version=7.01\nGeom File=g01\nFlow File=u01\n",
        encoding="utf-8",
    )
    (path / "Runner.g01").write_text("Geom Title=Runner\n", encoding="utf-8")
    return path


def _write_install(path: Path) -> Path:
    (path / "x64").mkdir(parents=True)
    for relative in [
        "Ras.exe",
        "RasProcess.exe",
        "RasMapperLib.dll",
        "x64/RasGeomPreprocess.exe",
        "x64/RasUnsteady.exe",
    ]:
        (path / relative).write_bytes(relative.encode("ascii"))
    return path / "Ras.exe"


def _write_handlers(path: Path) -> Path:
    module = path / "qualification_runner_test_handlers.py"
    module.write_text(
        """
import time


def pass_action(context, update_key=None):
    evidence = {
        "operation_id": context["operation_id"],
        "project_exists": __import__("pathlib").Path(context["project_file"]).is_file(),
    }
    updates = {update_key: context["operation_id"]} if update_key else {}
    return {"passed": True, "evidence": evidence, "context_updates": updates}


def observe_update(context, required_key):
    return {
        "passed": context.get(required_key) == "project.open",
        "evidence": {"observed": context.get(required_key)},
    }


def sleep_action(context, seconds):
    time.sleep(seconds)
    return {"passed": True, "evidence": {"slept": seconds}}


def fail_action(context):
    return {
        "passed": False,
        "evidence": {"failure_fingerprint": "content-level-evidence"},
        "diagnostics": {"reason": "intentional rejection"},
    }


def diagnostic_artifacts(context):
    return {
        "passed": True,
        "evidence": {"diagnostic": True},
        "artifacts": {"results": {"successful": True}},
        "series": {
            "outflow": {
                "kind": "profile_line_flow",
                "value_columns": ["flow"],
                "records": [{"time": "2026-01-01T00:00:00", "flow": 1.0}],
            }
        },
        "context_updates": {"extraction_complete": True},
    }
""".lstrip(),
        encoding="utf-8",
    )
    return module


def _config(tmp_path: Path, actions, *, stop_on_failure=False) -> QualificationRunConfig:
    source = _write_project(tmp_path / "source")
    ras_exe = _write_install(tmp_path / "HEC-RAS" / "7.0.1")
    return QualificationRunConfig(
        profile=ExecutorProfile.WINDOWS_NATIVE,
        expected_version="7.0.1",
        ras_executable=ras_exe,
        source_project=source,
        workspace_root=tmp_path / "workspaces",
        receipt_path=tmp_path / "receipts" / "native.json",
        fixture={"id": "runner-unit"},
        actions=actions,
        stop_on_failure=stop_on_failure,
    )


def _prepend_pythonpath(monkeypatch, path: Path) -> None:
    existing = os.environ.get("PYTHONPATH", "")
    value = str(path) if not existing else str(path) + os.pathsep + existing
    monkeypatch.setenv("PYTHONPATH", value)


def test_runner_checkpoints_actions_and_propagates_context(tmp_path, monkeypatch):
    _write_handlers(tmp_path)
    _prepend_pythonpath(monkeypatch, tmp_path)
    module = "qualification_runner_test_handlers"
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                f"{module}:pass_action",
                parameters={"update_key": "opened_by"},
            ),
            QualificationActionSpec(
                "project.save",
                f"{module}:observe_update",
                parameters={"required_key": "opened_by"},
            ),
        ],
    )

    receipt = RasQualificationRunner(config).run()
    operations = {item["id"]: item for item in receipt["operations"]}

    assert operations["installation.detect"]["status"] == "passed"
    assert operations["project.clone"]["status"] == "passed"
    assert operations["project.open"]["status"] == "passed"
    assert operations["project.save"]["status"] == "passed"
    assert operations["path.spaces"]["status"] == "failed"
    assert receipt["runner_passed"] is False
    assert config.receipt_path.is_file()
    context = json.loads(
        (config.receipt_path.parent / "native-run" / "context.json").read_text()
    )
    assert context["opened_by"] == "project.open"


def test_runner_terminates_timed_out_operation_and_retains_diagnostics(tmp_path, monkeypatch):
    _write_handlers(tmp_path)
    _prepend_pythonpath(monkeypatch, tmp_path)
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                "qualification_runner_test_handlers:sleep_action",
                timeout_seconds=1,
                parameters={"seconds": 30},
            )
        ],
        stop_on_failure=True,
    )

    receipt = RasQualificationRunner(config).run()
    operation = next(item for item in receipt["operations"] if item["id"] == "project.open")

    assert operation["status"] == "failed"
    assert operation["diagnostics"]["timed_out"] is True
    assert Path(operation["diagnostics"]["operation_log"]).is_file()
    assert receipt["runner_passed"] is False


def test_stop_on_failure_ignores_unconfigured_placeholders(tmp_path, monkeypatch):
    module = _write_handlers(tmp_path).stem
    _prepend_pythonpath(monkeypatch, tmp_path)
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                f"{module}:pass_action",
            ),
            QualificationActionSpec(
                "projection.select",
                f"{module}:pass_action",
            ),
        ],
        stop_on_failure=True,
    )

    receipt = RasQualificationRunner(config).run()
    operations = {item["id"]: item for item in receipt["operations"]}

    assert operations["project.open"]["status"] == "passed"
    assert operations["project.save"]["status"] == "failed"
    assert operations["projection.select"]["status"] == "passed"
    assert receipt["runner_passed"] is False


def test_runner_retains_content_evidence_from_failed_action(tmp_path, monkeypatch):
    _write_handlers(tmp_path)
    _prepend_pythonpath(monkeypatch, tmp_path)
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                "qualification_runner_test_handlers:fail_action",
            )
        ],
        stop_on_failure=True,
    )

    receipt = RasQualificationRunner(config).run()
    operation = next(item for item in receipt["operations"] if item["id"] == "project.open")

    assert operation["status"] == "failed"
    assert operation["evidence"]["failure_fingerprint"] == "content-level-evidence"
    assert operation["evidence"]["project_fingerprint_before"]
    assert operation["evidence"]["project_fingerprint_after"]
    assert operation["diagnostics"]["reason"] == "intentional rejection"


def test_manifest_parser_rejects_duplicate_actions(tmp_path):
    source = _write_project(tmp_path / "source")
    ras_exe = _write_install(tmp_path / "HEC-RAS" / "7.0.1")
    manifest = {
        "schema_version": RasQualification.SCHEMA_VERSION,
        "profile": "windows_native",
        "expected_version": "7.0.1",
        "ras_executable": str(ras_exe),
        "source_project": str(source),
        "workspace_root": str(tmp_path / "workspaces"),
        "receipt_path": str(tmp_path / "receipt.json"),
        "fixture": {"id": "duplicate-test"},
        "actions": [
            {"id": "project.open", "handler": "x:y"},
            {"id": "project.open", "handler": "x:z"},
        ],
    }

    try:
        QualificationRunConfig.from_mapping(manifest)
    except ValueError as exc:
        assert "Duplicate action specifications" in str(exc)
    else:
        raise AssertionError("duplicate actions were accepted")


def test_manifest_action_defaults_to_fail_closed_builtin_dispatcher():
    action = QualificationActionSpec.from_mapping({"id": "project.open"})

    assert action.handler == DEFAULT_ACTION_HANDLER
    assert action.worker_runtime == "configured"


def test_manifest_action_accepts_native_worker_runtime():
    action = QualificationActionSpec.from_mapping(
        {"id": "mesh.generate_initial", "worker_runtime": "native"}
    )

    assert action.worker_runtime == "native"


def test_manifest_accepts_geometry_table_diagnostic():
    action = QualificationActionSpec.from_mapping(
        {"id": "properties.geometry_tables"}
    )

    assert action.operation_id in RasQualification.DIAGNOSTIC_OPERATIONS


def test_failed_diagnostic_does_not_set_runner_failure(tmp_path, monkeypatch):
    _write_handlers(tmp_path)
    _prepend_pythonpath(monkeypatch, tmp_path)
    monkeypatch.setattr(
        RasQualification,
        "REQUIRED_OPERATIONS",
        ("installation.detect", "project.clone", "project.open"),
    )
    monkeypatch.setattr(
        RasQualification,
        "validate_run_receipt",
        staticmethod(lambda *args, **kwargs: {"passed": True}),
    )
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                "qualification_runner_test_handlers:pass_action",
            ),
            QualificationActionSpec(
                "properties.geometry_tables",
                "qualification_runner_test_handlers:fail_action",
            ),
        ],
    )

    receipt = RasQualificationRunner(config).run()
    operations = {item["id"]: item for item in receipt["operations"]}

    assert operations["project.open"]["status"] == "passed"
    assert operations["properties.geometry_tables"]["status"] == "failed"
    assert receipt["runner_passed"] is True


def test_passed_diagnostic_merges_artifacts_series_and_context(tmp_path, monkeypatch):
    _write_handlers(tmp_path)
    _prepend_pythonpath(monkeypatch, tmp_path)
    monkeypatch.setattr(
        RasQualification,
        "REQUIRED_OPERATIONS",
        ("installation.detect", "project.clone", "project.open"),
    )
    monkeypatch.setattr(
        RasQualification,
        "validate_run_receipt",
        staticmethod(lambda *args, **kwargs: {"passed": True}),
    )
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec(
                "project.open",
                "qualification_runner_test_handlers:pass_action",
            ),
            QualificationActionSpec(
                "results.extract_series",
                "qualification_runner_test_handlers:diagnostic_artifacts",
            ),
        ],
    )

    runner = RasQualificationRunner(config)
    receipt = runner.run()

    assert receipt["artifacts"]["results"]["successful"] is True
    assert receipt["series"]["outflow"]["records"][0]["flow"] == 1.0
    assert runner.context["extraction_complete"] is True


def test_wine_manifest_requires_explicit_windows_python_worker(tmp_path):
    source = _write_project(tmp_path / "source")
    ras_exe = _write_install(tmp_path / "HEC-RAS" / "7.0.1")
    manifest = {
        "profile": "linux_wine_windows_ras",
        "expected_version": "7.0.1",
        "ras_executable": str(ras_exe),
        "source_project": str(source),
        "workspace_root": str(tmp_path / "workspaces"),
        "receipt_path": str(tmp_path / "wine.json"),
        "fixture": {"id": "wine-worker-contract"},
        "actions": [],
    }

    with pytest.raises(ValueError, match="Wine-hosted Windows Python"):
        QualificationRunConfig.from_mapping(manifest)

    manifest["executor"] = {
        "worker_command": ["wine", "C:\\Python311\\python.exe"],
        "payload_path_mode": "wine",
    }
    parsed = QualificationRunConfig.from_mapping(manifest)
    assert parsed.executor["worker_command"][1] == "C:\\Python311\\python.exe"
    assert parsed.executor["payload_path_mode"] == "wine"


def test_wine_payload_paths_roundtrip_through_configured_prefix(tmp_path, monkeypatch):
    config = replace(
        _config(tmp_path, actions=[]),
        profile=ExecutorProfile.LINUX_WINE_WINDOWS_RAS,
        executor={
            "worker_command": ["wine", r"C:\Python311\python.exe"],
            "payload_path_mode": "wine",
        },
    )
    runner = RasQualificationRunner(config)
    host_path = str((tmp_path / "payloads" / "operation.json").resolve())
    calls = []

    def convert(value, direction):
        calls.append((value, direction))
        if direction == "-w":
            return r"C:\rasq\operation.json"
        return host_path

    monkeypatch.setattr(runner, "_winepath", convert)

    worker_payload = runner._to_worker_paths(
        {"result_path": host_path, "ordinary_value": "mesh.breakline"}
    )
    assert worker_payload == {
        "result_path": r"C:\rasq\operation.json",
        "ordinary_value": "mesh.breakline",
    }
    host_payload = runner._to_host_paths(worker_payload)
    assert host_payload["result_path"] == host_path
    assert host_payload["ordinary_value"] == "mesh.breakline"
    assert calls == [
        (host_path, "-w"),
        (r"C:\rasq\operation.json", "-u"),
    ]


def test_wine_worker_environment_disables_modal_debugger_by_default(tmp_path):
    config = replace(
        _config(tmp_path, actions=[]),
        profile=ExecutorProfile.LINUX_WINE_WINDOWS_RAS,
        executor={"environment": {"WINEDEBUG": "+seh"}},
        wine={},
    )
    runner = RasQualificationRunner(config)
    runner.context = {"wine_prefix": str(tmp_path / "prefix")}

    environment = runner._worker_environment()

    assert environment["WINEPREFIX"] == str(tmp_path / "prefix")
    assert environment["WINEDLLOVERRIDES"] == (
        "winemenubuilder.exe=d;winedbg.exe=d"
    )
    assert environment["WINEDEBUG"] == "+seh"


def test_wine_prepare_rejects_missing_template_before_creating_prefix(
    tmp_path, monkeypatch
):
    config = replace(
        _config(tmp_path, actions=[]),
        profile=ExecutorProfile.LINUX_WINE_WINDOWS_RAS,
        executor={
            "worker_command": ["wine", r"C:\Python311\python.exe"],
            "payload_path_mode": "wine",
        },
        wine={"prefix_root": str(tmp_path / "prefixes")},
    )

    def unexpected_prefix_creation(*_args, **_kwargs):
        raise AssertionError("prefix creation must not run without a template")

    monkeypatch.setattr(
        RasQualification,
        "create_isolated_wine_prefix",
        staticmethod(unexpected_prefix_creation),
    )

    with pytest.raises(ValueError, match=r"wine\.template_prefix"):
        RasQualificationRunner(config)._prepare()

    assert not (tmp_path / "prefixes").exists()


def test_wine_prepare_uses_cloned_installation_not_shared_template(tmp_path, monkeypatch):
    source = _write_project(tmp_path / "source")
    template = tmp_path / "template-prefix"
    ras_exe = _write_install(template / "drive_c" / "HEC-RAS" / "7.0.1")
    pythonnet_metadata = (
        template
        / "drive_c"
        / "Python311"
        / "Lib"
        / "site-packages"
        / "pythonnet-3.0.5.dist-info"
        / "METADATA"
    )
    pythonnet_metadata.parent.mkdir(parents=True)
    pythonnet_metadata.write_text(
        "Name: pythonnet\nVersion: 3.0.5\n", encoding="utf-8"
    )
    stale_package = pythonnet_metadata.parent.parent / "ras_commander"
    stale_package.mkdir()
    (stale_package / "RasQualificationRunner.py").write_text(
        "# stale template package\n", encoding="utf-8"
    )
    (template / "drive_c" / "Python311" / "GDAL" / "bin64").mkdir(
        parents=True
    )
    (
        template
        / "drive_c"
        / "Python311"
        / "GDAL"
        / "common"
        / "data"
    ).mkdir(parents=True)
    (template / "drive_c" / "HEC-RAS" / "7.0.1" / "GDAL" / "bin64").mkdir(
        parents=True
    )
    (
        template
        / "drive_c"
        / "HEC-RAS"
        / "7.0.1"
        / "GDAL"
        / "common"
        / "data"
    ).mkdir(parents=True)
    clone = tmp_path / "prefixes" / "isolated-prefix"
    config = QualificationRunConfig(
        profile=ExecutorProfile.LINUX_WINE_WINDOWS_RAS,
        expected_version="7.0.1",
        ras_executable=ras_exe,
        source_project=source,
        workspace_root=tmp_path / "workspaces",
        receipt_path=tmp_path / "receipts" / "wine.json",
        fixture={"id": "isolated-install-test"},
        actions=[],
        executor={
            "worker_command": ["wine", r"C:\Python311\python.exe"],
            "payload_path_mode": "wine",
        },
        wine={
            "template_prefix": str(template),
            "prefix_root": str(tmp_path / "prefixes"),
            "stage_inside_prefix": True,
            "python_site_packages": "drive_c/Python311/Lib/site-packages",
            "runtime_packages": {"pythonnet": "3.0.5"},
        },
    )

    clone_calls = []

    def clone_prefix(*_args, **_kwargs):
        clone_calls.append(_kwargs)
        shutil.copytree(template, clone)
        metadata = {
            "prefix": str(clone),
            "wine_executable": "wine",
            "wine_arch": "win64",
            "initialized": True,
            "template_prefix": str(template),
            "template_fingerprint": "test-template",
        }
        RasQualification._write_prefix_metadata(clone, metadata)
        return metadata

    monkeypatch.setattr(
        RasQualification,
        "create_isolated_wine_prefix",
        staticmethod(clone_prefix),
    )
    runner = RasQualificationRunner(config)
    runner._prepare()

    expected = clone / ras_exe.relative_to(template)
    assert runner.context["ras_executable"] == str(expected)
    assert runner.context["template_ras_executable"] == str(ras_exe)
    prefix_evidence = runner.context["wine_prefix_receipt"]
    assert prefix_evidence["isolated_ras_executable"] == str(expected)
    assert prefix_evidence["isolated_component_hashes_match"] is True
    assert prefix_evidence["isolated_installation_identity_matches"] is True
    assert prefix_evidence["runtime_packages_match"] is True
    assert prefix_evidence["runtime_packages"]["checks"]["pythonnet"]["matches"] is True
    package_sync = prefix_evidence["worker_package_sync"]
    assert package_sync["matched"] is True
    assert package_sync["same_location"] is False
    assert package_sync["source_fingerprint"] == package_sync["destination_fingerprint"]
    assert package_sync["source_file_count"] == package_sync["destination_file_count"]
    installed_runner = (
        clone
        / "drive_c"
        / "Python311"
        / "Lib"
        / "site-packages"
        / "ras_commander"
        / "RasQualificationRunner.py"
    )
    running_runner = Path(
        __import__(
            "ras_commander.RasQualificationRunner",
            fromlist=["__file__"],
        ).__file__
    )
    assert installed_runner.read_bytes() == running_runner.read_bytes()
    assert (stale_package / "RasQualificationRunner.py").read_text(
        encoding="utf-8"
    ) == "# stale template package\n"
    assert prefix_evidence["gdal_bridge"]["usable"] is True
    assert prefix_evidence["gdal_bridge"]["target_within_prefix"] is True
    assert clone_calls[0]["initialize"] is False


def test_builtin_project_actions_open_save_and_reopen_staged_project(tmp_path):
    config = _config(
        tmp_path,
        actions=[
            QualificationActionSpec.from_mapping({"id": "project.open"}),
            QualificationActionSpec.from_mapping(
                {
                    "id": "project.save",
                    "parameters": {"marker": "runner persisted marker"},
                }
            ),
        ],
    )

    receipt = RasQualificationRunner(config).run()
    operations = {item["id"]: item for item in receipt["operations"]}

    assert operations["project.open"]["status"] == "passed"
    assert operations["project.open"]["evidence"]["plan_count"] == 1
    assert operations["project.save"]["status"] == "passed"
    assert operations["project.save"]["evidence"]["persisted_exactly"] is True
    assert operations["project.save"]["evidence"]["file_changed"] is True
    assert operations["project.open"]["evidence"]["executor_project_lock"]["release"]["released"] is True
    assert operations["project.save"]["evidence"]["executor_project_lock"]["release"]["released"] is True
    staged_project = Path(operations["project.clone"]["evidence"]["destination"])
    assert not (staged_project / ".ras-commander-project.lock").exists()
    assert receipt["runner_passed"] is False  # missing critical actions remain fatal
