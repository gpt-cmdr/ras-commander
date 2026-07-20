#!/usr/bin/env python3
"""Fingerprint one Wine prefix with only the native Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


def _load_fingerprint_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "ras_commander"
        / "WinePrefixFingerprint.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_ras_commander_wine_prefix_fingerprint",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the Wine-prefix fingerprint module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
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


def _post_restart_envelope(
    fingerprint: dict,
    receipt_path: Path,
) -> dict:
    """Bind one fresh prefix fingerprint to its verified transfer receipt."""
    raw = receipt_path.read_bytes()
    receipt = json.loads(raw.decode("utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("post-restart receipt must be a JSON object")

    claimed_self_hash = receipt.get("report_sha256")
    body = dict(receipt)
    body.pop("report_sha256", None)
    if not _is_sha256(claimed_self_hash) or claimed_self_hash != _canonical_hash(body):
        raise ValueError("post-restart receipt self-hash is invalid")

    target = receipt.get("target")
    if not isinstance(target, dict):
        raise ValueError("post-restart receipt target is missing")
    target_version = target.get("version")
    target_sha256 = target.get("sha256")
    profile_sha256 = receipt.get("prefix_instance_token_sha256")
    if not isinstance(target_version, str) or not target_version.strip():
        raise ValueError("post-restart receipt target version is missing")
    if not _is_sha256(target_sha256) or not _is_sha256(profile_sha256):
        raise ValueError("post-restart receipt identity binding is invalid")
    if (
        receipt.get("kind") != "exact_version_captured_acceptance_transfer"
        or receipt.get("status") != "accepted_and_restarts_verified"
        or receipt.get("passed") is not True
        or receipt.get("safe_completion") is not True
        or receipt.get("destination_is_disposable") is not True
    ):
        raise ValueError("post-restart receipt is not a passed disposable transfer")
    cooldown = receipt.get("restart_cooldown_seconds")
    if (
        isinstance(cooldown, bool)
        or not isinstance(cooldown, (int, float))
        or not math.isfinite(cooldown)
        or cooldown < 45.0
    ):
        raise ValueError("post-restart receipt lacks the required 45-second cooldown")

    restart_probes = receipt.get("restart_probes")
    if not isinstance(restart_probes, list) or len(restart_probes) != 2:
        raise ValueError("post-restart receipt must contain exactly two restart probes")
    for probe in restart_probes:
        if (
            not isinstance(probe, dict)
            or probe.get("identity") != target
            or probe.get("status") != "ready"
            or probe.get("interactions") != 0
            or probe.get("process_tree_terminated") is not True
            or probe.get("survivors") != []
        ):
            raise ValueError("post-restart receipt contains an unsafe restart probe")

    created_at = datetime.fromisoformat(
        str(receipt.get("created_at_utc", "")).replace("Z", "+00:00")
    )
    if created_at.tzinfo is None:
        raise ValueError("post-restart receipt timestamp must include a timezone")
    captured_at = datetime.now(timezone.utc)
    if captured_at < created_at:
        raise ValueError("post-restart receipt timestamp is in the future")

    envelope = {
        "schema_version": 2,
        "kind": "post_restart_wine_prefix_evidence",
        "captured_at_utc": captured_at.isoformat(),
        "captured_after_verified_restarts": True,
        "binding": {
            "receipt_file_sha256": hashlib.sha256(raw).hexdigest(),
            "receipt_self_sha256": claimed_self_hash,
            "target_version": target_version,
            "target_executable_sha256": target_sha256,
            "profile_instance_sha256": profile_sha256,
        },
        "fingerprint": fingerprint,
    }
    envelope["envelope_sha256"] = _canonical_hash(envelope)
    return envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a deterministic, hash-only JSON fingerprint of one Wine prefix"
        )
    )
    parser.add_argument("prefix", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON evidence path; stdout remains the default",
    )
    parser.add_argument(
        "--post-restart-receipt",
        type=Path,
        help=(
            "Emit a self-hashed post-restart evidence envelope bound to this "
            "captured-transfer receipt; no receipt path or raw state is emitted"
        ),
    )
    parser.add_argument(
        "--exclude-wine-dosdevices",
        action="store_true",
        help=(
            "Exclude only root dosdevices from the content root and emit its "
            "privacy-preserving mapping hash; the default rejects escaping links"
        ),
    )
    args = parser.parse_args(argv)
    module = _load_fingerprint_module()

    try:
        result = module.fingerprint_wine_prefix(
            args.prefix,
            exclude_wine_dosdevices=args.exclude_wine_dosdevices,
        )
    except module.WinePrefixFingerprintError as exc:
        parser.exit(2, f"fingerprint_wine_prefix: error: {exc}\n")

    fingerprint = {
        "schema_version": 1,
        "exclude_wine_dosdevices": args.exclude_wine_dosdevices,
        **asdict(result),
    }
    if args.post_restart_receipt is None:
        payload = fingerprint
    else:
        try:
            payload = _post_restart_envelope(
                fingerprint,
                args.post_restart_receipt.expanduser().resolve(),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.exit(
                2,
                "fingerprint_wine_prefix: error: post-restart receipt "
                f"validation failed ({type(exc).__name__})\n",
            )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        if args.post_restart_receipt is None:
            print(f"PREFIX_SHA256 {result.root_sha256}")
        else:
            print(f"PREFIX_EVIDENCE_SHA256 {payload['envelope_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
