"""
RasControl - HECRASController API Wrapper (ras-commander style)

Provides ras-commander style API for legacy HEC-RAS versions (3.x-4.x)
that use HECRASController COM interface instead of HDF files.

Includes robust process management with session tracking, orphan detection,
and optional watchdog protection for Jupyter kernel restarts.

Public functions (HEC-RAS Operations):
- RasControl.run_plan(plan, ras_object=None, force_recompute=False, use_watchdog=True, max_runtime=3600) -> Tuple[bool, List[str]]
- RasControl.get_steady_results(plan, ras_object=None) -> pandas.DataFrame
- RasControl.get_unsteady_results(plan, max_times=None, ras_object=None) -> pandas.DataFrame
- RasControl.get_output_times(plan, ras_object=None) -> List[str]
- RasControl.get_plans(plan, ras_object=None) -> List[dict]
- RasControl.set_current_plan(plan, ras_object=None) -> bool
- RasControl.get_comp_msgs(plan, ras_object=None) -> str

Public functions (Process Management):
- RasControl.list_processes(show_all=False) -> pandas.DataFrame
- RasControl.scan_orphans() -> List[SessionLock]
- RasControl.cleanup_orphans(interactive=True, dry_run=False) -> int
- RasControl.force_cleanup_all() -> int

Private functions:
- _terminate_ras_process() -> None
- _is_ras_running() -> bool
- RasControl._normalize_version(version: str) -> str
- RasControl._get_project_info(plan, ras_object=None) -> Tuple[Path, str, Optional[str], Optional[str]]
- RasControl._com_open_close(project_path: Path, version: str, operation_func: Callable[[Any], Any]) -> Any

Session tracking infrastructure:
- SessionLock dataclass - Tracks active COM sessions with lock files
- Module-level _active_sessions dict - Tracks all active sessions
- atexit handler - Emergency cleanup on Python exit
- Watchdog support - Optional independent process for kernel restart protection

"""

import psutil
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Any, Union, Dict
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

logger = logging.getLogger(__name__)

# Import ras-commander components
from .RasPrj import ras


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

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> 'SessionLock':
        """Deserialize from JSON string."""
        return cls(**json.loads(data))

    @classmethod
    def from_file(cls, path: Path) -> 'SessionLock':
        """Load from lock file."""
        return cls.from_json(path.read_text(encoding='utf-8'))


# Module-level session tracking
_active_sessions: Dict[str, SessionLock] = {}  # {session_id: SessionLock}

# Lock file directory
LOCK_DIR = Path(tempfile.gettempdir()) / "rascontrol_sessions"
LOCK_DIR.mkdir(exist_ok=True)


def _get_lock_file_path(session_id: str) -> Path:
    """Generate lock file path for a session."""
    filename = f"rasctl_{os.getpid()}_{session_id}.lock"
    return LOCK_DIR / filename


def _find_our_ras_process(project_path: Path, before_snapshot: Dict[int, Any]) -> Tuple[Optional[int], int]:
    """
    Multi-strategy detection to find the ras.exe process we just launched.

    Args:
        project_path: Path to .prj file being opened
        before_snapshot: Dict of {pid: proc_info} before COM launch

    Returns:
        Tuple of (pid, confidence_score). PID is None if detection failed.
        Confidence score is 0-100.
    """
    time.sleep(0.3)  # Give process time to appear

    candidates = {}  # {pid: confidence_score}

    try:
        after = {
            p.pid: p.info
            for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time'])
            if p.info['name'] and p.info['name'].lower() == 'ras.exe'
        }
    except Exception as e:
        logger.warning(f"Error scanning for ras.exe processes: {e}")
        return None, 0

    new_pids = set(after.keys()) - set(before_snapshot.keys())

    for pid in after.keys():
        proc_info = after[pid]
        score = 0

        # Criteria 1: Newly appeared (50 points)
        if pid in new_pids:
            score += 50

        # Criteria 2: Project path in cmdline (40 points)
        try:
            cmdline = ' '.join(proc_info['cmdline'] or [])
            if str(project_path) in cmdline or project_path.name in cmdline:
                score += 40
        except (TypeError, AttributeError):
            pass

        # Criteria 3: Very recent creation time (30 points)
        try:
            age = time.time() - proc_info['create_time']
            if age < 2.0:  # Created within 2 seconds
                score += 30
        except (TypeError, KeyError):
            pass

        # Criteria 4: Only one new process (20 points)
        if len(new_pids) == 1 and pid in new_pids:
            score += 20

        if score > 0:
            candidates[pid] = score

    if not candidates:
        logger.warning(f"Could not reliably identify ras.exe PID for {project_path.name}")
        return None, 0

    # Return highest confidence PID
    best_pid = max(candidates, key=candidates.get)
    confidence = candidates[best_pid]

    if confidence < 50:
        logger.warning(f"Low confidence ({confidence}/100) for PID {best_pid}")
    else:
        logger.info(f"Detected ras.exe PID {best_pid} (confidence: {confidence}/100)")

    return best_pid, confidence


