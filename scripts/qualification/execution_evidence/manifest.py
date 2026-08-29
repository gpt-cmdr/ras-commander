"""Strict, deterministic manifest validation and normalization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .snapshots import (
    SnapshotError,
    assert_plain_ancestry,
    resolve_plain_path,
    stable_sha256,
)


class ManifestError(ValueError):
    """The qualification manifest is unsafe, ambiguous, or inconsistent."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_COMMAND_KEYS = {
    "argv",
    "command",
    "hec_ras_command",
    "ras_command",
    "raw_command",
}
_SOURCE_KINDS = {"project_file", "ras_examples", "fixture_database"}
_EXECUTION_APIS = {"ras_cmdr", "ras_control"}
_RESULT_FORMATS = {"hdf", "legacy"}
_SUPPORT_STATES = {"supported", "expected_prelaunch_failure", "blocked"}
_DATA_ORIGINS = {
    "captured_real",
    "staged_execution_output",
    "archived_failed_execution",
    "generated_edge_case",
}
_INITIAL_STATES = {
    "neither",
    "expected_only",
    "opposing_only",
    "both_expected_newer",
    "both_opposing_newer",
    "both_equal_mtime",
    "copied_preserved_times",
    "copied_rewritten_times",
}
_TERMINAL_CATEGORIES = {
    "passed",
    "expected_failure",
    "failed_invariant",
    "execution_failed",
    "timed_out",
    "worker_crashed",
    "blocked",
    "harness_error",
}
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "run_name",
    "repository",
    "archive_root",
    "execution_root",
    "defaults",
    "fixtures",
    "engines",
    "lanes",
}
_REPOSITORY_FIELDS = {
    "root",
    "required_head",
    "require_clean",
    "bind_running_code",
}
_DEFAULT_FIELDS = {
    "timeout_seconds",
    "termination_grace_seconds",
    "hash_files",
    "real_engine_jobs",
}
_FIXTURE_COMMON_FIELDS = {
    "fixture_id",
    "source_kind",
    "source_immutable",
    "source_content_fingerprint",
    "data_origin",
    "plan_number",
    "plan_title",
    "plan_type",
}
_FIXTURE_KIND_FIELDS = {
    "project_file": {"source_project", "replay_artifacts"},
    "ras_examples": {"example_project", "archive_sha256"},
    "fixture_database": {"fixture_database", "project_id"},
}
_REPLAY_FIELDS = {"source_root", "data_origin", "files"}
_REPLAY_FILE_FIELDS = {"relative_path", "sha256", "size_bytes", "mtime_ns"}
_REPLAY_DATA_ORIGINS = {
    "staged_execution_output",
    "archived_failed_execution",
    "generated_edge_case",
}
_ENGINE_COMMON_FIELDS = {
    "engine_id",
    "execution_api",
    "version_requested",
    "expected_result_format",
    "support_state",
}
_ENGINE_API_FIELDS = {
    "ras_cmdr": {"executable", "executable_sha256"},
    "ras_control": {
        "controller_version",
        "resolved_controller_version",
        "controller_progid",
        "blocking",
    },
}
_LANE_FIELDS = {
    "lane_id",
    "fixture_id",
    "engine_id",
    "initial_state",
    "expected_terminal_category",
    "tags",
    "required_invariants",
    "expected_failure_reason_code",
}
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def canonical_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes used by manifest and receipt hashes."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Could not read manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError("manifest root must be a JSON object")
    return payload


