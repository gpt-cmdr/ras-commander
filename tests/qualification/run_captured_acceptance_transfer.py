"""Test an opaque exact-version acceptance bundle in a disposable target.

No candidate value is accepted on the command line or written to the receipt.
The private bundle must have been captured after a verified source probe, and
the target must have the same exact version and executable hash. Diagnostic-
only mode runs only the restoring black-box check and cannot qualify or
provision a target. Persistent transfer remains restricted to stable 6.1--6.6:
it provisions only the captured value and requires two independently
terminated full-duration restart probes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ras_commander import (  # noqa: E402
    AcceptanceProbeResult,
    AcceptanceStateBundle,
    RasAcceptanceState,
    RasExecutableIdentity,
    RegistryValueSnapshot,
)


DIAGNOSTIC_EXACT_VERSIONS = frozenset(
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

PERSISTENT_TRANSFER_EXACT_VERSIONS = frozenset(
    {"6.1", "6.2", "6.3", "6.3.1", "6.4.1", "6.5", "6.6"}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _opaque_hash(label: str, value: str) -> str:
    return _sha256_bytes(f"ras-commander:{label}:v1\0{value}".encode("utf-8"))


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _safe_json(value: Any, *, field_name: str = "") -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {
            str(key): _safe_json(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, field_name=field_name) for item in value]
    if field_name in {"value", "candidate_value", "authorization_reference"}:
        if value is None:
            return None
        return {"opaque_sha256": _opaque_hash(field_name, str(value))}
    return value


def _load_bundle(path: Path, expected_sha256: str) -> AcceptanceStateBundle:
    data = path.read_bytes()
    observed_sha256 = _sha256_bytes(data)
    if observed_sha256 != expected_sha256:
        raise ValueError("Private source-bundle file hash does not match")
    payload = json.loads(data.decode("utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported private source-bundle schema")
    raw = payload.get("bundle")
    if not isinstance(raw, dict):
        raise ValueError("Private source-bundle payload is missing")

    identity = RasExecutableIdentity(**raw["identity"])
    state = RegistryValueSnapshot(**raw["state"])
    probe_raw = dict(raw["source_probe"])
    probe_identity = RasExecutableIdentity(**probe_raw.pop("identity"))
    for field in (
        "visible_titles",
        "blocked_titles",
        "survivors",
        "main_window_signature",
        "topology_signatures",
        "observed_process_ids",
    ):
        probe_raw[field] = tuple(probe_raw.get(field, ()))
    probe = AcceptanceProbeResult(identity=probe_identity, **probe_raw)
    return AcceptanceStateBundle(
        identity=identity,
        state=state,
        source_probe=probe,
        captured_at_utc=raw["captured_at_utc"],
        fingerprint=raw["fingerprint"],
    )


def _probe_safe(probe: AcceptanceProbeResult, timeout_seconds: float) -> bool:
    return bool(
        probe.no_modal_verified
        and probe.elapsed_seconds >= timeout_seconds
        and probe.interactions == 0
        and probe.process_tree_terminated
        and not probe.survivors
    )


def _legal_negative_safe(probe: AcceptanceProbeResult) -> bool:
    """Return whether a detected TCU is a safe completed negative outcome."""
    return bool(
        probe.status == "legal_modal"
        and probe.started
        and probe.visible_window_seen
        and probe.blocked_reason
        and probe.interactions == 0
        and probe.process_tree_terminated
        and not probe.survivors
        and probe.topology_signatures
        and probe.observed_process_ids
    )


def _restoration_safe(diagnostic: Any) -> bool:
    """Require exact value and application-subtree restoration."""
    return bool(
        diagnostic.registry_restored
        and diagnostic.candidate_stayed_exact
        and diagnostic.before == diagnostic.restored
        and diagnostic.applied == diagnostic.after_probe
        and diagnostic.application_subtree_before_fingerprint
        == diagnostic.application_subtree_restored_fingerprint
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    report["report_sha256"] = _sha256_bytes(canonical)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ras-executable", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    parser.add_argument("--authorization-reference-file", type=Path)
    parser.add_argument("--prefix-instance-token-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--diagnostic-only",
        action="store_true",
        help=(
            "Run only the restoring exact-version/same-executable diagnostic; "
            "this determines potential portability but is not qualification"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--ready-seconds", type=float, default=5.0)
    parser.add_argument(
        "--restart-cooldown-seconds",
        type=float,
        default=45.0,
        help="Quiet period before each independently terminated restart probe",
    )
    parser.add_argument("--destination-is-disposable", action="store_true")
    args = parser.parse_args()

    expected_bundle_sha256 = args.source_bundle_sha256.strip().lower()
    if not _valid_sha256(expected_bundle_sha256):
        parser.error("--source-bundle-sha256 must be a SHA-256 digest")
    if not args.destination_is_disposable:
        parser.error("--destination-is-disposable is required")
    if args.output.expanduser().resolve().exists():
        parser.error("Refusing to overwrite a prior diagnostic/transfer receipt")
    if args.timeout_seconds <= 0 or args.ready_seconds <= 0:
        parser.error("Probe timing values must be positive")
    if (
        not math.isfinite(args.restart_cooldown_seconds)
        or args.restart_cooldown_seconds < 0
    ):
        parser.error("--restart-cooldown-seconds must be finite and nonnegative")
    if args.expected_version not in DIAGNOSTIC_EXACT_VERSIONS:
        parser.error(
            "Captured-state diagnostics are limited to the installed stable "
            "4.0--6.6 black-box set"
        )
    if not args.diagnostic_only:
        if args.restart_cooldown_seconds < 45.0:
            parser.error(
                "Persistent transfer requires at least 45 seconds of target "
                "quiet before each restart probe"
            )
        if args.expected_version not in PERSISTENT_TRANSFER_EXACT_VERSIONS:
            parser.error(
                "Persistent transfer is restricted to stable 6.1--6.6 builds; "
                "use --diagnostic-only for the older installed builds"
            )
        if (
            args.authorization_reference_file is None
            or args.prefix_instance_token_file is None
        ):
            parser.error(
                "Persistent transfer requires --authorization-reference-file "
                "and --prefix-instance-token-file"
            )

    source_bundle = _load_bundle(
        args.source_bundle.expanduser().resolve(),
        expected_bundle_sha256,
    )
    if (
        source_bundle.source_probe is None
        or not _probe_safe(source_bundle.source_probe, args.timeout_seconds)
    ):
        raise ValueError(
            "Private source bundle lacks a safe full-duration source probe"
        )
    executable = args.ras_executable.expanduser().resolve()
    diagnostic = RasAcceptanceState.diagnose_candidate(
        executable,
        candidate_value=source_bundle.state.value or "",
        candidate_registry_type=source_bundle.state.registry_type,
        source_version=args.expected_version,
        expected_version=args.expected_version,
        permitted_transition=(args.expected_version, args.expected_version),
        diagnostic_label=(
            "exact-version-captured-portability-diagnostic"
            if args.diagnostic_only
            else "exact-version-captured-transfer"
        ),
        timeout_seconds=args.timeout_seconds,
        ready_seconds=args.ready_seconds,
        source_bundle=source_bundle,
        clean_application_subtree_for_probe=True,
    )
    restoration_safe = _restoration_safe(diagnostic)
    technical_effective = bool(
        diagnostic.passed
        and restoration_safe
        and _probe_safe(diagnostic.probe, args.timeout_seconds)
    )

    if args.diagnostic_only:
        safe_negative = bool(
            not technical_effective
            and restoration_safe
            and _legal_negative_safe(diagnostic.probe)
        )
        if not technical_effective and not safe_negative:
            raise RuntimeError(
                "Restoring exact-version portability diagnostic did not complete "
                "as a safe ready or legal-modal outcome"
            )
        report = {
            "schema_version": 1,
            "kind": "exact_version_captured_acceptance_diagnostic",
            "status": "portable" if technical_effective else "not_portable",
            "candidate_origin": "captured_verified",
            "purpose": "expected_to_determine_portability_not_qualification",
            "qualification_status": "diagnostic_only_nonqualifying",
            "technical_effective": technical_effective,
            "target": asdict(diagnostic.target),
            "source_bundle_file_sha256": expected_bundle_sha256,
            "source_bundle_fingerprint": source_bundle.fingerprint,
            "destination_is_disposable": True,
            "diagnostic": _safe_json(diagnostic),
            "persistence_performed": False,
            "restart_probes": [],
            "automated_ui_interactions": diagnostic.probe.interactions,
            "process_trees_terminated": diagnostic.probe.process_tree_terminated,
            "survivors": list(diagnostic.probe.survivors),
            "safe_completion": technical_effective or safe_negative,
            "passed": True,
            "created_at_utc": _utc_now(),
        }
        _write_report(args.output, report)
        print(f"REPORT_SHA256 {report['report_sha256']}", flush=True)
        return 0

    if not technical_effective:
        raise RuntimeError("Restoring exact-version transfer diagnostic failed")

    assert args.authorization_reference_file is not None
    assert args.prefix_instance_token_file is not None
    authorization_reference = args.authorization_reference_file.read_text(
        encoding="utf-8"
    ).strip()
    prefix_instance_token = args.prefix_instance_token_file.read_text(
        encoding="utf-8"
    ).strip()
    if not authorization_reference or not prefix_instance_token:
        parser.error("Authorization and prefix-instance token files must be nonempty")

    provision = RasAcceptanceState.provision(
        executable,
        diagnostic=diagnostic,
        authorization_reference=authorization_reference,
        destination_is_disposable=True,
        expected_version=args.expected_version,
        dry_run=False,
        source_bundle=source_bundle,
        replace_application_subtree=True,
    )
    restart_probe_list = []
    for _index in range(2):
        if args.restart_cooldown_seconds:
            time.sleep(args.restart_cooldown_seconds)
        restart_probe_list.append(
            RasAcceptanceState.probe(
                executable,
                expected_version=args.expected_version,
                timeout_seconds=args.timeout_seconds,
                ready_seconds=args.ready_seconds,
            )
        )
    restart_probes = tuple(restart_probe_list)
    persisted = RasAcceptanceState.capture(
        executable,
        expected_version=args.expected_version,
        source_probe=restart_probes[-1],
    )
    persisted_exact = bool(
        persisted.state.exists
        and persisted.state.value == source_bundle.state.value
        and persisted.state.registry_type == source_bundle.state.registry_type
    )
    restart_safe = all(
        _probe_safe(probe, args.timeout_seconds) for probe in restart_probes
    )
    passed = bool(
        provision.written
        and diagnostic.registry_restored
        and diagnostic.candidate_stayed_exact
        and restart_safe
        and persisted_exact
    )

    report = {
        "schema_version": 1,
        "kind": "exact_version_captured_acceptance_transfer",
        "status": "accepted_and_restarts_verified" if passed else "failed",
        "candidate_origin": "captured_verified",
        "target": asdict(diagnostic.target),
        "source_bundle_file_sha256": expected_bundle_sha256,
        "source_bundle_fingerprint": source_bundle.fingerprint,
        "authorization_reference_sha256": _opaque_hash(
            "authorization-reference",
            authorization_reference,
        ),
        "prefix_instance_token_sha256": _opaque_hash(
            "prefix-instance-token",
            prefix_instance_token,
        ),
        "destination_is_disposable": True,
        "diagnostic": _safe_json(diagnostic),
        "provision": _safe_json(provision),
        "restart_probes": _safe_json(restart_probes),
        "restart_cooldown_seconds": args.restart_cooldown_seconds,
        "persisted_state": {
            "exists": persisted.state.exists,
            "registry_type": persisted.state.registry_type,
            "value_sha256": _opaque_hash(
                "acceptance-state",
                persisted.state.value or "",
            ),
            "matches_source_exactly": persisted_exact,
        },
        "automated_ui_interactions": sum(
            probe.interactions
            for probe in (diagnostic.probe, *restart_probes)
        ),
        "process_trees_terminated": all(
            probe.process_tree_terminated
            for probe in (diagnostic.probe, *restart_probes)
        ),
        "survivors": sorted(
            {
                pid
                for probe in (diagnostic.probe, *restart_probes)
                for pid in probe.survivors
            }
        ),
        "safe_completion": technical_effective and restart_safe,
        "passed": passed,
        "created_at_utc": _utc_now(),
    }
    _write_report(args.output, report)
    print(f"REPORT_SHA256 {report['report_sha256']}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
