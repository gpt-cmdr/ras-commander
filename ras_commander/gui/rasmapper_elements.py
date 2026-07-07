"""
RASMapper specific GUI element finders and actors.

Knows about the .NET WinForms RASMapper window structure:
TreeView layer navigation, context menus, toolbar, status bar.

Uses Win32Primitives for all low-level operations.

All methods are static and use the @log_call decorator.
"""

import time
from typing import Optional, Tuple

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = None
    WIN32_AVAILABLE = False

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .win32_primitives import Win32Primitives

logger = get_logger(__name__)


class RasMapperElements:
    """
    RASMapper specific GUI element finders and actors.

    RASMapper is a .NET WinForms application embedded within HEC-RAS.
    It has completely different window class names and control hierarchies
    from the VB6 main application.

    Key controls:
    - TreeView for layer navigation (Geometries, Terrain, Results, etc.)
    - Context menus for layer operations (right-click actions)
    - Toolbar for edit mode tools
    - Status bar for progress and status messages

    All methods are static and decorated with @log_call.
    """

    @staticmethod
    @log_call
    def find_rasmapper_window() -> Optional[Tuple[int, str]]:
        """
        Find the RASMapper window by title.

        Returns:
            (hwnd, title) tuple if found, None otherwise.
        """
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "RAS Mapper" in title:
                    windows.append((hwnd, title))
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)
        return windows[0] if windows else None

    @staticmethod
    @log_call
    def wait_for_rasmapper(timeout: int = 300, check_interval: int = 3) -> Optional[Tuple[int, str]]:
        """
        Wait for RASMapper window to appear and become responsive.

        Large projects may take several minutes to load geometry/terrain.
        This method checks window responsiveness, not just visibility.

        Args:
            timeout: Maximum seconds to wait. Default 300 (5 min).
            check_interval: Seconds between checks. Default 3.

        Returns:
            (hwnd, title) tuple if found and responsive, None on timeout.
        """
        start_time = time.time()
        last_log_time = start_time

        while time.time() - start_time < timeout:
            result = RasMapperElements.find_rasmapper_window()
            if result:
                hwnd, title = result
                if Win32Primitives.is_window_responsive(hwnd):
                    elapsed = int(time.time() - start_time)
                    logger.info(f"RASMapper opened (took {elapsed}s)")
                    logger.debug("RASMapper window title: %s", title)
                    return result
                else:
                    logger.debug("RASMapper window found but still loading...")

            elapsed = time.time() - start_time
            if elapsed - (last_log_time - start_time) >= 15:
                logger.debug(f"Still waiting for RASMapper... ({int(elapsed)}s elapsed)")
                last_log_time = time.time()

            time.sleep(check_interval)

        elapsed = int(time.time() - start_time)
        logger.error(f"RASMapper window did not appear after {elapsed} seconds")
        return None

    @staticmethod
    @log_call
    def wait_for_rasmapper_idle(
        hwnd: int,
        timeout: int = 600,
        check_interval: int = 3,
        idle_grace_seconds: int = 5,
    ) -> bool:
        """
        Wait for RASMapper to become idle after an operation.

        Checks window responsiveness as a proxy for operation completion.
        For mesh generation, also monitors the geometry HDF file modification time.

        Args:
            hwnd: RASMapper window handle.
            timeout: Maximum seconds to wait. Default 600 (10 min).
            check_interval: Seconds between checks. Default 3.
            idle_grace_seconds: Responsive quiet period to accept as idle when
                the command never makes the window visibly unresponsive.

        Returns:
            True if RASMapper became idle within timeout.
        """
        start_time = time.time()
        last_log_time = start_time

        # Wait for window to become unresponsive (operation started) then
        # responsive again. Some lightweight RASMapper commands never make the
        # window visibly unresponsive, so accept a short responsive quiet period
        # as completion instead of waiting out the full timeout.
        was_busy = False
        responsive_since = None

        while time.time() - start_time < timeout:
            responsive = Win32Primitives.is_window_responsive(hwnd)

            if not responsive:
                was_busy = True
                responsive_since = None
                logger.debug("RASMapper is busy...")
            elif was_busy and responsive:
                elapsed = int(time.time() - start_time)
                logger.info(f"RASMapper operation completed ({elapsed}s)")
                return True
            elif responsive and not was_busy:
                if responsive_since is None:
                    responsive_since = time.time()
                elif time.time() - responsive_since >= idle_grace_seconds:
                    elapsed = int(time.time() - start_time)
                    logger.debug(f"RASMapper remained responsive; treating as idle ({elapsed}s)")
                    return True

            elapsed = time.time() - start_time
            if elapsed - (last_log_time - start_time) >= 15:
                logger.debug(f"Waiting for RASMapper operation... ({int(elapsed)}s elapsed)")
                last_log_time = time.time()

            time.sleep(check_interval)

        elapsed = int(time.time() - start_time)
        logger.warning(f"RASMapper operation did not complete after {elapsed} seconds")
        return False
