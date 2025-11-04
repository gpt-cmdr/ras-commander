"""
RasControl - HECRASController API Wrapper (ras-commander style)

Provides ras-commander style API for legacy HEC-RAS versions (3.x-4.x)
that use HECRASController COM interface instead of HDF files.

Public functions:
- RasControl.run_plan(plan: Union[str, Path], ras_object: Optional[Any] = None) -> Tuple[bool, List[str]]
- RasControl.get_steady_results(plan: Union[str, Path], ras_object: Optional[Any] = None) -> pandas.DataFrame
- RasControl.get_unsteady_results(plan: Union[str, Path], max_times: Optional[int] = None, ras_object: Optional[Any] = None) -> pandas.DataFrame
- RasControl.get_output_times(plan: Union[str, Path], ras_object: Optional[Any] = None) -> List[str]
- RasControl.get_plans(plan: Union[str, Path], ras_object: Optional[Any] = None) -> List[dict]
- RasControl.set_current_plan(plan: Union[str, Path], ras_object: Optional[Any] = None) -> bool
- RasControl.get_comp_msgs(plan: Union[str, Path], ras_object: Optional[Any] = None) -> str

Private functions:
- _terminate_ras_process() -> None
- _is_ras_running() -> bool
- RasControl._normalize_version(version: str) -> str
- RasControl._get_project_info(plan: Union[str, Path], ras_object: Optional[Any] = None) -> Tuple[Path, str, Optional[str], Optional[str]]
- RasControl._com_open_close(project_path: Path, version: str, operation_func: Callable[[Any], Any]) -> Any

"""

import win32com.client
import psutil
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Any, Union
import logging
import time

logger = logging.getLogger(__name__)

# Import ras-commander components
from .RasPrj import ras


def _terminate_ras_process() -> None:
    """Force terminate any running ras.exe processes."""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'ras.exe':
                proc.terminate()
                proc.wait(timeout=3)
                logger.info("Terminated ras.exe process")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass


def _is_ras_running() -> bool:
    """Check if HEC-RAS is currently running"""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'ras.exe':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


