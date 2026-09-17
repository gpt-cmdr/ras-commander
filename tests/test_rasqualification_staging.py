"""Tests for RasQualification.stage_project and project_tree_fingerprint.

Ported from the c05a-mesh-depth qualification tests (tests/test_rasqualification.py)
for the minimal staging surface carried on main, plus the call shapes used by
fim-commander's clone-only steady boundary adapter.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ras_commander import RasQualification, RasUtils


def _write_minimal_project(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "Fixture.prj").write_text(
        "Proj Title=Qualification Fixture\nCurrent Plan=p01\nPlan File=p01\n",
        encoding="utf-8",
    )
    (folder / "Fixture.p01").write_text(
        "Plan Title=Qualification\nProgram Version=7.01\nGeom File=g01\nFlow File=u01\n",
        encoding="utf-8",
    )
    (folder / "Fixture.g01").write_text("Geom Title=Qualification\n", encoding="utf-8")
    return folder


def test_project_tree_fingerprint_is_stable_and_content_sensitive(tmp_path):
    project = _write_minimal_project(tmp_path / "project")
    first = RasQualification.project_tree_fingerprint(project)

    assert isinstance(first, str)
    assert len(first) == 64
    assert RasQualification.project_tree_fingerprint(str(project)) == first

    (project / "Fixture.g01").write_text("Geom Title=Changed\n", encoding="utf-8")
    changed = RasQualification.project_tree_fingerprint(project)
    assert changed != first

    (project / "Fixture.g01").write_text("Geom Title=Qualification\n", encoding="utf-8")
    assert RasQualification.project_tree_fingerprint(project) == first

    (project / "Fixture.g01").rename(project / "Fixture.g02")
    assert RasQualification.project_tree_fingerprint(project) != first


def test_project_tree_fingerprint_ignores_runner_lock_and_includes_subfolders(tmp_path):
    project = _write_minimal_project(tmp_path / "project")
    before = RasQualification.project_tree_fingerprint(project)

    (project / RasQualification.PROJECT_LOCK_NAME).write_text("token", encoding="utf-8")
    assert RasQualification.project_tree_fingerprint(project) == before

    (project / "Terrain").mkdir()
    (project / "Terrain" / "Terrain.vrt").write_text("<VRTDataset/>", encoding="utf-8")
    assert RasQualification.project_tree_fingerprint(project) != before


def test_project_tree_fingerprint_rejects_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="Project folder not found"):
        RasQualification.project_tree_fingerprint(tmp_path / "missing")


def test_stage_project_preserves_content_and_exercises_spaces_and_long_paths(tmp_path):
    source = _write_minimal_project(tmp_path / "source")
    spaces = RasQualification.stage_project(source, tmp_path / "runs", "spaces", "spaces")
    long_path = RasQualification.stage_project(
        source,
        tmp_path / "runs",
        "long",
        "long",
        minimum_long_path=180,
    )

    assert spaces["content_matches"] is True
    assert " " in spaces["destination"]
    assert long_path["content_matches"] is True
    assert long_path["path_length"] >= 180
    assert (source / "Fixture.prj").read_text(encoding="utf-8").startswith("Proj Title=")


def test_stage_project_excludes_transient_runner_lock(tmp_path):
    source = _write_minimal_project(tmp_path / "locked-source")
    source_fingerprint = RasQualification.project_tree_fingerprint(source)
    (source / RasQualification.PROJECT_LOCK_NAME).write_text("owner", encoding="utf-8")

    stage = RasQualification.stage_project(source, tmp_path / "runs", "locked-copy")

    destination = Path(stage["destination"])
    assert stage["source_fingerprint"] == source_fingerprint
    assert stage["destination_fingerprint"] == source_fingerprint
    assert stage["transient_lock"]["source_present_during_stage"] is True
    assert stage["transient_lock"]["excluded"] is True
    assert not (destination / RasQualification.PROJECT_LOCK_NAME).exists()
    assert (source / RasQualification.PROJECT_LOCK_NAME).exists()


def test_stage_project_makes_only_the_isolated_read_only_fixture_copy_writable(
    tmp_path,
):
    source = _write_minimal_project(tmp_path / "read-only-source")
    source_file = source / "Fixture.prj"
    original_source_mode = source.stat().st_mode
    original_file_mode = source_file.stat().st_mode
    source_file.chmod(original_file_mode & ~stat.S_IWUSR)
    source.chmod(original_source_mode & ~stat.S_IWUSR)

    try:
        stage = RasQualification.stage_project(
            source,
            tmp_path / "runs",
            "read-only-copy",
        )
        destination = Path(stage["destination"])
        destination_file = destination / source_file.name

        assert source_file.stat().st_mode & stat.S_IWUSR == 0
        if os.name != "nt":
            # Windows does not persist a read-only bit on directories.
            assert source.stat().st_mode & stat.S_IWUSR == 0
        assert destination.stat().st_mode & stat.S_IWUSR
        assert destination_file.stat().st_mode & stat.S_IWUSR
        assert stage["writable_clone"] == {
            "normalized": True,
            "owner_write_verified": True,
            "directory_count": 1,
            "file_count": 3,
            "source_permissions_unchanged": True,
        }
        destination_file.write_text("Proj Title=Edited clone\n", encoding="utf-8")
        assert source_file.read_text(encoding="utf-8").startswith(
            "Proj Title=Qualification Fixture"
        )
    finally:
        source.chmod(original_source_mode | stat.S_IWUSR)
        source_file.chmod(original_file_mode | stat.S_IWUSR)


def test_stage_project_uses_mapped_drive_safe_resolution(tmp_path, monkeypatch):
    source = _write_minimal_project(tmp_path / "source")
    workspace = tmp_path / "workspace"
    resolved = []

    def safe_resolve(path):
        resolved.append(Path(path))
        return Path(path).absolute()

    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(safe_resolve))
    stage = RasQualification.stage_project(source, workspace, task_id="mapped-drive")

    assert resolved == [source, workspace]
    assert Path(stage["destination"]).drive == Path(workspace.absolute()).drive
    assert stage["content_matches"] is True


def test_stage_project_rejects_missing_source_prj_and_bad_variant(tmp_path):
    with pytest.raises(FileNotFoundError):
        RasQualification.stage_project(tmp_path / "missing", tmp_path / "runs")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No HEC-RAS .prj"):
        RasQualification.stage_project(empty, tmp_path / "runs")
    source = _write_minimal_project(tmp_path / "source")
    with pytest.raises(ValueError, match="path_variant"):
        RasQualification.stage_project(source, tmp_path / "runs", path_variant="bogus")


def test_fim_commander_clone_only_boundary_call_shape(tmp_path):
    """Mirror fim_commander.adapters.ras_steady_boundary's use of the API."""
    from ras_commander import (  # noqa: F401 - the adapter's exact import list
        RasPlan,
        RasPrj,
        RasQualification as ImportedQualification,
        RasSteady,
        init_ras_project,
    )

    source_project = _write_minimal_project(tmp_path / "source") / "Fixture.prj"
    workspace = tmp_path / "workspace"
    task_id = "ble steady/boundary 001"

    source_before = ImportedQualification.project_tree_fingerprint(source_project.parent)
    stage = ImportedQualification.stage_project(
        source_project.parent,
        workspace,
        task_id=task_id,
    )
    clone_folder = Path(stage.get("destination", "")).resolve()
    clone_project = Path(stage.get("project_file", "")).resolve()

    assert clone_project.name.casefold() == source_project.name.casefold()
    assert clone_project.is_file()
    assert clone_project.is_relative_to(clone_folder)
    assert clone_folder.is_relative_to(workspace.resolve())
    assert "ble-steady-boundary-001" in clone_folder.parent.name

    (clone_project.parent / "Fixture.f01").write_text("Flow Title=Clone only\n")
    source_after = ImportedQualification.project_tree_fingerprint(source_project.parent)
    assert source_before == source_after
