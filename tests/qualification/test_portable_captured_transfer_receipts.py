"""Fail-closed gate for the seven-build captured-transfer qualification lane.

The gate reads a SHA-256-pinned private manifest and its relative artifacts.
Private source bundles are treated as opaque files: their bytes are hashed but
never decoded, logged, or copied into the repository.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

import pytest


RUN_ENV = "RAS_COMMANDER_RUN_PORTABLE_CAPTURED_TRANSFER_QUALIFICATION"
EVIDENCE_ROOT_ENV = "RAS_COMMANDER_PORTABLE_CAPTURED_TRANSFER_EVIDENCE_ROOT"
MANIFEST_SHA256_ENV = (
    "RAS_COMMANDER_PORTABLE_CAPTURED_TRANSFER_MANIFEST_SHA256"
)
MANIFEST_NAME = "portable-captured-transfer-matrix.json"
SCHEMA_NAME = "portable-captured-transfer-matrix.schema.json"
QUALIFICATION_ENABLED = os.environ.get(RUN_ENV, "").strip() == "1"

pytestmark = [
    pytest.mark.hecras_qualification,
    pytest.mark.qualification_critical,
    pytest.mark.skipif(
        not QUALIFICATION_ENABLED,
        reason=f"set {RUN_ENV}=1 only on the configured private runner",
    ),
]

EXACT_BUILDS = (
    "6.1",
    "6.2",
    "6.3",
    "6.3.1",
    "6.4.1",
    "6.5",
    "6.6",
)

_MANIFEST_KEYS = {
    "schema_version",
    "qualification_mode",
    "generated_at_utc",
    "scope",
    "policy",
    "summary",
    "receipts",
    "manifest_sha256",
}
_SCOPE_KEYS = {
    "exact_builds",
    "covers_every_historical_release",
    "cross_version_transfer_allowed",
}
_POLICY_KEYS = {
    "required_restart_count",
    "minimum_full_duration_seconds",
    "minimum_restart_cooldown_seconds",
    "maximum_automated_ui_interactions",
    "require_process_tree_termination",
    "require_no_survivors",
    "require_persisted_exact_state",
    "require_post_restart_prefix_fingerprint",
    "require_receipt_bound_prefix_evidence",
    "require_unique_profile_instances",
    "hashed_evidence_only",
}
_SUMMARY_KEYS = {
    "all_passed",
    "all_safe",
    "exact_build_count",
    "critical_skips",
}
_ENTRY_KEYS = {
    "version",
    "executable_sha256",
    "profile_instance_sha256",
    "transfer_receipt",
    "source_capture_receipt",
    "source_bundle",
    "prefix_evidence",
    "critical_skips",
}
_HASHED_ARTIFACT_KEYS = {"filename", "file_sha256", "self_sha256"}
_BUNDLE_ARTIFACT_KEYS = {"filename", "file_sha256"}
_PREFIX_ENVELOPE_KEYS = {
    "schema_version",
    "kind",
    "captured_at_utc",
    "captured_after_verified_restarts",
    "binding",
    "fingerprint",
    "envelope_sha256",
}
_PREFIX_BINDING_KEYS = {
    "receipt_file_sha256",
    "receipt_self_sha256",
    "target_version",
    "target_executable_sha256",
    "profile_instance_sha256",
}
_PREFIX_FILE_KEYS = {
    "schema_version",
    "exclude_wine_dosdevices",
    "root_sha256",
    "user_reg_sha256",
    "system_reg_sha256",
    "userdef_reg_sha256",
    "dosdevices_sha256",
    "file_count",
    "total_bytes",
}
_IDENTITY_KEYS = {
    "path",
    "version",
    "sha256",
    "detected_version",
    "file_version",
    "product_version",
    "architecture",
}
_PROBE_KEYS = {
    "identity",
    "status",
    "started",
    "visible_window_seen",
    "visible_titles",
    "blocked_reason",
    "blocked_titles",
    "interactions",
    "process_tree_terminated",
    "survivors",
    "elapsed_seconds",
    "observed_at_utc",
    "main_window_signature",
    "topology_signatures",
    "observed_process_ids",
}
_CAPTURE_KEYS = {
    "schema_version",
    "kind",
    "candidate_origin",
    "target",
    "source_bundle_fingerprint",
    "bundle_file_sha256",
    "state_value_sha256",
    "state_registry_type",
    "probe",
    "automated_ui_interactions",
    "safe_completion",
    "passed",
    "created_at_utc",
    "receipt_sha256",
}
_TRANSFER_KEYS = {
    "schema_version",
    "kind",
    "status",
    "candidate_origin",
    "target",
    "source_bundle_file_sha256",
    "source_bundle_fingerprint",
    "authorization_reference_sha256",
    "prefix_instance_token_sha256",
    "destination_is_disposable",
    "diagnostic",
    "provision",
    "restart_probes",
    "restart_cooldown_seconds",
    "persisted_state",
    "automated_ui_interactions",
    "process_trees_terminated",
    "survivors",
    "safe_completion",
    "passed",
    "created_at_utc",
    "report_sha256",
}
_DIAGNOSTIC_KEYS = {
    "target",
    "source_version",
    "transition",
    "candidate_origin",
    "candidate_value",
    "candidate_registry_type",
    "candidate_fingerprint",
    "source_bundle_fingerprint",
    "before",
    "applied",
    "restored",
    "after_probe",
    "registry_restored",
    "candidate_stayed_exact",
    "clean_application_subtree_for_probe",
    "application_subtree_before_fingerprint",
    "application_subtree_after_probe_fingerprint",
    "application_subtree_restored_fingerprint",
    "probe",
    "passed",
    "diagnostic_label",
    "created_at_utc",
}
_SNAPSHOT_KEYS = {"key", "name", "exists", "value", "registry_type"}
_PROVISION_KEYS = {
    "target",
    "key",
    "value_name",
    "value",
    "registry_type",
    "diagnostic_fingerprint",
    "authorization_reference",
    "dry_run",
    "written",
    "application_subtree_replaced",
    "created_at_utc",
}
_PERSISTED_KEYS = {
    "exists",
    "registry_type",
    "value_sha256",
    "matches_source_exactly",
}
_FORBIDDEN_KEYS = {
    "acceptance_state",
    "candidate_derivations",
    "derivation",
    "derivation_strategy",
    "raw_acceptance_state",
    "raw_state",
    "registry_value",
    "state",
}


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: dict, *, trailing_newline: bool = False) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    if trailing_newline:
        encoded += b"\n"
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    assert isinstance(value, str) and value.strip()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    return parsed


def _assert_exact_keys(payload: dict, expected: set[str], context: str) -> None:
    assert isinstance(payload, dict), f"{context} must be an object"
    assert set(payload) == expected, (
        f"{context} fields changed: missing={sorted(expected - set(payload))}, "
        f"unexpected={sorted(set(payload) - expected)}"
    )


def _assert_opaque_hash(value: object) -> None:
    assert isinstance(value, dict)
    assert set(value) == {"opaque_sha256"}
    assert _is_sha256(value["opaque_sha256"])


def _assert_sanitized(value: object, *, field_name: str = "") -> None:
    """Reject derivation metadata and any non-hashed state-like value."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.casefold()
            assert normalized not in _FORBIDDEN_KEYS
            assert "formula" not in normalized
            assert "deriv" not in normalized
            if normalized in {"value", "candidate_value", "authorization_reference"}:
                if item is not None:
                    _assert_opaque_hash(item)
            else:
                _assert_sanitized(item, field_name=normalized)
        return
    if isinstance(value, list):
        for item in value:
            _assert_sanitized(item, field_name=field_name)


