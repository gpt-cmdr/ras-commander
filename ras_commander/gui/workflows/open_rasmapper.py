"""
Open RASMapper workflow.

Opens HEC-RAS and launches RASMapper via the GIS Tools menu.
Migrated from RasGuiAutomation.open_rasmapper().
"""

import time
from typing import Optional

# Win32 imports - Windows only
try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32con = win32api = None
    WIN32_AVAILABLE = False

from ...LoggingConfig import get_logger
from ...Decorators import log_call
from ..win32_primitives import Win32Primitives
from ..hecras_elements import HecRasElements
from ..rasmapper_elements import RasMapperElements
from ..constants import Win32Constants

logger = get_logger(__name__)


class OpenRasMapperWorkflow:
    """
    Open RASMapper via HEC-RAS GUI automation.

    Steps:
    1. Launch HEC-RAS and wait for main window
    2. Click GIS Tools > RAS Mapper (via menu enumeration or keyboard fallback)
    3. Wait for RASMapper window to appear and become responsive
    4. Optionally wait for user to close RASMapper

    Notes:
        - RASMapper has NO COM interface — must use GUI automation
        - Opening RASMapper automatically upgrades .rasmap to current version
        - Large projects may take minutes to load — progress logged every 15s
    """

    @staticmethod
    @log_call
    def run(
        ras_object=None,
        wait_for_user: bool = True,
        timeout: int = 300
    ) -> bool:
        """
        Open RASMapper via the GIS Tools menu.

        Args:
            ras_object: Optional RasPrj object instance.
            wait_for_user: If True, wait for user to close RASMapper. Default True.
            timeout: Max seconds to wait for RASMapper window. Default 300 (5 min).

        Returns:
            True if RASMapper opened successfully.
        """
        # Step 1: Launch HEC-RAS and wait for main window
        hecras_process, hec_ras_hwnd = HecRasElements.launch_and_wait(
            ras_object=ras_object, timeout=30
        )

        if not hec_ras_hwnd:
            return False

        # Step 2: Click GIS Tools > RAS Mapper
        logger.info("Opening RASMapper via menu...")
        try:
            win32gui.SetForegroundWindow(hec_ras_hwnd)
        except:
            pass
        time.sleep(0.5)

        # Try menu path first (robust across versions)
        if not HecRasElements.click_menu_by_path(hec_ras_hwnd, ["&GIS Tools", "RAS &Mapper"]):
            # Fallback: Try keyboard shortcut Alt+G, M
            logger.debug("Menu path not found, trying keyboard shortcut...")
            try:
                win32gui.SetForegroundWindow(hec_ras_hwnd)
                time.sleep(0.2)

                # Alt+G to open GIS Tools menu
                win32api.keybd_event(Win32Constants.VK_MENU, 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('G'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('G'), 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)
                win32api.keybd_event(Win32Constants.VK_MENU, 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                time.sleep(0.3)

                # M to select Mapper
                win32api.keybd_event(ord('M'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('M'), 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                logger.debug("Sent keyboard shortcut Alt+G, M")
            except Exception as e:
                logger.warning("User must manually click GIS Tools > RAS Mapper")
                logger.debug("RASMapper keyboard shortcut failed: %s", e)

        # Step 3: Wait for RASMapper window
        logger.debug(f"Waiting for RASMapper window (up to {timeout} seconds)...")
        logger.debug("Large projects may take several minutes to load")

        rasmapper_result = RasMapperElements.wait_for_rasmapper(
            timeout=timeout, check_interval=3
        )

        if not rasmapper_result:
            logger.warning("RASMapper window did not open automatically")
            if not wait_for_user:
                return False

        # Step 4: Wait for user or return
        if wait_for_user:
            logger.debug("Waiting for user to close RASMapper...")

            while True:
                time.sleep(2)
                if not RasMapperElements.find_rasmapper_window():
                    logger.info("RASMapper closed by user")
                    break

            # Close HEC-RAS
            logger.debug("Closing HEC-RAS...")
            try:
                win32gui.PostMessage(hec_ras_hwnd, win32con.WM_CLOSE, 0, 0)
            except:
                pass
            try:
                hecras_process.wait(timeout=10)
            except:
                pass
            logger.debug("HEC-RAS closed")
        else:
            logger.info("Returning without waiting for RASMapper to close")
            logger.debug(f"HEC-RAS process ID: {hecras_process.pid}")

        return True
