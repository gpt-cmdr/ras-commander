"""Fail-closed inventory and removal of unsteady-flow boundary blocks.

This module deliberately operates only on an atomically staged project.  It
never resolves a source-library path, falls back to the package-global project,
or deserializes and reserializes an unsteady-flow file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

import pandas as pd

from .LoggingConfig import get_logger
from .schemas import DATAFRAME_SCHEMAS

if TYPE_CHECKING:
    from .RasProject import StageProjectResult


logger = get_logger(__name__)

_BOUNDARY_SCHEMA_VERSION = 1
_MUTATION_SCHEMA_VERSION = 1
_METADATA_DIRECTORY = ".ras-commander"
_STAGE_MANIFEST = "stage.json"
_MUTATION_LOCK = "boundary-mutation.lock"
_BOUNDARY_MARKER = b"Boundary Location="
_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_UNSTEADY_NUMBER_PATTERN = re.compile(r"[0-9]{2}\Z")

_BOUNDARY_TYPE_KEYWORDS = (
    ("Lateral Inflow Hydrograph=", "Lateral Inflow Hydrograph"),
    ("Uniform Lateral Inflow Hydrograph=", "Uniform Lateral Inflow Hydrograph"),
    ("Uniform Lateral Inflow=", "Uniform Lateral Inflow"),
    ("Observed Stage and Flow Hydrograph=", "Observed Stage and Flow"),
    ("Flow Hydrograph=", "Flow Hydrograph"),
    ("Stage Hydrograph=", "Stage Hydrograph"),
    ("Precipitation Hydrograph=", "Precipitation Hydrograph"),
    ("Rating Curve=", "Rating Curve"),
    ("Friction Slope=", "Normal Depth"),
    ("Gate Name=", "Gate Opening"),
    ("Gate Openings=", "Gate Opening"),
    ("Ground Water Interflow=", "Ground Water Interflow"),
    ("Navigation Dam=", "Navigation Dam"),
    ("Rule Operation=", "Rule Operation"),
)

# These anchors are project-level settings observed after the final boundary.
# The first anchor terminates the final block; every following byte is retained.
_GLOBAL_TRAILER_PREFIXES = (
    "Met Point Raster Parameters=",
    "Met Station Name=",
    "Met Station Gauge Height=",
    "Met Station LL=",
    "Met Station XY=",
    "Precipitation Mode=",
    "Wind Mode=",
    "Air Density Mode=",
    "Wave Mode=",
    "Met BC=",
    "Non-Newtonian",
    "User Yeild=",
    "User Yield=",
    "User Viscosity=",
    "User Viscosity Ratio=",
    "Herschel-Bulkley",
    "Clastic",
    "Coulomb",
    "Voellmy",
    "Lava",
    "Temperature=",
    "Heat Ballance=",
    "Viscosity=",
    "Yield Strength=",
    "Consistency Factor=",
    "Profile Coefficient=",
    "Lava Param=",
)

# A final block without a recognized global trailer may extend to EOF only when
# each key/value line is known to be boundary-owned.  Non-key table payload
# lines are retained as part of the block.
_BOUNDARY_FIELD_PREFIXES = tuple(keyword for keyword, _ in _BOUNDARY_TYPE_KEYWORDS) + (
    "Interval=",
    "DSS Path=",
    "DSS File=",
    "Use DSS=",
    "Use Fixed Start Time=",
    "Fixed Start Date/Time=",
    "Is Critical Boundary=",
    "Critical Boundary Flow=",
    "Flow Hydrograph QMult=",
    "Flow Hydrograph QMin=",
    "Flow Hydrograph Slope=",
    "Stage Hydrograph TW Check=",
    "Rating Curve TW Check=",
    "Ground Water Darcy K=",
    "Ground Water Darcy K/day=",
    "Ground Water Darcy Distance=",
    "Gate ",
    "Navigation Dam ",
    "Rule ",
)

_BOUNDARY_SCHEMA_COLUMNS = DATAFRAME_SCHEMAS["boundary_block_inventory"]["columns"]
_INVENTORY_DTYPES = {
    column["name"]: column["dtype"] for column in _BOUNDARY_SCHEMA_COLUMNS
}
BOUNDARY_BLOCK_COLUMNS = tuple(column["name"] for column in _BOUNDARY_SCHEMA_COLUMNS)


class BoundaryMutationError(RuntimeError):
    """Base exception for fail-closed boundary inventory and mutation."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        mutation_applied: Optional[bool] = False,
    ) -> None:
        self.reason_code = reason_code
        self.mutation_applied = mutation_applied
        super().__init__(f"{reason_code}: {message}")


class BoundaryStageOwnershipError(BoundaryMutationError):
    """The supplied stage or target cannot be proved to be owned and isolated."""


class BoundarySelectorError(BoundaryMutationError):
    """The exact boundary selector is invalid, missing, or ambiguous."""


class BoundaryStaleEvidenceError(BoundaryMutationError):
    """Snapshot evidence no longer matches the staged target."""


class BoundaryFormatError(BoundaryMutationError):
    """The unsteady-flow bytes cannot be parsed without guessing."""


class BoundaryPublicationError(BoundaryMutationError):
    """The verified byte splice could not be atomically published."""


