"""Build a hash-only manifest for the seven-build captured-transfer lane.

The manifest contains only relative artifact names, cryptographic digests, and
non-sensitive qualification metadata.  Private source bundles are hashed as
opaque files and are never decoded or copied by this helper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


EXACT_BUILDS = (
    "6.1",
    "6.2",
    "6.3",
    "6.3.1",
    "6.4.1",
    "6.5",
    "6.6",
)
MANIFEST_NAME = "portable-captured-transfer-matrix.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path.name}")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_prefix_evidence(
    envelope: dict,
    *,
    transfer: dict,
    transfer_file_sha256: str,
) -> None:
    expected_keys = {
        "schema_version",
        "kind",
        "captured_at_utc",
        "captured_after_verified_restarts",
        "binding",
        "fingerprint",
        "envelope_sha256",
    }
    if set(envelope) != expected_keys:
        raise ValueError("Post-restart prefix evidence fields changed")
    claimed_hash = envelope["envelope_sha256"]
    body = dict(envelope)
    body.pop("envelope_sha256")
    if not _is_sha256(claimed_hash) or claimed_hash != _canonical_hash(body):
        raise ValueError("Post-restart prefix evidence self-hash is invalid")
    if (
        envelope["schema_version"] != 2
        or envelope["kind"] != "post_restart_wine_prefix_evidence"
        or envelope["captured_after_verified_restarts"] is not True
    ):
        raise ValueError("Post-restart prefix evidence contract is invalid")

    binding = envelope["binding"]
    expected_binding_keys = {
        "receipt_file_sha256",
        "receipt_self_sha256",
        "target_version",
        "target_executable_sha256",
        "profile_instance_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding_keys:
        raise ValueError("Post-restart prefix evidence binding fields changed")
    if binding != {
        "receipt_file_sha256": transfer_file_sha256,
        "receipt_self_sha256": transfer["report_sha256"],
        "target_version": transfer["target"]["version"],
        "target_executable_sha256": transfer["target"]["sha256"],
        "profile_instance_sha256": transfer["prefix_instance_token_sha256"],
    }:
        raise ValueError("Post-restart prefix evidence is bound to another receipt")

    fingerprint = envelope["fingerprint"]
    expected_fingerprint_keys = {
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
    if not isinstance(fingerprint, dict) or set(fingerprint) != expected_fingerprint_keys:
        raise ValueError("Wine-prefix fingerprint fields changed")
    if fingerprint["schema_version"] != 1:
        raise ValueError("Unsupported Wine-prefix fingerprint schema")
    if fingerprint["exclude_wine_dosdevices"] is not True:
        raise ValueError("Qualification prefix evidence must exclude root dosdevices")
    for field in (
        "root_sha256",
        "user_reg_sha256",
        "system_reg_sha256",
        "userdef_reg_sha256",
        "dosdevices_sha256",
    ):
        if not _is_sha256(fingerprint[field]):
            raise ValueError("Wine-prefix fingerprint hash is invalid")
    if fingerprint["file_count"] <= 0 or fingerprint["total_bytes"] <= 0:
        raise ValueError("Wine-prefix fingerprint content is empty")


def _relative_name(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _outside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return True
    return False


def _write_json_atomic(path: Path, payload: dict, *, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(
            f"Refusing to overwrite {path}; pass --replace after review"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _entry(root: Path, version: str) -> dict:
    evidence_dir = root / f"evidence-{version}"
    transfer_candidates = sorted(
        evidence_dir.glob(f"captured-transfer-{version}*.json")
    )
    if len(transfer_candidates) != 1:
        raise ValueError(
            f"Expected exactly one transfer receipt for {version}; "
            f"found {len(transfer_candidates)}"
        )
    transfer_path = transfer_candidates[0]
    prefix_path = evidence_dir / transfer_path.name.replace(
        "captured-transfer-",
        "prefix-",
        1,
    )
    capture_path = root / "sources" / f"{version}.capture-receipt.json"
    bundle_path = root / "sources" / f"{version}.bundle.json"
    for required in (transfer_path, prefix_path, capture_path, bundle_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    transfer = _read_json(transfer_path)
    capture = _read_json(capture_path)
    prefix_evidence = _read_json(prefix_path)
    transfer_file_sha256 = _sha256_file(transfer_path)
    transfer_self_sha256 = transfer.get("report_sha256")
    transfer_body = dict(transfer)
    transfer_body.pop("report_sha256", None)
    if (
        not _is_sha256(transfer_self_sha256)
        or transfer_self_sha256 != _canonical_hash(transfer_body)
    ):
        raise ValueError(f"Transfer receipt self-hash is invalid for {version}")
    _validate_prefix_evidence(
        prefix_evidence,
        transfer=transfer,
        transfer_file_sha256=transfer_file_sha256,
    )
    cooldown = transfer.get("restart_cooldown_seconds")
    if (
        isinstance(cooldown, bool)
        or not isinstance(cooldown, (int, float))
        or not math.isfinite(cooldown)
        or cooldown < 45.0
    ):
        raise ValueError(
            f"Transfer receipt for {version} lacks the required 45-second cooldown"
        )
    transfer_created = datetime.fromisoformat(
        str(transfer["created_at_utc"]).replace("Z", "+00:00")
    )
    prefix_captured = datetime.fromisoformat(
        str(prefix_evidence["captured_at_utc"]).replace("Z", "+00:00")
    )
    if transfer_created.tzinfo is None or prefix_captured.tzinfo is None:
        raise ValueError("Evidence timestamps must include a timezone")
    if prefix_captured < transfer_created:
        raise ValueError(
            f"Prefix fingerprint for {version} predates its transfer receipt"
        )

    return {
        "version": version,
        "executable_sha256": transfer["target"]["sha256"],
        "profile_instance_sha256": transfer["prefix_instance_token_sha256"],
        "transfer_receipt": {
            "filename": _relative_name(root, transfer_path),
            "file_sha256": transfer_file_sha256,
            "self_sha256": transfer_self_sha256,
        },
        "source_capture_receipt": {
            "filename": _relative_name(root, capture_path),
            "file_sha256": _sha256_file(capture_path),
            "self_sha256": capture["receipt_sha256"],
        },
        "source_bundle": {
            "filename": _relative_name(root, bundle_path),
            "file_sha256": _sha256_file(bundle_path),
        },
        "prefix_evidence": {
            "filename": _relative_name(root, prefix_path),
            "file_sha256": _sha256_file(prefix_path),
            "self_sha256": prefix_evidence["envelope_sha256"],
        },
        "critical_skips": [],
    }


def build_manifest(root: Path) -> dict:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    entries = [_entry(root, version) for version in EXACT_BUILDS]
    manifest = {
        "schema_version": 2,
        "qualification_mode": "portable_captured_transfer_exact_build_matrix",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "exact_builds": list(EXACT_BUILDS),
            "covers_every_historical_release": False,
            "cross_version_transfer_allowed": False,
        },
        "policy": {
            "required_restart_count": 2,
            "minimum_full_duration_seconds": 20.0,
            "minimum_restart_cooldown_seconds": 45.0,
            "maximum_automated_ui_interactions": 0,
            "require_process_tree_termination": True,
            "require_no_survivors": True,
            "require_persisted_exact_state": True,
            "require_post_restart_prefix_fingerprint": True,
            "require_receipt_bound_prefix_evidence": True,
            "require_unique_profile_instances": True,
            "hashed_evidence_only": True,
        },
        "summary": {
            "all_passed": True,
            "all_safe": True,
            "exact_build_count": len(EXACT_BUILDS),
            "critical_skips": [],
        },
        "receipts": entries,
    }
    manifest["manifest_sha256"] = _canonical_hash(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    root = args.evidence_root.expanduser().resolve()
    output = (
        args.output.expanduser().resolve()
        if args.output
        else root / MANIFEST_NAME
    )
    if not _outside_repository(output):
        parser.error("The private manifest must remain outside the repository")
    manifest = build_manifest(root)
    _write_json_atomic(output, manifest, replace=args.replace)
    print(f"MANIFEST_SHA256 {manifest['manifest_sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
