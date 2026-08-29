"""Deterministic Markdown reporting from qualification Parquet tables."""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from .aggregate import verify_run
from .schemas import validate_table
from .snapshots import SnapshotError, assert_plain_ancestry, resolve_plain_path


def render_summary(run_root: str | Path) -> str:
    try:
        root = resolve_plain_path(run_root, kind="directory")
        lane_path = assert_plain_ancestry(
            root / "tables" / "lanes.parquet",
            stop=root,
        )
        invariant_path = assert_plain_ancestry(
            root / "tables" / "invariants.parquet",
            stop=root,
        )
    except SnapshotError as exc:
        raise RuntimeError(f"summary input path is linked or unsafe: {run_root}") from exc
    # Reporting is not a weaker trust path: prove every table against the
    # immutable receipts before rendering two of them.
    verify_run(root)
    lanes = pq.read_table(lane_path)
    invariants = pq.read_table(invariant_path)
    validate_table("lanes", lanes)
    validate_table("invariants", invariants)
    lane_rows = sorted(
        lanes.to_pylist(),
        key=lambda row: (row["lane_id"], row["attempt_id"]),
    )
    invariant_rows = invariants.to_pylist()
    terminal = Counter(row["terminal_category"] for row in lane_rows)
    invariant_evaluation_status = Counter(row["status"] for row in invariant_rows)
    invariant_attempts = {
        (row["lane_id"], row["attempt_id"]) for row in invariant_rows
    }

    def required_invariant_gate(row: dict[str, object]) -> str:
        if row["all_invariants_passed"]:
            return "pass"
        if (row["lane_id"], row["attempt_id"]) not in invariant_attempts:
            return "not_evaluated"
        return "incomplete_or_failed"

    invariant_gate_status = Counter(required_invariant_gate(row) for row in lane_rows)
    lines = [
        "# Execution-evidence qualification summary",
        "",
        f"Attempts: **{len(lane_rows)}**",
        "",
        "## Terminal categories",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {terminal[name]} |" for name in sorted(terminal))
    lines.extend(
        [
            "",
            "## Recorded invariant evaluations",
            "",
            f"Invariant check rows: **{len(invariant_rows)}**",
            "",
            "| Evaluation status | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| `{name}` | {invariant_evaluation_status[name]} |"
        for name in sorted(invariant_evaluation_status)
    )
    lines.extend(
        [
            "",
            "## Required-invariant attempt gates",
            "",
            "| Gate status | Attempts |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| `{name}` | {invariant_gate_status[name]} |"
        for name in sorted(invariant_gate_status)
    )
    lines.extend(
        [
            "",
            "## Attempts",
            "",
            "| Lane | Attempt | Terminal | Result family | Required-invariant gate |",
            "|---|---|---|---|---|",
        ]
    )
    for row in lane_rows:
        family = row["selected_result_format"] or "unresolved"
        gate = required_invariant_gate(row)
        lines.append(
            f"| `{row['lane_id']}` | `{row['attempt_id']}` | "
            f"`{row['terminal_category']}` | `{family}` | `{gate}` |"
        )
    return "\n".join(lines) + "\n"


def write_summary(run_root: str | Path) -> Path:
    try:
        root = resolve_plain_path(run_root, kind="directory")
        assert_plain_ancestry(root / "summary.md", stop=root)
    except SnapshotError as exc:
        raise RuntimeError(f"summary output path is linked or unsafe: {run_root}") from exc
    target = root / "summary.md"
    contents = render_summary(root).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".summary.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


__all__ = ["render_summary", "write_summary"]
