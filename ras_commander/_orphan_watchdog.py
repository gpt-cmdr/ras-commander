"""Minimal fail-closed worker for RasControl orphan cleanup.

This module is executed as a standalone Python file by :mod:`RasControl` so
the watchdog does not need to import the full package in its child process.
It signals only a process whose PID, creation time, and exact image name match
the identity captured by the Controller parent.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import psutil


_SAFE_STATES = frozenset({"absent", "stopped", "pid_reused", "terminated", "killed"})


def _publish_worker_identity(identity_file: Path, token: str) -> dict[str, Any]:
    """Publish the actual interpreter identity before arming the watchdog.

    On Windows a virtual-environment Python launcher can create a second
    interpreter process. Its Popen PID is not necessarily this worker's PID.
    The parent verifies this nonce-bound record against the live process and
    launcher ancestry before recording an identity eligible for cleanup.
    Publication is atomic and never replaces an existing record.
    """
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{32,64}", token) is None:
        raise ValueError("watchdog identity token must be 32 to 64 lowercase hex characters")
    process = psutil.Process(os.getpid())
    payload = {
        "schema": "ras-commander-orphan-watchdog/v1",
        "token": token,
        "pid": os.getpid(),
        "create_time": float(process.create_time()),
        "name": str(process.name()),
        "exe": str(process.exe()),
        "parent_pid": os.getppid(),
        "argv": list(sys.argv),
    }
    if (
        not math.isfinite(payload["create_time"])
        or payload["create_time"] <= 0
        or not payload["name"]
        or not payload["exe"]
    ):
        raise ValueError("watchdog worker identity is incomplete")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=identity_file.parent,
            prefix=identity_file.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # A same-directory hard link is atomic and fails if the destination
        # already exists, including a symlink. Never overwrite retained proof.
        os.link(temporary, identity_file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return payload


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
    deadline = time_module.monotonic() + max_runtime
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

        if time_module.monotonic() > deadline:
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
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--identity-token")
    args = parser.parse_args(argv)
    if (args.identity_file is None) != (args.identity_token is None):
        parser.error("--identity-file and --identity-token must be supplied together")
    if not math.isfinite(args.max_runtime) or args.max_runtime <= 0:
        parser.error("--max-runtime must be finite and positive")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.identity_file is not None:
        try:
            _publish_worker_identity(args.identity_file, args.identity_token)
        except (OSError, ValueError, psutil.Error) as error:
            print(
                f"[Watchdog] identity publication failed: {_error_text(error)}",
                file=sys.stderr, flush=True,
            )
            return 2  # Do not arm an unidentifiable cleanup worker.
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
