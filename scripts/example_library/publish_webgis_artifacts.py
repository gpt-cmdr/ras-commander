#!/usr/bin/env python
"""Stage a RAS example release on CLB03 and invoke its restricted publisher.

The WebGIS host intentionally exposes its artifact dataset read-only to the
public-serving container. This command uses the trusted CLB03 staging host as
the sole bridge: it wraps one validated HEC-RAS version root in the production
``data/rasexamples`` namespace, then asks the host-managed publisher to
promote that release.

The CLB03 publisher is responsible for authenticating to WebGIS with its
dedicated key.  This script never carries deployment keys, never uses a remote
shell on WebGIS, and deliberately does not pass ``--delete`` to rsync.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
REMOTE_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
EXPECTED_ROOT_NAME = "hec-ras-7.0"


def validate_release_id(release_id: str) -> str:
    """Return a safe release identifier for a remote path."""
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError(
            "Release ID must be 1-80 ASCII letters, digits, dots, underscores, or hyphens "
            "and must not start with punctuation."
        )
    return release_id


def validate_webgis_root(webgis_root: Path) -> Path:
    """Validate an HEC-RAS 7.0 version root produced by the catalog builder."""
    root = webgis_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"WebGIS release root does not exist: {root}")
    if root.name != EXPECTED_ROOT_NAME:
        raise ValueError(
            f"WebGIS release root must be named {EXPECTED_ROOT_NAME}, got {root}"
        )
    return root


def validate_remote_host(host: str) -> str:
    """Return a hostname or SSH config alias safe to pass to OpenSSH."""
    if not REMOTE_HOST_RE.fullmatch(host):
        raise ValueError(f"Unsafe CLB03 host name: {host!r}")
    return host


def validate_remote_path(path: str, *, label: str) -> str:
    """Return a normalized absolute POSIX path accepted by the remote shell."""
    if not REMOTE_PATH_RE.fullmatch(path) or "//" in path or "/../" in f"/{path}/":
        raise ValueError(f"Unsafe {label}: {path!r}")
    return path.rstrip("/") or "/"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for block in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(webgis_root: Path, release_id: str) -> dict[str, Any]:
    """Describe every regular file in the immutable candidate release."""
    files: list[dict[str, Any]] = []
    for path in sorted(webgis_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not publishable WebGIS artifacts: {path}")
        if path.is_file():
            relative_path = (Path("data") / "rasexamples" / webgis_root.name / path.relative_to(webgis_root)).as_posix()
            files.append(
                {
                    "path": relative_path,
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    if not files:
        raise ValueError(f"No files found beneath WebGIS release root: {webgis_root}")
    return {
        "schemaVersion": 1,
        "releaseId": validate_release_id(release_id),
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }


def command_for_display(command: Sequence[str]) -> str:
    """Render an argument vector without relying on a shell."""
    return " ".join(json.dumps(argument) for argument in command)


def run(command: Sequence[str], *, dry_run: bool) -> None:
    print(command_for_display(command))
    if not dry_run:
        subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--webgis-root",
        type=Path,
        required=True,
        help="Local hec-ras-7.0 release root to promote.",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="Remote immutable staging directory name. Defaults to a UTC timestamp.",
    )
    parser.add_argument("--clb03-host", default="CLB03")
    parser.add_argument(
        "--clb03-stage-root",
        default="/mnt/pool_12tb/rascommander-webgis-staging",
        help="Trusted staging area on CLB03, outside the public artifact dataset.",
    )
    parser.add_argument(
        "--publisher-command",
        default="/usr/local/sbin/rascommander-webgis-publish",
        help="Root-owned CLB03 command that validates and promotes one release directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print commands without changing either remote host.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    webgis_root = validate_webgis_root(args.webgis_root)
    clb03_host = validate_remote_host(args.clb03_host)
    clb03_stage_root = validate_remote_path(args.clb03_stage_root, label="CLB03 stage root")
    publisher_command = validate_remote_path(args.publisher_command, label="publisher command")
    release_id = validate_release_id(
        args.release_id
        or f"rasexamples-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    manifest = build_manifest(webgis_root, release_id)
    remote_release = f"{clb03_stage_root}/{release_id}"
    with tempfile.TemporaryDirectory(prefix="rascommander-webgis-") as temporary_directory:
        manifest_path = Path(temporary_directory) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                clb03_host,
                "install",
                "-d",
                "-m",
                "0750",
                f"{remote_release}/data/rasexamples",
            ],
            dry_run=args.dry_run,
        )
        run(
            [
                "scp",
                "-p",
                "-r",
                str(webgis_root),
                f"{clb03_host}:{remote_release}/data/rasexamples/",
            ],
            dry_run=args.dry_run,
        )
        run(
            [
                "scp",
                "-p",
                str(manifest_path),
                f"{clb03_host}:{remote_release}/",
            ],
            dry_run=args.dry_run,
        )
        run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                clb03_host,
                "find",
                remote_release,
                "-type",
                "d",
                "-exec",
                "chmod",
                "0750",
                "{}",
                "+",
            ],
            dry_run=args.dry_run,
        )
        run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                clb03_host,
                "find",
                remote_release,
                "-type",
                "f",
                "-exec",
                "chmod",
                "0640",
                "{}",
                "+",
            ],
            dry_run=args.dry_run,
        )
        run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                clb03_host,
                publisher_command,
                "--release-dir",
                remote_release,
            ],
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Publishing stopped before promotion. The CLB03 staged release was retained for retry; "
            f"the failing command exited with status {error.returncode}."
        ) from None
