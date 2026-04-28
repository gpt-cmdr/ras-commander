from pathlib import Path

import pandas as pd
import pytest

from ras_commander.check._utils import resolve_hdf_paths


class FakeCheckRasProject:
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
                    "HDF_Results_Path": str(self.project_folder / "custom" / "Plan01.p01.hdf"),
                },
                {
                    "plan_number": "02",
                    "geometry_number": "03",
                    "Geom File": "g03",
                    "Geom Path": str(self.project_folder / f"{project_name}.g03"),
                    "HDF_Results_Path": str(self.project_folder / "custom" / "Plan02.p02.hdf"),
                },
            ]
        )
        self.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "02",
                    "full_path": str(self.project_folder / f"{project_name}.g02"),
                },
                {
                    "geom_number": "03",
                    "full_path": str(self.project_folder / f"{project_name}.g03"),
                },
            ]
        )


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_resolve_hdf_paths_uses_project_asset_resolution_for_plan_selectors(tmp_path):
    ras = FakeCheckRasProject(tmp_path)
    plan_hdf = _touch(tmp_path / "custom" / "Plan01.p01.hdf")
    geom_hdf = _touch(tmp_path / "TestProject.g02.hdf")

    assert resolve_hdf_paths("01", ras) == (plan_hdf, geom_hdf)
    assert resolve_hdf_paths("p01", ras) == (plan_hdf, geom_hdf)


def test_resolve_hdf_paths_falls_back_to_plan_hdf_when_geometry_hdf_missing(tmp_path):
    ras = FakeCheckRasProject(tmp_path)
    plan_hdf = _touch(tmp_path / "custom" / "Plan02.p02.hdf")

    assert resolve_hdf_paths("02", ras) == (plan_hdf, plan_hdf)


def test_resolve_hdf_paths_preserves_legacy_path_only_geometry_derivation(tmp_path):
    plan_hdf = _touch(tmp_path / "Model.p04.hdf")
    geom_hdf = _touch(tmp_path / "Model.g04.hdf")

    assert resolve_hdf_paths(plan_hdf, None) == (plan_hdf, geom_hdf)


def test_resolve_hdf_paths_reports_unknown_plan_numbers(tmp_path):
    ras = FakeCheckRasProject(tmp_path)

    with pytest.raises(ValueError, match="Plan '09' not found"):
        resolve_hdf_paths("09", ras)
