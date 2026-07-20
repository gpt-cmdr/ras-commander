"""Gate user-driven Wine TCU evidence for the installed stable matrix.

This gate consumes only private, pinned evidence.  It validates the hash-only
receipt emitted by ``run_user_acceptance_session.py`` and a post-session
whole-prefix fingerprint for each installed exact build.  Acceptance-state
values are deliberately outside this schema and are never inspected here.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Iterable

import pytest


RUN_ENV = "RAS_COMMANDER_RUN_USER_DRIVEN_WINE_TCU_QUALIFICATION"
RECEIPT_DIR_ENV = "RAS_COMMANDER_USER_DRIVEN_WINE_TCU_RECEIPT_DIR"
MANIFEST_SHA256_ENV = "RAS_COMMANDER_USER_DRIVEN_WINE_TCU_MANIFEST_SHA256"
MANIFEST_NAME = "user-driven-wine-tcu-matrix.json"
SCHEMA_NAME = "user-driven-wine-tcu-matrix.schema.json"
QUALIFICATION_ENABLED = os.environ.get(RUN_ENV, "").strip() == "1"

pytestmark = [
    pytest.mark.hecras_qualification,
    pytest.mark.qualification_critical,
    pytest.mark.skipif(
        not QUALIFICATION_ENABLED,
        reason=f"set {RUN_ENV}=1 only on the configured private runner",
    ),
]

STABLE_EXACT_BUILDS = (
    "4.0",
    "4.1.0",
    "5.0.3",
    "5.0.6",
    "5.0.7",
    "6.0",
    "6.1",
    "6.2",
    "6.3",
    "6.3.1",
    "6.4.1",
    "6.5",
    "6.6",
    "7.0",
    "7.0.1",
)

OPTIONAL_BETA_BUILDS = (
    "6.7 Beta 4a",
    "6.7 Beta 5",
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
_SCOPE_KEYS = {
    "stable_exact_builds",
    "optional_beta_builds",
    "covers_every_historical_release",
    "betas_in_stable_scope",
    "betas_require_separate_authorization",
    "one_disposable_prefix_per_build",
    "source_evidence_exact_build_bound",
}
_POLICY_KEYS = {
    "required_restart_count",
    "minimum_restart_timeout_seconds",
    "strict_full_duration_restarts",
    "maximum_automated_ui_interactions",
    "require_process_tree_termination",
    "require_no_survivors",
    "require_post_restart_prefix_fingerprint",
}
_SUMMARY_KEYS = {
    "all_passed",
    "all_safe",
    "stable_build_count",
    "critical_skips",
}
_ENTRY_KEYS = {
    "scope",
    "version",
    "receipt_filename",
    "receipt_file_sha256",
    "executable_sha256",
    "source_evidence",
    "wine_prefix_fingerprint",
    "critical_skips",
}
_SOURCE_EVIDENCE_KEYS = {
    "kind",
    "artifact_filename",
    "report_sha256",
    "case_id",
    "exact_version",
    "executable_sha256",
}
_PREFIX_FINGERPRINT_KEYS = {
    "schema_version",
    "captured_at_utc",
    "captured_after_verified_restarts",
    "dosdevices_excluded_from_root",
    "root_sha256",
    "user_reg_sha256",
    "system_reg_sha256",
    "userdef_reg_sha256",
    "dosdevices_sha256",
    "file_count",
    "total_bytes",
}
_USER_RECEIPT_KEYS = {
    "target",
    "status",
    "destination_is_disposable",
    "source_evidence_sha256",
    "authorization_reference_sha256",
    "beta_authorization_reference_sha256",
    "profile_instance_token_sha256",
    "legal_dialog_body_sha256",
    "legal_dialog_signature",
    "main_window_signature",
    "observed_process_ids",
    "process_tree_terminated",
    "survivors",
    "automated_ui_interactions",
    "initial_session_elapsed_seconds",
    "restart_timeout_seconds",
    "restart_ready_seconds",
    "restart_probes",
    "created_at_utc",
    "fingerprint",
    "passed",
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


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
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


def _receipt_directory() -> Path:
    raw = os.environ.get(RECEIPT_DIR_ENV, "").strip()
    if not raw:
        pytest.fail(f"{RECEIPT_DIR_ENV} is required when {RUN_ENV}=1", pytrace=False)
    directory = Path(raw).expanduser()
    if not directory.is_dir():
        pytest.fail(f"Receipt directory does not exist: {directory}", pytrace=False)
    return directory


def _safe_json_path(filename: str) -> Path:
    relative = Path(filename)
    assert relative.name == filename
    assert relative.suffix.casefold() == ".json"
    return _receipt_directory() / relative


def _read_manifest() -> dict:
    expected_hash = os.environ.get(MANIFEST_SHA256_ENV, "").strip()
    if not _is_sha256(expected_hash):
        pytest.fail(
            f"{MANIFEST_SHA256_ENV} must pin the reviewed manifest SHA-256",
            pytrace=False,
        )
    path = _safe_json_path(MANIFEST_NAME)
    if not path.is_file():
        pytest.fail(f"Required user-driven manifest is missing: {path}", pytrace=False)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _assert_exact_keys(manifest, _MANIFEST_KEYS, "manifest")
    claimed_hash = manifest.pop("manifest_sha256")
    assert claimed_hash == _canonical_hash(manifest)
    assert claimed_hash == expected_hash
    _validate_manifest_header(manifest)
    return manifest


def _validate_manifest_header(manifest: dict) -> None:
    assert manifest["schema_version"] == 1
    assert manifest["qualification_mode"] == "user_driven_wine_tcu_exact_build_matrix"
    _parse_timestamp(manifest["generated_at_utc"])

    scope = manifest["scope"]
    _assert_exact_keys(scope, _SCOPE_KEYS, "manifest.scope")
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
    _assert_exact_keys(policy, _POLICY_KEYS, "manifest.policy")
    assert policy["required_restart_count"] == 2
    assert float(policy["minimum_restart_timeout_seconds"]) >= 15.0
    assert policy["strict_full_duration_restarts"] is True
    assert policy["maximum_automated_ui_interactions"] == 0
    assert policy["require_process_tree_termination"] is True
    assert policy["require_no_survivors"] is True
    assert policy["require_post_restart_prefix_fingerprint"] is True

    summary = manifest["summary"]
    _assert_exact_keys(summary, _SUMMARY_KEYS, "manifest.summary")
    assert summary == {
        "all_passed": True,
        "all_safe": True,
        "stable_build_count": len(STABLE_EXACT_BUILDS),
        "critical_skips": [],
    }


def _read_source_report(source: dict) -> dict:
    _assert_exact_keys(source, _SOURCE_EVIDENCE_KEYS, "source_evidence")
    assert source["kind"] == "opaque_native_exact_version_capture"
    assert _is_sha256(source["report_sha256"])
    assert _is_sha256(source["executable_sha256"])
    path = _safe_json_path(source["artifact_filename"])
    if not path.is_file():
        pytest.fail(
            f"Required native source evidence is missing: {path}",
            pytrace=False,
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    claimed_hash = report.pop("report_sha256", None)
    assert claimed_hash == source["report_sha256"]
    assert claimed_hash == _canonical_hash(report)
    summary = report.get("summary", {})
    assert summary.get("all_passed") is True
    assert summary.get("all_safe") is True
    assert summary.get("critical_skips") == []
    return report


def _assert_identity(identity: dict, *, version: str, executable_sha256: str) -> None:
    _assert_exact_keys(identity, _IDENTITY_KEYS, f"identity for {version}")
    assert identity["version"] == version
    expected_detected_version = (
        version.split(" ", 1)[0] if "beta" in version.casefold() else version
    )
    assert identity["detected_version"] == expected_detected_version
    assert identity["sha256"] == executable_sha256
    assert _is_sha256(identity["sha256"])
    executable_path = PureWindowsPath(identity["path"])
    assert executable_path.name.casefold() == "ras.exe"
    assert executable_path.parent.name.casefold() == version.casefold()


def _probe_from_case(case: dict) -> dict:
    return case.get("probe") or case.get("receipt", {}).get("probe") or {}


def _target_from_case(case: dict) -> dict:
    return (
        case.get("target")
        or case.get("receipt", {}).get("target")
        or _probe_from_case(case).get("identity")
        or {}
    )


def _assert_exact_source_evidence(entry: dict, receipt: dict) -> None:
    source = entry["source_evidence"]
    assert source["exact_version"] == entry["version"]
    assert source["executable_sha256"] == entry["executable_sha256"]
    assert receipt["source_evidence_sha256"] == source["report_sha256"]
    assert source["case_id"].startswith(f"{entry['version']}:")

    report = _read_source_report(source)
    cases = {case["case_id"]: case for case in report["cases"]}
    assert len(cases) == len(report["cases"])
    case = cases[source["case_id"]]
    assert case["passed"] is True
    assert case["safe_completion"] is True
    assert case["kind"] in {
        "verified_captured_state_positive",
        "exact_version_verified_captured_state_positive",
    }
    if case.get("candidate_origin") is not None:
        assert case["candidate_origin"] == "captured_verified"
    assert case.get("receipt", {}).get("candidate_origin") == "captured_verified"
    assert _is_sha256(case.get("source_bundle_fingerprint"))
    assert case.get("receipt", {}).get("source_bundle_fingerprint") == case[
        "source_bundle_fingerprint"
    ]
    assert case.get("receipt", {}).get("registry_restored") is True
    assert case.get("receipt", {}).get("candidate_stayed_exact") is True
    _assert_identity(
        _target_from_case(case),
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )
    probe = _probe_from_case(case)
    assert probe["identity"] == _target_from_case(case)
    assert probe["status"] == "ready"
    assert probe["started"] is True
    assert probe["visible_window_seen"] is True
    assert probe["interactions"] == 0
    assert probe["process_tree_terminated"] is True
    assert probe["survivors"] == []
    assert probe["blocked_reason"] is None
    assert probe["blocked_titles"] == []
    assert probe["elapsed_seconds"] >= report["timeout_seconds"]
    _assert_main_signature(probe["main_window_signature"])
    assert probe["topology_signatures"]
    assert probe["observed_process_ids"]


def _assert_main_signature(signature: object) -> None:
    assert isinstance(signature, list) and len(signature) == 4
    class_name, title, owner_hwnd, enabled = signature
    assert all(isinstance(item, str) and item for item in (class_name, title))
    assert class_name == "ThunderRT6Main"
    recognized_title = title.casefold() == "ras" or (
        "hec-ras" in title.casefold()
        or "river analysis system" in title.casefold()
    )
    assert recognized_title
    assert owner_hwnd == "0"
    assert enabled == "1"


def _assert_restart_probe(
    probe: dict,
    *,
    target: dict,
    restart_timeout_seconds: float,
) -> datetime:
    _assert_exact_keys(probe, _PROBE_KEYS, "restart probe")
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
    assert probe["elapsed_seconds"] >= restart_timeout_seconds
    _assert_main_signature(probe["main_window_signature"])
    assert probe["topology_signatures"]
    assert probe["observed_process_ids"]
    assert all(
        isinstance(pid, int) and pid > 0
        for pid in probe["observed_process_ids"]
    )
    return _parse_timestamp(probe["observed_at_utc"])


def _read_user_receipt(entry: dict, policy: dict, *, beta: bool) -> dict:
    path = _safe_json_path(entry["receipt_filename"])
    if not path.is_file():
        pytest.fail(f"Required user-driven receipt is missing: {path}", pytrace=False)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["receipt_file_sha256"]
    receipt = json.loads(raw.decode("utf-8"))
    _assert_exact_keys(receipt, _USER_RECEIPT_KEYS, f"receipt for {entry['version']}")
    assert receipt["passed"] is True
    fingerprint = receipt["fingerprint"]
    assert _is_sha256(fingerprint)
    fingerprint_payload = {
        key: value
        for key, value in receipt.items()
        if key not in {"fingerprint", "passed"}
    }
    assert fingerprint == _canonical_hash(fingerprint_payload)

    assert receipt["status"] == "accepted_and_restarts_verified"
    assert receipt["destination_is_disposable"] is True
    assert _is_sha256(receipt["authorization_reference_sha256"])
    assert _is_sha256(receipt["profile_instance_token_sha256"])
    assert _is_sha256(receipt["legal_dialog_body_sha256"])
    if beta:
        assert _is_sha256(receipt["beta_authorization_reference_sha256"])
        assert receipt["beta_authorization_reference_sha256"] != receipt[
            "authorization_reference_sha256"
        ]
    else:
        assert receipt["beta_authorization_reference_sha256"] is None

    assert isinstance(receipt["legal_dialog_signature"], list)
    assert len(receipt["legal_dialog_signature"]) == 4
    assert "terms" in receipt["legal_dialog_signature"][1].casefold()
    _assert_main_signature(receipt["main_window_signature"])
    assert receipt["observed_process_ids"]
    assert all(
        isinstance(pid, int) and pid > 0
        for pid in receipt["observed_process_ids"]
    )
    assert receipt["process_tree_terminated"] is True
    assert receipt["survivors"] == []
    assert receipt["automated_ui_interactions"] == 0
    assert receipt["initial_session_elapsed_seconds"] > 0

    restart_timeout = float(receipt["restart_timeout_seconds"])
    assert restart_timeout >= float(policy["minimum_restart_timeout_seconds"])
    assert 0 < float(receipt["restart_ready_seconds"]) <= restart_timeout
    restart_probes = receipt["restart_probes"]
    assert len(restart_probes) == policy["required_restart_count"] == 2
    restart_times = [
        _assert_restart_probe(
            probe,
            target=receipt["target"],
            restart_timeout_seconds=restart_timeout,
        )
        for probe in restart_probes
    ]
    assert restart_times == sorted(restart_times)
    assert len(set(restart_times)) == len(restart_times)
    created_at = _parse_timestamp(receipt["created_at_utc"])
    assert all(moment <= created_at for moment in restart_times)
    return receipt


def _assert_prefix_fingerprint(entry: dict, receipt: dict) -> str:
    prefix = entry["wine_prefix_fingerprint"]
    _assert_exact_keys(prefix, _PREFIX_FINGERPRINT_KEYS, "wine_prefix_fingerprint")
    assert prefix["schema_version"] == 1
    assert prefix["captured_after_verified_restarts"] is True
    assert prefix["dosdevices_excluded_from_root"] is True
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
    assert _parse_timestamp(prefix["captured_at_utc"]) >= _parse_timestamp(
        receipt["created_at_utc"]
    )
    return prefix["root_sha256"]


def _assert_entry(entry: dict, policy: dict, *, beta: bool) -> tuple[str, str]:
    _assert_exact_keys(entry, _ENTRY_KEYS, f"manifest entry for {entry.get('version')}")
    expected_scope = "beta" if beta else "stable"
    assert entry["scope"] == expected_scope
    assert entry["critical_skips"] == []
    assert _is_sha256(entry["receipt_file_sha256"])
    assert _is_sha256(entry["executable_sha256"])
    receipt = _read_user_receipt(entry, policy, beta=beta)
    _assert_identity(
        receipt["target"],
        version=entry["version"],
        executable_sha256=entry["executable_sha256"],
    )
    _assert_exact_source_evidence(entry, receipt)
    prefix_sha256 = _assert_prefix_fingerprint(entry, receipt)
    return receipt["profile_instance_token_sha256"], prefix_sha256


def _assert_unique(values: Iterable[str]) -> None:
    materialized = list(values)
    assert len(set(materialized)) == len(materialized)


def test_all_15_installed_stable_exact_builds_have_user_driven_wine_evidence():
    manifest = _read_manifest()
    entries = manifest["stable_receipts"]
    assert [entry["version"] for entry in entries] == list(STABLE_EXACT_BUILDS)
    assert len(entries) == len(STABLE_EXACT_BUILDS)
    assert len({entry["receipt_filename"] for entry in entries}) == len(entries)

    evidence = [
        _assert_entry(entry, manifest["policy"], beta=False)
        for entry in entries
    ]
    _assert_unique(profile_hash for profile_hash, _ in evidence)
    _assert_unique(prefix_hash for _, prefix_hash in evidence)


def test_optional_betas_are_separate_and_require_distinct_authorization():
    manifest = _read_manifest()
    stable_entries = manifest["stable_receipts"]
    beta_entries = manifest["beta_receipts"]
    beta_versions = [entry["version"] for entry in beta_entries]
    assert len(beta_versions) == len(set(beta_versions))
    assert set(beta_versions).issubset(OPTIONAL_BETA_BUILDS)
    assert set(beta_versions).isdisjoint(STABLE_EXACT_BUILDS)

    stable_profiles = set()
    stable_prefixes = set()
    for entry in stable_entries:
        profile_hash, prefix_hash = _assert_entry(
            entry,
            manifest["policy"],
            beta=False,
        )
        stable_profiles.add(profile_hash)
        stable_prefixes.add(prefix_hash)

    beta_evidence = [
        _assert_entry(entry, manifest["policy"], beta=True)
        for entry in beta_entries
    ]
    beta_profiles = {profile_hash for profile_hash, _ in beta_evidence}
    beta_prefixes = {prefix_hash for _, prefix_hash in beta_evidence}
    assert len(beta_profiles) == len(beta_entries)
    assert len(beta_prefixes) == len(beta_entries)
    assert stable_profiles.isdisjoint(beta_profiles)
    assert stable_prefixes.isdisjoint(beta_prefixes)


def test_checked_in_manifest_schema_pins_the_same_stable_scope():
    schema_path = Path(__file__).with_name("manifests") / SCHEMA_NAME
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["scope"]["properties"][
        "stable_exact_builds"
    ]["const"] == list(STABLE_EXACT_BUILDS)
    assert schema["properties"]["scope"]["properties"][
        "optional_beta_builds"
    ]["const"] == list(OPTIONAL_BETA_BUILDS)
    assert schema["additionalProperties"] is False
