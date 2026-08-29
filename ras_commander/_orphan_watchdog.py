"""Minimal fail-closed worker for RasControl orphan cleanup.

This module is executed as a standalone Python file by :mod:`RasControl` so
the watchdog does not need to import the full package in its child process.
It signals only a process whose PID, creation time, and exact image name match
the identity captured by the Controller parent.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import psutil


_SAFE_STATES = frozenset({"absent", "stopped", "pid_reused", "terminated", "killed"})


@dataclass(frozen=True)
class _IdentityInspection:
    """One exact process-identity observation."""

    state: str
    process: Optional[Any] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class _OwnedProcessCleanupResult:
    """Outcome of one fail-closed owned-process cleanup attempt."""

    state: str
    terminated: bool = False
    killed: bool = False
    error: Optional[str] = None

    @property
    def safe_to_remove_lock(self) -> bool:
        """Whether the recorded process is positively absent or stopped."""
        return self.state in _SAFE_STATES


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _inspect_process_identity(
    *,
    pid: int,
    create_time: float,
    name: str,
    psutil_module: Any = psutil,
) -> _IdentityInspection:
    """Classify one PID without treating query uncertainty as absence."""
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or isinstance(create_time, bool)
        or not isinstance(create_time, (int, float))
        or not math.isfinite(float(create_time))
        or float(create_time) <= 0
        or not isinstance(name, str)
        or not name.strip()
    ):
        return _IdentityInspection(
            "query_failed",
            error="recorded process identity is malformed",
        )
    try:
        process = psutil_module.Process(pid)
        observed_create_time = float(process.create_time())
        observed_name = str(process.name()).strip()
        running = bool(process.is_running())
    except psutil_module.ZombieProcess as error:
        return _IdentityInspection("query_failed", error=_error_text(error))
    except psutil_module.NoSuchProcess:
        return _IdentityInspection("absent")
    except psutil_module.AccessDenied as error:
        return _IdentityInspection("access_denied", error=_error_text(error))
    except (OSError, ValueError, TypeError) as error:
        return _IdentityInspection("query_failed", error=_error_text(error))

    if (
        not math.isfinite(observed_create_time)
        or observed_create_time <= 0
        or not observed_name
    ):
        return _IdentityInspection(
            "query_failed",
            error="observed process identity is malformed",
        )
    if (
        not math.isclose(
            observed_create_time,
            float(create_time),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        or observed_name.casefold() != name.strip().casefold()
    ):
        return _IdentityInspection("pid_reused")
    if not running:
        return _IdentityInspection("stopped")
    return _IdentityInspection("exact", process=process)


def _result_from_inspection(
    inspection: _IdentityInspection,
    *,
    terminated: bool = False,
    killed: bool = False,
) -> _OwnedProcessCleanupResult:
    return _OwnedProcessCleanupResult(
        state=inspection.state,
        terminated=terminated,
        killed=killed,
        error=inspection.error,
    )


def _cleanup_owned_process(
    *,
    pid: int,
    create_time: float,
    name: str,
    wait_timeout: float = 10.0,
    psutil_module: Any = psutil,
) -> _OwnedProcessCleanupResult:
    """Stop only an exact process identity and prove its terminal state."""
    initial = _inspect_process_identity(
        pid=pid,
        create_time=create_time,
        name=name,
        psutil_module=psutil_module,
    )
    if initial.state != "exact":
        return _result_from_inspection(initial)

    # Re-open and reverify immediately before the first signal.  The returned
    # process handle is the only handle used for that signal.
    before_terminate = _inspect_process_identity(
        pid=pid,
        create_time=create_time,
        name=name,
        psutil_module=psutil_module,
    )
    if before_terminate.state != "exact" or before_terminate.process is None:
        return _result_from_inspection(before_terminate)
    process = before_terminate.process

    try:
        process.terminate()
    except psutil_module.NoSuchProcess:
        return _OwnedProcessCleanupResult("terminated", terminated=True)
    except psutil_module.AccessDenied as error:
        return _OwnedProcessCleanupResult(
            "terminate_failed",
            error=_error_text(error),
        )
    except (OSError, ValueError, TypeError) as error:
        return _OwnedProcessCleanupResult(
            "terminate_failed",
            error=_error_text(error),
        )

    try:
        process.wait(timeout=wait_timeout)
    except psutil_module.NoSuchProcess:
        return _OwnedProcessCleanupResult("terminated", terminated=True)
    except psutil_module.TimeoutExpired:
        # Re-open and reverify immediately before escalating.  A reused or
        # unverifiable PID is never killed.
        before_kill = _inspect_process_identity(
            pid=pid,
            create_time=create_time,
            name=name,
            psutil_module=psutil_module,
        )
        if before_kill.state != "exact" or before_kill.process is None:
            return _result_from_inspection(before_kill, terminated=True)
        kill_process = before_kill.process
        try:
            kill_process.kill()
        except psutil_module.NoSuchProcess:
            return _OwnedProcessCleanupResult(
                "killed",
                terminated=True,
                killed=True,
            )
        except psutil_module.AccessDenied as error:
            return _OwnedProcessCleanupResult(
                "kill_failed",
                terminated=True,
                error=_error_text(error),
            )
        except (OSError, ValueError, TypeError) as error:
            return _OwnedProcessCleanupResult(
                "kill_failed",
                terminated=True,
                error=_error_text(error),
            )
        try:
            kill_process.wait(timeout=wait_timeout)
        except psutil_module.NoSuchProcess:
            return _OwnedProcessCleanupResult(
                "killed",
                terminated=True,
                killed=True,
            )
        except psutil_module.TimeoutExpired:
            final = _inspect_process_identity(
                pid=pid,
                create_time=create_time,
                name=name,
                psutil_module=psutil_module,
            )
            if final.state in _SAFE_STATES:
                return _OwnedProcessCleanupResult(
                    "killed",
                    terminated=True,
                    killed=True,
                )
            if final.state == "exact":
                return _OwnedProcessCleanupResult(
                    "survivor",
                    terminated=True,
                    killed=True,
                    error="process survived terminate, kill, and both waits",
                )
            return _result_from_inspection(
                final,
                terminated=True,
                killed=True,
            )
        except psutil_module.AccessDenied as error:
            return _OwnedProcessCleanupResult(
                "wait_failed",
                terminated=True,
                killed=True,
                error=_error_text(error),
            )
        except (OSError, ValueError, TypeError) as error:
            return _OwnedProcessCleanupResult(
                "wait_failed",
                terminated=True,
                killed=True,
                error=_error_text(error),
            )
    except psutil_module.AccessDenied as error:
        return _OwnedProcessCleanupResult(
            "wait_failed",
            terminated=True,
            error=_error_text(error),
        )
    except (OSError, ValueError, TypeError) as error:
        return _OwnedProcessCleanupResult(
            "wait_failed",
            terminated=True,
            error=_error_text(error),
        )

    final = _inspect_process_identity(
        pid=pid,
        create_time=create_time,
        name=name,
        psutil_module=psutil_module,
    )
    if final.state in _SAFE_STATES:
        return _OwnedProcessCleanupResult("terminated", terminated=True)
    if final.state == "exact":
        return _OwnedProcessCleanupResult(
            "survivor",
            terminated=True,
            error="process remained exact after terminate wait completed",
        )
    return _result_from_inspection(final, terminated=True)


def _cleanup_after_trigger(
    *,
    lock_file: Path,
    ras_pid: int,
    ras_create_time: float,
    ras_name: str,
    wait_timeout: float = 10.0,
    psutil_module: Any = psutil,
) -> Tuple[int, _OwnedProcessCleanupResult]:
    """Clean the owned process and remove its lock only after proof."""
    result = _cleanup_owned_process(
        pid=ras_pid,
        create_time=ras_create_time,
        name=ras_name,
        wait_timeout=wait_timeout,
        psutil_module=psutil_module,
    )
    if not result.safe_to_remove_lock:
        return 2, result
    try:
        lock_file.unlink(missing_ok=True)
    except OSError as error:
        return 3, _OwnedProcessCleanupResult(
            state=result.state,
            terminated=result.terminated,
            killed=result.killed,
            error=f"lock removal failed: {_error_text(error)}",
        )
    return 0, result


def _run_watchdog(
    *,
    parent_pid: int,
    parent_create_time: float,
    parent_name: str,
    ras_pid: int,
    ras_create_time: float,
    ras_name: str,
    max_runtime: float,
    lock_file: Path,
    check_interval: float = 5.0,
    psutil_module: Any = psutil,
    time_module: Any = time,
) -> int:
    """Monitor the exact parent identity and clean on orphan or timeout."""
    started = time_module.time()
    while True:
        time_module.sleep(check_interval)
        if not lock_file.exists():
            return 0

        parent = _inspect_process_identity(
            pid=parent_pid,
            create_time=parent_create_time,
            name=parent_name,
            psutil_module=psutil_module,
        )
        if parent.state in _SAFE_STATES:
            exit_code, result = _cleanup_after_trigger(
                lock_file=lock_file,
                ras_pid=ras_pid,
                ras_create_time=ras_create_time,
                ras_name=ras_name,
                psutil_module=psutil_module,
            )
            if exit_code:
                print(
                    f"[Watchdog] orphan cleanup failed: {result.state}: "
                    f"{result.error or 'no detail'}",
                    file=sys.stderr,
                    flush=True,
                )
            return exit_code
        if parent.state != "exact":
            print(
                f"[Watchdog] parent identity query failed: {parent.state}: "
                f"{parent.error or 'no detail'}",
                file=sys.stderr,
                flush=True,
            )
            return 2

        if time_module.time() - started > max_runtime:
            exit_code, result = _cleanup_after_trigger(
                lock_file=lock_file,
                ras_pid=ras_pid,
                ras_create_time=ras_create_time,
                ras_name=ras_name,
                psutil_module=psutil_module,
            )
            if exit_code:
                print(
                    f"[Watchdog] timeout cleanup failed: {result.state}: "
                    f"{result.error or 'no detail'}",
                    file=sys.stderr,
                    flush=True,
                )
            return exit_code


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--parent-create-time", required=True, type=float)
    parser.add_argument("--parent-name", required=True)
    parser.add_argument("--ras-pid", required=True, type=int)
    parser.add_argument("--ras-create-time", required=True, type=float)
    parser.add_argument("--ras-name", required=True)
    parser.add_argument("--max-runtime", required=True, type=float)
    parser.add_argument("--lock-file", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return _run_watchdog(
        parent_pid=args.parent_pid,
        parent_create_time=args.parent_create_time,
        parent_name=args.parent_name,
        ras_pid=args.ras_pid,
        ras_create_time=args.ras_create_time,
        ras_name=args.ras_name,
        max_runtime=args.max_runtime,
        lock_file=args.lock_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
