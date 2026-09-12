"""Stable, read-only project-tree snapshots for qualification receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from .schemas import QUALIFICATION_SCHEMA_VERSION


class SnapshotError(RuntimeError):
    """A filesystem population or stable-read invariant could not be proved."""


@dataclass(frozen=True)
class TreeSnapshot:
    snapshot_id: str
    phase: str
    captured_at: datetime
    root: Path
    root_kind: str
    fingerprint_algorithm: str
    content_fingerprint: str
    metadata_fingerprint: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SnapshotDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    content_changed: tuple[str, ...]
    metadata_changed: tuple[str, ...]


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def _is_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    if path.is_symlink():
        return True
    current = info if info is not None else path.lstat()
    attributes = getattr(current, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def lexical_absolute_path(path: str | Path) -> Path:
    """Return an absolute spelling without resolving links or reparse points."""
    return Path(os.path.abspath(os.fspath(path)))


def assert_plain_ancestry(path: str | Path, *, stop: str | Path | None = None) -> Path:
    """Reject every existing symlink/reparse component in one lexical path.

    The check intentionally happens before ``Path.resolve()`` so a linked root
    cannot erase the evidence that the caller supplied an alias.  This is a
    fail-closed path-policy check, not a claim that pathname operations can be
    made race-free on every supported filesystem.
    """
    candidate = lexical_absolute_path(path)
    boundary = lexical_absolute_path(stop) if stop is not None else None
    if boundary is not None:
        try:
            candidate.relative_to(boundary)
        except ValueError as exc:
            raise SnapshotError(
                f"path escapes required plain ancestry root: {candidate}"
            ) from exc
    current = candidate
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            info = None
        except OSError as exc:
            raise SnapshotError(
                f"could not inspect path ancestry component {current}: {exc}"
            ) from exc
        if info is not None and _is_reparse(current, info):
            raise SnapshotError(
                f"reparse or symlink path is not snapshot-safe: {current}"
            )
        if current == boundary or current.parent == current:
            return candidate
        current = current.parent


def resolve_plain_path(
    path: str | Path,
    *,
    kind: str | None = None,
) -> Path:
    """Resolve an existing path only after proving its ancestry is plain."""
    lexical = assert_plain_ancestry(path)
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SnapshotError(f"could not resolve required path {lexical}: {exc}") from exc
    if kind == "directory" and not resolved.is_dir():
        raise SnapshotError(f"required path is not a directory: {resolved}")
    if kind == "file" and not resolved.is_file():
        raise SnapshotError(f"required path is not a regular file: {resolved}")
    return resolved


def stable_sha256(path: Path) -> tuple[str, os.stat_result]:
    """Hash a regular file and reject identity or metadata drift during read."""
    path = assert_plain_ancestry(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise SnapshotError(f"not a regular file: {path}")
    if _is_reparse(path, path.lstat()):
        raise SnapshotError(f"reparse or symlink file is not snapshot-safe: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SnapshotError(f"could not hash {path}: {exc}") from exc
    after = path.stat()
    if _identity(before) != _identity(after):
        raise SnapshotError(f"file changed while hashing: {path}")
    return digest.hexdigest(), after


def _canonical_digest(rows: list[dict[str, Any]], *, metadata: bool) -> str:
    payload = []
    for row in rows:
        if not row["exists"] or not row["is_file"]:
            continue
        item = {
            "relative_path": row["relative_path"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
        }
        if metadata:
            item.update(
                {
                    "mtime_ns": row["mtime_ns"],
                    "volume_id": row["volume_id"],
                    "file_id": row["file_id"],
                }
            )
        payload.append(item)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _classify_artifact(relative_path: str) -> tuple[str, str | None]:
    name = Path(relative_path).name
    lowered = name.casefold()
    if re.search(r"\.p\d{2}\.hdf$", lowered) and ".tmp.hdf" not in lowered:
        return "plan_result", "hdf"
    if re.search(r"\.o\d{2}$", lowered):
        return "plan_result", "legacy"
    if lowered.endswith((".comp_msgs.txt", ".computemsgs.txt")) or re.search(
        r"\.bco\d{2}$", lowered
    ):
        return "compute_message", None
    if lowered.endswith(".tmp.hdf"):
        return "temporary_preprocess", None
    if re.search(r"\.p\d{2}$", lowered):
        return "plan", None
    if lowered.endswith(".prj"):
        return "project", None
    return "project_file", None


def snapshot_tree(
    root: str | Path,
    *,
    run_id: str,
    lane_id: str,
    attempt_id: str,
    phase: str,
    root_kind: str,
    data_origin: str,
    known_paths: Iterable[str | Path] = (),
    origin_overrides: Mapping[str, str] | None = None,
) -> TreeSnapshot:
    """Capture a stable sorted inventory without following linked paths."""
    root_path = resolve_plain_path(root, kind="directory")
    captured_at = datetime.now(timezone.utc)
    snapshot_id = str(uuid.uuid4())
    overrides = dict(origin_overrides or {})
    discovered: dict[str, Path] = {}

    for current_text, directory_names, file_names in os.walk(root_path, followlinks=False):
        current = Path(current_text)
        assert_plain_ancestry(current, stop=root_path)
        for directory_name in list(directory_names):
            directory = current / directory_name
            if _is_reparse(directory):
                raise SnapshotError(f"reparse or symlink directory is not allowed: {directory}")
        for file_name in file_names:
            path = current / file_name
            assert_plain_ancestry(path, stop=root_path)
            relative = path.relative_to(root_path).as_posix()
            key = relative.casefold()
            if key in discovered:
                raise SnapshotError(
                    f"case-colliding project paths are ambiguous: {relative} and "
                    f"{discovered[key].relative_to(root_path).as_posix()}"
                )
            discovered[key] = path

    normalized_known: dict[str, str] = {}
    for raw in known_paths:
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                candidate = assert_plain_ancestry(candidate, stop=root_path)
                relative = candidate.relative_to(root_path).as_posix()
            except ValueError as exc:
                raise SnapshotError(f"known path escapes snapshot root: {candidate}") from exc
        else:
            if ".." in candidate.parts:
                raise SnapshotError(f"known path escapes snapshot root: {candidate}")
            relative = candidate.as_posix().lstrip("./")
            if relative:
                assert_plain_ancestry(root_path / relative, stop=root_path)
        if not relative or relative == ".":
            raise SnapshotError("known path must identify a child of the snapshot root")
        key = relative.casefold()
        existing = normalized_known.get(key)
        if existing is not None and existing != relative:
            raise SnapshotError(f"case-colliding known paths: {existing} and {relative}")
        normalized_known[key] = relative

    rows: list[dict[str, Any]] = []
    all_keys = sorted(set(discovered) | set(normalized_known))
    for key in all_keys:
        path = discovered.get(key)
        relative = (
            path.relative_to(root_path).as_posix()
            if path is not None
            else normalized_known[key]
        )
        artifact_kind, result_family = _classify_artifact(relative)
        origin = overrides.get(relative, overrides.get(key, data_origin))
        if path is None:
            rows.append(
                {
                    "schema_version": QUALIFICATION_SCHEMA_VERSION,
                    "run_id": run_id,
                    "lane_id": lane_id,
                    "attempt_id": attempt_id,
                    "snapshot_id": snapshot_id,
                    "phase": phase,
                    "captured_at": captured_at,
                    "root_kind": root_kind,
                    "root_path": str(root_path),
                    "relative_path": relative,
                    "artifact_kind": artifact_kind,
                    "result_family": result_family,
                    "data_origin": origin,
                    "exists": False,
                    "is_file": False,
                    "is_dir": False,
                    "size_bytes": None,
                    "mtime_ns": None,
                    "volume_id": None,
                    "file_id": None,
                    "sha256": None,
                    "stable_read": None,
                    "fingerprint_algorithm": (
                        QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
                    ),
                    "content_fingerprint": None,
                    "metadata_fingerprint": None,
                    "reason_code": "known_path_absent",
                    "detail": None,
                }
            )
            continue
        digest, info = stable_sha256(path)
        rows.append(
            {
                "schema_version": QUALIFICATION_SCHEMA_VERSION,
                "run_id": run_id,
                "lane_id": lane_id,
                "attempt_id": attempt_id,
                "snapshot_id": snapshot_id,
                "phase": phase,
                "captured_at": captured_at,
                "root_kind": root_kind,
                "root_path": str(root_path),
                "relative_path": relative,
                "artifact_kind": artifact_kind,
                "result_family": result_family,
                "data_origin": origin,
                "exists": True,
                "is_file": True,
                "is_dir": False,
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "volume_id": str(info.st_dev),
                "file_id": str(info.st_ino),
                "sha256": digest,
                "stable_read": True,
                "fingerprint_algorithm": (
                    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
                ),
                "content_fingerprint": None,
                "metadata_fingerprint": None,
                "reason_code": "stable_file_hashed",
                "detail": None,
            }
        )

    content_fingerprint = _canonical_digest(rows, metadata=False)
    metadata_fingerprint = _canonical_digest(rows, metadata=True)
    for row in rows:
        row["content_fingerprint"] = content_fingerprint
        row["metadata_fingerprint"] = metadata_fingerprint
    return TreeSnapshot(
        snapshot_id=snapshot_id,
        phase=phase,
        captured_at=captured_at,
        root=root_path,
        root_kind=root_kind,
        fingerprint_algorithm=QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
        content_fingerprint=content_fingerprint,
        metadata_fingerprint=metadata_fingerprint,
        rows=tuple(rows),
    )


def diff_snapshots(before: TreeSnapshot, after: TreeSnapshot) -> SnapshotDiff:
    """Return exact population, content, and metadata changes."""
    before_rows = {row["relative_path"].casefold(): row for row in before.rows if row["exists"]}
    after_rows = {row["relative_path"].casefold(): row for row in after.rows if row["exists"]}
    before_keys = set(before_rows)
    after_keys = set(after_rows)
    shared = before_keys & after_keys
    return SnapshotDiff(
        added=tuple(after_rows[key]["relative_path"] for key in sorted(after_keys - before_keys)),
        removed=tuple(before_rows[key]["relative_path"] for key in sorted(before_keys - after_keys)),
        content_changed=tuple(
            after_rows[key]["relative_path"]
            for key in sorted(shared)
            if before_rows[key]["sha256"] != after_rows[key]["sha256"]
        ),
        metadata_changed=tuple(
            after_rows[key]["relative_path"]
            for key in sorted(shared)
            if (
                before_rows[key]["mtime_ns"],
                before_rows[key]["volume_id"],
                before_rows[key]["file_id"],
            )
            != (
                after_rows[key]["mtime_ns"],
                after_rows[key]["volume_id"],
                after_rows[key]["file_id"],
            )
        ),
    )


__all__ = [
    "SnapshotDiff",
    "SnapshotError",
    "TreeSnapshot",
    "assert_plain_ancestry",
    "diff_snapshots",
    "lexical_absolute_path",
    "resolve_plain_path",
    "snapshot_tree",
    "stable_sha256",
]
