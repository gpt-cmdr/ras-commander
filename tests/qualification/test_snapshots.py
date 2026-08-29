from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence.fingerprint_contracts import (
    QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM,
)
from scripts.qualification.execution_evidence.snapshots import (
    SnapshotError,
    diff_snapshots,
    snapshot_tree,
)


pytestmark = pytest.mark.qualification_harness


def _snapshot(root: Path, phase: str, *, known_paths=()):
    return snapshot_tree(
        root,
        run_id="run-1",
        lane_id="lane-1",
        attempt_id="attempt-1",
        phase=phase,
        root_kind="stage",
        data_origin="copied_source",
        known_paths=known_paths,
    )


def test_snapshot_hashes_regular_files_and_records_known_absence(tmp_path: Path) -> None:
    (tmp_path / "Model.prj").write_bytes(b"project")
    (tmp_path / "Model.p01.hdf").write_bytes(b"result")

    snapshot = _snapshot(tmp_path, "before", known_paths=["Model.O01"])
    rows = {row["relative_path"]: row for row in snapshot.rows}

    assert rows["Model.p01.hdf"]["result_family"] == "hdf"
    assert rows["Model.p01.hdf"]["stable_read"] is True
    assert rows["Model.O01"]["exists"] is False
    assert (
        snapshot.fingerprint_algorithm
        == QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM
    )
    assert {
        row["fingerprint_algorithm"] for row in snapshot.rows
    } == {QUALIFICATION_SNAPSHOT_FINGERPRINT_ALGORITHM}
    assert len(snapshot.content_fingerprint) == 64
    assert len(snapshot.metadata_fingerprint) == 64


def test_timestamp_rewrite_changes_metadata_not_content_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "Model.prj"
    path.write_bytes(b"same bytes")
    before = _snapshot(tmp_path, "before")
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
    after = _snapshot(tmp_path, "after")

    assert before.content_fingerprint == after.content_fingerprint
    assert before.metadata_fingerprint != after.metadata_fingerprint
    diff = diff_snapshots(before, after)
    assert diff.content_changed == ()
    assert diff.metadata_changed == ("Model.prj",)


def test_snapshot_diff_reports_add_remove_and_content_change(tmp_path: Path) -> None:
    retained = tmp_path / "retained.txt"
    removed = tmp_path / "removed.txt"
    retained.write_bytes(b"before")
    removed.write_bytes(b"remove")
    before = _snapshot(tmp_path, "before")
    retained.write_bytes(b"after")
    removed.unlink()
    (tmp_path / "added.txt").write_bytes(b"add")
    after = _snapshot(tmp_path, "after")

    diff = diff_snapshots(before, after)
    assert diff.added == ("added.txt",)
    assert diff.removed == ("removed.txt",)
    assert diff.content_changed == ("retained.txt",)


def test_known_path_escape_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="escapes"):
        _snapshot(tmp_path, "before", known_paths=["../outside.txt"])


def test_case_colliding_known_paths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="case-colliding"):
        _snapshot(tmp_path, "before", known_paths=["Model.O01", "model.o01"])


def test_symlink_file_is_rejected_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(SnapshotError, match="symlink"):
        _snapshot(tmp_path, "before")


def test_symlink_root_is_rejected_before_resolution(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "Model.prj").write_text("project", encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(SnapshotError, match="symlink"):
        _snapshot(alias, "before")


def test_nested_symlink_directory_is_rejected_without_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "foreign.txt").write_text("foreign", encoding="utf-8")
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    try:
        with pytest.raises(SnapshotError, match="symlink"):
            _snapshot(tmp_path, "before")
    finally:
        (outside / "foreign.txt").unlink(missing_ok=True)
        outside.rmdir()
