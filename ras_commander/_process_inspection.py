"""Strict Windows HEC-RAS process inspection and exact path matching.

This private module is shared by :mod:`RasControl` host inspection and
:mod:`RasCmdr` plan-specific cancellation.  It never selects a process from a
substring or basename match.
"""

from __future__ import annotations

import math
import ntpath
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .ComputeResults import (
    PlanProcessInventory,
    RasProcessInventory,
    RasProcessQueryError,
    RasProcessRecord,
)

# Exact executable names observed in read-only inventories of the installed
# HEC-RAS 4.0, 4.1.0, 6.1, 6.6, and 7.0 distributions.  This host-wide safety
# boundary includes launchers, supported command-line drivers, hydraulic
# solvers, geometry preprocessors, and sediment/water-quality engines.  It
# deliberately excludes generic IPC/runtime helpers, testing tools, plotters,
# and GUI/viewer-only programs: a shared vendor directory or a name containing
# ``Ras`` is never sufficient for classification.
#
# Legacy engines generally use unprefixed names.  Modern engines generally use
# the ``Ras`` prefix, while SIAM and the kinetics interfaces retain their own
# names.  Comparisons remain case-insensitive exact-name comparisons.
_RAS_PROCESS_NAMES = frozenset(
    {
        "adh.exe",
        "adh_hot.exe",
        "kinetics_wpf_interface.exe",
        "kineticsinterface.exe",
        "pre_adh.exe",
        "ras.exe",
        "rasprocess.exe",
        "geompreprocessor.exe",
        "siam.exe",
        "steady.exe",
        "unsteady.exe",
        "sediment.exe",
        "wqnet.exe",
        "rasgeompreprocess.exe",
        "rassteady.exe",
        "rasunsteady.exe",
        "rasquasirvsm.exe",
        "rasquasisediment.exe",
        "rasunsteadysediment.exe",
        "raswaterquality.exe",
    }
)

# Only these processes currently expose a command signature that can be tied
# to one exact project plan without inference.  Other globally inventoried
# engines still block a host-wide quiescence claim, but are never selected for
# plan-specific cancellation merely because they are HEC-RAS compute engines.
_PLAN_MATCHABLE_PROCESS_NAMES = frozenset(
    {
        "ras.exe",
        "rassteady.exe",
        "rasunsteady.exe",
        "steady.exe",
        "unsteady.exe",
    }
)


@dataclass(frozen=True)
class _ProcessScan:
    inventory: RasProcessInventory
    handles: Dict[Tuple[int, float], Any]


def _query_error(
    *,
    pid: Optional[int],
    operation: str,
    error: BaseException,
) -> RasProcessQueryError:
    exception_type = type(error).__name__
    normalized_type = exception_type.casefold()
    if "accessdenied" in normalized_type:
        reason_code = "access_denied"
    elif "nosuchprocess" in normalized_type:
        reason_code = "process_exited_during_query"
    elif "zombieprocess" in normalized_type:
        reason_code = "zombie_process"
    else:
        reason_code = "process_query_failed"
    return RasProcessQueryError(
        pid=pid,
        operation=operation,
        reason_code=reason_code,
        exception_type=exception_type,
        detail=str(error),
    )


def _read_process_value(process: Any, field: str) -> Any:
    """Read one psutil value while supporting its ``process_iter`` cache."""
    info = getattr(process, "info", None)
    if isinstance(info, dict) and field in info and info[field] is not None:
        return info[field]
    if field == "pid":
        return process.pid
    accessor = getattr(process, field)
    return accessor()