def _evidence_root() -> Path:
    raw = os.environ.get(EVIDENCE_ROOT_ENV, "").strip()
    if not raw:
        pytest.fail(f"{EVIDENCE_ROOT_ENV} is required when {RUN_ENV}=1", pytrace=False)
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        pytest.fail(f"Evidence root does not exist: {root}", pytrace=False)
    return root


def _safe_artifact_path(root: Path, filename: str) -> Path:
    assert isinstance(filename, str) and filename
    assert "\\" not in filename
    relative = PurePosixPath(filename)
    assert not relative.is_absolute()
    assert all(part not in {"", ".", ".."} for part in relative.parts)
    assert relative.suffix.casefold() == ".json"
    path = root.joinpath(*relative.parts).resolve()
    path.relative_to(root)
    return path


def _read_json_artifact(
    root: Path,
    reference: dict,
    *,
    reference_keys: set[str],
    context: str,
) -> dict:
    _assert_exact_keys(reference, reference_keys, context)
    assert _is_sha256(reference["file_sha256"])
    path = _safe_artifact_path(root, reference["filename"])
    if not path.is_file():
        pytest.fail(f"Required private artifact is missing: {path.name}", pytrace=False)
    assert _sha256_file(path) == reference["file_sha256"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_manifest() -> tuple[Path, dict]:
    expected_hash = os.environ.get(MANIFEST_SHA256_ENV, "").strip()
    if not _is_sha256(expected_hash):
        pytest.fail(
            f"{MANIFEST_SHA256_ENV} must pin the reviewed manifest SHA-256",
            pytrace=False,
        )
    root = _evidence_root()
    path = root / MANIFEST_NAME
    if not path.is_file():
        pytest.fail(f"Required private manifest is missing: {path.name}", pytrace=False)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _assert_exact_keys(manifest, _MANIFEST_KEYS, "portable transfer manifest")
    claimed_hash = manifest.pop("manifest_sha256")
    assert claimed_hash == _canonical_hash(manifest)
    assert claimed_hash == expected_hash
    _assert_sanitized(manifest)
    return root, manifest


def _assert_manifest_header(manifest: dict) -> dict:
    assert manifest["schema_version"] == 2
    assert (
        manifest["qualification_mode"]
        == "portable_captured_transfer_exact_build_matrix"
    )
    _parse_timestamp(manifest["generated_at_utc"])

    scope = manifest["scope"]
    _assert_exact_keys(scope, _SCOPE_KEYS, "manifest.scope")
    assert scope == {
        "exact_builds": list(EXACT_BUILDS),
        "covers_every_historical_release": False,
        "cross_version_transfer_allowed": False,
    }

    policy = manifest["policy"]
    _assert_exact_keys(policy, _POLICY_KEYS, "manifest.policy")
    assert policy["required_restart_count"] == 2
    assert float(policy["minimum_full_duration_seconds"]) >= 20.0
    policy_cooldown = policy["minimum_restart_cooldown_seconds"]
    assert not isinstance(policy_cooldown, bool)
    assert isinstance(policy_cooldown, (int, float))
    assert math.isfinite(policy_cooldown)
    assert policy_cooldown >= 45.0
    assert policy["maximum_automated_ui_interactions"] == 0
    assert policy["require_process_tree_termination"] is True
    assert policy["require_no_survivors"] is True
    assert policy["require_persisted_exact_state"] is True
    assert policy["require_post_restart_prefix_fingerprint"] is True
    assert policy["require_receipt_bound_prefix_evidence"] is True
    assert policy["require_unique_profile_instances"] is True
    assert policy["hashed_evidence_only"] is True

    summary = manifest["summary"]
    _assert_exact_keys(summary, _SUMMARY_KEYS, "manifest.summary")
    assert summary == {
        "all_passed": True,
        "all_safe": True,
        "exact_build_count": len(EXACT_BUILDS),
        "critical_skips": [],
    }
    return policy


def _assert_identity(identity: dict, *, version: str, executable_sha256: str) -> None:
    _assert_exact_keys(identity, _IDENTITY_KEYS, f"identity for {version}")
    assert identity["version"] == version
    assert identity["detected_version"] == version
    assert identity["sha256"] == executable_sha256
    assert _is_sha256(identity["sha256"])
    executable = PureWindowsPath(identity["path"])
    assert executable.name.casefold() == "ras.exe"
    assert executable.parent.name.casefold() == version.casefold()


def _assert_main_signature(signature: object) -> None:
    assert isinstance(signature, list) and len(signature) == 4
    class_name, title, owner_hwnd, enabled = signature
    assert class_name == "ThunderRT6Main"
    assert isinstance(title, str) and title
    assert owner_hwnd == "0"
    assert enabled == "1"
    recognized_title = title.casefold() == "ras" or (
        "hec-ras" in title.casefold()
        or "river analysis system" in title.casefold()
    )
    assert recognized_title


def _assert_probe(
    probe: dict,
    *,
    target: dict,
    minimum_seconds: float,
) -> datetime:
    _assert_exact_keys(probe, _PROBE_KEYS, "full-duration ready probe")
    assert probe["identity"] == target
    assert probe["status"] == "ready"
    assert probe["started"] is True
    assert probe["visible_window_seen"] is True
    assert probe["visible_titles"]
    assert probe["blocked_reason"] is None
    assert probe["blocked_titles"] == []
    assert probe["interactions"] == 0
    assert probe["process_tree_terminated"] is True
    assert probe["survivors"] == []
    assert float(probe["elapsed_seconds"]) >= minimum_seconds
    _assert_main_signature(probe["main_window_signature"])
    assert probe["topology_signatures"]
    assert probe["observed_process_ids"]
    assert all(
        isinstance(pid, int) and pid > 0 for pid in probe["observed_process_ids"]
    )
    return _parse_timestamp(probe["observed_at_utc"])


def _assert_capture_receipt(
    root: Path,
    entry: dict,
    *,
    minimum_seconds: float,
) -> dict:
    reference = entry["source_capture_receipt"]
    capture = _read_json_artifact(
        root,
        reference,
        reference_keys=_HASHED_ARTIFACT_KEYS,
        context=f"source capture reference for {entry['version']}",
    )
    _assert_exact_keys(capture, _CAPTURE_KEYS, "source capture receipt")
    _assert_sanitized(capture)
    claimed_hash = capture.pop("receipt_sha256")
    assert claimed_hash == reference["self_sha256"]
    assert claimed_hash == _canonical_hash(capture, trailing_newline=True)
    assert capture["schema_version"] == 1
    assert capture["kind"] == "exact_version_acceptance_bundle_capture"
    assert capture["candidate_origin"] == "captured_verified"
    assert capture["automated_ui_interactions"] == 0
    assert capture["safe_completion"] is True
    assert capture["passed"] is True
    assert _is_sha256(capture["source_bundle_fingerprint"])
    assert _is_sha256(capture["bundle_file_sha256"])
    assert _is_sha256(capture["state_value_sha256"])
    assert isinstance(capture["state_registry_type"], int)
    _assert_identity(
        capture["target"],
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )
    observed_at = _assert_probe(
        capture["probe"],
        target=capture["target"],
        minimum_seconds=minimum_seconds,
    )
    assert observed_at <= _parse_timestamp(capture["created_at_utc"])
    return capture


def _assert_snapshot(snapshot: dict) -> None:
    _assert_exact_keys(snapshot, _SNAPSHOT_KEYS, "restoring diagnostic snapshot")
    assert isinstance(snapshot["key"], str) and snapshot["key"]
    assert isinstance(snapshot["name"], str) and snapshot["name"]
    assert isinstance(snapshot["exists"], bool)
    if snapshot["exists"]:
        _assert_opaque_hash(snapshot["value"])
        assert isinstance(snapshot["registry_type"], int)
    else:
        assert snapshot["value"] is None
        assert snapshot["registry_type"] is None


def _assert_transfer_receipt(
    root: Path,
    entry: dict,
    capture: dict,
    *,
    policy: dict,
) -> dict:
    reference = entry["transfer_receipt"]
    receipt = _read_json_artifact(
        root,
        reference,
        reference_keys=_HASHED_ARTIFACT_KEYS,
        context=f"transfer receipt reference for {entry['version']}",
    )
    _assert_exact_keys(receipt, _TRANSFER_KEYS, "captured transfer receipt")
    _assert_sanitized(receipt)
    claimed_hash = receipt["report_sha256"]
    assert claimed_hash == reference["self_sha256"]
    receipt_body = dict(receipt)
    receipt_body.pop("report_sha256")
    assert claimed_hash == _canonical_hash(receipt_body)
    assert receipt["schema_version"] == 1
    assert receipt["kind"] == "exact_version_captured_acceptance_transfer"
    assert receipt["status"] == "accepted_and_restarts_verified"
    assert receipt["candidate_origin"] == "captured_verified"
    assert receipt["destination_is_disposable"] is True
    assert receipt["automated_ui_interactions"] == 0
    assert receipt["process_trees_terminated"] is True
    assert receipt["survivors"] == []
    assert receipt["safe_completion"] is True
    assert receipt["passed"] is True
    assert _is_sha256(receipt["authorization_reference_sha256"])
    assert receipt["prefix_instance_token_sha256"] == entry[
        "profile_instance_sha256"
    ]
    assert _is_sha256(receipt["prefix_instance_token_sha256"])
    _assert_identity(
        receipt["target"],
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )

    assert receipt["source_bundle_file_sha256"] == capture[
        "bundle_file_sha256"
    ]
    assert receipt["source_bundle_fingerprint"] == capture[
        "source_bundle_fingerprint"
    ]

    diagnostic = receipt["diagnostic"]
    _assert_exact_keys(diagnostic, _DIAGNOSTIC_KEYS, "restoring diagnostic")
    assert diagnostic["target"] == receipt["target"]
    assert diagnostic["source_version"] == entry["version"]
    assert diagnostic["transition"] == [entry["version"], entry["version"]]
    assert diagnostic["candidate_origin"] == "captured_verified"
    _assert_opaque_hash(diagnostic["candidate_value"])
    assert isinstance(diagnostic["candidate_registry_type"], int)
    assert _is_sha256(diagnostic["candidate_fingerprint"])
    assert diagnostic["source_bundle_fingerprint"] == capture[
        "source_bundle_fingerprint"
    ]
    for name in ("before", "applied", "restored", "after_probe"):
        _assert_snapshot(diagnostic[name])
    assert diagnostic["before"] == diagnostic["restored"]
    assert diagnostic["applied"] == diagnostic["after_probe"]
    assert diagnostic["registry_restored"] is True
    assert diagnostic["candidate_stayed_exact"] is True
    assert diagnostic["clean_application_subtree_for_probe"] is True
    assert _is_sha256(diagnostic["application_subtree_before_fingerprint"])
    assert _is_sha256(diagnostic["application_subtree_after_probe_fingerprint"])
    assert diagnostic["application_subtree_restored_fingerprint"] == diagnostic[
        "application_subtree_before_fingerprint"
    ]
    assert diagnostic["passed"] is True
    assert isinstance(diagnostic["diagnostic_label"], str)
    assert diagnostic["diagnostic_label"]

    minimum_seconds = float(policy["minimum_full_duration_seconds"])
    diagnostic_observed = _assert_probe(
        diagnostic["probe"],
        target=receipt["target"],
        minimum_seconds=minimum_seconds,
    )
    diagnostic_created = _parse_timestamp(diagnostic["created_at_utc"])
    assert diagnostic_observed <= diagnostic_created

    provision = receipt["provision"]
    _assert_exact_keys(provision, _PROVISION_KEYS, "persistent provision")
    assert provision["target"] == receipt["target"]
    assert provision["diagnostic_fingerprint"] == diagnostic[
        "candidate_fingerprint"
    ]
    assert isinstance(provision["key"], str) and provision["key"]
    assert isinstance(provision["value_name"], str) and provision["value_name"]
    _assert_opaque_hash(provision["value"])
    assert provision["registry_type"] == diagnostic["candidate_registry_type"]
    _assert_opaque_hash(provision["authorization_reference"])
    assert provision["dry_run"] is False
    assert provision["written"] is True
    assert provision["application_subtree_replaced"] is True
    provision_created = _parse_timestamp(provision["created_at_utc"])
    assert diagnostic_created <= provision_created

    cooldown_value = receipt["restart_cooldown_seconds"]
    assert not isinstance(cooldown_value, bool)
    assert isinstance(cooldown_value, (int, float))
    cooldown = float(cooldown_value)
    assert math.isfinite(cooldown)
    assert cooldown >= float(policy["minimum_restart_cooldown_seconds"])
    restart_probes = receipt["restart_probes"]
    assert len(restart_probes) == policy["required_restart_count"] == 2
    restart_times = [
        _assert_probe(
            probe,
            target=receipt["target"],
            minimum_seconds=minimum_seconds,
        )
        for probe in restart_probes
    ]
    assert restart_times == sorted(restart_times)
    assert len(set(restart_times)) == len(restart_times)
    assert (restart_times[0] - provision_created).total_seconds() >= cooldown
    assert (
        restart_times[1] - restart_times[0]
    ).total_seconds() >= cooldown

    persisted = receipt["persisted_state"]
    _assert_exact_keys(persisted, _PERSISTED_KEYS, "persisted exact state")
    assert persisted["exists"] is True
    assert persisted["registry_type"] == capture["state_registry_type"]
    assert persisted["value_sha256"] == capture["state_value_sha256"]
    assert persisted["matches_source_exactly"] is True
    assert restart_times[-1] <= _parse_timestamp(receipt["created_at_utc"])
    return receipt


def _assert_source_bundle(
    root: Path,
    entry: dict,
    capture: dict,
    receipt: dict,
) -> None:
    reference = entry["source_bundle"]
    _assert_exact_keys(reference, _BUNDLE_ARTIFACT_KEYS, "private bundle reference")
    assert _is_sha256(reference["file_sha256"])
    path = _safe_artifact_path(root, reference["filename"])
    if not path.is_file():
        pytest.fail(f"Required private bundle is missing: {path.name}", pytrace=False)
    assert _sha256_file(path) == reference["file_sha256"]
    assert reference["file_sha256"] == capture["bundle_file_sha256"]
    assert reference["file_sha256"] == receipt["source_bundle_file_sha256"]


def _assert_prefix_evidence(
    root: Path,
    entry: dict,
    receipt: dict,
) -> str:
    reference = entry["prefix_evidence"]
    envelope = _read_json_artifact(
        root,
        reference,
        reference_keys=_HASHED_ARTIFACT_KEYS,
        context=f"prefix evidence reference for {entry['version']}",
    )
    _assert_exact_keys(envelope, _PREFIX_ENVELOPE_KEYS, "prefix evidence envelope")
    claimed_hash = envelope["envelope_sha256"]
    assert claimed_hash == reference["self_sha256"]
    envelope_body = dict(envelope)
    envelope_body.pop("envelope_sha256")
    assert claimed_hash == _canonical_hash(envelope_body)
    assert envelope["schema_version"] == 2
    assert envelope["kind"] == "post_restart_wine_prefix_evidence"
    assert envelope["captured_after_verified_restarts"] is True
    assert _parse_timestamp(envelope["captured_at_utc"]) >= _parse_timestamp(
        receipt["created_at_utc"]
    )

    binding = envelope["binding"]
    _assert_exact_keys(binding, _PREFIX_BINDING_KEYS, "prefix evidence binding")
    transfer_reference = entry["transfer_receipt"]
    assert binding == {
        "receipt_file_sha256": transfer_reference["file_sha256"],
        "receipt_self_sha256": transfer_reference["self_sha256"],
        "target_version": entry["version"],
        "target_executable_sha256": entry["executable_sha256"],
        "profile_instance_sha256": entry["profile_instance_sha256"],
    }
    assert binding["receipt_self_sha256"] == receipt["report_sha256"]
    assert binding["target_version"] == receipt["target"]["version"]
    assert binding["target_executable_sha256"] == receipt["target"]["sha256"]
    assert binding["profile_instance_sha256"] == receipt[
        "prefix_instance_token_sha256"
    ]

    prefix = envelope["fingerprint"]
    _assert_exact_keys(prefix, _PREFIX_FILE_KEYS, "Wine prefix fingerprint")
    assert prefix["schema_version"] == 1
    assert prefix["exclude_wine_dosdevices"] is True
    for field in (
        "root_sha256",
        "user_reg_sha256",
        "system_reg_sha256",
        "userdef_reg_sha256",
        "dosdevices_sha256",
    ):
        assert _is_sha256(prefix[field])
    assert isinstance(prefix["file_count"], int) and prefix["file_count"] > 0
    assert isinstance(prefix["total_bytes"], int) and prefix["total_bytes"] > 0
    return prefix["root_sha256"]


def _assert_entry(root: Path, entry: dict, *, policy: dict) -> tuple[str, str]:
    _assert_exact_keys(entry, _ENTRY_KEYS, f"entry for {entry.get('version')}")
    assert entry["version"] in EXACT_BUILDS
    assert _is_sha256(entry["executable_sha256"])
    assert _is_sha256(entry["profile_instance_sha256"])
    assert entry["critical_skips"] == []
    capture = _assert_capture_receipt(
        root,
        entry,
        minimum_seconds=float(policy["minimum_full_duration_seconds"]),
    )
    receipt = _assert_transfer_receipt(root, entry, capture, policy=policy)
    _assert_source_bundle(root, entry, capture, receipt)
    prefix_sha256 = _assert_prefix_evidence(root, entry, receipt)
    return receipt["prefix_instance_token_sha256"], prefix_sha256


def _assert_unique(values: Iterable[str]) -> None:
    materialized = list(values)
    assert len(set(materialized)) == len(materialized)


def test_all_seven_portable_exact_builds_pass_the_captured_transfer_gate():
    root, manifest = _read_manifest()
    policy = _assert_manifest_header(manifest)
    entries = manifest["receipts"]
    assert [entry["version"] for entry in entries] == list(EXACT_BUILDS)
    assert len(entries) == len(EXACT_BUILDS)
    evidence = [_assert_entry(root, entry, policy=policy) for entry in entries]
    _assert_unique(profile for profile, _prefix in evidence)
    _assert_unique(prefix for _profile, prefix in evidence)


def test_checked_in_schema_pins_the_same_seven_build_scope_and_policy():
    schema_path = Path(__file__).with_name("manifests") / SCHEMA_NAME
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == 2
    assert schema["properties"]["scope"]["properties"]["exact_builds"][
        "const"
    ] == list(EXACT_BUILDS)
    assert schema["properties"]["receipts"]["minItems"] == len(EXACT_BUILDS)
    assert schema["properties"]["receipts"]["maxItems"] == len(EXACT_BUILDS)
    policy = schema["properties"]["policy"]["properties"]
    assert policy["required_restart_count"]["const"] == 2
    assert policy["minimum_full_duration_seconds"]["minimum"] == 20
    assert policy["minimum_restart_cooldown_seconds"]["minimum"] == 45
    assert policy["maximum_automated_ui_interactions"]["const"] == 0
    assert policy["require_receipt_bound_prefix_evidence"]["const"] is True
    envelope = schema["$defs"]["prefixEvidenceEnvelope"]
    assert envelope["properties"]["schema_version"]["const"] == 2
    assert envelope["properties"]["kind"]["const"] == (
        "post_restart_wine_prefix_evidence"
    )
    assert set(envelope["properties"]["binding"]["required"]) == (
        _PREFIX_BINDING_KEYS
    )
    serialized = json.dumps(schema, sort_keys=True).casefold()
    assert "candidate_derivation" not in serialized
    assert "candidate_formula" not in serialized
