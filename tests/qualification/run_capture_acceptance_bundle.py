"""Capture one exact-version opaque acceptance bundle into a private file.

The output bundle necessarily contains the opaque per-user state required for
an exact-version portability diagnostic or eligible transfer. It must remain
outside the repository and be handled as private qualification evidence.
Console output and the companion receipt do not expose that value. HEC-RAS is
launched only through
``RasAcceptanceState.probe`` and no UI interaction is automated.
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

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ras_commander import RasAcceptanceState  # noqa: E402


CAPTURABLE_EXACT_VERSIONS = frozenset(
    {
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
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _opaque_hash(label: str, value: str) -> str:
    return _sha256_bytes(f"ras-commander:{label}:v1\0{value}".encode("utf-8"))


def _canonical_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")


def _write_private(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _outside_repository(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ras-executable", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output-bundle", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--ready-seconds", type=float, default=5.0)
    parser.add_argument(
        "--private-output-authorized",
        action="store_true",
        help="Acknowledge that the bundle is private exact-version evidence",
    )
    args = parser.parse_args()

    bundle_path = args.output_bundle.expanduser().resolve()
    receipt_path = args.output_receipt.expanduser().resolve()
    if not args.private_output_authorized:
        parser.error("--private-output-authorized is required")
    if not _outside_repository(bundle_path):
        parser.error("The private bundle must be written outside the repository")
    if bundle_path == receipt_path:
        parser.error("Bundle and receipt paths must be distinct")
    if bundle_path.exists() or receipt_path.exists():
        parser.error("Refusing to overwrite prior bundle or receipt evidence")
    if args.timeout_seconds <= 0 or args.ready_seconds <= 0:
        parser.error("Probe timing values must be positive")
    if args.expected_version not in CAPTURABLE_EXACT_VERSIONS:
        parser.error(
            "Private capture is limited to the installed stable 4.0--6.6 "
            "black-box diagnostic set"
        )

    executable = args.ras_executable.expanduser().resolve()
    probe = RasAcceptanceState.probe(
        executable,
        expected_version=args.expected_version,
        timeout_seconds=args.timeout_seconds,
        ready_seconds=args.ready_seconds,
    )
    safe = (
        probe.interactions == 0
        and probe.process_tree_terminated
        and not probe.survivors
        and probe.elapsed_seconds >= args.timeout_seconds
    )
    if not probe.no_modal_verified or not safe:
        raise RuntimeError("Exact-version source probe did not pass safely")

    bundle = RasAcceptanceState.capture(
        executable,
        expected_version=args.expected_version,
        source_probe=probe,
    )
    if not bundle.state.exists or bundle.state.value is None:
        raise RuntimeError("Exact-version source capture is missing opaque state")

    bundle_payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(bundle),
    }
    bundle_bytes = _canonical_bytes(bundle_payload)
    bundle_sha256 = _sha256_bytes(bundle_bytes)
    _write_private(bundle_path, bundle_bytes)

    receipt = {
        "schema_version": 1,
        "kind": "exact_version_acceptance_bundle_capture",
        "candidate_origin": "captured_verified",
        "target": asdict(bundle.identity),
        "source_bundle_fingerprint": bundle.fingerprint,
        "bundle_file_sha256": bundle_sha256,
        "state_value_sha256": _opaque_hash(
            "acceptance-state",
            bundle.state.value,
        ),
        "state_registry_type": bundle.state.registry_type,
        "probe": asdict(probe),
        "automated_ui_interactions": probe.interactions,
        "safe_completion": safe,
        "passed": bundle.no_modal_verified and safe,
        "created_at_utc": _utc_now(),
    }
    receipt["receipt_sha256"] = _sha256_bytes(_canonical_bytes(receipt))
    _write_private(receipt_path, _canonical_bytes(receipt))

    print(f"BUNDLE_SHA256 {bundle_sha256}", flush=True)
    print(f"RECEIPT_SHA256 {receipt['receipt_sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
