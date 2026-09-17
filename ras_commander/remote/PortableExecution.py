"""Portable one-core steady-plan execution and steady result validation.

:func:`execute_request` is the common in-container entry point for Docker and
Slurm/Apptainer. It never computes in the source project: a complete project
tree is copied to the request's isolated output directory before
:class:`RasCmdr` is initialized, and the outcome is written as a
``ras-commander-execution-receipt/v1`` JSON receipt.

:func:`validate_steady_results` checks that a computed steady plan HDF carries
finite results for every authored profile and that each result cross section's
flow matches the effective authored flow schedule. It is exported top-level as
``from ras_commander import validate_steady_results``.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from ..RasCmdr import RasCmdr
from ..RasPlan import RasPlan
from ..RasPrj import RasPrj
from ..RasSteady import RasSteady
from ..hdf.HdfResultsPlan import HdfResultsPlan
from ..results.ResultsParser import ResultsParser
from .ExecutionContract import (
    STORED_MAPS_OUTPUT_DIRECTORY,
    PreprocessPolicy,
    RasExecutionReceipt,
    RasExecutionRequest,
    sha256_file,
    utc_now,
)


logger = get_logger(__name__)
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
_GEOMETRY_FILE = re.compile(r"^\s*Geom File\s*=\s*g([0-9]+)\s*$", re.IGNORECASE)


def _copytree_with_file_digest(
    source_root: Path,
    destination_root: Path,
    selected_file: Path,
) -> tuple[str, str]:
    """Copy one tree while hashing the exact bytes written to the runtime copy."""
    root = source_root.resolve()
    selected = selected_file.resolve()
    if not root.is_dir() or not selected.is_file() or not selected.is_relative_to(root):
        raise ValueError("Selected project must be a regular member of its project tree")
    if destination_root.exists():
        raise FileExistsError(f"Runtime project directory already exists: {destination_root}")

    items = list(root.rglob("*"))
    links = [item for item in items if item.is_symlink()]
    if links:
        raise ValueError(f"Project trees cannot contain symbolic links: {links[0]}")

    destination_root.mkdir(parents=True)
    directories = sorted(
        (item for item in items if item.is_dir()),
        key=lambda item: (len(item.relative_to(root).parts), item.as_posix()),
    )
    for directory in directories:
        (destination_root / directory.relative_to(root)).mkdir()

    tree_digest = hashlib.sha256()
    project_digest = hashlib.sha256()
    selected_seen = False
    files = sorted(
        (item for item in items if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for source in files:
        relative = source.relative_to(root)
        destination = destination_root / relative
        is_selected = source.resolve() == selected
        selected_seen = selected_seen or is_selected
        tree_digest.update(relative.as_posix().encode("utf-8"))
        tree_digest.update(b"\0")
        with source.open("rb") as reader, destination.open("xb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(block)
                tree_digest.update(block)
                if is_selected:
                    project_digest.update(block)
        tree_digest.update(b"\0")
        shutil.copystat(source, destination, follow_symlinks=False)

    if not selected_seen:
        raise ValueError("Selected project disappeared while staging the runtime tree")
    for directory in reversed(directories):
        shutil.copystat(
            directory,
            destination_root / directory.relative_to(root),
            follow_symlinks=False,
        )
    shutil.copystat(root, destination_root, follow_symlinks=False)
    return tree_digest.hexdigest(), project_digest.hexdigest()


def _geometry_number(plan_path: Path) -> str:
    for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _GEOMETRY_FILE.match(line)
        if match:
            return match.group(1)
    raise ValueError(f"Plan has no Geom File reference: {plan_path}")


def _prepare_preprocessing(
    policy: str, runtime_project: Path, plan_path: Path
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    """Perform fail-closed preprocessing cleanup before RasCmdr is invoked."""
    geometry_number = _geometry_number(plan_path)
    c_path = runtime_project.parent / f"{runtime_project.stem}.c{geometry_number}"
    geom_hdf = runtime_project.parent / (
        f"{runtime_project.stem}.g{geometry_number}.hdf"
    )
    candidates = (c_path, geom_hdf)
    value = PreprocessPolicy(policy)
    targets = ()
    required_outputs = ()
    retained = []
    if value is PreprocessPolicy.REUSE:
        for path in candidates:
            if path.is_file() and path.stat().st_size > 0:
                retained.append(
                    {
                        "path": path.name,
                        "size_bytes": path.stat().st_size,
                        "mtime_ns": path.stat().st_mtime_ns,
                    }
                )
        if not retained:
            raise ValueError(
                "REUSE requires an existing nonempty compiled geometry artifact: "
                f"{c_path.name} or {geom_hdf.name}"
            )
        required_outputs = tuple(
            runtime_project.parent / item["path"] for item in retained
        )
    elif value is PreprocessPolicy.REBUILD:
        targets = (c_path,)
        required_outputs = candidates
    elif value is PreprocessPolicy.FORCE_REBUILD:
        targets = candidates
        required_outputs = candidates
    preexisting = [
        {
            "path": path.name,
            "size_bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in candidates
        if path.is_file() and path.stat().st_size > 0
    ]
    verified_absent = {path.name for path in candidates if not path.exists()}
    removed = []
    for path in targets:
        if path.exists():
            before = path.stat()
            path.unlink()
            if path.exists():
                raise RuntimeError(f"Preprocessor artifact could not be removed: {path}")
            removed.append(
                {
                    "path": path.name,
                    "size_bytes": before.st_size,
                    "mtime_ns": before.st_mtime_ns,
                }
            )
        verified_absent.add(path.name)
    evidence = {
        "requested_policy": value.value,
        "effective_action": (
            "reuse" if value is PreprocessPolicy.REUSE else "explicit-clean-and-rebuild"
        ),
        "removed_artifacts": removed,
        "retained_artifacts_before": retained,
        "preexisting_artifacts": preexisting,
        "verified_absent_before_compute": sorted(verified_absent),
        "candidate_outputs": [path.name for path in candidates],
        "required_outputs": [path.name for path in required_outputs],
        "passed": False,
    }
    return evidence, required_outputs


def _complete_preprocessing_evidence(
    evidence: dict[str, Any], required_outputs: tuple[Path, ...], run_started_ns: int
) -> bool:
    if evidence["effective_action"] == "reuse":
        after = []
        for path, prior in zip(
            required_outputs, evidence["retained_artifacts_before"]
        ):
            if not path.is_file() or path.stat().st_size <= 0:
                evidence["error"] = f"Retained preprocessor artifact missing: {prior['path']}"
                evidence["passed"] = False
                return False
            after.append(
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                }
            )
        evidence["retained_artifacts_after"] = after
        evidence["retained_unchanged"] = after == evidence["retained_artifacts_before"]
        evidence["passed"] = bool(after) and evidence["retained_unchanged"]
        return bool(evidence["passed"])
    generated = []
    verified_absent = set(evidence["verified_absent_before_compute"])
    for path in required_outputs:
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        fresh_for_run = (
            path.name in verified_absent or path.stat().st_mtime_ns >= run_started_ns
        )
        generated.append(
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
                "fresh_for_run": fresh_for_run,
                "created_after_verified_absence": path.name in verified_absent,
            }
        )
    evidence["generated_artifacts"] = generated
    # HEC-RAS 6.6 may compile 1D geometry to either the legacy c## file or the
    # geometry HDF. Reappearance after verified absence is strongest; a
    # rewritten pre-existing alternate is accepted only when fresh for this run.
    evidence["passed"] = any(item["fresh_for_run"] for item in generated)
    if not evidence["passed"]:
        evidence["error"] = "No fresh compiled geometry artifact was produced"
    return bool(evidence["passed"])


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


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


@log_call
def execute_request(request_path: Union[str, Path]) -> RasExecutionReceipt:
    """Execute a validated request and write ``execution_receipt.json``.

    The source project is verified once immediately before execution.  Hydraulic
    success requires all of the following: ``RasCmdr.compute_plan`` success,
    a non-empty plan HDF, a ``Complete Process`` compute message, no parsed
    compute errors. The solver runs only on an isolated source-tree copy.

    When the request carries a ``stored_maps`` block, maps are generated only
    after the steady results pass hydraulic validation, by
    ``RasProcess.store_maps_at_steady_profiles`` on the runtime copy with a
    freshly initialized project object, into ``<output>/maps``. The receipt's
    ``stored_maps`` section records the requested block, ``status``
    (``passed``, ``failed``, or ``skipped``), a reason code, elapsed seconds,
    one row per product with paths relative to the output directory, and any
    error. A mapping failure never changes ``solver_verified``,
    ``hydraulic_validated``, or ``result_validation``. Receipt ``success``
    requires hydraulic success and, when maps were requested, ``passed`` maps.

    Args:
        request_path: Path to a ``ras-commander-execution-request/v1`` JSON.

    Returns:
        RasExecutionReceipt: The validated hydraulic (and stored-map) execution
        evidence.

    Raises:
        ValueError: If request identity, source hashes, plan type, or isolation
            constraints are invalid.  Operational solver failures are recorded
            as failed receipts rather than raised.
    """
    request_file = Path(request_path).resolve()
    request = RasExecutionRequest.read(request_file)
    source_project, output_root = request.resolve_paths(request_file)
    if not source_project.is_file() or source_project.suffix.lower() != ".prj":
        raise ValueError(f"Missing source HEC-RAS project: {source_project}")

    source_tree = source_project.parent.resolve()
    _validate_initial_output(output_root, request)
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root = output_root / "runtime_project"
    receipt_path = output_root / "execution_receipt.json"
    tree_digest_before, project_digest_before = _copytree_with_file_digest(
        source_tree,
        runtime_root,
        source_project,
    )
    if project_digest_before != request.source_project_sha256:
        raise ValueError("Source project hash does not match execution request")
    if tree_digest_before != request.source_tree_sha256:
        raise ValueError("Source project tree hash does not match execution request")
    runtime_project = runtime_root / source_project.name
    started_at = utc_now()
    error = None
    diagnostics = {}
    messages = ""
    hdf_path = None
    result_hdf_digest = None
    compute_success = False
    solver_verified = False
    hydraulic_validated = False
    result_validation = {
        "passed": False,
        "reason_codes": ["STEADY_RESULTS_NOT_EVALUATED"],
    }
    preprocessing_evidence = {
        "requested_policy": request.preprocess_policy,
        "effective_action": "not-started",
        "passed": False,
    }
    fresh_result_evidence = {"passed": False, "reason": "not-started"}

    try:
        ras_object = RasPrj()
        ras_object.initialize(
            runtime_root,
            request.ras_executable,
            prj_file=runtime_project,
            load_results_summary=False,
        )
        if not RasPlan.is_plan_steady_state(
            request.plan_number, ras_object=ras_object
        ):
            raise ValueError(
                f"Plan {request.plan_number} is not classified as a steady plan"
            )

        plan_row = ras_object.plan_df[
            ras_object.plan_df["plan_number"] == request.plan_number
        ]
        if plan_row.empty or not str(plan_row.iloc[0].get("Flow Path", "")).strip():
            raise ValueError("Selected steady plan has no resolvable flow file")
        flow_path = Path(plan_row.iloc[0]["Flow Path"])
        plan_path = runtime_root / f"{runtime_project.stem}.p{request.plan_number}"
        if not plan_path.is_file():
            raise ValueError(f"Selected steady plan file is missing: {plan_path}")

        preprocessing_evidence, required_preprocess_outputs = _prepare_preprocessing(
            request.preprocess_policy, runtime_project, plan_path
        )
        # A copied historic result can never satisfy this execution request.
        hdf_path = runtime_root / (
            f"{runtime_project.stem}.p{request.plan_number}.hdf"
        )
        prior_hdf = None
        if hdf_path.exists():
            prior_hdf = {
                "size_bytes": hdf_path.stat().st_size,
                "mtime_ns": hdf_path.stat().st_mtime_ns,
            }
            hdf_path.unlink()
        if hdf_path.exists():
            raise RuntimeError("Pre-existing result HDF could not be removed")
        run_started_ns = time.time_ns()
        # RasCmdr.compute_plan launches Ras.exe shell-free with a quoted argv
        # command line, so no invocation override is needed here.  Geometry
        # preprocessor cleanup was performed and verified explicitly above.
        result = RasCmdr.compute_plan(
            request.plan_number,
            ras_object=ras_object,
            clear_geompre=False,
            force_geompre=False,
            force_rerun=True,
            num_cores=1,
            verify=True,
            max_runtime=float(request.timeout_seconds),
        )
        preprocess_ok = _complete_preprocessing_evidence(
            preprocessing_evidence, required_preprocess_outputs, run_started_ns
        )
        if hdf_path.is_file() and hdf_path.stat().st_size > 0:
            messages = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path) or ""
            diagnostics = ResultsParser.parse_compute_messages(messages)
            result_hdf_digest = sha256_file(hdf_path)
            fresh_result_evidence = {
                "passed": True,
                "prior_hdf": prior_hdf,
                "verified_absent_before_compute": True,
                "created_after_run_start": hdf_path.stat().st_mtime_ns
                >= run_started_ns,
                "size_bytes": hdf_path.stat().st_size,
                "mtime_ns": hdf_path.stat().st_mtime_ns,
                "sha256": result_hdf_digest,
            }
        else:
            diagnostics = {
                "completed": False,
                "has_errors": True,
                "has_warnings": False,
                "error_count": 1,
                "warning_count": 0,
                "first_error_line": "Missing or empty plan HDF",
            }
        solver_verified = bool(
            result
            and preprocess_ok
            and hdf_path.is_file()
            and hdf_path.stat().st_size > 0
            and fresh_result_evidence["passed"]
            and diagnostics.get("completed")
            and not diagnostics.get("has_errors")
        )
        if solver_verified:
            result_validation = validate_steady_results(
                hdf_path,
                flow_path,
                absolute_tolerance=request.flow_tolerance_absolute,
                relative_tolerance=request.flow_tolerance_relative,
            )
            hydraulic_validated = bool(result_validation["passed"])
        compute_success = solver_verified and hydraulic_validated
        if not solver_verified:
            error = getattr(result, "error", None) or diagnostics.get(
                "first_error_line"
            ) or "HEC-RAS compute did not pass HDF and compute-message validation"
        elif not hydraulic_validated:
            error = "Steady results failed hydraulic validation: " + ", ".join(
                result_validation["reason_codes"]
            )
    except Exception as exc:
        logger.exception("Portable execution failed for %s", request.execution_id)
        error = f"{type(exc).__name__}: {exc}"

    # The copied snapshot matched the request before use, and the solver only
    # targets that isolated copy. Preserve v1 fields without a post-run source read.
    tree_digest_after = tree_digest_before
    source_unchanged = True

    message_path = output_root / "compute_messages.txt"
    if messages:
        message_path.write_text(messages, encoding="utf-8", newline="\n")

    stored_maps = None
    if request.stored_maps is not None:
        if compute_success:
            stored_maps = _run_stored_maps(
                request,
                runtime_root,
                runtime_project,
                output_root,
                hdf_path,
                result_hdf_digest,
            )
        else:
            stored_maps = _stored_maps_section(
                request,
                "skipped",
                "STORED_MAPS_SKIPPED_HYDRAULICS_NOT_VALIDATED",
            )
        if compute_success and stored_maps["status"] != "passed" and error is None:
            error = (
                f"Stored maps failed ({stored_maps['reason_code']}): "
                f"{stored_maps['error']}"
            )

    success = bool(
        compute_success
        and source_unchanged
        and (stored_maps is None or stored_maps["status"] == "passed")
    )
    diagnostics = dict(diagnostics)
    diagnostics["source_validation"] = {
        "passed": True,
        "method": "single-pass-runtime-copy-and-hash",
        "post_compute_rehash": False,
        "execution_target": "isolated-runtime-copy",
    }
    diagnostics["preprocessing"] = preprocessing_evidence
    diagnostics["fresh_result"] = fresh_result_evidence
    runtime_identity = os.environ.get(
        "RAS_COMMANDER_RUNTIME_CONTAINER_IDENTITY", request.container_identity
    )
    receipt = RasExecutionReceipt(
        execution_id=request.execution_id,
        request_sha256=request.digest,
        container_identity=request.container_identity,
        runtime_container_identity=runtime_identity,
        success=success,
        status="succeeded" if success else "failed",
        started_at=started_at,
        finished_at=utc_now(),
        source_tree_sha256_before=tree_digest_before,
        source_tree_sha256_after=tree_digest_after,
        source_unchanged=source_unchanged,
        solver_verified=solver_verified,
        hydraulic_validated=hydraulic_validated,
        result_validation=result_validation,
        runtime_project_path=_relative(runtime_root, output_root),
        result_hdf_path=(
            _relative(hdf_path, output_root)
            if hdf_path is not None and hdf_path.is_file()
            else None
        ),
        result_hdf_sha256=result_hdf_digest,
        compute_messages_sha256=None,
        compute_messages_length=len(messages),
        compute_diagnostics=diagnostics,
        error=error,
        stored_maps=stored_maps,
    )
    receipt.write(receipt_path)
    return receipt


def _stored_maps_section(
    request: RasExecutionRequest,
    status: str,
    reason_code: str,
    *,
    elapsed_seconds: float | None = None,
    products: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Return one receipt ``stored_maps`` section."""
    return {
        "requested": request.stored_maps.to_dict(),
        "status": status,
        "reason_code": reason_code,
        "elapsed_seconds": elapsed_seconds,
        "output_directory": STORED_MAPS_OUTPUT_DIRECTORY,
        "products": products or [],
        "error": error,
    }


