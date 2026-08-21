"""Contract tests for the package-owned RAS scenario worker."""

import hashlib
import importlib
import importlib.resources
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ras_commander import (
    HdfResultsProducts,
    RasRunArtifact,
    RasScenarioWorker,
    RasScenarioWorkspace,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    project = source / "Model.prj"
    project.write_text("Proj Title=Test\nCurrent Plan=p01\n", encoding="utf-8")
    model_manifest = tmp_path / "ras-model.json"
    model_manifest.write_text(
        json.dumps({"schema_version": 1, "stage": "ras"}),
        encoding="utf-8",
    )
    hydrology = tmp_path / "hms-output.dss"
    hydrology.write_bytes(b"hydrology")
    hydrologic_manifest = tmp_path / "hydrologic-products.json"
    hydrologic_manifest.write_text(
        json.dumps(
            {
                "schema": "hms-commander/hydrologic-product-manifest/1.0",
                "source": {"sha256": _sha256(hydrology)},
            }
        ),
        encoding="utf-8",
    )
    excess = tmp_path / "ras-excess.dss"
    excess.write_bytes(b"excess")
    excess_provenance = tmp_path / "ras-excess.json"
    excess_provenance.write_text(
        json.dumps({"schema": "test/excess-provenance/1.0"}),
        encoding="utf-8",
    )
    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"executable")
    request = {
        "schema": RasScenarioWorker.REQUEST_SCHEMA,
        "scenario": {
            "scenario_id": "test-scenario",
            "specification_sha256": "1" * 64,
        },
        "source_model": {
            "project": str(project),
            "project_file_sha256": _sha256(project),
            "template_plan": "01",
            "model_manifest": str(model_manifest),
            "model_manifest_sha256": _sha256(model_manifest),
            "linked_asset_directories": [],
        },
        "hydrology": {
            "dss": str(hydrology),
            "sha256": _sha256(hydrology),
            "product_manifest": str(hydrologic_manifest),
            "product_manifest_sha256": _sha256(hydrologic_manifest),
        },
        "boundary_links": [
            {
                "mapping_id": "tributary",
                "dss_path": "//TRIBUTARY/FLOW//5MIN/RUN:SCENARIO/",
                "expected_bc_type": "Flow Hydrograph",
                "river": "River",
                "reach": "Reach",
                "station": "1000",
            }
        ],
        "forcing_excess": {
            "dss": str(excess),
            "sha256": _sha256(excess),
            "provenance_manifest": str(excess_provenance),
            "provenance_manifest_sha256": _sha256(excess_provenance),
            "pathname": "/SHG/BASIN/PRECIPITATION///EXCESS/",
            "interpolation": "Bilinear",
        },
        "model_window": {
            "start": "2019-09-18T13:00:00",
            "end": "2019-09-19T13:00:00",
            "time_zone": "America/Chicago",
        },
        "workspace": str(tmp_path / "workspace"),
        "products": {
            "directory": str(tmp_path / "products"),
            "include_preview": False,
        },
        "execution": {
            "ras_executable": str(executable),
            "timeout_seconds": 60,
            "cores": 2,
        },
    }
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return request, request_path, result_path


def _write_prior_preparation_failure(request, request_path, result_path):
    """Write a preparation failure bound to the exact retained request."""
    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")
    request_sha256 = worker_module._json_sha256(request)
    Path(request["workspace"]).mkdir()
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.write_text(
        json.dumps(
            {
                "schema": RasScenarioWorker.RESULT_SCHEMA,
                "status": "failed",
                "request": {
                    "schema": RasScenarioWorker.REQUEST_SCHEMA,
                    "sha256": request_sha256,
                },
                "preparation": {"status": "in_progress"},
                "execution": {"status": "not_started"},
                "error": {"classification": "invalid_boundary_selector"},
            }
        ),
        encoding="utf-8",
    )
    return request_sha256


