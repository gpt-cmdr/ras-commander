"""Phase-2 atomic byte records kept separate from foundation receipt code."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .snapshots import SnapshotError, assert_plain_ancestry, lexical_absolute_path


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, contents: bytes) -> None:
    path = lexical_absolute_path(path)
    try:
        assert_plain_ancestry(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        assert_plain_ancestry(path.parent)
    except (OSError, SnapshotError) as exc:
        raise RuntimeError(f"record path is not a plain filesystem path: {path}") from exc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Same-directory hard-link publication is atomic and cannot
            # overwrite a path that wins a concurrent race.
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"immutable record already exists: {path}") from exc
        except OSError as exc:
            raise RuntimeError(
                f"atomic no-overwrite publication is unavailable for {path}"
            ) from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_bytes_with_digest(path: str | Path, contents: bytes) -> str:
    """Atomically publish exact bytes followed by a SHA-256 sibling."""
    if not isinstance(contents, bytes):
        raise TypeError("contents must be bytes")
    target = lexical_absolute_path(path)
    digest_path = target.with_suffix(".sha256")
    if digest_path == target:
        raise RuntimeError("record path and digest path must be distinct")
    if digest_path.exists():
        raise FileExistsError(f"immutable digest already exists: {digest_path}")
    digest = hashlib.sha256(contents).hexdigest()
    _write_atomic(target, contents)
    # If digest publication fails, retain the target-only partial. Readers
    # fail closed and an operator can identify the incomplete publication.
    _write_atomic(digest_path, (digest + "\n").encode("ascii"))
    return digest


__all__ = ["write_bytes_with_digest"]
