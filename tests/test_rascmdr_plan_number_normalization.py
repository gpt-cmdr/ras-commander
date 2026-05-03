import importlib
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeResult


rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
RasCmdr = rascmdr_module.RasCmdr


class FakeRasProject:
    DEFAULT_PLAN_NUMBERS = ["01", "02", "03"]

    def __init__(self, project_folder=None, plan_numbers=None):
        self.project_name = "TestProject"
        self.ras_exe_path = Path("C:/HEC-RAS/6.6/Ras.exe")
        self._plan_numbers = list(plan_numbers or self.DEFAULT_PLAN_NUMBERS)
        self.project_folder = (
            Path(project_folder) if project_folder is not None else Path.cwd()
        )
        self.prj_file = self.project_folder / f"{self.project_name}.prj"
        self.plan_df = self.get_plan_entries()
        self.geom_df = pd.DataFrame(columns=["geom_number"])
        self.flow_df = pd.DataFrame(columns=["flow_number"])
        self.unsteady_df = pd.DataFrame(columns=["unsteady_number"])
        self.results_df = pd.DataFrame(columns=["plan_number", "status"])

    def check_initialized(self):
        return None

    def initialize(self, project_folder, ras_exe_path):
        self.project_folder = Path(project_folder)
        self.ras_exe_path = ras_exe_path
        self.prj_file = self.project_folder / f"{self.project_name}.prj"
        self.plan_df = self.get_plan_entries()

    def get_plan_entries(self):
        return pd.DataFrame(
            {
                "plan_number": self._plan_numbers,
                "geometry_number": ["01"] * len(self._plan_numbers),
                "Geom File": ["01"] * len(self._plan_numbers),
            }
        )

    def get_geom_entries(self):
        return pd.DataFrame(columns=["geom_number"])

    def get_flow_entries(self):
        return pd.DataFrame(columns=["flow_number"])

    def get_unsteady_entries(self):
        return pd.DataFrame(columns=["unsteady_number"])

    def update_results_df(self, plan_numbers=None):
        plan_numbers = [] if plan_numbers is None else list(plan_numbers)
        self.results_df = pd.DataFrame(
            {
                "plan_number": plan_numbers,
                "status": ["done"] * len(plan_numbers),
            }
        )

    def close(self):
        return None


def fake_init_ras_project(ras_project_folder, ras_version, ras_object):
    ras_object.initialize(ras_project_folder, ras_version)
    return ras_object


