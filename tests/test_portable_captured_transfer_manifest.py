"""Unit contracts for receipt-bound portable-transfer prefix evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parent
    / "qualification"
    / "build_portable_captured_transfer_manifest.py"
)
SPEC = importlib.util.spec_from_file_location("portable_manifest_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_tree(root: Path, *, version: str = "6.1") -> tuple[Path, dict]:
    target_sha256 = "a" * 64
    profile_sha256 = "b" * 64
    transfer = {
        "target": {
            "version": version,
            "sha256": target_sha256,
        },
        "prefix_instance_token_sha256": profile_sha256,
        "restart_cooldown_seconds": 45.0,
        "created_at_utc": "2026-07-18T00:00:00+00:00",
    }
    transfer["report_sha256"] = builder._canonical_hash(transfer)
    transfer_path = root / f"evidence-{version}" / f"captured-transfer-{version}.json"
    _write_json(transfer_path, transfer)

    capture_path = root / "sources" / f"{version}.capture-receipt.json"
    _write_json(capture_path, {"receipt_sha256": "c" * 64})
    bundle_path = root / "sources" / f"{version}.bundle.json"
    _write_json(bundle_path, {"opaque": "private-bundle-placeholder"})

    fingerprint = {
        "schema_version": 1,
        "exclude_wine_dosdevices": True,
        "root_sha256": "d" * 64,
        "user_reg_sha256": "e" * 64,
        "system_reg_sha256": "f" * 64,
        "userdef_reg_sha256": "1" * 64,
        "dosdevices_sha256": "2" * 64,
        "file_count": 10,
        "total_bytes": 1000,
    }
    envelope = {
        "schema_version": 2,
        "kind": "post_restart_wine_prefix_evidence",
        "captured_at_utc": "2026-07-18T00:01:00+00:00",
        "captured_after_verified_restarts": True,
        "binding": {
            "receipt_file_sha256": _sha256_file(transfer_path),
            "receipt_self_sha256": transfer["report_sha256"],
            "target_version": version,
            "target_executable_sha256": target_sha256,
            "profile_instance_sha256": profile_sha256,
        },
        "fingerprint": fingerprint,
    }
    envelope["envelope_sha256"] = builder._canonical_hash(envelope)
    prefix_path = root / f"evidence-{version}" / f"prefix-{version}.json"
    _write_json(prefix_path, envelope)
    return prefix_path, envelope


def test_entry_uses_only_self_hashed_receipt_bound_prefix_reference(tmp_path: Path):
    _prefix_path, envelope = _evidence_tree(tmp_path)

    entry = builder._entry(tmp_path.resolve(), "6.1")

    assert entry["prefix_evidence"]["self_sha256"] == envelope["envelope_sha256"]
    assert entry["prefix_evidence"]["filename"] == "evidence-6.1/prefix-6.1.json"
    assert "prefix_fingerprint" not in entry
    serialized = json.dumps(entry, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "private-bundle-placeholder" not in serialized


def test_manifest_builder_emits_schema_two_for_all_seven_exact_builds(
    tmp_path: Path,
):
    for version in builder.EXACT_BUILDS:
        _evidence_tree(tmp_path, version=version)

    manifest = builder.build_manifest(tmp_path)

    assert manifest["schema_version"] == 2
    assert [entry["version"] for entry in manifest["receipts"]] == list(
        builder.EXACT_BUILDS
    )
    assert manifest["policy"]["minimum_restart_cooldown_seconds"] == 45.0
    assert manifest["policy"]["require_receipt_bound_prefix_evidence"] is True
    body = dict(manifest)
    claimed_hash = body.pop("manifest_sha256")
    assert claimed_hash == builder._canonical_hash(body)


def test_entry_rejects_validly_self_hashed_envelope_bound_to_another_receipt(
    tmp_path: Path,
):
    prefix_path, envelope = _evidence_tree(tmp_path)
    envelope["binding"]["profile_instance_sha256"] = "9" * 64
    body = dict(envelope)
    body.pop("envelope_sha256")
    envelope["envelope_sha256"] = builder._canonical_hash(body)
    _write_json(prefix_path, envelope)

    with pytest.raises(ValueError, match="bound to another receipt"):
        builder._entry(tmp_path.resolve(), "6.1")


@pytest.mark.parametrize(
    "cooldown",
    [44.0, float("nan"), "45", True],
    ids=("too-short", "nan", "string", "boolean"),
)
def test_entry_rejects_invalid_transfer_receipt_cooldown(
    tmp_path: Path,
    cooldown: object,
):
    prefix_path, envelope = _evidence_tree(tmp_path)
    transfer_path = tmp_path / "evidence-6.1" / "captured-transfer-6.1.json"
    transfer = json.loads(transfer_path.read_text(encoding="utf-8"))
    transfer["restart_cooldown_seconds"] = cooldown
    transfer.pop("report_sha256")
    transfer["report_sha256"] = builder._canonical_hash(transfer)
    _write_json(transfer_path, transfer)

    envelope["binding"]["receipt_file_sha256"] = _sha256_file(transfer_path)
    envelope["binding"]["receipt_self_sha256"] = transfer["report_sha256"]
    envelope.pop("envelope_sha256")
    envelope["envelope_sha256"] = builder._canonical_hash(envelope)
    _write_json(prefix_path, envelope)

    with pytest.raises(ValueError, match="45-second cooldown"):
        builder._entry(tmp_path.resolve(), "6.1")