def _install_success_fakes(monkeypatch, request):
    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")
    calls = {"prepare": 0, "execute": 0, "export": 0}

    def prepare(*_args, **_kwargs):
        calls["prepare"] += 1
        folder = Path(request["workspace"])
        folder.mkdir()
        project_file = folder / "Model.prj"
        plan_file = folder / "Model.p02"
        unsteady_file = folder / "Model.u02"
        geometry_file = folder / "Model.g01"
        for path in (project_file, plan_file, unsteady_file, geometry_file):
            path.write_text("test\n", encoding="utf-8")
        hydrology_file = folder / "hydrology" / "hms-output.dss"
        hydrology_file.parent.mkdir()
        hydrology_file.write_bytes(b"hydrology")
        excess_file = folder / "hydrology" / "ras-excess.dss"
        excess_file.write_bytes(b"excess")
        return RasScenarioWorkspace(
            scenario_id=request["scenario"]["scenario_id"],
            source_project=Path(request["source_model"]["project"]),
            project_folder=folder,
            project_file=project_file,
            plan_number="02",
            plan_file=plan_file,
            unsteady_number="02",
            unsteady_file=unsteady_file,
            hydrology_source=Path(request["hydrology"]["dss"]),
            hydrology_file=hydrology_file,
            forcing_excess_source=Path(request["forcing_excess"]["dss"]),
            forcing_excess_file=excess_file,
            forcing_excess_pathname=request["forcing_excess"]["pathname"],
            result_hdf=folder / "Model.p02.hdf",
            boundary_mapping_ids=("tributary",),
            simulation_start=request["model_window"]["start"],
            simulation_end=request["model_window"]["end"],
        )

    def execute(workspace, **_kwargs):
        calls["execute"] += 1
        workspace.result_hdf.write_bytes(b"completed hdf")
        return RasRunArtifact(
            scenario_id=workspace.scenario_id,
            status="succeeded",
            plan_number=workspace.plan_number,
            project_folder=workspace.project_folder,
            result_hdf=workspace.result_hdf,
            started_at="2026-08-20T12:00:00Z",
            finished_at="2026-08-20T12:01:00Z",
            compute_returned_successfully=True,
            result_exists=True,
            result_size_bytes=workspace.result_hdf.stat().st_size,
            hdf_completed_successfully=True,
            output_start=request["model_window"]["start"],
            output_end=request["model_window"]["end"],
            time_window_matches=True,
            hdf_inspection_error=None,
        )

    def export(_hdf, output, **_kwargs):
        calls["export"] += 1
        output = Path(output)
        output.mkdir()
        numerical = {
            "schema": "ras-commander/numerical-qaqc-summary/1.0",
            "acceptance": "not_evaluated",
            "compute_message_findings": {
                "maximum_iteration": {
                    "count": 2,
                    "messages": ["maximum iteration"],
                }
            },
        }
        (output / HdfResultsProducts.FILENAMES["numerical-qaqc"]).write_text(
            json.dumps(numerical), encoding="utf-8"
        )
        manifest = {
            "schema": HdfResultsProducts.SCHEMA,
            "status": {
                "completed_successfully": True,
                "time_axis_consistent": True,
                "hydraulic_qaqc": "not_evaluated",
            },
        }
        (output / HdfResultsProducts.MANIFEST_FILENAME).write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return manifest

    monkeypatch.setattr(worker_module.RasScenario, "prepare_workspace", prepare)
    monkeypatch.setattr(
        worker_module.RasScenario,
        "validate_workspace",
        lambda *_args: {
            "project_uses_cloned_plan": True,
            "plan_window_matches_contract": True,
            "one_newline_convention": True,
            "all_boundaries_exist_in_active_geometry": True,
            "forcing_excess_link_matches": True,
        },
    )
    monkeypatch.setattr(
        worker_module.RasScenario,
        "inspect_workspace_evidence",
        lambda *_args: {
            "current_plan": "02",
            "simulation_window": {
                "start": request["model_window"]["start"],
                "end": request["model_window"]["end"],
            },
            "geometry_crosswalk": {"tributary": True},
            "newline": {"consistent": True, "convention": "\n"},
            "forcing_excess": {"enabled": True, "mode": "Gridded"},
        },
    )
    monkeypatch.setattr(worker_module.RasScenario, "execute", execute)
    monkeypatch.setattr(worker_module.HdfResultsProducts, "export", export)
    return calls


