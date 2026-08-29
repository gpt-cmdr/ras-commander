from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

import pandas as pd
import psutil
import pyarrow
import pytest

import ras_commander
from ras_commander.ExecutionArtifacts import PlanExecutionCleanup
from ras_commander.ExecutionEvidence import (
    EXECUTION_OBSERVATION_NAMES,
    EvidenceObservation,
    ExecutionEvidence,
)
from scripts.qualification.execution_evidence import live_worker
from scripts.qualification.execution_evidence.locks import ExclusiveQualificationLock
from scripts.qualification.execution_evidence.planning import file_sha256
from scripts.qualification.execution_evidence.receipts import (
    read_json_with_digest,
    write_json_with_digest,
)
from scripts.qualification.execution_evidence.snapshots import snapshot_tree


HASH_A = "a" * 64
GIT_HEAD = "c" * 40
REQUIRED = ["R01", "R02", "R03", "R04", "R06", "R10", "R11", "R12"]


@dataclass(frozen=True)
class _PublicRecord:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class _FakeRasPrj:
    pass


def _project(root: Path) -> Path:
    root.mkdir()
    project = root / "Model.prj"
    project.write_text(
        "Proj Title=Live Qualification\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        "Plan Title=Base\n"
        "Program Version=7.00\n"
        "Short Identifier=Base\n"
        "Simulation Date=01JAN2020,0000,02JAN2020,2400\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.g01").write_text("Geom Title=Geometry\n", encoding="ascii")
    (root / "Model.f01").write_text("Flow Title=Flow\n", encoding="ascii")
    return project


def _request(
    tmp_path: Path,
    *,
    execution_api: str = "ras_cmdr",
) -> tuple[dict[str, Any], Any, Path]:
    run_root = tmp_path / "archive" / "run-1"
    attempt_dir = run_root / "attempts" / "lane-1" / "attempt-1"
    attempt_dir.mkdir(parents=True)
    execution_root = tmp_path / "execution" / "run-1"
    (execution_root / "lane-1" / "attempt-1").mkdir(parents=True)
    source_project = _project(tmp_path / "source")
    source_snapshot = snapshot_tree(
        source_project.parent,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase="request_source",
        root_kind="source",
        data_origin="captured_real",
        known_paths=("Model.p01.hdf", "Model.O01"),
    )
    engine_file = tmp_path / "engine" / "Ras.exe"
    engine_file.parent.mkdir()
    engine_file.write_bytes(b"never executed by this test")
    if execution_api == "ras_cmdr":
        engine = {
            "engine_id": "ras-7",
            "execution_api": "ras_cmdr",
            "version_requested": "7.0",
            "expected_result_format": "hdf",
            "support_state": "supported",
            "executable": str(engine_file),
            "executable_sha256": file_sha256(engine_file),
        }
    else:
        engine = {
            "engine_id": "ras-4",
            "execution_api": "ras_control",
            "version_requested": "4.1.0",
            "expected_result_format": "legacy",
            "support_state": "supported",
            "controller_version": "4.1.0",
            "resolved_controller_version": "4.1",
            "controller_progid": "RAS41.HECRASController",
            "controller_executable": str(engine_file),
            "controller_executable_sha256": file_sha256(engine_file),
            "blocking": False,
        }
    fixture = {
        "fixture_id": "fixture-1",
        "source_kind": "project_file",
        "source_project": str(source_project),
        "source_immutable": True,
        "source_content_fingerprint_algorithm": (
            source_snapshot.fingerprint_algorithm
        ),
        "source_content_fingerprint": source_snapshot.content_fingerprint,
        "data_origin": "captured_real",
        "plan_number": "01",
        "plan_title": "Base",
        "plan_type": "steady_1d",
    }
    lane = {
        "lane_id": "lane-1",
        "fixture_id": "fixture-1",
        "engine_id": engine["engine_id"],
        "initial_state": "neither",
        "expected_terminal_category": "passed",
        "required_invariants": REQUIRED,
        "tags": ["real_ras"],
    }
    context = SimpleNamespace(
        run_root=run_root,
        descriptor={"execution_run_root": str(execution_root)},
    )
    lock = ExclusiveQualificationLock(
        tmp_path / "real-engine.lock",
        kind="real_engine",
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        git_head=GIT_HEAD,
    )
    lock_payload = lock.acquire()
    request = {
        "schema_version": 1,
        "action": "run",
        "run_id": "run-1",
        "lane_id": "lane-1",
        "attempt_id": "attempt-1",
        "manifest_sha256": HASH_A,
        "git_head": GIT_HEAD,
        "repository_root": str(Path(__file__).resolve().parents[2]),
        "python_executable": str(Path(__import__("sys").executable).resolve()),
        "python_executable_sha256": file_sha256(__import__("sys").executable),
        "python_version": platform.python_version(),
        "pyarrow_version": pyarrow.__version__,
        "psutil_version": psutil.__version__,
        "ras_commander_version": str(ras_commander.__version__),
        "ras_commander_import_path": str(Path(ras_commander.__file__).resolve()),
        "run_descriptor_sha256": "b" * 64,
        "normalized_manifest_path": str(run_root / "manifest.normalized.json"),
        "normalized_manifest_sha256": "d" * 64,
        "lane": lane,
        "fixture": fixture,
        "engine": engine,
        "required_invariants": REQUIRED,
        "source_project": str(source_project),
        "source_snapshot_content_fingerprint_algorithm": (
            source_snapshot.fingerprint_algorithm
        ),
        "source_snapshot_content_fingerprint": source_snapshot.content_fingerprint,
        "source_snapshot_metadata_fingerprint": source_snapshot.metadata_fingerprint,
        "stage_root": str(execution_root / "lane-1" / "attempt-1" / "stage"),
        "timeout_seconds": 30,
        "termination_grace_seconds": 0.01,
        "hash_files": True,
        "process_baseline": [],
        "process_baseline_evidence": {
            "observed_at": 1.0,
            "complete": True,
            "processes": [],
            "query_errors": [],
        },
        "real_engine_lock": {
            "path": str(lock.path),
            "token": lock_payload["token"],
            "run_id": "run-1",
            "lane_id": "lane-1",
            "attempt_id": "attempt-1",
        },
        "worker_launch": {
            "launch_nonce": str(uuid.uuid4()),
            "intent_path": str(attempt_dir / "worker-launch-intent.json"),
            "hello_path": str(attempt_dir / "worker-hello.json"),
            "authorization_path": str(
                attempt_dir / "worker-authorization.json"
            ),
        },
        "hec_ras_execution_enabled": True,
    }
    return request, context, lock


