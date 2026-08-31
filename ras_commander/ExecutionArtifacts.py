"""Plan-scoped result-artifact selection and cleanup.

This module is intentionally independent of the execution front ends.  It is
the single source of truth for deciding between modern plan HDF results and
legacy ``.O##`` results, and for removing only the exact artifacts owned by a
selected plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from numbers import Number
from pathlib import Path
from typing import Literal, Optional, Union

from .LoggingConfig import get_logger
from .RasPrj import RasPrj, ras
from .RasUtils import RasUtils

logger = get_logger(__name__)

ResultFormat = Literal["hdf", "legacy"]
RemovalFormat = Literal["hdf", "legacy", "both"]


def normalize_program_version(value: object) -> Optional[str]:
    """Normalize a HEC-RAS version without reducing it to a float."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    dotted = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", text)
    if dotted is not None:
        major = int(dotted.group(1))
        minor_text = dotted.group(2)
        patch_text = dotted.group(3)
        if patch_text is not None:
            patch = int(patch_text)
            return (
                f"{major}.{int(minor_text)}"
                if patch == 0
                else f"{major}.{int(minor_text)}.{patch}"
            )
        # HEC-RAS plan files use compact dotted values such as 6.60, 5.06,
        # and 4.10 for 6.6, 5.0.6, and 4.1 respectively.
        if len(minor_text) == 2:
            if major == 5 and minor_text.startswith("0"):
                return f"5.0.{int(minor_text[1])}"
            if minor_text.endswith("0"):
                return f"{major}.{int(minor_text[0])}"
            return f"{major}.{int(minor_text[0])}.{int(minor_text[1])}"
        return f"{major}.{int(minor_text)}"

    compact = re.fullmatch(r"\s*(\d{2,3})\s*", text)
    if compact is None:
        return None
    digits = compact.group(1)
    if len(digits) == 3:
        return f"{int(digits[0])}.{int(digits[1])}.{int(digits[2])}"
    return f"{int(digits[0])}.{int(digits[1])}"


def program_version_major(value: object) -> Optional[int]:
    """Return the normalized major version, or ``None`` when unresolved."""
    normalized = normalize_program_version(value)
    if normalized is None:
        return None
    return int(normalized.split(".", 1)[0])


@dataclass(frozen=True)
class PlanResultArtifactPaths:
    """Exact result and message paths owned by one plan."""

    plan_number: str
    plan_file: Path
    hdf: Path
    legacy_output: Path
    message_sidecars: tuple[Path, ...]


@dataclass(frozen=True)
class ResultArtifactResolution:
    """Version-aware selection of one plan-result family."""

    paths: PlanResultArtifactPaths
    declared_program_version: Optional[str]
    expected_format: Optional[ResultFormat]
    selected_format: Optional[ResultFormat]
    selected_path: Optional[Path]
    selected_exists: bool
    conflicts: tuple[str, ...] = ()
    detail: Optional[str] = None


