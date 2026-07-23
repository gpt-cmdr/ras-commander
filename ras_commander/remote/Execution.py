"""
Execution - Distributed parallel execution across remote workers.

This module provides the compute_parallel_remote() function for executing
HEC-RAS plans across multiple local and remote workers.

IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED
"""

import time
import time as _wtime
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from typing import Dict, List, Optional, Union

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


def _effective_worker_capacity(worker: RasWorker, num_cores: int) -> int:
    """Return scheduler slots allowed by worker configuration and requested cores."""
    configured_capacity = getattr(worker, "max_parallel_plans", None)
    if configured_capacity is None:
        configured_capacity = 1
    if (
        isinstance(configured_capacity, bool)
        or not isinstance(configured_capacity, Integral)
        or configured_capacity < 1
    ):
        raise ValueError(
            f"Worker {getattr(worker, 'worker_id', '<unknown>')} has invalid "
            f"max_parallel_plans={configured_capacity!r}"
        )

    cores_total = getattr(worker, "cores_total", None)
    if cores_total is None:
        return int(configured_capacity)
    if (
        isinstance(cores_total, bool)
        or not isinstance(cores_total, Integral)
        or cores_total < 1
    ):
        raise ValueError(
            f"Worker {getattr(worker, 'worker_id', '<unknown>')} has invalid "
            f"cores_total={cores_total!r}"
        )

    return min(int(configured_capacity), int(cores_total) // num_cores)


@log_call
def compute_parallel_remote(
    plan_numbers: Union[str, List[str]],
    workers: List[RasWorker],
    ras_object=None,
    num_cores: int = 4,
    clear_geompre: bool = False,
    force_geompre: bool = False,
    force_rerun: bool = False,
    max_concurrent: Optional[int] = None,
    autoclean: bool = True,
    copy_geometry_outputs: bool = True,
) -> Dict[str, ExecutionResult]:
    """
    Execute HEC-RAS plans in parallel across multiple remote workers.

    Plans are assigned as worker capacity becomes available, respecting each
    worker's queue_priority (lower values execute first).

    Args:
        plan_numbers: Single plan number or list of plan numbers to execute
        workers: List of initialized worker objects (from init_ras_worker)
        ras_object: RasPrj object for the project. If None, uses global ras.
        num_cores: Number of cores to allocate per plan execution
        clear_geompre: Clear geometry preprocessor files (.c## files) before execution
        force_geompre: Force full geometry reprocessing (clears both .g##.hdf AND .c## files)
        force_rerun: Force execution even if results are current. When False (default),
            checks file modification times and skips if results are current.
        max_concurrent: Maximum concurrent executions (default: sum of all worker slots)
        autoclean: Delete temporary worker folders after execution (default True).
                   Set to False for debugging to preserve worker folders.
        copy_geometry_outputs: Copy geometry outputs back after local or PsExec execution
            (default True for backward compatibility). Concurrent plans sharing
            a geometry can race during copyback; use False for scenario ensembles
            that share preprocessed geometry.

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
                print(
                    f"Plan {plan_num} succeeded "
                    f"({result.execution_time:.1f}s)"
                )
            else:
                print(f"Plan {plan_num} failed: {result.error_message}")

    Scheduling:
        Workers are sorted by queue_priority (ascending). Plans are submitted only
        when a worker has an available capacity slot, so faster workers can take
        later plans without oversubscribing slower hosts.

    Multi-Core Workers:
        Effective capacity is the smaller of the worker's configured
        max_parallel_plans and cores_total // num_cores. For example, a worker
        configured for 4 plans but given num_cores=8 and cores_total=16 runs at
        most 2 plans simultaneously.
    """
    from ..RasPrj import ras as global_ras

    if ras_object is None:
        ras_object = global_ras

    if isinstance(num_cores, bool) or not isinstance(num_cores, Integral) or num_cores < 1:
        raise ValueError("num_cores must be an integer greater than or equal to 1")
    num_cores = int(num_cores)

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

    # Sort workers by queue_priority (lower first)
    sorted_workers = sorted(workers, key=lambda w: getattr(w, 'queue_priority', 0))

    # Track actual free slots per worker. Plans are submitted only after a slot
    # is acquired and the slot is returned when that worker's future completes.
    worker_states = []
    for worker in sorted_workers:
        capacity = _effective_worker_capacity(worker, num_cores)
        if capacity < 1:
            logger.warning(
                "Worker %s has no capacity for num_cores=%s and will be skipped",
                worker.worker_id,
                num_cores,
            )
            continue
        worker_states.append(
            {
                "worker": worker,
                "free_slots": list(range(1, capacity + 1)),
            }
        )

    for state in worker_states:
        runtime = getattr(state["worker"], "max_runtime_minutes", 600)
        if (
            isinstance(runtime, bool)
            or not isinstance(runtime, Real)
            or runtime <= 0
        ):
            raise ValueError(
                f"Worker {state['worker'].worker_id} has invalid "
                f"max_runtime_minutes={runtime!r}; expected a positive number"
            )

    total_slots = sum(len(state["free_slots"]) for state in worker_states)
    if total_slots == 0:
        raise ValueError(
            f"No worker can run a plan with num_cores={num_cores}; "
            "increase cores_total or reduce num_cores"
        )
    logger.debug("Total worker slots available: %s", total_slots)

    # Calculate max concurrent executions
    if max_concurrent is None:
        max_concurrent = total_slots
    if (
        isinstance(max_concurrent, bool)
        or not isinstance(max_concurrent, Integral)
        or max_concurrent < 1
    ):
        raise ValueError("max_concurrent must be an integer greater than or equal to 1")
    max_concurrent = int(min(max_concurrent, total_slots, len(plan_numbers)))
    logger.info(
        "Starting distributed execution of %s plan(s) across %s worker(s) "
        "(%s slot(s), max_concurrent=%s)",
        len(plan_numbers),
        len(worker_states),
        total_slots,
        max_concurrent,
    )

    # Results dictionary
    results: Dict[str, ExecutionResult] = {}

    # The progress watchdog stops queued submissions after the slowest worker
    # runtime plus a staging/copy-back margin. Python cannot terminate an
    # already-running thread safely, so watchdog teardown waits for started
    # tasks before this function returns; otherwise they could mutate project
    # outputs afterward.
    _max_rt_min = max(
        (getattr(state["worker"], "max_runtime_minutes", 600) or 600)
        for state in worker_states
    )
    no_progress_timeout_sec = _max_rt_min * 60 + 900  # + 15 min staging margin

    executor = ThreadPoolExecutor(max_workers=max_concurrent)
    watchdog_triggered = False
    try:
        futures = {}
        queued_plans = deque(plan_numbers)
        worker_cursor = 0

        def acquire_worker_slot():
            nonlocal worker_cursor

            available_priorities = [
                getattr(state["worker"], "queue_priority", 0)
                for state in worker_states
                if state["free_slots"]
            ]
            if not available_priorities:
                return None

            priority = min(available_priorities)
            for offset in range(len(worker_states)):
                index = (worker_cursor + offset) % len(worker_states)
                state = worker_states[index]
                if (
                    state["free_slots"]
                    and getattr(state["worker"], "queue_priority", 0) == priority
                ):
                    sub_worker_id = state["free_slots"].pop(0)
                    worker_cursor = (index + 1) % len(worker_states)
                    return state, sub_worker_id
            return None

        def submit_available_plans():
            while queued_plans and len(futures) < max_concurrent:
                acquired = acquire_worker_slot()
                if acquired is None:
                    return
                state, sub_worker_id = acquired
                worker = state["worker"]
                plan_number = queued_plans.popleft()

                logger.debug(
                    "Submitting plan %s to worker %s (sub-worker #%s)",
                    plan_number,
                    worker.worker_id,
                    sub_worker_id,
                )

                future = executor.submit(
                    _execute_single_plan,
                    worker=worker,
                    plan_number=plan_number,
                    ras_object=ras_object,
                    num_cores=num_cores,
                    clear_geompre=clear_geompre,
                    force_geompre=force_geompre,
                    force_rerun=force_rerun,
                    sub_worker_id=sub_worker_id,
                    autoclean=autoclean,
                    copy_geometry_outputs=copy_geometry_outputs,
                )
                futures[future] = (plan_number, state, sub_worker_id)

        submit_available_plans()

        # Collect results as they complete, with a no-progress watchdog.
        last_progress = _wtime.monotonic()
        while futures:
            done, _ = wait(
                tuple(futures),
                timeout=3,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                if _wtime.monotonic() - last_progress > no_progress_timeout_sec:
                    watchdog_triggered = True
                    for future, (plan_number, state, _) in list(futures.items()):
                        future.cancel()
                        logger.error(
                            f"Plan {plan_number} abandoned: no plan completed in "
                            f"{no_progress_timeout_sec}s (fleet watchdog) -- "
                            f"a worker thread is presumed hung."
                        )
                        results[plan_number] = ExecutionResult(
                            plan_number=plan_number,
                            worker_id=state["worker"].worker_id,
                            success=False,
                            error_message=(
                                f"fleet watchdog: no progress in "
                                f"{no_progress_timeout_sec}s"
                            ),
                        )
                    futures.clear()
                    while queued_plans:
                        plan_number = queued_plans.popleft()
                        results[plan_number] = ExecutionResult(
                            plan_number=plan_number,
                            worker_id="unknown",
                            success=False,
                            error_message=(
                                f"fleet watchdog: no progress in "
                                f"{no_progress_timeout_sec}s"
                            ),
                        )
                    break
                continue

            last_progress = _wtime.monotonic()
            for future in done:
                plan_number, state, sub_worker_id = futures.pop(future)
                state["free_slots"].append(sub_worker_id)
                state["free_slots"].sort()
                try:
                    result = future.result()
                    results[plan_number] = result

                    if result.success:
                        logger.debug(
                            f"Plan {plan_number} completed successfully "
                            f"({result.execution_time:.1f}s)"
                        )
                    else:
                        logger.error(
                            f"Plan {plan_number} failed on worker "
                            f"{result.worker_id} after {result.execution_time:.1f}s: "
                            f"{result.error_message}"
                        )

                except Exception as e:
                    logger.error(f"Plan {plan_number} raised exception: {e}")
                    results[plan_number] = ExecutionResult(
                        plan_number=plan_number,
                        worker_id="unknown",
                        success=False,
                        error_message=str(e)
                    )

            submit_available_plans()
    finally:
        # Healthy futures are complete here. After watchdog activation, wait
        # for started tasks so none can mutate outputs after this API returns.
        executor.shutdown(
            wait=watchdog_triggered,
            cancel_futures=watchdog_triggered,
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
    force_geompre: bool,
    force_rerun: bool,
    sub_worker_id: int,
    autoclean: bool = True,
    copy_geometry_outputs: bool = True,
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
        clear_geompre: Clear geompre files (.c## only)
        force_geompre: Force full geometry reprocessing (clears .g##.hdf AND .c##)
        force_rerun: Force execution even if results are current
        sub_worker_id: Sub-worker ID for multi-slot workers
        autoclean: Delete temporary worker folder after execution
        copy_geometry_outputs: Copy geometry outputs back after local or PsExec execution

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
                force_geompre=force_geompre,
                force_rerun=force_rerun,
                sub_worker_id=sub_worker_id,
                autoclean=autoclean,
                copy_geometry_outputs=copy_geometry_outputs,
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
                force_geompre=force_geompre,
                force_rerun=force_rerun,
                sub_worker_id=sub_worker_id,
                autoclean=autoclean,
                copy_geometry_outputs=copy_geometry_outputs,
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
            from .DockerWorker import execute_docker_plan
            success = execute_docker_plan(
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
                else:
                    # Check for .tmp.hdf (Linux container output)
                    tmp_hdf = Path(ras_object.project_folder) / f"{project_name}.p{plan_number}.tmp.hdf"
                    if tmp_hdf.exists():
                        result.hdf_path = str(tmp_hdf)

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
