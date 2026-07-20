#!/usr/bin/env python
"""Reconstruct the additive RAS example namespace from retained releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


EXPECTED_PREFIX = ("data", "rasexamples", "hec-ras-7.0")


@dataclass(frozen=True)
class Release:
    generated_at: str
    release_id: str
    directory: Path
    files: tuple[dict[str, Any], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_release(directory: Path) -> Release:
    manifest_path = directory / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("files"), list):
        raise ValueError(f"Unsupported release manifest: {manifest_path}")
    generated_at = str(
        payload.get("generatedAt")
        or datetime.fromtimestamp(manifest_path.stat().st_mtime, timezone.utc).isoformat()
    )
    release_id = str(payload.get("releaseId") or directory.name)
    return Release(generated_at, release_id, directory, tuple(payload["files"]))


def discover_releases(release_root: Path) -> list[Release]:
    releases = [
        _load_release(path.parent)
        for path in release_root.glob("*/manifest.json")
        if path.is_file()
    ]
    return sorted(releases, key=lambda item: (item.generated_at, item.release_id))


def _validated_source(release: Release, entry: dict[str, Any]) -> tuple[Path, Path]:
    relative = PurePosixPath(str(entry.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:3] != EXPECTED_PREFIX:
        raise ValueError(f"Release path is outside the RAS example namespace: {entry!r}")
    source = release.directory.joinpath(*relative.parts)
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"Release artifact is missing or not regular: {source}")
    expected_bytes = int(entry.get("bytes", -1))
    expected_hash = str(entry.get("sha256") or "")
    if source.stat().st_size != expected_bytes or _sha256(source) != expected_hash:
        raise ValueError(f"Release artifact failed size/hash validation: {source}")
    destination = Path(*relative.parts[3:])
    return source, destination


def reconstruct_snapshot(
    release_root: Path,
    output_root: Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    output_root = output_root.resolve()
    if output_root.parent != release_root:
        raise ValueError("Output must be a direct child of the retained release root")
    if output_root.exists() and not replace:
        raise FileExistsError(f"Snapshot already exists: {output_root}")

    releases = discover_releases(release_root)
    if not releases:
        raise ValueError(f"No retained releases found beneath {release_root}")

    incoming = release_root / f".{output_root.name}.incoming.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    incoming.mkdir()
    applied = 0
    try:
        for release in releases:
            for entry in release.files:
                source, relative = _validated_source(release, entry)
                destination = incoming / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                applied += 1
        if output_root.exists():
            shutil.rmtree(output_root)
        incoming.replace(output_root)
    except Exception:
        shutil.rmtree(incoming, ignore_errors=True)
        raise

    summary = {
        "schema": "rascommander.webgis-snapshot/1",
        "release_count": len(releases),
        "applied_file_count": applied,
        "final_file_count": sum(1 for path in output_root.rglob("*") if path.is_file()),
        "releases": [release.release_id for release in releases],
        "output": str(output_root),
    }
    (output_root / "snapshot.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            reconstruct_snapshot(args.release_root, args.output_root, replace=args.replace),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
