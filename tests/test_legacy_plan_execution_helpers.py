from pathlib import Path

import pandas as pd

from ras_commander.RasUtils import RasUtils
from ras_commander.RasPrj import get_ras_exe
from ras_commander.geom.GeomPreprocessor import GeomPreprocessor


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "TestProject"
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "17",
                    "geometry_number": "05",
                }
            ]
        )
        self.geom_df = None

    def check_initialized(self):
        return None

    def get_geom_entries(self):
        return self.plan_df.copy()


def test_get_ras_exe_normalizes_legacy_dotted_versions(monkeypatch):
    fake_exe = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\5.0.3\Ras.exe")

    monkeypatch.setattr(
        RasUtils,
        "discover_ras_versions",
        staticmethod(lambda: {"5.0.3": fake_exe}),
    )

    assert get_ras_exe("5.03") == str(fake_exe)


def test_get_ras_exe_keeps_compact_66_mapped_to_66(monkeypatch):
    fake_66 = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe")
    fake_70 = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe")

    monkeypatch.setattr(
        RasUtils,
        "discover_ras_versions",
        staticmethod(lambda: {"6.6": fake_66, "7.0": fake_70}),
    )

    assert get_ras_exe("66") == str(fake_66)


def test_get_ras_exe_maps_new_orleans_670_plan_version(monkeypatch):
    fake_67 = Path(r"C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5\Ras.exe")

    monkeypatch.setattr(
        RasUtils,
        "discover_ras_versions",
        staticmethod(lambda: {"6.7 Beta 5": fake_67}),
    )

    assert get_ras_exe("6.70") == str(fake_67)


def test_normalize_ras_number_accepts_prefixed_strings_and_filenames():
    assert RasUtils.normalize_ras_number("p01") == "01"
    assert RasUtils.normalize_ras_number(".g07") == "07"
    assert RasUtils.normalize_ras_number("Model.u12") == "12"


def test_clear_geompre_files_uses_geometry_number_from_plan_df(tmp_path):
    project = _FakeRasProject(tmp_path)
    plan_path = tmp_path / "TestProject.p17"
    plan_path.write_text("Plan Title=Legacy Test\n")

    geom_preprocessor = tmp_path / "TestProject.c05"
    geom_preprocessor.write_text("preprocessor\n")

    GeomPreprocessor.clear_geompre_files(plan_path, ras_object=project)

    assert not geom_preprocessor.exists()
