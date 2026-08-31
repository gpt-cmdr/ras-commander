from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence import run_io


pytestmark = pytest.mark.qualification_harness


def test_exact_byte_record_uses_no_overwrite_publication(tmp_path: Path) -> None:
    path = tmp_path / "manifest.source.json"
    digest = run_io.write_bytes_with_digest(path, b"exact bytes\r\n")
    assert path.read_bytes() == b"exact bytes\r\n"
    assert path.with_suffix(".sha256").read_text(encoding="ascii") == f"{digest}\n"
    with pytest.raises(FileExistsError):
        run_io.write_bytes_with_digest(path, b"replacement")
    assert path.read_bytes() == b"exact bytes\r\n"


def test_concurrent_winner_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.source.json"
    original_link = os.link

    def racing_link(source, destination, *args, **kwargs):
        destination_path = Path(destination)
        if destination_path == path:
            destination_path.write_bytes(b"concurrent winner")
            raise FileExistsError(destination)
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(run_io.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        run_io.write_bytes_with_digest(path, b"losing bytes")
    assert path.read_bytes() == b"concurrent winner"
    assert not path.with_suffix(".sha256").exists()


def test_reparse_parent_is_rejected_without_publication(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    linked_parent = tmp_path / "linked"
    real_parent.mkdir()
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    with pytest.raises(RuntimeError, match="plain filesystem path"):
        run_io.write_bytes_with_digest(linked_parent / "record.json", b"bytes")
    assert not (real_parent / "record.json").exists()
    assert not (real_parent / "record.sha256").exists()
