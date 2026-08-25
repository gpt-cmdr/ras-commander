"""Tests for version-aware, read-only execution evidence inspection."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

import ras_commander
from ras_commander import (
    EXECUTION_OBSERVATION_NAMES,
    EvidenceObservation,
    ExecutionEvidence,
    RasCmdr,
    RasControl,
)


class _RasObject:
    def __init__(self, project_file: Path, version: str) -> None:
        self.initialized = True
        self.prj_file = project_file
        self.project_folder = project_file.parent
        self.project_name = project_file.stem
        self.ras_version = version
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "Plan Title": "Base",
                    "Program Version": version,
                    "Simulation Date": (
                        "01JAN2020,0000,02JAN2020,0000"
                    ),
                    "full_path": str(project_file.parent / f"{project_file.stem}.p01"),
                }
            ]
        )

    def check_initialized(self) -> None:
        if not self.initialized:
            raise RuntimeError("not initialized")


def _write_project(root: Path, *, version: str) -> tuple[Path, _RasObject]:
    root.mkdir()
    project = root / "Model.prj"
    project.write_text(
        "Proj Title=Evidence Test\n"
        "Current Plan=p01\n"
        "Plan File=p01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        "Plan Title=Base\n"
        f"Program Version={version}\n"
        "Simulation Date=01JAN2020,0000,02JAN2020,0000\n"
        "Geom File=g01\n"
        "Flow File=u01\n",
        encoding="ascii",
    )
    return project, _RasObject(project, version)


def _write_hdf(
    root: Path,
    *,
    file_version: str,
    messages: str | None,
    completion_attribute: object = None,
    compute_times_ms: list[float] | None = None,
    explicit_window: bool = True,
) -> Path:
    path = root / "Model.p01.hdf"
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["File Version"] = file_version
        plan_info = hdf_file.require_group("Plan Data/Plan Information")
        if explicit_window:
            plan_info.attrs["Simulation Start Time"] = "01Jan2020 00:00:00"
            plan_info.attrs["Simulation End Time"] = "02Jan2020 00:00:00"
        else:
            plan_info.attrs["Time Window"] = (
                "01Jan2020 00:00:00 to 02Jan2020 00:00:00"
            )
        if completion_attribute is not None:
            event = hdf_file.require_group("Event Conditions")
            event.attrs["Completed Successfully"] = completion_attribute
        if messages is not None:
            hdf_file.require_group("Results/Summary").create_dataset(
                "Compute Messages (text)",
                data=np.bytes_(messages.encode("utf-8")),
            )
        if compute_times_ms is not None:
            processes = hdf_file.require_group(
                "Results/Summary/Compute Processes"
            )
            processes.create_dataset(
                "Compute Time (ms)",
                data=np.asarray(compute_times_ms, dtype=float),
            )
    return path


def test_public_contract_exports_fixed_registry() -> None:
    assert hasattr(RasCmdr, "inspect_execution_evidence")
    assert ras_commander.ExecutionEvidence is ExecutionEvidence
    assert ras_commander.EvidenceObservation is EvidenceObservation
    assert len(EXECUTION_OBSERVATION_NAMES) == len(
        set(EXECUTION_OBSERVATION_NAMES)
    )
    assert "completion_message_hdf" in EXECUTION_OBSERVATION_NAMES
    assert "completion_message_stored" in EXECUTION_OBSERVATION_NAMES
    assert "mechanical_completion" not in EXECUTION_OBSERVATION_NAMES


def test_available_observation_requires_a_value() -> None:
    with pytest.raises(ValueError, match="must contain a value"):
        EvidenceObservation(
            state="available",
            value=None,
            channel="hdf",
            source_locator=None,
            source_sha256=None,
            observed_program_version=None,
            inspected_at=datetime.now(timezone.utc),
        )


def test_modern_hdf_keeps_completion_separate_from_message_errors(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "modern", version="6.60")
    hdf_path = _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Error: stored map failed\nComplete Process\t1:29\n",
        completion_attribute=True,
        compute_times_ms=[1000.0, 2500.0],
    )

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        hash_files=True,
    )

    assert evidence.mechanical_completion.state == "available"
    assert evidence.mechanical_completion.value is True
    assert evidence.conflicts == ()
    assert evidence.observations["completion_attribute"].value is True
    assert evidence.observations["completion_message_hdf"].value is True
    assert evidence.observations["result_artifact_structural_state"].value == (
        "plan_information_present"
    )
    assert evidence.observations["completion_attribute"].source_sha256 == (
        hashlib.sha256(hdf_path.read_bytes()).hexdigest()
    )
    assert evidence.observations["message_error_count"].value == 1
    assert evidence.observations["runtime_seconds"].value == 3.5
    assert evidence.observations["runtime_seconds"].channel == "hdf"
    assert evidence.observations["producer_program_version"].value == (
        "HEC-RAS 6.6"
    )
    assert evidence.observations["process_success"].state == "not_inspected"
    assert evidence.observations["com_completion"].state == "not_inspected"
    assert evidence.observations["simulation_start"].value == datetime(
        2020, 1, 1
    )


def test_conflicting_completion_sources_fail_closed(tmp_path: Path) -> None:
    _, ras_object = _write_project(tmp_path / "conflict", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute=False,
    )

    evidence = RasCmdr.inspect_execution_evidence(1, ras_object=ras_object)

    assert evidence.observations["completion_attribute"].value is False
    assert evidence.observations["completion_message_hdf"].value is True
    assert evidence.mechanical_completion.state == "failed"
    assert evidence.mechanical_completion.reason_code == "conflicting_evidence"
    assert evidence.conflicts == ("completion_sources_disagree",)


def test_explicit_false_without_message_marker_remains_false(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "explicit-false", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Computation stopped before final task\n",
        completion_attribute=False,
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_attribute"].value is False
    assert evidence.observations["completion_message_hdf"].state == (
        "not_inspected"
    )
    assert evidence.mechanical_completion.state == "available"
    assert evidence.mechanical_completion.value is False


@pytest.mark.parametrize(
    "message",
    [
        "Did not Complete Process",
        "Complete Process failed",
        "Waiting for Complete Process",
    ],
)
def test_misleading_completion_substrings_are_not_completion_assertions(
    tmp_path: Path,
    message: str,
) -> None:
    _, ras_object = _write_project(
        tmp_path / message.split()[0],
        version="7.00",
    )
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 7.0",
        messages=message,
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_attribute"].state == (
        "not_inspected"
    )
    assert evidence.observations["completion_message_hdf"].state == (
        "not_inspected"
    )
    assert evidence.observations["completion_message_hdf"].reason_code == (
        "completion_marker_absent"
    )
    assert evidence.mechanical_completion.state == "not_inspected"
    assert evidence.mechanical_completion.value is None


def test_exact_legacy_completion_record_accepts_decimal_seconds(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(
        tmp_path / "legacy-decimal-seconds",
        version="4.10",
    )
    (ras_object.project_folder / "Model.O01").write_bytes(b"legacy output")
    (ras_object.project_folder / "Model.p01.comp_msgs.txt").write_text(
        "Steady Flow Simulation Version 4.1.0 Jan 2010\n"
        "Task\tTime\n"
        "Complete Process\t1.44 sec\n",
        encoding="ascii",
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_message_stored"].value is True
    assert evidence.mechanical_completion.value is True
    assert evidence.observations["runtime_seconds"].value == 1.44


def test_ras_501_uses_message_runtime_and_time_window_fallback(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "ras501", version="5.01")
    messages = (
        "Computations Summary\n"
        "Computation Task\tTime(hh:mm:ss)\n"
        "Complete Process\t10:35\n"
    )
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 5.0.1",
        messages=messages,
        explicit_window=False,
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_attribute"].state == (
        "not_available_in_version"
    )
    assert evidence.mechanical_completion.value is True
    assert evidence.observations["runtime_seconds"].channel == "hdf"
    assert evidence.observations["runtime_seconds"].value == 635.0
    assert evidence.observations["simulation_start"].value == datetime(
        2020, 1, 1
    )
    assert evidence.observations["simulation_end"].value == datetime(
        2020, 1, 2
    )


def test_legacy_output_uses_source_preserving_stored_messages(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "legacy", version="4.10")
    output = ras_object.project_folder / "Model.O01"
    output.write_bytes(b"legacy steady output")
    sidecar = ras_object.project_folder / "Model.p01.comp_msgs.txt"
    sidecar.write_text(
        "Steady Flow Simulation Version 4.1.0 Jan 2010\n"
        "Computations Summary\n"
        "Computation Task\tTime(hh:mm:ss)\n"
        "Complete Process\t1.44\n",
        encoding="ascii",
    )

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        hash_files=True,
    )

    assert evidence.observations["result_artifact_exists"].value is True
    assert evidence.observations["result_artifact_structural_state"].state == (
        "not_available_in_version"
    )
    assert evidence.observations["completion_message_hdf"].state == (
        "not_available_in_version"
    )
    stored = evidence.observations["completion_message_stored"]
    assert stored.state == "available"
    assert stored.value is True
    assert stored.source_locator == str(sidecar)
    assert stored.source_sha256 == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    assert evidence.observations["producer_program_version"].value == "4.1.0"
    assert evidence.mechanical_completion.value is True


def test_legacy_output_without_messages_is_indeterminate(tmp_path: Path) -> None:
    _, ras_object = _write_project(tmp_path / "legacy-no-msg", version="3.13")
    (ras_object.project_folder / "Model.O01").write_bytes(b"legacy output")

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["result_artifact_exists"].value is True
    assert evidence.observations["completion_message_stored"].state == (
        "not_inspected"
    )
    assert evidence.mechanical_completion.state == "not_inspected"
    assert evidence.mechanical_completion.value is None


def test_modified_after_threshold_is_independent_from_completion(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "threshold", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute=True,
    )

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        result_modified_after=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )

    freshness = evidence.observations[
        "result_artifact_modified_after_threshold"
    ]
    assert freshness.state == "available"
    assert freshness.value is False
    assert evidence.mechanical_completion.value is True


def test_bco_without_marker_does_not_contradict_hdf_completion(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "bco-detail", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute=True,
    )
    (ras_object.project_folder / "Model.bco01").write_text(
        "Detailed volume accounting\nPercent Error 0.01\n",
        encoding="ascii",
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    stored = evidence.observations["completion_message_stored"]
    assert stored.state == "not_inspected"
    assert stored.reason_code == "completion_marker_absent"
    assert evidence.mechanical_completion.value is True
    assert evidence.conflicts == ()


def test_declared_and_observed_version_transition_is_retained(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "versions", version="5.05")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 5.0.6",
        messages="Complete Process\n",
    )
    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.declared_program_version == "5.05"
    assert evidence.observations["producer_program_version"].value == (
        "HEC-RAS 5.0.6"
    )
    assert evidence.conflicts == ()


def test_existing_hdf_overrides_legacy_declared_result_family(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(
        tmp_path / "legacy-plan-modern-result",
        version="4.00",
    )
    (ras_object.project_folder / "Model.O01").write_bytes(
        b"older legacy output"
    )
    hdf_path = _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 7.0",
        messages="Complete Process\n",
        completion_attribute=True,
    )

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        result_modified_after=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    artifact = evidence.observations["result_artifact_exists"]
    assert artifact.value is True
    assert artifact.source_locator == str(hdf_path)
    assert "legacy output artifact also exists" in (artifact.detail or "")
    assert evidence.observations[
        "result_artifact_modified_after_threshold"
    ].value is True
    assert evidence.observations["completion_attribute"].value is True
    assert evidence.observations["completion_message_hdf"].value is True
    assert evidence.observations["producer_program_version"].value == (
        "HEC-RAS 7.0"
    )
    assert evidence.mechanical_completion.value is True
    assert evidence.conflicts == ()


def test_existing_legacy_output_is_selected_when_hdf_is_absent(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(
        tmp_path / "modern-plan-legacy-result",
        version="6.60",
    )
    legacy_path = ras_object.project_folder / "Model.O01"
    legacy_path.write_bytes(b"legacy output retained after conversion")

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
    )

    artifact = evidence.observations["result_artifact_exists"]
    assert artifact.value is True
    assert artifact.source_locator == str(legacy_path)
    assert evidence.observations[
        "result_artifact_structural_state"
    ].reason_code == "result_hdf_missing"


def test_hdf_and_stored_producer_version_disagreement_is_retained(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "version-sources", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
    )
    (ras_object.project_folder / "Model.p01.comp_msgs.txt").write_text(
        "Unsteady Flow Simulation Version 6.5\nComplete Process\n",
        encoding="ascii",
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert "producer_version_sources_disagree" in evidence.conflicts
    assert "declared_producer_versions_disagree" not in evidence.conflicts


def test_empty_hdf_messages_fall_back_to_stored_message_health(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "empty-hdf-message", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="",
        completion_attribute=True,
    )
    (ras_object.project_folder / "Model.p01.computeMsgs.txt").write_text(
        "Error: stored diagnostic\n",
        encoding="ascii",
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_message_hdf"].state == (
        "not_inspected"
    )
    assert evidence.observations["message_error_count"].channel == (
        "stored_message"
    )
    assert evidence.observations["message_error_count"].value == 1


def test_result_modified_after_rejects_naive_datetime(tmp_path: Path) -> None:
    _, ras_object = _write_project(tmp_path / "naive-time", version="6.60")

    with pytest.raises(ValueError, match="timezone-aware"):
        RasCmdr.inspect_execution_evidence(
            "01",
            ras_object=ras_object,
            result_modified_after=datetime(2020, 1, 1),
        )


def test_malformed_completion_attribute_does_not_erase_message_observation(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "malformed", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute="maybe",
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["completion_attribute"].state == "failed"
    assert evidence.observations["completion_message_hdf"].state == "available"
    assert evidence.observations["completion_message_hdf"].value is True
    assert evidence.mechanical_completion.state == "failed"
    assert evidence.mechanical_completion.reason_code == (
        "completion_inspection_failed"
    )


def test_missing_modern_result_is_not_a_failed_computation(tmp_path: Path) -> None:
    _, ras_object = _write_project(tmp_path / "missing", version="6.60")

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["result_artifact_exists"].state == "available"
    assert evidence.observations["result_artifact_exists"].value is False
    assert evidence.mechanical_completion.state == "not_inspected"


def test_hash_failure_fails_closed_for_hdf_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ras_object = _write_project(tmp_path / "hash-failure", version="6.60")
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute=True,
    )
    execution_module = importlib.import_module(
        "ras_commander.ExecutionEvidence"
    )

    def _fail_hash(path: Path) -> str:
        raise RuntimeError(f"simulated hash failure: {path.name}")

    monkeypatch.setattr(execution_module, "_stable_sha256", _fail_hash)

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        hash_files=True,
    )

    assert evidence.observations["result_artifact_structural_state"].state == (
        "failed"
    )
    assert evidence.observations["completion_attribute"].state == "failed"
    assert "hash unavailable" in (
        evidence.observations["result_artifact_exists"].detail or ""
    )


def test_hdf_change_during_hash_discards_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ras_object = _write_project(tmp_path / "hash-change", version="6.60")
    hdf_path = _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages="Complete Process\n",
        completion_attribute=True,
    )
    execution_module = importlib.import_module(
        "ras_commander.ExecutionEvidence"
    )

    def _hash_then_change(path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        os.utime(
            path,
            ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
        )
        return digest

    monkeypatch.setattr(execution_module, "_stable_sha256", _hash_then_change)

    evidence = RasCmdr.inspect_execution_evidence(
        "01",
        ras_object=ras_object,
        hash_files=True,
    )

    structural = evidence.observations["result_artifact_structural_state"]
    assert structural.state == "failed"
    assert structural.source_sha256 is None
    assert evidence.observations["result_artifact_exists"].source_sha256 is None
    assert hdf_path.is_file()


def test_offline_inspector_does_not_dispatch_com(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ras_object = _write_project(tmp_path / "no-com", version="4.10")
    (ras_object.project_folder / "Model.O01").write_bytes(b"legacy output")

    def _reject_com(*args, **kwargs):
        raise AssertionError("offline inspection must not dispatch COM")

    monkeypatch.setattr(
        RasControl,
        "_com_open_close",
        staticmethod(_reject_com),
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    assert evidence.observations["com_completion"].state == "not_inspected"


def test_record_is_immutable_and_json_serializable_without_message_text(
    tmp_path: Path,
) -> None:
    _, ras_object = _write_project(tmp_path / "serialize", version="6.60")
    secret_message = "Sensitive diagnostic text\nComplete Process\n"
    _write_hdf(
        ras_object.project_folder,
        file_version="HEC-RAS 6.6",
        messages=secret_message,
        completion_attribute=True,
    )

    evidence = RasCmdr.inspect_execution_evidence("01", ras_object=ras_object)

    with pytest.raises(TypeError):
        evidence.observations["runtime_seconds"] = evidence.observations[
            "runtime_seconds"
        ]
    payload = json.dumps(evidence.to_dict())
    assert secret_message not in payload
    assert "Sensitive diagnostic text" not in payload
    assert set(evidence.observations) == set(EXECUTION_OBSERVATION_NAMES)
