"""Immutable run planning for the offline qualification worker."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import psutil
import pyarrow
import ras_commander

from .manifest import canonical_sha256, load_and_normalize_manifest, load_manifest
from .receipts import (
    read_json_with_digest,
    write_json_with_digest,
)
from .run_io import write_bytes_with_digest


class PlanningError(RuntimeError):
    """A run root or one of its immutable pins is invalid."""


@dataclass(frozen=True)
class RunContext:
    run_root: Path
    descriptor: dict[str, Any]
    descriptor_sha256: str
    manifest: dict[str, Any]
    normalized_manifest_sha256: str


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_runtime_pins() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "pyarrow_version": pyarrow.__version__,
        "psutil_version": psutil.__version__,
        "ras_commander_version": str(ras_commander.__version__),
        "ras_commander_import_path": str(
            Path(ras_commander.__file__).resolve(strict=True)
        ),
    }


def _prove_running_code_binding(repository_root: Path) -> None:
    harness_root = Path(__file__).resolve(strict=True).parents[3]
    package_root = Path(ras_commander.__file__).resolve(strict=True).parent.parent
    try:
        harness_bound = os.path.samefile(harness_root, repository_root)
        package_bound = os.path.samefile(package_root, repository_root)
    except OSError as exc:
        raise PlanningError("could not prove running-code repository identity") from exc
    if not harness_bound or not package_bound:
        raise PlanningError(
            "qualification harness and ras_commander must both originate from the pinned repository"
        )


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _verify_normalized_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    claimed = normalized.pop("manifest_sha256", None)
    if not isinstance(claimed, str) or canonical_sha256(normalized) != claimed:
        raise PlanningError("normalized manifest hash does not match its canonical content")
    normalized["manifest_sha256"] = claimed
    return normalized


def plan_run(manifest_path: str | Path, run_root: str | Path) -> RunContext:
    """Create one immutable archive run and one separate local execution root."""
    source_path = Path(manifest_path).resolve(strict=True)
    source_manifest = load_manifest(source_path)
    source_repository = source_manifest.get("repository")
    if not isinstance(source_repository, Mapping):
        raise PlanningError("source manifest repository must be an object")
    if source_repository.get("bind_running_code") is not True:
        raise PlanningError("plan_run requires repository.bind_running_code=true")
    if source_repository.get("require_clean") is not True:
        raise PlanningError("plan_run requires repository.require_clean=true")
    normalized = load_and_normalize_manifest(source_path)
    repository_root = Path(normalized["repository"]["root"]).resolve(strict=True)
    _prove_running_code_binding(repository_root)
    if normalized["repository"].get("observed_clean") is not True:
        raise PlanningError("plan_run requires a proved-clean pinned repository")
    archive_root = Path(normalized["archive_root"]).resolve(strict=False)
    execution_root = Path(normalized["execution_root"]).resolve(strict=False)
    target = Path(run_root).resolve(strict=False)
    if target == archive_root or not _is_within(target, archive_root):
        raise PlanningError("run_root must be a new child of manifest.archive_root")
    if target.exists():
        raise FileExistsError(f"archive run root already exists: {target}")

    python_executable = Path(sys.executable).resolve(strict=True)
    run_id = str(uuid.uuid4())
    execution_run_root = execution_root / run_id
    if execution_run_root.exists():
        raise FileExistsError(f"execution run root already exists: {execution_run_root}")

    archive_root.mkdir(parents=True, exist_ok=True)
    execution_root.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=False, exist_ok=False)
    execution_run_root.mkdir(parents=False, exist_ok=False)

    source_manifest_sha256 = write_bytes_with_digest(
        target / "manifest.source.json",
        source_path.read_bytes(),
    )
    normalized_file_sha256 = write_json_with_digest(
        target / "manifest.normalized.json",
        normalized,
    )
    descriptor = {
        "schema_version": 1,
        "run_id": run_id,
        "run_name": normalized["run_name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archive_run_root": str(target),
        "execution_run_root": str(execution_run_root),
        "source_manifest_sha256": source_manifest_sha256,
        "normalized_manifest_sha256": normalized_file_sha256,
        "manifest_sha256": normalized["manifest_sha256"],
        "repository_root": normalized["repository"]["root"],
        "bind_running_code": True,
        "git_head": normalized["repository"]["required_head"],
        "python_executable": str(python_executable),
        "python_executable_sha256": file_sha256(python_executable),
        **current_runtime_pins(),
        "lane_ids": [lane["lane_id"] for lane in normalized["lanes"]],
        "hec_ras_execution_enabled": False,
    }
    descriptor_sha256 = write_json_with_digest(target / "run.json", descriptor)
    return RunContext(
        run_root=target,
        descriptor=descriptor,
        descriptor_sha256=descriptor_sha256,
        manifest=normalized,
        normalized_manifest_sha256=normalized_file_sha256,
    )


def load_run(run_root: str | Path) -> RunContext:
    """Read and re-prove all immutable plan pins without staging a project."""
    root = Path(run_root).resolve(strict=True)
    descriptor, descriptor_sha256 = read_json_with_digest(root / "run.json")
    source_manifest, source_manifest_sha256 = read_json_with_digest(
        root / "manifest.source.json"
    )
    manifest, normalized_file_sha256 = read_json_with_digest(
        root / "manifest.normalized.json"
    )
    manifest = _verify_normalized_manifest(manifest)
    checks = {
        "archive_run_root": str(root),
        "source_manifest_sha256": source_manifest_sha256,
        "normalized_manifest_sha256": normalized_file_sha256,
        "manifest_sha256": manifest["manifest_sha256"],
        "repository_root": manifest["repository"]["root"],
        "git_head": manifest["repository"]["required_head"],
    }
    for field, expected in checks.items():
        if descriptor.get(field) != expected:
            raise PlanningError(f"run descriptor pin mismatch for {field}")
    executable = Path(str(descriptor.get("python_executable", ""))).resolve(strict=True)
    if file_sha256(executable) != descriptor.get("python_executable_sha256"):
        raise PlanningError("pinned Python interpreter hash mismatch")
    if not os.path.samefile(executable, Path(sys.executable).resolve(strict=True)):
        raise PlanningError("run was planned for a different Python interpreter")
    if descriptor.get("bind_running_code") is not True:
        raise PlanningError("run descriptor does not bind running code")
    source_repository = source_manifest.get("repository")
    if (
        not isinstance(source_repository, Mapping)
        or source_repository.get("bind_running_code") is not True
        or source_repository.get("require_clean") is not True
    ):
        raise PlanningError("archived source manifest lacks mandatory code binding")
    _prove_running_code_binding(Path(descriptor["repository_root"]).resolve(strict=True))
    for field, observed in current_runtime_pins().items():
        if descriptor.get(field) != observed:
            raise PlanningError(f"runtime pin mismatch for {field}")
    execution_run_root = Path(str(descriptor.get("execution_run_root", ""))).resolve(
        strict=True
    )
    expected_execution_parent = Path(manifest["execution_root"]).resolve(strict=True)
    if execution_run_root.parent != expected_execution_parent:
        raise PlanningError("execution run root escaped manifest.execution_root")
    if execution_run_root.name != descriptor.get("run_id"):
        raise PlanningError("execution run root does not match run_id")
    if descriptor.get("hec_ras_execution_enabled") is not False:
        raise PlanningError("offline run descriptor unexpectedly enables HEC-RAS execution")
    return RunContext(
        run_root=root,
        descriptor=descriptor,
        descriptor_sha256=descriptor_sha256,
        manifest=manifest,
        normalized_manifest_sha256=normalized_file_sha256,
    )


def select_lane(context: RunContext, lane_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    lanes = {lane["lane_id"]: lane for lane in context.manifest["lanes"]}
    if lane_id not in lanes:
        raise PlanningError(f"unknown lane_id: {lane_id}")
    lane = lanes[lane_id]
    fixtures = {
        fixture["fixture_id"]: fixture for fixture in context.manifest["fixtures"]
    }
    engines = {engine["engine_id"]: engine for engine in context.manifest["engines"]}
    return lane, fixtures[lane["fixture_id"]], engines[lane["engine_id"]]


__all__ = [
    "PlanningError",
    "RunContext",
    "current_runtime_pins",
    "file_sha256",
    "load_run",
    "plan_run",
    "select_lane",
]
