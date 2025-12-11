"""
Example callback implementations for HEC-RAS execution monitoring.

This module provides ready-to-use callback classes demonstrating common patterns:
- ConsoleCallback: Simple console output
- FileLoggerCallback: Per-plan log files
- ProgressBarCallback: tqdm progress bars
- SynchronizedCallback: Thread-safe wrapper

These serve as both working implementations and reference examples for
creating custom callbacks.
"""

from pathlib import Path
from typing import Optional
from threading import Lock
import sys

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

from .LoggingConfig import get_logger

logger = get_logger(__name__)


class ConsoleCallback:
    """
    Simple callback that prints execution progress to console.

    This is the simplest possible callback implementation, suitable for:
    - Interactive sessions
    - Debugging
    - Quick scripts

    Thread Safety:
        Uses print() with file argument for atomic writes.
        Safe for concurrent use in compute_parallel().

    Example:
        >>> from ras_commander import RasCmdr
        >>> from ras_commander.callbacks import ConsoleCallback
        >>>
        >>> callback = ConsoleCallback()
        >>> RasCmdr.compute_plan("01", stream_callback=callback)
        [Plan 01] Starting execution...
        [Plan 01] Geometry Preprocessor Version 6.6
        [Plan 01] SUCCESS in 45.2s
    """

    def __init__(self, verbose: bool = False):
        """
        Initialize console callback.

        Args:
            verbose: If True, print all messages. If False, only print start/complete.
        """
        self.verbose = verbose

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """Print execution start message."""
        print(f"[Plan {plan_number}] Starting execution...", file=sys.stdout, flush=True)
        if self.verbose:
            print(f"[Plan {plan_number}] Command: {command}", file=sys.stdout, flush=True)

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """Print execution messages (if verbose mode enabled)."""
        if self.verbose:
            print(f"[Plan {plan_number}] {message.strip()}", file=sys.stdout, flush=True)

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """Print execution completion message."""
        status = "SUCCESS" if success else "FAILED"
        print(f"[Plan {plan_number}] {status} in {duration:.1f}s", file=sys.stdout, flush=True)


class FileLoggerCallback:
    """
    Callback that writes execution progress to per-plan log files.

    Creates a separate log file for each plan, enabling:
    - Detailed execution logs
    - Post-execution analysis
    - Archival records

    Thread Safety:
        Uses threading.Lock to ensure thread-safe file operations.
        Safe for concurrent use in compute_parallel().

    Example:
        >>> from pathlib import Path
        >>> from ras_commander.callbacks import FileLoggerCallback
        >>>
        >>> callback = FileLoggerCallback(output_dir=Path("logs"))
        >>> RasCmdr.compute_plan("01", stream_callback=callback)
        # Creates logs/plan_01_execution.log with full details
    """

    def __init__(self, output_dir: Path):
        """
        Initialize file logger callback.

        Args:
            output_dir: Directory for log files (created if doesn't exist)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_handles = {}
        self.lock = Lock()
        logger.info(f"FileLoggerCallback initialized: {self.output_dir}")

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """Open log file for this plan."""
        with self.lock:
            log_file = self.output_dir / f"plan_{plan_number}_execution.log"
            self.log_handles[plan_number] = open(log_file, 'w', encoding='utf-8')
            self.log_handles[plan_number].write(f"=== Plan {plan_number} Execution Log ===\n")
            self.log_handles[plan_number].write(f"Command: {command}\n")
            self.log_handles[plan_number].write("=" * 80 + "\n\n")
            self.log_handles[plan_number].flush()

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """Write message to plan's log file."""
        with self.lock:
            if plan_number in self.log_handles:
                self.log_handles[plan_number].write(message + '\n')
                self.log_handles[plan_number].flush()

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """Write completion message and close log file."""
        with self.lock:
            if plan_number in self.log_handles:
                status = "SUCCESS" if success else "FAILED"
                self.log_handles[plan_number].write("\n" + "=" * 80 + "\n")
                self.log_handles[plan_number].write(f"Execution {status} in {duration:.1f} seconds\n")
                self.log_handles[plan_number].close()
                del self.log_handles[plan_number]

    def __del__(self):
        """Cleanup: close any remaining open file handles."""
        with self.lock:
            for handle in self.log_handles.values():
                try:
                    handle.close()
                except:
                    pass


