from pathlib import Path

import pandas as pd

from ras_commander.RasComputeState import RasComputeState
from ras_commander.RasModPuls import RasModPuls
from ras_commander.check import _utils as check_utils
from ras_commander.hdf.HdfChannelCapacity import HdfChannelCapacity


class FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.folder = self.project_folder
        self.project_name = "TestProject"
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "Geom File": "g02",
                    "Geom Path": str(self.project_folder / "TestProject.g02"),
                    "Flow Path": str(self.project_folder / "TestProject.u01"),
                    "full_path": str(self.project_folder / "TestProject.p01"),
                    "HDF_Results_Path": str(self.project_folder / "TestProject.p01.hdf"),
                }
            ]
        )
        self.geom_df = pd.DataFrame(
            [
                {
                    "geom_number": "01",
                    "full_path": str(self.project_folder / "TestProject.g01"),
                    "hdf_path": str(self.project_folder / "TestProject.g01.hdf"),
                },
                {
                    "geom_number": "02",
                    "full_path": str(self.project_folder / "TestProject.g02"),
                    "hdf_path": str(self.project_folder / "TestProject.g02.hdf"),
                },
            ]
        )

    def check_initialized(self):
        return None


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_compute_state_get_plan_input_files_uses_shared_assets(tmp_path):
    ras = FakeRasProject(tmp_path)

    files = RasComputeState.get_plan_input_files("p01", ras)

    assert files == {
        "plan": tmp_path / "TestProject.p01",
        "geom": tmp_path / "TestProject.g02",
        "flow": tmp_path / "TestProject.u01",
    }


def test_check_utils_resolve_hdf_paths_uses_shared_plan_geometry_lookup(tmp_path):
    ras = FakeRasProject(tmp_path)
    plan_hdf = _touch(tmp_path / "TestProject.p01.hdf")
    geom_hdf = _touch(tmp_path / "TestProject.g02.hdf")

    assert check_utils.resolve_hdf_paths("p01", ras) == (plan_hdf, geom_hdf)


def test_check_utils_resolve_hdf_paths_falls_back_to_plan_hdf_for_embedded_geometry(tmp_path):
    ras = FakeRasProject(tmp_path)
    plan_hdf = _touch(tmp_path / "TestProject.p01.hdf")

    assert check_utils.resolve_hdf_paths("01", ras) == (plan_hdf, plan_hdf)


def test_modpuls_private_hdf_helpers_delegate_to_shared_assets(tmp_path):
    ras = FakeRasProject(tmp_path)
    plan_hdf = _touch(tmp_path / "TestProject.p01.hdf")
    geom_hdf = _touch(tmp_path / "TestProject.g02.hdf")

    assert RasModPuls._resolve_hdf_path("p01", ras) == plan_hdf
    assert RasModPuls._get_geom_hdf_path(plan_hdf, "p01", ras) == geom_hdf


def test_channel_capacity_distinguishes_plan_and_geometry_number_inputs(tmp_path):
    ras = FakeRasProject(tmp_path)

    assert (
        HdfChannelCapacity._standardize_hdf_input("01", "plan", ras)
        == tmp_path / "TestProject.p01.hdf"
    )
    assert (
        HdfChannelCapacity._standardize_hdf_input("01", "geometry", ras)
        == tmp_path / "TestProject.g01.hdf"
    )
    assert (
        HdfChannelCapacity._standardize_hdf_input("g02", "geometry", ras)
        == tmp_path / "TestProject.g02.hdf"
    )
