"""Temporary single-plan project declarations for HEC-RAS 7.0.2 launches.

HEC-RAS 7.0.2 ``Ras.exe -c "<project>" "<plan>"`` ignores the plan argument and
the project's ``Current Plan=`` declaration and computes the project's
``Plan File=`` entries in listed order (qualified on the installed release,
bounded Windows qualification, 2026-10-29). The 7.0.1 control honoured the plan
argument. Older releases keep their existing version-specific launch paths.

This module exposes exactly one requested ``Plan File=`` entry (and the matching
``Current Plan=``) for the duration of one owned launch and restores the
original project bytes afterwards.  It never deletes or renames model files and
it never changes what ``RasPrj`` reports; the mutation is a file transaction
with a recoverable backup, an exclusive per-project claim, and verification of
every step.  Nothing here runs HEC-RAS.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import socket
import stat
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Tuple

from .LoggingConfig import get_logger
from ._process_inspection import normalize_windows_path_token
from ._ras_text import _split_ras_records

logger = get_logger(__name__)

#: Releases whose command-line launcher ignores the requested plan.
SINGLE_PLAN_PROJECT_RELEASES = frozenset({(7, 0, 2)})

# Exact locally patched frontend; no vendor executable or patch is distributed.
# Unknown or unreadable builds retain the release-specific project guard.
_SINGLE_PLAN_CLI_SHA256 = frozenset({
    "039863ff8d31cf9d2ae2aa5fdc1d4024a61a75f46ba49f2448672acc0336a0b6",
})

CLAIM_SUFFIX = ".single-plan.claim"
BACKUP_SUFFIX = ".single-plan.orig"
TEMP_SUFFIX = ".single-plan.tmp"
REWRITE_SUFFIX = ".single-plan.rewritten-"
CLAIM_FORMAT = "ras-commander single-plan project claim v1"

_RELEASE_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")
_PLAN_ENTRY = re.compile(rb"^Plan File=\s*([pP]\d\d)\s*$")
_CURRENT_PLAN = re.compile(rb"^Current Plan=\s*(.*?)\s*$")
_PROJECT_TITLE = re.compile(rb"^Proj Title=")
_SOLVER_PLAN_TOKEN = re.compile(r"[bB]\d\d")
_ENGINE_PROCESS_NAMES = frozenset(
    {
        "ras.exe",
        "rasunsteady.exe",
        "rasunsteady64.exe",
        "rassteady.exe",
        "rassteady64.exe",
        "rasgeompreprocess.exe",
        "rasprocess.exe",
    }
)


class SinglePlanProjectError(RuntimeError):
    """A single-plan project declaration could not be established safely.

    ``kind`` is one of ``plan_missing``, ``plan_duplicated``, ``malformed``,
    ``claim_conflict``, ``active_launch``, ``inventory_incomplete``,
    ``reentrant`` or ``io``.  The project file is unchanged unless the message
    names a retained backup.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclasses.dataclass(frozen=True)
