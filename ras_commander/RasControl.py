"""
RasControl - HECRASController API Wrapper (ras-commander style)

Provides ras-commander style API for legacy HEC-RAS versions (3.x-4.x)
that use HECRASController COM interface instead of HDF files.

Includes robust process management with session tracking, orphan detection,
and optional watchdog protection for Jupyter kernel restarts.

Public functions (HEC-RAS Operations):
- RasControl.run_plan(..., blocking=False, controller_version=None, strict_close=False) -> RasControlResult
- RasControl.get_controller_progid(version) -> str
- RasControl.get_steady_results(plan, ras_object=None) -> pandas.DataFrame
- RasControl.get_unsteady_results(plan, max_times=None, ras_object=None) -> pandas.DataFrame
- RasControl.get_output_times(plan, ras_object=None) -> List[str]
- RasControl.get_plans(plan, ras_object=None) -> List[dict]
- RasControl.set_current_plan(plan, ras_object=None) -> bool
- RasControl.get_comp_msgs(plan, ras_object=None) -> str

Public functions (Process Management):
- RasControl.inspect_processes() -> RasProcessInventory
- RasControl.list_processes(show_all=False) -> pandas.DataFrame
- RasControl.scan_orphans() -> List[SessionLock]
- RasControl.cleanup_orphans(interactive=True, dry_run=False) -> int
- RasControl.force_cleanup_all() -> int

Private functions:
- _terminate_ras_process() -> None
- _is_ras_running() -> bool
- RasControl._normalize_version(version: str) -> str
- RasControl._get_project_info(plan, ras_object=None) -> Tuple[Path, str, Optional[str], Optional[str]]
- RasControl._com_open_close(..., strict_close=False) -> Any

Session tracking infrastructure:
- SessionLock dataclass - Tracks active COM sessions with lock files
- Module-level _active_sessions dict - Tracks all active sessions
- atexit handler - Emergency cleanup on Python exit
- Watchdog support - Optional independent process for kernel restart protection

"""

import hashlib
import math
import psutil
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Any, Union, Dict, TYPE_CHECKING
import logging
import time
import json
import socket
import tempfile
import uuid
import atexit
import sys
import subprocess
import os
from dataclasses import dataclass, asdict

# Win32 COM interface - Windows only
try:
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    win32com = None
    WIN32_AVAILABLE = False

from .LoggingConfig import get_logger
from .Decorators import log_call
from .ExecutionArtifacts import (
    finalize_plan_execution_artifacts,
    get_plan_result_artifact_paths,
    normalize_program_version,
    prepare_plan_execution_artifacts,
    program_version_major,
)
from .RasPrj import ras

if TYPE_CHECKING:
    from .ComputeResults import RasControlResult, RasProcessInventory

logger = get_logger(__name__)


def _log_failed_extraction_comp_msgs(comp_msgs_file: Path, comp_msgs: str) -> None:
    """Log failed extraction compute messages without dumping full text at ERROR."""
    logger.error(
        "Computation messages found for failed extraction: %s (%s characters); "
        "enable DEBUG logging for full contents",
        comp_msgs_file.name,
        len(comp_msgs),
    )
    logger.debug(f"Computation messages from {comp_msgs_file}:\n{comp_msgs}")


# ============================================================================
# SESSION TRACKING INFRASTRUCTURE
# ============================================================================

@dataclass
class SessionLock:
    """
    Represents a tracked RasControl session for process cleanup.

    Stored as JSON in temp directory to track active COM sessions and enable
    orphan detection after crashes/kernel restarts.
    """
    python_pid: int              # Python process PID
    ras_pid: Optional[int]       # ras.exe PID (None if couldn't detect)
    project_path: str            # Absolute path to .prj file
    ras_version: str             # HEC-RAS version (e.g., "6.5")
    session_id: str              # Unique session UUID
    start_time: float            # time.time() when session started
    python_exe: str              # sys.executable
    hostname: str                # socket.gethostname()
    detection_confidence: int    # 0-100 score from PID detection
    ras_create_time: Optional[float] = None  # PID-reuse-resistant identity
    ras_executable_path: Optional[str] = None  # Verified running image path
    ras_executable_sha256: Optional[str] = None  # Stable running image digest
    watchdog_pid: Optional[int] = None
    watchdog_create_time: Optional[float] = None
    watchdog_name: Optional[str] = None
    identity_unverified: bool = False
    validation_error: Optional[str] = None

    def __post_init__(self) -> None:
        """Reject non-finite or non-JSON-safe live session identities."""
        integer_fields = {
            'python_pid': self.python_pid,
            'detection_confidence': self.detection_confidence,
        }
        for field_name, value in integer_fields.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"SessionLock {field_name} must be an integer")
        if self.python_pid < 0:
            raise ValueError("SessionLock python_pid must be nonnegative")
        if not 0 <= self.detection_confidence <= 100:
            raise ValueError(
                "SessionLock detection_confidence must be between 0 and 100"
            )
        for field_name, value in {
            'ras_pid': self.ras_pid,
            'watchdog_pid': self.watchdog_pid,
        }.items():
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(
                    f"SessionLock {field_name} must be a positive integer or null"
                )
        if (
            isinstance(self.start_time, bool)
            or not isinstance(self.start_time, (int, float))
            or not math.isfinite(float(self.start_time))
        ):
            raise ValueError("SessionLock start_time must be finite")
        for field_name, value in {
            'ras_create_time': self.ras_create_time,
            'watchdog_create_time': self.watchdog_create_time,
        }.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ) and value is not None:
                raise ValueError(
                    f"SessionLock {field_name} must be finite or null"
                )
        for field_name, value in {
            'project_path': self.project_path,
            'ras_version': self.ras_version,
            'session_id': self.session_id,
            'python_exe': self.python_exe,
            'hostname': self.hostname,
        }.items():
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"SessionLock {field_name} must be a nonempty string"
                )
        for field_name, value in {
            'ras_executable_path': self.ras_executable_path,
            'ras_executable_sha256': self.ras_executable_sha256,
            'watchdog_name': self.watchdog_name,
            'validation_error': self.validation_error,
        }.items():
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"SessionLock {field_name} must be a string or null"
                )
            if isinstance(value, str) and not value:
                raise ValueError(
                    f"SessionLock {field_name} must be nonempty or null"
                )
        if not isinstance(self.identity_unverified, bool):
            raise ValueError("SessionLock identity_unverified must be boolean")
        if self.watchdog_pid is None and (
            self.watchdog_create_time is not None or self.watchdog_name is not None
        ):
            raise ValueError(
                "SessionLock watchdog identity must be complete or entirely absent"
            )
        if (
            self.watchdog_pid is not None
            and not self.identity_unverified
            and (self.watchdog_create_time is None or self.watchdog_name is None)
        ):
            raise ValueError(
                "SessionLock watchdog identity must be complete unless quarantined"
            )
        if (
            self.ras_pid is not None
            and not self.identity_unverified
            and (
                self.ras_create_time is None
                or self.ras_executable_path is None
                or self.ras_executable_sha256 is None
            )
        ):
            raise ValueError(
                "SessionLock Ras.exe identity must be complete unless quarantined"
            )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        self.__post_init__()
        return json.dumps(asdict(self), indent=2, allow_nan=False)

    @classmethod
    def from_json(cls, data: str) -> 'SessionLock':
        """Deserialize from JSON string."""
        payload = json.loads(data)
        # Locks written before execution-provenance capture did not contain a
        # process creation time. Preserve read compatibility, but cleanup must
        # never signal such an unproven PID.
        payload.setdefault('ras_create_time', None)
        payload.setdefault('ras_executable_path', None)
        payload.setdefault('ras_executable_sha256', None)
        payload.setdefault('watchdog_pid', None)
        payload.setdefault('watchdog_create_time', None)
        payload.setdefault('watchdog_name', None)
        payload.setdefault('identity_unverified', False)
        payload.setdefault('validation_error', None)
        if payload.get('ras_pid') is not None and any(
            payload.get(field) is None
            for field in (
                'ras_create_time',
                'ras_executable_path',
                'ras_executable_sha256',
            )
        ):
            payload['identity_unverified'] = True
            payload['validation_error'] = (
                payload.get('validation_error')
                or "legacy lock lacks complete Ras.exe process provenance"
            )
        try:
            return cls(**payload)
        except (TypeError, ValueError) as exc:
            # Syntactically readable legacy evidence is retained in a strict,
            # JSON-safe quarantine record. It can be reported, but never used
            # to signal a PID or justify deleting the original lock file.
            return cls(
                python_pid=0,
                ras_pid=None,
                project_path=(
                    payload.get('project_path')
                    if isinstance(payload.get('project_path'), str)
                    and payload.get('project_path')
                    else '[invalid legacy project path]'
                ),
                ras_version=(
                    payload.get('ras_version')
                    if isinstance(payload.get('ras_version'), str)
                    and payload.get('ras_version')
                    else '[invalid legacy version]'
                ),
                session_id=(
                    payload.get('session_id')
                    if isinstance(payload.get('session_id'), str)
                    and payload.get('session_id')
                    else '[invalid legacy session]'
                ),
                start_time=0.0,
                python_exe=(
                    payload.get('python_exe')
                    if isinstance(payload.get('python_exe'), str)
                    and payload.get('python_exe')
                    else '[invalid legacy Python]'
                ),
                hostname=(
                    payload.get('hostname')
                    if isinstance(payload.get('hostname'), str)
                    and payload.get('hostname')
                    else '[invalid legacy host]'
                ),
                detection_confidence=0,
                identity_unverified=True,
                validation_error=f"{type(exc).__name__}: {exc}",
            )

    @classmethod
    def from_file(cls, path: Path) -> 'SessionLock':
        """Load from lock file."""
        return cls.from_json(path.read_text(encoding='utf-8'))


@dataclass(frozen=True)
class _SessionCleanupResult:
    """Outcome of cleaning one Controller-owned process and session lock."""

    session_id: str
    ras_pid: Optional[int]
    process_detected: bool = False
    terminated: bool = False
    killed: bool = False
    process_survived: bool = False
    lock_retained: bool = False
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Return True when no identified Controller-owned process survived."""
        return not self.process_survived


@dataclass(frozen=True)
class _WatchdogIdentity:
    """Exact watchdog process identity captured immediately after launch."""

    pid: int
    create_time: Optional[float]
    name: Optional[str]

    @property
    def complete(self) -> bool:
        return (
            isinstance(self.pid, int)
            and not isinstance(self.pid, bool)
            and self.pid > 0
            and isinstance(self.create_time, (int, float))
            and not isinstance(self.create_time, bool)
            and math.isfinite(float(self.create_time))
            and isinstance(self.name, str)
            and bool(self.name)
        )


@dataclass(frozen=True)
class _WatchdogCleanupResult:
    """Fail-closed result of exact watchdog process cleanup."""

    pid: int
    identity_state: str
    terminated: bool = False
    killed: bool = False
    error: Optional[str] = None

    @property
    def safe(self) -> bool:
        return self.identity_state in {
            'absent',
            'pid_reused',
            'terminated',
            'killed',
        }


@dataclass(frozen=True)
class _StoredCompMessageCandidate:
    """One inspected compute-message sidecar in deterministic precedence."""

    path: Path
    contents: Optional[str]
    source_sha256: Optional[str]
    error: Optional[str] = None


@dataclass
class ProjectInfo:
    """
    Resolved project information for RasControl operations.

    Returned by _get_project_info() to provide named access to
    project path, version, and plan details.

    Attributes:
        project_path: Path to the .prj file
        version: HEC-RAS version string (e.g., "4.1", "6.5")
        plan_number: Plan number (e.g., "01") or None if using direct path
        plan_name: Plan name from project or None if using direct path
    """
    project_path: Path
    version: str
    plan_number: Optional[str]
    plan_name: Optional[str]


# Module-level session tracking
_active_sessions: Dict[str, SessionLock] = {}  # {session_id: SessionLock}

# Lock file directory
LOCK_DIR = Path(tempfile.gettempdir()) / "rascontrol_sessions"
LOCK_DIR.mkdir(exist_ok=True)


def _get_lock_file_path(session_id: str) -> Path:
    """Generate lock file path for a session."""
    filename = f"rasctl_{os.getpid()}_{session_id}.lock"
    return LOCK_DIR / filename


def _file_identity(stat_result: os.stat_result) -> Tuple[int, ...]:
    """Return fields that must remain stable while hashing an executable."""
    return (
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(stat_result.st_ctime_ns),
    )


def _stable_file_sha256(path: Path) -> str:
    """Hash one file while rejecting replacement or mutation during reading."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        before = _file_identity(os.fstat(stream.fileno()))
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        after = _file_identity(os.fstat(stream.fileno()))
    if before != after:
        raise RuntimeError(f"Executable changed while hashing: {path}")
    return digest.hexdigest()