def _scan_ras_process_handles(
    *,
    tracked_pids: Iterable[int] = (),
    tracked_sessions: Optional[Mapping[Tuple[int, float], str]] = None,
    psutil_module: Any,
) -> _ProcessScan:
    """Return a strict inventory plus private handles for safe signalling."""
    tracked = {int(pid) for pid in tracked_pids}
    sessions = {
        (int(identity[0]), float(identity[1])): str(session_id)
        for identity, session_id in (tracked_sessions or {}).items()
    }
    records = []
    errors = []
    handles: Dict[Tuple[int, float], Any] = {}

    try:
        process_iterator = psutil_module.process_iter(
            ["pid", "name", "create_time", "cmdline", "exe", "cwd"]
        )
        for process in process_iterator:
            pid: Optional[int] = None
            name: Optional[str] = None
            try:
                pid = int(_read_process_value(process, "pid"))
                name = str(_read_process_value(process, "name")).strip()
                if not name:
                    raise ValueError("process name is empty")
            except Exception as error:
                errors.append(
                    _query_error(
                        pid=pid,
                        operation="classify_process",
                        error=error,
                    )
                )
                continue

            if name.casefold() not in _RAS_PROCESS_NAMES:
                continue
            if pid <= 0:
                errors.append(
                    _query_error(
                        pid=pid,
                        operation="classify_process",
                        error=ValueError("HEC-RAS process pid must be positive"),
                    )
                )
                continue

            values: Dict[str, Any] = {}
            process_complete = True
            for field in ("create_time", "cmdline", "exe", "cwd"):
                try:
                    values[field] = _read_process_value(process, field)
                except Exception as error:
                    process_complete = False
                    errors.append(
                        _query_error(
                            pid=pid,
                            operation=f"query_{field}",
                            error=error,
                        )
                    )

            if not process_complete:
                continue
            try:
                create_time = float(values["create_time"])
                if not math.isfinite(create_time) or create_time <= 0:
                    raise ValueError("process create_time must be finite and positive")
                raw_cmdline = values["cmdline"]
                if not isinstance(raw_cmdline, (list, tuple)) or not raw_cmdline:
                    raise ValueError("process command line is missing or malformed")
                cmdline = tuple(str(token) for token in raw_cmdline)
                exe = None if values["exe"] is None else str(values["exe"])
                cwd = None if values["cwd"] is None else str(values["cwd"])
            except (TypeError, ValueError) as error:
                errors.append(
                    _query_error(
                        pid=pid,
                        operation="normalize_process_metadata",
                        error=error,
                    )
                )
                continue

            record = RasProcessRecord(
                pid=pid,
                create_time=create_time,
                name=name,
                executable_path=exe,
                command_line=cmdline,
                working_directory=cwd,
                tracked=(pid, create_time) in sessions or pid in tracked,
                session_id=sessions.get((pid, create_time)),
            )
            records.append(record)
            handles[record.identity] = process
    except Exception as error:
        errors.append(
            _query_error(
                pid=None,
                operation="enumerate_processes",
                error=error,
            )
        )

    records.sort(key=lambda item: item.identity)
    inventory = RasProcessInventory(
        observed_at=time.time(),
        complete=not errors,
        processes=tuple(records),
        query_errors=tuple(errors),
    )
    return _ProcessScan(inventory=inventory, handles=handles)


def scan_ras_processes(
    *,
    tracked_pids: Iterable[int] = (),
    tracked_sessions: Optional[Mapping[Tuple[int, float], str]] = None,
    psutil_module: Any,
) -> RasProcessInventory:
    """Return a strict host-wide HEC-RAS compute-process inventory.

    The exact-name taxonomy covers legacy and modern launchers, solvers,
    sediment/water-quality engines, and geometry preprocessors.  It excludes
    HEC-RAS GUI viewers and plotting/testing helpers.
    """
    return _scan_ras_process_handles(
        tracked_pids=tracked_pids,
        tracked_sessions=tracked_sessions,
        psutil_module=psutil_module,
    ).inventory


def normalize_windows_path_token(token: str, cwd: Optional[str] = None) -> str:
    """Normalize one command token as a Windows path for exact comparison."""
    value = str(token).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    value = value.replace("/", "\\")
    lowered = value.casefold()
    if lowered.startswith("\\\\?\\unc\\"):
        value = "\\\\" + value[8:]
    elif lowered.startswith("\\\\?\\"):
        value = value[4:]
    elif lowered.startswith("\\??\\"):
        value = value[4:]

    if not ntpath.isabs(value):
        if not cwd:
            return ""
        base = str(cwd).replace("/", "\\")
        base_lowered = base.casefold()
        if base_lowered.startswith("\\\\?\\unc\\"):
            base = "\\\\" + base[8:]
        elif base_lowered.startswith("\\\\?\\"):
            base = base[4:]
        value = ntpath.join(base, value)
    return ntpath.normcase(ntpath.normpath(value)).casefold()


