"""
HEC-RAS specific GUI element finders and actors.

Knows about HEC-RAS VB6 windows, menus, and dialogs.
Uses Win32Primitives for all low-level operations.

All methods are static and use the @log_call decorator.
"""

import time
import subprocess
import sys
from typing import Optional, List, Tuple

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = win32com = None
    WIN32_AVAILABLE = False

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .win32_primitives import Win32Primitives
from .constants import Win32Constants

logger = get_logger(__name__)


class HecRasElements:
    """
    HEC-RAS specific GUI element finders and actors.

    This class knows about HEC-RAS VB6 window structure:
    - Main MDI window identification (by title and menu bar)
    - "Already running" dialog handling
    - Plan combo box selection
    - Menu path navigation (e.g., GIS Tools > RAS Mapper)
    - Launch and wait orchestration

    Uses Win32Primitives for all low-level Win32 operations.
    All methods are static and decorated with @log_call.
    """

    @staticmethod
    @log_call
    def find_main_hecras_window(windows: List[Tuple[int, str]]) -> Tuple[Optional[int], Optional[str]]:
        """
        Find the main HEC-RAS window from a list of windows.

        The main window is identified by having "HEC-RAS" in the title and a menu bar.

        Args:
            windows: List of (window_handle, window_title) tuples.

        Returns:
            (window_handle, window_title) or (None, None).
        """
        for hwnd, title in windows:
            if "HEC-RAS" in title and win32gui.GetMenu(hwnd):
                logger.debug(f"Found main HEC-RAS window: {title}")
                return hwnd, title
        return None, None

    @staticmethod
    @log_call
    def handle_already_running_dialog(timeout: int = 5) -> bool:
        """
        Handle the "already an instance of HEC-RAS running" dialog.

        When HEC-RAS is launched while another instance is running, a dialog appears.
        This function automatically clicks "Yes" to continue.

        Args:
            timeout: Maximum seconds to wait for dialog to appear. Default 5.

        Returns:
            True if dialog was found and dismissed, False if no dialog appeared.
        """
        if not WIN32_AVAILABLE:
            return False

        logger.debug("Checking for 'already running' dialog...")
        start_time = time.time()
        check_interval = 0.5

        while time.time() - start_time < timeout:
            def find_already_running_dialog():
                def callback(hwnd, dialogs):
                    if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        class_name = win32gui.GetClassName(hwnd)

                        if class_name == Win32Constants.DIALOG_CLASS:
                            if "HEC-RAS" in title or title == "":
                                child_texts = []
                                def child_callback(child_hwnd, texts):
                                    try:
                                        text = win32gui.GetWindowText(child_hwnd)
                                        if text:
                                            texts.append(text.lower())
                                    except:
                                        pass
                                    return True
                                win32gui.EnumChildWindows(hwnd, child_callback, child_texts)

                                combined_text = " ".join(child_texts)
                                if "already" in combined_text or "another" in combined_text or "instance" in combined_text:
                                    dialogs.append(hwnd)
                    return True

                dialogs = []
                win32gui.EnumWindows(callback, dialogs)
                return dialogs[0] if dialogs else None

            dialog_hwnd = find_already_running_dialog()

            if dialog_hwnd:
                logger.debug("Found 'already running' dialog; attempting to continue")

                yes_button = None
                for button_text in ["Yes", "&Yes", "Ja", "&Ja"]:
                    yes_button = Win32Primitives.find_button_by_text(dialog_hwnd, button_text)
                    if yes_button:
                        break

                if yes_button:
                    Win32Primitives.click_button(yes_button)
                    logger.debug("Clicked 'Yes' button on already running dialog")
                    time.sleep(0.5)
                    return True
                else:
                    logger.debug("Yes button not found, trying Enter key...")
                    try:
                        win32gui.SetForegroundWindow(dialog_hwnd)
                        time.sleep(0.1)
                        win32api.keybd_event(Win32Constants.VK_RETURN, 0, 0, 0)
                        time.sleep(0.05)
                        win32api.keybd_event(Win32Constants.VK_RETURN, 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                        logger.debug("Sent Enter key to dismiss dialog")
                        time.sleep(0.5)
                        return True
                    except Exception as e:
                        logger.warning("Failed to dismiss already-running dialog")
                        logger.debug("Already-running dialog dismissal failure: %s", e)

            time.sleep(check_interval)

        logger.debug("No 'already running' dialog detected")
        return False

    @staticmethod
    @log_call
    def set_current_plan(hwnd: int, plan_number: str, ras_object=None) -> bool:
        """
        Set the current plan in HEC-RAS by finding and selecting from the plan dropdown.

        Args:
            hwnd: Handle to the main HEC-RAS window.
            plan_number: Plan number to select (e.g., "01", "02").
            ras_object: Optional RAS object instance.

        Returns:
            True if plan was successfully selected.
        """
        from ..RasPrj import ras
        ras_obj = ras_object or ras

        plan_combo = Win32Primitives.find_combobox_by_neighbor(hwnd, "Plan:")

        if not plan_combo:
            logger.warning("Could not find plan combo box")
            return False

        try:
            from ..RasPlan import RasPlan
            plan_title = RasPlan.get_plan_title(plan_number, ras_object=ras_obj)
            plan_shortid = RasPlan.get_shortid(plan_number, ras_object=ras_obj)

            search_terms = [
                f"p{plan_number}",
                f"{plan_shortid}",
                f"p{plan_number} - {plan_title}",
                f"p{plan_number} - {plan_shortid}",
            ]

            for term in search_terms:
                if Win32Primitives.select_combobox_item_by_text(plan_combo, term):
                    logger.debug(f"Successfully set current plan to p{plan_number}")
                    return True

            if Win32Primitives.select_combobox_item_by_text(plan_combo, plan_number):
                logger.debug(f"Successfully set current plan to p{plan_number}")
                return True

        except Exception as e:
            logger.debug("Could not get plan details; trying simple search: %s", e)
            if Win32Primitives.select_combobox_item_by_text(plan_combo, f"p{plan_number}"):
                logger.debug(f"Successfully set current plan to p{plan_number}")
                return True

        logger.error(f"Failed to set current plan to p{plan_number}")
        return False

    @staticmethod
    @log_call
    def launch_and_wait(
        ras_object=None,
        timeout: int = 30
    ) -> Tuple[Optional[subprocess.Popen], Optional[int]]:
        """
        Launch HEC-RAS, handle the already-running dialog, and wait for main window.

        This consolidates the duplicated launch logic from open_and_compute(),
        run_multiple_plans(), and open_rasmapper().

        Args:
            ras_object: Optional RAS object instance.
            timeout: Maximum seconds to wait for main window. Default 30.

        Returns:
            (process, hwnd) tuple. Both are None on failure.
        """
        if not WIN32_AVAILABLE:
            logger.error("GUI automation requires Windows and pywin32")
            return None, None

        from ..RasPrj import ras
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Step 1: Open HEC-RAS
        logger.info("Opening HEC-RAS...")
        ras_exe = ras_obj.ras_exe_path
        prj_path = f'"{str(ras_obj.prj_file)}"'
        command = f"{ras_exe} {prj_path}"

        try:
            if sys.platform == "win32":
                hecras_process = subprocess.Popen(command)
            else:
                hecras_process = subprocess.Popen([str(ras_exe), str(ras_obj.prj_file)])

            logger.info("HEC-RAS opened")
            logger.debug("HEC-RAS process ID: %s", hecras_process.pid)
        except Exception as e:
            logger.error("Failed to open HEC-RAS")
            logger.debug("HEC-RAS launch failure: %s", e)
            return None, None

        # Step 2: Handle "already running" dialog if it appears
        time.sleep(1)
        HecRasElements.handle_already_running_dialog(timeout=3)

        # Step 3: Wait for main window
        logger.debug("Waiting for HEC-RAS main window...")
        time.sleep(2)

        def find_ras_window():
            windows = Win32Primitives.get_windows_by_pid(hecras_process.pid)
            hwnd, title = HecRasElements.find_main_hecras_window(windows)
            return hwnd

        hec_ras_hwnd = Win32Primitives.wait_for_window(find_ras_window, timeout=timeout)

        if not hec_ras_hwnd:
            logger.error("Could not find main HEC-RAS window")
            try:
                hecras_process.terminate()
            except:
                pass
            return None, None

        logger.info("Found HEC-RAS main window")
        logger.debug("HEC-RAS main window title: %s", win32gui.GetWindowText(hec_ras_hwnd))
        return hecras_process, hec_ras_hwnd

    @staticmethod
    @log_call
    def click_menu_by_path(hwnd: int, menu_path: List[str]) -> bool:
        """
        Find and click a menu item by navigating the menu path.

        Uses runtime menu enumeration to find the correct menu ID,
        which is more robust than hardcoded IDs across HEC-RAS versions.

        Args:
            hwnd: Handle to the main window.
            menu_path: List of menu labels, e.g., ["&GIS Tools", "RAS &Mapper"].
                       Matching is case-insensitive and ignores '&' accelerators.

        Returns:
            True if menu item was found and clicked.
        """
        menus = Win32Primitives.enumerate_all_menus(hwnd)

        if not menus:
            logger.debug("No menus found")
            return False

        if len(menu_path) != 2:
            logger.error("click_menu_by_path currently supports 2-level menu paths only")
            return False

        top_menu_search = menu_path[0].replace("&", "").lower()
        item_search = menu_path[1].replace("&", "").lower()

        for menu_name, items in menus.items():
            if top_menu_search in menu_name.replace("&", "").lower():
                for item_text, menu_id in items:
                    if isinstance(item_text, str) and item_search in item_text.replace("&", "").lower():
                        logger.debug(f"Found menu item: '{item_text}' (ID: {menu_id})")
                        if isinstance(menu_id, int) and menu_id > 0:
                            return Win32Primitives.click_menu_item(hwnd, menu_id)

        logger.debug(f"Menu path not found: {menu_path}")
        return False

    @staticmethod
    @log_call
    def dismiss_save_prompt(timeout: int = 5) -> bool:
        """
        Dismiss a "Save changes?" prompt by clicking No.

        Args:
            timeout: Maximum seconds to wait for prompt. Default 5.

        Returns:
            True if prompt was found and dismissed.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            for pattern in ["Save", "save"]:
                dialog = Win32Primitives.find_dialog_by_title(pattern)
                if dialog:
                    for button_text in ["No", "&No", "Don't Save"]:
                        button = Win32Primitives.find_button_by_text(dialog, button_text)
                        if button:
                            Win32Primitives.click_button(button)
                            logger.debug("Dismissed save prompt")
                            return True
            time.sleep(0.5)

        logger.debug("No save prompt detected")
        return False