def _inventory(*, plan: bool, project: Path | None = None) -> _PublicRecord:
    payload: dict[str, Any] = {
        "observed_at": 1.0,
        "complete": True,
        "query_errors": [],
    }
    if plan:
        assert project is not None
        payload.update(
            {
                "plan_number": "01",
                "project_path": str(project),
                "plan_path": str(project.parent / "Model.p01"),
                "tmp_hdf_path": None,
                "matched": [],
            }
        )
    else:
        payload["processes"] = []
    return _PublicRecord(payload)


def _observation(
    *,
    channel: str,
    value: Any = None,
    locator: str | None = None,
    reason: str = "not_available_in_test_fixture",
) -> EvidenceObservation[Any]:
    now = datetime.now(timezone.utc)
    if value is None:
        return EvidenceObservation(
            state="not_available_in_version",
            value=None,
            channel=channel,
            source_locator=locator,
            source_sha256=None,
            observed_program_version=None,
            inspected_at=now,
            reason_code=reason,
        )
    return EvidenceObservation(
        state="available",
        value=value,
        channel=channel,
        source_locator=locator,
        source_sha256=None,
        observed_program_version=None,
        inspected_at=now,
    )


def _evidence(project: Path, *, result_format: str) -> ExecutionEvidence:
    now = datetime.now(timezone.utc)
    result = (
        project.parent / "Model.p01.hdf"
        if result_format == "hdf"
        else project.parent / "Model.O01"
    )
    message_channel = "hdf" if result_format == "hdf" else "stored_message"
    structural_channel = "hdf" if result_format == "hdf" else "legacy_output"
    channels = {
        "result_artifact_exists": "filesystem",
        "result_artifact_modified_at": "filesystem",
        "result_artifact_modified_after_threshold": "filesystem",
        "result_artifact_structural_state": structural_channel,
        "producer_program_version": message_channel,
        "completion_attribute": "hdf",
        "completion_message_hdf": "hdf",
        "completion_message_stored": "stored_message",
        "message_error_count": message_channel,
        "message_warning_count": message_channel,
        "message_first_error": message_channel,
        "runtime_seconds": message_channel,
        "simulation_start": "filesystem",
        "simulation_end": "filesystem",
        "process_success": "process",
        "com_completion": "com",
    }
    values: dict[str, Any] = {
        "result_artifact_exists": True,
        "result_artifact_modified_at": now,
        "result_artifact_modified_after_threshold": True,
        "result_artifact_structural_state": "readable",
        "producer_program_version": "7.0" if result_format == "hdf" else "4.1",
        "message_error_count": 0,
        "message_warning_count": 0,
        "runtime_seconds": 1.0,
        "simulation_start": datetime(2020, 1, 1),
        "simulation_end": datetime(2020, 1, 3),
        "process_success": True,
    }
    if result_format == "hdf":
        values["completion_attribute"] = True
        values["completion_message_hdf"] = True
    else:
        values["completion_message_stored"] = True
        values["com_completion"] = True
    observations = {
        name: _observation(
            channel=channels[name],
            value=values.get(name),
            locator=str(result) if name == "result_artifact_exists" else None,
        )
        for name in EXECUTION_OBSERVATION_NAMES
    }
    mechanical = _observation(channel="derived", value=True)
    return ExecutionEvidence(
        schema_version=1,
        evidence_id="evidence-1",
        inspected_at=now,
        project_file=project,
        plan_file=project.parent / "Model.p01",
        plan_number="01",
        declared_program_version="7.00" if result_format == "hdf" else "4.10",
        mechanical_completion=mechanical,
        observations=observations,
        conflicts=(),
    )


