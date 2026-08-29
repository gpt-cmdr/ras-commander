"""CLI contribution for explicitly acknowledged real-engine orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .live_supervisor import (
    execute_live_action,
    live_status,
    recover_live_host_lock,
)


def add_live_subcommands(subparsers: argparse._SubParsersAction) -> None:
    run = subparsers.add_parser(
        "run",
        help="run fresh disposable real-engine attempts (strict capability gate)",
    )
    run.add_argument("--run-root", required=True, type=Path)
    run.add_argument("--ack-real-ras", required=True, action="store_true")
    run.add_argument("--lane", action="append", dest="lanes")
    run.add_argument(
        "--phase",
        help="select lanes containing this exact manifest tag",
    )

    resume = subparsers.add_parser(
        "resume",
        help="reuse verified terminals and create fresh attempts for remaining lanes",
    )
    resume.add_argument("--run-root", required=True, type=Path)
    resume.add_argument("--ack-real-ras", required=True, action="store_true")

    status = subparsers.add_parser(
        "status",
        help="read run, attempt, and lock state without HEC-RAS inspection",
    )
    status.add_argument("--run-root", required=True, type=Path)

    recover = subparsers.add_parser(
        "recover",
        help="recover a retained real-engine lock after strict safety proofs",
    )
    recover.add_argument("--run-root", required=True, type=Path)
    recover.add_argument(
        "--ack-recover-real-engine-lock",
        required=True,
        action="store_true",
    )


def _attempt_outcomes(attempts) -> list[dict[str, object]]:
    return [
        {
            "lane_id": attempt.receipt["lane_id"],
            "attempt_id": attempt.receipt["attempt_id"],
            "terminal_category": attempt.receipt["terminal_category"],
            "worker_pid": attempt.receipt.get("worker_pid"),
            "hec_ras_invoked": attempt.receipt.get("hec_ras_invoked"),
        }
        for attempt in attempts
    ]


def dispatch_live(args: argparse.Namespace) -> int | None:
    if args.command == "run":
        attempts = execute_live_action(
            args.run_root,
            acknowledge_real_ras=args.ack_real_ras,
            lane_ids=args.lanes,
            phase=args.phase,
        )
        outcomes = _attempt_outcomes(attempts)
        print(json.dumps(outcomes, sort_keys=True))
        successful = {"passed", "expected_failure"}
        return 0 if all(
            item["terminal_category"] in successful for item in outcomes
        ) else 1
    if args.command == "resume":
        attempts = execute_live_action(
            args.run_root,
            acknowledge_real_ras=args.ack_real_ras,
            resume=True,
        )
        outcomes = _attempt_outcomes(attempts)
        print(json.dumps(outcomes, sort_keys=True))
        successful = {"passed", "expected_failure"}
        return 0 if all(
            item["terminal_category"] in successful for item in outcomes
        ) else 1
    if args.command == "status":
        print(json.dumps(live_status(args.run_root), sort_keys=True))
        return 0
    if args.command == "recover":
        receipt = recover_live_host_lock(
            args.run_root,
            acknowledge_recovery=args.ack_recover_real_engine_lock,
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    return None


__all__ = ["add_live_subcommands", "dispatch_live"]
