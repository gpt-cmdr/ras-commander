"""Public-runtime controls for serial native sampling in an isolated worker."""

from __future__ import annotations

from collections.abc import Callable
from logging import getLogger
from threading import Lock
from typing import Any, TypeVar

_T = TypeVar("_T")
_sampling_lock = Lock()
logger = getLogger(__name__)


def _load_controls(*, initialized: bool = False) -> dict[str, Any]:
    if not initialized:
        from .terrain import RasTerrainMod

        RasTerrainMod._ensure_initialized()
    from System import Environment, IntPtr
    from System.Diagnostics import Process
    from System.Threading import ManualResetEvent, Thread, ThreadPool, WaitCallback

    process = Process.GetCurrentProcess()

    def invoke(operation: Callable[[], _T]) -> _T:
        results = []
        errors = []
        finished = ManualResetEvent(False)

        def call(state: Any) -> None:
            try:
                if not Thread.CurrentThread.IsThreadPoolThread:
                    raise RuntimeError(
                        "native sampling did not enter a CLR pool worker"
                    )
                results.append(operation())
            except BaseException as exc:  # noqa: BLE001 - preserve failure and restore runtime
                errors.append(exc)
            finally:
                finished.Set()

        try:
            if not ThreadPool.QueueUserWorkItem(WaitCallback(call)):
                raise RuntimeError("CLR pool rejected the native sampling callback")
            # An event wait cannot inline the callback on the waiting Python thread.
            finished.WaitOne()
        finally:
            finished.Dispose()
        if errors:
            raise errors[0]
        if len(results) != 1:
            raise RuntimeError("native sampling worker returned no result")
        return results[0]

    return {
        "get_affinity": lambda: int(process.ProcessorAffinity.ToInt64()),
        "set_affinity": lambda mask: setattr(
            process, "ProcessorAffinity", IntPtr(mask)
        ),
        "get_min": lambda: tuple(int(v) for v in ThreadPool.GetMinThreads()),
        "get_max": lambda: tuple(int(v) for v in ThreadPool.GetMaxThreads()),
        "set_min": ThreadPool.SetMinThreads,
        "set_max": ThreadPool.SetMaxThreads,
        "invoke": invoke,
        "processor_count": int(Environment.ProcessorCount),
    }


def run_serial_sampling(
    operation: Callable[[], _T], *, _initialized: bool = False
) -> tuple[_T, dict[str, Any]]:
    """Run a blocking callback on the sole CLR pool worker; restore runtime controls.

    Requires a caller-owned isolated Windows/Wine process with no other native
    work. Uses public process-affinity and CLR ThreadPool APIs, never HEC private
    caches or sampling parameters. Units, CRS, source mutation and artifacts are
    those of the callback. Returns its result plus execution/restoration evidence.
    Unsupported limits fail before invoking the callback. Concurrent or nested
    calls are rejected; a callback must not await separately queued CLR work.
    """
    if not callable(operation):
        raise TypeError("operation must be callable")
    if not _sampling_lock.acquire(blocking=False):
        raise RuntimeError("serial native sampling is already active in this process")
    try:
        controls = (
            _load_controls(initialized=True) if _initialized else _load_controls()
        )
        original_affinity = controls["get_affinity"]()
        original_min = controls["get_min"]()
        original_max = controls["get_max"]()
        if original_affinity <= 0:
            raise RuntimeError("native sampling process has no available processor")
        single_affinity = original_affinity & -original_affinity
        evidence = {
            "mode": "single-clr-pool-worker-v1",
            "original_processor_affinity": original_affinity,
            "sampling_processor_affinity": single_affinity,
            "reported_processor_count": controls["processor_count"],
            "original_min_threads": list(original_min),
            "original_max_threads": list(original_max),
            "sampling_min_threads": [1, 1],
            "sampling_max_threads": [1, 1],
            "called_on_pool_worker": False,
            "runtime_restored": False,
        }
        primary = None
        try:
            controls["set_affinity"](single_affinity)
            if not controls["set_min"](1, 1) or not controls["set_max"](1, 1):
                raise RuntimeError(
                    "runtime rejected single-worker native sampling limits"
                )
            if (
                controls["get_affinity"]() != single_affinity
                or controls["get_min"]() != (1, 1)
                or controls["get_max"]() != (1, 1)
            ):
                raise RuntimeError(
                    "runtime did not apply single-worker native sampling limits"
                )
            logger.info(
                "Native sampling mode=%s affinity=%s max_threads=%s",
                evidence["mode"],
                single_affinity,
                controls["get_max"](),
            )
            result = controls["invoke"](operation)
            evidence["called_on_pool_worker"] = True
        except BaseException as exc:
            primary = exc
            raise
        finally:
            failures = []
            for name, args in (
                ("set_max", original_max),
                ("set_min", original_min),
                ("set_affinity", (original_affinity,)),
            ):
                try:
                    if controls[name](*args) is False:
                        failures.append(name + " rejected restoration")
                except BaseException as exc:  # noqa: BLE001 - preserve failure and restore runtime
                    failures.append(name + ": " + str(exc))
            try:
                evidence["runtime_restored"] = (
                    controls["get_affinity"]() == original_affinity
                    and controls["get_min"]() == original_min
                    and controls["get_max"]() == original_max
                )
            except BaseException as exc:  # noqa: BLE001 - preserve failure and restore runtime
                failures.append("restoration readback: " + str(exc))
            if failures or not evidence["runtime_restored"]:
                message = "native sampling runtime restoration failed: " + "; ".join(
                    failures
                )
                if primary is not None:
                    note = getattr(primary, "add_note", None)
                    if callable(note):
                        note(message)
                    else:
                        logger.error(message)
                else:
                    raise RuntimeError(message)
        return result, evidence
    finally:
        _sampling_lock.release()