def _install_public_api_fakes(
    monkeypatch: pytest.MonkeyPatch,
    request: dict[str, Any],
    *,
    invalid_details: bool = False,
) -> dict[str, Any]:
    calls: dict[str, Any] = {
        "compute": [],
        "control": [],
        "cleanup": [],
        "inspection": 0,
        "global_inventory": 0,
        "plan_inventory": 0,
        "tcu_status": [],
    }

    def tcu_status(*, ras_version: str) -> Any:
        calls["tcu_status"].append(ras_version)
        executable = request["engine"].get("executable") or request["engine"].get(
            "controller_executable"
        )
        install_dir = (
            str(Path(executable).parent)
            if executable
            else None
        )
        return SimpleNamespace(
            accepted=True,
            version=ras_version,
            install_dir=install_dir,
            registry_key=f"test-registry/{install_dir}",
            reason="accepted",
        )

    def forbidden_tcu_mutation(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the live worker must never mutate TCU acceptance")

    def fake_init(project_file: str | Path, **kwargs: Any) -> Any:
        project = Path(project_file)
        assert isinstance(kwargs["ras_object"], _FakeRasPrj)
        assert kwargs["load_results_summary"] is False
        assert kwargs["load_hdf_metadata"] is False
        assert kwargs["hide_intro"] is True
        return SimpleNamespace(
            prj_file=project,
            project_folder=project.parent,
            project_name=project.stem,
            ras_version=request["engine"]["version_requested"],
            ras_exe_path=request["engine"].get("executable"),
        )

    def inspect_global() -> _PublicRecord:
        calls["global_inventory"] += 1
        return _inventory(plan=False)

    def inspect_plan(plan_number: str, *, ras_object: Any) -> _PublicRecord:
        calls["plan_inventory"] += 1
        assert plan_number == "01"
        return _inventory(plan=True, project=ras_object.prj_file)

    def cleanup(plan_number: str, **kwargs: Any) -> PlanExecutionCleanup:
        calls["cleanup"].append((plan_number, kwargs))
        root = kwargs["ras_object"].project_folder
        requested = kwargs["result_format"]
        candidates = []
        if requested in {"hdf", "both"}:
            candidates.append(root / "Model.p01.hdf")
        if requested in {"legacy", "both"}:
            candidates.append(root / "Model.O01")
        if kwargs["include_message_sidecars"]:
            candidates.extend(
                [
                    root / "Model.p01.comp_msgs.txt",
                    root / "Model.p01.computeMsgs.txt",
                    root / "Model.bco01",
                ]
            )
        return PlanExecutionCleanup(
            plan_number="01",
            result_format=requested,
            include_message_sidecars=kwargs["include_message_sidecars"],
            removed_paths=(),
            missing_paths=tuple(candidates),
        )

    def inspect_evidence(plan_number: str, *, ras_object: Any, hash_files: bool) -> Any:
        calls["inspection"] += 1
        assert plan_number == "01"
        assert hash_files is True
        return _evidence(
            ras_object.prj_file,
            result_format=request["engine"]["expected_result_format"],
        )

    def compute(plan_number: str, **kwargs: Any) -> Any:
        calls["compute"].append((plan_number, kwargs))
        project = kwargs["ras_object"].prj_file
        (project.parent / "Model.p01.hdf").write_bytes(b"fake modern result")
        details = {
            "execution_api": "ras_cmdr",
            "calculation_attempted": True,
            "selected_result_format": "hdf",
            "solver_quiescence_confirmed": True,
            "result_artifacts_finalized": True,
            "engine_kind": "executable",
            "selected_executable_path": request["engine"].get("executable"),
            "selected_executable_sha256": request["engine"].get("executable_sha256"),
            "launcher_pid": 2468,
            "launcher_create_time": 12345.0,
            "actual_engine_provenance_confirmed": True,
            "compute_mode": "subprocess",
        }
        if invalid_details:
            details.pop("solver_quiescence_confirmed")
        return SimpleNamespace(
            success=True,
            completion_verified=True,
            execution_details=details,
        )

    def run_control(plan_number: str, **kwargs: Any) -> Any:
        calls["control"].append((plan_number, kwargs))
        project = kwargs["ras_object"].prj_file
        (project.parent / "Model.O01").write_bytes(b"fake legacy result")
        return SimpleNamespace(
            success=True,
            messages=["Complete Process", "No errors"],
            execution_details={
                "execution_api": "ras_control",
                "calculation_attempted": True,
                "selected_result_format": "legacy",
                "solver_quiescence_confirmed": True,
                "result_artifacts_finalized": True,
                "engine_kind": "controller",
                "requested_controller_version": request["engine"][
                    "controller_version"
                ],
                "controller_progid": "RAS41.HECRASController",
                "resolved_controller_version": "4.1",
                "controller_executable_path": request["engine"][
                    "controller_executable"
                ],
                "controller_executable_sha256": request["engine"][
                    "controller_executable_sha256"
                ],
                "controller_pid": 2468,
                "controller_create_time": 12345.0,
                "watchdog_requested": True,
                "watchdog_started": True,
                "strict_close_requested": True,
                "max_runtime_seconds": request["timeout_seconds"],
                "controller_close_safe": True,
                "owned_process_exit_confirmed": True,
                "post_close_plan_processes_quiescent": True,
                "post_close_global_processes_quiescent": True,
                "actual_engine_provenance_confirmed": True,
                "compute_mode": "poll",
            },
        )

    monkeypatch.setattr(ras_commander, "RasPrj", _FakeRasPrj)
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "status",
        staticmethod(tcu_status),
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "accept",
        staticmethod(forbidden_tcu_mutation),
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "open_gui",
        staticmethod(forbidden_tcu_mutation),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasTcu,
        "open_gui_to_accept",
        staticmethod(forbidden_tcu_mutation),
    )
    monkeypatch.setattr(ras_commander, "init_ras_project", fake_init)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        staticmethod(inspect_global),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_plan_processes",
        staticmethod(inspect_plan),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "cancel_plan_exact",
        staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("not called"))),
        raising=False,
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "remove_plan_execution_artifacts",
        staticmethod(cleanup),
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_execution_evidence",
        staticmethod(inspect_evidence),
    )
    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "compute_plan",
        staticmethod(compute),
    )
    monkeypatch.setattr(
        ras_commander.RasControl,
        "run_plan",
        staticmethod(run_control),
    )
    return calls


