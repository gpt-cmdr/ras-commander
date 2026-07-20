"""Fail-closed gate for the hybrid stable Wine TCU evidence matrix.

Each exact build must use either the zero-input user-driven workflow or an
explicitly authorized, exact-version ``captured_verified`` transfer.  The
transfer receipt is a sanitized evidence record: it proves the restoring
diagnostic and persistent disposable-prefix provisioning without containing
the opaque acceptance-state value.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from tests.qualification import test_user_driven_wine_tcu_receipts as user_gate


RUN_ENV = "RAS_COMMANDER_RUN_HYBRID_WINE_TCU_QUALIFICATION"
RECEIPT_DIR_ENV = user_gate.RECEIPT_DIR_ENV
MANIFEST_SHA256_ENV = "RAS_COMMANDER_HYBRID_WINE_TCU_MANIFEST_SHA256"
MANIFEST_NAME = "hybrid-wine-tcu-matrix.json"
SCHEMA_NAME = "hybrid-wine-tcu-matrix.schema.json"
QUALIFICATION_ENABLED = os.environ.get(RUN_ENV, "").strip() == "1"

pytestmark = [
    pytest.mark.hecras_qualification,
    pytest.mark.qualification_critical,
    pytest.mark.skipif(
        not QUALIFICATION_ENABLED,
        reason=f"set {RUN_ENV}=1 only on the configured private runner",
    ),
]

STABLE_EXACT_BUILDS = user_gate.STABLE_EXACT_BUILDS
OPTIONAL_BETA_BUILDS = user_gate.OPTIONAL_BETA_BUILDS
ALLOWED_METHODS = ("user_driven", "captured_verified_transfer")
CAPTURED_TRANSFER_EXACT_BUILDS = (
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
    "stable_receipts",
    "beta_receipts",
    "manifest_sha256",
}
_SCOPE_KEYS = user_gate._SCOPE_KEYS
_POLICY_KEYS = {
    "allowed_methods",
    "required_restart_count",
    "minimum_restart_timeout_seconds",
    "minimum_restart_cooldown_seconds",
    "strict_full_duration_restarts",
    "maximum_automated_ui_interactions",
    "require_process_tree_termination",
    "require_no_survivors",
    "require_post_restart_prefix_fingerprint",
    "require_explicit_authority_hash",
    "require_restoring_transfer_diagnostic",
    "require_persistent_disposable_provisioning",
    "forbid_raw_acceptance_state",
}
_SUMMARY_KEYS = {
    "all_passed",
    "all_safe",
    "stable_build_count",
    "user_driven_count",
    "captured_verified_transfer_count",
    "critical_skips",
}
_ENTRY_KEYS = user_gate._ENTRY_KEYS | {"method"}
_TRANSFER_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "candidate_origin",
    "target",
    "status",
    "source_bundle_file_sha256",
    "source_bundle_fingerprint",
    "destination_is_disposable",
    "authorization_reference_sha256",
    "prefix_instance_token_sha256",
    "automated_ui_interactions",
    "diagnostic",
    "provision",
    "restart_probes",
    "restart_cooldown_seconds",
    "persisted_state",
    "process_trees_terminated",
    "survivors",
    "safe_completion",
    "created_at_utc",
    "report_sha256",
    "passed",
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
_SNAPSHOT_KEYS = {"key", "name", "exists", "value", "registry_type"}
_PERSISTED_STATE_KEYS = {
    "exists",
    "registry_type",
    "value_sha256",
    "matches_source_exactly",
}
_SOURCE_CAPTURE_RECEIPT_KEYS = {
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
_FORBIDDEN_DERIVATION_KEYS = {
    "candidate_derivations",
    "derivation",
    "derivation_strategy",
    "formula",
}


def _receipt_directory() -> Path:
    return user_gate._receipt_directory()


def _safe_json_path(filename: str) -> Path:
    return user_gate._safe_json_path(filename)


def _read_manifest() -> dict:
    expected_hash = os.environ.get(MANIFEST_SHA256_ENV, "").strip()
    if not user_gate._is_sha256(expected_hash):
        pytest.fail(
            f"{MANIFEST_SHA256_ENV} must pin the reviewed manifest SHA-256",
            pytrace=False,
        )
    path = _safe_json_path(MANIFEST_NAME)
    if not path.is_file():
        pytest.fail(f"Required hybrid manifest is missing: {path}", pytrace=False)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    user_gate._assert_exact_keys(manifest, _MANIFEST_KEYS, "hybrid manifest")
    claimed_hash = manifest.pop("manifest_sha256")
    assert claimed_hash == user_gate._canonical_hash(manifest)
    assert claimed_hash == expected_hash
    _validate_manifest_header(manifest)
    return manifest


def _validate_manifest_header(manifest: dict) -> None:
    assert manifest["schema_version"] == 2
    assert manifest["qualification_mode"] == "hybrid_wine_tcu_exact_build_matrix"
    user_gate._parse_timestamp(manifest["generated_at_utc"])

    scope = manifest["scope"]
    user_gate._assert_exact_keys(scope, _SCOPE_KEYS, "hybrid manifest.scope")
    assert scope == {
        "stable_exact_builds": list(STABLE_EXACT_BUILDS),
        "optional_beta_builds": list(OPTIONAL_BETA_BUILDS),
        "covers_every_historical_release": False,
        "betas_in_stable_scope": False,
        "betas_require_separate_authorization": True,
        "one_disposable_prefix_per_build": True,
        "source_evidence_exact_build_bound": True,
    }

    policy = manifest["policy"]
    user_gate._assert_exact_keys(policy, _POLICY_KEYS, "hybrid manifest.policy")
    assert policy["allowed_methods"] == list(ALLOWED_METHODS)
    assert policy["required_restart_count"] == 2
    assert float(policy["minimum_restart_timeout_seconds"]) >= 15.0
    policy_cooldown = policy["minimum_restart_cooldown_seconds"]
    assert not isinstance(policy_cooldown, bool)
    assert isinstance(policy_cooldown, (int, float))
    assert math.isfinite(policy_cooldown)
    assert policy_cooldown >= 45.0
    assert policy["strict_full_duration_restarts"] is True
    assert policy["maximum_automated_ui_interactions"] == 0
    assert policy["require_process_tree_termination"] is True
    assert policy["require_no_survivors"] is True
    assert policy["require_post_restart_prefix_fingerprint"] is True
    assert policy["require_explicit_authority_hash"] is True
    assert policy["require_restoring_transfer_diagnostic"] is True
    assert policy["require_persistent_disposable_provisioning"] is True
    assert policy["forbid_raw_acceptance_state"] is True

    summary = manifest["summary"]
    user_gate._assert_exact_keys(summary, _SUMMARY_KEYS, "hybrid manifest.summary")
    assert summary["all_passed"] is True
    assert summary["all_safe"] is True
    assert summary["stable_build_count"] == len(STABLE_EXACT_BUILDS)
    assert summary["critical_skips"] == []
    assert isinstance(summary["user_driven_count"], int)
    assert isinstance(summary["captured_verified_transfer_count"], int)
    assert summary["user_driven_count"] >= 0
    assert summary["captured_verified_transfer_count"] >= 0
    assert (
        summary["user_driven_count"]
        + summary["captured_verified_transfer_count"]
        == len(STABLE_EXACT_BUILDS)
    )


def _read_receipt(entry: dict) -> dict:
    path = _safe_json_path(entry["receipt_filename"])
    if not path.is_file():
        pytest.fail(f"Required hybrid method receipt is missing: {path}", pytrace=False)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["receipt_file_sha256"]
    return json.loads(raw.decode("utf-8"))


def _assert_safe_opaque_fields(value: object, *, field_name: str = "") -> None:
    """Reject raw state and derivation data in a schema-v2 source report."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in _FORBIDDEN_DERIVATION_KEYS
            if key in {"value", "candidate_value"} and item is not None:
                assert isinstance(item, dict)
                assert set(item) == {"opaque_sha256"}
                assert user_gate._is_sha256(item["opaque_sha256"])
            _assert_safe_opaque_fields(item, field_name=key)
        return
    if isinstance(value, list):
        for item in value:
            _assert_safe_opaque_fields(item, field_name=field_name)
        return
    if field_name == "candidate_origin" and value is not None:
        assert value in {"captured_verified", "synthetic_negative"}


