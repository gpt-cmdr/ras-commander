from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.qualification.execution_evidence.manifest import (
    ManifestError,
    normalize_manifest,
)
from scripts.qualification.execution_evidence.cli import main
from scripts.qualification.execution_evidence.receipts import read_json_with_digest
from scripts.qualification.execution_evidence.snapshots import SnapshotError


pytestmark = pytest.mark.qualification_harness


def _manifest(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Qualification Test"], check=True)
    (repo / "tracked.txt").write_text("pinned\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fixture"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = tmp_path / "source"
    source.mkdir()
    project = source / "Model.prj"
    project.write_text("Proj Title=Test\n", encoding="ascii")
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    executable = engine_dir / "Ras.exe"
    executable.write_bytes(b"not executed")
    return {
        "schema_version": 1,
        "run_name": "test-run",
        "repository": {
            "root": str(repo),
            "required_head": head,
            "require_clean": True,
            "bind_running_code": False,
        },
        "archive_root": str(tmp_path / "archive"),
        "execution_root": str(tmp_path / "execution"),
        "defaults": {
            "timeout_seconds": 60,
            "termination_grace_seconds": 10,
            "hash_files": True,
            "real_engine_jobs": 1,
        },
        "fixtures": [
            {
                "fixture_id": "fixture-a",
                "source_kind": "project_file",
                "source_project": str(project),
                "source_immutable": True,
                "source_content_fingerprint": "f" * 64,
                "data_origin": "captured_real",
                "plan_number": 1,
                "plan_title": "Base",
                "plan_type": "steady_1d",
            }
        ],
        "engines": [
            {
                "engine_id": "ras-7",
                "execution_api": "ras_cmdr",
                "version_requested": "7.0",
                "expected_result_format": "hdf",
                "support_state": "supported",
                "executable": str(executable),
                "executable_sha256": hashlib.sha256(b"not executed").hexdigest(),
            }
        ],
        "lanes": [
            {
                "lane_id": "lane-a",
                "fixture_id": "fixture-a",
                "engine_id": "ras-7",
                "initial_state": "neither",
                "expected_terminal_category": "passed",
                "tags": ["real_ras", "real_ras"],
            }
        ],
    }


def test_normalization_is_deterministic_and_resolves_paths(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    first = normalize_manifest(payload)
    second = normalize_manifest(payload)

    assert first == second
    assert len(first["manifest_sha256"]) == 64
    assert first["fixtures"][0]["plan_number"] == "01"
    assert first["lanes"][0]["tags"] == ["real_ras"]
    assert Path(first["fixtures"][0]["source_project"]).is_absolute()


@pytest.mark.parametrize("field", ["command", "argv", "raw_command"])
def test_raw_execution_commands_are_forbidden(tmp_path: Path, field: str) -> None:
    payload = _manifest(tmp_path)
    payload["engines"][0][field] = ["Ras.exe", "-c"]
    with pytest.raises(ManifestError, match="forbidden"):
        normalize_manifest(payload)


def test_executable_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["engines"][0]["executable_sha256"] = "0" * 64
    with pytest.raises(ManifestError, match="hash mismatch"):
        normalize_manifest(payload)


def test_output_root_may_not_overlap_source(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    source = Path(payload["fixtures"][0]["source_project"]).parent
    payload["execution_root"] = str(source / "runs")
    with pytest.raises(ManifestError, match="must not overlap"):
        normalize_manifest(payload)


def test_duplicate_lane_ids_are_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["lanes"].append(dict(payload["lanes"][0]))
    with pytest.raises(ManifestError, match="lane_id values must be unique"):
        normalize_manifest(payload)


def test_path_unsafe_lane_id_is_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["lanes"][0]["lane_id"] = "../escape"
    with pytest.raises(ManifestError, match="path-safe identifier"):
        normalize_manifest(payload)


def test_version_result_family_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["engines"][0]["expected_result_format"] = "legacy"
    with pytest.raises(ManifestError, match="implies hdf"):
        normalize_manifest(payload)


def test_repository_head_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["repository"]["required_head"] = "0" * 40
    with pytest.raises(ManifestError, match="HEAD mismatch"):
        normalize_manifest(payload)


def test_dirty_repository_is_rejected_when_required(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    (Path(payload["repository"]["root"]) / "untracked.txt").write_text(
        "dirty\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError, match="repository is dirty"):
        normalize_manifest(payload)


def test_dirty_repository_is_observed_when_allowed(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["repository"]["require_clean"] = False
    (Path(payload["repository"]["root"]) / "untracked.txt").write_text(
        "dirty\n", encoding="utf-8"
    )
    normalized = normalize_manifest(payload)
    assert normalized["repository"]["observed_clean"] is False


def test_source_fingerprint_is_validated_and_preserved(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    normalized = normalize_manifest(payload)
    assert normalized["fixtures"][0]["source_content_fingerprint"] == "f" * 64

    payload["fixtures"][0]["source_content_fingerprint"] = "not-a-hash"
    with pytest.raises(ManifestError, match="source_content_fingerprint"):
        normalize_manifest(payload)


def test_rascontrol_identity_uses_canonical_static_mapping(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["engines"] = [
        {
            "engine_id": "controller-630",
            "execution_api": "ras_control",
            "version_requested": "6.3.0.2",
            "expected_result_format": "hdf",
            "support_state": "supported",
            "controller_version": "6.3.0.2",
            "resolved_controller_version": "6.3.0.2",
            "controller_progid": "RAS630.HECRASController",
            "blocking": True,
        }
    ]
    payload["lanes"][0]["engine_id"] = "controller-630"
    normalized = normalize_manifest(payload)
    assert normalized["engines"][0]["controller_progid"] == "RAS630.HECRASController"

    payload["engines"][0]["controller_progid"] = "RAS631.HECRASController"
    with pytest.raises(ManifestError, match="controller_progid mismatch"):
        normalize_manifest(payload)


def test_rascontrol_canonical_version_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["engines"] = [
        {
            "engine_id": "controller-64",
            "execution_api": "ras_control",
            "version_requested": "6.4",
            "expected_result_format": "hdf",
            "support_state": "supported",
            "controller_version": "6.4",
            "resolved_controller_version": "6.4",
            "controller_progid": "RAS641.HECRASController",
            "blocking": True,
        }
    ]
    payload["lanes"][0]["engine_id"] = "controller-64"
    with pytest.raises(ManifestError, match="resolved_controller_version mismatch"):
        normalize_manifest(payload)


def test_cli_validate_runs_repository_preflight_and_writes_digest_bound_normalized_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    normalized_path = tmp_path / "normalized.json"

    assert main(
        [
            "validate",
            "--manifest",
            str(manifest_path),
            "--output-normalized",
            str(normalized_path),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    normalized, file_digest = read_json_with_digest(normalized_path)
    assert output["hec_ras_invoked"] is False
    assert output["manifest_sha256"] == normalized["manifest_sha256"]
    assert output["normalized_file_sha256"] == file_digest
    assert normalized["repository"]["observed_clean"] is True


def test_repository_requires_exact_top_level_and_strict_binding_flag(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    nested = Path(payload["repository"]["root"]) / "nested"
    nested.mkdir()
    payload["repository"]["root"] = str(nested)
    with pytest.raises(ManifestError, match="exact git top-level"):
        normalize_manifest(payload)

    payload = _manifest(tmp_path / "second")
    payload["repository"].pop("bind_running_code")
    with pytest.raises(ManifestError, match="bind_running_code"):
        normalize_manifest(payload)
    payload["repository"]["bind_running_code"] = "false"
    with pytest.raises(ManifestError, match="bind_running_code"):
        normalize_manifest(payload)


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("top", "worker_command"),
        ("repository", "branch"),
        ("defaults", "shell"),
        ("fixture", "copy_command"),
        ("engine", "args"),
        ("lane", "worker"),
    ],
)
def test_unknown_fields_and_command_smuggling_are_rejected(
    tmp_path: Path,
    location: str,
    field: str,
) -> None:
    payload = _manifest(tmp_path)
    targets = {
        "top": payload,
        "repository": payload["repository"],
        "defaults": payload["defaults"],
        "fixture": payload["fixtures"][0],
        "engine": payload["engines"][0],
        "lane": payload["lanes"][0],
    }
    targets[location][field] = ["Ras.exe", "-c"]
    with pytest.raises(ManifestError, match="unknown fields|forbidden"):
        normalize_manifest(payload)


def test_rascmdr_executable_must_be_ras_exe(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    original = Path(payload["engines"][0]["executable"])
    substitute = original.with_name("not-ras.exe")
    substitute.write_bytes(original.read_bytes())
    payload["engines"][0]["executable"] = str(substitute)
    with pytest.raises(ManifestError, match="must identify Ras.exe"):
        normalize_manifest(payload)


@pytest.mark.parametrize("identity_kind", ["fixture", "engine", "lane"])
def test_identifiers_are_case_insensitively_unique(
    tmp_path: Path,
    identity_kind: str,
) -> None:
    payload = _manifest(tmp_path)
    if identity_kind == "fixture":
        duplicate = dict(payload["fixtures"][0])
        duplicate["fixture_id"] = "Fixture-A"
        payload["fixtures"].append(duplicate)
    elif identity_kind == "engine":
        duplicate = dict(payload["engines"][0])
        duplicate["engine_id"] = "RAS-7"
        payload["engines"].append(duplicate)
    else:
        duplicate = dict(payload["lanes"][0])
        duplicate["lane_id"] = "Lane-A"
        payload["lanes"].append(duplicate)
    with pytest.raises(ManifestError, match="case-insensitively unique"):
        normalize_manifest(payload)


def test_unicode_plan_digits_are_rejected(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["fixtures"][0]["plan_number"] = "١"
    with pytest.raises(ManifestError, match="two-digit HEC-RAS plan"):
        normalize_manifest(payload)


@pytest.mark.parametrize(
    "origin",
    [
        "captured_real",
        "staged_execution_output",
        "archived_failed_execution",
        "generated_edge_case",
    ],
)
def test_dataset_origin_registry_is_closed(
    tmp_path: Path,
    origin: str,
) -> None:
    payload = _manifest(tmp_path)
    payload["fixtures"][0]["data_origin"] = origin
    assert normalize_manifest(payload)["fixtures"][0]["data_origin"] == origin

    payload["fixtures"][0]["data_origin"] = "copied_source"
    with pytest.raises(ManifestError, match="data_origin"):
        normalize_manifest(payload)


def test_output_roots_cannot_overlap_each_other_or_repository(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["archive_root"] = str(tmp_path / "shared")
    payload["execution_root"] = str(tmp_path / "shared" / "execution")
    with pytest.raises(ManifestError, match="archive_root and execution_root"):
        normalize_manifest(payload)

    payload = _manifest(tmp_path / "repo-overlap")
    payload["archive_root"] = str(Path(payload["repository"]["root"]) / "archive")
    with pytest.raises(ManifestError, match="repository.root"):
        normalize_manifest(payload)


def _add_replay_artifacts(payload: dict, replay_root: Path) -> Path:
    replay_root.mkdir(exist_ok=True)
    artifact = replay_root / "Model.p01.hdf"
    artifact.write_bytes(b"captured result")
    info = artifact.stat()
    payload["fixtures"][0]["replay_artifacts"] = {
        "source_root": str(replay_root),
        "data_origin": "staged_execution_output",
        "files": [
            {
                "relative_path": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
        ],
    }
    return artifact


def test_replay_artifacts_are_strictly_pinned_and_normalized(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    artifact = _add_replay_artifacts(payload, tmp_path / "replay")
    normalized = normalize_manifest(payload)
    replay = normalized["fixtures"][0]["replay_artifacts"]
    assert replay["source_root"] == str(artifact.parent.resolve())
    assert replay["files"][0]["relative_path"] == artifact.name


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda replay: replay.update({"unknown": True}), "unknown fields"),
        (
            lambda replay: replay.update({"data_origin": "captured_real"}),
            "data_origin",
        ),
        (
            lambda replay: replay["files"][0].update({"relative_path": "../escape"}),
            "exact relative path",
        ),
        (
            lambda replay: replay["files"][0].update({"relative_path": "other.txt"}),
            "replay allowlist",
        ),
        (
            lambda replay: replay["files"][0].update({"sha256": "0" * 64}),
            "metadata mismatch",
        ),
        (
            lambda replay: replay["files"][0].update({"size_bytes": 999}),
            "metadata mismatch",
        ),
        (
            lambda replay: replay["files"][0].update({"mtime_ns": 0}),
            "metadata mismatch",
        ),
    ],
)
def test_replay_artifact_contract_rejects_untrusted_claims(
    tmp_path: Path,
    mutation,
    match: str,
) -> None:
    payload = _manifest(tmp_path)
    _add_replay_artifacts(payload, tmp_path / "replay")
    mutation(payload["fixtures"][0]["replay_artifacts"])
    with pytest.raises(ManifestError, match=match):
        normalize_manifest(payload)


def test_replay_artifacts_reject_casefold_duplicates_and_unstable_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _manifest(tmp_path)
    _add_replay_artifacts(payload, tmp_path / "replay")
    replay = payload["fixtures"][0]["replay_artifacts"]
    replay["files"].append(dict(replay["files"][0]))
    with pytest.raises(ManifestError, match="case-insensitive duplicate"):
        normalize_manifest(payload)

    payload = _manifest(tmp_path / "unstable")
    _add_replay_artifacts(payload, tmp_path / "unstable-replay")
    manifest_module = __import__(
        "scripts.qualification.execution_evidence.manifest",
        fromlist=["stable_sha256"],
    )
    original_stable_sha256 = manifest_module.stable_sha256

    def unstable_replay(path: Path):
        if path.name.casefold().endswith(".hdf"):
            raise SnapshotError("changed")
        return original_stable_sha256(path)

    monkeypatch.setattr(
        manifest_module,
        "stable_sha256",
        unstable_replay,
    )
    with pytest.raises(ManifestError, match="changed or is linked"):
        normalize_manifest(payload)


def test_expected_failure_reason_is_exactly_scoped(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["lanes"][0]["expected_terminal_category"] = "expected_failure"
    with pytest.raises(ManifestError, match="expected_failure_reason_code"):
        normalize_manifest(payload)
    payload["lanes"][0]["expected_failure_reason_code"] = (
        "legacy_output_timestamp_after_hdf"
    )
    normalized = normalize_manifest(payload)
    assert normalized["lanes"][0]["expected_failure_reason_code"] == (
        "legacy_output_timestamp_after_hdf"
    )

    payload["lanes"][0]["expected_terminal_category"] = "passed"
    with pytest.raises(ManifestError, match="valid only"):
        normalize_manifest(payload)


def test_replay_root_and_files_must_have_plain_ancestry(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    real_root = tmp_path / "real-replay"
    _add_replay_artifacts(payload, real_root)
    alias_root = tmp_path / "replay-alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    payload["fixtures"][0]["replay_artifacts"]["source_root"] = str(alias_root)
    with pytest.raises(ManifestError, match="plain directory"):
        normalize_manifest(payload)

    payload = _manifest(tmp_path / "linked-file")
    replay_root = tmp_path / "linked-file-replay"
    replay_root.mkdir()
    target = replay_root / "target.bin"
    target.write_bytes(b"target")
    linked = replay_root / "Model.p01.hdf"
    linked.symlink_to(target)
    info = target.stat()
    payload["fixtures"][0]["replay_artifacts"] = {
        "source_root": str(replay_root),
        "data_origin": "staged_execution_output",
        "files": [
            {
                "relative_path": linked.name,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "size_bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
            }
        ],
    }
    with pytest.raises(ManifestError, match="linked"):
        normalize_manifest(payload)


@pytest.mark.parametrize(
    "path_field",
    ["repository", "source_project", "archive_root", "execution_root"],
)
def test_manifest_roots_reject_lexical_directory_aliases(
    tmp_path: Path,
    path_field: str,
) -> None:
    payload = _manifest(tmp_path)
    if path_field == "repository":
        target = Path(payload["repository"]["root"])
        alias = tmp_path / "repository-alias"
    elif path_field == "source_project":
        source = Path(payload["fixtures"][0]["source_project"])
        target = source.parent
        alias = tmp_path / "source-alias"
    else:
        target = tmp_path / f"{path_field}-target"
        target.mkdir()
        alias = tmp_path / f"{path_field}-alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    if path_field == "repository":
        payload["repository"]["root"] = str(alias)
    elif path_field == "source_project":
        payload["fixtures"][0]["source_project"] = str(alias / source.name)
    else:
        payload[path_field] = str(alias)

    with pytest.raises(ManifestError, match="not a plain"):
        normalize_manifest(payload)


def test_manifest_absolute_paths_reject_parent_traversal(tmp_path: Path) -> None:
    payload = _manifest(tmp_path)
    payload["archive_root"] = str(tmp_path / "unused" / ".." / "archive")
    with pytest.raises(ManifestError, match="parent traversal"):
        normalize_manifest(payload)


@pytest.mark.parametrize(
    "overlap_kind",
    ["same_root", "replay_under_source", "source_under_replay"],
)
def test_replay_root_must_be_disjoint_from_source_project_tree(
    tmp_path: Path,
    overlap_kind: str,
) -> None:
    payload = _manifest(tmp_path)
    source_parent = Path(payload["fixtures"][0]["source_project"]).parent
    if overlap_kind == "same_root":
        replay_root = source_parent
    elif overlap_kind == "replay_under_source":
        replay_root = source_parent / "archived-results"
    else:
        replay_root = source_parent.parent
    _add_replay_artifacts(payload, replay_root)

    with pytest.raises(ManifestError, match="must be disjoint"):
        normalize_manifest(payload)
