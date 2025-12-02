"""
LocalWorker - Local parallel execution worker.

This module implements the LocalWorker class for local parallel execution
using RasCmdr.compute_plan() internally.

IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED
"""

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class LocalWorker(RasWorker):
    """
    Local parallel execution worker (uses RasCmdr.compute_plan internally).

    IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED

    This worker provides a unified interface for local execution that matches
    the remote worker interface. It creates temporary worker folders, copies
    projects, executes using RasCmdr.compute_plan(), and copies results back.

    Attributes:
        worker_folder: Local path where worker folders are created (e.g., C:\\RasRemote)
        process_priority: OS process priority ("low", "below normal", "normal")
        queue_priority: Execution queue priority (0-9, lower executes first)
        cores_total: Total CPU cores available for this worker
        cores_per_plan: Cores to allocate per HEC-RAS plan
        max_parallel_plans: Max plans to run in parallel (calculated: cores_total/cores_per_plan)

    Example:
        worker = init_ras_worker(
            "local",
            worker_folder=r"C:\\RasRemote",
            process_priority="low",
            queue_priority=0,
            cores_total=8,
            cores_per_plan=2
        )
    """
    worker_folder: str = None
    process_priority: str = "low"
    queue_priority: int = 0
    cores_total: int = None
    cores_per_plan: int = 4
    max_parallel_plans: int = None

    def __post_init__(self):
        """Validate LocalWorker configuration."""
        super().__post_init__()
        self.worker_type = "local"
        self.hostname = "localhost"

        if not self.worker_folder:
            # Default to C:\RasRemote
            self.worker_folder = "C:\\RasRemote"
            logger.debug(f"Using default worker_folder: {self.worker_folder}")

        if self.process_priority not in ["low", "below normal", "normal"]:
            raise ValueError(
                f"process_priority must be 'low', 'below normal', or 'normal' "
                f"(got '{self.process_priority}'). 'low' is recommended."
            )

        if not isinstance(self.queue_priority, int) or self.queue_priority < 0 or self.queue_priority > 9:
            raise ValueError(
                f"queue_priority must be an integer from 0 to 9 (got {self.queue_priority}). "
                f"Lower values execute first. Default is 0."
            )

        # Calculate max parallel plans if cores_total specified
        if self.cores_total is not None:
            self.max_parallel_plans = self.cores_total // self.cores_per_plan
            if self.max_parallel_plans < 1:
                self.max_parallel_plans = 1
        else:
            self.max_parallel_plans = 1


def init_local_worker(**kwargs) -> LocalWorker:
    """
    Initialize local worker.

    Args:
        worker_folder: Local path where worker folders are created (default: C:\\RasRemote)
        process_priority: OS process priority ("low", "below normal", "normal")
        queue_priority: Execution queue priority (0-9)
        cores_total: Total CPU cores available
        cores_per_plan: Cores per plan (default 4)
        worker_id: Unique identifier (auto-generated if not provided)
        ras_exe_path: Path to HEC-RAS executable (obtained from ras object if not provided)

    Returns:
        LocalWorker: Configured worker ready for execution
    """
    logger.info("Initializing local worker")

    kwargs['worker_type'] = 'local'
    worker = LocalWorker(**kwargs)

    # Create worker folder if it doesn't exist
    worker_folder_path = Path(worker.worker_folder)
    worker_folder_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Local worker configured:")
    logger.info(f"  Worker folder: {worker.worker_folder}")
    logger.info(f"  RAS Exe: {worker.ras_exe_path}")
    logger.info(f"  Process Priority: {worker.process_priority}")
    logger.info(f"  Queue Priority: {worker.queue_priority}")
    if worker.max_parallel_plans > 1:
        logger.info(f"  Parallel Capacity: {worker.max_parallel_plans} plans simultaneously")
    else:
        logger.info(f"  Execution Mode: Sequential")

    return worker


