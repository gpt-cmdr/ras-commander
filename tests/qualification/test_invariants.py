from __future__ import annotations

import pytest

from ras_commander.RasProject import STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM
from scripts.qualification.execution_evidence.fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from scripts.qualification.execution_evidence.invariants import evaluate_invariants
from scripts.qualification.execution_evidence.schemas import table_from_rows


pytestmark = pytest.mark.qualification_harness


def _passing_facts() -> dict:
    return {
        "snapshot_ids": ["before", "after"],
        "evidence_ids": ["evidence-1"],
        "inspection_fingerprints": {
            "before_content": "a",
            "after_content": "a",
            "before_metadata": "b",
            "after_metadata": "b",
        },
        "execution_attempted": True,
        "selected_result_format": "hdf",
        "cleanup_output_format": "hdf",
        "authoritative_evidence_channels": ["hdf", "derived", "filesystem"],
        "deleted_relative_paths": ["Model.O01"],
        "allowed_deleted_relative_paths": ["Model.O01", "Model.bco01"],
        "prelaunch_failed": True,
        "prelaunch_final_result_fingerprints": {"before": "x", "after": "x"},
        "finalization_attempted": True,
        "quiescence_confirmed": True,
        "skipped": True,
        "skip_fingerprints": {
            "before_content": "c",
            "after_content": "c",
            "before_metadata": "d",
            "after_metadata": "d",
        },
        "process_state": "unknown",
        "conflicting_artifacts_visible": True,
        "lane_failed": True,
        "transport_or_worker_promotion": True,
        "promotion_complete": True,
        "tmp_hdf_promoted": False,
        "evidence_contract": {
            "immutable": True,
            "json_safe": True,
            "schema_valid": True,
            "stable_hashes": True,
        },
        "source_fingerprints": {
            "fingerprint_algorithm": (
                QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
            ),
            "before_content": "e",
            "after_content": "e",
            "before_metadata": "f",
            "after_metadata": "f",
        },
        "expected_source_fingerprint_algorithm": (
            QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
        ),
        "expected_source_content_fingerprint": "e",
        "stage_fingerprint_algorithm": STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM,
        "stage_source_fingerprint_before": "stage",
        "stage_source_fingerprint_after": "stage",
        "stage_copied_fingerprint": "stage",
        "remaining_owned_processes": [],
    }


def test_all_named_invariants_can_pass_from_explicit_facts() -> None:
    results = evaluate_invariants(_passing_facts())
    assert [result.invariant_id for result in results] == [
        f"R{number:02d}" for number in range(1, 13)
    ]
    assert {result.status for result in results} == {"pass"}
    rows = [
        result.to_row(run_id="run-1", lane_id="lane-a", attempt_id="attempt-1")
        for result in results
    ]
    assert table_from_rows("invariants", rows).num_rows == 12


def test_missing_facts_are_not_inferred_as_passes() -> None:
    results = evaluate_invariants({})
    assert {result.status for result in results} == {"not_applicable"}


def test_content_drift_fails_read_only_and_source_invariants() -> None:
    facts = _passing_facts()
    facts["inspection_fingerprints"]["after_content"] = "changed"
    facts["source_fingerprints"]["after_content"] = "changed"
    statuses = {
        result.invariant_id: result.status
        for result in evaluate_invariants(facts, required=["R01", "R11"])
    }
    assert statuses == {"R01": "fail", "R11": "fail"}


def test_pinned_source_and_stage_project_fingerprint_namespaces_are_independent() -> None:
    facts = _passing_facts()
    facts["source_fingerprints"] = {
        "fingerprint_algorithm": QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
        "before_content": "pinned",
        "after_content": "pinned",
        "before_metadata": "metadata",
        "after_metadata": "metadata",
    }
    facts["expected_source_content_fingerprint"] = "pinned"
    facts["stage_source_fingerprint_before"] = "stage"
    facts["stage_source_fingerprint_after"] = "stage"
    facts["stage_copied_fingerprint"] = "stage"
    assert evaluate_invariants(facts, required=["R11"])[0].status == "pass"

    facts["stage_source_fingerprint_after"] = "drifted"
    failed = evaluate_invariants(facts, required=["R11"])[0]
    assert failed.status == "fail"
    assert failed.reason_code == "source_drift"

    facts["stage_source_fingerprint_after"] = "stage"
    facts["source_fingerprints"]["before_content"] = "unpinned"
    assert evaluate_invariants(facts, required=["R11"])[0].status == "fail"

    facts = _passing_facts()
    facts["stage_fingerprint_algorithm"] = (
        QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
    )
    assert evaluate_invariants(facts, required=["R11"])[0].status == "fail"


def test_required_filter_is_deterministic_and_rejects_unknown_ids() -> None:
    results = evaluate_invariants(_passing_facts(), required=["R12", "R01"])
    assert [result.invariant_id for result in results] == ["R01", "R12"]
    with pytest.raises(ValueError, match="unknown invariant"):
        evaluate_invariants({}, required=["R99"])


def test_unresolved_result_format_cannot_pass_channel_separation() -> None:
    result = evaluate_invariants(
        {
            "selected_result_format": None,
            "authoritative_evidence_channels": ["stored_message"],
        },
        required=["R03"],
    )[0]
    assert result.status == "fail"
    assert result.reason_code == "selected_result_format_unresolved"