class RasControl:
    """
    HECRASController API wrapper with ras-commander style interface.

    Works with legacy HEC-RAS versions (3.x-4.x) that use COM interface
    instead of HDF files. Integrates with ras-commander project management.

    Usage (ras-commander style):
        >>> from ras_commander import init_ras_project, RasControl
        >>>
        >>> # Initialize with version (with or without periods)
        >>> init_ras_project(path, "4.1")  # or "41"
        >>>
        >>> # Use plan numbers like HDF methods
        >>> RasControl.run_plan("02")
        >>> df = RasControl.get_steady_results("02")

    Supported Versions:
        All installed versions: 3.x, 4.x, 5.0.x, 6.0-6.7+
        Accepts formats: "4.1", "41", "5.0.6", "506", "6.6", "66", etc.
    """

    # Version mapping based on ACTUAL COM interfaces registered on system
    # Only these COM interfaces exist: RAS41, RAS503, RAS505, RAS506, RAS507,
    # RAS60, RAS631, RAS641, RAS65, RAS66, RAS67
    # Other versions use nearest available fallback
    VERSION_MAP = {
        # HEC-RAS 3.x → Use 4.1 (3.x COM not registered)
        '3.0': 'RAS41.HECRASController',
        '30': 'RAS41.HECRASController',
        '3.1': 'RAS41.HECRASController',
        '31': 'RAS41.HECRASController',
        '3.1.1': 'RAS41.HECRASController',
        '311': 'RAS41.HECRASController',
        '3.1.2': 'RAS41.HECRASController',
        '312': 'RAS41.HECRASController',
        '3.1.3': 'RAS41.HECRASController',
        '313': 'RAS41.HECRASController',

        # HEC-RAS 4.x
        '4.0': 'RAS41.HECRASController',    # Use 4.1 (4.0 COM not registered)
        '40': 'RAS41.HECRASController',
        '4.1': 'RAS41.HECRASController',    # ✓ EXISTS
        '41': 'RAS41.HECRASController',
        '4.1.0': 'RAS41.HECRASController',
        '410': 'RAS41.HECRASController',

        # HEC-RAS 5.0.x
        '5.0': 'RAS503.HECRASController',   # Use 5.0.3 (RAS50 COM not registered)
        '50': 'RAS503.HECRASController',
        '5.0.1': 'RAS501.HECRASController', # ✓ EXISTS
        '501': 'RAS501.HECRASController',
        '5.0.3': 'RAS503.HECRASController', # ✓ EXISTS
        '503': 'RAS503.HECRASController',
        '5.0.4': 'RAS504.HECRASController', # ✓ EXISTS (newly installed)
        '504': 'RAS504.HECRASController',
        '5.0.5': 'RAS505.HECRASController', # ✓ EXISTS
        '505': 'RAS505.HECRASController',
        '5.0.6': 'RAS506.HECRASController', # ✓ EXISTS
        '506': 'RAS506.HECRASController',
        '5.0.7': 'RAS507.HECRASController', # ✓ EXISTS
        '507': 'RAS507.HECRASController',

        # HEC-RAS 6.x
        '6.0': 'RAS60.HECRASController',    # ✓ EXISTS
        '60': 'RAS60.HECRASController',
        '6.1': 'RAS60.HECRASController',    # Use 6.0 (6.1 COM not registered)
        '61': 'RAS60.HECRASController',
        '6.2': 'RAS60.HECRASController',    # Use 6.0 (6.2 COM not registered)
        '62': 'RAS60.HECRASController',
        '6.3': 'RAS631.HECRASController',   # Use 6.3.1 (6.3 COM not registered)
        '63': 'RAS631.HECRASController',
        '6.3.1': 'RAS631.HECRASController', # ✓ EXISTS
        '631': 'RAS631.HECRASController',
        '6.4': 'RAS641.HECRASController',   # Use 6.4.1 (6.4 COM not registered)
        '64': 'RAS641.HECRASController',
        '6.4.1': 'RAS641.HECRASController', # ✓ EXISTS
        '641': 'RAS641.HECRASController',
        '6.5': 'RAS65.HECRASController',    # ✓ EXISTS
        '65': 'RAS65.HECRASController',
        '6.6': 'RAS66.HECRASController',    # ✓ EXISTS
        '66': 'RAS66.HECRASController',
        '6.7': 'RAS67.HECRASController',    # ✓ EXISTS
        '67': 'RAS67.HECRASController',
        '6.7 Beta 4': 'RAS67.HECRASController',
    }

    # Legacy reference (kept for backwards compatibility)
    SUPPORTED_VERSIONS = VERSION_MAP

    # Output variable codes
    WSEL = 2
    ENERGY = 3
    MAX_CHL_DPTH = 4
    MIN_CH_EL = 5
    ENERGY_SLOPE = 6
    FLOW_TOTAL = 24
    VEL_TOTAL = 25
    STA_WS_LFT = 36
    STA_WS_RGT = 37
    FROUDE_CHL = 48
    FROUDE_XS = 49
    Q_WEIR = 94
    Q_CULVERT_TOT = 242

    # ========== PRIVATE METHODS (HECRASController COM API) ==========

    @staticmethod
    def _normalize_version(version: str) -> str:
        """
        Normalize version string to match VERSION_MAP keys.

        Handles formats like:
            "6.6", "66" → "6.6"
            "4.1", "41" → "4.1"
            "5.0.6", "506" → "5.0.6"
            "6.7 Beta 4" → "6.7 Beta 4"

        Returns:
            Normalized version string that exists in VERSION_MAP

        Raises:
            ValueError: If version cannot be normalized or is not supported
        """
        version_str = str(version).strip()

        # Direct match
        if version_str in RasControl.VERSION_MAP:
            return version_str

        # Try common normalizations
        normalized_candidates = [
            version_str,
            version_str.replace('.', ''),  # "6.6" → "66"
        ]

        # Try adding periods for compact formats
        if len(version_str) == 2:  # "66" → "6.6"
            normalized_candidates.append(f"{version_str[0]}.{version_str[1]}")
        elif len(version_str) == 3 and version_str.startswith('5'):  # "506" → "5.0.6"
            normalized_candidates.append(f"5.0.{version_str[2]}")
        elif len(version_str) == 3:  # "631" → "6.3.1"
            normalized_candidates.append(f"{version_str[0]}.{version_str[1]}.{version_str[2]}")

        # Check all candidates
        for candidate in normalized_candidates:
            if candidate in RasControl.VERSION_MAP:
                logger.debug(f"Normalized version '{version}' → '{candidate}'")
                return candidate

        # Not found
        raise ValueError(
            f"Version '{version}' not supported. Supported versions:\n"
            f"  3.x: 3.0, 3.1 (3.1.1, 3.1.2, 3.1.3)\n"
            f"  4.x: 4.0, 4.1\n"
            f"  5.0.x: 5.0, 5.0.1, 5.0.3, 5.0.4, 5.0.5, 5.0.6, 5.0.7\n"
            f"  6.x: 6.0, 6.1, 6.2, 6.3, 6.3.1, 6.4, 6.4.1, 6.5, 6.6, 6.7\n"
            f"  Formats: Can use '6.6' or '66', '5.0.6' or '506', etc."
        )

    @staticmethod
    def _get_project_info(plan: Union[str, Path], ras_object=None):
        """
        Resolve plan number/path to project path, version, and plan details.

        Returns:
            Tuple[Path, str, str, str]: (project_path, version, plan_number, plan_name)
            plan_number and plan_name are None if using direct .prj path
        """
        if ras_object is None:
            ras_object = ras

        # If it's a path to .prj file
        plan_path = Path(plan) if isinstance(plan, str) else plan
        if plan_path.exists() and plan_path.suffix == '.prj':
            # Direct path - need version from ras_object
            if not hasattr(ras_object, 'ras_version') or not ras_object.ras_version:
                raise ValueError(
                    "When using direct .prj paths, project must be initialized with version.\n"
                    "Use: init_ras_project(path, '4.1') or similar"
                )
            return plan_path, ras_object.ras_version, None, None

        # Otherwise treat as plan number
        plan_num = str(plan).zfill(2)

        # Get project path from ras_object
        if not hasattr(ras_object, 'prj_file') or not ras_object.prj_file:
            raise ValueError(
                "No project initialized. Use init_ras_project() first.\n"
                "Example: init_ras_project(path, '4.1')"
            )

        project_path = Path(ras_object.prj_file)

        # Get version
        if not hasattr(ras_object, 'ras_version') or not ras_object.ras_version:
            raise ValueError(
                "Project initialized without version. Re-initialize with:\n"
                "init_ras_project(path, '4.1')  # or '41', '501', etc."
            )

        version = ras_object.ras_version

        # Get plan name from plan_df
        plan_row = ras_object.plan_df[ras_object.plan_df['plan_number'] == plan_num]
        if plan_row.empty:
            raise ValueError(f"Plan '{plan_num}' not found in project")

        plan_name = plan_row['Plan Title'].iloc[0]

        return project_path, version, plan_num, plan_name

    @staticmethod
    def _com_open_close(project_path: Path, version: str, operation_func: Callable[[Any], Any]) -> Any:
        """
        PRIVATE: Open HEC-RAS via COM, run operation, close HEC-RAS.

        This is the core COM interface handler. All public methods use this.
        """
        # Normalize version (handles "6.6" → "6.6", "66" → "6.6", etc.)
        normalized_version = RasControl._normalize_version(version)

        if not project_path.exists():
            raise FileNotFoundError(f"Project file not found: {project_path}")

        com_rc = None
        result = None

        try:
            # Open HEC-RAS COM interface
            com_string = RasControl.VERSION_MAP[normalized_version]
            logger.info(f"Opening HEC-RAS: {com_string} (version: {version})")
            com_rc = win32com.client.Dispatch(com_string)

            # Open project
            logger.info(f"Opening project: {project_path}")
            com_rc.Project_Open(str(project_path))

            # Perform operation
            logger.info("Executing operation...")
            result = operation_func(com_rc)
            logger.info("Operation completed successfully")

            return result

        except Exception as e:
            logger.error(f"Operation failed: {e}")
            raise

        finally:
            # ALWAYS close
            logger.info("Closing HEC-RAS...")

            if com_rc is not None:
                try:
                    com_rc.QuitRas()
                    logger.info("HEC-RAS closed via QuitRas()")
                except Exception as e:
                    logger.warning(f"QuitRas() failed: {e}")

            _terminate_ras_process()

            if _is_ras_running():
                logger.warning("HEC-RAS may still be running!")
            else:
                logger.info("HEC-RAS fully closed")

    # ========== PUBLIC API (ras-commander style) ==========

    @staticmethod
    def run_plan(plan: Union[str, Path], ras_object=None, force_recompute: bool = False) -> Tuple[bool, List[str]]:
        """
        Run a plan (steady or unsteady) and wait for completion.

        This method checks if results are current before running. If results
        are up-to-date, it skips computation (unless force_recompute=True).
        When computation is needed, it starts the computation and polls
        Compute_Complete() until the run finishes. It will block until completion.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)
            force_recompute: If False (default), checks if results are current
                before running. If results are up-to-date, skips computation.
                If True, always runs the plan regardless of current status.
                Defaults to False.

        Returns:
            Tuple of (success: bool, messages: List[str])

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> # Default: skips computation if results are current
            >>> success, msgs = RasControl.run_plan("02")
            >>> # Force recomputation even if results are current
            >>> success, msgs = RasControl.run_plan("02", force_recompute=True)

        Note:
            Can take several minutes for large models or unsteady runs.
            Progress is logged every 30 seconds.
            If PlanOutput_IsCurrent() check fails (e.g., older HEC-RAS versions),
            the plan will be run as a safe fallback.
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _run_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            # Check if results are current (unless force_recompute=True)
            if not force_recompute:
                try:
                    is_current = com_rc.PlanOutput_IsCurrent()
                    if is_current:
                        logger.info(f"Plan {plan_num} results are current. Skipping computation.")
                        logger.info("Use force_recompute=True to recompute anyway.")
                        return True, ["Results are current - computation skipped"]
                except Exception as e:
                    logger.warning(f"Could not check PlanOutput_IsCurrent(): {e}")
                    logger.warning("Proceeding with computation...")

            # Version-specific behavior (normalize for checking)
            norm_version = RasControl._normalize_version(version)

            # Start computation (returns immediately - ASYNCHRONOUS!)
            logger.info("Starting computation...")
            if norm_version.startswith('4') or norm_version.startswith('3'):
                status, _, messages = com_rc.Compute_CurrentPlan(None, None)
            else:
                status, _, messages, _ = com_rc.Compute_CurrentPlan(None, None)

            # CRITICAL: Wait for computation to complete
            # Compute_CurrentPlan is ASYNCHRONOUS - it returns before computation finishes
            logger.info("Waiting for computation to complete...")
            poll_count = 0
            while True:
                try:
                    # Check if computation is complete
                    is_complete = com_rc.Compute_Complete()

                    if is_complete:
                        logger.info(f"Computation completed (polled {poll_count} times)")
                        break

                    # Still computing - wait and poll again
                    time.sleep(1)  # Poll every second
                    poll_count += 1

                    # Log progress every 30 seconds
                    if poll_count % 30 == 0:
                        logger.info(f"Still computing... ({poll_count} seconds elapsed)")

                except Exception as e:
                    logger.error(f"Error checking completion status: {e}")
                    # If we can't check status, break and hope for the best
                    break

            return status, list(messages) if messages else []

        return RasControl._com_open_close(project_path, version, _run_operation)

    @staticmethod
    def get_steady_results(plan: Union[str, Path], ras_object=None) -> pd.DataFrame:
        """
        Extract steady state profile results.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            DataFrame with columns: river, reach, node_id, profile, wsel,
            velocity, flow, froude, energy, max_depth, min_ch_el

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> df = RasControl.get_steady_results("02")
            >>> df.to_csv('results.csv', index=False)
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            results = []
            error_logged = False  # Track if we've already logged comp_msgs

            # Get profiles
            _, profile_names = com_rc.Output_GetProfiles(2, None)

            if profile_names is None:
                raise RuntimeError(
                    "No steady state results found. Please ensure:\n"
                    "  1. The model has been run (use RasControl.run_plan() first)\n"
                    "  2. The current plan is a steady state plan\n"
                    "  3. Results were successfully computed"
                )

            profiles = [{'name': name, 'code': i+1} for i, name in enumerate(profile_names)]
            logger.info(f"Found {len(profiles)} profiles")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.info(f"Found {len(river_names)} rivers")

            # Extract data
            for riv_code, riv_name in enumerate(river_names, start=1):
                _, _, reach_names = com_rc.Geometry_GetReaches(riv_code, None, None)

                for rch_code, rch_name in enumerate(reach_names, start=1):
                    _, _, _, node_ids, node_types = com_rc.Geometry_GetNodes(
                        riv_code, rch_code, None, None, None
                    )

                    for node_code, (node_id, node_type) in enumerate(
                        zip(node_ids, node_types), start=1
                    ):
                        if node_type == '':  # Cross sections only
                            for profile in profiles:
                                try:
                                    row = {
                                        'river': riv_name.strip(),
                                        'reach': rch_name.strip(),
                                        'node_id': node_id.strip(),
                                        'profile': profile['name'].strip(),
                                    }

                                    # Extract output variables
                                    row['wsel'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.WSEL
                                    )[0]

                                    row['min_ch_el'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.MIN_CH_EL
                                    )[0]

                                    row['velocity'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.VEL_TOTAL
                                    )[0]

                                    row['flow'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.FLOW_TOTAL
                                    )[0]

                                    row['froude'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.FROUDE_CHL
                                    )[0]

                                    row['energy'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.ENERGY
                                    )[0]

                                    row['max_depth'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        profile['code'], RasControl.MAX_CHL_DPTH
                                    )[0]

                                    results.append(row)

                                except Exception as e:
                                    if not error_logged:
                                        # First error - read and log comp_msgs to diagnose issue
                                        logger.error(
                                            f"Failed to extract results at {riv_name}/{rch_name}/{node_id} "
                                            f"profile {profile['name']}: {e}"
                                        )
                                        logger.error(
                                            "This usually indicates the model run was not successful or "
                                            "results are invalid. Reading computation messages..."
                                        )

                                        # Read comp_msgs file
                                        try:
                                            project_base = project_path.stem
                                            plan_file = project_path.parent / f"{project_base}.p{plan_num}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                logger.error(f"\n{'='*80}\nCOMPUTATION MESSAGES:\n{'='*80}\n{comp_msgs}\n{'='*80}")
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.info("Suppressing further extraction warnings...")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.info(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(project_path, version, _extract_operation)

    @staticmethod
    def get_unsteady_results(plan: Union[str, Path], max_times: int = None,
                            ras_object=None) -> pd.DataFrame:
        """
        Extract unsteady flow time series results.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            max_times: Optional limit on timesteps (for testing/large datasets)
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            DataFrame with columns: river, reach, node_id, time_index, time_string,
            wsel, velocity, flow, froude, energy, max_depth, min_ch_el

        Important - Understanding "Max WS":
            The first row (time_index=1, time_string="Max WS") contains the MAXIMUM
            values that occurred at ANY computational timestep during the simulation,
            not just at output intervals. This is critical data for identifying peaks.

            For time series plotting, filter to actual timesteps:
                df_timeseries = df[df['time_string'] != 'Max WS']

            For showing maximum as reference line:
                max_wse = df[df['time_string'] == 'Max WS']['wsel'].iloc[0]
                plt.axhline(max_wse, color='r', linestyle='--', label='Max WS')

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> df = RasControl.get_unsteady_results("01", max_times=10)
            >>> # Includes "Max WS" as first row
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _extract_operation(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            results = []
            error_logged = False  # Track if we've already logged comp_msgs

            # Get output times
            _, time_strings = com_rc.Output_GetProfiles(0, None)

            if time_strings is None:
                raise RuntimeError(
                    "No unsteady results found. Please ensure:\n"
                    "  1. The model has been run (use RasControl.run_plan() first)\n"
                    "  2. The current plan is an unsteady flow plan\n"
                    "  3. Results were successfully computed"
                )

            times = list(time_strings)
            if max_times:
                times = times[:max_times]

            logger.info(f"Extracting {len(times)} time steps")

            # Get rivers
            _, river_names = com_rc.Output_GetRivers(0, None)

            if river_names is None:
                raise RuntimeError("No river geometry found in model.")

            logger.info(f"Found {len(river_names)} rivers")

            # Extract data
            for riv_code, riv_name in enumerate(river_names, start=1):
                _, _, reach_names = com_rc.Geometry_GetReaches(riv_code, None, None)

                for rch_code, rch_name in enumerate(reach_names, start=1):
                    _, _, _, node_ids, node_types = com_rc.Geometry_GetNodes(
                        riv_code, rch_code, None, None, None
                    )

                    for node_code, (node_id, node_type) in enumerate(
                        zip(node_ids, node_types), start=1
                    ):
                        if node_type == '':  # Cross sections only
                            for time_idx, time_str in enumerate(times, start=1):
                                try:
                                    row = {
                                        'river': riv_name.strip(),
                                        'reach': rch_name.strip(),
                                        'node_id': node_id.strip(),
                                        'time_index': time_idx,
                                        'time_string': time_str.strip(),
                                    }

                                    # Extract output variables (time_idx is profile code for unsteady)
                                    row['wsel'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.WSEL
                                    )[0]

                                    row['min_ch_el'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.MIN_CH_EL
                                    )[0]

                                    row['velocity'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.VEL_TOTAL
                                    )[0]

                                    row['flow'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.FLOW_TOTAL
                                    )[0]

                                    row['froude'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.FROUDE_CHL
                                    )[0]

                                    row['energy'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.ENERGY
                                    )[0]

                                    row['max_depth'] = com_rc.Output_NodeOutput(
                                        riv_code, rch_code, node_code, 0,
                                        time_idx, RasControl.MAX_CHL_DPTH
                                    )[0]

                                    results.append(row)

                                except Exception as e:
                                    if not error_logged:
                                        # First error - read and log comp_msgs to diagnose issue
                                        logger.error(
                                            f"Failed to extract results at {riv_name}/{rch_name}/{node_id} "
                                            f"time {time_str}: {e}"
                                        )
                                        logger.error(
                                            "This usually indicates the model run was not successful or "
                                            "results are invalid. Reading computation messages..."
                                        )

                                        # Read comp_msgs file
                                        try:
                                            project_base = project_path.stem
                                            plan_file = project_path.parent / f"{project_base}.p{plan_num}"
                                            comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

                                            if comp_msgs_file.exists():
                                                with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
                                                    comp_msgs = f.read()
                                                logger.error(f"\n{'='*80}\nCOMPUTATION MESSAGES:\n{'='*80}\n{comp_msgs}\n{'='*80}")
                                            else:
                                                logger.error(f"Computation messages file not found: {comp_msgs_file}")
                                        except Exception as msg_error:
                                            logger.error(f"Could not read computation messages: {msg_error}")

                                        error_logged = True
                                        logger.info("Suppressing further extraction warnings...")

            if error_logged and len(results) == 0:
                raise RuntimeError(
                    "Failed to extract any results. The model run likely failed or produced invalid results. "
                    "Check the computation messages above for details."
                )

            logger.info(f"Extracted {len(results)} result rows")
            return pd.DataFrame(results)

        return RasControl._com_open_close(project_path, version, _extract_operation)

    @staticmethod
    def get_output_times(plan: Union[str, Path], ras_object=None) -> List[str]:
        """
        Get list of output times for unsteady run.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            List of time strings (e.g., ["01JAN2000 0000", ...])

        Example:
            >>> times = RasControl.get_output_times("01")
            >>> print(f"Found {len(times)} output times")
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        def _get_times(com_rc):
            # Set current plan if we have plan_name (using plan number)
            if plan_name:
                logger.info(f"Setting current plan to: {plan_name}")
                com_rc.Plan_SetCurrent(plan_name)

            _, time_strings = com_rc.Output_GetProfiles(0, None)

            if time_strings is None:
                raise RuntimeError(
                    "No unsteady output times found. Ensure plan has been run."
                )

            times = list(time_strings)
            logger.info(f"Found {len(times)} output times")
            return times

        return RasControl._com_open_close(project_path, version, _get_times)

    @staticmethod
    def get_plans(plan: Union[str, Path], ras_object=None) -> List[dict]:
        """
        Get list of plans in project.

        Args:
            plan: Plan number or path to .prj file
            ras_object: Optional RasPrj instance

        Returns:
            List of dicts with 'name' and 'filename' keys
        """
        project_path, version, _, _ = RasControl._get_project_info(plan, ras_object)

        def _get_plans(com_rc):
            # Don't set current plan - just getting list
            _, plan_names, _ = com_rc.Plan_Names(None, None, None)

            plans = []
            for name in plan_names:
                filename, _ = com_rc.Plan_GetFilename(name)
                plans.append({'name': name, 'filename': filename})

            logger.info(f"Found {len(plans)} plans")
            return plans

        return RasControl._com_open_close(project_path, version, _get_plans)

    @staticmethod
    def set_current_plan(plan: Union[str, Path], ras_object=None) -> bool:
        """
        Set the current/active plan by plan number.

        Note: This is rarely needed - run_plan() and get_*_results()
        automatically set the correct plan. This is provided for
        advanced use cases.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance

        Returns:
            True if successful

        Example:
            >>> RasControl.set_current_plan("02")  # Set to Plan 02
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        if not plan_name:
            raise ValueError("Cannot set current plan - plan name could not be determined")

        def _set_plan(com_rc):
            com_rc.Plan_SetCurrent(plan_name)
            logger.info(f"Set current plan to Plan {plan_num}: {plan_name}")
            return True

        return RasControl._com_open_close(project_path, version, _set_plan)

    @staticmethod
    def get_comp_msgs(plan: Union[str, Path], ras_object=None) -> str:
        """
        Read computation messages from the .comp_msgs.txt file.

        The comp_msgs file is created by HEC-RAS during plan computation
        and contains detailed messages about the computation process,
        including warnings, errors, and convergence information.

        Args:
            plan: Plan number ("01", "02") or path to .prj file
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            String containing computation messages

        Raises:
            FileNotFoundError: If comp_msgs file doesn't exist

        Example:
            >>> from ras_commander import init_ras_project, RasControl
            >>> init_ras_project(path, "4.1")
            >>> msgs = RasControl.get_comp_msgs("08")
            >>> print(msgs)

        Note:
            The file naming convention is: {plan_file}.comp_msgs.txt
            For example, if plan file is A100_00_00.p08, the comp_msgs
            file will be A100_00_00.p08.comp_msgs.txt
        """
        project_path, version, plan_num, plan_name = RasControl._get_project_info(plan, ras_object)

        # Construct plan file path
        # e.g., "A100_00_00.prj" -> "A100_00_00"
        project_base = project_path.stem
        plan_file = project_path.parent / f"{project_base}.p{plan_num}"

        # Construct comp_msgs file path
        comp_msgs_file = Path(str(plan_file) + ".comp_msgs.txt")

        if not comp_msgs_file.exists():
            raise FileNotFoundError(
                f"Computation messages file not found: {comp_msgs_file}\n"
                f"This file is created when HEC-RAS runs a plan.\n"
                f"Ensure the plan has been computed before reading messages."
            )

        logger.info(f"Reading computation messages from: {comp_msgs_file}")

        # Read and return contents
        with open(comp_msgs_file, 'r', encoding='utf-8', errors='ignore') as f:
            contents = f.read()

        logger.info(f"Read {len(contents)} characters from comp_msgs file")
        return contents


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("RasControl (ras-commander API) loaded successfully")
    print(f"Supported versions: {list(RasControl.SUPPORTED_VERSIONS.keys())}")
    print("\nUsage example:")
    print("  from ras_commander import init_ras_project, RasControl")
    print("  init_ras_project(path, '4.1')")
    print("  df = RasControl.get_steady_results('02')")