def _assert_safe_exact_source(entry: dict, receipt: dict) -> dict:
    user_gate._assert_exact_source_evidence(entry, receipt)
    source = entry["source_evidence"]
    report = user_gate._read_source_report(source)
    assert report["schema_version"] == 2
    assert report["qualification_mode"] == "exact_version_captured_state"
    _assert_safe_opaque_fields(report)
    cases = {case["case_id"]: case for case in report["cases"]}
    return cases[source["case_id"]]


def _canonical_line_hash(payload: dict) -> str:
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_opaque_hash(value: object) -> None:
    assert isinstance(value, dict)
    assert set(value) == {"opaque_sha256"}
    assert user_gate._is_sha256(value["opaque_sha256"])


def _assert_transfer_source(entry: dict, receipt: dict, policy: dict) -> dict:
    source = entry["source_evidence"]
    user_gate._assert_exact_keys(
        source,
        user_gate._SOURCE_EVIDENCE_KEYS,
        f"transfer source evidence for {entry['version']}",
    )
    assert source["kind"] == "private_native_exact_version_bundle_capture"
    assert source["exact_version"] == entry["version"]
    assert source["executable_sha256"] == entry["executable_sha256"]
    assert source["case_id"] == f"{entry['version']}:source-bundle-capture"
    assert user_gate._is_sha256(source["report_sha256"])

    path = _safe_json_path(source["artifact_filename"])
    if not path.is_file():
        pytest.fail(
            f"Required private source-capture receipt is missing: {path}",
            pytrace=False,
        )
    capture = json.loads(path.read_text(encoding="utf-8"))
    user_gate._assert_exact_keys(
        capture,
        _SOURCE_CAPTURE_RECEIPT_KEYS,
        f"source-capture receipt for {entry['version']}",
    )
    claimed_hash = capture.pop("receipt_sha256")
    assert claimed_hash == source["report_sha256"]
    assert claimed_hash == _canonical_line_hash(capture)
    assert capture["schema_version"] == 1
    assert capture["kind"] == "exact_version_acceptance_bundle_capture"
    assert capture["candidate_origin"] == "captured_verified"
    assert capture["passed"] is True
    assert capture["safe_completion"] is True
    assert capture["automated_ui_interactions"] == 0
    assert user_gate._is_sha256(capture["source_bundle_fingerprint"])
    assert user_gate._is_sha256(capture["bundle_file_sha256"])
    assert user_gate._is_sha256(capture["state_value_sha256"])
    assert isinstance(capture["state_registry_type"], int)
    user_gate._assert_identity(
        capture["target"],
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )
    user_gate._assert_restart_probe(
        capture["probe"],
        target=capture["target"],
        restart_timeout_seconds=float(policy["minimum_restart_timeout_seconds"]),
    )
    user_gate._parse_timestamp(capture["created_at_utc"])
    assert receipt["source_bundle_file_sha256"] == capture[
        "bundle_file_sha256"
    ]
    assert receipt["source_bundle_fingerprint"] == capture[
        "source_bundle_fingerprint"
    ]
    return capture


