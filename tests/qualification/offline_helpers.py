from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.qualification.execution_evidence.snapshots import snapshot_tree


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def make_clean_runtime_repo(tmp_path: Path) -> tuple[Path, str]:
    source_repo = Path(__file__).resolve().parents[2]
    runtime_repo = tmp_path / "runtime-repo"
    runtime_repo.mkdir()
    shutil.copytree(
        source_repo / "ras_commander",
        runtime_repo / "ras_commander",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    qualification_target = runtime_repo / "scripts" / "qualification"
    qualification_target.parent.mkdir()
    shutil.copytree(
        source_repo / "scripts" / "qualification",
        qualification_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _run(["git", "init", "-q", str(runtime_repo)])
    _run(["git", "-C", str(runtime_repo), "config", "user.email", "test@example.test"])
    _run(["git", "-C", str(runtime_repo), "config", "user.name", "Qualification Test"])
    _run(["git", "-C", str(runtime_repo), "add", "ras_commander", "scripts"])
    _run(["git", "-C", str(runtime_repo), "commit", "-q", "-m", "pinned runtime"])
    head = _run(["git", "-C", str(runtime_repo), "rev-parse", "HEAD"]).stdout.strip()
    return runtime_repo, head


def make_captured_legacy_project(root: Path) -> Path:
    root.mkdir()
    project = root / "Model.prj"
    project.write_text(
        "Proj Title=Captured Legacy\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.p01").write_text(
        "Plan Title=Base\n"
        "Program Version=4.10\n"
        "Short Identifier=Base\n"
        "Simulation Date=01JAN2020,0000,02JAN2020,2400\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Model.g01").write_text(
        "Geom Title=Captured Geometry\n",
        encoding="ascii",
    )
    (root / "Model.f01").write_text(
        "Flow Title=Captured Steady Flow\n",
        encoding="ascii",
    )
    return project


def make_captured_legacy_replay(root: Path) -> Path:
    root.mkdir()
    (root / "Model.O01").write_bytes(b"captured legacy steady output\r\n")
    (root / "Model.p01.comp_msgs.txt").write_text(
        "Steady Flow Simulation Version 4.1.0 Jan 2010\r\n"
        "Computations Summary\r\n"
        "Computation Task\tTime(hh:mm:ss)\r\n"
        "Complete Process\t1.44\r\n",
        encoding="ascii",
        newline="",
    )
    return root


def make_unresolved_mixed_project(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    project = root / "Mixed.prj"
    project.write_text(
        "Proj Title=Captured Mixed\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Mixed.p01").write_text(
        "Plan Title=Mixed\n"
        "Short Identifier=Mixed\n"
        "Geom File=g01\n"
        "Flow File=f01\n",
        encoding="ascii",
    )
    (root / "Mixed.g01").write_text("Geom Title=Mixed\n", encoding="ascii")
    (root / "Mixed.f01").write_text("Flow Title=Mixed\n", encoding="ascii")
    replay_root = root.parent / "mixed-replay"
    replay_root.mkdir()
    (replay_root / "Mixed.p01.hdf").write_bytes(b"captured opaque hdf bytes")
    (replay_root / "Mixed.O01").write_bytes(b"captured legacy bytes")
    return project, replay_root


def _pinned_file(path: Path, root: Path) -> dict[str, object]:
    info = path.stat()
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }


def pinned_replay_files(root: Path) -> list[dict[str, object]]:
    return [_pinned_file(path, root) for path in sorted(root.iterdir())]


def make_offline_manifest(
    tmp_path: Path,
    *,
    runtime_repo: Path,
    head: str,
    source_project: Path,
    replay_root: Path,
) -> Path:
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    executable = engine_dir / "Ras.exe"
    executable.write_bytes(b"pinned but never executed")
    source_snapshot = snapshot_tree(
        source_project.parent,
        run_id="offline-manifest",
        lane_id="offline-manifest",
        attempt_id="offline-manifest",
        phase="source_manifest_pin",
        root_kind="source",
        data_origin="captured_real",
    )
    payload = {
        "schema_version": 1,
        "run_name": "offline-process-test",
        "repository": {
            "root": str(runtime_repo),
            "required_head": head,
            "require_clean": True,
            "bind_running_code": True,
        },
        "archive_root": str(tmp_path / "archive"),
        "execution_root": str(tmp_path / "execution"),
        "defaults": {
            "timeout_seconds": 30,
            "termination_grace_seconds": 5,
            "hash_files": True,
            "real_engine_jobs": 1,
        },
        "fixtures": [
            {
                "fixture_id": "captured-legacy",
                "source_kind": "project_file",
                "source_project": str(source_project),
                "source_immutable": True,
                "source_content_fingerprint_algorithm": (
                    source_snapshot.fingerprint_algorithm
                ),
                "source_content_fingerprint": source_snapshot.content_fingerprint,
                "data_origin": "captured_real",
                "replay_artifacts": {
                    "source_root": str(replay_root),
                    "data_origin": "staged_execution_output",
                    "files": pinned_replay_files(replay_root),
                },
                "plan_number": "01",
                "plan_title": "Base",
                "plan_type": "steady_1d",
            }
        ],
        "engines": [
            {
                "engine_id": "legacy-route",
                "execution_api": "ras_cmdr",
                "version_requested": "4.1",
                "expected_result_format": "legacy",
                "support_state": "supported",
                "executable": str(executable),
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        ],
        "lanes": [
            {
                "lane_id": "captured-legacy-41",
                "fixture_id": "captured-legacy",
                "engine_id": "legacy-route",
                "initial_state": "copied_preserved_times",
                "expected_terminal_category": "passed",
                "required_invariants": ["R01", "R03", "R11"],
                "tags": ["offline_evidence", "destructive_copy"],
            }
        ],
    }
    manifest = tmp_path / "offline-manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest


def runtime_environment(runtime_repo: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(runtime_repo)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_offline_cli(
    runtime_repo: Path,
    *arguments: str,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.qualification.execution_evidence",
            *arguments,
        ],
        cwd=runtime_repo,
        env=runtime_environment(runtime_repo),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def last_json_line(output: str):
    lines = [line for line in output.splitlines() if line.strip()]
    return json.loads(lines[-1])


__all__ = [
    "last_json_line",
    "make_captured_legacy_project",
    "make_captured_legacy_replay",
    "make_unresolved_mixed_project",
    "make_clean_runtime_repo",
    "make_offline_manifest",
    "pinned_replay_files",
    "run_offline_cli",
    "runtime_environment",
]
