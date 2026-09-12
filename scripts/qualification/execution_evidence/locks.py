"""Exclusive, owner-token-bound qualification file locks."""

from __future__ import annotations

import json
import math
import os
import socket
import stat
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from .manifest import canonical_json_bytes
from .snapshots import (
    SnapshotError,
    assert_plain_ancestry,
    lexical_absolute_path,
)


class QualificationLockError(RuntimeError):
    """An exclusive qualification lock could not be acquired or proved safe."""


@dataclass(frozen=True)
class LockState:
    path: Path
    payload: dict[str, Any]
    owner_alive: bool | None
    reason_code: str
    file_identity: tuple[int, int, int, int, int] | None = None


_LOCK_KINDS = {"run", "lane", "attempt", "real_engine"}


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_lock_payload(path: Path) -> tuple[dict[str, Any], tuple[int, int, int, int, int]]:
    """Read one plain lock while proving its identity stayed stable."""
    try:
        candidate = assert_plain_ancestry(path)
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise QualificationLockError(f"lock is not a regular file: {candidate}")
        raw = candidate.read_bytes()
        after = candidate.lstat()
    except SnapshotError as exc:
        raise QualificationLockError(f"lock path is not plain: {path}") from exc
    except OSError as exc:
        raise QualificationLockError(f"cannot read lock {path}: {exc}") from exc
    identity = _file_identity(before)
    if _file_identity(after) != identity:
        raise QualificationLockError(f"lock changed while being read: {candidate}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationLockError(f"cannot parse lock {candidate}: {exc}") from exc
    if not isinstance(payload, dict):
        raise QualificationLockError(f"lock payload must be an object: {candidate}")
    return payload, identity


def _retire_verified_lock(
    path: Path,
    *,
    expected_identity: tuple[int, int, int, int, int],
    expected_token: str | None,
) -> None:
    """Atomically rename an identified lock, reverify it, then delete it.

    Renaming to a random same-directory quarantine prevents the ordinary
    compare-then-unlink race from deleting a new owner at the original path.
    Python does not expose a portable Windows unlink-by-open-handle primitive;
    a hostile actor that guesses and replaces the random quarantine name in
    the final lstat/unlink interval remains an irreducible residual.  The final
    identity check makes that residual fail closed for non-malicious races.
    """
    try:
        candidate = assert_plain_ancestry(path)
    except SnapshotError as exc:
        raise QualificationLockError(f"lock path is not plain: {path}") from exc
    try:
        if _file_identity(candidate.lstat()) != expected_identity:
            raise QualificationLockError(
                f"lock identity changed; refusing removal: {candidate}"
            )
    except FileNotFoundError as exc:
        raise QualificationLockError(f"lock disappeared before removal: {candidate}") from exc
    quarantine = candidate.with_name(
        f".{candidate.name}.{uuid.uuid4().hex}.retired"
    )
    try:
        os.rename(candidate, quarantine)
    except OSError as exc:
        raise QualificationLockError(
            f"could not quarantine verified lock {candidate}: {exc}"
        ) from exc
    if expected_token is None:
        try:
            observed_identity = _file_identity(quarantine.lstat())
        except OSError as exc:
            raise QualificationLockError(
                f"could not reverify quarantined lock {quarantine}: {exc}"
            ) from exc
    else:
        payload, observed_identity = _read_lock_payload(quarantine)
        if payload.get("token") != expected_token:
            raise QualificationLockError(
                f"quarantined lock token changed; retained at {quarantine}"
            )
    if observed_identity != expected_identity:
        raise QualificationLockError(
            f"quarantined lock identity changed; retained at {quarantine}"
        )
    try:
        if _file_identity(quarantine.lstat()) != expected_identity:
            raise QualificationLockError(
                f"quarantined lock changed before deletion: {quarantine}"
            )
        quarantine.unlink()
    except OSError as exc:
        raise QualificationLockError(
            f"could not delete quarantined lock {quarantine}: {exc}"
        ) from exc


class ExclusiveQualificationLock:
    """An `O_EXCL` lock removable only by its random owner token."""

    def __init__(
        self,
        path: str | Path,
        *,
        kind: str,
        run_id: str,
        lane_id: str | None = None,
        attempt_id: str | None = None,
        git_head: str | None = None,
    ) -> None:
        if kind not in _LOCK_KINDS:
            raise QualificationLockError(
                f"unsupported qualification lock kind: {kind!r}"
            )
        self.path = lexical_absolute_path(path)
        self.kind = kind
        self.run_id = run_id
        self.lane_id = lane_id
        self.attempt_id = attempt_id
        self.git_head = git_head
        self.token: str | None = None
        self._file_identity: tuple[int, int, int, int, int] | None = None

    def acquire(self) -> dict[str, Any]:
        if self.token is not None:
            raise QualificationLockError("lock object already owns a lock")
        try:
            assert_plain_ancestry(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            assert_plain_ancestry(self.path.parent)
        except (OSError, SnapshotError) as exc:
            raise QualificationLockError(
                f"qualification lock path is not plain: {self.path}"
            ) from exc
        token = str(uuid.uuid4())
        process = psutil.Process(os.getpid())
        payload = {
            "schema_version": 1,
            "kind": self.kind,
            "token": token,
            "run_id": self.run_id,
            "lane_id": self.lane_id,
            "attempt_id": self.attempt_id,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "process_create_time": process.create_time(),
            "python_executable": sys.executable,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_head": self.git_head,
        }
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError as exc:
            raise QualificationLockError(f"qualification lock already exists: {self.path}") from exc
        opened_identity = _file_identity(os.fstat(descriptor))
        created_identity = None
        try:
            encoded = canonical_json_bytes(payload)
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise QualificationLockError(
                        f"incomplete qualification lock write: {self.path}"
                    )
                remaining = remaining[written:]
            os.fsync(descriptor)
            # Capture the full size/time identity only after the immutable
            # payload is durable; the pre-write descriptor necessarily has
            # different size and timestamps.
            created_identity = _file_identity(os.fstat(descriptor))
        except Exception:
            os.close(descriptor)
            try:
                partial_identity = _file_identity(self.path.lstat())
            except OSError:
                partial_identity = None
            if (
                partial_identity is not None
                and partial_identity[:2] == opened_identity[:2]
            ):
                _retire_verified_lock(
                    self.path,
                    expected_identity=partial_identity,
                    expected_token=None,
                )
            raise
        else:
            os.close(descriptor)
        try:
            observed_identity = _file_identity(self.path.lstat())
        except OSError as exc:
            raise QualificationLockError(
                f"could not verify published qualification lock: {self.path}"
            ) from exc
        # Windows/SMB may finalize timestamps lazily when the descriptor
        # closes.  Prove the same file object (volume/file ID), then retain the
        # full post-close identity for all later ownership checks.
        if created_identity is None or created_identity[:2] != observed_identity[:2]:
            raise QualificationLockError(
                f"qualification lock identity changed during publication: {self.path}"
            )
        self.token = token
        self._file_identity = observed_identity
        return payload

    def release(self) -> None:
        if self.token is None:
            raise QualificationLockError("lock object does not own a lock")
        if self._file_identity is None:
            raise QualificationLockError("owned lock has no captured file identity")
        payload, identity = _read_lock_payload(self.path)
        if payload.get("token") != self.token:
            raise QualificationLockError(f"lock token changed; refusing removal: {self.path}")
        if identity != self._file_identity:
            raise QualificationLockError(
                f"lock identity changed; refusing removal: {self.path}"
            )
        _retire_verified_lock(
            self.path,
            expected_identity=identity,
            expected_token=self.token,
        )
        self.token = None
        self._file_identity = None

    def __enter__(self) -> "ExclusiveQualificationLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def inspect_lock(path: str | Path) -> LockState:
    lock_path = lexical_absolute_path(path)
    try:
        payload, identity = _read_lock_payload(lock_path)
    except QualificationLockError as exc:
        if not lock_path.exists() and not lock_path.is_symlink():
            return LockState(lock_path, {}, False, "lock_missing")
        cause = exc.__cause__
        if isinstance(cause, (UnicodeError, json.JSONDecodeError)):
            reason = f"lock_unreadable:{type(cause).__name__}"
        elif isinstance(cause, SnapshotError):
            reason = "lock_path_unsafe"
        else:
            reason = f"lock_unreadable:{type(cause or exc).__name__}"
        return LockState(lock_path, {}, None, reason)
    except FileNotFoundError:
        return LockState(lock_path, {}, False, "lock_missing")
    if payload.get("schema_version") != 1:
        return LockState(lock_path, payload, None, "lock_schema_invalid", identity)
    if payload.get("kind") not in _LOCK_KINDS:
        return LockState(lock_path, payload, None, "lock_kind_invalid", identity)
    try:
        uuid.UUID(str(payload.get("token")))
    except (ValueError, TypeError, AttributeError):
        return LockState(lock_path, payload, None, "lock_token_invalid", identity)
    if payload.get("hostname") != socket.gethostname():
        return LockState(
            lock_path,
            payload,
            None,
            "lock_owner_remote_or_unknown",
            identity,
        )
    pid = payload.get("pid")
    create_time = payload.get("process_create_time")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(create_time, (int, float))
        or isinstance(create_time, bool)
        or not math.isfinite(float(create_time))
    ):
        return LockState(
            lock_path, payload, None, "lock_process_identity_invalid", identity
        )
    try:
        process = psutil.Process(pid)
        observed_create_time = process.create_time()
    except psutil.NoSuchProcess:
        return LockState(lock_path, payload, False, "lock_owner_absent", identity)
    except (psutil.AccessDenied, OSError):
        return LockState(lock_path, payload, None, "lock_owner_state_unknown", identity)
    if abs(observed_create_time - float(create_time)) > 0.001:
        return LockState(lock_path, payload, False, "lock_pid_reused", identity)
    return LockState(lock_path, payload, True, "lock_owner_alive", identity)


def recover_stale_lock(
    path: str | Path,
    *,
    expected_run_id: str,
    acknowledge: bool,
) -> dict[str, Any]:
    """Remove only a proved-stale generic lock and return a recovery receipt.

    Real-engine lock recovery additionally requires HEC-RAS process inspection
    and is intentionally deferred until the engine supervisor is implemented.
    """
    if not acknowledge:
        raise QualificationLockError("lock recovery requires acknowledge=True")
    state = inspect_lock(path)
    if state.payload.get("run_id") != expected_run_id:
        raise QualificationLockError("lock run_id does not match expected_run_id")
    if state.payload.get("kind") == "real_engine":
        raise QualificationLockError(
            "real-engine lock recovery is unavailable before exact HEC-RAS process checks are wired"
        )
    if state.owner_alive is not False:
        raise QualificationLockError(
            f"lock owner absence is not proved: {state.reason_code}"
        )
    if state.file_identity is None:
        raise QualificationLockError("stale lock has no verified file identity")
    lock_path = lexical_absolute_path(path)
    observed_token = state.payload.get("token")
    current, current_identity = _read_lock_payload(lock_path)
    if current_identity != state.file_identity:
        raise QualificationLockError("lock identity changed during recovery inspection")
    if current.get("token") != observed_token:
        raise QualificationLockError("lock changed during recovery inspection")
    _retire_verified_lock(
        lock_path,
        expected_identity=current_identity,
        expected_token=str(observed_token),
    )
    return {
        "schema_version": 1,
        "recovered_at": datetime.now(timezone.utc).isoformat(),
        "path": str(lock_path),
        "run_id": expected_run_id,
        "prior_token": observed_token,
        "reason_code": state.reason_code,
        "recovery_pid": os.getpid(),
    }


__all__ = [
    "ExclusiveQualificationLock",
    "LockState",
    "QualificationLockError",
    "inspect_lock",
    "recover_stale_lock",
]