def _stored_map_products(frame: Any, output_root: Path) -> list[dict[str, Any]]:
    """Convert the steady stored-map frame to receipt product rows."""
    required = {"profile_index", "profile_name", "map_type", "primary_path", "file_count"}
    missing = required - set(getattr(frame, "columns", ()))
    if missing:
        raise _StoredMapsError(
            "STORED_MAPS_OUTPUT_INVALID",
            "Stored-map frame is missing columns: " + ", ".join(sorted(missing)),
        )
    maps_root = (output_root / STORED_MAPS_OUTPUT_DIRECTORY).resolve()
    products = []
    for row in frame.itertuples(index=False):
        primary_text = row.primary_path
        if not isinstance(primary_text, (str, Path)) or not str(primary_text).strip():
            raise _StoredMapsError(
                "STORED_MAPS_PRODUCT_MISSING",
                f"No primary file for {row.map_type} ({row.profile_name})",
            )
        primary = Path(primary_text)
        if not primary.is_absolute():
            primary = maps_root / primary
        primary = primary.resolve()
        try:
            primary.relative_to(maps_root)
        except ValueError as exc:
            raise _StoredMapsError(
                "STORED_MAPS_OUTPUT_OUTSIDE_RESULTS",
                f"Stored-map product is outside {STORED_MAPS_OUTPUT_DIRECTORY}/: {primary}",
            ) from exc
        if not primary.is_file():
            raise _StoredMapsError(
                "STORED_MAPS_PRODUCT_MISSING",
                f"Stored-map primary file is missing: {primary.name}",
            )
        products.append(
            {
                "profile_index": int(row.profile_index),
                "profile_name": str(row.profile_name),
                "map_type": str(row.map_type),
                "primary_path": _relative(primary, output_root),
                "file_count": int(row.file_count),
            }
        )
    if not products:
        raise _StoredMapsError(
            "STORED_MAPS_NO_PRODUCTS", "StoreAllMaps returned no products"
        )
    return products