def _classify_lock_file(lock: SessionLock) -> str:
    """
    Classify lock file state.

    Returns:
        'active' - Python still running, session active
        'stale_orphan' - Python dead, ras.exe still running
        'stale_clean' - Both dead, safe to delete
        'foreign_machine' - From different machine, don't touch
    """
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
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    if python_alive:
        return 'active'

    # Check 3: Is ras.exe still running?
    if lock.ras_pid is not None:
        try:
            ras_proc = psutil.Process(lock.ras_pid)
            if ras_proc.is_running() and ras_proc.name().lower() == 'ras.exe':
                # Verify it's working on our project (if cmdline available)
                try:
                    cmdline = ' '.join(ras_proc.cmdline() or [])
                    if lock.project_path in cmdline or Path(lock.project_path).name in cmdline:
                        return 'stale_orphan'  # Orphaned process!
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                # Couldn't verify project, but ras.exe exists - assume orphan if Python dead
                return 'stale_orphan'
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

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


def _cleanup_session(session_id: str) -> None:
    """Clean up a specific session."""
    if session_id in _active_sessions:
        lock = _active_sessions[session_id]

        # Try to terminate the ras.exe process gracefully
        if lock.ras_pid:
            try:
                proc = psutil.Process(lock.ras_pid)
                if proc.is_running() and proc.name().lower() == 'ras.exe':
                    logger.info(f"Terminating tracked ras.exe PID {lock.ras_pid}")
                    proc.terminate()
                    proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied) as e:
                logger.debug(f"Could not terminate PID {lock.ras_pid}: {e}")

        # Remove from tracking
        del _active_sessions[session_id]

        # Remove lock file
        _remove_session_lock(session_id)


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


