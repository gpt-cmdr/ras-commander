"""
RasGuiAutomation - GUI automation for HEC-RAS using win32com

This module provides functionality to automate HEC-RAS GUI operations using Windows
COM automation and win32gui. It enables programmatic control of menu items, dialogs,
and buttons for workflows that don't have API support.

Public functions:
    get_windows_by_pid(pid)                    - Return all windows for a given process ID as (hwnd, title) tuples.
    find_main_hecras_window(windows)           - Identify the main HEC-RAS window from a window list.
    enumerate_all_menus(hwnd)                  - Return all top-level menus and items for the given window handle.
    click_menu_item(hwnd, menu_id)             - Trigger a menu item by sending WM_COMMAND to the main window.
    find_dialog_by_title(pattern, exact)       - Locate a visible dialog window by title substring or exact match.
    find_button_by_text(hwnd, text)            - Find a button control in a dialog window by its text.
    click_button(button_hwnd)                  - Simulate a click on a button control.
    find_combobox_by_neighbor(hwnd, text)      - Find a combo box control near a label with specific text.
    select_combobox_item_by_text(combo, text)  - Select an item in a combo box by its text.
    set_current_plan(hwnd, plan_number, ...)   - Set the current plan in HEC-RAS by selecting from the plan dropdown.
    wait_for_window(find_window_func, ...)     - Wait for a window using a polling function and timeout.
    open_and_compute(...)                      - Open HEC-RAS, set plan, navigate via menu, optionally click Compute.
    close_window(hwnd)                         - Close the given window handle via WM_CLOSE.
    run_multiple_plans(...)                    - Automate GUI workflow for "Run Multiple Plans" in HEC-RAS.

Private functions (scoped within above):
    Various local callback functions for window and child window enumeration.

This module is part of the ras-commander library and uses a centralized logging configuration.
All public functions are static methods on RasGuiAutomation and are decorated with @log_call.
"""

import time
import ctypes
from ctypes import wintypes
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Any

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    import win32com.client
    import win32process
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = win32com = win32process = None
    WIN32_AVAILABLE = False

from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

# Windows constants
WM_COMMAND = 0x0111
MF_BYPOSITION = 0x00000400


