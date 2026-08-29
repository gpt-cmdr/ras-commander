from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence import replay


pytestmark = [pytest.mark.qualification_harness, pytest.mark.offline_evidence]


def _replay_packet(source_root: Path, relative_path: str) -> dict:
    source = source_root / relative_path
    info = source.stat()
    return {
        "source_root": str(source_root),
        "data_origin": "staged_execution_output",
        "files": [
            {
                "relative_path": relative_path,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
        ],
    }


def test_replay_overlay_is_exact_immutable_and_no_overwrite(tmp_path: Path) -> None:
    source_root = tmp_path / "replay"
    stage_root = tmp_path / "stage"
    source_root.mkdir()
    stage_root.mkdir()
    source = source_root / "Model.O01"
    source.write_bytes(b"captured result bytes\r\n")
    packet = _replay_packet(source_root, source.name)
    source_before = source.read_bytes(), source.stat().st_mtime_ns

    records = replay.overlay_replay_artifacts(stage_root, packet)

    target = stage_root / source.name
    assert target.read_bytes() == source_before[0]
    assert target.stat().st_mtime_ns == source_before[1]
    assert source.read_bytes() == source_before[0]
    assert source.stat().st_mtime_ns == source_before[1]
    assert records[0]["source_sha256_before"] == records[0]["source_sha256_after"]
    assert records[0]["sha256"] == packet["files"][0]["sha256"]
    with pytest.raises(replay.ReplayArtifactError, match="already exists"):
        replay.overlay_replay_artifacts(stage_root, packet)
    assert target.read_bytes() == source_before[0]


def test_replay_overlay_rejects_source_pin_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "replay"
    stage_root = tmp_path / "stage"
    source_root.mkdir()
    stage_root.mkdir()
    source = source_root / "Model.O01"
    source.write_bytes(b"original")
    packet = _replay_packet(source_root, source.name)
    source.write_bytes(b"changed")

    with pytest.raises(replay.ReplayArtifactError, match="pin mismatch"):
        replay.overlay_replay_artifacts(stage_root, packet)
    assert not (stage_root / source.name).exists()


def test_replay_publication_never_overwrites_concurrent_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "replay"
    stage_root = tmp_path / "stage"
    source_root.mkdir()
    stage_root.mkdir()
    source = source_root / "Model.O01"
    source.write_bytes(b"captured")
    packet = _replay_packet(source_root, source.name)
    target = stage_root / source.name
    original_link = replay.os.link

    def racing_link(source_path, destination_path, *args, **kwargs):
        if Path(destination_path) == target:
            target.write_bytes(b"concurrent winner")
            raise FileExistsError(destination_path)
        return original_link(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(replay.os, "link", racing_link)
    with pytest.raises(replay.ReplayArtifactError, match="appeared concurrently"):
        replay.overlay_replay_artifacts(stage_root, packet)
    assert target.read_bytes() == b"concurrent winner"