class SinglePlanProjectRestore:
    """Outcome of restoring the original project declaration."""

    restored: bool
    proved: bool
    detail: str
    backup_path: Optional[str] = None
    claim_path: Optional[str] = None
    unexpected_rewrite_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the original bytes are back and no residue remains."""
        return self.restored and self.proved

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def ras_release_tuple(
    *,
    ras_exe_path: Any = None,
    ras_version: Any = None,
) -> Optional[Tuple[int, int, int]]:
    """Resolve ``(major, minor, patch)`` from the executable folder or version."""
    candidates: List[str] = []
    if ras_exe_path:
        # PureWindowsPath splits on both separators, so a Windows executable
        # path keeps its release folder even when inspected from Linux.
        candidates.append(PureWindowsPath(str(ras_exe_path)).parent.name)
    if ras_version:
        candidates.append(str(ras_version))
    for candidate in candidates:
        match = _RELEASE_PATTERN.search(candidate)
        if match is None:
            continue
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)
    return None


def single_plan_project_required(
    *,
    ras_exe_path: Any = None,
    ras_version: Any = None,
) -> bool:
    """Require the guard unless this release has an exact recognized CLI patch."""
    release = ras_release_tuple(ras_exe_path=ras_exe_path, ras_version=ras_version)
    if release not in SINGLE_PLAN_PROJECT_RELEASES:
        return False
    if ras_exe_path:
        try:
            # Recheck bytes on each call; replacing the executable must not
            # reuse a previous decision for the same path.
            digest = hashlib.sha256()
            with Path(ras_exe_path).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() in _SINGLE_PLAN_CLI_SHA256:
                logger.debug("Recognized single-plan CLI patch; project guard skipped")
                return False
        except OSError:
            # Missing paths and failed reads do not establish patched behavior.
            pass
    return True


def _normalize_plan_entry(plan_number: Any) -> str:
    text = str(plan_number).strip()
    if text.lower().startswith("p") and text[1:].isdigit():
        text = text[1:]
    if not text.isdigit():
        raise SinglePlanProjectError(
            f"plan number {plan_number!r} is not a HEC-RAS plan number",
            kind="malformed",
        )
    if len(text) > 2:
        text = text.lstrip("0") or "0"
    if not 1 <= int(text) <= 99:
        raise SinglePlanProjectError(
            f"plan number {plan_number!r} is outside 01-99",
            kind="malformed",
        )
    return f"p{int(text):02d}"


def filter_project_declaration(
    data: bytes,
    plan_number: Any,
    *,
    project_name: str = "project file",
) -> Tuple[bytes, Dict[str, Any]]:
    """Return project bytes that declare only ``plan_number``.

    Every record that is not a ``Plan File=`` or ``Current Plan=`` declaration
    is copied byte for byte, including its own line terminator, so encoding,
    newline style, and a missing final newline are preserved.  The requested
    plan must be declared exactly once; anything else fails before mutation.
    """
    wanted = _normalize_plan_entry(plan_number)
    records = _split_ras_records(data, keepends=True)
    if b"".join(records) != data:
        raise SinglePlanProjectError(
            f"{project_name} could not be split into records losslessly",
            kind="malformed",
        )
    output: List[bytes] = []
    kept: List[str] = []
    removed: List[str] = []
    declared: List[str] = []
    current_before: List[str] = []
    crlf = sum(1 for record in records if record.endswith(b"\r\n"))
    lf = sum(1 for record in records if record.endswith(b"\n")) - crlf
    newline = b"\r\n" if crlf >= lf else b"\n"
    for record in records:
        body = record.rstrip(b"\r\n")
        ending = record[len(body):]
        plan_match = _PLAN_ENTRY.match(body)
        if plan_match:
            entry = plan_match.group(1).decode("ascii").lower()
            declared.append(entry)
            if entry == wanted:
                kept.append(entry)
                output.append(record)
            else:
                removed.append(entry)
            continue
        if body.startswith(b"Plan File="):
            raise SinglePlanProjectError(
                f"{project_name} contains a malformed Plan File declaration",
                kind="malformed",
            )
        current_match = _CURRENT_PLAN.match(body)
        if current_match:
            current_before.append(current_match.group(1).decode("latin-1"))
            output.append(b"Current Plan=" + wanted.encode("ascii") + ending)
            continue
        output.append(record)
    if not kept:
        raise SinglePlanProjectError(
            f"{project_name} does not declare 'Plan File={wanted}'; declared "
            f"plans: {', '.join(declared) or 'none'}",
            kind="plan_missing",
        )
    if len(kept) > 1:
        raise SinglePlanProjectError(
            f"{project_name} declares 'Plan File={wanted}' {len(kept)} times; "
            "repair the duplicate declaration before launching",
            kind="plan_duplicated",
        )
    inserted_current_plan = False
    if not current_before:
        line = b"Current Plan=" + wanted.encode("ascii") + newline
        insert_at = 0
        for index, record in enumerate(output):
            if _PROJECT_TITLE.match(record):
                insert_at = index + 1
                break
        output.insert(insert_at, line)
        inserted_current_plan = True
    filtered = b"".join(output)
    summary = {
        "exposed_plan": wanted,
        "declared_plan_entries": declared,
        "removed_plan_entries": removed,
        "current_plan_before": current_before,
        "current_plan_after": wanted,
        "inserted_current_plan": inserted_current_plan,
        "newline": "crlf" if newline == b"\r\n" else "lf",
    }
    return filtered, summary


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_file_atomically(path: Path, data: bytes, mode: Optional[int]) -> None:
    """Write ``data`` to ``path`` through a fsynced sibling and ``os.replace``.

    ``mode`` (``stat.S_IMODE``) is applied to the staged file before the
    replace and re-applied afterwards.  A read-only target is made writable
    for the replace only, because Windows refuses to replace read-only files.
    """
    temp = path.with_name(path.name + TEMP_SUFFIX)
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            try:
                os.chmod(temp, mode)
            except OSError:
                pass
        if path.exists() and not os.access(path, os.W_OK):
            try:
                current_mode = stat.S_IMODE(os.stat(path).st_mode)
                os.chmod(path, current_mode | stat.S_IWUSR)
            except OSError:
                pass
        os.replace(temp, path)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory)
    except OSError:
        pass
    finally:
        os.close(directory)


def _remove_quietly(path: Optional[Path]) -> bool:
    """Remove ``path`` if present; return whether it is absent afterwards."""
    if path is None:
        return True
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        logger.warning("Could not remove %s: %s", path, exc)
        return not path.exists()
    return True


def _process_identity() -> Dict[str, Any]:
    identity: Dict[str, Any] = {
        "pid": os.getpid(),
        "create_time": None,
        "host": socket.gethostname(),
    }
    try:
        import psutil

        identity["create_time"] = float(psutil.Process(os.getpid()).create_time())
    except Exception:  # pragma: no cover - identity stays pid-only
        pass
    return identity


def _claim_owner_alive(owner: Dict[str, Any]) -> Optional[bool]:
    """Return whether the recorded claim owner is still running.

    ``None`` means the question could not be answered; callers treat that as
    alive and fail closed.
    """
    pid = owner.get("pid")
    create_time = owner.get("create_time")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    host = owner.get("host")
    if host and host != socket.gethostname():
        return None
    try:
        import psutil
    except Exception:
        return None
    try:
        if not psutil.pid_exists(pid):
            return False
        process = psutil.Process(pid)
        observed = float(process.create_time())
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return None
    if create_time is None:
        return True
    try:
        return abs(observed - float(create_time)) < 0.01
    except (TypeError, ValueError):
        return None


def _engine_process_records() -> Optional[List[Tuple[str, int, Tuple[str, ...], Optional[str]]]]:
    """Return ``(name, pid, cmdline, cwd)`` for every HEC-RAS engine process.

    ``None`` means at least one engine-named process could not be read, so
    the host inventory is incomplete.  Non-engine processes are never queried
    beyond their name.
    """
    try:
        import psutil
    except Exception:
        return None
    records: List[Tuple[str, int, Tuple[str, ...], Optional[str]]] = []
    try:
        iterator = psutil.process_iter(["pid", "name"])
        for process in iterator:
            try:
                name = process.info.get("name") or ""
                if name.casefold() not in _ENGINE_PROCESS_NAMES:
                    continue
                if process.pid == os.getpid():
                    continue
                arguments = tuple(str(item) for item in process.cmdline())
                try:
                    cwd = process.cwd()
                except (psutil.AccessDenied, OSError):
                    cwd = None
                records.append((name, int(process.pid), arguments, cwd))
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                return None
    except Exception:
        return None
    return records


def active_project_launches(project_path: Path) -> Tuple[List[str], bool]:
    """Return ``(conflicts, complete)`` for engines already using a project.

    A conflict is any HEC-RAS engine process whose command line names the
    project file or any sibling file of the same project (``<name>.p03``,
    ``<name>.p03.tmp.hdf`` ...), or a solver started in the project folder
    with a ``b##`` plan token.  ``complete`` is false when the inventory could
    not be read fully.
    """
    records = _engine_process_records()
    if records is None:
        return [], False
    project_norm = normalize_windows_path_token(str(project_path))
    folder_norm = normalize_windows_path_token(str(project_path.parent))
    family_prefix = normalize_windows_path_token(str(project_path.with_suffix(""))) + "."
    conflicts: List[str] = []
    for name, pid, arguments, cwd in records:
        hit = False
        for token in arguments:
            normalized = normalize_windows_path_token(token, cwd=cwd)
            if normalized and (
                normalized == project_norm or normalized.startswith(family_prefix)
            ):
                hit = True
                break
        if not hit and cwd and normalize_windows_path_token(cwd) == folder_norm:
            hit = any(
                _SOLVER_PLAN_TOKEN.fullmatch(str(token).strip().strip('"'))
                for token in arguments
            )
        if hit:
            conflicts.append(f"{name} (pid {pid})")
    return conflicts, True


class SinglePlanProjectTransaction:
    """Expose one plan in a project file for one owned launch, then restore it.

    Lifecycle: :meth:`apply` validates the declaration, refuses active project
    launches and foreign claims, records a claim, stages a verified backup of
    the original bytes, and replaces the project file atomically.
    :meth:`restore` puts the original bytes, permissions and timestamps back
    and, when the launch's processes are proved stopped, removes the backup
    and the claim.  Restoration failures never raise; they are reported so the
    caller can fail its result with the recovery path.
    """

    def __init__(
        self,
        project_path: Any,
        plan_number: Any,
        *,
        launch_owner: str = "ras-commander",
    ) -> None:
        self.project_path = Path(project_path)
        self.plan_entry = _normalize_plan_entry(plan_number)
        self.plan_number = self.plan_entry[1:]
        self.launch_owner = launch_owner
        self.backup_path = self.project_path.with_name(
            self.project_path.name + BACKUP_SUFFIX
        )
        self.claim_path = self.project_path.with_name(
            self.project_path.name + CLAIM_SUFFIX
        )
        self._applied = False
        self._released = False
        self._original: Optional[bytes] = None
        self._filtered: Optional[bytes] = None
        self._original_mode: Optional[int] = None
        self._original_times_ns: Optional[Tuple[int, int]] = None
        self._summary: Dict[str, Any] = {}
        self._outcome: Optional[SinglePlanProjectRestore] = None
        self._stale_claim_recovered = False
        self._applied_at: Optional[float] = None

    # ------------------------------------------------------------------ state
    @property
    def applied(self) -> bool:
        return self._applied

    @property
    def released(self) -> bool:
        return self._released

    @property
    def outcome(self) -> Optional[SinglePlanProjectRestore]:
        return self._outcome

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "engaged": True,
            "reason": "HEC-RAS 7.0.2 launcher computes listed plans in order",
            "launch_owner": self.launch_owner,
            "project_path": str(self.project_path),
            "plan_number": self.plan_number,
            "backup_path": str(self.backup_path),
            "claim_path": str(self.claim_path),
            "applied": self._applied,
            "released": self._released,
            "stale_claim_recovered": self._stale_claim_recovered,
            "original_sha256": _sha256(self._original) if self._original is not None else None,
            "filtered_sha256": _sha256(self._filtered) if self._filtered is not None else None,
            "original_mode": (
                oct(self._original_mode) if self._original_mode is not None else None
            ),
        }
        payload.update(self._summary)
        payload["restore"] = self._outcome.to_dict() if self._outcome else None
        return payload

    # ------------------------------------------------------------------ apply
    def apply(self) -> None:
        """Expose only the requested plan; raise before any mutation on doubt."""
        if self._applied:
            raise SinglePlanProjectError(
                f"{self.project_path.name} is already exposed as a single-plan "
                "project by this transaction",
                kind="reentrant",
            )
        project = self.project_path
        if not project.is_file():
            raise SinglePlanProjectError(
                f"project file not found: {project}", kind="io"
            )

        conflicts, complete = active_project_launches(project)
        if not complete:
            raise SinglePlanProjectError(
                "the HEC-RAS process inventory could not be read completely, "
                f"so no pre-existing launch of {project.name} can be ruled out; "
                "the project file was not modified",
                kind="inventory_incomplete",
            )
        if conflicts:
            raise SinglePlanProjectError(
                f"HEC-RAS is already using {project.name}: "
                + ", ".join(conflicts)
                + ". Wait for or stop that launch before requesting plan "
                f"{self.plan_number} on HEC-RAS 7.0.2; the project file was not "
                "modified",
                kind="active_launch",
            )

        # A leftover claim is either a competing launch (fail closed) or a
        # provably stale predecessor whose original bytes are recovered before
        # this declaration is validated against the project file.
        if self.claim_path.exists():
            self._recover_stale_claim(_read_bytes(project) or b"")
        original, filtered, summary, file_stat = self._read_and_filter()
        self._acquire_claim(original, filtered, file_stat)
        if self.backup_path.exists():
            _remove_quietly(self.claim_path)
            raise SinglePlanProjectError(
                f"Refusing to overwrite retained backup {self.backup_path}; "
                "inspect the project and recover that backup before retrying",
                kind="claim_conflict",
            )
        if _read_bytes(project) != original:
            _remove_quietly(self.claim_path)
            raise SinglePlanProjectError(
                f"{project.name} changed while acquiring the project claim; "
                "the project was not modified",
                kind="claim_conflict",
            )

        try:
            self.backup_path.write_bytes(original)
            with open(self.backup_path, "rb+") as handle:
                os.fsync(handle.fileno())
            if _read_bytes(self.backup_path) != original:
                raise SinglePlanProjectError(
                    f"backup {self.backup_path.name} did not read back "
                    "identically; the project file was not modified",
                    kind="io",
                )
        except BaseException:
            _remove_quietly(self.backup_path)
            _remove_quietly(self.claim_path)
            raise

        mode = stat.S_IMODE(file_stat.st_mode)
        try:
            _write_file_atomically(project, filtered, mode)
            observed = _read_bytes(project)
            if observed != filtered:
                raise SinglePlanProjectError(
                    f"{project.name} did not read back as the single-plan "
                    "declaration after replacement",
                    kind="io",
                )
        except BaseException as error:
            # Undo immediately. Keep the backup and claim only when the undo
            # itself cannot be proved.
            undone = False
            try:
                _write_file_atomically(project, original, mode)
                undone = _read_bytes(project) == original
            except OSError:
                undone = False
            if undone:
                _remove_quietly(self.backup_path)
                _remove_quietly(self.claim_path)
                raise
            logger.critical(
                "Could not establish or undo the single-plan declaration for "
                "%s. The original bytes are retained in %s; copy that file "
                "over the project file, then delete %s.",
                project,
                self.backup_path,
                self.claim_path,
            )
            raise SinglePlanProjectError(
                f"{project.name} could not be restored after a failed "
                f"single-plan replacement ({error}). The original bytes are "
                f"retained in {self.backup_path}; copy that file over "
                f"{project.name}, then delete {self.claim_path}",
                kind="io",
            ) from error

        self._original = original
        self._filtered = filtered
        self._original_mode = mode
        self._original_times_ns = (file_stat.st_atime_ns, file_stat.st_mtime_ns)
        self._summary = summary
        self._applied = True
        self._applied_at = time.time()
        logger.info(
            "Exposing only plan %s in %s for this HEC-RAS 7.0.2 launch "
            "(%d other plan declaration(s) hidden until restoration)",
            self.plan_number,
            project.name,
            len(summary.get("removed_plan_entries", [])),
        )
        logger.debug(
            "Single-plan declaration for %s: original sha256 %s, filtered "
            "sha256 %s, backup %s, claim %s",
            project,
            _sha256(original),
            _sha256(filtered),
            self.backup_path,
            self.claim_path,
        )

    def _read_and_filter(self) -> Tuple[bytes, bytes, Dict[str, Any], os.stat_result]:
        project = self.project_path
        try:
            file_stat = os.stat(project)
            original = project.read_bytes()
        except OSError as exc:
            raise SinglePlanProjectError(
                f"could not read {project}: {exc}", kind="io"
            ) from exc
        filtered, summary = filter_project_declaration(
            original, self.plan_number, project_name=project.name
        )
        return original, filtered, summary, file_stat

    def _claim_payload(
        self, original: bytes, filtered: bytes, file_stat: os.stat_result
    ) -> Dict[str, Any]:
        return {
            "format": CLAIM_FORMAT,
            "owner": _process_identity(),
            "launch_owner": self.launch_owner,
            "plan_number": self.plan_number,
            "project_path": str(self.project_path),
            "backup_path": str(self.backup_path),
            "original_sha256": _sha256(original),
            "filtered_sha256": _sha256(filtered),
            "original_mode": stat.S_IMODE(file_stat.st_mode),
            "original_mtime_ns": file_stat.st_mtime_ns,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def _acquire_claim(
        self, original: bytes, filtered: bytes, file_stat: os.stat_result
    ) -> None:
        """Create the exclusive per-project claim atomically."""
        try:
            descriptor = os.open(
                str(self.claim_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError:
            raise SinglePlanProjectError(
                f"claim {self.claim_path.name} appeared while it was being "
                f"acquired; another launch is competing for "
                f"{self.project_path.name}. Wait for it to finish, then retry",
                kind="claim_conflict",
            ) from None
        except OSError as exc:
            raise SinglePlanProjectError(
                f"could not create claim {self.claim_path}: {exc}", kind="io"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    self._claim_payload(original, filtered, file_stat),
                    handle,
                    indent=1,
                )
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            _remove_quietly(self.claim_path)
            raise

    def _recover_stale_claim(self, current: bytes) -> None:
        """Serialize stale recovery so competing recoverers cannot undo a new claim."""
        recovery = self.claim_path.with_name(self.claim_path.name + ".recovery")
        try:
            descriptor = os.open(str(recovery), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise SinglePlanProjectError(
                f"Another recovery owns {recovery}; inspect that claim before retrying",
                kind="claim_conflict",
            ) from exc
        try:
            self._recover_stale_claim_locked(current)
        finally:
            os.close(descriptor)
            _remove_quietly(recovery)

    def _recover_stale_claim_locked(self, current: bytes) -> None:
        """Clear a claim whose owner is gone and whose project state is provable.

        Any doubt (live or unknown owner, unreadable claim, missing or altered
        backup, project bytes matching neither recorded state) fails closed
        with the recovery path.
        """
        claim = self.claim_path
        project = self.project_path
        try:
            record = json.loads(claim.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("claim is not a JSON object")
            if record.get("format") != CLAIM_FORMAT:
                raise ValueError("claim format is not recognized")
        except (OSError, ValueError) as exc:
            raise SinglePlanProjectError(
                f"{project.name} carries an unreadable single-plan claim "
                f"({claim}: {exc}). Confirm no HEC-RAS process is using the "
                f"project, compare {project.name} with any "
                f"{self.backup_path.name} backup, then delete the claim",
                kind="claim_conflict",
            ) from exc
        owner = record.get("owner") if isinstance(record.get("owner"), dict) else {}
        alive = _claim_owner_alive(owner)
        description = (
            f"{record.get('launch_owner', 'unknown launcher')} pid "
            f"{owner.get('pid')} on {owner.get('host')} since "
            f"{record.get('created_at')} for plan {record.get('plan_number')}"
        )
        if alive is not False:
            state = "is still running" if alive else "could not be verified"
            raise SinglePlanProjectError(
                f"{project.name} is already exposed as a single-plan project by "
                f"another launch ({description}); its owner {state}. Wait for "
                "that launch to finish. If it is known to be dead, confirm "
                f"{project.name} matches {self.backup_path.name} (or copy the "
                f"backup over it), then delete {claim}",
                kind="claim_conflict",
            )
        backup = _read_bytes(self.backup_path)
        recorded_original = record.get("original_sha256")
        recorded_filtered = record.get("filtered_sha256")
        if backup is None or _sha256(backup) != recorded_original:
            raise SinglePlanProjectError(
                f"{project.name} carries a stale single-plan claim "
                f"({description}) but its backup {self.backup_path.name} is "
                f"{'missing' if backup is None else 'altered'}; inspect the "
                "project file manually, restore the full plan list, then "
                f"delete {claim}",
                kind="claim_conflict",
            )
        current_sha = _sha256(current)
        if current_sha == recorded_filtered:
            mode = record.get("original_mode")
            mode = mode if isinstance(mode, int) and not isinstance(mode, bool) else None
            try:
                _write_file_atomically(project, backup, mode)
            except OSError as exc:
                raise SinglePlanProjectError(
                    f"could not restore {project.name} from the stale backup "
                    f"{self.backup_path}: {exc}",
                    kind="io",
                ) from exc
            if _read_bytes(project) != backup:
                raise SinglePlanProjectError(
                    f"{project.name} did not read back as the stale backup "
                    f"{self.backup_path.name}; restore it manually, then delete "
                    f"{claim}",
                    kind="io",
                )
            logger.warning(
                "Recovered %s from the stale single-plan backup left by %s",
                project.name,
                description,
            )
        elif current_sha == recorded_original:
            logger.warning(
                "Cleared a stale single-plan claim on %s left by %s; the "
                "project file already held the original declaration",
                project.name,
                description,
            )
        else:
            raise SinglePlanProjectError(
                f"{project.name} carries a stale single-plan claim "
                f"({description}) and now matches neither the recorded original "
                f"nor the recorded single-plan declaration. Inspect "
                f"{project.name} and {self.backup_path}, restore the intended "
                f"plan list manually, then delete {claim}",
                kind="claim_conflict",
            )
        if not (_remove_quietly(self.backup_path) and _remove_quietly(claim)):
            raise SinglePlanProjectError(
                f"could not remove the stale single-plan files beside "
                f"{project.name}; delete {self.backup_path.name} and "
                f"{claim.name} manually",
                kind="io",
            )
        self._stale_claim_recovered = True

    # ---------------------------------------------------------------- restore
    def restore(self, *, owned_quiescent: bool = True) -> SinglePlanProjectRestore:
        """Put the original project bytes back; report instead of raising.

        ``owned_quiescent`` states that the launch's HEC-RAS processes are
        proved stopped. Otherwise leave the single-plan declaration, original
        backup and claim in place so a surviving engine cannot discover other
        plans. Restoration failures retain the recovery files.
        """
        try:
            return self._restore(owned_quiescent=owned_quiescent)
        except Exception as exc:
            detail = (
                f"Could not restore {self.project_path.name}: {exc}. "
                f"The original backup {self.backup_path} and claim "
                f"{self.claim_path} are retained. Confirm all HEC-RAS processes "
                "are stopped before restoring the project from the backup."
            )
            logger.critical(detail)
            self._outcome = SinglePlanProjectRestore(
                restored=False, proved=False, detail=detail,
                backup_path=str(self.backup_path), claim_path=str(self.claim_path),
            )
            self._released = True
            return self._outcome

    def _restore(self, *, owned_quiescent: bool) -> SinglePlanProjectRestore:
        if self._outcome is not None:
            return self._outcome
        if not self._applied:
            self._outcome = SinglePlanProjectRestore(
                restored=True,
                proved=True,
                detail="no single-plan declaration was applied",
            )
            self._released = True
            return self._outcome
        project = self.project_path
        if not owned_quiescent:
            detail = (
                f"HEC-RAS processes for {project.name} could not be proved stopped. "
                "The single-plan declaration remains in place. Confirm all owned "
                f"processes have stopped, then restore {project} from "
                f"{self.backup_path} and remove {self.claim_path}."
            )
            logger.critical(detail)
            self._outcome = SinglePlanProjectRestore(
                restored=False, proved=False, detail=detail,
                backup_path=str(self.backup_path), claim_path=str(self.claim_path),
            )
            self._released = True
            return self._outcome
        assert self._original is not None and self._filtered is not None
        rewrite_path: Optional[Path] = None
        current = _read_bytes(project)
        if current != self._filtered:
            if current is None:
                logger.warning(
                    "%s disappeared during the single-plan launch; restoring "
                    "the original declaration",
                    project.name,
                )
            else:
                rewrite_path = project.with_name(
                    project.name
                    + REWRITE_SUFFIX
                    + time.strftime("%Y%m%dT%H%M%S")
                    + f"-{os.getpid()}"
                )
                try:
                    rewrite_path.write_bytes(current)
                except OSError as exc:
                    logger.critical(
                        "%s was rewritten during the single-plan launch and the "
                        "rewrite could not be preserved (%s)",
                        project.name,
                        exc,
                    )
                    raise OSError(
                        "Refusing to overwrite the unexpected project rewrite "
                        "because its recovery copy could not be written"
                    ) from exc
                else:
                    logger.warning(
                        "%s was rewritten during the single-plan launch; the "
                        "rewritten bytes were preserved in %s and the original "
                        "declaration is being restored",
                        project.name,
                        rewrite_path,
                    )
        restored = False
        failure: Optional[str] = None
        try:
            _write_file_atomically(project, self._original, self._original_mode)
            observed = _read_bytes(project)
            if observed != self._original:
                failure = "project bytes did not read back as the original"
            else:
                mode_now = stat.S_IMODE(os.stat(project).st_mode)
                if self._original_mode is not None and mode_now != self._original_mode:
                    failure = (
                        f"project mode {oct(mode_now)} differs from the original "
                        f"{oct(self._original_mode)}"
                    )
                else:
                    restored = True
        except OSError as exc:
            failure = f"{type(exc).__name__}: {exc}"
        if restored and self._original_times_ns is not None:
            try:
                os.utime(project, ns=self._original_times_ns)
            except OSError:
                pass
        if not restored:
            detail = (
                f"Could not restore the original declaration of {project.name} "
                f"after the HEC-RAS 7.0.2 launch ({failure}). The original bytes "
                f"are retained in {self.backup_path}; copy that file over "
                f"{project}, then delete {self.claim_path}"
            )
            logger.critical(detail)
            self._outcome = SinglePlanProjectRestore(
                restored=False,
                proved=False,
                detail=detail,
                backup_path=str(self.backup_path),
                claim_path=str(self.claim_path),
                unexpected_rewrite_path=str(rewrite_path) if rewrite_path else None,
            )
            self._released = True
            return self._outcome
        backup_gone = _remove_quietly(self.backup_path)
        claim_gone = _remove_quietly(self.claim_path)
        if not (backup_gone and claim_gone):
            leftovers = ", ".join(
                str(path)
                for path, gone in ((self.backup_path, backup_gone), (self.claim_path, claim_gone))
                if not gone
            )
            detail = (
                f"Restored the original declaration of {project.name}, but could "
                f"not remove {leftovers}; delete the leftover file(s) after "
                "confirming the project file is intact"
            )
            logger.critical(detail)
            self._outcome = SinglePlanProjectRestore(
                restored=True,
                proved=False,
                detail=detail,
                backup_path=str(self.backup_path),
                claim_path=str(self.claim_path),
                unexpected_rewrite_path=str(rewrite_path) if rewrite_path else None,
            )
            self._released = True
            return self._outcome
        detail = f"restored the original declaration of {project.name}"
        if rewrite_path is not None:
            detail += f"; an unexpected rewrite was preserved in {rewrite_path}"
        logger.info(
            "Restored the full plan list of %s after the HEC-RAS 7.0.2 launch "
            "of plan %s",
            project.name,
            self.plan_number,
        )
        self._outcome = SinglePlanProjectRestore(
            restored=True,
            proved=True,
            detail=detail,
            unexpected_rewrite_path=str(rewrite_path) if rewrite_path else None,
        )
        self._released = True
        return self._outcome


class SinglePlanLaunchLifecycle:
    """Hold one transaction for a launch and finish it exactly once.

    ``prove_quiescent`` is an optional callable that returns whether the
    launch's HEC-RAS processes are stopped; it runs immediately before
    restoration.  :meth:`finish` is idempotent so that both the normal result
    path and an exception ``finally`` can call it.
    """

    def __init__(self) -> None:
        self.transaction: Optional[SinglePlanProjectTransaction] = None
        self.prove_quiescent: Optional[Callable[[], bool]] = None
        self.outcome: Optional[SinglePlanProjectRestore] = None

    @property
    def pending(self) -> bool:
        transaction = self.transaction
        return (
            transaction is not None
            and transaction.applied
            and not transaction.released
        )

    def finish(self) -> Optional[SinglePlanProjectRestore]:
        if not self.pending:
            return self.outcome
        quiescent = True
        if self.prove_quiescent is not None:
            try:
                quiescent = bool(self.prove_quiescent())
            except Exception as exc:
                logger.warning(
                    "Could not prove owned HEC-RAS quiescence before restoring "
                    "%s: %s",
                    self.transaction.project_path.name,
                    exc,
                )
                quiescent = False
        self.outcome = self.transaction.restore(owned_quiescent=quiescent)
        return self.outcome
