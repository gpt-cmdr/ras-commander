"""
HEC-RAS window screenshot capture utilities.

Migrated from RasScreenshot.py into the gui/ subpackage.
Re-exports the RasScreenshot class unchanged.
"""

# Import the actual implementation from the original module location.
# The original RasScreenshot.py will become a shim that imports from here.
# For now, during migration, we define the class here and the shim imports from us.

import time
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

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

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)

DEFAULT_SCREENSHOT_FOLDER = Path(".claude/outputs/win32com-automation-expert/screenshots")


class RasScreenshot:
    """
    Static class for capturing HEC-RAS window screenshots.

    Uses Win32 Device Context (DC) and BitBlt to capture window pixels
    directly. Screenshots capture only the target window (not full screen).

    All methods are static and use the @log_call decorator.
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
        """Capture a screenshot of a specific window by handle."""
        available, msg = RasScreenshot._check_dependencies()
        if not available:
            logger.error(msg)
            return None

        try:
            if not win32gui.IsWindow(hwnd):
                logger.warning(f"Invalid window handle: {hwnd}")
                return None

            if restore_if_minimized and win32gui.IsIconic(hwnd):
                logger.debug(f"Restoring minimized window: {hwnd}")
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.3)

            window_title = win32gui.GetWindowText(hwnd)
            logger.debug(f"Capturing window: '{window_title}' (HWND: {hwnd})")

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                logger.warning(f"Invalid window dimensions: {width}x{height}")
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)

            image = Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )

            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            if output_path is None:
                output_path = RasScreenshot._generate_screenshot_path(
                    window_title, include_timestamp
                )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            image.save(str(output_path), 'PNG')
            logger.info(f"Screenshot saved: {output_path}")

            return output_path

        except Exception as e:
            logger.error(f"Screenshot capture failed for HWND {hwnd}: {e}")
            return None

    @staticmethod
    def _generate_screenshot_path(
        window_title: str, include_timestamp: bool = True
    ) -> Path:
        """Generate unique screenshot filename with timestamp."""
        safe_title = "".join(
            c if c.isalnum() or c in " -_" else "_"
            for c in window_title
        )
        safe_title = re.sub(r'[_\s]+', '_', safe_title)
        safe_title = safe_title[:50].strip('_')

        if not safe_title:
            safe_title = "window"

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
        """Get or create the screenshot output folder."""
        folder = DEFAULT_SCREENSHOT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    @log_call
    def capture_hecras_main(
        pid: int, output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Capture screenshot of main HEC-RAS window by process ID."""
        from .win32_primitives import Win32Primitives
        from .hecras_elements import HecRasElements

        windows = Win32Primitives.get_windows_by_pid(pid)
        hwnd, title = HecRasElements.find_main_hecras_window(windows)

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
        """Capture screenshot of a dialog window by title pattern."""
        from .win32_primitives import Win32Primitives

        hwnd = Win32Primitives.find_dialog_by_title(title_pattern, exact_match)

        if hwnd:
            return RasScreenshot.capture_window(hwnd, output_path)
        else:
            logger.warning(f"No dialog found matching '{title_pattern}'")
            return None

    @staticmethod
    @log_call
    def capture_all_ras_windows(
        pid: int, output_folder: Optional[Path] = None
    ) -> List[Path]:
        """Capture screenshots of ALL windows for a HEC-RAS process."""
        from .win32_primitives import Win32Primitives

        windows = Win32Primitives.get_windows_by_pid(pid)
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
    def capture_foreground(output_path: Optional[Path] = None) -> Optional[Path]:
        """Capture screenshot of the current foreground window."""
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
        hwnd: int, delay_seconds: float = 1.0, output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Capture window screenshot after a delay."""
        logger.debug(f"Waiting {delay_seconds}s before capture...")
        time.sleep(delay_seconds)
        return RasScreenshot.capture_window(hwnd, output_path)

    @staticmethod
    @log_call
    def list_screenshots(
        folder: Optional[Path] = None, pattern: str = "*.png"
    ) -> List[Path]:
        """List all screenshots in the output folder."""
        if folder is None:
            folder = RasScreenshot.get_screenshot_folder()
        else:
            folder = Path(folder)

        if not folder.exists():
            return []

        files = list(folder.glob(pattern))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    @staticmethod
    @log_call
    def capture_menu_exploration(
        hwnd: int, menu_id: int, delay_after_click: float = 1.5
    ) -> Tuple[bool, Optional[Path], Optional[Path]]:
        """Click a menu item and capture both before and after screenshots."""
        from .win32_primitives import Win32Primitives

        before_screenshot = RasScreenshot.capture_window(hwnd)

        success = Win32Primitives.click_menu_item(hwnd, menu_id)
        if not success:
            logger.warning(f"Failed to click menu ID {menu_id}")
            return False, before_screenshot, None

        time.sleep(delay_after_click)

        fg_hwnd = win32gui.GetForegroundWindow()

        if fg_hwnd and fg_hwnd != hwnd:
            after_screenshot = RasScreenshot.capture_window(fg_hwnd)
        else:
            after_screenshot = RasScreenshot.capture_window(hwnd)

        return True, before_screenshot, after_screenshot

    @staticmethod
    @log_call
    def document_dialog(
        hwnd: int, capture_screenshot: bool = True
    ) -> Dict[str, Any]:
        """Document a dialog window's controls and optionally capture screenshot."""
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

        if capture_screenshot:
            screenshot_path = RasScreenshot.capture_window(hwnd)
            result["screenshot"] = str(screenshot_path) if screenshot_path else None

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
                        "left": rect[0], "top": rect[1],
                        "right": rect[2], "bottom": rect[3]
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