def _spawn_watchdog(parent_pid: int, ras_pid: int, max_runtime: int,
                    lock_file_path: Path) -> int:
    """
    Spawn independent watchdog process for long-running operations.

    The watchdog monitors for:
    1. Parent Python process death (orphan detection)
    2. Runtime timeout
    3. Manual cancellation via lock file deletion

    Returns:
        Watchdog process PID
    """
    watchdog_script = f"""
import psutil
import time
import sys
from pathlib import Path

PARENT_PID = {parent_pid}
RAS_PID = {ras_pid}
MAX_RUNTIME = {max_runtime}
LOCK_FILE = Path({str(lock_file_path)!r})
CHECK_INTERVAL = 5  # seconds

start_time = time.time()

while True:
    time.sleep(CHECK_INTERVAL)

    # Check 1: Parent Python still alive?
    try:
        parent = psutil.Process(PARENT_PID)
        if not parent.is_running():
            # Parent died, orphan detected
            print(f"[Watchdog] Parent {{PARENT_PID}} died, terminating ras.exe {{RAS_PID}}", flush=True)
            try:
                ras = psutil.Process(RAS_PID)
                ras.terminate()
                ras.wait(timeout=10)
            except:
                pass
            LOCK_FILE.unlink(missing_ok=True)
            sys.exit(0)
    except psutil.NoSuchProcess:
        # Parent already gone
        try:
            ras = psutil.Process(RAS_PID)
            ras.terminate()
            ras.wait(timeout=10)
        except:
            pass
        LOCK_FILE.unlink(missing_ok=True)
        sys.exit(0)

    # Check 2: Timeout exceeded?
    if time.time() - start_time > MAX_RUNTIME:
        print(f"[Watchdog] Timeout exceeded, terminating ras.exe {{RAS_PID}}", flush=True)
        try:
            ras = psutil.Process(RAS_PID)
            ras.terminate()
            ras.wait(timeout=10)
        except:
            pass
        LOCK_FILE.unlink(missing_ok=True)
        sys.exit(0)

    # Check 3: Lock file deleted? (manual cancel signal)
    if not LOCK_FILE.exists():
        print(f"[Watchdog] Lock file deleted, assuming manual cleanup", flush=True)
        sys.exit(0)
"""

    try:
        # Launch watchdog as completely independent process
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        proc = subprocess.Popen(
            [sys.executable, '-c', watchdog_script],
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        logger.info(f"Spawned watchdog process PID {proc.pid} (monitoring PID {ras_pid})")
        return proc.pid
    except Exception as e:
        logger.error(f"Failed to spawn watchdog process: {e}")
        return 0


def _terminate_watchdog(watchdog_pid: int) -> None:
    """Terminate a watchdog process."""
    if watchdog_pid == 0:
        return

    try:
        proc = psutil.Process(watchdog_pid)
        proc.terminate()
        proc.wait(timeout=3)
        logger.debug(f"Terminated watchdog process PID {watchdog_pid}")
    except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
        pass


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
        Accepts formats: "4.1", "41", "5.0.6", "506", "6.6", "66", etc.
    """

    # Version mapping based on ACTUAL COM interfaces registered on system
    # Only these COM interfaces exist: RAS41, RAS503, RAS505, RAS506, RAS507,
    # RAS60, RAS631, RAS641, RAS65, RAS66, RAS67
    # Other versions use nearest available fallback
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
        '4.0': 'RAS41.HECRASController',    # Use 4.1 (4.0 COM not registered)
        '40': 'RAS41.HECRASController',
        '4.1': 'RAS41.HECRASController',    # ✓ EXISTS
        '41': 'RAS41.HECRASController',
        '4.1.0': 'RAS41.HECRASController',
        '410': 'RAS41.HECRASController',

        # HEC-RAS 5.0.x
        '5.0': 'RAS503.HECRASController',   # Use 5.0.3 (RAS50 COM not registered)
        '50': 'RAS503.HECRASController',
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
        '6.1': 'RAS60.HECRASController',    # Use 6.0 (6.1 COM not registered)
        '61': 'RAS60.HECRASController',
        '6.2': 'RAS60.HECRASController',    # Use 6.0 (6.2 COM not registered)
        '62': 'RAS60.HECRASController',
        '6.3': 'RAS631.HECRASController',   # Use 6.3.1 (6.3 COM not registered)
        '63': 'RAS631.HECRASController',
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
            "6.6", "66" → "6.6"
            "4.1", "41" → "4.1"
            "5.0.6", "506" → "5.0.6"
            "6.7 Beta 4" → "6.7 Beta 4"

        Returns:
            Normalized version string that exists in VERSION_MAP

        Raises:
            ValueError: If version cannot be normalized or is not supported
        """
        version_str = str(version).strip()

        # Direct match
        if version_str in RasControl.VERSION_MAP:
            return version_str

        # Try common normalizations
        normalized_candidates = [
            version_str,
            version_str.replace('.', ''),  # "6.6" → "66"
        ]

        # Try adding periods for compact formats
        if len(version_str) == 2:  # "66" → "6.6"
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
            f"  6.x: 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.4, 6.4.1, 6.5, 6.6, 6.7\n"
            f"  Formats: Can use '6.6' or '66', '5.0.6' or '506', etc."
        )

    @staticmethod
    def _get_project_info(plan: Union[str, Path], ras_object=None):
        """
        Resolve plan number/path to project path, version, and plan details.

        Returns:
            Tuple[Path, str, str, str]: (project_path, version, plan_number, plan_name)
            plan_number and plan_name are None if using direct .prj path
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
            return plan_path, ras_object.ras_version, None, None

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

        return project_path, version, plan_num, plan_name

    @staticmethod
    def _com_open_close(project_path: Path, version: str, operation_func: Callable[[Any], Any]) -> Any:
        """
        PRIVATE: Open HEC-RAS via COM, run operation, close HEC-RAS.

        This is the core COM interface handler. All public methods use this.
        Includes session tracking for robust cleanup on crashes/kernel restarts.
        """
        # Normalize version (handles "6.6" → "6.6", "66" → "6.6", etc.)
        normalized_version = RasControl._normalize_version(version)

        if not project_path.exists():
            raise FileNotFoundError(f"Project file not found: {project_path}")

        com_rc = None
        result = None
        session_id = str(uuid.uuid4())
        lock_path = None

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
            com_string = RasControl.VERSION_MAP[normalized_version]
            logger.info(f"Opening HEC-RAS: {com_string} (version: {version})")
            com_rc = win32com.client.Dispatch(com_string)

            # Open project
            logger.info(f"Opening project: {project_path}")
            com_rc.Project_Open(str(project_path))

            # Detect ras.exe PID after COM launch
            ras_pid, confidence = _find_our_ras_process(project_path, before_snapshot)

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
                detection_confidence=confidence
            )

            # Track session globally
            _active_sessions[session_id] = lock_data

            # Create lock file
            lock_path = _create_session_lock(session_id, lock_data)

            # Perform operation
            logger.info("Executing operation...")
            result = operation_func(com_rc)
            logger.info("Operation completed successfully")

            return result

        except Exception as e:
            logger.error(f"Operation failed: {e}")
            raise

        finally:
            # ALWAYS close
            logger.info("Closing HEC-RAS...")

            if com_rc is not None:
                try:
                    com_rc.QuitRas()
                    logger.info("HEC-RAS closed via QuitRas()")
                except Exception as e:
                    logger.warning(f"QuitRas() failed: {e}")

            # Clean up session tracking (terminates only our tracked PID)
            _cleanup_session(session_id)

            # Check if our specific process is still running
            if session_id in _active_sessions:
                logger.warning("Session cleanup may have failed - session still tracked")
            else:
                logger.debug("Session cleanup completed successfully")

    # ========== PUBLIC API (ras-commander style) ==========

    @staticmethod
    def run_plan(plan: Union[str, Path], ras_object=None, force_recompute: bool = False,
                 use_watchdog: bool = True, max_runtime: int = 86400) -> Tuple[bool, List[str]]:
        """
        Run a plan (steady or unsteady) and wait for completion.

        This method checks if results are current before running. If results
        are up-to-date, it skips computation (unless force_recompute=True).
        When computation is needed, it starts the computation and polls
        Compute_Complete() until the run finishes. It will block until completion.

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
            max_runtime: Maximum runtime in seconds before watchdog terminates the
                process. Only used if use_watchdog=True. Defaults to 3600 (1 hour).

        Returns:
            Tuple of (success: bool, messages: List[str])

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> # Default: with watchdog protection (recommended)
            >>> success, msgs = RasControl.run_plan("02")
            >>> # Force recomputation even if results are current
            >>> success, msgs = RasControl.run_plan("02", force_recompute=True)
            >>> # Disable watchdog (not recommended in Jupyter)
            >>> success, msgs = RasControl.run_plan("01", use_watchdog=False)
            >>> # Long-running with extended timeout
            >>> success, msgs = RasControl.run_plan("01", max_runtime=7200)

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
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _run_operation(com_rc):
            watchdog_pid = 0

            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            # Check if results are current (unless force_recompute=True)
            if not force_recompute:
                try:
                    is_current = com_rc.PlanOutput_IsCurrent()
                    if is_current:
                        logger.info(f"Plan {plan_num} results are current. Skipping computation.")
                        logger.info("Use force_recompute=True to recompute anyway.")
                        return True, ["Results are current - computation skipped"]
                except Exception as e:
                    logger.warning(f"Could not check PlanOutput_IsCurrent(): {e}")
                    logger.warning("Proceeding with computation...")

            # Version-specific behavior (normalize for checking)
            norm_version = RasControl._normalize_version(version)

            # Start computation (returns immediately - ASYNCHRONOUS!)
            logger.info("Starting computation...")
            if norm_version.startswith('4') or norm_version.startswith('3'):
                status, _, messages = com_rc.Compute_CurrentPlan(None, None)
            else:
                status, _, messages, _ = com_rc.Compute_CurrentPlan(None, None)

            # Spawn watchdog if requested
            if use_watchdog:
                # Find our session to get ras_pid and lock file
                current_session = None
                for session in _active_sessions.values():
                    if session.project_path == str(project_path):
                        current_session = session
                        break

                if current_session and current_session.ras_pid:
                    lock_file = _get_lock_file_path(current_session.session_id)
                    watchdog_pid = _spawn_watchdog(
                        parent_pid=os.getpid(),
                        ras_pid=current_session.ras_pid,
                        max_runtime=max_runtime,
                        lock_file_path=lock_file
                    )
                else:
                    logger.warning("Could not spawn watchdog - ras.exe PID not detected")

            try:
                # CRITICAL: Wait for computation to complete
                # Compute_CurrentPlan is ASYNCHRONOUS - it returns before computation finishes
                logger.info("Waiting for computation to complete...")
                poll_count = 0
                while True:
                    try:
                        # Check if computation is complete
                        is_complete = com_rc.Compute_Complete()

                        if is_complete:
                            logger.info(f"Computation completed (polled {poll_count} times)")
                            break

                        # Still computing - wait and poll again
                        time.sleep(1)  # Poll every second
                        poll_count += 1

                        # Log progress every 30 seconds
                        if poll_count % 30 == 0:
                            logger.info(f"Still computing... ({poll_count} seconds elapsed.  Simulation will timeout after {max_runtime} seconds.  Set max_runtime to override.)")

                    except Exception as e:
                        logger.error(f"Error checking completion status: {e}")
                        # If we can't check status, break and hope for the best
                        break

                return status, list(messages) if messages else []

            finally:
                # Always terminate watchdog on completion (even if error)
                if watchdog_pid:
                    _terminate_watchdog(watchdog_pid)

        return RasControl._com_open_close(project_path, version, _run_operation)

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
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

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
            logger.info(f"Found {len(profiles)} profiles")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.info(f"Found {len(river_names)} rivers")

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
                                            project_base = project_path.stem
                                            plan_file = project_path.parent / f"{project_base}.p{plan_num}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                logger.error(f"\n{'='*80}\nCOMPUTATION MESSAGES:\n{'='*80}\n{comp_msgs}\n{'='*80}")
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.info("Suppressing further extraction warnings...")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.info(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(project_path, version, _extract_operation)

    @staticmethod
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
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

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

            logger.info(f"Extracting {len(times)} time steps")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.info(f"Found {len(river_names)} rivers")

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
                                            project_base = project_path.stem
                                            plan_file = project_path.parent / f"{project_base}.p{plan_num}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                logger.error(f"\n{'='*80}\nCOMPUTATION MESSAGES:\n{'='*80}\n{comp_msgs}\n{'='*80}")
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.info("Suppressing further extraction warnings...")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.info(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(project_path, version, _extract_operation)

    @staticmethod
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
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _get_times(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            _, time_strings = com_rc.Output_GetProfiles(0, None)

            if time_strings is None:
                raise RuntimeError(
                    "No unsteady output times found. Ensure plan has been run."
                )

            times = list(time_strings)
            logger.info(f"Found {len(times)} output times")
            return times

        return RasControl._com_open_close(project_path, version, _get_times)

    @staticmethod
    def get_plans(plan: Union[str, Path], ras_object=None) -> List[dict]:
        """
        Get list of plans in project.

        Args:
            plan: Plan number or path to .prj file
            ras_object: Optional RasPrj instance

        Returns:
            List of dicts with 'name' and 'filename' keys
        """
        project_path, version, _, _ = RasControl._get_project_info(plan, ras_object)

        def _get_plans(com_rc):
            # Don't set current plan - just getting list
            _, plan_names, _ = com_rc.Plan_Names(None, None, None)

            plans = []
            for name in plan_names:
                filename, _ = com_rc.Plan_GetFilename(name)
                plans.append({'name': name, 'filename': filename})

            logger.info(f"Found {len(plans)} plans")
            return plans

        return RasControl._com_open_close(project_path, version, _get_plans)

    @staticmethod
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
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        if not plan_name:
            raise ValueError("Cannot set current plan - plan name could not be determined")

        def _set_plan(com_rc):
            com_rc.Plan_SetCurrent(plan_name)
            logger.info(f"Set current plan to Plan {plan_num}: {plan_name}")
            return True

        return RasControl._com_open_close(project_path, version, _set_plan)

    @staticmethod
    def get_comp_msgs(plan: Union[str, Path], ras_object=None) -> str:
        """
        Read computation messages from .txt file with fallback to HDF.

        The comp_msgs file is created by HEC-RAS during plan computation
        and contains detailed messages about the computation process,
        including warnings, errors, and convergence information.

        This method checks for two .txt naming patterns (version-dependent):
        - .comp_msgs.txt (HEC-RAS 3.x-5.x)
        - .computeMsgs.txt (HEC-RAS 6.x+)

        If neither .txt file exists, falls back to HDF extraction.

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
            - Older: {plan_file}.comp_msgs.txt
            - Newer: {plan_file}.computeMsgs.txt
            Falls back to HDF: /Results/Summary/Compute Messages (text)
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        # Construct plan file path
        # e.g., "A100_00_00.prj" -> "A100_00_00"
        project_base = project_path.stem
        plan_file = project_path.parent / f"{project_base}.p{plan_num}"

        # Try both .txt file naming patterns (version-dependent)
        comp_msgs_file_old = Path(str(plan_file) + ".comp_msgs.txt")
        comp_msgs_file_new = Path(str(plan_file) + ".computeMsgs.txt")

        comp_msgs_file = None
        if comp_msgs_file_old.exists():
            comp_msgs_file = comp_msgs_file_old
        elif comp_msgs_file_new.exists():
            comp_msgs_file = comp_msgs_file_new

        # If .txt file found, read and return
        if comp_msgs_file is not None:
            logger.info(f"Reading computation messages from: {comp_msgs_file}")

            try:
                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                    contents = f.read()

                logger.info(f"Read {len(contents)} characters from comp_msgs file")
                return contents
            except Exception as e:
                logger.error(f"Error reading .txt file: {e}, attempting HDF fallback")

        # If no .txt file found, try HDF fallback
        logger.warning(
            f"Computation messages .txt file not found (tried .comp_msgs.txt and .computeMsgs.txt), "
            f"falling back to HDF extraction"
        )

        try:
            # Late import to avoid circular dependency
            from .HdfResultsPlan import HdfResultsPlan

            # Construct HDF path
            hdf_file = Path(str(plan_file) + ".hdf")
            if hdf_file.exists():
                hdf_contents = HdfResultsPlan.get_compute_messages(hdf_file)
                if hdf_contents:
                    logger.info(f"Successfully retrieved {len(hdf_contents)} characters from HDF")
                    return hdf_contents
        except Exception as e:
            logger.debug(f"HDF fallback failed: {e}")

        # Both methods failed
        logger.debug(
            f"No computation messages found in .txt or HDF sources for plan {plan_num}"
        )
        return ""

    # ========== PROCESS MANAGEMENT API ==========

    @staticmethod
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
            logger.info("No ras.exe processes found")
            return pd.DataFrame(columns=['pid', 'tracked', 'project', 'age_sec', 'status'])

        return pd.DataFrame(rows)

    @staticmethod
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