def test_modern_live_attempt_uses_only_public_apis_and_publishes_worker_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 0
    assert calls["compute"]
    assert calls["control"] == []
    _, kwargs = calls["compute"][0]
    assert kwargs == {
        "ras_object": kwargs["ras_object"],
        "force_rerun": True,
        "skip_existing": False,
        "verify": True,
        "dialog_watchdog": True,
    }
    assert calls["global_inventory"] == 3
    assert calls["plan_inventory"] == 2
    assert calls["cleanup"][0][1]["result_format"] == "both"
    assert calls["tcu_status"] == [request["engine"]["executable"]]
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert not (attempt / "receipt.json").exists()
    assert receipt["hec_ras_invoked"] is True
    assert receipt["terminal_category"] == "passed"
    assert receipt["worker_exit_code"] == 0
    assert {row["invariant_id"] for row in receipt["tables"]["invariants"]} == set(
        REQUIRED
    )
    assert all(row["status"] == "pass" for row in receipt["tables"]["invariants"])
    assert all(
        item["relative_path"] not in {"stdout.log", "stderr.log"}
        for item in receipt["referenced_artifacts"]
    )
    assert receipt["tcu_status"] == {
        "accepted": True,
        "install_dir": str(Path(request["engine"]["executable"]).parent),
        "ras_version_argument": request["engine"]["executable"],
        "reason": "accepted",
        "registry_key": (
            "test-registry/" + str(Path(request["engine"]["executable"]).parent)
        ),
        "version": request["engine"]["executable"],
    }
    tcu_events = [
        row
        for row in receipt["tables"]["events"]
        if row["event_name"] == "tcu_acceptance_preflight_passed"
    ]
    assert len(tcu_events) == 1
    assert json.loads(tcu_events[0]["payload_json"])["tcu_status"]["accepted"] is True
    final_hdf = [
        row
        for row in receipt["tables"]["artifacts"]
        if row["phase"] == "post_evidence_inspection"
        and row["relative_path"] == "Model.p01.hdf"
    ][0]
    assert final_hdf["data_origin"] == "staged_execution_output"


