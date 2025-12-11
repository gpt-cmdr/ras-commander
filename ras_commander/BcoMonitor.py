"""
BcoMonitor - Real-time monitoring of HEC-RAS .bco files during execution.

This module provides utilities for monitoring HEC-RAS computation progress by:
1. Enabling detailed logging (Write Detailed=1) in plan files
2. Monitoring .bco files for execution signals and messages
3. Streaming messages to callbacks in real-time
4. Detecting completion signals for early termination

Extracted from DockerWorker preprocessing logic and generalized for reuse.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable
import subprocess
import time
import re
from .LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class BcoMonitor:
    """
    Monitor HEC-RAS .bco file for execution signals and messages.

    The .bco file is created when 'Write Detailed= 1' is set in the plan file.
    It contains detailed computation messages written incrementally during execution.

    This class enables:
    - Real-time progress monitoring via .bco file polling
    - Message streaming to callbacks
    - Signal detection for early termination
    - Thread-safe operation (no shared state)

    Attributes:
        project_path: Path to HEC-RAS project folder
        plan_number: Plan number (e.g., "01", "02")
        project_name: Project name (without extension)
        signal_string: String to detect in .bco for early termination
        check_interval: Seconds between .bco file polls (default: 0.5)
        max_wait_seconds: Maximum wait time before timeout (default: 300)
        message_callback: Optional callback for new messages

    Example:
        >>> monitor = BcoMonitor(
        ...     project_path=Path("/path/to/project"),
        ...     plan_number="01",
        ...     project_name="MyProject",
        ...     message_callback=lambda msg: print(msg)
        ... )
        >>> process = subprocess.Popen(["RAS.exe", ...])
        >>> signal_detected = monitor.monitor_until_signal(process)
    """

    # Configuration
    project_path: Path
    plan_number: str
    project_name: str
    signal_string: str = "Starting Unsteady Flow Computations"
    check_interval: float = 0.5
    max_wait_seconds: int = 300

    # Optional callback for streaming messages
    message_callback: Optional[Callable[[str], None]] = None

    # Internal state (initialized in __post_init__)
    bco_file: Path = field(init=False)
    execution_start_time: Optional[float] = field(default=None, init=False)
    _last_file_position: int = field(default=0, init=False)

    def __post_init__(self):
        """Initialize paths and validate configuration."""
        self.bco_file = self.project_path / f"{self.project_name}.bco{self.plan_number}"
        logger.debug(f"BcoMonitor initialized for {self.bco_file.name}")

    @staticmethod
    def enable_detailed_logging(plan_file_path: Path) -> bool:
        """
        Enable detailed logging in a plan file by setting 'Write Detailed= 1'.

        This creates a .bcoXX file during HEC-RAS execution that can be monitored
        for the "Starting Unsteady Flow Computations" signal and other messages.

        Args:
            plan_file_path: Path to the plan file (.pXX)

        Returns:
            bool: True if successful, False otherwise

        Note:
            This modifies the plan file in-place. The modification is safe and
            follows HEC-RAS plan file format conventions.
        """
        try:
            content = plan_file_path.read_text(encoding='utf-8', errors='ignore')

            # Check if Write Detailed line exists
            if "Write Detailed=" in content:
                # Replace existing setting
                new_content = re.sub(
                    r'Write Detailed=\s*\d+',
                    'Write Detailed= 1',
                    content
                )
                if new_content != content:
                    plan_file_path.write_text(new_content, encoding='utf-8')
                    logger.debug(f"Enabled detailed logging in {plan_file_path.name}")
            else:
                # Add the setting after Run HTab line or at the end
                if "Run HTab=" in content:
                    new_content = content.replace(
                        "Run HTab=",
                        "Write Detailed= 1\nRun HTab="
                    )
                else:
                    new_content = content + "\nWrite Detailed= 1\n"
                plan_file_path.write_text(new_content, encoding='utf-8')
                logger.debug(f"Added detailed logging setting to {plan_file_path.name}")

            return True
        except Exception as e:
            logger.warning(f"Could not enable detailed logging: {e}")
            return False

    def monitor_until_signal(self, process: subprocess.Popen) -> bool:
        """
        Monitor .bco file until signal string appears or process completes.

        This method polls the .bco file at regular intervals, checking for:
        1. Process completion (normal exit or crash)
        2. Signal string detection (for early termination)
        3. New messages (streamed to callback if provided)

        Args:
            process: Running subprocess.Popen instance

        Returns:
            bool: True if signal detected, False if process completed without signal

        Note:
            - This is a blocking call that returns when signal appears or process exits
            - Callbacks are invoked from the calling thread (not a new thread)
            - File is read incrementally to minimize I/O overhead
        """
        self.execution_start_time = time.time()
        start_time = time.time()

        logger.info(f"Monitoring {self.bco_file.name} for '{self.signal_string}' signal...")

        while time.time() - start_time < self.max_wait_seconds:
            # Check if process died
            if process.poll() is not None:
                logger.info(f"Process exited with code {process.returncode}")
                # Read any final messages
                if self.bco_file.exists():
                    self._read_and_callback_new_content()
                return False

            # Check for .bco file with signal detection
            if self.bco_file.exists():
                # Verify file was modified after we started execution
                file_mtime = self.bco_file.stat().st_mtime
                if file_mtime >= self.execution_start_time:
                    # Read new content and check for signal
                    content = self._read_and_callback_new_content()
                    if content and self.signal_string in content:
                        logger.info(f"Detected '{self.signal_string}' in {self.bco_file.name}")
                        return True

            time.sleep(self.check_interval)

        logger.warning(f"Monitoring timed out after {self.max_wait_seconds}s")
        return False

    def get_final_messages(self) -> Optional[str]:
        """
        Read complete .bco file content after execution.

        Returns:
            Optional[str]: Full .bco file content, or None if file doesn't exist

        Note:
            Uses encoding resilience (errors='ignore') to handle partially written files.
        """
        if not self.bco_file.exists():
            return None

        try:
            return self.bco_file.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.debug(f"Could not read .bco file: {e}")
            return None

    def _read_and_callback_new_content(self) -> Optional[str]:
        """
        Read new content since last position and invoke callback if provided.

        Returns:
            Optional[str]: New content read, or None if error/no new content

        Note:
            Updates internal _last_file_position to track reading progress.
        """
        try:
            # Get current file size
            file_size = self.bco_file.stat().st_size

            # No new content since last read
            if file_size <= self._last_file_position:
                return None

            # Read from last position to current end
            with open(self.bco_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self._last_file_position)
                new_content = f.read()
                self._last_file_position = f.tell()

            # Invoke callback with new content if provided
            if new_content and self.message_callback:
                # Split into lines and call back for each non-empty line
                for line in new_content.splitlines():
                    if line.strip():
                        try:
                            self.message_callback(line)
                        except Exception as e:
                            logger.warning(f"Callback error: {e}")

            return new_content

        except Exception as e:
            logger.debug(f"Could not read new .bco content: {e}")
            return None

    def has_signal(self) -> bool:
        """
        Check if signal string exists in .bco file.

        Returns:
            bool: True if signal detected, False otherwise
        """
        content = self.get_final_messages()
        return content is not None and self.signal_string in content
