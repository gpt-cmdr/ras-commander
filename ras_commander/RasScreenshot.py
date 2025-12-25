"""
RasScreenshot - HEC-RAS window screenshot capture utilities

This module provides window-specific screenshot capabilities for HEC-RAS
automation and documentation. Screenshots capture only the target window
(not full screen) and are saved with timestamps to a gitignored folder.

The agent can "see" captured screenshots by using the Read tool on the
saved PNG files - Claude's multimodal capabilities interpret images.

Public classes:
    RasScreenshot - Static class for all screenshot operations

Public functions (via RasScreenshot class):
    capture_window(hwnd, output_path)           - Capture specific window by handle
    capture_hecras_main(pid, output_path)       - Capture main HEC-RAS window
    capture_dialog(title_pattern, output_path)  - Capture dialog by title pattern
    capture_all_ras_windows(pid, output_folder) - Capture all HEC-RAS windows
    capture_foreground(output_path)             - Capture current foreground window
    capture_with_delay(hwnd, delay, output_path) - Capture after delay
    get_screenshot_folder()                     - Get/create screenshot output folder
    list_screenshots()                          - List all captured screenshots

This module is part of the ras-commander library and uses centralized logging.
All public functions are static methods decorated with @log_call.

Dependencies:
    - pywin32 (win32gui, win32ui, win32con) - Windows API access
    - Pillow (PIL) - Image processing

Example:
    >>> from ras_commander import RasScreenshot, RasGuiAutomation
    >>> import subprocess
    >>>
    >>> # Launch HEC-RAS
    >>> process = subprocess.Popen([ras_exe, project_file])
    >>> pid = process.pid
    >>>
    >>> # Wait for window
    >>> import time
    >>> time.sleep(5)
    >>>
    >>> # Capture main window
    >>> screenshot = RasScreenshot.capture_hecras_main(pid)
    >>> print(f"Screenshot saved: {screenshot}")
    >>>
    >>> # Agent can view with: Read(file_path=str(screenshot))
"""

import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
import logging

# Win32 imports - Windows only
try:
    import win32gui
    import win32ui
    import win32con
    import win32process
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32ui = win32con = win32process = win32api = None
    WIN32_AVAILABLE = False

# PIL/Pillow imports
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    PIL_AVAILABLE = False

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Default output location (gitignored in .claude/outputs/)
DEFAULT_SCREENSHOT_FOLDER = Path(".claude/outputs/win32com-automation-expert/screenshots")


