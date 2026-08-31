"""Deterministic verified-receipt aggregation into Arrow and Parquet."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from .receipts import VerifiedAttempt, verify_attempt_receipt
from .schemas import SCHEMAS, schema_metadata, table_from_rows, validate_table
from .snapshots import (
    SnapshotError,
    assert_plain_ancestry,
    lexical_absolute_path,
    resolve_plain_path,
)


_SORT_KEYS: Mapping[str, tuple[str, ...]] = {
    "lanes": ("lane_id", "attempt_id"),
    "artifacts": ("lane_id", "attempt_id", "phase", "relative_path"),
    "observations": ("lane_id", "attempt_id", "evidence_id", "observation_name"),
    "events": ("lane_id", "attempt_id", "sequence"),
    "invariants": ("lane_id", "attempt_id", "invariant_id"),
}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INVARIANT_RE = re.compile(r"R(?:0[1-9]|1[0-2])")


class AggregateError(RuntimeError):
    """Verified attempt receipts cannot form one coherent run."""


def discover_attempts(run_root: str | Path) -> tuple[VerifiedAttempt, ...]:
    try:
        root = resolve_plain_path(run_root, kind="directory")
    except SnapshotError as exc:
        raise AggregateError(f"run root is not a plain directory: {run_root}") from exc
    attempt_root = root / "attempts"
    try:
        assert_plain_ancestry(attempt_root, stop=root)
    except SnapshotError as exc:
        raise AggregateError(f"attempt root is linked or unsafe: {attempt_root}") from exc
    if not attempt_root.is_dir():
        raise AggregateError(f"attempt directory is missing: {attempt_root}")
    verified: list[VerifiedAttempt] = []
    attempt_dirs: list[Path] = []
    lane_dirs = sorted(attempt_root.iterdir(), key=lambda path: path.name.casefold())
    if len({path.name.casefold() for path in lane_dirs}) != len(lane_dirs):
        raise AggregateError("case-insensitively colliding lane directories under attempts")
    for lane_dir in lane_dirs:
        if not _SAFE_ID_RE.fullmatch(lane_dir.name) or lane_dir.name in {".", ".."}:
            raise AggregateError(f"unsafe lane attempt directory name: {lane_dir.name!r}")
        try:
            assert_plain_ancestry(lane_dir, stop=attempt_root)
        except SnapshotError as exc:
            raise AggregateError(f"lane attempt directory is linked: {lane_dir}") from exc
        if not lane_dir.is_dir():
            raise AggregateError(f"unexpected non-directory under attempts: {lane_dir}")
        children = sorted(lane_dir.iterdir(), key=lambda path: path.name.casefold())
        if len({path.name.casefold() for path in children}) != len(children):
            raise AggregateError(
                f"case-insensitively colliding attempt directories under {lane_dir}"
            )
        for attempt_dir in children:
            if (
                not _SAFE_ID_RE.fullmatch(attempt_dir.name)
                or attempt_dir.name in {".", ".."}
            ):
                raise AggregateError(
                    f"unsafe attempt directory name: {attempt_dir.name!r}"
                )
            try:
                assert_plain_ancestry(attempt_dir, stop=lane_dir)
            except SnapshotError as exc:
                raise AggregateError(f"attempt directory is linked: {attempt_dir}") from exc
            if not attempt_dir.is_dir():
                raise AggregateError(f"unexpected non-directory under lane attempts: {attempt_dir}")
            attempt_dirs.append(attempt_dir)
    for attempt_dir in attempt_dirs:
        if not (attempt_dir / "receipt.json").is_file():
            raise AggregateError(f"attempt has no terminal receipt: {attempt_dir}")
        verified.append(verify_attempt_receipt(attempt_dir))
    if not verified:
        raise AggregateError(f"no verified attempt receipts found under {attempt_root}")
    return tuple(verified)


def _rows_from_attempts(
    attempts: Iterable[VerifiedAttempt],
) -> tuple[dict[str, list[dict[str, Any]]], str, str, datetime]:
    rows = {name: [] for name in SCHEMAS}
    manifest_hashes: set[str] = set()
    git_heads: set[str] = set()
    receipt_times: list[datetime] = []
    for attempt in attempts:
        receipt = attempt.receipt
        manifest_hashes.add(str(receipt.get("manifest_sha256")))
        git_heads.add(str(receipt.get("git_head")))
        receipt_time = datetime.fromisoformat(
            str(receipt["receipt_committed_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        receipt_times.append(receipt_time)
        tables = receipt.get("tables")
        if not isinstance(tables, Mapping):
            raise AggregateError(f"receipt has no tables object: {attempt.attempt_dir}")
        extra_tables = set(tables) - set(SCHEMAS)
        if extra_tables:
            raise AggregateError(
                f"receipt contains unknown tables {sorted(extra_tables)}: {attempt.attempt_dir}"
            )
        identity = {
            "run_id": receipt.get("run_id"),
            "lane_id": receipt.get("lane_id"),
            "attempt_id": receipt.get("attempt_id"),
        }
        attempt_rows: dict[str, list[dict[str, Any]]] = {}
        for table_name in SCHEMAS:
            table_rows = tables.get(table_name, [])
            if not isinstance(table_rows, list):
                raise AggregateError(
                    f"receipt table {table_name} is not an array: {attempt.attempt_dir}"
                )
            if table_name == "lanes" and len(table_rows) != 1:
                raise AggregateError(
                    f"receipt must contain exactly one lanes row: {attempt.attempt_dir}"
                )
            materialized_rows: list[dict[str, Any]] = []
            for index, row in enumerate(table_rows):
                if not isinstance(row, Mapping):
                    raise AggregateError(
                        f"{table_name}[{index}] is not an object: {attempt.attempt_dir}"
                    )
                materialized = dict(row)
                for field, expected in identity.items():
                    if materialized.get(field) != expected:
                        raise AggregateError(
                            f"{table_name}[{index}].{field} disagrees with receipt identity"
                        )
                if table_name == "lanes":
                    for field in ("manifest_sha256", "git_head", "terminal_category", "worker_exit_code"):
                        if materialized.get(field) != receipt.get(field):
                            raise AggregateError(
                                f"lanes[{index}].{field} disagrees with receipt"
                            )
                materialized_rows.append(materialized)
                rows[table_name].append(materialized)
            attempt_rows[table_name] = materialized_rows

        lane_row = attempt_rows["lanes"][0]
        required = attempt.request.get("required_invariants")
        if (
            not isinstance(required, list)
            or not required
            or any(
                not isinstance(item, str) or not _INVARIANT_RE.fullmatch(item)
                for item in required
            )
            or len(required) != len(set(required))
        ):
            raise AggregateError(
                f"request has no valid unique required_invariants: {attempt.attempt_dir}"
            )
        invariant_rows = attempt_rows["invariants"]
        invariant_status = {
            row.get("invariant_id"): row.get("status") for row in invariant_rows
        }
        all_rows_pass = bool(invariant_rows) and all(
            row.get("status") == "pass" for row in invariant_rows
        )
        required_pass = all(invariant_status.get(item) == "pass" for item in required)
        derived_all_passed = all_rows_pass and required_pass
        claimed_all_passed = lane_row.get("all_invariants_passed")
        if not isinstance(claimed_all_passed, bool):
            raise AggregateError(
                f"lanes.all_invariants_passed must be boolean: {attempt.attempt_dir}"
            )
        if claimed_all_passed != derived_all_passed:
            missing = sorted(set(required) - set(invariant_status))
            failing = sorted(
                str(key)
                for key, status in invariant_status.items()
                if status != "pass"
            )
            raise AggregateError(
                "lanes.all_invariants_passed disagrees with invariant evidence: "
                f"missing={missing}, nonpassing={failing}, attempt={attempt.attempt_dir}"
            )
        if lane_row.get("terminal_category") == "passed" and not derived_all_passed:
            raise AggregateError(
                f"passed lane lacks complete passing required invariants: {attempt.attempt_dir}"
            )
    if len(manifest_hashes) != 1 or len(git_heads) != 1:
        raise AggregateError(
            f"attempt receipts span multiple manifests or commits: manifests={manifest_hashes}, heads={git_heads}"
        )
    for table_name, values in rows.items():
        keys = _SORT_KEYS[table_name]
        values.sort(key=lambda row: tuple(row.get(key) for key in keys))
        observed_keys = [tuple(row.get(key) for key in keys) for row in values]
        if len(observed_keys) != len(set(observed_keys)):
            raise AggregateError(f"duplicate deterministic keys in {table_name}")
    return rows, manifest_hashes.pop(), git_heads.pop(), max(receipt_times)


def build_tables(
    attempts: Iterable[VerifiedAttempt],
    *,
    created_at: datetime | None = None,
) -> dict[str, pa.Table]:
    rows, manifest_sha256, git_head, receipt_created_at = _rows_from_attempts(attempts)
    timestamp = created_at or receipt_created_at
    return {
        name: table_from_rows(
            name,
            table_rows,
            metadata=schema_metadata(
                name,
                manifest_sha256=manifest_sha256,
                git_head=git_head,
                created_at=timestamp,
            ),
        )
        for name, table_rows in rows.items()
    }


def _write_parquet_atomic(path: Path, table: pa.Table) -> None:
    path = lexical_absolute_path(path)
    try:
        assert_plain_ancestry(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert_plain_ancestry(path.parent)
    except (OSError, SnapshotError) as exc:
        raise AggregateError(f"aggregate output path is linked or unsafe: {path}") from exc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            version="2.6",
            use_dictionary=True,
        )
        # Windows requires a writable descriptor for fsync/FlushFileBuffers.
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def aggregate_run(run_root: str | Path) -> dict[str, pa.Table]:
    """Verify every receipt and atomically rebuild all aggregate tables."""
    try:
        root = resolve_plain_path(run_root, kind="directory")
    except SnapshotError as exc:
        raise AggregateError(f"run root is not a plain directory: {run_root}") from exc
    attempts = discover_attempts(root)
    tables = build_tables(attempts)
    for name, table in tables.items():
        _write_parquet_atomic(root / "tables" / f"{name}.parquet", table)
    return tables


def verify_run(run_root: str | Path) -> dict[str, int]:
    """Prove saved Parquet tables equal a fresh receipt-only rebuild."""
    try:
        root = resolve_plain_path(run_root, kind="directory")
    except SnapshotError as exc:
        raise AggregateError(f"run root is not a plain directory: {run_root}") from exc
    attempts = discover_attempts(root)
    rebuilt = build_tables(attempts)
    counts: dict[str, int] = {}
    for name, expected in rebuilt.items():
        path = root / "tables" / f"{name}.parquet"
        try:
            assert_plain_ancestry(path, stop=root)
        except SnapshotError as exc:
            raise AggregateError(f"aggregate table path is linked or unsafe: {path}") from exc
        if not path.is_file():
            raise AggregateError(f"aggregate table is missing: {path}")
        actual = pq.read_table(path)
        validate_table(name, actual)
        if actual.schema.metadata is None:
            raise AggregateError(f"aggregate table metadata is missing: {path}")
        if actual.schema.metadata != expected.schema.metadata:
            raise AggregateError(
                f"aggregate metadata map differs from verified receipts: {path}"
            )
        if not actual.replace_schema_metadata(None).equals(
            expected.replace_schema_metadata(None), check_metadata=False
        ):
            raise AggregateError(f"aggregate table differs from verified receipts: {path}")
        counts[name] = actual.num_rows
    return counts


__all__ = [
    "AggregateError",
    "aggregate_run",
    "build_tables",
    "discover_attempts",
    "verify_run",
]