def _command_has_exact_path(
    command: Sequence[str],
    target: Path,
    cwd: Optional[str],
) -> bool:
    normalized_target = normalize_windows_path_token(str(target), cwd=None)
    for token in command:
        normalized_token = normalize_windows_path_token(token, cwd=cwd)
        if not normalized_token:
            continue
        if _same_windows_path(normalized_token, normalized_target):
            return True
    return False


def _same_windows_path(left: str, right: str) -> bool:
    """Compare normalized Windows paths, including accessible file aliases."""
    normalized_left = normalize_windows_path_token(left, cwd=None)
    normalized_right = normalize_windows_path_token(right, cwd=None)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    if os.name == "nt":
        try:
            return os.path.samefile(normalized_left, normalized_right)
        except (OSError, ValueError):
            pass
    return False


def _command_has_exact_marker(command: Sequence[str], marker: str) -> bool:
    """Return true only for a complete non-path command token match."""
    expected = marker.casefold()
    for token in command:
        value = str(token).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value.casefold() == expected:
            return True
    return False


def _resolve_plan_computation_file(
    *,
    project_path: Path,
    plan_path: Path,
) -> Optional[Path]:
    """Resolve the project-specific ``.cNN`` token from a readable plan."""
    try:
        plan_bytes = plan_path.read_bytes()
    except OSError:
        return None
    match = re.search(
        rb"(?im)^\s*Geom File\s*=\s*g([0-9]+)\s*$",
        plan_bytes,
    )
    if match is None:
        return None
    geometry_number = match.group(1).decode("ascii")
    return project_path.parent / f"{project_path.stem}.c{geometry_number}"


def match_plan_processes(
    inventory: RasProcessInventory,
    *,
    plan_number: str,
    project_path: Path,
    plan_path: Path,
    tmp_hdf_path: Path,
) -> PlanProcessInventory:
    """Narrow a strict inventory using exact command-token path matches."""
    run_file_path = project_path.parent / (
        f"{project_path.stem}.r{plan_number}"
    )
    computation_file_path = _resolve_plan_computation_file(
        project_path=project_path,
        plan_path=plan_path,
    )
    matches = []
    for process in inventory.processes:
        name = process.name.casefold()
        if name not in _PLAN_MATCHABLE_PROCESS_NAMES:
            continue
        if name == "ras.exe":
            matched = _command_has_exact_path(
                process.command_line,
                project_path,
                process.working_directory,
            ) and _command_has_exact_path(
                process.command_line,
                plan_path,
                process.working_directory,
            )
        elif name in {"rassteady.exe", "steady.exe"}:
            # Both legacy and modern steady solvers receive the exact .rNN
            # run file.  A basename or partial token is never sufficient.
            matched = _command_has_exact_path(
                process.command_line,
                run_file_path,
                process.working_directory,
            )
        elif name in {"rasunsteady.exe", "unsteady.exe"}:
            tmp_hdf_match = _command_has_exact_path(
                process.command_line,
                tmp_hdf_path,
                process.working_directory,
            )
            # Native Windows RasUnsteady invocations are version-specific.
            # Some modern versions pass the tmp HDF directly; others pass a
            # project-specific computation file plus the exact plan marker
            # ``bNN`` while using the project directory as cwd. The latter was
            # confirmed on HEC-RAS 6.3.1. Requiring both exact cwd identity and
            # the complete marker avoids basename/substring selection.
            marker_match = (
                process.working_directory is not None
                and _same_windows_path(
                    process.working_directory,
                    str(project_path.parent),
                )
                and _command_has_exact_marker(
                    process.command_line,
                    f"b{plan_number}",
                )
                and (
                    computation_file_path is None
                    or _command_has_exact_path(
                        process.command_line,
                        computation_file_path,
                        process.working_directory,
                    )
                )
            )
            matched = tmp_hdf_match or marker_match
        else:
            matched = False
        if matched:
            matches.append(process)

    matching_processes = tuple(sorted(matches, key=lambda item: item.identity))
    return PlanProcessInventory(
        observed_at=inventory.observed_at,
        plan_number=plan_number,
        project_path=str(project_path),
        plan_path=str(plan_path),
        tmp_hdf_path=str(tmp_hdf_path),
        complete=inventory.complete,
        matched=matching_processes,
        query_errors=inventory.query_errors,
    )
