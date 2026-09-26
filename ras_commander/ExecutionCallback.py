"""
ExecutionCallback - Protocol for HEC-RAS execution progress callbacks.

This module defines the callback interface for monitoring HEC-RAS computation
lifecycle events. Callbacks enable real-time progress tracking, logging, and
UI updates during long-running simulations.

The Protocol pattern allows partial implementation - classes only need to
implement the callback methods they care about.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutionCallback(Protocol):
    """
    Protocol for execution progress callbacks.

    This defines the interface for monitoring HEC-RAS computation lifecycle.
    Implementations can provide any subset of these methods - all are optional.

    Lifecycle Hooks (terminal ordering depends on the execution outcome):
        1. on_prep_start()     - Before plan setup
        2. on_prep_complete()  - After plan setup, before engine preprocessing
        3. on_exec_start()     - Immediately before HEC-RAS subprocess launch
        4. on_exec_message()   - During execution (potentially many calls)
        5. on_exec_complete()  - HEC-RAS subprocess finished
        6. on_verify_result()  - After HDF verification (if verify=True)

    Thread Safety:
        compute_plan() accepts stream_callback; compute_parallel() and
        compute_test_mode() do not. If caller-managed threads share a callback,
        protect shared state with locks, thread-local storage, or atomic operations.

    Example - Simple Console Logging:
        >>> class ConsoleCallback:
        ...     def on_exec_start(self, plan_number, command):
        ...         print(f"[{plan_number}] Starting...")
        ...     def on_exec_message(self, plan_number, message):
        ...         print(f"[{plan_number}] {message}")
        ...     def on_exec_complete(self, plan_number, success, duration):
        ...         print(f"[{plan_number}] Done in {duration:.1f}s")

    Example - Thread-Safe File Logging:
        >>> from threading import Lock
        >>> class FileCallback:
        ...     def __init__(self):
        ...         self.lock = Lock()
        ...         self.files = {}
        ...     def on_exec_start(self, plan_number, command):
        ...         with self.lock:
        ...             self.files[plan_number] = open(f"plan_{plan_number}.log", 'w')
        ...     def on_exec_message(self, plan_number, message):
        ...         with self.lock:
        ...             if plan_number in self.files:
        ...                 self.files[plan_number].write(message + '\\n')
    """

    def on_prep_start(self, plan_number: str) -> None:
        """
        Called before plan setup, including preprocessor-file clearing and core setup.

        This is invoked before:
        - Geometry preprocessor file clearing (if clear_geompre=True)
        - Number of cores configuration (if num_cores specified)

        Args:
            plan_number: Plan identifier (e.g., "01", "02")

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
        """
        ...

    def on_prep_complete(self, plan_number: str) -> None:
        """
        Called after plan setup completes; engine preprocessing may still be required.

        This is invoked after:
        - Geometry preprocessor files cleared (if applicable)
        - Number of cores set in plan file (if applicable)
        - Just before HEC-RAS subprocess starts

        Args:
            plan_number: Plan identifier (e.g., "01", "02")

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
        """
        ...

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """
        Called immediately before launching the HEC-RAS subprocess.

        This is invoked immediately before subprocess execution begins.
        The command includes the full command line that will be executed.

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            command: Full version-specific command line (for example, HEC-RAS
                6.0+ uses '"C:/RAS/RAS.exe" -c project.prj plan.p01').

        Note:
            At this point the subprocess has been constructed but not yet started.
            This is the last callback before HEC-RAS begins running.

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
        """
        ...

    def on_exec_message(self, plan_number: str, message: str) -> None:
        """
        Called for each new .bco file message during execution.

        This is invoked repeatedly as HEC-RAS writes to the .bco file.
        Messages are streamed line-by-line in near real-time (polling interval: 0.5s).

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            message: Single line from .bco file (newline stripped)

        Frequency:
            - Called potentially hundreds or thousands of times per plan
            - Frequency depends on HEC-RAS computation complexity
            - Polling interval: 0.5 seconds (configurable in BcoMonitor)

        Performance:
            - Keep callback implementation FAST (< 1ms recommended)
            - Avoid blocking I/O, network calls, or heavy computation
            - For expensive operations, queue messages and process in separate thread

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
            CRITICAL: Implement proper locking if writing to shared resources.

        Example Messages:
            - "Geometry Preprocessor Version 6.6"
            - "Computing Cross Section HTAB's"
            - "Starting Unsteady Flow Computations"
            - "Time: 01JAN2020 0600 [  1.25% Done]"
        """
        ...

    def on_exec_complete(self, plan_number: str, success: bool, duration: float) -> None:
        """
        Called when HEC-RAS execution finishes.

        This reports the execution-phase outcome. Later artifact handling can
        still change the final ComputeResult.success value.

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            success: Execution-phase success under the selected engine contract;
                not necessarily equivalent to a zero launcher return code
            duration: Execution time in seconds (floating point)

        Note:
            - success=True does NOT guarantee HEC-RAS succeeded (it may have errors)
            - Use on_verify_result() to check if HDF contains "Complete Process"
            - duration is wall-clock time, not CPU time

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
        """
        ...

    def on_verify_result(self, plan_number: str, verified: bool) -> None:
        """
        Called after HDF verification (only if verify=True parameter used).

        This is invoked after checking HDF file for "Complete Process" message.

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            verified: True if HDF contains "Complete Process", False otherwise

        Note:
            - Only called when RasCmdr.compute_plan(..., verify=True)
            - verified=True reports completion evidence, not hydraulic acceptance
              or successful later artifact handling
            - verified=False may indicate computation errors or incomplete results

        Thread Safety:
            Protect shared state if caller-managed threads share this callback.
        """
        ...


# Type alias for simpler imports
Callback = ExecutionCallback
