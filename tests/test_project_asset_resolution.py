from pathlib import Path

import pandas as pd
import pytest

from ras_commander.RasPrjAssets import RasPrjAssets, PlanAssets


class FakeRasProject:
    def __init__(self, project_folder: Path, project_name: str = "TestProject"):
        self.project_folder = Path(project_folder)
        self.project_name = project_name
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geometry_number": "02",
                    "Geom File": "g02",
                    "Geom Path": str(self.project_folder / f"{project_name}.g02"),
                    "Flow Path": str(self.project_folder / f"{project_name}.u01"),
                    "full_path": str(self.project_folder / f"{project_name}.p01"),
                    "HDF_Results_Path": str(self.project_folder / f"{project_name}.p01.hdf"),
                },
                {
                    "plan_number": "03",
                    "geometry_number": "04",
                    "Geom File": "g04",
                    "Geom Path": str(self.project_folder / f"{project_name}.g04"),
                    "Flow Path": None,
                    "full_path": str(self.project_folder / f"{project_name}.p03"),
                    "HDF_Results_Path": None,
                },
            ]
        )
        self.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "02",
                    "full_path": str(self.project_folder / f"{project_name}.g02"),
                    "hdf_path": str(self.project_folder / f"{project_name}.g02.hdf"),
                },
                {
                    "geom_number": "04",
                    "full_path": str(self.project_folder / f"{project_name}.g04"),
                    "hdf_path": str(self.project_folder / f"{project_name}.g04.hdf"),
                },
            ]
        )

    def check_initialized(self):
        return None


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_normalize_number_accepts_numbers_prefixes_and_paths(tmp_path):
    assert RasPrjAssets.normalize_number("1") == "01"
    assert RasPrjAssets.normalize_number("01") == "01"
    assert RasPrjAssets.normalize_number(1) == "01"
    assert RasPrjAssets.normalize_number(1.0) == "01"
    assert RasPrjAssets.normalize_number("p03", prefix="p") == "03"
    assert RasPrjAssets.normalize_number("g04", prefix="g") == "04"
    assert RasPrjAssets.normalize_number(tmp_path / "TestProject.p05", prefix="p") == "05"


def test_normalize_number_rejects_invalid_values():
    with pytest.raises(ValueError):
        RasPrjAssets.normalize_number("p00", prefix="p")
    with pytest.raises(ValueError):
        RasPrjAssets.normalize_number("abc", prefix="p")


def test_extract_number_handles_optional_metadata():
    assert RasPrjAssets.extract_number(None, prefix="p") is None
    assert RasPrjAssets.extract_number("none", prefix="p") is None
    assert RasPrjAssets.extract_number("Project.g03.hdf", prefix="g") == "03"
    assert RasPrjAssets.extract_number(Path("Project.p07.hdf"), prefix="p") == "07"
    assert RasPrjAssets.extract_number("g04", prefix="g") == "04"
    assert RasPrjAssets.extract_number("04", prefix="g") == "04"
    assert RasPrjAssets.extract_number("not-a-number", prefix="g") is None


def test_plan_results_hdf_uses_plan_df_path(tmp_path):
    ras = FakeRasProject(tmp_path)
    expected = _touch(tmp_path / "TestProject.p01.hdf")

    assert RasPrjAssets.plan_results_hdf("01", ras_object=ras) == expected
    assert RasPrjAssets.plan_results_hdf("p01", ras_object=ras) == expected


def test_plan_results_hdf_can_return_expected_missing_path(tmp_path):
    ras = FakeRasProject(tmp_path)

    assert RasPrjAssets.plan_results_hdf("03", ras_object=ras) is None
    assert (
        RasPrjAssets.plan_results_hdf("03", ras_object=ras, must_exist=False)
        == tmp_path / "TestProject.p03.hdf"
    )


def test_geometry_hdf_bare_number_keeps_plan_selector_behavior(tmp_path):
    ras = FakeRasProject(tmp_path)
    expected = _touch(tmp_path / "TestProject.g02.hdf")

    assert RasPrjAssets.geometry_hdf("01", ras_object=ras) == expected
    assert RasPrjAssets.geometry_hdf(1, ras_object=ras) == expected


def test_geometry_hdf_supports_explicit_geometry_selector(tmp_path):
    ras = FakeRasProject(tmp_path)
    expected = _touch(tmp_path / "TestProject.g04.hdf")

    assert RasPrjAssets.geometry_hdf("g04", ras_object=ras) == expected
    assert RasPrjAssets.geometry_hdf("04", ras_object=ras, selector_kind="geom") == expected


def test_plan_assets_returns_passive_container(tmp_path):
    ras = FakeRasProject(tmp_path)
    _touch(tmp_path / "TestProject.p01")
    _touch(tmp_path / "TestProject.p01.hdf")
    _touch(tmp_path / "TestProject.g02")
    _touch(tmp_path / "TestProject.g02.hdf")
    _touch(tmp_path / "TestProject.u01")

    assets = RasPrjAssets.plan_assets("01", ras_object=ras, must_exist=True)

    assert isinstance(assets, PlanAssets)
    assert assets.plan_number == "01"
    assert assets.plan_path == tmp_path / "TestProject.p01"
    assert assets.results_hdf_path == tmp_path / "TestProject.p01.hdf"
    assert assets.geometry_number == "02"
    assert assets.geometry_path == tmp_path / "TestProject.g02"
    assert assets.geometry_hdf_path == tmp_path / "TestProject.g02.hdf"
    assert assets.flow_path == tmp_path / "TestProject.u01"


def test_plan_assets_falls_back_to_plan_geom_path_when_geom_df_is_stale(tmp_path):
    ras = FakeRasProject(tmp_path)
    ras.geom_df = pd.DataFrame(columns=["geom_number", "full_path", "hdf_path"])

    assets = RasPrjAssets.plan_assets("01", ras_object=ras, must_exist=False)

    assert assets.geometry_path == tmp_path / "TestProject.g02"
    assert assets.geometry_hdf_path == tmp_path / "TestProject.g02.hdf"


def test_explicit_ras_object_keeps_multi_project_lookup_isolated(tmp_path):
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    ras_a = FakeRasProject(project_a, project_name="ProjectA")
    ras_b = FakeRasProject(project_b, project_name="ProjectB")
    hdf_a = _touch(project_a / "ProjectA.p01.hdf")
    hdf_b = _touch(project_b / "ProjectB.p01.hdf")

    assert RasPrjAssets.plan_results_hdf("01", ras_object=ras_a) == hdf_a
    assert RasPrjAssets.plan_results_hdf("01", ras_object=ras_b) == hdf_b