class BoundaryPostPublicationError(BoundaryMutationError):
    """A failure occurred after the atomic replacement was applied."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(reason_code, message, mutation_applied=True)


@dataclass(frozen=True)
class BoundaryMutationResult:
    """Evidence for a previewed or applied exact boundary deletion."""

    mutation_schema_version: int
    mutation_id: str
    state: Literal["previewed", "applied"]
    staged_project_file: Path
    staged_root: Path
    unsteady_file: Path
    unsteady_number: str
    boundary_id: str
    bc_type: str
    boundary_location_raw: str
    boundary_index: int
    occurrence_ordinal: int
    start_byte: int
    end_byte_exclusive: int
    removed_block_sha256: str
    source_sha256: str
    result_sha256: str
    before_boundary_count: int
    after_boundary_count: int
    prefix_sha256: str
    suffix_sha256: str
    encoding: str
    newline: str
    manifest_verified: bool
    reparse_verified: bool
    target_identity_reverified: bool
    boundaries_df_refreshed: bool

    def __bool__(self) -> bool:
        """Prevent a rich evidence object from being mistaken for success."""
        raise TypeError("BoundaryMutationResult has no truth value; inspect .state")


@dataclass(frozen=True)
class _FileIdentity:
    size: int
    mtime_ns: int
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class _ByteLine:
    start: int
    content_end: int
    end: int
    content: bytes


@dataclass(frozen=True)
class _BoundaryBlock:
    boundary_index: int
    occurrence_ordinal: int
    start_byte: int
    end_byte_exclusive: int
    location_bytes: bytes
    location: str
    parts: tuple[str, ...]
    location_kind: str
    bc_type: str
    block_sha256: str
    boundary_id: str


@dataclass(frozen=True)
class _StageTarget:
    staged_project: StageProjectResult
    stage_operation_id: str
    stage_root: Path
    project_file: Path
    target: Path
    owner_relative_path: str
    manifest_sha256: str


@dataclass(frozen=True)
class _BoundarySnapshot:
    context: _StageTarget
    raw: bytes
    identity: _FileIdentity
    owner_sha256: str
    encoding: str
    has_bom: bool
    newline: str
    blocks: tuple[_BoundaryBlock, ...]


def _raise(error_type: type[BoundaryMutationError], code: str, message: str) -> None:
    raise error_type(code, message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    info = path.lstat()
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & marker)


def _file_identity(info: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        device=info.st_dev,
        inode=info.st_ino,
        mode=stat.S_IMODE(info.st_mode),
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError as exc:
        raise BoundaryStageOwnershipError(
            "path_identity_unavailable",
            "Filesystem identity could not be established for an ownership path",
        ) from exc


def _require_under_root(path: Path, root: Path) -> None:
    path_absolute = os.path.normcase(os.path.abspath(path))
    root_absolute = os.path.normcase(os.path.abspath(root))
    try:
        common = os.path.commonpath((path_absolute, root_absolute))
    except ValueError:
        common = ""
    if common != root_absolute or path_absolute == root_absolute:
        _raise(
            BoundaryStageOwnershipError,
            "target_outside_stage",
            "The unsteady-flow target is not a child of the staged root",
        )


def _require_nonreparse_chain(path: Path, root: Path, *, regular_file: bool) -> None:
    _require_under_root(path, root)
    current = path
    while True:
        try:
            if _is_reparse_point(current):
                _raise(
                    BoundaryStageOwnershipError,
                    "reparse_point",
                    f"Reparse points are not supported in a staged mutation: {current.name}",
                )
        except FileNotFoundError as exc:
            raise BoundaryStageOwnershipError(
                "stage_path_missing",
                f"Required staged path is missing: {current.name}",
            ) from exc
        if _same_path(current, root):
            break
        parent = current.parent
        if parent == current:
            _raise(
                BoundaryStageOwnershipError,
                "stage_root_not_reached",
                "Could not prove the target parent chain reaches the staged root",
            )
        current = parent
    if regular_file and not path.is_file():
        _raise(
            BoundaryStageOwnershipError,
            "target_not_regular_file",
            "The selected unsteady-flow target is not a regular file",
        )


def _normalize_unsteady_number(unsteady_number: str) -> str:
    if not isinstance(unsteady_number, str):
        _raise(
            BoundarySelectorError,
            "invalid_unsteady_number",
            "unsteady_number must be a two-character string such as '01'",
        )
    value = unsteady_number.strip()
    if not _UNSTEADY_NUMBER_PATTERN.fullmatch(value):
        _raise(
            BoundarySelectorError,
            "invalid_unsteady_number",
            "unsteady_number must contain exactly two ASCII digits",
        )
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        _raise(
            BoundarySelectorError,
            "invalid_expected_digest",
            f"{field_name} must be a lowercase hexadecimal SHA-256 digest",
        )
    return value


def _manifest_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        _raise(
            BoundaryStageOwnershipError,
            "invalid_stage_manifest",
            "The stage manifest has no artifacts list",
        )
    indexed: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("relative_path"), str):
            _raise(
                BoundaryStageOwnershipError,
                "invalid_stage_manifest",
                "The stage manifest contains a malformed artifact row",
            )
        relative = item["relative_path"].replace("\\", "/")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or relative in {"", "."}:
            _raise(
                BoundaryStageOwnershipError,
                "invalid_stage_manifest_path",
                "The stage manifest contains an unsafe artifact path",
            )
        folded_key = relative.casefold()
        if folded_key in folded:
            _raise(
                BoundaryStageOwnershipError,
                "ambiguous_stage_manifest_path",
                f"The stage manifest repeats an artifact path: {relative}",
            )
        folded.add(folded_key)
        indexed[relative] = item
    return indexed


def _stage_target(
    staged_project: StageProjectResult,
    unsteady_number: str,
) -> _StageTarget:
    # Local import avoids the RasProject -> RasUnsteady module cycle.
    from .RasProject import StageProjectResult

    if type(staged_project) is not StageProjectResult:
        _raise(
            BoundaryStageOwnershipError,
            "invalid_stage_result",
            "A concrete StageProjectResult returned by stage_project() is required",
        )
    if staged_project.publication_state != "published":
        _raise(
            BoundaryStageOwnershipError,
            "stage_not_published",
            "The supplied stage was not atomically published",
        )

    number = _normalize_unsteady_number(unsteady_number)
    root = Path(staged_project.destination_root)
    project_file = Path(staged_project.destination_project_file)
    if not root.is_dir() or _is_reparse_point(root):
        _raise(
            BoundaryStageOwnershipError,
            "invalid_stage_root",
            "The staged destination root is missing or is a reparse point",
        )
    _require_nonreparse_chain(project_file, root, regular_file=True)
    ras_project_file = getattr(staged_project.ras_object, "prj_file", None)
    if ras_project_file is None or not _same_path(Path(ras_project_file), project_file):
        _raise(
            BoundaryStageOwnershipError,
            "ras_project_mismatch",
            "The StageProjectResult RasPrj is not bound to its destination project",
        )

    manifest_path = root / _METADATA_DIRECTORY / _STAGE_MANIFEST
    _require_nonreparse_chain(manifest_path, root, regular_file=True)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BoundaryStageOwnershipError(
            "invalid_stage_manifest",
            "The stage manifest could not be read exactly",
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        _raise(
            BoundaryStageOwnershipError,
            "unsupported_stage_manifest",
            "Only stage manifest schema version 1 is supported",
        )
    manifest_project = manifest.get("destination_project_file")
    if not isinstance(manifest_project, str) or not _same_path(
        Path(manifest_project), project_file
    ):
        _raise(
            BoundaryStageOwnershipError,
            "manifest_project_mismatch",
            "The stage manifest names a different destination project",
        )
    operation_id = manifest.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        _raise(
            BoundaryStageOwnershipError,
            "invalid_stage_operation_id",
            "The stage manifest has no operation identity",
        )

    unsteady_df = getattr(staged_project.ras_object, "unsteady_df", None)
    if not isinstance(unsteady_df, pd.DataFrame):
        _raise(
            BoundaryStageOwnershipError,
            "unsteady_inventory_unavailable",
            "The staged RasPrj has no unsteady-flow inventory",
        )
    required_columns = {"unsteady_number", "full_path"}
    if not required_columns.issubset(unsteady_df.columns):
        _raise(
            BoundaryStageOwnershipError,
            "unsteady_inventory_invalid",
            "The staged unsteady-flow inventory is missing required columns",
        )
    matches = unsteady_df.loc[
        unsteady_df["unsteady_number"].astype(str).str.zfill(2) == number
    ]
    if len(matches) != 1:
        _raise(
            BoundarySelectorError,
            "unsteady_number_not_unique",
            f"unsteady_number {number!r} resolved to {len(matches)} staged files",
        )
    target = Path(matches.iloc[0]["full_path"])
    _require_nonreparse_chain(target, root, regular_file=True)
    if target.suffix.casefold() != f".u{number}".casefold():
        _raise(
            BoundaryStageOwnershipError,
            "unsteady_suffix_mismatch",
            "The staged inventory path does not match the requested unsteady number",
        )

    relative = target.relative_to(root).as_posix()
    artifacts = _manifest_artifacts(manifest)
    matching_artifacts = [
        item
        for artifact_relative, item in artifacts.items()
        if artifact_relative.casefold() == relative.casefold()
    ]
    if len(matching_artifacts) != 1:
        _raise(
            BoundaryStageOwnershipError,
            "target_not_in_stage_manifest",
            "The selected unsteady-flow file is not uniquely recorded in the stage manifest",
        )
    artifact = matching_artifacts[0]
    manifest_sha256 = artifact.get("sha256")
    if artifact.get("provenance") != "copied_source" or not isinstance(
        manifest_sha256, str
    ) or _SHA256_PATTERN.fullmatch(manifest_sha256) is None:
        _raise(
            BoundaryStageOwnershipError,
            "invalid_target_manifest_evidence",
            "The target has no copied-source SHA-256 evidence in the stage manifest",
        )

    published_fingerprint = staged_project.published_fingerprint
    if (
        not isinstance(published_fingerprint, str)
        or _SHA256_PATTERN.fullmatch(published_fingerprint) is None
    ):
        _raise(
            BoundaryStageOwnershipError,
            "invalid_published_fingerprint",
            "StageProjectResult has no valid published-tree fingerprint",
        )
    try:
        from .RasProject import _tree_snapshot

        _, observed_fingerprint, _ = _tree_snapshot(root)
    except Exception as exc:
        raise BoundaryStageOwnershipError(
            "stage_population_verification_failed",
            "The complete staged population could not be verified",
        ) from exc
    if observed_fingerprint != published_fingerprint:
        _raise(
            BoundaryStaleEvidenceError,
            "stage_population_changed",
            "The published stage population changed after stage_project() returned",
        )

    return _StageTarget(
        staged_project=staged_project,
        stage_operation_id=operation_id,
        stage_root=root,
        project_file=project_file,
        target=target,
        owner_relative_path=relative,
        manifest_sha256=manifest_sha256,
    )


def _read_stable(path: Path, root: Path) -> tuple[bytes, _FileIdentity]:
    _require_nonreparse_chain(path, root, regular_file=True)
    try:
        with path.open("rb") as stream:
            before = _file_identity(os.fstat(stream.fileno()))
            if before.inode == 0:
                _raise(
                    BoundaryStageOwnershipError,
                    "file_identity_unavailable",
                    "The filesystem did not expose a stable target file identity",
                )
            raw = stream.read()
            after = _file_identity(os.fstat(stream.fileno()))
    except BoundaryMutationError:
        raise
    except OSError as exc:
        raise BoundaryStageOwnershipError(
            "target_read_failed",
            "The staged unsteady-flow file could not be read exactly",
        ) from exc
    path_after = _file_identity(path.lstat())
    if before != after or after != path_after or len(raw) != after.size:
        _raise(
            BoundaryStaleEvidenceError,
            "target_changed_during_read",
            "The staged unsteady-flow file changed while it was read",
        )
    return raw, after


def _detect_encoding(raw: bytes) -> tuple[str, bool]:
    if raw.startswith(_UTF32_BOMS) or raw.startswith(_UTF16_BOMS):
        _raise(
            BoundaryFormatError,
            "unsupported_encoding",
            "UTF-16/UTF-32 unsteady-flow files are not supported for exact mutation",
        )
    if b"\x00" in raw:
        _raise(
            BoundaryFormatError,
            "nul_byte",
            "NUL bytes are not supported in an exact text boundary inventory",
        )
    if _UTF8_BOM in raw[3:]:
        _raise(
            BoundaryFormatError,
            "mid_file_bom",
            "A UTF-8 BOM is present after the beginning of the file",
        )
    if raw.startswith(_UTF8_BOM):
        try:
            raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise BoundaryFormatError(
                "undecodable_utf8_bom",
                "The UTF-8 BOM file contains invalid UTF-8 bytes",
            ) from exc
        return "utf-8-sig", True
    if raw.isascii():
        return "ascii", False
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8", False
    except UnicodeDecodeError:
        try:
            raw.decode("cp1252", errors="strict")
            return "cp1252", False
        except UnicodeDecodeError as exc:
            raise BoundaryFormatError(
                "unsupported_encoding",
                "The unsteady-flow bytes are neither strict UTF-8 nor Windows-1252",
            ) from exc


def _detect_newline(raw: bytes) -> tuple[bytes, str]:
    conventions = {match.group(0) for match in re.finditer(br"\r\n|\r|\n", raw)}
    if not conventions:
        _raise(
            BoundaryFormatError,
            "newline_unavailable",
            "The unsteady-flow file has no detectable line convention",
        )
    if len(conventions) != 1:
        _raise(
            BoundaryFormatError,
            "mixed_newlines",
            "Mixed newline conventions are not supported for exact mutation",
        )
    newline = conventions.pop()
    return newline, {b"\r\n": "CRLF", b"\n": "LF", b"\r": "CR"}[newline]


def _byte_lines(raw: bytes, newline: bytes) -> tuple[_ByteLine, ...]:
    lines: list[_ByteLine] = []
    start = 0
    while True:
        delimiter = raw.find(newline, start)
        if delimiter < 0:
            lines.append(_ByteLine(start, len(raw), len(raw), raw[start:]))
            break
        end = delimiter + len(newline)
        lines.append(_ByteLine(start, delimiter, end, raw[start:delimiter]))
        start = end
        if start == len(raw):
            break
    return tuple(lines)


def _line_without_initial_bom(line: _ByteLine, index: int) -> bytes:
    if index == 0 and line.content.startswith(_UTF8_BOM):
        return line.content[len(_UTF8_BOM) :]
    return line.content


def _decode(raw: bytes, encoding: str) -> str:
    codec = "utf-8" if encoding == "utf-8-sig" else encoding
    return raw.decode(codec, errors="strict")


def _hash_identity_fields(fields: tuple[bytes, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b"ras-commander-boundary-id-v1\0")
    for field in fields:
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    return digest.hexdigest()


def _validate_final_block_lines(
    lines: tuple[_ByteLine, ...],
    start_line: int,
    end_line: int,
    encoding: str,
) -> None:
    for line in lines[start_line + 1 : end_line]:
        text = _decode(line.content, encoding).lstrip()
        if not text or "=" not in text:
            continue
        if not text.startswith(_BOUNDARY_FIELD_PREFIXES):
            _raise(
                BoundaryFormatError,
                "unsupported_final_block_extent",
                f"Cannot prove final-boundary ownership of key {text.split('=', 1)[0]!r}",
            )


def _parse_boundary_bytes(
    raw: bytes,
    owner_relative_path: str,
    owner_sha256: str,
    owner_identity: _FileIdentity,
) -> tuple[str, bool, str, tuple[_BoundaryBlock, ...]]:
    encoding, has_bom = _detect_encoding(raw)
    newline_bytes, newline_name = _detect_newline(raw)
    lines = _byte_lines(raw, newline_bytes)
    starts: list[int] = []
    for index, line in enumerate(lines):
        content = _line_without_initial_bom(line, index)
        if content.startswith(_BOUNDARY_MARKER):
            starts.append(index)
        elif _BOUNDARY_MARKER.lower() in content.lower():
            _raise(
                BoundaryFormatError,
                "malformed_boundary_header",
                "Boundary Location headers must use exact case at byte-level line starts",
            )
    blocks: list[_BoundaryBlock] = []
    occurrences: dict[tuple[bytes, str], int] = {}

    for boundary_index, start_line in enumerate(starts):
        next_start_line = (
            starts[boundary_index + 1] if boundary_index + 1 < len(starts) else None
        )
        validate_final_extent = next_start_line is None
        if next_start_line is None:
            end_line = len(lines)
            for index in range(start_line + 1, len(lines)):
                text = _decode(lines[index].content, encoding)
                if text.startswith(_GLOBAL_TRAILER_PREFIXES):
                    end_line = index
                    break
        else:
            end_line = next_start_line

        initial_bom_length = (
            len(_UTF8_BOM)
            if start_line == 0 and lines[start_line].content.startswith(_UTF8_BOM)
            else 0
        )
        start_byte = lines[start_line].start + initial_bom_length
        end_byte = lines[end_line].start if end_line < len(lines) else len(raw)
        if end_byte <= start_byte:
            _raise(
                BoundaryFormatError,
                "invalid_block_extent",
                "A boundary block has a non-positive byte extent",
            )
        location_line = _line_without_initial_bom(lines[start_line], start_line)
        location_bytes = location_line[len(_BOUNDARY_MARKER) :]
        location = _decode(location_bytes, encoding)
        parts = tuple(part.strip() for part in location.split(","))
        if len(parts) < 3:
            _raise(
                BoundaryFormatError,
                "invalid_boundary_location",
                "Boundary Location must contain at least three comma-separated fields",
            )

        detected_types: set[str] = set()
        for line in lines[start_line + 1 : end_line]:
            text = _decode(line.content, encoding).lstrip()
            for keyword, bc_type in _BOUNDARY_TYPE_KEYWORDS:
                if text.startswith(keyword):
                    detected_types.add(bc_type)
        if len(detected_types) != 1:
            state = "none" if not detected_types else "multiple"
            _raise(
                BoundaryFormatError,
                "ambiguous_boundary_type",
                f"Boundary block {boundary_index} has {state} recognized boundary types",
            )
        bc_type = detected_types.pop()
        if validate_final_extent:
            _validate_final_block_lines(lines, start_line, end_line, encoding)

        area_2d = parts[5] if len(parts) > 5 else ""
        bc_line = parts[7] if len(parts) > 7 else ""
        if area_2d or bc_line:
            location_kind = "2d"
        elif any(parts[:3]):
            location_kind = "1d"
        else:
            _raise(
                BoundaryFormatError,
                "ambiguous_location_kind",
                f"Boundary block {boundary_index} has no provable 1D or 2D location",
            )

        block_raw = raw[start_byte:end_byte]
        block_sha256 = _sha256(block_raw)
        occurrence_key = (location_bytes, bc_type)
        occurrence_ordinal = occurrences.get(occurrence_key, 0)
        occurrences[occurrence_key] = occurrence_ordinal + 1
        boundary_id = _hash_identity_fields(
            (
                owner_relative_path.encode("utf-8"),
                owner_sha256.encode("ascii"),
                str(owner_identity.device).encode("ascii"),
                str(owner_identity.inode).encode("ascii"),
                str(owner_identity.mtime_ns).encode("ascii"),
                location_bytes,
                bc_type.encode("utf-8"),
                str(occurrence_ordinal).encode("ascii"),
                str(start_byte).encode("ascii"),
                str(end_byte).encode("ascii"),
                block_sha256.encode("ascii"),
            )
        )
        blocks.append(
            _BoundaryBlock(
                boundary_index=boundary_index,
                occurrence_ordinal=occurrence_ordinal,
                start_byte=start_byte,
                end_byte_exclusive=end_byte,
                location_bytes=location_bytes,
                location=location,
                parts=parts,
                location_kind=location_kind,
                bc_type=bc_type,
                block_sha256=block_sha256,
                boundary_id=boundary_id,
            )
        )

    ids = {block.boundary_id for block in blocks}
    if len(ids) != len(blocks):
        _raise(
            BoundaryFormatError,
            "boundary_identity_collision",
            "The exact boundary inventory contains a boundary ID collision",
        )
    return encoding, has_bom, newline_name, tuple(blocks)


def _snapshot(
    staged_project: StageProjectResult,
    unsteady_number: str,
) -> _BoundarySnapshot:
    context = _stage_target(staged_project, unsteady_number)
    raw, identity = _read_stable(context.target, context.stage_root)
    owner_sha256 = _sha256(raw)
    if owner_sha256 != context.manifest_sha256:
        _raise(
            BoundaryStaleEvidenceError,
            "stage_artifact_changed",
            "The staged target no longer matches its copied-source manifest digest",
        )
    encoding, has_bom, newline, blocks = _parse_boundary_bytes(
        raw,
        context.owner_relative_path,
        owner_sha256,
        identity,
    )
    return _BoundarySnapshot(
        context=context,
        raw=raw,
        identity=identity,
        owner_sha256=owner_sha256,
        encoding=encoding,
        has_bom=has_bom,
        newline=newline,
        blocks=blocks,
    )


def _inventory_frame(snapshot: _BoundarySnapshot) -> pd.DataFrame:
    inventory_id = str(uuid.uuid4())
    count = len(snapshot.blocks)
    rows: list[dict[str, Any]] = []
    for block in snapshot.blocks:
        parts = block.parts
        rows.append(
            {
                "inventory_schema_version": _BOUNDARY_SCHEMA_VERSION,
                "inventory_id": inventory_id,
                "stage_operation_id": snapshot.context.stage_operation_id,
                "staged_project_file": str(snapshot.context.project_file),
                "staged_root": str(snapshot.context.stage_root),
                "unsteady_number": snapshot.context.target.suffix[2:],
                "owner_relative_path": snapshot.context.owner_relative_path,
                "owner_sha256": snapshot.owner_sha256,
                "owner_size_bytes": snapshot.identity.size,
                "owner_mtime_ns": snapshot.identity.mtime_ns,
                "volume_id": str(snapshot.identity.device),
                "file_id": str(snapshot.identity.inode),
                "boundary_index": block.boundary_index,
                "boundary_condition_number": block.boundary_index + 1,
                "occurrence_ordinal": block.occurrence_ordinal,
                "boundary_count": count,
                "boundary_location_raw": block.location,
                "location_kind": block.location_kind,
                "river": parts[0] if len(parts) > 0 else "",
                "reach": parts[1] if len(parts) > 1 else "",
                "river_station": parts[2] if len(parts) > 2 else "",
                "area_2d": parts[5] if len(parts) > 5 else "",
                "bc_line": parts[7] if len(parts) > 7 else "",
                "bc_type": block.bc_type,
                "start_byte": block.start_byte,
                "end_byte_exclusive": block.end_byte_exclusive,
                "block_length_bytes": (
                    block.end_byte_exclusive - block.start_byte
                ),
                "block_sha256": block.block_sha256,
                "encoding": snapshot.encoding,
                "has_bom": snapshot.has_bom,
                "newline": snapshot.newline,
                "boundary_id": block.boundary_id,
                "inspection_state": "available",
                "reason_code": None,
                "detail": None,
            }
        )
    frame = pd.DataFrame(rows, columns=BOUNDARY_BLOCK_COLUMNS)
    for column, dtype in _INVENTORY_DTYPES.items():
        frame[column] = frame[column].astype(dtype)
    return frame.convert_dtypes(dtype_backend="pyarrow")


def inspect_boundary_blocks(
    staged_project: StageProjectResult,
    *,
    unsteady_number: str,
) -> pd.DataFrame:
    """Return exact, snapshot-bound boundary block evidence for a staged file."""
    return _inventory_frame(_snapshot(staged_project, unsteady_number))


def _select_block(
    snapshot: _BoundarySnapshot,
    *,
    boundary_id: str,
    expected_source_sha256: str,
    expected_block_sha256: str,
    expected_bc_type: str,
    expected_location_raw: str,
) -> _BoundaryBlock:
    boundary_id = _require_sha256(boundary_id, "boundary_id")
    source_sha256 = _require_sha256(
        expected_source_sha256, "expected_source_sha256"
    )
    block_sha256 = _require_sha256(
        expected_block_sha256, "expected_block_sha256"
    )
    if source_sha256 != snapshot.owner_sha256:
        _raise(
            BoundaryStaleEvidenceError,
            "source_digest_mismatch",
            "expected_source_sha256 does not match the staged target snapshot",
        )
    matches = [block for block in snapshot.blocks if block.boundary_id == boundary_id]
    if len(matches) != 1:
        _raise(
            BoundaryStaleEvidenceError,
            "boundary_id_not_current",
            f"boundary_id resolved to {len(matches)} blocks in the current snapshot",
        )
    block = matches[0]
    if block.block_sha256 != block_sha256:
        _raise(
            BoundaryStaleEvidenceError,
            "block_digest_mismatch",
            "expected_block_sha256 does not match the selected boundary block",
        )
    if not isinstance(expected_bc_type, str) or block.bc_type != expected_bc_type:
        _raise(
            BoundarySelectorError,
            "boundary_type_mismatch",
            "expected_bc_type does not exactly match the selected boundary type",
        )
    if (
        not isinstance(expected_location_raw, str)
        or block.location != expected_location_raw
    ):
        _raise(
            BoundarySelectorError,
            "boundary_location_mismatch",
            "expected_location_raw does not exactly match the selected location bytes",
        )
    return block


def _build_plan(
    snapshot: _BoundarySnapshot,
    block: _BoundaryBlock,
) -> tuple[bytes, tuple[_BoundaryBlock, ...]]:
    prefix = snapshot.raw[: block.start_byte]
    suffix = snapshot.raw[block.end_byte_exclusive :]
    predicted = prefix + suffix
    predicted_sha256 = _sha256(predicted)
    _, _, _, after_blocks = _parse_boundary_bytes(
        predicted,
        snapshot.context.owner_relative_path,
        predicted_sha256,
        snapshot.identity,
    )
    expected_digests = [
        candidate.block_sha256
        for candidate in snapshot.blocks
        if candidate.boundary_index != block.boundary_index
    ]
    observed_digests = [candidate.block_sha256 for candidate in after_blocks]
    if len(after_blocks) != len(snapshot.blocks) - 1:
        _raise(
            BoundaryFormatError,
            "post_reparse_count_mismatch",
            "The predicted splice does not contain exactly one fewer boundary block",
        )
    if observed_digests != expected_digests:
        _raise(
            BoundaryFormatError,
            "post_reparse_identity_mismatch",
            "The predicted splice changed an unselected boundary block",
        )
    if any(candidate.boundary_id == block.boundary_id for candidate in after_blocks):
        _raise(
            BoundaryFormatError,
            "selected_boundary_still_present",
            "The selected snapshot-bound identity survived the predicted splice",
        )
    return predicted, after_blocks


def _result(
    snapshot: _BoundarySnapshot,
    block: _BoundaryBlock,
    predicted: bytes,
    *,
    state: Literal["previewed", "applied"],
    boundaries_df_refreshed: bool,
) -> BoundaryMutationResult:
    return BoundaryMutationResult(
        mutation_schema_version=_MUTATION_SCHEMA_VERSION,
        mutation_id=str(uuid.uuid4()),
        state=state,
        staged_project_file=snapshot.context.project_file,
        staged_root=snapshot.context.stage_root,
        unsteady_file=snapshot.context.target,
        unsteady_number=snapshot.context.target.suffix[2:],
        boundary_id=block.boundary_id,
        bc_type=block.bc_type,
        boundary_location_raw=block.location,
        boundary_index=block.boundary_index,
        occurrence_ordinal=block.occurrence_ordinal,
        start_byte=block.start_byte,
        end_byte_exclusive=block.end_byte_exclusive,
        removed_block_sha256=block.block_sha256,
        source_sha256=snapshot.owner_sha256,
        result_sha256=_sha256(predicted),
        before_boundary_count=len(snapshot.blocks),
        after_boundary_count=len(snapshot.blocks) - 1,
        prefix_sha256=_sha256(snapshot.raw[: block.start_byte]),
        suffix_sha256=_sha256(snapshot.raw[block.end_byte_exclusive :]),
        encoding=snapshot.encoding,
        newline=snapshot.newline,
        manifest_verified=True,
        reparse_verified=True,
        target_identity_reverified=state == "applied",
        boundaries_df_refreshed=boundaries_df_refreshed,
    )


def _safe_unlink_owned(
    path: Path,
    identity: Optional[tuple[int, int]],
    *,
    expected_bytes: Optional[bytes] = None,
    expected_sha256: Optional[str] = None,
) -> None:
    if identity is None:
        return
    try:
        before = path.lstat()
    except FileNotFoundError:
        return
    content_matches = True
    try:
        if expected_bytes is not None:
            content_matches = path.read_bytes() == expected_bytes
        elif expected_sha256 is not None:
            content_matches = _sha256_file(path) == expected_sha256
        after = path.lstat()
    except OSError:
        content_matches = False
        after = before
    if (
        (before.st_dev, before.st_ino) != identity
        or (after.st_dev, after.st_ino) != identity
        or _is_reparse_point(path)
        or not content_matches
    ):
        logger.error("Refusing to clean up replaced boundary-operation file %s", path.name)
        return
    try:
        path.unlink()
    except OSError:
        logger.exception("Could not clean up owned boundary-operation file %s", path.name)


def _acquire_lock(stage_root: Path) -> tuple[Path, tuple[int, int], bytes]:
    parent = stage_root.parent
    if not parent.is_dir() or _is_reparse_point(parent):
        _raise(
            BoundaryStageOwnershipError,
            "stage_parent_unsupported",
            "The stage parent must be a non-reparse directory for mutation locking",
        )
    lock = parent / f".{stage_root.name}.{_MUTATION_LOCK}"
    token = f"pid={os.getpid()};operation={uuid.uuid4()}\n".encode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lock, flags, 0o600)
    except FileExistsError as exc:
        raise BoundaryPublicationError(
            "boundary_mutation_locked",
            "Another cooperative boundary mutation owns this staged project",
        ) from exc
    except OSError as exc:
        raise BoundaryPublicationError(
            "boundary_lock_failed",
            "Could not acquire the staged boundary-mutation lock",
        ) from exc
    info = os.fstat(descriptor)
    try:
        view = memoryview(token)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _raise(
                    BoundaryPublicationError,
                    "boundary_lock_write_failed",
                    "The boundary-mutation lock write made no progress",
                )
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        _safe_unlink_owned(lock, (info.st_dev, info.st_ino))
        raise
    os.close(descriptor)
    return lock, (info.st_dev, info.st_ino), token


def _require_owned_lock(
    lock: Path,
    identity: tuple[int, int],
    token: bytes,
) -> None:
    try:
        before = lock.lstat()
        observed = lock.read_bytes()
        after = lock.lstat()
    except OSError as exc:
        raise BoundaryPublicationError(
            "boundary_lock_changed",
            "The cooperative mutation lock became unreadable before replacement",
        ) from exc
    if (
        (before.st_dev, before.st_ino) != identity
        or (after.st_dev, after.st_ino) != identity
        or _is_reparse_point(lock)
        or observed != token
    ):
        _raise(
            BoundaryPublicationError,
            "boundary_lock_changed",
            "The cooperative mutation lock identity or token changed before replacement",
        )


def _require_atomic_filesystem(stage_root: Path) -> None:
    """Reject Windows remote/unknown volumes until replace semantics are proven."""
    if os.name != "nt":
        return
    import ctypes

    anchor = Path(os.path.abspath(stage_root)).anchor
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(anchor))
    # DRIVE_FIXED is the currently proven Windows lane. In particular, SMB/UNC
    # replacement errors can be ambiguous after commit and are preview-only.
    if drive_type != 3:
        _raise(
            BoundaryPublicationError,
            "atomic_replace_not_proven",
            "Apply is supported only on a fixed local Windows volume; preview remains available",
        )


def _write_temp(
    snapshot: _BoundarySnapshot,
    predicted: bytes,
) -> tuple[Path, tuple[int, int]]:
    temp = snapshot.context.target.with_name(
        f".{snapshot.context.target.name}.ras-boundary-{uuid.uuid4().hex}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(temp, flags, snapshot.identity.mode or 0o600)
    except OSError as exc:
        raise BoundaryPublicationError(
            "temporary_create_failed",
            "Could not exclusively create the boundary-mutation temporary file",
        ) from exc
    try:
        view = memoryview(predicted)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _raise(
                    BoundaryPublicationError,
                    "temporary_write_failed",
                    "The temporary boundary file write made no progress",
                )
            view = view[written:]
        os.fsync(descriptor)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, snapshot.identity.mode)
        info = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        try:
            current = temp.lstat()
            _safe_unlink_owned(temp, (current.st_dev, current.st_ino))
        except FileNotFoundError:
            pass
        raise
    os.close(descriptor)
    if not hasattr(os, "fchmod"):
        os.chmod(temp, snapshot.identity.mode)
    identity = (info.st_dev, info.st_ino)
    if info.st_size != len(predicted) or _sha256_file(temp) != _sha256(predicted):
        _safe_unlink_owned(temp, identity)
        _raise(
            BoundaryPublicationError,
            "temporary_verification_failed",
            "The temporary boundary file does not match the predicted bytes",
        )
    return temp, identity


def _atomic_replace(
    temp: Path,
    target: Path,
    *,
    stage_root: Path,
    expected_target_identity: _FileIdentity,
    expected_target_sha256: str,
    expected_result_sha256: str,
    expected_temp_identity: tuple[int, int],
) -> None:
    current_raw, current_identity = _read_stable(target, stage_root)
    if (
        current_identity != expected_target_identity
        or _sha256(current_raw) != expected_target_sha256
    ):
        _raise(
            BoundaryStaleEvidenceError,
            "target_changed_before_replace",
            "The staged target changed immediately before atomic replacement",
        )
    try:
        temp_info = temp.lstat()
    except FileNotFoundError as exc:
        raise BoundaryPublicationError(
            "temporary_file_missing",
            "The verified temporary boundary file disappeared before replacement",
        ) from exc
    if (
        (temp_info.st_dev, temp_info.st_ino) != expected_temp_identity
        or _is_reparse_point(temp)
    ):
        _raise(
            BoundaryPublicationError,
            "temporary_identity_changed",
            "The temporary boundary file identity changed before replacement",
        )
    try:
        os.replace(temp, target)
    except OSError as exc:
        try:
            observed_raw, observed_identity = _read_stable(target, stage_root)
            observed_sha256 = _sha256(observed_raw)
        except BoundaryMutationError:
            error = BoundaryPublicationError(
                "atomic_replace_state_indeterminate",
                "Atomic replacement reported an error and the target state is indeterminate",
                mutation_applied=None,
            )
            raise error from exc
        if observed_sha256 == expected_result_sha256:
            raise BoundaryPostPublicationError(
                "atomic_replace_error_after_commit",
                "Atomic replacement reported an error after the result bytes were committed",
            ) from exc
        if (
            observed_sha256 == expected_target_sha256
            and observed_identity == expected_target_identity
        ):
            raise BoundaryPublicationError(
                "atomic_replace_failed",
                "The staged target remained intact after atomic replacement failed",
            ) from exc
        error = BoundaryPublicationError(
            "atomic_replace_state_indeterminate",
            "Atomic replacement reported an error and the target has unexpected bytes",
            mutation_applied=None,
        )
        raise error from exc


def _refresh_boundaries_df(
    snapshot: _BoundarySnapshot,
    expected_count: int,
) -> None:
    ras_object = snapshot.context.staged_project.ras_object
    try:
        refreshed = ras_object.get_boundary_conditions()
    except Exception as exc:
        raise BoundaryPostPublicationError(
            "boundaries_df_refresh_failed",
            "The boundary deletion was applied but RasPrj refresh failed",
        ) from exc
    if not isinstance(refreshed, pd.DataFrame):
        _raise(
            BoundaryPostPublicationError,
            "boundaries_df_refresh_invalid",
            "The boundary deletion was applied but RasPrj returned no DataFrame",
        )
    if refreshed.empty or "unsteady_number" not in refreshed.columns:
        observed_count = 0
    else:
        observed_count = int(
            (
                refreshed["unsteady_number"].astype(str).str.zfill(2)
                == snapshot.context.target.suffix[2:]
            ).sum()
        )
    if observed_count != expected_count:
        _raise(
            BoundaryPostPublicationError,
            "boundaries_df_count_mismatch",
            "The deletion was applied but refreshed RasPrj boundary count disagrees",
        )
    ras_object.boundaries_df = refreshed


def delete_boundary(
    staged_project: StageProjectResult,
    *,
    unsteady_number: str,
    boundary_id: str,
    expected_source_sha256: str,
    expected_block_sha256: str,
    expected_bc_type: str,
    expected_location_raw: str,
    dry_run: bool = True,
) -> BoundaryMutationResult:
    """Preview or apply one exact boundary-block deletion on an owned stage."""
    if type(dry_run) is not bool:
        _raise(
            BoundarySelectorError,
            "invalid_dry_run",
            "dry_run must be a bool and defaults to True",
        )

    snapshot = _snapshot(staged_project, unsteady_number)
    block = _select_block(
        snapshot,
        boundary_id=boundary_id,
        expected_source_sha256=expected_source_sha256,
        expected_block_sha256=expected_block_sha256,
        expected_bc_type=expected_bc_type,
        expected_location_raw=expected_location_raw,
    )
    predicted, _ = _build_plan(snapshot, block)
    if dry_run:
        return _result(
            snapshot,
            block,
            predicted,
            state="previewed",
            boundaries_df_refreshed=False,
        )

    _require_atomic_filesystem(snapshot.context.stage_root)
    lock_path, lock_identity, lock_token = _acquire_lock(snapshot.context.stage_root)
    temp_path: Optional[Path] = None
    temp_identity: Optional[tuple[int, int]] = None
    try:
        # Inventory and selection are repeated under the cooperative lock.  This
        # makes evidence gathered before lock acquisition incapable of authorizing
        # a write after another compliant operation changed the stage.
        snapshot = _snapshot(staged_project, unsteady_number)
        block = _select_block(
            snapshot,
            boundary_id=boundary_id,
            expected_source_sha256=expected_source_sha256,
            expected_block_sha256=expected_block_sha256,
            expected_bc_type=expected_bc_type,
            expected_location_raw=expected_location_raw,
        )
        predicted, expected_after_blocks = _build_plan(snapshot, block)
        temp_path, temp_identity = _write_temp(snapshot, predicted)

        temp_raw, _ = _read_stable(temp_path, snapshot.context.stage_root)
        temp_encoding, temp_bom, temp_newline, temp_blocks = _parse_boundary_bytes(
            temp_raw,
            snapshot.context.owner_relative_path,
            _sha256(temp_raw),
            _file_identity(temp_path.lstat()),
        )
        if (
            temp_raw != predicted
            or temp_encoding != snapshot.encoding
            or temp_bom != snapshot.has_bom
            or temp_newline != snapshot.newline
            or [item.block_sha256 for item in temp_blocks]
            != [item.block_sha256 for item in expected_after_blocks]
        ):
            _raise(
                BoundaryPublicationError,
                "temporary_reparse_mismatch",
                "The temporary boundary file failed exact reparse verification",
            )

        _require_owned_lock(lock_path, lock_identity, lock_token)
        _atomic_replace(
            temp_path,
            snapshot.context.target,
            stage_root=snapshot.context.stage_root,
            expected_target_identity=snapshot.identity,
            expected_target_sha256=snapshot.owner_sha256,
            expected_result_sha256=_sha256(predicted),
            expected_temp_identity=temp_identity,
        )
        temp_path = None
        temp_identity = None

        try:
            post_raw, post_identity = _read_stable(
                snapshot.context.target, snapshot.context.stage_root
            )
            post_sha256 = _sha256(post_raw)
            _, _, _, post_blocks = _parse_boundary_bytes(
                post_raw,
                snapshot.context.owner_relative_path,
                post_sha256,
                post_identity,
            )
        except BoundaryMutationError as exc:
            raise BoundaryPostPublicationError(
                "post_publication_reparse_failed",
                "The deletion was applied but the published file could not be reparsed",
            ) from exc
        if (
            post_raw != predicted
            or [item.block_sha256 for item in post_blocks]
            != [item.block_sha256 for item in expected_after_blocks]
        ):
            _raise(
                BoundaryPostPublicationError,
                "post_publication_mismatch",
                "The deletion was applied but the published bytes differ from the proof",
            )
        _refresh_boundaries_df(snapshot, len(expected_after_blocks))
        return _result(
            snapshot,
            block,
            predicted,
            state="applied",
            boundaries_df_refreshed=True,
        )
    finally:
        if temp_path is not None:
            _safe_unlink_owned(
                temp_path,
                temp_identity,
                expected_sha256=_sha256(predicted),
            )
        _safe_unlink_owned(
            lock_path,
            lock_identity,
            expected_bytes=lock_token,
        )


__all__ = [
    "BOUNDARY_BLOCK_COLUMNS",
    "BoundaryFormatError",
    "BoundaryMutationError",
    "BoundaryMutationResult",
    "BoundaryPostPublicationError",
    "BoundaryPublicationError",
    "BoundarySelectorError",
    "BoundaryStageOwnershipError",
    "BoundaryStaleEvidenceError",
    "delete_boundary",
    "inspect_boundary_blocks",
]