class RasGuiAutomation:
    """
    Static class for automating HEC-RAS GUI operations using win32com.

    This class provides methods to programmatically control HEC-RAS GUI elements
    including menus, dialogs, and buttons. It's designed for workflows that don't
    have programmatic API support (e.g., floodplain mapping).

    All methods are static and use the @log_call decorator for automatic logging.
    """

    @staticmethod
    @log_call
    def get_windows_by_pid(pid: int) -> List[Tuple[int, str]]:
        """
        Find all windows belonging to a specific process ID.

        Args:
            pid (int): Process ID to search for.

        Returns:
            List[Tuple[int, str]]: List of (window_handle, window_title) tuples.

        Examples:
            >>> windows = RasGuiAutomation.get_windows_by_pid(12345)
            >>> for hwnd, title in windows:
            ...     print(f"Window: {title}")
        """
        def callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                # Get the process ID for this window
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    window_title = win32gui.GetWindowText(hwnd)
                    if window_title:  # Only include windows with titles
                        hwnds.append((hwnd, window_title))
            return True

        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds

    @staticmethod
    @log_call
    def find_main_hecras_window(windows: List[Tuple[int, str]]) -> Tuple[Optional[int], Optional[str]]:
        """
        Find the main HEC-RAS window from a list of windows.

        The main window is identified by having "HEC-RAS" in the title and a menu bar.

        Args:
            windows (List[Tuple[int, str]]): List of (window_handle, window_title) tuples.

        Returns:
            Tuple[Optional[int], Optional[str]]: (window_handle, window_title) or (None, None).

        Examples:
            >>> windows = RasGuiAutomation.get_windows_by_pid(12345)
            >>> hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
        """
        for hwnd, title in windows:
            # Main window usually has "HEC-RAS" in title and has a menu bar
            if "HEC-RAS" in title and win32gui.GetMenu(hwnd):
                logger.debug(f"Found main HEC-RAS window: {title}")
                return hwnd, title
        return None, None

    @staticmethod
    @log_call
    def get_menu_string(menu_handle: int, pos: int) -> str:
        """
        Get menu item string at a specific position.

        Args:
            menu_handle (int): Handle to the menu.
            pos (int): Position index of the menu item.

        Returns:
            str: Menu item text, or empty string if not found.
        """
        # Create buffer for menu string
        buf_size = 256
        buf = ctypes.create_unicode_buffer(buf_size)

        # Get menu item info
        user32 = ctypes.windll.user32
        result = user32.GetMenuStringW(
            menu_handle,
            pos,
            buf,
            buf_size,
            MF_BYPOSITION
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
            hwnd (int): Handle to the window.

        Returns:
            dict: Dictionary mapping menu text to list of (item_text, menu_id) tuples.

        Examples:
            >>> hwnd = 12345
            >>> menus = RasGuiAutomation.enumerate_all_menus(hwnd)
            >>> print(menus['&Run'])
            [('&Unsteady Flow Analysis ...', 47), ...]
        """
        menu_bar = win32gui.GetMenu(hwnd)
        if not menu_bar:
            logger.warning("No menu bar found")
            return {}

        menu_count = win32gui.GetMenuItemCount(menu_bar)
        logger.debug(f"Found {menu_count} top-level menus")

        all_menus = {}

        for i in range(menu_count):
            # Get menu text
            menu_text = RasGuiAutomation.get_menu_string(menu_bar, i)

            # Get submenu handle
            submenu = win32gui.GetSubMenu(menu_bar, i)
            if submenu:
                item_count = win32gui.GetMenuItemCount(submenu)
                menu_items = []

                for j in range(item_count):
                    item_text = RasGuiAutomation.get_menu_string(submenu, j)
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
            hwnd (int): Handle to the main window.
            menu_id (int): Menu item ID to activate.

        Returns:
            bool: True if message was posted successfully.

        Examples:
            >>> # Click "Run > Unsteady Flow Analysis" (menu ID 47)
            >>> RasGuiAutomation.click_menu_item(hwnd, 47)
        """
        try:
            win32api.PostMessage(hwnd, WM_COMMAND, menu_id, 0)
            logger.info(f"Clicked menu item ID: {menu_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to click menu item {menu_id}: {e}")
            return False

    @staticmethod
    @log_call
    def find_dialog_by_title(title_pattern: str, exact_match: bool = False) -> Optional[int]:
        """
        Find a dialog window by title pattern.

        Args:
            title_pattern (str): Text to search for in window title.
            exact_match (bool): If True, require exact match. Default is substring match.

        Returns:
            Optional[int]: Window handle if found, None otherwise.

        Examples:
            >>> # Find "Unsteady Flow Analysis" dialog
            >>> dialog_hwnd = RasGuiAutomation.find_dialog_by_title("Unsteady Flow Analysis")
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
            dialog_hwnd (int): Handle to the dialog window.
            button_text (str): Text on the button (case-insensitive).

        Returns:
            Optional[int]: Button handle if found, None otherwise.

        Examples:
            >>> button_hwnd = RasGuiAutomation.find_button_by_text(dialog_hwnd, "Compute")
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
        Click a button by sending BN_CLICKED message.

        Args:
            button_hwnd (int): Handle to the button.

        Returns:
            bool: True if successful.
        """
        try:
            win32api.SendMessage(button_hwnd, win32con.BM_CLICK, 0, 0)
            logger.info(f"Clicked button: {win32gui.GetWindowText(button_hwnd)}")
            return True
        except Exception as e:
            logger.error(f"Failed to click button: {e}")
            return False

    @staticmethod
    @log_call
    def find_combobox_by_neighbor(hwnd: int, neighbor_text: str) -> Optional[int]:
        """
        Find a combo box control near a label with specific text.

        Args:
            hwnd (int): Handle to the parent window.
            neighbor_text (str): Text of a nearby label (case-insensitive).

        Returns:
            Optional[int]: Combo box handle if found, None otherwise.

        Examples:
            >>> combo = RasGuiAutomation.find_combobox_by_neighbor(hwnd, "Plan:")
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
            # For now, return the first combo box found
            # In a more sophisticated implementation, we could check proximity to the label
            return combos[0]

        logger.debug(f"No combo box found near '{neighbor_text}'")
        return None

    @staticmethod
    @log_call
    def select_combobox_item_by_text(combo_hwnd: int, item_text: str) -> bool:
        """
        Select an item in a combo box by its text.

        Args:
            combo_hwnd (int): Handle to the combo box.
            item_text (str): Text of the item to select (partial match, case-insensitive).

        Returns:
            bool: True if item was found and selected.

        Examples:
            >>> RasGuiAutomation.select_combobox_item_by_text(combo_hwnd, "p01")
        """
        try:
            # CB_GETCOUNT = 0x0146
            CB_GETCOUNT = 0x0146
            # CB_GETLBTEXTLEN = 0x0149
            CB_GETLBTEXTLEN = 0x0149
            # CB_GETLBTEXT = 0x0148
            CB_GETLBTEXT = 0x0148
            # CB_SETCURSEL = 0x014E
            CB_SETCURSEL = 0x014E

            # Get number of items in combo box
            count = win32api.SendMessage(combo_hwnd, CB_GETCOUNT, 0, 0)
            logger.debug(f"Combo box has {count} items")

            # Search for matching item
            for i in range(count):
                # Get length of text for this item
                text_len = win32api.SendMessage(combo_hwnd, CB_GETLBTEXTLEN, i, 0)
                if text_len > 0:
                    # Get the text
                    buffer = ctypes.create_unicode_buffer(text_len + 1)
                    win32api.SendMessage(combo_hwnd, CB_GETLBTEXT, i, buffer)
                    item = buffer.value

                    logger.debug(f"Combo box item {i}: '{item}'")

                    # Check for match (case-insensitive, partial match)
                    if item_text.lower() in item.lower():
                        # Select this item
                        win32api.SendMessage(combo_hwnd, CB_SETCURSEL, i, 0)
                        logger.info(f"Selected combo box item {i}: '{item}'")
                        return True

            logger.warning(f"Could not find item containing '{item_text}' in combo box")
            return False

        except Exception as e:
            logger.error(f"Failed to select combo box item: {e}")
            return False

## CHANGE THIS (START)

    @staticmethod
    @log_call
    def set_current_plan(hwnd: int, plan_number: str, ras_object=None) -> bool:
        """
        Set the current plan in HEC-RAS by finding and selecting from the plan dropdown.

        Args:
            hwnd (int): Handle to the main HEC-RAS window.
            plan_number (str): Plan number to select (e.g., "01", "02").
            ras_object: Optional RAS object instance.

        Returns:
            bool: True if plan was successfully selected.

        Examples:
            >>> RasGuiAutomation.set_current_plan(hwnd, "01")
        """
        ras_obj = ras_object or ras
        
        # Try to find the plan combo box
        # In HEC-RAS, the plan selector is typically a combo box near a "Plan:" label
        plan_combo = RasGuiAutomation.find_combobox_by_neighbor(hwnd, "Plan:")
        
        if not plan_combo:
            logger.warning("Could not find plan combo box")
            return False

        # Get plan details to construct the full plan text
        # Plans are typically shown as "p01 - Plan Title" or similar
        try:
            from .RasPlan import RasPlan
            plan_title = RasPlan.get_plan_title(plan_number, ras_object=ras_obj)
            plan_shortid = RasPlan.get_shortid(plan_number, ras_object=ras_obj)
            
            # Try different formats that HEC-RAS might use
            search_terms = [
                f"p{plan_number}",  # Just the plan number
                f"{plan_shortid}",  # Short ID
                f"p{plan_number} - {plan_title}",  # Full format with title
                f"p{plan_number} - {plan_shortid}",  # Format with short ID
            ]
            
            for term in search_terms:
                if RasGuiAutomation.select_combobox_item_by_text(plan_combo, term):
                    logger.info(f"Successfully set current plan to p{plan_number}")
                    return True
            
            # If none of the specific formats worked, just try the plan number
            if RasGuiAutomation.select_combobox_item_by_text(plan_combo, plan_number):
                logger.info(f"Successfully set current plan to p{plan_number}")
                return True
                
        except Exception as e:
            logger.warning(f"Could not get plan details, trying simple search: {e}")
            # Fallback to simple plan number search
            if RasGuiAutomation.select_combobox_item_by_text(plan_combo, f"p{plan_number}"):
                logger.info(f"Successfully set current plan to p{plan_number}")
                return True

        logger.error(f"Failed to set current plan to p{plan_number}")
        return False

## CHANGE THIS (START)


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
            find_window_func (Callable): Function that returns window handle or None.
            timeout (int): Maximum time to wait in seconds. Default is 60.
            check_interval (int): Time between checks in seconds. Default is 2.

        Returns:
            Any: Result from find_window_func if found within timeout, None otherwise.

        Examples:
            >>> # Wait for main HEC-RAS window
            >>> def find_ras():
            ...     windows = RasGuiAutomation.get_windows_by_pid(pid)
            ...     hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
            ...     return hwnd
            >>> hwnd = RasGuiAutomation.wait_for_window(find_ras, timeout=30)
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = find_window_func()
            if result:
                logger.debug("Window found")
                return result
            logger.debug(f"Window not found, waiting {check_interval} seconds...")
            time.sleep(check_interval)

        logger.warning(f"Window not found after {timeout} seconds")
        return None

    @staticmethod
    @log_call
    def open_and_compute(
        plan_number: str,
        ras_object=None,
        auto_click_compute: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        """
        Open HEC-RAS, set the current plan, navigate to Unsteady Flow Analysis, and optionally click Compute.

        This function automates the workflow:
        1. Open HEC-RAS with the project
        2. Wait for main window to appear
        3. Set the current plan to the specified plan_number
        4. Click "Run > Unsteady Flow Analysis" menu (ID 47)
        5. Optionally click "Compute" button in dialog
        6. Wait for user to close HEC-RAS (or return immediately)

        Args:
            plan_number (str): Plan number to run (e.g., "01", "02").
            ras_object: Optional RAS object instance.
            auto_click_compute (bool): If True, automatically click Compute button. Default True.
            wait_for_user (bool): If True, wait for user to close HEC-RAS. Default True.

        Returns:
            bool: True if successful, False otherwise.

        Examples:
            >>> # Full automation - runs plan "01"
            >>> RasGuiAutomation.open_and_compute("01", auto_click_compute=True)

            >>> # Just open dialog for plan "02", let user click Compute
            >>> RasGuiAutomation.open_and_compute("02", auto_click_compute=False)

        Notes:
            - This is designed for floodplain mapping workflows that require GUI execution
            - The function will attempt to set the current plan before running
            - Menu ID 47 is "Run > Unsteady Flow Analysis" in HEC-RAS 6.x
            - If plan selection or auto_click_compute fails, user can manually complete the workflow
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Step 1: Set current plan in .prj file BEFORE opening HEC-RAS
        # This ensures HEC-RAS opens with the correct plan active
        logger.info(f"Setting current plan to {plan_number} in project file...")
        try:
            ras_obj.set_current_plan(plan_number)
            logger.info(f"Current plan set to {plan_number} in {ras_obj.prj_file}")
        except Exception as e:
            logger.error(f"Failed to set current plan: {e}")
            return False

        # Step 2: Open HEC-RAS
        logger.info("Opening HEC-RAS...")
        ras_exe = ras_obj.ras_exe_path
        prj_path = f'"{str(ras_obj.prj_file)}"'
        command = f"{ras_exe} {prj_path}"

        try:
            if sys.platform == "win32":
                hecras_process = subprocess.Popen(command)
            else:
                hecras_process = subprocess.Popen([str(ras_exe), str(ras_obj.prj_file)])

            logger.info(f"HEC-RAS opened with Process ID: {hecras_process.pid}")
        except Exception as e:
            logger.error(f"Failed to open HEC-RAS: {e}")
            return False

        # Step 3: Wait for main window
        logger.info("Waiting for HEC-RAS main window...")
        time.sleep(3)  # Initial wait for process to start

        def find_ras_window():
            windows = RasGuiAutomation.get_windows_by_pid(hecras_process.pid)
            hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
            return hwnd

        hec_ras_hwnd = RasGuiAutomation.wait_for_window(find_ras_window, timeout=30)

        if not hec_ras_hwnd:
            logger.error("Could not find main HEC-RAS window")
            return False

        logger.info(f"Found HEC-RAS main window: {win32gui.GetWindowText(hec_ras_hwnd)}")

        # Note: Current plan was already set in .prj file before opening HEC-RAS (Step 1)
        # HEC-RAS should now have the correct plan active
        time.sleep(1)  # Let window fully load

        # Step 4: Click "Run > Unsteady Flow Analysis" (menu ID 47)
        logger.info("Clicking 'Run > Unsteady Flow Analysis' menu...")
        time.sleep(0.5)

        if not RasGuiAutomation.click_menu_item(hec_ras_hwnd, 47):
            logger.warning("Failed to click menu item, but continuing...")

        time.sleep(2)  # Wait for dialog to open

        # Step 5: Find and click Compute button (if auto_click_compute)
        if auto_click_compute:
            logger.info("Looking for Unsteady Flow Analysis dialog...")

            def find_unsteady_dialog():
                return RasGuiAutomation.find_dialog_by_title("Unsteady Flow Analysis")

            dialog_hwnd = RasGuiAutomation.wait_for_window(find_unsteady_dialog, timeout=15)

            if dialog_hwnd:
                logger.info("Found Unsteady Flow Analysis dialog")
                logger.info("Looking for Compute button...")

                # Try to find and click Compute button
                compute_button = RasGuiAutomation.find_button_by_text(dialog_hwnd, "Compute")

                if compute_button:
                    logger.info("Clicking Compute button...")
                    RasGuiAutomation.click_button(compute_button)
                else:
                    logger.warning("Could not find Compute button - user must click manually")
                    logger.info("Trying keyboard shortcut as fallback...")
                    try:
                        shell = win32com.client.Dispatch("WScript.Shell")
                        time.sleep(0.5)
                        shell.SendKeys("{ENTER}")
                        logger.info("Sent Enter key to dialog")
                    except Exception as e:
                        logger.warning(f"Keyboard fallback failed: {e}")
            else:
                logger.warning("Could not find Unsteady Flow Analysis dialog")
                logger.info("User must manually click 'Run > Unsteady Flow Analysis' and Compute")

        # Step 6: Wait for user to close HEC-RAS (or return immediately)
        if wait_for_user:
            logger.info("Waiting for user to close HEC-RAS...")
            logger.info(f"Please monitor plan {plan_number} execution and close HEC-RAS when complete")

            try:
                hecras_process.wait()
                logger.info("HEC-RAS has been closed")
            except Exception as e:
                logger.error(f"Error waiting for HEC-RAS to close: {e}")
                return False
        else:
            logger.info("Returning without waiting for HEC-RAS to close")
            logger.info(f"HEC-RAS process ID: {hecras_process.pid}")

        return True

    @staticmethod
    @log_call
    def close_window(hwnd: int) -> bool:
        """
        Close a window by sending WM_CLOSE message.

        Args:
            hwnd (int): Handle to the window to close.

        Returns:
            bool: True if successful.
        """
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            logger.info(f"Closed window: {win32gui.GetWindowText(hwnd)}")
            return True
        except Exception as e:
            logger.error(f"Failed to close window: {e}")
            return False

    @staticmethod
    @log_call
    def run_multiple_plans(
        plan_numbers: Optional[List[str]] = None,
        ras_object=None,
        check_all: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        """
        Open HEC-RAS and automate "Run > Run Multiple Plans" workflow.

        This function automates the workflow:
        1. Open HEC-RAS with the project
        2. Wait for main window to appear
        3. Click "Run > Run Multiple Plans" menu (ID 52)
        4. Optionally check all plans or select specific plans
        5. Click "Compute" or "Run All Checked Plans" button
        6. Wait for user to close HEC-RAS (or return immediately)

        Args:
            plan_numbers (Optional[List[str]]): List of plan numbers to run. If None and
                check_all=True, all plans will be checked. Currently informational only -
                the function checks all plans regardless.
            ras_object: Optional RAS object instance.
            check_all (bool): If True, attempts to check all plans. Default True.
            wait_for_user (bool): If True, wait for user to close HEC-RAS. Default True.

        Returns:
            bool: True if successful, False otherwise.

        Examples:
            >>> # Run all plans
            >>> RasGuiAutomation.run_multiple_plans(check_all=True)

            >>> # Run specific plans (currently checks all, but logs which plans were requested)
            >>> RasGuiAutomation.run_multiple_plans(plan_numbers=["01", "02"])

        Notes:
            - Menu ID 52 is "Run > Run Multiple Plans" in HEC-RAS 6.x
            - This is useful for batch processing multiple plans or stored maps
            - Currently checks all plans; specific plan selection would require
              analyzing the dialog checkbox structure
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if plan_numbers:
            logger.info(f"Requested plans: {', '.join(plan_numbers)}")
            logger.info("Note: Currently checking all plans. Specific plan selection not yet implemented.")

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

            logger.info(f"HEC-RAS opened with Process ID: {hecras_process.pid}")
        except Exception as e:
            logger.error(f"Failed to open HEC-RAS: {e}")
            return False

        # Step 2: Wait for main window
        logger.info("Waiting for HEC-RAS main window...")
        time.sleep(3)  # Initial wait for process to start

        def find_ras_window():
            windows = RasGuiAutomation.get_windows_by_pid(hecras_process.pid)
            hwnd, title = RasGuiAutomation.find_main_hecras_window(windows)
            return hwnd

        hec_ras_hwnd = RasGuiAutomation.wait_for_window(find_ras_window, timeout=30)

        if not hec_ras_hwnd:
            logger.error("Could not find main HEC-RAS window")
            return False

        logger.info(f"Found HEC-RAS main window: {win32gui.GetWindowText(hec_ras_hwnd)}")

        # Step 3: Click "Run > Run Multiple Plans" (menu ID 52)
        logger.info("Clicking 'Run > Run Multiple Plans' menu...")
        time.sleep(1)  # Let window fully load

        if not RasGuiAutomation.click_menu_item(hec_ras_hwnd, 52):
            logger.warning("Failed to click menu item, but continuing...")

        time.sleep(2)  # Wait for dialog to open

        # Step 4: Find the Run Multiple Plans dialog
        logger.info("Looking for Run Multiple Plans dialog...")

        def find_multiple_plans_dialog():
            # Try multiple possible dialog titles
            for title_pattern in ["Run Multiple Plans", "Multiple Plans", "Compute Multiple"]:
                hwnd = RasGuiAutomation.find_dialog_by_title(title_pattern)
                if hwnd:
                    return hwnd
            return None

        dialog_hwnd = RasGuiAutomation.wait_for_window(find_multiple_plans_dialog, timeout=15)

        if dialog_hwnd:
            logger.info(f"Found dialog: {win32gui.GetWindowText(dialog_hwnd)}")

            # Step 5: Try to check all plans (if check_all)
            if check_all:
                logger.info("Attempting to check all plans...")

                # Try to find "Check All" or "Select All" button
                check_all_button = None
                for button_text in ["Check All", "Select All", "All"]:
                    check_all_button = RasGuiAutomation.find_button_by_text(dialog_hwnd, button_text)
                    if check_all_button:
                        logger.info(f"Found '{button_text}' button")
                        RasGuiAutomation.click_button(check_all_button)
                        time.sleep(0.5)
                        break

                if not check_all_button:
                    logger.warning("Could not find 'Check All' button - plans may need manual selection")

            # Step 6: Click "Compute" or "Run All Checked Plans" button
            logger.info("Looking for Compute button...")
            time.sleep(1)

            compute_button = None
            for button_text in ["Compute", "Run", "Run All Checked Plans", "Start"]:
                compute_button = RasGuiAutomation.find_button_by_text(dialog_hwnd, button_text)
                if compute_button:
                    logger.info(f"Found '{button_text}' button")
                    RasGuiAutomation.click_button(compute_button)
                    break

            if not compute_button:
                logger.warning("Could not find Compute button - trying keyboard fallback...")
                try:
                    shell = win32com.client.Dispatch("WScript.Shell")
                    time.sleep(0.5)
                    shell.SendKeys("{ENTER}")
                    logger.info("Sent Enter key to dialog")
                except Exception as e:
                    logger.warning(f"Keyboard fallback failed: {e}")
                    logger.info("User must manually click Compute button")

        else:
            logger.warning("Could not find Run Multiple Plans dialog")
            logger.info("User must manually navigate to 'Run > Run Multiple Plans' and click Compute")

        # Step 7: Wait for user to close HEC-RAS (or return immediately)
        if wait_for_user:
            logger.info("Waiting for user to close HEC-RAS...")
            if plan_numbers:
                logger.info(f"Please monitor execution of plans: {', '.join(plan_numbers)}")
            else:
                logger.info("Please monitor execution and close HEC-RAS when complete")

            try:
                hecras_process.wait()
                logger.info("HEC-RAS has been closed")
            except Exception as e:
                logger.error(f"Error waiting for HEC-RAS to close: {e}")
                return False
        else:
            logger.info("Returning without waiting for HEC-RAS to close")
            logger.info(f"HEC-RAS process ID: {hecras_process.pid}")

        return True