@pytest.mark.parametrize("asset_kind", ["dss_file", "gridded_dataset", "terrain"])
def test_required_external_linked_asset_stops_before_cleanup_or_compute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    asset_kind: str,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    public_stage_project = ras_commander.stage_project

    def stage_with_external_asset(*args: Any, **kwargs: Any) -> Any:
        result = public_stage_project(*args, **kwargs)
        assets = result.assets.copy()
        row_index = assets.index[assets["required"].eq(True)][0]  # noqa: E712
        external_path = tmp_path / "external-library" / f"{asset_kind}.dat"
        assets.loc[row_index, "asset_kind"] = asset_kind
        assets.loc[row_index, "reference_raw"] = str(external_path)
        assets.loc[row_index, "resolved_path"] = str(external_path)
        assets.loc[row_index, "path_scope"] = "external"
        assets.loc[row_index, "portable"] = False
        assert str(assets["required"].dtype) == "bool[pyarrow]"
        assert str(assets["path_scope"].dtype) == "string[pyarrow]"
        return replace(result, assets=assets)

    monkeypatch.setattr(ras_commander, "stage_project", stage_with_external_asset)
    try:
        with pytest.raises(
            live_worker.LiveAssetGateError,
            match="external_execution_asset",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert calls["inspection"] == 0
    events_path = (
        context.run_root
        / "attempts"
        / "lane-1"
        / "attempt-1"
        / "events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    rejection = [
        event
        for event in events
        if event["event_name"] == "stage_asset_gate_rejected"
    ]
    assert len(rejection) == 1
    assert rejection[0]["reason_code"] == "external_execution_asset"
    assert rejection[0]["severity"] == "error"
    payload = json.loads(rejection[0]["payload_json"])
    assert payload["findings"][0]["asset_kind"] == asset_kind


def test_internal_pyarrow_asset_inventory_passes_live_gate(tmp_path: Path) -> None:
    source_project = _project(tmp_path / "source")
    staged = ras_commander.stage_project(source_project, tmp_path / "stage")

    result = live_worker._require_live_stage_assets_safe(
        staged.assets,
        stage_root=staged.destination_root,
    )

    assert result["asset_count"] == len(staged.assets)
    assert result["required_asset_count"] == 4
    assert result["external_execution_asset_count"] == 0
    assert all(
        isinstance(staged.assets[column].dtype, pd.ArrowDtype)
        for column in live_worker._LIVE_ASSET_GATE_COLUMNS
    )


def test_non_pyarrow_stage_asset_gate_dtype_stops_before_compute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    public_stage_project = ras_commander.stage_project

    def stage_with_object_dtype(*args: Any, **kwargs: Any) -> Any:
        result = public_stage_project(*args, **kwargs)
        assets = result.assets.copy()
        assets["path_scope"] = assets["path_scope"].astype("object")
        return replace(result, assets=assets)

    monkeypatch.setattr(ras_commander, "stage_project", stage_with_object_dtype)
    try:
        with pytest.raises(live_worker.LiveCapabilityError, match="PyArrow-backed"):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []


def test_controller_live_attempt_uses_exact_controller_route_and_externalizes_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path, execution_api="ras_control")
    calls = _install_public_api_fakes(monkeypatch, request)
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 0
    assert calls["compute"] == []
    assert len(calls["control"]) == 1
    _, kwargs = calls["control"][0]
    assert kwargs["force_recompute"] is True
    assert kwargs["use_watchdog"] is True
    assert kwargs["max_runtime"] == 30
    assert kwargs["refresh_results"] is False
    assert kwargs["blocking"] is False
    assert kwargs["controller_version"] == "4.1.0"
    assert kwargs["strict_close"] is True
    assert calls["tcu_status"] == ["4.1.0"]
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert (attempt / "messages.txt").read_text(encoding="utf-8").find(
        "Complete Process"
    ) >= 0
    assert "Complete Process" not in json.dumps(receipt)
    assert receipt["execution_result"]["message_count"] == 2
    assert receipt["tables"]["lanes"][0]["controller_progid"] == (
        "RAS41.HECRASController"
    )


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        (False, "no-vb6-subtree"),
        (None, "version-unresolved"),
    ],
)
def test_tcu_acceptance_not_confirmed_stops_before_staging_or_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool | None,
    reason: str,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    stage_called = False

    def status(*, ras_version: str) -> Any:
        calls["tcu_status"].append(ras_version)
        return SimpleNamespace(
            accepted=accepted,
            version=ras_version,
            install_dir=str(Path(request["engine"]["executable"]).parent),
            registry_key="test-registry/tcu",
            reason=reason,
        )

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander.RasTcu, "status", staticmethod(status))
    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    try:
        with pytest.raises(
            live_worker.LiveTcuGateError,
            match="TCU acceptance was not confirmed",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert calls["tcu_status"] == [request["engine"]["executable"]]
    assert stage_called is False
    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert not Path(request["stage_root"]).exists()
    events_path = (
        context.run_root
        / "attempts"
        / "lane-1"
        / "attempt-1"
        / "events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    rejected = [
        event
        for event in events
        if event["event_name"] == "tcu_acceptance_preflight_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "tcu_acceptance_not_confirmed"
    payload = json.loads(rejected[0]["payload_json"])["tcu_status"]
    assert payload["accepted"] is accepted
    assert payload["reason"] == reason
    assert payload["ras_version_argument"] == request["engine"]["executable"]


def test_qualification_manifest_pin_mismatch_stops_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request)
    request["fixture"]["source_content_fingerprint"] = "0" * 64
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="qualification source fingerprint gate failed before staging",
        ):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert calls["cleanup"] == []
    assert calls["compute"] == []
    assert calls["control"] == []
    assert not Path(request["stage_root"]).exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("execution_api", "ras_cmdr"),
        ("actual_engine_provenance_confirmed", False),
        ("requested_controller_version", "4.0"),
        ("compute_mode", "blocking"),
        ("watchdog_requested", False),
        ("watchdog_started", False),
        ("strict_close_requested", False),
        ("max_runtime_seconds", 31),
        ("controller_executable_sha256", "0" * 64),
        ("controller_pid", None),
        ("controller_create_time", 0),
        ("post_close_plan_processes_quiescent", False),
        ("post_close_global_processes_quiescent", False),
    ],
)
def test_controller_live_result_requires_exact_execution_contract(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    details = {
        "execution_api": "ras_control",
        "calculation_attempted": True,
        "selected_result_format": "legacy",
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "engine_kind": "controller",
        "requested_controller_version": "4.1.0",
        "controller_progid": "RAS41.HECRASController",
        "resolved_controller_version": "4.1",
        "controller_executable_path": request["engine"][
            "controller_executable"
        ],
        "controller_executable_sha256": request["engine"][
            "controller_executable_sha256"
        ],
        "controller_pid": 2468,
        "controller_create_time": 12345.0,
        "compute_mode": "poll",
        "watchdog_requested": True,
        "watchdog_started": True,
        "strict_close_requested": True,
        "max_runtime_seconds": 30,
        "controller_close_safe": True,
        "owned_process_exit_confirmed": True,
        "post_close_plan_processes_quiescent": True,
        "post_close_global_processes_quiescent": True,
        "actual_engine_provenance_confirmed": True,
    }
    details[field] = invalid_value
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(live_worker.LiveWorkerError):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


def test_controller_live_result_rejects_forged_executable_path(
    tmp_path: Path,
) -> None:
    request, _, lock = _request(tmp_path, execution_api="ras_control")
    forged = tmp_path / "forged" / "Ras.exe"
    forged.parent.mkdir()
    forged.write_bytes(b"different Controller image")
    details = {
        "execution_api": "ras_control",
        "calculation_attempted": True,
        "selected_result_format": "legacy",
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "engine_kind": "controller",
        "requested_controller_version": "4.1.0",
        "controller_progid": "RAS41.HECRASController",
        "resolved_controller_version": "4.1",
        "controller_executable_path": str(forged),
        "controller_executable_sha256": request["engine"][
            "controller_executable_sha256"
        ],
        "controller_pid": 2468,
        "controller_create_time": 12345.0,
        "compute_mode": "poll",
        "watchdog_requested": True,
        "watchdog_started": True,
        "strict_close_requested": True,
        "max_runtime_seconds": 30,
        "controller_close_safe": True,
        "owned_process_exit_confirmed": True,
        "post_close_plan_processes_quiescent": True,
        "post_close_global_processes_quiescent": True,
        "actual_engine_provenance_confirmed": True,
    }
    result = SimpleNamespace(success=True, messages=[], execution_details=details)
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="executable path mismatch",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("launcher_pid", None),
        ("launcher_pid", True),
        ("launcher_create_time", 0),
        ("launcher_create_time", float("nan")),
    ],
)
def test_modern_live_result_requires_exact_launcher_identity(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    request, _, lock = _request(tmp_path)
    details = {
        "execution_api": "ras_cmdr",
        "engine_kind": "executable",
        "calculation_attempted": True,
        "selected_result_format": "hdf",
        "solver_quiescence_confirmed": True,
        "result_artifacts_finalized": True,
        "actual_engine_provenance_confirmed": True,
        "selected_executable_path": request["engine"]["executable"],
        "selected_executable_sha256": request["engine"]["executable_sha256"],
        "launcher_pid": 2468,
        "launcher_create_time": 12345.0,
    }
    details[field] = invalid_value
    result = SimpleNamespace(
        success=True,
        completion_verified=True,
        execution_details=details,
    )
    try:
        with pytest.raises(
            live_worker.LiveCapabilityError,
            match="launcher PID/create-time",
        ):
            live_worker._validate_execution_result(request, result)
    finally:
        lock.release()


def test_missing_structured_process_capability_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        None,
        raising=False,
    )
    try:
        with pytest.raises(live_worker.LiveCapabilityError):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert not Path(request["stage_root"]).exists()
    assert not (
        context.run_root / "attempts" / "lane-1" / "attempt-1" / "worker_receipt.json"
    ).exists()


