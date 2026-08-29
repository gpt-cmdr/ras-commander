"""Atomic, digest-bound request, event, and receipt records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .manifest import canonical_json_bytes
from .snapshots import (
    SnapshotError,
    assert_plain_ancestry,
    lexical_absolute_path,
    resolve_plain_path,
    stable_sha256,
)


class ReceiptError(RuntimeError):
    """An immutable attempt record is incomplete or unverifiable."""


@dataclass(frozen=True)
class VerifiedAttempt:
    attempt_dir: Path
    request: dict[str, Any]
    receipt: dict[str, Any]
    request_sha256: str
    receipt_sha256: str


_LOWER_HEX = frozenset("0123456789abcdef")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INVARIANT_RE = re.compile(r"R(?:0[1-9]|1[0-2])")


def _require_utc_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReceiptError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReceiptError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes_atomic(path: Path, contents: bytes, *, replace: bool) -> None:
    path = lexical_absolute_path(path)
    # Check both before and after mkdir so an existing linked parent cannot be
    # followed merely to prepare the output directory.
    try:
        assert_plain_ancestry(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert_plain_ancestry(path.parent)
    except (OSError, SnapshotError) as exc:
        raise ReceiptError(f"record path is not a plain filesystem path: {path}") from exc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            # Explicit replacement is used only for regenerable records.  A
            # pre-existing reparse target was rejected by the ancestry check.
            os.replace(temporary, path)
        else:
            try:
                # Linking a same-directory temporary file is an atomic
                # no-overwrite publication: unlike os.replace(), it cannot
                # silently replace a record that won a concurrent race.
                os.link(temporary, path)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"immutable record already exists: {path}"
                ) from exc
            except OSError as exc:
                raise ReceiptError(
                    "atomic no-overwrite publication is unavailable for "
                    f"{path}; refusing a check-then-replace fallback"
                ) from exc
            temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_with_digest(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    replace: bool = False,
) -> str:
    """Atomically publish canonical JSON, then its lowercase SHA-256 digest."""
    target = Path(path)
    encoded = canonical_json_bytes(dict(payload))
    digest = hashlib.sha256(encoded).hexdigest()
    digest_path = target.with_suffix(".sha256")
    if lexical_absolute_path(digest_path) == lexical_absolute_path(target):
        raise ReceiptError("record path and digest path must be distinct")
    if digest_path.exists() and not replace:
        raise FileExistsError(f"immutable digest already exists: {digest_path}")
    _write_bytes_atomic(target, encoded, replace=replace)
    try:
        _write_bytes_atomic(digest_path, (digest + "\n").encode("ascii"), replace=replace)
    except Exception:
        # Publishing two directory entries cannot be one portable filesystem
        # transaction. Leave a target-only partial publication in place rather
        # than risk deleting a concurrently replaced path; verification fails
        # closed until an operator resolves the incomplete pair.
        raise
    return digest


def _stable_read_bytes(path: Path) -> bytes:
    """Read one plain regular file and reject metadata/identity drift."""
    try:
        candidate = assert_plain_ancestry(path)
        before = candidate.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ReceiptError(f"record is not a regular file: {candidate}")
        raw = candidate.read_bytes()
        after = candidate.stat()
    except SnapshotError as exc:
        raise ReceiptError(f"record path is not snapshot-safe: {path}") from exc
    except OSError as exc:
        raise ReceiptError(f"could not read {path}: {exc}") from exc
    before_identity = (
        before.st_size,
        before.st_mtime_ns,
        before.st_dev,
        before.st_ino,
    )
    after_identity = (
        after.st_size,
        after.st_mtime_ns,
        after.st_dev,
        after.st_ino,
    )
    if before_identity != after_identity:
        raise ReceiptError(f"record changed while reading: {candidate}")
    return raw


def read_json_with_digest(path: str | Path) -> tuple[dict[str, Any], str]:
    target = lexical_absolute_path(path)
    digest_path = target.with_suffix(".sha256")
    if not target.is_file() or not digest_path.is_file():
        raise ReceiptError(f"record or digest is missing: {target}")
    try:
        raw = _stable_read_bytes(target)
        expected = _stable_read_bytes(digest_path).decode("ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ReceiptError(f"could not read {target}: {exc}") from exc
    observed = hashlib.sha256(raw).hexdigest()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ReceiptError(f"invalid digest text for {target}")
    if observed != expected:
        raise ReceiptError(
            f"digest mismatch for {target}: expected {expected}, observed {observed}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"invalid JSON record {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReceiptError(f"record root must be an object: {target}")
    return payload, observed


class EventJournal:
    """Single-writer, fsynced JSONL attempt journal."""

    def __init__(self, path: str | Path, *, run_id: str, lane_id: str, attempt_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.lane_id = lane_id
        self.attempt_id = attempt_id
        self.sequence = 0
        if self.path.exists():
            raise FileExistsError(f"event journal already exists: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        phase: str,
        event_name: str,
        status: str,
        severity: str = "info",
        api: str | None = None,
        reason_code: str | None = None,
        detail: str | None = None,
        relative_path: str | None = None,
        pid: int | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.sequence += 1
        payload_json = None
        if payload is not None:
            payload_json = canonical_json_bytes(dict(payload)).decode("utf-8").rstrip("\n")
            if len(payload_json) > 16_384:
                raise ReceiptError("event payload_json exceeds the 16,384-character bound")
        event = {
            "schema_version": 1,
            "run_id": self.run_id,
            "lane_id": self.lane_id,
            "attempt_id": self.attempt_id,
            "sequence": self.sequence,
            "event_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "event_name": event_name,
            "status": status,
            "severity": severity,
            "api": api,
            "reason_code": reason_code,
            "detail": None if detail is None else detail[:1000],
            "relative_path": relative_path,
            "pid": pid,
            "payload_json": payload_json,
        }
        encoded = canonical_json_bytes(event)
        with self.path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return event


def read_event_journal(path: str | Path) -> list[dict[str, Any]]:
    journal = Path(path)
    events: list[dict[str, Any]] = []
    try:
        lines = journal.read_bytes().splitlines()
    except OSError as exc:
        raise ReceiptError(f"could not read event journal {journal}: {exc}") from exc
    for index, raw in enumerate(lines, start=1):
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReceiptError(f"invalid event journal line {index}: {exc}") from exc
        if not isinstance(event, dict) or event.get("sequence") != index:
            raise ReceiptError(f"event journal sequence mismatch at line {index}")
        events.append(event)
    return events


def _verify_referenced_artifacts(attempt_dir: Path, receipt: Mapping[str, Any]) -> None:
    references = receipt.get("referenced_artifacts", [])
    if not isinstance(references, list):
        raise ReceiptError("receipt.referenced_artifacts must be an array")
    seen_paths: set[str] = set()
    for index, item in enumerate(references):
        if not isinstance(item, Mapping):
            raise ReceiptError(f"referenced_artifacts[{index}] must be an object")
        relative = item.get("relative_path")
        expected = item.get("sha256")
        relative_path = Path(relative) if isinstance(relative, str) else None
        if (
            relative_path is None
            or not relative
            or relative_path.is_absolute()
            or relative_path.drive
            or relative_path.root
            or ".." in relative_path.parts
            or relative_path in {Path("."), Path("")}
        ):
            raise ReceiptError(f"invalid referenced artifact path at index {index}")
        path_key = relative_path.as_posix().casefold()
        if path_key in seen_paths:
            raise ReceiptError(f"duplicate referenced artifact path: {relative}")
        seen_paths.add(path_key)
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in _LOWER_HEX for character in expected)
        ):
            raise ReceiptError(f"invalid referenced artifact digest at index {index}")
        try:
            path = assert_plain_ancestry(
                attempt_dir / relative_path,
                stop=attempt_dir,
            )
        except SnapshotError as exc:
            raise ReceiptError(
                f"referenced artifact is linked or escapes attempt directory: {relative}"
            ) from exc
        if not path.is_file():
            raise ReceiptError(f"referenced artifact is missing: {relative}")
        try:
            observed, _ = stable_sha256(path)
        except SnapshotError as exc:
            raise ReceiptError(
                f"referenced artifact is not stable and plain: {relative}"
            ) from exc
        if observed != expected:
            raise ReceiptError(f"referenced artifact digest mismatch: {relative}")


def verify_attempt_receipt(attempt_dir: str | Path) -> VerifiedAttempt:
    """Verify request/receipt digests, identities, and referenced artifacts."""
    try:
        directory = resolve_plain_path(attempt_dir, kind="directory")
    except SnapshotError as exc:
        raise ReceiptError(f"attempt directory is not a plain directory: {attempt_dir}") from exc
    request, request_digest = read_json_with_digest(directory / "request.json")
    receipt, receipt_digest = read_json_with_digest(directory / "receipt.json")
    if request.get("schema_version") != 1 or receipt.get("schema_version") != 1:
        raise ReceiptError("request and receipt require schema_version=1")
    identity_fields = ("run_id", "lane_id", "attempt_id", "manifest_sha256", "git_head")
    for field in identity_fields:
        if request.get(field) != receipt.get(field):
            raise ReceiptError(f"request/receipt identity mismatch for {field}")
    for field in ("run_id", "lane_id", "attempt_id"):
        value = request.get(field)
        if (
            not isinstance(value, str)
            or not _SAFE_ID_RE.fullmatch(value)
            or value in {".", ".."}
        ):
            raise ReceiptError(f"request.{field} must be a path-safe identifier")
    if request["lane_id"] != directory.parent.name:
        raise ReceiptError("request.lane_id disagrees with its attempt directory")
    if request["attempt_id"] != directory.name:
        raise ReceiptError("request.attempt_id disagrees with its attempt directory")
    manifest_hash = request.get("manifest_sha256")
    if (
        not isinstance(manifest_hash, str)
        or len(manifest_hash) != 64
        or any(character not in _LOWER_HEX for character in manifest_hash)
    ):
        raise ReceiptError("request.manifest_sha256 must be lowercase SHA-256")
    git_head = request.get("git_head")
    if (
        not isinstance(git_head, str)
        or len(git_head) != 40
        or any(character not in _LOWER_HEX for character in git_head)
    ):
        raise ReceiptError("request.git_head must be a lowercase 40-hex commit")
    required_invariants = request.get("required_invariants")
    if (
        not isinstance(required_invariants, list)
        or not required_invariants
        or any(
            not isinstance(item, str) or not _INVARIANT_RE.fullmatch(item)
            for item in required_invariants
        )
        or len(required_invariants) != len(set(required_invariants))
    ):
        raise ReceiptError(
            "request.required_invariants must be a nonempty unique R01-R12 array"
        )
    _require_utc_timestamp(receipt.get("receipt_committed_at"), "receipt.receipt_committed_at")
    if receipt.get("request_sha256") != request_digest:
        raise ReceiptError("receipt does not bind the verified request digest")
    terminal = receipt.get("terminal_category")
    exit_code = receipt.get("worker_exit_code")
    expected_codes = {
        "passed": 0,
        "expected_failure": 10,
        "failed_invariant": 20,
        "execution_failed": 20,
        "harness_error": 30,
        "timed_out": 124,
    }
    if terminal in expected_codes and exit_code != expected_codes[terminal]:
        raise ReceiptError(
            f"worker exit code {exit_code!r} disagrees with terminal category {terminal!r}"
        )
    if terminal not in {
        "passed",
        "expected_failure",
        "failed_invariant",
        "execution_failed",
        "timed_out",
        "worker_crashed",
        "blocked",
        "harness_error",
    }:
        raise ReceiptError(f"unsupported terminal category: {terminal!r}")
    _verify_referenced_artifacts(directory, receipt)
    return VerifiedAttempt(
        attempt_dir=directory,
        request=request,
        receipt=receipt,
        request_sha256=request_digest,
        receipt_sha256=receipt_digest,
    )


__all__ = [
    "EventJournal",
    "ReceiptError",
    "VerifiedAttempt",
    "read_event_journal",
    "read_json_with_digest",
    "verify_attempt_receipt",
    "write_json_with_digest",
]
