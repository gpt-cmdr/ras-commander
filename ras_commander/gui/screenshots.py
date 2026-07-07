"""
HEC-RAS window screenshot capture utilities.

Migrated from RasScreenshot.py into the gui/ subpackage.
Re-exports the RasScreenshot class unchanged.
"""

# Import the actual implementation from the original module location.
# The original RasScreenshot.py will become a shim that imports from here.
# For now, during migration, we define the class here and the shim imports from us.

import ctypes
import re
import time
from ctypes import wintypes
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
DWMWA_EXTENDED_FRAME_BOUNDS = 9


class RasScreenshot:
    """
    Static class for capturing HEC-RAS window screenshots.

    Uses Win32 Device Context (DC) and BitBlt to capture window pixels
    directly. Screenshots capture only the target window frame, not extra
    desktop pixels around it.

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
    def _get_dwm_extended_frame_bounds(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """Return visible DWM frame bounds for a window, if Windows exposes them."""
        try:
            rect = wintypes.RECT()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                int(hwnd),
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
        except Exception as exc:
            logger.debug(f"DWM frame bounds unavailable for HWND {hwnd}: {exc}")
            return None

        if result != 0:
            logger.debug(f"DWM frame bounds failed for HWND {hwnd}: HRESULT {result}")
            return None

        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    @staticmethod
    def _visible_frame_crop_box(
        window_rect: Tuple[int, int, int, int],
        visible_frame_rect: Optional[Tuple[int, int, int, int]],
        image_size: Tuple[int, int],
    ) -> Optional[Tuple[int, int, int, int]]:
        """Translate screen-space visible frame bounds into an image crop box."""
        if visible_frame_rect is None:
            return None

        left, top, right, bottom = window_rect
        width, height = image_size
        visible_left, visible_top, visible_right, visible_bottom = visible_frame_rect

        if width <= 0 or height <= 0 or right <= left or bottom <= top:
            return None

        crop_left = max(0, min(width, visible_left - left))
        crop_top = max(0, min(height, visible_top - top))
        crop_right = max(0, min(width, visible_right - left))
        crop_bottom = max(0, min(height, visible_bottom - top))

        if crop_right <= crop_left or crop_bottom <= crop_top:
            return None

        crop_width = crop_right - crop_left
        crop_height = crop_bottom - crop_top
        if crop_width < width * 0.5 or crop_height < height * 0.5:
            logger.debug(
                "Ignoring implausible visible-frame crop "
                f"{(crop_left, crop_top, crop_right, crop_bottom)} "
                f"for image size {(width, height)}"
            )
            return None

        crop_box = crop_left, crop_top, crop_right, crop_bottom
        if crop_box == (0, 0, width, height):
            return None

        return crop_box

    @staticmethod
    def _bring_window_to_front(hwnd: int) -> bool:
        """Best-effort foreground request before a visible-frame screen capture."""
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            logger.debug(f"Could not bring HWND {hwnd} to foreground: {exc}")
        time.sleep(0.1)
        try:
            return win32gui.GetForegroundWindow() == hwnd
        except Exception as exc:
            logger.debug(f"Could not verify foreground HWND {hwnd}: {exc}")
            return False

    @staticmethod
    def _capture_screen_rect(rect: Tuple[int, int, int, int]):
        """Capture a screen-space rectangle into a Pillow image."""
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        screen_dc = None
        mfc_dc = None
        save_dc = None
        bitmap = None
        try:
            screen_dc = win32gui.GetDC(0)
            mfc_dc = win32ui.CreateDCFromHandle(screen_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            raster_op = win32con.SRCCOPY | getattr(win32con, "CAPTUREBLT", 0)
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), raster_op)

            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)
            return Image.frombuffer(
                'RGB',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRX', 0, 1
            )
        except Exception as exc:
            logger.debug(f"Screen rectangle capture failed for {rect}: {exc}")
            return None
        finally:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            if screen_dc is not None:
                win32gui.ReleaseDC(0, screen_dc)

    @staticmethod
    @log_call
    def capture_window(
        hwnd: int,
        output_path: Optional[Path] = None,
        include_timestamp: bool = True,
        restore_if_minimized: bool = True,
        crop_to_visible_frame: bool = True,
    ) -> Optional[Path]:
        """Capture a screenshot of a specific window by handle."""
        available, msg = RasScreenshot._check_dependencies()
        if not available:
            logger.error(msg)
            return None

        try:
            if not win32gui.IsWindow(hwnd):
                logger.warning("Invalid window handle")
                logger.debug("Invalid window handle: %s", hwnd)
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
                logger.warning("Invalid window dimensions")
                logger.debug("Invalid window dimensions for HWND %s: %sx%s", hwnd, width, height)
                return None

            visible_frame_rect = (
                RasScreenshot._get_dwm_extended_frame_bounds(hwnd)
                if crop_to_visible_frame
                else None
            )
            image = None
            captured_visible_frame = False
            if visible_frame_rect is not None:
                if RasScreenshot._bring_window_to_front(hwnd):
                    image = RasScreenshot._capture_screen_rect(visible_frame_rect)
                    captured_visible_frame = image is not None

            if image is None:
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

            if (
                crop_to_visible_frame
                and visible_frame_rect is not None
                and not captured_visible_frame
            ):
                crop_box = RasScreenshot._visible_frame_crop_box(
                    (left, top, right, bottom),
                    visible_frame_rect,
                    image.size,
                )
                if crop_box is not None:
                    logger.debug(
                        f"Cropping screenshot to visible frame: {crop_box}"
                    )
                    image = image.crop(crop_box)

            if output_path is None:
                output_path = RasScreenshot._generate_screenshot_path(
                    window_title, include_timestamp
                )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            image.save(str(output_path), 'PNG')
            logger.info("Screenshot saved: %s", output_path.name)
            logger.debug("Screenshot saved path: %s", output_path)

            return output_path

        except Exception as e:
            logger.error("Screenshot capture failed")
            logger.debug("Screenshot capture failure for HWND %s: %s", hwnd, e)
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
            logger.warning("No main HEC-RAS window found")
            logger.debug("No main HEC-RAS window found for PID %s", pid)
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

        logger.info(f"Captured {len(screenshots)} screenshots")
        logger.debug("Captured screenshots for PID %s: %s", pid, screenshots)
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
            logger.warning("Failed to click menu item")
            logger.debug("Failed to click menu ID %s", menu_id)
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

        logger.info(f"Documented dialog with {len(controls)} controls")
        logger.debug("Documented dialog title: %s", result["window_title"])
        return result