def test_incomplete_global_inventory_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)
    stage_called = False

    def forbidden_stage(*args: Any, **kwargs: Any) -> Any:
        nonlocal stage_called
        stage_called = True
        raise AssertionError("stage_project must not be reached")

    monkeypatch.setattr(ras_commander, "stage_project", forbidden_stage)
    monkeypatch.setattr(
        ras_commander.RasControl,
        "inspect_processes",
        staticmethod(
            lambda: _PublicRecord(
                {
                    "observed_at": 1.0,
                    "complete": False,
                    "processes": [],
                    "query_errors": [
                        {
                            "pid": None,
                            "operation": "enumerate_processes",
                            "reason_code": "access_denied",
                            "exception_type": "AccessDenied",
                            "detail": "test uncertainty",
                        }
                    ],
                }
            )
        ),
    )
    try:
        with pytest.raises(live_worker.LiveProcessGateError, match="incomplete"):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert stage_called is False
    assert not Path(request["stage_root"]).exists()


def test_incomplete_execution_details_quarantine_before_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    calls = _install_public_api_fakes(monkeypatch, request, invalid_details=True)
    try:
        with pytest.raises(live_worker.LiveCapabilityError):
            live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert len(calls["compute"]) == 1
    assert calls["inspection"] == 0
    assert not (
        context.run_root / "attempts" / "lane-1" / "attempt-1" / "worker_receipt.json"
    ).exists()


