"""Isolated project staging and source-tree fingerprinting for qualification runs.

This module carries the minimal public surface of the HEC-RAS qualification
API that downstream tools (for example fim-commander's clone-only boundary and
local compute adapters) depend on:

- :meth:`RasQualification.project_tree_fingerprint` hashes a small HEC-RAS
  project tree so callers can prove a source project was not modified.
- :meth:`RasQualification.stage_project` copies one source project into a new,
  uniquely named folder below a task workspace and verifies the copy.

The receipt, lock, HDF-fingerprint, raster-parity, and Wine-prefix portions of
the full qualification harness are intentionally not included here.

Relationship to :func:`ras_commander.RasProject.stage_project`
---------------------------------------------------------------
The two staging functions are deliberately different and are not aliases:

- ``RasProject.stage_project(source, destination, *, ras_object=None)`` takes
  an exact destination project directory whose parent must already exist,
  rejects lock artifacts in the source, initializes the copy with
  ``init_ras_project``, publishes it atomically, and returns a
  :class:`~ras_commander.RasProject.StageProjectResult` dataclass.
- ``RasQualification.stage_project(source_project, workspace_root, task_id=...)``
  takes a workspace root, creates a unique ``rasq-<task>-<token>/<source name>``
  folder (optionally with spaces or a long path), tolerates and excludes the
  transient qualification runner lock, normalizes the copy to be
  owner-writable, does not initialize a ``RasPrj``, and returns a plain
  dictionary with ``destination`` and ``project_file`` keys.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasProject import _io_path
from .RasUtils import RasUtils


logger = get_logger(__name__)


class RasQualification:
    """Static helpers for isolated qualification staging and tree fingerprints.

    All methods are static; do not instantiate this class.
    """

    PROJECT_LOCK_NAME = ".ras-commander-project.lock"

    @staticmethod
    @log_call
    def project_tree_fingerprint(project_folder: Union[str, Path]) -> str:
        """Hash immutable project content, excluding the transient runner lock.

        The digest covers every file below ``project_folder`` in sorted
        relative-POSIX-path order, framing each relative path and its bytes.
        Directory entries and file metadata (timestamps, permissions) are not
        included. The file named :attr:`PROJECT_LOCK_NAME` is ignored.

        Args:
            project_folder (Union[str, Path]): HEC-RAS project folder to hash.

        Returns:
            str: Hex-encoded SHA-256 digest of the project tree content.

        Raises:
            FileNotFoundError: If ``project_folder`` is not an existing directory.

        Examples:
            >>> before = RasQualification.project_tree_fingerprint("C:/Models/Muncie")
            >>> # ... operate only on a staged copy ...
            >>> assert RasQualification.project_tree_fingerprint("C:/Models/Muncie") == before
        """
        root = Path(project_folder)
        if not root.is_dir():
            raise FileNotFoundError(f"Project folder not found: {root}")
        digest = hashlib.sha256()
        files = (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != RasQualification.PROJECT_LOCK_NAME
        )
        for path in sorted(files, key=lambda p: p.as_posix()):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            with path.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b"\x00")
        return digest.hexdigest()

    @staticmethod
    @log_call
    def stage_project(
        source_project: Union[str, Path],
        workspace_root: Union[str, Path],
        task_id: Optional[str] = None,
        path_variant: str = "standard",
        minimum_long_path: int = 280,
    ) -> Dict[str, Any]:
        """Copy one immutable source project into an isolated task workspace.

        The destination is ``<workspace_root>/rasq-<task_id>-<token>/<source name>``
        for the ``standard`` variant, a folder containing spaces for
        ``spaces``, and a nested path of at least ``minimum_long_path``
        characters for ``long``. The source tree is fingerprinted before the
        copy and the copy must reproduce the same fingerprint. The copy is made
        owner-writable even if the source fixture is read-only; the source is
        never modified. The transient runner lock (:attr:`PROJECT_LOCK_NAME`)
        and Windows reserved device names are excluded from the copy.

        This is not an alias of :func:`ras_commander.RasProject.stage_project`;
        see the module docstring for the differences.

        Args:
            source_project (Union[str, Path]): Source project folder containing
                a ``.prj`` file.
            workspace_root (Union[str, Path]): Workspace folder under which the
                unique destination is created (created if missing).
            task_id (Optional[str]): Label used in the destination folder name.
                Characters outside ``[A-Za-z0-9_.-]`` are replaced with ``-``.
            path_variant (str): ``"standard"``, ``"spaces"``, or ``"long"``.
            minimum_long_path (int): Minimum destination path length for the
                ``long`` variant.

        Returns:
            Dict[str, Any]: Staging evidence including ``source``,
            ``destination`` (staged project folder), ``project_file`` (staged
            ``.prj`` path; the first ``.prj`` in sorted name order),
            ``path_variant``, ``path_length``, ``source_fingerprint``,
            ``destination_fingerprint``, ``content_matches``,
            ``writable_clone``, and ``transient_lock``.

        Raises:
            FileNotFoundError: If the source folder does not exist.
            ValueError: If the source has no ``.prj`` file or ``path_variant``
                is invalid.
            FileExistsError: If the generated destination already exists.
            RuntimeError: If the copy is not owner-writable, copied the runner
                lock, or does not reproduce the source fingerprint.

        Examples:
            >>> stage = RasQualification.stage_project(
            ...     "C:/Models/Muncie", "C:/Work", task_id="ble-apply"
            ... )
            >>> Path(stage["project_file"]).name  # doctest: +SKIP
            'Muncie.prj'
        """
        source = RasUtils.safe_resolve(Path(source_project))
        if not source.is_dir():
            raise FileNotFoundError(f"Source project folder not found: {source}")
        project_files = sorted(source.glob("*.prj"))
        if not project_files:
            raise ValueError(f"No HEC-RAS .prj file found in source fixture: {source}")

        variant = path_variant.lower()
        if variant not in {"standard", "spaces", "long"}:
            raise ValueError("path_variant must be 'standard', 'spaces', or 'long'")

        root = RasUtils.safe_resolve(Path(workspace_root))
        root.mkdir(parents=True, exist_ok=True)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id or "task").strip("-.") or "task"
        token = uuid.uuid4().hex[:10]
        if variant == "spaces":
            destination = root / f"RAS qualification {safe_task} {token}" / source.name
        elif variant == "long":
            destination = root / f"rasq-{safe_task}-{token}"
            segment_index = 0
            while len(str(destination / source.name)) < minimum_long_path:
                destination = destination / f"long-path-segment-{segment_index:02d}-qualification"
                segment_index += 1
            destination = destination / source.name
        else:
            destination = root / f"rasq-{safe_task}-{token}" / source.name

        # Descendant model filenames can cross MAX_PATH even when the
        # destination directory itself is shorter than the threshold.
        destination_io = _io_path(destination)
        if destination_io.exists():
            raise FileExistsError(f"Isolated project destination already exists: {destination}")

        source_lock_present = (source / RasQualification.PROJECT_LOCK_NAME).is_file()
        source_fingerprint = RasQualification.project_tree_fingerprint(source)
        destination_io.parent.mkdir(parents=True, exist_ok=True)

        def ignore_runtime_files(directory: str, names: List[str]) -> List[str]:
            ignored = set(RasUtils.ignore_windows_reserved(directory, names))
            if RasQualification.PROJECT_LOCK_NAME in names:
                ignored.add(RasQualification.PROJECT_LOCK_NAME)
            return sorted(ignored)

        shutil.copytree(source, destination_io, ignore=ignore_runtime_files)
        writable_paths = [destination_io, *destination_io.rglob("*")]
        writable_file_count = 0
        writable_directory_count = 0
        for copied_path in writable_paths:
            if copied_path.is_symlink():
                continue
            current_mode = copied_path.stat().st_mode
            owner_mode = stat.S_IRUSR | stat.S_IWUSR
            if copied_path.is_dir():
                owner_mode |= stat.S_IXUSR
                writable_directory_count += 1
            else:
                writable_file_count += 1
            copied_path.chmod(current_mode | owner_mode)
        owner_write_verified = all(
            copied_path.is_symlink()
            or bool(copied_path.stat().st_mode & stat.S_IWUSR)
            for copied_path in writable_paths
        )
        if not owner_write_verified:
            raise RuntimeError(
                f"Isolated project clone is not owner-writable: {destination}"
            )
        destination_lock = destination_io / RasQualification.PROJECT_LOCK_NAME
        if destination_lock.exists():
            raise RuntimeError(
                f"Transient project lock was copied into isolated workspace: {destination_lock}"
            )
        destination_fingerprint = RasQualification.project_tree_fingerprint(destination_io)
        if source_fingerprint != destination_fingerprint:
            raise RuntimeError(
                f"Project clone content mismatch: {source_fingerprint} != {destination_fingerprint}"
            )

        return {
            "source": str(source),
            "destination": str(destination),
            "project_file": str(destination / project_files[0].name),
            "path_variant": variant,
            "path_length": len(str(destination)),
            "source_fingerprint": source_fingerprint,
            "destination_fingerprint": destination_fingerprint,
            "content_matches": True,
            "writable_clone": {
                "normalized": True,
                "owner_write_verified": owner_write_verified,
                "directory_count": writable_directory_count,
                "file_count": writable_file_count,
                "source_permissions_unchanged": True,
            },
            "transient_lock": {
                "name": RasQualification.PROJECT_LOCK_NAME,
                "source_present_during_stage": source_lock_present,
                "destination_present": False,
                "excluded": True,
            },
        }