class RasScreenshot:
    """
    Static class for capturing HEC-RAS window screenshots.

    This class provides methods to programmatically capture screenshots of
    HEC-RAS windows and dialogs. Screenshots capture only the target window
    (not the full screen) and are saved with timestamps for easy organization.

    All methods are static and use the @log_call decorator for automatic logging.

    Technical Approach:
        Uses Win32 Device Context (DC) and BitBlt to capture window pixels
        directly from the window, even if partially occluded. The captured
        bitmap is converted to a PIL Image and saved as PNG.

    Output Location:
        Screenshots are saved to `.claude/outputs/win32com-automation-expert/screenshots/`
        which is gitignored, keeping the repository clean.

    Agent Integration:
        The agent can "see" captured screenshots using Claude's multimodal
        capabilities by calling Read(file_path=str(screenshot_path)).

    Examples:
        >>> # Capture main HEC-RAS window
        >>> screenshot = RasScreenshot.capture_hecras_main(hecras_pid)
        >>> print(f"Saved to: {screenshot}")

        >>> # Capture a specific dialog
        >>> screenshot = RasScreenshot.capture_dialog("Unsteady Flow Analysis")

        >>> # Capture all HEC-RAS windows
        >>> screenshots = RasScreenshot.capture_all_ras_windows(hecras_pid)
        >>> for path in screenshots:
        ...     print(f"  - {path}")
    """

    @staticmethod
    def _check_dependencies() -> Tuple[bool, str]:
        """Check if required dependencies are available."""
        if not WIN32_AVAILABLE:
            return False, "pywin32 not installed. Install with: pip install pywin32"
        if not PIL_AVAILABLE:
            return False, "Pillow not installed. Install with: pip install Pillow"
        return True, "All dependencies available"

    @staticmethod
    @log_call
    def capture_window(
        hwnd: int,
        output_path: Optional[Path] = None,
        include_timestamp: bool = True,
        restore_if_minimized: bool = True
    ) -> Optional[Path]:
        """
        Capture a screenshot of a specific window by handle.

        This method captures ONLY the target window (not full screen) using
        Win32 Device Context operations. The window does not need to be in
        the foreground.

        Args:
            hwnd: Window handle (HWND) to capture
            output_path: Path to save screenshot. If None, auto-generates path
                        in the default screenshot folder with timestamp.
            include_timestamp: If True, add timestamp to auto-generated filename
            restore_if_minimized: If True, restore minimized windows before capture

        Returns:
            Path to saved screenshot file, or None if capture failed

        Technical Details:
            Uses GetWindowDC + CreateCompatibleDC + BitBlt to capture window
            pixels. The bitmap is converted to PIL Image and saved as PNG.
            This approach captures the window even if partially occluded.

        Examples:
            >>> hwnd = 12345  # Window handle from get_windows_by_pid
            >>> screenshot = RasScreenshot.capture_window(hwnd)
            >>> print(f"Screenshot: {screenshot}")

            >>> # With custom path
            >>> screenshot = RasScreenshot.capture_window(
            ...     hwnd,
            ...     output_path=Path("my_screenshot.png")
            ... )
        """
        # Check dependencies
        available, msg = RasScreenshot._check_dependencies()
        if not available:
            logger.error(msg)
            return None

        try:
            # Validate window handle
            if not win32gui.IsWindow(hwnd):
                logger.warning(f"Invalid window handle: {hwnd}")
                return None

            # Restore if minimized
            if restore_if_minimized and win32gui.IsIconic(hwnd):
                logger.debug(f"Restoring minimized window: {hwnd}")
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.3)  # Wait for restore animation

            # Get window title for filename
            window_title = win32gui.GetWindowText(hwnd)
            logger.debug(f"Capturing window: '{window_title}' (HWND: {hwnd})")

            # Get window dimensions
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                logger.warning(f"Invalid window dimensions: {width}x{height}")
                return None

            # Get window DC and create compatible DC
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            # Create bitmap to hold capture
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # BitBlt to capture window pixels
            # SRCCOPY = direct copy of source pixels
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

            # Convert bitmap to PIL Image
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)

            image = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )

            # Clean up Windows GDI objects
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            # Generate output path if not provided
            if output_path is None:
                output_path = RasScreenshot._generate_screenshot_path(
                    window_title,
                    include_timestamp
                )

            # Ensure parent directory exists
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save image as PNG
            image.save(str(output_path), 'PNG')
            logger.info(f"Screenshot saved: {output_path}")

            return output_path

        except Exception as e:
            logger.error(f"Screenshot capture failed for HWND {hwnd}: {e}")
            return None

    @staticmethod
    def _generate_screenshot_path(
        window_title: str,
        include_timestamp: bool = True
    ) -> Path:
        """
        Generate unique screenshot filename with timestamp.

        Args:
            window_title: Window title to include in filename
            include_timestamp: If True, prepend timestamp to filename

        Returns:
            Path object for screenshot file
        """
        # Sanitize window title for filename
        # Keep only alphanumeric, spaces, hyphens, underscores
        safe_title = "".join(
            c if c.isalnum() or c in " -_" else "_"
            for c in window_title
        )
        # Replace multiple underscores/spaces with single underscore
        import re
        safe_title = re.sub(r'[_\s]+', '_', safe_title)
        safe_title = safe_title[:50].strip('_')  # Limit length

        if not safe_title:
            safe_title = "window"

        # Generate timestamp with milliseconds
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        if include_timestamp:
            filename = f"{timestamp}_{safe_title}.png"
        else:
            filename = f"{safe_title}.png"

        folder = RasScreenshot.get_screenshot_folder()
        return folder / filename

    @staticmethod
    @log_call
    def get_screenshot_folder() -> Path:
        """
        Get or create the screenshot output folder.

        Returns:
            Path to screenshot folder (creates if doesn't exist)

        Notes:
            Default location is `.claude/outputs/win32com-automation-expert/screenshots/`
            which is gitignored, keeping the repository clean.
        """
        folder = DEFAULT_SCREENSHOT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    @log_call
    def capture_hecras_main(
        pid: int,
        output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Capture screenshot of main HEC-RAS window by process ID.

        Finds the main HEC-RAS window (with menu bar) for the given process
        and captures a screenshot.

        Args:
            pid: HEC-RAS process ID (from subprocess.Popen.pid)
            output_path: Optional custom output path

        Returns:
            Path to screenshot file, or None if window not found

        Examples:
            >>> import subprocess
            >>> process = subprocess.Popen([ras_exe, project_file])
            >>> time.sleep(5)  # Wait for HEC-RAS to start
            >>> screenshot = RasScreenshot.capture_hecras_main(process.pid)
        """
        from .RasGuiAutomation import RasGuiAutomation

        windows = RasGuiAutomation.get_windows_by_pid(pid)
        hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)

        if hwnd:
            return RasScreenshot.capture_window(hwnd, output_path)
        else:
            logger.warning(f"No main HEC-RAS window found for PID {pid}")
            return None

    @staticmethod
    @log_call
    def capture_dialog(
        title_pattern: str,
        output_path: Optional[Path] = None,
        exact_match: bool = False
    ) -> Optional[Path]:
        """
        Capture screenshot of a dialog window by title pattern.

        Searches for visible dialogs matching the title pattern and
        captures a screenshot of the first match.

        Args:
            title_pattern: Substring to match in dialog title
            output_path: Optional custom output path
            exact_match: If True, require exact title match

        Returns:
            Path to screenshot file, or None if dialog not found

        Examples:
            >>> # Capture Unsteady Flow Analysis dialog
            >>> screenshot = RasScreenshot.capture_dialog("Unsteady Flow Analysis")

            >>> # Capture any dialog with "Plan" in title
            >>> screenshot = RasScreenshot.capture_dialog("Plan")
        """
        from .RasGuiAutomation import RasGuiAutomation

        hwnd = RasGuiAutomation.find_dialog_by_title(title_pattern, exact_match)

        if hwnd:
            return RasScreenshot.capture_window(hwnd, output_path)
        else:
            logger.warning(f"No dialog found matching '{title_pattern}'")
            return None

    @staticmethod
    @log_call
    def capture_all_ras_windows(
        pid: int,
        output_folder: Optional[Path] = None
    ) -> List[Path]:
        """
        Capture screenshots of ALL windows for a HEC-RAS process.

        Useful for capturing both the main window and any open dialogs
        in a single operation.

        Args:
            pid: HEC-RAS process ID
            output_folder: Folder to save screenshots (uses default if None)

        Returns:
            List of paths to saved screenshots

        Examples:
            >>> screenshots = RasScreenshot.capture_all_ras_windows(hecras_pid)
            >>> print(f"Captured {len(screenshots)} windows:")
            >>> for path in screenshots:
            ...     print(f"  - {path}")
        """
        from .RasGuiAutomation import RasGuiAutomation

        windows = RasGuiAutomation.get_windows_by_pid(pid)
        screenshots = []

        if output_folder is None:
            output_folder = RasScreenshot.get_screenshot_folder()
        else:
            output_folder = Path(output_folder)
            output_folder.mkdir(parents=True, exist_ok=True)

        for hwnd, title in windows:
            path = RasScreenshot.capture_window(hwnd)
            if path:
                screenshots.append(path)

        logger.info(f"Captured {len(screenshots)} screenshots for PID {pid}")
        return screenshots

    @staticmethod
    @log_call
    def capture_foreground(
        output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Capture screenshot of the current foreground window.

        Useful after triggering a menu click or dialog that changes focus.

        Args:
            output_path: Optional custom output path

        Returns:
            Path to screenshot file, or None if capture failed

        Examples:
            >>> # Click a menu, then capture resulting dialog
            >>> RasGuiAutomation.click_menu_item(hwnd, 47)
            >>> time.sleep(1.0)
            >>> screenshot = RasScreenshot.capture_foreground()
        """
        available, msg = RasScreenshot._check_dependencies()
        if not available:
            logger.error(msg)
            return None

        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd:
            return RasScreenshot.capture_window(fg_hwnd, output_path)
        else:
            logger.warning("No foreground window found")
            return None

    @staticmethod
    @log_call
    def capture_with_delay(
        hwnd: int,
        delay_seconds: float = 1.0,
        output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Capture window screenshot after a delay.

        Essential after menu clicks or dialog interactions to allow
        the UI to settle before capturing.

        Args:
            hwnd: Window handle to capture
            delay_seconds: Time to wait before capture (default 1.0s)
            output_path: Optional custom output path

        Returns:
            Path to screenshot file, or None if capture failed

        Examples:
            >>> # Click menu and capture with delay
            >>> RasGuiAutomation.click_menu_item(hwnd, 47)
            >>> screenshot = RasScreenshot.capture_with_delay(hwnd, delay_seconds=2.0)
        """
        logger.debug(f"Waiting {delay_seconds}s before capture...")
        time.sleep(delay_seconds)
        return RasScreenshot.capture_window(hwnd, output_path)

    @staticmethod
    @log_call
    def list_screenshots(
        folder: Optional[Path] = None,
        pattern: str = "*.png"
    ) -> List[Path]:
        """
        List all screenshots in the output folder.

        Args:
            folder: Folder to list (uses default if None)
            pattern: Glob pattern for files (default "*.png")

        Returns:
            List of screenshot file paths, sorted by modification time (newest first)

        Examples:
            >>> screenshots = RasScreenshot.list_screenshots()
            >>> print(f"Found {len(screenshots)} screenshots")
            >>> for path in screenshots[:5]:  # Show 5 most recent
            ...     print(f"  - {path.name}")
        """
        if folder is None:
            folder = RasScreenshot.get_screenshot_folder()
        else:
            folder = Path(folder)

        if not folder.exists():
            return []

        # Get files matching pattern, sorted by modification time (newest first)
        files = list(folder.glob(pattern))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return files

    @staticmethod
    @log_call
    def capture_menu_exploration(
        hwnd: int,
        menu_id: int,
        delay_after_click: float = 1.5
    ) -> Tuple[bool, Optional[Path], Optional[Path]]:
        """
        Click a menu item and capture both the triggering window and result.

        Captures the main window state before clicking, clicks the menu,
        waits for the result, then captures the resulting dialog or state.

        Args:
            hwnd: Main window handle
            menu_id: Menu item ID to click
            delay_after_click: Seconds to wait after clicking (default 1.5s)

        Returns:
            Tuple of (success, before_screenshot, after_screenshot)
            - success: True if menu click succeeded
            - before_screenshot: Screenshot before clicking (or None)
            - after_screenshot: Screenshot after clicking (or None)

        Examples:
            >>> # Explore the Unsteady Flow Analysis menu
            >>> success, before, after = RasScreenshot.capture_menu_exploration(
            ...     hwnd=main_hwnd,
            ...     menu_id=47,  # Unsteady Flow Analysis
            ...     delay_after_click=2.0
            ... )
            >>> if after:
            ...     print(f"Dialog captured: {after}")
        """
        from .RasGuiAutomation import RasGuiAutomation

        # Capture before state
        before_screenshot = RasScreenshot.capture_window(hwnd)

        # Click menu
        success = RasGuiAutomation.click_menu_item(hwnd, menu_id)
        if not success:
            logger.warning(f"Failed to click menu ID {menu_id}")
            return False, before_screenshot, None

        # Wait for UI to respond
        time.sleep(delay_after_click)

        # Try to capture new foreground window (dialog)
        fg_hwnd = win32gui.GetForegroundWindow()

        if fg_hwnd and fg_hwnd != hwnd:
            # New window appeared (likely dialog)
            after_screenshot = RasScreenshot.capture_window(fg_hwnd)
        else:
            # No new window, capture main window state
            after_screenshot = RasScreenshot.capture_window(hwnd)

        return True, before_screenshot, after_screenshot

    @staticmethod
    @log_call
    def document_dialog(
        hwnd: int,
        capture_screenshot: bool = True
    ) -> Dict[str, Any]:
        """
        Document a dialog window's controls and optionally capture screenshot.

        Enumerates all child controls (buttons, text boxes, combo boxes, etc.)
        and optionally captures a screenshot for visual reference.

        Args:
            hwnd: Dialog window handle
            capture_screenshot: If True, capture screenshot

        Returns:
            Dictionary with dialog documentation:
            {
                "timestamp": "2025-12-21T14:30:25.123",
                "window_title": "Unsteady Flow Analysis",
                "window_class": "#32770",
                "screenshot": Path("...") or None,
                "controls": [
                    {"class": "Button", "text": "Compute", "control_id": 101, ...},
                    ...
                ]
            }

        Examples:
            >>> dialog_hwnd = RasGuiAutomation.find_dialog_by_title("Unsteady Flow")
            >>> doc = RasScreenshot.document_dialog(dialog_hwnd)
            >>> print(f"Dialog: {doc['window_title']}")
            >>> for ctrl in doc['controls']:
            ...     if ctrl['text']:
            ...         print(f"  [{ctrl['class']}] {ctrl['text']}")
        """
        available, msg = RasScreenshot._check_dependencies()
        if not available:
            logger.error(msg)
            return {"error": msg}

        result = {
            "timestamp": datetime.now().isoformat(),
            "window_title": win32gui.GetWindowText(hwnd),
            "window_class": win32gui.GetClassName(hwnd),
            "screenshot": None,
            "controls": []
        }

        # Capture screenshot if requested
        if capture_screenshot:
            screenshot_path = RasScreenshot.capture_window(hwnd)
            result["screenshot"] = str(screenshot_path) if screenshot_path else None

        # Enumerate child controls
        def enum_callback(child_hwnd, controls):
            try:
                style = win32gui.GetWindowLong(child_hwnd, win32con.GWL_STYLE)
                rect = win32gui.GetWindowRect(child_hwnd)

                control_info = {
                    "hwnd": child_hwnd,
                    "class": win32gui.GetClassName(child_hwnd),
                    "text": win32gui.GetWindowText(child_hwnd),
                    "control_id": win32gui.GetDlgCtrlID(child_hwnd),
                    "visible": bool(style & win32con.WS_VISIBLE),
                    "enabled": bool(style & win32con.WS_DISABLED) == False,
                    "rect": {
                        "left": rect[0],
                        "top": rect[1],
                        "right": rect[2],
                        "bottom": rect[3]
                    }
                }
                controls.append(control_info)
            except Exception as e:
                logger.debug(f"Could not enumerate control {child_hwnd}: {e}")
            return True

        controls = []
        win32gui.EnumChildWindows(hwnd, enum_callback, controls)
        result["controls"] = controls

        logger.info(f"Documented dialog '{result['window_title']}' with {len(controls)} controls")
        return result
