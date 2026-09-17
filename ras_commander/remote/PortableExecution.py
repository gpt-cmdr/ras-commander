"""Steady-plan result validation for portable and local execution.

:func:`validate_steady_results` checks that a computed steady plan HDF carries
finite results for every authored profile and that each result cross section's
flow matches the effective authored flow schedule. It is exported top-level as
``from ras_commander import validate_steady_results``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from ..RasSteady import RasSteady
from ..hdf.HdfResultsPlan import HdfResultsPlan


logger = get_logger(__name__)
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


def _station(value: Any) -> float:
    match = _NUMBER.search(str(value))
    if not match:
        raise ValueError(f"River station is not numeric: {value!r}")
    return float(match.group())


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


@log_call
def validate_steady_results(
    hdf_path: Union[str, Path],
    flow_path: Union[str, Path],
    *,
    absolute_tolerance: float = 0.01,
    relative_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Validate steady HDF rows and the effective authored flow schedule.

    Flow changes are applied downstream in descending river-station order for
    each river/reach. Every steady result cross section must map to an authored
    effective flow for its profile within ``max(abs_tol, rel_tol * |flow|)``.
    The function never raises for unreadable or inconsistent inputs; it fails
    closed with ``passed=False`` and one or more reason codes.

    Args:
        hdf_path (Union[str, Path]): Computed steady plan HDF (``.p##.hdf``).
        flow_path (Union[str, Path]): Steady flow file (``.f##``) the plan ran with.
        absolute_tolerance (float): Absolute flow tolerance (model units).
        relative_tolerance (float): Relative flow tolerance.

    Returns:
        dict[str, Any]: Summary with ``passed`` (bool), ``reason_codes``
        (list of str), ``result_row_count``, ``authored_profile_count``,
        ``result_profile_count``, ``flow_rows_compared``,
        ``flow_rows_unmatched``, ``flow_mismatch_count``,
        ``max_absolute_flow_mismatch``, ``max_relative_flow_mismatch``, the two
        tolerances, and ``error``/``missing_columns`` when applicable. Reason
        codes: ``STEADY_RESULTS_UNREADABLE``, ``STEADY_RESULTS_EMPTY``,
        ``STEADY_PROFILE_MISMATCH``, ``STEADY_RESULT_COLUMNS_MISSING``,
        ``STEADY_NONFINITE_FLOW``, ``STEADY_NONFINITE_WSEL``,
        ``STEADY_FLOW_SCHEDULE_INVALID``, ``STEADY_FLOW_SCHEDULE_UNMATCHED``,
        ``STEADY_FLOW_SCHEDULE_MISMATCH``, ``STEADY_FLOW_ROWS_NOT_COMPARED``.

    Examples:
        >>> from ras_commander import validate_steady_results
        >>> summary = validate_steady_results("Model.p01.hdf", "Model.f01")
        >>> summary["passed"], summary["reason_codes"]  # doctest: +SKIP
        (True, [])
    """
    reason_codes = []
    summary = {
        "passed": False,
        "reason_codes": reason_codes,
        "result_row_count": 0,
        "authored_profile_count": 0,
        "result_profile_count": 0,
        "flow_rows_compared": 0,
        "flow_rows_unmatched": 0,
        "flow_mismatch_count": 0,
        "max_absolute_flow_mismatch": None,
        "max_relative_flow_mismatch": None,
        "flow_tolerance_absolute": absolute_tolerance,
        "flow_tolerance_relative": relative_tolerance,
    }
    try:
        authored = RasSteady.read_flow_file(Path(flow_path))
        authored_profiles = [str(item).strip() for item in authored["profile_names"]]
        result_profiles = [
            str(item).strip()
            for item in HdfResultsPlan.get_steady_profile_names(Path(hdf_path))
        ]
        results = HdfResultsPlan.get_steady_results(Path(hdf_path))
    except Exception as exc:
        reason_codes.append("STEADY_RESULTS_UNREADABLE")
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary

    summary["result_row_count"] = len(results)
    summary["authored_profile_count"] = len(authored_profiles)
    summary["result_profile_count"] = len(result_profiles)
    if results.empty:
        reason_codes.append("STEADY_RESULTS_EMPTY")
    if len(authored_profiles) != len(result_profiles) or set(authored_profiles) != set(
        result_profiles
    ):
        reason_codes.append("STEADY_PROFILE_MISMATCH")
    required = {"river", "reach", "node_id", "profile", "flow", "wsel"}
    if not required.issubset(results.columns):
        reason_codes.append("STEADY_RESULT_COLUMNS_MISSING")
        summary["missing_columns"] = sorted(required - set(results.columns))
        return summary

    finite_flow = results["flow"].map(_finite)
    finite_wsel = results["wsel"].map(_finite)
    if not finite_flow.all():
        reason_codes.append("STEADY_NONFINITE_FLOW")
    if not finite_wsel.all():
        reason_codes.append("STEADY_NONFINITE_WSEL")

    schedule = {}
    try:
        for change in authored["flow_changes"]:
            key = (str(change["river"]).strip(), str(change["reach"]).strip())
            schedule.setdefault(key, []).append(
                (
                    _station(change["station"]),
                    [float(item) for item in change["flows"]],
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        reason_codes.append("STEADY_FLOW_SCHEDULE_INVALID")
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
    for changes in schedule.values():
        changes.sort(key=lambda item: item[0], reverse=True)

    profile_index = {name: index for index, name in enumerate(authored_profiles)}
    absolute_mismatches = []
    relative_mismatches = []
    unmatched = 0
    mismatches = 0
    compared = 0
    for row in results.itertuples(index=False):
        key = (str(row.river).strip(), str(row.reach).strip())
        try:
            station = _station(row.node_id)
            index = profile_index[str(row.profile).strip()]
            candidates = [item for item in schedule.get(key, []) if item[0] >= station]
            selected = min(candidates, key=lambda item: item[0])
            expected = selected[1][index]
        except (KeyError, ValueError, IndexError):
            unmatched += 1
            continue
        if not _finite(row.flow):
            continue
        actual = float(row.flow)
        compared += 1
        absolute = abs(actual - expected)
        relative = absolute / max(abs(expected), absolute_tolerance, 1e-12)
        absolute_mismatches.append(absolute)
        relative_mismatches.append(relative)
        tolerance = max(absolute_tolerance, relative_tolerance * abs(expected))
        if absolute > tolerance:
            mismatches += 1

    summary.update(
        {
            "flow_rows_compared": compared,
            "flow_rows_unmatched": unmatched,
            "flow_mismatch_count": mismatches,
            "max_absolute_flow_mismatch": (
                max(absolute_mismatches) if absolute_mismatches else None
            ),
            "max_relative_flow_mismatch": (
                max(relative_mismatches) if relative_mismatches else None
            ),
        }
    )
    if unmatched:
        reason_codes.append("STEADY_FLOW_SCHEDULE_UNMATCHED")
    if mismatches:
        reason_codes.append("STEADY_FLOW_SCHEDULE_MISMATCH")
    if not compared:
        reason_codes.append("STEADY_FLOW_ROWS_NOT_COMPARED")
    summary["passed"] = not reason_codes
    return summary
