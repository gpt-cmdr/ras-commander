"""find_valid_ras_folders: nested projects are pruned by default, kept on request.

The walk stops at the first valid HEC-RAS project so that backup copies kept in
subfolders of a working model ("Backup/", "Old/") are not counted as separate
projects. Delivered corpora such as FEMA eBFE nest real projects inside others,
so ``include_nested=True`` opts back in to descending.
"""

from pathlib import Path

from ras_commander import RasUtils


def _write_project(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.prj").write_text(
        f"Proj Title={name}\nCurrent Plan=p01\n", encoding="utf-8"
    )
    (folder / f"{name}.p01").write_text(
        f"Plan Title={name} plan\nProgram Version=6.60\n", encoding="utf-8"
    )


def test_nested_project_pruned_by_default_and_found_when_requested(tmp_path):
    parent = tmp_path / "ParentModel"
    _write_project(parent, "Parent")
    _write_project(parent / "Backup", "ParentBackup")

    default_found = RasUtils.find_valid_ras_folders(tmp_path)
    assert default_found == [parent]

    nested_found = RasUtils.find_valid_ras_folders(tmp_path, include_nested=True)
    assert sorted(nested_found) == sorted([parent, parent / "Backup"])


def test_include_nested_returns_project_info_for_both_levels(tmp_path):
    parent = tmp_path / "ParentModel"
    _write_project(parent, "Parent")
    _write_project(parent / "Backup", "ParentBackup")

    info = RasUtils.find_valid_ras_folders(
        tmp_path, return_project_info=True, include_nested=True
    )
    assert sorted(item["project_name"] for item in info) == ["Parent", "ParentBackup"]
    assert all(item["plan_count"] == 1 for item in info)