def test_worker_writes_identity_bound_success_and_verifies_repeat(
    tmp_path, monkeypatch
):
    request, request_path, result_path = _request(tmp_path)
    calls = _install_success_fakes(monkeypatch, request)

    assert RasScenarioWorker.run(request_path, result_path) == 0
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes)

    assert result["schema"] == RasScenarioWorker.RESULT_SCHEMA
    assert result["status"] == "succeeded"
    assert result["preparation"]["evidence"]["current_plan"] == "02"
    assert result["execution"]["hdf_completed_successfully"] is True
    assert result["result_hdf"]["sha256"] == _sha256(Path(result["result_hdf"]["path"]))
    assert result["products"]["schema"] == HdfResultsProducts.SCHEMA
    assert result["numerical_qaqc"]["acceptance"] == "not_evaluated"
    assert result["conditional_findings"]["maximum_iteration"]["count"] == 2
    assert result["error"] is None
    assert calls == {"prepare": 1, "execute": 1, "export": 1}

    assert RasScenarioWorker.run(request_path, result_path) == 0
    assert result_path.read_bytes() == result_bytes
    assert calls == {"prepare": 1, "execute": 1, "export": 1}

    Path(result["result_hdf"]["path"]).write_bytes(b"tampered")
    assert RasScenarioWorker.run(request_path, result_path) == 3
    assert result_path.read_bytes() == result_bytes


def test_worker_rejects_invalid_forcing_excess_identity(tmp_path):
    request, request_path, result_path = _request(tmp_path)
    request["forcing_excess"]["sha256"] = "f" * 64
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "forcing_excess_identity"
    assert not Path(request["workspace"]).exists()


def test_worker_rejects_hydrologic_manifest_for_another_dss(tmp_path):
    request, request_path, result_path = _request(tmp_path)
    manifest = Path(request["hydrology"]["product_manifest"])
    manifest.write_text(
        json.dumps(
            {
                "schema": "hms-commander/hydrologic-product-manifest/1.0",
                "source": {"sha256": "f" * 64},
            }
        ),
        encoding="utf-8",
    )
    request["hydrology"]["product_manifest_sha256"] = _sha256(manifest)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "hydrology_identity"


def test_worker_rejects_non_ras_model_manifest(tmp_path):
    request, request_path, result_path = _request(tmp_path)
    manifest = Path(request["source_model"]["model_manifest"])
    manifest.write_text(
        json.dumps({"schema_version": 1, "stage": "hms"}),
        encoding="utf-8",
    )
    request["source_model"]["model_manifest_sha256"] = _sha256(manifest)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "source_model_identity"


@pytest.mark.parametrize(
    "link",
    [
        {
            "mapping_id": "missing-selector",
            "dss_path": "//A/FLOW//5MIN/RUN/",
            "expected_bc_type": "Flow Hydrograph",
        },
        {
            "mapping_id": "mixed-selector",
            "dss_path": "//A/FLOW//5MIN/RUN/",
            "expected_bc_type": "Flow Hydrograph",
            "river": "River",
            "sa_2d_name": "Mesh",
        },
    ],
)
def test_worker_rejects_invalid_boundary_selectors(tmp_path, link):
    request, request_path, result_path = _request(tmp_path)
    request["boundary_links"] = [link]
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "invalid_request"


