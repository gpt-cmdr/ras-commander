"""Exact byte-preserving replay overlay for captured HEC-RAS artifacts."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .snapshots import assert_plain_ancestry, resolve_plain_path, stable_sha256


class ReplayArtifactError(RuntimeError):
    """A pinned replay artifact could not be proved or published exactly."""


def _identity(info: os.stat_result) -> dict[str, int | str]:
    return {
        "size_bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "volume_id": str(info.st_dev),
        "file_id": str(info.st_ino),
    }


def _verify_pin(
    path: Path,
    pin: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, os.stat_result]:
    digest, info = stable_sha256(path)
    expected = (
        pin["sha256"],
        pin["size_bytes"],
        pin["mtime_ns"],
    )
    observed = (digest, info.st_size, info.st_mtime_ns)
    if observed != expected:
        raise ReplayArtifactError(
            f"{label} pin mismatch: expected={expected!r}, observed={observed!r}"
        )
    return digest, info


def overlay_replay_artifacts(
    stage_root: str | Path,
    replay: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Copy only normalized replay allowlist files into a disposable stage.

    Sources and destinations are stable-hashed before and after. Publication
    uses a same-directory hard link and therefore cannot overwrite a file that
    wins a concurrent race. No directory traversal or archived staging
    metadata is copied.
    """
    if replay is None:
        return ()
    destination_root = resolve_plain_path(stage_root, kind="directory")
    source_root = resolve_plain_path(replay["source_root"], kind="directory")
    origin = replay["data_origin"]
    records: list[dict[str, Any]] = []
    for pin in replay["files"]:
        relative = Path(pin["relative_path"])
        source = assert_plain_ancestry(source_root / relative, stop=source_root)
        source = resolve_plain_path(source, kind="file")
        target = assert_plain_ancestry(destination_root / relative, stop=destination_root)
        if target.exists() or target.is_symlink():
            raise ReplayArtifactError(f"replay destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        assert_plain_ancestry(target.parent, stop=destination_root)
        source_digest, source_before = _verify_pin(
            source, pin, label=f"replay source {relative.as_posix()}"
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".rpl-", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            _verify_pin(
                temporary,
                pin,
                label=f"replay temporary {relative.as_posix()}",
            )
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ReplayArtifactError(
                    f"replay destination appeared concurrently: {target}"
                ) from exc
            except OSError as exc:
                raise ReplayArtifactError(
                    f"atomic replay publication is unavailable: {target}"
                ) from exc
            temporary.unlink()
        finally:
            temporary.unlink(missing_ok=True)
        target_digest, target_info = _verify_pin(
            target, pin, label=f"replay destination {relative.as_posix()}"
        )
        source_after_digest, source_after = _verify_pin(
            source, pin, label=f"replay source after copy {relative.as_posix()}"
        )
        records.append(
            {
                "relative_path": relative.as_posix(),
                "source_path": str(source),
                "destination_path": str(target),
                "data_origin": origin,
                "sha256": target_digest,
                "source_sha256_before": source_digest,
                "source_sha256_after": source_after_digest,
                "source_identity_before": _identity(source_before),
                "source_identity_after": _identity(source_after),
                "destination_identity": _identity(target_info),
            }
        )
    return tuple(records)


def replay_origin_overrides(
    replay: Mapping[str, Any] | None,
) -> dict[str, str]:
    if replay is None:
        return {}
    return {
        item["relative_path"]: replay["data_origin"]
        for item in replay["files"]
    }


__all__ = [
    "ReplayArtifactError",
    "overlay_replay_artifacts",
    "replay_origin_overrides",
]
