"""
Open and Compute workflow.

Opens HEC-RAS, sets plan, navigates to Unsteady Flow Analysis, and clicks Compute.
Migrated from RasGuiAutomation.open_and_compute().
"""

import time
from typing import Optional

# Win32 imports - Windows only
try:
    import win32gui
    import win32api
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32api = win32com = None
    WIN32_AVAILABLE = False

from ...LoggingConfig import get_logger
from ...Decorators import log_call
from ..win32_primitives import Win32Primitives
from ..hecras_elements import HecRasElements
from ..workflow_base import WorkflowStep, WorkflowResult, WorkflowExecutor
from ..constants import Win32Constants

logger = get_logger(__name__)


class OpenAndComputeWorkflow:
    """
    Open HEC-RAS, set plan, run Unsteady Flow Analysis, and click Compute.

    This workflow automates:
    1. Set current plan in .prj file
    2. Launch HEC-RAS and wait for main window
    3. Click Run > Unsteady Flow Analysis (menu ID 47)
    4. Optionally click Compute button in dialog
    5. Optionally wait for user to close HEC-RAS
    """

    @staticmethod
    @log_call
    def run(
        plan_number: str,
        ras_object=None,
        auto_click_compute: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        """
        Open HEC-RAS, set plan, and run Unsteady Flow Analysis.

        Args:
            plan_number: Plan number to run (e.g., "01", "02").
            ras_object: Optional RAS object instance.
            auto_click_compute: If True, automatically click Compute button. Default True.
            wait_for_user: If True, wait for user to close HEC-RAS. Default True.

        Returns:
            True if successful, False otherwise.
        """
        from ...RasPrj import ras
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Step 1: Set current plan in .prj file BEFORE opening HEC-RAS
        logger.info(f"Setting current plan to {plan_number} in project file...")
        try:
            ras_obj.set_current_plan(plan_number)
            logger.info(f"Current plan set to {plan_number} in {ras_obj.prj_file}")
        except Exception as e:
            logger.error(f"Failed to set current plan: {e}")
            return False

        # Step 2: Launch HEC-RAS and wait for main window
        hecras_process, hec_ras_hwnd = HecRasElements.launch_and_wait(
            ras_object=ras_obj, timeout=30
        )

        if not hec_ras_hwnd:
            return False

        time.sleep(1)  # Let window fully load

        # Step 3: Click "Run > Unsteady Flow Analysis" (menu ID 47)
        logger.info("Clicking 'Run > Unsteady Flow Analysis' menu...")
        time.sleep(0.5)

        if not Win32Primitives.click_menu_item(hec_ras_hwnd, 47):
            logger.warning("Failed to click menu item, but continuing...")

        time.sleep(2)

        # Step 4: Find and click Compute button (if auto_click_compute)
        if auto_click_compute:
            logger.info("Looking for Unsteady Flow Analysis dialog...")

            def find_unsteady_dialog():
                return Win32Primitives.find_dialog_by_title("Unsteady Flow Analysis")

            dialog_hwnd = Win32Primitives.wait_for_window(find_unsteady_dialog, timeout=15)

            if dialog_hwnd:
                logger.info("Found Unsteady Flow Analysis dialog")
                logger.info("Looking for Compute button...")

                try:
                    win32gui.SetForegroundWindow(dialog_hwnd)
                    time.sleep(0.5)
                except:
                    pass

                compute_button = None
                for button_text in ["Compute", "&Compute", "C&ompute", "OK", "&OK"]:
                    compute_button = Win32Primitives.find_button_by_text(dialog_hwnd, button_text)
                    if compute_button:
                        logger.info(f"Found button with text '{button_text}'")
                        break

                if compute_button:
                    logger.info("Clicking Compute button...")
                    Win32Primitives.click_button(compute_button)
                    time.sleep(0.5)
                else:
                    logger.warning("Could not find Compute button - trying keyboard shortcut...")
                    try:
                        win32api.keybd_event(Win32Constants.VK_RETURN, 0, 0, 0)
                        time.sleep(0.05)
                        win32api.keybd_event(Win32Constants.VK_RETURN, 0, Win32Constants.KEYEVENTF_KEYUP, 0)
                        logger.info("Sent Enter key via win32api")
                        time.sleep(0.5)
                    except Exception as e1:
                        logger.warning(f"win32api keyboard approach failed: {e1}")
                        try:
                            shell = win32com.client.Dispatch("WScript.Shell")
                            time.sleep(0.5)
                            shell.SendKeys("{ENTER}")
                            logger.info("Sent Enter key via WScript.Shell")
                        except Exception as e2:
                            logger.warning(f"WScript.Shell approach failed: {e2}")
                            logger.info("User must manually click Compute button")
            else:
                logger.warning("Could not find Unsteady Flow Analysis dialog")
                logger.info("User must manually click 'Run > Unsteady Flow Analysis' and Compute")

        # Step 5: Wait for user to close HEC-RAS (or return immediately)
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
