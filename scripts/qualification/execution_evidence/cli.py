"""Qualification CLI for offline evidence and gated live orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .aggregate import aggregate_run, verify_run
from .live_cli import add_live_subcommands, dispatch_live
from .manifest import load_and_normalize_manifest
from .offline_cli import add_offline_subcommands, dispatch_offline
from .receipts import write_json_with_digest
from .report import write_summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="execution-evidence-qualification",
        description=(
            "Validate manifests, run process-isolated qualification phases, and "
            "rebuild verified receipt aggregates. Live execution requires explicit "
            "acknowledgement and complete structured safety evidence."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate and normalize a manifest")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument(
        "--output-normalized",
        type=Path,
        help="atomically write normalized JSON and its .sha256 sibling",
    )

    aggregate = subparsers.add_parser(
        "aggregate", help="verify receipts and rebuild all Parquet tables"
    )
    aggregate.add_argument("--run-root", required=True, type=Path)

    verify = subparsers.add_parser(
        "verify", help="prove aggregate tables equal verified receipts"
    )
    verify.add_argument("--run-root", required=True, type=Path)

    report = subparsers.add_parser(
        "report", help="rebuild summary.md from validated Parquet tables"
    )
    report.add_argument("--run-root", required=True, type=Path)
    add_offline_subcommands(subparsers)
    add_live_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    offline_result = dispatch_offline(args)
    if offline_result is not None:
        return offline_result
    live_result = dispatch_live(args)
    if live_result is not None:
        return live_result
    if args.command == "validate":
        normalized = load_and_normalize_manifest(args.manifest)
        normalized_file_sha256 = None
        if args.output_normalized is not None:
            normalized_file_sha256 = write_json_with_digest(
                args.output_normalized,
                normalized,
                replace=False,
            )
        print(
            json.dumps(
                {
                    "valid": True,
                    "manifest_sha256": normalized["manifest_sha256"],
                    "normalized_file_sha256": normalized_file_sha256,
                    "fixtures": len(normalized["fixtures"]),
                    "engines": len(normalized["engines"]),
                    "lanes": len(normalized["lanes"]),
                    "hec_ras_invoked": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "aggregate":
        tables = aggregate_run(args.run_root)
        print(json.dumps({name: table.num_rows for name, table in tables.items()}, sort_keys=True))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_run(args.run_root), sort_keys=True))
        return 0
    if args.command == "report":
        print(str(write_summary(args.run_root)))
        return 0
    raise AssertionError(args.command)


__all__ = ["main"]
