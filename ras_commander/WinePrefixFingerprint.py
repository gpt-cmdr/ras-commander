"""Deterministic, content-based fingerprints for isolated Wine prefixes.

The fingerprint deliberately excludes filesystem metadata such as timestamps,
ownership, permissions, inode numbers, and the absolute prefix path. It is
therefore suitable for proving that independently copied prefixes contain the
same files without disclosing Wine registry values.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Tuple

_SCHEMA_DOMAIN = b"ras-commander:wine-prefix-fingerprint:v1\0"
_DOSDEVICES_SCHEMA_DOMAIN = b"ras-commander:wine-dosdevices-fingerprint:v1\0"
_REGISTRY_FILENAMES = ("user.reg", "system.reg", "userdef.reg")
_READ_SIZE = 1024 * 1024


class WinePrefixFingerprintError(ValueError):
    """Raised when a prefix cannot be fingerprinted safely and completely."""


@dataclass(frozen=True)
class WinePrefixFingerprint:
    """Non-sensitive summary of one Wine-prefix filesystem state.

    ``file_count`` and ``total_bytes`` describe regular files. Directories and
    safe in-prefix symbolic links still contribute to ``root_sha256``.
    """

    root_sha256: str
    user_reg_sha256: str
    system_reg_sha256: str
    userdef_reg_sha256: str
    file_count: int
    total_bytes: int
    dosdevices_sha256: str | None


def _path_bytes(relative_path: Path) -> bytes:
    return relative_path.as_posix().encode("utf-8", errors="surrogateescape")


def _write_field(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big", signed=False))
    digest.update(value)


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker is not None and checker())


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _iter_entries(
    root: Path,
    *,
    exclude_wine_dosdevices: bool = False,
) -> Iterator[Tuple[Path, Path]]:
    """Yield all prefix entries in canonical relative-path byte order."""
    pending = [root]
    entries = []
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            raise WinePrefixFingerprintError(
                "Cannot enumerate Wine-prefix directory: "
                f"{directory.relative_to(root).as_posix()}"
            ) from exc
        for child in children:
            relative = child.relative_to(root)
            if exclude_wine_dosdevices and relative == Path("dosdevices"):
                continue
            try:
                mode = child.lstat().st_mode
            except OSError as exc:
                raise WinePrefixFingerprintError(
                    f"Cannot inspect Wine-prefix entry: {relative.as_posix()}"
                ) from exc
            entries.append((relative, child))
            if stat.S_ISDIR(mode) and not _is_junction(child):
                pending.append(child)

    entries.sort(key=lambda item: _path_bytes(item[0]))
    yield from entries


def _stable_file_chunks(path: Path, relative: Path) -> Iterator[bytes]:
    """Read a regular file and reject a concurrent replacement or mutation."""
    try:
        before = path.stat(follow_symlinks=False)
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or opened.st_size != before.st_size
            ):
                raise WinePrefixFingerprintError(
                    f"Wine-prefix file changed while opening: {relative.as_posix()}"
                )
            for chunk in iter(lambda: stream.read(_READ_SIZE), b""):
                yield chunk
        after = path.stat(follow_symlinks=False)
    except WinePrefixFingerprintError:
        raise
    except OSError as exc:
        raise WinePrefixFingerprintError(
            f"Cannot read Wine-prefix file: {relative.as_posix()}"
        ) from exc

    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise WinePrefixFingerprintError(
            f"Wine-prefix file changed while hashing: {relative.as_posix()}"
        )


def _symlink_content(path: Path, relative: Path, root: Path) -> bytes:
    try:
        target = path.resolve(strict=True)
        raw_target = os.readlink(path)
    except (OSError, RuntimeError) as exc:
        raise WinePrefixFingerprintError(
            f"Wine-prefix link is dangling or cyclic: {relative.as_posix()}"
        ) from exc
    if not _is_within(target, root):
        raise WinePrefixFingerprintError(
            f"Wine-prefix link resolves outside the prefix: {relative.as_posix()}"
        )
    if os.path.isabs(raw_target):
        normalized_target = _path_bytes(target.relative_to(root))
        return b"absolute-prefix-internal\0" + normalized_target
    return b"relative-prefix-internal\0" + os.fsencode(raw_target)


def _dosdevice_target_class(path: Path, root: Path) -> bytes:
    """Classify one mapping without retaining a private host target path."""
    try:
        raw_target = os.readlink(path)
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise WinePrefixFingerprintError(
            f"Cannot classify Wine dosdevice mapping: {path.name}"
        ) from exc

    if _is_within(resolved, root):
        relative_target = _path_bytes(resolved.relative_to(root))
        return b"prefix-internal\0" + relative_target

    raw_path = Path(raw_target)
    if os.path.isabs(raw_target):
        try:
            host_anchor = Path(resolved.anchor).resolve(strict=False)
        except (OSError, RuntimeError):
            host_anchor = None
        if host_anchor is not None and resolved == host_anchor:
            return b"host-root"
        return b"host-absolute"
    if raw_path.parts:
        return b"host-relative-escape"
    raise WinePrefixFingerprintError(
        f"Wine dosdevice mapping has an empty target: {path.name}"
    )


def _dosdevices_fingerprint(dosdevices: Path, root: Path) -> str:
    """Hash a flat Wine mapping directory without hashing host target paths."""
    try:
        metadata = dosdevices.lstat()
    except OSError as exc:
        raise WinePrefixFingerprintError(
            "Qualification-mode fingerprinting requires root dosdevices"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_junction(dosdevices)
    ):
        raise WinePrefixFingerprintError(
            "Root dosdevices must be a real directory, not a link or file"
        )
    try:
        mappings = list(dosdevices.iterdir())
    except OSError as exc:
        raise WinePrefixFingerprintError(
            "Cannot enumerate root Wine dosdevices directory"
        ) from exc
    if not mappings:
        raise WinePrefixFingerprintError(
            "Root Wine dosdevices directory must contain link mappings"
        )

    mappings.sort(key=lambda path: _path_bytes(Path(path.name)))
    digest = hashlib.sha256()
    digest.update(_DOSDEVICES_SCHEMA_DOMAIN)
    for mapping in mappings:
        try:
            mapping_metadata = mapping.lstat()
        except OSError as exc:
            raise WinePrefixFingerprintError(
                f"Cannot inspect Wine dosdevice mapping: {mapping.name}"
            ) from exc
        if not (stat.S_ISLNK(mapping_metadata.st_mode) or _is_junction(mapping)):
            raise WinePrefixFingerprintError(
                "Root Wine dosdevices must be flat and link-only; invalid entry: "
                f"{mapping.name}"
            )
        _write_field(digest, _path_bytes(Path(mapping.name)))
        _write_field(digest, _dosdevice_target_class(mapping, root))
    return digest.hexdigest()


def fingerprint_wine_prefix(
    prefix: str | Path,
    *,
    exclude_wine_dosdevices: bool = False,
) -> WinePrefixFingerprint:
    """Return a canonical SHA-256 fingerprint of a complete Wine prefix.

    Relative paths, entry types, semantic sizes, and content are hashed in
    sorted order. Regular-file content is streamed. Safe links are hashed as
    links without following their content; any link or junction resolving
    outside the prefix is rejected. The three Wine registry files must be
    root-level regular files, and only their SHA-256 digests are returned.

    A normal Wine prefix deliberately maps ``dosdevices/z:`` outside the
    prefix. Callers performing controlled qualification may explicitly set
    ``exclude_wine_dosdevices=True``. That mode excludes only the root-level
    ``dosdevices`` directory from the content root, requires it to be a flat
    link-only directory, and returns a separate digest of mapping names and
    privacy-preserving target classes. Raw host target paths are never hashed
    or returned. The default remains strict and rejects all escaping links.
    """
    requested_root = Path(prefix)
    if requested_root.is_symlink() or _is_junction(requested_root):
        raise WinePrefixFingerprintError(
            "The Wine-prefix root must not be a symbolic link or junction"
        )
    try:
        root = requested_root.resolve(strict=True)
    except OSError as exc:
        raise WinePrefixFingerprintError("The Wine-prefix root does not exist") from exc
    if not root.is_dir():
        raise WinePrefixFingerprintError("The Wine-prefix root is not a directory")

    dosdevices_sha256 = None
    if exclude_wine_dosdevices:
        dosdevices_sha256 = _dosdevices_fingerprint(root / "dosdevices", root)

    root_digest = hashlib.sha256()
    root_digest.update(_SCHEMA_DOMAIN)
    registry_hashes = {}
    file_count = 0
    total_bytes = 0

    for relative, path in _iter_entries(
        root,
        exclude_wine_dosdevices=exclude_wine_dosdevices,
    ):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise WinePrefixFingerprintError(
                f"Cannot inspect Wine-prefix entry: {relative.as_posix()}"
            ) from exc

        path_data = _path_bytes(relative)
        if stat.S_ISLNK(metadata.st_mode) or _is_junction(path):
            content = _symlink_content(path, relative, root)
            _write_field(root_digest, path_data)
            _write_field(root_digest, b"link")
            root_digest.update(
                len(content).to_bytes(8, byteorder="big", signed=False)
            )
            root_digest.update(content)
        elif stat.S_ISDIR(metadata.st_mode):
            _write_field(root_digest, path_data)
            _write_field(root_digest, b"directory")
            root_digest.update((0).to_bytes(8, byteorder="big", signed=False))
        elif stat.S_ISREG(metadata.st_mode):
            size = metadata.st_size
            _write_field(root_digest, path_data)
            _write_field(root_digest, b"file")
            root_digest.update(size.to_bytes(8, byteorder="big", signed=False))
            file_digest = hashlib.sha256()
            bytes_read = 0
            for chunk in _stable_file_chunks(path, relative):
                root_digest.update(chunk)
                file_digest.update(chunk)
                bytes_read += len(chunk)
            if bytes_read != size:
                raise WinePrefixFingerprintError(
                    "Wine-prefix file size changed while hashing: "
                    f"{relative.as_posix()}"
                )
            file_count += 1
            total_bytes += size
            relative_name = relative.as_posix()
            if relative_name in _REGISTRY_FILENAMES:
                registry_hashes[relative_name] = file_digest.hexdigest()
        else:
            raise WinePrefixFingerprintError(
                f"Unsupported Wine-prefix entry type: {relative.as_posix()}"
            )

    missing = [name for name in _REGISTRY_FILENAMES if name not in registry_hashes]
    if missing:
        raise WinePrefixFingerprintError(
            "Wine prefix is missing regular root registry files: " + ", ".join(missing)
        )

    return WinePrefixFingerprint(
        root_sha256=root_digest.hexdigest(),
        user_reg_sha256=registry_hashes["user.reg"],
        system_reg_sha256=registry_hashes["system.reg"],
        userdef_reg_sha256=registry_hashes["userdef.reg"],
        file_count=file_count,
        total_bytes=total_bytes,
        dosdevices_sha256=dosdevices_sha256,
    )