def execute_local_plan(
    worker: LocalWorker,
    plan_number: str,
    ras_obj,
    num_cores: int,
    clear_geompre: bool,
    sub_worker_id: int = 1,
    autoclean: bool = True
) -> bool:
    """
    Execute a plan on a local worker using RasCmdr.compute_plan().

    Execution flow:
    1. Create temporary worker folder
    2. Copy project to worker folder
    3. Execute using RasCmdr.compute_plan()
    4. Copy results back
    5. Cleanup temporary folder (if autoclean=True)

    Args:
        worker: LocalWorker instance
        plan_number: Plan number to execute
        ras_obj: RAS project object
        num_cores: Number of cores
        clear_geompre: Clear geompre files
        sub_worker_id: Sub-worker ID for parallel execution (default 1)
        autoclean: Delete temporary worker folder after execution (default True)

    Returns:
        bool: True if successful
    """
    logger.info(f"Starting local execution of plan {plan_number} (sub-worker #{sub_worker_id})")

    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name

    # Step 1: Create temporary worker folder
    worker_folder_path = Path(worker.worker_folder)
    worker_folder_path.mkdir(parents=True, exist_ok=True)

    worker_temp_folder = worker_folder_path / f"{project_name}_{plan_number}_SW{sub_worker_id}_{uuid.uuid4().hex[:8]}"
    worker_temp_folder.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created worker folder: {worker_temp_folder}")

    try:
        # Step 2: Copy project to worker folder
        logger.info(f"Copying project to {worker_temp_folder}")
        worker_project_path = worker_temp_folder / project_name
        shutil.copytree(project_folder, worker_project_path, dirs_exist_ok=True)

        # Step 3: Execute using RasCmdr.compute_plan()
        from ..RasCmdr import RasCmdr
        from ..RasPrj import RasPrj, init_ras_project

        # Initialize project in worker folder
        logger.info(f"Initializing project in worker folder")
        temp_ras = RasPrj()
        prj_files = list(worker_project_path.glob("*.prj"))
        if not prj_files:
            logger.error(f"No .prj file found in {worker_project_path}")
            return False

        # Get version from original ras object
        ras_version = getattr(ras_obj, 'ras_version', '6.6')
        init_ras_project(str(worker_project_path), ras_version, ras_object=temp_ras)

        logger.info(f"Executing plan {plan_number} with RasCmdr.compute_plan()")
        success = RasCmdr.compute_plan(
            plan_number=plan_number,
            ras_object=temp_ras,
            clear_geompre=clear_geompre,
            num_cores=num_cores
        )

        if not success:
            logger.error(f"RasCmdr.compute_plan() returned False for plan {plan_number}")
            return False

        # Step 4: Copy results back (HDF file)
        hdf_file = worker_project_path / f"{project_name}.p{plan_number}.hdf"

        if not hdf_file.exists():
            logger.error(f"HDF file not created: {hdf_file}")
            return False

        logger.info(f"HDF file created successfully: {hdf_file}")

        dest_hdf = project_folder / hdf_file.name
        shutil.copy2(hdf_file, dest_hdf)
        logger.info(f"Copied results to {dest_hdf}")

        # Also copy any other result files (.computeMsgs.txt, etc.)
        for result_file in worker_project_path.glob(f"{project_name}.p{plan_number}.*"):
            if result_file.suffix not in ['.hdf']:  # HDF already copied
                dest_file = project_folder / result_file.name
                if not dest_file.exists() or result_file.stat().st_mtime > dest_file.stat().st_mtime:
                    shutil.copy2(result_file, dest_file)
                    logger.debug(f"Copied result file: {result_file.name}")

        # Step 5: Cleanup (if autoclean enabled)
        if autoclean:
            shutil.rmtree(worker_temp_folder, ignore_errors=True)
            logger.debug(f"Cleaned up worker folder: {worker_temp_folder}")
        else:
            logger.info(f"Preserving worker folder for debugging: {worker_temp_folder}")

        return True

    except Exception as e:
        logger.error(f"Error in local execution: {e}")
        import traceback
        logger.debug(traceback.format_exc())

        if autoclean:
            try:
                if worker_temp_folder.exists():
                    shutil.rmtree(worker_temp_folder, ignore_errors=True)
            except:
                pass
        else:
            logger.info(f"Preserving worker folder for debugging: {worker_temp_folder}")
        return False