def _prove_ras_process_image(
    *,
    pid: int,
    create_time: float,
    snapshot_executable: str,
) -> Tuple[str, str]:
    """Prove one running Ras.exe identity and hash its stable image bytes.

    The PID creation time and executable path are checked immediately before
    and after hashing. This rejects PID reuse, a forged snapshot path, and a
    file mutation race rather than attributing unproven bytes to a Controller.
    """
    from ._process_inspection import _same_windows_path

    process = psutil.Process(pid)

    def verify() -> Path:
        if int(process.pid) != int(pid):
            raise RuntimeError("Controller PID changed during image proof")
        observed_create_time = float(process.create_time())
        if not math.isclose(
            observed_create_time,
            float(create_time),
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise RuntimeError("Controller PID identity changed during image proof")
        if process.name().casefold() != 'ras.exe':
            raise RuntimeError("Controller process image is not Ras.exe")
        observed_executable = str(process.exe())
        if not _same_windows_path(observed_executable, snapshot_executable):
            raise RuntimeError("Controller executable path changed after discovery")
        executable = Path(observed_executable).resolve(strict=True)
        if not executable.is_file() or executable.name.casefold() != 'ras.exe':
            raise RuntimeError("Controller executable is not a regular Ras.exe file")
        return executable

    executable = verify()
    executable_sha256 = _stable_file_sha256(executable)
    final_executable = verify()
    if not _same_windows_path(str(final_executable), str(executable)):
        raise RuntimeError("Controller executable identity changed while hashing")
    return str(final_executable), executable_sha256


def _find_our_ras_process(
    project_path: Path,
    before_snapshot: Dict[int, Any],
) -> Tuple[Optional[int], Optional[float], int, Optional[str], Optional[str]]:
    """
    Multi-strategy detection to find the ras.exe process we just launched.

    Args:
        project_path: Path to .prj file being opened
        before_snapshot: Dict of {pid: proc_info} before COM launch

    Returns:
        Tuple of ``(pid, create_time, confidence_score, executable_path,
        executable_sha256)``. Identity and image evidence are all absent if
        detection or proof fails. The initial identity/path is captured from
        one post-Dispatch process snapshot, then reverified before and after
        stable hashing so PID reuse or image replacement cannot be credited.
    """
    time.sleep(0.3)  # Give process time to appear

    candidates = {}  # {(pid, create_time): confidence_score}

    try:
        after = {
            p.pid: p.info
            for p in psutil.process_iter(
                ['pid', 'name', 'cmdline', 'create_time', 'cwd', 'exe']
            )
            if p.info['name'] and p.info['name'].lower() == 'ras.exe'
        }
    except Exception as e:
        logger.warning(f"Error scanning for ras.exe processes: {e}")
        return None, None, 0, None, None

    # A recycled PID is a new identity only when its process creation time
    # differs from the pre-dispatch snapshot.
    new_identities = set()
    for pid, info in after.items():
        try:
            create_time = float(info['create_time'])
        except (KeyError, TypeError, ValueError):
            continue
        before_info = before_snapshot.get(pid)
        before_create_time = (
            before_info.get('create_time')
            if isinstance(before_info, dict)
            else None
        )
        if before_info is None or before_create_time != info.get('create_time'):
            new_identities.add((pid, create_time))

    from ._process_inspection import _command_has_exact_path

    unique_new_identity = (
        next(iter(new_identities)) if len(new_identities) == 1 else None
    )

    for pid, proc_info in after.items():
        try:
            create_time = float(proc_info['create_time'])
        except (KeyError, TypeError, ValueError):
            continue
        identity = (pid, create_time)
        score = 0
        project_matches = False

        # Criteria 1: Newly appeared identity (50 points)
        if identity in new_identities:
            score += 50

        # Criteria 2: Exact project path token (40 points). Basename and
        # substring matches are deliberately insufficient.
        try:
            cmdline = proc_info['cmdline']
            if (
                isinstance(cmdline, (list, tuple))
                and _command_has_exact_path(
                    tuple(str(item) for item in cmdline),
                    project_path,
                    proc_info.get('cwd'),
                )
            ):
                project_matches = True
                score += 40
        except (TypeError, AttributeError, KeyError):
            pass

        # Criteria 3: Very recent creation time (30 points)
        try:
            age = time.time() - create_time
            if age < 2.0:  # Created within 2 seconds
                score += 30
        except (TypeError, KeyError):
            pass

        # Criteria 4: Only one new identity (20 points). Under host-exclusive
        # dispatch this is sufficient attribution even when the Controller
        # command line omits the project path.
        if unique_new_identity == identity:
            score += 20

        if project_matches or unique_new_identity == identity:
            candidates[identity] = score

    if not candidates:
        logger.warning(f"Could not reliably identify ras.exe PID for {project_path.name}")
        return None, None, 0, None, None

    # Return highest confidence identity from the atomic snapshot.
    best_identity = max(candidates, key=candidates.get)
    best_pid, best_create_time = best_identity
    confidence = min(100, candidates[best_identity])

    snapshot_executable = after[best_pid].get('exe')
    if not isinstance(snapshot_executable, str) or not snapshot_executable.strip():
        logger.warning(
            "Could not prove ras.exe PID %s because its image path was unavailable",
            best_pid,
        )
        return None, None, 0, None, None
    try:
        executable_path, executable_sha256 = _prove_ras_process_image(
            pid=best_pid,
            create_time=best_create_time,
            snapshot_executable=snapshot_executable,
        )
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
    ) as exc:
        logger.warning(
            "Could not prove ras.exe PID %s image identity: %s",
            best_pid,
            exc,
        )
        return None, None, 0, None, None

    if confidence < 50:
        logger.warning(f"Low confidence ({confidence}/100) for PID {best_pid}")
    else:
        logger.debug(f"Detected ras.exe PID {best_pid} (confidence: {confidence}/100)")

    return (
        best_pid,
        best_create_time,
        confidence,
        executable_path,
        executable_sha256,
    )


def _process_matches_lock_identity(proc: Any, lock: SessionLock) -> bool:
    """Return True only for the exact PID/create-time identity in ``lock``."""
    if lock.ras_pid is None or lock.ras_create_time is None:
        return False
    if int(getattr(proc, 'pid', -1)) != int(lock.ras_pid):
        return False
    try:
        create_time = float(proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError, TypeError):
        return False
    return math.isclose(
        create_time,
        float(lock.ras_create_time),
        rel_tol=0.0,
        abs_tol=1e-6,
    )


def _classify_lock_file(lock: SessionLock) -> str:
    """
    Classify lock file state.

    Returns:
        'active' - Python still running, session active
        'stale_orphan' - Python dead, ras.exe still running
        'stale_clean' - Both dead, safe to delete
        'foreign_machine' - From different machine, don't touch
        'identity_unverified' - PID exists but creation time is unavailable;
                                preserve evidence and never signal it
    """
    if lock.identity_unverified:
        return 'identity_unverified'

    # Check 1: Different machine?
    if lock.hostname != socket.gethostname():
        return 'foreign_machine'

    # Check 2: Is Python process still running?
    python_alive = False
    try:
        python_proc = psutil.Process(lock.python_pid)
        if python_proc.is_running():
            # Verify it's actually Python (not PID reuse)
            if 'python' in python_proc.name().lower():
                python_alive = True
    except psutil.NoSuchProcess:
        pass
    except (psutil.AccessDenied, OSError, ValueError, TypeError):
        return 'identity_unverified'

    if python_alive:
        return 'active'

    # Check 3: Is ras.exe still running?
    if lock.ras_pid is not None:
        try:
            ras_proc = psutil.Process(lock.ras_pid)
            if ras_proc.is_running() and ras_proc.name().lower() == 'ras.exe':
                if lock.ras_create_time is None:
                    return 'identity_unverified'
                if not _process_matches_lock_identity(ras_proc, lock):
                    # The tracked Controller identity exited and this PID was
                    # reused. It is not our process and must not be signaled.
                    return 'stale_clean'
                # Verify it's working on our project (if cmdline available)
                try:
                    cmdline = ' '.join(ras_proc.cmdline() or [])
                    if lock.project_path in cmdline or Path(lock.project_path).name in cmdline:
                        return 'stale_orphan'  # Orphaned process!
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                # Couldn't verify project, but ras.exe exists - assume orphan if Python dead
                return 'stale_orphan'
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, OSError, ValueError, TypeError):
            return 'identity_unverified'

    return 'stale_clean'


def _create_session_lock(session_id: str, lock_data: SessionLock) -> Path:
    """Create a lock file for the session."""
    lock_path = _get_lock_file_path(session_id)
    try:
        lock_path.write_text(lock_data.to_json(), encoding='utf-8')
        logger.debug(f"Created session lock: {lock_path.name}")
        return lock_path
    except Exception as e:
        logger.warning(f"Failed to create session lock file: {e}")
        return lock_path


def _remove_session_lock(session_id: str) -> None:
    """Remove a session lock file."""
    lock_path = _get_lock_file_path(session_id)
    try:
        lock_path.unlink(missing_ok=True)
        logger.debug(f"Removed session lock: {lock_path.name}")
    except Exception as e:
        logger.warning(f"Failed to remove session lock file: {e}")


def _cleanup_session(session_id: str) -> _SessionCleanupResult:
    """Clean one session and retain its lock if an owned process survives."""
    lock = _active_sessions.get(session_id)
    if lock is None:
        return _SessionCleanupResult(session_id=session_id, ras_pid=None)

    if lock.identity_unverified:
        lock_retained = _get_lock_file_path(session_id).exists()
        return _SessionCleanupResult(
            session_id=session_id,
            ras_pid=lock.ras_pid,
            process_survived=True,
            lock_retained=lock_retained,
            error=lock.validation_error or "session identity is unverified",
        )

    detected = False
    terminated = False
    killed = False
    survived = False
    error = None

    if lock.ras_pid:
        try:
            proc = psutil.Process(lock.ras_pid)
            if (
                proc.is_running()
                and proc.name().lower() == 'ras.exe'
                and _process_matches_lock_identity(proc, lock)
            ):
                detected = True
                logger.debug(f"Terminating tracked ras.exe PID {lock.ras_pid}")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                    terminated = True
                except psutil.TimeoutExpired:
                    logger.warning(
                        f"Tracked ras.exe PID {lock.ras_pid} did not exit gracefully; forcing kill"
                    )
                    proc.kill()
                    killed = True
                    proc.wait(timeout=5)
                survived = (
                    proc.is_running()
                    and _process_matches_lock_identity(proc, lock)
                )
            elif proc.is_running() and proc.name().lower() == 'ras.exe':
                if lock.ras_create_time is None:
                    survived = True
                    error = (
                        "Tracked ras.exe PID has no creation-time identity; "
                        "refusing to signal it"
                    )
                    logger.warning(error)
                else:
                    logger.info(
                        "Tracked ras.exe PID %s was reused; refusing to signal "
                        "the replacement process",
                        lock.ras_pid,
                    )
        except psutil.NoSuchProcess:
            terminated = detected
        except (psutil.TimeoutExpired, psutil.AccessDenied) as exc:
            survived = True
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"Could not verify termination of PID {lock.ras_pid}: {exc}")

    if not survived and lock.watchdog_pid is not None:
        watchdog_cleanup = _terminate_watchdog(
            _WatchdogIdentity(
                pid=lock.watchdog_pid,
                create_time=lock.watchdog_create_time,
                name=lock.watchdog_name,
            )
        )
        if not watchdog_cleanup.safe:
            survived = True
            error = (
                "Watchdog identity/exit could not be proved: "
                f"{watchdog_cleanup.identity_state}; "
                f"{watchdog_cleanup.error or 'no detail'}"
            )
            lock.identity_unverified = True
            lock.validation_error = error
            try:
                _create_session_lock(session_id, lock)
            except Exception:
                pass

    if survived:
        lock_retained = _get_lock_file_path(session_id).exists()
        return _SessionCleanupResult(
            session_id=session_id,
            ras_pid=lock.ras_pid,
            process_detected=detected,
            terminated=terminated,
            killed=killed,
            process_survived=True,
            lock_retained=lock_retained,
            error=error,
        )

    _active_sessions.pop(session_id, None)
    _remove_session_lock(session_id)
    return _SessionCleanupResult(
        session_id=session_id,
        ras_pid=lock.ras_pid,
        process_detected=detected,
        terminated=terminated,
        killed=killed,
    )


def _emergency_cleanup_all() -> None:
    """
    Emergency cleanup of all tracked sessions.
    Called by atexit handler.
    """
    if not _active_sessions:
        return

    logger.info(f"Emergency cleanup: {len(_active_sessions)} active session(s)")

    for session_id in list(_active_sessions.keys()):
        _cleanup_session(session_id)


