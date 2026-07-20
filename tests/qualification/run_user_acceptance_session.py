"""Run one zero-automation, human-completed HEC-RAS TCU session.

This harness never launches HEC-RAS itself. The sole launch entry point is
``RasAcceptanceState.run_user_driven_acceptance()``. Inputs are authorization
references and profile/evidence tokens; no raw acceptance-state value is read,
accepted, serialized, or printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Running this file directly places ``tests/qualification`` first on sys.path.
# Prefer the containing checkout when it is present; controlled Wine runners
# may instead supply an installed ras-commander package.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if (_REPOSITORY_ROOT / "ras_commander").is_dir():
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from ras_commander import RasAcceptanceState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ras-executable", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-evidence-sha256", required=True)
    parser.add_argument(
        "--destination-is-disposable",
        action="store_true",
        required=True,
    )
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--profile-instance-token", required=True)
    parser.add_argument("--beta-authorization-reference")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--session-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--legal-observation-seconds", type=float, default=0.25)
    parser.add_argument("--main-ready-seconds", type=float, default=2.0)
    parser.add_argument("--restart-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--restart-ready-seconds", type=float, default=2.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def status(signal: str) -> None:
        if signal != "AWAITING_USER":
            raise RuntimeError(f"Unexpected acceptance-session signal: {signal}")
        print("AWAITING_USER", flush=True)

    try:
        receipt = RasAcceptanceState.run_user_driven_acceptance(
            args.ras_executable,
            expected_version=args.expected_version,
            source_evidence_sha256=args.source_evidence_sha256,
            destination_is_disposable=args.destination_is_disposable,
            authorization_reference=args.authorization_reference,
            profile_instance_token=args.profile_instance_token,
            beta_authorization_reference=args.beta_authorization_reference,
            session_timeout_seconds=args.session_timeout_seconds,
            legal_observation_seconds=args.legal_observation_seconds,
            main_ready_seconds=args.main_ready_seconds,
            restart_timeout_seconds=args.restart_timeout_seconds,
            restart_ready_seconds=args.restart_ready_seconds,
            status_callback=status,
        )
    except BaseException as exc:
        _write_json(
            args.output,
            {
                "status": "failed_closed",
                "passed": False,
                "expected_version": args.expected_version,
                "source_evidence_sha256": args.source_evidence_sha256,
                "error": f"{type(exc).__name__}: {exc}",
                "created_at_utc": _utc_now(),
            },
        )
        raise

    payload = asdict(receipt)
    payload["passed"] = receipt.passed
    _write_json(args.output, payload)
    print(f"RECEIPT_WRITTEN {args.output}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by private runner
    raise SystemExit(main())