def _assert_snapshot(snapshot: dict) -> None:
    user_gate._assert_exact_keys(snapshot, _SNAPSHOT_KEYS, "registry snapshot")
    assert isinstance(snapshot["key"], str) and snapshot["key"]
    assert isinstance(snapshot["name"], str) and snapshot["name"]
    assert isinstance(snapshot["exists"], bool)
    if snapshot["value"] is None:
        assert snapshot["exists"] is False
    else:
        _assert_opaque_hash(snapshot["value"])
        assert snapshot["exists"] is True
    assert snapshot["registry_type"] is None or isinstance(
        snapshot["registry_type"],
        int,
    )


def _assert_transfer_receipt(entry: dict, policy: dict, *, beta: bool) -> dict:
    assert beta is False
    assert entry["version"] in CAPTURED_TRANSFER_EXACT_BUILDS
    receipt = _read_receipt(entry)
    user_gate._assert_exact_keys(
        receipt,
        _TRANSFER_RECEIPT_KEYS,
        f"captured transfer receipt for {entry['version']}",
    )
    assert receipt["schema_version"] == 1
    assert receipt["kind"] == "exact_version_captured_acceptance_transfer"
    assert receipt["candidate_origin"] == "captured_verified"
    assert receipt["status"] == "accepted_and_restarts_verified"
    assert receipt["destination_is_disposable"] is True
    assert receipt["passed"] is True
    claimed_hash = receipt.pop("report_sha256")
    assert claimed_hash == user_gate._canonical_hash(receipt)
    assert user_gate._is_sha256(receipt["authorization_reference_sha256"])
    assert user_gate._is_sha256(receipt["prefix_instance_token_sha256"])
    assert receipt["automated_ui_interactions"] == 0
    assert receipt["process_trees_terminated"] is True
    assert receipt["survivors"] == []
    assert receipt["safe_completion"] is True
    user_gate._assert_identity(
        receipt["target"],
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )
    _assert_safe_opaque_fields(receipt)

    source_capture = _assert_transfer_source(entry, receipt, policy)
    source_bundle_fingerprint = source_capture["source_bundle_fingerprint"]

    diagnostic = receipt["diagnostic"]
    user_gate._assert_exact_keys(
        diagnostic,
        _DIAGNOSTIC_KEYS,
        f"transfer diagnostic for {entry['version']}",
    )
    assert diagnostic["target"] == receipt["target"]
    assert diagnostic["source_version"] == entry["version"]
    assert diagnostic["transition"] == [entry["version"], entry["version"]]
    assert diagnostic["candidate_origin"] == "captured_verified"
    _assert_opaque_hash(diagnostic["candidate_value"])
    assert isinstance(diagnostic["candidate_registry_type"], int)
    assert user_gate._is_sha256(diagnostic["candidate_fingerprint"])
    assert diagnostic["source_bundle_fingerprint"] == source_bundle_fingerprint
    for snapshot_name in ("before", "applied", "restored", "after_probe"):
        _assert_snapshot(diagnostic[snapshot_name])
    assert diagnostic["applied"] == diagnostic["after_probe"]
    assert diagnostic["before"] == diagnostic["restored"]
    assert diagnostic["registry_restored"] is True
    assert diagnostic["candidate_stayed_exact"] is True
    assert isinstance(diagnostic["clean_application_subtree_for_probe"], bool)
    assert user_gate._is_sha256(
        diagnostic["application_subtree_before_fingerprint"]
    )
    assert diagnostic["application_subtree_restored_fingerprint"] == diagnostic[
        "application_subtree_before_fingerprint"
    ]
    assert user_gate._is_sha256(
        diagnostic["application_subtree_after_probe_fingerprint"]
    )
    assert diagnostic["passed"] is True
    assert isinstance(diagnostic["diagnostic_label"], str)
    assert diagnostic["diagnostic_label"]

    minimum_timeout = float(policy["minimum_restart_timeout_seconds"])
    diagnostic_observed_at = user_gate._assert_restart_probe(
        diagnostic["probe"],
        target=receipt["target"],
        restart_timeout_seconds=minimum_timeout,
    )
    diagnostic_created_at = user_gate._parse_timestamp(
        diagnostic["created_at_utc"]
    )
    assert diagnostic_observed_at <= diagnostic_created_at

    provision = receipt["provision"]
    user_gate._assert_exact_keys(
        provision,
        _PROVISION_KEYS,
        f"persistent provision for {entry['version']}",
    )
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
    assert diagnostic["clean_application_subtree_for_probe"] is True
    provision_created_at = user_gate._parse_timestamp(provision["created_at_utc"])
    assert diagnostic_created_at <= provision_created_at

    restart_probes = receipt["restart_probes"]
    assert len(restart_probes) == policy["required_restart_count"] == 2
    restart_times = [
        user_gate._assert_restart_probe(
            probe,
            target=receipt["target"],
            restart_timeout_seconds=minimum_timeout,
        )
        for probe in restart_probes
    ]
    assert restart_times == sorted(restart_times)
    assert len(set(restart_times)) == len(restart_times)
    cooldown_value = receipt["restart_cooldown_seconds"]
    assert not isinstance(cooldown_value, bool)
    assert isinstance(cooldown_value, (int, float))
    cooldown = float(cooldown_value)
    assert math.isfinite(cooldown)
    assert cooldown >= float(
        policy["minimum_restart_cooldown_seconds"]
    )
    assert (
        restart_times[0] - provision_created_at
    ).total_seconds() >= cooldown
    assert (
        restart_times[1] - restart_times[0]
    ).total_seconds() >= cooldown
    persisted = receipt["persisted_state"]
    user_gate._assert_exact_keys(
        persisted,
        _PERSISTED_STATE_KEYS,
        f"persisted state evidence for {entry['version']}",
    )
    assert persisted["exists"] is True
    assert persisted["registry_type"] == diagnostic["candidate_registry_type"]
    assert user_gate._is_sha256(persisted["value_sha256"])
    assert persisted["matches_source_exactly"] is True
    created_at = user_gate._parse_timestamp(receipt["created_at_utc"])
    assert restart_times[-1] <= created_at
    return receipt


