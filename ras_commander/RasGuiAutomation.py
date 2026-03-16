"""
RasGuiAutomation - Backward compatibility shim.

This module has been refactored into the gui/ subpackage.
All functionality is preserved. Import from ras_commander.gui for new code.

Deprecated: Use ras_commander.gui classes directly:
    - Win32Primitives (Layer 1: generic Win32 ops)
    - HecRasElements (Layer 2: HEC-RAS specific finders)
    - RasMapperElements (Layer 2b: RASMapper specific finders)
    - OpenAndComputeWorkflow, RunMultiplePlansWorkflow, etc. (Layer 3: workflows)
"""

import warnings
from typing import Optional, List, Tuple, Callable, Any

from .gui.win32_primitives import Win32Primitives
from .gui.hecras_elements import HecRasElements
from .gui.workflows.open_compute import OpenAndComputeWorkflow
from .gui.workflows.run_multiple_plans import RunMultiplePlansWorkflow
from .gui.workflows.open_rasmapper import OpenRasMapperWorkflow


class RasGuiAutomation:
    """
    Backward compatibility shim for GUI automation.

    All methods delegate to the gui/ subpackage. New code should import
    from ras_commander.gui directly.
    """

    # --- Layer 1: Win32 Primitives ---

    @staticmethod
    def get_windows_by_pid(pid: int) -> List[Tuple[int, str]]:
        return Win32Primitives.get_windows_by_pid(pid)

    @staticmethod
    def get_menu_string(menu_handle: int, pos: int) -> str:
        return Win32Primitives.get_menu_string(menu_handle, pos)

    @staticmethod
    def enumerate_all_menus(hwnd: int) -> dict:
        return Win32Primitives.enumerate_all_menus(hwnd)

    @staticmethod
    def click_menu_item(hwnd: int, menu_id: int) -> bool:
        return Win32Primitives.click_menu_item(hwnd, menu_id)

    @staticmethod
    def find_dialog_by_title(title_pattern: str, exact_match: bool = False) -> Optional[int]:
        return Win32Primitives.find_dialog_by_title(title_pattern, exact_match)

    @staticmethod
    def find_button_by_text(dialog_hwnd: int, button_text: str) -> Optional[int]:
        return Win32Primitives.find_button_by_text(dialog_hwnd, button_text)

    @staticmethod
    def click_button(button_hwnd: int) -> bool:
        return Win32Primitives.click_button(button_hwnd)

    @staticmethod
    def find_combobox_by_neighbor(hwnd: int, neighbor_text: str) -> Optional[int]:
        return Win32Primitives.find_combobox_by_neighbor(hwnd, neighbor_text)

    @staticmethod
    def select_combobox_item_by_text(combo_hwnd: int, item_text: str) -> bool:
        return Win32Primitives.select_combobox_item_by_text(combo_hwnd, item_text)

    @staticmethod
    def close_window(hwnd: int) -> bool:
        return Win32Primitives.close_window(hwnd)

    @staticmethod
    def wait_for_window(find_window_func: Callable, timeout: int = 60, check_interval: int = 2) -> Any:
        return Win32Primitives.wait_for_window(find_window_func, timeout, check_interval)

    # --- Layer 2: HEC-RAS Elements ---

    @staticmethod
    def find_main_hecras_window(windows: List[Tuple[int, str]]) -> Tuple[Optional[int], Optional[str]]:
        return HecRasElements.find_main_hecras_window(windows)

    @staticmethod
    def handle_already_running_dialog(timeout: int = 5) -> bool:
        return HecRasElements.handle_already_running_dialog(timeout)

    @staticmethod
    def set_current_plan(hwnd: int, plan_number: str, ras_object=None) -> bool:
        return HecRasElements.set_current_plan(hwnd, plan_number, ras_object)

    # --- Layer 3: Workflows ---

    @staticmethod
    def open_and_compute(
        plan_number: str,
        ras_object=None,
        auto_click_compute: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        return OpenAndComputeWorkflow.run(
            plan_number=plan_number,
            ras_object=ras_object,
            auto_click_compute=auto_click_compute,
            wait_for_user=wait_for_user,
        )

    @staticmethod
    def run_multiple_plans(
        plan_numbers: Optional[List[str]] = None,
        ras_object=None,
        check_all: bool = True,
        wait_for_user: bool = True
    ) -> bool:
        return RunMultiplePlansWorkflow.run(
            plan_numbers=plan_numbers,
            ras_object=ras_object,
            check_all=check_all,
            wait_for_user=wait_for_user,
        )

    @staticmethod
    def open_rasmapper(
        ras_object=None,
        wait_for_user: bool = True,
        timeout: int = 300
    ) -> bool:
        return OpenRasMapperWorkflow.run(
            ras_object=ras_object,
            wait_for_user=wait_for_user,
            timeout=timeout,
        )