def test_worker_refuses_existing_workspace(tmp_path):
    request, request_path, result_path = _request(tmp_path)
    Path(request["workspace"]).mkdir()

    assert RasScenarioWorker.run(request_path, result_path) == 3
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "existing_workspace"


def test_no_retry_request_identity_survives_validation_and_result_binding(
    tmp_path, monkeypatch
):
    request, request_path, result_path = _request(tmp_path)
    normalized = RasScenarioWorker._validate_request(request)
    assert "retry" not in normalized
    _install_success_fakes(monkeypatch, request)

    assert RasScenarioWorker.run(request_path, result_path) == 0

    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["request"]["sha256"] == worker_module._json_sha256(request)


def test_worker_authenticates_preparation_retry_and_preserves_prior_workspace(
    tmp_path, monkeypatch
):
    prior_root = tmp_path / "prior"
    prior_root.mkdir()
    prior_request, prior_request_path, prior_result_path = _request(prior_root)
    prior_hash = _write_prior_preparation_failure(
        prior_request, prior_request_path, prior_result_path
    )
    prior_workspace = Path(prior_request["workspace"])

    request = json.loads(json.dumps(prior_request))
    request["source_model"]["linked_asset_mode"] = "shared-cache"
    request["boundary_links"][0]["boundary_index"] = 0
    request["workspace"] = str(prior_root / "retry-workspace")
    request["products"]["directory"] = str(tmp_path / "retry-products")
    request["retry"] = {
        "prior_request": str(prior_request_path),
        "prior_result": str(prior_result_path),
    }
    request_path = tmp_path / "retry-request.json"
    result_path = tmp_path / "retry-result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    _install_success_fakes(monkeypatch, request)

    assert RasScenarioWorker.run(request_path, result_path) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    retry = result["preparation"]["retry"]
    assert retry["status"] == "authenticated"
    assert retry["prior_request_sha256"] == prior_hash
    assert retry["failure_classification"] == "invalid_boundary_selector"
    assert prior_workspace.is_dir()


def test_worker_refuses_retry_when_immutable_inputs_change(tmp_path):
    prior_root = tmp_path / "prior"
    prior_root.mkdir()
    prior_request, prior_request_path, prior_result_path = _request(prior_root)
    _write_prior_preparation_failure(
        prior_request, prior_request_path, prior_result_path
    )
    request = json.loads(json.dumps(prior_request))
    request["source_model"]["linked_asset_mode"] = "shared-cache"
    request["workspace"] = str(prior_root / "retry-workspace")
    request["products"]["directory"] = str(tmp_path / "retry-products")
    request["model_window"]["end"] = "2019-09-20T13:00:00"
    request["retry"] = {
        "prior_request": str(prior_request_path),
        "prior_result": str(prior_result_path),
    }
    request_path = tmp_path / "retry-request.json"
    result_path = tmp_path / "retry-result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "retry_evidence"
    assert not Path(request["workspace"]).exists()


def test_worker_writes_failure_result_for_timeout(tmp_path, monkeypatch):
    request, request_path, result_path = _request(tmp_path)
    _install_success_fakes(monkeypatch, request)
    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")
    monkeypatch.setattr(
        worker_module.RasScenario,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("HEC-RAS exceeded 60 seconds")
        ),
    )

    assert RasScenarioWorker.run(request_path, result_path) == 4
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "timeout"
    assert result["error"]["retryable"] is True
    assert result["preparation"]["status"] == "passed"
    assert result["execution"]["status"] == "in_progress"
    assert Path(request["workspace"]).is_dir()


