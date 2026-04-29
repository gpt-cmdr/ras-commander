"""
RASMapper geometry layer command workflows.

Runs RASMapper TreeView context-menu commands such as:
- Cross Sections > Update Cross Sections
- Storage Areas > Compute Elevation-Volume Data
- SA/2D Connections > Update SA/2D Connections
- Inline/Lateral Structures > Update Structures

Geometry updates must be executed from RASMapper opened through Ras.exe. Cold
pythonnet/RasMapperLib calls can load enough API surface to look tempting, but
they do not initialize the full RASMapper geometry-editing context and can fail
when updating geometry-derived attributes.
"""

import time
from typing import Dict, Iterable, List, Sequence, Tuple, Union

try:
    import win32api
    import win32gui
except ImportError:
    win32api = win32gui = None

from ...Decorators import log_call
from ...LoggingConfig import get_logger
from ..constants import Win32Constants
from ..hecras_elements import HecRasElements
from ..rasmapper_elements import RasMapperElements
from ..win32_primitives import Win32Primitives
from ..workflow_base import WorkflowExecutor, WorkflowResult, WorkflowStep

logger = get_logger(__name__)

NodeRef = Union[str, Sequence[str]]


class RasMapperLayerCommandWorkflow:
    """
    Run a RASMapper layer context-menu command through Ras.exe-hosted RASMapper.

    ``geom_number`` selects the RASMapper geometry branch. ``target_node`` then
    selects the node under that geometry to right-click. Public methods are
    one-shot operations: they expect HEC-RAS/RASMapper to be closed, launch
    Ras.exe, run one command, save, and exit.
    """

    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} is a static namespace; call class methods directly")

    TARGET_NODES: Dict[str, Tuple[str, ...]] = {
        "cross_sections": ("Cross Sections",),
        "xs": ("Cross Sections",),
        "storage_areas": ("Storage Areas",),
        "sa": ("Storage Areas",),
        "bridges_culverts": ("Bridges/Culverts",),
        "bridges": ("Bridges/Culverts",),
        "culverts": ("Bridges/Culverts",),
        "inline_structures": ("Inline Structures",),
        "inline": ("Inline Structures",),
        "lateral_structures": ("Lateral Structures",),
        "lateral": ("Lateral Structures",),
        "sa2d_connections": ("SA/2D Connections",),
        "sa_2d_connections": ("SA/2D Connections",),
        "blocked_obstructions": ("Cross Sections", "Blocked Obstructions"),
        "edge_lines": ("Cross Sections", "Edge Lines"),
        "interpolation_surface": ("Cross Sections", "Interpolation Surface"),
    }

    COMMANDS: Dict[str, Tuple[str, ...]] = {
        # Cross sections
        "xs_all_attributes_except_terrain": (
            "Update Cross Sections",
            "All XS Attributes (Except Terrain)",
        ),
        "xs_river_stations_table": ("Update Cross Sections", "River Stations Table"),
        "xs_river_stations": ("Update Cross Sections", "River Stations"),
        "xs_bank_stations": ("Update Cross Sections", "Bank Stations"),
        "xs_reach_lengths": ("Update Cross Sections", "Reach Lengths"),
        "xs_ineffective_flow_areas": ("Update Cross Sections", "Ineffective Flow Areas"),
        "xs_blocked_obstructions": ("Update Cross Sections", "Blocked Obstructions"),
        "xs_mannings_n_values": ("Update Cross Sections", "Manning"),
        "xs_elevation_profiles_from_terrain": (
            "Update Cross Sections",
            "Elevation Profiles from Terrain",
        ),
        "xs_elevation_profiles_from_terrain_overbanks_only": (
            "Update Cross Sections",
            "Elevation Profiles from Terrain (Overbanks Only)",
        ),
        "xs_elevation_profiles_from_terrain_channel_only": (
            "Update Cross Sections",
            "Elevation Profiles from Terrain (Channel Only)",
        ),
        "xs_elevation_profiles_from_points": (
            "Update Cross Sections",
            "Elevation Profiles from Points",
        ),
        "xs_interpolation_surface": ("Compute XS Interpolation Surface",),
        # Storage areas
        "storage_area_elevation_volume": ("Compute Elevation-Volume Data",),
        "storage_area_extract_elevation_volume_curve": ("Extract Elevation-Volume Curve",),
        # Structures
        "bridges_culverts_river_stations": ("Update Bridges/Culverts", "River Stations"),
        "bridges_culverts_elevation_profiles_from_terrain": (
            "Update Bridges/Culverts",
            "Elevation Profiles from Terrain",
        ),
        "inline_river_stations": ("Update Inline Structures", "River Stations"),
        "inline_elevation_profiles_from_terrain": (
            "Update Inline Structures",
            "Elevation Profiles from Terrain",
        ),
        "lateral_river_stations": ("Update Lateral Structures", "River Stations"),
        "lateral_elevation_profiles_from_terrain": (
            "Update Lateral Structures",
            "Elevation Profiles from Terrain",
        ),
        # SA/2D connections
        "sa2d_connection_from_to": ("Update SA/2D Connections", "Connection From/To"),
        "sa2d_elevation_profiles_from_terrain": (
            "Update SA/2D Connections",
            "Elevation Profiles from Terrain",
        ),
        "sa2d_edit_breakline_properties": ("Edit 2D Connection Breakline Properties",),
        "sa2d_enforce_all_as_breaklines": ("Enforce All 2D Connections As Breaklines",),
        # Cross-section helper layers
        "edge_lines_compute": ("Create Edge Lines at XS Limits",),
        "edge_lines_create_at_xs_limits": ("Create Edge Lines at XS Limits",),
        "blocked_obstructions_update_on_xss": ("Update Blocked Obstructions on XSs",),
        "blocked_obstructions_create_polygons_from_xs": (
            "Create Blocked Obstruction Polygons from XS Blocked Obstructions",
        ),
    }

    ALIASES: Dict[str, str] = {
        "all": "xs_all_attributes_except_terrain",
        "all_xs_attributes": "xs_all_attributes_except_terrain",
        "all_xs_attributes_except_terrain": "xs_all_attributes_except_terrain",
        "river_stations": "xs_river_stations_table",
        "river_station_table": "xs_river_stations_table",
        "river_stations_table": "xs_river_stations_table",
        "bank_stations": "xs_bank_stations",
        "reach_lengths": "xs_reach_lengths",
        "ineffective_flow_areas": "xs_ineffective_flow_areas",
        "mannings_n_values": "xs_mannings_n_values",
        "manning": "xs_mannings_n_values",
        "terrain": "xs_elevation_profiles_from_terrain",
        "elevation_profiles": "xs_elevation_profiles_from_terrain",
        "elevation_profiles_from_terrain": "xs_elevation_profiles_from_terrain",
        "overbanks": "xs_elevation_profiles_from_terrain_overbanks_only",
        "channel": "xs_elevation_profiles_from_terrain_channel_only",
        "points": "xs_elevation_profiles_from_points",
        "compute_interpolation_surface": "xs_interpolation_surface",
        "interpolation_surface": "xs_interpolation_surface",
        "compute_edge_lines": "edge_lines_compute",
        "edge_lines": "edge_lines_compute",
        "storage_area_curves": "storage_area_elevation_volume",
        "storage_area_curve": "storage_area_elevation_volume",
        "elevation_volume": "storage_area_elevation_volume",
        "compute_elevation_volume": "storage_area_elevation_volume",
        "connection_from_to": "sa2d_connection_from_to",
        "from_to": "sa2d_connection_from_to",
        "sa2d_terrain": "sa2d_elevation_profiles_from_terrain",
        "blocked_obstructions": "blocked_obstructions_update_on_xss",
    }

    @staticmethod
    @log_call
    def run_command(
        target_node: NodeRef,
        command: Union[str, Sequence[str]],
        geom_number: Union[str, int],
        ras_object=None,
        timeout: int = 600,
    ) -> WorkflowResult:
        """
        Run a context-menu command on a RASMapper TreeView node.

        Args:
            geom_number: Geometry number, such as ``"01"`` or ``1``. Required
                because RASMapper commands are geometry-scoped.
            target_node: Tree node name, target alias, or path. Group nodes run
                group/all-feature commands; individual child names run the same
                command for that feature/layer when RASMapper exposes it.
            command: Command alias/name, or explicit context-menu path.
            ras_object: Optional initialized ``RasPrj``. Defaults to global ras.
            timeout: Maximum seconds for RASMapper open/update waits.
        """
        target_path = RasMapperLayerCommandWorkflow._normalize_target_node(
            target_node,
            geom_number=geom_number,
            ras_object=ras_object,
        )
        menu_path = RasMapperLayerCommandWorkflow._normalize_command_path(command)

        context = {
            "ras_object": ras_object,
            "geom_number": geom_number,
            "timeout": timeout,
            "target_path": target_path,
            "menu_path": menu_path,
            "save_after": True,
            "close_after": True,
        }

        steps = RasMapperLayerCommandWorkflow._build_steps(context)
        try:
            return WorkflowExecutor.execute(
                steps,
                context,
                workflow_name=(
                    f"RASMapperLayerCommand[{target_path[-1]} > {' > '.join(menu_path)}]"
                ),
            )
        finally:
            try:
                RasMapperLayerCommandWorkflow._step_close(context)
            except Exception as exc:
                logger.warning("Cleanup close step failed: %s", exc)

    @staticmethod
    def available_commands() -> Iterable[str]:
        return RasMapperLayerCommandWorkflow.COMMANDS.keys()

    @staticmethod
    @log_call
    def update_storage_area_curves(
        geom_number: Union[str, int],
        target_node: NodeRef = "Storage Areas",
        ras_object=None,
        timeout: int = 600,
    ) -> WorkflowResult:
        """Compute elevation-volume data for all or one Storage Area node."""
        return RasMapperLayerCommandWorkflow.run_command(
            target_node=target_node,
            command="storage_area_elevation_volume",
            geom_number=geom_number,
            ras_object=ras_object,
            timeout=timeout,
        )

    @staticmethod
    @log_call
    def update_sa2d_connections(
        geom_number: Union[str, int],
        command: str = "connection_from_to",
        target_node: NodeRef = "SA/2D Connections",
        ras_object=None,
        timeout: int = 600,
    ) -> WorkflowResult:
        """Update all or one SA/2D Connection node."""
        command_map = {
            "connection_from_to": "sa2d_connection_from_to",
            "from_to": "sa2d_connection_from_to",
            "elevation_profiles_from_terrain": "sa2d_elevation_profiles_from_terrain",
            "terrain": "sa2d_elevation_profiles_from_terrain",
            "edit_breakline_properties": "sa2d_edit_breakline_properties",
            "enforce_all_as_breaklines": "sa2d_enforce_all_as_breaklines",
        }
        normalized = RasMapperLayerCommandWorkflow._normalize_key(command)
        return RasMapperLayerCommandWorkflow.run_command(
            target_node=target_node,
            command=command_map.get(normalized, command),
            geom_number=geom_number,
            ras_object=ras_object,
            timeout=timeout,
        )

    @staticmethod
    @log_call
    def update_structure(
        geom_number: Union[str, int],
        structure_type: str,
        command: str = "river_stations",
        target_node: NodeRef = None,
        ras_object=None,
        timeout: int = 600,
    ) -> WorkflowResult:
        """
        Update bridge/culvert, inline, or lateral structure attributes.

        ``structure_type`` accepts ``bridges_culverts``, ``inline``, or
        ``lateral``. Pass a specific ``target_node`` to run an individual
        structure/layer command when RASMapper exposes that menu.
        """
        structure_key = RasMapperLayerCommandWorkflow._normalize_key(structure_type)
        structure_aliases = {
            "bridge": "bridges_culverts",
            "bridges": "bridges_culverts",
            "culvert": "bridges_culverts",
            "culverts": "bridges_culverts",
            "bridgesculverts": "bridges_culverts",
            "inline": "inline",
            "inline_structures": "inline",
            "lateral": "lateral",
            "lateral_structures": "lateral",
        }
        command_aliases = {
            "river_stations": "river_stations",
            "terrain": "elevation_profiles_from_terrain",
            "elevation_profiles": "elevation_profiles_from_terrain",
            "elevation_profiles_from_terrain": "elevation_profiles_from_terrain",
        }
        structure_key = structure_aliases.get(structure_key, structure_key)
        command_key = command_aliases.get(
            RasMapperLayerCommandWorkflow._normalize_key(command),
            RasMapperLayerCommandWorkflow._normalize_key(command),
        )
        command_name = f"{structure_key}_{command_key}"
        if target_node is None:
            target_node = {
                "bridges_culverts": "Bridges/Culverts",
                "inline": "Inline Structures",
                "lateral": "Lateral Structures",
            }.get(structure_key, structure_type)

        return RasMapperLayerCommandWorkflow.run_command(
            target_node=target_node,
            command=command_name,
            geom_number=geom_number,
            ras_object=ras_object,
            timeout=timeout,
        )

    @staticmethod
    def _normalize_key(value: str) -> str:
        return value.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "")

    @staticmethod
    def _normalize_target_node(
        target_node: NodeRef,
        geom_number: Union[str, int] = None,
        ras_object=None,
    ) -> List[str]:
        if isinstance(target_node, str):
            key = RasMapperLayerCommandWorkflow._normalize_key(target_node)
            if key in RasMapperLayerCommandWorkflow.TARGET_NODES:
                target_path = list(RasMapperLayerCommandWorkflow.TARGET_NODES[key])
            else:
                target_path = [target_node]
        else:
            target_path = [str(part) for part in target_node]

        if geom_number is None:
            return target_path

        geom_node = RasMapperLayerCommandWorkflow._resolve_geometry_tree_node(
            geom_number,
            ras_object=ras_object,
        )
        if target_path and target_path[0].lower() == geom_node.lower():
            return target_path
        return [geom_node, *target_path]

    @staticmethod
    def _resolve_geometry_tree_node(geom_number: Union[str, int], ras_object=None) -> str:
        from ...RasMap import RasMap
        from ...RasPrj import ras
        from ...RasUtils import RasUtils

        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        geom_num = RasUtils.normalize_ras_number(geom_number)

        for geometry in RasMap.list_geometries(ras_obj):
            if str(geometry.get("geom_number", "")) == geom_num:
                name = str(geometry.get("name", "")).strip()
                if name:
                    return name

        geom_df = getattr(ras_obj, "geom_df", None)
        if geom_df is not None and "geom_number" in geom_df:
            matches = geom_df[geom_df["geom_number"].astype(str) == geom_num]
            if not matches.empty:
                title = str(matches.iloc[0].get("geom_title", "") or "").strip()
                if title:
                    return title

        raise ValueError(f"Geometry {geom_num} not found in RASMapper or geom_df")

    @staticmethod
    def _normalize_command(command: str) -> str:
        key = RasMapperLayerCommandWorkflow._normalize_key(command)
        key = RasMapperLayerCommandWorkflow.ALIASES.get(key, key)
        if key not in RasMapperLayerCommandWorkflow.COMMANDS:
            options = ", ".join(RasMapperLayerCommandWorkflow.COMMANDS)
            raise ValueError(f"Unknown RASMapper command '{command}'. Options: {options}")
        return key

    @staticmethod
    def _normalize_command_path(command: Union[str, Sequence[str]]) -> List[str]:
        if isinstance(command, str):
            return list(
                RasMapperLayerCommandWorkflow.COMMANDS[
                    RasMapperLayerCommandWorkflow._normalize_command(command)
                ]
            )
        return [str(part) for part in command]

    @staticmethod
    def _build_steps(context: dict) -> list:
        steps = [
            WorkflowStep(
                name="Verify HEC-RAS is closed",
                action=RasMapperLayerCommandWorkflow._step_verify_hecras_closed,
                max_retries=1,
            ),
            WorkflowStep(
                name="Launch HEC-RAS",
                action=RasMapperLayerCommandWorkflow._step_launch_hecras,
                max_retries=2,
                retry_delay=3.0,
            ),
            WorkflowStep(
                name="Open RASMapper",
                action=RasMapperLayerCommandWorkflow._step_open_rasmapper,
                max_retries=2,
                retry_delay=2.0,
            ),
            WorkflowStep(
                name="Wait for RASMapper",
                action=RasMapperLayerCommandWorkflow._step_wait_for_rasmapper,
                max_retries=1,
                timeout=context.get("timeout", 600),
            ),
            WorkflowStep(
                name="Start geometry editing",
                action=RasMapperLayerCommandWorkflow._step_start_geometry_editing,
                max_retries=2,
                retry_delay=2.0,
                recovery=RasMapperLayerCommandWorkflow._recover_context_menu,
            ),
            WorkflowStep(
                name="Run layer command",
                action=RasMapperLayerCommandWorkflow._step_run_layer_command,
                max_retries=2,
                retry_delay=2.0,
                recovery=RasMapperLayerCommandWorkflow._recover_context_menu,
            ),
            WorkflowStep(
                name="Wait for command to complete",
                action=RasMapperLayerCommandWorkflow._step_wait_for_update,
                max_retries=1,
                timeout=context.get("timeout", 600),
            ),
        ]

        if context.get("save_after", True):
            steps.append(WorkflowStep(
                name="Save geometry",
                action=RasMapperLayerCommandWorkflow._step_save_geometry,
                max_retries=2,
                retry_delay=1.0,
            ))

        return steps

    @staticmethod
    def _step_verify_hecras_closed(context: dict) -> None:
        """
        Ensure this one-shot workflow starts from a closed HEC-RAS desktop.

        RASMapper geometry commands are stateful. Refusing to attach to an
        already-open Ras.exe avoids sending a geometry update to the wrong UI
        session.
        """
        try:
            import psutil
        except ImportError:
            logger.warning("psutil unavailable; skipping HEC-RAS closed preflight")
            return

        running = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if name in {"ras.exe", "rasmapper.exe"}:
                running.append(f"{proc.info.get('name')}[{proc.info.get('pid')}]")

        if running:
            raise RuntimeError(
                "HEC-RAS/RASMapper must be closed before running this one-shot "
                "RASMapper operation. Running processes: " + ", ".join(running)
            )

    @staticmethod
    def _step_launch_hecras(context: dict) -> None:
        process, hwnd = HecRasElements.launch_and_wait(
            ras_object=context.get("ras_object"),
            timeout=30,
        )
        if not hwnd:
            raise RuntimeError("Failed to launch HEC-RAS")
        context["hecras_process"] = process
        context["hecras_hwnd"] = hwnd

    @staticmethod
    def _step_open_rasmapper(context: dict) -> None:
        hwnd = context["hecras_hwnd"]

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        if not HecRasElements.click_menu_by_path(hwnd, ["&GIS Tools", "RAS &Mapper"]):
            logger.info("Trying keyboard shortcut Alt+G, M...")
            Win32Primitives.send_keyboard_shortcut(hwnd, Win32Constants.VK_MENU, ord("G"))
            time.sleep(0.3)
            win32api.keybd_event(ord("M"), 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(ord("M"), 0, Win32Constants.KEYEVENTF_KEYUP, 0)

    @staticmethod
    def _step_wait_for_rasmapper(context: dict) -> None:
        timeout = context.get("timeout", 600)
        result = RasMapperElements.wait_for_rasmapper(timeout=timeout)
        if not result:
            raise RuntimeError("RASMapper did not become responsive")
        context["rasmapper_hwnd"] = result[0]
        context["rasmapper_title"] = result[1]

    @staticmethod
    def _step_run_layer_command(context: dict) -> None:
        from ..treeview_automation import (
            click_context_menu_path_uia,
            find_tree_item,
            find_tree_item_by_path,
            find_treeview_in_window,
            right_click_tree_item,
        )

        rasmapper_hwnd = context["rasmapper_hwnd"]
        target_path = list(context["target_path"])
        menu_path = list(context["menu_path"])

        try:
            win32gui.SetForegroundWindow(rasmapper_hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        tree_hwnd = find_treeview_in_window(rasmapper_hwnd)
        if not tree_hwnd:
            raise RuntimeError("Could not find RASMapper TreeView")

        if len(target_path) == 1:
            target_item = find_tree_item(tree_hwnd, target_path[0])
        else:
            target_item = find_tree_item_by_path(tree_hwnd, target_path)

        if not target_item:
            raise RuntimeError(
                "Could not find RASMapper tree node: " + " > ".join(target_path)
            )

        if not right_click_tree_item(tree_hwnd, target_item):
            raise RuntimeError(
                "Could not open context menu for RASMapper tree node: "
                + " > ".join(target_path)
            )

        time.sleep(0.3)
        if not click_context_menu_path_uia(menu_path, timeout=5.0):
            raise RuntimeError(
                "Could not click RASMapper context menu path: "
                + " > ".join(menu_path)
            )

        logger.info(
            "Triggered RASMapper layer command: %s > %s",
            " > ".join(target_path),
            " > ".join(menu_path),
        )

    @staticmethod
    def _step_start_geometry_editing(context: dict) -> None:
        from ..treeview_automation import click_context_menu_path_uia

        RasMapperLayerCommandWorkflow._open_target_context_menu(context)
        time.sleep(0.3)
        if not click_context_menu_path_uia(["Edit Geometry"], timeout=5.0):
            raise RuntimeError(
                "Could not start RASMapper edit mode for tree node: "
                + " > ".join(context["target_path"])
            )
        logger.info("Started RASMapper geometry edit mode")
        time.sleep(1.0)

    @staticmethod
    def _open_target_context_menu(context: dict) -> None:
        from ..treeview_automation import (
            find_tree_item,
            find_tree_item_by_path,
            find_treeview_in_window,
            right_click_tree_item,
        )

        rasmapper_hwnd = context["rasmapper_hwnd"]
        target_path = list(context["target_path"])

        try:
            win32gui.SetForegroundWindow(rasmapper_hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        tree_hwnd = find_treeview_in_window(rasmapper_hwnd)
        if not tree_hwnd:
            raise RuntimeError("Could not find RASMapper TreeView")

        if len(target_path) == 1:
            target_item = find_tree_item(tree_hwnd, target_path[0])
        else:
            target_item = find_tree_item_by_path(tree_hwnd, target_path)

        if not target_item:
            raise RuntimeError(
                "Could not find RASMapper tree node: " + " > ".join(target_path)
            )

        if not right_click_tree_item(tree_hwnd, target_item):
            raise RuntimeError(
                "Could not open context menu for RASMapper tree node: "
                + " > ".join(target_path)
            )

    @staticmethod
    def _step_wait_for_update(context: dict) -> None:
        rasmapper_hwnd = context["rasmapper_hwnd"]
        timeout = context.get("timeout", 600)

        time.sleep(2)
        if not RasMapperElements.wait_for_rasmapper_idle(rasmapper_hwnd, timeout=timeout):
            logger.warning("RASMapper may still be processing the layer command")

    @staticmethod
    def _step_save_geometry(context: dict) -> None:
        rasmapper_hwnd = context["rasmapper_hwnd"]
        try:
            win32gui.SetForegroundWindow(rasmapper_hwnd)
        except Exception:
            pass
        time.sleep(0.5)

        win32api.keybd_event(0x11, 0, 0, 0)  # Ctrl down
        time.sleep(0.05)
        win32api.keybd_event(ord("S"), 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(ord("S"), 0, Win32Constants.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x11, 0, Win32Constants.KEYEVENTF_KEYUP, 0)
        logger.info("Sent Ctrl+S to RASMapper")

    @staticmethod
    def _step_close(context: dict) -> None:
        rasmapper_hwnd = context.get("rasmapper_hwnd")
        hecras_hwnd = context.get("hecras_hwnd")
        hecras_process = context.get("hecras_process")

        if rasmapper_hwnd:
            Win32Primitives.close_window(rasmapper_hwnd)
            time.sleep(2)

        HecRasElements.dismiss_save_prompt(timeout=3)

        if hecras_hwnd:
            Win32Primitives.close_window(hecras_hwnd)

        if hecras_process:
            try:
                hecras_process.wait(timeout=10)
            except Exception:
                pass

    @staticmethod
    def _recover_context_menu(context: dict) -> None:
        from ..treeview_automation import dismiss_context_menu

        dismiss_context_menu()


class RasMapperXsecUpdateWorkflow:
    """Compatibility wrapper for 1D Cross Sections update commands."""

    def __new__(cls, *args, **kwargs):
        raise TypeError(f"{cls.__name__} is a static namespace; call class methods directly")

    UPDATE_COMMANDS: Dict[str, Tuple[str, ...]] = {
        key.removeprefix("xs_"): value
        for key, value in RasMapperLayerCommandWorkflow.COMMANDS.items()
        if key.startswith("xs_")
    }

    @staticmethod
    @log_call
    def update_cross_sections(
        geom_number: Union[str, int],
        command: str = "all_xs_attributes_except_terrain",
        target_node: NodeRef = "Cross Sections",
        ras_object=None,
        timeout: int = 600,
    ) -> WorkflowResult:
        """
        Run a 1D cross-section update command through RASMapper.

        ``geom_number`` selects the geometry branch. ``target_node`` defaults
        to the Cross Sections group for all XSs. Pass a specific child node/path
        when RASMapper exposes an individual feature command for that node.
        """
        normalized = RasMapperXsecUpdateWorkflow._normalize_command(command)
        return RasMapperLayerCommandWorkflow.run_command(
            target_node=target_node,
            command=f"xs_{normalized}",
            geom_number=geom_number,
            ras_object=ras_object,
            timeout=timeout,
        )

    @staticmethod
    def available_commands() -> Iterable[str]:
        return RasMapperXsecUpdateWorkflow.UPDATE_COMMANDS.keys()

    @staticmethod
    def _normalize_command(command: str) -> str:
        try:
            key = RasMapperLayerCommandWorkflow._normalize_command(command)
        except ValueError as exc:
            options = ", ".join(RasMapperXsecUpdateWorkflow.UPDATE_COMMANDS)
            raise ValueError(
                f"Unknown cross-section update command '{command}'. Options: {options}"
            ) from exc
        if key.startswith("xs_"):
            key = key.removeprefix("xs_")
        if key not in RasMapperXsecUpdateWorkflow.UPDATE_COMMANDS:
            options = ", ".join(RasMapperXsecUpdateWorkflow.UPDATE_COMMANDS)
            raise ValueError(
                f"Unknown cross-section update command '{command}'. Options: {options}"
            )
        return key
