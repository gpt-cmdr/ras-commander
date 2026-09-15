"""Named R01-R12 qualification invariants evaluated from receipt facts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ras_commander.RasProject import STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM

from .fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from .schemas import QUALIFICATION_SCHEMA_VERSION


@dataclass(frozen=True)
class InvariantResult:
    invariant_id: str
    name: str
    status: str
    expected: str | None
    observed: str | None
    reason_code: str | None
    detail: str | None
    supporting_snapshot_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()

    def to_row(
        self,
        *,
        run_id: str,
        lane_id: str,
        attempt_id: str,
        evaluated_at: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "run_id": run_id,
            "lane_id": lane_id,
            "attempt_id": attempt_id,
            "invariant_id": self.invariant_id,
            "name": self.name,
            "evaluated_at": evaluated_at or datetime.now(timezone.utc),
            "status": self.status,
            "expected": self.expected,
            "observed": self.observed,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "supporting_snapshot_ids": list(self.supporting_snapshot_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
        }


_NAMES = {
    "R01": "Read-only inspection",
    "R02": "Engine-owned result family",
    "R03": "No evidence-channel mixing",
    "R04": "Exact deletion allowlist",
    "R05": "Launch-gated mutation",
    "R06": "Quiescence-gated finalization",
    "R07": "Skipped-run immutability",
    "R08": "Visible uncertainty",
    "R09": "Atomic result promotion",
    "R10": "Stable evidence contract",
    "R11": "Source immutability",
    "R12": "Owned-process hygiene",
}


def _text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _result(
    invariant_id: str,
    *,
    applicable: bool,
    passed: bool,
    expected: Any,
    observed: Any,
    reason_code: str,
    detail: str | None = None,
    snapshots: Iterable[str] = (),
    evidence: Iterable[str] = (),
) -> InvariantResult:
    return InvariantResult(
        invariant_id=invariant_id,
        name=_NAMES[invariant_id],
        status=("not_applicable" if not applicable else ("pass" if passed else "fail")),
        expected=None if expected is None else _text(expected),
        observed=None if observed is None else _text(observed),
        reason_code=reason_code,
        detail=None if detail is None else detail[:1000],
        supporting_snapshot_ids=tuple(snapshots),
        supporting_evidence_ids=tuple(evidence),
    )


def evaluate_invariants(
    facts: Mapping[str, Any],
    *,
    required: Iterable[str] | None = None,
) -> tuple[InvariantResult, ...]:
    """Evaluate R01-R12 from explicit, receipt-bound facts.

    Missing optional facts produce ``not_applicable`` rather than an inferred
    pass. The later real-engine worker is responsible for supplying every fact
    required by its lane manifest.
    """
    required_set = set(required or _NAMES)
    unknown = required_set - set(_NAMES)
    if unknown:
        raise ValueError(f"unknown invariant IDs: {sorted(unknown)}")
    snapshot_ids = tuple(str(value) for value in facts.get("snapshot_ids", []))
    evidence_ids = tuple(str(value) for value in facts.get("evidence_ids", []))
    results: list[InvariantResult] = []

    inspection_pair = facts.get("inspection_fingerprints")
    inspection_applicable = isinstance(inspection_pair, Mapping)
    inspection_passed = bool(
        inspection_applicable
        and inspection_pair.get("before_content") == inspection_pair.get("after_content")
        and inspection_pair.get("before_metadata") == inspection_pair.get("after_metadata")
    )
    results.append(
        _result(
            "R01",
            applicable=inspection_applicable,
            passed=inspection_passed,
            expected="unchanged content and metadata fingerprints",
            observed=inspection_pair,
            reason_code="inspection_read_only" if inspection_passed else "inspection_changed_files",
            snapshots=snapshot_ids,
        )
    )

    execution_attempted = facts.get("execution_attempted") is True
    selected_format = facts.get("selected_result_format")
    cleanup_format = facts.get("cleanup_output_format")
    results.append(
        _result(
            "R02",
            applicable=execution_attempted,
            passed=selected_format in {"hdf", "legacy"} and cleanup_format == selected_format,
            expected=selected_format,
            observed=cleanup_format,
            reason_code=(
                "cleanup_followed_selected_engine"
                if cleanup_format == selected_format
                else "cleanup_engine_mismatch"
            ),
        )
    )

    channels = facts.get("authoritative_evidence_channels")
    channel_applicable = isinstance(channels, list)
    selected_channel = {
        "hdf": "hdf",
        "legacy": "stored_message",
    }.get(selected_format)
    channels_passed = bool(
        channel_applicable
        and selected_channel is not None
        and all(
            channel
            in {selected_channel, "derived", "filesystem", "process", "com"}
            for channel in channels
        )
    )
    results.append(
        _result(
            "R03",
            applicable=channel_applicable,
            passed=channels_passed,
            expected=f"no opposing channel for selected format {selected_format}",
            observed=channels,
            reason_code=(
                "evidence_channels_separate"
                if channels_passed
                else (
                    "selected_result_format_unresolved"
                    if selected_channel is None
                    else "evidence_channels_mixed"
                )
            ),
            evidence=evidence_ids,
        )
    )

    deleted = facts.get("deleted_relative_paths")
    allowed = facts.get("allowed_deleted_relative_paths")
    deletion_applicable = isinstance(deleted, list) and isinstance(allowed, list)
    deletion_passed = deletion_applicable and set(deleted).issubset(set(allowed))
    results.append(
        _result(
            "R04",
            applicable=deletion_applicable,
            passed=deletion_passed,
            expected=sorted(allowed) if isinstance(allowed, list) else None,
            observed=sorted(deleted) if isinstance(deleted, list) else None,
            reason_code="deletion_within_allowlist" if deletion_passed else "deletion_outside_allowlist",
            snapshots=snapshot_ids,
        )
    )

    prelaunch_failed = facts.get("prelaunch_failed") is True
    launch_fingerprints = facts.get("prelaunch_final_result_fingerprints")
    launch_applicable = prelaunch_failed and isinstance(launch_fingerprints, Mapping)
    launch_passed = bool(
        launch_applicable
        and launch_fingerprints.get("before") == launch_fingerprints.get("after")
    )
    results.append(
        _result(
            "R05",
            applicable=launch_applicable,
            passed=launch_passed,
            expected="prelaunch final results unchanged",
            observed=launch_fingerprints,
            reason_code="prelaunch_results_preserved" if launch_passed else "prelaunch_results_changed",
            snapshots=snapshot_ids,
        )
    )

    finalization_attempted = facts.get("finalization_attempted") is True
    quiescence = facts.get("quiescence_confirmed")
    results.append(
        _result(
            "R06",
            applicable=finalization_attempted,
            passed=quiescence is True,
            expected=True,
            observed=quiescence,
            reason_code="finalized_after_quiescence" if quiescence is True else "finalized_without_quiescence",
        )
    )

    skipped = facts.get("skipped") is True
    skip_pair = facts.get("skip_fingerprints")
    skip_applicable = skipped and isinstance(skip_pair, Mapping)
    skip_passed = bool(
        skip_applicable
        and skip_pair.get("before_content") == skip_pair.get("after_content")
        and skip_pair.get("before_metadata") == skip_pair.get("after_metadata")
    )
    results.append(
        _result(
            "R07",
            applicable=skip_applicable,
            passed=skip_passed,
            expected="skip preserves content and metadata",
            observed=skip_pair,
            reason_code="skip_read_only" if skip_passed else "skip_changed_files",
            snapshots=snapshot_ids,
        )
    )

    uncertain = facts.get("process_state") in {"active", "unknown"}
    visible = facts.get("conflicting_artifacts_visible") is True
    failed_lane = facts.get("lane_failed") is True
    results.append(
        _result(
            "R08",
            applicable=uncertain,
            passed=visible and failed_lane,
            expected={"conflicts_visible": True, "lane_failed": True},
            observed={"conflicts_visible": visible, "lane_failed": failed_lane},
            reason_code="uncertainty_visible" if visible and failed_lane else "uncertainty_hidden",
            snapshots=snapshot_ids,
        )
    )

    promotion_applicable = facts.get("transport_or_worker_promotion") is True
    promotion_complete = facts.get("promotion_complete") is True
    tmp_promoted = facts.get("tmp_hdf_promoted") is True
    results.append(
        _result(
            "R09",
            applicable=promotion_applicable,
            passed=promotion_complete and not tmp_promoted,
            expected={"complete": True, "tmp_promoted": False},
            observed={"complete": promotion_complete, "tmp_promoted": tmp_promoted},
            reason_code="promotion_atomic" if promotion_complete and not tmp_promoted else "promotion_invalid",
        )
    )

    evidence_contract = facts.get("evidence_contract")
    evidence_applicable = isinstance(evidence_contract, Mapping)
    evidence_passed = bool(
        evidence_applicable
        and evidence_contract.get("immutable") is True
        and evidence_contract.get("json_safe") is True
        and evidence_contract.get("schema_valid") is True
        and evidence_contract.get("stable_hashes") is True
    )
    results.append(
        _result(
            "R10",
            applicable=evidence_applicable,
            passed=evidence_passed,
            expected="immutable, JSON-safe, schema-valid, stable hashes",
            observed=evidence_contract,
            reason_code="evidence_contract_valid" if evidence_passed else "evidence_contract_invalid",
            evidence=evidence_ids,
        )
    )

    source_pair = facts.get("source_fingerprints")
    source_applicable = isinstance(source_pair, Mapping)
    expected_source_algorithm = facts.get("expected_source_fingerprint_algorithm")
    expected_source = facts.get("expected_source_content_fingerprint")
    stage_algorithm = facts.get("stage_fingerprint_algorithm")
    stage_source_before = facts.get("stage_source_fingerprint_before")
    stage_source_after = facts.get("stage_source_fingerprint_after")
    stage_copied = facts.get("stage_copied_fingerprint")
    pin_applicable = isinstance(expected_source, str)
    stage_applicable = all(
        isinstance(value, str)
        for value in (stage_source_before, stage_source_after, stage_copied)
    )
    source_passed = bool(
        source_applicable
        and pin_applicable
        and stage_applicable
        and expected_source_algorithm
        == QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
        and source_pair.get("fingerprint_algorithm")
        == QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
        and stage_algorithm == STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM
        and source_pair.get("before_content") == source_pair.get("after_content")
        and source_pair.get("before_metadata") == source_pair.get("after_metadata")
        and source_pair.get("before_content") == expected_source
        and stage_source_before == stage_source_after == stage_copied
    )
    source_observed = {
        "qualification_snapshot": source_pair,
        "stage_project_fingerprint_algorithm": stage_algorithm,
        "stage_source_fingerprint_before": stage_source_before,
        "stage_source_fingerprint_after": stage_source_after,
        "stage_copied_fingerprint": stage_copied,
    }
    results.append(
        _result(
            "R11",
            applicable=source_applicable,
            passed=source_passed,
            expected={
                "qualification_fingerprint_algorithm": (
                    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
                ),
                "source_content_and_metadata": "unchanged",
                "pinned_source_content_fingerprint": expected_source,
                "stage_project_fingerprint_algorithm": (
                    STAGE_PROJECT_TREE_FINGERPRINT_ALGORITHM
                ),
                "stage_project_fingerprint_chain": "before == after == copied",
            },
            observed=source_observed,
            reason_code="source_immutable" if source_passed else "source_drift",
            snapshots=snapshot_ids,
        )
    )

    remaining = facts.get("remaining_owned_processes")
    process_applicable = isinstance(remaining, list)
    process_passed = process_applicable and len(remaining) == 0
    results.append(
        _result(
            "R12",
            applicable=process_applicable,
            passed=process_passed,
            expected=[],
            observed=remaining,
            reason_code="no_owned_processes" if process_passed else "owned_process_survived",
        )
    )

    return tuple(result for result in results if result.invariant_id in required_set)


__all__ = ["InvariantResult", "evaluate_invariants"]