def _write_old_file(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(path, (old_time, old_time))


def _seed_parallel_project(project_folder: Path) -> None:
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    for plan_number in ["01", "02"]:
        _write_old_file(
            project_folder / f"TestProject.p{plan_number}",
            f"stale plan {plan_number}\n",
        )
        _write_old_file(
            project_folder / f"TestProject.p{plan_number}.hdf",
            f"stale hdf {plan_number}\n",
        )
    _write_old_file(
        project_folder / "TestProject.g01.hdf",
        "stale geometry\n",
    )


def test_normalize_requested_plan_numbers_returns_two_digit_strings():
    assert RasCmdr._normalize_requested_plan_numbers([1, "2", 3.0]) == [
        "01",
        "02",
        "03",
    ]
    assert RasCmdr._normalize_requested_plan_numbers("4") == ["04"]


def test_compute_parallel_normalizes_list_plan_numbers_before_filtering(
    monkeypatch, tmp_path
):
    project_folder = tmp_path / "parallel-project"
    project_folder.mkdir()
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    ras_object = FakeRasProject(project_folder=project_folder)
    executed_plans = []

    def fake_compute_plan(plan_number, **kwargs):
        executed_plans.append(plan_number)
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(rascmdr_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_parallel(
        plan_number=[1, 2],
        max_workers=1,
        ras_object=ras_object,
    )

    assert executed_plans == ["01", "02"]
    assert result.execution_results == {"01": True, "02": True}
    assert result.results_df["plan_number"].tolist() == ["01", "02"]
    assert ras_object.plan_df["plan_number"].tolist() == ["01", "02", "03"]


def test_compute_test_mode_normalizes_list_plan_numbers_before_filtering(
    monkeypatch, tmp_path
):
    project_folder = tmp_path / "test-mode-project"
    project_folder.mkdir()
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    ras_object = FakeRasProject(project_folder=project_folder)
    executed_plans = []

    def fake_compute_plan(plan_number, **kwargs):
        executed_plans.append(plan_number)
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_test_mode(
        plan_number=[1, "2"],
        dest_folder_suffix="[Normalized]",
        ras_object=ras_object,
    )

    assert executed_plans == ["01", "02"]
    assert result.execution_results == {"01": True, "02": True}
    assert result.results_df["plan_number"].tolist() == ["01", "02"]


def test_compute_parallel_does_not_let_later_worker_overwrite_fresh_outputs(
    monkeypatch, tmp_path
):
    project_folder = tmp_path / "parallel-project"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01", "02"],
    )

    def fake_compute_plan(plan_number, **kwargs):
        worker_folder = Path(kwargs["ras_object"].project_folder)
        (worker_folder / f"TestProject.p{plan_number}").write_text(
            f"fresh plan {plan_number}\n",
            encoding="utf-8",
        )
        (worker_folder / f"TestProject.p{plan_number}.hdf").write_text(
            f"fresh hdf {plan_number}\n",
            encoding="utf-8",
        )
        (worker_folder / f"TestProject.p{plan_number}.computeMsgs.txt").write_text(
            f"compute messages {plan_number}\n",
            encoding="utf-8",
        )
        if plan_number == "01":
            (worker_folder / "TestProject.g01.hdf").write_text(
                "fresh geometry\n",
                encoding="utf-8",
            )
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(rascmdr_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_parallel(
        plan_number=["01", "02"],
        max_workers=2,
        ras_object=ras_object,
    )

    assert result.execution_results == {"01": True, "02": True}
    assert (project_folder / "TestProject.p01.hdf").read_text(encoding="utf-8") == (
        "fresh hdf 01\n"
    )
    assert (project_folder / "TestProject.p01").read_text(encoding="utf-8") == (
        "fresh plan 01\n"
    )
    assert (project_folder / "TestProject.g01.hdf").read_text(encoding="utf-8") == (
        "fresh geometry\n"
    )
    assert (project_folder / "TestProject.p02.hdf").read_text(encoding="utf-8") == (
        "fresh hdf 02\n"
    )


def test_compute_parallel_dest_folder_keeps_fresh_outputs_when_workers_share_stale_seed(
    monkeypatch, tmp_path
):
    project_folder = tmp_path / "parallel-project"
    project_folder.mkdir()
    _seed_parallel_project(project_folder)
    ras_object = FakeRasProject(
        project_folder=project_folder,
        plan_numbers=["01", "02"],
    )
    dest_folder = tmp_path / "parallel-results"

    def fake_compute_plan(plan_number, **kwargs):
        worker_folder = Path(kwargs["ras_object"].project_folder)
        (worker_folder / f"TestProject.p{plan_number}").write_text(
            f"fresh plan {plan_number}\n",
            encoding="utf-8",
        )
        (worker_folder / f"TestProject.p{plan_number}.hdf").write_text(
            f"fresh hdf {plan_number}\n",
            encoding="utf-8",
        )
        if plan_number == "01":
            (worker_folder / "TestProject.g01.hdf").write_text(
                "fresh geometry\n",
                encoding="utf-8",
            )
        return ComputeResult(success=True)

    monkeypatch.setattr(rascmdr_module, "RasPrj", FakeRasProject)
    monkeypatch.setattr(rascmdr_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(rascmdr_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(RasCmdr, "compute_plan", staticmethod(fake_compute_plan))

    result = RasCmdr.compute_parallel(
        plan_number=["01", "02"],
        max_workers=2,
        ras_object=ras_object,
        dest_folder=dest_folder,
    )

    assert result.execution_results == {"01": True, "02": True}
    assert (dest_folder / "TestProject.p01.hdf").read_text(encoding="utf-8") == (
        "fresh hdf 01\n"
    )
    assert (dest_folder / "TestProject.p01").read_text(encoding="utf-8") == (
        "fresh plan 01\n"
    )
    assert (dest_folder / "TestProject.g01.hdf").read_text(encoding="utf-8") == (
        "fresh geometry\n"
    )
    assert (dest_folder / "TestProject.p02.hdf").read_text(encoding="utf-8") == (
        "fresh hdf 02\n"
    )


def test_filter_plan_entries_none_returns_all_plans():
    plan_entries = pd.DataFrame({"plan_number": ["01", "02", "03"]})
    result = RasCmdr._filter_plan_entries(plan_entries, None)
    assert result["plan_number"].tolist() == ["01", "02", "03"]


def test_filter_plan_entries_zero_raises():
    plan_entries = pd.DataFrame({"plan_number": ["01", "02"]})
    with pytest.raises(ValueError):
        RasCmdr._filter_plan_entries(plan_entries, 0)


def test_filter_plan_entries_empty_string_raises():
    plan_entries = pd.DataFrame({"plan_number": ["01", "02"]})
    with pytest.raises(ValueError):
        RasCmdr._filter_plan_entries(plan_entries, "")


def test_filter_plan_entries_empty_list_returns_empty():
    plan_entries = pd.DataFrame({"plan_number": ["01", "02"]})
    result = RasCmdr._filter_plan_entries(plan_entries, [])
    assert result.empty
