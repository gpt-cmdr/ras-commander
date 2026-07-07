"""
Win32 GUI automation primitives.

Generic Win32 window operations with zero HEC-RAS knowledge.
All methods are static and use the @log_call decorator.

Extracted from RasGuiAutomation.py for layered architecture.
"""

import time
import ctypes
from ctypes import wintypes
from typing import Optional, List, Tuple, Callable, Any

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    import win32process
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = win32process = None
    WIN32_AVAILABLE = False

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .constants import Win32Constants

logger = get_logger(__name__)


class Win32Primitives:
    """
    Generic Win32 window operations.

    This class has zero knowledge of HEC-RAS or any specific application.
    It provides reusable primitives for window discovery, menu interaction,
    button clicking, combo box selection, and window lifecycle management.

    All methods are static and decorated with @log_call.
    """

    @staticmethod
    @log_call
    def get_windows_by_pid(pid: int) -> List[Tuple[int, str]]:
        """
        Find all visible windows belonging to a specific process ID.

        Args:
            pid: Process ID to search for.

        Returns:
            List of (window_handle, window_title) tuples.
        """
        def callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:
                        hwnds.append((hwnd, window_title))
            return True

        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds

    @staticmethod
    @log_call
    def get_menu_string(menu_handle: int, pos: int) -> str:
        """
        Get menu item string at a specific position.

        Args:
            menu_handle: Handle to the menu.
            pos: Position index of the menu item.

        Returns:
            Menu item text, or empty string if not found.
        """
        buf_size = 256
        buf = ctypes.create_unicode_buffer(buf_size)
        user32 = ctypes.windll.user32
        result = user32.GetMenuStringW(
            menu_handle, pos, buf, buf_size,
            Win32Constants.MF_BYPOSITION
        )
        if result:
            return buf.value
        return ""

    @staticmethod
    @log_call
    def enumerate_all_menus(hwnd: int) -> dict:
        """
        Enumerate all menus and their items in a window.

        Args:
            hwnd: Handle to the window.

        Returns:
            Dictionary mapping menu text to list of (item_text, menu_id) tuples.
        """
        menu_bar = win32gui.GetMenu(hwnd)
        if not menu_bar:
            logger.debug("No menu bar found")
            return {}

        menu_count = win32gui.GetMenuItemCount(menu_bar)
        logger.debug(f"Found {menu_count} top-level menus")

        all_menus = {}

        for i in range(menu_count):
            menu_text = Win32Primitives.get_menu_string(menu_bar, i)
            submenu = win32gui.GetSubMenu(menu_bar, i)
            if submenu:
                item_count = win32gui.GetMenuItemCount(submenu)
                menu_items = []
                for j in range(item_count):
                    item_text = Win32Primitives.get_menu_string(submenu, j)
                    menu_id = win32gui.GetMenuItemID(submenu, j)
                    menu_items.append((item_text, menu_id))
                all_menus[menu_text] = menu_items

        return all_menus

    @staticmethod
    @log_call
    def click_menu_item(hwnd: int, menu_id: int) -> bool:
        """
        Click a menu item by sending a WM_COMMAND message.

        Args:
            hwnd: Handle to the main window.
            menu_id: Menu item ID to activate.

        Returns:
            True if message was posted successfully.
        """
        try:
            win32api.PostMessage(hwnd, Win32Constants.WM_COMMAND, menu_id, 0)
            logger.debug(f"Clicked menu item ID: {menu_id}")
            return True
        except Exception as e:
            logger.debug("Failed to click menu item %s: %s", menu_id, e)
            return False

    @staticmethod
    @log_call
    def find_dialog_by_title(title_pattern: str, exact_match: bool = False) -> Optional[int]:
        """
        Find a dialog window by title pattern.

        Args:
            title_pattern: Text to search for in window title.
            exact_match: If True, require exact match. Default is substring match.

        Returns:
            Window handle if found, None otherwise.
        """
        def callback(hwnd, dialogs):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if exact_match:
                    if window_title == title_pattern:
                        dialogs.append(hwnd)
                else:
                    if title_pattern.lower() in window_title.lower():
                        dialogs.append(hwnd)
            return True

        dialogs = []
        win32gui.EnumWindows(callback, dialogs)

        if dialogs:
            logger.debug(f"Found dialog matching '{title_pattern}': {len(dialogs)} window(s)")
            return dialogs[0]

        logger.debug(f"No dialog found matching '{title_pattern}'")
        return None

    @staticmethod
    @log_call
    def find_button_by_text(dialog_hwnd: int, button_text: str) -> Optional[int]:
        """
        Find a button in a dialog by its text.

        Args:
            dialog_hwnd: Handle to the dialog window.
            button_text: Text on the button (case-insensitive).

        Returns:
            Button handle if found, None otherwise.
        """
        def callback(child_hwnd, buttons):
            try:
                text = win32gui.GetWindowText(child_hwnd)
                class_name = win32gui.GetClassName(child_hwnd)
                if button_text.lower() in text.lower() and class_name == "Button":
                    buttons.append(child_hwnd)
            except:
                pass
            return True

        buttons = []
        win32gui.EnumChildWindows(dialog_hwnd, callback, buttons)

        if buttons:
            logger.debug(f"Found button with text '{button_text}'")
            return buttons[0]

        logger.debug(f"No button found with text '{button_text}'")
        return None

    @staticmethod
    @log_call
    def click_button(button_hwnd: int) -> bool:
        """
        Click a button by sending BM_CLICK message.

        Args:
            button_hwnd: Handle to the button.

        Returns:
            True if successful.
        """
        try:
            win32api.SendMessage(button_hwnd, win32con.BM_CLICK, 0, 0)
            logger.debug(f"Clicked button: {win32gui.GetWindowText(button_hwnd)}")
            return True
        except Exception as e:
            logger.debug("Button click failure for HWND %s: %s", button_hwnd, e)
            return False

    @staticmethod
    @log_call
    def find_combobox_by_neighbor(hwnd: int, neighbor_text: str) -> Optional[int]:
        """
        Find a combo box control near a label with specific text.

        Args:
            hwnd: Handle to the parent window.
            neighbor_text: Text of a nearby label (case-insensitive).

        Returns:
            Combo box handle if found, None otherwise.
        """
        def callback(child_hwnd, combos):
            try:
                class_name = win32gui.GetClassName(child_hwnd)
                if "ComboBox" in class_name:
                    combos.append(child_hwnd)
            except:
                pass
            return True

        combos = []
        win32gui.EnumChildWindows(hwnd, callback, combos)

        if combos:
            logger.debug(f"Found {len(combos)} combo box(es)")
            return combos[0]

        logger.debug(f"No combo box found near '{neighbor_text}'")
        return None

    @staticmethod
    @log_call
    def select_combobox_item_by_text(combo_hwnd: int, item_text: str) -> bool:
        """
        Select an item in a combo box by its text.

        Args:
            combo_hwnd: Handle to the combo box.
            item_text: Text of the item to select (partial match, case-insensitive).

        Returns:
            True if item was found and selected.
        """
        try:
            count = win32api.SendMessage(combo_hwnd, Win32Constants.CB_GETCOUNT, 0, 0)
            logger.debug(f"Combo box has {count} items")

            for i in range(count):
                text_len = win32api.SendMessage(combo_hwnd, Win32Constants.CB_GETLBTEXTLEN, i, 0)
                if text_len > 0:
                    buffer = ctypes.create_unicode_buffer(text_len + 1)
                    win32api.SendMessage(combo_hwnd, Win32Constants.CB_GETLBTEXT, i, buffer)
                    item = buffer.value

                    logger.debug(f"Combo box item {i}: '{item}'")

                    if item_text.lower() in item.lower():
                        win32api.SendMessage(combo_hwnd, Win32Constants.CB_SETCURSEL, i, 0)
                        logger.debug(f"Selected combo box item {i}: '{item}'")
                        return True

            logger.debug(f"Could not find item containing '{item_text}' in combo box")
            return False

        except Exception as e:
            logger.debug("Combo box selection failure for HWND %s: %s", combo_hwnd, e)
            return False

    @staticmethod
    @log_call
    def close_window(hwnd: int) -> bool:
        """
        Close a window by sending WM_CLOSE message.

        Args:
            hwnd: Handle to the window to close.

        Returns:
            True if successful.
        """
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            logger.debug(f"Closed window: {win32gui.GetWindowText(hwnd)}")
            return True
        except Exception as e:
            logger.debug("Window close failure for HWND %s: %s", hwnd, e)
            return False

    @staticmethod
    @log_call
    def wait_for_window(
        find_window_func: Callable,
        timeout: int = 60,
        check_interval: int = 2
    ) -> Any:
        """
        Wait for a window to appear using a custom search function.

        Args:
            find_window_func: Function that returns window handle or None.
            timeout: Maximum time to wait in seconds. Default is 60.
            check_interval: Time between checks in seconds. Default is 2.

        Returns:
            Result from find_window_func if found within timeout, None otherwise.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = find_window_func()
            if result:
                logger.debug("Window found")
                return result
            logger.debug(f"Window not found, waiting {check_interval} seconds...")
            time.sleep(check_interval)

        logger.debug(f"Window not found after {timeout} seconds")
        return None

    @staticmethod
    @log_call
    def is_window_responsive(hwnd: int, timeout_ms: int = 1000) -> bool:
        """
        Check if a window is responding (not hung).

        Uses SendMessageTimeout with SMTO_ABORTIFHUNG to detect hung windows.

        Args:
            hwnd: Window handle to check.
            timeout_ms: Timeout in milliseconds. Default 1000.

        Returns:
            True if window is responsive.
        """
        try:
            result = ctypes.windll.user32.SendMessageTimeoutW(
                hwnd, Win32Constants.WM_NULL, 0, 0,
                Win32Constants.SMTO_ABORTIFHUNG,
                timeout_ms,
                ctypes.byref(ctypes.c_ulong())
            )
            return result != 0
        except:
            return False

    @staticmethod
    @log_call
    def send_keyboard_shortcut(hwnd: int, *key_codes: int) -> bool:
        """
        Send a keyboard shortcut to a window.

        Presses all keys down in order, then releases in reverse order.

        Args:
            hwnd: Window handle to target (will be brought to foreground).
            *key_codes: Virtual key codes to press (e.g., VK_MENU, ord('G')).

        Returns:
            True if successful.
        """
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)

            # Press all keys down
            for vk in key_codes:
                win32api.keybd_event(vk, 0, 0, 0)
                time.sleep(0.05)

            # Release all keys in reverse order
            for vk in reversed(key_codes):
                win32api.keybd_event(vk, 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)

            logger.debug(f"Sent keyboard shortcut: {[hex(k) for k in key_codes]}")
            return True
        except Exception as e:
            logger.debug("Keyboard shortcut failed for HWND %s: %s", hwnd, e)
            return False

    @staticmethod
    @log_call
    def find_child_by_class_name(parent_hwnd: int, class_name: str) -> List[int]:
        """
        Find child windows by class name.

        Args:
            parent_hwnd: Handle to the parent window.
            class_name: Win32 class name to search for.

        Returns:
            List of matching child window handles.
        """
        def callback(child_hwnd, results):
            try:
                if win32gui.GetClassName(child_hwnd) == class_name:
                    results.append(child_hwnd)
            except:
                pass
            return True

        results = []
        win32gui.EnumChildWindows(parent_hwnd, callback, results)
        return results

    @staticmethod
    @log_call
    def get_window_class_name(hwnd: int) -> str:
        """
        Get the Win32 class name of a window.

        Args:
            hwnd: Window handle.

        Returns:
            Class name string.
        """
        try:
            return win32gui.GetClassName(hwnd)
        except:
            return ""