class ProgressBarCallback:
    """
    Callback that displays tqdm progress bars for execution.

    Shows real-time progress with:
    - Per-plan progress bar
    - Last message displayed
    - Execution time tracking

    Thread Safety:
        Uses threading.Lock to ensure thread-safe tqdm operations.
        Safe for concurrent use in compute_parallel().

    Requirements:
        Requires tqdm package: pip install tqdm

    Example:
        >>> from ras_commander.callbacks import ProgressBarCallback
        >>>
        >>> callback = ProgressBarCallback()
        >>> RasCmdr.compute_plan("01", stream_callback=callback)
        Plan 01: 100%|████████████| 1234/1234 [00:45<00:00, 27.42msg/s]
    """

    def __init__(self):
        """Initialize progress bar callback."""
        if not TQDM_AVAILABLE:
            raise ImportError(
                "ProgressBarCallback requires tqdm package. "
                "Install with: pip install tqdm"
            )
        self.pbars = {}
        self.lock = Lock()

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """Create progress bar for this plan."""
        with self.lock:
            self.pbars[plan_number] = tqdm(
                desc=f"Plan {plan_number}",
                unit="msg",
                dynamic_ncols=True
            )

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """Update progress bar with new message."""
        with self.lock:
            if plan_number in self.pbars:
                # Show last 50 characters of message
                short_message = message.strip()[-50:]
                self.pbars[plan_number].set_postfix_str(short_message)
                self.pbars[plan_number].update(1)

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """Close progress bar and display final status."""
        with self.lock:
            if plan_number in self.pbars:
                status = "SUCCESS" if success else "FAILED"
                self.pbars[plan_number].set_postfix_str(f"{status} in {duration:.1f}s")
                self.pbars[plan_number].close()
                del self.pbars[plan_number]


class SynchronizedCallback:
    """
    Thread-safe wrapper for any callback implementation.

    Wraps an existing callback to add thread-safety using locks.
    Useful when:
    - Using a callback that isn't thread-safe
    - Working with compute_parallel()
    - Sharing state across callbacks

    Thread Safety:
        Wraps all callback methods with threading.Lock.
        Guarantees only one thread executes callback at a time.

    Example:
        >>> class MyCallback:
        ...     def __init__(self):
        ...         self.messages = []  # Not thread-safe!
        ...     def on_exec_message(self, plan_number, message):
        ...         self.messages.append((plan_number, message))
        >>>
        >>> unsafe_callback = MyCallback()
        >>> safe_callback = SynchronizedCallback(unsafe_callback)
        >>> RasCmdr.compute_parallel(["01", "02"], stream_callback=safe_callback)
    """

    def __init__(self, callback):
        """
        Wrap a callback with thread-safety.

        Args:
            callback: Callback object to wrap (must implement ExecutionCallback methods)
        """
        self._callback = callback
        self._lock = Lock()

    def on_prep_start(self, plan_number: str) -> None:
        """Thread-safe wrapper for on_prep_start."""
        with self._lock:
            if hasattr(self._callback, 'on_prep_start'):
                self._callback.on_prep_start(plan_number)

    def on_prep_complete(self, plan_number: str) -> None:
        """Thread-safe wrapper for on_prep_complete."""
        with self._lock:
            if hasattr(self._callback, 'on_prep_complete'):
                self._callback.on_prep_complete(plan_number)

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """Thread-safe wrapper for on_exec_start."""
        with self._lock:
            if hasattr(self._callback, 'on_exec_start'):
                self._callback.on_exec_start(plan_number, command)

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """Thread-safe wrapper for on_exec_message."""
        with self._lock:
            if hasattr(self._callback, 'on_exec_message'):
                self._callback.on_exec_message(plan_number, message)

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """Thread-safe wrapper for on_exec_complete."""
        with self._lock:
            if hasattr(self._callback, 'on_exec_complete'):
                self._callback.on_exec_complete(plan_number, success, duration)

    def on_verify_result(self, plan_number: str, verified: bool) -> None:
        """Thread-safe wrapper for on_verify_result."""
        with self._lock:
            if hasattr(self._callback, 'on_verify_result'):
                self._callback.on_verify_result(plan_number, verified)