@pytest.mark.parametrize(
    ("changes", "classification"),
    [
        ({"result_exists": False, "result_size_bytes": 0}, "missing_hdf"),
        ({"hdf_completed_successfully": False}, "incomplete_hdf"),
        ({"time_window_matches": False}, "mismatched_result_time"),
    ],
)
def test_worker_classifies_failed_execution_artifacts(
    tmp_path, monkeypatch, changes, classification
):
    request, request_path, result_path = _request(tmp_path)
    _install_success_fakes(monkeypatch, request)
    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")

    def failed_execute(workspace, **_kwargs):
        workspace.result_hdf.write_bytes(b"failed hdf")
        values = {
            "scenario_id": workspace.scenario_id,
            "status": "failed",
            "plan_number": workspace.plan_number,
            "project_folder": workspace.project_folder,
            "result_hdf": workspace.result_hdf,
            "started_at": "2026-08-20T12:00:00Z",
            "finished_at": "2026-08-20T12:01:00Z",
            "compute_returned_successfully": True,
            "result_exists": True,
            "result_size_bytes": workspace.result_hdf.stat().st_size,
            "hdf_completed_successfully": True,
            "output_start": request["model_window"]["start"],
            "output_end": request["model_window"]["end"],
            "time_window_matches": True,
            "hdf_inspection_error": None,
        }
        values.update(changes)
        return RasRunArtifact(**values)

    monkeypatch.setattr(worker_module.RasScenario, "execute", failed_execute)

    assert RasScenarioWorker.run(request_path, result_path) == 4
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == classification
    assert result["products"] is None


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("Mixed newline conventions in HEC-RAS text file", "mixed_newlines"),
        (
            "Prepared RAS workspace failed validation: project_uses_cloned_plan",
            "wrong_current_plan",
        ),
        (
            "Prepared RAS workspace failed validation: plan_window_matches_contract",
            "wrong_window",
        ),
        (
            "Prepared RAS workspace failed validation: "
            "all_boundaries_exist_in_active_geometry",
            "inactive_geometry",
        ),
    ],
)
def test_worker_classifies_preparation_evidence_failures(
    tmp_path, monkeypatch, message, classification
):
    request, request_path, result_path = _request(tmp_path)
    worker_module = importlib.import_module("ras_commander.RasScenarioWorker")
    monkeypatch.setattr(
        worker_module.RasScenario,
        "prepare_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError(message)),
    )

    assert RasScenarioWorker.run(request_path, result_path) == 4
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == classification


def test_worker_rejects_request_contract_drift(tmp_path):
    request, request_path, result_path = _request(tmp_path)
    request["unexpected"] = True
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert RasScenarioWorker.run(request_path, result_path) == 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["error"]["classification"] == "invalid_request"
    assert "unknown unexpected" in result["error"]["message"]