def test_required_invariant_failure_publishes_coherent_nonzero_worker_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)

    def conflicting_evidence(
        plan_number: str,
        *,
        ras_object: Any,
        hash_files: bool,
    ) -> ExecutionEvidence:
        assert plan_number == "01"
        assert hash_files is True
        return _evidence(ras_object.prj_file, result_format="legacy")

    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "inspect_execution_evidence",
        staticmethod(conflicting_evidence),
    )
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 20
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert receipt["terminal_category"] == "failed_invariant"
    assert receipt["worker_exit_code"] == 20
    rows = {row["invariant_id"]: row for row in receipt["tables"]["invariants"]}
    assert rows["R02"]["status"] == "fail"
    assert receipt["tables"]["lanes"][0]["all_invariants_passed"] is False


def test_unsuccessful_calculation_cannot_publish_a_passing_live_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, context, lock = _request(tmp_path)
    _install_public_api_fakes(monkeypatch, request)

    def unsuccessful_compute(plan_number: str, **kwargs: Any) -> Any:
        assert plan_number == "01"
        project = kwargs["ras_object"].prj_file
        (project.parent / "Model.p01.hdf").write_bytes(b"failed calculation result")
        return SimpleNamespace(
            success=False,
            completion_verified=True,
            execution_details={
                "execution_api": "ras_cmdr",
                "calculation_attempted": True,
                "selected_result_format": "hdf",
                "solver_quiescence_confirmed": True,
                "result_artifacts_finalized": True,
                "engine_kind": "executable",
                "selected_executable_path": request["engine"]["executable"],
                "selected_executable_sha256": request["engine"][
                    "executable_sha256"
                ],
                "launcher_pid": 2468,
                "launcher_create_time": 12345.0,
                "actual_engine_provenance_confirmed": True,
                "compute_mode": "subprocess",
            },
        )

    monkeypatch.setattr(
        ras_commander.RasCmdr,
        "compute_plan",
        staticmethod(unsuccessful_compute),
    )
    try:
        exit_code = live_worker._perform(request, "e" * 64, context)
    finally:
        lock.release()

    assert exit_code == 20
    attempt = context.run_root / "attempts" / "lane-1" / "attempt-1"
    receipt, _ = read_json_with_digest(attempt / "worker_receipt.json")
    assert receipt["terminal_category"] == "execution_failed"
    assert receipt["tables"]["lanes"][0]["process_success"] is False