def _assert_method_version_allowed(entry: dict, *, beta: bool) -> None:
    """Keep captured-state transfer inside its seven demonstrated stable builds."""
    if entry["method"] == "captured_verified_transfer":
        assert beta is False
        assert entry["version"] in CAPTURED_TRANSFER_EXACT_BUILDS


def _assert_entry(entry: dict, policy: dict, *, beta: bool) -> tuple[str, str]:
    user_gate._assert_exact_keys(
        entry,
        _ENTRY_KEYS,
        f"hybrid entry for {entry.get('version')}",
    )
    assert entry["scope"] == ("beta" if beta else "stable")
    assert entry["method"] in ALLOWED_METHODS
    assert entry["critical_skips"] == []
    assert user_gate._is_sha256(entry["receipt_file_sha256"])
    assert user_gate._is_sha256(entry["executable_sha256"])
    _assert_method_version_allowed(entry, beta=beta)

    if entry["method"] == "user_driven":
        receipt = user_gate._read_user_receipt(entry, policy, beta=beta)
        _assert_safe_exact_source(entry, receipt)
        profile_hash = receipt["profile_instance_token_sha256"]
    else:
        receipt = _assert_transfer_receipt(entry, policy, beta=beta)
        profile_hash = receipt["prefix_instance_token_sha256"]

    prefix_sha256 = user_gate._assert_prefix_fingerprint(entry, receipt)
    return profile_hash, prefix_sha256


