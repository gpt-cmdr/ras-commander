"""CLI contribution for planning, staging, and offline inspection only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .offline_supervisor import execute_offline_action
from .planning import plan_run


def add_offline_subcommands(subparsers: argparse._SubParsersAction) -> None:
    plan = subparsers.add_parser(
        "plan",
        help="create pinned archive/execution roots without staging or execution",
    )
    plan.add_argument("--manifest", required=True, type=Path)
    plan.add_argument("--run-root", required=True, type=Path)

    stage = subparsers.add_parser(
        "stage", help="stage disposable project copies in fresh Python workers"
    )
    stage.add_argument("--run-root", required=True, type=Path)
    stage.add_argument("--lane", action="append", dest="lanes")

    inspect = subparsers.add_parser(
        "inspect", help="inspect captured results in a fresh read-only Python worker"
    )
    inspect.add_argument("--run-root", required=True, type=Path)
    inspect.add_argument("--lane", required=True, action="append", dest="lanes")


def dispatch_offline(args: argparse.Namespace) -> int | None:
    if args.command == "plan":
        context = plan_run(args.manifest, args.run_root)
        print(
            json.dumps(
                {
                    "run_id": context.descriptor["run_id"],
                    "run_root": str(context.run_root),
                    "execution_run_root": context.descriptor["execution_run_root"],
                    "manifest_sha256": context.manifest["manifest_sha256"],
                    "lanes": context.descriptor["lane_ids"],
                    "hec_ras_invoked": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command in {"stage", "inspect"}:
        attempts = execute_offline_action(
            args.run_root,
            action=args.command,
            lane_ids=args.lanes,
        )
        outcomes = [
            {
                "lane_id": attempt.receipt["lane_id"],
                "attempt_id": attempt.receipt["attempt_id"],
                "terminal_category": attempt.receipt["terminal_category"],
                "worker_pid": attempt.receipt.get("worker_pid"),
                "hec_ras_invoked": False,
            }
            for attempt in attempts
        ]
        print(json.dumps(outcomes, sort_keys=True))
        successful = {"passed", "expected_failure"}
        return 0 if all(item["terminal_category"] in successful for item in outcomes) else 1
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="execution-evidence-offline",
        description="Pinned process-isolated staging and inspection; never HEC-RAS execution.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_offline_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = dispatch_offline(args)
    if result is None:
        raise AssertionError(args.command)
    return result


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["add_offline_subcommands", "dispatch_offline", "main"]
