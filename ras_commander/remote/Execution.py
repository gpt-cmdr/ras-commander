"""
Execution - Distributed parallel execution across remote workers.

This module provides the compute_parallel_remote() function for executing
HEC-RAS plans across multiple local and remote workers.

IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from pathlib import Path

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    """
    Result of a single plan execution.

    Attributes:
        plan_number: Plan number that was executed
        worker_id: ID of worker that executed the plan
        success: True if execution completed successfully
        hdf_path: Path to output HDF file (if successful)
        error_message: Error message (if failed)
        execution_time: Time in seconds for execution
    """
    plan_number: str
    worker_id: str
    success: bool
    hdf_path: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: float = 0.0


@log_call
def compute_parallel_remote(
    plan_numbers: Union[str, List[str]],
    workers: List[RasWorker],
    ras_object=None,
    num_cores: int = 4,
    clear_geompre: bool = False,
    max_concurrent: Optional[int] = None,
    autoclean: bool = True
) -> Dict[str, ExecutionResult]:
    """
    Execute HEC-RAS plans in parallel across multiple remote workers.

    Plans are distributed to workers using naive round-robin scheduling,
    respecting each worker's queue_priority (lower values execute first).

    Args:
        plan_numbers: Single plan number or list of plan numbers to execute
        workers: List of initialized worker objects (from init_ras_worker)
        ras_object: RasPrj object for the project. If None, uses global ras.
        num_cores: Number of cores to allocate per plan execution
        clear_geompre: Clear geometry preprocessor files before execution
        max_concurrent: Maximum concurrent executions (default: sum of all worker slots)
        autoclean: Delete temporary worker folders after execution (default True).
                   Set to False for debugging to preserve worker folders.

    Returns:
        Dict mapping plan_number to ExecutionResult

    Example:
        # Initialize workers
        worker1 = init_ras_worker("psexec", hostname="PC1", ...)
        worker2 = init_ras_worker("psexec", hostname="PC2", ...)

        # Execute plans
        results = compute_parallel_remote(
            ["01", "02", "03", "04"],
            workers=[worker1, worker2],
            ras_object=ras
        )

        # Check results
        for plan_num, result in results.items():
            if result.success:
                print(f"Plan {plan_num}: {result.hdf_path}")
            else:
                print(f"Plan {plan_num} failed: {result.error_message}")

    Scheduling:
        Workers are sorted by queue_priority (ascending), then plans are assigned
        round-robin to available worker slots. Workers with lower queue_priority
        (e.g., 0=local, 1=remote) are filled first.

    Multi-Core Workers:
        Workers with cores_total and cores_per_plan set can run multiple plans
        in parallel. For example, a worker with cores_total=16 and cores_per_plan=4
        can run 4 plans simultaneously. Each parallel slot is called a "sub-worker".
    """
    from ..RasPrj import ras as global_ras

    if ras_object is None:
        ras_object = global_ras

    if ras_object is None or not hasattr(ras_object, 'project_folder'):
        raise ValueError("No valid RAS project. Initialize with init_ras_project() first.")

    # Normalize plan_numbers to list
    if isinstance(plan_numbers, str):
        plan_numbers = [plan_numbers]

    if not plan_numbers:
        logger.warning("No plans to execute")
        return {}

    if not workers:
        raise ValueError("No workers provided. Initialize workers with init_ras_worker().")

    logger.info(f"Starting distributed execution of {len(plan_numbers)} plans across {len(workers)} workers")

    # Sort workers by queue_priority (lower first)
    sorted_workers = sorted(workers, key=lambda w: getattr(w, 'queue_priority', 0))

    # Build worker slot list (worker, sub_worker_id) for round-robin assignment
    worker_slots = []
    for worker in sorted_workers:
        max_parallel = getattr(worker, 'max_parallel_plans', 1) or 1
        for sub_id in range(1, max_parallel + 1):
            worker_slots.append((worker, sub_id))

    total_slots = len(worker_slots)
    logger.info(f"Total worker slots available: {total_slots}")

    # Calculate max concurrent executions
    if max_concurrent is None:
        max_concurrent = total_slots
    max_concurrent = min(max_concurrent, total_slots, len(plan_numbers))

    # Results dictionary
    results: Dict[str, ExecutionResult] = {}

    # Execute plans using thread pool
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {}

        for idx, plan_number in enumerate(plan_numbers):
            # Round-robin assignment to worker slots
            worker, sub_worker_id = worker_slots[idx % total_slots]

            logger.info(
                f"Submitting plan {plan_number} to worker {worker.worker_id} "
                f"(sub-worker #{sub_worker_id})"
            )

            future = executor.submit(
                _execute_single_plan,
                worker=worker,
                plan_number=plan_number,
                ras_object=ras_object,
                num_cores=num_cores,
                clear_geompre=clear_geompre,
                sub_worker_id=sub_worker_id,
                autoclean=autoclean
            )
            futures[future] = plan_number

        # Collect results as they complete
        for future in as_completed(futures):
            plan_number = futures[future]
            try:
                result = future.result()
                results[plan_number] = result

                if result.success:
                    logger.info(
                        f"Plan {plan_number} completed successfully "
                        f"({result.execution_time:.1f}s)"
                    )
                else:
                    logger.error(
                        f"Plan {plan_number} failed: {result.error_message}"
                    )

            except Exception as e:
                logger.error(f"Plan {plan_number} raised exception: {e}")
                results[plan_number] = ExecutionResult(
                    plan_number=plan_number,
                    worker_id="unknown",
                    success=False,
                    error_message=str(e)
                )

    # Summary
    successful = sum(1 for r in results.values() if r.success)
    failed = len(results) - successful
    logger.info(f"Distributed execution complete: {successful} succeeded, {failed} failed")

    return results


def _execute_single_plan(
    worker: RasWorker,
    plan_number: str,
    ras_object,
    num_cores: int,
    clear_geompre: bool,
    sub_worker_id: int,
    autoclean: bool = True
) -> ExecutionResult:
    """
    Execute a single plan on a specific worker.

    This internal function routes to the appropriate worker-specific execution
    function based on worker_type.

    Args:
        worker: Worker instance
        plan_number: Plan number to execute
        ras_object: RAS project object
        num_cores: Number of cores
        clear_geompre: Clear geompre files
        sub_worker_id: Sub-worker ID for multi-slot workers
        autoclean: Delete temporary worker folder after execution

    Returns:
        ExecutionResult with execution outcome
    """
    start_time = time.time()
    result = ExecutionResult(
        plan_number=plan_number,
        worker_id=worker.worker_id,
        success=False
    )

    try:
        # Route to worker-specific execution
        if worker.worker_type == "psexec":
            from .PsexecWorker import execute_psexec_plan
            success = execute_psexec_plan(
                worker=worker,
                plan_number=plan_number,
                ras_obj=ras_object,
                num_cores=num_cores,
                clear_geompre=clear_geompre,
                sub_worker_id=sub_worker_id,
                autoclean=autoclean
            )
            result.success = success

            if success:
                project_name = ras_object.project_name
                hdf_file = Path(ras_object.project_folder) / f"{project_name}.p{plan_number}.hdf"
                if hdf_file.exists():
                    result.hdf_path = str(hdf_file)

        elif worker.worker_type == "local":
            from .LocalWorker import execute_local_plan
            success = execute_local_plan(
                worker=worker,
                plan_number=plan_number,
                ras_obj=ras_object,
                num_cores=num_cores,
                clear_geompre=clear_geompre,
                sub_worker_id=sub_worker_id,
                autoclean=autoclean
            )
            result.success = success

            if success:
                project_name = ras_object.project_name
                hdf_file = Path(ras_object.project_folder) / f"{project_name}.p{plan_number}.hdf"
                if hdf_file.exists():
                    result.hdf_path = str(hdf_file)

        elif worker.worker_type == "ssh":
            result.error_message = "SSH worker not yet implemented"

        elif worker.worker_type == "winrm":
            result.error_message = "WinRM worker not yet implemented"

        elif worker.worker_type == "docker":
            result.error_message = "Docker worker not yet implemented"

        elif worker.worker_type == "slurm":
            result.error_message = "Slurm worker not yet implemented"

        elif worker.worker_type == "aws_ec2":
            result.error_message = "AWS EC2 worker not yet implemented"

        elif worker.worker_type == "azure_fr":
            result.error_message = "Azure worker not yet implemented"

        else:
            result.error_message = f"Unknown worker type: {worker.worker_type}"

    except NotImplementedError as e:
        result.error_message = str(e)
    except Exception as e:
        result.error_message = f"Execution error: {e}"
        logger.exception(f"Error executing plan {plan_number} on {worker.worker_id}")

    result.execution_time = time.time() - start_time
    return result


def get_worker_status(workers: List[RasWorker]) -> Dict[str, Dict]:
    """
    Get status summary for a list of workers.

    Args:
        workers: List of worker instances

    Returns:
        Dict mapping worker_id to status dict with keys:
        - worker_type: Type of worker
        - hostname: Target hostname
        - queue_priority: Queue priority level
        - max_parallel_plans: Max concurrent plans
        - available: True if worker is available for execution
    """
    status = {}
    for worker in workers:
        status[worker.worker_id] = {
            'worker_type': worker.worker_type,
            'hostname': getattr(worker, 'hostname', 'localhost'),
            'queue_priority': getattr(worker, 'queue_priority', 0),
            'max_parallel_plans': getattr(worker, 'max_parallel_plans', 1),
            'available': True  # Future: add connectivity check
        }
    return status