def test_packaged_worker_schemas_match_public_contract_constants():
    package = importlib.resources.files("ras_commander") / "contracts"
    request_schema = json.loads(
        (package / "scenario-worker-request-v1.0.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result_schema = json.loads(
        (package / "scenario-worker-result-v1.0.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert request_schema["$id"] == RasScenarioWorker.REQUEST_SCHEMA
    assert result_schema["$id"] == RasScenarioWorker.RESULT_SCHEMA


@pytest.mark.integration
def test_installed_engine_executes_one_scenario(tmp_path):
    names = {
        "project": "RAS_WORKER_TEST_SOURCE_PROJECT",
        "plan": "RAS_WORKER_TEST_SOURCE_PLAN",
        "model_manifest": "RAS_WORKER_TEST_MODEL_MANIFEST",
        "hydrology": "RAS_WORKER_TEST_HYDROLOGY_DSS",
        "hydrology_manifest": "RAS_WORKER_TEST_HYDROLOGY_MANIFEST",
        "boundary_links": "RAS_WORKER_TEST_BOUNDARY_LINKS_JSON",
        "excess": "RAS_WORKER_TEST_EXCESS_DSS",
        "excess_manifest": "RAS_WORKER_TEST_EXCESS_MANIFEST",
        "excess_pathname": "RAS_WORKER_TEST_EXCESS_PATHNAME",
        "ras_executable": "RAS_WORKER_TEST_EXECUTABLE",
    }
    values = {key: os.environ.get(name) for key, name in names.items()}
    missing = [names[key] for key, value in values.items() if not value]
    if missing:
        pytest.skip(
            "Installed-engine worker inputs not configured: " + ", ".join(missing)
        )

    project = Path(values["project"])
    source_project = (
        project
        if project.is_file()
        else next(iter(sorted(project.glob("*.prj"))), None)
    )
    assert source_project is not None
    hydrology = Path(values["hydrology"])
    model_manifest = Path(values["model_manifest"])
    hydrology_manifest = Path(values["hydrology_manifest"])
    excess = Path(values["excess"])
    excess_manifest = Path(values["excess_manifest"])
    workspace = Path(
        os.environ.get("RAS_WORKER_TEST_WORKSPACE", str(tmp_path / "workspace"))
    )
    request = {
        "schema": RasScenarioWorker.REQUEST_SCHEMA,
        "scenario": {
            "scenario_id": "installed-engine-canary",
            "specification_sha256": "2" * 64,
        },
        "source_model": {
            "project": str(project),
            "project_file_sha256": _sha256(source_project),
            "template_plan": values["plan"],
            "model_manifest": str(model_manifest),
            "model_manifest_sha256": _sha256(model_manifest),
            "linked_asset_directories": json.loads(
                os.environ.get("RAS_WORKER_TEST_LINKED_ASSETS_JSON", "[]")
            ),
            "linked_asset_mode": os.environ.get(
                "RAS_WORKER_TEST_LINKED_ASSET_MODE", "copy"
            ),
        },
        "hydrology": {
            "dss": str(hydrology),
            "sha256": _sha256(hydrology),
            "product_manifest": str(hydrology_manifest),
            "product_manifest_sha256": _sha256(hydrology_manifest),
        },
        "boundary_links": json.loads(values["boundary_links"]),
        "forcing_excess": {
            "dss": str(excess),
            "sha256": _sha256(excess),
            "provenance_manifest": str(excess_manifest),
            "provenance_manifest_sha256": _sha256(excess_manifest),
            "pathname": values["excess_pathname"],
        },
        "model_window": {
            "start": os.environ.get("RAS_WORKER_TEST_START", "2019-09-18T13:00:00"),
            "end": os.environ.get("RAS_WORKER_TEST_END", "2019-09-22T13:00:00"),
            "time_zone": os.environ.get("RAS_WORKER_TEST_TIME_ZONE", "America/Chicago"),
        },
        "workspace": str(workspace),
        "products": {
            "directory": str(tmp_path / "products"),
            "include_preview": False,
        },
        "execution": {
            "ras_executable": values["ras_executable"],
            "timeout_seconds": int(
                os.environ.get("RAS_WORKER_TEST_TIMEOUT_SECONDS", "7200")
            ),
            "cores": int(os.environ.get("RAS_WORKER_TEST_CORES", "2")),
        },
    }
    prior_request = os.environ.get("RAS_WORKER_TEST_RETRY_REQUEST")
    prior_result = os.environ.get("RAS_WORKER_TEST_RETRY_RESULT")
    if bool(prior_request) != bool(prior_result):
        pytest.fail(
            "RAS_WORKER_TEST_RETRY_REQUEST and RAS_WORKER_TEST_RETRY_RESULT "
            "must be configured together"
        )
    if prior_request and prior_result:
        request["retry"] = {
            "prior_request": prior_request,
            "prior_result": prior_result,
        }
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ras_commander.RasScenarioWorker",
            "--request",
            str(request_path),
            "--result",
            str(result_path),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=request["execution"]["timeout_seconds"] + 120,
    )
    assert completed.returncode == 0, (
        "Installed RAS scenario worker failed.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert result["execution"]["hdf_completed_successfully"] is True
    assert all(result["preparation"]["checks"].values())
    assert Path(result["preparation"]["workspace"]["project_file"]).is_file()