def test_hybrid_matrix_covers_all_15_installed_stable_exact_builds():
    manifest = _read_manifest()
    entries = manifest["stable_receipts"]
    assert [entry["version"] for entry in entries] == list(STABLE_EXACT_BUILDS)
    assert len(entries) == len(STABLE_EXACT_BUILDS)
    assert len({entry["receipt_filename"] for entry in entries}) == len(entries)
    method_counts = {
        method: sum(entry["method"] == method for entry in entries)
        for method in ALLOWED_METHODS
    }
    assert method_counts["user_driven"] == manifest["summary"][
        "user_driven_count"
    ]
    assert method_counts["captured_verified_transfer"] == manifest["summary"][
        "captured_verified_transfer_count"
    ]

    evidence = [
        _assert_entry(entry, manifest["policy"], beta=False)
        for entry in entries
    ]
    user_gate._assert_unique(profile_hash for profile_hash, _ in evidence)
    user_gate._assert_unique(prefix_hash for _, prefix_hash in evidence)


def test_hybrid_beta_evidence_is_optional_separate_and_distinctly_authorized():
    manifest = _read_manifest()
    stable_evidence = [
        _assert_entry(entry, manifest["policy"], beta=False)
        for entry in manifest["stable_receipts"]
    ]
    beta_entries = manifest["beta_receipts"]
    beta_versions = [entry["version"] for entry in beta_entries]
    assert len(beta_versions) == len(set(beta_versions))
    assert set(beta_versions).issubset(OPTIONAL_BETA_BUILDS)
    assert set(beta_versions).isdisjoint(STABLE_EXACT_BUILDS)
    beta_evidence = [
        _assert_entry(entry, manifest["policy"], beta=True)
        for entry in beta_entries
    ]
    stable_profiles = {profile for profile, _ in stable_evidence}
    stable_prefixes = {prefix for _, prefix in stable_evidence}
    beta_profiles = {profile for profile, _ in beta_evidence}
    beta_prefixes = {prefix for _, prefix in beta_evidence}
    assert len(beta_profiles) == len(beta_entries)
    assert len(beta_prefixes) == len(beta_entries)
    assert stable_profiles.isdisjoint(beta_profiles)
    assert stable_prefixes.isdisjoint(beta_prefixes)


