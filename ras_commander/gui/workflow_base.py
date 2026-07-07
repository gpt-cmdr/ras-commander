"""
Workflow infrastructure for GUI automation.

Provides WorkflowStep and WorkflowResult dataclasses plus a step executor
that handles retry, recovery, timeout, and logging for each step.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


@dataclass
class WorkflowStep:
    """
    A single step in a GUI automation workflow.

    Attributes:
        name: Human-readable step name for logging.
        action: Callable that performs the step. Receives context dict, returns result.
        max_retries: Number of retries on failure. Default 3.
        retry_delay: Seconds between retries. Default 2.0.
        timeout: Step-level timeout in seconds. None means no timeout.
        required: If False, failure logs a warning but workflow continues. Default True.
        recovery: Optional callable invoked before each retry. Receives context dict.
    """
    name: str
    action: Callable
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: Optional[float] = None
    required: bool = True
    recovery: Optional[Callable] = None


@dataclass
class WorkflowResult:
    """
    Result of executing a GUI automation workflow.

    Attributes:
        success: True if all required steps completed.
        steps_completed: Names of successfully completed steps.
        steps_failed: Names of failed steps.
        step_results: Return values from each step, keyed by step name.
        elapsed_seconds: Total workflow execution time.
        error: The exception that caused failure, if any.
    """
    success: bool
    steps_completed: List[str] = field(default_factory=list)
    steps_failed: List[str] = field(default_factory=list)
    step_results: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    error: Optional[Exception] = None


class WorkflowExecutor:
    """
    Executes a sequence of WorkflowSteps with retry, recovery, and logging.

    Steps communicate via a shared context dict. Earlier steps produce
    values (e.g., context['hecras_hwnd']) consumed by later steps.
    """

    @staticmethod
    @log_call
    def execute(
        steps: List[WorkflowStep],
        context: Optional[Dict[str, Any]] = None,
        workflow_name: str = "Workflow"
    ) -> WorkflowResult:
        """
        Execute a sequence of workflow steps.

        Args:
            steps: List of WorkflowStep objects to execute in order.
            context: Shared mutable dict passed to each step's action and recovery.
                     Created empty if None.
            workflow_name: Name for logging. Default "Workflow".

        Returns:
            WorkflowResult with execution details.
        """
        if context is None:
            context = {}

        result = WorkflowResult(success=True)
        start_time = time.time()

        logger.info(f"Starting {workflow_name} ({len(steps)} steps)")

        for i, step in enumerate(steps, 1):
            step_start = time.time()
            logger.debug(f"[{i}/{len(steps)}] {step.name}")

            step_success = False
            step_error = None

            for attempt in range(1, step.max_retries + 1):
                try:
                    step_result = step.action(context)
                    result.step_results[step.name] = step_result
                    result.steps_completed.append(step.name)
                    step_success = True

                    step_elapsed = time.time() - step_start
                    logger.debug(f"[{i}/{len(steps)}] {step.name} completed ({step_elapsed:.1f}s)")
                    break

                except Exception as e:
                    step_error = e
                    logger.debug(
                        f"[{i}/{len(steps)}] {step.name} failed (attempt {attempt}/{step.max_retries}): {e}"
                    )

                    if attempt < step.max_retries:
                        # Run recovery before retry
                        if step.recovery:
                            try:
                                step.recovery(context)
                            except Exception as re:
                                logger.debug(f"Recovery for '{step.name}' failed: {re}")

                        time.sleep(step.retry_delay)

            if not step_success:
                result.steps_failed.append(step.name)

                if step.required:
                    result.success = False
                    result.error = step_error
                    logger.error(f"Required step '{step.name}' failed after {step.max_retries} attempts")
                    break
                else:
                    logger.warning(f"Optional step '{step.name}' failed, continuing workflow")

        result.elapsed_seconds = time.time() - start_time

        if result.success:
            logger.info(f"{workflow_name} completed successfully ({result.elapsed_seconds:.1f}s)")
        else:
            logger.error(
                f"{workflow_name} failed at step '{result.steps_failed[-1]}' "
                f"({result.elapsed_seconds:.1f}s, "
                f"{len(result.steps_completed)}/{len(steps)} steps completed)"
            )

        return result
