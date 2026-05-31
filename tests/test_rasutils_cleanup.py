from pathlib import Path
import shutil
import zipfile

import pandas as pd

from ras_commander.RasExamples import RasExamples
from ras_commander.RasUtils import RasUtils


def test_remove_with_retry_does_not_require_initialized_project(tmp_path):
    stale_worker = tmp_path / "AORC_900 [Worker 1]"
    stale_worker.mkdir()
    (stale_worker / "locked-after-hecras.txt").write_text("released", encoding="utf-8")

    assert RasUtils.remove_with_retry(stale_worker, ras_object=None)
    assert not stale_worker.exists()


def test_extract_project_reuses_retry_cleanup_for_existing_folder(tmp_path, monkeypatch):
    zip_path = tmp_path / "Example_Projects_7_0.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_ref:
        zip_ref.writestr("Category/FakeProject/FakeProject.prj", "Proj Title=FakeProject\n")

    existing_folder = tmp_path / "FakeProject_901"
    existing_folder.mkdir()
    (existing_folder / "old.prj").write_text("old", encoding="utf-8")

    removed_paths = []

    def fake_remove(path: Path, **kwargs) -> bool:
        removed_paths.append(Path(path))
        shutil.rmtree(path)
        return True

    monkeypatch.setattr(
        RasExamples,
        "_folder_df",
        pd.DataFrame([{"Category": "Category", "Project": "FakeProject"}]),
    )
    monkeypatch.setattr(RasExamples, "_zip_file_path", zip_path)
    monkeypatch.setattr(RasUtils, "remove_with_retry", staticmethod(fake_remove))

    extracted = RasExamples.extract_project("FakeProject", output_path=tmp_path, suffix="901")

    assert extracted == existing_folder
    assert removed_paths == [existing_folder]
    assert (existing_folder / "FakeProject.prj").exists()
