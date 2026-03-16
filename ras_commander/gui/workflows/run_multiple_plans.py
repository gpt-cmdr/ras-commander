"""
Run Multiple Plans workflow.

Opens HEC-RAS and automates the "Run > Run Multiple Plans" dialog.
Migrated from RasGuiAutomation.run_multiple_plans().
"""

import time
from typing import Optional, List

# Win32 imports - Windows only
try:
    import win32gui
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    win32gui = win32com = None
    WIN32_AVAILABLE = False

from ...LoggingConfig import get_logger
from ...Decorators import log_call
from ..win32_primitives import Win32Primitives
from ..hecras_elements import HecRasElements
from ..constants import Win32Constants

logger = get_logger(__name__)


class RunMultiplePlansWorkflow:
    """
    Open HEC-RAS and automate "Run > Run Multiple Plans" workflow.

    Steps:
    1. Launch HEC-RAS and wait for main window
    2. Click Run > Run Multiple Plans (menu ID 52)
    3. Optionally check all plans
    4. Click Compute or Run All Checked Plans
    5. Optionally wait for user to close HEC-RAS
    """

    @staticmethod
    @log_call
    def run(
        plan_numbers: Optional[List[str]] = None,
        ras_object=None,
        check_all: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        """
        Open HEC-RAS and run multiple plans.

        Args:
            plan_numbers: List of plan numbers to run. Currently informational only.
            ras_object: Optional RAS object instance.
            check_all: If True, attempts to check all plans. Default True.
            wait_for_user: If True, wait for user to close HEC-RAS. Default True.

        Returns:
            True if successful, False otherwise.
        """
        if plan_numbers:
            logger.info(f"Requested plans: {', '.join(plan_numbers)}")
            logger.info("Note: Currently checking all plans. Specific plan selection not yet implemented.")

        # Step 1: Launch HEC-RAS and wait for main window
        hecras_process, hec_ras_hwnd = HecRasElements.launch_and_wait(
            ras_object=ras_object, timeout=30
        )

        if not hec_ras_hwnd:
            return False

        # Step 2: Click "Run > Run Multiple Plans" (menu ID 52)
        logger.info("Clicking 'Run > Run Multiple Plans' menu...")
        time.sleep(1)

        if not Win32Primitives.click_menu_item(hec_ras_hwnd, 52):
            logger.warning("Failed to click menu item, but continuing...")

        time.sleep(2)

        # Step 3: Find the Run Multiple Plans dialog
        logger.info("Looking for Run Multiple Plans dialog...")

        def find_multiple_plans_dialog():
            for title_pattern in ["Run Multiple Plans", "Multiple Plans", "Compute Multiple"]:
                hwnd = Win32Primitives.find_dialog_by_title(title_pattern)
                if hwnd:
                    return hwnd
            return None

        dialog_hwnd = Win32Primitives.wait_for_window(find_multiple_plans_dialog, timeout=15)

        if dialog_hwnd:
            logger.info(f"Found dialog: {win32gui.GetWindowText(dialog_hwnd)}")

            # Step 4: Try to check all plans
            if check_all:
                logger.info("Attempting to check all plans...")
                check_all_button = None
                for button_text in ["Check All", "Select All", "All"]:
                    check_all_button = Win32Primitives.find_button_by_text(dialog_hwnd, button_text)
                    if check_all_button:
                        logger.info(f"Found '{button_text}' button")
                        Win32Primitives.click_button(check_all_button)
                        time.sleep(0.5)
                        break

                if not check_all_button:
                    logger.warning("Could not find 'Check All' button - plans may need manual selection")

            # Step 5: Click Compute button
            logger.info("Looking for Compute button...")
            time.sleep(1)

            compute_button = None
            for button_text in ["Compute", "Run", "Run All Checked Plans", "Start"]:
                compute_button = Win32Primitives.find_button_by_text(dialog_hwnd, button_text)
                if compute_button:
                    logger.info(f"Found '{button_text}' button")
                    Win32Primitives.click_button(compute_button)
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

        # Step 6: Wait for user to close HEC-RAS (or return immediately)
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