def test_checked_in_hybrid_schema_pins_scope_methods_and_no_raw_state_fields():
    schema_path = Path(__file__).with_name("manifests") / SCHEMA_NAME
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == 2
    assert schema["properties"]["scope"]["properties"][
        "stable_exact_builds"
    ]["const"] == list(STABLE_EXACT_BUILDS)
    assert schema["properties"]["policy"]["properties"][
        "allowed_methods"
    ]["const"] == list(ALLOWED_METHODS)
    assert schema["properties"]["policy"]["properties"][
        "minimum_restart_cooldown_seconds"
    ]["minimum"] == 45
    assert schema["additionalProperties"] is False
    transfer_definition = schema["$defs"]["capturedTransferReceipt"]
    source_capture_definition = schema["$defs"]["sourceCaptureReceipt"]
    diagnostic_definition = schema["$defs"]["sanitizedDiagnostic"]
    provision_definition = schema["$defs"]["sanitizedProvision"]
    assert set(transfer_definition["required"]) == _TRANSFER_RECEIPT_KEYS
    assert set(source_capture_definition["required"]) == (
        _SOURCE_CAPTURE_RECEIPT_KEYS
    )
    assert set(diagnostic_definition["required"]) == _DIAGNOSTIC_KEYS
    assert set(provision_definition["required"]) == _PROVISION_KEYS
    transfer_properties = transfer_definition["properties"]
    assert transfer_properties["restart_cooldown_seconds"]["minimum"] == 45
    assert "candidate_value" not in transfer_properties
    assert "value" not in transfer_properties
    diagnostic_properties = diagnostic_definition["properties"]
    provision_properties = provision_definition["properties"]
    assert diagnostic_properties["candidate_value"] == {
        "$ref": "#/$defs/opaqueHash"
    }
    assert provision_properties["value"] == {"$ref": "#/$defs/opaqueHash"}
    assert provision_properties["authorization_reference"] == {
        "$ref": "#/$defs/opaqueHash"
    }
    transfer_condition = schema["$defs"]["receiptEntry"]["allOf"][0]
    assert transfer_condition["if"]["properties"]["method"]["const"] == (
        "captured_verified_transfer"
    )
    assert transfer_condition["then"]["properties"]["version"]["enum"] == list(
        CAPTURED_TRANSFER_EXACT_BUILDS
    )