def _reject_command_fields(value: Any, location: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            if normalized in _FORBIDDEN_COMMAND_KEYS:
                raise ManifestError(
                    f"{location}.{key} is forbidden; the harness accepts API identity, not raw HEC-RAS commands"
                )
            _reject_command_fields(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_command_fields(item, f"{location}[{index}]")


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ManifestError(
            f"{label} contains unknown fields: {sorted(str(item) for item in unknown)}"
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{label} must be an object")
    return dict(value)


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be an array")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be nonempty text")
    return value.strip()


def _require_identifier(value: Any, label: str) -> str:
    identifier = _require_text(value, label)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier) or identifier in {
        ".",
        "..",
    }:
        raise ManifestError(
            f"{label} must be a path-safe identifier containing letters, digits, dot, dash, or underscore"
        )
    if identifier.endswith(".") or identifier.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise ManifestError(f"{label} is not a Windows-safe path identifier")
    return identifier


def _absolute_path(
    value: Any,
    label: str,
    *,
    must_exist: bool = False,
    kind: str | None = None,
) -> str:
    raw = _require_text(value, label)
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        raise ManifestError(f"{label} must resolve to an absolute path: {raw}")
    if ".." in path.parts:
        raise ManifestError(f"{label} must not contain parent traversal: {raw}")
    try:
        if must_exist:
            path = resolve_plain_path(path, kind=kind)
        else:
            path = assert_plain_ancestry(path)
            if path.exists():
                if kind == "directory" and not path.is_dir():
                    raise SnapshotError(f"required path is not a directory: {path}")
                if kind == "file" and not path.is_file():
                    raise SnapshotError(f"required path is not a regular file: {path}")
    except SnapshotError as exc:
        raise ManifestError(f"{label} is not a plain {kind or 'path'}: {path}") from exc
    return str(path)


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _file_sha256(path: Path) -> str:
    try:
        digest, _ = stable_sha256(path)
    except SnapshotError as exc:
        raise ManifestError(f"file is not stable and plain: {path}") from exc
    return digest


def _normalize_replay_artifacts(
    raw: Any,
    *,
    fixture_id: str,
    project_stem: str,
    plan_number: str,
) -> dict[str, Any]:
    replay = _require_mapping(raw, f"fixture {fixture_id}.replay_artifacts")
    _reject_unknown_fields(
        replay,
        _REPLAY_FIELDS,
        f"fixture {fixture_id}.replay_artifacts",
    )
    raw_root = _require_text(
        replay.get("source_root"),
        f"fixture {fixture_id}.replay_artifacts.source_root",
    )
    expanded_root = Path(os.path.expandvars(raw_root)).expanduser()
    if not expanded_root.is_absolute():
        raise ManifestError(
            f"fixture {fixture_id}.replay_artifacts.source_root must be absolute"
        )
    try:
        source_root = resolve_plain_path(expanded_root, kind="directory")
    except SnapshotError as exc:
        raise ManifestError(
            f"fixture {fixture_id}.replay_artifacts.source_root is not a plain directory"
        ) from exc
    data_origin = _require_text(
        replay.get("data_origin"),
        f"fixture {fixture_id}.replay_artifacts.data_origin",
    )
    if data_origin not in _REPLAY_DATA_ORIGINS:
        raise ManifestError(
            f"fixture {fixture_id}.replay_artifacts.data_origin must be one of "
            f"{sorted(_REPLAY_DATA_ORIGINS)}"
        )
    raw_files = _require_list(
        replay.get("files"),
        f"fixture {fixture_id}.replay_artifacts.files",
    )
    if not raw_files:
        raise ManifestError(
            f"fixture {fixture_id}.replay_artifacts.files must be nonempty"
        )
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    allowed_paths = {
        f"{project_stem}.p{plan_number}.hdf".casefold(),
        f"{project_stem}.O{plan_number}".casefold(),
        f"{project_stem}.p{plan_number}.comp_msgs.txt".casefold(),
        f"{project_stem}.p{plan_number}.computeMsgs.txt".casefold(),
        f"{project_stem}.bco{plan_number}".casefold(),
    }
    for index, raw_item in enumerate(raw_files):
        label = f"fixture {fixture_id}.replay_artifacts.files[{index}]"
        item = _require_mapping(raw_item, label)
        _reject_unknown_fields(item, _REPLAY_FILE_FIELDS, label)
        relative = _require_text(item.get("relative_path"), f"{label}.relative_path")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or relative_path.drive
            or relative_path.root
            or "\\" in relative
            or ".." in relative_path.parts
            or relative_path in {Path("."), Path("")}
        ):
            raise ManifestError(f"{label}.relative_path must be an exact relative path")
        normalized_relative = relative_path.as_posix()
        path_key = normalized_relative.casefold()
        if path_key not in allowed_paths:
            raise ManifestError(
                f"{label}.relative_path is outside the selected plan replay allowlist"
            )
        if path_key in seen_paths:
            raise ManifestError(
                f"fixture {fixture_id}.replay_artifacts.files contains a "
                f"case-insensitive duplicate path: {normalized_relative}"
            )
        seen_paths.add(path_key)
        try:
            artifact_path = assert_plain_ancestry(
                source_root / relative_path,
                stop=source_root,
            )
        except SnapshotError as exc:
            raise ManifestError(
                f"{label}.relative_path is linked or escapes source_root"
            ) from exc
        if not artifact_path.is_file():
            raise ManifestError(f"{label}.relative_path is not a regular file")
        expected_hash = _require_text(item.get("sha256"), f"{label}.sha256")
        if not _SHA256_RE.fullmatch(expected_hash):
            raise ManifestError(f"{label}.sha256 must be lowercase SHA-256")
        expected_size = item.get("size_bytes")
        expected_mtime = item.get("mtime_ns")
        for value, field in (
            (expected_size, "size_bytes"),
            (expected_mtime, "mtime_ns"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ManifestError(f"{label}.{field} must be a nonnegative integer")
        try:
            observed_hash, info = stable_sha256(artifact_path)
        except SnapshotError as exc:
            raise ManifestError(f"{label} changed or is linked while hashing") from exc
        mismatches = []
        if observed_hash != expected_hash:
            mismatches.append("sha256")
        if info.st_size != expected_size:
            mismatches.append("size_bytes")
        if info.st_mtime_ns != expected_mtime:
            mismatches.append("mtime_ns")
        if mismatches:
            raise ManifestError(
                f"{label} replay artifact metadata mismatch: {mismatches}"
            )
        normalized_files.append(
            {
                "relative_path": normalized_relative,
                "sha256": observed_hash,
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
        )
    return {
        "source_root": str(source_root),
        "data_origin": data_origin,
        "files": sorted(
            normalized_files,
            key=lambda item: item["relative_path"].casefold(),
        ),
    }


def _git_read(repository_root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    command = [
        "git",
        "-c",
        f"safe.directory={repository_root}",
        "-C",
        str(repository_root),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManifestError(f"could not inspect repository {repository_root}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git returned no detail"
        raise ManifestError(f"could not inspect repository {repository_root}: {detail}")
    return result.stdout.strip()


def _preflight_repository(
    repository_root: Path,
    *,
    required_head: str,
    require_clean: bool,
) -> dict[str, Any]:
    """Prove the pinned commit and requested cleanliness without modifying git state."""
    observed_top = _git_read(repository_root, "rev-parse", "--show-toplevel")
    try:
        top_level_matches = os.path.samefile(
            Path(observed_top).resolve(strict=True),
            repository_root.resolve(strict=True),
        )
    except OSError as exc:
        raise ManifestError(
            f"could not prove repository top-level identity: {exc}"
        ) from exc
    if not top_level_matches:
        raise ManifestError(
            "repository.root must be the exact git top-level; "
            f"observed {observed_top}"
        )
    actual_head = _git_read(repository_root, "rev-parse", "--verify", "HEAD").casefold()
    if not _GIT_RE.fullmatch(actual_head):
        raise ManifestError(f"repository HEAD is not a full commit identity: {actual_head!r}")
    if actual_head != required_head:
        raise ManifestError(
            f"repository HEAD mismatch: expected {required_head}, observed {actual_head}"
        )
    porcelain = _git_read(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if require_clean and porcelain:
        first_entries = ", ".join(porcelain.splitlines()[:5])
        raise ManifestError(f"repository is dirty but require_clean=true: {first_entries}")
    return {
        "observed_head": actual_head,
        "observed_clean": not bool(porcelain),
    }


def _version_major(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d+)\.", value)
    if match is None:
        compact = re.fullmatch(r"\s*(\d)[0-9]{1,2}\s*", value)
        return int(compact.group(1)) if compact else None
    return int(match.group(1))


def _normalize_plan_number(value: Any, label: str) -> str:
    text = str(value).strip().lstrip("pP")
    if not re.fullmatch(r"[0-9]{1,2}", text):
        raise ManifestError(f"{label} must identify a two-digit HEC-RAS plan")
    return text.zfill(2)


def _normalize_fixture(raw: Any, index: int) -> dict[str, Any]:
    fixture = _require_mapping(raw, f"fixtures[{index}]")
    fixture_id = _require_identifier(
        fixture.get("fixture_id"), f"fixtures[{index}].fixture_id"
    )
    source_kind = _require_text(fixture.get("source_kind"), f"fixtures[{index}].source_kind")
    if source_kind not in _SOURCE_KINDS:
        raise ManifestError(f"fixture {fixture_id} has unsupported source_kind={source_kind!r}")
    _reject_unknown_fields(
        fixture,
        _FIXTURE_COMMON_FIELDS | _FIXTURE_KIND_FIELDS[source_kind],
        f"fixture {fixture_id}",
    )
    normalized = deepcopy(fixture)
    normalized["fixture_id"] = fixture_id
    normalized["source_kind"] = source_kind
    normalized["plan_number"] = _normalize_plan_number(
        fixture.get("plan_number"), f"fixture {fixture_id}.plan_number"
    )
    normalized["plan_type"] = _require_text(
        fixture.get("plan_type"), f"fixture {fixture_id}.plan_type"
    )
    normalized["plan_title"] = _require_text(
        fixture.get("plan_title"), f"fixture {fixture_id}.plan_title"
    )
    normalized["data_origin"] = _require_text(
        fixture.get("data_origin", "captured_real"),
        f"fixture {fixture_id}.data_origin",
    )
    if normalized["data_origin"] not in _DATA_ORIGINS:
        raise ManifestError(
            f"fixture {fixture_id}.data_origin must be one of {sorted(_DATA_ORIGINS)}"
        )
    if fixture.get("source_immutable") is not True:
        raise ManifestError(f"fixture {fixture_id} must assert source_immutable=true")
    source_fingerprint = fixture.get("source_content_fingerprint")
    if source_fingerprint is not None:
        if not isinstance(source_fingerprint, str) or not _SHA256_RE.fullmatch(
            source_fingerprint
        ):
            raise ManifestError(
                f"fixture {fixture_id}.source_content_fingerprint must be lowercase SHA-256"
            )
        normalized["source_content_fingerprint"] = source_fingerprint

    if source_kind == "project_file":
        normalized["source_project"] = _absolute_path(
            fixture.get("source_project"),
            f"fixture {fixture_id}.source_project",
            must_exist=True,
            kind="file",
        )
        if not Path(normalized["source_project"]).is_file():
            raise ManifestError(f"fixture {fixture_id} source_project is not a regular file")
        replay = fixture.get("replay_artifacts")
        if replay is not None:
            if normalized["data_origin"] != "captured_real":
                raise ManifestError(
                    f"fixture {fixture_id} with replay_artifacts must keep its "
                    "main source data_origin=captured_real"
                )
            normalized["replay_artifacts"] = _normalize_replay_artifacts(
                replay,
                fixture_id=fixture_id,
                project_stem=Path(normalized["source_project"]).stem,
                plan_number=normalized["plan_number"],
            )
            source_parent = Path(normalized["source_project"]).parent
            replay_root = Path(normalized["replay_artifacts"]["source_root"])
            if _is_within(replay_root, source_parent) or _is_within(
                source_parent,
                replay_root,
            ):
                raise ManifestError(
                    f"fixture {fixture_id}.replay_artifacts.source_root and "
                    "source_project parent must be disjoint"
                )
    elif source_kind == "ras_examples":
        normalized["example_project"] = _require_text(
            fixture.get("example_project"), f"fixture {fixture_id}.example_project"
        )
        normalized["archive_sha256"] = _require_text(
            fixture.get("archive_sha256"), f"fixture {fixture_id}.archive_sha256"
        )
        if not _SHA256_RE.fullmatch(normalized["archive_sha256"]):
            raise ManifestError(f"fixture {fixture_id}.archive_sha256 is invalid")
    else:
        normalized["fixture_database"] = _absolute_path(
            fixture.get("fixture_database"),
            f"fixture {fixture_id}.fixture_database",
            must_exist=True,
            kind="file",
        )
        project_id = fixture.get("project_id")
        if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id < 1:
            raise ManifestError(f"fixture {fixture_id}.project_id must be a positive integer")
        normalized["project_id"] = project_id
    return normalized


def _normalize_engine(raw: Any, index: int) -> dict[str, Any]:
    engine = _require_mapping(raw, f"engines[{index}]")
    engine_id = _require_identifier(
        engine.get("engine_id"), f"engines[{index}].engine_id"
    )
    execution_api = _require_text(
        engine.get("execution_api"), f"engine {engine_id}.execution_api"
    )
    if execution_api not in _EXECUTION_APIS:
        raise ManifestError(f"engine {engine_id} has unsupported execution_api={execution_api!r}")
    _reject_unknown_fields(
        engine,
        _ENGINE_COMMON_FIELDS | _ENGINE_API_FIELDS[execution_api],
        f"engine {engine_id}",
    )
    requested = _require_text(
        engine.get("version_requested"), f"engine {engine_id}.version_requested"
    )
    expected_format = _require_text(
        engine.get("expected_result_format"),
        f"engine {engine_id}.expected_result_format",
    )
    if expected_format not in _RESULT_FORMATS:
        raise ManifestError(f"engine {engine_id} has invalid expected_result_format")
    major = _version_major(requested)
    if major is None:
        raise ManifestError(
            f"engine {engine_id}.version_requested does not identify a HEC-RAS version"
        )
    version_format = "legacy" if major < 5 else "hdf"
    if version_format != expected_format:
        raise ManifestError(
            f"engine {engine_id} version {requested} implies {version_format}, not {expected_format}"
        )
    support_state = _require_text(
        engine.get("support_state", "supported"), f"engine {engine_id}.support_state"
    )
    if support_state not in _SUPPORT_STATES:
        raise ManifestError(f"engine {engine_id} has invalid support_state")

    normalized = deepcopy(engine)
    normalized.update(
        {
            "engine_id": engine_id,
            "execution_api": execution_api,
            "version_requested": requested,
            "expected_result_format": expected_format,
            "support_state": support_state,
        }
    )
    if execution_api == "ras_cmdr":
        executable = Path(
            _absolute_path(
                engine.get("executable"),
                f"engine {engine_id}.executable",
                must_exist=True,
                kind="file",
            )
        )
        if not executable.is_file():
            raise ManifestError(f"engine {engine_id}.executable is not a regular file")
        if executable.name.casefold() != "ras.exe":
            raise ManifestError(
                f"engine {engine_id}.executable must identify Ras.exe, not {executable.name!r}"
            )
        expected_hash = _require_text(
            engine.get("executable_sha256"), f"engine {engine_id}.executable_sha256"
        )
        if not _SHA256_RE.fullmatch(expected_hash):
            raise ManifestError(f"engine {engine_id}.executable_sha256 is invalid")
        actual_hash = _file_sha256(executable)
        if actual_hash != expected_hash:
            raise ManifestError(
                f"engine {engine_id} executable hash mismatch: expected {expected_hash}, observed {actual_hash}"
            )
        normalized["executable"] = str(executable)
        normalized["executable_sha256"] = actual_hash
        for forbidden in ("controller_version", "controller_progid", "blocking"):
            if forbidden in engine:
                raise ManifestError(f"engine {engine_id}.{forbidden} is not valid for ras_cmdr")
    else:
        # Resolve through ras-commander's static mapping only. This does not
        # dispatch COM or inspect Controller registration.
        from ras_commander import RasControl

        normalized["controller_version"] = _require_text(
            engine.get("controller_version"), f"engine {engine_id}.controller_version"
        )
        normalized["resolved_controller_version"] = _require_text(
            engine.get("resolved_controller_version"),
            f"engine {engine_id}.resolved_controller_version",
        )
        progid = _require_text(
            engine.get("controller_progid"), f"engine {engine_id}.controller_progid"
        )
        if not re.fullmatch(r"RAS[0-9]+\.HECRASController", progid):
            raise ManifestError(f"engine {engine_id}.controller_progid is malformed")
        try:
            requested_progid = RasControl.get_controller_progid(requested)
            controller_progid = RasControl.get_controller_progid(
                normalized["controller_version"]
            )
        except ValueError as exc:
            raise ManifestError(f"engine {engine_id} has unsupported Controller version") from exc
        if controller_progid != requested_progid:
            raise ManifestError(
                f"engine {engine_id}.controller_version routes to {controller_progid}, "
                f"not requested route {requested_progid}"
            )
        if progid != requested_progid:
            raise ManifestError(
                f"engine {engine_id}.controller_progid mismatch: expected "
                f"{requested_progid}, observed {progid}"
            )
        canonical_version = RasControl._CONTROLLER_CANONICAL_VERSIONS[requested_progid]
        if normalized["resolved_controller_version"] != canonical_version:
            raise ManifestError(
                f"engine {engine_id}.resolved_controller_version mismatch: expected "
                f"{canonical_version}, observed {normalized['resolved_controller_version']}"
            )
        normalized["controller_progid"] = progid
        if not isinstance(engine.get("blocking"), bool):
            raise ManifestError(f"engine {engine_id}.blocking must be true or false")
        normalized["blocking"] = engine["blocking"]
        if "executable" in engine or "executable_sha256" in engine:
            raise ManifestError(
                f"engine {engine_id} cannot claim a COM server executable through the Controller contract"
            )
    return normalized


def _normalize_lane(
    raw: Any,
    index: int,
    fixtures: Mapping[str, dict[str, Any]],
    engines: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    lane = _require_mapping(raw, f"lanes[{index}]")
    lane_id = _require_identifier(lane.get("lane_id"), f"lanes[{index}].lane_id")
    fixture_id = _require_identifier(lane.get("fixture_id"), f"lane {lane_id}.fixture_id")
    engine_id = _require_identifier(lane.get("engine_id"), f"lane {lane_id}.engine_id")
    _reject_unknown_fields(lane, _LANE_FIELDS, f"lane {lane_id}")
    if fixture_id not in fixtures:
        raise ManifestError(f"lane {lane_id} references unknown fixture {fixture_id!r}")
    if engine_id not in engines:
        raise ManifestError(f"lane {lane_id} references unknown engine {engine_id!r}")
    initial_state = _require_text(lane.get("initial_state"), f"lane {lane_id}.initial_state")
    if initial_state not in _INITIAL_STATES:
        raise ManifestError(f"lane {lane_id} has unsupported initial_state={initial_state!r}")
    terminal = _require_text(
        lane.get("expected_terminal_category", "passed"),
        f"lane {lane_id}.expected_terminal_category",
    )
    if terminal not in _TERMINAL_CATEGORIES:
        raise ManifestError(f"lane {lane_id} has invalid expected_terminal_category")
    expected_failure_reason = lane.get("expected_failure_reason_code")
    if terminal == "expected_failure":
        expected_failure_reason = _require_text(
            expected_failure_reason,
            f"lane {lane_id}.expected_failure_reason_code",
        )
    elif "expected_failure_reason_code" in lane:
        raise ManifestError(
            f"lane {lane_id}.expected_failure_reason_code is valid only when "
            "expected_terminal_category='expected_failure'"
        )
    tags = lane.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ManifestError(f"lane {lane_id}.tags must be an array of nonempty strings")
    required = lane.get("required_invariants", [f"R{number:02d}" for number in range(1, 13)])
    if (
        not isinstance(required, list)
        or not required
        or any(
            not re.fullmatch(r"R(?:0[1-9]|1[0-2])", str(item))
            for item in required
        )
    ):
        raise ManifestError(f"lane {lane_id}.required_invariants contains an invalid ID")
    normalized = deepcopy(lane)
    normalized.update(
        {
            "lane_id": lane_id,
            "fixture_id": fixture_id,
            "engine_id": engine_id,
            "initial_state": initial_state,
            "expected_terminal_category": terminal,
            "tags": sorted(set(tags)),
            "required_invariants": sorted(set(required)),
        }
    )
    if expected_failure_reason is not None:
        normalized["expected_failure_reason_code"] = expected_failure_reason
    return normalized


def normalize_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a source manifest and return canonical, resolved content.

    This phase does not import COM, initialize a project, or execute HEC-RAS.
    """
    if not isinstance(payload, Mapping):
        raise ManifestError("manifest must be an object")
    source = deepcopy(dict(payload))
    _reject_command_fields(source)
    _reject_unknown_fields(source, _TOP_LEVEL_FIELDS, "manifest")
    if source.get("schema_version") != 1:
        raise ManifestError("only manifest schema_version=1 is supported")
    run_name = _require_text(source.get("run_name"), "run_name")
    repository = _require_mapping(source.get("repository"), "repository")
    _reject_unknown_fields(repository, _REPOSITORY_FIELDS, "repository")
    repository_root = _absolute_path(
        repository.get("root"),
        "repository.root",
        must_exist=True,
        kind="directory",
    )
    required_head = _require_text(repository.get("required_head"), "repository.required_head")
    if not _GIT_RE.fullmatch(required_head):
        raise ManifestError("repository.required_head must be a lowercase 40-hex commit")
    if not isinstance(repository.get("require_clean"), bool):
        raise ManifestError("repository.require_clean must be true or false")
    if not isinstance(repository.get("bind_running_code"), bool):
        raise ManifestError("repository.bind_running_code must be true or false")
    repository_observation = _preflight_repository(
        Path(repository_root),
        required_head=required_head,
        require_clean=repository["require_clean"],
    )

    archive_root = _absolute_path(
        source.get("archive_root"),
        "archive_root",
        kind="directory",
    )
    execution_root = _absolute_path(
        source.get("execution_root"),
        "execution_root",
        kind="directory",
    )
    if _is_within(Path(archive_root), Path(execution_root)) or _is_within(
        Path(execution_root), Path(archive_root)
    ):
        raise ManifestError("archive_root and execution_root must not overlap")

    defaults = _require_mapping(source.get("defaults", {}), "defaults")
    _reject_unknown_fields(defaults, _DEFAULT_FIELDS, "defaults")
    timeout = defaults.get("timeout_seconds", 14_400)
    grace = defaults.get("termination_grace_seconds", 120)
    jobs = defaults.get("real_engine_jobs", 1)
    for value, label in ((timeout, "timeout_seconds"), (grace, "termination_grace_seconds")):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ManifestError(f"defaults.{label} must be a positive integer")
    if jobs != 1:
        raise ManifestError("pre-engine schema requires defaults.real_engine_jobs=1")
    if not isinstance(defaults.get("hash_files", True), bool):
        raise ManifestError("defaults.hash_files must be true or false")

    fixture_rows = [
        _normalize_fixture(item, index)
        for index, item in enumerate(_require_list(source.get("fixtures"), "fixtures"))
    ]
    engine_rows = [
        _normalize_engine(item, index)
        for index, item in enumerate(_require_list(source.get("engines"), "engines"))
    ]
    fixtures = {item["fixture_id"]: item for item in fixture_rows}
    engines = {item["engine_id"]: item for item in engine_rows}
    if len(fixtures) != len(fixture_rows):
        raise ManifestError("fixture_id values must be unique")
    if len(engines) != len(engine_rows):
        raise ManifestError("engine_id values must be unique")
    if len({item["fixture_id"].casefold() for item in fixture_rows}) != len(fixture_rows):
        raise ManifestError("fixture_id values must be case-insensitively unique")
    if len({item["engine_id"].casefold() for item in engine_rows}) != len(engine_rows):
        raise ManifestError("engine_id values must be case-insensitively unique")
    lane_rows = [
        _normalize_lane(item, index, fixtures, engines)
        for index, item in enumerate(_require_list(source.get("lanes"), "lanes"))
    ]
    if len({item["lane_id"] for item in lane_rows}) != len(lane_rows):
        raise ManifestError("lane_id values must be unique")
    if len({item["lane_id"].casefold() for item in lane_rows}) != len(lane_rows):
        raise ManifestError("lane_id values must be case-insensitively unique")

    protected_roots = [("repository.root", Path(repository_root))]
    for fixture in fixture_rows:
        source_path = fixture.get("source_project") or fixture.get("fixture_database")
        if source_path is not None:
            protected_roots.append(
                (f"fixture {fixture['fixture_id']} source tree", Path(source_path).parent)
            )
        replay = fixture.get("replay_artifacts")
        if isinstance(replay, Mapping):
            protected_roots.append(
                (
                    f"fixture {fixture['fixture_id']} replay source",
                    Path(replay["source_root"]),
                )
            )
    for output_label, output_root in (
        ("archive_root", Path(archive_root)),
        ("execution_root", Path(execution_root)),
    ):
        for protected_label, protected_root in protected_roots:
            if _is_within(output_root, protected_root) or _is_within(
                protected_root, output_root
            ):
                raise ManifestError(
                    f"{output_label} and {protected_label} must not overlap"
                )

    normalized = {
        "schema_version": 1,
        "run_name": run_name,
        "repository": {
            "root": repository_root,
            "required_head": required_head,
            "require_clean": repository["require_clean"],
            "bind_running_code": repository["bind_running_code"],
            **repository_observation,
        },
        "archive_root": archive_root,
        "execution_root": execution_root,
        "defaults": {
            "timeout_seconds": timeout,
            "termination_grace_seconds": grace,
            "hash_files": defaults.get("hash_files", True),
            "real_engine_jobs": 1,
        },
        "fixtures": sorted(fixture_rows, key=lambda item: item["fixture_id"]),
        "engines": sorted(engine_rows, key=lambda item: item["engine_id"]),
        "lanes": sorted(lane_rows, key=lambda item: item["lane_id"]),
    }
    normalized["manifest_sha256"] = canonical_sha256(normalized)
    return normalized


def load_and_normalize_manifest(path: str | Path) -> dict[str, Any]:
    return normalize_manifest(load_manifest(path))


__all__ = [
    "ManifestError",
    "canonical_json_bytes",
    "canonical_sha256",
    "load_and_normalize_manifest",
    "load_manifest",
    "normalize_manifest",
]