@dataclass(frozen=True)
class PlanExecutionCleanup:
    """Audit record returned after exact, permanent artifact removal."""

    plan_number: str
    result_format: RemovalFormat
    include_message_sidecars: bool
    removed_paths: tuple[Path, ...]
    missing_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation for execution audit records."""
        return {
            "plan_number": self.plan_number,
            "result_format": self.result_format,
            "include_message_sidecars": self.include_message_sidecars,
            "removed_paths": [str(path) for path in self.removed_paths],
            "missing_paths": [str(path) for path in self.missing_paths],
        }


class PlanExecutionCleanupError(RuntimeError):
    """Raised when exact cleanup fails after reporting any partial removal."""

    def __init__(
        self,
        *,
        cleanup: PlanExecutionCleanup,
        failed_path: Path,
        cause: BaseException,
    ) -> None:
        self.cleanup = cleanup
        self.failed_path = failed_path
        self.cause = cause
        super().__init__(
            f"Could not remove execution artifact {failed_path}: {cause}. "
            f"Already removed: {[str(path) for path in cleanup.removed_paths]}"
        )


class ResultArtifactAmbiguityError(RuntimeError):
    """Raised when coexisting result formats cannot be read safely."""

    def __init__(
        self,
        *,
        paths: PlanResultArtifactPaths,
        declared_program_version: Optional[str],
        expected_format: Optional[ResultFormat],
        reason_code: str,
        hdf_mtime_ns: Optional[int] = None,
        legacy_mtime_ns: Optional[int] = None,
        detail: Optional[str] = None,
    ) -> None:
        self.plan_number = paths.plan_number
        self.plan_file = paths.plan_file
        self.declared_program_version = declared_program_version
        self.expected_format = expected_format
        self.hdf_path = paths.hdf
        self.legacy_output_path = paths.legacy_output
        self.hdf_mtime_ns = hdf_mtime_ns
        self.legacy_mtime_ns = legacy_mtime_ns
        self.reason_code = reason_code
        self.detail = detail
        message = (
            f"Plan {paths.plan_number} has ambiguous result artifacts "
            f"({paths.hdf.name} and {paths.legacy_output.name}); "
            f"reason={reason_code}, declared_program_version="
            f"{declared_program_version or 'unresolved'}. Remove one format with "
            "RasCmdr.remove_plan_execution_artifacts(..., "
            "result_format='hdf' or 'legacy'), or rerun the plan with the "
            "selected HEC-RAS version through ras-commander."
        )
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)


def _read_declared_program_version(plan_file: Path) -> Optional[str]:
    """Read ``Program Version=`` from the plan bytes at inspection time."""
    raw = plan_file.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "Program Version":
            return value.strip() or None
    return None


def get_plan_result_artifact_paths(
    plan_number: Union[str, Number, Path],
    *,
    ras_object: Optional[RasPrj] = None,
    project_folder: Optional[Union[str, Path]] = None,
    project_name: Optional[str] = None,
) -> PlanResultArtifactPaths:
    """Resolve the exact artifact allowlist for one plan.

    Explicit ``project_folder`` and ``project_name`` identify the project
    without requiring the process-global project object to be initialized.
    Both values are required together so cleanup cannot combine metadata from
    different project contexts.
    """
    explicit_project = project_folder is not None or project_name is not None
    if explicit_project:
        if project_folder is None or project_name is None:
            raise ValueError(
                "project_folder and project_name must be provided together"
            )
        ras_obj = None
    else:
        ras_obj = ras_object if ras_object is not None else ras
        if hasattr(ras_obj, "check_initialized"):
            ras_obj.check_initialized()
        elif not hasattr(ras_obj, "project_folder") or not hasattr(
            ras_obj, "project_name"
        ):
            raise ValueError("ras_object must identify an initialized project")
    normalized = RasUtils.normalize_ras_number(plan_number)
    folder = Path(
        project_folder if explicit_project else ras_obj.project_folder
    ).resolve()
    name = str(project_name if explicit_project else ras_obj.project_name)
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(
            "project_name must be a plain filename stem without path separators"
        )
    plan_file = folder / f"{name}.p{normalized}"
    resolved = PlanResultArtifactPaths(
        plan_number=normalized,
        plan_file=plan_file,
        hdf=Path(f"{plan_file}.hdf"),
        legacy_output=folder / f"{name}.O{normalized}",
        message_sidecars=(
            Path(f"{plan_file}.comp_msgs.txt"),
            Path(f"{plan_file}.computeMsgs.txt"),
            folder / f"{name}.bco{normalized}",
        ),
    )
    for candidate in (
        resolved.plan_file,
        resolved.hdf,
        resolved.legacy_output,
        *resolved.message_sidecars,
    ):
        if candidate.resolve().parent != folder:
            raise ValueError(
                f"Execution artifact escapes the project folder: {candidate}"
            )
    return resolved


def resolve_plan_result_artifact(
    plan_number: Union[str, Number, Path],
    *,
    ras_object: Optional[RasPrj] = None,
) -> ResultArtifactResolution:
    """Select a result artifact using the current plan-file declaration.

    File timestamps are consulted only when both result families exist. They
    are a conservative error trigger, not proof of run chronology. Actual
    execution cleanup is governed separately by the selected engine version.
    """
    paths = get_plan_result_artifact_paths(plan_number, ras_object=ras_object)
    if not paths.plan_file.is_file():
        raise FileNotFoundError(f"Plan file not found: {paths.plan_file}")
    declared = _read_declared_program_version(paths.plan_file)
    declared_major = program_version_major(declared)
    expected: Optional[ResultFormat]
    if declared_major is None:
        expected = None
    else:
        expected = "legacy" if declared_major < 5 else "hdf"

    has_hdf = paths.hdf.is_file()
    has_legacy = paths.legacy_output.is_file()
    conflicts: list[str] = []
    detail: Optional[str] = None

    if has_hdf and has_legacy:
        try:
            hdf_mtime_ns = paths.hdf.stat().st_mtime_ns
            legacy_mtime_ns = paths.legacy_output.stat().st_mtime_ns
        except OSError as exc:
            raise ResultArtifactAmbiguityError(
                paths=paths,
                declared_program_version=declared,
                expected_format=expected,
                reason_code="result_artifact_timestamp_unavailable",
                detail=str(exc),
            ) from exc

        if expected == "hdf":
            if legacy_mtime_ns > hdf_mtime_ns:
                raise ResultArtifactAmbiguityError(
                    paths=paths,
                    declared_program_version=declared,
                    expected_format=expected,
                    reason_code="legacy_output_timestamp_after_hdf",
                    hdf_mtime_ns=hdf_mtime_ns,
                    legacy_mtime_ns=legacy_mtime_ns,
                    detail=(
                        "The timestamp comparison is conservative because "
                        "copied folders can preserve or rewrite filesystem "
                        "times. Re-run with the selected HEC-RAS version or "
                        "remove one result family explicitly."
                    ),
                )
            conflicts.append("multiple_result_formats_present")
            detail = (
                f"Selected {paths.hdf.name} because the plan declares "
                f"HEC-RAS {declared} and its filesystem modification time "
                f"is equal to or later than {paths.legacy_output.name}; "
                "ignored the coexisting legacy result."
            )
            logger.warning("%s", detail)
            return ResultArtifactResolution(
                paths=paths,
                declared_program_version=declared,
                expected_format=expected,
                selected_format="hdf",
                selected_path=paths.hdf,
                selected_exists=True,
                conflicts=tuple(conflicts),
                detail=detail,
            )
        if expected is None:
            raise ResultArtifactAmbiguityError(
                paths=paths,
                declared_program_version=declared,
                expected_format=expected,
                reason_code="program_version_unresolved_multiple_formats",
                hdf_mtime_ns=hdf_mtime_ns,
                legacy_mtime_ns=legacy_mtime_ns,
            )
        if hdf_mtime_ns > legacy_mtime_ns:
            raise ResultArtifactAmbiguityError(
                paths=paths,
                declared_program_version=declared,
                expected_format=expected,
                reason_code="hdf_timestamp_after_legacy_output",
                hdf_mtime_ns=hdf_mtime_ns,
                legacy_mtime_ns=legacy_mtime_ns,
                detail=(
                    "The timestamp comparison is conservative because copied "
                    "folders can preserve or rewrite filesystem times."
                ),
            )
        conflicts.append("multiple_result_formats_present")
        detail = (
            f"Selected {paths.legacy_output.name} because the plan declares "
            f"HEC-RAS {declared} and its filesystem modification time is "
            f"equal to or later than {paths.hdf.name}; ignored the "
            "coexisting HDF result."
        )
        logger.warning("%s", detail)
        return ResultArtifactResolution(
            paths=paths,
            declared_program_version=declared,
            expected_format=expected,
            selected_format="legacy",
            selected_path=paths.legacy_output,
            selected_exists=True,
            conflicts=tuple(conflicts),
            detail=detail,
        )

    if has_hdf:
        selected_format: Optional[ResultFormat] = "hdf"
        selected_path = paths.hdf
    elif has_legacy:
        selected_format = "legacy"
        selected_path = paths.legacy_output
    elif expected == "legacy":
        selected_format = "legacy"
        selected_path = paths.legacy_output
    elif expected == "hdf":
        selected_format = "hdf"
        selected_path = paths.hdf
    else:
        selected_format = None
        selected_path = None

    if (has_hdf or has_legacy) and expected is not None and selected_format != expected:
        conflicts.append("unexpected_result_format")
        detail = (
            f"Selected sole existing {selected_format} result even though the "
            f"plan declares HEC-RAS {declared} ({expected} expected)."
        )
        logger.warning("%s", detail)
    elif expected is None:
        conflicts.append("program_version_unresolved")
        detail = (
            "Plan Program Version could not be resolved; selected the sole "
            "existing result format." if has_hdf or has_legacy else
            "Plan Program Version could not be resolved; no result exists."
        )
        logger.warning("%s", detail)

    return ResultArtifactResolution(
        paths=paths,
        declared_program_version=declared,
        expected_format=expected,
        selected_format=selected_format,
        selected_path=selected_path,
        selected_exists=(selected_path.is_file() if selected_path else False),
        conflicts=tuple(conflicts),
        detail=detail,
    )


def remove_plan_execution_artifacts(
    plan_number: Union[str, Number, Path],
    *,
    result_format: RemovalFormat,
    include_message_sidecars: bool = False,
    ras_object: Optional[RasPrj] = None,
    project_folder: Optional[Union[str, Path]] = None,
    project_name: Optional[str] = None,
) -> PlanExecutionCleanup:
    """Permanently remove exact, plan-owned result artifacts.

    ``result_format`` is required so callers must explicitly choose whether to
    remove modern HDF results, legacy ``.O##`` results, or both.  Geometry HDF,
    DSS, terrain, and temporary Linux preprocessing files are never included.
    """
    if result_format not in {"hdf", "legacy", "both"}:
        raise ValueError("result_format must be 'hdf', 'legacy', or 'both'")
    if not isinstance(include_message_sidecars, bool):
        raise TypeError("include_message_sidecars must be True or False")
    paths = get_plan_result_artifact_paths(
        plan_number,
        ras_object=ras_object,
        project_folder=project_folder,
        project_name=project_name,
    )
    candidates: list[Path] = []
    if result_format in {"hdf", "both"}:
        candidates.append(paths.hdf)
    if result_format in {"legacy", "both"}:
        candidates.append(paths.legacy_output)
    if include_message_sidecars:
        candidates.extend(paths.message_sidecars)

    # Validate the complete allowlist before the first permanent mutation.
    # This prevents a later directory/path validation failure from leaving an
    # unreported partially-cleaned project.
    project_root = paths.plan_file.parent.resolve()
    for candidate in candidates:
        if candidate.resolve().parent != project_root:
            raise ValueError(
                f"Refusing to remove an artifact outside {project_root}: "
                f"{candidate}"
            )
        if candidate.exists() and not candidate.is_file():
            raise IsADirectoryError(
                f"Refusing to remove non-file execution artifact: {candidate}"
            )

    removed: list[Path] = []
    missing: list[Path] = []
    for candidate in candidates:
        if not candidate.exists():
            missing.append(candidate)
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            cleanup = PlanExecutionCleanup(
                plan_number=paths.plan_number,
                result_format=result_format,
                include_message_sidecars=include_message_sidecars,
                removed_paths=tuple(removed),
                missing_paths=tuple(missing),
            )
            raise PlanExecutionCleanupError(
                cleanup=cleanup,
                failed_path=candidate,
                cause=exc,
            ) from exc
        removed.append(candidate)
        logger.info("Removed plan %s execution artifact: %s", paths.plan_number, candidate.name)

    return PlanExecutionCleanup(
        plan_number=paths.plan_number,
        result_format=result_format,
        include_message_sidecars=include_message_sidecars,
        removed_paths=tuple(removed),
        missing_paths=tuple(missing),
    )


def infer_execution_result_format(ras_object: RasPrj) -> ResultFormat:
    """Resolve the output family from the actual configured execution engine.

    This function is deliberately fail-closed because its result authorizes
    permanent deletion of the opposing result family before computation.
    """
    configured_version = getattr(ras_object, "ras_version", None)
    configured_major = program_version_major(configured_version)
    executable = getattr(ras_object, "ras_exe_path", None)
    executable_major = None
    if executable:
        path = Path(str(executable))
        for part in reversed(path.parts[:-1]):
            executable_major = program_version_major(part)
            if executable_major is not None:
                break

    configured_format = (
        None
        if configured_major is None
        else ("legacy" if configured_major < 5 else "hdf")
    )
    executable_format = (
        None
        if executable_major is None
        else ("legacy" if executable_major < 5 else "hdf")
    )

    if (
        configured_format is not None
        and executable_format is not None
        and configured_format != executable_format
    ):
        raise ValueError(
            "Configured HEC-RAS metadata disagrees with the selected "
            f"executable: ras_version={configured_version!r} implies "
            f"{configured_format} results, while ras_exe_path={str(executable)!r} "
            f"implies {executable_format} results. Cleanup was not attempted; "
            "reinitialize the project with the executable that will actually run."
        )

    # A versioned executable is the closest available description of the
    # process that will actually be launched. Metadata is only a fallback for
    # unversioned executable names such as ``Ras.exe``.
    if executable_format is not None:
        return executable_format
    if configured_format is not None:
        return configured_format
    raise ValueError(
        "Could not determine the HEC-RAS output format from ras_version or "
        "a versioned ras_exe_path. Cleanup was not attempted; initialize the "
        "project with an explicit HEC-RAS version."
    )


def prepare_plan_execution_artifacts(
    plan_number: Union[str, Number, Path],
    *,
    output_format: ResultFormat,
    ras_object: RasPrj,
    project_folder: Optional[Union[str, Path]] = None,
    project_name: Optional[str] = None,
) -> PlanExecutionCleanup:
    """Remove the opposing result family and stale message sidecars."""
    opposing: RemovalFormat = "legacy" if output_format == "hdf" else "hdf"
    return remove_plan_execution_artifacts(
        plan_number,
        result_format=opposing,
        include_message_sidecars=True,
        ras_object=ras_object,
        project_folder=project_folder,
        project_name=project_name,
    )


def finalize_plan_execution_artifacts(
    plan_number: Union[str, Number, Path],
    *,
    output_format: ResultFormat,
    ras_object: RasPrj,
    project_folder: Optional[Union[str, Path]] = None,
    project_name: Optional[str] = None,
) -> PlanExecutionCleanup:
    """Remove an opposing result artifact recreated during execution.

    Message sidecars are retained because they belong to the just-finished run.
    """
    opposing: RemovalFormat = "legacy" if output_format == "hdf" else "hdf"
    return remove_plan_execution_artifacts(
        plan_number,
        result_format=opposing,
        include_message_sidecars=False,
        ras_object=ras_object,
        project_folder=project_folder,
        project_name=project_name,
    )


__all__ = [
    "PlanExecutionCleanup",
    "PlanExecutionCleanupError",
    "PlanResultArtifactPaths",
    "RemovalFormat",
    "ResultArtifactAmbiguityError",
    "ResultArtifactResolution",
    "ResultFormat",
    "finalize_plan_execution_artifacts",
    "get_plan_result_artifact_paths",
    "infer_execution_result_format",
    "normalize_program_version",
    "prepare_plan_execution_artifacts",
    "program_version_major",
    "remove_plan_execution_artifacts",
    "resolve_plan_result_artifact",
]