class _StoredMapsError(RuntimeError):
    """Stored-map failure with a stable receipt reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _run_stored_maps(
    request: RasExecutionRequest,
    runtime_root: Path,
    runtime_project: Path,
    output_root: Path,
    hdf_path: Path,
    result_hdf_digest: str,
) -> dict[str, Any]:
    """Generate requested steady-profile maps on the validated runtime copy.

    Never raises: every failure is returned as a ``failed`` section so the
    hydraulic receipt fields are preserved.
    """
    from ..RasProcess import RasProcess

    block = request.stored_maps
    started = time.monotonic()
    try:
        ras_object = RasPrj()
        ras_object.initialize(
            runtime_root,
            request.ras_executable,
            prj_file=runtime_project,
            load_results_summary=False,
        )
        frame = RasProcess.store_maps_at_steady_profiles(
            request.plan_number,
            profiles=None if block.profiles is None else list(block.profiles),
            output_path=output_root / STORED_MAPS_OUTPUT_DIRECTORY,
            map_types=list(block.map_types),
            ras_object=ras_object,
            timeout=block.timeout_seconds,
            terrain_name=block.terrain_name,
            inundation_boundary=block.inundation_boundary,
        )
        products = _stored_map_products(frame, output_root)
        # The receipt's result HDF digest is the hydraulically validated
        # bytes. Mapping must not have rewritten them.
        if sha256_file(hdf_path) != result_hdf_digest:
            raise _StoredMapsError(
                "STORED_MAPS_RESULT_HDF_CHANGED",
                "Stored-map generation changed the validated result HDF",
            )
    except _StoredMapsError as exc:
        reason, message = exc.reason_code, str(exc)
    except subprocess.TimeoutExpired as exc:
        reason, message = "STORED_MAPS_TIMEOUT", f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        logger.exception("Stored-map generation failed for %s", request.execution_id)
        reason, message = "STORED_MAPS_FAILED", f"{type(exc).__name__}: {exc}"
    else:
        return _stored_maps_section(
            request,
            "passed",
            "STORED_MAPS_COMPLETED",
            elapsed_seconds=time.monotonic() - started,
            products=products,
        )
    return _stored_maps_section(
        request,
        "failed",
        reason,
        elapsed_seconds=time.monotonic() - started,
        error=message,
    )


def _validate_initial_output(
    output_root: Path, request: RasExecutionRequest
) -> None:
    """Reject preexisting output except the active, isolated Wine task root."""
    if not output_root.exists():
        return
    entries = list(output_root.iterdir())
    if not entries:
        return
    if os.environ.get("RAS_COMMANDER_WINE_DELEGATED") != "1" or len(entries) != 1:
        raise ValueError(
            f"Output directory must be absent or empty for an immutable run: {output_root}"
        )
    prefix_value = os.environ.get("RAS_COMMANDER_WINE_PREFIX_WINDOWS", "")
    prefix = Path(prefix_value)
    output_resolved = output_root.resolve()
    expected_name_start = f".ras-wine-runtime-{request.execution_id}-"
    try:
        prefix_resolved = prefix.resolve(strict=True)
        task_root = prefix_resolved.parent
        entry_resolved = entries[0].resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Active Wine runtime path cannot be resolved") from exc
    valid = (
        prefix_value
        and prefix.is_absolute()
        and not prefix.is_symlink()
        and prefix_resolved.is_dir()
        and prefix_resolved.name == "prefix"
        and task_root.parent == output_resolved
        and re.fullmatch(
            rf"{re.escape(expected_name_start)}[A-Za-z0-9_-]{{6,}}",
            task_root.name,
        )
        is not None
        and entries[0].is_dir()
        and not entries[0].is_symlink()
        and entry_resolved == task_root
    )
    if not valid:
        raise ValueError(
            f"Output directory must be absent or empty for an immutable run: {output_root}"
        )
