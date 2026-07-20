"""Capture or apply the authorized six-build legacy VB6 UI fallback.

Both subcommands launch HEC-RAS only through public ``RasAcceptanceState``
methods. Private bundle files contain opaque product state and must remain
outside the repository. Console output and receipts contain hashes only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ras_commander import (  # noqa: E402
    AcceptanceProbeResult,
    AcceptanceStateBundle,
    LegacyTcuContractEvidence,
    RasAcceptanceState,
    RasExecutableIdentity,
    RegistryValueSnapshot,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _outside_repository(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return True
    return False


def _write_private(path: Path, payload: dict) -> str:
    path = path.expanduser().resolve()
    if not _outside_repository(path):
        raise ValueError("Qualification artifacts must be written outside the repository")
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite qualification artifact: {path}")
    data = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
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
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(data)


def _probe(raw: dict) -> AcceptanceProbeResult:
    values = dict(raw)
    identity = RasExecutableIdentity(**values.pop("identity"))
    for field in (
        "visible_titles",
        "blocked_titles",
        "survivors",
        "main_window_signature",
        "topology_signatures",
        "observed_process_ids",
    ):
        values[field] = tuple(values.get(field, ()))
    return AcceptanceProbeResult(identity=identity, **values)


def _evidence(raw: dict) -> LegacyTcuContractEvidence:
    values = dict(raw)
    values["target"] = RasExecutableIdentity(**values["target"])
    values["survivors"] = tuple(values.get("survivors", ()))
    return LegacyTcuContractEvidence(**values)


def _bundle(raw: dict) -> AcceptanceStateBundle:
    values = dict(raw)
    identity = RasExecutableIdentity(**values["identity"])
    state = RegistryValueSnapshot(**values["state"])
    source_probe = _probe(values["source_probe"]) if values.get("source_probe") else None
    contract = (
        _evidence(values["legacy_tcu_contract"])
        if values.get("legacy_tcu_contract")
        else None
    )
    return AcceptanceStateBundle(
        identity=identity,
        state=state,
        source_probe=source_probe,
        captured_at_utc=values["captured_at_utc"],
        fingerprint=values["fingerprint"],
        legacy_tcu_contract=contract,
    )


def _load_private_bundle(path: Path, expected_sha256: str) -> AcceptanceStateBundle:
    resolved = path.expanduser().resolve()
    if not _outside_repository(resolved):
        raise ValueError("The private source bundle must remain outside the repository")
    data = resolved.read_bytes()
    if _sha256(data) != expected_sha256:
        raise ValueError("Pinned source-bundle file hash does not match")
    payload = json.loads(data.decode("utf-8"))
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "private_exact_version_acceptance_bundle"
        or not isinstance(payload.get("bundle"), dict)
    ):
        raise ValueError("Unsupported private source-bundle schema")
    return _bundle(payload["bundle"])


def _capture_source(args: argparse.Namespace) -> int:
    if not args.private_output_authorized:
        raise ValueError("--private-output-authorized is required")
    paths = (
        args.output_original_bundle,
        args.output_extended_bundle,
        args.output_receipt,
    )
    resolved = tuple(path.expanduser().resolve() for path in paths)
    if len(set(resolved)) != len(resolved):
        raise ValueError("Source-capture output paths must be distinct")
    if not all(_outside_repository(path) for path in resolved):
        raise ValueError("Source-capture outputs must remain outside the repository")
    if any(path.exists() for path in resolved):
        raise FileExistsError("Refusing to overwrite a source-capture artifact")

    result = RasAcceptanceState.capture_authorized_legacy_ui_transfer_source(
        args.ras_executable,
        expected_version=args.expected_version,
        probe_timeout_seconds=args.probe_timeout_seconds,
        probe_ready_seconds=args.probe_ready_seconds,
        legal_timeout_seconds=args.legal_timeout_seconds,
        legal_observation_seconds=args.legal_observation_seconds,
    )
    original_payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(result.original_bundle),
    }
    extended_payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(result.extended_bundle),
    }
    original_sha256 = _write_private(args.output_original_bundle, original_payload)
    extended_sha256 = _write_private(args.output_extended_bundle, extended_payload)
    receipt = {
        "schema_version": 1,
        "kind": "authorized_legacy_ui_source_capture",
        "target": asdict(result.extended_bundle.identity),
        "original_bundle_file_sha256": original_sha256,
        "extended_bundle_file_sha256": extended_sha256,
        "original_bundle_fingerprint": result.original_bundle.fingerprint,
        "extended_bundle_fingerprint": result.extended_bundle.fingerprint,
        "contract_evidence": asdict(result.contract_evidence),
        "automated_ui_interactions": 0,
        "passed": result.passed,
        "created_at_utc": _utc_now(),
    }
    receipt["receipt_sha256"] = _sha256(_canonical_bytes(receipt))
    receipt_file_sha256 = _write_private(args.output_receipt, receipt)
    print(f"ORIGINAL_BUNDLE_SHA256 {original_sha256}", flush=True)
    print(f"EXTENDED_BUNDLE_SHA256 {extended_sha256}", flush=True)
    print(f"RECEIPT_SHA256 {receipt['receipt_sha256']}", flush=True)
    print(f"RECEIPT_FILE_SHA256 {receipt_file_sha256}", flush=True)
    return 0 if result.passed else 1


def _transfer(args: argparse.Namespace) -> int:
    expected_sha256 = args.source_bundle_sha256.strip().lower()
    if not _valid_sha256(expected_sha256):
        raise ValueError("--source-bundle-sha256 must be a lowercase SHA-256")
    if args.output.expanduser().resolve().exists():
        raise FileExistsError("Refusing to overwrite a transfer receipt")
    source_bundle = _load_private_bundle(args.source_bundle, expected_sha256)
    authorization_reference = args.authorization_reference_file.read_text(
        encoding="utf-8"
    ).strip()
    profile_instance_token = args.profile_instance_token_file.read_text(
        encoding="utf-8"
    ).strip()
    if not authorization_reference or not profile_instance_token:
        raise ValueError("Authorization/profile token files must be nonempty")
    receipt = RasAcceptanceState.run_authorized_legacy_ui_transfer(
        args.ras_executable,
        expected_version=args.expected_version,
        source_bundle=source_bundle,
        source_bundle_file_sha256=expected_sha256,
        destination_is_disposable=args.destination_is_disposable,
        authorization_reference=authorization_reference,
        profile_instance_token=profile_instance_token,
        session_timeout_seconds=args.session_timeout_seconds,
        restart_timeout_seconds=args.restart_timeout_seconds,
        restart_ready_seconds=args.restart_ready_seconds,
    )
    payload = asdict(receipt)
    payload["passed"] = receipt.passed
    payload["report_sha256"] = _sha256(_canonical_bytes(payload))
    receipt_file_sha256 = _write_private(args.output, payload)
    print(f"REPORT_SHA256 {receipt.fingerprint}", flush=True)
    print(f"RECEIPT_FILE_SHA256 {receipt_file_sha256}", flush=True)
    return 0 if receipt.passed else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture-source")
    capture.add_argument("--ras-executable", type=Path, required=True)
    capture.add_argument("--expected-version", required=True)
    capture.add_argument("--output-original-bundle", type=Path, required=True)
    capture.add_argument("--output-extended-bundle", type=Path, required=True)
    capture.add_argument("--output-receipt", type=Path, required=True)
    capture.add_argument("--private-output-authorized", action="store_true")
    capture.add_argument("--probe-timeout-seconds", type=float, default=45.0)
    capture.add_argument("--probe-ready-seconds", type=float, default=20.0)
    capture.add_argument("--legal-timeout-seconds", type=float, default=20.0)
    capture.add_argument("--legal-observation-seconds", type=float, default=0.5)
    capture.set_defaults(handler=_capture_source)

    transfer = subparsers.add_parser("transfer")
    transfer.add_argument("--ras-executable", type=Path, required=True)
    transfer.add_argument("--expected-version", required=True)
    transfer.add_argument("--source-bundle", type=Path, required=True)
    transfer.add_argument("--source-bundle-sha256", required=True)
    transfer.add_argument("--authorization-reference-file", type=Path, required=True)
    transfer.add_argument("--profile-instance-token-file", type=Path, required=True)
    transfer.add_argument("--destination-is-disposable", action="store_true", required=True)
    transfer.add_argument("--output", type=Path, required=True)
    transfer.add_argument("--session-timeout-seconds", type=float, default=60.0)
    transfer.add_argument("--restart-timeout-seconds", type=float, default=45.0)
    transfer.add_argument("--restart-ready-seconds", type=float, default=20.0)
    transfer.set_defaults(handler=_transfer)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover - private runner entry point
    raise SystemExit(main())
