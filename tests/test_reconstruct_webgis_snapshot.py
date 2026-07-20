from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.example_library.reconstruct_webgis_snapshot import reconstruct_snapshot


def _release(root: Path, release_id: str, generated_at: str, files: dict[str, bytes]) -> None:
    directory = root / release_id
    entries = []
    for relative, content in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseId": release_id,
                "generatedAt": generated_at,
                "files": entries,
            }
        ),
        encoding="utf-8",
    )


def test_reconstructs_additive_namespace_in_manifest_time_order(tmp_path: Path) -> None:
    relative = "data/rasexamples/hec-ras-7.0/projects/demo/viewer/manifest.json"
    _release(tmp_path, "later", "2026-07-16T02:00:00Z", {relative: b"new"})
    _release(tmp_path, "earlier", "2026-07-16T01:00:00Z", {relative: b"old"})
    _release(
        tmp_path,
        "addition",
        "2026-07-16T03:00:00Z",
        {"data/rasexamples/hec-ras-7.0/catalog.json": b"catalog"},
    )

    summary = reconstruct_snapshot(tmp_path, tmp_path / "snapshot")

    assert (tmp_path / "snapshot/projects/demo/viewer/manifest.json").read_bytes() == b"new"
    assert (tmp_path / "snapshot/catalog.json").read_bytes() == b"catalog"
    assert summary["release_count"] == 3
    assert summary["final_file_count"] == 2


def test_rejects_artifact_outside_namespace(tmp_path: Path) -> None:
    _release(tmp_path, "bad", "2026-07-16T01:00:00Z", {"data/other/file.txt": b"bad"})

    with pytest.raises(ValueError, match="outside"):
        reconstruct_snapshot(tmp_path, tmp_path / "snapshot")