def test_main_rejects_tampered_digest_before_live_imports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_path = tmp_path / "request.json"
    write_json_with_digest(request_path, {"schema_version": 1, "action": "run"})
    request_path.write_text('{"schema_version":1,"action":"run","tampered":true}\n')

    assert live_worker.main(["--request", str(request_path)]) == 31
    assert "digest mismatch" in capsys.readouterr().err


def _write_worker_launch_intent(
    request: dict[str, Any],
    request_sha256: str,
) -> str:
    launch = request["worker_launch"]
    intent = {
        "schema_version": 1,
        "action": "launch_live_worker",
        "created_at": "2026-08-28T12:00:00+00:00",
        "request_sha256": request_sha256,
        "launch_nonce": launch["launch_nonce"],
        "run_id": request["run_id"],
        "lane_id": request["lane_id"],
        "attempt_id": request["attempt_id"],
        "real_engine_lock_token": request["real_engine_lock"]["token"],
        "supervisor_pid": os.getpid(),
    }
    return write_json_with_digest(launch["intent_path"], intent)


def test_worker_missing_parent_authorization_stops_before_staging(
    tmp_path: Path,
) -> None:
    request, _context_value, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    request_path = attempt_dir / "request.json"
    request_sha256 = write_json_with_digest(request_path, request)
    _write_worker_launch_intent(request, request_sha256)
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="did not authorize this exact worker identity",
        ):
            live_worker._register_and_verify_worker_authorization(
                request_path,
                request["worker_launch"]["launch_nonce"],
            )
    finally:
        lock.release()

    assert Path(request["worker_launch"]["hello_path"]).is_file()
    assert not Path(request["stage_root"]).exists()
    assert not (attempt_dir / "worker_receipt.json").exists()


def test_worker_tampered_parent_authorization_stops_before_staging(
    tmp_path: Path,
) -> None:
    request, _context_value, lock = _request(tmp_path)
    attempt_dir = Path(request["worker_launch"]["intent_path"]).parent
    request_path = attempt_dir / "request.json"
    request_sha256 = write_json_with_digest(request_path, request)
    _write_worker_launch_intent(request, request_sha256)
    write_json_with_digest(
        request["worker_launch"]["authorization_path"],
        {
            "schema_version": 1,
            "action": "authorize_live_worker",
            "request_sha256": "0" * 64,
        },
    )
    try:
        with pytest.raises(
            live_worker.LiveWorkerError,
            match="authorization mismatch for request_sha256",
        ):
            live_worker._register_and_verify_worker_authorization(
                request_path,
                request["worker_launch"]["launch_nonce"],
            )
    finally:
        lock.release()

    assert not Path(request["stage_root"]).exists()
    assert not (attempt_dir / "worker_receipt.json").exists()


def test_live_worker_contains_no_raw_process_or_filesystem_deletion_escape_hatch() -> None:
    source = Path(live_worker.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "psutil.process_iter" not in source
    assert ".terminate(" not in source
    assert ".kill(" not in source
    assert ".unlink(" not in source
    assert "taskkill" not in source.casefold()
    assert "stop-process" not in source.casefold()
    assert "Popen(" not in source
