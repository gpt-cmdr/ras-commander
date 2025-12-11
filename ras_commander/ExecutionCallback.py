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

    Lifecycle Order:
        1. on_prep_start()     - Before geometry preprocessing
        2. on_prep_complete()  - After preprocessing
        3. on_exec_start()     - HEC-RAS subprocess started
        4. on_exec_message()   - During execution (potentially many calls)
        5. on_exec_complete()  - HEC-RAS subprocess finished
        6. on_verify_result()  - After HDF verification (if verify=True)

    Thread Safety:
        When used with compute_parallel(), callbacks are invoked from
        worker threads concurrently. Implementations MUST be thread-safe.
        Use locks, thread-local storage, or atomic operations as needed.

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
        Called before geometry preprocessing and core setup.

        This is invoked before:
        - Geometry preprocessor file clearing (if clear_geompre=True)
        - Number of cores configuration (if num_cores specified)

        Args:
            plan_number: Plan identifier (e.g., "01", "02")

        Thread Safety:
            May be called concurrently for different plans in compute_parallel().
        """
        ...

    def on_prep_complete(self, plan_number: str) -> None:
        """
        Called after geometry preprocessing and core setup complete.

        This is invoked after:
        - Geometry preprocessor files cleared (if applicable)
        - Number of cores set in plan file (if applicable)
        - Just before HEC-RAS subprocess starts

        Args:
            plan_number: Plan identifier (e.g., "01", "02")

        Thread Safety:
            May be called concurrently for different plans in compute_parallel().
        """
        ...

    def on_exec_start(self, plan_number: str, command: str) -> None:
        """
        Called when HEC-RAS subprocess starts.

        This is invoked immediately before subprocess execution begins.
        The command includes the full command line that will be executed.

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            command: Full command line (e.g., '"C:/RAS/RAS.exe" -c project.prj plan.p01')

        Note:
            At this point the subprocess has been constructed but not yet started.
            This is the last callback before HEC-RAS begins running.

        Thread Safety:
            May be called concurrently for different plans in compute_parallel().
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
            May be called concurrently for different plans in compute_parallel().
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

        This is invoked immediately after subprocess completes (successfully or not).

        Args:
            plan_number: Plan identifier (e.g., "01", "02")
            success: True if subprocess exited with code 0, False otherwise
            duration: Execution time in seconds (floating point)

        Note:
            - success=True does NOT guarantee HEC-RAS succeeded (it may have errors)
            - Use on_verify_result() to check if HDF contains "Complete Process"
            - duration is wall-clock time, not CPU time

        Thread Safety:
            May be called concurrently for different plans in compute_parallel().
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
            - verified=True is the strongest guarantee that HEC-RAS succeeded
            - verified=False may indicate computation errors or incomplete results

        Thread Safety:
            May be called concurrently for different plans in compute_parallel().
        """
        ...


# Type alias for simpler imports
Callback = ExecutionCallback