def _spawn_watchdog(parent_pid: int, ras_pid: int, ras_create_time: float,
                    max_runtime: int, lock_file_path: Path) -> Optional[_WatchdogIdentity]:
    """
    Spawn independent watchdog process for long-running operations.

    The watchdog monitors for:
    1. Parent Python process death (orphan detection)
    2. Runtime timeout
    3. Manual cancellation via lock file deletion

    Returns:
        Exact watchdog PID/create-time/name identity. ``None`` means no
        watchdog process survived launch. An incomplete identity is returned
        only when a launched PID exists but cannot be verified; callers must
        retain session evidence and fail closed.
    """
    try:
        try:
            parent = psutil.Process(parent_pid)
            parent_create_time = float(parent.create_time())
            parent_name = str(parent.name()).strip()
            if (
                not parent.is_running()
                or not math.isfinite(parent_create_time)
                or parent_create_time <= 0
                or not parent_name
            ):
                raise RuntimeError("parent process identity is invalid")
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            logger.error(
                "Could not prove watchdog parent PID %s identity: %s",
                parent_pid,
                exc,
            )
            return None

        watchdog_worker = Path(__file__).with_name('_orphan_watchdog.py')
        if not watchdog_worker.is_file():
            logger.error("Orphan-watchdog worker is unavailable: %s", watchdog_worker)
            return None

        # Launch watchdog as completely independent process
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        proc = subprocess.Popen(
            [
                sys.executable,
                str(watchdog_worker),
                '--parent-pid',
                str(parent_pid),
                '--parent-create-time',
                repr(parent_create_time),
                '--parent-name',
                parent_name,
                '--ras-pid',
                str(ras_pid),
                '--ras-create-time',
                repr(float(ras_create_time)),
                '--ras-name',
                'ras.exe',
                '--max-runtime',
                str(max_runtime),
                '--lock-file',
                str(lock_file_path),
            ],
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        try:
            watchdog = psutil.Process(proc.pid)
            identity = _WatchdogIdentity(
                pid=int(proc.pid),
                create_time=float(watchdog.create_time()),
                name=str(watchdog.name()),
            )
            state, _ = _watchdog_process_state(identity)
            if state == 'absent':
                return None
            if state != 'exact':
                return _WatchdogIdentity(int(proc.pid), None, None)
        except psutil.NoSuchProcess:
            return None
        except (psutil.AccessDenied, OSError, ValueError, TypeError) as exc:
            logger.error(
                "Spawned watchdog PID %s but could not prove its identity: %s",
                proc.pid,
                exc,
            )
            return _WatchdogIdentity(int(proc.pid), None, None)

        logger.debug(
            "Spawned watchdog process PID %s/create-time %.6f/name %s "
            "(monitoring PID %s)",
            identity.pid,
            identity.create_time,
            identity.name,
            ras_pid,
        )
        return identity
    except Exception as e:
        logger.error(f"Failed to spawn watchdog process: {e}")
        return None


def _watchdog_process_state(
    identity: _WatchdogIdentity,
) -> Tuple[str, Optional[Any]]:
    """Return exact/absent/reused/unknown for one watchdog identity."""
    if not identity.complete:
        return 'identity_unverified', None
    try:
        proc = psutil.Process(identity.pid)
        create_time = float(proc.create_time())
        name = str(proc.name())
        running = proc.is_running()
    except psutil.NoSuchProcess:
        return 'absent', None
    except (psutil.AccessDenied, OSError, ValueError, TypeError):
        return 'identity_unverified', None
    if not running:
        return 'absent', None
    if (
        not math.isclose(
            create_time,
            float(identity.create_time),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        or name.casefold() != str(identity.name).casefold()
    ):
        return 'pid_reused', None
    return 'exact', proc


def _terminate_watchdog(
    identity: Optional[_WatchdogIdentity],
) -> _WatchdogCleanupResult:
    """Stop only an exact watchdog identity, failing closed on uncertainty."""
    if identity is None:
        return _WatchdogCleanupResult(pid=0, identity_state='absent')

    state, proc = _watchdog_process_state(identity)
    if state != 'exact' or proc is None:
        return _WatchdogCleanupResult(pid=identity.pid, identity_state=state)
    try:
        # The lookup above is the immediate PID/create-time/name proof before
        # the first signal.
        proc.terminate()
        proc.wait(timeout=3)
    except psutil.NoSuchProcess:
        return _WatchdogCleanupResult(
            pid=identity.pid,
            identity_state='terminated',
            terminated=True,
        )
    except psutil.TimeoutExpired:
        # Re-open and reverify immediately before the stronger signal. A
        # reused PID is never killed; an unavailable identity retains evidence.
        kill_state, kill_proc = _watchdog_process_state(identity)
        if kill_state != 'exact' or kill_proc is None:
            return _WatchdogCleanupResult(
                pid=identity.pid,
                identity_state=kill_state,
                terminated=True,
            )
        try:
            kill_proc.kill()
            kill_proc.wait(timeout=3)
        except psutil.NoSuchProcess:
            return _WatchdogCleanupResult(
                pid=identity.pid,
                identity_state='killed',
                terminated=True,
                killed=True,
            )
        except (psutil.TimeoutExpired, psutil.AccessDenied, OSError) as exc:
            return _WatchdogCleanupResult(
                pid=identity.pid,
                identity_state='identity_unverified',
                terminated=True,
                killed=True,
                error=f"{type(exc).__name__}: {exc}",
            )
        final_state, _ = _watchdog_process_state(identity)
        if final_state in {'absent', 'pid_reused'}:
            return _WatchdogCleanupResult(
                pid=identity.pid,
                identity_state='killed',
                terminated=True,
                killed=True,
            )
        return _WatchdogCleanupResult(
            pid=identity.pid,
            identity_state='identity_unverified',
            terminated=True,
            killed=True,
            error=f"watchdog post-kill state: {final_state}",
        )
    except (psutil.AccessDenied, OSError) as exc:
        return _WatchdogCleanupResult(
            pid=identity.pid,
            identity_state='identity_unverified',
            error=f"{type(exc).__name__}: {exc}",
        )

    final_state, _ = _watchdog_process_state(identity)
    if final_state in {'absent', 'pid_reused'}:
        logger.debug(f"Terminated watchdog process PID {identity.pid}")
        return _WatchdogCleanupResult(
            pid=identity.pid,
            identity_state='terminated',
            terminated=True,
        )
    return _WatchdogCleanupResult(
        pid=identity.pid,
        identity_state='identity_unverified',
        terminated=True,
        error=f"watchdog post-terminate state: {final_state}",
    )


def _inspect_controller_post_close_processes(
    *,
    project_path: Path,
    plan_number: str,
):
    """Capture one strict host snapshot and narrow it to the executed plan."""
    from ._process_inspection import match_plan_processes, scan_ras_processes

    project_path = project_path.resolve(strict=False)
    plan_path = project_path.parent / f"{project_path.stem}.p{plan_number}"
    tmp_hdf_path = project_path.parent / (
        f"{project_path.stem}.p{plan_number}.tmp.hdf"
    )
    host_inventory = scan_ras_processes(psutil_module=psutil)
    plan_inventory = match_plan_processes(
        host_inventory,
        plan_number=plan_number,
        project_path=project_path,
        plan_path=plan_path,
        tmp_hdf_path=tmp_hdf_path,
    )
    return plan_inventory, host_inventory


# Register atexit cleanup handler
atexit.register(_emergency_cleanup_all)


# ============================================================================
# LEGACY PROCESS TERMINATION FUNCTIONS (kept for compatibility)
# ============================================================================

def _terminate_ras_process() -> None:
    """Force terminate any running ras.exe processes."""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'ras.exe':
                proc.terminate()
                proc.wait(timeout=3)
                logger.info("Terminated ras.exe process")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass


def _is_ras_running() -> bool:
    """Check if HEC-RAS is currently running"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'ras.exe':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


class RasControl:
    """
    HECRASController API wrapper with ras-commander style interface.

    Works with legacy HEC-RAS versions (3.x-4.x) that use COM interface
    instead of HDF files. Integrates with ras-commander project management.

    Usage (ras-commander style):
        >>> from ras_commander import init_ras_project, RasControl
        >>>
        >>> # Initialize with version (with or without periods)
        >>> init_ras_project(path, "4.1")  # or "41"
        >>>
        >>> # Use plan numbers like HDF methods
        >>> RasControl.run_plan("02")
        >>> df = RasControl.get_steady_results("02")

    Supported Versions:
        All installed versions: 3.x, 4.x, 5.0.x, 6.0-6.7+
        Accepts formats: "4.1", "41", "5.0.6", "506", "7.0", "66", etc.
    """

    # Version mapping based on HEC-RAS COM ProgIDs. Some releases do not
    # register a distinct controller and therefore retain a documented nearest
    # compatible fallback. HEC-RAS 4.0 does register RAS400 and must not be
    # silently executed by the 4.1 controller.
    VERSION_MAP = {
        # HEC-RAS 3.x → Use 4.1 (3.x COM not registered)
        '3.0': 'RAS41.HECRASController',
        '30': 'RAS41.HECRASController',
        '3.1': 'RAS41.HECRASController',
        '31': 'RAS41.HECRASController',
        '3.1.1': 'RAS41.HECRASController',
        '311': 'RAS41.HECRASController',
        '3.1.2': 'RAS41.HECRASController',
        '312': 'RAS41.HECRASController',
        '3.1.3': 'RAS41.HECRASController',
        '313': 'RAS41.HECRASController',

        # HEC-RAS 4.x
        '4.0': 'RAS400.HECRASController',   # ✓ EXISTS
        '40': 'RAS400.HECRASController',
        '4.1': 'RAS41.HECRASController',    # ✓ EXISTS
        '41': 'RAS41.HECRASController',
        '4.1.0': 'RAS41.HECRASController',
        '410': 'RAS41.HECRASController',

        # HEC-RAS 5.0.x
        '5.0': 'RAS500.HECRASController',   # ✓ EXISTS
        '50': 'RAS500.HECRASController',
        '5.0.1': 'RAS501.HECRASController', # ✓ EXISTS
        '501': 'RAS501.HECRASController',
        '5.0.3': 'RAS503.HECRASController', # ✓ EXISTS
        '503': 'RAS503.HECRASController',
        '5.0.4': 'RAS504.HECRASController', # ✓ EXISTS (newly installed)
        '504': 'RAS504.HECRASController',
        '5.0.5': 'RAS505.HECRASController', # ✓ EXISTS
        '505': 'RAS505.HECRASController',
        '5.0.6': 'RAS506.HECRASController', # ✓ EXISTS
        '506': 'RAS506.HECRASController',
        '5.0.7': 'RAS507.HECRASController', # ✓ EXISTS
        '507': 'RAS507.HECRASController',

        # HEC-RAS 6.x
        '6.0': 'RAS60.HECRASController',    # ✓ EXISTS
        '60': 'RAS60.HECRASController',
        '6.1': 'RAS610.HECRASController',   # ✓ EXISTS
        '61': 'RAS610.HECRASController',
        '6.2': 'RAS620.HECRASController',   # ✓ EXISTS
        '62': 'RAS620.HECRASController',
        '6.3': 'RAS630.HECRASController',   # ✓ EXISTS
        '63': 'RAS630.HECRASController',
        '6.3.0': 'RAS630.HECRASController',
        '6.3.0.2': 'RAS630.HECRASController',
        '630': 'RAS630.HECRASController',
        '6.3.1': 'RAS631.HECRASController', # ✓ EXISTS
        '631': 'RAS631.HECRASController',
        '6.4': 'RAS641.HECRASController',   # Use 6.4.1 (6.4 COM not registered)
        '64': 'RAS641.HECRASController',
        '6.4.1': 'RAS641.HECRASController', # ✓ EXISTS
        '641': 'RAS641.HECRASController',
        '6.5': 'RAS65.HECRASController',    # ✓ EXISTS
        '65': 'RAS65.HECRASController',
        '6.6': 'RAS66.HECRASController',    # ✓ EXISTS
        '66': 'RAS66.HECRASController',
        '6.7': 'RAS67.HECRASController',    # ✓ EXISTS
        '67': 'RAS67.HECRASController',
        '6.7 Beta 4': 'RAS67.HECRASController',
        '6.7 Beta 5': 'RAS67.HECRASController',
        '7.0': 'RAS70.HECRASController',    # ✓ EXISTS
        '70': 'RAS70.HECRASController',
    }

    _CONTROLLER_CANONICAL_VERSIONS = {
        'RAS400.HECRASController': '4.0',
        'RAS41.HECRASController': '4.1',
        'RAS500.HECRASController': '5.0',
        'RAS501.HECRASController': '5.0.1',
        'RAS503.HECRASController': '5.0.3',
        'RAS504.HECRASController': '5.0.4',
        'RAS505.HECRASController': '5.0.5',
        'RAS506.HECRASController': '5.0.6',
        'RAS507.HECRASController': '5.0.7',
        'RAS60.HECRASController': '6.0',
        'RAS610.HECRASController': '6.1',
        'RAS620.HECRASController': '6.2',
        'RAS630.HECRASController': '6.3.0.2',
        'RAS631.HECRASController': '6.3.1',
        'RAS641.HECRASController': '6.4.1',
        'RAS65.HECRASController': '6.5',
        'RAS66.HECRASController': '6.6',
        'RAS67.HECRASController': '6.7',
        'RAS70.HECRASController': '7.0',
    }

    # Legacy reference (kept for backwards compatibility)
    SUPPORTED_VERSIONS = VERSION_MAP

    # Output variable codes
    WSEL = 2
    ENERGY = 3
    MAX_CHL_DPTH = 4
    MIN_CH_EL = 5
    ENERGY_SLOPE = 6
    FLOW_TOTAL = 24
    VEL_TOTAL = 25
    STA_WS_LFT = 36
    STA_WS_RGT = 37
    FROUDE_CHL = 48
    FROUDE_XS = 49
    Q_WEIR = 94
    Q_CULVERT_TOT = 242

    # ========== PRIVATE METHODS (HECRASController COM API) ==========

    @staticmethod
    def _normalize_version(version: str) -> str:
        """
        Normalize version string to match VERSION_MAP keys.

        Handles formats like:
            "7.0", "66" → "7.0"
            "4.1", "41" → "4.1"
            "5.0.6", "506" → "5.0.6"
            "6.7 Beta 4" → "6.7 Beta 4"

        Returns:
            Normalized version string that exists in VERSION_MAP

        Raises:
            ValueError: If version cannot be normalized or is not supported
        """
        version_str = str(version).strip()

        artifact_normalized = normalize_program_version(version_str)
        if artifact_normalized in RasControl.VERSION_MAP:
            version_str = artifact_normalized

        # Direct match
        if version_str in RasControl.VERSION_MAP:
            return version_str

        # Try common normalizations
        normalized_candidates = [
            version_str,
            version_str.replace('.', ''),  # "7.0" → "66"
        ]

        # Try adding periods for compact formats
        if len(version_str) == 2:  # "66" → "7.0"
            normalized_candidates.append(f"{version_str[0]}.{version_str[1]}")
        elif len(version_str) == 3 and version_str.startswith('5'):  # "506" → "5.0.6"
            normalized_candidates.append(f"5.0.{version_str[2]}")
        elif len(version_str) == 3:  # "631" → "6.3.1"
            normalized_candidates.append(f"{version_str[0]}.{version_str[1]}.{version_str[2]}")

        # Check all candidates
        for candidate in normalized_candidates:
            if candidate in RasControl.VERSION_MAP:
                logger.debug(f"Normalized version '{version}' → '{candidate}'")
                return candidate

        # Not found
        raise ValueError(
            f"Version '{version}' not supported. Supported versions:\n"
            f"  3.x: 3.0, 3.1 (3.1.1, 3.1.2, 3.1.3)\n"
            f"  4.x: 4.0, 4.1\n"
            f"  5.0.x: 5.0, 5.0.1, 5.0.3, 5.0.4, 5.0.5, 5.0.6, 5.0.7\n"
            f"  6.x: 6.0, 6.1, 6.2, 6.3, 6.3.0.2, 6.3.1, 6.4, 6.4.1, 6.5, 6.6, 6.7\n"
            f"  7.x: 7.0\n"
            f"  Formats: Can use '6.6' or '66', '5.0.6' or '506', etc."
        )

    @staticmethod
    @log_call
    def get_controller_progid(version: str) -> str:
        """Return ras-commander's configured Controller ProgID for a version.

        This performs a static mapping; COM registration is checked only when
        the Controller is dispatched. Exact product identities remain distinct
        from patch releases: ``6.3`` and ``6.3.0.2`` resolve to
        ``RAS630.HECRASController`` while ``6.3.1`` resolves to
        ``RAS631.HECRASController``.
        """
        normalized = RasControl._normalize_version(version)
        return RasControl.VERSION_MAP[normalized]

    @staticmethod
    def _get_project_info(plan: Union[str, Path], ras_object=None) -> ProjectInfo:
        """
        Resolve plan number/path to project path, version, and plan details.

        Returns:
            ProjectInfo: Dataclass with project_path, version, plan_number, and plan_name.
            plan_number and plan_name are None if using direct .prj path.
        """
        if ras_object is None:
            ras_object = ras

        # If it's a path to .prj file
        plan_path = Path(plan) if isinstance(plan, str) else plan
        if plan_path.exists() and plan_path.suffix == '.prj':
            # Direct path - need version from ras_object
            if not hasattr(ras_object, 'ras_version') or not ras_object.ras_version:
                raise ValueError(
                    "When using direct .prj paths, project must be initialized with version.\n"
                    "Use: init_ras_project(path, '4.1') or similar"
                )
            current_plan_number = None
            current_plan_name = None
            try:
                for line in plan_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines():
                    key, separator, value = line.partition("=")
                    if separator and key.strip() == "Current Plan":
                        token = value.strip().lstrip("pP")
                        if token.isdigit():
                            current_plan_number = token.zfill(2)
                        break
                if (
                    current_plan_number is not None
                    and hasattr(ras_object, "plan_df")
                ):
                    rows = ras_object.plan_df[
                        ras_object.plan_df["plan_number"].astype(str).str.zfill(2)
                        == current_plan_number
                    ]
                    if not rows.empty:
                        current_plan_name = rows.iloc[0].get("Plan Title")
            except (OSError, KeyError, TypeError):
                logger.debug(
                    "Could not resolve Current Plan from direct project path: %s",
                    plan_path,
                )
            return ProjectInfo(
                project_path=plan_path,
                version=ras_object.ras_version,
                plan_number=current_plan_number,
                plan_name=current_plan_name,
            )

        # Otherwise treat as plan number
        plan_num = str(plan).zfill(2)

        # Get project path from ras_object
        if not hasattr(ras_object, 'prj_file') or not ras_object.prj_file:
            raise ValueError(
                "No project initialized. Use init_ras_project() first.\n"
                "Example: init_ras_project(path, '4.1')"
            )

        project_path = Path(ras_object.prj_file)

        # Get version
        if not hasattr(ras_object, 'ras_version') or not ras_object.ras_version:
            raise ValueError(
                "Project initialized without version. Re-initialize with:\n"
                "init_ras_project(path, '4.1')  # or '41', '501', etc."
            )

        version = ras_object.ras_version

        # Get plan name from plan_df
        plan_row = ras_object.plan_df[ras_object.plan_df['plan_number'] == plan_num]
        if plan_row.empty:
            raise ValueError(f"Plan '{plan_num}' not found in project")

        plan_name = plan_row['Plan Title'].iloc[0]

        return ProjectInfo(
            project_path=project_path,
            version=version,
            plan_number=plan_num,
            plan_name=plan_name
        )

    @staticmethod
    def _com_open_close(
        project_path: Path,
        version: str,
        operation_func: Callable[[Any], Any],
        *,
        strict_close: bool = False,
        require_safe_close: bool = False,
        close_outcome_callback: Optional[
            Callable[[bool, _SessionCleanupResult, Optional[BaseException]], None]
        ] = None,
        session_open_callback: Optional[Callable[[SessionLock], None]] = None,
    ) -> Any:
        """
        PRIVATE: Open HEC-RAS via COM, run operation, close HEC-RAS.

        This is the core COM interface handler. All public methods use this.
        Includes session tracking for robust cleanup on crashes/kernel restarts.
        When ``strict_close`` is True, a failed ``QuitRas()`` or a verified
        surviving owned process fails an otherwise successful operation.
        ``require_safe_close`` is used by destructive execution workflows that
        must not proceed unless Controller close or owned-process cleanup
        positively establishes that no result writer survived.
        """
        # Normalize version (handles "7.0" → "7.0", "66" → "7.0", etc.)
        normalized_version = RasControl._normalize_version(version)

        if not project_path.exists():
            raise FileNotFoundError(f"Project file not found: {project_path}")

        com_rc = None
        result = None
        session_id = str(uuid.uuid4())
        operation_error = None

        # Take snapshot of ras.exe processes before COM launch
        before_snapshot = {}
        try:
            before_snapshot = {
                p.pid: p.info
                for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time'])
                if p.info['name'] and p.info['name'].lower() == 'ras.exe'
            }
        except Exception as e:
            logger.debug(f"Could not snapshot processes: {e}")

        try:
            # Open HEC-RAS COM interface
            com_string = RasControl.get_controller_progid(normalized_version)
            logger.debug(f"Opening HEC-RAS: {com_string} (version: {version})")
            com_rc = win32com.client.Dispatch(com_string)

            # Open project
            logger.debug(f"Opening project: {project_path.name}")
            logger.debug(f"Opening project path: {project_path}")
            com_rc.Project_Open(str(project_path))

            # Detect ras.exe PID after COM launch
            (
                ras_pid,
                ras_create_time,
                confidence,
                ras_executable_path,
                ras_executable_sha256,
            ) = _find_our_ras_process(project_path, before_snapshot)

            # Create session lock
            lock_data = SessionLock(
                python_pid=os.getpid(),
                ras_pid=ras_pid,
                project_path=str(project_path),
                ras_version=version,
                session_id=session_id,
                start_time=time.time(),
                python_exe=sys.executable,
                hostname=socket.gethostname(),
                detection_confidence=confidence,
                ras_create_time=ras_create_time,
                ras_executable_path=ras_executable_path,
                ras_executable_sha256=ras_executable_sha256,
            )

            # Track session globally
            _active_sessions[session_id] = lock_data

            # Create lock file
            _create_session_lock(session_id, lock_data)
            if session_open_callback is not None:
                session_open_callback(lock_data)

            # Perform operation
            logger.debug("Executing operation...")
            result = operation_func(com_rc)
            logger.debug("Operation completed successfully")

            return result

        except Exception as e:
            operation_error = e
            logger.error(f"Operation failed: {e}")
            raise

        finally:
            # ALWAYS close
            logger.debug("Closing HEC-RAS...")

            close_error = None
            if com_rc is not None:
                try:
                    com_rc.QuitRas()
                    logger.debug("HEC-RAS closed via QuitRas()")
                except Exception as e:
                    close_error = e
                    logger.warning(f"QuitRas() failed: {e}")
                finally:
                    # Release the pywin32 proxy deterministically. Otherwise
                    # its finalizer can contact an already-closed COM server
                    # during a later, unrelated garbage-collection cycle.
                    com_rc = None

            # Clean up session tracking (terminates only our tracked PID)
            cleanup_result = _cleanup_session(session_id)
            close_safe = (
                not cleanup_result.process_survived
                and (
                    close_error is None
                    or cleanup_result.ras_pid is not None
                )
            )
            if close_outcome_callback is not None:
                close_outcome_callback(
                    close_safe,
                    cleanup_result,
                    close_error,
                )

            # Check if our specific process is still running
            if cleanup_result.process_survived:
                logger.warning(
                    "Session cleanup failed for tracked ras.exe PID %s; "
                    "session evidence retained=%s",
                    cleanup_result.ras_pid,
                    cleanup_result.lock_retained,
                )
            else:
                logger.debug("Session cleanup completed successfully")

            if (strict_close or require_safe_close) and operation_error is None:
                strict_errors = []
                if strict_close and close_error is not None:
                    strict_errors.append(f"QuitRas() failed: {close_error}")
                if (
                    (strict_close or require_safe_close)
                    and cleanup_result.process_survived
                ):
                    strict_errors.append(
                        f"owned ras.exe PID {cleanup_result.ras_pid} survived cleanup"
                    )
                elif require_safe_close and not close_safe:
                    strict_errors.append(
                        "Controller close and owned-process exit could not be "
                        "confirmed"
                    )
                if strict_errors:
                    raise RuntimeError("; ".join(strict_errors)) from close_error

    # ========== PUBLIC API (ras-commander style) ==========

    @staticmethod
    @log_call
    def run_plan(plan: Union[str, Path], ras_object=None, force_recompute: bool = False,
                 use_watchdog: bool = True, max_runtime: int = 86400,
                 refresh_results: bool = True, *, blocking: bool = False,
                 controller_version: Optional[str] = None,
                 strict_close: bool = False) -> 'RasControlResult':
        """
        Run a plan (steady or unsteady) and wait for completion.

        This method checks if results are current before running. If results
        are up-to-date, it skips computation (unless force_recompute=True).
        When computation is needed, the default path starts it asynchronously
        and polls ``Compute_Complete()``. The opt-in blocking path delegates the
        wait to the Controller.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)
            force_recompute: If False (default), checks if results are current
                before running. If results are up-to-date, skips computation.
                If True, always runs the plan regardless of current status.
                Defaults to False.
            use_watchdog: If True, spawns independent watchdog process that will
                terminate ras.exe if Python crashes/kernel restarts. Provides
                protection against orphaned processes in Jupyter notebooks.
                Defaults to True (recommended). Set to False to disable.
            max_runtime: Maximum runtime in seconds. The nonblocking Controller
                poll loop always enforces this deadline; when ``use_watchdog``
                is enabled, the independent watchdog enforces it as well.
                Defaults to 86400 (24 hours).
            refresh_results: Refresh ``plan_df`` and ``results_df`` after the
                controller returns. Disable for compute-only validation when
                detailed legacy result extraction is unnecessary. Defaults to True.
            blocking: Pass the Controller's blocking flag to
                ``Compute_CurrentPlan`` instead of polling ``Compute_Complete``.
                This is required by exact HEC-RAS 6.3.0.2 batch execution.
                Defaults to False for backward compatibility.
            controller_version: Optional exact Controller product identity.
                Use ``"6.3.0.2"`` to select
                ``RAS630.HECRASController`` while leaving the project's
                executable family label unchanged.
            strict_close: Raise if ``QuitRas()`` fails after an otherwise
                successful operation. An owned ``ras.exe`` process surviving
                cleanup always fails plan execution, including in the default
                non-strict mode. Defaults to False for compatibility with
                recoverable ``QuitRas()`` failures.

        Returns:
            RasControlResult: Result object backward compatible with Tuple[bool, List[str]].
                ``success``: Whether execution succeeded.
                ``messages``: List of computation messages.
                ``results_df_row``: Single row from results_df (pd.Series or None).
                ``execution_details``: JSON-safe Controller identity, mode,
                watchdog, message-count, timing provenance, owned PID plus
                creation time, verified ``Ras.exe`` path and SHA-256,
                safe-close/owned-exit state, post-close plan/global process
                quiescence, result-family finalization, and exact preparation
                and finalization cleanup records. In those records,
                ``result_format`` names the family targeted for deletion.
                Calculated success requires every terminal gate.
                Existing code ``success, msgs = RasControl.run_plan("01")`` still works via __iter__.

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> # Old usage (still works):
            >>> success, msgs = RasControl.run_plan("02")
            >>> # New usage:
            >>> result = RasControl.run_plan("02")
            >>> if result:
            ...     print(result.results_df_row)
            >>> # Force recomputation even if results are current
            >>> success, msgs = RasControl.run_plan("02", force_recompute=True)
            >>> # Disable watchdog (not recommended in Jupyter)
            >>> success, msgs = RasControl.run_plan("01", use_watchdog=False)
            >>> # Long-running with extended timeout
            >>> success, msgs = RasControl.run_plan("01", max_runtime=7200)
            >>> # Exact HEC-RAS 6.3.0.2 under an outer batch supervisor
            >>> result = RasControl.run_plan(
            ...     "01", blocking=True, controller_version="6.3.0.2",
            ...     use_watchdog=False, strict_close=True,
            ...     refresh_results=False,
            ... )

        Note:
            Can take several minutes for large models or unsteady runs.
            Progress is logged every 30 seconds.
            If PlanOutput_IsCurrent() check fails (e.g., older HEC-RAS versions),
            the plan will be run as a safe fallback.

            Watchdog protection (use_watchdog=True):
            - Spawns independent Python process monitoring parent death
            - Survives kernel restarts and crashes
            - Automatically terminates orphaned ras.exe processes
            - Enforces max_runtime timeout

            When computation occurs, the selected controller version governs
            permanent, plan-scoped result cleanup. HEC-RAS 5+ preserves HDF;
            HEC-RAS 3-4 preserves legacy .O##. Skipped runs do not mutate
            execution artifacts. Before any plan mutation or cleanup, live
            Controller execution requires a complete and empty strict global
            HEC-RAS process inventory. This intentionally enforces exclusive
            host use; an incomplete or occupied inventory raises while
            preserving existing plan artifacts.
        """
        if isinstance(max_runtime, bool) or not isinstance(
            max_runtime, (int, float)
        ):
            raise ValueError("max_runtime must be a positive number of seconds")
        try:
            max_runtime_seconds = float(max_runtime)
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                "max_runtime must be a positive finite number of seconds"
            ) from exc
        if not math.isfinite(max_runtime_seconds) or max_runtime_seconds <= 0:
            raise ValueError(
                "max_runtime must be a positive finite number of seconds"
            )

        info = RasControl._get_project_info(plan, ras_object)
        _ras_obj = ras_object if ras_object is not None else ras
        if info.plan_number is None:
            raise ValueError(
                "Could not resolve the current plan number from the project. "
                "Pass an explicit plan number so result cleanup remains "
                "exactly plan-scoped."
            )

        requested_controller_version = str(controller_version or info.version)
        normalized_version = RasControl._normalize_version(requested_controller_version)
        controller_progid = RasControl.get_controller_progid(normalized_version)
        resolved_controller_version = RasControl._CONTROLLER_CANONICAL_VERSIONS[
            controller_progid
        ]
        if blocking and normalized_version.startswith(('3', '4')):
            raise ValueError(
                "blocking=True is supported only by HEC-RAS 5.x and newer Controllers"
            )

        def _set_current_plan(com_rc) -> None:
            if info.plan_name:
                logger.debug(f"Setting current plan to: {info.plan_name}")
                com_rc.Plan_SetCurrent(info.plan_name)

        def _normalize_messages(raw_messages) -> List[str]:
            if isinstance(raw_messages, str):
                return [raw_messages]
            return [
                item.decode('utf-8', errors='replace')
                if isinstance(item, bytes) else str(item)
                for item in (raw_messages or [])
            ]

        def _json_scalar(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(
                    "Controller execution detail floats must be finite"
                )
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='replace')
            return str(value)

        def _execution_details(mode: str, messages: List[str], *,
                               controller_message_count=None,
                               watchdog_pid: int = 0,
                               duration_seconds: float = 0.0,
                               **extra) -> Dict[str, Any]:
            try:
                returned_count = int(controller_message_count)
            except (TypeError, ValueError):
                returned_count = None
            details = {
                'execution_api': 'ras_control',
                'engine_kind': 'controller',
                'selected_result_format': execution_result_format,
                'calculation_attempted': calculation_attempted,
                'solver_quiescence_confirmed': (
                    solver_quiescence_confirmed
                    if calculation_attempted else None
                ),
                'result_artifacts_finalized': result_artifacts_finalized,
                'artifact_preparation_cleanup': (
                    None
                    if artifact_preparation_cleanup is None
                    else artifact_preparation_cleanup.to_dict()
                ),
                'artifact_finalization_cleanup': (
                    None
                    if artifact_finalization_cleanup is None
                    else artifact_finalization_cleanup.to_dict()
                ),
                'actual_engine_provenance_confirmed': (
                    actual_engine_provenance_confirmed
                ),
                'requested_controller_version': requested_controller_version,
                'resolved_controller_version': resolved_controller_version,
                'controller_progid': controller_progid,
                'controller_pid': controller_pid,
                'controller_create_time': controller_create_time,
                'controller_executable_path': controller_executable_path,
                'controller_executable_sha256': controller_executable_sha256,
                'controller_close_safe': controller_close_safe,
                'owned_process_exit_confirmed': owned_process_exit_confirmed,
                'post_close_plan_processes_quiescent': (
                    post_close_plan_processes_quiescent
                ),
                'post_close_global_processes_quiescent': (
                    post_close_global_processes_quiescent
                ),
                'compute_mode': mode,
                'message_count': len(messages),
                'controller_message_count': returned_count,
                'watchdog_requested': use_watchdog,
                'watchdog_started': watchdog_pid != 0,
                'strict_close_requested': bool(strict_close),
                'max_runtime_seconds': float(max_runtime_seconds),
                'duration_seconds': float(duration_seconds),
            }
            details.update({key: _json_scalar(value) for key, value in extra.items()})
            return details

        # Cleanup follows the Controller that will actually execute the plan,
        # not the plan-file declaration. This keeps explicit cross-version runs
        # deterministic and prevents stale opposing result families.
        version_major = program_version_major(resolved_controller_version)
        if version_major is None:
            raise ValueError(
                "Could not determine result format for resolved HEC-RAS "
                f"Controller {resolved_controller_version!r}"
            )
        execution_result_format = "legacy" if version_major < 5 else "hdf"
        artifact_paths = get_plan_result_artifact_paths(
            info.plan_number,
            ras_object=_ras_obj,
            project_folder=info.project_path.parent,
            project_name=info.project_path.stem,
        )
        selected_result = (
            artifact_paths.legacy_output
            if execution_result_format == "legacy"
            else artifact_paths.hdf
        )
        opposing_result = (
            artifact_paths.hdf
            if execution_result_format == "legacy"
            else artifact_paths.legacy_output
        )

        calculation_attempted = False
        solver_quiescence_confirmed = False
        result_artifacts_finalized = False
        artifact_preparation_cleanup = None
        artifact_finalization_cleanup = None
        controller_pid = None
        controller_create_time = None
        controller_executable_path = None
        controller_executable_sha256 = None
        controller_detection_confidence = 0
        controller_close_safe = False
        owned_process_exit_confirmed = False
        actual_engine_provenance_confirmed = False
        post_close_plan_processes_quiescent = None
        post_close_global_processes_quiescent = None

        if not force_recompute:
            current_check_close_safe = False

            def _record_current_check_close(
                safe: bool,
                _cleanup_result: _SessionCleanupResult,
                _close_error: Optional[BaseException],
            ) -> None:
                nonlocal current_check_close_safe
                current_check_close_safe = bool(safe)

            def _check_current(com_rc):
                _set_current_plan(com_rc)
                return bool(com_rc.PlanOutput_IsCurrent())

            try:
                close_kwargs = {"strict_close": True} if strict_close else {}
                is_current = RasControl._com_open_close(
                    info.project_path,
                    requested_controller_version,
                    _check_current,
                    require_safe_close=True,
                    close_outcome_callback=_record_current_check_close,
                    **close_kwargs,
                )
                if not current_check_close_safe:
                    raise RuntimeError(
                        "Could not confirm safe Controller close after the "
                        "plan-currency check"
                    )
                if is_current and selected_result.is_file() and not opposing_result.is_file():
                    logger.info(
                        f"Plan {info.plan_number} results are current. "
                        "Skipping computation."
                    )
                    logger.info("Use force_recompute=True to recompute anyway.")
                    from .ComputeResults import RasControlResult
                    messages = ["Results are current - computation skipped"]
                    return RasControlResult(
                        success=True,
                        messages=messages,
                        results_df_row=None,
                        execution_details=_execution_details(
                            'skipped_current', messages
                        ),
                    )
                if is_current:
                    logger.warning(
                        "HEC-RAS reports plan %s current, but its %s result "
                        "family is missing or an opposing result is also "
                        "present. Recomputing with HEC-RAS %s to normalize "
                        "the artifacts.",
                        info.plan_number,
                        execution_result_format,
                        resolved_controller_version,
                    )
            except Exception as e:
                if not current_check_close_safe:
                    raise RuntimeError(
                        "Could not confirm safe Controller close after the "
                        "plan-currency check; computation was not started"
                    ) from e
                if strict_close:
                    # The caller explicitly requested that any otherwise
                    # successful COM session fail when QuitRas() fails. Do not
                    # downgrade that close failure to the historical
                    # PlanOutput_IsCurrent fallback and start a second session.
                    raise
                logger.warning(f"Could not check PlanOutput_IsCurrent(): {e}")
                logger.warning("Proceeding with computation...")

        # This plan-file mutation belongs to execution, not inspection. Keep
        # the skip path byte-for-byte read-only.
        pre_run_inventory, pre_run_host_inventory = (
            _inspect_controller_post_close_processes(
                project_path=info.project_path,
                plan_number=info.plan_number,
            )
        )
        if not pre_run_inventory.complete:
            raise RuntimeError(
                "Exact-plan process inventory was incomplete before Controller "
                "execution; result artifacts were preserved"
            )
        if pre_run_inventory.matched:
            raise RuntimeError(
                "An exact-plan HEC-RAS process was already active before "
                "Controller execution; result artifacts were preserved"
            )
        host_query_errors = getattr(
            pre_run_host_inventory, 'query_errors', None
        )
        host_processes = getattr(pre_run_host_inventory, 'processes', None)
        if (
            pre_run_host_inventory.complete is not True
            or not isinstance(host_query_errors, (list, tuple))
            or bool(host_query_errors)
            or not isinstance(host_processes, (list, tuple))
        ):
            raise RuntimeError(
                "Strict global HEC-RAS process inventory was incomplete before "
                "Controller execution; result artifacts were preserved"
            )
        if host_processes:
            raise RuntimeError(
                "A HEC-RAS process was already active on this host before "
                "Controller execution; exclusive-host execution is required "
                "and result artifacts were preserved"
            )

        from .RasBco import BcoMonitor
        plan_file = info.project_path.parent / f"{info.project_path.stem}.p{info.plan_number}"
        BcoMonitor.enable_detailed_logging(plan_file)
        logger.debug(f"Enabled Write Detailed= 1 for plan {info.plan_number}")

        def _record_close_outcome(
            safe: bool,
            cleanup_result: _SessionCleanupResult,
            _close_error: Optional[BaseException],
        ) -> None:
            nonlocal controller_close_safe, owned_process_exit_confirmed
            controller_close_safe = bool(safe)
            owned_process_exit_confirmed = bool(
                controller_pid is not None
                and controller_create_time is not None
                and cleanup_result.ras_pid == controller_pid
                and not cleanup_result.process_survived
            )

        def _record_controller_session(lock: SessionLock) -> None:
            nonlocal controller_pid
            nonlocal controller_create_time
            nonlocal controller_executable_path
            nonlocal controller_executable_sha256
            nonlocal controller_detection_confidence
            nonlocal actual_engine_provenance_confirmed
            controller_pid = lock.ras_pid
            controller_create_time = lock.ras_create_time
            controller_executable_path = lock.ras_executable_path
            controller_executable_sha256 = lock.ras_executable_sha256
            controller_detection_confidence = int(lock.detection_confidence)
            actual_engine_provenance_confirmed = bool(
                controller_pid is not None
                and controller_create_time is not None
                and controller_executable_path is not None
                and controller_executable_sha256 is not None
                and controller_detection_confidence >= 50
                and RasControl.get_controller_progid(
                    requested_controller_version
                ) == controller_progid
                and RasControl._CONTROLLER_CANONICAL_VERSIONS.get(
                    controller_progid
                ) == resolved_controller_version
            )

        def _run_operation(com_rc):
            nonlocal calculation_attempted, solver_quiescence_confirmed
            nonlocal artifact_preparation_cleanup
            watchdog_pid = 0
            watchdog_identity = None
            current_session = None

            # Set current plan if we have plan_name (using plan number)
            _set_current_plan(com_rc)
            # Spawn watchdog if requested
            if use_watchdog:
                # Find our session to get ras_pid and lock file
                for session in _active_sessions.values():
                    if session.project_path == str(info.project_path):
                        current_session = session
                        break

                if (
                    current_session
                    and current_session.ras_pid
                    and current_session.ras_create_time is not None
                    ):
                    lock_file = _get_lock_file_path(current_session.session_id)
                    watchdog_identity = _spawn_watchdog(
                        parent_pid=os.getpid(),
                        ras_pid=current_session.ras_pid,
                        ras_create_time=current_session.ras_create_time,
                        max_runtime=max_runtime_seconds,
                        lock_file_path=str(lock_file)
                    )
                    if watchdog_identity is not None:
                        watchdog_pid = watchdog_identity.pid
                        current_session.watchdog_pid = watchdog_identity.pid
                        current_session.watchdog_create_time = (
                            watchdog_identity.create_time
                        )
                        current_session.watchdog_name = watchdog_identity.name
                        if not watchdog_identity.complete:
                            current_session.identity_unverified = True
                            current_session.validation_error = (
                                "watchdog PID was launched but its exact "
                                "create-time/name identity is unverified"
                            )
                        if isinstance(current_session, SessionLock):
                            _create_session_lock(
                                current_session.session_id, current_session
                            )
                        if not watchdog_identity.complete:
                            raise RuntimeError(
                                "Watchdog process identity could not be proved; "
                                "session evidence was retained and computation "
                                "was not started"
                            )
                else:
                    logger.warning("Could not spawn watchdog - ras.exe PID not detected")

            try:
                compute_started = time.monotonic()
                logger.info(
                    "Starting %s Controller computation...",
                    "blocking" if blocking else "asynchronous",
                )

                # Couple cleanup to the actual compute attempt so Controller
                # activation, project-open, and watchdog setup failures leave
                # existing final results untouched.
                artifact_preparation_cleanup = prepare_plan_execution_artifacts(
                    info.plan_number,
                    output_format=execution_result_format,
                    ras_object=_ras_obj,
                    project_folder=info.project_path.parent,
                    project_name=info.project_path.stem,
                )
                calculation_attempted = True

                if blocking:
                    raw_compute = com_rc.Compute_CurrentPlan(None, None, True)
                    if not isinstance(raw_compute, (tuple, list)) or len(raw_compute) < 3:
                        raise RuntimeError(
                            "Blocking Compute_CurrentPlan returned an unsupported result"
                        )
                    # A valid blocking Controller return arrives only after the
                    # calculation has stopped writing its result artifacts.
                    solver_quiescence_confirmed = True
                    status = raw_compute[0]
                    controller_message_count = raw_compute[1]
                    messages = _normalize_messages(raw_compute[2])
                    blocking_result = raw_compute[3] if len(raw_compute) > 3 else None
                    return status, messages, _execution_details(
                        'blocking',
                        messages,
                        controller_message_count=controller_message_count,
                        watchdog_pid=watchdog_pid,
                        duration_seconds=time.monotonic() - compute_started,
                        blocking_result=blocking_result,
                    )

                if normalized_version.startswith(('3', '4')):
                    status, controller_message_count, raw_messages = (
                        com_rc.Compute_CurrentPlan(None, None)
                    )
                else:
                    status, controller_message_count, raw_messages, _ = (
                        com_rc.Compute_CurrentPlan(None, None)
                    )
                messages = _normalize_messages(raw_messages)

                # CRITICAL: Wait for computation to complete
                # Compute_CurrentPlan is ASYNCHRONOUS - it returns before computation finishes
                logger.info("Waiting for computation to complete...")
                poll_count = 0
                completion_deadline = compute_started + max_runtime_seconds
                while True:
                    try:
                        remaining = completion_deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                "HEC-RAS computation exceeded max_runtime="
                                f"{max_runtime} seconds; solver quiescence "
                                "was not confirmed and opposing result "
                                "artifacts were preserved"
                            )

                        # Check if computation is complete
                        is_complete = com_rc.Compute_Complete()

                        # A Controller call can itself block. Do not credit a
                        # late completion after the monotonic deadline.
                        remaining = completion_deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                "HEC-RAS computation exceeded max_runtime="
                                f"{max_runtime} seconds; solver quiescence "
                                "was not confirmed and opposing result "
                                "artifacts were preserved"
                            )

                        if is_complete:
                            logger.info(f"Computation completed (polled {poll_count} times)")
                            solver_quiescence_confirmed = True
                            break

                        # Still computing - wait and poll again
                        time.sleep(min(1.0, remaining))
                        poll_count += 1

                        # Log progress every 30 seconds
                        if poll_count % 30 == 0:
                            logger.info(
                                "Still computing... %s seconds elapsed; timeout=%s seconds",
                                poll_count,
                                max_runtime,
                            )

                    except TimeoutError:
                        raise
                    except Exception as e:
                        logger.error(f"Error checking completion status: {e}")
                        raise RuntimeError(
                            "Could not confirm HEC-RAS solver quiescence; "
                            "opposing result artifacts were preserved"
                        ) from e

                return status, messages, _execution_details(
                    'poll',
                    messages,
                    controller_message_count=controller_message_count,
                    watchdog_pid=watchdog_pid,
                    duration_seconds=time.monotonic() - compute_started,
                    poll_count=poll_count,
                )

            finally:
                # Always terminate watchdog on completion (even if error)
                if watchdog_identity is not None:
                    watchdog_cleanup = _terminate_watchdog(watchdog_identity)
                    if not watchdog_cleanup.safe:
                        if current_session is not None:
                            current_session.identity_unverified = True
                            current_session.validation_error = (
                                "watchdog cleanup identity is unverified: "
                                f"{watchdog_cleanup.identity_state}; "
                                f"{watchdog_cleanup.error or 'no detail'}"
                            )
                            if isinstance(current_session, SessionLock):
                                _create_session_lock(
                                    current_session.session_id,
                                    current_session,
                                )
                        raise RuntimeError(
                            "Watchdog cleanup could not prove exact process exit; "
                            "session evidence was retained"
                        )

        try:
            close_kwargs = {"strict_close": True} if strict_close else {}
            raw_result = RasControl._com_open_close(
                info.project_path,
                requested_controller_version,
                _run_operation,
                require_safe_close=True,
                close_outcome_callback=_record_close_outcome,
                session_open_callback=_record_controller_session,
                **close_kwargs,
            )
            (
                post_close_plan_inventory,
                post_close_global_inventory,
            ) = _inspect_controller_post_close_processes(
                project_path=info.project_path,
                plan_number=info.plan_number,
            )
            post_close_plan_processes_quiescent = bool(
                post_close_plan_inventory.complete
                and not post_close_plan_inventory.matched
            )
            post_close_global_processes_quiescent = bool(
                post_close_global_inventory.complete
                and not post_close_global_inventory.processes
            )
            if (
                not post_close_plan_inventory.complete
                or not post_close_global_inventory.complete
            ):
                solver_quiescence_confirmed = False
                raise RuntimeError(
                    "Controller post-close HEC-RAS process inventory was "
                    "incomplete; opposing result artifacts were preserved"
                )
            if (
                post_close_plan_inventory.matched
                or post_close_global_inventory.processes
            ):
                solver_quiescence_confirmed = False
                raise RuntimeError(
                    "A HEC-RAS compute process remained after Controller "
                    "close; opposing result artifacts were preserved"
                )
            if not all(
                (
                    solver_quiescence_confirmed,
                    controller_close_safe,
                    owned_process_exit_confirmed,
                    actual_engine_provenance_confirmed,
                    post_close_plan_processes_quiescent,
                    post_close_global_processes_quiescent,
                )
            ):
                raise RuntimeError(
                    "Plan execution did not establish exact Controller "
                    "provenance, solver quiescence, safe close, and owned "
                    "process exit"
                )
        finally:
            # HEC-RAS 5+ can recreate .O## during 1D computation, so enforce
            # the selected engine's output family after the controller closes.
            if (
                calculation_attempted
                and solver_quiescence_confirmed
                and controller_close_safe
                and owned_process_exit_confirmed
                and actual_engine_provenance_confirmed
                and post_close_plan_processes_quiescent
                and post_close_global_processes_quiescent
            ):
                artifact_finalization_cleanup = finalize_plan_execution_artifacts(
                    info.plan_number,
                    output_format=execution_result_format,
                    ras_object=_ras_obj,
                    project_folder=info.project_path.parent,
                    project_name=info.project_path.stem,
                )
                result_artifacts_finalized = True
            elif calculation_attempted:
                logger.warning(
                    "Preserving opposing result artifacts for plan %s because "
                    "solver quiescence or safe Controller close was not confirmed",
                    info.plan_number,
                )

        # Wrap tuple result into RasControlResult with results_df_row
        from .ComputeResults import RasControlResult
        _success = bool(raw_result[0]) if raw_result else False
        _messages = list(raw_result[1]) if raw_result and len(raw_result) > 1 else []
        _details = raw_result[2] if raw_result and len(raw_result) > 2 else {}
        _details.update(
            {
                'execution_api': 'ras_control',
                'engine_kind': 'controller',
                'selected_result_format': execution_result_format,
                'calculation_attempted': calculation_attempted,
                'solver_quiescence_confirmed': (
                    bool(solver_quiescence_confirmed)
                    if calculation_attempted else None
                ),
                'result_artifacts_finalized': result_artifacts_finalized,
                'artifact_preparation_cleanup': (
                    None
                    if artifact_preparation_cleanup is None
                    else artifact_preparation_cleanup.to_dict()
                ),
                'artifact_finalization_cleanup': (
                    None
                    if artifact_finalization_cleanup is None
                    else artifact_finalization_cleanup.to_dict()
                ),
                'actual_engine_provenance_confirmed': (
                    actual_engine_provenance_confirmed
                ),
                'controller_pid': controller_pid,
                'controller_create_time': controller_create_time,
                'controller_executable_path': controller_executable_path,
                'controller_executable_sha256': controller_executable_sha256,
                'controller_close_safe': controller_close_safe,
                'owned_process_exit_confirmed': owned_process_exit_confirmed,
                'post_close_plan_processes_quiescent': (
                    post_close_plan_processes_quiescent
                ),
                'post_close_global_processes_quiescent': (
                    post_close_global_processes_quiescent
                ),
                'strict_close_requested': bool(strict_close),
                'max_runtime_seconds': float(max_runtime_seconds),
            }
        )
        if _success and not all(
            (
                _details['calculation_attempted'] is True,
                _details['solver_quiescence_confirmed'] is True,
                _details['result_artifacts_finalized'] is True,
                _details['actual_engine_provenance_confirmed'] is True,
                _details['controller_close_safe'] is True,
                _details['owned_process_exit_confirmed'] is True,
                _details['post_close_plan_processes_quiescent'] is True,
                _details['post_close_global_processes_quiescent'] is True,
            )
        ):
            _success = False
        _results_df_row = None

        # Refresh DataFrames and capture results_df row (even on failure for diagnostics)
        if (
            refresh_results
            and execution_result_format == "hdf"
            and info.plan_number
            and hasattr(_ras_obj, 'update_results_df')
        ):
            try:
                _ras_obj.plan_df = _ras_obj.get_plan_entries()
                _ras_obj.update_results_df(plan_numbers=[info.plan_number])
                mask = _ras_obj.results_df['plan_number'] == info.plan_number
                if mask.any():
                    _results_df_row = _ras_obj.results_df[mask].iloc[0].copy()
            except Exception as e:
                logger.debug(f"Could not extract results_df_row: {e}")

        return RasControlResult(
            success=_success,
            messages=_messages,
            results_df_row=_results_df_row,
            execution_details=_details,
        )

    @staticmethod
    def _parse_ras_datetime(time_string: str) -> pd.Timestamp:
        """
        Parse HEC-RAS COM datetime string to pandas Timestamp.

        Args:
            time_string: RAS format (e.g., "18FEB1999 0000" or "01JAN2000 0000")

        Returns:
            pandas Timestamp, or pd.NaT if string is "Max WS" or parsing fails

        Note:
            This is a private helper method for converting RAS datetime strings
            from the COM interface into proper datetime64[ns] objects. The "Max WS"
            special value is converted to pd.NaT to allow clean filtering.

            Special handling for "2400" hours: HEC-RAS uses 2400 to represent
            midnight at the end of a day (equivalent to 0000 of the next day).
        """
        time_str = time_string.strip()

        # Special case: Max WS row contains computational maximums, not a timestamp
        if time_str == 'Max WS':
            return pd.NaT

        # Special case: 2400 hours (midnight at end of day)
        # HEC-RAS uses 2400 to mean 24:00 (midnight at end of day)
        # Convert to 0000 of next day
        if ' 2400' in time_str:
            # Replace 2400 with 0000 and parse, then add 1 day
            temp_str = time_str.replace(' 2400', ' 0000')
            try:
                dt = pd.to_datetime(temp_str, format='%d%b%Y %H%M')
                # Add 1 day to get correct midnight
                return dt + pd.Timedelta(days=1)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse RAS datetime with 2400: '{time_str}'")
                return pd.NaT

        try:
            # Primary format: "01JAN2000 0000" (%d%b%Y %H%M)
            return pd.to_datetime(time_str, format='%d%b%Y %H%M')
        except (ValueError, TypeError):
            try:
                # Alternate format with seconds: "01JAN2000 0000:00"
                return pd.to_datetime(time_str, format='%d%b%Y %H%M:%S')
            except (ValueError, TypeError):
                logger.warning(f"Could not parse RAS datetime: '{time_str}'")
                return pd.NaT

    @staticmethod
    @log_call
    def get_steady_results(plan: Union[str, Path], ras_object=None) -> pd.DataFrame:
        """
        Extract steady state profile results from HEC-RAS via COM interface.

        Opens HEC-RAS, loads the specified plan, extracts water surface elevations
        and hydraulic parameters for all profiles at all cross sections, then closes
        HEC-RAS.

        Parameters
        ----------
        plan : str or Path
            Plan number (e.g., "01", "02") or full path to .prj file
        ras_object : RasPrj, optional
            RAS project object. If None, uses global `ras` object.

        Returns
        -------
        pd.DataFrame
            Steady state results with one row per cross-section per profile

            **Schema:**

            +----------------+----------+---------------------------------------+
            | Column         | Type     | Description                           |
            +================+==========+=======================================+
            | river          | str      | River name                            |
            +----------------+----------+---------------------------------------+
            | reach          | str      | Reach name                            |
            +----------------+----------+---------------------------------------+
            | node_id        | str      | Cross section river station           |
            +----------------+----------+---------------------------------------+
            | profile        | str      | Profile name (e.g., "PF 1", "50Pct")  |
            +----------------+----------+---------------------------------------+
            | wsel           | float    | Water surface elevation (ft or m)     |
            +----------------+----------+---------------------------------------+
            | velocity       | float    | Total velocity (ft/s or m/s)          |
            +----------------+----------+---------------------------------------+
            | flow           | float    | Total flow (cfs or cms)               |
            +----------------+----------+---------------------------------------+
            | froude         | float    | Channel Froude number (dimensionless) |
            +----------------+----------+---------------------------------------+
            | energy         | float    | Energy grade elevation (ft or m)      |
            +----------------+----------+---------------------------------------+
            | max_depth      | float    | Maximum channel depth (ft or m)       |
            +----------------+----------+---------------------------------------+
            | min_ch_el      | float    | Minimum channel elevation (ft or m)   |
            +----------------+----------+---------------------------------------+

            **Note on data types:**

            - String columns (`river`, `reach`, `node_id`, `profile`) are decoded
              from COM byte strings and stripped of whitespace
            - Numeric columns are float64
            - Units depend on project settings (US customary or SI)

        Raises
        ------
        ValueError
            - If project not initialized with version
            - If plan number not found in project
        RuntimeError
            - If no steady state results found
            - If model run was not successful

        Notes
        -----
        **Comparison with HDF Methods:**

        This COM-based method returns MORE data than the HDF-based
        `HdfResultsPlan.get_steady_wse()`, which only returns WSE.
        RasControl includes velocity, flow, Froude, energy, and depths.

        **Performance Notes:**

        - HEC-RAS is opened and closed for each call (not persistent)
        - For HEC-RAS 6.0+, HDF methods may offer better performance
        - COM interface is single-threaded

        Examples
        --------
        Extract steady results for Plan 02:

        >>> from ras_commander import init_ras_project, RasControl
        >>> init_ras_project(path, "4.1")
        >>> df = RasControl.get_steady_results("02")
        >>> df.to_csv('steady_results.csv', index=False)

        Plot water surface profile:

        >>> import matplotlib.pyplot as plt
        >>> profile_data = df[df['profile'] == 'PF 1']
        >>> plt.plot(profile_data['node_id'].astype(float),
        ...          profile_data['wsel'])
        >>> plt.xlabel('Station')
        >>> plt.ylabel('Water Surface Elevation (ft)')
        >>> plt.show()

        See Also
        --------
        get_unsteady_results : Extract unsteady time series
        run_plan : Run a plan before extracting results
        HdfResultsPlan.get_steady_wse : Modern HDF-based steady extraction

        References
        ----------
        For comparison with HDF-based methods, see:
        ``feature_dev_notes/rascontrol_vs_hdf_comparison.md``
        """
        info = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if info.plan_name:
                logger.debug(f"Setting current plan to: {info.plan_name}")
                com_rc.Plan_SetCurrent(info.plan_name)

            results = []
            error_logged = False  # Track if we've already logged comp_msgs

            # Get profiles
            _, profile_names = com_rc.Output_GetProfiles(2, None)

            if profile_names is None:
                raise RuntimeError(
                    "No steady state results found. Please ensure:\n"
                    "  1. The model has been run (use RasControl.run_plan() first)\n"
                    "  2. The current plan is a steady state plan\n"
                    "  3. Results were successfully computed"
                )

            profiles = [{'name': name, 'code': i+1} for i, name in enumerate(profile_names)]
            logger.debug(f"Found {len(profiles)} profiles")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.debug(f"Found {len(river_names)} rivers")

            # Extract data
            for riv_code, riv_name in enumerate(river_names, start=1):
                _, _, reach_names = com_rc.Geometry_GetReaches(riv_code, None, None)

                for rch_code, rch_name in enumerate(reach_names, start=1):
                    _, _, _, node_ids, node_types = com_rc.Geometry_GetNodes(
                        riv_code, rch_code, None, None, None
                    )

                    for node_code, (node_id, node_type) in enumerate(
                        zip(node_ids, node_types), start=1
                    ):
                        if node_type == '':  # Cross sections only
                            for profile in profiles:
                                try:
                                    row = {
                                        'river': riv_name.strip(),
                                        'reach': rch_name.strip(),
                                        'node_id': node_id.strip(),
                                        'profile': profile['name'].strip(),
                                    }

                                    # Extract output variables
                                    row['wsel'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.WSEL
                                    )[0]

                                    row['min_ch_el'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.MIN_CH_EL
                                    )[0]

                                    row['velocity'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.VEL_TOTAL
                                    )[0]

                                    row['flow'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.FLOW_TOTAL
                                    )[0]

                                    row['froude'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.FROUDE_CHL
                                    )[0]

                                    row['energy'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.ENERGY
                                    )[0]

                                    row['max_depth'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.MAX_CHL_DPTH
                                    )[0]

                                    results.append(row)

                                except Exception as e:
                                    if not error_logged:
                                        # First error - read and log comp_msgs to diagnose issue
                                        logger.error(
                                            f"Failed to extract results at {riv_name}/{rch_name}/{node_id} "
                                            f"profile {profile['name']}: {e}"
                                        )
                                        logger.error(
                                            "This usually indicates the model run was not successful or "
                                            "results are invalid. Reading computation messages..."
                                        )

                                        # Read comp_msgs file
                                        try:
                                            project_base = info.project_path.stem
                                            plan_file = info.project_path.parent / f"{project_base}.p{info.plan_number}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                _log_failed_extraction_comp_msgs(comp_msgs_file, comp_msgs)
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.debug("Suppressing further extraction warnings")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.debug(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(info.project_path, info.version, _extract_operation)

    @staticmethod
    @log_call
    def get_unsteady_results(plan: Union[str, Path], max_times: Optional[int] = None,
                            ras_object=None) -> pd.DataFrame:
        """
        Extract unsteady flow time series results from HEC-RAS via COM interface.

        Opens HEC-RAS, loads the specified plan, extracts all computed time series
        data including the critical "Max WS" row, then closes HEC-RAS.

        Parameters
        ----------
        plan : str or Path
            Plan number (e.g., "01", "02") or full path to .prj file.
        max_times : int, optional
            Maximum number of timesteps to extract. If None, extracts all timesteps.
            Note: "Max WS" row is always included and doesn't count toward this limit.
        ras_object : RasPrj, optional
            RAS project object. If None, uses global `ras` object.

        Returns
        -------
        pd.DataFrame
            Unsteady flow time series with one row per cross-section per timestep,
            plus one "Max WS" row per cross-section containing computational maximums.

            **Schema:**

            +-----------------+----------------+-------------------------------------------+
            | Column          | Type           | Description                               |
            +=================+================+===========================================+
            | river           | str            | River name                                |
            +-----------------+----------------+-------------------------------------------+
            | reach           | str            | Reach name                                |
            +-----------------+----------------+-------------------------------------------+
            | node_id         | str            | Cross section river station               |
            +-----------------+----------------+-------------------------------------------+
            | time_index      | int            | 1-based timestep index                    |
            |                 |                | 1 = "Max WS", 2+ = actual timesteps       |
            +-----------------+----------------+-------------------------------------------+
            | time_string     | str            | RAS datetime format "01JAN2000 0000"      |
            |                 |                | or "Max WS" for maximum value row         |
            +-----------------+----------------+-------------------------------------------+
            | datetime        | datetime64[ns] | Parsed timestamp                          |
            |                 |                | pd.NaT for "Max WS" rows                  |
            +-----------------+----------------+-------------------------------------------+
            | wsel            | float          | Water surface elevation (ft or m)         |
            +-----------------+----------------+-------------------------------------------+
            | velocity        | float          | Total velocity (ft/s or m/s)              |
            +-----------------+----------------+-------------------------------------------+
            | flow            | float          | Total flow (cfs or cms)                   |
            +-----------------+----------------+-------------------------------------------+
            | froude          | float          | Channel Froude number (dimensionless)     |
            +-----------------+----------------+-------------------------------------------+
            | energy          | float          | Energy grade elevation (ft or m)          |
            +-----------------+----------------+-------------------------------------------+
            | max_depth       | float          | Maximum channel depth (ft or m)           |
            +-----------------+----------------+-------------------------------------------+
            | min_ch_el       | float          | Minimum channel elevation (ft or m)       |
            +-----------------+----------------+-------------------------------------------+

            **Units depend on project settings (US Customary or SI).**

        Raises
        ------
        ValueError
            - If project not initialized with version
            - If plan not found in project
        RuntimeError
            - If no unsteady results found
            - If HEC-RAS computation was not successful

        Notes
        -----
        **Understanding "Max WS" Rows:**

        The "Max WS" row (time_index=1, time_string="Max WS") contains the maximum
        value at ANY computational timestep, not just the output intervals. This is
        critical for design applications because:

        - HEC-RAS computes at finer intervals than it outputs
        - Peak values often occur between output timesteps
        - "Max WS" captures the true computational maximum

        To separate "Max WS" from time series data:

        >>> df_max = df[df['time_string'] == 'Max WS']
        >>> df_timeseries = df[df['datetime'].notna()]  # Excludes Max WS (has NaT)

        **New in v0.81.0:**

        The `datetime` column is now included automatically as datetime64[ns] objects.
        Users no longer need to manually parse `time_string`. For backward compatibility,
        `time_string` is still included.

        **Performance Notes:**

        - HEC-RAS is opened and closed for each call (not persistent)
        - For large time series, consider using HDF-based methods for better performance
        - COM interface is single-threaded

        Examples
        --------
        Extract and plot time series at a cross section:

        >>> from ras_commander import init_ras_project, RasControl
        >>> import matplotlib.pyplot as plt
        >>>
        >>> init_ras_project(path, "4.1")
        >>> df = RasControl.get_unsteady_results("01")
        >>>
        >>> # Separate max WS from time series
        >>> df_max = df[df['time_string'] == 'Max WS']
        >>> df_ts = df[df['datetime'].notna()]
        >>>
        >>> # Plot time series for specific cross section
        >>> xs_data = df_ts[df_ts['node_id'] == '10000'].sort_values('datetime')
        >>> plt.plot(xs_data['datetime'], xs_data['wsel'])
        >>> plt.axhline(df_max[df_max['node_id'] == '10000']['wsel'].iloc[0],
        ...             color='r', linestyle='--', label='Max WS')
        >>> plt.xlabel('Date/Time')
        >>> plt.ylabel('WSE (ft)')
        >>> plt.legend()
        >>> plt.show()

        Filter to specific time range using datetime column:

        >>> import pandas as pd
        >>> start = pd.Timestamp('1999-02-18')
        >>> end = pd.Timestamp('1999-02-20')
        >>> filtered = df_ts[(df_ts['datetime'] >= start) & (df_ts['datetime'] <= end)]

        See Also
        --------
        get_steady_results : Extract steady state profile results
        get_output_times : List available timesteps before extracting
        run_plan : Run a plan before extracting results
        HdfResultsXsec.get_xsec_timeseries : Modern HDF-based extraction (returns xarray)

        References
        ----------
        For comparison with HDF-based methods, see:
        ``feature_dev_notes/rascontrol_vs_hdf_comparison.md``
        """
        info = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if info.plan_name:
                logger.debug(f"Setting current plan to: {info.plan_name}")
                com_rc.Plan_SetCurrent(info.plan_name)

            results = []
            error_logged = False  # Track if we've already logged comp_msgs

            # Get output times
            _, time_strings = com_rc.Output_GetProfiles(0, None)

            if time_strings is None:
                raise RuntimeError(
                    "No unsteady results found. Please ensure:\n"
                    "  1. The model has been run (use RasControl.run_plan() first)\n"
                    "  2. The current plan is an unsteady flow plan\n"
                    "  3. Results were successfully computed"
                )

            times = list(time_strings)
            if max_times:
                times = times[:max_times]

            logger.debug(f"Extracting {len(times)} time steps")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.debug(f"Found {len(river_names)} rivers")

            # Extract data
            for riv_code, riv_name in enumerate(river_names, start=1):
                _, _, reach_names = com_rc.Geometry_GetReaches(riv_code, None, None)

                for rch_code, rch_name in enumerate(reach_names, start=1):
                    _, _, _, node_ids, node_types = com_rc.Geometry_GetNodes(
                        riv_code, rch_code, None, None, None
                    )

                    for node_code, (node_id, node_type) in enumerate(
                        zip(node_ids, node_types), start=1
                    ):
                        if node_type == '':  # Cross sections only
                            for time_idx, time_str in enumerate(times, start=1):
                                try:
                                    row = {
                                        'river': riv_name.strip(),
                                        'reach': rch_name.strip(),
                                        'node_id': node_id.strip(),
                                        'time_index': time_idx,
                                        'time_string': time_str.strip(),
                                        'datetime': RasControl._parse_ras_datetime(time_str),
                                    }

                                    # Extract output variables (time_idx is profile code for unsteady)
                                    row['wsel'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.WSEL
                                    )[0]

                                    row['min_ch_el'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.MIN_CH_EL
                                    )[0]

                                    row['velocity'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.VEL_TOTAL
                                    )[0]

                                    row['flow'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.FLOW_TOTAL
                                    )[0]

                                    row['froude'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.FROUDE_CHL
                                    )[0]

                                    row['energy'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.ENERGY
                                    )[0]

                                    row['max_depth'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.MAX_CHL_DPTH
                                    )[0]

                                    results.append(row)

                                except Exception as e:
                                    if not error_logged:
                                        # First error - read and log comp_msgs to diagnose issue
                                        logger.error(
                                            f"Failed to extract results at {riv_name}/{rch_name}/{node_id} "
                                            f"time {time_str}: {e}"
                                        )
                                        logger.error(
                                            "This usually indicates the model run was not successful or "
                                            "results are invalid. Reading computation messages..."
                                        )

                                        # Read comp_msgs file
                                        try:
                                            project_base = info.project_path.stem
                                            plan_file = info.project_path.parent / f"{project_base}.p{info.plan_number}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                _log_failed_extraction_comp_msgs(comp_msgs_file, comp_msgs)
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.debug("Suppressing further extraction warnings")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.debug(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(info.project_path, info.version, _extract_operation)

    @staticmethod
    @log_call
    def get_output_times(plan: Union[str, Path], ras_object=None) -> List[str]:
        """
        Get list of output times for unsteady run.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            List of time strings (e.g., ["01JAN2000 0000", ...])

        Example:
            >>> times = RasControl.get_output_times("01")
            >>> print(f"Found {len(times)} output times")
        """
        info = RasControl._get_project_info(plan, ras_object)

        def _get_times(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if info.plan_name:
                logger.debug(f"Setting current plan to: {info.plan_name}")
                com_rc.Plan_SetCurrent(info.plan_name)

            _, time_strings = com_rc.Output_GetProfiles(0, None)

            if time_strings is None:
                raise RuntimeError(
                    "No unsteady output times found. Ensure plan has been run."
                )

            times = list(time_strings)
            logger.debug(f"Found {len(times)} output times")
            return times

        return RasControl._com_open_close(info.project_path, info.version, _get_times)

    @staticmethod
    @log_call
    def get_plans(plan: Union[str, Path], ras_object=None) -> List[dict]:
        """
        Get list of plans in project.

        Args:
            plan: Plan number or path to .prj file
            ras_object: Optional RasPrj instance

        Returns:
            List of dicts with 'name' and 'filename' keys
        """
        info = RasControl._get_project_info(plan, ras_object)

        def _get_plans(com_rc):
            # Don't set current plan - just getting list
            _, plan_names, _ = com_rc.Plan_Names(None, None, None)

            plans = []
            for name in plan_names:
                filename, _ = com_rc.Plan_GetFilename(name)
                plans.append({'name': name, 'filename': filename})

            logger.debug(f"Found {len(plans)} plans")
            return plans

        return RasControl._com_open_close(info.project_path, info.version, _get_plans)

    @staticmethod
    @log_call
    def set_current_plan(plan: Union[str, Path], ras_object=None) -> bool:
        """
        Set the current/active plan by plan number.

        Note: This is rarely needed - run_plan() and get_*_results()
        automatically set the correct plan. This is provided for
        advanced use cases.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance

        Returns:
            True if successful

        Example:
            >>> RasControl.set_current_plan("02")  # Set to Plan 02
        """
        info = RasControl._get_project_info(plan, ras_object)

        if not info.plan_name:
            raise ValueError("Cannot set current plan - plan name could not be determined")

        def _set_plan(com_rc):
            com_rc.Plan_SetCurrent(info.plan_name)
            logger.info(f"Set current plan to Plan {info.plan_number}: {info.plan_name}")
            return True

        return RasControl._com_open_close(info.project_path, info.version, _set_plan)

    @staticmethod
    def _read_stored_comp_msgs(
        plan: Union[str, Path],
        ras_object=None,
        *,
        strict: bool = True,
        hash_file: bool = False,
    ) -> Tuple[_StoredCompMessageCandidate, ...]:
        """Inspect every stored compute-message sidecar in fixed precedence.

        This helper never opens COM and never falls back to HDF.  Keeping the
        source path, optional digest, and per-candidate error lets evidence
        callers surface multiplicity without silently treating the first file
        as the only sidecar.  The returned order preserves the historical
        selection precedence: ``.comp_msgs.txt``, ``.computeMsgs.txt``, then
        ``.bco##``.
        """
        info = RasControl._get_project_info(plan, ras_object)
        project_base = info.project_path.stem
        plan_file = info.project_path.parent / (
            f"{project_base}.p{info.plan_number}"
        )
        candidates = (
            Path(f"{plan_file}.comp_msgs.txt"),
            Path(f"{plan_file}.computeMsgs.txt"),
            info.project_path.parent
            / f"{project_base}.bco{info.plan_number}",
        )

        inspected = []
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                before = candidate.stat()
                raw = candidate.read_bytes()
                after = candidate.stat()
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise RuntimeError(
                        "Stored computation messages changed while reading: "
                        f"{candidate}"
                    )
                if raw.startswith(b"\xef\xbb\xbf"):
                    contents = raw.decode(
                        "utf-8-sig",
                        errors="strict" if strict else "ignore",
                    )
                elif not strict:
                    contents = raw.decode("utf-8", errors="ignore")
                else:
                    try:
                        contents = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        contents = raw.decode("cp1252")
                source_sha256 = (
                    hashlib.sha256(raw).hexdigest() if hash_file else None
                )
                inspected.append(
                    _StoredCompMessageCandidate(
                        path=candidate,
                        contents=contents,
                        source_sha256=source_sha256,
                    )
                )
            except Exception as exc:
                inspected.append(
                    _StoredCompMessageCandidate(
                        path=candidate,
                        contents=None,
                        source_sha256=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return tuple(inspected)

    @staticmethod
    @log_call
    def get_comp_msgs(plan: Union[str, Path], ras_object=None) -> str:
        """
        Read computation messages from .txt file with fallback to HDF.

        The comp_msgs file is created by HEC-RAS during plan computation
        and contains detailed messages about the computation process,
        including warnings, errors, and convergence information.

        This method checks multiple naming patterns (version-dependent):
        - .comp_msgs.txt (HEC-RAS 3.x-5.x COM interface)
        - .computeMsgs.txt (HEC-RAS 6.x+)
        - .bco## (HEC-RAS 5.x detailed compute output)

        If no text file exists, falls back to HDF extraction.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            String containing computation messages, or empty string if unavailable

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> msgs = RasControl.get_comp_msgs("08")
            >>> print(msgs)

        Note:
            File naming conventions vary by HEC-RAS version:
            - COM interface: {plan_file}.comp_msgs.txt
            - HEC-RAS 6.x+: {plan_file}.computeMsgs.txt
            - HEC-RAS 5.x: {project_name}.bco{plan_number}
            If several filesystem sidecars exist, all are inspected and the
            first is returned in the fixed order listed above. A warning
            identifies the additional candidates.
            Falls back to HDF: /Results/Summary/Compute Messages (text)
        """
        info = RasControl._get_project_info(plan, ras_object)
        project_base = info.project_path.stem
        plan_file = (
            info.project_path.parent
            / f"{project_base}.p{info.plan_number}"
        )

        try:
            stored_candidates = RasControl._read_stored_comp_msgs(
                plan,
                ras_object,
                strict=False,
            )
            if stored_candidates:
                selected = stored_candidates[0]
                if selected.error is not None or selected.contents is None:
                    raise RuntimeError(
                        selected.error
                        or f"Stored computation messages unreadable: {selected.path}"
                    )
                contents = selected.contents
                source_path = selected.path
                if len(stored_candidates) > 1:
                    logger.warning(
                        "Multiple stored computation-message sidecars exist for "
                        "plan %s; using %s by fixed precedence and ignoring: %s",
                        info.plan_number,
                        source_path.name,
                        ", ".join(
                            candidate.path.name
                            for candidate in stored_candidates[1:]
                        ),
                    )
                normalized_contents = contents.replace(
                    "\r\n", "\n"
                ).replace("\r", "\n")
                is_bco = source_path.name.casefold().endswith(
                    f".bco{info.plan_number}".casefold()
                )
                has_usable_contents = (
                    bool(normalized_contents.strip()) if is_bco else True
                )
                if has_usable_contents:
                    logger.debug(
                        "Reading computation messages for plan %s from comp_msgs file",
                        info.plan_number,
                    )
                    logger.debug(
                        "Computation messages file path: %s",
                        source_path,
                    )
                    logger.debug(
                        "Read %s characters from comp_msgs file",
                        len(normalized_contents),
                    )
                    # Preserve the historical text-mode API contract.  The
                    # provenance helper retains decoded source newlines,
                    # while get_comp_msgs() continues to apply universal-
                    # newline normalization as Python's former text-mode
                    # read did.
                    return normalized_contents
                logger.debug(
                    "Stored BCO computation message file is empty: %s; "
                    "attempting HDF fallback",
                    source_path,
                )
        except Exception as e:
            logger.warning(
                "Could not read stored computation messages; attempting HDF fallback"
            )
            logger.debug("Stored computation message read failed: %s", e)

        # If no .txt or .bco file found, try HDF fallback
        logger.debug(
            f"Computation messages file not found (tried .comp_msgs.txt, .computeMsgs.txt, and .bco{info.plan_number}), "
            f"falling back to HDF extraction"
        )

        try:
            # Late import to avoid circular dependency
            from .hdf.HdfResultsPlan import HdfResultsPlan

            # Construct HDF path
            hdf_file = Path(str(plan_file) + ".hdf")
            if hdf_file.exists():
                hdf_contents = HdfResultsPlan.get_compute_messages(hdf_file)
                if hdf_contents:
                    logger.debug(f"Successfully retrieved {len(hdf_contents)} characters from HDF")
                    return hdf_contents
        except Exception as e:
            logger.debug(f"HDF fallback failed: {e}")

        # Both methods failed
        logger.debug(
            f"No computation messages found in .txt or HDF sources for plan {info.plan_number}"
        )
        return ""

    # ========== PROCESS MANAGEMENT API ==========

    @staticmethod
    @log_call
    def inspect_processes() -> 'RasProcessInventory':
        """Return a strict host-wide HEC-RAS process inventory.

        Unlike :meth:`list_processes`, this safety-oriented API includes exact
        legacy and modern HEC-RAS launcher, solver, sediment/water-quality,
        and geometry-preprocessor names. It preserves PID plus creation-time
        identity and reports every query failure. Active sessions are tracked
        by that complete identity, never PID alone. Callers must require
        ``result.complete`` before treating an empty inventory as proof that
        the host is clear.

        Returns:
            RasProcessInventory: Immutable, JSON-safe process evidence.
        """
        from ._process_inspection import scan_ras_processes

        tracked_sessions = {
            (lock.ras_pid, lock.ras_create_time): lock.session_id
            for lock in _active_sessions.values()
            if lock.ras_pid and lock.ras_create_time is not None
        }
        return scan_ras_processes(
            tracked_sessions=tracked_sessions,
            psutil_module=psutil,
        )

    @staticmethod
    @log_call
    def list_processes(show_all: bool = False) -> pd.DataFrame:
        """
        List ras.exe processes with tracking status.

        Args:
            show_all: If True, show all ras.exe processes. If False (default),
                     only show processes tracked by this Python session.

        Returns:
            DataFrame with columns: pid, tracked, project, age_sec, status

        Example:
            >>> # Show only tracked processes
            >>> df = RasControl.list_processes()
            >>> print(df)

            >>> # Show all ras.exe on system
            >>> df_all = RasControl.list_processes(show_all=True)
            >>> print(df_all)
        """
        tracked_pids = {lock.ras_pid for lock in _active_sessions.values() if lock.ras_pid}

        rows = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time', 'cmdline']):
            try:
                if proc.info['name'] and proc.info['name'].lower() != 'ras.exe':
                    continue

                is_tracked = proc.info['pid'] in tracked_pids

                if not show_all and not is_tracked:
                    continue

                age = time.time() - proc.info['create_time']

                # Try to extract project from cmdline
                project = "Unknown"
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    for token in cmdline.split():
                        if token.endswith('.prj'):
                            project = Path(token).name
                            break
                except (TypeError, AttributeError):
                    pass

                rows.append({
                    'pid': proc.info['pid'],
                    'tracked': is_tracked,
                    'project': project,
                    'age_sec': round(age, 1),
                    'status': 'TRACKED' if is_tracked else 'UNTRACKED'
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not rows:
            logger.debug("No ras.exe processes found")
            return pd.DataFrame(columns=['pid', 'tracked', 'project', 'age_sec', 'status'])

        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    def scan_orphans() -> List[SessionLock]:
        """
        Scan lock files for orphaned sessions from crashed Python processes.

        Returns:
            List of SessionLock objects for orphaned processes (Python dead,
            ras.exe still running).

        Example:
            >>> orphans = RasControl.scan_orphans()
            >>> if orphans:
            >>>     print(f"Found {len(orphans)} orphaned processes")
            >>>     for orphan in orphans:
            >>>         print(f"  PID {orphan.ras_pid}: {Path(orphan.project_path).name}")
        """
        orphans = []

        if not LOCK_DIR.exists():
            return orphans

        for lock_file in LOCK_DIR.glob("rasctl_*.lock"):
            try:
                lock = SessionLock.from_file(lock_file)
                status = _classify_lock_file(lock)

                if status == 'stale_orphan':
                    orphans.append(lock)
                elif status == 'stale_clean':
                    # Clean up stale lock files
                    try:
                        lock_file.unlink()
                        logger.debug(f"Cleaned stale lock file: {lock_file.name}")
                    except Exception as e:
                        logger.debug(f"Could not clean stale lock: {e}")
            except Exception as e:
                logger.warning(f"Error reading lock file {lock_file.name}: {e}")

        return orphans

    @staticmethod
    @log_call
    def cleanup_orphans(interactive: bool = True, dry_run: bool = False) -> int:
        """
        Clean up orphaned ras.exe processes from crashed Python sessions.

        This method ONLY terminates processes that:
        1. Were started by RasControl (have session lock files)
        2. Have a dead parent Python process
        3. Are still running

        Args:
            interactive: If True, prompts user for confirmation before cleanup
            dry_run: If True, only reports what would be cleaned (no action)

        Returns:
            Number of processes cleaned up

        Example:
            >>> # Interactive cleanup (prompts for confirmation)
            >>> RasControl.cleanup_orphans()

            >>> # Automatic cleanup (no prompts)
            >>> count = RasControl.cleanup_orphans(interactive=False)
            >>> print(f"Cleaned {count} orphans")

            >>> # Dry run (see what would be cleaned)
            >>> RasControl.cleanup_orphans(dry_run=True)
        """
        orphans = RasControl.scan_orphans()

        if not orphans:
            print("✅ No orphaned processes found")
            logger.info("No orphaned processes found")
            return 0

        print(f"Found {len(orphans)} orphaned RAS process(es):")
        for orphan in orphans:
            age_min = (time.time() - orphan.start_time) / 60
            print(f"  • PID {orphan.ras_pid}: {Path(orphan.project_path).name} "
                  f"(running {age_min:.1f} min, Python {orphan.python_pid} crashed)")

        if dry_run:
            print("\n[Dry run - no action taken]")
            logger.info("Dry run - no orphans terminated")
            return 0

        if interactive:
            response = input("\nClean up these processes? (y/n): ")
            if response.lower() != 'y':
                print("Cancelled")
                logger.info("Cleanup cancelled by user")
                return 0

        cleaned = 0
        for orphan in orphans:
            try:
                proc = psutil.Process(orphan.ras_pid)
                if not _process_matches_lock_identity(proc, orphan):
                    logger.warning(
                        "Refusing to terminate PID %s because its creation "
                        "time does not match the session lock",
                        orphan.ras_pid,
                    )
                    continue
                proc.terminate()
                proc.wait(timeout=10)
                print(f"✅ Terminated PID {orphan.ras_pid}")
                logger.info(f"Terminated orphaned PID {orphan.ras_pid}")
                cleaned += 1

                # Remove lock file
                lock_file = _get_lock_file_path(orphan.session_id)
                lock_file.unlink(missing_ok=True)
            except psutil.TimeoutExpired:
                # Force kill if graceful termination fails
                try:
                    if not _process_matches_lock_identity(proc, orphan):
                        logger.warning(
                            "Refusing to kill PID %s because its identity "
                            "changed after terminate()",
                            orphan.ras_pid,
                        )
                        continue
                    proc.kill()
                    print(f"⚠️  Force killed PID {orphan.ras_pid}")
                    logger.warning(f"Force killed orphaned PID {orphan.ras_pid}")
                    cleaned += 1
                except Exception as e:
                    print(f"❌ Failed to kill PID {orphan.ras_pid}: {e}")
                    logger.error(f"Failed to kill orphaned PID {orphan.ras_pid}: {e}")
            except Exception as e:
                print(f"❌ Failed to terminate PID {orphan.ras_pid}: {e}")
                logger.error(f"Failed to terminate orphaned PID {orphan.ras_pid}: {e}")

        print(f"\n✅ Cleaned up {cleaned}/{len(orphans)} processes")
        logger.info(f"Cleaned up {cleaned}/{len(orphans)} orphaned processes")
        return cleaned

    @staticmethod
    @log_call
    def force_cleanup_all() -> int:
        """
        NUCLEAR OPTION: Terminate ALL ras.exe processes on the system.

        ⚠️  WARNING: This will kill:
        - Your tracked processes
        - Other users' processes
        - Manual HEC-RAS GUI sessions
        - Other Python scripts' processes

        Requires explicit "YES" confirmation to prevent accidental use.

        Returns:
            Number of processes terminated

        Example:
            >>> # Prompts for "YES" confirmation
            >>> RasControl.force_cleanup_all()
        """
        all_ras = [p for p in psutil.process_iter(['pid', 'name'])
                   if p.info['name'] and p.info['name'].lower() == 'ras.exe']

        if not all_ras:
            print("No ras.exe processes found")
            logger.info("No ras.exe processes to clean up")
            return 0

        print(f"⚠️  WARNING: This will terminate ALL {len(all_ras)} ras.exe process(es)")
        print("This includes:")
        print("  • Your tracked processes")
        print("  • Other users' processes")
        print("  • Manual HEC-RAS GUI sessions")
        print("  • Other Python scripts' processes")

        response = input("\n⚠️  Type 'YES' in all caps to confirm: ")
        if response != 'YES':
            print("Cancelled")
            logger.info("Force cleanup cancelled by user")
            return 0

        terminated = 0
        for proc in all_ras:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"✅ Terminated PID {proc.pid}")
                logger.info(f"Force terminated PID {proc.pid}")
                terminated += 1
            except psutil.TimeoutExpired:
                try:
                    proc.kill()
                    print(f"⚠️  Force killed PID {proc.pid}")
                    logger.warning(f"Force killed PID {proc.pid}")
                    terminated += 1
                except Exception as e:
                    print(f"❌ Failed to kill PID {proc.pid}: {e}")
                    logger.error(f"Failed to kill PID {proc.pid}: {e}")
            except Exception as e:
                print(f"❌ Failed to terminate PID {proc.pid}: {e}")
                logger.error(f"Failed to terminate PID {proc.pid}: {e}")

        print(f"\n✅ Terminated {terminated}/{len(all_ras)} processes")
        logger.info(f"Force cleanup terminated {terminated}/{len(all_ras)} processes")

        # Clean up all lock files
        if LOCK_DIR.exists():
            for lock_file in LOCK_DIR.glob("rasctl_*.lock"):
                try:
                    lock_file.unlink()
                except Exception:
                    pass

        return terminated


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("RasControl (ras-commander API) loaded successfully")
    print(f"Supported versions: {list(RasControl.SUPPORTED_VERSIONS.keys())}")
    print("\nUsage example:")
    print("  from ras_commander import init_ras_project, RasControl")
    print("  init_ras_project(path, '4.1')")
    print("  df = RasControl.get_steady_results('02')")
