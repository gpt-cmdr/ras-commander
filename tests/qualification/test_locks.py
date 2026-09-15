from __future__ import annotations

import json
import os
import socket
import uuid
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence.locks import (
    ExclusiveQualificationLock,
    QualificationLockError,
    inspect_lock,
    recover_stale_lock,
)
from scripts.qualification.execution_evidence.manifest import canonical_json_bytes


pytestmark = pytest.mark.qualification_harness


def test_lock_is_exclusive_and_owner_token_releases(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    first = ExclusiveQualificationLock(path, kind="run", run_id="run-1")
    payload = first.acquire()
    state = inspect_lock(path)

    assert state.owner_alive is True
    assert state.payload["token"] == payload["token"]
    with pytest.raises(QualificationLockError, match="already exists"):
        ExclusiveQualificationLock(path, kind="run", run_id="run-2").acquire()
    first.release()
    assert not path.exists()


def test_lock_refuses_to_remove_changed_token(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    lock = ExclusiveQualificationLock(path, kind="run", run_id="run-1")
    payload = lock.acquire()
    payload["token"] = "replaced-token"
    path.write_bytes(canonical_json_bytes(payload))

    with pytest.raises(QualificationLockError, match="token changed"):
        lock.release()
    assert path.exists()


def _stale_lock(path: Path, *, kind: str = "run") -> None:
    payload = {
        "schema_version": 1,
        "kind": kind,
        "token": str(uuid.UUID(int=1)),
        "run_id": "run-1",
        "lane_id": None,
        "attempt_id": None,
        "hostname": socket.gethostname(),
        "pid": max(os.getpid() + 1_000_000, 2_000_000_000),
        "process_create_time": 1.0,
        "python_executable": "python",
        "created_at": "2026-08-28T12:00:00+00:00",
        "git_head": None,
    }
    path.write_bytes(canonical_json_bytes(payload))


def test_proved_stale_generic_lock_requires_acknowledgement(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    _stale_lock(path)
    assert inspect_lock(path).owner_alive is False
    with pytest.raises(QualificationLockError, match="acknowledge"):
        recover_stale_lock(path, expected_run_id="run-1", acknowledge=False)

    receipt = recover_stale_lock(path, expected_run_id="run-1", acknowledge=True)
    assert receipt["prior_token"] == str(uuid.UUID(int=1))
    assert not path.exists()


def test_real_engine_lock_recovery_is_deferred_and_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "engine.lock"
    _stale_lock(path, kind="real_engine")
    with pytest.raises(QualificationLockError, match="unavailable"):
        recover_stale_lock(path, expected_run_id="run-1", acknowledge=True)
    assert path.exists()


def test_nonempty_lock_captures_post_close_identity_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    lock = ExclusiveQualificationLock(path, kind="run", run_id="run-1")
    payload = lock.acquire()
    assert path.stat().st_size == len(canonical_json_bytes(payload))
    assert lock._file_identity is not None
    assert lock._file_identity[:2] == (path.stat().st_dev, path.stat().st_ino)
    lock.release()
    assert not path.exists()


def test_lock_parent_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(QualificationLockError, match="not plain"):
        ExclusiveQualificationLock(
            alias / "run.lock",
            kind="run",
            run_id="run-1",
        ).acquire()
    assert not (target / "run.lock").exists()


def test_release_quarantines_replacement_instead_of_deleting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "run.lock"
    lock = ExclusiveQualificationLock(path, kind="run", run_id="run-1")
    lock.acquire()
    replacement = tmp_path / "replacement.lock"
    replacement_payload = {
        "schema_version": 1,
        "kind": "run",
        "token": str(uuid.uuid4()),
        "run_id": "run-2",
    }
    replacement.write_bytes(canonical_json_bytes(replacement_payload))
    original_rename = os.rename
    raced = False

    def race_before_quarantine(source, destination):
        nonlocal raced
        if not raced and Path(source) == path:
            raced = True
            os.replace(replacement, path)
        return original_rename(source, destination)

    monkeypatch.setattr(os, "rename", race_before_quarantine)
    with pytest.raises(QualificationLockError, match="token changed|identity changed"):
        lock.release()
    retired = list(tmp_path.glob(".run.lock.*.retired"))
    assert len(retired) == 1
    assert json.loads(retired[0].read_text(encoding="utf-8"))["run_id"] == "run-2"
